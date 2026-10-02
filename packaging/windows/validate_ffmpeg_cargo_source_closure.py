from __future__ import annotations

import argparse
import csv
import re
from collections import Counter
from pathlib import Path


SCRIPT_ROOT = Path(__file__).resolve().parent
DEFAULT_CLOSURE = SCRIPT_ROOT / "ffmpeg-cargo-source-closure.tsv"
DEFAULT_REVIEW = SCRIPT_ROOT / "ffmpeg-source-license-review.tsv"

STAGE = "scripts.d/50-librsvg/99-librsvg.sh"
LOCATOR = "SCRIPT_REPO"
REVISION = "7612431eb02dc009319094f8513d63c1faaecfb4"
TARGET = "x86_64-pc-windows-gnu"
FEATURES = "avif"
REGISTRY_SOURCE = "registry+https://github.com/rust-lang/crates.io-index"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

CLOSURE_FIELDS = [
    "stage",
    "locator_variable",
    "revision",
    "target",
    "default_features",
    "features",
    "context",
    "name",
    "version",
    "license",
    "source",
    "cargo_lock_checksum",
    "vendor_package_checksum",
    "checksum_files_verified",
    "candidate_count",
    "package_id",
]


class ValidationError(ValueError):
    pass


def read_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        rows = list(reader)
        return list(reader.fieldnames or []), rows


def fail(message: str) -> None:
    raise ValidationError(message)


def validate(closure_path: Path, review_path: Path) -> tuple[int, int, int]:
    fields, rows = read_tsv(closure_path)
    if fields != CLOSURE_FIELDS:
        fail("Unexpected FFmpeg Cargo source closure header")
    if len(rows) != 203:
        fail(f"Expected 203 Cargo closure packages, found {len(rows)}")

    package_ids: set[str] = set()
    context_counts: Counter[str] = Counter()
    for row in rows:
        identity = f"{row['name']} {row['version']}"
        if (
            row["stage"] != STAGE
            or row["locator_variable"] != LOCATOR
            or row["revision"] != REVISION
            or row["target"] != TARGET
            or row["default_features"] != "no"
            or row["features"] != FEATURES
        ):
            fail(f"Cargo closure source/build identity mismatch: {identity}")
        if row["context"] not in {"runtime", "build"}:
            fail(f"Invalid Cargo closure context: {identity}")
        if not row["name"] or not row["version"] or not row["license"]:
            fail(f"Incomplete Cargo package identity: {identity}")
        try:
            candidate_count = int(row["candidate_count"])
        except ValueError as error:
            raise ValidationError(f"Invalid candidate count: {identity}") from error
        if candidate_count < 1:
            fail(f"Cargo package has no reviewed source candidates: {identity}")

        if row["source"] == "workspace":
            if row["name"] not in {"librsvg", "librsvg-c"}:
                fail(f"Unexpected workspace package: {identity}")
            if (
                row["cargo_lock_checksum"]
                or row["vendor_package_checksum"]
                or row["checksum_files_verified"] != "n/a"
                or row["package_id"] != f"workspace#{row['name']}@{row['version']}"
            ):
                fail(f"Invalid workspace package provenance: {identity}")
        else:
            if row["source"] != REGISTRY_SOURCE:
                fail(f"Unexpected Cargo package source: {identity}")
            if (
                not SHA256_RE.fullmatch(row["cargo_lock_checksum"])
                or row["cargo_lock_checksum"] != row["vendor_package_checksum"]
                or row["checksum_files_verified"] != "yes"
                or not row["package_id"].startswith(f"{REGISTRY_SOURCE}#")
            ):
                fail(f"Invalid checksum-verified Cargo provenance: {identity}")

        if re.search(r"(?:^[A-Za-z]:[/\\]|/home/|/Users/)", row["package_id"]):
            fail(f"Cargo package identity leaks a local path: {identity}")
        if row["package_id"] in package_ids:
            fail(f"Duplicate Cargo package identity: {row['package_id']}")
        package_ids.add(row["package_id"])
        context_counts[row["context"]] += 1

    if context_counts != Counter(runtime=182, build=21):
        fail(f"Unexpected Cargo closure split: {dict(context_counts)}")

    _, review_rows = read_tsv(review_path)
    stage_reviews = [row for row in review_rows if row.get("stage") == STAGE]
    shipped_license_paths = {
        row["candidate_path"]
        for row in stage_reviews
        if row.get("candidate_disposition") == "shipped-license"
    }
    build_only_paths = {
        row["candidate_path"]
        for row in stage_reviews
        if row.get("candidate_disposition") == "build-only"
    }
    if "./COPYING.LIB" not in shipped_license_paths:
        fail("Workspace librsvg packages have no exact shipped license review")

    for row in rows:
        if row["source"] == "workspace":
            continue
        prefix = f"./vendor/{row['name']}-{row['version']}/"
        relevant = shipped_license_paths if row["context"] == "runtime" else build_only_paths
        if not any(path.startswith(prefix) for path in relevant):
            fail(
                f"Cargo {row['context']} package lacks the expected reviewed disposition: "
                f"{row['name']} {row['version']}"
            )

    expressions = {
        row.get("spdx_expression", "")
        for row in stage_reviews
        if row.get("candidate_disposition") == "shipped-license"
    }
    required_terms = {
        "LGPL-2.1-or-later",
        "MIT",
        "Apache-2.0",
        "MPL-2.0",
        "Unicode-3.0",
        "Unicode-DFS-2016",
        "Zlib",
        "BSD-3-Clause",
    }
    missing_terms = required_terms - expressions
    if missing_terms:
        fail(f"Cargo closure review is missing selected SPDX terms: {sorted(missing_terms)}")

    return len(rows), context_counts["runtime"], context_counts["build"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--closure", type=Path, default=DEFAULT_CLOSURE)
    parser.add_argument("--review", type=Path, default=DEFAULT_REVIEW)
    args = parser.parse_args()
    total, runtime, build = validate(args.closure, args.review)
    print(
        f"Validated {total} librsvg Cargo package(s): {runtime} runtime and "
        f"{build} build-only."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
