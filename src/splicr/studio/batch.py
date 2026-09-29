from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
import contextlib
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import inspect
import json
from pathlib import Path
import sqlite3
import threading
import uuid

from ..domain import (
    BATCH_ITEM_VARIABLE,
    DeliveryControls,
    JobRecord,
    JobStatus,
    JsonValue,
    NonverbalFrequency,
    SpeechPace,
    TonePreset,
    VocalStyle,
    utc_now,
)
from ..planning import ChunkTargetMode, SplitStrategy
from ..service import SynthesisService


class BatchQueueStatus(StrEnum):
    PREPARING = "preparing"
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class BatchItemStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


TERMINAL_ITEM_STATUSES = {
    BatchItemStatus.COMPLETED,
    BatchItemStatus.FAILED,
    BatchItemStatus.SKIPPED,
    BatchItemStatus.CANCELLED,
}


def _optional_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f"batch item {field_name} must be an integer or null")
    return int(value)


@dataclass(frozen=True, slots=True)
class BatchItemSpec:
    project_id: str
    project_name: str
    source_name: str | None
    source_text: str
    source_sha256: str
    profile_id: str
    profile_name: str
    profile_snapshot: Mapping[str, JsonValue]
    provider_name: str
    resource_revision: int | None
    model: str | None
    voice: str | None
    instructions: str | None
    controls: DeliveryControls
    variables: Mapping[str, JsonValue]
    split_strategy: SplitStrategy
    chunk_target_mode: ChunkTargetMode
    chunk_target_value: int | None
    remove_numeric_citations: bool
    export_stem: str

    def __post_init__(self) -> None:
        if not self.project_id.strip():
            raise ValueError("project id must not be blank")
        if not self.profile_id.strip():
            raise ValueError("profile id must not be blank")
        if not self.source_text.strip():
            raise ValueError("source text must not be blank")
        actual_hash = hashlib.sha256(self.source_text.encode("utf-8")).hexdigest()
        if self.source_sha256 != actual_hash:
            raise ValueError("source hash does not match the frozen source text")

    def to_mapping(self) -> dict[str, JsonValue]:
        return {
            "project_id": self.project_id,
            "project_name": self.project_name,
            "source_name": self.source_name,
            "source_text": self.source_text,
            "source_sha256": self.source_sha256,
            "profile_id": self.profile_id,
            "profile_name": self.profile_name,
            "profile_snapshot": dict(self.profile_snapshot),
            "provider_name": self.provider_name,
            "resource_revision": self.resource_revision,
            "model": self.model,
            "voice": self.voice,
            "instructions": self.instructions,
            "controls": {
                "tone": self.controls.tone.value,
                "pace": self.controls.pace.value,
                "vocal_style": self.controls.vocal_style.value,
                "nonverbal_frequency": self.controls.nonverbal_frequency.value,
            },
            "variables": dict(self.variables),
            "split_strategy": self.split_strategy.value,
            "chunk_target_mode": self.chunk_target_mode.value,
            "chunk_target_value": self.chunk_target_value,
            "remove_numeric_citations": self.remove_numeric_citations,
            "export_stem": self.export_stem,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> BatchItemSpec:
        controls = value.get("controls")
        if not isinstance(controls, Mapping):
            raise ValueError("batch item controls are missing")
        profile_snapshot = value.get("profile_snapshot")
        variables = value.get("variables")
        if not isinstance(profile_snapshot, Mapping) or not isinstance(variables, Mapping):
            raise ValueError("batch item snapshot is invalid")
        return cls(
            project_id=str(value["project_id"]),
            project_name=str(value["project_name"]),
            source_name=str(value["source_name"]) if value.get("source_name") else None,
            source_text=str(value["source_text"]),
            source_sha256=str(value["source_sha256"]),
            profile_id=str(value["profile_id"]),
            profile_name=str(value["profile_name"]),
            profile_snapshot=dict(profile_snapshot),  # type: ignore[arg-type]
            provider_name=str(value["provider_name"]),
            resource_revision=_optional_int(
                value.get("resource_revision"), "resource_revision"
            ),
            model=str(value["model"]) if value.get("model") else None,
            voice=str(value["voice"]) if value.get("voice") else None,
            instructions=str(value["instructions"]) if value.get("instructions") else None,
            controls=DeliveryControls(
                tone=TonePreset(str(controls.get("tone", TonePreset.NEUTRAL.value))),
                pace=SpeechPace(str(controls.get("pace", SpeechPace.NORMAL.value))),
                vocal_style=VocalStyle(
                    str(controls.get("vocal_style", VocalStyle.NATURAL.value))
                ),
                nonverbal_frequency=NonverbalFrequency(
                    str(
                        controls.get(
                            "nonverbal_frequency", NonverbalFrequency.NEVER.value
                        )
                    )
                ),
            ),
            variables=dict(variables),  # type: ignore[arg-type]
            split_strategy=SplitStrategy(str(value["split_strategy"])),
            chunk_target_mode=ChunkTargetMode(str(value["chunk_target_mode"])),
            chunk_target_value=_optional_int(
                value.get("chunk_target_value"), "chunk_target_value"
            ),
            remove_numeric_citations=bool(value.get("remove_numeric_citations", False)),
            export_stem=str(value["export_stem"]),
        )


@dataclass(frozen=True, slots=True)
class BatchItemDraft:
    project_id: str
    project_name: str
    profile_id: str
    profile_name: str
    spec: BatchItemSpec | None
    error_code: str | None = None
    error_detail: str | None = None


@dataclass(frozen=True, slots=True)
class BatchItem:
    id: str
    queue_id: str
    position: int
    project_id: str
    project_name: str
    profile_id: str
    profile_name: str
    spec: BatchItemSpec | None
    status: BatchItemStatus
    job_id: str | None
    take_id: str | None
    error_code: str | None
    error_detail: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class BatchQueue:
    id: str
    name: str
    status: BatchQueueStatus
    items: tuple[BatchItem, ...]
    pause_after_current: bool
    cancel_remaining: bool
    created_at: str
    updated_at: str

    @property
    def counts(self) -> dict[str, int]:
        result = {status.value: 0 for status in BatchItemStatus}
        for item in self.items:
            result[item.status.value] += 1
        result["total"] = len(self.items)
        return result


class BatchQueueNotFoundError(LookupError):
    pass


class BatchItemNotFoundError(LookupError):
    pass


class InvalidBatchStateError(ValueError):
    pass


class BatchQueueStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path)
        self._lock = threading.RLock()

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS studio_batch_queues (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    pause_after_current INTEGER NOT NULL DEFAULT 0,
                    cancel_remaining INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS studio_batch_items (
                    id TEXT PRIMARY KEY,
                    queue_id TEXT NOT NULL REFERENCES studio_batch_queues(id) ON DELETE CASCADE,
                    position INTEGER NOT NULL,
                    project_id TEXT NOT NULL,
                    project_name TEXT NOT NULL,
                    profile_id TEXT NOT NULL,
                    profile_name TEXT NOT NULL,
                    spec_json TEXT,
                    status TEXT NOT NULL,
                    job_id TEXT,
                    take_id TEXT,
                    error_code TEXT,
                    error_detail TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(queue_id, position)
                );
                CREATE INDEX IF NOT EXISTS idx_studio_batch_queues_created
                    ON studio_batch_queues(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_studio_batch_items_queue
                    ON studio_batch_items(queue_id, position);
                """
            )

    def create(self, name: str, drafts: Sequence[BatchItemDraft]) -> BatchQueue:
        if not drafts:
            raise ValueError("a batch queue requires at least one item")
        queue_id = uuid.uuid4().hex
        now = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO studio_batch_queues
                    (id, name, status, pause_after_current, cancel_remaining, created_at, updated_at)
                VALUES (?, ?, ?, 0, 0, ?, ?)
                """,
                (queue_id, name.strip() or "Narration batch", BatchQueueStatus.PREPARING.value, now, now),
            )
            for position, draft in enumerate(drafts):
                status = BatchItemStatus.PENDING if draft.spec else BatchItemStatus.SKIPPED
                connection.execute(
                    """
                    INSERT INTO studio_batch_items (
                        id, queue_id, position, project_id, project_name, profile_id,
                        profile_name, spec_json, status, job_id, take_id, error_code,
                        error_detail, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?)
                    """,
                    (
                        uuid.uuid4().hex,
                        queue_id,
                        position,
                        draft.project_id,
                        draft.project_name,
                        draft.profile_id,
                        draft.profile_name,
                        json.dumps(draft.spec.to_mapping(), sort_keys=True) if draft.spec else None,
                        status.value,
                        draft.error_code,
                        draft.error_detail,
                        now,
                        now,
                    ),
                )
        return self.get(queue_id)

    def get(self, queue_id: str) -> BatchQueue:
        with self._lock, self._connect() as connection:
            queue_row = connection.execute(
                "SELECT * FROM studio_batch_queues WHERE id = ?", (queue_id,)
            ).fetchone()
            if queue_row is None:
                raise BatchQueueNotFoundError(queue_id)
            item_rows = connection.execute(
                "SELECT * FROM studio_batch_items WHERE queue_id = ? ORDER BY position",
                (queue_id,),
            ).fetchall()
        return self._queue_from_rows(queue_row, item_rows)

    def list(self, *, limit: int = 100) -> list[BatchQueue]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT id FROM studio_batch_queues ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self.get(row["id"]) for row in rows]

    def recoverable(self) -> list[str]:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE studio_batch_queues SET status = ?, updated_at = ?
                WHERE status = ?
                """,
                (BatchQueueStatus.QUEUED.value, utc_now(), BatchQueueStatus.RUNNING.value),
            )
            rows = connection.execute(
                """
                SELECT id FROM studio_batch_queues
                WHERE status IN (?, ?) ORDER BY created_at
                """,
                (BatchQueueStatus.PREPARING.value, BatchQueueStatus.QUEUED.value),
            ).fetchall()
        return [row["id"] for row in rows]

    def set_queue_status(self, queue_id: str, status: BatchQueueStatus) -> BatchQueue:
        self._update_queue(queue_id, status=status.value)
        return self.get(queue_id)

    def finish_preparation(self, queue_id: str) -> BatchQueue:
        queue = self.get(queue_id)
        has_work = any(
            item.status in {BatchItemStatus.READY, BatchItemStatus.RUNNING}
            for item in queue.items
        )
        return self.set_queue_status(
            queue_id, BatchQueueStatus.QUEUED if has_work else BatchQueueStatus.COMPLETED
        )

    def link_job(self, item_id: str, job_id: str) -> BatchItem:
        self._update_item(
            item_id,
            allowed={BatchItemStatus.PENDING},
            status=BatchItemStatus.READY.value,
            job_id=job_id,
            error_code=None,
            error_detail=None,
        )
        return self.get_item(item_id)

    def get_item(self, item_id: str) -> BatchItem:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM studio_batch_items WHERE id = ?", (item_id,)
            ).fetchone()
        if row is None:
            raise BatchItemNotFoundError(item_id)
        return self._item_from_row(row)

    def next_item(self, queue_id: str) -> BatchItem | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM studio_batch_items
                WHERE queue_id = ? AND status IN (?, ?)
                ORDER BY CASE status WHEN ? THEN 0 ELSE 1 END, position
                LIMIT 1
                """,
                (
                    queue_id,
                    BatchItemStatus.RUNNING.value,
                    BatchItemStatus.READY.value,
                    BatchItemStatus.RUNNING.value,
                ),
            ).fetchone()
        return self._item_from_row(row) if row else None

    def mark_item_running(self, item_id: str) -> BatchItem:
        item = self.get_item(item_id)
        if item.status is BatchItemStatus.RUNNING:
            return item
        self._update_item(
            item_id,
            allowed={BatchItemStatus.READY},
            status=BatchItemStatus.RUNNING.value,
        )
        return self.get_item(item_id)

    def complete_item(self, item_id: str, take_id: str | None) -> BatchItem:
        self._update_item(
            item_id,
            allowed={BatchItemStatus.RUNNING},
            status=BatchItemStatus.COMPLETED.value,
            take_id=take_id,
            error_code=None,
            error_detail=None,
        )
        return self.get_item(item_id)

    def fail_item(self, item_id: str, code: str, detail: str) -> BatchItem:
        self._update_item(
            item_id,
            allowed={BatchItemStatus.PENDING, BatchItemStatus.READY, BatchItemStatus.RUNNING},
            status=BatchItemStatus.FAILED.value,
            error_code=code,
            error_detail=detail,
        )
        return self.get_item(item_id)

    def cancel_item(self, item_id: str, detail: str = "Cancelled by the user") -> BatchItem:
        item = self.get_item(item_id)
        if item.status in TERMINAL_ITEM_STATUSES:
            return item
        self._update_item(
            item_id,
            allowed={BatchItemStatus.PENDING, BatchItemStatus.READY, BatchItemStatus.RUNNING},
            status=BatchItemStatus.CANCELLED.value,
            error_code="cancelled",
            error_detail=detail,
        )
        return self.get_item(item_id)

    def cancel_remaining_items(self, queue_id: str) -> BatchQueue:
        now = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE studio_batch_items
                SET status = ?, error_code = ?, error_detail = ?, updated_at = ?
                WHERE queue_id = ? AND status IN (?, ?)
                """,
                (
                    BatchItemStatus.CANCELLED.value,
                    "cancelled",
                    "Cancelled before synthesis began",
                    now,
                    queue_id,
                    BatchItemStatus.PENDING.value,
                    BatchItemStatus.READY.value,
                ),
            )
        self._update_queue(queue_id, cancel_remaining=1)
        return self.get(queue_id)

    def request_pause_after_current(self, queue_id: str) -> BatchQueue:
        self._update_queue(queue_id, pause_after_current=1)
        queue = self.get(queue_id)
        if not any(item.status is BatchItemStatus.RUNNING for item in queue.items):
            return self.set_queue_status(queue_id, BatchQueueStatus.PAUSED)
        return queue

    def resume(self, queue_id: str) -> BatchQueue:
        queue = self.get(queue_id)
        if queue.status is not BatchQueueStatus.PAUSED:
            raise InvalidBatchStateError(f"cannot resume a {queue.status.value} queue")
        self._update_queue(
            queue_id,
            status=BatchQueueStatus.QUEUED.value,
            pause_after_current=0,
        )
        return self.get(queue_id)

    def finalize(self, queue_id: str) -> BatchQueue:
        queue = self.get(queue_id)
        if any(item.status not in TERMINAL_ITEM_STATUSES for item in queue.items):
            return queue
        status = (
            BatchQueueStatus.CANCELLED
            if queue.items and all(item.status is BatchItemStatus.CANCELLED for item in queue.items)
            else BatchQueueStatus.COMPLETED
        )
        return self.set_queue_status(queue_id, status)

    def reorder(self, queue_id: str, ordered_item_ids: Sequence[str]) -> BatchQueue:
        queue = self.get(queue_id)
        current = {item.id: item for item in queue.items}
        if set(ordered_item_ids) != set(current):
            raise ValueError("ordered item ids must contain every queue item exactly once")
        changed = [
            current[item_id]
            for position, item_id in enumerate(ordered_item_ids)
            if current[item_id].position != position
        ]
        if any(item.status not in {BatchItemStatus.PENDING, BatchItemStatus.READY} for item in changed):
            raise InvalidBatchStateError("only not-started items may be reordered")
        with self._lock, self._connect() as connection:
            for item in queue.items:
                connection.execute(
                    "UPDATE studio_batch_items SET position = ? WHERE id = ?",
                    (-(item.position + 1), item.id),
                )
            now = utc_now()
            for position, item_id in enumerate(ordered_item_ids):
                connection.execute(
                    "UPDATE studio_batch_items SET position = ?, updated_at = ? WHERE id = ?",
                    (position, now, item_id),
                )
        return self.get(queue_id)

    def remove(self, queue_id: str, item_id: str) -> BatchQueue:
        item = self.get_item(item_id)
        if item.queue_id != queue_id:
            raise BatchItemNotFoundError(item_id)
        if item.status not in {BatchItemStatus.PENDING, BatchItemStatus.READY}:
            raise InvalidBatchStateError("only not-started items may be removed")
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM studio_batch_items WHERE id = ?", (item_id,))
            rows = connection.execute(
                "SELECT id FROM studio_batch_items WHERE queue_id = ? ORDER BY position",
                (queue_id,),
            ).fetchall()
            for position, row in enumerate(rows):
                connection.execute(
                    "UPDATE studio_batch_items SET position = ?, updated_at = ? WHERE id = ?",
                    (position, utc_now(), row["id"]),
                )
        return self.finalize(queue_id)

    def _update_queue(self, queue_id: str, **values: object) -> None:
        assignments = ["updated_at = ?"]
        parameters: list[object] = [utc_now()]
        for key, value in values.items():
            assignments.append(f"{key} = ?")
            parameters.append(value)
        parameters.append(queue_id)
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                f"UPDATE studio_batch_queues SET {', '.join(assignments)} WHERE id = ?",
                parameters,
            )
        if cursor.rowcount != 1:
            raise BatchQueueNotFoundError(queue_id)

    def _update_item(
        self,
        item_id: str,
        *,
        allowed: set[BatchItemStatus],
        **values: object,
    ) -> None:
        assignments = ["updated_at = ?"]
        parameters: list[object] = [utc_now()]
        for key, value in values.items():
            assignments.append(f"{key} = ?")
            parameters.append(value)
        parameters.extend([item_id, *(status.value for status in allowed)])
        placeholders = ", ".join("?" for _ in allowed)
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                f"""
                UPDATE studio_batch_items SET {', '.join(assignments)}
                WHERE id = ? AND status IN ({placeholders})
                """,
                parameters,
            )
        if cursor.rowcount != 1:
            item = self.get_item(item_id)
            raise InvalidBatchStateError(f"cannot modify a {item.status.value} item")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @classmethod
    def _queue_from_rows(
        cls, queue_row: sqlite3.Row, item_rows: Sequence[sqlite3.Row]
    ) -> BatchQueue:
        return BatchQueue(
            id=queue_row["id"],
            name=queue_row["name"],
            status=BatchQueueStatus(queue_row["status"]),
            items=tuple(cls._item_from_row(row) for row in item_rows),
            pause_after_current=bool(queue_row["pause_after_current"]),
            cancel_remaining=bool(queue_row["cancel_remaining"]),
            created_at=queue_row["created_at"],
            updated_at=queue_row["updated_at"],
        )

    @staticmethod
    def _item_from_row(row: sqlite3.Row) -> BatchItem:
        raw_spec = json.loads(row["spec_json"]) if row["spec_json"] else None
        return BatchItem(
            id=row["id"],
            queue_id=row["queue_id"],
            position=row["position"],
            project_id=row["project_id"],
            project_name=row["project_name"],
            profile_id=row["profile_id"],
            profile_name=row["profile_name"],
            spec=BatchItemSpec.from_mapping(raw_spec) if raw_spec else None,
            status=BatchItemStatus(row["status"]),
            job_id=row["job_id"],
            take_id=row["take_id"],
            error_code=row["error_code"],
            error_detail=row["error_detail"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


CompletionCallback = Callable[[JobRecord], str | None | Awaitable[str | None]]


class BatchQueueService:
    def __init__(
        self,
        *,
        store: BatchQueueStore,
        synthesis: SynthesisService,
        on_job_completed: CompletionCallback | None = None,
        poll_interval_seconds: float = 0.2,
    ) -> None:
        self.store = store
        self.synthesis = synthesis
        self.on_job_completed = on_job_completed
        self.poll_interval_seconds = poll_interval_seconds
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._worker is not None:
            return
        self.store.initialize()
        for queue_id in self.store.recoverable():
            queue = self.store.get(queue_id)
            if queue.status is BatchQueueStatus.PREPARING:
                await self._prepare_queue(queue_id)
                queue = self.store.get(queue_id)
            if queue.status is BatchQueueStatus.QUEUED:
                self._queue.put_nowait(queue_id)
        self._worker = asyncio.create_task(self._worker_loop(), name="splicr-batch-worker")

    async def stop(self) -> None:
        if self._worker is None:
            return
        self._worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._worker
        self._worker = None

    async def submit(self, name: str, drafts: Sequence[BatchItemDraft]) -> BatchQueue:
        self.store.initialize()
        queue = self.store.create(name, drafts)
        await self._prepare_queue(queue.id)
        queue = self.store.get(queue.id)
        if queue.status is BatchQueueStatus.QUEUED:
            await self._queue.put(queue.id)
        return queue

    def get(self, queue_id: str) -> BatchQueue:
        return self.store.get(queue_id)

    def list(self, *, limit: int = 100) -> list[BatchQueue]:
        return self.store.list(limit=limit)

    async def pause_remaining(self, queue_id: str) -> BatchQueue:
        return self.store.request_pause_after_current(queue_id)

    async def pause_current(self, queue_id: str) -> BatchQueue:
        queue = self.store.request_pause_after_current(queue_id)
        current = next(
            (item for item in queue.items if item.status is BatchItemStatus.RUNNING), None
        )
        if current and current.job_id:
            job = self.synthesis.get_job(current.job_id)
            if job.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
                await self.synthesis.pause(job.id)
            self.store.set_queue_status(queue_id, BatchQueueStatus.PAUSED)
        return self.store.get(queue_id)

    async def resume(self, queue_id: str) -> BatchQueue:
        queue = self.store.resume(queue_id)
        current = next(
            (item for item in queue.items if item.status is BatchItemStatus.RUNNING), None
        )
        if current and current.job_id:
            job = self.synthesis.get_job(current.job_id)
            if job.status is JobStatus.PAUSED:
                await self.synthesis.resume(job.id)
            self.store.set_queue_status(queue_id, BatchQueueStatus.RUNNING)
        else:
            await self._queue.put(queue_id)
        return self.store.get(queue_id)

    async def cancel_current(self, queue_id: str) -> BatchQueue:
        queue = self.store.get(queue_id)
        current = next(
            (item for item in queue.items if item.status is BatchItemStatus.RUNNING), None
        )
        if current and current.job_id:
            await self.synthesis.cancel(current.job_id)
        return self.store.get(queue_id)

    async def cancel_remaining(self, queue_id: str) -> BatchQueue:
        queue = self.store.cancel_remaining_items(queue_id)
        return self.store.finalize(queue.id)

    async def cancel_all(self, queue_id: str) -> BatchQueue:
        await self.cancel_remaining(queue_id)
        await self.cancel_current(queue_id)
        return self.store.get(queue_id)

    def reorder(self, queue_id: str, ordered_item_ids: Sequence[str]) -> BatchQueue:
        return self.store.reorder(queue_id, ordered_item_ids)

    async def remove(self, queue_id: str, item_id: str) -> BatchQueue:
        item = self.store.get_item(item_id)
        if item.queue_id != queue_id:
            raise BatchItemNotFoundError(item_id)
        if item.status not in {BatchItemStatus.PENDING, BatchItemStatus.READY}:
            raise InvalidBatchStateError("only not-started items may be removed")
        if item.job_id:
            job = self.synthesis.get_job(item.job_id)
            if job.status in {JobStatus.QUEUED, JobStatus.PAUSED}:
                await self.synthesis.cancel(job.id)
        return self.store.remove(queue_id, item_id)

    async def _prepare_queue(self, queue_id: str) -> None:
        queue = self.store.get(queue_id)
        for item in queue.items:
            if item.status is not BatchItemStatus.PENDING or item.spec is None:
                continue
            try:
                existing = self._find_marked_job(item.id)
                if existing is None:
                    spec = item.spec
                    existing = await self.synthesis.submit(
                        text=spec.source_text,
                        provider_name=spec.provider_name,
                        model=spec.model,
                        voice=spec.voice,
                        instructions=spec.instructions,
                        controls=spec.controls,
                        variables=spec.variables,
                        resource_revision=spec.resource_revision,
                        split_strategy=spec.split_strategy,
                        chunk_target_mode=spec.chunk_target_mode,
                        chunk_target_value=spec.chunk_target_value,
                        remove_numeric_citations=spec.remove_numeric_citations,
                        export_stem=spec.export_stem,
                        internal_variables={
                            BATCH_ITEM_VARIABLE: {
                                "queue_id": queue_id,
                                "item_id": item.id,
                            }
                        },
                        enqueue=False,
                    )
                self.store.link_job(item.id, existing.id)
            except Exception as error:
                self.store.fail_item(item.id, "batch_item_preparation_failed", str(error))
        self.store.finish_preparation(queue_id)

    def _find_marked_job(self, item_id: str) -> JobRecord | None:
        for job in self.synthesis.list_jobs(limit=5000):
            marker = job.variables.get(BATCH_ITEM_VARIABLE)
            if isinstance(marker, Mapping) and marker.get("item_id") == item_id:
                return job
        return None

    async def _worker_loop(self) -> None:
        while True:
            queue_id = await self._queue.get()
            try:
                await self._run_queue(queue_id)
            finally:
                self._queue.task_done()

    async def _run_queue(self, queue_id: str) -> None:
        queue = self.store.get(queue_id)
        if queue.status is not BatchQueueStatus.QUEUED:
            return
        self.store.set_queue_status(queue_id, BatchQueueStatus.RUNNING)
        while True:
            queue = self.store.get(queue_id)
            if queue.status is BatchQueueStatus.PAUSED:
                return
            item = self.store.next_item(queue_id)
            if item is None:
                self.store.finalize(queue_id)
                return
            if item.status is BatchItemStatus.READY:
                item = self.store.mark_item_running(item.id)
                if not item.job_id:
                    self.store.fail_item(item.id, "missing_job", "Prepared item has no synthesis job")
                    continue
                await self.synthesis.enqueue_job(item.job_id)
            await self._wait_for_item(queue_id, item)
            queue = self.store.get(queue_id)
            if queue.status is BatchQueueStatus.PAUSED:
                return
            if queue.pause_after_current:
                self.store.set_queue_status(queue_id, BatchQueueStatus.PAUSED)
                return

    async def _wait_for_item(self, queue_id: str, item: BatchItem) -> None:
        if not item.job_id:
            self.store.fail_item(item.id, "missing_job", "Batch item has no synthesis job")
            return
        while True:
            job = self.synthesis.get_job(item.job_id)
            if job.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
                await asyncio.sleep(self.poll_interval_seconds)
                continue
            if job.status is JobStatus.COMPLETED:
                take_id = await self._notify_completed(job)
                if self.on_job_completed is not None and not take_id:
                    self.store.fail_item(
                        item.id,
                        "studio_sync_failed",
                        "Audio completed, but its editable Studio take could not be indexed",
                    )
                    return
                self.store.complete_item(item.id, take_id)
                return
            if job.status is JobStatus.CANCELLED:
                self.store.cancel_item(item.id)
                return
            if job.status is JobStatus.PAUSED:
                queue = self.store.get(queue_id)
                if queue.status is BatchQueueStatus.PAUSED:
                    await asyncio.sleep(self.poll_interval_seconds)
                    continue
                detail = job.error_detail.message if job.error_detail else job.error
                self.store.fail_item(
                    item.id,
                    job.error_detail.code if job.error_detail else "synthesis_paused",
                    detail or "Synthesis paused because the provider reported an error",
                )
                return
            self.store.fail_item(
                item.id,
                job.error_detail.code if job.error_detail else "synthesis_failed",
                (job.error_detail.message if job.error_detail else job.error)
                or "Synthesis failed",
            )
            return

    async def _notify_completed(self, job: JobRecord) -> str | None:
        if self.on_job_completed is None:
            return None
        result = self.on_job_completed(job)
        if inspect.isawaitable(result):
            return await result
        return result
