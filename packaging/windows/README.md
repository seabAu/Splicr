# Windows desktop package

The desktop package is a PyInstaller **one-directory** build wrapped by an optional per-user Inno
Setup installer. It deliberately keeps mutable state outside the installation directory:

- application files: `%LOCALAPPDATA%\Programs\SPLICR Studio`
- user data: `%LOCALAPPDATA%\SPLICR Studio\data`
- logs: `%LOCALAPPDATA%\SPLICR Studio\data\logs`

Installing a newer version replaces application files but leaves jobs, SQLite state, credentials,
component settings, generated media, and external model environments untouched. Uninstalling the
application also leaves that data in place so a reinstall can resume it. The app never copies or
deletes the Kokoro, Qwen3-TTS, or Audio8 environments configured in Components.

## Build locally

Requirements:

- Windows x64
- Python 3.11+ and `uv`
- Node.js/npm
- Network access for the pinned, checksum-verified upstream `lgpl-shared` FFmpeg asset
  (recommended), or a reviewed FFmpeg/FFprobe directory supplied explicitly with `-FfmpegBin`.
  The current pinned asset is effectively GPL-covered because its static Chromaprint includes
  FFTW3; the upstream variant name is not a license determination.
- Inno Setup 6, unless only the portable ZIP is needed

```powershell
$ffmpegBin = uv run python .\packaging\windows\fetch_ffmpeg_release.py
.\packaging\windows\build.ps1 -Version 0.1.0 -FfmpegBin $ffmpegBin
```

Use `-SkipInstaller` to build only the portable ZIP. `build.ps1` rebuilds the React assets, copies
FFmpeg/FFprobe and required shared DLLs into the private app bundle, builds the one-directory
executable, creates checksums, records the exact bundled media-tool build, and then compiles the
installer. The fetcher pins the BtbN release tag, asset name, and SHA-256 digest; it also creates a
`SOURCE_INFO.txt` record. Required external-library license files are declared once in
`ffmpeg-packaged-license-files.tsv`; the standard-library Python fetcher downloads exact revision
URLs, applies only declared transport decoding, retries bounded transient failures, and rejects a
hash mismatch. Generated vendor tools and build outputs are ignored by Git. Every package includes
`THIRD_PARTY_NOTICES.md`, generated `BUILD_INFO.txt`, the FFmpeg `LICENSE.txt` and
`SOURCE_INFO.txt`, and each manifest-listed dependency license beside the bundled media tools. The
build locates Inno Setup from `PATH` or its standard per-user and machine-wide installation
directories, so installer builds do not require an administrator-only Inno installation.

