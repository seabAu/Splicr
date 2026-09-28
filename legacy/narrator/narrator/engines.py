"""The three TTS engines and the cross-environment worker bridge.

Kokoro and Qwen3 cannot share a virtualenv, so when one is installed
elsewhere this module re-invokes the package inside that interpreter
and reads the result back.
"""

import argparse
import datetime
import hashlib
import importlib.util
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import wave

from .config import (_no_window, cache_dir, external_python,
                     load_pronunciations, PRONOUNCE_FILE)
from .audio import join_audio, duration_of
from .subtitles import merge_subtitles
from .segments import (save_segments, load_segments, segments_from_pieces,
                       segments_from_word_srt, group_sentences)


# ---------------------------------------------------------------------------
# Engines
# ---------------------------------------------------------------------------




def run_edge(chunks, voice, speed_pct, log, want_subtitles=False):
    """Generates audio, caching every chunk on disk as it goes.

    Returns a dict on success:
        master         path to the joined audio (edge's native mp3)
        chunk_paths    per-chunk audio files, in order
        chunk_durations  seconds per chunk, matching chunk_paths
        chunk_texts    the text of each chunk, matching chunk_paths
        native_srt     edge's own word-level subtitle file, or None
    or None on failure. Knows nothing about output folders, filenames, or
    final format -- that's finalize_render's job, once generation succeeds.
    """
    workdir = cache_dir("edge", voice, speed_pct, "".join(chunks))
    parts, subs = [], []
    # Prefer running the module in this interpreter over an edge-tts.exe on
    # PATH: console-script launchers embed the absolute path of the venv
    # they were installed into and stop working the moment that folder is
    # moved or copied elsewhere, whereas "python -m edge_tts" does not care.
    if importlib.util.find_spec("edge_tts") is not None:
        base_cmd = [sys.executable, "-m", "edge_tts"]
    else:
        base_cmd = ["edge-tts"]

    for i, chunk in enumerate(chunks, 1):
        part = os.path.join(workdir, f"{i:04d}.mp3")
        sub = os.path.join(workdir, f"{i:04d}.srt")
        txt = os.path.join(workdir, f"{i:04d}.txt")
        with open(txt, "w", encoding="utf-8") as fh:
            fh.write(chunk)

        if os.path.exists(part) and os.path.getsize(part) > 500 and \
                os.path.exists(sub):
            log(f"  part {i}/{len(chunks)} already rendered, reusing")
            parts.append(part)
            subs.append(sub)
            continue

        log(f"  part {i}/{len(chunks)} ({len(chunk):,} characters)")
        # Word-level subtitles are always requested: besides captions, they
        # are how sentence boundaries inside an edge chunk are known.
        cmd = base_cmd + ["--voice", voice, f"--rate={speed_pct:+d}%",
                          "--file", txt, "--write-media", part,
                          "--write-subtitles", sub]
        result = subprocess.run(cmd, capture_output=True, text=True,
                                creationflags=_no_window())
        if result.returncode != 0 or not os.path.exists(part):
            log(f"  ! part {i} failed: {result.stderr.strip()[:200]}")
            log("    Dropped connections are common. Press Generate again "
                "to resume from this part.")
            return None
        parts.append(part)
        subs.append(sub)

    from .documents import split_sentences
    segments = []
    for part, sub, chunk in zip(parts, subs, chunks):
        segs = None
        if not os.path.isfile(sidecar := os.path.splitext(part)[0] + ".segments.json"):
            segs = segments_from_word_srt(chunk, sub, split_sentences)
            if segs:
                save_segments(part, segs)
        segments.append(segs or load_segments(part, chunk, duration_of(part)))

    master = os.path.join(workdir, "_master.mp3")
    log("Joining parts...")
    join_audio(parts, master, log)

    native_srt = None
    if want_subtitles and subs:
        native_srt = os.path.join(workdir, "_native.srt")
        try:
            merge_subtitles(parts, subs, native_srt)
        except Exception as exc:
            log(f"  ! could not merge subtitles: {exc}")
            native_srt = None

    return {
        "master": master,
        "chunk_paths": parts,
        "chunk_durations": [duration_of(p) or 0.0 for p in parts],
        "chunk_texts": list(chunks),
        "segments": segments,
        "native_srt": native_srt,
        "chunk_gap": 0.0,  # edge inserts no silence between chunks
    }


def rejoin_master(chunk_paths, workdir, gap_seconds, log):
    """Rebuild a master audio file from a (possibly just-edited) list of
    per-chunk files. Used after fixing one chunk: everything else about the
    take is unchanged, but the master has to be rebuilt from the full chunk
    list since audio files can't be patched in place.

    Dispatches on file extension rather than remembering which engine
    produced these chunks, since that's what actually determines how they
    need to be joined: WAV chunks (Kokoro/Qwen3) are concatenated as raw
    samples with a silence gap inserted between them; MP3 chunks (edge-tts)
    are concatenated with ffmpeg, which already handles the container
    correctly and needs no separate gap since edge-tts's own service leaves
    natural spacing in the speech itself.
    """
    ext = os.path.splitext(chunk_paths[0])[1].lower()
    if ext == ".wav":
        result = _join_chunk_wavs(chunk_paths, [""] * len(chunk_paths),
                                  workdir, gap_seconds=gap_seconds)
        return result["master"]
    master = os.path.join(workdir, "_master" + ext)
    join_audio(chunk_paths, master, log)
    return master


# Silence left at each trimmed edge, so joins don't cut speech off
# abruptly. Two of these sit inside every gap between parts, which is why
# the inserted silence subtracts them (see _join_chunk_wavs).
TRIM_KEEP = 0.04


def trim_silence(data, rate, keep=TRIM_KEEP, floor=0.02):
    """Trim near-silence from both ends of an array, leaving `keep`
    seconds of it. `floor` is relative to the loudest sample, so this
    adapts to how loud the take actually is rather than assuming a level.

    Exists because a generated chunk already ends with the natural pause
    of its last sentence. Adding a fixed gap on top of that made the
    total pause however long the model happened to trail off PLUS the
    gap -- so pauses varied unpredictably, and with many small chunks
    they piled up into audibly metronomic, over-punctuated pacing.
    Trimming first makes the pause between chunks exactly the gap asked
    for, every time.
    """
    import numpy as np
    if data.ndim > 1:
        mono = data.mean(axis=1)
    else:
        mono = data
    if not len(mono):
        return data
    peak = float(np.abs(mono).max())
    if peak <= 0:
        return data
    loud = np.flatnonzero(np.abs(mono) > peak * floor)
    if not len(loud):
        return data
    pad = int(rate * keep)
    a = max(0, int(loud[0]) - pad)
    b = min(len(mono), int(loud[-1]) + pad)
    return data[a:b]


