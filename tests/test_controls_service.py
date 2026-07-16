from __future__ import annotations

import asyncio

from splicr.config import Settings
from splicr.domain import (
    DeliveryControls,
    JobStatus,
    NonverbalFrequency,
    SpeechPace,
    TonePreset,
    VocalStyle,
)
from splicr.providers import ProviderRegistry
from splicr.service import SynthesisService

from .fakes import RecordingProvider


async def _terminal(service: SynthesisService, job_id: str):
    for _ in range(300):
        job = service.get_job(job_id)
        if job.status in {JobStatus.COMPLETED, JobStatus.PAUSED, JobStatus.CANCELLED}:
            return job
        await asyncio.sleep(0.01)
    raise AssertionError("job did not finish")


def test_worker_reconstructs_persisted_delivery_controls_for_every_chunk(tmp_path) -> None:
    async def scenario() -> None:
        provider = RecordingProvider()
        settings = Settings(
            data_dir=tmp_path,
            chunk_max_bytes=10_000,
            chunk_max_words=2,
            pacing_seconds=0,
            backoff_base_seconds=0,
            backoff_max_seconds=0,
            backoff_jitter_seconds=0,
        )
        service = SynthesisService(settings=settings, providers=ProviderRegistry([provider]))
        controls = DeliveryControls(
            tone=TonePreset.EMPATHETIC,
            pace=SpeechPace.SLOW,
            vocal_style=VocalStyle.AUDIOBOOK,
        )
        await service.start()
        try:
            submitted = await service.submit(
                text="one two. three four. five six.",
                provider_name="fake",
                controls=controls,
            )
            finished = await _terminal(service, submitted.id)
            assert finished.status is JobStatus.COMPLETED
            assert len(provider.options) == 3
            assert all(options.controls == controls for options in provider.options)
            assert service.get_job(submitted.id).controls == controls
        finally:
            await service.stop()

    asyncio.run(scenario())


def test_nonverbal_cue_plan_is_persisted_in_synthesis_chunks(tmp_path) -> None:
    async def scenario() -> None:
        provider = RecordingProvider()
        settings = Settings(
            data_dir=tmp_path,
            chunk_max_bytes=10_000,
            chunk_max_words=10_000,
            pacing_seconds=0,
            backoff_base_seconds=0,
            backoff_max_seconds=0,
            backoff_jitter_seconds=0,
        )
        service = SynthesisService(settings=settings, providers=ProviderRegistry([provider]))
        await service.start()
        try:
            submitted = await service.submit(
                text="First sentence. Second sentence. Third sentence.",
                provider_name="fake",
                controls=DeliveryControls(nonverbal_frequency=NonverbalFrequency.VERY_FREQUENT),
            )
            finished = await _terminal(service, submitted.id)
            assert finished.status is JobStatus.COMPLETED
            stored_text = " ".join(
                chunk.text for chunk in service.store.chunks_for_job(submitted.id)
            )
            assert "[" in stored_text and "]" in stored_text
            assert provider.calls == [stored_text]
        finally:
            await service.stop()

    asyncio.run(scenario())
