from __future__ import annotations

import asyncio
import base64
import io
import json
import wave
from typing import Any

import httpx
import pytest

import splicr.providers.inworld as inworld_module
from splicr.domain import (
    DeliveryControls,
    NONVERBAL_CUE_MARKER_PREFIX,
    NONVERBAL_CUE_MARKER_SUFFIX,
    ProviderError,
    SpeechPace,
    SynthesisOptions,
    TonePreset,
    VocalStyle,
)
from splicr.providers.inworld import InworldTtsProvider


def _wav_bytes(
    pcm: bytes,
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


def _success_body(pcm: bytes = b"\x01\x00\x02\x00") -> dict[str, Any]:
    return {"audioContent": base64.b64encode(_wav_bytes(pcm)).decode("ascii")}


def test_posts_explicit_wav_request_and_returns_canonical_pcm_frames() -> None:
    pcm = b"\x01\x00\x02\x00"
    captured: dict[str, Any] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["Authorization"]
        captured["content_type"] = request.headers["Content-Type"]
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json=_success_body(pcm))

    options = SynthesisOptions(
        model="inworld-tts-2",
        voice="Dennis",
        instructions="Keep [quoted] words distinct.\nNo mumbling.",
        controls=DeliveryControls(
            tone=TonePreset.WARM,
            pace=SpeechPace.SLOW,
            vocal_style=VocalStyle.AUDIOBOOK,
        ),
    )
    text = (
        "One. "
        f"{NONVERBAL_CUE_MARKER_PREFIX}sighs{NONVERBAL_CUE_MARKER_SUFFIX} Two."
    )
    expected_text = (
        "[Use a warm and reassuring tone. Use polished long-form audiobook narration. "
        "Keep (quoted) words distinct. "
        "No mumbling.]\nOne. [sigh] Two."
    )

    async def scenario() -> tuple[Any, int, Any]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            provider = InworldTtsProvider(
                api_key="already-base64-api-key",
                client=client,
                minimum_request_interval_seconds=0.25,
            )
            audio = await provider.synthesize(text, options)
            return audio, provider.estimate_input_characters(text, options), provider.info

    audio, measured_characters, info = asyncio.run(scenario())

    assert audio.pcm == pcm
    assert audio.format.sample_rate == 24_000
    assert audio.format.channels == 1
    assert captured["url"] == "https://api.inworld.ai/tts/v1/voice"
    assert captured["authorization"] == "Basic already-base64-api-key"
    assert captured["content_type"] == "application/json"
    assert captured["payload"] == {
        "text": expected_text,
        "voiceId": "Dennis",
        "modelId": "inworld-tts-2",
        "audioConfig": {
            "audioEncoding": "WAV",
            "sampleRateHertz": 24_000,
            "speakingRate": 0.75,
        },
        "deliveryMode": "BALANCED",
        "applyTextNormalization": "ON",
    }
    assert measured_characters == len(expected_text)
    assert info.max_input_characters == 2_000
    assert info.minimum_request_interval_seconds == 0.25


@pytest.mark.parametrize(
    ("cue", "tag"),
    [
        ("laughs", "[laugh]"),
        ("giggles", "[laugh]"),
        ("gasp", "[breathe]"),
        ("clear-throat", "[clear throat]"),
        ("sighs", "[sigh]"),
        ("coughs", "[cough]"),
        ("yawns", "[yawn]"),
    ],
)
def test_replaces_splicr_cue_aliases_with_supported_inworld_tags(cue: str, tag: str) -> None:
    marker = f"{NONVERBAL_CUE_MARKER_PREFIX}{cue}{NONVERBAL_CUE_MARKER_SUFFIX}"

    assert InworldTtsProvider._replace_cue_markers(f"Before {marker} after") == (
        f"Before {tag} after"
    )


def test_rejects_unknown_reserved_cue_before_network_io() -> None:
    marker = f"{NONVERBAL_CUE_MARKER_PREFIX}applause{NONVERBAL_CUE_MARKER_SUFFIX}"

    with pytest.raises(ProviderError, match="does not support") as raised:
        InworldTtsProvider._replace_cue_markers(marker)

    assert raised.value.retryable is False
    assert raised.value.status_code == 400


def test_enforces_2000_character_limit_after_steering_is_added() -> None:
    options = SynthesisOptions(
        model="inworld-tts-2",
        voice="Dennis",
        instructions="Read every word precisely.",
    )
    text = "x" * 1_990
    provider = InworldTtsProvider(api_key="key", client=httpx.AsyncClient())

    assert provider.estimate_input_characters(text, options) > 2_000
    with pytest.raises(ProviderError, match="2000-character limit") as raised:
        asyncio.run(provider.synthesize(text, options))

    assert raised.value.retryable is False
    assert raised.value.status_code == 400
    asyncio.run(provider._client.aclose())


def test_non_tts2_model_disables_steering_and_omits_delivery_mode() -> None:
    captured: dict[str, Any] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json=_success_body(b"\x00\x01"))

    async def scenario() -> InworldTtsProvider:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            provider = InworldTtsProvider(
                default_model="inworld-tts-1.5-max",
                api_key="key",
                client=client,
            )
            await provider.synthesize(
                "Hello.",
                SynthesisOptions(
                    model="inworld-tts-1.5-max",
                    voice="Dennis",
                    controls=DeliveryControls(pace=SpeechPace.FAST),
                ),
            )
            return provider

    provider = asyncio.run(scenario())

    assert captured["payload"]["audioConfig"]["speakingRate"] == 1.25
    assert "deliveryMode" not in captured["payload"]
    assert provider.info.capabilities.supports_custom_instructions is False
    assert provider.info.capabilities.tone_presets == ()
    assert provider.info.capabilities.nonverbal_cues == ()


