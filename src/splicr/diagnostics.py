from __future__ import annotations

import hashlib
import json
import math
import os
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any
from urllib.parse import parse_qsl, quote, quote_plus, urlencode, urlsplit, urlunsplit

import httpx

from .domain import JsonValue, ProviderDiagnostic, ProviderError


_REDACTED = "[REDACTED]"
_MAX_DEPTH = 10
_MAX_ITEMS = 200
_MAX_STRING_CHARS = 64_000
_MAX_EXCEPTION_CHAIN = 10
_SENSITIVE_KEY_RE = re.compile(
    r"(?i)(?:^|[-_. ])(?:authorization|proxy[-_ ]?authorization|cookie|set[-_ ]?cookie|"
    r"api[-_ ]?key|token|secret|password|passwd|credential|private[-_ ]?key|access[-_ ]?key|"
    r"client[-_ ]?secret|key)(?:$|[-_. ])"
)
_AUDIO_KEY_RE = re.compile(
    r"(?i)(?:audio(?:content|data|bytes|payload)?|pcm|waveform|speechdata|speech_data)"
)
_AUTH_VALUE_RE = re.compile(r"(?i)\b(?:bearer|basic|token)\s+[A-Za-z0-9._~+/%=-]+")
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[-_ ]?key|token|secret|password|credential|authorization)"
    r"(\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;}&]+)"
)
_BASE64_RE = re.compile(r"^[A-Za-z0-9+/\r\n]+={0,2}$")
_PROXY_NAMES = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
)


def _known_secret_variants(known_secrets: Iterable[str]) -> tuple[str, ...]:
    variants: set[str] = set()
    for candidate in known_secrets:
        if not isinstance(candidate, str):
            continue
        secret = candidate.strip()
        if len(secret) < 4:
            continue
        variants.update((secret, quote(secret, safe=""), quote_plus(secret)))
    return tuple(sorted(variants, key=len, reverse=True))


def _redact_text(value: str, known_secrets: Iterable[str]) -> str:
    redacted = value
    for secret in _known_secret_variants(known_secrets):
        redacted = redacted.replace(secret, _REDACTED)
    redacted = _AUTH_VALUE_RE.sub(_REDACTED, redacted)
    redacted = _SECRET_ASSIGNMENT_RE.sub(rf"\1\2{_REDACTED}", redacted)
    if len(redacted) <= _MAX_STRING_CHARS:
        return redacted
    omitted = len(redacted) - _MAX_STRING_CHARS
    return f"{redacted[:_MAX_STRING_CHARS]}\n[truncated {omitted} characters]"


def _replace_known_secrets(value: str, known_secrets: Iterable[str]) -> str:
    redacted = value
    for secret in _known_secret_variants(known_secrets):
        redacted = redacted.replace(secret, _REDACTED)
    if len(redacted) <= _MAX_STRING_CHARS:
        return redacted
    omitted = len(redacted) - _MAX_STRING_CHARS
    return f"{redacted[:_MAX_STRING_CHARS]}\n[truncated {omitted} characters]"


def _binary_summary(value: bytes, *, kind: str = "binary") -> dict[str, JsonValue]:
    return {
        "kind": kind,
        "byte_count": len(value),
        "sha256": hashlib.sha256(value).hexdigest(),
    }


def _base64_summary(value: str, *, kind: str = "base64") -> dict[str, JsonValue]:
    return {
        "kind": kind,
        "encoded_character_count": len(value),
        "sha256": hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest(),
    }


def _looks_like_base64(value: str) -> bool:
    compact = "".join(value.split())
    return len(compact) >= 4_096 and len(compact) % 4 == 0 and bool(_BASE64_RE.fullmatch(compact))


def sanitize_diagnostic(
    value: Any,
    *,
    known_secrets: Iterable[str] = (),
    _depth: int = 0,
    _key: str | None = None,
) -> JsonValue:
    """Return bounded JSON-safe diagnostic data with credentials removed recursively."""

    if _depth >= _MAX_DEPTH:
        return "[maximum diagnostic depth reached]"
    if _key and _SENSITIVE_KEY_RE.search(_key):
        return _REDACTED
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, bytes | bytearray | memoryview):
        return _binary_summary(bytes(value))
    if isinstance(value, str):
        redacted = (
            sanitize_url(value, known_secrets=known_secrets)
            if value.lower().startswith(("http://", "https://"))
            else _redact_text(value, known_secrets)
        )
        if _key and _AUDIO_KEY_RE.fullmatch(_key.replace("-", "").replace("_", "")):
            return _base64_summary(redacted, kind="base64_audio")
        if _looks_like_base64(redacted):
            return _base64_summary(redacted)
        return redacted
    if isinstance(value, Mapping):
        result: dict[str, JsonValue] = {}
        for index, (raw_key, item) in enumerate(value.items()):
            if index >= _MAX_ITEMS:
                result["_splicr_truncated_items"] = len(value) - _MAX_ITEMS
                break
            key = _redact_text(str(raw_key), known_secrets)
            result[key] = sanitize_diagnostic(
                item,
                known_secrets=known_secrets,
                _depth=_depth + 1,
                _key=key,
            )
        return result
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        items = [
            sanitize_diagnostic(item, known_secrets=known_secrets, _depth=_depth + 1)
            for item in value[:_MAX_ITEMS]
        ]
        if len(value) > _MAX_ITEMS:
            items.append(f"[truncated {len(value) - _MAX_ITEMS} items]")
        return items
    if isinstance(value, Iterable):
        items: list[JsonValue] = []
        for index, item in enumerate(value):
            if index >= _MAX_ITEMS:
                items.append("[additional items truncated]")
                break
            items.append(sanitize_diagnostic(item, known_secrets=known_secrets, _depth=_depth + 1))
        return items
    return _redact_text(str(value), known_secrets)


