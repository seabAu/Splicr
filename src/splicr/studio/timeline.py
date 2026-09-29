from __future__ import annotations

import io
import math
import sys
import wave
from array import array
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from splicr.domain import (
    CANONICAL_AUDIO_FORMAT,
    SEGMENT_OPTIONS_VARIABLE,
    ChunkRecord,
    ChunkStatus,
    JobRecord,
    JobStatus,
)
from splicr.storage import LocalJobStorage
from splicr.store import SqliteJobStore


@dataclass(frozen=True, slots=True)
class TimelineSegment:
    index: int
    text: str
    start: float
    end: float
    duration: float
    byte_count: int
    word_count: int
    engine_id: str
    voice_id: str
    speaker: str | None = None


@dataclass(frozen=True, slots=True)
class JobTimeline:
    job_id: str
    status: JobStatus
    engine_id: str
    voice_id: str
    duration: float
    waveform: tuple[float, ...]
    segments: tuple[TimelineSegment, ...]
    audio_url: str | None


def build_job_timeline(
    job_store: SqliteJobStore,
    job_storage: LocalJobStorage,
    job_id: str,
    *,
    waveform_buckets: int = 940,
    audio_path: Path | None = None,
    audio_url: str | None = None,
    offset_seconds: float = 0.0,
) -> JobTimeline:
    if waveform_buckets < 1 or waveform_buckets > 4_000:
        raise ValueError("waveform_buckets must be between 1 and 4000")
    if not math.isfinite(offset_seconds) or offset_seconds < 0:
        raise ValueError("offset_seconds must be a finite non-negative value")
    job = job_store.get_job(job_id)
    chunks = job_store.chunks_for_job(job_id)
    if not chunks:
        raise ValueError("the selected take has no synthesis segments")
    paths = _completed_chunk_paths(chunks)
    segment_options = _segment_options(job, len(chunks))
    cursor = offset_seconds
    segments: list[TimelineSegment] = []
    for chunk, path, settings in zip(chunks, paths, segment_options, strict=True):
        duration = _pcm_duration(path)
        voice = str(settings.get("voice") or job.voice)
        speaker_value = settings.get("speaker")
        speaker = str(speaker_value) if speaker_value else None
        segments.append(
            TimelineSegment(
                index=chunk.index,
                text=chunk.text,
                start=cursor,
                end=cursor + duration,
                duration=duration,
                byte_count=chunk.byte_count,
                word_count=chunk.word_count,
                engine_id=job.provider,
                voice_id=voice,
                speaker=speaker,
            )
        )
        cursor += duration
    output = (
        audio_path
        if audio_path is not None
        else Path(job.output_path)
        if job.output_path
        else job_storage.output_path(job_id)
    )
    if audio_path is not None:
        duration = _wav_duration(output)
        waveform = _wav_waveform_envelope(output, waveform_buckets)
        resolved_audio_url = audio_url
    else:
        duration = cursor
        waveform = _waveform_envelope(paths, waveform_buckets)
        resolved_audio_url = (
            audio_url
            if audio_url is not None
            else f"/v1/speech/jobs/{job.id}/audio"
            if output.is_file()
            else None
        )
    return JobTimeline(
        job_id=job.id,
        status=job.status,
        engine_id=job.provider,
        voice_id=job.voice,
        duration=duration,
        waveform=waveform,
        segments=tuple(segments),
        audio_url=resolved_audio_url,
    )


def wav_span_bytes(path: Path, start: float, end: float) -> bytes:
    if not math.isfinite(start) or not math.isfinite(end):
        raise ValueError("timeline selection must use finite times")
    if start < 0 or end <= start:
        raise ValueError("timeline selection must have a positive duration")
    with wave.open(str(path), "rb") as source:
        if (
            source.getnchannels() != CANONICAL_AUDIO_FORMAT.channels
            or source.getsampwidth() != CANONICAL_AUDIO_FORMAT.sample_width
            or source.getframerate() != CANONICAL_AUDIO_FORMAT.sample_rate
        ):
            raise ValueError("timeline audio is not canonical mono PCM16 at 24 kHz")
        frames = source.getnframes()
        first = min(frames, int(start * source.getframerate()))
        last = min(frames, int(math.ceil(end * source.getframerate())))
        if last <= first:
            raise ValueError("timeline selection falls outside the available audio")
        source.setpos(first)
        selected = source.readframes(last - first)

    destination = io.BytesIO()
    with wave.open(destination, "wb") as output:
        output.setnchannels(CANONICAL_AUDIO_FORMAT.channels)
        output.setsampwidth(CANONICAL_AUDIO_FORMAT.sample_width)
        output.setframerate(CANONICAL_AUDIO_FORMAT.sample_rate)
        output.writeframes(selected)
    return destination.getvalue()


def _wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as source:
        _validate_canonical_wav(source)
        return source.getnframes() / source.getframerate()


def _validate_canonical_wav(source: wave.Wave_read) -> None:
    if (
        source.getnchannels() != CANONICAL_AUDIO_FORMAT.channels
        or source.getsampwidth() != CANONICAL_AUDIO_FORMAT.sample_width
        or source.getframerate() != CANONICAL_AUDIO_FORMAT.sample_rate
    ):
        raise ValueError("timeline audio is not canonical mono PCM16 at 24 kHz")


