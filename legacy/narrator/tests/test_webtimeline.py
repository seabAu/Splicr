import os, sys, shutil, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "stubs"), HERE, os.path.dirname(HERE)]
os.environ["STUB_LOG"] = "/tmp/wtl.jsonl"
APP = os.path.dirname(HERE)
shutil.rmtree(os.path.join(APP, "narrator_data"), ignore_errors=True)
shutil.rmtree(os.path.join(APP, "narrator_output"), ignore_errors=True)
D = "/tmp/wtimeline"; shutil.rmtree(D, ignore_errors=True); os.makedirs(D)
doc = f"{D}/story.md"
open(doc, "w").write(
    "This is the first sentence of the story. Here is a second one to "
    "give the timeline something real to split. And a third sentence "
    "closes things out nicely.\n")

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


# --- produce a real take to open in the timeline ---
cfg = {"path": doc, "root": D, "engine": "Kokoro (offline, best all-round)",
       "voice": "af_heart", "format": "WAV (uncompressed)"}
render = wait(c.post("/api/render", headers=H, json={"cfg": cfg}).json()["id"])
assert render["status"] == "done", render
out_path = render["result"]["output"]
print(f"setup ok: rendered a real take -> {os.path.basename(out_path)}")

takes = c.get("/api/takes", headers=H).json()["takes"]
mine = [t for t in takes if t["out_path"] == out_path][0]
manifest = mine["manifest"]
assert os.path.isfile(manifest)
print(f"T0 ok: /api/takes exposes a manifest path, and the file is real: "
     f"{os.path.basename(manifest)}")

# --- /api/timeline: the flattened sentence view + waveform ---
tl = c.get("/api/timeline", headers=H, params={"manifest": manifest}).json()
assert tl["engine"] == "kokoro"
assert tl["duration"] > 0
assert len(tl["sentences"]) >= 3
for a, b in zip(tl["sentences"], tl["sentences"][1:]):
    assert a["end"] <= b["start"] + 0.01, (a, b)  # in time order
print(f"T1 ok: {len(tl['sentences'])} sentences in time order, "
     f"duration {tl['duration']:.2f}s")

assert isinstance(tl["waveform"], list) and len(tl["waveform"]) > 0
assert all(0.0 <= v <= 1.0 for v in tl["waveform"])
print(f"T2 ok: a real waveform envelope came back "
     f"({len(tl['waveform'])} buckets, values in [0,1])")

first = tl["sentences"][0]
assert "first sentence" in first["text"].lower()
print(f"T3 ok: sentence text matches the source document: "
     f"{first['text']!r}")

# a manifest that doesn't exist is a clean 404
missing = c.get("/api/timeline", headers=H,
                params={"manifest": f"{D}/no-such-manifest.json"})
assert missing.status_code == 404
print("T4 ok: opening a nonexistent manifest is a clean 404")

# --- /api/timeline/span: extract a real audio clip ---
span = c.get("/api/timeline/span", headers=H, params={
    "manifest": manifest, "start": first["start"], "end": first["end"]})
assert span.status_code == 200
assert span.headers["content-type"].startswith("audio/")
assert len(span.content) > 100
print(f"S1 ok: extracting the first sentence's span returns real audio "
     f"bytes ({len(span.content)} bytes)")

# --- /api/timeline/words: Kokoro-only per-word detail ---
words = c.get("/api/timeline/words", headers=H, params={
    "manifest": manifest, "text": first["text"]}).json()
assert len(words["words"]) > 0
assert all("word" in w and "phonemes" in w and "source" in w
          for w in words["words"])
print(f"W1 ok: per-word pronunciation detail for a Kokoro take -- "
     f"{len(words['words'])} words, e.g. {words['words'][0]}")

# --- /api/timeline/resplice: re-record one sentence in place ---
rjob = c.post("/api/timeline/resplice", headers=H, json={
    "manifest": manifest, "chunk": first["chunk"], "seg": first["seg"],
    "text": "This sentence has been re-recorded with new words."}).json()
rsnap = wait(rjob["id"])
assert rsnap["status"] == "done", rsnap
new_out = rsnap["result"]["output"]
assert os.path.isfile(new_out)
print(f"R1 ok: resplicing a sentence rebuilds the take -> "
     f"{os.path.basename(new_out)}")

# reopening the timeline after a resplice reflects the edited text
tl2 = c.get("/api/timeline", headers=H,
           params={"manifest": manifest}).json()
assert "re-recorded with new words" in tl2["sentences"][0]["text"]
print("R2 ok: reopening the timeline after resplicing shows the "
     "updated sentence text, not the stale original")

# an empty replacement is refused before any rendering happens
empty = c.post("/api/timeline/resplice", headers=H, json={
    "manifest": manifest, "chunk": 0, "seg": 0, "text": "   "})
assert empty.status_code == 400
print("R3 ok: an empty replacement sentence is refused with a clean 400")

# resplicing against a bogus manifest is a clean 404, not a crash
bad = c.post("/api/timeline/resplice", headers=H, json={
    "manifest": f"{D}/nope.json", "chunk": 0, "seg": 0, "text": "hi"})
assert bad.status_code == 404
print("R4 ok: resplicing against a nonexistent manifest is a clean 404")

print("\nALL WEB TIMELINE TESTS PASSED")
