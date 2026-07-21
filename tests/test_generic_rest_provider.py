from __future__ import annotations

import asyncio
import base64
import io
import json
import wave
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from typing import Any, Callable

import httpx
import pytest

import splicr.providers.generic_rest as generic_rest_module
from splicr.domain import (
    CANONICAL_AUDIO_FORMAT,
    DeliveryControls,
    NonverbalFrequency,
    ProviderError,
    SpeechPace,
    SynthesisOptions,
    TonePreset,
    VocalStyle,
)
from splicr.providers.generic_rest import (
    GenericRestAuthLocation,
    GenericRestLimitBasis,
    GenericRestResponseMode,
    GenericRestSpec,
    GenericRestTtsProvider,
)


_PCM = b"\x01\x00\x02\x00"


def _wav_bytes(
    pcm: bytes = _PCM,
    *,
    sample_rate: int = 24_000,
    channels: int = 1,
    sample_width: int = 2,
) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as destination:
        destination.setnchannels(channels)
        destination.setsampwidth(sample_width)
        destination.setframerate(sample_rate)
        destination.writeframes(pcm)
    return output.getvalue()


def _options() -> SynthesisOptions:
    return SynthesisOptions(
        model="model-a",
        voice="voice-a",
        instructions="Keep it intimate.",
        controls=DeliveryControls(
            tone=TonePreset.WARM,
            pace=SpeechPace.SLOW,
            vocal_style=VocalStyle.AUDIOBOOK,
            nonverbal_frequency=NonverbalFrequency.RARE,
        ),
    )


def _spec(**changes: Any) -> GenericRestSpec:
    base = GenericRestSpec(
        name="custom-tts",
        url="https://tts.example.test/v1/speech",
        default_model="model-a",
        default_voice="voice-a",
        auth_location=GenericRestAuthLocation.NONE,
        response_mode=GenericRestResponseMode.RAW_PCM16,
    )
    return replace(base, **changes)


def _run(
    spec: GenericRestSpec,
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    text: str = "Hello world.",
    options: SynthesisOptions | None = None,
    api_key: str | None = None,
    follow_redirects: bool = False,
) -> object:
    async def scenario() -> object:
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), follow_redirects=follow_redirects
        )
        provider = GenericRestTtsProvider(spec, api_key=api_key, client=client)
        try:
            return await provider.synthesize(text, options or _options())
        finally:
            await client.aclose()

    return asyncio.run(scenario())


