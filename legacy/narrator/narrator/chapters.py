"""Chapter markers: locating each heading of the source document inside a
rendered take, and turning that into a YouTube description block or
markers embedded in the audio file itself.

No new pipeline runs for this -- it rides entirely on the manifest
(segments.py) and the `headings_out` side-channel `clean_document()` can
now optionally fill in (documents.py). A heading that can't be confidently
located is left out rather than guessed at: an incomplete chapter list is
a minor gap, a wrong timestamp is actively misleading.

The mp3/m4a embedding calls here were built against the real packages,
not from memory -- mutagen's CHAP/CTOC field names, and whether ffmpeg's
-map_metadata alone (vs. also needing -map_chapters) actually carries
chapters from an FFMETADATA file, were both confirmed by writing a file
and reading it back with an independent tool (ffprobe) before this was
written the way it now is.
"""

import os
import shutil
import subprocess
import tempfile

from .config import _no_window, have_ffmpeg


def compute_chapters(last_render):
    """Best-effort [{"title", "level", "seconds"}, ...] for the headings of
    last_render's source document, in order. [] if there's no source
    document on record, it's gone, or it has no headings with body text
    after them.
    """
    from .documents import clean_document
    from .segments import build_manifest

    source = last_render.get("source_path")
    if not source or not os.path.isfile(source):
        return []
    headings = []
    try:
        # The same call (same defaults) real narration already used, so
        # this text is identical to what was actually chunked and
        # rendered -- headings_out is a pure side channel, it changes
        # nothing about the returned text.
        clean_document(source, headings_out=headings)
    except Exception:
        return []
    if not headings:
        return []

    manifest = build_manifest(last_render)
    search_from = {}
    chapters = []
    for title, level, hint in headings:
        if not hint:
            continue
        for chunk in manifest["chunks"]:
            start_at = search_from.get(chunk["index"], 0)
            pos = chunk["text"].find(hint, start_at)
            if pos < 0:
                continue
            search_from[chunk["index"]] = pos + 1
            chapters.append({"title": title, "level": level,
                            "seconds": _locate_in_chunk(chunk, pos)})
            break
    chapters.sort(key=lambda c: c["seconds"])
    return chapters


def _locate_in_chunk(chunk, offset):
    """Which segment of `chunk` covers character `offset` of its text,
    walking segments in the order they were recorded and matching against
    their OWN text lengths. Correct regardless of how finely -- or by
    whose sentence-splitting rules -- that particular engine actually
    segmented the chunk: this never assumes segment boundaries match any
    particular re-splitting of the text, only that segment texts, joined
    by roughly a single space, reconstruct the chunk in order (true for
    all three engines by construction, since every one of them builds its
    segments by working through that same chunk's text)."""
    segs = chunk.get("segments") or []
    if not segs:
        return chunk["start"]
    pos = 0
    for seg in segs:
        seg_len = len(seg["text"])
        if pos <= offset < pos + seg_len:
            return seg["abs_start"]
        pos += seg_len + 1  # +1: the single space assumed between segments
    return segs[-1]["abs_start"]


