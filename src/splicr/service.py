from __future__ import annotations

import asyncio
from collections.abc import Sequence
import contextlib
import hashlib
import json
import logging
import os
import random
import shutil
import uuid
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Callable, Mapping

from .chunking import ChunkPolicy, word_count
from .config import Settings
from .delivery import annotate_nonverbal_cues
from .diagnostics import (
    error_fingerprint,
    exception_chain,
    no_response_diagnostic,
    sanitize_diagnostic,
    sanitize_url,
)
from .domain import (
    CANONICAL_AUDIO_FORMAT,
    ChunkRecord,
    ChunkStatus,
    validate_control_values,
    DeliveryControls,
    ErrorEventDraft,
    JobErrorDetail,
    InvalidJobStateError,
    JobRecord,
    JobStatus,
    JsonValue,
    NonverbalFrequency,
    ProviderError,
    SEGMENT_OPTIONS_VARIABLE,
    SpeechPace,
    SynthesisSegment,
    SynthesisOptions,
    TonePreset,
    TtsProvider,
    VocalStyle,
)
from .errors import classify_job_error
from .preprocessing import preprocess_text
from .providers import TtsProviderRegistry
from .planning import ChunkPlan, ChunkTargetMode, SplitStrategy, plan_chunks
from .pronunciation import (
    PRONUNCIATION_REVISION_VARIABLE,
    PRONUNCIATION_VARIABLE,
    TextCustomizationStore,
    apply_substitutions,
)
from .storage import LocalJobStorage
from .store import SqliteJobStore
from .studio.engines import (
    EngineAdapter,
    EngineSession,
    EngineSessionContext,
    engine_adapter_for_provider,
)


def _controls_payload(controls: DeliveryControls) -> dict[str, JsonValue]:
    return {
        "tone": controls.tone.value,
        "pace": controls.pace.value,
        "vocal_style": controls.vocal_style.value,
        "nonverbal_frequency": controls.nonverbal_frequency.value,
    }


def _controls_from_payload(payload: object) -> DeliveryControls:
    if not isinstance(payload, Mapping):
        raise ValueError("persisted segment controls are invalid")
    try:
        return DeliveryControls(
            tone=TonePreset(str(payload.get("tone", TonePreset.NEUTRAL.value))),
            pace=SpeechPace(str(payload.get("pace", SpeechPace.NORMAL.value))),
            vocal_style=VocalStyle(
                str(payload.get("vocal_style", VocalStyle.NATURAL.value))
            ),
            nonverbal_frequency=NonverbalFrequency(
                str(
                    payload.get(
                        "nonverbal_frequency",
                        NonverbalFrequency.NEVER.value,
                    )
                )
            ),
        )
    except ValueError as error:
        raise ValueError("persisted segment controls contain an unknown value") from error


