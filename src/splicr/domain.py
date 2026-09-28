from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Mapping, Protocol, TypeAlias


JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
SEGMENT_OPTIONS_VARIABLE = "__splicr_segment_options"


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
