from __future__ import annotations

import asyncio
import hashlib
import json
import math
import shutil
import subprocess
import struct
import sys
import time
import wave
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from splicr.api import create_app
from splicr.config import Settings
from splicr.domain import JobStatus
from splicr.providers import ProviderRegistry
from splicr.service import SynthesisService
from splicr.studio.audiogram import (
    AudiogramBackgroundFit,
    AudiogramBackgroundMode,
    AudiogramGeometry,
    AudiogramJob,
    AudiogramJobKind,
    AudiogramJobService,
    AudiogramJobStatus,
    AudiogramJobStore,
    AudiogramOutputFormat,
    AudiogramRenderCancelled,
    AudiogramSource,
    AudiogramSpec,
    FfmpegAudiogramRenderer,
    audiogram_media_type,
    audiogram_output_extension,
    build_ffmpeg_command,
    build_filter_graph,
    requires_frame_renderer,
    resolve_layout,
)
from splicr.studio.domain import ArtifactKind
from splicr.studio.store import SqliteStudioStore
from splicr.studio.subtitles import SubtitleService

from .fakes import RecordingProvider


class FakeRenderer:
    available = True

    def __init__(self) -> None:
        self.subtitle_path: Path | None = None

    async def render(
        self,
        source_path: Path,
        output_path: Path,
        spec: AudiogramSpec,
        *,
        render_seconds: float,
        subtitle_path: Path | None,
        background_path: Path | None = None,
        on_progress,
        is_cancelled,
    ) -> None:
        assert source_path.read_bytes().startswith(b"RIFF")
        assert render_seconds > 0
        assert not is_cancelled()
        self.subtitle_path = subtitle_path
        if spec.background_mode is AudiogramBackgroundMode.IMAGE:
            assert background_path is not None and background_path.is_file()
        on_progress(0.25)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"fake-video")
        on_progress(1)


class CancelThenCompleteRenderer:
    available = True

    def __init__(self) -> None:
        self.attempt = 0

    async def render(
        self,
        source_path: Path,
        output_path: Path,
        spec: AudiogramSpec,
        *,
        render_seconds: float,
        subtitle_path: Path | None,
        background_path: Path | None = None,
        on_progress,
        is_cancelled,
    ) -> None:
        self.attempt += 1
        if self.attempt == 1:
            on_progress(0.2)
            for _ in range(300):
                if is_cancelled():
                    raise AudiogramRenderCancelled
                await asyncio.sleep(0.005)
            raise AssertionError("the test render was not cancelled")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"retried-video")
        on_progress(1)


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        chunk_max_bytes=10_000,
        chunk_max_words=100,
        pacing_seconds=0,
        max_attempts=1,
    )


async def _completed_source(service: SynthesisService) -> str:
    created = await service.submit(text="A short audiogram source.", provider_name="fake")
    for _ in range(300):
        current = service.get_job(created.id)
        if current.status is JobStatus.COMPLETED:
            return current.id
        await asyncio.sleep(0.01)
    raise AssertionError("source synthesis did not finish")


def test_ffmpeg_command_is_structured_and_keeps_audio(tmp_path: Path) -> None:
    spec = AudiogramSpec(
        source=AudiogramSource.FREQUENCY,
        width=1280,
        height=720,
        visualizer_height=240,
        foreground_color="#FFAA33",
        background_color="#101218",
        sharpen=0.4,
        output_format=AudiogramOutputFormat.MP4,
    )
    graph = build_filter_graph(spec)
    command = build_ffmpeg_command(
        "ffmpeg",
        tmp_path / "source.wav",
        tmp_path / "output.mp4",
        spec,
        render_seconds=4.5,
    )

    assert "showfreqs=" in graph
    assert "color=c=0x101218" in graph
    assert "cas=strength=0.400" in graph
    assert command[command.index("-map") + 1] == "[v]"
    assert command[command.index("-map", command.index("-map") + 1) + 1] == "0:a:0"
    assert "libx264" in command
    assert "aac" in command
    assert "-an" not in command
    assert command[-1].endswith("output.mp4")
    vector_graph = build_filter_graph(
        AudiogramSpec(source=AudiogramSource.VECTORSCOPE, foreground_color="#FFAA33")
    )
    assert "rc=255:gc=170:bc=51" in vector_graph