def test_non_tts2_model_rejects_tts2_only_controls_before_io() -> None:
    provider = InworldTtsProvider(api_key="key", client=httpx.AsyncClient())
    options = SynthesisOptions(
        model="inworld-tts-1.5-mini",
        voice="Dennis",
        controls=DeliveryControls(tone=TonePreset.WARM),
    )

    with pytest.raises(ProviderError, match="require the inworld-tts-2 model") as raised:
        asyncio.run(provider.synthesize("Hello.", options))

    assert raised.value.retryable is False
    asyncio.run(provider._client.aclose())


@pytest.mark.parametrize(
    ("status_code", "body", "retryable", "reported_status", "retry_after"),
    [
        (429, {"error": {"message": "quota reached"}}, True, 429, 12.5),
        (
            400,
            {"error": {"code": 8, "message": "RESOURCE_EXHAUSTED"}},
            True,
            429,
            None,
        ),
        (503, {"error": {"message": "unavailable"}}, True, 503, None),
        (401, {"error": {"message": "bad credentials"}}, False, 401, None),
        (400, {"error": {"message": "bad request"}}, False, 400, None),
    ],
)
def test_classifies_provider_failures(
    status_code: int,
    body: dict[str, Any],
    retryable: bool,
    reported_status: int,
    retry_after: float | None,
) -> None:
    headers = {"Retry-After": "12.5"} if retry_after is not None else None

    def handle(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=body, headers=headers)

    async def scenario() -> ProviderError:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            provider = InworldTtsProvider(api_key="key", client=client)
            with pytest.raises(ProviderError) as raised:
                await provider.synthesize(
                    "Hello.", SynthesisOptions(model="inworld-tts-2", voice="Dennis")
                )
            return raised.value

    error = asyncio.run(scenario())

    assert error.retryable is retryable
    assert error.status_code == reported_status
    assert error.retry_after == retry_after


def test_classifies_network_failures_as_retryable() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network offline", request=request)

    async def scenario() -> ProviderError:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            provider = InworldTtsProvider(api_key="key", client=client)
            with pytest.raises(ProviderError, match="network offline") as raised:
                await provider.synthesize(
                    "Hello.", SynthesisOptions(model="inworld-tts-2", voice="Dennis")
                )
            return raised.value

    error = asyncio.run(scenario())

    assert error.retryable is True
    assert error.status_code is None


def test_classifies_error_payload_on_http_200_as_permanent() -> None:
    def handle(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": {"code": 3, "message": "invalid voice"}})

    async def scenario() -> ProviderError:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            provider = InworldTtsProvider(api_key="key", client=client)
            with pytest.raises(ProviderError, match="invalid voice") as raised:
                await provider.synthesize(
                    "Hello.", SynthesisOptions(model="inworld-tts-2", voice="missing")
                )
            return raised.value

    error = asyncio.run(scenario())

    assert error.retryable is False
    assert error.status_code == 400


@pytest.mark.parametrize(
    ("sample_rate", "channels", "sample_width"),
    [(22_050, 1, 2), (24_000, 2, 2), (24_000, 1, 1)],
)
def test_rejects_noncanonical_wav(
    sample_rate: int,
    channels: int,
    sample_width: int,
) -> None:
    wav_data = _wav_bytes(
        b"\x00\x00\x00\x00",
        sample_rate=sample_rate,
        channels=channels,
        sample_width=sample_width,
    )
    body = {"audioContent": base64.b64encode(wav_data).decode("ascii")}

    def handle(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    async def scenario() -> ProviderError:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            provider = InworldTtsProvider(api_key="key", client=client)
            with pytest.raises(ProviderError, match="incompatible WAV") as raised:
                await provider.synthesize(
                    "Hello.", SynthesisOptions(model="inworld-tts-2", voice="Dennis")
                )
            return raised.value

    error = asyncio.run(scenario())

    assert error.retryable is False


def test_rejects_invalid_base64_audio_as_retryable() -> None:
    def handle(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"audioContent": "not base64!"})

    async def scenario() -> ProviderError:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            provider = InworldTtsProvider(api_key="key", client=client)
            with pytest.raises(ProviderError, match="invalid base64") as raised:
                await provider.synthesize(
                    "Hello.", SynthesisOptions(model="inworld-tts-2", voice="Dennis")
                )
            return raised.value

    assert asyncio.run(scenario()).retryable is True


def test_closes_only_an_internally_owned_http_client(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.closed = False

        async def post(self, *_: Any, **__: Any) -> httpx.Response:
            return httpx.Response(200, json=_success_body())

        async def aclose(self) -> None:
            self.closed = True

    owned = FakeClient()
    injected = FakeClient()
    monkeypatch.setattr(inworld_module.httpx, "AsyncClient", lambda **_: owned)

    async def scenario() -> None:
        owner = InworldTtsProvider(api_key="key")
        borrower = InworldTtsProvider(api_key="key", client=injected)  # type: ignore[arg-type]
        await owner.synthesize(
            "Hello.", SynthesisOptions(model="inworld-tts-2", voice="Dennis")
        )
        await owner.close()
        await borrower.close()

    asyncio.run(scenario())

    assert owned.closed is True
    assert injected.closed is False
