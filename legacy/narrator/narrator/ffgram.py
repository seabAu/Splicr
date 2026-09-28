"""Building ffmpeg audiogram commands from parts.

Why this exists: the frame-by-frame renderer in `audiogram.py` gives total
control -- pivots, formulas, layered fills, real transparency -- but it is
too slow for hour-long episodes. Measured on this machine at 1920x1080:

    ffmpeg showwaves        0.72x realtime  ->  43 min for a 60-min episode
    frame renderer          3.63x realtime  ->  3.6 hours for the same

and the DaVinci Resolve/Reactor Lua fuse Routh was using before takes
8-24 hours for the same material. So for a plain waveform, ffmpeg is not
a shortcut, it is the only practical option at length -- and the frame
renderer is for the cases ffmpeg genuinely cannot draw.

The catch is that the filter syntax is unforgiving and hard to explore.
This module turns a graph into structured data: a source visualiser plus
an ordered stack of effects plus encoder settings, each with named
options carrying ranges and one-line descriptions. From that it can build
the command, explain it, estimate how long it will take, and run it --
and any hand-written graph can still be used verbatim instead.

Option names and value ranges were read from `ffmpeg -h filter=...` on
the machine this was written on, not from memory.
"""

import os
import shlex
import subprocess

from .config import _no_window, have_ffmpeg

# --- the visualisers -------------------------------------------------------
#
# Each option: (kind, default, choices-or-range, description). "size" is
# handled separately, since the render size is also a speed control.
SOURCES = {
    "showwaves": {
        "label": "Waveform",
        "supports_rate": True,
        "note": "The classic audiogram: amplitude over time.",
        "options": {
            "mode": ("choice", "cline",
                     ["point", "line", "p2p", "cline"],
                     "cline is the usual centred waveform; p2p joins "
                     "samples; point and line are sparser."),
            "colors": ("color", "0xFFFFFF", None,
                       "One colour, or several separated by | for "
                       "multi-channel audio."),
            "scale": ("choice", "lin", ["lin", "log", "sqrt", "cbrt"],
                      "How amplitude maps to height. sqrt and cbrt lift "
                      "quiet passages."),
            "draw": ("choice", "scale", ["scale", "full"],
                     "full draws every pixel for a sample -- heavier, "
                     "solid-looking."),
            "split_channels": ("bool", False, None,
                               "Draw left and right separately."),
        },
    },
    "showfreqs": {
        "label": "Frequency bars",
        "supports_rate": True,
        "note": "A spectrum analyser: energy per frequency band.",
        "options": {
            "mode": ("choice", "bar", ["line", "bar", "dot"],
                     "How each band is drawn."),
            "ascale": ("choice", "log", ["lin", "sqrt", "cbrt", "log"],
                       "Amplitude scale."),
            "fscale": ("choice", "lin", ["lin", "sqrt", "cbrt", "log"],
                       "Frequency scale. log spreads the bass out."),
            "win_size": ("int", 2048, (16, 65536),
                         "Bigger means finer frequency detail but blurrier "
                         "in time."),
            "colors": ("color", "0xFFFFFF", None, "Bar colour."),
        },
    },
    "showspectrum": {
        "label": "Spectrogram",
        # No `rate` option: its frame rate follows the audio and the
        # sliding mode. Passing r= makes ffmpeg reject the whole graph.
        "supports_rate": False,
        "note": "Frequency over time as a scrolling image.",
        "options": {
            "slide": ("choice", "scroll",
                      ["replace", "scroll", "fullframe", "rscroll"],
                      "How the image advances."),
            "mode": ("choice", "combined", ["combined", "separate"],
                     "Combine channels or stack them."),
            "scale": ("choice", "sqrt",
                      ["lin", "sqrt", "cbrt", "log", "4thrt", "5thrt"],
                      "Intensity scale."),
            "saturation": ("float", 1.0, (-10.0, 10.0),
                           "Colour intensity."),
            "rotation": ("float", 0.0, (-1.0, 1.0),
                         "Shifts the colour mapping."),
        },
    },
    "avectorscope": {
        "label": "Vectorscope",
        "supports_rate": True,
        "note": "Stereo field as a shape. Needs stereo audio to be "
                "interesting -- a mono file draws a diagonal line.",
        "options": {
            "mode": ("choice", "lissajous",
                     ["lissajous", "lissajous_xy", "polar"],
                     "Projection."),
            "draw": ("choice", "dot", ["dot", "line", "aaline"],
                     "aaline is smoothest."),
            "zoom": ("float", 1.0, (0.0, 10.0), "Magnification."),
            "scale": ("choice", "lin", ["lin", "sqrt", "cbrt", "log"],
                      "Amplitude scale."),
        },
    },
}

