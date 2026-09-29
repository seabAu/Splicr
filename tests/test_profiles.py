from __future__ import annotations

import sqlite3

import pytest

from splicr.domain import DeliveryControls, SpeechPace, TonePreset
from splicr.planning import ChunkTargetMode, SplitStrategy
from splicr.profiles import ProfileNotFoundError, StudioProfileStore


def _values() -> dict:
    return {
        "name": "Chapter narration",
        "resource_id": "custom-voice",
        "resource_revision": 3,
        "text": "# Chapter\n\nThe saved source.",
        "model": "voice-model",
        "voice": "narrator",
        "voice_profile_id": "voice-profile-123",
        "instructions": "Keep headings distinct.",
        "controls": DeliveryControls(tone=TonePreset.WARM, pace=SpeechPace.SLOW),
        "split_strategy": SplitStrategy.HEADING_1,
        "chunk_target_mode": ChunkTargetMode.CHARACTERS,
        "chunk_target_value": 1200,
        "remove_numeric_citations": True,
        "variables": {"seed": 42, "metadata": {"language": "en"}},
        "job_id": "job-123",
    }


def test_profile_round_trip_update_and_delete(tmp_path) -> None:
    store = StudioProfileStore(tmp_path / "splicr.sqlite3")
    store.initialize()

    created = store.create(**_values())

    assert created.resource_revision == 3
    assert created.voice_profile_id == "voice-profile-123"
    assert created.text.startswith("# Chapter")
    assert created.controls.tone is TonePreset.WARM
    assert created.chunk_target_mode is ChunkTargetMode.CHARACTERS
    assert created.chunk_target_value == 1200
    assert created.variables["metadata"] == {"language": "en"}
    assert store.list() == [created]

    values = _values()
    values.update(
        name="Revised profile",
        job_id=None,
        resource_revision=4,
        voice_profile_id="voice-profile-456",
    )
    updated = store.update(created.id, **values)

    assert updated.id == created.id
    assert updated.name == "Revised profile"
    assert updated.resource_revision == 4
    assert updated.job_id is None
    assert updated.voice_profile_id == "voice-profile-456"
    assert updated.updated_at >= created.updated_at

    store.delete(created.id)
    with pytest.raises(ProfileNotFoundError):
        store.get(created.id)


def test_profile_store_survives_reinitialization(tmp_path) -> None:
    database_path = tmp_path / "splicr.sqlite3"
    first = StudioProfileStore(database_path)
    first.initialize()
    created = first.create(**_values())

    second = StudioProfileStore(database_path)
    second.initialize()

    assert second.get(created.id) == created


def test_profile_variables_must_be_finite_json(tmp_path) -> None:
    store = StudioProfileStore(tmp_path / "splicr.sqlite3")
    store.initialize()
    values = _values()
    values["variables"] = {"bad": float("nan")}

    with pytest.raises(ValueError):
        store.create(**values)


def test_profile_store_adds_voice_profile_column_to_existing_database(tmp_path) -> None:
    database_path = tmp_path / "splicr.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE studio_profiles (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                resource_id TEXT NOT NULL,
                resource_revision INTEGER,
                text TEXT NOT NULL,
                model TEXT,
                voice TEXT,
                instructions TEXT,
                controls_json TEXT NOT NULL,
                split_strategy TEXT NOT NULL,
                remove_numeric_citations INTEGER NOT NULL DEFAULT 0,
                variables_json TEXT NOT NULL DEFAULT '{}',
                job_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

    store = StudioProfileStore(database_path)
    store.initialize()
    created = store.create(**_values())

    assert created.voice_profile_id == "voice-profile-123"
    assert created.chunk_target_mode is ChunkTargetMode.CHARACTERS
