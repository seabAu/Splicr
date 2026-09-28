from __future__ import annotations

import asyncio

import pytest

from splicr.domain import UnknownProviderError
from splicr.providers import CompositeProviderRegistry, ProviderRegistry
from tests.fakes import RecordingProvider


class NamedRecordingProvider(RecordingProvider):
    def __init__(self, name: str) -> None:
        super().__init__()
        self._info = self.info.__class__(
            name=name,
            default_model=self.info.default_model,
            default_voice=self.info.default_voice,
            max_input_bytes=self.info.max_input_bytes,
            max_input_tokens=self.info.max_input_tokens,
        )

    @property
    def info(self):
        return self._info if hasattr(self, "_info") else super().info


def test_composite_registry_resolves_local_overlay_and_primary_provider() -> None:
    primary_provider = NamedRecordingProvider("remote")
    local_provider = NamedRecordingProvider("local")
    registry = CompositeProviderRegistry(
        ProviderRegistry((primary_provider,)),
        (local_provider,),
    )

    assert registry.get("remote") is primary_provider
    assert registry.get("LOCAL") is local_provider
    assert [info.name for info in registry.list()] == ["remote", "local"]
    assert registry.current_revision("local") is None
    assert registry.retry_policy("local") is None
    with pytest.raises(UnknownProviderError, match="does not have resource revision"):
        registry.get_revision("local", 1)

    asyncio.run(registry.close())
