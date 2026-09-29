from __future__ import annotations

import time
import io
import wave

from fastapi.testclient import TestClient

from splicr.api import create_app
from splicr.config import Settings
from splicr.domain import ControlDefinition, ControlValueType
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


def _wav_bytes(seconds: float = 2.1, sample_rate: int = 8_000) -> bytes:
    stream = io.BytesIO()
    with wave.open(stream, "wb") as recording:
        recording.setnchannels(1)
        recording.setsampwidth(2)
        recording.setframerate(sample_rate)
        recording.writeframes(b"\0\0" * int(seconds * sample_rate))
    return stream.getvalue()


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


def test_advanced_values_survive_api_plan_chunks_and_resume(tmp_path) -> None:
    provider = RecordingProvider(
        fail_text="Fail here.",
        control_definitions=(
            ControlDefinition(
                key="speed",
                value_type=ControlValueType.NUMBER,
                default=1.0,
                minimum=0.5,
                maximum=2.0,
            ),
        ),
        allows_undeclared_variables=False,
    )
    settings = Settings(
        data_dir=tmp_path,
        pacing_seconds=0,
        max_attempts=2,
        chunk_max_words=2,
        backoff_base_seconds=0,
        backoff_max_seconds=0,
        backoff_jitter_seconds=0,
    )
    service = SynthesisService(
        settings=settings,
        providers=ProviderRegistry([provider]),
    )
    app = create_app(settings=settings, service=service)

    with TestClient(app) as client:
        response = client.post(
            "/v1/speech/jobs",
            json={
                "text": "First bit. Fail here.",
                "provider": "fake",
                "variables": {"speed": 1.37},
            },
        )
        assert response.status_code == 202
        job_id = response.json()["id"]

        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            paused = client.get(f"/v1/speech/jobs/{job_id}").json()
            if paused["status"] == "paused":
                break
            time.sleep(0.01)
        else:
            raise AssertionError("job did not pause after the provider failure")

        project = client.get("/v1/studio/projects").json()[0]
        plan = app.state.studio_store.list_render_plans(project["id"])[0]
        assert all(
            segment.settings["variables"] == {"speed": 1.37}
            for segment in plan.segments
        )
        chunks = service.store.chunks_for_job(job_id)
        assert chunks[0].status.value == "completed"
        assert chunks[1].status.value == "failed"

        provider.fail_text = None
        resumed = client.post(f"/v1/speech/jobs/{job_id}/resume")
        assert resumed.status_code == 202
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            finished = client.get(f"/v1/speech/jobs/{job_id}").json()
            if finished["status"] == "completed":
                break
            time.sleep(0.01)
        else:
            raise AssertionError("resumed job did not complete")

    assert provider.calls == ["First bit.", "Fail here.", "Fail here."]
    assert all(options.variables == {"speed": 1.37} for options in provider.options)
    assert service.get_job(job_id).variables == {"speed": 1.37}


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


def test_voice_studio_manages_reference_voices_and_presets(tmp_path) -> None:
    app = _app(tmp_path)

    with TestClient(app) as client:
        created = client.post(
            "/v1/studio/voices/reference",
            data={
                "label": "My voice",
                "engine_id": "qwen3",
                "reference_text": "These are the exact spoken words.",
                "description": "Warm and direct",
                "kind": "cloned",
            },
            files={"file": ("recording.wav", _wav_bytes(), "audio/wav")},
        )
        assert created.status_code == 201
        voice = created.json()
        assert voice["kind"] == "cloned"
        assert voice["has_reference"] is True
        assert "reference_audio_path" not in voice

        reference = client.get(voice["reference_url"])
        assert reference.status_code == 200
        assert reference.content.startswith(b"RIFF")

        renamed = client.put(
            f"/v1/studio/voices/{voice['id']}",
            json={"label": "Renamed voice", "description": "Quietly confident"},
        )
        assert renamed.status_code == 200
        assert renamed.json()["label"] == "Renamed voice"

        preset = client.post(
            "/v1/studio/voices/presets",
            json={
                "label": "Announcer",
                "engine_id": "qwen3",
                "voice_id": "Ryan",
                "instructions": "Bright and concise",
            },
        )
        assert preset.status_code == 201
        assert preset.json()["settings"]["voice_id"] == "Ryan"

        listing = client.get("/v1/studio/voices?engine_id=qwen3")
        assert listing.status_code == 200
        assert {item["label"] for item in listing.json()} == {
            "Renamed voice",
            "Announcer",
        }

        deleted = client.delete(f"/v1/studio/voices/{voice['id']}")
        assert deleted.status_code == 204
        assert client.get(voice["reference_url"]).status_code == 404
        assert not (tmp_path / "studio" / "voices" / voice["id"]).exists()


def test_voice_studio_rejects_short_or_untranscribed_clone(tmp_path) -> None:
    app = _app(tmp_path)

    with TestClient(app) as client:
        missing_transcript = client.post(
            "/v1/studio/voices/reference",
            data={"label": "No transcript", "engine_id": "qwen3", "kind": "cloned"},
            files={"file": ("recording.wav", _wav_bytes(), "audio/wav")},
        )
        too_short = client.post(
            "/v1/studio/voices/reference",
            data={
                "label": "Too short",
                "engine_id": "audio8",
                "kind": "cloned",
                "reference_text": "Short sample.",
            },
            files={"file": ("recording.wav", _wav_bytes(1.0), "audio/wav")},
        )

    assert missing_transcript.status_code == 422
    assert "exact words" in missing_transcript.json()["detail"]
    assert too_short.status_code == 422
    assert "at least 3s" in too_short.json()["detail"]
