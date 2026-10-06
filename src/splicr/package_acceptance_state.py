from __future__ import annotations

import hashlib
import json
import math
import struct
from pathlib import Path
from typing import Any

from .config import Settings
from .domain import ChunkStatus, DeliveryControls, JobStatus
from .planning import ChunkTargetMode, SplitStrategy
from .profiles import StudioProfileStore
from .storage import LocalJobStorage
from .store import SqliteJobStore
from .studio import (
    Artifact,
    ArtifactKind,
    Project,
    RenderPlan,
    RenderSegment,
    SqliteStudioStore,
    Take,
    TakeStatus,
    VoiceProfile,
    VoiceProfileKind,
)


_SCHEMA_VERSION = 1
_PROJECT_ID = "package-acceptance-project-v1"
_RENDER_PLAN_ID = "package-acceptance-plan-v1"
_TAKE_ID = "package-acceptance-take-v1"
_ARTIFACT_ID = "package-acceptance-audio-v1"
_VOICE_PROFILE_ID = "package-acceptance-voice-v1"
_JOB_ID = "package-acceptance-job-v1"
_SOURCE_TEXT = (
    "# Package acceptance\n\n"
    "This durable project proves that jobs, profiles, render plans, and generated media survive "
    "an application uninstall and reinstall."
)
_ENGINE_ID = "package-acceptance"
_VOICE_ID = "acceptance-voice"


