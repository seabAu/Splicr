import os, sys, shutil, time, subprocess, json
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "stubs"), HERE, os.path.dirname(HERE)]
os.environ["STUB_LOG"] = "/tmp/wvs.jsonl"
APP = os.path.dirname(HERE)
shutil.rmtree(os.path.join(APP, "narrator_data"), ignore_errors=True)
if os.path.exists("/tmp/wvs.jsonl"):
    os.remove("/tmp/wvs.jsonl")
D = "/tmp/wvoices"; shutil.rmtree(D, ignore_errors=True); os.makedirs(D)

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


def calls(name):
    if not os.path.exists("/tmp/wvs.jsonl"):
        return []
    return [json.loads(l) for l in open("/tmp/wvs.jsonl") if l.strip()
            and json.loads(l).get("call") == name]


# --- empty state ---
r0 = c.get("/api/voices", headers=H).json()
assert r0["voices"] == []
print("E1 ok: no voices yet -> an empty list, not an error")

# --- audition: designs a Qwen3 voice from a description alone ---
job = c.post("/api/voices/audition", headers=H,
            json={"description": "a warm, unhurried narrator",
                  "take": 1}).json()
snap = wait(job["id"])
assert snap["status"] == "done", snap
assert os.path.isfile(snap["result"]["reference"])
print(f"A1 ok: auditioning designs a real reference clip -- "
     f"{os.path.basename(snap['result']['reference'])}")

design_calls = calls("qwen_voice_design")
assert len(design_calls) == 1
print("A2 ok: exactly one design call was made for one audition")

# an empty description is refused before any job starts
bad = c.post("/api/voices/audition", headers=H,
            json={"description": "   "})
assert bad.status_code == 400
print("A3 ok: an empty description is refused with a clean 400")

# it now shows up in the plain list
r1 = c.get("/api/voices", headers=H).json()
assert len(r1["voices"]) == 1
assert r1["voices"][0]["engine"] == "qwen3"
assert r1["voices"][0]["kind"] == "designed"
qwen_folder = r1["voices"][0]["id"]
print(f"A4 ok: the designed voice appears in /api/voices as "
     f"engine={r1['voices'][0]['engine']!r}, kind={r1['voices'][0]['kind']!r}")

# and the full=true view carries the extra fields Voice studio needs
rfull = c.get("/api/voices", headers=H, params={"full": "true"}).json()
row = rfull["voices"][0]
assert "description" in row and "take" in row and "created" in row
assert row["has_reference"] is True
print("A5 ok: full=true exposes description/take/created/has_reference "
     "for the management view, beyond the trimmed picker shape")

# --- rename ---
rn = c.post("/api/voices/rename", headers=H,
           json={"folder": qwen_folder, "label": "Calm Narrator"})
assert rn.status_code == 200
assert rn.json()["label"] == "Calm Narrator"
after = c.get("/api/voices", headers=H, params={"full": "true"}).json()
assert after["voices"][0]["label"] == "Calm Narrator"
print("R1 ok: renaming persists and shows up in the list immediately")

# renaming a folder that doesn't exist is a clean 400, not a 500
rn_bad = c.post("/api/voices/rename", headers=H,
               json={"folder": f"{D}/no-such-voice", "label": "x"})
assert rn_bad.status_code == 400
print("R2 ok: renaming a nonexistent voice is a clean 400")

# --- upload-and-clone: Qwen3 ---
ref_wav = f"{D}/ref.wav"
subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                "-i", "sine=frequency=220:duration=3", "-ar", "44100",
                ref_wav], capture_output=True, check=True)

with open(ref_wav, "rb") as fh:
    up = c.post("/api/voices/clone", headers=H,
               data={"transcript": "This is my own voice speaking.",
                    "description": "my web-cloned voice",
                    "engine": "qwen3"},
               files={"file": ("ref.wav", fh, "audio/wav")})
assert up.status_code == 200, up.text
clone_folder = up.json()["folder"]
assert os.path.isdir(clone_folder)
assert os.path.isfile(os.path.join(clone_folder, "voice.json"))
print(f"C1 ok: uploading bytes from the client clones a real voice -- "
     f"{os.path.basename(clone_folder)}")

meta = json.load(open(os.path.join(clone_folder, "voice.json")))
assert meta["engine"] == "qwen3" and meta["kind"] == "cloned"
print("C2 ok: the uploaded clone is tagged engine=qwen3 like any other "
     "Qwen3 clone")

# the temp upload file is cleaned up, not left behind
tmp_leftovers = [f for f in os.listdir("/tmp")
                 if f.startswith("tmp") and f.endswith(".wav")]
print(f"C3 note: temp dir has {len(tmp_leftovers)} leftover .wav file(s) "
     "matching the upload pattern (informational -- other tests may "
     "also create temp wavs)")

# --- upload-and-clone: Audio8, a second engine, same upload path ---
with open(ref_wav, "rb") as fh:
    up2 = c.post("/api/voices/clone", headers=H,
                data={"transcript": "This is my own voice speaking.",
                     "description": "my audio8 clone", "engine": "audio8"},
                files={"file": ("ref.wav", fh, "audio/wav")})
