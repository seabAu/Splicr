#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "usage: $0 BTBN_REPOSITORY" >&2
    exit 2
fi

script_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
collector="$script_root/collect-ffmpeg-source-graph.sh"
btbn_root="$(cd "$1" && pwd)"
work_root="$(mktemp -d)"
trap 'rm -rf -- "$work_root"' EXIT

full_output="$work_root/full"
bash "$collector" "$btbn_root" "$full_output" --plan-only

stage_count="$(($(wc -l < "$full_output/collection-plan.tsv") - 1))"
[[ "$stage_count" -eq 90 ]] || { echo "Expected 90 planned stages, found $stage_count" >&2; exit 1; }
fetch_count="$(tail -n +2 "$full_output/collection-plan.tsv" | cut -f3 | grep -c '^fetch$')"
no_source_count="$(tail -n +2 "$full_output/collection-plan.tsv" | cut -f3 | grep -c '^no-external-source$')"
[[ "$fetch_count" -eq 85 ]] || { echo "Expected 85 source-bearing stages, found $fetch_count" >&2; exit 1; }
[[ "$no_source_count" -eq 5 ]] || { echo "Expected 5 no-source stages, found $no_source_count" >&2; exit 1; }
duplicate_archives="$(tail -n +2 "$full_output/collection-plan.tsv" | cut -f4 | sed '/^$/d' | sort | uniq -d)"
[[ -z "$duplicate_archives" ]] || { echo "Plan contains duplicate archive names" >&2; exit 1; }
grep -Fq 'State: planned-only' "$full_output/COLLECTION_INFO.txt"
grep -Fq 'Scope: full-graph' "$full_output/COLLECTION_INFO.txt"
grep -Fq 'Pending source-bearing stage count: 85' "$full_output/COLLECTION_INFO.txt"
grep -Fq 'Tracked Cargo source supplement count: 1' "$full_output/COLLECTION_INFO.txt"
grep -Fq 'Minimum free-space reserve: 12 GiB' "$full_output/COLLECTION_INFO.txt"
grep -Fq 'Corresponding source complete: false' "$full_output/COLLECTION_INFO.txt"
grep -Fq 'Public release gate satisfied: false' "$full_output/COLLECTION_INFO.txt"
grep -Fq \
    'ghcr.io/btbn/ffmpeg-builds/base@sha256:ce3051e936d2f67b550efad8c5f07118a14e08f4e15b98e56ce14003e60d54cc' \
    "$full_output/COLLECTION_INFO.txt"
[[ ! -e "$full_output/.collector-run-plan.tsv" ]]

rav1e_supplement="$script_root/ffmpeg-cargo-source-supplements.tsv"
grep -Fxq $'scripts.d/50-rav1e.sh\tSCRIPT_REPO\t31435de9d76fddd38f6dcc31d4014574cebb2092\tx86_64-pc-windows-gnu\tyes\tdefault\tcc=1.4.7,find-msvc-tools=0.1.13,shlex@2.0.1=2.0.1\t14a4b2ae596569e83e40a3431ffc4b210dd872e333969ddb18ce895f7b19d7c7\t275' \
    "$rav1e_supplement"

tampered_supplement="$work_root/tampered-cargo-supplements.tsv"
cp "$rav1e_supplement" "$tampered_supplement"
sed -i \
    's/31435de9d76fddd38f6dcc31d4014574cebb2092/0000000000000000000000000000000000000000/' \
    "$tampered_supplement"
if SPLICR_CARGO_SUPPLEMENTS_PATH="$tampered_supplement" \
    bash "$collector" "$btbn_root" "$work_root/tampered-supplement" \
        --stage scripts.d/50-rav1e.sh --plan-only >/dev/null 2>&1; then
    echo "Collector accepted Cargo supplement metadata that differs from the pinned graph" >&2
    exit 1
fi

repeat_output="$work_root/repeat"
bash "$collector" "$btbn_root" "$repeat_output" --plan-only >/dev/null
cmp "$full_output/collection-plan.tsv" "$repeat_output/collection-plan.tsv"
cmp "$full_output/COLLECTION_INFO.txt" "$repeat_output/COLLECTION_INFO.txt"

partial_output="$work_root/partial"
bash "$collector" "$btbn_root" "$partial_output" \
    --stage scripts.d/50-openh264.sh --plan-only
partial_count="$(($(wc -l < "$partial_output/collection-plan.tsv") - 1))"
[[ "$partial_count" -eq 1 ]] || { echo "Expected one planned stage, found $partial_count" >&2; exit 1; }
grep -Fq 'Scope: single-stage' "$partial_output/COLLECTION_INFO.txt"
grep -Fq $'scripts.d/50-openh264.sh\t' "$partial_output/collection-plan.tsv"

batch_output="$work_root/batch"
bash "$collector" "$btbn_root" "$batch_output" \
    --stage scripts.d/25-libogg.sh \
    --stage scripts.d/20-zlib.sh \
    --min-free-gib 8 \
    --plan-only
batch_count="$(($(wc -l < "$batch_output/collection-plan.tsv") - 1))"
[[ "$batch_count" -eq 2 ]] || { echo "Expected two planned batch stages, found $batch_count" >&2; exit 1; }
grep -Fq 'Scope: stage-batch' "$batch_output/COLLECTION_INFO.txt"
grep -Fq 'Selected stage count: 2' "$batch_output/COLLECTION_INFO.txt"
grep -Fq 'Minimum free-space reserve: 8 GiB' "$batch_output/COLLECTION_INFO.txt"
[[ "$(sed -n '2p' "$batch_output/collection-plan.tsv" | cut -f1)" == 'scripts.d/25-libogg.sh' ]]
[[ "$(sed -n '3p' "$batch_output/collection-plan.tsv" | cut -f1)" == 'scripts.d/20-zlib.sh' ]]

if bash "$collector" "$btbn_root" "$work_root/duplicate" \
    --stage scripts.d/25-libogg.sh \
    --stage scripts.d/25-libogg.sh \
    --plan-only >/dev/null 2>&1; then
    echo "Collector accepted a duplicate selected stage" >&2
    exit 1
fi

if bash "$collector" "$btbn_root" "$work_root/invalid-reserve" \
    --stage scripts.d/25-libogg.sh \
    --min-free-gib invalid \
    --plan-only >/dev/null 2>&1; then
    echo "Collector accepted an invalid free-space reserve" >&2
    exit 1
fi

if bash "$collector" "$btbn_root" "$work_root/impossible-reserve" \
    --stage scripts.d/25-libogg.sh \
    --min-free-gib 999999 >/dev/null 2>&1; then
    echo "Collector ignored an impossible free-space reserve" >&2
    exit 1
fi

if bash "$collector" "$btbn_root" "$work_root/unknown" \
    --stage scripts.d/not-enabled.sh --plan-only >/dev/null 2>&1; then
    echo "Collector accepted a stage outside the enabled graph" >&2
    exit 1
fi

tampered_root="$work_root/tampered-recipes"
cp -a "$btbn_root" "$tampered_root"
sed -i \
    's/8b2d28faade10d74d99ac80e199aef664c9c5a3b/0000000000000000000000000000000000000000/' \
    "$tampered_root/scripts.d/50-openh264.sh"
if bash "$collector" "$tampered_root" "$work_root/tampered" \
    --stage scripts.d/50-openh264.sh --plan-only >/dev/null 2>&1; then
    echo "Collector accepted a recipe that differs from the tracked source graph" >&2
    exit 1
fi

printf 'FFmpeg source collector plan passed (%s stages plus negative cases).\n' "$stage_count"
