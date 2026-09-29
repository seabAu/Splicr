from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import threading
import uuid
import wave
from collections.abc import Callable
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from ..domain import JobStatus, utc_now
from ..storage import LocalJobStorage
from ..store import SqliteJobStore
from .domain import Artifact, ArtifactKind
from .migration import import_splicr_job
from .store import SqliteStudioStore
from .subtitles import SubtitleFormat, SubtitleService


_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_PRESET_COST = {"ultrafast": 0.18, "veryfast": 0.34, "fast": 0.72, "medium": 1.0}


class AudiogramSource(StrEnum):
    WAVEFORM = "waveform"
    FREQUENCY = "frequency"
    SPECTRUM = "spectrum"
    VECTORSCOPE = "vectorscope"


class AudiogramOutputFormat(StrEnum):
    MP4 = "mp4"
    WEBM = "webm"


class AudiogramJobKind(StrEnum):
    PREVIEW = "preview"
    EXPORT = "export"


class AudiogramJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    FAILED = "failed"
    COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class AudiogramSpec:
    source: AudiogramSource = AudiogramSource.WAVEFORM
    width: int = 1280
    height: int = 720
    fps: int = 24
    visualizer_height: int = 300
    vertical_position: float = 0.5
    foreground_color: str = "#F4A259"
    background_color: str = "#0B0D10"
    waveform_mode: str = "cline"
    amplitude_scale: str = "sqrt"
    blur: float = 0.0
    sharpen: float = 0.0
    trail: bool = False
    burn_captions: bool = False
    output_format: AudiogramOutputFormat = AudiogramOutputFormat.MP4
    preset: str = "ultrafast"
    crf: int = 20

    def __post_init__(self) -> None:
        if not 320 <= self.width <= 3840 or self.width % 2:
            raise ValueError("width must be an even number between 320 and 3840")
        if not 180 <= self.height <= 2160 or self.height % 2:
            raise ValueError("height must be an even number between 180 and 2160")
        if not 12 <= self.fps <= 60:
            raise ValueError("fps must be between 12 and 60")
        if not 64 <= self.visualizer_height <= self.height:
            raise ValueError("visualizer_height must be between 64 and the canvas height")
        if not 0 <= self.vertical_position <= 1:
            raise ValueError("vertical_position must be between 0 and 1")
        for label, value in (
            ("foreground_color", self.foreground_color),
            ("background_color", self.background_color),
        ):
            if not _HEX_COLOR.fullmatch(value):
                raise ValueError(f"{label} must use #RRGGBB notation")
        if self.waveform_mode not in {"cline", "line", "p2p", "point"}:
            raise ValueError("waveform_mode must be cline, line, p2p, or point")
        if self.amplitude_scale not in {"lin", "sqrt", "cbrt", "log"}:
            raise ValueError("amplitude_scale must be lin, sqrt, cbrt, or log")
        if not 0 <= self.blur <= 20:
            raise ValueError("blur must be between 0 and 20")
        if not 0 <= self.sharpen <= 1:
            raise ValueError("sharpen must be between 0 and 1")
        if self.preset not in _PRESET_COST:
            raise ValueError("preset must be ultrafast, veryfast, fast, or medium")
        crf_max = 63 if self.output_format is AudiogramOutputFormat.WEBM else 51
        if not 0 <= self.crf <= crf_max:
            raise ValueError(f"crf must be between 0 and {crf_max}")

    def to_mapping(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, value: dict[str, object]) -> AudiogramSpec:
        return cls(
            **{
                **value,
                "source": AudiogramSource(str(value.get("source", "waveform"))),
                "output_format": AudiogramOutputFormat(str(value.get("output_format", "mp4"))),
            }
        )


@dataclass(frozen=True, slots=True)
class AudiogramJob:
    id: str
    source_job_id: str
    project_id: str
    take_id: str
    kind: AudiogramJobKind
    status: AudiogramJobStatus
    spec: AudiogramSpec
    duration_seconds: float
    render_seconds: float
    progress: float
    output_path: str | None
    artifact_id: str | None
    error_code: str | None
    error_detail: str | None
    cancel_requested: bool
    created_at: str
    updated_at: str


class AudiogramJobNotFoundError(LookupError):
    pass


class InvalidAudiogramJobStateError(RuntimeError):
    pass


class AudiogramRenderError(RuntimeError):
    pass


class AudiogramRenderCancelled(RuntimeError):
    pass


class AudiogramJobStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path)
        self._lock = threading.RLock()

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS studio_audiogram_jobs (
                    id TEXT PRIMARY KEY,
                    source_job_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    take_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    spec_json TEXT NOT NULL,
                    duration_seconds REAL NOT NULL,
                    render_seconds REAL NOT NULL,
                    progress REAL NOT NULL DEFAULT 0,
                    output_path TEXT,
                    artifact_id TEXT,
                    error_code TEXT,
                    error_detail TEXT,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_studio_audiogram_jobs_created
                    ON studio_audiogram_jobs(created_at DESC);
                """
            )

    def create(self, job: AudiogramJob) -> AudiogramJob:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO studio_audiogram_jobs (
                    id, source_job_id, project_id, take_id, kind, status, spec_json,
                    duration_seconds, render_seconds, progress, output_path, artifact_id,
                    error_code, error_detail, cancel_requested, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._values(job),
            )
        return self.get(job.id)

    def get(self, job_id: str) -> AudiogramJob:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM studio_audiogram_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        if row is None:
            raise AudiogramJobNotFoundError(job_id)
        return self._from_row(row)

    def list(self, *, limit: int = 100) -> list[AudiogramJob]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM studio_audiogram_jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def requeue_interrupted(self) -> list[str]:
        now = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE studio_audiogram_jobs
                SET status = ?, progress = 0, cancel_requested = 0,
                    error_code = NULL, error_detail = NULL, updated_at = ?
                WHERE status IN (?, ?)
                """,
                (
                    AudiogramJobStatus.QUEUED.value,
                    now,
                    AudiogramJobStatus.RUNNING.value,
                    AudiogramJobStatus.CANCEL_REQUESTED.value,
                ),
            )
            rows = connection.execute(
                "SELECT id FROM studio_audiogram_jobs WHERE status = ? ORDER BY created_at",
                (AudiogramJobStatus.QUEUED.value,),
            ).fetchall()
        return [row["id"] for row in rows]

    def claim(self, job_id: str) -> bool:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE studio_audiogram_jobs
                SET status = ?, progress = 0, updated_at = ?
                WHERE id = ? AND status = ? AND cancel_requested = 0
                """,
                (
                    AudiogramJobStatus.RUNNING.value,
                    utc_now(),
                    job_id,
                    AudiogramJobStatus.QUEUED.value,
                ),
            )
        return cursor.rowcount == 1

    def update_progress(self, job_id: str, progress: float) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE studio_audiogram_jobs SET progress = ?, updated_at = ?
                WHERE id = ? AND status IN (?, ?)
                """,
                (
                    max(0.0, min(1.0, progress)),
                    utc_now(),
                    job_id,
                    AudiogramJobStatus.RUNNING.value,
                    AudiogramJobStatus.CANCEL_REQUESTED.value,
                ),
            )

    def complete(self, job_id: str, output_path: Path, artifact_id: str | None) -> AudiogramJob:
        self._transition(
            job_id,
            AudiogramJobStatus.COMPLETED,
            progress=1.0,
            output_path=str(output_path.resolve()),
            artifact_id=artifact_id,
            cancel_requested=0,
            error_code=None,
            error_detail=None,
        )
        return self.get(job_id)

    def fail(self, job_id: str, code: str, detail: str) -> AudiogramJob:
        self._transition(
            job_id,
            AudiogramJobStatus.FAILED,
            error_code=code,
            error_detail=detail,
            cancel_requested=0,
        )
        return self.get(job_id)

    def request_cancel(self, job_id: str) -> AudiogramJob:
        job = self.get(job_id)
        if job.status is AudiogramJobStatus.QUEUED:
            self._transition(
                job_id,
                AudiogramJobStatus.CANCELLED,
                cancel_requested=1,
            )
        elif job.status is AudiogramJobStatus.RUNNING:
            self._transition(
                job_id,
                AudiogramJobStatus.CANCEL_REQUESTED,
                cancel_requested=1,
            )
        elif job.status not in {
            AudiogramJobStatus.CANCEL_REQUESTED,
            AudiogramJobStatus.CANCELLED,
        }:
            raise InvalidAudiogramJobStateError(f"cannot cancel a {job.status.value} job")
        return self.get(job_id)

    def mark_cancelled(self, job_id: str) -> AudiogramJob:
        self._transition(
            job_id,
            AudiogramJobStatus.CANCELLED,
            cancel_requested=1,
        )
        return self.get(job_id)

    def retry(self, job_id: str) -> AudiogramJob:
        job = self.get(job_id)
        if job.status not in {AudiogramJobStatus.FAILED, AudiogramJobStatus.CANCELLED}:
            raise InvalidAudiogramJobStateError(f"cannot retry a {job.status.value} job")
        self._transition(
            job_id,
            AudiogramJobStatus.QUEUED,
            progress=0.0,
            output_path=None,
            artifact_id=None,
            error_code=None,
            error_detail=None,
            cancel_requested=0,
        )
        return self.get(job_id)

    def _transition(self, job_id: str, status: AudiogramJobStatus, **values: object) -> None:
        assignments = ["status = ?", "updated_at = ?"]
        parameters: list[object] = [status.value, utc_now()]
        for key, value in values.items():
            assignments.append(f"{key} = ?")
            parameters.append(value)
        parameters.append(job_id)
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                f"UPDATE studio_audiogram_jobs SET {', '.join(assignments)} WHERE id = ?",
                parameters,
            )
        if cursor.rowcount != 1:
            raise AudiogramJobNotFoundError(job_id)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _values(job: AudiogramJob) -> tuple[object, ...]:
        return (
            job.id,
            job.source_job_id,
            job.project_id,
            job.take_id,
            job.kind.value,
            job.status.value,
            json.dumps(job.spec.to_mapping(), sort_keys=True),
            job.duration_seconds,
            job.render_seconds,
            job.progress,
            job.output_path,
            job.artifact_id,
            job.error_code,
            job.error_detail,
            int(job.cancel_requested),
            job.created_at,
            job.updated_at,
        )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> AudiogramJob:
        return AudiogramJob(
            id=row["id"],
            source_job_id=row["source_job_id"],
            project_id=row["project_id"],
            take_id=row["take_id"],
            kind=AudiogramJobKind(row["kind"]),
            status=AudiogramJobStatus(row["status"]),
            spec=AudiogramSpec.from_mapping(json.loads(row["spec_json"])),
            duration_seconds=row["duration_seconds"],
            render_seconds=row["render_seconds"],
            progress=row["progress"],
            output_path=row["output_path"],
            artifact_id=row["artifact_id"],
            error_code=row["error_code"],
            error_detail=row["error_detail"],
            cancel_requested=bool(row["cancel_requested"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


def _ffmpeg_color(value: str) -> str:
    return f"0x{value[1:]}"


def _rgb_components(value: str) -> tuple[int, int, int]:
    return int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16)


def _ffmpeg_subtitle_path(path: Path) -> str:
    value = path.resolve().as_posix()
    for character in ("\\", ":", "'", ",", "[", "]", ";"):
        value = value.replace(character, f"\\{character}")
    return value


def build_filter_graph(
    spec: AudiogramSpec, *, subtitle_path: Path | None = None
) -> str:
    size = f"{spec.width}x{spec.visualizer_height}"
    color = _ffmpeg_color(spec.foreground_color)
    if spec.source is AudiogramSource.WAVEFORM:
        visualizer = (
            f"showwaves=s={size}:mode={spec.waveform_mode}:rate={spec.fps}:"
            f"colors={color}:scale={spec.amplitude_scale}"
        )
    elif spec.source is AudiogramSource.FREQUENCY:
        visualizer = (
            f"showfreqs=s={size}:mode=line:fscale=log:ascale={spec.amplitude_scale}:"
            f"colors={color}:rate={spec.fps}"
        )
    elif spec.source is AudiogramSource.SPECTRUM:
        visualizer = (
            f"showspectrum=s={size}:mode=combined:color=intensity:scale=log:"
            f"slide=scroll:fps={spec.fps}"
        )
    else:
        red, green, blue = _rgb_components(spec.foreground_color)
        visualizer = (
            f"avectorscope=s={size}:mode=lissajous:draw=line:scale=lin:"
            f"rate={spec.fps}:rc={red}:gc={green}:bc={blue}"
        )
    effects = [visualizer, "format=rgba", "colorkey=0x000000:0.08:0.04"]
    if spec.sharpen:
        effects.append(f"cas=strength={spec.sharpen:.3f}")
    if spec.blur:
        effects.append(f"gblur=sigma={spec.blur:.3f}")
    if spec.trail:
        effects.append("tblend=all_mode=average")
    y = round((spec.height - spec.visualizer_height) * spec.vertical_position)
    graph = (
        f"[0:a]aformat=channel_layouts=mono,{','.join(effects)}[viz];"
        f"color=c={_ffmpeg_color(spec.background_color)}:s={spec.width}x{spec.height}:"
        f"r={spec.fps}[bg];"
        f"[bg][viz]overlay=x=0:y={y}:shortest=1,format=yuv420p[composite]"
    )
    if spec.burn_captions:
        if subtitle_path is None:
            raise ValueError("caption burn-in requires a subtitle artifact")
        escaped = _ffmpeg_subtitle_path(subtitle_path)
        return (
            f"{graph};[composite]subtitles=filename='{escaped}':"
            "force_style='Alignment=2,MarginV=28,Outline=2,Shadow=1'[v]"
        )
    return f"{graph};[composite]null[v]"


def build_ffmpeg_command(
    executable: str,
    source_path: Path,
    output_path: Path,
    spec: AudiogramSpec,
    *,
    render_seconds: float,
    subtitle_path: Path | None = None,
) -> list[str]:
    command = [
        executable,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-progress",
        "pipe:1",
        "-nostats",
        "-i",
        str(source_path),
        "-filter_complex",
        build_filter_graph(spec, subtitle_path=subtitle_path),
        "-map",
        "[v]",
        "-map",
        "0:a:0",
        "-t",
        f"{render_seconds:.3f}",
        "-r",
        str(spec.fps),
    ]
    if spec.output_format is AudiogramOutputFormat.MP4:
        command.extend(
            [
                "-c:v",
                "libx264",
                "-preset",
                spec.preset,
                "-crf",
                str(spec.crf),
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-movflags",
                "+faststart",
            ]
        )
    else:
        command.extend(
            [
                "-c:v",
                "libvpx-vp9",
                "-deadline",
                "realtime" if spec.preset == "ultrafast" else "good",
                "-cpu-used",
                "8" if spec.preset == "ultrafast" else "4",
                "-crf",
                str(spec.crf),
                "-b:v",
                "0",
                "-c:a",
                "libopus",
                "-b:a",
                "160k",
            ]
        )
    command.extend(["-shortest", str(output_path)])
    return command


def estimate_render_seconds(spec: AudiogramSpec, audio_seconds: float) -> float:
    pixel_ratio = (spec.width * spec.height) / (1920 * 1080)
    fps_ratio = spec.fps / 30
    source_cost = {
        AudiogramSource.WAVEFORM: 0.85,
        AudiogramSource.FREQUENCY: 1.05,
        AudiogramSource.SPECTRUM: 1.2,
        AudiogramSource.VECTORSCOPE: 1.1,
    }[spec.source]
    effects_cost = 1 + min(spec.blur / 20, 0.4) + (0.18 if spec.trail else 0)
    return max(1.0, audio_seconds * pixel_ratio * fps_ratio * _PRESET_COST[spec.preset] * source_cost * effects_cost)


ProgressCallback = Callable[[float], None]
CancelCallback = Callable[[], bool]


class AudiogramRenderer(Protocol):
    @property
    def available(self) -> bool: ...

    async def render(
        self,
        source_path: Path,
        output_path: Path,
        spec: AudiogramSpec,
        *,
        render_seconds: float,
        subtitle_path: Path | None = None,
        on_progress: ProgressCallback,
        is_cancelled: CancelCallback,
    ) -> None: ...


class FfmpegAudiogramRenderer:
    def __init__(self, executable: str = "ffmpeg") -> None:
        self.executable = executable

    @property
    def available(self) -> bool:
        return shutil.which(self.executable) is not None

    async def render(
        self,
        source_path: Path,
        output_path: Path,
        spec: AudiogramSpec,
        *,
        render_seconds: float,
        subtitle_path: Path | None = None,
        on_progress: ProgressCallback,
        is_cancelled: CancelCallback,
    ) -> None:
        if not self.available:
            raise AudiogramRenderError(
                "FFmpeg was not found. Install FFmpeg and ensure the ffmpeg command is on PATH."
            )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = build_ffmpeg_command(
            self.executable,
            source_path,
            output_path,
            spec,
            render_seconds=render_seconds,
            subtitle_path=subtitle_path,
        )
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=creationflags,
        )
        if process.stdout is None or process.stderr is None:
            process.kill()
            raise AudiogramRenderError("FFmpeg did not expose its progress streams")
        stdout = process.stdout
        stderr_task = asyncio.create_task(process.stderr.read())
        try:
            while process.returncode is None:
                if is_cancelled():
                    process.terminate()
                    with contextlib.suppress(asyncio.TimeoutError):
                        await asyncio.wait_for(process.wait(), timeout=3)
                    if process.returncode is None:
                        process.kill()
                        await process.wait()
                    raise AudiogramRenderCancelled
                try:
                    line = await asyncio.wait_for(stdout.readline(), timeout=0.25)
                except asyncio.TimeoutError:
                    continue
                if not line:
                    await process.wait()
                    break
                key, _, raw_value = line.decode("utf-8", errors="replace").strip().partition("=")
                if key in {"out_time_us", "out_time_ms"}:
                    with contextlib.suppress(ValueError):
                        on_progress(min(0.995, int(raw_value) / 1_000_000 / render_seconds))
            stderr = (await stderr_task).decode("utf-8", errors="replace").strip()
            if process.returncode:
                raise AudiogramRenderError(stderr[-8_000:] or f"FFmpeg exited with code {process.returncode}")
            on_progress(1.0)
        except (asyncio.CancelledError, AudiogramRenderCancelled):
            if process.returncode is None:
                process.terminate()
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(process.wait(), timeout=3)
                if process.returncode is None:
                    process.kill()
            stderr_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await stderr_task
            raise


class AudiogramJobService:
    def __init__(
        self,
        *,
        store: AudiogramJobStore,
        source_store: SqliteJobStore,
        source_storage: LocalJobStorage,
        studio_store: SqliteStudioStore,
        output_root: Path,
        subtitle_service: SubtitleService | None = None,
        renderer: AudiogramRenderer | None = None,
    ) -> None:
        self.store = store
        self.source_store = source_store
        self.source_storage = source_storage
        self.studio_store = studio_store
        self.output_root = Path(output_root)
        self.subtitle_service = subtitle_service
        self.renderer = renderer or FfmpegAudiogramRenderer()
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None

    @property
    def ffmpeg_available(self) -> bool:
        return self.renderer.available

    async def start(self) -> None:
        if self._worker is not None:
            return
        self.store.initialize()
        self.output_root.mkdir(parents=True, exist_ok=True)
        for job_id in self.store.requeue_interrupted():
            self._queue.put_nowait(job_id)
        self._worker = asyncio.create_task(self._worker_loop(), name="splicr-audiogram-worker")

    async def stop(self) -> None:
        if self._worker is None:
            return
        self._worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._worker
        self._worker = None

    def list_sources(self) -> list[dict[str, object]]:
        sources: list[dict[str, object]] = []
        for source in self.source_store.list_jobs():
            if source.status is not JobStatus.COMPLETED:
                continue
            path = Path(source.output_path) if source.output_path else self.source_storage.output_path(source.id)
            if not path.is_file():
                continue
            with contextlib.suppress(OSError, wave.Error):
                duration = self._wav_duration(path)
                sources.append(
                    {
                        "job_id": source.id,
                        "provider": source.provider,
                        "voice": source.voice,
                        "duration_seconds": duration,
                        "created_at": source.created_at,
                    }
                )
        return sources

    async def submit(
        self,
        source_job_id: str,
        spec: AudiogramSpec,
        *,
        kind: AudiogramJobKind,
    ) -> AudiogramJob:
        if not self.ffmpeg_available:
            raise AudiogramRenderError(
                "FFmpeg was not found. Install FFmpeg and ensure the ffmpeg command is on PATH."
            )
        if spec.burn_captions and self.subtitle_service is None:
            raise AudiogramRenderError("caption burn-in is not configured")
        source = self.source_store.get_job(source_job_id)
        if source.status is not JobStatus.COMPLETED:
            raise ValueError("audiograms require a completed narration take")
        source_path = Path(source.output_path) if source.output_path else self.source_storage.output_path(source.id)
        if not source_path.is_file():
            raise FileNotFoundError("the completed take's audio file is missing")
        duration = self._wav_duration(source_path)
        imported = import_splicr_job(
            job_id=source_job_id,
            job_store=self.source_store,
            job_storage=self.source_storage,
            studio_store=self.studio_store,
        )
        if imported.take_id is None:
            raise ValueError("the source take has no render plan")
        job_id = uuid.uuid4().hex
        render_seconds = min(8.0, duration) if kind is AudiogramJobKind.PREVIEW else duration
        now = utc_now()
        job = self.store.create(
            AudiogramJob(
                id=job_id,
                source_job_id=source_job_id,
                project_id=imported.project_id,
                take_id=imported.take_id,
                kind=kind,
                status=AudiogramJobStatus.QUEUED,
                spec=spec,
                duration_seconds=duration,
                render_seconds=render_seconds,
                progress=0.0,
                output_path=None,
                artifact_id=None,
                error_code=None,
                error_detail=None,
                cancel_requested=False,
                created_at=now,
                updated_at=now,
            )
        )
        await self._queue.put(job.id)
        return job

    async def cancel(self, job_id: str) -> AudiogramJob:
        return self.store.request_cancel(job_id)

    async def retry(self, job_id: str) -> AudiogramJob:
        job = self.store.retry(job_id)
        await self._queue.put(job.id)
        return job

    def output_for(self, job_id: str) -> Path:
        job = self.store.get(job_id)
        if job.status is not AudiogramJobStatus.COMPLETED or not job.output_path:
            raise InvalidAudiogramJobStateError("audiogram output is not ready")
        path = Path(job.output_path)
        if not path.is_file():
            raise FileNotFoundError("the audiogram output file is missing")
        return path

    async def _worker_loop(self) -> None:
        while True:
            job_id = await self._queue.get()
            try:
                if self.store.claim(job_id):
                    await self._render(job_id)
            finally:
                self._queue.task_done()

    async def _render(self, job_id: str) -> None:
        job = self.store.get(job_id)
        source = self.source_store.get_job(job.source_job_id)
        source_path = Path(source.output_path) if source.output_path else self.source_storage.output_path(source.id)
        extension = job.spec.output_format.value
        directory = self.output_root / job.id
        final_path = directory / f"{job.kind.value}.{extension}"
        temporary_path = directory / f".{job.kind.value}.{uuid.uuid4().hex}.part.{extension}"
        temporary_path.parent.mkdir(parents=True, exist_ok=True)
        final_path.unlink(missing_ok=True)
        last_reported = -1.0
        subtitle_export = None
        subtitle_path = None

        def on_progress(progress: float) -> None:
            nonlocal last_reported
            if progress >= 1 or progress - last_reported >= 0.0025:
                self.store.update_progress(job.id, progress)
                last_reported = progress

        try:
            if job.spec.burn_captions:
                if self.subtitle_service is None:
                    raise AudiogramRenderError("caption burn-in is not configured")
                subtitle_export = self.subtitle_service.export(
                    job.source_job_id, SubtitleFormat.SRT
                )
                subtitle_path = Path(subtitle_export.artifact.path)
            await self.renderer.render(
                source_path,
                temporary_path,
                job.spec,
                render_seconds=job.render_seconds,
                subtitle_path=subtitle_path,
                on_progress=on_progress,
                is_cancelled=lambda: self.store.get(job.id).cancel_requested,
            )
            if self.store.get(job.id).cancel_requested:
                raise AudiogramRenderCancelled
            if not temporary_path.is_file() or temporary_path.stat().st_size == 0:
                raise AudiogramRenderError("FFmpeg completed without producing a video file")
            os.replace(temporary_path, final_path)
            artifact_id: str | None = None
            if job.kind is AudiogramJobKind.EXPORT:
                artifact_id = uuid.uuid4().hex
                self.studio_store.add_artifact(
                    Artifact(
                        id=artifact_id,
                        project_id=job.project_id,
                        take_id=job.take_id,
                        kind=ArtifactKind.VIDEO,
                        path=str(final_path.resolve()),
                        media_type=(
                            "video/mp4"
                            if job.spec.output_format is AudiogramOutputFormat.MP4
                            else "video/webm"
                        ),
                        size_bytes=final_path.stat().st_size,
                        sha256=self._sha256(final_path),
                        metadata={
                            "captions_burned_in": job.spec.burn_captions,
                            "subtitle_artifact_id": (
                                subtitle_export.artifact.id if subtitle_export else None
                            ),
                            "subtitle_sha256": (
                                subtitle_export.artifact.sha256 if subtitle_export else None
                            ),
                            "source_job_id": job.source_job_id,
                        },
                    )
                )
            self.store.complete(job.id, final_path, artifact_id)
        except AudiogramRenderCancelled:
            temporary_path.unlink(missing_ok=True)
            self.store.mark_cancelled(job.id)
        except asyncio.CancelledError:
            temporary_path.unlink(missing_ok=True)
            raise
        except Exception as error:
            temporary_path.unlink(missing_ok=True)
            self.store.fail(job.id, "render_failed", str(error))
    @staticmethod
    def _wav_duration(path: Path) -> float:
        with wave.open(str(path), "rb") as wav_file:
            if wav_file.getframerate() <= 0:
                raise ValueError("source audio has an invalid sample rate")
            return wav_file.getnframes() / wav_file.getframerate()

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()
