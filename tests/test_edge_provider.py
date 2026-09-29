from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from splicr import engine_worker
from splicr.domain import AudioChunk, DeliveryControls, SpeechPace, SynthesisOptions
from splicr.providers.edge import EDGE_DEFAULT_VOICE, EdgeTtsProvider


def test_edge_provider_uses_cached_voices_and_typed_controls(tmp_path: Path) -> None:
    cache = tmp_path / "edge-voices.json"
    cache.write_text(
        json.dumps(
            {
                "voices": [
                    {
                        "short_name": "en-GB-SoniaNeural",
                        "locale": "en-GB",
                        "gender": "Female",
                        "personalities": ["Friendly"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    provider = EdgeTtsProvider(Path(sys.executable), voice_cache_path=cache)

    assert provider.info.name == "edge-tts"
    assert provider.info.default_voice == EDGE_DEFAULT_VOICE
    assert provider.info.capabilities.voices[0].id == "en-GB-SoniaNeural"
    controls = {item.key: item for item in provider.info.capabilities.control_definitions}
    assert controls["rate_percent"].minimum == -50
    assert controls["timing_boundary"].choices == ("sentence", "word")
    assert provider.create_engine_adapter().descriptor.id == "edge-tts"


def test_edge_runtime_streams_timing_and_normalizes_with_ffmpeg(monkeypatch, tmp_path) -> None:
    calls = {}

    class Communicate:
        def __init__(self, text, voice, **kwargs):
            calls.update(text=text, voice=voice, **kwargs)

        async def stream(self):
            yield {"type": "audio", "data": b"fake-mp3"}
            yield {
                "type": "WordBoundary",
                "offset": 5_000_000,
                "duration": 2_500_000,
                "text": "Hello",
            }

    fake_module = SimpleNamespace(Communicate=Communicate)
    original_import = engine_worker.importlib.import_module
    monkeypatch.setattr(
        engine_worker.importlib,
        "import_module",
        lambda name: fake_module if name == "edge_tts" else original_import(name),
    )
    monkeypatch.setattr(engine_worker.shutil, "which", lambda name: "ffmpeg")
    monkeypatch.setattr(
        engine_worker.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=b"\x01\x00" * 240,
            stderr=b"",
        ),
    )
    output = tmp_path / "chunk.pcm"
    runtime = engine_worker.EdgeRuntime()
    metadata = runtime.synthesize(
        "Hello",
        {
            "voice": "en-US-AriaNeural",
            "variables": {
                "pitch_hz": 4,
                "volume_percent": -5,
                "timing_boundary": "word",
            },
            "controls": {"pace": SpeechPace.FAST.value},
        },
        output,
    )

    assert output.read_bytes() == b"\x01\x00" * 240
    assert calls == {
        "text": "Hello",
        "voice": "en-US-AriaNeural",
        "rate": "+15%",
        "volume": "-5%",
        "pitch": "+4Hz",
        "boundary": "WordBoundary",
    }
    assert metadata == {
        "timings": [
            {
                "type": "WordBoundary",
                "start_seconds": 0.5,
                "duration_seconds": 0.25,
                "text": "Hello",
            }
        ],
        "timing_boundary": "word",
    }


def test_edge_runtime_classifies_offline_failure(monkeypatch) -> None:
    class ClientConnectorError(RuntimeError):
        pass

    class Communicate:
        def __init__(self, *args, **kwargs):
            pass

        async def stream(self):
            raise ClientConnectorError("network unavailable")
            yield

    fake_module = SimpleNamespace(Communicate=Communicate)
    original_import = engine_worker.importlib.import_module
    monkeypatch.setattr(
        engine_worker.importlib,
        "import_module",
        lambda name: fake_module if name == "edge_tts" else original_import(name),
    )
    monkeypatch.setattr(engine_worker.shutil, "which", lambda name: "ffmpeg")
    runtime = engine_worker.EdgeRuntime()

    with pytest.raises(engine_worker.EngineWorkerRequestError) as raised:
        runtime.synthesize(
            "Hello",
            {
                "voice": "en-US-AriaNeural",
                "variables": {},
                "controls": {"pace": "normal"},
            },
            Path("unused.pcm"),
        )
    assert raised.value.code == "edge_offline"
    assert raised.value.retryable is True


def test_edge_voice_tool_normalizes_catalog(monkeypatch) -> None:
    async def list_voices():
        return [
            {
                "ShortName": "fr-FR-DeniseNeural",
                "Locale": "fr-FR",
                "Gender": "Female",
                "VoiceTag": {"VoicePersonalities": ["Friendly"]},
            },
            {
                "ShortName": "en-US-AriaNeural",
                "Locale": "en-US",
                "Gender": "Female",
                "VoiceTag": {},
            },
        ]

    fake_module = SimpleNamespace(list_voices=list_voices)
    original_import = engine_worker.importlib.import_module
    monkeypatch.setattr(
        engine_worker.importlib,
        "import_module",
        lambda name: fake_module if name == "edge_tts" else original_import(name),
    )

    result = engine_worker._tool_edge_voices({})

    assert [voice["short_name"] for voice in result["voices"]] == [
        "en-US-AriaNeural",
        "fr-FR-DeniseNeural",
    ]


def test_audio_chunk_metadata_is_provider_neutral() -> None:
    options = SynthesisOptions(
        model="edge-tts",
        voice="en-US-AriaNeural",
        controls=DeliveryControls(pace=SpeechPace.NORMAL),
    )
    provider = EdgeTtsProvider(Path(sys.executable), voice_cache_path=Path("missing.json"))
    assert provider.estimate_input_tokens("héllo", options) == len("héllo".encode("utf-8"))
    audio = AudioChunk(pcm=b"\x00\x00", metadata={"timings": [{"text": "hello"}]})
    assert audio.metadata["timings"] == [{"text": "hello"}]
