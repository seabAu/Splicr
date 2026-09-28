from __future__ import annotations

import wave
import xml.etree.ElementTree as ET
from pathlib import Path

from fastapi.testclient import TestClient

from splicr.api import create_app
from splicr.config import Settings
from splicr.providers import ProviderRegistry
from splicr.service import SynthesisService
from splicr.storage import LocalJobStorage
from splicr.store import SqliteJobStore
from splicr.studio.domain import (
    Artifact,
    ArtifactKind,
    Project,
    RenderPlan,
    RenderSegment,
    Take,
    TakeStatus,
)
from splicr.studio.publishing import (
    ATOM_NS,
    ITUNES_NS,
    ChapterCue,
    PodcastChannel,
    PublishedEpisode,
    PublishingService,
    PublishingStore,
    build_feed_xml,
    chapter_cues,
    youtube_chapters,
)
from splicr.studio.store import SqliteStudioStore
from splicr.studio.timeline import JobTimeline, TimelineSegment

from .fakes import RecordingProvider


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        chunk_max_bytes=10_000,
        chunk_max_words=100,
        pacing_seconds=0,
        max_attempts=1,
    )


def _write_wav(path: Path, seconds: float = 2.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(24_000)
        stream.writeframes(b"\0\0" * int(24_000 * seconds))


def _studio_source(tmp_path: Path) -> tuple[Settings, SqliteStudioStore, Artifact]:
    settings = _settings(tmp_path)
    studio = SqliteStudioStore(settings.database_path)
    studio.initialize()
    source = "# Opening\n\nWelcome.\n\n## Details\n\nThe useful middle.\n\n# Finish\n\nGoodbye."
    project = studio.save_project(Project(id="project-1", name="Book", source_text=source))
    first_end = source.index("## Details")
    plan = studio.create_render_plan(
        RenderPlan(
            id="plan-1",
            project_id=project.id,
            revision=1,
            segments=(
                RenderSegment(
                    id="segment-1",
                    ordinal=0,
                    text=source[:first_end].strip(),
                    source_start=0,
                    source_end=first_end,
                    engine_id="fake",
                    voice_id="voice",
                ),
                RenderSegment(
                    id="segment-2",
                    ordinal=1,
                    text=source[first_end:].strip(),
                    source_start=first_end,
                    source_end=len(source),
                    engine_id="fake",
                    voice_id="voice",
                ),
            ),
        )
    )
    take = studio.create_take(
        Take(
            id="take-1",
            project_id=project.id,
            render_plan_id=plan.id,
            label="First render",
            status=TakeStatus.COMPLETED,
        )
    )
    audio_path = tmp_path / "source.wav"
    _write_wav(audio_path, 4)
    artifact = studio.add_artifact(
        Artifact(
            id="audio-1",
            project_id=project.id,
            take_id=take.id,
            kind=ArtifactKind.AUDIO,
            path=str(audio_path),
            media_type="audio/wav",
            size_bytes=audio_path.stat().st_size,
        )
    )
    return settings, studio, artifact


def _publishing_service(
    settings: Settings, studio: SqliteStudioStore
) -> PublishingService:
    jobs = SqliteJobStore(settings.database_path)
    jobs.initialize()
    storage = LocalJobStorage(settings.jobs_dir)
    storage.initialize()
    service = PublishingService(
        store=PublishingStore(settings.database_path),
        studio_store=studio,
        job_store=jobs,
        job_storage=storage,
        output_root=settings.data_dir / "studio" / "publishing",
    )
    service.initialize()
    return service


def test_chapter_cues_use_segment_timing_and_youtube_rules(tmp_path: Path) -> None:
    _, studio, _ = _studio_source(tmp_path)
    take = studio.get_take("take-1")
    project = studio.get_project(take.project_id)
    plan = studio.get_render_plan(take.render_plan_id)
    timeline = JobTimeline(
        job_id="job-1",
        status="completed",  # type: ignore[arg-type]
        engine_id="fake",
        voice_id="voice",
        duration=20,
        waveform=(),
        segments=(
            TimelineSegment(0, "first", 0, 5, 5, 1, 1, "fake", "voice"),
            TimelineSegment(1, "second", 5, 20, 15, 1, 1, "fake", "voice"),
        ),
        audio_url=None,
    )

    cues = chapter_cues(project.source_text, plan, timeline, 20)

    assert [cue.title for cue in cues] == ["Opening", "Details", "Finish"]
    assert cues[0].seconds < 1.5
    assert 5 <= cues[1].seconds < cues[2].seconds <= 20
    assert youtube_chapters(cues).splitlines()[0].startswith("0:00 Opening")


def test_feed_xml_escapes_text_and_includes_podcast_namespaces() -> None:
    channel = PodcastChannel(
        title="Words & Sound",
        author="SPLICR",
        owner_email="owner@example.test",
        description="A <local> feed",
        website_url="https://example.test/show",
        media_base_url="https://cdn.example.test/podcast",
    )
    episode = PublishedEpisode(
        id="episode-1",
        take_id="take-1",
        project_id="project-1",
        audio_artifact_id="audio-1",
        title="One & Only",
        description="A <chapter>",
        publication_date="2026-09-28T12:00:00+00:00",
        episode_number=1,
        media_path="C:/managed/episode one.mp3",
        media_type="audio/mpeg",
        media_size_bytes=123,
        duration_seconds=65,
    )

    payload = build_feed_xml(channel, [episode])
    root = ET.fromstring(payload)
    item = root.find("channel/item")

    assert item is not None
    assert item.findtext("title") == "One & Only"
    assert item.findtext(f"{{{ITUNES_NS}}}duration") == "1:05"
    assert root.find(f"channel/{{{ATOM_NS}}}link") is not None
    assert item.find("enclosure").attrib["url"].endswith("media/episode%20one.mp3")  # type: ignore[union-attr]


def test_publish_is_durable_and_republishing_updates_same_episode(tmp_path: Path) -> None:
    settings, studio, audio = _studio_source(tmp_path)
    service = _publishing_service(settings, studio)
    service.store.save_channel(
        PodcastChannel(media_base_url="https://media.example.test/splicr")
    )

    first = service.publish_episode(
        take_id="take-1",
        audio_artifact_id=audio.id,
        title="Episode one",
        description="First description",
    )
    second = service.publish_episode(
        take_id="take-1",
        audio_artifact_id=audio.id,
        title="Episode one, revised",
        description="Revised description",
    )

    assert second.id == first.id
    assert second.episode_number == first.episode_number == 1
    assert second.title == "Episode one, revised"
    assert len(service.store.list_episodes()) == 1
    assert Path(second.media_path).is_file()
    assert service.feed_path.read_text(encoding="utf-8").count("<item>") == 1
    assert studio.get_artifact(second.transcript_artifact_id).kind is ArtifactKind.TRANSCRIPT  # type: ignore[arg-type]
    assert studio.get_artifact(second.chapters_artifact_id).kind is ArtifactKind.CHAPTERS  # type: ignore[arg-type]


def test_publishing_api_exports_and_downloads_local_artifacts(tmp_path: Path) -> None:
    settings, studio, audio = _studio_source(tmp_path)
    publishing = _publishing_service(settings, studio)
    synthesis = SynthesisService(
        settings=settings,
        providers=ProviderRegistry([RecordingProvider()]),
    )
    app = create_app(settings=settings, service=synthesis, publishing_service=publishing)

    with TestClient(app) as client:
        saved = client.put(
            "/v1/studio/publishing/channel",
            json={
                "title": "Book feed",
                "description": "Local episodes",
                "media_base_url": "https://media.example.test/book",
            },
        )
        assert saved.status_code == 200
        sources = client.get("/v1/studio/publishing/sources")
        assert sources.status_code == 200
        assert sources.json()[0]["take_id"] == "take-1"

        published = client.post(
            "/v1/studio/publishing/episodes",
            json={
                "take_id": "take-1",
                "audio_artifact_id": audio.id,
                "title": "The first episode",
            },
        )
        assert published.status_code == 201
        body = published.json()
        assert client.get(body["media_url"]).content.startswith(b"RIFF")
        assert client.get(body["transcript_url"]).text.startswith("# Opening")
        assert client.get(body["chapters_url"]).text.startswith("0:00 Opening")
        assert client.get("/v1/studio/publishing/feed").status_code == 200


def test_channel_rejects_non_http_media_base_url() -> None:
    try:
        PodcastChannel(media_base_url="/tmp/feed")
    except ValueError as error:
        assert "http://" in str(error)
    else:
        raise AssertionError("relative media base URL was accepted")


def test_youtube_export_explains_missing_or_short_chapter_sets() -> None:
    assert youtube_chapters([]) == "No Markdown headings were found in this document.\n"
    text = youtube_chapters([ChapterCue("Only chapter", 0, 1)])
    assert "requires at least three timestamps" in text
