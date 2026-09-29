from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Mapping, Protocol, TypeAlias


JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
SEGMENT_OPTIONS_VARIABLE = "__splicr_segment_options"
INTERNAL_VARIABLE_PREFIX = "__splicr_"
_CONTROL_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ChunkStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class TonePreset(StrEnum):
    NEUTRAL = "neutral"
    CALM = "calm"
    WARM = "warm"
    CHEERFUL = "cheerful"
    EXCITED = "excited"
    SERIOUS = "serious"
    EMPATHETIC = "empathetic"
    SOMBER = "somber"
    ANGRY = "angry"
    FEARFUL = "fearful"
    MYSTERIOUS = "mysterious"
    AUTHORITATIVE = "authoritative"


class SpeechPace(StrEnum):
    VERY_SLOW = "very_slow"
    SLOW = "slow"
    NORMAL = "normal"
    FAST = "fast"
    VERY_FAST = "very_fast"


class VocalStyle(StrEnum):
    NATURAL = "natural"
    AUDIOBOOK = "audiobook"
    CONVERSATIONAL = "conversational"
    DOCUMENTARY = "documentary"
    STORYTELLER = "storyteller"
    NEWSCASTER = "newscaster"
    PODCAST = "podcast"
    DRAMATIC = "dramatic"
    MEDITATION = "meditation"
    INSTRUCTIONAL = "instructional"


class NonverbalFrequency(StrEnum):
    NEVER = "never"
    RARE = "rare"
    OCCASIONAL = "occasional"
    FREQUENT = "frequent"
    VERY_FREQUENT = "very_frequent"


NONVERBAL_CUE_MARKER_PREFIX = "[[SPLICR_AUDIO_CUE:"
NONVERBAL_CUE_MARKER_SUFFIX = "]]"


class ControlMode(StrEnum):
    NATIVE_ENUM = "native_enum"
    NATIVE_SCALAR = "native_scalar"
    PROMPT = "prompt"
    INLINE_MARKUP = "inline_markup"
    CLIENT_TRANSFORM = "client_transform"
    UNSUPPORTED = "unsupported"


