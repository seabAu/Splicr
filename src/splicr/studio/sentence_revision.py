from __future__ import annotations

import math
import re
import sys
from array import array
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, cast

from splicr.domain import CANONICAL_AUDIO_FORMAT, AudioChunk, JsonValue


SENTENCE_REVISION_VARIABLE = "__splicr_sentence_revision__"


@dataclass(frozen=True, slots=True)
class SentenceSpan:
    index: int
    text: str
    text_start: int
    text_end: int
    start: float
    end: float
    duration: float
    timing_source: str
    confidence: str
    reliable: bool
    metadata_key: str


def sentence_spans(
    text: str,
    metadata: Mapping[str, JsonValue],
    chunk_duration: float,
) -> tuple[SentenceSpan, ...]:
    """Return only sentence timings safe enough to drive non-destructive edits."""

    sources = (
        ("timings", "engine", "exact"),
        ("transcription_timings", "transcription", "aligned"),
    )
    for metadata_key, source, confidence in sources:
        raw = metadata.get(metadata_key)
        if not isinstance(raw, list):
            continue
        candidates = _timing_candidates(raw, chunk_duration, words=False)
        aligned = _align_candidates(text, candidates, source, confidence, metadata_key)
        word_candidates = _timing_candidates(raw, chunk_duration, words=True)
        word_spans = _align_candidates(
            text,
            word_candidates,
            source,
            confidence,
            metadata_key,
        )
        grouped = _group_word_spans(
            text,
            word_spans,
            source=source,
            confidence=confidence,
            metadata_key=metadata_key,
        )
        combined = _merge_sentence_sources(aligned, grouped)
        if combined:
            return combined
    return ()


