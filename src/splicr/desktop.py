from __future__ import annotations

import json
import os
import shutil
import socket
import sys
import threading
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import TextIO


def desktop_data_dir() -> Path:
    """Return the upgrade-safe per-user data root used by the desktop launcher."""

    configured = os.getenv("SPLICR_DATA_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    if sys.platform == "win32":
        local = os.getenv("LOCALAPPDATA", "").strip()
        root = Path(local) if local else Path.home() / "AppData" / "Local"
        return (root / "SPLICR Studio" / "data").resolve()
    xdg = os.getenv("XDG_DATA_HOME", "").strip()
    root = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return (root / "splicr-studio").resolve()


def prepare_desktop_environment() -> Path:
    """Set stable data and bundled-tool paths before importing the FastAPI app."""

    data_dir = desktop_data_dir()
    os.environ.setdefault("SPLICR_DATA_DIR", str(data_dir))
    data_dir.mkdir(parents=True, exist_ok=True)
    executable_root = Path(sys.executable).resolve().parent
    candidates = (
        executable_root / "ffmpeg",
        executable_root / "_internal" / "ffmpeg",
    )
    for candidate in candidates:
        if (candidate / "ffmpeg.exe").is_file() and (candidate / "ffprobe.exe").is_file():
            path_entries = os.environ.get("PATH", "").split(os.pathsep)
            if str(candidate) not in path_entries:
                os.environ["PATH"] = f"{candidate}{os.pathsep}{os.environ.get('PATH', '')}"
            break
    return data_dir


def is_splicr_running(host: str, port: int, *, timeout: float = 0.35) -> bool:
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/health", timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if payload != {"status": "ok"}:
            return False
        with urllib.request.urlopen(f"http://{host}:{port}/studio/", timeout=timeout) as response:
            head = response.read(4_096).decode("utf-8", errors="replace")
        return "<title>SPLICR Studio</title>" in head
    except (OSError, ValueError, urllib.error.URLError):
        return False


def available_port(host: str, preferred: int, *, attempts: int = 20) -> int:
    if preferred < 1 or preferred > 65_535:
        raise ValueError("preferred port must be between 1 and 65535")
    final_port = min(65_535, preferred + attempts - 1)
    for port in range(preferred, final_port + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
            try:
                candidate.bind((host, port))
            except OSError:
                continue
            return port
    raise RuntimeError(
        f"SPLICR could not find an available local port from {preferred} through {final_port}."
    )


def find_running_splicr(host: str, preferred: int, *, attempts: int = 20) -> int | None:
    final_port = min(65_535, preferred + attempts - 1)
    return next(
        (port for port in range(preferred, final_port + 1) if is_splicr_running(host, port)),
        None,
    )


def run_desktop(
    *,
    host: str = "127.0.0.1",
    preferred_port: int = 8765,
    open_browser: bool = True,
) -> int:
    """Run SPLICR behind a small native lifecycle window and open the Studio browser UI."""

    data_dir = prepare_desktop_environment()
    running_port = find_running_splicr(host, preferred_port)
    if running_port is not None:
        if open_browser:
            webbrowser.open(f"http://{host}:{running_port}/studio/")
        return 0
    port = available_port(host, preferred_port)
    log_stream = _desktop_log(data_dir)
    if getattr(sys, "frozen", False):
        sys.stdout = log_stream
        sys.stderr = log_stream

    import tkinter as tk
    from tkinter import messagebox

    import uvicorn

    from .api import create_app

    url = f"http://{host}:{port}/studio/"
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(),
            host=host,
            port=port,
            log_level="info",
            access_log=False,
        )
    )
    server_thread = threading.Thread(target=server.run, name="splicr-server", daemon=True)
    server_thread.start()

    root = tk.Tk()
    root.title("SPLICR Studio")
    root.geometry("440x235")
    root.minsize(400, 220)
    root.configure(background="#11130f")
    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)

    frame = tk.Frame(root, background="#11130f", padx=28, pady=24)
    frame.grid(sticky="nsew")
    frame.columnconfigure(0, weight=1)
    tk.Label(
        frame,
        text="SPLICR Studio",
        background="#11130f",
        foreground="#e9f6bd",
        font=("Segoe UI Semibold", 18),
    ).grid(row=0, column=0, sticky="w")
    status = tk.StringVar(value="Starting the local workspace…")
    tk.Label(
        frame,
        textvariable=status,
        background="#11130f",
        foreground="#b8bcae",
        font=("Segoe UI", 10),
        justify="left",
        wraplength=370,
    ).grid(row=1, column=0, sticky="w", pady=(10, 18))
    buttons = tk.Frame(frame, background="#11130f")
    buttons.grid(row=2, column=0, sticky="ew")
    open_button = tk.Button(
        buttons,
        text="Open Studio",
        state="disabled",
        command=lambda: webbrowser.open(url),
        background="#d8ff72",
        foreground="#14170f",
        activebackground="#e5ffa2",
        relief="flat",
        padx=18,
        pady=8,
        font=("Segoe UI Semibold", 9),
    )
    open_button.pack(side="left")
    tk.Button(
        buttons,
        text="Open data folder",
        command=lambda: webbrowser.open(data_dir.as_uri()),
        background="#24271f",
        foreground="#e1e4da",
        activebackground="#30342a",
        activeforeground="#ffffff",
        relief="flat",
        padx=14,
        pady=8,
        font=("Segoe UI", 9),
    ).pack(side="left", padx=(9, 0))

    closing = False

    def ready_check(attempt: int = 0) -> None:
        if closing:
            return
        if is_splicr_running(host, port, timeout=0.5):
            status.set(f"Running locally at {url}\nKeep this window open while using SPLICR.")
            open_button.configure(state="normal")
            if open_browser:
                webbrowser.open(url)
            return
        if not server_thread.is_alive():
            status.set("SPLICR stopped before its local service became ready.")
            messagebox.showerror(
                "SPLICR could not start",
                f"See {data_dir / 'logs' / 'desktop.log'} for details.",
            )
            return
        root.after(200 if attempt < 10 else 500, lambda: ready_check(attempt + 1))

    def close() -> None:
        nonlocal closing
        if closing:
            return
        closing = True
        status.set("Stopping safely…")
        open_button.configure(state="disabled")
        server.should_exit = True

        def wait_for_stop() -> None:
            if server_thread.is_alive():
                root.after(100, wait_for_stop)
                return
            log_stream.close()
            root.destroy()

        wait_for_stop()

    root.protocol("WM_DELETE_WINDOW", close)
    root.after(50, ready_check)
    root.mainloop()
    return 0


