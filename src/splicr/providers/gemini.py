from __future__ import annotations

import asyncio
import base64
import binascii
import os
import re
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
    AudioFormat,
    CANONICAL_AUDIO_FORMAT,
    ControlMode,
    NONVERBAL_CUE_MARKER_PREFIX,
    NONVERBAL_CUE_MARKER_SUFFIX,
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


_TRANSIENT_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}
_TRANSIENT_RPC_CODES = {4, 8, 10, 13, 14}
_DEFAULT_API_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
_MARKDOWN_STRUCTURE_RE = re.compile(
    r"(?m)^(?:#{1,6}[ \t]+|[-*+][ \t]+|\d+\.[ \t]+|>[ \t]+)|(?:\*\*|__|(?<!\*)\*(?!\*))\S"
)

_GEMINI_VOICES = (
    VoiceOption("Zephyr", ("bright",)),
    VoiceOption("Puck", ("upbeat",)),
    VoiceOption("Charon", ("informative",)),
    VoiceOption("Kore", ("firm",)),
    VoiceOption("Fenrir", ("excitable",)),
    VoiceOption("Leda", ("youthful",)),
    VoiceOption("Orus", ("firm",)),
    VoiceOption("Aoede", ("breezy",)),
    VoiceOption("Callirrhoe", ("easy-going",)),
    VoiceOption("Autonoe", ("bright",)),
    VoiceOption("Enceladus", ("breathy",)),
    VoiceOption("Iapetus", ("clear",)),
    VoiceOption("Umbriel", ("easy-going",)),
    VoiceOption("Algieba", ("smooth",)),
    VoiceOption("Despina", ("smooth",)),
    VoiceOption("Erinome", ("clear",)),
    VoiceOption("Algenib", ("gravelly",)),
    VoiceOption("Rasalgethi", ("informative",)),
    VoiceOption("Laomedeia", ("upbeat",)),
    VoiceOption("Achernar", ("soft",)),
    VoiceOption("Alnilam", ("firm",)),
    VoiceOption("Schedar", ("even",)),
    VoiceOption("Gacrux", ("mature",)),
    VoiceOption("Pulcherrima", ("forward",)),
    VoiceOption("Achird", ("friendly",)),
    VoiceOption("Zubenelgenubi", ("casual",)),
    VoiceOption("Vindemiatrix", ("gentle",)),
    VoiceOption("Sadachbia", ("lively",)),
    VoiceOption("Sadaltager", ("knowledgeable",)),
    VoiceOption("Sulafat", ("warm",)),
)

_TONE_DIRECTIONS = {
    TonePreset.CALM: "calm and composed",
    TonePreset.WARM: "warm and reassuring",
    TonePreset.CHEERFUL: "cheerful and optimistic",
    TonePreset.EXCITED: "energetic and excited",
    TonePreset.SERIOUS: "serious and measured",
    TonePreset.EMPATHETIC: "empathetic and compassionate",
    TonePreset.SOMBER: "somber and reflective",
    TonePreset.ANGRY: "controlled but clearly angry",
    TonePreset.FEARFUL: "tense and fearful",
    TonePreset.MYSTERIOUS: "mysterious and suspenseful",
    TonePreset.AUTHORITATIVE: "authoritative and confident",
}

_PACE_DIRECTIONS = {
    SpeechPace.VERY_SLOW: "very slow, with generous pauses and careful articulation",
    SpeechPace.SLOW: "slow and deliberate",
    SpeechPace.FAST: "brisk and energetic while remaining intelligible",
    SpeechPace.VERY_FAST: "very fast while preserving clarity and every word",
}

_STYLE_DIRECTIONS = {
    VocalStyle.AUDIOBOOK: "polished long-form audiobook narration",
    VocalStyle.CONVERSATIONAL: "natural conversational speech",
    VocalStyle.DOCUMENTARY: "cinematic documentary narration",
    VocalStyle.STORYTELLER: "expressive oral storytelling",
    VocalStyle.NEWSCASTER: "crisp professional newscast delivery",
    VocalStyle.PODCAST: "engaging studio podcast delivery",
    VocalStyle.DRAMATIC: "dramatic theatrical performance",
    VocalStyle.MEDITATION: "gentle guided-meditation delivery",
    VocalStyle.INSTRUCTIONAL: "clear patient instructional delivery",
}


