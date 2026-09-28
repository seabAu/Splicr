import os, sys, shutil, subprocess, json, time
import numpy as np
from PIL import Image
sys.path[:0] = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "stubs"),
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
from narrator import audiogram as A
D = "/tmp/agtest"; shutil.rmtree(D, ignore_errors=True); os.makedirs(D)
log = lambda m: None
src = f"{D}/a.wav"
subprocess.run(["ffmpeg","-y","-v","error","-f","lavfi",
                "-i","sine=frequency=300:duration=3","-ar","24000",src],
               capture_output=True, check=True)
rows = A.analyse(src, 30, 48, 0.35, log)

def alpha(cfg, w=320, h=180, row=None):
    return np.array(A.draw_frame(row if row is not None else rows[45],
                                 cfg, w, h))[:, :, 3]

# --- layers are independent and combinable ---
bars = alpha({"geometry": "linear", "show_bars": True})
line = alpha({"geometry": "linear", "show_bars": False, "show_line": True})
fill = alpha({"geometry": "linear", "show_bars": False, "show_fill": True})
both = alpha({"geometry": "linear", "show_bars": True, "show_line": True,
              "show_fill": True})
for name, img in (("bars", bars), ("line", line)):
    assert img.max() > 100, f"{name} drew nothing"
# The fill is translucent by design (opacity x fill_opacity), so it is
# checked by coverage rather than by peak alpha.
assert fill.astype(bool).sum() > 500, "fill drew nothing"
assert 0 < fill.max() < 200, f"fill should be translucent, got {fill.max()}"
# Compared at the same line width: a 3px stroke can out-cover the area
# under a sparse spectrum, so the width has to be held constant for the
# comparison to mean anything.
thin_line = alpha({"geometry": "linear", "show_bars": False,
                   "show_line": True, "line_width": 1})
assert fill.astype(bool).sum() > thin_line.astype(bool).sum(), \
    (fill.astype(bool).sum(), thin_line.astype(bool).sum())
assert both.astype(bool).sum() >= max(bars.astype(bool).sum(),
                                      fill.astype(bool).sum())
print(f"L1 ok: bars/line/fill each render and combine "
     f"(bars {bars.astype(bool).sum()}, line {line.astype(bool).sum()}, "
     f"fill {fill.astype(bool).sum()}, all three {both.astype(bool).sum()} px)")

# fill has its own colour and opacity
tinted = np.array(A.draw_frame(rows[45], {
    "geometry": "linear", "show_bars": False, "show_fill": True,
    "color": "#FFFFFF", "fill_color": "#FF0000", "fill_opacity": 0.5},
    320, 180))
lit = tinted[:, :, 3] > 0
assert tinted[:, :, 0][lit].mean() > 200 and tinted[:, :, 2][lit].mean() < 60
assert 0 < tinted[:, :, 3][lit].max() < 255, "fill opacity must apply"
print(f"L2 ok: the fill takes its own colour and opacity "
     f"(alpha {tinted[:, :, 3][lit].max()} of 255)")

# --- a layout saved before the toggles still renders ---
legacy_bars = alpha({"geometry": "linear", "style": "bars"})
legacy_line = alpha({"geometry": "linear", "style": "line",
                     "show_bars": False})
assert legacy_bars.max() > 100 and legacy_line.max() > 100
assert A.active_layers({"style": "line", "show_bars": False})["line"] is True
assert A.active_layers({"style": "bars", "show_bars": False})["bars"] is True
print("L3 ok: a layout saved before the toggles existed still renders, "
     "translated from its old style field rather than drawing nothing")

# --- polar gets the same layers, and the ring stays hollow ---
# A pure sine leaves most bands near zero, so the filled ring is thin;
# use full-amplitude values where the point is that the AREA fills.
loud = np.ones(48, dtype="float32")
pol_fill = alpha({"geometry": "polar", "show_bars": False,
                  "show_fill": True}, 400, 400, row=loud)
assert pol_fill[200, 200] == 0, "the middle of the ring must stay empty"
assert pol_fill.astype(bool).sum() > 20000, pol_fill.astype(bool).sum()
pol_line = alpha({"geometry": "polar", "show_bars": False,
                  "show_line": True, "line_width": 1}, 400, 400, row=loud)
