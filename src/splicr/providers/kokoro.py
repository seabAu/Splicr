from __future__ import annotations

from pathlib import Path

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


KOKORO_VOICES = (
    VoiceOption("af_alloy", ("American English", "female")),
    VoiceOption("af_aoede", ("American English", "female")),
    VoiceOption("af_heart", ("American English", "female")),
    VoiceOption("af_bella", ("American English", "female")),
    VoiceOption("af_jessica", ("American English", "female")),
    VoiceOption("af_kore", ("American English", "female")),
    VoiceOption("af_nicole", ("American English", "female")),
    VoiceOption("af_nova", ("American English", "female")),
    VoiceOption("af_river", ("American English", "female")),
    VoiceOption("af_sarah", ("American English", "female")),
    VoiceOption("af_sky", ("American English", "female")),
    VoiceOption("am_adam", ("American English", "male")),
    VoiceOption("am_echo", ("American English", "male")),
    VoiceOption("am_eric", ("American English", "male")),
    VoiceOption("am_fenrir", ("American English", "male")),
    VoiceOption("am_liam", ("American English", "male")),
    VoiceOption("am_michael", ("American English", "male")),
    VoiceOption("am_onyx", ("American English", "male")),
    VoiceOption("am_puck", ("American English", "male")),
    VoiceOption("am_santa", ("American English", "male")),
    VoiceOption("bf_alice", ("British English", "female")),
    VoiceOption("bf_emma", ("British English", "female")),
    VoiceOption("bf_isabella", ("British English", "female")),
    VoiceOption("bf_lily", ("British English", "female")),
    VoiceOption("bm_daniel", ("British English", "male")),
    VoiceOption("bm_fable", ("British English", "male")),
    VoiceOption("bm_george", ("British English", "male")),
    VoiceOption("bm_lewis", ("British English", "male")),
    VoiceOption("ef_dora", ("Spanish", "female")),
    VoiceOption("em_alex", ("Spanish", "male")),
    VoiceOption("em_santa", ("Spanish", "male")),
    VoiceOption("ff_siwis", ("French", "female")),
    VoiceOption("hf_alpha", ("Hindi", "female")),
    VoiceOption("hf_beta", ("Hindi", "female")),
    VoiceOption("hm_omega", ("Hindi", "male")),
    VoiceOption("hm_psi", ("Hindi", "male")),
    VoiceOption("if_sara", ("Italian", "female")),
    VoiceOption("im_nicola", ("Italian", "male")),
    VoiceOption("jf_alpha", ("Japanese", "female")),
    VoiceOption("jf_gongitsune", ("Japanese", "female")),
    VoiceOption("jf_nezumi", ("Japanese", "female")),
    VoiceOption("jf_tebukuro", ("Japanese", "female")),
    VoiceOption("jm_kumo", ("Japanese", "male")),
    VoiceOption("pf_dora", ("Brazilian Portuguese", "female")),
    VoiceOption("pm_alex", ("Brazilian Portuguese", "male")),
    VoiceOption("pm_santa", ("Brazilian Portuguese", "male")),
    VoiceOption("zf_xiaobei", ("Mandarin Chinese", "female")),
    VoiceOption("zf_xiaoni", ("Mandarin Chinese", "female")),
    VoiceOption("zf_xiaoxiao", ("Mandarin Chinese", "female")),
    VoiceOption("zf_xiaoyi", ("Mandarin Chinese", "female")),
    VoiceOption("zm_yunjian", ("Mandarin Chinese", "male")),
    VoiceOption("zm_yunxi", ("Mandarin Chinese", "male")),
    VoiceOption("zm_yunxia", ("Mandarin Chinese", "male")),
    VoiceOption("zm_yunyang", ("Mandarin Chinese", "male")),
)


class KokoroTtsProvider:
    """Planning facade whose synthesis runs in an isolated Kokoro environment."""

    def __init__(
        self,
        python_executable: Path,
        *,
        startup_timeout_seconds: float = 600.0,
        request_timeout_seconds: float = 300.0,
    ) -> None:
        executable = python_executable.expanduser().resolve()
        if not executable.is_file():
            raise ValueError(f"Kokoro Python executable does not exist: {executable}")
        self.python_executable = executable
        self.startup_timeout_seconds = startup_timeout_seconds
        self.request_timeout_seconds = request_timeout_seconds
        self._info = ProviderInfo(
            name="kokoro-local",
            default_model="kokoro-82m",
            default_voice="af_heart",
            max_input_bytes=None,
            max_input_tokens=510,
            recommended_chunk_characters=450,
            minimum_request_interval_seconds=0.0,
            capabilities=ProviderCapabilities(
                models=("kokoro-82m",),
                voices=KOKORO_VOICES,
                speech_paces=tuple(SpeechPace),
                pace_modes=(ControlMode.NATIVE_SCALAR,),
                supports_custom_instructions=False,
                control_definitions=(
                    ControlDefinition(
                        key="speed",
                        value_type=ControlValueType.NUMBER,
                        label="Precise speed",
                        description=(
                            "Optional exact Kokoro rate. When set, this overrides the "
                            "five-step speaking pace."
                        ),
                        group="Pacing",
                        minimum=0.5,
                        maximum=2.0,
                        step=0.01,
                        unit="×",
                    ),
                ),
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
            "Kokoro synthesis requires a job-scoped local engine session",
            retryable=False,
            origin="engine",
        )

    def create_engine_adapter(self) -> LocalSubprocessEngineAdapter:
        worker_path = Path(__file__).resolve().parents[1] / "engine_worker.py"
        descriptor = EngineDescriptor(
            id=self.info.name,
            display_name="Kokoro (local)",
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