def _join_chunk_wavs(chunk_paths, chunk_texts, workdir, gap_seconds=None):
    """Join per-chunk WAV files into one master with a controlled pause
    between chunks. Shared by Kokoro and Qwen3, since both write real
    per-chunk files to disk rather than only concatenating in memory --
    which is also what makes them resumable the same way edge-tts is.

    Each chunk's own trailing/leading silence is trimmed before the pause
    is inserted, so the gap between chunks is what was asked for rather
    than that plus however long the model trailed off.
    """
    import numpy as np
    import soundfile as sf

    if gap_seconds is None:
        gap_seconds = chunk_gap_setting()

    # What actually gets inserted, as opposed to the total pause the user
    # asked for -- the trimmed edges supply the rest. Subtitles and the
    # manifest need THIS number: they step from one chunk's start to the
    # next, and a chunk's own trailing keep is already inside its duration.
    inserted_pad = max(0.0, gap_seconds - 2 * TRIM_KEEP)
    arrays, rate, durations = [], 24000, []
    for i, path in enumerate(chunk_paths):
        data, rate = sf.read(path, dtype="float32")
        data = trim_silence(data, rate)
        durations.append(len(data) / rate if rate else 0.0)
        arrays.append(data)
        if i < len(chunk_paths) - 1:
            # Each trimmed edge already contributes TRIM_KEEP of silence,
            # so insert only the remainder: the total pause then really is
            # gap_seconds, which is what the setting claims.
            arrays.append(
                np.zeros(int(rate * inserted_pad), dtype=np.float32))

    master = os.path.join(workdir, "_master.wav")
    sf.write(master, np.concatenate(arrays) if arrays
            else np.zeros(1, dtype=np.float32), rate)

    return {
        "master": master,
        "chunk_paths": chunk_paths,
        "chunk_durations": durations,
        "chunk_texts": list(chunk_texts),
        # Per-sentence spans inside each chunk file, from the sidecar written
        # at render time (or one whole-chunk span for older cached chunks).
        "segments": [load_segments(p, t, d) for p, t, d in
                     zip(chunk_paths, chunk_texts, durations)],
        "native_srt": None,
        "chunk_gap": inserted_pad,
    }


def _run_kokoro_local(chunks, voice, speed, workdir, log):
    import numpy as np
    import soundfile as sf
    from kokoro import KPipeline

    lang = "b" if voice.startswith(("bf_", "bm_")) else "a"
    log("Loading Kokoro (first run downloads about 300 MB)...")
    pipeline = KPipeline(lang_code=lang)

    overrides = load_pronunciations()
    real_overrides = {k: v for k, v in overrides.items()
                      if not k.endswith("__respelling")}
    if real_overrides:
        for word, phonemes in real_overrides.items():
            pipeline.g2p.lexicon.golds[word] = phonemes
        log(f"  applied {len(real_overrides)} custom pronunciation(s) from "
            f"{os.path.basename(PRONOUNCE_FILE)}")

    chunk_paths = []
    for i, chunk in enumerate(chunks, 1):
        part = os.path.join(workdir, f"{i:04d}.wav")
        if os.path.exists(part) and os.path.getsize(part) > 1000:
            log(f"  part {i}/{len(chunks)} already rendered, reusing")
        else:
            log(f"  part {i}/{len(chunks)} ({len(chunk):,} characters)")
            # Kokoro hands back one piece per sentence it split off; the
            # text and length of each is exactly the sentence span we need.
            pieces = [(gs, np.asarray(audio, dtype=np.float32).reshape(-1))
                      for gs, _, audio in
                      pipeline(chunk, voice=voice, speed=speed)]
            merged = (np.concatenate([a for _, a in pieces]) if pieces
                     else np.zeros(1, dtype=np.float32))
            sf.write(part, merged, 24000)
            save_segments(part, segments_from_pieces(pieces, 24000))
        chunk_paths.append(part)

    return _join_chunk_wavs(chunk_paths, chunks, workdir)


# --- Qwen3-TTS ------------------------------------------------------------
#
# Verified against the qwen-tts 0.1.1 package source (Qwen3TTSModel in
# qwen_tts/inference/qwen3_tts_model.py) and its README, not from memory.
#
# WHY TWO MODELS. generate_voice_design() takes a written description and
# SAMPLES a voice that fits it -- a fresh sample on every call. The previous
# version called it once per chunk, so every chunk got a slightly (or very)
# different narrator: that is the "new voice every few seconds" bug. Seeding
# does not fix it, because with different text tokens the sampling path
# diverges regardless of seed, so speaker identity is never pinned.
#
# The workflow the Qwen3-TTS README itself recommends for "a consistent
# character voice across many lines" is design-then-clone:
#
#   1. The VoiceDesign model reads a short reference passage in the
#      described voice -- ONCE. That clip is saved as "the voice".
#   2. The Base model turns the clip into a clone prompt (speaker embedding
#      + reference codes + transcript) -- also once per run.
#   3. Every chunk is generated with generate_voice_clone() against that
#      same prompt object, so every chunk has the same speaker.
#
# The reference clip lives in narrator_data/voices/ and is reused across
# runs and documents. A description is designed once; after that the voice
# is fixed. "Take" lets you roll a different voice for the same description
# if the first one isn't right -- each take is its own saved voice.
#
# NOTE: no NVIDIA GPU was available where this was written, so the calls
# below are checked against the package source, not executed on hardware.
# If something errors, the message will say exactly what failed.

QWEN_DESIGN_REPO = "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"
QWEN_CLONE_REPO = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
# Lighter alternative for the clone stage (settings key "qwen_clone_repo").
QWEN_CLONE_REPO_SMALL = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
# Named in qwen-tts 0.1.1's own README, not guessed. The speakers it
# offers are NOT hardcoded anywhere in the package -- they come from
# model.get_supported_speakers() at runtime, so they are queried rather
# than listed here (the same reasoning as the Kokoro voice discovery).
QWEN_CUSTOM_REPO = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"

