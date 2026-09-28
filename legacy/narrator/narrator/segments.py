"""Sentence-level structure of a render, and the splice that replaces one
sentence inside a chunk without touching anything else.

Why this exists: "Fix a chunk" regenerates a whole chunk (up to two minutes
of audio) to correct one word. Because the engines build each chunk from
sentences we hand them, the start and end of every sentence *inside* a chunk
is known exactly at render time -- no speech recognition or forced
alignment needed. This module records those boundaries, keeps them on disk
beside the chunk audio (so resumed and cached renders still have them), and
does the surgery when one sentence is re-recorded.

A segment is a dict: {"text": str, "start": float, "end": float}, with times
in seconds from the start of *its chunk's audio file*. The take manifest
(write_manifest) adds absolute times in the joined master.

Nothing here imports tkinter; the worker uses it.
"""

import json
import os
import re

import numpy as np

# --- sidecar files ---------------------------------------------------------


def sidecar_path(chunk_path):
    return os.path.splitext(chunk_path)[0] + ".segments.json"


def save_segments(chunk_path, segments):
    with open(sidecar_path(chunk_path), "w", encoding="utf-8") as fh:
        json.dump(segments, fh, ensure_ascii=False, indent=1)


def load_segments(chunk_path, text=None, duration=None):
    """Segments for a chunk file, or -- when no sidecar exists (chunk was
    rendered before this module) -- one segment spanning the whole chunk,
    so every caller can rely on at least one."""
    p = sidecar_path(chunk_path)
    if os.path.isfile(p):
        try:
            with open(p, encoding="utf-8") as fh:
                segs = json.load(fh)
            if segs:
                return segs
        except (OSError, ValueError):
            pass
    return [{"text": text or "", "start": 0.0, "end": float(duration or 0.0)}]


def segments_from_pieces(pieces, rate, gap_seconds=0.0):
    """Build segments from a list of (text, audio_array) already laid out
    back to back with `gap_seconds` of silence between them -- the shape
    Kokoro's pipeline and the Qwen3 sentence loop both produce."""
    # Kokoro splits on its own rules, which can leave a stray "Dr." or a
    # two-word fragment as a piece of its own. Fold anything under three
    # words into the piece that follows, so the list reads as sentences.
    merged = []
    for text, audio in pieces:
        if merged and len(merged[-1][0].split()) < 3:
            ptext, paudio = merged.pop()
            text, audio = (ptext + " " + text).strip(), np.concatenate([paudio, audio])
        merged.append((text, audio))
    pieces = merged
    segs, pos = [], 0
    gap = int(rate * gap_seconds)
    for k, (text, audio) in enumerate(pieces):
        n = int(len(audio))
        segs.append({"text": text, "start": pos / rate, "end": (pos + n) / rate})
        pos += n + (gap if k < len(pieces) - 1 else 0)
    return segs


_WORD = re.compile(r"[\w']+")


def segments_from_word_srt(chunk_text, srt_path, split_sentences):
    """edge-tts writes one cue per spoken word. Walk the sentences of the
    chunk and hand each one the cues for its words. Returns None when the
    counts don't line up (edge normalises numbers and abbreviations into
    different word counts), and the caller falls back to one segment."""
    from .subtitles import _parse_srt_time
    try:
        with open(srt_path, encoding="utf-8") as fh:
            raw = fh.read()
    except OSError:
        return None
    cues = []
    for block in re.split(r"\n\s*\n", raw.strip()):
        lines = [l for l in block.splitlines() if l.strip()]
        if len(lines) < 3 or "-->" not in lines[1]:
            continue
        a, b = [t.strip() for t in lines[1].split("-->")]
        cues.append((_parse_srt_time(a), _parse_srt_time(b),
                     " ".join(lines[2:])))
    sentences = split_sentences(chunk_text.replace("\n", " "))
    words_per = [len(_WORD.findall(s)) for s in sentences]
    if not cues or sum(words_per) != len(cues):
        return None
    segs, i = [], 0
    for s, n in zip(sentences, words_per):
        if n == 0:
            continue
        segs.append({"text": s, "start": cues[i][0], "end": cues[i + n - 1][1]})
        i += n
    return segs or None


