from __future__ import annotations

import asyncio
import json
import time
import wave
from pathlib import Path

from fastapi.testclient import TestClient

from splicr.api import create_app
from splicr.config import Settings
from splicr.providers import ProviderRegistry
from splicr.service import SynthesisService
from splicr.studio import SqliteStudioStore
from splicr.studio.voice_design import (
    QWEN_DESIGN_MODEL,
    QWEN_REFERENCE_TEXT,
    VoiceDesignJobService,
    VoiceDesignJobStatus,
    VoiceDesignJobStore,
    VoiceDesignCancelled,
    VoiceDesignResult,
)

from .fakes import RecordingProvider


def _write_reference(path: Path, seconds: float = 0.1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as recording:
        recording.setnchannels(1)
        recording.setsampwidth(2)
        recording.setframerate(24_000)
        recording.writeframes(b"\x00\x00" * round(24_000 * seconds))


class FakeVoiceDesignRunner:
    def __init__(self, *, failures: int = 0) -> None:
        self.failures = failures
        self.calls: list[tuple[str, int]] = []

    async def design(
        self,
        *,
        description: str,
        take: int,
        output_path: Path,
        result_path: Path,
        should_cancel,
    ) -> VoiceDesignResult:
        del should_cancel
        self.calls.append((description, take))
        if len(self.calls) <= self.failures:
            raise RuntimeError("synthetic design failure")
        _write_reference(output_path)
        result = VoiceDesignResult(
            output_path=str(output_path.resolve()),
            reference_text=QWEN_REFERENCE_TEXT,
            model=QWEN_DESIGN_MODEL,
            seed=1000 + take,
            sample_rate=24_000,
            seconds=0.1,
        )
        result_path.write_text(
            json.dumps(
                {
                    "output_path": result.output_path,
                    "reference_text": result.reference_text,
                    "model": result.model,
                    "seed": result.seed,
                    "sample_rate": result.sample_rate,
                    "seconds": result.seconds,
                }
            ),
            encoding="utf-8",
        )
        return result


class BlockingVoiceDesignRunner:
    def __init__(self) -> None:
        self.calls = 0

    async def design(
        self,
        *,
        description: str,
        take: int,
        output_path: Path,
        result_path: Path,
        should_cancel,
    ) -> VoiceDesignResult:
        del description, take, output_path, result_path
        self.calls += 1
        while not should_cancel():
            await asyncio.sleep(0.005)
        raise VoiceDesignCancelled("voice design was cancelled")


class CancelBeforeCompleteStore(VoiceDesignJobStore):
    def complete(self, job_id, profile):
        self.request_cancel(job_id)
        return super().complete(job_id, profile)


async def _wait_for(
    service: VoiceDesignJobService,
    job_id: str,
    status: VoiceDesignJobStatus,
) -> None:
    for _ in range(200):
        if service.store.get(job_id).status is status:
            return
        await asyncio.sleep(0.005)
    raise AssertionError(f"voice design job did not reach {status.value}")


def _service(tmp_path: Path, runner: FakeVoiceDesignRunner) -> VoiceDesignJobService:
    database = tmp_path / "splicr.sqlite3"
    studio = SqliteStudioStore(database)
    studio.initialize()
    store = VoiceDesignJobStore(database)
    store.initialize()
    return VoiceDesignJobService(
        store=store,
        studio_store=studio,
        output_root=tmp_path / "studio" / "voices",
        runner=runner,
    )


def test_voice_design_job_creates_reproducible_managed_profile_and_reuses_identity(
    tmp_path,
) -> None:
    async def scenario() -> None:
        runner = FakeVoiceDesignRunner()
        service = _service(tmp_path, runner)
        await service.start()
        try:
            first = await service.submit(
                label="Measured narrator",
                description="A measured, thoughtful alto voice",
                take=3,
            )
            await _wait_for(service, first.id, VoiceDesignJobStatus.COMPLETED)
            completed = service.store.get(first.id)
            profile = service.studio_store.get_voice_profile(completed.profile_id or "")

            assert profile.kind.value == "designed"
            assert profile.reference_text == QWEN_REFERENCE_TEXT
            assert profile.settings["design_take"] == 3
            assert profile.metadata["design_seed"] == 1003
            assert Path(profile.reference_audio_path or "").is_file()

            reused = await service.submit(
                label="A different label does not fork identity",
                description=" A measured, thoughtful alto voice ",
                take=3,
            )
            assert reused.id == completed.id
            assert runner.calls == [("A measured, thoughtful alto voice", 3)]

            another = await service.submit(
                label="Measured narrator take 4",
                description="A measured, thoughtful alto voice",
                take=4,
            )
            await _wait_for(service, another.id, VoiceDesignJobStatus.COMPLETED)
            assert another.id != first.id
            assert runner.calls[-1] == ("A measured, thoughtful alto voice", 4)
        finally:
            await service.stop()

    asyncio.run(scenario())


def test_voice_design_restart_finalizes_existing_atomic_result_without_redesign(
    tmp_path,
) -> None:
    async def scenario() -> None:
        runner = FakeVoiceDesignRunner()
        service = _service(tmp_path, runner)
        job = service.store.create_or_get(
            label="Recovered voice",
            description="A clear recovered narrator",
            take=2,
        )
        assert service.store.claim(job.id)
        directory = service.output_root / job.id
        output = directory / "reference.wav"
        result_path = directory / "design-result.json"
        _write_reference(output)
        result_path.write_text(
            json.dumps(
                {
                    "output_path": str(output.resolve()),
                    "reference_text": QWEN_REFERENCE_TEXT,
                    "model": QWEN_DESIGN_MODEL,
                    "seed": 1002,
                    "sample_rate": 24_000,
                    "seconds": 0.1,
                }
            ),
            encoding="utf-8",
        )

        await service.start()
        try:
            await _wait_for(service, job.id, VoiceDesignJobStatus.COMPLETED)
            assert runner.calls == []
            assert service.studio_store.get_voice_profile(job.id).reference_text == (
                QWEN_REFERENCE_TEXT
            )
        finally:
            await service.stop()

    asyncio.run(scenario())


def test_voice_design_cancel_stops_running_work_and_can_retry(tmp_path) -> None:
    async def scenario() -> None:
        runner = BlockingVoiceDesignRunner()
        service = _service(tmp_path, runner)
        await service.start()
        try:
            job = await service.submit(
                label="Cancelable voice",
                description="A voice that can be cancelled safely",
                take=1,
            )
            await _wait_for(service, job.id, VoiceDesignJobStatus.RUNNING)
            requested = await service.cancel(job.id)
            assert requested.status is VoiceDesignJobStatus.CANCEL_REQUESTED
            await _wait_for(service, job.id, VoiceDesignJobStatus.CANCELLED)
            assert service.store.get(job.id).profile_id is None
            assert runner.calls == 1

            recovery = FakeVoiceDesignRunner()
            service.runner = recovery
            retried = await service.retry(job.id)
            assert retried.status is VoiceDesignJobStatus.QUEUED
            await _wait_for(service, job.id, VoiceDesignJobStatus.COMPLETED)
            assert recovery.calls == [("A voice that can be cancelled safely", 1)]
        finally:
            await service.stop()

    asyncio.run(scenario())


def test_voice_design_restart_honors_persisted_cancel_request(tmp_path) -> None:
    async def scenario() -> None:
        runner = FakeVoiceDesignRunner()
        service = _service(tmp_path, runner)
        job = service.store.create_or_get(
            label="Previously cancelled voice",
            description="A voice cancelled before restart",
            take=1,
        )
        assert service.store.claim(job.id)
        assert service.store.request_cancel(job.id).status is (
            VoiceDesignJobStatus.CANCEL_REQUESTED
        )

        await service.start()
        try:
            assert service.store.get(job.id).status is VoiceDesignJobStatus.CANCELLED
            assert runner.calls == []
        finally:
            await service.stop()

    asyncio.run(scenario())


def test_voice_design_cancel_wins_completion_race_and_removes_profile(tmp_path) -> None:
    async def scenario() -> None:
        database = tmp_path / "splicr.sqlite3"
        studio = SqliteStudioStore(database)
        studio.initialize()
        store = CancelBeforeCompleteStore(database)
        store.initialize()
        service = VoiceDesignJobService(
            store=store,
            studio_store=studio,
            output_root=tmp_path / "studio" / "voices",
            runner=FakeVoiceDesignRunner(),
        )
        await service.start()
        try:
            job = await service.submit(
                label="Completion race",
                description="A voice cancelled at the completion boundary",
                take=1,
            )
            await _wait_for(service, job.id, VoiceDesignJobStatus.CANCELLED)
            assert service.store.get(job.id).profile_id is None
            try:
                studio.get_voice_profile(job.id)
            except KeyError:
                pass
            else:
                raise AssertionError("cancelled job left a managed voice profile behind")
        finally:
            await service.stop()

    asyncio.run(scenario())


def test_voice_design_api_surfaces_durable_status_retry_and_profile(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path, pacing_seconds=0)
    synthesis = SynthesisService(
        settings=settings,
        providers=ProviderRegistry([RecordingProvider()]),
    )
    runner = FakeVoiceDesignRunner(failures=1)
    designs = _service(tmp_path, runner)

    with TestClient(
        create_app(
            settings=settings,
            service=synthesis,
            voice_design_service=designs,
        )
    ) as client:
        created = client.post(
            "/v1/studio/voice-design/jobs",
            json={
                "label": "API narrator",
                "description": "A calm documentary voice",
                "take": 1,
            },
        )
        assert created.status_code == 202
        job_id = created.json()["id"]

        deadline = time.monotonic() + 3
        body = {}
        while time.monotonic() < deadline:
            body = client.get(f"/v1/studio/voice-design/jobs/{job_id}").json()
            if body["status"] == "failed":
                break
            time.sleep(0.01)
        assert body["error_code"] == "voice_design_failed"

        retried = client.post(f"/v1/studio/voice-design/jobs/{job_id}/retry")
        assert retried.status_code == 202
        while time.monotonic() < deadline + 3:
            body = client.get(f"/v1/studio/voice-design/jobs/{job_id}").json()
            if body["status"] == "completed":
                break
            time.sleep(0.01)
        assert body["status"] == "completed"
        assert body["profile"]["kind"] == "designed"
        assert body["profile"]["settings"]["design_take"] == 1
        assert client.get("/v1/studio/voice-design/jobs").json()[0]["id"] == job_id


def test_voice_design_api_cancels_running_worker_without_creating_profile(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path, pacing_seconds=0)
    synthesis = SynthesisService(
        settings=settings,
        providers=ProviderRegistry([RecordingProvider()]),
    )
    runner = BlockingVoiceDesignRunner()
    designs = _service(tmp_path, runner)

    with TestClient(
        create_app(
            settings=settings,
            service=synthesis,
            voice_design_service=designs,
        )
    ) as client:
        created = client.post(
            "/v1/studio/voice-design/jobs",
            json={
                "label": "Cancelled API narrator",
                "description": "A voice cancelled through the API",
                "take": 1,
            },
        )
        assert created.status_code == 202
        job_id = created.json()["id"]

        deadline = time.monotonic() + 3
        body = {}
        while time.monotonic() < deadline:
            body = client.get(f"/v1/studio/voice-design/jobs/{job_id}").json()
            if body["status"] == "running":
                break
            time.sleep(0.01)
        assert body["status"] == "running"

        cancelled = client.post(f"/v1/studio/voice-design/jobs/{job_id}/cancel")
        assert cancelled.status_code == 202
        assert cancelled.json()["status"] in {"cancel_requested", "cancelled"}
        while time.monotonic() < deadline:
            body = client.get(f"/v1/studio/voice-design/jobs/{job_id}").json()
            if body["status"] == "cancelled":
                break
            time.sleep(0.01)
        assert body["status"] == "cancelled"
        assert body["profile"] is None
        assert runner.calls == 1
