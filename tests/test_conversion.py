from __future__ import annotations

import asyncio
import math
import shutil
import struct
import time
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from splicr.api import create_app
from splicr.config import Settings
from splicr.domain import JobStatus
from splicr.providers import ProviderRegistry
from splicr.service import SynthesisService
from splicr.studio.conversion import (
    AudioOutputFormat,
    ConversionCancelled,
    ConversionJob,
    ConversionJobService,
    ConversionJobStatus,
    ConversionJobStore,
    ConversionSpec,
    FfmpegAudioConverter,
    SplitMode,
)
from splicr.studio.domain import ArtifactKind
from splicr.studio.store import SqliteStudioStore

from .fakes import RecordingProvider


class FakeConverter:
    available = True

    async def probe_duration(self, source_path: Path) -> float:
        assert source_path.is_file()
        return 12.0

    async def convert(
        self,
        source_path: Path,
        output_path: Path,
        spec: ConversionSpec,
        *,
        duration_seconds: float,
        on_progress,
        is_cancelled,
    ) -> None:
        assert source_path.read_bytes().startswith(b"RIFF")
        assert duration_seconds == 12
        assert not is_cancelled()
        on_progress(0.4)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"converted-audio")
        on_progress(1)

    async def split(
        self,
        source_path: Path,
        output_directory: Path,
        spec: ConversionSpec,
        *,
        duration_seconds: float,
        on_progress,
        is_cancelled,
    ) -> list[Path]:
        assert source_path.read_bytes() == b"converted-audio"
        assert spec.split_mode is SplitMode.TIME
        output_directory.mkdir(parents=True, exist_ok=True)
        parts = [output_directory / "part-000.mp3", output_directory / "part-001.mp3"]
        for index, part in enumerate(parts, 1):
            part.write_bytes(f"part-{index}".encode())
        on_progress(1)
        return parts


class CancelThenCompleteConverter(FakeConverter):
    def __init__(self) -> None:
        self.attempt = 0

    async def convert(self, source_path: Path, output_path: Path, spec: ConversionSpec, **kwargs) -> None:
        self.attempt += 1
        if self.attempt == 1:
            kwargs["on_progress"](0.2)
            for _ in range(300):
                if kwargs["is_cancelled"]():
                    raise ConversionCancelled
                await asyncio.sleep(0.005)
            raise AssertionError("conversion was not cancelled")
        await super().convert(source_path, output_path, spec, **kwargs)


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        chunk_max_bytes=10_000,
        chunk_max_words=100,
        pacing_seconds=0,
        max_attempts=1,
    )


async def _completed_source(service: SynthesisService) -> str:
    created = await service.submit(text="A conversion source.", provider_name="fake")
    for _ in range(300):
        current = service.get_job(created.id)
        if current.status is JobStatus.COMPLETED:
            return current.id
        await asyncio.sleep(0.01)
    raise AssertionError("source synthesis did not finish")


def _service(
    settings: Settings,
    synthesis: SynthesisService,
    studio: SqliteStudioStore,
    converter,
) -> ConversionJobService:
    return ConversionJobService(
        store=ConversionJobStore(settings.database_path),
        source_store=synthesis.store,
        source_storage=synthesis.storage,
        studio_store=studio,
        output_root=settings.data_dir / "studio" / "conversions",
        input_root=settings.data_dir / "studio" / "conversion-inputs",
        converter=converter,
    )


def test_ffmpeg_conversion_command_is_whitelisted_and_maps_quality(tmp_path: Path) -> None:
    converter = FfmpegAudioConverter()
    command = converter.build_conversion_command(
        tmp_path / "source.wav",
        tmp_path / "output.mp3",
        ConversionSpec(
            output_format=AudioOutputFormat.MP3,
            quality_pct=70,
            sample_rate=24_000,
            channels=1,
            normalize_loudness=True,
        ),
    )

    assert command[command.index("-map") + 1] == "0:a:0"
    assert command[command.index("-ar") + 1] == "24000"
    assert command[command.index("-ac") + 1] == "1"
    assert command[command.index("-b:a") + 1] == "224k"
    assert "loudnorm=I=-16:TP=-1.5:LRA=11" in command
    assert command[-1].endswith("output.mp3")


def test_durable_conversion_splits_and_adds_take_artifacts(tmp_path: Path) -> None:
    async def scenario() -> None:
        settings = _settings(tmp_path)
        synthesis = SynthesisService(settings=settings, providers=ProviderRegistry([RecordingProvider()]))
        studio = SqliteStudioStore(settings.database_path)
        studio.initialize()
        service = _service(settings, synthesis, studio, FakeConverter())
        await synthesis.start()
        await service.start()
        try:
            source_id = await _completed_source(synthesis)
            created = await service.submit(
                ConversionSpec(split_mode=SplitMode.TIME, split_minutes=5),
                source_job_id=source_id,
            )
            for _ in range(300):
                current = service.store.get(created.id)
                if current.status is ConversionJobStatus.COMPLETED:
                    break
                await asyncio.sleep(0.01)
            else:
                raise AssertionError("conversion did not finish")

            assert service.output_for(current.id).read_bytes() == b"converted-audio"
            assert [service.output_for(current.id, index).read_bytes() for index in range(2)] == [
                b"part-1",
                b"part-2",
            ]
            assert len(current.artifact_ids) == 3
            assert all(studio.get_artifact(item).kind is ArtifactKind.AUDIO for item in current.artifact_ids)
        finally:
            await service.stop()
            await synthesis.stop()

    asyncio.run(scenario())