def _desktop_log(data_dir: Path) -> TextIO:
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return (log_dir / "desktop.log").open("a", encoding="utf-8", buffering=1)


def package_smoke_test() -> int:
    """Verify the frozen bundle can initialize its app, worker, UI, and media tools."""

    prepare_desktop_environment()
    from .api import create_app

    application = create_app()
    route_paths = {route.path for route in application.routes}
    required_routes = {"/health", "/studio/", "/v1/studio/components"}
    missing = required_routes - route_paths
    if missing:
        raise RuntimeError(f"packaged app is missing routes: {sorted(missing)}")
    package_root = Path(__file__).resolve().parent
    required_files = (
        package_root / "engine_worker.py",
        package_root / "static" / "studio" / "index.html",
    )
    missing_files = [str(path) for path in required_files if not path.is_file()]
    if missing_files:
        raise RuntimeError(f"packaged app is missing files: {missing_files}")
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise RuntimeError("packaged FFmpeg and FFprobe were not detected")
    # Advanced audiograms import Pillow/NumPy lazily. Exercise the actual drawing path so a
    # frozen build cannot pass while silently omitting those runtime-only modules.
    import numpy as np
    from PIL import Image

    from .studio.audiogram import (
        AudiogramBackgroundMode,
        AudiogramGeometry,
        AudiogramOutputFormat,
        AudiogramSpec,
    )
    from .studio.audiogram_frames import draw_frame, frame_context

    spec = AudiogramSpec(
        width=320,
        height=180,
        visualizer_height=90,
        fps=12,
        geometry=AudiogramGeometry.POLAR,
        show_line=True,
        bar_count=12,
        rotation="8 * sin(t)",
        background_mode=AudiogramBackgroundMode.TRANSPARENT,
        output_format=AudiogramOutputFormat.PNG_SEQUENCE,
    )
    values = np.linspace(0.1, 1.0, spec.bar_count, dtype=np.float32)
    context = frame_context(1, 3, spec.fps, 0.25, values)
    frame, _overlay = draw_frame(
        values,
        spec,
        context=context,
        background=Image.new("RGBA", (spec.width, spec.height), (0, 0, 0, 0)),
    )
    if frame.size != (spec.width, spec.height) or frame.getbbox() is None:
        raise RuntimeError("packaged advanced audiogram renderer did not produce a frame")
    return 0


def main() -> None:
    arguments = sys.argv[1:]
    if arguments == ["--package-smoke-test"]:
        raise SystemExit(package_smoke_test())
    if arguments not in ([], ["--no-browser"]):
        raise SystemExit(
            "usage: SPLICR Studio.exe [--no-browser | --package-smoke-test]"
        )
    raise SystemExit(run_desktop(open_browser=arguments != ["--no-browser"]))


if __name__ == "__main__":
    main()