def _format_time(seconds, force_hours=False):
    seconds = max(0, int(round(seconds)))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h or force_hours:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def format_youtube_chapters(chapters, intro_label="Introduction"):
    """The description-box text YouTube parses into a chapter list.
    YouTube requires the FIRST timestamp to be exactly 0:00 and at least
    three entries total, or it silently shows no chapters at all -- both
    are handled here rather than left to be discovered by trial and
    error."""
    if not chapters:
        return ""
    rows = [dict(c) for c in chapters]
    if rows[0]["seconds"] > 1.5:
        rows.insert(0, {"title": intro_label, "seconds": 0.0})
    else:
        rows[0]["seconds"] = 0.0
    force_hours = rows[-1]["seconds"] >= 3600
    lines = [f"{_format_time(r['seconds'], force_hours)} {r['title']}"
            for r in rows]
    if len(rows) < 3:
        lines += ["", "(YouTube needs at least 3 marks to turn these into "
                      "clickable chapters -- fine as a plain timestamp "
                      "list otherwise, but it won't get the chapter UI.)"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Embedding into the audio file itself


def _chapter_bounds_ms(chapters, total_seconds):
    """[(title, start_ms, end_ms), ...] -- each chapter runs to the next
    one's start, the last to the end of the file."""
    out = []
    for i, ch in enumerate(chapters):
        start = int(round(ch["seconds"] * 1000))
        end = (int(round(chapters[i + 1]["seconds"] * 1000))
              if i + 1 < len(chapters) else int(round(total_seconds * 1000)))
        out.append((ch["title"], start, max(end, start + 1)))
    return out


def write_ffmetadata(chapters, total_seconds, path):
    """FFMETADATA1 chapter file ffmpeg can mux into a container (m4a)."""
    lines = [";FFMETADATA1"]
    for title, start_ms, end_ms in _chapter_bounds_ms(chapters, total_seconds):
        esc = (title.replace("\\", "\\\\").replace("=", "\\=")
              .replace(";", "\\;").replace("#", "\\#").replace("\n", " "))
        lines += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={start_ms}",
                 f"END={end_ms}", f"title={esc}"]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def embed_chapters_m4a(audio_path, chapters, total_seconds):
    if not have_ffmpeg():
        raise RuntimeError("ffmpeg isn't available, so chapters can't be "
                           "embedded (the audio file itself is unaffected).")
    with tempfile.TemporaryDirectory() as td:
        meta = write_ffmetadata(chapters, total_seconds,
                                os.path.join(td, "chapters.txt"))
        out = os.path.join(td, "out.m4a")
        r = subprocess.run(
            ["ffmpeg", "-y", "-i", audio_path, "-i", meta,
             "-map_metadata", "1", "-c", "copy", out],
            capture_output=True, text=True, creationflags=_no_window())
        if r.returncode != 0 or not os.path.isfile(out):
            raise RuntimeError("ffmpeg couldn't embed the chapters:\n" +
                              r.stderr[-800:])
        shutil.move(out, audio_path)
    return audio_path


def embed_chapters_mp3(audio_path, chapters, total_seconds):
    try:
        from mutagen.id3 import ID3, ID3NoHeaderError, CHAP, CTOC, \
            CTOCFlags, TIT2
    except ImportError:
        raise RuntimeError(
            "Embedding chapters into mp3 needs the 'mutagen' package, "
            "which isn't installed.\n\nInstall it from Tools -> "
            "Components and add-ons (one click), or run "
            "'pip install mutagen' yourself.\n\nIt isn't bundled because "
            "it's GPL-2.0. Chapters in m4a files work without it.")
    try:
        tags = ID3(audio_path)
    except ID3NoHeaderError:
        tags = ID3()
    child_ids = []
    for i, (title, start_ms, end_ms) in enumerate(
            _chapter_bounds_ms(chapters, total_seconds)):
        cid = f"chp{i}"
        child_ids.append(cid)
        tags.add(CHAP(element_id=cid, start_time=start_ms, end_time=end_ms,
                      start_offset=0xffffffff, end_offset=0xffffffff,
                      sub_frames=[TIT2(text=[title])]))
    tags.add(CTOC(element_id="toc",
                 flags=CTOCFlags.TOP_LEVEL | CTOCFlags.ORDERED,
                 child_element_ids=child_ids,
                 sub_frames=[TIT2(text=["Chapters"])]))
    tags.save(audio_path)
    return audio_path


def embed_chapters(audio_path, chapters, total_seconds):
    """Dispatches on the file extension. Raises RuntimeError with a plain
    explanation for anything that can't be done, rather than failing
    silently or half-writing the file."""
    if not chapters:
        raise RuntimeError("No chapters to embed -- generate the chapter "
                           "list first.")
    ext = os.path.splitext(audio_path)[1].lower()
    if ext == ".m4a":
        return embed_chapters_m4a(audio_path, chapters, total_seconds)
    if ext == ".mp3":
        return embed_chapters_mp3(audio_path, chapters, total_seconds)
    raise RuntimeError(f"Chapter embedding isn't supported for '{ext}' "
                       "files -- mp3 and m4a are. The YouTube chapter "
                       "text still works regardless of output format.")