def test_mp4_command_uses_bitrate_driven_openh264_fallback(tmp_path: Path) -> None:
    spec = AudiogramSpec(
        output_format=AudiogramOutputFormat.MP4,
        width=1280,
        height=720,
        fps=30,
        crf=23,
    )

    command = build_ffmpeg_command(
        "ffmpeg",
        tmp_path / "source.wav",
        tmp_path / "output.mp4",
        spec,
        render_seconds=2,
        mp4_video_encoder="libopenh264",
    )

    assert command[command.index("-c:v") + 1] == "libopenh264"
    assert command[command.index("-rc_mode") + 1] == "bitrate"
    assert int(command[command.index("-b:v") + 1]) > 1_000_000
    assert "-crf" not in command
    assert "-preset" not in command


@pytest.mark.parametrize(
    ("encoders", "expected"),
    [
        (" V..... libopenh264 H.264 encoder", "libopenh264"),
        (" V..... libopenh264 H.264 encoder\n V..... libx264 H.264 encoder", "libx264"),
    ],
)
def test_renderer_detects_lgpl_mp4_encoder_and_prefers_x264(
    encoders: str,
    expected: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "splicr.studio.audiogram.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, encoders, ""),
    )
    renderer = FfmpegAudiogramRenderer(executable=sys.executable)

    assert renderer.mp4_video_encoder == expected
    assert AudiogramOutputFormat.MP4 in renderer.supported_output_formats


def test_image_background_uses_shared_layout_and_managed_ffmpeg_input(tmp_path: Path) -> None:
    background = tmp_path / "background.png"
    background.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
    spec = AudiogramSpec(
        width=1080,
        height=1920,
        visualizer_height=480,
        vertical_position=0.25,
        background_mode=AudiogramBackgroundMode.IMAGE,
        background_asset_id="asset-1",
        background_fit=AudiogramBackgroundFit.COVER,
        background_position_x=0.2,
        background_position_y=0.8,
    )

    layout = resolve_layout(spec)
    graph = build_filter_graph(spec)
    command = build_ffmpeg_command(
        "ffmpeg",
        tmp_path / "source.wav",
        tmp_path / "output.mp4",
        spec,
        render_seconds=4,
        background_path=background,
    )

    assert layout.visualizer_y == 360
    assert layout.to_mapping()["background_fit"] == "cover"
    assert "[1:v]scale=1080x1920:force_original_aspect_ratio=increase" in graph
    assert "crop=1080x1920:x='(iw-ow)*0.200000':y='(ih-oh)*0.800000'" in graph
    assert "overlay=x='0':y='360'" in graph
    start = command.index("-loop")
    assert command[start : start + 7] == [
        "-loop",
        "1",
        "-framerate",
        "24",
        "-i",
        str(background),
        "-filter_complex",
    ]


def test_image_background_requires_a_managed_asset() -> None:
    with pytest.raises(ValueError, match="background_asset_id"):
        AudiogramSpec(background_mode=AudiogramBackgroundMode.IMAGE)


@pytest.mark.parametrize(
    ("output_format", "codec", "pixel_format", "extension", "media_type"),
    [
        (AudiogramOutputFormat.WEBM_ALPHA, "libvpx-vp9", "yuva420p", "webm", "video/webm"),
        (
            AudiogramOutputFormat.PRORES_4444,
            "prores_ks",
            "yuva444p10le",
            "mov",
            "video/quicktime",
        ),
        (
            AudiogramOutputFormat.PNG_SEQUENCE,
            "png",
            "rgba",
            "zip",
            "application/zip",
        ),
    ],
)
def test_transparent_output_commands_preserve_alpha(
    tmp_path: Path,
    output_format: AudiogramOutputFormat,
    codec: str,
    pixel_format: str,
    extension: str,
    media_type: str,
) -> None:
    spec = AudiogramSpec(
        width=640,
        height=360,
        visualizer_height=180,
        background_mode=AudiogramBackgroundMode.TRANSPARENT,
        output_format=output_format,
    )
    target = tmp_path / (
        "frame-%08d.png"
        if output_format is AudiogramOutputFormat.PNG_SEQUENCE
        else f"out.{extension}"
    )
    graph = build_filter_graph(spec)
    command = build_ffmpeg_command(
        "ffmpeg",
        tmp_path / "source.wav",
        target,
        spec,
        render_seconds=2,
    )

    assert "black@0.0" in graph
    assert "format=auto,format=rgba" in graph
    assert codec in command
    assert pixel_format in command
    assert audiogram_output_extension(output_format) == extension
    assert audiogram_media_type(output_format) == media_type
    if output_format is AudiogramOutputFormat.PNG_SEQUENCE:
        assert command.count("-map") == 1
        assert "0:a:0" not in command
        assert "-shortest" not in command


