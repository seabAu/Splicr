from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from ..diagnostics import (
    error_fingerprint,
    exception_chain,
    no_response_diagnostic,
    proxy_environment_diagnostic,
    request_diagnostic,
    response_diagnostic,
    sanitize_diagnostic,
    sanitize_url,
    transport_error_category,
    transport_error_phase,
    with_provider_diagnostic,
)
from ..domain import (
    AudioChunk,
    CANONICAL_AUDIO_FORMAT,
    ControlMode,
    NonverbalFrequency,
    ProviderCapabilities,
    ProviderDiagnostic,
    ProviderError,
    ProviderInfo,
    SpeechPace,
    SynthesisOptions,
    TonePreset,
    VocalStyle,
    VoiceOption,
)


_MAX_INPUT_CHARACTERS = 2_000
_PACE_VALUES = {
    SpeechPace.VERY_SLOW: "0.7",
    SpeechPace.SLOW: "0.85",
    SpeechPace.NORMAL: "1.0",
    SpeechPace.FAST: "1.2",
    SpeechPace.VERY_FAST: "1.5",
}

# Deepgram combines model generation, voice, and language in one model identifier.
# Traits are display metadata from the official voice catalog, not runtime style controls.
_AURA_2_VOICES = (
    VoiceOption("aura-2-amalthea-en", ("cheerful", "natural", "Filipino")),
    VoiceOption("aura-2-andromeda-en", ("casual", "expressive", "American")),
    VoiceOption("aura-2-apollo-en", ("confident", "casual", "American")),
    VoiceOption("aura-2-arcas-en", ("natural", "smooth", "American")),
    VoiceOption("aura-2-aries-en", ("warm", "energetic", "American")),
    VoiceOption("aura-2-asteria-en", ("clear", "confident", "American")),
    VoiceOption("aura-2-athena-en", ("calm", "storytelling", "American")),
    VoiceOption("aura-2-atlas-en", ("enthusiastic", "friendly", "American")),
    VoiceOption("aura-2-aurora-en", ("cheerful", "expressive", "American")),
    VoiceOption("aura-2-callista-en", ("clear", "professional", "American")),
    VoiceOption("aura-2-cora-en", ("smooth", "storytelling", "American")),
    VoiceOption("aura-2-cordelia-en", ("warm", "storytelling", "American")),
    VoiceOption("aura-2-delia-en", ("casual", "cheerful", "American")),
    VoiceOption("aura-2-draco-en", ("warm", "baritone", "British")),
    VoiceOption("aura-2-electra-en", ("professional", "engaging", "American")),
    VoiceOption("aura-2-harmonia-en", ("empathetic", "calm", "American")),
    VoiceOption("aura-2-helena-en", ("caring", "friendly", "American")),
    VoiceOption("aura-2-hera-en", ("smooth", "warm", "American")),
    VoiceOption("aura-2-hermes-en", ("expressive", "professional", "American")),
    VoiceOption("aura-2-hyperion-en", ("warm", "empathetic", "Australian")),
    VoiceOption("aura-2-iris-en", ("cheerful", "positive", "American")),
    VoiceOption("aura-2-janus-en", ("smooth", "Southern", "American")),
    VoiceOption("aura-2-juno-en", ("natural", "melodic", "American")),
    VoiceOption("aura-2-jupiter-en", ("expressive", "baritone", "American")),
    VoiceOption("aura-2-luna-en", ("friendly", "natural", "American")),
    VoiceOption("aura-2-mars-en", ("smooth", "patient", "American")),
    VoiceOption("aura-2-minerva-en", ("positive", "storytelling", "American")),
    VoiceOption("aura-2-neptune-en", ("professional", "patient", "American")),
    VoiceOption("aura-2-odysseus-en", ("calm", "professional", "American")),
    VoiceOption("aura-2-ophelia-en", ("expressive", "cheerful", "American")),
    VoiceOption("aura-2-orion-en", ("approachable", "calm", "American")),
    VoiceOption("aura-2-orpheus-en", ("clear", "storytelling", "American")),
    VoiceOption("aura-2-pandora-en", ("smooth", "melodic", "British")),
    VoiceOption("aura-2-phoebe-en", ("energetic", "warm", "American")),
    VoiceOption("aura-2-pluto-en", ("calm", "baritone", "American")),
    VoiceOption("aura-2-saturn-en", ("knowledgeable", "baritone", "American")),
    VoiceOption("aura-2-selene-en", ("expressive", "energetic", "American")),
    VoiceOption("aura-2-thalia-en", ("clear", "confident", "American")),
    VoiceOption("aura-2-theia-en", ("expressive", "sincere", "Australian")),
    VoiceOption("aura-2-vesta-en", ("natural", "storytelling", "American")),
    VoiceOption("aura-2-zeus-en", ("deep", "smooth", "American")),
    VoiceOption("aura-2-agustina-es", ("calm", "professional", "Spanish")),
    VoiceOption("aura-2-alvaro-es", ("calm", "clear", "Spanish")),
    VoiceOption("aura-2-antonia-es", ("friendly", "natural", "Argentine")),
    VoiceOption("aura-2-aquila-es", ("expressive", "Latin American", "codeswitching")),
    VoiceOption("aura-2-carina-es", ("professional", "Spanish", "codeswitching")),
    VoiceOption("aura-2-celeste-es", ("clear", "energetic", "Colombian")),
    VoiceOption("aura-2-diana-es", ("professional", "Spanish", "codeswitching")),
    VoiceOption("aura-2-estrella-es", ("natural", "calm", "Mexican")),
    VoiceOption("aura-2-gloria-es", ("clear", "expressive", "Colombian")),
    VoiceOption("aura-2-javier-es", ("professional", "Mexican", "codeswitching")),
    VoiceOption("aura-2-luciano-es", ("cheerful", "energetic", "Mexican")),
    VoiceOption("aura-2-nestor-es", ("calm", "professional", "Spanish")),
    VoiceOption("aura-2-olivia-es", ("calm", "warm", "Mexican")),
    VoiceOption("aura-2-selena-es", ("friendly", "Latin American", "codeswitching")),
    VoiceOption("aura-2-silvia-es", ("clear", "warm", "Spanish")),
    VoiceOption("aura-2-sirio-es", ("calm", "baritone", "Mexican")),
    VoiceOption("aura-2-valerio-es", ("deep", "professional", "Mexican")),
    VoiceOption("aura-2-beatrix-nl", ("cheerful", "warm", "Dutch")),
    VoiceOption("aura-2-cornelia-nl", ("friendly", "warm", "Dutch")),
    VoiceOption("aura-2-daphne-nl", ("calm", "audiobook", "Dutch")),
    VoiceOption("aura-2-hestia-nl", ("caring", "expressive", "Dutch")),
    VoiceOption("aura-2-lars-nl", ("casual", "sincere", "Dutch")),
    VoiceOption("aura-2-leda-nl", ("caring", "empathetic", "Dutch")),
    VoiceOption("aura-2-rhea-nl", ("caring", "smooth", "Dutch")),
    VoiceOption("aura-2-roman-nl", ("calm", "deep", "Dutch")),
    VoiceOption("aura-2-sander-nl", ("calm", "professional", "Dutch")),
    VoiceOption("aura-2-agathe-fr", ("cheerful", "natural", "French")),
    VoiceOption("aura-2-hector-fr", ("empathetic", "patient", "French")),
    VoiceOption("aura-2-aurelia-de", ("natural", "sincere", "German")),
    VoiceOption("aura-2-elara-de", ("calm", "trustworthy", "German")),
    VoiceOption("aura-2-fabian-de", ("confident", "professional", "German")),
    VoiceOption("aura-2-julius-de", ("casual", "friendly", "German")),
    VoiceOption("aura-2-kara-de", ("empathetic", "professional", "German")),
    VoiceOption("aura-2-lara-de", ("caring", "warm", "German")),
    VoiceOption("aura-2-viktoria-de", ("cheerful", "warm", "German")),
    VoiceOption("aura-2-cesare-it", ("clear", "natural", "Italian")),
    VoiceOption("aura-2-cinzia-it", ("friendly", "warm", "Italian")),
    VoiceOption("aura-2-demetra-it", ("calm", "patient", "Italian")),
    VoiceOption("aura-2-dionisio-it", ("confident", "melodic", "Italian")),
    VoiceOption("aura-2-elio-it", ("calm", "smooth", "Italian")),
    VoiceOption("aura-2-flavio-it", ("deep", "professional", "Italian")),
    VoiceOption("aura-2-livia-it", ("clear", "audiobook", "Italian")),
    VoiceOption("aura-2-maia-it", ("energetic", "warm", "Italian")),
    VoiceOption("aura-2-melia-it", ("natural", "friendly", "Italian")),
    VoiceOption("aura-2-perseo-it", ("casual", "smooth", "Italian")),
    VoiceOption("aura-2-ama-ja", ("casual", "natural", "Japanese")),
    VoiceOption("aura-2-ebisu-ja", ("calm", "deep", "Japanese")),
    VoiceOption("aura-2-fujin-ja", ("calm", "professional", "Japanese")),
    VoiceOption("aura-2-izanami-ja", ("clear", "professional", "Japanese")),
    VoiceOption("aura-2-uzume-ja", ("clear", "trustworthy", "Japanese")),
)

