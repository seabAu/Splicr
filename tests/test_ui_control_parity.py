from __future__ import annotations

import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEGACY_SCHEMA = ROOT / "legacy" / "narrator" / "narrator" / "render_config.py"
PARITY_MANIFEST = ROOT / "docs" / "ui-control-parity.json"


def _legacy_field_names() -> set[str]:
    tree = ast.parse(LEGACY_SCHEMA.read_text(encoding="utf-8"))
    for statement in tree.body:
        if not isinstance(statement, ast.Assign):
            continue
        if any(
            isinstance(target, ast.Name) and target.id == "FIELDS"
            for target in statement.targets
        ):
            value = ast.literal_eval(statement.value)
            return set(value)
    raise AssertionError("legacy render_config.py no longer declares FIELDS")


def test_every_preserved_narrator_render_control_has_an_explicit_destination() -> None:
    manifest = json.loads(PARITY_MANIFEST.read_text(encoding="utf-8"))
    rows = manifest["legacy_render_fields"]
    keys = [row["key"] for row in rows]

    assert len(keys) == len(set(keys)), "parity manifest contains duplicate legacy fields"
    assert set(keys) == _legacy_field_names()
    assert all(row["status"] in manifest["statuses"] for row in rows)
    assert all(row.get("workspace") for row in rows)
    assert all(row.get("next_step") for row in rows if row["status"] == "gap")
    assert all(
        row.get("rationale")
        for row in rows
        if row["status"] == "intentional_replacement"
    )


def test_broader_native_capabilities_are_never_left_ambiguous() -> None:
    manifest = json.loads(PARITY_MANIFEST.read_text(encoding="utf-8"))
    rows = manifest["broader_native_capabilities"]

    assert len({row["capability"] for row in rows}) == len(rows)
    assert all(row["status"] in manifest["statuses"] for row in rows)
    assert all(row.get("workspace") for row in rows)
    assert all(row.get("next_step") for row in rows if row["status"] == "gap")
