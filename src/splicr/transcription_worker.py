"""One-shot JSON-lines worker for optional faster-whisper environments.

The module deliberately imports only the standard library until a transcription request starts.
It can therefore be launched by an isolated Python environment that contains faster-whisper but
does not contain SPLICR itself.
"""

from __future__ import annotations

import contextlib
import importlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping


PROTOCOL_VERSION = 1


def _emit(message: Mapping[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False, allow_nan=False) + "\n")
    sys.stdout.flush()


def _safe_error(error: BaseException, payload: Mapping[str, Any]) -> str:
    detail = str(error).strip() or type(error).__name__
    for key, replacement in (("audio_path", "<audio>"), ("download_root", "<model-cache>")):
        value = str(payload.get(key) or "").strip()
        if value:
            detail = detail.replace(value, replacement)
    return detail[-2_000:]


def _error_code(error: BaseException, stage: str) -> str:
    if isinstance(error, (ImportError, ModuleNotFoundError)):
        return "component_missing"
    text = f"{type(error).__name__}: {error}".casefold()
    if any(word in text for word in ("huggingface", "download", "connection", "network", "http")):
        return "model_download_failed"
    if stage == "model":
        return "model_load_failed"
    return "recognition_failed"


def _word_payload(word: Any) -> dict[str, object]:
    return {
        "start": float(word.start),
        "end": float(word.end),
        "text": str(word.word or "").strip(),
    }


def _segment_payload(segment: Any, *, include_words: bool) -> dict[str, object]:
    words = []
    if include_words:
        words = [
            _word_payload(word) for word in (segment.words or []) if str(word.word or "").strip()
        ]
    return {
        "start": float(segment.start),
        "end": float(segment.end),
        "text": str(segment.text or "").strip(),
        "words": words,
    }


def _transcribe(payload: Mapping[str, Any]) -> None:
    stage = "component"
    try:
        with contextlib.redirect_stdout(sys.stderr):
            WhisperModel = getattr(importlib.import_module("faster_whisper"), "WhisperModel")

        audio_path = Path(str(payload.get("audio_path") or "")).resolve()
        if not audio_path.is_file():
            raise FileNotFoundError("the managed audio source is missing")
        model_name = str(payload.get("model") or "base").strip()
        device = str(payload.get("device") or "auto").strip()
        compute_type = str(payload.get("compute_type") or "default").strip()
        download_root_value = str(payload.get("download_root") or "").strip()
        download_root = download_root_value or None
        if download_root:
            Path(download_root).mkdir(parents=True, exist_ok=True)

        stage = "model"
        _emit({"type": "phase", "phase": "loading_model", "progress": 0.01})
        with contextlib.redirect_stdout(sys.stderr):
            model = WhisperModel(
                model_name,
                device=device,
                compute_type=compute_type,
                download_root=download_root,
            )

        stage = "recognition"
        language_value = str(payload.get("language") or "").strip()
        include_words = bool(payload.get("word_timestamps", False))
        with contextlib.redirect_stdout(sys.stderr):
            segments, info = model.transcribe(
                str(audio_path),
                language=language_value or None,
                word_timestamps=include_words,
                vad_filter=bool(payload.get("vad_filter", True)),
            )
        duration = float(getattr(info, "duration", 0.0) or 0.0)
        _emit(
            {
                "type": "metadata",
                "language": getattr(info, "language", None),
                "language_probability": getattr(info, "language_probability", None),
                "duration": duration,
            }
        )
        count = 0
        for count, segment in enumerate(segments, 1):
            item = _segment_payload(segment, include_words=include_words)
            _emit(
                {
                    "type": "segment",
                    "index": count - 1,
                    "segment": item,
                    "processed_seconds": item["end"],
                    "duration": duration,
                }
            )
        _emit({"type": "complete", "segment_count": count})
    except BaseException as error:
        _emit(
            {
                "type": "error",
                "code": _error_code(error, stage),
                "message": _safe_error(error, payload),
                "exception_type": type(error).__name__,
                "stage": stage,
            }
        )


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, OSError) as error:
        _emit({"type": "error", "code": "invalid_request", "message": str(error)})
        return 2
    if not isinstance(payload, dict):
        _emit({"type": "error", "code": "invalid_request", "message": "request must be an object"})
        return 2
    _emit(
        {
            "type": "ready",
            "protocol": PROTOCOL_VERSION,
            "provider": "faster-whisper",
        }
    )
    _transcribe(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
