from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

import httpx

from splicr.diagnostics import (
    error_fingerprint,
    exception_chain,
    no_response_diagnostic,
    proxy_environment_diagnostic,
    response_diagnostic,
    sanitize_diagnostic,
    sanitize_url,
)


def test_recursively_redacts_secrets_and_summarizes_audio() -> None:
    secret = "a-secret/key+value"
    value = {
        "headers": {
            "Authorization": f"Bearer {secret}",
            "Cookie": "session=private",
            "Content-Type": "application/json",
        },
        "body": {
            "text": f"The exact credential is {secret}",
            "password": "private",
            "audioContent": "YWJjZA==",
        },
    }

    sanitized = sanitize_diagnostic(value, known_secrets=(secret,))
    serialized = json.dumps(sanitized)

    assert secret not in serialized
    assert "a-secret%2Fkey%2Bvalue" not in serialized
    assert sanitized["headers"]["Authorization"] == "[REDACTED]"  # type: ignore[index]
    assert sanitized["headers"]["Cookie"] == "[REDACTED]"  # type: ignore[index]
    assert sanitized["body"]["password"] == "[REDACTED]"  # type: ignore[index]
    assert sanitized["body"]["audioContent"]["kind"] == "base64_audio"  # type: ignore[index]


def test_nested_absolute_url_redacts_userinfo_and_percent_encoded_api_key() -> None:
    value = {
        "nested": {
            "callback": (
                "https://user:password@example.test/path?%61pi_key=encoded-secret&visible=yes"
            )
        }
    }

    sanitized = sanitize_diagnostic(value)
    callback = sanitized["nested"]["callback"]  # type: ignore[index]
    assert isinstance(callback, str)
    parsed = urlsplit(callback)
    query = parse_qs(parsed.query)

    assert "user" not in parsed.netloc
    assert "password" not in parsed.netloc
    assert parsed.netloc == "%5BREDACTED%5D@example.test"
    assert query == {"api_key": ["[REDACTED]"], "visible": ["yes"]}


def test_exception_chain_is_bounded_json_safe_and_redacted() -> None:
    secret = "transport-secret"
    request = httpx.Request(
        "POST",
        f"https://user:{secret}@tts.example.test/speak?token={secret}",
    )
    try:
        try:
            raise OSError(10061, f"connection failed using {secret}")
        except OSError as cause:
            raise httpx.ConnectError(
                f"could not connect using {secret}", request=request
            ) from cause
    except httpx.ConnectError as error:
        diagnostic = exception_chain(error, known_secrets=(secret,))

    serialized = json.dumps(diagnostic)
    assert secret not in serialized
    assert diagnostic["root_type"] == "builtins.ConnectionRefusedError"
    chain = diagnostic["chain"]
    assert isinstance(chain, list)
    assert chain[0]["type"] == "httpx.ConnectError"  # type: ignore[index]
    assert "%5BREDACTED%5D@tts.example.test" in chain[0]["request_url"]  # type: ignore[index]


def test_response_diagnostic_redacts_headers_and_json_audio() -> None:
    secret = "response-secret"
    response = httpx.Response(
        429,
        headers={
            "Content-Type": "application/json",
            "Set-Cookie": f"session={secret}",
            "X-Request-Id": "request-123",
        },
        json={
            "message": f"quota for {secret}",
            "api_key": secret,
            "audioContent": "YWJjZA==",
        },
    )

    diagnostic = response_diagnostic(response, known_secrets=(secret,))
    serialized = json.dumps(diagnostic)

    assert secret not in serialized
    assert diagnostic["status_code"] == 429
    assert diagnostic["headers"]["set-cookie"] == "[REDACTED]"  # type: ignore[index]
    assert diagnostic["headers"]["x-request-id"] == "request-123"  # type: ignore[index]
    assert diagnostic["body"]["audioContent"]["kind"] == "base64_audio"  # type: ignore[index]


def test_proxy_environment_and_no_response_are_explicit(monkeypatch) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy-user:proxy-pass@127.0.0.1:9")

    proxy = proxy_environment_diagnostic(trust_env=False)
    serialized = json.dumps(proxy)

    assert "proxy-user" not in serialized
    assert "proxy-pass" not in serialized
    assert proxy["environment_proxy_present"] is True
    assert proxy["environment_proxy_used"] is False
    assert no_response_diagnostic("Connection failed") == {
        "received": False,
        "message": "Connection failed",
    }


def test_sanitize_url_and_fingerprint_are_deterministic() -> None:
    url = sanitize_url("https://user:pass@example.test/path?token=value&visible=yes")
    assert url == ("https://%5BREDACTED%5D@example.test/path?token=%5BREDACTED%5D&visible=yes")
    first = error_fingerprint(
        category="network_error",
        provider="inworld",
        phase="connect",
        status_code=None,
    )
    second = error_fingerprint(
        category="network_error",
        provider="inworld",
        phase="connect",
        status_code=None,
    )
    assert first == second
    assert len(first) == 64
