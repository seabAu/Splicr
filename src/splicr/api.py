from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
import re
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, File, HTTPException, Query, UploadFile, status
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
from .config import Settings
from .diagnostics import sanitize_diagnostic, sanitize_url
from .domain import (
    ControlMode,
    DeliveryControls,
    ErrorEventDraft,
    ErrorEventRecord,
    InvalidJobStateError,
    JobNotFoundError,
    JobRecord,
    JobStatus,
    NonverbalFrequency,
    ProviderError,
    ProviderInfo,
    SpeechPace,
    TonePreset,
    UnknownProviderError,
    VocalStyle,
)
from .document_import import DocumentImportError, import_document
from .errors import JobErrorCode, suggestion_for
from .planning import ChunkPlan, PlannedChunk, SplitStrategy
from .profiles import ProfileNotFoundError, StudioProfile, StudioProfileStore
from .service import SynthesisService
from .secret_vault import SecretVaultUnavailableError
from .ui import register_ui


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
    instructions: str | None = Field(
        default=None,
        max_length=2_000,
        description="Optional provider-neutral delivery/style direction",
    )
    controls: DeliveryControlsPayload = Field(default_factory=DeliveryControlsPayload)
    variables: dict[str, Any] = Field(default_factory=dict)
    split_strategy: SplitStrategy = SplitStrategy.SEMANTIC
    remove_numeric_citations: bool = Field(
        default=False,
        description="Remove standalone numeric citations such as [123] before chunking",
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
        return self

    @property
    def selected_resource_id(self) -> str:
        return self.resource_id or self.provider or "gemini"


class AudioFormatResponse(BaseModel):
    encoding: str
    sample_rate: int
    channels: int
    sample_width: int


class VoiceOptionResponse(BaseModel):
    id: str
    traits: list[str]


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
    boundary: str

    @classmethod
    def from_chunk(cls, chunk: PlannedChunk) -> "ChunkPreviewResponse":
        return cls(**{field: getattr(chunk, field) for field in cls.model_fields})


class PreviewResponse(BaseModel):
    text: str
    strategy: SplitStrategy
    total_chars: int
    total_bytes: int
    total_words: int
    chunks: list[ChunkPreviewResponse]

    @classmethod
    def from_plan(cls, plan: ChunkPlan) -> "PreviewResponse":
        return cls(
            text=plan.text,
            strategy=plan.strategy,
            total_chars=plan.total_chars,
            total_bytes=plan.total_bytes,
            total_words=plan.total_words,
            chunks=[ChunkPreviewResponse.from_chunk(chunk) for chunk in plan.chunks],
        )


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
            variables=dict(job.variables),
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
    instructions: str | None = Field(default=None, max_length=2_000)
    controls: DeliveryControlsPayload = Field(default_factory=DeliveryControlsPayload)
    split_strategy: SplitStrategy = SplitStrategy.SEMANTIC
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


class StudioProfileResponse(StudioProfilePayload):
    id: str
    created_at: str
    updated_at: str
    job: JobResponse | None = None


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
                "required",
                "default",
                "choices",
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
                    required=item.get("required", False),
                    default=item.get("default"),
                    choices=tuple(item.get("choices", ())),
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


def create_app(
    *,
    settings: Settings | None = None,
    service: SynthesisService | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings.from_env()
    synthesis = service or create_service(resolved_settings)
    profiles = StudioProfileStore(resolved_settings.database_path)
    profiles.initialize()
    candidate_resource_store = getattr(synthesis.providers, "store", None)
    resource_store = (
        candidate_resource_store
        if isinstance(candidate_resource_store, SqliteApiResourceStore)
        else None
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await synthesis.start()
        try:
            yield
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
    application.state.error_event_store = synthesis.store
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

    def job_response(job: JobRecord) -> JobResponse:
        response = JobResponse.from_record(job, synthesis.progress_detail(job.id))
        if (
            response.error_event_id
            and synthesis.store.get_error_event(response.error_event_id) is None
        ):
            return response.model_copy(update={"error_event_id": None})
        return response

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
        return tuple(dict.fromkeys(secrets))

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
            instructions=profile.instructions,
            controls=DeliveryControlsPayload.from_domain(profile.controls),
            split_strategy=profile.split_strategy,
            remove_numeric_citations=profile.remove_numeric_citations,
            variables=dict(profile.variables),
            job_id=profile.job_id,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
            job=linked_job,
        )

    def validate_profile_payload(payload: StudioProfilePayload) -> None:
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
        try:
            if resource_store is not None:
                resource = (
                    resource_store.get(payload.resource_id, payload.resource_revision)
                    if payload.resource_revision is not None
                    else resource_store.get_current(payload.resource_id)
                )
                if resource is None:
                    raise UnknownProviderError(
                        f"unknown TTS provider revision: "
                        f"{payload.resource_id}@{payload.resource_revision}"
                    )
            else:
                synthesis.providers.get(payload.resource_id)
        except UnknownProviderError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    def profile_resource_revision(payload: StudioProfilePayload) -> int | None:
        if payload.resource_revision is not None:
            return payload.resource_revision
        resolver = getattr(synthesis.providers, "current_revision", None)
        if resolver is None:
            return None
        return int(resolver(payload.resource_id))

    @application.get("/health", tags=["service"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

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
        validate_profile_payload(payload)
        revision = profile_resource_revision(payload)
        profile = profiles.create(
            name=payload.name,
            resource_id=payload.resource_id,
            resource_revision=revision,
            text=payload.text,
            model=payload.model,
            voice=payload.voice,
            instructions=payload.instructions,
            controls=payload.controls.to_domain(),
            split_strategy=payload.split_strategy,
            remove_numeric_citations=payload.remove_numeric_citations,
            variables=payload.variables,
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
        validate_profile_payload(payload)
        try:
            profile = profiles.update(
                profile_id,
                name=payload.name,
                resource_id=payload.resource_id,
                resource_revision=profile_resource_revision(payload),
                text=payload.text,
                model=payload.model,
                voice=payload.voice,
                instructions=payload.instructions,
                controls=payload.controls.to_domain(),
                split_strategy=payload.split_strategy,
                remove_numeric_citations=payload.remove_numeric_citations,
                variables=payload.variables,
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
        try:
            plan = synthesis.preview(
                text=request.text,
                provider_name=request.selected_resource_id,
                model=request.model,
                voice=request.voice,
                instructions=request.instructions,
                controls=request.controls.to_domain(),
                variables=request.variables,
                resource_revision=request.resource_revision,
                split_strategy=request.split_strategy,
                remove_numeric_citations=request.remove_numeric_citations,
            )
        except UnknownProviderError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except (ValueError, ProviderError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return PreviewResponse.from_plan(plan)

    @application.post(
        "/v1/speech/jobs",
        response_model=JobResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["speech jobs"],
    )
    async def create_job(request: CreateJobRequest) -> JobResponse:
        try:
            job = await synthesis.submit(
                text=request.text,
                provider_name=request.selected_resource_id,
                model=request.model,
                voice=request.voice,
                instructions=request.instructions,
                controls=request.controls.to_domain(),
                variables=request.variables,
                resource_revision=request.resource_revision,
                split_strategy=request.split_strategy,
                remove_numeric_citations=request.remove_numeric_citations,
            )
        except UnknownProviderError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except (ValueError, ProviderError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return job_response(job)

    @application.get("/v1/speech/jobs", response_model=list[JobResponse], tags=["speech jobs"])
    async def list_jobs(
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[JobResponse]:
        return [job_response(job) for job in synthesis.list_jobs(limit)]

    @application.get("/v1/speech/jobs/{job_id}", response_model=JobResponse, tags=["speech jobs"])
    async def get_job(job_id: str) -> JobResponse:
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
            path = await synthesis.partial_output_path(job_id)
        except JobNotFoundError as error:
            raise HTTPException(status_code=404, detail="job not found") from error
        except (ValueError, FileNotFoundError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return FileResponse(
            path,
            media_type="audio/wav",
            filename=f"splicr-{job_id}-partial.wav",
            headers={"X-SPLICR-Partial": "true"},
        )

    @application.get("/v1/speech/jobs/{job_id}/audio", tags=["speech jobs"])
    async def get_audio(job_id: str) -> FileResponse:
        try:
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
            filename=f"splicr-{job_id}.wav",
        )

    register_auth(application, settings=resolved_settings, manager=auth_manager)
    register_ui(application)
    return application


app = create_app()
