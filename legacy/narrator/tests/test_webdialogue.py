import os, sys, shutil, time, json, socket, subprocess
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "stubs"), os.path.dirname(HERE)]
os.environ["STUB_LOG"] = "/tmp/wdlg.jsonl"
APP = os.path.dirname(HERE)
shutil.rmtree(os.path.join(APP, "narrator_data"), ignore_errors=True)
shutil.rmtree(os.path.join(APP, "narrator_output"), ignore_errors=True)
D = "/tmp/wdlg"; shutil.rmtree(D, ignore_errors=True); os.makedirs(D)
doc = f"{D}/ep.md"
open(doc, "w").write("# One\n\nAlpha material here.\n\n## Two\n\nBeta "
                     "material here.\n\n## Three\n\nGamma material here.\n")
from fastapi.testclient import TestClient
from narrator import webapi
from mockllm import Mock
c = TestClient(webapi.create_app())
H = {"X-Narrator-Token": webapi.TOKEN}

def wait(job_id, limit=300):
    for _ in range(limit):
        snap = c.get(f"/api/jobs/{job_id}", headers=H).json()
        if snap["status"] != "running":
            return snap
        time.sleep(0.25)
    raise AssertionError("job never finished")

srv = Mock(require_key="k-good", models=["test-model"])

# --- providers, with the key never coming back in full ---
r = c.get("/api/llm/providers", headers=H).json()
assert r["providers"] == {} and len(r["templates"]) == 10
assert all(not t["needs_key"] for t in r["templates"].values() if t["local"])
print(f"P1 ok: {len(r['templates'])} templates, none local requiring a key")

c.post("/api/llm/providers", headers=H, json={"name": "mine", "config": {
    "base_url": srv.base, "api_key": "k-good", "model": "test-model"}})
p = c.get("/api/llm/providers", headers=H).json()["providers"]["mine"]
assert "k-good" not in json.dumps(p) and p["has_key"] is True
print(f"P2 ok: the key comes back masked as {p['api_key']!r}, never in full")

# saving with a blank key keeps the stored one -- what lets a UI show the
# mask and send it back harmlessly
c.post("/api/llm/providers", headers=H, json={
    "name": "mine", "config": {"model": "test-model", "api_key": ""}})
v = c.post("/api/llm/verify", headers=H, json={"name": "mine"}).json()
assert v["ok"], v["stages"]
print("P3 ok: re-saving with a blank key kept the working key -- verify "
     "still passes all five stages")

bad = c.post("/api/llm/providers", headers=H, json={"name": "bad", "config": {
    "base_url": srv.base, "api_key": "wrong", "model": "test-model"}})
vb = c.post("/api/llm/verify", headers=H, json={"name": "bad"}).json()
assert not vb["ok"] and vb["stages"][-1]["stage"] == "Key accepted"
print(f"P4 ok: a bad key stops at the right stage: "
     f"{vb['stages'][-1]['detail'][:50]}")

# --- script generation ---
job = c.post("/api/dialogue/script", headers=H, json={
    "document": doc, "provider": "mine",
    "options": {"words_per_section": 60}}).json()
snap = wait(job["id"])
assert snap["status"] == "done", snap
turns = snap["result"]["turns"]
assert len(turns) >= 4
for a, b in zip(turns, turns[1:]):
    assert a["speaker"] != b["speaker"]
assert any("3 section" in l for l in snap["lines"]), snap["lines"]
print(f"S1 ok: {len(turns)} alternating turns from 3 real sections "
     f"(headings survived cleaning)")

# --- the script round-trips through the tagged text the UI edits ---
from narrator import dialogue as DG
text = DG.script_to_text(turns)
assert DG.parse_turns(text) == turns
edited = text.replace(turns[0]["text"], "A line I rewrote myself.")
reparsed = DG.parse_turns(edited)
assert reparsed[0]["text"] == "A line I rewrote myself."
assert len(reparsed) == len(turns)
print("S2 ok: the script round-trips through its text form, and a "
     "hand-edited line survives re-parsing -- which is what makes the "
     "editable box safe")

# --- the sample signoff and the full render ---
cfg = {"path": doc, "root": D, "engine": "Kokoro (offline, best all-round)",
       "voice": "af_heart", "format": "MP3 (most compatible)"}
sign = wait(c.post("/api/dialogue/signoff", headers=H, json={
    "cfg": cfg, "voice1": "af_heart", "voice2": "am_michael"}).json()["id"])
assert sign["status"] == "done"
assert os.path.isfile(sign["result"]["output"])
print(f"G1 ok: the sample signoff renders a real two-voice clip "
     f"({os.path.basename(sign['result']['output'])})")

full = wait(c.post("/api/dialogue/render", headers=H, json={
    "cfg": cfg, "turns": reparsed,
    "voice1": "af_heart", "voice2": "am_michael"}).json()["id"])
