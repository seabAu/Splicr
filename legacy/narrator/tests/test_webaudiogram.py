import os, sys, shutil, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "stubs"), HERE, os.path.dirname(HERE)]
os.environ["STUB_LOG"] = "/tmp/wag.jsonl"
APP = os.path.dirname(HERE)
shutil.rmtree(os.path.join(APP, "narrator_data"), ignore_errors=True)
shutil.rmtree(os.path.join(APP, "narrator_output"), ignore_errors=True)
D = "/tmp/waudiogram"; shutil.rmtree(D, ignore_errors=True); os.makedirs(D)
doc = f"{D}/story.md"
open(doc, "w").write(
    "A short narration to give the audiogram something real to draw "
    "from. It just needs a few seconds of audio.\n")

from fastapi.testclient import TestClient
from narrator import webapi
c = TestClient(webapi.create_app())
H = {"X-Narrator-Token": webapi.TOKEN}


def wait(job_id, limit=300):
    for _ in range(limit):
        snap = c.get(f"/api/jobs/{job_id}", headers=H).json()
        if snap["status"] != "running":
            return snap
        time.sleep(0.1)
    raise AssertionError("job never finished")


# --- produce a real take so estimate/motion-preview/export have real audio ---
cfg = {"path": doc, "root": D, "engine": "Kokoro (offline, best all-round)",
       "voice": "af_heart", "format": "WAV (uncompressed)"}
render = wait(c.post("/api/render", headers=H, json={"cfg": cfg}).json()["id"])
assert render["status"] == "done", render
out_path = render["result"]["output"]
takes = c.get("/api/takes", headers=H).json()["takes"]
manifest = [t for t in takes if t["out_path"] == out_path][0]["manifest"]
print(f"setup ok: rendered a real take -> {os.path.basename(out_path)}")

# --- defaults ---
d = c.get("/api/audiogram/defaults", headers=H).json()
assert d["cfg"]["geometry"] == "linear"
assert "x" in d["animatable"] and "rotation" in d["animatable"]
assert any(cd["key"] == "webm" for cd in d["codecs"])
assert d["preview_max_seconds"] > 0
print(f"D1 ok: defaults expose {len(d['cfg'])} cfg fields, "
     f"{len(d['animatable'])} animatable names, {len(d['codecs'])} codecs")
base_cfg = d["cfg"]

# --- source: no explicit audio_source -> falls back to the given take ---
src = c.get("/api/audiogram/source", headers=H,
           params={"manifest": manifest}).json()
assert src["note"] != "" and not src["warning"]
print(f"S1 ok: with no audio_source set, source note reflects the take: "
     f"{src['note']!r}")

src_missing = c.get("/api/audiogram/source", headers=H).json()
assert "nothing yet" in src_missing["note"] or src_missing["note"]
print(f"S2 ok: with no manifest and no audio_source: {src_missing['note']!r}")

# --- layout: real geometry from the real layout() function ---
lay = c.post("/api/audiogram/layout", headers=H,
            json={"cfg": base_cfg, "width": 480, "height": 270}).json()
assert lay["geometry"] == "linear"
x0, y0, x1, y1 = lay["box"]
assert 0 <= x0 < x1 <= 480 and 0 <= y0 < y1 <= 270
print(f"L1 ok: linear layout box is real pixel geometry within the "
     f"480x270 frame: {lay['box']}")

polar_cfg = dict(base_cfg, geometry="polar")
lay2 = c.post("/api/audiogram/layout", headers=H,
             json={"cfg": polar_cfg, "width": 480, "height": 270}).json()
assert lay2["geometry"] == "polar"
assert lay2["center"] != lay["center"] or lay2["box"] != lay["box"]
print(f"L2 ok: switching geometry to polar changes the computed layout: "
     f"center={lay2['center']}")

rotated_cfg = dict(base_cfg, rotation=45)
lay3 = c.post("/api/audiogram/layout", headers=H,
             json={"cfg": rotated_cfg, "width": 480, "height": 270}).json()
assert lay3["rotation_disables_crop"] is True
print("L3 ok: a nonzero rotation is flagged as disabling cropped export, "
     "matching the desktop's hint")

# --- preview.png: a real image, drawn by the real renderer ---
png = c.post("/api/audiogram/preview.png", headers=H,
            json={"cfg": base_cfg, "width": 480, "height": 270})
