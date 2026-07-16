from __future__ import annotations

import asyncio
import struct
import wave

from splicr.config import Settings
from splicr.domain import JobStatus
from splicr.providers import ProviderRegistry
from splicr.service import SynthesisService
from splicr.storage import LocalJobStorage
from tests.fakes import RecordingProvider


def _settings(tmp_path, **overrides) -> Settings:
    values = {
        "data_dir": tmp_path,
        "chunk_max_bytes": 10_000,
        "chunk_max_words": 2,
        "pacing_seconds": 0,
        "max_attempts": 3,
        "backoff_base_seconds": 0,
        "backoff_max_seconds": 0,
        "backoff_jitter_seconds": 0,
    }
    values.update(overrides)
    return Settings(**values)


async def _wait_for_terminal(service: SynthesisService, job_id: str):
    async def poll():
        while True:
            job = service.get_job(job_id)
            if job.status in {JobStatus.COMPLETED, JobStatus.PAUSED, JobStatus.CANCELLED}:
                return job
            await asyncio.sleep(0.01)

    return await asyncio.wait_for(poll(), timeout=3)


def test_service_preserves_chunk_order_and_builds_wav(tmp_path) -> None:
    async def scenario() -> None:
        provider = RecordingProvider()
        service = SynthesisService(
            settings=_settings(tmp_path), providers=ProviderRegistry([provider])
        )
        await service.start()
        try:
            submitted = await service.submit(
                text="one two\n\nthree four\n\nfive six", provider_name="fake"
            )
            finished = await _wait_for_terminal(service, submitted.id)
            assert finished.status is JobStatus.COMPLETED
            assert provider.calls == ["one two", "three four", "five six"]
            with wave.open(str(service.output_path(submitted.id)), "rb") as wav_file:
                assert wav_file.getnchannels() == 1
                assert wav_file.getframerate() == 24_000
                assert wav_file.getnframes() == 12
        finally:
            await service.stop()

    asyncio.run(scenario())


def test_transient_failure_retries_same_chunk(tmp_path) -> None:
    async def scenario() -> None:
        provider = RecordingProvider(transient_failures=2)
        service = SynthesisService(
            settings=_settings(tmp_path, chunk_max_words=100),
            providers=ProviderRegistry([provider]),
        )
        await service.start()
        try:
            submitted = await service.submit(text="retry me", provider_name="fake")
            finished = await _wait_for_terminal(service, submitted.id)
            assert finished.status is JobStatus.COMPLETED
            assert provider.calls == ["retry me", "retry me", "retry me"]
            assert service.store.chunks_for_job(submitted.id)[0].attempts == 3
        finally:
            await service.stop()

    asyncio.run(scenario())


def test_retry_resumes_after_completed_checkpoint(tmp_path) -> None:
    async def scenario() -> None:
        provider = RecordingProvider(fail_text="three")
        service = SynthesisService(
            settings=_settings(tmp_path), providers=ProviderRegistry([provider])
        )
        await service.start()
        try:
            submitted = await service.submit(text="one two\n\nthree four", provider_name="fake")
            failed = await _wait_for_terminal(service, submitted.id)
            assert failed.status is JobStatus.PAUSED
            assert provider.call_counts["one two"] == 1
            assert provider.call_counts["three four"] == 1

            provider.fail_text = None
            await service.retry(submitted.id)
            completed = await _wait_for_terminal(service, submitted.id)
            assert completed.status is JobStatus.COMPLETED
            assert provider.call_counts["one two"] == 1
            assert provider.call_counts["three four"] == 2
        finally:
            await service.stop()

    asyncio.run(scenario())


def test_restart_reuses_atomic_checkpoint_written_before_database_update(tmp_path) -> None:
    async def scenario() -> None:
        provider = RecordingProvider()
        settings = _settings(tmp_path, chunk_max_words=100)
        service = SynthesisService(settings=settings, providers=ProviderRegistry([provider]))
        service.store.initialize()
        service.storage.initialize()
        service.store.create_job(
            job_id="checkpoint-job",
            provider="fake",
            model="fake-model",
            voice="fake-voice",
            instructions=None,
        )
        service.store.add_chunks("checkpoint-job", ["already synthesized"])
        service.storage.write_source("checkpoint-job", "already synthesized")
        pcm = struct.pack("<hh", 7, 8)
        service.storage.write_chunk("checkpoint-job", 0, pcm)

        await service.start()
        try:
            finished = await _wait_for_terminal(service, "checkpoint-job")
            assert finished.status is JobStatus.COMPLETED
            assert provider.calls == []
            with wave.open(str(service.output_path("checkpoint-job")), "rb") as wav_file:
                assert wav_file.readframes(2) == pcm
        finally:
            await service.stop()

    asyncio.run(scenario())