_AURA_1_VOICES = tuple(
    VoiceOption(voice_id, ("legacy", "English"))
    for voice_id in (
        "aura-angus-en",
        "aura-arcas-en",
        "aura-asteria-en",
        "aura-athena-en",
        "aura-helios-en",
        "aura-hera-en",
        "aura-luna-en",
        "aura-orion-en",
        "aura-orpheus-en",
        "aura-perseus-en",
        "aura-stella-en",
        "aura-zeus-en",
    )
)


class DeepgramTtsProvider:
    """Deepgram Aura REST adapter returning canonical raw PCM frames."""

    def __init__(
        self,
        *,
        default_model: str = "aura-2",
        default_voice: str = "aura-2-thalia-en",
        provider_name: str = "deepgram",
        api_url: str = "https://api.deepgram.com/v1/speak",
        request_timeout_seconds: float = 300.0,
        minimum_request_interval_seconds: float = 0.0,
        trust_env_proxies: bool = False,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds must be positive")
        if minimum_request_interval_seconds < 0:
            raise ValueError("minimum_request_interval_seconds cannot be negative")

        voices = (*_AURA_2_VOICES, *_AURA_1_VOICES)
        if all(voice.id != default_voice for voice in voices):
            voices = (VoiceOption(default_voice, ("configured",)), *voices)
        normalized_name = provider_name.strip().lower()
        if not normalized_name:
            raise ValueError("provider_name cannot be empty")
        self._info = ProviderInfo(
            name=normalized_name,
            default_model=default_model,
            default_voice=default_voice,
            max_input_bytes=None,
            max_input_tokens=None,
            max_input_characters=_MAX_INPUT_CHARACTERS,
            recommended_chunk_characters=1_900,
            minimum_request_interval_seconds=minimum_request_interval_seconds,
            capabilities=ProviderCapabilities(
                models=("aura-2", "aura-1"),
                voices=voices,
                speech_paces=tuple(SpeechPace),
                pace_modes=(ControlMode.NATIVE_SCALAR,),
                supports_custom_instructions=False,
            ),
        )
        self._api_key = api_key
        self._api_url = api_url
        self._request_timeout_seconds = request_timeout_seconds
        self._trust_env_proxies = trust_env_proxies
        self._client = client
        self._owns_client = client is None

    @property
    def info(self) -> ProviderInfo:
        return self._info

    def estimate_input_tokens(self, text: str, options: SynthesisOptions) -> int:
        del options
        # Deepgram does not publish a token limit. This remains a conservative protocol
        # implementation and is not used when max_input_tokens is None.
        return len(text.encode("utf-8"))

    def estimate_input_characters(self, text: str, options: SynthesisOptions) -> int:
        del options
        return len(text)

    async def synthesize(self, text: str, options: SynthesisOptions) -> AudioChunk:
        self._validate_request(text, options)
        api_key = self._resolve_api_key()
        voice = options.voice.strip()
        params = {
            "model": voice,
            "encoding": "linear16",
            "container": "none",
            "sample_rate": "24000",
        }
        speed = self._speed_for(voice, options.controls.pace)
        if speed is not None:
            params["speed"] = speed

        headers = {
            "Authorization": f"Token {api_key}",
            "Content-Type": "application/json",
        }
        body = {"text": text}
        safe_request = request_diagnostic(
            method="POST",
            endpoint=self._api_url,
            headers=headers,
            query=params,
            body=body,
            known_secrets=self._known_secrets(),
        )
        started = time.perf_counter()
        try:
            response = await self._get_client().post(
                self._api_url,
                params=params,
                headers=headers,
                json=body,
                timeout=self._request_timeout_seconds,
            )
        except httpx.RequestError as error:
            category = transport_error_category(error)
            phase = transport_error_phase(error)
            diagnostic = self._failure_diagnostic(
                category=category,
                phase=phase,
                request=safe_request,
                elapsed_ms=(time.perf_counter() - started) * 1_000,
                error=error,
                no_response_reason=(
                    "No HTTP response was received; the request failed before a response was "
                    "available."
                ),
            )
            safe_message = sanitize_diagnostic(
                str(error).strip() or error.__class__.__name__,
                known_secrets=self._known_secrets(),
            )
            raise ProviderError(
                f"Deepgram request failed: {str(safe_message)[:1000]}",
                retryable=True,
                diagnostic=diagnostic,
            ) from error

        elapsed_ms = (time.perf_counter() - started) * 1_000
        if response.status_code != httpx.codes.OK:
            diagnostic = self._failure_diagnostic(
                category="http_error",
                phase="response",
                request=safe_request,
                elapsed_ms=elapsed_ms,
                response=response,
            )
            raise self._http_error(response, diagnostic=diagnostic)
        try:
            return self._parse_audio(response)
        except ProviderError as error:
            diagnostic = self._failure_diagnostic(
                category="invalid_audio",
                phase="decode_audio",
                request=safe_request,
                elapsed_ms=elapsed_ms,
                response=response,
                error=error,
            )
            raise with_provider_diagnostic(error, diagnostic) from error

    async def close(self) -> None:
        if not self._owns_client or self._client is None:
            return
        client = self._client
        self._client = None
        await client.aclose()

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._request_timeout_seconds,
                trust_env=self._trust_env_proxies,
            )
        return self._client

    def _resolve_api_key(self) -> str:
        value = (self._api_key or os.getenv("DEEPGRAM_API_KEY") or "").strip()
        if not value:
            raise ProviderError(
                "Deepgram API credentials are missing; set DEEPGRAM_API_KEY",
                retryable=False,
            )
        return value

    def _known_secrets(self) -> tuple[str, ...]:
        return tuple(value for value in (self._api_key, os.getenv("DEEPGRAM_API_KEY")) if value)

    def _failure_diagnostic(
        self,
        *,
        category: str,
        phase: str,
        request: dict[str, Any],
        elapsed_ms: float,
        response: httpx.Response | None = None,
        error: BaseException | None = None,
        no_response_reason: str | None = None,
    ) -> ProviderDiagnostic:
        secrets = self._known_secrets()
        return ProviderDiagnostic(
            category=category,
            phase=phase,
            provider=self.info.name,
            method="POST",
            endpoint=sanitize_url(self._api_url, known_secrets=secrets),
            request=request,
            response=(
                response_diagnostic(response, known_secrets=secrets)
                if response is not None
                else no_response_diagnostic(no_response_reason or "No HTTP response was received.")
            ),
            exception=(exception_chain(error, known_secrets=secrets) if error else None),
            metadata={
                "elapsed_ms": round(max(0.0, elapsed_ms), 3),
                "proxy": proxy_environment_diagnostic(trust_env=self._trust_env_proxies),
                "fingerprint": error_fingerprint(
                    category=category,
                    provider=self.info.name,
                    phase=phase,
                    status_code=(response.status_code if response is not None else None),
                    exception=error,
                ),
            },
        )

    @staticmethod
    def _validate_request(text: str, options: SynthesisOptions) -> None:
        if not text.strip():
            raise ProviderError("Deepgram input text cannot be empty", retryable=False)
        if len(text) > _MAX_INPUT_CHARACTERS:
            raise ProviderError(
                "Deepgram input text exceeds the 2000-character limit",
                retryable=False,
                status_code=413,
            )
        if options.instructions and options.instructions.strip():
            raise ProviderError(
                "Deepgram does not support custom synthesis instructions",
                retryable=False,
            )
        controls = options.controls
        if (
            controls.tone is not TonePreset.NEUTRAL
            or controls.vocal_style is not VocalStyle.NATURAL
            or controls.nonverbal_frequency is not NonverbalFrequency.NEVER
        ):
            raise ProviderError(
                "Deepgram supports speaking pace but not runtime tone, vocal style, or "
                "non-verbal controls",
                retryable=False,
            )
        if not options.voice.strip():
            raise ProviderError("Deepgram voice cannot be empty", retryable=False)

    @staticmethod
    def _speed_for(voice: str, pace: SpeechPace) -> str | None:
        # Aura-2 native speed control currently supports English and Spanish. Omitting
        # it for other languages and Aura-1 preserves their normal provider delivery.
        if not voice.startswith("aura-2-") or not voice.endswith(("-en", "-es")):
            if pace is not SpeechPace.NORMAL:
                raise ProviderError(
                    "Deepgram pace control is available only for Aura-2 English and Spanish",
                    retryable=False,
                )
            return None
        if voice.endswith("-es") and pace in {SpeechPace.VERY_SLOW, SpeechPace.SLOW}:
            return "0.9"
        return _PACE_VALUES[pace]

    @staticmethod
    def _parse_audio(response: httpx.Response) -> AudioChunk:
        raw_content_type = response.headers.get("content-type", "")
        content_type = raw_content_type.lower().replace(" ", "")
        if not content_type.startswith("audio/l16") or "rate=24000" not in content_type:
            raise ProviderError(
                "Deepgram returned incompatible audio content type: "
                f"{raw_content_type or 'missing'}",
                retryable=False,
            )
        pcm = response.content
        if not pcm or len(pcm) % CANONICAL_AUDIO_FORMAT.frame_width:
            raise ProviderError("Deepgram returned invalid PCM frame data", retryable=True)
        return AudioChunk(pcm=pcm, format=CANONICAL_AUDIO_FORMAT)

    @classmethod
    def _http_error(
        cls,
        response: httpx.Response,
        *,
        diagnostic: ProviderDiagnostic | None = None,
    ) -> ProviderError:
        status_code = response.status_code
        retryable = status_code == 429 or 500 <= status_code <= 599
        retry_after = cls._parse_retry_after(response.headers.get("retry-after"))
        error_code: str | None = None
        error_message: str | None = None
        request_id = response.headers.get("dg-request-id")
        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError):
            payload = None
        if isinstance(payload, dict):
            raw_code = payload.get("err_code") or payload.get("error_code")
            raw_message = payload.get("err_msg") or payload.get("message")
            raw_request_id = payload.get("request_id")
            error_code = str(raw_code) if raw_code else None
            error_message = str(raw_message) if raw_message else None
            request_id = str(raw_request_id) if raw_request_id else request_id
        if not error_message:
            error_message = response.text.strip()[:1000] or response.reason_phrase

        details = [f"Deepgram request failed ({status_code})"]
        if error_code:
            details.append(error_code)
        if error_message:
            details.append(error_message[:1000])
        if request_id:
            details.append(f"request_id={request_id}")
        return ProviderError(
            ": ".join(details),
            retryable=retryable,
            status_code=status_code,
            retry_after=retry_after,
            diagnostic=diagnostic,
        )

    @staticmethod
    def _parse_retry_after(value: str | None) -> float | None:
        if not value:
            return None
        try:
            return max(0.0, float(value))
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(value)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())
            except (TypeError, ValueError, OverflowError):
                return None
