from __future__ import annotations

import os
import uuid
import wave
from pathlib import Path
from typing import Iterable

from .domain import AudioFormat, CANONICAL_AUDIO_FORMAT


class LocalJobStorage:
    """Filesystem storage for source text, resumable PCM chunks, and final WAV files."""

    def __init__(self, jobs_dir: Path) -> None:
        self.jobs_dir = jobs_dir

    def initialize(self) -> None:
        self.jobs_dir.mkdir(parents=True, exist_ok=True)

    def job_dir(self, job_id: str) -> Path:
        return self.jobs_dir / job_id

    def source_path(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "source.txt"

    def chunk_path(self, job_id: str, index: int) -> Path:
        return self.job_dir(job_id) / "chunks" / f"{index:06d}.pcm"

    def output_path(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "speech.wav"

    def partial_output_path(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "partial.wav"

    def total_chunk_bytes(self, job_id: str) -> int:
        chunk_dir = self.job_dir(job_id) / "chunks"
        if not chunk_dir.is_dir():
            return 0
        return sum(path.stat().st_size for path in chunk_dir.glob("*.pcm") if path.is_file())

    def write_source(self, job_id: str, text: str) -> Path:
        path = self.source_path(job_id)
        self._atomic_write(path, text.encode("utf-8"))
        return path

    def read_source(self, job_id: str) -> str:
        return self.source_path(job_id).read_text(encoding="utf-8")

    def write_chunk(
        self,
        job_id: str,
        index: int,
        pcm: bytes,
        audio_format: AudioFormat = CANONICAL_AUDIO_FORMAT,
    ) -> Path:
        if not pcm:
            raise ValueError("provider returned an empty PCM chunk")
        if len(pcm) % audio_format.frame_width:
            raise ValueError(
                f"PCM byte count {len(pcm)} is not aligned to {audio_format.frame_width}-byte frames"
            )
        path = self.chunk_path(job_id, index)
        self._atomic_write(path, pcm)
        return path

    @staticmethod
    def validate_chunk(path: Path, audio_format: AudioFormat = CANONICAL_AUDIO_FORMAT) -> None:
        size = path.stat().st_size
        if not size:
            raise ValueError(f"PCM chunk is empty: {path}")
        if size % audio_format.frame_width:
            raise ValueError(f"PCM chunk has a partial frame: {path}")

    def assemble_wav(
        self,
        job_id: str,
        chunk_paths: Iterable[Path],
        audio_format: AudioFormat = CANONICAL_AUDIO_FORMAT,
    ) -> Path:
        return self._assemble_wav_to(self.output_path(job_id), chunk_paths, audio_format)

    def assemble_partial_wav(
        self,
        job_id: str,
        chunk_paths: Iterable[Path],
        audio_format: AudioFormat = CANONICAL_AUDIO_FORMAT,
    ) -> Path:
        """Create a point-in-time playable prefix without marking a job completed."""

        return self._assemble_wav_to(self.partial_output_path(job_id), chunk_paths, audio_format)

    def _assemble_wav_to(
        self,
        output: Path,
        chunk_paths: Iterable[Path],
        audio_format: AudioFormat,
    ) -> Path:
        if audio_format.encoding != "pcm_s16le":
            raise ValueError(f"unsupported canonical encoding: {audio_format.encoding}")

        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(f".{output.name}.{uuid.uuid4().hex}.tmp")
        wrote_frames = False
        try:
            with wave.open(str(temporary), "wb") as wav_file:
                wav_file.setnchannels(audio_format.channels)
                wav_file.setsampwidth(audio_format.sample_width)
                wav_file.setframerate(audio_format.sample_rate)
                for path in chunk_paths:
                    self.validate_chunk(path, audio_format)
                    data = path.read_bytes()
                    wav_file.writeframesraw(data)
                    wrote_frames = True
            if not wrote_frames:
                raise ValueError("cannot assemble a WAV without audio frames")
            os.replace(temporary, output)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        return output

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        try:
            temporary.write_bytes(data)
            os.replace(temporary, path)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
