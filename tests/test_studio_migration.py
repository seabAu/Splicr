from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from splicr.domain import SEGMENT_OPTIONS_VARIABLE, DeliveryControls, JobStatus
from splicr.storage import LocalJobStorage
from splicr.store import SqliteJobStore
from splicr.studio import SqliteStudioStore, TakeStatus, import_splicr_job


def _legacy_job(tmp_path: Path) -> tuple[SqliteJobStore, LocalJobStorage, SqliteStudioStore]:
    database = tmp_path / "splicr.sqlite3"
    job_store = SqliteJobStore(database)
    job_store.initialize()
    storage = LocalJobStorage(tmp_path / "jobs")
    storage.initialize()
    studio_store = SqliteStudioStore(database)
    studio_store.initialize()
    job_store.create_job_with_chunks(
        job_id="legacy-job",
        provider="gemini",
        model="gemini-tts",
        voice="Kore",
        instructions="Read clearly.",
        controls=DeliveryControls(),
        resource_revision=3,
        variables={"temperature": 0.8},
        chunks=["First sentence.", "Second sentence."],
    )
    storage.write_source("legacy-job", "First sentence.\n\nSecond sentence.")
    return job_store, storage, studio_store


def test_import_splicr_job_builds_studio_hierarchy_idempotently(tmp_path) -> None:
    job_store, storage, studio_store = _legacy_job(tmp_path)

    first = import_splicr_job(
        job_id="legacy-job",
        job_store=job_store,
        job_storage=storage,
        studio_store=studio_store,
    )
    second = import_splicr_job(
        job_id="legacy-job",
        job_store=job_store,
        job_storage=storage,
        studio_store=studio_store,
    )

    assert first == second
    project = studio_store.get_project(first.project_id)
    plan = studio_store.get_render_plan(first.render_plan_id or "")
    take = studio_store.get_take(first.take_id or "")
    assert project.source_text == "First sentence.\n\nSecond sentence."
    assert plan.segments[1].source_start == 17
    assert plan.segments[0].settings["resource_revision"] == 3
    assert take.status is TakeStatus.QUEUED
    with sqlite3.connect(studio_store.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM studio_projects").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM studio_render_plans").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM studio_takes").fetchone()[0] == 1


def test_import_preserves_segment_voice_and_speaker_options(tmp_path) -> None:
    database = tmp_path / "splicr.sqlite3"
    job_store = SqliteJobStore(database)
    job_store.initialize()
    storage = LocalJobStorage(tmp_path / "jobs")
    storage.initialize()
    studio_store = SqliteStudioStore(database)
    studio_store.initialize()
    job_store.create_job_with_chunks(
        job_id="dialogue-job",
        provider="qwen3-local",
        model="qwen-model",
        voice="host-profile",
        instructions="Warm and curious.",
        controls=DeliveryControls(),
        resource_revision=4,
        variables={
            "shared": "kept",
            SEGMENT_OPTIONS_VARIABLE: [
                {
                    "model": "qwen-model",
                    "voice": "host-profile",
                    "instructions": "Warm and curious.",
                    "controls": {
                        "tone": "warm",
                        "pace": "normal",
                        "vocal_style": "conversational",
                        "nonverbal_frequency": "never",
                    },
                    "variables": {"temperature": 0.6},
                    "session_key": "host-session",
                    "segment_index": 0,
                    "speaker": "Person1",
                },
                {
                    "model": "qwen-model",
                    "voice": "guest-profile",
                    "instructions": "Measured and precise.",
                    "controls": {
                        "tone": "serious",
                        "pace": "slow",
                        "vocal_style": "narrative",
                        "nonverbal_frequency": "never",
                    },
                    "variables": {"temperature": 0.2},
                    "session_key": "guest-session",
                    "segment_index": 1,
                    "speaker": "Person2",
                },
            ],
        },
        chunks=["Welcome to the show.", "Thank you for having me."],
    )
    storage.write_source(
        "dialogue-job",
        "Welcome to the show.\n\nThank you for having me.",
    )

    imported = import_splicr_job(
        job_id="dialogue-job",
        job_store=job_store,
        job_storage=storage,
        studio_store=studio_store,
        take_label="Dialogue take",
    )

    plan = studio_store.get_render_plan(imported.render_plan_id or "")
    take = studio_store.get_take(imported.take_id or "")
    assert [segment.voice_id for segment in plan.segments] == [
        "host-profile",
        "guest-profile",
    ]
    assert [segment.speaker for segment in plan.segments] == ["Person1", "Person2"]
    assert plan.segments[0].instructions == "Warm and curious."
    assert plan.segments[1].settings["source_segment_index"] == 1
    assert plan.segments[1].settings["session_key"] == "guest-session"
    assert plan.segments[1].settings["variables"] == {"temperature": 0.2}
    assert SEGMENT_OPTIONS_VARIABLE not in plan.segments[0].settings["variables"]
    assert take.label == "Dialogue take"