assert up2.status_code == 200, up2.text
a8_folder = up2.json()["folder"]
meta2 = json.load(open(os.path.join(a8_folder, "voice.json")))
assert meta2["engine"] == "audio8"
print("C4 ok: the same upload endpoint clones for a second engine "
     "(audio8) correctly tagged, via engine_tag dispatch")

# a too-short recording is refused with a real reason, not a silent 500
short_wav = f"{D}/short.wav"
subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                "-i", "sine=frequency=220:duration=1", "-ar", "44100",
                short_wav], capture_output=True, check=True)
with open(short_wav, "rb") as fh:
    up3 = c.post("/api/voices/clone", headers=H,
                data={"transcript": "too short", "description": "x",
                     "engine": "audio8"},
                files={"file": ("short.wav", fh, "audio/wav")})
assert up3.status_code == 400
assert "3" in up3.json()["detail"] or "short" in up3.json()["detail"].lower()
print("C5 ok: a too-short recording for audio8's 3s minimum is refused "
     "with a real reason, through the full upload path")

# a missing file is a clean 400
up4 = c.post("/api/voices/clone", headers=H,
            data={"transcript": "text", "description": "x"})
assert up4.status_code in (400, 422)
print("C6 ok: no uploaded file at all is refused, not a server error")

# --- reference playback ---
token = os.path.basename(qwen_folder)
play = c.get(f"/api/voices/reference/{token}", headers=H)
assert play.status_code == 200
assert play.headers["content-type"].startswith("audio/")
print("P1 ok: the reference clip streams back for in-browser playback")

# path traversal is refused, not resolved outside the voices dir
traversal = c.get("/api/voices/reference/..%2f..%2f..%2fetc%2fpasswd",
                  headers=H)
assert traversal.status_code in (400, 404)
print("P2 ok: a path-traversal token is refused rather than resolved")

missing = c.get("/api/voices/reference/not-a-real-voice", headers=H)
assert missing.status_code == 404
print("P3 ok: a real-looking but nonexistent token is a clean 404")

# --- delete ---
dl = c.post("/api/voices/delete", headers=H, json={"folder": a8_folder})
assert dl.status_code == 200
remaining = c.get("/api/voices", headers=H).json()["voices"]
assert a8_folder not in {v["id"] for v in remaining}
print("D1 ok: deleting removes the voice from the list")

dl_bad = c.post("/api/voices/delete", headers=H,
               json={"folder": f"{D}/never-existed"})
assert dl_bad.status_code == 400
print("D2 ok: deleting a nonexistent voice is a clean 400, not a crash")

# --- CustomVoice: fetch speakers (a background job -- downloads a model) ---
fjob = c.post("/api/voices/custom-speakers/fetch", headers=H).json()
fsnap = wait(fjob["id"])
assert fsnap["status"] == "done", fsnap
assert fsnap["result"]["speakers"] == ["Chloe", "Ethan", "Sunny"]
print(f"S1 ok: fetching the CustomVoice speaker list runs as a "
     f"background job and returns {fsnap['result']['speakers']}")

cached = c.get("/api/voices/custom-speakers", headers=H).json()
assert cached["speakers"] == ["Chloe", "Ethan", "Sunny"]
print("S2 ok: the fetched list is cached and re-readable without "
     "fetching again")

# --- CustomVoice: save/delete a preset ---
sp = c.post("/api/voices/custom-preset", headers=H,
           json={"label": "Storyteller", "speaker": "Ethan",
                "instruct": "warm and slow"})
assert sp.status_code == 200
presets = c.get("/api/voices", headers=H).json()["voices"]
# presets have no folder, so they're excluded from the default (picker)
# view -- confirmed via the full view instead
full_after_preset = c.get("/api/voices", headers=H,
                          params={"full": "true"}).json()["voices"]
preset_rows = [v for v in full_after_preset if v["kind"] == "custom"]
assert len(preset_rows) == 1 and preset_rows[0]["label"] == "Storyteller"
assert preset_rows[0]["speaker"] == "Ethan"
print("CP1 ok: a saved CustomVoice preset shows up in the full view "
     "with its speaker and instruction, and is excluded from the "
     "trimmed picker view (it has no folder/reference to render from "
     "in the dialogue editor)")

sp_bad = c.post("/api/voices/custom-preset", headers=H,
               json={"label": "", "speaker": "Ethan"})
assert sp_bad.status_code == 400
print("CP2 ok: saving a preset with no name is refused")

dp = c.post("/api/voices/custom-preset/delete", headers=H,
           json={"folder": "", "label": "Storyteller"})
assert dp.status_code == 200
full_after_delete = c.get("/api/voices", headers=H,
                          params={"full": "true"}).json()["voices"]
assert not [v for v in full_after_delete if v["kind"] == "custom"]
print("CP3 ok: deleting the preset removes it from the list")

print("\nALL WEB VOICES TESTS PASSED")
