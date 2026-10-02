from __future__ import annotations

import csv
import gzip
import hashlib
import importlib.util
import io
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).with_name("fetch_ffmpeg_release.py")
TEST_ROOT = MODULE_PATH.parents[2] / ".test-runs" / "fetch-crate-tests"
TEST_ROOT.mkdir(parents=True, exist_ok=True)
SPEC = importlib.util.spec_from_file_location("fetch_ffmpeg_release", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Could not load {MODULE_PATH}")
FETCHER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = FETCHER
SPEC.loader.exec_module(FETCHER)


class _Response:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


def _crate_bytes(member_name: str, member_bytes: bytes, *, symlink: bool = False) -> bytes:
    raw = io.BytesIO()
    with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w") as archive:
            member = tarfile.TarInfo(member_name)
            member.mtime = 0
            if symlink:
                member.type = tarfile.SYMTYPE
                member.linkname = "elsewhere"
                archive.addfile(member)
            else:
                member.size = len(member_bytes)
                archive.addfile(member, io.BytesIO(member_bytes))
    return raw.getvalue()


class CargoCrateTransportTests(unittest.TestCase):
    def test_extracts_hash_verified_member_and_reuses_archive(self) -> None:
        member_name = "demo-1.0.0/LICENSE"
        member_bytes = b"demo license\n"
        payload = _crate_bytes(member_name, member_bytes)
        archive_sha256 = hashlib.sha256(payload).hexdigest()
        member_sha256 = hashlib.sha256(member_bytes).hexdigest()
        encoding = f"crate+tar.gz:{archive_sha256}:{member_name}"
        calls = 0

        def open_once(*_args: object, **_kwargs: object) -> _Response:
            nonlocal calls
            calls += 1
            return _Response(payload)

        with tempfile.TemporaryDirectory(dir=TEST_ROOT) as directory, patch.object(
            FETCHER.urllib.request, "urlopen", side_effect=open_once
        ):
            root = Path(directory)
            cache: dict[tuple[str, str], bytes] = {}
            for name in ("first.txt", "second.txt"):
                destination = root / name
                FETCHER.download_verified(
                    url="https://example.invalid/demo.crate",
                    destination=destination,
                    expected_sha256=member_sha256,
                    label=name,
                    content_encoding=encoding,
                    maximum_attempts=1,
                    payload_cache=cache,
                )
                self.assertEqual(destination.read_bytes(), member_bytes)
            self.assertEqual(calls, 1)

    def test_rejects_archive_hash_mismatch(self) -> None:
        payload = _crate_bytes("demo-1.0.0/LICENSE", b"demo license\n")
        encoding = f"crate+tar.gz:{'0' * 64}:demo-1.0.0/LICENSE"
        with tempfile.TemporaryDirectory(dir=TEST_ROOT) as directory, patch.object(
            FETCHER.urllib.request, "urlopen", return_value=_Response(payload)
        ):
            with self.assertRaisesRegex(ValueError, "Cargo crate hash mismatch"):
                FETCHER.download_verified(
                    url="https://example.invalid/demo.crate",
                    destination=Path(directory) / "LICENSE",
                    expected_sha256=hashlib.sha256(b"demo license\n").hexdigest(),
                    label="demo",
                    content_encoding=encoding,
                    maximum_attempts=1,
                )

    def test_rejects_non_regular_archive_member(self) -> None:
        member_name = "demo-1.0.0/LICENSE"
        payload = _crate_bytes(member_name, b"", symlink=True)
        encoding = (
            f"crate+tar.gz:{hashlib.sha256(payload).hexdigest()}:{member_name}"
        )
        with tempfile.TemporaryDirectory(dir=TEST_ROOT) as directory, patch.object(
            FETCHER.urllib.request, "urlopen", return_value=_Response(payload)
        ):
            with self.assertRaisesRegex(ValueError, "exactly one regular file"):
                FETCHER.download_verified(
                    url="https://example.invalid/demo.crate",
                    destination=Path(directory) / "LICENSE",
                    expected_sha256=hashlib.sha256(b"").hexdigest(),
                    label="demo",
                    content_encoding=encoding,
                    maximum_attempts=1,
                )

    def test_manifest_rejects_traversal_member(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_ROOT) as directory:
            manifest = Path(directory) / "manifest.tsv"
            with manifest.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
                writer.writerow(
                    ["package_path", "source_url", "revision", "sha256", "content_encoding"]
                )
                writer.writerow(
                    [
                        "ffmpeg/DEMO-LICENSE.txt",
                        "https://example.invalid/demo.crate",
                        "1" * 40,
                        "2" * 64,
                        f"crate+tar.gz:{'3' * 64}:demo-1.0.0/../LICENSE",
                    ]
                )
            with self.assertRaisesRegex(ValueError, "Invalid packaged FFmpeg license"):
                FETCHER.load_manifest(manifest)


if __name__ == "__main__":
    unittest.main()
