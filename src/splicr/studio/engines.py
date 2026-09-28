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
    """Stable job identity and storage assigned to one engine session."""

    job_id: str
    project_id: str
    render_plan_id: str
    take_id: str
    work_directory: Path
    resume: bool = False

    def __post_init__(self) -> None:
        for field_name in ("job_id", "project_id", "render_plan_id", "take_id"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must not be blank")
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
    ) -> None:
        self._provider = provider
        info = provider.info
        self._descriptor = EngineDescriptor(
            id=engine_id or info.name,
            display_name=display_name or info.name,
            transport=EngineTransport.REMOTE_HTTP,
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
