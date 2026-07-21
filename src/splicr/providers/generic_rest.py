from __future__ import annotations

import base64
import binascii
import io
import json
import math
import re
import sys
import time
import wave
from array import array
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Protocol
from urllib.parse import quote, quote_plus

import httpx

from splicr.diagnostics import (
    error_fingerprint,
    exception_chain,
    no_response_diagnostic,
    proxy_environment_diagnostic,
    request_diagnostic,
    response_diagnostic,
    sanitize_url,
    transport_error_category,
    transport_error_phase,
    with_provider_diagnostic,
)
from splicr.domain import (
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


JsonTemplate = Any
_PLACEHOLDER_RE = re.compile(r"{{\s*([A-Za-z_][A-Za-z0-9_.-]*)\s*}}")
_WORD_RE = re.compile(r"\S+")
_TRANSIENT_STATUSES = frozenset({408, 425, 429})
_ERROR_TEXT_LIMIT = 1_000
_RESERVED_CONTEXT_KEYS = frozenset(
    {
        "api_key",
        "text",
        "model",
        "voice",
        "instructions",
        "tone",
        "pace",
        "vocal_style",
        "nonverbal_frequency",
    }
)


class GenericRestResponseMode(StrEnum):
    RAW_PCM16 = "raw_pcm16"
    WAV_PCM16 = "wav_pcm16"
    JSON_BASE64_RAW_PCM16 = "json_base64_raw_pcm16"
    JSON_BASE64_WAV = "json_base64_wav"


class GenericRestAuthLocation(StrEnum):
    NONE = "none"
    HEADER = "header"
    QUERY = "query"


class GenericRestLimitBasis(StrEnum):
    TEXT = "text"
    BODY = "body"


class GenericRestSpecLike(Protocol):
    """Narrow endpoint-spec contract consumed by :class:`GenericRestTtsProvider`."""

    name: str
    url: str
    method: str
    default_model: str
    default_voice: str
    headers: Mapping[str, JsonTemplate]
    query: Mapping[str, JsonTemplate]
    body_template: JsonTemplate
    custom_variables: Mapping[str, JsonTemplate]
    required_variables: tuple[str, ...]
    auth_location: str
    auth_name: str
    auth_prefix: str
    response_mode: str
    response_json_pointer: str
    timeout_seconds: float
    max_input_characters: int | None
    max_input_bytes: int | None
    max_input_tokens: int | None
    max_input_words: int | None
    recommended_chunk_characters: int | None
    recommended_chunk_bytes: int | None
    recommended_chunk_words: int | None
    limit_basis: str
    response_sample_rate: int
    response_channels: int
    response_sample_width: int
    response_encoding: str
    minimum_request_interval_seconds: float
    models: tuple[str, ...]
    voices: tuple[str, ...]
    capabilities: ProviderCapabilities | None


@dataclass(frozen=True, slots=True)
class GenericRestSpec:
    """Immutable, serializable description of a JSON-over-HTTP TTS endpoint.

    API credentials deliberately live outside this object. A caller can safely persist the
    endpoint shape while storing the corresponding secret in a credential store.
    """

    name: str
    url: str
    method: str = "POST"
    default_model: str = ""
    default_voice: str = ""
    headers: Mapping[str, JsonTemplate] = field(default_factory=dict)
    query: Mapping[str, JsonTemplate] = field(default_factory=dict)
    body_template: JsonTemplate = field(default_factory=lambda: {"text": "{{text}}"})
    custom_variables: Mapping[str, JsonTemplate] = field(default_factory=dict)
    required_variables: tuple[str, ...] = ()
    auth_location: str = GenericRestAuthLocation.HEADER
    auth_name: str = "Authorization"
    auth_prefix: str = "Bearer"
    response_mode: str = GenericRestResponseMode.RAW_PCM16
    response_json_pointer: str = ""
    timeout_seconds: float = 300.0
    max_input_characters: int | None = None
    max_input_bytes: int | None = None
    max_input_tokens: int | None = None
    max_input_words: int | None = None
    recommended_chunk_characters: int | None = None
    recommended_chunk_bytes: int | None = None
    recommended_chunk_words: int | None = None
    limit_basis: str = GenericRestLimitBasis.TEXT
    response_sample_rate: int = 24_000
    response_channels: int = 1
    response_sample_width: int = 2
    response_encoding: str = "pcm_s16le"
    minimum_request_interval_seconds: float = 0.0
    models: tuple[str, ...] = ()
    voices: tuple[str, ...] = ()
    capabilities: ProviderCapabilities | None = None

    def __post_init__(self) -> None:
        name = self.name.strip()
        url = self.url.strip()
        method = self.method.upper().strip()
        auth_location = str(self.auth_location).lower().strip()
        response_mode = str(self.response_mode).lower().strip()
        limit_basis = str(self.limit_basis).lower().strip()
        if not name:
            raise ValueError("name cannot be empty")
        if not url:
            raise ValueError("url cannot be empty")
        if method not in {"GET", "POST", "PUT", "PATCH"}:
            raise ValueError("method must be GET, POST, PUT, or PATCH")
        if auth_location not in set(GenericRestAuthLocation):
            raise ValueError("auth_location must be none, header, or query")
        if auth_location != GenericRestAuthLocation.NONE and not self.auth_name.strip():
            raise ValueError("auth_name cannot be empty when authentication is enabled")
        if response_mode not in set(GenericRestResponseMode):
            raise ValueError("unsupported response_mode")
        if limit_basis not in set(GenericRestLimitBasis):
            raise ValueError("limit_basis must be text or body")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.minimum_request_interval_seconds < 0:
            raise ValueError("minimum_request_interval_seconds cannot be negative")
        for field_name in (
            "max_input_characters",
            "max_input_bytes",
            "max_input_tokens",
            "max_input_words",
            "recommended_chunk_characters",
            "recommended_chunk_bytes",
            "recommended_chunk_words",
        ):
            value = getattr(self, field_name)
            if value is not None and value <= 0:
                raise ValueError(f"{field_name} must be positive when set")
        if self.response_json_pointer and not self.response_json_pointer.startswith("/"):
            raise ValueError("response_json_pointer must be empty or start with '/'")
        if "api_key" in self.custom_variables:
            raise ValueError("api_key must be supplied separately from custom_variables")
        required_variables = tuple(self.required_variables)
        if any(not isinstance(name, str) or not name.strip() for name in required_variables):
            raise ValueError("required_variables must contain non-empty names")
        if len(required_variables) != len(set(required_variables)):
            raise ValueError("required_variables must be unique")
        reserved_required = sorted(set(required_variables) & _RESERVED_CONTEXT_KEYS)
        if reserved_required:
            raise ValueError(
                "required_variables cannot contain reserved names: " + ", ".join(reserved_required)
            )
        if self.response_sample_rate <= 0:
            raise ValueError("response_sample_rate must be positive")
        if not 1 <= self.response_channels <= 32:
            raise ValueError("response_channels must be between 1 and 32")
        expected_encoding = {
            1: "pcm_u8",
            2: "pcm_s16le",
            3: "pcm_s24le",
            4: "pcm_s32le",
        }.get(self.response_sample_width)
        if expected_encoding is None:
            raise ValueError("response_sample_width must be between 1 and 4")
        if self.response_encoding.lower() != expected_encoding:
            raise ValueError(
                f"{self.response_sample_width * 8}-bit PCM requires {expected_encoding}"
            )

        object.__setattr__(self, "name", name)
        object.__setattr__(self, "url", url)
        object.__setattr__(self, "method", method)
        object.__setattr__(self, "auth_location", auth_location)
        object.__setattr__(self, "response_mode", response_mode)
        object.__setattr__(self, "limit_basis", limit_basis)
        object.__setattr__(self, "headers", _freeze_mapping(self.headers, "headers"))
        object.__setattr__(self, "query", _freeze_mapping(self.query, "query"))
        object.__setattr__(self, "body_template", _freeze_json(self.body_template))
        object.__setattr__(
            self,
            "custom_variables",
            _freeze_mapping(self.custom_variables, "custom_variables"),
        )
        object.__setattr__(self, "required_variables", required_variables)
        object.__setattr__(self, "models", tuple(self.models))
        object.__setattr__(self, "voices", tuple(self.voices))
        if self.capabilities is not None and not isinstance(
            self.capabilities, ProviderCapabilities
        ):
            raise TypeError("capabilities must be ProviderCapabilities or None")


@dataclass(frozen=True, slots=True)
class _RenderedRequest:
    url: str
    headers: dict[str, str]
    query: dict[str, Any]
    body: JsonTemplate


class GenericRestTtsProvider:
    def __init__(
        self,
        spec: GenericRestSpecLike,
        *,
        api_key: str | None = None,
        trust_env_proxies: bool = False,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._spec = spec
        self._api_key = api_key
        self._trust_env_proxies = trust_env_proxies
        self._client = client
        self._owns_client = client is None
        models = tuple(dict.fromkeys((spec.default_model, *spec.models)))
        voices = tuple(dict.fromkeys((spec.default_voice, *spec.voices)))
        advertised_capabilities = getattr(spec, "capabilities", None)
        if advertised_capabilities is None:
            advertised_capabilities = ProviderCapabilities(
                models=tuple(value for value in models if value),
                voices=tuple(VoiceOption(value) for value in voices if value),
                tone_presets=tuple(TonePreset),
                speech_paces=tuple(SpeechPace),
                vocal_styles=tuple(VocalStyle),
                nonverbal_frequencies=tuple(NonverbalFrequency),
                tone_modes=(ControlMode.NATIVE_ENUM,),
                pace_modes=(ControlMode.NATIVE_ENUM,),
                vocal_style_modes=(ControlMode.NATIVE_ENUM,),
                nonverbal_modes=(ControlMode.NATIVE_ENUM,),
                supports_custom_instructions=True,
            )
        self._info = ProviderInfo(
            name=spec.name,
            default_model=spec.default_model,
            default_voice=spec.default_voice,
            max_input_bytes=spec.max_input_bytes,
            max_input_tokens=spec.max_input_tokens,
            max_input_characters=spec.max_input_characters,
            recommended_chunk_bytes=spec.recommended_chunk_bytes,
            recommended_chunk_words=spec.recommended_chunk_words or spec.max_input_words,
            recommended_chunk_characters=spec.recommended_chunk_characters,
            minimum_request_interval_seconds=spec.minimum_request_interval_seconds,
            capabilities=advertised_capabilities,
        )

    @property
    def info(self) -> ProviderInfo:
        return self._info

    def estimate_input_characters(self, text: str, options: SynthesisOptions) -> int:
        value = self._limit_value(text, options)
        return len(value)

    def estimate_input_tokens(self, text: str, options: SynthesisOptions) -> int:
        return max(1, math.ceil(self.estimate_input_characters(text, options) / 4))

    async def synthesize(self, text: str, options: SynthesisOptions) -> AudioChunk:
        if not text.strip():
            raise ProviderError(f"{self._spec.name} request text cannot be empty", retryable=False)
        request = self._render_request(text, options)
        _serialize_json(request.body)
        self._validate_limits(text, options, request.body)

        safe_request = request_diagnostic(
            method=self._spec.method,
            endpoint=request.url,
            headers=request.headers,
            query=request.query,
            body=request.body,
            known_secrets=self._known_secrets(),
        )
        started = time.perf_counter()
        try:
            response = await self._get_client().request(
                self._spec.method,
                request.url,
                headers=request.headers,
                params=request.query,
                json=request.body,
                timeout=self._spec.timeout_seconds,
                follow_redirects=False,
            )
        except httpx.RequestError as error:
            detail = _sanitize(str(error).strip() or error.__class__.__name__, self._api_key)
            category = transport_error_category(error)
            phase = transport_error_phase(error)
            diagnostic = self._failure_diagnostic(
                category=category,
                phase=phase,
                endpoint=request.url,
                request=safe_request,
                elapsed_ms=(time.perf_counter() - started) * 1_000,
                error=error,
                no_response_reason=(
                    "No HTTP response was received; the request failed before a response was "
                    "available."
                ),
            )
            raise ProviderError(
                f"{self._spec.name} request failed: {detail[:_ERROR_TEXT_LIMIT]}",
                retryable=True,
                diagnostic=diagnostic,
            ) from None

        elapsed_ms = (time.perf_counter() - started) * 1_000
        if not 200 <= response.status_code <= 299:
            diagnostic = self._failure_diagnostic(
                category="http_error",
                phase="response",
                endpoint=request.url,
                request=safe_request,
                elapsed_ms=elapsed_ms,
                response=response,
            )
            raise self._http_error(response, diagnostic=diagnostic)
        try:
            return self._decode_response(response)
        except ProviderError as error:
            diagnostic = self._failure_diagnostic(
                category="invalid_audio",
                phase="decode_audio",
                endpoint=request.url,
                request=safe_request,
                elapsed_ms=elapsed_ms,
                response=response,
                error=error,
            )
            raise with_provider_diagnostic(error, diagnostic) from error

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> GenericRestTtsProvider:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                follow_redirects=False,
                trust_env=self._trust_env_proxies,
            )
        return self._client

    def _known_secrets(self) -> tuple[str, ...]:
        return (self._api_key,) if self._api_key else ()

    def _failure_diagnostic(
        self,
        *,
        category: str,
        phase: str,
        endpoint: str,
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
            method=self._spec.method.upper(),
            endpoint=sanitize_url(endpoint, known_secrets=secrets),
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

    def _context(self, text: str, options: SynthesisOptions) -> dict[str, Any]:
        controls = options.controls
        context = {key: _thaw_json(value) for key, value in self._spec.custom_variables.items()}
        reserved = sorted(set(options.variables) & _RESERVED_CONTEXT_KEYS)
        if reserved:
            names = ", ".join(reserved)
            raise ProviderError(
                f"custom variables cannot replace reserved values: {names}",
                retryable=False,
            )
        context.update({key: _thaw_json(value) for key, value in options.variables.items()})
        missing = [
            name
            for name in self._spec.required_variables
            if name not in context or context[name] is None
        ]
        if missing:
            raise ProviderError(
                "missing required custom variables: " + ", ".join(sorted(missing)),
                retryable=False,
            )
        context.update(
            {
                "text": text,
                "model": options.model,
                "voice": options.voice,
                "instructions": options.instructions,
                "tone": controls.tone.value,
                "pace": controls.pace.value,
                "vocal_style": controls.vocal_style.value,
                "nonverbal_frequency": controls.nonverbal_frequency.value,
            }
        )
        if self._api_key:
            context["api_key"] = self._api_key
        return context

    def _render_request(self, text: str, options: SynthesisOptions) -> _RenderedRequest:
        context = self._context(text, options)
        url = _render_template(self._spec.url, context, "url")
        raw_headers = _render_template(self._spec.headers, context, "headers")
        raw_query = _render_template(self._spec.query, context, "query")
        body = _render_template(self._spec.body_template, context, "body")
        if not isinstance(url, str) or not url.strip():
            raise ProviderError("rendered endpoint URL must be a non-empty string", retryable=False)
        if not isinstance(raw_headers, dict) or not isinstance(raw_query, dict):
            raise ProviderError("rendered headers and query must be objects", retryable=False)
        headers = {str(key): _stringify(value) for key, value in raw_headers.items()}
        query = {str(key): _query_value(value) for key, value in raw_query.items()}
        self._apply_auth(headers, query)
        return _RenderedRequest(url=url, headers=headers, query=query, body=body)

    def _apply_auth(self, headers: dict[str, str], query: dict[str, Any]) -> None:
        location = self._spec.auth_location
        if location == GenericRestAuthLocation.NONE:
            return
        if not self._api_key:
            raise ProviderError(f"{self._spec.name} API key is not configured", retryable=False)
        value = (
            f"{self._spec.auth_prefix.strip()} {self._api_key}"
            if self._spec.auth_prefix.strip()
            else self._api_key
        )
        if location == GenericRestAuthLocation.HEADER:
            headers[self._spec.auth_name] = value
        else:
            query[self._spec.auth_name] = value

    def _limit_value(self, text: str, options: SynthesisOptions) -> str:
        if self._spec.limit_basis == GenericRestLimitBasis.TEXT:
            return text
        body = _render_template(self._spec.body_template, self._context(text, options), "body")
        return _serialize_json(body)

    def _validate_limits(
        self, text: str, options: SynthesisOptions, rendered_body: JsonTemplate
    ) -> None:
        value = (
            text
            if self._spec.limit_basis == GenericRestLimitBasis.TEXT
            else _serialize_json(rendered_body)
        )
        measurements = {
            "characters": len(value),
            "UTF-8 bytes": len(value.encode("utf-8")),
            "estimated tokens": max(1, math.ceil(len(value) / 4)),
            "words": len(_WORD_RE.findall(value)),
        }
        limits = {
            "characters": self._spec.max_input_characters,
            "UTF-8 bytes": self._spec.max_input_bytes,
            "estimated tokens": self._spec.max_input_tokens,
            "words": self._spec.max_input_words,
        }
        for label, actual in measurements.items():
            maximum = limits[label]
            if maximum is not None and actual > maximum:
                raise ProviderError(
                    f"{self._spec.name} rendered {self._spec.limit_basis} has {actual} "
                    f"{label}; limit is {maximum}",
                    retryable=False,
                )

    def _decode_response(self, response: httpx.Response) -> AudioChunk:
        mode = self._spec.response_mode
        if mode in {
            GenericRestResponseMode.JSON_BASE64_RAW_PCM16,
            GenericRestResponseMode.JSON_BASE64_WAV,
        }:
            try:
                payload = response.json()
            except (json.JSONDecodeError, ValueError):
                raise ProviderError(
                    f"{self._spec.name} returned invalid JSON audio data", retryable=True
                ) from None
            encoded = _json_pointer(payload, self._spec.response_json_pointer, self._spec.name)
            if not isinstance(encoded, str) or not encoded:
                raise ProviderError(
                    f"{self._spec.name} JSON audio value must be a non-empty base64 string",
                    retryable=True,
                )
            try:
                audio = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError, TypeError) as error:
                raise ProviderError(
                    f"{self._spec.name} returned invalid base64 audio data", retryable=True
                ) from error
        else:
            audio = response.content

        if mode in {
            GenericRestResponseMode.WAV_PCM16,
            GenericRestResponseMode.JSON_BASE64_WAV,
        }:
            pcm = _decode_and_normalize_wav(audio, self._spec.name)
        else:
            pcm = _normalize_pcm(
                audio,
                provider_name=self._spec.name,
                sample_rate=self._spec.response_sample_rate,
                channels=self._spec.response_channels,
                sample_width=self._spec.response_sample_width,
            )
        return AudioChunk(pcm=pcm, format=CANONICAL_AUDIO_FORMAT)

    def _http_error(
        self,
        response: httpx.Response,
        *,
        diagnostic: ProviderDiagnostic | None = None,
    ) -> ProviderError:
        status = response.status_code
        retryable = status in _TRANSIENT_STATUSES or 500 <= status <= 599
        retry_after = _parse_retry_after(response.headers.get("retry-after"))
        detail = _sanitize(response.text.strip() or response.reason_phrase, self._api_key)
        detail = detail[:_ERROR_TEXT_LIMIT]
        suffix = f": {detail}" if detail else ""
        return ProviderError(
            f"{self._spec.name} request failed ({status}){suffix}",
            retryable=retryable,
            status_code=status,
            retry_after=retry_after,
            diagnostic=diagnostic,
        )


def _freeze_mapping(value: Mapping[str, JsonTemplate], label: str) -> Mapping[str, JsonTemplate]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    frozen: dict[str, JsonTemplate] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise ValueError(f"{label} keys must be strings")
        frozen[key] = _freeze_json(item)
    return MappingProxyType(frozen)


def _freeze_json(value: JsonTemplate) -> JsonTemplate:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_json(item) for key, item in value.items()})
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: JsonTemplate) -> JsonTemplate:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_thaw_json(item) for item in value]
    return value


