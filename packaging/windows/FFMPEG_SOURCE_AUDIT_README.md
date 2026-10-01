# SPLICR Studio FFmpeg primary-source audit kit

This archive is an **audit aid, not a complete corresponding-source distribution**.

It pins and verifies the exact FFmpeg source commit, OpenH264 source commit, and BtbN build-recipe
snapshot associated with SPLICR Studio's current Windows FFmpeg binary. It also preserves the
binary's reported configure line, download provenance, exact 90-stage enabled build graph,
recipe-pinned source revisions, and raw source-fetch commands. `SOURCE_MANIFEST.json` records every
hash and keeps `public_release_gate_satisfied` set to `false`.

Why the gate remains open: the BtbN asset named `lgpl-shared` upstream was configured with numerous
external libraries, some statically incorporated into the FFmpeg DLLs. Review has confirmed that
enabled Chromaprint statically incorporates GPL-2.0-or-later FFTW3, so the current media DLLs must
be treated as GPL-covered rather than LGPL-only. The complete applicable dependency source set,
notices, build correspondence, and final hosted download URL have not yet been assembled into this
kit.

Before public distribution, complete the checklist in `docs/FFMPEG_DISTRIBUTION.md`. Do not rename
this archive to “corresponding source” or link it as complete source while the manifest's release
gate remains false.
