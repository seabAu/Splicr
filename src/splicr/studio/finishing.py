from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import math
import os
import shutil
import sqlite3
import subprocess
import threading
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from ..artifacts import sanitize_export_stem
from ..domain import JobStatus, JsonValue, utc_now
from ..storage import LocalJobStorage
from ..store import SqliteJobStore
from .domain import Artifact, ArtifactKind
from .migration import import_splicr_job
from .store import SqliteStudioStore
from .subtitles import SubtitleFormat, SubtitleService


_UPLOAD_SUFFIXES = {".aac", ".flac", ".m4a", ".mp3", ".ogg", ".opus", ".wav", ".webm"}


class FinishingJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCEL_REQUESTED = "cancel_requested"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class FinishingAsset:
    id: str
    name: str
    path: str
    media_type: str
    size_bytes: int
    sha256: str
    duration_seconds: float
    created_at: str


@dataclass(frozen=True, slots=True)
class FinishingSpec:
    intro_asset_id: str | None = None
    outro_asset_id: str | None = None
    crossfade_seconds: float = 1.0
    normalize_loudness: bool = False

    def __post_init__(self) -> None:
        if not self.intro_asset_id and not self.outro_asset_id:
            raise ValueError("select an intro, an outro, or both")
        if not math.isfinite(self.crossfade_seconds) or not 0 <= self.crossfade_seconds <= 30:
            raise ValueError("crossfade_seconds must be between 0 and 30")

    def to_mapping(self) -> dict[str, JsonValue]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, value: dict[str, object]) -> FinishingSpec:
        return cls(
            intro_asset_id=_optional_string(value.get("intro_asset_id")),
            outro_asset_id=_optional_string(value.get("outro_asset_id")),
            crossfade_seconds=_float_value(value.get("crossfade_seconds"), default=1.0),
            normalize_loudness=bool(value.get("normalize_loudness", False)),
        )


@dataclass(frozen=True, slots=True)
class FinishingJob:
    id: str
    source_job_id: str
    project_id: str
    take_id: str
    status: FinishingJobStatus
    spec: FinishingSpec
    intro_offset: float
    intro_crossfade: float
    outro_crossfade: float
    source_duration: float
    output_duration: float
    progress: float
    output_path: str | None
    artifact_id: str | None
    subtitle_artifact_ids: tuple[str, ...]
    error_code: str | None
    error_detail: str | None
    error_context: dict[str, JsonValue]
    cancel_requested: bool
    created_at: str
    updated_at: str


class FinishingJobNotFoundError(KeyError):
    pass


class FinishingAssetNotFoundError(KeyError):
    pass


class InvalidFinishingJobStateError(ValueError):
    pass


class FinishingError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        context: dict[str, JsonValue] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.context = context or {}


class FinishingCancelled(Exception):
    pass


class FinishingStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path)
        self._lock = threading.RLock()

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS studio_finishing_assets (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    path TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL CHECK (size_bytes > 0),
                    sha256 TEXT NOT NULL,
                    duration_seconds REAL NOT NULL CHECK (duration_seconds > 0),
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS studio_finishing_jobs (
                    id TEXT PRIMARY KEY,
                    source_job_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    take_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    spec_json TEXT NOT NULL,
                    intro_offset REAL NOT NULL,
                    intro_crossfade REAL NOT NULL,
                    outro_crossfade REAL NOT NULL,
                    source_duration REAL NOT NULL,
                    output_duration REAL NOT NULL,
                    progress REAL NOT NULL DEFAULT 0,
                    output_path TEXT,
                    artifact_id TEXT,
                    subtitle_artifact_ids_json TEXT NOT NULL DEFAULT '[]',
                    error_code TEXT,
                    error_detail TEXT,
                    error_context_json TEXT NOT NULL DEFAULT '{}',
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS studio_finishing_jobs_source_idx
                    ON studio_finishing_jobs(source_job_id, created_at DESC);
                """
            )

    def save_asset(self, asset: FinishingAsset) -> FinishingAsset:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO studio_finishing_assets (
                    id, name, path, media_type, size_bytes, sha256,
                    duration_seconds, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO NOTHING
                """,
                (
                    asset.id,
                    asset.name,
                    asset.path,
                    asset.media_type,
                    asset.size_bytes,
                    asset.sha256,
                    asset.duration_seconds,
                    asset.created_at,
                ),
            )
        return self.get_asset(asset.id)

    def get_asset(self, asset_id: str) -> FinishingAsset:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM studio_finishing_assets WHERE id = ?", (asset_id,)
            ).fetchone()
        if row is None:
            raise FinishingAssetNotFoundError(asset_id)
        return self._asset_from_row(row)

    def list_assets(self) -> list[FinishingAsset]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM studio_finishing_assets ORDER BY created_at DESC, id"
            ).fetchall()
        return [self._asset_from_row(row) for row in rows]

    def create_job(self, job: FinishingJob) -> FinishingJob:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO studio_finishing_jobs (
                    id, source_job_id, project_id, take_id, status, spec_json,
                    intro_offset, intro_crossfade, outro_crossfade, source_duration,
                    output_duration, progress, output_path, artifact_id,
                    subtitle_artifact_ids_json, error_code, error_detail,
                    error_context_json, cancel_requested, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._values(job),
            )
        return self.get_job(job.id)

    def get_job(self, job_id: str) -> FinishingJob:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM studio_finishing_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        if row is None:
            raise FinishingJobNotFoundError(job_id)
        return self._job_from_row(row)

    def list_jobs(self, *, limit: int = 100) -> list[FinishingJob]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM studio_finishing_jobs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._job_from_row(row) for row in rows]

    def requeue_interrupted(self) -> list[str]:
        now = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE studio_finishing_jobs
                SET status = ?, progress = 0, updated_at = ?
                WHERE status = ? AND cancel_requested = 0
                """,
                (FinishingJobStatus.QUEUED, now, FinishingJobStatus.RUNNING),
            )
            connection.execute(
                """
                UPDATE studio_finishing_jobs SET status = ?, updated_at = ?
                WHERE status IN (?, ?) AND cancel_requested = 1
                """,
                (
                    FinishingJobStatus.CANCELLED,
                    now,
                    FinishingJobStatus.RUNNING,
                    FinishingJobStatus.CANCEL_REQUESTED,
                ),
            )
            rows = connection.execute(
                "SELECT id FROM studio_finishing_jobs WHERE status = ? ORDER BY created_at",
                (FinishingJobStatus.QUEUED,),
            ).fetchall()
        return [str(row["id"]) for row in rows]

    def claim(self, job_id: str) -> bool:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE studio_finishing_jobs
                SET status = ?, progress = 0, updated_at = ?
                WHERE id = ? AND status = ? AND cancel_requested = 0
                """,
                (
                    FinishingJobStatus.RUNNING,
                    utc_now(),
                    job_id,
                    FinishingJobStatus.QUEUED,
                ),
            )
        return cursor.rowcount == 1

    def update_progress(self, job_id: str, progress: float) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE studio_finishing_jobs SET progress = ?, updated_at = ?
                WHERE id = ? AND status IN (?, ?)
                """,
                (
                    max(0.0, min(1.0, progress)),
                    utc_now(),
                    job_id,
                    FinishingJobStatus.RUNNING,
                    FinishingJobStatus.CANCEL_REQUESTED,
                ),
            )

    def complete(
        self,
        job_id: str,
        output_path: Path,
        artifact_id: str,
        subtitle_artifact_ids: tuple[str, ...],
    ) -> FinishingJob:
        return self._transition(
            job_id,
            FinishingJobStatus.COMPLETED,
            progress=1.0,
            output_path=str(output_path.resolve()),
            artifact_id=artifact_id,
            subtitle_artifact_ids_json=json.dumps(subtitle_artifact_ids),
            error_code=None,
            error_detail=None,
            error_context_json="{}",
            cancel_requested=0,
        )

    def fail(self, job_id: str, error: FinishingError) -> FinishingJob:
        return self._transition(
            job_id,
            FinishingJobStatus.FAILED,
            error_code=error.code,
            error_detail=error.message,
            error_context_json=json.dumps(error.context, sort_keys=True),
        )

    def request_cancel(self, job_id: str) -> FinishingJob:
        job = self.get_job(job_id)
        if job.status is FinishingJobStatus.QUEUED:
            return self._transition(
                job_id, FinishingJobStatus.CANCELLED, cancel_requested=1
            )
        if job.status in {
            FinishingJobStatus.RUNNING,
            FinishingJobStatus.CANCEL_REQUESTED,
        }:
            return self._transition(
                job_id, FinishingJobStatus.CANCEL_REQUESTED, cancel_requested=1
            )
        raise InvalidFinishingJobStateError("only queued or running finishing jobs can cancel")

    def mark_cancelled(self, job_id: str) -> FinishingJob:
        return self._transition(
            job_id, FinishingJobStatus.CANCELLED, cancel_requested=1
        )

    def retry(self, job_id: str) -> FinishingJob:
        job = self.get_job(job_id)
        if job.status not in {FinishingJobStatus.FAILED, FinishingJobStatus.CANCELLED}:
            raise InvalidFinishingJobStateError("only failed or cancelled finishing jobs can retry")
        return self._transition(
            job_id,
            FinishingJobStatus.QUEUED,
            progress=0.0,
            output_path=None,
            artifact_id=None,
            subtitle_artifact_ids_json="[]",
            error_code=None,
            error_detail=None,
            error_context_json="{}",
            cancel_requested=0,
        )

    def _transition(
        self, job_id: str, status: FinishingJobStatus, **values: object
    ) -> FinishingJob:
        assignments = ["status = ?", "updated_at = ?"]
        parameters: list[object] = [status.value, utc_now()]
        for key, value in values.items():
            assignments.append(f"{key} = ?")
            parameters.append(value)
        parameters.append(job_id)
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                f"UPDATE studio_finishing_jobs SET {', '.join(assignments)} WHERE id = ?",  # noqa: S608
                parameters,
            )
        if cursor.rowcount != 1:
            raise FinishingJobNotFoundError(job_id)
        return self.get_job(job_id)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _values(job: FinishingJob) -> tuple[object, ...]:
        return (
            job.id,
            job.source_job_id,
            job.project_id,
            job.take_id,
            job.status.value,
            json.dumps(job.spec.to_mapping(), sort_keys=True),
            job.intro_offset,
            job.intro_crossfade,
            job.outro_crossfade,
            job.source_duration,
            job.output_duration,
            job.progress,
            job.output_path,
            job.artifact_id,
            json.dumps(job.subtitle_artifact_ids),
            job.error_code,
            job.error_detail,
            json.dumps(job.error_context, sort_keys=True),
            int(job.cancel_requested),
            job.created_at,
            job.updated_at,
        )

    @staticmethod
    def _asset_from_row(row: sqlite3.Row) -> FinishingAsset:
        return FinishingAsset(
            id=row["id"],
            name=row["name"],
            path=row["path"],
            media_type=row["media_type"],
            size_bytes=row["size_bytes"],
            sha256=row["sha256"],
            duration_seconds=row["duration_seconds"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _job_from_row(row: sqlite3.Row) -> FinishingJob:
        return FinishingJob(
            id=row["id"],
            source_job_id=row["source_job_id"],
            project_id=row["project_id"],
            take_id=row["take_id"],
            status=FinishingJobStatus(row["status"]),
            spec=FinishingSpec.from_mapping(json.loads(row["spec_json"])),
            intro_offset=row["intro_offset"],
            intro_crossfade=row["intro_crossfade"],
            outro_crossfade=row["outro_crossfade"],
            source_duration=row["source_duration"],
            output_duration=row["output_duration"],
            progress=row["progress"],
            output_path=row["output_path"],
            artifact_id=row["artifact_id"],
            subtitle_artifact_ids=tuple(json.loads(row["subtitle_artifact_ids_json"])),
            error_code=row["error_code"],
            error_detail=row["error_detail"],
            error_context=dict(json.loads(row["error_context_json"])),
            cancel_requested=bool(row["cancel_requested"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


ProgressCallback = Callable[[float], None]
CancelCallback = Callable[[], bool]


class FinishingRenderer(Protocol):
    @property
    def available(self) -> bool: ...

    def probe_duration(self, path: Path) -> float: ...

    async def render(
        self,
        parts: tuple[Path, ...],
        joins: tuple[float, ...],
        output_path: Path,
        *,
        duration_seconds: float,
        normalize_loudness: bool,
        on_progress: ProgressCallback,
        is_cancelled: CancelCallback,
    ) -> None: ...


class FfmpegFinishingRenderer:
    def __init__(self, executable: str | None = None, ffprobe: str | None = None) -> None:
        self.executable = executable or shutil.which("ffmpeg") or "ffmpeg"
        self.ffprobe = ffprobe or shutil.which("ffprobe") or "ffprobe"

    @property
    def available(self) -> bool:
        return shutil.which(self.executable) is not None and shutil.which(self.ffprobe) is not None

    def probe_duration(self, path: Path) -> float:
        try:
            result = subprocess.run(
                [
                    self.ffprobe,
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    str(path),
                ],
                check=True,
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            duration = float(result.stdout.strip())
        except (OSError, subprocess.CalledProcessError, ValueError) as error:
            raise FinishingError(
                "asset_unreadable",
                f"FFmpeg could not read audio asset {path.name}",
                context={"path": str(path), "detail": str(error)},
            ) from error
        if not math.isfinite(duration) or duration <= 0:
            raise FinishingError(
                "asset_unreadable",
                f"Audio asset {path.name} has no positive duration",
                context={"path": str(path)},
            )
        return duration

    async def render(
        self,
        parts: tuple[Path, ...],
        joins: tuple[float, ...],
        output_path: Path,
        *,
        duration_seconds: float,
        normalize_loudness: bool,
        on_progress: ProgressCallback,
        is_cancelled: CancelCallback,
    ) -> None:
        if not self.available:
            raise FinishingError("ffmpeg_unavailable", "FFmpeg and FFprobe are required")
        command = build_finishing_command(
            self.executable,
            parts,
            joins,
            output_path,
            normalize_loudness=normalize_loudness,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if process.stdout is None or process.stderr is None:
            process.kill()
            raise FinishingError("ffmpeg_failed", "FFmpeg did not expose progress streams")
        stderr_task = asyncio.create_task(process.stderr.read())
        try:
            while process.returncode is None:
                if is_cancelled():
                    process.terminate()
                    with contextlib.suppress(asyncio.TimeoutError):
                        await asyncio.wait_for(process.wait(), timeout=3)
                    if process.returncode is None:
                        process.kill()
                        await process.wait()
                    raise FinishingCancelled
                try:
                    line = await asyncio.wait_for(process.stdout.readline(), timeout=0.25)
                except asyncio.TimeoutError:
                    continue
                if not line:
                    await process.wait()
                    break
                key, _, raw = line.decode(errors="replace").strip().partition("=")
                if key in {"out_time_us", "out_time_ms"}:
                    with contextlib.suppress(ValueError):
                        on_progress(min(0.995, int(raw) / 1_000_000 / duration_seconds))
            stderr = (await stderr_task).decode(errors="replace").strip()
            if process.returncode:
                raise FinishingError(
                    "ffmpeg_failed",
                    "FFmpeg could not assemble the finishing plan",
                    context={"stderr": stderr[-8_000:], "returncode": process.returncode},
                )
            on_progress(1.0)
        except (asyncio.CancelledError, FinishingCancelled):
            if process.returncode is None:
                process.terminate()
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(process.wait(), timeout=3)
                if process.returncode is None:
                    process.kill()
            stderr_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await stderr_task
            raise


def build_finishing_command(
    executable: str,
    parts: tuple[Path, ...],
    joins: tuple[float, ...],
    output_path: Path,
    *,
    normalize_loudness: bool = False,
) -> list[str]:
    if len(parts) < 2 or len(joins) != len(parts) - 1:
        raise ValueError("finishing command requires one join per adjacent audio pair")
    command = [executable, "-y", "-hide_banner", "-loglevel", "error"]
    for part in parts:
        command.extend(("-i", str(part)))
    filters: list[str] = []
    for index in range(len(parts)):
        effects = "aformat=sample_fmts=s16:sample_rates=24000:channel_layouts=mono"
        if normalize_loudness:
            effects += ",loudnorm=I=-16:TP=-1.5:LRA=11"
        filters.append(f"[{index}:a]{effects}[p{index}]")
    previous = "[p0]"
    for index, fade in enumerate(joins, start=1):
        output = "[out]" if index == len(parts) - 1 else f"[m{index}]"
        if fade > 0:
            filters.append(
                f"{previous}[p{index}]acrossfade=d={fade:.6f}:c1=tri:c2=tri{output}"
            )
        else:
            filters.append(f"{previous}[p{index}]concat=n=2:v=0:a=1{output}")
        previous = output
    command.extend(
        (
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[out]",
            "-c:a",
            "pcm_s16le",
            "-ar",
            "24000",
            "-ac",
            "1",
            "-progress",
            "pipe:1",
            "-nostats",
            str(output_path),
        )
    )
    return command


class FinishingJobService:
    def __init__(
        self,
        *,
        store: FinishingStore,
        source_store: SqliteJobStore,
        source_storage: LocalJobStorage,
        studio_store: SqliteStudioStore,
        subtitle_service: SubtitleService,
        asset_root: Path,
        output_root: Path,
        renderer: FinishingRenderer | None = None,
        max_upload_bytes: int = 250_000_000,
    ) -> None:
        self.store = store
        self.source_store = source_store
        self.source_storage = source_storage
        self.studio_store = studio_store
        self.subtitle_service = subtitle_service
        self.asset_root = Path(asset_root)
        self.output_root = Path(output_root)
        self.renderer = renderer or FfmpegFinishingRenderer()
        self.max_upload_bytes = max_upload_bytes
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None

    @property
    def ffmpeg_available(self) -> bool:
        return self.renderer.available

    async def start(self) -> None:
        self.store.initialize()
        for job_id in self.store.requeue_interrupted():
            await self._queue.put(job_id)
        if self._worker is None:
            self._worker = asyncio.create_task(self._worker_loop())

    async def stop(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker
            self._worker = None

    def register_upload(self, name: str, media_type: str, payload: bytes) -> FinishingAsset:
        if not payload:
            raise FinishingError("asset_empty", "The uploaded audio asset is empty")
        if len(payload) > self.max_upload_bytes:
            raise FinishingError(
                "asset_too_large",
                f"Audio asset exceeds the {self.max_upload_bytes} byte limit",
            )
        suffix = Path(name).suffix.casefold()
        if suffix not in _UPLOAD_SUFFIXES:
            raise FinishingError(
                "asset_type_unsupported",
                f"Unsupported audio asset type: {suffix or 'no extension'}",
            )
        digest = hashlib.sha256(payload).hexdigest()
        asset_id = f"finishing-{digest[:24]}"
        with contextlib.suppress(FinishingAssetNotFoundError):
            existing = self.store.get_asset(asset_id)
            if Path(existing.path).is_file():
                return existing
        stem = sanitize_export_stem(Path(name).stem, fallback="audio-asset")
        path = self.asset_root / f"{asset_id}-{stem}{suffix}"
        _atomic_write(path, payload)
        try:
            duration = self.renderer.probe_duration(path)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return self.store.save_asset(
            FinishingAsset(
                id=asset_id,
                name=Path(name).name,
                path=str(path.resolve()),
                media_type=media_type or "application/octet-stream",
                size_bytes=len(payload),
                sha256=digest,
                duration_seconds=duration,
                created_at=utc_now(),
            )
        )

    async def submit(self, source_job_id: str, spec: FinishingSpec) -> FinishingJob:
        if not self.ffmpeg_available:
            raise FinishingError("ffmpeg_unavailable", "FFmpeg and FFprobe are required")
        source = self.source_store.get_job(source_job_id)
        if source.status is not JobStatus.COMPLETED:
            raise ValueError("finishing requires a completed narration take")
        source_path = (
            Path(source.output_path)
            if source.output_path
            else self.source_storage.output_path(source.id)
        )
        if not source_path.is_file():
            raise FinishingError(
                "source_missing",
                "The completed narration audio is missing",
                context={"source_job_id": source.id},
            )
        intro = self._asset(spec.intro_asset_id, role="intro")
        outro = self._asset(spec.outro_asset_id, role="outro")
        source_duration = self.renderer.probe_duration(source_path)
        intro_fade = _clamped_crossfade(
            spec.crossfade_seconds,
            intro.duration_seconds if intro else None,
            source_duration,
        )
        outro_fade = _clamped_crossfade(
            spec.crossfade_seconds,
            source_duration,
            outro.duration_seconds if outro else None,
        )
        intro_offset = max(0.0, (intro.duration_seconds if intro else 0.0) - intro_fade)
        output_duration = (
            source_duration
            + (intro.duration_seconds if intro else 0.0)
            + (outro.duration_seconds if outro else 0.0)
            - intro_fade
            - outro_fade
        )
        imported = import_splicr_job(
            job_id=source_job_id,
            job_store=self.source_store,
            job_storage=self.source_storage,
            studio_store=self.studio_store,
        )
        if imported.take_id is None:
            raise ValueError("the source take has no render plan")
        now = utc_now()
        job = self.store.create_job(
            FinishingJob(
                id=uuid.uuid4().hex,
                source_job_id=source.id,
                project_id=imported.project_id,
                take_id=imported.take_id,
                status=FinishingJobStatus.QUEUED,
                spec=spec,
                intro_offset=intro_offset,
                intro_crossfade=intro_fade,
                outro_crossfade=outro_fade,
                source_duration=source_duration,
                output_duration=output_duration,
                progress=0.0,
                output_path=None,
                artifact_id=None,
                subtitle_artifact_ids=(),
                error_code=None,
                error_detail=None,
                error_context={},
                cancel_requested=False,
                created_at=now,
                updated_at=now,
            )
        )
        await self._queue.put(job.id)
        return job

    async def cancel(self, job_id: str) -> FinishingJob:
        return self.store.request_cancel(job_id)

    async def retry(self, job_id: str) -> FinishingJob:
        job = self.store.retry(job_id)
        await self._queue.put(job.id)
        return job

    def output_for(self, job_id: str) -> Path:
        job = self.store.get_job(job_id)
        if job.status is not FinishingJobStatus.COMPLETED or not job.output_path:
            raise InvalidFinishingJobStateError("finishing output is not complete")
        path = Path(job.output_path)
        if not path.is_file():
            raise FileNotFoundError("finished audio artifact is missing")
        return path

    async def _worker_loop(self) -> None:
        while True:
            job_id = await self._queue.get()
            try:
                if self.store.claim(job_id):
                    try:
                        await self._render(job_id)
                    except asyncio.CancelledError:
                        raise
                    except FinishingError as error:
                        self.store.fail(job_id, error)
                    except Exception as error:
                        self.store.fail(
                            job_id,
                            FinishingError(
                                "internal_error",
                                str(error),
                                context={"type": type(error).__name__},
                            ),
                        )
            finally:
                self._queue.task_done()

    async def _render(self, job_id: str) -> None:
        job = self.store.get_job(job_id)
        source = self.source_store.get_job(job.source_job_id)
        source_path = (
            Path(source.output_path)
            if source.output_path
            else self.source_storage.output_path(source.id)
        )
        intro = self._asset(job.spec.intro_asset_id, role="intro")
        outro = self._asset(job.spec.outro_asset_id, role="outro")
        parts = tuple(
            path
            for path in (
                Path(intro.path) if intro else None,
                source_path,
                Path(outro.path) if outro else None,
            )
            if path is not None
        )
        joins = tuple(
            fade
            for fade, present in (
                (job.intro_crossfade, intro is not None),
                (job.outro_crossfade, outro is not None),
            )
            if present
        )
        directory = self.output_root / job.id
        final_path = directory / "finished.wav"
        temporary_path = directory / f".finished.{uuid.uuid4().hex}.part.wav"
        final_path.unlink(missing_ok=True)
        last_reported = -1.0

        def on_progress(progress: float) -> None:
            nonlocal last_reported
            if progress >= 1 or progress - last_reported >= 0.0025:
                self.store.update_progress(job.id, progress)
                last_reported = progress

        try:
            for role, asset in (("intro", intro), ("outro", outro)):
                if asset is not None and not Path(asset.path).is_file():
                    raise FinishingError(
                        "asset_missing",
                        f"The selected {role} asset is missing",
                        context={"role": role, "asset_id": asset.id, "path": asset.path},
                    )
            await self.renderer.render(
                parts,
                joins,
                temporary_path,
                duration_seconds=job.output_duration,
                normalize_loudness=job.spec.normalize_loudness,
                on_progress=on_progress,
                is_cancelled=lambda: self.store.get_job(job.id).cancel_requested,
            )
            if self.store.get_job(job.id).cancel_requested:
                raise FinishingCancelled
            if not temporary_path.is_file() or temporary_path.stat().st_size == 0:
                raise FinishingError(
                    "atomic_output_missing", "FFmpeg completed without a finished audio file"
                )
            digest = _sha256(temporary_path)
            plan_metadata: dict[str, JsonValue] = {
                "source_job_id": job.source_job_id,
                "source_audio_path": str(source_path.resolve()),
                "intro_asset_id": intro.id if intro else None,
                "intro_asset_sha256": intro.sha256 if intro else None,
                "outro_asset_id": outro.id if outro else None,
                "outro_asset_sha256": outro.sha256 if outro else None,
                "requested_crossfade": job.spec.crossfade_seconds,
                "intro_crossfade": job.intro_crossfade,
                "outro_crossfade": job.outro_crossfade,
                "intro_offset": job.intro_offset,
                "source_duration": job.source_duration,
                "output_duration": job.output_duration,
                "normalize_loudness": job.spec.normalize_loudness,
                "finishing_job_id": job.id,
            }
            plan_digest = hashlib.sha256(
                json.dumps(plan_metadata, sort_keys=True).encode()
            ).hexdigest()[:10]
            artifact_id = f"finished-audio-{job.take_id}-{digest[:12]}-{plan_digest}"
            artifact = Artifact(
                id=artifact_id,
                project_id=job.project_id,
                take_id=job.take_id,
                kind=ArtifactKind.AUDIO,
                path=str(final_path.resolve()),
                media_type="audio/wav",
                size_bytes=temporary_path.stat().st_size,
                sha256=digest,
                metadata=plan_metadata,
            )
            subtitle_ids = tuple(
                self.subtitle_service.export(
                    job.source_job_id,
                    output_format,
                    offset_seconds=job.intro_offset,
                    source_audio_artifact_id=artifact.id,
                ).artifact.id
                for output_format in (SubtitleFormat.SRT, SubtitleFormat.WEBVTT)
            )
            final_path.parent.mkdir(parents=True, exist_ok=True)
            os.replace(temporary_path, final_path)
            try:
                stored = self.studio_store.add_artifact(artifact)
            except sqlite3.IntegrityError:
                stored = self.studio_store.get_artifact(artifact_id)
            self.store.complete(job.id, final_path, stored.id, subtitle_ids)
        except FinishingCancelled:
            temporary_path.unlink(missing_ok=True)
            self.store.mark_cancelled(job.id)
        except asyncio.CancelledError:
            temporary_path.unlink(missing_ok=True)
            raise
        except FinishingError as error:
            temporary_path.unlink(missing_ok=True)
            self.store.fail(job.id, error)
        except Exception as error:
            temporary_path.unlink(missing_ok=True)
            self.store.fail(
                job.id,
                FinishingError("internal_error", str(error), context={"type": type(error).__name__}),
            )

    def _asset(self, asset_id: str | None, *, role: str) -> FinishingAsset | None:
        if asset_id is None:
            return None
        try:
            return self.store.get_asset(asset_id)
        except FinishingAssetNotFoundError as error:
            raise FinishingError(
                "asset_not_found",
                f"The selected {role} asset no longer exists",
                context={"role": role, "asset_id": asset_id},
            ) from error


def _clamped_crossfade(
    requested: float, left_duration: float | None, right_duration: float | None
) -> float:
    if requested <= 0 or left_duration is None or right_duration is None:
        return 0.0
    shortest = min(left_duration, right_duration)
    return requested if requested < shortest else max(0.0, shortest / 2)


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _float_value(value: object, *, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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