def test_renders_deep_json_arrays_and_preserves_whole_value_types() -> None:
    spec = _spec(
        url="https://{{host}}/v1/{{route}}",
        method="PUT",
        headers={"X-Voice": "voice={{voice}}", "X-Flag": "{{enabled}}"},
        query={"model": "{{model}}", "tags": "{{tags}}"},
        body_template={
            "input": {
                "text": "{{text}}",
                "settings": [
                    {
                        "count": "{{count}}",
                        "enabled": "{{enabled}}",
                        "payload": "{{payload}}",
                        "description": "{{tone}}/{{pace}}/{{vocal_style}}/{{nonverbal_frequency}}",
                    },
                    "instructions={{instructions}}",
                ],
            },
            "{{dynamic_key}}": "{{nullable}}",
        },
        custom_variables={
            "host": "tts.example.test",
            "route": "render",
            "count": 3,
            "enabled": True,
            "payload": {"nested": [1, False]},
            "tags": ["one", "two"],
            "dynamic_key": "metadata",
            "nullable": None,
        },
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PUT"
        assert str(request.url.copy_with(query=None)) == "https://tts.example.test/v1/render"
        assert request.headers["x-voice"] == "voice=voice-a"
        assert request.headers["x-flag"] == "true"
        assert request.url.params.get_list("tags") == ["one", "two"]
        assert request.url.params["model"] == "model-a"
        assert json.loads(request.content) == {
            "input": {
                "text": "Hello world.",
                "settings": [
                    {
                        "count": 3,
                        "enabled": True,
                        "payload": {"nested": [1, False]},
                        "description": "warm/slow/audiobook/rare",
                    },
                    "instructions=Keep it intimate.",
                ],
            },
            "metadata": None,
        }
        return httpx.Response(200, content=_PCM)

    audio = _run(spec, handler)
    assert getattr(audio, "pcm") == _PCM
    assert getattr(audio, "format") == CANONICAL_AUDIO_FORMAT


def test_per_job_variables_override_resource_defaults() -> None:
    spec = _spec(
        body_template={"text": "{{text}}", "locale": "{{locale}}", "metadata": "{{metadata}}"},
        custom_variables={"locale": "en-US", "metadata": {"source": "resource"}},
    )
    options = replace(
        _options(),
        variables={"locale": "fr-FR", "metadata": {"source": "job", "chapter": 4}},
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content) == {
            "text": "Hello world.",
            "locale": "fr-FR",
            "metadata": {"source": "job", "chapter": 4},
        }
        return httpx.Response(200, content=_PCM)

    _run(spec, handler, options=options)


def test_per_job_variables_cannot_supply_secrets_or_replace_builtins() -> None:
    spec = _spec(body_template={"text": "{{text}}"})
    options = replace(_options(), variables={"api_key": "browser-secret", "text": "wrong"})

    with pytest.raises(ProviderError, match="reserved values: api_key, text") as caught:
        _run(spec, lambda _: httpx.Response(200, content=_PCM), options=options)
    assert caught.value.retryable is False


def test_required_custom_variables_must_be_supplied_per_resource_or_job() -> None:
    spec = _spec(
        body_template={"text": "{{text}}", "locale": "{{locale}}"},
        custom_variables={"locale": None},
        required_variables=("locale",),
    )

    with pytest.raises(ProviderError, match="missing required custom variables: locale"):
        _run(spec, lambda _: httpx.Response(200, content=_PCM))

    options = replace(_options(), variables={"locale": "en-US"})

    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["locale"] == "en-US"
        return httpx.Response(200, content=_PCM)

    _run(spec, handler, options=options)


@pytest.mark.parametrize(
    ("location", "name", "prefix", "expected_header", "expected_query"),
    [
        ("header", "X-Api-Key", "Token", "Token top-secret", None),
        ("query", "key", "", None, "top-secret"),
    ],
)
def test_applies_configurable_authentication(
    location: str,
    name: str,
    prefix: str,
    expected_header: str | None,
    expected_query: str | None,
) -> None:
    spec = _spec(auth_location=location, auth_name=name, auth_prefix=prefix)

    def handler(request: httpx.Request) -> httpx.Response:
        if expected_header is not None:
            assert request.headers[name] == expected_header
        if expected_query is not None:
            assert request.url.params[name] == expected_query
        return httpx.Response(200, content=_PCM)

    _run(spec, handler, api_key="top-secret")


def test_api_key_can_be_used_as_an_explicit_template_variable() -> None:
    spec = _spec(
        headers={"X-Secondary-Key": "{{api_key}}"},
        body_template={"text": "{{text}}", "credential": "prefix-{{api_key}}"},
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-secondary-key"] == "top-secret"
        assert json.loads(request.content)["credential"] == "prefix-top-secret"
        return httpx.Response(200, content=_PCM)

    _run(spec, handler, api_key="top-secret")


def test_missing_template_variable_fails_before_network_io() -> None:
    calls = 0
    spec = _spec(body_template={"text": "{{text}}", "region": "{{missing.region}}"})

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=_PCM)

    with pytest.raises(ProviderError, match="missing template variable 'missing.region'") as caught:
        _run(spec, handler)
    assert caught.value.retryable is False
    assert calls == 0


def test_missing_authentication_key_fails_before_network_io() -> None:
    calls = 0
    spec = _spec(auth_location="header")

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=_PCM)

    with pytest.raises(ProviderError, match="API key is not configured") as caught:
        _run(spec, handler)
    assert caught.value.retryable is False
    assert calls == 0


