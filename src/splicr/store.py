from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Iterable

from .chunking import utf8_size, word_count
from .domain import (
    ChunkRecord,
    ChunkStatus,
    DeliveryControls,
    InvalidJobStateError,
    JobErrorDetail,
    JobNotFoundError,
    JobRecord,
    JobStatus,
    NonverbalFrequency,
    SpeechPace,
    TonePreset,
    VocalStyle,
    utc_now,
)


_CONTROLS_SCHEMA_VERSION = 1
_ERROR_SCHEMA_VERSION = 1


def _encode_controls(controls: DeliveryControls) -> str:
    return json.dumps(
        {
            "version": _CONTROLS_SCHEMA_VERSION,
            "tone": controls.tone.value,
            "pace": controls.pace.value,
            "vocal_style": controls.vocal_style.value,
            "nonverbal_frequency": controls.nonverbal_frequency.value,
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def _decode_controls(value: str | None) -> DeliveryControls:
    payload = json.loads(value or "{}")
    if not payload:
        return DeliveryControls()
    if payload.get("version") != _CONTROLS_SCHEMA_VERSION:
        raise ValueError("unsupported persisted delivery-controls version")
    return DeliveryControls(
        tone=TonePreset(payload["tone"]),
        pace=SpeechPace(payload["pace"]),
        vocal_style=VocalStyle(payload["vocal_style"]),
        nonverbal_frequency=NonverbalFrequency(payload["nonverbal_frequency"]),
    )


def _encode_error(error: JobErrorDetail | None) -> str | None:
    if error is None:
        return None
    return json.dumps(
        {
            "version": _ERROR_SCHEMA_VERSION,
            "code": error.code,
            "message": error.message,
            "retryable": error.retryable,
            "status_code": error.status_code,
            "chunk_index": error.chunk_index,
            "occurred_at": error.occurred_at,
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def _decode_error(value: str | None, legacy_message: str | None) -> JobErrorDetail | None:
    if not value:
        if not legacy_message:
            return None
        return JobErrorDetail(
            code="legacy_error",
            message=legacy_message,
            retryable=True,
        )
    payload = json.loads(value)
    if payload.get("version") != _ERROR_SCHEMA_VERSION:
        raise ValueError("unsupported persisted job-error version")
    return JobErrorDetail(
        code=str(payload["code"]),
        message=str(payload["message"]),
        retryable=bool(payload["retryable"]),
        status_code=payload.get("status_code"),
        chunk_index=payload.get("chunk_index"),
        occurred_at=str(payload["occurred_at"]),
    )


class SqliteJobStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self._lock = threading.RLock()

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    voice TEXT NOT NULL,
                    instructions TEXT,
                    controls_json TEXT NOT NULL DEFAULT '{}',
                    total_chunks INTEGER NOT NULL DEFAULT 0,
                    completed_chunks INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    error_json TEXT,
                    output_path TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS chunks (
                    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    chunk_index INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    byte_count INTEGER NOT NULL,
                    word_count INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    pcm_path TEXT,
                    error TEXT,
                    PRIMARY KEY (job_id, chunk_index)
                );

                CREATE INDEX IF NOT EXISTS jobs_status_created_idx
                    ON jobs(status, created_at);
                """
            )
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(jobs)").fetchall()
            }
            if "controls_json" not in columns:
                connection.execute(
                    "ALTER TABLE jobs ADD COLUMN controls_json TEXT NOT NULL DEFAULT '{}'"
                )
            if "error_json" not in columns:
                connection.execute("ALTER TABLE jobs ADD COLUMN error_json TEXT")
            connection.execute("PRAGMA user_version = 2")

    def create_job(
        self,
        *,
        job_id: str,
        provider: str,
        model: str,
        voice: str,
        instructions: str | None,
        controls: DeliveryControls | None = None,
    ) -> JobRecord:
        now = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO jobs (
                    id, status, provider, model, voice, instructions, controls_json,
                    total_chunks, completed_chunks, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?)
                """,
                (
                    job_id,
                    JobStatus.QUEUED,
                    provider,
                    model,
                    voice,
                    instructions,
                    _encode_controls(controls or DeliveryControls()),
                    now,
                    now,
                ),
            )
        return self.get_job(job_id)

    def create_job_with_chunks(
        self,
        *,
        job_id: str,
        provider: str,
        model: str,
        voice: str,
        instructions: str | None,
        controls: DeliveryControls | None = None,
        chunks: Iterable[str],
    ) -> JobRecord:
        chunk_list = list(chunks)
        if not chunk_list:
            raise ValueError("a job must have at least one chunk")
        now = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO jobs (
                    id, status, provider, model, voice, instructions, controls_json,
                    total_chunks, completed_chunks, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    job_id,
                    JobStatus.QUEUED,
                    provider,
                    model,
                    voice,
                    instructions,
                    _encode_controls(controls or DeliveryControls()),
                    len(chunk_list),
                    now,
                    now,
                ),
            )
            connection.executemany(
                """
                INSERT INTO chunks (
                    job_id, chunk_index, text, byte_count, word_count, status, attempts
                ) VALUES (?, ?, ?, ?, ?, ?, 0)
                """,
                [
                    (
                        job_id,
                        index,
                        text,
                        utf8_size(text),
                        word_count(text),
                        ChunkStatus.PENDING,
                    )
                    for index, text in enumerate(chunk_list)
                ],
            )
        return self.get_job(job_id)

    def add_chunks(self, job_id: str, chunks: Iterable[str]) -> None:
        chunk_list = list(chunks)
        if not chunk_list:
            raise ValueError("a job must have at least one chunk")
        now = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM chunks WHERE job_id = ?", (job_id,))
            connection.executemany(
                """
                INSERT INTO chunks (
                    job_id, chunk_index, text, byte_count, word_count, status, attempts
                ) VALUES (?, ?, ?, ?, ?, ?, 0)
                """,
                [
                    (
                        job_id,
                        index,
                        text,
                        utf8_size(text),
                        word_count(text),
                        ChunkStatus.PENDING,
                    )
                    for index, text in enumerate(chunk_list)
                ],
            )
            connection.execute(
                """
                UPDATE jobs
                SET total_chunks = ?, completed_chunks = 0, updated_at = ?
                WHERE id = ?
                """,
                (len(chunk_list), now, job_id),
            )

    def get_job(self, job_id: str) -> JobRecord:
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise JobNotFoundError(job_id)
        return self._job_from_row(row)

    def list_jobs(self, limit: int = 100) -> list[JobRecord]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._job_from_row(row) for row in rows]

    def chunks_for_job(self, job_id: str) -> list[ChunkRecord]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM chunks WHERE job_id = ? ORDER BY chunk_index", (job_id,)
            ).fetchall()
        return [self._chunk_from_row(row) for row in rows]

    def queued_job_ids(self) -> list[str]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT id FROM jobs WHERE status = ? ORDER BY created_at", (JobStatus.QUEUED,)
            ).fetchall()
        return [str(row["id"]) for row in rows]

    def requeue_interrupted(self) -> list[str]:
        now = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE chunks SET status = ?, error = NULL
                WHERE status = ? AND job_id IN (
                    SELECT id FROM jobs WHERE status IN (?, ?, ?)
                )
                """,
                (
                    ChunkStatus.PENDING,
                    ChunkStatus.RUNNING,
                    JobStatus.QUEUED,
                    JobStatus.RUNNING,
                    JobStatus.PAUSED,
                ),
            )
            connection.execute(
                """
                UPDATE jobs SET status = ?, error = NULL, error_json = NULL, updated_at = ?
                WHERE status = ?
                """,
                (JobStatus.QUEUED, now, JobStatus.RUNNING),
            )
        return self.queued_job_ids()

    def claim_job(self, job_id: str) -> bool:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status = ?, error = NULL, error_json = NULL, output_path = NULL, updated_at = ?
                WHERE id = ? AND status = ?
                """,
                (JobStatus.RUNNING, utc_now(), job_id, JobStatus.QUEUED),
            )
        return cursor.rowcount == 1

    def mark_job_running(self, job_id: str) -> None:
        if not self.claim_job(job_id):
            raise InvalidJobStateError("only queued jobs can start")

    def mark_job_completed_if_running(self, job_id: str, output_path: str) -> bool:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status = ?, error = NULL, error_json = NULL, output_path = ?, updated_at = ?
                WHERE id = ? AND status = ?
                """,
                (JobStatus.COMPLETED, output_path, utc_now(), job_id, JobStatus.RUNNING),
            )
        return cursor.rowcount == 1

    def mark_job_completed(self, job_id: str, output_path: str) -> None:
        if not self.mark_job_completed_if_running(job_id, output_path):
            raise InvalidJobStateError("only a running job can complete")

    def mark_job_failed(self, job_id: str, error: str) -> None:
        self._update_job(job_id, status=JobStatus.FAILED, error=error, output_path=None)

    def pause_job(self, job_id: str) -> JobRecord:
        job = self.get_job(job_id)
        if job.status is JobStatus.PAUSED:
            return job
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs SET status = ?, updated_at = ?
                WHERE id = ? AND status IN (?, ?)
                """,
                (JobStatus.PAUSED, utc_now(), job_id, JobStatus.QUEUED, JobStatus.RUNNING),
            )
        if cursor.rowcount != 1:
            raise InvalidJobStateError("only queued or running jobs can be paused")
        return self.get_job(job_id)

    def pause_for_error(self, job_id: str, error: JobErrorDetail) -> bool:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status = ?, error = ?, error_json = ?, output_path = NULL, updated_at = ?
                WHERE id = ? AND status IN (?, ?, ?)
                """,
                (
                    JobStatus.PAUSED,
                    error.message,
                    _encode_error(error),
                    utc_now(),
                    job_id,
                    JobStatus.QUEUED,
                    JobStatus.RUNNING,
                    JobStatus.PAUSED,
                ),
            )
        return cursor.rowcount == 1

    def resume_job(self, job_id: str) -> JobRecord:
        now = utc_now()
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status = ?, error = NULL, error_json = NULL, output_path = NULL, updated_at = ?
                WHERE id = ? AND status IN (?, ?)
                """,
                (JobStatus.QUEUED, now, job_id, JobStatus.PAUSED, JobStatus.FAILED),
            )
            if cursor.rowcount != 1:
                exists = connection.execute("SELECT 1 FROM jobs WHERE id = ?", (job_id,)).fetchone()
                if exists is None:
                    raise JobNotFoundError(job_id)
                raise InvalidJobStateError("only paused jobs can be resumed")
            connection.execute(
                """
                UPDATE chunks
                SET status = ?, attempts = 0, pcm_path = NULL, error = NULL
                WHERE job_id = ? AND status IN (?, ?)
                """,
                (ChunkStatus.PENDING, job_id, ChunkStatus.FAILED, ChunkStatus.RUNNING),
            )
        return self.get_job(job_id)

    def cancel_job(self, job_id: str) -> JobRecord:
        job = self.get_job(job_id)
        if job.status is JobStatus.CANCELLED:
            return job
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs SET status = ?, updated_at = ?
                WHERE id = ? AND status IN (?, ?, ?, ?)
                """,
                (
                    JobStatus.CANCELLED,
                    utc_now(),
                    job_id,
                    JobStatus.QUEUED,
                    JobStatus.RUNNING,
                    JobStatus.PAUSED,
                    JobStatus.FAILED,
                ),
            )
        if cursor.rowcount != 1:
            raise InvalidJobStateError("completed jobs cannot be cancelled")
        return self.get_job(job_id)

    def mark_chunk_running(self, job_id: str, index: int) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE chunks
                SET status = ?, attempts = attempts + 1, error = NULL
                WHERE job_id = ? AND chunk_index = ?
                """,
                (ChunkStatus.RUNNING, job_id, index),
            )
            connection.execute("UPDATE jobs SET updated_at = ? WHERE id = ?", (utc_now(), job_id))

    def mark_chunk_pending(self, job_id: str, index: int, error: str) -> None:
        self._update_chunk(job_id, index, ChunkStatus.PENDING, error=error)

    def reset_chunk_for_resynthesis(self, job_id: str, index: int, error: str) -> None:
        now = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE chunks
                SET status = ?, attempts = 0, pcm_path = NULL, error = ?
                WHERE job_id = ? AND chunk_index = ?
                """,
                (ChunkStatus.PENDING, error, job_id, index),
            )
            connection.execute(
                """
                UPDATE jobs
                SET completed_chunks = (
                    SELECT COUNT(*) FROM chunks WHERE job_id = ? AND status = ?
                ), updated_at = ?
                WHERE id = ?
                """,
                (job_id, ChunkStatus.COMPLETED, now, job_id),
            )

    def mark_chunk_failed(self, job_id: str, index: int, error: str) -> None:
        self._update_chunk(job_id, index, ChunkStatus.FAILED, error=error)

    def mark_chunk_completed(self, job_id: str, index: int, pcm_path: str) -> None:
        now = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE chunks SET status = ?, pcm_path = ?, error = NULL
                WHERE job_id = ? AND chunk_index = ?
                """,
                (ChunkStatus.COMPLETED, pcm_path, job_id, index),
            )
            connection.execute(
                """
                UPDATE jobs
                SET completed_chunks = (
                    SELECT COUNT(*) FROM chunks WHERE job_id = ? AND status = ?
                ), updated_at = ?
                WHERE id = ?
                """,
                (job_id, ChunkStatus.COMPLETED, now, job_id),
            )

    def retry_job(self, job_id: str) -> JobRecord:
        return self.resume_job(job_id)

    def _update_job(
        self,
        job_id: str,
        *,
        status: JobStatus,
        error: str | None,
        output_path: str | None,
    ) -> None:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status = ?, error = ?, error_json = NULL, output_path = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, error, output_path, utc_now(), job_id),
            )
        if cursor.rowcount == 0:
            raise JobNotFoundError(job_id)

    def _update_chunk(
        self,
        job_id: str,
        index: int,
        status: ChunkStatus,
        *,
        error: str | None,
    ) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE chunks SET status = ?, error = ?
                WHERE job_id = ? AND chunk_index = ?
                """,
                (status, error, job_id, index),
            )
            connection.execute(
                """
                UPDATE jobs
                SET completed_chunks = (
                    SELECT COUNT(*) FROM chunks WHERE job_id = ? AND status = ?
                ), updated_at = ?
                WHERE id = ?
                """,
                (job_id, ChunkStatus.COMPLETED, utc_now(), job_id),
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _job_from_row(row: sqlite3.Row) -> JobRecord:
        return JobRecord(
            id=row["id"],
            status=JobStatus(row["status"]),
            provider=row["provider"],
            model=row["model"],
            voice=row["voice"],
            instructions=row["instructions"],
            controls=_decode_controls(row["controls_json"]),
            total_chunks=row["total_chunks"],
            completed_chunks=row["completed_chunks"],
            error=row["error"],
            error_detail=_decode_error(row["error_json"], row["error"]),
            output_path=row["output_path"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _chunk_from_row(row: sqlite3.Row) -> ChunkRecord:
        return ChunkRecord(
            job_id=row["job_id"],
            index=row["chunk_index"],
            text=row["text"],
            byte_count=row["byte_count"],
            word_count=row["word_count"],
            status=ChunkStatus(row["status"]),
            attempts=row["attempts"],
            pcm_path=row["pcm_path"],
            error=row["error"],
        )