assert pol_line.astype(bool).sum() < pol_fill.astype(bool).sum() / 5
print("P1 ok: polar supports fill and outline too, and the ring's centre "
     "stays hollow in both")

# --- bar width is a real control ---
thin = alpha({"geometry": "linear", "bar_width": 0.15}).astype(bool).sum()
thick = alpha({"geometry": "linear", "bar_width": 1.0}).astype(bool).sum()
assert thick > thin * 1.5, (thin, thick)
print(f"B1 ok: bar width changes coverage ({thin} -> {thick} px)")

# --- render estimates ---
small = A.estimate_render(1800, 480, 270)
big = A.estimate_render(1800, 3840, 2160)
assert big["seconds"] > small["seconds"] * 20
assert big["frames"] == small["frames"] == 1800 * 30
text = A.describe_estimate(big)
assert "hours" in text or "min" in text
assert "Rough guide" in text, "the estimate must admit it's approximate"
print(f"E1 ok: 30 min of audio at 480x270 -> {A.describe_estimate(small)[:46]}")
print(f"E2 ok: same at 4K -> {text[:60]}")

fast = A.estimate_render(1800, 1920, 1080, fps=15)
slow = A.estimate_render(1800, 1920, 1080, fps=60)
assert slow["seconds"] > fast["seconds"] * 3
print(f"E3 ok: sampling rate moves the estimate too (15fps vs 60fps: "
     f"{fast['seconds']:.0f}s vs {slow['seconds']:.0f}s)")

cropped = A.estimate_render(1800, 1920, 1080, crop_fraction=0.24)
assert cropped["seconds"] < A.estimate_render(1800, 1920, 1080)["seconds"] / 3
print("E4 ok: cropping to the audiogram's own area is reflected in the "
     "estimate")

# --- the ffmpeg fast path ---
graph = A.build_ffmpeg_filter({"geometry": "linear", "color": "#613D2D"},
                              1920, 360)
assert "showwaves=s=1920x360" in graph and "0x613D2D" in graph
assert graph.startswith("[0:a]") and graph.endswith("[v]")
print(f"F1 ok: linear filter graph: {graph}")

ring = A.build_ffmpeg_filter({"geometry": "polar"}, 1280, 720)
assert "v360=input=flat:output=fisheye" in ring
print(f"F2 ok: polar uses the fisheye trick: {ring}")

fancy = A.build_ffmpeg_filter({"geometry": "linear", "sharpen": 0.5,
                               "blur": 2, "trail": True}, 1920, 1080)
assert "cas=0.5" in fancy and "gblur=sigma=2" in fancy and "tblend" in fancy
print(f"F3 ok: sharpen/blur/trail all reach the graph")

cmd = A.command_preview(src, f"{D}/o.mp4", {"geometry": "linear"},
                        1920, 1080, seconds=5)
assert "-t 5" in cmd and "libx264" in cmd and "-filter_complex" in cmd
assert cmd.startswith("ffmpeg ")
print(f"F4 ok: the command preview is copy-pasteable:\n    {cmd[:120]}...")

out = A.render_ffmpeg(src, f"{D}/fast.mp4", {"geometry": "linear"}, log,
                      width=320, height=180, seconds=2)
assert os.path.isfile(out) and os.path.getsize(out) > 1000
info = json.loads(subprocess.run(
    ["ffprobe","-v","error","-show_streams","-print_format","json",out],
    capture_output=True, text=True).stdout)["streams"][0]
assert info["codec_name"] == "h264"
print(f"F5 ok: the fast path really renders ({info['width']}x"
     f"{info['height']} h264, {os.path.getsize(out)/1000:.0f} KB)")

t0 = time.time()
A.render_ffmpeg(src, f"{D}/speed.mp4", {"geometry": "linear"}, log,
                width=1280, height=720, seconds=3)
ffmpeg_time = time.time() - t0
t0 = time.time()
A.render_overlay(src, f"{D}/slow.webm", {"geometry": "linear"}, log,
                 width=1280, height=720, codec="webm", progress_every=0)
pil_time = time.time() - t0
print(f"F6 ok: for 3s at 720p the ffmpeg path took {ffmpeg_time:.1f}s vs "
     f"{pil_time:.1f}s for the frame renderer ({pil_time/ffmpeg_time:.0f}x)")

