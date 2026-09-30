from __future__ import annotations

import asyncio
import contextlib
import json
import math
import os
import shutil
import subprocess
import wave
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

if TYPE_CHECKING:
    from .audiogram import AudiogramSpec


ProgressCallback = Callable[[float], None]
CancelCallback = Callable[[], bool]


def _read_wave(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as stream:
        channels = stream.getnchannels()
        sample_width = stream.getsampwidth()
        sample_rate = stream.getframerate()
        raw = stream.readframes(stream.getnframes())
    if sample_width == 1:
        samples = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128) / 128
    elif sample_width == 2:
        samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768
    elif sample_width == 4:
        samples = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648
    else:
        raise ValueError(f"advanced audiograms do not support {sample_width * 8}-bit WAV input")
    if channels > 1:
        samples = samples.reshape((-1, channels)).mean(axis=1)
    return samples, sample_rate


def analyse_frames(
    source_path: Path,
    *,
    fps: int,
    bands: int,
    smoothing: float,
    render_seconds: float,
) -> np.ndarray:
    """Return normalized log-frequency energy for every requested video frame."""
    mono, sample_rate = _read_wave(source_path)
    total = max(1, int(math.ceil(render_seconds * fps)))
    hop = max(1, round(sample_rate / fps))
    window_size = min(len(mono), max(1024, hop * 2))
    if window_size < 2:
        return np.zeros((total, bands), dtype=np.float32)
    window = np.hanning(window_size).astype(np.float32)
    edges = np.geomspace(1, window_size // 2 + 1, bands + 1).astype(int)
    rows = np.zeros((total, bands), dtype=np.float32)
    for frame in range(total):
        start = frame * hop
        segment = mono[start : start + window_size]
        if len(segment) < window_size:
            segment = np.pad(segment, (0, window_size - len(segment)))
        spectrum = np.abs(np.fft.rfft(segment * window))
        for band in range(bands):
            low = min(len(spectrum) - 1, max(1, int(edges[band])))
            high = min(len(spectrum), max(low + 1, int(edges[band + 1])))
            rows[frame, band] = float(spectrum[low:high].mean())
    peak = float(rows.max()) or 1.0
    rows = np.sqrt(rows / peak)
    amount = max(0.0, min(0.95, smoothing))
    if amount:
        for frame in range(1, len(rows)):
            rows[frame] = amount * rows[frame - 1] + (1 - amount) * rows[frame]
    return rows


def _rgba(color: str, opacity: float = 1.0) -> tuple[int, int, int, int]:
    value = color.removeprefix("#")
    red, green, blue = (int(value[index : index + 2], 16) for index in (0, 2, 4))
    return red, green, blue, round(max(0, min(1, opacity)) * 255)


def _background(spec: AudiogramSpec, background_path: Path | None) -> Image.Image:
    from .audiogram import AudiogramBackgroundFit, AudiogramBackgroundMode

    size = (spec.width, spec.height)
    if spec.background_mode is AudiogramBackgroundMode.TRANSPARENT:
        return Image.new("RGBA", size, (0, 0, 0, 0))
    base = Image.new("RGBA", size, _rgba(spec.background_color))
    if spec.background_mode is not AudiogramBackgroundMode.IMAGE:
        return base
    if background_path is None:
        raise ValueError("image backgrounds require a managed background file")
    with Image.open(background_path) as opened:
        image = opened.convert("RGBA")
    if spec.background_fit is AudiogramBackgroundFit.STRETCH:
        return image.resize(size, Image.Resampling.LANCZOS)
    factor = (
        max(spec.width / image.width, spec.height / image.height)
        if spec.background_fit is AudiogramBackgroundFit.COVER
        else min(spec.width / image.width, spec.height / image.height)
    )
    resized = image.resize(
        (max(1, round(image.width * factor)), max(1, round(image.height * factor))),
        Image.Resampling.LANCZOS,
    )
    x = round((spec.width - resized.width) * spec.background_position_x)
    y = round((spec.height - resized.height) * spec.background_position_y)
    if spec.background_fit is AudiogramBackgroundFit.COVER:
        return resized.crop((-x, -y, -x + spec.width, -y + spec.height))
    base.alpha_composite(resized, (x, y))
    return base


def frame_context(
    index: int, total: int, fps: int, duration: float, values: np.ndarray
) -> dict[str, float]:
    thirds = np.array_split(values, 3)
    level = float(values.mean())

    def mean_or_level(part: np.ndarray) -> float:
        return float(part.mean()) if part.size else level

    return {
        "t": index / fps,
        "duration": duration,
        "progress": index / max(1, total - 1),
        "frame": float(index),
        "fps": float(fps),
        "level": level,
        "bass": mean_or_level(thirds[0]),
        "mid": mean_or_level(thirds[1]),
        "treble": mean_or_level(thirds[2]),
    }


def draw_frame(
    values: np.ndarray,
    spec: AudiogramSpec,
    *,
    context: dict[str, float],
    background: Image.Image,
    previous_overlay: Image.Image | None = None,
) -> tuple[Image.Image, Image.Image]:
    from .audiogram import AudiogramGeometry, resolve_layout

    layout = resolve_layout(spec, context)
    overlay = Image.new("RGBA", (spec.width, spec.height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    paint = _rgba(spec.foreground_color, layout.opacity)
    count = len(values)
    width = max(1, round(layout.line_width))
    if layout.geometry is AudiogramGeometry.POLAR:
        span = layout.outer_radius - layout.inner_radius
        middle = (layout.inner_radius + layout.outer_radius) / 2
        starts: list[tuple[float, float]] = []
        tips: list[tuple[float, float]] = []
        for index, value in enumerate(values):
            angle = math.tau * index / count - math.pi / 2
            if layout.mirror:
                start_radius = middle - float(value) * span / 2
                end_radius = middle + float(value) * span / 2
            else:
                start_radius = layout.inner_radius
                end_radius = layout.inner_radius + float(value) * span
            starts.append(
                (
                    layout.center_x + start_radius * math.cos(angle),
                    layout.center_y + start_radius * math.sin(angle),
                )
            )
            tips.append(
                (
                    layout.center_x + end_radius * math.cos(angle),
                    layout.center_y + end_radius * math.sin(angle),
                )
            )
        if layout.show_bars:
            for start, tip in zip(starts, tips, strict=True):
                draw.line((start, tip), fill=paint, width=width)
        if layout.show_line and len(tips) > 1:
            draw.line(tips + [tips[0]], fill=paint, width=width, joint="curve")
    else:
        step = layout.visualizer_width / count
        baseline = (
            layout.visualizer_y + layout.visualizer_height / 2
            if layout.mirror
            else layout.visualizer_y + layout.visualizer_height
        )
        reach = layout.visualizer_height / 2 if layout.mirror else layout.visualizer_height
        tips = [
            (
                layout.visualizer_x + (index + 0.5) * step,
                baseline - float(value) * reach,
            )
            for index, value in enumerate(values)
        ]
        if layout.show_bars:
            bar_width = max(1, round(step * spec.bar_width))
            for x, y in tips:
                bottom = baseline + (baseline - y) if layout.mirror else baseline
                draw.rectangle((x - bar_width / 2, y, x + bar_width / 2, bottom), fill=paint)
        if layout.show_line and len(tips) > 1:
            draw.line(tips, fill=paint, width=width, joint="curve")
            if layout.mirror:
                draw.line(
                    [(x, baseline + (baseline - y)) for x, y in tips],
                    fill=paint,
                    width=width,
                    joint="curve",
                )
    if layout.rotation:
        overlay = overlay.rotate(
            -layout.rotation,
            resample=Image.Resampling.BICUBIC,
            center=(layout.pivot_x, layout.pivot_y),
        )
    if spec.blur:
        overlay = overlay.filter(ImageFilter.GaussianBlur(spec.blur))
    if spec.sharpen:
        overlay = ImageEnhance.Sharpness(overlay).enhance(1 + spec.sharpen * 2)
    if spec.trail and previous_overlay is not None:
        overlay = Image.blend(previous_overlay, overlay, 0.65)
    frame = background.copy()
    frame.alpha_composite(overlay)
    return frame, overlay


def _video_command(
    executable: str,
    source_path: Path,
    target: Path,
    spec: AudiogramSpec,
    *,
    render_seconds: float,
    subtitle_path: Path | None,
    mp4_video_encoder: str = "libx264",
) -> list[str]:
    from .audiogram import AudiogramOutputFormat, _ffmpeg_subtitle_path, _mp4_video_arguments

    command = [
        executable,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgba",
        "-s",
        f"{spec.width}x{spec.height}",
        "-r",
        str(spec.fps),
        "-i",
        "pipe:0",
    ]
    if spec.output_format is not AudiogramOutputFormat.PNG_SEQUENCE:
        command.extend(["-i", str(source_path), "-map", "0:v:0", "-map", "1:a:0"])
    else:
        command.extend(["-map", "0:v:0"])
    if subtitle_path is not None:
        command.extend(
            [
                "-vf",
                f"subtitles=filename='{_ffmpeg_subtitle_path(subtitle_path)}':force_style='Alignment=2,MarginV=28,Outline=2,Shadow=1'",
            ]
        )
    command.extend(["-t", f"{render_seconds:.3f}", "-r", str(spec.fps)])
    if spec.output_format is AudiogramOutputFormat.MP4:
        command.extend(_mp4_video_arguments(spec, mp4_video_encoder))
        command.extend(
            ["-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest"]
        )
    elif spec.output_format in {AudiogramOutputFormat.WEBM, AudiogramOutputFormat.WEBM_ALPHA}:
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
        command.extend(["-c:a", "libopus", "-b:a", "160k", "-shortest"])
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
                "-shortest",
            ]
        )
    else:
        command.extend(["-c:v", "png", "-pix_fmt", "rgba", "-start_number", "0"])
    command.append(str(target))
    return command


def _archive_frames(
    output_path: Path, frames_dir: Path, spec: AudiogramSpec, duration: float
) -> None:
    frames = sorted(frames_dir.glob("frame-*.png"))
    if not frames:
        raise RuntimeError("FFmpeg completed without producing PNG sequence frames")
    manifest = json.dumps(
        {
            "format": "splicr-png-sequence-v1",
            "fps": spec.fps,
            "width": spec.width,
            "height": spec.height,
            "frame_count": len(frames),
            "render_seconds": duration,
        },
        indent=2,
        sort_keys=True,
    ).encode()
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as archive:
        info = zipfile.ZipInfo("manifest.json", date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, manifest)
        for frame in frames:
            info = zipfile.ZipInfo(f"frames/{frame.name}", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, frame.read_bytes())


def _render_sync(
    executable: str,
    source_path: Path,
    output_path: Path,
    spec: AudiogramSpec,
    *,
    render_seconds: float,
    subtitle_path: Path | None,
    background_path: Path | None,
    mp4_video_encoder: str,
    on_progress: ProgressCallback,
    is_cancelled: CancelCallback,
) -> None:
    from .audiogram import AudiogramOutputFormat, AudiogramRenderCancelled, AudiogramRenderError

    output_path.parent.mkdir(parents=True, exist_ok=True)
    frames_dir: Path | None = None
    target = output_path
    if spec.output_format is AudiogramOutputFormat.PNG_SEQUENCE:
        frames_dir = output_path.parent / f".{output_path.name}.frames"
        shutil.rmtree(frames_dir, ignore_errors=True)
        frames_dir.mkdir(parents=True)
        target = frames_dir / "frame-%08d.png"
    rows = analyse_frames(
        source_path,
        fps=spec.fps,
        bands=spec.bar_count,
        smoothing=spec.smoothing,
        render_seconds=render_seconds,
    )
    base = _background(spec, background_path)
    command = _video_command(
        executable,
        source_path,
        target,
        spec,
        render_seconds=render_seconds,
        subtitle_path=subtitle_path,
        mp4_video_encoder=mp4_video_encoder,
    )
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        creationflags=creationflags,
    )
    previous_overlay: Image.Image | None = None
    try:
        if process.stdin is None:
            raise AudiogramRenderError("FFmpeg did not expose its frame input")
        for index, values in enumerate(rows):
            if is_cancelled():
                raise AudiogramRenderCancelled
            context = frame_context(index, len(rows), spec.fps, render_seconds, values)
            frame, previous_overlay = draw_frame(
                values, spec, context=context, background=base, previous_overlay=previous_overlay
            )
            process.stdin.write(frame.tobytes())
            if index % max(1, spec.fps // 4) == 0:
                on_progress(min(0.995, (index + 1) / len(rows)))
        process.stdin.close()
        stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
        if process.wait() != 0:
            raise AudiogramRenderError(
                stderr[-8_000:] or f"FFmpeg exited with code {process.returncode}"
            )
        if frames_dir is not None:
            _archive_frames(output_path, frames_dir, spec, render_seconds)
        on_progress(1.0)
    except (BrokenPipeError, OSError) as error:
        stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
        raise AudiogramRenderError(stderr[-8_000:] or str(error)) from error
    except BaseException:
        if process.poll() is None:
            process.terminate()
            with contextlib.suppress(Exception):
                process.wait(timeout=3)
            if process.poll() is None:
                process.kill()
        raise
    finally:
        if process.stdin and not process.stdin.closed:
            with contextlib.suppress(Exception):
                process.stdin.close()
        if process.stderr:
            process.stderr.close()
        if frames_dir is not None:
            shutil.rmtree(frames_dir, ignore_errors=True)


async def render_advanced_audiogram(
    executable: str,
    source_path: Path,
    output_path: Path,
    spec: AudiogramSpec,
    *,
    render_seconds: float,
    subtitle_path: Path | None,
    background_path: Path | None,
    mp4_video_encoder: str = "libx264",
    on_progress: ProgressCallback,
    is_cancelled: CancelCallback,
) -> None:
    await asyncio.to_thread(
        _render_sync,
        executable,
        source_path,
        output_path,
        spec,
        render_seconds=render_seconds,
        subtitle_path=subtitle_path,
        background_path=background_path,
        mp4_video_encoder=mp4_video_encoder,
        on_progress=on_progress,
        is_cancelled=is_cancelled,
    )
