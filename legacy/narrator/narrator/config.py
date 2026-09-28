"""Paths, settings, voice catalogues, and engine detection.

Import-safe everywhere: no tkinter, no TTS libraries, nothing that
needs a display. The cross-environment worker imports this, so it has
to stay light.
"""

import argparse
import datetime
import hashlib
import importlib.util
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import wave


# Voice catalogues
# ---------------------------------------------------------------------------

EDGE_VOICES = [
    ("en-US-AndrewNeural", "Andrew - warm American male (best default)"),
    ("en-US-BrianNeural", "Brian - formal American male"),
    ("en-US-AvaNeural", "Ava - clear American female"),
    ("en-US-EmmaNeural", "Emma - soft American female"),
    ("en-GB-RyanNeural", "Ryan - neutral British male"),
    ("en-GB-SoniaNeural", "Sonia - British female, documentary"),
    ("en-AU-NatashaNeural", "Natasha - Australian female"),
    ("en-CA-LiamNeural", "Liam - Canadian male"),
]

KOKORO_VOICES = [
    ("af_heart", "Heart - warm American female (best default)"),
    ("af_bella", "Bella - rich American female"),
    ("af_nicole", "Nicole - softer American female"),
    ("am_michael", "Michael - warm American male"),
    ("am_fenrir", "Fenrir - bright American male"),
    ("bf_emma", "Emma - refined British female"),
    ("bm_george", "George - British male, documentary"),
]

# Qwen3's VoiceDesign mode builds a voice from a written description rather
# than a fixed name, so these are editable starting points, not a fixed list.
QWEN_VOICES = [
    ("A measured male academic in his fifties, neutral transatlantic accent, "
     "dry and precise, unhurried, no vocal fry.",
     "Academic male - measured and precise"),
    ("A warm female documentary narrator, mid-forties, neutral British accent, "
     "clear articulation, calm authority, unhurried pacing.",
     "Documentary female - calm authority"),
    ("A thoughtful male essayist, forties, gentle American accent, "
     "conversational but serious, natural pauses between ideas.",
     "Essayist male - thoughtful"),
    ("A crisp female lecturer, thirties, neutral accent, engaged and clear, "
     "slightly brisk without rushing.",
     "Lecturer female - crisp"),
]

SAMPLE_TEXT = ("The digital twin is not a copy of a thing. It is a claim about "
               "how much of a thing can be known, and at what cost.")


# ---------------------------------------------------------------------------
# Engine detection
#
# Kokoro and Qwen3 cannot share one environment: qwen-tts pins
# transformers==4.57.3 exactly while Kokoro wants it unpinned, so installing
# both together breaks one of them. Rather than forcing you to relaunch the
# app from a different environment for each engine, the app looks for sibling
# virtual environments next to itself and runs those engines inside their own
# interpreter as a subprocess. edge-tts has no heavy dependencies at all
# (no torch, no transformers) so it works in whichever environment you launch
# from, and can safely be installed in all of them.
# ---------------------------------------------------------------------------

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# One level up from this file: config.py lives in narrator/, so the project
# root is its parent. This deliberately keeps narrator_data/ and
# narrator_output/ beside the launcher where they have always been, rather
# than burying them inside the package folder -- the restructure should not
# move a person's files out from under them.
SETTINGS_FILE = os.path.join(APP_DIR, "narrator_settings.json")

# Folder names the setup guides tell you to create, checked in order.
VENV_CANDIDATES = {
    "kokoro": ["kokoro-env", "kokoro_env", "venv-kokoro"],
    "qwen3": ["qwen-env", "qwen_env", "qwen3-env", "venv-qwen"],
}


def _venv_python(folder):
    """Path to the interpreter inside a venv folder, or None."""
    for rel in (os.path.join("Scripts", "python.exe"),   # Windows
                os.path.join("bin", "python3"),          # macOS / Linux
                os.path.join("bin", "python")):
        candidate = os.path.join(folder, rel)
        if os.path.isfile(candidate):
            return candidate
    return None


def _module_in(python_exe, module):
    """Ask another interpreter whether it can import a module."""
    try:
        r = subprocess.run(
            [python_exe, "-c", f"import importlib.util,sys;"
                               f"sys.exit(0 if importlib.util."
                               f"find_spec('{module}') else 1)"],
            capture_output=True, timeout=60,
            creationflags=(subprocess.CREATE_NO_WINDOW
                           if os.name == "nt" else 0))
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


_EXTERNAL_CACHE = {}


def env_roots():
    """Folders searched for kokoro-env / qwen-env, most specific first.

    "env_root" in settings lets one copy of the app use environments that
    were built beside an older copy somewhere else, rather than downloading
    several GB again. The app's own folder is always searched too.
    """
    roots = []
    configured = (load_settings().get("env_root") or "").strip()
    if configured and os.path.isdir(configured):
        roots.append(configured)
    if APP_DIR not in roots:
        roots.append(APP_DIR)
    return roots


