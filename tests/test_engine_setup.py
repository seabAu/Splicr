from __future__ import annotations

import asyncio
import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from splicr import engine_worker
from splicr.api import create_app
from splicr.config import Settings
from splicr.providers import ProviderRegistry
from splicr.service import SynthesisService
from splicr.studio import engine_setup as module
from splicr.studio.components import ComponentManager
from splicr.studio.engine_setup import EngineSetupManager, SetupError

from .fakes import RecordingProvider


@pytest.fixture
def manager(tmp_path, monkeypatch):
    for engine in ("EDGE", "KOKORO", "QWEN3", "AUDIO8", "WHISPER"):
        monkeypatch.delenv(f"SPLICR_{engine}_PYTHON", raising=False)
    monkeypatch.setattr(EngineSetupManager, "supported", staticmethod(lambda: True))
    monkeypatch.setattr(
        module.shutil, "disk_usage", lambda path: SimpleNamespace(free=100 * 1024**3)
    )
    instance = EngineSetupManager(ComponentManager(Settings(data_dir=tmp_path)))
    instance._gpu_checked = True
    return instance


def test_preflight_requires_consent_supported_mode_and_disk(manager, monkeypatch):
    with pytest.raises(SetupError, match="Confirm"):
        manager.start("edge", "cpu", False)
    with pytest.raises(SetupError, match="Unknown"):
        manager.start("../../escape", "cpu", True)
    with pytest.raises(SetupError, match="CPU mode only"):
        manager.start("edge", "cuda", True)
    with pytest.raises(SetupError, match="NVIDIA"):
        manager.start("qwen3", "cuda", True)
    monkeypatch.setattr(module.shutil, "disk_usage", lambda path: SimpleNamespace(free=1))
    with pytest.raises(SetupError, match="GiB free"):
        manager.start("edge", "cpu", True)
    assert not manager.jobs


def test_environment_override_is_not_replaced(manager, monkeypatch):
    monkeypatch.setenv("SPLICR_EDGE_PYTHON", sys.executable)
    with pytest.raises(SetupError, match="environment variable"):
        manager.start("edge", "cpu", True)


@pytest.mark.parametrize("engine", ["edge", "kokoro", "qwen3", "audio8", "whisper"])
def test_setup_uses_private_paths_verifies_then_connects(manager, monkeypatch, engine):
    commands = []
    saved = []

    async def bootstrap(job):
        return manager.root / "tools" / "uv.exe"

    async def run(job, command, stage):
        commands.append((command, stage))
        assert manager.root == manager.path.parent

    monkeypatch.setattr(manager, "_bootstrap", bootstrap)
    monkeypatch.setattr(manager, "_run", run)
    monkeypatch.setattr(manager.components, "save_engine", lambda *args: saved.append(args))

    async def scenario():
        job = manager.start(engine, "cpu", True)
        with pytest.raises(SetupError, match="Another setup"):
            manager.start("edge", "cpu", True)
        await manager.task
        return manager.get(job["id"])

    job = asyncio.run(scenario())
    assert job["status"] == "completed"
    assert saved == [(engine, job["python_path"])]
    assert Path(job["python_path"]).is_relative_to(manager.root / "environments")
    assert commands[0][0][commands[0][0].index("--python") + 1] == "3.12.14"
    assert "--managed-python" in commands[0][0]
    assert not any("--system" in command or "--clear" in command for command, _ in commands)
    assert "Verifying" in commands[-2][1]
    assert commands[-1][0][4] == "freeze"
    marker = json.loads((Path(job["python_path"]).parents[1] / "splicr-managed.json").read_text())
    assert marker["model_cache"] == str(manager.root / "models")
    if engine in {"kokoro", "qwen3", "audio8"}:
        torch = next(
            command for command, _ in commands if "https://download.pytorch.org/whl/cpu" in command
        )
        assert "torch==2.11.0" in torch


def test_failed_setup_is_durable_and_retry_reuses_same_environment(manager, monkeypatch):
    saved = []
    monkeypatch.setattr(manager.components, "save_engine", lambda *args: saved.append(args))

    async def fail(job):
        raise SetupError("network unavailable")

    monkeypatch.setattr(manager, "_bootstrap", fail)

    async def scenario():
        job = manager.start("edge", "cpu", True)
        await manager.task
        assert manager.get(job["id"])["status"] == "failed"
        assert not saved
        before = set(manager.jobs)
        retried = manager.retry(job["id"], True)
        await manager.task
        assert retried["id"] == job["id"]
        assert set(manager.jobs) == before
        return job["id"]

    job_id = asyncio.run(scenario())
    recovered = EngineSetupManager(manager.components)
    assert recovered.get(job_id)["status"] == "failed"
    assert "network unavailable" in recovered.get(job_id)["error"]