def group_sentences(text, limit):
    """Sentences packed into groups of at most `limit` characters, whole
    sentences only. One sentence longer than the limit is its own group."""
    from .documents import split_sentences
    groups, cur = [], ""
    for para in text.split("\n\n"):
        for s in split_sentences(para):
            if cur and len(cur) + len(s) + 1 > limit:
                groups.append(cur.strip())
                cur = ""
            cur += s + " "
    if cur.strip():
        groups.append(cur.strip())
    return groups or [text.strip()]


# --- splicing ----------------------------------------------------------------


def _read(path):
    import soundfile as sf
    data, rate = sf.read(path, dtype="float32")
    if data.ndim > 1:
        data = data.mean(axis=1)
    return data, rate


def _rms(x):
    return float(np.sqrt(np.mean(np.square(x)))) if len(x) else 0.0


def _resample(x, src, dst):
    if src == dst:
        return x
    n = int(round(len(x) * dst / src))
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)),
                     x).astype(np.float32)


def replace_span(chunk_path, start, end, new_audio_path, out_path,
                 fade_ms=20, max_gain_db=6.0):
    """Write out_path = chunk audio with [start, end] seconds replaced by the
    audio in new_audio_path. The new piece is level-matched to what it
    replaces (capped so a mis-rendered near-silent take can't be boosted
    into noise) and joined with short linear crossfades so the seams are
    inaudible. Returns (new_chunk_duration, new_span_end): the replaced span
    now ends at `new_span_end` seconds, and everything after it has moved
    by the difference."""
    import soundfile as sf
    old, rate = _read(chunk_path)
    new, nrate = _read(new_audio_path)
    new = _resample(new, nrate, rate)

    a = max(0, min(len(old), int(round(start * rate))))
    b = max(a, min(len(old), int(round(end * rate))))

    # Trim leading/trailing silence from the new take so its edges sit where
    # speech starts and stops, the same way the neighbours' edges do.
    if len(new):
        thresh = max(1e-4, np.abs(new).max() * 0.02)
        loud = np.flatnonzero(np.abs(new) > thresh)
        if len(loud):
            pad = int(rate * 0.03)
            new = new[max(0, loud[0] - pad):min(len(new), loud[-1] + pad)]

    old_rms, new_rms = _rms(old[a:b]), _rms(new)
    if old_rms > 1e-5 and new_rms > 1e-5:
        gain = old_rms / new_rms
        cap = 10 ** (max_gain_db / 20)
        new = new * float(min(cap, max(1 / cap, gain)))

    fade = min(int(rate * fade_ms / 1000), len(new) // 4, a, len(old) - b)
    head, tail = old[:a].copy(), old[b:].copy()
    piece = new.copy()
    if fade > 0:
        ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)
        piece[:fade] = piece[:fade] * ramp + head[-fade:] * (1 - ramp)
        head = head[:-fade]
        piece[-fade:] = piece[-fade:] * (1 - ramp) + tail[:fade] * ramp
        tail = tail[fade:]
    out = np.concatenate([head, piece, tail]).astype(np.float32)
    np.clip(out, -1.0, 1.0, out=out)
    sf.write(out_path, out, rate)
    return len(out) / rate, (len(head) + len(piece)) / rate


def apply_replacement(segments, index, new_text, new_span_end,
                      new_chunk_duration):
    """Rewrite one segment after replace_span and shift the ones after it."""
    old = segments[index]
    delta = new_span_end - old["end"]
    segs = [dict(s) for s in segments]
    segs[index] = {"text": new_text, "start": old["start"], "end": new_span_end}
    for s in segs[index + 1:]:
        s["start"] += delta
        s["end"] += delta
    if segs:
        segs[-1]["end"] = min(segs[-1]["end"], new_chunk_duration) \
            if index != len(segs) - 1 else new_span_end
    return segs


