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
- [x] The exact BtbN generator for target `win64`, variant `lgpl-shared`, add-in `9.0` emitted 90
  enabled build stages and 92 source locators, each with an exact Git commit, tag, or SVN revision.
  The tracked graph preserves the ordered stage list, source locator/revision table, and raw
  source-fetch commands; `test-ffmpeg-source-graph.ps1` rejects a changed count, unpinned revision,
  duplicate/missing stage, or accidentally enabled libx264/libx265.
- [x] `collect-ffmpeg-source-graph.sh` verifies each selected recipe's generated fetch command
  against that graph and plans or collects resumable, normalized per-stage archives with the
  BtbN downloader image pinned by digest. `test-ffmpeg-source-collector.sh` covers the complete
  90-stage plan, one-stage selection, unknown-stage rejection, and recipe-tamper rejection. This is
  collection machinery, not evidence that the full collection has run.
- [x] A real single-stage acceptance run pulled that exact image digest, fetched OpenH264 commit
  `8b2d28faade10d74d99ac80e199aef664c9c5a3b`, produced a valid 118,568,280-byte archive with
  `LICENSE` and the expected detached Git `HEAD`, passed every emitted checksum, retained both
  fail-closed status flags, and reused the same archive on a second run. The ignored evidence is in
  `.test-runs/ffmpeg-source-collector-runtime`; this proves collector execution/resume, not the full
  graph.
- [x] `inventory-ffmpeg-source-licenses.sh` now checksum-validates a collection, extracts
  filename-based license/notice candidates without writing archive paths to disk, and emits a
  deterministic candidate inventory plus a fail-closed review template. Its synthetic acceptance
  test covers multi-candidate, missing-candidate, no-source, stale-output, checksum-tamper, and
  schema-tamper cases. The real OpenH264 archive yielded its exact `LICENSE` with SHA-256
  `dd5c1c96…`; the tracked review records `BSD-2-Clause` and the binary notice obligation, while
  a unique hash anchor proves the complete notice is present in the packaged third-party notice,
  and full-graph and codec patent review remain explicitly open.
- [x] The collector accepts ordered repeated `--stage` arguments for bounded batches, records the
  batch scope, reuses valid prior archives, and enforces a configurable 12 GiB free-space reserve
  on both the output filesystem and collector workspace before uncached work. Plan acceptance
  rejects duplicates, invalid reserves, and an intentionally impossible reserve. A real combined
  run reused OpenH264, libogg, and zlib without downloading them again.
- [x] A second incremental real-source run fetched libogg commit
  `06a5e0262cdc28aa4ae6797627a783b5010440f0` into a 500,976-byte normalized archive. The inventory
  found `./COPYING` at SHA-256 `d2ab5758…`; the tracked review records `BSD-3-Clause`, and CI proves
  its complete required binary notice is present through a unique hash anchor.
- [x] A third incremental run fetched zlib commit
  `767c4c947852e143f582c85f14cf573411df1b35` into a 2,854,928-byte normalized archive. Review of
  the root `./LICENSE` (`e32ff4e0…`) records `Zlib` and no mandatory binary notice; the source archive
  retains that notice. The root recipe runs zlib's own configure/make targets, so unrelated
  `contrib/dotzlib` and `contrib/minizip` candidate licenses are not classified as shipped code.
- [x] A bounded four-stage run fetched mingw-std-threads, libopus, libunibreak, and snappy at their
  graph-pinned revisions, then reconciled all six detected candidates. Required BSD notices are
  reproduced exactly; the Opus collaboration/patent-reference notice is retained without claiming
  a patent determination; and snappy testdata terms are classified not-built because the recipe
  disables tests, benchmarks, and fuzzing. Successful fetch output is now concise, while a failed
  stage retains and tails a bounded diagnostic log.
- [x] A separate TwoLAME run brought the reviewed total to eight of 92 source locators and 12
  candidates: eight shipped licenses, one supplemental notice, and three recipe-proven not-built
  candidates. Because TwoLAME is LGPL-2.1-or-later and FFmpeg's bundled license is LGPLv3, the
  package now downloads and hash-verifies the exact pinned TwoLAME `COPYING` file through
  `ffmpeg-packaged-license-files.tsv`. The build and artifact acceptance harness require that exact
  file and reject a changed SHA-256.
- [x] A bounded AMF, libffi, libpng, and OpenJPEG run brought the reviewed total to 12 of 92 source
  locators and 27 candidates: 12 shipped licenses, one supplemental notice, and 14 recipe-proven
  not-built candidates. AMF's MIT license and OpenJPEG's BSD-2-Clause license are now exact
  URL/revision/SHA-256-bound package files; their upstream patent-rights caveats remain visible and
  are not presented as patent clearance. libffi's root MIT notice is hash-anchored in the combined
  notices, while its MSVC/Sun/test build-tool license is excluded by the actual GNU cross-build.
  libpng's root `libpng-2.0` license is recorded, and its CI/workflow/contrib candidates are excluded
  from the root static-library build based on the pinned recipe and source metadata. Real
  `0.1.0-dev.7` portable and installed-package acceptance independently verified all three
  manifest-bound dependency licenses by revision and SHA-256.
