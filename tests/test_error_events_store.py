from __future__ import annotations

import json
import sqlite3

import pytest

from splicr.domain import ErrorEventDraft, JobErrorDetail
from splicr.store import SqliteJobStore


def _draft(
    fingerprint: str,
    *,
    message: str | None = None,
    occurred_at: str = "2026-07-18T12:00:00+00:00",
    **overrides,
) -> ErrorEventDraft:
    values = {
        "fingerprint": fingerprint,
        "source": "provider",
        "code": "provider_error",
        "message": message or fingerprint,
        "occurred_at": occurred_at,
    }
    values.update(overrides)
    return ErrorEventDraft(**values)


def test_error_event_persists_all_fields_across_restart(tmp_path) -> None:
    database = tmp_path / "jobs.sqlite3"
    store = SqliteJobStore(database)
    store.initialize()
    draft = _draft(
        "inworld|connect|job-1|2",
        message="All connection attempts failed",
        severity="critical",
        category="connection",
        retryable=True,
        status_code=503,
        method="POST",
        endpoint="https://api.inworld.ai/tts/v1/voice",
        request={"headers": {"authorization": "[redacted]"}, "body": {"text": "Héllo"}},
        response={"status": 503, "headers": {"retry-after": "3"}},
        exception={"type": "ConnectError", "causes": ["DNS", "TCP"]},
        context={"phase": "synthesize", "timing_ms": 1250.5},
        provider="inworld",
        resource_revision=4,
        job_id="job-1",
        chunk_index=2,
        attempt=3,
        occurred_at="2026-07-18T12:34:56+00:00",
    )

    created = store.record_error_event(draft)
    restarted = SqliteJobStore(database)
    restarted.initialize()
    restored = restarted.get_error_event(created.id)

    assert restored is not None
    assert restored.id == created.id
    assert restored.fingerprint == draft.fingerprint
    assert restored.source == draft.source
    assert restored.severity == draft.severity
    assert restored.code == draft.code
    assert restored.category == draft.category
    assert restored.message == draft.message
    assert restored.retryable is True
    assert restored.status_code == 503
    assert restored.method == "POST"
    assert restored.endpoint == draft.endpoint
    assert restored.request == draft.request
    assert restored.response == draft.response
    assert restored.exception == draft.exception
    assert restored.context == draft.context
    assert restored.provider == "inworld"
    assert restored.resource_revision == 4
    assert restored.job_id == "job-1"
    assert restored.chunk_index == 2
    assert restored.attempt == 3
    assert restored.count == 1
    assert restored.first_occurred_at == draft.occurred_at
    assert restored.last_occurred_at == draft.occurred_at
    assert restored.read_at is None
    assert restarted.error_event_counts() == (1, 1)


