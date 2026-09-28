from __future__ import annotations

import sqlite3
from dataclasses import replace

import pytest

from splicr.studio import (
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


def _project(*, updated_at: str = "2026-09-28T10:00:00+00:00") -> Project:
    return Project(
        id="project-1",
        name="A Book",
        source_text="First sentence.\n\nSecond sentence.",
        source_name="book.md",
        source_media_type="text/markdown",
        metadata={"language": "en", "nested": {"chapters": 2}},
        created_at="2026-09-28T09:00:00+00:00",
        updated_at=updated_at,
    )


def _plan(*, identifier: str = "plan-1", revision: int = 1) -> RenderPlan:
    return RenderPlan(
        id=identifier,
        project_id="project-1",
        revision=revision,
        segments=(
            RenderSegment(
                id="segment-1",
                ordinal=0,
                text="First sentence.",
                source_start=0,
                source_end=15,
                engine_id="kokoro",
                voice_id="af_heart",
                instructions="Read warmly.",
                settings={"speed": 0.9},
            ),
            RenderSegment(
                id="segment-2",
                ordinal=1,
                text="Second sentence.",
                source_start=17,
                source_end=33,
                engine_id="kokoro",
                voice_id="af_heart",
            ),
        ),
        metadata={"split": "paragraph"},
        created_at="2026-09-28T09:01:00+00:00",
    )


def _take() -> Take:
    return Take(
        id="take-1",
        project_id="project-1",
        render_plan_id="plan-1",
        label="First take",
        status=TakeStatus.QUEUED,
        created_at="2026-09-28T09:02:00+00:00",
        updated_at="2026-09-28T09:02:00+00:00",
    )


def test_studio_entities_round_trip_and_survive_reinitialize(tmp_path) -> None:
    database = tmp_path / "splicr.sqlite3"
    store = SqliteStudioStore(database)
    store.initialize()
    store.save_project(_project())
    store.create_render_plan(_plan())
    store.create_take(_take())
    artifact = Artifact(
        id="artifact-1",
        project_id="project-1",
        take_id="take-1",
        kind=ArtifactKind.AUDIO,
        path="output/book.wav",
        media_type="audio/wav",
        size_bytes=1_024,
        sha256="a" * 64,
        created_at="2026-09-28T09:03:00+00:00",
    )
    store.add_artifact(artifact)

    restarted = SqliteStudioStore(database)
    restarted.initialize()

    assert restarted.get_project("project-1") == _project()
    assert restarted.get_render_plan("plan-1") == _plan()
    assert restarted.get_take("take-1").artifact_ids == ("artifact-1",)
    assert restarted.list_artifacts("take-1") == [artifact]


def test_project_upsert_preserves_creation_timestamp(tmp_path) -> None:
    store = SqliteStudioStore(tmp_path / "splicr.sqlite3")
    store.initialize()
    store.save_project(_project())
    changed = Project(
        id="project-1",
        name="Renamed Book",
        created_at="2099-01-01T00:00:00+00:00",
        updated_at="2026-09-28T11:00:00+00:00",
    )

    saved = store.save_project(changed)

    assert saved.name == "Renamed Book"
    assert saved.created_at == _project().created_at
    assert saved.updated_at == changed.updated_at


def test_render_plans_are_immutable_and_revisions_are_unique(tmp_path) -> None:
    store = SqliteStudioStore(tmp_path / "splicr.sqlite3")
    store.initialize()
    store.save_project(_project())
    store.create_render_plan(_plan())

    with pytest.raises(sqlite3.IntegrityError):
        store.create_render_plan(_plan())
    with pytest.raises(sqlite3.IntegrityError):
        store.create_render_plan(_plan(identifier="different-id"))

    assert store.get_render_plan("plan-1") == _plan()


def test_cross_project_take_and_artifact_references_are_rejected(tmp_path) -> None:
    store = SqliteStudioStore(tmp_path / "splicr.sqlite3")
    store.initialize()
    store.save_project(_project())
    store.save_project(Project(id="project-2", name="Other"))
    store.create_render_plan(_plan())

    with pytest.raises(sqlite3.IntegrityError):
        store.create_take(
            Take(
                id="bad-take",
                project_id="project-2",
                render_plan_id="plan-1",
                label="Wrong project",
            )
        )

    store.create_take(_take())
    with pytest.raises(sqlite3.IntegrityError):
        store.add_artifact(
            Artifact(
                id="bad-artifact",
                project_id="project-2",
                take_id="take-1",
                kind=ArtifactKind.AUDIO,
                path="wrong.wav",
                media_type="audio/wav",
                size_bytes=44,
            )
        )


def test_take_status_and_artifacts_are_derived_from_current_rows(tmp_path) -> None:
    store = SqliteStudioStore(tmp_path / "splicr.sqlite3")
    store.initialize()
    store.save_project(_project())
    store.create_render_plan(_plan())
    store.create_take(_take())

    changed = store.update_take_status(
        "take-1",
        TakeStatus.RENDERING,
        updated_at="2026-09-28T09:04:00+00:00",
    )

    assert changed.status is TakeStatus.RENDERING
    assert changed.updated_at == "2026-09-28T09:04:00+00:00"
    assert changed.artifact_ids == ()


def test_import_records_are_idempotent_and_track_fingerprint_changes(tmp_path) -> None:
    store = SqliteStudioStore(tmp_path / "splicr.sqlite3")
    store.initialize()

    first = store.record_import(
        source_system="splicr-job",
        source_key="job-1",
        entity_type="project",
        entity_id="project-1",
        fingerprint="old",
        imported_at="2026-09-28T09:00:00+00:00",
    )
    second = store.record_import(
        source_system="splicr-job",
        source_key="job-1",
        entity_type="project",
        entity_id="project-1",
        fingerprint="new",
        imported_at="2026-09-28T10:00:00+00:00",
    )

    assert first.fingerprint == "old"
    assert second.fingerprint == "new"
    assert second.imported_at == "2026-09-28T10:00:00+00:00"
    with sqlite3.connect(store.database_path) as connection:
        count = connection.execute("SELECT COUNT(*) FROM studio_imports").fetchone()[0]
    assert count == 1


def test_voice_profiles_round_trip_filter_update_and_delete(tmp_path) -> None:
    store = SqliteStudioStore(tmp_path / "splicr.sqlite3")
    store.initialize()
    profile = VoiceProfile(
        id="voice-1",
        label="Warm narrator",
        engine_id="qwen3",
        kind=VoiceProfileKind.CLONED,
        description="Measured and warm",
        reference_audio_path="voices/voice-1/reference.wav",
        reference_text="The exact spoken words.",
        settings={"temperature": 0.7},
        metadata={"managed": True},
        created_at="2026-09-28T09:00:00+00:00",
        updated_at="2026-09-28T09:00:00+00:00",
    )

    assert store.save_voice_profile(profile) == profile
    assert store.list_voice_profiles("qwen3") == [profile]
    assert store.list_voice_profiles("audio8") == []

    changed = replace(
        profile,
        label="Renamed narrator",
        updated_at="2026-09-28T10:00:00+00:00",
    )
    assert store.save_voice_profile(changed).label == "Renamed narrator"
    assert store.save_voice_profile(changed).created_at == profile.created_at
    assert store.delete_voice_profile("voice-1").label == "Renamed narrator"
    with pytest.raises(KeyError):
        store.get_voice_profile("voice-1")
