from __future__ import annotations

from pathlib import Path

from ..domain import (
    AudioChunk,
    ControlCondition,
    ControlDefinition,
    ControlValueType,
    ProviderCapabilities,
    ProviderError,
    ProviderInfo,
    SynthesisOptions,
)
from ..studio.engines import EngineDescriptor, EngineTransport
from ..studio.local_subprocess import LocalSubprocessEngineAdapter, LocalSubprocessSpec


QWEN3_MODELS = (
    "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
    "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
    "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
)
QWEN_SEED_VARIABLE = "seed"
QWEN_VOICE_TAKE_VARIABLE = "voice_take"


class Qwen3TtsProvider:
    """Planning facade for a job-scoped Qwen3-TTS subprocess."""

    def __init__(
        self,
        python_executable: Path,
        *,
        startup_timeout_seconds: float = 600.0,
        request_timeout_seconds: float = 300.0,
    ) -> None:
        executable = python_executable.expanduser().resolve()
        if not executable.is_file():
            raise ValueError(f"Qwen3 Python executable does not exist: {executable}")
        self.python_executable = executable
        self.startup_timeout_seconds = startup_timeout_seconds
        self.request_timeout_seconds = request_timeout_seconds
        self._info = ProviderInfo(
            name="qwen3-local",
            default_model=QWEN3_MODELS[0],
            default_voice="voice-profile-required",
            max_input_bytes=None,
            max_input_tokens=None,
            max_input_characters=250,
            recommended_chunk_characters=250,
            minimum_request_interval_seconds=0.0,
            capabilities=ProviderCapabilities(
                models=QWEN3_MODELS,
                supports_custom_instructions=True,
                control_definitions=(
                    ControlDefinition(
                        key=QWEN_SEED_VARIABLE,
                        value_type=ControlValueType.INTEGER,
                        label="Synthesis seed",
                        description=(
                            "Freezes Qwen sampling for a reproducible take. Generate another "
                            "seed to explore a different delivery without changing the voice."
                        ),
                        group="Generation",
                        default=1000,
                        minimum=0,
                        maximum=2_147_483_647,
                        step=1,
                        randomizable=True,
                    ),
                    ControlDefinition(
                        key=QWEN_VOICE_TAKE_VARIABLE,
                        value_type=ControlValueType.INTEGER,
                        label="Designed voice take",
                        description=(
                            "This identity belongs to the selected Voice Profile. Create another "
                            "designed profile in Voice Studio to change it."
                        ),
                        group="Voice",
                        minimum=1,
                        maximum=99,
                        read_only=True,
                        visible_when=(ControlCondition("voice_profile_kind", "designed"),),
                    ),
                ),
            ),
        )

    @property
    def info(self) -> ProviderInfo:
        return self._info

    def estimate_input_tokens(self, text: str, options: SynthesisOptions) -> int:
        del options
        return max(1, len(text) * 2)

    def estimate_input_characters(self, text: str, options: SynthesisOptions) -> int:
        del options
        return len(text)

    async def synthesize(self, text: str, options: SynthesisOptions) -> AudioChunk:
        del text, options
        raise ProviderError(
            "Qwen3 synthesis requires a job-scoped local engine session",
            retryable=False,
            origin="engine",
        )

    def create_engine_adapter(self) -> LocalSubprocessEngineAdapter:
        worker_path = Path(__file__).resolve().parents[1] / "engine_worker.py"
        descriptor = EngineDescriptor(
            id=self.info.name,
            display_name="Qwen3-TTS (local)",
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
