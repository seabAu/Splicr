from __future__ import annotations

import inspect
from collections.abc import Iterable
from typing import Protocol

from ..domain import ProviderInfo, TtsProvider, UnknownProviderError


class TtsProviderRegistry(Protocol):
    def get(self, name: str) -> TtsProvider: ...

    def list(self) -> list[ProviderInfo]: ...

    async def close(self) -> None: ...


class ProviderRegistry:
    def __init__(self, providers: Iterable[TtsProvider] = ()) -> None:
        self._providers: dict[str, TtsProvider] = {}
        for provider in providers:
            self.register(provider)

    def register(self, provider: TtsProvider) -> None:
        name = provider.info.name.strip().lower()
        if not name:
            raise ValueError("provider name cannot be empty")
        if name in self._providers:
            raise ValueError(f"provider already registered: {name}")
        self._providers[name] = provider

    def get(self, name: str) -> TtsProvider:
        try:
            return self._providers[name.strip().lower()]
        except KeyError as error:
            raise UnknownProviderError(f"unknown TTS provider: {name}") from error

    def list(self) -> list[ProviderInfo]:
        return [provider.info for provider in self._providers.values()]

    async def close(self) -> None:
        for provider in self._providers.values():
            close = getattr(provider, "close", None)
            if close is None:
                continue
            result = close()
            if inspect.isawaitable(result):
                await result


class CompositeProviderRegistry:
    """Overlay local engine providers on a durable API-resource registry."""

    def __init__(
        self,
        primary: TtsProviderRegistry,
        extras: Iterable[TtsProvider] = (),
    ) -> None:
        self.primary = primary
        self._extras: dict[str, TtsProvider] = {}
        for provider in extras:
            name = provider.info.name.strip().lower()
            if not name:
                raise ValueError("provider name cannot be empty")
            if name in self._extras:
                raise ValueError(f"provider already registered: {name}")
            self._extras[name] = provider

    @property
    def store(self) -> object | None:
        return getattr(self.primary, "store", None)

    def get(self, name: str) -> TtsProvider:
        normalized = name.strip().lower()
        if normalized in self._extras:
            return self._extras[normalized]
        return self.primary.get(name)

    def get_revision(self, name: str, revision: int) -> TtsProvider:
        normalized = name.strip().lower()
        if normalized in self._extras:
            raise UnknownProviderError(
                f"local engine provider does not have resource revision {revision}: {name}"
            )
        resolver = getattr(self.primary, "get_revision", None)
        if resolver is None:
            return self.primary.get(name)
        return resolver(name, revision)

    def current_revision(self, name: str) -> int | None:
        if name.strip().lower() in self._extras:
            return None
        resolver = getattr(self.primary, "current_revision", None)
        return resolver(name) if resolver is not None else None

    def retry_policy(self, name: str, revision: int | None = None):
        if name.strip().lower() in self._extras:
            return None
        resolver = getattr(self.primary, "retry_policy", None)
        return resolver(name, revision) if resolver is not None else None

    def list(self) -> list[ProviderInfo]:
        extras = list(self._extras.values())
        extra_names = set(self._extras)
        primary_infos = [
            info for info in self.primary.list() if info.name.strip().lower() not in extra_names
        ]
        return [*primary_infos, *(provider.info for provider in extras)]

    async def close(self) -> None:
        await self.primary.close()
        for provider in self._extras.values():
            close = getattr(provider, "close", None)
            if close is None:
                continue
            result = close()
            if inspect.isawaitable(result):
                await result
