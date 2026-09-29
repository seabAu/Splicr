from __future__ import annotations

import pytest

from splicr.studio.domain import VoiceProfile, VoiceProfileKind
from splicr.studio.voice_resolution import (
    VOICE_PROFILE_VARIABLE,
    model_for_voice_profile,
    resolve_voice_profile,
)


def test_qwen_clone_resolution_freezes_reference_and_preserves_variables(tmp_path) -> None:
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"RIFF-reference")
    profile = VoiceProfile(
        id="voice-one",
        label="Narrator",
        engine_id="qwen3",
        kind=VoiceProfileKind.CLONED,
        reference_audio_path=str(reference),
        reference_text="Exact spoken words.",
        settings={"language": "English"},
    )
    original = {"chapter": 3}

    voice, variables = resolve_voice_profile("qwen3-local", profile, original)

    assert voice == profile.id
    assert original == {"chapter": 3}
    assert variables["chapter"] == 3
    snapshot = variables[VOICE_PROFILE_VARIABLE]
    assert isinstance(snapshot, dict)
    assert snapshot["id"] == profile.id
    assert snapshot["reference_audio_path"] == str(reference)
    assert snapshot["reference_text"] == "Exact spoken words."


def test_qwen_preset_resolution_uses_native_speaker() -> None:
    profile = VoiceProfile(
        id="preset-one",
        label="Announcer",
        engine_id="qwen3",
        kind=VoiceProfileKind.PRESET,
        settings={"speaker": "Ryan", "instructions": "Bright and concise"},
    )

    voice, variables = resolve_voice_profile("qwen3-local", profile, {})

    assert voice == "Ryan"
    assert variables[VOICE_PROFILE_VARIABLE]["kind"] == "preset"


def test_qwen_designed_profile_owns_take_identity(tmp_path) -> None:
    reference = tmp_path / "designed.wav"
    reference.write_bytes(b"RIFF-reference")
    profile = VoiceProfile(
        id="designed-one",
        label="Designed narrator",
        description="Warm, measured, and reflective",
        engine_id="qwen3",
        kind=VoiceProfileKind.DESIGNED,
        reference_audio_path=str(reference),
        reference_text="These are the exact reference words.",
        settings={"design_take": 7},
    )

    _, variables = resolve_voice_profile(
        "qwen3-local",
        profile,
        {"seed": 42, "voice_take": 99},
    )

    assert variables["seed"] == 42
    assert variables["voice_take"] == 7
    assert variables[VOICE_PROFILE_VARIABLE]["description"] == (
        "Warm, measured, and reflective"
    )
    _, repeated_variables = resolve_voice_profile(
        "qwen3-local",
        profile,
        {"seed": 42},
    )
    assert repeated_variables == variables

    another = VoiceProfile(
        id="designed-two",
        label="Designed narrator, take 8",
        engine_id="qwen3",
        kind=VoiceProfileKind.DESIGNED,
        reference_audio_path=str(reference),
        reference_text="These are the exact reference words.",
        settings={"design_take": 8},
    )
    _, another_variables = resolve_voice_profile("qwen3-local", another, {"seed": 42})
    assert another_variables["voice_take"] == 8
    assert another_variables[VOICE_PROFILE_VARIABLE]["id"] != (
        variables[VOICE_PROFILE_VARIABLE]["id"]
    )


def test_qwen_designed_profile_rejects_invalid_take(tmp_path) -> None:
    reference = tmp_path / "designed.wav"
    reference.write_bytes(b"RIFF-reference")
    profile = VoiceProfile(
        id="designed-one",
        label="Broken designed narrator",
        engine_id="qwen3",
        kind=VoiceProfileKind.DESIGNED,
        reference_audio_path=str(reference),
        reference_text="These are the exact reference words.",
        settings={"design_take": 0},
    )

    with pytest.raises(ValueError, match="invalid designed take"):
        resolve_voice_profile("qwen3-local", profile, {})


def test_voice_profile_selects_the_model_family_it_can_render(tmp_path) -> None:
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"RIFF-reference")
    preset = VoiceProfile(
        id="preset-one",
        label="Announcer",
        engine_id="qwen3",
        kind=VoiceProfileKind.PRESET,
        settings={"speaker": "Ryan"},
    )
    clone = VoiceProfile(
        id="clone-one",
        label="Narrator",
        engine_id="qwen3",
        kind=VoiceProfileKind.CLONED,
        reference_audio_path=str(reference),
        reference_text="Exact spoken words.",
    )

    assert model_for_voice_profile("qwen3-local", preset, None) == (
        "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
    )
    assert model_for_voice_profile(
        "qwen3-local",
        clone,
        "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
    ) == "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
    assert model_for_voice_profile(
        "qwen3-local",
        clone,
        "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
    ) == "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
    assert model_for_voice_profile("audio8-local", clone, None) == (
        "Audio8/Audio8-TTS-Preview-0.6b"
    )


def test_voice_resolution_rejects_provider_mismatch(tmp_path) -> None:
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"RIFF-reference")
    profile = VoiceProfile(
        id="voice-one",
        label="Narrator",
        engine_id="qwen3",
        kind=VoiceProfileKind.CLONED,
        reference_audio_path=str(reference),
        reference_text="Exact spoken words.",
    )

    with pytest.raises(ValueError, match="requires provider 'qwen3-local'"):
        resolve_voice_profile("gemini", profile, {})


def test_audio8_resolution_requires_clone(tmp_path) -> None:
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"RIFF-reference")
    profile = VoiceProfile(
        id="designed-one",
        label="Designed",
        engine_id="audio8",
        kind=VoiceProfileKind.DESIGNED,
        reference_audio_path=str(reference),
        reference_text="Exact spoken words.",
    )

    with pytest.raises(ValueError, match="cloned Voice Profiles only"):
        resolve_voice_profile("audio8-local", profile, {})
