"""Going the other way: an existing audio file back into text.

Everything else here turns a document into narration. This turns
narration -- or any speech, from any source, not necessarily made by this
app -- back into a readable transcript, subtitles, and chapter marks.

Speech recognition is genuinely needed for this (unlike the chapter marks
we produce for our OWN renders, where the timings are known exactly
because we generated the audio). `faster-whisper` does the recognition;
it is an optional dependency, asked for plainly if missing rather than
failing with an ImportError.

Signatures here were checked against faster-whisper 1.2.1's actual source
rather than assumed: `WhisperModel(model_size_or_path, device=,
compute_type=, download_root=)`, `transcribe(audio, language=,
word_timestamps=, vad_filter=)` returning `(segments, info)` where each
segment carries `.start/.end/.text/.words` and each word
`.start/.end/.word`.
"""

import os
import re

# Whisper's own size ladder. tiny/base are usable on any CPU; small is the
# usual "good enough" point; medium and large want real hardware or a lot
# of patience. Sizes are the download, not the memory used.
MODEL_SIZES = [
    ("tiny", "tiny -- fastest, roughly 75 MB, noticeably rougher"),
    ("base", "base -- fast, roughly 150 MB"),
    ("small", "small -- good balance, roughly 500 MB"),
    ("medium", "medium -- better, roughly 1.5 GB, slow on CPU"),
    ("large-v3", "large-v3 -- best, roughly 3 GB, needs a GPU to be "
                 "practical"),
]
DEFAULT_MODEL = "base"

# A pause at least this long between spoken segments is treated as a
# section break when chapters are requested. Speech recognition gives no
# heading information, so a long silence is the only structural signal in
# the audio itself -- this is a heuristic and is described as one wherever
# it reaches the user.
CHAPTER_SILENCE = 2.0


class TranscribeUnavailable(RuntimeError):
    """faster-whisper isn't installed, with the instruction to fix it."""


def load_model(size, log, download_root=None):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise TranscribeUnavailable(
            "Transcribing audio needs the 'faster-whisper' package, which "
            "isn't installed here.\n\nIn a terminal:\n\n"
            "    pip install faster-whisper\n\n"
            "Then try again -- nothing else needs to change.")
    log(f"Loading the {size} speech model "
       "(the first run downloads it)...")
    # device="auto" picks CUDA when it is genuinely usable and falls back
    # to CPU otherwise; compute_type="default" lets the library choose a
    # precision that actually works on that device rather than forcing one
    # that may not.
    return WhisperModel(size, device="auto", compute_type="default",
                        download_root=download_root)


def transcribe_audio(path, log, size=DEFAULT_MODEL, language=None,
                     want_words=False, model=None):
    """Recognise speech in `path`. Returns (segments, info_dict).

    Each segment is a plain dict -- {"start", "end", "text", "words"} --
    rather than the library's own objects, so everything downstream (and
    the tests) can work without faster-whisper being importable at all.
    """
    model = model or load_model(size, log)
    log("Listening to the audio (this takes a while -- roughly real time "
       "on a CPU for the smaller models)...")
    segments, info = model.transcribe(
        path, language=language, word_timestamps=want_words,
        vad_filter=True)

    out = []
    # `segments` is a generator: recognition happens as it is consumed, so
    # progress can only be reported from inside this loop.
    for seg in segments:
        words = [{"start": w.start, "end": w.end, "word": w.word}
                for w in (seg.words or [])] if want_words else []
        out.append({"start": float(seg.start), "end": float(seg.end),
                   "text": (seg.text or "").strip(), "words": words})
        if len(out) % 25 == 0:
            log(f"  {len(out)} segments, {seg.end / 60:.1f} minutes in...")

    detail = {
        "language": getattr(info, "language", None),
        "language_probability": getattr(info, "language_probability", None),
        "duration": getattr(info, "duration", None),
    }
    log(f"  done: {len(out)} segments, "
       f"{(detail['duration'] or 0) / 60:.1f} minutes, "
       f"language {detail['language']}")
    return out, detail


# --- turning segments into the three outputs -------------------------------


def _srt_time(seconds):
    ms = round(max(0.0, seconds) * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(segments, out_path):
    blocks = []
    for i, seg in enumerate([s for s in segments if s["text"]], 1):
        blocks.append(f"{i}\n{_srt_time(seg['start'])} --> "
                     f"{_srt_time(seg['end'])}\n{seg['text']}")
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("\n\n".join(blocks) + "\n")
    return out_path


def paragraphs(segments, gap=CHAPTER_SILENCE):
    """Group segments into paragraphs, breaking on a noticeable pause.
    Whisper returns one segment per utterance, which reads as choppy
    fragments if written out one per line."""
    groups, current, prev_end = [], [], None
    for seg in segments:
        if not seg["text"]:
            continue
        if prev_end is not None and seg["start"] - prev_end >= gap and current:
            groups.append(" ".join(current))
            current = []
        current.append(seg["text"])
        prev_end = seg["end"]
    if current:
        groups.append(" ".join(current))
    return groups


def write_transcript(segments, out_path, title=None, detail=None,
                     with_timestamps=False, gap=CHAPTER_SILENCE):
    lines = []
    if title:
        lines += [f"# {title}", ""]
    if detail:
        mins = (detail.get("duration") or 0) / 60
        lines += [f"*Transcribed from audio -- {mins:.1f} minutes, "
                  f"detected language: {detail.get('language')}. "
                  "Machine transcription, so expect some errors.*", ""]
    if with_timestamps:
        for seg in segments:
            if seg["text"]:
                lines.append(f"**[{_clock(seg['start'])}]** {seg['text']}")
                lines.append("")
    else:
        for para in paragraphs(segments, gap):
            lines += [para, ""]
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines).strip() + "\n")
    return out_path


def _clock(seconds):
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def detect_chapters(segments, gap=CHAPTER_SILENCE, max_title_words=9):
    """Chapter marks guessed from long pauses, titled with the opening
    words of whatever follows each pause.

    Worth being clear-eyed about: recognised speech carries no heading
    structure, so unlike the chapter marks produced for our own renders
    (which come from the source document's real headings), these are a
    guess. They are a starting point to edit, not a finished chapter list.
    """
    spoken = [s for s in segments if s["text"]]
    if not spoken:
        return []
    marks, prev_end = [], None
    for seg in spoken:
        is_break = prev_end is None or (seg["start"] - prev_end) >= gap
        if is_break:
            words = re.findall(r"[\w''-]+", seg["text"])[:max_title_words]
            title = " ".join(words) or "Section"
            marks.append({"title": title[:1].upper() + title[1:],
                         "seconds": 0.0 if prev_end is None
                                    else float(seg["start"])})
        prev_end = seg["end"]
    return marks