def test_initialize_migrates_v3_and_decodes_job_error_without_event_id(tmp_path) -> None:
    database = tmp_path / "v3.sqlite3"
    legacy_error = json.dumps(
        {
            "version": 1,
            "code": "provider_error",
            "message": "legacy detail",
            "retryable": True,
            "status_code": 429,
            "chunk_index": 1,
            "occurred_at": "2026-01-01T00:01:00+00:00",
        }
    )
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE jobs (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                voice TEXT NOT NULL,
                instructions TEXT,
                controls_json TEXT NOT NULL DEFAULT '{}',
                resource_revision INTEGER,
                variables_json TEXT NOT NULL DEFAULT '{}',
                total_chunks INTEGER NOT NULL DEFAULT 0,
                completed_chunks INTEGER NOT NULL DEFAULT 0,
                error TEXT,
                error_json TEXT,
                output_path TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE chunks (
                job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                chunk_index INTEGER NOT NULL,
                text TEXT NOT NULL,
                byte_count INTEGER NOT NULL,
                word_count INTEGER NOT NULL,
                status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                pcm_path TEXT,
                error TEXT,
                PRIMARY KEY (job_id, chunk_index)
            );
            PRAGMA user_version = 3;
            """
        )
        connection.execute(
            """
            INSERT INTO jobs (
                id, status, provider, model, voice, instructions, controls_json,
                resource_revision, variables_json, total_chunks, completed_chunks,
                error, error_json, output_path, created_at, updated_at
            ) VALUES (?, 'paused', 'inworld', 'tts-1.5-max', 'Alex', NULL, '{}',
                      2, '{"language":"en"}', 3, 1, 'legacy detail', ?, NULL,
                      '2026-01-01T00:00:00+00:00', '2026-01-01T00:01:00+00:00')
            """,
            ("legacy", legacy_error),
        )

    store = SqliteJobStore(database)
    store.initialize()
    store.initialize()

    job = store.get_job("legacy")
    assert job.completed_chunks == 1
    assert job.variables == {"language": "en"}
    assert job.error_detail is not None
    assert job.error_detail.message == "legacy detail"
    assert job.error_detail.event_id is None
    assert store.record_error_event(_draft("migration-proof")).count == 1

    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    assert {"jobs", "chunks", "error_events", "error_event_meta"} <= tables
    assert version == 4


def test_unread_dedupe_keeps_id_and_refreshes_sequence_and_latest_details(tmp_path) -> None:
    store = SqliteJobStore(tmp_path / "jobs.sqlite3")
    store.initialize()
    first = store.record_error_event(
        _draft(
            "same-fingerprint",
            message="first message",
            response={"status": 500, "generation": 1},
            attempt=1,
            occurred_at="2026-07-18T12:00:00+00:00",
        )
    )
    second = store.record_error_event(
        _draft(
            "same-fingerprint",
            message="latest message",
            severity="critical",
            category="transport",
            retryable=True,
            status_code=503,
            request={"body": {"text": "second"}},
            response={"status": 503, "generation": 2},
            exception={"type": "ConnectError"},
            context={"retry_budget": "exhausted"},
            provider="inworld",
            resource_revision=7,
            job_id="job-latest",
            chunk_index=4,
            attempt=2,
            occurred_at="2026-07-18T12:01:00+00:00",
        )
    )

    assert second.id == first.id
    assert second.sequence > first.sequence
    assert second.count == 2
    assert second.first_occurred_at == first.first_occurred_at
    assert second.last_occurred_at == "2026-07-18T12:01:00+00:00"
    assert second.message == "latest message"
    assert second.response == {"status": 503, "generation": 2}
    assert second.request == {"body": {"text": "second"}}
    assert second.exception == {"type": "ConnectError"}
    assert second.context == {"retry_budget": "exhausted"}
    assert second.provider == "inworld"
    assert second.resource_revision == 7
    assert second.job_id == "job-latest"
    assert second.chunk_index == 4
    assert second.attempt == 2
    assert store.error_event_counts() == (1, 1)
    assert store.list_error_events(after_sequence=first.sequence) == [second]


def test_read_event_then_same_fingerprint_creates_a_new_event(tmp_path) -> None:
    store = SqliteJobStore(tmp_path / "jobs.sqlite3")
    store.initialize()
    first = store.record_error_event(_draft("repeat-after-read"))

    marked = store.mark_error_event_read(first.id)
    second = store.record_error_event(
        _draft("repeat-after-read", occurred_at="2026-07-18T12:05:00+00:00")
    )

    assert marked is not None
    assert marked.read_at is not None
    assert second.id != first.id
    assert second.count == 1
    assert store.error_event_counts() == (1, 2)
    assert [item.id for item in store.list_error_events(unread_only=True)] == [second.id]


def test_list_order_cursor_limit_and_validation(tmp_path) -> None:
    store = SqliteJobStore(tmp_path / "jobs.sqlite3")
    store.initialize()
    first = store.record_error_event(_draft("first"))
    second = store.record_error_event(_draft("second"))
    third = store.record_error_event(_draft("third"))

    assert [item.id for item in store.list_error_events()] == [third.id, second.id, first.id]
    assert [item.id for item in store.list_error_events(limit=2)] == [third.id, second.id]
    assert [item.id for item in store.list_error_events(after_sequence=first.sequence)] == [
        third.id,
        second.id,
    ]
    assert store.list_error_events(after_sequence=third.sequence) == []

    with pytest.raises(ValueError, match="after_sequence"):
        store.list_error_events(after_sequence=-1)
    with pytest.raises(ValueError, match="limit"):
        store.list_error_events(limit=0)


def test_mark_all_clear_scopes_and_missing_event(tmp_path) -> None:
    store = SqliteJobStore(tmp_path / "jobs.sqlite3")
    store.initialize()
    store.record_error_event(_draft("one"))
    store.record_error_event(_draft("two"))
    store.record_error_event(_draft("three"))

    assert store.mark_error_event_read("missing") is None
    assert store.mark_all_error_events_read() == 3
    assert store.error_event_counts() == (0, 3)
    assert store.mark_all_error_events_read() == 0
    assert store.clear_error_events("read") == 3
    assert store.error_event_counts() == (0, 0)

    store.record_error_event(_draft("four"))
    store.record_error_event(_draft("five"))
    assert store.clear_error_events("all") == 2
    assert store.error_event_counts() == (0, 0)
    with pytest.raises(ValueError, match="scope"):
        store.clear_error_events("unread")


def test_error_event_retention_keeps_the_500_newest_records(tmp_path) -> None:
    store = SqliteJobStore(tmp_path / "jobs.sqlite3")
    store.initialize()
    records = [store.record_error_event(_draft(f"event-{index}")) for index in range(505)]

    retained = store.list_error_events(limit=1_000)

    assert len(retained) == 500
    assert store.error_event_counts() == (500, 500)
    assert retained[0].id == records[-1].id
    assert retained[-1].id == records[5].id
    assert store.get_error_event(records[0].id) is None
    assert store.get_error_event(records[-1].id) is not None


def test_job_error_event_id_round_trips_and_non_finite_json_is_rejected(tmp_path) -> None:
    database = tmp_path / "jobs.sqlite3"
    store = SqliteJobStore(database)
    store.initialize()
    event = store.record_error_event(_draft("job-error-link"))
    store.create_job_with_chunks(
        job_id="linked",
        provider="inworld",
        model="tts-1.5-max",
        voice="Alex",
        instructions=None,
        chunks=["One."],
    )
    detail = JobErrorDetail(
        code="internal_error",
        message="All connection attempts failed",
        retryable=True,
        chunk_index=0,
        event_id=event.id,
    )
    assert store.pause_for_error("linked", detail) is True

    restarted = SqliteJobStore(database)
    restarted.initialize()
    assert restarted.get_job("linked").error_detail == detail

    with pytest.raises(ValueError, match="JSON"):
        restarted.record_error_event(_draft("invalid-json", request={"not_finite": float("nan")}))
