from __future__ import annotations

import asyncio
import json
from typing import Callable

import httpx
import pytest

import splicr.providers.deepgram as deepgram_module
from splicr.domain import (
    CANONICAL_AUDIO_FORMAT,
    DeliveryControls,
    ProviderError,
    SpeechPace,
    SynthesisOptions,
    TonePreset,
)
from splicr.providers.deepgram import DeepgramTtsProvider


def _options(
    *,
    voice: str = "aura-2-thalia-en",
    pace: SpeechPace = SpeechPace.NORMAL,
    instructions: str | None = None,
) -> SynthesisOptions:
    return SynthesisOptions(
        model="aura-2",
        voice=voice,
        instructions=instructions,
        controls=DeliveryControls(pace=pace),
    )


def _run_with_transport(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    text: str = "Hello world.",
    options: SynthesisOptions | None = None,
) -> object:
    async def run() -> object:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = DeepgramTtsProvider(api_key="deepgram-secret", client=client)
        try:
            return await provider.synthesize(text, options or _options())
        finally:
            await client.aclose()

    return asyncio.run(run())


def test_sends_exact_rest_contract_and_returns_canonical_pcm() -> None:
    pcm = b"\x01\x00\x02\x00"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url.copy_with(query=None)) == "https://api.deepgram.com/v1/speak"
        assert dict(request.url.params) == {
            "model": "aura-2-thalia-en",
            "encoding": "linear16",
            "container": "none",
            "sample_rate": "24000",
            "speed": "1.0",
        }
        assert request.headers["authorization"] == "Token deepgram-secret"
        assert request.headers["content-type"] == "application/json"
        assert json.loads(request.content) == {"text": "Hello world."}
        return httpx.Response(
            200,
            headers={
                "Content-Type": "audio/l16; rate=24000",
                "dg-request-id": "request-123",
            },
            content=pcm,
        )

    audio = _run_with_transport(handler)

    assert getattr(audio, "pcm") == pcm
    assert getattr(audio, "format") == CANONICAL_AUDIO_FORMAT


def test_provider_metadata_exposes_character_limit_and_native_pacing() -> None:
    provider = DeepgramTtsProvider(
        api_key="secret",
        minimum_request_interval_seconds=0.25,
    )

    assert provider.info.name == "deepgram"
    assert provider.info.default_model == "aura-2"
    assert provider.info.default_voice == "aura-2-thalia-en"
    assert provider.info.max_input_characters == 2_000
    assert provider.info.recommended_chunk_characters == 1_900
    assert provider.info.minimum_request_interval_seconds == 0.25
    assert provider.info.capabilities.speech_paces == tuple(SpeechPace)
    assert provider.info.capabilities.supports_custom_instructions is False
    assert provider.estimate_input_characters("é🙂", _options()) == 2


def test_rejects_unsupported_delivery_controls_before_io() -> None:
    provider = DeepgramTtsProvider(api_key="secret", client=httpx.AsyncClient())
    options = SynthesisOptions(
        model="aura-2",
        voice="aura-2-thalia-en",
        controls=DeliveryControls(tone=TonePreset.WARM),
    )

    with pytest.raises(ProviderError, match="not runtime tone") as raised:
        asyncio.run(provider.synthesize("Hello.", options))

    assert raised.value.retryable is False
    asyncio.run(provider._client.aclose())


@pytest.mark.parametrize(
    ("pace", "expected"),
    [
        (SpeechPace.VERY_SLOW, "0.7"),
        (SpeechPace.SLOW, "0.85"),
        (SpeechPace.NORMAL, "1.0"),
        (SpeechPace.FAST, "1.2"),
        (SpeechPace.VERY_FAST, "1.5"),
    ],
)
def test_maps_native_english_pace(pace: SpeechPace, expected: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["speed"] == expected
        return httpx.Response(
            200,
            headers={"Content-Type": "audio/l16;rate=24000"},
            content=b"\x00\x00",
        )

    _run_with_transport(handler, options=_options(pace=pace))


@pytest.mark.parametrize("pace", [SpeechPace.VERY_SLOW, SpeechPace.SLOW])
def test_clamps_slow_spanish_pace_to_documented_minimum(pace: SpeechPace) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["model"] == "aura-2-celeste-es"
        assert request.url.params["speed"] == "0.9"
        return httpx.Response(
            200,
            headers={"Content-Type": "audio/l16;rate=24000"},
            content=b"\x00\x00",
        )

    _run_with_transport(
        handler,
        options=_options(voice="aura-2-celeste-es", pace=pace),
    )


def test_omits_normal_speed_for_languages_without_native_pace_control() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "speed" not in request.url.params
        return httpx.Response(
            200,
            headers={"Content-Type": "audio/l16;rate=24000"},
            content=b"\x00\x00",
        )

    _run_with_transport(handler, options=_options(voice="aura-2-fujin-ja"))


def test_rejects_non_normal_pace_for_unsupported_language_before_request() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    with pytest.raises(ProviderError, match="English and Spanish") as raised:
        _run_with_transport(
            handler,
            options=_options(voice="aura-2-fujin-ja", pace=SpeechPace.SLOW),
        )

    assert raised.value.retryable is False
    assert calls == 0


def test_allows_2000_multibyte_characters() -> None:
    text = "🙂" * 2_000

    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content) == {"text": text}
        return httpx.Response(
            200,
            headers={"Content-Type": "audio/l16;rate=24000"},
            content=b"\x00\x00",
        )

    _run_with_transport(handler, text=text)


