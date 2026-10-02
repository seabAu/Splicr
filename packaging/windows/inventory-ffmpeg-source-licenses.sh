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
script_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
extra_paths_path="${FFMPEG_LICENSE_EXTRA_PATHS_FILE:-$script_root/ffmpeg-source-license-extra-paths.tsv}"
[[ -f "$extra_paths_path" ]] || {
    echo "Supplemental license-candidate path manifest not found: $extra_paths_path" >&2
    exit 1
}
expected_extra_header=$'stage\tcandidate_path'
[[ "$(head -n 1 "$extra_paths_path")" == "$expected_extra_header" ]] || {
    echo "Unexpected supplemental license-candidate path manifest header" >&2
    exit 1
}
declare -A seen_extra_paths=()
while IFS=$'\t' read -r extra_stage extra_candidate_path extra_field; do
    [[ "$extra_stage" != "stage" ]] || continue
    [[ -n "$extra_stage" && -n "$extra_candidate_path" && -z "$extra_field" ]] || {
        echo "Malformed supplemental license-candidate path row" >&2
        exit 1
    }
    [[ "$extra_stage" == scripts.d/*.sh && "$extra_stage" != *'..'* && \
        "$extra_candidate_path" == ./* && "$extra_candidate_path" != *'..'* && \
        "$extra_candidate_path" != */ && "$extra_candidate_path" != *$'\n'* ]] || {
        echo "Unsafe supplemental license-candidate path: $extra_stage $extra_candidate_path" >&2
        exit 1
    }
    extra_key="$extra_stage"$'\t'"$extra_candidate_path"
    [[ -z "${seen_extra_paths[$extra_key]:-}" ]] || {
        echo "Duplicate supplemental license-candidate path: $extra_stage $extra_candidate_path" >&2
        exit 1
    }
    seen_extra_paths[$extra_key]=1
done < "$extra_paths_path"

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
inventory_work_root="$(mktemp -d)"
trap 'rm -rf -- "$inventory_work_root"' EXIT
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

extract_candidate_bytes() {
    local extracted_root="$1"
    local stage="$2"
    local candidate_path="$3"
    local output_path="$4"
    local source_path="$extracted_root/${candidate_path#./}"
    local resolved_path

    resolved_path="$(realpath -e -- "$source_path")" || {
        echo "License/notice candidate is missing or has an invalid symlink chain: $stage $candidate_path" >&2
        return 1
    }
    [[ "$resolved_path" == "$extracted_root"/* ]] || {
        echo "License/notice candidate symlink escapes archive root: $stage $candidate_path" >&2
        return 1
    }
    [[ -f "$resolved_path" ]] || {
        echo "License/notice candidate is not a regular file or safe symlink: $stage $candidate_path" >&2
        return 1
    }
    cp -- "$resolved_path" "$output_path"
}

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

    stage_extract_root="$inventory_work_root/$slug"
    mkdir -p "$stage_extract_root"
    tar -xf "$archive_path" -C "$stage_extract_root"

    mapfile -t candidate_paths < <(
        find "$stage_extract_root" -mindepth 1 ! -type d -printf './%P\n' |
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
    while IFS=$'\t' read -r extra_stage extra_candidate_path; do
        [[ "$extra_stage" == "$stage" ]] || continue
        candidate_paths+=("$extra_candidate_path")
    done < <(tail -n +2 "$extra_paths_path")
    mapfile -t candidate_paths < <(
        printf '%s\n' "${candidate_paths[@]}" | awk 'NF' | LC_ALL=C sort -u
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
        extract_candidate_bytes "$stage_extract_root" "$stage" "$candidate_path" "$extracted_path"
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
    rm -rf -- "$stage_extract_root"
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
Stages with no tracked license candidate: $missing_candidate_count
All enabled dependency licenses reviewed: false
Corresponding source complete: false
Public release gate satisfied: false
EOF

printf 'Extracted license/notice candidates for %s source-bearing stage(s); %s require review and %s have no tracked candidate.\n' \
    "$source_stage_count" "$pending_review_count" "$missing_candidate_count"
