from __future__ import annotations

from fastapi.testclient import TestClient

from splicr.api import create_app
from splicr.config import Settings
from splicr.providers import ProviderRegistry
from splicr.providers.gemini import GeminiTtsProvider
from splicr.providers.inworld import InworldTtsProvider
from splicr.service import SynthesisService

from .fakes import RecordingProvider


def _client(tmp_path, provider) -> TestClient:
    settings = Settings(
        data_dir=tmp_path,
        pacing_seconds=0,
        backoff_base_seconds=0,
        backoff_max_seconds=0,
        backoff_jitter_seconds=0,
    )
    service = SynthesisService(
        settings=settings,
        providers=ProviderRegistry([provider]),
    )
    return TestClient(create_app(settings=settings, service=service))


def test_provider_metadata_exposes_ordered_gemini_controls_and_all_voices(tmp_path) -> None:
    with _client(tmp_path, GeminiTtsProvider()) as client:
        response = client.get("/v1/providers")

    assert response.status_code == 200
    provider = response.json()[0]
    capabilities = provider["capabilities"]
    assert capabilities["speech_paces"] == [
        "very_slow",
        "slow",
        "normal",
        "fast",
        "very_fast",
    ]
    assert capabilities["nonverbal_frequencies"] == [
        "never",
        "rare",
        "occasional",
        "frequent",
        "very_frequent",
    ]
    assert len(capabilities["voices"]) == 30
    assert {voice["id"] for voice in capabilities["voices"]} >= {"Kore", "Puck", "Sulafat"}
    assert capabilities["nonverbal_modes"] == ["inline_markup", "client_transform"]


def test_provider_specific_preflight_error_is_returned_as_validation_detail(tmp_path) -> None:
    with _client(tmp_path, InworldTtsProvider()) as client:
        response = client.post(
            "/v1/speech/preview",
            json={
                "text": "Hello.",
                "provider": "inworld",
                "model": "inworld-tts-1.5-mini",
                "controls": {"tone": "warm"},
            },
        )

    assert response.status_code == 422
    assert "require the inworld-tts-2 model" in response.json()["detail"]


def test_controls_are_validated_persisted_and_echoed(tmp_path) -> None:
    provider = RecordingProvider()
    with _client(tmp_path, provider) as client:
        response = client.post(
            "/v1/speech/jobs",
            json={
                "text": "A warm opening. A quiet ending.",
                "provider": "fake",
                "instructions": "Pause between sections.",
                "controls": {
                    "tone": "warm",
                    "pace": "slow",
                    "vocal_style": "audiobook",
                    "nonverbal_frequency": "occasional",
                },
            },
        )
        assert response.status_code == 202
        body = response.json()
        persisted = client.get(f"/v1/speech/jobs/{body['id']}").json()

    assert body["controls"] == {
        "tone": "warm",
        "pace": "slow",
        "vocal_style": "audiobook",
        "nonverbal_frequency": "occasional",
    }
    assert persisted["controls"] == body["controls"]
    assert persisted["instructions"] == "Pause between sections."


def test_unknown_control_preset_returns_validation_error(tmp_path) -> None:
    with _client(tmp_path, RecordingProvider()) as client:
        response = client.post(
            "/v1/speech/jobs",
            json={
                "text": "Hello.",
                "provider": "fake",
                "controls": {"tone": "laser_unicorn"},
            },
        )

    assert response.status_code == 422