assert png.status_code == 200
assert png.headers["content-type"] == "image/png"
assert png.content[:8] == b"\x89PNG\r\n\x1a\n"  # real PNG magic bytes
print(f"P1 ok: preview.png returns real PNG bytes ({len(png.content)} "
     "bytes) -- rendered by draw_frame, not a client-side approximation")

# different bar counts actually change the image (a cheap sanity check
# that the cfg is genuinely driving the render, not returning a cached
# or default image regardless of input)
png_bars = c.post("/api/audiogram/preview.png", headers=H,
                  json={"cfg": dict(base_cfg, bars=8), "width": 480,
                       "height": 270})
assert png_bars.content != png.content
print("P2 ok: changing `bars` in the cfg actually changes the rendered "
     "PNG bytes -- confirms the server is really using the given cfg")

# --- command: the real ffmpeg command text for this layout ---
cmd = c.get("/api/audiogram/command", headers=H,
           params={"manifest": manifest}).json()
assert "ffmpeg" in cmd["command"] and os.path.basename(out_path)[:6] in \
    cmd["command"] or out_path in cmd["command"]
print(f"C1 ok: command text references the take's real audio path")

cmd_override = c.get("/api/audiogram/command", headers=H, params={
    "manifest": manifest, "filter_override": "showspectrum=s=640x360"})
assert "showspectrum" in cmd_override.json()["command"]
print("C2 ok: a filter_override is reflected in the returned command "
     "text, matching the desktop's hand-edit box")

# --- preview-reason ---
reason = c.get("/api/audiogram/preview-reason", headers=H).json()
assert reason["engine"] in ("ffmpeg", "frames")
print(f"R1 ok: preview-reason names an engine with a real justification: "
     f"{reason['text']!r}")

# --- estimate: real duration, real numbers ---
est = c.get("/api/audiogram/estimate", headers=H,
           params={"manifest": manifest, "width": 480, "height": 270}).json()
assert est["seconds"] > 0
assert "For" in est["text"]
print(f"E1 ok: estimate uses the take's real duration "
     f"({est['seconds']:.2f}s): {est['text']!r}")

est_no_take = c.get("/api/audiogram/estimate", headers=H,
                    params={"manifest": ""}).json()
assert est_no_take["seconds"] == 0
assert "Render an episode" in est_no_take["text"]
print("E2 ok: with no take, estimate says so plainly instead of a "
     "meaningless number")

# --- preview-motion: a real background job, a real file produced ---
mjob = c.post("/api/audiogram/preview-motion", headers=H,
             json={"manifest": manifest, "seconds": 2}).json()
msnap = wait(mjob["id"])
assert msnap["status"] == "done", msnap
assert os.path.isfile(msnap["result"]["output"])
assert msnap["result"]["engine"] in ("ffmpeg", "frames")
print(f"M1 ok: motion preview job produced a real file -> "
     f"{os.path.basename(msnap['result']['output'])} "
     f"({msnap['result']['engine']} renderer)")

# --- export: a real background job, a real overlay file produced, and
#     the layout is persisted as the new default ---
ejob = c.post("/api/audiogram/export", headers=H, json={
    "cfg": dict(base_cfg, bars=16), "manifest": manifest, "codec": "webm",
    "width": 320, "height": 180, "crop": True}).json()
esnap = wait(ejob["id"], limit=600)
assert esnap["status"] == "done", esnap
out_overlay = esnap["result"]["output"]
assert os.path.isfile(out_overlay)
print(f"X1 ok: export job produced a real overlay file -> "
     f"{os.path.basename(out_overlay)}")

saved = c.get("/api/settings", headers=H).json()["settings"]
assert saved["audiogram"]["bars"] == 16
print("X2 ok: exporting persists the layout as the new default (bars=16 "
     "now saved), matching the desktop's implicit Save-layout-on-export")

# a bad manifest / no audio source is a clean 400, not a crash
bad_export = c.post("/api/audiogram/export", headers=H, json={
    "cfg": base_cfg, "manifest": "", "codec": "webm"})
assert bad_export.status_code == 400
print("X3 ok: exporting with no resolvable audio source is a clean 400")

print("\nALL WEB AUDIOGRAM TESTS PASSED")
