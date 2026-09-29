from __future__ import annotations

import os
from pathlib import Path

import pytest

from splicr.studio.transcription import FasterWhisperProvider, TranscriptionOptions


@pytest.mark.live_engine
def test_live_faster_whisper_transcribes_real_audio(tmp_path: Path) -> None:
    python_value = os.getenv("SPLICR_WHISPER_PYTHON", "").strip()
    audio_value = os.getenv("SPLICR_LIVE_TRANSCRIPTION_AUDIO", "").strip()
    if not python_value or not audio_value:
        pytest.skip(
            "set SPLICR_WHISPER_PYTHON and SPLICR_LIVE_TRANSCRIPTION_AUDIO for live ASR acceptance"
        )
    python_path = Path(python_value).expanduser().resolve()
    audio_path = Path(audio_value).expanduser().resolve()
    if not python_path.is_file() or not audio_path.is_file():
        pytest.skip("configured live transcription interpreter or audio fixture does not exist")
    provider = FasterWhisperProvider(
        python_path=python_path,
        worker_path=Path(__file__).resolve().parents[1]
        / "src"
        / "splicr"
        / "transcription_worker.py",
        download_root=tmp_path / "models",
    )
    progress: list[float] = []

    import asyncio

    result = asyncio.run(
        provider.transcribe(
            audio_path,
            TranscriptionOptions(
                model=os.getenv("SPLICR_LIVE_TRANSCRIPTION_MODEL", "tiny"),
                word_timestamps=True,
            ),
            on_progress=lambda value, *_: progress.append(value),
            is_cancelled=lambda: False,
        )
    )

    assert result.segments
    assert result.duration_seconds > 0
    assert any(segment.words for segment in result.segments)
    assert progress
