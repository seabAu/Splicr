#!/usr/bin/env bash
set -euo pipefail

if [[ $# -gt 4 ]]; then
    echo "usage: $0 [REVIEW_FILE [THIRD_PARTY_NOTICES_FILE [CANDIDATE_INVENTORY_FILE [PACKAGED_LICENSE_FILES]]]]" >&2
    exit 2
fi

script_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
graph_root="$script_root/ffmpeg-source-graph"
review_path="${1:-$script_root/ffmpeg-source-license-review.tsv}"
revisions_path="$graph_root/source-revisions.tsv"
stages_path="$graph_root/enabled-stages.txt"
notices_path="${2:-$script_root/THIRD_PARTY_NOTICES.md}"
inventory_path="${3:-}"
packaged_licenses_path="${4:-$script_root/ffmpeg-packaged-license-files.tsv}"

for required in "$review_path" "$revisions_path" "$stages_path" "$notices_path" "$packaged_licenses_path"; do
    [[ -f "$required" ]] || { echo "Required review input not found: $required" >&2; exit 1; }
done
if [[ -n "$inventory_path" && ! -f "$inventory_path" ]]; then
    echo "Candidate inventory not found: $inventory_path" >&2
    exit 1
fi

expected_packaged_licenses_header=$'package_path\tsource_url\trevision\tsha256'
[[ "$(head -n 1 "$packaged_licenses_path")" == "$expected_packaged_licenses_header" ]] || {
    echo "Unexpected packaged license file manifest header" >&2
    exit 1
}
declare -A packaged_license_hashes=()
declare -A packaged_license_revisions=()
declare -A packaged_license_references=()
while IFS=$'\t' read -r package_path source_url package_revision package_sha256 extra; do
    [[ "$package_path" != "package_path" ]] || continue
    [[ -z "${extra:-}" && "$package_path" =~ ^ffmpeg/[A-Za-z0-9._-]+$ && \
        "$source_url" == https://* && "$package_revision" =~ ^[0-9a-f]{40}$ && \
        "$package_sha256" =~ ^[0-9a-f]{64}$ ]] || {
        echo "Invalid packaged license file manifest row: $package_path" >&2
        exit 1
    }
    [[ -z "${packaged_license_hashes[$package_path]:-}" ]] || {
        echo "Duplicate packaged license file manifest path: $package_path" >&2
        exit 1
    }
    packaged_license_hashes["$package_path"]="$package_sha256"
    packaged_license_revisions["$package_path"]="$package_revision"
done < "$packaged_licenses_path"

expected_header=$'stage\tlocator_variable\trevision\tarchive_sha256\tcandidate_path\tcandidate_sha256\tcandidate_final_newline\tcandidate_disposition\tspdx_expression\tbinary_notice_requirement\tnotice_anchor\treview_status\treview_notes'
[[ "$(head -n 1 "$review_path")" == "$expected_header" ]] || {
    echo "Unexpected FFmpeg source license review header" >&2
    exit 1
}

reviewed_count=0
shipped_license_count=0
shipped_notice_count=0
not_built_count=0
build_only_count=0
declare -A seen_records=()
declare -A inventory_records=()
declare -A inventory_stages=()
declare -A reviewed_inventory_records=()
inventory_candidate_count=0

if [[ -n "$inventory_path" ]]; then
    expected_inventory_header=$'stage\tsource_status\tarchive_name\tarchive_sha256\tcandidate_path\tcandidate_sha256\textracted_path'
    [[ "$(head -n 1 "$inventory_path")" == "$expected_inventory_header" ]] || {
        echo "Unexpected license candidate inventory header" >&2
        exit 1
    }
    while IFS=$'\t' read -r inventory_stage source_status archive_name inventory_archive_sha256 \
        inventory_candidate_path inventory_candidate_sha256 extracted_path extra; do
        [[ "$inventory_stage" != "stage" ]] || continue
        [[ -z "${extra:-}" ]] || {
            echo "Candidate inventory row has unexpected extra fields: $inventory_stage" >&2
            exit 1
        }
        [[ -n "$inventory_stage" ]] || { echo "Candidate inventory row has no stage" >&2; exit 1; }
        inventory_stages["$inventory_stage"]=1
        [[ -n "$inventory_candidate_path" ]] || continue
        inventory_key="$inventory_stage|$inventory_archive_sha256|$inventory_candidate_path|$inventory_candidate_sha256"
        [[ -z "${inventory_records[$inventory_key]:-}" ]] || {
            echo "Duplicate candidate inventory record: $inventory_key" >&2
            exit 1
        }
        inventory_records["$inventory_key"]=1
        inventory_candidate_count=$((inventory_candidate_count + 1))
    done < "$inventory_path"
    [[ "$inventory_candidate_count" -gt 0 ]] || {
        echo "Candidate inventory contains no filename-based candidates" >&2
        exit 1
    }
fi

extract_notice_block() {
    local anchor="$1"
    awk -v anchor="$anchor" '
        index($0, anchor) { anchored = 1; next }
        anchored && $0 == "```text" { in_block = 1; next }
        in_block && $0 == "```" { closed = 1; exit }
        in_block { print }
        END { if (!anchored || !in_block || !closed) exit 1 }
    ' "$notices_path"
}

while IFS=$'\t' read -r stage locator_variable revision archive_sha256 candidate_path \
    candidate_sha256 candidate_final_newline candidate_disposition spdx_expression \
    binary_notice_requirement notice_anchor review_status review_notes extra; do
    [[ "$stage" != "stage" ]] || continue
    [[ -z "${extra:-}" ]] || { echo "Review row has unexpected extra fields: $stage" >&2; exit 1; }
    [[ -n "$stage" && -n "$locator_variable" && -n "$revision" ]] || {
        echo "Review row is missing source identity fields" >&2
        exit 1
    }
    grep -Fxq "$stage" "$stages_path" || {
        echo "Review row names a stage outside the enabled graph: $stage" >&2
        exit 1
    }
    awk -F '\t' -v stage="$stage" -v variable="$locator_variable" -v revision="$revision" '
        NR > 1 && $1 == stage && $2 == variable && $5 == revision { found = 1 }
        END { exit(found ? 0 : 1) }
    ' "$revisions_path" || {
        echo "Review source identity differs from the pinned graph: $stage $locator_variable $revision" >&2
        exit 1
    }
    [[ "$archive_sha256" =~ ^[0-9a-f]{64}$ ]] || {
        echo "Review row has an invalid archive checksum: $stage" >&2
        exit 1
    }
    [[ "$candidate_path" == ./* && "$candidate_path" != *$'\t'* ]] || {
        echo "Review row has an invalid candidate path: $stage" >&2
        exit 1
    }
    [[ "$candidate_sha256" =~ ^[0-9a-f]{64}$ ]] || {
        echo "Review row has an invalid candidate checksum: $stage" >&2
        exit 1
    }
    [[ "$candidate_final_newline" == "yes" || "$candidate_final_newline" == "no" ]] || {
        echo "Review row has an invalid candidate newline marker: $stage" >&2
        exit 1
    }
    [[ "$candidate_disposition" == "shipped-license" || \
        "$candidate_disposition" == "shipped-notice" || \
        "$candidate_disposition" == "not-built" || \
        "$candidate_disposition" == "build-only" ]] || {
        echo "Review row has an unresolved candidate disposition: $stage $candidate_path" >&2
        exit 1
    }
    if [[ "$candidate_disposition" == "not-built" || "$candidate_disposition" == "build-only" ]]; then
        [[ "$spdx_expression" == "-" && "$binary_notice_requirement" == "not-applicable" && \
            "$notice_anchor" == "-" ]] || {
            echo "A non-shipped candidate must not make shipped-license or notice claims: $stage $candidate_path" >&2
            exit 1
        }
        if [[ "$candidate_disposition" == "not-built" ]]; then
            not_built_count=$((not_built_count + 1))
        else
            build_only_count=$((build_only_count + 1))
        fi
    elif [[ "$candidate_disposition" == "shipped-license" ]]; then
        [[ -n "$spdx_expression" && "$spdx_expression" != "-" && "$spdx_expression" != *$'\t'* ]] || {
            echo "Shipped review row is missing an SPDX expression: $stage" >&2
            exit 1
        }
        [[ "$binary_notice_requirement" == "required" || "$binary_notice_requirement" == "not-required" ]] || {
            echo "Review row has an unresolved binary notice requirement: $stage" >&2
            exit 1
        }
        shipped_license_count=$((shipped_license_count + 1))
    else
        [[ "$spdx_expression" == "-" && \
            ( "$binary_notice_requirement" == "informational" || "$binary_notice_requirement" == "required" ) && \
            -n "$notice_anchor" && "$notice_anchor" != "-" ]] || {
            echo "A shipped supplemental notice must be required or informational and hash-anchored: $stage $candidate_path" >&2
            exit 1
        }
        shipped_notice_count=$((shipped_notice_count + 1))
    fi
    if [[ "$candidate_disposition" == "shipped-notice" || \
        "$candidate_disposition" == "shipped-license" && "$binary_notice_requirement" == "required" ]]; then
        [[ -n "$notice_anchor" ]] || {
            echo "Required binary notice has no package-notice anchor: $stage" >&2
            exit 1
        }
        if [[ "$notice_anchor" == file:* ]]; then
            packaged_path="${notice_anchor#file:}"
            [[ -n "${packaged_license_hashes[$packaged_path]:-}" ]] || {
                echo "Required binary notice has no packaged license manifest record: $stage $packaged_path" >&2
                exit 1
            }
            [[ "${packaged_license_revisions[$packaged_path]}" == "$revision" ]] || {
                echo "Packaged license revision differs from the reviewed source: $stage $packaged_path" >&2
                exit 1
            }
            grep -Fq "$packaged_path" "$notices_path" || {
                echo "Packaged license file is absent from THIRD_PARTY_NOTICES.md: $stage $packaged_path" >&2
                exit 1
            }
            notice_sha256="${packaged_license_hashes[$packaged_path]}"
            packaged_license_references["$packaged_path"]=$((
                ${packaged_license_references[$packaged_path]:-0} + 1
            ))
        else
            grep -Fq "$notice_anchor" "$notices_path" || {
                echo "Required binary notice is absent from THIRD_PARTY_NOTICES.md: $stage" >&2
                exit 1
            }
            if [[ "$candidate_final_newline" == "yes" ]]; then
                notice_sha256="$(extract_notice_block "$notice_anchor" | sha256sum | cut -d' ' -f1)"
            else
                notice_sha256="$(extract_notice_block "$notice_anchor" | head -c -1 | sha256sum | cut -d' ' -f1)"
            fi
        fi
        [[ "$notice_sha256" == "$candidate_sha256" ]] || {
            echo "Packaged binary notice text differs from the reviewed source candidate: $stage" >&2
            exit 1
        }
    elif [[ "$candidate_disposition" == "shipped-license" ]]; then
        [[ "$notice_anchor" == "-" ]] || {
            echo "A not-required binary notice must use '-' as its anchor: $stage" >&2
            exit 1
        }
    fi
    [[ "$review_status" == "reviewed" && -n "$review_notes" ]] || {
        echo "Review row is not documented as reviewed: $stage" >&2
        exit 1
    }

    record_key="$stage|$locator_variable|$revision|$candidate_path|$candidate_sha256"
    [[ -z "${seen_records[$record_key]:-}" ]] || {
        echo "Duplicate FFmpeg source license review record: $record_key" >&2
        exit 1
    }
    seen_records[$record_key]=1
    if [[ -n "$inventory_path" && -n "${inventory_stages[$stage]:-}" ]]; then
        inventory_key="$stage|$archive_sha256|$candidate_path|$candidate_sha256"
        [[ -n "${inventory_records[$inventory_key]:-}" ]] || {
            echo "Reviewed candidate is absent from the supplied inventory: $stage $candidate_path" >&2
            exit 1
        }
        reviewed_inventory_records["$inventory_key"]=1
    fi
    reviewed_count=$((reviewed_count + 1))
done < "$review_path"

[[ "$reviewed_count" -gt 0 ]] || { echo "FFmpeg source license review contains no records" >&2; exit 1; }
for packaged_path in "${!packaged_license_hashes[@]}"; do
    [[ -n "${packaged_license_references[$packaged_path]:-}" ]] || {
        echo "Packaged license file has no reviewed source candidate: $packaged_path" >&2
        exit 1
    }
done
if [[ -n "$inventory_path" ]]; then
    for inventory_key in "${!inventory_records[@]}"; do
        [[ -n "${reviewed_inventory_records[$inventory_key]:-}" ]] || {
            echo "Candidate inventory record has no reviewed disposition: $inventory_key" >&2
            exit 1
        }
    done
fi
source_locator_count="$(($(wc -l < "$revisions_path") - 1))"
printf 'Validated %s reviewed FFmpeg source candidate(s): %s shipped license(s), %s supplemental notice(s), %s not built, %s build-only/not shipped; %s pinned source locator(s) exist and full-graph review remains open.\n' \
    "$reviewed_count" "$shipped_license_count" "$shipped_notice_count" "$not_built_count" "$build_only_count" \
    "$source_locator_count"
if [[ -n "$inventory_path" ]]; then
    printf 'All %s filename-based candidate(s) in the supplied inventory have an exact reviewed disposition.\n' \
        "$inventory_candidate_count"
fi
