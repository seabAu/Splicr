from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace

from splicr import __main__ as cli
from splicr.domain import DeliveryControls, JobRecord, JobStatus, utc_now


def _job(status: JobStatus, *, error: str | None = None) -> JobRecord:
    now = utc_now()
    return JobRecord(
        id="job-1",
        status=status,
        provider="fake",
        model="model",
        voice="voice",
        instructions=None,
        controls=DeliveryControls(),
        total_chunks=1,
        completed_chunks=0,
        error=error,
        error_detail=None,
        output_path=None,
        created_at=now,
        updated_at=now,
    )


def test_file_cli_returns_when_provider_error_pauses_job(monkeypatch, tmp_path, capsys) -> None:
    class FakeService:
        def __init__(self) -> None:
            self.stopped = False

        async def start(self) -> None:
            pass

        async def submit(self, **_: object) -> JobRecord:
            return _job(JobStatus.QUEUED)

        def get_job(self, _job_id: str) -> JobRecord:
            return replace(_job(JobStatus.PAUSED), error="local engine unavailable")

        async def stop(self) -> None:
            self.stopped = True

    service = FakeService()
    monkeypatch.setattr(cli, "create_service", lambda _settings: service)
    source = tmp_path / "input.txt"
    source.write_text("hello", encoding="utf-8")
    args = argparse.Namespace(
        input=source,
        output=tmp_path / "output.wav",
        provider="fake",
        model=None,
        voice=None,
        instructions=None,
        tone="neutral",
        pace="normal",
        vocal_style="natural",
        nonverbal_frequency="never",
    )

    result = asyncio.run(cli._synthesize_file(args))

    assert result == 1
    assert service.stopped is True
    assert "Synthesis stopped (paused): local engine unavailable" in capsys.readouterr().err
