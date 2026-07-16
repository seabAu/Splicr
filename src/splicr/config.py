from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _float_env(name: str, default: float, *, minimum: float = 0) -> float:
    value = float(os.getenv(name, str(default)))
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


def _int_env(name: str, default: int, *, minimum: int = 1) -> int:
    value = int(os.getenv(name, str(default)))
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    data_dir: Path = Path("data")
    max_source_bytes: int = 1_000_000
    max_source_words: int = 100_000
    max_upload_bytes: int = 25_000_000
    max_output_pcm_bytes: int = 4_000_000_000
    gemini_model: str = "gemini-3.1-flash-tts-preview"
    gemini_voice: str = "Kore"
    deepgram_model: str = "aura-2"
    deepgram_voice: str = "aura-2-thalia-en"
    deepgram_api_url: str = "https://api.deepgram.com/v1/speak"
    deepgram_pacing_seconds: float = 0.0
    inworld_model: str = "inworld-tts-2"
    inworld_voice: str = "Ashley"
    inworld_api_url: str = "https://api.inworld.ai/tts/v1/voice"
    inworld_pacing_seconds: float = 0.0
    chunk_max_bytes: int = 3_800
    chunk_max_words: int = 350
    pacing_seconds: float = 3.0
    provider_timeout_seconds: float = 300.0
    max_attempts: int = 3
    backoff_base_seconds: float = 5.0
    backoff_max_seconds: float = 60.0
    backoff_jitter_seconds: float = 1.0
    cors_origins: tuple[str, ...] = field(
        default_factory=lambda: ("http://localhost:3000", "http://localhost:5173")
    )

    @property
    def database_path(self) -> Path:
        return self.data_dir / "splicr.sqlite3"

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    @classmethod
    def from_env(cls) -> "Settings":
        from dotenv import load_dotenv

        load_dotenv()
        origins = tuple(
            origin.strip()
            for origin in os.getenv(
                "SPLICR_CORS_ORIGINS", "http://localhost:3000,http://localhost:5173"
            ).split(",")
            if origin.strip()
        )
        return cls(
            data_dir=Path(os.getenv("SPLICR_DATA_DIR", "data")).expanduser().resolve(),
            max_source_bytes=_int_env("SPLICR_MAX_SOURCE_BYTES", 1_000_000),
            max_source_words=_int_env("SPLICR_MAX_SOURCE_WORDS", 100_000),
            max_upload_bytes=_int_env("SPLICR_MAX_UPLOAD_BYTES", 25_000_000),
            max_output_pcm_bytes=_int_env("SPLICR_MAX_OUTPUT_PCM_BYTES", 4_000_000_000),
            gemini_model=os.getenv("SPLICR_GEMINI_MODEL", "gemini-3.1-flash-tts-preview").strip(),
            gemini_voice=os.getenv("SPLICR_GEMINI_VOICE", "Kore").strip(),
            deepgram_model=os.getenv("SPLICR_DEEPGRAM_MODEL", "aura-2").strip(),
            deepgram_voice=os.getenv(
                "SPLICR_DEEPGRAM_VOICE", "aura-2-thalia-en"
            ).strip(),
            deepgram_api_url=os.getenv(
                "SPLICR_DEEPGRAM_API_URL", "https://api.deepgram.com/v1/speak"
            ).strip(),
            deepgram_pacing_seconds=_float_env("SPLICR_DEEPGRAM_PACING_SECONDS", 0.0),
            inworld_model=os.getenv("SPLICR_INWORLD_MODEL", "inworld-tts-2").strip(),
            inworld_voice=os.getenv("SPLICR_INWORLD_VOICE", "Ashley").strip(),
            inworld_api_url=os.getenv(
                "SPLICR_INWORLD_API_URL", "https://api.inworld.ai/tts/v1/voice"
            ).strip(),
            inworld_pacing_seconds=_float_env("SPLICR_INWORLD_PACING_SECONDS", 0.0),
            chunk_max_bytes=_int_env("SPLICR_CHUNK_MAX_BYTES", 3_800),
            chunk_max_words=_int_env("SPLICR_CHUNK_MAX_WORDS", 350),
            pacing_seconds=_float_env("SPLICR_PACING_SECONDS", 3.0),
            provider_timeout_seconds=_float_env(
                "SPLICR_PROVIDER_TIMEOUT_SECONDS", 300.0, minimum=1
            ),
            max_attempts=_int_env("SPLICR_MAX_ATTEMPTS", 3),
            backoff_base_seconds=_float_env("SPLICR_BACKOFF_BASE_SECONDS", 5.0),
            backoff_max_seconds=_float_env("SPLICR_BACKOFF_MAX_SECONDS", 60.0),
            backoff_jitter_seconds=_float_env("SPLICR_BACKOFF_JITTER_SECONDS", 1.0),
            cors_origins=origins,
        )
