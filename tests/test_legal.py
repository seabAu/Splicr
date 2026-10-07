from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from splicr.api import create_app
from splicr.config import Settings
from splicr.providers import ProviderRegistry
from splicr.service import SynthesisService
from splicr.studio.legal import LegalAssets, LegalMetadataError

from .fakes import RecordingProvider


def _legal_root(
    tmp_path: Path,
    *,
    with_source: bool = True,
    with_application_license: bool = True,
) -> Path:
    root = tmp_path / "legal"
    ffmpeg = root / "ffmpeg"
    ffmpeg.mkdir(parents=True)
    if with_application_license:
        (root / "LICENSE.txt").write_text("Apache-2.0 terms\n", encoding="utf-8")
    (root / "THIRD_PARTY_NOTICES.md").write_text("# Notices\n", encoding="utf-8")
    (root / "BUILD_INFO.txt").write_text("ffmpeg version test\n", encoding="utf-8")
    (ffmpeg / "LICENSE.txt").write_text("license terms\n", encoding="utf-8")
    (ffmpeg / "SOURCE_INFO.txt").write_text("binary source record\n", encoding="utf-8")
    metadata = {
        "schema_version": 1,
        "application_version": "1.2.3",
        "application_license": "Apache-2.0",
        "ffmpeg_effective_license": "reviewed test status",
        "corresponding_source_url": (
            "https://downloads.example.test/SPLICR-FFmpeg-source.zip" if with_source else None
        ),
        "corresponding_source_sha256": "a" * 64 if with_source else None,
    }
    (root / "LEGAL_INFO.json").write_text(json.dumps(metadata), encoding="utf-8")
    return root


def test_legal_assets_expose_attribution_without_local_paths(tmp_path: Path) -> None:
    root = _legal_root(tmp_path)
    legal = LegalAssets([root])

    info = legal.info()

    assert info["application"] == {
        "name": "SPLICR Studio",
        "version": "1.2.3",
        "license": {"id": "Apache-2.0", "document_available": True},
    }
    assert info["public_release_ready"] is True
    assert info["ffmpeg"]["corresponding_source"] == {
        "available": True,
        "url": "https://downloads.example.test/SPLICR-FFmpeg-source.zip",
        "sha256": "a" * 64,
    }
    assert {item["id"] for item in info["documents"]} == {
        "application-license",
        "third-party-notices",
        "ffmpeg-license",
        "ffmpeg-source-info",
        "build-info",
    }
    assert str(root) not in json.dumps(info)
    assert legal.document("third-party-notices") == (
        "# Notices\n",
        "text/markdown; charset=utf-8",
    )


@pytest.mark.parametrize(
    ("url", "sha256"),
    [
        ("http://downloads.example.test/source.zip", "a" * 64),
        ("https://user:secret@downloads.example.test/source.zip", "a" * 64),
        ("https://downloads.example.test/source.zip", None),
        (None, "a" * 64),
        ("https://downloads.example.test/source.zip", "not-a-digest"),
    ],
)
def test_legal_assets_reject_unsafe_or_incomplete_source_metadata(
    tmp_path: Path,
    url: str | None,
    sha256: str | None,
) -> None:
    root = _legal_root(tmp_path, with_source=False)
    metadata = json.loads((root / "LEGAL_INFO.json").read_text(encoding="utf-8"))
    metadata["corresponding_source_url"] = url
    metadata["corresponding_source_sha256"] = sha256
    (root / "LEGAL_INFO.json").write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(LegalMetadataError):
        LegalAssets([root]).info()


def test_legal_api_returns_metadata_and_known_documents(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data", pacing_seconds=0, max_attempts=1)
    synthesis = SynthesisService(
        settings=settings,
        providers=ProviderRegistry([RecordingProvider()]),
    )
    legal = LegalAssets([_legal_root(tmp_path)])

    with TestClient(create_app(settings=settings, service=synthesis, legal_assets=legal)) as client:
        info_response = client.get("/v1/studio/legal")
        document_response = client.get("/v1/studio/legal/documents/application-license")
        missing_response = client.get("/v1/studio/legal/documents/not-a-document")

    assert info_response.status_code == 200
    assert info_response.headers["cache-control"] == "no-store"
    assert info_response.json()["public_release_ready"] is True
    assert document_response.status_code == 200
    assert document_response.text == "Apache-2.0 terms\n"
    assert document_response.headers["content-disposition"] == (
        'inline; filename="application-license.txt"'
    )
    assert missing_response.status_code == 404


def test_internal_build_is_explicitly_not_public_release_ready(tmp_path: Path) -> None:
    info = LegalAssets([_legal_root(tmp_path, with_source=False)]).info()

    assert info["public_release_ready"] is False
    assert info["ffmpeg"]["corresponding_source"] == {
        "available": False,
        "url": None,
        "sha256": None,
    }


def test_missing_application_license_is_not_public_release_ready(tmp_path: Path) -> None:
    info = LegalAssets([_legal_root(tmp_path, with_application_license=False)]).info()

    assert info["application"]["license"] == {
        "id": "Apache-2.0",
        "document_available": False,
    }
    assert info["public_release_ready"] is False
