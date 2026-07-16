from __future__ import annotations

from fastapi.testclient import TestClient

from splicr.api import create_app
from splicr.config import Settings
from splicr.providers import ProviderRegistry
from splicr.service import SynthesisService

from .fakes import RecordingProvider


def _app(tmp_path):
    settings = Settings(data_dir=tmp_path, pacing_seconds=0)
    service = SynthesisService(
        settings=settings,
        providers=ProviderRegistry([RecordingProvider()]),
    )
    return create_app(settings=settings, service=service)


def test_root_serves_accessible_studio_without_shadowing_api_routes(tmp_path) -> None:
    with TestClient(_app(tmp_path)) as client:
        root = client.get("/")
        health = client.get("/health")
        docs = client.get("/docs")
        providers = client.get("/v1/providers")

    assert root.status_code == 200
    assert root.headers["content-type"].startswith("text/html")
    csp = root.headers["content-security-policy"]
    assert "default-src 'self'" in csp
    assert "object-src 'none'" in csp
    assert "'unsafe-inline'" not in csp
    assert root.headers["x-content-type-options"] == "nosniff"
    assert '<label class="sr-only" for="transcript">' in root.text
    assert '<label for="tone">' in root.text
    assert '<label for="pace">' in root.text
    assert '<label for="nonverbal-frequency">' in root.text
    assert '<output id="pace-output"' in root.text
    assert 'id="remove-numeric-citations"' in root.text
    assert 'id="job-activity"' in root.text
    assert 'id="job-activity-title" aria-live="polite"' in root.text
    assert 'id="job-activity-detail"' in root.text
    assert 'id="job-activity-excerpt"' in root.text
    assert 'id="submission-privacy"' in root.text
    assert "sent to\n            the selected external provider" in root.text
    assert "saved locally in plaintext" in root.text
    assert "not\n            purged automatically" in root.text
    assert "Local-first" not in root.text
    assert '<script src="/assets/app.js" defer></script>' in root.text
    assert "onclick=" not in root.text
    assert health.json() == {"status": "ok"}
    assert docs.status_code == 200
    assert providers.status_code == 200


def test_static_assets_are_packaged_and_path_traversal_is_rejected(tmp_path) -> None:
    with TestClient(_app(tmp_path)) as client:
        css = client.get("/assets/app.css")
        javascript = client.get("/assets/app.js")
        duplicate_entry = client.get("/assets/index.html")
        traversal = client.get("/assets/%2e%2e/api.py")

    assert css.status_code == 200
    assert css.headers["content-type"].startswith("text/css")
    assert "prefers-reduced-motion" in css.text
    assert javascript.status_code == 200
    assert "javascript" in javascript.headers["content-type"]
    assert ".innerHTML" not in javascript.text
    assert "eval(" not in javascript.text
    assert "value.id || value.name" in javascript.text
    assert "remove_numeric_citations: elements.removeNumericCitations.checked" in javascript.text
    assert 'typeof preview.text === "string"' in javascript.text
    assert "job.current_chunk_index" in javascript.text
    assert "completedChunks !== previousAudioChunks" in javascript.text
    assert "if (shouldRefreshPartial) refreshCurrentAudio();" in javascript.text
    assert duplicate_entry.status_code == 404
    assert traversal.status_code in {404, 405}
