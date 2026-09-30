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
import zipfile
from collections.abc import Callable
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from ..domain import JobStatus, utc_now
from ..storage import LocalJobStorage
from ..store import SqliteJobStore
from .domain import Artifact, ArtifactKind
from .audiogram_expressions import (
    AudiogramExpressionError,
    compile_expression,
    resolve_numeric,
    sample_context,
)
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
    WEBM_ALPHA = "webm_alpha"
    PRORES_4444 = "prores_4444"
    PNG_SEQUENCE = "png_sequence"


class AudiogramBackgroundMode(StrEnum):
    SOLID = "solid"
    IMAGE = "image"
    TRANSPARENT = "transparent"


class AudiogramBackgroundFit(StrEnum):
    COVER = "cover"
    CONTAIN = "contain"
    STRETCH = "stretch"


class AudiogramGeometry(StrEnum):
    LINEAR = "linear"
    POLAR = "polar"


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
class AudiogramBackgroundAsset:
    id: str
    name: str
    media_type: str
    path: str
    size_bytes: int
    sha256: str
    created_at: str


@dataclass(frozen=True, slots=True)
class AudiogramLayout:
    canvas_width: int
    canvas_height: int
    visualizer_x: int
    visualizer_y: int
    visualizer_width: int
    visualizer_height: int
    geometry: AudiogramGeometry
    center_x: int
    center_y: int
    inner_radius: int
    outer_radius: int
    pivot_x: int
    pivot_y: int
    rotation: float
    opacity: float
    line_width: float
    show_bars: bool
    show_line: bool
    mirror: bool
    smoothing: float
    bar_count: int
    animated: bool
    background_mode: AudiogramBackgroundMode
    background_fit: AudiogramBackgroundFit
    background_position_x: float
    background_position_y: float

    def to_mapping(self) -> dict[str, object]:
        return asdict(self)


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
    background_mode: AudiogramBackgroundMode = AudiogramBackgroundMode.SOLID
    background_asset_id: str | None = None
    background_fit: AudiogramBackgroundFit = AudiogramBackgroundFit.COVER
    background_position_x: float = 0.5
    background_position_y: float = 0.5
    geometry: AudiogramGeometry = AudiogramGeometry.LINEAR
    show_bars: bool = True
    show_line: bool = False
    bar_count: int = 96
    bar_width: float = 0.7
    mirror: bool = True
    smoothing: float = 0.0
    linear_x: float | str = 0.0
    linear_y: float | str | None = None
    linear_width: float | str = 1.0
    linear_height: float | str | None = None
    center_x: float | str = 0.5
    center_y: float | str = 0.5
    inner_radius: float | str = 0.18
    outer_radius: float | str = 0.34
    pivot_x: float | str = 0.5
    pivot_y: float | str = 0.5
    rotation: float | str = 0.0
    opacity: float | str = 0.92
    line_width: float | str = 3.0
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
        if not 0 <= self.background_position_x <= 1:
            raise ValueError("background_position_x must be between 0 and 1")
        if not 0 <= self.background_position_y <= 1:
            raise ValueError("background_position_y must be between 0 and 1")
        if not 2 <= self.bar_count <= 512:
            raise ValueError("bar_count must be between 2 and 512")
        if not 0.05 <= self.bar_width <= 1:
            raise ValueError("bar_width must be between 0.05 and 1")
        if not 0 <= self.smoothing <= 0.95:
            raise ValueError("smoothing must be between 0 and 0.95")
        if not self.show_bars and not self.show_line:
            raise ValueError("at least one of show_bars or show_line must be enabled")
        for field_name in (
            "linear_x",
            "linear_y",
            "linear_width",
            "linear_height",
            "center_x",
            "center_y",
            "inner_radius",
            "outer_radius",
            "pivot_x",
            "pivot_y",
            "rotation",
            "opacity",
            "line_width",
        ):
            value = getattr(self, field_name)
            if isinstance(value, str):
                try:
                    compile_expression(value)
                except AudiogramExpressionError as error:
                    raise ValueError(f"{field_name}: {error}") from error
        if self.background_mode is AudiogramBackgroundMode.IMAGE and not self.background_asset_id:
            raise ValueError("image backgrounds require background_asset_id")
        if self.background_mode is not AudiogramBackgroundMode.IMAGE and self.background_asset_id:
            raise ValueError("only image backgrounds can reference a background asset")
        alpha_formats = {
            AudiogramOutputFormat.WEBM_ALPHA,
            AudiogramOutputFormat.PRORES_4444,
            AudiogramOutputFormat.PNG_SEQUENCE,
        }
        if self.background_mode is AudiogramBackgroundMode.TRANSPARENT:
            if self.output_format not in alpha_formats:
                raise ValueError("transparent backgrounds require an alpha-capable output format")
        elif self.output_format in alpha_formats:
            raise ValueError("alpha-capable output formats require a transparent background")
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
        crf_max = (
            63
            if self.output_format in {AudiogramOutputFormat.WEBM, AudiogramOutputFormat.WEBM_ALPHA}
            else 51
        )
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
                "background_mode": AudiogramBackgroundMode(
                    str(value.get("background_mode", "solid"))
                ),
                "background_fit": AudiogramBackgroundFit(str(value.get("background_fit", "cover"))),
                "geometry": AudiogramGeometry(str(value.get("geometry", "linear"))),
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