# --- effects applied after the visualiser ---------------------------------
EFFECTS = {
    "scale": {
        "label": "Resize",
        "note": "Render small and scale up: the visualiser is the "
                "expensive part, so this genuinely saves time.",
        "template": "scale={w}:{h}{flags}",
        "options": {
            "w": ("int", 1920, (16, 7680), "Output width."),
            "h": ("int", 1080, (16, 4320), "Output height."),
            "flags": ("choice", "", ["", "neighbor", "bilinear", "bicubic",
                                     "lanczos"],
                      "neighbor keeps hard edges; lanczos is smoothest."),
        },
    },
    "fisheye": {
        "label": "Bend into a ring",
        "note": "Projects a flat waveform as a circle. This is how you "
                "get a ring out of showwaves, which cannot draw one.",
        # w/h are set explicitly because the fisheye projection changes
        # the frame's proportions on its own -- a 720x720 input comes out
        # 360x720 otherwise, which makes the output size unpredictable and
        # the render estimate wrong.
        "template": ("v360=input=flat:output=fisheye:h_fov={fov}"
                     ":v_fov={fov}:w={w}:h={h}"),
        "options": {
            "fov": ("int", 360, (90, 360),
                    "360 wraps the full width into a complete ring; less "
                    "leaves an arc."),
            "w": ("int", 1080, (16, 4320), "Output width."),
            "h": ("int", 1080, (16, 4320), "Output height."),
        },
    },
    "cas": {
        "label": "Sharpen",
        "note": "Contrast-adaptive sharpening. Crisps up a soft waveform.",
        "template": "cas={strength}",
        "options": {"strength": ("float", 0.5, (0.0, 1.0), "How much.")},
    },
    "gblur": {
        "label": "Blur",
        "note": "Gaussian blur. Good for a soft glow underneath a sharp "
                "copy.",
        "template": "gblur=sigma={sigma}",
        "options": {"sigma": ("float", 4.0, (0.1, 100.0), "Blur radius.")},
    },
    "tblend": {
        "label": "Motion trail",
        "note": "Blends each frame with the one before, so movement "
                "smears rather than flickering.",
        "template": "tblend=all_mode={mode}",
        "options": {
            "mode": ("choice", "lighten",
                     ["lighten", "average", "screen", "addition"],
                     "lighten keeps the brightest of the two frames."),
        },
    },
    "hue": {
        "label": "Shift colour",
        "note": "Rotate hue and adjust saturation. `t` is available, so "
                "h=t*30 cycles the colour over time.",
        "template": "hue=h={h}:s={s}",
        "options": {
            "h": ("text", "0", None, "Hue in degrees; may use `t`."),
            "s": ("float", 1.0, (0.0, 5.0), "Saturation."),
        },
    },
    "pad": {
        "label": "Pad to size",
        "note": "Centres the image in a larger frame instead of "
                "stretching it.",
        "template": "pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color={color}",
        "options": {
            "w": ("int", 1920, (16, 7680), "Frame width."),
            "h": ("int", 1080, (16, 4320), "Frame height."),
            "color": ("color", "black@0", None,
                      "black@0 keeps it transparent."),
        },
    },
    "colorkey": {
        "label": "Make a colour transparent",
        "note": "Turns the background transparent so the result can be "
                "laid over video. Needs a codec that keeps alpha.",
        "template": "colorkey={color}:{similarity}:{blend}",
        "options": {
            "color": ("color", "black", None, "Colour to remove."),
            "similarity": ("float", 0.1, (0.01, 1.0), "How close counts."),
            "blend": ("float", 0.0, (0.0, 1.0), "Edge softness."),
        },
    },
}

