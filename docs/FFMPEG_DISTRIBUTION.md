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

**Effective-license correction:** `lgpl-shared` is the upstream asset-variant name, not the
effective license of every compiled dependency. The enabled Chromaprint recipe selects static
FFTW3, its pkg-config metadata publishes `-lfftw3`, and FFmpeg resolves dependency metadata with
`--pkg-config-flags=--static`. The distributed `avformat-63.dll` contains FFTW 3.3.11 markers and
imports no FFTW DLL. Because FFTW is GPL-2.0-or-later, this pinned media bundle must be treated as
GPL-covered. Omitting FFmpeg's own `--enable-gpl` flag is therefore necessary but not sufficient to
establish an LGPL-only result. This is an engineering record, not legal advice.

## FFmpeg checklist mapping

The upstream FFmpeg legal page says its checklist is one suggested path rather than legal advice.
Its LGPL path requires, among other things, a build without `--enable-gpl`/`--enable-nonfree`,
dynamic FFmpeg library linkage, exact corresponding source, build instructions/configuration,
source hosted beside the binary, visible attribution/source links, and repeated review of libraries
compiled into FFmpeg. The current transitive FFTW finding means the pinned bundle does not qualify
for that LGPL-only path without replacement.

- [x] The recorded configure line omits `--enable-gpl` and `--enable-nonfree`.
- [x] Transitive static-dependency inspection overrides the misleading upstream variant label:
  Chromaprint + FFTW makes the current media DLLs GPL-covered, and package metadata/tests now state
  and enforce that finding.
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
- [x] A bounded dav1d, FFTW3, FriBidi, and libsamplerate run originally classified both FFTW3 and
  libsamplerate as build-only based on the direct FFmpeg configuration and absent DLLs. The later
  Chromaprint review disproved the FFTW3 half of that inference: Chromaprint selects FFTW3 and
  static pkg-config resolution incorporates it into `avformat-63.dll`. The tracked FFTW records are
  corrected to shipped GPL terms; libsamplerate remains build-only because its only identified
  consumer, librubberband, is disabled. Real `0.1.0-dev.8` acceptance remains valid package evidence
  for the files it checked, but its then-current LGPL-only classification is superseded.
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
- [x] A bounded LV2, Serd, Zix, Sord, Sratom, and Lilv run brought coverage to 45 of 92 locators and
  168 candidates: 58 shipped licenses, twelve supplemental notices, 74 not-built candidates, and
  24 build-only/not-shipped candidates. Seven new manifest-bound files preserve every linked ISC
  notice, including both Zix texts because their copyright ranges differ. Exact recipes disable
  documentation, tools, tests, benchmarks, and Python bindings as applicable; LV2 schema assets and
  build metadata remain only in the intermediate prefix. The inventory now resolves safe relative
  in-archive license symlinks, with deterministic positive coverage and negative escape rejection.
  The downloader independently fetched and SHA-256-verified all 60 manifest files, and exact-batch,
  tracked, synthetic, and negative reconciliation suites pass. Real `0.1.0-dev.15` portable and
  installed-package acceptance independently verified all 60 files plus the existing media and
  lifecycle checks. Hosted browser run `36765143610` passed all six Studio journeys in 43.6 seconds
  on acceptance-record commit `8e33227`.
- [x] A bounded Chromaprint, LAME, Theora, and Vorbis run brought coverage to 49 of 92 locators and
  180 candidates: 63 shipped licenses, fifteen supplemental notices, 81 not-built candidates, and
  21 build-only/not-shipped candidates. Eight new manifest-bound files preserve Chromaprint's
  LGPL/MIT terms, LAME's LGPL terms and guidance, Theora's BSD terms and On2 non-assertion, and
  Vorbis's BSD terms. The same review corrected FFTW3 from build-only to statically incorporated and
  added its GPL-2.0-or-later text and source notice. The package gate now proves Chromaprint/static
  pkg-config enablement, requires exactly one `avformat` DLL with an embedded FFTW marker, rejects a
  separate FFTW DLL, and records the effective GPL status in `SOURCE_INFO.txt`. Exact source-batch,
  tracked, synthetic, and negative reconciliation passed, and all 68 manifest files were fetched
  and hash-verified. A real `0.1.0-dev.16` build passed the tracked package harness on Windows,
  covering checksums, Unicode-path portable smoke, immutable-tree behavior, installation,
  payload parity, all 68 manifest-bound legal files, static-FFTW evidence, OpenH264/AAC MP4,
  uninstall, and user-data preservation. The schema-v2 acceptance record is emitted beside the
  artifacts; hosted-browser evidence remains open before this batch is complete.
