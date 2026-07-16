from __future__ import annotations

import asyncio
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .bootstrap import create_service
from .config import Settings
from .domain import (
    ControlMode,
    DeliveryControls,
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
from .service import SynthesisService
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
    provider: str = Field(default="gemini", min_length=1, max_length=50)
    model: str | None = Field(default=None, min_length=1, max_length=200)
    voice: str | None = Field(default=None, min_length=1, max_length=100)
    instructions: str | None = Field(
        default=None,
        max_length=2_000,
        description="Optional provider-neutral delivery/style direction",
    )
    controls: DeliveryControlsPayload = Field(default_factory=DeliveryControlsPayload)
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
    total_chunks: int
    completed_chunks: int
    progress: float
    error: str | None
    error_code: str | None
    error_detail: str | None
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
            total_chunks=job.total_chunks,
            completed_chunks=job.completed_chunks,
            progress=progress,
            error=job.error,
            error_code=job.error_detail.code if job.error_detail else None,
            error_detail=job.error_detail.message if job.error_detail else job.error,
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


def create_app(
    *,
    settings: Settings | None = None,
    service: SynthesisService | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings.from_env()
    synthesis = service or create_service(resolved_settings)

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
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved_settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    def job_response(job: JobRecord) -> JobResponse:
        return JobResponse.from_record(job, synthesis.progress_detail(job.id))

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

    @application.get("/v1/speech/error-codes", tags=["speech jobs"])
    async def list_error_codes() -> list[dict[str, str]]:
        return [{"code": code.value, "suggestion": suggestion_for(code)} for code in JobErrorCode]

    @application.post(
        "/v1/speech/preview",
        response_model=PreviewResponse,
        tags=["speech jobs"],
    )
    async def preview_speech(request: CreateJobRequest) -> PreviewResponse:
        try:
            plan = synthesis.preview(
                text=request.text,
                provider_name=request.provider,
                model=request.model,
                voice=request.voice,
                instructions=request.instructions,
                controls=request.controls.to_domain(),
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
                provider_name=request.provider,
                model=request.model,
                voice=request.voice,
                instructions=request.instructions,
                controls=request.controls.to_domain(),
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

    register_ui(application)
    return application


app = create_app()
