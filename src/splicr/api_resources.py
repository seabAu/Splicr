"""Versioned, secret-free definitions for configurable TTS API resources."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import threading
from types import MappingProxyType
from typing import Any, Final
from urllib.parse import urlsplit

from .secret_vault import (
    KeyringSecretVault,
    SecretVault,
    SecretVaultUnavailableError,
)


_SCHEMA_VERSION: Final = 1
_RESOURCE_ID_RE = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")
_VARIABLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_HEADER_NAME_RE = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_DANGEROUS_TRANSPORT_HEADERS = frozenset(
    {
        "connection",
        "content-length",
        "cookie",
        "host",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "set-cookie",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)
_STATIC_SECRET_HEADERS = frozenset({"authorization", "x-api-key", "x-goog-api-key"})
_SECRET_FIELD_RE = re.compile(r"(?:authorization|api[-_]?key|access[-_]?token|secret)", re.I)

JsonScalar = str | int | float | bool | None
JsonValue = JsonScalar | tuple["JsonValue", ...] | Mapping[str, "JsonValue"]


class AdapterType(StrEnum):
    GEMINI = "gemini"
    DEEPGRAM = "deepgram"
    INWORLD = "inworld"
    GENERIC_REST = "generic_rest"


class HttpMethod(StrEnum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"


class AuthMode(StrEnum):
    NONE = "none"
    HEADER = "header"
    QUERY = "query"
    TEMPLATE = "template"


class ResponseMode(StrEnum):
    RAW_PCM = "raw_pcm"
    WAV = "wav"
    JSON_BASE64_PCM = "json_base64_pcm"
    JSON_BASE64_WAV = "json_base64_wav"


class VariableType(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    JSON = "json"


class LimitBasis(StrEnum):
    TEXT = "text"
    BODY = "body"


class CapabilityMode(StrEnum):
    NATIVE_ENUM = "native_enum"
    NATIVE_SCALAR = "native_scalar"
    PROMPT = "prompt"
    INLINE_MARKUP = "inline_markup"
    CLIENT_TRANSFORM = "client_transform"
    UNSUPPORTED = "unsupported"


def _non_empty(value: str, field_name: str, *, maximum: int = 255) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    if len(value) > maximum:
        raise ValueError(f"{field_name} cannot exceed {maximum} characters")
    if any(character in value for character in ("\x00", "\r", "\n")):
        raise ValueError(f"{field_name} contains an invalid control character")
    return value


def _is_finite_number(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _string_tuple(values: Sequence[str], field_name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise TypeError(f"{field_name} values must be an array")
    result = tuple(_non_empty(value, field_name) for value in values)
    if len(result) != len(set(result)):
        raise ValueError(f"{field_name} values must be unique")
    return result


def _enum_tuple(
    values: Sequence[CapabilityMode | str], field_name: str
) -> tuple[CapabilityMode, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise TypeError(f"{field_name} values must be an array")
    result = tuple(CapabilityMode(value) for value in values)
    if len(result) != len(set(result)):
        raise ValueError(f"{field_name} values must be unique")
    return result


def _freeze_json(
    value: Any,
    *,
    path: str = "$",
    active_containers: set[int] | None = None,
) -> JsonValue:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} contains a non-finite number")
        return value
    if active_containers is None:
        active_containers = set()
    if isinstance(value, Mapping):
        identity = id(value)
        if identity in active_containers:
            raise ValueError(f"{path} contains a circular reference")
        active_containers.add(identity)
        try:
            items: dict[str, JsonValue] = {}
            keys = tuple(value)
            if any(not isinstance(key, str) for key in keys):
                raise TypeError(f"{path} contains a non-string object key")
            for key in sorted(keys):
                items[key] = _freeze_json(
                    value[key], path=f"{path}.{key}", active_containers=active_containers
                )
            return MappingProxyType(items)
        finally:
            active_containers.remove(identity)
    if isinstance(value, (list, tuple)):
        identity = id(value)
        if identity in active_containers:
            raise ValueError(f"{path} contains a circular reference")
        active_containers.add(identity)
        try:
            return tuple(
                _freeze_json(item, path=f"{path}[{index}]", active_containers=active_containers)
                for index, item in enumerate(value)
            )
        finally:
            active_containers.remove(identity)
    raise TypeError(f"{path} contains a non-JSON value of type {type(value).__name__}")


def _freeze_object(value: Mapping[str, Any], field_name: str) -> Mapping[str, JsonValue]:
    frozen = _freeze_json(value, path=field_name)
    if not isinstance(frozen, Mapping):  # pragma: no cover - type narrowing guard
        raise TypeError(f"{field_name} must be a JSON object")
    return frozen


def _thaw_json(value: JsonValue) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _canonical_json(value: JsonValue) -> str:
    return json.dumps(_thaw_json(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _validate_base_url(value: str, *, allow_insecure_http: bool) -> str:
    value = _non_empty(value, "base_url", maximum=2_048)
    if value != value.strip() or "\\" in value or any(character.isspace() for character in value):
        raise ValueError("base_url cannot contain whitespace or backslashes")
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError as error:
        raise ValueError("base_url contains an invalid port") from error
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("base_url must use HTTPS (or explicitly permitted HTTP)")
    if not parsed.hostname:
        raise ValueError("base_url must include a hostname")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("base_url cannot contain embedded credentials")
    if parsed.fragment:
        raise ValueError("base_url cannot contain a fragment")
    if parsed.scheme.lower() == "http" and not (
        allow_insecure_http or _is_loopback_host(parsed.hostname)
    ):
        raise ValueError(
            "HTTP is allowed only for loopback URLs unless allow_insecure_http is true"
        )
    return value


def _is_loopback_host(hostname: str) -> bool:
    if hostname.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _validate_header_name(name: str, *, permit_auth_header: bool = False) -> str:
    if not _HEADER_NAME_RE.fullmatch(name):
        raise ValueError(f"invalid HTTP header name: {name!r}")
    normalized = name.casefold()
    if normalized in _DANGEROUS_TRANSPORT_HEADERS:
        raise ValueError(f"transport-controlled header is not allowed: {name}")
    if not permit_auth_header and (
        normalized in _STATIC_SECRET_HEADERS or _SECRET_FIELD_RE.search(normalized)
    ):
        raise ValueError(f"credential-bearing header must use the auth configuration: {name}")
    return name


def _assert_no_header_newlines(value: JsonValue, field_name: str) -> None:
    if isinstance(value, str) and ("\r" in value or "\n" in value):
        raise ValueError(f"{field_name} cannot contain CR or LF characters")
    if isinstance(value, Mapping):
        for nested in value.values():
            _assert_no_header_newlines(nested, field_name)
    elif isinstance(value, tuple):
        for nested in value:
            _assert_no_header_newlines(nested, field_name)


@dataclass(frozen=True, slots=True)
class ApiAuthSpec:
    mode: AuthMode = AuthMode.NONE
    name: str | None = None
    prefix: str = ""
    credential_reference: str | None = None
    env_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", AuthMode(self.mode))
        if isinstance(self.env_keys, (str, bytes, bytearray)) or not isinstance(
            self.env_keys, Sequence
        ):
            raise TypeError("env_keys must be an array")
        object.__setattr__(self, "env_keys", tuple(self.env_keys))
        if self.mode is AuthMode.NONE:
            if self.name is not None or self.prefix or self.credential_reference or self.env_keys:
                raise ValueError("auth mode 'none' cannot include credential settings")
            return
        if self.mode is AuthMode.TEMPLATE:
            if self.name is not None or self.prefix:
                raise ValueError("template auth cannot include a header/query name or prefix")
        else:
            if self.name is None:
                raise ValueError("header/query auth requires a name")
            if self.mode is AuthMode.HEADER:
                _validate_header_name(self.name, permit_auth_header=True)
            else:
                _non_empty(self.name, "auth query name")
        if not isinstance(self.prefix, str):
            raise TypeError("auth prefix must be a string")
        if len(self.prefix) > 100 or any(c in self.prefix for c in ("\x00", "\r", "\n")):
            raise ValueError("auth prefix is invalid")
        if self.credential_reference is not None:
            _non_empty(self.credential_reference, "credential_reference")
        for env_key in self.env_keys:
            if not _ENV_NAME_RE.fullmatch(env_key):
                raise ValueError(f"invalid environment key reference: {env_key!r}")
        if len(self.env_keys) != len(set(self.env_keys)):
            raise ValueError("environment key references must be unique")


@dataclass(frozen=True, slots=True)
class ApiVariableDefinition:
    name: str
    kind: VariableType = VariableType.STRING
    label: str | None = None
    description: str = ""
    group: str = "General"
    required: bool = False
    default: JsonValue = None
    choices: tuple[JsonValue, ...] = ()
    minimum: int | float | None = None
    maximum: int | float | None = None
    step: int | float | None = None
    unit: str | None = None
    sensitive: bool = False
    read_only: bool = False
    randomizable: bool = False
    visible_when: Mapping[str, JsonValue] = field(default_factory=dict)
    enabled_when: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not _VARIABLE_NAME_RE.fullmatch(self.name):
            raise ValueError(f"invalid variable name: {self.name!r}")
        object.__setattr__(self, "kind", VariableType(self.kind))
        if self.label is not None:
            _non_empty(self.label, "variable label")
        if len(self.description) > 2_000:
            raise ValueError("variable description cannot exceed 2000 characters")
        _non_empty(self.group, "variable group")
        if any(
            not isinstance(value, bool)
            for value in (self.required, self.sensitive, self.read_only, self.randomizable)
        ):
            raise TypeError("variable flags must be booleans")
        default = _freeze_json(self.default, path=f"variable {self.name} default")
        if isinstance(self.choices, (str, bytes, bytearray)) or not isinstance(
            self.choices, Sequence
        ):
            raise TypeError("variable choices must be an array")
        choices = tuple(
            _freeze_json(choice, path=f"variable {self.name} choice") for choice in self.choices
        )
        object.__setattr__(self, "default", default)
        object.__setattr__(self, "choices", choices)
        if default is not None and not _matches_variable_type(default, self.kind):
            raise ValueError(f"default for {self.name} does not match {self.kind.value}")
        if any(not _matches_variable_type(choice, self.kind) for choice in choices):
            raise ValueError(f"choice for {self.name} does not match {self.kind.value}")
        signatures = tuple(_canonical_json(choice) for choice in choices)
        if len(signatures) != len(set(signatures)):
            raise ValueError(f"choices for {self.name} must be unique")
        if choices and default is not None and _canonical_json(default) not in signatures:
            raise ValueError(f"default for {self.name} must be one of its choices")
        if self.sensitive and (default is not None or choices):
            raise ValueError("sensitive variables cannot declare defaults or choices")
        if self.randomizable and self.kind is not VariableType.INTEGER:
            raise ValueError("randomizable variables must be integers")
        numeric_metadata = (self.minimum, self.maximum, self.step)
        if any(value is not None for value in numeric_metadata):
            if self.kind not in {VariableType.INTEGER, VariableType.NUMBER}:
                raise ValueError("variable range metadata requires integer or number kind")
            if any(not _is_finite_number(value) for value in numeric_metadata if value is not None):
                raise ValueError("variable range metadata must contain finite numbers")
            if self.minimum is not None and self.maximum is not None:
                if self.minimum > self.maximum:
                    raise ValueError("variable minimum cannot exceed maximum")
            if self.step is not None and self.step <= 0:
                raise ValueError("variable step must be positive")
        if self.kind is VariableType.INTEGER and any(
            value is not None and (isinstance(value, bool) or not isinstance(value, int))
            for value in numeric_metadata
        ):
            raise ValueError("integer variable range metadata must use integers")
        if self.unit is not None:
            _non_empty(self.unit, "variable unit", maximum=100)
        if isinstance(default, (int, float)) and not isinstance(default, bool):
            if self.minimum is not None and default < self.minimum:
                raise ValueError(f"default for {self.name} is below its minimum")
            if self.maximum is not None and default > self.maximum:
                raise ValueError(f"default for {self.name} exceeds its maximum")
        for choice in choices:
            if isinstance(choice, (int, float)) and not isinstance(choice, bool):
                if self.minimum is not None and choice < self.minimum:
                    raise ValueError(f"choice for {self.name} is below its minimum")
                if self.maximum is not None and choice > self.maximum:
                    raise ValueError(f"choice for {self.name} exceeds its maximum")
        visible_when = _freeze_object(self.visible_when, f"variable {self.name} visible_when")
        enabled_when = _freeze_object(self.enabled_when, f"variable {self.name} enabled_when")
        for condition_key in (*visible_when, *enabled_when):
            if not _VARIABLE_NAME_RE.fullmatch(condition_key):
                raise ValueError(f"invalid variable condition key: {condition_key!r}")
            if condition_key == self.name:
                raise ValueError("a variable cannot condition itself")
        object.__setattr__(self, "visible_when", visible_when)
        object.__setattr__(self, "enabled_when", enabled_when)


def _matches_variable_type(value: JsonValue, kind: VariableType) -> bool:
    if kind is VariableType.JSON:
        return True
    if kind is VariableType.STRING:
        return isinstance(value, str)
    if kind is VariableType.BOOLEAN:
        return isinstance(value, bool)
    if kind is VariableType.INTEGER:
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, (int, float)) and not isinstance(value, bool)


@dataclass(frozen=True, slots=True)
class ApiResponseSpec:
    mode: ResponseMode
    json_pointer: str | None = None
    sample_rate_hz: int = 24_000
    channels: int = 1
    sample_width_bytes: int = 2

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", ResponseMode(self.mode))
        is_json = self.mode in {ResponseMode.JSON_BASE64_PCM, ResponseMode.JSON_BASE64_WAV}
        if is_json:
            if self.json_pointer is None or not self.json_pointer.startswith("/"):
                raise ValueError("JSON base64 responses require an absolute JSON Pointer")
            if re.search(r"~(?:[^01]|$)", self.json_pointer):
                raise ValueError("json_pointer contains an invalid escape")
        elif self.json_pointer is not None:
            raise ValueError("json_pointer is valid only for JSON response modes")
        if (
            isinstance(self.sample_rate_hz, bool)
            or not isinstance(self.sample_rate_hz, int)
            or self.sample_rate_hz <= 0
        ):
            raise ValueError("sample_rate_hz must be positive")
        if (
            isinstance(self.channels, bool)
            or not isinstance(self.channels, int)
            or self.channels <= 0
        ):
            raise ValueError("channels must be positive")
        if (
            isinstance(self.sample_width_bytes, bool)
            or not isinstance(self.sample_width_bytes, int)
            or self.sample_width_bytes not in {1, 2, 3, 4}
        ):
            raise ValueError("sample_width_bytes must be between 1 and 4")


@dataclass(frozen=True, slots=True)
class TtsVoiceSpec:
    id: str
    label: str | None = None
    traits: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _non_empty(self.id, "voice id")
        if self.label is not None:
            _non_empty(self.label, "voice label")
        object.__setattr__(self, "traits", _string_tuple(self.traits, "voice trait"))


@dataclass(frozen=True, slots=True)
class TtsDefaults:
    default_model: str
    default_voice: str
    models: tuple[str, ...] = ()
    voices: tuple[TtsVoiceSpec, ...] = ()

    def __post_init__(self) -> None:
        _non_empty(self.default_model, "default_model")
        _non_empty(self.default_voice, "default_voice")
        models = _string_tuple(self.models, "model")
        if isinstance(self.voices, (str, bytes, bytearray)) or not isinstance(
            self.voices, Sequence
        ):
            raise TypeError("voices must be an array")
        voices = tuple(self.voices)
        if any(not isinstance(voice, TtsVoiceSpec) for voice in voices):
            raise TypeError("voices must contain TtsVoiceSpec values")
        voice_ids = tuple(voice.id for voice in voices)
        if len(voice_ids) != len(set(voice_ids)):
            raise ValueError("voice ids must be unique")
        if models and self.default_model not in models:
            raise ValueError("default_model must be present in models")
        if voices and self.default_voice not in voice_ids:
            raise ValueError("default_voice must be present in voices")
        object.__setattr__(self, "models", models)
        object.__setattr__(self, "voices", voices)


@dataclass(frozen=True, slots=True)
class InputLimits:
    max_bytes: int | None = None
    max_tokens: int | None = None
    max_characters: int | None = None
    max_words: int | None = None
    recommended_bytes: int | None = None
    recommended_words: int | None = None
    recommended_characters: int | None = None
    limit_basis: LimitBasis = LimitBasis.TEXT

    def __post_init__(self) -> None:
        object.__setattr__(self, "limit_basis", LimitBasis(self.limit_basis))
        for name in (
            "max_bytes",
            "max_tokens",
            "max_characters",
            "max_words",
            "recommended_bytes",
            "recommended_words",
            "recommended_characters",
        ):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value <= 0
            ):
                raise ValueError(f"{name} must be positive when provided")
        for recommended, maximum in (
            (self.recommended_bytes, self.max_bytes),
            (self.recommended_characters, self.max_characters),
            (self.recommended_words, self.max_words),
        ):
            if recommended is not None and maximum is not None and recommended > maximum:
                raise ValueError("recommended input limit cannot exceed its hard limit")


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 3
    request_timeout_seconds: float = 300.0
    backoff_initial_seconds: float = 5.0
    backoff_max_seconds: float = 60.0
    jitter_seconds: float = 1.0
    retry_status_codes: tuple[int, ...] = (408, 425, 429, 500, 502, 503, 504)
    honor_retry_after: bool = True

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_attempts, bool)
            or not isinstance(self.max_attempts, int)
            or self.max_attempts < 1
        ):
            raise ValueError("max_attempts must be at least 1")
        if not _is_finite_number(self.request_timeout_seconds) or self.request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds must be positive")
        if not _is_finite_number(self.backoff_initial_seconds) or not _is_finite_number(
            self.backoff_max_seconds
        ):
            raise ValueError("retry backoff values must be finite numbers")
        if self.backoff_initial_seconds < 0 or self.backoff_max_seconds < 0:
            raise ValueError("retry backoff values cannot be negative")
        if self.backoff_initial_seconds > self.backoff_max_seconds:
            raise ValueError("initial retry backoff cannot exceed maximum backoff")
        if not _is_finite_number(self.jitter_seconds) or self.jitter_seconds < 0:
            raise ValueError("jitter_seconds cannot be negative")
        if isinstance(self.retry_status_codes, (str, bytes, bytearray)) or not isinstance(
            self.retry_status_codes, Sequence
        ):
            raise TypeError("retry_status_codes must be an array")
        codes = tuple(self.retry_status_codes)
        if any(
            isinstance(code, bool) or not isinstance(code, int) or not 100 <= code <= 599
            for code in codes
        ):
            raise ValueError("retry_status_codes must contain valid HTTP status codes")
        if len(codes) != len(set(codes)):
            raise ValueError("retry_status_codes must be unique")
        if not isinstance(self.honor_retry_after, bool):
            raise TypeError("honor_retry_after must be a boolean")
        object.__setattr__(self, "retry_status_codes", codes)


@dataclass(frozen=True, slots=True)
class PacingPolicy:
    minimum_interval_seconds: float = 0.0
    requests_per_minute: int | None = None
    max_concurrency: int = 1

    def __post_init__(self) -> None:
        if (
            not _is_finite_number(self.minimum_interval_seconds)
            or self.minimum_interval_seconds < 0
        ):
            raise ValueError("minimum_interval_seconds cannot be negative")
        if self.requests_per_minute is not None and (
            isinstance(self.requests_per_minute, bool)
            or not isinstance(self.requests_per_minute, int)
            or self.requests_per_minute <= 0
        ):
            raise ValueError("requests_per_minute must be positive when provided")
        if (
            isinstance(self.max_concurrency, bool)
            or not isinstance(self.max_concurrency, int)
            or self.max_concurrency < 1
        ):
            raise ValueError("max_concurrency must be at least 1")


@dataclass(frozen=True, slots=True)
class TtsCapabilities:
    tone_presets: tuple[str, ...] = ()
    speech_paces: tuple[str, ...] = ()
    vocal_styles: tuple[str, ...] = ()
    nonverbal_frequencies: tuple[str, ...] = ()
    tone_modes: tuple[CapabilityMode, ...] = ()
    pace_modes: tuple[CapabilityMode, ...] = ()
    vocal_style_modes: tuple[CapabilityMode, ...] = ()
    nonverbal_modes: tuple[CapabilityMode, ...] = ()
    nonverbal_cues: tuple[str, ...] = ()
    supports_custom_instructions: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.supports_custom_instructions, bool):
            raise TypeError("supports_custom_instructions must be a boolean")
        for name in (
            "tone_presets",
            "speech_paces",
            "vocal_styles",
            "nonverbal_frequencies",
            "nonverbal_cues",
        ):
            object.__setattr__(self, name, _string_tuple(getattr(self, name), name))
        for name in ("tone_modes", "pace_modes", "vocal_style_modes", "nonverbal_modes"):
            object.__setattr__(self, name, _enum_tuple(getattr(self, name), name))


@dataclass(frozen=True, slots=True)
class ApiResourceSpec:
    resource_id: str
    revision: int
    name: str
    adapter_type: AdapterType
    method: HttpMethod
    base_url: str
    description: str = ""
    allow_insecure_http: bool = False
    auth: ApiAuthSpec = field(default_factory=ApiAuthSpec)
    headers: Mapping[str, JsonValue] = field(default_factory=dict)
    query: Mapping[str, JsonValue] = field(default_factory=dict)
    request_template: Mapping[str, JsonValue] = field(default_factory=dict)
    variables: tuple[ApiVariableDefinition, ...] = ()
    response: ApiResponseSpec = field(default_factory=lambda: ApiResponseSpec(ResponseMode.RAW_PCM))
    defaults: TtsDefaults = field(default_factory=lambda: TtsDefaults("default", "default"))
    input_limits: InputLimits = field(default_factory=InputLimits)
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    pacing: PacingPolicy = field(default_factory=PacingPolicy)
    capabilities: TtsCapabilities = field(default_factory=TtsCapabilities)

    def __post_init__(self) -> None:
        if not _RESOURCE_ID_RE.fullmatch(self.resource_id):
            raise ValueError(
                "resource_id must start with a lowercase letter and contain only "
                "lowercase letters, digits, dots, underscores, or hyphens"
            )
        if (
            isinstance(self.revision, bool)
            or not isinstance(self.revision, int)
            or self.revision < 1
        ):
            raise ValueError("revision must be a positive integer")
        _non_empty(self.name, "resource name")
        if not isinstance(self.description, str):
            raise TypeError("resource description must be a string")
        if len(self.description) > 10_000:
            raise ValueError("resource description cannot exceed 10000 characters")
        if not isinstance(self.allow_insecure_http, bool):
            raise TypeError("allow_insecure_http must be a boolean")
        object.__setattr__(self, "adapter_type", AdapterType(self.adapter_type))
        object.__setattr__(self, "method", HttpMethod(self.method))
        object.__setattr__(
            self,
            "base_url",
            _validate_base_url(self.base_url, allow_insecure_http=self.allow_insecure_http),
        )
        if not isinstance(self.auth, ApiAuthSpec):
            raise TypeError("auth must be an ApiAuthSpec")
        headers = _freeze_object(self.headers, "headers")
        query = _freeze_object(self.query, "query")
        request_template = _freeze_object(self.request_template, "request_template")
        for header_name, header_value in headers.items():
            _validate_header_name(header_name)
            _assert_no_header_newlines(header_value, f"header {header_name}")
        normalized_headers = {header.casefold() for header in headers}
        auth_name = self.auth.name
        if (
            self.auth.mode is AuthMode.HEADER
            and auth_name is not None
            and auth_name.casefold() in normalized_headers
        ):
            raise ValueError("auth header cannot also appear in static headers")
        if self.auth.mode is AuthMode.QUERY and auth_name is not None and auth_name in query:
            raise ValueError("auth query parameter cannot also appear in static query values")
        secret_query_names = sorted(name for name in query if _SECRET_FIELD_RE.search(name))
        if secret_query_names:
            raise ValueError(
                "credential-bearing query values must use the auth configuration: "
                + ", ".join(secret_query_names)
            )
        if isinstance(self.variables, (str, bytes, bytearray)) or not isinstance(
            self.variables, Sequence
        ):
            raise TypeError("variables must be an array")
        variables = tuple(self.variables)
        if any(not isinstance(variable, ApiVariableDefinition) for variable in variables):
            raise TypeError("variables must contain ApiVariableDefinition values")
        variable_names = tuple(variable.name for variable in variables)
        if len(variable_names) != len(set(variable_names)):
            raise ValueError("variable names must be unique")
        for name, expected_type in (
            ("response", ApiResponseSpec),
            ("defaults", TtsDefaults),
            ("input_limits", InputLimits),
            ("retry", RetryPolicy),
            ("pacing", PacingPolicy),
            ("capabilities", TtsCapabilities),
        ):
            if not isinstance(getattr(self, name), expected_type):
                raise TypeError(f"{name} must be a {expected_type.__name__}")
        object.__setattr__(self, "headers", headers)
        object.__setattr__(self, "query", query)
        object.__setattr__(self, "request_template", request_template)
        object.__setattr__(self, "variables", variables)

    def to_dict(self) -> dict[str, Any]:
        """Return a deterministic-schema mapping that can never contain an API key."""

        return {
            "schema_version": _SCHEMA_VERSION,
            "resource_id": self.resource_id,
            "revision": self.revision,
            "name": self.name,
            "description": self.description,
            "adapter_type": self.adapter_type.value,
            "method": self.method.value,
            "base_url": self.base_url,
            "allow_insecure_http": self.allow_insecure_http,
            "auth": {
                "mode": self.auth.mode.value,
                "name": self.auth.name,
                "prefix": self.auth.prefix,
                "credential_reference": self.auth.credential_reference,
                "env_keys": list(self.auth.env_keys),
            },
            "headers": _thaw_json(self.headers),
            "query": _thaw_json(self.query),
            "request_template": _thaw_json(self.request_template),
            "variables": [
                {
                    "name": variable.name,
                    "kind": variable.kind.value,
                    "label": variable.label,
                    "description": variable.description,
                    "group": variable.group,
                    "required": variable.required,
                    "default": _thaw_json(variable.default),
                    "choices": [_thaw_json(choice) for choice in variable.choices],
                    "minimum": variable.minimum,
                    "maximum": variable.maximum,
                    "step": variable.step,
                    "unit": variable.unit,
                    "sensitive": variable.sensitive,
                    "read_only": variable.read_only,
                    "randomizable": variable.randomizable,
                    "visible_when": _thaw_json(variable.visible_when),
                    "enabled_when": _thaw_json(variable.enabled_when),
                }
                for variable in self.variables
            ],
            "response": {
                "mode": self.response.mode.value,
                "json_pointer": self.response.json_pointer,
                "sample_rate_hz": self.response.sample_rate_hz,
                "channels": self.response.channels,
                "sample_width_bytes": self.response.sample_width_bytes,
            },
            "defaults": {
                "default_model": self.defaults.default_model,
                "default_voice": self.defaults.default_voice,
                "models": list(self.defaults.models),
                "voices": [
                    {"id": voice.id, "label": voice.label, "traits": list(voice.traits)}
                    for voice in self.defaults.voices
                ],
            },
            "input_limits": {
                "max_bytes": self.input_limits.max_bytes,
                "max_tokens": self.input_limits.max_tokens,
                "max_characters": self.input_limits.max_characters,
                "max_words": self.input_limits.max_words,
                "recommended_bytes": self.input_limits.recommended_bytes,
                "recommended_words": self.input_limits.recommended_words,
                "recommended_characters": self.input_limits.recommended_characters,
                "limit_basis": self.input_limits.limit_basis.value,
            },
            "retry": {
                "max_attempts": self.retry.max_attempts,
                "request_timeout_seconds": self.retry.request_timeout_seconds,
                "backoff_initial_seconds": self.retry.backoff_initial_seconds,
                "backoff_max_seconds": self.retry.backoff_max_seconds,
                "jitter_seconds": self.retry.jitter_seconds,
                "retry_status_codes": list(self.retry.retry_status_codes),
                "honor_retry_after": self.retry.honor_retry_after,
            },
            "pacing": {
                "minimum_interval_seconds": self.pacing.minimum_interval_seconds,
                "requests_per_minute": self.pacing.requests_per_minute,
                "max_concurrency": self.pacing.max_concurrency,
            },
            "capabilities": {
                "tone_presets": list(self.capabilities.tone_presets),
                "speech_paces": list(self.capabilities.speech_paces),
                "vocal_styles": list(self.capabilities.vocal_styles),
                "nonverbal_frequencies": list(self.capabilities.nonverbal_frequencies),
                "tone_modes": [mode.value for mode in self.capabilities.tone_modes],
                "pace_modes": [mode.value for mode in self.capabilities.pace_modes],
                "vocal_style_modes": [mode.value for mode in self.capabilities.vocal_style_modes],
                "nonverbal_modes": [mode.value for mode in self.capabilities.nonverbal_modes],
                "nonverbal_cues": list(self.capabilities.nonverbal_cues),
                "supports_custom_instructions": self.capabilities.supports_custom_instructions,
            },
        }

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )

    @classmethod
    def from_json(cls, payload: str) -> "ApiResourceSpec":
        try:
            value = json.loads(payload)
        except (TypeError, json.JSONDecodeError) as error:
            raise ValueError("invalid API resource JSON") from error
        if not isinstance(value, dict):
            raise ValueError("API resource JSON must contain an object")
        return cls.from_dict(value)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ApiResourceSpec":
        _reject_unknown_keys(
            value,
            {
                "schema_version",
                "resource_id",
                "revision",
                "name",
                "description",
                "adapter_type",
                "method",
                "base_url",
                "allow_insecure_http",
                "auth",
                "headers",
                "query",
                "request_template",
                "variables",
                "response",
                "defaults",
                "input_limits",
                "retry",
                "pacing",
                "capabilities",
            },
            "resource",
        )
        if value.get("schema_version", _SCHEMA_VERSION) != _SCHEMA_VERSION:
            raise ValueError("unsupported API resource schema version")
        auth = _mapping(value.get("auth", {}), "auth")
        response = _mapping(value.get("response", {}), "response")
        defaults = _mapping(value.get("defaults", {}), "defaults")
        limits = _mapping(value.get("input_limits", {}), "input_limits")
        retry = _mapping(value.get("retry", {}), "retry")
        pacing = _mapping(value.get("pacing", {}), "pacing")
        capabilities = _mapping(value.get("capabilities", {}), "capabilities")
        _reject_unknown_keys(
            auth, {"mode", "name", "prefix", "credential_reference", "env_keys"}, "auth"
        )
        _reject_unknown_keys(
            response,
            {"mode", "json_pointer", "sample_rate_hz", "channels", "sample_width_bytes"},
            "response",
        )
        _reject_unknown_keys(
            defaults, {"default_model", "default_voice", "models", "voices"}, "defaults"
        )
        _reject_unknown_keys(
            limits,
            {
                "max_bytes",
                "max_tokens",
                "max_characters",
                "max_words",
                "recommended_bytes",
                "recommended_words",
                "recommended_characters",
                "limit_basis",
            },
            "input_limits",
        )
        _reject_unknown_keys(
            retry,
            {
                "max_attempts",
                "request_timeout_seconds",
                "backoff_initial_seconds",
                "backoff_max_seconds",
                "jitter_seconds",
                "retry_status_codes",
                "honor_retry_after",
            },
            "retry",
        )
        _reject_unknown_keys(
            pacing,
            {"minimum_interval_seconds", "requests_per_minute", "max_concurrency"},
            "pacing",
        )
        _reject_unknown_keys(
            capabilities,
            {
                "tone_presets",
                "speech_paces",
                "vocal_styles",
                "nonverbal_frequencies",
                "tone_modes",
                "pace_modes",
                "vocal_style_modes",
                "nonverbal_modes",
                "nonverbal_cues",
                "supports_custom_instructions",
            },
            "capabilities",
        )
        variables = tuple(
            _variable_from_dict(_mapping(item, "variable"))
            for item in _sequence(value.get("variables", ()), "variables")
        )
        voices = tuple(
            _voice_from_dict(_mapping(item, "voice"))
            for item in _sequence(defaults.get("voices", ()), "voices")
        )
        return cls(
            resource_id=value["resource_id"],
            revision=value.get("revision", 1),
            name=value["name"],
            description=value.get("description", ""),
            adapter_type=AdapterType(value["adapter_type"]),
            method=HttpMethod(value.get("method", HttpMethod.POST.value)),
            base_url=value["base_url"],
            allow_insecure_http=value.get("allow_insecure_http", False),
            auth=ApiAuthSpec(
                mode=AuthMode(auth.get("mode", AuthMode.NONE.value)),
                name=auth.get("name"),
                prefix=auth.get("prefix", ""),
                credential_reference=auth.get("credential_reference"),
                env_keys=tuple(auth.get("env_keys", ())),
            ),
            headers=_mapping(value.get("headers", {}), "headers"),
            query=_mapping(value.get("query", {}), "query"),
            request_template=_mapping(value.get("request_template", {}), "request_template"),
            variables=variables,
            response=ApiResponseSpec(
                mode=ResponseMode(response.get("mode", ResponseMode.RAW_PCM.value)),
                json_pointer=response.get("json_pointer"),
                sample_rate_hz=response.get("sample_rate_hz", 24_000),
                channels=response.get("channels", 1),
                sample_width_bytes=response.get("sample_width_bytes", 2),
            ),
            defaults=TtsDefaults(
                default_model=defaults["default_model"],
                default_voice=defaults["default_voice"],
                models=tuple(defaults.get("models", ())),
                voices=voices,
            ),
            input_limits=InputLimits(
                **{
                    **limits,
                    "limit_basis": LimitBasis(limits.get("limit_basis", LimitBasis.TEXT.value)),
                }
            ),
            retry=RetryPolicy(**retry),
            pacing=PacingPolicy(**pacing),
            capabilities=TtsCapabilities(**capabilities),
        )


def _mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be an object")
    return value


def _sequence(value: Any, field_name: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError(f"{field_name} must be an array")
    return value


def _reject_unknown_keys(value: Mapping[str, Any], allowed: set[str], field_name: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"unknown {field_name} field(s): {', '.join(unknown)}")


def _variable_from_dict(value: Mapping[str, Any]) -> ApiVariableDefinition:
    _reject_unknown_keys(
        value,
        {
            "name",
            "kind",
            "label",
            "description",
            "group",
            "required",
            "default",
            "choices",
            "minimum",
            "maximum",
            "step",
            "unit",
            "sensitive",
            "read_only",
            "randomizable",
            "visible_when",
            "enabled_when",
        },
        "variable",
    )
    return ApiVariableDefinition(
        name=value["name"],
        kind=VariableType(value.get("kind", VariableType.STRING.value)),
        label=value.get("label"),
        description=value.get("description", ""),
        group=value.get("group", "General"),
        required=value.get("required", False),
        default=value.get("default"),
        choices=tuple(value.get("choices", ())),
        minimum=value.get("minimum"),
        maximum=value.get("maximum"),
        step=value.get("step"),
        unit=value.get("unit"),
        sensitive=value.get("sensitive", False),
        read_only=value.get("read_only", False),
        randomizable=value.get("randomizable", False),
        visible_when=_mapping(value.get("visible_when", {}), "variable visible_when"),
        enabled_when=_mapping(value.get("enabled_when", {}), "variable enabled_when"),
    )


def _voice_from_dict(value: Mapping[str, Any]) -> TtsVoiceSpec:
    _reject_unknown_keys(value, {"id", "label", "traits"}, "voice")
    return TtsVoiceSpec(
        id=value["id"], label=value.get("label"), traits=tuple(value.get("traits", ()))
    )


class ApiResourceStoreError(RuntimeError):
    """Base class for stable catalog-store failures."""


class ApiResourceNotFoundError(ApiResourceStoreError):
    """Raised when a requested resource or current revision does not exist."""


class ApiResourceConflictError(ApiResourceStoreError):
    """Raised when attempting to create an already-used resource id."""


class _ApiKeyUnchanged:
    __slots__ = ()


API_KEY_UNCHANGED: Final = _ApiKeyUnchanged()


@dataclass(frozen=True, slots=True)
class StoredResourceRevision:
    spec: ApiResourceSpec
    enabled: bool
    created_at: datetime
    deleted_at: datetime | None = None


class SqliteApiResourceStore:
    """Append-only resource revisions with one enabled head per resource id."""

    def __init__(
        self,
        database_path: Path,
        *,
        vault: SecretVault | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self.database_path = Path(database_path)
        self.vault = vault if vault is not None else KeyringSecretVault()
        self.environ = os.environ if environ is None else environ
        self._lock = threading.RLock()

    def initialize(self, *, seed_builtins: bool = True) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS api_resource_revisions (
                    resource_id TEXT NOT NULL,
                    revision INTEGER NOT NULL CHECK (revision > 0),
                    enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
                    spec_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    deleted_at TEXT,
                    PRIMARY KEY (resource_id, revision)
                );

                CREATE UNIQUE INDEX IF NOT EXISTS api_resource_enabled_head_idx
                    ON api_resource_revisions(resource_id)
                    WHERE enabled = 1;

                CREATE INDEX IF NOT EXISTS api_resource_enabled_name_idx
                    ON api_resource_revisions(enabled, resource_id);
                """
            )
        if seed_builtins:
            self.seed_builtins()

    def create(self, spec: ApiResourceSpec, *, api_key: str | None = None) -> ApiResourceSpec:
        if spec.revision != 1:
            raise ValueError("a new resource must start at revision 1")
        if api_key is not None and spec.auth.mode is AuthMode.NONE:
            raise ValueError("cannot save an API key for auth mode 'none'")
        reference = self._credential_reference(spec)
        secret_written = False
        with self._lock:
            try:
                with self._connect() as connection:
                    existing = connection.execute(
                        "SELECT 1 FROM api_resource_revisions WHERE resource_id = ? LIMIT 1",
                        (spec.resource_id,),
                    ).fetchone()
                    if existing is not None:
                        raise ApiResourceConflictError(
                            f"API resource already exists: {spec.resource_id}"
                        )
                    if api_key is not None:
                        self.vault.set_secret(reference, api_key)
                        secret_written = True
                    self._insert(connection, spec)
            except Exception:
                if secret_written:
                    self.vault.delete_secret(reference)
                raise
        return spec

    def update(
        self,
        resource_id: str,
        replacement: ApiResourceSpec,
        *,
        api_key: str | None | _ApiKeyUnchanged = API_KEY_UNCHANGED,
    ) -> ApiResourceSpec:
        if replacement.resource_id != resource_id:
            raise ValueError("replacement resource_id must match the resource being updated")
        with self._lock:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT * FROM api_resource_revisions
                    WHERE resource_id = ? AND enabled = 1
                    """,
                    (resource_id,),
                ).fetchone()
                if row is None:
                    raise ApiResourceNotFoundError(f"current API resource not found: {resource_id}")
                current = self._revision_from_row(row).spec
                next_spec = replace(replacement, revision=current.revision + 1)
                old_reference = self._credential_reference(current)
                new_reference = self._credential_reference(next_spec)
                if old_reference != new_reference and isinstance(api_key, _ApiKeyUnchanged):
                    raise ValueError(
                        "changing credential_reference requires explicitly replacing or clearing "
                        "the API key"
                    )
                if api_key is not None and not isinstance(api_key, _ApiKeyUnchanged):
                    if next_spec.auth.mode is AuthMode.NONE:
                        raise ValueError("cannot save an API key for auth mode 'none'")

                restore_secret: str | None | _ApiKeyUnchanged = API_KEY_UNCHANGED
                secret_changed = not isinstance(api_key, _ApiKeyUnchanged)
                if secret_changed:
                    restore_secret = self.vault.get_secret(new_reference)
                try:
                    if isinstance(api_key, str):
                        self.vault.set_secret(new_reference, api_key)
                    elif api_key is None:
                        self.vault.delete_secret(new_reference)
                    connection.execute(
                        "UPDATE api_resource_revisions SET enabled = 0 WHERE resource_id = ? "
                        "AND enabled = 1",
                        (resource_id,),
                    )
                    self._insert(connection, next_spec)
                except Exception:
                    if secret_changed:
                        if isinstance(restore_secret, str):
                            self.vault.set_secret(new_reference, restore_secret)
                        elif restore_secret is None:
                            self.vault.delete_secret(new_reference)
                    raise
        return next_spec

    def list(self) -> tuple[ApiResourceSpec, ...]:
        """List current enabled heads, ordered by display name then resource id."""

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM api_resource_revisions
                WHERE enabled = 1
                ORDER BY resource_id
                """
            ).fetchall()
        specs = tuple(self._revision_from_row(row).spec for row in rows)
        return tuple(sorted(specs, key=lambda spec: (spec.name.casefold(), spec.resource_id)))

    def list_revisions(self, resource_id: str) -> tuple[StoredResourceRevision, ...]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM api_resource_revisions
                WHERE resource_id = ? ORDER BY revision
                """,
                (resource_id,),
            ).fetchall()
        return tuple(self._revision_from_row(row) for row in rows)

    def get(self, resource_id: str, revision: int) -> ApiResourceSpec | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM api_resource_revisions
                WHERE resource_id = ? AND revision = ?
                """,
                (resource_id, revision),
            ).fetchone()
        return None if row is None else self._revision_from_row(row).spec

    def get_current(self, resource_id: str) -> ApiResourceSpec | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM api_resource_revisions
                WHERE resource_id = ? AND enabled = 1
                """,
                (resource_id,),
            ).fetchone()
        return None if row is None else self._revision_from_row(row).spec

    def soft_delete(self, resource_id: str, *, delete_secret: bool = False) -> bool:
        """Disable the current head while preserving all revisions for pinned jobs."""

        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM api_resource_revisions
                WHERE resource_id = ? AND enabled = 1
                """,
                (resource_id,),
            ).fetchone()
            if row is None:
                return False
            stored = self._revision_from_row(row)
            reference = self._credential_reference(stored.spec)
            restore_secret: str | None = None
            if delete_secret:
                restore_secret = self.vault.get_secret(reference)
            try:
                if delete_secret:
                    self.vault.delete_secret(reference)
                connection.execute(
                    """
                    UPDATE api_resource_revisions
                    SET enabled = 0, deleted_at = ?
                    WHERE resource_id = ? AND revision = ?
                    """,
                    (_utc_now().isoformat(), resource_id, stored.spec.revision),
                )
            except Exception:
                if delete_secret and restore_secret is not None:
                    self.vault.set_secret(reference, restore_secret)
                raise
        return True

    def seed_builtins(
        self, specs: Sequence[ApiResourceSpec] | None = None
    ) -> tuple[ApiResourceSpec, ...]:
        """Insert missing built-ins once without overwriting user revisions or deletions."""

        candidates = tuple(builtin_resource_specs() if specs is None else specs)
        inserted: list[ApiResourceSpec] = []
        with self._lock, self._connect() as connection:
            for spec in candidates:
                if spec.revision != 1:
                    raise ValueError("seed resources must start at revision 1")
                exists = connection.execute(
                    "SELECT 1 FROM api_resource_revisions WHERE resource_id = ? LIMIT 1",
                    (spec.resource_id,),
                ).fetchone()
                if exists is None:
                    self._insert(connection, spec)
                    inserted.append(spec)
        return tuple(inserted)

    def set_api_key(self, resource_id: str, api_key: str) -> None:
        spec = self.get_current(resource_id)
        if spec is None:
            raise ApiResourceNotFoundError(f"current API resource not found: {resource_id}")
        if spec.auth.mode is AuthMode.NONE:
            raise ValueError("cannot save an API key for auth mode 'none'")
        self.vault.set_secret(self._credential_reference(spec), api_key)

    def clear_api_key(self, resource_id: str) -> None:
        spec = self.get_current(resource_id)
        if spec is None:
            raise ApiResourceNotFoundError(f"current API resource not found: {resource_id}")
        self.vault.delete_secret(self._credential_reference(spec))

    def has_api_key(self, resource: str | ApiResourceSpec) -> bool:
        return self.resolve_api_key(resource) is not None

    def api_key_source(self, resource: str | ApiResourceSpec) -> str | None:
        _, source = self._resolve_api_key(resource)
        return source

    def resolve_api_key(self, resource: str | ApiResourceSpec) -> str | None:
        """Resolve a key for an adapter; never include this value in an API response."""

        secret, _ = self._resolve_api_key(resource)
        return secret

    def _resolve_api_key(self, resource: str | ApiResourceSpec) -> tuple[str | None, str | None]:
        if isinstance(resource, str):
            spec = self.get_current(resource)
            if spec is None:
                raise ApiResourceNotFoundError(f"current API resource not found: {resource}")
        else:
            spec = resource
        if spec.auth.mode is AuthMode.NONE:
            return None, None
        reference = self._credential_reference(spec)
        vault_error: SecretVaultUnavailableError | None = None
        try:
            secret = self.vault.get_secret(reference)
        except SecretVaultUnavailableError as error:
            secret = None
            vault_error = error
        if secret is not None:
            return secret, "vault"
        for env_key in spec.auth.env_keys:
            value = self.environ.get(env_key)
            if value:
                return value, "environment"
        if vault_error is not None:
            raise vault_error
        return None, None

    def _credential_reference(self, spec: ApiResourceSpec) -> str:
        return spec.auth.credential_reference or f"resource:{spec.resource_id}"

    def _insert(self, connection: sqlite3.Connection, spec: ApiResourceSpec) -> None:
        connection.execute(
            """
            INSERT INTO api_resource_revisions (
                resource_id, revision, enabled, spec_json, created_at, deleted_at
            ) VALUES (?, ?, 1, ?, ?, NULL)
            """,
            (spec.resource_id, spec.revision, spec.to_json(), _utc_now().isoformat()),
        )

    def _revision_from_row(self, row: sqlite3.Row) -> StoredResourceRevision:
        return StoredResourceRevision(
            spec=ApiResourceSpec.from_json(row["spec_json"]),
            enabled=bool(row["enabled"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            deleted_at=(datetime.fromisoformat(row["deleted_at"]) if row["deleted_at"] else None),
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection


def _utc_now() -> datetime:
    return datetime.now(UTC)


_TONES = (
    "neutral",
    "calm",
    "warm",
    "cheerful",
    "excited",
    "serious",
    "empathetic",
    "somber",
    "angry",
    "fearful",
    "mysterious",
    "authoritative",
)
_PACES = ("very_slow", "slow", "normal", "fast", "very_fast")
_STYLES = (
    "natural",
    "audiobook",
    "conversational",
    "documentary",
    "storyteller",
    "newscaster",
    "podcast",
    "dramatic",
    "meditation",
    "instructional",
)
_NONVERBAL_FREQUENCIES = ("never", "rare", "occasional", "frequent", "very_frequent")


def builtin_resource_specs() -> tuple[ApiResourceSpec, ...]:
    """Return fresh immutable catalog records for SPLICR's three native adapters."""

    common_variables = (
        ApiVariableDefinition("text", required=True, label="Text"),
        ApiVariableDefinition("model", required=True, label="Model"),
        ApiVariableDefinition("voice", required=True, label="Voice"),
    )
    gemini_voices = tuple(
        TtsVoiceSpec(voice)
        for voice in (
            "Achernar",
            "Achird",
            "Aoede",
            "Charon",
            "Fenrir",
            "Kore",
            "Puck",
            "Zephyr",
        )
    )
    expressive_capabilities = TtsCapabilities(
        tone_presets=_TONES,
        speech_paces=_PACES,
        vocal_styles=_STYLES,
        nonverbal_frequencies=_NONVERBAL_FREQUENCIES,
        tone_modes=(CapabilityMode.PROMPT,),
        pace_modes=(CapabilityMode.PROMPT, CapabilityMode.INLINE_MARKUP),
        vocal_style_modes=(CapabilityMode.PROMPT, CapabilityMode.INLINE_MARKUP),
        nonverbal_modes=(CapabilityMode.INLINE_MARKUP, CapabilityMode.CLIENT_TRANSFORM),
        nonverbal_cues=("sighs", "giggles", "laughs", "gasp"),
        supports_custom_instructions=True,
    )
    gemini = ApiResourceSpec(
        resource_id="gemini",
        revision=1,
        name="Gemini",
        description="Google Gemini text-to-speech through SPLICR's native adapter.",
        adapter_type=AdapterType.GEMINI,
        method=HttpMethod.POST,
        base_url="https://generativelanguage.googleapis.com/v1beta/interactions",
        auth=ApiAuthSpec(
            mode=AuthMode.HEADER,
            name="X-Goog-Api-Key",
            env_keys=("GOOGLE_API_KEY", "GEMINI_API_KEY"),
        ),
        headers={"Content-Type": "application/json"},
        request_template={"text": "${text}"},
        variables=common_variables,
        response=ApiResponseSpec(ResponseMode.RAW_PCM),
        defaults=TtsDefaults(
            default_model="gemini-3.1-flash-tts-preview",
            default_voice="Kore",
            models=("gemini-3.1-flash-tts-preview",),
            voices=gemini_voices,
        ),
        input_limits=InputLimits(max_tokens=8_192, recommended_bytes=3_800, recommended_words=350),
        pacing=PacingPolicy(minimum_interval_seconds=3.0),
        capabilities=expressive_capabilities,
    )
    deepgram = ApiResourceSpec(
        resource_id="deepgram",
        revision=1,
        name="Deepgram",
        description="Deepgram Aura text-to-speech through SPLICR's native adapter.",
        adapter_type=AdapterType.DEEPGRAM,
        method=HttpMethod.POST,
        base_url="https://api.deepgram.com/v1/speak",
        auth=ApiAuthSpec(
            mode=AuthMode.HEADER,
            name="Authorization",
            prefix="Token ",
            env_keys=("DEEPGRAM_API_KEY",),
        ),
        headers={"Content-Type": "application/json"},
        query={
            "model": "${voice}",
            "encoding": "linear16",
            "container": "none",
            "sample_rate": 24_000,
        },
        request_template={"text": "${text}"},
        variables=common_variables,
        response=ApiResponseSpec(ResponseMode.RAW_PCM),
        defaults=TtsDefaults(
            default_model="aura-2",
            default_voice="aura-2-thalia-en",
            models=("aura-2", "aura-1"),
            voices=(
                TtsVoiceSpec("aura-2-thalia-en", traits=("English",)),
                TtsVoiceSpec("aura-2-orpheus-en", traits=("English",)),
            ),
        ),
        input_limits=InputLimits(max_characters=2_000, recommended_characters=1_900),
        capabilities=TtsCapabilities(
            speech_paces=_PACES,
            pace_modes=(CapabilityMode.NATIVE_SCALAR,),
            supports_custom_instructions=False,
        ),
    )
    inworld = ApiResourceSpec(
        resource_id="inworld",
        revision=1,
        name="Inworld",
        description="Inworld text-to-speech through SPLICR's native adapter.",
        adapter_type=AdapterType.INWORLD,
        method=HttpMethod.POST,
        base_url="https://api.inworld.ai/tts/v1/voice",
        auth=ApiAuthSpec(
            mode=AuthMode.HEADER,
            name="Authorization",
            prefix="Basic ",
            env_keys=("INWORLD_API_KEY",),
        ),
        headers={"Content-Type": "application/json"},
        request_template={
            "text": "${text}",
            "voiceId": "${voice}",
            "modelId": "${model}",
            "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": 24_000},
            "deliveryMode": "BALANCED",
            "applyTextNormalization": "ON",
        },
        variables=common_variables,
        response=ApiResponseSpec(ResponseMode.JSON_BASE64_WAV, json_pointer="/audioContent"),
        defaults=TtsDefaults(
            default_model="inworld-tts-2",
            default_voice="Ashley",
            models=("inworld-tts-2", "inworld-tts-1.5-max", "inworld-tts-1.5-mini"),
            voices=(TtsVoiceSpec("Ashley"), TtsVoiceSpec("Dennis")),
        ),
        input_limits=InputLimits(max_characters=2_000, recommended_characters=1_900),
        capabilities=TtsCapabilities(
            tone_presets=_TONES,
            speech_paces=_PACES,
            vocal_styles=_STYLES,
            nonverbal_frequencies=_NONVERBAL_FREQUENCIES,
            tone_modes=(CapabilityMode.PROMPT,),
            pace_modes=(CapabilityMode.NATIVE_SCALAR,),
            vocal_style_modes=(CapabilityMode.PROMPT,),
            nonverbal_modes=(
                CapabilityMode.INLINE_MARKUP,
                CapabilityMode.CLIENT_TRANSFORM,
            ),
            nonverbal_cues=("laugh", "breathe", "clear_throat", "sigh", "cough", "yawn"),
            supports_custom_instructions=True,
        ),
    )
    return gemini, deepgram, inworld