def _resolve_placeholder(name: str, context: Mapping[str, Any], path: str) -> Any:
    if name in context:
        return context[name]
    parts = name.split(".")
    current: Any = context
    for part in parts:
        if isinstance(current, Mapping) and part in current:
            current = current[part]
        elif isinstance(current, Sequence) and not isinstance(current, (str, bytes, bytearray)):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                break
        else:
            break
    else:
        return current
    raise ProviderError(f"missing template variable '{name}' at {path}", retryable=False)


def _render_template(value: JsonTemplate, context: Mapping[str, Any], path: str) -> JsonTemplate:
    if isinstance(value, str):
        whole = _PLACEHOLDER_RE.fullmatch(value)
        if whole:
            return _thaw_json(_resolve_placeholder(whole.group(1), context, path))

        def replace(match: re.Match[str]) -> str:
            return _stringify(_resolve_placeholder(match.group(1), context, path))

        return _PLACEHOLDER_RE.sub(replace, value)
    if isinstance(value, Mapping):
        rendered: dict[str, JsonTemplate] = {}
        for key, item in value.items():
            rendered_key = _render_template(str(key), context, f"{path}.<key>")
            rendered[str(rendered_key)] = _render_template(item, context, f"{path}.{rendered_key}")
        return rendered
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [
            _render_template(item, context, f"{path}[{index}]") for index, item in enumerate(value)
        ]
    return value


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (Mapping, list, tuple)):
        return _serialize_json(_thaw_json(value))
    return str(value)


