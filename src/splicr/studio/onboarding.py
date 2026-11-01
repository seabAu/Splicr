from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any
from uuid import uuid4


class SetupGuidePreferences:
    """Persist only the setup preference, never installation consent or engine settings."""

    MODES = frozenset({"local", "remote", "later"})

    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "studio" / "setup-guide.json"
        self._lock = threading.RLock()

    def read(self) -> dict[str, Any]:
        with self._lock:
            try:
                if not self.path.exists():
                    return {"schema_version": 1, "mode": None, "preference_warning": None}
                with self.path.open("rb") as stream:
                    payload = stream.read(4097)
                if len(payload) > 4096:
                    raise ValueError("oversized setup preference")
                value = json.loads(payload.decode("utf-8"))
                if (
                    not isinstance(value, dict)
                    or type(value.get("schema_version")) is not int
                    or value["schema_version"] != 1
                    or not isinstance(value.get("mode"), str)
                    or value["mode"] not in self.MODES
                ):
                    raise ValueError("invalid setup preference")
                return {"schema_version": 1, "mode": value["mode"], "preference_warning": None}
            except (OSError, ValueError, TypeError, RecursionError):
                return {
                    "schema_version": 1,
                    "mode": None,
                    "preference_warning": "The saved setup choice could not be read. Choose again to save it.",
                }

    def choose(self, mode: str) -> dict[str, Any]:
        if not isinstance(mode, str) or mode not in self.MODES:
            raise ValueError("unknown setup preference")
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
            try:
                temporary.write_text(
                    json.dumps({"schema_version": 1, "mode": mode}), encoding="utf-8"
                )
                os.replace(temporary, self.path)
            finally:
                temporary.unlink(missing_ok=True)
            return self.read()

    def status(
        self,
        *,
        engines: list[dict[str, Any]],
        has_existing_work: bool,
        managed_setup_supported: bool,
    ) -> dict[str, Any]:
        preference = self.read()
        has_environment = any(item.get("path") or item.get("active_path") for item in engines)
        return {
            **preference,
            "enabled": True,
            "prompt_required": preference["mode"] is None
            and not has_existing_work
            and not has_environment,
            "managed_setup_supported": managed_setup_supported,
            "engines": engines,
            "restart_required": any(item.get("restart_required") for item in engines),
        }
