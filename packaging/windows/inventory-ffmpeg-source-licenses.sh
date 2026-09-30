#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "usage: $0 COLLECTION_DIRECTORY" >&2
    exit 2
fi

collection_root="$1"
[[ -d "$collection_root" ]] || {
    echo "Collection directory not found: $collection_root" >&2
    exit 1
}
collection_root="$(cd "$collection_root" && pwd)"

manifest_path="$collection_root/collection-manifest.tsv"
plan_path="$collection_root/collection-plan.tsv"
checksums_path="$collection_root/COLLECTION-SHA256SUMS.txt"
collection_info_path="$collection_root/COLLECTION_INFO.txt"
for required in "$manifest_path" "$plan_path" "$checksums_path" "$collection_info_path"; do
    [[ -f "$required" ]] || { echo "Required collection file not found: $required" >&2; exit 1; }
done

expected_header=$'stage\tcommand_sha256\tsource_status\tarchive_name\tarchive_sha256'
[[ "$(head -n 1 "$manifest_path")" == "$expected_header" ]] || {
    echo "Unexpected collection manifest header" >&2
    exit 1
}
grep -Eq '^[0-9a-f]{64}  collection-manifest\.tsv$' "$checksums_path" || {
    echo "Collection checksum file does not authenticate collection-manifest.tsv" >&2
    exit 1
}
grep -Eq '^[0-9a-f]{64}  collection-plan\.tsv$' "$checksums_path" || {
    echo "Collection checksum file does not authenticate collection-plan.tsv" >&2
    exit 1
}

(
    cd "$collection_root"
    sha256sum --check --strict COLLECTION-SHA256SUMS.txt
) >/dev/null

candidate_root="$collection_root/license-candidates"
inventory_path="$collection_root/license-candidate-inventory.tsv"
review_template_path="$collection_root/license-review-template.tsv"
review_info_path="$collection_root/LICENSE_REVIEW_INFO.txt"
rm -rf -- "$candidate_root"
mkdir -p "$candidate_root"

printf 'stage\tsource_status\tarchive_name\tarchive_sha256\tcandidate_path\tcandidate_sha256\textracted_path\n' \
    > "$inventory_path"
printf 'stage\tsource_status\tcandidate_count\tproposed_spdx_expression\tnotice_requirements\treview_status\treviewer_notes\n' \
    > "$review_template_path"

stage_count=0
source_stage_count=0
no_source_count=0
pending_review_count=0
missing_candidate_count=0

