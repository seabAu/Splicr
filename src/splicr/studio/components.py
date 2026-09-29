from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..config import Settings


_ENGINE_DEFINITIONS = {
    "kokoro": {
        "label": "Kokoro",
        "attribute": "kokoro_python",
        "environment": "SPLICR_KOKORO_PYTHON",
        "description": "Fast local narration plus dictionary-aware pronunciation tools.",
        "unlocks": ["Kokoro narration", "Pronunciation previews", "Kokoro voice blends"],
    },
    "qwen3": {
        "label": "Qwen3-TTS",
        "attribute": "qwen3_python",
        "environment": "SPLICR_QWEN3_PYTHON",
        "description": "Local voice design, cloning, and expressive preset voices.",
        "unlocks": ["Qwen3 narration", "Voice cloning", "Designed voices"],
    },
    "audio8": {
        "label": "Audio8",
        "attribute": "audio8_python",
        "environment": "SPLICR_AUDIO8_PYTHON",
        "description": "Local reference-voice rendering through an isolated environment.",
        "unlocks": ["Audio8 narration", "Audio8 cloned voices"],
    },
    "edge": {
        "label": "Edge TTS",
        "attribute": "edge_python",
        "environment": "SPLICR_EDGE_PYTHON",
        "description": "Zero-key online narration with cached multilingual voice discovery.",
        "unlocks": ["Edge TTS narration", "Multilingual neural voices", "Speech timing"],
        "install_url": "https://pypi.org/project/edge-tts/",
    },
}


class ComponentConfigurationError(ValueError):
    pass


class ComponentConfigurationLockedError(RuntimeError):
    pass


