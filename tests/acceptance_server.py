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
    synthesis = SynthesisService(
        settings=settings,
        providers=ProviderRegistry([RecordingProvider()]),
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