assert full["status"] == "done", full
out = full["result"]["output"]
assert os.path.isfile(out)
print(f"G2 ok: the EDITED script rendered -> {os.path.basename(out)}")

# it becomes an ordinary take
takes = c.get("/api/takes", headers=H).json()["takes"]
assert any(t["out_path"] == out for t in takes)
jobs = c.get("/api/jobs", headers=H, params={"kind": "dialogue"}).json()["jobs"]
assert jobs[0]["detail"]["voices"] == "af_heart / am_michael"
print("G3 ok: it lands as an ordinary take, and its job records the "
     "voices used")

srv.stop()

# --- the refine endpoint: one selected span, rewritten in place ---
srv2 = Mock(require_key="k-good", models=["test-model"])
c.post("/api/llm/providers", headers=H, json={"name": "editor", "config": {
    "base_url": srv2.base, "api_key": "k-good", "model": "test-model"}})

r = c.post("/api/dialogue/refine", headers=H, json={
    "provider": "editor", "speaker": "Person1",
    "before": "So, ", "selected": "let's discuss the weather",
    "after": " today.", "instruction": "make it about tides instead"})
assert r.status_code == 200, r.text
body = r.json()
assert "make it about tides instead" in body["replacement"]
print(f"F1 ok: /api/dialogue/refine rewrites a span per the "
     f"instruction: {body['replacement']!r}")

# an unknown provider name is a clean 404, not a 500
r2 = c.post("/api/dialogue/refine", headers=H, json={
    "provider": "no-such-provider", "speaker": "Person1",
    "before": "", "selected": "text", "after": "",
    "instruction": "anything"})
assert r2.status_code == 404
print("F2 ok: refining with an unknown provider name is a clean 404")

# an empty selection is a clean 400, not a silent no-op or a crash
r3 = c.post("/api/dialogue/refine", headers=H, json={
    "provider": "editor", "speaker": "Person1",
    "before": "text", "selected": "   ", "after": "",
    "instruction": "anything"})
assert r3.status_code == 400
print("F3 ok: an empty selection is a clean 400, not a silent failure")

# neighboring turns pass through the HTTP layer intact, not just when
# calling refine_selection() directly in-process
r4 = c.post("/api/dialogue/refine", headers=H, json={
    "provider": "editor", "speaker": "Person2",
    "before": "", "selected": "sure", "after": "",
    "instruction": "sound more confident",
    "neighbor_before": {"speaker": "Person1", "text": "Is that right?"},
    "neighbor_after": None})
assert r4.status_code == 200, r4.text
sent = srv2.seen[-1]["messages"][-1]["content"]
assert "Is that right?" in sent
print("F4 ok: neighbor-turn context survives the HTTP request boundary "
     "(dicts round-trip through pydantic correctly)")

srv2.stop()

# --- /api/voices: engine-specific filtering for the dialogue voice picker ---
from narrator import engines as engines_mod
subprocess = __import__("subprocess")
ref = f"{D}/ref_for_voices.wav"
subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                "-i", "sine=frequency=180:duration=4", "-ar", "44100", ref],
               capture_output=True, check=True)
q_folder = engines_mod.clone_voice_from_recording(
    ref, "A voice for the dialogue picker test.", "web-test qwen voice",
    print, engine_tag="qwen3")
a_folder = engines_mod.clone_voice_from_recording(
    ref, "A voice for the dialogue picker test.", "web-test audio8 voice",
    print, engine_tag="audio8", min_seconds=3.0)

r_all = c.get("/api/voices", headers=H).json()["voices"]
ids_all = {v["id"] for v in r_all}
assert q_folder in ids_all and a_folder in ids_all
print(f"V1 ok: /api/voices with no filter lists both engines' clones "
     f"({len(r_all)} total)")

r_q = c.get("/api/voices", headers=H, params={"engine": "qwen3"}).json()
q_ids = {v["id"] for v in r_q["voices"]}
assert q_folder in q_ids and a_folder not in q_ids
print("V2 ok: filtering by engine=qwen3 excludes the Audio8 clone -- "
     "the actual gap this closes, since offering the wrong engine's "
     "voice would fail deep inside a render")

r_a = c.get("/api/voices", headers=H, params={"engine": "audio8"}).json()
a_ids = {v["id"] for v in r_a["voices"]}
assert a_folder in a_ids and q_folder not in a_ids
print("V3 ok: filtering by engine=audio8 excludes the Qwen3 clone, "
     "symmetrically")

# a voice with no folder (a CustomVoice preset) is never offered here --
# the dialogue editor has no way to encode one into a render request
assert all(v["id"] for v in r_all), "a voice with no usable id leaked through"
print("V4 ok: folder-less voices (CustomVoice presets) are filtered out, "
     "since the dialogue editor can't use them")

print("\nALL WEB DIALOGUE TESTS PASSED")
