from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import mimetypes
import os
import re
import shutil
import wave
from collections.abc import Mapping
from contextlib import asynccontextmanager
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .api_resources import (
    API_KEY_UNCHANGED,
    AdapterType,
    ApiAuthSpec,
    ApiResourceConflictError,
    ApiResourceNotFoundError,
    ApiResourceSpec,
    ApiResponseSpec,
    ApiVariableDefinition,
    AuthMode,
    CapabilityMode,
    HttpMethod,
    InputLimits,
    LimitBasis,
    PacingPolicy,
    ResponseMode,
    RetryPolicy,
    SqliteApiResourceStore,
    TtsCapabilities,
    TtsDefaults,
    TtsVoiceSpec,
    VariableType,
)
from .auth import AuthManager, AuthMiddleware, register_auth
from .bootstrap import create_service
from .chat_resources import (
    ChatResourceConflictError,
    ChatResourceNotFoundError,
    ChatResourceSpec,
    SqliteChatResourceStore,
    StoredChatResource,
)
from .config import Settings
from .diagnostics import sanitize_diagnostic, sanitize_url
from .dialogue_jobs import (
    DialogueScriptJob,
    DialogueScriptJobNotFoundError,
    DialogueScriptJobRequest,
    DialogueScriptJobService,
    InvalidDialogueScriptJobStateError,
    SqliteDialogueScriptJobStore,
)
from .domain import (
    BATCH_ITEM_VARIABLE,
    SEGMENT_OPTIONS_VARIABLE,
    ChunkStatus,
    ControlValueType,
    ControlMode,
    DeliveryControls,
    ErrorEventDraft,
    ErrorEventRecord,
    InvalidJobStateError,
    JobNotFoundError,
    JobRecord,
    JobStatus,
    JsonValue,
    NonverbalFrequency,
    ProviderError,
    ProviderInfo,
    SpeechPace,
    SynthesisSegment,
    TonePreset,
    UnknownProviderError,
    VocalStyle,
    validate_control_values,
    utc_now,
)
from .document_import import DocumentImportError, import_document
from .errors import JobErrorCode, suggestion_for
from .planning import ChunkPlan, ChunkTargetMode, PlannedChunk, SplitStrategy
from .pronunciation import KokoroToolClient, KokoroToolError, PronunciationEntry
from .profiles import ProfileNotFoundError, StudioProfile, StudioProfileStore
from .service import SynthesisService
from .secret_vault import SecretVaultUnavailableError
from .studio import (
    Artifact,
    ArtifactKind,
    Project,
    SqliteStudioStore,
    VoiceProfile,
    VoiceProfileKind,
    import_splicr_job,
)
from .studio.audiogram import (
    AudiogramBackgroundAsset,
    AudiogramBackgroundError,
    AudiogramBackgroundFit,
    AudiogramBackgroundMode,
    AudiogramJob,
    AudiogramJobKind,
    AudiogramJobNotFoundError,
    AudiogramJobService,
    AudiogramJobStatus,
    AudiogramJobStore,
    AudiogramOutputFormat,
    AudiogramRenderError,
    AudiogramSource,
    AudiogramSpec,
    FfmpegAudiogramRenderer,
    InvalidAudiogramJobStateError,
    audiogram_media_type,
    audiogram_output_extension,
    estimate_render_seconds,
    resolve_layout,
)
from .studio.batch import (
    BatchItem,
    BatchItemDraft,
    BatchItemSpec,
    BatchItemStatus,
    BatchQueue,
    BatchQueueNotFoundError,
    BatchQueueService,
    BatchQueueStatus,
    BatchQueueStore,
    InvalidBatchStateError,
)
from .studio.chat import ChatCompletionError, OpenAiChatCompleter
from .studio.components import (
    ComponentConfigurationError,
    ComponentConfigurationLockedError,
    ComponentManager,
)
from .studio.conversion import (
    AudioOutputFormat,
    ConversionError,
    ConversionInput,
    ConversionInputNotFoundError,
    ConversionJob,
    ConversionJobNotFoundError,
    ConversionJobService,
    ConversionJobStatus,
    ConversionJobStore,
    ConversionSpec,
    FfmpegAudioConverter,
    InvalidConversionJobStateError,
    SplitMode,
    media_type_for,
)
from .studio.dialogue import (
    DialogueGenerationError,
    DialogueGenerationOptions,
    DialogueScript as GeneratedDialogueScript,
    DialogueTurn as GeneratedDialogueTurn,
    generate_script,
    refine_selection,
)
from .studio.finishing import (
    FfmpegFinishingRenderer,
    FinishingAsset,
    FinishingAssetNotFoundError,
    FinishingError,
    FinishingJob,
    FinishingJobNotFoundError,
    FinishingJobService,
    FinishingJobStatus,
    FinishingSpec,
    FinishingStore,
    InvalidFinishingJobStateError,
)
from .studio.publishing import (
    ChapterCue,
    PodcastChannel,
    PublishedEpisode,
    PublishingService,
    PublishingStore,
)
from .studio.subtitles import (
    SubtitleCue,
    SubtitleExport,
    SubtitleFormat,
    SubtitleService,
    SubtitleTimeline,
)
from .studio.transcription import (
    FasterWhisperProvider,
    InvalidTranscriptionJobStateError,
    TranscriptionJob,
    TranscriptionJobNotFoundError,
    TranscriptionJobService,
    TranscriptionJobStatus,
    TranscriptionJobStore,
    TranscriptionOptions,
    TranscriptionProviderError,
)
from .studio.voice_design import (
    InvalidVoiceDesignJobStateError,
    SubprocessQwenVoiceDesignRunner,
    VoiceDesignJob,
    VoiceDesignJobNotFoundError,
    VoiceDesignJobService,
    VoiceDesignJobStatus,
    VoiceDesignJobStore,
    VoiceDesignUnavailableError,
)
from .studio.timeline import (
    JobTimeline,
    TimelineSegment,
    TimelineSentenceSpan,
    build_job_timeline,
    wav_span_bytes,
)
from .studio.voice_resolution import (
    VOICE_PROFILE_VARIABLE,
    model_for_voice_profile,
    resolve_voice_profile,
)
from .ui import register_ui


logger = logging.getLogger(__name__)


def _plain_control_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain_control_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_control_value(item) for item in value]
    return value


def _suggest_project_name(text: str, source_name: str | None) -> str:
    if source_name:
        candidate = Path(source_name).stem.strip()
        if candidate:
            return candidate[:240]
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    first_line = re.sub(r"^#{1,6}[ \t]+", "", first_line).strip()
    if not first_line:
        return "Untitled narration"
    return first_line[:237] + "..." if len(first_line) > 240 else first_line


class DeliveryControlsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tone: TonePreset = TonePreset.NEUTRAL
    pace: SpeechPace = SpeechPace.NORMAL
    vocal_style: VocalStyle = VocalStyle.NATURAL
    nonverbal_frequency: NonverbalFrequency = NonverbalFrequency.NEVER

    def to_domain(self) -> DeliveryControls:
        return DeliveryControls(
            tone=self.tone,
            pace=self.pace,
            vocal_style=self.vocal_style,
            nonverbal_frequency=self.nonverbal_frequency,
        )

    @classmethod
    def from_domain(cls, controls: DeliveryControls) -> "DeliveryControlsPayload":
        return cls(
            tone=controls.tone,
            pace=controls.pace,
            vocal_style=controls.vocal_style,
            nonverbal_frequency=controls.nonverbal_frequency,
        )


class CreateJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, description="UTF-8 text to synthesize")
    provider: str | None = Field(default=None, min_length=1, max_length=64)
    resource_id: str | None = Field(default=None, min_length=1, max_length=64)
    resource_revision: int | None = Field(default=None, ge=1)
    model: str | None = Field(default=None, min_length=1, max_length=200)
    voice: str | None = Field(default=None, min_length=1, max_length=100)
    voice_profile_id: str | None = Field(default=None, min_length=1, max_length=64)
    instructions: str | None = Field(
        default=None,
        max_length=2_000,
        description="Optional provider-neutral delivery/style direction",
    )
    controls: DeliveryControlsPayload = Field(default_factory=DeliveryControlsPayload)
    variables: dict[str, Any] = Field(default_factory=dict)
    split_strategy: SplitStrategy = SplitStrategy.SEMANTIC
    chunk_target_mode: ChunkTargetMode = ChunkTargetMode.AUTOMATIC
    chunk_target_value: int | None = Field(default=None, ge=1, le=10_000_000)
    remove_numeric_citations: bool = Field(
        default=False,
        description=(
            r"Remove standalone numeric citations such as [123] or \[123\] before chunking"
        ),
    )
    project_name: str | None = Field(default=None, min_length=1, max_length=240)
    source_name: str | None = Field(default=None, min_length=1, max_length=500)
    export_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=240,
        description="Friendly filename stem; the immutable job ID remains unchanged",
    )

    @field_validator("text")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must contain a non-whitespace character")
        return value

    @model_validator(mode="after")
    def resource_identity_must_agree(self) -> "CreateJobRequest":
        if self.provider and self.resource_id and self.provider != self.resource_id:
            raise ValueError("provider and resource_id must identify the same API resource")
        if self.chunk_target_mode is ChunkTargetMode.AUTOMATIC:
            if self.chunk_target_value is not None:
                raise ValueError("automatic chunk targeting does not accept a target value")
        elif self.chunk_target_value is None:
            raise ValueError(
                f"{self.chunk_target_mode.value} chunk targeting requires a target value"
            )
        elif self.chunk_target_mode is ChunkTargetMode.PARTS and self.chunk_target_value > 10_000:
            raise ValueError("parts chunk targeting accepts at most 10000 requested parts")
        return self

    @property
    def selected_resource_id(self) -> str:
        return self.resource_id or self.provider or "gemini"


class DialogueTurnPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    speaker: Literal["Person1", "Person2"]
    text: str = Field(min_length=1, max_length=100_000)

    @field_validator("text")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("dialogue turn text must not be blank")
        return value


class DialogueSpeakerPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str | None = Field(default=None, min_length=1, max_length=200)
    voice: str | None = Field(default=None, min_length=1, max_length=100)
    voice_profile_id: str | None = Field(default=None, min_length=1, max_length=64)
    instructions: str | None = Field(default=None, max_length=2_000)
    controls: DeliveryControlsPayload = Field(default_factory=DeliveryControlsPayload)
    variables: dict[str, Any] = Field(default_factory=dict)


class DialogueRenderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str | None = Field(default=None, min_length=1, max_length=64)
    resource_id: str | None = Field(default=None, min_length=1, max_length=64)
    resource_revision: int | None = Field(default=None, ge=1)
    turns: list[DialogueTurnPayload] = Field(min_length=1, max_length=2_000)
    person1: DialogueSpeakerPayload
    person2: DialogueSpeakerPayload
    source_text: str | None = None
    split_strategy: SplitStrategy = SplitStrategy.SEMANTIC
    remove_numeric_citations: bool = False
    project_name: str | None = Field(default=None, min_length=1, max_length=240)
    source_name: str | None = Field(default=None, min_length=1, max_length=500)
    export_name: str | None = Field(default=None, min_length=1, max_length=240)

    @model_validator(mode="after")
    def resource_identity_must_agree(self) -> "DialogueRenderRequest":
        if self.provider and self.resource_id and self.provider != self.resource_id:
            raise ValueError("provider and resource_id must identify the same API resource")
        if self.source_text is not None and not self.source_text.strip():
            raise ValueError("source_text must not be blank when supplied")
        return self

    @property
    def selected_resource_id(self) -> str:
        return self.resource_id or self.provider or "gemini"

    def speaker_settings(self, speaker: Literal["Person1", "Person2"]) -> DialogueSpeakerPayload:
        return self.person1 if speaker == "Person1" else self.person2

    def transcript_text(self) -> str:
        return "\n\n".join(f"{turn.speaker}: {turn.text.strip()}" for turn in self.turns)


class AudioFormatResponse(BaseModel):
    encoding: str
    sample_rate: int
    channels: int
    sample_width: int


class VoiceOptionResponse(BaseModel):
    id: str
    traits: list[str]


class ControlConditionResponse(BaseModel):
    key: str
    equals: Any


class ControlDefinitionResponse(BaseModel):
    key: str
    value_type: ControlValueType
    label: str | None
    description: str
    group: str
    required: bool
    default: Any
    choices: list[Any]
    minimum: int | float | None
    maximum: int | float | None
    step: int | float | None
    unit: str | None
    sensitive: bool
    read_only: bool
    randomizable: bool
    visible_when: list[ControlConditionResponse]
    enabled_when: list[ControlConditionResponse]


class VoiceProfileResponse(BaseModel):
    id: str
    label: str
    engine_id: str
    kind: VoiceProfileKind
    description: str
    reference_text: str | None
    settings: dict[str, Any]
    metadata: dict[str, Any]
    has_reference: bool
    reference_url: str | None
    created_at: str
    updated_at: str

    @classmethod
    def from_domain(cls, profile: VoiceProfile) -> "VoiceProfileResponse":
        reference = Path(profile.reference_audio_path) if profile.reference_audio_path else None
        return cls(
            id=profile.id,
            label=profile.label,
            engine_id=profile.engine_id,
            kind=profile.kind,
            description=profile.description,
            reference_text=profile.reference_text,
            settings=dict(profile.settings),
            metadata=dict(profile.metadata),
            has_reference=bool(reference and reference.is_file()),
            reference_url=(
                f"/v1/studio/voices/{profile.id}/reference" if reference else None
            ),
            created_at=profile.created_at,
            updated_at=profile.updated_at,
        )


class VoiceProfileUpdatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2_000)


class VoiceDesignCreatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2_000)
    take: int = Field(default=1, ge=1, le=99)

    @field_validator("label", "description")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("value cannot be blank")
        return normalized


class VoiceDesignJobResponse(BaseModel):
    id: str
    label: str
    description: str
    take: int
    status: VoiceDesignJobStatus
    progress: float
    profile_id: str | None
    reference_text: str
    error_code: str | None
    error_detail: str | None
    created_at: str
    updated_at: str
    profile: VoiceProfileResponse | None = None


class VoicePresetPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=200)
    engine_id: str = Field(min_length=1, max_length=100)
    voice_id: str = Field(min_length=1, max_length=200)
    instructions: str = Field(default="", max_length=2_000)
    description: str = Field(default="", max_length=2_000)


class ProviderCapabilitiesResponse(BaseModel):
    models: list[str]
    voices: list[VoiceOptionResponse]
    tone_presets: list[TonePreset]
    speech_paces: list[SpeechPace]
    vocal_styles: list[VocalStyle]
    nonverbal_frequencies: list[NonverbalFrequency]
    tone_modes: list[ControlMode]
    pace_modes: list[ControlMode]
    vocal_style_modes: list[ControlMode]
    nonverbal_modes: list[ControlMode]
    nonverbal_cues: list[str]
    supports_custom_instructions: bool
    control_definitions: list[ControlDefinitionResponse]
    allows_undeclared_variables: bool


class ProviderResponse(BaseModel):
    name: str
    default_model: str
    default_voice: str
    max_input_bytes: int | None
    max_input_tokens: int | None
    max_input_characters: int | None
    recommended_chunk_bytes: int | None
    recommended_chunk_words: int | None
    recommended_chunk_characters: int | None
    minimum_request_interval_seconds: float | None
    canonical_audio: AudioFormatResponse
    capabilities: ProviderCapabilitiesResponse

    @classmethod
    def from_info(cls, info: ProviderInfo) -> "ProviderResponse":
        capabilities = info.capabilities
        models = list(capabilities.models)
        if info.default_model not in models:
            models.insert(0, info.default_model)
        voices = [
            VoiceOptionResponse(id=voice.id, traits=list(voice.traits))
            for voice in capabilities.voices
        ]
        if all(voice.id != info.default_voice for voice in voices):
            voices.insert(0, VoiceOptionResponse(id=info.default_voice, traits=[]))
        return cls(
            name=info.name,
            default_model=info.default_model,
            default_voice=info.default_voice,
            max_input_bytes=info.max_input_bytes,
            max_input_tokens=info.max_input_tokens,
            max_input_characters=info.max_input_characters,
            recommended_chunk_bytes=info.recommended_chunk_bytes,
            recommended_chunk_words=info.recommended_chunk_words,
            recommended_chunk_characters=info.recommended_chunk_characters,
            minimum_request_interval_seconds=info.minimum_request_interval_seconds,
            canonical_audio=AudioFormatResponse(
                encoding=info.canonical_audio.encoding,
                sample_rate=info.canonical_audio.sample_rate,
                channels=info.canonical_audio.channels,
                sample_width=info.canonical_audio.sample_width,
            ),
            capabilities=ProviderCapabilitiesResponse(
                models=models,
                voices=voices,
                tone_presets=list(capabilities.tone_presets or (TonePreset.NEUTRAL,)),
                speech_paces=list(capabilities.speech_paces or (SpeechPace.NORMAL,)),
                vocal_styles=list(capabilities.vocal_styles or (VocalStyle.NATURAL,)),
                nonverbal_frequencies=list(
                    capabilities.nonverbal_frequencies or (NonverbalFrequency.NEVER,)
                ),
                tone_modes=list(capabilities.tone_modes or (ControlMode.UNSUPPORTED,)),
                pace_modes=list(capabilities.pace_modes or (ControlMode.UNSUPPORTED,)),
                vocal_style_modes=list(
                    capabilities.vocal_style_modes or (ControlMode.UNSUPPORTED,)
                ),
                nonverbal_modes=list(capabilities.nonverbal_modes or (ControlMode.UNSUPPORTED,)),
                nonverbal_cues=list(capabilities.nonverbal_cues),
                supports_custom_instructions=capabilities.supports_custom_instructions,
                control_definitions=[
                    ControlDefinitionResponse(
                        key=definition.key,
                        value_type=definition.value_type,
                        label=definition.label,
                        description=definition.description,
                        group=definition.group,
                        required=definition.required,
                        default=_plain_control_value(definition.default),
                        choices=[_plain_control_value(choice) for choice in definition.choices],
                        minimum=definition.minimum,
                        maximum=definition.maximum,
                        step=definition.step,
                        unit=definition.unit,
                        sensitive=definition.sensitive,
                        read_only=definition.read_only,
                        randomizable=definition.randomizable,
                        visible_when=[
                            ControlConditionResponse(
                                key=item.key,
                                equals=_plain_control_value(item.equals),
                            )
                            for item in definition.visible_when
                        ],
                        enabled_when=[
                            ControlConditionResponse(
                                key=item.key,
                                equals=_plain_control_value(item.equals),
                            )
                            for item in definition.enabled_when
                        ],
                    )
                    for definition in capabilities.control_definitions
                ],
                allows_undeclared_variables=capabilities.allows_undeclared_variables,
            ),
        )


class ApiResourcePayload(BaseModel):
    """Browser-friendly resource editor payload.

    The catalog itself remains nested and versioned. This flat shape keeps the modal practical,
    while the optional advanced fields allow clients to configure every persisted endpoint value.
    Secrets are write-only.
    """

    model_config = ConfigDict(extra="forbid")

    id: str | None = Field(default=None, min_length=1, max_length=64)
    resource_id: str | None = Field(default=None, min_length=1, max_length=64)
    revision: int | None = Field(default=None, ge=1)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=10_000)
    adapter: str | None = None
    adapter_type: str | None = None
    method: str | None = None
    base_url: str | None = Field(default=None, max_length=2_048)
    allow_insecure_http: bool | None = None

    auth_placement: str | None = None
    auth_name: str | None = Field(default=None, max_length=255)
    auth_prefix: str | None = Field(default=None, max_length=100)
    auth_env_keys: list[str] | None = None
    api_key: str | None = Field(default=None, max_length=10_000)
    clear_api_key: bool = False

    headers: dict[str, Any] | None = None
    query: dict[str, Any] | None = None
    request_template: dict[str, Any] | None = None
    default_variables: dict[str, Any] | None = None
    variable_definitions: list[dict[str, Any]] | None = None

    default_model: str | None = Field(default=None, max_length=255)
    default_voice: str | None = Field(default=None, max_length=255)
    models: list[str] | None = None
    voices: list[str | dict[str, Any]] | None = None

    max_input_bytes: int | None = Field(default=None, ge=1)
    max_input_tokens: int | None = Field(default=None, ge=1)
    max_input_characters: int | None = Field(default=None, ge=1)
    max_input_words: int | None = Field(default=None, ge=1)
    recommended_chunk_bytes: int | None = Field(default=None, ge=1)
    recommended_chunk_words: int | None = Field(default=None, ge=1)
    recommended_chunk_characters: int | None = Field(default=None, ge=1)
    limit_basis: str | None = None

    request_timeout_seconds: float | None = Field(default=None, gt=0)
    retry_max_attempts: int | None = Field(default=None, ge=1)
    retry_backoff_initial_seconds: float | None = Field(default=None, ge=0)
    retry_backoff_max_seconds: float | None = Field(default=None, ge=0)
    retry_jitter_seconds: float | None = Field(default=None, ge=0)
    retry_status_codes: list[int] | None = None
    honor_retry_after: bool | None = None

    minimum_request_interval_seconds: float | None = Field(default=None, ge=0)
    requests_per_minute: int | None = Field(default=None, ge=1)
    max_concurrency: int | None = Field(default=None, ge=1)

    response_mode: str | None = None
    audio_json_pointer: str | None = Field(default=None, max_length=2_048)
    response_sample_rate_hz: int | None = Field(default=None, ge=1)
    response_channels: int | None = Field(default=None, ge=1)
    response_sample_width_bytes: int | None = Field(default=None, ge=1, le=4)
    capabilities: dict[str, Any] | None = None

    @model_validator(mode="after")
    def aliases_and_secret_action_must_agree(self) -> "ApiResourcePayload":
        if self.id and self.resource_id and self.id != self.resource_id:
            raise ValueError("id and resource_id must match")
        if self.adapter and self.adapter_type and self.adapter != self.adapter_type:
            raise ValueError("adapter and adapter_type must match")
        if self.clear_api_key and self.api_key:
            raise ValueError("api_key and clear_api_key cannot be used together")
        return self

    @property
    def selected_id(self) -> str | None:
        return self.resource_id or self.id

    @property
    def selected_adapter(self) -> str | None:
        return self.adapter_type or self.adapter


class ChatResourcePayload(BaseModel):
    """Editable OpenAI-compatible chat endpoint; credentials are write-only."""

    model_config = ConfigDict(extra="forbid")

    resource_id: str = Field(min_length=1, max_length=64)
    revision: int | None = Field(default=None, ge=1)
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=10_000)
    base_url: str = Field(min_length=1, max_length=2_048)
    default_model: str = Field(min_length=1, max_length=255)
    models: list[str] = Field(default_factory=list, max_length=1_000)
    local: bool = False
    allow_insecure_http: bool = False
    headers: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: float = Field(default=180.0, gt=0, le=900)
    api_key_envs: list[str] = Field(default_factory=list, max_length=100)
    api_key: str | None = Field(default=None, max_length=10_000)
    clear_api_key: bool = False

    @model_validator(mode="after")
    def secret_action_must_be_unambiguous(self) -> "ChatResourcePayload":
        if self.clear_api_key and self.api_key:
            raise ValueError("api_key and clear_api_key cannot be used together")
        return self


class ChatResourceResponse(BaseModel):
    resource_id: str
    revision: int
    name: str
    description: str
    base_url: str
    default_model: str
    models: list[str]
    local: bool
    allow_insecure_http: bool
    headers: dict[str, str]
    timeout_seconds: float
    api_key_envs: list[str]
    built_in: bool
    has_api_key: bool
    api_key_source: str | None
    secure_storage_available: bool
    created_at: str


