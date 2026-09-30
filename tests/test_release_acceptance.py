from __future__ import annotations

import asyncio
import io
import os
import shutil
import struct
import time
import uuid
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from splicr.api import create_app
from splicr.config import Settings
from splicr.domain import AudioChunk, ChunkStatus, JobStatus, SynthesisOptions
from splicr.providers import ProviderRegistry
from splicr.service import SynthesisService
from splicr.storage import LocalJobStorage
from tests.fakes import RecordingProvider


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        chunk_max_bytes=100,
        chunk_max_words=2,
        pacing_seconds=0,
        max_attempts=2,
        backoff_base_seconds=0,
        backoff_max_seconds=0,
        backoff_jitter_seconds=0,
    )


async def _terminal(service: SynthesisService, job_id: str):
    async def poll():
        while True:
            job = service.get_job(job_id)
            if job.status in {JobStatus.COMPLETED, JobStatus.PAUSED, JobStatus.CANCELLED}:
                return job
            await asyncio.sleep(0.01)

    return await asyncio.wait_for(poll(), timeout=5)


class BoundaryProvider(RecordingProvider):
    """Blocks before its next billable call after a configured checkpoint count."""

    def __init__(self, complete_before_block: int | None) -> None:
        super().__init__()
        self.complete_before_block = complete_before_block
        self.blocked = asyncio.Event()
        self._release = asyncio.Event()

    async def synthesize(self, text: str, options: SynthesisOptions) -> AudioChunk:
        if self.complete_before_block is not None and len(self.calls) >= self.complete_before_block:
            self.blocked.set()
            await self._release.wait()
        self.call_times.append(time.monotonic())
        self.calls.append(text)
        self.options.append(options)
        self.call_counts[text] += 1
        segment = int(text.rsplit(" ", 1)[1])
        return AudioChunk(pcm=struct.pack("<h", segment + 1) * 4)


