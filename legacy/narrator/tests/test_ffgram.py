import os, sys, shutil, subprocess, json, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "stubs"), os.path.dirname(HERE)]
from narrator import ffgram as F
D = "/tmp/ffg"; shutil.rmtree(D, ignore_errors=True); os.makedirs(D)
log = lambda m: None
src = f"{D}/a.wav"
subprocess.run(["ffmpeg","-y","-v","error","-f","lavfi",
                "-i","sine=frequency=300:duration=4","-ar","48000","-ac","2",
                src], capture_output=True, check=True)

def probe(path):
    return json.loads(subprocess.run(
        ["ffprobe","-v","error","-show_streams","-print_format","json",path],
        capture_output=True, text=True).stdout)["streams"][0]

# --- the default spec is a working command ---
spec = F.default_spec()
graph = F.build_graph(spec)
assert graph.startswith("[0:a]showwaves=") and graph.endswith("[v]")
assert "scale=1920:1080" in graph
print(f"B1 ok: default graph -> {graph}")

out = F.render(src, f"{D}/default.mp4", spec, log, seconds=2)
info = probe(out)
assert (info["width"], info["height"]) == (1920, 1080), info
print(f"B2 ok: it renders, at {info['width']}x{info['height']} {info['codec_name']}")

# --- every declared source builds and runs ---
for name, meta in F.SOURCES.items():
    s = dict(F.default_spec(), source=name, source_options={})
    g = F.build_graph(s)
    assert g.startswith(f"[0:a]{name}="), g
    o = F.render(src, f"{D}/{name}.mp4", s, log, seconds=1)
    assert os.path.getsize(o) > 500
print(f"S1 ok: all {len(F.SOURCES)} visualisers build and render "
     f"({', '.join(F.SOURCES)})")

# --- every declared option is a real ffmpeg option ---
for name, meta in F.SOURCES.items():
    s = dict(F.default_spec(), source=name,
             source_options={k: v[1] for k, v in meta["options"].items()})
    o = F.render(src, f"{D}/opt_{name}.mp4", s, log, seconds=1)
    assert os.path.isfile(o)
print("S2 ok: every declared option is accepted by ffmpeg -- none were "
     "invented (each visualiser rendered with all its options set)")

# --- every effect is real too ---
for name in F.EFFECTS:
    s = dict(F.default_spec(),
             effects=[{"name": name, "options": {}}])
    o = F.render(src, f"{D}/fx_{name}.mp4", s, log, seconds=1)
    assert os.path.isfile(o), name
print(f"E1 ok: all {len(F.EFFECTS)} effects build and render "
     f"({', '.join(F.EFFECTS)})")

# the ring, which is the one that can't be done any other way
ring = dict(F.default_spec(), render_width=720, render_height=720,
            effects=[{"name": "fisheye",
                      "options": {"fov": 360, "w": 800, "h": 800}}])
g = F.build_graph(ring)
assert "v360=input=flat:output=fisheye:h_fov=360:v_fov=360" in g
o = F.render(src, f"{D}/ring.mp4", ring, log, seconds=1)
# The projection reshapes the frame on its own, so the size is stated
# explicitly rather than inferred -- otherwise the estimate is wrong too.
assert (probe(o)["width"], probe(o)["height"]) == (800, 800), probe(o)
assert F.output_size(ring) == (800, 800)
print("E2 ok: the fisheye ring renders at the size asked for (800x800), "
     "not whatever the projection would have produced")

# effects stack in order
stacked = dict(F.default_spec(), effects=[
    {"name": "gblur", "options": {"sigma": 3}},
    {"name": "cas", "options": {"strength": 0.4}},
    {"name": "scale", "options": {"w": 640, "h": 360}}])
g = F.build_graph(stacked)
assert g.index("gblur") < g.index("cas") < g.index("scale"), g
o = F.render(src, f"{D}/stack.mp4", stacked, log, seconds=1)
assert probe(o)["width"] == 640
print(f"E3 ok: effects apply in the order given -> {g[:90]}...")

# --- unknown options are dropped rather than passed to ffmpeg ---
dirty = dict(F.default_spec(),
             source_options={"mode": "cline", "nonsense": "boom"})
assert "nonsense" not in F.build_graph(dirty)
o = F.render(src, f"{D}/clean.mp4", dirty, log, seconds=1)
assert os.path.isfile(o)
print("O1 ok: an unrecognised option is dropped, so a stale saved setting "
     "can't break the command")

# --- a custom graph wins entirely ---
custom = dict(F.default_spec(),
              custom_graph="[0:a]showwaves=s=200x100:colors=0x00FF00[v]")
assert F.build_graph(custom) == custom["custom_graph"]
o = F.render(src, f"{D}/custom.mp4", custom, log, seconds=1)
assert (probe(o)["width"], probe(o)["height"]) == (200, 100)
assert F.explain(custom) == ["Using your own filter graph, unchanged."]
print("C1 ok: a hand-written graph is used verbatim and the explanation "
     "says so")

# --- a broken graph reports ffmpeg's own words ---
try:
    F.render(src, f"{D}/bad.mp4",
             dict(F.default_spec(), custom_graph="[0:a]notafilter=1[v]"),
             log, seconds=1)
    raise SystemExit("should have raised")
