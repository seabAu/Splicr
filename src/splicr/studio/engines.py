from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import AsyncContextManager, AsyncIterator, Protocol

from splicr.domain import AudioChunk, ProviderInfo, SynthesisOptions, TtsProvider


class EngineTransport(StrEnum):
    LOCAL_SUBPROCESS = "local_subprocess"
    LOCAL_HTTP = "local_http"
    REMOTE_HTTP = "remote_http"


@dataclass(frozen=True, slots=True)
class EngineDescriptor:
    id: str
    display_name: str
    transport: EngineTransport
    provider_info: ProviderInfo

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("engine id must not be blank")
        if not self.display_name.strip():
            raise ValueError("engine display name must not be blank")


@dataclass(frozen=True, slots=True)
class EngineSessionContext:
    """Stable job identity and storage assigned to one engine session.

    Project and plan ids remain optional while legacy SPLICR jobs are migrated into
    the Studio hierarchy. A legacy job is itself the initial take.
    """

    job_id: str
    take_id: str
    work_directory: Path
    project_id: str | None = None
    render_plan_id: str | None = None
    resume: bool = False

    def __post_init__(self) -> None:
        for field_name in ("job_id", "take_id"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must not be blank")
        for field_name in ("project_id", "render_plan_id"):
            value = getattr(self, field_name)
            if value is not None and not value.strip():
                raise ValueError(f"{field_name} must not be blank when provided")
        if not self.work_directory.is_absolute():
            raise ValueError("engine work directory must be absolute")


class EngineSession(Protocol):
    async def synthesize(self, text: str, options: SynthesisOptions) -> AudioChunk: ...


class EngineAdapter(Protocol):
    @property
    def descriptor(self) -> EngineDescriptor: ...

    def estimate_input_tokens(self, text: str, options: SynthesisOptions) -> int: ...

    def estimate_input_characters(self, text: str, options: SynthesisOptions) -> int: ...

    def open_session(
        self,
        context: EngineSessionContext,
    ) -> AsyncContextManager[EngineSession]: ...


@dataclass(slots=True)
class _ProviderEngineSession:
    provider: TtsProvider

    async def synthesize(self, text: str, options: SynthesisOptions) -> AudioChunk:
        return await self.provider.synthesize(text, options)


class ProviderEngineAdapter:
    """Expose an existing stateless remote provider through the session contract."""

    def __init__(
        self,
        provider: TtsProvider,
        *,
        engine_id: str | None = None,
        display_name: str | None = None,
        transport: EngineTransport = EngineTransport.REMOTE_HTTP,
    ) -> None:
        self._provider = provider
        info = provider.info
        self._descriptor = EngineDescriptor(
            id=engine_id or info.name,
            display_name=display_name or info.name,
            transport=transport,
            provider_info=info,
        )

    @property
    def descriptor(self) -> EngineDescriptor:
        return self._descriptor

    def estimate_input_tokens(self, text: str, options: SynthesisOptions) -> int:
        return self._provider.estimate_input_tokens(text, options)

    def estimate_input_characters(self, text: str, options: SynthesisOptions) -> int:
        return self._provider.estimate_input_characters(text, options)

    @asynccontextmanager
    async def open_session(
        self,
        context: EngineSessionContext,
    ) -> AsyncIterator[EngineSession]:
        del context
        yield _ProviderEngineSession(self._provider)


def engine_adapter_for_provider(provider: TtsProvider) -> EngineAdapter:
    """Use an engine-aware provider's adapter, otherwise bridge the remote provider."""

    create_adapter = getattr(provider, "create_engine_adapter", None)
    if create_adapter is None:
        transport = EngineTransport(
            getattr(provider, "engine_transport", EngineTransport.REMOTE_HTTP)
        )
        return ProviderEngineAdapter(provider, transport=transport)
    adapter = create_adapter()
    if adapter.descriptor.provider_info.name != provider.info.name:
        raise ValueError("engine adapter provider identity does not match its provider")
    return adapter
