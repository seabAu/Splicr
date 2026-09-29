from __future__ import annotations

import asyncio
import struct
import threading
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi.testclient import TestClient

from splicr.api import create_app
from splicr.config import Settings
from splicr.domain import AudioChunk, JobStatus, ProviderError, SynthesisOptions, TtsProvider
from splicr.providers import ProviderRegistry
from splicr.service import SynthesisService
from splicr.studio import EngineSession, EngineSessionContext, ProviderEngineAdapter
from tests.fakes import RecordingProvider


class TrackingProviderAdapter(ProviderEngineAdapter):
    def __init__(self, provider: TtsProvider) -> None:
        super().__init__(provider)
        self.contexts: list[EngineSessionContext] = []
        self.closed_sessions = 0

    @asynccontextmanager
    async def open_session(
        self,
        context: EngineSessionContext,
    ) -> AsyncIterator[EngineSession]:
        self.contexts.append(context)
        try:
            async with super().open_session(context) as session:
                yield session
        finally:
            self.closed_sessions += 1


class FailingLocalSession:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def synthesize(self, text: str, options: SynthesisOptions) -> AudioChunk:
        self.calls.append(text)
        if "bad" in text:
            raise ProviderError(
                "local model rejected the segment",
                retryable=False,
                origin="engine",
            )
        return AudioChunk(pcm=struct.pack("<h", 17) * 4)


class FailingLocalAdapter(ProviderEngineAdapter):
    def __init__(self, provider: TtsProvider) -> None:
        super().__init__(provider)
        self.session = FailingLocalSession()
        self.opened_sessions = 0
        self.closed_sessions = 0

    @asynccontextmanager
    async def open_session(
        self,
        context: EngineSessionContext,
    ) -> AsyncIterator[EngineSession]:
        self.opened_sessions += 1
        try:
            yield self.session
        finally:
            self.closed_sessions += 1


class SlowLocalSession:
    def __init__(self, started: threading.Event) -> None:
        self.started = started

    async def synthesize(self, text: str, options: SynthesisOptions) -> AudioChunk:
        self.started.set()
        await asyncio.sleep(0.15)
        return AudioChunk(pcm=struct.pack("<h", 21) * 4)


class SlowLocalAdapter(ProviderEngineAdapter):
    def __init__(self, provider: TtsProvider) -> None:
        super().__init__(provider)
        self.started = threading.Event()
        self.closed = threading.Event()
        self.opened_sessions = 0
        self.closed_sessions = 0

    @asynccontextmanager
    async def open_session(
        self,
        context: EngineSessionContext,
    ) -> AsyncIterator[EngineSession]:
        self.opened_sessions += 1
        try:
            yield SlowLocalSession(self.started)
        finally:
            self.closed_sessions += 1
            self.closed.set()


async def _wait_for_terminal(service: SynthesisService, job_id: str):
    async def poll():
        while True:
            job = service.get_job(job_id)
            if job.status in {JobStatus.COMPLETED, JobStatus.PAUSED, JobStatus.CANCELLED}:
                return job
            await asyncio.sleep(0.01)

    return await asyncio.wait_for(poll(), timeout=3)


def test_service_reuses_one_engine_session_for_all_uncached_chunks(tmp_path) -> None:
    async def scenario() -> None:
        provider = RecordingProvider()
        adapter = TrackingProviderAdapter(provider)
        service = SynthesisService(
            settings=Settings(
                data_dir=tmp_path,
                chunk_max_bytes=10_000,
                chunk_max_words=2,
                pacing_seconds=0,
            ),
            providers=ProviderRegistry([provider]),
            engine_adapter_factory=lambda _: adapter,
        )
        await service.start()
        try:
            submitted = await service.submit(
                text="one two\n\nthree four\n\nfive six",
                provider_name="fake",
            )
            finished = await _wait_for_terminal(service, submitted.id)
        finally:
            await service.stop()

        assert finished.status is JobStatus.COMPLETED
        assert provider.calls == ["one two", "three four", "five six"]
        assert len(adapter.contexts) == 1
        assert adapter.contexts[0].job_id == submitted.id
        assert adapter.contexts[0].take_id == submitted.id
        assert adapter.contexts[0].project_id is None
        assert adapter.contexts[0].render_plan_id is None
        assert adapter.closed_sessions == 1

    asyncio.run(scenario())


def test_local_engine_failure_closes_session_and_allows_export_then_cancel(tmp_path) -> None:
    provider = RecordingProvider(provider_name="fake-local")
    adapter = FailingLocalAdapter(provider)
    settings = Settings(
        data_dir=tmp_path,
        chunk_max_bytes=10_000,
        chunk_max_words=2,
        pacing_seconds=0,
        max_attempts=1,
    )
    service = SynthesisService(
        settings=settings,
        providers=ProviderRegistry([provider]),
        engine_adapter_factory=lambda _: adapter,
    )

    with TestClient(create_app(settings=settings, service=service)) as client:
        submitted = client.post(
            "/v1/speech/jobs",
            json={
                "text": "good words\n\nbad words",
                "provider": "fake-local",
            },
        ).json()
        for _ in range(300):
            paused = client.get(f"/v1/speech/jobs/{submitted['id']}").json()
            if paused["status"] == "paused":
                break
            time.sleep(0.01)
        else:
            raise AssertionError("local engine failure did not pause the job")

        assert paused["completed_chunks"] == 1
        assert paused["error_detail"] == "local model rejected the segment"
        assert adapter.opened_sessions == 1
        assert adapter.closed_sessions == 1
        partial = client.get(paused["partial_audio_url"])
        assert partial.status_code == 200
        assert partial.headers["x-splicr-partial"] == "true"
        export = client.get(paused["checkpoint_export_url"])
        assert export.status_code == 200
        assert export.headers["x-splicr-exported-chunks"] == "1"

        cancelled = client.post(f"/v1/speech/jobs/{submitted['id']}/cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"
        assert client.get(f"/v1/speech/jobs/{submitted['id']}/audio").status_code == 409


def test_local_engine_session_closes_after_cancelled_inflight_job(tmp_path) -> None:
    provider = RecordingProvider(provider_name="fake-local")
    adapter = SlowLocalAdapter(provider)
    settings = Settings(
        data_dir=tmp_path,
        chunk_max_bytes=10_000,
        chunk_max_words=100,
        pacing_seconds=0,
    )
    service = SynthesisService(
        settings=settings,
        providers=ProviderRegistry([provider]),
        engine_adapter_factory=lambda _: adapter,
    )

    with TestClient(create_app(settings=settings, service=service)) as client:
        submitted = client.post(
            "/v1/speech/jobs",
            json={"text": "cancel local work", "provider": "fake-local"},
        ).json()
        assert adapter.started.wait(timeout=2)
        cancelled = client.post(f"/v1/speech/jobs/{submitted['id']}/cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"
        assert adapter.closed.wait(timeout=2)

    assert adapter.opened_sessions == 1
    assert adapter.closed_sessions == 1