# What the designed voice reads for its reference clip. Roughly twelve
# seconds: long enough to pin timbre and pace, short enough that carrying
# it as a prompt in front of every chunk costs nothing noticeable.
QWEN_REFERENCE_TEXT = (
    "This is a short reference recording. It is made once, from a written "
    "description, so that every chapter that follows can be read in this "
    "same voice, at this same steady pace.")

# Codec tokens per second for the 12 Hz models; used to size the generation
# budget so a slow, long chunk is never silently cut off.
_QWEN_TOKENS_PER_SEC = 12

# Sentence groups within a chunk: whole sentences up to this many characters
# per generation, with a short pause between groups.
QWEN_GROUP_CHARS = 250
# Sentence groups end at sentence boundaries, where the model already
# leaves a natural pause of its own -- so the seam only needs a token
# amount of extra silence, not a full sentence-length one.
QWEN_GROUP_GAP = 0.06

# The pause inserted between chunks, in seconds. Chunk boundaries also
# fall at sentence ends, so this is on top of a natural pause that is
# already there; the audio is trimmed first (see trim_silence) so this
# number is the ACTUAL resulting gap rather than an addition to an
# unknown one. 0.35 was the old fixed value and read as over-punctuated
# once token-based chunking made many-chunk documents normal.
DEFAULT_CHUNK_GAP = 0.12


def chunk_gap_setting():
    from .config import load_settings
    try:
        return max(0.0, min(2.0, float(
            load_settings().get("chunk_gap", DEFAULT_CHUNK_GAP))))
    except (TypeError, ValueError):
        return DEFAULT_CHUNK_GAP

# Qwen3's own defaults (verified in qwen_tts 0.1.1: do_sample=True,
# top_k=50, temperature=0.9, repetition_penalty=1.05, and a SEPARATE
# subtalker_temperature=0.9 for the acoustic detail) are tuned for
# expressive one-off speech, not for an hour of one narrator sounding like
# the same person. 0.9 is high: every generation samples independently, so
# each one lands somewhere slightly different in the voice's neighbourhood.
# For narration we want the opposite trade -- less variety, more sameness --
# so both temperatures are lowered here. Overridable per-user via
# narrator_settings.json ("qwen_sampling": {...}) for anyone who wants the
# livelier original behaviour back.
# Qwen3's own defaults are 0.9/0.9. Dropping both to 0.6 fixed the voice
# drifting between generations, but bought that consistency with
# expressiveness: less variation between samples also means less variation
# WITHIN a reading, which comes out flatter. 0.75 splits the difference,
# and "expressiveness" below makes it a dial rather than a constant
# somebody has to edit a JSON file to change.
QWEN_SAMPLING = {
    "temperature": 0.75,
    "subtalker_temperature": 0.75,
    "top_k": 50,
    "top_p": 1.0,
    "repetition_penalty": 1.05,
}

# 0.0 = most consistent voice, flattest delivery. 1.0 = Qwen3's own
# livelier defaults, with more chance of the voice shifting between
# generations. Maps onto both temperatures together, since they control
# the same trade at different levels of the model.
EXPRESSIVENESS_RANGE = (0.45, 0.95)


# Everything each engine genuinely exposes, as (settings key, label,
# low, high, step, default, help). Verified against the installed
# packages rather than assumed -- qwen_tts 0.1.1's generate call and
# Kokoro/edge's own parameters. Anything not listed here is not actually
# adjustable, however plausible it might sound.
TUNABLE_PARAMS = {
    "qwen3": [
        ("temperature", "Temperature", 0.05, 1.5, 0.05, 0.75,
         "How much the model varies between samples. Lower is steadier "
         "and flatter; higher is livelier and drifts more."),
        ("subtalker_temperature", "Detail temperature", 0.05, 1.5, 0.05,
         0.75, "The same trade at the acoustic-detail level. Usually "
         "worth keeping near Temperature."),
        ("top_k", "Top-K", 0, 200, 5, 50,
         "How many candidates are considered at each step. 0 means no "
         "limit."),
        ("top_p", "Top-P", 0.1, 1.0, 0.05, 1.0,
         "Keeps only the most likely candidates adding up to this "
         "probability. 1.0 disables it."),
        ("repetition_penalty", "Repetition penalty", 1.0, 2.0, 0.01, 1.05,
         "Discourages the model repeating itself. Too high distorts "
         "ordinary repeated words."),
    ],
    "kokoro": [],
    "edge": [],
}


def engine_params(engine_key):
    """Saved overrides for one engine, defaults filled in for anything
    untouched. Only keys this engine actually declares survive, so a
    stale or hand-typed setting can never become an unexpected keyword
    argument inside a model call."""
    from .config import load_settings
    spec = TUNABLE_PARAMS.get(engine_key, [])
    saved = (load_settings().get("engine_params") or {}).get(engine_key, {})
    out = {}
    for key, _label, lo, hi, _step, default, _help in spec:
        value = saved.get(key, default)
        try:
            value = float(value)
        except (TypeError, ValueError):
            value = default
        value = max(lo, min(hi, value))
        out[key] = int(value) if isinstance(default, int) else value
    return out


def qwen_group_gap():
    from .config import load_settings
    try:
        return max(0.0, min(1.0, float(
            load_settings().get("qwen_group_gap", QWEN_GROUP_GAP))))
    except (TypeError, ValueError):
        return QWEN_GROUP_GAP


def qwen_sampling_settings():
    """QWEN_SAMPLING with any user overrides applied. Unknown keys are
    dropped rather than passed through, so a typo in the settings file
    can't turn into an unexpected keyword argument deep inside the
    model's generate call."""
    from .config import load_settings
    settings = load_settings()
    out = dict(QWEN_SAMPLING)
    if settings.get("expressiveness") is not None:
        try:
            frac = max(0.0, min(1.0, float(settings["expressiveness"])))
            lo, hi = EXPRESSIVENESS_RANGE
            temp = round(lo + (hi - lo) * frac, 3)
            out["temperature"] = out["subtalker_temperature"] = temp
        except (TypeError, ValueError):
            pass
    # Explicit per-parameter values win over the expressiveness dial:
    # the dial is the simple front end, these are the real knobs.
    saved_params = (settings.get("engine_params") or {}).get("qwen3", {})
    for key in QWEN_SAMPLING:
        if key in saved_params:
            out[key] = engine_params("qwen3")[key]
    # The older hand-edited block still wins over both.
    user = (settings.get("qwen_sampling") or {})
    for k, v in user.items():
        if k in QWEN_SAMPLING:
            out[k] = v
    return out


