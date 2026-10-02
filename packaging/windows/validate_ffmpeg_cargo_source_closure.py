from __future__ import annotations

import argparse
import csv
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


SCRIPT_ROOT = Path(__file__).resolve().parent
DEFAULT_CLOSURE = SCRIPT_ROOT / "ffmpeg-cargo-source-closure.tsv"
DEFAULT_REVIEW = SCRIPT_ROOT / "ffmpeg-source-license-review.tsv"

REGISTRY_SOURCE = "registry+https://github.com/rust-lang/crates.io-index"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ClosureProfile:
    locator: str
    revision: str
    target: str
    default_features: str
    features: str
    runtime_count: int
    build_count: int
    review_count: int
    workspace_packages: frozenset[str]
    workspace_license_paths: frozenset[str]
    required_terms: frozenset[str]
    validate_candidate_counts: bool


PROFILES = {
    "scripts.d/50-librsvg/99-librsvg.sh": ClosureProfile(
        locator="SCRIPT_REPO",
        revision="7612431eb02dc009319094f8513d63c1faaecfb4",
        target="x86_64-pc-windows-gnu",
        default_features="no",
        features="avif",
        runtime_count=182,
        build_count=21,
        review_count=662,
        workspace_packages=frozenset({"librsvg", "librsvg-c"}),
        workspace_license_paths=frozenset({"./COPYING.LIB"}),
        required_terms=frozenset(
            {
                "LGPL-2.1-or-later",
                "MIT",
                "Apache-2.0",
                "MPL-2.0",
                "Unicode-3.0",
                "Unicode-DFS-2016",
                "Zlib",
                "BSD-3-Clause",
            }
        ),
        validate_candidate_counts=False,
    ),
    "scripts.d/50-rav1e.sh": ClosureProfile(
        locator="SCRIPT_REPO",
        revision="31435de9d76fddd38f6dcc31d4014574cebb2092",
        target="x86_64-pc-windows-gnu",
        default_features="yes",
        features="default",
        runtime_count=82,
        build_count=41,
        review_count=512,
        workspace_packages=frozenset({"rav1e", "ivf"}),
        workspace_license_paths=frozenset({"./LICENSE", "./ivf/LICENSE"}),
        required_terms=frozenset({"BSD-2-Clause", "MIT", "Unicode-3.0"}),
        validate_candidate_counts=True,
    ),
}

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
    expected_total = sum(profile.runtime_count + profile.build_count for profile in PROFILES.values())
    if len(rows) != expected_total:
        fail(f"Expected {expected_total} Cargo closure packages, found {len(rows)}")

    package_ids: set[tuple[str, str]] = set()
    context_counts: dict[str, Counter[str]] = {stage: Counter() for stage in PROFILES}
    for row in rows:
        identity = f"{row['name']} {row['version']}"
        profile = PROFILES.get(row["stage"])
        if profile is None:
            fail(f"Unexpected Cargo closure stage: {row['stage']}")
        if (
            row["locator_variable"] != profile.locator
            or row["revision"] != profile.revision
            or row["target"] != profile.target
            or row["default_features"] != profile.default_features
            or row["features"] != profile.features
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
            if row["name"] not in profile.workspace_packages:
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
        package_key = (row["stage"], row["package_id"])
        if package_key in package_ids:
            fail(f"Duplicate Cargo package identity: {row['package_id']}")
        package_ids.add(package_key)
        context_counts[row["stage"]][row["context"]] += 1

    for stage, profile in PROFILES.items():
        expected_counts = Counter(runtime=profile.runtime_count, build=profile.build_count)
        if context_counts[stage] != expected_counts:
            fail(f"Unexpected Cargo closure split for {stage}: {dict(context_counts[stage])}")

    _, review_rows = read_tsv(review_path)
    for stage, profile in PROFILES.items():
        stage_reviews = [row for row in review_rows if row.get("stage") == stage]
        if len(stage_reviews) != profile.review_count:
            fail(
                f"Expected {profile.review_count} reviewed source candidates for {stage}, "
                f"found {len(stage_reviews)}"
            )
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
        missing_workspace_paths = profile.workspace_license_paths - shipped_license_paths
        if missing_workspace_paths:
            fail(
                f"Workspace packages have no exact shipped license review for {stage}: "
                f"{sorted(missing_workspace_paths)}"
            )

        for row in (item for item in rows if item["stage"] == stage):
            if row["source"] == "workspace":
                continue
            prefix = f"./vendor/{row['name']}-{row['version']}/"
            package_reviews = [item for item in stage_reviews if item["candidate_path"].startswith(prefix)]
            if profile.validate_candidate_counts and len(package_reviews) != int(row["candidate_count"]):
                fail(
                    f"Cargo package candidate count differs from review: "
                    f"{row['name']} {row['version']}"
                )
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
        missing_terms = profile.required_terms - expressions
        if missing_terms:
            fail(
                f"Cargo closure review for {stage} is missing selected SPDX terms: "
                f"{sorted(missing_terms)}"
            )

    runtime_total = sum(counts["runtime"] for counts in context_counts.values())
    build_total = sum(counts["build"] for counts in context_counts.values())
    return len(rows), runtime_total, build_total


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--closure", type=Path, default=DEFAULT_CLOSURE)
    parser.add_argument("--review", type=Path, default=DEFAULT_REVIEW)
    args = parser.parse_args()
    total, runtime, build = validate(args.closure, args.review)
    print(
        f"Validated {total} target-specific Cargo package(s): {runtime} runtime and "
        f"{build} build-only."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