def _query_value(value: Any) -> Any:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_stringify(item) for item in value]
    return _stringify(value)


def _serialize_json(value: JsonTemplate) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as error:
        raise ProviderError("rendered request body is not valid JSON", retryable=False) from error


def _json_pointer(payload: Any, pointer: str, provider_name: str) -> Any:
    current = payload
    if not pointer:
        return current
    for encoded_part in pointer[1:].split("/"):
        part = encoded_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping) and part in current:
            current = current[part]
            continue
        if isinstance(current, list):
            try:
                current = current[int(part)]
                continue
            except (ValueError, IndexError):
                pass
        raise ProviderError(
            f"{provider_name} response JSON pointer '{pointer}' was not found",
            retryable=True,
        )
    return current


def _normalize_pcm(
    audio: bytes,
    *,
    provider_name: str,
    sample_rate: int,
    channels: int,
    sample_width: int,
) -> bytes:
    frame_width = channels * sample_width
    if not audio or len(audio) % frame_width:
        raise ProviderError(f"{provider_name} returned invalid PCM frame data", retryable=True)
    samples = _pcm_samples(audio, sample_width)
    if channels > 1:
        samples = [
            max(-32_768, min(32_767, sum(samples[index : index + channels]) // channels))
            for index in range(0, len(samples), channels)
        ]
    if sample_rate != CANONICAL_AUDIO_FORMAT.sample_rate:
        samples = _resample_linear(
            samples,
            source_rate=sample_rate,
            target_rate=CANONICAL_AUDIO_FORMAT.sample_rate,
        )
    result = array("h", samples)
    if sys.byteorder != "little":  # pragma: no cover - Windows/Linux production is little-endian
        result.byteswap()
    return result.tobytes()


def _pcm_samples(audio: bytes, sample_width: int) -> list[int]:
    if sample_width == 1:
        return [(sample - 128) << 8 for sample in audio]
    if sample_width == 2:
        samples = array("h")
        samples.frombytes(audio)
        if sys.byteorder != "little":  # pragma: no cover
            samples.byteswap()
        return list(samples)
    if sample_width == 4:
        samples32 = array("i")
        samples32.frombytes(audio)
        if sys.byteorder != "little":  # pragma: no cover
            samples32.byteswap()
        return [sample >> 16 for sample in samples32]
    samples24: list[int] = []
    for index in range(0, len(audio), 3):
        value = audio[index] | (audio[index + 1] << 8) | (audio[index + 2] << 16)
        if value & 0x800000:
            value -= 1 << 24
        samples24.append(value >> 8)
    return samples24


def _resample_linear(
    samples: list[int],
    *,
    source_rate: int,
    target_rate: int,
) -> list[int]:
    if not samples:
        return []
    output_count = max(1, round(len(samples) * target_rate / source_rate))
    output: list[int] = []
    for output_index in range(output_count):
        numerator = output_index * source_rate
        left = min(numerator // target_rate, len(samples) - 1)
        right = min(left + 1, len(samples) - 1)
        remainder = numerator % target_rate
        value = (
            samples[left] * (target_rate - remainder) + samples[right] * remainder
        ) // target_rate
        output.append(max(-32_768, min(32_767, value)))
    return output


def _decode_and_normalize_wav(audio: bytes, provider_name: str) -> bytes:
    try:
        with wave.open(io.BytesIO(audio), "rb") as source:
            channels = source.getnchannels()
            sample_width = source.getsampwidth()
            sample_rate = source.getframerate()
            compression = source.getcomptype()
            frame_count = source.getnframes()
            pcm = source.readframes(frame_count)
    except (EOFError, wave.Error) as error:
        raise ProviderError(
            f"{provider_name} returned an invalid WAV file", retryable=True
        ) from error
    if compression != "NONE":
        raise ProviderError(
            f"{provider_name} returned compressed WAV audio ({compression})",
            retryable=False,
        )
    expected_bytes = frame_count * channels * sample_width
    if not pcm or len(pcm) != expected_bytes:
        raise ProviderError(f"{provider_name} returned invalid PCM frame data", retryable=True)
    return _normalize_pcm(
        pcm,
        provider_name=provider_name,
        sample_rate=sample_rate,
        channels=channels,
        sample_width=sample_width,
    )


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


def _sanitize(value: str, secret: str | None) -> str:
    sanitized = value.replace("\r", " ").replace("\n", " ")
    if secret:
        for candidate in {secret, quote(secret, safe=""), quote_plus(secret)}:
            if candidate:
                sanitized = sanitized.replace(candidate, "[REDACTED]")
    return " ".join(sanitized.split())
