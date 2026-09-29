from __future__ import annotations

import io
import struct
import sys
import wave
from pathlib import Path

from fastapi.testclient import TestClient

from splicr.api import create_app
from splicr.bootstrap import create_service
from splicr.config import Settings
from splicr.studio import VoiceProfile, VoiceProfileKind
from splicr.studio.voice_resolution import VOICE_PROFILE_VARIABLE


def _wav_bytes(seconds: float = 2.1) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as recording:
        recording.setnchannels(1)
        recording.setsampwidth(2)
        recording.setframerate(24_000)
        recording.writeframes(struct.pack("<h", 200) * int(24_000 * seconds))
    return output.getvalue()


def _app(tmp_path):
    settings = Settings(
        data_dir=tmp_path,
        pacing_seconds=0,
        qwen3_python=Path(sys.executable),
        audio8_python=Path(sys.executable),
    )
    return create_app(settings=settings, service=create_service(settings))


def test_preview_resolves_qwen_voice_profile_and_rejects_mismatch(tmp_path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as client:
        created = client.post(
            "/v1/studio/voices/reference",
            data={
                "label": "Reference narrator",
                "engine_id": "qwen3",
                "reference_text": "These are the exact spoken words.",
                "kind": "cloned",
            },
            files={"file": ("reference.wav", _wav_bytes(), "audio/wav")},
        )
        assert created.status_code == 201
        voice_id = created.json()["id"]

        preview = client.post(
            "/v1/speech/preview",
            json={
                "text": "A short document for planning.",
                "provider": "qwen3-local",
                "voice_profile_id": voice_id,
            },
        )
        mismatch = client.post(
            "/v1/speech/preview",
            json={
                "text": "A short document for planning.",
                "provider": "audio8-local",
                "voice_profile_id": voice_id,
            },
        )
        directions = client.post(
            "/v1/speech/preview",
            json={
                "text": "A short document for planning.",
                "provider": "qwen3-local",
                "voice_profile_id": voice_id,
                "instructions": "Whisper this passage.",
            },
        )

    assert preview.status_code == 200
    assert len(preview.json()["chunks"]) == 1
    assert mismatch.status_code == 422
    assert "requires provider 'qwen3-local'" in mismatch.json()["detail"]
    assert directions.status_code == 422
    assert "preset speakers" in directions.json()["detail"]


def test_profile_persists_voice_profile_selection_and_reserved_snapshot_is_write_protected(
    tmp_path,
) -> None:
    app = _app(tmp_path)
    with TestClient(app) as client:
        voice = client.post(
            "/v1/studio/voices/presets",
            json={
                "label": "Announcer",
                "engine_id": "qwen3",
                "voice_id": "Ryan",
                "instructions": "Bright and concise",
            },
        ).json()
        profile = client.post(
            "/v1/profiles",
            json={
                "name": "Qwen announcement",
                "resource_id": "qwen3-local",
                "text": "Welcome.",
                "voice_profile_id": voice["id"],
            },
        )
        forged = client.post(
            "/v1/speech/preview",
            json={
                "text": "No arbitrary paths.",
                "provider": "qwen3-local",
                "variables": {VOICE_PROFILE_VARIABLE: {"reference_audio_path": "C:/secret.wav"}},
            },
        )

    assert profile.status_code == 201
    assert profile.json()["voice_profile_id"] == voice["id"]
    assert forged.status_code == 422
    assert "managed by Voice Profile selection" in forged.json()["detail"]


def test_qwen_profile_freezes_seed_and_profile_owned_designed_take(tmp_path) -> None:
    app = _app(tmp_path)
    reference = tmp_path / "designed-reference.wav"
    reference.write_bytes(_wav_bytes())
    voice = app.state.studio_store.save_voice_profile(
        VoiceProfile(
            id="designed-voice",
            label="Designed narrator",
            engine_id="qwen3",
            kind=VoiceProfileKind.DESIGNED,
            reference_audio_path=str(reference),
            reference_text="These are the exact spoken words.",
            settings={"design_take": 7},
        )
    )

    with TestClient(app) as client:
        response = client.post(
            "/v1/profiles",
            json={
                "name": "Reproducible Qwen narration",
                "resource_id": "qwen3-local",
                "voice_profile_id": voice.id,
                "variables": {"seed": 31_415, "voice_take": 99},
            },
        )

    assert response.status_code == 201
    variables = response.json()["variables"]
    assert variables == {"seed": 31_415, "voice_take": 7}
    assert VOICE_PROFILE_VARIABLE not in variables
    assert str(reference) not in response.text
