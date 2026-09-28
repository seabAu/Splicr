"""A local HTTP API over Narrator's existing modules.

This adds no capability. Every endpoint below is a thin call into
`session`, `tasks`, `render_config` or `components` -- the modules already
extracted from the Tk app. If an endpoint here ever needs logic of its
own, that logic belongs in one of those modules instead, where the
desktop app and the CLI can reach it too.

**Security.** This binds to localhost and requires a token, because
"local" is not the same as "safe": any page open in your browser, and
anything else on your machine, can make requests to 127.0.0.1. The API
can browse the filesystem and start processes, so it is protected the
same way a local Jupyter server is -- a token minted at startup and handed
to the frontend when it is served.
"""

import os
import secrets
import tempfile
import time

from . import components as components_mod
from . import library
from . import render_config
from . import session as session_mod
from . import tasks as tasks_mod
from . import audiogram as audiogram_mod
from .jobs import JobStore
from . import publish as publish_mod
from .config import (APP_DIR, default_output_root, load_podcast_settings,
                     load_settings, save_podcast_settings, save_settings,
                     unique_path)
from .audio import duration_of
from .pipeline import ENGINES

TOKEN = secrets.token_urlsafe(24)
STORE = JobStore()
SESSION = session_mod.Session()


def _engine_summary():
    out = []
    for name, spec in ENGINES.items():
        out.append({
            "name": name, "key": spec["key"],
            "installed": bool(spec["detect"]()),
            "editable": spec["editable"],
            "voices": [{"id": vid, "label": desc}
                      for vid, desc in spec["voices"]],
        })
    return out


