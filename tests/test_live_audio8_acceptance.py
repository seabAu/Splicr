from __future__ import annotations

import asyncio
import hashlib
import os
import wave
from pathlib import Path

import pytest

from splicr.bootstrap import create_service
from splicr.config import Settings
from splicr.domain import ChunkStatus, JobStatus
from splicr.providers.audio8 import AUDIO8_MODEL
from splicr.studio.domain import VoiceProfile, VoiceProfileKind
from splicr.studio.voice_resolution import resolve_voice_profile


_AUDIO8_ENV = "SPLICR_AUDIO8_PYTHON"
_REFERENCE_AUDIO_ENV = "SPLICR_LIVE_AUDIO8_REFERENCE_AUDIO"
_REFERENCE_TEXT_ENV = "SPLICR_LIVE_AUDIO8_REFERENCE_TEXT"


def _configured_file(variable: str, label: str) -> Path:
    value = os.getenv(variable, "").strip()
    if not value:
        pytest.skip(f"set {variable} to run the real Audio8 acceptance gate")
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        pytest.fail(f"configured {label} does not exist: {path}")
    return path


@pytest.mark.live_engine
def test_real_audio8_clone_forced_resume_and_canonical_output(tmp_path: Path) -> None:
    audio8_python = _configured_file(_AUDIO8_ENV, "Audio8 Python")
    reference_audio = _configured_file(_REFERENCE_AUDIO_ENV, "Audio8 reference audio")
    reference_text = os.getenv(_REFERENCE_TEXT_ENV, "").strip()
    if not reference_text:
        pytest.skip(f"set {_REFERENCE_TEXT_ENV} to the exact reference transcript")

    profile = VoiceProfile(
        id="live-audio8-clone",
        label="Live Audio8 clone",
        engine_id="audio8",
        kind=VoiceProfileKind.CLONED,
        reference_audio_path=str(reference_audio),
        reference_text=reference_text,
    )
    voice, variables = resolve_voice_profile("audio8-local", profile, {})
    text = (
        "Audio8 renders this cloned voice through an isolated local engine session.\n\n"
        "The first completed checkpoint must remain byte identical after interruption.\n\n"
        "A restarted service resumes the unfinished work and assembles canonical audio."
    )
    data_dir = tmp_path / "data"

    def settings(*, pacing_seconds: float) -> Settings:
        return Settings(
            data_dir=data_dir,
            audio8_python=audio8_python,
            chunk_max_bytes=10_000,
            chunk_max_words=10,
            pacing_seconds=pacing_seconds,
            max_attempts=3,
            local_engine_startup_timeout_seconds=900.0,
            local_engine_request_timeout_seconds=900.0,
        )

    async def render_with_forced_restart() -> None:
        first_service = create_service(settings(pacing_seconds=2.0))
        await first_service.start()
        try:
            preview = first_service.preview(
                text=text,
                provider_name="audio8-local",
                model=AUDIO8_MODEL,
                voice=voice,
                variables=variables,
            )
            assert len(preview.chunks) >= 3
            submitted = await first_service.submit(
                text=text,
                provider_name="audio8-local",
                model=AUDIO8_MODEL,
                voice=voice,
                variables=variables,
            )
            assert submitted.variables == variables
            assert [chunk.text for chunk in first_service.store.chunks_for_job(submitted.id)] == [
                chunk.text for chunk in preview.chunks
            ]

            for _ in range(12_000):
                chunks = first_service.store.chunks_for_job(submitted.id)
                completed = [chunk for chunk in chunks if chunk.status is ChunkStatus.COMPLETED]
                if completed:
                    break
                await asyncio.sleep(0.05)
            else:
                raise AssertionError("Audio8 did not produce the first durable checkpoint")

            first_chunk = completed[0]
            checkpoint = first_service.storage.chunk_path(submitted.id, first_chunk.index)
            checkpoint_digest = hashlib.sha256(checkpoint.read_bytes()).digest()
            checkpoint_mtime = checkpoint.stat().st_mtime_ns
            first_attempts = first_chunk.attempts
        finally:
            await first_service.stop()

        resumed_service = create_service(settings(pacing_seconds=0.0))
        await resumed_service.start()
        try:
            for _ in range(24_000):
                finished = resumed_service.get_job(submitted.id)
                if finished.status in {
                    JobStatus.COMPLETED,
                    JobStatus.PAUSED,
                    JobStatus.CANCELLED,
                    JobStatus.FAILED,
                }:
                    break
                await asyncio.sleep(0.05)
            else:
                raise AssertionError("Audio8 resume did not reach a terminal state")

            assert finished.status is JobStatus.COMPLETED, finished.error
            assert finished.variables == variables
            resumed_first = resumed_service.store.chunks_for_job(submitted.id)[first_chunk.index]
            assert resumed_first.attempts == first_attempts
            assert checkpoint.stat().st_mtime_ns == checkpoint_mtime
            assert hashlib.sha256(checkpoint.read_bytes()).digest() == checkpoint_digest
            with wave.open(str(resumed_service.output_path(submitted.id)), "rb") as recording:
                assert recording.getnchannels() == 1
                assert recording.getsampwidth() == 2
                assert recording.getframerate() == 24_000
                assert recording.getnframes() > 0
        finally:
            await resumed_service.stop()

    asyncio.run(render_with_forced_restart())
