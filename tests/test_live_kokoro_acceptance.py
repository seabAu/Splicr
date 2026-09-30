from __future__ import annotations

import asyncio
import hashlib
import os
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from splicr.api import create_app
from splicr.bootstrap import create_service
from splicr.config import Settings
from splicr.document_import import import_document
from splicr.domain import ChunkStatus, JobStatus


_KOKORO_ENV = "SPLICR_KOKORO_PYTHON"


def _configured_kokoro_python() -> Path:
    value = os.getenv(_KOKORO_ENV, "").strip()
    if not value:
        pytest.skip(f"set {_KOKORO_ENV} to run the real Kokoro acceptance gate")
    executable = Path(value).expanduser().resolve()
    if not executable.is_file():
        pytest.fail(f"configured Kokoro Python does not exist: {executable}")
    return executable


@pytest.mark.live_engine
def test_real_kokoro_import_preview_forced_resume_and_playback(tmp_path: Path) -> None:
    kokoro_python = _configured_kokoro_python()
    imported = import_document(
        "kokoro-acceptance.md",
        (
            "# Kokoro acceptance\n\n"
            "SPLICR imports a structured document and previews its durable chunk plan.\n\n"
            "The first checkpoint must survive a deliberately interrupted rendering session.\n\n"
            "After restart, synthesis continues in order without replacing completed audio."
        ).encode("utf-8"),
        max_upload_bytes=10_000,
    )
    data_dir = tmp_path / "data"

    def settings(*, pacing_seconds: float) -> Settings:
        return Settings(
            data_dir=data_dir,
            kokoro_python=kokoro_python,
            chunk_max_bytes=10_000,
            chunk_max_words=12,
            pacing_seconds=pacing_seconds,
            max_attempts=3,
        )

    async def render_with_forced_restart() -> tuple[str, bytes, int, int]:
        first_service = create_service(settings(pacing_seconds=2.0))
        await first_service.start()
        try:
            preview = first_service.preview(
                text=imported.text,
                provider_name="kokoro-local",
                voice="af_heart",
            )
            assert len(preview.chunks) >= 3
            submitted = await first_service.submit(
                text=imported.text,
                provider_name="kokoro-local",
                voice="af_heart",
            )
            assert [chunk.text for chunk in first_service.store.chunks_for_job(submitted.id)] == [
                chunk.text for chunk in preview.chunks
            ]

            for _ in range(1_200):
                chunks = first_service.store.chunks_for_job(submitted.id)
                completed = [chunk for chunk in chunks if chunk.status is ChunkStatus.COMPLETED]
                if completed:
                    break
                await asyncio.sleep(0.05)
            else:
                raise AssertionError("Kokoro did not produce the first durable checkpoint")

            first_chunk = completed[0]
            checkpoint = first_service.storage.chunk_path(submitted.id, first_chunk.index)
            checkpoint_payload = checkpoint.read_bytes()
            checkpoint_mtime = checkpoint.stat().st_mtime_ns
            first_attempts = first_chunk.attempts
        finally:
            await first_service.stop()

        resumed_service = create_service(settings(pacing_seconds=0.0))
        await resumed_service.start()
        try:
            for _ in range(2_400):
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
                raise AssertionError("Kokoro resume did not reach a terminal state")

            assert finished.status is JobStatus.COMPLETED, finished.error
            resumed_first = resumed_service.store.chunks_for_job(submitted.id)[first_chunk.index]
            assert resumed_first.attempts == first_attempts
            assert checkpoint.stat().st_mtime_ns == checkpoint_mtime
            assert hashlib.sha256(checkpoint.read_bytes()).digest() == hashlib.sha256(
                checkpoint_payload
            ).digest()

            output = resumed_service.output_path(submitted.id)
            with wave.open(str(output), "rb") as audio:
                assert audio.getnchannels() == 1
                assert audio.getsampwidth() == 2
                assert audio.getframerate() == 24_000
                assert audio.getnframes() > 0
            return submitted.id, checkpoint_payload, checkpoint_mtime, first_attempts
        finally:
            await resumed_service.stop()

    job_id, _payload, _mtime, _attempts = asyncio.run(render_with_forced_restart())

    playback_settings = settings(pacing_seconds=0.0)
    playback_service = create_service(playback_settings)
    with TestClient(create_app(settings=playback_settings, service=playback_service)) as client:
        response = client.get(
            f"/v1/speech/jobs/{job_id}/audio",
            headers={"Range": "bytes=0-43"},
        )
        assert response.status_code == 206
        assert response.headers["content-type"].startswith("audio/wav")
        assert response.headers["content-range"].startswith("bytes 0-43/")
        assert response.content[:4] == b"RIFF"
