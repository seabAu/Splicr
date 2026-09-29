from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from ..domain import JobStatus, utc_now
from ..storage import LocalJobStorage
from ..store import SqliteJobStore
from .conversion import ConversionJobStore
from .domain import Artifact, ArtifactKind
from .migration import import_splicr_job
from .store import SqliteStudioStore
from .subtitles import (
    SubtitleCue,
    SubtitleFormat,
    SubtitleTimingConfidence,
    SubtitleTimingSource,
    serialize_subtitles,
)


TRANSCRIPTION_PROTOCOL_VERSION = 1
DEFAULT_TRANSCRIPTION_MODEL = "base"
TRANSCRIPTION_MODELS = ("tiny", "base", "small", "medium", "large-v3")
TRANSCRIPTION_DEVICES = ("auto", "cpu", "cuda")
TRANSCRIPTION_COMPUTE_TYPES = (
    "default",
    "int8",
    "int8_float16",
    "float16",
    "float32",
)


class TranscriptionJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class TranscriptionControlDefinition:
    key: str
    label: str
    value_type: str
    default: object
    description: str
    choices: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None


@dataclass(frozen=True, slots=True)
class TranscriptionProviderDescriptor:
    id: str
    label: str
    description: str
    controls: tuple[TranscriptionControlDefinition, ...]


