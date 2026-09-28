from __future__ import annotations

import time

from fastapi.testclient import TestClient

from splicr.api import create_app
from splicr.config import Settings
from splicr.providers import ProviderRegistry
from splicr.service import SynthesisService
from splicr.studio import ArtifactKind, Project, TakeStatus

from .fakes import RecordingProvider


def _app(tmp_path):
    settings = Settings(data_dir=tmp_path, pacing_seconds=0)
    service = SynthesisService(
        settings=settings,
        providers=ProviderRegistry([RecordingProvider()]),
    )
    return create_app(settings=settings, service=service)


def test_studio_project_library_lists_summaries_and_loads_source(tmp_path) -> None:
    app = _app(tmp_path)
    app.state.studio_store.save_project(
        Project(
            id="project-1",
            name="Imported book",
            source_text="Chapter one.\n\nChapter two.",
            source_name="book.md",
            source_media_type="text/markdown",
            metadata={"legacy_source_system": "narrator-library"},
            created_at="2026-09-28T10:00:00+00:00",
            updated_at="2026-09-28T11:00:00+00:00",
        )
    )

    with TestClient(app) as client:
        listing = client.get("/v1/studio/projects")
        detail = client.get("/v1/studio/projects/project-1")
        missing = client.get("/v1/studio/projects/missing")

    assert listing.status_code == 200
    assert listing.json() == [
        {
            "id": "project-1",
            "name": "Imported book",
            "source_name": "book.md",
            "source_media_type": "text/markdown",
            "source_chars": 26,
            "source_preview": "Chapter one. Chapter two.",
            "metadata": {"legacy_source_system": "narrator-library"},
            "render_plan_count": 0,
            "take_count": 0,
            "created_at": "2026-09-28T10:00:00+00:00",
            "updated_at": "2026-09-28T11:00:00+00:00",
        }
    ]
    assert detail.status_code == 200
    assert detail.json()["source_text"] == "Chapter one.\n\nChapter two."
    assert missing.status_code == 404


def test_studio_project_api_does_not_duplicate_preserved_legacy_source_in_metadata(
    tmp_path,
) -> None:
    app = _app(tmp_path)
    app.state.studio_store.save_project(
        Project(
            id="project-2",
            name="Fallback source",
            source_text="Canonical rendered text.",
            metadata={
                "legacy_source_span_strategy": "canonical_chunks",
                "legacy_original_source_text": "Private original source.",
            },
        )
    )

    with TestClient(app) as client:
        listing = client.get("/v1/studio/projects").json()
        detail = client.get("/v1/studio/projects/project-2").json()

    assert "legacy_original_source_text" not in listing[0]["metadata"]
    assert "legacy_original_source_text" not in detail["metadata"]


def test_new_synthesis_job_is_live_synced_into_the_studio_library(tmp_path) -> None:
    app = _app(tmp_path)

    with TestClient(app) as client:
        created = client.post(
            "/v1/speech/jobs",
            json={
                "text": "Chapter one. This is the source manuscript.",
                "provider": "fake",
                "project_name": "A recognizable book",
                "source_name": "book.txt",
            },
        )
        assert created.status_code == 202
        job_id = created.json()["id"]

        projects = client.get("/v1/studio/projects").json()
        assert len(projects) == 1
        project = projects[0]
        assert project["name"] == "A recognizable book"
        assert project["source_name"] == "book.txt"
        assert project["source_media_type"] == "text/plain"
        assert project["render_plan_count"] == 1
        assert project["take_count"] == 1

        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            response = client.get(f"/v1/speech/jobs/{job_id}")
            if response.json()["status"] == "completed":
                break
            time.sleep(0.01)
        else:
            raise AssertionError("job did not complete")

        project_id = project["id"]
        detail = client.get(f"/v1/studio/projects/{project_id}").json()
        assert detail["source_text"] == "Chapter one. This is the source manuscript."

    takes = app.state.studio_store.list_takes(project_id)
    assert len(takes) == 1
    assert takes[0].label == "Narration take"
    assert takes[0].status is TakeStatus.COMPLETED
    artifacts = app.state.studio_store.list_artifacts(takes[0].id)
    assert len(artifacts) == 1
    assert artifacts[0].kind is ArtifactKind.AUDIO


def test_repeated_job_reads_do_not_rewrite_unchanged_studio_imports(tmp_path) -> None:
    app = _app(tmp_path)

    with TestClient(app) as client:
        created = client.post(
            "/v1/speech/jobs",
            json={"text": "Keep this import stable.", "provider": "fake"},
        ).json()
        job_id = created["id"]
        assert client.get("/v1/studio/projects").json()[0]["name"] == (
            "Keep this import stable."
        )
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            response = client.get(f"/v1/speech/jobs/{job_id}")
            if response.json()["status"] == "completed":
                break
            time.sleep(0.01)
        else:
            raise AssertionError("job did not complete")

        first_project = app.state.studio_store.get_import_record(
            "splicr-job", job_id, "project"
        )
        first_take = app.state.studio_store.get_import_record(
            "splicr-job", job_id, "take"
        )
        client.get(f"/v1/speech/jobs/{job_id}")
        second_project = app.state.studio_store.get_import_record(
            "splicr-job", job_id, "project"
        )
        second_take = app.state.studio_store.get_import_record(
            "splicr-job", job_id, "take"
        )

    assert first_project is not None
    assert first_take is not None
    assert second_project == first_project
    assert second_take == first_take
