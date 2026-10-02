#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
    echo "usage: $0 ARCHIVE EXPECTED_CARGO_LOCK_SHA256 EXPECTED_VENDOR_PACKAGE_COUNT" >&2
    exit 2
fi

archive_path="$1"
expected_lock_sha256="$2"
expected_vendor_count="$3"

[[ -s "$archive_path" ]] || {
    echo "Collected source archive is missing or empty: $archive_path" >&2
    exit 1
}
xz --test "$archive_path"

if [[ -z "$expected_lock_sha256" && -z "$expected_vendor_count" ]]; then
    exit 0
fi
[[ "$expected_lock_sha256" =~ ^[0-9a-f]{64}$ && "$expected_vendor_count" =~ ^[1-9][0-9]*$ ]] || {
    echo "Invalid Cargo supplement expectations for $archive_path" >&2
    exit 1
}

listing_path="$(mktemp)"
trap 'rm -f -- "$listing_path"' EXIT
tar -tf "$archive_path" > "$listing_path"
grep -Fxq './Cargo.lock' "$listing_path" || {
    echo "Cargo-supplemented archive has no Cargo.lock: $archive_path" >&2
    exit 1
}
grep -Fxq './.cargo/config.toml' "$listing_path" || {
    echo "Cargo-supplemented archive has no vendoring config: $archive_path" >&2
    exit 1
}

actual_lock_sha256="$(tar -xOf "$archive_path" -- ./Cargo.lock | sha256sum | cut -d' ' -f1)"
[[ "$actual_lock_sha256" == "$expected_lock_sha256" ]] || {
    echo "Cargo lock checksum differs in collected archive: $archive_path" >&2
    exit 1
}

actual_vendor_count="$(
    awk -F/ '
        $1 == "." && $2 == "vendor" && $3 != "" { packages[$3] = 1 }
        END { print length(packages) }
    ' "$listing_path"
)"
[[ "$actual_vendor_count" -eq "$expected_vendor_count" ]] || {
    echo "Cargo vendor package count differs in collected archive: expected $expected_vendor_count, found $actual_vendor_count" >&2
    exit 1
}
