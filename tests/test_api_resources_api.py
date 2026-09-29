from __future__ import annotations

import json

from fastapi.testclient import TestClient

from splicr.api import create_app
from splicr.api_resources import SqliteApiResourceStore
from splicr.config import Settings
from splicr.resource_registry import ResourceProviderRegistry
from splicr.secret_vault import InMemorySecretVault
from splicr.service import SynthesisService


def _resource_client(tmp_path):
    settings = Settings(
        data_dir=tmp_path,
        pacing_seconds=0,
        backoff_base_seconds=0,
        backoff_max_seconds=0,
        backoff_jitter_seconds=0,
    )
    vault = InMemorySecretVault()
    store = SqliteApiResourceStore(settings.database_path, vault=vault, environ={})
    store.initialize()
    registry = ResourceProviderRegistry(store, settings=settings)
    service = SynthesisService(settings=settings, providers=registry)
    return TestClient(create_app(settings=settings, service=service)), store, vault


def _custom_payload(**changes):
    payload = {
        "id": "narrator.local",
        "name": "Narrator Local",
        "adapter": "generic_rest",
        "method": "PATCH",
        "base_url": "https://speech.example.test/v2/render",
        "default_model": "narrator-v2",
        "default_voice": "ember",
        "models": ["narrator-v2"],
        "voices": [{"id": "ember", "traits": ["warm"]}],
        "auth_placement": "header",
        "auth_name": "X-Api-Key",
        "auth_prefix": "",
        "headers": {"X-Region": "{{ region }}"},
        "query": {"format": "pcm"},
        "request_template": {
            "input": {"text": "{{ text }}"},
            "voice": "{{ voice }}",
            "metadata": "{{ metadata }}",
        },
        "default_variables": {
            "region": "us-east",
            "metadata": {"source": "splicr"},
        },
        "max_input_characters": 100,
        "max_input_tokens": 50,
        "max_input_words": 30,
        "recommended_chunk_characters": 90,
        "limit_basis": "text",
        "request_timeout_seconds": 20,
        "retry_max_attempts": 4,
        "minimum_request_interval_seconds": 0.25,
        "requests_per_minute": 120,
        "max_concurrency": 1,
        "response_mode": "raw_pcm",
        "response_sample_rate_hz": 24_000,
        "response_channels": 1,
        "response_sample_width_bytes": 2,
    }
    payload.update(changes)
    return payload


def test_resource_crud_is_versioned_and_api_keys_are_write_only(tmp_path) -> None:
    client, store, vault = _resource_client(tmp_path)
    secret = "only-in-the-vault"

    with client:
        created_response = client.post(
            "/v1/api-resources",
            json=_custom_payload(api_key=secret),
        )
        assert created_response.status_code == 201
        created = created_response.json()
        assert created["id"] == "narrator.local"
        assert created["revision"] == 1
        assert created["has_api_key"] is True
        assert created["api_key_source"] == "vault"
        assert created["headers"] == {"X-Region": "{{ region }}"}
        assert created["default_variables"]["metadata"] == {"source": "splicr"}
        assert secret not in json.dumps(created)
        assert vault.get_secret("resource:narrator.local") == secret
        assert secret.encode() not in settings_database_bytes(store)

        listed = client.get("/v1/api-resources").json()
        assert {resource["id"] for resource in listed} >= {
            "gemini",
            "deepgram",
            "inworld",
            "narrator.local",
        }
        deepgram = next(resource for resource in listed if resource["id"] == "deepgram")
        assert len(deepgram["capabilities"]["voices"]) > 2

        updated_response = client.put(
            "/v1/api-resources/narrator.local",
            json=_custom_payload(revision=1, name="Narrator Revised"),
        )
        assert updated_response.status_code == 200
        updated = updated_response.json()
        assert updated["revision"] == 2
        assert updated["name"] == "Narrator Revised"
        assert vault.get_secret("resource:narrator.local") == secret
        assert store.get("narrator.local", 1) is not None

        stale = client.put(
            "/v1/api-resources/narrator.local",
            json=_custom_payload(revision=1),
        )
        assert stale.status_code == 409

        cleared = client.put(
            "/v1/api-resources/narrator.local",
            json=_custom_payload(revision=2, clear_api_key=True),
        )
        assert cleared.status_code == 200
        assert cleared.json()["revision"] == 3
        assert cleared.json()["has_api_key"] is False
        assert vault.get_secret("resource:narrator.local") is None

        deleted = client.delete("/v1/api-resources/narrator.local")
        assert deleted.status_code == 204
        assert client.get("/v1/api-resources/narrator.local").status_code == 404
        historical = client.get("/v1/api-resources/narrator.local?revision=3")
        assert historical.status_code == 200
        assert historical.json()["revision"] == 3


