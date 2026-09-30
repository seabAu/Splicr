#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 || $# -gt 5 ]]; then
    echo "usage: $0 BTBN_REPOSITORY OUTPUT_DIRECTORY [TARGET] [VARIANT] [ADDIN]" >&2
    exit 2
fi

btbn_root="$(cd "$1" && pwd)"
output_root="$2"
target="${3:-win64}"
variant="${4:-lgpl-shared}"
addin="${5:-9.0}"

mkdir -p "$output_root"
output_root="$(cd "$output_root" && pwd)"

cd "$btbn_root"
./generate.sh "$target" "$variant" "$addin"

mapfile -t stages < <(
    sed -nE 's/^ENV SELF="([^"]+)".*/\1/p' Dockerfile
)

if [[ ${#stages[@]} -eq 0 ]]; then
    echo "BtbN generator produced no enabled stages" >&2
    exit 1
fi

printf '%s\n' "${stages[@]}" > "$output_root/enabled-stages.txt"
printf 'stage\tlocator_variable\tlocator\trevision_variable\trevision\n' \
    > "$output_root/source-revisions.tsv"
: > "$output_root/source-commands.txt"

for stage in "${stages[@]}"; do
    (
        source util/vars.sh "$target" "$variant" "$addin"
        source util/dl_functions.sh
        source "$stage"

        printf '### %s\n' "$stage" >> "$output_root/source-commands.txt"
        ffbuild_dockerdl >> "$output_root/source-commands.txt"
        printf '\n' >> "$output_root/source-commands.txt"

        while IFS= read -r locator_variable; do
            suffix="${locator_variable##*[!0-9]}"
            if [[ "$suffix" == "$locator_variable" ]]; then
                suffix=""
            fi
            revision_variable="SCRIPT_COMMIT${suffix}"
            locator="${!locator_variable-}"
            revision="${!revision_variable-}"
            if [[ -z "$revision" ]]; then
                revision_variable="SCRIPT_REV${suffix}"
                revision="${!revision_variable-}"
            fi
            printf '%s\t%s\t%s\t%s\t%s\n' \
                "$stage" "$locator_variable" "$locator" "$revision_variable" "$revision" \
                >> "$output_root/source-revisions.tsv"
        done < <(
            compgen -A variable | grep -E '^SCRIPT_(REPO|MIRROR)[0-9]*$' | sort -u || true
        )
    )
done

cat > "$output_root/GRAPH_INFO.txt" <<EOF
Generator: BtbN/FFmpeg-Builds generate.sh
Target: $target
Variant: $variant
Add-in: $addin
Enabled stage count: ${#stages[@]}
EOF

printf 'Generated %s enabled source stages in %s\n' "${#stages[@]}" "$output_root"
