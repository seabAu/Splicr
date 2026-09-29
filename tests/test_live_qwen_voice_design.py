from __future__ import annotations

import asyncio
import os
import wave
from pathlib import Path

import pytest

from splicr.studio.voice_design import (
    QWEN_REFERENCE_TEXT,
    SubprocessQwenVoiceDesignRunner,
)


@pytest.mark.live_engine
def test_live_qwen_voice_design_creates_cloneable_reference(tmp_path) -> None:
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
            take=1,
            output_path=output,
            result_path=result_path,
            should_cancel=lambda: False,
        )
    )

    assert result.reference_text == QWEN_REFERENCE_TEXT
    assert result.seed == 1001
    assert result_path.is_file()
    with wave.open(str(output), "rb") as recording:
        assert recording.getnchannels() == 1
        assert recording.getsampwidth() == 2
        assert recording.getframerate() == 24_000
        assert recording.getnframes() > 24_000
