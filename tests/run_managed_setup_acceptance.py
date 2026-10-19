"""Explicit hosted-runner setup acceptance; downloads packages, not model weights.

Run only on a disposable Windows GitHub runner, never automatically on a user's PC.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from splicr.config import Settings
from splicr.studio.components import ComponentManager
from splicr.studio.engine_setup import EngineSetupManager, RECIPES


async def check(root: Path, engines: list[str]) -> None:
    manager = EngineSetupManager(ComponentManager(Settings(data_dir=root)))
    try:
        for engine in engines:
            job = manager.start(engine, "cpu", True)
            print(f"Installing {engine} in a runner-private environment", flush=True)
            await manager.task
            result = manager.get(job["id"])
            print(json.dumps(result, indent=2), flush=True)
            if result["status"] != "completed":
                raise RuntimeError(f"{engine} setup failed: {result['error']}")
            configured = manager.components.apply(Settings(data_dir=root))
            assert Path(result["python_path"]).is_file()
            if engine == "edge":
                assert configured.edge_python == Path(result["python_path"])
            print(f"MANAGED SETUP PASSED: {engine}", flush=True)
    finally:
        await manager.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--engines", nargs="+", choices=list(RECIPES), default=list(RECIPES))
    args = parser.parse_args()
    asyncio.run(check(args.root.resolve(), args.engines))