def qwen_group_chars():
    """Characters per generation within a chunk. Bigger = fewer separate
    generations, so fewer places the voice can shift; too big and Qwen3's
    own autoregressive drift takes over within a single generation
    instead. Adjustable for anyone who wants to trade one against the
    other."""
    from .config import load_settings
    try:
        return max(80, int(load_settings().get("qwen_group_chars",
                                               QWEN_GROUP_CHARS)))
    except (TypeError, ValueError):
        return QWEN_GROUP_CHARS


def qwen_voice_fingerprint(description, take=1):
    """Stable id for one designed voice: same description + take -> same
    saved reference clip, on every run and for every document."""
    raw = f"{QWEN_DESIGN_REPO}|{QWEN_REFERENCE_TEXT}|{take}|{description.strip()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def saved_voices():
    """Every designed voice, cloned voice, and saved CustomVoice preset,
    newest first -- three different kinds of "voice" unified into one
    list for the Voice studio. A folder missing its reference clip or
    metadata is skipped rather than half-listed; a CustomVoice preset has
    no folder or reference clip at all, by design (see
    custom_voice_presets())."""
    from .config import VOICES_DIR
    out = []
    if os.path.isdir(VOICES_DIR):
        for name in os.listdir(VOICES_DIR):
            folder = os.path.join(VOICES_DIR, name)
            ref = os.path.join(folder, "reference.wav")
            meta_path = os.path.join(folder, "voice.json")
            if not (os.path.isfile(ref) and os.path.isfile(meta_path)):
                continue
            try:
                with open(meta_path, encoding="utf-8") as fh:
                    meta = json.load(fh)
            except (OSError, ValueError):
                continue
            out.append({
                "folder": folder, "name": name, "reference": ref,
                "description": meta.get("description", ""),
                "take": meta.get("take", 1),
                "label": meta.get("label") or "",
                "kind": meta.get("kind", "designed"),
                # Designed/legacy-cloned voices predate this field and
                # have none -- "qwen3" is the correct read for those,
                # since that's the only engine that made them.
                "engine": meta.get("engine", "qwen3"),
                "created": os.path.getmtime(meta_path),
            })
    for p in custom_voice_presets():
        desc = p["speaker"] + (f"  —  {p['instruct']}"
                               if p.get("instruct") else "")
        out.append({
            "folder": None, "name": p["label"], "reference": None,
            "description": desc, "take": None, "label": p["label"],
            "kind": "custom", "created": p.get("created", 0),
            "speaker": p["speaker"], "instruct": p.get("instruct", ""),
            "engine": "qwen3",
        })
    return sorted(out, key=lambda v: -v["created"])


def rename_voice(folder, label):
    """A friendly label, stored alongside the description. The folder name
    is left alone: it is derived from the description and take, and is
    what the cache key depends on."""
    meta_path = os.path.join(folder, "voice.json")
    with open(meta_path, encoding="utf-8") as fh:
        meta = json.load(fh)
    meta["label"] = label
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2, ensure_ascii=False)
    return meta


def delete_voice(folder):
    from .config import VOICES_DIR
    real = os.path.realpath(folder)
    # Refuse anything outside the voices folder: this deletes a directory
    # tree, and a bad path here would be unrecoverable.
    if not real.startswith(os.path.realpath(VOICES_DIR) + os.sep):
        raise ValueError("That folder isn't inside the voices directory.")
    shutil.rmtree(real)
    return True


