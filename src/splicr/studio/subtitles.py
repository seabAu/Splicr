from __future__ import annotations

import hashlib
import math
import os
import sqlite3
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from ..artifacts import sanitize_export_stem
from ..domain import (
    CANONICAL_AUDIO_FORMAT,
    SEGMENT_OPTIONS_VARIABLE,
    ChunkRecord,
    ChunkStatus,
    JsonValue,
)
from ..storage import LocalJobStorage
from ..store import SqliteJobStore

from .domain import Artifact, ArtifactKind
from .migration import import_splicr_job
from .store import SqliteStudioStore


class SubtitleTimingSource(StrEnum):
    ENGINE = "engine"
    CHECKPOINT = "checkpoint"
    TRANSCRIPTION = "transcription"


class SubtitleTimingConfidence(StrEnum):
    EXACT = "exact"
    ESTIMATED = "estimated"


class SubtitleFormat(StrEnum):
    SRT = "srt"
    WEBVTT = "vtt"


@dataclass(frozen=True, slots=True)
class SubtitleCue:
    index: int
    source_text: str
    start: float
    end: float
    speaker: str | None
    confidence: SubtitleTimingConfidence
    source: SubtitleTimingSource

    def __post_init__(self) -> None:
        if self.index < 0:
            raise ValueError("subtitle cue index must be non-negative")
        if not self.source_text.strip():
            raise ValueError("subtitle cue text must not be blank")
        if not math.isfinite(self.start) or not math.isfinite(self.end):
            raise ValueError("subtitle cue times must be finite")
        if self.start < 0 or self.end <= self.start:
            raise ValueError("subtitle cue end must be after its non-negative start")


@dataclass(frozen=True, slots=True)
class SubtitleTimeline:
    job_id: str
    status: str
    partial: bool
    duration: float
    completed_chunks: int
    total_chunks: int
    cues: tuple[SubtitleCue, ...]

    @property
    def source_counts(self) -> Mapping[str, int]:
        return dict(Counter(cue.source.value for cue in self.cues))

    @property
    def confidence_counts(self) -> Mapping[str, int]:
        return dict(Counter(cue.confidence.value for cue in self.cues))


@dataclass(frozen=True, slots=True)
class SubtitleExport:
    artifact: Artifact
    timeline: SubtitleTimeline


