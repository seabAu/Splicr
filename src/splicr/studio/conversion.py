from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import mimetypes
import os
import shutil
import sqlite3
import threading
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from ..domain import JobStatus, utc_now
from ..storage import LocalJobStorage
from ..store import SqliteJobStore
from .domain import Artifact, ArtifactKind
from .migration import import_splicr_job
from .store import SqliteStudioStore


class AudioOutputFormat(StrEnum):
    MP3 = "mp3"
    M4A = "m4a"
    WAV = "wav"
    FLAC = "flac"


class SplitMode(StrEnum):
    NONE = "none"
    TIME = "time"
    SIZE = "size"


class ConversionJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    FAILED = "failed"
    COMPLETED = "completed"


_BITRATES = {
    AudioOutputFormat.MP3: (64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 320),
    AudioOutputFormat.M4A: (48, 64, 80, 96, 112, 128, 144, 160, 176, 192, 192),
}
_MEDIA_TYPES = {
    AudioOutputFormat.MP3: "audio/mpeg",
    AudioOutputFormat.M4A: "audio/mp4",
    AudioOutputFormat.WAV: "audio/wav",
    AudioOutputFormat.FLAC: "audio/flac",
}
_UPLOAD_SUFFIXES = {
    ".aac",
    ".aif",
    ".aiff",
    ".flac",
    ".m4a",
    ".mka",
    ".mov",
    ".mp3",
    ".mp4",
    ".oga",
    ".ogg",
    ".opus",
    ".wav",
    ".webm",
    ".wma",
}


@dataclass(frozen=True, slots=True)
class ConversionSpec:
    output_format: AudioOutputFormat = AudioOutputFormat.MP3
    quality_pct: int = 70
    sample_rate: int = 48_000
    bit_depth: int = 16
    channels: int = 0
    normalize_loudness: bool = False
    split_mode: SplitMode = SplitMode.NONE
    split_minutes: float = 20.0
    split_megabytes: float = 25.0

    def __post_init__(self) -> None:
        if not 0 <= self.quality_pct <= 100:
            raise ValueError("quality_pct must be between 0 and 100")
        if self.sample_rate not in {16_000, 22_050, 24_000, 44_100, 48_000}:
            raise ValueError("sample_rate must be 16000, 22050, 24000, 44100, or 48000")
        if self.bit_depth not in {16, 24}:
            raise ValueError("bit_depth must be 16 or 24")
        if self.channels not in {0, 1, 2}:
            raise ValueError("channels must be 0, 1, or 2")
        if not 0.1 <= self.split_minutes <= 1_440:
            raise ValueError("split_minutes must be between 0.1 and 1440")
        if not 0.1 <= self.split_megabytes <= 4_096:
            raise ValueError("split_megabytes must be between 0.1 and 4096")

    def to_mapping(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, value: dict[str, object]) -> ConversionSpec:
        return cls(
            **{
                **value,
                "output_format": AudioOutputFormat(str(value.get("output_format", "mp3"))),
                "split_mode": SplitMode(str(value.get("split_mode", "none"))),
            }
        )


@dataclass(frozen=True, slots=True)
class ConversionInput:
    id: str
    original_name: str
    path: str
    media_type: str
    size_bytes: int
    created_at: str


@dataclass(frozen=True, slots=True)
class ConversionJob:
    id: str
    source_job_id: str | None
    input_id: str | None
    source_name: str
    project_id: str | None
    take_id: str | None
    status: ConversionJobStatus
    spec: ConversionSpec
    duration_seconds: float
    progress: float
    output_path: str | None
    part_paths: tuple[str, ...]
    artifact_ids: tuple[str, ...]
    error_code: str | None
    error_detail: str | None
    cancel_requested: bool
    created_at: str
    updated_at: str


class ConversionJobNotFoundError(LookupError):
    pass


class ConversionInputNotFoundError(LookupError):
    pass


class InvalidConversionJobStateError(RuntimeError):
    pass


class ConversionError(RuntimeError):
    pass


class ConversionCancelled(RuntimeError):
    pass


class ConversionJobStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path)
        self._lock = threading.RLock()

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS studio_conversion_inputs (
                    id TEXT PRIMARY KEY,
                    original_name TEXT NOT NULL,
                    path TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS studio_conversion_jobs (
                    id TEXT PRIMARY KEY,
                    source_job_id TEXT,
                    input_id TEXT,
                    source_name TEXT NOT NULL,
                    project_id TEXT,
                    take_id TEXT,
                    status TEXT NOT NULL,
                    spec_json TEXT NOT NULL,
                    duration_seconds REAL NOT NULL,
                    progress REAL NOT NULL DEFAULT 0,
                    output_path TEXT,
                    part_paths_json TEXT NOT NULL DEFAULT '[]',
                    artifact_ids_json TEXT NOT NULL DEFAULT '[]',
                    error_code TEXT,
                    error_detail TEXT,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    CHECK ((source_job_id IS NOT NULL) != (input_id IS NOT NULL))
                );
                CREATE INDEX IF NOT EXISTS idx_studio_conversion_jobs_created
                    ON studio_conversion_jobs(created_at DESC);
                """
            )

    def save_input(self, item: ConversionInput) -> ConversionInput:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO studio_conversion_inputs
                    (id, original_name, path, media_type, size_bytes, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    item.id,
                    item.original_name,
                    item.path,
                    item.media_type,
                    item.size_bytes,
                    item.created_at,
                ),
            )
        return self.get_input(item.id)

    def get_input(self, input_id: str) -> ConversionInput:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM studio_conversion_inputs WHERE id = ?", (input_id,)
            ).fetchone()
        if row is None:
            raise ConversionInputNotFoundError(input_id)
        return ConversionInput(
            id=row["id"],
            original_name=row["original_name"],
            path=row["path"],
            media_type=row["media_type"],
            size_bytes=row["size_bytes"],
            created_at=row["created_at"],
        )

    def list_inputs(self, *, limit: int = 100) -> list[ConversionInput]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM studio_conversion_inputs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self.get_input(row["id"]) for row in rows]

    def create(self, job: ConversionJob) -> ConversionJob:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO studio_conversion_jobs (
                    id, source_job_id, input_id, source_name, project_id, take_id,
                    status, spec_json, duration_seconds, progress, output_path,
                    part_paths_json, artifact_ids_json, error_code, error_detail,
                    cancel_requested, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._values(job),
            )
        return self.get(job.id)

    def get(self, job_id: str) -> ConversionJob:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM studio_conversion_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        if row is None:
            raise ConversionJobNotFoundError(job_id)
        return self._from_row(row)

    def list(self, *, limit: int = 100) -> list[ConversionJob]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM studio_conversion_jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def requeue_interrupted(self) -> list[str]:
        now = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE studio_conversion_jobs
                SET status = ?, progress = 0, cancel_requested = 0,
                    error_code = NULL, error_detail = NULL, updated_at = ?
                WHERE status IN (?, ?)
                """,
                (
                    ConversionJobStatus.QUEUED.value,
                    now,
                    ConversionJobStatus.RUNNING.value,
                    ConversionJobStatus.CANCEL_REQUESTED.value,
                ),
            )
            rows = connection.execute(
                "SELECT id FROM studio_conversion_jobs WHERE status = ? ORDER BY created_at",
                (ConversionJobStatus.QUEUED.value,),
            ).fetchall()
        return [row["id"] for row in rows]

    def claim(self, job_id: str) -> bool:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE studio_conversion_jobs
                SET status = ?, progress = 0, updated_at = ?
                WHERE id = ? AND status = ? AND cancel_requested = 0
                """,
                (
                    ConversionJobStatus.RUNNING.value,
                    utc_now(),
                    job_id,
                    ConversionJobStatus.QUEUED.value,
                ),
            )
        return cursor.rowcount == 1

    def update_progress(self, job_id: str, progress: float) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE studio_conversion_jobs SET progress = ?, updated_at = ? WHERE id = ?",
                (max(0.0, min(1.0, progress)), utc_now(), job_id),
            )

    def complete(
        self,
        job_id: str,
        output_path: Path,
        part_paths: list[Path],
        artifact_ids: list[str],
    ) -> ConversionJob:
        self._transition(
            job_id,
            ConversionJobStatus.COMPLETED,
            progress=1.0,
            output_path=str(output_path.resolve()),
            part_paths_json=json.dumps([str(path.resolve()) for path in part_paths]),
            artifact_ids_json=json.dumps(artifact_ids),
            cancel_requested=0,
            error_code=None,
            error_detail=None,
        )
        return self.get(job_id)

    def fail(self, job_id: str, code: str, detail: str) -> ConversionJob:
        self._transition(
            job_id,
            ConversionJobStatus.FAILED,
            error_code=code,
            error_detail=detail,
            cancel_requested=0,
        )
        return self.get(job_id)

    def request_cancel(self, job_id: str) -> ConversionJob:
        job = self.get(job_id)
        if job.status is ConversionJobStatus.QUEUED:
            self._transition(job_id, ConversionJobStatus.CANCELLED, cancel_requested=1)
        elif job.status is ConversionJobStatus.RUNNING:
            self._transition(job_id, ConversionJobStatus.CANCEL_REQUESTED, cancel_requested=1)
        elif job.status not in {
            ConversionJobStatus.CANCEL_REQUESTED,
            ConversionJobStatus.CANCELLED,
        }:
            raise InvalidConversionJobStateError(f"cannot cancel a {job.status.value} job")
        return self.get(job_id)

    def mark_cancelled(self, job_id: str) -> ConversionJob:
        self._transition(job_id, ConversionJobStatus.CANCELLED, cancel_requested=1)
        return self.get(job_id)

    def retry(self, job_id: str) -> ConversionJob:
        job = self.get(job_id)
        if job.status not in {ConversionJobStatus.FAILED, ConversionJobStatus.CANCELLED}:
            raise InvalidConversionJobStateError(f"cannot retry a {job.status.value} job")
        self._transition(
            job_id,
            ConversionJobStatus.QUEUED,
            progress=0.0,
            output_path=None,
            part_paths_json="[]",
            artifact_ids_json="[]",
            error_code=None,
            error_detail=None,
            cancel_requested=0,
        )
        return self.get(job_id)

    def _transition(self, job_id: str, status: ConversionJobStatus, **values: object) -> None:
        assignments = ["status = ?", "updated_at = ?"]
        parameters: list[object] = [status.value, utc_now()]
        for key, value in values.items():
            assignments.append(f"{key} = ?")
            parameters.append(value)
        parameters.append(job_id)
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                f"UPDATE studio_conversion_jobs SET {', '.join(assignments)} WHERE id = ?",
                parameters,
            )
        if cursor.rowcount != 1:
            raise ConversionJobNotFoundError(job_id)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _values(job: ConversionJob) -> tuple[object, ...]:
        return (
            job.id,
            job.source_job_id,
            job.input_id,
            job.source_name,
            job.project_id,
            job.take_id,
            job.status.value,
            json.dumps(job.spec.to_mapping(), sort_keys=True),
            job.duration_seconds,
            job.progress,
            job.output_path,
            json.dumps(job.part_paths),
            json.dumps(job.artifact_ids),
            job.error_code,
            job.error_detail,
            int(job.cancel_requested),
            job.created_at,
            job.updated_at,
        )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> ConversionJob:
        return ConversionJob(
            id=row["id"],
            source_job_id=row["source_job_id"],
            input_id=row["input_id"],
            source_name=row["source_name"],
            project_id=row["project_id"],
            take_id=row["take_id"],
            status=ConversionJobStatus(row["status"]),
            spec=ConversionSpec.from_mapping(json.loads(row["spec_json"])),
            duration_seconds=row["duration_seconds"],
            progress=row["progress"],
            output_path=row["output_path"],
            part_paths=tuple(json.loads(row["part_paths_json"])),
            artifact_ids=tuple(json.loads(row["artifact_ids_json"])),
            error_code=row["error_code"],
            error_detail=row["error_detail"],
            cancel_requested=bool(row["cancel_requested"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


ProgressCallback = Callable[[float], None]
CancelCallback = Callable[[], bool]


class AudioConverter(Protocol):
    @property
    def available(self) -> bool: ...

    async def probe_duration(self, source_path: Path) -> float: ...

    async def convert(
        self,
        source_path: Path,
        output_path: Path,
        spec: ConversionSpec,
        *,
        duration_seconds: float,
        on_progress: ProgressCallback,
        is_cancelled: CancelCallback,
    ) -> None: ...

    async def split(
        self,
        source_path: Path,
        output_directory: Path,
        spec: ConversionSpec,
        *,
        duration_seconds: float,
        on_progress: ProgressCallback,
        is_cancelled: CancelCallback,
    ) -> list[Path]: ...


class FfmpegAudioConverter:
    def __init__(self, executable: str = "ffmpeg", probe_executable: str = "ffprobe") -> None:
        self.executable = executable
        self.probe_executable = probe_executable

    @property
    def available(self) -> bool:
        return shutil.which(self.executable) is not None and shutil.which(self.probe_executable) is not None

    async def probe_duration(self, source_path: Path) -> float:
        process = await asyncio.create_subprocess_exec(
            self.probe_executable,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(source_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            detail = stderr.decode(errors="replace").strip()[-600:]
            raise ConversionError(f"FFmpeg could not read this audio file: {detail}")
        try:
            duration = float(stdout.decode().strip())
        except ValueError as error:
            raise ConversionError("FFmpeg did not report a usable audio duration") from error
        if duration <= 0:
            raise ConversionError("The selected audio has no playable duration")
        return duration

    async def convert(
        self,
        source_path: Path,
        output_path: Path,
        spec: ConversionSpec,
        *,
        duration_seconds: float,
        on_progress: ProgressCallback,
        is_cancelled: CancelCallback,
    ) -> None:
        command = self.build_conversion_command(source_path, output_path, spec)
        await self._run(
            command,
            duration_seconds=duration_seconds,
            on_progress=on_progress,
            is_cancelled=is_cancelled,
        )

    async def split(
        self,
        source_path: Path,
        output_directory: Path,
        spec: ConversionSpec,
        *,
        duration_seconds: float,
        on_progress: ProgressCallback,
        is_cancelled: CancelCallback,
    ) -> list[Path]:
        output_directory.mkdir(parents=True, exist_ok=True)
        if spec.split_mode is SplitMode.TIME:
            target_seconds = spec.split_minutes * 60
            max_bytes = None
        elif spec.split_mode is SplitMode.SIZE:
            max_bytes = int(spec.split_megabytes * 1_000_000)
            bytes_per_second = source_path.stat().st_size / duration_seconds
            target_seconds = max(1.0, max_bytes / bytes_per_second * 0.97)
        else:
            return []

        pattern = output_directory / f"part-%03d.{spec.output_format.value}"
        parts: list[Path] = []
        for attempt in range(4):
            for old in output_directory.glob(f"part-*.{spec.output_format.value}"):
                old.unlink(missing_ok=True)
            command = [
                self.executable,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(source_path),
                "-map",
                "0:a:0",
                "-f",
                "segment",
                "-segment_time",
                f"{target_seconds:.3f}",
                "-reset_timestamps",
                "1",
                "-c",
                "copy",
                "-progress",
                "pipe:1",
                "-nostats",
                str(pattern),
            ]
            await self._run(
                command,
                duration_seconds=duration_seconds,
                on_progress=on_progress,
                is_cancelled=is_cancelled,
            )
            parts = sorted(output_directory.glob(f"part-*.{spec.output_format.value}"))
            if not parts or any(path.stat().st_size == 0 for path in parts):
                raise ConversionError("Splitting completed without producing usable audio parts")
            if max_bytes is None:
                break
            largest = max(path.stat().st_size for path in parts)
            if largest <= max_bytes:
                break
            if attempt == 3:
                raise ConversionError(
                    "The requested size limit could not be met after four measured attempts; "
                    "choose a lower quality or a larger part size."
                )
            target_seconds *= (max_bytes / largest) * 0.95
        return parts

    def build_conversion_command(
        self, source_path: Path, output_path: Path, spec: ConversionSpec
    ) -> list[str]:
        command = [
            self.executable,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source_path),
            "-map",
            "0:a:0",
            "-vn",
            "-map_metadata",
            "0",
            "-ar",
            str(spec.sample_rate),
        ]
        if spec.channels:
            command += ["-ac", str(spec.channels)]
        if spec.normalize_loudness:
            command += ["-af", "loudnorm=I=-16:TP=-1.5:LRA=11"]
        quality_index = min(10, max(0, (spec.quality_pct + 5) // 10))
        if spec.output_format is AudioOutputFormat.WAV:
            command += ["-c:a", f"pcm_s{spec.bit_depth}le"]
        elif spec.output_format is AudioOutputFormat.FLAC:
            command += [
                "-c:a",
                "flac",
                "-sample_fmt",
                "s16" if spec.bit_depth == 16 else "s32",
                "-compression_level",
                str(min(8, quality_index)),
            ]
        elif spec.output_format is AudioOutputFormat.M4A:
            command += ["-c:a", "aac", "-b:a", f"{_BITRATES[spec.output_format][quality_index]}k"]
        else:
            command += [
                "-c:a",
                "libmp3lame",
                "-b:a",
                f"{_BITRATES[spec.output_format][quality_index]}k",
            ]
        command += ["-progress", "pipe:1", "-nostats", str(output_path)]
        return command

    async def _run(
        self,
        command: list[str],
        *,
        duration_seconds: float,
        on_progress: ProgressCallback,
        is_cancelled: CancelCallback,
    ) -> None:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        messages: list[str] = []
        try:
            assert process.stdout is not None
            while True:
                if is_cancelled():
                    process.terminate()
                    with contextlib.suppress(asyncio.TimeoutError):
                        await asyncio.wait_for(process.wait(), timeout=3)
                    if process.returncode is None:
                        process.kill()
                        await process.wait()
                    raise ConversionCancelled
                try:
                    line = await asyncio.wait_for(process.stdout.readline(), timeout=0.2)
                except asyncio.TimeoutError:
                    continue
                if not line:
                    break
                text = line.decode(errors="replace").strip()
                if text.startswith("out_time_us="):
                    with contextlib.suppress(ValueError):
                        seconds = int(text.partition("=")[2]) / 1_000_000
                        on_progress(min(1.0, seconds / max(duration_seconds, 0.001)))
                elif text and not text.startswith(("progress=", "bitrate=", "speed=", "total_size=")):
                    messages.append(text)
                    messages = messages[-12:]
            return_code = await process.wait()
            if return_code != 0:
                raise ConversionError("FFmpeg failed: " + "\n".join(messages)[-1200:])
            on_progress(1.0)
        except asyncio.CancelledError:
            if process.returncode is None:
                process.terminate()
                with contextlib.suppress(Exception):
                    await process.wait()
            raise


class ConversionJobService:
    def __init__(
        self,
        *,
        store: ConversionJobStore,
        source_store: SqliteJobStore,
        source_storage: LocalJobStorage,
        studio_store: SqliteStudioStore,
        output_root: Path,
        input_root: Path,
        converter: AudioConverter | None = None,
    ) -> None:
        self.store = store
        self.source_store = source_store
        self.source_storage = source_storage
        self.studio_store = studio_store
        self.output_root = Path(output_root)
        self.input_root = Path(input_root)
        self.converter = converter or FfmpegAudioConverter()
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None

    @property
    def ffmpeg_available(self) -> bool:
        return self.converter.available

    async def start(self) -> None:
        if self._worker is not None:
            return
        self.store.initialize()
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.input_root.mkdir(parents=True, exist_ok=True)
        for job_id in self.store.requeue_interrupted():
            self._queue.put_nowait(job_id)
        self._worker = asyncio.create_task(self._worker_loop(), name="splicr-conversion-worker")

    async def stop(self) -> None:
        if self._worker is None:
            return
        self._worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._worker
        self._worker = None

    def register_upload(
        self,
        *,
        original_name: str,
        temporary_path: Path,
        media_type: str | None,
    ) -> ConversionInput:
        safe_name = Path(original_name).name or "audio"
        suffix = Path(safe_name).suffix.casefold()
        if suffix not in _UPLOAD_SUFFIXES:
            raise ValueError("unsupported audio file type")
        input_id = uuid.uuid4().hex
        directory = self.input_root / input_id
        directory.mkdir(parents=True, exist_ok=False)
        final_path = directory / f"source{suffix}"
        os.replace(temporary_path, final_path)
        return self.store.save_input(
            ConversionInput(
                id=input_id,
                original_name=safe_name,
                path=str(final_path.resolve()),
                media_type=media_type or mimetypes.guess_type(safe_name)[0] or "application/octet-stream",
                size_bytes=final_path.stat().st_size,
                created_at=utc_now(),
            )
        )

    def list_sources(self) -> list[dict[str, object]]:
        sources: list[dict[str, object]] = []
        for source in self.source_store.list_jobs():
            if source.status is not JobStatus.COMPLETED:
                continue
            path = Path(source.output_path) if source.output_path else self.source_storage.output_path(source.id)
            if path.is_file():
                sources.append(
                    {
                        "kind": "take",
                        "id": source.id,
                        "name": f"{source.provider} · {source.voice} · {source.id[:8]}",
                        "size_bytes": path.stat().st_size,
                        "created_at": source.created_at,
                    }
                )
        for item in self.store.list_inputs():
            if Path(item.path).is_file():
                sources.append(
                    {
                        "kind": "upload",
                        "id": item.id,
                        "name": item.original_name,
                        "size_bytes": item.size_bytes,
                        "created_at": item.created_at,
                    }
                )
        return sorted(sources, key=lambda item: str(item["created_at"]), reverse=True)

    async def submit(
        self,
        spec: ConversionSpec,
        *,
        source_job_id: str | None = None,
        input_id: str | None = None,
    ) -> ConversionJob:
        if not self.ffmpeg_available:
            raise ConversionError(
                "FFmpeg and FFprobe were not found. Install FFmpeg and ensure both commands are on PATH."
            )
        if bool(source_job_id) == bool(input_id):
            raise ValueError("choose exactly one completed take or uploaded audio file")
        project_id: str | None = None
        take_id: str | None = None
        if source_job_id:
            source = self.source_store.get_job(source_job_id)
            if source.status is not JobStatus.COMPLETED:
                raise ValueError("conversion requires a completed narration take")
            source_path = Path(source.output_path) if source.output_path else self.source_storage.output_path(source.id)
            if not source_path.is_file():
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
            uploaded = self.store.get_input(input_id or "")
            source_path = Path(uploaded.path)
            if not source_path.is_file():
                raise FileNotFoundError("the uploaded audio file is missing")
            source_name = uploaded.original_name
        duration = await self.converter.probe_duration(source_path)
        now = utc_now()
        job = self.store.create(
            ConversionJob(
                id=uuid.uuid4().hex,
                source_job_id=source_job_id,
                input_id=input_id,
                source_name=source_name,
                project_id=project_id,
                take_id=take_id,
                status=ConversionJobStatus.QUEUED,
                spec=spec,
                duration_seconds=duration,
                progress=0.0,
                output_path=None,
                part_paths=(),
                artifact_ids=(),
                error_code=None,
                error_detail=None,
                cancel_requested=False,
                created_at=now,
                updated_at=now,
            )
        )
        await self._queue.put(job.id)
        return job

    async def cancel(self, job_id: str) -> ConversionJob:
        return self.store.request_cancel(job_id)

    async def retry(self, job_id: str) -> ConversionJob:
        job = self.store.retry(job_id)
        await self._queue.put(job.id)
        return job

    def output_for(self, job_id: str, part_index: int | None = None) -> Path:
        job = self.store.get(job_id)
        if job.status is not ConversionJobStatus.COMPLETED or not job.output_path:
            raise InvalidConversionJobStateError("conversion output is not ready")
        if part_index is None:
            path = Path(job.output_path)
        else:
            try:
                path = Path(job.part_paths[part_index])
            except IndexError as error:
                raise FileNotFoundError("conversion part not found") from error
        if not path.is_file():
            raise FileNotFoundError("conversion output file is missing")
        return path

    async def _worker_loop(self) -> None:
        while True:
            job_id = await self._queue.get()
            try:
                if self.store.claim(job_id):
                    await self._convert(job_id)
            finally:
                self._queue.task_done()

    async def _convert(self, job_id: str) -> None:
        job = self.store.get(job_id)
        source_path = self._source_path(job)
        directory = self.output_root / job.id
        extension = job.spec.output_format.value
        final_path = directory / f"converted.{extension}"
        temporary_path = directory / f".converted.{uuid.uuid4().hex}.part.{extension}"
        temporary_parts = directory / f".parts-{uuid.uuid4().hex}"
        final_parts = directory / "parts"
        directory.mkdir(parents=True, exist_ok=True)
        final_path.unlink(missing_ok=True)

        def update(fraction: float, *, base: float, span: float) -> None:
            self.store.update_progress(job.id, base + max(0.0, min(1.0, fraction)) * span)

        try:
            convert_span = 0.78 if job.spec.split_mode is not SplitMode.NONE else 1.0
            await self.converter.convert(
                source_path,
                temporary_path,
                job.spec,
                duration_seconds=job.duration_seconds,
                on_progress=lambda value: update(value, base=0, span=convert_span),
                is_cancelled=lambda: self.store.get(job.id).cancel_requested,
            )
            if self.store.get(job.id).cancel_requested:
                raise ConversionCancelled
            if not temporary_path.is_file() or temporary_path.stat().st_size == 0:
                raise ConversionError("FFmpeg completed without producing an audio file")
            os.replace(temporary_path, final_path)
            part_paths: list[Path] = []
            if job.spec.split_mode is not SplitMode.NONE:
                part_paths = await self.converter.split(
                    final_path,
                    temporary_parts,
                    job.spec,
                    duration_seconds=job.duration_seconds,
                    on_progress=lambda value: update(value, base=0.78, span=0.22),
                    is_cancelled=lambda: self.store.get(job.id).cancel_requested,
                )
                if final_parts.exists():
                    shutil.rmtree(final_parts)
                os.replace(temporary_parts, final_parts)
                part_paths = [final_parts / path.name for path in part_paths]
            artifact_ids = self._record_artifacts(job, [final_path, *part_paths])
            self.store.complete(job.id, final_path, part_paths, artifact_ids)
        except ConversionCancelled:
            temporary_path.unlink(missing_ok=True)
            shutil.rmtree(temporary_parts, ignore_errors=True)
            self.store.mark_cancelled(job.id)
        except asyncio.CancelledError:
            temporary_path.unlink(missing_ok=True)
            shutil.rmtree(temporary_parts, ignore_errors=True)
            raise
        except Exception as error:
            temporary_path.unlink(missing_ok=True)
            shutil.rmtree(temporary_parts, ignore_errors=True)
            self.store.fail(job.id, "conversion_failed", str(error))

    def _source_path(self, job: ConversionJob) -> Path:
        if job.source_job_id:
            source = self.source_store.get_job(job.source_job_id)
            return Path(source.output_path) if source.output_path else self.source_storage.output_path(source.id)
        return Path(self.store.get_input(job.input_id or "").path)

    def _record_artifacts(self, job: ConversionJob, paths: list[Path]) -> list[str]:
        if not job.project_id or not job.take_id:
            return []
        artifact_ids: list[str] = []
        for path in paths:
            artifact_id = uuid.uuid4().hex
            self.studio_store.add_artifact(
                Artifact(
                    id=artifact_id,
                    project_id=job.project_id,
                    take_id=job.take_id,
                    kind=ArtifactKind.AUDIO,
                    path=str(path.resolve()),
                    media_type=_MEDIA_TYPES[job.spec.output_format],
                    size_bytes=path.stat().st_size,
                    sha256=self._sha256(path),
                )
            )
            artifact_ids.append(artifact_id)
        return artifact_ids

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()


def media_type_for(output_format: AudioOutputFormat) -> str:
    return _MEDIA_TYPES[output_format]
