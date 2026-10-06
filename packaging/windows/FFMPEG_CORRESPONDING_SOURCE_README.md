# SPLICR Studio FFmpeg corresponding-source candidate

This directory contains the source, build recipes, patches, review records, and offline-build
evidence for the FFmpeg/FFprobe bundle distributed with SPLICR Studio.

The source set is complete for the pinned 90-stage BtbN build graph and has been reconciled against
all 1,684 detected license/notice candidates. It also includes the exact FFmpeg source, the pinned
BtbN recipe snapshot, each collected external dependency source, the recipe patch set, SPLICR's
offline-build patch, and the authenticated logs from a network-disabled rebuild.

The generated `SOURCE_MANIFEST.json` deliberately keeps `public_release_gate_satisfied` false.
This is a release candidate until the publisher assigns a stable public HTTPS location, verifies
the published archive digest, places the required attribution and direct source link beside the
binary download and in the application, confirms release terms preserve LGPL debugging/relinking
rights, and completes the separate codec-patent review.

## Rebuild outline

1. Verify `SOURCE-SHA256SUMS.txt` from the root of this directory.
2. Start from `primary-sources/btbn-build-scripts.zip` at the commit recorded in
   `SOURCE_MANIFEST.json`.
3. Populate the recipe cache from the normalized archives in `dependency-sources/stages`, using
   `dependency-sources/collection-manifest.tsv` as the stage-to-archive map.
4. Apply the patch files in `patches` and use `build-evidence/Dockerfile.offline.prepared`.
5. Build the dependency image and final FFmpeg compiler container with networking disabled. The
   exact prior commands and output are preserved in the two build logs.
6. Build the exact FFmpeg source in `primary-sources/ffmpeg-source.zip`, then compare the compiler,
   configure arguments, library ABI versions, and smoke-test formats with
   `tooling/ffmpeg-correspondence-evidence.json`.

The collected sources remain modifiable. Rebuilding the normally named shared FFmpeg DLL set and
substituting it in SPLICR Studio's private media-tool directory is the relinking path for statically
incorporated LGPL components.
