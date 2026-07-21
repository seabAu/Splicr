from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import json
import sqlite3

import pytest

from splicr.api_resources import (
    AdapterType,
    ApiAuthSpec,
    ApiResourceConflictError,
    ApiResourceSpec,
    ApiResponseSpec,
    ApiVariableDefinition,
    AuthMode,
    HttpMethod,
    InputLimits,
    LimitBasis,
    ResponseMode,
    SqliteApiResourceStore,
    TtsDefaults,
    VariableType,
    builtin_resource_specs,
)
from splicr.secret_vault import InMemorySecretVault, SecretVaultUnavailableError


def resource_spec(**changes: object) -> ApiResourceSpec:
    base: dict[str, object] = {
        "resource_id": "custom-api",
        "revision": 1,
        "name": "Custom API",
        "adapter_type": AdapterType.GENERIC_REST,
        "method": HttpMethod.POST,
        "base_url": "https://speech.example.test/v1/synthesize",
        "auth": ApiAuthSpec(
            mode=AuthMode.HEADER,
            name="Authorization",
            prefix="Bearer ",
            env_keys=("CUSTOM_TTS_API_KEY",),
        ),
        "headers": {"Content-Type": "application/json", "X-Client": "splicr"},
        "query": {"format": "pcm"},
        "request_template": {
            "input": {"text": "${text}"},
            "settings": {"voice": "${voice}", "flags": [True, None]},
        },
        "variables": (
            ApiVariableDefinition("text", required=True),
            ApiVariableDefinition(
                "voice",
                kind=VariableType.STRING,
                default="sample",
                choices=("sample", "other"),
            ),
        ),
        "response": ApiResponseSpec(ResponseMode.JSON_BASE64_PCM, "/data/audio"),
        "defaults": TtsDefaults("model-a", "sample", ("model-a",)),
        "input_limits": InputLimits(
            max_characters=2_000,
            max_words=400,
            recommended_words=350,
            recommended_characters=1_900,
            limit_basis=LimitBasis.BODY,
        ),
    }
    base.update(changes)
    return ApiResourceSpec(**base)


def test_resource_is_deeply_immutable_and_round_trips_deterministically() -> None:
    mutable_headers = {"X-Z": "last", "X-A": "first"}
    mutable_template = {"nested": {"items": [1, 2]}}
    spec = resource_spec(headers=mutable_headers, request_template=mutable_template)
    mutable_headers["X-Late"] = "must not appear"
    mutable_template["nested"]["items"].append(3)  # type: ignore[index,union-attr]

    with pytest.raises(FrozenInstanceError):
        spec.name = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        spec.headers["X-New"] = "value"  # type: ignore[index]

    encoded = spec.to_json()
    assert "X-Late" not in encoded
    assert encoded == ApiResourceSpec.from_json(encoded).to_json()
    assert encoded.index('"X-A"') < encoded.index('"X-Z"')
    assert ApiResourceSpec.from_json(encoded).input_limits.max_words == 400
    assert ApiResourceSpec.from_json(encoded).input_limits.limit_basis is LimitBasis.BODY


def test_serialization_rejects_unknown_secret_fields() -> None:
    payload = resource_spec().to_dict()
    payload["auth"]["api_key"] = "do-not-store"

    with pytest.raises(ValueError, match="api_key"):
        ApiResourceSpec.from_dict(payload)


@pytest.mark.parametrize(
    "url",
    [
        "http://speech.example.test/v1/tts",
        "ftp://speech.example.test/v1/tts",
        "https://user:password@speech.example.test/v1/tts",
        "https://speech.example.test/v1/tts#secret",
        " https://speech.example.test/v1/tts",
        "https://speech.example.test\\@attacker.test/v1/tts",
    ],
)
def test_resource_rejects_unsafe_urls(url: str) -> None:
    with pytest.raises(ValueError):
        resource_spec(base_url=url)


@pytest.mark.parametrize(
    "url", ["http://localhost:8123/tts", "http://127.0.0.1:8123/tts", "http://[::1]:8123/tts"]
)
def test_loopback_http_is_allowed(url: str) -> None:
    assert resource_spec(base_url=url).base_url == url


def test_insecure_non_loopback_http_requires_an_explicit_flag() -> None:
    spec = resource_spec(
        base_url="http://devbox.internal/tts",
        allow_insecure_http=True,
    )
    assert spec.allow_insecure_http is True


@pytest.mark.parametrize("header", ["Host", "Content-Length", "Transfer-Encoding"])
def test_resource_rejects_transport_controlled_headers(header: str) -> None:
    with pytest.raises(ValueError, match="not allowed"):
        resource_spec(headers={header: "unsafe"})


@pytest.mark.parametrize("header", ["Authorization", "X-Api-Key", "X-Secret-Token"])
def test_static_credentials_must_use_write_only_auth_configuration(header: str) -> None:
    with pytest.raises(ValueError, match="auth configuration"):
        resource_spec(headers={header: "plaintext"})

    with pytest.raises(ValueError, match="credential-bearing query"):
        resource_spec(query={"access_token": "plaintext"})


def test_template_auth_keeps_body_credentials_in_the_vault(tmp_path) -> None:
    store = SqliteApiResourceStore(
        tmp_path / "template-auth.sqlite3", vault=InMemorySecretVault(), environ={}
    )
    store.initialize(seed_builtins=False)
    spec = resource_spec(
        auth=ApiAuthSpec(mode=AuthMode.TEMPLATE),
        request_template={"text": "${text}", "key": "${api_key}"},
    )

    store.create(spec, api_key="body-only-secret")

    assert store.resolve_api_key(spec) == "body-only-secret"
    assert "body-only-secret" not in spec.to_json()


