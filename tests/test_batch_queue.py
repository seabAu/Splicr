from __future__ import annotations

import asyncio
import hashlib

import pytest

from splicr.config import Settings
from splicr.domain import DeliveryControls, JobStatus
from splicr.planning import ChunkTargetMode, SplitStrategy
from splicr.providers import ProviderRegistry
from splicr.service import SynthesisService
from splicr.studio.batch import (
    BatchItemDraft,
    BatchItemSpec,
    BatchItemStatus,
    BatchQueueService,
    BatchQueueStatus,
    BatchQueueStore,
    InvalidBatchStateError,
)

from .fakes import RecordingProvider


class SlowRecordingProvider(RecordingProvider):
    async def synthesize(self, text, options):
        await asyncio.sleep(0.08)
        return await super().synthesize(text, options)


def _settings(tmp_path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        chunk_max_bytes=10_000,
        chunk_max_words=10_000,
        pacing_seconds=0,
        backoff_base_seconds=0,
        backoff_max_seconds=0,
        backoff_jitter_seconds=0,
    )


def _draft(index: int, text: str, *, provider_name: str = "fake") -> BatchItemDraft:
    source_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    spec = BatchItemSpec(
        project_id=f"project-{index}",
        project_name=f"Project {index}",
        source_name=f"chapter-{index}.md",
        source_text=text,
        source_sha256=source_hash,
        profile_id=f"profile-{index}",
        profile_name=f"Profile {index}",
        profile_snapshot={"name": f"Profile {index}", "voice": "fake-voice"},
        provider_name=provider_name,
        resource_revision=None,
        model="fake-model",
        voice="fake-voice",
        instructions=None,
        controls=DeliveryControls(),
        variables={"seed": index},
        split_strategy=SplitStrategy.SEMANTIC,
        chunk_target_mode=ChunkTargetMode.AUTOMATIC,
        chunk_target_value=None,
        remove_numeric_citations=False,
        export_stem=f"chapter-{index}",
    )
    return BatchItemDraft(
        project_id=spec.project_id,
        project_name=spec.project_name,
        profile_id=spec.profile_id,
        profile_name=spec.profile_name,
        spec=spec,
    )


async def _terminal(batch: BatchQueueService, queue_id: str):
    for _ in range(600):
        queue = batch.get(queue_id)
        if queue.status in {BatchQueueStatus.COMPLETED, BatchQueueStatus.CANCELLED}:
            return queue
        await asyncio.sleep(0.01)
    raise AssertionError("batch queue did not finish")


async def _status(batch: BatchQueueService, queue_id: str, status: BatchQueueStatus):
    for _ in range(600):
        queue = batch.get(queue_id)
        if queue.status is status:
            return queue
        await asyncio.sleep(0.01)
    raise AssertionError(f"batch queue did not reach {status.value}")


def test_batch_prepares_frozen_jobs_and_runs_them_sequentially(tmp_path) -> None:
    async def scenario() -> None:
        provider = RecordingProvider()
        settings = _settings(tmp_path)
        synthesis = SynthesisService(settings=settings, providers=ProviderRegistry([provider]))
        batch = BatchQueueService(
            store=BatchQueueStore(settings.database_path),
            synthesis=synthesis,
            poll_interval_seconds=0.01,
            on_job_completed=lambda job: f"take-{job.id}",
        )
        await synthesis.start()
        try:
            submitted = await batch.submit(
                "Book one", [_draft(1, "First chapter."), _draft(2, "Second chapter.")]
            )
            assert submitted.status is BatchQueueStatus.QUEUED
            assert [item.status for item in submitted.items] == [
                BatchItemStatus.READY,
                BatchItemStatus.READY,
            ]
            assert all(item.job_id for item in submitted.items)
            assert provider.calls == []

            await batch.start()
            finished = await _terminal(batch, submitted.id)
            assert provider.calls == ["First chapter.", "Second chapter."]
            assert [item.status for item in finished.items] == [
                BatchItemStatus.COMPLETED,
                BatchItemStatus.COMPLETED,
            ]
            assert all(item.take_id and item.take_id.startswith("take-") for item in finished.items)
            assert finished.counts["completed"] == 2
            assert finished.items[0].spec is not None
            assert finished.items[0].spec.source_text == "First chapter."
            assert finished.items[0].spec.profile_snapshot["voice"] == "fake-voice"
        finally:
            await batch.stop()
            await synthesis.stop()

    asyncio.run(scenario())