def splice_sentence_audio(
    *,
    source_pcm: bytes,
    replacement: AudioChunk,
    span: SentenceSpan,
    replacement_text: str,
    crossfade_ms: float = 30.0,
) -> AudioChunk:
    """Replace one timed sentence while preserving all PCM outside its old span."""

    if replacement.format != CANONICAL_AUDIO_FORMAT:
        raise ValueError("sentence replacement audio is not in the canonical PCM format")
    source_samples = _samples(source_pcm)
    replacement_samples = _samples(replacement.pcm)
    if not replacement_samples:
        raise ValueError("sentence replacement audio is empty")

    rate = CANONICAL_AUDIO_FORMAT.sample_rate
    start_frame = round(span.start * rate)
    end_frame = round(span.end * rate)
    if start_frame < 0 or end_frame <= start_frame or end_frame > len(source_samples):
        raise ValueError("sentence timing falls outside the source checkpoint")

    replacement_samples = _trim_silence(replacement_samples)
    source_sentence = source_samples[start_frame:end_frame]
    replacement_samples, gain_db = _level_match(replacement_samples, source_sentence)
    fade_frames = max(0, round(crossfade_ms * rate / 1000))
    fade_frames = min(fade_frames, len(source_sentence) // 2, len(replacement_samples) // 2)
    if fade_frames:
        _crossfade_inside_replacement(
            replacement_samples,
            source_sentence,
            fade_frames,
        )

    revised_samples = array("h")
    revised_samples.extend(source_samples[:start_frame])
    revised_samples.extend(replacement_samples)
    revised_samples.extend(source_samples[end_frame:])
    replacement_duration = len(replacement_samples) / rate
    delta = replacement_duration - span.duration
    metadata = _revised_metadata(
        source_metadata={},
        replacement_metadata=replacement.metadata,
        span=span,
        replacement_text=replacement_text,
        replacement_duration=replacement_duration,
        duration_delta=delta,
        crossfade_frames=fade_frames,
        gain_db=gain_db,
    )
    return AudioChunk(pcm=_sample_bytes(revised_samples), metadata=metadata)


def merge_revision_metadata(
    *,
    source_metadata: Mapping[str, JsonValue],
    revised_audio: AudioChunk,
    span: SentenceSpan,
    replacement_text: str,
    source_job_id: str,
    chunk_index: int,
) -> AudioChunk:
    """Attach shifted timings and immutable-source provenance to spliced audio."""

    revision = revised_audio.metadata.get("sentence_revision")
    if not isinstance(revision, Mapping):
        raise ValueError("spliced sentence audio is missing revision metadata")
    revision_payload = cast(Mapping[str, JsonValue], revision)
    replacement_duration = _number(revision_payload.get("replacement_duration"))
    duration_delta = _number(revision_payload.get("duration_delta"))
    crossfade_frames = revision_payload.get("crossfade_frames")
    gain_db = _number(revision_payload.get("gain_db"))
    recovered = revision_payload.get("recovered_from_checkpoint") is True
    if replacement_duration is None or duration_delta is None:
        raise ValueError("spliced sentence revision metadata is invalid")
    if gain_db is None and not recovered:
        raise ValueError("spliced sentence gain metadata is invalid")
    if isinstance(crossfade_frames, bool) or not isinstance(crossfade_frames, int):
        raise ValueError("spliced sentence crossfade metadata is invalid")
    metadata = _revised_metadata(
        source_metadata=source_metadata,
        replacement_metadata={},
        span=span,
        replacement_text=replacement_text,
        replacement_duration=replacement_duration,
        duration_delta=duration_delta,
        crossfade_frames=crossfade_frames,
        gain_db=gain_db,
        recovered_from_checkpoint=recovered,
    )
    raw_provenance = metadata["sentence_revision"]
    if not isinstance(raw_provenance, dict):
        raise ValueError("generated sentence revision provenance is invalid")
    provenance = cast(dict[str, JsonValue], raw_provenance)
    provenance.update(
        {
            "source_job_id": source_job_id,
            "chunk_index": chunk_index,
            "sentence_index": span.index,
            "provider_timing_available": (
                revision_payload.get("provider_timing_available") is True
            ),
        }
    )
    metadata["sentence_revision"] = provenance
    return AudioChunk(pcm=revised_audio.pcm, metadata=metadata)


def pcm_duration_seconds(pcm: bytes) -> float:
    frame_width = CANONICAL_AUDIO_FORMAT.sample_width * CANONICAL_AUDIO_FORMAT.channels
    if len(pcm) % frame_width:
        raise ValueError("PCM checkpoint is not frame-aligned")
    return len(pcm) / frame_width / CANONICAL_AUDIO_FORMAT.sample_rate


def _timing_candidates(
    rows: Sequence[JsonValue],
    chunk_duration: float,
    *,
    words: bool,
) -> list[tuple[float, float, str]]:
    candidates: list[tuple[float, float, str]] = []
    for item in rows:
        if not isinstance(item, Mapping):
            continue
        boundary = str(item.get("type") or "").casefold()
        if words != ("word" in boundary):
            continue
        start = _number(item.get("start_seconds"))
        duration = _number(item.get("duration_seconds"))
        value = str(item.get("text") or "").strip()
        if (
            start is None
            or duration is None
            or not value
            or start < 0
            or duration <= 0
            or start >= chunk_duration
        ):
            continue
        candidates.append((start, min(chunk_duration, start + duration), value))
    candidates.sort(key=lambda row: (row[0], row[1]))
    return candidates


def _group_word_spans(
    text: str,
    words: Sequence[SentenceSpan],
    *,
    source: str,
    confidence: str,
    metadata_key: str,
) -> tuple[SentenceSpan, ...]:
    if not words:
        return ()
    grouped: list[SentenceSpan] = []
    sentence_pattern = re.compile(r"\s*(.+?(?:[.!?](?=\s|$)|$))", re.DOTALL)
    for match in sentence_pattern.finditer(text):
        sentence_text = match.group(1)
        if not sentence_text.strip():
            continue
        text_start = match.start(1)
        text_end = match.end(1)
        included = [
            word
            for word in words
            if word.text_start >= text_start and word.text_end <= text_end
        ]
        if not included:
            continue
        grouped.append(
            SentenceSpan(
                index=len(grouped),
                text=sentence_text,
                text_start=text_start,
                text_end=text_end,
                start=included[0].start,
                end=included[-1].end,
                duration=included[-1].end - included[0].start,
                timing_source=source,
                confidence=confidence,
                reliable=True,
                metadata_key=metadata_key,
            )
        )
    return tuple(grouped)


def _merge_sentence_sources(
    explicit: Sequence[SentenceSpan],
    grouped_words: Sequence[SentenceSpan],
) -> tuple[SentenceSpan, ...]:
    candidates = [(span, 0) for span in explicit] + [
        (span, 1) for span in grouped_words
    ]
    candidates.sort(key=lambda item: (item[0].text_start, item[1], item[0].text_end))
    merged: list[SentenceSpan] = []
    for candidate, _priority in candidates:
        if any(
            candidate.text_start < existing.text_end
            and candidate.text_end > existing.text_start
            for existing in merged
        ):
            continue
        merged.append(candidate)
    merged.sort(key=lambda span: span.text_start)
    return tuple(replace(span, index=index) for index, span in enumerate(merged))


def _align_candidates(
    text: str,
    candidates: Sequence[tuple[float, float, str]],
    source: str,
    confidence: str,
    metadata_key: str,
) -> tuple[SentenceSpan, ...]:
    spans: list[SentenceSpan] = []
    text_cursor = 0
    time_cursor = 0.0
    for start, end, candidate_text in candidates:
        if start + 1e-6 < time_cursor:
            return ()
        location = _find_text_span(text, candidate_text, text_cursor)
        if location is None:
            return ()
        text_start, text_end = location
        spans.append(
            SentenceSpan(
                index=len(spans),
                text=text[text_start:text_end],
                text_start=text_start,
                text_end=text_end,
                start=start,
                end=end,
                duration=end - start,
                timing_source=source,
                confidence=confidence,
                reliable=True,
                metadata_key=metadata_key,
            )
        )
        text_cursor = text_end
        time_cursor = end
    return tuple(spans)


def _find_text_span(text: str, candidate: str, cursor: int) -> tuple[int, int] | None:
    exact = text.find(candidate, cursor)
    if exact >= 0:
        return exact, exact + len(candidate)
    folded = text.casefold().find(candidate.casefold(), cursor)
    if folded >= 0:
        return folded, folded + len(candidate)
    pieces = re.split(r"(\s+)", candidate.strip())
    pattern = "".join(r"\s+" if piece.isspace() else re.escape(piece) for piece in pieces)
    match = re.search(pattern, text[cursor:], flags=re.IGNORECASE)
    if match is None:
        return None
    return cursor + match.start(), cursor + match.end()


def _samples(pcm: bytes) -> array[int]:
    if len(pcm) % 2:
        raise ValueError("PCM checkpoint contains a partial sample")
    samples = array("h")
    samples.frombytes(pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    return samples


def _sample_bytes(samples: array[int]) -> bytes:
    result = array("h", samples)
    if sys.byteorder != "little":
        result.byteswap()
    return result.tobytes()


def _trim_silence(samples: array[int], threshold: int = 96, padding_frames: int = 240) -> array[int]:
    audible = [index for index, sample in enumerate(samples) if abs(sample) > threshold]
    if not audible:
        return samples
    start = max(0, audible[0] - padding_frames)
    end = min(len(samples), audible[-1] + padding_frames + 1)
    return array("h", samples[start:end])


def _rms(samples: Sequence[int]) -> float:
    if not samples:
        return 0.0
    return math.sqrt(sum(float(sample) ** 2 for sample in samples) / len(samples))


def _level_match(replacement: array[int], reference: array[int]) -> tuple[array[int], float]:
    replacement_rms = _rms(replacement)
    reference_rms = _rms(reference)
    if replacement_rms < 1 or reference_rms < 1:
        return replacement, 0.0
    raw_gain = reference_rms / replacement_rms
    gain = min(10 ** (4 / 20), max(10 ** (-4 / 20), raw_gain))
    gain_db = 20 * math.log10(gain)
    adjusted = array("h", (_clamp_sample(round(sample * gain)) for sample in replacement))
    return adjusted, gain_db


def _crossfade_inside_replacement(
    replacement: array[int],
    original: array[int],
    frames: int,
) -> None:
    for index in range(frames):
        replacement_weight = (index + 1) / (frames + 1)
        replacement[index] = _clamp_sample(
            round(original[index] * (1 - replacement_weight) + replacement[index] * replacement_weight)
        )
    original_offset = len(original) - frames
    replacement_offset = len(replacement) - frames
    for index in range(frames):
        original_weight = (index + 1) / (frames + 1)
        target = replacement_offset + index
        replacement[target] = _clamp_sample(
            round(
                replacement[target] * (1 - original_weight)
                + original[original_offset + index] * original_weight
            )
        )


def _clamp_sample(value: int) -> int:
    return max(-32_768, min(32_767, value))


def _revised_metadata(
    *,
    source_metadata: Mapping[str, JsonValue],
    replacement_metadata: Mapping[str, JsonValue],
    span: SentenceSpan,
    replacement_text: str,
    replacement_duration: float,
    duration_delta: float,
    crossfade_frames: int,
    gain_db: float | None,
    recovered_from_checkpoint: bool = False,
) -> dict[str, JsonValue]:
    metadata = dict(source_metadata)
    raw = source_metadata.get(span.metadata_key)
    shifted: list[JsonValue] = []
    inserted = False
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, Mapping):
                continue
            start = _number(item.get("start_seconds"))
            duration = _number(item.get("duration_seconds"))
            if start is None or duration is None:
                continue
            end = start + duration
            if end <= span.start + 1e-6:
                shifted.append(dict(item))
            elif start >= span.end - 1e-6:
                if not inserted:
                    shifted.append(_replacement_timing(span, replacement_text, replacement_duration))
                    inserted = True
                moved = dict(item)
                moved["start_seconds"] = start + duration_delta
                shifted.append(moved)
        if not inserted:
            shifted.append(_replacement_timing(span, replacement_text, replacement_duration))
        metadata[span.metadata_key] = shifted
    else:
        metadata[span.metadata_key] = [
            _replacement_timing(span, replacement_text, replacement_duration)
        ]
    metadata["sentence_revision"] = {
        "timing_source": span.timing_source,
        "timing_confidence": span.confidence,
        "original_start": span.start,
        "original_end": span.end,
        "original_duration": span.duration,
        "replacement_duration": replacement_duration,
        "duration_delta": duration_delta,
        "crossfade_frames": crossfade_frames,
        "gain_db": gain_db,
        "provider_timing_available": bool(replacement_metadata.get("timings")),
        "recovered_from_checkpoint": recovered_from_checkpoint,
    }
    return metadata


def _replacement_timing(
    span: SentenceSpan,
    text: str,
    duration: float,
) -> dict[str, JsonValue]:
    return {
        "type": "SentenceBoundary",
        "start_seconds": span.start,
        "duration_seconds": duration,
        "text": text,
        "source": "sentence_revision",
    }


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None
