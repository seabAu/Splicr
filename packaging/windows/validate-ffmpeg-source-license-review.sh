#!/usr/bin/env bash
set -euo pipefail

if [[ $# -gt 6 ]]; then
    echo "usage: $0 [REVIEW_FILE [THIRD_PARTY_NOTICES_FILE [CANDIDATE_INVENTORY_FILE [PACKAGED_LICENSE_FILES [PACKAGED_LICENSE_COMPANIONS [SOURCE_LOCATOR_ALIASES]]]]]]" >&2
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
packaged_companions_path="${5:-$script_root/ffmpeg-packaged-license-companions.tsv}"
locator_aliases_path="${6:-$script_root/ffmpeg-source-locator-aliases.tsv}"

for required in "$review_path" "$revisions_path" "$stages_path" "$notices_path" "$packaged_licenses_path" "$packaged_companions_path" "$locator_aliases_path"; do
    [[ -f "$required" ]] || { echo "Required review input not found: $required" >&2; exit 1; }
done
if [[ -n "$inventory_path" && ! -f "$inventory_path" ]]; then
    echo "Candidate inventory not found: $inventory_path" >&2
    exit 1
fi

expected_packaged_licenses_header=$'package_path\tsource_url\trevision\tsha256\tcontent_encoding'
[[ "$(head -n 1 "$packaged_licenses_path")" == "$expected_packaged_licenses_header" ]] || {
    echo "Unexpected packaged license file manifest header" >&2
    exit 1
}
declare -A packaged_license_hashes=()
declare -A packaged_license_revisions=()
declare -A packaged_license_references=()
while IFS=$'\t' read -r package_path source_url package_revision package_sha256 content_encoding extra; do
    [[ "$package_path" != "package_path" ]] || continue
    [[ -z "${extra:-}" && "$package_path" =~ ^ffmpeg/[A-Za-z0-9._-]+$ && \
        "$source_url" == https://* && \
        "$package_revision" =~ ^([0-9a-f]{40}|[1-9][0-9]*|v[0-9]+(\.[0-9]+){1,3}([._-][0-9A-Za-z]+)*|openssl-[0-9]+(\.[0-9]+){2,3})$ && \
        "$package_sha256" =~ ^[0-9a-f]{64}$ && \
        "$content_encoding" =~ ^(base64)?$ ]] || {
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

expected_packaged_companions_header=$'package_path\tstage\tlocator_variable\trevision\tcandidate_path\tcandidate_sha256\tcompanion_spdx\treview_notes'
[[ "$(head -n 1 "$packaged_companions_path")" == "$expected_packaged_companions_header" ]] || {
    echo "Unexpected packaged license companion manifest header" >&2
    exit 1
}
declare -A companion_review_keys=()
declare -A companion_spdx_terms=()
declare -A companion_review_hits=()
companion_count=0
while IFS=$'\t' read -r package_path companion_stage companion_locator_variable companion_revision \
    companion_candidate_path companion_candidate_sha256 companion_spdx review_notes extra; do
    [[ "$package_path" != "package_path" ]] || continue
    [[ -z "${extra:-}" && -n "$review_notes" && \
        -n "${packaged_license_hashes[$package_path]:-}" && \
        "$companion_candidate_path" == ./* && \
        "$companion_candidate_sha256" =~ ^[0-9a-f]{64}$ && \
        "$companion_spdx" =~ ^[A-Za-z0-9.-]+$ ]] || {
        echo "Invalid packaged license companion manifest row: $package_path" >&2
        exit 1
    }
    grep -Fxq "$companion_stage" "$stages_path" || {
        echo "Packaged license companion names a stage outside the enabled graph: $package_path" >&2
        exit 1
    }
    awk -F '\t' -v stage="$companion_stage" -v variable="$companion_locator_variable" \
        -v revision="$companion_revision" '
        NR > 1 && $1 == stage && $2 == variable && $5 == revision { found = 1 }
        END { exit(found ? 0 : 1) }
    ' "$revisions_path" || {
        echo "Packaged license companion source identity differs from the pinned graph: $package_path" >&2
        exit 1
    }
    [[ -z "${companion_review_keys[$package_path]:-}" ]] || {
        echo "Duplicate packaged license companion path: $package_path" >&2
        exit 1
    }
    companion_review_keys["$package_path"]="$companion_stage|$companion_locator_variable|$companion_revision|$companion_candidate_path|$companion_candidate_sha256"
    companion_spdx_terms["$package_path"]="$companion_spdx"
    companion_count=$((companion_count + 1))
done < "$packaged_companions_path"

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
declare -A reviewed_locators=()
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
    reviewed_locators["$stage|$locator_variable|$revision"]=1
    for companion_path in "${!companion_review_keys[@]}"; do
        [[ "${companion_review_keys[$companion_path]}" == "$record_key" ]] || continue
        [[ "$candidate_disposition" == "shipped-license" ]] || {
            echo "Packaged companion license is not attached to a shipped-license candidate: $companion_path" >&2
            exit 1
        }
        [[ "$spdx_expression" == *"${companion_spdx_terms[$companion_path]}"* ]] || {
            echo "Packaged companion SPDX term is absent from the reviewed expression: $companion_path" >&2
            exit 1
        }
        grep -Fq "$companion_path" "$notices_path" || {
            echo "Packaged companion license file is absent from THIRD_PARTY_NOTICES.md: $companion_path" >&2
            exit 1
        }
        companion_review_hits["$companion_path"]=1
        packaged_license_references["$companion_path"]=$((
            ${packaged_license_references[$companion_path]:-0} + 1
        ))
    done
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

expected_locator_aliases_header=$'stage\talias_locator_variable\tcanonical_locator_variable\trevision\treview_status\treview_notes'
[[ "$(head -n 1 "$locator_aliases_path")" == "$expected_locator_aliases_header" ]] || {
    echo "Unexpected FFmpeg source locator alias header" >&2
    exit 1
}
declare -A locator_alias_targets=()
locator_alias_count=0
while IFS=$'\t' read -r alias_stage alias_locator_variable canonical_locator_variable alias_revision \
    alias_review_status alias_review_notes extra; do
    [[ "$alias_stage" != "stage" ]] || continue
    [[ -z "${extra:-}" && "$alias_locator_variable" =~ ^[A-Z][A-Z0-9_]*$ && \
        "$canonical_locator_variable" =~ ^[A-Z][A-Z0-9_]*$ && \
        "$alias_locator_variable" != "$canonical_locator_variable" && \
        "$alias_revision" =~ ^[0-9a-f]{40}$ && \
        "$alias_review_status" == "reviewed" && -n "$alias_review_notes" ]] || {
        echo "Invalid FFmpeg source locator alias row: $alias_stage $alias_locator_variable" >&2
        exit 1
    }
    grep -Fxq "$alias_stage" "$stages_path" || {
        echo "Source locator alias names a stage outside the enabled graph: $alias_stage" >&2
        exit 1
    }
    alias_graph_record="$(awk -F '\t' -v stage="$alias_stage" -v variable="$alias_locator_variable" '
        NR > 1 && $1 == stage && $2 == variable { print $3 "\t" $5; exit }
    ' "$revisions_path")"
    canonical_graph_record="$(awk -F '\t' -v stage="$alias_stage" -v variable="$canonical_locator_variable" '
        NR > 1 && $1 == stage && $2 == variable { print $3 "\t" $5; exit }
    ' "$revisions_path")"
    [[ -n "$alias_graph_record" && -n "$canonical_graph_record" ]] || {
        echo "Source locator alias is absent from the pinned graph: $alias_stage $alias_locator_variable" >&2
        exit 1
    }
    IFS=$'\t' read -r alias_url alias_graph_revision <<< "$alias_graph_record"
    IFS=$'\t' read -r canonical_url canonical_graph_revision <<< "$canonical_graph_record"
    [[ "$alias_graph_revision" == "$alias_revision" && \
        "$canonical_graph_revision" == "$alias_revision" && \
        "$alias_url" != "$canonical_url" ]] || {
        echo "Source locator alias does not bind distinct transports of one pinned revision: $alias_stage $alias_locator_variable" >&2
        exit 1
    }
    alias_key="$alias_stage|$alias_locator_variable|$alias_revision"
    canonical_key="$alias_stage|$canonical_locator_variable|$alias_revision"
    [[ -z "${locator_alias_targets[$alias_key]:-}" ]] || {
        echo "Duplicate FFmpeg source locator alias: $alias_key" >&2
        exit 1
    }
    [[ -n "${reviewed_locators[$canonical_key]:-}" ]] || {
        echo "Source locator alias target has no reviewed candidates: $canonical_key" >&2
        exit 1
    }
    [[ -z "${reviewed_locators[$alias_key]:-}" ]] || {
        echo "Source locator alias duplicates directly reviewed candidates: $alias_key" >&2
        exit 1
    }
    locator_alias_targets["$alias_key"]="$canonical_key"
    locator_alias_count=$((locator_alias_count + 1))
done < "$locator_aliases_path"
for alias_key in "${!locator_alias_targets[@]}"; do
    canonical_key="${locator_alias_targets[$alias_key]}"
    [[ -z "${locator_alias_targets[$canonical_key]:-}" ]] || {
        echo "Chained FFmpeg source locator aliases are not allowed: $alias_key" >&2
        exit 1
    }
done

for companion_path in "${!companion_review_keys[@]}"; do
    [[ -n "${companion_review_hits[$companion_path]:-}" ]] || {
        echo "Packaged companion license has no exact reviewed source candidate: $companion_path" >&2
        exit 1
    }
done
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
validated_locator_count="$((${#reviewed_locators[@]} + locator_alias_count))"
[[ "$validated_locator_count" -le "$source_locator_count" ]] || {
    echo "Validated source locator count exceeds the pinned graph" >&2
    exit 1
}
printf 'Validated %s reviewed FFmpeg source candidate(s): %s shipped license(s), %s supplemental notice(s), %s not built, %s build-only/not shipped; %s of %s pinned source locator(s) have exact review or validated aliases and full-graph review remains open.\n' \
    "$reviewed_count" "$shipped_license_count" "$shipped_notice_count" "$not_built_count" "$build_only_count" \
    "$validated_locator_count" "$source_locator_count"
printf 'Validated %s commit-identical source locator alias(es).\n' "$locator_alias_count"
printf 'Validated %s external companion license mapping(s).\n' "$companion_count"
if [[ -n "$inventory_path" ]]; then
    printf 'All %s filename-based candidate(s) in the supplied inventory have an exact reviewed disposition.\n' \
        "$inventory_candidate_count"
fi
