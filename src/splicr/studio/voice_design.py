from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
import subprocess
import threading
import wave
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from ..domain import utc_now
from .domain import VoiceProfile, VoiceProfileKind
from .store import SqliteStudioStore


QWEN_DESIGN_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"
QWEN_REFERENCE_TEXT = (
    "This is a short reference recording. It is made once, from a written "
    "description, so that every chapter that follows can be read in this "
    "same voice, at this same steady pace."
)


class VoiceDesignJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class VoiceDesignJob:
    id: str
    label: str
    description: str
    take: int
    design_key: str
    status: VoiceDesignJobStatus
    progress: float
    profile_id: str | None
    output_path: str | None
    reference_text: str
    error_code: str | None
    error_detail: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class VoiceDesignResult:
    output_path: str
    reference_text: str
    model: str
    seed: int
    sample_rate: int
    seconds: float

    @classmethod
    def from_mapping(cls, value: dict[str, object]) -> VoiceDesignResult:
        return cls(
            output_path=str(value["output_path"]),
            reference_text=str(value["reference_text"]),
            model=str(value["model"]),
            seed=int(value["seed"]),
            sample_rate=int(value["sample_rate"]),
            seconds=float(value["seconds"]),
        )


class VoiceDesignRunner(Protocol):
    async def design(
        self,
        *,
        description: str,
        take: int,
        output_path: Path,
        result_path: Path,
        should_cancel: Callable[[], bool],
    ) -> VoiceDesignResult: ...


class VoiceDesignJobNotFoundError(LookupError):
    pass


class InvalidVoiceDesignJobStateError(RuntimeError):
    pass


class VoiceDesignUnavailableError(RuntimeError):
    pass


class VoiceDesignCancelled(RuntimeError):
    pass


def design_key(description: str, take: int) -> str:
    normalized = " ".join(description.split()).casefold()
    return hashlib.sha256(f"qwen-voice-design-v1\0{normalized}\0{take}".encode()).hexdigest()


class VoiceDesignJobStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path)
        self._lock = threading.RLock()

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS studio_voice_design_jobs (
                    id TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    description TEXT NOT NULL,
                    take INTEGER NOT NULL,
                    design_key TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    progress REAL NOT NULL DEFAULT 0,
                    profile_id TEXT,
                    output_path TEXT,
                    reference_text TEXT NOT NULL,
                    error_code TEXT,
                    error_detail TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_studio_voice_design_jobs_created
                    ON studio_voice_design_jobs(created_at DESC);
                """
            )

    def create_or_get(self, *, label: str, description: str, take: int) -> VoiceDesignJob:
        key = design_key(description, take)
        with self._lock, self._connect() as connection:
            existing = connection.execute(
                "SELECT * FROM studio_voice_design_jobs WHERE design_key = ?", (key,)
            ).fetchone()
            if existing is not None:
                return self._from_row(existing)
            now = utc_now()
            job_id = uuid4().hex
            connection.execute(
                """
                INSERT INTO studio_voice_design_jobs (
                    id, label, description, take, design_key, status, progress,
                    profile_id, output_path, reference_text, error_code, error_detail,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 0, NULL, NULL, ?, NULL, NULL, ?, ?)
                """,
                (
                    job_id,
                    label.strip(),
                    " ".join(description.split()),
                    take,
                    key,
                    VoiceDesignJobStatus.QUEUED.value,
                    QWEN_REFERENCE_TEXT,
                    now,
                    now,
                ),
            )
        return self.get(job_id)

    def get(self, job_id: str) -> VoiceDesignJob:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM studio_voice_design_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        if row is None:
            raise VoiceDesignJobNotFoundError(job_id)
        return self._from_row(row)

    def list(self, limit: int = 100) -> list[VoiceDesignJob]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM studio_voice_design_jobs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def requeue_interrupted(self) -> list[str]:
        now = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE studio_voice_design_jobs
                SET status = ?, updated_at = ?
                WHERE status = ?
                """,
                (
                    VoiceDesignJobStatus.CANCELLED.value,
                    now,
                    VoiceDesignJobStatus.CANCEL_REQUESTED.value,
                ),
            )
            connection.execute(
                """
                UPDATE studio_voice_design_jobs
                SET status = ?, progress = 0, error_code = NULL, error_detail = NULL,
                    updated_at = ?
                WHERE status = ?
                """,
                (
                    VoiceDesignJobStatus.QUEUED.value,
                    now,
                    VoiceDesignJobStatus.RUNNING.value,
                ),
            )
            rows = connection.execute(
                "SELECT id FROM studio_voice_design_jobs WHERE status = ? ORDER BY created_at",
                (VoiceDesignJobStatus.QUEUED.value,),
            ).fetchall()
        return [str(row["id"]) for row in rows]

    def claim(self, job_id: str) -> bool:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE studio_voice_design_jobs
                SET status = ?, progress = 0.1, error_code = NULL, error_detail = NULL,
                    updated_at = ?
                WHERE id = ? AND status = ?
                """,
                (
                    VoiceDesignJobStatus.RUNNING.value,
                    utc_now(),
                    job_id,
                    VoiceDesignJobStatus.QUEUED.value,
                ),
            )
        return cursor.rowcount == 1

    def complete(self, job_id: str, profile: VoiceProfile) -> VoiceDesignJob:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE studio_voice_design_jobs
                SET status = ?, progress = 1, profile_id = ?, output_path = ?,
                    error_code = NULL, error_detail = NULL, updated_at = ?
                WHERE id = ? AND status = ?
                """,
                (
                    VoiceDesignJobStatus.COMPLETED.value,
                    profile.id,
                    profile.reference_audio_path,
                    utc_now(),
                    job_id,
                    VoiceDesignJobStatus.RUNNING.value,
                ),
            )
        if cursor.rowcount != 1:
            job = self.get(job_id)
            if job.status is VoiceDesignJobStatus.CANCEL_REQUESTED:
                raise VoiceDesignCancelled("voice design was cancelled")
            raise InvalidVoiceDesignJobStateError(
                f"cannot complete a {job.status.value} job"
            )
        return self.get(job_id)

    def fail(self, job_id: str, code: str, detail: str) -> VoiceDesignJob:
        self._update(
            job_id,
            status=VoiceDesignJobStatus.FAILED.value,
            error_code=code,
            error_detail=detail,
        )
        return self.get(job_id)

    def retry(self, job_id: str) -> VoiceDesignJob:
        job = self.get(job_id)
        if job.status not in {
            VoiceDesignJobStatus.FAILED,
            VoiceDesignJobStatus.CANCELLED,
        }:
            raise InvalidVoiceDesignJobStateError(f"cannot retry a {job.status.value} job")
        self._update(
            job_id,
            status=VoiceDesignJobStatus.QUEUED.value,
            progress=0.0,
            error_code=None,
            error_detail=None,
        )
        return self.get(job_id)

    def request_cancel(self, job_id: str) -> VoiceDesignJob:
        while True:
            job = self.get(job_id)
            if job.status in {
                VoiceDesignJobStatus.CANCEL_REQUESTED,
                VoiceDesignJobStatus.CANCELLED,
            }:
                return job
            if job.status is VoiceDesignJobStatus.QUEUED:
                target = VoiceDesignJobStatus.CANCELLED
            elif job.status is VoiceDesignJobStatus.RUNNING:
                target = VoiceDesignJobStatus.CANCEL_REQUESTED
            else:
                raise InvalidVoiceDesignJobStateError(
                    f"cannot cancel a {job.status.value} job"
                )
            with self._lock, self._connect() as connection:
                cursor = connection.execute(
                    """
                    UPDATE studio_voice_design_jobs
                    SET status = ?, updated_at = ?
                    WHERE id = ? AND status = ?
                    """,
                    (target.value, utc_now(), job_id, job.status.value),
                )
            if cursor.rowcount == 1:
                return self.get(job_id)

    def cancel_requested(self, job_id: str) -> bool:
        return self.get(job_id).status is VoiceDesignJobStatus.CANCEL_REQUESTED

    def mark_cancelled(self, job_id: str) -> VoiceDesignJob:
        self._update(job_id, status=VoiceDesignJobStatus.CANCELLED.value)
        return self.get(job_id)

    def restart_completed(self, job_id: str) -> VoiceDesignJob:
        job = self.get(job_id)
        if job.status is not VoiceDesignJobStatus.COMPLETED:
            return job
        self._update(
            job_id,
            status=VoiceDesignJobStatus.QUEUED.value,
            progress=0.0,
            profile_id=None,
            output_path=None,
            error_code=None,
            error_detail=None,
        )
        return self.get(job_id)

    def _update(self, job_id: str, **values: object) -> None:
        assignments = ["updated_at = ?"]
        parameters: list[object] = [utc_now()]
        for key, value in values.items():
            assignments.append(f"{key} = ?")
            parameters.append(value)
        parameters.append(job_id)
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                f"UPDATE studio_voice_design_jobs SET {', '.join(assignments)} WHERE id = ?",
                parameters,
            )
        if cursor.rowcount != 1:
            raise VoiceDesignJobNotFoundError(job_id)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    @staticmethod
    def _from_row(row: sqlite3.Row) -> VoiceDesignJob:
        return VoiceDesignJob(
            id=row["id"],
            label=row["label"],
            description=row["description"],
            take=row["take"],
            design_key=row["design_key"],
            status=VoiceDesignJobStatus(row["status"]),
            progress=row["progress"],
            profile_id=row["profile_id"],
            output_path=row["output_path"],
            reference_text=row["reference_text"],
            error_code=row["error_code"],
            error_detail=row["error_detail"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


class SubprocessQwenVoiceDesignRunner:
    def __init__(
        self,
        python_executable: Path,
        *,
        timeout_seconds: float = 1_800.0,
    ) -> None:
        self.python_executable = python_executable.expanduser().resolve()
        self.worker_path = Path(__file__).resolve().parents[1] / "engine_worker.py"
        self.timeout_seconds = timeout_seconds

    async def design(
        self,
        *,
        description: str,
        take: int,
        output_path: Path,
        result_path: Path,
        should_cancel: Callable[[], bool],
    ) -> VoiceDesignResult:
        process = await asyncio.create_subprocess_exec(
            str(self.python_executable),
            str(self.worker_path),
            "--tool",
            "qwen_voice_design",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        payload = json.dumps(
            {
                "description": description,
                "take": take,
                "output_path": str(output_path.resolve()),
                "result_path": str(result_path.resolve()),
            },
            ensure_ascii=False,
        ).encode()
        communicate = asyncio.create_task(process.communicate(payload))
        started = asyncio.get_running_loop().time()
        try:
            while not communicate.done():
                if should_cancel():
                    if process.returncode is None:
                        process.kill()
                        await process.wait()
                    communicate.cancel()
                    with suppress(asyncio.CancelledError):
                        await communicate
                    raise VoiceDesignCancelled("voice design was cancelled")
                if asyncio.get_running_loop().time() - started > self.timeout_seconds:
                    if process.returncode is None:
                        process.kill()
                        await process.wait()
                    communicate.cancel()
                    with suppress(asyncio.CancelledError):
                        await communicate
                    raise TimeoutError
                await asyncio.sleep(0.25)
            stdout, stderr = await communicate
        except asyncio.CancelledError:
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise
        except TimeoutError as error:
            raise RuntimeError("Qwen VoiceDesign exceeded its execution timeout") from error
        try:
            response = json.loads(stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            detail = stderr.decode("utf-8", errors="replace")[-4000:]
            raise RuntimeError(f"Qwen VoiceDesign returned invalid output: {detail}") from error
        if not isinstance(response, dict):
            raise RuntimeError("Qwen VoiceDesign returned an invalid response")
        if process.returncode != 0 or "error_type" in response:
            message = str(response.get("message") or "Qwen VoiceDesign failed")
            detail = stderr.decode("utf-8", errors="replace")[-4000:]
            raise RuntimeError(f"{message}{f': {detail}' if detail else ''}")
        return VoiceDesignResult.from_mapping(response)


class VoiceDesignJobService:
    def __init__(
        self,
        *,
        store: VoiceDesignJobStore,
        studio_store: SqliteStudioStore,
        output_root: Path,
        runner: VoiceDesignRunner | None,
    ) -> None:
        self.store = store
        self.studio_store = studio_store
        self.output_root = Path(output_root)
        self.runner = runner
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._worker is not None:
            return
        self.store.initialize()
        self.output_root.mkdir(parents=True, exist_ok=True)
        for job_id in self.store.requeue_interrupted():
            await self._queue.put(job_id)
        self._worker = asyncio.create_task(
            self._worker_loop(), name="splicr-voice-design-worker"
        )

    async def stop(self) -> None:
        if self._worker is None:
            return
        self._worker.cancel()
        try:
            await self._worker
        except asyncio.CancelledError:
            pass
        self._worker = None

    async def submit(self, *, label: str, description: str, take: int) -> VoiceDesignJob:
        if self.runner is None:
            raise VoiceDesignUnavailableError(
                "Qwen3 is not configured. Connect its Python environment in Components first."
            )
        job = self.store.create_or_get(label=label, description=description, take=take)
        if job.status is VoiceDesignJobStatus.COMPLETED:
            try:
                self.studio_store.get_voice_profile(job.profile_id or "")
                return job
            except KeyError:
                job = self.store.restart_completed(job.id)
        if job.status is VoiceDesignJobStatus.QUEUED:
            await self._queue.put(job.id)
        return job

    async def retry(self, job_id: str) -> VoiceDesignJob:
        if self.runner is None:
            raise VoiceDesignUnavailableError(
                "Qwen3 is not configured. Connect its Python environment in Components first."
            )
        job = self.store.retry(job_id)
        await self._queue.put(job.id)
        return job

    async def cancel(self, job_id: str) -> VoiceDesignJob:
        return self.store.request_cancel(job_id)

    async def _worker_loop(self) -> None:
        while True:
            job_id = await self._queue.get()
            try:
                await self._run_job(job_id)
            except asyncio.CancelledError:
                raise
            finally:
                self._queue.task_done()

    async def _run_job(self, job_id: str) -> None:
        if not self.store.claim(job_id):
            return
        job = self.store.get(job_id)
        directory = self.output_root / job.id
        output_path = directory / "reference.wav"
        result_path = directory / "design-result.json"
        directory.mkdir(parents=True, exist_ok=True)
        profile: VoiceProfile | None = None
        try:
            if result_path.is_file() and output_path.is_file():
                result = VoiceDesignResult.from_mapping(
                    json.loads(result_path.read_text(encoding="utf-8"))
                )
            else:
                if self.runner is None:
                    raise VoiceDesignUnavailableError("Qwen3 is not configured")
                result = await self.runner.design(
                    description=job.description,
                    take=job.take,
                    output_path=output_path,
                    result_path=result_path,
                    should_cancel=lambda: self.store.cancel_requested(job.id),
                )
            if self.store.cancel_requested(job.id):
                raise VoiceDesignCancelled("voice design was cancelled")
            profile = self._materialize_profile(job, output_path, result)
            self.store.complete(job.id, profile)
        except asyncio.CancelledError:
            raise
        except VoiceDesignCancelled:
            if profile is not None:
                with suppress(KeyError):
                    self.studio_store.delete_voice_profile(profile.id)
            self.store.mark_cancelled(job.id)
            return
        except VoiceDesignUnavailableError as error:
            self.store.fail(job.id, "engine_unavailable", str(error))
            return
        except Exception as error:
            self.store.fail(job.id, "voice_design_failed", str(error))
            return

    def _materialize_profile(
        self,
        job: VoiceDesignJob,
        output_path: Path,
        result: VoiceDesignResult,
    ) -> VoiceProfile:
        if result.reference_text != QWEN_REFERENCE_TEXT:
            raise ValueError("VoiceDesign returned an unexpected reference transcript")
        if Path(result.output_path).resolve() != output_path.resolve() or not output_path.is_file():
            raise ValueError("VoiceDesign did not create the expected reference recording")
        with wave.open(str(output_path), "rb") as recording:
            if (
                recording.getcomptype() != "NONE"
                or recording.getnchannels() != 1
                or recording.getsampwidth() != 2
                or recording.getframerate() != 24_000
                or recording.getnframes() < 1
            ):
                raise ValueError(
                    "VoiceDesign reference must be mono PCM16 WAV audio at 24,000 Hz"
                )
            seconds = recording.getnframes() / recording.getframerate()
            metadata = {
                "managed": True,
                "voice_design_job_id": job.id,
                "design_model": result.model,
                "design_seed": result.seed,
                "size_bytes": output_path.stat().st_size,
                "seconds": round(seconds, 3),
                "sample_rate": recording.getframerate(),
                "channels": recording.getnchannels(),
                "sample_width": recording.getsampwidth(),
            }
        return self.studio_store.save_voice_profile(
            VoiceProfile(
                id=job.id,
                label=job.label,
                engine_id="qwen3",
                kind=VoiceProfileKind.DESIGNED,
                description=job.description,
                reference_audio_path=str(output_path.resolve()),
                reference_text=QWEN_REFERENCE_TEXT,
                settings={"design_take": job.take},
                metadata=metadata,
                created_at=job.created_at,
                updated_at=utc_now(),
            )
        )
