from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from string import hexdigits
from typing import Mapping

from splicr.domain import JsonValue, utc_now


def _require_identifier(value: str, field_name: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{field_name} must not be blank")


class TakeStatus(StrEnum):
    DRAFT = "draft"
    QUEUED = "queued"
    RENDERING = "rendering"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ArtifactKind(StrEnum):
    AUDIO = "audio"
    VIDEO = "video"
    SUBTITLES = "subtitles"
    CHAPTERS = "chapters"
    TRANSCRIPT = "transcript"
    MANIFEST = "manifest"


class VoiceProfileKind(StrEnum):
    """How a reusable voice is reproduced by its engine."""

    DESIGNED = "designed"
    CLONED = "cloned"
    PRESET = "preset"
    BLEND = "blend"


@dataclass(frozen=True, slots=True)
class Project:
    """User-authored source and metadata shared by all renders."""

    id: str
    name: str
    source_text: str = ""
    source_name: str | None = None
    source_media_type: str = "text/plain"
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _require_identifier(self.id, "project id")
        _require_identifier(self.name, "project name")
        _require_identifier(self.source_media_type, "source media type")


@dataclass(frozen=True, slots=True)
class RenderSegment:
    """One ordered synthesis unit, independent of how its engine is hosted."""

    id: str
    ordinal: int
    text: str
    source_start: int
    source_end: int
    engine_id: str
    voice_id: str
    speaker: str | None = None
    instructions: str | None = None
    settings: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_identifier(self.id, "segment id")
        _require_identifier(self.engine_id, "engine id")
        _require_identifier(self.voice_id, "voice id")
        if self.ordinal < 0:
            raise ValueError("segment ordinal must be non-negative")
        if not self.text.strip():
            raise ValueError("segment text must not be blank")
        if self.source_start < 0 or self.source_end <= self.source_start:
            raise ValueError("segment source span must be positive and ordered")


@dataclass(frozen=True, slots=True)
class RenderPlan:
    """A versioned, reproducible description of what a take should render."""

    id: str
    project_id: str
    revision: int
    segments: tuple[RenderSegment, ...]
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _require_identifier(self.id, "render plan id")
        _require_identifier(self.project_id, "project id")
        if self.revision < 1:
            raise ValueError("render plan revision must be at least 1")
        if not self.segments:
            raise ValueError("render plan must contain at least one segment")
        ordinals = tuple(segment.ordinal for segment in self.segments)
        if ordinals != tuple(range(len(self.segments))):
            raise ValueError("render plan segment ordinals must be contiguous and ordered")
        ids = {segment.id for segment in self.segments}
        if len(ids) != len(self.segments):
            raise ValueError("render plan segment ids must be unique")


@dataclass(frozen=True, slots=True)
class Take:
    """One execution of an immutable render-plan revision."""

    id: str
    project_id: str
    render_plan_id: str
    label: str
    status: TakeStatus = TakeStatus.DRAFT
    artifact_ids: tuple[str, ...] = ()
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _require_identifier(self.id, "take id")
        _require_identifier(self.project_id, "project id")
        _require_identifier(self.render_plan_id, "render plan id")
        _require_identifier(self.label, "take label")
        if len(set(self.artifact_ids)) != len(self.artifact_ids):
            raise ValueError("take artifact ids must be unique")


@dataclass(frozen=True, slots=True)
class Artifact:
    """A durable file or manifest emitted by a take."""

    id: str
    project_id: str
    take_id: str
    kind: ArtifactKind
    path: str
    media_type: str
    size_bytes: int
    sha256: str | None = None
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _require_identifier(self.id, "artifact id")
        _require_identifier(self.project_id, "project id")
        _require_identifier(self.take_id, "take id")
        _require_identifier(self.path, "artifact path")
        _require_identifier(self.media_type, "artifact media type")
        if self.size_bytes < 0:
            raise ValueError("artifact size must be non-negative")
        if self.sha256 is not None:
            if len(self.sha256) != 64 or any(character not in hexdigits for character in self.sha256):
                raise ValueError("artifact sha256 must be a 64-character hexadecimal digest")


@dataclass(frozen=True, slots=True)
class VoiceProfile:
    """A reusable voice identity, independent of where its engine runs."""

    id: str
    label: str
    engine_id: str
    kind: VoiceProfileKind
    description: str = ""
    reference_audio_path: str | None = None
    reference_text: str | None = None
    settings: Mapping[str, JsonValue] = field(default_factory=dict)
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _require_identifier(self.id, "voice profile id")
        _require_identifier(self.label, "voice profile label")
        _require_identifier(self.engine_id, "voice profile engine id")
        if self.kind in {VoiceProfileKind.DESIGNED, VoiceProfileKind.CLONED}:
            if not self.reference_audio_path:
                raise ValueError("designed and cloned voices require reference audio")
        if self.kind is VoiceProfileKind.CLONED and not (self.reference_text or "").strip():
            raise ValueError("cloned voices require the exact reference transcript")