class ChatResourceVerificationResponse(BaseModel):
    ok: bool
    detail: str
    resource_id: str
    model: str


class DialogueGenerationOptionsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host1_name: str = Field(default="Alex", min_length=1, max_length=100)
    host2_name: str = Field(default="Sam", min_length=1, max_length=100)
    host1_role: str = Field(
        default="explains the material clearly and with enthusiasm",
        min_length=1,
        max_length=2_000,
    )
    host2_role: str = Field(
        default="asks the questions a smart newcomer would ask",
        min_length=1,
        max_length=2_000,
    )
    style: str = Field(
        default="warm, curious and unhurried; plain language over jargon",
        min_length=1,
        max_length=4_000,
    )
    words_per_section: int = Field(default=320, ge=50, le=2_000)
    section_chars: int = Field(default=6_000, ge=500, le=100_000)
    max_sections: int = Field(default=40, ge=1, le=200)
    temperature: float = Field(default=0.8, ge=0, le=2)

    def to_domain(self) -> DialogueGenerationOptions:
        return DialogueGenerationOptions(**self.model_dump())


class DialogueGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=20_000_000)
    chat_resource_id: str = Field(min_length=1, max_length=64)
    model: str | None = Field(default=None, max_length=255)
    options: DialogueGenerationOptionsPayload = Field(
        default_factory=DialogueGenerationOptionsPayload
    )

    @field_validator("text")
    @classmethod
    def document_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("document text must not be blank")
        return value


class DialogueScriptResponse(BaseModel):
    turns: list[DialogueTurnPayload]
    sections: int
    outline: list[str]
    removed_duplicates: int
    word_count: int
    cancelled: bool
    progress: list[str]


class DialogueScriptJobResponse(BaseModel):
    id: str
    status: str
    chat_resource_id: str
    resource_revision: int
    model: str
    total_sections: int
    completed_sections: int
    progress: float
    progress_message: str
    progress_messages: list[str]
    result: DialogueScriptResponse | None
    error_code: str | None
    error_detail: str | None
    created_at: str
    updated_at: str


class DialogueRefineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chat_resource_id: str = Field(min_length=1, max_length=64)
    model: str | None = Field(default=None, max_length=255)
    before: str = Field(default="", max_length=100_000)
    selected: str = Field(min_length=1, max_length=100_000)
    after: str = Field(default="", max_length=100_000)
    instruction: str = Field(min_length=1, max_length=10_000)
    speaker: Literal["Person1", "Person2"]
    neighbor_before: DialogueTurnPayload | None = None
    neighbor_after: DialogueTurnPayload | None = None

    @field_validator("selected", "instruction")
    @classmethod
    def required_text_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("selected text and instruction must not be blank")
        return value


class DialogueRefineResponse(BaseModel):
    replacement: str


class ImportedDocumentMetadataResponse(BaseModel):
    title: str | None
    heading_count: int
    source_bytes: int


class ImportedDocumentResponse(BaseModel):
    filename: str
    format: str
    text: str
    metadata: ImportedDocumentMetadataResponse


class ChunkPreviewResponse(BaseModel):
    index: int
    text: str
    start_char: int
    end_char: int
    byte_count: int
    word_count: int
    character_count: int
    token_count: int | None
    limit_headroom: dict[str, int]
    boundary: str

    @classmethod
    def from_chunk(cls, chunk: PlannedChunk) -> "ChunkPreviewResponse":
        return cls(**{field: getattr(chunk, field) for field in cls.model_fields})


class PreviewResponse(BaseModel):
    text: str
    strategy: SplitStrategy
    target_mode: ChunkTargetMode
    target_value: int | None
    warnings: list[str]
    total_chars: int
    total_bytes: int
    total_words: int
    chunks: list[ChunkPreviewResponse]

    @classmethod
    def from_plan(cls, plan: ChunkPlan) -> "PreviewResponse":
        return cls(
            text=plan.text,
            strategy=plan.strategy,
            target_mode=plan.target_mode,
            target_value=plan.target_value,
            warnings=list(plan.warnings),
            total_chars=plan.total_chars,
            total_bytes=plan.total_bytes,
            total_words=plan.total_words,
            chunks=[ChunkPreviewResponse.from_chunk(chunk) for chunk in plan.chunks],
        )


class DialogueTurnPreviewResponse(BaseModel):
    turn_index: int
    speaker: Literal["Person1", "Person2"]
    text: str
    total_chars: int
    total_bytes: int
    total_words: int
    chunks: list[ChunkPreviewResponse]


class DialoguePreviewResponse(BaseModel):
    strategy: SplitStrategy
    total_turns: int
    total_chunks: int
    total_chars: int
    total_bytes: int
    total_words: int
    turns: list[DialogueTurnPreviewResponse]


class JobResponse(BaseModel):
    id: str
    status: JobStatus
    provider: str
    model: str
    voice: str
    instructions: str | None
    controls: DeliveryControlsPayload
    resource_revision: int | None
    variables: dict[str, Any]
    total_chunks: int
    completed_chunks: int
    progress: float
    error: str | None
    error_code: str | None
    error_detail: str | None
    error_retryable: bool | None
    error_status_code: int | None
    error_chunk_index: int | None
    error_occurred_at: str | None
    error_event_id: str | None
    audio_url: str | None
    partial_audio_url: str | None
    checkpoint_export_url: str | None
    export_stem: str
    download_filename: str
    current_char: int
    total_chars: int
    current_chunk_index: int | None
    current_excerpt: str | None
    created_at: str
    updated_at: str

    @classmethod
    def from_record(
        cls,
        job: JobRecord,
        progress_detail: dict[str, int | str | None] | None = None,
    ) -> "JobResponse":
        progress = job.completed_chunks / job.total_chunks if job.total_chunks else 0.0
        detail = progress_detail or {}
        current_chunk_index = detail.get("current_chunk_index")
        current_excerpt = detail.get("current_excerpt")
        return cls(
            id=job.id,
            status=job.status,
            provider=job.provider,
            model=job.model,
            voice=job.voice,
            instructions=job.instructions,
            controls=DeliveryControlsPayload.from_domain(job.controls),
            resource_revision=job.resource_revision,
            variables={
                key: value
                for key, value in job.variables.items()
                if key != SEGMENT_OPTIONS_VARIABLE
            },
            total_chunks=job.total_chunks,
            completed_chunks=job.completed_chunks,
            progress=progress,
            error=job.error,
            error_code=job.error_detail.code if job.error_detail else None,
            error_detail=job.error_detail.message if job.error_detail else job.error,
            error_retryable=job.error_detail.retryable if job.error_detail else None,
            error_status_code=job.error_detail.status_code if job.error_detail else None,
            error_chunk_index=job.error_detail.chunk_index if job.error_detail else None,
            error_occurred_at=job.error_detail.occurred_at if job.error_detail else None,
            error_event_id=job.error_detail.event_id if job.error_detail else None,
            audio_url=(
                f"/v1/speech/jobs/{job.id}/audio" if job.status is JobStatus.COMPLETED else None
            ),
            partial_audio_url=(
                f"/v1/speech/jobs/{job.id}/partial-audio"
                if job.completed_chunks > 0 and job.status is not JobStatus.COMPLETED
                else None
            ),
            checkpoint_export_url=(
                f"/v1/speech/jobs/{job.id}/checkpoints"
                if job.completed_chunks > 0
                else None
            ),
            export_stem=job.export_stem,
            download_filename=f"{job.export_stem}.wav",
            current_char=int(detail.get("current_char") or 0),
            total_chars=int(detail.get("total_chars") or 0),
            current_chunk_index=(
                int(current_chunk_index) if current_chunk_index is not None else None
            ),
            current_excerpt=(str(current_excerpt) if current_excerpt is not None else None),
            created_at=job.created_at,
            updated_at=job.updated_at,
        )


class ClientErrorReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(
        default="client_error",
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$",
    )
    category: str | None = Field(
        default=None,
        max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$",
    )
    message: str = Field(min_length=1, max_length=8_000)
    severity: Literal["info", "warning", "error", "critical"] = "error"
    retryable: bool = False
    status_code: int | None = Field(default=None, ge=100, le=599)
    method: str | None = Field(default=None, max_length=16, pattern=r"^[A-Za-z]+$")
    endpoint: str | None = Field(default=None, max_length=2_000)
    request: dict[str, Any] | None = None
    response: dict[str, Any] | None = None
    exception: dict[str, Any] | None = None
    context: dict[str, Any] | None = None
    provider: str | None = Field(
        default=None,
        max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$",
    )
    resource_revision: int | None = Field(default=None, ge=1)
    job_id: str | None = Field(
        default=None,
        max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$",
    )
    chunk_index: int | None = Field(default=None, ge=0)
    attempt: int | None = Field(default=None, ge=1)


class ErrorEventResponse(BaseModel):
    id: str
    sequence: int
    source: str
    severity: str
    code: str
    category: str | None
    message: str
    retryable: bool
    status_code: int | None
    method: str | None
    endpoint: str | None
    request: dict[str, Any] | None
    response: dict[str, Any] | None
    exception: dict[str, Any] | None
    context: dict[str, Any] | None
    provider: str | None
    resource_revision: int | None
    job_id: str | None
    chunk_index: int | None
    attempt: int | None
    count: int
    first_occurred_at: str
    last_occurred_at: str
    read_at: str | None

    @classmethod
    def from_record(cls, event: ErrorEventRecord) -> "ErrorEventResponse":
        safe_message = sanitize_diagnostic(event.message)
        safe_endpoint = sanitize_url(event.endpoint) if event.endpoint is not None else None
        safe_code = sanitize_diagnostic(event.code)
        safe_category = sanitize_diagnostic(event.category)
        safe_method = sanitize_diagnostic(event.method)
        safe_provider = sanitize_diagnostic(event.provider)
        safe_job_id = sanitize_diagnostic(event.job_id)
        return cls(
            id=event.id,
            sequence=event.sequence,
            source=event.source,
            severity=event.severity,
            code=str(safe_code or "unknown_error"),
            category=str(safe_category) if safe_category is not None else None,
            message=str(safe_message or "Error details unavailable"),
            retryable=event.retryable,
            status_code=event.status_code,
            method=str(safe_method) if safe_method is not None else None,
            endpoint=str(safe_endpoint) if safe_endpoint is not None else None,
            request=_sanitized_error_mapping(
                dict(event.request) if event.request is not None else None
            ),
            response=_sanitized_error_mapping(
                dict(event.response) if event.response is not None else None
            ),
            exception=_sanitized_error_mapping(
                dict(event.exception) if event.exception is not None else None
            ),
            context=_sanitized_error_mapping(
                dict(event.context) if event.context is not None else None
            ),
            provider=str(safe_provider) if safe_provider is not None else None,
            resource_revision=event.resource_revision,
            job_id=str(safe_job_id) if safe_job_id is not None else None,
            chunk_index=event.chunk_index,
            attempt=event.attempt,
            count=event.count,
            first_occurred_at=event.first_occurred_at,
            last_occurred_at=event.last_occurred_at,
            read_at=event.read_at,
        )


class ErrorEventBriefResponse(BaseModel):
    id: str
    sequence: int
    source: str
    severity: str
    code: str
    category: str | None
    message: str
    retryable: bool
    status_code: int | None
    method: str | None
    endpoint: str | None
    provider: str | None
    resource_revision: int | None
    job_id: str | None
    chunk_index: int | None
    attempt: int | None
    count: int
    first_occurred_at: str
    last_occurred_at: str
    read_at: str | None

    @classmethod
    def from_record(cls, event: ErrorEventRecord) -> "ErrorEventBriefResponse":
        return cls.model_validate(ErrorEventResponse.from_record(event).model_dump())


class ErrorEventListResponse(BaseModel):
    events: list[ErrorEventBriefResponse]
    unread_count: int
    total_count: int


def _sanitized_error_mapping(
    value: dict[str, Any] | None,
    *,
    known_secrets: tuple[str, ...] = (),
) -> dict[str, Any] | None:
    if value is None:
        return None
    sanitized = sanitize_diagnostic(value, known_secrets=known_secrets)
    return dict(sanitized) if isinstance(sanitized, dict) else {"value": sanitized}


def _client_error_fingerprint(identifying: dict[str, Any]) -> str:
    encoded = json.dumps(identifying, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class StudioProfilePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    resource_id: str = Field(min_length=1, max_length=64)
    resource_revision: int | None = Field(default=None, ge=1)
    text: str = ""
    model: str | None = Field(default=None, max_length=200)
    voice: str | None = Field(default=None, max_length=200)
    voice_profile_id: str | None = Field(default=None, max_length=64)
    instructions: str | None = Field(default=None, max_length=2_000)
    controls: DeliveryControlsPayload = Field(default_factory=DeliveryControlsPayload)
    split_strategy: SplitStrategy = SplitStrategy.SEMANTIC
    chunk_target_mode: ChunkTargetMode = ChunkTargetMode.AUTOMATIC
    chunk_target_value: int | None = Field(default=None, ge=1, le=10_000_000)
    remove_numeric_citations: bool = False
    variables: dict[str, Any] = Field(default_factory=dict)
    job_id: str | None = Field(default=None, max_length=64)

    @field_validator("name", "resource_id")
    @classmethod
    def required_text_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value cannot be blank")
        return normalized

    @model_validator(mode="after")
    def chunk_target_must_be_complete(self) -> "StudioProfilePayload":
        if self.chunk_target_mode is ChunkTargetMode.AUTOMATIC:
            if self.chunk_target_value is not None:
                raise ValueError("automatic chunk targeting does not accept a target value")
        elif self.chunk_target_value is None:
            raise ValueError(
                f"{self.chunk_target_mode.value} chunk targeting requires a target value"
            )
        elif self.chunk_target_mode is ChunkTargetMode.PARTS and self.chunk_target_value > 10_000:
            raise ValueError("parts chunk targeting accepts at most 10000 requested parts")
        return self


class StudioProfileResponse(StudioProfilePayload):
    id: str
    created_at: str
    updated_at: str
    job: JobResponse | None = None


class StudioProjectSummaryResponse(BaseModel):
    id: str
    name: str
    source_name: str | None
    source_media_type: str
    source_chars: int
    source_preview: str
    metadata: dict[str, Any]
    render_plan_count: int
    take_count: int
    created_at: str
    updated_at: str

    @classmethod
    def from_domain(
        cls,
        project: Project,
        *,
        render_plan_count: int,
        take_count: int,
    ) -> "StudioProjectSummaryResponse":
        return cls(
            id=project.id,
            name=project.name,
            source_name=project.source_name,
            source_media_type=project.source_media_type,
            source_chars=len(project.source_text),
            source_preview=" ".join(project.source_text.split())[:240],
            metadata={
                key: value
                for key, value in project.metadata.items()
                if key != "legacy_original_source_text"
            },
            render_plan_count=render_plan_count,
            take_count=take_count,
            created_at=project.created_at,
            updated_at=project.updated_at,
        )


class StudioProjectResponse(StudioProjectSummaryResponse):
    source_text: str


class BatchQueueItemPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1, max_length=64)
    profile_id: str = Field(min_length=1, max_length=64)


class BatchQueueCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="Narration batch", min_length=1, max_length=240)
    items: list[BatchQueueItemPayload] = Field(min_length=1, max_length=100)


class BatchQueueReorderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_ids: list[str] = Field(min_length=1, max_length=100)


class BatchItemResponse(BaseModel):
    id: str
    position: int
    project_id: str
    project_name: str
    profile_id: str
    profile_name: str
    status: BatchItemStatus
    job_id: str | None
    take_id: str | None
    source_sha256: str | None
    provider_name: str | None
    resource_revision: int | None
    model: str | None
    voice: str | None
    error_code: str | None
    error_detail: str | None
    created_at: str
    updated_at: str

    @classmethod
    def from_domain(cls, item: BatchItem) -> "BatchItemResponse":
        spec = item.spec
        return cls(
            id=item.id,
            position=item.position,
            project_id=item.project_id,
            project_name=item.project_name,
            profile_id=item.profile_id,
            profile_name=item.profile_name,
            status=item.status,
            job_id=item.job_id,
            take_id=item.take_id,
            source_sha256=spec.source_sha256 if spec else None,
            provider_name=spec.provider_name if spec else None,
            resource_revision=spec.resource_revision if spec else None,
            model=spec.model if spec else None,
            voice=spec.voice if spec else None,
            error_code=item.error_code,
            error_detail=item.error_detail,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )


class BatchQueueResponse(BaseModel):
    id: str
    name: str
    status: BatchQueueStatus
    progress: float
    counts: dict[str, int]
    pause_after_current: bool
    cancel_remaining: bool
    items: list[BatchItemResponse]
    created_at: str
    updated_at: str


class TimelineAudioArtifactResponse(BaseModel):
    id: str
    name: str
    intro_offset: float
    duration: float
    audio_url: str


class TimelineTakeResponse(BaseModel):
    id: str
    provider: str
    voice: str
    total_chunks: int
    finished_audio_artifacts: list[TimelineAudioArtifactResponse]
    created_at: str
    updated_at: str

    @classmethod
    def from_record(
        cls,
        job: JobRecord,
        *,
        finished_audio_artifacts: list[TimelineAudioArtifactResponse] | None = None,
    ) -> "TimelineTakeResponse":
        return cls(
            id=job.id,
            provider=job.provider,
            voice=job.voice,
            total_chunks=job.total_chunks,
            finished_audio_artifacts=finished_audio_artifacts or [],
            created_at=job.created_at,
            updated_at=job.updated_at,
        )


class TimelineSentenceSpanResponse(BaseModel):
    index: int
    text: str
    text_start: int
    text_end: int
    start: float
    end: float
    duration: float
    timing_source: str
    confidence: str
    reliable: bool

    @classmethod
    def from_domain(
        cls, sentence: TimelineSentenceSpan
    ) -> "TimelineSentenceSpanResponse":
        return cls(**asdict(sentence))


class TimelineSegmentResponse(BaseModel):
    index: int
    text: str
    start: float
    end: float
    duration: float
    byte_count: int
    word_count: int
    engine_id: str
    voice_id: str
    speaker: str | None
    sentences: list[TimelineSentenceSpanResponse]
    sentence_revision_available: bool
    sentence_revision_fallback: str | None

    @classmethod
    def from_domain(cls, segment: TimelineSegment) -> "TimelineSegmentResponse":
        return cls(
            index=segment.index,
            text=segment.text,
            start=segment.start,
            end=segment.end,
            duration=segment.duration,
            byte_count=segment.byte_count,
            word_count=segment.word_count,
            engine_id=segment.engine_id,
            voice_id=segment.voice_id,
            speaker=segment.speaker,
            sentences=[
                TimelineSentenceSpanResponse.from_domain(sentence)
                for sentence in segment.sentences
            ],
            sentence_revision_available=segment.sentence_revision_available,
            sentence_revision_fallback=segment.sentence_revision_fallback,
        )


class TimelineResponse(BaseModel):
    job_id: str
    status: JobStatus
    engine_id: str
    voice_id: str
    duration: float
    waveform: list[float]
    segments: list[TimelineSegmentResponse]
    audio_url: str | None

    @classmethod
    def from_domain(cls, timeline: JobTimeline) -> "TimelineResponse":
        return cls(
            job_id=timeline.job_id,
            status=timeline.status,
            engine_id=timeline.engine_id,
            voice_id=timeline.voice_id,
            duration=timeline.duration,
            waveform=list(timeline.waveform),
            segments=[TimelineSegmentResponse.from_domain(item) for item in timeline.segments],
            audio_url=timeline.audio_url,
        )


class TimelineRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)

    @field_validator("text")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be blank")
        return value


class TimelineSentenceRevisionRequest(TimelineRevisionRequest):
    crossfade_ms: float = Field(default=30.0, ge=0, le=250)


class SubtitleCueResponse(BaseModel):
    index: int
    source_text: str
    start: float
    end: float
    speaker: str | None
    confidence: str
    source: str

    @classmethod
    def from_domain(cls, cue: SubtitleCue) -> "SubtitleCueResponse":
        return cls(
            index=cue.index,
            source_text=cue.source_text,
            start=cue.start,
            end=cue.end,
            speaker=cue.speaker,
            confidence=cue.confidence.value,
            source=cue.source.value,
        )


class SubtitleTimelineResponse(BaseModel):
    job_id: str
    status: str
    partial: bool
    duration: float
    completed_chunks: int
    total_chunks: int
    source_counts: dict[str, int]
    confidence_counts: dict[str, int]
    cues: list[SubtitleCueResponse]

    @classmethod
    def from_domain(cls, timeline: SubtitleTimeline) -> "SubtitleTimelineResponse":
        return cls(
            job_id=timeline.job_id,
            status=timeline.status,
            partial=timeline.partial,
            duration=timeline.duration,
            completed_chunks=timeline.completed_chunks,
            total_chunks=timeline.total_chunks,
            source_counts=dict(timeline.source_counts),
            confidence_counts=dict(timeline.confidence_counts),
            cues=[SubtitleCueResponse.from_domain(cue) for cue in timeline.cues],
        )


class SubtitleExportResponse(BaseModel):
    artifact_id: str
    format: SubtitleFormat
    partial: bool
    cue_count: int
    size_bytes: int
    sha256: str
    download_url: str

    @classmethod
    def from_domain(cls, export: SubtitleExport) -> "SubtitleExportResponse":
        artifact = export.artifact
        output_format = SubtitleFormat(str(artifact.metadata["format"]))
        if artifact.sha256 is None:
            raise ValueError("subtitle artifact is missing its content hash")
        return cls(
            artifact_id=artifact.id,
            format=output_format,
            partial=export.timeline.partial,
            cue_count=len(export.timeline.cues),
            size_bytes=artifact.size_bytes,
            sha256=artifact.sha256,
            download_url=f"/v1/studio/subtitles/artifacts/{artifact.id}",
        )


class FinishingAssetResponse(BaseModel):
    id: str
    name: str
    media_type: str
    size_bytes: int
    sha256: str
    duration_seconds: float
    created_at: str

    @classmethod
    def from_domain(cls, asset: FinishingAsset) -> "FinishingAssetResponse":
        return cls(
            id=asset.id,
            name=asset.name,
            media_type=asset.media_type,
            size_bytes=asset.size_bytes,
            sha256=asset.sha256,
            duration_seconds=asset.duration_seconds,
            created_at=asset.created_at,
        )


class FinishingSpecPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intro_asset_id: str | None = Field(default=None, min_length=1, max_length=64)
    outro_asset_id: str | None = Field(default=None, min_length=1, max_length=64)
    crossfade_seconds: float = Field(default=1.0, ge=0, le=30)
    normalize_loudness: bool = False

    def to_domain(self) -> FinishingSpec:
        return FinishingSpec(**self.model_dump())


class FinishingCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_job_id: str = Field(min_length=1, max_length=64)
    spec: FinishingSpecPayload


class FinishingJobResponse(BaseModel):
    id: str
    source_job_id: str
    project_id: str
    take_id: str
    status: FinishingJobStatus
    spec: FinishingSpecPayload
    intro_offset: float
    intro_crossfade: float
    outro_crossfade: float
    source_duration: float
    output_duration: float
    progress: float
    output_url: str | None
    artifact_id: str | None
    subtitle_artifact_ids: list[str]
    error_code: str | None
    error_detail: str | None
    error_context: dict[str, Any]
    cancel_requested: bool
    created_at: str
    updated_at: str

    @classmethod
    def from_domain(cls, job: FinishingJob) -> "FinishingJobResponse":
        ready = job.status is FinishingJobStatus.COMPLETED and bool(job.output_path)
        return cls(
            id=job.id,
            source_job_id=job.source_job_id,
            project_id=job.project_id,
            take_id=job.take_id,
            status=job.status,
            spec=FinishingSpecPayload(**job.spec.to_mapping()),
            intro_offset=job.intro_offset,
            intro_crossfade=job.intro_crossfade,
            outro_crossfade=job.outro_crossfade,
            source_duration=job.source_duration,
            output_duration=job.output_duration,
            progress=job.progress,
            output_url=(
                f"/v1/studio/finishing/jobs/{job.id}/file" if ready else None
            ),
            artifact_id=job.artifact_id,
            subtitle_artifact_ids=list(job.subtitle_artifact_ids),
            error_code=job.error_code,
            error_detail=job.error_detail,
            error_context=dict(job.error_context),
            cancel_requested=job.cancel_requested,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )


class AudiogramSpecPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: AudiogramSource = AudiogramSource.WAVEFORM
    width: int = Field(default=1280, ge=320, le=3840, multiple_of=2)
    height: int = Field(default=720, ge=180, le=2160, multiple_of=2)
    fps: int = Field(default=24, ge=12, le=60)
    visualizer_height: int = Field(default=300, ge=64, le=2160)
    vertical_position: float = Field(default=0.5, ge=0, le=1)
    foreground_color: str = Field(default="#F4A259", pattern=r"^#[0-9a-fA-F]{6}$")
    background_color: str = Field(default="#0B0D10", pattern=r"^#[0-9a-fA-F]{6}$")
    background_mode: AudiogramBackgroundMode = AudiogramBackgroundMode.SOLID
    background_asset_id: str | None = None
    background_fit: AudiogramBackgroundFit = AudiogramBackgroundFit.COVER
    background_position_x: float = Field(default=0.5, ge=0, le=1)
    background_position_y: float = Field(default=0.5, ge=0, le=1)
    waveform_mode: Literal["cline", "line", "p2p", "point"] = "cline"
    amplitude_scale: Literal["lin", "sqrt", "cbrt", "log"] = "sqrt"
    blur: float = Field(default=0, ge=0, le=20)
    sharpen: float = Field(default=0, ge=0, le=1)
    trail: bool = False
    burn_captions: bool = False
    output_format: AudiogramOutputFormat = AudiogramOutputFormat.MP4
    preset: Literal["ultrafast", "veryfast", "fast", "medium"] = "ultrafast"
    crf: int = Field(default=20, ge=0, le=63)

    def to_domain(self) -> AudiogramSpec:
        try:
            return AudiogramSpec(**self.model_dump())
        except ValueError as error:
            raise ValueError(str(error)) from error


class AudiogramBackgroundResponse(BaseModel):
    id: str
    name: str
    media_type: str
    size_bytes: int
    sha256: str
    created_at: str
    url: str

    @classmethod
    def from_domain(cls, asset: AudiogramBackgroundAsset) -> "AudiogramBackgroundResponse":
        return cls(
            id=asset.id,
            name=asset.name,
            media_type=asset.media_type,
            size_bytes=asset.size_bytes,
            sha256=asset.sha256,
            created_at=asset.created_at,
            url=f"/v1/studio/audiograms/backgrounds/{asset.id}/file",
        )


class AudiogramCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_job_id: str = Field(min_length=1, max_length=64)
    kind: AudiogramJobKind = AudiogramJobKind.EXPORT
    spec: AudiogramSpecPayload = Field(default_factory=AudiogramSpecPayload)


class AudiogramJobResponse(BaseModel):
    id: str
    source_job_id: str
    project_id: str
    take_id: str
    kind: AudiogramJobKind
    status: AudiogramJobStatus
    spec: AudiogramSpecPayload
    duration_seconds: float
    render_seconds: float
    progress: float
    output_url: str | None
    artifact_id: str | None
    error_code: str | None
    error_detail: str | None
    cancel_requested: bool
    created_at: str
    updated_at: str

    @classmethod
    def from_domain(cls, job: AudiogramJob) -> "AudiogramJobResponse":
        return cls(
            id=job.id,
            source_job_id=job.source_job_id,
            project_id=job.project_id,
            take_id=job.take_id,
            kind=job.kind,
            status=job.status,
            spec=AudiogramSpecPayload.model_validate(job.spec.to_mapping()),
            duration_seconds=job.duration_seconds,
            render_seconds=job.render_seconds,
            progress=job.progress,
            output_url=(
                f"/v1/studio/audiograms/jobs/{job.id}/file"
                if job.status is AudiogramJobStatus.COMPLETED and job.output_path
                else None
            ),
            artifact_id=job.artifact_id,
            error_code=job.error_code,
            error_detail=job.error_detail,
            cancel_requested=job.cancel_requested,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )


class ConversionSpecPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output_format: AudioOutputFormat = AudioOutputFormat.MP3
    quality_pct: int = Field(default=70, ge=0, le=100)
    sample_rate: int = Field(default=48_000)
    bit_depth: int = Field(default=16)
    channels: int = Field(default=0, ge=0, le=2)
    normalize_loudness: bool = False
    split_mode: SplitMode = SplitMode.NONE
    split_minutes: float = Field(default=20, ge=0.1, le=1_440)
    split_megabytes: float = Field(default=25, ge=0.1, le=4_096)

    def to_domain(self) -> ConversionSpec:
        return ConversionSpec(**self.model_dump())


class ConversionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_job_id: str | None = Field(default=None, min_length=1, max_length=64)
    input_id: str | None = Field(default=None, min_length=1, max_length=64)
    spec: ConversionSpecPayload = Field(default_factory=ConversionSpecPayload)

    @model_validator(mode="after")
    def source_must_be_unambiguous(self) -> "ConversionCreateRequest":
        if bool(self.source_job_id) == bool(self.input_id):
            raise ValueError("choose exactly one completed take or uploaded audio file")
        return self


class ConversionInputResponse(BaseModel):
    id: str
    original_name: str
    media_type: str
    size_bytes: int
    created_at: str

    @classmethod
    def from_domain(cls, item: ConversionInput) -> "ConversionInputResponse":
        return cls(
            id=item.id,
            original_name=item.original_name,
            media_type=item.media_type,
            size_bytes=item.size_bytes,
            created_at=item.created_at,
        )


class ConversionJobResponse(BaseModel):
    id: str
    source_job_id: str | None
    input_id: str | None
    source_name: str
    project_id: str | None
    take_id: str | None
    status: ConversionJobStatus
    spec: ConversionSpecPayload
    duration_seconds: float
    progress: float
    output_url: str | None
    part_urls: list[str]
    artifact_ids: list[str]
    error_code: str | None
    error_detail: str | None
    cancel_requested: bool
    created_at: str
    updated_at: str

    @classmethod
    def from_domain(cls, job: ConversionJob) -> "ConversionJobResponse":
        ready = job.status is ConversionJobStatus.COMPLETED and bool(job.output_path)
        return cls(
            id=job.id,
            source_job_id=job.source_job_id,
            input_id=job.input_id,
            source_name=job.source_name,
            project_id=job.project_id,
            take_id=job.take_id,
            status=job.status,
            spec=ConversionSpecPayload(**job.spec.to_mapping()),
            duration_seconds=job.duration_seconds,
            progress=job.progress,
            output_url=f"/v1/studio/conversions/jobs/{job.id}/file" if ready else None,
            part_urls=(
                [f"/v1/studio/conversions/jobs/{job.id}/parts/{index}" for index in range(len(job.part_paths))]
                if ready
                else []
            ),
            artifact_ids=list(job.artifact_ids),
            error_code=job.error_code,
            error_detail=job.error_detail,
            cancel_requested=job.cancel_requested,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )


class TranscriptionOptionsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = Field(default="base", min_length=1, max_length=240)
    language: str | None = Field(default=None, max_length=24)
    device: Literal["auto", "cpu", "cuda"] = "auto"
    compute_type: Literal["default", "int8", "int8_float16", "float16", "float32"] = (
        "default"
    )
    vad_filter: bool = True
    word_timestamps: bool = False
    include_srt: bool = True
    include_vtt: bool = True
    line_timestamps: bool = False
    guessed_chapters: bool = True
    paragraph_gap_seconds: float = Field(default=2, ge=0.25, le=30)
    chapter_pause_seconds: float = Field(default=2, ge=0.25, le=30)

    @field_validator("language")
    @classmethod
    def normalize_language(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    def to_domain(self) -> TranscriptionOptions:
        return TranscriptionOptions(**self.model_dump())


class TranscriptionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_job_id: str | None = Field(default=None, min_length=1, max_length=64)
    input_id: str | None = Field(default=None, min_length=1, max_length=64)
    provider_id: str = Field(default="faster-whisper", min_length=1, max_length=100)
    options: TranscriptionOptionsPayload = Field(default_factory=TranscriptionOptionsPayload)

    @model_validator(mode="after")
    def source_must_be_unambiguous(self) -> "TranscriptionCreateRequest":
        if bool(self.source_job_id) == bool(self.input_id):
            raise ValueError("choose exactly one completed take or imported audio file")
        return self


class TranscriptionJobResponse(BaseModel):
    id: str
    source_job_id: str | None
    input_id: str | None
    source_name: str
    project_id: str | None
    take_id: str | None
    provider_id: str
    status: TranscriptionJobStatus
    phase: str
    options: TranscriptionOptionsPayload
    progress: float
    processed_seconds: float
    duration_seconds: float
    segment_count: int
    detected_language: str | None
    language_probability: float | None
    output_urls: dict[str, str]
    artifact_ids: dict[str, str]
    error_code: str | None
    error_detail: str | None
    cancel_requested: bool
    created_at: str
    updated_at: str

    @classmethod
    def from_domain(cls, job: TranscriptionJob) -> "TranscriptionJobResponse":
        ready = job.status is TranscriptionJobStatus.COMPLETED
        return cls(
            id=job.id,
            source_job_id=job.source_job_id,
            input_id=job.input_id,
            source_name=job.source_name,
            project_id=job.project_id,
            take_id=job.take_id,
            provider_id=job.provider_id,
            status=job.status,
            phase=job.phase,
            options=TranscriptionOptionsPayload(**job.options.to_mapping()),
            progress=job.progress,
            processed_seconds=job.processed_seconds,
            duration_seconds=job.duration_seconds,
            segment_count=job.segment_count,
            detected_language=job.detected_language,
            language_probability=job.language_probability,
            output_urls=(
                {
                    name: f"/v1/studio/transcriptions/jobs/{job.id}/files/{name}"
                    for name in job.output_paths
                }
                if ready
                else {}
            ),
            artifact_ids=dict(job.artifact_ids),
            error_code=job.error_code,
            error_detail=job.error_detail,
            cancel_requested=job.cancel_requested,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )


class PodcastChannelPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=300)
    author: str = Field(default="", max_length=300)
    owner_email: str = Field(default="", max_length=320)
    description: str = Field(min_length=1, max_length=10_000)
    website_url: str = Field(default="", max_length=2_000)
    media_base_url: str = Field(default="", max_length=2_000)
    artwork_url: str = Field(default="", max_length=2_000)
    category: str = Field(default="Technology", max_length=200)
    language: str = Field(default="en-us", min_length=2, max_length=35)
    explicit: bool = False
    updated_at: str | None = None

    def to_domain(self) -> PodcastChannel:
        return PodcastChannel(
            title=self.title.strip(),
            author=self.author.strip(),
            owner_email=self.owner_email.strip(),
            description=self.description.strip(),
            website_url=self.website_url.strip(),
            media_base_url=self.media_base_url.strip(),
            artwork_url=self.artwork_url.strip(),
            category=self.category.strip(),
            language=self.language.strip(),
            explicit=self.explicit,
        )

    @classmethod
    def from_domain(cls, channel: PodcastChannel) -> "PodcastChannelPayload":
        return cls(**asdict(channel))


class ChapterCueResponse(BaseModel):
    title: str
    seconds: float
    level: int

    @classmethod
    def from_domain(cls, cue: ChapterCue) -> "ChapterCueResponse":
        return cls(**asdict(cue))


class PublishEpisodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    take_id: str = Field(min_length=1, max_length=300)
    audio_artifact_id: str = Field(min_length=1, max_length=300)
    title: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=50_000)
    publication_date: str | None = Field(default=None, max_length=100)
    episode_number: int | None = Field(default=None, ge=1)


class PublishedEpisodeResponse(BaseModel):
    id: str
    take_id: str
    project_id: str
    audio_artifact_id: str
    title: str
    description: str
    publication_date: str
    episode_number: int
    media_type: str
    media_size_bytes: int
    duration_seconds: float
    transcript_artifact_id: str | None
    chapters_artifact_id: str | None
    chapters: list[ChapterCueResponse]
    media_url: str
    transcript_url: str | None
    chapters_url: str | None
    created_at: str
    updated_at: str

    @classmethod
    def from_domain(cls, episode: PublishedEpisode) -> "PublishedEpisodeResponse":
        return cls(
            id=episode.id,
            take_id=episode.take_id,
            project_id=episode.project_id,
            audio_artifact_id=episode.audio_artifact_id,
            title=episode.title,
            description=episode.description,
            publication_date=episode.publication_date,
            episode_number=episode.episode_number,
            media_type=episode.media_type,
            media_size_bytes=episode.media_size_bytes,
            duration_seconds=episode.duration_seconds,
            transcript_artifact_id=episode.transcript_artifact_id,
            chapters_artifact_id=episode.chapters_artifact_id,
            chapters=[ChapterCueResponse.from_domain(cue) for cue in episode.chapters],
            media_url=f"/v1/studio/publishing/episodes/{episode.id}/media",
            transcript_url=(
                f"/v1/studio/publishing/artifacts/{episode.transcript_artifact_id}"
                if episode.transcript_artifact_id
                else None
            ),
            chapters_url=(
                f"/v1/studio/publishing/artifacts/{episode.chapters_artifact_id}"
                if episode.chapters_artifact_id
                else None
            ),
            created_at=episode.created_at,
            updated_at=episode.updated_at,
        )


class EngineComponentPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    python_path: str = Field(min_length=1, max_length=4_096)

    @field_validator("python_path")
    @classmethod
    def path_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("python_path must not be blank")
        return value.strip()


class PronunciationEntryResponse(BaseModel):
    word: str
    ipa: str
    respelling: str | None = None

    @classmethod
    def from_domain(cls, entry: PronunciationEntry) -> "PronunciationEntryResponse":
        return cls(word=entry.word, ipa=entry.ipa, respelling=entry.respelling)


class RespellRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    word: str = Field(min_length=1, max_length=200)
    respelling: str = Field(min_length=1, max_length=500)


class RespellPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    respelling: str = Field(max_length=500)


class SubstitutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=500)
    replacement: str = Field(min_length=1, max_length=2_000)


def _payload_value(
    payload: ApiResourcePayload,
    field_name: str,
    current_value: Any,
    default: Any,
) -> Any:
    if field_name in payload.model_fields_set:
        return getattr(payload, field_name)
    return current_value if current_value is not None else default


def _variable_kind(value: Any) -> VariableType:
    if isinstance(value, bool):
        return VariableType.BOOLEAN
    if isinstance(value, int):
        return VariableType.INTEGER
    if isinstance(value, float):
        return VariableType.NUMBER
    if isinstance(value, str):
        return VariableType.STRING
    return VariableType.JSON


def _variable_definitions(
    payload: ApiResourcePayload,
    current: ApiResourceSpec | None,
) -> tuple[ApiVariableDefinition, ...]:
    if payload.variable_definitions is not None:
        definitions: list[ApiVariableDefinition] = []
        for item in payload.variable_definitions:
            allowed = {
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
            }
            unknown = set(item) - allowed
            if unknown:
                raise ValueError(
                    f"unknown variable definition fields: {', '.join(sorted(unknown))}"
                )
            definitions.append(
                ApiVariableDefinition(
                    name=item["name"],
                    kind=VariableType(item.get("kind", VariableType.STRING.value)),
                    label=item.get("label"),
                    description=item.get("description", ""),
                    group=item.get("group", "General"),
                    required=item.get("required", False),
                    default=item.get("default"),
                    choices=tuple(item.get("choices", ())),
                    minimum=item.get("minimum"),
                    maximum=item.get("maximum"),
                    step=item.get("step"),
                    unit=item.get("unit"),
                    sensitive=item.get("sensitive", False),
                    read_only=item.get("read_only", False),
                    randomizable=item.get("randomizable", False),
                    visible_when=item.get("visible_when", {}),
                    enabled_when=item.get("enabled_when", {}),
                )
            )
        return tuple(definitions)
    if payload.default_variables is not None:
        reserved = {"text", "model", "voice", "instructions", "api_key"}
        existing = {variable.name: variable for variable in current.variables} if current else {}
        definitions = [variable for variable in existing.values() if variable.name in reserved]
        for name, value in payload.default_variables.items():
            prior = existing.get(name)
            if prior is not None:
                try:
                    definitions.append(replace(prior, default=value))
                    continue
                except ValueError:
                    pass
            definitions.append(
                ApiVariableDefinition(name=name, kind=_variable_kind(value), default=value)
            )
        return tuple(definitions)
    return current.variables if current is not None else ()


def _voice_specs(
    values: list[str | dict[str, Any]] | None,
    current: tuple[TtsVoiceSpec, ...],
    default_voice: str,
) -> tuple[TtsVoiceSpec, ...]:
    if values is None:
        voices = list(current)
    else:
        voices = []
        for value in values:
            if isinstance(value, str):
                voices.append(TtsVoiceSpec(value))
                continue
            unknown = set(value) - {"id", "label", "traits"}
            if unknown:
                raise ValueError(f"unknown voice fields: {', '.join(sorted(unknown))}")
            voices.append(
                TtsVoiceSpec(
                    id=value["id"],
                    label=value.get("label"),
                    traits=tuple(value.get("traits", ())),
                )
            )
    if all(voice.id != default_voice for voice in voices):
        voices.insert(0, TtsVoiceSpec(default_voice))
    return tuple(voices)


def _default_generic_capabilities() -> TtsCapabilities:
    return TtsCapabilities(
        tone_presets=tuple(value.value for value in TonePreset),
        speech_paces=tuple(value.value for value in SpeechPace),
        vocal_styles=tuple(value.value for value in VocalStyle),
        nonverbal_frequencies=tuple(value.value for value in NonverbalFrequency),
        tone_modes=(CapabilityMode.NATIVE_ENUM,),
        pace_modes=(CapabilityMode.NATIVE_ENUM,),
        vocal_style_modes=(CapabilityMode.NATIVE_ENUM,),
        nonverbal_modes=(CapabilityMode.NATIVE_ENUM,),
        supports_custom_instructions=True,
    )


def _resource_spec_from_payload(
    payload: ApiResourcePayload,
    current: ApiResourceSpec | None = None,
) -> ApiResourceSpec:
    resource_id = payload.selected_id or (current.resource_id if current else None)
    if resource_id is None:
        raise ValueError("resource id is required")
    if current is not None and resource_id != current.resource_id:
        raise ValueError("resource id cannot be changed")

    adapter_value = payload.selected_adapter or (
        current.adapter_type.value if current else AdapterType.GENERIC_REST.value
    )
    adapter = AdapterType(adapter_value)
    method = HttpMethod(
        _payload_value(payload, "method", current.method.value if current else None, "POST")
    )
    base_url = _payload_value(
        payload,
        "base_url",
        current.base_url if current else None,
        None,
    )
    if not base_url:
        raise ValueError("base_url is required")

    current_auth = current.auth if current else None
    auth_mode = AuthMode(
        _payload_value(
            payload,
            "auth_placement",
            current_auth.mode.value if current_auth else None,
            AuthMode.HEADER.value,
        )
    )
    if auth_mode is AuthMode.NONE:
        auth = ApiAuthSpec()
    elif auth_mode is AuthMode.TEMPLATE:
        env_keys = _payload_value(
            payload,
            "auth_env_keys",
            current_auth.env_keys if current_auth else None,
            (),
        )
        auth = ApiAuthSpec(
            mode=auth_mode,
            credential_reference=(current_auth.credential_reference if current_auth else None),
            env_keys=tuple(env_keys or ()),
        )
    else:
        default_auth_name = "Authorization" if auth_mode is AuthMode.HEADER else "key"
        auth_name = _payload_value(
            payload,
            "auth_name",
            current_auth.name if current_auth else None,
            default_auth_name,
        )
        auth_prefix = _payload_value(
            payload,
            "auth_prefix",
            current_auth.prefix if current_auth else None,
            "Bearer ",
        )
        env_keys = _payload_value(
            payload,
            "auth_env_keys",
            current_auth.env_keys if current_auth else None,
            (),
        )
        auth = ApiAuthSpec(
            mode=auth_mode,
            name=auth_name,
            prefix=auth_prefix or "",
            credential_reference=(current_auth.credential_reference if current_auth else None),
            env_keys=tuple(env_keys or ()),
        )

    current_defaults = current.defaults if current else None
    default_model = _payload_value(
        payload,
        "default_model",
        current_defaults.default_model if current_defaults else None,
        None,
    )
    default_voice = _payload_value(
        payload,
        "default_voice",
        current_defaults.default_voice if current_defaults else None,
        None,
    )
    if not default_model or not default_voice:
        raise ValueError("default_model and default_voice are required")
    models = list(
        _payload_value(
            payload,
            "models",
            current_defaults.models if current_defaults else None,
            (),
        )
        or ()
    )
    if default_model not in models:
        models.insert(0, default_model)
    voices = _voice_specs(
        payload.voices if "voices" in payload.model_fields_set else None,
        current_defaults.voices if current_defaults else (),
        default_voice,
    )

    current_limits = current.input_limits if current else InputLimits()
    limits = InputLimits(
        max_bytes=_payload_value(payload, "max_input_bytes", current_limits.max_bytes, None),
        max_tokens=_payload_value(payload, "max_input_tokens", current_limits.max_tokens, None),
        max_characters=_payload_value(
            payload, "max_input_characters", current_limits.max_characters, None
        ),
        max_words=_payload_value(payload, "max_input_words", current_limits.max_words, None),
        recommended_bytes=_payload_value(
            payload, "recommended_chunk_bytes", current_limits.recommended_bytes, None
        ),
        recommended_words=_payload_value(
            payload, "recommended_chunk_words", current_limits.recommended_words, None
        ),
        recommended_characters=_payload_value(
            payload,
            "recommended_chunk_characters",
            current_limits.recommended_characters,
            None,
        ),
        limit_basis=LimitBasis(
            _payload_value(
                payload,
                "limit_basis",
                current_limits.limit_basis.value,
                LimitBasis.TEXT.value,
            )
        ),
    )

    current_retry = current.retry if current else RetryPolicy()
    retry = RetryPolicy(
        max_attempts=_payload_value(payload, "retry_max_attempts", current_retry.max_attempts, 3),
        request_timeout_seconds=_payload_value(
            payload,
            "request_timeout_seconds",
            current_retry.request_timeout_seconds,
            300.0,
        ),
        backoff_initial_seconds=_payload_value(
            payload,
            "retry_backoff_initial_seconds",
            current_retry.backoff_initial_seconds,
            5.0,
        ),
        backoff_max_seconds=_payload_value(
            payload,
            "retry_backoff_max_seconds",
            current_retry.backoff_max_seconds,
            60.0,
        ),
        jitter_seconds=_payload_value(
            payload, "retry_jitter_seconds", current_retry.jitter_seconds, 1.0
        ),
        retry_status_codes=tuple(
            _payload_value(
                payload,
                "retry_status_codes",
                current_retry.retry_status_codes,
                (408, 425, 429, 500, 502, 503, 504),
            )
        ),
        honor_retry_after=_payload_value(
            payload, "honor_retry_after", current_retry.honor_retry_after, True
        ),
    )

    current_pacing = current.pacing if current else PacingPolicy()
    pacing = PacingPolicy(
        minimum_interval_seconds=_payload_value(
            payload,
            "minimum_request_interval_seconds",
            current_pacing.minimum_interval_seconds,
            0.0,
        ),
        requests_per_minute=_payload_value(
            payload, "requests_per_minute", current_pacing.requests_per_minute, None
        ),
        max_concurrency=_payload_value(
            payload, "max_concurrency", current_pacing.max_concurrency, 1
        ),
    )

    current_response = current.response if current else None
    response_mode = ResponseMode(
        _payload_value(
            payload,
            "response_mode",
            current_response.mode.value if current_response else None,
            ResponseMode.RAW_PCM.value,
        )
    )
    response_pointer = _payload_value(
        payload,
        "audio_json_pointer",
        current_response.json_pointer if current_response else None,
        None,
    )
    if response_mode not in {ResponseMode.JSON_BASE64_PCM, ResponseMode.JSON_BASE64_WAV}:
        response_pointer = None
    response = ApiResponseSpec(
        mode=response_mode,
        json_pointer=response_pointer,
        sample_rate_hz=_payload_value(
            payload,
            "response_sample_rate_hz",
            current_response.sample_rate_hz if current_response else None,
            24_000,
        ),
        channels=_payload_value(
            payload,
            "response_channels",
            current_response.channels if current_response else None,
            1,
        ),
        sample_width_bytes=_payload_value(
            payload,
            "response_sample_width_bytes",
            current_response.sample_width_bytes if current_response else None,
            2,
        ),
    )

    if payload.capabilities is not None:
        capabilities = TtsCapabilities(**payload.capabilities)
    elif current is not None:
        capabilities = current.capabilities
    else:
        capabilities = _default_generic_capabilities()

    return ApiResourceSpec(
        resource_id=resource_id,
        revision=current.revision if current else 1,
        name=payload.name.strip(),
        description=_payload_value(
            payload, "description", current.description if current else None, ""
        )
        or "",
        adapter_type=adapter,
        method=method,
        base_url=base_url,
        allow_insecure_http=bool(
            _payload_value(
                payload,
                "allow_insecure_http",
                current.allow_insecure_http if current else None,
                False,
            )
        ),
        auth=auth,
        headers=_payload_value(payload, "headers", current.headers if current else None, {}) or {},
        query=_payload_value(payload, "query", current.query if current else None, {}) or {},
        request_template=_payload_value(
            payload,
            "request_template",
            current.request_template if current else None,
            {"text": "{{ text }}", "model": "{{ model }}", "voice": "{{ voice }}"},
        )
        or {},
        variables=_variable_definitions(payload, current),
        response=response,
        defaults=TtsDefaults(
            default_model=default_model,
            default_voice=default_voice,
            models=tuple(models),
            voices=voices,
        ),
        input_limits=limits,
        retry=retry,
        pacing=pacing,
        capabilities=capabilities,
    )


