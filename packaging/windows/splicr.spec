from __future__ import annotations

import csv
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


ROOT = Path(SPECPATH).resolve().parents[1]
SOURCE = ROOT / "src"
VENDOR = ROOT / "packaging" / "windows" / "vendor" / "ffmpeg" / "bin"

datas = [
    (str(SOURCE / "splicr" / "static"), "splicr/static"),
    (str(SOURCE / "splicr" / "engine_worker.py"), "splicr"),
    (str(ROOT / "packaging" / "windows" / "THIRD_PARTY_NOTICES.md"), "."),
    (str(ROOT / "packaging" / "windows" / "vendor" / "ffmpeg" / "BUILD_INFO.txt"), "."),
]
packaged_license_manifest = ROOT / "packaging" / "windows" / "ffmpeg-packaged-license-files.tsv"
packaged_license_names = []
with packaged_license_manifest.open(encoding="utf-8", newline="") as manifest_stream:
    for record in csv.DictReader(manifest_stream, delimiter="\t"):
        packaged_license_names.append(Path(record["package_path"]).name)
for metadata in ("LICENSE.txt", "SOURCE_INFO.txt", *packaged_license_names):
    candidate = ROOT / "packaging" / "windows" / "vendor" / "ffmpeg" / metadata
    if candidate.is_file():
        datas.append((str(candidate), "ffmpeg"))
    elif metadata in packaged_license_names:
        raise SystemExit(f"Missing required dependency license metadata: {candidate}")
binaries = []
for executable in ("ffmpeg.exe", "ffprobe.exe"):
    candidate = VENDOR / executable
    if not candidate.is_file():
        raise SystemExit(f"Missing required bundled tool: {candidate}")
    binaries.append((str(candidate), "ffmpeg"))
for library in sorted(VENDOR.glob("*.dll")):
    binaries.append((str(library), "ffmpeg"))

hiddenimports = sorted(
    set(
        collect_submodules("keyring.backends")
        + collect_submodules("uvicorn")
        + [
            "splicr.api",
            "splicr.bootstrap",
            "splicr.providers.audio8",
            "splicr.providers.deepgram",
            "splicr.providers.gemini",
            "splicr.providers.inworld",
            "splicr.providers.kokoro",
            "splicr.providers.qwen3",
        ]
    )
)

analysis = Analysis(
    [str(ROOT / "packaging" / "windows" / "desktop_entry.py")],
    pathex=[str(SOURCE)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "ruff"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="SPLICR Studio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
collection = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="SPLICR Studio",
)