def test_preview_can_pin_an_older_resource_revision(tmp_path) -> None:
    client, _, _ = _resource_client(tmp_path)

    with client:
        created = client.post(
            "/v1/api-resources",
            json=_custom_payload(auth_placement="none", auth_name=None, auth_prefix=""),
        )
        assert created.status_code == 201
        updated = client.put(
            "/v1/api-resources/narrator.local",
            json=_custom_payload(
                revision=1,
                auth_placement="none",
                auth_name=None,
                auth_prefix="",
                max_input_characters=2,
                recommended_chunk_characters=2,
            ),
        )
        assert updated.status_code == 200

        pinned = client.post(
            "/v1/speech/preview",
            json={
                "text": "Hello world.",
                "provider": "narrator.local",
                "resource_id": "narrator.local",
                "resource_revision": 1,
            },
        )
        current = client.post(
            "/v1/speech/preview",
            json={
                "text": "Hello world.",
                "provider": "narrator.local",
                "resource_id": "narrator.local",
                "resource_revision": 2,
            },
        )

    assert pinned.status_code == 200
    assert current.status_code == 200
    assert len(pinned.json()["chunks"]) == 1
    assert len(current.json()["chunks"]) > 1


def test_resource_control_definitions_are_exposed_with_ui_metadata(tmp_path) -> None:
    client, _, _ = _resource_client(tmp_path)
    variable_definitions = [
        {
            "name": "temperature",
            "kind": "number",
            "label": "Temperature",
            "description": "Generation randomness.",
            "group": "Generation",
            "default": 0.75,
            "minimum": 0,
            "maximum": 2,
            "step": 0.05,
            "unit": "ratio",
            "visible_when": {"sampling_enabled": True},
            "read_only": False,
            "randomizable": False,
        }
    ]

    with client:
        response = client.post(
            "/v1/api-resources",
            json=_custom_payload(
                auth_placement="none",
                auth_name=None,
                auth_prefix="",
                headers={},
                request_template={"text": "{{ text }}", "temperature": "{{ temperature }}"},
                default_variables=None,
                variable_definitions=variable_definitions,
            ),
        )

    assert response.status_code == 201
    resource = response.json()
    saved_definition = resource["variable_definitions"][0]
    assert {key: saved_definition[key] for key in variable_definitions[0]} == (
        variable_definitions[0]
    )
    control = resource["capabilities"]["control_definitions"][0]
    assert control["key"] == "temperature"
    assert control["value_type"] == "number"
    assert control["group"] == "Generation"
    assert control["minimum"] == 0
    assert control["maximum"] == 2
    assert control["step"] == 0.05
    assert control["visible_when"] == [
        {"key": "sampling_enabled", "equals": True}
    ]
    assert control["read_only"] is False
    assert control["randomizable"] is False


def settings_database_bytes(store: SqliteApiResourceStore) -> bytes:
    # SQLite may keep recent data in WAL; neither file may contain a write-only secret.
    content = store.database_path.read_bytes()
    wal = store.database_path.with_name(f"{store.database_path.name}-wal")
    if wal.exists():
        content += wal.read_bytes()
    return content
