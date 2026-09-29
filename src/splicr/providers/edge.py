from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..domain import (
    AudioChunk,
    ControlDefinition,
    ControlMode,
    ControlValueType,
    ProviderCapabilities,
    ProviderError,
    ProviderInfo,
    SpeechPace,
    SynthesisOptions,
    VoiceOption,
)
from ..studio.engines import EngineDescriptor, EngineTransport
from ..studio.local_subprocess import LocalSubprocessEngineAdapter, LocalSubprocessSpec


EDGE_MODEL = "edge-tts"
EDGE_DEFAULT_VOICE = "en-US-AriaNeural"
EDGE_FALLBACK_VOICES = (
    VoiceOption(EDGE_DEFAULT_VOICE, ("en-US", "Female")),
    VoiceOption("en-US-GuyNeural", ("en-US", "Male")),
)


def _cached_voice_options(path: Path) -> tuple[VoiceOption, ...]:
    if not path.is_file():
        return EDGE_FALLBACK_VOICES
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        raw_voices = payload.get("voices") if isinstance(payload, dict) else None
        if not isinstance(raw_voices, list):
            return EDGE_FALLBACK_VOICES
        voices: list[VoiceOption] = []
        for raw in raw_voices:
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("short_name") or "").strip()
            if not name:
                continue
            descriptors = tuple(
                value
                for value in (
                    str(raw.get("locale") or "").strip(),
                    str(raw.get("gender") or "").strip(),
                    *(
                        str(value).strip()
                        for value in raw.get("personalities", [])
                        if str(value).strip()
                    ),
                )
                if value
            )
            voices.append(VoiceOption(name, descriptors))
        return tuple(voices) or EDGE_FALLBACK_VOICES
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return EDGE_FALLBACK_VOICES


class EdgeTtsProvider:
    """Planning facade for Edge's online TTS service in an isolated environment."""

    def __init__(
        self,
        python_executable: Path,
        *,
        voice_cache_path: Path,
        startup_timeout_seconds: float = 60.0,
        request_timeout_seconds: float = 300.0,
    ) -> None:
        executable = python_executable.expanduser().resolve()
        if not executable.is_file():
            raise ValueError(f"Edge TTS Python executable does not exist: {executable}")
        self.python_executable = executable
        self.voice_cache_path = voice_cache_path
        self.startup_timeout_seconds = startup_timeout_seconds
        self.request_timeout_seconds = request_timeout_seconds

    @property
    def info(self) -> ProviderInfo:
        return ProviderInfo(
            name="edge-tts",
            default_model=EDGE_MODEL,
            default_voice=EDGE_DEFAULT_VOICE,
            max_input_bytes=4_000,
            max_input_tokens=None,
            recommended_chunk_characters=1_200,
            minimum_request_interval_seconds=0.0,
            capabilities=ProviderCapabilities(
                models=(EDGE_MODEL,),
                voices=_cached_voice_options(self.voice_cache_path),
                speech_paces=tuple(SpeechPace),
                pace_modes=(ControlMode.NATIVE_SCALAR,),
                supports_custom_instructions=False,
                control_definitions=(
                    ControlDefinition(
                        key="rate_percent",
                        value_type=ControlValueType.INTEGER,
                        label="Precise rate",
                        description=(
                            "Optional Edge rate adjustment. When set, this overrides the "
                            "five-step speaking pace."
                        ),
                        group="Pacing",
                        minimum=-50,
                        maximum=100,
                        step=1,
                        unit="%",
                    ),
                    ControlDefinition(
                        key="pitch_hz",
                        value_type=ControlValueType.INTEGER,
                        label="Pitch shift",
                        group="Voice",
                        default=0,
                        minimum=-100,
                        maximum=100,
                        step=1,
                        unit="Hz",
                    ),
                    ControlDefinition(
                        key="volume_percent",
                        value_type=ControlValueType.INTEGER,
                        label="Volume adjustment",
                        group="Output",
                        default=0,
                        minimum=-100,
                        maximum=100,
                        step=1,
                        unit="%",
                    ),
                    ControlDefinition(
                        key="timing_boundary",
                        value_type=ControlValueType.STRING,
                        label="Timing detail",
                        group="Output",
                        default="sentence",
                        choices=("sentence", "word"),
                    ),
                ),
            ),
        )

    def estimate_input_tokens(self, text: str, options: SynthesisOptions) -> int:
        del options
        return max(1, len(text.encode("utf-8")))

    def estimate_input_characters(self, text: str, options: SynthesisOptions) -> int:
        del options
        return len(text)

    async def synthesize(self, text: str, options: SynthesisOptions) -> AudioChunk:
        del text, options
        raise ProviderError(
            "Edge TTS synthesis requires a job-scoped isolated engine session",
            retryable=False,
            origin="engine",
        )

    def create_engine_adapter(self) -> LocalSubprocessEngineAdapter:
        worker_path = Path(__file__).resolve().parents[1] / "engine_worker.py"
        descriptor = EngineDescriptor(
            id=self.info.name,
            display_name="Edge TTS (online)",
            transport=EngineTransport.LOCAL_SUBPROCESS,
            provider_info=self.info,
        )
        return LocalSubprocessEngineAdapter(
            descriptor,
            LocalSubprocessSpec(
                command=(
                    str(self.python_executable),
                    str(worker_path),
                    "--engine",
                    self.info.name,
                ),
                startup_timeout_seconds=self.startup_timeout_seconds,
                request_timeout_seconds=self.request_timeout_seconds,
            ),
        )


def normalize_edge_voices(raw_voices: list[dict[str, Any]]) -> list[dict[str, object]]:
    normalized: list[dict[str, object]] = []
    for raw in raw_voices:
        tags = raw.get("VoiceTag")
        personalities = tags.get("VoicePersonalities", []) if isinstance(tags, dict) else []
        normalized.append(
            {
                "short_name": str(raw.get("ShortName") or ""),
                "locale": str(raw.get("Locale") or ""),
                "gender": str(raw.get("Gender") or ""),
                "personalities": [str(value) for value in personalities],
            }
        )
    return sorted(
        (voice for voice in normalized if voice["short_name"]),
        key=lambda voice: str(voice["short_name"]),
    )