def test_running_conversion_can_cancel_and_retry_without_partial_output(tmp_path: Path) -> None:
    async def scenario() -> None:
        settings = _settings(tmp_path)
        synthesis = SynthesisService(settings=settings, providers=ProviderRegistry([RecordingProvider()]))
        studio = SqliteStudioStore(settings.database_path)
        studio.initialize()
        service = _service(settings, synthesis, studio, CancelThenCompleteConverter())
        await synthesis.start()
        await service.start()
        try:
            source_id = await _completed_source(synthesis)
            created = await service.submit(ConversionSpec(), source_job_id=source_id)
            for _ in range(300):
                if service.store.get(created.id).status is ConversionJobStatus.RUNNING:
                    break
                await asyncio.sleep(0.005)
            await service.cancel(created.id)
            for _ in range(300):
                cancelled = service.store.get(created.id)
                if cancelled.status is ConversionJobStatus.CANCELLED:
                    break
                await asyncio.sleep(0.005)
            else:
                raise AssertionError("conversion did not cancel")
            assert cancelled.output_path is None

            await service.retry(created.id)
            for _ in range(300):
                retried = service.store.get(created.id)
                if retried.status is ConversionJobStatus.COMPLETED:
                    break
                await asyncio.sleep(0.005)
            else:
                raise AssertionError("conversion retry did not finish")
            assert service.output_for(created.id).read_bytes() == b"converted-audio"
        finally:
            await service.stop()
            await synthesis.stop()

    asyncio.run(scenario())


def test_interrupted_conversion_is_requeued(tmp_path: Path) -> None:
    store = ConversionJobStore(tmp_path / "jobs.sqlite3")
    store.initialize()
    now = "2026-01-01T00:00:00+00:00"
    created = store.create(
        ConversionJob(
            id="conversion-1",
            source_job_id="source-1",
            input_id=None,
            source_name="source.wav",
            project_id="project-1",
            take_id="take-1",
            status=ConversionJobStatus.QUEUED,
            spec=ConversionSpec(),
            duration_seconds=30,
            progress=0,
            output_path=None,
            part_paths=(),
            artifact_ids=(),
            error_code=None,
            error_detail=None,
            cancel_requested=False,
            created_at=now,
            updated_at=now,
        )
    )
    assert store.claim(created.id)
    store.update_progress(created.id, 0.6)

    assert store.requeue_interrupted() == [created.id]
    recovered = store.get(created.id)
    assert recovered.status is ConversionJobStatus.QUEUED
    assert recovered.progress == 0
    assert recovered.output_path is None


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg is not installed",
)
def test_real_ffmpeg_conversion_and_time_split(tmp_path: Path) -> None:
    source = tmp_path / "tone.wav"
    with wave.open(str(source), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24_000)
        audio.writeframes(
            b"".join(
                struct.pack("<h", round(math.sin(index * 2 * math.pi * 440 / 24_000) * 9_000))
                for index in range(288_000)
            )
        )
    converter = FfmpegAudioConverter()
    output = tmp_path / "out.flac"
    spec = ConversionSpec(
        output_format=AudioOutputFormat.FLAC,
        sample_rate=16_000,
        split_mode=SplitMode.TIME,
        split_minutes=0.1,
    )

    duration_seconds = asyncio.run(converter.probe_duration(source))
    asyncio.run(
        converter.convert(
            source,
            output,
            spec,
            duration_seconds=duration_seconds,
            on_progress=lambda _value: None,
            is_cancelled=lambda: False,
        )
    )
    parts = asyncio.run(
        converter.split(
            output,
            tmp_path / "parts",
            spec,
            duration_seconds=duration_seconds,
            on_progress=lambda _value: None,
            is_cancelled=lambda: False,
        )
    )

    assert output.stat().st_size > 0
    assert len(parts) >= 2
    assert all(path.stat().st_size > 0 for path in parts)


def test_conversion_api_uploads_and_serves_completed_audio(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    synthesis = SynthesisService(settings=settings, providers=ProviderRegistry([RecordingProvider()]))
    studio = SqliteStudioStore(settings.database_path)
    studio.initialize()
    conversions = _service(settings, synthesis, studio, FakeConverter())

    with TestClient(
        create_app(settings=settings, service=synthesis, conversion_service=conversions)
    ) as client:
        uploaded = client.post(
            "/v1/studio/conversions/inputs",
            files={"file": ("recording.wav", b"RIFF-fake-wave", "audio/wav")},
        )
        assert uploaded.status_code == 201
        input_id = uploaded.json()["id"]
        sources = client.get("/v1/studio/conversions/sources")
        assert any(item["id"] == input_id and item["kind"] == "upload" for item in sources.json())

        response = client.post(
            "/v1/studio/conversions/jobs",
            json={"input_id": input_id, "spec": {"output_format": "mp3"}},
        )
        assert response.status_code == 202
        conversion_id = response.json()["id"]
        for _ in range(300):
            converted = client.get(f"/v1/studio/conversions/jobs/{conversion_id}").json()
            if converted["status"] == "completed":
                break
            time.sleep(0.01)
        else:
            raise AssertionError("conversion did not finish")

        audio = client.get(converted["output_url"])
        assert audio.status_code == 200
        assert audio.headers["content-type"] == "audio/mpeg"
        assert audio.content == b"converted-audio"
