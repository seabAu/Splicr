"""Standalone JSON-lines worker for isolated local synthesis environments.

This module intentionally imports only the standard library at module load. Engine-specific
dependencies are imported after argument parsing so the file can be executed by an isolated
environment without installing the rest of SPLICR into that environment.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Mapping, Protocol


PROTOCOL_VERSION = 1
PACE_SPEEDS = {
    "very_slow": 0.70,
    "slow": 0.85,
    "normal": 1.0,
    "fast": 1.15,
    "very_fast": 1.30,
}
PRONUNCIATION_VARIABLE = "__splicr_pronunciations"


class EngineRuntime(Protocol):
    def synthesize(
        self,
        text: str,
        options: Mapping[str, Any],
        output_path: Path,
    ) -> None: ...


def _apply_pronunciation_overrides(pipeline: Any, options: Mapping[str, Any]) -> int:
    variables = options.get("variables")
    pronunciations = (
        variables.get(PRONUNCIATION_VARIABLE)
        if isinstance(variables, Mapping)
        else None
    )
    if not isinstance(pronunciations, Mapping):
        return 0
    golds = pipeline.g2p.lexicon.golds
    applied = 0
    for word, phonemes in pronunciations.items():
        if isinstance(word, str) and isinstance(phonemes, str):
            word = word.strip().lower()
            phonemes = phonemes.strip()
            if word and phonemes:
                golds[word] = phonemes
                applied += 1
    return applied


class KokoroRuntime:
    def __init__(self) -> None:
        with contextlib.redirect_stdout(sys.stderr):
            np = importlib.import_module("numpy")
            KPipeline = getattr(importlib.import_module("kokoro"), "KPipeline")

        self._np = np
        self._pipeline_type = KPipeline
        self._pipelines: dict[str, Any] = {}

    def synthesize(
        self,
        text: str,
        options: Mapping[str, Any],
        output_path: Path,
    ) -> None:
        voice = str(options.get("voice") or "").strip()
        if not voice:
            raise ValueError("Kokoro voice must not be blank")
        language = voice.split("_", 1)[0][:1].lower()
        if not language or not language.isalpha():
            raise ValueError(f"cannot determine Kokoro language from voice {voice!r}")
        pipeline = self._pipelines.get(language)
        if pipeline is None:
            _event("info", f"Loading Kokoro language pipeline {language!r}")
            with contextlib.redirect_stdout(sys.stderr):
                pipeline = self._pipeline_type(lang_code=language)
            self._pipelines[language] = pipeline

        _apply_pronunciation_overrides(pipeline, options)

        speed = _kokoro_speed(options)
        pieces = []
        with contextlib.redirect_stdout(sys.stderr):
            for _, _, audio in pipeline(text, voice=voice, speed=speed):
                pieces.append(self._np.asarray(audio, dtype=self._np.float32).reshape(-1))
        if pieces:
            samples = self._np.concatenate(pieces)
        else:
            samples = self._np.zeros(1, dtype=self._np.float32)
        pcm = (
            self._np.clip(samples, -1.0, 1.0) * 32767.0
        ).astype("<i2", copy=False)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = output_path.with_name(f".{output_path.name}.{os.getpid()}.tmp")
        try:
            temporary_path.write_bytes(pcm.tobytes())
            os.replace(temporary_path, output_path)
        finally:
            temporary_path.unlink(missing_ok=True)


def _kokoro_speed(options: Mapping[str, Any]) -> float:
    variables = options.get("variables")
    if isinstance(variables, Mapping) and "speed" in variables:
        raw_speed = variables["speed"]
        if isinstance(raw_speed, bool) or not isinstance(raw_speed, (int, float)):
            raise ValueError("Kokoro speed variable must be numeric")
        speed = float(raw_speed)
        if not 0.5 <= speed <= 2.0:
            raise ValueError("Kokoro speed variable must be between 0.5 and 2.0")
        return speed
    controls = options.get("controls")
    pace = controls.get("pace", "normal") if isinstance(controls, Mapping) else "normal"
    try:
        return PACE_SPEEDS[str(pace)]
    except KeyError as error:
        raise ValueError(f"unsupported Kokoro pace {pace!r}") from error


def _runtime(engine: str) -> EngineRuntime:
    if engine == "kokoro-local":
        return KokoroRuntime()
    raise ValueError(f"unknown local engine {engine!r}")


def _emit(message: Mapping[str, Any]) -> None:
    print(
        json.dumps(message, ensure_ascii=False, allow_nan=False, separators=(",", ":")),
        flush=True,
    )


def _event(level: str, message: str) -> None:
    _emit({"type": "event", "level": level, "message": message})


def _handle_synthesis(runtime: EngineRuntime, message: Mapping[str, Any]) -> None:
    request_id = str(message.get("id") or "")
    text = message.get("text")
    options = message.get("options")
    output_path_value = message.get("output_path")
    if not request_id:
        raise ValueError("synthesis request id must not be blank")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("synthesis text must not be blank")
    if not isinstance(options, Mapping):
        raise ValueError("synthesis options must be an object")
    if not isinstance(output_path_value, str) or not output_path_value:
        raise ValueError("synthesis output_path must not be blank")
    output_path = Path(output_path_value)
    if not output_path.is_absolute():
        raise ValueError("synthesis output_path must be absolute")

    runtime.synthesize(text, options, output_path)
    _emit(
        {
            "type": "result",
            "id": request_id,
            "output_path": str(output_path),
            "audio_format": {
                "sample_rate": 24_000,
                "channels": 1,
                "sample_width": 2,
                "encoding": "pcm_s16le",
            },
        }
    )


def run(engine: str) -> int:
    try:
        runtime = _runtime(engine)
    except Exception:
        traceback.print_exc(file=sys.stderr)
        return 2
    _emit({"type": "ready", "protocol": PROTOCOL_VERSION, "engine": engine})

    for line in sys.stdin:
        if not line.strip():
            continue
        request_id = ""
        try:
            message = json.loads(line)
            if not isinstance(message, dict):
                raise ValueError("worker command must be a JSON object")
            request_id = str(message.get("id") or "")
            message_type = message.get("type")
            if message_type == "shutdown":
                return 0
            if message_type != "synthesize":
                raise ValueError(f"unknown worker command {message_type!r}")
            _handle_synthesis(runtime, message)
        except Exception as error:
            traceback.print_exc(file=sys.stderr)
            _emit(
                {
                    "type": "error",
                    "id": request_id,
                    "message": str(error) or error.__class__.__name__,
                    "error_type": error.__class__.__name__,
                    "retryable": False,
                }
            )
    return 0


def _gold_to_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        preferred = value.get("DEFAULT") or next(iter(value.values()), "")
        others = [str(key) for key in value if key != "DEFAULT"]
        if others:
            return f"{preferred}  (varies by role: {', '.join(sorted(others))})"
        return str(preferred)
    return str(value)


def _pronunciation_overrides(payload: Mapping[str, Any]) -> dict[str, str]:
    value = payload.get("overrides")
    if not isinstance(value, Mapping):
        return {}
    return {
        str(key).strip().lower(): str(item).strip()
        for key, item in value.items()
        if str(key).strip()
        and str(item).strip()
        and not str(key).endswith("__respelling")
    }


def _misaki_g2p():
    with contextlib.redirect_stdout(sys.stderr):
        misaki_en = importlib.import_module("misaki.en")
        return misaki_en.G2P(trf=False, british=False)


def _tool_lookup_words(payload: Mapping[str, Any]) -> dict[str, Any]:
    query = str(payload.get("query") or "").strip().lower()
    limit = max(1, min(int(payload.get("limit") or 150), 500))
    overrides = _pronunciation_overrides(payload)
    g2p = _misaki_g2p()
    golds = getattr(g2p.lexicon, "golds", {}) or {}
    words = set(golds)
    words.update(overrides)
    if query:
        starts = sorted(word for word in words if word.startswith(query))
        contains = sorted(
            word for word in words if query in word and not word.startswith(query)
        )
        hits = starts + contains
    else:
        hits = sorted(words)
    matches = []
    for word in hits[:limit]:
        if word in overrides:
            matches.append(
                {"word": word, "phonemes": overrides[word], "source": "override"}
            )
        else:
            matches.append(
                {
                    "word": word,
                    "phonemes": _gold_to_text(golds.get(word, "")),
                    "source": "dictionary",
                }
            )
    return {"matches": matches, "total": len(hits), "error": None}


def _tool_current_phonemes(payload: Mapping[str, Any]) -> dict[str, Any]:
    original = str(payload.get("word") or "")
    word = original.strip().lower()
    if not word:
        raise ValueError("No word given.")
    overrides = _pronunciation_overrides(payload)
    if word in overrides:
        return {
            "word": original,
            "phonemes": overrides[word],
            "source": "override",
            "error": None,
        }
    g2p = _misaki_g2p()
    golds = getattr(g2p.lexicon, "golds", {}) or {}
    if word in golds:
        return {
            "word": original,
            "phonemes": _gold_to_text(golds[word]),
            "source": "dictionary",
            "error": None,
        }
    phonemes, _ = g2p(original)
    if phonemes in ("", "❓", None):
        return {
            "word": original,
            "phonemes": None,
            "source": None,
            "error": "Kokoro cannot pronounce this word.",
        }
    return {
        "word": original,
        "phonemes": phonemes,
        "source": "guessed",
        "error": None,
    }


def _tool_respell_to_ipa(payload: Mapping[str, Any]) -> dict[str, Any]:
    respelling = str(payload.get("respelling") or "").strip()
    raw_pieces = respelling.split()
    if not raw_pieces:
        return {"ipa": "", "failed": None}
    pieces: list[str] = []
    stress_on: int | None = None
    for index, raw_piece in enumerate(raw_pieces):
        piece = raw_piece
        if piece.startswith("*") and len(piece) > 1:
            stress_on = index
            piece = piece[1:]
        pieces.append(piece)
    if stress_on is None:
        stress_on = 0
    g2p = _misaki_g2p()
    phoneme_parts = []
    for index, piece in enumerate(pieces):
        result, _ = g2p(piece)
        if not result or result == "❓":
            return {"ipa": None, "failed": piece}
        if index != stress_on:
            result = result.replace("ˈ", "ˌ")
        phoneme_parts.append(result)
    return {"ipa": "".join(phoneme_parts) or None, "failed": None}


def run_tool(operation: str) -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        if not isinstance(payload, Mapping):
            raise ValueError("tool payload must be a JSON object")
        with contextlib.redirect_stdout(sys.stderr):
            if operation == "lookup_words":
                result = _tool_lookup_words(payload)
            elif operation == "current_phonemes":
                result = _tool_current_phonemes(payload)
            elif operation == "respell_to_ipa":
                result = _tool_respell_to_ipa(payload)
            else:
                raise ValueError(f"unknown tool operation {operation!r}")
    except Exception as error:
        result = {
            "error_type": error.__class__.__name__,
            "message": str(error) or error.__class__.__name__,
        }
    sys.stdout.write(json.dumps(result, ensure_ascii=False, allow_nan=False))
    sys.stdout.flush()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="SPLICR isolated local-engine worker")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--engine")
    mode.add_argument("--tool")
    args = parser.parse_args()
    if args.tool:
        raise SystemExit(run_tool(args.tool))
    raise SystemExit(run(args.engine))


if __name__ == "__main__":
    main()
