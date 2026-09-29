from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from splicr.domain import ProviderError, SpeechPace, SynthesisOptions
from splicr.engine_worker import _apply_pronunciation_overrides, _kokoro_speed
from splicr.providers.kokoro import KokoroTtsProvider
from splicr.studio import EngineTransport, engine_adapter_for_provider


def test_kokoro_provider_builds_isolated_job_scoped_adapter() -> None:
    provider = KokoroTtsProvider(Path(sys.executable))
    adapter = engine_adapter_for_provider(provider)

    assert provider.info.name == "kokoro-local"
    assert provider.info.default_voice == "af_heart"
    assert provider.info.capabilities.speech_paces == tuple(SpeechPace)
    speed = provider.info.capabilities.control_definitions[0]
    assert (speed.key, speed.minimum, speed.maximum, speed.unit) == (
        "speed",
        0.5,
        2.0,
        "×",
    )
    assert adapter.descriptor.transport is EngineTransport.LOCAL_SUBPROCESS
    assert adapter.descriptor.provider_info is provider.info
    assert adapter.spec.command[0] == str(Path(sys.executable).resolve())
    assert adapter.spec.command[-2:] == ("--engine", "kokoro-local")


def test_kokoro_provider_refuses_stateless_synthesis() -> None:
    async def scenario() -> None:
        provider = KokoroTtsProvider(Path(sys.executable))
        with pytest.raises(ProviderError, match="job-scoped"):
            await provider.synthesize(
                "hello",
                SynthesisOptions(model="kokoro-82m", voice="af_heart"),
            )

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("pace", "expected"),
    [
        ("very_slow", 0.70),
        ("slow", 0.85),
        ("normal", 1.0),
        ("fast", 1.15),
        ("very_fast", 1.30),
    ],
)
def test_kokoro_worker_maps_studio_pacing(pace: str, expected: float) -> None:
    assert _kokoro_speed({"controls": {"pace": pace}}) == expected


def test_kokoro_worker_accepts_bounded_numeric_speed_override() -> None:
    assert _kokoro_speed(
        {
            "variables": {"speed": 1.37},
            "controls": {"pace": "very_slow"},
        }
    ) == 1.37
    with pytest.raises(ValueError, match="between 0.5 and 2.0"):
        _kokoro_speed({"variables": {"speed": 3.0}})


def test_kokoro_worker_applies_frozen_pronunciation_snapshot() -> None:
    class Lexicon:
        golds = {"existing": "old"}

    class G2p:
        lexicon = Lexicon()

    class Pipeline:
        g2p = G2p()

    applied = _apply_pronunciation_overrides(
        Pipeline(),
        {
            "variables": {
                "__splicr_pronunciations": {
                    "SPLICR": "splɪkɚ",
                    "blank": " ",
                    "invalid": 42,
                }
            }
        },
    )

    assert applied == 1
    assert Lexicon.golds == {"existing": "old", "splicr": "splɪkɚ"}