def _wav_waveform_envelope(path: Path, buckets: int) -> tuple[float, ...]:
    with wave.open(str(path), "rb") as source:
        _validate_canonical_wav(source)
        total_frames = source.getnframes()
        if not total_frames:
            return ()
        frames_per_bucket = max(1, math.ceil(total_frames / buckets))
        bucket_count = math.ceil(total_frames / frames_per_bucket)
        peaks: list[float] = []
        for bucket in range(bucket_count):
            bucket_start = bucket * frames_per_bucket
            bucket_end = min(total_frames, bucket_start + frames_per_bucket)
            sample_windows = [(bucket_start, bucket_end - bucket_start)]
            if bucket_end - bucket_start > 1_024:
                sample_windows = []
                for window in range(12):
                    midpoint = bucket_start + int(
                        (window + 0.5) * (bucket_end - bucket_start) / 12
                    )
                    start = max(bucket_start, midpoint - 32)
                    start = min(start, bucket_end - 64)
                    sample_windows.append((start, 64))
            peak = 0
            for start, count in sample_windows:
                source.setpos(start)
                samples = array("h")
                samples.frombytes(source.readframes(count))
                if sys.byteorder != "little":
                    samples.byteswap()
                if samples:
                    peak = max(peak, max(abs(sample) for sample in samples))
            peaks.append(min(1.0, peak / 32_768))
    return tuple(peaks)


def _completed_chunk_paths(chunks: Sequence[ChunkRecord]) -> tuple[Path, ...]:
    paths: list[Path] = []
    for chunk in chunks:
        if chunk.status is not ChunkStatus.COMPLETED or not chunk.pcm_path:
            raise ValueError("the selected take does not have complete audio checkpoints")
        path = Path(chunk.pcm_path)
        if not path.is_file():
            raise ValueError(f"audio checkpoint {chunk.index + 1} is missing")
        paths.append(path)
    return tuple(paths)


def _segment_options(job: JobRecord, count: int) -> tuple[Mapping[str, object], ...]:
    raw = job.variables.get(SEGMENT_OPTIONS_VARIABLE)
    if raw is None:
        return tuple({} for _ in range(count))
    if not isinstance(raw, list) or len(raw) != count:
        raise ValueError("persisted segment options do not match the take")
    if any(not isinstance(item, Mapping) for item in raw):
        raise ValueError("persisted segment options are invalid")
    return tuple(cast(Mapping[str, object], item) for item in raw)


def _pcm_duration(path: Path) -> float:
    size = path.stat().st_size
    frame_width = CANONICAL_AUDIO_FORMAT.frame_width
    if size <= 0 or size % frame_width:
        raise ValueError(f"audio checkpoint is not aligned PCM: {path.name}")
    return size / frame_width / CANONICAL_AUDIO_FORMAT.sample_rate


def _waveform_envelope(paths: Sequence[Path], buckets: int) -> tuple[float, ...]:
    frame_width = CANONICAL_AUDIO_FORMAT.frame_width
    frame_counts = [path.stat().st_size // frame_width for path in paths]
    total_frames = sum(frame_counts)
    if not total_frames:
        return ()
    frames_per_bucket = max(1, math.ceil(total_frames / buckets))
    bucket_count = math.ceil(total_frames / frames_per_bucket)
    peaks = [0] * bucket_count
    starts: list[int] = []
    cursor = 0
    for count in frame_counts:
        starts.append(cursor)
        cursor += count
    requests: list[list[tuple[int, int, int]]] = [[] for _ in paths]

    def queue_window(bucket: int, start: int, count: int) -> None:
        remaining = count
        position = start
        while remaining > 0 and position < total_frames:
            path_index = min(len(paths) - 1, bisect_right(starts, position) - 1)
            local_start = position - starts[path_index]
            available = frame_counts[path_index] - local_start
            take = min(remaining, available)
            if take <= 0:
                break
            requests[path_index].append((bucket, local_start, take))
            position += take
            remaining -= take

    for bucket in range(bucket_count):
        bucket_start = bucket * frames_per_bucket
        bucket_end = min(total_frames, bucket_start + frames_per_bucket)
        bucket_frames = bucket_end - bucket_start
        if bucket_frames <= 1_024:
            queue_window(bucket, bucket_start, bucket_frames)
            continue
        window_count = 12
        window_frames = 64
        for window in range(window_count):
            midpoint = bucket_start + int((window + 0.5) * bucket_frames / window_count)
            window_start = max(bucket_start, midpoint - window_frames // 2)
            window_start = min(window_start, bucket_end - window_frames)
            queue_window(bucket, window_start, window_frames)

    for path, path_requests in zip(paths, requests, strict=True):
        with path.open("rb") as handle:
            for bucket, local_start, count in sorted(path_requests, key=lambda item: item[1]):
                handle.seek(local_start * frame_width)
                payload = handle.read(count * frame_width)
                samples = array("h")
                samples.frombytes(payload)
                if sys.byteorder != "little":
                    samples.byteswap()
                if samples:
                    peaks[bucket] = max(peaks[bucket], max(abs(sample) for sample in samples))
    return tuple(min(1.0, peak / 32_768) for peak in peaks)
