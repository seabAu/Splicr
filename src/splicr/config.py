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


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean (true/false, yes/no, on/off, or 1/0)")


@dataclass(frozen=True, slots=True)
class Settings:
    data_dir: Path = Path("data")
    auth_enabled: bool = False
    auth_cookie_secure: bool = False
    auth_session_seconds: int = 43_200
    secret_vault_backend: str = "keyring"
    secret_vault_key_file: Path | None = None
    secret_vault_path: Path | None = None
    max_source_bytes: int = 1_000_000
    max_source_words: int = 100_000
    max_upload_bytes: int = 25_000_000
    max_audio_upload_bytes: int = 2_000_000_000
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
    kokoro_python: Path | None = None
    qwen3_python: Path | None = None
    audio8_python: Path | None = None
    local_engine_startup_timeout_seconds: float = 600.0
    local_engine_request_timeout_seconds: float = 300.0
    chunk_max_bytes: int = 3_800
    chunk_max_words: int = 350
    pacing_seconds: float = 3.0
    provider_timeout_seconds: float = 300.0
    max_attempts: int = 3
    backoff_base_seconds: float = 5.0
    backoff_max_seconds: float = 60.0
    backoff_jitter_seconds: float = 1.0
    trust_env_proxies: bool = False
    cors_origins: tuple[str, ...] = field(
        default_factory=lambda: ("http://localhost:3000", "http://localhost:5173")
    )

    @property
    def database_path(self) -> Path:
        return self.data_dir / "splicr.sqlite3"

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    @property
    def auth_credentials_path(self) -> Path:
        return self.data_dir / "auth" / "credentials.json"

    @property
    def encrypted_vault_path(self) -> Path:
        return self.secret_vault_path or (self.data_dir / "secrets" / "api-resources.vault")

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
        vault_backend = os.getenv("SPLICR_SECRET_VAULT_BACKEND", "keyring").strip().lower()
        if vault_backend not in {"keyring", "encrypted-file"}:
            raise ValueError(
                "SPLICR_SECRET_VAULT_BACKEND must be 'keyring' or 'encrypted-file'"
            )
        vault_key_file_value = os.getenv("SPLICR_SECRET_VAULT_KEY_FILE", "").strip()
        vault_path_value = os.getenv("SPLICR_SECRET_VAULT_PATH", "").strip()
        kokoro_python_value = os.getenv("SPLICR_KOKORO_PYTHON", "").strip()
        qwen3_python_value = os.getenv("SPLICR_QWEN3_PYTHON", "").strip()
        audio8_python_value = os.getenv("SPLICR_AUDIO8_PYTHON", "").strip()
        return cls(
            data_dir=Path(os.getenv("SPLICR_DATA_DIR", "data")).expanduser().resolve(),
            auth_enabled=_bool_env("SPLICR_AUTH_ENABLED", False),
            auth_cookie_secure=_bool_env("SPLICR_AUTH_COOKIE_SECURE", False),
            auth_session_seconds=_int_env("SPLICR_AUTH_SESSION_SECONDS", 43_200, minimum=300),
            secret_vault_backend=vault_backend,
            secret_vault_key_file=(
                Path(vault_key_file_value).expanduser().resolve()
                if vault_key_file_value
                else None
            ),
            secret_vault_path=(
                Path(vault_path_value).expanduser().resolve() if vault_path_value else None
            ),
            max_source_bytes=_int_env("SPLICR_MAX_SOURCE_BYTES", 1_000_000),
            max_source_words=_int_env("SPLICR_MAX_SOURCE_WORDS", 100_000),
            max_upload_bytes=_int_env("SPLICR_MAX_UPLOAD_BYTES", 25_000_000),
            max_audio_upload_bytes=_int_env(
                "SPLICR_MAX_AUDIO_UPLOAD_BYTES", 2_000_000_000
            ),
            max_output_pcm_bytes=_int_env("SPLICR_MAX_OUTPUT_PCM_BYTES", 4_000_000_000),
            gemini_model=os.getenv("SPLICR_GEMINI_MODEL", "gemini-3.1-flash-tts-preview").strip(),
            gemini_voice=os.getenv("SPLICR_GEMINI_VOICE", "Kore").strip(),
            deepgram_model=os.getenv("SPLICR_DEEPGRAM_MODEL", "aura-2").strip(),
            deepgram_voice=os.getenv("SPLICR_DEEPGRAM_VOICE", "aura-2-thalia-en").strip(),
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
            kokoro_python=(
                Path(kokoro_python_value).expanduser().resolve()
                if kokoro_python_value
                else None
            ),
            qwen3_python=(
                Path(qwen3_python_value).expanduser().resolve()
                if qwen3_python_value
                else None
            ),
            audio8_python=(
                Path(audio8_python_value).expanduser().resolve()
                if audio8_python_value
                else None
            ),
            local_engine_startup_timeout_seconds=_float_env(
                "SPLICR_LOCAL_ENGINE_STARTUP_TIMEOUT_SECONDS",
                600.0,
                minimum=1,
            ),
            local_engine_request_timeout_seconds=_float_env(
                "SPLICR_LOCAL_ENGINE_REQUEST_TIMEOUT_SECONDS",
                300.0,
                minimum=1,
            ),
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
            trust_env_proxies=_bool_env("SPLICR_TRUST_ENV_PROXIES", False),
            cors_origins=origins,
        )
