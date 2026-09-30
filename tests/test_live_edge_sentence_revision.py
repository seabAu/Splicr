from __future__ import annotations

import asyncio
import json
import os
import shutil
import wave
from pathlib import Path

import pytest

from splicr.bootstrap import create_service
from splicr.config import Settings
from splicr.domain import JobStatus
from splicr.providers.edge import EDGE_DEFAULT_VOICE, EDGE_MODEL
from splicr.studio.timeline import build_job_timeline


@pytest.mark.live_engine
@pytest.mark.live_provider
def test_live_edge_sentence_revision_retains_audible_artifacts(tmp_path: Path) -> None:
    if os.getenv("SPLICR_LIVE_EDGE_SENTENCE_REVISION") != "1":
        pytest.skip("set SPLICR_LIVE_EDGE_SENTENCE_REVISION=1 for the audible seam gate")
    executable_value = os.getenv("SPLICR_EDGE_PYTHON", "").strip()
    artifact_value = os.getenv("SPLICR_LIVE_SEAM_ARTIFACT_DIR", "").strip()
    if not executable_value:
        pytest.skip("SPLICR_EDGE_PYTHON is not configured")
    if not artifact_value:
        pytest.skip("set SPLICR_LIVE_SEAM_ARTIFACT_DIR outside source control")
    executable = Path(executable_value).expanduser().resolve()
    if not executable.is_file():
        pytest.fail(f"configured Edge TTS Python does not exist: {executable}")
    artifact_dir = Path(artifact_value).expanduser().resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)

    settings = Settings(
        data_dir=tmp_path / "data",
        edge_python=executable,
        chunk_max_bytes=10_000,
        chunk_max_words=100,
        pacing_seconds=0.0,
        max_attempts=3,
        local_engine_request_timeout_seconds=120.0,
    )
    source_text = (
        "The opening sentence establishes a calm and measured pace. "
        "This middle sentence will be replaced during the acceptance check. "
        "The final sentence should continue smoothly after the edited passage."
    )
    replacement_text = "This revised middle sentence should blend naturally at both seams."

    async def wait_for_terminal(service, job_id: str):
        for _ in range(2_400):
            job = service.get_job(job_id)
            if job.status in {
                JobStatus.COMPLETED,
                JobStatus.PAUSED,
                JobStatus.CANCELLED,
                JobStatus.FAILED,
            }:
                return job
            await asyncio.sleep(0.05)
        raise AssertionError(f"Edge job {job_id} did not reach a terminal state")

    async def scenario() -> tuple[Path, Path, dict[str, object]]:
        service = create_service(settings)
        await service.start()
        try:
            source = await service.submit(
                text=source_text,
                provider_name="edge-tts",
                model=EDGE_MODEL,
                voice=EDGE_DEFAULT_VOICE,
                variables={"timing_boundary": "word"},
            )
            source_finished = await wait_for_terminal(service, source.id)
            assert source_finished.status is JobStatus.COMPLETED, source_finished.error
            source_timeline = build_job_timeline(service.store, service.storage, source.id)
            assert len(source_timeline.segments) == 1
            assert [span.text for span in source_timeline.segments[0].sentences] == [
                "The opening sentence establishes a calm and measured pace.",
                "This middle sentence will be replaced during the acceptance check.",
                "The final sentence should continue smoothly after the edited passage.",
            ]

            revised = await service.revise_sentence(
                source_job_id=source.id,
                chunk_index=0,
                sentence_index=1,
                text=replacement_text,
                crossfade_ms=30.0,
            )
            revised_finished = await wait_for_terminal(service, revised.id)
            assert revised_finished.status is JobStatus.COMPLETED, revised_finished.error
            revised_chunk = service.store.chunks_for_job(revised.id)[0]
            provenance = revised_chunk.metadata["sentence_revision"]
            assert isinstance(provenance, dict)
            assert provenance["crossfade_frames"] == 720
            assert provenance["timing_source"] == "engine"

            return (
                service.output_path(source.id),
                service.output_path(revised.id),
                {
                    "source_job_id": source.id,
                    "revised_job_id": revised.id,
                    "voice": EDGE_DEFAULT_VOICE,
                    "source_text": source_text,
                    "replacement_text": replacement_text,
                    "revision": provenance,
                },
            )
        finally:
            await service.stop()

    source_path, revised_path, manifest = asyncio.run(scenario())
    retained_source = artifact_dir / "edge-sentence-seam-source.wav"
    retained_revision = artifact_dir / "edge-sentence-seam-revised.wav"
    shutil.copy2(source_path, retained_source)
    shutil.copy2(revised_path, retained_revision)
    (artifact_dir / "edge-sentence-seam-manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    for output in (retained_source, retained_revision):
        with wave.open(str(output), "rb") as recording:
            assert recording.getnchannels() == 1
            assert recording.getsampwidth() == 2
            assert recording.getframerate() == 24_000
            assert recording.getnframes() > 0