def test_local_checkpoint_failure_does_not_repeat_billable_provider_call(tmp_path) -> None:
    class FailingStorage(LocalJobStorage):
        def write_chunk(self, *args, **kwargs):
            raise OSError("disk full")

    async def scenario() -> None:
        provider = RecordingProvider()
        settings = _settings(tmp_path, chunk_max_words=100)
        service = SynthesisService(
            settings=settings,
            providers=ProviderRegistry([provider]),
            storage=FailingStorage(settings.jobs_dir),
        )
        await service.start()
        try:
            submitted = await service.submit(text="one request", provider_name="fake")
            failed = await _wait_for_terminal(service, submitted.id)
            assert failed.status is JobStatus.PAUSED
            assert provider.calls == ["one request"]
            assert "checkpoint" in (failed.error or "")
        finally:
            await service.stop()

    asyncio.run(scenario())


def test_corrupt_completed_checkpoint_is_resynthesized(tmp_path) -> None:
    async def scenario() -> None:
        provider = RecordingProvider()
        settings = _settings(tmp_path, chunk_max_words=100)
        service = SynthesisService(settings=settings, providers=ProviderRegistry([provider]))
        service.store.initialize()
        service.storage.initialize()
        service.store.create_job(
            job_id="corrupt-job",
            provider="fake",
            model="fake-model",
            voice="fake-voice",
            instructions=None,
        )
        service.store.add_chunks("corrupt-job", ["replace this checkpoint"])
        checkpoint = service.storage.chunk_path("corrupt-job", 0)
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        checkpoint.write_bytes(b"x")
        service.store.mark_chunk_completed("corrupt-job", 0, str(checkpoint.resolve()))

        await service.start()
        try:
            finished = await _wait_for_terminal(service, "corrupt-job")
            assert finished.status is JobStatus.COMPLETED
            assert provider.calls == ["replace this checkpoint"]
        finally:
            await service.stop()

    asyncio.run(scenario())


def test_pacing_applies_between_separate_single_chunk_jobs(tmp_path) -> None:
    async def scenario() -> None:
        provider = RecordingProvider()
        service = SynthesisService(
            settings=_settings(tmp_path, chunk_max_words=100, pacing_seconds=0.05),
            providers=ProviderRegistry([provider]),
        )
        await service.start()
        try:
            first = await service.submit(text="first", provider_name="fake")
            second = await service.submit(text="second", provider_name="fake")
            assert (await _wait_for_terminal(service, first.id)).status is JobStatus.COMPLETED
            assert (await _wait_for_terminal(service, second.id)).status is JobStatus.COMPLETED
            assert len(provider.call_times) == 2
            assert provider.call_times[1] - provider.call_times[0] >= 0.04
        finally:
            await service.stop()

    asyncio.run(scenario())


def test_provider_interval_overrides_the_global_request_pacing(tmp_path) -> None:
    async def scenario() -> None:
        provider = RecordingProvider(minimum_request_interval_seconds=0)
        service = SynthesisService(
            settings=_settings(tmp_path, chunk_max_words=100, pacing_seconds=0.5),
            providers=ProviderRegistry([provider]),
        )
        await service.start()
        try:
            first = await service.submit(text="first", provider_name="fake")
            second = await service.submit(text="second", provider_name="fake")
            assert (await _wait_for_terminal(service, first.id)).status is JobStatus.COMPLETED
            assert (await _wait_for_terminal(service, second.id)).status is JobStatus.COMPLETED
            assert len(provider.call_times) == 2
            assert provider.call_times[1] - provider.call_times[0] < 0.25
        finally:
            await service.stop()

    asyncio.run(scenario())


def test_retry_after_is_a_minimum_not_capped_by_local_backoff(tmp_path) -> None:
    service = SynthesisService(
        settings=_settings(
            tmp_path,
            backoff_base_seconds=5,
            backoff_max_seconds=60,
            backoff_jitter_seconds=0,
        ),
        providers=ProviderRegistry([RecordingProvider()]),
    )

    assert service._retry_delay(attempt=1, retry_after=120) == 120


def test_restart_consumes_only_remaining_automatic_attempt_budget(tmp_path) -> None:
    async def scenario() -> None:
        provider = RecordingProvider()
        settings = _settings(tmp_path, chunk_max_words=100, max_attempts=3)
        service = SynthesisService(settings=settings, providers=ProviderRegistry([provider]))
        service.store.initialize()
        service.storage.initialize()
        service.store.create_job(
            job_id="attempt-job",
            provider="fake",
            model="fake-model",
            voice="fake-voice",
            instructions=None,
        )
        service.store.add_chunks("attempt-job", ["last allowed attempt"])
        service.store.mark_chunk_running("attempt-job", 0)
        service.store.mark_chunk_pending("attempt-job", 0, "crash one")
        service.store.mark_chunk_running("attempt-job", 0)
        service.store.mark_chunk_pending("attempt-job", 0, "crash two")

        await service.start()
        try:
            finished = await _wait_for_terminal(service, "attempt-job")
            assert finished.status is JobStatus.COMPLETED
            assert provider.calls == ["last allowed attempt"]
            assert service.store.chunks_for_job("attempt-job")[0].attempts == 3
        finally:
            await service.stop()

    asyncio.run(scenario())


