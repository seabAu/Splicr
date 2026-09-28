from __future__ import annotations

import json
from collections.abc import Sequence

from fastapi.testclient import TestClient

import splicr.api as api_module
from splicr.api import create_app
from splicr.chat_resources import SqliteChatResourceStore
from splicr.config import Settings
from splicr.providers import ProviderRegistry
from splicr.secret_vault import InMemorySecretVault
from splicr.service import SynthesisService
from splicr.studio.chat import ChatCompletionError, ChatResource
from splicr.studio.dialogue import ChatMessage
from tests.fakes import RecordingProvider


class FakeOpenAiChatCompleter:
    responses: list[str | Exception] = []
    instances: list["FakeOpenAiChatCompleter"] = []

    def __init__(
        self,
        resource: ChatResource,
        *,
        api_key: str | None = None,
    ) -> None:
        self.resource = resource
        self.api_key = api_key
        self.calls: list[dict[str, object]] = []
        self.instances.append(self)

    async def __aenter__(self) -> "FakeOpenAiChatCompleter":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2_048,
    ) -> str:
        self.calls.append(
            {
                "messages": list(messages),
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _client(tmp_path, monkeypatch) -> tuple[TestClient, SqliteChatResourceStore, InMemorySecretVault]:
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
    vault = InMemorySecretVault()
    store = SqliteChatResourceStore(settings.database_path, vault=vault, environ={})
    monkeypatch.setattr(api_module, "OpenAiChatCompleter", FakeOpenAiChatCompleter)
    FakeOpenAiChatCompleter.responses = []
    FakeOpenAiChatCompleter.instances = []
    return (
        TestClient(
            create_app(
                settings=settings,
                service=service,
                chat_resource_store=store,
            )
        ),
        store,
        vault,
    )


def _payload(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "resource_id": "openai-compatible",
        "name": "OpenAI-compatible test endpoint",
        "description": "Used by the dialogue writer.",
        "base_url": "https://chat.example.test/v1",
        "default_model": "writer-small",
        "models": ["writer-small", "writer-large"],
        "local": False,
        "headers": {"X-Workspace": "splicr"},
        "timeout_seconds": 30,
        "api_key_envs": ["TEST_CHAT_API_KEY"],
    }
    payload.update(changes)
    return payload


def test_chat_resource_crud_is_versioned_and_secrets_are_write_only(
    tmp_path,
    monkeypatch,
) -> None:
    client, store, vault = _client(tmp_path, monkeypatch)
    secret = "chat-secret-only-in-vault"

    with client:
        created_response = client.post(
            "/v1/chat-resources",
            json=_payload(api_key=secret),
        )
        assert created_response.status_code == 201
        created = created_response.json()
        assert created["resource_id"] == "openai-compatible"
        assert created["revision"] == 1
        assert created["has_api_key"] is True
        assert created["api_key_source"] == "vault"
        assert secret not in json.dumps(created)
        assert vault.get_secret("splicr.chat.openai-compatible") == secret
        assert secret.encode() not in store.database_path.read_bytes()

        listed = client.get("/v1/chat-resources")
        assert listed.status_code == 200
        assert {item["resource_id"] for item in listed.json()} >= {
            "ollama",
            "lmstudio",
            "llamacpp",
            "openai-compatible",
        }

        updated = client.put(
            "/v1/chat-resources/openai-compatible",
            json=_payload(revision=1, name="Revised endpoint"),
        )
        assert updated.status_code == 200
        assert updated.json()["revision"] == 2
        assert updated.json()["name"] == "Revised endpoint"
        assert vault.get_secret("splicr.chat.openai-compatible") == secret

        stale = client.put(
            "/v1/chat-resources/openai-compatible",
            json=_payload(revision=1),
        )
        assert stale.status_code == 409

        cleared = client.put(
            "/v1/chat-resources/openai-compatible",
            json=_payload(revision=2, clear_api_key=True),
        )
        assert cleared.status_code == 200
        assert cleared.json()["revision"] == 3
        assert cleared.json()["has_api_key"] is False

        deleted = client.delete("/v1/chat-resources/openai-compatible")
        assert deleted.status_code == 204
        assert client.get("/v1/chat-resources/openai-compatible").status_code == 404
        assert client.delete("/v1/chat-resources/ollama").status_code == 409


def test_chat_verification_generation_and_refinement_use_resolved_resource(
    tmp_path,
    monkeypatch,
) -> None:
    client, _, _ = _client(tmp_path, monkeypatch)

    with client:
        created = client.post(
            "/v1/chat-resources",
            json=_payload(api_key="resolved-secret"),
        )
        assert created.status_code == 201

        FakeOpenAiChatCompleter.responses = ["ready"]
        verified = client.post("/v1/chat-resources/openai-compatible/verify")
        assert verified.status_code == 200
        assert verified.json()["ok"] is True
        assert FakeOpenAiChatCompleter.instances[-1].api_key == "resolved-secret"

        FakeOpenAiChatCompleter.responses = [
            "1. Introduction",
            "<Person1>Welcome.</Person1><Person2>Let us explore it.</Person2>"
        ]
        generated = client.post(
            "/v1/studio/dialogue/generate",
            json={
                "text": "# Introduction\nA compact source section.",
                "chat_resource_id": "openai-compatible",
                "model": "writer-large",
                "options": {"section_chars": 500},
            },
        )
        assert generated.status_code == 200, generated.text
        assert [turn["speaker"] for turn in generated.json()["turns"]] == [
            "Person1",
            "Person2",
        ]
        assert generated.json()["sections"] == 1
        assert generated.json()["progress"]
        assert FakeOpenAiChatCompleter.instances[-1].resource.model == "writer-large"

        FakeOpenAiChatCompleter.responses = ['[[["A clearer sentence."]]]']
        refined = client.post(
            "/v1/studio/dialogue/refine",
            json={
                "chat_resource_id": "openai-compatible",
                "selected": "A muddy sentence.",
                "instruction": "Make this clearer.",
                "speaker": "Person1",
                "neighbor_before": {"speaker": "Person2", "text": "What does that mean?"},
            },
        )
        assert refined.status_code == 200
        assert refined.json() == {"replacement": "A clearer sentence."}


def test_chat_provider_failures_are_structured_without_exposing_credentials(
    tmp_path,
    monkeypatch,
) -> None:
    client, _, _ = _client(tmp_path, monkeypatch)

    with client:
        client.post(
            "/v1/chat-resources",
            json=_payload(api_key="must-not-leak"),
        )
        FakeOpenAiChatCompleter.responses = [
            ChatCompletionError("Rate limited.", status_code=429, retryable=True)
        ]
        failed = client.post("/v1/chat-resources/openai-compatible/verify")

    assert failed.status_code == 502
    assert failed.json()["detail"] == {
        "code": "CHAT_PROVIDER_ERROR",
        "message": "Rate limited.",
        "provider_status": 429,
        "retryable": True,
    }
    assert "must-not-leak" not in failed.text
