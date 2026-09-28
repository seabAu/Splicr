from __future__ import annotations

import asyncio
import wave

import pytest

from splicr.config import Settings
from splicr.domain import JobStatus
from splicr.providers import ProviderRegistry
from splicr.service import SynthesisService
from splicr.studio.timeline import build_job_timeline, wav_span_bytes

from .fakes import RecordingProvider


def _settings(tmp_path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        chunk_max_bytes=10_000,
        chunk_max_words=2,
        pacing_seconds=0,
        max_attempts=1,
    )


async def _wait_for_completion(service: SynthesisService, job_id: str):
    async def poll():
        while True:
            job = service.get_job(job_id)
            if job.status is JobStatus.COMPLETED:
                return job
            await asyncio.sleep(0.01)

    return await asyncio.wait_for(poll(), timeout=3)


def test_timeline_uses_exact_checkpoint_durations_and_waveform(tmp_path) -> None:
    async def scenario() -> None:
        provider = RecordingProvider()
        service = SynthesisService(
            settings=_settings(tmp_path), providers=ProviderRegistry([provider])
        )
        await service.start()
        try:
            job = await service.submit(
                text="one two\n\nthree four\n\nfive six",
                provider_name="fake",
            )
            finished = await _wait_for_completion(service, job.id)
            timeline = build_job_timeline(
                service.store,
                service.storage,
                finished.id,
                waveform_buckets=5,
            )

            frame_duration = 4 / 24_000
            assert timeline.status is JobStatus.COMPLETED
            assert timeline.duration == pytest.approx(frame_duration * 3)
            assert [segment.start for segment in timeline.segments] == pytest.approx(
                [0, frame_duration, frame_duration * 2]
            )
            assert [segment.end for segment in timeline.segments] == pytest.approx(
                [frame_duration, frame_duration * 2, frame_duration * 3]
            )
            assert [segment.text for segment in timeline.segments] == [
                "one two",
                "three four",
                "five six",
            ]
            assert timeline.audio_url == f"/v1/speech/jobs/{job.id}/audio"
            assert timeline.waveform
            assert all(0 <= value <= 1 for value in timeline.waveform)

            selected = wav_span_bytes(
                service.output_path(job.id),
                timeline.segments[0].start,
                timeline.segments[1].end,
            )
            selected_path = tmp_path / "selected.wav"
            selected_path.write_bytes(selected)
            with wave.open(str(selected_path), "rb") as audio:
                assert audio.getnchannels() == 1
                assert audio.getsampwidth() == 2
                assert audio.getframerate() == 24_000
                assert audio.getnframes() == 8
        finally:
            await service.stop()

    asyncio.run(scenario())


def test_timeline_rejects_a_missing_checkpoint(tmp_path) -> None:
    async def scenario() -> None:
        service = SynthesisService(
            settings=_settings(tmp_path),
            providers=ProviderRegistry([RecordingProvider()]),
        )
        await service.start()
        try:
            job = await service.submit(text="one two", provider_name="fake")
            await _wait_for_completion(service, job.id)
            service.storage.chunk_path(job.id, 0).unlink()

            with pytest.raises(ValueError, match="missing"):
                build_job_timeline(service.store, service.storage, job.id)
        finally:
            await service.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("start", "end", "message"),
    [(-1, 1, "positive duration"), (1, 1, "positive duration"), (3, 4, "outside")],
)
def test_wav_span_rejects_invalid_ranges(tmp_path, start, end, message) -> None:
    path = tmp_path / "source.wav"
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24_000)
        audio.writeframes(b"\0\0" * 4)

    with pytest.raises(ValueError, match=message):
        wav_span_bytes(path, start, end)
