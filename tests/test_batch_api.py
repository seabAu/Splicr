from __future__ import annotations

import time

from fastapi.testclient import TestClient

from splicr.api import create_app
from splicr.config import Settings
from splicr.providers import ProviderRegistry
from splicr.service import SynthesisService
from splicr.studio import Project

from .fakes import RecordingProvider


def _app(tmp_path):
    settings = Settings(
        data_dir=tmp_path,
        pacing_seconds=0,
        backoff_base_seconds=0,
        backoff_max_seconds=0,
        backoff_jitter_seconds=0,
    )
    provider = RecordingProvider()
    service = SynthesisService(settings=settings, providers=ProviderRegistry([provider]))
    app = create_app(settings=settings, service=service)
    return app, provider


def _profile(client: TestClient) -> str:
    response = client.post(
        "/v1/profiles",
        json={
            "name": "Book narration",
            "resource_id": "fake",
            "text": "Profile placeholder.",
            "model": "fake-model",
            "voice": "fake-voice",
            "controls": {
                "tone": "neutral",
                "pace": "normal",
                "vocal_style": "natural",
                "nonverbal_frequency": "never",
            },
            "split_strategy": "semantic",
            "chunk_target_mode": "automatic",
            "remove_numeric_citations": True,
            "variables": {"seed": 23},
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def _terminal(client: TestClient, queue_id: str) -> dict:
    for _ in range(300):
        response = client.get(f"/v1/studio/batches/{queue_id}")
        assert response.status_code == 200
        queue = response.json()
        if queue["status"] in {"completed", "cancelled"}:
            return queue
        time.sleep(0.01)
    raise AssertionError("batch queue did not finish")


def test_batch_api_freezes_library_projects_and_creates_separate_takes(tmp_path) -> None:
    app, provider = _app(tmp_path)
    for index, text in enumerate(("First [12] chapter.", "Second chapter."), start=1):
        app.state.studio_store.save_project(
            Project(
                id=f"project-{index}",
                name=f"Chapter {index}",
                source_text=text,
                source_name=f"chapter-{index}.md",
                source_media_type="text/markdown",
            )
        )

    with TestClient(app) as client:
        profile_id = _profile(client)
        created = client.post(
            "/v1/studio/batches",
            json={
                "name": "Two chapters",
                "items": [
                    {"project_id": "project-1", "profile_id": profile_id},
                    {"project_id": "project-2", "profile_id": profile_id},
                ],
            },
        )
        assert created.status_code == 201
        queue = _terminal(client, created.json()["id"])

    assert queue["counts"]["completed"] == 2
    assert queue["progress"] == 1.0
    assert [item["project_id"] for item in queue["items"]] == ["project-1", "project-2"]
    assert all(item["job_id"] and item["take_id"] for item in queue["items"])
    assert provider.calls == ["First chapter.", "Second chapter."]
    assert len(app.state.studio_store.list_takes("project-1")) == 1
    assert len(app.state.studio_store.list_takes("project-2")) == 1


def test_batch_api_keeps_missing_inputs_as_visible_skipped_items(tmp_path) -> None:
    app, _ = _app(tmp_path)
    with TestClient(app) as client:
        profile_id = _profile(client)
        created = client.post(
            "/v1/studio/batches",
            json={
                "name": "Missing source",
                "items": [{"project_id": "deleted-project", "profile_id": profile_id}],
            },
        )

    assert created.status_code == 201
    queue = created.json()
    assert queue["status"] == "completed"
    assert queue["counts"]["skipped"] == 1
    assert queue["items"][0]["error_code"] == "missing_source"
