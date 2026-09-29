from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from splicr.artifacts import CheckpointExporter, sanitize_export_stem
from splicr.domain import (
    ChunkRecord,
    ChunkStatus,
    DeliveryControls,
    JobRecord,
    JobStatus,
)
from splicr.storage import LocalJobStorage


def _job(*, status: JobStatus = JobStatus.PAUSED) -> JobRecord:
    return JobRecord(
        id="immutable-job-id",
        status=status,
        provider="fake",
        model="model",
        voice="voice",
        instructions=None,
        controls=DeliveryControls(),
        total_chunks=3,
        completed_chunks=2,
        error=None,
        error_detail=None,
        output_path=None,
        created_at="2026-09-29T00:00:00+00:00",
        updated_at="2026-09-29T00:01:00+00:00",
        export_stem="Résumé final",
    )


def _chunk(
    index: int,
    *,
    status: ChunkStatus,
    path: Path | None = None,
) -> ChunkRecord:
    text = f"Chunk {index + 1} — café"
    return ChunkRecord(
        job_id="immutable-job-id",
        index=index,
        text=text,
        byte_count=len(text.encode("utf-8")),
        word_count=4,
        status=status,
        attempts=1,
        pcm_path=str(path) if path else None,
        error=None,
        metadata={"speaker": "Narrator"},
    )


def test_sanitize_export_stem_preserves_unicode_and_blocks_reserved_names() -> None:
    assert sanitize_export_stem("  Résumé / final?.  ") == "Résumé - final-"
    assert sanitize_export_stem("NUL") == "NUL-audio"
    assert sanitize_export_stem("../") == "splicr-export"
    assert sanitize_export_stem("\x00\x01") == "splicr-export"


@pytest.mark.parametrize(
    "status",
    [JobStatus.PAUSED, JobStatus.FAILED, JobStatus.CANCELLED],
)
def test_checkpoint_export_orders_wav_copies_and_records_missing_chunks(
    tmp_path,
    status: JobStatus,
) -> None:
    storage = LocalJobStorage(tmp_path / "jobs")
    storage.initialize()
    first = storage.write_chunk("immutable-job-id", 0, b"\x01\x00" * 24)
    third = storage.write_chunk("immutable-job-id", 2, b"\x02\x00" * 48)
    chunks = [
        _chunk(2, status=ChunkStatus.COMPLETED, path=third),
        _chunk(0, status=ChunkStatus.COMPLETED, path=first),
        _chunk(1, status=ChunkStatus.COMPLETED, path=tmp_path / "missing.pcm"),
    ]

    artifact = CheckpointExporter(storage).export(_job(status=status), chunks)

    assert artifact.partial is True
    assert artifact.exported_chunks == 2
    assert artifact.missing_chunks == 1
    with zipfile.ZipFile(artifact.path) as archive:
        assert archive.namelist() == [
            "Résumé final-chunk-0001.wav",
            "Résumé final-chunk-0003.wav",
            "Résumé final-checkpoints.json",
        ]
        manifest = json.loads(archive.read("Résumé final-checkpoints.json"))
        assert manifest["job_id"] == "immutable-job-id"
        assert manifest["job_status"] == status.value
        assert manifest["is_finished_master"] is False
        assert [item["index"] for item in manifest["chunks"]] == [0, 1, 2]
        assert [item["availability"] for item in manifest["chunks"]] == [
            "exported",
            "missing",
            "exported",
        ]
        assert manifest["chunks"][0]["text"] == "Chunk 1 — café"
        assert archive.read("Résumé final-chunk-0001.wav").startswith(b"RIFF")

    assert first.read_bytes() == b"\x01\x00" * 24
    assert third.read_bytes() == b"\x02\x00" * 48


def test_checkpoint_export_removes_temporary_archive_after_interruption(
    tmp_path,
    monkeypatch,
) -> None:
    storage = LocalJobStorage(tmp_path / "jobs")
    storage.initialize()
    pcm = storage.write_chunk("immutable-job-id", 0, b"\x01\x00" * 24)
    exporter = CheckpointExporter(storage)

    def fail(_pcm: bytes) -> bytes:
        raise RuntimeError("simulated interruption")

    monkeypatch.setattr(exporter, "_wav_bytes", fail)
    with pytest.raises(RuntimeError, match="simulated interruption"):
        exporter.export(
            _job(),
            [_chunk(0, status=ChunkStatus.COMPLETED, path=pcm)],
        )

    export_dir = storage.job_dir("immutable-job-id") / "exports"
    assert not (export_dir / "Résumé final-checkpoints.zip").exists()
    assert list(export_dir.glob("*.tmp")) == []
