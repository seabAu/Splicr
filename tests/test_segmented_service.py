from __future__ import annotations

import asyncio
import struct
import wave

from splicr.config import Settings
from splicr.domain import JobStatus, SynthesisSegment
from splicr.providers import ProviderRegistry
from splicr.service import SEGMENT_OPTIONS_VARIABLE, SynthesisService
from tests.fakes import RecordingProvider


async def _wait_for_terminal(service: SynthesisService, job_id: str):
    async def poll():
        while True:
            job = service.get_job(job_id)
            if job.status in {
                JobStatus.COMPLETED,
                JobStatus.PAUSED,
                JobStatus.CANCELLED,
            }:
                return job
            await asyncio.sleep(0.01)

    return await asyncio.wait_for(poll(), timeout=3)


def _settings(tmp_path, *, chunk_max_words: int = 100) -> Settings:
    return Settings(
        data_dir=tmp_path,
        chunk_max_bytes=10_000,
        chunk_max_words=chunk_max_words,
        pacing_seconds=0,
        max_attempts=1,
        backoff_base_seconds=0,
        backoff_max_seconds=0,
        backoff_jitter_seconds=0,
    )


def test_segmented_job_groups_equal_voice_state_and_assembles_in_source_order(tmp_path) -> None:
    async def scenario() -> None:
        provider = RecordingProvider()
        service = SynthesisService(
            settings=_settings(tmp_path),
            providers=ProviderRegistry([provider]),
        )
        await service.start()
        try:
            submitted = await service.submit_segments(
                provider_name="fake",
                source_text="A source document retained separately from its dialogue.",
                segments=(
                    SynthesisSegment(text="First host opens.", voice="voice-alpha", speaker="Person1"),
                    SynthesisSegment(text="Second host replies.", voice="voice-beta", speaker="Person2"),
                    SynthesisSegment(text="First host continues.", voice="voice-alpha", speaker="Person1"),
                ),
            )
            finished = await _wait_for_terminal(service, submitted.id)
        finally:
            await service.stop()

        assert finished.status is JobStatus.COMPLETED
        assert provider.calls == [
            "First host opens.",
            "First host continues.",
            "Second host replies.",
        ]
        assert [options.voice for options in provider.options] == [
            "voice-alpha",
            "voice-alpha",
            "voice-beta",
        ]
        assert [chunk.text for chunk in service.store.chunks_for_job(submitted.id)] == [
            "First host opens.",
            "Second host replies.",
            "First host continues.",
        ]

        persisted = service.get_job(submitted.id).variables[SEGMENT_OPTIONS_VARIABLE]
        assert isinstance(persisted, list)
        assert [entry["speaker"] for entry in persisted] == [
            "Person1",
            "Person2",
            "Person1",
        ]
        assert [entry["segment_index"] for entry in persisted] == [0, 1, 2]

        with wave.open(str(service.output_path(submitted.id)), "rb") as wav_file:
            samples = struct.unpack("<12h", wav_file.readframes(12))
        assert samples == (1,) * 4 + (3,) * 4 + (2,) * 4
        assert service.storage.read_source(submitted.id) == (
            "A source document retained separately from its dialogue."
        )

    asyncio.run(scenario())


def test_segment_voice_options_expand_with_provider_chunking(tmp_path) -> None:
    async def scenario() -> None:
        provider = RecordingProvider()
        service = SynthesisService(
            settings=_settings(tmp_path, chunk_max_words=2),
            providers=ProviderRegistry([provider]),
        )
        await service.start()
        try:
            submitted = await service.submit_segments(
                provider_name="fake",
                segments=(
                    SynthesisSegment(
                        text="one two three four",
                        voice="voice-alpha",
                        speaker="Person1",
                    ),
                    SynthesisSegment(text="five six", voice="voice-beta", speaker="Person2"),
                ),
            )
            finished = await _wait_for_terminal(service, submitted.id)
        finally:
            await service.stop()

        assert finished.status is JobStatus.COMPLETED
        chunks = service.store.chunks_for_job(submitted.id)
        assert [chunk.text for chunk in chunks] == ["one two", "three four", "five six"]
        persisted = service.get_job(submitted.id).variables[SEGMENT_OPTIONS_VARIABLE]
        assert isinstance(persisted, list)
        assert [entry["segment_index"] for entry in persisted] == [0, 0, 1]
        assert [entry["voice"] for entry in persisted] == [
            "voice-alpha",
            "voice-alpha",
            "voice-beta",
        ]

    asyncio.run(scenario())


def test_segmented_job_resume_keeps_completed_voice_checkpoints(tmp_path) -> None:
    async def scenario() -> None:
        provider = RecordingProvider(fail_text="reply")
        service = SynthesisService(
            settings=_settings(tmp_path),
            providers=ProviderRegistry([provider]),
        )
        await service.start()
        try:
            submitted = await service.submit_segments(
                provider_name="fake",
                segments=(
                    SynthesisSegment(text="opening", voice="voice-alpha", speaker="Person1"),
                    SynthesisSegment(text="reply", voice="voice-beta", speaker="Person2"),
                ),
            )
            paused = await _wait_for_terminal(service, submitted.id)
            assert paused.status is JobStatus.PAUSED
            provider.fail_text = None
            await service.retry(submitted.id)
            finished = await _wait_for_terminal(service, submitted.id)
        finally:
            await service.stop()

        assert finished.status is JobStatus.COMPLETED
        assert provider.calls == ["opening", "reply", "reply"]
        assert [options.voice for options in provider.options] == [
            "voice-alpha",
            "voice-beta",
            "voice-beta",
        ]
        assert provider.call_counts["opening"] == 1

    asyncio.run(scenario())
