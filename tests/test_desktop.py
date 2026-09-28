from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

import pytest

from splicr.config import Settings
from splicr.desktop import (
    available_port,
    desktop_data_dir,
    find_running_splicr,
    package_smoke_test,
    prepare_desktop_environment,
)


def test_desktop_data_dir_is_stable_and_respects_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured = tmp_path / "kept-between-upgrades"
    monkeypatch.setenv("SPLICR_DATA_DIR", str(configured))

    assert desktop_data_dir() == configured.resolve()
    assert Settings.from_env().data_dir == configured.resolve()


def test_frozen_settings_default_outside_install_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SPLICR_DATA_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "win32")

    assert Settings.from_env().data_dir == (
        tmp_path / "Local" / "SPLICR Studio" / "data"
    ).resolve()


def test_packaged_ffmpeg_directory_is_added_without_overwriting_user_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install = tmp_path / "install"
    tools = install / "_internal" / "ffmpeg"
    tools.mkdir(parents=True)
    (tools / "ffmpeg.exe").write_bytes(b"binary")
    (tools / "ffprobe.exe").write_bytes(b"binary")
    data = tmp_path / "user-data"
    marker = data / "keep.txt"
    data.mkdir()
    marker.write_text("preserve", encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(install / "SPLICR Studio.exe"))
    monkeypatch.setenv("SPLICR_DATA_DIR", str(data))
    monkeypatch.setenv("PATH", "existing-path")

    assert prepare_desktop_environment() == data.resolve()
    assert marker.read_text(encoding="utf-8") == "preserve"
    assert str(tools) in os.environ["PATH"].split(os.pathsep)


def test_available_port_skips_an_occupied_port() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        first = occupied.getsockname()[1]

        assert available_port("127.0.0.1", first, attempts=2) == first + 1


def test_available_port_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="between 1 and 65535"):
        available_port("127.0.0.1", 0)


def test_existing_instance_scan_checks_fallback_ports(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "splicr.desktop.is_splicr_running",
        lambda host, port: host == "127.0.0.1" and port == 8767,
    )

    assert find_running_splicr("127.0.0.1", 8765, attempts=5) == 8767


def test_package_smoke_test_initializes_routes_assets_worker_and_media_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SPLICR_DATA_DIR", str(tmp_path / "data"))

    assert package_smoke_test() == 0
