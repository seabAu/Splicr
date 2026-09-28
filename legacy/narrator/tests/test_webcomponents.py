import os, sys, shutil, time, json
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "stubs"), os.path.dirname(HERE)]
APP = os.path.dirname(HERE)
shutil.rmtree(os.path.join(APP, "narrator_data"), ignore_errors=True)
from fastapi.testclient import TestClient
from narrator import webapi, pipeline
c = TestClient(webapi.create_app())
H = {"X-Narrator-Token": webapi.TOKEN}

def wait(job_id, limit=800):
    for _ in range(limit):
        snap = c.get(f"/api/jobs/{job_id}", headers=H).json()
        if snap["status"] != "running":
            return snap
        time.sleep(0.5)
    raise AssertionError("job never finished")

# --- an unknown component/engine is a clean 404 ---
assert c.post("/api/components/install", headers=H,
              json={"key": "not-real"}).status_code == 404
assert c.post("/api/engines/not-real/install", headers=H).status_code == 404
print("N1 ok: an unknown component or engine is refused with 404")

# --- an external tool (ffmpeg) can't be auto-installed -- said plainly ---
r = c.post("/api/components/install", headers=H, json={"key": "ffmpeg"})
assert r.status_code == 400
assert "isn't something this can install" in r.text
print(f"N2 ok: asking to auto-install an external tool is refused with "
     f"a real reason: {r.json()['detail'][:70]}")

# --- installing a real pip component through the API ---
before = c.get("/api/components", headers=H).json()["components"]
fw = next(x for x in before if x["key"] == "faster-whisper")
if fw["installed"]:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "uninstall", "-y",
                    "--break-system-packages", "faster-whisper"],
                   capture_output=True)
job = c.post("/api/components/install", headers=H,
             json={"key": "faster-whisper"}).json()
snap = wait(job["id"])
assert snap["status"] == "done", snap
assert "ready" in snap["outcome"]
after = next(x for x in c.get("/api/components", headers=H).json()["components"]
            if x["key"] == "faster-whisper")
assert after["installed"] is True
print(f"I1 ok: really installed faster-whisper through the API "
     f"(outcome: {snap['outcome']!r}), and the component report now "
     "shows it installed")

# --- engine install, with the real download stubbed so this test doesn't
#     try to pull several GB ---
from narrator import setup_engines as se
stages = []
def fake_create(key, log=print, progress=None, use_gpu=True):
    stages.append(key)
    for i, label in enumerate(["Creating environment", "Installing torch",
                               "Installing qwen-tts"], 1):
        if progress:
            progress({"kind": "stage", "label": label, "step": i, "total": 3})
        log(label + "...")
    pipeline.ENGINES["Qwen3-TTS (offline, designed voices)"]["detect"] = \
        lambda: True
    return True
se.create_environment = fake_create

job2 = c.post("/api/engines/Qwen3-TTS (offline, designed voices)/install",
             headers=H).json()
snap2 = wait(job2["id"])
assert snap2["status"] == "done", snap2
assert stages == ["qwen3"]
assert any("Installing qwen-tts" in l for l in snap2["lines"])
print(f"I2 ok: engine install ran through create_environment and reported "
     f"its stages in the job log")

eng = c.get("/api/engines", headers=H).json()["engines"]
assert next(e for e in eng if e["key"] == "qwen3")["installed"] is True
print("I3 ok: the engine list reflects the install immediately, with no "
     "restart -- the probe cache was cleared")

# --- environments folder override ---
import tempfile
probe_calls = {"n": 0}
real_forget = None
try:
    from narrator.config import forget_engine_probes as real_forget
except ImportError:
    pass

def counting_forget():
    probe_calls["n"] += 1
    if real_forget:
        real_forget()

import narrator.webapi as webapi_mod
# Patch the module-level name the endpoint imports fresh each call, by
# patching where it's looked up from (config.forget_engine_probes) --
# the endpoint does `from .config import forget_engine_probes` inside
# the function body, so patching narrator.config's attribute is what
# actually takes effect.
import narrator.config as config_mod
config_mod.forget_engine_probes = counting_forget

bad_env = c.post("/api/engines/env-root", headers=H,
                 json={"path": "/no/such/env/folder"})
assert bad_env.status_code == 400
print("V1 ok: an env-root path that doesn't exist is refused with a "
     "clean 400")

real_dir = tempfile.mkdtemp()
good_env = c.post("/api/engines/env-root", headers=H,
                  json={"path": real_dir})
assert good_env.status_code == 200
assert good_env.json()["env_root"] == real_dir
settings_after = c.get("/api/settings", headers=H).json()["settings"]
assert settings_after["env_root"] == real_dir
assert probe_calls["n"] >= 1
print(f"V2 ok: a valid env-root path is saved to settings and clears "
     f"the probe cache ({probe_calls['n']} call(s)), so the change "
     "takes effect without restarting")

clear_env = c.post("/api/engines/env-root", headers=H, json={"path": ""})
assert clear_env.status_code == 200
settings_cleared = c.get("/api/settings", headers=H).json()["settings"]
assert "env_root" not in settings_cleared
print("V3 ok: an empty path clears the override, going back to the "
     "app's own folder")

print("\nALL WEB COMPONENT TESTS PASSED")