- [x] A bounded dav1d, FFTW3, FriBidi, and libsamplerate run brought the reviewed total to 16 of 92
  source locators and 35 candidates: 14 shipped licenses, two supplemental notices, 14 not-built
  candidates, and five build-only/not-shipped candidates. Exact dav1d BSD and AOMedia patent-license
  files plus FriBidi's LGPL-2.1-or-later file are manifest-bound package payloads. The packaged
  FFmpeg configuration proves dav1d and FriBidi are enabled, while FFTW3 and libsamplerate are only
  built into the toolchain and are not incorporated: libfftw3/libsamplerate are absent and their
  librubberband consumer is disabled. The review schema now distinguishes that state from source
  trees that recipes never build. Real `0.1.0-dev.8` portable and installed-package acceptance verified
  all six manifest-bound dependency files by exact revision and SHA-256, including both dav1d files
  and FriBidi's license.
- [x] The ffnvcodec embedded-header review brought coverage to 19 of 92 locators and 50 candidates:
  19 shipped licenses, two supplemental notices, 24 not-built candidates, and five build-only/not-
  shipped candidates. A tracked supplemental-path manifest makes nonstandard license-bearing files
  part of deterministic inventory and negative testing. All five MIT-bearing primary headers used by
  FFmpeg 9 are exact URL/revision/SHA-256-bound package files; ten sdk/13.0 and sdk/11.1 header
  candidates are recipe-proven not built for the packaged FFmpeg 9 variant. Real `0.1.0-dev.9`
  portable and installed-package acceptance verified all 11 manifest-bound dependency files.
- [x] A bounded Game Music Emu, GMP, Kvazaar, and LCEVCdec run brought coverage to 23 of 92
  locators and 69 candidates: 24 shipped licenses, five supplemental notices, 35 not-built
  candidates, and five build-only/not-shipped candidates. The package manifest now binds exact GME
  LGPL and emu2413 MIT terms, GMP's LGPLv3 supplement plus incorporated GPLv3 and preserved GPLv2
  alternative, Kvazaar's BSD notice, and LCEVCdec's Clear BSD license plus required no-patent-
  license notice. Recipe options prove GME's GPL MAME alternative, Kvazaar's test/distribution
  helpers, and LCEVCdec's utility/platform dependencies are not built. The legal-file fetcher
  independently downloaded and SHA-256-verified all eight new manifest files. Real `0.1.0-dev.10`
  portable and installed-package acceptance independently verified all 19 manifest-bound dependency
  files by exact revision and SHA-256, plus the existing media and lifecycle checks.
- [x] A bounded libvpx, libwebp, libzmq, and OpenCORE AMR run brought coverage to 27 of 92 locators
  and 87 candidates: 30 shipped licenses, nine supplemental notices, 43 not-built candidates, and
  five build-only/not-shipped candidates. Ten new manifest-bound files preserve both WebM BSD terms
  and patent grants, libvpx's compiled x86inc ISC notice, libzmq's MPL-2.0 terms and compiled wepoll
  BSD notice, and OpenCORE's Apache license, attribution notice, and explicit no-patent-rights
  disclaimer. Exact recipe paths exclude libvpx test/example dependencies and libzmq SHA-1, Unity,
  and Debian-packaging candidates. The downloader independently fetched and SHA-256-verified all
  29 manifest files; immutable GitHub mirror URLs avoid SourceForge's intermittent browser challenge
  while exact hashes retain correspondence to the collected source. Real `0.1.0-dev.11` portable
  and installed-package acceptance independently verified every one of those 29 files by exact
  revision and SHA-256, plus the existing media and lifecycle checks.
- [x] A bounded libudfread, oneVPL, PCRE2, and pixman run brought coverage to 31 of 92 locators and
  108 candidates: 34 shipped licenses, ten supplemental notices, 59 not-built candidates, and five
  build-only/not-shipped candidates. Five new manifest-bound files preserve libudfread's LGPL-2.1,
  oneVPL's MIT, PCRE2's BSD-3-Clause-with-exception plus its upstream licence pointer, and pixman's
  MIT terms. Exact recipe/source paths exclude 14 oneVPL examples, its test-only googletest, and
  PCRE2's unused CMake scripts; PCRE2 JIT defaults off, so absent SLJIT is not incorporated. The
  downloader independently fetched and SHA-256-verified all 34 manifest files. Byte-identical,
  immutable GitHub mirror commits avoid Code.Videolan and GitLab automated-client challenges while
  exact hashes retain correspondence to the collected source. Real `0.1.0-dev.12` portable and
  installed-package acceptance independently verified every one of those 34 files by exact revision
  and SHA-256, plus the existing media and lifecycle checks.
