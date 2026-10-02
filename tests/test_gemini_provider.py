from __future__ import annotations

import asyncio
import base64
import json
from types import SimpleNamespace
from typing import Any

import pytest
import google.genai
import httpx
from google.genai.interactions import Interaction

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
from splicr.delivery import NONVERBAL_CUE_MARKER_PREFIX, NONVERBAL_CUE_MARKER_SUFFIX
from splicr.providers.gemini import GeminiTtsProvider


class FakeInteractions:
    def __init__(
        self,
        output_audio: Any,
        *,
        status: str = "completed",
        interaction: Any | None = None,
    ) -> None:
        self.output_audio = output_audio
        self.status = status
        self.interaction = interaction
        self.kwargs: dict[str, Any] = {}

    async def create(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        return self.interaction or SimpleNamespace(
            status=self.status,
            output_audio=self.output_audio,
        )


class FailingInteractions:
    async def create(self, **_: Any) -> Any:
        request = httpx.Request(
            "POST", "https://generativelanguage.googleapis.com/v1beta/interactions"
        )
        raise httpx.ConnectError(
            "connection failed using gemini-secret",
            request=request,
        )


def test_uses_interactions_api_and_decodes_canonical_pcm() -> None:
    pcm = b"\x01\x00\x02\x00"
    interactions = FakeInteractions(
        SimpleNamespace(
            data=base64.b64encode(pcm).decode("ascii"),
            mime_type="audio/l16",
            sample_rate=24_000,
            channels=1,
        )
    )
    provider = GeminiTtsProvider(
        client=SimpleNamespace(aio=SimpleNamespace(interactions=interactions))
    )

    audio = asyncio.run(
        provider.synthesize(
            "Hello world.",
            SynthesisOptions(
                model="gemini-3.1-flash-tts-preview",
                voice="Kore",
                instructions="Speak calmly.",
            ),
        )
    )

    assert audio.pcm == pcm
    assert interactions.kwargs["response_format"] == {"type": "audio"}
    assert interactions.kwargs["generation_config"] == {"speech_config": [{"voice": "Kore"}]}
    assert interactions.kwargs["store"] is False
    assert "### DIRECTOR'S NOTES" in interactions.kwargs["input"]
    assert "### TRANSCRIPT\n\nHello world." in interactions.kwargs["input"]


def test_installed_google_sdk_exposes_the_v2_audio_contract() -> None:
    assert int(google.genai.__version__.split(".", 1)[0]) >= 2
    pcm = b"\x01\x00\x02\x00"
    interaction = Interaction.model_validate(
        {
            "status": "completed",
            "steps": [
                {
                    "type": "model_output",
                    "content": [
                        {
                            "type": "audio",
                            "data": base64.b64encode(pcm).decode("ascii"),
                            "mime_type": "audio/l16",
                            "sample_rate": 24_000,
                            "channels": 1,
                        }
                    ],
                }
            ],
        }
    )
    assert interaction.output_audio is not None
    interactions = FakeInteractions(interaction.output_audio, interaction=interaction)
    provider = GeminiTtsProvider(
        client=SimpleNamespace(aio=SimpleNamespace(interactions=interactions))
    )

    audio = asyncio.run(
        provider.synthesize("SDK contract.", SynthesisOptions(model="model", voice="Kore"))
    )

    assert audio.pcm == pcm


def test_network_failure_includes_redacted_request_and_exception_diagnostics() -> None:
    provider = GeminiTtsProvider(
        api_key="gemini-secret",
        client=SimpleNamespace(aio=SimpleNamespace(interactions=FailingInteractions())),
    )

    with pytest.raises(ProviderError, match="connection failed") as raised:
        asyncio.run(
            provider.synthesize(
                "Diagnostic text.",
                SynthesisOptions(model="gemini-model", voice="Kore"),
            )
        )

    diagnostic = raised.value.diagnostic
    assert diagnostic is not None
    assert diagnostic.category == "network_error"
    assert diagnostic.phase == "connect"
    assert diagnostic.request is not None
    assert diagnostic.request["headers"]["X-Goog-Api-Key"] == "[REDACTED]"  # type: ignore[index]
    assert "Diagnostic text." in diagnostic.request["body"]["input"]  # type: ignore[index,operator]
    assert diagnostic.response is not None
    assert diagnostic.response["received"] is False
    assert "gemini-secret" not in json.dumps(diagnostic, default=str)


def test_sdk_clients_ignore_environment_proxies_by_default(monkeypatch) -> None:
    captured: list[Any] = []
    sentinel = object()

    def create_client(**kwargs: Any) -> object:
        captured.append(kwargs["http_options"])
        return sentinel

    monkeypatch.setattr(google.genai, "Client", create_client)
    provider = GeminiTtsProvider(api_key="gemini-secret")

    assert provider._get_client() is sentinel
    assert captured[0].client_args == {"trust_env": False}
    assert captured[0].async_client_args == {"trust_env": False}


def test_accepts_documented_default_pcm_when_optional_metadata_is_omitted() -> None:
    pcm = b"\x01\x00\x02\x00"
    interactions = FakeInteractions(SimpleNamespace(data=base64.b64encode(pcm).decode("ascii")))
    provider = GeminiTtsProvider(
        client=SimpleNamespace(aio=SimpleNamespace(interactions=interactions))
    )

    audio = asyncio.run(
        provider.synthesize("Default format.", SynthesisOptions(model="model", voice="Kore"))
    )

    assert audio.pcm == pcm
    assert audio.format.sample_rate == 24_000
    assert audio.format.channels == 1


@pytest.mark.parametrize(
    "mime_type,sample_rate,channels",
    [
        ("audio/l16; rate=24000; channels=1", 24_000, 1),
        ("audio/L16; RATE=24000; CHANNELS=1", None, None),
    ],
)
def test_accepts_canonical_pcm_mime_parameters(
    mime_type: str,
    sample_rate: int | None,
    channels: int | None,
) -> None:
    pcm = b"\x01\x00\x02\x00"
    interactions = FakeInteractions(
        SimpleNamespace(
            data=base64.b64encode(pcm).decode("ascii"),
            mime_type=mime_type,
            sample_rate=sample_rate,
            channels=channels,
        )
    )
    provider = GeminiTtsProvider(
        client=SimpleNamespace(aio=SimpleNamespace(interactions=interactions))
    )

    audio = asyncio.run(
        provider.synthesize("Parameterized format.", SynthesisOptions(model="model", voice="Kore"))
    )

    assert audio.pcm == pcm
    assert audio.format == CANONICAL_AUDIO_FORMAT


def test_rejects_conflicting_pcm_mime_parameters() -> None:
    interactions = FakeInteractions(
        SimpleNamespace(
            data=base64.b64encode(b"\x00\x00").decode("ascii"),
            mime_type="audio/l16; rate=16000; channels=1",
            sample_rate=24_000,
            channels=1,
        )
    )
    provider = GeminiTtsProvider(
        client=SimpleNamespace(aio=SimpleNamespace(interactions=interactions))
    )

    with pytest.raises(ProviderError, match="conflicting PCM sample-rate"):
        asyncio.run(
            provider.synthesize("Conflicting format.", SynthesisOptions(model="model", voice="Kore"))
        )


@pytest.mark.parametrize(
    "mime_type",
    ["audio/l16; rate", "audio/l16; rate=not-a-number"],
)
def test_rejects_invalid_pcm_mime_parameters(mime_type: str) -> None:
    interactions = FakeInteractions(
        SimpleNamespace(
            data=base64.b64encode(b"\x00\x00").decode("ascii"),
            mime_type=mime_type,
            sample_rate=None,
            channels=None,
        )
    )
    provider = GeminiTtsProvider(
        client=SimpleNamespace(aio=SimpleNamespace(interactions=interactions))
    )

    with pytest.raises(ProviderError, match="invalid audio format metadata") as raised:
        asyncio.run(
            provider.synthesize("Invalid format.", SynthesisOptions(model="model", voice="Kore"))
        )

    assert raised.value.retryable is True


@pytest.mark.parametrize(
    "mime_type",
    ["audio/l16; rate=0; channels=1", "audio/l16; rate=24000; channels=0"],
)
def test_rejects_zero_pcm_mime_parameters(mime_type: str) -> None:
    interactions = FakeInteractions(
        SimpleNamespace(
            data=base64.b64encode(b"\x00\x00").decode("ascii"),
            mime_type=mime_type,
            sample_rate=None,
            channels=None,
        )
    )
    provider = GeminiTtsProvider(
        client=SimpleNamespace(aio=SimpleNamespace(interactions=interactions))
    )

    with pytest.raises(ProviderError, match="incompatible PCM"):
        asyncio.run(
            provider.synthesize("Invalid format.", SynthesisOptions(model="model", voice="Kore"))
        )


def test_rejects_non_pcm_response() -> None:
    interactions = FakeInteractions(
        SimpleNamespace(
            data=base64.b64encode(b"fake-mp3").decode("ascii"),
            mime_type="audio/mp3",
            sample_rate=24_000,
            channels=1,
        )
    )
    provider = GeminiTtsProvider(
        client=SimpleNamespace(aio=SimpleNamespace(interactions=interactions))
    )

    with pytest.raises(ProviderError, match="unsupported") as raised:
        asyncio.run(provider.synthesize("Hello.", SynthesisOptions(model="model", voice="voice")))

    assert raised.value.retryable is False


@pytest.mark.parametrize(
    ("sample_rate", "channels"),
    [(22_050, 1), (24_000, 2)],
)
def test_rejects_reported_noncanonical_pcm(sample_rate: int, channels: int) -> None:
    interactions = FakeInteractions(
        SimpleNamespace(
            data=base64.b64encode(b"\x00\x00").decode("ascii"),
            mime_type="audio/l16",
            sample_rate=sample_rate,
            channels=channels,
        )
    )
    provider = GeminiTtsProvider(
        client=SimpleNamespace(aio=SimpleNamespace(interactions=interactions))
    )

    with pytest.raises(ProviderError, match="incompatible"):
        asyncio.run(provider.synthesize("Hello.", SynthesisOptions(model="model", voice="voice")))


def test_rejects_incomplete_interaction_even_when_partial_audio_exists() -> None:
    interactions = FakeInteractions(
        SimpleNamespace(
            data=base64.b64encode(b"\x00\x00").decode("ascii"),
            mime_type="audio/l16",
            sample_rate=24_000,
            channels=1,
        ),
        status="incomplete",
    )
    provider = GeminiTtsProvider(
        client=SimpleNamespace(aio=SimpleNamespace(interactions=interactions))
    )

    with pytest.raises(ProviderError, match="incomplete") as raised:
        asyncio.run(provider.synthesize("Hello.", SynthesisOptions(model="model", voice="voice")))

    assert raised.value.retryable is True


def test_delivery_presets_and_audio_tags_render_into_the_measured_prompt() -> None:
    options = SynthesisOptions(
        model="gemini-3.1-flash-tts-preview",
        voice="Kore",
        instructions="Keep quotations distinct.",
        controls=DeliveryControls(
            tone=TonePreset.WARM,
            pace=SpeechPace.SLOW,
            vocal_style=VocalStyle.AUDIOBOOK,
            nonverbal_frequency=NonverbalFrequency.OCCASIONAL,
        ),
    )
    transcript = (
        "Read [Appendix A]. "
        f"{NONVERBAL_CUE_MARKER_PREFIX}sighs{NONVERBAL_CUE_MARKER_SUFFIX} Continue."
    )

    prompt = GeminiTtsProvider._render_prompt(transcript, options)

    assert "Tone and emotion: warm and reassuring." in prompt
    assert "Speaking pace: slow and deliberate." in prompt
    assert "Vocal style: polished long-form audiobook narration." in prompt
    assert "never speak the marker aloud" in prompt
    assert "every other bracketed passage as literal transcript wording" in prompt
    assert "### DIRECTOR'S NOTES\n\nKeep quotations distinct." in prompt
    assert prompt.endswith(f"### TRANSCRIPT\n\n{transcript}")
    assert GeminiTtsProvider().estimate_input_tokens(transcript, options) == len(
        prompt.encode("utf-8")
    )


def test_default_controls_preserve_the_legacy_prompt_shape() -> None:
    options = SynthesisOptions(model="model", voice="Kore")

    prompt = GeminiTtsProvider._render_prompt("Hello.", options)

    assert "### DELIVERY PRESET" not in prompt
    assert "### DIRECTOR'S NOTES" not in prompt
    assert prompt == (
        "Synthesize speech from the transcript below. Speak only the transcript; do not read "
        "section headings or these instructions aloud. Preserve the wording and order exactly."
        "\n\n### TRANSCRIPT\n\nHello."
    )


def test_markdown_structure_is_rendered_as_delivery_metadata_not_spoken_punctuation() -> None:
    options = SynthesisOptions(model="model", voice="Kore")

    prompt = GeminiTtsProvider._render_prompt("# Chapter\nRead **this** carefully.", options)

    assert "silent document structure" in prompt
    assert "never speak the Markdown punctuation" in prompt