def test_batch_continues_after_provider_failure_and_summarizes_skips(tmp_path) -> None:
    async def scenario() -> None:
        provider = RecordingProvider(fail_text="broken")
        settings = _settings(tmp_path)
        synthesis = SynthesisService(settings=settings, providers=ProviderRegistry([provider]))
        batch = BatchQueueService(
            store=BatchQueueStore(settings.database_path),
            synthesis=synthesis,
            poll_interval_seconds=0.01,
        )
        missing = BatchItemDraft(
            project_id="missing",
            project_name="Missing source",
            profile_id="profile",
            profile_name="Profile",
            spec=None,
            error_code="missing_source",
            error_detail="The project was deleted before the queue was created",
        )
        await synthesis.start()
        await batch.start()
        try:
            submitted = await batch.submit(
                "Mixed batch",
                [_draft(1, "broken chapter."), missing, _draft(3, "Healthy chapter.")],
            )
            finished = await _terminal(batch, submitted.id)
            assert [item.status for item in finished.items] == [
                BatchItemStatus.FAILED,
                BatchItemStatus.SKIPPED,
                BatchItemStatus.COMPLETED,
            ]
            assert finished.items[0].error_code
            assert finished.items[1].error_code == "missing_source"
            assert finished.counts == {
                "pending": 0,
                "ready": 0,
                "running": 0,
                "completed": 1,
                "failed": 1,
                "skipped": 1,
                "cancelled": 0,
                "total": 3,
            }
        finally:
            await batch.stop()
            await synthesis.stop()

    asyncio.run(scenario())


def test_batch_survives_restart_without_uncoordinated_or_duplicate_synthesis(tmp_path) -> None:
    async def scenario() -> None:
        first_provider = RecordingProvider()
        settings = _settings(tmp_path)
        first_synthesis = SynthesisService(
            settings=settings, providers=ProviderRegistry([first_provider])
        )
        first_batch = BatchQueueService(
            store=BatchQueueStore(settings.database_path),
            synthesis=first_synthesis,
            poll_interval_seconds=0.01,
        )
        await first_synthesis.start()
        submitted = await first_batch.submit("Restartable", [_draft(1, "Resume me once.")])
        await first_synthesis.stop()
        assert first_provider.calls == []

        resumed_provider = RecordingProvider()
        resumed_synthesis = SynthesisService(
            settings=settings, providers=ProviderRegistry([resumed_provider])
        )
        resumed_batch = BatchQueueService(
            store=BatchQueueStore(settings.database_path),
            synthesis=resumed_synthesis,
            poll_interval_seconds=0.01,
        )
        await resumed_synthesis.start()
        try:
            await asyncio.sleep(0.03)
            assert resumed_provider.calls == []
            await resumed_batch.start()
            finished = await _terminal(resumed_batch, submitted.id)
            assert finished.items[0].status is BatchItemStatus.COMPLETED
            assert resumed_provider.calls == ["Resume me once."]
        finally:
            await resumed_batch.stop()
            await resumed_synthesis.stop()

    asyncio.run(scenario())


def test_only_not_started_items_can_be_reordered_or_removed(tmp_path) -> None:
    store = BatchQueueStore(tmp_path / "batch.sqlite3")
    store.initialize()
    queue = store.create("Editable", [_draft(1, "One."), _draft(2, "Two.")])
    first, second = queue.items
    store.link_job(first.id, "job-one")
    store.link_job(second.id, "job-two")

    reordered = store.reorder(queue.id, [second.id, first.id])
    assert [item.id for item in reordered.items] == [second.id, first.id]
    store.mark_item_running(second.id)
    with pytest.raises(InvalidBatchStateError, match="not-started"):
        store.reorder(queue.id, [first.id, second.id])
    with pytest.raises(InvalidBatchStateError, match="not-started"):
        store.remove(queue.id, second.id)

    remaining = store.remove(queue.id, first.id)
    assert [item.id for item in remaining.items] == [second.id]


