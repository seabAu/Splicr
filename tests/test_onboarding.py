from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from splicr.api import create_app
from splicr.config import Settings
from splicr.providers import ProviderRegistry
from splicr.service import SynthesisService
from splicr.studio.components import ComponentManager
from splicr.studio.engine_setup import EngineSetupManager
from splicr.studio.onboarding import SetupGuidePreferences

from .fakes import RecordingProvider


def test_setup_choice_is_durable_and_not_installation_consent(tmp_path) -> None:
    preferences = SetupGuidePreferences(tmp_path)
    assert preferences.read()["mode"] is None
    assert not preferences.path.exists()
    preferences.choose("local")
    assert SetupGuidePreferences(tmp_path).read()["mode"] == "local"
    assert json.loads(preferences.path.read_text("utf-8")) == {"schema_version": 1, "mode": "local"}


@pytest.mark.parametrize("mode", [None, [], {}, True, "install-everything"])
def test_invalid_setup_choices_do_not_write(tmp_path, mode) -> None:
    preferences = SetupGuidePreferences(tmp_path)
    with pytest.raises(ValueError, match="unknown setup"):
        preferences.choose(mode)
    assert not preferences.path.exists()


@pytest.mark.parametrize(
    "payload",
    ["broken", "[]", '{"schema_version":true,"mode":"local"}', " " * 4097, "[" * 1500 + "]" * 1500],
)
def test_corrupt_setup_preferences_are_bounded_and_not_rewritten(tmp_path, payload) -> None:
    preferences = SetupGuidePreferences(tmp_path)
    preferences.path.parent.mkdir(parents=True)
    preferences.path.write_text(payload, encoding="utf-8")
    state = preferences.read()
    assert state["mode"] is None
    assert state["preference_warning"]
    assert preferences.path.read_text("utf-8") == payload
    preferences.choose("later")
    assert preferences.read()["preference_warning"] is None


def test_failed_preference_write_preserves_previous_choice(tmp_path, monkeypatch) -> None:
    preferences = SetupGuidePreferences(tmp_path)
    preferences.choose("remote")

    def fail(*_):
        raise OSError("write unavailable")

    monkeypatch.setattr("splicr.studio.onboarding.os.replace", fail)
    with pytest.raises(OSError):
        preferences.choose("local")
    assert preferences.read()["mode"] == "remote"
    assert not list(preferences.path.parent.glob(".*.tmp"))


def test_setup_prompt_does_not_interrupt_existing_work_or_environments(tmp_path) -> None:
    preferences = SetupGuidePreferences(tmp_path)
    options = {"engines": [], "has_existing_work": False, "managed_setup_supported": True}
    assert preferences.status(**options)["prompt_required"]
    assert not preferences.status(**{**options, "has_existing_work": True})["prompt_required"]
    assert not preferences.status(**{**options, "engines": [{"path": "existing"}]})[
        "prompt_required"
    ]
    preferences.choose("later")
    assert not preferences.status(**options)["prompt_required"]


def _app(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path, pacing_seconds=0)
    service = SynthesisService(settings=settings, providers=ProviderRegistry([RecordingProvider()]))
    monkeypatch.setattr(ComponentManager, "status", lambda *_: {"engines": []})

    def no_install(*_, **__):
        raise AssertionError("A setup preference must never install software")

    monkeypatch.setattr(EngineSetupManager, "start", no_install)
    return create_app(settings=settings, service=service)


def test_first_run_choice_round_trips_without_creating_jobs(tmp_path, monkeypatch) -> None:
    with TestClient(
        _app(tmp_path, monkeypatch), base_url="http://127.0.0.1", client=("127.0.0.1", 1234)
    ) as client:
        response = client.get("/v1/studio/setup-guide")
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["prompt_required"]
        for choice in ("local", "remote", "later"):
            assert (
                client.put("/v1/studio/setup-guide", json={"mode": choice}).json()["mode"] == choice
            )
            assert not client.get("/v1/studio/setup-guide").json()["prompt_required"]
        assert (
            client.put(
                "/v1/studio/setup-guide", json={"mode": "local", "consent": True}
            ).status_code
            == 422
        )
        assert client.get("/v1/speech/jobs").json() == []
    assert SetupGuidePreferences(tmp_path).read()["mode"] == "later"


@pytest.mark.parametrize(
    "host, peer, origin",
    [
        ("http://127.0.0.1", "203.0.113.1", None),
        ("http://rebound.invalid", "127.0.0.1", None),
        ("http://127.0.0.1", "127.0.0.1", "https://untrusted.invalid"),
    ],
)
def test_setup_choice_rejects_remote_rebound_and_cross_origin_writes(
    tmp_path, monkeypatch, host, peer, origin
) -> None:
    with TestClient(_app(tmp_path, monkeypatch), base_url=host, client=(peer, 1234)) as client:
        headers = {"Origin": origin} if origin else {}
        assert client.get("/v1/studio/setup-guide", headers=headers).json()["enabled"] is False
        assert (
            client.put(
                "/v1/studio/setup-guide", json={"mode": "local"}, headers=headers
            ).status_code
            == 403
        )
    assert not SetupGuidePreferences(tmp_path).path.exists()


def test_existing_job_suppresses_first_run_prompt(tmp_path, monkeypatch) -> None:
    with TestClient(
        _app(tmp_path, monkeypatch), base_url="http://127.0.0.1", client=("127.0.0.1", 1234)
    ) as client:
        response = client.post(
            "/v1/speech/jobs", json={"text": "Existing narration.", "provider": "fake"}
        )
        assert response.status_code == 202
        assert not client.get("/v1/studio/setup-guide").json()["prompt_required"]
