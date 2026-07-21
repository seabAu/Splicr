from __future__ import annotations

from fastapi.testclient import TestClient

from splicr.api import create_app
from splicr.config import Settings
from splicr.providers import ProviderRegistry
from splicr.service import SynthesisService

from .fakes import RecordingProvider


def _client(tmp_path) -> TestClient:
    settings = Settings(
        data_dir=tmp_path,
        pacing_seconds=0,
        backoff_base_seconds=0,
        backoff_max_seconds=0,
        backoff_jitter_seconds=0,
    )
    service = SynthesisService(
        settings=settings,
        providers=ProviderRegistry([RecordingProvider()]),
    )
    return TestClient(create_app(settings=settings, service=service))


def test_profile_api_restores_editor_state_and_linked_job(tmp_path) -> None:
    with _client(tmp_path) as client:
        job = client.post(
            "/v1/speech/jobs",
            json={"text": "Saved narration.", "provider": "fake"},
        ).json()
        created_response = client.post(
            "/v1/profiles",
            json={
                "name": "My narration",
                "resource_id": "fake",
                "text": "# Source\n\nSaved narration.",
                "model": "fake-model",
                "voice": "fake-voice",
                "instructions": "Read warmly.",
                "controls": {
                    "tone": "warm",
                    "pace": "slow",
                    "vocal_style": "audiobook",
                    "nonverbal_frequency": "rare",
                },
                "split_strategy": "h1",
                "remove_numeric_citations": True,
                "variables": {"seed": 7, "locale": "en-US"},
                "job_id": job["id"],
            },
        )

        assert created_response.status_code == 201
        created = created_response.json()
        assert created["text"].startswith("# Source")
        assert created["variables"] == {"locale": "en-US", "seed": 7}
        assert created["job"]["id"] == job["id"]

        listed = client.get("/v1/profiles").json()
        assert [profile["id"] for profile in listed] == [created["id"]]

        update_payload = {
            key: value
            for key, value in created.items()
            if key not in {"id", "created_at", "updated_at", "job"}
        }
        update_payload["name"] = "Renamed narration"
        updated = client.put(
            f"/v1/profiles/{created['id']}",
            json=update_payload,
        )
        assert updated.status_code == 200
        assert updated.json()["name"] == "Renamed narration"

        deleted = client.delete(f"/v1/profiles/{created['id']}")
        assert deleted.status_code == 204
        assert client.get(f"/v1/profiles/{created['id']}").status_code == 404


def test_profile_rejects_missing_job_link(tmp_path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/v1/profiles",
            json={
                "name": "Broken link",
                "resource_id": "fake",
                "job_id": "missing",
            },
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "linked job was not found"
