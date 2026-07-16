from __future__ import annotations

from .config import Settings
from .providers import ProviderRegistry
from .providers.deepgram import DeepgramTtsProvider
from .providers.gemini import GeminiTtsProvider
from .providers.inworld import InworldTtsProvider
from .service import SynthesisService


def create_service(settings: Settings) -> SynthesisService:
    providers = ProviderRegistry(
        [
            GeminiTtsProvider(
                default_model=settings.gemini_model,
                default_voice=settings.gemini_voice,
                request_timeout_seconds=settings.provider_timeout_seconds,
            ),
            DeepgramTtsProvider(
                default_model=settings.deepgram_model,
                default_voice=settings.deepgram_voice,
                api_url=settings.deepgram_api_url,
                request_timeout_seconds=settings.provider_timeout_seconds,
                minimum_request_interval_seconds=settings.deepgram_pacing_seconds,
            ),
            InworldTtsProvider(
                default_model=settings.inworld_model,
                default_voice=settings.inworld_voice,
                api_url=settings.inworld_api_url,
                request_timeout_seconds=settings.provider_timeout_seconds,
                minimum_request_interval_seconds=settings.inworld_pacing_seconds,
            ),
        ]
    )
    return SynthesisService(settings=settings, providers=providers)
