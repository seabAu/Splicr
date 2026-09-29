from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from splicr.api import create_app
from splicr.config import Settings
from splicr.providers import ProviderRegistry
from splicr.service import SynthesisService
from splicr.studio.components import (
    ComponentConfigurationLockedError,
    ComponentManager,
)
from splicr.studio import components as component_module

from .fakes import RecordingProvider


def _settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path, pacing_seconds=0, max_attempts=1)


def _clear_engine_environment(monkeypatch) -> None:
    for name in (
        "SPLICR_KOKORO_PYTHON",
        "SPLICR_QWEN3_PYTHON",
        "SPLICR_AUDIO8_PYTHON",
        "SPLICR_EDGE_PYTHON",
        "SPLICR_WHISPER_PYTHON",
    ):
        monkeypatch.delenv(name, raising=False)


def test_saved_engine_path_applies_on_next_startup(tmp_path: Path, monkeypatch) -> None:
    _clear_engine_environment(monkeypatch)
    settings = _settings(tmp_path)
    manager = ComponentManager(settings)

    manager.save_engine("kokoro", sys.executable)
    pending = manager.status(settings)
    kokoro = next(item for item in pending["engines"] if item["id"] == "kokoro")
    assert pending["restart_required"] is True
    assert kokoro["state"] == "restart_required"
    assert kokoro["active_path"] is None

    applied = manager.apply(settings)
    active = manager.status(applied)
    kokoro = next(item for item in active["engines"] if item["id"] == "kokoro")
    assert applied.kokoro_python == Path(sys.executable).resolve()
    assert active["restart_required"] is False
    assert kokoro["state"] == "configured"
    assert kokoro["source"] == "studio"


def test_environment_path_is_authoritative_and_ui_locked(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    monkeypatch.setenv("SPLICR_QWEN3_PYTHON", sys.executable)
    manager = ComponentManager(settings)

    active = manager.apply(settings)
    qwen = next(item for item in manager.status(active)["engines"] if item["id"] == "qwen3")

    assert active.qwen3_python == settings.qwen3_python
    assert qwen["locked"] is True
    assert qwen["source"] == "environment"
    try:
        manager.save_engine("qwen3", sys.executable)
    except ComponentConfigurationLockedError as error:
        assert "SPLICR_QWEN3_PYTHON" in str(error)
    else:
        raise AssertionError("environment-controlled engine was editable")


def test_malformed_component_file_is_ignored_safely(tmp_path: Path, monkeypatch) -> None:
    _clear_engine_environment(monkeypatch)
    settings = _settings(tmp_path)
    path = tmp_path / "studio" / "components.json"
    path.parent.mkdir(parents=True)
    path.write_text("not-json", encoding="utf-8")

    manager = ComponentManager(settings)

    assert manager.apply(settings) == settings
    assert len(manager.status(settings)["engines"]) == 5


def test_component_api_persists_validated_engine_paths(tmp_path: Path, monkeypatch) -> None:
    _clear_engine_environment(monkeypatch)
    settings = _settings(tmp_path)
    synthesis = SynthesisService(
        settings=settings,
        providers=ProviderRegistry([RecordingProvider()]),
    )
    monkeypatch.setattr(
        ComponentManager,
        "refresh_edge_voices",
        lambda self, active_settings: {
            "count": 2,
            "refreshed_at": "2026-09-29T00:00:00+00:00",
            "path": str(tmp_path / "studio" / "edge-voices.json"),
        },
    )

    with TestClient(create_app(settings=settings, service=synthesis)) as client:
        initial = client.get("/v1/studio/components")
        assert initial.status_code == 200
        assert {item["id"] for item in initial.json()["engines"]} == {
            "kokoro",
            "qwen3",
            "audio8",
            "edge",
            "whisper",
        }
        refreshed = client.post("/v1/studio/components/engines/edge/voices/refresh")
        assert refreshed.status_code == 200
        assert refreshed.json()["count"] == 2

        invalid = client.put(
            "/v1/studio/components/engines/kokoro",
            json={"python_path": str(tmp_path / "missing-python")},
        )
        assert invalid.status_code == 422

        saved = client.put(
            "/v1/studio/components/engines/kokoro",
            json={"python_path": sys.executable},
        )
        assert saved.status_code == 200
        assert saved.json()["restart_required"] is True
        persisted = json.loads((tmp_path / "studio" / "components.json").read_text("utf-8"))
        assert persisted["engines"]["kokoro"]["python"] == str(Path(sys.executable).resolve())

        cleared = client.delete("/v1/studio/components/engines/kokoro")
        assert cleared.status_code == 200
        assert cleared.json()["restart_required"] is False


def test_edge_voice_refresh_is_explicit_and_atomically_cached(tmp_path, monkeypatch) -> None:
    settings = Settings(data_dir=tmp_path, edge_python=Path(sys.executable))
    manager = ComponentManager(settings)
    payload = {
        "voices": [
            {
                "short_name": "en-US-AriaNeural",
                "locale": "en-US",
                "gender": "Female",
                "personalities": [],
            }
        ]
    }
    monkeypatch.setattr(
        component_module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(payload),
            stderr="",
        ),
    )

    refreshed = manager.refresh_edge_voices(settings)

    assert refreshed["count"] == 1
    cached = json.loads((tmp_path / "studio" / "edge-voices.json").read_text("utf-8"))
    assert cached["voices"] == payload["voices"]
    edge = next(item for item in manager.status(settings)["engines"] if item["id"] == "edge")
    assert edge["voice_catalog"]["count"] == 1