def create_app(static_dir=None):
    from fastapi import (Depends, FastAPI, HTTPException, Header, Form,
                         UploadFile)
    from fastapi.responses import StreamingResponse
    from pydantic import BaseModel

    app = FastAPI(title="Narrator", version="2.1",
                  description="Local API for Narrator. Every endpoint is a "
                              "thin call into the same modules the desktop "
                              "app and CLI use.")

    def require_token(x_narrator_token: str = Header(default="")):
        # secrets.compare_digest, not ==, so a wrong token can't be found
        # a character at a time by timing the response.
        if not secrets.compare_digest(x_narrator_token, TOKEN):
            raise HTTPException(status_code=401, detail="Bad or missing token")
        return True

    auth = [Depends(require_token)]

    # --- what this installation can do -----------------------------------

    @app.get("/api/health")
    def health():
        """Deliberately unauthenticated: a client needs to know the server
        is up before it can prove who it is. Returns nothing sensitive."""
        return {"ok": True, "app": "narrator"}

    @app.get("/api/schema", dependencies=auth)
    def schema():
        """Every render setting, its type, allowed values and description.
        A settings form should be generated from this rather than written
        by hand -- that is the whole reason the schema exists."""
        return {"fields": render_config.describe(),
                "defaults": render_config.defaults()}

    @app.get("/api/engines", dependencies=auth)
    def engines():
        return {"engines": _engine_summary(),
                "output_root": default_output_root()}

    @app.get("/api/voices", dependencies=auth)
    def voices(engine: str = "", full: bool = False):
        """Saved designed/cloned voices, newest first. `engine` narrows
        the list to one engine's own voices (e.g. the dialogue editor's
        host pickers, where a Qwen3-cloned voice would fail if handed to
        Audio8 and vice versa) -- omit it to get everything, the way
        Voice studio's management view wants. `full=true` returns every
        field `saved_voices()` has (description, take, creation time,
        reference clip, CustomVoice speaker/instruct) for Voice studio's
        own list; the default is the trimmed {id, engine, kind, label}
        shape the dialogue voice pickers actually need."""
        from . import engines as engines_mod
        out = engines_mod.saved_voices()
        if engine:
            out = [v for v in out if v.get("engine", "qwen3") == engine]
        if full:
            return {"voices": [
                {**v, "has_reference": bool(v.get("reference"))
                     and os.path.isfile(v["reference"])}
                for v in out]}
        # `folder` is the actual string the render/signoff endpoints want
        # as a `voice` value (see DialogueRenderRequest) -- everything
        # else here is display-only. A custom-voice preset has no
        # folder; those aren't offered to the dialogue editor today
        # (it has no encode-custom-voice UI of its own), so they're
        # filtered out rather than sent as an unusable choice.
        out = [v for v in out if v["folder"]]
        return {"voices": [
            {"id": v["folder"], "engine": v.get("engine", "qwen3"),
             "kind": v["kind"],
             "label": (v["label"] or v["description"] or
                      os.path.basename(v["folder"]))}
            for v in out]}

    class RenameVoiceRequest(BaseModel):
        folder: str
        label: str

    @app.post("/api/voices/rename", dependencies=auth)
    def rename_voice_route(request: RenameVoiceRequest):
        from . import engines as engines_mod
        try:
            meta = engines_mod.rename_voice(request.folder, request.label)
        except Exception as exc:
            raise HTTPException(400, str(exc))
        return {"label": meta.get("label", "")}

    class DeleteVoiceRequest(BaseModel):
        folder: str

    @app.post("/api/voices/delete", dependencies=auth)
    def delete_voice_route(request: DeleteVoiceRequest):
        from . import engines as engines_mod
        try:
            engines_mod.delete_voice(request.folder)
        except Exception as exc:
            raise HTTPException(400, str(exc))
        return {"deleted": True}

    class AuditionRequest(BaseModel):
        description: str
        take: int = 1

    @app.post("/api/voices/audition", dependencies=auth)
    def audition_voice(request: AuditionRequest):
        """Design a Qwen3 voice from a description alone, without
        narrating a document -- a background job because designing (as
        opposed to reusing a cached voice) takes real time on first use,
        the same as it does on the desktop."""
        from . import engines as engines_mod
        if not request.description.strip():
            raise HTTPException(400, "Describe the voice first.")

        def work(job):
            ref, _ = engines_mod.ensure_qwen_voice(
                request.description, request.take, job.log)
            job.outcome = "designed -- reference clip ready"
            return {"reference": ref}

        job = STORE.start("audition", work,
                          label=request.description[:60],
                          detail={"take": request.take})
        return job.snapshot()

    @app.post("/api/voices/clone", dependencies=auth)
    async def clone_voice_route(
        transcript: str = Form(...), description: str = Form(""),
        engine: str = Form("qwen3"), file: UploadFile = None,
    ):
        """Clone a voice from an uploaded recording. Bytes come from the
        browser (not a server-side path, unlike the desktop's file
        picker) so this works even when the browser and the machine
        running Narrator aren't the same computer -- deliberately, since
        that's the point of a web interface the desktop version doesn't
        need to solve."""
        from . import engines as engines_mod
        if file is None:
            raise HTTPException(400, "No recording was uploaded.")
        min_seconds = 3.0 if engine == "audio8" else 2.0
        suffix = os.path.splitext(file.filename or "")[1] or ".wav"
        with tempfile.NamedTemporaryFile(suffix=suffix,
                                         delete=False) as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name
        try:
            folder = engines_mod.clone_voice_from_recording(
                tmp_path, transcript, description.strip() or "my own voice",
                print, engine_tag=engine, min_seconds=min_seconds)
        except Exception as exc:
            raise HTTPException(400, str(exc))
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        return {"folder": folder}

    @app.get("/api/voices/custom-speakers", dependencies=auth)
    def custom_speakers():
        from . import engines as engines_mod
        return {"speakers": engines_mod.qwen_custom_speakers()}

    @app.post("/api/voices/custom-speakers/fetch", dependencies=auth)
    def fetch_custom_speakers():
        """Downloads the CustomVoice model itself the first time (several
        GB) to read off its speaker list -- a background job for the
        same reason audition is: this can take a while and needs
        progress reported, not a request that just hangs."""
        from . import engines as engines_mod

        def work(job):
            speakers = engines_mod.fetch_qwen_custom_speakers(job.log)
            engines_mod.save_qwen_custom_speakers(speakers)
            job.outcome = f"{len(speakers)} speaker(s) found"
            return {"speakers": speakers}

        job = STORE.start("fetch-speakers", work, label="CustomVoice")
        return job.snapshot()

    class SavePresetRequest(BaseModel):
        label: str
        speaker: str
        instruct: str = ""

    @app.post("/api/voices/custom-preset", dependencies=auth)
    def save_preset(request: SavePresetRequest):
        from . import engines as engines_mod
        if not request.speaker.strip():
            raise HTTPException(400, "Choose a speaker first.")
        if not request.label.strip():
            raise HTTPException(400, "Give it a name to save it under.")
        engines_mod.save_custom_voice_preset(
            request.label.strip(), request.speaker.strip(),
            request.instruct)
        return {"saved": True}

    @app.post("/api/voices/custom-preset/delete", dependencies=auth)
    def delete_preset(request: RenameVoiceRequest):
        # Reuses RenameVoiceRequest's shape ({folder, label}) purely for
        # the label field; a preset has no folder, so `folder` is unused
        # here but kept so the client doesn't need a third request model
        # for what is, from the outside, "delete this named thing".
        from . import engines as engines_mod
        engines_mod.delete_custom_voice_preset(request.label)
        return {"deleted": True}

    @app.get("/api/voices/reference/{token}", dependencies=auth)
    def voice_reference(token: str):
        """Streams a saved voice's reference clip back for in-browser
        playback -- the desktop equivalent just opens the file with the
        OS's default player (reveal_file), which has no web analog."""
        from fastapi.responses import FileResponse
        from . import engines as engines_mod
        from .config import VOICES_DIR
        # `token` is the voice's folder name (not a full path) so this
        # can't be used to read an arbitrary file off disk -- resolved
        # against VOICES_DIR and checked to still be inside it.
        folder = os.path.join(VOICES_DIR, token)
        real = os.path.realpath(folder)
        if not real.startswith(os.path.realpath(VOICES_DIR) + os.sep):
            raise HTTPException(400, "Invalid voice reference.")
        ref = os.path.join(folder, "reference.wav")
        if not os.path.isfile(ref):
            raise HTTPException(404, "No reference clip for that voice.")
        return FileResponse(ref, media_type="audio/wav")

    # --- timeline: per-sentence view of a finished take -------------------

    def _load_take_or_404(manifest):
        from .segments import load_manifest
        if not os.path.isfile(manifest):
            raise HTTPException(404, f"No manifest at {manifest}")
        try:
            return load_manifest(manifest)
        except Exception as exc:
            raise HTTPException(400, f"Couldn't read that take: {exc}")

    @app.get("/api/timeline", dependencies=auth)
    def timeline(manifest: str):
        """Every sentence of a take, in time order, plus its waveform --
        one call gets everything the timeline needs to draw itself.
        Rebuilt from the manifest file alone (via load_manifest), the
        same way the desktop's "Open a take..." path works, so this has
        no dependency on any in-memory app state -- reopening a take from
        an earlier session works exactly like reopening one from this
        session."""
        from . import session as session_mod
        from .audio import envelope
        take = _load_take_or_404(manifest)
        if not os.path.isfile(take.get("out_path", "")):
            raise HTTPException(
                404, "That take's finished audio is missing -- it may "
                    "have been moved or deleted.")
        flat, man = session_mod.flatten_take(take)
        if not flat:
            raise HTTPException(400, "That take has no sentence "
                                     "information to show.")
        total = max(man["duration"], flat[-1]["end"]) or 1.0
        env = envelope(take["out_path"], buckets=900)
        return {
            "out_path": take["out_path"],
            "engine": take["engine_key"],
            "duration": total,
            "waveform": env,
            "sentences": [
                {"index": i, "chunk": s["chunk"], "seg": s["seg"],
                 "text": s["text"], "start": s["start"], "end": s["end"]}
                for i, s in enumerate(flat)],
        }

    @app.get("/api/timeline/span", dependencies=auth)
    def timeline_span(manifest: str, start: float, end: float):
        """Extract [start, end] seconds of the take's finished audio as
        its own downloadable clip, for listening to one sentence or a
        drag-selected range in isolation -- the desktop's "Play
        selection" does the same extraction, just opening the result
        with the OS player instead of streaming it back."""
        from .audio import extract_span
        from fastapi.responses import FileResponse
        take = _load_take_or_404(manifest)
        suffix = os.path.splitext(take["out_path"])[1] or ".wav"
        out = os.path.join(tempfile.gettempdir(),
                           f"narrator_timeline_span{suffix}")
        path = extract_span(take["out_path"], start, end, out, print)
        if not path:
            raise HTTPException(400, "Couldn't extract that span.")
        return FileResponse(path, media_type="audio/mpeg"
                            if suffix != ".wav" else "audio/wav")

    class RespliceRequest(BaseModel):
        manifest: str
        chunk: int
        seg: int
        text: str
        retry: int = 0

    @app.post("/api/timeline/resplice", dependencies=auth)
    def timeline_resplice(request: RespliceRequest):
        """Re-record ONE sentence and splice it into the finished take in
        place -- a background job, since it renders through the real
        engine and rebuilds the master file, the same work
        resplice_segment() does on the desktop."""
        from .pipeline import resplice_segment
        if not request.text.strip():
            raise HTTPException(400, "The sentence can't be empty.")
        take = _load_take_or_404(request.manifest)

        def work(job):
            out = resplice_segment(take, request.chunk, request.seg,
                                   request.text, job.log,
                                   retry=request.retry)
            job.outcome = f"spliced -> {os.path.basename(out)}"
            return {"output": out}

        job = STORE.start("resplice", work,
                          label=os.path.basename(take["out_path"]),
                          detail={"chunk": request.chunk,
                                 "seg": request.seg})
        return job.snapshot()

    @app.get("/api/timeline/words", dependencies=auth)
    def timeline_words(manifest: str, text: str):
        """How Kokoro currently pronounces each word of a sentence --
        Kokoro-only per-word detail, same restriction as the desktop
        (other engines have no equivalent introspection)."""
        from . import engines as engines_mod
        from .pronunciation import words_in, load_pronunciations
        take = _load_take_or_404(manifest)
        if take["engine_key"] != "kokoro":
            return {"words": [], "note": "per-word detail is Kokoro-only"}
        res = engines_mod.kokoro_words_phonemes(
            words_in(text), print, load_pronunciations())
        if res.get("error"):
            raise HTTPException(400, res["error"])
        return {"words": res["words"]}

    # --- audiogram: layout, live preview, motion preview, export ----------

    def _take_audio_for(manifest):
        """The web equivalent of the desktop's take_audio(): a specific
        take's finished file, or None. The desktop reads whichever take
        the Publish dropdown points at (in-memory app state); the web
        API has no such session-local selection, so the caller passes
        which take's manifest to use -- explicit rather than guessed."""
        if not manifest:
            return None
        from .segments import load_manifest
        try:
            take = load_manifest(manifest)
        except Exception:
            return None
        path = take.get("out_path", "")
        return path if path and os.path.isfile(path) else None

    @app.get("/api/audiogram/defaults", dependencies=auth)
    def audiogram_defaults():
        """The full field set with its defaults, and the codec/animatable
        lists the form needs -- one call so the client doesn't hardcode
        any of this and drift from the real module."""
        saved = load_settings().get("audiogram") or {}
        cfg = audiogram_mod.config_with_defaults(saved)
        return {
            "cfg": cfg,
            "animatable": list(audiogram_mod.ANIMATABLE),
            "codecs": [{"key": k, "label": v["label"]}
                      for k, v in audiogram_mod.CODECS.items()],
            "preview_max_seconds": audiogram_mod.PREVIEW_MAX_SECONDS,
        }

    @app.get("/api/audiogram/source", dependencies=auth)
    def audiogram_source(manifest: str = ""):
        """One line describing what the waveform will actually be read
        from -- an explicit audio_source in the saved cfg wins over the
        given take, same precedence as resolve_audio_source()."""
        cfg = audiogram_mod.config_with_defaults(
            load_settings().get("audiogram") or {})
        fallback = _take_audio_for(manifest)
        note = audiogram_mod.source_note(cfg, fallback)
        return {"note": note,
                "warning": "NOT the take" in note or "MISSING" in note}

    class AudiogramLayoutRequest(BaseModel):
        cfg: dict
        width: int = 480
        height: int = 270

    @app.post("/api/audiogram/layout", dependencies=auth)
    def audiogram_layout(request: AudiogramLayoutRequest):
        """The resolved pixel geometry (box/center/pivot) for the guide
        overlay the client draws over the preview image -- computed by
        the SAME layout() function the real renderer uses, so the guides
        can't disagree with where the waveform actually gets drawn."""
        geo = audiogram_mod.layout(request.cfg, request.width,
                                   request.height)
        box = audiogram_mod.crop_box(request.cfg, 1920, 1080)
        frac = ((box[2] - box[0]) * (box[3] - box[1])) / (1920 * 1080)
        return {"box": geo["box"], "center": geo["center"],
                "pivot": geo["pivot"], "geometry": geo["geometry"],
                "rotation": geo["rotation"],
                "crop_fraction": frac,
                "rotation_disables_crop": bool(request.cfg.get("rotation"))}

    @app.post("/api/audiogram/preview.png", dependencies=auth)
    def audiogram_preview_png(request: AudiogramLayoutRequest):
        """A single still frame, drawn by the REAL renderer (draw_frame)
        against a synthetic demo waveform -- not a sketch of the layout,
        so the preview can't disagree with what an actual render would
        produce. Matches the desktop's still-preview exactly (same demo
        sine-wave values), which is why this needs no real audio file to
        exist yet."""
        from fastapi.responses import Response
        import io
        import numpy as np
        from PIL import Image
        cfg = audiogram_mod.config_with_defaults(request.cfg)
        n = max(2, int(cfg["bars"]))
        demo = (0.35 + 0.55 * np.abs(np.sin(
            np.linspace(0, 3.4, n) * 1.7))).astype("float32")
        img = Image.new("RGBA", (request.width, request.height),
                        (34, 34, 34, 255))
        img.alpha_composite(audiogram_mod.draw_frame(
            demo, cfg, request.width, request.height))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return Response(content=buf.getvalue(), media_type="image/png")

    @app.get("/api/audiogram/command", dependencies=auth)
    def audiogram_command(manifest: str = "", width: int = 1920,
                          height: int = 1080, filter_override: str = ""):
        """The ffmpeg fast-path command this layout would run -- shown so
        the person can see and, if they want, hand-edit the filter graph
        (filter_override), same as the desktop's command box."""
        cfg = audiogram_mod.config_with_defaults(
            load_settings().get("audiogram") or {})
        audio = _resolve_or_placeholder(cfg, manifest)
        text = audiogram_mod.command_preview(
            audio, "audiogram.mp4", cfg, width, height, seconds=None,
            filter_override=filter_override.strip() or None)
        return {"command": text}

    @app.get("/api/audiogram/estimate", dependencies=auth)
    def audiogram_estimate(manifest: str, width: int = 1920,
                           height: int = 1080, fps: int = 30,
                           crop: bool = True, codec: str = "webm"):
        """Roughly how long a full export will take and how big it will
        be, for the given take's real duration -- the desktop shows this
        next to the export button so a several-minute render isn't a
        surprise."""
        cfg = audiogram_mod.config_with_defaults(
            load_settings().get("audiogram") or {})
        audio = _take_audio_for(manifest)
        if not audio:
            return {"seconds": 0, "text": "Render an episode first to "
                                          "see a time estimate for it."}
        seconds = duration_of(audio) or 0
        if not seconds:
            return {"seconds": 0, "text": "Render an episode first to "
                                          "see a time estimate for it."}
        box = (audiogram_mod.crop_box(cfg, width, height) if crop
              else (0, 0, width, height))
        fraction = ((box[2] - box[0]) * (box[3] - box[1])) / (width * height)
        est = audiogram_mod.estimate_render(seconds, width, height, fps,
                                            fraction, codec)
        return {"seconds": seconds,
                "text": f"For {seconds / 60:.0f} min of audio: "
                       + audiogram_mod.describe_estimate(est)}

    def _resolve_or_placeholder(cfg, manifest):
        try:
            return audiogram_mod.resolve_audio_source(
                cfg, _take_audio_for(manifest))
        except FileNotFoundError:
            return "<your audio file>"

    @app.get("/api/audiogram/preview-reason", dependencies=auth)
    def audiogram_preview_reason():
        cfg = audiogram_mod.config_with_defaults(
            load_settings().get("audiogram") or {})
        engine, why = audiogram_mod.preview_reason(cfg)
        name = "fast ffmpeg path" if engine == "ffmpeg" else "frame renderer"
        return {"engine": engine, "text": f"Will use the {name} -- {why}."}

    class AudiogramMotionRequest(BaseModel):
        manifest: str = ""
        seconds: int = 5

    @app.post("/api/audiogram/preview-motion", dependencies=auth)
    def audiogram_preview_motion(request: AudiogramMotionRequest):
        """A real few-second moving preview -- a background job, since
        even the fast ffmpeg path takes a moment and the frame renderer
        can take longer, same as the desktop's threaded version."""
        cfg = audiogram_mod.config_with_defaults(
            load_settings().get("audiogram") or {})
        try:
            audio = audiogram_mod.resolve_audio_source(
                cfg, _take_audio_for(request.manifest))
        except FileNotFoundError as exc:
            raise HTTPException(400, str(exc))

        def work(job):
            path, engine = audiogram_mod.preview_clip(
                audio, os.path.join(default_output_root(), "_preview"),
                cfg, job.log, seconds=request.seconds, width=640,
                height=360)
            job.outcome = f"preview ready ({engine} renderer)"
            return {"output": path, "engine": engine}

        job = STORE.start("audiogram-preview", work, label="Audiogram",
                          detail={"seconds": request.seconds})
        return job.snapshot()

    class AudiogramExportRequest(BaseModel):
        cfg: dict
        manifest: str = ""
        codec: str = "webm"
        width: int = 1920
        height: int = 1080
        crop: bool = True

    @app.post("/api/audiogram/export", dependencies=auth)
    def audiogram_export(request: AudiogramExportRequest):
        """Bake the full audiogram to a transparent overlay clip -- a
        background job (this can take minutes for a long episode at high
        resolution, per the estimate endpoint above). Also saves the
        layout as the new default, same as the desktop's "Save layout"
        happening implicitly on export."""
        cfg = audiogram_mod.config_with_defaults(request.cfg)
        try:
            audio = audiogram_mod.resolve_audio_source(
                cfg, _take_audio_for(request.manifest))
        except FileNotFoundError as exc:
            raise HTTPException(400, str(exc))
        settings = load_settings()
        settings["audiogram"] = dict(cfg)
        save_settings(settings)

        ext = audiogram_mod.CODECS[request.codec]["ext"]
        base = os.path.splitext(audio)[0] + "_audiogram"
        out = unique_path(base + ext) if ext else base

        def work(job):
            path = audiogram_mod.render_overlay(
                audio, out, cfg, job.log, width=request.width,
                height=request.height, codec=request.codec,
                crop=request.crop)
            ox, oy, fw, fh = audiogram_mod.render_overlay.last_crop
            note = (f"Done: {os.path.basename(path)}"
                   + (f" -- place it at x={ox}, y={oy} in your editor "
                      f"({fw}x{fh})." if (fw, fh) != (request.width,
                                                       request.height)
                      else " -- full frame, drop it straight on top."))
            job.outcome = note
            return {"output": path, "crop": [ox, oy, fw, fh]}

        frames = audiogram_mod.estimate_frames(audio, cfg["fps"])
        job = STORE.start("audiogram-export", work, label="Audiogram",
                          detail={"frames": frames, "codec": request.codec})
        return job.snapshot()

    @app.get("/api/expressions/reference", dependencies=auth)
    def expressions_reference(filter: str = ""):
        """Available variables/functions for the formula lookup list,
        optionally filtered to what's under the cursor -- the same list
        the desktop's autocomplete box shows."""
        from . import expressions as expressions_mod
        return {"items": expressions_mod.reference(filter)}

    class ExpressionValidateRequest(BaseModel):
        source: str

    @app.post("/api/expressions/validate", dependencies=auth)
    def expressions_validate(request: ExpressionValidateRequest):
        from . import expressions as expressions_mod
        ok, message = expressions_mod.validate(request.source)
        return {"ok": ok, "message": message}

    @app.get("/api/components", dependencies=auth)
    def component_report():
        return {"components": components_mod.report()}

    class ComponentInstallRequest(BaseModel):
        key: str

    @app.post("/api/components/install", dependencies=auth)
    def install_component(request: ComponentInstallRequest):
        """Install a pip-based optional component as a job -- it can take
        a while and needs progress reported, same shape as everything
        else long-running here."""
        spec = components_mod.COMPONENTS.get(request.key)
        if spec is None:
            raise HTTPException(404, f"No component called "
                                     f"{request.key!r}")
        if spec["kind"] != "python":
            raise HTTPException(
                400, f"{spec['label']} isn't something this can install "
                     f"automatically -- {spec.get('hint', '')}")

        def work(job):
            components_mod.install_python_component(request.key, job.log)
            job.outcome = f"{spec['label']} is ready."
            return {"installed": True}

        job = STORE.start("install", work, label=spec["label"],
                          detail={"component": request.key,
                                 "licence": spec["licence"]})
        return job.snapshot()

    @app.post("/api/engines/{name}/install", dependencies=auth)
    def install_engine(name: str):
        """Set up a Kokoro or Qwen3 environment -- the multi-gigabyte
        download. A job for the same reason: it can take a long time and
        the person needs to see it happening, not wonder if it's frozen."""
        spec = ENGINES.get(name)
        if spec is None:
            raise HTTPException(404, f"No engine called {name!r}")
        from . import setup_engines

        def work(job):
            def on_progress(info):
                if info.get("kind") == "stage":
                    job.log(f"{info['label']} "
                           f"(step {info['step']} of {info['total']})...")
                elif info.get("kind") == "downloading":
                    job.log(f"Downloading {info.get('name', '')} "
                           f"{info.get('size', '')}...")
            ok = setup_engines.create_environment(spec["key"], job.log,
                                                  on_progress)
            if not ok:
                raise RuntimeError("Setup did not complete -- see the log.")
            from .config import forget_engine_probes
            forget_engine_probes()
            job.outcome = f"{name} is ready."
            return {"installed": True}

        job = STORE.start("install", work, label=name,
                          detail={"engine": spec["key"]})
        return job.snapshot()

    @app.get("/api/library", dependencies=auth)
    def get_library():
        return {"projects": library.all_projects()}

    # --- browsing the machine --------------------------------------------

    @app.get("/api/files", dependencies=auth)
    def list_files(path: str = "", only_dirs: bool = False,
                   search: str = "", search_depth: int = 4):
        """A browser can't hand over a file path, so the server browses on
        its behalf. This is why the token exists.

        Defaults to APP_DIR (where Narrator itself lives), not the OS
        home folder -- the person's documents and output almost always
        live under or near the app, so that's a far more useful starting
        point than dropping them in their home directory every time.

        `search`, when given, looks recursively under `path` (or
        APP_DIR) up to `search_depth` levels rather than listing that
        one folder -- results carry their own containing folder so a
        match three levels down is still unambiguous."""
        target = os.path.abspath(os.path.expanduser(path or APP_DIR))
        if not os.path.isdir(target):
            raise HTTPException(404, f"Not a folder: {target}")

        def entry_for(full, name, is_dir):
            try:
                stat = os.stat(full)
            except OSError:
                return None
            return {"name": name, "path": full, "dir": is_dir,
                    "size": None if is_dir else stat.st_size,
                    "mtime": stat.st_mtime}

        if search.strip():
            q = search.strip().lower()
            found = []
            base_depth = target.rstrip(os.sep).count(os.sep)
            for cur_root, dirs, files in os.walk(target):
                depth = cur_root.rstrip(os.sep).count(os.sep) - base_depth
                if depth >= search_depth:
                    dirs[:] = []
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                names = (dirs if only_dirs else dirs + files)
                for name in names:
                    if q not in name.lower():
                        continue
                    if name.startswith("."):
                        continue
                    full = os.path.join(cur_root, name)
                    is_dir = os.path.isdir(full)
                    if only_dirs and not is_dir:
                        continue
                    e = entry_for(full, name, is_dir)
                    if e:
                        e["folder"] = os.path.relpath(cur_root, target)
                        found.append(e)
                    if len(found) >= 500:
                        break
                if len(found) >= 500:
                    break
            return {"path": target, "parent": None, "entries": found,
                    "search": search}

        entries = []
        try:
            for name in os.listdir(target):
                if name.startswith("."):
                    continue
                full = os.path.join(target, name)
                is_dir = os.path.isdir(full)
                if only_dirs and not is_dir:
                    continue
                e = entry_for(full, name, is_dir)
                if e:
                    entries.append(e)
        except PermissionError:
            raise HTTPException(403, f"Not allowed to read {target}")
        parent = os.path.dirname(target)
        return {"path": target,
                "parent": parent if parent != target else None,
                "entries": entries}

    # --- settings ---------------------------------------------------------

    class SettingsPatch(BaseModel):
        values: dict

    @app.get("/api/settings", dependencies=auth)
    def get_settings():
        return {"settings": load_settings()}

    @app.post("/api/settings", dependencies=auth)
    def patch_settings(patch: SettingsPatch):
        current = load_settings()
        current.update(patch.values)
        save_settings(current)
        return {"settings": current}

    class EnvRootRequest(BaseModel):
        path: str = ""

    @app.post("/api/engines/env-root", dependencies=auth)
    def set_env_root(request: EnvRootRequest):
        """Where engine environments are searched for -- point this at an
        older Narrator folder to reuse kokoro-env/qwen3-env instead of
        downloading several GB again. A blank path goes back to this
        app's own folder. Its own endpoint (rather than the generic
        /api/settings PATCH) because setting it must also invalidate the
        cached probe results, or the change wouldn't take effect until
        the app restarted."""
        path = (request.path or "").strip()
        if path and not os.path.isdir(path):
            raise HTTPException(400, f"{path} doesn't exist.")
        settings = load_settings()
        if path:
            settings["env_root"] = path
        else:
            settings.pop("env_root", None)
        save_settings(settings)
        from .config import forget_engine_probes
        forget_engine_probes()
        return {"env_root": path}

    # --- validation, before anything is started ---------------------------

    class RenderRequest(BaseModel):
        cfg: dict

    @app.post("/api/validate", dependencies=auth)
    def validate(request: RenderRequest):
        """Check settings without doing anything. The frontend can call
        this as a form changes, and gets the same verdict a render
        would."""
        cfg, problems = render_config.coerce(request.cfg)
        return {"cfg": cfg, "problems": problems, "ok": not problems}

    # --- jobs -------------------------------------------------------------

    @app.post("/api/render", dependencies=auth)
    def start_render(request: RenderRequest):
        cfg, problems = render_config.coerce(request.cfg)
        blocking = [p for p in problems
                   if "required" in p or "isn't one of" in p
                   or "no file at" in p or "no folder at" in p]
        if blocking:
            raise HTTPException(400, {"problems": blocking})
        spec = ENGINES.get(cfg["engine"])
        if spec is None:
            raise HTTPException(400, f"Unknown engine {cfg['engine']!r}")

        def work(job):
            for problem in problems:
                job.log(f"Note: {problem}")
            out = session_mod.render_document(cfg, job.log, spec, SESSION)
            if out:
                from .audio import duration_of
                minutes = (duration_of(out) or 0) / 60
                size = os.path.getsize(out) / 1e6
                job.outcome = (f"{minutes:.1f} min, {size:.1f} MB -> "
                              f"{os.path.basename(out)}")
            else:
                job.outcome = "produced no output"
            return {"output": out}

        job = STORE.start(
            "render", work, label=os.path.basename(cfg["path"]),
            detail={"document": cfg["path"], "engine": cfg["engine"],
                   "voice": cfg["voice"], "format": cfg["format"]})
        return job.snapshot()

    class QueueRequest(BaseModel):
        paths: list

    @app.post("/api/queue", dependencies=auth)
    def start_queue(request: QueueRequest):
        paths = request.paths or [
            p["path"] for p in library.all_projects()
            if (p.get("cfg") or {}).get("engine")]
        if not paths:
            raise HTTPException(400, "Nothing to render.")

        def work(job):
            outcome = session_mod.run_queue(paths, job.log, ENGINES, SESSION,
                                            should_cancel=job.cancelled)
            bits = [f"{len(outcome['done'])} rendered"]
            if outcome["failed"]:
                bits.append(f"{len(outcome['failed'])} failed")
            if outcome["skipped"]:
                bits.append(f"{len(outcome['skipped'])} skipped")
            job.outcome = ", ".join(bits)
            return outcome

        job = STORE.start("queue", work, label=f"{len(paths)} document(s)",
                          detail={"documents": ", ".join(
                              os.path.basename(p) for p in paths[:6])})
        return job.snapshot()

    class TranscribeRequest(BaseModel):
        audio: str
        model: str = "base"
        subtitles: bool = True
        chapters: bool = True
        timestamps: bool = False

    @app.post("/api/transcribe", dependencies=auth)
    def start_transcribe(request: TranscribeRequest):
        if not os.path.isfile(request.audio):
            raise HTTPException(400, f"No file at {request.audio}")

        def work(job):
            made = tasks_mod.transcribe_file(
                request.audio, job.log, model=request.model,
                want_srt=request.subtitles, want_chapters=request.chapters,
                timestamps=request.timestamps)
            job.outcome = (f"{len(made)} file(s): "
                          + ", ".join(os.path.basename(m) for m in made))
            return {"files": made}

        job = STORE.start("transcribe", work,
                          label=os.path.basename(request.audio),
                          detail={"audio": request.audio,
                                 "model": request.model})
        return job.snapshot()

    @app.get("/api/jobs", dependencies=auth)
    def list_jobs(query: str = "", status: str = "", kind: str = "",
                  history: bool = True):
        """Summaries only, filtered server-side so a long history isn't
        shipped over the wire just to be searched in the client."""
        return {"jobs": STORE.list(query=query, status=status, kind=kind,
                                   include_history=history)}

    @app.delete("/api/jobs/history", dependencies=auth)
    def clear_history():
        STORE.clear_history()
        return {"jobs": STORE.list()}

    @app.get("/api/jobs/{job_id}", dependencies=auth)
    def job_status(job_id: str, since: int = 0):
        job = STORE.get(job_id)
        if job is not None:
            return job.snapshot(since=since)
        # Not running here -- it may still be remembered from an earlier
        # run, which is the whole point of keeping a history.
        record = STORE.get_record(job_id)
        if record is None:
            raise HTTPException(404, "No such job")
        record = dict(record)
        record["lines"] = record.get("lines", [])[since:]
        return record

    @app.post("/api/jobs/{job_id}/cancel", dependencies=auth)
    def cancel_job(job_id: str):
        job = STORE.get(job_id)
        if job is None:
            raise HTTPException(404, "No such job")
        job.cancel()
        return job.snapshot(since=10 ** 9)

    @app.get("/api/jobs/{job_id}/events")
    def job_events(job_id: str, token: str = ""):
        """Server-Sent Events: log lines as they arrive.

        The token comes as a query parameter rather than a header because
        EventSource cannot set headers -- a real constraint of the browser
        API, not a shortcut. It is compared the same constant-time way.
        """
        if not secrets.compare_digest(token, TOKEN):
            raise HTTPException(401, "Bad or missing token")
        job = STORE.get(job_id)
        if job is None:
            raise HTTPException(404, "No such job")

        def stream():
            import json
            sent = 0
            while True:
                snap = job.snapshot(since=sent)
                sent += len(snap["lines"])
                if snap["lines"] or snap["status"] != "running":
                    yield "data: " + json.dumps(snap) + "\n\n"
                if snap["status"] in ("done", "failed", "cancelled"):
                    return
                time.sleep(0.25)

        return StreamingResponse(
            stream(), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache",
                     "X-Accel-Buffering": "no"})

    # --- publishing -------------------------------------------------------

    def _take_or_404(name):
        take = SESSION.take_named(name) if name else SESSION.last_render
        if take is None or not os.path.isfile(take.get("out_path", "")):
            raise HTTPException(
                404, "No finished take. Render something first.")
        return take

    @app.get("/api/podcast", dependencies=auth)
    def get_podcast():
        """Channel settings plus which required fields are still unset --
        publishing works without them, but a feed won't be accepted."""
        settings = load_podcast_settings()
        return {"settings": settings,
                "fields": publish_mod.REQUIRED_CHANNEL_FIELDS,
                "missing": publish_mod.missing_channel_fields(settings),
                "episodes": publish_mod.load_episodes()}

    class PodcastPatch(BaseModel):
        values: dict

    @app.post("/api/podcast", dependencies=auth)
    def patch_podcast(patch: PodcastPatch):
        settings = load_podcast_settings()
        settings.update(patch.values)
        save_podcast_settings(settings)
        return {"settings": settings,
                "missing": publish_mod.missing_channel_fields(settings)}

    class PublishRequest(BaseModel):
        take: str = ""
        title: str = ""
        notes: str = ""

    @app.post("/api/publish", dependencies=auth)
    def publish_episode(request: PublishRequest):
        take = _take_or_404(request.take)
        lines = []
        try:
            result = tasks_mod.publish_take(take, request.title,
                                            request.notes, lines.append)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        from . import library
        if take.get("source_path"):
            library.touch(take["source_path"], status="published")
        return {**result, "log": lines}

    @app.get("/api/chapters", dependencies=auth)
    def get_chapters(take: str = ""):
        marks, text = tasks_mod.chapters_for_take(_take_or_404(take))
        return {"chapters": marks, "text": text}

    class TakeRequest(BaseModel):
        take: str = ""

    @app.post("/api/chapters/embed", dependencies=auth)
    def embed_chapters(request: TakeRequest):
        lines = []
        try:
            marks = tasks_mod.embed_chapters_in_take(
                _take_or_404(request.take), lines.append)
        except RuntimeError as exc:
            raise HTTPException(400, str(exc))
        return {"embedded": len(marks), "log": lines}

    class TranscriptRequest(BaseModel):
        document: str
        out_dir: str = ""

    @app.post("/api/transcript", dependencies=auth)
    def make_transcript(request: TranscriptRequest):
        if not os.path.isfile(request.document):
            raise HTTPException(400, f"No file at {request.document}")
        lines = []
        out_dir = request.out_dir or os.path.dirname(request.document)
        path = tasks_mod.export_transcript(request.document, out_dir,
                                           lines.append)
        return {"path": path, "log": lines}

    # --- LLM providers and dialogue ---------------------------------------

    @app.get("/api/llm/providers", dependencies=auth)
    def llm_providers():
        """Configured providers with keys MASKED, plus the templates a new
        one can be started from."""
        from . import llm
        return {"providers": llm.safe_providers(),
                "templates": llm.PROVIDER_TEMPLATES}

    class ProviderPatch(BaseModel):
        name: str
        config: dict

    @app.post("/api/llm/providers", dependencies=auth)
    def save_llm_provider(patch: ProviderPatch):
        from . import llm
        if not patch.name.strip():
            raise HTTPException(400, "The provider needs a name.")
        llm.save_provider(patch.name.strip(), patch.config)
        return {"providers": llm.safe_providers()}

    @app.delete("/api/llm/providers/{name}", dependencies=auth)
    def remove_llm_provider(name: str):
        from . import llm
        llm.delete_provider(name)
        return {"providers": llm.safe_providers()}

    class VerifyRequest(BaseModel):
        name: str
        model: str = ""

    @app.post("/api/llm/verify", dependencies=auth)
    def verify_llm(request: VerifyRequest):
        """Staged checks, stopping at the first real failure so the
        message names the fault rather than a symptom."""
        from . import llm
        cfg = llm.load_providers().get(request.name)
        if cfg is None:
            raise HTTPException(404, f"No provider called {request.name!r}")
        lines = []
        stages = llm.verify(cfg, request.model or None, lines.append)
        return {"stages": stages, "log": lines,
                "ok": all(s["ok"] for s in stages)}

    class ScriptRequest(BaseModel):
        document: str
        provider: str
        model: str = ""
        options: dict = {}

    @app.post("/api/dialogue/script", dependencies=auth)
    def start_script(request: ScriptRequest):
        from . import dialogue, llm
        if not os.path.isfile(request.document):
            raise HTTPException(400, f"No file at {request.document}")
        cfg = llm.load_providers().get(request.provider)
        if cfg is None:
            raise HTTPException(404,
                                f"No provider called {request.provider!r}")
        try:
            # Keeps headings, which the sectioning and outline depend on.
            text = dialogue.load_document(request.document)
        except Exception as exc:
            raise HTTPException(400, f"Couldn't read that document: {exc}")

        def work(job):
            result = dialogue.generate_script(
                text, cfg, request.options, job.log,
                request.model or None, should_cancel=job.cancelled)
            job.outcome = (
                f"{len(result['turns'])} turns, ~{result['word_count']:,} "
                f"words (~{result['word_count'] / 150:.0f} min)"
                + (f", {result['removed_duplicates']} repeat(s) removed"
                   if result["removed_duplicates"] else ""))
            return result

        job = STORE.start("script", work,
                          label=os.path.basename(request.document),
                          detail={"document": request.document,
                                 "provider": request.provider,
                                 "model": request.model or cfg.get("model")})
        return job.snapshot()

    class DialogueRenderRequest(BaseModel):
        cfg: dict
        turns: list
        voice1: str
        voice2: str

    @app.post("/api/dialogue/render", dependencies=auth)
    def start_dialogue_render(request: DialogueRenderRequest):
        cfg, problems = render_config.coerce(request.cfg)
        blocking = [p for p in problems
                   if "required" in p or "isn't one of" in p
                   or "no file at" in p or "no folder at" in p]
        if blocking:
            raise HTTPException(400, {"problems": blocking})
        spec = ENGINES.get(cfg["engine"])
        if spec is None:
            raise HTTPException(400, f"Unknown engine {cfg['engine']!r}")
        if not request.turns:
            raise HTTPException(400, "There is no dialogue to render.")

        def work(job):
            out = session_mod.render_dialogue(
                request.turns, cfg, request.voice1, request.voice2,
                job.log, spec, SESSION)
            if out:
                from .audio import duration_of
                job.outcome = (f"{(duration_of(out) or 0) / 60:.1f} min -> "
                              f"{os.path.basename(out)}")
            return {"output": out}

        job = STORE.start("dialogue", work,
                          label=os.path.basename(cfg["path"]),
                          detail={"voices": f"{request.voice1} / "
                                           f"{request.voice2}",
                                 "turns": len(request.turns)})
        return job.snapshot()

    class SignoffRequest(BaseModel):
        cfg: dict
        voice1: str
        voice2: str
        turns: list = []

    @app.post("/api/dialogue/signoff", dependencies=auth)
    def dialogue_signoff(request: SignoffRequest):
        """The last stage of setting a provider up: render a short sample
        exchange through the real voices, so the final check is something
        you can listen to rather than a green tick."""
        cfg, problems = render_config.coerce(request.cfg)
        blocking = [p for p in problems
                   if "required" in p or "isn't one of" in p
                   or "no file at" in p or "no folder at" in p]
        if blocking:
            raise HTTPException(400, {"problems": blocking})
        spec = ENGINES.get(cfg["engine"])
        if spec is None:
            raise HTTPException(400, f"Unknown engine {cfg['engine']!r}")
        sample = request.turns[:4] or [
            {"speaker": "Person1",
             "text": "This is how the first host will sound."},
            {"speaker": "Person2",
             "text": "And this is the second voice, replying."},
        ]

        def work(job):
            out = session_mod.render_dialogue(
                sample, cfg, request.voice1, request.voice2, job.log, spec)
            job.outcome = ("sample ready: "
                          + (os.path.basename(out) if out else "failed"))
            return {"output": out, "turns": sample}

        job = STORE.start("signoff", work, label="voice sample",
                          detail={"voices": f"{request.voice1} / "
                                           f"{request.voice2}"})
        return job.snapshot()

    class RefineRequest(BaseModel):
        provider: str
        model: str = ""
        speaker: str
        before: str = ""
        selected: str
        after: str = ""
        instruction: str
        neighbor_before: dict | None = None
        neighbor_after: dict | None = None

    @app.post("/api/dialogue/refine", dependencies=auth)
    def refine_line(request: RefineRequest):
        """One inline edit: rewrite a selected span of a single turn per
        a short instruction. Synchronous, not a background job -- this is
        meant to feel instant while typing, the way an inline editor
        popup does, not something the person watches a job log for."""
        from . import dialogue, llm
        cfg = llm.load_providers().get(request.provider)
        if cfg is None:
            raise HTTPException(404,
                                f"No provider called {request.provider!r}")
        try:
            replacement = dialogue.refine_selection(
                request.before, request.selected, request.after,
                request.instruction, request.speaker, cfg,
                request.model or None, request.neighbor_before,
                request.neighbor_after)
        except dialogue.LLMError as exc:
            raise HTTPException(400, str(exc))
        return {"replacement": replacement}

    # --- pronunciation ----------------------------------------------------

    @app.get("/api/pronunciation/search", dependencies=auth)
    def pronunciation_search(query: str = "", limit: int = 150):
        """Kokoro's dictionary plus your own overrides. Prefix matches
        sort first, which is what makes typing feel like filtering."""
        from .config import load_pronunciations
        from .engines import kokoro_lookup_words
        return kokoro_lookup_words(query, lambda _m: None, limit,
                                   load_pronunciations())

    @app.get("/api/pronunciation/word", dependencies=auth)
    def pronunciation_word(word: str):
        """What Kokoro would actually say for this word right now, and
        where that came from -- override, dictionary, or a guess. Works
        for any word, including ones the scanner never flags."""
        from .config import load_pronunciations
        from .engines import kokoro_current_phonemes
        return kokoro_current_phonemes(word, lambda _m: None,
                                       load_pronunciations())

    class RespellRequest(BaseModel):
        word: str
        respelling: str = ""

    @app.post("/api/pronunciation/preview", dependencies=auth)
    def pronunciation_preview(request: RespellRequest):
        """Build the phonemes a respelling would produce, without saving.
        `failed` names the first piece Kokoro doesn't recognise."""
        from .pronunciation import respell_to_ipa
        pieces = request.respelling.split()
        if not pieces:
            return {"ipa": "", "failed": None}
        stress = next((i for i, p in enumerate(pieces)
                      if p.startswith("*")), 0)
        ipa, failed = respell_to_ipa([p.lstrip("*") for p in pieces], stress)
        return {"ipa": ipa, "failed": failed}

    @app.post("/api/pronunciation/save", dependencies=auth)
    def pronunciation_save(request: RespellRequest):
        from .config import load_pronunciations, save_pronunciations
        from .pronunciation import respell_to_ipa
        word = request.word.strip().lower()
        if not word:
            raise HTTPException(400, "No word given.")
        pieces = request.respelling.split()
        if not pieces:
            raise HTTPException(400, "No respelling given.")
        stress = next((i for i, p in enumerate(pieces)
                      if p.startswith("*")), 0)
        ipa, failed = respell_to_ipa([p.lstrip("*") for p in pieces], stress)
        if failed or not ipa:
            raise HTTPException(
                400, f"'{failed}' isn't a word Kokoro knows -- try a "
                     "different real word that sounds like that part.")
        data = load_pronunciations()
        data[word] = ipa
        data[word + "__respelling"] = request.respelling.strip()
        save_pronunciations(data)
        return {"word": word, "ipa": ipa}

    @app.delete("/api/pronunciation/{word}", dependencies=auth)
    def pronunciation_delete(word: str):
        from .config import load_pronunciations, save_pronunciations
        data = load_pronunciations()
        key = word.strip().lower()
        removed = data.pop(key, None)
        data.pop(key + "__respelling", None)
        if removed is None:
            raise HTTPException(404, f"No override saved for {word!r}.")
        save_pronunciations(data)
        return {"word": key, "removed": True}

    # --- converting audio -------------------------------------------------

    @app.get("/api/convert/options", dependencies=auth)
    def convert_options():
        from .audio import AUDIO_FORMATS
        return {"formats": list(AUDIO_FORMATS),
                "sample_rates": [22050, 44100, 48000],
                "bit_depths": [16, 24],
                "channels": {"Keep as-is": None, "Mono": 1, "Stereo": 2}}

    class ConvertRequest(BaseModel):
        source: str
        format: str
        quality_pct: int = 70
        sample_rate: int = 48000
        bit_depth: int = 16
        channels: int = 0          # 0 keeps whatever the source has
        split_mode: str = "none"   # none|time|size
        split_minutes: float = 20.0
        split_mb: float = 25.0

    @app.post("/api/convert", dependencies=auth)
    def start_convert(request: ConvertRequest):
        from .audio import AUDIO_FORMATS, convert_audio, split_audio
        from .config import unique_path
        if not os.path.isfile(request.source):
            raise HTTPException(400, f"No file at {request.source}")
        if request.format not in AUDIO_FORMATS:
            raise HTTPException(400, f"Unknown format {request.format!r}")
        spec = AUDIO_FORMATS[request.format]
        folder = os.path.dirname(request.source)
        stem = os.path.splitext(os.path.basename(request.source))[0]
        target = unique_path(os.path.join(
            folder, f"{stem}_converted.{spec['ext']}"))

        def work(job):
            job.log(f"Converting {os.path.basename(request.source)} -> "
                   f"{request.format}")
            out = convert_audio(request.source, target, request.format,
                                request.quality_pct, request.sample_rate,
                                request.bit_depth,
                                request.channels or None, job.log)
            if not out:
                raise RuntimeError("Conversion failed -- see the log.")
            job.log(f"  {os.path.basename(out)}, "
                   f"{os.path.getsize(out) / 1e6:.1f} MB")
            parts = []
            if request.split_mode != "none":
                part_dir = os.path.join(folder, f"{stem}_parts")
                job.log("Splitting...")
                parts = split_audio(
                    out, part_dir, stem, spec["ext"],
                    seconds=(request.split_minutes * 60
                            if request.split_mode == "time" else None),
                    max_bytes=(request.split_mb * 1_000_000
                              if request.split_mode == "size" else None),
                    log=job.log)
                job.outcome = (f"{len(parts)} part(s) in "
                              f"{os.path.basename(part_dir)}")
            else:
                job.outcome = (f"{os.path.getsize(out) / 1e6:.1f} MB -> "
                              f"{os.path.basename(out)}")
            return {"output": out, "parts": parts}

        job = STORE.start("convert", work,
                          label=os.path.basename(request.source),
                          detail={"format": request.format,
                                 "split": request.split_mode})
        return job.snapshot()

    # --- takes produced this session --------------------------------------

    @app.get("/api/takes", dependencies=auth)
    def takes():
        from .segments import manifest_path
        return {"takes": [
            {"name": os.path.basename(t["out_path"]),
             "out_path": t["out_path"], "source": t.get("source_path"),
             "engine": t["engine_key"], "voice": t["voice"],
             # Computed the same way write_manifest() names the file, so
             # the timeline editor can be pointed at a take without the
             # client guessing at a naming convention.
             "manifest": manifest_path(t)}
            for t in SESSION.takes()]}

    if static_dir and os.path.isdir(static_dir):
        from fastapi.staticfiles import StaticFiles
        # Mounted last so it can't shadow /api.
        app.mount("/", StaticFiles(directory=static_dir, html=True),
                  name="ui")

    return app


def serve(host="127.0.0.1", port=8765, static_dir=None, open_browser=True):
    """Run the API. Binds to localhost only by default -- exposing this on
    a network would hand anyone who can reach it a filesystem browser and
    a process launcher."""
    import uvicorn
    url = f"http://{host}:{port}/?token={TOKEN}"
    print(f"Narrator is at:\n  {url}\n")
    if host not in ("127.0.0.1", "localhost", "::1"):
        print("WARNING: binding beyond localhost exposes file browsing and "
              "process launching to anything that can reach this port.\n")
    if open_browser:
        import webbrowser
        webbrowser.open(url)
    uvicorn.run(create_app(static_dir), host=host, port=port,
                log_level="warning")
