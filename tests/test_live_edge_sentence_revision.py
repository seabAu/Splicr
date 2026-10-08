from __future__ import annotations

import asyncio
from array import array
import hashlib
import json
import math
import os
import shutil
import sys
import wave
from pathlib import Path

import pytest

from splicr.bootstrap import create_service
from splicr.config import Settings
from splicr.domain import JobStatus
from splicr.providers.edge import EDGE_DEFAULT_VOICE, EDGE_MODEL
from splicr.studio.timeline import build_job_timeline


def _pcm_seam_metrics(
    path: Path,
    seam_seconds: list[float],
    *,
    window_ms: float = 50.0,
) -> list[dict[str, float | int]]:
    with wave.open(str(path), "rb") as recording:
        assert recording.getnchannels() == 1
        assert recording.getsampwidth() == 2
        sample_rate = recording.getframerate()
        samples = array("h")
        samples.frombytes(recording.readframes(recording.getnframes()))
    if sys.byteorder == "big":
        samples.byteswap()

    window_frames = max(1, round(sample_rate * window_ms / 1_000.0))
    metrics: list[dict[str, float | int]] = []
    for seconds in seam_seconds:
        frame = round(seconds * sample_rate)
        if not 0 < frame < len(samples):
            raise AssertionError(f"seam frame {frame} is outside {path.name}")
        before = samples[max(0, frame - window_frames) : frame]
        after = samples[frame : min(len(samples), frame + window_frames)]
        local = samples[
            max(0, frame - window_frames) : min(len(samples), frame + window_frames)
        ]
        derivatives = sorted(
            abs(right - left) for left, right in zip(local, local[1:], strict=False)
        )
        percentile_index = max(0, math.ceil(0.99 * len(derivatives)) - 1)
        derivative_p99 = derivatives[percentile_index]
        jump = abs(samples[frame] - samples[frame - 1])
        rms_before = math.sqrt(sum(sample * sample for sample in before) / len(before))
        rms_after = math.sqrt(sum(sample * sample for sample in after) / len(after))
        metrics.append(
            {
                "seconds": seconds,
                "frame": frame,
                "sample_jump_abs": jump,
                "local_derivative_p99": derivative_p99,
                "jump_to_local_p99_ratio": jump / max(derivative_p99, 1),
                "rms_before": rms_before,
                "rms_after": rms_after,
                "rms_delta_db": 20.0
                * math.log10(max(rms_after, 1.0) / max(rms_before, 1.0)),
                "peak_before": max(map(abs, before)),
                "peak_after": max(map(abs, after)),
            }
        )
    return metrics


def test_pcm_seam_metrics_quantify_boundary_continuity(tmp_path: Path) -> None:
    output = tmp_path / "ramp.wav"
    samples = array("h", range(-1_200, 1_200))
    if sys.byteorder == "big":
        samples.byteswap()
    with wave.open(str(output), "wb") as recording:
        recording.setnchannels(1)
        recording.setsampwidth(2)
        recording.setframerate(24_000)
        recording.writeframes(samples.tobytes())

    metrics = _pcm_seam_metrics(output, [0.05], window_ms=25.0)

    assert metrics == [
        {
            "seconds": 0.05,
            "frame": 1_200,
            "sample_jump_abs": 1,
            "local_derivative_p99": 1,
            "jump_to_local_p99_ratio": 1.0,
            "rms_before": pytest.approx(346.84314418288085),
            "rms_after": pytest.approx(345.97711870392044),
            "rms_delta_db": pytest.approx(-0.02171473917485587),
            "peak_before": 600,
            "peak_after": 599,
        }
    ]


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

    artifacts: dict[str, object] = {}
    for label, output in (("source", retained_source), ("revised", retained_revision)):
        with wave.open(str(output), "rb") as recording:
            assert recording.getnchannels() == 1
            assert recording.getsampwidth() == 2
            assert recording.getframerate() == 24_000
            assert recording.getnframes() > 0
            frames = recording.getnframes()
            artifacts[label] = {
                "filename": output.name,
                "bytes": output.stat().st_size,
                "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                "channels": recording.getnchannels(),
                "sample_width_bytes": recording.getsampwidth(),
                "sample_rate": recording.getframerate(),
                "frames": frames,
                "duration_seconds": frames / recording.getframerate(),
            }

    revision = manifest["revision"]
    assert isinstance(revision, dict)
    original_start = float(revision["original_start"])
    original_end = float(revision["original_end"])
    duration_delta = float(revision["duration_delta"])
    revised_seams = [original_start, original_end + duration_delta]
    objective_seam_analysis = _pcm_seam_metrics(retained_revision, revised_seams)
    assert all(
        metric["jump_to_local_p99_ratio"] <= 1.0 for metric in objective_seam_analysis
    )
    assert all(
        max(metric["peak_before"], metric["peak_after"]) < 32_768
        for metric in objective_seam_analysis
    )
    manifest["artifacts"] = artifacts
    manifest["objective_seam_analysis"] = {
        "window_ms": 50.0,
        "boundaries": objective_seam_analysis,
        "criteria": [
            "The exact splice sample jump does not exceed the nearby 99th-percentile natural derivative.",
            "Neither 50 ms boundary window reaches signed-16-bit full scale.",
            "These metrics support but do not replace the required human audible review.",
        ],
    }
    manifest["listening"] = {
        "source_focus_seconds": [max(0.0, original_start - 0.75), original_end + 0.75],
        "revised_focus_seconds": [
            max(0.0, original_start - 0.75),
            original_end + duration_delta + 0.75,
        ],
        "criteria": [
            "No click, pop, duplicated phoneme, or clipped syllable at either splice.",
            "Room tone, loudness, pace, and vocal identity remain perceptually continuous.",
            "The replacement sentence is complete and the following sentence begins naturally.",
        ],
    }
    (artifact_dir / "edge-sentence-seam-manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
