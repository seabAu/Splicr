"""What Narrator is doing, independent of how it's being shown.

Everything here was previously trapped inside `ui.py` as closures over Tk
widgets, which meant a second interface would have had to reimplement it.
Nothing in this module imports tkinter or touches a widget: it takes a
settings snapshot (`cfg`) and a `log` callable, and returns plain data.

`Session` holds the state that outlives a single render -- which takes
exist and which one the person is currently pointed at. It is in-memory
only, exactly as it was before: `segments.load_manifest()` remains the
route back to a take from an earlier run.
"""

import os

from .audio import duration_of, finalize_render, join_pieces
from .config import output_paths, slugify
from .documents import (DEFAULT_CHARS_PER_TOKEN, chunk_limit_for,
                        chunk_text, read_text_file)
from .segments import build_manifest, write_manifest
from . import library


class Session:
    """The takes produced so far, and which one actions apply to.

    Keyed by source document as well as "most recent", so a batch run
    leaves every take usable rather than only whichever finished last --
    publishing the wrong document is a quiet mistake that's easy to make
    and hard to notice.
    """

    def __init__(self):
        self.last_render = None
        self.renders = {}          # source path -> take record

    def record(self, source_path, take):
        self.last_render = take
        self.renders[source_path] = take
        return take

    def takes(self):
        """Every take whose output file still exists, newest last."""
        return [t for t in self.renders.values()
               if os.path.isfile(t.get("out_path", ""))]

    def take_named(self, out_name):
        """The take whose output file has this basename, or the most
        recent one if there's no match -- which is what an interface
        wants when nothing is explicitly selected."""
        for take in self.renders.values():
            if os.path.basename(take.get("out_path", "")) == out_name:
                return take
        return self.last_render

    def take_names(self):
        return [os.path.basename(t["out_path"]) for t in self.takes()]


def chunks_for(cfg, engine_spec):
    """The text of cfg's document, split the way cfg asks for.

    Uses the same helper the on-screen preview uses, so what was shown is
    exactly what gets rendered. The engine's own cap still applies inside
    it: Qwen3 drifts badly above a few thousand characters whatever was
    asked for.
    """
    text = read_text_file(cfg["path"]).strip()
    limit = chunk_limit_for(
        text, cfg.get("chunk_mode", "parts"),
        cfg.get("chunk_target", cfg.get("chunk_count", 1)),
        engine_spec["chunk"],
        cfg.get("chars_per_token") or DEFAULT_CHARS_PER_TOKEN)
    return chunk_text(text, limit)


def render(cfg, chunks, voice, is_sample, log, engine_spec, session=None):
    """Render from a settings snapshot only -- never widgets. This runs on
    a worker thread, and Tcl variables read off the main thread can hand
    back stale values.

    A real render is recorded on `session`; samples and comparisons are
    not, since they're throwaway snippets.
    """
    folder, stem = output_paths(cfg["root"], cfg["path"], engine_spec["key"],
                                voice, is_sample,
                                use_subfolders=cfg.get("use_subfolders",
                                                      False))
    if not is_sample and cfg.get("filename"):
        stem = slugify(cfg["filename"], 80)

    result = engine_spec["run"](chunks, voice, cfg["speed"], log,
                                subtitles=cfg.get("subtitles", False),
                                take=cfg.get("take", 1))
    if result is None:
        return None

    # Samples and voice comparisons never get subtitles, kept chunks or a
    # video, regardless of what's ticked for the real render.
    finalize_cfg = dict(cfg) if not is_sample else {
        **cfg, "subtitles": False, "keep_chunks": False, "make_video": False,
    }
    out = finalize_render(result, finalize_cfg, folder, stem, log)
    if not out:
        return out

    secs = duration_of(out)
    length = f" ({secs / 60:.1f} min)" if secs else ""
    log(f"  saved{length}: {os.path.basename(out)}")

    if not is_sample:
        take = {
            "engine_key": engine_spec["key"], "voice": voice,
            "speed": cfg["speed"], "cfg": finalize_cfg,
            "take": cfg.get("take", 1),
            "folder": folder, "stem": stem, "out_path": out,
            "result": result, "source_path": cfg["path"],
        }
        if session is not None:
            session.record(cfg["path"], take)
        mpath = write_manifest(take)
        if mpath:
            log(f"  take manifest: {os.path.basename(mpath)}")
        library.touch(cfg["path"], cfg=finalize_cfg, status="rendered",
                     output=out)
    return out


def render_document(cfg, log, engine_spec, session=None):
    """One document start to finish. Shared by a single Generate and the
    batch queue, so there is one narration path rather than two that
    could drift apart."""
    chunks = chunks_for(cfg, engine_spec)
    log(f"Narrating in {len(chunks)} part(s)\n")
    return render(cfg, chunks, cfg["voice"], False, log, engine_spec,
                  session)


