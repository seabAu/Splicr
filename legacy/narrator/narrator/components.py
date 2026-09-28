"""Optional components: what's installed, what each one unlocks, and how
to get it.

The point of this module is that Narrator should run, and be honestly
usable, with none of the optional pieces present -- and that every feature
which needs one should say so plainly instead of failing at the moment you
click it. That matters for a personal tool and matters much more for
anything handed to someone else.

It also carries the licence position. Everything permissive can be
bundled or installed automatically; `mutagen` is GPL-2.0, so it is
deliberately NOT bundled and is instead offered as a one-click optional
install, the way Audacity handles ffmpeg. Nothing here is legal advice --
the licence fields are recorded so the question stays visible, not
because this module resolves it.

The registry is UI-agnostic on purpose: it returns plain dicts, so the
current Tk dialog and any future interface both read the same source of
truth.
"""

import os
import shutil
import subprocess
import sys

from .config import _no_window

# kind:
#   "python"   -- a pip package installed into the app's own interpreter
#   "external" -- a normal program that has to be on PATH
#   "engine"   -- a TTS engine in its own virtual environment
#   "model"    -- model weights fetched on first use by an engine
COMPONENTS = {
    "ffmpeg": {
        "kind": "external", "label": "ffmpeg",
        "licence": "LGPL/GPL depending on build",
        "size": "~100 MB",
        "enables": ["Any audio output at all", "Video and audiograms",
                    "Converting and splitting audio"],
        "essential": True,
        "url": "https://ffmpeg.org/download.html",
        "hint": "Install it and make sure it's on PATH, then restart "
                "Narrator.",
    },
    "espeak-ng": {
        "kind": "external", "label": "espeak-ng",
        "licence": "GPL-3.0", "size": "~10 MB",
        "enables": ["Kokoro pronunciation of words outside its dictionary"],
        "url": "https://github.com/espeak-ng/espeak-ng/releases",
        "hint": "Needed by Kokoro. Install it separately, then restart.",
    },
    "pandoc": {
        "kind": "external", "label": "pandoc",
        "licence": "GPL-2.0-or-later", "size": "~150 MB",
        "enables": [".docx, .odt, .html, .epub and .tex input"],
        "url": "https://pandoc.org/installing.html",
        "hint": "Only needed for those formats -- .txt and .md work "
                "without it.",
    },
    "mutagen": {
        "kind": "python", "label": "mutagen", "package": "mutagen",
        "licence": "GPL-2.0", "size": "~1 MB",
        "enables": ["Chapter markers embedded in mp3 files"],
        "url": "https://github.com/quodlibet/mutagen",
        # The reason this is an optional install rather than a bundled
        # dependency. m4a chapters go through ffmpeg and need nothing here.
        "hint": "Not bundled: it's GPL-2.0, which carries obligations for "
                "redistributing it inside another program. Installing it "
                "yourself keeps that decision yours. m4a chapters work "
                "without it.",
    },
    "faster-whisper": {
        "kind": "python", "label": "faster-whisper",
        "package": "faster-whisper",
        "licence": "MIT", "size": "~5 MB (models are separate)",
        "enables": ["Transcribing existing audio back into text"],
        "url": "https://github.com/SYSTRAN/faster-whisper",
        "hint": "Speech models download separately the first time you "
                "transcribe.",
    },
    "pillow": {
        # The import name differs from the package name, which is
        # exactly the case a naive package-name-to-module guess gets
        # wrong -- so it's stated rather than derived.
        "kind": "python", "label": "Pillow", "package": "pillow",
        "module": "PIL",
        "licence": "MIT-CMU", "size": "~3 MB",
        "enables": ["Audiogram rendering and its preview"],
        "url": "https://python-pillow.org/",
        "hint": "",
    },
    "kokoro": {
        "kind": "engine", "label": "Kokoro", "engine_key": "kokoro",
        "licence": "Apache-2.0 (code and weights)", "size": "~2 GB",
        "enables": ["Kokoro narration", "Pronunciation editing"],
        "url": "https://github.com/hexgrad/kokoro",
        "hint": "Set up from Settings -> Preferences -> Engines.",
    },
    "qwen3": {
        "kind": "engine", "label": "Qwen3-TTS", "engine_key": "qwen3",
        # Weights confirmed Apache-2.0 by Routh, 2026-09-04.
        "licence": "Apache-2.0 (package and weights)",
        "size": "~8 GB",
        "enables": ["Designed voices", "Voice cloning", "CustomVoice"],
        "url": "https://github.com/QwenLM/Qwen3-TTS",
        "hint": "Set up from Settings -> Preferences -> Engines. Weights "
                "download on first use.",
    },
    "audio8": {
        "kind": "engine", "label": "Audio8-TTS", "engine_key": "audio8",
        # Confirmed via research 2026-09-12: the 0.6B checkpoint is
        # Apache-2.0. Its 0.1B sibling uses a separate revenue-capped
        # licence and is NOT what this integrates -- do not casually
        # "upgrade" the repo pin without re-checking that distinction.
        "licence": "Apache-2.0 (0.6B checkpoint only)",
        "size": "~3 GB",
        "enables": ["Voice cloning (lighter-weight, Preview quality)"],
        "url": "https://huggingface.co/Audio8/Audio8-TTS-Preview-0.6b",
        "hint": ("Set up from Settings -> Preferences -> Engines. "
                "Preview-quality and cloning-only -- not a narration "
                "default. See HANDOVER.md for the evaluation this was "
                "added from."),
    },
    "qwen-customvoice": {
        "kind": "model", "label": "Qwen3 CustomVoice model",
        "licence": "Apache-2.0", "size": "~5 GB",
        "enables": ["CustomVoice preset speakers"],
        "url": "https://huggingface.co/Qwen",
        "hint": "Fetched from the Voice studio's CustomVoice tab. Needs "
                "Qwen3-TTS set up first.",
        "requires": "qwen3",
    },
}


