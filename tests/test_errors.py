from __future__ import annotations

from splicr.domain import ProviderError
from splicr.errors import JobErrorCode, classify_job_error


def test_classifies_provider_authentication_and_rate_limit_errors() -> None:
    auth = classify_job_error(ProviderError("invalid key", retryable=False, status_code=401))
    rate = classify_job_error(ProviderError("quota exhausted", retryable=True, status_code=429))

    assert auth.code == JobErrorCode.AUTHENTICATION
    assert auth.retryable is False
    assert rate.code == JobErrorCode.RATE_LIMIT
    assert rate.retryable is True


def test_classifies_checkpoint_and_audio_validation_errors() -> None:
    checkpoint = classify_job_error(OSError("checkpoint disk is full"))
    audio = classify_job_error(ValueError("PCM chunk has a partial frame"))

    assert checkpoint.code == JobErrorCode.CHECKPOINT_IO
    assert audio.code == JobErrorCode.INVALID_AUDIO


def test_persisted_error_message_redacts_credentials(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "super-secret-value")

    detail = classify_job_error(
        RuntimeError("Authorization: Bearer token-value api_key=super-secret-value")
    )

    assert "super-secret-value" not in detail.message
    assert "token-value" not in detail.message
    assert detail.message.count("[REDACTED]") >= 2