# Measured on this machine: seconds of render per second of audio at
# 1920x1080/30fps, by encoder preset. The preset dominates -- far more
# than the visualiser or the resolution.
PRESET_COST = {
    "ultrafast": 0.26, "superfast": 0.32, "veryfast": 0.40,
    "faster": 0.50, "fast": 0.62, "medium": 0.72, "slow": 1.10,
}
PRESETS = list(PRESET_COST)

ENCODERS = {
    "h264": {"label": "H.264 (.mp4) — opaque, universal",
             "args": ["-c:v", "libx264", "-pix_fmt", "yuv420p"],
             "ext": ".mp4", "alpha": False},
    "prores": {"label": "ProRes 4444 (.mov) — keeps transparency",
               "args": ["-c:v", "prores_ks", "-profile:v", "4444",
                        "-pix_fmt", "yuva444p10le"],
               "ext": ".mov", "alpha": True},
    "vp9": {"label": "VP9 (.webm) — keeps transparency, small",
            "args": ["-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p",
                     "-b:v", "0", "-crf", "30"],
            "ext": ".webm", "alpha": True},
}


# A colour genuinely absent from the rest of the picture is the whole
# point of chroma key. Pure green is the traditional choice because human
# skin, most sets, and most waveform colours never land on it by
# accident; magenta is the other common pick when green appears
# deliberately (e.g. in the waveform colour itself).
CHROMA_KEY_COLOR = "0x00FF00"


def default_spec():
    return {
        "source": "showwaves",
        "source_options": {"mode": "cline", "colors": "0xFFFFFF"},
        "render_width": 1920, "render_height": 360,
        "fps": 30,
        "effects": [{"name": "scale", "options": {"w": 1920, "h": 1080}}],
        "encoder": "h264", "preset": "ultrafast", "crf": 20,
        # An opaque background solid enough to key out in an editor --
        # simpler to guarantee than real alpha, which depends on the
        # receiving app actually trusting the channel. Blank disables it
        # and falls back to plain black, ffmpeg's own default.
        "chroma_key_background": "",
        "custom_graph": "",
    }


def _fmt(value):
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def build_graph(spec):
    """The filter graph string. A `custom_graph` is returned untouched --
    the whole point of showing the command is that it can be replaced."""
    if (spec.get("custom_graph") or "").strip():
        return spec["custom_graph"].strip()

    bg = (spec.get("chroma_key_background") or "").strip()
    if bg:
        # showwaves only paints the waveform itself; everything it
        # doesn't paint is genuinely transparent black, not "coloured
        # black" -- so a colorkey filter downstream would find nothing to
        # key on. The fix is a solid colour UNDER the waveform: `color=`
        # as a second input, composited before anything else runs.
        return _build_graph_with_background(spec, bg)

    source = SOURCES.get(spec.get("source") or "showwaves")
    name = spec.get("source") or "showwaves"
    parts = [f"s={int(spec.get('render_width', 1920))}x"
             f"{int(spec.get('render_height', 360))}"]
    if source.get("supports_rate", True):
        parts.append(f"r={int(spec.get('fps', 30))}")
    for key, value in (spec.get("source_options") or {}).items():
        if key not in source["options"]:
            continue          # unknown keys are dropped, not passed on
        if value in ("", None):
            continue
        parts.append(f"{key}={_fmt(value)}")
    chain = [name + "=" + ":".join(parts)]

    for effect in spec.get("effects") or []:
        spec_e = EFFECTS.get(effect.get("name"))
        if not spec_e:
            continue
        values = {}
        for key, (_kind, default, _range, _desc) in spec_e["options"].items():
            values[key] = (effect.get("options") or {}).get(key, default)
        if effect.get("name") == "scale":
            flags = values.get("flags") or ""
            values["flags"] = f":flags={flags}" if flags else ""
        chain.append(spec_e["template"].format(
            **{k: _fmt(v) for k, v in values.items()}))
    return "[0:a]" + ",".join(chain) + "[v]"


