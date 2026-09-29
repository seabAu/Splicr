from __future__ import annotations

import struct
from pathlib import Path

from fastapi.testclient import TestClient

from splicr.api import create_app
from splicr.config import Settings
from splicr.domain import SEGMENT_OPTIONS_VARIABLE
from splicr.providers import ProviderRegistry
from splicr.service import SynthesisService
from splicr.storage import LocalJobStorage
from splicr.store import SqliteJobStore
from splicr.studio.domain import ArtifactKind
from splicr.studio.store import SqliteStudioStore
from splicr.studio.subtitles import (
    SubtitleCue,
    SubtitleFormat,
    SubtitleService,
    SubtitleTimingConfidence,
    SubtitleTimingSource,
    serialize_subtitles,
)

from .fakes import RecordingProvider


def _service(tmp_path: Path) -> tuple[SubtitleService, SqliteJobStore, LocalJobStorage]:
    database = tmp_path / "splicr.sqlite3"
    job_store = SqliteJobStore(database)
    job_store.initialize()
    storage = LocalJobStorage(tmp_path / "jobs")
    storage.initialize()
    studio = SqliteStudioStore(database)
    studio.initialize()
    return (
        SubtitleService(
            job_store=job_store,
            job_storage=storage,
            studio_store=studio,
            output_root=tmp_path / "studio" / "subtitles",
        ),
        job_store,
        storage,
    )


def _checkpoint(
    store: SqliteJobStore,
    storage: LocalJobStorage,
    job_id: str,
    index: int,
    *,
    seconds: float = 1,
    metadata=None,
) -> Path:
    frames = round(24_000 * seconds)
    path = storage.write_chunk(job_id, index, struct.pack("<h", index + 1) * frames)
    store.mark_chunk_completed(job_id, index, str(path), metadata=metadata)
    return path


def test_timeline_prefers_engine_timings_and_labels_checkpoint_estimates(
    tmp_path: Path,
) -> None:
    service, store, storage = _service(tmp_path)
    store.create_job_with_chunks(
        job_id="mixed-timing",
        provider="edge",
        model="edge-tts",
        voice="en-US-AriaNeural",
        instructions=None,
        variables={
            SEGMENT_OPTIONS_VARIABLE: [
                {"speaker": "Alice"},
                {"speaker": "Bob"},
                {"speaker": "Alice"},
            ]
        },
        chunks=["Hello world", "Second line", "Not rendered"],
        export_stem="Unicode story",
    )
    _checkpoint(
        store,
        storage,
        "mixed-timing",
        0,
        metadata={
            "timings": [
                {
                    "type": "WordBoundary",
                    "start_seconds": 0,
                    "duration_seconds": 0.4,
                    "text": "Hello",
                },
                {
                    "type": "WordBoundary",
                    "start_seconds": 0.45,
                    "duration_seconds": 0.5,
                    "text": "world",
                },
            ]
        },
    )
    _checkpoint(store, storage, "mixed-timing", 1)

    timeline = service.timeline("mixed-timing")

    assert timeline.partial is True
    assert timeline.completed_chunks == 2
    assert timeline.total_chunks == 3
    assert timeline.duration == 2
    assert [cue.source_text for cue in timeline.cues] == [
        "Hello",
        "world",
        "Second line",
    ]
    assert [cue.speaker for cue in timeline.cues] == ["Alice", "Alice", "Bob"]
    assert timeline.source_counts == {"engine": 2, "checkpoint": 1}
    assert timeline.confidence_counts == {"exact": 2, "estimated": 1}
    assert all(
        left.end <= right.start
        for left, right in zip(timeline.cues, timeline.cues[1:])
    )


