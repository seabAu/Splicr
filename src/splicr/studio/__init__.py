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
from .migration import (
    ImportedJob,
    ImportedNarratorCustomizations,
    ImportedNarratorProject,
    NarratorProjectManifest,
    NarratorSnapshot,
    NarratorVoiceManifest,
    import_narrator_customizations,
    import_narrator_projects,
    import_splicr_job,
    import_splicr_jobs,
    scan_narrator_data,
)
from .store import ImportRecord, SqliteStudioStore

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
    "ImportRecord",
    "ImportedJob",
    "ImportedNarratorCustomizations",
    "ImportedNarratorProject",
    "NarratorProjectManifest",
    "NarratorSnapshot",
    "NarratorVoiceManifest",
    "Project",
    "ProviderEngineAdapter",
    "RenderPlan",
    "RenderSegment",
    "Take",
    "TakeStatus",
    "SqliteStudioStore",
    "engine_adapter_for_provider",
    "import_narrator_customizations",
    "import_narrator_projects",
    "import_splicr_job",
    "import_splicr_jobs",
    "scan_narrator_data",
]
