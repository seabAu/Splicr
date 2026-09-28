from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


_RESPELLING_SUFFIX = "__respelling"
PRONUNCIATION_VARIABLE = "__splicr_pronunciations"
PRONUNCIATION_REVISION_VARIABLE = "__splicr_pronunciation_revision"


@dataclass(frozen=True, slots=True)
class PronunciationEntry:
    word: str
    ipa: str
    respelling: str | None = None


def _clean_word(value: str) -> str:
    word = value.strip().lower()
    if not word:
        raise ValueError("word must not be blank")
    if any(character.isspace() for character in word):
        raise ValueError("pronunciation overrides must contain exactly one word")
    return word


def _clean_mapping(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {
        str(key).strip(): str(item).strip()
        for key, item in value.items()
        if str(key).strip() and str(item).strip()
    }


def apply_substitutions(text: str, substitutions: Mapping[str, str]) -> tuple[str, dict[str, int]]:
    """Apply literal whole-word substitutions, longest match first."""

    rewritten = text
    applied: dict[str, int] = {}
    for source in sorted(substitutions, key=len, reverse=True):
        replacement = substitutions[source]
        pattern = re.compile(rf"(?<!\w){re.escape(source)}(?!\w)", re.IGNORECASE)
        rewritten, count = pattern.subn(lambda _match: replacement, rewritten)
        if count:
            applied[source] = count
    return rewritten, applied


class TextCustomizationStore:
    """Small, atomic JSON store shared by the UI and isolated local engines."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.pronunciations_path = directory / "pronunciations.json"
        self.substitutions_path = directory / "substitutions.json"
        self._lock = threading.RLock()

    def pronunciation_entries(self) -> tuple[PronunciationEntry, ...]:
        data = self.pronunciation_snapshot()
        entries = []
        for word, ipa in data.items():
            if word.endswith(_RESPELLING_SUFFIX):
                continue
            entries.append(
                PronunciationEntry(
                    word=word,
                    ipa=ipa,
                    respelling=data.get(f"{word}{_RESPELLING_SUFFIX}"),
                )
            )
        return tuple(sorted(entries, key=lambda entry: entry.word))

    def pronunciation_snapshot(self) -> dict[str, str]:
        with self._lock:
            return self._read_mapping(self.pronunciations_path)

    def pronunciation_revision(self, snapshot: Mapping[str, str] | None = None) -> str:
        values = dict(snapshot) if snapshot is not None else self.pronunciation_snapshot()
        encoded = json.dumps(
            values,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def save_pronunciation(self, *, word: str, ipa: str, respelling: str) -> PronunciationEntry:
        key = _clean_word(word)
        normalized_ipa = ipa.strip()
        normalized_respelling = respelling.strip()
        if not normalized_ipa:
            raise ValueError("IPA must not be blank")
        if not normalized_respelling:
            raise ValueError("respelling must not be blank")
        with self._lock:
            values = self._read_mapping(self.pronunciations_path)
            values[key] = normalized_ipa
            values[f"{key}{_RESPELLING_SUFFIX}"] = normalized_respelling
            self._write_mapping(self.pronunciations_path, values)
        return PronunciationEntry(key, normalized_ipa, normalized_respelling)

    def delete_pronunciation(self, word: str) -> bool:
        key = _clean_word(word)
        with self._lock:
            values = self._read_mapping(self.pronunciations_path)
            removed = values.pop(key, None) is not None
            values.pop(f"{key}{_RESPELLING_SUFFIX}", None)
            if removed:
                self._write_mapping(self.pronunciations_path, values)
            return removed

    def import_pronunciations(
        self,
        values: object,
        *,
        overwrite: bool = False,
    ) -> int:
        imported = _clean_mapping(values)
        with self._lock:
            current = self._read_mapping(self.pronunciations_path)
            added = 0
            for source_word, ipa in imported.items():
                if source_word.endswith(_RESPELLING_SUFFIX):
                    continue
                try:
                    word = _clean_word(source_word)
                except ValueError:
                    continue
                if word in current and not overwrite:
                    continue
                current[word] = ipa
                respelling = imported.get(f"{source_word}{_RESPELLING_SUFFIX}")
                if respelling:
                    current[f"{word}{_RESPELLING_SUFFIX}"] = respelling
                added += 1
            if added:
                self._write_mapping(self.pronunciations_path, current)
            return added

    def substitutions(self) -> dict[str, str]:
        with self._lock:
            return self._read_mapping(self.substitutions_path)

    def save_substitution(self, *, source: str, replacement: str) -> dict[str, str]:
        normalized_source = source.strip()
        normalized_replacement = replacement.strip()
        if not normalized_source or not normalized_replacement:
            raise ValueError("substitution source and replacement must not be blank")
        with self._lock:
            values = self._read_mapping(self.substitutions_path)
            values[normalized_source] = normalized_replacement
            self._write_mapping(self.substitutions_path, values)
            return dict(values)

    def delete_substitution(self, source: str) -> bool:
        normalized_source = source.strip()
        if not normalized_source:
            raise ValueError("substitution source must not be blank")
        with self._lock:
            values = self._read_mapping(self.substitutions_path)
            removed = values.pop(normalized_source, None) is not None
            if removed:
                self._write_mapping(self.substitutions_path, values)
            return removed

    def import_substitutions(
        self,
        values: object,
        *,
        overwrite: bool = False,
    ) -> int:
        imported = _clean_mapping(values)
        with self._lock:
            current = self._read_mapping(self.substitutions_path)
            added = 0
            for source, replacement in imported.items():
                if source in current and not overwrite:
                    continue
                current[source] = replacement
                added += 1
            if added:
                self._write_mapping(self.substitutions_path, current)
            return added

    @staticmethod
    def real_pronunciations(values: Mapping[str, str]) -> dict[str, str]:
        return {
            key: value
            for key, value in values.items()
            if not key.endswith(_RESPELLING_SUFFIX)
        }

    @staticmethod
    def _read_mapping(path: Path) -> dict[str, str]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return {}
        return _clean_mapping(value)

    def _write_mapping(self, path: Path, values: Mapping[str, str]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        payload = json.dumps(
            dict(sorted(values.items())),
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
        ) + "\n"
        try:
            temporary.write_text(payload, encoding="utf-8")
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


class KokoroToolError(RuntimeError):
    pass


class KokoroToolClient:
    """Run lightweight Misaki tools inside Kokoro's isolated Python environment."""

    def __init__(
        self,
        python_executable: Path,
        *,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.python_executable = python_executable.expanduser().resolve()
        self.timeout_seconds = timeout_seconds

    def execute(self, operation: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        if not self.python_executable.is_file():
            raise KokoroToolError(
                f"Kokoro Python executable does not exist: {self.python_executable}"
            )
        worker_path = Path(__file__).resolve().parent / "engine_worker.py"
        try:
            result = subprocess.run(
                (
                    str(self.python_executable),
                    str(worker_path),
                    "--tool",
                    operation,
                ),
                input=json.dumps(dict(payload), ensure_ascii=False, allow_nan=False),
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=self.timeout_seconds,
                check=False,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise KokoroToolError(f"Kokoro pronunciation tool failed: {error}") from error
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "no error detail"
            raise KokoroToolError(f"Kokoro pronunciation tool failed: {detail}")
        try:
            value = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise KokoroToolError("Kokoro pronunciation tool returned invalid JSON") from error
        if not isinstance(value, dict):
            raise KokoroToolError("Kokoro pronunciation tool returned a non-object result")
        if value.get("error_type"):
            raise KokoroToolError(str(value.get("message") or value["error_type"]))
        return value
