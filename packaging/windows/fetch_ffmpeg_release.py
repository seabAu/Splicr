from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import re
import shutil
import sys
import tarfile
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path


ARCHIVE_NAME = "ffmpeg-n9.0.2-3-ga5923073bf-win64-lgpl-shared-9.0.zip"
RELEASE_TAG = "autobuild-2026-09-24-14-14"
ARCHIVE_SHA256 = "735bae484ba2c3342bfb34df477b9c6b0f43f9819f4d2fde011be293ee1b6517"
ARCHIVE_URL = (
    f"https://github.com/BtbN/FFmpeg-Builds/releases/download/{RELEASE_TAG}/{ARCHIVE_NAME}"
)
PACKAGE_PATH_RE = re.compile(r"^ffmpeg/[A-Za-z0-9._-]+$")
REVISION_RE = re.compile(
    r"^(?:[0-9a-f]{40}|[1-9][0-9]*|v[0-9]+(?:\.[0-9]+){1,3}(?:[._-][0-9A-Za-z]+)*|"
    r"openssl-[0-9]+(?:\.[0-9]+){2,3})$"
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CRATE_ENCODING_RE = re.compile(
    r"^crate\+tar\.gz:([0-9a-f]{64}):([A-Za-z0-9][A-Za-z0-9._+\-/]*)$"
)


@dataclass(frozen=True)
class PackagedLicense:
    package_path: str
    source_url: str
    revision: str
    sha256: str
    content_encoding: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_content_encoding(content_encoding: str) -> bool:
    if content_encoding in {"", "base64"}:
        return True
    match = CRATE_ENCODING_RE.fullmatch(content_encoding)
    if match is None:
        return False
    member_path = match.group(2)
    return (
        "\\" not in member_path
        and not member_path.startswith("/")
        and all(part not in {"", ".", ".."} for part in member_path.split("/"))
    )


def _decode_content(payload: bytes, content_encoding: str, label: str) -> bytes:
    if content_encoding == "":
        return payload
    if content_encoding == "base64":
        return base64.b64decode(payload, validate=True)

    match = CRATE_ENCODING_RE.fullmatch(content_encoding)
    if match is None or not _validate_content_encoding(content_encoding):
        raise ValueError(f"Unsupported content encoding for {label}: {content_encoding}")
    expected_archive_sha256, member_path = match.groups()
    actual_archive_sha256 = hashlib.sha256(payload).hexdigest()
    if actual_archive_sha256 != expected_archive_sha256:
        raise ValueError(
            f"Pinned Cargo crate hash mismatch for {label}: expected "
            f"{expected_archive_sha256}, received {actual_archive_sha256}"
        )

    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        members = [member for member in archive.getmembers() if member.name == member_path]
        if len(members) != 1 or not members[0].isfile():
            raise ValueError(
                f"Pinned Cargo crate must contain exactly one regular file at {member_path}: "
                f"{label}"
            )
        stream = archive.extractfile(members[0])
        if stream is None:
            raise ValueError(f"Could not read pinned Cargo crate member {member_path}: {label}")
        return stream.read()


def load_manifest(path: Path) -> list[PackagedLicense]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    records: list[PackagedLicense] = []
    for row in rows:
        record = PackagedLicense(
            package_path=row.get("package_path", ""),
            source_url=row.get("source_url", ""),
            revision=row.get("revision", ""),
            sha256=row.get("sha256", ""),
            content_encoding=row.get("content_encoding") or "",
        )
        if (
            PACKAGE_PATH_RE.fullmatch(record.package_path) is None
            or not record.source_url.startswith("https://")
            or REVISION_RE.fullmatch(record.revision) is None
            or SHA256_RE.fullmatch(record.sha256) is None
            or not _validate_content_encoding(record.content_encoding)
        ):
            raise ValueError(
                f"Invalid packaged FFmpeg license manifest record: {record.package_path}"
            )
        records.append(record)
    if not records:
        raise ValueError("The packaged FFmpeg license manifest is empty.")
    return records


def download_verified(
    *,
    url: str,
    destination: Path,
    expected_sha256: str,
    label: str,
    content_encoding: str = "",
    maximum_attempts: int = 5,
    payload_cache: dict[tuple[str, str], bytes] | None = None,
) -> None:
    temporary = destination.with_name(f"{destination.name}.part")
    crate_match = CRATE_ENCODING_RE.fullmatch(content_encoding)
    transport_sha256 = crate_match.group(1) if crate_match is not None else expected_sha256
    cache_key = (url, transport_sha256)
    for attempt in range(1, maximum_attempts + 1):
        try:
            payload = payload_cache.get(cache_key) if payload_cache is not None else None
            if payload is None:
                request = urllib.request.Request(
                    url,
                    headers={"User-Agent": "SPLICR-release-packager/1"},
                )
                with urllib.request.urlopen(request, timeout=45) as response:
                    payload = response.read()
                if hashlib.sha256(payload).hexdigest() == transport_sha256 and payload_cache is not None:
                    payload_cache[cache_key] = payload
            temporary.write_bytes(_decode_content(payload, content_encoding, label))
            actual_sha256 = sha256_file(temporary)
            if actual_sha256 != expected_sha256:
                raise ValueError(
                    f"Pinned download hash mismatch for {label}: expected "
                    f"{expected_sha256}, received {actual_sha256}"
                )
            temporary.replace(destination)
            return
        except Exception as error:
            temporary.unlink(missing_ok=True)
            if attempt == maximum_attempts:
                raise
            delay_seconds = min(16, 2**attempt)
            print(
                f"Download attempt {attempt}/{maximum_attempts} failed for {label}: "
                f"{error}. Retrying in {delay_seconds} seconds.",
                file=sys.stderr,
            )
            time.sleep(delay_seconds)


def fetch_release(destination: Path, manifest_path: Path) -> Path:
    records = load_manifest(manifest_path)
    destination.mkdir(parents=True, exist_ok=True)
    archive_path = destination / ARCHIVE_NAME
    extracted_path = destination / Path(ARCHIVE_NAME).stem

    if not archive_path.exists() or sha256_file(archive_path) != ARCHIVE_SHA256:
        download_verified(
            url=ARCHIVE_URL,
            destination=archive_path,
            expected_sha256=ARCHIVE_SHA256,
            label=ARCHIVE_NAME,
        )
    if sha256_file(archive_path) != ARCHIVE_SHA256:
        raise ValueError(
            f"Pinned FFmpeg archive hash mismatch: expected {ARCHIVE_SHA256}, "
            f"received {sha256_file(archive_path)}"
        )

    if extracted_path.exists():
        shutil.rmtree(extracted_path)
    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(destination)

    bin_path = extracted_path / "bin"
    for tool in ("ffmpeg.exe", "ffprobe.exe"):
        if not (bin_path / tool).is_file():
            raise FileNotFoundError(f"Pinned FFmpeg archive is missing {tool}")

    payload_cache: dict[tuple[str, str], bytes] = {}
    for record in records:
        download_verified(
            url=record.source_url,
            destination=extracted_path / Path(record.package_path).name,
            expected_sha256=record.sha256,
            label=record.package_path,
            content_encoding=record.content_encoding,
            payload_cache=payload_cache,
        )

    source_lines = [
        "Provider: BtbN/FFmpeg-Builds",
        f"Release tag: {RELEASE_TAG}",
        f"Asset: {ARCHIVE_NAME}",
        f"Asset URL: {ARCHIVE_URL}",
        f"SHA-256: {ARCHIVE_SHA256}",
        "Upstream asset variant: Windows x64 LGPL shared",
        "Effective bundled media license: GPL-covered because static Chromaprint includes FFTW3",
        "",
        "Additional packaged dependency licenses:",
    ]
    for record in records:
        encoding_note = (
            f" | transport encoding {record.content_encoding}" if record.content_encoding else ""
        )
        source_lines.append(
            f"{record.package_path} | revision {record.revision} | SHA-256 "
            f"{record.sha256}{encoding_note} | {record.source_url}"
        )
    (extracted_path / "SOURCE_INFO.txt").write_text(
        "\n".join(source_lines) + "\n",
        encoding="utf-8",
    )
    return bin_path


def parse_args() -> argparse.Namespace:
    script_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--destination",
        type=Path,
        default=script_dir / "vendor" / "ffmpeg-lgpl",
    )
    parser.add_argument(
        "--packaged-license-manifest",
        type=Path,
        default=script_dir / "ffmpeg-packaged-license-files.tsv",
    )
    parser.add_argument("--validate-manifest-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    records = load_manifest(args.packaged_license_manifest)
    if args.validate_manifest_only:
        print(f"Validated {len(records)} packaged FFmpeg license manifest records.")
        return 0
    print(fetch_release(args.destination, args.packaged_license_manifest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