def _visualiser_chain(spec):
    """The visualiser + effects portion only, as a plain filter list (no
    [0:a] input tag, no [v] output tag) -- reused by both the normal path
    and the chroma-key path, which has to splice it into a larger graph
    with a second input.
    """
    source = SOURCES.get(spec.get("source") or "showwaves")
    name = spec.get("source") or "showwaves"
    parts = [f"s={int(spec.get('render_width', 1920))}x"
             f"{int(spec.get('render_height', 360))}"]
    if source.get("supports_rate", True):
        parts.append(f"r={int(spec.get('fps', 30))}")
    for key, value in (spec.get("source_options") or {}).items():
        if key not in source["options"] or value in ("", None):
            continue
        parts.append(f"{key}={_fmt(value)}")
    chain = [name + "=" + ":".join(parts)]
    for effect in spec.get("effects") or []:
        spec_e = EFFECTS.get(effect.get("name"))
        if not spec_e:
            continue
        values = {}
        for key, (_kind, default, _range, _desc) in spec_e["options"].items():
            values[key] = (effect.get("options") or {}).get(key, default)
        if effect.get("name") == "scale":
            flags = values.get("flags") or ""
            values["flags"] = f":flags={flags}" if flags else ""
        chain.append(spec_e["template"].format(
            **{k: _fmt(v) for k, v in values.items()}))
    return chain


def _build_graph_with_background(spec, color):
    """A solid-colour background input, composited under the waveform.

    ffmpeg's `color` source needs a size and duration to exist at all;
    the size is matched to the visualiser's OWN drawing size (post-effects
    dimensions are handled by `overlay`'s auto-sizing), and the duration is
    left to follow the audio via `-shortest` at the command level.
    """
    chain = _visualiser_chain(spec)
    width, height = output_size(spec)
    bg = f"color=c={color}:s={width}x{height}[bg]"
    wave = "[0:a]" + ",".join(chain) + "[wave]"
    # overlay's OWN shortest=1 stops the composite at the shorter input,
    # here the real audio-driven waveform rather than the colour source
    # (which has no length of its own). The output-level -shortest flag
    # was tried first and does NOT reliably bound this graph shape --
    # confirmed directly: a render with only the output flag ran to
    # 37.9s against a 4.0s source before being killed by a timeout, while
    # the identical graph with overlay's own shortest=1 stopped correctly
    # at 4.07s. The output flag is kept too, as a second line of defence,
    # but overlay's own parameter is what actually does the job.
    return f"{bg};{wave};[bg][wave]overlay=format=auto:shortest=1[v]"


def build_command(audio_path, out_path, spec, seconds=None):
    graph = build_graph(spec)
    encoder = ENCODERS.get(spec.get("encoder") or "h264", ENCODERS["h264"])
    cmd = ["ffmpeg", "-y", "-i", audio_path]
    if seconds:
        cmd += ["-t", f"{float(seconds):g}"]
    cmd += ["-filter_complex", graph, "-map", "[v]", "-an"]
    cmd += list(encoder["args"])
    if encoder["ext"] == ".mp4":
        cmd += ["-preset", spec.get("preset") or "ultrafast",
                "-crf", str(int(spec.get("crf", 20)))]
    cmd += ["-r", str(int(spec.get("fps", 30)))]
    if (spec.get("chroma_key_background") or "").strip() \
            and not (spec.get("custom_graph") or "").strip():
        # -shortest is an OUTPUT option: it has to come after -map/the
        # encoder flags, not beside -i. Placed there it is silently a
        # no-op, and the still-colour background then has no natural
        # length, so ffmpeg runs forever -- confirmed the hard way, in
        # the shell version of this same graph, which hung for real
        # until killed. `seconds` alone had been masking this in testing,
        # since -t bounds the run regardless of whether -shortest works.
        cmd += ["-shortest"]
    cmd.append(out_path)
    return cmd