def test_serializers_escape_unicode_multiline_and_preserve_speakers() -> None:
    cues = (
        SubtitleCue(
            index=0,
            source_text="Café & tea\n<quietly>",
            start=0,
            end=1.25,
            speaker="Alice & Bob",
            confidence=SubtitleTimingConfidence.EXACT,
            source=SubtitleTimingSource.ENGINE,
        ),
        SubtitleCue(
            index=1,
            source_text="Second cue",
            start=1.1,
            end=2,
            speaker=None,
            confidence=SubtitleTimingConfidence.ESTIMATED,
            source=SubtitleTimingSource.CHECKPOINT,
        ),
    )

    srt = serialize_subtitles(cues, SubtitleFormat.SRT)
    vtt = serialize_subtitles(cues, SubtitleFormat.WEBVTT)

    assert "00:00:00,000 --> 00:00:01,250" in srt
    assert "Alice & Bob: Café & tea\n<quietly>" in srt
    assert "00:00:01,250 --> 00:00:02,000" in srt
    assert vtt.startswith("WEBVTT\n")
    assert "<v Alice &amp; Bob>Café &amp; tea\n&lt;quietly&gt;" in vtt
    assert "00:00:01.250 --> 00:00:02.000" in vtt


def test_partial_exports_are_hashed_idempotent_and_keep_provenance(tmp_path: Path) -> None:
    service, store, storage = _service(tmp_path)
    store.create_job_with_chunks(
        job_id="partial-export",
        provider="fake",
        model="fake-model",
        voice="fake-voice",
        instructions=None,
        chunks=["Rendered Ω", "Waiting"],
        export_stem="My subtitles",
    )
    storage.write_source("partial-export", "Rendered Ω\n\nWaiting")
    _checkpoint(store, storage, "partial-export", 0)

    first = service.export("partial-export", SubtitleFormat.SRT)
    second = service.export("partial-export", SubtitleFormat.SRT)

    assert first.artifact == second.artifact
    assert first.artifact.kind is ArtifactKind.SUBTITLES
    assert first.artifact.sha256
    assert first.artifact.metadata["partial"] is True
    assert first.artifact.metadata["source_job_id"] == "partial-export"
    assert first.artifact.metadata["timing_confidence"] == {"estimated": 1}
    assert Path(first.artifact.path).read_text(encoding="utf-8").endswith("\n")
    assert service.artifact_path(first.artifact.id) == Path(first.artifact.path)

    reopened = SqliteStudioStore(tmp_path / "splicr.sqlite3")
    reopened.initialize()
    persisted = reopened.get_artifact(first.artifact.id)
    assert persisted.metadata == first.artifact.metadata
    assert persisted.sha256 == first.artifact.sha256


def test_partial_subtitle_api_previews_exports_and_downloads(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        chunk_max_bytes=10_000,
        chunk_max_words=100,
        pacing_seconds=0,
        max_attempts=1,
    )
    synthesis = SynthesisService(
        settings=settings,
        providers=ProviderRegistry([RecordingProvider()]),
    )
    synthesis.store.initialize()
    synthesis.storage.initialize()
    synthesis.store.create_job_with_chunks(
        job_id="subtitle-api",
        provider="fake",
        model="fake-model",
        voice="fake-voice",
        instructions=None,
        chunks=["Available cue", "Still pending"],
    )
    synthesis.storage.write_source("subtitle-api", "Available cue\n\nStill pending")
    _checkpoint(synthesis.store, synthesis.storage, "subtitle-api", 0)
    synthesis.store.pause_job("subtitle-api")

    with TestClient(create_app(settings=settings, service=synthesis)) as client:
        preview = client.get("/v1/studio/subtitles/jobs/subtitle-api")
        assert preview.status_code == 200
        assert preview.json()["partial"] is True
        assert preview.json()["confidence_counts"] == {"estimated": 1}

        exported = client.post(
            "/v1/studio/subtitles/jobs/subtitle-api/export?format=vtt"
        )
        assert exported.status_code == 200
        assert exported.json()["format"] == "vtt"
        assert exported.json()["partial"] is True

        downloaded = client.get(exported.json()["download_url"])
        assert downloaded.status_code == 200
        assert downloaded.headers["content-type"].startswith("text/vtt")
        assert downloaded.text.startswith("WEBVTT\n")
