from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from splicr.bootstrap import create_service
from splicr.config import Settings


def test_bootstrap_registers_all_tts_providers_without_credentials(tmp_path) -> None:
    service = create_service(Settings(data_dir=tmp_path))

    providers = {info.name: info for info in service.providers.list()}

    assert list(providers) == ["gemini", "deepgram", "inworld"]
    assert providers["deepgram"].max_input_characters == 2_000
    assert providers["deepgram"].recommended_chunk_characters == 1_900
    assert providers["inworld"].max_input_characters == 2_000
    assert providers["inworld"].recommended_chunk_characters == 1_900
    assert providers["deepgram"].minimum_request_interval_seconds == 0
    assert providers["inworld"].minimum_request_interval_seconds == 0

    asyncio.run(service.providers.close())


def test_bootstrap_adds_configured_local_engines(tmp_path) -> None:
    service = create_service(
        Settings(
            data_dir=tmp_path,
            kokoro_python=Path(sys.executable),
            qwen3_python=Path(sys.executable),
            audio8_python=Path(sys.executable),
            edge_python=Path(sys.executable),
        )
    )

    providers = {info.name: info for info in service.providers.list()}

    assert list(providers) == [
        "gemini",
        "deepgram",
        "inworld",
        "kokoro-local",
        "qwen3-local",
        "audio8-local",
        "edge-tts",
    ]
    assert providers["kokoro-local"].default_model == "kokoro-82m"
    assert providers["kokoro-local"].default_voice == "af_heart"
    assert providers["kokoro-local"].max_input_tokens == 510
    assert providers["qwen3-local"].recommended_chunk_characters == 250
    assert providers["audio8-local"].recommended_chunk_characters == 150
    assert providers["edge-tts"].default_voice == "en-US-AriaNeural"
    assert providers["edge-tts"].max_input_bytes == 4_000

    asyncio.run(service.providers.close())
