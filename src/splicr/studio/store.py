from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from splicr.domain import JsonValue, utc_now

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


def _encode_mapping(value: Mapping[str, JsonValue]) -> str:
    return json.dumps(
        dict(value),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _decode_mapping(value: str) -> Mapping[str, JsonValue]:
    decoded = json.loads(value)
    if not isinstance(decoded, dict):
        raise ValueError("stored JSON value must be an object")
    return decoded


@dataclass(frozen=True, slots=True)
class ImportRecord:
    source_system: str
    source_key: str
    entity_type: str
    entity_id: str
    fingerprint: str
    imported_at: str


class SqliteStudioStore:
    """Durable Studio entities stored additively beside the legacy job tables."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path)
        self._lock = threading.RLock()

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;

                CREATE TABLE IF NOT EXISTS studio_projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    source_text TEXT NOT NULL DEFAULT '',
                    source_name TEXT,
                    source_media_type TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS studio_render_plans (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES studio_projects(id) ON DELETE CASCADE,
                    revision INTEGER NOT NULL CHECK (revision >= 1),
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    UNIQUE (project_id, revision),
                    UNIQUE (id, project_id)
                );

                CREATE TABLE IF NOT EXISTS studio_render_segments (
                    render_plan_id TEXT NOT NULL
                        REFERENCES studio_render_plans(id) ON DELETE CASCADE,
                    id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
                    text TEXT NOT NULL,
                    source_start INTEGER NOT NULL CHECK (source_start >= 0),
                    source_end INTEGER NOT NULL CHECK (source_end > source_start),
                    engine_id TEXT NOT NULL,
                    voice_id TEXT NOT NULL,
                    speaker TEXT,
                    instructions TEXT,
                    settings_json TEXT NOT NULL DEFAULT '{}',
                    PRIMARY KEY (render_plan_id, ordinal),
                    UNIQUE (render_plan_id, id)
                );

                CREATE TABLE IF NOT EXISTS studio_takes (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES studio_projects(id) ON DELETE CASCADE,
                    render_plan_id TEXT NOT NULL,
                    label TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (id, project_id),
                    FOREIGN KEY (render_plan_id, project_id)
                        REFERENCES studio_render_plans(id, project_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS studio_artifacts (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES studio_projects(id) ON DELETE CASCADE,
                    take_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    path TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
                    sha256 TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (take_id, project_id)
                        REFERENCES studio_takes(id, project_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS studio_imports (
                    source_system TEXT NOT NULL,
                    source_key TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    imported_at TEXT NOT NULL,
                    PRIMARY KEY (source_system, source_key, entity_type)
                );

                CREATE TABLE IF NOT EXISTS studio_voice_profiles (
                    id TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    engine_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    reference_audio_path TEXT,
                    reference_text TEXT,
                    settings_json TEXT NOT NULL DEFAULT '{}',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS studio_projects_updated_idx
                    ON studio_projects(updated_at DESC, id);
                CREATE INDEX IF NOT EXISTS studio_render_plans_project_idx
                    ON studio_render_plans(project_id, revision DESC);
                CREATE INDEX IF NOT EXISTS studio_takes_project_idx
                    ON studio_takes(project_id, created_at DESC, id);
                CREATE INDEX IF NOT EXISTS studio_artifacts_take_idx
                    ON studio_artifacts(take_id, created_at, id);
                CREATE INDEX IF NOT EXISTS studio_voice_profiles_engine_idx
                    ON studio_voice_profiles(engine_id, updated_at DESC, id);
                """
            )
            artifact_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(studio_artifacts)")
            }
            if "metadata_json" not in artifact_columns:
                connection.execute(
                    "ALTER TABLE studio_artifacts "
                    "ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'"
                )

    def save_project(self, project: Project) -> Project:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO studio_projects (
                    id, name, source_text, source_name, source_media_type,
                    metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    source_text = excluded.source_text,
                    source_name = excluded.source_name,
                    source_media_type = excluded.source_media_type,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    project.id,
                    project.name,
                    project.source_text,
                    project.source_name,
                    project.source_media_type,
                    _encode_mapping(project.metadata),
                    project.created_at,
                    project.updated_at,
                ),
            )
        return self.get_project(project.id)

    def get_project(self, project_id: str) -> Project:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM studio_projects WHERE id = ?", (project_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"studio project not found: {project_id}")
        return self._project_from_row(row)

    def list_projects(self) -> list[Project]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM studio_projects ORDER BY updated_at DESC, id"
            ).fetchall()
        return [self._project_from_row(row) for row in rows]

    def create_render_plan(self, plan: RenderPlan) -> RenderPlan:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO studio_render_plans (
                    id, project_id, revision, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    plan.id,
                    plan.project_id,
                    plan.revision,
                    _encode_mapping(plan.metadata),
                    plan.created_at,
                ),
            )
            connection.executemany(
                """
                INSERT INTO studio_render_segments (
                    render_plan_id, id, ordinal, text, source_start, source_end,
                    engine_id, voice_id, speaker, instructions, settings_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        plan.id,
                        segment.id,
                        segment.ordinal,
                        segment.text,
                        segment.source_start,
                        segment.source_end,
                        segment.engine_id,
                        segment.voice_id,
                        segment.speaker,
                        segment.instructions,
                        _encode_mapping(segment.settings),
                    )
                    for segment in plan.segments
                ],
            )
        return self.get_render_plan(plan.id)

    def get_render_plan(self, render_plan_id: str) -> RenderPlan:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM studio_render_plans WHERE id = ?", (render_plan_id,)
            ).fetchone()
            segment_rows = connection.execute(
                """
                SELECT * FROM studio_render_segments
                WHERE render_plan_id = ? ORDER BY ordinal
                """,
                (render_plan_id,),
            ).fetchall()
        if row is None:
            raise KeyError(f"render plan not found: {render_plan_id}")
        return self._render_plan_from_rows(row, segment_rows)

    def list_render_plans(self, project_id: str) -> list[RenderPlan]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM studio_render_plans
                WHERE project_id = ? ORDER BY revision DESC
                """,
                (project_id,),
            ).fetchall()
            return [self._render_plan_with_connection(connection, row) for row in rows]

    def create_take(self, take: Take) -> Take:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO studio_takes (
                    id, project_id, render_plan_id, label, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    take.id,
                    take.project_id,
                    take.render_plan_id,
                    take.label,
                    take.status.value,
                    take.created_at,
                    take.updated_at,
                ),
            )
        return self.get_take(take.id)

    def update_take_status(
        self,
        take_id: str,
        status: TakeStatus,
        *,
        updated_at: str | None = None,
    ) -> Take:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "UPDATE studio_takes SET status = ?, updated_at = ? WHERE id = ?",
                (status.value, updated_at or utc_now(), take_id),
            )
        if cursor.rowcount != 1:
            raise KeyError(f"take not found: {take_id}")
        return self.get_take(take_id)

    def get_take(self, take_id: str) -> Take:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM studio_takes WHERE id = ?", (take_id,)
            ).fetchone()
            artifact_rows = connection.execute(
                """
                SELECT id FROM studio_artifacts
                WHERE take_id = ? ORDER BY created_at, id
                """,
                (take_id,),
            ).fetchall()
        if row is None:
            raise KeyError(f"take not found: {take_id}")
        return self._take_from_row(row, tuple(item["id"] for item in artifact_rows))

    def list_takes(self, project_id: str) -> list[Take]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM studio_takes
                WHERE project_id = ? ORDER BY created_at DESC, id
                """,
                (project_id,),
            ).fetchall()
            return [self._take_with_connection(connection, row) for row in rows]

    def add_artifact(self, artifact: Artifact) -> Artifact:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO studio_artifacts (
                    id, project_id, take_id, kind, path, media_type,
                    size_bytes, sha256, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact.id,
                    artifact.project_id,
                    artifact.take_id,
                    artifact.kind.value,
                    artifact.path,
                    artifact.media_type,
                    artifact.size_bytes,
                    artifact.sha256,
                    _encode_mapping(artifact.metadata),
                    artifact.created_at,
                ),
            )
        return self.get_artifact(artifact.id)

    def get_artifact(self, artifact_id: str) -> Artifact:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM studio_artifacts WHERE id = ?", (artifact_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"artifact not found: {artifact_id}")
        return self._artifact_from_row(row)

    def list_artifacts(self, take_id: str) -> list[Artifact]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM studio_artifacts
                WHERE take_id = ? ORDER BY created_at, id
                """,
                (take_id,),
            ).fetchall()
        return [self._artifact_from_row(row) for row in rows]

    def save_voice_profile(self, profile: VoiceProfile) -> VoiceProfile:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO studio_voice_profiles (
                    id, label, engine_id, kind, description, reference_audio_path,
                    reference_text, settings_json, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    label = excluded.label,
                    engine_id = excluded.engine_id,
                    kind = excluded.kind,
                    description = excluded.description,
                    reference_audio_path = excluded.reference_audio_path,
                    reference_text = excluded.reference_text,
                    settings_json = excluded.settings_json,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    profile.id,
                    profile.label,
                    profile.engine_id,
                    profile.kind.value,
                    profile.description,
                    profile.reference_audio_path,
                    profile.reference_text,
                    _encode_mapping(profile.settings),
                    _encode_mapping(profile.metadata),
                    profile.created_at,
                    profile.updated_at,
                ),
            )
        return self.get_voice_profile(profile.id)

    def get_voice_profile(self, profile_id: str) -> VoiceProfile:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM studio_voice_profiles WHERE id = ?", (profile_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"voice profile not found: {profile_id}")
        return self._voice_profile_from_row(row)

    def list_voice_profiles(self, engine_id: str | None = None) -> list[VoiceProfile]:
        with self._lock, self._connect() as connection:
            if engine_id is None:
                rows = connection.execute(
                    "SELECT * FROM studio_voice_profiles ORDER BY updated_at DESC, id"
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM studio_voice_profiles
                    WHERE engine_id = ? ORDER BY updated_at DESC, id
                    """,
                    (engine_id,),
                ).fetchall()
        return [self._voice_profile_from_row(row) for row in rows]

    def delete_voice_profile(self, profile_id: str) -> VoiceProfile:
        profile = self.get_voice_profile(profile_id)
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM studio_voice_profiles WHERE id = ?", (profile_id,))
        return profile

    def get_import_record(
        self, source_system: str, source_key: str, entity_type: str
    ) -> ImportRecord | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM studio_imports
                WHERE source_system = ? AND source_key = ? AND entity_type = ?
                """,
                (source_system, source_key, entity_type),
            ).fetchone()
        return None if row is None else self._import_from_row(row)

    def record_import(
        self,
        *,
        source_system: str,
        source_key: str,
        entity_type: str,
        entity_id: str,
        fingerprint: str,
        imported_at: str | None = None,
    ) -> ImportRecord:
        timestamp = imported_at or utc_now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO studio_imports (
                    source_system, source_key, entity_type,
                    entity_id, fingerprint, imported_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_system, source_key, entity_type) DO UPDATE SET
                    entity_id = excluded.entity_id,
                    fingerprint = excluded.fingerprint,
                    imported_at = excluded.imported_at
                """,
                (
                    source_system,
                    source_key,
                    entity_type,
                    entity_id,
                    fingerprint,
                    timestamp,
                ),
            )
        record = self.get_import_record(source_system, source_key, entity_type)
        assert record is not None
        return record

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _project_from_row(row: sqlite3.Row) -> Project:
        return Project(
            id=row["id"],
            name=row["name"],
            source_text=row["source_text"],
            source_name=row["source_name"],
            source_media_type=row["source_media_type"],
            metadata=_decode_mapping(row["metadata_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _render_plan_from_rows(
        row: sqlite3.Row, segment_rows: list[sqlite3.Row]
    ) -> RenderPlan:
        segments = tuple(
            RenderSegment(
                id=item["id"],
                ordinal=item["ordinal"],
                text=item["text"],
                source_start=item["source_start"],
                source_end=item["source_end"],
                engine_id=item["engine_id"],
                voice_id=item["voice_id"],
                speaker=item["speaker"],
                instructions=item["instructions"],
                settings=_decode_mapping(item["settings_json"]),
            )
            for item in segment_rows
        )
        return RenderPlan(
            id=row["id"],
            project_id=row["project_id"],
            revision=row["revision"],
            segments=segments,
            metadata=_decode_mapping(row["metadata_json"]),
            created_at=row["created_at"],
        )

    def _render_plan_with_connection(
        self, connection: sqlite3.Connection, row: sqlite3.Row
    ) -> RenderPlan:
        segment_rows = connection.execute(
            """
            SELECT * FROM studio_render_segments
            WHERE render_plan_id = ? ORDER BY ordinal
            """,
            (row["id"],),
        ).fetchall()
        return self._render_plan_from_rows(row, segment_rows)

    @staticmethod
    def _take_from_row(row: sqlite3.Row, artifact_ids: tuple[str, ...]) -> Take:
        return Take(
            id=row["id"],
            project_id=row["project_id"],
            render_plan_id=row["render_plan_id"],
            label=row["label"],
            status=TakeStatus(row["status"]),
            artifact_ids=artifact_ids,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _take_with_connection(
        self, connection: sqlite3.Connection, row: sqlite3.Row
    ) -> Take:
        artifact_rows = connection.execute(
            """
            SELECT id FROM studio_artifacts
            WHERE take_id = ? ORDER BY created_at, id
            """,
            (row["id"],),
        ).fetchall()
        return self._take_from_row(row, tuple(item["id"] for item in artifact_rows))

    @staticmethod
    def _artifact_from_row(row: sqlite3.Row) -> Artifact:
        return Artifact(
            id=row["id"],
            project_id=row["project_id"],
            take_id=row["take_id"],
            kind=ArtifactKind(row["kind"]),
            path=row["path"],
            media_type=row["media_type"],
            size_bytes=row["size_bytes"],
            sha256=row["sha256"],
            metadata=_decode_mapping(row["metadata_json"]),
            created_at=row["created_at"],
        )

    @staticmethod
    def _voice_profile_from_row(row: sqlite3.Row) -> VoiceProfile:
        return VoiceProfile(
            id=row["id"],
            label=row["label"],
            engine_id=row["engine_id"],
            kind=VoiceProfileKind(row["kind"]),
            description=row["description"],
            reference_audio_path=row["reference_audio_path"],
            reference_text=row["reference_text"],
            settings=_decode_mapping(row["settings_json"]),
            metadata=_decode_mapping(row["metadata_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _import_from_row(row: sqlite3.Row) -> ImportRecord:
        return ImportRecord(
            source_system=row["source_system"],
            source_key=row["source_key"],
            entity_type=row["entity_type"],
            entity_id=row["entity_id"],
            fingerprint=row["fingerprint"],
            imported_at=row["imported_at"],
        )
