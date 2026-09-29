from __future__ import annotations

import hashlib
import json
import math
import mimetypes
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping
from uuid import NAMESPACE_URL, uuid5

from splicr.domain import (
    SEGMENT_OPTIONS_VARIABLE,
    ChunkRecord,
    JobRecord,
    JobStatus,
    JsonValue,
)
from splicr.pronunciation import TextCustomizationStore
from splicr.storage import LocalJobStorage
from splicr.store import SqliteJobStore

from .domain import (
    Artifact,
    ArtifactKind,
    Project,
    RenderPlan,
    RenderSegment,
    Take,
    TakeStatus,
    VoiceProfile,
    VoiceProfileKind,
)
from .store import SqliteStudioStore


_SOURCE_SYSTEM = "splicr-job"
_NARRATOR_SOURCE_SYSTEM = "narrator-library"
_STATUS_MAP = {
    JobStatus.QUEUED: TakeStatus.QUEUED,
    JobStatus.RUNNING: TakeStatus.RENDERING,
    JobStatus.PAUSED: TakeStatus.PAUSED,
    JobStatus.COMPLETED: TakeStatus.COMPLETED,
    JobStatus.FAILED: TakeStatus.FAILED,
    JobStatus.CANCELLED: TakeStatus.CANCELLED,
}


@dataclass(frozen=True, slots=True)
class ImportedJob:
    source_job_id: str
    project_id: str
    render_plan_id: str | None
    take_id: str | None
    artifact_id: str | None


@dataclass(frozen=True, slots=True)
class NarratorProjectManifest:
    source_path: str
    label: str
    config: Mapping[str, JsonValue]
    status: str
    output_path: str | None
    updated_at: float


@dataclass(frozen=True, slots=True)
class NarratorVoiceManifest:
    metadata_path: Path
    asset_path: Path | None
    engine: str
    metadata: Mapping[str, JsonValue]


@dataclass(frozen=True, slots=True)
class NarratorSnapshot:
    data_directory: Path
    projects: tuple[NarratorProjectManifest, ...]
    voices: tuple[NarratorVoiceManifest, ...]
    settings: Mapping[str, JsonValue]
    podcast: Mapping[str, JsonValue]
    episodes: tuple[JsonValue, ...]
    pronunciations: JsonValue
    substitutions: JsonValue
    jobs: tuple[JsonValue, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ImportedNarratorProject:
    source_path: str
    project_id: str


@dataclass(frozen=True, slots=True)
class ImportedNarratorVoice:
    source_key: str
    profile_id: str


@dataclass(frozen=True, slots=True)
class ImportedNarratorCustomizations:
    pronunciations: int
    substitutions: int


def _stable_id(job_id: str, entity: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"splicr:{_SOURCE_SYSTEM}:{job_id}:{entity}"))


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        default=str,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _read_json(
    path: Path,
    default: JsonValue,
    warnings: list[str],
) -> JsonValue:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        warnings.append(f"Could not read {path.name}: {exc}")
        return default


def _mapping(value: JsonValue) -> Mapping[str, JsonValue]:
    return value if isinstance(value, dict) else {}


def _sequence(value: JsonValue) -> tuple[JsonValue, ...]:
    return tuple(value) if isinstance(value, list) else ()


def _timestamp(value: JsonValue) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return 0.0
    try:
        result = float(value)
    except ValueError:
        return 0.0
    return result if math.isfinite(result) else 0.0


