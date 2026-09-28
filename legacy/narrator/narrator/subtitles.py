"""Subtitle generation.

Two sources of timing: edge-tts returns real word-level timings that
need merging and offsetting across chunks, while Kokoro and Qwen3
return none -- but we know exactly which text produced which chunk
and how long it ran, so captions are built from that instead.
"""

import os
import re

from .config import _no_window


def _srt_time(seconds):
    ms = round(seconds * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _parse_srt_time(text):
    h, m, rest = text.split(":")
    s, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def merge_subtitles(audio_parts, srt_parts, out_path):
    """Concatenate per-chunk SRT files, shifting each by the real duration
    of every audio part before it so timestamps stay aligned with the
    single joined audio file rather than each restarting at zero."""
    offset = 0.0
    counter = 1
    blocks = []

    for audio_path, srt_path in zip(audio_parts, srt_parts):
        if os.path.exists(srt_path):
            raw = open(srt_path, encoding="utf-8").read().strip()
            for block in re.split(r"\n\s*\n", raw):
                lines = block.strip().split("\n")
                if len(lines) < 2:
                    continue
                time_line = next((l for l in lines if "-->" in l), None)
                if not time_line:
                    continue
                start_s, end_s = [t.strip() for t in time_line.split("-->")]
                start = _parse_srt_time(start_s) + offset
                end = _parse_srt_time(end_s) + offset
                text_lines = lines[lines.index(time_line) + 1:]
                blocks.append(
                    f"{counter}\n{_srt_time(start)} --> {_srt_time(end)}\n"
                    + "\n".join(text_lines))
                counter += 1

        from .audio import duration_of
        dur = duration_of(audio_path)
        offset += dur if dur else 0.0

    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("\n\n".join(blocks) + "\n")


def _chunk_srt_time(seconds):
    ms = round(seconds * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_chunk_srt(texts, durations, out_path, gap_seconds=0.0,
                    offset=0.0):
    """One caption per chunk, timed from the exact durations the engine
    produced. This is how Kokoro and Qwen3 get captions at all: neither
    engine returns word-level timing the way edge-tts's own service does, but
    we don't need transcription to caption our own generated audio -- we
    already know precisely which text produced which segment and exactly how
    long that segment is, because we generated both. Coarser than word-level
    (one caption per sentence rather than per word), but genuinely
    synchronised and often more readable as captions besides.

    gap_seconds must match whatever silence the engine actually inserted
    between chunks (0.35s for Kokoro/Qwen3, 0 for edge-tts) or captions will
    drift out of sync with the joined audio as more chunks accumulate.
    """
    blocks = []
    for i, (text, dur) in enumerate(zip(texts, durations), 1):
        text = text.strip()
        if not text:
            offset += (dur or 0) + gap_seconds
            continue
        start, end = offset, offset + (dur or 0)
        blocks.append(f"{i}\n{_chunk_srt_time(start)} --> "
                      f"{_chunk_srt_time(end)}\n{text}")
        offset = end + gap_seconds
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("\n\n".join(blocks) + "\n")
    return out_path


def shift_srt(path, offset):
    """Move every timestamp in an SRT later by `offset` seconds, in place.

    Needed because an intro is prepended to the finished audio AFTER the
    captions were timed against the narration alone -- without this, every
    caption would run early by exactly the length of the intro.
    """
    if not offset or not os.path.exists(path):
        return path
    raw = open(path, encoding="utf-8").read().strip()
    blocks = []
    for block in re.split(r"\n\s*\n", raw):
        lines = block.strip().split("\n")
        time_line = next((l for l in lines if "-->" in l), None)
        if not time_line:
            continue
        start_s, end_s = [t.strip() for t in time_line.split("-->")]
        start = _parse_srt_time(start_s) + offset
        end = _parse_srt_time(end_s) + offset
        idx = lines.index(time_line)
        blocks.append("\n".join(lines[:idx])
                      + ("\n" if idx else "")
                      + f"{_srt_time(start)} --> {_srt_time(end)}\n"
                      + "\n".join(lines[idx + 1:]))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n\n".join(blocks) + "\n")
    return path
