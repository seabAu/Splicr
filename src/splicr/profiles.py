from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .domain import (
    DeliveryControls,
    NonverbalFrequency,
    SpeechPace,
    TonePreset,
    VocalStyle,
    utc_now,
)
from .planning import SplitStrategy


JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]


class ProfileNotFoundError(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class StudioProfile:
    id: str
    name: str
    resource_id: str
    resource_revision: int | None
    text: str
    model: str | None
    voice: str | None
    instructions: str | None
    controls: DeliveryControls
    split_strategy: SplitStrategy
    remove_numeric_citations: bool
    variables: dict[str, JsonValue]
    job_id: str | None
    created_at: str
    updated_at: str
    voice_profile_id: str | None = None


def _encode_controls(controls: DeliveryControls) -> str:
    return json.dumps(
        {
            "tone": controls.tone.value,
            "pace": controls.pace.value,
            "vocal_style": controls.vocal_style.value,
            "nonverbal_frequency": controls.nonverbal_frequency.value,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _decode_controls(raw: str) -> DeliveryControls:
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("profile controls must be an object")
        return DeliveryControls(
            tone=TonePreset(str(payload.get("tone", TonePreset.NEUTRAL.value))),
            pace=SpeechPace(str(payload.get("pace", SpeechPace.NORMAL.value))),
            vocal_style=VocalStyle(str(payload.get("vocal_style", VocalStyle.NATURAL.value))),
            nonverbal_frequency=NonverbalFrequency(
                str(
                    payload.get(
                        "nonverbal_frequency",
                        NonverbalFrequency.NEVER.value,
                    )
                )
            ),
        )
    except (json.JSONDecodeError, TypeError, ValueError):
        return DeliveryControls()


def _normalize_variables(variables: Mapping[str, Any]) -> dict[str, JsonValue]:
    encoded = json.dumps(
        dict(variables),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    decoded = json.loads(encoded)
    if not isinstance(decoded, dict):
        raise ValueError("profile variables must be a JSON object")
    return decoded


class StudioProfileStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self._lock = threading.RLock()

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS studio_profiles (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    resource_revision INTEGER,
                    text TEXT NOT NULL,
                    model TEXT,
                    voice TEXT,
                    voice_profile_id TEXT,
                    instructions TEXT,
                    controls_json TEXT NOT NULL,
                    split_strategy TEXT NOT NULL,
                    remove_numeric_citations INTEGER NOT NULL DEFAULT 0,
                    variables_json TEXT NOT NULL DEFAULT '{}',
                    job_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS studio_profiles_updated_idx
                    ON studio_profiles(updated_at DESC);
                """
            )
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(studio_profiles)")
            }
            if "voice_profile_id" not in columns:
                connection.execute(
                    "ALTER TABLE studio_profiles ADD COLUMN voice_profile_id TEXT"
                )

    def create(
        self,
        *,
        name: str,
        resource_id: str,
        resource_revision: int | None,
        text: str,
        model: str | None,
        voice: str | None,
        voice_profile_id: str | None = None,
        instructions: str | None,
        controls: DeliveryControls,
        split_strategy: SplitStrategy,
        remove_numeric_citations: bool,
        variables: Mapping[str, Any],
        job_id: str | None,
    ) -> StudioProfile:
        profile_id = uuid.uuid4().hex
        now = utc_now()
        normalized_variables = _normalize_variables(variables)
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO studio_profiles (
                    id, name, resource_id, resource_revision, text, model, voice,
                    voice_profile_id,
                    instructions, controls_json, split_strategy,
                    remove_numeric_citations, variables_json, job_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile_id,
                    name.strip(),
                    resource_id.strip().lower(),
                    resource_revision,
                    text,
                    model,
                    voice,
                    voice_profile_id,
                    instructions,
                    _encode_controls(controls),
                    split_strategy.value,
                    int(remove_numeric_citations),
                    json.dumps(
                        normalized_variables,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                    job_id,
                    now,
                    now,
                ),
            )
        return self.get(profile_id)

    def update(
        self,
        profile_id: str,
        *,
        name: str,
        resource_id: str,
        resource_revision: int | None,
        text: str,
        model: str | None,
        voice: str | None,
        voice_profile_id: str | None = None,
        instructions: str | None,
        controls: DeliveryControls,
        split_strategy: SplitStrategy,
        remove_numeric_citations: bool,
        variables: Mapping[str, Any],
        job_id: str | None,
    ) -> StudioProfile:
        normalized_variables = _normalize_variables(variables)
        now = utc_now()
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE studio_profiles
                SET name = ?, resource_id = ?, resource_revision = ?, text = ?,
                    model = ?, voice = ?, voice_profile_id = ?, instructions = ?, controls_json = ?,
                    split_strategy = ?, remove_numeric_citations = ?, variables_json = ?,
                    job_id = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    name.strip(),
                    resource_id.strip().lower(),
                    resource_revision,
                    text,
                    model,
                    voice,
                    voice_profile_id,
                    instructions,
                    _encode_controls(controls),
                    split_strategy.value,
                    int(remove_numeric_citations),
                    json.dumps(
                        normalized_variables,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                    job_id,
                    now,
                    profile_id,
                ),
            )
        if cursor.rowcount != 1:
            raise ProfileNotFoundError(profile_id)
        return self.get(profile_id)

    def get(self, profile_id: str) -> StudioProfile:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM studio_profiles WHERE id = ?",
                (profile_id,),
            ).fetchone()
        if row is None:
            raise ProfileNotFoundError(profile_id)
        return self._from_row(row)

    def list(self, limit: int = 100) -> list[StudioProfile]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM studio_profiles ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def delete(self, profile_id: str) -> None:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM studio_profiles WHERE id = ?",
                (profile_id,),
            )
        if cursor.rowcount != 1:
            raise ProfileNotFoundError(profile_id)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    @staticmethod
    def _from_row(row: sqlite3.Row) -> StudioProfile:
        try:
            decoded_variables = json.loads(row["variables_json"])
        except (json.JSONDecodeError, TypeError):
            decoded_variables = {}
        if not isinstance(decoded_variables, dict):
            decoded_variables = {}
        try:
            split_strategy = SplitStrategy(row["split_strategy"])
        except ValueError:
            split_strategy = SplitStrategy.SEMANTIC
        return StudioProfile(
            id=row["id"],
            name=row["name"],
            resource_id=row["resource_id"],
            resource_revision=row["resource_revision"],
            text=row["text"],
            model=row["model"],
            voice=row["voice"],
            voice_profile_id=row["voice_profile_id"],
            instructions=row["instructions"],
            controls=_decode_controls(row["controls_json"]),
            split_strategy=split_strategy,
            remove_numeric_citations=bool(row["remove_numeric_citations"]),
            variables=decoded_variables,
            job_id=row["job_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