def scan_narrator_data(data_directory: Path) -> NarratorSnapshot:
    """Read Narrator manifests without importing modules or mutating source data."""

    root = Path(data_directory).resolve()
    warnings: list[str] = []
    raw_projects = _read_json(root / "narrator_projects.json", [], warnings)
    projects: list[NarratorProjectManifest] = []
    for index, item in enumerate(_sequence(raw_projects)):
        if not isinstance(item, dict):
            warnings.append(f"Skipped invalid Narrator project record {index}")
            continue
        source_path = item.get("path")
        if not isinstance(source_path, str):
            warnings.append(f"Skipped invalid Narrator project record {index}")
            continue
        source_name = Path(source_path).stem or source_path
        projects.append(
            NarratorProjectManifest(
                source_path=source_path,
                label=str(item.get("label") or source_name),
                config=_mapping(item.get("cfg", {})),
                status=str(item.get("status") or "not_started"),
                output_path=(
                    str(item["output"])
                    if item.get("output") not in (None, "")
                    else None
                ),
                updated_at=_timestamp(item.get("updated", 0.0)),
            )
        )

    voices: list[NarratorVoiceManifest] = []
    voices_root = root / "voices"
    if voices_root.is_dir():
        for metadata_path in sorted(voices_root.rglob("*.json")):
            raw_metadata = _read_json(metadata_path, {}, warnings)
            metadata = _mapping(raw_metadata)
            if not metadata:
                continue
            if metadata_path.name == "voice.json":
                engine = str(metadata.get("engine") or "qwen3")
                candidate = metadata_path.with_name("reference.wav")
            else:
                engine = "kokoro" if metadata_path.parent.name == "kokoro" else "unknown"
                candidate = metadata_path.with_suffix(".pt")
            voices.append(
                NarratorVoiceManifest(
                    metadata_path=metadata_path,
                    asset_path=candidate if candidate.is_file() else None,
                    engine=engine,
                    metadata=metadata,
                )
            )

    return NarratorSnapshot(
        data_directory=root,
        projects=tuple(projects),
        voices=tuple(voices),
        settings=_mapping(_read_json(root / "narrator_settings.json", {}, warnings)),
        podcast=_mapping(_read_json(root / "narrator_podcast.json", {}, warnings)),
        episodes=_sequence(_read_json(root / "narrator_episodes.json", [], warnings)),
        pronunciations=_read_json(root / "narrator_pronunciations.json", {}, warnings),
        substitutions=_read_json(root / "narrator_substitutions.json", {}, warnings),
        jobs=_sequence(_read_json(root / "narrator_jobs.json", [], warnings)),
        warnings=tuple(warnings),
    )


def import_narrator_projects(
    snapshot: NarratorSnapshot,
    studio_store: SqliteStudioStore,
) -> list[ImportedNarratorProject]:
    """Import Narrator's library index while leaving documents and media in place."""

    imported: list[ImportedNarratorProject] = []
    for item in snapshot.projects:
        normalized_key = str(Path(item.source_path)).casefold()
        project_id = str(
            uuid5(
                NAMESPACE_URL,
                f"splicr:{_NARRATOR_SOURCE_SYSTEM}:{normalized_key}:project",
            )
        )
        timestamp = datetime.fromtimestamp(max(item.updated_at, 0.0), tz=UTC).isoformat()
        media_type = mimetypes.guess_type(item.source_path)[0] or "text/plain"
        metadata: dict[str, JsonValue] = {
            "legacy_source_system": _NARRATOR_SOURCE_SYSTEM,
            "legacy_source_path": item.source_path,
            "legacy_status": item.status,
            "legacy_render_config": dict(item.config),
            "legacy_data_directory": str(snapshot.data_directory),
        }
        if item.output_path is not None:
            metadata["legacy_output_path"] = item.output_path
        project = Project(
            id=project_id,
            name=item.label,
            source_name=Path(item.source_path).name,
            source_media_type=media_type,
            metadata=metadata,
            created_at=timestamp,
            updated_at=timestamp,
        )
        studio_store.save_project(project)
        studio_store.record_import(
            source_system=_NARRATOR_SOURCE_SYSTEM,
            source_key=normalized_key,
            entity_type="project",
            entity_id=project_id,
            fingerprint=_fingerprint(
                {
                    "path": item.source_path,
                    "label": item.label,
                    "config": item.config,
                    "status": item.status,
                    "output": item.output_path,
                    "updated": item.updated_at,
                }
            ),
        )
        imported.append(ImportedNarratorProject(item.source_path, project_id))
    return imported


