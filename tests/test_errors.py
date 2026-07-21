from __future__ import annotations

from splicr.domain import ProviderDiagnostic, ProviderError
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


def test_classifies_structured_network_and_timeout_diagnostics() -> None:
    network = classify_job_error(
        ProviderError(
            "request failed",
            retryable=True,
            diagnostic=ProviderDiagnostic(
                category="network_error",
                phase="connect",
                exception={"root_type": "httpx.ConnectError"},
            ),
        )
    )
    timeout = classify_job_error(
        ProviderError(
            "request failed",
            retryable=True,
            diagnostic=ProviderDiagnostic(
                category="timeout",
                phase="read",
                exception={"root_type": "httpx.ReadTimeout"},
            ),
        )
    )

    assert network.code == JobErrorCode.NETWORK
    assert network.retryable is True
    assert timeout.code == JobErrorCode.PROVIDER_TIMEOUT


def test_classifies_connection_failure_from_exception_chain() -> None:
    try:
        try:
            raise ConnectionRefusedError("connection refused")
        except ConnectionRefusedError as cause:
            raise ProviderError("provider request failed", retryable=True) from cause
    except ProviderError as error:
        detail = classify_job_error(error)

    assert detail.code == JobErrorCode.NETWORK


def test_service_origin_is_not_misclassified_as_provider_network_failure() -> None:
    detail = classify_job_error(
        ProviderError(
            "connection bookkeeping failed",
            retryable=False,
            origin="service",
        )
    )

    assert detail.code == JobErrorCode.INTERNAL