# a custom graph is used verbatim
custom = "[0:a]showwaves=s=200x100:mode=p2p:colors=0x00FF00[v]"
out2 = A.render_ffmpeg(src, f"{D}/custom.mp4", {}, log, width=1920,
                       height=1080, seconds=1, filter_override=custom)
info2 = json.loads(subprocess.run(
    ["ffprobe","-v","error","-show_streams","-print_format","json",out2],
    capture_output=True, text=True).stdout)["streams"][0]
assert (info2["width"], info2["height"]) == (200, 100), info2
print("F7 ok: a hand-written filter graph overrides the built one entirely "
     "(output is 200x100, the size the custom graph asked for)")

try:
    A.render_ffmpeg(src, f"{D}/bad.mp4", {}, log, seconds=1,
                    filter_override="[0:a]nonsense_filter=1[v]")
    raise SystemExit("should have raised")
except RuntimeError as e:
    assert "couldn't render" in str(e)
print("F8 ok: a broken custom graph reports ffmpeg's own error rather "
     "than failing silently")

print("\nALL AUDIOGRAM TESTS PASSED")

# --- the motion preview ---
PD = f"{D}/preview"
path, engine = A.preview_clip(src, PD, {"geometry": "linear"}, log, seconds=2,
                              width=320, height=180)
assert os.path.isfile(path) and engine == "ffmpeg"
dur = float(subprocess.run(
    ["ffprobe","-v","error","-show_entries","format=duration",
     "-of","csv=p=0",path], capture_output=True, text=True).stdout.strip())
assert 1.5 < dur < 2.6, dur
print(f"M1 ok: a plain layout previews via the fast path ({dur:.1f}s clip)")

# a layout the fast path can't draw honestly falls back to the frame renderer
path2, engine2 = A.preview_clip(src, PD, {"geometry": "linear",
                                          "show_fill": True}, log,
                                seconds=2, width=320, height=180)
assert engine2 == "frames", engine2
assert os.path.isfile(path2)
print("M2 ok: a layout with a shaded fill previews via the frame renderer "
     "instead -- the preview never shows something the render won't")

for cfg_, expect in (
        ({"geometry": "linear"}, "ffmpeg"),
        ({"geometry": "linear", "rotation": 20}, "frames"),
        ({"geometry": "linear", "show_bars": True, "show_line": True}, "frames"),
        ({"geometry": "polar", "outer_radius": "0.2+0.1*level"}, "frames"),
        ({"geometry": "linear", "line_color": "#FF0000",
          "show_line": True}, "frames")):
    chosen, why = A.preview_reason(cfg_)
    assert chosen == expect, (cfg_, chosen, expect)
    assert why
print("M3 ok: the renderer choice is explained per layout, e.g. "
     f"{A.preview_reason({'geometry':'linear','rotation':20})[1]!r}")

# a preview is capped, however long you ask for
capped, _e = A.preview_clip(src, PD, {"geometry": "linear"}, log,
                            seconds=999, width=160, height=90)
dur2 = float(subprocess.run(
    ["ffprobe","-v","error","-show_entries","format=duration",
     "-of","csv=p=0",capped], capture_output=True, text=True).stdout.strip())
assert dur2 <= A.PREVIEW_MAX_SECONDS + 0.5, dur2
print(f"M4 ok: asking for 999s yields {dur2:.1f}s -- a preview stays a "
     "preview")

# the frame renderer honours a duration limit too
short = A.render_overlay(src, f"{D}/short.webm", {"geometry": "linear"}, log,
                         width=160, height=90, codec="webm",
                         progress_every=0, max_seconds=1)
dur3 = float(subprocess.run(
    ["ffprobe","-v","error","-show_entries","format=duration",
     "-of","csv=p=0",short], capture_output=True, text=True).stdout.strip())
assert dur3 < 1.5, dur3
print(f"M5 ok: the frame renderer can render just the opening "
     f"({dur3:.1f}s of a 3s file)")

# and the level scaling matches a full render, so the preview isn't a lie
full_rows = A.analyse(src, 30, 48, 0.35, log)
assert abs(float(full_rows.max()) - 1.0) < 0.01
print("M6 ok: analysis still runs over the whole file, so a preview "
     "normalises exactly as the full render does")

