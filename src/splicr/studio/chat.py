from __future__ import annotations

import ipaddress
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx

from .dialogue import ChatMessage


class ChatCompletionError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


def _is_loopback(hostname: str | None) -> bool:
    if not hostname:
        return False
    if hostname.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True, slots=True)
class ChatResource:
    resource_id: str
    name: str
    base_url: str
    model: str
    local: bool = False
    allow_insecure_http: bool = False
    headers: Mapping[str, str] = field(default_factory=dict)
    timeout_seconds: float = 180.0

    def __post_init__(self) -> None:
        for label, value in (
            ("resource_id", self.resource_id),
            ("name", self.name),
            ("base_url", self.base_url),
            ("model", self.model),
        ):
            if not value.strip():
                raise ValueError(f"{label} must not be blank")
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("base_url must be an absolute HTTP(S) URL")
        if parsed.username or parsed.password:
            raise ValueError("base_url must not contain credentials")
        if parsed.query or parsed.fragment:
            raise ValueError("base_url must not contain a query or fragment")
        if (
            parsed.scheme == "http"
            and not _is_loopback(parsed.hostname)
            and not self.allow_insecure_http
        ):
            raise ValueError("non-loopback HTTP requires allow_insecure_http")
        if self.timeout_seconds <= 0 or self.timeout_seconds > 900:
            raise ValueError("timeout_seconds must be between 0 and 900")
        normalized_headers: dict[str, str] = {}
        for name, value in self.headers.items():
            if "\r" in name or "\n" in name or "\r" in value or "\n" in value:
                raise ValueError("chat headers cannot contain newlines")
            if name.casefold() in {"authorization", "proxy-authorization", "cookie"}:
                raise ValueError(f"credential-bearing header {name!r} is managed by SPLICR")
            normalized_headers[name] = value
        object.__setattr__(self, "base_url", self.base_url.rstrip("/"))
        object.__setattr__(self, "headers", normalized_headers)


class OpenAiChatCompleter:
    """OpenAI chat-completions transport for local and hosted model servers."""

    def __init__(
        self,
        resource: ChatResource,
        *,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.resource = resource
        self._api_key = api_key
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> "OpenAiChatCompleter":
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2_048,
    ) -> str:
        if not messages:
            raise ValueError("at least one chat message is required")
        if not 0 <= temperature <= 2:
            raise ValueError("temperature must be between 0 and 2")
        if max_tokens < 1:
            raise ValueError("max_tokens must be positive")
        headers = {"Content-Type": "application/json", **self.resource.headers}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        payload: dict[str, Any] = {
            "model": model or self.resource.model,
            "messages": list(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        client = self._client
        if client is None:
            client = httpx.AsyncClient(timeout=self.resource.timeout_seconds)
            self._client = client
        try:
            response = await client.post(
                f"{self.resource.base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            detail = _safe_error_detail(error.response)
            if status in {401, 403}:
                message = f"The chat provider rejected its credential ({status})."
            elif status == 404:
                message = "The chat endpoint or selected model was not found (404)."
            elif status == 429:
                message = "The chat provider is rate limited or out of quota (429)."
            else:
                message = f"The chat provider returned HTTP {status}."
            if detail:
                message = f"{message} {detail}"
            raise ChatCompletionError(
                message,
                status_code=status,
                retryable=status in {408, 409, 425, 429} or status >= 500,
            ) from error
        except (httpx.TimeoutException, httpx.NetworkError) as error:
            location = "local model server" if self.resource.local else "chat provider"
            raise ChatCompletionError(
                f"Could not reach the {location}: {type(error).__name__}.",
                retryable=True,
            ) from error
        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as error:
            raise ChatCompletionError(
                "The provider response was not an OpenAI-compatible chat completion."
            ) from error
        if not isinstance(content, str) or not content.strip():
            raise ChatCompletionError("The chat provider returned an empty response.")
        return content


def _safe_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return ""
    if not isinstance(payload, Mapping):
        return ""
    error = payload.get("error")
    if isinstance(error, Mapping) and isinstance(error.get("message"), str):
        return error["message"][:400]
    if isinstance(payload.get("message"), str):
        return payload["message"][:400]
    return ""
