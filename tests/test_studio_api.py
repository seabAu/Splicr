from __future__ import annotations

from fastapi.testclient import TestClient

from splicr.api import create_app
from splicr.config import Settings
from splicr.providers import ProviderRegistry
from splicr.service import SynthesisService
from splicr.studio import Project

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
