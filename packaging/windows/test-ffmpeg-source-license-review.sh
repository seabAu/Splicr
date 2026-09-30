#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 0 ]]; then
    echo "usage: $0" >&2
    exit 2
fi

script_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
validator="$script_root/validate-ffmpeg-source-license-review.sh"
review="$script_root/ffmpeg-source-license-review.tsv"
work_root="$(mktemp -d)"
trap 'rm -rf -- "$work_root"' EXIT

bash "$validator" "$review"

candidate_inventory="$work_root/candidate-inventory.tsv"
printf 'stage\tsource_status\tarchive_name\tarchive_sha256\tcandidate_path\tcandidate_sha256\textracted_path\n' \
    > "$candidate_inventory"
awk -F '\t' 'BEGIN { OFS = "\t" } NR > 1 { print $1, "collected", "synthetic.tar.xz", $4, $5, $6, "synthetic/" NR ".txt" }' \
    "$review" >> "$candidate_inventory"
bash "$validator" "$review" "$script_root/THIRD_PARTY_NOTICES.md" "$candidate_inventory"

missing_candidate_review="$work_root/missing-candidate-review.tsv"
head -n -1 "$review" > "$missing_candidate_review"
if bash "$validator" "$missing_candidate_review" "$script_root/THIRD_PARTY_NOTICES.md" \
    "$candidate_inventory" >/dev/null 2>&1; then
    echo "Review validator accepted a candidate inventory with no reviewed disposition" >&2
    exit 1
fi

missing_inventory_candidate="$work_root/missing-inventory-candidate.tsv"
sed '4d' "$candidate_inventory" > "$missing_inventory_candidate"
if bash "$validator" "$review" "$script_root/THIRD_PARTY_NOTICES.md" \
    "$missing_inventory_candidate" >/dev/null 2>&1; then
    echo "Review validator accepted a reviewed candidate absent from its supplied inventory" >&2
    exit 1
fi

tampered_revision="$work_root/tampered-revision.tsv"
sed 's/8b2d28faade10d74d99ac80e199aef664c9c5a3b/0000000000000000000000000000000000000000/' \
    "$review" > "$tampered_revision"
if bash "$validator" "$tampered_revision" >/dev/null 2>&1; then
    echo "Review validator accepted a revision outside the pinned graph" >&2
    exit 1
fi

duplicate="$work_root/duplicate.tsv"
cp "$review" "$duplicate"
tail -n +2 "$review" >> "$duplicate"
if bash "$validator" "$duplicate" >/dev/null 2>&1; then
    echo "Review validator accepted a duplicate evidence record" >&2
    exit 1
fi

unresolved_notice="$work_root/unresolved-notice.tsv"
sed $'0,/\trequired\t/s//\treview-needed\t/' "$review" > "$unresolved_notice"
if bash "$validator" "$unresolved_notice" >/dev/null 2>&1; then
    echo "Review validator accepted an unresolved notice requirement" >&2
    exit 1
fi

missing_notice_anchor="$work_root/missing-notice-anchor.tsv"
sed $'0,/\tlibogg source license SHA-256: [0-9a-f]*\t/s//\tMissing packaged notice anchor\t/' \
    "$review" > "$missing_notice_anchor"
if bash "$validator" "$missing_notice_anchor" >/dev/null 2>&1; then
    echo "Review validator accepted a required notice absent from the package notice file" >&2
    exit 1
fi

tampered_notices="$work_root/tampered-notices.md"
sed '0,/Copyright (c) 2002, Xiph.org Foundation/s//Copyright (c) 2003, Xiph.org Foundation/' \
    "$script_root/THIRD_PARTY_NOTICES.md" > "$tampered_notices"
if bash "$validator" "$review" "$tampered_notices" >/dev/null 2>&1; then
    echo "Review validator accepted packaged notice text that differs from its reviewed source" >&2
    exit 1
fi

tampered_packaged_licenses="$work_root/tampered-packaged-licenses.tsv"
sed 's/257a842724705950b07da76ce0e22ffa80ec77b3e9dfc6702522ac342409da0f/0000000000000000000000000000000000000000000000000000000000000000/' \
    "$script_root/ffmpeg-packaged-license-files.tsv" > "$tampered_packaged_licenses"
if bash "$validator" "$review" "$script_root/THIRD_PARTY_NOTICES.md" "" \
    "$tampered_packaged_licenses" >/dev/null 2>&1; then
    echo "Review validator accepted a packaged license file hash that differs from its reviewed source" >&2
    exit 1
fi

tampered_packaged_revision="$work_root/tampered-packaged-revision.tsv"
sed 's/6fced852d4d5cfad58cf9dbe3ea619b08e87d398/0000000000000000000000000000000000000000/g' \
    "$script_root/ffmpeg-packaged-license-files.tsv" > "$tampered_packaged_revision"
if bash "$validator" "$review" "$script_root/THIRD_PARTY_NOTICES.md" "" \
    "$tampered_packaged_revision" >/dev/null 2>&1; then
    echo "Review validator accepted a packaged license revision outside its reviewed source" >&2
    exit 1
fi

orphan_packaged_license="$work_root/orphan-packaged-license.tsv"
cp "$script_root/ffmpeg-packaged-license-files.tsv" "$orphan_packaged_license"
printf 'ffmpeg/ORPHAN.txt\thttps://example.invalid/ORPHAN.txt\t%s\t%s\n' \
    '1111111111111111111111111111111111111111' \
    '2222222222222222222222222222222222222222222222222222222222222222' \
    >> "$orphan_packaged_license"
if bash "$validator" "$review" "$script_root/THIRD_PARTY_NOTICES.md" "" \
    "$orphan_packaged_license" >/dev/null 2>&1; then
    echo "Review validator accepted a packaged license file with no reviewed source candidate" >&2
    exit 1
fi

unexpected_optional_anchor="$work_root/unexpected-optional-anchor.tsv"
sed $'0,/\tnot-required\t-\treviewed\t/s//\tnot-required\tUnexpected anchor\treviewed\t/' \
    "$review" > "$unexpected_optional_anchor"
if bash "$validator" "$unexpected_optional_anchor" >/dev/null 2>&1; then
    echo "Review validator accepted a misleading anchor for a non-required binary notice" >&2
    exit 1
fi

misclassified_not_built="$work_root/misclassified-not-built.tsv"
sed $'0,/\tnot-built\t-\tnot-applicable\t-\treviewed\t/s//\tnot-built\tBSL-1.0\trequired\tUnexpected anchor\treviewed\t/' \
    "$review" > "$misclassified_not_built"
if bash "$validator" "$misclassified_not_built" >/dev/null 2>&1; then
    echo "Review validator accepted shipped-license claims for a not-built candidate" >&2
    exit 1
fi

printf 'FFmpeg source license review validation passed tracked and negative cases.\n'