def test_cancel_and_shutdown_never_connect_partial_environment(manager, monkeypatch):
    saved = []
    monkeypatch.setattr(manager.components, "save_engine", lambda *args: saved.append(args))

    async def bootstrap(job):
        await asyncio.sleep(0)
        manager._check_cancel()
        await asyncio.sleep(30)

    monkeypatch.setattr(manager, "_bootstrap", bootstrap)

    async def scenario():
        job = manager.start("edge", "cpu", True)
        await manager.cancel(job["id"])
        await manager.task
        assert manager.get(job["id"])["status"] == "cancelled"
        manager.retry(job["id"], True)
        await asyncio.sleep(0)
        await manager.close()
        assert manager.get(job["id"])["status"] == "cancelled"

    asyncio.run(scenario())
    assert not saved


def test_restart_recovers_incomplete_setup_without_downloading(manager):
    job_id = "a" * 32
    ComponentManager._save_json(
        manager.path, {"jobs": [{"id": job_id, "engine_id": "edge", "status": "running"}]}
    )
    recovered = EngineSetupManager(manager.components)
    assert recovered.get(job_id)["status"] == "interrupted"
    assert recovered.task is None


def test_environment_does_not_inherit_secrets_or_package_injection(manager, monkeypatch):
    for key in (
        "GEMINI_API_KEY",
        "PYTHONPATH",
        "PYTHONHOME",
        "UV_INDEX_URL",
        "PIP_INDEX_URL",
        "HTTPS_PROXY",
    ):
        monkeypatch.setenv(key, "sensitive-or-untrusted")
    environment = manager._environment()
    assert all("sensitive-or-untrusted" != value for value in environment.values())
    assert environment["UV_PYTHON_INSTALL_DIR"] == str(manager.root / "python")
    assert environment["UV_CACHE_DIR"] == str(manager.root / "cache")


def _archive(content=b"reviewed executable"):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as zipped:
        zipped.writestr("uv.exe", content)
        zipped.writestr("../../escape.exe", b"not extracted")
    return output.getvalue()


def test_bootstrap_download_is_bounded_pinned_and_not_arbitrary_zip_extraction(
    manager, monkeypatch
):
    archive = _archive()
    monkeypatch.setattr(module, "UV_SHA256", hashlib.sha256(archive).hexdigest())
    monkeypatch.setattr(module, "UV_BYTES", len(archive))
    real_client = httpx.AsyncClient
    calls = []

    def response(request):
        calls.append(str(request.url))
        return httpx.Response(200, content=archive)

    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(response), **kwargs),
    )
    job = {"logs": [], "id": "b" * 32}
    executable = asyncio.run(manager._bootstrap(job))
    assert executable.read_bytes() == b"reviewed executable"
    executable.write_bytes(b"tampered")
    assert asyncio.run(manager._bootstrap(job)).read_bytes() == b"reviewed executable"
    assert len(calls) == 1
    assert not (manager.root / "escape.exe").exists()


def test_bad_bootstrap_hash_never_publishes_executable(manager, monkeypatch):
    archive = _archive()
    monkeypatch.setattr(module, "UV_BYTES", len(archive))
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, content=archive)),
            **kwargs,
        ),
    )
    with pytest.raises(SetupError, match="checksum"):
        asyncio.run(manager._bootstrap({"logs": []}))
    assert not (manager.root / "tools" / "uv.exe").exists()
    assert not (manager.root / "tools" / f"uv-{module.UV_VERSION}.download").exists()


def test_setup_logs_are_bounded_and_redacted(manager):
    job = {"logs": []}
    for _ in range(160):
        manager._log(job, "Authorization: Bearer top-secret-value")
    assert len(job["logs"]) == 150
    assert "top-secret-value" not in " ".join(job["logs"])


def test_managed_worker_cache_and_espeak_are_scoped_to_marker(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "prefix", str(tmp_path))
    monkeypatch.delenv("HF_HOME", raising=False)
    engine_worker._configure_managed_environment()
    assert "HF_HOME" not in module.os.environ
    marker = tmp_path / "splicr-managed.json"
    marker.write_text(json.dumps({"engine_id": "edge", "model_cache": str(tmp_path / "cache")}))
    engine_worker._configure_managed_environment()
    assert module.os.environ["HF_HOME"] == str(tmp_path / "cache")


def test_setup_api_requires_loopback_same_origin_and_explicit_consent(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path, pacing_seconds=0)
    service = SynthesisService(settings=settings, providers=ProviderRegistry([RecordingProvider()]))
    app = create_app(settings=settings, service=service)
    setup = app.state.engine_setup_manager
    monkeypatch.setattr(setup, "supported", lambda: True)
    with TestClient(app, base_url="http://localhost") as client:
        assert client.get("/v1/studio/components/setup").status_code == 200
        assert client.post("/v1/studio/components/engines/edge/install", json={}).status_code == 409
        assert (
            client.post(
                "/v1/studio/components/engines/edge/install",
                json={"consent": True},
                headers={"Origin": "https://evil.example"},
            ).status_code
            == 403
        )
        assert (
            client.get(
                "/v1/studio/components/setup", headers={"Host": "rebind.example"}
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/v1/studio/components/engines/edge/install",
                json={"consent": True, "command": "arbitrary"},
            ).status_code
            == 422
        )