def run_queue(paths, log, engines_by_name, session=None,
              should_cancel=lambda: False):
    """Render several library documents back to back, each with its OWN
    saved settings rather than whatever an interface currently shows.

    One document failing never abandons the batch: it is reported and the
    queue moves on. Returns {"done", "failed", "skipped"} of labels.
    """
    done, failed, skipped = [], [], []
    log(f"Queue: {len(paths)} document(s).\n")
    for i, path in enumerate(paths, 1):
        if should_cancel():
            log("\nCancelled. Remaining documents were not started.")
            break
        label = os.path.basename(path)
        log(f"\n=== [{i}/{len(paths)}] {label} ===")
        if not os.path.isfile(path):
            log("  That file isn't where the library says it is; skipped.")
            skipped.append(label)
            continue
        entry = next((e for e in library.load_projects()
                     if e["path"] == path), None)
        saved = (entry or {}).get("cfg") or {}
        if not saved.get("engine"):
            log("  No saved settings for this one yet -- load it, choose a "
               "voice, and render it once by hand first; skipped.")
            skipped.append(label)
            continue
        if saved["engine"] not in engines_by_name:
            log(f"  Its saved engine ({saved['engine']}) isn't available "
               "here; skipped.")
            skipped.append(label)
            continue
        cfg = dict(saved)
        cfg["path"] = path
        try:
            out = render_document(cfg, log, engines_by_name[saved["engine"]],
                                 session)
            (done if out else failed).append(label)
        except Exception as exc:
            log(f"  Failed: {type(exc).__name__}: {exc}")
            failed.append(label)

    log("\n" + "=" * 40)
    log(f"Queue finished. {len(done)} rendered"
       + (f", {len(failed)} failed" if failed else "")
       + (f", {len(skipped)} skipped" if skipped else "") + ".")
    for label in failed:
        log(f"  failed:  {label}")
    for label in skipped:
        log(f"  skipped: {label}")
    return {"done": done, "failed": failed, "skipped": skipped}


def render_dialogue(turns, cfg, voice1, voice2, log, engine_spec,
                    session=None):
    """Render a two-host script to audio, one voice per speaker.

    **One engine call per voice, not per turn.** The obvious approach --
    render each turn as it comes -- would reload the model between every
    line, which for Qwen3 means several gigabytes per turn and is simply
    not viable. Instead every Person1 line is rendered in a single call
    and every Person2 line in another, then the resulting pieces are
    interleaved back into conversation order. Two model loads for a whole
    episode however long it is.

    The result is deliberately the same shape an engine returns, so
    `finalize_render`, the manifest, the timeline and publishing all work
    on a dialogue exactly as they do on a narration.
    """
    if not turns:
        raise ValueError("There is no dialogue to render.")

    groups = {"Person1": [], "Person2": []}
    for index, turn in enumerate(turns):
        groups[turn["speaker"]].append((index, turn["text"]))

    rendered = {}
    for speaker, voice in (("Person1", voice1), ("Person2", voice2)):
        entries = groups[speaker]
        if not entries:
            continue
        log(f"Rendering {len(entries)} {speaker} turn(s) as {voice}...")
        result = engine_spec["run"]([text for _i, text in entries], voice,
                                    cfg.get("speed", 0), log,
                                    subtitles=False,
                                    take=cfg.get("take", 1))
        if result is None:
            raise RuntimeError(f"The engine produced nothing for {speaker}.")
        paths = result["chunk_paths"]
        if len(paths) != len(entries):
            raise RuntimeError(
                f"The engine returned {len(paths)} pieces for "
                f"{len(entries)} {speaker} turns, so they cannot be put "
                "back in order safely.")
        for (index, _text), path in zip(entries, paths):
            rendered[index] = path

    ordered = [rendered[i] for i in range(len(turns))]
    workdir = os.path.dirname(ordered[0])
    master = os.path.join(workdir, "_dialogue_master.wav")
    log("Interleaving the turns...")
    master, durations, gap = join_pieces(ordered, master, log=log)

    result = {
        "master": master,
        "chunk_paths": ordered,
        "chunk_texts": [t["text"] for t in turns],
        "chunk_durations": durations,
        # One turn is one segment: the natural unit for the timeline, and
        # what "re-record this line" should act on.
        "segments": [[{"text": t["text"], "start": 0.0, "end": d}]
                    for t, d in zip(turns, durations)],
        "native_srt": None,
        "chunk_gap": gap,
        "speakers": [t["speaker"] for t in turns],
    }

    folder, stem = output_paths(cfg["root"], cfg["path"], engine_spec["key"],
                                f"dialogue-{voice1}-{voice2}", False,
                                use_subfolders=cfg.get("use_subfolders",
                                                      False))
    if cfg.get("filename"):
        stem = slugify(cfg["filename"], 80)
    out = finalize_render(result, cfg, folder, stem, log)
    if not out:
        return None
    secs = duration_of(out)
    log(f"  saved ({secs / 60:.1f} min): {os.path.basename(out)}")

    take = {
        "engine_key": engine_spec["key"],
        "voice": f"{voice1} / {voice2}", "speed": cfg.get("speed", 0),
        "cfg": dict(cfg), "take": cfg.get("take", 1),
        "folder": folder, "stem": stem, "out_path": out,
        "result": result, "source_path": cfg["path"], "kind": "dialogue",
    }
    if session is not None:
        session.record(cfg["path"], take)
    write_manifest(take)
    library.touch(cfg["path"], cfg=dict(cfg), status="rendered", output=out)
    return out


# --- the timeline's data model -------------------------------------------


def flatten_take(take):
    """Every sentence of a take, in time order, with the chunk and segment
    indices needed to re-record it. The timeline is a view of this."""
    manifest = build_manifest(take)
    flat = []
    for chunk in manifest["chunks"]:
        for k, seg in enumerate(chunk["segments"]):
            flat.append({"chunk": chunk["index"], "seg": k,
                        "text": seg["text"],
                        "start": seg["abs_start"], "end": seg["abs_end"]})
    return flat, manifest


def sentence_at(flat, seconds):
    """Which sentence covers this moment. A click landing in the gap
    BETWEEN chunks takes the next sentence rather than the previous one,
    and past the end clamps -- both are what a person means by clicking
    there."""
    if not flat:
        return 0
    for i, item in enumerate(flat):
        if item["start"] <= seconds <= item["end"]:
            return i
    for i, item in enumerate(flat):
        if item["start"] > seconds:
            return i
    return len(flat) - 1