def test_rejects_more_than_2000_characters_before_request() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    with pytest.raises(ProviderError, match="2000-character") as raised:
        _run_with_transport(handler, text="🙂" * 2_001)

    assert raised.value.retryable is False
    assert raised.value.status_code == 413
    assert calls == 0


@pytest.mark.parametrize(
    ("content_type", "content", "message", "retryable"),
    [
        ("audio/wav", b"\x00\x00", "content type", False),
        ("audio/l16;rate=16000", b"\x00\x00", "content type", False),
        ("audio/l16;rate=24000", b"", "PCM frame", True),
        ("audio/l16;rate=24000", b"\x00", "PCM frame", True),
    ],
)
def test_rejects_noncanonical_or_invalid_audio(
    content_type: str,
    content: bytes,
    message: str,
    retryable: bool,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, headers={"Content-Type": content_type}, content=content)

    with pytest.raises(ProviderError, match=message) as raised:
        _run_with_transport(handler)

    assert raised.value.retryable is retryable


def test_429_is_retryable_and_preserves_retry_after_and_request_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            429,
            headers={"Retry-After": "12.5"},
            json={
                "err_code": "Too Many Requests",
                "err_msg": "Please try again later.",
                "request_id": "rate-limited-request",
            },
        )

    with pytest.raises(ProviderError, match="rate-limited-request") as raised:
        _run_with_transport(handler)

    assert raised.value.retryable is True
    assert raised.value.status_code == 429
    assert raised.value.retry_after == 12.5


@pytest.mark.parametrize(
    ("status_code", "retryable"),
    [
        (400, False),
        (401, False),
        (402, False),
        (413, False),
        (422, False),
        (500, True),
        (503, True),
    ],
)
def test_classifies_http_errors(status_code: int, retryable: bool) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            status_code,
            json={"err_code": "TEST", "err_msg": "provider message", "request_id": "req"},
        )

    with pytest.raises(ProviderError, match="provider message") as raised:
        _run_with_transport(handler)

    assert raised.value.retryable is retryable
    assert raised.value.status_code == status_code
    assert raised.value.diagnostic is not None
    assert raised.value.diagnostic.category == "http_error"
    assert raised.value.diagnostic.response is not None
    assert raised.value.diagnostic.response["status_code"] == status_code


def test_network_errors_are_retryable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline using deepgram-secret", request=request)

    with pytest.raises(ProviderError, match="offline") as raised:
        _run_with_transport(handler)

    assert raised.value.retryable is True
    assert raised.value.status_code is None
    diagnostic = raised.value.diagnostic
    assert diagnostic is not None
    assert diagnostic.category == "network_error"
    assert diagnostic.phase == "connect"
    assert diagnostic.request is not None
    assert diagnostic.request["headers"]["Authorization"] == "[REDACTED]"  # type: ignore[index]
    assert diagnostic.request["body"] == {"text": "Hello world."}
    assert diagnostic.response is not None
    assert diagnostic.response["received"] is False
    assert "deepgram-secret" not in json.dumps(diagnostic, default=str)


def test_custom_instructions_are_rejected_before_request() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    with pytest.raises(ProviderError, match="custom synthesis instructions") as raised:
        _run_with_transport(handler, options=_options(instructions="Sound dramatic."))

    assert raised.value.retryable is False
    assert calls == 0


def test_missing_credentials_is_permanent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)
    provider = DeepgramTtsProvider()

    with pytest.raises(ProviderError, match="DEEPGRAM_API_KEY") as raised:
        asyncio.run(provider.synthesize("Hello.", _options()))

    assert raised.value.retryable is False


def test_close_does_not_close_injected_client() -> None:
    async def run() -> None:
        transport = httpx.MockTransport(lambda request: httpx.Response(500))
        client = httpx.AsyncClient(transport=transport)
        provider = DeepgramTtsProvider(api_key="secret", client=client)
        await provider.close()
        assert client.is_closed is False
        await client.aclose()

    asyncio.run(run())


def test_owned_client_ignores_environment_proxies_by_default(monkeypatch) -> None:
    captured: list[dict[str, object]] = []
    sentinel = object()

    def create_client(**kwargs):
        captured.append(kwargs)
        return sentinel

    monkeypatch.setattr(deepgram_module.httpx, "AsyncClient", create_client)
    provider = DeepgramTtsProvider(api_key="secret")

    assert provider._get_client() is sentinel
    assert captured == [{"timeout": 300.0, "trust_env": False}]