class PackageAcceptanceStateError(RuntimeError):
    """Representative package state could not be seeded or verified."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _relative_file(data_dir: Path, path: Path) -> dict[str, Any]:
    resolved_data_dir = data_dir.resolve()
    resolved_path = path.resolve()
    try:
        relative = resolved_path.relative_to(resolved_data_dir)
    except ValueError as error:
        raise PackageAcceptanceStateError(
            "acceptance file escaped the application data directory"
        ) from error
    return {
        "relative_path": relative.as_posix(),
        "bytes": resolved_path.stat().st_size,
        "sha256": _sha256(resolved_path),
    }


def _deterministic_pcm() -> bytes:
    sample_rate = 24_000
    frames = sample_rate // 5
    return b"".join(
        struct.pack("<h", round(math.sin(2 * math.pi * 330 * index / sample_rate) * 3_000))
        for index in range(frames)
    )


def seed_package_acceptance_state(settings: Settings, manifest_path: Path) -> dict[str, Any]:
    """Create real representative state for package uninstall/reinstall acceptance."""

    manifest_path = Path(manifest_path).resolve()
    if manifest_path.exists():
        raise PackageAcceptanceStateError("acceptance manifest already exists")

    jobs = SqliteJobStore(settings.database_path)
    storage = LocalJobStorage(settings.jobs_dir)
    studio = SqliteStudioStore(settings.database_path)
    profiles = StudioProfileStore(settings.database_path)
    jobs.initialize()
    storage.initialize()
    studio.initialize()
    profiles.initialize()

    try:
        jobs.get_job(_JOB_ID)
    except LookupError:
        pass
    else:
        raise PackageAcceptanceStateError("acceptance job already exists")

    studio.save_project(
        Project(
            id=_PROJECT_ID,
            name="Package acceptance project",
            source_text=_SOURCE_TEXT,
            source_name="package-acceptance.md",
            source_media_type="text/markdown",
            metadata={"acceptance_fixture": True, "schema_version": _SCHEMA_VERSION},
        )
    )
    studio.save_voice_profile(
        VoiceProfile(
            id=_VOICE_PROFILE_ID,
            label="Package acceptance voice",
            engine_id=_ENGINE_ID,
            kind=VoiceProfileKind.PRESET,
            description="Deterministic package lifecycle fixture",
            settings={"voice_id": _VOICE_ID, "seed": 424242},
            metadata={"acceptance_fixture": True},
        )
    )
    plan = studio.create_render_plan(
        RenderPlan(
            id=_RENDER_PLAN_ID,
            project_id=_PROJECT_ID,
            revision=1,
            segments=(
                RenderSegment(
                    id="package-acceptance-segment-v1",
                    ordinal=0,
                    text=_SOURCE_TEXT,
                    source_start=0,
                    source_end=len(_SOURCE_TEXT),
                    engine_id=_ENGINE_ID,
                    voice_id=_VOICE_ID,
                    instructions="Read clearly and consistently.",
                    settings={"seed": 424242, "pace": "normal"},
                ),
            ),
            metadata={
                "acceptance_fixture": True,
                "source_sha256": hashlib.sha256(_SOURCE_TEXT.encode()).hexdigest(),
            },
        )
    )
    studio.create_take(
        Take(
            id=_TAKE_ID,
            project_id=_PROJECT_ID,
            render_plan_id=plan.id,
            label="Package acceptance take",
            status=TakeStatus.COMPLETED,
        )
    )

    jobs.create_job_with_chunks(
        job_id=_JOB_ID,
        provider=_ENGINE_ID,
        model="acceptance-model-v1",
        voice=_VOICE_ID,
        instructions="Read clearly and consistently.",
        controls=DeliveryControls(),
        variables={"seed": 424242},
        chunks=[_SOURCE_TEXT],
        export_stem="package-acceptance",
    )
    source_path = storage.write_source(_JOB_ID, _SOURCE_TEXT)
    chunk_path = storage.write_chunk(_JOB_ID, 0, _deterministic_pcm())
    jobs.mark_job_running(_JOB_ID)
    jobs.mark_chunk_completed(
        _JOB_ID,
        0,
        str(chunk_path),
        {"acceptance_fixture": True, "sample_rate": 24_000},
    )
    output_path = storage.assemble_wav(_JOB_ID, [chunk_path])
    jobs.mark_job_completed(_JOB_ID, str(output_path))

    output_record = _relative_file(settings.data_dir, output_path)
    studio.add_artifact(
        Artifact(
            id=_ARTIFACT_ID,
            project_id=_PROJECT_ID,
            take_id=_TAKE_ID,
            kind=ArtifactKind.AUDIO,
            path=str(output_path),
            media_type="audio/wav",
            size_bytes=output_record["bytes"],
            sha256=output_record["sha256"],
            metadata={"job_id": _JOB_ID, "acceptance_fixture": True},
        )
    )
    saved_profile = profiles.create(
        name="Package acceptance profile",
        resource_id=_ENGINE_ID,
        resource_revision=1,
        text=_SOURCE_TEXT,
        model="acceptance-model-v1",
        voice=_VOICE_ID,
        voice_profile_id=_VOICE_PROFILE_ID,
        instructions="Read clearly and consistently.",
        controls=DeliveryControls(),
        split_strategy=SplitStrategy.DOUBLE_NEWLINE,
        chunk_target_mode=ChunkTargetMode.AUTOMATIC,
        remove_numeric_citations=True,
        variables={"seed": 424242},
        job_id=_JOB_ID,
    )

    manifest = {
        "schema_version": _SCHEMA_VERSION,
        "entities": {
            "project_id": _PROJECT_ID,
            "render_plan_id": _RENDER_PLAN_ID,
            "take_id": _TAKE_ID,
            "artifact_id": _ARTIFACT_ID,
            "voice_profile_id": _VOICE_PROFILE_ID,
            "studio_profile_id": saved_profile.id,
            "job_id": _JOB_ID,
        },
        "source_sha256": hashlib.sha256(_SOURCE_TEXT.encode("utf-8")).hexdigest(),
        "files": {
            "source": _relative_file(settings.data_dir, source_path),
            "checkpoint": _relative_file(settings.data_dir, chunk_path),
            "output": output_record,
        },
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = manifest_path.with_name(f".{manifest_path.name}.tmp")
    temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(manifest_path)
    return manifest


def verify_package_acceptance_state(settings: Settings, manifest_path: Path) -> dict[str, Any]:
    """Semantically reopen and hash-check package state after a lifecycle transition."""

    try:
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PackageAcceptanceStateError("could not read the acceptance manifest") from error
    if not isinstance(manifest, dict) or manifest.get("schema_version") != _SCHEMA_VERSION:
        raise PackageAcceptanceStateError("unsupported acceptance manifest schema")
    entities = manifest.get("entities")
    files = manifest.get("files")
    if not isinstance(entities, dict) or not isinstance(files, dict):
        raise PackageAcceptanceStateError("acceptance manifest is incomplete")
    required_entities = {
        "project_id",
        "render_plan_id",
        "take_id",
        "artifact_id",
        "voice_profile_id",
        "studio_profile_id",
        "job_id",
    }
    if not required_entities.issubset(entities) or not {
        "source",
        "checkpoint",
        "output",
    }.issubset(files):
        raise PackageAcceptanceStateError("acceptance manifest is incomplete")
    if any(not isinstance(files[label], dict) for label in ("source", "checkpoint", "output")):
        raise PackageAcceptanceStateError("acceptance manifest file records are invalid")

    jobs = SqliteJobStore(settings.database_path)
    studio = SqliteStudioStore(settings.database_path)
    profiles = StudioProfileStore(settings.database_path)
    jobs.initialize()
    studio.initialize()
    profiles.initialize()

    try:
        job = jobs.get_job(str(entities["job_id"]))
        chunks = jobs.chunks_for_job(job.id)
        project = studio.get_project(str(entities["project_id"]))
        plan = studio.get_render_plan(str(entities["render_plan_id"]))
        take = studio.get_take(str(entities["take_id"]))
        artifact = studio.get_artifact(str(entities["artifact_id"]))
        voice_profile = studio.get_voice_profile(str(entities["voice_profile_id"]))
        profile = profiles.get(str(entities["studio_profile_id"]))
    except (KeyError, LookupError) as error:
        raise PackageAcceptanceStateError(
            "representative application records did not reopen"
        ) from error

    source_sha256 = hashlib.sha256(project.source_text.encode("utf-8")).hexdigest()
    if source_sha256 != manifest.get("source_sha256") or project.source_text != _SOURCE_TEXT:
        raise PackageAcceptanceStateError("project source changed across the package lifecycle")
    if job.status is not JobStatus.COMPLETED or job.completed_chunks != 1 or job.total_chunks != 1:
        raise PackageAcceptanceStateError("completed synthesis job did not reopen intact")
    if len(chunks) != 1 or chunks[0].status is not ChunkStatus.COMPLETED:
        raise PackageAcceptanceStateError("completed synthesis checkpoint did not reopen intact")
    if plan.project_id != project.id or plan.segments[0].settings.get("seed") != 424242:
        raise PackageAcceptanceStateError(
            "immutable render plan changed across the package lifecycle"
        )
    if take.status is not TakeStatus.COMPLETED or take.render_plan_id != plan.id:
        raise PackageAcceptanceStateError("completed take did not reopen intact")
    if artifact.sha256 != files["output"].get("sha256") or artifact.take_id != take.id:
        raise PackageAcceptanceStateError("generated-media artifact record changed")
    if voice_profile.settings.get("seed") != 424242 or profile.voice_profile_id != voice_profile.id:
        raise PackageAcceptanceStateError("saved voice or Studio profile changed")
    if profile.job_id != job.id or profile.variables.get("seed") != 424242:
        raise PackageAcceptanceStateError(
            "saved Studio profile lost its job or deterministic controls"
        )

    for label in ("source", "checkpoint", "output"):
        record = files.get(label)
        if not isinstance(record, dict):
            raise PackageAcceptanceStateError(f"acceptance manifest omits {label}")
        relative = Path(str(record.get("relative_path", "")))
        if relative.is_absolute() or ".." in relative.parts:
            raise PackageAcceptanceStateError(f"unsafe {label} path in acceptance manifest")
        path = (settings.data_dir / relative).resolve()
        try:
            path.relative_to(settings.data_dir.resolve())
        except ValueError as error:
            raise PackageAcceptanceStateError(
                f"unsafe {label} path in acceptance manifest"
            ) from error
        if not path.is_file():
            raise PackageAcceptanceStateError(f"preserved {label} file is missing")
        if path.stat().st_size != record.get("bytes") or _sha256(path) != record.get("sha256"):
            raise PackageAcceptanceStateError(f"preserved {label} file changed")

    return {
        "schema_version": _SCHEMA_VERSION,
        "verified": True,
        "entity_count": len(entities),
        "file_count": len(files),
    }