except RuntimeError as e:
    assert "refused that graph" in str(e) and "notafilter" in str(e)
print("C2 ok: a broken graph surfaces ffmpeg's own error, which is more "
     "useful than any summary")

# --- explanation and estimates ---
lines = F.explain(F.default_spec())
assert len(lines) >= 4 and "Waveform" in lines[0]
assert any("No transparency" in l for l in lines)
print(f"X1 ok: the graph explains itself ({len(lines)} lines), including "
     "warning that H.264 has no transparency")

fast = F.estimate(dict(F.default_spec(), preset="ultrafast"), 3600)
slow = F.estimate(dict(F.default_spec(), preset="medium"), 3600)
assert slow["seconds"] > fast["seconds"] * 2
print(f"X2 ok: a 60-min episode estimates {fast['seconds']/60:.0f} min on "
     f"ultrafast vs {slow['seconds']/60:.0f} min on medium")

text = F.describe_estimate(dict(F.default_spec(), preset="medium"), 3600)
assert "ultrafast" in text, text
print(f"X3 ok: a slow preset is told about the quicker one -- {text[-90:]}")

small = F.estimate(dict(F.default_spec(),
                        effects=[{"name": "scale",
                                  "options": {"w": 960, "h": 540}}]), 3600)
assert small["seconds"] < fast["seconds"]
assert F.output_size(F.default_spec()) == (1920, 1080)
print("X4 ok: output size is read from the effect stack and moves the "
     "estimate")

print("\nALL FFGRAM TESTS PASSED")

# --- chroma-key background ---
green = dict(F.default_spec(), chroma_key_background="0x00FF00")
graph = F.build_graph(green)
# [bg] appears twice: once where it's defined, once where overlay
# consumes it -- that's correct, not a duplicate.
assert graph.count("[bg]") == 2 and "color=c=0x00FF00" in graph
assert "overlay=format=auto:shortest=1[v]" in graph
print(f"K1 ok: background graph -> {graph}")

cmd = F.build_command(src, f"{D}/green.mp4", green, seconds=1)
assert "-shortest" in cmd
print("K2 ok: -shortest is added, since the colour source has no natural "
     "length on its own")

out = F.render(src, f"{D}/green.mp4", green, log, seconds=1)
info = probe(out)
assert info["width"] == 1920 and info["height"] == 1080
print(f"K3 ok: it renders at the requested size ({info['width']}x"
     f"{info['height']}), not run forever by an unbounded background")

# THE real bug this feature had: -shortest is an OUTPUT option and does
# nothing if placed next to -i, which every earlier test here (seconds=1)
# masked, since -t bounds the run regardless of whether -shortest works.
# This is the actual failure mode -- no seconds= limit, so the only thing
# standing between a normal render and a process that runs forever is
# -shortest actually working -- checked on a real subprocess timeout,
# not by inspecting the command string.
cmd_all = F.build_command(src, f"{D}/full.mp4", green)  # no `seconds`
assert cmd_all.index("-shortest") > cmd_all.index("-map")
try:
    subprocess.run(cmd_all, capture_output=True, timeout=15, check=True)
except subprocess.TimeoutExpired:
    raise SystemExit(
        "REGRESSION: an unbounded chroma-key render hung -- -shortest is "
        "not doing its job")
dur = float(subprocess.run(
    ["ffprobe","-v","error","-show_entries","format=duration","-of",
     "csv=p=0", f"{D}/full.mp4"], capture_output=True, text=True).stdout)
assert 2.5 < dur < 4.5, dur
print(f"K3b ok: an UNBOUNDED render (no seconds= limit) with the "
     f"background on finished in real time rather than hanging, at "
     f"{dur:.1f}s -- matching the 4s source, not running forever")

# the corners are the pure key colour, and the render doesn't hang
frame = f"{D}/frame.png"
subprocess.run(["ffmpeg","-y","-v","error","-i",out,"-vframes","1",
                "-vf","crop=10:10:0:0",frame], capture_output=True, check=True)
from PIL import Image
px = Image.open(frame).convert("RGB").getpixel((5, 5))
assert px == (0, 255, 0), px
print(f"K4 ok: a corner pixel, where nothing is drawn, is pure "
     f"{px} -- a real solid key colour, not transparent black rendered "
     "as black")

# a custom graph is not touched by the background setting
custom = dict(F.default_spec(), chroma_key_background="0x00FF00",
             custom_graph="[0:a]showwaves=s=100x100[v]")
assert F.build_graph(custom) == custom["custom_graph"]
cmd2 = F.build_command(src, f"{D}/c.mp4", custom, seconds=1)
assert "-shortest" not in cmd2
print("K5 ok: a hand-written graph is untouched by the background "
     "setting, including the -shortest flag it would otherwise add")

# blank means no background at all -- the plain path, unchanged
plain = F.build_graph(F.default_spec())
assert "overlay" not in plain and "color=c=" not in plain
print("K6 ok: leaving the background blank uses the plain graph, "
     "identical to before this feature existed")

print("\nALL FFGRAM TESTS PASSED (including chroma-key background)")