class GeminiTtsProvider:
    """Google Gemini Interactions API adapter normalized to canonical raw PCM."""

    def __init__(
        self,
        *,
        default_model: str = "gemini-3.1-flash-tts-preview",
        default_voice: str = "Kore",
        provider_name: str = "gemini",
        request_timeout_seconds: float = 300.0,
        trust_env_proxies: bool = False,
        api_key: str | None = None,
        client: Any | None = None,
    ) -> None:
        voices = _GEMINI_VOICES
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
            max_input_tokens=8_192,
            recommended_chunk_bytes=3_800,
            recommended_chunk_words=350,
            capabilities=ProviderCapabilities(
                models=(default_model,),
                voices=voices,
                tone_presets=tuple(TonePreset),
                speech_paces=tuple(SpeechPace),
                vocal_styles=tuple(VocalStyle),
                nonverbal_frequencies=tuple(NonverbalFrequency),
                tone_modes=(ControlMode.PROMPT,),
                pace_modes=(ControlMode.PROMPT, ControlMode.INLINE_MARKUP),
                vocal_style_modes=(ControlMode.PROMPT, ControlMode.INLINE_MARKUP),
                nonverbal_modes=(ControlMode.INLINE_MARKUP, ControlMode.CLIENT_TRANSFORM),
                nonverbal_cues=("sighs", "giggles", "laughs", "gasp"),
            ),
        )
        self._api_key = api_key
        self._request_timeout_seconds = request_timeout_seconds
        self._trust_env_proxies = trust_env_proxies
        self._client = client
        self._owns_client = client is None

    @property
    def info(self) -> ProviderInfo:
        return self._info

    def estimate_input_tokens(self, text: str, options: SynthesisOptions) -> int:
        # Gemini does not expose a local tokenizer. UTF-8 bytes are a conservative upper
        # bound because a token cannot encode less than one source byte.
        return len(self._render_prompt(text, options).encode("utf-8"))

    def estimate_input_characters(self, text: str, options: SynthesisOptions) -> int:
        return len(self._render_prompt(text, options))

    async def synthesize(self, text: str, options: SynthesisOptions) -> AudioChunk:
        prompt = self._render_prompt(text, options)
        body = {
            "model": options.model,
            "input": prompt,
            "response_format": {"type": "audio"},
            "generation_config": {"speech_config": [{"voice": options.voice}]},
            "store": False,
        }
        credential = self._resolved_api_key()
        safe_request = request_diagnostic(
            method="POST",
            endpoint=_DEFAULT_API_URL,
            headers=({"X-Goog-Api-Key": credential} if credential else None),
            body=body,
            known_secrets=self._known_secrets(),
        )
        started = time.perf_counter()
        try:
            interaction = await self._get_client().aio.interactions.create(
                model=options.model,
                input=prompt,
                response_format={"type": "audio"},
                generation_config={"speech_config": [{"voice": options.voice}]},
                store=False,
                timeout=self._request_timeout_seconds,
            )
        except Exception as error:
            raise self._provider_error(
                error,
                request=safe_request,
                elapsed_ms=(time.perf_counter() - started) * 1_000,
            ) from error

        elapsed_ms = (time.perf_counter() - started) * 1_000
        interaction_status = self._string_value(getattr(interaction, "status", None))
        if interaction_status != "completed":
            failure_code, failure_message = self._interaction_failure(interaction)
            retryable = interaction_status in {"incomplete", "in_progress"} or (
                interaction_status == "failed" and failure_code in _TRANSIENT_RPC_CODES
            )
            detail = f": {failure_message}" if failure_message else ""
            diagnostic = self._failure_diagnostic(
                category="provider_error",
                phase="response",
                request=safe_request,
                elapsed_ms=elapsed_ms,
                status_code=failure_code,
                response_data={
                    "received": True,
                    "status_code": failure_code,
                    "status_text": interaction_status or "missing",
                    "body": {
                        "interaction_status": interaction_status or "missing",
                        "failure_code": failure_code,
                        "failure_message": failure_message,
                    },
                },
            )
            raise ProviderError(
                f"Gemini interaction ended with status: {interaction_status or 'missing'}{detail}",
                retryable=retryable,
                status_code=failure_code,
                diagnostic=diagnostic,
            )

        try:
            return self._parse_audio(interaction)
        except ProviderError as error:
            output_audio = getattr(interaction, "output_audio", None)
            diagnostic = self._failure_diagnostic(
                category="invalid_audio",
                phase="decode_audio",
                request=safe_request,
                elapsed_ms=elapsed_ms,
                error=error,
                response_data={
                    "received": True,
                    "status_code": None,
                    "status_text": interaction_status,
                    "body": {
                        "mime_type": getattr(output_audio, "mime_type", None),
                        "sample_rate": getattr(output_audio, "sample_rate", None),
                        "channels": getattr(output_audio, "channels", None),
                        "audio_data": getattr(output_audio, "data", None),
                    },
                },
            )
            raise with_provider_diagnostic(error, diagnostic) from error

    async def close(self) -> None:
        if not self._owns_client or self._client is None:
            return
        client = self._client
        self._client = None
        aio = getattr(client, "aio", None)
        aclose = getattr(aio, "aclose", None)
        if aclose is not None:
            await aclose()
        close = getattr(client, "close", None)
        if close is not None:
            await asyncio.to_thread(close)

    def _parse_audio(self, interaction: Any) -> AudioChunk:
        output_audio = getattr(interaction, "output_audio", None)
        if output_audio is None:
            raise ProviderError(
                "Gemini returned no audio output",
                retryable=True,
            )

        encoded = getattr(output_audio, "data", None)
        if not encoded:
            raise ProviderError("Gemini returned empty audio data", retryable=True)
        try:
            pcm = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError, TypeError) as error:
            raise ProviderError(
                "Gemini returned invalid base64 audio data", retryable=True
            ) from error

        # Gemini TTS currently rejects audio format overrides. Its documented default
        # is inline, mono, signed 16-bit PCM at 24 kHz; output metadata is optional.
        mime_type = self._string_value(getattr(output_audio, "mime_type", None)) or "audio/l16"
        if mime_type.lower() not in {"audio/l16", "audio/pcm"}:
            raise ProviderError(
                f"Gemini returned unsupported audio format: {mime_type}", retryable=False
            )
        sample_rate = getattr(output_audio, "sample_rate", None)
        channels = getattr(output_audio, "channels", None)
        if sample_rate is None:
            sample_rate = CANONICAL_AUDIO_FORMAT.sample_rate
        if channels is None:
            channels = CANONICAL_AUDIO_FORMAT.channels
        audio_format = AudioFormat(sample_rate=int(sample_rate), channels=int(channels))
        if audio_format != CANONICAL_AUDIO_FORMAT:
            raise ProviderError(
                "Gemini returned incompatible PCM "
                f"({audio_format.channels} channels at {audio_format.sample_rate} Hz)",
                retryable=False,
            )
        if not pcm or len(pcm) % audio_format.frame_width:
            raise ProviderError("Gemini returned invalid PCM frame data", retryable=True)
        return AudioChunk(pcm=pcm, format=audio_format)

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                from google import genai
                from google.genai import types
            except ImportError as error:
                raise ProviderError(
                    "google-genai is not installed; run `uv sync`",
                    retryable=False,
                ) from error
            if not self._api_key and not (
                os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
            ):
                raise ProviderError(
                    "Gemini API credentials are missing; set GEMINI_API_KEY or GOOGLE_API_KEY",
                    retryable=False,
                )
            # With no explicit key, let the SDK apply its documented environment-variable
            # precedence between GOOGLE_API_KEY and GEMINI_API_KEY.
            http_options = types.HttpOptions(
                timeout=int(self._request_timeout_seconds * 1_000),
                client_args={"trust_env": self._trust_env_proxies},
                async_client_args={"trust_env": self._trust_env_proxies},
                # The 2.x Interactions bridge maps attempts directly to max_retries;
                # zero keeps SPLICR as the sole retry/backoff owner.
                retry_options=types.HttpRetryOptions(attempts=0),
            )
            self._client = (
                genai.Client(api_key=self._api_key, http_options=http_options)
                if self._api_key
                else genai.Client(http_options=http_options)
            )
        return self._client

    def _resolved_api_key(self) -> str | None:
        return self._api_key or os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")

    def _known_secrets(self) -> tuple[str, ...]:
        return tuple(
            value
            for value in (
                self._api_key,
                os.getenv("GOOGLE_API_KEY"),
                os.getenv("GEMINI_API_KEY"),
            )
            if value
        )

    def _failure_diagnostic(
        self,
        *,
        category: str,
        phase: str,
        request: dict[str, Any],
        elapsed_ms: float,
        status_code: int | None = None,
        response: Any | None = None,
        response_data: dict[str, Any] | None = None,
        error: BaseException | None = None,
        no_response_reason: str | None = None,
    ) -> ProviderDiagnostic:
        secrets = self._known_secrets()
        if response_data is not None:
            safe_response = sanitize_diagnostic(response_data, known_secrets=secrets)
        elif response is not None:
            safe_response = response_diagnostic(response, known_secrets=secrets)
        else:
            safe_response = no_response_diagnostic(
                no_response_reason or "No HTTP response was received."
            )
        return ProviderDiagnostic(
            category=category,
            phase=phase,
            provider=self.info.name,
            method="POST",
            endpoint=sanitize_url(_DEFAULT_API_URL, known_secrets=secrets),
            request=request,
            response=safe_response if isinstance(safe_response, dict) else {"body": safe_response},
            exception=(exception_chain(error, known_secrets=secrets) if error else None),
            metadata={
                "elapsed_ms": round(max(0.0, elapsed_ms), 3),
                "proxy": proxy_environment_diagnostic(trust_env=self._trust_env_proxies),
                "fingerprint": error_fingerprint(
                    category=category,
                    provider=self.info.name,
                    phase=phase,
                    status_code=status_code,
                    exception=error,
                ),
            },
        )

    @staticmethod
    def _render_prompt(text: str, options: SynthesisOptions) -> str:
        sections = [
            "Synthesize speech from the transcript below. Speak only the transcript; do not read "
            "section headings or these instructions aloud. Preserve the wording and order exactly."
        ]
        controls = options.controls
        delivery_notes: list[str] = []
        if _MARKDOWN_STRUCTURE_RE.search(text):
            delivery_notes.append(
                "Interpret Markdown headings, lists, quotations, and emphasis as silent document "
                "structure. Reflect headings with natural section transitions and emphasized text "
                "with vocal emphasis; never speak the Markdown punctuation itself."
            )
        if controls.tone is not TonePreset.NEUTRAL:
            delivery_notes.append(f"Tone and emotion: {_TONE_DIRECTIONS[controls.tone]}.")
        if controls.pace is not SpeechPace.NORMAL:
            delivery_notes.append(f"Speaking pace: {_PACE_DIRECTIONS[controls.pace]}.")
        if controls.vocal_style is not VocalStyle.NATURAL:
            delivery_notes.append(f"Vocal style: {_STYLE_DIRECTIONS[controls.vocal_style]}.")
        if controls.nonverbal_frequency is not NonverbalFrequency.NEVER:
            delivery_notes.append(
                f"Treat only exact markers of the form {NONVERBAL_CUE_MARKER_PREFIX}name"
                f"{NONVERBAL_CUE_MARKER_SUFFIX} as non-verbal controls. At each marker, render "
                "the named sound at that exact position and never speak the marker aloud. Treat "
                "every other bracketed passage as literal transcript wording. Do not add other "
                "words or sounds."
            )
        if delivery_notes:
            sections.extend(["### DELIVERY PRESET", "\n".join(delivery_notes)])
        if options.instructions:
            sections.extend(["### DIRECTOR'S NOTES", options.instructions.strip()])
        sections.extend(["### TRANSCRIPT", text])
        return "\n\n".join(sections)

    @staticmethod
    def _string_value(value: Any) -> str | None:
        if value is None:
            return None
        enum_value = getattr(value, "value", value)
        return str(enum_value)

    @staticmethod
    def _interaction_failure(interaction: Any) -> tuple[int | None, str | None]:
        for step in reversed(getattr(interaction, "steps", None) or []):
            error = getattr(step, "error", None)
            if error is None:
                continue
            raw_code = getattr(error, "code", None)
            try:
                code = int(raw_code) if raw_code is not None else None
            except (TypeError, ValueError):
                code = None
            message = getattr(error, "message", None)
            return code, str(message)[:1000] if message else None
        return None, None

    def _provider_error(
        self,
        error: Exception,
        *,
        request: dict[str, Any],
        elapsed_ms: float,
    ) -> ProviderError:
        raw_status = getattr(error, "status_code", None) or getattr(error, "code", None)
        try:
            status_code = int(raw_status) if raw_status is not None else None
        except (TypeError, ValueError):
            status_code = None

        retry_after: float | None = None
        response = getattr(error, "response", None)
        headers = getattr(response, "headers", None)
        if headers:
            raw_milliseconds = headers.get("retry-after-ms") or headers.get("Retry-After-Ms")
            if raw_milliseconds:
                try:
                    retry_after = float(raw_milliseconds) / 1_000
                except (TypeError, ValueError):
                    retry_after = None
            if retry_after is None:
                raw_retry_after = headers.get("retry-after") or headers.get("Retry-After")
                if raw_retry_after:
                    try:
                        retry_after = float(raw_retry_after)
                    except (TypeError, ValueError):
                        try:
                            retry_at = parsedate_to_datetime(str(raw_retry_after))
                            if retry_at.tzinfo is None:
                                retry_at = retry_at.replace(tzinfo=timezone.utc)
                            retry_after = max(
                                0.0, (retry_at - datetime.now(timezone.utc)).total_seconds()
                            )
                        except (TypeError, ValueError, OverflowError):
                            retry_after = None

        retryable = (
            error.retryable
            if isinstance(error, ProviderError)
            else status_code is None or status_code in _TRANSIENT_STATUS_CODES
        )
        response = getattr(error, "response", None)
        if isinstance(error, ProviderError) and error.diagnostic is not None:
            return error
        is_transport = isinstance(
            error,
            (httpx.RequestError, TimeoutError, OSError),
        ) or any(
            token in (str(error).lower())
            for token in (
                "connection",
                "connecterror",
                "network",
                "dns",
                "getaddrinfo",
                "proxy",
                "timed out",
                "timeout",
                "tls",
                "ssl",
            )
        )
        category = (
            transport_error_category(error)
            if is_transport and status_code is None
            else "http_error"
            if status_code is not None
            else "provider_error"
        )
        phase = transport_error_phase(error) if is_transport else "response"
        diagnostic = self._failure_diagnostic(
            category=category,
            phase=phase,
            request=request,
            elapsed_ms=elapsed_ms,
            status_code=status_code,
            response=response,
            error=error,
            no_response_reason=(
                "No HTTP response was received; the provider request failed before a response "
                "was available."
            ),
        )
        safe_message = sanitize_diagnostic(
            str(error).strip() or error.__class__.__name__,
            known_secrets=self._known_secrets(),
        )
        if isinstance(error, ProviderError):
            return with_provider_diagnostic(error, diagnostic)
        return ProviderError(
            f"Gemini request failed: {str(safe_message)[:1000]}",
            retryable=retryable,
            status_code=status_code,
            retry_after=retry_after,
            diagnostic=diagnostic,
        )
