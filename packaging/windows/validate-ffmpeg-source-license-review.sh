#!/usr/bin/env bash
set -euo pipefail

if [[ $# -gt 2 ]]; then
    echo "usage: $0 [REVIEW_FILE [THIRD_PARTY_NOTICES_FILE]]" >&2
    exit 2
fi

script_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
graph_root="$script_root/ffmpeg-source-graph"
review_path="${1:-$script_root/ffmpeg-source-license-review.tsv}"
revisions_path="$graph_root/source-revisions.tsv"
stages_path="$graph_root/enabled-stages.txt"
notices_path="${2:-$script_root/THIRD_PARTY_NOTICES.md}"

for required in "$review_path" "$revisions_path" "$stages_path" "$notices_path"; do
    [[ -f "$required" ]] || { echo "Required review input not found: $required" >&2; exit 1; }
done

expected_header=$'stage\tlocator_variable\trevision\tarchive_sha256\tcandidate_path\tcandidate_sha256\tcandidate_final_newline\tspdx_expression\tbinary_notice_requirement\tnotice_anchor\treview_status\treview_notes'
[[ "$(head -n 1 "$review_path")" == "$expected_header" ]] || {
    echo "Unexpected FFmpeg source license review header" >&2
    exit 1
}

reviewed_count=0
declare -A seen_records=()

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
    candidate_sha256 candidate_final_newline spdx_expression binary_notice_requirement \
    notice_anchor review_status review_notes extra; do
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
    [[ -n "$spdx_expression" && "$spdx_expression" != *$'\t'* ]] || {
        echo "Review row is missing an SPDX expression: $stage" >&2
        exit 1
    }
    [[ "$binary_notice_requirement" == "required" || "$binary_notice_requirement" == "not-required" ]] || {
        echo "Review row has an unresolved binary notice requirement: $stage" >&2
        exit 1
    }
    if [[ "$binary_notice_requirement" == "required" ]]; then
        [[ -n "$notice_anchor" ]] || {
            echo "Required binary notice has no package-notice anchor: $stage" >&2
            exit 1
        }
        grep -Fq "$notice_anchor" "$notices_path" || {
            echo "Required binary notice is absent from THIRD_PARTY_NOTICES.md: $stage" >&2
            exit 1
        }
        if [[ "$candidate_final_newline" == "yes" ]]; then
            notice_sha256="$(extract_notice_block "$notice_anchor" | sha256sum | cut -d' ' -f1)"
        else
            notice_sha256="$(extract_notice_block "$notice_anchor" | head -c -1 | sha256sum | cut -d' ' -f1)"
        fi
        [[ "$notice_sha256" == "$candidate_sha256" ]] || {
            echo "Packaged binary notice text differs from the reviewed source candidate: $stage" >&2
            exit 1
        }
    else
        [[ "$notice_anchor" == "-" ]] || {
            echo "A not-required binary notice must use '-' as its anchor: $stage" >&2
            exit 1
        }
    fi
    [[ "$review_status" == "reviewed" && -n "$review_notes" ]] || {
        echo "Review row is not documented as reviewed: $stage" >&2
        exit 1
    }

    record_key="$stage|$locator_variable|$revision|$candidate_sha256"
    [[ -z "${seen_records[$record_key]:-}" ]] || {
        echo "Duplicate FFmpeg source license review record: $record_key" >&2
        exit 1
    }
    seen_records[$record_key]=1
    reviewed_count=$((reviewed_count + 1))
done < "$review_path"

[[ "$reviewed_count" -gt 0 ]] || { echo "FFmpeg source license review contains no records" >&2; exit 1; }
source_locator_count="$(($(wc -l < "$revisions_path") - 1))"
printf 'Validated %s reviewed FFmpeg source license record(s) against %s pinned source locator(s); full-graph review remains open.\n' \
    "$reviewed_count" "$source_locator_count"