Omitting `-FfmpegBin` retains the legacy behavior of copying `ffmpeg.exe` and `ffprobe.exe` from
`PATH`; that fallback does not discover or copy shared DLLs and must be reviewed independently.
`BUILD_INFO.txt` is authoritative for every candidate. For a public release, also host the exact
corresponding FFmpeg source, add the required attribution/source link to the download surface, and
complete the [FFmpeg legal checklist](https://ffmpeg.org/legal.html); bundling an LGPL build and its
license is necessary but is not, by itself, a legal review.

The small native lifecycle window owns the local FastAPI process. It opens `/studio/`, can reopen
the browser or data folder, writes startup diagnostics to `desktop.log`, and shuts the server down
cleanly when closed. Launching a second copy detects the existing local instance and opens it rather
than starting a competing service. `SPLICR Studio.exe --no-browser` runs the same lifecycle window
without automatically opening the browser, which is useful for managed launches and package
acceptance; the window still owns and cleanly stops the private server.

## Package acceptance

Run the artifact-level harness only on a disposable Windows VM or CI runner. It installs and
uninstalls the real package and therefore writes the normal per-user uninstall registration and
Start menu entry while it runs. The harness requires PowerShell 7 (`pwsh`):

```powershell
.\packaging\windows\test-package.ps1 -Version 0.1.0
```

The harness independently verifies the checksum manifest, extracts the portable ZIP to a path with
spaces, proves portable smoke leaves every package file unchanged, redirects mutable state to a
separate per-user data root, silently installs the real installer, checks FFmpeg's shared
configuration, effective-license evidence, and provenance files, proves the installed payload exactly matches the portable
payload, renders and probes an OpenH264/AAC MP4, uninstalls, and proves the application directory is
removed while user data remains. It writes a machine-readable
`SPLICR-Studio-<version>-Windows-x64-ACCEPTANCE.json` beside the packages. The release workflow
runs this gate before uploading any artifact.

On a disposable upgrade-test VM, pass the previous release installer to exercise an in-place
upgrade before the current artifact checks. The harness runs the older package smoke, creates and
hashes representative external user data, installs the current candidate over it, proves that data
is byte-identical, and rejects stale application files by comparing the installed payload with the
current portable package:

```powershell
.\packaging\windows\test-package.ps1 `
  -Version 0.2.0 `
  -PreviousInstaller .\previous\SPLICR-Studio-0.1.0-Windows-x64-setup.exe
```

This automated harness does not replace the release checklist's interactive clean-VM checks for
the lifecycle window, browser launch/reuse, real document playback, upgrade migration, Windows
Settings, Start menu behavior, or signing/malware review.

## FFmpeg source audit

The packaging workflow also creates and validates an explicitly incomplete FFmpeg primary-source
audit kit. It pins the exact FFmpeg, OpenH264, and BtbN recipe snapshots without pretending that
those three archives alone cover every external library compiled into the distributed FFmpeg DLLs.
The generator writes a separate SHA-256 sidecar and the validator checks both the outer archive and
every pinned source archive inside it. The kit also carries the exact 90-stage enabled build graph,
recipe-pinned revision table, and raw source-fetch commands extracted from the BtbN generator.

```powershell
.\packaging\windows\test-ffmpeg-source-graph.ps1
.\packaging\windows\prepare-ffmpeg-source-audit.ps1 -Version 0.1.0
.\packaging\windows\test-ffmpeg-source-audit.ps1 -Version 0.1.0
```

The Linux/Docker source collector has a separate fail-closed license-candidate stage. After a
partial or full collection, run `inventory-ffmpeg-source-licenses.sh` against its output, then run
`test-ffmpeg-source-license-inventory.sh` and `test-ffmpeg-source-license-review.sh`. Generated
candidate rows remain pending until their source identity, SPDX expression, and binary notice
obligation are added to the tracked `ffmpeg-source-license-review.tsv`. The reviewed set now covers
all 92 source locators and 1,651 detected candidates: 441 shipped licenses, 69 supplemental notices,
970 recipe-proven not-built candidates, and 171 build-only candidates absent from the
distributed binary. Required notices are hash-anchored byte-for-byte in `THIRD_PARTY_NOTICES.md` or
separately manifest-bound and packaged, including exact files for ffnvcodec, dav1d, FriBidi,
TwoLAME, AMF, OpenJPEG, Game Music Emu, GMP, Kvazaar, LCEVCdec, libvpx, libwebp, libzmq, and
OpenCORE AMR, libudfread, oneVPL, PCRE2, pixman, Little CMS, OpenAL Soft, SoX Resampler, and
uavs3d, Brotli, JPEG XL, Highway, Mbed TLS, TF-PSA-Crypto, librist, LV2, Serd, Zix, Sord, Sratom,
Lilv, FFTW3, Chromaprint, LAME, Theora, Vorbis, libxml2, ZVBI, GNU libiconv, Fontconfig, Unicode,
HarfBuzz, FreeType, aribb24, libaribcaption, libass, libbluray, OpenSSL, SVT-AV1, libva, VVenC,
libplacebo, OpenCL, OpenMPT, Vulkan-Headers, Vulkan-Shim-Loader, Shaderc, glslang, SPIRV-Tools,
SPIRV-Cross, SPIRV-Headers, libcurl, SRT, libssh, OpenAPV, AOM, MinGW-w64, VMAF, GLib, Cairo,
Pango, librsvg, librsvg's target-specific Cargo closure, rav1e, and rav1e's reconstructed Windows GNU
Cargo closure. The 339-file legal manifest is
downloaded from revision-pinned upstream URLs and hash-verified before packaging. The review
corrected FFTW3 from build-only to
statically incorporated: the package gate now requires its GPL text and notice, verifies the enabled
Chromaprint/static pkg-config path, rejects a separate FFTW DLL, and confirms an FFTW marker inside
`avformat-63.dll`. ZVBI supplies an additional GPL-2.0-only static-link path; SDL2 is recorded as
build-only because SPLICR does not distribute `ffplay.exe`. GNU libiconv is statically incorporated
under LGPL-2.1-or-later; the unshipped `iconv` CLI's gnulib inputs remain build-only. Fontconfig's
separate Unicode-3.0 obligation is bound through the companion manifest. MinGW-w64's root, runtime,
and winpthreads notices are preserved exactly; the runtime notice's unresolved Cephes wording remains
conservative even though package inspection shows the relevant math calls resolve to Windows UCRT and
no distinctive Cephes implementation markers are incorporated. VMAF's compiled embedded notices
are packaged exactly, including a separately pinned full MIT companion for `mkdirp.c`; reproducing
the recipe's Windows cross-configuration under GCC 16.2.0 proves that the compiler-provided
`stdatomic.h` is selected instead of either bundled compatibility header. GLib's selected runtime
notices include its dereferenced LGPL symlink target and the exact commit-pinned GVDB submodule;
Cairo's selected LGPL option and compiled-source notices and Pango's LGPL/ICU terms are packaged.
The librsvg record pins the exact 203-package Windows GNU closure (182 runtime and 21 build-only)
for `--no-default-features --features avif`. Its validator binds every runtime package to a shipped
license record, every build dependency to a build-only record, and every registry package to equal
Cargo.lock and vendored-package checksums. Crate-backed notice downloads verify the complete `.crate`
archive before extracting one exact regular member. The rav1e record reproduces the recipe's
time-dependent `cargo update cc` deterministically as `cc=1.4.7`, `find-msvc-tools=0.1.13`, and
`shlex@2.0.1=2.0.1`, verifies the resulting Cargo.lock SHA-256 and 275-directory vendor set, and pins
the exact 123-package target closure (82 runtime and 41 build-only). Its normalized collected archive
has SHA-256 `36cdce5987cceb1000ba937e7a96dd7c3713150349bd782f781fbf6ab94af02f`.
All 339 manifest-bound files are fetched and hash-checked. FFmpeg's own license is
not treated as a substitute for dependency licenses. The two libiconv fallback transports are
validated in `ffmpeg-source-locator-aliases.tsv` as commit-identical aliases of the already-reviewed
primary locators; they increase locator coverage without duplicating one source tree's 13 candidates.
Optional-notice, not-built, and build-only/not-shipped candidates remain explicit
rather than silently ignored. The validator can reconcile every generated candidate to exactly one
reviewed disposition. Inventory extraction resolves only bounded, relative, in-archive license
symlinks and rejects escaping, absolute, cyclic, ambiguous, or over-deep links. Repeated `--stage`
selections permit ordered bounded batches, with a 12 GiB
default reserve guarding both host output and collector workspace filesystems. Successful fetches
stay quiet while failures retain and print a bounded diagnostic log. Full-graph and codec patent
review remain incomplete.

See [`../../docs/FFMPEG_DISTRIBUTION.md`](../../docs/FFMPEG_DISTRIBUTION.md) for the exact binary
identity, upstream checklist mapping, and remaining corresponding-source/publication gates. The
audit kit is CI evidence; it must not be published or described as complete corresponding source.

## Removing local data manually

Windows uninstall intentionally removes only the application and shortcuts. To erase projects,
profiles, job history, generated media, settings, logs, and locally stored credential material,
first close SPLICR Studio and back up anything needed, then delete
`%LOCALAPPDATA%\SPLICR Studio\data` in File Explorer. This action is permanent and is deliberately
separate from uninstall so upgrading or reinstalling cannot silently destroy in-progress work.

The complete fresh-install, upgrade, uninstall, portable, live-engine, evidence, and rollback matrix
is maintained in [`../../docs/RELEASE_CHECKLIST.md`](../../docs/RELEASE_CHECKLIST.md).