def venv_candidates(engine_key):
    """Every interpreter that might host this engine, in priority order:
    an explicitly configured python.exe first, then each known folder name
    under each environments root."""
    settings = load_settings()
    configured = (settings.get("engine_pythons") or {}).get(engine_key)
    found = [configured] if configured else []
    for root in env_roots():
        for name in VENV_CANDIDATES.get(engine_key, []):
            exe = _venv_python(os.path.join(root, name))
            if exe:
                found.append(exe)
    return found


def forget_engine_probes():
    """Drop cached detection results (after the environments folder or a
    python path changes in settings)."""
    _EXTERNAL_CACHE.clear()


def external_python(engine_key):
    """Interpreter for an engine that lives in its own venv, or None if the
    engine is importable right here. Result cached: probing spawns processes."""
    if engine_key in _EXTERNAL_CACHE:
        return _EXTERNAL_CACHE[engine_key]

    result = None
    module = {"kokoro": "kokoro", "qwen3": "qwen_tts"}.get(engine_key)
    if module and not _installed(module):
        for exe in venv_candidates(engine_key):
            if exe and os.path.isfile(exe) and _module_in(exe, module):
                result = exe
                break

    _EXTERNAL_CACHE[engine_key] = result
    return result


def _installed(*module_names):
    for name in module_names:
        if importlib.util.find_spec(name) is None:
            return False
    return True


def have_edge():
    return bool(shutil.which("edge-tts")) or _installed("edge_tts")


def have_kokoro():
    return _installed("kokoro", "soundfile") or \
        external_python("kokoro") is not None


def have_qwen():
    # qwen-tts on PyPI installs as the qwen_tts module. (qwen3-tts is a
    # different, Mac-only package built on Apple's mlx and is not usable here.)
    return (_installed("soundfile") and _installed("qwen_tts")) or \
        external_python("qwen3") is not None


def have_audio8():
    # transformers is common enough that its presence alone says nothing;
    # the thing actually worth checking is whether Audio8's OWN isolated
    # environment (pinned to the transformers<5 it needs) is set up --
    # same shape as have_qwen's external_python() check.
    return external_python("audio8") is not None


def have_ffmpeg():
    return shutil.which("ffmpeg") is not None




# ---------------------------------------------------------------------------
# Output naming
# ---------------------------------------------------------------------------


def slugify(value, limit=40):
    """Make a string safe for a filename on every OS."""
    value = re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-")
    value = re.sub(r"-{2,}", "-", value)
    return value[:limit].strip("-") or "voice"


def run_stamp():
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")


def default_output_root():
    """One central folder for everything this app produces.

    Sits beside the script so output never scatters across the directories your
    source documents happen to live in. Falls back to the home folder if the
    script is somewhere unwritable, such as Program Files.
    """
    candidate = os.path.join(APP_DIR, "narrator_output")
    try:
        os.makedirs(candidate, exist_ok=True)
        probe = os.path.join(candidate, ".writetest")
        with open(probe, "w") as fh:
            fh.write("")
        os.remove(probe)
        return candidate
    except OSError:
        fallback = os.path.join(os.path.expanduser("~"), "narrator_output")
        os.makedirs(fallback, exist_ok=True)
        return fallback


def _migrate_into_data_dir(old_path, new_path):
    """Move a settings/pronunciation file from beside the script (where older
    versions of this app kept it) into narrator_data/, without ever deleting
    the original -- a copy, not a move, so nothing is lost if anything about
    this goes wrong. Only runs once: if the new location already has a file,
    that file wins and migration is skipped entirely."""
    if os.path.exists(new_path) or not os.path.exists(old_path):
        return
    try:
        shutil.copy2(old_path, new_path)
    except OSError:
        pass


DATA_DIR = os.path.join(APP_DIR, "narrator_data")
os.makedirs(DATA_DIR, exist_ok=True)

SETTINGS_FILE = os.path.join(DATA_DIR, "narrator_settings.json")
_migrate_into_data_dir(os.path.join(APP_DIR, "narrator_settings.json"),
                       SETTINGS_FILE)

PRONOUNCE_FILE = os.path.join(DATA_DIR, "narrator_pronunciations.json")
_migrate_into_data_dir(os.path.join(APP_DIR, "narrator_pronunciations.json"),
                       PRONOUNCE_FILE)

CACHE_ROOT = os.path.join(DATA_DIR, "cache")

# Designed voices (Qwen3): one folder per description+take, holding the
# reference clip that every render of that voice is cloned from. Kept out
# of the cache on purpose -- the cache is disposable, a voice is not.
VOICES_DIR = os.path.join(DATA_DIR, "voices")

# Set by worker_main when running inside another environment, where the
# dictionary is passed in the job file rather than read from disk.
_WORKER_PRONUNCIATIONS = None


