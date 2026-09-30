# FFmpeg distribution and corresponding-source audit

This is the authoritative living checklist for SPLICR Studio's Windows FFmpeg distribution. It is
an engineering record, not legal advice. The public-release gate remains open until every unchecked
item below has evidence.

## Binary identity

- Provider: BtbN/FFmpeg-Builds
- Release: `autobuild-2026-09-24-14-14`
- Asset: `ffmpeg-n9.0.2-3-ga5923073bf-win64-lgpl-shared-9.0.zip`
- Asset SHA-256: `735bae484ba2c3342bfb34df477b9c6b0f43f9819f4d2fde011be293ee1b6517`
- Reported FFmpeg version: `n9.0.2-3-ga5923073bf-20260924`
- FFmpeg commit: `a5923073bfd8f25b7300d93af3f8e690174ebd30`
- BtbN recipe commit: `20ad148c3b69a862b061eb7e6cc7b61d896bcfef`
- OpenH264 recipe commit: `8b2d28faade10d74d99ac80e199aef664c9c5a3b`

The machine-readable lock is
[`ffmpeg-source-lock.json`](../packaging/windows/ffmpeg-source-lock.json). The packaged
`BUILD_INFO.txt` remains authoritative for the actual configure line and library versions.

## FFmpeg checklist mapping

The upstream FFmpeg legal page says its checklist is one suggested path rather than legal advice.
It requires, among other things, a build without `--enable-gpl`/`--enable-nonfree`, dynamic FFmpeg
library linkage, exact corresponding source, build instructions/configuration, source hosted beside
the binary, visible attribution/source links, and a repeated review for LGPL libraries compiled
into FFmpeg.

- [x] The recorded configure line omits `--enable-gpl` and `--enable-nonfree`.
- [x] The Windows package uses the normally named shared FFmpeg DLLs and does not rename them.
- [x] `BUILD_INFO.txt` preserves the exact reported configure line and versions.
- [x] The exact binary asset URL and SHA-256 are pinned and verified before packaging.
- [x] The FFmpeg, OpenH264, and BtbN recipe commits are pinned with verified archive hashes.
- [x] `prepare-ffmpeg-source-audit.ps1` creates a repeatable, hash-verified primary-source audit kit, and
  `test-ffmpeg-source-audit.ps1` rejects missing/hash-mismatched sources or any false completeness
  claim.
- [ ] Generate the exact enabled BtbN dependency graph for target `win64`, variant `lgpl-shared`,
  add-in `9.0`, and archive every enabled external dependency source at its recipe-pinned revision.
- [ ] Record the applicable license and notice for every enabled dependency, including libraries
  statically incorporated into FFmpeg's shared DLLs.
- [ ] Rebuild from the archived sources or otherwise verify that the source set and instructions
  correspond to the distributed binaries. Record any BtbN-applied patches as `changes.diff` or
  equivalent patch files.
- [ ] Produce the final archive only after its manifest sets
  `all_enabled_external_dependency_sources_included`, `corresponding_source_complete`, and
  `public_release_gate_satisfied` to true following review.
- [ ] Host the final corresponding-source archive on the same release/download server as the
  Windows binaries and preserve it for the required distribution period.
- [ ] Put the required FFmpeg/LGPL attribution and direct source link on every public SPLICR download
  page and in the application's About/legal surface.
- [ ] Confirm release terms do not prohibit reverse engineering for LGPL debugging/relinking.
- [ ] Review codec patent/licensing implications separately; LGPL compliance does not answer patent
  questions.

## Current audit-only kit

Run from the repository root with PowerShell 7:

```powershell
pwsh .\packaging\windows\prepare-ffmpeg-source-audit.ps1 -Version 0.1.0
pwsh .\packaging\windows\test-ffmpeg-source-audit.ps1 -Version 0.1.0
```

For repeatable/offline testing, pass `-ArchiveDirectory` containing the three filenames in the
source lock. The output is intentionally named
`SPLICR-Studio-<version>-FFmpeg-primary-source-audit.zip`. Its manifest explicitly says it is
incomplete, so it cannot be mistaken for the final corresponding-source archive. A separate
`-SHA256.txt` sidecar authenticates the outer audit archive.

## Decision point

The current full-featured BtbN build enables a broad dependency graph, which makes a complete source
and notice bundle comparatively large. Two acceptable paths remain:

1. Collect, verify, review, and publish that full dependency source graph; or
2. replace the package binary with a reproducibly built, capability-tested FFmpeg configuration
   whose external dependency set is deliberately smaller, then redo this checklist against it.

The second path must preserve SPLICR's verified Convert, Audiogram, finishing, probing, H.264/AAC,
and supported input-format behavior. It is not acceptable to reduce the application's promised
capabilities merely to simplify licensing.

Primary references:

- https://ffmpeg.org/legal.html
- https://ffmpeg.org/download.html
- https://github.com/BtbN/FFmpeg-Builds