def _resource_response(
    spec: ApiResourceSpec,
    store: SqliteApiResourceStore,
    provider_info: ProviderInfo | None = None,
) -> dict[str, Any]:
    data = spec.to_dict()
    definitions = data.pop("variables")
    default_variables = {
        definition["name"]: definition["default"]
        for definition in definitions
        if definition["name"] not in {"text", "model", "voice", "instructions", "api_key"}
    }
    secure_storage_available = True
    try:
        api_key_source = store.api_key_source(spec)
        has_api_key = api_key_source is not None
    except SecretVaultUnavailableError:
        api_key_source = None
        has_api_key = False
        secure_storage_available = False
    data.update(
        {
            "id": spec.resource_id,
            "adapter": spec.adapter_type.value,
            "default_model": spec.defaults.default_model,
            "default_voice": spec.defaults.default_voice,
            "models": list(spec.defaults.models),
            "voices": data["defaults"]["voices"],
            "auth_placement": spec.auth.mode.value,
            "auth_name": spec.auth.name,
            "auth_prefix": spec.auth.prefix,
            "auth_env_keys": list(spec.auth.env_keys),
            "max_input_bytes": spec.input_limits.max_bytes,
            "max_input_tokens": spec.input_limits.max_tokens,
            "max_input_characters": spec.input_limits.max_characters,
            "max_input_words": spec.input_limits.max_words,
            "recommended_chunk_bytes": spec.input_limits.recommended_bytes,
            "recommended_chunk_words": spec.input_limits.recommended_words,
            "recommended_chunk_characters": spec.input_limits.recommended_characters,
            "limit_basis": spec.input_limits.limit_basis.value,
            "request_timeout_seconds": spec.retry.request_timeout_seconds,
            "retry_max_attempts": spec.retry.max_attempts,
            "minimum_request_interval_seconds": spec.pacing.minimum_interval_seconds,
            "requests_per_minute": spec.pacing.requests_per_minute,
            "max_concurrency": spec.pacing.max_concurrency,
            "response_mode": spec.response.mode.value,
            "audio_json_pointer": spec.response.json_pointer,
            "response_sample_rate_hz": spec.response.sample_rate_hz,
            "response_channels": spec.response.channels,
            "response_sample_width_bytes": spec.response.sample_width_bytes,
            "variable_definitions": definitions,
            "variables": default_variables,
            "default_variables": default_variables,
            "has_api_key": has_api_key,
            "api_key_source": api_key_source,
            "secure_storage_available": secure_storage_available,
        }
    )
    data["capabilities"]["models"] = list(spec.defaults.models)
    data["capabilities"]["voices"] = data["defaults"]["voices"]
    if provider_info is not None:
        provider_data = ProviderResponse.from_info(provider_info).model_dump(mode="json")
        data["default_model"] = provider_data["default_model"]
        data["default_voice"] = provider_data["default_voice"]
        data["capabilities"] = provider_data["capabilities"]
    return data


def _chat_resource_spec_from_payload(
    payload: ChatResourcePayload,
    current: ChatResourceSpec | None = None,
) -> ChatResourceSpec:
    return ChatResourceSpec(
        resource_id=payload.resource_id,
        revision=1 if current is None else current.revision + 1,
        name=payload.name,
        description=payload.description,
        base_url=payload.base_url,
        default_model=payload.default_model,
        models=tuple(payload.models),
        local=payload.local,
        allow_insecure_http=payload.allow_insecure_http,
        headers=payload.headers,
        timeout_seconds=payload.timeout_seconds,
        api_key_envs=tuple(payload.api_key_envs),
        built_in=False if current is None else current.built_in,
    )


def _chat_resource_response(
    stored: StoredChatResource,
    store: SqliteChatResourceStore,
) -> ChatResourceResponse:
    spec = stored.spec
    secure_storage_available = True
    try:
        api_key_source = store.api_key_source(spec.resource_id)
    except SecretVaultUnavailableError:
        api_key_source = None
        secure_storage_available = False
    return ChatResourceResponse(
        **spec.to_dict(),
        has_api_key=api_key_source is not None,
        api_key_source=api_key_source,
        secure_storage_available=secure_storage_available,
        created_at=stored.created_at,
    )


