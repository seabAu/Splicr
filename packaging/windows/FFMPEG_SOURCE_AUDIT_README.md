# SPLICR Studio FFmpeg primary-source audit kit

This archive is an **audit aid, not a complete corresponding-source distribution**.

It pins and verifies the exact FFmpeg source commit, OpenH264 source commit, and BtbN build-recipe
snapshot associated with SPLICR Studio's current Windows FFmpeg binary. It also preserves the
binary's reported configure line and download provenance. `SOURCE_MANIFEST.json` records every hash
and keeps `public_release_gate_satisfied` set to `false`.

Why the gate remains open: the BtbN LGPL-shared FFmpeg DLLs were configured with numerous external
libraries. Some are statically incorporated into the FFmpeg DLLs. FFmpeg's own compliance checklist
requires the distribution review to be repeated for LGPL external libraries compiled into FFmpeg.
Those dependency source archives, their applicable notices, and the final hosted download URL have
not yet been assembled into this kit.

Before public distribution, complete the checklist in `docs/FFMPEG_DISTRIBUTION.md`. Do not rename
this archive to “corresponding source” or link it as complete source while the manifest's release
gate remains false.
