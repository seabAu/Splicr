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
)

__all__ = [
    "Artifact",
    "ArtifactKind",
    "EngineAdapter",
    "EngineDescriptor",
    "EngineSession",
    "EngineSessionContext",
    "EngineTransport",
    "Project",
    "ProviderEngineAdapter",
    "RenderPlan",
    "RenderSegment",
    "Take",
    "TakeStatus",
]
