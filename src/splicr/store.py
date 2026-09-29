from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any, Iterable, Mapping

from .artifacts import collision_export_stem, sanitize_export_stem
from .chunking import utf8_size, word_count
from .domain import (
    ChunkRecord,
    ChunkStatus,
    DeliveryControls,
    ErrorEventDraft,
    ErrorEventRecord,
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
_DATABASE_SCHEMA_VERSION = 6
_ERROR_EVENT_RETENTION_LIMIT = 500


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


def _encode_variables(variables: Mapping[str, Any] | None) -> str:
    return json.dumps(
        dict(variables or {}),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _decode_variables(value: str | None) -> dict[str, Any]:
    payload = json.loads(value or "{}")
    if not isinstance(payload, dict):
        raise ValueError("persisted job variables must be a JSON object")
    return payload


def _encode_json_mapping(value: Mapping[str, Any] | None) -> str | None:
    if value is None:
        return None
    return json.dumps(
        dict(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _decode_json_mapping(value: str | None, *, field_name: str) -> dict[str, Any] | None:
    if value is None:
        return None
    payload = json.loads(value)
    if not isinstance(payload, dict):
        raise ValueError(f"persisted error-event {field_name} must be a JSON object")
    return payload


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
            "event_id": error.event_id,
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
    event_id = payload.get("event_id")
    return JobErrorDetail(
        code=str(payload["code"]),
        message=str(payload["message"]),
        retryable=bool(payload["retryable"]),
        status_code=payload.get("status_code"),
        chunk_index=payload.get("chunk_index"),
        event_id=str(event_id) if event_id is not None else None,
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
                    resource_revision INTEGER,
                    variables_json TEXT NOT NULL DEFAULT '{}',
                    total_chunks INTEGER NOT NULL DEFAULT 0,
                    completed_chunks INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    error_json TEXT,
                    output_path TEXT,
                    export_stem TEXT NOT NULL DEFAULT 'splicr-export',
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
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    PRIMARY KEY (job_id, chunk_index)
                );

                CREATE INDEX IF NOT EXISTS jobs_status_created_idx
                    ON jobs(status, created_at);

                CREATE TABLE IF NOT EXISTS error_event_meta (
                    key TEXT PRIMARY KEY,
                    value INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS error_events (
                    id TEXT PRIMARY KEY,
                    sequence INTEGER NOT NULL UNIQUE,
                    fingerprint TEXT NOT NULL,
                    source TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    code TEXT NOT NULL,
                    category TEXT,
                    message TEXT NOT NULL,
                    retryable INTEGER NOT NULL,
                    status_code INTEGER,
                    method TEXT,
                    endpoint TEXT,
                    request_json TEXT,
                    response_json TEXT,
                    exception_json TEXT,
                    context_json TEXT,
                    provider TEXT,
                    resource_revision INTEGER,
                    job_id TEXT,
                    chunk_index INTEGER,
                    attempt INTEGER,
                    count INTEGER NOT NULL DEFAULT 1,
                    first_occurred_at TEXT NOT NULL,
                    last_occurred_at TEXT NOT NULL,
                    read_at TEXT
                );

                CREATE UNIQUE INDEX IF NOT EXISTS error_events_unread_fingerprint_idx
                    ON error_events(fingerprint) WHERE read_at IS NULL;
                CREATE INDEX IF NOT EXISTS error_events_sequence_idx
                    ON error_events(sequence DESC);
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
            if "resource_revision" not in columns:
                connection.execute("ALTER TABLE jobs ADD COLUMN resource_revision INTEGER")
            if "variables_json" not in columns:
                connection.execute(
                    "ALTER TABLE jobs ADD COLUMN variables_json TEXT NOT NULL DEFAULT '{}'"
                )
            if "export_stem" not in columns:
                connection.execute(
                    "ALTER TABLE jobs ADD COLUMN export_stem TEXT NOT NULL DEFAULT ''"
                )
            used_export_stems: set[str] = set()
            for row in connection.execute(
                "SELECT id, export_stem FROM jobs ORDER BY created_at, id"
            ).fetchall():
                current = str(row["export_stem"] or "").strip()
                base = sanitize_export_stem(
                    current,
                    fallback=f"splicr-{str(row['id'])[:8]}",
                )
                ordinal = 1
                candidate = collision_export_stem(base, ordinal)
                while candidate.casefold() in used_export_stems:
                    ordinal += 1
                    candidate = collision_export_stem(base, ordinal)
                used_export_stems.add(candidate.casefold())
                if candidate != current:
                    connection.execute(
                        "UPDATE jobs SET export_stem = ? WHERE id = ?",
                        (candidate, row["id"]),
                    )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS jobs_export_stem_idx ON jobs(export_stem)"
            )
            chunk_columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(chunks)").fetchall()
            }
            if "metadata_json" not in chunk_columns:
                connection.execute(
                    "ALTER TABLE chunks ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'"
                )
            latest_sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) FROM error_events"
            ).fetchone()[0]
            connection.execute(
                "INSERT OR IGNORE INTO error_event_meta(key, value) VALUES ('sequence', ?)",
                (latest_sequence,),
            )
            connection.execute(
                """
                UPDATE error_event_meta
                SET value = CASE WHEN value < ? THEN ? ELSE value END
                WHERE key = 'sequence'
                """,
                (latest_sequence, latest_sequence),
            )
            connection.execute(f"PRAGMA user_version = {_DATABASE_SCHEMA_VERSION}")

    def record_error_event(self, draft: ErrorEventDraft) -> ErrorEventRecord:
        """Record an occurrence, refreshing an existing matching unread event in place.

        The public ID remains stable while ``sequence`` advances for every occurrence. This lets
        cursor-based clients observe deduplicated updates as new activity. Only the 500 records
        with the greatest sequences are retained.
        """

        if not draft.fingerprint:
            raise ValueError("an error event fingerprint must not be empty")

        request_json = _encode_json_mapping(draft.request)
        response_json = _encode_json_mapping(draft.response)
        exception_json = _encode_json_mapping(draft.exception)
        context_json = _encode_json_mapping(draft.context)

        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            sequence = self._next_error_event_sequence(connection)
            existing = connection.execute(
                """
                SELECT id FROM error_events
                WHERE fingerprint = ? AND read_at IS NULL
                LIMIT 1
                """,
                (draft.fingerprint,),
            ).fetchone()

            if existing is None:
                event_id = f"error_{uuid.uuid4().hex}"
                connection.execute(
                    """
                    INSERT INTO error_events (
                        id, sequence, fingerprint, source, severity, code, category, message,
                        retryable, status_code, method, endpoint, request_json, response_json,
                        exception_json, context_json, provider, resource_revision, job_id,
                        chunk_index, attempt, count, first_occurred_at, last_occurred_at, read_at
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        1, ?, ?, NULL
                    )
                    """,
                    (
                        event_id,
                        sequence,
                        draft.fingerprint,
                        draft.source,
                        draft.severity,
                        draft.code,
                        draft.category,
                        draft.message,
                        int(draft.retryable),
                        draft.status_code,
                        draft.method,
                        draft.endpoint,
                        request_json,
                        response_json,
                        exception_json,
                        context_json,
                        draft.provider,
                        draft.resource_revision,
                        draft.job_id,
                        draft.chunk_index,
                        draft.attempt,
                        draft.occurred_at,
                        draft.occurred_at,
                    ),
                )
            else:
                event_id = str(existing["id"])
                connection.execute(
                    """
                    UPDATE error_events
                    SET sequence = ?, source = ?, severity = ?, code = ?, category = ?,
                        message = ?, retryable = ?, status_code = ?, method = ?, endpoint = ?,
                        request_json = ?, response_json = ?, exception_json = ?, context_json = ?,
                        provider = ?, resource_revision = ?, job_id = ?, chunk_index = ?,
                        attempt = ?, count = count + 1, last_occurred_at = ?
                    WHERE id = ?
                    """,
                    (
                        sequence,
                        draft.source,
                        draft.severity,
                        draft.code,
                        draft.category,
                        draft.message,
                        int(draft.retryable),
                        draft.status_code,
                        draft.method,
                        draft.endpoint,
                        request_json,
                        response_json,
                        exception_json,
                        context_json,
                        draft.provider,
                        draft.resource_revision,
                        draft.job_id,
                        draft.chunk_index,
                        draft.attempt,
                        draft.occurred_at,
                        event_id,
                    ),
                )

            connection.execute(
                """
                DELETE FROM error_events
                WHERE id IN (
                    SELECT id FROM error_events
                    ORDER BY sequence DESC
                    LIMIT -1 OFFSET ?
                )
                """,
                (_ERROR_EVENT_RETENTION_LIMIT,),
            )
            row = connection.execute(
                "SELECT * FROM error_events WHERE id = ?", (event_id,)
            ).fetchone()

        if row is None:  # pragma: no cover - the just-recorded newest event cannot be pruned
            raise RuntimeError("recorded error event was unexpectedly unavailable")
        return self._error_event_from_row(row)

    def list_error_events(
        self,
        after_sequence: int = 0,
        limit: int = 100,
        unread_only: bool = False,
    ) -> list[ErrorEventRecord]:
        """List events with newer sequences first; ``after_sequence`` is an exclusive cursor."""

        if after_sequence < 0:
            raise ValueError("after_sequence must be non-negative")
        if limit < 1:
            raise ValueError("limit must be at least 1")
        effective_limit = min(limit, _ERROR_EVENT_RETENTION_LIMIT)
        unread_clause = " AND read_at IS NULL" if unread_only else ""
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM error_events
                WHERE sequence > ?{unread_clause}
                ORDER BY sequence DESC
                LIMIT ?
                """,
                (after_sequence, effective_limit),
            ).fetchall()
        return [self._error_event_from_row(row) for row in rows]

    def get_error_event(self, event_id: str) -> ErrorEventRecord | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM error_events WHERE id = ?", (event_id,)
            ).fetchone()
        return self._error_event_from_row(row) if row is not None else None

    def error_event_counts(self) -> tuple[int, int]:
        """Return ``(unread records, total records)`` within the retained event log."""

        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    SUM(CASE WHEN read_at IS NULL THEN 1 ELSE 0 END) AS unread,
                    COUNT(*) AS total
                FROM error_events
                """
            ).fetchone()
        return int(row["unread"] or 0), int(row["total"] or 0)

    def mark_error_event_read(self, event_id: str) -> ErrorEventRecord | None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE error_events
                SET read_at = COALESCE(read_at, ?)
                WHERE id = ?
                """,
                (utc_now(), event_id),
            )
            row = connection.execute(
                "SELECT * FROM error_events WHERE id = ?", (event_id,)
            ).fetchone()
        return self._error_event_from_row(row) if row is not None else None

    def mark_all_error_events_read(self) -> int:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "UPDATE error_events SET read_at = ? WHERE read_at IS NULL",
                (utc_now(),),
            )
        return cursor.rowcount

    def clear_error_events(self, scope: str) -> int:
        if scope not in {"read", "all"}:
            raise ValueError("error-event clear scope must be 'read' or 'all'")
        query = (
            "DELETE FROM error_events"
            if scope == "all"
            else ("DELETE FROM error_events WHERE read_at IS NOT NULL")
        )
        with self._lock, self._connect() as connection:
            cursor = connection.execute(query)
        return cursor.rowcount

    def create_job(
        self,
        *,
        job_id: str,
        provider: str,
        model: str,
        voice: str,
        instructions: str | None,
        controls: DeliveryControls | None = None,
        resource_revision: int | None = None,
        variables: Mapping[str, Any] | None = None,
        export_stem: str | None = None,
    ) -> JobRecord:
        now = utc_now()
        with self._lock, self._connect() as connection:
            allocated_export_stem = self._allocate_export_stem(
                connection,
                export_stem,
                job_id,
            )
            connection.execute(
                """
                INSERT INTO jobs (
                    id, status, provider, model, voice, instructions, controls_json,
                    resource_revision, variables_json, total_chunks, completed_chunks,
                    export_stem, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?)
                """,
                (
                    job_id,
                    JobStatus.QUEUED,
                    provider,
                    model,
                    voice,
                    instructions,
                    _encode_controls(controls or DeliveryControls()),
                    resource_revision,
                    _encode_variables(variables),
                    allocated_export_stem,
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
        resource_revision: int | None = None,
        variables: Mapping[str, Any] | None = None,
        chunks: Iterable[str],
        export_stem: str | None = None,
    ) -> JobRecord:
        chunk_list = list(chunks)
        if not chunk_list:
            raise ValueError("a job must have at least one chunk")
        now = utc_now()
        with self._lock, self._connect() as connection:
            allocated_export_stem = self._allocate_export_stem(
                connection,
                export_stem,
                job_id,
            )
            connection.execute(
                """
                INSERT INTO jobs (
                    id, status, provider, model, voice, instructions, controls_json,
                    resource_revision, variables_json, total_chunks, completed_chunks,
                    export_stem, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
                """,
                (
                    job_id,
                    JobStatus.QUEUED,
                    provider,
                    model,
                    voice,
                    instructions,
                    _encode_controls(controls or DeliveryControls()),
                    resource_revision,
                    _encode_variables(variables),
                    len(chunk_list),
                    allocated_export_stem,
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

    def mark_chunk_completed(
        self,
        job_id: str,
        index: int,
        pcm_path: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        now = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE chunks SET status = ?, pcm_path = ?, error = NULL, metadata_json = ?
                WHERE job_id = ? AND chunk_index = ?
                """,
                (ChunkStatus.COMPLETED, pcm_path, _encode_variables(metadata), job_id, index),
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
    def _next_error_event_sequence(connection: sqlite3.Connection) -> int:
        connection.execute("UPDATE error_event_meta SET value = value + 1 WHERE key = 'sequence'")
        row = connection.execute(
            "SELECT value FROM error_event_meta WHERE key = 'sequence'"
        ).fetchone()
        if row is None:
            raise RuntimeError("error-event sequence metadata is unavailable")
        return int(row["value"])

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
            resource_revision=row["resource_revision"],
            variables=_decode_variables(row["variables_json"]),
            export_stem=row["export_stem"],
        )

    @staticmethod
    def _allocate_export_stem(
        connection: sqlite3.Connection,
        requested: str | None,
        job_id: str,
    ) -> str:
        fallback = f"splicr-{job_id[:8]}"
        base = sanitize_export_stem(requested, fallback=fallback)
        existing = {
            str(row[0]).casefold()
            for row in connection.execute("SELECT export_stem FROM jobs").fetchall()
            if row[0]
        }
        ordinal = 1
        candidate = collision_export_stem(base, ordinal)
        while candidate.casefold() in existing:
            ordinal += 1
            candidate = collision_export_stem(base, ordinal)
        return candidate

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
            metadata=_decode_variables(row["metadata_json"]),
        )

    @staticmethod
    def _error_event_from_row(row: sqlite3.Row) -> ErrorEventRecord:
        return ErrorEventRecord(
            id=str(row["id"]),
            sequence=int(row["sequence"]),
            fingerprint=str(row["fingerprint"]),
            source=str(row["source"]),
            severity=str(row["severity"]),
            code=str(row["code"]),
            category=row["category"],
            message=str(row["message"]),
            retryable=bool(row["retryable"]),
            status_code=row["status_code"],
            method=row["method"],
            endpoint=row["endpoint"],
            request=_decode_json_mapping(row["request_json"], field_name="request"),
            response=_decode_json_mapping(row["response_json"], field_name="response"),
            exception=_decode_json_mapping(row["exception_json"], field_name="exception"),
            context=_decode_json_mapping(row["context_json"], field_name="context"),
            provider=row["provider"],
            resource_revision=row["resource_revision"],
            job_id=row["job_id"],
            chunk_index=row["chunk_index"],
            attempt=row["attempt"],
            count=int(row["count"]),
            first_occurred_at=str(row["first_occurred_at"]),
            last_occurred_at=str(row["last_occurred_at"]),
            read_at=row["read_at"],
        )