class AudiogramBackgroundError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class AudiogramBackgroundStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path)
        self._lock = threading.RLock()

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS studio_audiogram_backgrounds (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    path TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_studio_audiogram_backgrounds_created
                    ON studio_audiogram_backgrounds(created_at DESC);
                """
            )

    def add(self, asset: AudiogramBackgroundAsset) -> AudiogramBackgroundAsset:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO studio_audiogram_backgrounds (
                    id, name, media_type, path, size_bytes, sha256, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    asset.id,
                    asset.name,
                    asset.media_type,
                    asset.path,
                    asset.size_bytes,
                    asset.sha256,
                    asset.created_at,
                ),
            )
        return asset

    def get(self, asset_id: str) -> AudiogramBackgroundAsset:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM studio_audiogram_backgrounds WHERE id = ?",
                (asset_id,),
            ).fetchone()
        if row is None:
            raise AudiogramBackgroundError("background_not_found", "background image not found")
        return self._from_row(row)

    def list(self) -> list[AudiogramBackgroundAsset]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM studio_audiogram_backgrounds ORDER BY created_at DESC"
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _from_row(row: sqlite3.Row) -> AudiogramBackgroundAsset:
        return AudiogramBackgroundAsset(
            id=str(row["id"]),
            name=str(row["name"]),
            media_type=str(row["media_type"]),
            path=str(row["path"]),
            size_bytes=int(row["size_bytes"]),
            sha256=str(row["sha256"]),
            created_at=str(row["created_at"]),
        )


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


def resolve_layout(
    spec: AudiogramSpec,
    context: dict[str, float] | None = None,
) -> AudiogramLayout:
    resolved_context = context or sample_context(fps=float(spec.fps))
    animated_values = (
        spec.linear_x,
        spec.linear_y,
        spec.linear_width,
        spec.linear_height,
        spec.center_x,
        spec.center_y,
        spec.inner_radius,
        spec.outer_radius,
        spec.pivot_x,
        spec.pivot_y,
        spec.rotation,
        spec.opacity,
        spec.line_width,
    )
    animated = any(isinstance(value, str) for value in animated_values)

    def number(value: float | str | None, fallback: float) -> float:
        return resolve_numeric(fallback if value is None else value, resolved_context)

    def bounded(value: float | str | None, fallback: float, low: float, high: float) -> float:
        return max(low, min(high, number(value, fallback)))

    pivot_x = round(bounded(spec.pivot_x, 0.5, 0, 1) * spec.width)
    pivot_y = round(bounded(spec.pivot_y, 0.5, 0, 1) * spec.height)
    opacity = bounded(spec.opacity, 0.92, 0, 1)
    line_width = bounded(spec.line_width, 3, 1, 40)
    rotation = bounded(spec.rotation, 0, -36_000, 36_000)
    short_dimension = min(spec.width, spec.height)
    if spec.geometry is AudiogramGeometry.POLAR:
        center_x = round(bounded(spec.center_x, 0.5, 0, 1) * spec.width)
        center_y = round(bounded(spec.center_y, 0.5, 0, 1) * spec.height)
        inner_radius = round(bounded(spec.inner_radius, 0.18, 0, 0.7) * short_dimension)
        outer_radius = round(bounded(spec.outer_radius, 0.34, 0.01, 0.7) * short_dimension)
        outer_radius = max(inner_radius + 1, outer_radius)
        visualizer_x = center_x - outer_radius
        visualizer_y = center_y - outer_radius
        visualizer_width = max(2, outer_radius * 2)
        visualizer_height = visualizer_width
    else:
        fallback_y = (spec.height - spec.visualizer_height) * spec.vertical_position / spec.height
        fallback_height = spec.visualizer_height / spec.height
        x_fraction = bounded(spec.linear_x, 0, 0, 1)
        y_fraction = bounded(spec.linear_y, fallback_y, 0, 1)
        width_fraction = bounded(spec.linear_width, 1, 0.01, 1)
        height_fraction = bounded(spec.linear_height, fallback_height, 0.01, 1)
        width_fraction = min(width_fraction, 1 - x_fraction)
        height_fraction = min(height_fraction, 1 - y_fraction)
        visualizer_x = round(x_fraction * spec.width)
        visualizer_y = round(y_fraction * spec.height)
        visualizer_width = max(2, round(width_fraction * spec.width))
        visualizer_height = max(2, round(height_fraction * spec.height))
        center_x = visualizer_x + visualizer_width // 2
        center_y = visualizer_y + visualizer_height // 2
        inner_radius = 0
        outer_radius = 0

    return AudiogramLayout(
        canvas_width=spec.width,
        canvas_height=spec.height,
        visualizer_x=visualizer_x,
        visualizer_y=visualizer_y,
        visualizer_width=visualizer_width,
        visualizer_height=visualizer_height,
        geometry=spec.geometry,
        center_x=center_x,
        center_y=center_y,
        inner_radius=inner_radius,
        outer_radius=outer_radius,
        pivot_x=pivot_x,
        pivot_y=pivot_y,
        rotation=rotation,
        opacity=opacity,
        line_width=line_width,
        show_bars=spec.show_bars,
        show_line=spec.show_line,
        mirror=spec.mirror,
        smoothing=spec.smoothing,
        bar_count=spec.bar_count,
        animated=animated,
        background_mode=spec.background_mode,
        background_fit=spec.background_fit,
        background_position_x=spec.background_position_x,
        background_position_y=spec.background_position_y,
    )


def requires_frame_renderer(spec: AudiogramSpec) -> bool:
    """Return whether exact drawing is needed instead of FFmpeg's fast visualizer."""
    layout = resolve_layout(spec)
    return bool(
        layout.animated
        or spec.geometry is AudiogramGeometry.POLAR
        or spec.show_line
        or not spec.show_bars
        or not spec.mirror
        or spec.bar_count != 96
        or spec.bar_width != 0.7
        or spec.smoothing
        or layout.rotation
        or layout.line_width != 3
    )


def _background_filter(spec: AudiogramSpec, layout: AudiogramLayout) -> str:
    size = f"{layout.canvas_width}x{layout.canvas_height}"
    if layout.background_mode is AudiogramBackgroundMode.TRANSPARENT:
        return f"color=c=black@0.0:s={size}:r={spec.fps},format=rgba[bg]"
    if layout.background_mode is AudiogramBackgroundMode.SOLID:
        return f"color=c={_ffmpeg_color(spec.background_color)}:s={size}:r={spec.fps}[bg]"
    x = f"{layout.background_position_x:.6f}"
    y = f"{layout.background_position_y:.6f}"
    if layout.background_fit is AudiogramBackgroundFit.STRETCH:
        return f"[1:v]scale={size}:flags=lanczos,fps={spec.fps},format=rgba[bg]"
    if layout.background_fit is AudiogramBackgroundFit.COVER:
        return (
            f"[1:v]scale={size}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={size}:x='(iw-ow)*{x}':y='(ih-oh)*{y}',"
            f"fps={spec.fps},format=rgba[bg]"
        )
    return (
        f"[1:v]scale={size}:force_original_aspect_ratio=decrease:flags=lanczos[bgscaled];"
        f"color=c={_ffmpeg_color(spec.background_color)}:s={size}:r={spec.fps}[bgbase];"
        f"[bgbase][bgscaled]overlay=x='(W-w)*{x}':y='(H-h)*{y}':shortest=1,"
        "format=rgba[bg]"
    )


def build_filter_graph(spec: AudiogramSpec, *, subtitle_path: Path | None = None) -> str:
    layout = resolve_layout(spec)
    size = f"{layout.visualizer_width}x{layout.visualizer_height}"
    color = _ffmpeg_color(spec.foreground_color)
    if spec.source is AudiogramSource.WAVEFORM:
        waveform_mode = spec.waveform_mode
        if spec.show_line and not spec.show_bars:
            waveform_mode = "line"
        elif spec.show_bars and not spec.mirror:
            waveform_mode = "p2p"
        visualizer = (
            f"showwaves=s={size}:mode={waveform_mode}:rate={spec.fps}:"
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
    effects = [visualizer]
    if layout.geometry is AudiogramGeometry.POLAR:
        effects.append("v360=input=flat:output=fisheye:h_fov=360:v_fov=360")
    effects.extend(["format=rgba", "colorkey=0x000000:0.08:0.04"])
    if layout.opacity < 1:
        effects.append(f"colorchannelmixer=aa={layout.opacity:.6f}")
    if layout.smoothing:
        smoothing_frames = max(2, min(12, round(2 + layout.smoothing * 10)))
        effects.append(f"tmix=frames={smoothing_frames}:weights='1'")
    if spec.sharpen:
        effects.append(f"cas=strength={spec.sharpen:.3f}")
    if spec.blur:
        effects.append(f"gblur=sigma={spec.blur:.3f}")
    if spec.trail:
        effects.append("tblend=all_mode=average")
    overlay_x = str(layout.visualizer_x)
    overlay_y = str(layout.visualizer_y)
    if layout.rotation:
        effects.append(f"rotate={layout.rotation:.6f}*PI/180:ow=rotw(iw):oh=roth(ih):c=none")
        overlay_x = f"{layout.visualizer_x}-(w-{layout.visualizer_width})/2"
        overlay_y = f"{layout.visualizer_y}-(h-{layout.visualizer_height})/2"
    composite_format = (
        "rgba" if spec.background_mode is AudiogramBackgroundMode.TRANSPARENT else "yuv420p"
    )
    overlay_format = (
        ":format=auto" if spec.background_mode is AudiogramBackgroundMode.TRANSPARENT else ""
    )
    graph = (
        f"[0:a]aformat=channel_layouts=mono,{','.join(effects)}[viz];"
        f"{_background_filter(spec, layout)};"
        f"[bg][viz]overlay=x='{overlay_x}':y='{overlay_y}':"
        f"shortest=1{overlay_format},format={composite_format}[composite]"
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
    background_path: Path | None = None,
    mp4_video_encoder: str = "libx264",
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
    ]
    if spec.background_mode is AudiogramBackgroundMode.IMAGE:
        if background_path is None:
            raise ValueError("image backgrounds require a managed background file")
        command.extend(["-loop", "1", "-framerate", str(spec.fps), "-i", str(background_path)])
    command.extend(
        [
            "-filter_complex",
            build_filter_graph(spec, subtitle_path=subtitle_path),
            "-map",
            "[v]",
        ]
    )
    if spec.output_format is not AudiogramOutputFormat.PNG_SEQUENCE:
        command.extend(["-map", "0:a:0"])
    command.extend(["-t", f"{render_seconds:.3f}", "-r", str(spec.fps)])

    if spec.output_format is AudiogramOutputFormat.MP4:
        command.extend(_mp4_video_arguments(spec, mp4_video_encoder))
        command.extend(["-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"])
    elif spec.output_format in {
        AudiogramOutputFormat.WEBM,
        AudiogramOutputFormat.WEBM_ALPHA,
    }:
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
            ]
        )
        if spec.output_format is AudiogramOutputFormat.WEBM_ALPHA:
            command.extend(["-pix_fmt", "yuva420p", "-auto-alt-ref", "0"])
        command.extend(["-c:a", "libopus", "-b:a", "160k"])
    elif spec.output_format is AudiogramOutputFormat.PRORES_4444:
        command.extend(
            [
                "-c:v",
                "prores_ks",
                "-profile:v",
                "4",
                "-pix_fmt",
                "yuva444p10le",
                "-c:a",
                "pcm_s16le",
            ]
        )
    else:
        command.extend(["-c:v", "png", "-pix_fmt", "rgba", "-start_number", "0"])

    if spec.output_format is not AudiogramOutputFormat.PNG_SEQUENCE:
        command.append("-shortest")
    command.append(str(output_path))
    return command


