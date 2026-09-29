from __future__ import annotations

import asyncio
import hashlib
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
from splicr.studio.domain import ArtifactKind
from splicr.studio.finishing import (
    FfmpegFinishingRenderer,
    FinishingError,
    FinishingJobService,
    FinishingJobStatus,
    FinishingSpec,
    FinishingStore,
    build_finishing_command,
)
from splicr.studio.store import SqliteStudioStore
from splicr.studio.subtitles import SubtitleService

from .fakes import RecordingProvider


class FakeFinishingRenderer:
    available = True

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Path, ...], tuple[float, ...], bool]] = []

    def probe_duration(self, path: Path) -> float:
        if "intro" in path.name:
            return 4.0
        if "outro" in path.name:
            return 3.0
        return 10.0

    async def render(
        self,
        parts: tuple[Path, ...],
        joins: tuple[float, ...],
        output_path: Path,
        *,
        duration_seconds: float,
        normalize_loudness: bool,
        on_progress,
        is_cancelled,
    ) -> None:
        self.calls.append((parts, joins, normalize_loudness))
        assert not is_cancelled()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        _write_tone(output_path, duration_seconds)
        on_progress(1.0)


class FailingFinishingRenderer(FakeFinishingRenderer):
    async def render(self, *args, **kwargs) -> None:
        output_path = args[2]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"partial")
        raise FinishingError("ffmpeg_failed", "synthetic finishing failure")


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        chunk_max_bytes=10_000,
        chunk_max_words=100,
        pacing_seconds=0,
        max_attempts=1,
    )


async def _completed_source(service: SynthesisService) -> str:
    created = await service.submit(text="A finished narration source.", provider_name="fake")
    for _ in range(300):
        current = service.get_job(created.id)
        if current.status is JobStatus.COMPLETED:
            return current.id
        await asyncio.sleep(0.01)
    raise AssertionError("source synthesis did not finish")


def _service(
    settings: Settings,
    synthesis: SynthesisService,
    renderer,
) -> tuple[FinishingJobService, SqliteStudioStore]:
    studio = SqliteStudioStore(settings.database_path)
    studio.initialize()
    subtitles = SubtitleService(
        job_store=synthesis.store,
        job_storage=synthesis.storage,
        studio_store=studio,
        output_root=settings.data_dir / "studio" / "subtitles",
    )
    service = FinishingJobService(
        store=FinishingStore(settings.database_path),
        source_store=synthesis.store,
        source_storage=synthesis.storage,
        studio_store=studio,
        subtitle_service=subtitles,
        asset_root=settings.data_dir / "studio" / "finishing-assets",
        output_root=settings.data_dir / "studio" / "finished-audio",
        renderer=renderer,
    )
    service.store.initialize()
    return service, studio


