from __future__ import annotations

import asyncio

import pytest

from splicr.config import Settings
from splicr.domain import (
    ControlDefinition,
    ControlValueType,
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
                variables={"seed": 17, "locale": "en-US"},
            )
            finished = await _terminal(service, submitted.id)
            assert finished.status is JobStatus.COMPLETED
            assert len(provider.options) == 3
            assert all(options.controls == controls for options in provider.options)
            assert all(
                options.variables == {"seed": 17, "locale": "en-US"} for options in provider.options
            )
            persisted = service.get_job(submitted.id)
            assert persisted.controls == controls
            assert persisted.variables == {"seed": 17, "locale": "en-US"}
        finally:
            await service.stop()

    asyncio.run(scenario())


def test_advanced_control_defaults_are_frozen_and_invalid_values_fail_before_queueing(
    tmp_path,
) -> None:
    async def scenario() -> None:
        provider = RecordingProvider(
            control_definitions=(
                ControlDefinition(
                    key="seed",
                    value_type=ControlValueType.INTEGER,
                    default=17,
                    minimum=0,
                    maximum=100,
                ),
            ),
            allows_undeclared_variables=False,
        )
        settings = Settings(data_dir=tmp_path, pacing_seconds=0)
        service = SynthesisService(settings=settings, providers=ProviderRegistry([provider]))
        await service.start()
        try:
            submitted = await service.submit(text="A short test.", provider_name="fake")
            assert submitted.variables == {"seed": 17}

            with pytest.raises(ValueError, match="unknown advanced control"):
                await service.submit(
                    text="A rejected test.",
                    provider_name="fake",
                    variables={"mystery": True},
                )
            with pytest.raises(ValueError, match="at most 100"):
                service.preview(
                    text="A rejected preview.",
                    provider_name="fake",
                    variables={"seed": 101},
                )
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
