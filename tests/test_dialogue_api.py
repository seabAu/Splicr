from __future__ import annotations

import time

from fastapi.testclient import TestClient

from splicr.api import create_app
from splicr.config import Settings
from splicr.domain import SEGMENT_OPTIONS_VARIABLE
from splicr.providers import ProviderRegistry
from splicr.service import SynthesisService
from splicr.studio import SqliteStudioStore
from tests.fakes import RecordingProvider


def _dialogue_payload() -> dict[str, object]:
    return {
        "provider": "fake",
        "project_name": "Two-voice interview",
        "turns": [
            {"speaker": "Person1", "text": "Welcome to the studio."},
            {"speaker": "Person2", "text": "Thank you for inviting me."},
            {"speaker": "Person1", "text": "Let us begin."},
        ],
        "person1": {
            "voice": "host-voice",
            "variables": {"temperature": 0.4},
        },
        "person2": {
            "voice": "guest-voice",
            "variables": {"temperature": 0.2},
        },
    }


def test_dialogue_preview_and_job_preserve_turn_voice_assignments(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        chunk_max_bytes=10_000,
        chunk_max_words=100,
        pacing_seconds=0,
        backoff_base_seconds=0,
        backoff_max_seconds=0,
        backoff_jitter_seconds=0,
    )
    provider = RecordingProvider()
    service = SynthesisService(
        settings=settings,
        providers=ProviderRegistry([provider]),
    )

    with TestClient(create_app(settings=settings, service=service)) as client:
        preview = client.post("/v1/studio/dialogue/preview", json=_dialogue_payload())
        assert preview.status_code == 200
        assert preview.json()["total_turns"] == 3
        assert preview.json()["total_chunks"] == 3
        assert [turn["speaker"] for turn in preview.json()["turns"]] == [
            "Person1",
            "Person2",
            "Person1",
        ]

        created = client.post("/v1/studio/dialogue/jobs", json=_dialogue_payload())
        assert created.status_code == 202
        assert SEGMENT_OPTIONS_VARIABLE not in created.json()["variables"]
        job_id = created.json()["id"]

        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            current = client.get(f"/v1/speech/jobs/{job_id}")
            if current.json()["status"] == "completed":
                break
            time.sleep(0.01)
        else:
            raise AssertionError("dialogue job did not complete")

    assert provider.calls == [
        "Welcome to the studio.",
        "Let us begin.",
        "Thank you for inviting me.",
    ]
    assert [options.voice for options in provider.options] == [
        "host-voice",
        "host-voice",
        "guest-voice",
    ]
    job = service.store.get_job(job_id)
    stored_options = job.variables[SEGMENT_OPTIONS_VARIABLE]
    assert [entry["speaker"] for entry in stored_options] == [
        "Person1",
        "Person2",
        "Person1",
    ]

    studio = SqliteStudioStore(settings.database_path)
    studio.initialize()
    projects = studio.list_projects()
    assert len(projects) == 1
    project = studio.get_project(projects[0].id)
    assert project.name == "Two-voice interview"
    plan = studio.list_render_plans(project.id)[0]
    assert [segment.voice_id for segment in plan.segments] == [
        "host-voice",
        "guest-voice",
        "host-voice",
    ]
    assert [segment.speaker for segment in plan.segments] == [
        "Person1",
        "Person2",
        "Person1",
    ]
    assert studio.list_takes(project.id)[0].label == "Dialogue take"


def test_dialogue_rejects_reserved_variables_and_blank_turns(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path)
    service = SynthesisService(
        settings=settings,
        providers=ProviderRegistry([RecordingProvider()]),
    )
    reserved = _dialogue_payload()
    reserved["person1"] = {
        "voice": "host-voice",
        "variables": {SEGMENT_OPTIONS_VARIABLE: []},
    }
    blank = _dialogue_payload()
    blank["turns"] = [{"speaker": "Person1", "text": "   "}]

    with TestClient(create_app(settings=settings, service=service)) as client:
        reserved_response = client.post(
            "/v1/studio/dialogue/preview",
            json=reserved,
        )
        blank_response = client.post("/v1/studio/dialogue/jobs", json=blank)

    assert reserved_response.status_code == 422
    assert "managed by SPLICR" in reserved_response.json()["detail"]
    assert blank_response.status_code == 422