def _python_available(module):
    """Importable in the app's own interpreter? Checked in a subprocess so
    a heavy or half-broken package can't blow up or slow down the caller
    just by being probed."""
    try:
        r = subprocess.run(
            [sys.executable, "-c", f"import {module}"],
            capture_output=True, timeout=60, creationflags=_no_window())
        return r.returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


def component_status(key):
    """{installed, detail} for one component. Never raises: a component
    that can't be probed reports as not installed with the reason, which
    is more useful than an exception from a status check."""
    spec = COMPONENTS[key]
    try:
        if spec["kind"] == "external":
            binary = "ffmpeg" if key == "ffmpeg" else key
            path = shutil.which(binary)
            return {"installed": bool(path), "detail": path or "not on PATH"}

        if spec["kind"] == "python":
            module = spec.get("module") or spec["package"].replace("-", "_")
            ok = _python_available(module)
            return {"installed": ok,
                   "detail": "importable" if ok else "not installed"}

        if spec["kind"] == "engine":
            # engine_status returns a TUPLE (exists, python_path,
            # importable) -- not a dict. Verified against the function
            # rather than assumed.
            from .setup_engines import engine_status
            exists, python_path, importable = engine_status(
                spec["engine_key"])
            return {"installed": bool(importable),
                   "detail": python_path or
                            ("environment exists but the engine isn't "
                             "importable" if exists else "not set up")}

        if spec["kind"] == "model":
            from .engines import qwen_custom_speakers
            speakers = qwen_custom_speakers()
            return {"installed": bool(speakers),
                   "detail": (f"{len(speakers)} speaker(s) known"
                             if speakers else "not fetched yet")}
    except Exception as exc:
        return {"installed": False, "detail": f"couldn't check: {exc}"}
    return {"installed": False, "detail": "unknown"}


def report():
    """Status for every component, in registry order."""
    out = []
    for key, spec in COMPONENTS.items():
        st = component_status(key)
        entry = dict(spec)
        entry.update(st)
        entry["key"] = key
        out.append(entry)
    return out


def missing_for(*keys):
    """Which of these components aren't installed -- the check a feature
    makes before offering itself."""
    return [k for k in keys if not component_status(k)["installed"]]


def in_virtualenv():
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix)


def _pip_run(package, extra_args, log, progress):
    """One pip attempt. Returns (returncode, last_lines)."""
    cmd = [sys.executable, "-m", "pip", "install", "--progress-bar", "off",
          *extra_args, package]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, bufsize=1,
                            creationflags=_no_window())
    tail = []
    for line in proc.stdout:
        line = line.rstrip()
        if not line:
            continue
        tail.append(line)
        del tail[:-40]
        log("  " + line)
        if progress and "%" in line:
            for token in line.split():
                if token.endswith("%"):
                    try:
                        progress(min(1.0, float(token[:-1]) / 100))
                    except ValueError:
                        pass
                    break
    return proc.wait(), tail


def install_python_component(key, log, progress=None):
    """pip-install one optional Python package into whichever interpreter
    is running Narrator -- which is where the app's own imports look.

    Outside a virtualenv this uses `--user`. Modern Linux distributions
    mark the system Python as "externally managed" (PEP 668) and refuse a
    plain `pip install` outright; `--user` installs into the user's own
    site-packages, which that same interpreter imports, without touching
    anything the OS package manager owns. Inside a virtualenv `--user` is
    invalid, so a plain install is correct there. If a first attempt still
    fails on the externally-managed check, one retry adds `--user`.

    `progress`, if given, is called with 0..1 where pip reports a
    percentage, so a bar can move rather than just spin.
    """
    spec = COMPONENTS[key]
    if spec["kind"] != "python":
        raise ValueError(f"{key} isn't a pip-installable component.")
    package = spec["package"]
    log(f"Installing {package} ({spec['licence']})...")

    # Escalation ladder, each step only taken if the previous one was
    # refused for a reason the next one actually addresses.
    if in_virtualenv():
        # --user is invalid inside a virtualenv; a plain install is right.
        attempts = [[]]
    else:
        attempts = [
            ["--user"],
            # PEP 668: many Linux distributions mark the system Python
            # "externally managed" and refuse even --user. Verified here
            # that --user alone is NOT enough on Debian/Ubuntu. Combined
            # with --user this writes only to the user's own
            # site-packages -- despite its alarming name it does not
            # touch anything the OS package manager owns.
            ["--user", "--break-system-packages"],
        ]

    code, tail = -1, []
    for i, args in enumerate(attempts):
        if i:
            log("  the system Python is externally managed (PEP 668); "
               "retrying into your user packages only")
        code, tail = _pip_run(package, args, log, progress)
        if code == 0:
            break
        if "externally-managed" not in "\n".join(tail):
            break   # a different failure -- escalating wouldn't help

    if code != 0:
        detail = "\n  ".join(tail[-8:] or ["no output"])
        extra = ""
        if "externally-managed" in "\n".join(tail):
            extra = ("\n\nThis Python won't accept extra packages. The "
                    "cleanest fix is to run Narrator from a virtual "
                    "environment:\n"
                    "    python -m venv narrator-env\n"
                    "    narrator-env/bin/pip install " + package)
        raise RuntimeError(
            f"Installing {package} failed:\n  {detail}{extra}")
    if not component_status(key)["installed"]:
        raise RuntimeError(
            f"{package} installed but still isn't importable. If Narrator "
            "is running from a different Python than the one pip used, "
            "install it manually into the one running the app.")
    log(f"  {package} is ready.")
    return True
