from __future__ import annotations

import base64
import binascii
import io
import os
import re
import wave
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from ..domain import (
    AudioChunk,
    CANONICAL_AUDIO_FORMAT,
    ControlMode,
    NONVERBAL_CUE_MARKER_PREFIX,
    NONVERBAL_CUE_MARKER_SUFFIX,
    NonverbalFrequency,
    ProviderCapabilities,
    ProviderError,
    ProviderInfo,
    SpeechPace,
    SynthesisOptions,
    TonePreset,
    VocalStyle,
    VoiceOption,
)


_DEFAULT_API_URL = "https://api.inworld.ai/tts/v1/voice"
_MAX_INPUT_CHARACTERS = 2_000

_PACE_RATES = {
    SpeechPace.VERY_SLOW: 0.5,
    SpeechPace.SLOW: 0.75,
    SpeechPace.NORMAL: 1.0,
    SpeechPace.FAST: 1.25,
    SpeechPace.VERY_FAST: 1.5,
}

_TONE_DIRECTIONS = {
    TonePreset.CALM: "Use a calm and composed tone.",
    TonePreset.WARM: "Use a warm and reassuring tone.",
    TonePreset.CHEERFUL: "Use a cheerful and optimistic tone.",
    TonePreset.EXCITED: "Sound energetic and excited.",
    TonePreset.SERIOUS: "Use a serious and measured tone.",
    TonePreset.EMPATHETIC: "Sound empathetic and compassionate.",
    TonePreset.SOMBER: "Use a somber and reflective tone.",
    TonePreset.ANGRY: "Sound controlled but clearly angry.",
    TonePreset.FEARFUL: "Sound tense and fearful.",
    TonePreset.MYSTERIOUS: "Sound mysterious and suspenseful.",
    TonePreset.AUTHORITATIVE: "Sound authoritative and confident.",
}

_STYLE_DIRECTIONS = {
    VocalStyle.AUDIOBOOK: "Use polished long-form audiobook narration.",
    VocalStyle.CONVERSATIONAL: "Use natural conversational delivery.",
    VocalStyle.DOCUMENTARY: "Use cinematic documentary narration.",
    VocalStyle.STORYTELLER: "Use expressive oral storytelling.",
    VocalStyle.NEWSCASTER: "Use crisp professional newscast delivery.",
    VocalStyle.PODCAST: "Use engaging studio podcast delivery.",
    VocalStyle.DRAMATIC: "Use dramatic theatrical delivery.",
    VocalStyle.MEDITATION: "Use gentle guided-meditation delivery.",
    VocalStyle.INSTRUCTIONAL: "Use clear and patient instructional delivery.",
}

# Inworld TTS-2 documents these six non-verbal tags. The aliases preserve SPLICR's
# existing provider-neutral cue names when a persisted plan is rendered by Inworld.
_CUE_TAGS = {
    "laugh": "[laugh]",
    "laughs": "[laugh]",
    "giggle": "[laugh]",
    "giggles": "[laugh]",
    "breathe": "[breathe]",
    "breath": "[breathe]",
    "breaths": "[breathe]",
    "gasp": "[breathe]",
    "gasps": "[breathe]",
    "clear throat": "[clear throat]",
    "clears throat": "[clear throat]",
    "throat clear": "[clear throat]",
    "sigh": "[sigh]",
    "sighs": "[sigh]",
    "cough": "[cough]",
    "coughs": "[cough]",
    "yawn": "[yawn]",
    "yawns": "[yawn]",
}
_EXPOSED_CUES = ("laugh", "breathe", "clear throat", "sigh", "cough", "yawn")
_CUE_MARKER_RE = re.compile(
    re.escape(NONVERBAL_CUE_MARKER_PREFIX)
    + r"(?P<cue>[^\]\r\n]+)"
    + re.escape(NONVERBAL_CUE_MARKER_SUFFIX)
)
_HORIZONTAL_WHITESPACE_RE = re.compile(r"\s+")


