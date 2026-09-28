"""Create the engine environments automatically.

Kokoro and Qwen3-TTS cannot share a virtualenv -- qwen-tts pins transformers
to one exact version while Kokoro needs it unpinned -- so each gets its own
folder beside this script. This module builds them, so you don't have to run
the setup commands by hand.

What this CAN do:
    - create each environment on the correct Python version
    - install the engine packages into it
    - install PyTorch from the right index for your GPU
    - verify afterwards that the engine actually imports

What this CANNOT do:
    - bundle the engines themselves (they are downloaded from PyPI)
    - bundle the model weights (Kokoro ~300 MB, Qwen3 several GB, fetched
      from Hugging Face on first use by the engine itself)
    - install pandoc, ffmpeg or espeak-ng, which are ordinary programs
      rather than Python packages -- it reports whether they're present and
      tells you where to get them

Run it directly:
    python -m narrator.setup_engines            interactive menu
    python -m narrator.setup_engines kokoro     just that one
    python -m narrator.setup_engines --check    report status, change nothing
"""

import os
import re
import shutil
import subprocess
import sys

import importlib.util

from .config import (APP_DIR, VENV_CANDIDATES, _venv_python, env_roots,
                     load_settings)
from .documents import _have

# Kokoro refuses anything newer than 3.12, and several of its dependencies
# have no prebuilt wheels above it either -- on 3.13+ pip silently falls back
# to an ancient release and dies compiling a C extension. Pinning here means
# the person never has to discover that themselves.
ENGINE_PYTHON = "3.12"

TORCH_INDEX_CUDA = "https://download.pytorch.org/whl/cu128"

ENGINE_SPECS = {
    "kokoro": {
        "folder": "kokoro-env",
        "label": "Kokoro (offline, best all-round)",
        # torch first and WITHOUT torchaudio: Kokoro doesn't need torchaudio,
        # and installing it after torch is already present is what produces
        # the "Could not load libtorchaudio" failure.
        "steps": [
            (["torch"], TORCH_INDEX_CUDA),
            (["kokoro", "soundfile", "edge-tts"], None),
        ],
        "verify": "kokoro",
        "notes": "Also needs espeak-ng installed separately (see below).",
    },
    "qwen3": {
        "folder": "qwen-env",
        "label": "Qwen3-TTS (offline, designed voices)",
        # qwen-tts genuinely does require torchaudio, and both must come from
        # the same index in one command or their versions mismatch.
        "steps": [
            (["torch", "torchaudio"], TORCH_INDEX_CUDA),
            (["qwen-tts"], None),
        ],
        "verify": "qwen_tts",
        "notes": "Needs an NVIDIA GPU with roughly 6 GB of VRAM or more.",
    },
    "audio8": {
        "folder": "audio8-env",
        "label": "Audio8-TTS (offline, voice cloning, Preview)",
        # Confirmed during evaluation: transformers 5.x produces silent
        # all-zero output on this model, and it needs its own remote
        # code trusted at load time (handled in audio8_engine.py, not
        # here) -- so the version ceiling is pinned rather than left to
        # float with whatever else might be installed later.
        "steps": [
            (["torch"], TORCH_INDEX_CUDA),
            (["transformers>=4.57.0,<5", "soundfile", "accelerate"], None),
        ],
        "verify": "transformers",
        "notes": ("Preview-quality: independent testers report occasional "
                 "unstable/runaway output, worked around here with "
                 "automatic retries. A voice-cloning option, not a "
                 "narration default -- Kokoro remains that. Roughly 1-2 "
                 "GB VRAM; a GPU is not required but is much faster."),
    },
    # edge-tts is tiny and has no conflicting dependencies, so it goes into
    # whichever Python is running the app rather than a venv of its own.
    # Listed here so a fresh machine with nothing installed can still get a
    # working engine from the wizard instead of a dead end.
    "edge": {
        "folder": None,
        "label": "edge-tts (online, fastest setup)",
        "steps": [
            (["edge-tts"], None),
        ],
        "verify": "edge_tts",
        "notes": "About 10 MB. Needs internet while narrating.",
    },
}

EXTERNAL_TOOLS = {
    "ffmpeg": "Joins audio, converts formats, builds video. "
              "Windows: winget install ffmpeg",
    "pandoc": "Reads .docx/.odt/.html/.tex/.epub. "
              "Windows: winget install pandoc  (or pandoc.org)",
    "espeak-ng": "Kokoro uses it to pronounce unfamiliar words. "
                 "Search GitHub for espeak-ng releases and run the .msi",
}


