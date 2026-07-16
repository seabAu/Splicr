from __future__ import annotations

import os
import re
from enum import StrEnum

from .domain import JobErrorDetail, ProviderError


class JobErrorCode(StrEnum):
    AUTHENTICATION = "provider_authentication"
    RATE_LIMIT = "provider_rate_limit"
    REQUEST_REJECTED = "provider_request_rejected"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROVIDER_TIMEOUT = "provider_timeout"
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
    JobErrorCode.OUTPUT_LIMIT: "Raise the configured output limit or cancel and use a shorter source.",
    JobErrorCode.INVALID_AUDIO: "The provider returned incompatible audio; retry or change provider.",
    JobErrorCode.CHECKPOINT_IO: "Check free disk space and data-directory permissions.",
    JobErrorCode.INTERNAL: "Inspect the server log; completed checkpoints remain available.",
}

_AUTHORIZATION_RE = re.compile(r"(?i)\bauthorization(\s*[:=]\s*)(?:(?:bearer|basic)\s+)?[^\s,;]+")
_SECRET_ASSIGNMENT_RE = re.compile(r"(?i)\b(api[_ -]?key|x-goog-api-key)(\s*[:=]\s*)([^\s,;]+)")
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+\-/=]+")


def _sanitize_message(value: str) -> str:
    message = _AUTHORIZATION_RE.sub(r"Authorization\1[REDACTED]", value)
    message = _SECRET_ASSIGNMENT_RE.sub(r"\1\2[REDACTED]", message)
    message = _BEARER_RE.sub("Bearer [REDACTED]", message)
    configured_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if configured_key:
        message = message.replace(configured_key, "[REDACTED]")
    return message[:2000]


def classify_job_error(error: Exception, *, chunk_index: int | None = None) -> JobErrorDetail:
    message = _sanitize_message(str(error) or error.__class__.__name__)
    lowered = message.lower()
    status_code = error.status_code if isinstance(error, ProviderError) else None

    if "size limit" in lowered or "exceed" in lowered and "pcm" in lowered:
        code = JobErrorCode.OUTPUT_LIMIT
    elif status_code in {401, 403}:
        code = JobErrorCode.AUTHENTICATION
    elif status_code == 429:
        code = JobErrorCode.RATE_LIMIT
    elif status_code in {400, 404, 409, 422}:
        code = JobErrorCode.REQUEST_REJECTED
    elif isinstance(error, TimeoutError) or "timed out" in lowered or "timeout" in lowered:
        code = JobErrorCode.PROVIDER_TIMEOUT
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
