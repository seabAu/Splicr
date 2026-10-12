"""Provision test-only media tools; never use this payload in a desktop package."""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

from fetch_ffmpeg_release import download_verified, sha256_file


ARCHIVE_NAME = "ffmpeg-n9.0.2-17-g2a571b6068-win64-lgpl-shared-9.0.zip"
ARCHIVE_SHA256 = "7157177b8a6cb2174c1650ba8c71b363f2c78cba5330f88c4c02cf5b2b880646"
ARCHIVE_URL = (
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/"
    f"autobuild-2026-09-30-13-08/{ARCHIVE_NAME}"
)


def fetch_browser_media(destination: Path) -> Path:
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    archive_path = destination / ARCHIVE_NAME
    if not archive_path.is_file() or sha256_file(archive_path) != ARCHIVE_SHA256:
        download_verified(
            url=ARCHIVE_URL,
            destination=archive_path,
            expected_sha256=ARCHIVE_SHA256,
            label=ARCHIVE_NAME,
        )
    # Recheck even when a downloader is replaced or a cached file is supplied.
    if sha256_file(archive_path) != ARCHIVE_SHA256:
        raise ValueError("Browser-only FFmpeg archive failed checksum verification")
    root_name = Path(ARCHIVE_NAME).stem
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            target = (destination / member.filename).resolve()
            if not target.is_relative_to(destination / root_name):
                raise ValueError("Browser-only FFmpeg archive contains an unsafe path")
        archive.extractall(destination)
    bin_path = destination / root_name / "bin"
    for tool in ("ffmpeg.exe", "ffprobe.exe"):
        if not (bin_path / tool).is_file():
            raise FileNotFoundError(f"Browser-only FFmpeg archive is missing {tool}")
    return bin_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", required=True, type=Path)
    print(fetch_browser_media(parser.parse_args().destination))
