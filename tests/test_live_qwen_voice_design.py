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
from splicr.providers.qwen3 import QWEN3_MODELS
from splicr.studio.domain import VoiceProfile, VoiceProfileKind
from splicr.studio.voice_design import (
    QWEN_REFERENCE_TEXT,
    SubprocessQwenVoiceDesignRunner,
)
from splicr.studio.voice_resolution import resolve_voice_profile


@pytest.mark.live_engine
def test_live_qwen_voice_design_clones_with_advanced_controls_and_forced_resume(
    tmp_path,
) -> None:
    if os.getenv("SPLICR_LIVE_QWEN_VOICE_DESIGN") != "1":
        pytest.skip("set SPLICR_LIVE_QWEN_VOICE_DESIGN=1 to load the real VoiceDesign model")
    executable_value = os.getenv("SPLICR_QWEN3_PYTHON", "").strip()
    if not executable_value:
        pytest.skip("SPLICR_QWEN3_PYTHON is not configured")
    executable = Path(executable_value).expanduser().resolve()
    if not executable.is_file():
        pytest.fail(f"configured Qwen Python does not exist: {executable}")

    output = tmp_path / "reference.wav"
    result_path = tmp_path / "design-result.json"
    result = asyncio.run(
        SubprocessQwenVoiceDesignRunner(executable).design(
            description="A clear, calm documentary narrator with restrained warmth",
            take=2,
            output_path=output,
            result_path=result_path,
            should_cancel=lambda: False,
        )
    )

    assert result.reference_text == QWEN_REFERENCE_TEXT
    assert result.seed == 1002
    assert result_path.is_file()
    with wave.open(str(output), "rb") as recording:
        assert recording.getnchannels() == 1
        assert recording.getsampwidth() == 2
        assert recording.getframerate() == 24_000
        assert recording.getnframes() > 24_000

    profile = VoiceProfile(
        id="live-designed-qwen",
        label="Live designed Qwen narrator",
        engine_id="qwen3",
        kind=VoiceProfileKind.DESIGNED,
        description="A clear, calm documentary narrator with restrained warmth",
        reference_audio_path=str(output.resolve()),
        reference_text=result.reference_text,
        settings={
            "design_take": 2,
            "language": "English",
            "sampling": {
                "temperature": 0.62,
                "subtalker_temperature": 0.58,
                "top_k": 33,
                "top_p": 0.9,
                "repetition_penalty": 1.1,
            },
        },
    )
    voice, variables = resolve_voice_profile(
        "qwen3-local",
        profile,
        {"seed": 424_242},
    )
    text = (
        "Qwen renders this designed documentary voice with a frozen nondefault sampling plan.\n\n"
        "The first completed checkpoint must remain byte identical through interruption.\n\n"
        "Synthesis then resumes from the unfinished chunk and assembles one canonical take."
    )
    data_dir = tmp_path / "render-data"

    def settings(*, pacing_seconds: float) -> Settings:
        return Settings(
            data_dir=data_dir,
            qwen3_python=executable,
            chunk_max_bytes=10_000,
            chunk_max_words=12,
            pacing_seconds=pacing_seconds,
            max_attempts=3,
            local_engine_request_timeout_seconds=600.0,
        )

    async def render_with_forced_restart() -> None:
        first_service = create_service(settings(pacing_seconds=2.0))
        await first_service.start()
        try:
            preview = first_service.preview(
                text=text,
                provider_name="qwen3-local",
                model=QWEN3_MODELS[0],
                voice=voice,
                variables=variables,
            )
            assert len(preview.chunks) >= 3
            submitted = await first_service.submit(
                text=text,
                provider_name="qwen3-local",
                model=QWEN3_MODELS[0],
                voice=voice,
                variables=variables,
            )
            assert submitted.variables == variables
            assert [chunk.text for chunk in first_service.store.chunks_for_job(submitted.id)] == [
                chunk.text for chunk in preview.chunks
            ]

            for _ in range(2_400):
                chunks = first_service.store.chunks_for_job(submitted.id)
                completed = [chunk for chunk in chunks if chunk.status is ChunkStatus.COMPLETED]
                if completed:
                    break
                await asyncio.sleep(0.05)
            else:
                raise AssertionError("Qwen did not produce the first durable checkpoint")

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
            for _ in range(4_800):
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
                raise AssertionError("Qwen resume did not reach a terminal state")

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
