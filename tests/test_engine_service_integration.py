from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from splicr.config import Settings
from splicr.domain import JobStatus, TtsProvider
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
