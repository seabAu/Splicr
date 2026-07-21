from __future__ import annotations

import os
import json
from enum import StrEnum

from .diagnostics import sanitize_diagnostic
from .domain import JobErrorDetail, ProviderError


class JobErrorCode(StrEnum):
    AUTHENTICATION = "provider_authentication"
    RATE_LIMIT = "provider_rate_limit"
    REQUEST_REJECTED = "provider_request_rejected"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROVIDER_TIMEOUT = "provider_timeout"
    NETWORK = "network_error"
    OUTPUT_LIMIT = "output_size_limit"
    INVALID_AUDIO = "invalid_provider_audio"
    CHECKPOINT_IO = "checkpoint_io"
    INTERNAL = "internal_error"


_SUGGESTIONS = {
    JobErrorCode.AUTHENTICATION: "Check or rotate the provider API key, then resume the job.",
    JobErrorCode.RATE_LIMIT: "Wait for provider quota to recover, then resume the job.",
    JobErrorCode.REQUEST_REJECTED: "Review the current chunk and provider settings before resuming.",
    JobErrorCode.PROVIDER_UNAVAILABLE: "The provider may be temporarily unavailable; resume later.",
    JobErrorCode.PROVIDER_TIMEOUT: "Check connectivity and provider status, then resume the job.",
    JobErrorCode.NETWORK: ("Check the network, DNS, TLS, and proxy settings, then resume the job."),
    JobErrorCode.OUTPUT_LIMIT: "Raise the configured output limit or cancel and use a shorter source.",
    JobErrorCode.INVALID_AUDIO: "The provider returned incompatible audio; retry or change provider.",
    JobErrorCode.CHECKPOINT_IO: "Check free disk space and data-directory permissions.",
    JobErrorCode.INTERNAL: "Inspect the server log; completed checkpoints remain available.",
}

_TIMEOUT_CATEGORIES = frozenset({"timeout", "connect_timeout", "read_timeout"})
_NETWORK_CATEGORIES = frozenset(
    {"network_error", "proxy_error", "dns_error", "tls_error", "connection_error"}
)
_TIMEOUT_TOKENS = ("timeouterror", "timeoutexception", "timed out", "timeout")
_NETWORK_TOKENS = (
    "connecterror",
    "networkerror",
    "proxyerror",
    "all connection attempts failed",
    "connection refused",
    "connection reset",
    "getaddrinfo",
    "name resolution",
    "dns",
    "certificate verify",
    "tls",
    "ssl",
)


def _sanitize_message(value: str) -> str:
    known_secrets = tuple(
        secret
        for secret in (
            os.getenv("GEMINI_API_KEY"),
            os.getenv("GOOGLE_API_KEY"),
            os.getenv("DEEPGRAM_API_KEY"),
            os.getenv("INWORLD_API_KEY"),
        )
        if secret
    )
    sanitized = sanitize_diagnostic(value, known_secrets=known_secrets)
    return str(sanitized)[:2000]


def _error_context(error: Exception) -> tuple[str | None, str]:
    category: str | None = None
    parts: list[str] = []
    if isinstance(error, ProviderError) and error.diagnostic is not None:
        category = error.diagnostic.category
        parts.extend(
            (
                str(error.diagnostic.category or ""),
                str(error.diagnostic.phase or ""),
                json.dumps(error.diagnostic.exception or {}, ensure_ascii=False, default=str),
            )
        )
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        parts.append(f"{current.__class__.__module__}.{current.__class__.__name__}: {current}")
        current = current.__cause__ or current.__context__
    return category.lower() if category else None, " ".join(parts).lower()


def classify_job_error(error: Exception, *, chunk_index: int | None = None) -> JobErrorDetail:
    message = _sanitize_message(str(error) or error.__class__.__name__)
    lowered = message.lower()
    status_code = error.status_code if isinstance(error, ProviderError) else None
    diagnostic_category, error_context = _error_context(error)
    provider_origin = not isinstance(error, ProviderError) or error.origin == "provider"

    if "size limit" in lowered or "exceed" in lowered and "pcm" in lowered:
        code = JobErrorCode.OUTPUT_LIMIT
    elif status_code in {401, 403}:
        code = JobErrorCode.AUTHENTICATION
    elif status_code == 429:
        code = JobErrorCode.RATE_LIMIT
    elif status_code in {400, 404, 409, 422}:
        code = JobErrorCode.REQUEST_REJECTED
    elif provider_origin and (
        diagnostic_category in _TIMEOUT_CATEGORIES
        or any(token in error_context for token in _TIMEOUT_TOKENS)
    ):
        code = JobErrorCode.PROVIDER_TIMEOUT
    elif provider_origin and (
        diagnostic_category in _NETWORK_CATEGORIES
        or any(token in error_context for token in _NETWORK_TOKENS)
    ):
        code = JobErrorCode.NETWORK
    elif status_code is not None and status_code >= 500:
        code = JobErrorCode.PROVIDER_UNAVAILABLE
    elif any(token in lowered for token in ("pcm", "audio/l16", "sample rate", "channel")):
        code = JobErrorCode.INVALID_AUDIO
    elif isinstance(error, OSError) or any(
        token in lowered for token in ("checkpoint", "disk", "permission")
    ):
        code = JobErrorCode.CHECKPOINT_IO
    else:
        code = JobErrorCode.INTERNAL

    retryable = (
        error.retryable
        if isinstance(error, ProviderError)
        else code
        in {
            JobErrorCode.RATE_LIMIT,
            JobErrorCode.PROVIDER_UNAVAILABLE,
            JobErrorCode.PROVIDER_TIMEOUT,
            JobErrorCode.NETWORK,
            JobErrorCode.CHECKPOINT_IO,
            JobErrorCode.INTERNAL,
        }
    )
    return JobErrorDetail(
        code=code.value,
        message=message,
        retryable=retryable,
        status_code=status_code,
        chunk_index=chunk_index,
    )


def suggestion_for(code: JobErrorCode | str) -> str:
    try:
        normalized = code if isinstance(code, JobErrorCode) else JobErrorCode(code)
    except ValueError:
        normalized = JobErrorCode.INTERNAL
    return _SUGGESTIONS[normalized]
