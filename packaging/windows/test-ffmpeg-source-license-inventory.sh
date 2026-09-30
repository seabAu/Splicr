#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 0 ]]; then
    echo "usage: $0" >&2
    exit 2
fi

script_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
inventory_tool="$script_root/inventory-ffmpeg-source-licenses.sh"
work_root="$(mktemp -d)"
trap 'rm -rf -- "$work_root"' EXIT
collection_root="$work_root/collection"
mkdir -p "$collection_root/stages"

make_archive() {
    local source_root="$1"
    local archive_path="$2"
    (
        cd "$source_root"
        tar --sort=name --mtime='@0' --owner=0 --group=0 --numeric-owner \
            -I 'xz -T1 -9e' -cpf "$archive_path" .
    )
}

licensed_source="$work_root/licensed-source"
mkdir -p "$licensed_source/docs" "$licensed_source/LICENSES"
printf 'Synthetic permissive license\n' > "$licensed_source/LICENSE"
printf 'Synthetic notice\n' > "$licensed_source/docs/NOTICE.md"
printf 'Synthetic nested SPDX text\n' > "$licensed_source/LICENSES/BSD-2-Clause.txt"
ln -s ../LICENSE "$licensed_source/LICENSES/ISC.txt"
printf 'Read me\n' > "$licensed_source/README.md"
licensed_archive='scripts.d__10-licensed_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.tar.xz'
make_archive "$licensed_source" "$collection_root/stages/$licensed_archive"
licensed_sha="$(sha256sum "$collection_root/stages/$licensed_archive" | cut -d' ' -f1)"

unclassified_source="$work_root/unclassified-source"
mkdir -p "$unclassified_source/include"
printf 'No filename-based license candidate here\n' > "$unclassified_source/README.md"
printf 'Permission is hereby granted in this synthetic embedded notice.\n' \
    > "$unclassified_source/include/embedded_notice.h"
unclassified_archive='scripts.d__20-unclassified_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.tar.xz'
make_archive "$unclassified_source" "$collection_root/stages/$unclassified_archive"
unclassified_sha="$(sha256sum "$collection_root/stages/$unclassified_archive" | cut -d' ' -f1)"

cat > "$collection_root/collection-plan.tsv" <<EOF
stage	command_sha256	source_status	archive_name
scripts.d/10-licensed.sh	aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa	fetch	$licensed_archive
scripts.d/20-unclassified.sh	bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb	fetch	$unclassified_archive
scripts.d/30-built-in.sh	e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855	no-external-source	
EOF
cat > "$collection_root/collection-manifest.tsv" <<EOF
stage	command_sha256	source_status	archive_name	archive_sha256
scripts.d/10-licensed.sh	aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa	collected	$licensed_archive	$licensed_sha
scripts.d/20-unclassified.sh	bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb	collected	$unclassified_archive	$unclassified_sha
scripts.d/30-built-in.sh	e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855	no-external-source		
EOF
cat > "$collection_root/COLLECTION_INFO.txt" <<'EOF'
SPLICR Studio FFmpeg dependency source collection
State: sources-collected-unreviewed
Scope: synthetic-test
Corresponding source complete: false
Public release gate satisfied: false
EOF
(
    cd "$collection_root"
    sha256sum \
        "stages/$licensed_archive" \
        "stages/$unclassified_archive" \
        collection-manifest.tsv \
        collection-plan.tsv > COLLECTION-SHA256SUMS.txt
)

extra_paths="$work_root/extra-paths.tsv"
cat > "$extra_paths" <<'EOF'
stage	candidate_path
scripts.d/20-unclassified.sh	./include/embedded_notice.h
EOF
export FFMPEG_LICENSE_EXTRA_PATHS_FILE="$extra_paths"

bash "$inventory_tool" "$collection_root"

inventory="$collection_root/license-candidate-inventory.tsv"
review="$collection_root/license-review-template.tsv"
info="$collection_root/LICENSE_REVIEW_INFO.txt"
[[ "$(($(wc -l < "$inventory") - 1))" -eq 6 ]]
grep -Fq $'scripts.d/10-licensed.sh	collected	4			pending	' "$review"
grep -Fq $'scripts.d/20-unclassified.sh	collected	1			pending	' "$review"
grep -Fq $'scripts.d/30-built-in.sh	no-external-source	0			not-applicable	' "$review"
grep -Fq $'./LICENSE	' "$inventory"
grep -Fq $'./LICENSES/BSD-2-Clause.txt	' "$inventory"
grep -Fq $'./LICENSES/ISC.txt	' "$inventory"
grep -Fq $'./docs/NOTICE.md	' "$inventory"
grep -Fq $'./include/embedded_notice.h	' "$inventory"
grep -Fq 'State: candidates-extracted-unreviewed' "$info"
grep -Fq 'Pending human review count: 2' "$info"
grep -Fq 'Stages with no tracked license candidate: 0' "$info"
grep -Fq 'All enabled dependency licenses reviewed: false' "$info"
grep -Fq 'Corresponding source complete: false' "$info"
grep -Fq 'Public release gate satisfied: false' "$info"

