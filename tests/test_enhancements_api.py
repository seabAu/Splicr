from __future__ import annotations

import asyncio
import threading
import time

from fastapi.testclient import TestClient

from splicr.api import create_app
from splicr.config import Settings
from splicr.providers import ProviderRegistry
from splicr.service import SynthesisService

from .fakes import RecordingProvider


def _settings(tmp_path, **overrides) -> Settings:
    values = {
        "data_dir": tmp_path,
        "chunk_max_bytes": 10_000,
        "chunk_max_words": 2,
        "pacing_seconds": 0,
        "backoff_base_seconds": 0,
        "backoff_max_seconds": 0,
        "backoff_jitter_seconds": 0,
    }
    values.update(overrides)
    return Settings(**values)


def _wait_for_status(client: TestClient, job_id: str, expected: str) -> dict:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        body = client.get(f"/v1/speech/jobs/{job_id}").json()
        if body["status"] == expected:
            return body
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} did not reach {expected}")


def test_import_and_heading_preview_preserve_document_structure(tmp_path) -> None:
    settings = _settings(tmp_path, chunk_max_words=100)
    service = SynthesisService(settings=settings, providers=ProviderRegistry([RecordingProvider()]))

    with TestClient(create_app(settings=settings, service=service)) as client:
        imported = client.post(
            "/v1/documents/import",
            files={"file": ("chapters.md", b"# Book\n\n## One\nAlpha.\n\n## Two\nBeta.")},
        )
        assert imported.status_code == 200
        document = imported.json()
        assert document["format"] == "markdown"
        assert document["metadata"]["heading_count"] == 3

        preview = client.post(
            "/v1/speech/preview",
            json={"text": document["text"], "provider": "fake", "split_strategy": "h2"},
        )
        assert preview.status_code == 200
        chunks = preview.json()["chunks"]
        assert len(chunks) == 3
        assert [chunk["boundary"] for chunk in chunks] == ["h2", "h2", "h2"]
        assert all(chunk["end_char"] > chunk["start_char"] for chunk in chunks)


def test_preview_exposes_target_metrics_warnings_and_exact_job_manifest(tmp_path) -> None:
    settings = _settings(tmp_path, chunk_max_words=100)
    service = SynthesisService(settings=settings, providers=ProviderRegistry([RecordingProvider()]))
    payload = {
        "text": "First line.\nSecond line.",
        "provider": "fake",
        "split_strategy": "newline",
        "chunk_target_mode": "parts",
        "chunk_target_value": 1,
    }

    with TestClient(create_app(settings=settings, service=service)) as client:
        preview_response = client.post("/v1/speech/preview", json=payload)
        assert preview_response.status_code == 200
        preview = preview_response.json()
        assert preview["target_mode"] == "parts"
        assert preview["target_value"] == 1
        assert preview["warnings"]
        assert preview["chunks"][0]["character_count"] > 0
        assert preview["chunks"][0]["limit_headroom"]["bytes"] >= 0

        submitted_response = client.post("/v1/speech/jobs", json=payload)
        assert submitted_response.status_code == 202
        job = submitted_response.json()
        manifest = service.storage.read_plan(job["id"])
        assert manifest["target_mode"] == "parts"
        assert [chunk["text"] for chunk in manifest["chunks"]] == [
            chunk["text"] for chunk in preview["chunks"]
        ]

        invalid = client.post(
            "/v1/speech/preview",
            json={
                "text": "Too many tiny pieces.",
                "provider": "fake",
                "chunk_target_mode": "parts",
                "chunk_target_value": 10_001,
            },
        )
        assert invalid.status_code == 422
        assert "at most 10000" in invalid.text


def test_numeric_citation_cleanup_matches_preview_and_submitted_chunks(tmp_path) -> None:
    provider = RecordingProvider()
    settings = _settings(tmp_path, chunk_max_words=100)
    service = SynthesisService(settings=settings, providers=ProviderRegistry([provider]))
    payload = {
        "text": "Fact [123].\n\nNext [ 7 ].",
        "provider": "fake",
        "remove_numeric_citations": True,
    }

    with TestClient(create_app(settings=settings, service=service)) as client:
        preview_response = client.post("/v1/speech/preview", json=payload)
        assert preview_response.status_code == 200
        preview = preview_response.json()
        assert preview["text"] == "Fact.\n\nNext."
        expected_chunks = [chunk["text"] for chunk in preview["chunks"]]
        assert all("[" not in chunk for chunk in expected_chunks)

        submitted_response = client.post("/v1/speech/jobs", json=payload)
        assert submitted_response.status_code == 202
        submitted = submitted_response.json()
        _wait_for_status(client, submitted["id"], "completed")
        assert provider.calls == expected_chunks

        citation_only = client.post(
            "/v1/speech/preview",
            json={"text": "[1] [2]", "provider": "fake", "remove_numeric_citations": True},
        )
        assert citation_only.status_code == 422
        assert citation_only.json()["detail"] == (
            "text contains no speakable content after preprocessing"
        )