def load_settings():
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_settings(data):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
    except OSError:
        pass


def load_pronunciations():
    """word (lowercase) -> IPA phoneme string. Applies to Kokoro only; the
    other engines have no equivalent hook to intercept."""
    if _WORKER_PRONUNCIATIONS is not None:
        return _WORKER_PRONUNCIATIONS
    try:
        with open(PRONOUNCE_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_pronunciations(data):
    try:
        with open(PRONOUNCE_FILE, "w", encoding="utf-8") as fh:
            json.dump(dict(sorted(data.items())), fh, indent=2, ensure_ascii=False)
    except OSError:
        pass


# Podcast channel settings (title, author, hosting URL, ...) -- true across
# every episode, so this lives beside the app-wide settings, not per-render.
PODCAST_FILE = os.path.join(DATA_DIR, "narrator_podcast.json")
# The published-episode list is the source of truth for the feed; the XML
# in narrator_output/ is regenerated from this each time, never hand-edited
# or read back in, so a malformed feed is always fixable by rebuilding.
EPISODES_FILE = os.path.join(DATA_DIR, "narrator_episodes.json")


def load_podcast_settings():
    try:
        with open(PODCAST_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_podcast_settings(data):
    try:
        with open(PODCAST_FILE, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
    except OSError:
        pass


def load_episodes():
    try:
        with open(EPISODES_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return []


def save_episodes(episodes):
    try:
        with open(EPISODES_FILE, "w", encoding="utf-8") as fh:
            json.dump(episodes, fh, indent=2, ensure_ascii=False)
    except OSError:
        pass


# The project library: one record per document worked on, so returning to
# an earlier chapter doesn't mean reconstructing its settings from memory.
PROJECTS_FILE = os.path.join(DATA_DIR, "narrator_projects.json")


def load_projects():
    try:
        with open(PROJECTS_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return []


def save_projects(projects):
    try:
        with open(PROJECTS_FILE, "w", encoding="utf-8") as fh:
            json.dump(projects, fh, indent=2, ensure_ascii=False)
    except OSError:
        pass


def output_paths(root, source_path, engine_key, voice_id, is_sample,
                 use_subfolders=False):
    """Where a rendered file goes.

    Flat mode (use_subfolders=False, the default): every real output file
    lands directly in narrator_output/, all together.

        narrator_output/
            <document>__<engine>-<voice>__<timestamp>.mp3
            <other-document>__<engine>-<voice>__<timestamp>.mp3
            samples/
                sample__<engine>-<voice>__<timestamp>.mp3

    Subfolder mode (use_subfolders=True): one folder per document, still
    entirely inside narrator_output -- never at the source document's own
    location, regardless of this setting.

        narrator_output/
            <document>/
                <document>__<engine>-<voice>__<timestamp>.mp3
            samples/
                sample__<engine>-<voice>__<timestamp>.mp3

    Samples always live in narrator_output/samples/ in either mode -- there
    can be many of them from voice comparisons, and they aren't the kind of
    file organizing-by-document actually helps with.

    Returns (folder, filename_stem).
    """
    stem = os.path.splitext(os.path.basename(source_path))[0]
    safe_stem = slugify(stem, 60)

    if is_sample:
        folder = os.path.join(root, "samples")
    elif use_subfolders:
        folder = os.path.join(root, safe_stem)
    else:
        folder = root

    os.makedirs(folder, exist_ok=True)
    label = f"{engine_key}-{slugify(voice_id)}"
    prefix = "sample" if is_sample else safe_stem
    return folder, f"{prefix}__{label}__{run_stamp()}"


def document_folder(root, source_path, use_subfolders=False):
    if not use_subfolders:
        return root
    stem = os.path.splitext(os.path.basename(source_path))[0]
    return os.path.join(root, slugify(stem, 60))


def cache_dir(engine_key, voice_id, speed, text):
    """Per-settings cache, content-addressed and independent of wherever
    output ends up living. An interrupted run resumes because the same
    engine+voice+speed+text hashes to the same folder; a changed voice gets a
    fresh one automatically. Lives in narrator_data/cache, not inside
    narrator_output, so it's unaffected by the flat/subfolder output toggle
    and by output format changes -- it always holds the engine's native
    per-chunk audio, before any format conversion.
    """
    fingerprint = hashlib.sha1(
        f"{engine_key}|{voice_id}|{speed}|{text}".encode()).hexdigest()[:16]
    path = os.path.join(CACHE_ROOT, fingerprint)
    os.makedirs(path, exist_ok=True)
    return path


def unique_path(path):
    """Last-resort guard: never silently clobber an existing file."""
    if not os.path.exists(path):
        return path
    root, ext = os.path.splitext(path)
    n = 2
    while os.path.exists(f"{root}-{n}{ext}"):
        n += 1
    return f"{root}-{n}{ext}"


def _no_window():
    return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
