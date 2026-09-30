#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat >&2 <<'EOF'
usage: collect-ffmpeg-source-graph.sh BTBN_REPOSITORY OUTPUT_DIRECTORY [options]

Options:
  --stage STAGE       Collect or plan one exact enabled stage instead of the full graph. Repeat to
                      select an ordered batch.
  --min-free-gib GIB  Keep at least this many GiB free before each uncached stage (default: 12).
  --plan-only         Verify the recipe and write a deterministic plan without using Docker.
EOF
    exit 2
}

if [[ $# -lt 2 ]]; then
    usage
fi

btbn_root="$1"
output_root="$2"
shift 2

selected_stages=()
minimum_free_gib=12
plan_only=false
while [[ $# -gt 0 ]]; do
    case "$1" in
    --stage)
        [[ $# -ge 2 && -n "$2" ]] || usage
        for selected_stage in "${selected_stages[@]}"; do
            [[ "$selected_stage" != "$2" ]] || {
                echo "Stage was selected more than once: $2" >&2
                exit 1
            }
        done
        selected_stages+=("$2")
        shift 2
        ;;
    --min-free-gib)
        [[ $# -ge 2 && "$2" =~ ^[0-9]+$ ]] || usage
        minimum_free_gib="$2"
        shift 2
        ;;
    --plan-only)
        plan_only=true
        shift
        ;;
    *)
        usage
        ;;
    esac
done

script_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
graph_root="$script_root/ffmpeg-source-graph"
runner_image="ghcr.io/btbn/ffmpeg-builds/base@sha256:ce3051e936d2f67b550efad8c5f07118a14e08f4e15b98e56ce14003e60d54cc"

[[ -d "$btbn_root" ]] || { echo "BtbN repository not found: $btbn_root" >&2; exit 1; }
btbn_root="$(cd "$btbn_root" && pwd)"
mkdir -p "$output_root"
output_root="$(cd "$output_root" && pwd)"

for required in \
    "$btbn_root/util/dl_functions.sh" \
    "$graph_root/enabled-stages.txt" \
    "$graph_root/source-commands.txt"; do
    [[ -f "$required" ]] || { echo "Required file not found: $required" >&2; exit 1; }
done

mapfile -t enabled_stages < <(sed '/^[[:space:]]*$/d' "$graph_root/enabled-stages.txt")
if [[ ${#enabled_stages[@]} -eq 0 ]]; then
    echo "Tracked source graph contains no enabled stages" >&2
    exit 1
fi

stages=("${enabled_stages[@]}")
if [[ ${#selected_stages[@]} -gt 0 ]]; then
    stages=()
    for selected_stage in "${selected_stages[@]}"; do
        found=false
        for stage in "${enabled_stages[@]}"; do
            if [[ "$stage" == "$selected_stage" ]]; then
                found=true
                break
            fi
        done
        $found || {
            echo "Stage is not in the tracked enabled graph: $selected_stage" >&2
            exit 1
        }
        stages+=("$selected_stage")
    done
fi

minimum_free_kib=$((minimum_free_gib * 1024 * 1024))

available_kib() {
    local path="$1"
    df -Pk "$path" | awk 'NR == 2 { print $4 }'
}

require_free_space() {
    local path="$1"
    local label="$2"
    local free_kib
    free_kib="$(available_kib "$path")"
    [[ "$free_kib" =~ ^[0-9]+$ ]] || {
        echo "Could not determine free space for $label: $path" >&2
        exit 1
    }
    if (( free_kib < minimum_free_kib )); then
        printf 'Source collection requires a %s GiB free-space reserve; %s has %.2f GiB free.\n' \
            "$minimum_free_gib" "$label" "$(awk -v kib="$free_kib" 'BEGIN { print kib / 1024 / 1024 }')" >&2
        exit 1
    fi
}

tracked_command() {
    local stage="$1"
    awk -v header="### $stage" '
        $0 == header { capture = 1; next }
        capture && /^### / { exit }
        capture && NF { print }
    ' "$graph_root/source-commands.txt"
}

recipe_command() {
    local stage="$1"
    (
        cd "$btbn_root"
        source util/dl_functions.sh
        source "$stage"
        ffbuild_dockerdl
    )
}

plan_path="$output_root/collection-plan.tsv"
runner_plan_path="$output_root/.collector-run-plan.tsv"
info_path="$output_root/COLLECTION_INFO.txt"
printf 'stage\tcommand_sha256\tsource_status\tarchive_name\n' > "$plan_path"
: > "$runner_plan_path"

source_stage_count=0
for stage in "${stages[@]}"; do
    [[ -f "$btbn_root/$stage" ]] || { echo "Recipe stage not found: $stage" >&2; exit 1; }
    expected="$(tracked_command "$stage")"
    actual="$(recipe_command "$stage")"
    if [[ "$actual" != "$expected" ]]; then
        echo "Recipe fetch command differs from the tracked graph: $stage" >&2
        exit 1
    fi

    command_sha256="$(printf '%s\n' "$actual" | sha256sum | cut -d' ' -f1)"
    slug="${stage%.sh}"
    slug="${slug//\//__}"
    if [[ -z "$actual" ]]; then
        printf '%s\t%s\tno-external-source\t\n' "$stage" "$command_sha256" >> "$plan_path"
        continue
    fi

    archive_name="${slug}_${command_sha256}.tar.xz"
    printf '%s\t%s\tfetch\t%s\n' "$stage" "$command_sha256" "$archive_name" >> "$plan_path"
    printf '%s\t%s\t%s\t%s\n' "$stage" "$slug" "$command_sha256" "$archive_name" \
        >> "$runner_plan_path"
    source_stage_count=$((source_stage_count + 1))
done

pending_stage_count=0
while IFS=$'\t' read -r stage slug command_sha256 archive_name; do
    [[ -n "$stage" ]] || continue
    archive_path="$output_root/stages/$archive_name"
    if ! [[ -s "$archive_path" ]] || ! xz -t "$archive_path" 2>/dev/null; then
        pending_stage_count=$((pending_stage_count + 1))
    fi
done < "$runner_plan_path"

collection_scope="full-graph"
if [[ ${#selected_stages[@]} -eq 1 ]]; then
    collection_scope="single-stage"
elif [[ ${#selected_stages[@]} -gt 1 ]]; then
    collection_scope="stage-batch"
fi
collection_state="planned-only"

write_info() {
    cat > "$info_path" <<EOF
SPLICR Studio FFmpeg dependency source collection
State: $collection_state
Scope: $collection_scope
Runner image: $runner_image
Tracked enabled stage count: ${#enabled_stages[@]}
Selected stage count: ${#stages[@]}
Selected source-bearing stage count: $source_stage_count
Pending source-bearing stage count: $pending_stage_count
Minimum free-space reserve: $minimum_free_gib GiB
Corresponding source complete: false
Public release gate satisfied: false
EOF
}

write_info
if $plan_only; then
    rm -f "$runner_plan_path"
    printf 'Verified source collection plan for %s stage(s) in %s\n' \
        "${#stages[@]}" "$output_root"
    exit 0
fi

if [[ "$pending_stage_count" -gt 0 && "$minimum_free_kib" -gt 0 ]]; then
    require_free_space "$output_root" "output filesystem"
fi
command -v docker >/dev/null 2>&1 || { echo "Docker is required for source collection" >&2; exit 1; }
mkdir -p "$output_root/stages"

work_root="$(mktemp -d)"
trap 'rm -rf -- "$work_root"' EXIT
worker_path="$work_root/collect-stage-sources.sh"
cat > "$worker_path" <<'WORKER'
#!/usr/bin/env bash
set -euo pipefail

while IFS=$'\t' read -r stage slug expected_sha archive_name; do
    [[ -n "$stage" ]] || continue
    source /btbn/util/dl_functions.sh
    source "/btbn/$stage"
    command_text="$(ffbuild_dockerdl)"
    actual_sha="$(printf '%s\n' "$command_text" | sha256sum | cut -d' ' -f1)"
    if [[ "$actual_sha" != "$expected_sha" ]]; then
        echo "Container fetch command hash mismatch: $stage" >&2
        exit 1
    fi

    target="/output/stages/$archive_name"
    if [[ -s "$target" ]] && xz -t "$target"; then
        echo "Reusing $archive_name"
        continue
    fi
    rm -f "$target" "$target.tmp"

    if [[ "$SPLICR_MIN_FREE_KIB" -gt 0 ]]; then
        for filesystem in /output /tmp; do
            free_kib="$(df -Pk "$filesystem" | awk 'NR == 2 { print $4 }')"
            [[ "$free_kib" =~ ^[0-9]+$ ]] || {
                echo "Could not determine free space inside the collector: $filesystem" >&2
                exit 1
            }
            if (( free_kib < SPLICR_MIN_FREE_KIB )); then
                echo "Free-space reserve reached before collecting $stage on $filesystem" >&2
                exit 1
            fi
        done
    fi

    stage_work="$(mktemp -d)"
    (
        trap 'rm -rf -- "$stage_work"' EXIT
        cd "$stage_work"
        log_root="/output/.collector-logs"
        log_path="$log_root/$slug.log"
        mkdir -p "$log_root"
        if ! (
            set -e
            eval "$command_text"
        ) > "$log_path.tmp" 2>&1; then
            mv "$log_path.tmp" "$log_path.failed"
            echo "Source fetch failed for $stage; retained diagnostic log: $log_path.failed" >&2
            tail -n 100 "$log_path.failed" >&2
            exit 1
        fi
        rm -f "$log_path.tmp"
        echo "Fetched $stage"
        tar --sort=name --mtime='@0' --owner=0 --group=0 --numeric-owner \
            -I 'xz -T1 -9e' -cpf "$target.tmp" .
        mv "$target.tmp" "$target"
    )
done < /output/.collector-run-plan.tsv
WORKER
chmod +x "$worker_path"

uid_args=()
if ! docker info -f '{{println .SecurityOptions}}' 2>/dev/null | grep -q rootless; then
    uid_args=(-u "$(id -u):$(id -g)")
fi

docker run --rm "${uid_args[@]}" \
    -e "SPLICR_MIN_FREE_KIB=$minimum_free_kib" \
    -v "$btbn_root:/btbn:ro" \
    -v "$output_root:/output" \
    -v "$work_root:/collector:ro" \
    "$runner_image" \
    bash /collector/collect-stage-sources.sh

manifest_path="$output_root/collection-manifest.tsv"
checksums_path="$output_root/COLLECTION-SHA256SUMS.txt"
printf 'stage\tcommand_sha256\tsource_status\tarchive_name\tarchive_sha256\n' > "$manifest_path"
: > "$checksums_path"

while IFS=$'\t' read -r stage command_sha256 source_status archive_name; do
    [[ "$stage" != "stage" ]] || continue
    if [[ "$source_status" == "no-external-source" ]]; then
        printf '%s\t%s\t%s\t\t\n' "$stage" "$command_sha256" "$source_status" \
            >> "$manifest_path"
        continue
    fi
    archive_path="$output_root/stages/$archive_name"
    [[ -s "$archive_path" ]] || { echo "Collected archive missing: $archive_name" >&2; exit 1; }
    xz -t "$archive_path"
    archive_sha256="$(sha256sum "$archive_path" | cut -d' ' -f1)"
    printf '%s\t%s\tcollected\t%s\t%s\n' \
        "$stage" "$command_sha256" "$archive_name" "$archive_sha256" >> "$manifest_path"
    printf '%s  stages/%s\n' "$archive_sha256" "$archive_name" >> "$checksums_path"
done < "$plan_path"

manifest_sha256="$(sha256sum "$manifest_path" | cut -d' ' -f1)"
plan_sha256="$(sha256sum "$plan_path" | cut -d' ' -f1)"
printf '%s  collection-manifest.tsv\n' "$manifest_sha256" >> "$checksums_path"
printf '%s  collection-plan.tsv\n' "$plan_sha256" >> "$checksums_path"

collection_state="sources-collected-unreviewed"
write_info
rm -f "$runner_plan_path"
printf 'Collected source material for %s source-bearing stage(s) in %s\n' \
    "$source_stage_count" "$output_root"
