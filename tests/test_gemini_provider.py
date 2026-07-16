from __future__ import annotations

import asyncio
import base64
from types import SimpleNamespace
from typing import Any

import pytest
import google.genai
from google.genai.interactions import Interaction

from splicr.domain import (
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