def test_missing_persisted_provider_pauses_job_with_error(tmp_path) -> None:
    async def scenario() -> None:
        settings = _settings(tmp_path, chunk_max_words=100)
        service = SynthesisService(
            settings=settings,
            providers=ProviderRegistry([RecordingProvider()]),
        )
        service.store.initialize()
        service.storage.initialize()
        service.store.create_job(
            job_id="removed-provider-job",
            provider="removed",
            model="old-model",
            voice="old-voice",
            instructions=None,
        )
        service.store.add_chunks("removed-provider-job", ["cannot run"])

        await service.start()
        try:
            failed = await _wait_for_terminal(service, "removed-provider-job")
            assert failed.status is JobStatus.PAUSED
            assert "unknown TTS provider" in (failed.error or "")
        finally:
            await service.stop()

    asyncio.run(scenario())


def test_pcm_size_guard_fails_before_wav_overflow(tmp_path) -> None:
    async def scenario() -> None:
        provider = RecordingProvider()
        service = SynthesisService(
            settings=_settings(tmp_path, chunk_max_words=100, max_output_pcm_bytes=4),
            providers=ProviderRegistry([provider]),
        )
        await service.start()
        try:
            submitted = await service.submit(text="too much audio", provider_name="fake")
            failed = await _wait_for_terminal(service, submitted.id)
            assert failed.status is JobStatus.PAUSED
            assert "PCM/WAV size limit" in (failed.error or "")
        finally:
            await service.stop()

    asyncio.run(scenario())


def test_restart_rejects_aggregate_completed_checkpoints_over_pcm_limit(tmp_path) -> None:
    async def scenario() -> None:
        provider = RecordingProvider()
        service = SynthesisService(
            settings=_settings(tmp_path, chunk_max_words=100, max_output_pcm_bytes=6),
            providers=ProviderRegistry([provider]),
        )
        service.store.initialize()
        service.storage.initialize()
        service.store.create_job(
            job_id="oversized-completed-job",
            provider="fake",
            model="fake-model",
            voice="fake-voice",
            instructions=None,
        )
        service.store.add_chunks("oversized-completed-job", ["first", "second"])
        for index in range(2):
            checkpoint = service.storage.write_chunk(
                "oversized-completed-job", index, struct.pack("<hh", index, index)
            )
            service.store.mark_chunk_completed(
                "oversized-completed-job", index, str(checkpoint.resolve())
            )

        await service.start()
        try:
            failed = await _wait_for_terminal(service, "oversized-completed-job")
            assert failed.status is JobStatus.PAUSED
            assert "PCM/WAV size limit" in (failed.error or "")
            assert provider.calls == []
            assert not service.storage.output_path("oversized-completed-job").exists()
        finally:
            await service.stop()

    asyncio.run(scenario())


def test_final_checkpoint_budget_check_catches_growth_before_assembly(tmp_path) -> None:
    class GrowingCheckpointStorage(LocalJobStorage):
        def __init__(self, root) -> None:
            super().__init__(root)
            self.validation_count = 0

        def validate_chunk(self, path, *args, **kwargs) -> None:
            self.validation_count += 1
            if self.validation_count == 2:
                path.write_bytes(path.read_bytes() + struct.pack("<hh", 3, 4))
            super().validate_chunk(path, *args, **kwargs)

    async def scenario() -> None:
        provider = RecordingProvider()
        settings = _settings(tmp_path, chunk_max_words=100, max_output_pcm_bytes=4)
        storage = GrowingCheckpointStorage(settings.jobs_dir)
        service = SynthesisService(
            settings=settings,
            providers=ProviderRegistry([provider]),
            storage=storage,
        )
        service.store.initialize()
        service.storage.initialize()
        service.store.create_job(
            job_id="growing-checkpoint-job",
            provider="fake",
            model="fake-model",
            voice="fake-voice",
            instructions=None,
        )
        service.store.add_chunks("growing-checkpoint-job", ["already synthesized"])
        service.storage.write_chunk("growing-checkpoint-job", 0, struct.pack("<hh", 1, 2))

        await service.start()
        try:
            failed = await _wait_for_terminal(service, "growing-checkpoint-job")
            assert failed.status is JobStatus.PAUSED
            assert "PCM/WAV size limit" in (failed.error or "")
            assert provider.calls == []
            assert not service.storage.output_path("growing-checkpoint-job").exists()
        finally:
            await service.stop()

    asyncio.run(scenario())
