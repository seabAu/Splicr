from __future__ import annotations

import io
import json
import struct
import time
import zipfile

from fastapi.testclient import TestClient

from splicr.api import create_app
from splicr.config import Settings
from splicr.providers import ProviderRegistry
from splicr.service import SynthesisService
from tests.fakes import RecordingProvider


def test_job_lifecycle_and_audio_download(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        chunk_max_bytes=10_000,
        chunk_max_words=100,
        pacing_seconds=0,
        backoff_base_seconds=0,
        backoff_max_seconds=0,
        backoff_jitter_seconds=0,
    )
    service = SynthesisService(settings=settings, providers=ProviderRegistry([RecordingProvider()]))

    with TestClient(create_app(settings=settings, service=service)) as client:
        response = client.post(
            "/v1/speech/jobs",
            json={
                "text": "Hello from the API.",
                "provider": "fake",
                "export_name": "My: Résumé?",
            },
        )
        assert response.status_code == 202
        job_id = response.json()["id"]

        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            status_response = client.get(f"/v1/speech/jobs/{job_id}")
            if status_response.json()["status"] == "completed":
                break
            time.sleep(0.01)
        else:
            raise AssertionError("job did not complete")

        body = status_response.json()
        assert body["progress"] == 1.0
        assert body["audio_url"] == f"/v1/speech/jobs/{job_id}/audio"
        assert body["export_stem"] == "My- Résumé-"
        assert body["download_filename"] == "My- Résumé-.wav"
        assert body["checkpoint_export_url"].endswith("/checkpoints")
        audio = client.get(body["audio_url"])
        assert audio.status_code == 200
        assert audio.headers["content-type"] == "audio/wav"
        assert "My-%20R%C3%A9sum%C3%A9-.wav" in audio.headers["content-disposition"]
        assert audio.content.startswith(b"RIFF")

        checkpoints = client.get(body["checkpoint_export_url"])
        assert checkpoints.status_code == 200
        assert checkpoints.headers["content-type"] == "application/zip"
        assert checkpoints.headers["x-splicr-partial"] == "false"
        with zipfile.ZipFile(io.BytesIO(checkpoints.content)) as archive:
            manifest_name = "My- Résumé--checkpoints.json"
            manifest = json.loads(archive.read(manifest_name))
            assert manifest["job_id"] == job_id
            assert manifest["partial"] is False
            assert manifest["is_finished_master"] is False


def test_unknown_provider_and_blank_text_are_validation_errors(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path)
    service = SynthesisService(settings=settings, providers=ProviderRegistry([RecordingProvider()]))

    with TestClient(create_app(settings=settings, service=service)) as client:
        unknown = client.post("/v1/speech/jobs", json={"text": "Hello", "provider": "missing"})
        blank = client.post("/v1/speech/jobs", json={"text": "   ", "provider": "fake"})

    assert unknown.status_code == 422
    assert blank.status_code == 422


def test_timeline_routes_preview_and_revise_a_completed_take(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        chunk_max_bytes=10_000,
        chunk_max_words=2,
        pacing_seconds=0,
        backoff_base_seconds=0,
        backoff_max_seconds=0,
        backoff_jitter_seconds=0,
    )
    provider = RecordingProvider()
    service = SynthesisService(settings=settings, providers=ProviderRegistry([provider]))

    with TestClient(create_app(settings=settings, service=service)) as client:
        created = client.post(
            "/v1/speech/jobs",
            json={
                "text": "one two\n\nthree four\n\nfive six",
                "provider": "fake",
            },
        )
        assert created.status_code == 202
        job_id = created.json()["id"]

        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            current = client.get(f"/v1/speech/jobs/{job_id}").json()
            if current["status"] == "completed":
                break
            time.sleep(0.01)
        else:
            raise AssertionError("job did not complete")

        takes = client.get("/v1/studio/timeline/takes")
        assert takes.status_code == 200
        assert [take["id"] for take in takes.json()] == [job_id]

        timeline = client.get(
            f"/v1/studio/timeline/jobs/{job_id}?waveform_buckets=8"
        )
        assert timeline.status_code == 200
        body = timeline.json()
        assert [segment["text"] for segment in body["segments"]] == [
            "one two",
            "three four",
            "five six",
        ]
        assert body["waveform"]
        span = client.get(
            f"/v1/studio/timeline/jobs/{job_id}/span",
            params={
                "start": body["segments"][0]["start"],
                "end": body["segments"][1]["end"],
            },
        )
        assert span.status_code == 200
        assert span.headers["content-type"] == "audio/wav"
        assert span.content.startswith(b"RIFF")

        revised = client.post(
            f"/v1/studio/timeline/jobs/{job_id}/segments/1/revise",
            json={"text": "changed words"},
        )
        assert revised.status_code == 202
        revised_id = revised.json()["id"]
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            current = client.get(f"/v1/speech/jobs/{revised_id}").json()
            if current["status"] == "completed":
                break
            time.sleep(0.01)
        else:
            raise AssertionError("revised job did not complete")

        revised_timeline = client.get(f"/v1/studio/timeline/jobs/{revised_id}")
        assert revised_timeline.status_code == 200
        assert [segment["text"] for segment in revised_timeline.json()["segments"]] == [
            "one two",
            "changed words",
            "five six",
        ]
        assert len(provider.calls) == 4


def test_timeline_sentence_revision_route_uses_reliable_timing(tmp_path) -> None:
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
    service = SynthesisService(settings=settings, providers=ProviderRegistry([provider]))

    with TestClient(create_app(settings=settings, service=service)) as client:
        created = client.post(
            "/v1/speech/jobs",
            json={"text": "First sentence. Second sentence.", "provider": "fake"},
        )
        job_id = created.json()["id"]
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if client.get(f"/v1/speech/jobs/{job_id}").json()["status"] == "completed":
                break
            time.sleep(0.01)
        else:
            raise AssertionError("job did not complete")

        samples = [1000] * 1000 + [2000] * 1000
        checkpoint = service.storage.chunk_path(job_id, 0)
        checkpoint.write_bytes(struct.pack(f"<{len(samples)}h", *samples))
        service.store.mark_chunk_completed(
            job_id,
            0,
            str(checkpoint.resolve()),
            {
                "timings": [
                    {
                        "type": "SentenceBoundary",
                        "start_seconds": 0,
                        "duration_seconds": 1000 / 24_000,
                        "text": "First sentence.",
                    },
                    {
                        "type": "SentenceBoundary",
                        "start_seconds": 1000 / 24_000,
                        "duration_seconds": 1000 / 24_000,
                        "text": "Second sentence.",
                    },
                ]
            },
        )

        timeline = client.get(f"/v1/studio/timeline/jobs/{job_id}").json()
        assert timeline["segments"][0]["sentence_revision_available"] is True
        assert [item["text"] for item in timeline["segments"][0]["sentences"]] == [
            "First sentence.",
            "Second sentence.",
        ]

        revised = client.post(
            f"/v1/studio/timeline/jobs/{job_id}/segments/0/sentences/0/revise",
            json={"text": "Changed sentence.", "crossfade_ms": 20},
        )
        assert revised.status_code == 202
        revised_id = revised.json()["id"]
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            current = client.get(f"/v1/speech/jobs/{revised_id}").json()
            if current["status"] == "completed":
                break
            time.sleep(0.01)
        else:
            raise AssertionError("sentence revision did not complete")

        revised_timeline = client.get(f"/v1/studio/timeline/jobs/{revised_id}").json()
        assert revised_timeline["segments"][0]["text"] == (
            "Changed sentence. Second sentence."
        )
        assert provider.calls[-1] == "Changed sentence."