license_hash="$(printf 'Synthetic permissive license\n' | sha256sum | cut -d' ' -f1)"
grep -Fq "$license_hash" "$inventory"
awk -F '	' -v expected_hash="$license_hash" '
    $5 == "./LICENSES/ISC.txt" && $6 == expected_hash { found = 1 }
    END { exit !found }
' "$inventory"
grep -RFlq 'Synthetic permissive license' "$collection_root/license-candidates"

snapshot_root="$work_root/snapshot"
mkdir -p "$snapshot_root"
cp "$inventory" "$review" "$info" "$snapshot_root/"
cp -a "$collection_root/license-candidates" "$snapshot_root/"
printf 'stale\n' > "$collection_root/license-candidates/stale.txt"
bash "$inventory_tool" "$collection_root" >/dev/null
cmp "$inventory" "$snapshot_root/license-candidate-inventory.tsv"
cmp "$review" "$snapshot_root/license-review-template.tsv"
cmp "$info" "$snapshot_root/LICENSE_REVIEW_INFO.txt"
diff -ru "$snapshot_root/license-candidates" "$collection_root/license-candidates"

escape_source="$work_root/escape-source"
cp -a "$licensed_source" "$escape_source"
ln -s ../../../outside "$escape_source/LICENSES/ESCAPE.txt"
escape_archive="$work_root/escape.tar.xz"
make_archive "$escape_source" "$escape_archive"
cp "$collection_root/stages/$licensed_archive" "$work_root/licensed-archive.symlink-backup"
cp "$collection_root/collection-manifest.tsv" "$work_root/manifest.symlink-backup"
cp "$collection_root/COLLECTION-SHA256SUMS.txt" "$work_root/checksums.symlink-backup"
cp "$escape_archive" "$collection_root/stages/$licensed_archive"
escape_sha="$(sha256sum "$collection_root/stages/$licensed_archive" | cut -d' ' -f1)"
sed -i "s/$licensed_sha/$escape_sha/" "$collection_root/collection-manifest.tsv"
(
    cd "$collection_root"
    sha256sum \
        "stages/$licensed_archive" \
        "stages/$unclassified_archive" \
        collection-manifest.tsv \
        collection-plan.tsv > COLLECTION-SHA256SUMS.txt
)
if bash "$inventory_tool" "$collection_root" >/dev/null 2>&1; then
    echo "License inventory followed a candidate symlink outside the archive root" >&2
    exit 1
fi
mv "$work_root/licensed-archive.symlink-backup" "$collection_root/stages/$licensed_archive"
mv "$work_root/manifest.symlink-backup" "$collection_root/collection-manifest.tsv"
mv "$work_root/checksums.symlink-backup" "$collection_root/COLLECTION-SHA256SUMS.txt"

cp "$collection_root/stages/$licensed_archive" "$work_root/licensed-archive.backup"
printf 'tamper\n' >> "$collection_root/stages/$licensed_archive"
if bash "$inventory_tool" "$collection_root" >/dev/null 2>&1; then
    echo "License inventory accepted a checksum-mismatched archive" >&2
    exit 1
fi
mv "$work_root/licensed-archive.backup" "$collection_root/stages/$licensed_archive"

cp "$collection_root/collection-manifest.tsv" "$work_root/manifest.backup"
sed -i '1s/archive_sha256/archive_digest/' "$collection_root/collection-manifest.tsv"
if bash "$inventory_tool" "$collection_root" >/dev/null 2>&1; then
    echo "License inventory accepted an unexpected manifest schema" >&2
    exit 1
fi
mv "$work_root/manifest.backup" "$collection_root/collection-manifest.tsv"

cp "$collection_root/COLLECTION-SHA256SUMS.txt" "$work_root/checksums.backup"
sed -i '/  collection-plan.tsv$/d' "$collection_root/COLLECTION-SHA256SUMS.txt"
if bash "$inventory_tool" "$collection_root" >/dev/null 2>&1; then
    echo "License inventory accepted a checksum set that omitted the collection plan" >&2
    exit 1
fi
mv "$work_root/checksums.backup" "$collection_root/COLLECTION-SHA256SUMS.txt"

cp "$extra_paths" "$work_root/extra-paths.backup"
printf 'scripts.d/20-unclassified.sh\t./include/missing.h\n' >> "$extra_paths"
if bash "$inventory_tool" "$collection_root" >/dev/null 2>&1; then
    echo "License inventory accepted a missing supplemental candidate path" >&2
    exit 1
fi
mv "$work_root/extra-paths.backup" "$extra_paths"

printf 'FFmpeg source license-candidate inventory passed deterministic and negative cases.\n'
