from __future__ import annotations

import json
from pathlib import Path

import pytest

from splicr.config import Settings
from splicr.package_acceptance_state import (
    PackageAcceptanceStateError,
    seed_package_acceptance_state,
    verify_package_acceptance_state,
)
from splicr.profiles import StudioProfileStore
from splicr.store import SqliteJobStore
from splicr.studio import SqliteStudioStore


def test_representative_package_state_round_trips_semantically(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    manifest_path = tmp_path / "evidence" / "acceptance-state.json"

    manifest = seed_package_acceptance_state(settings, manifest_path)
    verified = verify_package_acceptance_state(settings, manifest_path)

    assert verified == {
        "schema_version": 1,
        "verified": True,
        "entity_count": 7,
        "file_count": 3,
    }
    assert manifest_path.is_file()
    assert manifest["source_sha256"] == (
        "7eada6ed3265254e0bf636179599ba0d15750b75e933e99fbcab8c8719c854db"
    )
    entities = manifest["entities"]
    assert SqliteJobStore(settings.database_path).get_job(entities["job_id"]).status.value == (
        "completed"
    )
    assert (
        SqliteStudioStore(settings.database_path).get_project(entities["project_id"]).source_name
        == "package-acceptance.md"
    )
    assert (
        StudioProfileStore(settings.database_path)
        .get(entities["studio_profile_id"])
        .remove_numeric_citations
        is True
    )


def test_representative_package_state_detects_changed_media(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    manifest_path = tmp_path / "acceptance-state.json"
    manifest = seed_package_acceptance_state(settings, manifest_path)
    output = settings.data_dir / Path(manifest["files"]["output"]["relative_path"])
    output.write_bytes(output.read_bytes() + b"tampered")

    with pytest.raises(PackageAcceptanceStateError, match="generated-media artifact|output file"):
        verify_package_acceptance_state(settings, manifest_path)


def test_representative_package_state_rejects_manifest_path_escape(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    manifest_path = tmp_path / "acceptance-state.json"
    manifest = seed_package_acceptance_state(settings, manifest_path)
    manifest["files"]["source"]["relative_path"] = "../outside.txt"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(PackageAcceptanceStateError, match="unsafe source path"):
        verify_package_acceptance_state(settings, manifest_path)


def test_representative_package_state_seed_is_fail_closed_when_reused(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    manifest_path = tmp_path / "acceptance-state.json"
    seed_package_acceptance_state(settings, manifest_path)

    with pytest.raises(PackageAcceptanceStateError, match="manifest already exists"):
        seed_package_acceptance_state(settings, manifest_path)
