from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from splicr import engine_worker
import pytest


@pytest.mark.parametrize("mode", ["engine", "tool"])
def test_nested_installer_stdout_cannot_corrupt_worker_protocol(tmp_path: Path, mode: str) -> None:
    """Python redirect_stdout alone does not redirect a subprocess's inherited OS stdout."""
    wrapper = tmp_path / "worker.py"
    wrapper.write_text(
        f"""
import importlib.util
import os
import subprocess
import sys
spec = importlib.util.spec_from_file_location('worker_under_test', {str(Path(engine_worker.__file__).resolve())!r})
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)
class Runtime:
    def synthesize(self, text, options, output_path):
        subprocess.run([sys.executable, '-c', "print('Installing language assets', flush=True)"], check=True)
        os.write(1, b'Native diagnostic output\\n')
        output_path.write_bytes(b'\\x00\\x00' * 100)
worker._runtime = lambda engine: Runtime()
def tool(payload):
    subprocess.run([sys.executable, '-c', "print('Installing language assets', flush=True)"], check=True)
    os.write(1, b'Native diagnostic output\\n')
    return {{'voices': []}}
worker._tool_edge_voices = tool
sys.argv = ['worker', '--engine', 'kokoro'] if {mode!r} == 'engine' else ['worker', '--tool', 'edge_voices']
worker.main()
""",
        encoding="utf-8",
    )
    commands = [
        {
            "type": "synthesize",
            "id": "first",
            "text": "A test sentence.",
            "options": {},
            "output_path": str(tmp_path / "chunk.pcm"),
        },
        {"type": "shutdown"},
    ]
    result = subprocess.run(
        [sys.executable, str(wrapper)],
        input=("\n".join(json.dumps(command) for command in commands) + "\n")
        if mode == "engine"
        else "{}",
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    messages = [json.loads(line) for line in result.stdout.splitlines()]
    if mode == "engine":
        assert [message["type"] for message in messages] == ["ready", "result"]
    else:
        assert messages == [{"voices": []}]
    assert "Installing language assets" in result.stderr
    assert "Native diagnostic output" in result.stderr