class SubtitleService:
    def __init__(
        self,
        *,
        job_store: SqliteJobStore,
        job_storage: LocalJobStorage,
        studio_store: SqliteStudioStore,
        output_root: Path,
    ) -> None:
        self.job_store = job_store
        self.job_storage = job_storage
        self.studio_store = studio_store
        self.output_root = Path(output_root)

    def timeline(
        self, job_id: str, *, offset_seconds: float = 0.0
    ) -> SubtitleTimeline:
        if not math.isfinite(offset_seconds) or offset_seconds < 0:
            raise ValueError("subtitle offset must be a finite non-negative number")
        job = self.job_store.get_job(job_id)
        chunks = self.job_store.chunks_for_job(job_id)
        if not chunks:
            raise ValueError("the selected take has no synthesis segments")
        speakers = _segment_speakers(job.variables, len(chunks))
        cursor = offset_seconds
        cues: list[SubtitleCue] = []
        completed_chunks = 0
        for chunk, speaker in zip(chunks, speakers, strict=True):
            path = _completed_checkpoint(chunk)
            if path is None:
                break
            duration = _pcm_duration(path)
            chunk_cues = _engine_cues(
                chunk,
                speaker=speaker,
                chunk_start=cursor,
                chunk_duration=duration,
                next_index=len(cues),
            )
            if not chunk_cues:
                chunk_cues = (
                    SubtitleCue(
                        index=len(cues),
                        source_text=chunk.text,
                        start=cursor,
                        end=cursor + duration,
                        speaker=speaker,
                        confidence=SubtitleTimingConfidence.ESTIMATED,
                        source=SubtitleTimingSource.CHECKPOINT,
                    ),
                )
            cues.extend(chunk_cues)
            cursor += duration
            completed_chunks += 1
        if not cues:
            raise ValueError("the selected take does not have a playable audio checkpoint")
        return SubtitleTimeline(
            job_id=job.id,
            status=job.status.value,
            partial=completed_chunks < len(chunks),
            duration=cursor,
            completed_chunks=completed_chunks,
            total_chunks=len(chunks),
            cues=tuple(cues),
        )

    def export(
        self,
        job_id: str,
        output_format: SubtitleFormat,
        *,
        offset_seconds: float = 0.0,
        source_audio_artifact_id: str | None = None,
    ) -> SubtitleExport:
        timeline = self.timeline(job_id, offset_seconds=offset_seconds)
        job = self.job_store.get_job(job_id)
        imported = import_splicr_job(
            job_id=job_id,
            job_store=self.job_store,
            job_storage=self.job_storage,
            studio_store=self.studio_store,
        )
        if imported.take_id is None or imported.render_plan_id is None:
            raise ValueError("the selected take has no render plan")
        payload = serialize_subtitles(timeline.cues, output_format).encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()
        provenance_digest = hashlib.sha256(
            f"{source_audio_artifact_id or 'source'}:{offset_seconds:.9f}".encode()
        ).hexdigest()[:8]
        provenance_suffix = (
            ""
            if source_audio_artifact_id is None and offset_seconds == 0
            else f"-{provenance_digest}"
        )
        artifact_id = (
            f"subtitle-{output_format.value}-{_safe_id(imported.take_id)}-"
            f"{digest[:12]}{provenance_suffix}"
        )
        try:
            existing = self.studio_store.get_artifact(artifact_id)
        except KeyError:
            existing = None
        if existing is not None:
            if Path(existing.path).is_file():
                return SubtitleExport(existing, timeline)
            raise FileNotFoundError(
                f"existing subtitle artifact is missing: {Path(existing.path).name}"
            )
        stem = sanitize_export_stem(job.export_stem)
        path = (
            self.output_root
            / imported.take_id
            / f"{stem}-{digest[:12]}.{output_format.value}"
        )
        _atomic_write(path, payload)
        metadata: dict[str, JsonValue] = {
            "schema_version": 1,
            "source_job_id": job.id,
            "source_job_status": job.status.value,
            "source_job_updated_at": job.updated_at,
            "source_project_id": imported.project_id,
            "source_render_plan_id": imported.render_plan_id,
            "source_take_id": imported.take_id,
            "format": output_format.value,
            "partial": timeline.partial,
            "completed_chunks": timeline.completed_chunks,
            "total_chunks": timeline.total_chunks,
            "cue_count": len(timeline.cues),
            "timing_sources": dict(timeline.source_counts),
            "timing_confidence": dict(timeline.confidence_counts),
            "content_sha256": digest,
            "offset_seconds": offset_seconds,
            "source_audio_artifact_id": source_audio_artifact_id,
        }
        artifact = Artifact(
            id=artifact_id,
            project_id=imported.project_id,
            take_id=imported.take_id,
            kind=ArtifactKind.SUBTITLES,
            path=str(path.resolve()),
            media_type=(
                "application/x-subrip"
                if output_format is SubtitleFormat.SRT
                else "text/vtt"
            ),
            size_bytes=len(payload),
            sha256=digest,
            metadata=metadata,
        )
        try:
            stored = self.studio_store.add_artifact(artifact)
        except sqlite3.IntegrityError:
            stored = self.studio_store.get_artifact(artifact_id)
        return SubtitleExport(stored, timeline)

    def job_id_for_take(self, take_id: str) -> str:
        take = self.studio_store.get_take(take_id)
        plan = self.studio_store.get_render_plan(take.render_plan_id)
        job_id = plan.metadata.get("legacy_job_id")
        if not isinstance(job_id, str) or not job_id:
            raise ValueError("the selected take is not linked to a synthesis job")
        return job_id

    def export_take(
        self,
        take_id: str,
        output_format: SubtitleFormat,
        *,
        offset_seconds: float = 0.0,
        source_audio_artifact_id: str | None = None,
    ) -> SubtitleExport:
        return self.export(
            self.job_id_for_take(take_id),
            output_format,
            offset_seconds=offset_seconds,
            source_audio_artifact_id=source_audio_artifact_id,
        )

    def artifact_path(self, artifact_id: str) -> Path:
        artifact = self.studio_store.get_artifact(artifact_id)
        if artifact.kind is not ArtifactKind.SUBTITLES:
            raise ValueError("artifact is not a subtitle export")
        path = Path(artifact.path)
        if not path.is_file():
            raise FileNotFoundError(f"subtitle artifact is missing: {path.name}")
        return path