def test_json_base64_response_requires_a_valid_pointer() -> None:
    with pytest.raises(ValueError, match="JSON Pointer"):
        ApiResponseSpec(ResponseMode.JSON_BASE64_WAV)
    with pytest.raises(ValueError, match="invalid escape"):
        ApiResponseSpec(ResponseMode.JSON_BASE64_WAV, "/audio/~2value")


def test_store_versions_heads_soft_deletes_and_preserves_history(tmp_path) -> None:
    store = SqliteApiResourceStore(
        tmp_path / "splicr.sqlite3", vault=InMemorySecretVault(), environ={}
    )
    store.initialize(seed_builtins=False)
    initial = store.create(resource_spec())
    replacement = replace(initial, name="Custom API v2", base_url="https://v2.example.test/tts")

    updated = store.update(initial.resource_id, replacement)

    assert updated.revision == 2
    assert store.get(initial.resource_id, 1) == initial
    assert store.get_current(initial.resource_id) == updated
    assert store.list() == (updated,)
    revisions = store.list_revisions(initial.resource_id)
    assert [revision.enabled for revision in revisions] == [False, True]

    assert store.soft_delete(initial.resource_id) is True
    assert store.soft_delete(initial.resource_id) is False
    assert store.get_current(initial.resource_id) is None
    assert store.get(initial.resource_id, 2) == updated
    assert store.list_revisions(initial.resource_id)[-1].deleted_at is not None


def test_store_rejects_reusing_even_a_soft_deleted_identity(tmp_path) -> None:
    store = SqliteApiResourceStore(tmp_path / "resources.sqlite3", vault=InMemorySecretVault())
    store.initialize(seed_builtins=False)
    spec = store.create(resource_spec())
    store.soft_delete(spec.resource_id)

    with pytest.raises(ApiResourceConflictError):
        store.create(spec)


def test_builtin_seeding_is_idempotent_and_does_not_resurrect_deletion(tmp_path) -> None:
    store = SqliteApiResourceStore(tmp_path / "resources.sqlite3", vault=InMemorySecretVault())
    store.initialize()
    assert {spec.resource_id for spec in store.list()} == {"gemini", "deepgram", "inworld"}
    assert store.seed_builtins() == ()

    store.soft_delete("gemini")
    store.initialize()
    assert store.get_current("gemini") is None
    assert len(store.list_revisions("gemini")) == 1


def test_api_key_is_write_only_and_never_enters_sqlite_or_spec_json(tmp_path) -> None:
    database = tmp_path / "resources.sqlite3"
    vault = InMemorySecretVault()
    store = SqliteApiResourceStore(database, vault=vault, environ={})
    store.initialize(seed_builtins=False)

    spec = store.create(resource_spec(), api_key="super-secret-key")

    assert store.has_api_key(spec) is True
    assert store.resolve_api_key(spec) == "super-secret-key"
    assert "super-secret-key" not in spec.to_json()
    with sqlite3.connect(database) as connection:
        stored_json = connection.execute("SELECT spec_json FROM api_resource_revisions").fetchone()[
            0
        ]
    assert "super-secret-key" not in stored_json

    store.set_api_key(spec.resource_id, "replacement-secret")
    assert store.resolve_api_key(spec) == "replacement-secret"
    store.clear_api_key(spec.resource_id)
    assert store.has_api_key(spec) is False


def test_environment_reference_is_used_when_vault_has_no_key(tmp_path) -> None:
    store = SqliteApiResourceStore(
        tmp_path / "resources.sqlite3",
        vault=InMemorySecretVault(),
        environ={"CUSTOM_TTS_API_KEY": "environment-secret"},
    )
    store.initialize(seed_builtins=False)
    spec = store.create(resource_spec())

    assert store.resolve_api_key(spec) == "environment-secret"
    assert store.api_key_source(spec) == "environment"
    assert "environment-secret" not in spec.to_json()


def test_configured_environment_fallback_survives_unavailable_keyring(tmp_path) -> None:
    class UnavailableVault:
        def set_secret(self, _reference: str, _secret: str) -> None:
            raise SecretVaultUnavailableError("unavailable")

        def get_secret(self, _reference: str) -> str | None:
            raise SecretVaultUnavailableError("unavailable")

        def delete_secret(self, _reference: str) -> None:
            raise SecretVaultUnavailableError("unavailable")

    store = SqliteApiResourceStore(
        tmp_path / "resources.sqlite3",
        vault=UnavailableVault(),
        environ={"CUSTOM_TTS_API_KEY": "environment-secret"},
    )
    store.initialize(seed_builtins=False)
    spec = store.create(resource_spec())

    assert store.resolve_api_key(spec) == "environment-secret"


def test_builtin_specs_are_serializable_and_secret_free() -> None:
    payload = json.dumps([spec.to_dict() for spec in builtin_resource_specs()])
    assert {spec.adapter_type for spec in builtin_resource_specs()} == {
        AdapterType.GEMINI,
        AdapterType.DEEPGRAM,
        AdapterType.INWORLD,
    }
    assert "super-secret-key" not in payload
    assert '"api_key"' not in payload.casefold()