_DOWNLOAD_START = re.compile(
    r"^\s*Downloading\s+(\S+?)(?:\.whl\.metadata|\.tar\.gz\.metadata)?"
    r"\s+\(([\d.]+)\s*(kB|MB|GB)\)")
_DOWNLOAD_DONE = re.compile(r"^\s*[━╺]+\s+[\d.]+/[\d.]+\s*(kB|MB|GB)")


_UNIT_BYTES = {"kB": 1_000, "MB": 1_000_000, "GB": 1_000_000_000}
_MIN_NOTABLE_BYTES = 300_000  # below this, it's a metadata pre-fetch, not a
                             # download worth interrupting the person for


def _run(cmd, log, progress=None, **kw):
    """Run a command, streaming its output as it arrives rather than
    waiting for it to finish.

    Verified against real pip output before relying on this: piped (non-
    interactive) pip does not animate its progress bar with carriage
    returns, so line-by-line reading is safe. It DOES announce each real
    download with a "Downloading <file> (<size>)" line the moment that
    download starts, before the file is fetched -- that line is what lets
    `progress()` report something real (a name and a size) rather than
    silence for the several minutes a big PyTorch wheel can take on an
    ordinary connection. What it does NOT reliably give, even piped, is a
    smooth byte-by-byte tick during that wait -- so the caller should treat
    the gap between the start line and the completion line as indeterminate,
    not animate a fake percentage across it.

    Pip also announces tiny .whl.metadata fetches (a few KB, one per
    dependency being resolved) with the same "Downloading" phrasing; those
    are filtered by actual byte size, not by name, since the metadata
    filename doesn't reliably say so.
    """
    log("    $ " + " ".join(str(c) for c in cmd))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True,
                            bufsize=1, **kw)
    tail = []
    for line in proc.stdout:
        line = line.rstrip()
        if not line:
            continue
        tail.append(line)
        del tail[:-12]

        if progress:
            m = _DOWNLOAD_START.match(line)
            if m:
                size_bytes = float(m.group(2)) * _UNIT_BYTES[m.group(3)]
                if size_bytes >= _MIN_NOTABLE_BYTES:
                    progress({"kind": "downloading", "name": m.group(1),
                              "size": f"{m.group(2)} {m.group(3)}"})
            elif _DOWNLOAD_DONE.match(line):
                progress({"kind": "downloaded"})

    proc.wait()
    if proc.returncode != 0:
        for line in tail:
            log("      " + line)
    return proc.returncode == 0


def env_path(engine_key):
    """Where this engine's environment is (or would be) built: inside the
    configured environments folder if there is one, else next to the
    project."""
    return os.path.join(env_roots()[0], ENGINE_SPECS[engine_key]["folder"])


def _can_import(exe, module):
    try:
        return subprocess.run(
            [exe, "-c", f"import importlib.util,sys; sys.exit("
                        f"0 if importlib.util.find_spec"
                        f"('{module}') else 1)"],
            capture_output=True, timeout=60).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def engine_status(engine_key):
    """(exists, python_path, importable) for one engine environment.

    For edge-tts, which has no environment of its own, "exists" and
    "importable" are the same question: is it importable right here?
    """
    spec = ENGINE_SPECS[engine_key]
    if importlib.util.find_spec(spec["verify"]) is not None:
        # Importable in the interpreter running the app (e.g. launched from
        # inside kokoro-env by the .bat): ready, whatever the folders say.
        return True, sys.executable, True
    if spec["folder"] is None:
        return False, None, False

    # An explicitly configured interpreter wins over folder discovery.
    configured = (load_settings().get("engine_pythons") or {}).get(engine_key)
    if configured and os.path.isfile(configured):
        return True, configured, _can_import(configured, spec["verify"])

    for root in env_roots():
        for name in VENV_CANDIDATES.get(engine_key, [spec["folder"]]):
            folder = os.path.join(root, name)
            if not os.path.isdir(folder):
                continue
            exe = _venv_python(folder)
            if not exe:
                return True, None, False
            return True, exe, _can_import(exe, spec["verify"])
    return False, None, False


