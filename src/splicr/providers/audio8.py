from __future__ import annotations

from pathlib import Path

from ..domain import (
    AudioChunk,
    ProviderCapabilities,
    ProviderError,
    ProviderInfo,
    SynthesisOptions,
)
from ..studio.engines import EngineDescriptor, EngineTransport
from ..studio.local_subprocess import LocalSubprocessEngineAdapter, LocalSubprocessSpec


AUDIO8_MODEL = "Audio8/Audio8-TTS-Preview-0.6b"


class Audio8TtsProvider:
    """Planning facade for a job-scoped Audio8 subprocess."""

    def __init__(
        self,
        python_executable: Path,
        *,
        startup_timeout_seconds: float = 600.0,
        request_timeout_seconds: float = 300.0,
    ) -> None:
        executable = python_executable.expanduser().resolve()
        if not executable.is_file():
            raise ValueError(f"Audio8 Python executable does not exist: {executable}")
        self.python_executable = executable
        self.startup_timeout_seconds = startup_timeout_seconds
        self.request_timeout_seconds = request_timeout_seconds
        self._info = ProviderInfo(
            name="audio8-local",
            default_model=AUDIO8_MODEL,
            default_voice="voice-profile-required",
            max_input_bytes=None,
            max_input_tokens=None,
            max_input_characters=150,
            recommended_chunk_characters=150,
            minimum_request_interval_seconds=0.0,
            capabilities=ProviderCapabilities(
                models=(AUDIO8_MODEL,),
                supports_custom_instructions=False,
            ),
        )

    @property
    def info(self) -> ProviderInfo:
        return self._info

    def estimate_input_tokens(self, text: str, options: SynthesisOptions) -> int:
        del options
        return max(1, len(text))

    def estimate_input_characters(self, text: str, options: SynthesisOptions) -> int:
        del options
        return len(text)

    async def synthesize(self, text: str, options: SynthesisOptions) -> AudioChunk:
        del text, options
        raise ProviderError(
            "Audio8 synthesis requires a job-scoped local engine session",
            retryable=False,
            origin="engine",
        )

    def create_engine_adapter(self) -> LocalSubprocessEngineAdapter:
        worker_path = Path(__file__).resolve().parents[1] / "engine_worker.py"
        descriptor = EngineDescriptor(
            id=self.info.name,
            display_name="Audio8 (local)",
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
