"""Shared domain and engine contracts for the local-first SPLICR Studio."""

from .domain import (
    Artifact,
    ArtifactKind,
    Project,
    RenderPlan,
    RenderSegment,
    Take,
    TakeStatus,
)
from .engines import (
    EngineAdapter,
    EngineDescriptor,
    EngineSession,
    EngineSessionContext,
    EngineTransport,
    ProviderEngineAdapter,
    engine_adapter_for_provider,
)
from .local_subprocess import LocalSubprocessEngineAdapter, LocalSubprocessSpec

__all__ = [
    "Artifact",
    "ArtifactKind",
    "EngineAdapter",
    "EngineDescriptor",
    "EngineSession",
    "EngineSessionContext",
    "EngineTransport",
    "LocalSubprocessEngineAdapter",
    "LocalSubprocessSpec",
    "Project",
    "ProviderEngineAdapter",
    "RenderPlan",
    "RenderSegment",
    "Take",
    "TakeStatus",
    "engine_adapter_for_provider",
]