def import_narrator_voices(
    snapshot: NarratorSnapshot,
    studio_store: SqliteStudioStore,
) -> list[ImportedNarratorVoice]:
    """Index legacy voice assets and presets without moving or rewriting them."""

    imported: list[ImportedNarratorVoice] = []
    for item in snapshot.voices:
        if item.asset_path is None:
            continue
        source_key = str(item.metadata_path.resolve()).casefold()
        profile_id = str(
            uuid5(NAMESPACE_URL, f"splicr:{_NARRATOR_SOURCE_SYSTEM}:{source_key}:voice")
        )
        raw_kind = str(item.metadata.get("kind") or "")
        if item.engine == "kokoro":
            kind = VoiceProfileKind.BLEND
        elif raw_kind == VoiceProfileKind.CLONED.value and item.metadata.get("reference_text"):
            kind = VoiceProfileKind.CLONED
        else:
            kind = VoiceProfileKind.DESIGNED
        description = str(item.metadata.get("description") or "")
        label = str(
            item.metadata.get("label")
            or description
            or item.metadata_path.parent.name
            or item.metadata_path.stem
        )
        reference_text = item.metadata.get("reference_text")
        timestamp = datetime.fromtimestamp(item.metadata_path.stat().st_mtime, tz=UTC).isoformat()
        profile = VoiceProfile(
            id=profile_id,
            label=label,
            engine_id=item.engine,
            kind=kind,
            description=description,
            reference_audio_path=(
                None if kind is VoiceProfileKind.BLEND else str(item.asset_path.resolve())
            ),
            reference_text=(str(reference_text) if reference_text else None),
            settings=(
                dict(item.metadata)
                if kind is VoiceProfileKind.BLEND
                else ({"design_take": int(item.metadata.get("take", 1) or 1)}
                      if kind is VoiceProfileKind.DESIGNED else {})
            ),
            metadata={
                "legacy_source_system": _NARRATOR_SOURCE_SYSTEM,
                "legacy_metadata_path": str(item.metadata_path.resolve()),
                "legacy_asset_path": str(item.asset_path.resolve()),
                "managed": False,
                "legacy_voice_metadata": dict(item.metadata),
            },
            created_at=timestamp,
            updated_at=timestamp,
        )
        studio_store.save_voice_profile(profile)
        studio_store.record_import(
            source_system=_NARRATOR_SOURCE_SYSTEM,
            source_key=source_key,
            entity_type="voice",
            entity_id=profile_id,
            fingerprint=_fingerprint(
                {
                    "metadata": item.metadata,
                    "asset_path": str(item.asset_path.resolve()),
                    "engine": item.engine,
                }
            ),
        )
        imported.append(ImportedNarratorVoice(source_key, profile_id))

    presets = snapshot.settings.get("custom_voice_presets")
    for index, raw_preset in enumerate(presets if isinstance(presets, list) else []):
        if not isinstance(raw_preset, dict):
            continue
        label = str(raw_preset.get("label") or "").strip()
        speaker = str(raw_preset.get("speaker") or "").strip()
        if not label or not speaker:
            continue
        source_key = f"custom-preset:{label.casefold()}:{speaker.casefold()}"
        profile_id = str(
            uuid5(NAMESPACE_URL, f"splicr:{_NARRATOR_SOURCE_SYSTEM}:{source_key}:voice")
        )
        created = _timestamp(raw_preset.get("created", 0.0))
        source_timestamp = (
            created
            or (snapshot.data_directory / "narrator_settings.json").stat().st_mtime
        )
        timestamp = datetime.fromtimestamp(source_timestamp, tz=UTC).isoformat()
        profile = VoiceProfile(
            id=profile_id,
            label=label,
            engine_id="qwen3",
            kind=VoiceProfileKind.PRESET,
            description=str(raw_preset.get("instruct") or ""),
            settings={
                "speaker": speaker,
                "instructions": str(raw_preset.get("instruct") or ""),
            },
            metadata={
                "legacy_source_system": _NARRATOR_SOURCE_SYSTEM,
                "legacy_preset_index": index,
                "managed": False,
            },
            created_at=timestamp,
            updated_at=timestamp,
        )
        studio_store.save_voice_profile(profile)
        studio_store.record_import(
            source_system=_NARRATOR_SOURCE_SYSTEM,
            source_key=source_key,
            entity_type="voice",
            entity_id=profile_id,
            fingerprint=_fingerprint(raw_preset),
        )
        imported.append(ImportedNarratorVoice(source_key, profile_id))
    return imported