def command_text(audio_path, out_path, spec, seconds=None):
    return " ".join(shlex.quote(p) for p in
                    build_command(audio_path, out_path, spec, seconds))


def explain(spec):
    """What each part of the graph is doing, in order -- so the command
    can be understood rather than only copied."""
    if (spec.get("custom_graph") or "").strip():
        return ["Using your own filter graph, unchanged."]
    source = SOURCES.get(spec.get("source") or "showwaves")
    lines = [f"{source['label']}: {source['note']}",
             f"Drawn at {spec.get('render_width')}x"
             f"{spec.get('render_height')}, {spec.get('fps')} fps."]
    for effect in spec.get("effects") or []:
        e = EFFECTS.get(effect.get("name"))
        if e:
            lines.append(f"{e['label']}: {e['note']}")
    encoder = ENCODERS.get(spec.get("encoder") or "h264", ENCODERS["h264"])
    lines.append(f"Encoded as {encoder['label']}."
                 + ("" if encoder["alpha"] else
                    " No transparency -- it will have a solid background."))
    return lines


def estimate(spec, audio_seconds):
    """How long a render will take, extrapolated from measurements here.

    The encoder preset matters more than anything else, which is not
    obvious and is why it is surfaced: at 1080p, ultrafast is roughly
    three times quicker than medium for the same picture.
    """
    preset = spec.get("preset") or "ultrafast"
    per_second = PRESET_COST.get(preset, 0.72)
    # Output size drives the encoder; the visualiser's own size matters
    # much less, which is why rendering small and scaling up helps only
    # a little.
    out_w, out_h = output_size(spec)
    scale = (out_w * out_h) / (1920 * 1080)
    fps_factor = int(spec.get("fps", 30)) / 30.0
    seconds = audio_seconds * per_second * max(0.05, scale) * fps_factor
    return {"seconds": seconds, "realtime": seconds / max(1, audio_seconds),
            "preset": preset}


def output_size(spec):
    """The final frame size after any resizing effects."""
    width = int(spec.get("render_width", 1920))
    height = int(spec.get("render_height", 360))
    for effect in spec.get("effects") or []:
        if effect.get("name") in ("scale", "pad", "fisheye"):
            options = effect.get("options") or {}
            defaults = EFFECTS[effect["name"]]["options"]
            width = int(options.get("w", defaults["w"][1]))
            height = int(options.get("h", defaults["h"][1]))
    return width, height


def describe_estimate(spec, audio_seconds):
    est = estimate(spec, audio_seconds)
    secs = est["seconds"]
    if secs < 90:
        took = f"{secs:.0f} seconds"
    elif secs < 5400:
        took = f"{secs / 60:.0f} minutes"
    else:
        took = f"{secs / 3600:.1f} hours"
    faster = ""
    if est["preset"] != "ultrafast":
        quick = audio_seconds * PRESET_COST["ultrafast"]
        if quick < secs * 0.7:
            faster = (f" The ultrafast preset would take about "
                      f"{quick / 60:.0f} minutes instead, at the cost of a "
                      "bigger file.")
    return (f"About {took} for {audio_seconds / 60:.0f} minutes of audio "
            f"({est['realtime']:.2f}x realtime).{faster}")


def render(audio_path, out_path, spec, log, seconds=None):
    if not have_ffmpeg():
        raise RuntimeError("This needs ffmpeg, which isn't on PATH.")
    cmd = build_command(audio_path, out_path, spec, seconds)
    log(command_text(audio_path, out_path, spec, seconds))
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          creationflags=_no_window())
    if proc.returncode != 0 or not os.path.exists(out_path):
        # ffmpeg's own message is far more useful than anything that could
        # be written here, so it is passed through rather than summarised.
        raise RuntimeError("ffmpeg refused that graph:\n"
                           + (proc.stderr.strip()[-600:] or "no output"))
    size = os.path.getsize(out_path) / 1e6
    log(f"  wrote {os.path.basename(out_path)} ({size:.1f} MB)")
    return out_path