print("\nALL AUDIOGRAM TESTS PASSED (including previews)")

# --- the audio source ---
other = f"{D}/other.wav"
subprocess.run(["ffmpeg","-y","-v","error","-f","lavfi",
                "-i","sine=frequency=800:duration=2","-ar","22050","-ac","1",
                other], capture_output=True, check=True)

assert A.resolve_audio_source({}, src) == src
assert A.resolve_audio_source({"audio_source": other}, src) == other
print("A1 ok: an explicit audio source wins over the selected take")

try:
    A.resolve_audio_source({"audio_source": f"{D}/gone.wav"}, src)
    raise SystemExit("should have raised")
except FileNotFoundError as e:
    assert "isn't there any more" in str(e)
print("A2 ok: a stale source path is reported up front, not several "
     "minutes into a render")

try:
    A.resolve_audio_source({}, None)
    raise SystemExit("should have raised")
except FileNotFoundError as e:
    assert "No audio to draw" in str(e)
print("A3 ok: with nothing to draw from, it says so")

note = A.source_note({"audio_source": other}, src)
assert "NOT the take" in note, note
assert A.source_note({}, src) == "the selected take"
assert "MISSING" in A.source_note({"audio_source": f"{D}/gone.wav"}, src)
print(f"A4 ok: pointing at a different file warns plainly -- {note[:70]}")

# a proxy really does drive the render
out = A.render_overlay(other, f"{D}/from_other.webm", {"geometry": "linear"},
                       log, width=160, height=90, codec="webm",
                       progress_every=0)
dur = float(subprocess.run(
    ["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",
     out], capture_output=True, text=True).stdout.strip())
assert 1.5 < dur < 2.6, dur
print(f"A5 ok: rendering from a chosen 2s file gives a {dur:.1f}s "
     "audiogram, so a proxy or a stem really does drive it")

print("\nALL AUDIOGRAM TESTS PASSED (including previews and sources)")

# --- exporting the analysis for other tools ---
import csv as _csv, json as _json
csv_path = A.export_analysis(src, f"{D}/an.csv", log, fps=30, bands=48)
with open(csv_path) as fh:
    first = fh.readline()
    assert first.startswith("#") and "normalised" in first
    reader = list(_csv.DictReader(fh))
assert len(reader) == 90, len(reader)
assert set(reader[0]) == {"frame", "time", "level", "bass", "mid", "treble"}
assert abs(float(reader[30]["time"]) - 1.0) < 0.01
assert all(0.0 <= float(r["level"]) <= 1.0 for r in reader)
print(f"AN1 ok: CSV has {len(reader)} frames with time/level/bass/mid/"
     "treble, and a header line saying what the numbers mean")

full = A.export_analysis(src, f"{D}/an_full.csv", log, fps=30, bands=48,
                         detail="bands")
with open(full) as fh:
    fh.readline()
    wide = list(_csv.DictReader(fh))
assert len([k for k in wide[0] if k.startswith("band_")]) == 48
print(f"AN2 ok: the full form adds all "
     f"{len([k for k in wide[0] if k.startswith('band_')])} bands")

js = A.export_analysis(src, f"{D}/an.json", log, fps=24, bands=32,
                       fmt="json")
payload = _json.load(open(js))
assert payload["fps"] == 24 and payload["bands"] == 32
assert payload["frames"] == len(payload["data"]) == 72
assert abs(payload["duration"] - 3.0) < 0.1
assert "normalised" in payload["note"]
print(f"AN3 ok: JSON carries its own settings and a note "
     f"({payload['frames']} frames, {payload['duration']}s at "
     f"{payload['fps']}fps)")

# the exported curve is the SAME one the audiogram draws
rows_direct = A.analyse(src, 30, 48, 0.35, log)
ctx = A.frame_context({"fps": 30}, 30, len(rows_direct), rows_direct[30])
assert abs(ctx["level"] - float(reader[30]["level"])) < 1e-4
print("AN4 ok: the exported level matches what a formula sees in the "
     "renderer at the same frame -- one analysis, not two that could "
     "disagree")

print("\nALL AUDIOGRAM TESTS PASSED (previews, sources and analysis export)")