def _options_session_key(options: SynthesisOptions) -> str:
    payload = {
        "model": options.model,
        "voice": options.voice,
        "instructions": options.instructions,
        "controls": _controls_payload(options.controls),
        "variables": options.variables,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _segment_options_payload(
    options: SynthesisOptions,
    *,
    segment_index: int,
    speaker: str | None,
) -> dict[str, JsonValue]:
    return {
        "model": options.model,
        "voice": options.voice,
        "instructions": options.instructions,
        "controls": _controls_payload(options.controls),
        "variables": dict(options.variables),
        "session_key": _options_session_key(options),
        "segment_index": segment_index,
        "speaker": speaker,
    }


def _options_from_segment_payload(payload: object) -> tuple[SynthesisOptions, str]:
    if not isinstance(payload, Mapping):
        raise ValueError("persisted segment options are invalid")
    model = str(payload.get("model") or "").strip()
    voice = str(payload.get("voice") or "").strip()
    session_key = str(payload.get("session_key") or "").strip()
    if not model or not voice or not session_key:
        raise ValueError("persisted segment options are incomplete")
    instructions_value = payload.get("instructions")
    if instructions_value is not None and not isinstance(instructions_value, str):
        raise ValueError("persisted segment instructions are invalid")
    variables = payload.get("variables")
    if not isinstance(variables, Mapping):
        raise ValueError("persisted segment variables are invalid")
    return (
        SynthesisOptions(
            model=model,
            voice=voice,
            instructions=instructions_value,
            controls=_controls_from_payload(payload.get("controls")),
            variables=dict(variables),
        ),
        session_key,
    )


logger = logging.getLogger(__name__)
MAX_INSTRUCTIONS_BYTES = 2_000


class _JobStopped(RuntimeError):
    """Internal cooperative-control signal; never persisted as a job error."""


class SynthesisService:
    def __init__(
        self,
        *,
        settings: Settings,
        providers: TtsProviderRegistry,
        store: SqliteJobStore | None = None,
        storage: LocalJobStorage | None = None,
        customizations: TextCustomizationStore | None = None,
        engine_adapter_factory: Callable[[TtsProvider], EngineAdapter] = engine_adapter_for_provider,
    ) -> None:
        self.settings = settings
        self.providers = providers
        self.store = store or SqliteJobStore(settings.database_path)
        self.storage = storage or LocalJobStorage(settings.jobs_dir)
        self.customizations = customizations or TextCustomizationStore(
            settings.data_dir / "studio" / "language"
        )
        self._engine_adapter_factory = engine_adapter_factory
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None
        self._provider_ready_at: dict[str, float] = {}
        self._control_events: dict[str, asyncio.Event] = {}

    async def start(self) -> None:
        if self._worker is not None:
            return
        self.store.initialize()
        self.storage.initialize()
        for job_id in self.store.requeue_interrupted():
            self._queue.put_nowait(job_id)
        self._worker = asyncio.create_task(self._worker_loop(), name="splicr-synthesis-worker")

    async def stop(self) -> None:
        if self._worker is None:
            return
        self._worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._worker
        self._worker = None
        await self.providers.close()

    async def submit(
        self,
        *,
        text: str,
        provider_name: str = "gemini",
        model: str | None = None,
        voice: str | None = None,
        instructions: str | None = None,
        controls: DeliveryControls | None = None,
        variables: Mapping[str, Any] | None = None,
        resource_revision: int | None = None,
        split_strategy: SplitStrategy = SplitStrategy.SEMANTIC,
        chunk_target_mode: ChunkTargetMode = ChunkTargetMode.AUTOMATIC,
        chunk_target_value: int | None = None,
        remove_numeric_citations: bool = False,
    ) -> JobRecord:
        prepared_text = preprocess_text(
            text,
            remove_numeric_citations=remove_numeric_citations,
        ).text
        if not prepared_text.strip():
            raise ValueError("text contains no speakable content after preprocessing")
        synthesis_text, _ = apply_substitutions(
            prepared_text,
            self.customizations.substitutions(),
        )
        provider, options, policy = self._prepare_request(
            text=synthesis_text,
            provider_name=provider_name,
            model=model,
            voice=voice,
            instructions=instructions,
            controls=controls,
            variables=variables,
            resource_revision=resource_revision,
        )
        info = provider.info
        if info.name == "kokoro-local":
            snapshot = self.customizations.pronunciation_snapshot()
            variables_with_snapshot = dict(options.variables)
            variables_with_snapshot[PRONUNCIATION_VARIABLE] = (
                self.customizations.real_pronunciations(snapshot)
            )
            variables_with_snapshot[PRONUNCIATION_REVISION_VARIABLE] = (
                self.customizations.pronunciation_revision(snapshot)
            )
            options = replace(options, variables=variables_with_snapshot)
        selected_controls = options.controls
        capabilities = info.capabilities
        synthesis_text = annotate_nonverbal_cues(
            synthesis_text,
            selected_controls.nonverbal_frequency,
            capabilities.nonverbal_cues,
        )
        plan = plan_chunks(
            synthesis_text,
            policy,
            split_strategy,
            chunk_target_mode,
            chunk_target_value,
        )
        job_id = uuid.uuid4().hex

        self.storage.write_source(job_id, prepared_text)
        self.storage.write_plan(job_id, plan)
        try:
            self.store.create_job_with_chunks(
                job_id=job_id,
                provider=info.name,
                model=options.model,
                voice=options.voice,
                instructions=options.instructions,
                controls=selected_controls,
                resource_revision=(
                    resource_revision
                    if resource_revision is not None
                    else self._current_provider_revision(info.name)
                ),
                variables=options.variables,
                chunks=(chunk.text for chunk in plan.chunks),
            )
        except Exception:
            logger.exception("Failed to persist job %s", job_id)
            raise

        await self._queue.put(job_id)
        return self.store.get_job(job_id)

    async def submit_segments(
        self,
        *,
        segments: Sequence[SynthesisSegment],
        provider_name: str,
        resource_revision: int | None = None,
        source_text: str | None = None,
        split_strategy: SplitStrategy = SplitStrategy.SEMANTIC,
        remove_numeric_citations: bool = False,
    ) -> JobRecord:
        """Submit ordered, independently voiced segments as one resumable audio job."""

        if not segments:
            raise ValueError("a segmented job must contain at least one segment")
        original_source = source_text or "\n\n".join(segment.text.strip() for segment in segments)
        if len(original_source.encode("utf-8")) > self.settings.max_source_bytes:
            raise ValueError(
                f"text exceeds the {self.settings.max_source_bytes}-byte source limit"
            )
        if word_count(original_source) > self.settings.max_source_words:
            raise ValueError(
                f"text exceeds the {self.settings.max_source_words}-word source limit"
            )

        chunk_texts: list[str] = []
        chunk_options: list[JsonValue] = []
        first_options: SynthesisOptions | None = None
        canonical_provider_name: str | None = None
        for segment_index, segment in enumerate(segments):
            if SEGMENT_OPTIONS_VARIABLE in segment.variables:
                raise ValueError(f"{SEGMENT_OPTIONS_VARIABLE} is managed by segmented jobs")
            prepared_text = preprocess_text(
                segment.text,
                remove_numeric_citations=remove_numeric_citations,
            ).text
            if not prepared_text.strip():
                raise ValueError(
                    f"segment {segment_index + 1} contains no speakable content after preprocessing"
                )
            synthesis_text, _ = apply_substitutions(
                prepared_text,
                self.customizations.substitutions(),
            )
            provider, options, policy = self._prepare_request(
                text=synthesis_text,
                provider_name=provider_name,
                model=segment.model,
                voice=segment.voice,
                instructions=segment.instructions,
                controls=segment.controls,
                variables=segment.variables,
                resource_revision=resource_revision,
            )
            info = provider.info
            if canonical_provider_name is None:
                canonical_provider_name = info.name
            elif canonical_provider_name != info.name:
                raise ValueError("all segments in one job must use the same provider")
            if info.name == "kokoro-local":
                snapshot = self.customizations.pronunciation_snapshot()
                variables_with_snapshot = dict(options.variables)
                variables_with_snapshot[PRONUNCIATION_VARIABLE] = (
                    self.customizations.real_pronunciations(snapshot)
                )
                variables_with_snapshot[PRONUNCIATION_REVISION_VARIABLE] = (
                    self.customizations.pronunciation_revision(snapshot)
                )
                options = replace(options, variables=variables_with_snapshot)
            synthesis_text = annotate_nonverbal_cues(
                synthesis_text,
                options.controls.nonverbal_frequency,
                info.capabilities.nonverbal_cues,
            )
            plan = plan_chunks(synthesis_text, policy, split_strategy)
            if first_options is None:
                first_options = options
            for chunk in plan.chunks:
                chunk_texts.append(chunk.text)
                chunk_options.append(
                    _segment_options_payload(
                        options,
                        segment_index=segment_index,
                        speaker=segment.speaker,
                    )
                )

        if first_options is None or canonical_provider_name is None:
            raise RuntimeError("segmented job preparation produced no synthesis options")
        job_variables = dict(first_options.variables)
        job_variables[SEGMENT_OPTIONS_VARIABLE] = chunk_options
        job_id = uuid.uuid4().hex
        self.storage.write_source(job_id, original_source)
        try:
            self.store.create_job_with_chunks(
                job_id=job_id,
                provider=canonical_provider_name,
                model=first_options.model,
                voice=first_options.voice,
                instructions=first_options.instructions,
                controls=first_options.controls,
                resource_revision=(
                    resource_revision
                    if resource_revision is not None
                    else self._current_provider_revision(canonical_provider_name)
                ),
                variables=job_variables,
                chunks=chunk_texts,
            )
        except Exception:
            logger.exception("Failed to persist segmented job %s", job_id)
            raise

        await self._queue.put(job_id)
        return self.store.get_job(job_id)

    async def revise_chunk(
        self,
        *,
        source_job_id: str,
        chunk_index: int,
        text: str,
    ) -> JobRecord:
        """Create a new take while reusing every unchanged PCM checkpoint."""

        source_job = self.store.get_job(source_job_id)
        if source_job.status is not JobStatus.COMPLETED:
            raise InvalidJobStateError("only completed takes can be edited")
        chunks = self.store.chunks_for_job(source_job_id)
        if chunk_index < 0 or chunk_index >= len(chunks):
            raise ValueError("timeline segment index is out of range")
        replacement = preprocess_text(text).text
        if not replacement.strip():
            raise ValueError("replacement text must not be blank")
        replacement, _ = apply_substitutions(
            replacement,
            self.customizations.substitutions(),
        )

        default_variables = dict(source_job.variables)
        raw_segment_options = default_variables.pop(SEGMENT_OPTIONS_VARIABLE, None)
        if raw_segment_options is None:
            selected_options = SynthesisOptions(
                model=source_job.model,
                voice=source_job.voice,
                instructions=source_job.instructions,
                controls=source_job.controls,
                variables=default_variables,
            )
        else:
            if (
                not isinstance(raw_segment_options, list)
                or len(raw_segment_options) != len(chunks)
            ):
                raise ValueError(
                    "persisted segment options do not match the job's chunk count"
                )
            selected_options, _ = _options_from_segment_payload(
                raw_segment_options[chunk_index]
            )

        provider, selected_options, policy = self._prepare_request(
            text=replacement,
            provider_name=source_job.provider,
            model=selected_options.model,
            voice=selected_options.voice,
            instructions=selected_options.instructions,
            controls=selected_options.controls,
            variables=selected_options.variables,
            resource_revision=source_job.resource_revision,
        )
        replacement = annotate_nonverbal_cues(
            replacement,
            selected_options.controls.nonverbal_frequency,
            provider.info.capabilities.nonverbal_cues,
        )
        replacement_plan = plan_chunks(replacement, policy, SplitStrategy.SEMANTIC)
        if len(replacement_plan.chunks) != 1:
            raise ValueError(
                "replacement text exceeds one synthesis chunk; shorten this timeline edit"
            )
        replacement = replacement_plan.chunks[0].text

        for chunk in chunks:
            if chunk.index == chunk_index:
                continue
            if chunk.status is not ChunkStatus.COMPLETED or not chunk.pcm_path:
                raise InvalidJobStateError(
                    "the source take has an incomplete audio checkpoint"
                )
            self.storage.validate_chunk(Path(chunk.pcm_path), CANONICAL_AUDIO_FORMAT)

        revised_texts = [
            replacement if chunk.index == chunk_index else chunk.text for chunk in chunks
        ]
        revised_source = "\n\n".join(revised_texts)
        if len(revised_source.encode("utf-8")) > self.settings.max_source_bytes:
            raise ValueError("revised take exceeds the configured source byte limit")
        if word_count(revised_source) > self.settings.max_source_words:
            raise ValueError("revised take exceeds the configured source word limit")
        job_id = uuid.uuid4().hex
        self.storage.write_source(job_id, revised_source)
        self.store.create_job_with_chunks(
            job_id=job_id,
            provider=source_job.provider,
            model=source_job.model,
            voice=source_job.voice,
            instructions=source_job.instructions,
            controls=source_job.controls,
            resource_revision=source_job.resource_revision,
            variables=source_job.variables,
            chunks=revised_texts,
        )
        try:
            for chunk in chunks:
                if chunk.index == chunk_index:
                    continue
                source = Path(chunk.pcm_path or "")
                destination = self.storage.chunk_path(job_id, chunk.index)
                destination.parent.mkdir(parents=True, exist_ok=True)
                try:
                    os.link(source, destination)
                except OSError:
                    shutil.copy2(source, destination)
                self.store.mark_chunk_completed(
                    job_id,
                    chunk.index,
                    str(destination.resolve()),
                    chunk.metadata,
                )
        except Exception as error:
            self.store.mark_job_failed(job_id, f"could not stage unchanged checkpoints: {error}")
            raise

        await self._queue.put(job_id)
        return self.store.get_job(job_id)

    def preview(
        self,
        *,
        text: str,
        provider_name: str = "gemini",
        model: str | None = None,
        voice: str | None = None,
        instructions: str | None = None,
        controls: DeliveryControls | None = None,
        variables: Mapping[str, Any] | None = None,
        resource_revision: int | None = None,
        split_strategy: SplitStrategy = SplitStrategy.SEMANTIC,
        chunk_target_mode: ChunkTargetMode = ChunkTargetMode.AUTOMATIC,
        chunk_target_value: int | None = None,
        remove_numeric_citations: bool = False,
    ) -> ChunkPlan:
        """Return the exact normalized chunk plan without creating or queuing a job."""

        prepared_text = preprocess_text(
            text,
            remove_numeric_citations=remove_numeric_citations,
        ).text
        if not prepared_text.strip():
            raise ValueError("text contains no speakable content after preprocessing")
        synthesis_text, _ = apply_substitutions(
            prepared_text,
            self.customizations.substitutions(),
        )
        provider, options, policy = self._prepare_request(
            text=synthesis_text,
            provider_name=provider_name,
            model=model,
            voice=voice,
            instructions=instructions,
            controls=controls,
            variables=variables,
            resource_revision=resource_revision,
        )
        synthesis_text = annotate_nonverbal_cues(
            synthesis_text,
            options.controls.nonverbal_frequency,
            provider.info.capabilities.nonverbal_cues,
        )
        return plan_chunks(
            synthesis_text,
            policy,
            split_strategy,
            chunk_target_mode,
            chunk_target_value,
        )

    def _prepare_request(
        self,
        *,
        text: str,
        provider_name: str,
        model: str | None,
        voice: str | None,
        instructions: str | None,
        controls: DeliveryControls | None,
        variables: Mapping[str, Any] | None,
        resource_revision: int | None,
    ) -> tuple[TtsProvider, SynthesisOptions, ChunkPolicy]:
        provider = self._provider_for_job(provider_name, resource_revision)
        info = provider.info
        source_bytes = len(text.encode("utf-8"))
        if source_bytes > self.settings.max_source_bytes:
            raise ValueError(f"text exceeds the {self.settings.max_source_bytes}-byte source limit")
        source_words = word_count(text)
        if source_words > self.settings.max_source_words:
            raise ValueError(f"text exceeds the {self.settings.max_source_words}-word source limit")
        selected_model = (model or info.default_model).strip()
        selected_voice = (voice or info.default_voice).strip()
        if not selected_model or not selected_voice:
            raise ValueError("model and voice cannot be empty")
        normalized_instructions = (
            instructions.strip() if instructions and instructions.strip() else None
        )
        if (
            normalized_instructions
            and len(normalized_instructions.encode("utf-8")) > MAX_INSTRUCTIONS_BYTES
        ):
            raise ValueError(f"instructions exceed the {MAX_INSTRUCTIONS_BYTES}-byte limit")
        selected_controls = controls or DeliveryControls()
        capabilities = info.capabilities
        selected_variables = validate_control_values(
            capabilities.control_definitions,
            variables,
            allow_unknown=capabilities.allows_undeclared_variables,
        )
        if normalized_instructions and not capabilities.supports_custom_instructions:
            raise ValueError(f"provider {info.name!r} does not support custom instructions")
        if (
            selected_controls.tone is not TonePreset.NEUTRAL
            and selected_controls.tone not in capabilities.tone_presets
        ):
            raise ValueError(f"provider {info.name!r} does not support the selected tone")
        if (
            selected_controls.pace is not SpeechPace.NORMAL
            and selected_controls.pace not in capabilities.speech_paces
        ):
            raise ValueError(f"provider {info.name!r} does not support the selected pace")
        if (
            selected_controls.vocal_style is not VocalStyle.NATURAL
            and selected_controls.vocal_style not in capabilities.vocal_styles
        ):
            raise ValueError(f"provider {info.name!r} does not support the selected vocal style")
        if (
            selected_controls.nonverbal_frequency is not NonverbalFrequency.NEVER
            and selected_controls.nonverbal_frequency not in capabilities.nonverbal_frequencies
        ):
            raise ValueError(
                f"provider {info.name!r} does not support non-verbal frequency control"
            )

        options = SynthesisOptions(
            model=selected_model,
            voice=selected_voice,
            instructions=normalized_instructions,
            controls=selected_controls,
            variables=selected_variables,
        )
        policy = ChunkPolicy(
            max_bytes=min(
                value
                for value in (
                    self.settings.chunk_max_bytes,
                    info.max_input_bytes,
                    info.recommended_chunk_bytes,
                )
                if value is not None
            ),
            max_words=min(
                value
                for value in (self.settings.chunk_max_words, info.recommended_chunk_words)
                if value is not None
            ),
            max_characters=min(
                (
                    value
                    for value in (
                        info.max_input_characters,
                        info.recommended_chunk_characters,
                    )
                    if value is not None
                ),
                default=None,
            ),
            character_estimator=lambda segment: provider.estimate_input_characters(
                segment, options
            ),
            max_tokens=info.max_input_tokens,
            token_estimator=lambda segment: provider.estimate_input_tokens(segment, options),
        )
        return provider, options, policy

    def _current_provider_revision(self, provider_name: str) -> int | None:
        resolver = getattr(self.providers, "current_revision", None)
        if resolver is None:
            return None
        revision = resolver(provider_name)
        return int(revision) if revision is not None else None

    def _provider_for_job(self, provider_name: str, revision: int | None) -> TtsProvider:
        if revision is not None:
            resolver = getattr(self.providers, "get_revision", None)
            if resolver is not None:
                return resolver(provider_name, revision)
        return self.providers.get(provider_name)

    def _retry_policy_for_job(self, provider_name: str, revision: int | None):
        resolver = getattr(self.providers, "retry_policy", None)
        if resolver is None:
            return None
        return resolver(provider_name, revision)

    def get_job(self, job_id: str) -> JobRecord:
        return self.store.get_job(job_id)

    def list_jobs(self, limit: int = 100) -> list[JobRecord]:
        return self.store.list_jobs(limit)

    def output_path(self, job_id: str) -> Path:
        job = self.store.get_job(job_id)
        if job.status is not JobStatus.COMPLETED or not job.output_path:
            raise ValueError("audio is available only after the job completes")
        path = Path(job.output_path)
        if not path.is_file():
            raise FileNotFoundError(f"completed job output is missing: {job_id}")
        return path

    async def retry(self, job_id: str) -> JobRecord:
        return await self.resume(job_id)

    async def pause(self, job_id: str) -> JobRecord:
        job = self.store.pause_job(job_id)
        self._control_event(job_id).set()
        return job

    async def resume(self, job_id: str) -> JobRecord:
        job = self.store.resume_job(job_id)
        await self._queue.put(job_id)
        return job

    async def cancel(self, job_id: str) -> JobRecord:
        job = self.store.cancel_job(job_id)
        self._control_event(job_id).set()
        return job

    async def partial_output_path(self, job_id: str) -> Path:
        self.store.get_job(job_id)
        prefix: list[Path] = []
        for chunk in self.store.chunks_for_job(job_id):
            if chunk.status is not ChunkStatus.COMPLETED or not chunk.pcm_path:
                break
            path = Path(chunk.pcm_path)
            self.storage.validate_chunk(path, CANONICAL_AUDIO_FORMAT)
            prefix.append(path)
        if not prefix:
            raise ValueError("partial audio is available after the first chunk completes")
        return await asyncio.to_thread(
            self.storage.assemble_partial_wav,
            job_id,
            prefix,
            CANONICAL_AUDIO_FORMAT,
        )

    def progress_detail(self, job_id: str) -> dict[str, int | str | None]:
        chunks = self.store.chunks_for_job(job_id)
        planned_chars = sum(len(chunk.text) for chunk in chunks)
        completed_planned_chars = sum(
            len(chunk.text) for chunk in chunks if chunk.status is ChunkStatus.COMPLETED
        )
        try:
            total_chars = len(self.storage.read_source(job_id))
        except FileNotFoundError:
            total_chars = planned_chars
        current_char = (
            round(total_chars * completed_planned_chars / planned_chars) if planned_chars else 0
        )
        current = next(
            (chunk for chunk in chunks if chunk.status is not ChunkStatus.COMPLETED), None
        )
        return {
            "current_char": min(total_chars, current_char),
            "total_chars": total_chars,
            "current_chunk_index": current.index if current else None,
            "current_excerpt": current.text[:240] if current else None,
        }

    def _control_event(self, job_id: str) -> asyncio.Event:
        return self._control_events.setdefault(job_id, asyncio.Event())

    def _ensure_running(self, job_id: str) -> None:
        if self.store.get_job(job_id).status is not JobStatus.RUNNING:
            raise _JobStopped(job_id)

    async def _interruptible_wait(self, job_id: str, delay: float) -> None:
        if delay <= 0:
            self._ensure_running(job_id)
            return
        event = self._control_event(job_id)
        try:
            await asyncio.wait_for(event.wait(), timeout=delay)
        except TimeoutError:
            self._ensure_running(job_id)
            return
        self._ensure_running(job_id)

    async def _worker_loop(self) -> None:
        while True:
            job_id = await self._queue.get()
            try:
                await self._run_job(job_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Unhandled worker error for job %s", job_id)
            finally:
                self._queue.task_done()

    async def _run_job(self, job_id: str) -> None:
        job = self.store.get_job(job_id)
        if job.status is not JobStatus.QUEUED or not self.store.claim_job(job_id):
            return
        self._control_event(job_id).clear()
        active_chunk_index: int | None = None
        try:
            job = self.store.get_job(job_id)
            provider = self._provider_for_job(job.provider, job.resource_revision)
            engine = self._engine_adapter_factory(provider)
            chunks = self.store.chunks_for_job(job_id)
            session_context = EngineSessionContext(
                job_id=job.id,
                take_id=job.id,
                work_directory=self.storage.job_dir(job.id).resolve(),
                project_id=None,
                render_plan_id=None,
                resume=any(
                    chunk.attempts > 0 or chunk.status is ChunkStatus.COMPLETED
                    for chunk in chunks
                ),
            )
            retry_policy = self._retry_policy_for_job(job.provider, job.resource_revision)
            default_variables = dict(job.variables)
            raw_segment_options = default_variables.pop(SEGMENT_OPTIONS_VARIABLE, None)
            options = SynthesisOptions(
                model=job.model,
                voice=job.voice,
                instructions=job.instructions,
                controls=job.controls,
                variables=default_variables,
            )
            work_items: list[tuple[ChunkRecord, SynthesisOptions, str]] = [
                (chunk, options, "default") for chunk in chunks
            ]
            if raw_segment_options is not None:
                if not isinstance(raw_segment_options, list) or len(raw_segment_options) != len(
                    chunks
                ):
                    raise ValueError(
                        "persisted segment options do not match the job's chunk count"
                    )
                work_items = []
                session_order: dict[str, int] = {}
                for chunk, payload in zip(chunks, raw_segment_options, strict=True):
                    chunk_options, session_key = _options_from_segment_payload(payload)
                    session_order.setdefault(session_key, len(session_order))
                    work_items.append((chunk, chunk_options, session_key))
                work_items.sort(
                    key=lambda item: (session_order[item[2]], item[0].index)
                )
            admitted_pcm_bytes = 0
            async with contextlib.AsyncExitStack() as session_stack:
                session: EngineSession | None = None
                for chunk, chunk_options, _session_key in work_items:
                    self._ensure_running(job_id)
                    active_chunk_index = chunk.index
                    prior_attempts = chunk.attempts
                    if chunk.status is ChunkStatus.COMPLETED:
                        recorded_path = Path(chunk.pcm_path) if chunk.pcm_path else None
                        try:
                            if recorded_path is None:
                                raise ValueError("checkpoint path is missing")
                            candidate_pcm_bytes = self._admit_checkpoint(
                                recorded_path, admitted_pcm_bytes
                            )
                        except (FileNotFoundError, ValueError):
                            self.store.reset_chunk_for_resynthesis(
                                job_id,
                                chunk.index,
                                "completed checkpoint was missing or invalid; synthesizing again",
                            )
                            prior_attempts = 0
                        else:
                            admitted_pcm_bytes = candidate_pcm_bytes
                            continue

                    checkpoint = self.storage.chunk_path(job_id, chunk.index)
                    if checkpoint.is_file():
                        try:
                            candidate_pcm_bytes = self._admit_checkpoint(
                                checkpoint, admitted_pcm_bytes
                            )
                        except (FileNotFoundError, ValueError):
                            pass
                        else:
                            self.store.mark_chunk_completed(
                                job_id,
                                chunk.index,
                                str(checkpoint.resolve()),
                                chunk.metadata,
                            )
                            admitted_pcm_bytes = candidate_pcm_bytes
                            continue

                    if session is None:
                        session = await session_stack.enter_async_context(
                            engine.open_session(session_context)
                        )
                    await self._synthesize_chunk(
                        job_id,
                        chunk.index,
                        chunk.text,
                        engine,
                        session,
                        chunk_options,
                        prior_attempts,
                        retry_policy,
                    )
                    admitted_pcm_bytes = self._admit_checkpoint(
                        self.storage.chunk_path(job_id, chunk.index), admitted_pcm_bytes
                    )
                    self._ensure_running(job_id)

            active_chunk_index = None
            self._ensure_running(job_id)
            finished_chunks = self.store.chunks_for_job(job_id)
            if any(chunk.status is not ChunkStatus.COMPLETED for chunk in finished_chunks):
                raise RuntimeError("job ended with incomplete chunks")
            chunk_paths: list[Path] = []
            verified_pcm_bytes = 0
            for chunk in finished_chunks:
                if not chunk.pcm_path:
                    raise RuntimeError("completed chunk is missing its checkpoint path")
                chunk_path = Path(chunk.pcm_path)
                verified_pcm_bytes = self._admit_checkpoint(chunk_path, verified_pcm_bytes)
                chunk_paths.append(chunk_path)
            output = await asyncio.to_thread(
                self.storage.assemble_wav,
                job_id,
                chunk_paths,
                CANONICAL_AUDIO_FORMAT,
            )
            if not self.store.mark_job_completed_if_running(job_id, str(output.resolve())):
                output.unlink(missing_ok=True)
                raise _JobStopped(job_id)
            logger.info("Completed synthesis job %s", job_id)
        except _JobStopped:
            logger.info("Stopped synthesis job %s at a durable checkpoint", job_id)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            detail = classify_job_error(error, chunk_index=active_chunk_index)
            detail = self._record_job_error_event(
                job_id,
                error,
                detail,
                active_chunk_index,
            )
            if self.store.pause_for_error(job_id, detail):
                logger.warning("Synthesis job %s paused: %s", job_id, detail.message)

    def _record_job_error_event(
        self,
        job_id: str,
        error: Exception,
        detail: JobErrorDetail,
        chunk_index: int | None,
    ) -> JobErrorDetail:
        """Persist a redacted diagnostic record without masking the synthesis failure."""

        try:
            job = self.store.get_job(job_id)
            known_secrets = self._known_provider_secrets(job)
            diagnostic = error.diagnostic if isinstance(error, ProviderError) else None
            provider_origin = isinstance(error, ProviderError) and error.origin == "provider"
            diagnostic_data = asdict(diagnostic) if diagnostic is not None else {}
            category = str(diagnostic_data.get("category") or detail.code)
            phase = str(diagnostic_data.get("phase") or "synthesis")
            provider = str(diagnostic_data.get("provider") or job.provider)
            request = diagnostic_data.get("request")
            response = diagnostic_data.get("response")
            exception = diagnostic_data.get("exception")
            metadata = diagnostic_data.get("metadata")

            chunk = next(
                (item for item in self.store.chunks_for_job(job_id) if item.index == chunk_index),
                None,
            )
            try:
                retry_policy = self._retry_policy_for_job(job.provider, job.resource_revision)
            except Exception:
                retry_policy = None
            max_attempts = (
                retry_policy.max_attempts
                if retry_policy is not None
                else self.settings.max_attempts
            )
            if request is None and chunk is not None and provider_origin:
                request = {
                    "body": {
                        "text": chunk.text,
                        "utf8_bytes": len(chunk.text.encode("utf-8")),
                        "note": "Only the failed chunk is retained; the full document is not logged.",
                    }
                }
            if exception is None:
                exception = (
                    {
                        "chain": [
                            {
                                "type": (
                                    f"{error.__class__.__module__}.{error.__class__.__name__}"
                                ),
                                "message": detail.message,
                            }
                        ]
                    }
                    if isinstance(error, ProviderError)
                    else exception_chain(error, known_secrets=known_secrets)
                )
            if response is None:
                response = no_response_diagnostic(
                    "No HTTP response was received; the failure occurred before or outside response handling."
                )

            safe_request = sanitize_diagnostic(request, known_secrets=known_secrets)
            safe_response = sanitize_diagnostic(response, known_secrets=known_secrets)
            safe_exception = sanitize_diagnostic(exception, known_secrets=known_secrets)
            context_value = sanitize_diagnostic(
                {
                    "phase": phase,
                    "resource_id": job.provider,
                    "resource_revision": job.resource_revision,
                    "model": job.model,
                    "voice": job.voice,
                    "job_status": job.status.value,
                    "completed_chunks": job.completed_chunks,
                    "total_chunks": job.total_chunks,
                    "chunk_attempts": chunk.attempts if chunk is not None else None,
                    "max_attempts": max_attempts,
                    "diagnostic_metadata": metadata,
                },
                known_secrets=known_secrets,
            )
            safe_message_value = sanitize_diagnostic(detail.message, known_secrets=known_secrets)
            safe_message = str(safe_message_value or error.__class__.__name__)
            event = self.store.record_error_event(
                ErrorEventDraft(
                    fingerprint=(
                        error_fingerprint(
                            category=category,
                            provider=provider,
                            phase=phase,
                            status_code=detail.status_code,
                            exception=error,
                        )
                        + f":{job_id}:{chunk_index}:"
                        + hashlib.sha256(safe_message.encode("utf-8")).hexdigest()[:16]
                    ),
                    source="provider" if provider_origin else "service",
                    code=detail.code,
                    category=category,
                    message=safe_message,
                    retryable=detail.retryable,
                    status_code=detail.status_code,
                    method=(
                        str(diagnostic_data["method"])
                        if diagnostic_data.get("method") is not None
                        else None
                    ),
                    endpoint=(
                        sanitize_url(str(diagnostic_data["endpoint"]), known_secrets=known_secrets)
                        if diagnostic_data.get("endpoint") is not None
                        else None
                    ),
                    request=safe_request if isinstance(safe_request, Mapping) else None,
                    response=safe_response if isinstance(safe_response, Mapping) else None,
                    exception=safe_exception if isinstance(safe_exception, Mapping) else None,
                    context=context_value if isinstance(context_value, Mapping) else None,
                    provider=provider,
                    resource_revision=job.resource_revision,
                    job_id=job_id,
                    chunk_index=chunk_index,
                    attempt=chunk.attempts if chunk is not None and chunk.attempts else None,
                    occurred_at=detail.occurred_at,
                )
            )
            return replace(detail, event_id=event.id)
        except Exception:
            logger.exception("Could not persist diagnostics for synthesis job %s", job_id)
            return detail

    def _known_provider_secrets(self, job: JobRecord) -> tuple[str, ...]:
        """Resolve credentials only for redaction; failures never block error handling."""

        secrets = [
            value
            for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "DEEPGRAM_API_KEY", "INWORLD_API_KEY")
            if (value := os.getenv(name))
        ]
        resource_store = getattr(self.providers, "store", None)
        try:
            if resource_store is not None:
                spec = (
                    resource_store.get(job.provider, job.resource_revision)
                    if job.resource_revision is not None
                    else resource_store.get_current(job.provider)
                )
                if spec is not None:
                    secret = resource_store.resolve_api_key(spec)
                    if secret:
                        secrets.append(secret)
        except Exception:
            pass
        return tuple(dict.fromkeys(secrets))

    def _admit_checkpoint(self, path: Path, admitted_pcm_bytes: int) -> int:
        self.storage.validate_chunk(path, CANONICAL_AUDIO_FORMAT)
        projected_size = admitted_pcm_bytes + path.stat().st_size
        if projected_size > self.settings.max_output_pcm_bytes:
            raise ProviderError(
                "job would exceed the configured PCM/WAV size limit",
                retryable=False,
                origin="service",
            )
        return projected_size

    async def _synthesize_chunk(
        self,
        job_id: str,
        index: int,
        text: str,
        engine: EngineAdapter,
        session: EngineSession,
        options: SynthesisOptions,
        prior_attempts: int,
        retry_policy=None,
    ) -> None:
        max_attempts = (
            retry_policy.max_attempts if retry_policy is not None else self.settings.max_attempts
        )
        if prior_attempts >= max_attempts:
            error = ProviderError(
                "automatic retry budget was already exhausted before restart",
                retryable=False,
                origin="service",
            )
            self.store.mark_chunk_failed(job_id, index, str(error))
            raise error

        for attempt in range(prior_attempts + 1, max_attempts + 1):
            self._ensure_running(job_id)
            self.store.mark_chunk_running(job_id, index)
            try:
                audio = await self._paced_engine_request(job_id, engine, session, text, options)
            except asyncio.CancelledError:
                raise
            except _JobStopped:
                raise
            except ProviderError as error:
                status_allowed = (
                    retry_policy is None
                    or error.status_code is None
                    or error.status_code in retry_policy.retry_status_codes
                )
                should_retry = error.retryable and status_allowed and attempt < max_attempts
                if not should_retry:
                    self.store.mark_chunk_failed(job_id, index, str(error)[:2000])
                    raise
                self.store.mark_chunk_pending(job_id, index, str(error)[:2000])
                delay = self._retry_delay(attempt, error.retry_after, retry_policy)
                logger.info(
                    "Retrying job %s chunk %s after %.2fs (attempt %s/%s)",
                    job_id,
                    index,
                    delay,
                    attempt,
                    max_attempts,
                )
                await self._interruptible_wait(job_id, delay)
                continue
            except Exception as error:
                wrapped = ProviderError(str(error) or error.__class__.__name__, retryable=True)
                if attempt >= max_attempts:
                    self.store.mark_chunk_failed(job_id, index, str(wrapped)[:2000])
                    raise wrapped from error
                self.store.mark_chunk_pending(job_id, index, str(wrapped)[:2000])
                await self._interruptible_wait(
                    job_id, self._retry_delay(attempt, None, retry_policy)
                )
                continue

            try:
                if audio.format != CANONICAL_AUDIO_FORMAT:
                    raise ProviderError(
                        f"provider returned non-canonical audio: {audio.format}",
                        retryable=False,
                        origin="service",
                    )
                checkpoint = self.storage.chunk_path(job_id, index)
                existing_size = checkpoint.stat().st_size if checkpoint.is_file() else 0
                projected_size = (
                    self.storage.total_chunk_bytes(job_id) - existing_size + len(audio.pcm)
                )
                if projected_size > self.settings.max_output_pcm_bytes:
                    raise ProviderError(
                        "job would exceed the configured PCM/WAV size limit",
                        retryable=False,
                        origin="service",
                    )
                path = self.storage.write_chunk(job_id, index, audio.pcm, audio.format)
                self.store.mark_chunk_completed(
                    job_id,
                    index,
                    str(path.resolve()),
                    audio.metadata,
                )
                return
            except ProviderError as error:
                self.store.mark_chunk_failed(job_id, index, str(error)[:2000])
                raise
            except Exception as error:
                message = f"failed to checkpoint synthesized audio: {error}"
                self.store.mark_chunk_failed(job_id, index, message[:2000])
                raise RuntimeError(message) from error

    async def _paced_engine_request(
        self,
        job_id: str,
        engine: EngineAdapter,
        session: EngineSession,
        text: str,
        options: SynthesisOptions,
    ):
        loop = asyncio.get_running_loop()
        provider_info = engine.descriptor.provider_info
        provider_name = provider_info.name
        ready_at = self._provider_ready_at.get(provider_name, 0.0)
        delay = ready_at - loop.time()
        if delay > 0:
            await self._interruptible_wait(job_id, delay)
        self._ensure_running(job_id)
        try:
            return await session.synthesize(text, options)
        finally:
            request_interval = provider_info.minimum_request_interval_seconds
            if request_interval is None:
                request_interval = self.settings.pacing_seconds
            self._provider_ready_at[provider_name] = loop.time() + request_interval

    def _retry_delay(
        self,
        attempt: int,
        retry_after: float | None,
        retry_policy=None,
    ) -> float:
        base_seconds = (
            retry_policy.backoff_initial_seconds
            if retry_policy is not None
            else self.settings.backoff_base_seconds
        )
        max_seconds = (
            retry_policy.backoff_max_seconds
            if retry_policy is not None
            else self.settings.backoff_max_seconds
        )
        jitter_seconds = (
            retry_policy.jitter_seconds
            if retry_policy is not None
            else self.settings.backoff_jitter_seconds
        )
        exponential = min(
            base_seconds * (2 ** (attempt - 1)),
            max_seconds,
        )
        local_delay = exponential + random.uniform(0, jitter_seconds)
        if retry_after is None or (retry_policy is not None and not retry_policy.honor_retry_after):
            return local_delay
        return max(local_delay, max(0.0, retry_after))