@pytest.mark.parametrize(
    ("mode", "response_factory"),
    [
        (GenericRestResponseMode.RAW_PCM16, lambda: httpx.Response(200, content=_PCM)),
        (
            GenericRestResponseMode.WAV_PCM16,
            lambda: httpx.Response(200, content=_wav_bytes()),
        ),
        (
            GenericRestResponseMode.JSON_BASE64_RAW_PCM16,
            lambda: httpx.Response(
                200,
                json={"data": {"items": [{"audio/bytes": base64.b64encode(_PCM).decode()}]}},
            ),
        ),
        (
            GenericRestResponseMode.JSON_BASE64_WAV,
            lambda: httpx.Response(
                200,
                json={
                    "data": {"items": [{"audio/bytes": base64.b64encode(_wav_bytes()).decode()}]}
                },
            ),
        ),
    ],
)
def test_decodes_all_response_modes_to_canonical_pcm(
    mode: GenericRestResponseMode,
    response_factory: Callable[[], httpx.Response],
) -> None:
    pointer = "/data/items/0/audio~1bytes" if mode.startswith("json_") else ""
    spec = _spec(response_mode=mode, response_json_pointer=pointer)

    audio = _run(spec, lambda _: response_factory())

    assert getattr(audio, "pcm") == _PCM
    assert getattr(audio, "format") == CANONICAL_AUDIO_FORMAT


@pytest.mark.parametrize(
    ("mode", "response", "message", "retryable"),
    [
        ("raw_pcm16", httpx.Response(200, content=b"\x00"), "PCM frame", True),
        ("wav_pcm16", httpx.Response(200, content=b"not-wave"), "invalid WAV", True),
        (
            "json_base64_raw_pcm16",
            httpx.Response(200, text="not-json"),
            "invalid JSON",
            True,
        ),
        (
            "json_base64_raw_pcm16",
            httpx.Response(200, json={"audio": "%%%"}),
            "invalid base64",
            True,
        ),
    ],
)
def test_rejects_invalid_response_audio_and_metadata(
    mode: str, response: httpx.Response, message: str, retryable: bool
) -> None:
    pointer = "/audio" if mode.startswith("json_") else ""
    spec = _spec(response_mode=mode, response_json_pointer=pointer)

    with pytest.raises(ProviderError, match=message) as caught:
        _run(spec, lambda _: response)
    assert caught.value.retryable is retryable


def test_normalizes_wav_rate_and_channels_to_canonical_pcm() -> None:
    resampled = _run(
        _spec(response_mode="wav_pcm16"),
        lambda _: httpx.Response(200, content=_wav_bytes(sample_rate=16_000)),
    )
    stereo = _run(
        _spec(response_mode="wav_pcm16"),
        lambda _: httpx.Response(
            200,
            content=_wav_bytes(
                b"\x00\x10\x00\x30",
                sample_rate=24_000,
                channels=2,
            ),
        ),
    )
    unsigned_8_bit = _run(
        _spec(response_sample_width=1, response_encoding="pcm_u8"),
        lambda _: httpx.Response(200, content=b"\x80\xff"),
    )

    assert getattr(resampled, "format") == CANONICAL_AUDIO_FORMAT
    assert getattr(resampled, "pcm") == b"\x01\x00\x01\x00\x02\x00"
    assert getattr(stereo, "pcm") == b"\x00\x20"
    assert getattr(unsigned_8_bit, "pcm") == b"\x00\x00\x00\x7f"


def test_rejects_missing_json_pointer_value() -> None:
    spec = _spec(response_mode="json_base64_raw_pcm16", response_json_pointer="/result/audio")
    with pytest.raises(ProviderError, match="pointer '/result/audio' was not found") as caught:
        _run(spec, lambda _: httpx.Response(200, json={"result": {}}))
    assert caught.value.retryable is True