def test_long_single_newline_document_previews_and_submits_without_mapping_error(
    tmp_path,
) -> None:
    provider = RecordingProvider()
    settings = _settings(tmp_path, chunk_max_words=350)
    service = SynthesisService(settings=settings, providers=ProviderRegistry([provider]))
    payload = {
        "text": ("A sentence with several ordinary words.\n" * 200).strip(),
        "provider": "fake",
    }

    with TestClient(create_app(settings=settings, service=service)) as client:
        preview_response = client.post("/v1/speech/preview", json=payload)
        assert preview_response.status_code == 200
        preview_chunks = [chunk["text"] for chunk in preview_response.json()["chunks"]]
        assert len(preview_chunks) > 1

        submitted_response = client.post("/v1/speech/jobs", json=payload)
        assert submitted_response.status_code == 202
        submitted = submitted_response.json()
        _wait_for_status(client, submitted["id"], "completed")
        assert provider.calls == preview_chunks


def test_error_pauses_job_and_exposes_resumable_partial_audio(tmp_path) -> None:
    provider = RecordingProvider(fail_text="bad")
    settings = _settings(tmp_path)
    service = SynthesisService(settings=settings, providers=ProviderRegistry([provider]))

    with TestClient(create_app(settings=settings, service=service)) as client:
        submitted = client.post(
            "/v1/speech/jobs",
            json={"text": "good words\n\nbad words", "provider": "fake"},
        ).json()
        paused = _wait_for_status(client, submitted["id"], "paused")

        assert paused["completed_chunks"] == 1
        assert paused["error_code"] == "provider_request_rejected"
        assert paused["error_detail"] == "bad request"
        assert paused["current_char"] > 0
        assert paused["partial_audio_url"].endswith("/partial-audio")
        assert paused["checkpoint_export_url"].endswith("/checkpoints")
        partial = client.get(paused["partial_audio_url"])
        assert partial.status_code == 200
        assert partial.content.startswith(b"RIFF")
        assert partial.headers["x-splicr-partial"] == "true"
        checkpoints = client.get(paused["checkpoint_export_url"])
        assert checkpoints.status_code == 200
        assert checkpoints.headers["x-splicr-partial"] == "true"
        assert checkpoints.headers["x-splicr-exported-chunks"] == "1"

        provider.fail_text = None
        resumed = client.post(f"/v1/speech/jobs/{submitted['id']}/resume")
        assert resumed.status_code == 202
        completed = _wait_for_status(client, submitted["id"], "completed")
        assert completed["audio_url"].endswith("/audio")
        assert provider.call_counts["good words"] == 1


def test_running_job_exposes_checkpoint_progress_without_http_caching(tmp_path) -> None:
    class GatedProvider(RecordingProvider):
        def __init__(self) -> None:
            super().__init__()
            self.second_request_started = threading.Event()
            self.release_second_request = threading.Event()

        async def synthesize(self, text, options):
            if self.calls:
                self.second_request_started.set()
                while not self.release_second_request.is_set():
                    await asyncio.sleep(0.01)
            return await super().synthesize(text, options)

    provider = GatedProvider()
    settings = _settings(tmp_path)
    service = SynthesisService(
        settings=settings,
        providers=ProviderRegistry([provider]),
    )

    with TestClient(create_app(settings=settings, service=service)) as client:
        submitted = client.post(
            "/v1/speech/jobs",
            json={"text": "first chunk\n\nsecond chunk", "provider": "fake"},
        ).json()
        assert provider.second_request_started.wait(timeout=2)

        running = client.get(f"/v1/speech/jobs/{submitted['id']}")

        assert running.status_code == 200
        assert running.headers["cache-control"] == "no-store"
        detail = running.json()
        assert detail["status"] == "running"
        assert detail["completed_chunks"] == 1
        assert detail["total_chunks"] == 2
        assert detail["progress"] == 0.5
        assert detail["current_chunk_index"] == 1
        assert 0 < detail["current_char"] < detail["total_chars"]

        recent = client.get("/v1/speech/jobs")
        assert recent.headers["cache-control"] == "no-store"
        assert recent.json()[0]["completed_chunks"] == 1

        provider.release_second_request.set()
        completed = _wait_for_status(client, submitted["id"], "completed")
        assert completed["completed_chunks"] == 2


def test_cancelled_job_cannot_be_overwritten_by_inflight_completion(tmp_path) -> None:
    class SlowProvider(RecordingProvider):
        async def synthesize(self, text, options):
            await asyncio.sleep(0.1)
            return await super().synthesize(text, options)

    provider = SlowProvider()
    settings = _settings(tmp_path, chunk_max_words=100)
    service = SynthesisService(settings=settings, providers=ProviderRegistry([provider]))

    with TestClient(create_app(settings=settings, service=service)) as client:
        submitted = client.post(
            "/v1/speech/jobs", json={"text": "cancel this", "provider": "fake"}
        ).json()
        cancelled = client.post(f"/v1/speech/jobs/{submitted['id']}/cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"
        time.sleep(0.2)
        assert client.get(f"/v1/speech/jobs/{submitted['id']}").json()["status"] == "cancelled"
        assert client.get(f"/v1/speech/jobs/{submitted['id']}/audio").status_code == 409