- [x] The libxml2, XZ/liblzma, SDL2, and ZVBI batch raised exact coverage to 53 of 92 locators and
  200 candidates: 67 shipped licenses, fifteen supplemental notices, 88 not-built candidates, and
  30 build-only/not-shipped candidates. Exact libxml2 and ZVBI files increased the package manifest
  to 70 hash-verified records. ZVBI's compiled GPL-2.0-only `packet-830.c` and `pdc.c` provide a
  second independent GPL-covered path; SDL2 remains build-only because SPLICR excludes `ffplay.exe`.
  The rebuilt `0.1.0-dev.16` package passed schema-v2 acceptance with all 70 files. Portable:
  184,156,833 bytes, SHA-256 `06bb7d6fe324362a775370cc7925c598fe0e0af3649404ec1886691604fcfc8e`.
  Installer: 119,806,398 bytes, SHA-256
  `fd260b9037468bbe2606010b29c4351ad69b771fc1ea120dfce321db9ac6c0f5`.
- [x] The two-locator GNU libiconv batch raised exact coverage to 55 of 92 locators and 213
  candidates: 69 shipped licenses, eighteen supplemental notices, 88 not-built candidates, and 38
  build-only/not-shipped candidates. The four new exact package files preserve LGPL-2.1 terms and
  the three compiled-source notices, bringing the manifest to 74 hash-verified records. The gnulib
  runtime feeds only the unshipped `iconv` CLI. The rebuilt `0.1.0-dev.16` package passed schema-v2
  lifecycle acceptance under PowerShell 7 with all 74 files. Portable: 179,641,079 bytes, SHA-256
  `416f3872206c9f34e14f181e75c21e65f7eff9cd38ffd33f6523340e9d0e6f7f`. Installer: 119,818,275
  bytes, SHA-256 `421f44ee2eca3ce3c1f4aea6c2f1fdf813cb45c50b8373ab3182a5bc6bc0f34e`.
