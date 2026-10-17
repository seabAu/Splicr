from pathlib import Path
import re
import shutil
import subprocess

import pytest


WORKFLOW = (
    Path(__file__).parents[1] / ".github" / "workflows" / "package-windows.yml"
).read_text(encoding="utf-8")
RETENTION_GUARD = "${{ github.event_name == 'workflow_dispatch' && inputs.retain_packages }}"


def _media_failure_guard():
    match = re.search(
        r"if \(\$LASTEXITCODE -ne 0 -or -not \$ffmpegBin\) \{.*?\n\s+\}",
        WORKFLOW,
        flags=re.DOTALL,
    )
    assert match is not None
    return match.group()


def test_package_retention_requires_explicit_boolean_opt_in():
    inputs = WORKFLOW.split("    inputs:\n", 1)[1].split("  push:\n", 1)[0]
    retention = inputs.split("      retain_packages:\n", 1)[1]
    assert "        type: boolean\n" in retention
    assert "        default: false\n" in retention
    assert "        required: true\n" in retention


def test_every_package_upload_is_guarded_and_tags_cannot_publish_implicitly():
    uploads = [
        step for step in WORKFLOW.split("      - name:") if "actions/upload-artifact@" in step
    ]
    assert uploads
    for step in uploads:
        assert f"        if: {RETENTION_GUARD}\n" in step
        assert step.index("        if:") < step.index("        uses:")


def test_failed_shipping_media_download_cannot_fall_back_to_path():
    fetch = "$ffmpegBin = python .\\packaging\\windows\\fetch_ffmpeg_release.py"
    build = ".\\packaging\\windows\\build.ps1"
    between = WORKFLOW.split(fetch, 1)[1].split(build, 1)[0]
    assert "if ($LASTEXITCODE -ne 0 -or -not $ffmpegBin)" in between
    assert 'throw "Reviewed shipping FFmpeg acquisition failed; refusing PATH fallback."' in between


@pytest.mark.parametrize(
    ("exit_code", "ffmpeg_bin", "should_proceed"),
    [(1, "$null", False), (0, "$null", False), (0, "'C:/reviewed-tools'", True)],
)
def test_shipping_media_guard_executes_fail_closed(exit_code, ffmpeg_bin, should_proceed):
    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("PowerShell 7 is required to execute the Windows workflow guard")
    guard = _media_failure_guard()
    script = (
        "$ErrorActionPreference = 'Stop'; "
        f"$LASTEXITCODE = {exit_code}; $ffmpegBin = {ffmpeg_bin};\n"
        f"{guard}\nWrite-Output 'BUILD_ALLOWED'"
    )
    result = subprocess.run(
        [pwsh, "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    assert (result.returncode == 0) is should_proceed
    assert ("BUILD_ALLOWED" in result.stdout) is should_proceed
    if not should_proceed:
        assert "refusing PATH fallback" in result.stderr


def test_media_is_on_path_before_python_regressions_and_build_uses_same_input():
    assert WORKFLOW.index("- name: Acquire reviewed shipping media") < WORKFLOW.index(
        "- name: Run tests and build installer"
    )
    assert "$ffmpegBin = (Resolve-Path -LiteralPath $ffmpegBin).Path" in WORKFLOW
    assert "$ffmpegBin | Out-File -FilePath $env:GITHUB_PATH" in WORKFLOW
    assert "REVIEWED_FFMPEG_BIN: ${{ steps.media.outputs.ffmpeg_bin }}" in WORKFLOW
    assert "-FfmpegBin $env:REVIEWED_FFMPEG_BIN" in WORKFLOW


@pytest.mark.parametrize(
    ("command", "failure"),
    [
        ("uv sync --frozen --extra dev", "Locked dependency installation failed"),
        ("uv run ruff check .", "Ruff failed"),
        ("uv run pytest -o addopts= -q", "Python regression suite failed"),
        (
            "python .\\packaging\\windows\\test_ffmpeg_cargo_source_closure.py",
            "Cargo source-closure regression failed",
        ),
    ],
)
def test_native_regression_failures_stop_before_packaging(command, failure):
    following = WORKFLOW.split(command + "\n", 1)[1].lstrip()
    assert following.startswith(f'if ($LASTEXITCODE -ne 0) {{ throw "{failure}" }}')
