from __future__ import annotations

import csv
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_ROOT = Path(__file__).resolve().parent
VALIDATOR_PATH = SCRIPT_ROOT / "validate_ffmpeg_cargo_source_closure.py"
SPEC = importlib.util.spec_from_file_location("ffmpeg_cargo_closure_validator", VALIDATOR_PATH)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VALIDATOR
SPEC.loader.exec_module(VALIDATOR)


def read_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        return list(reader.fieldnames or []), list(reader)


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class CargoSourceClosureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.closure = self.root / "closure.tsv"
        self.review = self.root / "review.tsv"
        self.closure.write_bytes(VALIDATOR.DEFAULT_CLOSURE.read_bytes())
        self.review.write_bytes(VALIDATOR.DEFAULT_REVIEW.read_bytes())

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_tracked_closure_is_complete(self) -> None:
        self.assertEqual(VALIDATOR.validate(self.closure, self.review), (203, 182, 21))

    def test_rejects_target_drift(self) -> None:
        fields, rows = read_tsv(self.closure)
        rows[0]["target"] = "x86_64-pc-windows-msvc"
        write_tsv(self.closure, fields, rows)
        with self.assertRaisesRegex(VALIDATOR.ValidationError, "identity mismatch"):
            VALIDATOR.validate(self.closure, self.review)

    def test_rejects_duplicate_package(self) -> None:
        fields, rows = read_tsv(self.closure)
        rows[-1] = rows[0].copy()
        write_tsv(self.closure, fields, rows)
        with self.assertRaisesRegex(VALIDATOR.ValidationError, "Duplicate Cargo package"):
            VALIDATOR.validate(self.closure, self.review)

    def test_rejects_checksum_drift(self) -> None:
        fields, rows = read_tsv(self.closure)
        registry_row = next(row for row in rows if row["source"] == VALIDATOR.REGISTRY_SOURCE)
        registry_row["vendor_package_checksum"] = "0" * 64
        write_tsv(self.closure, fields, rows)
        with self.assertRaisesRegex(VALIDATOR.ValidationError, "checksum-verified"):
            VALIDATOR.validate(self.closure, self.review)

    def test_rejects_local_path_identity(self) -> None:
        fields, rows = read_tsv(self.closure)
        workspace_row = next(row for row in rows if row["source"] == "workspace")
        workspace_row["package_id"] = "path+file:///C:/Users/example/librsvg"
        write_tsv(self.closure, fields, rows)
        with self.assertRaisesRegex(VALIDATOR.ValidationError, "workspace package provenance"):
            VALIDATOR.validate(self.closure, self.review)

    def test_rejects_runtime_package_without_shipped_license(self) -> None:
        closure_fields, closure_rows = read_tsv(self.closure)
        package = next(
            row
            for row in closure_rows
            if row["context"] == "runtime" and row["source"] == VALIDATOR.REGISTRY_SOURCE
        )
        review_fields, review_rows = read_tsv(self.review)
        prefix = f"./vendor/{package['name']}-{package['version']}/"
        for row in review_rows:
            if row["candidate_path"].startswith(prefix):
                row["candidate_disposition"] = "not-built"
        write_tsv(self.review, review_fields, review_rows)
        with self.assertRaisesRegex(VALIDATOR.ValidationError, "lacks the expected"):
            VALIDATOR.validate(self.closure, self.review)


if __name__ == "__main__":
    unittest.main()
