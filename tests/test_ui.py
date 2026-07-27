from __future__ import annotations

import re

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
    assert '<label for="provider">API resource</label>' in root.text
    assert 'id="add-resource" type="button" aria-label="Add API resource"' in root.text
    assert 'id="edit-resource" type="button" disabled' in root.text
    assert 'id="resource-modal" aria-labelledby="resource-modal-title"' in root.text
    assert 'id="resource-api-key" name="resource-api-key" type="password"' in root.text
    assert 'autocomplete="new-password"' in root.text
    assert 'id="toggle-resource-key" type="button" aria-label="Show API key"' in root.text
    assert 'id="request-template-tree" aria-label="Request JSON template builder"' in root.text
    assert 'id="resource-template-json" name="resource-template-json"' in root.text
    assert 'id="resource-headers-json"' in root.text
    assert 'id="resource-query-json"' in root.text
    assert 'id="resource-default-variables-json"' in root.text
    assert 'id="resource-timeout"' in root.text
    assert 'id="resource-retry-attempts"' in root.text
    assert 'id="profiles-modal" aria-labelledby="profiles-title"' in root.text
    assert 'id="profile-include-job" type="checkbox"' in root.text
    assert 'id="error-log-button"' in root.text
    assert 'aria-label="Open error log, 0 unread errors"' in root.text
    assert 'id="error-unread-badge" aria-hidden="true" hidden' in root.text
    assert 'id="error-toast-region"' in root.text
    assert 'aria-label="Error notifications"' in root.text
    assert 'aria-live="polite"' in root.text
    assert 'id="error-log-modal"' in root.text
    assert 'aria-labelledby="error-log-title"' in root.text
    assert 'id="error-details-modal"' in root.text
    assert 'aria-labelledby="error-details-title"' in root.text
    assert 'id="error-details-request"' in root.text
    assert 'id="error-details-response"' in root.text
    assert 'id="error-details-exception"' in root.text
    assert 'id="error-details-context"' in root.text
    assert 'id="error-details-raw"' in root.text
    assert 'id="view-job-diagnostics" type="button" hidden' in root.text
    assert '<output id="pace-output"' in root.text
    assert 'id="remove-numeric-citations"' in root.text
    assert 'id="job-activity"' in root.text
    assert 'id="job-activity-title" aria-live="polite"' in root.text
    assert 'id="job-activity-detail"' in root.text
    assert 'id="job-activity-excerpt"' in root.text
    assert 'id="submission-privacy"' in root.text
    assert "sent to\n            the selected external API resource" in root.text
    assert "saved locally in plaintext" in root.text
    assert "not\n            purged automatically" in root.text
    assert "Local-first" not in root.text
    assert '<script src="/assets/app.js" defer></script>' in root.text
    assert '<a class="quiet-link" href="/auth/settings">Account</a>' in root.text
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
    assert 'typeof value === "string" ? value : resourceId(value)' in javascript.text
    assert "remove_numeric_citations: elements.removeNumericCitations.checked" in javascript.text
    assert 'typeof preview.text === "string"' in javascript.text
    assert "job.current_chunk_index" in javascript.text
    assert "completedChunks !== previousAudioChunks" in javascript.text
    assert "if (shouldRefreshPartial) refreshCurrentAudio();" in javascript.text
    assert 'requestJson("/v1/api-resources", { reportError: false })' in javascript.text
    assert 'requestJson("/v1/providers")' in javascript.text
    assert 'requestJson("/v1/profiles")' in javascript.text
    assert 'fetch("/v1/errors/client"' in javascript.text
    assert (
        "`/v1/errors?after=${encodeURIComponent(after)}&limit=100&unread_only=false`"
        in javascript.text
    )
    assert "`/v1/errors/${encodeURIComponent(normalizedId)}`" in javascript.text
    assert "`/v1/errors/${encodeURIComponent(errorId)}/read`" in javascript.text
    assert 'requestJson("/v1/errors/read-all"' in javascript.text
    assert "reportError: false" in javascript.text
    assert "safeDiagnosticValue" in javascript.text
    assert "summarizeRequestBody" in javascript.text
    assert "SENSITIVE_FIELD_RE" in javascript.text
    assert "DIAGNOSTIC_STRING_LIMIT" in javascript.text
    assert "state.errorToasts.get(event.id)" in javascript.text
    assert 'view.setAttribute("aria-label", `View error details:' in javascript.text
    assert "createSvgIcon" in javascript.text
    assert "jobErrorEventId" in javascript.text
    assert "elements.viewJobDiagnostics.hidden" in javascript.text
    assert "trapDialogFocus" in javascript.text
    assert 'source: "client"' not in javascript.text
    assert 'source: "browser"' in javascript.text
    assert 'body.error_code === "authentication_required"' in javascript.text
    mojibake_markers = ("\u00c3", "\u00c2", "\u00e2")
    assert not any(marker in javascript.text for marker in mojibake_markers)
    assert 'method: editingId ? "PUT" : "POST"' in javascript.text
    assert 'method: "DELETE"' in javascript.text
    assert "templateNodeFromValue" in javascript.text
    assert "templateValueFromNode" in javascript.text
    assert "headers: parseJsonObjectField(elements.resourceHeadersJson" in javascript.text
    assert "response_sample_rate_hz: optionalNumber(elements.resourceSampleRate)" in javascript.text
    assert 'resourceConfigValue(resource, "request_timeout_seconds", 300)' in javascript.text
    assert 'resourceConfigValue(resource, "retry_max_attempts", 3)' in javascript.text
    assert 'resourceConfigValue(resource, "max_concurrency", 1)' in javascript.text
    assert (
        "state.keyVisibilityTimer = window.setTimeout(hideResourceKey, 30_000);" in javascript.text
    )
    assert 'document.addEventListener("visibilitychange"' in javascript.text
    assert 'elements.resourceApiKey.value = "";' in javascript.text
    assert (
        "resource_revision: job.resource_revision ?? state.selectedResourceRevision"
        in javascript.text
    )
    assert "remove_numeric_citations: job.remove_numeric_citations" in javascript.text
    assert "variables: job.variables" in javascript.text
    assert "job_id: includeJob && state.activeJobId ? state.activeJobId : null" in javascript.text
    # Fetch the root independently because the duplicate static entry is intentionally unavailable.
    with TestClient(_app(tmp_path)) as client:
        document = client.get("/").text
    assert not any(marker in document for marker in mojibake_markers)
    html_ids = re.findall(r'\bid="([^"]+)"', document)
    javascript_ids = re.findall(r'byId\("([^"]+)"\)', javascript.text)
    assert len(html_ids) == len(set(html_ids))
    assert set(javascript_ids) <= set(html_ids)
    assert duplicate_entry.status_code == 404
    assert traversal.status_code in {404, 405}