def sanitize_url(value: str, *, known_secrets: Iterable[str] = ()) -> str:
    """Redact URL credentials and sensitive query values while retaining routing context."""

    try:
        parsed = urlsplit(value)
    except (TypeError, ValueError):
        return _redact_text(str(value), known_secrets)
    if not parsed.scheme or not parsed.netloc:
        return _redact_text(value, known_secrets)

    hostname = parsed.hostname or ""
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    try:
        port = f":{parsed.port}" if parsed.port is not None else ""
    except ValueError:
        port = ""
    userinfo = f"{quote(_REDACTED, safe='')}@" if parsed.username is not None else ""
    netloc = f"{userinfo}{hostname}{port}"
    query: list[tuple[str, str]] = []
    for key, item in parse_qsl(parsed.query, keep_blank_values=True):
        if _SENSITIVE_KEY_RE.search(key):
            query.append((key, _REDACTED))
        else:
            query.append((key, _redact_text(item, known_secrets)))
    sanitized = urlunsplit(
        (
            parsed.scheme,
            netloc,
            _redact_text(parsed.path, known_secrets),
            urlencode(query, doseq=True),
            "",
        )
    )
    return _replace_known_secrets(sanitized, known_secrets)


def request_diagnostic(
    *,
    method: str,
    endpoint: str,
    headers: Mapping[str, Any] | None = None,
    query: Mapping[str, Any] | None = None,
    body: Any = None,
    known_secrets: Iterable[str] = (),
) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {
        "method": method.upper(),
        "url": sanitize_url(endpoint, known_secrets=known_secrets),
    }
    if headers is not None:
        result["headers"] = sanitize_diagnostic(headers, known_secrets=known_secrets)
    if query is not None:
        result["query"] = sanitize_diagnostic(query, known_secrets=known_secrets)
    if body is not None:
        result["body"] = sanitize_diagnostic(body, known_secrets=known_secrets)
    return result


def _headers_mapping(headers: Any) -> dict[str, str]:
    if headers is None:
        return {}
    try:
        pairs = headers.multi_items()
    except AttributeError:
        try:
            pairs = headers.items()
        except AttributeError:
            return {"value": str(headers)}
    result: dict[str, str] = {}
    for key, value in pairs:
        normalized = str(key)
        rendered = str(value)
        result[normalized] = (
            f"{result[normalized]}, {rendered}" if normalized in result else rendered
        )
    return result


def response_diagnostic(
    response: Any,
    *,
    known_secrets: Iterable[str] = (),
) -> dict[str, JsonValue]:
    status_code = getattr(response, "status_code", None)
    reason = getattr(response, "reason_phrase", None) or getattr(response, "reason", None)
    headers = _headers_mapping(getattr(response, "headers", None))
    content_type = next(
        (value for key, value in headers.items() if key.lower() == "content-type"),
        None,
    )
    result: dict[str, JsonValue] = {
        "received": True,
        "status_code": status_code if isinstance(status_code, int) else None,
        "status_text": _redact_text(str(reason), known_secrets) if reason else None,
        "headers": sanitize_diagnostic(headers, known_secrets=known_secrets),
        "content_type": content_type,
    }

    payload: Any = None
    json_loader = getattr(response, "json", None)
    if callable(json_loader):
        try:
            payload = json_loader()
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = None
    if payload is not None:
        result["body"] = sanitize_diagnostic(payload, known_secrets=known_secrets)
        return result

    content = getattr(response, "content", None)
    if isinstance(content, bytes | bytearray | memoryview):
        raw = bytes(content)
        result["body_byte_count"] = len(raw)
        if content_type and (
            content_type.lower().startswith("text/")
            or "json" in content_type.lower()
            or "xml" in content_type.lower()
        ):
            result["body"] = sanitize_diagnostic(
                raw.decode("utf-8", errors="replace"), known_secrets=known_secrets
            )
        elif raw:
            result["body"] = _binary_summary(raw, kind="binary_response")
        else:
            result["body"] = ""
        return result

    text = getattr(response, "text", None)
    if text is not None:
        result["body"] = sanitize_diagnostic(str(text), known_secrets=known_secrets)
    return result


