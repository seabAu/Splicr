from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from splicr.api import create_app
from splicr.config import Settings
from splicr.providers import ProviderRegistry
from splicr.service import SynthesisService
from splicr.storage import LocalJobStorage
from splicr.store import SqliteJobStore
from splicr.studio.conversion import ConversionJobStore
from splicr.studio.store import SqliteStudioStore
from splicr.studio.transcription import TranscriptionJobService, TranscriptionJobStore

from .fakes import RecordingProvider
from .test_transcription import FakeTranscriptionProvider


def _client(tmp_path: Path) -> TestClient:
    settings = Settings(data_dir=tmp_path, pacing_seconds=0, max_attempts=1)
    synthesis = SynthesisService(
        settings=settings,
        providers=ProviderRegistry([RecordingProvider()]),
    )
    source_store = SqliteJobStore(settings.database_path)
    source_store.initialize()
    studio = SqliteStudioStore(settings.database_path)
    studio.initialize()
    conversion_store = ConversionJobStore(settings.database_path)
    conversion_store.initialize()
    transcription = TranscriptionJobService(
        store=TranscriptionJobStore(settings.database_path),
        conversion_store=conversion_store,
        source_store=source_store,
        source_storage=LocalJobStorage(settings.jobs_dir),
        studio_store=studio,
        output_root=tmp_path / "studio" / "transcriptions",
        providers=[FakeTranscriptionProvider(delay=0.01)],
    )
    return TestClient(
        create_app(
            settings=settings,
            service=synthesis,
            transcription_service=transcription,
        )
    )


def test_transcription_api_imports_audio_tracks_progress_and_downloads_outputs(tmp_path) -> None:
    with _client(tmp_path) as client:
        capabilities = client.get("/v1/studio/transcriptions/capabilities")
        assert capabilities.status_code == 200
        provider = capabilities.json()["providers"][0]
        assert provider["id"] == "fake-asr"
        assert provider["available"] is True
        assert provider["controls"][0]["key"] == "model"

        uploaded = client.post(
            "/v1/studio/conversions/inputs",
            files={"file": ("Meeting Ω.wav", b"managed audio", "audio/wav")},
        )
        assert uploaded.status_code == 201
        input_id = uploaded.json()["id"]
        sources = client.get("/v1/studio/transcriptions/sources").json()
        assert any(item["id"] == input_id and item["kind"] == "upload" for item in sources)

        created = client.post(
            "/v1/studio/transcriptions/jobs",
            json={
                "provider_id": "fake-asr",
                "input_id": input_id,
                "options": {
                    "model": "base",
                    "language": "en",
                    "device": "cpu",
                    "compute_type": "int8",
                    "vad_filter": True,
                    "word_timestamps": True,
                    "include_srt": True,
                    "include_vtt": True,
                    "line_timestamps": True,
                    "guessed_chapters": True,
                    "paragraph_gap_seconds": 2,
                    "chapter_pause_seconds": 2,
                },
            },
        )
        assert created.status_code == 202
        job_id = created.json()["id"]

        snapshots = []
        for _ in range(200):
            response = client.get(f"/v1/studio/transcriptions/jobs/{job_id}")
            assert response.status_code == 200
            job = response.json()
            snapshots.append(job)
            if job["status"] in {"completed", "failed", "cancelled"}:
                break
            time.sleep(0.01)
        assert job["status"] == "completed"
        assert job["progress"] == 1
        assert job["processed_seconds"] == 8
        assert job["segment_count"] == 3
        assert any(snapshot["phase"] == "transcribing" for snapshot in snapshots)
        assert set(job["output_urls"]) == {"segments", "transcript", "srt", "vtt", "chapters"}

        for name, url in job["output_urls"].items():
            downloaded = client.get(url)
            assert downloaded.status_code == 200, name
            assert downloaded.content
        assert "**[0:00]** Opening words." in client.get(job["output_urls"]["transcript"]).text
        assert "Guessed chapters" in client.get(job["output_urls"]["chapters"]).text


def test_transcription_api_rejects_ambiguous_and_unknown_requests(tmp_path) -> None:
    with _client(tmp_path) as client:
        ambiguous = client.post(
            "/v1/studio/transcriptions/jobs",
            json={"provider_id": "fake-asr"},
        )
        assert ambiguous.status_code == 422

        uploaded = client.post(
            "/v1/studio/conversions/inputs",
            files={"file": ("source.wav", b"audio", "audio/wav")},
        ).json()
        unknown = client.post(
            "/v1/studio/transcriptions/jobs",
            json={"provider_id": "missing", "input_id": uploaded["id"]},
        )
        assert unknown.status_code == 422
