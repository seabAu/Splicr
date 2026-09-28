"""The things Narrator *does*, apart from rendering.

Each of these was a closure in a Tk dialog: gather some inputs, call an
already-clean module, report the result. The modules underneath
(`publish`, `chapters`, `transcribe`, `audiogram`) were always
UI-agnostic; the orchestration around them was not, so a second interface
would have had to rewrite the glue even though the hard parts were
reusable.

Every function here takes plain values and a `log` callable, returns
plain data, and raises with a message meant for a person. No tkinter, no
threads: threading is the interface's business, since a web backend and a
desktop app handle it completely differently.
"""

import os

from . import chapters as chapters_mod
from . import publish as publish_mod
from . import transcribe as transcribe_mod
from .config import unique_path
from .audio import duration_of


def publish_take(take, title, notes, log):
    """Add a finished take to the podcast feed and rebuild it.

    Returns {"episode", "feed", "missing", "format_warning"}. `missing`
    lists channel fields still unset -- publishing deliberately still
    works without them, since seeing the draft feed is often how you
    notice what's missing.
    """
    episode = publish_mod.episode_from_render(take, title, notes)
    publish_mod.add_episode(episode)
    feed, missing = publish_mod.write_feed(take["cfg"]["root"])
    log(f"Published episode {episode['episode_number']}: {episode['title']}")
    log(f"  feed rebuilt: {feed}")
    if missing:
        log("  Note: the feed is still missing " + ", ".join(missing)
           + " -- add these before submitting it anywhere.")

    ext = os.path.splitext(episode["audio_relpath"])[1].lower()
    warning = None
    if ext not in publish_mod.WIDELY_SUPPORTED:
        warning = (f"'{ext}' isn't accepted by most podcast directories -- "
                   "mp3 or m4a is safest for episodes you intend to submit.")
        log("  Note: " + warning)
    return {"episode": episode, "feed": feed, "missing": missing,
            "format_warning": warning}


def chapters_for_take(take, log=lambda _m: None):
    """(marks, formatted_text) for a take, or ([], "") when none of its
    headings could be placed."""
    marks = chapters_mod.compute_chapters(take)
    if not marks:
        log("Chapters: none found.")
        return [], ""
    log(f"Chapters: found {len(marks)}, matched to this take's timing.")
    return marks, chapters_mod.format_youtube_chapters(marks)


def embed_chapters_in_take(take, log):
    """Write chapter marks into the take's own audio file. Raises
    RuntimeError with an explanation if the format can't carry them or a
    needed component is missing."""
    marks, _text = chapters_for_take(take, log)
    if not marks:
        raise RuntimeError(
            "No headings from this document could be matched against this "
            "take, so there are no chapters to embed.")
    total = duration_of(take["out_path"]) or 0.0
    chapters_mod.embed_chapters(take["out_path"], marks, total)
    log(f"Embedded {len(marks)} chapter marker(s) into "
       f"{os.path.basename(take['out_path'])}")
    return marks


def export_transcript(source_path, out_dir, log):
    path, _clean_log, _words = publish_mod.export_transcript(source_path,
                                                             out_dir)
    log(f"Transcript saved: {path}")
    return path


def transcribe_file(audio_path, log, model="base", want_srt=True,
                    want_chapters=True, timestamps=False, out_dir=None):
    """Speech in `audio_path` -> a transcript, and optionally subtitles and
    guessed chapter marks. Returns the list of files written, transcript
    first.

    Raises `transcribe_mod.TranscribeUnavailable` when faster-whisper
    isn't installed -- callers should offer to install it rather than
    treating that as a failure.
    """
    folder = out_dir or os.path.dirname(audio_path) or "."
    stem = os.path.splitext(os.path.basename(audio_path))[0]
    segments, detail = transcribe_mod.transcribe_audio(
        audio_path, log, size=model, want_words=False)
    if not segments:
        raise RuntimeError("No speech was recognised in that file.")

    made = []
    md = unique_path(os.path.join(folder, stem + "_transcript.md"))
    transcribe_mod.write_transcript(segments, md, title=stem, detail=detail,
                                    with_timestamps=timestamps)
    made.append(md)
    log(f"Transcript: {md}")

    if want_srt:
        srt = unique_path(os.path.join(folder, stem + ".srt"))
        transcribe_mod.write_srt(segments, srt)
        made.append(srt)
        log(f"Subtitles: {srt}")

    if want_chapters:
        marks = transcribe_mod.detect_chapters(segments)
        text = chapters_mod.format_youtube_chapters(marks)
        path = unique_path(os.path.join(folder, stem + "_chapters.txt"))
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        made.append(path)
        log(f"Chapter marks ({len(marks)} guessed): {path}")
    return made
