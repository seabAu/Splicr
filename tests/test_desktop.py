from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path

import pytest

from splicr.config import Settings
from splicr.desktop import (
    _packaged_media_tools,
    available_port,
    desktop_data_dir,
    find_running_splicr,
    main,
    package_smoke_test,
    prepare_desktop_environment,
    run_desktop,
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

    assert Settings.from_env().data_dir == (tmp_path / "Local" / "SPLICR Studio" / "data").resolve()


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
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert _packaged_media_tools() == (
        (tools / "ffmpeg.exe").resolve(),
        (tools / "ffprobe.exe").resolve(),
    )


def test_frozen_media_tools_cannot_fall_back_to_global_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install = tmp_path / "install"
    install.mkdir()
    global_tools = tmp_path / "global-tools"
    global_tools.mkdir()
    monkeypatch.setattr(sys, "executable", str(install / "SPLICR Studio.exe"))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        "splicr.desktop.shutil.which",
        lambda name: str(global_tools / f"{name}.exe"),
    )

    with pytest.raises(RuntimeError, match="outside the application bundle"):
        _packaged_media_tools()


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


def test_desktop_acceptance_requires_distinct_ready_and_close_files(tmp_path: Path) -> None:
    signal_file = tmp_path / "desktop.signal"

    with pytest.raises(ValueError, match="ready and close files must differ"):
        run_desktop(
            open_browser=False,
            acceptance_ready_file=signal_file,
            acceptance_close_file=signal_file,
        )


def test_desktop_acceptance_reports_a_preexisting_instance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ready_file = tmp_path / "ready.json"
    close_file = tmp_path / "close.signal"
    monkeypatch.setenv("SPLICR_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr("splicr.desktop.find_running_splicr", lambda *_args: 8768)

    assert (
        run_desktop(
            open_browser=False,
            acceptance_ready_file=ready_file,
            acceptance_close_file=close_file,
        )
        == 0
    )
    evidence = json.loads(ready_file.read_text(encoding="utf-8"))
    assert evidence == {
        "existing_instance": True,
        "host": "127.0.0.1",
        "pid": os.getpid(),
        "port": 8768,
        "schema_version": 1,
    }


def test_package_smoke_test_initializes_routes_assets_worker_and_media_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SPLICR_DATA_DIR", str(tmp_path / "data"))

    assert package_smoke_test() == 0


@pytest.mark.parametrize(
    ("arguments", "open_browser"),
    [([], True), (["--no-browser"], False)],
)
def test_frozen_entrypoint_controls_browser_launch(
    arguments: list[str],
    open_browser: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[bool] = []
    monkeypatch.setattr(sys, "argv", ["SPLICR Studio.exe", *arguments])
    monkeypatch.setattr(
        "splicr.desktop.run_desktop",
        lambda *, open_browser: calls.append(open_browser) or 23,
    )

    with pytest.raises(SystemExit) as raised:
        main()

    assert raised.value.code == 23
    assert calls == [open_browser]


def test_frozen_entrypoint_routes_package_acceptance_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = tmp_path / "state.json"
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "SPLICR Studio.exe",
            "--package-acceptance-state",
            "verify",
            str(manifest),
        ],
    )
    monkeypatch.setattr(
        "splicr.desktop.package_acceptance_state",
        lambda action, path: calls.append((action, path)) or 29,
    )

    with pytest.raises(SystemExit) as raised:
        main()

    assert raised.value.code == 29
    assert calls == [("verify", str(manifest))]


def test_frozen_entrypoint_routes_package_lifecycle_test(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ready_file = tmp_path / "ready.json"
    close_file = tmp_path / "close.signal"
    calls: list[tuple[bool, Path, Path]] = []
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "SPLICR Studio.exe",
            "--package-lifecycle-test",
            str(ready_file),
            str(close_file),
        ],
    )
    monkeypatch.setattr(
        "splicr.desktop.run_desktop",
        lambda *, open_browser, acceptance_ready_file, acceptance_close_file: calls.append(
            (open_browser, acceptance_ready_file, acceptance_close_file)
        )
        or 31,
    )

    with pytest.raises(SystemExit) as raised:
        main()

    assert raised.value.code == 31
    assert calls == [(False, ready_file, close_file)]


def test_frozen_entrypoint_rejects_unknown_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["SPLICR Studio.exe", "--unknown"])

    with pytest.raises(SystemExit, match="usage: SPLICR Studio.exe"):
        main()