def test_transparent_and_opaque_formats_cannot_be_mixed() -> None:
    with pytest.raises(ValueError, match="alpha-capable"):
        AudiogramSpec(background_mode=AudiogramBackgroundMode.TRANSPARENT)
    with pytest.raises(ValueError, match="transparent background"):
        AudiogramSpec(output_format=AudiogramOutputFormat.PRORES_4444)


@pytest.mark.parametrize(
    ("output_format", "video_codec", "audio_codec"),
    [
        (AudiogramOutputFormat.MP4, "libx264", "aac"),
        (AudiogramOutputFormat.WEBM, "libvpx-vp9", "libopus"),
    ],
)
def test_caption_burn_in_uses_subtitle_filter_for_each_container(
    tmp_path: Path,
    output_format: AudiogramOutputFormat,
    video_codec: str,
    audio_codec: str,
) -> None:
    subtitle_path = tmp_path / "captions, unicode Ω.srt"
    spec = AudiogramSpec(
        output_format=output_format,
        burn_captions=True,
    )

    command = build_ffmpeg_command(
        "ffmpeg",
        tmp_path / "source.wav",
        tmp_path / f"output.{output_format.value}",
        spec,
        render_seconds=4.5,
        subtitle_path=subtitle_path,
    )
    graph = command[command.index("-filter_complex") + 1]

    assert "subtitles=filename=" in graph
    assert "captions\\, unicode Ω.srt" in graph
    assert video_codec in command
    assert audio_codec in command


def test_spec_rejects_unbounded_or_odd_render_dimensions() -> None:
    with pytest.raises(ValueError, match="even number"):
        AudiogramSpec(width=1279)
    with pytest.raises(ValueError, match="canvas height"):
        AudiogramSpec(height=360, visualizer_height=500)
    with pytest.raises(ValueError, match="#RRGGBB"):
        AudiogramSpec(foreground_color="red")


def test_polar_layout_uses_short_dimension_and_never_inverts_radii() -> None:
    layout = resolve_layout(
        AudiogramSpec(
            width=1280,
            height=720,
            geometry=AudiogramGeometry.POLAR,
            inner_radius=0.45,
            outer_radius=0.2,
        )
    )

    assert layout.inner_radius == round(720 * 0.45)
    assert layout.outer_radius == layout.inner_radius + 1
    assert layout.visualizer_width == layout.outer_radius * 2


def test_formula_layout_resolves_against_frame_and_audio_context() -> None:
    spec = AudiogramSpec(
        rotation="360 * progress",
        opacity="clamp(level, 0, 1)",
        pivot_x="0.25 + bass * 0.25",
    )
    layout = resolve_layout(
        spec,
        {
            "progress": 0.25,
            "level": 0.4,
            "bass": 0.5,
            "duration": 10,
            "fps": 24,
            "t": 2.5,
            "frame": 60,
            "mid": 0.3,
            "treble": 0.2,
        },
    )

    assert layout.rotation == 90
    assert layout.opacity == pytest.approx(0.4)
    assert layout.pivot_x == round(1280 * 0.375)
    assert layout.animated is True


