from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

import pytest

from splicr.domain import SynthesisOptions
from splicr.providers.edge import EDGE_DEFAULT_VOICE, EDGE_MODEL, EdgeTtsProvider
from splicr.studio import EngineSessionContext


@pytest.mark.live_provider
@pytest.mark.live_engine
def test_live_edge_tts_streams_canonical_audio_and_timing(tmp_path: Path) -> None:
    if os.getenv("SPLICR_LIVE_EDGE_TTS") != "1":
        pytest.skip("set SPLICR_LIVE_EDGE_TTS=1 to call the live Edge TTS service")
    executable_value = os.getenv("SPLICR_EDGE_PYTHON", "").strip()
    if not executable_value:
        pytest.skip("SPLICR_EDGE_PYTHON is not configured")
    executable = Path(executable_value).expanduser().resolve()
    if not executable.is_file():
        pytest.fail(f"configured Edge TTS Python does not exist: {executable}")
    if shutil.which("ffmpeg") is None:
        pytest.fail("ffmpeg is required for Edge TTS normalization")

    provider = EdgeTtsProvider(
        executable,
        voice_cache_path=tmp_path / "edge-voices.json",
        startup_timeout_seconds=30,
        request_timeout_seconds=60,
    )

    async def scenario():
        context = EngineSessionContext(
            job_id="live-edge",
            take_id="live-edge",
            work_directory=(tmp_path / "job").resolve(),
        )
        async with provider.create_engine_adapter().open_session(context) as session:
            return await session.synthesize(
                "This is a short SPLICR Edge TTS acceptance check.",
                SynthesisOptions(
                    model=EDGE_MODEL,
                    voice=EDGE_DEFAULT_VOICE,
                    variables={"timing_boundary": "word"},
                ),
            )

    audio = asyncio.run(scenario())

    assert audio.pcm
    assert len(audio.pcm) % 2 == 0
    assert audio.format.sample_rate == 24_000
    assert audio.format.channels == 1
    assert audio.format.sample_width == 2
    assert audio.metadata["timing_boundary"] == "word"
    assert audio.metadata["timings"]
