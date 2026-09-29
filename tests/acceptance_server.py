"""Deterministic real-HTTP server used by the Playwright acceptance suite."""

from __future__ import annotations

import argparse
import atexit
import json
import os
import tempfile
import wave
from pathlib import Path

import uvicorn

from splicr.api import create_app
from splicr.config import Settings
from splicr.domain import ControlCondition, ControlDefinition, ControlValueType
from splicr.providers import ProviderRegistry
from splicr.service import SynthesisService
from splicr.studio import SqliteStudioStore
from splicr.studio.voice_design import (
    QWEN_DESIGN_MODEL,
    QWEN_REFERENCE_TEXT,
    VoiceDesignJobService,
    VoiceDesignJobStore,
    VoiceDesignResult,
)
from tests.fakes import RecordingProvider


class AcceptanceVoiceDesignRunner:
    async def design(
        self, *, description, take, output_path, result_path, should_cancel
    ):
        del description, should_cancel
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output_path), "wb") as recording:
            recording.setnchannels(1)
            recording.setsampwidth(2)
            recording.setframerate(24_000)
            recording.writeframes(b"\x00\x00" * 2_400)
        result = VoiceDesignResult(
            output_path=str(output_path.resolve()),
            reference_text=QWEN_REFERENCE_TEXT,
            model=QWEN_DESIGN_MODEL,
            seed=1000 + take,
            sample_rate=24_000,
            seconds=0.1,
        )
        result_path.write_text(
            json.dumps(
                {
                    "output_path": result.output_path,
                    "reference_text": result.reference_text,
                    "model": result.model,
                    "seed": result.seed,
                    "sample_rate": result.sample_rate,
                    "seconds": result.seconds,
                }
            ),
            encoding="utf-8",
        )
        return result


def _settings() -> Settings:
    configured = os.environ.get("SPLICR_ACCEPTANCE_DATA_DIR", "").strip()
    if configured:
        data_dir = Path(configured).expanduser().resolve()
        data_dir.mkdir(parents=True, exist_ok=True)
    else:
        temporary = tempfile.TemporaryDirectory(prefix="splicr-acceptance-")
        atexit.register(temporary.cleanup)
        data_dir = Path(temporary.name)
    return Settings(
        data_dir=data_dir,
        auth_enabled=False,
        backoff_base_seconds=0.001,
        backoff_max_seconds=0.002,
        backoff_jitter_seconds=0.0,
    )


def application():
    settings = _settings()
    primary = RecordingProvider(
        control_definitions=(
            ControlDefinition(
                key="temperature",
                value_type=ControlValueType.NUMBER,
                label="Performance variation",
                description="Controls how much delivery can vary between passages.",
                group="Generation",
                default=0.7,
                minimum=0.0,
                maximum=1.0,
                step=0.1,
            ),
            ControlDefinition(
                key="delivery_mode",
                label="Delivery mode",
                group="Generation",
                default="natural",
                choices=("natural", "dramatic"),
            ),
            ControlDefinition(
                key="seed",
                value_type=ControlValueType.INTEGER,
                label="Repeatable seed",
                group="Generation",
                minimum=0,
                visible_when=(ControlCondition("delivery_mode", "dramatic"),),
                randomizable=True,
            ),
            ControlDefinition(
                key="normalize_audio",
                value_type=ControlValueType.BOOLEAN,
                label="Normalize audio",
                description="Balance loudness before the take is assembled.",
                group="Output",
                default=True,
            ),
        ),
        allows_undeclared_variables=False,
    )
    alternate = RecordingProvider(
        provider_name="alternate-fake",
        control_definitions=(
            ControlDefinition(
                key="clarity",
                value_type=ControlValueType.INTEGER,
                label="Clarity",
                group="Voice",
                default=5,
                minimum=1,
                maximum=10,
            ),
        ),
        allows_undeclared_variables=False,
    )
    synthesis = SynthesisService(
        settings=settings,
        providers=ProviderRegistry([primary, alternate]),
    )
    studio = SqliteStudioStore(settings.database_path)
    studio.initialize()
    voice_designs = VoiceDesignJobService(
        store=VoiceDesignJobStore(settings.database_path),
        studio_store=studio,
        output_root=settings.data_dir / "studio" / "voices",
        runner=AcceptanceVoiceDesignRunner(),
    )
    return create_app(
        settings=settings,
        service=synthesis,
        voice_design_service=voice_designs,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    uvicorn.run(application(), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