def clone_voice_from_recording(audio_path, transcript, description, log,
                               take=1, engine_tag="qwen3", min_seconds=2.0):
    """Save a voice built from the person's OWN recording rather than from
    a written description. Only the reference clip and its transcript are
    stored -- the same shape a designed voice has, so everything
    downstream (rendering, takes, the cache key) treats them identically.

    `engine_tag` picks the folder scheme and which engine's requirements
    apply (Qwen3's minimum clip length differs from Audio8's); both
    engines need the reference transcript for in-context cloning.
    """
    import soundfile as sf
    if not os.path.isfile(audio_path):
        raise ValueError("That recording isn't where you said it was.")
    if not (transcript or "").strip():
        raise ValueError(
            "This needs the exact words spoken in the recording -- it "
            "matches them against the audio to learn the voice.")
    folder = (qwen_voice_dir(description, take) if engine_tag == "qwen3"
             else engine_voice_dir(engine_tag, description, take))
    os.makedirs(folder, exist_ok=True)
    ref = os.path.join(folder, "reference.wav")
    data, rate = sf.read(audio_path, dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    seconds = len(mono) / rate if rate else 0
    if seconds < min_seconds:
        raise ValueError(
            f"That recording is only {seconds:.1f}s. This needs at "
            f"least {min_seconds:g}s of clear speech to clone from.")
    sf.write(ref, mono, rate)
    with open(os.path.join(folder, "voice.json"), "w",
             encoding="utf-8") as fh:
        json.dump({"description": description, "take": take,
                  "kind": "cloned", "engine": engine_tag,
                  "reference_text": transcript.strip(),
                  "source_recording": os.path.basename(audio_path),
                  "seconds": round(seconds, 2)}, fh, indent=2,
                 ensure_ascii=False)
    log(f"  saved a cloned voice from {seconds:.1f}s of audio")
    return folder


def qwen_voice_dir(description, take=1):
    from .config import VOICES_DIR, slugify
    name = f"{slugify(description, 32)}-{qwen_voice_fingerprint(description, take)}"
    return os.path.join(VOICES_DIR, name)


def engine_voice_dir(engine_tag, description, take=1):
    """Same folder-naming scheme as qwen_voice_dir, tagged by engine so
    two engines cloning a voice from the same description never collide
    on one folder."""
    from .config import VOICES_DIR, slugify
    fingerprint = qwen_voice_fingerprint(f"{engine_tag}:{description}", take)
    name = f"{engine_tag}-{slugify(description, 24)}-{fingerprint}"
    return os.path.join(VOICES_DIR, name)


def qwen_voice_exists(description, take=1):
    d = qwen_voice_dir(description, take)
    return (os.path.isfile(os.path.join(d, "reference.wav")) and
            os.path.isfile(os.path.join(d, "voice.json")))


def _qwen_device_kwargs(log):
    try:
        import torch
    except ImportError:
        return {}
    if torch.cuda.is_available():
        log(f"  GPU: {torch.cuda.get_device_name(0)}")
        return {"device_map": "cuda:0", "dtype": torch.bfloat16}
    log("  ! CUDA not available - Qwen3-TTS will be very slow on CPU.")
    log("    See section 0 of the local TTS guide about sm_120.")
    return {}


def _free_gpu():
    """Return freed GPU memory after the caller has dropped its last
    reference to a model (`del model` / `model = None`), so the design and
    clone models are never resident together. Order matters: the reference
    must already be gone, or there is nothing for this to free."""
    import gc
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


def ensure_qwen_voice(description, take, log, device_kwargs=None):
    """Return (reference_wav_path, reference_text) for a designed voice,
    creating it with the VoiceDesign model if this description+take has
    never been designed before. Safe to call from the GUI process only when
    qwen_tts is importable there; normally reached through the worker."""
    import json as _json
    import numpy as np
    import soundfile as sf

    vdir = qwen_voice_dir(description, take)
    wav_path = os.path.join(vdir, "reference.wav")
    meta_path = os.path.join(vdir, "voice.json")
    if os.path.isfile(wav_path) and os.path.isfile(meta_path):
        with open(meta_path, encoding="utf-8") as fh:
            meta = _json.load(fh)
        log(f"  voice: reusing saved reference ({os.path.basename(vdir)})")
        return wav_path, meta.get("reference_text", QWEN_REFERENCE_TEXT)

    from qwen_tts import Qwen3TTSModel
    import torch

    if device_kwargs is None:
        device_kwargs = _qwen_device_kwargs(log)

    log(f"  voice: designing a new reference from the description "
        f"(take {take})")
    log(f"  loading {QWEN_DESIGN_REPO}")
    log("  (first run downloads several GB from Hugging Face)")
    design = Qwen3TTSModel.from_pretrained(QWEN_DESIGN_REPO, **device_kwargs)
    # Seeded so that deleting narrator_data/voices and re-running gives the
    # same take back (on the same hardware/software), rather than a
    # surprise new narrator.
    torch.manual_seed(1000 + int(take))
    wavs, rate = design.generate_voice_design(
        text=QWEN_REFERENCE_TEXT, instruct=description, language="English")
    del design
    _free_gpu()

    os.makedirs(vdir, exist_ok=True)
    audio = np.asarray(wavs[0], dtype=np.float32).reshape(-1)
    sf.write(wav_path, audio, rate)
    with open(meta_path, "w", encoding="utf-8") as fh:
        _json.dump({
            "description": description,
            "take": int(take),
            "reference_text": QWEN_REFERENCE_TEXT,
            "design_model": QWEN_DESIGN_REPO,
            "sample_rate": int(rate),
            "seconds": round(len(audio) / float(rate), 2),
            "created": datetime.datetime.now().isoformat(timespec="seconds"),
        }, fh, indent=2)
    log(f"  voice: saved reference ({len(audio) / float(rate):.1f}s) to "
        f"narrator_data/voices/{os.path.basename(vdir)}")
    return wav_path, QWEN_REFERENCE_TEXT


def _run_qwen_local(chunks, description, speed, workdir, log, take=1,
                    clone_repo=None):
    import numpy as np
    import soundfile as sf

    try:
        from qwen_tts import Qwen3TTSModel
    except ImportError as exc:
        raise RuntimeError(
            "qwen-tts is not installed. Run:\n"
            "  pip install qwen-tts\n"
            f"(import error: {exc})") from exc
    import torch

    device_kwargs = _qwen_device_kwargs(log)
    custom = decode_custom_voice(description)

    # Which chunks still need rendering? Decide before loading anything, so
    # a fully cached run costs no model loads at all.
    chunk_paths, todo = [], []
    for i, chunk in enumerate(chunks, 1):
        part = os.path.join(workdir, f"{i:04d}.wav")
        chunk_paths.append(part)
        if os.path.exists(part) and os.path.getsize(part) > 1000:
            log(f"  part {i}/{len(chunks)} already rendered, reusing")
        else:
            todo.append((i, chunk, part))

    if todo and custom:
        # CustomVoice: a fixed preset speaker, no reference clip or clone
        # prompt -- the speaker identity comes from the model itself.
        speaker, instruct = custom["speaker"], custom["instruct"]
        log(f"  loading {QWEN_CUSTOM_REPO}")
        log("  (first run downloads several GB from Hugging Face)")
        model = Qwen3TTSModel.from_pretrained(QWEN_CUSTOM_REPO,
                                              **device_kwargs)
        base_seed = int(qwen_voice_fingerprint(
            f"{speaker}|{instruct}", 1), 16) % (2 ** 31)
        for i, chunk, part in todo:
            log(f"  part {i}/{len(chunks)} ({len(chunk):,} characters)")
            pieces, rate = [], 24000
            sampling = qwen_sampling_settings()
            for k, group in enumerate(group_sentences(chunk,
                                                      qwen_group_chars())):
                torch.manual_seed((base_seed + i * 1000 + k) % (2 ** 31))
                budget = max(2048, min(8192, len(group) * 2))
                wavs, rate = model.generate_custom_voice(
                    text=group, speaker=speaker,
                    instruct=instruct or None, language="English",
                    max_new_tokens=budget, **sampling)
                pieces.append((group, np.asarray(wavs[0], dtype=np.float32)
                               .reshape(-1)))
            pieces = [(t, trim_silence(a, rate)) for t, a in pieces]
            gap = np.zeros(int(rate * qwen_group_gap()), dtype=np.float32)
            audio = np.concatenate(
                [x for pair in pieces for x in (pair[1], gap)][:-1]
                if pieces else [np.zeros(1, dtype=np.float32)])
            sf.write(part, audio, rate)
            save_segments(part, segments_from_pieces(pieces, rate,
                                                     qwen_group_gap()))
        del model
        _free_gpu()
        return _join_chunk_wavs(chunk_paths, chunks, workdir)

    clone_repo = clone_repo or QWEN_CLONE_REPO
    if todo:
        # Stage 1 -- the voice itself (designed once, then saved).
        ref_wav, ref_text = ensure_qwen_voice(description, take, log,
                                              device_kwargs)

        # Stage 2 -- the clone model, and ONE prompt object reused for
        # every chunk. This is what makes the narrator consistent.
        log(f"  loading {clone_repo}")
        log("  (first run downloads several GB from Hugging Face)")
        model = Qwen3TTSModel.from_pretrained(clone_repo, **device_kwargs)
        prompt = model.create_voice_clone_prompt(
            ref_audio=ref_wav, ref_text=ref_text, x_vector_only_mode=False)

        base_seed = int(qwen_voice_fingerprint(description, take), 16) % (2 ** 31)
        for i, chunk, part in todo:
            log(f"  part {i}/{len(chunks)} ({len(chunk):,} characters)")
            # Each chunk is rendered as a few sentence groups rather than
            # one long generation: the clone prompt pins the voice either
            # way, shorter generations drift less, and it is what makes the
            # span of every sentence known exactly (for sentence-level
            # fixes) without any speech recognition.
            pieces, rate = [], 24000
            sampling = qwen_sampling_settings()
            for k, group in enumerate(group_sentences(chunk,
                                                      qwen_group_chars())):
                # Deterministic: re-rendering the same sentence of the same
                # document gives the same audio back.
                torch.manual_seed((base_seed + i * 1000 + k) % (2 ** 31))
                # Token budget: ~12 codec tokens per second of speech; the
                # package default of 2048 would cut off anything slow.
                budget = max(2048, min(8192, len(group) * 2))
                wavs, rate = model.generate_voice_clone(
                    text=group, language="English", voice_clone_prompt=prompt,
                    max_new_tokens=budget, **sampling)
                pieces.append((group, np.asarray(wavs[0], dtype=np.float32)
                               .reshape(-1)))
            # Same reasoning as between chunks: each group already ends
            # on its own sentence-final pause, so trim before adding the
            # seam rather than stacking one pause on another.
            pieces = [(t, trim_silence(a, rate)) for t, a in pieces]
            gap = np.zeros(int(rate * qwen_group_gap()), dtype=np.float32)
            audio = np.concatenate(
                [x for pair in pieces for x in (pair[1], gap)][:-1]
                if pieces else [np.zeros(1, dtype=np.float32)])
            sf.write(part, audio, rate)
            save_segments(part, segments_from_pieces(pieces, rate,
                                                     qwen_group_gap()))
        del model, prompt
        _free_gpu()

    return _join_chunk_wavs(chunk_paths, chunks, workdir)


# --- shared ---------------------------------------------------------------


# --- running an engine inside another virtual environment ------------------


def _run_worker_job(python_exe, job, log, label=None):
    """Shared mechanics for running part of this file inside another
    environment's Python: write the job, spawn `python -m narrator
    --worker jobfile`, relay PROGRESS lines into the log, read back the
    JSON result file. `_run_via_worker` (a full render) and
    `fetch_kokoro_voices` (a much smaller query) both go through this
    rather than duplicating the subprocess handling.
    """
    fd, jobfile = tempfile.mkstemp(suffix=".json", prefix="narrator_job_")
    os.close(fd)
    fd2, resultfile = tempfile.mkstemp(suffix=".json", prefix="narrator_result_")
    os.close(fd2)
    os.remove(resultfile)  # worker creates it only on success
    job = dict(job)
    job["result_file"] = resultfile
    label = label or job.get("engine", "?")

    try:
        with open(jobfile, "w", encoding="utf-8") as fh:
            json.dump(job, fh)

        log(f"  running {label} in its own environment")
        log(f"  ({python_exe})")

        # Invoke as a MODULE, not by file path. Now that this is a package,
        # running narrator/engines.py directly would break its relative
        # imports ("attempted relative import with no known parent
        # package"). PYTHONPATH points the other interpreter at the project
        # folder so it can find the package without the package being
        # installed in that venv -- which matters, because the Kokoro and
        # Qwen3 environments only ever have their engine installed, not this
        # app.
        pkg_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env = dict(os.environ)
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (pkg_root + os.pathsep + existing
                             if existing else pkg_root)

        proc = subprocess.Popen(
            [python_exe, "-m", "narrator", "--worker", jobfile],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, env=env,
            creationflags=_no_window())

        tail = []
        for line in proc.stdout:
            line = line.rstrip()
            if not line:
                continue
            tail.append(line)
            del tail[:-25]
            if line.startswith("PROGRESS "):
                log("  " + line[len("PROGRESS "):])
        proc.wait()

        if proc.returncode != 0 or not os.path.exists(resultfile):
            detail = "\n    ".join(tail[-12:]) or "no output"
            raise RuntimeError(
                f"{label} worker failed (exit {proc.returncode}):\n    "
                + detail)

        with open(resultfile, encoding="utf-8") as fh:
            return json.load(fh)
    finally:
        for f in (jobfile, resultfile):
            try:
                os.remove(f)
            except OSError:
                pass


def _run_via_worker(python_exe, engine_key, chunks, voice, speed, workdir,
                    log, extra=None):
    """Run an engine inside the interpreter that actually has it installed.

    This same file is re-invoked with --worker by that interpreter, so there
    is nothing extra to install in the other environment. Progress lines the
    worker prints are relayed into the app's log as they arrive. The worker
    writes its full result (chunk paths, durations, texts -- not just a
    single output path) to a small JSON file on the same filesystem, which
    this process reads back once the subprocess exits successfully.

    `extra` carries engine-specific options (Qwen3's take number, clone
    model and sampling settings) across to the worker. Everything in it
    must be JSON-serialisable.
    """
    job = {
        "engine": engine_key,
        "chunks": chunks,
        "voice": voice,
        "speed": speed,
        "workdir": workdir,
        "pronunciations": load_pronunciations() if engine_key == "kokoro"
                          else {},
    }
    job.update(extra or {})
    return _run_worker_job(python_exe, job, log, label=engine_key)


# Mirrors kokoro.pipeline.LANG_CODES / ALIASES (kokoro 0.9.4, verified
# against the installed package rather than assumed) -- kept as a small
# local copy instead of importing kokoro just for this, since that would
# need kokoro importable in THIS process even when it actually lives in a
# separate kokoro-env this process may not have access to.
KOKORO_LANGUAGES = {
    "a": "American English", "b": "British English", "e": "Spanish",
    "f": "French", "h": "Hindi", "i": "Italian",
    "p": "Portuguese (Brazil)", "j": "Japanese", "z": "Mandarin Chinese",
}
# These two need an extra package beyond what this app already sets up
# (espeak-ng, which covers e/f/h/i/p and English's own OOD fallback).
KOKORO_LANGUAGE_EXTRA_DEPS = {"j": "misaki[ja]", "z": "misaki[zh]"}


# Verified against kokoro 0.9.4's own source, not assumed: the model's hard
# ceiling is 510, and the unit is the LENGTH OF THE PHONEME STRING, not
# words, characters or subword tokens. KPipeline enforces it itself
# (pipeline.py: "if len(ps) > 510: ... Truncating"), and its en_tokenize()
# pre-splits at that same number using sentence-boundary "waterfall" logic.
KOKORO_TOKEN_LIMIT = 510
# The community's reported sweet spot -- close to the ceiling without
# risking it. Short generations have less prosodic context to work with,
# which is why very small parts can sound flatter.
KOKORO_TARGET_TOKENS = 500


def measure_kokoro_phonemes_local(texts, log=None):
    """Exact phoneme-string length for each text, using the same G2P
    Kokoro itself uses. model=False means only the (small) G2P front end
    loads -- this never downloads or touches the 300 MB voice model."""
    from kokoro import KPipeline
    pipeline = KPipeline(lang_code="a", model=False)
    counts = []
    for t in texts:
        try:
            ps, _ = pipeline.g2p(t)
            counts.append(len(ps or ""))
        except Exception:
            counts.append(-1)  # unmeasurable; caller falls back to estimate
    return counts


def measure_kokoro_phonemes(texts, log):
    """measure_kokoro_phonemes_local, run wherever kokoro actually is."""
    exe = external_python("kokoro")
    if exe:
        result = _run_worker_job(exe, {"action": "count_phonemes",
                                       "texts": list(texts)}, log,
                                 label="kokoro")
        return result["counts"]
    return measure_kokoro_phonemes_local(texts, log)


def kokoro_lookup_words(query, log, limit=150, overrides=None):
    """lookup_words, run wherever misaki actually is."""
    from .pronunciation import lookup_words
    exe = external_python("kokoro")
    if exe:
        return _run_worker_job(exe, {"action": "lookup_words",
                                     "query": query, "limit": limit,
                                     "overrides": overrides or {}},
                               log, label="kokoro")
    return lookup_words(query, limit, overrides)


def kokoro_words_phonemes(words, log, overrides=None):
    """phonemes_for_words, run wherever misaki actually is. One call for a
    whole sentence rather than one per word."""
    from .pronunciation import phonemes_for_words
    exe = external_python("kokoro")
    if exe:
        return _run_worker_job(exe, {"action": "phonemes_for_words",
                                     "words": list(words),
                                     "overrides": overrides or {}},
                               log, label="kokoro")
    return phonemes_for_words(words, overrides)


def kokoro_current_phonemes(word, log, overrides=None):
    """current_phonemes, run wherever misaki actually is."""
    from .pronunciation import current_phonemes
    exe = external_python("kokoro")
    if exe:
        return _run_worker_job(exe, {"action": "current_phonemes",
                                     "word": word,
                                     "overrides": overrides or {}},
                               log, label="kokoro")
    return current_phonemes(word, overrides)


def list_qwen_custom_speakers(log):
    """The CustomVoice model's actual speaker roster. NOT listed anywhere
    in the package -- only `model.get_supported_speakers()` on the loaded
    model knows, which means this loads the (multi-GB) CustomVoice model
    to find out. Only ever run when explicitly asked, and the result is
    cached (see qwen_custom_speakers() below) so it's a one-time cost.
    """
    from qwen_tts import Qwen3TTSModel
    device_kwargs = _qwen_device_kwargs(log)
    log(f"  loading {QWEN_CUSTOM_REPO} to ask it what speakers it has "
       "(this downloads it the first time)")
    model = Qwen3TTSModel.from_pretrained(QWEN_CUSTOM_REPO, **device_kwargs)
    getter = getattr(model, "get_supported_speakers", None)
    speakers = sorted(getter()) if getter else []
    log(f"  found {len(speakers)} speaker(s)")
    del model
    _free_gpu()
    return speakers


def fetch_qwen_custom_speakers(log):
    """list_qwen_custom_speakers, run wherever qwen-tts actually is."""
    exe = external_python("qwen3")
    if exe:
        result = _run_worker_job(exe, {"action": "list_custom_speakers"},
                                 log, label="qwen3")
        return result["speakers"]
    return list_qwen_custom_speakers(log)


def qwen_custom_speakers():
    """The cached speaker list, or [] if never fetched. Belongs in
    config.py's settings alongside everything else this app remembers."""
    from .config import load_settings
    return load_settings().get("qwen_custom_speakers") or []


def save_qwen_custom_speakers(speakers):
    from .config import load_settings, save_settings
    settings = load_settings()
    settings["qwen_custom_speakers"] = list(speakers)
    save_settings(settings)


def custom_voice_presets():
    """Saved (label, speaker, instruct) combinations -- a favourites list,
    not audio-artifact management: unlike a designed or cloned voice,
    speaker+instruct is already the whole, reproducible identity, so
    there's no reference clip or take to pin down and save."""
    from .config import load_settings
    return load_settings().get("custom_voice_presets") or []


def save_custom_voice_preset(label, speaker, instruct):
    from .config import load_settings, save_settings
    settings = load_settings()
    presets = [p for p in settings.get("custom_voice_presets", [])
              if p.get("label") != label]
    presets.append({"label": label, "speaker": speaker,
                    "instruct": instruct or "", "created": time.time()})
    settings["custom_voice_presets"] = presets
    save_settings(settings)
    return presets


def delete_custom_voice_preset(label):
    from .config import load_settings, save_settings
    settings = load_settings()
    presets = [p for p in settings.get("custom_voice_presets", [])
              if p.get("label") != label]
    settings["custom_voice_presets"] = presets
    save_settings(settings)
    return presets


def list_kokoro_voices(log):
    """Every voice file currently in the Kokoro-82M repo on Hugging Face --
    a live query (a fast file-listing call, not a download of the actual
    weights, so this is quick even on a slow connection), not the fixed
    set this app ships with by default. Requires internet."""
    from huggingface_hub import list_repo_files
    files = list_repo_files("hexgrad/Kokoro-82M")
    voices = sorted({m.group(1) for f in files
                     if (m := re.fullmatch(r"voices/([a-z]{2}_[a-z0-9]+)\.pt",
                                           f))})
    log(f"  found {len(voices)} voice(s) in the Hugging Face repo")
    return voices


def fetch_kokoro_voices(log):
    """list_kokoro_voices, run wherever huggingface_hub (a kokoro
    dependency) actually is -- in-process if kokoro is importable here,
    otherwise via the same cross-environment worker a render would use."""
    exe = external_python("kokoro")
    if exe:
        result = _run_worker_job(exe, {"action": "list_voices"}, log,
                                 label="kokoro")
        return result["voices"]
    return list_kokoro_voices(log)


def run_kokoro(chunks, voice, speed, log):
    workdir = cache_dir("kokoro", voice, speed, "".join(chunks))
    exe = external_python("kokoro")
    if exe:
        return _run_via_worker(exe, "kokoro", chunks, voice, speed,
                               workdir, log)
    return _run_kokoro_local(chunks, voice, speed, workdir, log)


def encode_custom_voice(speaker, instruct=""):
    """The single string a CustomVoice speaker+instruction is carried as
    everywhere `voice` is otherwise a plain description -- cfg, caches,
    the Voice tab's combobox. A prefix plus JSON rather than a hand-rolled
    delimiter, since an instruction line can contain anything.
    """
    return "custom:" + json.dumps({"speaker": speaker,
                                   "instruct": instruct or ""})


def decode_custom_voice(voice):
    """None if `voice` is an ordinary description; the {"speaker",
    "instruct"} dict if it is an encoded CustomVoice selection."""
    if not (voice or "").startswith("custom:"):
        return None
    try:
        return json.loads(voice[len("custom:"):])
    except (ValueError, TypeError):
        return None


def run_qwen(chunks, description, speed, log, take=1, clone_repo=None):
    custom = decode_custom_voice(description)
    if custom:
        voice_key = f"customvoice:{custom['speaker']}:{custom['instruct']}"
        workdir = cache_dir("qwen3", voice_key, speed, "".join(chunks))
        exe = external_python("qwen3")
        if exe:
            return _run_via_worker(exe, "qwen3", chunks, description, speed,
                                   workdir, log)
        return _run_qwen_local(chunks, description, speed, workdir, log)

    from .config import load_settings
    clone_repo = clone_repo or load_settings().get("qwen_clone_repo") or \
        QWEN_CLONE_REPO
    # "clone:" is part of the key on purpose: chunks rendered by the old
    # design-per-chunk code must never be picked up as "already rendered".
    voice_key = f"clone:{clone_repo}:take{take}:{description}"
    workdir = cache_dir("qwen3", voice_key, speed, "".join(chunks))
    exe = external_python("qwen3")
    if exe:
        return _run_via_worker(exe, "qwen3", chunks, description, speed,
                               workdir, log, extra={"take": take,
                                                    "clone_repo": clone_repo})
    return _run_qwen_local(chunks, description, speed, workdir, log,
                           take=take, clone_repo=clone_repo)


def run_audio8(chunks, voice_folder, speed, log, take=1):
    """`voice_folder` is a saved cloned-voice path -- Audio8 has no fixed
    preset speakers, only cloning, so unlike Kokoro/Qwen3 there is no
    other kind of `voice` value this could be. Dispatches to the isolated
    environment the same way Qwen3 does, and falls back to running
    in-process only if that environment isn't set up (which will then
    fail with a clear message rather than silently trying the wrong
    Python).
    """
    from .audio8_engine import AUDIO8_MAX_CHARS
    workdir = cache_dir("audio8", os.path.basename(voice_folder.rstrip(
        os.sep)), speed, "".join(chunks))
    exe = external_python("audio8")
    if exe:
        return _run_via_worker(exe, "audio8", chunks, voice_folder, speed,
                               workdir, log, extra={"take": take})
    from .audio8_engine import _run_audio8_local
    return _run_audio8_local(chunks, voice_folder, speed, workdir, log,
                             take=take)


def worker_main(jobfile):
    """Entry point when this file is run by another environment's Python."""
    with open(jobfile, encoding="utf-8") as fh:
        job = json.load(fh)

    def log(msg):
        print("PROGRESS " + str(msg), flush=True)

    if job.get("action") == "list_voices":
        result = {"voices": list_kokoro_voices(log)}
    elif job.get("action") == "list_custom_speakers":
        result = {"speakers": list_qwen_custom_speakers(log)}
    elif job.get("action") == "count_phonemes":
        result = {"counts": measure_kokoro_phonemes_local(job["texts"], log)}
    elif job.get("action") == "lookup_words":
        from .pronunciation import lookup_words
        result = lookup_words(job.get("query", ""), job.get("limit", 150),
                             job.get("overrides"))
    elif job.get("action") == "current_phonemes":
        from .pronunciation import current_phonemes
        result = current_phonemes(job["word"], job.get("overrides"))
    elif job.get("action") == "phonemes_for_words":
        from .pronunciation import phonemes_for_words
        result = phonemes_for_words(job["words"], job.get("overrides"))
    elif job["engine"] == "kokoro":
        if job.get("pronunciations"):
            # The worker has its own process, so hand the dictionary across
            # rather than relying on it reading the same file. It has to be
            # set on the config module -- that is where
            # load_pronunciations() looks -- not on a global here.
            from . import config as _config
            _config._WORKER_PRONUNCIATIONS = job["pronunciations"]
        result = _run_kokoro_local(job["chunks"], job["voice"], job["speed"],
                                   job["workdir"], log)
    elif job["engine"] == "qwen3":
        result = _run_qwen_local(job["chunks"], job["voice"], job["speed"],
                                 job["workdir"], log,
                                 take=job.get("take", 1),
                                 clone_repo=job.get("clone_repo"))
    elif job["engine"] == "audio8":
        from .audio8_engine import _run_audio8_local
        result = _run_audio8_local(job["chunks"], job["voice"],
                                   job["speed"], job["workdir"], log,
                                   take=job.get("take", 1))
    else:
        raise SystemExit(f"unknown engine {job['engine']!r}")

    with open(job["result_file"], "w", encoding="utf-8") as fh:
        json.dump(result, fh)
