from __future__ import annotations

import inspect
from collections.abc import Iterable

from ..domain import ProviderInfo, TtsProvider, UnknownProviderError


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
