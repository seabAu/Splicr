from __future__ import annotations

import hashlib
import io
import json
import os
import re
import unicodedata
import uuid
import wave
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

from .domain import CANONICAL_AUDIO_FORMAT, ChunkRecord, ChunkStatus, JobRecord, JobStatus
from .storage import LocalJobStorage


_INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WHITESPACE = re.compile(r"\s+")
_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
_MAX_EXPORT_STEM_LENGTH = 120


def sanitize_export_stem(value: str | None, *, fallback: str = "splicr-export") -> str:
    """Return a portable, Unicode-preserving filename stem."""

    normalized = unicodedata.normalize("NFKC", value or "")
    normalized = _INVALID_FILENAME.sub("-", normalized)
    normalized = _WHITESPACE.sub(" ", normalized).strip(" .")
    normalized = re.sub(r"-+", "-", normalized)
    if (
        not normalized
        or normalized in {".", ".."}
        or not any(character.isalnum() for character in normalized)
    ):
        normalized = fallback
    if normalized.split(".", 1)[0].upper() in _WINDOWS_RESERVED:
        normalized = f"{normalized}-audio"
    normalized = normalized[:_MAX_EXPORT_STEM_LENGTH].rstrip(" .")
    return normalized or fallback


def collision_export_stem(base: str, ordinal: int) -> str:
    """Apply the stable ``-N`` collision suffix without exceeding the stem limit."""

    if ordinal <= 1:
        return sanitize_export_stem(base)
    suffix = f"-{ordinal}"
    stem = sanitize_export_stem(base)
    return f"{stem[: _MAX_EXPORT_STEM_LENGTH - len(suffix)].rstrip(' .')}{suffix}"


@dataclass(frozen=True, slots=True)
class CheckpointExport:
    path: Path
    filename: str
    partial: bool
    exported_chunks: int
    missing_chunks: int


class CheckpointExporter:
    """Build point-in-time checkpoint archives without mutating synthesis artifacts."""

    def __init__(self, storage: LocalJobStorage) -> None:
        self.storage = storage

    def export(self, job: JobRecord, chunks: Sequence[ChunkRecord]) -> CheckpointExport:
        export_dir = self.storage.job_dir(job.id) / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{job.export_stem}-checkpoints.zip"
        output = export_dir / filename
        temporary = export_dir / f".{filename}.{uuid.uuid4().hex}.tmp"
        width = max(4, len(str(max(1, len(chunks)))))
        manifest_chunks: list[dict[str, Any]] = []
        exported_chunks = 0
        missing_chunks = 0

        try:
            with zipfile.ZipFile(
                temporary,
                mode="w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=6,
            ) as archive:
                for chunk in sorted(chunks, key=lambda item: item.index):
                    entry: dict[str, Any] = {
                        "index": chunk.index,
                        "source_order": chunk.index + 1,
                        "status": chunk.status.value,
                        "text": chunk.text,
                        "byte_count": chunk.byte_count,
                        "word_count": chunk.word_count,
                        "attempts": chunk.attempts,
                        "metadata": dict(chunk.metadata),
                        "checkpoint": None,
                        "availability": "incomplete",
                    }
                    if chunk.status is ChunkStatus.COMPLETED:
                        if not chunk.pcm_path or not Path(chunk.pcm_path).is_file():
                            entry["availability"] = "missing"
                            missing_chunks += 1
                        else:
                            pcm_path = Path(chunk.pcm_path)
                            try:
                                self.storage.validate_chunk(
                                    pcm_path,
                                    CANONICAL_AUDIO_FORMAT,
                                )
                                pcm = pcm_path.read_bytes()
                            except (OSError, ValueError):
                                entry["availability"] = "missing"
                                missing_chunks += 1
                            else:
                                checkpoint_name = (
                                    f"{job.export_stem}-chunk-"
                                    f"{chunk.index + 1:0{width}d}.wav"
                                )
                                archive.writestr(checkpoint_name, self._wav_bytes(pcm))
                                entry.update(
                                    {
                                        "checkpoint": checkpoint_name,
                                        "availability": "exported",
                                        "sha256": hashlib.sha256(pcm).hexdigest(),
                                        "pcm_bytes": len(pcm),
                                        "duration_seconds": (
                                            len(pcm)
                                            / CANONICAL_AUDIO_FORMAT.frame_width
                                            / CANONICAL_AUDIO_FORMAT.sample_rate
                                        ),
                                    }
                                )
                                exported_chunks += 1
                    manifest_chunks.append(entry)

                if not exported_chunks:
                    raise ValueError("no completed audio checkpoints are available to export")

                partial = (
                    job.status is not JobStatus.COMPLETED
                    or exported_chunks != len(chunks)
                    or missing_chunks > 0
                )
                manifest = {
                    "schema_version": 1,
                    "artifact_type": "splicr-checkpoint-export",
                    "artifact_id": f"checkpoint-export:{job.id}",
                    "job_id": job.id,
                    "job_status": job.status.value,
                    "export_stem": job.export_stem,
                    "is_finished_master": False,
                    "partial": partial,
                    "created_at": datetime.now(UTC).isoformat(),
                    "audio_format": {
                        "encoding": CANONICAL_AUDIO_FORMAT.encoding,
                        "sample_rate": CANONICAL_AUDIO_FORMAT.sample_rate,
                        "channels": CANONICAL_AUDIO_FORMAT.channels,
                        "sample_width": CANONICAL_AUDIO_FORMAT.sample_width,
                    },
                    "total_chunks": len(chunks),
                    "exported_chunks": exported_chunks,
                    "missing_chunks": missing_chunks,
                    "chunks": manifest_chunks,
                }
                archive.writestr(
                    f"{job.export_stem}-checkpoints.json",
                    json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
                )
            os.replace(temporary, output)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

        return CheckpointExport(
            path=output,
            filename=filename,
            partial=partial,
            exported_chunks=exported_chunks,
            missing_chunks=missing_chunks,
        )

    @staticmethod
    def _wav_bytes(pcm: bytes) -> bytes:
        output = io.BytesIO()
        with wave.open(output, "wb") as wav_file:
            wav_file.setnchannels(CANONICAL_AUDIO_FORMAT.channels)
            wav_file.setsampwidth(CANONICAL_AUDIO_FORMAT.sample_width)
            wav_file.setframerate(CANONICAL_AUDIO_FORMAT.sample_rate)
            wav_file.writeframes(pcm)
        return output.getvalue()