def export_span(chunk_path, start, end, out_path):
    """Write just [start, end] of a chunk to its own WAV, for listening."""
    import soundfile as sf
    data, rate = _read(chunk_path)
    a, b = int(max(0, start) * rate), int(min(end * rate, len(data)))
    sf.write(out_path, data[a:b], rate)
    return out_path


# --- the take manifest --------------------------------------------------------


def build_manifest(last_render):
    """Everything the timeline editor needs, with absolute times: chunk
    order, per-sentence spans, and where each lands in the joined master
    (chunk audio laid end to end with the engine's gap between chunks)."""
    r = last_render["result"]
    gap = float(r.get("chunk_gap", 0.0))
    # An intro prepended during finalize_render shifted the whole narration
    # later in the finished file. Absolute times here must match THAT file,
    # since that is what chapter marks point into and what the timeline
    # editor will scrub. Times inside each chunk stay chunk-relative.
    chunks, t = [], float(r.get("intro_offset", 0.0) or 0.0)
    segs_all = r.get("segments") or [None] * len(r["chunk_paths"])
    for i, path in enumerate(r["chunk_paths"]):
        dur = float(r["chunk_durations"][i] or 0.0)
        segs = segs_all[i] or load_segments(path, r["chunk_texts"][i], dur)
        chunks.append({
            "index": i, "audio": path, "text": r["chunk_texts"][i],
            "start": t, "end": t + dur, "duration": dur,
            "segments": [{"text": s["text"], "start": s["start"],
                          "end": s["end"], "abs_start": t + s["start"],
                          "abs_end": t + s["end"]} for s in segs],
        })
        t += dur + (gap if i < len(r["chunk_paths"]) - 1 else 0.0)
    return {
        "format": 1,
        "output": last_render["out_path"],
        "source": last_render.get("source_path"),
        "engine": last_render["engine_key"], "voice": last_render["voice"],
        "take": last_render.get("take", 1), "speed": last_render["speed"],
        "master": r["master"], "chunk_gap": gap, "native_srt": r.get("native_srt"),
        "cfg": last_render.get("cfg", {}),
        "folder": last_render["folder"], "stem": last_render["stem"],
        "duration": t, "chunks": chunks,
        "intro_offset": float(r.get("intro_offset", 0.0) or 0.0),
    }


def manifest_path(last_render):
    return os.path.join(last_render["folder"],
                        last_render["stem"] + ".manifest.json")


def write_manifest(last_render):
    path = manifest_path(last_render)
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(build_manifest(last_render), fh, ensure_ascii=False,
                      indent=1, default=str)
    except (OSError, TypeError):
        return None
    return path


def load_manifest(path):
    """Rebuild a last_render dict from a manifest, so a take can be fixed
    after the app was closed -- as long as its chunk audio is still in the
    cache."""
    with open(path, encoding="utf-8") as fh:
        m = json.load(fh)
    result = {
        "master": m["master"],
        "chunk_paths": [c["audio"] for c in m["chunks"]],
        "chunk_texts": [c["text"] for c in m["chunks"]],
        "chunk_durations": [c["duration"] for c in m["chunks"]],
        "segments": [[{"text": s["text"], "start": s["start"], "end": s["end"]}
                      for s in c["segments"]] for c in m["chunks"]],
        "native_srt": m.get("native_srt"), "chunk_gap": m.get("chunk_gap", 0.0),
        "intro_offset": m.get("intro_offset", 0.0),
    }
    return {
        "engine_key": m["engine"], "voice": m["voice"], "speed": m["speed"],
        "take": m.get("take", 1), "cfg": m.get("cfg", {}),
        "folder": m["folder"], "stem": m["stem"], "out_path": m["output"],
        "result": result, "source_path": m.get("source"),
    }
