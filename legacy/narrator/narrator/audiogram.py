"""Audiogram rendering: the animated waveform, drawn to a transparent
overlay so an editor only has to composite it.

Why this doesn't use ffmpeg's `showwaves`: that filter is linear only.
Wrapping a waveform into a ring, moving it, resizing it, or pivoting it
are not things it can express. Rendering the frames here instead makes
every one of those an ordinary parameter -- and since the result is baked,
the parameters are exactly what needs to be adjustable BEFORE baking.

Output is RGBA with real transparency (ProRes 4444, or a PNG sequence),
so the editor composites a finished clip rather than recomputing a
waveform every frame. That is the part that makes a Fusion/Reactor
audiogram slow.

`layout()` is deliberately shared with the preview in the UI, so what the
mockup draws and what gets rendered can't disagree.
"""

import math
import os
import subprocess

from .config import _no_window, have_ffmpeg
from .audio import duration_of
from . import expressions as expr

# Parameters that may be a formula instead of a number. Deliberately not
# every setting: `bars` fixes the shape of the analysis array and `fps`
# fixes the frame count, so both must stay constant for a render.
ANIMATABLE = ("x", "y", "width", "height", "center_x", "center_y",
              "inner_radius", "outer_radius", "pivot_x", "pivot_y",
              "rotation", "opacity", "line_width")