def serialize_subtitles(
    cues: Sequence[SubtitleCue], output_format: SubtitleFormat
) -> str:
    if not cues:
        raise ValueError("at least one subtitle cue is required")
    rows: list[str] = []
    if output_format is SubtitleFormat.WEBVTT:
        rows.extend(("WEBVTT", ""))
    previous_end_ms = 0
    for ordinal, cue in enumerate(cues, start=1):
        start_ms = max(previous_end_ms, round(cue.start * 1_000))
        end_ms = max(start_ms + 1, round(cue.end * 1_000))
        text = _normalized_text(cue.source_text)
        if output_format is SubtitleFormat.SRT:
            if cue.speaker:
                text = f"{cue.speaker}: {text}"
            rows.extend(
                (
                    str(ordinal),
                    f"{_timestamp(start_ms, ',')} --> {_timestamp(end_ms, ',')}",
                    text,
                    "",
                )
            )
        else:
            escaped = _vtt_escape(text)
            if cue.speaker:
                escaped = f"<v {_vtt_escape(cue.speaker)}>{escaped}"
            rows.extend(
                (
                    f"{_timestamp(start_ms, '.')} --> {_timestamp(end_ms, '.')}",
                    escaped,
                    "",
                )
            )
        previous_end_ms = end_ms
    return "\n".join(rows).rstrip() + "\n"


def _engine_cues(
    chunk: ChunkRecord,
    *,
    speaker: str | None,
    chunk_start: float,
    chunk_duration: float,
    next_index: int,
) -> tuple[SubtitleCue, ...]:
    raw = chunk.metadata.get("timings")
    timing_source = SubtitleTimingSource.ENGINE
    timing_confidence = SubtitleTimingConfidence.EXACT
    if not isinstance(raw, list):
        raw = chunk.metadata.get("transcription_timings")
        timing_source = SubtitleTimingSource.TRANSCRIPTION
        timing_confidence = SubtitleTimingConfidence.ESTIMATED
        if not isinstance(raw, list):
            return ()
    candidates: list[tuple[float, float, str]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        start = _number(item.get("start_seconds"))
        duration = _number(item.get("duration_seconds"))
        if start is None or duration is None:
            continue
        text = str(item.get("text") or "").strip()
        if (
            not text
            or not math.isfinite(start)
            or not math.isfinite(duration)
            or start < 0
            or duration <= 0
            or start >= chunk_duration
        ):
            continue
        candidates.append((start, min(chunk_duration, start + duration), text))
    candidates.sort(key=lambda row: (row[0], row[1], row[2]))
    cues: list[SubtitleCue] = []
    local_cursor = 0.0
    for start, end, text in candidates:
        start = max(start, local_cursor)
        if end <= start:
            continue
        cues.append(
            SubtitleCue(
                index=next_index + len(cues),
                source_text=text,
                start=chunk_start + start,
                end=chunk_start + end,
                speaker=speaker,
                confidence=timing_confidence,
                source=timing_source,
            )
        )
        local_cursor = end
    return tuple(cues)


def _segment_speakers(
    variables: Mapping[str, JsonValue], count: int
) -> tuple[str | None, ...]:
    raw = variables.get(SEGMENT_OPTIONS_VARIABLE)
    if raw is None:
        return tuple(None for _ in range(count))
    if not isinstance(raw, list) or len(raw) != count:
        raise ValueError("persisted segment options do not match the take")
    speakers: list[str | None] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise ValueError("persisted segment options are invalid")
        value = item.get("speaker")
        speakers.append(str(value).strip() if value else None)
    return tuple(speakers)


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _completed_checkpoint(chunk: ChunkRecord) -> Path | None:
    if chunk.status is not ChunkStatus.COMPLETED or not chunk.pcm_path:
        return None
    path = Path(chunk.pcm_path)
    return path if path.is_file() else None


def _pcm_duration(path: Path) -> float:
    size = path.stat().st_size
    frame_width = CANONICAL_AUDIO_FORMAT.frame_width
    if size <= 0 or size % frame_width:
        raise ValueError(f"audio checkpoint is not aligned PCM: {path.name}")
    return size / frame_width / CANONICAL_AUDIO_FORMAT.sample_rate


def _normalized_text(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "").strip()


def _vtt_escape(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _timestamp(milliseconds: int, separator: str) -> str:
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{separator}{millis:03d}"


def _safe_id(value: str) -> str:
    return "".join(character if character.isalnum() or character in "-_" else "-" for character in value)


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
