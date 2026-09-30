"""Standalone JSON-lines worker for isolated local synthesis environments.

This module intentionally imports only the standard library at module load. Engine-specific
dependencies are imported after argument parsing so the file can be executed by an isolated
environment without installing the rest of SPLICR into that environment.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import traceback
import wave
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
VOICE_PROFILE_VARIABLE = "__splicr_voice_profile"
QWEN_SEED_VARIABLE = "seed"
QWEN_CLONE_REPOS = (
    "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
    "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
)
QWEN_CUSTOM_REPO = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
QWEN_DESIGN_REPO = "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"
QWEN_REFERENCE_TEXT = (
    "This is a short reference recording. It is made once, from a written "
    "description, so that every chapter that follows can be read in this "
    "same voice, at this same steady pace."
)
QWEN_SAMPLING = {
    "temperature": 0.75,
    "subtalker_temperature": 0.75,
    "top_k": 50,
    "top_p": 1.0,
    "repetition_penalty": 1.05,
}
AUDIO8_REPO = "Audio8/Audio8-TTS-Preview-0.6b"


class EngineRuntime(Protocol):
    def synthesize(
        self,
        text: str,
        options: Mapping[str, Any],
        output_path: Path,
    ) -> Mapping[str, Any] | None: ...


class EngineWorkerRequestError(RuntimeError):
    def __init__(self, message: str, *, code: str, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


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


def _voice_profile(options: Mapping[str, Any]) -> Mapping[str, Any]:
    variables = options.get("variables")
    if not isinstance(variables, Mapping):
        raise ValueError("local voice engine requires job variables")
    snapshot = variables.get(VOICE_PROFILE_VARIABLE)
    if not isinstance(snapshot, Mapping):
        raise ValueError("select a compatible Voice Profile before rendering")
    return snapshot


def _profile_settings(snapshot: Mapping[str, Any]) -> Mapping[str, Any]:
    settings = snapshot.get("settings")
    return settings if isinstance(settings, Mapping) else {}


def _reference_voice(snapshot: Mapping[str, Any]) -> tuple[str, str]:
    reference_path = str(snapshot.get("reference_audio_path") or "").strip()
    reference_text = str(snapshot.get("reference_text") or "").strip()
    if not reference_path or not Path(reference_path).is_file():
        raise ValueError("Voice Profile reference audio is missing or unreadable")
    if not reference_text:
        raise ValueError("Voice Profile needs the exact reference transcript")
    return reference_path, reference_text


def _seed_for(
    snapshot: Mapping[str, Any],
    text: str,
    variables: Mapping[str, Any] | None = None,
) -> int:
    seed = None if variables is None else variables.get(QWEN_SEED_VARIABLE)
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
        raise ValueError("Qwen synthesis seed must be an integer")
    prefix = "" if seed is None else f"{seed}|"
    raw = f"{prefix}{snapshot.get('id', '')}|{snapshot.get('updated_at', '')}|{text}"
    return int(hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8], 16)


def _audio_pieces(text: str, limit: int) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    pieces: list[str] = []
    for sentence in sentences:
        remaining = sentence.strip()
        while len(remaining) > limit:
            cut = remaining.rfind(" ", 0, limit + 1)
            if cut < limit // 2:
                cut = limit
            pieces.append(remaining[:cut].strip())
            remaining = remaining[cut:].strip()
        if remaining:
            pieces.append(remaining)
    return pieces


def _write_canonical_pcm(
    np: Any,
    samples: Any,
    sample_rate: int,
    output_path: Path,
) -> None:
    if sample_rate < 1:
        raise ValueError("engine returned an invalid sample rate")
    audio = np.asarray(samples, dtype=np.float32)
    if audio.ndim > 1:
        channel_axis = 0 if audio.shape[0] <= 8 else 1
        audio = audio.mean(axis=channel_axis)
    audio = audio.reshape(-1)
    if not len(audio):
        audio = np.zeros(1, dtype=np.float32)
    if sample_rate != 24_000:
        output_length = max(1, round(len(audio) * 24_000 / sample_rate))
        source_positions = np.linspace(0.0, 1.0, num=len(audio), endpoint=False)
        target_positions = np.linspace(0.0, 1.0, num=output_length, endpoint=False)
        audio = np.interp(target_positions, source_positions, audio).astype(np.float32)
    pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2", copy=False)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(f".{output_path.name}.{os.getpid()}.tmp")
    try:
        temporary_path.write_bytes(pcm.tobytes())
        os.replace(temporary_path, output_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _write_canonical_wav(np: Any, samples: Any, sample_rate: int, output_path: Path) -> int:
    if sample_rate < 1:
        raise ValueError("engine returned an invalid sample rate")
    audio = np.asarray(samples, dtype=np.float32)
    if audio.ndim > 1:
        channel_axis = 0 if audio.shape[0] <= 8 else 1
        audio = audio.mean(axis=channel_axis)
    audio = audio.reshape(-1)
    if not len(audio):
        raise ValueError("VoiceDesign returned empty audio")
    if sample_rate != 24_000:
        output_length = max(1, round(len(audio) * 24_000 / sample_rate))
        source_positions = np.linspace(0.0, 1.0, num=len(audio), endpoint=False)
        target_positions = np.linspace(0.0, 1.0, num=output_length, endpoint=False)
        audio = np.interp(target_positions, source_positions, audio).astype(np.float32)
    pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2", copy=False)
    frame_count = len(audio)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(f".{output_path.name}.{os.getpid()}.tmp")
    try:
        with wave.open(str(temporary_path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(24_000)
            output.writeframes(pcm.tobytes())
        os.replace(temporary_path, output_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return frame_count


class Qwen3Runtime:
    def __init__(self) -> None:
        with contextlib.redirect_stdout(sys.stderr):
            self._np = importlib.import_module("numpy")
            self._torch = importlib.import_module("torch")
            self._model_type = getattr(importlib.import_module("qwen_tts"), "Qwen3TTSModel")
        self._model: Any | None = None
        self._model_repo: str | None = None
        self._prompt: Any | None = None
        self._prompt_profile_id: str | None = None

    def _load_model(self, repo: str) -> Any:
        if self._model is not None and self._model_repo == repo:
            return self._model
        if self._model is not None:
            self._model = None
            self._prompt = None
            self._prompt_profile_id = None
            if self._torch.cuda.is_available():
                self._torch.cuda.empty_cache()
        kwargs: dict[str, Any] = {}
        if self._torch.cuda.is_available():
            _event("info", f"Loading Qwen3-TTS on {self._torch.cuda.get_device_name(0)}")
            kwargs = {"device_map": "cuda:0", "dtype": self._torch.bfloat16}
        else:
            _event("warning", "CUDA is unavailable; Qwen3-TTS will be slow on CPU")
        with contextlib.redirect_stdout(sys.stderr):
            self._model = self._model_type.from_pretrained(repo, **kwargs)
        self._model_repo = repo
        return self._model

    def synthesize(
        self,
        text: str,
        options: Mapping[str, Any],
        output_path: Path,
    ) -> None:
        snapshot = _voice_profile(options)
        settings = _profile_settings(snapshot)
        kind = str(snapshot.get("kind") or "")
        sampling = dict(QWEN_SAMPLING)
        custom_sampling = settings.get("sampling")
        if isinstance(custom_sampling, Mapping):
            for key in QWEN_SAMPLING:
                if key in custom_sampling:
                    sampling[key] = custom_sampling[key]
        variables = options.get("variables")
        self._torch.manual_seed(
            _seed_for(
                snapshot,
                text,
                variables if isinstance(variables, Mapping) else None,
            )
        )
        budget = max(2048, min(8192, len(text) * 2))

        if kind == "preset":
            model = self._load_model(QWEN_CUSTOM_REPO)
            speaker = str(settings.get("speaker") or settings.get("voice_id") or "").strip()
            if not speaker:
                raise ValueError("Qwen3 preset Voice Profile has no speaker")
            directions = [
                str(settings.get("instructions") or "").strip(),
                str(options.get("instructions") or "").strip(),
            ]
            instruction = ". ".join(item for item in directions if item) or None
            with contextlib.redirect_stdout(sys.stderr):
                wavs, rate = model.generate_custom_voice(
                    text=text,
                    speaker=speaker,
                    instruct=instruction,
                    language=str(settings.get("language") or "English"),
                    max_new_tokens=budget,
                    **sampling,
                )
        elif kind in {"cloned", "designed"}:
            reference_path, reference_text = _reference_voice(snapshot)
            requested_model = str(options.get("model") or "")
            repo = requested_model if requested_model in QWEN_CLONE_REPOS else QWEN_CLONE_REPOS[0]
            model = self._load_model(repo)
            profile_id = str(snapshot.get("id") or "")
            if self._prompt is None or self._prompt_profile_id != profile_id:
                with contextlib.redirect_stdout(sys.stderr):
                    self._prompt = model.create_voice_clone_prompt(
                        ref_audio=reference_path,
                        ref_text=reference_text,
                        x_vector_only_mode=False,
                    )
                self._prompt_profile_id = profile_id
            with contextlib.redirect_stdout(sys.stderr):
                wavs, rate = model.generate_voice_clone(
                    text=text,
                    language=str(settings.get("language") or "English"),
                    voice_clone_prompt=self._prompt,
                    max_new_tokens=budget,
                    **sampling,
                )
        else:
            raise ValueError(f"Qwen3 does not support Voice Profile kind {kind!r}")
        _write_canonical_pcm(self._np, wavs[0], int(rate), output_path)


class Audio8Runtime:
    def __init__(self) -> None:
        with contextlib.redirect_stdout(sys.stderr):
            self._np = importlib.import_module("numpy")
            self._torch = importlib.import_module("torch")
            transformers = importlib.import_module("transformers")
            self._model_type = getattr(transformers, "AutoModel")
            self._processor_type = getattr(transformers, "AutoProcessor")
        self._model: Any | None = None
        self._processor: Any | None = None
        self._device = "cuda" if self._torch.cuda.is_available() else "cpu"

    def _load(self) -> tuple[Any, Any]:
        if self._model is not None and self._processor is not None:
            return self._model, self._processor
        if self._device == "cpu":
            _event("warning", "CUDA is unavailable; Audio8 will be slow on CPU")
        _event("info", f"Loading {AUDIO8_REPO}")
        with contextlib.redirect_stdout(sys.stderr):
            processor = self._processor_type.from_pretrained(
                AUDIO8_REPO,
                trust_remote_code=True,
            )
            model = self._model_type.from_pretrained(
                AUDIO8_REPO,
                trust_remote_code=True,
                dtype=(self._torch.bfloat16 if self._device == "cuda" else self._torch.float32),
            ).to(self._device)
            model.eval()
        self._processor = processor
        self._model = model
        return model, processor

    @staticmethod
    def _duration_is_plausible(text: str, seconds: float) -> bool:
        characters = max(1, len(text))
        return seconds > 0 and seconds >= (characters / 20.0) * 0.5 and seconds <= characters * 0.5

    @staticmethod
    def _decoded_waveform(model: Any, generated: Any) -> tuple[Any, int]:
        """Normalize the current Audio8 decoder contract and its preview predecessor."""
        codes = getattr(generated, "codes", generated)
        decoded, length_or_rate = model.decode_audio(codes)
        configured_rate = getattr(getattr(model, "config", None), "codec_sample_rate", None)
        if configured_rate is None:
            # Early preview builds returned ``(waveform, sample_rate)`` directly.
            return decoded, int(length_or_rate)

        length = int(length_or_rate[0])
        try:
            waveform = decoded[0, :length]
        except (IndexError, TypeError):
            waveform = decoded[0][:length]
        for conversion in ("float", "cpu", "numpy"):
            method = getattr(waveform, conversion, None)
            if callable(method):
                waveform = method()
        return waveform, int(configured_rate)

    def synthesize(
        self,
        text: str,
        options: Mapping[str, Any],
        output_path: Path,
    ) -> None:
        snapshot = _voice_profile(options)
        if str(snapshot.get("kind") or "") != "cloned":
            raise ValueError("Audio8 requires a cloned Voice Profile")
        reference_path, reference_text = _reference_voice(snapshot)
        model, processor = self._load()
        pieces = []
        rate = 44_100
        for piece in _audio_pieces(text, 150):
            accepted_audio = None
            for attempt in range(1, 4):
                with contextlib.redirect_stdout(sys.stderr):
                    try:
                        inputs = processor(
                            text=[piece],
                            reference_audio=[reference_path],
                            reference_text=[reference_text],
                            return_tensors="pt",
                        ).to(self._device)
                    except TypeError:
                        # Preserve compatibility with the original preview processor.
                        inputs = processor(
                            text=piece,
                            ref_audio=reference_path,
                            ref_text=reference_text,
                            return_tensors="pt",
                        ).to(self._device)
                    with self._torch.no_grad():
                        generated = model.generate(
                            **inputs,
                            max_new_tokens=1024,
                            temperature=0.8,
                            top_p=0.95,
                            top_k=50,
                            do_sample=True,
                            return_dict_in_generate=True,
                        )
                    audio, rate = self._decoded_waveform(model, generated)
                flattened = self._np.asarray(audio, dtype=self._np.float32).reshape(-1)
                seconds = len(flattened) / rate if rate else 0.0
                if self._duration_is_plausible(piece, seconds):
                    accepted_audio = flattened
                    break
                _event(
                    "warning",
                    f"Audio8 retry {attempt}/3: implausible {seconds:.2f}s result",
                )
            if accepted_audio is None:
                raise EngineWorkerRequestError(
                    "Audio8 returned implausible audio after three attempts",
                    code="audio8_implausible_output",
                    retryable=True,
                )
            pieces.append(accepted_audio)
        merged = self._np.concatenate(pieces) if pieces else self._np.zeros(1, dtype=self._np.float32)
        _write_canonical_pcm(self._np, merged, int(rate), output_path)


class EdgeRuntime:
    def __init__(self) -> None:
        self.edge_tts = importlib.import_module("edge_tts")
        self.ffmpeg = shutil.which("ffmpeg")
        if self.ffmpeg is None:
            raise RuntimeError("Edge TTS requires ffmpeg on PATH")

    def synthesize(
        self,
        text: str,
        options: Mapping[str, Any],
        output_path: Path,
    ) -> Mapping[str, Any]:
        voice = str(options.get("voice") or "").strip()
        if not voice:
            raise EngineWorkerRequestError(
                "Edge TTS voice must not be blank",
                code="edge_voice_not_found",
                retryable=False,
            )
        variables = options.get("variables")
        values = variables if isinstance(variables, Mapping) else {}
        controls = options.get("controls")
        delivery = controls if isinstance(controls, Mapping) else {}
        rate_value = values.get("rate_percent")
        if rate_value is None:
            pace = str(delivery.get("pace") or "normal")
            rate_percent = round((PACE_SPEEDS.get(pace, 1.0) - 1.0) * 100)
        else:
            rate_percent = int(rate_value)
        pitch_hz = int(values.get("pitch_hz", 0))
        volume_percent = int(values.get("volume_percent", 0))
        boundary_value = str(values.get("timing_boundary") or "sentence")
        boundary = "WordBoundary" if boundary_value == "word" else "SentenceBoundary"
        mp3, timings = asyncio.run(
            self._stream(
                text,
                voice,
                rate=f"{rate_percent:+d}%",
                volume=f"{volume_percent:+d}%",
                pitch=f"{pitch_hz:+d}Hz",
                boundary=boundary,
            )
        )
        completed = subprocess.run(
            [
                self.ffmpeg,
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "mp3",
                "-i",
                "pipe:0",
                "-f",
                "s16le",
                "-acodec",
                "pcm_s16le",
                "-ac",
                "1",
                "-ar",
                "24000",
                "pipe:1",
            ],
            input=mp3,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0 or not completed.stdout:
            detail = completed.stderr.decode("utf-8", errors="replace")[-1000:]
            raise EngineWorkerRequestError(
                f"Edge TTS audio conversion failed: {detail}",
                code="edge_audio_conversion_failed",
                retryable=False,
            )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = output_path.with_name(f".{output_path.name}.{os.getpid()}.tmp")
        try:
            temporary.write_bytes(completed.stdout)
            os.replace(temporary, output_path)
        finally:
            temporary.unlink(missing_ok=True)
        return {"timings": timings, "timing_boundary": boundary_value}

    async def _stream(
        self,
        text: str,
        voice: str,
        *,
        rate: str,
        volume: str,
        pitch: str,
        boundary: str,
    ) -> tuple[bytes, list[dict[str, object]]]:
        audio = bytearray()
        timings: list[dict[str, object]] = []
        try:
            communicate = self.edge_tts.Communicate(
                text,
                voice,
                rate=rate,
                volume=volume,
                pitch=pitch,
                boundary=boundary,
            )
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio.extend(chunk["data"])
                elif chunk["type"] in {"WordBoundary", "SentenceBoundary"}:
                    timings.append(
                        {
                            "type": str(chunk["type"]),
                            "start_seconds": round(int(chunk["offset"]) / 10_000_000, 6),
                            "duration_seconds": round(
                                int(chunk["duration"]) / 10_000_000, 6
                            ),
                            "text": str(chunk["text"]),
                        }
                    )
        except Exception as error:
            name = error.__class__.__name__
            message = str(error) or name
            if name in {"ClientResponseError", "WSServerHandshakeError"} and "429" in message:
                code, retryable = "edge_rate_limited", True
            elif name in {
                "ClientConnectionError",
                "ClientConnectorError",
                "ServerTimeoutError",
                "TimeoutError",
                "WebSocketError",
            }:
                code, retryable = "edge_offline", True
            elif name in {"NoAudioReceived", "ValueError"}:
                code, retryable = "edge_voice_not_found", False
            else:
                code, retryable = "edge_request_failed", True
            raise EngineWorkerRequestError(
                f"Edge TTS request failed: {message}",
                code=code,
                retryable=retryable,
            ) from error
        if not audio:
            raise EngineWorkerRequestError(
                "Edge TTS returned no audio",
                code="edge_no_audio",
                retryable=True,
            )
        return bytes(audio), timings


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
    if engine == "qwen3-local":
        return Qwen3Runtime()
    if engine == "audio8-local":
        return Audio8Runtime()
    if engine == "edge-tts":
        return EdgeRuntime()
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

    metadata = runtime.synthesize(text, options, output_path)
    response: dict[str, Any] = {
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
    if metadata:
        response["metadata"] = dict(metadata)
    _emit(response)


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
                    "code": getattr(error, "code", "local_engine_error"),
                    "retryable": bool(getattr(error, "retryable", False)),
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


def _tool_qwen_voice_design(payload: Mapping[str, Any]) -> dict[str, Any]:
    description = " ".join(str(payload.get("description") or "").split())
    if not description:
        raise ValueError("voice description must not be blank")
    take = int(payload.get("take") or 0)
    if not 1 <= take <= 99:
        raise ValueError("voice design take must be between 1 and 99")
    output_path = Path(str(payload.get("output_path") or ""))
    result_path = Path(str(payload.get("result_path") or ""))
    if not output_path.is_absolute() or not result_path.is_absolute():
        raise ValueError("voice design output paths must be absolute")

    np = importlib.import_module("numpy")
    torch = importlib.import_module("torch")
    model_type = getattr(importlib.import_module("qwen_tts"), "Qwen3TTSModel")
    kwargs: dict[str, Any] = {}
    if torch.cuda.is_available():
        kwargs = {"device_map": "cuda:0", "dtype": torch.bfloat16}
    seed = 1000 + take
    torch.manual_seed(seed)
    model = model_type.from_pretrained(QWEN_DESIGN_REPO, **kwargs)
    wavs, sample_rate = model.generate_voice_design(
        text=QWEN_REFERENCE_TEXT,
        instruct=description,
        language="English",
    )
    frames = _write_canonical_wav(np, wavs[0], int(sample_rate), output_path)
    result: dict[str, Any] = {
        "output_path": str(output_path.resolve()),
        "reference_text": QWEN_REFERENCE_TEXT,
        "model": QWEN_DESIGN_REPO,
        "seed": seed,
        "sample_rate": 24_000,
        "seconds": frames / 24_000,
    }
    result_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = result_path.with_name(f".{result_path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(temporary, result_path)
    finally:
        temporary.unlink(missing_ok=True)
    return result


def _tool_edge_voices(payload: Mapping[str, Any]) -> dict[str, Any]:
    del payload
    edge_tts = importlib.import_module("edge_tts")
    voices = asyncio.run(edge_tts.list_voices())
    normalized = []
    for raw in voices:
        tags = raw.get("VoiceTag")
        personalities = tags.get("VoicePersonalities", []) if isinstance(tags, dict) else []
        normalized.append(
            {
                "short_name": str(raw.get("ShortName") or ""),
                "locale": str(raw.get("Locale") or ""),
                "gender": str(raw.get("Gender") or ""),
                "personalities": [str(value) for value in personalities],
            }
        )
    normalized = sorted(
        (voice for voice in normalized if voice["short_name"]),
        key=lambda voice: str(voice["short_name"]),
    )
    return {"voices": normalized}


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
            elif operation == "qwen_voice_design":
                result = _tool_qwen_voice_design(payload)
            elif operation == "edge_voices":
                result = _tool_edge_voices(payload)
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
