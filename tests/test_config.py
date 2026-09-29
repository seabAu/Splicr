from __future__ import annotations

import pytest

from splicr.config import Settings


def test_environment_proxies_are_disabled_by_default(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SPLICR_TRUST_ENV_PROXIES", raising=False)

    assert Settings().trust_env_proxies is False
    assert Settings.from_env().trust_env_proxies is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_environment_proxy_opt_in_accepts_boolean_values(
    value: str,
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SPLICR_TRUST_ENV_PROXIES", value)

    assert Settings.from_env().trust_env_proxies is True


@pytest.mark.parametrize("value", ["0", "false", "FALSE", "no", "off"])
def test_environment_proxy_opt_out_accepts_boolean_values(
    value: str,
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SPLICR_TRUST_ENV_PROXIES", value)

    assert Settings.from_env().trust_env_proxies is False


def test_invalid_environment_proxy_boolean_is_rejected(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SPLICR_TRUST_ENV_PROXIES", "sometimes")

    with pytest.raises(ValueError, match="SPLICR_TRUST_ENV_PROXIES must be a boolean"):
        Settings.from_env()


def test_encrypted_file_vault_environment_is_resolved(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SPLICR_SECRET_VAULT_BACKEND", "encrypted-file")
    monkeypatch.setenv("SPLICR_SECRET_VAULT_KEY_FILE", "secrets/vault.key")
    monkeypatch.setenv("SPLICR_SECRET_VAULT_PATH", "state/resources.vault")

    settings = Settings.from_env()

    assert settings.secret_vault_backend == "encrypted-file"
    assert settings.secret_vault_key_file == (tmp_path / "secrets" / "vault.key").resolve()
    assert settings.encrypted_vault_path == (tmp_path / "state" / "resources.vault").resolve()


def test_unknown_secret_vault_backend_is_rejected(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SPLICR_SECRET_VAULT_BACKEND", "plaintext")

    with pytest.raises(ValueError, match="SPLICR_SECRET_VAULT_BACKEND"):
        Settings.from_env()


def test_auth_environment_is_explicit_and_resolves_persistent_credentials(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SPLICR_DATA_DIR", "state")
    monkeypatch.setenv("SPLICR_AUTH_ENABLED", "true")
    monkeypatch.setenv("SPLICR_AUTH_COOKIE_SECURE", "true")
    monkeypatch.setenv("SPLICR_AUTH_SESSION_SECONDS", "7200")

    settings = Settings.from_env()

    assert settings.auth_enabled is True
    assert settings.auth_cookie_secure is True
    assert settings.auth_session_seconds == 7200
    assert settings.auth_credentials_path == (tmp_path / "state" / "auth" / "credentials.json")


def test_local_engine_environments_are_optional_and_resolved(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    kokoro_path = tmp_path / "kokoro-env" / "Scripts" / "python.exe"
    qwen3_path = tmp_path / "qwen3-env" / "Scripts" / "python.exe"
    audio8_path = tmp_path / "audio8-env" / "Scripts" / "python.exe"
    edge_path = tmp_path / "edge-env" / "Scripts" / "python.exe"
    whisper_path = tmp_path / "whisper-env" / "Scripts" / "python.exe"
    monkeypatch.setenv("SPLICR_KOKORO_PYTHON", str(kokoro_path))
    monkeypatch.setenv("SPLICR_QWEN3_PYTHON", str(qwen3_path))
    monkeypatch.setenv("SPLICR_AUDIO8_PYTHON", str(audio8_path))
    monkeypatch.setenv("SPLICR_EDGE_PYTHON", str(edge_path))
    monkeypatch.setenv("SPLICR_WHISPER_PYTHON", str(whisper_path))
    monkeypatch.setenv("SPLICR_LOCAL_ENGINE_STARTUP_TIMEOUT_SECONDS", "900")
    monkeypatch.setenv("SPLICR_LOCAL_ENGINE_REQUEST_TIMEOUT_SECONDS", "450")

    settings = Settings.from_env()

    assert settings.kokoro_python == kokoro_path.resolve()
    assert settings.qwen3_python == qwen3_path.resolve()
    assert settings.audio8_python == audio8_path.resolve()
    assert settings.edge_python == edge_path.resolve()
    assert settings.whisper_python == whisper_path.resolve()
    assert settings.local_engine_startup_timeout_seconds == 900
    assert settings.local_engine_request_timeout_seconds == 450