def create_environment(engine_key, log=print, progress=None, use_gpu=True):
    """Build one engine environment from scratch. Returns True on success.

    progress, if given, is called with small dicts describing what stage
    things are at:
        {"kind": "stage", "label": "Creating environment", "step": 1, "total": 4}
        {"kind": "downloading", "name": "torch-...whl", "size": "750.0 MB"}
        {"kind": "downloaded"}
        {"kind": "done"}
    This is deliberately coarse rather than a fake smooth percentage: pip's
    own progress reporting doesn't reliably give byte-level ticks once piped
    (see _run's docstring), so "step 2 of 4, downloading a 750 MB file, no
    further detail until it's done" is the honest granularity available.
    """
    def stage(label, step, total):
        log(f"{label}...")
        if progress:
            progress({"kind": "stage", "label": label,
                      "step": step, "total": total})

    spec = ENGINE_SPECS[engine_key]

    if spec["folder"] is None:
        # No environment to build: install into the interpreter running the
        # app. pip falls back to a per-user install by itself when the
        # system site-packages isn't writable, so this needs no admin.
        total_steps = 1 + len(spec["steps"])
        for i, (packages, _index) in enumerate(spec["steps"], 1):
            stage(f"Installing {', '.join(packages)}", i, total_steps)
            if not _run([sys.executable, "-m", "pip", "install",
                         "--upgrade"] + list(packages), log, progress):
                log(f"  ! Failed installing {', '.join(packages)}.")
                return False
        stage(f"Verifying {spec['label']}", total_steps, total_steps)
        ok = subprocess.run([sys.executable, "-c",
                             f"import {spec['verify']}"],
                            capture_output=True)
        if ok.returncode != 0:
            log(f"  ! Installed, but importing {spec['verify']} failed.")
            return False
        log(f"  {spec['label']} is ready.")
        if progress:
            progress({"kind": "done"})
        return True

    target = env_path(engine_key)
    total_steps = 2 + len(spec["steps"])  # venv + each install group + verify

    if os.path.isdir(target):
        log(f"{spec['folder']} already exists. Delete it first to rebuild.")
        return False

    stage(f"Creating {spec['folder']} on Python {ENGINE_PYTHON}", 1, total_steps)

    if shutil.which("uv"):
        made = _run(["uv", "venv", "--python", ENGINE_PYTHON, "--seed",
                     target], log, progress)
    else:
        # Without uv we can only use the interpreter running right now, so
        # its version has to be suitable -- say so plainly rather than
        # failing later inside pip with a confusing compile error.
        if sys.version_info[:2] > (3, 12):
            log(f"  ! This is Python {sys.version_info.major}."
                f"{sys.version_info.minor}, but the engines need 3.12 or "
                f"older.")
            log("    Install uv (pip install uv) and run this again -- it "
                "fetches the right Python for you.")
            return False
        made = _run([sys.executable, "-m", "venv", target], log, progress)

    if not made:
        log("  ! Could not create the environment.")
        return False

    exe = _venv_python(target)
    if not exe:
        log("  ! Environment created but no interpreter found inside it.")
        return False

    for i, (packages, index) in enumerate(spec["steps"], 2):
        stage(f"Installing {', '.join(packages)}", i, total_steps)
        cmd = [exe, "-m", "pip", "install", "--upgrade"] + list(packages)
        if index and use_gpu:
            cmd += ["--index-url", index]
        if not _run(cmd, log, progress):
            log(f"  ! Failed installing {', '.join(packages)}.")
            return False

    stage(f"Verifying {spec['label']}", total_steps, total_steps)
    ok = subprocess.run(
        [exe, "-c", f"import {spec['verify']}"], capture_output=True)
    if ok.returncode != 0:
        log(f"  ! Installed, but importing {spec['verify']} failed.")
        return False

    log(f"  {spec['label']} is ready.")
    if spec.get("notes"):
        log(f"  Note: {spec['notes']}")
    if progress:
        progress({"kind": "done"})
    return True


def check_all(log=print):
    """Report what's set up without changing anything."""
    log("Engine environments:")
    for key, spec in ENGINE_SPECS.items():
        exists, exe, importable = engine_status(key)
        if importable:
            state = "ready"
        elif exists:
            state = "folder exists, but the engine doesn't import"
        else:
            state = "not set up"
        log(f"  {spec['label']:38} {state}")

    log("")
    log("Supporting programs (installed normally, not via pip):")
    for tool, why in EXTERNAL_TOOLS.items():
        log(f"  {tool:10} {'found' if _have(tool) else 'MISSING'}")
        if not _have(tool):
            log(f"             {why}")

    log("")
    roots = env_roots()
    log(f"Environments are looked for in: {roots[0]}"
        + (f"  (and {roots[1]})" if len(roots) > 1 else ""))


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)

    if "--check" in argv:
        check_all()
        return

    wanted = [a for a in argv if a in ENGINE_SPECS]
    if not wanted:
        check_all()
        print("")
        print("To set one up:")
        for key in ENGINE_SPECS:
            print(f"    python -m narrator.setup_engines {key}")
        return

    for key in wanted:
        create_environment(key)
        print("")


if __name__ == "__main__":
    main()
