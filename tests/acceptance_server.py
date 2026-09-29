"""Deterministic real-HTTP server used by the Playwright acceptance suite."""

from __future__ import annotations

import argparse
import atexit
import os
import tempfile
from pathlib import Path

import uvicorn

from splicr.api import create_app
from splicr.config import Settings
from splicr.domain import ControlCondition, ControlDefinition, ControlValueType
from splicr.providers import ProviderRegistry
from splicr.service import SynthesisService
from tests.fakes import RecordingProvider


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
    return create_app(settings=settings, service=synthesis)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    uvicorn.run(application(), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