def frame_context(cfg, frame_index, total_frames, row=None):
    """The variables a formula sees for one frame. `row` is that frame's
    band magnitudes, which is what makes level/bass/mid/treble reactive
    rather than merely time-based."""
    fps = max(1, int(cfg.get("fps", 30)))
    duration = total_frames / fps if fps else 0.0
    t = frame_index / fps if fps else 0.0
    ctx = {
        "t": t, "duration": duration,
        "progress": (frame_index / (total_frames - 1))
                    if total_frames > 1 else 0.0,
        "frame": frame_index, "fps": fps,
        "pi": math.pi, "tau": math.tau, "e": math.e,
        "level": 0.0, "bass": 0.0, "mid": 0.0, "treble": 0.0,
    }
    if row is not None and len(row):
        n = len(row)
        third = max(1, n // 3)
        ctx["level"] = float(sum(row) / n)
        ctx["bass"] = float(sum(row[:third]) / third)
        ctx["mid"] = float(sum(row[third:2 * third]) / max(1, third))
        ctx["treble"] = float(sum(row[2 * third:]) / max(1, n - 2 * third))
    return ctx


def resolved_cfg(cfg, context):
    """cfg with every animatable formula evaluated for this frame. Values
    that are already numbers are untouched, so a layout with no formulas
    costs nothing."""
    if not any(expr.is_expression(cfg.get(k)) for k in ANIMATABLE):
        return cfg
    out = dict(cfg)
    for key in ANIMATABLE:
        value = cfg.get(key)
        if expr.is_expression(value):
            out[key] = expr.resolve(value, context, DEFAULTS.get(key, 0.0))
    return out

# Everything adjustable, with defaults. Fractions are of the frame, so a
# layout keeps working if the output resolution changes.
DEFAULTS = {
    "geometry": "linear",     # "linear" | "polar"
    # Independent layers rather than one exclusive style, so bars, a line
    # through the tips and a shaded fill can be combined, each with its
    # own colour.
    "show_bars": True,
    "show_line": False,
    "show_fill": False,
    "style": "bars",          # legacy single-style field; still honoured
                              # for layouts saved before the toggles
    "line_color": "",         # blank means "same as the main colour"
    "fill_color": "",
    "fill_opacity": 0.35,
    "bars": 64,
    "bar_width": 0.6,         # fraction of each bar's slot actually drawn
    "fps": 30,
    # Linear: the box the waveform is drawn in.
    "x": 0.0, "y": 0.72, "width": 1.0, "height": 0.22,
    # Polar: ring centre and radii (fractions of the SHORTER frame side
    # for radii, of the frame for the centre).
    "center_x": 0.5, "center_y": 0.5,
    "inner_radius": 0.18, "outer_radius": 0.34,
    # Pivot for rotation, as a fraction of the frame. Defaults to the
    # centre; moving it lets the whole figure swing about another point.
    "pivot_x": 0.5, "pivot_y": 0.5,
    "rotation": 0.0,          # degrees
    "mirror": True,           # bars grow both ways from the baseline
    "color": "#FFFFFF",
    "opacity": 0.9,
    "line_width": 3,
    "smoothing": 0.35,        # 0 = raw and jittery, 1 = very smooth
    # Which audio drives the waveform. Blank means "whatever take is
    # selected". Set it to point the audiogram at a different file from
    # the one that will end up in the video -- a mono mixdown, a single
    # stem, or a music bed.
    "audio_source": "",
    # Only used by the ffmpeg fast path.
    "sharpen": 0.0,           # cas strength, 0 disables
    "blur": 0.0,              # gblur sigma, 0 disables
    "trail": False,           # blend successive frames for a motion trail
}

CODECS = {
    "prores": {
        "label": "ProRes 4444 (.mov) -- transparent, best for editors",
        "ext": ".mov",
        "args": ["-c:v", "prores_ks", "-profile:v", "4444",
                 "-pix_fmt", "yuva444p10le", "-alpha_bits", "8"],
    },
    "webm": {
        "label": "VP9 (.webm) -- transparent, much smaller files",
        "ext": ".webm",
        "args": ["-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p",
                 "-b:v", "0", "-crf", "30"],
    },
    "png": {
        "label": "PNG sequence -- transparent, largest, most portable",
        "ext": "",
        "args": None,   # handled separately: frames written as files
    },
}


def config_with_defaults(saved=None):
    """DEFAULTS overlaid with saved settings. Values are kept exactly as
    stored -- a formula stays a string here and is only turned into a
    number by resolved_cfg(), once per frame."""
    cfg = dict(DEFAULTS)
    for key, value in (saved or {}).items():
        if key in DEFAULTS:
            cfg[key] = value
    return cfg


# --- geometry ---------------------------------------------------------------


def layout(cfg, width, height, context=None):
    """Resolve fractional settings into pixels. Shared by the renderer and
    the preview so the mockup can't drift from the real output.

    Any animatable value that is still a formula is evaluated against
    `context` (or a representative sample one), so a layout containing
    formulas can always be drawn -- the preview and the crop estimate both
    depend on that.
    """
    cfg = resolved_cfg(config_with_defaults(cfg),
                       context or expr.sample_context())
    short = min(width, height)
    out = {
        "geometry": cfg["geometry"],
        "pivot": (cfg["pivot_x"] * width, cfg["pivot_y"] * height),
        "rotation": float(cfg["rotation"]),
        "bars": max(2, int(cfg["bars"])),
        "mirror": bool(cfg["mirror"]),
        "style": cfg["style"],
        "line_width": max(1, int(cfg["line_width"])),
        "layers": active_layers(cfg),
    }
    if cfg["geometry"] == "polar":
        out["center"] = (cfg["center_x"] * width, cfg["center_y"] * height)
        out["inner_r"] = cfg["inner_radius"] * short
        out["outer_r"] = max(cfg["outer_radius"] * short,
                            cfg["inner_radius"] * short + 1)
        r = out["outer_r"]
        cx, cy = out["center"]
        out["box"] = (cx - r, cy - r, cx + r, cy + r)
    else:
        x0, y0 = cfg["x"] * width, cfg["y"] * height
        out["box"] = (x0, y0, x0 + cfg["width"] * width,
                     y0 + cfg["height"] * height)
        out["center"] = ((out["box"][0] + out["box"][2]) / 2,
                        (out["box"][1] + out["box"][3]) / 2)
    return out


def active_layers(cfg):
    """Which layers to draw.

    A layout saved before the toggles existed carries only `style`, so it
    is translated rather than ignored -- an old layout has to keep looking
    the way it did rather than silently rendering nothing.
    """
    cfg = config_with_defaults(cfg)
    if any(cfg.get(k) for k in ("show_bars", "show_line", "show_fill")):
        return {"bars": bool(cfg.get("show_bars")),
                "line": bool(cfg.get("show_line")),
                "fill": bool(cfg.get("show_fill"))}
    return {"bars": cfg.get("style") != "line",
            "line": cfg.get("style") == "line", "fill": False}


def _rgba(color, opacity):
    color = (color or "#FFFFFF").lstrip("#")
    if len(color) == 3:
        color = "".join(c * 2 for c in color)
    try:
        r, g, b = (int(color[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        r = g = b = 255
    return (r, g, b, max(0, min(255, int(round(opacity * 255)))))


# --- analysis ---------------------------------------------------------------


def analyse(audio_path, fps, bands, smoothing=0.35, log=None):
    """Per-frame band magnitudes, each 0..1. One row per video frame, one
    column per bar. Uses a plain STFT: for a waveform display, band
    magnitudes read better than raw samples, and it makes `bars` an
    honest parameter rather than a decimation artefact."""
    import numpy as np
    import soundfile as sf

    data, rate = sf.read(audio_path, dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    total_frames = max(1, int(math.ceil(len(mono) / rate * fps)))
    hop = max(1, int(rate / fps))
    window = min(len(mono), max(hop * 2, 1024))
    win = np.hanning(window).astype("float32")

    rows = np.zeros((total_frames, bands), dtype="float32")
    # Log-spaced edges: linear FFT bins put almost everything in the
    # bottom bar for speech, which looks dead.
    edges = np.unique(np.geomspace(1, window // 2, bands + 1).astype(int))
    while len(edges) < bands + 1:
        edges = np.unique(np.append(edges, edges[-1] + 1))

    for i in range(total_frames):
        start = i * hop
        seg = mono[start:start + window]
        if len(seg) < window:
            seg = np.pad(seg, (0, window - len(seg)))
        spec = np.abs(np.fft.rfft(seg * win))
        for b in range(bands):
            lo, hi = edges[b], max(edges[b] + 1, edges[b + 1])
            rows[i, b] = spec[lo:hi].mean() if hi <= len(spec) else 0.0

    peak = float(rows.max()) or 1.0
    rows = np.sqrt(rows / peak)          # perceptual-ish, not raw power

    if smoothing > 0:
        a = max(0.0, min(0.95, float(smoothing)))
        for i in range(1, len(rows)):
            rows[i] = a * rows[i - 1] + (1 - a) * rows[i]
    if log:
        log(f"  analysed {total_frames} frames x {bands} bands")
    return rows


# --- drawing ----------------------------------------------------------------


def draw_frame(values, cfg, width, height, context=None):
    """One RGBA frame. `values` is one row from analyse()."""
    from PIL import Image, ImageDraw
    cfg = resolved_cfg(config_with_defaults(cfg),
                       context or expr.sample_context())
    geo = layout(cfg, width, height, context)
    fill = _rgba(cfg["color"], cfg["opacity"])

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    n = len(values)
    layers = geo["layers"]
    line_paint = _rgba(cfg["line_color"] or cfg["color"], cfg["opacity"])
    fill_paint = _rgba(cfg["fill_color"] or cfg["color"],
                       cfg["opacity"] * float(cfg["fill_opacity"]))

    if geo["geometry"] == "polar":
        cx, cy = geo["center"]
        inner, outer = geo["inner_r"], geo["outer_r"]
        span = outer - inner
        inners, tips = [], []
        for i, v in enumerate(values):
            ang = 2 * math.pi * i / n - math.pi / 2
            r2 = inner + span * float(v)
            inners.append((cx + inner * math.cos(ang),
                          cy + inner * math.sin(ang)))
            tips.append((cx + r2 * math.cos(ang), cy + r2 * math.sin(ang)))
        # Fill first, so bars and the outline sit on top of it.
        if layers["fill"] and len(tips) > 2:
            draw.polygon(tips + list(reversed(inners)), fill=fill_paint)
        if layers["bars"]:
            for start, end in zip(inners, tips):
                draw.line([start, end], fill=fill, width=geo["line_width"])
        if layers["line"] and len(tips) > 1:
            draw.line(tips + [tips[0]], fill=line_paint,
                     width=geo["line_width"], joint="curve")
    else:
        x0, y0, x1, y1 = geo["box"]
        w, h = x1 - x0, y1 - y0
        base = y0 + h / 2 if geo["mirror"] else y1
        step = w / n
        reach = h / 2 if geo["mirror"] else h
        tops = [(x0 + (i + 0.5) * step, base - float(v) * reach)
               for i, v in enumerate(values)]
        if layers["fill"] and len(tops) > 1:
            draw.polygon(tops + [(tops[-1][0], base), (tops[0][0], base)],
                        fill=fill_paint)
            if geo["mirror"]:
                lower = [(x, base + (base - y)) for x, y in tops]
                draw.polygon(lower + [(lower[-1][0], base),
                                     (lower[0][0], base)], fill=fill_paint)
        if layers["bars"]:
            bw = max(1, int(step * max(0.05, min(1.0,
                                                float(cfg["bar_width"])))))
            for (px, py), _v in zip(tops, values):
                bottom = base + (base - py) if geo["mirror"] else base
                draw.rectangle([px - bw / 2, py, px + bw / 2, bottom],
                              fill=fill)
        if layers["line"] and len(tops) > 1:
            draw.line(tops, fill=line_paint, width=geo["line_width"],
                     joint="curve")
            if geo["mirror"]:
                draw.line([(x, base + (base - y)) for x, y in tops],
                         fill=line_paint, width=geo["line_width"],
                         joint="curve")

    if geo["rotation"]:
        # Rotate about the pivot rather than the image centre, which is
        # what makes the pivot a meaningful control at all.
        img = img.rotate(-geo["rotation"], resample=Image.BICUBIC,
                        center=geo["pivot"])
    return img


# --- export -----------------------------------------------------------------


def crop_box(cfg, width, height, margin=8):
    """The frame-sized region the audiogram actually occupies, snapped to
    even pixels (several codecs require even dimensions). Rendering only
    this instead of the full frame is a large saving: a waveform strip
    across the bottom fifth is about a fifth of the pixels, and every
    frame is otherwise transparent anyway."""
    if any(expr.is_expression(cfg.get(k)) for k in ANIMATABLE):
        # A formula can move or grow the figure anywhere over the run;
        # working out the union of every frame's box is not worth the
        # risk of clipping, so an animated layout renders full-frame.
        return 0, 0, width, height
    geo = layout(cfg, width, height)
    x0, y0, x1, y1 = geo["box"]
    if geo["rotation"]:
        # A rotated figure can swing outside its own box, and working out
        # exactly how far is not worth the risk of clipping it.
        return 0, 0, width, height
    x0 = max(0, int(x0) - margin)
    y0 = max(0, int(y0) - margin)
    x1 = min(width, int(math.ceil(x1)) + margin)
    y1 = min(height, int(math.ceil(y1)) + margin)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return 0, 0, width, height
    x1 -= (x1 - x0) % 2
    y1 -= (y1 - y0) % 2
    return x0, y0, x1, y1


def render_overlay(audio_path, out_path, cfg, log, width=1920, height=1080,
                   codec="webm", progress_every=150, crop=False,
                   max_seconds=None):
    """Render the whole audiogram to a transparent overlay clip (or a PNG
    sequence when codec == "png"). Returns the path written.

    With crop=True the output covers only the audiogram's own area rather
    than the whole frame -- much faster and smaller, at the cost of having
    to position it in the editor. The offset to use is logged and returned
    on the function's `last_crop` attribute.
    """
    cfg = config_with_defaults(cfg)
    fps = max(1, int(cfg["fps"]))
    if codec != "png" and not have_ffmpeg():
        raise RuntimeError("Rendering an overlay clip needs ffmpeg.")

    rows = analyse(audio_path, fps, max(2, int(cfg["bars"])),
                   cfg["smoothing"], log)
    if max_seconds:
        # A preview renders the opening of the file, not all of it. The
        # analysis still runs over the whole thing so smoothing and the
        # level scaling match what a full render would produce -- a
        # preview that normalises differently would be misleading.
        rows = rows[:max(1, int(max_seconds * fps))]
    total = len(rows)
    ox, oy, ex, ey = crop_box(cfg, width, height) if crop \
        else (0, 0, width, height)
    fw, fh = ex - ox, ey - oy
    render_overlay.last_crop = (ox, oy, fw, fh)
    if crop and (fw, fh) != (width, height):
        log(f"Rendering {total} frames, cropped to {fw}x{fh} at "
           f"+{ox}+{oy} (place it there in your editor)...")
    else:
        log(f"Rendering {total} frames at {fw}x{fh}...")

    if codec == "png":
        os.makedirs(out_path, exist_ok=True)
        for i, row in enumerate(rows):
            frame = draw_frame(row, cfg, width, height,
                              frame_context(cfg, i, total, row))
            if (fw, fh) != (width, height):
                frame = frame.crop((ox, oy, ex, ey))
            frame.save(os.path.join(out_path, f"frame_{i:06d}.png"))
            if progress_every and i and i % progress_every == 0:
                log(f"  {i}/{total} frames")
        log(f"  wrote {total} PNG frames")
        return out_path

    spec = CODECS[codec]
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
          "-f", "rawvideo", "-pix_fmt", "rgba",
          "-s", f"{fw}x{fh}", "-r", str(fps), "-i", "-"] \
        + spec["args"] + ["-r", str(fps), out_path]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            creationflags=_no_window())
    try:
        for i, row in enumerate(rows):
            frame = draw_frame(row, cfg, width, height,
                              frame_context(cfg, i, total, row))
            if (fw, fh) != (width, height):
                frame = frame.crop((ox, oy, ex, ey))
            proc.stdin.write(frame.tobytes())
            if progress_every and i and i % progress_every == 0:
                log(f"  {i}/{total} frames")
        proc.stdin.close()
    except BrokenPipeError:
        pass
    err = proc.stderr.read().decode("utf-8", "replace")
    if proc.wait() != 0 or not os.path.exists(out_path):
        raise RuntimeError("ffmpeg couldn't write the overlay:\n"
                           + err.strip()[-400:])
    log(f"  wrote {os.path.basename(out_path)}")
    return out_path


# Measured on this machine, 3s of audio, polar, 64 bars: 480x270 ~0.43s
# per rendered second; 1280x720 ~3.2; 1920x1080 ~7.0. Cost tracks pixels
# far more than bar count, because the per-frame work is dominated by
# building and piping the RGBA buffer rather than by drawing.
_PIXEL_COST = 7.0 / (1920 * 1080)      # seconds of render per second of
                                       # audio, per pixel, at 30fps


def estimate_render(audio_seconds, width, height, fps=30, crop_fraction=1.0,
                    codec="webm"):
    """Roughly how long a render will take, and how big it will be.

    Deliberately reported as a range with its basis stated: it is a
    straight-line extrapolation from measurements on one machine, and a
    slower or faster CPU moves it. The point is to warn someone off a
    four-hour 4K render before they start it, not to be exact.
    """
    pixels = max(1, int(width * height * max(0.01, crop_fraction)))
    ratio = _PIXEL_COST * pixels * (max(1, fps) / 30.0)
    seconds = max(1.0, audio_seconds * ratio)
    # VP9 is roughly two hundred times smaller than ProRes for a mostly
    # transparent overlay; PNG frames are larger again.
    per_second = {"webm": 0.007, "prores": 1.4, "png": 3.0}.get(codec, 0.01)
    megabytes = audio_seconds * per_second * (pixels / (1920 * 1080))
    return {"seconds": seconds, "low": seconds * 0.6, "high": seconds * 1.7,
            "realtime_ratio": ratio, "megabytes": megabytes,
            "frames": int(audio_seconds * max(1, fps))}


def describe_estimate(est):
    def clock(secs):
        if secs < 90:
            return f"{secs:.0f}s"
        if secs < 5400:
            return f"{secs / 60:.0f} min"
        return f"{secs / 3600:.1f} hours"
    size = (f"{est['megabytes'] * 1000:.0f} KB" if est["megabytes"] < 1
            else f"{est['megabytes']:.1f} MB")
    return (f"about {clock(est['low'])}–{clock(est['high'])} to render "
            f"({est['frames']:,} frames, roughly {size}). Rough guide "
            "only — a faster machine will beat it.")


def build_ffmpeg_filter(cfg, width, height, seconds=None):
    """The ffmpeg filter graph for the FAST path.

    ffmpeg's own `showwaves` cannot express a ring, a pivot or a formula,
    which is why the frame-by-frame renderer exists. But for a plain
    waveform it is far quicker, and it can be pushed further than it
    looks: `v360=input=flat:output=fisheye` bends a linear waveform into
    a circle, and `cas` sharpens it. This builds that graph so it can be
    shown, edited, or run as-is.
    """
    cfg = config_with_defaults(cfg)
    fps = max(1, int(cfg["fps"]))
    colour = (cfg["color"] or "#FFFFFF").lstrip("#")
    mode = {True: "cline"}.get(bool(cfg.get("show_line")), "p2p")
    if cfg.get("show_bars") and not cfg.get("show_line"):
        mode = "cline"
    chain = [f"showwaves=s={width}x{height}:mode={mode}"
             f":colors=0x{colour}:r={fps}"]
    if cfg["geometry"] == "polar":
        # Routh's discovery: a flat waveform projected as a fisheye comes
        # out as a ring.
        chain.append("v360=input=flat:output=fisheye:h_fov=360:v_fov=360")
    if cfg.get("sharpen"):
        chain.append(f"cas={float(cfg['sharpen']):g}")
    if cfg.get("blur"):
        chain.append(f"gblur=sigma={float(cfg['blur']):g}")
    if cfg.get("trail"):
        chain.append(f"tblend=all_mode=lighten")
    return "[0:a]" + ",".join(chain) + "[v]"


def ffmpeg_command(audio_path, out_path, cfg, width, height, seconds=None,
                   filter_override=None):
    """The complete command, as a list, ready to show or run."""
    graph = filter_override or build_ffmpeg_filter(cfg, width, height,
                                                   seconds)
    cmd = ["ffmpeg", "-y", "-i", audio_path]
    if seconds:
        cmd += ["-t", f"{float(seconds):g}"]
    cmd += ["-filter_complex", graph, "-map", "[v]", "-an",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-r", str(max(1, int(config_with_defaults(cfg)["fps"]))),
            out_path]
    return cmd


def command_preview(audio_path, out_path, cfg, width, height, seconds=None,
                    filter_override=None):
    """The command as a copy-pasteable string, quoted where needed."""
    import shlex
    return " ".join(shlex.quote(part) for part in
                    ffmpeg_command(audio_path, out_path, cfg, width, height,
                                   seconds, filter_override))


def render_ffmpeg(audio_path, out_path, cfg, log, width=1920, height=1080,
                  seconds=None, filter_override=None):
    """Run the fast path. Returns the output path.

    Not a replacement for `render_overlay`: this produces an opaque video
    rather than a transparent overlay, and cannot do pivots, formulas or
    layered fills. It exists because for a plain waveform it is an order
    of magnitude quicker, and because a filter graph can be edited by
    hand, which frame rendering cannot.
    """
    cmd = ffmpeg_command(audio_path, out_path, cfg, width, height, seconds,
                         filter_override)
    log("Running: " + command_preview(audio_path, out_path, cfg, width,
                                      height, seconds, filter_override))
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          creationflags=_no_window())
    if proc.returncode != 0 or not os.path.exists(out_path):
        raise RuntimeError("ffmpeg couldn't render that:\n"
                           + proc.stderr.strip()[-500:])
    log(f"  wrote {os.path.basename(out_path)}")
    return out_path


# A preview exists to be watched immediately. Past a few seconds it stops
# being a preview and starts being a render you are waiting for.
def export_analysis(audio_path, out_path, log, fps=30, bands=64,
                    smoothing=0.35, fmt="csv", detail="summary"):
    """Write the analysis out so something else can use it.

    This is the numeric middle of the pipeline: for each video frame, how
    loud the audio is overall and in each frequency band. Exporting it
    means a Fusion setup, an After Effects expression, or any custom tool
    can be driven by the same curve the audiogram draws, without redoing
    the analysis or having to match it.

    Not MIDI: MIDI is symbolic note data (pitch, velocity, note on/off),
    and deriving that from a mixed recording is pitch transcription -- a
    different problem, and one that produces nonsense on speech. What is
    useful here is the continuous curve, which is what animation software
    actually wants to key off.

    `detail`: "summary" gives time, level, bass, mid and treble --
    enough for almost any reactive animation. "bands" adds every band,
    which is large but complete.
    """
    rows = analyse(audio_path, fps, bands, smoothing, log)
    frames = len(rows)
    third = max(1, bands // 3)
    records = []
    for i, row in enumerate(rows):
        entry = {
            "frame": i,
            "time": round(i / max(1, fps), 4),
            "level": round(float(row.mean()), 5),
            "bass": round(float(row[:third].mean()), 5),
            "mid": round(float(row[third:2 * third].mean()), 5),
            "treble": round(float(row[2 * third:].mean()), 5),
        }
        if detail == "bands":
            for b, value in enumerate(row):
                entry[f"band_{b:03d}"] = round(float(value), 5)
        records.append(entry)

    if fmt == "json":
        import json
        payload = {
            "source": os.path.basename(audio_path),
            "fps": fps, "bands": bands, "smoothing": smoothing,
            "frames": frames,
            "duration": round(frames / max(1, fps), 3),
            "note": "Values are 0-1, normalised to this file's own peak. "
                    "level/bass/mid/treble are means across their bands.",
            "data": records,
        }
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=1)
    else:
        import csv
        with open(out_path, "w", encoding="utf-8", newline="") as fh:
            # A comment line first: someone opening this in six months
            # should not have to guess what the numbers mean or what they
            # are relative to.
            fh.write(f"# {os.path.basename(audio_path)} — {frames} frames "
                    f"at {fps} fps, values 0-1 normalised to this file's "
                    "own peak\n")
            writer = csv.DictWriter(fh, fieldnames=list(records[0]))
            writer.writeheader()
            writer.writerows(records)
    log(f"  wrote {frames:,} frames of analysis to "
       f"{os.path.basename(out_path)}")
    return out_path


PREVIEW_MAX_SECONDS = 8


def resolve_audio_source(cfg, fallback=None):
    """Which file the waveform should be read from.

    An explicit `audio_source` wins over the selected take. It is checked
    for existence here rather than at render time, so a stale path is
    reported while it can still be corrected instead of failing several
    minutes into a job.
    """
    chosen = (cfg or {}).get("audio_source") or ""
    if chosen:
        if not os.path.isfile(chosen):
            raise FileNotFoundError(
                f"The audiogram's audio source isn't there any more:\n"
                f"{chosen}\n\nPick another file, or clear it to use the "
                "selected take.")
        return chosen
    if fallback and os.path.isfile(fallback):
        return fallback
    raise FileNotFoundError(
        "No audio to draw. Render something, or choose an audio file for "
        "the audiogram.")


def source_note(cfg, fallback=None):
    """One line describing what the waveform will be read from, and
    whether that differs from the take -- worth saying plainly, since
    driving the audiogram from a different file than the video is easy to
    forget you did."""
    chosen = (cfg or {}).get("audio_source") or ""
    if not chosen:
        return ("the selected take" if fallback
                else "nothing yet -- render something or choose a file")
    name = os.path.basename(chosen)
    if not os.path.isfile(chosen):
        return f"{name} (MISSING -- pick another or clear this)"
    if fallback and os.path.abspath(chosen) != os.path.abspath(fallback):
        return (f"{name} -- note this is NOT the take you have selected, "
                "so the waveform won't match that audio")
    return name


def preview_clip(audio_path, out_dir, cfg, log, seconds=5, width=640,
                 height=360, engine="auto"):
    """A short moving preview.

    `engine`: "ffmpeg" is much faster but cannot show pivots, formulas,
    layered fills or per-layer colours; "frames" shows exactly what a real
    render will look like. "auto" picks frames when the layout uses
    anything ffmpeg can't express, and ffmpeg otherwise -- so the preview
    is as fast as it can be without ever being a lie about the output.
    """
    cfg = config_with_defaults(cfg)
    seconds = max(1, min(float(seconds), PREVIEW_MAX_SECONDS))
    if engine == "auto":
        layers = active_layers(cfg)
        animated = any(expr.is_expression(cfg.get(k)) for k in ANIMATABLE)
        needs_frames = (animated or layers["fill"]
                        or (layers["bars"] and layers["line"])
                        or float(cfg.get("rotation") or 0)
                        or (cfg.get("line_color") or cfg.get("fill_color")))
        engine = "frames" if needs_frames else "ffmpeg"
    os.makedirs(out_dir, exist_ok=True)

    if engine == "ffmpeg":
        out = os.path.join(out_dir, "audiogram_preview.mp4")
        log(f"Preview: {seconds:g}s via ffmpeg (fast path)")
        return render_ffmpeg(audio_path, out, cfg, log, width, height,
                             seconds=seconds), "ffmpeg"

    out = os.path.join(out_dir, "audiogram_preview.webm")
    log(f"Preview: {seconds:g}s via the frame renderer "
       "(this layout uses something the fast path can't draw)")
    return render_overlay(audio_path, out, cfg, log, width=width,
                          height=height, codec="webm", progress_every=0,
                          max_seconds=seconds), "frames"


def preview_reason(cfg):
    """Why the preview will use one renderer or the other, in a sentence
    -- so the choice doesn't look arbitrary."""
    cfg = config_with_defaults(cfg)
    layers = active_layers(cfg)
    if any(expr.is_expression(cfg.get(k)) for k in ANIMATABLE):
        return ("frames", "a value is animated by a formula")
    if layers["fill"]:
        return ("frames", "a shaded fill is on")
    if layers["bars"] and layers["line"]:
        return ("frames", "bars and a line are combined")
    if float(cfg.get("rotation") or 0):
        return ("frames", "the figure is rotated")
    if cfg.get("line_color") or cfg.get("fill_color"):
        return ("frames", "layers have separate colours")
    return ("ffmpeg", "this layout is a plain waveform, so the fast path "
                      "can draw it")


def estimate_frames(audio_path, fps):
    return int(math.ceil((duration_of(audio_path) or 0) * max(1, int(fps))))