def import_narrator_customizations(
    snapshot: NarratorSnapshot,
    customizations: TextCustomizationStore,
    *,
    overwrite: bool = False,
) -> ImportedNarratorCustomizations:
    """Copy portable language rules while leaving all Narrator media external."""

    return ImportedNarratorCustomizations(
        pronunciations=customizations.import_pronunciations(
            snapshot.pronunciations,
            overwrite=overwrite,
        ),
        substitutions=customizations.import_substitutions(
            snapshot.substitutions,
            overwrite=overwrite,
        ),
    )


def _controls(job: JobRecord) -> dict[str, JsonValue]:
    return {key: value.value for key, value in asdict(job.controls).items()}


def _plan_payload(
    job: JobRecord,
    chunks: Iterable[ChunkRecord],
    planning_manifest: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    payload = {
        "provider": job.provider,
        "model": job.model,
        "voice": job.voice,
        "instructions": job.instructions,
        "controls": _controls(job),
        "resource_revision": job.resource_revision,
        "variables": dict(job.variables),
        "chunks": [
            {
                "index": chunk.index,
                "text": chunk.text,
                "byte_count": chunk.byte_count,
                "word_count": chunk.word_count,
            }
            for chunk in chunks
        ],
    }
    if planning_manifest is not None:
        payload["chunk_planning"] = {
            key: planning_manifest.get(key)
            for key in ("schema_version", "strategy", "target_mode", "target_value")
        }
    return payload


def _render_segment_options(
    job: JobRecord,
    chunk_index: int,
) -> tuple[str, str | None, str | None, dict[str, JsonValue]]:
    base_variables = dict(job.variables)
    raw_options = base_variables.pop(SEGMENT_OPTIONS_VARIABLE, None)
    entry = (
        raw_options[chunk_index]
        if isinstance(raw_options, list)
        and chunk_index < len(raw_options)
        and isinstance(raw_options[chunk_index], Mapping)
        else None
    )
    if entry is None:
        settings: dict[str, JsonValue] = {
            "model": job.model,
            "controls": _controls(job),
            "variables": base_variables,
            "legacy_chunk_index": chunk_index,
        }
        if job.resource_revision is not None:
            settings["resource_revision"] = job.resource_revision
        return job.voice, job.instructions, None, settings

    model = str(entry.get("model") or job.model)
    voice = str(entry.get("voice") or job.voice)
    instructions_value = entry.get("instructions")
    instructions = instructions_value if isinstance(instructions_value, str) else None
    speaker_value = entry.get("speaker")
    speaker = speaker_value if isinstance(speaker_value, str) and speaker_value else None
    controls = entry.get("controls")
    variables = entry.get("variables")
    settings = {
        "model": model,
        "controls": dict(controls) if isinstance(controls, Mapping) else _controls(job),
        "variables": dict(variables) if isinstance(variables, Mapping) else base_variables,
        "legacy_chunk_index": chunk_index,
    }
    source_segment_index = entry.get("segment_index")
    if isinstance(source_segment_index, int):
        settings["source_segment_index"] = source_segment_index
    session_key = entry.get("session_key")
    if isinstance(session_key, str) and session_key:
        settings["session_key"] = session_key
    if job.resource_revision is not None:
        settings["resource_revision"] = job.resource_revision
    return voice, instructions, speaker, settings


def _source_and_spans(
    source_text: str,
    chunks: list[ChunkRecord],
) -> tuple[str, list[tuple[int, int]], str, str | None]:
    spans: list[tuple[int, int]] = []
    cursor = 0
    for chunk in chunks:
        start = source_text.find(chunk.text, cursor)
        if start < 0:
            break
        end = start + len(chunk.text)
        spans.append((start, end))
        cursor = end
    if len(spans) == len(chunks):
        return source_text, spans, "exact", None

    separator = "\n\n"
    canonical = separator.join(chunk.text for chunk in chunks)
    spans = []
    cursor = 0
    for chunk in chunks:
        end = cursor + len(chunk.text)
        spans.append((cursor, end))
        cursor = end + len(separator)
    return canonical, spans, "canonical_chunks", source_text


def import_splicr_job(
    *,
    job_id: str,
    job_store: SqliteJobStore,
    job_storage: LocalJobStorage,
    studio_store: SqliteStudioStore,
    project_name: str | None = None,
    source_name: str | None = None,
    source_media_type: str | None = None,
    take_label: str | None = None,
    target_project_id: str | None = None,
) -> ImportedJob:
    """Import or resynchronize one legacy SPLICR job without altering it."""

    job = job_store.get_job(job_id)
    chunks = job_store.chunks_for_job(job_id)
    try:
        stored_source = job_storage.read_source(job_id)
    except OSError:
        stored_source = "\n\n".join(chunk.text for chunk in chunks)

    source_text, spans, span_strategy, original_source = _source_and_spans(
        stored_source, chunks
    )
    project_record = studio_store.get_import_record(_SOURCE_SYSTEM, job.id, "project")
    project_id = (
        target_project_id
        or (project_record.entity_id if project_record is not None else None)
        or _stable_id(job.id, "project")
    )
    try:
        existing_project = studio_store.get_project(project_id)
    except KeyError:
        existing_project = None
    project_metadata: dict[str, JsonValue] = {
        **(dict(existing_project.metadata) if existing_project is not None else {}),
        "legacy_source_system": _SOURCE_SYSTEM,
        "legacy_job_id": job.id,
        "legacy_job_status": job.status.value,
        "legacy_source_span_strategy": span_strategy,
        "legacy_job_directory": str(job_storage.job_dir(job.id).resolve()),
    }
    if original_source is not None:
        project_metadata["legacy_original_source_text"] = original_source
    project = Project(
        id=project_id,
        name=(
            project_name
            or (existing_project.name if existing_project is not None else None)
            or f"SPLICR job {job.id}"
        ),
        source_text=source_text,
        source_name=(
            source_name
            or (existing_project.source_name if existing_project is not None else None)
            or job_storage.source_path(job.id).name
        ),
        source_media_type=(
            source_media_type
            or (
                existing_project.source_media_type
                if existing_project is not None
                else "text/plain"
            )
        ),
        metadata=project_metadata,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )
    project_fingerprint = _fingerprint(
        {
            "name": project.name,
            "source": source_text,
            "source_name": project.source_name,
            "source_media_type": project.source_media_type,
            "metadata": project_metadata,
            "updated_at": job.updated_at,
        }
    )
    if project_record is None or project_record.fingerprint != project_fingerprint:
        studio_store.save_project(project)
        studio_store.record_import(
            source_system=_SOURCE_SYSTEM,
            source_key=job.id,
            entity_type="project",
            entity_id=project_id,
            fingerprint=project_fingerprint,
        )

    if not chunks:
        return ImportedJob(job.id, project_id, None, None, None)

    try:
        planning_manifest = job_storage.read_plan(job.id)
    except (OSError, ValueError, json.JSONDecodeError):
        planning_manifest = None
    plan_payload = _plan_payload(job, chunks, planning_manifest)
    plan_fingerprint = _fingerprint(plan_payload)
    plan_record = studio_store.get_import_record(_SOURCE_SYSTEM, job.id, "render_plan")
    if plan_record is None:
        plan_id = _stable_id(job.id, f"render-plan:{plan_fingerprint}")
        segment_rows: list[RenderSegment] = []
        for ordinal, chunk in enumerate(chunks):
            voice, instructions, speaker, settings = _render_segment_options(
                job,
                chunk.index,
            )
            segment_rows.append(
                RenderSegment(
                    id=_stable_id(job.id, f"segment:{chunk.index}"),
                    ordinal=ordinal,
                    text=chunk.text,
                    source_start=spans[ordinal][0],
                    source_end=spans[ordinal][1],
                    engine_id=job.provider,
                    voice_id=voice,
                    speaker=speaker,
                    instructions=instructions,
                    settings=settings,
                )
            )
        segments = tuple(segment_rows)
        plan_metadata: dict[str, JsonValue] = {
            "legacy_job_id": job.id,
            "legacy_plan_fingerprint": plan_fingerprint,
        }
        if planning_manifest is not None:
            plan_metadata["chunk_planning"] = {
                key: planning_manifest.get(key)
                for key in (
                    "schema_version",
                    "strategy",
                    "target_mode",
                    "target_value",
                    "warnings",
                )
            }
        existing_revisions = studio_store.list_render_plans(project_id)
        revision = (
            max(existing.revision for existing in existing_revisions) + 1
            if existing_revisions
            else 1
        )
        plan = RenderPlan(
            id=plan_id,
            project_id=project_id,
            revision=revision,
            segments=segments,
            metadata=plan_metadata,
            created_at=job.created_at,
        )
        studio_store.create_render_plan(plan)
        studio_store.record_import(
            source_system=_SOURCE_SYSTEM,
            source_key=job.id,
            entity_type="render_plan",
            entity_id=plan_id,
            fingerprint=plan_fingerprint,
        )
    else:
        if plan_record.fingerprint != plan_fingerprint:
            raise ValueError(
                f"legacy SPLICR job {job.id} changed after its render plan was imported"
            )
        plan_id = plan_record.entity_id

    take_id = _stable_id(job.id, "take")
    take_record = studio_store.get_import_record(_SOURCE_SYSTEM, job.id, "take")
    take_fingerprint = _fingerprint(
        {"status": job.status.value, "updated_at": job.updated_at}
    )
    if take_record is None:
        studio_store.create_take(
            Take(
                id=take_id,
                project_id=project_id,
                render_plan_id=plan_id,
                label=take_label or "Legacy synthesis",
                status=_STATUS_MAP[job.status],
                created_at=job.created_at,
                updated_at=job.updated_at,
            )
        )
    else:
        take_id = take_record.entity_id
        if take_record.fingerprint != take_fingerprint:
            studio_store.update_take_status(
                take_id,
                _STATUS_MAP[job.status],
                updated_at=job.updated_at,
            )
    if take_record is None or take_record.fingerprint != take_fingerprint:
        studio_store.record_import(
            source_system=_SOURCE_SYSTEM,
            source_key=job.id,
            entity_type="take",
            entity_id=take_id,
            fingerprint=take_fingerprint,
        )

    artifact_id: str | None = None
    output_path = Path(job.output_path) if job.output_path else job_storage.output_path(job.id)
    if job.status is JobStatus.COMPLETED and output_path.is_file():
        artifact_record = studio_store.get_import_record(
            _SOURCE_SYSTEM, job.id, "audio_artifact"
        )
        artifact_fingerprint = _fingerprint(
            {
                "path": str(output_path.resolve()),
                "size_bytes": output_path.stat().st_size,
                "modified_ns": output_path.stat().st_mtime_ns,
            }
        )
        if artifact_record is None:
            artifact_id = _stable_id(job.id, "audio-artifact")
            studio_store.add_artifact(
                Artifact(
                    id=artifact_id,
                    project_id=project_id,
                    take_id=take_id,
                    kind=ArtifactKind.AUDIO,
                    path=str(output_path.resolve()),
                    media_type="audio/wav",
                    size_bytes=output_path.stat().st_size,
                    created_at=job.updated_at,
                )
            )
            studio_store.record_import(
                source_system=_SOURCE_SYSTEM,
                source_key=job.id,
                entity_type="audio_artifact",
                entity_id=artifact_id,
                fingerprint=artifact_fingerprint,
            )
        else:
            if artifact_record.fingerprint != artifact_fingerprint:
                raise ValueError(
                    f"legacy SPLICR output for job {job.id} changed after import"
                )
            artifact_id = artifact_record.entity_id

    return ImportedJob(job.id, project_id, plan_id, take_id, artifact_id)


def import_splicr_jobs(
    *,
    job_store: SqliteJobStore,
    job_storage: LocalJobStorage,
    studio_store: SqliteStudioStore,
    limit: int = 10_000,
) -> list[ImportedJob]:
    return [
        import_splicr_job(
            job_id=job.id,
            job_store=job_store,
            job_storage=job_storage,
            studio_store=studio_store,
        )
        for job in reversed(job_store.list_jobs(limit=limit))
    ]
