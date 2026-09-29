from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from splicr.domain import ProviderCapabilities, ProviderError, ProviderInfo, SynthesisOptions
from splicr.studio import (
    EngineDescriptor,
    EngineSessionContext,
    EngineTransport,
    LocalSubprocessEngineAdapter,
    LocalSubprocessSpec,
)


FAKE_WORKER = r'''
import json
import os
import pathlib
import sys
import time

engine = sys.argv[1]
marker = pathlib.Path(sys.argv[2])
marker.write_text(marker.read_text() + "start\n" if marker.exists() else "start\n")
start_count = len(marker.read_text().splitlines())

def emit(value):
    print(json.dumps(value, separators=(",", ":")), flush=True)

emit({"type": "ready", "protocol": 1, "engine": engine})
for line in sys.stdin:
    message = json.loads(line)
    if message["type"] == "shutdown":
        raise SystemExit(0)
    request_id = message["id"]
    text = message["text"]
    if text == "worker error":
        emit({
            "type": "error",
            "id": request_id,
            "message": "deliberate worker failure",
            "retryable": False,
        })
        continue
    if text == "timeout once" and start_count == 1:
        time.sleep(5)
    output = pathlib.Path(message["output_path"])
    output.write_bytes(b"\x00\x00" * max(1, len(text)))
    emit({"type": "event", "level": "info", "message": "rendered"})
    emit({
        "type": "result",
        "id": request_id,
        "output_path": str(output),
        "audio_format": {
            "sample_rate": 24000,
            "channels": 1,
            "sample_width": 2,
            "encoding": "pcm_s16le",
        },
        "metadata": {"timings": [{"text": text, "start_seconds": 0.0}]},
    })
'''


def _adapter(
    tmp_path: Path,
    *,
    request_timeout_seconds: float = 2.0,
) -> tuple[LocalSubprocessEngineAdapter, EngineSessionContext, Path]:
    worker = tmp_path / "fake_worker.py"
    worker.write_text(FAKE_WORKER, encoding="utf-8")
    marker = tmp_path / "starts.txt"
    info = ProviderInfo(
        name="fake-local",
        default_model="fake-model",
        default_voice="fake-voice",
        max_input_bytes=1_000,
        max_input_tokens=1_000,
        capabilities=ProviderCapabilities(models=("fake-model",)),
    )
    adapter = LocalSubprocessEngineAdapter(
        EngineDescriptor(
            id="fake-local",
            display_name="Fake local",
            transport=EngineTransport.LOCAL_SUBPROCESS,
            provider_info=info,
        ),
        LocalSubprocessSpec(
            command=(sys.executable, str(worker), "fake-local", str(marker)),
            startup_timeout_seconds=2,
            request_timeout_seconds=request_timeout_seconds,
            shutdown_timeout_seconds=1,
        ),
    )
    context = EngineSessionContext(
        job_id="job-1",
        take_id="take-1",
        work_directory=(tmp_path / "job").resolve(),
    )
    return adapter, context, marker


def test_local_worker_is_reused_and_returns_canonical_pcm(tmp_path: Path) -> None:
    async def scenario() -> None:
        adapter, context, marker = _adapter(tmp_path)
        options = SynthesisOptions(model="fake-model", voice="fake-voice")
        async with adapter.open_session(context) as session:
            first = await session.synthesize("first", options)
            second = await session.synthesize("second", options)

        assert first.pcm == b"\x00\x00" * len("first")
        assert second.pcm == b"\x00\x00" * len("second")
        assert first.format.sample_rate == 24_000
        assert first.metadata == {
            "timings": [{"text": "first", "start_seconds": 0.0}]
        }
        assert marker.read_text(encoding="utf-8").splitlines() == ["start"]
        assert not list((context.work_directory / ".engine").glob("*.pcm"))

    asyncio.run(scenario())


def test_local_worker_error_preserves_engine_diagnostics(tmp_path: Path) -> None:
    async def scenario() -> None:
        adapter, context, _ = _adapter(tmp_path)
        options = SynthesisOptions(model="fake-model", voice="fake-voice")
        async with adapter.open_session(context) as session:
            with pytest.raises(ProviderError, match="deliberate worker failure") as caught:
                await session.synthesize("worker error", options)

        assert caught.value.retryable is False
        assert caught.value.origin == "engine"
        assert caught.value.diagnostic is not None
        assert caught.value.diagnostic.category == "local_engine"
        assert caught.value.diagnostic.phase == "synthesis"
        assert caught.value.diagnostic.provider == "fake-local"

    asyncio.run(scenario())


def test_local_worker_timeout_restarts_before_the_next_attempt(tmp_path: Path) -> None:
    async def scenario() -> None:
        adapter, context, marker = _adapter(tmp_path, request_timeout_seconds=0.1)
        options = SynthesisOptions(model="fake-model", voice="fake-voice")
        async with adapter.open_session(context) as session:
            with pytest.raises(ProviderError, match="timed out") as caught:
                await session.synthesize("timeout once", options)
            recovered = await session.synthesize("timeout once", options)

        assert caught.value.retryable is True
        assert recovered.pcm == b"\x00\x00" * len("timeout once")
        assert marker.read_text(encoding="utf-8").splitlines() == ["start", "start"]

    asyncio.run(scenario())