def test_import_resynchronizes_take_and_adds_completed_output(tmp_path) -> None:
    job_store, storage, studio_store = _legacy_job(tmp_path)
    imported = import_splicr_job(
        job_id="legacy-job",
        job_store=job_store,
        job_storage=storage,
        studio_store=studio_store,
    )
    assert job_store.claim_job("legacy-job") is True
    output = storage.output_path("legacy-job")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"RIFFlegacy-wave")
    job_store.mark_job_completed("legacy-job", str(output.resolve()))

    completed = import_splicr_job(
        job_id="legacy-job",
        job_store=job_store,
        job_storage=storage,
        studio_store=studio_store,
    )

    assert completed.project_id == imported.project_id
    assert completed.artifact_id is not None
    assert studio_store.get_take(completed.take_id or "").status is TakeStatus.COMPLETED
    artifact = studio_store.get_artifact(completed.artifact_id)
    assert artifact.path == str(output.resolve())
    assert artifact.size_bytes == len(b"RIFFlegacy-wave")


def test_import_preserves_original_source_when_chunks_no_longer_match(tmp_path) -> None:
    job_store, storage, studio_store = _legacy_job(tmp_path)
    storage.write_source("legacy-job", "Original [1] source.")

    imported = import_splicr_job(
        job_id="legacy-job",
        job_store=job_store,
        job_storage=storage,
        studio_store=studio_store,
    )

    project = studio_store.get_project(imported.project_id)
    assert project.source_text == "First sentence.\n\nSecond sentence."
    assert project.metadata["legacy_original_source_text"] == "Original [1] source."
    assert project.metadata["legacy_source_span_strategy"] == "canonical_chunks"


def test_import_rejects_changed_immutable_plan(tmp_path) -> None:
    job_store, storage, studio_store = _legacy_job(tmp_path)
    import_splicr_job(
        job_id="legacy-job",
        job_store=job_store,
        job_storage=storage,
        studio_store=studio_store,
    )
    with sqlite3.connect(job_store.database_path) as connection:
        connection.execute(
            "UPDATE chunks SET text = 'Changed sentence.' WHERE chunk_index = 0"
        )

    with pytest.raises(ValueError, match="changed after its render plan was imported"):
        import_splicr_job(
            job_id="legacy-job",
            job_store=job_store,
            job_storage=storage,
            studio_store=studio_store,
        )


def test_empty_legacy_job_imports_project_without_invalid_plan(tmp_path) -> None:
    database = tmp_path / "splicr.sqlite3"
    job_store = SqliteJobStore(database)
    job_store.initialize()
    job_store.create_job(
        job_id="empty",
        provider="gemini",
        model="model",
        voice="voice",
        instructions=None,
    )
    storage = LocalJobStorage(tmp_path / "jobs")
    storage.initialize()
    studio_store = SqliteStudioStore(database)
    studio_store.initialize()

    imported = import_splicr_job(
        job_id="empty",
        job_store=job_store,
        job_storage=storage,
        studio_store=studio_store,
    )

    assert imported.render_plan_id is None
    assert studio_store.get_project(imported.project_id).source_text == ""
    assert job_store.get_job("empty").status is JobStatus.QUEUED
