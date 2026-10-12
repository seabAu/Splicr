from __future__ import annotations

import hashlib
import importlib
import io
import zipfile
from pathlib import Path

import pytest


@pytest.fixture
def fetcher(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "packaging" / "windows"))
    return importlib.import_module("fetch_browser_media")


def _fixture_archive(fetcher, monkeypatch, members):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        for name in members:
            archive.writestr(name, b"test-only tool")
    payload = data.getvalue()
    monkeypatch.setattr(fetcher, "ARCHIVE_SHA256", hashlib.sha256(payload).hexdigest())
    calls = []

    def download(**kwargs):
        calls.append(kwargs)
        kwargs["destination"].write_bytes(payload)

    monkeypatch.setattr(fetcher, "download_verified", download)
    return payload, calls


def test_browser_media_verifies_and_reuses_exact_archive(fetcher, monkeypatch, tmp_path):
    root = Path(fetcher.ARCHIVE_NAME).stem
    payload, calls = _fixture_archive(
        fetcher, monkeypatch, [f"{root}/bin/ffmpeg.exe", f"{root}/bin/ffprobe.exe"]
    )
    bin_path = fetcher.fetch_browser_media(tmp_path)
    assert (bin_path / "ffmpeg.exe").is_file()
    assert fetcher.fetch_browser_media(tmp_path) == bin_path
    assert len(calls) == 1
    assert calls[0]["expected_sha256"] == hashlib.sha256(payload).hexdigest()
    assert calls[0]["url"] == fetcher.ARCHIVE_URL


def test_browser_media_rejects_checksum_mismatch(fetcher, monkeypatch, tmp_path):
    monkeypatch.setattr(
        fetcher, "download_verified", lambda **kwargs: kwargs["destination"].write_bytes(b"bad")
    )
    with pytest.raises(ValueError, match="checksum"):
        fetcher.fetch_browser_media(tmp_path)
    assert not (tmp_path / Path(fetcher.ARCHIVE_NAME).stem).exists()


def test_browser_media_rejects_traversal_before_extraction(fetcher, monkeypatch, tmp_path):
    _fixture_archive(fetcher, monkeypatch, ["../escaped.exe"])
    with pytest.raises(ValueError, match="unsafe path"):
        fetcher.fetch_browser_media(tmp_path)
    assert not (tmp_path.parent / "escaped.exe").exists()


def test_browser_media_requires_both_tools(fetcher, monkeypatch, tmp_path):
    root = Path(fetcher.ARCHIVE_NAME).stem
    _fixture_archive(fetcher, monkeypatch, [f"{root}/bin/ffmpeg.exe"])
    with pytest.raises(FileNotFoundError, match="ffprobe.exe"):
        fetcher.fetch_browser_media(tmp_path)
