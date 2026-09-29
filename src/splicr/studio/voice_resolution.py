from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from ..domain import JsonValue
from ..providers.audio8 import AUDIO8_MODEL
from ..providers.qwen3 import QWEN3_MODELS, QWEN_VOICE_TAKE_VARIABLE
from .domain import VoiceProfile, VoiceProfileKind


VOICE_PROFILE_VARIABLE = "__splicr_voice_profile"

_ENGINE_PROVIDERS = {
    "qwen3": "qwen3-local",
    "qwen3-local": "qwen3-local",
    "audio8": "audio8-local",
    "audio8-local": "audio8-local",
    "kokoro": "kokoro-local",
    "kokoro-local": "kokoro-local",
}


def provider_for_voice_engine(engine_id: str) -> str | None:
    return _ENGINE_PROVIDERS.get(engine_id.strip().casefold())


def model_for_voice_profile(
    provider_name: str,
    profile: VoiceProfile,
    requested_model: str | None,
) -> str | None:
    """Choose the model family that can actually render this voice profile."""

    normalized_provider = provider_name.strip().casefold()
    if normalized_provider == "audio8-local":
        return AUDIO8_MODEL
    if normalized_provider != "qwen3-local":
        return requested_model
    if profile.kind is VoiceProfileKind.PRESET:
        return QWEN3_MODELS[2]
    if requested_model in QWEN3_MODELS[:2]:
        return requested_model
    return QWEN3_MODELS[0]


def resolve_voice_profile(
    provider_name: str,
    profile: VoiceProfile,
    variables: Mapping[str, JsonValue],
) -> tuple[str, dict[str, JsonValue]]:
    """Freeze a compatible Studio voice profile into provider-bound job variables."""

    expected_provider = provider_for_voice_engine(profile.engine_id)
    if expected_provider is None:
        raise ValueError(f"voice profile engine {profile.engine_id!r} cannot render speech yet")
    if provider_name.casefold() != expected_provider:
        raise ValueError(
            f"voice profile {profile.label!r} requires provider {expected_provider!r}, "
            f"not {provider_name!r}"
        )

    reference_path = profile.reference_audio_path
    reference_text = (profile.reference_text or "").strip() or None
    settings = dict(profile.settings)
    native_voice = str(settings.get("voice_id") or settings.get("speaker") or profile.id)

    if expected_provider in {"qwen3-local", "audio8-local"}:
        if profile.kind in {VoiceProfileKind.CLONED, VoiceProfileKind.DESIGNED}:
            if not reference_path or not Path(reference_path).is_file():
                raise ValueError(f"voice profile {profile.label!r} has no readable reference audio")
            if not reference_text:
                raise ValueError(
                    f"voice profile {profile.label!r} needs the exact reference transcript"
                )
        if expected_provider == "audio8-local" and profile.kind is not VoiceProfileKind.CLONED:
            raise ValueError("Audio8 currently supports cloned Voice Profiles only")
        if expected_provider == "qwen3-local" and profile.kind is VoiceProfileKind.PRESET:
            speaker = str(settings.get("speaker") or settings.get("voice_id") or "").strip()
            if not speaker:
                raise ValueError(f"voice profile {profile.label!r} has no preset speaker")
            native_voice = speaker
        elif profile.kind not in {VoiceProfileKind.CLONED, VoiceProfileKind.DESIGNED}:
            raise ValueError(
                f"voice profile kind {profile.kind.value!r} is not supported by {expected_provider}"
            )

    snapshot: dict[str, JsonValue] = {
        "id": profile.id,
        "label": profile.label,
        "description": profile.description,
        "engine_id": profile.engine_id,
        "kind": profile.kind.value,
        "reference_audio_path": reference_path,
        "reference_text": reference_text,
        "settings": settings,
        "updated_at": profile.updated_at,
    }
    resolved_variables = dict(variables)
    resolved_variables.pop(QWEN_VOICE_TAKE_VARIABLE, None)
    if expected_provider == "qwen3-local" and profile.kind is VoiceProfileKind.DESIGNED:
        legacy = profile.metadata.get("legacy_voice_metadata")
        legacy_take = legacy.get("take") if isinstance(legacy, Mapping) else None
        take = settings.get("design_take", settings.get("take", legacy_take or 1))
        if isinstance(take, bool) or not isinstance(take, int) or not 1 <= take <= 99:
            raise ValueError(f"voice profile {profile.label!r} has an invalid designed take")
        resolved_variables[QWEN_VOICE_TAKE_VARIABLE] = take
    resolved_variables[VOICE_PROFILE_VARIABLE] = snapshot
    return native_voice, resolved_variables
