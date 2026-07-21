from __future__ import annotations

import time

from fastapi.testclient import TestClient

from splicr.api import create_app
from splicr.config import Settings
from splicr.providers import ProviderRegistry
from splicr.service import SynthesisService

from .fakes import RecordingProvider


def _client(tmp_path, provider: RecordingProvider | None = None) -> TestClient:
    settings = Settings(
        data_dir=tmp_path,
        chunk_max_bytes=10_000,
        chunk_max_words=2,
        pacing_seconds=0,
        backoff_base_seconds=0,
        backoff_max_seconds=0,
        backoff_jitter_seconds=0,
    )
    service = SynthesisService(
        settings=settings,
        providers=ProviderRegistry([provider or RecordingProvider()]),
    )
    return TestClient(create_app(settings=settings, service=service))


def _wait_for_paused(client: TestClient, job_id: str) -> dict:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        job = client.get(f"/v1/speech/jobs/{job_id}").json()
        if job["status"] == "paused":
            return job
        time.sleep(0.01)
    raise AssertionError("job did not pause")


def test_provider_failure_links_job_to_durable_diagnostics(tmp_path) -> None:
    with _client(tmp_path, RecordingProvider(fail_text="bad")) as client:
        created = client.post(
            "/v1/speech/jobs",
            json={"text": "good words\n\nbad words", "provider": "fake"},
        ).json()
        paused = _wait_for_paused(client, created["id"])

        assert paused["error_event_id"]
        assert paused["error_retryable"] is False
        assert paused["error_status_code"] == 400
        assert paused["error_chunk_index"] == 1
        event_response = client.get(f"/v1/errors/{paused['error_event_id']}")
        assert event_response.status_code == 200
        event = event_response.json()
        assert event["job_id"] == created["id"]
        assert event["provider"] == "fake"
        assert event["status_code"] == 400
        assert event["request"]["body"]["text"] == "bad words"
        assert "No HTTP response" in event["response"]["message"]

        listing = client.get("/v1/errors").json()
        assert listing["unread_count"] == 1
        assert listing["total_count"] == 1
        assert listing["events"][0]["id"] == paused["error_event_id"]

        client.post(f"/v1/errors/{paused['error_event_id']}/read")
        client.delete("/v1/errors", params={"scope": "read"})
        refreshed_job = client.get(f"/v1/speech/jobs/{created['id']}").json()
        assert refreshed_job["error_event_id"] is None
        assert refreshed_job["error_detail"] == "bad request"


def test_client_errors_are_redacted_deduplicated_and_manageable(tmp_path, monkeypatch) -> None:
    secret = "should-never-be-returned"
    monkeypatch.setenv("INWORLD_API_KEY", secret)
    report = {
        "code": "http_error",
        "message": "Saving the profile failed",
        "status_code": 502,
        "method": "post",
        "endpoint": f"https://alice:{secret}@example.test/tts?api%5Fkey={secret}",
        "request": {
            "headers": {"Authorization": f"Bearer {secret}"},
            "body": {"token": secret, "text": "short safe message"},
        },
        "response": {
            "status_text": "Bad Gateway",
            "body": {"message": "upstream", "opaque": secret},
        },
        "exception": {"type": "TypeError", "message": f"Bearer {secret}"},
    }

    with _client(tmp_path) as client:
        first = client.post("/v1/errors/client", json=report)
        normalized_report = {**report, "category": "client", "method": "POST"}
        second = client.post("/v1/errors/client", json=normalized_report)
        assert first.status_code == 201
        assert second.status_code == 201
        assert second.json()["id"] == first.json()["id"]
        assert second.json()["count"] == 2
        assert secret not in second.text
        assert "redact" in second.text.lower()
        persisted = client.app.state.error_event_store.get_error_event(first.json()["id"])
        assert persisted is not None
        assert secret not in repr(persisted)
        assert all(
            secret.encode() not in path.read_bytes()
            for path in tmp_path.rglob("*")
            if path.is_file()
        )

        marked = client.post(f"/v1/errors/{first.json()['id']}/read")
        assert marked.status_code == 200
        assert marked.json()["read_at"] is not None

        third = client.post("/v1/errors/client", json=report)
        assert third.status_code == 201
        assert third.json()["id"] != first.json()["id"]
        assert third.json()["count"] == 1

        all_read = client.post("/v1/errors/read-all").json()
        assert all_read["unread_count"] == 0
        cleared = client.delete("/v1/errors", params={"scope": "read"}).json()
        assert cleared["deleted"] == 2
        assert cleared["total_count"] == 0


def test_client_error_fingerprint_keeps_resource_and_chunk_context_separate(tmp_path) -> None:
    base = {
        "code": "http_400",
        "category": "api_request",
        "message": "Provider rejected the request",
        "status_code": 400,
        "method": "POST",
        "endpoint": "https://example.test/tts",
        "provider": "inworld",
        "resource_revision": 1,
        "job_id": "job-1",
        "chunk_index": 0,
    }
    with _client(tmp_path) as client:
        first = client.post("/v1/errors/client", json=base).json()
        revision = client.post("/v1/errors/client", json={**base, "resource_revision": 2}).json()
        chunk = client.post("/v1/errors/client", json={**base, "chunk_index": 1}).json()

        assert len({first["id"], revision["id"], chunk["id"]}) == 3