def create_app(
    *,
    settings: Settings | None = None,
    service: SynthesisService | None = None,
    chat_resource_store: SqliteChatResourceStore | None = None,
    dialogue_script_service: DialogueScriptJobService | None = None,
    subtitle_service: SubtitleService | None = None,
    finishing_service: FinishingJobService | None = None,
    audiogram_service: AudiogramJobService | None = None,
    conversion_service: ConversionJobService | None = None,
    transcription_service: TranscriptionJobService | None = None,
    publishing_service: PublishingService | None = None,
    voice_design_service: VoiceDesignJobService | None = None,
    batch_queue_service: BatchQueueService | None = None,
) -> FastAPI:
    base_settings = settings or Settings.from_env()
    components = ComponentManager(base_settings)
    resolved_settings = components.apply(base_settings)
    synthesis = service or create_service(resolved_settings)
    profiles = StudioProfileStore(resolved_settings.database_path)
    profiles.initialize()
    studio = SqliteStudioStore(resolved_settings.database_path)
    studio.initialize()
    batches = batch_queue_service or BatchQueueService(
        store=BatchQueueStore(resolved_settings.database_path),
        synthesis=synthesis,
    )
    batches.store.initialize()
    voice_designs = voice_design_service or VoiceDesignJobService(
        store=VoiceDesignJobStore(resolved_settings.database_path),
        studio_store=studio,
        output_root=resolved_settings.data_dir / "studio" / "voices",
        runner=(
            SubprocessQwenVoiceDesignRunner(
                resolved_settings.qwen3_python,
                timeout_seconds=max(
                    1_800.0,
                    resolved_settings.local_engine_startup_timeout_seconds,
                ),
            )
            if resolved_settings.qwen3_python is not None
            else None
        ),
    )
    voice_designs.store.initialize()
    subtitles = subtitle_service or SubtitleService(
        job_store=synthesis.store,
        job_storage=synthesis.storage,
        studio_store=studio,
        output_root=resolved_settings.data_dir / "studio" / "subtitles",
    )
    finishing = finishing_service or FinishingJobService(
        store=FinishingStore(resolved_settings.database_path),
        source_store=synthesis.store,
        source_storage=synthesis.storage,
        studio_store=studio,
        subtitle_service=subtitles,
        asset_root=resolved_settings.data_dir / "studio" / "finishing-assets",
        output_root=resolved_settings.data_dir / "studio" / "finished-audio",
        renderer=FfmpegFinishingRenderer(),
        max_upload_bytes=resolved_settings.max_audio_upload_bytes,
    )
    finishing.store.initialize()
    audiograms = audiogram_service or AudiogramJobService(
        store=AudiogramJobStore(resolved_settings.database_path),
        source_store=synthesis.store,
        source_storage=synthesis.storage,
        studio_store=studio,
        output_root=resolved_settings.data_dir / "studio" / "audiograms",
        background_root=resolved_settings.data_dir / "studio" / "audiogram-backgrounds",
        subtitle_service=subtitles,
        renderer=FfmpegAudiogramRenderer(),
        max_background_bytes=resolved_settings.max_audio_upload_bytes,
    )
    audiograms.store.initialize()
    conversions = conversion_service or ConversionJobService(
        store=ConversionJobStore(resolved_settings.database_path),
        source_store=synthesis.store,
        source_storage=synthesis.storage,
        studio_store=studio,
        output_root=resolved_settings.data_dir / "studio" / "conversions",
        input_root=resolved_settings.data_dir / "studio" / "conversion-inputs",
        converter=FfmpegAudioConverter(),
    )
    conversions.store.initialize()
    transcriptions = transcription_service or TranscriptionJobService(
        store=TranscriptionJobStore(resolved_settings.database_path),
        conversion_store=conversions.store,
        source_store=synthesis.store,
        source_storage=synthesis.storage,
        studio_store=studio,
        output_root=resolved_settings.data_dir / "studio" / "transcriptions",
        providers=[
            FasterWhisperProvider(
                python_path=resolved_settings.whisper_python,
                worker_path=Path(__file__).resolve().parent / "transcription_worker.py",
                download_root=resolved_settings.data_dir / "studio" / "models" / "faster-whisper",
                startup_timeout_seconds=resolved_settings.local_engine_startup_timeout_seconds,
            )
        ],
    )
    transcriptions.store.initialize()
    publishing = publishing_service or PublishingService(
        store=PublishingStore(resolved_settings.database_path),
        studio_store=studio,
        job_store=synthesis.store,
        job_storage=synthesis.storage,
        output_root=resolved_settings.data_dir / "studio" / "publishing",
    )
    publishing.initialize()
    customizations = synthesis.customizations
    kokoro_tools = (
        KokoroToolClient(
            resolved_settings.kokoro_python,
            timeout_seconds=min(
                resolved_settings.local_engine_startup_timeout_seconds,
                60.0,
            ),
        )
        if resolved_settings.kokoro_python is not None
        else None
    )
    candidate_resource_store = getattr(synthesis.providers, "store", None)
    resource_store = (
        candidate_resource_store
        if isinstance(candidate_resource_store, SqliteApiResourceStore)
        else None
    )
    chat_resources = chat_resource_store or SqliteChatResourceStore(
        resolved_settings.database_path,
        vault=resource_store.vault if resource_store is not None else None,
    )
    chat_resources.initialize()
    chat_resources.seed_builtins()

    def dialogue_completer(request: DialogueScriptJobRequest) -> OpenAiChatCompleter:
        stored = chat_resources.get_revision(
            request.chat_resource_id,
            request.resource_revision,
        )
        runtime = stored.spec.runtime(model=request.model)
        api_key = chat_resources.resolve_api_key(request.chat_resource_id)
        return OpenAiChatCompleter(runtime, api_key=api_key)

    dialogue_scripts = dialogue_script_service or DialogueScriptJobService(
        SqliteDialogueScriptJobStore(resolved_settings.database_path),
        dialogue_completer,
    )
    dialogue_scripts.store.initialize()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await synthesis.start()
        try:
            await dialogue_scripts.start()
            try:
                await voice_designs.start()
                try:
                    await finishing.start()
                    try:
                        await audiograms.start()
                        try:
                            await conversions.start()
                            try:
                                await transcriptions.start()
                                try:
                                    await batches.start()
                                    try:
                                        yield
                                    finally:
                                        await batches.stop()
                                finally:
                                    await transcriptions.stop()
                            finally:
                                await conversions.stop()
                        finally:
                            await audiograms.stop()
                    finally:
                        await finishing.stop()
                finally:
                    await voice_designs.stop()
            finally:
                await dialogue_scripts.stop()
        finally:
            await synthesis.stop()

    application = FastAPI(
        title="SPLICR Long-Document TTS",
        version="0.1.0",
        description="Queue, synthesize, checkpoint, and stitch long-form speech jobs.",
        lifespan=lifespan,
    )
    application.state.synthesis_service = synthesis
    application.state.api_resource_store = resource_store
    application.state.chat_resource_store = chat_resources
    application.state.dialogue_script_service = dialogue_scripts
    application.state.subtitle_service = subtitles
    application.state.finishing_service = finishing
    application.state.audiogram_service = audiograms
    application.state.conversion_service = conversions
    application.state.transcription_service = transcriptions
    application.state.batch_queue_service = batches
    application.state.publishing_service = publishing
    application.state.voice_design_service = voice_designs
    application.state.component_manager = components
    application.state.error_event_store = synthesis.store
    application.state.studio_store = studio
    application.state.text_customization_store = customizations
    auth_manager = AuthManager(
        resolved_settings.auth_credentials_path,
        session_seconds=resolved_settings.auth_session_seconds,
    )
    application.state.auth_manager = auth_manager
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved_settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type"],
    )
    if resolved_settings.auth_enabled:
        application.add_middleware(
            AuthMiddleware,
            manager=auth_manager,
            cookie_secure=resolved_settings.auth_cookie_secure,
        )

    def sync_studio_job(
        job: JobRecord,
        *,
        project_name: str | None = None,
        source_name: str | None = None,
        take_label: str = "Narration take",
        target_project_id: str | None = None,
    ) -> str | None:
        if target_project_id is None:
            marker = job.variables.get(BATCH_ITEM_VARIABLE)
            item_id = marker.get("item_id") if isinstance(marker, Mapping) else None
            if isinstance(item_id, str):
                try:
                    batch_item = batches.store.get_item(item_id)
                except LookupError:
                    batch_item = None
                if batch_item is not None:
                    target_project_id = batch_item.project_id
                    project_name = batch_item.project_name
                    take_label = f"Batch · {batch_item.profile_name}"
                    if batch_item.spec is not None:
                        source_name = batch_item.spec.source_name
        try:
            imported = import_splicr_job(
                job_id=job.id,
                job_store=synthesis.store,
                job_storage=synthesis.storage,
                studio_store=studio,
                project_name=project_name,
                source_name=source_name,
                source_media_type=(
                    mimetypes.guess_type(source_name)[0]
                    if source_name is not None
                    else None
                ),
                take_label=take_label,
                target_project_id=target_project_id,
            )
            return imported.take_id
        except Exception:
            # A queued synthesis must not be reported as failed merely because the
            # secondary Studio index could not be refreshed. Later reads retry it.
            logger.exception("Failed to synchronize job %s into Studio", job.id)
            return None

    def job_response(
        job: JobRecord,
        *,
        project_name: str | None = None,
        source_name: str | None = None,
        take_label: str = "Narration take",
    ) -> JobResponse:
        sync_studio_job(
            job,
            project_name=project_name,
            source_name=source_name,
            take_label=take_label,
        )
        response = JobResponse.from_record(job, synthesis.progress_detail(job.id))
        if (
            response.error_event_id
            and synthesis.store.get_error_event(response.error_event_id) is None
        ):
            return response.model_copy(update={"error_event_id": None})
        return response

    def batch_queue_response(queue: BatchQueue) -> BatchQueueResponse:
        processed = sum(
            item.status
            in {
                BatchItemStatus.COMPLETED,
                BatchItemStatus.FAILED,
                BatchItemStatus.SKIPPED,
                BatchItemStatus.CANCELLED,
            }
            for item in queue.items
        )
        current_fraction = 0.0
        current = next(
            (item for item in queue.items if item.status is BatchItemStatus.RUNNING),
            None,
        )
        if current and current.job_id:
            try:
                job = synthesis.get_job(current.job_id)
                if job.total_chunks:
                    current_fraction = min(1.0, job.completed_chunks / job.total_chunks)
            except JobNotFoundError:
                pass
        total = len(queue.items)
        progress = (processed + current_fraction) / total if total else 1.0
        return BatchQueueResponse(
            id=queue.id,
            name=queue.name,
            status=queue.status,
            progress=progress,
            counts=queue.counts,
            pause_after_current=queue.pause_after_current,
            cancel_remaining=queue.cancel_remaining,
            items=[BatchItemResponse.from_domain(item) for item in queue.items],
            created_at=queue.created_at,
            updated_at=queue.updated_at,
        )

    def sync_batch_job(job: JobRecord) -> str | None:
        marker = job.variables.get(BATCH_ITEM_VARIABLE)
        if not isinstance(marker, Mapping):
            return sync_studio_job(job)
        item_id = marker.get("item_id")
        if not isinstance(item_id, str):
            return sync_studio_job(job)
        try:
            item = batches.store.get_item(item_id)
        except LookupError:
            return sync_studio_job(job)
        spec = item.spec
        return sync_studio_job(
            job,
            project_name=item.project_name,
            source_name=spec.source_name if spec else None,
            take_label=f"Batch · {item.profile_name}",
            target_project_id=item.project_id,
        )

    batches.on_job_completed = sync_batch_job

    def require_resource_store() -> SqliteApiResourceStore:
        if resource_store is None:
            raise HTTPException(
                status_code=404,
                detail="configurable API resources are unavailable for this service instance",
            )
        return resource_store

    def known_provider_secrets() -> tuple[str, ...]:
        """Read credentials only to guarantee that diagnostics cannot retain them."""

        secrets = [
            value
            for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "DEEPGRAM_API_KEY", "INWORLD_API_KEY")
            if (value := os.getenv(name))
        ]
        if resource_store is not None:
            for spec in resource_store.list():
                try:
                    secret = resource_store.resolve_api_key(spec)
                except SecretVaultUnavailableError:
                    continue
                if secret:
                    secrets.append(secret)
        for stored in chat_resources.list():
            try:
                secret = chat_resources.resolve_api_key(stored.spec.resource_id)
            except SecretVaultUnavailableError:
                continue
            if secret:
                secrets.append(secret)
        return tuple(dict.fromkeys(secrets))

    def dialogue_script_response(
        script: GeneratedDialogueScript,
        progress_messages: list[str] | tuple[str, ...],
    ) -> DialogueScriptResponse:
        return DialogueScriptResponse(
            turns=[
                DialogueTurnPayload(speaker=turn.speaker, text=turn.text)
                for turn in script.turns
            ],
            sections=script.sections,
            outline=list(script.outline),
            removed_duplicates=script.removed_duplicates,
            word_count=script.word_count,
            cancelled=script.cancelled,
            progress=list(progress_messages),
        )

    def dialogue_script_job_response(
        job: DialogueScriptJob,
    ) -> DialogueScriptJobResponse:
        known_secrets = known_provider_secrets()
        safe_progress_messages = [
            str(sanitize_diagnostic(message, known_secrets=known_secrets))
            for message in job.progress_messages
        ]
        safe_error = (
            str(
                sanitize_diagnostic(
                    job.error_detail,
                    known_secrets=known_secrets,
                )
            )
            if job.error_detail
            else None
        )
        return DialogueScriptJobResponse(
            id=job.id,
            status=job.status.value,
            chat_resource_id=job.request.chat_resource_id,
            resource_revision=job.request.resource_revision,
            model=job.request.model,
            total_sections=job.total_sections,
            completed_sections=job.completed_sections,
            progress=job.progress,
            progress_message=str(
                sanitize_diagnostic(
                    job.progress_message,
                    known_secrets=known_secrets,
                )
            ),
            progress_messages=safe_progress_messages,
            result=(
                dialogue_script_response(job.result, safe_progress_messages)
                if job.result is not None
                else None
            ),
            error_code=job.error_code,
            error_detail=safe_error,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )

    async def invalidate_resource(resource_id: str) -> None:
        invalidator = getattr(synthesis.providers, "invalidate", None)
        if invalidator is None:
            return
        result = invalidator(resource_id)
        if inspect.isawaitable(result):
            await result

    def provider_info_for(resource_id: str) -> ProviderInfo | None:
        return next(
            (info for info in synthesis.providers.list() if info.name == resource_id),
            None,
        )

    def secure_storage_error(error: SecretVaultUnavailableError) -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "SECURE_STORAGE_UNAVAILABLE", "message": str(error)},
        )

    def configured_chat(
        resource_id: str,
        model: str | None,
    ) -> tuple[OpenAiChatCompleter, str]:
        stored = chat_resources.get_current(resource_id)
        selected_model = (model or stored.spec.default_model).strip()
        runtime = stored.spec.runtime(model=selected_model)
        api_key = chat_resources.resolve_api_key(stored.spec.resource_id)
        return OpenAiChatCompleter(runtime, api_key=api_key), selected_model

    def chat_provider_error(error: ChatCompletionError | DialogueGenerationError) -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "CHAT_PROVIDER_ERROR",
                "message": str(error),
                "provider_status": getattr(error, "status_code", None),
                "retryable": bool(getattr(error, "retryable", False)),
            },
        )

    def profile_response(profile: StudioProfile) -> StudioProfileResponse:
        linked_job: JobResponse | None = None
        if profile.job_id:
            try:
                linked_job = job_response(synthesis.get_job(profile.job_id))
            except JobNotFoundError:
                linked_job = None
        return StudioProfileResponse(
            id=profile.id,
            name=profile.name,
            resource_id=profile.resource_id,
            resource_revision=profile.resource_revision,
            text=profile.text,
            model=profile.model,
            voice=profile.voice,
            voice_profile_id=profile.voice_profile_id,
            instructions=profile.instructions,
            controls=DeliveryControlsPayload.from_domain(profile.controls),
            split_strategy=profile.split_strategy,
            chunk_target_mode=profile.chunk_target_mode,
            chunk_target_value=profile.chunk_target_value,
            remove_numeric_citations=profile.remove_numeric_citations,
            variables=dict(profile.variables),
            job_id=profile.job_id,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
            job=linked_job,
        )

    def validate_profile_payload(payload: StudioProfilePayload) -> dict[str, Any]:
        submitted_variables = dict(payload.variables)
        if VOICE_PROFILE_VARIABLE in payload.variables:
            raise HTTPException(
                status_code=422,
                detail=f"{VOICE_PROFILE_VARIABLE} is managed by Voice Profile selection",
            )
        if len(payload.text.encode("utf-8")) > resolved_settings.max_source_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="profile text exceeds the configured source-text limit",
            )
        if payload.job_id:
            try:
                synthesis.get_job(payload.job_id)
            except JobNotFoundError as error:
                raise HTTPException(status_code=422, detail="linked job was not found") from error
        if payload.voice_profile_id:
            voice_profile = require_voice_profile(payload.voice_profile_id)
            try:
                _, submitted_variables = resolve_voice_profile(
                    payload.resource_id,
                    voice_profile,
                    submitted_variables,
                )
                submitted_variables.pop(VOICE_PROFILE_VARIABLE, None)
            except ValueError as error:
                raise HTTPException(status_code=422, detail=str(error)) from error
        try:
            selected_provider = None
            if resource_store is not None:
                resource = (
                    resource_store.get(payload.resource_id, payload.resource_revision)
                    if payload.resource_revision is not None
                    else resource_store.get_current(payload.resource_id)
                )
                if resource is None:
                    if payload.resource_revision is not None:
                        raise UnknownProviderError(
                            f"unknown TTS provider revision: "
                            f"{payload.resource_id}@{payload.resource_revision}"
                        )
                    selected_provider = synthesis.providers.get(payload.resource_id)
                else:
                    revision_resolver = getattr(synthesis.providers, "get_revision", None)
                    selected_provider = (
                        revision_resolver(payload.resource_id, payload.resource_revision)
                        if payload.resource_revision is not None
                        and revision_resolver is not None
                        else synthesis.providers.get(payload.resource_id)
                    )
            else:
                selected_provider = synthesis.providers.get(payload.resource_id)
            capabilities = selected_provider.info.capabilities
            normalized_variables = validate_control_values(
                capabilities.control_definitions,
                submitted_variables,
                allow_unknown=capabilities.allows_undeclared_variables,
            )
        except UnknownProviderError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except (TypeError, ValueError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return normalized_variables

    def profile_resource_revision(payload: StudioProfilePayload) -> int | None:
        if payload.resource_revision is not None:
            return payload.resource_revision
        resolver = getattr(synthesis.providers, "current_revision", None)
        if resolver is None:
            return None
        revision = resolver(payload.resource_id)
        return int(revision) if revision is not None else None

    def require_kokoro_tools() -> KokoroToolClient:
        if kokoro_tools is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Kokoro pronunciation tools are unavailable. Configure "
                    "SPLICR_KOKORO_PYTHON with the isolated Kokoro environment."
                ),
            )
        return kokoro_tools

    def run_kokoro_tool(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return require_kokoro_tools().execute(operation, payload)
        except KokoroToolError as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(error),
            ) from error

    managed_voice_root = (resolved_settings.data_dir / "studio" / "voices").resolve()

    def require_voice_profile(profile_id: str) -> VoiceProfile:
        try:
            return studio.get_voice_profile(profile_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Voice profile not found") from error

    def voice_design_response(job: VoiceDesignJob) -> VoiceDesignJobResponse:
        profile: VoiceProfileResponse | None = None
        if job.profile_id:
            try:
                profile = VoiceProfileResponse.from_domain(
                    studio.get_voice_profile(job.profile_id)
                )
            except KeyError:
                profile = None
        return VoiceDesignJobResponse(
            id=job.id,
            label=job.label,
            description=job.description,
            take=job.take,
            status=job.status,
            progress=job.progress,
            profile_id=job.profile_id,
            reference_text=job.reference_text,
            error_code=job.error_code,
            error_detail=job.error_detail,
            created_at=job.created_at,
            updated_at=job.updated_at,
            profile=profile,
        )

    def resolved_voice_request(
        request: CreateJobRequest,
    ) -> tuple[str | None, str | None, dict[str, Any]]:
        managed_variables = {
            key
            for key in (VOICE_PROFILE_VARIABLE, SEGMENT_OPTIONS_VARIABLE)
            if key in request.variables
        }
        if managed_variables:
            key = sorted(managed_variables)[0]
            owner = (
                "Voice Profile selection"
                if key == VOICE_PROFILE_VARIABLE
                else "SPLICR"
            )
            raise HTTPException(
                status_code=422,
                detail=f"{key} is managed by {owner}",
            )
        if not request.voice_profile_id:
            return request.model, request.voice, dict(request.variables)
        profile = require_voice_profile(request.voice_profile_id)
        if (
            request.instructions
            and profile.engine_id.strip().casefold() in {"qwen3", "qwen3-local"}
            and profile.kind is not VoiceProfileKind.PRESET
        ):
            raise HTTPException(
                status_code=422,
                detail="Qwen3 custom directions are available for preset speakers, not cloned voices",
            )
        try:
            voice, variables = resolve_voice_profile(
                request.selected_resource_id,
                profile,
                request.variables,
            )
            return (
                model_for_voice_profile(
                    request.selected_resource_id,
                    profile,
                    request.model,
                ),
                voice,
                variables,
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    def freeze_batch_item(payload: BatchQueueItemPayload) -> BatchItemDraft:
        try:
            project = studio.get_project(payload.project_id)
        except KeyError as error:
            return BatchItemDraft(
                project_id=payload.project_id,
                project_name=payload.project_id,
                profile_id=payload.profile_id,
                profile_name=payload.profile_id,
                spec=None,
                error_code="missing_source",
                error_detail=str(error),
            )
        try:
            profile = profiles.get(payload.profile_id)
        except ProfileNotFoundError as error:
            return BatchItemDraft(
                project_id=project.id,
                project_name=project.name,
                profile_id=payload.profile_id,
                profile_name=payload.profile_id,
                spec=None,
                error_code="invalid_profile",
                error_detail=str(error),
            )
        if not project.source_text.strip():
            return BatchItemDraft(
                project_id=project.id,
                project_name=project.name,
                profile_id=profile.id,
                profile_name=profile.name,
                spec=None,
                error_code="missing_source",
                error_detail="The selected project contains no source text",
            )
        request = CreateJobRequest(
            text=project.source_text,
            resource_id=profile.resource_id,
            resource_revision=profile.resource_revision,
            model=profile.model,
            voice=profile.voice,
            voice_profile_id=profile.voice_profile_id,
            instructions=profile.instructions,
            controls=DeliveryControlsPayload.from_domain(profile.controls),
            variables=profile.variables,
            split_strategy=profile.split_strategy,
            chunk_target_mode=profile.chunk_target_mode,
            chunk_target_value=profile.chunk_target_value,
            remove_numeric_citations=profile.remove_numeric_citations,
            project_name=project.name,
            source_name=project.source_name,
            export_name=project.name,
        )
        try:
            model, voice, variables = resolved_voice_request(request)
        except HTTPException as error:
            return BatchItemDraft(
                project_id=project.id,
                project_name=project.name,
                profile_id=profile.id,
                profile_name=profile.name,
                spec=None,
                error_code="invalid_profile",
                error_detail=str(error.detail),
            )
        revision = profile.resource_revision
        if revision is None:
            resolver = getattr(synthesis.providers, "current_revision", None)
            if resolver is not None:
                current_revision = resolver(profile.resource_id)
                revision = int(current_revision) if current_revision is not None else None
        controls_payload = DeliveryControlsPayload.from_domain(profile.controls).model_dump(
            mode="json"
        )
        profile_snapshot: dict[str, JsonValue] = {
            "id": profile.id,
            "name": profile.name,
            "resource_id": profile.resource_id,
            "resource_revision": revision,
            "model": model,
            "voice": voice,
            "voice_profile_id": profile.voice_profile_id,
            "instructions": profile.instructions,
            "controls": _plain_control_value(controls_payload),
            "variables": _plain_control_value(variables),
            "split_strategy": profile.split_strategy.value,
            "chunk_target_mode": profile.chunk_target_mode.value,
            "chunk_target_value": profile.chunk_target_value,
            "remove_numeric_citations": profile.remove_numeric_citations,
        }
        spec = BatchItemSpec(
            project_id=project.id,
            project_name=project.name,
            source_name=project.source_name,
            source_text=project.source_text,
            source_sha256=hashlib.sha256(project.source_text.encode("utf-8")).hexdigest(),
            profile_id=profile.id,
            profile_name=profile.name,
            profile_snapshot=profile_snapshot,
            provider_name=profile.resource_id,
            resource_revision=revision,
            model=model,
            voice=voice,
            instructions=profile.instructions,
            controls=profile.controls,
            variables=variables,
            split_strategy=profile.split_strategy,
            chunk_target_mode=profile.chunk_target_mode,
            chunk_target_value=profile.chunk_target_value,
            remove_numeric_citations=profile.remove_numeric_citations,
            export_stem=project.name,
        )
        return BatchItemDraft(
            project_id=project.id,
            project_name=project.name,
            profile_id=profile.id,
            profile_name=profile.name,
            spec=spec,
        )

    def resolved_dialogue_speaker(
        resource_id: str,
        speaker: DialogueSpeakerPayload,
    ) -> tuple[str | None, str | None, dict[str, Any]]:
        return resolved_voice_request(
            CreateJobRequest(
                text="Dialogue voice configuration",
                resource_id=resource_id,
                model=speaker.model,
                voice=speaker.voice,
                voice_profile_id=speaker.voice_profile_id,
                instructions=speaker.instructions,
                controls=speaker.controls,
                variables=speaker.variables,
            )
        )

    def dialogue_segments(request: DialogueRenderRequest) -> tuple[SynthesisSegment, ...]:
        resolved = {
            "Person1": resolved_dialogue_speaker(
                request.selected_resource_id,
                request.person1,
            ),
            "Person2": resolved_dialogue_speaker(
                request.selected_resource_id,
                request.person2,
            ),
        }
        segments: list[SynthesisSegment] = []
        for turn in request.turns:
            speaker = request.speaker_settings(turn.speaker)
            model, voice, variables = resolved[turn.speaker]
            segments.append(
                SynthesisSegment(
                    text=turn.text,
                    model=model,
                    voice=voice,
                    instructions=speaker.instructions,
                    controls=speaker.controls.to_domain(),
                    variables=variables,
                    speaker=turn.speaker,
                )
            )
        return tuple(segments)

    def managed_voice_directory(profile: VoiceProfile) -> Path | None:
        if not profile.metadata.get("managed") or not profile.reference_audio_path:
            return None
        candidate = Path(profile.reference_audio_path).resolve().parent
        if not candidate.is_relative_to(managed_voice_root):
            logger.error("Refused managed voice path outside Studio root: %s", candidate)
            return None
        return candidate

    @application.get("/health", tags=["service"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get(
        "/v1/studio/pronunciations",
        response_model=list[PronunciationEntryResponse],
    )
    def list_pronunciations() -> list[PronunciationEntryResponse]:
        return [
            PronunciationEntryResponse.from_domain(entry)
            for entry in customizations.pronunciation_entries()
        ]

    @application.get("/v1/studio/pronunciation/status")
    def pronunciation_status() -> dict[str, Any]:
        available = (
            kokoro_tools is not None and kokoro_tools.python_executable.is_file()
        )
        return {
            "available": available,
            "message": (
                "Kokoro pronunciation tools are ready."
                if available
                else (
                    "Configure SPLICR_KOKORO_PYTHON to search, inspect, and preview "
                    "Kokoro pronunciations. Saved overrides remain visible."
                )
            ),
        }

    @application.get("/v1/studio/pronunciation/search")
    def search_pronunciations(
        query: str = Query(default="", max_length=200),
        limit: int = Query(default=150, ge=1, le=500),
    ) -> dict[str, Any]:
        return run_kokoro_tool(
            "lookup_words",
            {
                "query": query,
                "limit": limit,
                "overrides": customizations.pronunciation_snapshot(),
            },
        )

    @application.get("/v1/studio/pronunciation/word")
    def get_word_pronunciation(
        word: str = Query(min_length=1, max_length=200),
    ) -> dict[str, Any]:
        return run_kokoro_tool(
            "current_phonemes",
            {
                "word": word,
                "overrides": customizations.pronunciation_snapshot(),
            },
        )

    @application.post("/v1/studio/pronunciation/preview")
    def preview_pronunciation(payload: RespellPreviewRequest) -> dict[str, Any]:
        return run_kokoro_tool(
            "respell_to_ipa",
            {"respelling": payload.respelling},
        )

    @application.put(
        "/v1/studio/pronunciations/{word}",
        response_model=PronunciationEntryResponse,
    )
    def save_pronunciation(word: str, payload: RespellRequest) -> PronunciationEntryResponse:
        if word.strip().lower() != payload.word.strip().lower():
            raise HTTPException(status_code=422, detail="path word and payload word must match")
        result = run_kokoro_tool(
            "respell_to_ipa",
            {"respelling": payload.respelling},
        )
        failed = result.get("failed")
        ipa = result.get("ipa")
        if failed or not isinstance(ipa, str) or not ipa:
            detail = (
                f"{failed!r} is not a word Kokoro recognizes; try a different real word"
                if failed
                else "respelling did not produce a pronunciation"
            )
            raise HTTPException(status_code=422, detail=detail)
        try:
            entry = customizations.save_pronunciation(
                word=word,
                ipa=ipa,
                respelling=payload.respelling,
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return PronunciationEntryResponse.from_domain(entry)

    @application.delete("/v1/studio/pronunciations/{word}", status_code=204)
    def delete_pronunciation(word: str) -> Response:
        try:
            removed = customizations.delete_pronunciation(word)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if not removed:
            raise HTTPException(status_code=404, detail="pronunciation override not found")
        return Response(status_code=204)

    @application.get("/v1/studio/substitutions")
    def list_substitutions() -> dict[str, str]:
        return customizations.substitutions()

    @application.post("/v1/studio/substitutions")
    def save_substitution(payload: SubstitutionRequest) -> dict[str, str]:
        try:
            return customizations.save_substitution(
                source=payload.source,
                replacement=payload.replacement,
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @application.delete("/v1/studio/substitutions", status_code=204)
    def delete_substitution(
        source: str = Query(min_length=1, max_length=500),
    ) -> Response:
        try:
            removed = customizations.delete_substitution(source)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if not removed:
            raise HTTPException(status_code=404, detail="substitution not found")
        return Response(status_code=204)

    @application.post(
        "/v1/documents/import",
        response_model=ImportedDocumentResponse,
        tags=["documents"],
    )
    async def import_document_file(file: UploadFile = File(...)) -> ImportedDocumentResponse:
        filename = file.filename or "document"
        content = await file.read(resolved_settings.max_upload_bytes + 1)
        if len(content) > resolved_settings.max_upload_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail={
                    "code": "file_too_large",
                    "message": (
                        f"Document exceeds the {resolved_settings.max_upload_bytes}-byte upload "
                        "limit."
                    ),
                },
            )
        try:
            imported = await asyncio.to_thread(
                import_document,
                filename,
                content,
                max_upload_bytes=resolved_settings.max_upload_bytes,
                max_expanded_bytes=resolved_settings.max_source_bytes * 4,
            )
        except DocumentImportError as error:
            too_large = "too_large" in error.code.value
            raise HTTPException(
                status_code=(
                    status.HTTP_413_CONTENT_TOO_LARGE
                    if too_large
                    else status.HTTP_422_UNPROCESSABLE_ENTITY
                ),
                detail={"code": error.code.value, "message": str(error)},
            ) from error
        if len(imported.text.encode("utf-8")) > resolved_settings.max_source_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail={
                    "code": "expanded_text_too_large",
                    "message": (
                        "The extracted text exceeds the configured source-text limit. "
                        "Split the document before importing it."
                    ),
                },
            )
        return ImportedDocumentResponse(
            filename=imported.filename,
            format=imported.source_format.value,
            text=imported.text,
            metadata=ImportedDocumentMetadataResponse(
                title=imported.title,
                heading_count=len(re.findall(r"(?m)^#{1,6}[ \t]+", imported.text)),
                source_bytes=imported.source_bytes,
            ),
        )

    @application.get("/v1/providers", response_model=list[ProviderResponse], tags=["providers"])
    async def list_providers() -> list[ProviderResponse]:
        return [ProviderResponse.from_info(info) for info in synthesis.providers.list()]

    @application.get("/v1/studio/components", tags=["studio"])
    async def list_components(response: Response) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        return await asyncio.to_thread(components.status, resolved_settings)

    @application.put("/v1/studio/components/engines/{engine_id}", tags=["studio"])
    async def configure_engine_component(
        engine_id: str,
        request: EngineComponentPayload,
    ) -> dict[str, Any]:
        try:
            await asyncio.to_thread(components.save_engine, engine_id, request.python_path)
        except ComponentConfigurationLockedError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ComponentConfigurationError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return await asyncio.to_thread(components.status, resolved_settings)

    @application.delete("/v1/studio/components/engines/{engine_id}", tags=["studio"])
    async def clear_engine_component(engine_id: str) -> dict[str, Any]:
        try:
            await asyncio.to_thread(components.clear_engine, engine_id)
        except ComponentConfigurationLockedError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ComponentConfigurationError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return await asyncio.to_thread(components.status, resolved_settings)

    @application.post("/v1/studio/components/engines/edge/voices/refresh", tags=["studio"])
    async def refresh_edge_voices() -> dict[str, Any]:
        try:
            return await asyncio.to_thread(
                components.refresh_edge_voices,
                resolved_settings,
            )
        except ComponentConfigurationError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @application.get(
        "/v1/studio/projects",
        response_model=list[StudioProjectSummaryResponse],
        tags=["studio"],
    )
    async def list_studio_projects() -> list[StudioProjectSummaryResponse]:
        return [
            StudioProjectSummaryResponse.from_domain(
                project,
                render_plan_count=len(studio.list_render_plans(project.id)),
                take_count=len(studio.list_takes(project.id)),
            )
            for project in studio.list_projects()
        ]

    @application.get(
        "/v1/studio/projects/{project_id}",
        response_model=StudioProjectResponse,
        tags=["studio"],
    )
    async def get_studio_project(project_id: str) -> StudioProjectResponse:
        try:
            project = studio.get_project(project_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Studio project not found") from error
        summary = StudioProjectSummaryResponse.from_domain(
            project,
            render_plan_count=len(studio.list_render_plans(project.id)),
            take_count=len(studio.list_takes(project.id)),
        )
        return StudioProjectResponse(**summary.model_dump(), source_text=project.source_text)

    def require_batch_queue(queue_id: str) -> BatchQueue:
        try:
            return batches.get(queue_id)
        except BatchQueueNotFoundError as error:
            raise HTTPException(status_code=404, detail="Batch queue not found") from error

    @application.get(
        "/v1/studio/batches",
        response_model=list[BatchQueueResponse],
        tags=["studio"],
    )
    async def list_batch_queues(
        response: Response,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[BatchQueueResponse]:
        response.headers["Cache-Control"] = "no-store"
        return [batch_queue_response(queue) for queue in batches.list(limit=limit)]

    @application.post(
        "/v1/studio/batches",
        response_model=BatchQueueResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["studio"],
    )
    async def create_batch_queue(payload: BatchQueueCreateRequest) -> BatchQueueResponse:
        drafts = [freeze_batch_item(item) for item in payload.items]
        queue = await batches.submit(payload.name, drafts)
        return batch_queue_response(queue)

    @application.get(
        "/v1/studio/batches/{queue_id}",
        response_model=BatchQueueResponse,
        tags=["studio"],
    )
    async def get_batch_queue(queue_id: str, response: Response) -> BatchQueueResponse:
        response.headers["Cache-Control"] = "no-store"
        return batch_queue_response(require_batch_queue(queue_id))

    @application.put(
        "/v1/studio/batches/{queue_id}/order",
        response_model=BatchQueueResponse,
        tags=["studio"],
    )
    async def reorder_batch_queue(
        queue_id: str, payload: BatchQueueReorderRequest
    ) -> BatchQueueResponse:
        require_batch_queue(queue_id)
        try:
            queue = batches.reorder(queue_id, payload.item_ids)
        except (InvalidBatchStateError, ValueError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return batch_queue_response(queue)

    @application.delete(
        "/v1/studio/batches/{queue_id}/items/{item_id}",
        response_model=BatchQueueResponse,
        tags=["studio"],
    )
    async def remove_batch_item(queue_id: str, item_id: str) -> BatchQueueResponse:
        require_batch_queue(queue_id)
        try:
            queue = await batches.remove(queue_id, item_id)
        except (InvalidBatchStateError, LookupError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return batch_queue_response(queue)

    @application.post(
        "/v1/studio/batches/{queue_id}/pause-current",
        response_model=BatchQueueResponse,
        tags=["studio"],
    )
    async def pause_current_batch_item(queue_id: str) -> BatchQueueResponse:
        require_batch_queue(queue_id)
        try:
            return batch_queue_response(await batches.pause_current(queue_id))
        except (InvalidBatchStateError, InvalidJobStateError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @application.post(
        "/v1/studio/batches/{queue_id}/pause-remaining",
        response_model=BatchQueueResponse,
        tags=["studio"],
    )
    async def pause_remaining_batch_items(queue_id: str) -> BatchQueueResponse:
        require_batch_queue(queue_id)
        return batch_queue_response(await batches.pause_remaining(queue_id))

    @application.post(
        "/v1/studio/batches/{queue_id}/resume",
        response_model=BatchQueueResponse,
        tags=["studio"],
    )
    async def resume_batch_queue(queue_id: str) -> BatchQueueResponse:
        require_batch_queue(queue_id)
        try:
            return batch_queue_response(await batches.resume(queue_id))
        except (InvalidBatchStateError, InvalidJobStateError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @application.post(
        "/v1/studio/batches/{queue_id}/cancel-current",
        response_model=BatchQueueResponse,
        tags=["studio"],
    )
    async def cancel_current_batch_item(queue_id: str) -> BatchQueueResponse:
        require_batch_queue(queue_id)
        return batch_queue_response(await batches.cancel_current(queue_id))

    @application.post(
        "/v1/studio/batches/{queue_id}/cancel-remaining",
        response_model=BatchQueueResponse,
        tags=["studio"],
    )
    async def cancel_remaining_batch_items(queue_id: str) -> BatchQueueResponse:
        require_batch_queue(queue_id)
        return batch_queue_response(await batches.cancel_remaining(queue_id))

    @application.post(
        "/v1/studio/batches/{queue_id}/cancel",
        response_model=BatchQueueResponse,
        tags=["studio"],
    )
    async def cancel_batch_queue(queue_id: str) -> BatchQueueResponse:
        require_batch_queue(queue_id)
        return batch_queue_response(await batches.cancel_all(queue_id))

    def finished_audio_artifact(
        source_job_id: str, artifact_id: str
    ) -> tuple[Artifact, Path, float]:
        artifact = studio.get_artifact(artifact_id)
        if artifact.kind is not ArtifactKind.AUDIO:
            raise ValueError("the selected artifact is not audio")
        if artifact.metadata.get("source_job_id") != source_job_id:
            raise ValueError("the selected audio artifact does not belong to this take")
        path = Path(artifact.path)
        if not path.is_file():
            raise FileNotFoundError("the selected finished audio file is missing")
        offset_value = artifact.metadata.get("intro_offset", 0.0)
        if isinstance(offset_value, bool) or not isinstance(offset_value, (int, float)):
            raise ValueError("the selected audio artifact has an invalid intro offset")
        offset = float(offset_value)
        if offset < 0:
            raise ValueError("the selected audio artifact has an invalid intro offset")
        return artifact, path, offset

    @application.get(
        "/v1/studio/timeline/takes",
        response_model=list[TimelineTakeResponse],
        tags=["studio"],
    )
    async def list_timeline_takes(
        response: Response,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[TimelineTakeResponse]:
        response.headers["Cache-Control"] = "no-store"
        available: list[TimelineTakeResponse] = []
        completed_finishing: dict[str, list[FinishingJob]] = {}
        for finishing_job in finishing.store.list_jobs(limit=500):
            if (
                finishing_job.status is FinishingJobStatus.COMPLETED
                and finishing_job.artifact_id
                and finishing_job.output_path
                and Path(finishing_job.output_path).is_file()
            ):
                completed_finishing.setdefault(finishing_job.source_job_id, []).append(
                    finishing_job
                )
        for job in synthesis.list_jobs(limit):
            if job.status is not JobStatus.COMPLETED:
                continue
            chunks = synthesis.store.chunks_for_job(job.id)
            if len(chunks) != job.total_chunks or any(
                chunk.status is not ChunkStatus.COMPLETED
                or not chunk.pcm_path
                or not Path(chunk.pcm_path).is_file()
                for chunk in chunks
            ):
                continue
            try:
                synthesis.output_path(job.id)
            except (ValueError, FileNotFoundError):
                continue
            finished_audio: list[TimelineAudioArtifactResponse] = []
            for finishing_job in completed_finishing.get(job.id, []):
                finished_audio.append(
                    TimelineAudioArtifactResponse(
                        id=finishing_job.artifact_id,
                        name=f"Finished {finishing_job.created_at}",
                        intro_offset=finishing_job.intro_offset,
                        duration=finishing_job.output_duration,
                        audio_url=f"/v1/studio/finishing/jobs/{finishing_job.id}/file",
                    )
                )
            available.append(
                TimelineTakeResponse.from_record(
                    job, finished_audio_artifacts=finished_audio
                )
            )
        return available

    @application.get(
        "/v1/studio/timeline/jobs/{job_id}",
        response_model=TimelineResponse,
        tags=["studio"],
    )
    async def get_job_timeline(
        job_id: str,
        response: Response,
        waveform_buckets: int = Query(default=940, ge=1, le=4_000),
        audio_artifact_id: str | None = Query(default=None),
    ) -> TimelineResponse:
        response.headers["Cache-Control"] = "no-store"
        try:
            audio_path = None
            audio_url = None
            offset = 0.0
            if audio_artifact_id:
                artifact, audio_path, offset = finished_audio_artifact(
                    job_id, audio_artifact_id
                )
                finishing_job_id = artifact.metadata.get("finishing_job_id")
                if not isinstance(finishing_job_id, str):
                    raise ValueError("the selected audio artifact has no finishing job")
                audio_url = f"/v1/studio/finishing/jobs/{finishing_job_id}/file"
            timeline = build_job_timeline(
                synthesis.store,
                synthesis.storage,
                job_id,
                waveform_buckets=waveform_buckets,
                audio_path=audio_path,
                audio_url=audio_url,
                offset_seconds=offset,
            )
        except JobNotFoundError as error:
            raise HTTPException(status_code=404, detail="job not found") from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail="audio artifact not found") from error
        except FileNotFoundError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return TimelineResponse.from_domain(timeline)

    @application.get(
        "/v1/studio/timeline/jobs/{job_id}/span",
        tags=["studio"],
    )
    async def get_timeline_span(
        job_id: str,
        start: float = Query(ge=0),
        end: float = Query(gt=0),
        audio_artifact_id: str | None = Query(default=None),
    ) -> Response:
        try:
            path = (
                finished_audio_artifact(job_id, audio_artifact_id)[1]
                if audio_artifact_id
                else synthesis.output_path(job_id)
            )
            payload = wav_span_bytes(path, start, end)
        except JobNotFoundError as error:
            raise HTTPException(status_code=404, detail="job not found") from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail="audio artifact not found") from error
        except (ValueError, FileNotFoundError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return Response(
            payload,
            media_type="audio/wav",
            headers={"Content-Disposition": f'inline; filename="splicr-{job_id}-span.wav"'},
        )

    @application.post(
        "/v1/studio/timeline/jobs/{job_id}/segments/{segment_index}/revise",
        response_model=JobResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["studio"],
    )
    async def revise_timeline_segment(
        job_id: str,
        segment_index: int,
        request: TimelineRevisionRequest,
    ) -> JobResponse:
        try:
            revised = await synthesis.revise_chunk(
                source_job_id=job_id,
                chunk_index=segment_index,
                text=request.text,
            )
        except JobNotFoundError as error:
            raise HTTPException(status_code=404, detail="job not found") from error
        except InvalidJobStateError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except UnknownProviderError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return job_response(revised, take_label="Timeline revision")

    @application.post(
        "/v1/studio/timeline/jobs/{job_id}/segments/{segment_index}/sentences/{sentence_index}/revise",
        response_model=JobResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["studio"],
    )
    async def revise_timeline_sentence(
        job_id: str,
        segment_index: int,
        sentence_index: int,
        request: TimelineSentenceRevisionRequest,
    ) -> JobResponse:
        try:
            revised = await synthesis.revise_sentence(
                source_job_id=job_id,
                chunk_index=segment_index,
                sentence_index=sentence_index,
                text=request.text,
                crossfade_ms=request.crossfade_ms,
            )
        except JobNotFoundError as error:
            raise HTTPException(status_code=404, detail="job not found") from error
        except InvalidJobStateError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except UnknownProviderError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return job_response(revised, take_label="Sentence revision")

    @application.get(
        "/v1/studio/subtitles/jobs/{job_id}",
        response_model=SubtitleTimelineResponse,
        tags=["studio"],
    )
    async def get_subtitle_timeline(
        job_id: str,
        response: Response,
        audio_artifact_id: str | None = Query(default=None),
    ) -> SubtitleTimelineResponse:
        response.headers["Cache-Control"] = "no-store"
        try:
            offset = 0.0
            if audio_artifact_id:
                _, _, offset = finished_audio_artifact(job_id, audio_artifact_id)
            return SubtitleTimelineResponse.from_domain(
                subtitles.timeline(job_id, offset_seconds=offset)
            )
        except JobNotFoundError as error:
            raise HTTPException(status_code=404, detail="job not found") from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail="audio artifact not found") from error
        except FileNotFoundError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @application.post(
        "/v1/studio/subtitles/jobs/{job_id}/export",
        response_model=SubtitleExportResponse,
        tags=["studio"],
    )
    async def export_job_subtitles(
        job_id: str,
        output_format: SubtitleFormat = Query(alias="format"),
        audio_artifact_id: str | None = Query(default=None),
    ) -> SubtitleExportResponse:
        try:
            offset = 0.0
            source_audio_artifact_id = None
            if audio_artifact_id:
                _, _, offset = finished_audio_artifact(job_id, audio_artifact_id)
                source_audio_artifact_id = audio_artifact_id
            return SubtitleExportResponse.from_domain(
                subtitles.export(
                    job_id,
                    output_format,
                    offset_seconds=offset,
                    source_audio_artifact_id=source_audio_artifact_id,
                )
            )
        except JobNotFoundError as error:
            raise HTTPException(status_code=404, detail="job not found") from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail="audio artifact not found") from error
        except FileNotFoundError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @application.get(
        "/v1/studio/subtitles/artifacts/{artifact_id}", tags=["studio"]
    )
    async def get_subtitle_artifact(artifact_id: str) -> FileResponse:
        try:
            artifact = studio.get_artifact(artifact_id)
            path = subtitles.artifact_path(artifact_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="subtitle artifact not found") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return FileResponse(path, media_type=artifact.media_type, filename=path.name)

    @application.get("/v1/studio/finishing/capabilities", tags=["studio"])
    async def get_finishing_capabilities() -> dict[str, object]:
        return {
            "ffmpeg_available": finishing.ffmpeg_available,
            "max_upload_bytes": finishing.max_upload_bytes,
            "supported_extensions": [
                ".aac",
                ".flac",
                ".m4a",
                ".mp3",
                ".ogg",
                ".opus",
                ".wav",
                ".webm",
            ],
            "defaults": FinishingSpecPayload().model_dump(mode="json"),
        }

    @application.get(
        "/v1/studio/finishing/assets",
        response_model=list[FinishingAssetResponse],
        tags=["studio"],
    )
    async def list_finishing_assets(response: Response) -> list[FinishingAssetResponse]:
        response.headers["Cache-Control"] = "no-store"
        return [
            FinishingAssetResponse.from_domain(item)
            for item in finishing.store.list_assets()
        ]

    @application.post(
        "/v1/studio/finishing/assets",
        response_model=FinishingAssetResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["studio"],
    )
    async def upload_finishing_asset(file: UploadFile = File(...)) -> FinishingAssetResponse:
        payload = await file.read(finishing.max_upload_bytes + 1)
        try:
            asset = finishing.register_upload(
                Path(file.filename or "audio").name,
                file.content_type or "application/octet-stream",
                payload,
            )
        except FinishingError as error:
            status_code = (
                status.HTTP_413_CONTENT_TOO_LARGE
                if error.code == "asset_too_large"
                else status.HTTP_422_UNPROCESSABLE_CONTENT
            )
            raise HTTPException(
                status_code=status_code,
                detail={
                    "code": error.code,
                    "message": error.message,
                    "context": error.context,
                },
            ) from error
        return FinishingAssetResponse.from_domain(asset)

    @application.get(
        "/v1/studio/finishing/jobs",
        response_model=list[FinishingJobResponse],
        tags=["studio"],
    )
    async def list_finishing_jobs(
        response: Response,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[FinishingJobResponse]:
        response.headers["Cache-Control"] = "no-store"
        return [
            FinishingJobResponse.from_domain(job)
            for job in finishing.store.list_jobs(limit=limit)
        ]

    @application.post(
        "/v1/studio/finishing/jobs",
        response_model=FinishingJobResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["studio"],
    )
    async def create_finishing_job(
        request: FinishingCreateRequest,
    ) -> FinishingJobResponse:
        try:
            return FinishingJobResponse.from_domain(
                await finishing.submit(request.source_job_id, request.spec.to_domain())
            )
        except JobNotFoundError as error:
            raise HTTPException(status_code=404, detail="source take not found") from error
        except FinishingAssetNotFoundError as error:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "asset_not_found",
                    "message": str(error).strip("'"),
                    "context": {},
                },
            ) from error
        except FinishingError as error:
            error_status = {
                "asset_not_found": status.HTTP_404_NOT_FOUND,
                "asset_missing": status.HTTP_409_CONFLICT,
                "source_missing": status.HTTP_409_CONFLICT,
            }.get(error.code, status.HTTP_503_SERVICE_UNAVAILABLE)
            raise HTTPException(
                status_code=error_status,
                detail={
                    "code": error.code,
                    "message": error.message,
                    "context": error.context,
                },
            ) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @application.get(
        "/v1/studio/finishing/jobs/{job_id}",
        response_model=FinishingJobResponse,
        tags=["studio"],
    )
    async def get_finishing_job(
        job_id: str, response: Response
    ) -> FinishingJobResponse:
        response.headers["Cache-Control"] = "no-store"
        try:
            return FinishingJobResponse.from_domain(finishing.store.get_job(job_id))
        except FinishingJobNotFoundError as error:
            raise HTTPException(status_code=404, detail="finishing job not found") from error

    @application.post(
        "/v1/studio/finishing/jobs/{job_id}/cancel",
        response_model=FinishingJobResponse,
        tags=["studio"],
    )
    async def cancel_finishing_job(job_id: str) -> FinishingJobResponse:
        try:
            return FinishingJobResponse.from_domain(await finishing.cancel(job_id))
        except FinishingJobNotFoundError as error:
            raise HTTPException(status_code=404, detail="finishing job not found") from error
        except InvalidFinishingJobStateError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @application.post(
        "/v1/studio/finishing/jobs/{job_id}/retry",
        response_model=FinishingJobResponse,
        tags=["studio"],
    )
    async def retry_finishing_job(job_id: str) -> FinishingJobResponse:
        try:
            return FinishingJobResponse.from_domain(await finishing.retry(job_id))
        except FinishingJobNotFoundError as error:
            raise HTTPException(status_code=404, detail="finishing job not found") from error
        except InvalidFinishingJobStateError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @application.get("/v1/studio/finishing/jobs/{job_id}/file", tags=["studio"])
    async def get_finishing_file(job_id: str) -> FileResponse:
        try:
            job = finishing.store.get_job(job_id)
            path = finishing.output_for(job_id)
        except FinishingJobNotFoundError as error:
            raise HTTPException(status_code=404, detail="finishing job not found") from error
        except InvalidFinishingJobStateError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return FileResponse(
            path,
            media_type="audio/wav",
            filename=f"splicr-finished-{job.id}.wav",
        )

    @application.get("/v1/studio/audiograms/capabilities", tags=["studio"])
    async def get_audiogram_capabilities() -> dict[str, Any]:
        defaults = AudiogramSpec()
        return {
            "ffmpeg_available": audiograms.ffmpeg_available,
            "preview_seconds": 8,
            "sources": [item.value for item in AudiogramSource],
            "output_formats": [item.value for item in audiograms.supported_output_formats],
            "alpha_output_formats": [
                AudiogramOutputFormat.WEBM_ALPHA.value,
                AudiogramOutputFormat.PRORES_4444.value,
                AudiogramOutputFormat.PNG_SEQUENCE.value,
            ],
            "background_modes": [item.value for item in AudiogramBackgroundMode],
            "background_fits": [item.value for item in AudiogramBackgroundFit],
            "max_background_bytes": audiograms.max_background_bytes,
            "presets": ["ultrafast", "veryfast", "fast", "medium"],
            "waveform_modes": ["cline", "line", "p2p", "point"],
            "amplitude_scales": ["lin", "sqrt", "cbrt", "log"],
            "defaults": AudiogramSpecPayload.model_validate(defaults.to_mapping()).model_dump(
                mode="json"
            ),
            "default_layout": resolve_layout(defaults).to_mapping(),
        }

    @application.get(
        "/v1/studio/audiograms/backgrounds",
        response_model=list[AudiogramBackgroundResponse],
        tags=["studio"],
    )
    async def list_audiogram_backgrounds(
        response: Response,
    ) -> list[AudiogramBackgroundResponse]:
        response.headers["Cache-Control"] = "no-store"
        return [
            AudiogramBackgroundResponse.from_domain(asset)
            for asset in audiograms.background_store.list()
        ]

    @application.post(
        "/v1/studio/audiograms/backgrounds",
        response_model=AudiogramBackgroundResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["studio"],
    )
    async def upload_audiogram_background(
        file: UploadFile = File(...),
    ) -> AudiogramBackgroundResponse:
        payload = await file.read(audiograms.max_background_bytes + 1)
        try:
            asset = audiograms.register_background(
                Path(file.filename or "background").name,
                payload,
            )
        except AudiogramBackgroundError as error:
            raise HTTPException(
                status_code=(
                    status.HTTP_413_CONTENT_TOO_LARGE
                    if error.code == "background_too_large"
                    else status.HTTP_422_UNPROCESSABLE_CONTENT
                ),
                detail={"code": error.code, "message": str(error)},
            ) from error
        return AudiogramBackgroundResponse.from_domain(asset)

    @application.get(
        "/v1/studio/audiograms/backgrounds/{asset_id}/file",
        tags=["studio"],
    )
    async def get_audiogram_background_file(asset_id: str) -> FileResponse:
        try:
            asset = audiograms.background_store.get(asset_id)
            path = audiograms.background_path(asset_id)
        except AudiogramBackgroundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return FileResponse(path, media_type=asset.media_type, filename=asset.name)

    @application.get("/v1/studio/audiograms/sources", tags=["studio"])
    async def list_audiogram_sources(response: Response) -> list[dict[str, Any]]:
        response.headers["Cache-Control"] = "no-store"
        return audiograms.list_sources()

    @application.post("/v1/studio/audiograms/estimate", tags=["studio"])
    async def estimate_audiogram(request: AudiogramCreateRequest) -> dict[str, Any]:
        try:
            source = synthesis.get_job(request.source_job_id)
            source_path = synthesis.output_path(source.id)
            with wave.open(str(source_path), "rb") as wav_file:
                duration = wav_file.getnframes() / wav_file.getframerate()
            spec = request.spec.to_domain()
            if spec.background_mode is AudiogramBackgroundMode.IMAGE:
                audiograms.background_path(spec.background_asset_id or "")
        except JobNotFoundError as error:
            raise HTTPException(status_code=404, detail="source take not found") from error
        except (ValueError, FileNotFoundError, wave.Error) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        render_duration = min(8, duration) if request.kind is AudiogramJobKind.PREVIEW else duration
        return {
            "audio_seconds": render_duration,
            "estimated_render_seconds": estimate_render_seconds(spec, render_duration),
            "layout": resolve_layout(spec).to_mapping(),
        }

    @application.get(
        "/v1/studio/audiograms/jobs",
        response_model=list[AudiogramJobResponse],
        tags=["studio"],
    )
    async def list_audiogram_jobs(
        response: Response,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[AudiogramJobResponse]:
        response.headers["Cache-Control"] = "no-store"
        return [AudiogramJobResponse.from_domain(job) for job in audiograms.store.list(limit=limit)]

    @application.post(
        "/v1/studio/audiograms/jobs",
        response_model=AudiogramJobResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["studio"],
    )
    async def create_audiogram_job(request: AudiogramCreateRequest) -> AudiogramJobResponse:
        try:
            job = await audiograms.submit(
                request.source_job_id,
                request.spec.to_domain(),
                kind=request.kind,
            )
        except JobNotFoundError as error:
            raise HTTPException(status_code=404, detail="source take not found") from error
        except AudiogramRenderError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except FileNotFoundError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return AudiogramJobResponse.from_domain(job)

    @application.get(
        "/v1/studio/audiograms/jobs/{job_id}",
        response_model=AudiogramJobResponse,
        tags=["studio"],
    )
    async def get_audiogram_job(job_id: str, response: Response) -> AudiogramJobResponse:
        response.headers["Cache-Control"] = "no-store"
        try:
            return AudiogramJobResponse.from_domain(audiograms.store.get(job_id))
        except AudiogramJobNotFoundError as error:
            raise HTTPException(status_code=404, detail="audiogram job not found") from error

    @application.post(
        "/v1/studio/audiograms/jobs/{job_id}/cancel",
        response_model=AudiogramJobResponse,
        tags=["studio"],
    )
    async def cancel_audiogram_job(job_id: str) -> AudiogramJobResponse:
        try:
            return AudiogramJobResponse.from_domain(await audiograms.cancel(job_id))
        except AudiogramJobNotFoundError as error:
            raise HTTPException(status_code=404, detail="audiogram job not found") from error
        except InvalidAudiogramJobStateError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @application.post(
        "/v1/studio/audiograms/jobs/{job_id}/retry",
        response_model=AudiogramJobResponse,
        tags=["studio"],
    )
    async def retry_audiogram_job(job_id: str) -> AudiogramJobResponse:
        try:
            return AudiogramJobResponse.from_domain(await audiograms.retry(job_id))
        except AudiogramJobNotFoundError as error:
            raise HTTPException(status_code=404, detail="audiogram job not found") from error
        except InvalidAudiogramJobStateError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @application.get("/v1/studio/audiograms/jobs/{job_id}/file", tags=["studio"])
    async def get_audiogram_file(job_id: str) -> FileResponse:
        try:
            job = audiograms.store.get(job_id)
            path = audiograms.output_for(job_id)
        except AudiogramJobNotFoundError as error:
            raise HTTPException(status_code=404, detail="audiogram job not found") from error
        except InvalidAudiogramJobStateError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except FileNotFoundError as error:
            raise HTTPException(status_code=500, detail=str(error)) from error
        return FileResponse(
            path,
            media_type=audiogram_media_type(job.spec.output_format),
            filename=(
                f"splicr-{job.kind.value}-{job.id}."
                f"{audiogram_output_extension(job.spec.output_format)}"
            ),
        )

    @application.get("/v1/studio/conversions/capabilities", tags=["studio"])
    async def get_conversion_capabilities() -> dict[str, Any]:
        defaults = ConversionSpec()
        return {
            "ffmpeg_available": conversions.ffmpeg_available,
            "output_formats": [item.value for item in AudioOutputFormat],
            "sample_rates": [16_000, 22_050, 24_000, 44_100, 48_000],
            "bit_depths": [16, 24],
            "channels": [0, 1, 2],
            "split_modes": [item.value for item in SplitMode],
            "max_upload_bytes": resolved_settings.max_audio_upload_bytes,
            "defaults": ConversionSpecPayload(**defaults.to_mapping()).model_dump(mode="json"),
        }

    @application.get("/v1/studio/conversions/sources", tags=["studio"])
    async def list_conversion_sources(response: Response) -> list[dict[str, Any]]:
        response.headers["Cache-Control"] = "no-store"
        return conversions.list_sources()

    @application.post(
        "/v1/studio/conversions/inputs",
        response_model=ConversionInputResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["studio"],
    )
    async def upload_conversion_input(file: UploadFile = File(...)) -> ConversionInputResponse:
        filename = Path(file.filename or "audio").name
        upload_root = resolved_settings.data_dir / "studio" / "conversion-inputs"
        upload_root.mkdir(parents=True, exist_ok=True)
        temporary_path = upload_root / f".upload-{uuid4().hex}.part"
        size = 0
        try:
            with temporary_path.open("wb") as stream:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > resolved_settings.max_audio_upload_bytes:
                        raise HTTPException(
                            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                            detail={
                                "code": "audio_file_too_large",
                                "message": (
                                    "Audio exceeds the configured "
                                    f"{resolved_settings.max_audio_upload_bytes}-byte upload limit."
                                ),
                            },
                        )
                    stream.write(chunk)
            if size == 0:
                raise HTTPException(status_code=422, detail="The uploaded audio file is empty")
            try:
                item = conversions.register_upload(
                    original_name=filename,
                    temporary_path=temporary_path,
                    media_type=file.content_type,
                )
            except ValueError as error:
                raise HTTPException(status_code=422, detail=str(error)) from error
            return ConversionInputResponse.from_domain(item)
        finally:
            temporary_path.unlink(missing_ok=True)

    @application.get(
        "/v1/studio/conversions/jobs",
        response_model=list[ConversionJobResponse],
        tags=["studio"],
    )
    async def list_conversion_jobs(
        response: Response,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[ConversionJobResponse]:
        response.headers["Cache-Control"] = "no-store"
        return [ConversionJobResponse.from_domain(job) for job in conversions.store.list(limit=limit)]

    @application.post(
        "/v1/studio/conversions/jobs",
        response_model=ConversionJobResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["studio"],
    )
    async def create_conversion_job(request: ConversionCreateRequest) -> ConversionJobResponse:
        try:
            job = await conversions.submit(
                request.spec.to_domain(),
                source_job_id=request.source_job_id,
                input_id=request.input_id,
            )
        except (JobNotFoundError, ConversionInputNotFoundError) as error:
            raise HTTPException(status_code=404, detail="conversion source not found") from error
        except ConversionError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except FileNotFoundError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return ConversionJobResponse.from_domain(job)

    @application.get(
        "/v1/studio/conversions/jobs/{job_id}",
        response_model=ConversionJobResponse,
        tags=["studio"],
    )
    async def get_conversion_job(job_id: str, response: Response) -> ConversionJobResponse:
        response.headers["Cache-Control"] = "no-store"
        try:
            return ConversionJobResponse.from_domain(conversions.store.get(job_id))
        except ConversionJobNotFoundError as error:
            raise HTTPException(status_code=404, detail="conversion job not found") from error

    @application.post(
        "/v1/studio/conversions/jobs/{job_id}/cancel",
        response_model=ConversionJobResponse,
        tags=["studio"],
    )
    async def cancel_conversion_job(job_id: str) -> ConversionJobResponse:
        try:
            return ConversionJobResponse.from_domain(await conversions.cancel(job_id))
        except ConversionJobNotFoundError as error:
            raise HTTPException(status_code=404, detail="conversion job not found") from error
        except InvalidConversionJobStateError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @application.post(
        "/v1/studio/conversions/jobs/{job_id}/retry",
        response_model=ConversionJobResponse,
        tags=["studio"],
    )
    async def retry_conversion_job(job_id: str) -> ConversionJobResponse:
        try:
            return ConversionJobResponse.from_domain(await conversions.retry(job_id))
        except ConversionJobNotFoundError as error:
            raise HTTPException(status_code=404, detail="conversion job not found") from error
        except InvalidConversionJobStateError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @application.get("/v1/studio/conversions/jobs/{job_id}/file", tags=["studio"])
    async def get_conversion_file(job_id: str) -> FileResponse:
        try:
            job = conversions.store.get(job_id)
            path = conversions.output_for(job_id)
        except ConversionJobNotFoundError as error:
            raise HTTPException(status_code=404, detail="conversion job not found") from error
        except InvalidConversionJobStateError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except FileNotFoundError as error:
            raise HTTPException(status_code=500, detail=str(error)) from error
        return FileResponse(
            path,
            media_type=media_type_for(job.spec.output_format),
            filename=f"{Path(job.source_name).stem}-converted.{job.spec.output_format.value}",
        )

    @application.get(
        "/v1/studio/conversions/jobs/{job_id}/parts/{part_index}", tags=["studio"]
    )
    async def get_conversion_part(job_id: str, part_index: int) -> FileResponse:
        try:
            job = conversions.store.get(job_id)
            path = conversions.output_for(job_id, part_index)
        except ConversionJobNotFoundError as error:
            raise HTTPException(status_code=404, detail="conversion job not found") from error
        except InvalidConversionJobStateError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return FileResponse(
            path,
            media_type=media_type_for(job.spec.output_format),
            filename=f"{Path(job.source_name).stem}-{part_index + 1:03d}.{job.spec.output_format.value}",
        )

    @application.get("/v1/studio/transcriptions/capabilities", tags=["studio"])
    async def get_transcription_capabilities(response: Response) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        return {
            "providers": transcriptions.capabilities(),
            "defaults": TranscriptionOptionsPayload().model_dump(mode="json"),
            "max_upload_bytes": resolved_settings.max_audio_upload_bytes,
        }

    @application.get("/v1/studio/transcriptions/sources", tags=["studio"])
    async def list_transcription_sources(response: Response) -> list[dict[str, Any]]:
        response.headers["Cache-Control"] = "no-store"
        return conversions.list_sources()

    @application.get(
        "/v1/studio/transcriptions/jobs",
        response_model=list[TranscriptionJobResponse],
        tags=["studio"],
    )
    async def list_transcription_jobs(
        response: Response,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[TranscriptionJobResponse]:
        response.headers["Cache-Control"] = "no-store"
        return [
            TranscriptionJobResponse.from_domain(job)
            for job in transcriptions.store.list(limit=limit)
        ]

    @application.post(
        "/v1/studio/transcriptions/jobs",
        response_model=TranscriptionJobResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["studio"],
    )
    async def create_transcription_job(
        request: TranscriptionCreateRequest,
    ) -> TranscriptionJobResponse:
        try:
            job = await transcriptions.submit(
                provider_id=request.provider_id,
                options=request.options.to_domain(),
                source_job_id=request.source_job_id,
                input_id=request.input_id,
            )
        except (JobNotFoundError, ConversionInputNotFoundError) as error:
            raise HTTPException(status_code=404, detail="transcription source not found") from error
        except TranscriptionProviderError as error:
            raise HTTPException(status_code=503, detail=error.detail) from error
        except FileNotFoundError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return TranscriptionJobResponse.from_domain(job)

    @application.get(
        "/v1/studio/transcriptions/jobs/{job_id}",
        response_model=TranscriptionJobResponse,
        tags=["studio"],
    )
    async def get_transcription_job(
        job_id: str, response: Response
    ) -> TranscriptionJobResponse:
        response.headers["Cache-Control"] = "no-store"
        try:
            return TranscriptionJobResponse.from_domain(transcriptions.store.get(job_id))
        except TranscriptionJobNotFoundError as error:
            raise HTTPException(status_code=404, detail="transcription job not found") from error

    @application.post(
        "/v1/studio/transcriptions/jobs/{job_id}/cancel",
        response_model=TranscriptionJobResponse,
        tags=["studio"],
    )
    async def cancel_transcription_job(job_id: str) -> TranscriptionJobResponse:
        try:
            return TranscriptionJobResponse.from_domain(await transcriptions.cancel(job_id))
        except TranscriptionJobNotFoundError as error:
            raise HTTPException(status_code=404, detail="transcription job not found") from error
        except InvalidTranscriptionJobStateError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @application.post(
        "/v1/studio/transcriptions/jobs/{job_id}/retry",
        response_model=TranscriptionJobResponse,
        tags=["studio"],
    )
    async def retry_transcription_job(job_id: str) -> TranscriptionJobResponse:
        try:
            return TranscriptionJobResponse.from_domain(await transcriptions.retry(job_id))
        except TranscriptionJobNotFoundError as error:
            raise HTTPException(status_code=404, detail="transcription job not found") from error
        except InvalidTranscriptionJobStateError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @application.get(
        "/v1/studio/transcriptions/jobs/{job_id}/files/{output_name}", tags=["studio"]
    )
    async def get_transcription_file(job_id: str, output_name: str) -> FileResponse:
        media_types = {
            "transcript": "text/markdown",
            "segments": "application/json",
            "srt": "application/x-subrip",
            "vtt": "text/vtt",
            "chapters": "text/plain",
        }
        if output_name not in media_types:
            raise HTTPException(status_code=404, detail="transcription output not found")
        try:
            job = transcriptions.store.get(job_id)
            path = transcriptions.output_for(job_id, output_name)
        except TranscriptionJobNotFoundError as error:
            raise HTTPException(status_code=404, detail="transcription job not found") from error
        except InvalidTranscriptionJobStateError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(job.source_name).stem).strip("-.")
        return FileResponse(
            path,
            media_type=media_types[output_name],
            filename=f"{safe_stem or 'transcription'}-{path.name}",
        )

    @application.get(
        "/v1/studio/publishing/channel",
        response_model=PodcastChannelPayload,
        tags=["studio"],
    )
    def get_podcast_channel(response: Response) -> PodcastChannelPayload:
        response.headers["Cache-Control"] = "no-store"
        return PodcastChannelPayload.from_domain(publishing.store.get_channel())

    @application.put(
        "/v1/studio/publishing/channel",
        response_model=PodcastChannelPayload,
        tags=["studio"],
    )
    def update_podcast_channel(payload: PodcastChannelPayload) -> PodcastChannelPayload:
        try:
            channel = publishing.store.save_channel(payload.to_domain())
            publishing.rebuild_feed()
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return PodcastChannelPayload.from_domain(channel)

    @application.get("/v1/studio/publishing/sources", tags=["studio"])
    def list_publishing_sources(response: Response) -> list[dict[str, object]]:
        response.headers["Cache-Control"] = "no-store"
        return publishing.list_sources()

    @application.get(
        "/v1/studio/publishing/takes/{take_id}/chapters",
        response_model=list[ChapterCueResponse],
        tags=["studio"],
    )
    def preview_publishing_chapters(
        take_id: str,
        response: Response,
        audio_artifact_id: str | None = Query(default=None),
    ) -> list[ChapterCueResponse]:
        response.headers["Cache-Control"] = "no-store"
        try:
            return [
                ChapterCueResponse.from_domain(cue)
                for cue in publishing.preview_chapters(
                    take_id, audio_artifact_id=audio_artifact_id
                )
            ]
        except KeyError as error:
            raise HTTPException(status_code=404, detail="publishing source not found") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @application.post("/v1/studio/publishing/takes/{take_id}/transcript", tags=["studio"])
    def export_publishing_transcript(take_id: str) -> dict[str, object]:
        try:
            artifact = publishing.export_transcript(take_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="publishing source not found") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return {
            "artifact_id": artifact.id,
            "size_bytes": artifact.size_bytes,
            "download_url": f"/v1/studio/publishing/artifacts/{artifact.id}",
        }

    @application.post(
        "/v1/studio/publishing/takes/{take_id}/subtitles",
        response_model=SubtitleExportResponse,
        tags=["studio"],
    )
    def export_publishing_subtitles(
        take_id: str,
        output_format: SubtitleFormat = Query(alias="format"),
        audio_artifact_id: str | None = Query(default=None),
    ) -> SubtitleExportResponse:
        try:
            offset = 0.0
            if audio_artifact_id:
                artifact = studio.get_artifact(audio_artifact_id)
                if artifact.take_id != take_id or artifact.kind is not ArtifactKind.AUDIO:
                    raise ValueError("the selected audio artifact does not belong to this take")
                if not Path(artifact.path).is_file():
                    raise FileNotFoundError("the selected audio artifact is missing")
                offset_value = artifact.metadata.get("intro_offset", 0.0)
                if isinstance(offset_value, bool) or not isinstance(
                    offset_value, (int, float)
                ):
                    raise ValueError("the selected audio artifact has an invalid intro offset")
                offset = float(offset_value)
            return SubtitleExportResponse.from_domain(
                subtitles.export_take(
                    take_id,
                    output_format,
                    offset_seconds=offset,
                    source_audio_artifact_id=audio_artifact_id,
                )
            )
        except (KeyError, JobNotFoundError) as error:
            raise HTTPException(status_code=404, detail="publishing source not found") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except FileNotFoundError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @application.get(
        "/v1/studio/publishing/episodes",
        response_model=list[PublishedEpisodeResponse],
        tags=["studio"],
    )
    def list_published_episodes(response: Response) -> list[PublishedEpisodeResponse]:
        response.headers["Cache-Control"] = "no-store"
        return [
            PublishedEpisodeResponse.from_domain(episode)
            for episode in publishing.store.list_episodes()
        ]

    @application.post(
        "/v1/studio/publishing/episodes",
        response_model=PublishedEpisodeResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["studio"],
    )
    def publish_podcast_episode(payload: PublishEpisodeRequest) -> PublishedEpisodeResponse:
        try:
            episode = publishing.publish_episode(
                take_id=payload.take_id,
                audio_artifact_id=payload.audio_artifact_id,
                title=payload.title,
                description=payload.description,
                publication_date=payload.publication_date,
                episode_number=payload.episode_number,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="publishing source not found") from error
        except FileNotFoundError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return PublishedEpisodeResponse.from_domain(episode)

    @application.get("/v1/studio/publishing/feed", tags=["studio"])
    def get_podcast_feed() -> FileResponse:
        path = publishing.rebuild_feed()
        return FileResponse(path, media_type="application/rss+xml", filename="podcast.xml")

    @application.get(
        "/v1/studio/publishing/episodes/{episode_id}/media", tags=["studio"]
    )
    def get_published_episode_media(episode_id: str) -> FileResponse:
        try:
            episode = publishing.store.get_episode(episode_id)
            path = publishing.episode_media_path(episode_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="published episode not found") from error
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return FileResponse(path, media_type=episode.media_type, filename=path.name)

    @application.get(
        "/v1/studio/publishing/artifacts/{artifact_id}", tags=["studio"]
    )
    def get_publishing_artifact(artifact_id: str) -> FileResponse:
        try:
            artifact = studio.get_artifact(artifact_id)
            path = publishing.artifact_path(artifact_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="publishing artifact not found") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return FileResponse(path, media_type=artifact.media_type, filename=path.name)

    @application.get(
        "/v1/studio/voices",
        response_model=list[VoiceProfileResponse],
        tags=["studio"],
    )
    def list_voice_profiles(
        engine_id: str | None = Query(default=None, max_length=100),
    ) -> list[VoiceProfileResponse]:
        return [
            VoiceProfileResponse.from_domain(profile)
            for profile in studio.list_voice_profiles(engine_id)
        ]

    @application.get(
        "/v1/studio/voice-design/jobs",
        response_model=list[VoiceDesignJobResponse],
        tags=["studio"],
    )
    def list_voice_design_jobs(
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[VoiceDesignJobResponse]:
        return [voice_design_response(job) for job in voice_designs.store.list(limit)]

    @application.post(
        "/v1/studio/voice-design/jobs",
        response_model=VoiceDesignJobResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["studio"],
    )
    async def create_voice_design_job(
        payload: VoiceDesignCreatePayload,
    ) -> VoiceDesignJobResponse:
        try:
            job = await voice_designs.submit(
                label=payload.label,
                description=payload.description,
                take=payload.take,
            )
        except VoiceDesignUnavailableError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return voice_design_response(job)

    @application.get(
        "/v1/studio/voice-design/jobs/{job_id}",
        response_model=VoiceDesignJobResponse,
        tags=["studio"],
    )
    def get_voice_design_job(job_id: str) -> VoiceDesignJobResponse:
        try:
            return voice_design_response(voice_designs.store.get(job_id))
        except VoiceDesignJobNotFoundError as error:
            raise HTTPException(status_code=404, detail="Voice design job not found") from error

    @application.post(
        "/v1/studio/voice-design/jobs/{job_id}/retry",
        response_model=VoiceDesignJobResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["studio"],
    )
    async def retry_voice_design_job(job_id: str) -> VoiceDesignJobResponse:
        try:
            return voice_design_response(await voice_designs.retry(job_id))
        except VoiceDesignJobNotFoundError as error:
            raise HTTPException(status_code=404, detail="Voice design job not found") from error
        except (InvalidVoiceDesignJobStateError, VoiceDesignUnavailableError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @application.post(
        "/v1/studio/voice-design/jobs/{job_id}/cancel",
        response_model=VoiceDesignJobResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["studio"],
    )
    async def cancel_voice_design_job(job_id: str) -> VoiceDesignJobResponse:
        try:
            return voice_design_response(await voice_designs.cancel(job_id))
        except VoiceDesignJobNotFoundError as error:
            raise HTTPException(status_code=404, detail="Voice design job not found") from error
        except InvalidVoiceDesignJobStateError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @application.post(
        "/v1/studio/voices/reference",
        response_model=VoiceProfileResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["studio"],
    )
    def create_reference_voice(
        file: UploadFile = File(...),
        label: str = Form(..., min_length=1, max_length=200),
        engine_id: str = Form(..., min_length=1, max_length=100),
        reference_text: str = Form(default="", max_length=20_000),
        description: str = Form(default="", max_length=2_000),
        kind: VoiceProfileKind = Form(default=VoiceProfileKind.CLONED),
    ) -> VoiceProfileResponse:
        if kind not in {VoiceProfileKind.CLONED, VoiceProfileKind.DESIGNED}:
            raise HTTPException(status_code=422, detail="Reference audio must be cloned or designed")
        if kind is VoiceProfileKind.CLONED and not reference_text.strip():
            raise HTTPException(
                status_code=422,
                detail="A cloned voice needs the exact words spoken in the recording",
            )
        filename = Path(file.filename or "reference.wav").name
        if Path(filename).suffix.casefold() != ".wav":
            raise HTTPException(status_code=422, detail="Reference recordings must be WAV files")

        profile_id = uuid4().hex
        directory = managed_voice_root / profile_id
        target = directory / "reference.wav"
        directory.mkdir(parents=True, exist_ok=False)
        size = 0
        try:
            with target.open("wb") as output:
                while block := file.file.read(1024 * 1024):
                    size += len(block)
                    if size > resolved_settings.max_upload_bytes:
                        raise HTTPException(
                            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                            detail=(
                                "Reference recording exceeds the configured "
                                f"{resolved_settings.max_upload_bytes}-byte upload limit"
                            ),
                        )
                    output.write(block)
            try:
                with wave.open(str(target), "rb") as recording:
                    channels = recording.getnchannels()
                    sample_rate = recording.getframerate()
                    sample_width = recording.getsampwidth()
                    frames = recording.getnframes()
                    compression = recording.getcomptype()
            except (OSError, EOFError, wave.Error) as error:
                raise HTTPException(status_code=422, detail="The upload is not a readable WAV file") from error
            if compression != "NONE" or channels < 1 or sample_rate < 1 or sample_width < 1:
                raise HTTPException(status_code=422, detail="The WAV must contain uncompressed PCM audio")
            seconds = frames / sample_rate
            minimum_seconds = 3.0 if engine_id.strip().casefold() == "audio8" else 2.0
            if kind is VoiceProfileKind.CLONED and seconds < minimum_seconds:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"The recording is {seconds:.1f}s; {engine_id.strip()} cloning "
                        f"needs at least {minimum_seconds:g}s of clear speech"
                    ),
                )
            profile = studio.save_voice_profile(
                VoiceProfile(
                    id=profile_id,
                    label=label.strip(),
                    engine_id=engine_id.strip(),
                    kind=kind,
                    description=description.strip(),
                    reference_audio_path=str(target),
                    reference_text=reference_text.strip() or None,
                    metadata={
                        "managed": True,
                        "source_filename": filename,
                        "size_bytes": size,
                        "seconds": round(seconds, 3),
                        "sample_rate": sample_rate,
                        "channels": channels,
                        "sample_width": sample_width,
                    },
                )
            )
        except Exception:
            shutil.rmtree(directory, ignore_errors=True)
            raise
        return VoiceProfileResponse.from_domain(profile)

    @application.post(
        "/v1/studio/voices/presets",
        response_model=VoiceProfileResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["studio"],
    )
    def create_voice_preset(payload: VoicePresetPayload) -> VoiceProfileResponse:
        profile = studio.save_voice_profile(
            VoiceProfile(
                id=uuid4().hex,
                label=payload.label.strip(),
                engine_id=payload.engine_id.strip(),
                kind=VoiceProfileKind.PRESET,
                description=payload.description.strip(),
                settings={
                    "voice_id": payload.voice_id.strip(),
                    "instructions": payload.instructions.strip(),
                },
                metadata={"managed": True},
            )
        )
        return VoiceProfileResponse.from_domain(profile)

    @application.put(
        "/v1/studio/voices/{profile_id}",
        response_model=VoiceProfileResponse,
        tags=["studio"],
    )
    def update_voice_profile(
        profile_id: str,
        payload: VoiceProfileUpdatePayload,
    ) -> VoiceProfileResponse:
        profile = require_voice_profile(profile_id)
        changed = studio.save_voice_profile(
            replace(
                profile,
                label=payload.label.strip(),
                description=payload.description.strip(),
                updated_at=utc_now(),
            )
        )
        return VoiceProfileResponse.from_domain(changed)

    @application.get("/v1/studio/voices/{profile_id}/reference", tags=["studio"])
    def get_voice_reference(profile_id: str) -> FileResponse:
        profile = require_voice_profile(profile_id)
        if not profile.reference_audio_path:
            raise HTTPException(status_code=404, detail="This voice has no reference recording")
        path = Path(profile.reference_audio_path)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="The reference recording is unavailable")
        return FileResponse(path, media_type="audio/wav", filename=f"{profile.label}.wav")

    @application.delete("/v1/studio/voices/{profile_id}", status_code=204, tags=["studio"])
    def delete_voice_profile(profile_id: str) -> Response:
        profile = require_voice_profile(profile_id)
        studio.delete_voice_profile(profile_id)
        if directory := managed_voice_directory(profile):
            shutil.rmtree(directory, ignore_errors=True)
        return Response(status_code=204)

    @application.get(
        "/v1/chat-resources",
        response_model=list[ChatResourceResponse],
        tags=["chat resources"],
    )
    async def list_chat_resources() -> list[ChatResourceResponse]:
        return [_chat_resource_response(stored, chat_resources) for stored in chat_resources.list()]

    @application.post(
        "/v1/chat-resources",
        response_model=ChatResourceResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["chat resources"],
    )
    async def create_chat_resource(payload: ChatResourcePayload) -> ChatResourceResponse:
        try:
            spec = _chat_resource_spec_from_payload(payload)
            stored = chat_resources.create(spec)
            if payload.api_key:
                chat_resources.set_api_key(spec.resource_id, payload.api_key)
        except ChatResourceConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except SecretVaultUnavailableError as error:
            raise secure_storage_error(error) from error
        except (KeyError, TypeError, ValueError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return _chat_resource_response(stored, chat_resources)

    @application.get(
        "/v1/chat-resources/{resource_id}",
        response_model=ChatResourceResponse,
        tags=["chat resources"],
    )
    async def get_chat_resource(resource_id: str) -> ChatResourceResponse:
        try:
            stored = chat_resources.get_current(resource_id)
        except ChatResourceNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return _chat_resource_response(stored, chat_resources)

    @application.put(
        "/v1/chat-resources/{resource_id}",
        response_model=ChatResourceResponse,
        tags=["chat resources"],
    )
    async def update_chat_resource(
        resource_id: str,
        payload: ChatResourcePayload,
    ) -> ChatResourceResponse:
        if payload.resource_id != resource_id:
            raise HTTPException(status_code=422, detail="resource id cannot be changed")
        try:
            current = chat_resources.get_current(resource_id)
            expected_revision = payload.revision or current.spec.revision
            replacement = _chat_resource_spec_from_payload(payload, current.spec)
            stored = chat_resources.update(
                resource_id,
                replacement,
                expected_revision=expected_revision,
            )
            if payload.clear_api_key:
                chat_resources.clear_api_key(resource_id)
            elif payload.api_key:
                chat_resources.set_api_key(resource_id, payload.api_key)
        except ChatResourceNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ChatResourceConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except SecretVaultUnavailableError as error:
            raise secure_storage_error(error) from error
        except (KeyError, TypeError, ValueError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return _chat_resource_response(stored, chat_resources)

    @application.delete(
        "/v1/chat-resources/{resource_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["chat resources"],
    )
    async def delete_chat_resource(resource_id: str) -> Response:
        try:
            chat_resources.soft_delete(resource_id)
        except ChatResourceNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ChatResourceConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except SecretVaultUnavailableError as error:
            raise secure_storage_error(error) from error
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @application.post(
        "/v1/chat-resources/{resource_id}/verify",
        response_model=ChatResourceVerificationResponse,
        tags=["chat resources"],
    )
    async def verify_chat_resource(
        resource_id: str,
        model: str | None = Query(default=None, max_length=255),
    ) -> ChatResourceVerificationResponse:
        try:
            completer, selected_model = configured_chat(resource_id, model)
            async with completer:
                await completer.complete(
                    [{"role": "user", "content": "Reply with exactly: ready"}],
                    model=selected_model,
                    temperature=0,
                    max_tokens=16,
                )
        except ChatResourceNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except SecretVaultUnavailableError as error:
            raise secure_storage_error(error) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except ChatCompletionError as error:
            raise chat_provider_error(error) from error
        return ChatResourceVerificationResponse(
            ok=True,
            detail="Connection succeeded.",
            resource_id=resource_id,
            model=selected_model,
        )

    @application.post(
        "/v1/studio/dialogue/script-jobs",
        response_model=DialogueScriptJobResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["studio"],
    )
    async def create_dialogue_script_job(
        payload: DialogueGenerateRequest,
    ) -> DialogueScriptJobResponse:
        try:
            stored = chat_resources.get_current(payload.chat_resource_id)
            selected_model = (payload.model or stored.spec.default_model).strip()
            stored.spec.runtime(model=selected_model)
            chat_resources.resolve_api_key(payload.chat_resource_id)
            job = await dialogue_scripts.create(
                DialogueScriptJobRequest(
                    chat_resource_id=stored.spec.resource_id,
                    resource_revision=stored.spec.revision,
                    model=selected_model,
                    text=payload.text,
                    options=payload.options.to_domain(),
                )
            )
        except ChatResourceNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except SecretVaultUnavailableError as error:
            raise secure_storage_error(error) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return dialogue_script_job_response(job)

    @application.get(
        "/v1/studio/dialogue/script-jobs",
        response_model=list[DialogueScriptJobResponse],
        tags=["studio"],
    )
    async def list_dialogue_script_jobs(
        limit: int = Query(default=50, ge=1, le=200),
    ) -> list[DialogueScriptJobResponse]:
        return [
            dialogue_script_job_response(job)
            for job in dialogue_scripts.store.list(limit=limit)
        ]

    @application.get(
        "/v1/studio/dialogue/script-jobs/{job_id}",
        response_model=DialogueScriptJobResponse,
        tags=["studio"],
    )
    async def get_dialogue_script_job(job_id: str) -> DialogueScriptJobResponse:
        try:
            job = dialogue_scripts.store.get(job_id)
        except DialogueScriptJobNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return dialogue_script_job_response(job)

    @application.post(
        "/v1/studio/dialogue/script-jobs/{job_id}/cancel",
        response_model=DialogueScriptJobResponse,
        tags=["studio"],
    )
    async def cancel_dialogue_script_job(job_id: str) -> DialogueScriptJobResponse:
        try:
            job = await dialogue_scripts.cancel(job_id)
        except DialogueScriptJobNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except InvalidDialogueScriptJobStateError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return dialogue_script_job_response(job)

    @application.post(
        "/v1/studio/dialogue/script-jobs/{job_id}/resume",
        response_model=DialogueScriptJobResponse,
        tags=["studio"],
    )
    async def resume_dialogue_script_job(job_id: str) -> DialogueScriptJobResponse:
        try:
            job = await dialogue_scripts.resume(job_id)
        except DialogueScriptJobNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except InvalidDialogueScriptJobStateError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return dialogue_script_job_response(job)

    @application.post(
        "/v1/studio/dialogue/generate",
        response_model=DialogueScriptResponse,
        tags=["studio"],
    )
    async def generate_dialogue_script(
        payload: DialogueGenerateRequest,
    ) -> DialogueScriptResponse:
        progress_messages: list[str] = []
        try:
            completer, selected_model = configured_chat(
                payload.chat_resource_id,
                payload.model,
            )
            async with completer:
                script = await generate_script(
                    payload.text,
                    completer,
                    options=payload.options.to_domain(),
                    model=selected_model,
                    progress=progress_messages.append,
                )
        except ChatResourceNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except SecretVaultUnavailableError as error:
            raise secure_storage_error(error) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except (ChatCompletionError, DialogueGenerationError) as error:
            raise chat_provider_error(error) from error
        return dialogue_script_response(script, progress_messages)

    @application.post(
        "/v1/studio/dialogue/refine",
        response_model=DialogueRefineResponse,
        tags=["studio"],
    )
    async def refine_dialogue_selection(
        payload: DialogueRefineRequest,
    ) -> DialogueRefineResponse:
        neighbor_before = (
            GeneratedDialogueTurn(
                speaker=payload.neighbor_before.speaker,
                text=payload.neighbor_before.text,
            )
            if payload.neighbor_before is not None
            else None
        )
        neighbor_after = (
            GeneratedDialogueTurn(
                speaker=payload.neighbor_after.speaker,
                text=payload.neighbor_after.text,
            )
            if payload.neighbor_after is not None
            else None
        )
        try:
            completer, selected_model = configured_chat(
                payload.chat_resource_id,
                payload.model,
            )
            async with completer:
                replacement = await refine_selection(
                    before=payload.before,
                    selected=payload.selected,
                    after=payload.after,
                    instruction=payload.instruction,
                    speaker=payload.speaker,
                    completer=completer,
                    model=selected_model,
                    neighbor_before=neighbor_before,
                    neighbor_after=neighbor_after,
                )
        except ChatResourceNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except SecretVaultUnavailableError as error:
            raise secure_storage_error(error) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except (ChatCompletionError, DialogueGenerationError) as error:
            raise chat_provider_error(error) from error
        return DialogueRefineResponse(replacement=replacement)

    @application.get("/v1/api-resources", tags=["API resources"])
    async def list_api_resources() -> list[dict[str, Any]]:
        store = require_resource_store()
        infos = {info.name: info for info in synthesis.providers.list()}
        builtin_order = {"gemini": 0, "deepgram": 1, "inworld": 2}
        specs = sorted(
            store.list(),
            key=lambda spec: (
                builtin_order.get(spec.resource_id, len(builtin_order)),
                spec.name.casefold(),
                spec.resource_id,
            ),
        )
        return [_resource_response(spec, store, infos.get(spec.resource_id)) for spec in specs]

    @application.post(
        "/v1/api-resources",
        status_code=status.HTTP_201_CREATED,
        tags=["API resources"],
    )
    async def create_api_resource(payload: ApiResourcePayload) -> dict[str, Any]:
        store = require_resource_store()
        try:
            spec = _resource_spec_from_payload(payload)
            stored = store.create(spec, api_key=(payload.api_key or None))
        except ApiResourceConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except SecretVaultUnavailableError as error:
            raise secure_storage_error(error) from error
        except (KeyError, TypeError, ValueError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return _resource_response(stored, store, provider_info_for(stored.resource_id))

    @application.get("/v1/api-resources/{resource_id}", tags=["API resources"])
    async def get_api_resource(
        resource_id: str,
        revision: int | None = Query(default=None, ge=1),
    ) -> dict[str, Any]:
        store = require_resource_store()
        spec = (
            store.get(resource_id, revision)
            if revision is not None
            else store.get_current(resource_id)
        )
        if spec is None:
            raise HTTPException(status_code=404, detail="API resource not found")
        info = provider_info_for(spec.resource_id) if revision is None else None
        return _resource_response(spec, store, info)

    @application.put("/v1/api-resources/{resource_id}", tags=["API resources"])
    async def update_api_resource(
        resource_id: str,
        payload: ApiResourcePayload,
    ) -> dict[str, Any]:
        store = require_resource_store()
        current = store.get_current(resource_id)
        if current is None:
            raise HTTPException(status_code=404, detail="API resource not found")
        if payload.selected_id is not None and payload.selected_id != resource_id:
            raise HTTPException(status_code=422, detail="resource id cannot be changed")
        if payload.revision is not None and payload.revision != current.revision:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"API resource revision changed from {payload.revision} to "
                    f"{current.revision}; reopen the editor before saving"
                ),
            )
        try:
            replacement = _resource_spec_from_payload(payload, current)
            key_update: Any = API_KEY_UNCHANGED
            if payload.clear_api_key:
                key_update = None
            elif payload.api_key:
                key_update = payload.api_key
            stored = store.update(resource_id, replacement, api_key=key_update)
        except ApiResourceNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except SecretVaultUnavailableError as error:
            raise secure_storage_error(error) from error
        except (KeyError, TypeError, ValueError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if payload.clear_api_key or payload.api_key:
            await invalidate_resource(resource_id)
        return _resource_response(stored, store, provider_info_for(stored.resource_id))

    @application.delete(
        "/v1/api-resources/{resource_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["API resources"],
    )
    async def delete_api_resource(resource_id: str) -> Response:
        store = require_resource_store()
        if not store.soft_delete(resource_id, delete_secret=False):
            raise HTTPException(status_code=404, detail="API resource not found")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @application.get("/v1/speech/error-codes", tags=["speech jobs"])
    async def list_error_codes() -> list[dict[str, str]]:
        return [{"code": code.value, "suggestion": suggestion_for(code)} for code in JobErrorCode]

    @application.get(
        "/v1/errors",
        response_model=ErrorEventListResponse,
        tags=["error reporting"],
    )
    async def list_errors(
        after: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=500),
        unread_only: bool = Query(default=False),
    ) -> ErrorEventListResponse:
        events = synthesis.store.list_error_events(
            after_sequence=after,
            limit=limit,
            unread_only=unread_only,
        )
        unread_count, total_count = synthesis.store.error_event_counts()
        return ErrorEventListResponse(
            events=[ErrorEventBriefResponse.from_record(event) for event in events],
            unread_count=unread_count,
            total_count=total_count,
        )

    @application.post(
        "/v1/errors/client",
        response_model=ErrorEventResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["error reporting"],
    )
    async def report_client_error(payload: ClientErrorReport) -> ErrorEventResponse:
        raw = payload.model_dump(mode="json")
        if len(json.dumps(raw, ensure_ascii=False).encode("utf-8")) > 512_000:
            raise HTTPException(status_code=413, detail="client error report is too large")
        known_secrets = known_provider_secrets()
        safe_message_value = sanitize_diagnostic(payload.message, known_secrets=known_secrets)
        safe_message = str(safe_message_value or "Browser request failed")
        safe_endpoint = (
            sanitize_url(payload.endpoint, known_secrets=known_secrets)
            if payload.endpoint is not None
            else None
        )
        safe_code = str(sanitize_diagnostic(payload.code, known_secrets=known_secrets))
        safe_category = str(
            sanitize_diagnostic(payload.category or "client", known_secrets=known_secrets)
        )
        safe_method = (
            str(sanitize_diagnostic(payload.method, known_secrets=known_secrets)).upper()
            if payload.method
            else None
        )
        safe_provider = (
            str(sanitize_diagnostic(payload.provider, known_secrets=known_secrets))
            if payload.provider
            else None
        )
        safe_job_id = (
            str(sanitize_diagnostic(payload.job_id, known_secrets=known_secrets))
            if payload.job_id
            else None
        )
        identifying = {
            "source": "browser",
            "code": safe_code,
            "category": safe_category,
            "message": safe_message,
            "status_code": payload.status_code,
            "method": safe_method,
            "endpoint": safe_endpoint,
            "provider": safe_provider,
            "resource_revision": payload.resource_revision,
            "job_id": safe_job_id,
            "chunk_index": payload.chunk_index,
        }
        event = synthesis.store.record_error_event(
            ErrorEventDraft(
                fingerprint=_client_error_fingerprint(identifying),
                source="browser",
                severity=payload.severity,
                code=safe_code,
                category=safe_category,
                message=safe_message,
                retryable=payload.retryable,
                status_code=payload.status_code,
                method=safe_method,
                endpoint=safe_endpoint,
                request=_sanitized_error_mapping(payload.request, known_secrets=known_secrets),
                response=_sanitized_error_mapping(payload.response, known_secrets=known_secrets),
                exception=_sanitized_error_mapping(payload.exception, known_secrets=known_secrets),
                context=_sanitized_error_mapping(payload.context, known_secrets=known_secrets),
                provider=safe_provider,
                resource_revision=payload.resource_revision,
                job_id=safe_job_id,
                chunk_index=payload.chunk_index,
                attempt=payload.attempt,
            )
        )
        return ErrorEventResponse.from_record(event)

    @application.post("/v1/errors/read-all", tags=["error reporting"])
    async def mark_all_errors_read() -> dict[str, int]:
        changed = synthesis.store.mark_all_error_events_read()
        unread_count, total_count = synthesis.store.error_event_counts()
        return {"changed": changed, "unread_count": unread_count, "total_count": total_count}

    @application.post(
        "/v1/errors/{event_id}/read",
        response_model=ErrorEventResponse,
        tags=["error reporting"],
    )
    async def mark_error_read(event_id: str) -> ErrorEventResponse:
        event = synthesis.store.mark_error_event_read(event_id)
        if event is None:
            raise HTTPException(status_code=404, detail="error event not found")
        return ErrorEventResponse.from_record(event)

    @application.get(
        "/v1/errors/{event_id}",
        response_model=ErrorEventResponse,
        tags=["error reporting"],
    )
    async def get_error(event_id: str) -> ErrorEventResponse:
        event = synthesis.store.get_error_event(event_id)
        if event is None:
            raise HTTPException(status_code=404, detail="error event not found")
        return ErrorEventResponse.from_record(event)

    @application.delete("/v1/errors", tags=["error reporting"])
    async def clear_errors(
        scope: Literal["read", "all"] = Query(default="read"),
    ) -> dict[str, int]:
        deleted = synthesis.store.clear_error_events(scope)
        unread_count, total_count = synthesis.store.error_event_counts()
        return {"deleted": deleted, "unread_count": unread_count, "total_count": total_count}

    @application.get(
        "/v1/profiles",
        response_model=list[StudioProfileResponse],
        tags=["studio profiles"],
    )
    async def list_profiles(
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[StudioProfileResponse]:
        return [profile_response(profile) for profile in profiles.list(limit)]

    @application.post(
        "/v1/profiles",
        response_model=StudioProfileResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["studio profiles"],
    )
    async def create_profile(payload: StudioProfilePayload) -> StudioProfileResponse:
        normalized_variables = validate_profile_payload(payload)
        revision = profile_resource_revision(payload)
        profile = profiles.create(
            name=payload.name,
            resource_id=payload.resource_id,
            resource_revision=revision,
            text=payload.text,
            model=payload.model,
            voice=payload.voice,
            voice_profile_id=payload.voice_profile_id,
            instructions=payload.instructions,
            controls=payload.controls.to_domain(),
            split_strategy=payload.split_strategy,
            chunk_target_mode=payload.chunk_target_mode,
            chunk_target_value=payload.chunk_target_value,
            remove_numeric_citations=payload.remove_numeric_citations,
            variables=normalized_variables,
            job_id=payload.job_id,
        )
        return profile_response(profile)

    @application.get(
        "/v1/profiles/{profile_id}",
        response_model=StudioProfileResponse,
        tags=["studio profiles"],
    )
    async def get_profile(profile_id: str) -> StudioProfileResponse:
        try:
            return profile_response(profiles.get(profile_id))
        except ProfileNotFoundError as error:
            raise HTTPException(status_code=404, detail="profile not found") from error

    @application.put(
        "/v1/profiles/{profile_id}",
        response_model=StudioProfileResponse,
        tags=["studio profiles"],
    )
    async def update_profile(
        profile_id: str,
        payload: StudioProfilePayload,
    ) -> StudioProfileResponse:
        normalized_variables = validate_profile_payload(payload)
        try:
            profile = profiles.update(
                profile_id,
                name=payload.name,
                resource_id=payload.resource_id,
                resource_revision=profile_resource_revision(payload),
                text=payload.text,
                model=payload.model,
                voice=payload.voice,
                voice_profile_id=payload.voice_profile_id,
                instructions=payload.instructions,
                controls=payload.controls.to_domain(),
                split_strategy=payload.split_strategy,
                chunk_target_mode=payload.chunk_target_mode,
                chunk_target_value=payload.chunk_target_value,
                remove_numeric_citations=payload.remove_numeric_citations,
                variables=normalized_variables,
                job_id=payload.job_id,
            )
        except ProfileNotFoundError as error:
            raise HTTPException(status_code=404, detail="profile not found") from error
        return profile_response(profile)

    @application.delete(
        "/v1/profiles/{profile_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["studio profiles"],
    )
    async def delete_profile(profile_id: str) -> Response:
        try:
            profiles.delete(profile_id)
        except ProfileNotFoundError as error:
            raise HTTPException(status_code=404, detail="profile not found") from error
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @application.post(
        "/v1/speech/preview",
        response_model=PreviewResponse,
        tags=["speech jobs"],
    )
    async def preview_speech(request: CreateJobRequest) -> PreviewResponse:
        model, voice, variables = resolved_voice_request(request)
        try:
            plan = synthesis.preview(
                text=request.text,
                provider_name=request.selected_resource_id,
                model=model,
                voice=voice,
                instructions=request.instructions,
                controls=request.controls.to_domain(),
                variables=variables,
                resource_revision=request.resource_revision,
                split_strategy=request.split_strategy,
                chunk_target_mode=request.chunk_target_mode,
                chunk_target_value=request.chunk_target_value,
                remove_numeric_citations=request.remove_numeric_citations,
            )
        except UnknownProviderError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except (ValueError, ProviderError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return PreviewResponse.from_plan(plan)

    @application.post(
        "/v1/studio/dialogue/preview",
        response_model=DialoguePreviewResponse,
        tags=["studio dialogue"],
    )
    async def preview_dialogue(
        request: DialogueRenderRequest,
    ) -> DialoguePreviewResponse:
        segments = dialogue_segments(request)
        turn_previews: list[DialogueTurnPreviewResponse] = []
        try:
            for turn_index, (turn, segment) in enumerate(zip(request.turns, segments)):
                plan = synthesis.preview(
                    text=segment.text,
                    provider_name=request.selected_resource_id,
                    model=segment.model,
                    voice=segment.voice,
                    instructions=segment.instructions,
                    controls=segment.controls,
                    variables=segment.variables,
                    resource_revision=request.resource_revision,
                    split_strategy=request.split_strategy,
                    remove_numeric_citations=request.remove_numeric_citations,
                )
                turn_previews.append(
                    DialogueTurnPreviewResponse(
                        turn_index=turn_index,
                        speaker=turn.speaker,
                        text=plan.text,
                        total_chars=plan.total_chars,
                        total_bytes=plan.total_bytes,
                        total_words=plan.total_words,
                        chunks=[
                            ChunkPreviewResponse.from_chunk(chunk)
                            for chunk in plan.chunks
                        ],
                    )
                )
        except UnknownProviderError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except (ValueError, ProviderError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return DialoguePreviewResponse(
            strategy=request.split_strategy,
            total_turns=len(turn_previews),
            total_chunks=sum(len(turn.chunks) for turn in turn_previews),
            total_chars=sum(turn.total_chars for turn in turn_previews),
            total_bytes=sum(turn.total_bytes for turn in turn_previews),
            total_words=sum(turn.total_words for turn in turn_previews),
            turns=turn_previews,
        )

    @application.post(
        "/v1/studio/dialogue/jobs",
        response_model=JobResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["studio dialogue"],
    )
    async def create_dialogue_job(request: DialogueRenderRequest) -> JobResponse:
        segments = dialogue_segments(request)
        source_text = request.source_text or request.transcript_text()
        suggested_name = request.project_name or _suggest_project_name(
            source_text,
            request.source_name,
        )
        try:
            job = await synthesis.submit_segments(
                segments=segments,
                provider_name=request.selected_resource_id,
                resource_revision=request.resource_revision,
                source_text=source_text,
                split_strategy=request.split_strategy,
                remove_numeric_citations=request.remove_numeric_citations,
                export_stem=request.export_name or suggested_name,
            )
        except UnknownProviderError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except (ValueError, ProviderError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return job_response(
            job,
            project_name=suggested_name,
            source_name=request.source_name,
            take_label="Dialogue take",
        )

    @application.post(
        "/v1/speech/jobs",
        response_model=JobResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["speech jobs"],
    )
    async def create_job(request: CreateJobRequest) -> JobResponse:
        model, voice, variables = resolved_voice_request(request)
        suggested_name = request.project_name or _suggest_project_name(
            request.text,
            request.source_name,
        )
        try:
            job = await synthesis.submit(
                text=request.text,
                provider_name=request.selected_resource_id,
                model=model,
                voice=voice,
                instructions=request.instructions,
                controls=request.controls.to_domain(),
                variables=variables,
                resource_revision=request.resource_revision,
                split_strategy=request.split_strategy,
                chunk_target_mode=request.chunk_target_mode,
                chunk_target_value=request.chunk_target_value,
                remove_numeric_citations=request.remove_numeric_citations,
                export_stem=request.export_name or suggested_name,
            )
        except UnknownProviderError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except (ValueError, ProviderError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return job_response(
            job,
            project_name=suggested_name,
            source_name=request.source_name,
        )

    @application.get("/v1/speech/jobs", response_model=list[JobResponse], tags=["speech jobs"])
    async def list_jobs(
        response: Response,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[JobResponse]:
        response.headers["Cache-Control"] = "no-store"
        return [job_response(job) for job in synthesis.list_jobs(limit)]

    @application.get("/v1/speech/jobs/{job_id}", response_model=JobResponse, tags=["speech jobs"])
    async def get_job(job_id: str, response: Response) -> JobResponse:
        response.headers["Cache-Control"] = "no-store"
        try:
            return job_response(synthesis.get_job(job_id))
        except JobNotFoundError as error:
            raise HTTPException(status_code=404, detail="job not found") from error

    @application.post(
        "/v1/speech/jobs/{job_id}/retry",
        response_model=JobResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["speech jobs"],
    )
    async def retry_job(job_id: str) -> JobResponse:
        try:
            return job_response(await synthesis.retry(job_id))
        except JobNotFoundError as error:
            raise HTTPException(status_code=404, detail="job not found") from error
        except InvalidJobStateError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @application.post(
        "/v1/speech/jobs/{job_id}/pause",
        response_model=JobResponse,
        tags=["speech jobs"],
    )
    async def pause_job(job_id: str) -> JobResponse:
        try:
            return job_response(await synthesis.pause(job_id))
        except JobNotFoundError as error:
            raise HTTPException(status_code=404, detail="job not found") from error
        except InvalidJobStateError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @application.post(
        "/v1/speech/jobs/{job_id}/resume",
        response_model=JobResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["speech jobs"],
    )
    async def resume_job(job_id: str) -> JobResponse:
        try:
            return job_response(await synthesis.resume(job_id))
        except JobNotFoundError as error:
            raise HTTPException(status_code=404, detail="job not found") from error
        except InvalidJobStateError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @application.post(
        "/v1/speech/jobs/{job_id}/cancel",
        response_model=JobResponse,
        tags=["speech jobs"],
    )
    async def cancel_job(job_id: str) -> JobResponse:
        try:
            return job_response(await synthesis.cancel(job_id))
        except JobNotFoundError as error:
            raise HTTPException(status_code=404, detail="job not found") from error
        except InvalidJobStateError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @application.get("/v1/speech/jobs/{job_id}/partial-audio", tags=["speech jobs"])
    async def get_partial_audio(job_id: str) -> FileResponse:
        try:
            job = synthesis.get_job(job_id)
            path = await synthesis.partial_output_path(job_id)
        except JobNotFoundError as error:
            raise HTTPException(status_code=404, detail="job not found") from error
        except (ValueError, FileNotFoundError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return FileResponse(
            path,
            media_type="audio/wav",
            filename=f"{job.export_stem}-partial.wav",
            headers={"X-SPLICR-Partial": "true"},
        )

    @application.get(
        "/v1/speech/jobs/{job_id}/checkpoints",
        tags=["speech jobs"],
    )
    async def get_checkpoint_export(job_id: str) -> FileResponse:
        try:
            artifact = await synthesis.checkpoint_export(job_id)
        except JobNotFoundError as error:
            raise HTTPException(status_code=404, detail="job not found") from error
        except (ValueError, FileNotFoundError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return FileResponse(
            artifact.path,
            media_type="application/zip",
            filename=artifact.filename,
            headers={
                "X-SPLICR-Partial": "true" if artifact.partial else "false",
                "X-SPLICR-Exported-Chunks": str(artifact.exported_chunks),
                "X-SPLICR-Missing-Chunks": str(artifact.missing_chunks),
            },
        )

    @application.get("/v1/speech/jobs/{job_id}/audio", tags=["speech jobs"])
    async def get_audio(job_id: str) -> FileResponse:
        try:
            job = synthesis.get_job(job_id)
            path: Path = synthesis.output_path(job_id)
        except JobNotFoundError as error:
            raise HTTPException(status_code=404, detail="job not found") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except FileNotFoundError as error:
            raise HTTPException(status_code=500, detail=str(error)) from error
        return FileResponse(
            path,
            media_type="audio/wav",
            filename=f"{job.export_stem}.wav",
        )

    register_auth(application, settings=resolved_settings, manager=auth_manager)
    register_ui(application)
    return application


app = create_app()