@dataclass(frozen=True, slots=True)
class TranscriptionOptions:
    model: str = DEFAULT_TRANSCRIPTION_MODEL
    language: str | None = None
    device: str = "auto"
    compute_type: str = "default"
    vad_filter: bool = True
    word_timestamps: bool = False
    include_srt: bool = True
    include_vtt: bool = True
    line_timestamps: bool = False
    guessed_chapters: bool = True
    paragraph_gap_seconds: float = 2.0
    chapter_pause_seconds: float = 2.0

    def __post_init__(self) -> None:
        model = self.model.strip()
        if not model or len(model) > 240:
            raise ValueError("transcription model must be between 1 and 240 characters")
        if self.language is not None:
            language = self.language.strip()
            if not language or len(language) > 24 or not re.fullmatch(r"[A-Za-z0-9_-]+", language):
                raise ValueError(
                    "language must be a short language code or omitted for auto-detect"
                )
        if self.device not in TRANSCRIPTION_DEVICES:
            raise ValueError(f"device must be one of {', '.join(TRANSCRIPTION_DEVICES)}")
        if self.compute_type not in TRANSCRIPTION_COMPUTE_TYPES:
            raise ValueError(
                f"compute_type must be one of {', '.join(TRANSCRIPTION_COMPUTE_TYPES)}"
            )
        for name in ("paragraph_gap_seconds", "chapter_pause_seconds"):
            value = getattr(self, name)
            if not math.isfinite(value) or not 0.25 <= value <= 30:
                raise ValueError(f"{name} must be between 0.25 and 30 seconds")

    def to_mapping(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> TranscriptionOptions:
        language_value = value.get("language")
        return cls(
            model=str(value.get("model") or DEFAULT_TRANSCRIPTION_MODEL),
            language=(str(language_value).strip() if language_value else None),
            device=str(value.get("device") or "auto"),
            compute_type=str(value.get("compute_type") or "default"),
            vad_filter=bool(value.get("vad_filter", True)),
            word_timestamps=bool(value.get("word_timestamps", False)),
            include_srt=bool(value.get("include_srt", True)),
            include_vtt=bool(value.get("include_vtt", True)),
            line_timestamps=bool(value.get("line_timestamps", False)),
            guessed_chapters=bool(value.get("guessed_chapters", True)),
            paragraph_gap_seconds=_float_value(
                value.get("paragraph_gap_seconds", 2.0), field="paragraph_gap_seconds"
            ),
            chapter_pause_seconds=_float_value(
                value.get("chapter_pause_seconds", 2.0), field="chapter_pause_seconds"
            ),
        )


@dataclass(frozen=True, slots=True)
class TranscriptionWord:
    start: float
    end: float
    text: str

    def __post_init__(self) -> None:
        if not math.isfinite(self.start) or not math.isfinite(self.end):
            raise ValueError("word timings must be finite")
        if self.start < 0 or self.end < self.start:
            raise ValueError("word timing end must not precede its start")
        if not self.text.strip():
            raise ValueError("transcription word must not be blank")


@dataclass(frozen=True, slots=True)
class TranscriptionSegment:
    index: int
    start: float
    end: float
    text: str
    words: tuple[TranscriptionWord, ...] = ()

    def __post_init__(self) -> None:
        if self.index < 0:
            raise ValueError("segment index must be non-negative")
        if not math.isfinite(self.start) or not math.isfinite(self.end):
            raise ValueError("segment timings must be finite")
        if self.start < 0 or self.end <= self.start:
            raise ValueError("segment end must be after its non-negative start")
        if not self.text.strip():
            raise ValueError("transcription segment must not be blank")


@dataclass(frozen=True, slots=True)
class TranscriptionResult:
    segments: tuple[TranscriptionSegment, ...]
    language: str | None
    language_probability: float | None
    duration_seconds: float

    def __post_init__(self) -> None:
        if not self.segments:
            raise ValueError("no speech was detected in the selected audio")
        if not math.isfinite(self.duration_seconds) or self.duration_seconds < 0:
            raise ValueError("transcription duration must be finite and non-negative")


TranscriptionProgress = Callable[[float, str, float, float, int], None]
CancellationCheck = Callable[[], bool]


class TranscriptionProvider(Protocol):
    @property
    def descriptor(self) -> TranscriptionProviderDescriptor: ...

    @property
    def available(self) -> bool: ...

    async def transcribe(
        self,
        audio_path: Path,
        options: TranscriptionOptions,
        *,
        on_progress: TranscriptionProgress,
        is_cancelled: CancellationCheck,
    ) -> TranscriptionResult: ...


class TranscriptionProviderError(RuntimeError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


class TranscriptionCancelled(RuntimeError):
    pass


class FasterWhisperProvider:
    def __init__(
        self,
        *,
        python_path: Path | None,
        worker_path: Path,
        download_root: Path,
        startup_timeout_seconds: float = 600.0,
    ) -> None:
        self.python_path = Path(python_path).resolve() if python_path else None
        self.worker_path = Path(worker_path).resolve()
        self.download_root = Path(download_root).resolve()
        self.startup_timeout_seconds = startup_timeout_seconds

    @property
    def descriptor(self) -> TranscriptionProviderDescriptor:
        return TranscriptionProviderDescriptor(
            id="faster-whisper",
            label="faster-whisper",
            description=(
                "Local Whisper-compatible recognition in an isolated Python environment. "
                "The first use of a model may download it."
            ),
            controls=(
                TranscriptionControlDefinition(
                    "model",
                    "Model size",
                    "enum",
                    DEFAULT_TRANSCRIPTION_MODEL,
                    "Larger models are more accurate but require more memory and time.",
                    TRANSCRIPTION_MODELS,
                ),
                TranscriptionControlDefinition(
                    "language",
                    "Language",
                    "text",
                    "",
                    "Leave blank to auto-detect, or enter a language code such as en or es.",
                ),
                TranscriptionControlDefinition(
                    "device",
                    "Device",
                    "enum",
                    "auto",
                    "Auto selects a usable accelerator and otherwise falls back to CPU.",
                    TRANSCRIPTION_DEVICES,
                ),
                TranscriptionControlDefinition(
                    "compute_type",
                    "Compute type",
                    "enum",
                    "default",
                    "Precision/quantization used by CTranslate2.",
                    TRANSCRIPTION_COMPUTE_TYPES,
                ),
                TranscriptionControlDefinition(
                    "vad_filter",
                    "Voice activity filter",
                    "boolean",
                    True,
                    "Filter extended silence before recognition.",
                ),
                TranscriptionControlDefinition(
                    "word_timestamps",
                    "Word timings",
                    "boolean",
                    False,
                    "Retain word-level timing for later editing.",
                ),
                TranscriptionControlDefinition(
                    "paragraph_gap_seconds",
                    "Paragraph pause",
                    "decimal",
                    2.0,
                    "Start a readable paragraph after a pause this long.",
                    minimum=0.25,
                    maximum=30,
                    step=0.25,
                ),
                TranscriptionControlDefinition(
                    "chapter_pause_seconds",
                    "Guessed chapter pause",
                    "decimal",
                    2.0,
                    "Suggest a chapter after a pause this long; these marks are only guesses.",
                    minimum=0.25,
                    maximum=30,
                    step=0.25,
                ),
            ),
        )

    @property
    def available(self) -> bool:
        return bool(self.python_path and self.python_path.is_file() and self.worker_path.is_file())

    async def transcribe(
        self,
        audio_path: Path,
        options: TranscriptionOptions,
        *,
        on_progress: TranscriptionProgress,
        is_cancelled: CancellationCheck,
    ) -> TranscriptionResult:
        if not self.available or self.python_path is None:
            raise TranscriptionProviderError(
                "component_missing",
                "Configure a Python environment containing faster-whisper in Components.",
            )
        self.download_root.mkdir(parents=True, exist_ok=True)
        process = await asyncio.create_subprocess_exec(
            str(self.python_path),
            str(self.worker_path),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        assert process.stdin is not None
        assert process.stdout is not None
        assert process.stderr is not None
        stderr_task = asyncio.create_task(process.stderr.read())
        payload = {
            **options.to_mapping(),
            "audio_path": str(audio_path.resolve()),
            "download_root": str(self.download_root),
        }
        process.stdin.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        await process.stdin.drain()
        process.stdin.close()

        segments: list[TranscriptionSegment] = []
        language: str | None = None
        probability: float | None = None
        duration = 0.0
        ready = False
        completed = False
        try:
            while True:
                if is_cancelled():
                    raise TranscriptionCancelled
                try:
                    line = await asyncio.wait_for(process.stdout.readline(), timeout=0.25)
                except asyncio.TimeoutError:
                    if process.returncode is not None:
                        break
                    continue
                if not line:
                    break
                if len(line) > 1_000_000:
                    raise TranscriptionProviderError(
                        "invalid_provider_response", "transcription worker response was too large"
                    )
                try:
                    message = json.loads(line)
                except json.JSONDecodeError as error:
                    raise TranscriptionProviderError(
                        "invalid_provider_response",
                        "transcription worker returned invalid JSON",
                    ) from error
                message_type = message.get("type")
                if message_type == "ready":
                    if message.get("protocol") != TRANSCRIPTION_PROTOCOL_VERSION:
                        raise TranscriptionProviderError(
                            "protocol_mismatch", "unsupported transcription worker protocol"
                        )
                    ready = True
                elif message_type == "phase":
                    on_progress(
                        _float_value(message.get("progress", 0.01), field="progress"),
                        str(message.get("phase") or "loading_model"),
                        0.0,
                        duration,
                        len(segments),
                    )
                elif message_type == "metadata":
                    language_value = message.get("language")
                    language = str(language_value) if language_value else None
                    probability_value = message.get("language_probability")
                    probability = (
                        _float_value(probability_value, field="language_probability")
                        if probability_value is not None
                        else None
                    )
                    duration = max(
                        0.0, _float_value(message.get("duration") or 0.0, field="duration")
                    )
                    on_progress(0.05, "transcribing", 0.0, duration, len(segments))
                elif message_type == "segment":
                    segment = _segment_from_mapping(message.get("segment"), len(segments))
                    segments.append(segment)
                    processed = max(
                        segment.end,
                        _float_value(
                            message.get("processed_seconds") or 0.0,
                            field="processed_seconds",
                        ),
                    )
                    reported_duration = _float_value(
                        message.get("duration") or duration or 0.0, field="duration"
                    )
                    duration = max(duration, reported_duration, processed)
                    fraction = (
                        min(0.94, processed / reported_duration)
                        if reported_duration > 0
                        else min(0.94, len(segments) / (len(segments) + 10))
                    )
                    on_progress(fraction, "transcribing", processed, duration, len(segments))
                elif message_type == "error":
                    raise TranscriptionProviderError(
                        str(message.get("code") or "transcription_failed"),
                        str(message.get("message") or "transcription provider failed"),
                    )
                elif message_type == "complete":
                    completed = True
                    break

            await process.wait()
            stderr = (await stderr_task).decode("utf-8", errors="replace").strip()
            if not ready:
                raise TranscriptionProviderError(
                    "provider_start_failed",
                    _sanitize_detail(
                        stderr[-1_000:] or "transcription worker exited before becoming ready",
                        audio_path,
                        self.download_root,
                    ),
                )
            if process.returncode != 0 or not completed:
                raise TranscriptionProviderError(
                    "provider_process_failed",
                    _sanitize_detail(
                        stderr[-1_000:] or "transcription worker exited before completion",
                        audio_path,
                        self.download_root,
                    ),
                )
            final_duration = max(duration, segments[-1].end if segments else 0.0)
            return TranscriptionResult(tuple(segments), language, probability, final_duration)
        except asyncio.CancelledError:
            await _terminate(process)
            raise
        except TranscriptionCancelled:
            await _terminate(process)
            raise
        except Exception:
            await _terminate(process)
            raise
        finally:
            if not stderr_task.done():
                stderr_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await stderr_task


def _segment_from_mapping(value: object, index: int) -> TranscriptionSegment:
    if not isinstance(value, Mapping):
        raise TranscriptionProviderError(
            "invalid_provider_response", "transcription segment was not an object"
        )
    words_value = value.get("words")
    words: list[TranscriptionWord] = []
    if isinstance(words_value, Sequence) and not isinstance(words_value, (str, bytes)):
        for item in words_value:
            if not isinstance(item, Mapping):
                continue
            words.append(
                TranscriptionWord(
                    start=_float_value(item.get("start") or 0.0, field="word start"),
                    end=_float_value(item.get("end") or 0.0, field="word end"),
                    text=str(item.get("text") or "").strip(),
                )
            )
    return TranscriptionSegment(
        index=index,
        start=_float_value(value.get("start") or 0.0, field="segment start"),
        end=_float_value(value.get("end") or 0.0, field="segment end"),
        text=str(value.get("text") or "").strip(),
        words=tuple(words),
    )


async def _terminate(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=3)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()


class TranscriptionJobNotFoundError(LookupError):
    pass


class InvalidTranscriptionJobStateError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class TranscriptionJob:
    id: str
    source_job_id: str | None
    input_id: str | None
    source_name: str
    project_id: str | None
    take_id: str | None
    provider_id: str
    status: TranscriptionJobStatus
    phase: str
    options: TranscriptionOptions
    progress: float
    processed_seconds: float
    duration_seconds: float
    segment_count: int
    detected_language: str | None
    language_probability: float | None
    output_paths: Mapping[str, str]
    artifact_ids: Mapping[str, str]
    error_code: str | None
    error_detail: str | None
    cancel_requested: bool
    created_at: str
    updated_at: str


class TranscriptionJobStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path)

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS studio_transcription_jobs (
                    id TEXT PRIMARY KEY,
                    source_job_id TEXT,
                    input_id TEXT,
                    source_name TEXT NOT NULL,
                    project_id TEXT,
                    take_id TEXT,
                    provider_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    options_json TEXT NOT NULL,
                    progress REAL NOT NULL DEFAULT 0,
                    processed_seconds REAL NOT NULL DEFAULT 0,
                    duration_seconds REAL NOT NULL DEFAULT 0,
                    segment_count INTEGER NOT NULL DEFAULT 0,
                    detected_language TEXT,
                    language_probability REAL,
                    output_paths_json TEXT NOT NULL DEFAULT '{}',
                    artifact_ids_json TEXT NOT NULL DEFAULT '{}',
                    error_code TEXT,
                    error_detail TEXT,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    CHECK ((source_job_id IS NOT NULL) != (input_id IS NOT NULL))
                );
                CREATE INDEX IF NOT EXISTS idx_studio_transcription_jobs_created
                    ON studio_transcription_jobs(created_at DESC);
                """
            )

    def create(self, job: TranscriptionJob) -> TranscriptionJob:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO studio_transcription_jobs (
                    id, source_job_id, input_id, source_name, project_id, take_id,
                    provider_id, status, phase, options_json, progress,
                    processed_seconds, duration_seconds, segment_count,
                    detected_language, language_probability, output_paths_json,
                    artifact_ids_json, error_code, error_detail, cancel_requested,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._values(job),
            )
        return self.get(job.id)

    def get(self, job_id: str) -> TranscriptionJob:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM studio_transcription_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        if row is None:
            raise TranscriptionJobNotFoundError(job_id)
        return self._from_row(row)

    def list(self, *, limit: int = 100) -> list[TranscriptionJob]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM studio_transcription_jobs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def requeue_interrupted(self) -> list[str]:
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE studio_transcription_jobs
                SET status = ?, phase = ?, progress = 0, processed_seconds = 0,
                    segment_count = 0, cancel_requested = 0, error_code = NULL,
                    error_detail = NULL, updated_at = ?
                WHERE status IN (?, ?)
                """,
                (
                    TranscriptionJobStatus.QUEUED.value,
                    "queued",
                    now,
                    TranscriptionJobStatus.RUNNING.value,
                    TranscriptionJobStatus.CANCEL_REQUESTED.value,
                ),
            )
            rows = connection.execute(
                "SELECT id FROM studio_transcription_jobs WHERE status = ? ORDER BY created_at",
                (TranscriptionJobStatus.QUEUED.value,),
            ).fetchall()
        return [row["id"] for row in rows]

    def claim(self, job_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE studio_transcription_jobs
                SET status = ?, phase = ?, updated_at = ?
                WHERE id = ? AND status = ? AND cancel_requested = 0
                """,
                (
                    TranscriptionJobStatus.RUNNING.value,
                    "starting",
                    utc_now(),
                    job_id,
                    TranscriptionJobStatus.QUEUED.value,
                ),
            )
        return cursor.rowcount == 1

    def update_progress(
        self,
        job_id: str,
        progress: float,
        phase: str,
        processed_seconds: float,
        duration_seconds: float,
        segment_count: int,
    ) -> None:
        self._update(
            job_id,
            progress=max(0.0, min(0.99, progress)),
            phase=phase,
            processed_seconds=max(0.0, processed_seconds),
            duration_seconds=max(0.0, duration_seconds),
            segment_count=max(0, segment_count),
        )

    def complete(
        self,
        job_id: str,
        result: TranscriptionResult,
        output_paths: Mapping[str, str],
        artifact_ids: Mapping[str, str],
    ) -> TranscriptionJob:
        self._transition(
            job_id,
            TranscriptionJobStatus.COMPLETED,
            phase="completed",
            progress=1.0,
            processed_seconds=result.duration_seconds,
            duration_seconds=result.duration_seconds,
            segment_count=len(result.segments),
            detected_language=result.language,
            language_probability=result.language_probability,
            output_paths_json=json.dumps(dict(output_paths), sort_keys=True),
            artifact_ids_json=json.dumps(dict(artifact_ids), sort_keys=True),
            error_code=None,
            error_detail=None,
            cancel_requested=0,
        )
        return self.get(job_id)

    def fail(self, job_id: str, code: str, detail: str) -> TranscriptionJob:
        self._transition(
            job_id,
            TranscriptionJobStatus.FAILED,
            phase="failed",
            error_code=code,
            error_detail=detail,
            cancel_requested=0,
        )
        return self.get(job_id)

    def request_cancel(self, job_id: str) -> TranscriptionJob:
        job = self.get(job_id)
        if job.status is TranscriptionJobStatus.QUEUED:
            self._transition(
                job_id,
                TranscriptionJobStatus.CANCELLED,
                phase="cancelled",
                cancel_requested=1,
            )
        elif job.status is TranscriptionJobStatus.RUNNING:
            self._transition(
                job_id,
                TranscriptionJobStatus.CANCEL_REQUESTED,
                phase="cancelling",
                cancel_requested=1,
            )
        elif job.status not in {
            TranscriptionJobStatus.CANCEL_REQUESTED,
            TranscriptionJobStatus.CANCELLED,
        }:
            raise InvalidTranscriptionJobStateError(f"cannot cancel a {job.status.value} job")
        return self.get(job_id)

    def mark_cancelled(self, job_id: str) -> TranscriptionJob:
        self._transition(
            job_id,
            TranscriptionJobStatus.CANCELLED,
            phase="cancelled",
            cancel_requested=1,
        )
        return self.get(job_id)

    def retry(self, job_id: str) -> TranscriptionJob:
        job = self.get(job_id)
        if job.status not in {TranscriptionJobStatus.FAILED, TranscriptionJobStatus.CANCELLED}:
            raise InvalidTranscriptionJobStateError(f"cannot retry a {job.status.value} job")
        self._transition(
            job_id,
            TranscriptionJobStatus.QUEUED,
            phase="queued",
            progress=0.0,
            processed_seconds=0.0,
            segment_count=0,
            output_paths_json="{}",
            artifact_ids_json="{}",
            error_code=None,
            error_detail=None,
            cancel_requested=0,
        )
        return self.get(job_id)

    def _transition(self, job_id: str, status: TranscriptionJobStatus, **values: object) -> None:
        self._update(job_id, status=status.value, **values)

    def _update(self, job_id: str, **values: object) -> None:
        assignments = ["updated_at = ?"]
        parameters: list[object] = [utc_now()]
        for key, value in values.items():
            assignments.append(f"{key} = ?")
            parameters.append(value)
        parameters.append(job_id)
        with self._connect() as connection:
            cursor = connection.execute(
                f"UPDATE studio_transcription_jobs SET {', '.join(assignments)} WHERE id = ?",
                parameters,
            )
        if cursor.rowcount != 1:
            raise TranscriptionJobNotFoundError(job_id)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _values(job: TranscriptionJob) -> tuple[object, ...]:
        return (
            job.id,
            job.source_job_id,
            job.input_id,
            job.source_name,
            job.project_id,
            job.take_id,
            job.provider_id,
            job.status.value,
            job.phase,
            json.dumps(job.options.to_mapping(), sort_keys=True),
            job.progress,
            job.processed_seconds,
            job.duration_seconds,
            job.segment_count,
            job.detected_language,
            job.language_probability,
            json.dumps(dict(job.output_paths), sort_keys=True),
            json.dumps(dict(job.artifact_ids), sort_keys=True),
            job.error_code,
            job.error_detail,
            int(job.cancel_requested),
            job.created_at,
            job.updated_at,
        )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> TranscriptionJob:
        return TranscriptionJob(
            id=row["id"],
            source_job_id=row["source_job_id"],
            input_id=row["input_id"],
            source_name=row["source_name"],
            project_id=row["project_id"],
            take_id=row["take_id"],
            provider_id=row["provider_id"],
            status=TranscriptionJobStatus(row["status"]),
            phase=row["phase"],
            options=TranscriptionOptions.from_mapping(json.loads(row["options_json"])),
            progress=row["progress"],
            processed_seconds=row["processed_seconds"],
            duration_seconds=row["duration_seconds"],
            segment_count=row["segment_count"],
            detected_language=row["detected_language"],
            language_probability=row["language_probability"],
            output_paths=json.loads(row["output_paths_json"]),
            artifact_ids=json.loads(row["artifact_ids_json"]),
            error_code=row["error_code"],
            error_detail=row["error_detail"],
            cancel_requested=bool(row["cancel_requested"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


class TranscriptionJobService:
    def __init__(
        self,
        *,
        store: TranscriptionJobStore,
        conversion_store: ConversionJobStore,
        source_store: SqliteJobStore,
        source_storage: LocalJobStorage,
        studio_store: SqliteStudioStore,
        output_root: Path,
        providers: Sequence[TranscriptionProvider],
    ) -> None:
        self.store = store
        self.conversion_store = conversion_store
        self.source_store = source_store
        self.source_storage = source_storage
        self.studio_store = studio_store
        self.output_root = Path(output_root)
        self.providers = {provider.descriptor.id: provider for provider in providers}
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._worker is not None:
            return
        self.store.initialize()
        self.output_root.mkdir(parents=True, exist_ok=True)
        for job_id in self.store.requeue_interrupted():
            self._queue.put_nowait(job_id)
        self._worker = asyncio.create_task(self._worker_loop(), name="splicr-transcription-worker")

    async def stop(self) -> None:
        if self._worker is None:
            return
        self._worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._worker
        self._worker = None

    def capabilities(self) -> list[dict[str, object]]:
        return [
            {
                "id": provider.descriptor.id,
                "label": provider.descriptor.label,
                "description": provider.descriptor.description,
                "available": provider.available,
                "controls": [asdict(control) for control in provider.descriptor.controls],
            }
            for provider in self.providers.values()
        ]

    async def submit(
        self,
        *,
        provider_id: str,
        options: TranscriptionOptions,
        source_job_id: str | None = None,
        input_id: str | None = None,
    ) -> TranscriptionJob:
        try:
            provider = self.providers[provider_id]
        except KeyError as error:
            raise ValueError("unknown transcription provider") from error
        if not provider.available:
            raise TranscriptionProviderError(
                "component_missing",
                f"{provider.descriptor.label} is not configured. Open Components to select its Python environment.",
            )
        if bool(source_job_id) == bool(input_id):
            raise ValueError("choose exactly one completed take or imported audio file")
        project_id: str | None = None
        take_id: str | None = None
        if source_job_id:
            source = self.source_store.get_job(source_job_id)
            if source.status is not JobStatus.COMPLETED:
                raise ValueError("transcription requires a completed narration take")
            path = (
                Path(source.output_path)
                if source.output_path
                else self.source_storage.output_path(source.id)
            )
            if not path.is_file():
                raise FileNotFoundError("the completed take's audio file is missing")
            imported = import_splicr_job(
                job_id=source_job_id,
                job_store=self.source_store,
                job_storage=self.source_storage,
                studio_store=self.studio_store,
            )
            project_id = imported.project_id
            take_id = imported.take_id
            source_name = f"{source.provider} · {source.voice} · {source.id[:8]}"
        else:
            upload = self.conversion_store.get_input(input_id or "")
            if not Path(upload.path).is_file():
                raise FileNotFoundError("the imported audio file is missing")
            source_name = upload.original_name
        now = utc_now()
        job = self.store.create(
            TranscriptionJob(
                id=uuid.uuid4().hex,
                source_job_id=source_job_id,
                input_id=input_id,
                source_name=source_name,
                project_id=project_id,
                take_id=take_id,
                provider_id=provider_id,
                status=TranscriptionJobStatus.QUEUED,
                phase="queued",
                options=options,
                progress=0.0,
                processed_seconds=0.0,
                duration_seconds=0.0,
                segment_count=0,
                detected_language=None,
                language_probability=None,
                output_paths={},
                artifact_ids={},
                error_code=None,
                error_detail=None,
                cancel_requested=False,
                created_at=now,
                updated_at=now,
            )
        )
        await self._queue.put(job.id)
        return job

    async def cancel(self, job_id: str) -> TranscriptionJob:
        return self.store.request_cancel(job_id)

    async def retry(self, job_id: str) -> TranscriptionJob:
        job = self.store.retry(job_id)
        await self._queue.put(job.id)
        return job

    def output_for(self, job_id: str, output_name: str) -> Path:
        job = self.store.get(job_id)
        if job.status is not TranscriptionJobStatus.COMPLETED:
            raise InvalidTranscriptionJobStateError("transcription output is not ready")
        path_value = job.output_paths.get(output_name)
        if not path_value:
            raise FileNotFoundError("transcription output not found")
        path = Path(path_value)
        if not path.is_file():
            raise FileNotFoundError("transcription output file is missing")
        return path

    async def _worker_loop(self) -> None:
        while True:
            job_id = await self._queue.get()
            try:
                if self.store.claim(job_id):
                    await self._transcribe(job_id)
            finally:
                self._queue.task_done()

    async def _transcribe(self, job_id: str) -> None:
        job = self.store.get(job_id)
        provider = self.providers[job.provider_id]
        source_path = self._source_path(job)
        job_directory = self.output_root / job.id
        build_directory = job_directory / f".build-{uuid.uuid4().hex}"
        final_directory = job_directory / "outputs"
        shutil.rmtree(build_directory, ignore_errors=True)
        build_directory.mkdir(parents=True, exist_ok=False)

        def update(
            fraction: float,
            phase: str,
            processed_seconds: float,
            duration_seconds: float,
            segment_count: int,
        ) -> None:
            mapped = 0.02 + max(0.0, min(1.0, fraction)) * 0.9
            self.store.update_progress(
                job.id,
                mapped,
                phase,
                processed_seconds,
                duration_seconds,
                segment_count,
            )

        try:
            result = await provider.transcribe(
                source_path,
                job.options,
                on_progress=update,
                is_cancelled=lambda: self.store.get(job.id).cancel_requested,
            )
            if self.store.get(job.id).cancel_requested:
                raise TranscriptionCancelled
            self.store.update_progress(
                job.id,
                0.96,
                "materializing",
                result.duration_seconds,
                result.duration_seconds,
                len(result.segments),
            )
            local_outputs = materialize_transcription(
                build_directory, result, job.options, Path(job.source_name).stem
            )
            if final_directory.exists():
                shutil.rmtree(final_directory)
            os.replace(build_directory, final_directory)
            outputs = {
                name: str((final_directory / path.name).resolve())
                for name, path in local_outputs.items()
            }
            artifacts = self._record_artifacts(job, result, outputs)
            self.store.complete(job.id, result, outputs, artifacts)
        except TranscriptionCancelled:
            shutil.rmtree(build_directory, ignore_errors=True)
            self.store.mark_cancelled(job.id)
        except asyncio.CancelledError:
            shutil.rmtree(build_directory, ignore_errors=True)
            raise
        except TranscriptionProviderError as error:
            shutil.rmtree(build_directory, ignore_errors=True)
            self.store.fail(job.id, error.code, error.detail)
        except Exception as error:
            shutil.rmtree(build_directory, ignore_errors=True)
            code = (
                "no_speech_detected"
                if "no speech" in str(error).casefold()
                else "transcription_failed"
            )
            self.store.fail(
                job.id,
                code,
                _sanitize_detail(str(error), source_path, job_directory, self.output_root),
            )

    def _source_path(self, job: TranscriptionJob) -> Path:
        if job.source_job_id:
            source = self.source_store.get_job(job.source_job_id)
            return (
                Path(source.output_path)
                if source.output_path
                else self.source_storage.output_path(source.id)
            )
        return Path(self.conversion_store.get_input(job.input_id or "").path)

    def _record_artifacts(
        self,
        job: TranscriptionJob,
        result: TranscriptionResult,
        outputs: Mapping[str, str],
    ) -> dict[str, str]:
        if not job.project_id or not job.take_id:
            return {}
        kinds = {
            "transcript": (ArtifactKind.TRANSCRIPT, "text/markdown"),
            "segments": (ArtifactKind.MANIFEST, "application/json"),
            "srt": (ArtifactKind.SUBTITLES, "application/x-subrip"),
            "vtt": (ArtifactKind.SUBTITLES, "text/vtt"),
            "chapters": (ArtifactKind.CHAPTERS, "text/plain"),
        }
        artifact_ids: dict[str, str] = {}
        for name, path_value in outputs.items():
            path = Path(path_value)
            kind, media_type = kinds[name]
            artifact_id = uuid.uuid4().hex
            self.studio_store.add_artifact(
                Artifact(
                    id=artifact_id,
                    project_id=job.project_id,
                    take_id=job.take_id,
                    kind=kind,
                    path=str(path.resolve()),
                    media_type=media_type,
                    size_bytes=path.stat().st_size,
                    sha256=_sha256(path),
                    metadata={
                        "source": "transcription",
                        "provider": job.provider_id,
                        "model": job.options.model,
                        "detected_language": result.language,
                        "timing_confidence": "estimated",
                        "guessed_chapters": name == "chapters",
                    },
                )
            )
            artifact_ids[name] = artifact_id
        return artifact_ids


def regroup_paragraphs(
    segments: Sequence[TranscriptionSegment], *, gap_seconds: float = 2.0
) -> tuple[str, ...]:
    paragraphs: list[str] = []
    current: list[str] = []
    previous_end: float | None = None
    for segment in segments:
        if previous_end is not None and segment.start - previous_end >= gap_seconds and current:
            paragraphs.append(" ".join(current))
            current = []
        current.append(segment.text.strip())
        previous_end = segment.end
    if current:
        paragraphs.append(" ".join(current))
    return tuple(paragraphs)


def guess_chapters(
    segments: Sequence[TranscriptionSegment],
    *,
    gap_seconds: float = 2.0,
    max_title_words: int = 9,
) -> tuple[dict[str, object], ...]:
    marks: list[dict[str, object]] = []
    previous_end: float | None = None
    for segment in segments:
        if previous_end is None or segment.start - previous_end >= gap_seconds:
            words = re.findall(r"[\w'’-]+", segment.text, re.UNICODE)[:max_title_words]
            title = " ".join(words) or "Section"
            marks.append(
                {
                    "title": title[:1].upper() + title[1:],
                    "seconds": 0.0 if previous_end is None else segment.start,
                    "guessed": True,
                }
            )
        previous_end = segment.end
    return tuple(marks)


def materialize_transcription(
    directory: Path,
    result: TranscriptionResult,
    options: TranscriptionOptions,
    title: str,
) -> dict[str, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, Path] = {}
    segments_path = directory / "segments.json"
    segment_payload = {
        "schema_version": 1,
        "source": "transcription",
        "timing_confidence": "estimated",
        "language": result.language,
        "language_probability": result.language_probability,
        "duration_seconds": result.duration_seconds,
        "segments": [
            {
                "index": segment.index,
                "start": segment.start,
                "end": segment.end,
                "text": segment.text,
                "words": [asdict(word) for word in segment.words],
            }
            for segment in result.segments
        ],
    }
    _atomic_text(segments_path, json.dumps(segment_payload, indent=2, ensure_ascii=False) + "\n")
    outputs["segments"] = segments_path

    transcript_path = directory / "transcript.md"
    lines = [f"# {title}", ""]
    language = result.language or "unknown"
    lines.extend(
        [
            (
                f"*Machine transcription · {result.duration_seconds / 60:.1f} minutes · "
                f"detected language: {language}. Review before publication.*"
            ),
            "",
        ]
    )
    if options.line_timestamps:
        for segment in result.segments:
            lines.extend([f"**[{_clock(segment.start)}]** {segment.text}", ""])
    else:
        for paragraph in regroup_paragraphs(
            result.segments, gap_seconds=options.paragraph_gap_seconds
        ):
            lines.extend([paragraph, ""])
    _atomic_text(transcript_path, "\n".join(lines).strip() + "\n")
    outputs["transcript"] = transcript_path

    cues = tuple(
        SubtitleCue(
            index=segment.index,
            source_text=segment.text,
            start=segment.start,
            end=segment.end,
            speaker=None,
            confidence=SubtitleTimingConfidence.ESTIMATED,
            source=SubtitleTimingSource.TRANSCRIPTION,
        )
        for segment in result.segments
    )
    if options.include_srt:
        path = directory / "transcript.srt"
        _atomic_text(path, serialize_subtitles(cues, SubtitleFormat.SRT))
        outputs["srt"] = path
    if options.include_vtt:
        path = directory / "transcript.vtt"
        _atomic_text(path, serialize_subtitles(cues, SubtitleFormat.WEBVTT))
        outputs["vtt"] = path
    if options.guessed_chapters:
        path = directory / "guessed-chapters.txt"
        marks = guess_chapters(result.segments, gap_seconds=options.chapter_pause_seconds)
        chapter_lines = [
            "# Guessed chapters",
            "# Derived from pauses in machine-recognized speech; review and edit before use.",
            "",
            *[
                f"{_clock(_float_value(mark['seconds'], field='chapter seconds'))} {mark['title']}"
                for mark in marks
            ],
        ]
        _atomic_text(path, "\n".join(chapter_lines).rstrip() + "\n")
        outputs["chapters"] = path
    return outputs


def _clock(seconds: float) -> str:
    whole = int(max(0.0, seconds))
    hours, remainder = divmod(whole, 3_600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


def _float_value(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"{field} must be numeric")
    try:
        converted = float(value)
    except ValueError as error:
        raise ValueError(f"{field} must be numeric") from error
    if not math.isfinite(converted):
        raise ValueError(f"{field} must be finite")
    return converted


def _sanitize_detail(detail: str, *paths: Path) -> str:
    sanitized = detail
    for path in paths:
        values = {str(path), str(path.resolve())}
        for value in values:
            if value:
                sanitized = sanitized.replace(value, "<managed-path>")
    return sanitized[-2_000:]


def _atomic_text(path: Path, value: str) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(value, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
