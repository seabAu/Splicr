from __future__ import annotations

import time

from fastapi.testclient import TestClient

from splicr.api import create_app
from splicr.config import Settings
from splicr.providers import ProviderRegistry
from splicr.service import SynthesisService
from tests.fakes import RecordingProvider


def test_job_lifecycle_and_audio_download(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        chunk_max_bytes=10_000,
        chunk_max_words=100,
        pacing_seconds=0,
        backoff_base_seconds=0,
        backoff_max_seconds=0,
        backoff_jitter_seconds=0,
    )
    service = SynthesisService(settings=settings, providers=ProviderRegistry([RecordingProvider()]))

    with TestClient(create_app(settings=settings, service=service)) as client:
        response = client.post(
            "/v1/speech/jobs",
            json={"text": "Hello from the API.", "provider": "fake"},
        )
        assert response.status_code == 202
        job_id = response.json()["id"]

        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            status_response = client.get(f"/v1/speech/jobs/{job_id}")
            if status_response.json()["status"] == "completed":
                break
            time.sleep(0.01)
        else:
            raise AssertionError("job did not complete")

        body = status_response.json()
        assert body["progress"] == 1.0
        assert body["audio_url"] == f"/v1/speech/jobs/{job_id}/audio"
        audio = client.get(body["audio_url"])
        assert audio.status_code == 200
        assert audio.headers["content-type"] == "audio/wav"
        assert audio.content.startswith(b"RIFF")


def test_unknown_provider_and_blank_text_are_validation_errors(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path)
    service = SynthesisService(settings=settings, providers=ProviderRegistry([RecordingProvider()]))

    with TestClient(create_app(settings=settings, service=service)) as client:
        unknown = client.post("/v1/speech/jobs", json={"text": "Hello", "provider": "missing"})
        blank = client.post("/v1/speech/jobs", json={"text": "   ", "provider": "fake"})

    assert unknown.status_code == 422
    assert blank.status_code == 422