def test_fast_renderer_stays_default_while_advanced_controls_opt_in() -> None:
    assert requires_frame_renderer(AudiogramSpec()) is False
    assert requires_frame_renderer(AudiogramSpec(geometry=AudiogramGeometry.POLAR)) is True
    assert requires_frame_renderer(AudiogramSpec(rotation="15 * sin(t)")) is True
    assert "v360=" not in build_filter_graph(AudiogramSpec())
    assert "tmix=" not in build_filter_graph(AudiogramSpec())
    assert "v360=" in build_filter_graph(AudiogramSpec(geometry=AudiogramGeometry.POLAR))


def test_api_rejects_unsafe_audiogram_formula_before_render(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    synthesis = SynthesisService(
        settings=settings,
        providers=ProviderRegistry([RecordingProvider()]),
    )
    with TestClient(create_app(settings=settings, service=synthesis)) as client:
        response = client.post(
            "/v1/studio/audiograms/estimate",
            json={
                "source_job_id": "missing",
                "kind": "preview",
                "spec": {"rotation": "__import__('os').system('whoami')"},
            },
        )

    assert response.status_code == 422
    assert "Only listed formula functions" in response.text


def test_durable_audiogram_job_creates_video_artifact(tmp_path: Path) -> None:
    async def scenario() -> None:
        settings = _settings(tmp_path)
        synthesis = SynthesisService(
            settings=settings,
            providers=ProviderRegistry([RecordingProvider()]),
        )
        studio = SqliteStudioStore(settings.database_path)
        studio.initialize()
        job_store = AudiogramJobStore(settings.database_path)
        service = AudiogramJobService(
            store=job_store,
            source_store=synthesis.store,
            source_storage=synthesis.storage,
            studio_store=studio,
            output_root=tmp_path / "studio" / "audiograms",
            renderer=FakeRenderer(),
        )
        await synthesis.start()
        await service.start()
        try:
            source_job_id = await _completed_source(synthesis)
            created = await service.submit(
                source_job_id,
                AudiogramSpec(width=640, height=360, visualizer_height=180),
                kind=AudiogramJobKind.EXPORT,
            )
            for _ in range(300):
                current = job_store.get(created.id)
                if current.status is AudiogramJobStatus.COMPLETED:
                    break
                await asyncio.sleep(0.01)
            else:
                raise AssertionError("audiogram did not finish")

            assert current.progress == 1
            assert current.artifact_id
            assert service.output_for(current.id).read_bytes() == b"fake-video"
            artifact = studio.get_artifact(current.artifact_id)
            assert artifact.kind is ArtifactKind.VIDEO
            assert artifact.take_id == current.take_id
            assert artifact.sha256
        finally:
            await service.stop()
            await synthesis.stop()

    asyncio.run(scenario())


def test_captioned_audiogram_keeps_source_and_records_subtitle_provenance(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        settings = _settings(tmp_path)
        synthesis = SynthesisService(
            settings=settings,
            providers=ProviderRegistry([RecordingProvider()]),
        )
        studio = SqliteStudioStore(settings.database_path)
        studio.initialize()
        subtitles = SubtitleService(
            job_store=synthesis.store,
            job_storage=synthesis.storage,
            studio_store=studio,
            output_root=tmp_path / "studio" / "subtitles",
        )
        renderer = FakeRenderer()
        service = AudiogramJobService(
            store=AudiogramJobStore(settings.database_path),
            source_store=synthesis.store,
            source_storage=synthesis.storage,
            studio_store=studio,
            output_root=tmp_path / "studio" / "audiograms",
            subtitle_service=subtitles,
            renderer=renderer,
        )
        await synthesis.start()
        await service.start()
        try:
            source_job_id = await _completed_source(synthesis)
            source_path = synthesis.output_path(source_job_id)
            source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
            created = await service.submit(
                source_job_id,
                AudiogramSpec(
                    width=640,
                    height=360,
                    visualizer_height=180,
                    burn_captions=True,
                ),
                kind=AudiogramJobKind.EXPORT,
            )
            for _ in range(300):
                current = service.store.get(created.id)
                if current.status is AudiogramJobStatus.COMPLETED:
                    break
                await asyncio.sleep(0.01)
            else:
                raise AssertionError("captioned audiogram did not finish")

            assert renderer.subtitle_path is not None
            assert renderer.subtitle_path.read_text(encoding="utf-8").startswith("1\n")
            assert hashlib.sha256(source_path.read_bytes()).hexdigest() == source_hash
            artifact = studio.get_artifact(current.artifact_id or "")
            assert artifact.metadata["captions_burned_in"] is True
            subtitle_id = artifact.metadata["subtitle_artifact_id"]
            assert isinstance(subtitle_id, str)
            subtitle_artifact = studio.get_artifact(subtitle_id)
            assert subtitle_artifact.kind is ArtifactKind.SUBTITLES
            assert artifact.metadata["subtitle_sha256"] == subtitle_artifact.sha256
        finally:
            await service.stop()
            await synthesis.stop()

    asyncio.run(scenario())


def test_running_audiogram_can_cancel_without_exposing_partial_and_retry(tmp_path: Path) -> None:
    async def scenario() -> None:
        settings = _settings(tmp_path)
        synthesis = SynthesisService(
            settings=settings,
            providers=ProviderRegistry([RecordingProvider()]),
        )
        studio = SqliteStudioStore(settings.database_path)
        studio.initialize()
        renderer = CancelThenCompleteRenderer()
        service = AudiogramJobService(
            store=AudiogramJobStore(settings.database_path),
            source_store=synthesis.store,
            source_storage=synthesis.storage,
            studio_store=studio,
            output_root=tmp_path / "studio" / "audiograms",
            renderer=renderer,
        )
        await synthesis.start()
        await service.start()
        try:
            source_job_id = await _completed_source(synthesis)
            created = await service.submit(
                source_job_id,
                AudiogramSpec(width=640, height=360, visualizer_height=180),
                kind=AudiogramJobKind.PREVIEW,
            )
            for _ in range(300):
                if service.store.get(created.id).status is AudiogramJobStatus.RUNNING:
                    break
                await asyncio.sleep(0.005)
            await service.cancel(created.id)
            for _ in range(300):
                cancelled = service.store.get(created.id)
                if cancelled.status is AudiogramJobStatus.CANCELLED:
                    break
                await asyncio.sleep(0.005)
            else:
                raise AssertionError("audiogram did not cancel")
            assert cancelled.output_path is None
            assert not list((service.output_root / created.id).glob("*.mp4"))

            await service.retry(created.id)
            for _ in range(300):
                retried = service.store.get(created.id)
                if retried.status is AudiogramJobStatus.COMPLETED:
                    break
                await asyncio.sleep(0.005)
            else:
                raise AssertionError("audiogram retry did not finish")
            assert service.output_for(created.id).read_bytes() == b"retried-video"
        finally:
            await service.stop()
            await synthesis.stop()

    asyncio.run(scenario())


def test_interrupted_jobs_are_requeued_without_claiming_partial_output(tmp_path: Path) -> None:
    store = AudiogramJobStore(tmp_path / "jobs.sqlite3")
    store.initialize()
    now = "2026-01-01T00:00:00+00:00"
    job = store.create(
        AudiogramJob(
            id="render-1",
            source_job_id="source-1",
            project_id="project-1",
            take_id="take-1",
            kind=AudiogramJobKind.EXPORT,
            status=AudiogramJobStatus.QUEUED,
            spec=AudiogramSpec(),
            duration_seconds=30,
            render_seconds=30,
            progress=0,
            output_path=None,
            artifact_id=None,
            error_code=None,
            error_detail=None,
            cancel_requested=False,
            created_at=now,
            updated_at=now,
        )
    )
    assert store.claim(job.id)
    store.update_progress(job.id, 0.6)

    assert store.requeue_interrupted() == [job.id]
    recovered = store.get(job.id)
    assert recovered.status is AudiogramJobStatus.QUEUED
    assert recovered.progress == 0
    assert recovered.output_path is None


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is not installed")
@pytest.mark.parametrize("visualizer", list(AudiogramSource))
def test_real_ffmpeg_renderer_smoke(tmp_path: Path, visualizer: AudiogramSource) -> None:
    source = tmp_path / "tone.wav"
    with wave.open(str(source), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24_000)
        frames = b"".join(
            struct.pack("<h", round(math.sin(index * 2 * math.pi * 440 / 24_000) * 9_000))
            for index in range(12_000)
        )
        audio.writeframes(frames)

    output = tmp_path / f"{visualizer.value}.mp4"
    progress: list[float] = []
    asyncio.run(
        FfmpegAudiogramRenderer().render(
            source,
            output,
            AudiogramSpec(
                source=visualizer,
                width=640,
                height=360,
                visualizer_height=180,
                fps=24,
            ),
            render_seconds=0.5,
            on_progress=progress.append,
            is_cancelled=lambda: False,
        )
    )

    assert output.stat().st_size > 0
    assert progress[-1] == 1


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is not installed")
def test_advanced_renderer_exports_formula_driven_polar_alpha_frames(
    tmp_path: Path,
) -> None:
    renderer = FfmpegAudiogramRenderer()
    if AudiogramOutputFormat.PNG_SEQUENCE not in renderer.supported_output_formats:
        pytest.skip("FFmpeg PNG encoder is unavailable")
    source = tmp_path / "tone.wav"
    with wave.open(str(source), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24_000)
        audio.writeframes(
            b"".join(
                struct.pack(
                    "<h",
                    round(math.sin(index * 2 * math.pi * 220 / 24_000) * 10_000),
                )
                for index in range(6_000)
            )
        )
    output = tmp_path / "advanced-frames.zip"
    progress: list[float] = []

    asyncio.run(
        renderer.render(
            source,
            output,
            AudiogramSpec(
                width=320,
                height=180,
                visualizer_height=90,
                fps=12,
                geometry=AudiogramGeometry.POLAR,
                bar_count=16,
                show_line=True,
                rotation="15 * sin(t * 2)",
                background_mode=AudiogramBackgroundMode.TRANSPARENT,
                output_format=AudiogramOutputFormat.PNG_SEQUENCE,
            ),
            render_seconds=0.25,
            on_progress=progress.append,
            is_cancelled=lambda: False,
        )
    )

    with zipfile.ZipFile(output) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        first_frame = archive.read("frames/frame-00000000.png")
    assert manifest["frame_count"] == 3
    assert first_frame.startswith(b"\x89PNG\r\n\x1a\n")
    assert progress[-1] == 1


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is not installed")
def test_advanced_renderer_cancellation_removes_partial_frame_workspace(
    tmp_path: Path,
) -> None:
    renderer = FfmpegAudiogramRenderer()
    if AudiogramOutputFormat.PNG_SEQUENCE not in renderer.supported_output_formats:
        pytest.skip("FFmpeg PNG encoder is unavailable")
    source = tmp_path / "silence.wav"
    with wave.open(str(source), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24_000)
        audio.writeframes(b"\0\0" * 6_000)
    output = tmp_path / "cancelled.zip"

    with pytest.raises(AudiogramRenderCancelled):
        asyncio.run(
            renderer.render(
                source,
                output,
                AudiogramSpec(
                    width=320,
                    height=180,
                    visualizer_height=90,
                    fps=12,
                    geometry=AudiogramGeometry.POLAR,
                    background_mode=AudiogramBackgroundMode.TRANSPARENT,
                    output_format=AudiogramOutputFormat.PNG_SEQUENCE,
                ),
                render_seconds=0.25,
                on_progress=lambda _progress: None,
                is_cancelled=lambda: True,
            )
        )

    assert not output.exists()
    assert not list(tmp_path.glob(".*.frames"))


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is not installed")
def test_real_ffmpeg_renderer_builds_atomic_png_sequence_archive(tmp_path: Path) -> None:
    renderer = FfmpegAudiogramRenderer()
    if AudiogramOutputFormat.PNG_SEQUENCE not in renderer.supported_output_formats:
        pytest.skip("FFmpeg PNG encoder is unavailable")
    source = tmp_path / "tone.wav"
    with wave.open(str(source), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24_000)
        audio.writeframes(b"\0\0" * 6_000)
    output = tmp_path / "frames.zip"

    asyncio.run(
        renderer.render(
            source,
            output,
            AudiogramSpec(
                width=640,
                height=360,
                visualizer_height=180,
                fps=24,
                background_mode=AudiogramBackgroundMode.TRANSPARENT,
                output_format=AudiogramOutputFormat.PNG_SEQUENCE,
            ),
            render_seconds=0.25,
            on_progress=lambda _progress: None,
            is_cancelled=lambda: False,
        )
    )

    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        manifest = json.loads(archive.read("manifest.json"))
    assert names[0] == "manifest.json"
    assert any(name.startswith("frames/frame-") for name in names)
    assert manifest["frame_count"] == len(names) - 1
    assert manifest["fps"] == 24


def test_audiogram_api_lists_sources_and_serves_completed_preview(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    synthesis = SynthesisService(
        settings=settings,
        providers=ProviderRegistry([RecordingProvider()]),
    )
    studio = SqliteStudioStore(settings.database_path)
    studio.initialize()
    audiograms = AudiogramJobService(
        store=AudiogramJobStore(settings.database_path),
        source_store=synthesis.store,
        source_storage=synthesis.storage,
        studio_store=studio,
        output_root=tmp_path / "studio" / "audiograms",
        renderer=FakeRenderer(),
    )

    with TestClient(
        create_app(settings=settings, service=synthesis, audiogram_service=audiograms)
    ) as client:
        created = client.post(
            "/v1/speech/jobs",
            json={"text": "API audiogram source", "provider": "fake"},
        )
        source_id = created.json()["id"]
        for _ in range(300):
            source = client.get(f"/v1/speech/jobs/{source_id}").json()
            if source["status"] == "completed":
                break
            time.sleep(0.01)
        else:
            raise AssertionError("source did not finish")

        sources = client.get("/v1/studio/audiograms/sources")
        assert sources.status_code == 200
        assert [item["job_id"] for item in sources.json()] == [source_id]
        uploaded = client.post(
            "/v1/studio/audiograms/backgrounds",
            files={"file": ("cover.png", b"\x89PNG\r\n\x1a\nfixture", "image/png")},
        )
        assert uploaded.status_code == 201
        background = uploaded.json()
        assert client.get(background["url"]).content == b"\x89PNG\r\n\x1a\nfixture"
        assert client.get("/v1/studio/audiograms/backgrounds").json()[0]["id"] == background["id"]

        estimate = client.post(
            "/v1/studio/audiograms/estimate",
            json={
                "source_job_id": source_id,
                "kind": "preview",
                "spec": {
                    "width": 640,
                    "height": 360,
                    "visualizer_height": 180,
                    "background_mode": "image",
                    "background_asset_id": background["id"],
                    "background_fit": "contain",
                    "background_position_x": 0.25,
                    "background_position_y": 0.75,
                },
            },
        )
        assert estimate.status_code == 200
        layout = estimate.json()["layout"]
        assert {
            key: layout[key]
            for key in (
                "canvas_width",
                "canvas_height",
                "visualizer_x",
                "visualizer_y",
                "visualizer_width",
                "visualizer_height",
                "background_mode",
                "background_fit",
                "background_position_x",
                "background_position_y",
            )
        } == {
            "canvas_width": 640,
            "canvas_height": 360,
            "visualizer_x": 0,
            "visualizer_y": 90,
            "visualizer_width": 640,
            "visualizer_height": 180,
            "background_mode": "image",
            "background_fit": "contain",
            "background_position_x": 0.25,
            "background_position_y": 0.75,
        }
        response = client.post(
            "/v1/studio/audiograms/jobs",
            json={
                "source_job_id": source_id,
                "kind": "preview",
                "spec": {
                    "width": 640,
                    "height": 360,
                    "visualizer_height": 180,
                    "background_mode": "image",
                    "background_asset_id": background["id"],
                    "background_fit": "contain",
                },
            },
        )
        assert response.status_code == 202
        render_id = response.json()["id"]
        for _ in range(300):
            rendered = client.get(f"/v1/studio/audiograms/jobs/{render_id}").json()
            if rendered["status"] == "completed":
                break
            time.sleep(0.01)
        else:
            raise AssertionError("preview did not finish")

        assert rendered["progress"] == 1
        video = client.get(rendered["output_url"])
        assert video.status_code == 200
        assert video.headers["content-type"] == "video/mp4"
        assert video.content == b"fake-video"