class InworldTtsProvider:
    """Inworld's non-streaming TTS endpoint normalized to canonical raw PCM frames."""

    def __init__(
        self,
        *,
        default_model: str = "inworld-tts-2",
        default_voice: str = "Dennis",
        api_url: str = _DEFAULT_API_URL,
        request_timeout_seconds: float = 300.0,
        minimum_request_interval_seconds: float = 0.0,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds must be positive")
        if minimum_request_interval_seconds < 0:
            raise ValueError("minimum_request_interval_seconds cannot be negative")

        supports_steering = default_model == "inworld-tts-2"
        voices = (
            VoiceOption("Ashley", ("system",)),
            VoiceOption("Dennis", ("system",)),
        )
        if all(voice.id != default_voice for voice in voices):
            voices = (VoiceOption(default_voice, ("configured",)), *voices)
        self._info = ProviderInfo(
            name="inworld",
            default_model=default_model,
            default_voice=default_voice,
            max_input_bytes=None,
            max_input_tokens=None,
            max_input_characters=_MAX_INPUT_CHARACTERS,
            recommended_chunk_bytes=None,
            recommended_chunk_words=None,
            recommended_chunk_characters=1_900,
            minimum_request_interval_seconds=minimum_request_interval_seconds,
            capabilities=ProviderCapabilities(
                models=(default_model,),
                voices=voices,
                tone_presets=tuple(TonePreset) if supports_steering else (),
                speech_paces=tuple(SpeechPace),
                vocal_styles=tuple(VocalStyle) if supports_steering else (),
                nonverbal_frequencies=(
                    tuple(NonverbalFrequency) if supports_steering else ()
                ),
                tone_modes=(ControlMode.PROMPT,) if supports_steering else (),
                pace_modes=(ControlMode.NATIVE_SCALAR,),
                vocal_style_modes=(ControlMode.PROMPT,) if supports_steering else (),
                nonverbal_modes=(
                    (ControlMode.INLINE_MARKUP, ControlMode.CLIENT_TRANSFORM)
                    if supports_steering
                    else ()
                ),
                nonverbal_cues=_EXPOSED_CUES if supports_steering else (),
                supports_custom_instructions=supports_steering,
            ),
        )
        self._api_key = api_key
        self._api_url = api_url
        self._request_timeout_seconds = request_timeout_seconds
        self._client = client
        self._owns_client = client is None

    @property
    def info(self) -> ProviderInfo:
        return self._info

    def estimate_input_characters(self, text: str, options: SynthesisOptions) -> int:
        return len(self._render_text(text, options))

    def estimate_input_tokens(self, text: str, options: SynthesisOptions) -> int:
        # Inworld enforces characters rather than tokens. This remains a deterministic
        # conservative estimate for callers that still display a token-like metric.
        return self.estimate_input_characters(text, options)

    async def synthesize(self, text: str, options: SynthesisOptions) -> AudioChunk:
        request_text = self._render_text(text, options)
        if not request_text.strip():
            raise ProviderError("Inworld input text cannot be empty", retryable=False)
        if not options.model.strip():
            raise ProviderError("Inworld model cannot be empty", retryable=False)
        if not options.voice.strip():
            raise ProviderError("Inworld voice cannot be empty", retryable=False)
        character_count = len(request_text)
        if character_count > _MAX_INPUT_CHARACTERS:
            raise ProviderError(
                "Inworld input exceeds its 2000-character limit after delivery controls "
                f"and audio cues are applied ({character_count} characters)",
                retryable=False,
                status_code=400,
            )

        payload: dict[str, Any] = {
            "text": request_text,
            "voiceId": options.voice,
            "modelId": options.model,
            "audioConfig": {
                "audioEncoding": "WAV",
                "sampleRateHertz": CANONICAL_AUDIO_FORMAT.sample_rate,
                "speakingRate": _PACE_RATES[options.controls.pace],
            },
            "applyTextNormalization": "ON",
        }
        if options.model == "inworld-tts-2":
            payload["deliveryMode"] = "BALANCED"

        headers = self._authorization_headers()
        try:
            response = await self._get_client().post(
                self._api_url,
                headers=headers,
                json=payload,
                timeout=self._request_timeout_seconds,
            )
        except (httpx.RequestError, TimeoutError, OSError) as error:
            message = str(error).strip() or error.__class__.__name__
            raise ProviderError(
                f"Inworld request failed: {message[:1000]}",
                retryable=True,
            ) from error

        response_payload = self._response_json(response)
        rpc_code = self._rpc_code(response_payload)
        has_provider_error = "error" in response_payload or (
            rpc_code is not None and "audioContent" not in response_payload
        )
        if response.status_code >= 400 or has_provider_error:
            raise self._response_error(response, response_payload, rpc_code)
        return self._parse_audio(response_payload)

    async def close(self) -> None:
        if not self._owns_client or self._client is None:
            return
        client = self._client
        self._client = None
        await client.aclose()

    async def __aenter__(self) -> InworldTtsProvider:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._request_timeout_seconds)
        return self._client

    def _authorization_headers(self) -> dict[str, str]:
        api_key = self._api_key or os.getenv("INWORLD_API_KEY")
        if not api_key or not api_key.strip():
            raise ProviderError(
                "Inworld API credentials are missing; set INWORLD_API_KEY",
                retryable=False,
            )
        credential = api_key.strip()
        authorization = (
            credential if credential.lower().startswith("basic ") else f"Basic {credential}"
        )
        return {
            "Authorization": authorization,
            "Content-Type": "application/json",
        }

    @classmethod
    def _render_text(cls, text: str, options: SynthesisOptions) -> str:
        if options.model != "inworld-tts-2":
            controls = options.controls
            if (
                (options.instructions and options.instructions.strip())
                or controls.tone is not TonePreset.NEUTRAL
                or controls.vocal_style is not VocalStyle.NATURAL
                or controls.nonverbal_frequency is not NonverbalFrequency.NEVER
                or _CUE_MARKER_RE.search(text)
            ):
                raise ProviderError(
                    "Inworld steering and non-verbal cues require the inworld-tts-2 model",
                    retryable=False,
                    status_code=400,
                )
            return text

        transformed = cls._replace_cue_markers(text)
        controls = options.controls
        directions: list[str] = []
        if controls.tone is not TonePreset.NEUTRAL:
            directions.append(_TONE_DIRECTIONS[controls.tone])
        if controls.vocal_style is not VocalStyle.NATURAL:
            directions.append(_STYLE_DIRECTIONS[controls.vocal_style])
        if options.instructions and options.instructions.strip():
            directions.append(cls._sanitize_steering(options.instructions))
        if not directions:
            return transformed
        return f"[{' '.join(directions)}]\n{transformed}"

    @staticmethod
    def _sanitize_steering(instructions: str) -> str:
        # Square brackets delimit Inworld's steering directive. Parentheses preserve the
        # user's meaning without allowing a custom note to terminate the directive early.
        flattened = _HORIZONTAL_WHITESPACE_RE.sub(" ", instructions).strip()
        return flattened.replace("[", "(").replace("]", ")")

    @staticmethod
    def _replace_cue_markers(text: str) -> str:
        def replace(match: re.Match[str]) -> str:
            raw_cue = match.group("cue")
            normalized = _HORIZONTAL_WHITESPACE_RE.sub(
                " ", raw_cue.strip().lower().replace("_", "-").replace("-", " ")
            )
            tag = _CUE_TAGS.get(normalized)
            if tag is None:
                raise ProviderError(
                    f"Inworld does not support SPLICR audio cue: {raw_cue}",
                    retryable=False,
                    status_code=400,
                )
            return tag

        return _CUE_MARKER_RE.sub(replace, text)

    @staticmethod
    def _response_json(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except (ValueError, TypeError) as error:
            retryable = (
                response.status_code == 429
                or response.status_code >= 500
                or response.status_code < 400
            )
            raise ProviderError(
                f"Inworld returned invalid JSON (HTTP {response.status_code})",
                retryable=retryable,
                status_code=response.status_code,
                retry_after=InworldTtsProvider._retry_after(response),
            ) from error
        if not isinstance(payload, dict):
            raise ProviderError(
                f"Inworld returned an invalid JSON object (HTTP {response.status_code})",
                retryable=(
                    response.status_code == 429
                    or response.status_code >= 500
                    or response.status_code < 400
                ),
                status_code=response.status_code,
                retry_after=InworldTtsProvider._retry_after(response),
            )
        return payload

    @staticmethod
    def _rpc_code(payload: dict[str, Any]) -> int | None:
        error = payload.get("error")
        candidate = error.get("code") if isinstance(error, dict) else payload.get("code")
        try:
            return int(candidate) if candidate is not None else None
        except (TypeError, ValueError):
            return None

    @classmethod
    def _response_error(
        cls,
        response: httpx.Response,
        payload: dict[str, Any],
        rpc_code: int | None,
    ) -> ProviderError:
        error = payload.get("error")
        if isinstance(error, dict):
            raw_message = error.get("message") or error.get("status")
        else:
            raw_message = error or payload.get("message")
        message = str(raw_message).strip() if raw_message else response.reason_phrase
        resource_exhausted = rpc_code == 8
        status_code = (
            429
            if resource_exhausted
            else response.status_code
            if response.status_code >= 400
            else 400
        )
        retryable = resource_exhausted or response.status_code == 429 or response.status_code >= 500
        return ProviderError(
            f"Inworld request failed (HTTP {response.status_code}): {message[:1000]}",
            retryable=retryable,
            status_code=status_code,
            retry_after=cls._retry_after(response),
        )

    @staticmethod
    def _retry_after(response: httpx.Response) -> float | None:
        raw_retry_after = response.headers.get("Retry-After")
        if not raw_retry_after:
            return None
        try:
            return max(0.0, float(raw_retry_after))
        except (TypeError, ValueError):
            try:
                retry_at = parsedate_to_datetime(raw_retry_after)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())
            except (TypeError, ValueError, OverflowError):
                return None

    @staticmethod
    def _parse_audio(payload: dict[str, Any]) -> AudioChunk:
        encoded = payload.get("audioContent")
        if not isinstance(encoded, str) or not encoded:
            raise ProviderError("Inworld returned no audio content", retryable=True)
        try:
            wav_data = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError, TypeError) as error:
            raise ProviderError(
                "Inworld returned invalid base64 audio data",
                retryable=True,
            ) from error

        try:
            with wave.open(io.BytesIO(wav_data), "rb") as source:
                channels = source.getnchannels()
                sample_width = source.getsampwidth()
                sample_rate = source.getframerate()
                compression = source.getcomptype()
                frame_count = source.getnframes()
                pcm = source.readframes(frame_count)
        except (EOFError, wave.Error) as error:
            raise ProviderError("Inworld returned an invalid WAV file", retryable=True) from error

        if (
            compression != "NONE"
            or channels != CANONICAL_AUDIO_FORMAT.channels
            or sample_width != CANONICAL_AUDIO_FORMAT.sample_width
            or sample_rate != CANONICAL_AUDIO_FORMAT.sample_rate
        ):
            raise ProviderError(
                "Inworld returned incompatible WAV audio "
                f"({channels} channels, {sample_width * 8}-bit, {sample_rate} Hz, {compression})",
                retryable=False,
            )
        expected_bytes = frame_count * CANONICAL_AUDIO_FORMAT.frame_width
        if not pcm or len(pcm) != expected_bytes:
            raise ProviderError("Inworld returned invalid PCM frame data", retryable=True)
        return AudioChunk(pcm=pcm, format=CANONICAL_AUDIO_FORMAT)
