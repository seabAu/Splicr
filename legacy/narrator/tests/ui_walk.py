"""Walk the real web UI in headless Chromium and screenshot it.

Not run by run_all.py (it needs Playwright + a Chromium build, which
aren't always present). Run from the repo root after `npm run build`:

    python tests/ui_walk.py OUT_DIR [render] STEP...

Steps: tab:<name>  click:<exact text>  role:<role>=<name>  wait:<secs>
       advanced  shot:<file-stem>
"render" (must be first) does a real stubbed-Kokoro render before the
browser opens, so Timeline/Publish/Library show real UI, not an empty
state. NO_ENGINES=1 leaves every engine uninstalled.

Prints any console/page errors at the end -- this is what caught the
Publish crash (missing Select import) and the Providers-panel crash
that blanked the whole app, neither of which a build or the backend
tests could see. Example full walk:

    python tests/ui_walk.py /tmp/shots render tab:Library tab:Timeline \\
        tab:Audiogram tab:Publish "tab:Voice studio" tab:Dialogue \\
        "click:Providers…" wait:1 click:Hide tab:Pronunciation \\
        tab:Components wait:2 tab:Convert shot:final
"""
# Serves the real built app via uvicorn (same as `python -m narrator web`)
# and screenshots it in headless Chromium. Engines' detect() is forced
# True so the forms show real voice lists without real TTS installed.
import os, sys, threading, time, socket
sys.path[:0] = ["tests/stubs", "."]
from narrator import webapi, pipeline
for spec in pipeline.ENGINES.values():
    # NO_ENGINES=1 leaves every engine uninstalled, to see that state.
    spec["detect"] = (lambda: False) if os.environ.get("NO_ENGINES") else (lambda: True)
import uvicorn
from playwright.sync_api import sync_playwright

s = socket.socket(); s.bind(("127.0.0.1", 0)); PORT = s.getsockname()[1]; s.close()
app = webapi.create_app(static_dir="narrator/webui")
cfg = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="error")
srv = uvicorn.Server(cfg)
threading.Thread(target=srv.run, daemon=True).start()
while not srv.started: time.sleep(0.05)

OUT = sys.argv[1] if len(sys.argv) > 1 else "/tmp/shots"

# "render" as the first step: produce a real take (through the stubbed
# Kokoro) before the browser opens, so Timeline/Publish/Library/Audiogram
# show their actual UI instead of an empty state.
if len(sys.argv) > 2 and sys.argv[2] == "render":
    import json, urllib.request
    os.makedirs("/tmp/shotdoc", exist_ok=True)
    doc = "/tmp/shotdoc/Chapter One.md"
    open(doc, "w").write("# Chapter One\n\nThis is the first sentence of the story. "
        "Here is a second one, a little longer, to give the timeline something "
        "real to split. And a third sentence closes things out nicely.\n")
    H = {"X-Narrator-Token": webapi.TOKEN, "Content-Type": "application/json"}
    body = json.dumps({"cfg": {"path": doc, "root": "/tmp/shotdoc",
        "engine": "Kokoro (offline, best all-round)", "voice": "af_heart",
        "format": "WAV (uncompressed)"}}).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/api/render", data=body, headers=H)
    job = json.load(urllib.request.urlopen(req))
    for _ in range(300):
        snap = json.load(urllib.request.urlopen(urllib.request.Request(
            f"http://127.0.0.1:{PORT}/api/jobs/{job['id']}", headers=H)))
        if snap["status"] != "running": break
        time.sleep(0.1)
    print("render:", snap["status"])
    sys.argv.pop(2)
steps = sys.argv[2:] or ["narrate"]
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1100, "height": 900})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: m.type == "error" and errs.append(m.text))
    pg.goto(f"http://127.0.0.1:{PORT}/?token={webapi.TOKEN}")
    pg.wait_for_selector("h1")
    time.sleep(0.8)
    for step in steps:
        if step.startswith("tab:"):
            pg.get_by_role("tab", name=step[4:]).click(); time.sleep(0.8)
        elif step.startswith("click:"):
            pg.get_by_text(step[6:], exact=True).first.click(); time.sleep(0.6)
        elif step.startswith("role:"):
            role, name = step[5:].split("=", 1)
            pg.get_by_role(role, name=name).first.click(); time.sleep(0.6)
        elif step.startswith("shot:"):
            pg.screenshot(path=f"{OUT}/{step[5:]}.png", full_page=True)
        elif step.startswith("wait:"):
            time.sleep(float(step[5:]))
        elif step == "advanced":
            pg.get_by_text("Show every setting").click(); time.sleep(0.5)
    print("console/page errors:", errs if errs else "none")
    b.close()
srv.should_exit = True
