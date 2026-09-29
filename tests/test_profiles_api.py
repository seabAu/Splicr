from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

from splicr.api import create_app
from splicr.bootstrap import create_service
from splicr.config import Settings
from splicr.domain import ControlDefinition, ControlValueType
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


def test_profile_freezes_control_defaults_and_rejects_unknown_values(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path)
    provider = RecordingProvider(
        control_definitions=(
            ControlDefinition(
                key="seed",
                value_type=ControlValueType.INTEGER,
                default=17,
                minimum=0,
            ),
        ),
        allows_undeclared_variables=False,
    )
    service = SynthesisService(settings=settings, providers=ProviderRegistry([provider]))

    with TestClient(create_app(settings=settings, service=service)) as client:
        created = client.post(
            "/v1/profiles",
            json={"name": "Deterministic", "resource_id": "fake"},
        )
        rejected = client.post(
            "/v1/profiles",
            json={
                "name": "Unknown controls",
                "resource_id": "fake",
                "variables": {"mystery": True},
            },
        )

    assert created.status_code == 201
    assert created.json()["variables"] == {"seed": 17}
    assert rejected.status_code == 422
    assert "unknown advanced control" in rejected.json()["detail"]


def test_profile_rejects_sensitive_control_without_echoing_its_value(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path)
    provider = RecordingProvider(
        control_definitions=(ControlDefinition(key="access_token", sensitive=True),),
        allows_undeclared_variables=False,
    )
    service = SynthesisService(settings=settings, providers=ProviderRegistry([provider]))
    secret = "profile-secret-must-not-echo"

    with TestClient(create_app(settings=settings, service=service)) as client:
        response = client.post(
            "/v1/profiles",
            json={
                "name": "Rejected secret",
                "resource_id": "fake",
                "variables": {"access_token": secret},
            },
        )

    assert response.status_code == 422
    assert "secret storage" in response.json()["detail"]
    assert secret not in response.text


def test_profile_accepts_non_resource_local_engine(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        kokoro_python=Path(sys.executable),
    )
    service = create_service(settings)

    with TestClient(create_app(settings=settings, service=service)) as client:
        provider_names = [item["name"] for item in client.get("/v1/providers").json()]
        resource_ids = [
            item["resource_id"] for item in client.get("/v1/api-resources").json()
        ]
        response = client.post(
            "/v1/profiles",
            json={
                "name": "Local Kokoro",
                "resource_id": "kokoro-local",
                "text": "Saved local narration.",
                "model": "kokoro-82m",
                "voice": "af_heart",
                "variables": {"speed": 1.37},
            },
        )
        rejected = client.post(
            "/v1/profiles",
            json={
                "name": "Invalid Kokoro speed",
                "resource_id": "kokoro-local",
                "variables": {"speed": 3.0},
            },
        )

    assert provider_names == ["gemini", "deepgram", "inworld", "kokoro-local"]
    assert resource_ids == ["gemini", "deepgram", "inworld"]
    assert response.status_code == 201
    assert response.json()["resource_id"] == "kokoro-local"
    assert response.json()["resource_revision"] is None
    assert response.json()["variables"] == {"speed": 1.37}
    assert rejected.status_code == 422
    assert "at most 2.0" in rejected.json()["detail"]
