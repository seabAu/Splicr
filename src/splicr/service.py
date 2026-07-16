from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import uuid
from pathlib import Path

from .chunking import ChunkPolicy, word_count
from .config import Settings
from .delivery import annotate_nonverbal_cues
from .domain import (
    CANONICAL_AUDIO_FORMAT,
    ChunkStatus,
    DeliveryControls,
    JobRecord,
    JobStatus,
    NonverbalFrequency,
    ProviderError,
    SpeechPace,
    SynthesisOptions,
    TonePreset,
    TtsProvider,
    VocalStyle,
)
from .errors import classify_job_error
from .preprocessing import preprocess_text
from .providers import ProviderRegistry
from .planning import ChunkPlan, SplitStrategy, plan_chunks
from .storage import LocalJobStorage
from .store import SqliteJobStore


logger = logging.getLogger(__name__)
MAX_INSTRUCTIONS_BYTES = 2_000


class _JobStopped(RuntimeError):
    """Internal cooperative-control signal; never persisted as a job error."""


class SynthesisService:
    def __init__(
        self,
        *,
        settings: Settings,
        providers: ProviderRegistry,
        store: SqliteJobStore | None = None,
        storage: LocalJobStorage | None = None,
    ) -> None:
        self.settings = settings
        self.providers = providers
        self.store = store or SqliteJobStore(settings.database_path)
        self.storage = storage or LocalJobStorage(settings.jobs_dir)
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
        split_strategy: SplitStrategy = SplitStrategy.SEMANTIC,
        remove_numeric_citations: bool = False,
    ) -> JobRecord:
        prepared_text = preprocess_text(
            text,
            remove_numeric_citations=remove_numeric_citations,
        ).text
        if not prepared_text.strip():
            raise ValueError("text contains no speakable content after preprocessing")
        provider, options, policy = self._prepare_request(
            text=prepared_text,
            provider_name=provider_name,
            model=model,
            voice=voice,
            instructions=instructions,
            controls=controls,
        )
        info = provider.info
        selected_controls = options.controls
        capabilities = info.capabilities
        synthesis_text = annotate_nonverbal_cues(
            prepared_text,
            selected_controls.nonverbal_frequency,
            capabilities.nonverbal_cues,
        )
        plan = plan_chunks(synthesis_text, policy, split_strategy)
        job_id = uuid.uuid4().hex

        self.storage.write_source(job_id, prepared_text)
        try:
            self.store.create_job_with_chunks(
                job_id=job_id,
                provider=info.name,
                model=options.model,
                voice=options.voice,
                instructions=options.instructions,
                controls=selected_controls,
                chunks=(chunk.text for chunk in plan.chunks),
            )
        except Exception:
            logger.exception("Failed to persist job %s", job_id)
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
        split_strategy: SplitStrategy = SplitStrategy.SEMANTIC,
        remove_numeric_citations: bool = False,
    ) -> ChunkPlan:
        """Return the exact normalized chunk plan without creating or queuing a job."""

        prepared_text = preprocess_text(
            text,
            remove_numeric_citations=remove_numeric_citations,
        ).text
        if not prepared_text.strip():
            raise ValueError("text contains no speakable content after preprocessing")
        _, _, policy = self._prepare_request(
            text=prepared_text,
            provider_name=provider_name,
            model=model,
            voice=voice,
            instructions=instructions,
            controls=controls,
        )
        return plan_chunks(prepared_text, policy, split_strategy)

    def _prepare_request(
        self,
        *,
        text: str,
        provider_name: str,
        model: str | None,
        voice: str | None,
        instructions: str | None,
        controls: DeliveryControls | None,
    ) -> tuple[TtsProvider, SynthesisOptions, ChunkPolicy]:
        provider = self.providers.get(provider_name)
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
            provider = self.providers.get(job.provider)
            options = SynthesisOptions(
                model=job.model,
                voice=job.voice,
                instructions=job.instructions,
                controls=job.controls,
            )
            chunks = self.store.chunks_for_job(job_id)
            admitted_pcm_bytes = 0
            for chunk in chunks:
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
                        candidate_pcm_bytes = self._admit_checkpoint(checkpoint, admitted_pcm_bytes)
                    except (FileNotFoundError, ValueError):
                        pass
                    else:
                        self.store.mark_chunk_completed(
                            job_id, chunk.index, str(checkpoint.resolve())
                        )
                        admitted_pcm_bytes = candidate_pcm_bytes
                        continue

                await self._synthesize_chunk(
                    job_id,
                    chunk.index,
                    chunk.text,
                    provider,
                    options,
                    prior_attempts,
                )
                admitted_pcm_bytes = self._admit_checkpoint(
                    self.storage.chunk_path(job_id, chunk.index), admitted_pcm_bytes
                )
                self._ensure_running(job_id)

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
            if self.store.pause_for_error(job_id, detail):
                logger.warning("Synthesis job %s paused: %s", job_id, detail.message)

    def _admit_checkpoint(self, path: Path, admitted_pcm_bytes: int) -> int:
        self.storage.validate_chunk(path, CANONICAL_AUDIO_FORMAT)
        projected_size = admitted_pcm_bytes + path.stat().st_size
        if projected_size > self.settings.max_output_pcm_bytes:
            raise ProviderError(
                "job would exceed the configured PCM/WAV size limit",
                retryable=False,
            )
        return projected_size

    async def _synthesize_chunk(
        self,
        job_id: str,
        index: int,
        text: str,
        provider: TtsProvider,
        options: SynthesisOptions,
        prior_attempts: int,
    ) -> None:
        if prior_attempts >= self.settings.max_attempts:
            error = ProviderError(
                "automatic retry budget was already exhausted before restart",
                retryable=False,
            )
            self.store.mark_chunk_failed(job_id, index, str(error))
            raise error

        for attempt in range(prior_attempts + 1, self.settings.max_attempts + 1):
            self._ensure_running(job_id)
            self.store.mark_chunk_running(job_id, index)
            try:
                audio = await self._paced_provider_request(job_id, provider, text, options)
            except asyncio.CancelledError:
                raise
            except _JobStopped:
                raise
            except ProviderError as error:
                should_retry = error.retryable and attempt < self.settings.max_attempts
                if not should_retry:
                    self.store.mark_chunk_failed(job_id, index, str(error)[:2000])
                    raise
                self.store.mark_chunk_pending(job_id, index, str(error)[:2000])
                delay = self._retry_delay(attempt, error.retry_after)
                logger.info(
                    "Retrying job %s chunk %s after %.2fs (attempt %s/%s)",
                    job_id,
                    index,
                    delay,
                    attempt,
                    self.settings.max_attempts,
                )
                await self._interruptible_wait(job_id, delay)
                continue
            except Exception as error:
                wrapped = ProviderError(str(error) or error.__class__.__name__, retryable=True)
                if attempt >= self.settings.max_attempts:
                    self.store.mark_chunk_failed(job_id, index, str(wrapped)[:2000])
                    raise wrapped from error
                self.store.mark_chunk_pending(job_id, index, str(wrapped)[:2000])
                await self._interruptible_wait(job_id, self._retry_delay(attempt, None))
                continue

            try:
                if audio.format != CANONICAL_AUDIO_FORMAT:
                    raise ProviderError(
                        f"provider returned non-canonical audio: {audio.format}",
                        retryable=False,
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
                    )
                path = self.storage.write_chunk(job_id, index, audio.pcm, audio.format)
                self.store.mark_chunk_completed(job_id, index, str(path.resolve()))
                return
            except ProviderError as error:
                self.store.mark_chunk_failed(job_id, index, str(error)[:2000])
                raise
            except Exception as error:
                message = f"failed to checkpoint synthesized audio: {error}"
                self.store.mark_chunk_failed(job_id, index, message[:2000])
                raise RuntimeError(message) from error

    async def _paced_provider_request(
        self,
        job_id: str,
        provider: TtsProvider,
        text: str,
        options: SynthesisOptions,
    ):
        loop = asyncio.get_running_loop()
        provider_name = provider.info.name
        ready_at = self._provider_ready_at.get(provider_name, 0.0)
        delay = ready_at - loop.time()
        if delay > 0:
            await self._interruptible_wait(job_id, delay)
        self._ensure_running(job_id)
        try:
            return await provider.synthesize(text, options)
        finally:
            request_interval = provider.info.minimum_request_interval_seconds
            if request_interval is None:
                request_interval = self.settings.pacing_seconds
            self._provider_ready_at[provider_name] = loop.time() + request_interval

    def _retry_delay(self, attempt: int, retry_after: float | None) -> float:
        exponential = min(
            self.settings.backoff_base_seconds * (2 ** (attempt - 1)),
            self.settings.backoff_max_seconds,
        )
        local_delay = exponential + random.uniform(0, self.settings.backoff_jitter_seconds)
        if retry_after is None:
            return local_delay
        return max(local_delay, max(0.0, retry_after))
