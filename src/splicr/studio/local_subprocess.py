from __future__ import annotations

import asyncio
import json
import os
import subprocess
import uuid
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator, Mapping, cast

from splicr.domain import (
    AudioChunk,
    AudioFormat,
    JsonValue,
    ProviderDiagnostic,
    ProviderError,
    SynthesisOptions,
)

from .engines import EngineDescriptor, EngineSession, EngineSessionContext


LOCAL_ENGINE_PROTOCOL_VERSION = 1


@dataclass(frozen=True, slots=True)
class LocalSubprocessSpec:
    command: tuple[str, ...]
    environment: Mapping[str, str] = field(default_factory=dict)
    startup_timeout_seconds: float = 600.0
    request_timeout_seconds: float = 300.0
    shutdown_timeout_seconds: float = 5.0
    max_message_bytes: int = 1_000_000
    max_output_bytes: int = 256_000_000

    def __post_init__(self) -> None:
        if not self.command or any(not part for part in self.command):
            raise ValueError("local engine command must not be empty")
        for name in (
            "startup_timeout_seconds",
            "request_timeout_seconds",
            "shutdown_timeout_seconds",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.max_message_bytes < 1_024:
            raise ValueError("max_message_bytes must be at least 1024")
        if self.max_output_bytes < 2:
            raise ValueError("max_output_bytes must be at least 2")


class LocalSubprocessEngineAdapter:
    """Run one isolated engine process for the lifetime of a synthesis job."""

    def __init__(self, descriptor: EngineDescriptor, spec: LocalSubprocessSpec) -> None:
        self._descriptor = descriptor
        self.spec = spec

    @property
    def descriptor(self) -> EngineDescriptor:
        return self._descriptor

    def estimate_input_tokens(self, text: str, options: SynthesisOptions) -> int:
        del options
        return max(1, len(text))

    def estimate_input_characters(self, text: str, options: SynthesisOptions) -> int:
        del options
        return len(text)

    @asynccontextmanager
    async def open_session(
        self,
        context: EngineSessionContext,
    ) -> AsyncIterator[EngineSession]:
        session = _LocalSubprocessEngineSession(self.descriptor, self.spec, context)
        await session.start()
        try:
            yield session
        finally:
            close_task = asyncio.create_task(session.close())
            try:
                await asyncio.shield(close_task)
            except asyncio.CancelledError:
                await close_task
                raise


class _LocalSubprocessEngineSession:
    def __init__(
        self,
        descriptor: EngineDescriptor,
        spec: LocalSubprocessSpec,
        context: EngineSessionContext,
    ) -> None:
        self.descriptor = descriptor
        self.spec = spec
        self.context = context
        self._process: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._stderr_tail: deque[str] = deque(maxlen=40)
        self._events: deque[dict[str, object]] = deque(maxlen=100)
        self._request_lock = asyncio.Lock()
        self._closed = False

    async def start(self) -> None:
        if self._closed:
            raise RuntimeError("local engine session is closed")
        if self._process is not None and self._process.returncode is None:
            return

        engine_directory = self.context.work_directory / ".engine"
        engine_directory.mkdir(parents=True, exist_ok=True)
        environment = os.environ.copy()
        environment.update(self.spec.environment)
        try:
            self._process = await asyncio.create_subprocess_exec(
                *self.spec.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(engine_directory),
                env=environment,
                limit=self.spec.max_message_bytes,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            self._stderr_task = asyncio.create_task(self._read_stderr())
            message = await self._read_until_type(
                "ready",
                timeout=self.spec.startup_timeout_seconds,
            )
            protocol = message.get("protocol")
            if protocol != LOCAL_ENGINE_PROTOCOL_VERSION:
                raise RuntimeError(
                    f"unsupported local engine protocol {protocol!r}; "
                    f"expected {LOCAL_ENGINE_PROTOCOL_VERSION}"
                )
            worker_engine = message.get("engine")
            if worker_engine != self.descriptor.id:
                raise RuntimeError(
                    f"local worker identified itself as {worker_engine!r}, "
                    f"expected {self.descriptor.id!r}"
                )
        except asyncio.CancelledError:
            await self._stop_process(graceful=False)
            raise
        except Exception as error:
            await self._stop_process(graceful=False)
            if isinstance(error, ProviderError):
                raise
            raise self._provider_error(
                f"local engine failed to start: {error}",
                retryable=False,
                phase="startup",
                exception=error,
            ) from error

    async def synthesize(self, text: str, options: SynthesisOptions) -> AudioChunk:
        async with self._request_lock:
            if self._closed:
                raise self._provider_error(
                    "local engine session is closed",
                    retryable=False,
                    phase="synthesis",
                )
            if self._process is None or self._process.returncode is not None:
                await self.start()

            request_id = uuid.uuid4().hex
            output_path = self.context.work_directory / ".engine" / f"{request_id}.pcm"
            payload = {
                "type": "synthesize",
                "id": request_id,
                "text": text,
                "output_path": str(output_path.resolve()),
                "options": {
                    "model": options.model,
                    "voice": options.voice,
                    "instructions": options.instructions,
                    "controls": {
                        "tone": options.controls.tone.value,
                        "pace": options.controls.pace.value,
                        "vocal_style": options.controls.vocal_style.value,
                        "nonverbal_frequency": options.controls.nonverbal_frequency.value,
                    },
                    "variables": dict(options.variables),
                },
            }

            try:
                await self._write_message(payload)
                response = await self._read_response(
                    request_id,
                    timeout=self.spec.request_timeout_seconds,
                )
                if response.get("type") == "error":
                    raise self._provider_error(
                        str(response.get("message") or "local engine request failed"),
                        retryable=bool(response.get("retryable", False)),
                        phase="synthesis",
                        response=response,
                    )
                return await self._read_audio_result(response, output_path)
            except asyncio.CancelledError:
                await self._stop_process(graceful=False)
                raise
            except ProviderError:
                raise
            except asyncio.TimeoutError as error:
                await self._stop_process(graceful=False)
                raise self._provider_error(
                    "local engine request timed out",
                    retryable=True,
                    phase="synthesis",
                    exception=error,
                ) from error
            except Exception as error:
                await self._stop_process(graceful=False)
                raise self._provider_error(
                    f"local engine protocol failed: {error}",
                    retryable=True,
                    phase="synthesis",
                    exception=error,
                ) from error
            finally:
                output_path.unlink(missing_ok=True)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._stop_process(graceful=True)

    async def _read_audio_result(
        self,
        response: Mapping[str, object],
        expected_path: Path,
    ) -> AudioChunk:
        returned_path = Path(str(response.get("output_path", ""))).resolve()
        if returned_path != expected_path.resolve():
            raise ValueError("local engine returned an unexpected output path")
        if not returned_path.is_file():
            raise FileNotFoundError("local engine did not create its PCM output")
        output_size = returned_path.stat().st_size
        if output_size <= 0 or output_size > self.spec.max_output_bytes:
            raise ValueError(
                f"local engine PCM output size {output_size} is outside the allowed range"
            )

        format_value = response.get("audio_format")
        if not isinstance(format_value, Mapping):
            raise ValueError("local engine response is missing audio_format")
        audio_format = AudioFormat(
            sample_rate=int(format_value.get("sample_rate", 0)),
            channels=int(format_value.get("channels", 0)),
            sample_width=int(format_value.get("sample_width", 0)),
            encoding=str(format_value.get("encoding", "")),
        )
        if (
            audio_format.sample_rate <= 0
            or audio_format.channels <= 0
            or audio_format.sample_width <= 0
        ):
            raise ValueError("local engine returned an invalid audio format")
        if output_size % audio_format.frame_width:
            raise ValueError("local engine returned a partial PCM frame")
        pcm = await asyncio.to_thread(returned_path.read_bytes)
        return AudioChunk(pcm=pcm, format=audio_format)

    async def _write_message(self, message: Mapping[str, object]) -> None:
        process = self._process
        if process is None or process.stdin is None or process.returncode is not None:
            raise RuntimeError("local engine process is not running")
        line = json.dumps(
            message,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8") + b"\n"
        if len(line) > self.spec.max_message_bytes:
            raise ValueError("local engine request exceeds the protocol message limit")
        process.stdin.write(line)
        await process.stdin.drain()

    async def _read_response(self, request_id: str, *, timeout: float) -> dict[str, object]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise asyncio.TimeoutError
            message = await self._read_message(timeout=remaining)
            if message.get("type") == "event":
                self._events.append(message)
                continue
            if message.get("id") != request_id:
                raise RuntimeError("local engine response id did not match its request")
            if message.get("type") not in {"result", "error"}:
                raise RuntimeError("local engine returned an unknown response type")
            return message

    async def _read_until_type(self, message_type: str, *, timeout: float) -> dict[str, object]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise asyncio.TimeoutError
            message = await self._read_message(timeout=remaining)
            if message.get("type") == "event":
                self._events.append(message)
                continue
            if message.get("type") != message_type:
                raise RuntimeError(f"expected local engine message type {message_type!r}")
            return message

    async def _read_message(self, *, timeout: float) -> dict[str, object]:
        process = self._process
        if process is None or process.stdout is None:
            raise RuntimeError("local engine process is not running")
        line = await asyncio.wait_for(process.stdout.readline(), timeout=timeout)
        if not line:
            return_code = await process.wait()
            detail = self._stderr_detail()
            raise RuntimeError(f"local engine exited with code {return_code}: {detail}")
        try:
            value = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RuntimeError("local engine emitted invalid JSON") from error
        if not isinstance(value, dict):
            raise RuntimeError("local engine message must be a JSON object")
        return value

    async def _read_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        while line := await process.stderr.readline():
            value = line.decode("utf-8", errors="replace").strip()
            if value:
                self._stderr_tail.append(value[:2_000])

    async def _stop_process(self, *, graceful: bool) -> None:
        process = self._process
        stderr_task = self._stderr_task
        self._process = None
        self._stderr_task = None
        if process is not None and process.returncode is None:
            if graceful and process.stdin is not None:
                try:
                    line = json.dumps(
                        {"type": "shutdown"},
                        separators=(",", ":"),
                    ).encode("utf-8") + b"\n"
                    process.stdin.write(line)
                    await process.stdin.drain()
                    await asyncio.wait_for(
                        process.wait(),
                        timeout=self.spec.shutdown_timeout_seconds,
                    )
                except (BrokenPipeError, ConnectionResetError, asyncio.TimeoutError):
                    pass
            if process.returncode is None:
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(
                        process.wait(),
                        timeout=self.spec.shutdown_timeout_seconds,
                    )
                except asyncio.TimeoutError:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                    await process.wait()
        if stderr_task is not None:
            if not stderr_task.done():
                stderr_task.cancel()
            await asyncio.gather(stderr_task, return_exceptions=True)

    def _provider_error(
        self,
        message: str,
        *,
        retryable: bool,
        phase: str,
        response: Mapping[str, object] | None = None,
        exception: BaseException | None = None,
    ) -> ProviderError:
        exception_detail = None
        if exception is not None:
            exception_detail = {
                "type": exception.__class__.__name__,
                "message": str(exception),
            }
        diagnostic = ProviderDiagnostic(
            category="local_engine",
            phase=phase,
            provider=self.descriptor.id,
            method="subprocess",
            endpoint=" ".join(self.spec.command[:3]),
            response=(
                cast(Mapping[str, JsonValue], dict(response))
                if response is not None
                else None
            ),
            exception=exception_detail,
            metadata={
                "transport": self.descriptor.transport.value,
                "stderr_tail": self._stderr_detail(),
                "job_id": self.context.job_id,
            },
        )
        return ProviderError(
            message,
            retryable=retryable,
            diagnostic=diagnostic,
            origin="engine",
        )

    def _stderr_detail(self) -> str:
        return "\n".join(self._stderr_tail) or "no stderr output"
