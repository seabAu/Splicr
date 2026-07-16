from __future__ import annotations

import asyncio

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
