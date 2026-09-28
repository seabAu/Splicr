"""Audio8-TTS-Preview-0.6b: an opt-in zero-shot voice-cloning engine.

Added specifically for cloning, not as a narration default. Kokoro stays
the default narrator (faster, smaller, more predictable); Audio8's value
is a second, lighter-weight cloning path alongside Qwen3's.

Why isolated like Qwen3, not folded into it: Audio8 needs custom remote
code (`trust_remote_code=True`) and `transformers>=4.57.0,<5` --
Transformers 5.x is confirmed to produce silent all-zero output on this
model. Pinning that requirement onto the shared environment would risk
breaking whatever Kokoro or Qwen3 need there instead. A dedicated
environment costs disk space, not correctness.

Two things the evaluation flagged as real, not theoretical, and both are
handled here rather than left for the person to discover mid-render:

- **150-character input ceiling** (the model's own context cap forces
  this). `_audio8_chunks()` splits on sentence boundaries under that
  limit, the same way the narration path already splits for length --
  reused rather than reinvented.
- **Unstable end-of-speech ("runaway") generation**, reported by
  independent testers and consistent with a demo-space hang. Each piece
  is screened for a plausible duration against its text (roughly 20
  chars/second is a generous floor for spoken English) and re-generated
  up to twice if it comes back far too short or far too long, before
  giving up and reporting the piece rather than silently shipping
  garbled audio.

Preview status is real: this is offered as an option, never a default,
and `describe()` in components.py says so plainly.
"""

import os

AUDIO8_REPO = "Audio8/Audio8-TTS-Preview-0.6b"
# The model's own context cap forces short inputs; sentences longer than
# this are further split by clause/word the same way `documents.py`
# already handles an oversized sentence elsewhere.
AUDIO8_MAX_CHARS = 150
# A generous floor: real speech is rarely faster than this, so a result
# shorter than text_len / RATE is very likely truncated generation.
AUDIO8_MIN_CHARS_PER_SEC = 20.0
# A generous ceiling: past this the model is very likely running away
# rather than still speaking the given text.
AUDIO8_MAX_SECONDS_PER_CHAR = 0.5
AUDIO8_MAX_RETRIES = 2


def _audio8_chunks(text, limit=AUDIO8_MAX_CHARS):
    """Sentence-bounded pieces under the model's own context cap. Reuses
    the narration path's sentence splitter and oversized-sentence
    fallback rather than duplicating either."""
    from .documents import split_sentences
    pieces = []
    for sentence in split_sentences(text):
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) <= limit:
            pieces.append(sentence)
            continue
        # A single sentence longer than the cap: break on the nearest
        # space before the limit, repeatedly. Losing a little context at
        # each cut is preferable to silently truncating the model's own
        # input, which is what would otherwise happen.
        remaining = sentence
        while len(remaining) > limit:
            cut = remaining.rfind(" ", 0, limit)
            cut = cut if cut > limit // 2 else limit
            pieces.append(remaining[:cut].strip())
            remaining = remaining[cut:].strip()
        if remaining:
            pieces.append(remaining)
    return pieces


def _plausible_duration(text, seconds):
    """Whether a rendered piece's length is consistent with its text, per
    the floor/ceiling above. Returns (ok, reason) so a retry can be
    logged with WHY, not just that one happened."""
    chars = max(1, len(text))
    if seconds <= 0:
        return False, "produced no audio at all"
    min_ok = chars / AUDIO8_MIN_CHARS_PER_SEC
    max_ok = chars * AUDIO8_MAX_SECONDS_PER_CHAR
    if seconds < min_ok * 0.5:
        return False, (f"{seconds:.1f}s is far too short for "
                       f"{chars} characters -- likely cut off")
    if seconds > max_ok:
        return False, (f"{seconds:.1f}s is far too long for {chars} "
                       "characters -- likely a runaway generation")
    return True, ""


def _run_audio8_local(chunks, voice, speed, workdir, log, take=1):
    """Render through Audio8. `voice` is a saved-voice folder path (a
    cloned voice's reference clip + transcript) -- this engine has no
    fixed preset speakers, only cloning, so there is nothing else a
    `voice` string here could mean.
    """
    import numpy as np
    import soundfile as sf

    try:
        from transformers import AutoModel, AutoProcessor
    except ImportError as exc:
        raise RuntimeError(
            "transformers is not installed in Audio8's environment.\n"
            f"(import error: {exc})") from exc
    import torch

    meta_path = os.path.join(voice, "voice.json")
    ref_path = os.path.join(voice, "reference.wav")
    if not (os.path.isfile(meta_path) and os.path.isfile(ref_path)):
        raise RuntimeError(
            "Audio8 needs a cloned voice (a reference clip and its "
            "transcript) -- design one in Voice studio first.")
    import json
    with open(meta_path, encoding="utf-8") as fh:
        meta = json.load(fh)
    reference_text = meta.get("reference_text", "")
    if not reference_text:
        raise RuntimeError(
            "This voice has no reference transcript saved, which Audio8 "
            "needs for cloning -- re-create it from Voice studio.")

    chunk_paths, todo = [], []
    for i, chunk in enumerate(chunks, 1):
        part = os.path.join(workdir, f"{i:04d}.wav")
        chunk_paths.append(part)
        if os.path.exists(part) and os.path.getsize(part) > 1000:
            log(f"  part {i}/{len(chunks)} already rendered, reusing")
        else:
            todo.append((i, chunk, part))

    if todo:
        log(f"  loading {AUDIO8_REPO}")
        log("  (first run downloads the model from Hugging Face)")
        device = "cuda" if torch.cuda.is_available() else "cpu"
        if device == "cpu":
            log("  ! no GPU found -- Audio8 will be slow on CPU")
        processor = AutoProcessor.from_pretrained(AUDIO8_REPO,
                                                  trust_remote_code=True)
        model = AutoModel.from_pretrained(
            AUDIO8_REPO, trust_remote_code=True,
            dtype=torch.bfloat16 if device == "cuda" else torch.float32,
        ).to(device)
        model.eval()

        for i, chunk, part in todo:
            log(f"  part {i}/{len(chunks)} ({len(chunk):,} characters)")
            pieces, rate = [], 44100
            for j, sentence in enumerate(_audio8_chunks(chunk), 1):
                audio, sr, reason = None, rate, ""
                for attempt in range(1, AUDIO8_MAX_RETRIES + 2):
                    inputs = processor(
                        text=sentence, ref_audio=ref_path,
                        ref_text=reference_text, return_tensors="pt",
                    ).to(device)
                    with torch.no_grad():
                        out = model.generate(**inputs)
                    audio, sr = model.decode_audio(out)
                    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
                    seconds = len(audio) / sr if sr else 0
                    ok, reason = _plausible_duration(sentence, seconds)
                    if ok:
                        break
                    log(f"    retry {attempt}/{AUDIO8_MAX_RETRIES + 1} "
                       f"for piece {j}: {reason}")
                else:
                    log(f"    ! kept the last attempt despite: {reason}")
                pieces.append(audio)
                rate = sr
            merged = (np.concatenate(pieces) if pieces
                     else np.zeros(1, dtype=np.float32))
            sf.write(part, merged, rate)

    return {"chunk_paths": chunk_paths, "native_srt": None}