def test_finishing_api_shifts_timeline_subtitles_and_chapters(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    synthesis = SynthesisService(
        settings=settings,
        providers=ProviderRegistry([RecordingProvider()]),
    )
    finishing, _ = _service(settings, synthesis, FakeFinishingRenderer())

    with TestClient(
        create_app(
            settings=settings,
            service=synthesis,
            finishing_service=finishing,
        )
    ) as client:
        source = client.post(
            "/v1/speech/jobs",
            json={"text": "# Opening\n\nA finished narration source.", "provider": "fake"},
        )
        assert source.status_code == 202
        source_job_id = source.json()["id"]
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            current = client.get(f"/v1/speech/jobs/{source_job_id}").json()
            if current["status"] == "completed":
                break
            time.sleep(0.01)
        else:
            raise AssertionError("source job did not complete")

        uploaded = client.post(
            "/v1/studio/finishing/assets",
            files={"file": ("intro.wav", b"intro", "audio/wav")},
        )
        assert uploaded.status_code == 201
        asset_id = uploaded.json()["id"]
        created = client.post(
            "/v1/studio/finishing/jobs",
            json={
                "source_job_id": source_job_id,
                "spec": {
                    "intro_asset_id": asset_id,
                    "crossfade_seconds": 30,
                    "normalize_loudness": False,
                },
            },
        )
        assert created.status_code == 202
        finishing_job_id = created.json()["id"]
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            current = client.get(
                f"/v1/studio/finishing/jobs/{finishing_job_id}"
            ).json()
            if current["status"] == "completed":
                break
            time.sleep(0.01)
        else:
            raise AssertionError("finishing job did not complete")

        artifact_id = current["artifact_id"]
        assert current["intro_offset"] == 2
        assert client.get(current["output_url"]).content.startswith(b"RIFF")

        takes = client.get("/v1/studio/timeline/takes").json()
        selected_take = next(item for item in takes if item["id"] == source_job_id)
        assert selected_take["finished_audio_artifacts"][0]["id"] == artifact_id

        timeline = client.get(
            f"/v1/studio/timeline/jobs/{source_job_id}",
            params={"waveform_buckets": 8, "audio_artifact_id": artifact_id},
        )
        assert timeline.status_code == 200
        assert timeline.json()["segments"][0]["start"] == 2
        assert timeline.json()["duration"] == 12
        assert timeline.json()["waveform"]

        subtitles = client.get(
            f"/v1/studio/subtitles/jobs/{source_job_id}",
            params={"audio_artifact_id": artifact_id},
        )
        assert subtitles.status_code == 200
        assert subtitles.json()["cues"][0]["start"] == 2

        sources = client.get("/v1/studio/publishing/sources").json()
        publish_source = next(item for item in sources if item["source_job_id"] == source_job_id)
        finished = next(item for item in publish_source["audio_artifacts"] if item["id"] == artifact_id)
        assert finished["role"] == "finished"
        assert finished["intro_offset"] == 2
        chapters = client.get(
            f"/v1/studio/publishing/takes/{publish_source['take_id']}/chapters",
            params={"audio_artifact_id": artifact_id},
        )
        assert chapters.status_code == 200
        assert chapters.json()[0]["seconds"] == 0
        assert chapters.json()[1]["seconds"] == 2

        missing = client.post(
            "/v1/studio/finishing/jobs",
            json={
                "source_job_id": source_job_id,
                "spec": {"intro_asset_id": "missing"},
            },
        )
        assert missing.status_code == 404
        assert missing.json()["detail"]["code"] == "asset_not_found"


def test_finishing_plan_is_durable_clamped_and_shifts_subtitles(tmp_path: Path) -> None:
    async def scenario() -> None:
        settings = _settings(tmp_path)
        synthesis = SynthesisService(
            settings=settings,
            providers=ProviderRegistry([RecordingProvider()]),
        )
        renderer = FakeFinishingRenderer()
        service, studio = _service(settings, synthesis, renderer)
        await synthesis.start()
        await service.start()
        try:
            source_job_id = await _completed_source(synthesis)
            source_path = synthesis.output_path(source_job_id)
            source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
            intro = service.register_upload("intro.wav", "audio/wav", b"intro")
            outro = service.register_upload("outro.wav", "audio/wav", b"outro")

            created = await service.submit(
                source_job_id,
                FinishingSpec(
                    intro_asset_id=intro.id,
                    outro_asset_id=outro.id,
                    crossfade_seconds=30,
                ),
            )
            assert created.intro_crossfade == 2
            assert created.outro_crossfade == 1.5
            assert created.intro_offset == 2
            assert created.output_duration == 13.5
            for _ in range(300):
                job = service.store.get_job(created.id)
                if job.status is FinishingJobStatus.COMPLETED:
                    break
                await asyncio.sleep(0.01)
            else:
                raise AssertionError("finishing job did not complete")

            assert hashlib.sha256(source_path.read_bytes()).hexdigest() == source_hash
            assert renderer.calls[0][1] == (2, 1.5)
            artifact = studio.get_artifact(job.artifact_id or "")
            assert artifact.kind is ArtifactKind.AUDIO
            assert artifact.metadata["intro_offset"] == 2
            assert artifact.metadata["requested_crossfade"] == 30
            assert len(job.subtitle_artifact_ids) == 2
            for subtitle_id in job.subtitle_artifact_ids:
                subtitle = studio.get_artifact(subtitle_id)
                assert subtitle.metadata["offset_seconds"] == 2
                assert subtitle.metadata["source_audio_artifact_id"] == artifact.id
                text = Path(subtitle.path).read_text(encoding="utf-8")
                assert "00:00:02" in text

            reopened = FinishingStore(settings.database_path)
            reopened.initialize()
            assert reopened.get_asset(intro.id) == intro
            assert reopened.get_job(job.id) == job
        finally:
            await service.stop()
            await synthesis.stop()

    asyncio.run(scenario())


def test_missing_asset_fails_structurally_without_touching_source_or_final(tmp_path: Path) -> None:
    async def scenario() -> None:
        settings = _settings(tmp_path)
        synthesis = SynthesisService(
            settings=settings,
            providers=ProviderRegistry([RecordingProvider()]),
        )
        service, studio = _service(settings, synthesis, FakeFinishingRenderer())
        await synthesis.start()
        try:
            source_job_id = await _completed_source(synthesis)
            source_path = synthesis.output_path(source_job_id)
            original = source_path.read_bytes()
            intro = service.register_upload("intro.wav", "audio/wav", b"intro")
            created = await service.submit(
                source_job_id,
                FinishingSpec(intro_asset_id=intro.id, crossfade_seconds=1),
            )
            Path(intro.path).unlink()
            await service.start()
            for _ in range(300):
                job = service.store.get_job(created.id)
                if job.status is FinishingJobStatus.FAILED:
                    break
                await asyncio.sleep(0.01)
            else:
                raise AssertionError("missing asset did not fail the finishing job")

            assert job.error_code == "asset_missing"
            assert job.error_context["asset_id"] == intro.id
            assert source_path.read_bytes() == original
            assert job.output_path is None
            assert not any(
                artifact.metadata.get("finishing_job_id") == job.id
                for artifact in studio.list_artifacts(job.take_id)
            )
        finally:
            await service.stop()
            await synthesis.stop()

    asyncio.run(scenario())


def test_atomic_renderer_failure_removes_partial_output(tmp_path: Path) -> None:
    async def scenario() -> None:
        settings = _settings(tmp_path)
        synthesis = SynthesisService(
            settings=settings,
            providers=ProviderRegistry([RecordingProvider()]),
        )
        service, _ = _service(settings, synthesis, FailingFinishingRenderer())
        await synthesis.start()
        await service.start()
        try:
            source_job_id = await _completed_source(synthesis)
            intro = service.register_upload("intro.wav", "audio/wav", b"intro")
            created = await service.submit(
                source_job_id,
                FinishingSpec(intro_asset_id=intro.id),
            )
            for _ in range(300):
                job = service.store.get_job(created.id)
                if job.status is FinishingJobStatus.FAILED:
                    break
                await asyncio.sleep(0.01)
            else:
                raise AssertionError("synthetic renderer failure was not persisted")
            assert job.error_code == "ffmpeg_failed"
            assert not list((settings.data_dir / "studio" / "finished-audio").rglob("*.part.wav"))
            assert not list((settings.data_dir / "studio" / "finished-audio").rglob("finished.wav"))
        finally:
            await service.stop()
            await synthesis.stop()

    asyncio.run(scenario())


def test_finishing_command_uses_concat_or_independent_crossfades(tmp_path: Path) -> None:
    parts = tuple(tmp_path / name for name in ("intro.wav", "voice.wav", "outro.wav"))
    crossfade = build_finishing_command(
        "ffmpeg", parts, (0.5, 0.25), tmp_path / "finished.wav"
    )
    concat = build_finishing_command(
        "ffmpeg", parts[:2], (0,), tmp_path / "concat.wav", normalize_loudness=True
    )

    graph = crossfade[crossfade.index("-filter_complex") + 1]
    concat_graph = concat[concat.index("-filter_complex") + 1]
    assert "acrossfade=d=0.500000" in graph
    assert "acrossfade=d=0.250000" in graph
    assert "concat=n=2:v=0:a=1[out]" in concat_graph
    assert "loudnorm=I=-16" in concat_graph
    assert "pcm_s16le" in concat


@pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
    reason="FFmpeg and FFprobe are not installed",
)
@pytest.mark.parametrize(
    ("part_durations", "joins", "expected"),
    [
        ((0.2, 0.4), (0.05,), 0.55),
        ((0.4, 0.2), (0.05,), 0.55),
        ((0.2, 0.4, 0.2), (0.05, 0.05), 0.7),
        ((0.2, 0.4, 0.2), (0.0, 0.0), 0.8),
        ((0.2, 0.4, 0.2), (0.1, 0.1), 0.6),
    ],
)
def test_real_ffmpeg_finishing_combinations(
    tmp_path: Path,
    part_durations: tuple[float, ...],
    joins: tuple[float, ...],
    expected: float,
) -> None:
    renderer = FfmpegFinishingRenderer()
    parts: list[Path] = []
    for index, duration in enumerate(part_durations):
        path = tmp_path / f"part-{index}.wav"
        _write_tone(path, duration, frequency=220 + index * 110)
        parts.append(path)
    output = tmp_path / "finished.wav"

    asyncio.run(
        renderer.render(
            tuple(parts),
            joins,
            output,
            duration_seconds=expected,
            normalize_loudness=False,
            on_progress=lambda _: None,
            is_cancelled=lambda: False,
        )
    )

    assert output.is_file()
    assert renderer.probe_duration(output) == pytest.approx(expected, abs=0.04)
    with wave.open(str(output), "rb") as audio:
        assert audio.getnchannels() == 1
        assert audio.getsampwidth() == 2
        assert audio.getframerate() == 24_000


def _write_tone(path: Path, seconds: float, *, frequency: int = 330) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24_000)
        audio.writeframes(
            b"".join(
                struct.pack(
                    "<h",
                    round(math.sin(index * 2 * math.pi * frequency / 24_000) * 5_000),
                )
                for index in range(round(seconds * 24_000))
            )
        )