def no_response_diagnostic(reason: str) -> dict[str, JsonValue]:
    return {"received": False, "message": _redact_text(reason, ())}


def _exception_nodes(error: BaseException) -> list[BaseException]:
    nodes: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen and len(nodes) < _MAX_EXCEPTION_CHAIN:
        seen.add(id(current))
        nodes.append(current)
        current = current.__cause__ or current.__context__
    return nodes


def exception_chain(
    error: BaseException,
    *,
    known_secrets: Iterable[str] = (),
) -> dict[str, JsonValue]:
    chain: list[JsonValue] = []
    nodes = _exception_nodes(error)
    for item in nodes:
        node: dict[str, JsonValue] = {
            "type": f"{item.__class__.__module__}.{item.__class__.__name__}",
            "message": _redact_text(str(item) or item.__class__.__name__, known_secrets),
        }
        errno = getattr(item, "errno", None)
        winerror = getattr(item, "winerror", None)
        if isinstance(errno, int):
            node["errno"] = errno
        if isinstance(winerror, int):
            node["winerror"] = winerror
        request = getattr(item, "request", None)
        request_url = getattr(request, "url", None)
        if request_url is not None:
            node["request_url"] = sanitize_url(str(request_url), known_secrets=known_secrets)
        chain.append(node)
    root = nodes[-1] if nodes else error
    return {
        "chain": chain,
        "root_type": f"{root.__class__.__module__}.{root.__class__.__name__}",
        "root_message": _redact_text(str(root) or root.__class__.__name__, known_secrets),
    }


def transport_error_category(error: BaseException) -> str:
    nodes = _exception_nodes(error)
    joined = " ".join(f"{item.__class__.__name__} {str(item)}".lower() for item in nodes)
    if any(isinstance(item, (httpx.TimeoutException, TimeoutError)) for item in nodes):
        return "timeout"
    if any(isinstance(item, httpx.ProxyError) for item in nodes) or "proxy" in joined:
        return "proxy_error"
    if any(token in joined for token in ("getaddrinfo", "name resolution", "dns")):
        return "dns_error"
    if any(token in joined for token in ("certificate verify", "ssl", "tls")):
        return "tls_error"
    return "network_error"


def transport_error_phase(error: BaseException) -> str:
    nodes = _exception_nodes(error)
    if any(isinstance(item, httpx.ProxyError) for item in nodes):
        return "proxy"
    if any(isinstance(item, (httpx.ConnectError, httpx.ConnectTimeout)) for item in nodes):
        return "connect"
    if any(isinstance(item, httpx.WriteTimeout) for item in nodes):
        return "write"
    if any(isinstance(item, httpx.ReadTimeout) for item in nodes):
        return "read"
    if any(isinstance(item, httpx.PoolTimeout) for item in nodes):
        return "connection_pool"
    return "request"


def proxy_environment_diagnostic(*, trust_env: bool) -> dict[str, JsonValue]:
    variables: dict[str, JsonValue] = {}
    for name in _PROXY_NAMES:
        value = os.getenv(name)
        if not value:
            continue
        variables[name] = (
            _redact_text(value, ()) if name.lower() == "no_proxy" else sanitize_url(value)
        )
    return {
        "trust_environment_proxies": trust_env,
        "environment_proxy_present": any(name.lower() != "no_proxy" for name in variables),
        "environment_proxy_used": trust_env
        and any(name.lower() != "no_proxy" for name in variables),
        "variables": variables,
    }


def error_fingerprint(
    *,
    category: str,
    provider: str | None = None,
    phase: str | None = None,
    status_code: int | None = None,
    exception: BaseException | None = None,
) -> str:
    root_type = None
    if exception is not None:
        nodes = _exception_nodes(exception)
        root = nodes[-1] if nodes else exception
        root_type = f"{root.__class__.__module__}.{root.__class__.__name__}"
    payload = json.dumps(
        {
            "category": category,
            "provider": provider,
            "phase": phase,
            "status_code": status_code,
            "root_type": root_type,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def with_provider_diagnostic(
    error: ProviderError,
    diagnostic: ProviderDiagnostic,
) -> ProviderError:
    """Copy a provider error while preserving retry semantics and adding missing context."""

    if error.diagnostic is not None:
        return error
    return ProviderError(
        str(error),
        retryable=error.retryable,
        status_code=error.status_code,
        retry_after=error.retry_after,
        diagnostic=diagnostic,
        origin=error.origin,
    )