@pytest.mark.release_acceptance
def test_long_job_survives_repeated_boundary_termination_without_duplicate_chunks(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        settings = _settings(tmp_path)
        job_id: str | None = None
        all_calls: list[str] = []
        completed = 0
        for _ in range(3):
            provider = BoundaryProvider(complete_before_block=2)
            service = SynthesisService(
                settings=settings,
                providers=ProviderRegistry([provider]),
            )
            await service.start()
            if job_id is None:
                submitted = await service.submit(
                    text="\n\n".join(f"segment {index}" for index in range(8)),
                    provider_name="fake",
                )
                job_id = submitted.id
            await asyncio.wait_for(provider.blocked.wait(), timeout=3)
            completed += 2
            chunks = service.store.chunks_for_job(job_id)
            assert sum(chunk.status is ChunkStatus.COMPLETED for chunk in chunks) == completed
            all_calls.extend(provider.calls)
            await service.stop()

        provider = BoundaryProvider(complete_before_block=None)
        service = SynthesisService(
            settings=settings,
            providers=ProviderRegistry([provider]),
        )
        await service.start()
        try:
            assert job_id is not None
            finished = await _terminal(service, job_id)
            all_calls.extend(provider.calls)
            assert finished.status is JobStatus.COMPLETED
            assert all_calls == [f"segment {index}" for index in range(8)]
            with wave.open(str(service.output_path(job_id)), "rb") as output:
                pcm = output.readframes(output.getnframes())
            values = struct.unpack(f"<{len(pcm) // 2}h", pcm)
            assert [values[index] for index in range(0, len(values), 4)] == list(range(1, 9))
        finally:
            await service.stop()

    asyncio.run(scenario())


@pytest.mark.release_acceptance
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is not installed")
def test_near_limit_audio_upload_streams_to_disk_and_output_supports_ranges(
    tmp_path: Path,
) -> None:
    source = io.BytesIO()
    with wave.open(source, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        # Keep the payload above the 1 MiB upload read size without making the
        # real-FFmpeg acceptance test synthesize a long-duration fixture.
        audio.setframerate(192_000)
        audio.writeframes(b"\0\0" * 600_000)
    payload = source.getvalue()
    settings = Settings(
        data_dir=tmp_path,
        chunk_max_bytes=100,
        chunk_max_words=2,
        pacing_seconds=0,
        max_audio_upload_bytes=len(payload) + 128,
    )
    synthesis = SynthesisService(
        settings=settings,
        providers=ProviderRegistry([RecordingProvider()]),
    )

    with TestClient(create_app(settings=settings, service=synthesis)) as client:
        uploaded = client.post(
            "/v1/studio/conversions/inputs",
            files={"file": ("near-limit.wav", payload, "audio/wav")},
        )
        assert uploaded.status_code == 201
        conversion = client.post(
            "/v1/studio/conversions/jobs",
            json={
                "input_id": uploaded.json()["id"],
                "spec": {"output_format": "wav"},
            },
        )
        assert conversion.status_code == 202
        conversion_id = conversion.json()["id"]
        for _ in range(500):
            current = client.get(f"/v1/studio/conversions/jobs/{conversion_id}").json()
            if current["status"] == "completed":
                break
            time.sleep(0.01)
        else:
            raise AssertionError("near-limit conversion did not complete")

        partial = client.get(current["output_url"], headers={"Range": "bytes=0-1023"})
        assert partial.status_code == 206
        assert len(partial.content) == 1024
        assert partial.headers["content-range"].startswith("bytes 0-1023/")

        rejected = client.post(
            "/v1/studio/conversions/inputs",
            files={
                "file": (
                    "over-limit.wav",
                    payload + b"x" * 129,
                    "audio/wav",
                )
            },
        )
        assert rejected.status_code == 413

    upload_root = tmp_path / "studio" / "conversion-inputs"
    assert not list(upload_root.glob(".upload-*.part"))


@pytest.mark.release_acceptance
def test_multi_gigabyte_sparse_output_is_range_read_without_full_body(tmp_path: Path) -> None:
    pcm_bytes = 3_900_000_000
    settings = Settings(
        data_dir=tmp_path,
        pacing_seconds=0,
        max_output_pcm_bytes=4_000_000_000,
    )
    synthesis = SynthesisService(
        settings=settings,
        providers=ProviderRegistry([RecordingProvider()]),
    )
    synthesis.store.initialize()
    job_id = uuid.uuid4().hex
    synthesis.store.create_job_with_chunks(
        job_id=job_id,
        provider="fake",
        model="fake-model",
        voice="fake-voice",
        instructions=None,
        chunks=["A sparse release-acceptance output."],
    )
    synthesis.store.mark_job_running(job_id)
    output = synthesis.storage.output_path(job_id)
    output.parent.mkdir(parents=True, exist_ok=True)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        pcm_bytes + 36,
        b"WAVE",
        b"fmt ",
        16,
        1,
        1,
        24_000,
        48_000,
        2,
        16,
        b"data",
        pcm_bytes,
    )
    with output.open("wb") as stream:
        stream.write(header)
        stream.truncate(len(header) + pcm_bytes)
    synthesis.store.mark_job_completed(job_id, str(output.resolve()))

    total_bytes = len(header) + pcm_bytes
    ranges = (
        (0, 1023),
        (total_bytes // 2, total_bytes // 2 + 1023),
        (total_bytes - 1024, total_bytes - 1),
    )
    with TestClient(create_app(settings=settings, service=synthesis)) as client:
        for start, end in ranges:
            response = client.get(
                f"/v1/speech/jobs/{job_id}/audio",
                headers={"Range": f"bytes={start}-{end}"},
            )
            assert response.status_code == 206
            assert len(response.content) == 1024
            assert response.headers["content-range"] == f"bytes {start}-{end}/{total_bytes}"
            assert response.headers["content-length"] == "1024"

    assert output.stat().st_size == total_bytes


class FinalReplaceFailureStorage(LocalJobStorage):
    def _assemble_wav_to(self, output, chunk_paths, audio_format):
        original_replace = os.replace

        def fail_replace(_source, _target):
            raise OSError("simulated termination during final replacement")

        os.replace = fail_replace
        try:
            return super()._assemble_wav_to(output, chunk_paths, audio_format)
        finally:
            os.replace = original_replace


@pytest.mark.release_acceptance
def test_final_assembly_interruption_never_publishes_a_partial_result(tmp_path: Path) -> None:
    async def scenario() -> None:
        settings = _settings(tmp_path)
        storage = FinalReplaceFailureStorage(settings.jobs_dir)
        service = SynthesisService(
            settings=settings,
            providers=ProviderRegistry([RecordingProvider()]),
            storage=storage,
        )
        await service.start()
        try:
            submitted = await service.submit(text="one segment", provider_name="fake")
            paused = await _terminal(service, submitted.id)
            assert paused.status is JobStatus.PAUSED
            assert paused.output_path is None
            assert not storage.output_path(submitted.id).exists()
            assert not list(storage.job_dir(submitted.id).glob("*.tmp"))
        finally:
            await service.stop()

    asyncio.run(scenario())