class ControlValueType(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    JSON = "json"


def _plain_json(value: JsonValue) -> JsonValue:
    if isinstance(value, Mapping):
        return {key: _plain_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_json(item) for item in value]
    return value


def _json_signature(value: JsonValue) -> str:
    return json.dumps(_plain_json(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _matches_control_type(value: JsonValue, value_type: ControlValueType) -> bool:
    if value_type is ControlValueType.JSON:
        return True
    if value_type is ControlValueType.STRING:
        return isinstance(value, str)
    if value_type is ControlValueType.BOOLEAN:
        return isinstance(value, bool)
    if value_type is ControlValueType.INTEGER:
        return isinstance(value, int) and not isinstance(value, bool)
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


@dataclass(frozen=True, slots=True)
class ControlCondition:
    """Declarative equality condition used for UI visibility/enabling."""

    key: str
    equals: JsonValue

    def __post_init__(self) -> None:
        if not _CONTROL_KEY_RE.fullmatch(self.key):
            raise ValueError(f"invalid control condition key: {self.key!r}")


@dataclass(frozen=True, slots=True)
class ControlDefinition:
    """Provider-neutral metadata and validation for one advanced engine value."""

    key: str
    value_type: ControlValueType = ControlValueType.STRING
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
    visible_when: tuple[ControlCondition, ...] = ()
    enabled_when: tuple[ControlCondition, ...] = ()

    def __post_init__(self) -> None:
        if not _CONTROL_KEY_RE.fullmatch(self.key):
            raise ValueError(f"invalid control key: {self.key!r}")
        object.__setattr__(self, "value_type", ControlValueType(self.value_type))
        if self.label is not None and not self.label.strip():
            raise ValueError("control label cannot be blank")
        if not self.group.strip():
            raise ValueError("control group cannot be blank")
        if len(self.description) > 2_000:
            raise ValueError("control description cannot exceed 2000 characters")
        if any(
            not isinstance(value, bool)
            for value in (self.required, self.sensitive, self.read_only, self.randomizable)
        ):
            raise TypeError("control flags must be booleans")
        if self.default is not None and not _matches_control_type(
            self.default, self.value_type
        ):
            raise ValueError(f"default for {self.key} does not match {self.value_type.value}")
        if any(not _matches_control_type(choice, self.value_type) for choice in self.choices):
            raise ValueError(f"choice for {self.key} does not match {self.value_type.value}")
        signatures = tuple(_json_signature(choice) for choice in self.choices)
        if len(signatures) != len(set(signatures)):
            raise ValueError(f"choices for {self.key} must be unique")
        if self.choices and self.default is not None:
            if _json_signature(self.default) not in signatures:
                raise ValueError(f"default for {self.key} must be one of its choices")
        if self.sensitive and (self.default is not None or self.choices):
            raise ValueError("sensitive controls cannot declare defaults or choices")
        if self.randomizable and self.value_type is not ControlValueType.INTEGER:
            raise ValueError("randomizable controls must be integers")
        numeric_metadata = (self.minimum, self.maximum, self.step)
        if any(value is not None for value in numeric_metadata):
            if self.value_type not in {ControlValueType.INTEGER, ControlValueType.NUMBER}:
                raise ValueError("range metadata is only valid for integer or number controls")
            if any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                for value in numeric_metadata
                if value is not None
            ):
                raise ValueError("control range metadata must contain finite numbers")
            if self.minimum is not None and self.maximum is not None:
                if self.minimum > self.maximum:
                    raise ValueError("control minimum cannot exceed maximum")
            if self.step is not None and self.step <= 0:
                raise ValueError("control step must be positive")
        if self.value_type is ControlValueType.INTEGER and any(
            value is not None and not isinstance(value, int)
            for value in numeric_metadata
        ):
            raise ValueError("integer control range metadata must use integers")
        if self.unit is not None and not self.unit.strip():
            raise ValueError("control unit cannot be blank")
        for condition in (*self.visible_when, *self.enabled_when):
            if not isinstance(condition, ControlCondition):
                raise TypeError("control conditions must be ControlCondition values")
            if condition.key == self.key:
                raise ValueError("a control cannot condition itself")


def validate_control_values(
    definitions: tuple[ControlDefinition, ...],
    values: Mapping[str, JsonValue] | None,
    *,
    allow_unknown: bool = False,
) -> dict[str, JsonValue]:
    """Merge defaults and validate public values before they become durable job state."""

    selected = dict(values or {})
    if any(not isinstance(key, str) for key in selected):
        raise TypeError("control value names must be strings")
    by_key = {definition.key: definition for definition in definitions}
    if len(by_key) != len(definitions):
        raise ValueError("control definition keys must be unique")
    unknown = sorted(
        key
        for key in selected
        if key not in by_key and not key.startswith(INTERNAL_VARIABLE_PREFIX)
    )
    if unknown and not allow_unknown:
        raise ValueError("unknown advanced control values: " + ", ".join(unknown))

    normalized: dict[str, JsonValue] = {
        definition.key: _plain_json(definition.default)
        for definition in definitions
        if definition.default is not None
    }
    normalized.update(selected)
    for definition in definitions:
        if definition.required and (
            definition.key not in normalized or normalized[definition.key] is None
        ):
            raise ValueError(f"advanced control {definition.key!r} is required")
        if definition.key not in normalized:
            continue
        if definition.sensitive:
            raise ValueError(
                f"advanced control {definition.key!r} is sensitive and must use secret storage"
            )
        value = normalized[definition.key]
        if value is None and not definition.required:
            normalized.pop(definition.key)
            continue
        if not _matches_control_type(value, definition.value_type):
            raise ValueError(
                f"advanced control {definition.key!r} must be {definition.value_type.value}"
            )
        if definition.choices:
            signatures = {_json_signature(choice) for choice in definition.choices}
            if _json_signature(value) not in signatures:
                raise ValueError(
                    f"advanced control {definition.key!r} must be one of its declared choices"
                )
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if definition.minimum is not None and value < definition.minimum:
                raise ValueError(
                    f"advanced control {definition.key!r} must be at least {definition.minimum}"
                )
            if definition.maximum is not None and value > definition.maximum:
                raise ValueError(
                    f"advanced control {definition.key!r} must be at most {definition.maximum}"
                )
    return normalized


@dataclass(frozen=True, slots=True)
class AudioFormat:
    sample_rate: int = 24_000
    channels: int = 1
    sample_width: int = 2
    encoding: str = "pcm_s16le"

    @property
    def frame_width(self) -> int:
        return self.channels * self.sample_width


CANONICAL_AUDIO_FORMAT = AudioFormat()


@dataclass(frozen=True, slots=True)
class VoiceOption:
    id: str
    traits: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    models: tuple[str, ...] = ()
    voices: tuple[VoiceOption, ...] = ()
    tone_presets: tuple[TonePreset, ...] = ()
    speech_paces: tuple[SpeechPace, ...] = ()
    vocal_styles: tuple[VocalStyle, ...] = ()
    nonverbal_frequencies: tuple[NonverbalFrequency, ...] = ()
    tone_modes: tuple[ControlMode, ...] = ()
    pace_modes: tuple[ControlMode, ...] = ()
    vocal_style_modes: tuple[ControlMode, ...] = ()
    nonverbal_modes: tuple[ControlMode, ...] = ()
    nonverbal_cues: tuple[str, ...] = ()
    supports_custom_instructions: bool = True
    control_definitions: tuple[ControlDefinition, ...] = ()
    allows_undeclared_variables: bool = False


@dataclass(frozen=True, slots=True)
class DeliveryControls:
    tone: TonePreset = TonePreset.NEUTRAL
    pace: SpeechPace = SpeechPace.NORMAL
    vocal_style: VocalStyle = VocalStyle.NATURAL
    nonverbal_frequency: NonverbalFrequency = NonverbalFrequency.NEVER


@dataclass(frozen=True, slots=True)
class SynthesisOptions:
    model: str
    voice: str
    instructions: str | None = None
    controls: DeliveryControls = field(default_factory=DeliveryControls)
    variables: Mapping[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SynthesisSegment:
    """One exact source-ordered unit with its own reproducible voice settings."""

    text: str
    model: str | None = None
    voice: str | None = None
    instructions: str | None = None
    controls: DeliveryControls = field(default_factory=DeliveryControls)
    variables: Mapping[str, JsonValue] = field(default_factory=dict)
    speaker: str | None = None

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("segment text must not be blank")


@dataclass(frozen=True, slots=True)
class AudioChunk:
    pcm: bytes
    format: AudioFormat = CANONICAL_AUDIO_FORMAT


@dataclass(frozen=True, slots=True)
class ProviderInfo:
    name: str
    default_model: str
    default_voice: str
    max_input_bytes: int | None
    max_input_tokens: int | None
    max_input_characters: int | None = None
    recommended_chunk_bytes: int | None = None
    recommended_chunk_words: int | None = None
    recommended_chunk_characters: int | None = None
    minimum_request_interval_seconds: float | None = None
    canonical_audio: AudioFormat = CANONICAL_AUDIO_FORMAT
    capabilities: ProviderCapabilities = field(default_factory=ProviderCapabilities)


@dataclass(frozen=True, slots=True)
class ProviderDiagnostic:
    """Sanitizable provider-boundary context attached to a failed request."""

    category: str | None = None
    phase: str | None = None
    provider: str | None = None
    method: str | None = None
    endpoint: str | None = None
    request: Mapping[str, JsonValue] | None = None
    response: Mapping[str, JsonValue] | None = None
    exception: Mapping[str, JsonValue] | None = None
    metadata: Mapping[str, JsonValue] | None = None


class ProviderError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        retryable: bool,
        status_code: int | None = None,
        retry_after: float | None = None,
        diagnostic: ProviderDiagnostic | None = None,
        origin: str = "provider",
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code
        self.retry_after = retry_after
        self.diagnostic = diagnostic
        self.origin = origin


@dataclass(frozen=True, slots=True)
class JobErrorDetail:
    code: str
    message: str
    retryable: bool
    status_code: int | None = None
    chunk_index: int | None = None
    event_id: str | None = None
    occurred_at: str = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class ErrorEventDraft:
    fingerprint: str
    source: str
    code: str
    message: str
    severity: str = "error"
    category: str | None = None
    retryable: bool = False
    status_code: int | None = None
    method: str | None = None
    endpoint: str | None = None
    request: Mapping[str, JsonValue] | None = None
    response: Mapping[str, JsonValue] | None = None
    exception: Mapping[str, JsonValue] | None = None
    context: Mapping[str, JsonValue] | None = None
    provider: str | None = None
    resource_revision: int | None = None
    job_id: str | None = None
    chunk_index: int | None = None
    attempt: int | None = None
    occurred_at: str = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class ErrorEventRecord:
    id: str
    sequence: int
    fingerprint: str
    source: str
    severity: str
    code: str
    category: str | None
    message: str
    retryable: bool
    status_code: int | None
    method: str | None
    endpoint: str | None
    request: Mapping[str, JsonValue] | None
    response: Mapping[str, JsonValue] | None
    exception: Mapping[str, JsonValue] | None
    context: Mapping[str, JsonValue] | None
    provider: str | None
    resource_revision: int | None
    job_id: str | None
    chunk_index: int | None
    attempt: int | None
    count: int
    first_occurred_at: str
    last_occurred_at: str
    read_at: str | None


class TtsProvider(Protocol):
    @property
    def info(self) -> ProviderInfo: ...

    def estimate_input_tokens(self, text: str, options: SynthesisOptions) -> int: ...

    def estimate_input_characters(self, text: str, options: SynthesisOptions) -> int: ...

    async def synthesize(self, text: str, options: SynthesisOptions) -> AudioChunk: ...


@dataclass(frozen=True, slots=True)
class JobRecord:
    id: str
    status: JobStatus
    provider: str
    model: str
    voice: str
    instructions: str | None
    controls: DeliveryControls
    total_chunks: int
    completed_chunks: int
    error: str | None
    error_detail: JobErrorDetail | None
    output_path: str | None
    created_at: str
    updated_at: str
    resource_revision: int | None = None
    variables: Mapping[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ChunkRecord:
    job_id: str
    index: int
    text: str
    byte_count: int
    word_count: int
    status: ChunkStatus
    attempts: int
    pcm_path: str | None
    error: str | None


class UnknownProviderError(ValueError):
    pass


class JobNotFoundError(LookupError):
    pass


class InvalidJobStateError(RuntimeError):
    pass