def test_removing_prepared_item_cancels_its_frozen_synthesis_job(tmp_path) -> None:
    async def scenario() -> None:
        provider = RecordingProvider()
        settings = _settings(tmp_path)
        synthesis = SynthesisService(settings=settings, providers=ProviderRegistry([provider]))
        batch = BatchQueueService(
            store=BatchQueueStore(settings.database_path),
            synthesis=synthesis,
            poll_interval_seconds=0.01,
        )
        await synthesis.start()
        try:
            submitted = await batch.submit(
                "Remove prepared", [_draft(1, "Remove me."), _draft(2, "Keep me.")]
            )
            removed = submitted.items[0]
            assert removed.job_id is not None

            remaining = await batch.remove(submitted.id, removed.id)

            assert [item.project_name for item in remaining.items] == ["Project 2"]
            assert synthesis.get_job(removed.job_id).status is JobStatus.CANCELLED
            assert provider.calls == []
        finally:
            await synthesis.stop()

    asyncio.run(scenario())


def test_pause_after_current_survives_until_explicit_resume(tmp_path) -> None:
    async def scenario() -> None:
        provider = SlowRecordingProvider()
        settings = _settings(tmp_path)
        synthesis = SynthesisService(settings=settings, providers=ProviderRegistry([provider]))
        batch = BatchQueueService(
            store=BatchQueueStore(settings.database_path),
            synthesis=synthesis,
            poll_interval_seconds=0.01,
        )
        await synthesis.start()
        await batch.start()
        try:
            submitted = await batch.submit(
                "Pause scopes", [_draft(1, "First slow item."), _draft(2, "Second item.")]
            )
            await _status(batch, submitted.id, BatchQueueStatus.RUNNING)
            paused_request = await batch.pause_remaining(submitted.id)
            assert paused_request.pause_after_current is True
            paused = await _status(batch, submitted.id, BatchQueueStatus.PAUSED)
            assert [item.status for item in paused.items] == [
                BatchItemStatus.COMPLETED,
                BatchItemStatus.READY,
            ]
            assert provider.calls == ["First slow item."]

            resumed = await batch.resume(submitted.id)
            assert resumed.status in {BatchQueueStatus.QUEUED, BatchQueueStatus.RUNNING}
            finished = await _terminal(batch, submitted.id)
            assert [item.status for item in finished.items] == [
                BatchItemStatus.COMPLETED,
                BatchItemStatus.COMPLETED,
            ]
        finally:
            await batch.stop()
            await synthesis.stop()

    asyncio.run(scenario())


def test_cancel_current_continues_and_cancel_remaining_preserves_current(tmp_path) -> None:
    async def scenario() -> None:
        provider = SlowRecordingProvider()
        settings = _settings(tmp_path)
        synthesis = SynthesisService(settings=settings, providers=ProviderRegistry([provider]))
        batch = BatchQueueService(
            store=BatchQueueStore(settings.database_path),
            synthesis=synthesis,
            poll_interval_seconds=0.01,
        )
        await synthesis.start()
        await batch.start()
        try:
            first_queue = await batch.submit(
                "Cancel current", [_draft(1, "Cancel this."), _draft(2, "Keep this.")]
            )
            await _status(batch, first_queue.id, BatchQueueStatus.RUNNING)
            await batch.cancel_current(first_queue.id)
            first_finished = await _terminal(batch, first_queue.id)
            assert [item.status for item in first_finished.items] == [
                BatchItemStatus.CANCELLED,
                BatchItemStatus.COMPLETED,
            ]

            second_queue = await batch.submit(
                "Cancel remaining", [_draft(3, "Keep current."), _draft(4, "Cancel pending.")]
            )
            await _status(batch, second_queue.id, BatchQueueStatus.RUNNING)
            await batch.cancel_remaining(second_queue.id)
            second_finished = await _terminal(batch, second_queue.id)
            assert [item.status for item in second_finished.items] == [
                BatchItemStatus.COMPLETED,
                BatchItemStatus.CANCELLED,
            ]
        finally:
            await batch.stop()
            await synthesis.stop()

    asyncio.run(scenario())