- [x] A bounded Little CMS, OpenAL Soft, SoX Resampler, and uavs3d run brought coverage to 35 of 92
  locators and 123 candidates: 44 shipped licenses, eleven supplemental notices, 61 not-built
  candidates, and seven build-only/not-shipped candidates. Eleven new manifest-bound files preserve
  Little CMS's MIT terms; OpenAL Soft's LGPL, PFFFT, Apache, BSD, fmt, and GSL terms; SoXR's LGPL,
  project declaration, and embedded PFFFT notice; and uavs3d's BSD terms. A supplemental inventory
  path prevents SoXR's source-embedded PFFFT notice from escaping filename-only discovery. Exact
  recipe/source and packaged-binary evidence excludes disabled jpgicc/LSR tests and classifies the
  separately built GPL-3.0 Little CMS plugins as unincorporated, unshipped static archives. The
  downloader independently fetched and SHA-256-verified all 45 manifest files; the SoXR entries use
  an immutable GitHub mirror at the identical SourceForge commit. Real `0.1.0-dev.13` portable and
  installed-package acceptance independently verified every one of those 45 files by exact revision
  and SHA-256, plus the existing media and lifecycle checks. AVS3 patent review remains open.
- [x] A bounded Brotli, JPEG XL, Mbed TLS, and librist run brought coverage to 39 of 92 locators and
  140 candidates: 51 shipped licenses, twelve supplemental notices, 68 not-built candidates, and
  nine build-only/not-shipped candidates. Eight new manifest-bound files preserve Brotli's MIT
  notice; JPEG XL's BSD terms and patent grant; Highway's Apache and BSD terms; Mbed TLS and
  TF-PSA-Crypto's dual Apache/GPL terms; and librist's BSD notice. Exact recipe/source evidence
  excludes disabled JPEG XL tools/tests/examples/benchmarks, experimental ML-DSA, and librist's
  vendored Mbed TLS. Mbed TLS's two framework submodules are build-time-only. The manifest validator
  now accepts graph-pinned semantic release tags such as `v4.2.0` while rejecting unsafe arbitrary
  refs, and the PowerShell downloader independently fetched and SHA-256-verified all 53 manifest
  files; librist uses a commit-pinned, byte-identical GitHub mirror because the canonical host returns
  an anti-bot page to automated clients. Exact-batch, tracked, synthetic, and negative reconciliation
  suites pass. Real `0.1.0-dev.14` portable and installed-package acceptance independently verified
  all 53 files plus the existing media and lifecycle checks. Hosted browser run `36761944917` passed
  all six Studio journeys in 44.2 seconds on the acceptance-record commit. Codec patent review
  remains open.
- [ ] Execute the tracked fetch commands and archive every enabled external dependency source at its
  recipe-pinned revision.
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

## Full dependency source collection

Use a Linux host with Bash and Docker. First obtain and hash-verify the exact BtbN recipe archive
listed in `ffmpeg-source-lock.json`, then extract it. A plan-only run performs all recipe-to-graph
checks without pulling the relatively large downloader image:

```bash
bash packaging/windows/collect-ffmpeg-source-graph.sh \
  /path/to/FFmpeg-Builds-20ad148c3b69a862b061eb7e6cc7b61d896bcfef \
  /path/to/collection \
  --plan-only

bash packaging/windows/test-ffmpeg-source-collector.sh \
  /path/to/FFmpeg-Builds-20ad148c3b69a862b061eb7e6cc7b61d896bcfef
```

Remove `--plan-only` for the resumable full collection. Repeat `--stage` with exact paths from
`enabled-stages.txt` for an ordered bounded batch. `--min-free-gib` changes the default 12 GiB
reserve; set it to zero only in a separately capacity-controlled environment. A successful download
writes a plan, per-stage archives, a source manifest, and checksums, while continuing to state that
corresponding-source and public-release gates are false. License/notice review and binary
correspondence still follow.

After any partial or full collection, generate the deterministic candidate inventory and validate
the independently tracked reviewed rows:

```bash
bash packaging/windows/inventory-ffmpeg-source-licenses.sh /path/to/collection
bash packaging/windows/test-ffmpeg-source-license-inventory.sh
bash packaging/windows/test-ffmpeg-source-license-review.sh
```

`license-review-template.tsv` is generated evidence, not an approval. Promote a row into
`ffmpeg-source-license-review.tsv` only after checking the extracted text, pinned source identity,
SPDX expression, and binary notice requirement. The validator rejects source identities outside the
pinned graph, malformed checksums, unresolved notice requirements, duplicate evidence, and
undocumented reviews. Pass a generated `license-candidate-inventory.tsv` as the validator's third
optional input to require an exact reviewed disposition for every detected candidate. A disposition
may identify a shipped license or document, with recipe evidence, that a source subtree is not
built. It does not claim that a filename search found every applicable term.

Primary references:

- https://ffmpeg.org/legal.html
- https://ffmpeg.org/download.html
- https://github.com/BtbN/FFmpeg-Builds
