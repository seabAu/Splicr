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


class EngineRuntime(Protocol):
    def synthesize(
        self,
        text: str,
        options: Mapping[str, Any],
        output_path: Path,
    ) -> None: ...


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


def main() -> None:
    parser = argparse.ArgumentParser(description="SPLICR isolated local-engine worker")
    parser.add_argument("--engine", required=True)
    args = parser.parse_args()
    raise SystemExit(run(args.engine))


if __name__ == "__main__":
    main()
