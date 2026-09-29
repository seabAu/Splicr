from __future__ import annotations

import sqlite3

from splicr.domain import (
    ChunkStatus,
    DeliveryControls,
    JobErrorDetail,
    JobStatus,
    NonverbalFrequency,
    SpeechPace,
    TonePreset,
    VocalStyle,
)
from splicr.store import SqliteJobStore


def test_controls_round_trip_with_job_and_chunks(tmp_path) -> None:
    store = SqliteJobStore(tmp_path / "jobs.sqlite3")
    store.initialize()
    controls = DeliveryControls(
        tone=TonePreset.WARM,
        pace=SpeechPace.SLOW,
        vocal_style=VocalStyle.AUDIOBOOK,
        nonverbal_frequency=NonverbalFrequency.OCCASIONAL,
    )

    store.create_job_with_chunks(
        job_id="round-trip",
        provider="fake",
        model="model",
        voice="voice",
        instructions="Be clear.",
        controls=controls,
        resource_revision=4,
        variables={"seed": 7, "metadata": {"language": "en"}},
        chunks=["One.", "Two."],
    )

    job = store.get_job("round-trip")
    assert job.controls == controls
    assert job.resource_revision == 4
    assert job.variables == {"seed": 7, "metadata": {"language": "en"}}
    store.mark_chunk_completed(
        "round-trip",
        0,
        "chunk-00000.pcm",
        {"timings": [{"text": "One", "start_seconds": 0.0}]},
    )
    assert store.chunks_for_job("round-trip")[0].metadata == {
        "timings": [{"start_seconds": 0.0, "text": "One"}]
    }


def test_initialize_migrates_legacy_jobs_without_losing_progress(tmp_path) -> None:
    database = tmp_path / "legacy.sqlite3"
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
                total_chunks INTEGER NOT NULL DEFAULT 0,
                completed_chunks INTEGER NOT NULL DEFAULT 0,
                error TEXT,
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
            INSERT INTO jobs (
                id, status, provider, model, voice, instructions,
                total_chunks, completed_chunks, created_at, updated_at
            ) VALUES (
                'legacy', 'running', 'gemini', 'old-model', 'Kore', 'Legacy notes',
                2, 1, '2026-01-01T00:00:00+00:00', '2026-01-01T00:01:00+00:00'
            );
            INSERT INTO chunks (
                job_id, chunk_index, text, byte_count, word_count, status, attempts
            ) VALUES ('legacy', 0, 'Already complete.', 17, 2, 'completed', 1);
            """
        )

    store = SqliteJobStore(database)
    store.initialize()
    store.initialize()

    job = store.get_job("legacy")
    assert job.completed_chunks == 1
    assert job.instructions == "Legacy notes"
    assert job.controls == DeliveryControls()
    assert store.chunks_for_job("legacy")[0].text == "Already complete."

    with sqlite3.connect(database) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(jobs)")}
        chunk_columns = {row[1] for row in connection.execute("PRAGMA table_info(chunks)")}
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    assert "controls_json" in columns
    assert "error_json" in columns
    assert "resource_revision" in columns
    assert "variables_json" in columns
    assert "metadata_json" in chunk_columns
    assert version == 5


def test_paused_error_round_trips_and_survives_restart_requeue(tmp_path) -> None:
    store = SqliteJobStore(tmp_path / "jobs.sqlite3")
    store.initialize()
    store.create_job_with_chunks(
        job_id="paused",
        provider="fake",
        model="model",
        voice="voice",
        instructions=None,
        chunks=["One."],
    )
    assert store.claim_job("paused") is True
    store.mark_chunk_running("paused", 0)
    detail = JobErrorDetail(
        code="provider_rate_limit",
        message="slow down",
        retryable=True,
        status_code=429,
        chunk_index=0,
    )
    assert store.pause_for_error("paused", detail) is True

    requeued = store.requeue_interrupted()
    paused = store.get_job("paused")

    assert "paused" not in requeued
    assert paused.status is JobStatus.PAUSED
    assert paused.error_detail == detail
    assert store.chunks_for_job("paused")[0].status is ChunkStatus.PENDING


def test_cancel_wins_over_late_worker_completion(tmp_path) -> None:
    store = SqliteJobStore(tmp_path / "jobs.sqlite3")
    store.initialize()
    store.create_job_with_chunks(
        job_id="cancelled",
        provider="fake",
        model="model",
        voice="voice",
        instructions=None,
        chunks=["One."],
    )
    assert store.claim_job("cancelled") is True

    assert store.cancel_job("cancelled").status is JobStatus.CANCELLED
    assert store.mark_job_completed_if_running("cancelled", "speech.wav") is False
    assert store.get_job("cancelled").status is JobStatus.CANCELLED
