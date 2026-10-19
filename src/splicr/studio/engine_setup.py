"""Explicit, per-user engine provisioning; never modifies external environments."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from ..diagnostics import sanitize_diagnostic
from .components import ComponentManager

UV_VERSION = "0.12.5"
UV_URL = (
    f"https://github.com/astral-sh/uv/releases/download/{UV_VERSION}/uv-x86_64-pc-windows-msvc.zip"
)
UV_SHA256 = "4c4d49d8738847d9b71ba319e49a5688c93eac0fe6204b1df24e98528dddf39a"
UV_BYTES = 20_329_591
PYTHON_VERSION = "3.12.14"
ACTIVE = {"queued", "running", "cancelling"}
RECIPES = {
    "edge": {
        "packages": ["edge-tts==7.2.8"],
        "imports": ["edge_tts"],
        "space_gb": 1,
        "note": "Small setup. Narration still uses Microsoft's online service.",
    },
    "kokoro": {
        "packages": ["kokoro==0.9.4", "soundfile", "phonemizer-fork", "espeakng-loader==0.2.4"],
        "imports": ["kokoro", "soundfile", "espeakng_loader"],
        "space_gb": 5,
        "note": "Includes a private eSpeak library; no system installer. Model weights download on first use.",
    },
    "qwen3": {
        "packages": ["qwen-tts==0.1.1"],
        "imports": ["qwen_tts"],
        "space_gb": 15,
        "note": "Large models download on first use. NVIDIA acceleration is recommended; CPU can be very slow.",
    },
    "audio8": {
        "packages": ["transformers==4.57.6", "soundfile", "accelerate"],
        "imports": ["transformers", "soundfile", "accelerate", "torchaudio"],
        "space_gb": 10,
        "note": "First render downloads model weights and executes Audio8 model code from Hugging Face. CPU can be very slow.",
    },
    "whisper": {
        "packages": ["faster-whisper==1.2.1", "av==19.0.0"],
        "imports": ["faster_whisper", "av"],
        "space_gb": 5,
        "note": "Transcription models download on first use. This installer uses CPU-compatible dependencies.",
    },
}


class SetupError(ValueError):
    pass


class EngineSetupManager:
    """One durable install at a time. Restart recovery is explicit, not an automatic download."""

    def __init__(self, components: ComponentManager) -> None:
        self.components = components
        self.root = components.path.parent / "managed-engines"
        self.path = self.root / "setup-jobs.json"
        self.jobs: dict[str, dict[str, Any]] = {}
        self.task: asyncio.Task | None = None
        self.process: asyncio.subprocess.Process | None = None
        self._cancel = False
        self._gpu_checked = False
        self._gpu: str | None = None
        try:
            stored = json.loads(self.path.read_text("utf-8"))
            for job in stored.get("jobs", []):
                if (
                    re.fullmatch(r"[0-9a-f]{32}", str(job.get("id", "")))
                    and job.get("engine_id") in RECIPES
                ):
                    if job.get("status") in ACTIVE:
                        job.update(
                            status="interrupted",
                            stage="Interrupted by application restart",
                            error="Setup stopped before completion. Retry to reuse downloaded packages.",
                        )
                    self.jobs[job["id"]] = job
        except (OSError, ValueError, TypeError, AttributeError):
            self.jobs = {}

    @staticmethod
    def supported() -> bool:
        return sys.platform == "win32" and platform.machine().lower() in {"amd64", "x86_64"}

    def catalog(self) -> dict[str, Any]:
        self.root.mkdir(parents=True, exist_ok=True)
        gpu = None
        executable = shutil.which("nvidia-smi") if not self._gpu_checked else None
        if executable:
            try:
                result = subprocess.run(
                    [executable, "--query-gpu=name", "--format=csv,noheader"],
                    capture_output=True,
                    text=True,
                    timeout=3,
                    check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                if result.returncode == 0:
                    gpu = result.stdout.strip()[:200] or None
            except (OSError, subprocess.SubprocessError):
                pass
        if not self._gpu_checked:
            self._gpu_checked, self._gpu = True, gpu
        gpu = self._gpu
        return {
            "supported": self.supported(),
            "root": str(self.root),
            "free_bytes": shutil.disk_usage(self.root).free,
            "nvidia_gpu": gpu,
            "recipes": [{"id": key, **value} for key, value in RECIPES.items()],
            "jobs": list(self.jobs.values())[-50:],
            "notice": "Windows x64 managed setup. No administrator rights or system Python needed. "
            "Downloads Python and third-party packages; selected models download later on first use. "
            "Space figures are conservative planning estimates, not exact download sizes.",
        }

    def active_for(self, engine_id: str) -> bool:
        return any(
            j["engine_id"] == engine_id and j["status"] in ACTIVE for j in self.jobs.values()
        )

    def start(self, engine_id: str, accelerator: str, consent: bool) -> dict[str, Any]:
        self._preflight(engine_id, accelerator, consent)
        job_id = uuid.uuid4().hex
        job = {
            "id": job_id,
            "engine_id": engine_id,
            "accelerator": accelerator,
            "status": "queued",
            "stage": "Waiting to start",
            "logs": [],
            "error": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "download_bytes": 0,
            "download_total": None,
            "python_path": None,
        }
        self.jobs[job_id] = job
        self._launch(job)
        return dict(job)

    def retry(self, job_id: str, consent: bool) -> dict[str, Any]:
        job = self.get(job_id)
        if job["status"] not in {"failed", "cancelled", "interrupted"}:
            raise SetupError("Only failed, cancelled, or interrupted setup can be retried")
        self._preflight(job["engine_id"], job["accelerator"], consent)
        job.update(
            status="queued",
            error=None,
            stage="Retrying setup",
            download_bytes=0,
            download_total=None,
        )
        self._launch(job)
        return dict(job)

    def get(self, job_id: str) -> dict[str, Any]:
        if job_id not in self.jobs:
            raise SetupError("Setup job not found")
        return self.jobs[job_id]

    async def cancel(self, job_id: str) -> dict[str, Any]:
        job = self.get(job_id)
        if job["status"] in ACTIVE:
            self._cancel = True
            self._update(job, status="cancelling", stage="Stopping setup…")
            await self._kill_process()
        return dict(job)

    async def close(self) -> None:
        if self.task and not self.task.done():
            self._cancel = True
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)

    def _preflight(self, engine_id: str, accelerator: str, consent: bool) -> None:
        if not consent:
            raise SetupError("Confirm the download and third-party code notice before installing")
        if not self.supported():
            raise SetupError(
                "Managed setup currently supports Windows x64; connect an existing environment here"
            )
        if engine_id not in RECIPES or accelerator not in {"cpu", "cuda"}:
            raise SetupError("Unknown engine or acceleration mode")
        if accelerator == "cuda" and engine_id not in {"kokoro", "qwen3", "audio8"}:
            raise SetupError("This setup recipe supports CPU mode only")
        if self.task and not self.task.done():
            raise SetupError("Another setup is active. Wait or cancel it first")
        if self.components._environment_value(engine_id):
            raise SetupError(
                "An environment variable controls this engine; remove it before managed setup"
            )
        self.root.mkdir(parents=True, exist_ok=True)
        required = (
            int(RECIPES[engine_id]["space_gb"]) + (8 if accelerator == "cuda" else 0)
        ) * 1024**3
        if shutil.disk_usage(self.root).free < required:
            raise SetupError(
                f"Allow at least {required // 1024**3} GiB free for this setup and model cache"
            )
        if accelerator == "cuda" and not self.catalog()["nvidia_gpu"]:
            raise SetupError(
                "No working NVIDIA driver detected. Choose CPU or install the GPU driver separately"
            )

    def _launch(self, job: dict[str, Any]) -> None:
        self._cancel = False
        self._persist()
        self.task = asyncio.create_task(self._install(job))

    def _persist(self) -> None:
        ComponentManager._save_json(self.path, {"version": 1, "jobs": list(self.jobs.values())})

    def _update(self, job: dict[str, Any], **values: Any) -> None:
        job.update(values, updated_at=datetime.now(timezone.utc).isoformat())
        self._persist()

    def _log(self, job: dict[str, Any], text: str) -> None:
        safe = str(sanitize_diagnostic(text))
        safe = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", safe)
        job["logs"] = (job["logs"] + [safe[-1000:]])[-150:]
        self._persist()

    def _check_cancel(self) -> None:
        if self._cancel:
            raise asyncio.CancelledError

    async def _bootstrap(self, job: dict[str, Any]) -> Path:
        tools = self.root / "tools"
        tools.mkdir(parents=True, exist_ok=True)
        archive = tools / f"uv-{UV_VERSION}.zip"
        archive_valid = False
        if archive.is_file():
            with archive.open("rb") as source:
                archive_valid = hashlib.file_digest(source, "sha256").hexdigest() == UV_SHA256
        if not archive_valid:
            partial = archive.with_suffix(".download")
            self._update(job, stage="Downloading verified setup tool", download_total=UV_BYTES)
            try:
                async with httpx.AsyncClient(
                    follow_redirects=True, trust_env=False, timeout=30
                ) as client:
                    async with client.stream("GET", UV_URL) as response:
                        response.raise_for_status()
                        received = 0
                        digest = hashlib.sha256()
                        with partial.open("wb") as output:
                            async for block in response.aiter_bytes(1024 * 1024):
                                self._check_cancel()
                                received += len(block)
                                if received > UV_BYTES:
                                    raise SetupError(
                                        "Setup-tool download exceeds the reviewed size"
                                    )
                                digest.update(block)
                                output.write(block)
                                self._update(job, download_bytes=received)
                        if received != UV_BYTES or digest.hexdigest() != UV_SHA256:
                            raise SetupError(
                                "Setup-tool checksum mismatch; downloaded executable was not run"
                            )
                        os.replace(partial, archive)
            finally:
                partial.unlink(missing_ok=True)
        self._check_cancel()
        # Never extract arbitrary ZIP paths; only the reviewed executable is copied.
        with zipfile.ZipFile(archive) as zipped:
            entries = [item for item in zipped.infolist() if item.filename == "uv.exe"]
            if len(entries) != 1 or entries[0].file_size > 100 * 1024**2:
                raise SetupError("Unexpected setup-tool archive layout")
            executable = tools / "uv.exe"
            content = zipped.read(entries[0])
            if not executable.is_file() or executable.read_bytes() != content:
                temporary = executable.with_suffix(".tmp")
                temporary.write_bytes(content)
                os.replace(temporary, executable)
        return executable

    def _environment(self) -> dict[str, str]:
        # Do not inherit package indexes, injected Python paths, proxies, or API secrets.
        allowed = {
            "SYSTEMROOT",
            "WINDIR",
            "COMSPEC",
            "TEMP",
            "TMP",
            "PATH",
            "PATHEXT",
            "USERPROFILE",
            "LOCALAPPDATA",
            "APPDATA",
            "PROGRAMFILES",
            "PROGRAMFILES(X86)",
        }
        environment = {key: value for key, value in os.environ.items() if key.upper() in allowed}
        environment.update(
            UV_PYTHON_INSTALL_DIR=str(self.root / "python"),
            UV_PYTHON_BIN_DIR=str(self.root / "python-bin"),
            UV_CACHE_DIR=str(self.root / "cache"),
            HF_HOME=str(self.root / "models"),
            PYTHONUTF8="1",
            PYTHONUNBUFFERED="1",
            UV_NO_CONFIG="1",
        )
        return environment

    async def _run(self, job: dict[str, Any], command: list[str], stage: str) -> None:
        self._check_cancel()
        self._update(job, stage=stage, download_bytes=0, download_total=None)
        self.process = await asyncio.create_subprocess_exec(
            *command,
            cwd=self.root,
            env=self._environment(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            async with asyncio.timeout(3600):
                assert self.process.stdout is not None
                while block := await self.process.stdout.read(2048):
                    self._check_cancel()
                    self._log(job, block.decode("utf-8", errors="replace"))
                returncode = await self.process.wait()
                self._check_cancel()
                if returncode:
                    raise SetupError(
                        f"{stage} failed (exit {returncode}). See the setup log; retry reuses cached downloads"
                    )
        finally:
            await self._kill_process()
            self.process = None

    async def _kill_process(self) -> None:
        process = self.process
        if process and process.returncode is None:
            if sys.platform == "win32":
                killer = await asyncio.create_subprocess_exec(
                    "taskkill",
                    "/PID",
                    str(process.pid),
                    "/T",
                    "/F",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                await killer.wait()
            else:
                process.kill()
            await process.wait()

    async def _install(self, job: dict[str, Any]) -> None:
        engine = job["engine_id"]
        recipe = RECIPES[engine]
        environment = self.root / "environments" / job["id"]
        python = environment / "Scripts" / "python.exe"
        try:
            self._check_cancel()
            self._update(job, status="running", stage="Preparing isolated setup")
            uv = str(await self._bootstrap(job))
            await self._run(
                job,
                [
                    uv,
                    "--no-config",
                    "--no-progress",
                    "venv",
                    "--no-project",
                    "--python",
                    PYTHON_VERSION,
                    "--managed-python",
                    "--allow-existing",
                    "--seed",
                    str(environment),
                ],
                "Installing private Python and environment",
            )
            pip = [
                uv,
                "--no-config",
                "--no-progress",
                "pip",
                "install",
                "--python",
                str(python),
                "--link-mode",
                "copy",
            ]
            for native in (
                "torch",
                "torchaudio",
                "numpy",
                "scipy",
                "spacy",
                "tokenizers",
                "soundfile",
                "ctranslate2",
                "av",
                "espeakng-loader",
            ):
                pip.extend(["--only-binary", native])
            torch = []
            if engine in {"kokoro", "qwen3", "audio8"}:
                torch = ["torch==2.11.0"]
                if engine in {"qwen3", "audio8"}:
                    torch.append("torchaudio==2.11.0")
                channel = "cu128" if job["accelerator"] == "cuda" else "cpu"
                await self._run(
                    job,
                    [
                        *pip,
                        "--default-index",
                        f"https://download.pytorch.org/whl/{channel}",
                        "--no-deps",
                        *torch,
                    ],
                    "Installing PyTorch runtime",
                )
            await self._run(
                job,
                [
                    *pip,
                    "--default-index",
                    "https://pypi.org/simple",
                    "--exclude-newer",
                    "2026-10-20",
                    *recipe["packages"],
                    *torch,
                ],
                "Installing engine packages",
            )
            imports = "import pip; " + "; ".join(f"import {name}" for name in recipe["imports"])
            if job["accelerator"] == "cuda":
                imports += "; import torch; assert torch.cuda.is_available(), 'NVIDIA runtime unavailable; use CPU setup'"
            if engine == "kokoro":
                imports += (
                    "; import espeakng_loader; from phonemizer.backend.espeak.wrapper import EspeakWrapper"
                    "; EspeakWrapper.set_library(espeakng_loader.get_library_path())"
                    "; EspeakWrapper.set_data_path(espeakng_loader.get_data_path())"
                    "; from phonemizer import phonemize; assert phonemize('Hello', language='en-us')"
                )
            await self._run(job, [str(python), "-I", "-c", imports], "Verifying installed engine")
            await self._run(
                job,
                [*pip[:4], "freeze", "--python", str(python)],
                "Recording installed package versions",
            )
            self._check_cancel()
            # Write model-cache location only for this managed generation. External engines are untouched.
            ComponentManager._save_json(
                environment / "splicr-managed.json",
                {
                    "engine_id": engine,
                    "accelerator": job["accelerator"],
                    "model_cache": str(self.root / "models"),
                    "recipe_version": 1,
                },
            )
            self.components.save_engine(engine, str(python))
            self._update(
                job,
                status="completed",
                stage="Installed and verified — restart SPLICR to activate",
                python_path=str(python),
                error=None,
            )
        except asyncio.CancelledError:
            await self._kill_process()
            self._update(
                job,
                status="cancelled",
                stage="Setup stopped — cached downloads retained",
                error="Retry to continue. Existing configured engines were not replaced.",
            )
        except Exception as error:
            self._log(job, str(error))
            self._update(
                job,
                status="failed",
                stage="Setup needs attention",
                error=str(sanitize_diagnostic(str(error))),
            )