while IFS=$'\t' read -r stage command_sha256 source_status archive_name archive_sha256; do
    [[ "$stage" != "stage" ]] || continue
    [[ -n "$stage" && -n "$command_sha256" && -n "$source_status" ]] || {
        echo "Malformed collection manifest row" >&2
        exit 1
    }
    stage_count=$((stage_count + 1))

    if [[ "$source_status" == "no-external-source" ]]; then
        [[ -z "$archive_name" && -z "$archive_sha256" ]] || {
            echo "No-source stage unexpectedly names an archive: $stage" >&2
            exit 1
        }
        printf '%s\t%s\t\t\t\t\t\n' "$stage" "$source_status" >> "$inventory_path"
        printf '%s\t%s\t0\t\t\tnot-applicable\t\n' "$stage" "$source_status" \
            >> "$review_template_path"
        no_source_count=$((no_source_count + 1))
        continue
    fi

    [[ "$source_status" == "collected" && -n "$archive_name" && -n "$archive_sha256" ]] || {
        echo "Source-bearing stage is not a complete collected row: $stage" >&2
        exit 1
    }
    [[ "$archive_name" != */* && "$archive_name" == *.tar.xz ]] || {
        echo "Unsafe or unexpected archive name for $stage: $archive_name" >&2
        exit 1
    }

    archive_path="$collection_root/stages/$archive_name"
    [[ -s "$archive_path" ]] || { echo "Collected archive missing: $archive_name" >&2; exit 1; }
    xz --test "$archive_path"
    actual_archive_sha256="$(sha256sum "$archive_path" | cut -d' ' -f1)"
    [[ "$actual_archive_sha256" == "$archive_sha256" ]] || {
        echo "Collected archive checksum mismatch: $archive_name" >&2
        exit 1
    }

    slug="${stage%.sh}"
    slug="${slug//\//__}"
    stage_candidate_root="$candidate_root/$slug"
    mkdir -p "$stage_candidate_root"
    stage_index_path="$stage_candidate_root/candidate-index.tsv"
    printf 'extracted_path\tarchive_path\tsha256\n' > "$stage_index_path"

    mapfile -t candidate_paths < <(
        tar -tf "$archive_path" |
            LC_ALL=C sort -u |
            awk '
                {
                    path = tolower($0)
                    if (path ~ /(^|\/)(licen[cs]e(s)?([._-][^\/]*)?|unlicense([._-][^\/]*)?|copying[^\/]*|notice([._-][^\/]*)?|copyright(s)?([._-][^\/]*)?|patents?([._-][^\/]*)?|legal([._-][^\/]*)?)$/ ||
                        path ~ /(^|\/)(licenses?|legal)\/[^\/]+$/) {
                        print $0
                    }
                }
            '
    )

    candidate_count=0
    for candidate_path in "${candidate_paths[@]}"; do
        [[ -n "$candidate_path" && "$candidate_path" != */ ]] || continue
        [[ "$candidate_path" != *$'\t'* && "$candidate_path" != *$'\n'* ]] || {
            echo "License/notice candidate path cannot be represented safely: $stage" >&2
            exit 1
        }
        candidate_count=$((candidate_count + 1))
        extracted_name="$(printf '%03d.txt' "$candidate_count")"
        extracted_relative="license-candidates/$slug/$extracted_name"
        extracted_path="$collection_root/$extracted_relative"
        tar -xOf "$archive_path" -- "$candidate_path" > "$extracted_path"
        [[ -s "$extracted_path" ]] || {
            echo "License/notice candidate is empty or not a regular readable file: $stage $candidate_path" >&2
            exit 1
        }
        candidate_sha256="$(sha256sum "$extracted_path" | cut -d' ' -f1)"
        printf '%s\t%s\t%s\n' "$extracted_relative" "$candidate_path" "$candidate_sha256" \
            >> "$stage_index_path"
        printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
            "$stage" "$source_status" "$archive_name" "$archive_sha256" \
            "$candidate_path" "$candidate_sha256" "$extracted_relative" >> "$inventory_path"
    done

    if [[ "$candidate_count" -eq 0 ]]; then
        printf '%s\t%s\t%s\t%s\t\t\t\n' \
            "$stage" "$source_status" "$archive_name" "$archive_sha256" >> "$inventory_path"
        missing_candidate_count=$((missing_candidate_count + 1))
    fi
    printf '%s\t%s\t%s\t\t\tpending\t\n' "$stage" "$source_status" "$candidate_count" \
        >> "$review_template_path"
    source_stage_count=$((source_stage_count + 1))
    pending_review_count=$((pending_review_count + 1))
done < "$manifest_path"

[[ "$stage_count" -gt 0 ]] || { echo "Collection manifest contains no stages" >&2; exit 1; }

collection_scope="$(sed -n 's/^Scope: //p' "$collection_info_path")"
[[ -n "$collection_scope" ]] || collection_scope="unknown"
cat > "$review_info_path" <<EOF
SPLICR Studio FFmpeg dependency license-candidate inventory
State: candidates-extracted-unreviewed
Collection scope: $collection_scope
Selected stage count: $stage_count
Selected source-bearing stage count: $source_stage_count
No-external-source stage count: $no_source_count
Pending human review count: $pending_review_count
Stages with no filename-based license candidate: $missing_candidate_count
All enabled dependency licenses reviewed: false
Corresponding source complete: false
Public release gate satisfied: false
EOF

printf 'Extracted license/notice candidates for %s source-bearing stage(s); %s require review and %s have no filename-based candidate.\n' \
    "$source_stage_count" "$pending_review_count" "$missing_candidate_count"
