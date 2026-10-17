from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path

import pytest


@pytest.fixture
def fetcher(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "packaging" / "windows"))
    module = importlib.import_module("fetch_ffmpeg_release")
    monkeypatch.setattr(module, "ARCHIVE_NAME", "reviewed-fixture.zip")
    monkeypatch.setattr(module, "ARCHIVE_SHA256", hashlib.sha256(b"reviewed").hexdigest())

    def no_network(**kwargs):
        pytest.fail("An explicit/cached archive must not trigger a network fallback")

    monkeypatch.setattr(module, "download_verified", no_network)
    return module


def test_supplied_exact_archive_is_copied_and_verified(fetcher, tmp_path):
    source = tmp_path / "source.zip"
    source.write_bytes(b"reviewed")
    result = fetcher.acquire_archive(tmp_path / "cache", source)
    assert result.read_bytes() == b"reviewed"
    assert source.read_bytes() == b"reviewed"
    assert not result.with_name(result.name + ".part").exists()


@pytest.mark.parametrize("payload", [None, b"wrong build"])
def test_bad_explicit_input_never_falls_back_to_network(fetcher, tmp_path, payload):
    source = tmp_path / "source.zip"
    if payload is not None:
        source.write_bytes(payload)
    with pytest.raises((ValueError, FileNotFoundError)):
        fetcher.acquire_archive(tmp_path / "cache", source)
    assert not (tmp_path / "cache").exists()


def test_exact_input_repairs_corrupt_cache(fetcher, tmp_path):
    source = tmp_path / "source.zip"
    source.write_bytes(b"reviewed")
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / fetcher.ARCHIVE_NAME).write_bytes(b"corrupt")
    assert fetcher.acquire_archive(cache, source).read_bytes() == b"reviewed"


def test_exact_cache_can_be_its_own_explicit_input(fetcher, tmp_path):
    source = tmp_path / fetcher.ARCHIVE_NAME
    source.write_bytes(b"reviewed")
    assert fetcher.acquire_archive(tmp_path, source) == source
    assert fetcher.acquire_archive(tmp_path) == source


def test_copy_is_reverified_before_atomic_publication(fetcher, monkeypatch, tmp_path):
    source = tmp_path / "source.zip"
    source.write_bytes(b"reviewed")
    monkeypatch.setattr(fetcher.shutil, "copyfile", lambda src, dst: dst.write_bytes(b"changed"))
    cache = tmp_path / "cache"
    with pytest.raises(ValueError, match="Copied FFmpeg archive"):
        fetcher.acquire_archive(cache, source)
    assert not (cache / fetcher.ARCHIVE_NAME).exists()
    assert not list(cache.glob("*.part"))


def test_absent_input_uses_the_unchanged_pinned_download(fetcher, monkeypatch, tmp_path):
    calls = []

    def download(**kwargs):
        calls.append(kwargs)
        kwargs["destination"].write_bytes(b"reviewed")

    monkeypatch.setattr(fetcher, "download_verified", download)
    assert fetcher.acquire_archive(tmp_path).read_bytes() == b"reviewed"
    assert calls[0]["url"] == fetcher.ARCHIVE_URL
    assert calls[0]["expected_sha256"] == fetcher.ARCHIVE_SHA256


def test_private_ci_environment_path_is_parsed_as_a_path(fetcher, monkeypatch):
    monkeypatch.setenv("SPLICR_FFMPEG_ARCHIVE_FILE", "ci-inputs/reviewed.zip")
    monkeypatch.setattr(fetcher.sys, "argv", ["fetch_ffmpeg_release.py"])
    assert fetcher.parse_args().archive_file == Path("ci-inputs/reviewed.zip")


def test_explicit_cli_input_overrides_environment(fetcher, monkeypatch):
    monkeypatch.setenv("SPLICR_FFMPEG_ARCHIVE_FILE", "ci-inputs/unused.zip")
    monkeypatch.setattr(
        fetcher.sys, "argv", ["fetch_ffmpeg_release.py", "--archive-file", "actual.zip"]
    )
    assert fetcher.parse_args().archive_file == Path("actual.zip")


def test_hash_pinned_patch_has_checkout_stable_lf_bytes():
    root = Path(__file__).parents[1]
    assert "*.patch text eol=lf" in (root / ".gitattributes").read_text(encoding="utf-8")
    packaging = root / "packaging" / "windows"
    manifest = json.loads((packaging / "ffmpeg-offline-build-inputs.json").read_text())
    patch = next(record for record in manifest["inputs"] if record["kind"] == "patch")
    payload = (packaging / "ffmpeg-build-patches" / patch["filename"]).read_bytes()
    assert b"\r\n" not in payload
    assert hashlib.sha256(payload).hexdigest() == patch["sha256"]