@pytest.mark.parametrize(
    ("status", "retryable"),
    [
        (400, False),
        (401, False),
        (408, True),
        (422, False),
        (425, True),
        (429, True),
        (500, True),
        (503, True),
    ],
)
def test_classifies_http_failures(status: int, retryable: bool) -> None:
    spec = _spec()
    with pytest.raises(ProviderError) as caught:
        _run(spec, lambda _: httpx.Response(status, text="provider failure"))
    assert caught.value.status_code == status
    assert caught.value.retryable is retryable


def test_honors_numeric_and_http_date_retry_after() -> None:
    spec = _spec()

    with pytest.raises(ProviderError) as numeric:
        _run(
            spec,
            lambda _: httpx.Response(429, headers={"Retry-After": "7.5"}, text="slow"),
        )
    assert numeric.value.retry_after == 7.5

    retry_at = datetime.now(timezone.utc) + timedelta(seconds=30)
    with pytest.raises(ProviderError) as dated:
        _run(
            spec,
            lambda _: httpx.Response(
                503, headers={"Retry-After": format_datetime(retry_at)}, text="slow"
            ),
        )
    assert dated.value.retry_after is not None
    assert 25 <= dated.value.retry_after <= 30


def test_network_failures_are_retryable_and_redact_the_secret() -> None:
    secret = "s3cr+t/key"
    spec = _spec(auth_location="query", auth_name="key", auth_prefix="")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"could not connect using {secret}", request=request)

    with pytest.raises(ProviderError) as caught:
        _run(spec, handler, api_key=secret)
    assert caught.value.retryable is True
    assert secret not in str(caught.value)
    assert "[REDACTED]" in str(caught.value)
    assert caught.value.__cause__ is None
    diagnostic = caught.value.diagnostic
    assert diagnostic is not None
    assert diagnostic.category == "network_error"
    assert diagnostic.phase == "connect"
    assert diagnostic.request is not None
    assert diagnostic.request["query"]["key"] == "[REDACTED]"  # type: ignore[index]
    assert diagnostic.request["body"]["text"] == "Hello world."  # type: ignore[index]
    assert diagnostic.response is not None
    assert diagnostic.response["received"] is False
    assert secret not in json.dumps(diagnostic, default=str)


def test_http_error_body_is_truncated_and_never_exposes_secret() -> None:
    secret = "s3cr+t/key"
    spec = _spec(auth_location="header")
    body = f"credential={secret}; encoded=s3cr%2Bt%2Fkey; " + ("x" * 5_000)

    with pytest.raises(ProviderError) as caught:
        _run(spec, lambda _: httpx.Response(400, text=body), api_key=secret)

    message = str(caught.value)
    assert secret not in message
    assert "s3cr%2Bt%2Fkey" not in message
    assert "[REDACTED]" in message
    assert len(message) < 1_100
    assert caught.value.diagnostic is not None
    assert secret not in json.dumps(caught.value.diagnostic, default=str)
    assert caught.value.diagnostic.response is not None
    assert caught.value.diagnostic.response["status_code"] == 400


def test_redirects_are_disabled_even_when_injected_client_defaults_to_following() -> None:
    calls: list[str] = []
    spec = _spec()

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if len(calls) == 1:
            return httpx.Response(307, headers={"Location": "https://tts.example.test/other"})
        return httpx.Response(200, content=_PCM)

    with pytest.raises(ProviderError) as caught:
        _run(spec, handler, follow_redirects=True)
    assert caught.value.status_code == 307
    assert calls == ["https://tts.example.test/v1/speech"]


@pytest.mark.parametrize(
    ("changes", "text", "message"),
    [
        ({"max_input_characters": 3}, "four", "4 characters; limit is 3"),
        ({"max_input_bytes": 3}, "éé", "4 UTF-8 bytes; limit is 3"),
        ({"max_input_tokens": 1}, "token", "2 estimated tokens; limit is 1"),
        ({"max_input_words": 2}, "one two three", "3 words; limit is 2"),
    ],
)
def test_enforces_text_limits_before_network_io(
    changes: dict[str, Any], text: str, message: str
) -> None:
    calls = 0
    spec = _spec(**changes)

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=_PCM)

    with pytest.raises(ProviderError, match=message):
        _run(spec, handler, text=text)
    assert calls == 0