def _mp4_video_arguments(spec: AudiogramSpec, encoder: str) -> list[str]:
    if encoder == "libx264":
        return [
            "-c:v",
            encoder,
            "-preset",
            spec.preset,
            "-crf",
            str(spec.crf),
            "-pix_fmt",
            "yuv420p",
        ]
    if encoder == "libopenh264":
        # OpenH264 is bitrate-driven rather than CRF-driven. Preserve the existing quality control
        # as a stable approximation scaled by resolution and frame rate.
        quality_scale = 2 ** ((23 - spec.crf) / 6)
        bitrate = max(
            350_000,
            min(20_000_000, round(spec.width * spec.height * spec.fps * 0.07 * quality_scale)),
        )
        return [
            "-c:v",
            encoder,
            "-rc_mode",
            "bitrate",
            "-b:v",
            str(bitrate),
            "-maxrate",
            str(round(bitrate * 1.5)),
            "-bufsize",
            str(bitrate * 2),
            "-pix_fmt",
            "yuv420p",
        ]
    raise ValueError(f"unsupported MP4 video encoder: {encoder}")


def estimate_render_seconds(spec: AudiogramSpec, audio_seconds: float) -> float:
    layout = resolve_layout(spec)
    pixel_ratio = (layout.canvas_width * layout.canvas_height) / (1920 * 1080)
    fps_ratio = spec.fps / 30
    source_cost = {
        AudiogramSource.WAVEFORM: 0.85,
        AudiogramSource.FREQUENCY: 1.05,
        AudiogramSource.SPECTRUM: 1.2,
        AudiogramSource.VECTORSCOPE: 1.1,
    }[spec.source]
    effects_cost = (
        1
        + min(spec.blur / 20, 0.4)
        + (0.18 if spec.trail else 0)
        + (0.08 if layout.background_mode is AudiogramBackgroundMode.IMAGE else 0)
    )
    renderer_cost = 4.5 if requires_frame_renderer(spec) else 1.0
    return max(
        1.0,
        audio_seconds
        * pixel_ratio
        * fps_ratio
        * _PRESET_COST[spec.preset]
        * source_cost
        * effects_cost
        * renderer_cost,
    )


