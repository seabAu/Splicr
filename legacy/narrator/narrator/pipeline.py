"""Engine registry and the render pipeline: which engine runs, and how
one chunk gets regenerated and spliced back into a finished take.
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
import wave

from .config import have_kokoro, have_qwen, have_edge, have_audio8
from .audio import finalize_render
from .engines import (run_kokoro, run_qwen, run_edge, run_audio8,
                      rejoin_master)
from .config import KOKORO_VOICES, QWEN_VOICES, EDGE_VOICES


# ---------------------------------------------------------------------------
# Engine registry
# ---------------------------------------------------------------------------

ENGINES = {
    "Kokoro (offline, best all-round)": {
        "key": "kokoro",
        "detect": have_kokoro,
        "voices": KOKORO_VOICES,
        "editable": False,
        "chunk": 20000,
        "run": lambda c, v, pct, log, **kw: run_kokoro(
            c, v, 1.0 + pct / 100.0, log),
        "hint": "Offline. No drift on long files. Fixed voices.",
    },
    "Qwen3-TTS (offline, designed voices)": {
        "key": "qwen3",
        "detect": have_qwen,
        "voices": QWEN_VOICES,
        "editable": True,
        # Autoregressive, so it drifts on long generations, and its token
        # budget caps a single call at a few minutes of speech: keep chunks
        # to about two minutes of narration.
        "chunk": 1500,
        "run": lambda c, v, pct, log, **kw: run_qwen(
            c, v, 1.0 + pct / 100.0, log, take=kw.get("take", 1)),
        "hint": ("Describe the voice in your own words. It is designed once, "
                 "saved, and cloned for every part, so the narrator stays "
                 "the same throughout. Not right? Try the next take."),
    },
    "Audio8-TTS (offline, voice cloning, Preview)": {
        "key": "audio8",
        "detect": have_audio8,
        # Cloning-only: no fixed preset list, so the "voices" a settings
        # form would offer come from Voice studio's saved-voice list,
        # filtered to this engine -- not a static table like the others.
        "voices": [],
        "editable": True,
        # The engine's own 150-char cap is handled internally per-sentence
        # (audio8_engine._audio8_chunks); this is the document-splitting
        # chunk size, kept modest since it's an autoregressive model with
        # the same drift-on-long-runs shape as Qwen3.
        "chunk": 1500,
        "run": lambda c, v, pct, log, **kw: run_audio8(
            c, v, 1.0 + pct / 100.0, log, take=kw.get("take", 1)),
        "hint": ("Preview quality: clones a voice from a short recording "
                 "you provide, similar to Qwen3 but lighter-weight. "
                 "Occasional unstable output is retried automatically. "
                 "Not a default narrator -- use Kokoro or Qwen3 for that."),
    },
    "edge-tts (online, fastest setup)": {
        "key": "edge",
        "detect": have_edge,
        "voices": EDGE_VOICES,
        "editable": False,
        "chunk": 4000,
        "run": lambda c, v, pct, log, **kw: run_edge(
            c, v, pct, log, want_subtitles=kw.get("subtitles", False)),
        "hint": "Needs internet. Resumes if a connection drops.",
    },
}

# Reverse lookup by short key ("kokoro"/"qwen3"/"edge") rather than the
# display label, so code that only knows which engine produced a past render
# (resplice_chunk) can still call back into it correctly.
ENGINE_BY_KEY = {s["key"]: s for s in ENGINES.values()}


def resplice_chunk(last_render, chunk_index, new_text, log):
    """Regenerate exactly one chunk of an already-finished render and splice
    it back in -- every other chunk's audio is untouched and not
    regenerated. Rebuilds the master, then re-runs the same finalize step
    (format, subtitles, kept chunks, video) that produced the original
    output, overwriting it in place rather than creating a new file.

    Reuses the engine's own "run" entry from ENGINES rather than calling
    run_kokoro/run_qwen/run_edge directly, so a single-chunk regeneration
    goes through the exact same speed-conversion and subtitle-flag handling
    as a normal render -- nothing here can quietly drift out of sync with
    how generation normally works.
    """
    s = ENGINE_BY_KEY[last_render["engine_key"]]
    result = last_render["result"]

    single = s["run"]([new_text], last_render["voice"], last_render["speed"],
                      log, subtitles=False, take=last_render.get("take", 1))
    if not single or not single.get("chunk_paths"):
        raise RuntimeError(
            "Regenerating that chunk produced no audio; nothing was "
            "changed, the previous take is untouched.")

    result["chunk_paths"][chunk_index] = single["chunk_paths"][0]
    result["chunk_texts"][chunk_index] = new_text
    result["chunk_durations"][chunk_index] = single["chunk_durations"][0]
    if single.get("segments"):
        result.setdefault("segments", [None] * len(result["chunk_paths"]))
        result["segments"][chunk_index] = single["segments"][0]
    # Any previously-merged word-level SRT (edge-tts) no longer lines up
    # after a splice; finalize_render falls back to chunk-level captions
    # built fresh from the (now updated) chunk texts and durations.
    result["native_srt"] = None

    log("Rebuilding the full take with the fixed chunk...")
    workdir = os.path.dirname(result["master"])
    result["master"] = rejoin_master(result["chunk_paths"], workdir,
                                     result.get("chunk_gap", 0.0), log)

    out = finalize_render(result, last_render["cfg"], last_render["folder"],
                          last_render["stem"], log,
                          existing_path=last_render["out_path"])
    from .segments import write_manifest
    write_manifest(last_render)
    return out


def resplice_segment(last_render, chunk_index, seg_index, new_text, log,
                     retry=0):
    """Re-record ONE sentence of a finished take and splice it into its
    chunk. Only that sentence is regenerated; the rest of the chunk's audio
    is bytes-identical, and every other chunk is untouched.

    The sentence is rendered as a one-chunk job through the engine's normal
    entry point (same voice, take, speed, pronunciations), then level-matched
    and crossfaded into the chunk at the span recorded when the chunk was
    first rendered. The edited chunk is written as a NEW file beside the
    original, so the cache still holds the untouched render of the source
    document. `retry` changes nothing but the cache key, which is what "try
    that sentence again" needs when the text itself was fine.
    """
    from .segments import (replace_span, apply_replacement, load_segments,
                           save_segments, write_manifest)

    s = ENGINE_BY_KEY[last_render["engine_key"]]
    result = last_render["result"]
    chunk_path = result["chunk_paths"][chunk_index]
    if not os.path.isfile(chunk_path):
        raise RuntimeError(
            "That chunk's cached audio is gone (the cache was cleared), so "
            "there is nothing to splice into. Use 'Regenerate this chunk' "
            "instead.")
    if not chunk_path.lower().endswith(".wav"):
        raise RuntimeError(
            "Sentence-level fixes work on the offline engines (Kokoro, "
            "Qwen3). edge-tts chunks are compressed mp3; use 'Regenerate "
            "this chunk' for those.")

    segs = (result.get("segments") or [None] * len(result["chunk_paths"]))[chunk_index] \
        or load_segments(chunk_path, result["chunk_texts"][chunk_index],
                         result["chunk_durations"][chunk_index])
    if not 0 <= seg_index < len(segs):
        raise IndexError("no such sentence in that chunk")
    target = segs[seg_index]

    # A retry counter rides along in the text seen by the cache key only:
    # trailing spaces change the fingerprint but not what is spoken.
    render_text = new_text + (" " * retry)
    single = s["run"]([render_text], last_render["voice"], last_render["speed"],
                      log, subtitles=False, take=last_render.get("take", 1))
    if not single or not single.get("chunk_paths"):
        raise RuntimeError(
            "Regenerating that sentence produced no audio; nothing was "
            "changed, the previous take is untouched.")

    base = re.sub(r"\.fix\d+$", "", os.path.splitext(chunk_path)[0])
    n = 1
    while os.path.exists(edited := f"{base}.fix{n}.wav"):
        n += 1
    log(f"  splicing the new sentence into part {chunk_index + 1} at "
        f"{target['start']:.2f}-{target['end']:.2f}s")
    new_dur, span_end = replace_span(chunk_path, target["start"],
                                     target["end"], single["chunk_paths"][0],
                                     edited)
    new_segs = apply_replacement(segs, seg_index, new_text, span_end, new_dur)
    save_segments(edited, new_segs)

    result["chunk_paths"][chunk_index] = edited
    result["chunk_durations"][chunk_index] = new_dur
    result["chunk_texts"][chunk_index] = " ".join(x["text"] for x in new_segs)
    result.setdefault("segments", [None] * len(result["chunk_paths"]))
    result["segments"][chunk_index] = new_segs
    result["native_srt"] = None

    log("Rebuilding the full take with the fixed sentence...")
    workdir = os.path.dirname(result["master"])
    result["master"] = rejoin_master(result["chunk_paths"], workdir,
                                     result.get("chunk_gap", 0.0), log)
    out = finalize_render(result, last_render["cfg"], last_render["folder"],
                          last_render["stem"], log,
                          existing_path=last_render["out_path"])
    write_manifest(last_render)
    return out
