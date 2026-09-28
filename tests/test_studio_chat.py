from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from splicr.studio.chat import (
    ChatCompletionError,
    ChatResource,
    OpenAiChatCompleter,
)


def test_chat_resource_restricts_insecure_urls_and_secret_headers() -> None:
    local = ChatResource("ollama", "Ollama", "http://localhost:11434/v1/", "qwen3")
    assert local.base_url == "http://localhost:11434/v1"
    with pytest.raises(ValueError, match="non-loopback HTTP"):
        ChatResource("remote", "Remote", "http://models.example/v1", "model")
    with pytest.raises(ValueError, match="managed by SPLICR"):
        ChatResource(
            "forged",
            "Forged",
            "https://models.example/v1",
            "model",
            headers={"Authorization": "Bearer plaintext"},
        )


def test_openai_chat_completer_sends_key_and_extracts_content() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "<Person1>Hello.</Person1>"}}]},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    completer = OpenAiChatCompleter(
        ChatResource("hosted", "Hosted", "https://models.example/v1", "default-model"),
        api_key="vault-secret",
        client=client,
    )
    result = asyncio.run(
        completer.complete(
            [{"role": "user", "content": "Write a greeting."}],
            model="chosen-model",
            temperature=0.4,
            max_tokens=120,
        )
    )
    asyncio.run(client.aclose())

    assert result == "<Person1>Hello.</Person1>"
    assert captured["url"] == "https://models.example/v1/chat/completions"
    assert captured["authorization"] == "Bearer vault-secret"
    assert captured["body"] == {
        "model": "chosen-model",
        "messages": [{"role": "user", "content": "Write a greeting."}],
        "temperature": 0.4,
        "max_tokens": 120,
    }


@pytest.mark.parametrize(
    ("status", "retryable", "phrase"),
    [(401, False, "rejected"), (429, True, "rate limited"), (503, True, "HTTP 503")],
)
def test_openai_chat_completer_classifies_http_errors(
    status: int,
    retryable: bool,
    phrase: str,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": "provider detail"}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    completer = OpenAiChatCompleter(
        ChatResource("test", "Test", "https://models.example/v1", "model"),
        client=client,
    )
    with pytest.raises(ChatCompletionError) as caught:
        asyncio.run(completer.complete([{"role": "user", "content": "Hello"}]))
    asyncio.run(client.aclose())

    assert caught.value.status_code == status
    assert caught.value.retryable is retryable
    assert phrase in str(caught.value)
    assert "provider detail" in str(caught.value)


def test_openai_chat_completer_rejects_malformed_or_empty_responses() -> None:
    responses = iter(
        [
            httpx.Response(200, json={"unexpected": True}),
            httpx.Response(200, json={"choices": [{"message": {"content": ""}}]}),
        ]
    )
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: next(responses))
    )
    completer = OpenAiChatCompleter(
        ChatResource("test", "Test", "https://models.example/v1", "model"),
        client=client,
    )
    with pytest.raises(ChatCompletionError, match="OpenAI-compatible"):
        asyncio.run(completer.complete([{"role": "user", "content": "One"}]))
    with pytest.raises(ChatCompletionError, match="empty response"):
        asyncio.run(completer.complete([{"role": "user", "content": "Two"}]))
    asyncio.run(client.aclose())