def test_body_limit_counts_rendered_json_and_estimator_uses_same_basis() -> None:
    spec = _spec(
        body_template={"input": "prefix {{text}}", "enabled": True},
        limit_basis=GenericRestLimitBasis.BODY,
    )
    provider = GenericRestTtsProvider(spec)
    expected = len('{"input":"prefix Hi","enabled":true}')
    assert provider.estimate_input_characters("Hi", _options()) == expected

    limited = replace(spec, max_input_characters=expected - 1)
    with pytest.raises(ProviderError, match=f"{expected} characters"):
        _run(limited, lambda _: httpx.Response(200, content=_PCM), text="Hi")


def test_spec_freezes_nested_templates_and_validates_raw_metadata() -> None:
    nested = {"settings": {"values": [1, 2]}}
    spec = _spec(body_template=nested)
    nested["settings"]["values"].append(3)  # type: ignore[index,union-attr]

    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content) == {"settings": {"values": [1, 2]}}
        return httpx.Response(200, content=_PCM)

    _run(spec, handler)

    assert _spec(response_sample_rate=16_000).response_sample_rate == 16_000

    with pytest.raises(ValueError, match="8-bit PCM requires pcm_u8"):
        _spec(response_sample_width=1)

    with pytest.raises(ValueError, match="api_key must be supplied separately"):
        _spec(custom_variables={"api_key": "must-not-be-persisted-here"})


def test_non_json_request_body_fails_before_network_io() -> None:
    calls = 0
    spec = _spec(body_template={"bad": object()})

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=_PCM)

    with pytest.raises(ProviderError, match="request body is not valid JSON") as caught:
        _run(spec, handler)
    assert caught.value.retryable is False
    assert calls == 0


def test_provider_metadata_reflects_endpoint_spec() -> None:
    provider = GenericRestTtsProvider(
        _spec(
            models=("model-b",),
            voices=("voice-b",),
            max_input_characters=2_000,
            max_input_bytes=4_000,
            max_input_tokens=500,
            max_input_words=350,
            recommended_chunk_characters=1_900,
            minimum_request_interval_seconds=1.25,
        )
    )
    assert provider.info.name == "custom-tts"
    assert provider.info.max_input_characters == 2_000
    assert provider.info.max_input_bytes == 4_000
    assert provider.info.max_input_tokens == 500
    assert provider.info.recommended_chunk_words == 350
    assert provider.info.recommended_chunk_characters == 1_900
    assert provider.info.minimum_request_interval_seconds == 1.25
    assert provider.info.capabilities.models == ("model-a", "model-b")
    assert tuple(voice.id for voice in provider.info.capabilities.voices) == (
        "voice-a",
        "voice-b",
    )


def test_close_only_closes_an_internally_owned_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.closed = False

        async def request(self, *_: Any, **__: Any) -> httpx.Response:
            return httpx.Response(200, content=_PCM)

        async def aclose(self) -> None:
            self.closed = True

    owned = FakeClient()
    injected = FakeClient()
    construction: list[dict[str, Any]] = []

    def create_client(**kwargs: Any) -> FakeClient:
        construction.append(kwargs)
        return owned

    monkeypatch.setattr(generic_rest_module.httpx, "AsyncClient", create_client)

    async def scenario() -> None:
        owner = GenericRestTtsProvider(_spec())
        borrower = GenericRestTtsProvider(_spec(), client=injected)  # type: ignore[arg-type]
        await owner.synthesize("Hello.", _options())
        await owner.close()
        await borrower.close()

    asyncio.run(scenario())

    assert construction == [{"follow_redirects": False, "trust_env": False}]
    assert owned.closed is True
    assert injected.closed is False