def audiogram_output_extension(output_format: AudiogramOutputFormat) -> str:
    return {
        AudiogramOutputFormat.MP4: "mp4",
        AudiogramOutputFormat.WEBM: "webm",
        AudiogramOutputFormat.WEBM_ALPHA: "webm",
        AudiogramOutputFormat.PRORES_4444: "mov",
        AudiogramOutputFormat.PNG_SEQUENCE: "zip",
    }[output_format]


def audiogram_media_type(output_format: AudiogramOutputFormat) -> str:
    return {
        AudiogramOutputFormat.MP4: "video/mp4",
        AudiogramOutputFormat.WEBM: "video/webm",
        AudiogramOutputFormat.WEBM_ALPHA: "video/webm",
        AudiogramOutputFormat.PRORES_4444: "video/quicktime",
        AudiogramOutputFormat.PNG_SEQUENCE: "application/zip",
    }[output_format]


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
        background_path: Path | None = None,
        on_progress: ProgressCallback,
        is_cancelled: CancelCallback,
    ) -> None: ...


class FfmpegAudiogramRenderer:
    def __init__(self, executable: str = "ffmpeg") -> None:
        self.executable = executable
        self._supported_output_formats: tuple[AudiogramOutputFormat, ...] | None = None
        self._encoders: str | None = None

    @property
    def available(self) -> bool:
        return shutil.which(self.executable) is not None

    @property
    def supported_output_formats(self) -> tuple[AudiogramOutputFormat, ...]:
        if self._supported_output_formats is not None:
            return self._supported_output_formats
        if not self.available:
            self._supported_output_formats = ()
            return self._supported_output_formats
        encoders = self._encoder_listing
        supported: list[AudiogramOutputFormat] = []
        if self.mp4_video_encoder is not None:
            supported.append(AudiogramOutputFormat.MP4)
        if re.search(r"\blibvpx-vp9\b", encoders):
            supported.extend([AudiogramOutputFormat.WEBM, AudiogramOutputFormat.WEBM_ALPHA])
        if re.search(r"\bprores_ks\b", encoders):
            supported.append(AudiogramOutputFormat.PRORES_4444)
        if re.search(r"\bpng\b", encoders):
            supported.append(AudiogramOutputFormat.PNG_SEQUENCE)
        self._supported_output_formats = tuple(supported)
        return self._supported_output_formats

    @property
    def mp4_video_encoder(self) -> str | None:
        encoders = self._encoder_listing
        for encoder in ("libx264", "libopenh264"):
            if re.search(rf"\b{encoder}\b", encoders):
                return encoder
        return None

    @property
    def _encoder_listing(self) -> str:
        if self._encoders is not None:
            return self._encoders
        if not self.available:
            self._encoders = ""
            return self._encoders
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        result = subprocess.run(
            [self.executable, "-hide_banner", "-encoders"],
            check=False,
            capture_output=True,
            text=True,
            creationflags=creationflags,
        )
        self._encoders = result.stdout + result.stderr
        return self._encoders

    async def render(
        self,
        source_path: Path,
        output_path: Path,
        spec: AudiogramSpec,
        *,
        render_seconds: float,
        subtitle_path: Path | None = None,
        background_path: Path | None = None,
        on_progress: ProgressCallback,
        is_cancelled: CancelCallback,
    ) -> None:
        if not self.available:
            raise AudiogramRenderError(
                "FFmpeg was not found. Install FFmpeg and ensure the ffmpeg command is on PATH."
            )
        if spec.output_format not in self.supported_output_formats:
            raise AudiogramRenderError(
                f"this FFmpeg installation does not support {spec.output_format.value}"
            )
        if requires_frame_renderer(spec):
            from .audiogram_frames import render_advanced_audiogram

            await render_advanced_audiogram(
                self.executable,
                source_path,
                output_path,
                spec,
                render_seconds=render_seconds,
                subtitle_path=subtitle_path,
                background_path=background_path,
                mp4_video_encoder=self.mp4_video_encoder or "libx264",
                on_progress=on_progress,
                is_cancelled=is_cancelled,
            )
            return
        output_path.parent.mkdir(parents=True, exist_ok=True)
        frames_dir: Path | None = None
        render_target = output_path
        if spec.output_format is AudiogramOutputFormat.PNG_SEQUENCE:
            frames_dir = output_path.parent / f".{output_path.name}.frames"
            shutil.rmtree(frames_dir, ignore_errors=True)
            frames_dir.mkdir(parents=True)
            render_target = frames_dir / "frame-%08d.png"
        command = build_ffmpeg_command(
            self.executable,
            source_path,
            render_target,
            spec,
            render_seconds=render_seconds,
            subtitle_path=subtitle_path,
            background_path=background_path,
            mp4_video_encoder=self.mp4_video_encoder or "libx264",
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
            if frames_dir is not None:
                shutil.rmtree(frames_dir, ignore_errors=True)
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
                raise AudiogramRenderError(
                    stderr[-8_000:] or f"FFmpeg exited with code {process.returncode}"
                )
            if frames_dir is not None:
                frames = sorted(frames_dir.glob("frame-*.png"))
                if not frames:
                    raise AudiogramRenderError(
                        "FFmpeg completed without producing PNG sequence frames"
                    )
                manifest = json.dumps(
                    {
                        "format": "splicr-png-sequence-v1",
                        "fps": spec.fps,
                        "width": spec.width,
                        "height": spec.height,
                        "frame_count": len(frames),
                        "render_seconds": render_seconds,
                    },
                    indent=2,
                    sort_keys=True,
                ).encode("utf-8")
                with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as archive:
                    manifest_info = zipfile.ZipInfo(
                        "manifest.json", date_time=(1980, 1, 1, 0, 0, 0)
                    )
                    manifest_info.compress_type = zipfile.ZIP_DEFLATED
                    archive.writestr(manifest_info, manifest)
                    for frame in frames:
                        info = zipfile.ZipInfo(
                            f"frames/{frame.name}", date_time=(1980, 1, 1, 0, 0, 0)
                        )
                        info.compress_type = zipfile.ZIP_DEFLATED
                        archive.writestr(info, frame.read_bytes())
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
        finally:
            if frames_dir is not None:
                shutil.rmtree(frames_dir, ignore_errors=True)


class AudiogramJobService:
    def __init__(
        self,
        *,
        store: AudiogramJobStore,
        source_store: SqliteJobStore,
        source_storage: LocalJobStorage,
        studio_store: SqliteStudioStore,
        output_root: Path,
        background_root: Path | None = None,
        background_store: AudiogramBackgroundStore | None = None,
        subtitle_service: SubtitleService | None = None,
        renderer: AudiogramRenderer | None = None,
        max_background_bytes: int = 25_000_000,
    ) -> None:
        self.store = store
        self.source_store = source_store
        self.source_storage = source_storage
        self.studio_store = studio_store
        self.output_root = Path(output_root)
        self.background_root = Path(
            background_root or self.output_root.parent / "audiogram-backgrounds"
        )
        self.background_store = background_store or AudiogramBackgroundStore(store.database_path)
        self.subtitle_service = subtitle_service
        self.renderer = renderer or FfmpegAudiogramRenderer()
        self.max_background_bytes = max_background_bytes
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None

    @property
    def ffmpeg_available(self) -> bool:
        return self.renderer.available

    @property
    def supported_output_formats(self) -> tuple[AudiogramOutputFormat, ...]:
        formats = getattr(self.renderer, "supported_output_formats", None)
        return tuple(formats) if formats is not None else tuple(AudiogramOutputFormat)

    async def start(self) -> None:
        if self._worker is not None:
            return
        self.store.initialize()
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.background_store.initialize()
        self.background_root.mkdir(parents=True, exist_ok=True)
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
            path = (
                Path(source.output_path)
                if source.output_path
                else self.source_storage.output_path(source.id)
            )
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

    def register_background(self, name: str, payload: bytes) -> AudiogramBackgroundAsset:
        if not payload:
            raise AudiogramBackgroundError("empty_background", "background image is empty")
        if len(payload) > self.max_background_bytes:
            raise AudiogramBackgroundError(
                "background_too_large",
                f"background image exceeds the {self.max_background_bytes}-byte upload limit",
            )
        media_type, extension = self._detect_image(payload)
        asset_id = uuid.uuid4().hex
        directory = self.background_root / asset_id
        final_path = directory / f"source.{extension}"
        temporary_path = directory / f".source.{uuid.uuid4().hex}.part"
        directory.mkdir(parents=True, exist_ok=True)
        temporary_path.write_bytes(payload)
        os.replace(temporary_path, final_path)
        asset = AudiogramBackgroundAsset(
            id=asset_id,
            name=Path(name).name or f"background.{extension}",
            media_type=media_type,
            path=str(final_path.resolve()),
            size_bytes=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
            created_at=utc_now(),
        )
        try:
            return self.background_store.add(asset)
        except Exception:
            final_path.unlink(missing_ok=True)
            raise

    def background_path(self, asset_id: str) -> Path:
        asset = self.background_store.get(asset_id)
        path = Path(asset.path)
        if not path.is_file():
            raise AudiogramBackgroundError(
                "background_file_missing", "managed background image file is missing"
            )
        return path

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
        if spec.output_format not in self.supported_output_formats:
            raise AudiogramRenderError(
                f"this FFmpeg installation does not support {spec.output_format.value}"
            )
        if (
            kind is AudiogramJobKind.PREVIEW
            and spec.output_format is AudiogramOutputFormat.PNG_SEQUENCE
        ):
            raise ValueError("PNG sequences use the live canvas preview and full export only")
        if spec.burn_captions and self.subtitle_service is None:
            raise AudiogramRenderError("caption burn-in is not configured")
        if spec.background_mode is AudiogramBackgroundMode.IMAGE:
            self.background_path(spec.background_asset_id or "")
        source = self.source_store.get_job(source_job_id)
        if source.status is not JobStatus.COMPLETED:
            raise ValueError("audiograms require a completed narration take")
        source_path = (
            Path(source.output_path)
            if source.output_path
            else self.source_storage.output_path(source.id)
        )
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
        source_path = (
            Path(source.output_path)
            if source.output_path
            else self.source_storage.output_path(source.id)
        )
        extension = audiogram_output_extension(job.spec.output_format)
        directory = self.output_root / job.id
        final_path = directory / f"{job.kind.value}.{extension}"
        temporary_path = directory / f".{job.kind.value}.{uuid.uuid4().hex}.part.{extension}"
        temporary_path.parent.mkdir(parents=True, exist_ok=True)
        final_path.unlink(missing_ok=True)
        last_reported = -1.0
        subtitle_export = None
        subtitle_path = None
        background_path = None

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
            if job.spec.background_mode is AudiogramBackgroundMode.IMAGE:
                background_path = self.background_path(job.spec.background_asset_id or "")
            await self.renderer.render(
                source_path,
                temporary_path,
                job.spec,
                render_seconds=job.render_seconds,
                subtitle_path=subtitle_path,
                background_path=background_path,
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
                        media_type=audiogram_media_type(job.spec.output_format),
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
    def _detect_image(payload: bytes) -> tuple[str, str]:
        if payload.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png", "png"
        if payload.startswith(b"\xff\xd8\xff"):
            return "image/jpeg", "jpg"
        if payload.startswith(b"RIFF") and payload[8:12] == b"WEBP":
            return "image/webp", "webp"
        raise AudiogramBackgroundError(
            "unsupported_background",
            "background image must be a PNG, JPEG, or WebP file",
        )

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
