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
sed $'2s/\trequired\t/\treview-needed\t/' "$review" > "$unresolved_notice"
if bash "$validator" "$unresolved_notice" >/dev/null 2>&1; then
    echo "Review validator accepted an unresolved notice requirement" >&2
    exit 1
fi

missing_notice_anchor="$work_root/missing-notice-anchor.tsv"
sed $'2s/\tlibogg source license SHA-256: [0-9a-f]*\t/\tMissing packaged notice anchor\t/' \
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

printf 'FFmpeg source license review validation passed tracked and negative cases.\n'
