from __future__ import annotations

import json

import pytest

from splicr.chat_resources import (
    ChatResourceConflictError,
    ChatResourceNotFoundError,
    ChatResourceSpec,
    SqliteChatResourceStore,
)
from splicr.secret_vault import InMemorySecretVault


def _store(tmp_path, *, environ=None) -> SqliteChatResourceStore:
    store = SqliteChatResourceStore(
        tmp_path / "splicr.sqlite3",
        InMemorySecretVault(),
        environ=environ or {},
    )
    store.initialize()
    return store


def _remote(revision: int = 1, name: str = "Hosted chat") -> ChatResourceSpec:
    return ChatResourceSpec(
        resource_id="hosted-chat",
        revision=revision,
        name=name,
        description="A private OpenAI-compatible endpoint.",
        base_url="https://models.example/v1",
        default_model="small-chat",
        models=("small-chat", "large-chat"),
        api_key_envs=("HOSTED_CHAT_API_KEY",),
    )


def test_chat_resource_round_trip_never_serializes_api_keys(tmp_path) -> None:
    store = _store(tmp_path)
    created = store.create(_remote())
    store.set_api_key("hosted-chat", "super-secret-token")

    payload = created.spec.to_json()
    assert "super-secret-token" not in payload
    assert ChatResourceSpec.from_json(payload) == created.spec
    assert store.resolve_api_key("hosted-chat") == "super-secret-token"
    assert store.api_key_source("hosted-chat") == "vault"
    with open(tmp_path / "splicr.sqlite3", "rb") as database:
        assert b"super-secret-token" not in database.read()


def test_chat_resource_uses_environment_fallback_and_vault_precedence(tmp_path) -> None:
    store = _store(tmp_path, environ={"HOSTED_CHAT_API_KEY": "environment-token"})
    store.create(_remote())
    assert store.resolve_api_key("hosted-chat") == "environment-token"
    assert store.api_key_source("hosted-chat") == "environment:HOSTED_CHAT_API_KEY"

    store.set_api_key("hosted-chat", "vault-token")
    assert store.resolve_api_key("hosted-chat") == "vault-token"
    assert store.api_key_source("hosted-chat") == "vault"
    store.clear_api_key("hosted-chat")
    assert store.resolve_api_key("hosted-chat") == "environment-token"


def test_chat_resource_revisions_use_optimistic_concurrency(tmp_path) -> None:
    store = _store(tmp_path)
    store.create(_remote())
    updated = store.update(
        "hosted-chat",
        _remote(name="Renamed chat"),
        expected_revision=1,
    )
    assert updated.spec.revision == 2
    assert updated.spec.name == "Renamed chat"
    assert store.get_revision("hosted-chat", 1).spec.name == "Hosted chat"
    with pytest.raises(ChatResourceConflictError, match="expected revision 1"):
        store.update("hosted-chat", _remote(), expected_revision=1)


def test_chat_resource_soft_delete_clears_secret_and_preserves_history(tmp_path) -> None:
    store = _store(tmp_path)
    store.create(_remote())
    store.set_api_key("hosted-chat", "vault-token")
    deleted = store.soft_delete("hosted-chat")
    assert deleted.deleted is True
    assert deleted.spec.revision == 2
    assert store.list() == []
    with pytest.raises(ChatResourceNotFoundError):
        store.get_current("hosted-chat")
    assert store.vault.get_secret("splicr.chat.hosted-chat") is None
    with pytest.raises(ChatResourceConflictError):
        store.create(_remote())


def test_builtin_local_chat_resources_are_seeded_and_not_deletable(tmp_path) -> None:
    store = _store(tmp_path)
    store.seed_builtins()
    store.seed_builtins()
    resources = store.list()
    assert {resource.spec.resource_id for resource in resources} == {
        "ollama",
        "lmstudio",
        "llamacpp",
    }
    assert all(resource.spec.local and resource.spec.built_in for resource in resources)
    assert all(resource.spec.runtime().base_url.startswith("http://localhost:") for resource in resources)
    with pytest.raises(ChatResourceConflictError, match="cannot be deleted"):
        store.soft_delete("ollama")


def test_chat_resource_validation_rejects_unsafe_configuration() -> None:
    with pytest.raises(ValueError, match="non-loopback HTTP"):
        ChatResourceSpec(
            "unsafe",
            1,
            "Unsafe",
            "http://models.example/v1",
            "model",
        )
    with pytest.raises(ValueError, match="environment variable"):
        ChatResourceSpec(
            "bad-env",
            1,
            "Bad env",
            "https://models.example/v1",
            "model",
            api_key_envs=("lowercase-key",),
        )
    serialized = json.dumps(_remote().to_dict())
    assert "credential" not in serialized.casefold()
