from __future__ import annotations

import asyncio
import os

import pytest

from splicr.config import Settings
from splicr.domain import CANONICAL_AUDIO_FORMAT, SynthesisOptions, TtsProvider
from splicr.providers.deepgram import DeepgramTtsProvider
from splicr.providers.gemini import GeminiTtsProvider
from splicr.providers.inworld import InworldTtsProvider


_PROVIDER_ENV = "SPLICR_LIVE_PROVIDER"


def _configured_provider(settings: Settings) -> TtsProvider:
    name = os.getenv(_PROVIDER_ENV, "").strip().lower()
    if not name:
        pytest.skip(
            f"set {_PROVIDER_ENV} to gemini, deepgram, or inworld to spend quota on a live check"
        )
    if name == "gemini":
        return GeminiTtsProvider(
            default_model=settings.gemini_model,
            default_voice=settings.gemini_voice,
            request_timeout_seconds=settings.provider_timeout_seconds,
            trust_env_proxies=settings.trust_env_proxies,
        )
    if name == "deepgram":
        return DeepgramTtsProvider(
            default_model=settings.deepgram_model,
            default_voice=settings.deepgram_voice,
            api_url=settings.deepgram_api_url,
            request_timeout_seconds=settings.provider_timeout_seconds,
            minimum_request_interval_seconds=settings.deepgram_pacing_seconds,
            trust_env_proxies=settings.trust_env_proxies,
        )
    if name == "inworld":
        return InworldTtsProvider(
            default_model=settings.inworld_model,
            default_voice=settings.inworld_voice,
            api_url=settings.inworld_api_url,
            request_timeout_seconds=settings.provider_timeout_seconds,
            minimum_request_interval_seconds=settings.inworld_pacing_seconds,
            trust_env_proxies=settings.trust_env_proxies,
        )
    pytest.fail(f"unsupported {_PROVIDER_ENV} value: {name!r}")


@pytest.mark.live_provider
def test_configured_provider_returns_canonical_pcm() -> None:
    """Exercise one real provider only when its opt-in environment variable is set."""

    provider = _configured_provider(Settings.from_env())
    info = provider.info

    async def synthesize_once():
        try:
            return await provider.synthesize(
                "SPLICR live provider acceptance check.",
                SynthesisOptions(model=info.default_model, voice=info.default_voice),
            )
        finally:
            await provider.close()

    audio = asyncio.run(synthesize_once())

    assert audio.pcm
    assert len(audio.pcm) % CANONICAL_AUDIO_FORMAT.frame_width == 0
    assert audio.format == CANONICAL_AUDIO_FORMAT