class ComponentManager:
    """Detect optional tools and persist paths to existing local engine environments.

    Environment variables remain authoritative. UI changes are written atomically to a small
    local JSON file and take effect on the next service restart; the running provider registry is
    deliberately never mutated underneath an active synthesis job.
    """

    def __init__(self, settings: Settings) -> None:
        self.path = settings.data_dir / "studio" / "components.json"
        self._lock = threading.RLock()

    def apply(self, settings: Settings) -> Settings:
        stored = self._load()
        updates: dict[str, Path | None] = {}
        for engine_id, definition in _ENGINE_DEFINITIONS.items():
            attribute = str(definition["attribute"])
            if self._environment_value(engine_id):
                continue
            configured = self._stored_path(stored, engine_id)
            if configured is not None and configured.is_file():
                updates[attribute] = configured
        return replace(settings, **updates) if updates else settings

    def status(self, active_settings: Settings) -> dict[str, Any]:
        stored = self._load()
        ffmpeg = self._tool_status("ffmpeg", "-version")
        ffprobe = self._tool_status("ffprobe", "-version")
        engines = [
            self._engine_status(engine_id, definition, stored, active_settings)
            for engine_id, definition in _ENGINE_DEFINITIONS.items()
        ]
        return {
            "restart_required": any(bool(item["restart_required"]) for item in engines),
            "system": [
                {
                    "id": "ffmpeg",
                    "label": "FFmpeg media toolkit",
                    "kind": "system",
                    "available": ffmpeg["available"] and ffprobe["available"],
                    "state": (
                        "ready" if ffmpeg["available"] and ffprobe["available"] else "missing"
                    ),
                    "description": "Local audio conversion, splitting, normalization, and video rendering.",
                    "path": ffmpeg["path"],
                    "version": ffmpeg["version"],
                    "detail": (
                        None
                        if ffmpeg["available"] and ffprobe["available"]
                        else "Both ffmpeg and ffprobe must be available on PATH."
                    ),
                    "unlocks": ["Convert workspace", "Audiogram rendering"],
                    "install_url": "https://ffmpeg.org/download.html",
                },
                {
                    "id": "python",
                    "label": "SPLICR Python runtime",
                    "kind": "system",
                    "available": True,
                    "state": "ready",
                    "description": "The isolated runtime hosting the SPLICR API and Studio.",
                    "path": sys.executable,
                    "version": sys.version.split()[0],
                    "detail": None,
                    "unlocks": ["SPLICR service", "Document import", "Remote TTS providers"],
                    "install_url": None,
                },
            ],
            "engines": engines,
            "planned": [
                {
                    "id": "transcription",
                    "label": "Local transcription",
                    "kind": "planned",
                    "available": False,
                    "state": "planned",
                    "description": "Narrator's faster-whisper workflow is preserved but not wired into Studio yet.",
                    "unlocks": ["Audio-to-text", "Subtitle drafts", "Pause-based chapter drafts"],
                },
                {
                    "id": "chapter-tags",
                    "label": "Embedded chapter tags",
                    "kind": "planned",
                    "available": False,
                    "state": "planned",
                    "description": "Mutagen-backed MP3 chapters will arrive with the Publish workspace.",
                    "unlocks": ["MP3 chapter markers"],
                },
            ],
        }

    def save_engine(self, engine_id: str, python_path: str) -> None:
        self._definition(engine_id)
        if self._environment_value(engine_id):
            raise ComponentConfigurationLockedError(
                f"{_ENGINE_DEFINITIONS[engine_id]['environment']} controls this engine"
            )
        resolved = Path(python_path).expanduser().resolve()
        self._validate_interpreter(resolved)
        with self._lock:
            data = self._load()
            engines = data.setdefault("engines", {})
            assert isinstance(engines, dict)
            engines[engine_id] = {"python": str(resolved)}
            self._save(data)

    def clear_engine(self, engine_id: str) -> bool:
        self._definition(engine_id)
        if self._environment_value(engine_id):
            raise ComponentConfigurationLockedError(
                f"{_ENGINE_DEFINITIONS[engine_id]['environment']} controls this engine"
            )
        with self._lock:
            data = self._load()
            engines = data.setdefault("engines", {})
            assert isinstance(engines, dict)
            removed = engines.pop(engine_id, None) is not None
            self._save(data)
        return removed

    def refresh_edge_voices(self, active_settings: Settings) -> dict[str, Any]:
        executable = active_settings.edge_python
        if executable is None or not executable.is_file():
            raise ComponentConfigurationError(
                "Activate an Edge TTS Python environment before refreshing voices"
            )
        worker = Path(__file__).resolve().parents[1] / "engine_worker.py"
        try:
            result = subprocess.run(
                [str(executable), str(worker), "--tool", "edge_voices"],
                input="{}",
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise ComponentConfigurationError(
                f"Could not discover Edge TTS voices: {error}"
            ) from error
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            detail = (result.stderr or result.stdout).strip()[-500:]
            raise ComponentConfigurationError(
                f"Edge TTS voice discovery returned invalid output: {detail}"
            ) from error
        if not isinstance(payload, dict) or "error_type" in payload:
            message = payload.get("message") if isinstance(payload, dict) else None
            raise ComponentConfigurationError(
                str(message or "Edge TTS voice discovery failed")
            )
        voices = payload.get("voices")
        if result.returncode != 0 or not isinstance(voices, list) or not voices:
            raise ComponentConfigurationError("Edge TTS returned no available voices")
        refreshed_at = datetime.now(timezone.utc).isoformat()
        catalog = {"version": 1, "refreshed_at": refreshed_at, "voices": voices}
        path = self.path.parent / "edge-voices.json"
        self._save_json(path, catalog)
        return {
            "count": len(voices),
            "refreshed_at": refreshed_at,
            "path": str(path),
        }

    def _engine_status(
        self,
        engine_id: str,
        definition: dict[str, object],
        stored: dict[str, Any],
        active_settings: Settings,
    ) -> dict[str, Any]:
        environment_path = self._environment_value(engine_id)
        configured_path = self._stored_path(stored, engine_id)
        active_path = getattr(active_settings, str(definition["attribute"]))
        desired_path = Path(environment_path).expanduser().resolve() if environment_path else configured_path
        candidate = desired_path or active_path
        available = bool(candidate and candidate.is_file())
        version = self._interpreter_version(candidate) if available else None
        locked = bool(environment_path)
        restart_required = (
            not locked
            and (str(configured_path) if configured_path else None)
            != (str(active_path) if active_path else None)
        )
        if locked:
            source = "environment"
        elif configured_path:
            source = "studio"
        elif active_path:
            source = "startup"
        else:
            source = "unconfigured"
        state = "restart_required" if restart_required else "configured" if available else "missing"
        return {
            "id": engine_id,
            "label": definition["label"],
            "kind": "engine",
            "available": available,
            "state": state,
            "description": definition["description"],
            "path": str(candidate) if candidate else None,
            "active_path": str(active_path) if active_path else None,
            "version": version,
            "detail": (
                "Restart SPLICR to activate this interpreter."
                if restart_required
                else "Interpreter is active; engine packages are verified when a job starts."
                if available
                else "Choose the Python executable inside an existing engine environment."
            ),
            "unlocks": definition["unlocks"],
            "locked": locked,
            "source": source,
            "environment_variable": definition["environment"],
            "install_url": definition.get("install_url"),
            "restart_required": restart_required,
            "voice_catalog": self._edge_catalog_status() if engine_id == "edge" else None,
        }

    def _edge_catalog_status(self) -> dict[str, Any]:
        path = self.path.parent / "edge-voices.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            voices = payload.get("voices") if isinstance(payload, dict) else None
        except (OSError, json.JSONDecodeError):
            payload, voices = {}, None
        return {
            "count": len(voices) if isinstance(voices, list) else 0,
            "refreshed_at": payload.get("refreshed_at") if isinstance(payload, dict) else None,
            "path": str(path),
        }

    @staticmethod
    def _tool_status(command: str, version_argument: str) -> dict[str, object]:
        path = shutil.which(command)
        if path is None:
            return {"available": False, "path": None, "version": None}
        try:
            result = subprocess.run(
                [path, version_argument],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            first_line = (result.stdout or result.stderr).splitlines()[0].strip()
        except (OSError, subprocess.SubprocessError, IndexError):
            first_line = None
        return {"available": True, "path": path, "version": first_line}

    @staticmethod
    def _validate_interpreter(path: Path) -> None:
        if not path.is_file():
            raise ComponentConfigurationError("Python executable does not exist")
        try:
            result = subprocess.run(
                [str(path), "--version"],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise ComponentConfigurationError(f"Could not start that Python executable: {error}") from error
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()[-300:]
            raise ComponentConfigurationError(f"That Python executable could not run: {detail}")

    @staticmethod
    def _interpreter_version(path: Path | None) -> str | None:
        if path is None:
            return None
        try:
            result = subprocess.run(
                [str(path), "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if result.returncode != 0:
            return None
        return (result.stdout or result.stderr).strip().splitlines()[0]

    @staticmethod
    def _environment_value(engine_id: str) -> str:
        definition = _ENGINE_DEFINITIONS[engine_id]
        return os.getenv(str(definition["environment"]), "").strip()

    @staticmethod
    def _definition(engine_id: str) -> dict[str, object]:
        try:
            return _ENGINE_DEFINITIONS[engine_id]
        except KeyError as error:
            raise ComponentConfigurationError("unknown local engine") from error

    @staticmethod
    def _stored_path(data: dict[str, Any], engine_id: str) -> Path | None:
        engines = data.get("engines")
        if not isinstance(engines, dict):
            return None
        item = engines.get(engine_id)
        if not isinstance(item, dict) or not isinstance(item.get("python"), str):
            return None
        value = item["python"].strip()
        return Path(value).expanduser().resolve() if value else None

    def _load(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {"version": 1, "engines": {}}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"version": 1, "engines": {}}
        if not isinstance(value, dict):
            return {"version": 1, "engines": {}}
        value.setdefault("version", 1)
        value.setdefault("engines", {})
        return value

    def _save(self, data: dict[str, Any]) -> None:
        self._save_json(self.path, data)

    @staticmethod
    def _save_json(path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(
                json.dumps(data, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