- [x] The four-locator font stack batch raised exact coverage to 59 of 92 locators and 232
  candidates: 72 shipped licenses, 23 supplemental notices, 93 not-built candidates, and 44
  build-only/not-shipped candidates. Fontconfig, HarfBuzz, and the bootstrap/final FreeType stages
  add nine exact package files, bringing the manifest to 83 hash-verified records. The companion
  manifest binds Fontconfig's separately sourced Unicode-3.0 terms to its reviewed `COPYING`
  candidate. The bounded Python fetcher decodes only explicitly declared Gitiles base64 transport,
  retries transient failures, and still verifies the decoded source bytes against the reviewed
  hashes. The rebuilt `0.1.0-dev.16` package passed schema-v2 lifecycle acceptance under PowerShell
  7 with all 83 files. Portable: 184,202,955 bytes, SHA-256
  `b2dad13acef808cafed5f40b326827b0042e12daf8b011feb0aa3344d821c532`. Installer: 119,829,501
  bytes, SHA-256 `43266d10023515a62264200e8c697b8f1f5febcdae8d99a380bf65de454a61df`.
  Hosted browser run [`36913670670`](https://github.com/seabAu/Splicr/actions/runs/36913670670)
  passed all six Studio journeys in 45.8 seconds on commit `9e3d8ee`.
- [x] The aribb24, libaribcaption, libass, and libbluray batch raised exact coverage to 63 of 92
  locators and 249 candidates: 78 shipped licenses, 28 supplemental notices, 98 not-built
  candidates, and 45 build-only/not-shipped candidates. Nine exact package files bring the legal
  manifest to 92 hash-verified records. Recipe and build-manifest evidence excludes libaribcaption's
  OpenSSL-replaced MD5 body, libass's AArch64 assembly, libbluray's disabled BD-J ASM payload, and
  libbluray's tools-only getopt fallback. The rebuilt `0.1.0-dev.16` package passed schema-v2
  lifecycle acceptance with all 92 files on Windows 10. Portable: 184,241,112 bytes, SHA-256
  `efd590cb5321c3dc1cf62bfb9e88f50c8ed939b989eec26a5beab6fe9eccb854`. Installer: 119,839,389
  bytes, SHA-256 `ed928b4b0e0f54de2c525fcef98abd22f02131b5bc3b428709a38c0d8817c21c`.
  Hosted browser run [`36917251299`](https://github.com/seabAu/Splicr/actions/runs/36917251299)
  passed all six Studio journeys in 41.3 seconds on commit `0575c89`.
- [x] The OpenSSL batch raised exact coverage to 64 of 92 locators and 253 candidates: 79 shipped
  licenses, 28 supplemental notices, 101 not-built candidates, and 45 build-only/not-shipped
  candidates. The exact Apache-2.0 license brings the legal manifest to 93 hash-verified records.
  The pinned media DLL carries the OpenSSL 3.6.4 marker; the pinned media-tool directory contains no
  separate SSL or crypto DLL. The recursively collected cloudflare-quiche and nested BoringSSL
  sources are recipe-proven not built because the stage invokes only OpenSSL's `build_sw` target.
  The rebuilt `0.1.0-dev.16` package passed schema-v2 lifecycle acceptance with all 93 files on
  Windows 10. Portable: 184,245,775 bytes, SHA-256
  `75cae844c1b909cd56bcba8af99529dce9491c8090fcf6ea1d8334747c2a82ae`. Installer: 119,844,402
  bytes, SHA-256 `3c5bfc0b049fb3bd0e0c8a53567fc199d1b8758dbb134c61d518aa52f82200df`.
  Hosted browser run [`36919996114`](https://github.com/seabAu/Splicr/actions/runs/36919996114)
  passed all six Studio journeys in 53.8 seconds on commit `950b0c1`.
- [x] The SVT-AV1, libva, and VVenC batch raised exact coverage to 67 of 92 locators and 262
  candidates: 86 shipped licenses, 29 supplemental notices, 101 not-built candidates, and 46
  build-only/not-shipped candidates. Eight exact package files bring the legal manifest to 101
  hash-verified records, including both SVT-AV1 license families, its AOMedia patent terms and
  incorporated FASTFEAT notice, plus VVenC's bundled nlohmann JSON and SIMDe notices. The rebuilt
  `0.1.0-dev.16` package passed schema-v2 lifecycle acceptance with all 101 files on Windows 10 at
  `2026-10-01T20:38:38.9403150Z`. Portable: 184,254,515 bytes, SHA-256
  `9a235c9a3e764fb512a718036e3fb98bc0edf73d990a8a1ea1ed15386b5f3607`. Installer: 119,848,157
  bytes, SHA-256 `e22916cb52b474451b49e7d7931eddeda3f3465a3f7ff78aada8bcfc1006d9dc`.
  Hosted browser run [`36923571926`](https://github.com/seabAu/Splicr/actions/runs/36923571926)
  passed all six Studio journeys in 44.1 seconds on commit `e76e3e5`. rav1e remains unresolved: its
  recipe performs a time-dependent Cargo update and the full target crate closure must be
  notice-reconciled before promotion.
- [x] The libplacebo batch raised exact coverage to 68 of 92 locators and 283 candidates: 96 shipped
  licenses, 33 supplemental notices, 104 not-built candidates, and 50 build-only/not-shipped
  candidates. Fourteen exact package files bring the legal manifest to 115 hash-verified records.
  The review follows the recursive submodules to their own immutable revisions and packages the
  Vulkan-Headers, fast_float, glad, project, shader, filter, and hashing terms; Jinja and MarkupSafe
  are build-only generators, while the disabled demos and Nuklear subtree are not built. The rebuilt
  `0.1.0-dev.16` package passed schema-v2 lifecycle acceptance with all 115 files on Windows 10 at
  `2026-10-01T21:01:26.4972742Z`. Portable: 184,313,166 bytes, SHA-256
  `aba0200ad839480fb8b1354d93b4d4f06f5a390de2c325ca1aab330651a6bf25`. Installer: 119,873,387
  bytes, SHA-256 `4899de203fd0ea1007e679df9959112868f70a2b44b24bed25a7955208b9854c`.
  Hosted browser run [`36927179317`](https://github.com/seabAu/Splicr/actions/runs/36927179317)
  passed all six Studio journeys in 42.1 seconds on implementation commit `13ff415`.
- [x] The OpenCL-Headers, OpenCL-ICD-Loader, and OpenMPT batch raised exact coverage to 71 of 92
  locators and 328 candidates: 101 shipped licenses, 37 supplemental notices, 140 not-built
  candidates, and 50 build-only/not-shipped candidates. Nine exact package files bring the legal
  manifest to 124 hash-verified records. The review packages both OpenCL Apache-2.0 texts,
  OpenMPT's BSD-3-Clause terms, minimp3's CC0 terms, the selected BSD branch for dual-licensed
  utility headers, and four compiled public-domain provenance notices. The rebuilt `0.1.0-dev.16`
  package passed schema-v2 lifecycle acceptance with all 124 files on Windows 10 at
  `2026-10-01T21:31:28.4930829Z`. Portable: 184,352,521 bytes, SHA-256
  `d534fe19b863baf808d368693a26b9a9fda6391b3cb4e70fab8dbaa4e04b6b4f`. Installer: 119,891,255
  bytes, SHA-256 `f08f504073be7a42bac4b7b29a0d6e9764a1d9d35548aa1ebcfa8516acddb816`.
  Hosted browser run [`36929574347`](https://github.com/seabAu/Splicr/actions/runs/36929574347)
  passed all six Studio journeys in 43.9 seconds on implementation commit `b18f7d4`.
- [x] The Vulkan-Headers, Vulkan-Shim-Loader, Shaderc/glslang/SPIRV-Tools, SPIRV-Cross, and
  standalone SPIRV-Headers batch raised exact coverage to 77 of 92 locators and 371 candidates:
  123 shipped licenses, 43 supplemental notices, 148 not-built candidates, and 57
  build-only/not-shipped candidates. Twenty-eight exact files bring the legal manifest to 152
  hash-verified records. The review follows Shaderc's pinned dependency closure and packages the
  generated parser's GPL-3.0-or-later terms together with the Bison exception, plus every retained
  Apache, BSD, AML, MIT, and generated-header notice. The rebuilt `0.1.0-dev.16` package passed
  schema-v2 lifecycle acceptance with all 152 files on Windows 10 at
  `2026-10-01T21:55:20.5653230Z`. Portable: 184,579,105 bytes, SHA-256
  `2df198360b03a74ebd21617d10d35091022bf444946295e5901c87bdd1e67f8d`. Installer: 119,997,991
  bytes, SHA-256 `859418fce2d738cd8ca33a87ff6dfcfee3ec41de478aff0398f6a034366199ae`.
  Hosted browser run [`36932068565`](https://github.com/seabAu/Splicr/actions/runs/36932068565)
  passed all six Studio journeys in 44.4 seconds on implementation commit `fdff678`.
- [x] The independently complete libcurl and SRT subset raised exact coverage to 79 of 92 locators
  and 384 candidates: 128 shipped licenses, 48 supplemental notices, 151 not-built candidates, and
  57 build-only/not-shipped candidates. Ten exact files bring the legal manifest to 162
  hash-verified records. The review packages libcurl's curl/ISC terms and compiled compatibility
  notices plus SRT's MPL-2.0, UDT-derived BSD, Unlicense, and public-domain notices. libssh remains
  deferred until its conditional MinGW object selection is proved with a real build log or link map.
  The rebuilt `0.1.0-dev.16` package passed schema-v2 lifecycle acceptance with all 162 files on
  Windows 10 at `2026-10-01T22:13:42.0809380Z`. Portable: 184,648,770 bytes, SHA-256
  `457447fa80315530fe7a631c90788af879fa023e3cf6de1c3c96d072511aaeeb`. Installer: 120,032,060
  bytes, SHA-256 `221cc01dab433076127f71f0f1e0d6f096bf6e7557ee015294a128ece219231b`.
  Hosted browser run [`36933969511`](https://github.com/seabAu/Splicr/actions/runs/36933969511)
  passed all six Studio journeys in 43.4 seconds on implementation commit `6da624f`.
- [x] The independently complete OpenAPV, zimg, and AOM subset raised exact coverage to 82 of 92
  locators and 401 candidates: 136 shipped licenses, 49 supplemental notices, 159 not-built
  candidates, and 57 build-only/not-shipped candidates. Seven revision-pinned files bring the legal
  manifest to 169 hash-verified records. OpenAPV's BSD-3-Clause terms and AOM's BSD-2-Clause terms,
  required patent grant, fastfeat, libyuv, vector, and x86inc notices are packaged exactly; zimg's
  WTFPL terms remain preserved in corresponding source and impose no binary-notice requirement.
  VMAF remains deferred until its MinGW stdatomic selection is proved and the mkdirp MIT companion
  rule is encoded. The rebuilt `0.1.0-dev.16` package passed schema-v2 lifecycle acceptance with all
  169 files on Windows 10 at `2026-10-01T22:34:12.9787652Z`. Portable: 184,657,432 bytes, SHA-256
  `e2e905f549144a6e4ba55878199679cfe997aed9f62fb5c3fcd2f3b4356abd08`. Installer: 120,042,072
  bytes, SHA-256 `de34f869c48488eafffc30ca049877edae6ab666605d54eb639c4cf93a6356fd`.
  Hosted browser run [`36936124562`](https://github.com/seabAu/Splicr/actions/runs/36936124562)
  passed all six Studio journeys in 43.7 seconds on implementation commit `4094bf0`.
- [x] The MinGW-w64 foundation stage raised exact coverage to 83 of 92 locators and 412 candidates:
  138 shipped licenses, 50 supplemental notices, 166 not-built candidates, and 58
  build-only/not-shipped candidates. Its root, runtime, and winpthreads notices bring the legal
  manifest to 172 hash-verified records. The runtime notice's unresolved Cephes wording remains
  preserved conservatively, while package inspection shows the relevant `cbrt`/`cbrtf` calls resolve
  to Windows UCRT and no distinctive Cephes implementation markers are incorporated. The rebuilt
  `0.1.0-dev.16` package passed schema-v2 lifecycle acceptance with all 172 files on Windows 10 at
  `2026-10-01T22:53:59.5145337Z`. Portable: 184,664,939 bytes, SHA-256
  `994e056fb9120f725db295d18ab6c7720b25edddfaa7af453b6209f2a75cbc1c`. Installer: 120,043,157
  bytes, SHA-256 `9e8329c0429ce11662f9d58816a90351a86f7fa2fbfca3f1bcbd3d8d3ea4ee3f`.
  Hosted browser run [`36938236224`](https://github.com/seabAu/Splicr/actions/runs/36938236224)
  passed all six Studio journeys in 44.1 seconds on implementation commit `19850b3`.
- [x] The two libiconv fallback transports are validated as commit-identical aliases of the
  already-reviewed primary libiconv and gnulib locators. Coverage rises to 85 of 92 locators while
  candidate reconciliation remains exactly 412 and the legal manifest remains 172 files; duplicating
  the 13 candidate rows would incorrectly count one source tree twice. The fail-closed validator
  rejects revision divergence, duplicate aliases, aliases without a directly reviewed canonical
  locator, and chained aliases. Hosted browser run
  [`36939425939`](https://github.com/seabAu/Splicr/actions/runs/36939425939) passed all six Studio
  journeys in 41.8 seconds on implementation commit `b998c22`.
- [x] The VMAF stage raises exact coverage to 86 of 92 locators and 424 candidates: 147 shipped
  licenses, 50 supplemental notices, 169 not-built candidates, and 58 build-only/not-shipped
  candidates. Ten revision-pinned legal files bring the manifest to 182 hash-verified records. The
  exact embedded notices are packaged, and the terse MIT marker in compiled `mkdirp.c` is paired
  with the complete terms from an immutable upstream revision through the companion manifest.
  Configuring the pinned VMAF source with the recipe's Windows cross-file under GCC 16.2.0 reports
  compiler-provided `stdatomic.h` usable, proving neither compatibility header is selected. The
  rebuilt `0.1.0-dev.16` package passed all twelve schema-v2 lifecycle checks on Windows 10 at
  `2026-10-01T23:40:19.8161998Z`. Portable: 184,700,169 bytes, SHA-256
  `caacdef6ad61c13986d8a33667a7e82b4cc03d5c2fa8149910aa9e231b04bcf5`. Installer: 120,053,734
  bytes, SHA-256 `babdee6a060ad6f1de53cd0afb473d1651faafa92e91e005efd638dc4c274464`.
  Hosted browser run [`36942172393`](https://github.com/seabAu/Splicr/actions/runs/36942172393)
  passed all six Studio journeys in 41.8 seconds on implementation commit `0898707`.
- [x] The libssh stage raises exact coverage to 87 of 92 locators and 440 candidates: 151 shipped
  licenses, 53 supplemental notices, 177 not-built candidates, and 59 build-only/not-shipped
  candidates. Seven revision-pinned files bring the legal manifest to 189 hash-verified records.
  Reproducing the exact static-library recipe with GCC 16.2.0, OpenSSL 3.6.4, and zlib 1.3.2.1
  proves the selected bcrypt, Blowfish, ChaCha20, Poly1305, sntrup761, and match objects and excludes
  the bundled Curve25519, Ed25519, libcrux ML-KEM, and getopt fallbacks. The rebuilt
  `0.1.0-dev.16` package passed all twelve schema-v2 lifecycle checks on Windows 10 at
  `2026-10-02T00:01:27.0681559Z`. Portable: 184,735,584 bytes, SHA-256
  `bc3be7b2dfaab051dd721b26cc2eab367817400a25ab8d89d2a4f662e7864822`. Installer: 120,081,884
  bytes, SHA-256 `bb0db4dad2839d18ca12dc443caa4c3a666d5b6aeb0f380f492da4f43d730836`.
  Hosted browser run [`36943982113`](https://github.com/seabAu/Splicr/actions/runs/36943982113)
  passed all six Studio journeys in 44.7 seconds on implementation commit `40ea3e5`.
- [x] The native GLib, Cairo, and Pango stages raise exact coverage to 90 of 92 locators and 477
  candidates: 165 shipped licenses, 58 supplemental notices, 195 not-built candidates, and 59
  build-only/not-shipped candidates. Seventeen revision-pinned files bring the legal manifest to 206
  hash-verified records. The audit preserves GLib's exact LGPL terms and compiled checksum, Mersenne
  Twister, Valgrind, Windows iconv, and pinned GVDB notices; Cairo's selected LGPL-2.1 option, root
  dual-license notice, informational MPL alternative, and five compiled-source notices; and Pango's
  LGPL plus the ICU terms in its compiled Unicode script table. The rebuilt `0.1.0-dev.16` package
  passed all twelve schema-v2 lifecycle checks on Windows 10 at
  `2026-10-02T00:30:32.4766727Z`. Portable: 184,918,215 bytes, SHA-256
  `84ab22d6f926876210d6371e3712909c509c58df4216963d0c80ca35350735ca`. Installer: 120,176,664
  bytes, SHA-256 `ad45f0e92de3467c03d9e23c00855ff40a77477975400d7421ff4b390aab66e7`.
  Hosted browser run [`36946481820`](https://github.com/seabAu/Splicr/actions/runs/36946481820)
  passed all six Studio journeys in 45.9 seconds on implementation commit `a94e827`.
- [x] The librsvg stage raises exact coverage to 91 of 92 locators and 1,139 candidates: 354 shipped
  licenses, 67 supplemental notices, 621 not-built candidates, and 97 build-only/not-shipped
  candidates. The target-specific Cargo record contains exactly 203 packages for
  `x86_64-pc-windows-gnu`, `--no-default-features`, and `--features avif`: 182 runtime packages and
  21 build-only packages. Equal Cargo.lock/vendor checksums, package-to-review coverage, portable
  package identities, and the complete selected SPDX set are enforced by a dedicated validator and
  six negative tests. Eighty-six exact librsvg/Cargo payloads bring the legal manifest to 292 files.
  The downloader authenticates each complete `.crate` archive before extracting one exact regular
  member, rejects traversal/non-regular members and checksum drift, and fetched/hash-verified all
  292 records. The rebuilt `0.1.0-dev.16` package passed all twelve schema-v2 lifecycle checks at
  `2026-10-02T01:07:44.2759357Z`. Portable: 185,028,993 bytes, SHA-256
  `42f5fe1deec5ba9de583098680be6305546145bdbab3d4453b79b5354ed7335b`. Installer: 120,196,533
  bytes, SHA-256 `467035251285f01096978aa8a1c2e2349407423d16d430bd227e94bf37453572`.
  Hosted browser run [`36949971407`](https://github.com/seabAu/Splicr/actions/runs/36949971407)
  passed all six Studio journeys in 43.5 seconds on implementation commit `2eed132`.
- [x] The rav1e stage completes exact review coverage for all 92 locators and 1,651 candidates: 441
  shipped licenses, 69 supplemental notices, 970 not-built candidates, and 171 build-only/not-shipped
  candidates. The recipe's time-dependent `cargo update cc` is reconstructed as `cc=1.4.7`,
  `find-msvc-tools=0.1.13`, and `shlex@2.0.1=2.0.1`; collection verifies Cargo.lock SHA-256
  `14a4b2ae596569e83e40a3431ffc4b210dd872e333969ddb18ce895f7b19d7c7` and all 275 versioned vendor
  directories. The exact Windows GNU target closure contains 123 packages (82 runtime and 41
  build-only), bringing the combined tracked Cargo profiles to 326 packages (264 runtime and 62
  build-only). Forty-seven exact rav1e/Cargo payloads bring the legal manifest to 339 files; all 339
  fetched and hash-verified. Four packages whose crate archives intentionally omit a license file are
  bound to explicit companion records: exact VCS-commit MIT files for `profiling` and
  `profiling-procmacros`, the closest immutable pre-publication upstream MIT file for `av-metrics`
  without claiming byte identity to its later crate, and a clearly labeled SPLICR-generated notice
  for `simd_helpers` because its exact immutable source has no license file. The rebuilt
  `0.1.0-dev.16` package passed all twelve schema-v2 lifecycle checks at
  `2026-10-02T02:29:22.8861851Z`, including all 339 dependency-license files. Portable:
  180,544,170 bytes, SHA-256 `53e590fa92edc98026a97c835d260975c17f397064a61e8f7c509b8a6c3e175f`.
  Installer: 120,209,563 bytes, SHA-256
  `0e33ec58e21a203ddd0f257a99ffd19954fff560a26ed5886513d0483822aa58`.
  Hosted browser run [`36956359725`](https://github.com/seabAu/Splicr/actions/runs/36956359725)
  passed all six Studio journeys in 40.5 seconds on implementation commit `4f6df70`.
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

## librsvg corresponding-source and relinking record

The pinned librsvg source archive is commit
`7612431eb02dc009319094f8513d63c1faaecfb4`. Its source-collection step runs Cargo vendor with
versioned directories, so the normalized stage archive carries the exact registry inputs rather
than depending on crates.io during a rebuild. The selected target closure is versioned in
[`ffmpeg-cargo-source-closure.tsv`](../packaging/windows/ffmpeg-cargo-source-closure.tsv); it omits
local audit paths and records the target, feature selection, runtime/build context, package identity,
Cargo.lock checksum, vendored-package checksum, and candidate count for every package.

To reproduce or relink this component, start from BtbN recipe commit
`20ad148c3b69a862b061eb7e6cc7b61d896bcfef` and its exact
`scripts.d/50-librsvg/99-librsvg.sh` stage. Use the collected source tree with
`CARGO_NET_OFFLINE=true`; remove the recipe's two environment overrides from `meson.build`; then
configure Meson for a release, static, no-wrap build with the recipe's Rust target and cross file,
LTO disabled, AVIF enabled, and pixbuf, pixbuf-loader, rsvg-convert, introspection, Vala, docs, and
tests disabled. Build and install with Ninja, then rebuild the shared FFmpeg stage with
`--enable-librsvg` and the tracked configure line. A recipient may replace or modify the collected
librsvg/Cargo sources before those steps and substitute the resulting normally named FFmpeg DLLs;
that full shared-DLL rebuild is the relinking path for the statically incorporated LGPL components.

This record closes the librsvg-specific source and relinking analysis. It does not claim that the
current primary-source audit ZIP is complete corresponding source for the entire 92-locator bundle;
the final full-graph collection, rebuild, and publication gates above remain open.

## rav1e corresponding-source and relinking record

The pinned rav1e source is commit `31435de9d76fddd38f6dcc31d4014574cebb2092`. Its BtbN recipe
performs a time-dependent `cargo update cc`; the tracked supplement makes that transformation
reproducible, validates the resulting lockfile, and vendors all 275 lockfile crates into versioned
directories. The normalized collected stage archive is
`scripts.d__50-rav1e_b2d3a4caec12576416c156eb16b4f83433caf3dc3a8270ed0bfe4fb74098dd54.tar.xz`, SHA-256
`36cdce5987cceb1000ba937e7a96dd7c3713150349bd782f781fbf6ab94af02f`. The selected target closure is
versioned in [`ffmpeg-cargo-source-closure.tsv`](../packaging/windows/ffmpeg-cargo-source-closure.tsv)
for `x86_64-pc-windows-gnu`, default features, and the runtime/build context used by the recipe.

To reproduce or relink this component, start from BtbN recipe commit
`20ad148c3b69a862b061eb7e6cc7b61d896bcfef` and `scripts.d/50-rav1e.sh`. Use the normalized rav1e
tree and its generated `.cargo/config.toml` with `CARGO_NET_OFFLINE=true`, build the pinned source for
`x86_64-pc-windows-gnu` with default features, and install the resulting static rav1e library and
headers. Then rebuild the shared FFmpeg stage with `--enable-librav1e` and the tracked configure line.
A recipient may modify or replace the collected rav1e/Cargo sources before those steps and substitute
the resulting normally named FFmpeg DLLs; rebuilding the shared DLL set is the relinking path for the
statically incorporated rav1e component.

This closes the rav1e-specific source and relinking analysis. Full-graph collection, correspondence
rebuild verification, archive publication, and download-page attribution remain release gates.

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

1. Treat the current bundle as GPL-covered and collect, verify, review, and publish the complete
   applicable GPL corresponding-source and notice set; or
2. replace the package binary with a reproducibly built, capability-tested non-GPL FFmpeg
   configuration (including a non-GPL Chromaprint FFT backend or no Chromaprint)
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
