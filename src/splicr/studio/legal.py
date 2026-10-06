from __future__ import annotations

import json
import re
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DOCUMENTS = {
    "third-party-notices": ("THIRD_PARTY_NOTICES.md", "text/markdown; charset=utf-8"),
    "ffmpeg-license": ("ffmpeg/LICENSE.txt", "text/plain; charset=utf-8"),
    "ffmpeg-source-info": ("ffmpeg/SOURCE_INFO.txt", "text/plain; charset=utf-8"),
    "build-info": ("BUILD_INFO.txt", "text/plain; charset=utf-8"),
}


class LegalMetadataError(ValueError):
    """The packaged legal metadata is malformed or unsafe to expose."""


class LegalDocumentNotFoundError(LookupError):
    """A known legal document is not present in this runtime."""


class LegalAssets:
    """Resolve packaged legal material without leaking host filesystem paths."""

    def __init__(self, roots: list[Path] | tuple[Path, ...] | None = None) -> None:
        self.roots = tuple(Path(root).resolve() for root in (roots or self._default_roots()))

    @staticmethod
    def _default_roots() -> tuple[Path, ...]:
        roots: list[Path] = []
        bundle_root = getattr(sys, "_MEIPASS", None)
        if bundle_root:
            roots.append(Path(bundle_root))
        repository_root = Path(__file__).resolve().parents[3]
        roots.extend(
            [
                repository_root / "packaging" / "windows",
                repository_root / "packaging" / "windows" / "vendor",
                repository_root / "packaging" / "windows" / "vendor" / "ffmpeg",
            ]
        )
        return tuple(roots)

    @staticmethod
    def _application_version() -> str:
        try:
            return version("splicr-tts")
        except PackageNotFoundError:
            return "development"

    def info(self) -> dict[str, Any]:
        metadata = self._release_metadata()
        corresponding_source_url = self._optional_https_url(
            metadata.get("corresponding_source_url"),
            "corresponding_source_url",
        )
        corresponding_source_sha256 = self._optional_sha256(
            metadata.get("corresponding_source_sha256"),
            "corresponding_source_sha256",
        )
        if bool(corresponding_source_url) != bool(corresponding_source_sha256):
            raise LegalMetadataError(
                "corresponding source URL and SHA-256 must either both be present or both be absent"
            )

        documents = [
            {
                "id": document_id,
                "label": label,
                "url": f"/v1/studio/legal/documents/{document_id}",
            }
            for document_id, label in (
                ("third-party-notices", "Third-party notices"),
                ("ffmpeg-license", "Bundled FFmpeg license"),
                ("ffmpeg-source-info", "Bundled binary source record"),
                ("build-info", "Bundled media build information"),
            )
            if self._find_document(document_id) is not None
        ]
        app_version = str(metadata.get("application_version") or self._application_version())
        effective_license = str(
            metadata.get("ffmpeg_effective_license")
            or "GPL-covered (FFTW3 statically incorporated through Chromaprint)"
        )
        return {
            "schema_version": 1,
            "application": {"name": "SPLICR Studio", "version": app_version},
            "ffmpeg": {
                "project_url": "https://ffmpeg.org/",
                "legal_url": "https://ffmpeg.org/legal.html",
                "effective_license": effective_license,
                "attribution": (
                    "SPLICR Studio uses FFmpeg and FFprobe for local audio and video processing. "
                    "FFmpeg is a separate third-party project and is not owned by SPLICR Studio."
                ),
                "corresponding_source": {
                    "available": corresponding_source_url is not None,
                    "url": corresponding_source_url,
                    "sha256": corresponding_source_sha256,
                },
            },
            "public_release_ready": bool(corresponding_source_url and corresponding_source_sha256),
            "documents": documents,
        }

    def document(self, document_id: str) -> tuple[str, str]:
        record = _DOCUMENTS.get(document_id)
        if record is None:
            raise LegalDocumentNotFoundError(document_id)
        path = self._find_document(document_id)
        if path is None:
            raise LegalDocumentNotFoundError(document_id)
        return path.read_text(encoding="utf-8", errors="replace"), record[1]

    def _release_metadata(self) -> dict[str, Any]:
        path = self._find_relative("LEGAL_INFO.json")
        if path is None:
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise LegalMetadataError("could not read packaged legal metadata") from error
        if not isinstance(value, dict) or value.get("schema_version") != 1:
            raise LegalMetadataError("unsupported packaged legal metadata schema")
        return value

    def _find_document(self, document_id: str) -> Path | None:
        record = _DOCUMENTS.get(document_id)
        return self._find_relative(record[0]) if record else None

    def _find_relative(self, relative_path: str) -> Path | None:
        relative = Path(relative_path)
        for root in self.roots:
            candidate = (root / relative).resolve()
            try:
                candidate.relative_to(root)
            except ValueError:
                continue
            if candidate.is_file():
                return candidate
        return None

    @staticmethod
    def _optional_https_url(value: object, field: str) -> str | None:
        if value in (None, ""):
            return None
        if not isinstance(value, str):
            raise LegalMetadataError(f"{field} must be a string")
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise LegalMetadataError(f"{field} must be an HTTPS URL without embedded credentials")
        return value

    @staticmethod
    def _optional_sha256(value: object, field: str) -> str | None:
        if value in (None, ""):
            return None
        if not isinstance(value, str) or _SHA256.fullmatch(value.lower()) is None:
            raise LegalMetadataError(f"{field} must be a 64-character SHA-256 digest")
        return value.lower()
