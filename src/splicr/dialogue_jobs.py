from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

from .studio.dialogue import (
    ChatCompleter,
    DialogueGenerationCheckpoint,
    DialogueGenerationError,
    DialogueGenerationOptions,
    DialogueScript,
    DialogueTurn,
    generate_script,
    split_sections,
)


class DialogueScriptJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    FAILED = "failed"
    COMPLETED = "completed"


class DialogueScriptJobNotFoundError(LookupError):
    pass


class InvalidDialogueScriptJobStateError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DialogueScriptJobRequest:
    chat_resource_id: str
    resource_revision: int
    model: str
    text: str
    options: DialogueGenerationOptions

    def __post_init__(self) -> None:
        if not self.chat_resource_id.strip():
            raise ValueError("chat_resource_id must not be blank")
        if self.resource_revision < 1:
            raise ValueError("resource_revision must be positive")
        if not self.model.strip():
            raise ValueError("model must not be blank")
        if not self.text.strip():
            raise ValueError("text must not be blank")

    def to_dict(self) -> dict[str, Any]:
        return {
            "chat_resource_id": self.chat_resource_id,
            "resource_revision": self.resource_revision,
            "model": self.model,
            "text": self.text,
            "options": asdict(self.options),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> DialogueScriptJobRequest:
        return cls(
            chat_resource_id=str(value["chat_resource_id"]),
            resource_revision=int(value["resource_revision"]),
            model=str(value["model"]),
            text=str(value["text"]),
            options=DialogueGenerationOptions(**dict(value["options"])),
        )


@dataclass(frozen=True, slots=True)
class DialogueScriptJob:
    id: str
    status: DialogueScriptJobStatus
    request: DialogueScriptJobRequest
    total_sections: int
    completed_sections: int
    progress_message: str
    progress_messages: tuple[str, ...]
    checkpoint: DialogueGenerationCheckpoint | None
    result: DialogueScript | None
    error_code: str | None
    error_detail: str | None
    created_at: str
    updated_at: str

    @property
    def progress(self) -> float:
        if self.status is DialogueScriptJobStatus.COMPLETED:
            return 1.0
        if not self.total_sections:
            return 0.0
        return min(1.0, self.completed_sections / self.total_sections)


class SqliteDialogueScriptJobStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path)
        self._lock = threading.RLock()

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS dialogue_script_jobs (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    total_sections INTEGER NOT NULL,
                    completed_sections INTEGER NOT NULL DEFAULT 0,
                    progress_message TEXT NOT NULL DEFAULT '',
                    progress_json TEXT NOT NULL DEFAULT '[]',
                    checkpoint_json TEXT,
                    result_json TEXT,
                    error_code TEXT,
                    error_detail TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_dialogue_script_jobs_updated
                ON dialogue_script_jobs(updated_at DESC)
                """
            )
            connection.commit()

    def create(self, request: DialogueScriptJobRequest) -> DialogueScriptJob:
        total_sections = len(
            split_sections(
                request.text,
                max_chars=request.options.section_chars,
                max_sections=request.options.max_sections,
            )
        )
        if not total_sections:
            raise ValueError("There is no text to turn into dialogue.")
        job_id = uuid4().hex
        created_at = _utc_now()
        message = f"Queued {total_sections} section(s) for dialogue writing."
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO dialogue_script_jobs (
                    id, status, request_json, total_sections, completed_sections,
                    progress_message, progress_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    DialogueScriptJobStatus.QUEUED.value,
                    _json(request.to_dict()),
                    total_sections,
                    message,
                    _json([message]),
                    created_at,
                    created_at,
                ),
            )
            connection.commit()
        return self.get(job_id)

    def get(self, job_id: str) -> DialogueScriptJob:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM dialogue_script_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        if row is None:
            raise DialogueScriptJobNotFoundError(f"dialogue script job not found: {job_id}")
        return self._job(row)

    def list(self, *, limit: int = 50) -> list[DialogueScriptJob]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM dialogue_script_jobs ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._job(row) for row in rows]

    def claim(self, job_id: str) -> bool:
        now = _utc_now()
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE dialogue_script_jobs
                SET status = ?, updated_at = ?
                WHERE id = ? AND status = ?
                """,
                (
                    DialogueScriptJobStatus.RUNNING.value,
                    now,
                    job_id,
                    DialogueScriptJobStatus.QUEUED.value,
                ),
            )
            connection.commit()
        return cursor.rowcount == 1

    def append_progress(self, job_id: str, message: str) -> DialogueScriptJob:
        current = self.get(job_id)
        messages = (*current.progress_messages, message)[-100:]
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE dialogue_script_jobs
                SET progress_message = ?, progress_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (message, _json(messages), _utc_now(), job_id),
            )
            connection.commit()
        return self.get(job_id)

    def save_checkpoint(
        self,
        job_id: str,
        checkpoint: DialogueGenerationCheckpoint,
    ) -> DialogueScriptJob:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE dialogue_script_jobs
                SET completed_sections = ?, checkpoint_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    checkpoint.completed_sections,
                    _json(_checkpoint_to_dict(checkpoint)),
                    _utc_now(),
                    job_id,
                ),
            )
            connection.commit()
        return self.get(job_id)

    def complete(
        self,
        job_id: str,
        script: DialogueScript,
        *,
        cancelled: bool = False,
    ) -> DialogueScriptJob:
        status = (
            DialogueScriptJobStatus.CANCELLED
            if cancelled
            else DialogueScriptJobStatus.COMPLETED
        )
        message = (
            "Cancelled; the generated script so far is available."
            if cancelled
            else "Dialogue script is ready."
        )
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE dialogue_script_jobs
                SET status = ?, completed_sections = ?, progress_message = ?,
                    result_json = ?, error_code = NULL, error_detail = NULL,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    status.value,
                    script.sections if not cancelled else self.get(job_id).completed_sections,
                    message,
                    _json(_script_to_dict(script)),
                    _utc_now(),
                    job_id,
                ),
            )
            connection.commit()
        self.append_progress(job_id, message)
        return self.get(job_id)

    def fail(self, job_id: str, code: str, detail: str) -> DialogueScriptJob:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE dialogue_script_jobs
                SET status = ?, error_code = ?, error_detail = ?,
                    progress_message = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    DialogueScriptJobStatus.FAILED.value,
                    code,
                    detail,
                    detail,
                    _utc_now(),
                    job_id,
                ),
            )
            connection.commit()
        return self.get(job_id)

    def cancel(self, job_id: str) -> DialogueScriptJob:
        current = self.get(job_id)
        if current.status is DialogueScriptJobStatus.QUEUED:
            status = DialogueScriptJobStatus.CANCELLED
            message = "Cancelled before dialogue writing began."
        elif current.status is DialogueScriptJobStatus.RUNNING:
            status = DialogueScriptJobStatus.CANCEL_REQUESTED
            message = "Cancellation requested; waiting for the current model call."
        elif current.status is DialogueScriptJobStatus.CANCEL_REQUESTED:
            return current
        else:
            raise InvalidDialogueScriptJobStateError(
                f"cannot cancel a {current.status.value} dialogue script job"
            )
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE dialogue_script_jobs
                SET status = ?, progress_message = ?, updated_at = ? WHERE id = ?
                """,
                (status.value, message, _utc_now(), job_id),
            )
            connection.commit()
        self.append_progress(job_id, message)
        return self.get(job_id)

    def resume(self, job_id: str) -> DialogueScriptJob:
        current = self.get(job_id)
        if current.status not in {
            DialogueScriptJobStatus.CANCELLED,
            DialogueScriptJobStatus.FAILED,
        }:
            raise InvalidDialogueScriptJobStateError(
                f"cannot resume a {current.status.value} dialogue script job"
            )
        message = f"Queued to resume after {current.completed_sections} section(s)."
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE dialogue_script_jobs
                SET status = ?, result_json = NULL, error_code = NULL,
                    error_detail = NULL, progress_message = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    DialogueScriptJobStatus.QUEUED.value,
                    message,
                    _utc_now(),
                    job_id,
                ),
            )
            connection.commit()
        self.append_progress(job_id, message)
        return self.get(job_id)

    def cancel_requested(self, job_id: str) -> bool:
        return self.get(job_id).status is DialogueScriptJobStatus.CANCEL_REQUESTED

    def requeue_interrupted(self) -> list[str]:
        now = _utc_now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE dialogue_script_jobs SET status = ?, updated_at = ?
                WHERE status = ?
                """,
                (
                    DialogueScriptJobStatus.QUEUED.value,
                    now,
                    DialogueScriptJobStatus.RUNNING.value,
                ),
            )
            connection.execute(
                """
                UPDATE dialogue_script_jobs SET status = ?, updated_at = ?
                WHERE status = ?
                """,
                (
                    DialogueScriptJobStatus.CANCELLED.value,
                    now,
                    DialogueScriptJobStatus.CANCEL_REQUESTED.value,
                ),
            )
            rows = connection.execute(
                "SELECT id FROM dialogue_script_jobs WHERE status = ? ORDER BY created_at",
                (DialogueScriptJobStatus.QUEUED.value,),
            ).fetchall()
            connection.commit()
        return [str(row["id"]) for row in rows]

    @staticmethod
    def _job(row: sqlite3.Row) -> DialogueScriptJob:
        checkpoint = (
            _checkpoint_from_dict(json.loads(row["checkpoint_json"]))
            if row["checkpoint_json"]
            else None
        )
        result = (
            _script_from_dict(json.loads(row["result_json"]))
            if row["result_json"]
            else None
        )
        return DialogueScriptJob(
            id=row["id"],
            status=DialogueScriptJobStatus(row["status"]),
            request=DialogueScriptJobRequest.from_dict(json.loads(row["request_json"])),
            total_sections=int(row["total_sections"]),
            completed_sections=int(row["completed_sections"]),
            progress_message=row["progress_message"],
            progress_messages=tuple(json.loads(row["progress_json"])),
            checkpoint=checkpoint,
            result=result,
            error_code=row["error_code"],
            error_detail=row["error_detail"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection


CompleterFactory = Callable[
    [DialogueScriptJobRequest],
    AbstractAsyncContextManager[ChatCompleter],
]


class DialogueScriptJobService:
    def __init__(
        self,
        store: SqliteDialogueScriptJobStore,
        completer_factory: CompleterFactory,
    ) -> None:
        self.store = store
        self.completer_factory = completer_factory
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._worker is not None:
            return
        self.store.initialize()
        for job_id in self.store.requeue_interrupted():
            await self._queue.put(job_id)
        self._worker = asyncio.create_task(
            self._worker_loop(),
            name="splicr-dialogue-script-worker",
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

    async def create(self, request: DialogueScriptJobRequest) -> DialogueScriptJob:
        job = self.store.create(request)
        await self._queue.put(job.id)
        return job

    async def cancel(self, job_id: str) -> DialogueScriptJob:
        return self.store.cancel(job_id)

    async def resume(self, job_id: str) -> DialogueScriptJob:
        job = self.store.resume(job_id)
        await self._queue.put(job.id)
        return job

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
        try:
            async with self.completer_factory(job.request) as completer:
                script = await generate_script(
                    job.request.text,
                    completer,
                    options=job.request.options,
                    model=job.request.model,
                    progress=lambda message: self.store.append_progress(job_id, message),
                    should_cancel=lambda: self.store.cancel_requested(job_id),
                    checkpoint=job.checkpoint,
                    save_checkpoint=lambda checkpoint: self.store.save_checkpoint(
                        job_id, checkpoint
                    ),
                )
        except asyncio.CancelledError:
            raise
        except DialogueGenerationError as error:
            self.store.fail(job_id, "dialogue_generation_error", str(error))
            return
        except Exception as error:
            self.store.fail(job_id, "chat_provider_error", str(error))
            return
        self.store.complete(job_id, script, cancelled=script.cancelled)


def _checkpoint_to_dict(checkpoint: DialogueGenerationCheckpoint) -> dict[str, Any]:
    return {
        "sections": checkpoint.sections,
        "outline": list(checkpoint.outline),
        "completed_sections": checkpoint.completed_sections,
        "turns": [_turn_to_dict(turn) for turn in checkpoint.turns],
        "running_summary": checkpoint.running_summary,
        "last_speaker": checkpoint.last_speaker,
    }


def _checkpoint_from_dict(value: Mapping[str, Any]) -> DialogueGenerationCheckpoint:
    return DialogueGenerationCheckpoint(
        sections=int(value["sections"]),
        outline=tuple(str(item) for item in value["outline"]),
        completed_sections=int(value.get("completed_sections", 0)),
        turns=tuple(_turn_from_dict(item) for item in value.get("turns", ())),
        running_summary=str(value.get("running_summary", "")),
        last_speaker=value.get("last_speaker"),
    )


def _script_to_dict(script: DialogueScript) -> dict[str, Any]:
    return {
        "turns": [_turn_to_dict(turn) for turn in script.turns],
        "sections": script.sections,
        "outline": list(script.outline),
        "removed_duplicates": script.removed_duplicates,
        "word_count": script.word_count,
        "cancelled": script.cancelled,
    }


def _script_from_dict(value: Mapping[str, Any]) -> DialogueScript:
    return DialogueScript(
        turns=tuple(_turn_from_dict(item) for item in value["turns"]),
        sections=int(value["sections"]),
        outline=tuple(str(item) for item in value["outline"]),
        removed_duplicates=int(value["removed_duplicates"]),
        word_count=int(value["word_count"]),
        cancelled=bool(value.get("cancelled", False)),
    )


def _turn_to_dict(turn: DialogueTurn) -> dict[str, str]:
    return {"speaker": turn.speaker, "text": turn.text}


def _turn_from_dict(value: Mapping[str, Any]) -> DialogueTurn:
    return DialogueTurn(speaker=value["speaker"], text=str(value["text"]))


def _json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
