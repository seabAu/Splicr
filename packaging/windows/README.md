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
- A retained checksum-verified copy of the pinned upstream `lgpl-shared` FFmpeg asset,
  or a reviewed FFmpeg/FFprobe directory supplied explicitly with `-FfmpegBin`.
  The current pinned asset is effectively GPL-covered because its static Chromaprint includes
  FFTW3; the upstream variant name is not a license determination.
- Inno Setup 6, unless only the portable ZIP is needed

**Upstream availability (2026-10-12):** BtbN removed the pinned September 24 daily release;
its original download URL now returns 404. Cached, hash-verified input still supports local
builds, but fresh package runners need a durable approved source for that exact archive.
Do not change the shipping pin or use browser-only media as a substitute: the reviewed source,
dependency notices, and correspondence evidence apply to the September 24 payload.

The fetcher accepts a retained exact archive without changing its identity:

```powershell
$ffmpegBin = uv run python .\packaging\windows\fetch_ffmpeg_release.py `
  --archive-file C:\reviewed-inputs\ffmpeg-n9.0.2-3-ga5923073bf-win64-lgpl-shared-9.0.zip
```

`SPLICR_FFMPEG_ARCHIVE_FILE` is the equivalent optional environment variable (the CLI flag takes
precedence). CI reads it from a repository variable with the same name. A supplied file must match
the existing reviewed SHA-256 before it is copied, and the copy is checked again before atomic
publication into the local cache. Missing/wrong supplied files fail rather than falling back to
another build or download. Dependency licenses still come from their existing revision-pinned
manifest. The user-approved private `Splicr-CI` source/input mirror can provide that archive to a
fresh runner without putting binaries in the public source repository or retaining installers.
The successful dev.22 run `39045114567` used this route. Its source snapshot matches public commit
`fffb210` exactly; update and verify that snapshot before testing a newer public commit. A new public
push alone does not update the separate private source/input mirror.

Browser acceptance separately uses `fetch_browser_media.py` with the retained September 30
month-end archive and upstream SHA-256 `7157177b8a6cb2174c1650ba8c71b363f2c78cba5330f88c4c02cf5b2b880646`.
It checks the download digest, extraction paths, and both tool executables. This test-only
directory lives under the runner's temporary directory, is never uploaded or fed into packaging,
and does not satisfy exact shipping-media or installer acceptance.

```powershell
$ffmpegBin = uv run python .\packaging\windows\fetch_ffmpeg_release.py
.\packaging\windows\build.ps1 -Version 0.1.0 -FfmpegBin $ffmpegBin
```

Use `-SkipInstaller` to build only the portable ZIP. `build.ps1` rebuilds the React assets, copies
FFmpeg/FFprobe and required shared DLLs into the private app bundle, builds the one-directory
executable, creates a checksum manifest containing only the publishable portable ZIP and installer,
records the exact bundled media-tool build, and then compiles the installer. The fetcher pins the
BtbN release tag, asset name, and SHA-256 digest; it also creates a
`SOURCE_INFO.txt` record. Required external-library license files are declared once in
`ffmpeg-packaged-license-files.tsv`; the standard-library Python fetcher downloads exact revision
URLs, applies only declared transport decoding, retries bounded transient failures, and rejects a
hash mismatch. Generated vendor tools and build outputs are ignored by Git. Every package includes
the application's root Apache-2.0 `LICENSE.txt`, `THIRD_PARTY_NOTICES.md`, generated
`BUILD_INFO.txt`, the FFmpeg `LICENSE.txt` and
`SOURCE_INFO.txt`, generated `LEGAL_INFO.json`, and each manifest-listed dependency license beside
the bundled media tools. Studio's **About & legal** modal reads those files through fixed,
read-only API routes; it never exposes a local path. An internal build explicitly reports that no
published corresponding-source archive is configured.

Only after the final corresponding-source archive has passed review and been assigned its public
HTTPS location, embed that direct link and the archive's independently computed SHA-256:

```powershell
.\packaging\windows\build.ps1 `
  -Version 0.1.0 `
  -FfmpegBin $ffmpegBin `
  -CorrespondingSourceUrl "https://downloads.example/SPLICR-Studio-0.1.0-FFmpeg-source.zip" `
  -CorrespondingSourceSha256 "<64 lowercase hexadecimal characters>"
```

The two corresponding-source arguments are all-or-nothing and the URL must be HTTPS without
embedded credentials. Their presence makes the direct download and digest visible in the legal
modal; it does not itself prove that the archive is complete. The
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

Hosted package runs are **build/test-only by default**, including tag-triggered runs. They do not
upload installers, portable ZIPs, or audit archives. Only an explicit manual workflow dispatch
with the boolean `retain_packages` input enabled can retain downloadable package artifacts, and
that option must wait for the release/compliance checklist. A build/test-only run still needs the
exact reviewed shipping-media input; the removed upstream daily archive currently blocks fresh
runner acquisition. The workflow fails closed on acquisition errors instead of falling back to
unrelated tools on `PATH`. Browser-only media must not be substituted.

Run the artifact-level harness only on a disposable Windows VM or CI runner. It installs and
uninstalls the real package and therefore writes the normal per-user uninstall registration and
Start menu entry while it runs. The harness requires PowerShell 7 (`pwsh`):

```powershell
.\packaging\windows\test-package.ps1 -Version 0.1.0
```

The harness independently verifies the checksum manifest and the application license/digest,
extracts the portable ZIP to a path with
spaces, proves portable smoke leaves every package file unchanged, redirects mutable state to a
separate per-user data root, silently installs the real installer, checks FFmpeg's shared
configuration, effective-license evidence, and provenance files, proves the installed payload exactly matches the portable
payload, and runs SPLICR's own Convert backend from WAV to FLAC plus its Audiogram backend from WAV
to MP4 using the bundled FFmpeg/FFprobe resolution path. It separately renders and probes an
OpenH264/AAC MP4, uninstalls, and proves the application directory is removed while user data
remains. It also verifies the per-user Start-menu shortcut and Windows
uninstall registration after install/reinstall and proves both are removed after each uninstall.
Before uninstall, the packaged application seeds a real completed job with source/checkpoint/output
media plus a Library project, immutable render plan/take/artifact, voice profile, and Studio profile.
The harness reinstalls the exact candidate, makes the packaged application semantically reopen every
record and hash-check all three files, compares the reinstalled payload with the portable payload,
and uninstalls again without removing user data. It writes a machine-readable
`SPLICR-Studio-<version>-Windows-x64-ACCEPTANCE.json` beside the packages. The release workflow
runs this gate before uploading any artifact.

The installed-package phase also starts the real native lifecycle window and local FastAPI server,
waits for the packaged `/health` and `/studio/` surfaces, proves that a second desktop launch reuses
the running instance, and requests a graceful lifecycle shutdown. This package-only probe never
opens an external browser and communicates through unique files under the disposable acceptance
run directory.

On a disposable upgrade-test VM, pass the previous release installer to exercise an in-place
upgrade before the current artifact checks. The harness runs the older package smoke, creates and
hashes representative external user data, installs the current candidate over it, proves that data
is byte-identical, and rejects stale application files by comparing the installed payload with the
current portable package. The installer clears only its application-owned content-hashed Studio
asset directory before replacement so obsolete JavaScript and CSS cannot survive an upgrade; the
separate per-user data root is never part of that cleanup. Once the previous package contains the
package-state acceptance command,
add `-RequirePreviousRepresentativeState`: the previous executable then seeds the completed job,
checkpoint/output media, Library project, render plan/take/artifact, voice profile, and Studio
profile. The candidate must migrate and semantically reopen that exact state before the harness
continues, and the evidence JSON records `representative_state_origin` as `previous_package`:

```powershell
.\packaging\windows\test-package.ps1 `
  -Version 0.2.0 `
  -PreviousInstaller .\previous\SPLICR-Studio-0.1.0-Windows-x64-setup.exe `
  -RequirePreviousRepresentativeState
```

This automated harness does not replace the release checklist's interactive clean-VM checks for
the visible lifecycle window, actual browser launch, real document playback, Windows Settings,
launching through the Start menu, credentials migration, or signing/malware review.

For the human-visible portion, copy the installer, portable ZIP, checksum manifest, and repository
checkout to a disposable clean Windows x64 VM. From a non-elevated PowerShell 7 session run:

```powershell
.\packaging\windows\run-clean-vm-checklist.ps1 `
  -Version 0.1.0 `
  -ArtifactsDir .\dist `
  -ConfirmDisposableMachine
```

That is the fresh-install scenario. Preserve its JSON, revert the VM to the original clean snapshot,
and run the upgrade scenario with the retained previous installer:

```powershell
.\packaging\windows\run-clean-vm-checklist.ps1 `
  -Version 0.1.0 `
  -ArtifactsDir .\dist `
  -PreviousInstaller .\dist\SPLICR-Studio-0.0.9-Windows-x64-setup.exe `
  -ConfirmDisposableMachine
```

The upgrade scenario installs and opens the previous package first, seeds the same representative
job/project/profile/media graph used by automated package acceptance, asks the operator to prepare
any additional resumable work and credential metadata, then installs the candidate over it. The
candidate must verify the package-owned state, preserve a hash-bound external marker, register the
new version, and reopen the operator-observed state. Fresh and upgrade runs write separate
`CLEAN-VM-FRESH-ACCEPTANCE.json` and `CLEAN-VM-UPGRADE-ACCEPTANCE.json` files.

The guided harness refuses an elevated or previously used machine, verifies both artifact hashes,
installs per-user, launches through the Start-menu shortcut, checks the loopback health and packaged
Studio surface, verifies second-launch port reuse, and prompts only for observations that require a
person: the visible lifecycle/browser experience, actual rendering/playback, bundled media tools,
Windows Settings, and preserved state after uninstall/reinstall. After the final uninstall it also
extracts the portable ZIP to a spaces-bearing temporary path, launches the full Studio against the
preserved user data, verifies clean shutdown, and proves the portable application tree stayed
unchanged. It stores booleans rather than credentials or document content in
`SPLICR-Studio-<version>-Windows-x64-CLEAN-VM-<scenario>-ACCEPTANCE.json`, then leaves the intentionally
preserved data directory and extracted portable tree in place for inspection.

Before copying the candidate to the VM, the same script can perform a non-destructive artifact and
checksum preflight on the build machine. This mode never installs, launches, uninstalls, prompts, or
writes clean-VM acceptance evidence:

```powershell
.\packaging\windows\run-clean-vm-checklist.ps1 `
  -Version 0.1.0 `
  -ArtifactsDir .\dist `
  -ValidateOnly
```

## FFmpeg source audit

The packaging workflow also creates and validates an explicitly incomplete FFmpeg primary-source
audit kit. It pins the exact FFmpeg, OpenH264, and BtbN recipe snapshots without pretending that
those three archives alone cover every external library compiled into the distributed FFmpeg DLLs.
The generator writes a separate SHA-256 sidecar and the validator checks both the outer archive and
every pinned source archive inside it. The kit also carries the exact 90-stage enabled build graph,
recipe-pinned revision table, and raw source-fetch commands extracted from the BtbN generator.

```powershell
.\packaging\windows\test-rebuild-ffmpeg-offline-dependencies.ps1
.\packaging\windows\test-ffmpeg-source-graph.ps1
.\packaging\windows\prepare-ffmpeg-source-audit.ps1 -Version 0.1.0
.\packaging\windows\test-ffmpeg-source-audit.ps1 -Version 0.1.0
```

For a collected rebuild workspace whose `repo` directory contains the generated BtbN Dockerfile
and authenticated `.cache/downloads` archives, prepare and build the dependency image without
network access with:

```powershell
.\packaging\windows\rebuild-ffmpeg-offline-dependencies.ps1 `
  -RebuildWorkspace D:\splicr-ffmpeg-rebuild-podman
```

The helper leaves the preserved Dockerfile and archives unchanged. It embeds an LF-only executable
stage runner into a derived Dockerfile and descends through a sole archive wrapper directory when
present. It also verifies every entry in `ffmpeg-offline-build-inputs.json` by SHA-256, replaces
the oneVPL recipe's live PR-patch fetch with the tracked local patch, and supplies FreeType's exact
`dlg` submodule revision from the tracked source archive instead of cloning during the build.
Dependency stages default to sequential execution because Podman 5.6.1 can panic while committing
parallel Buildah stages; individual dependency build systems may still compile in parallel.

Once the full collection, candidate inventory, and network-disabled rebuild match the pinned
evidence, create the publication-pending corresponding-source directory with:

```powershell
.\packaging\windows\prepare-ffmpeg-corresponding-source.ps1 `
  -Version 0.1.0-dev.18 `
  -CollectionRoot D:\splicr-ffmpeg-corresponding-source `
  -PrimarySourceDirectory .\.test-runs\ffmpeg-source-audit `
  -RebuildWorkspace D:\splicr-ffmpeg-rebuild-podman `
  -OutputDirectory D:\SPLICR-Studio-0.1.0-dev.18-FFmpeg-corresponding-source-candidate `
  -UseHardLinks

.\packaging\windows\test-ffmpeg-corresponding-source.ps1 `
  -BundleDirectory D:\SPLICR-Studio-0.1.0-dev.18-FFmpeg-corresponding-source-candidate
```

Hard links are optional and only avoid duplicating the large archive bytes on the same volume. The
output manifest records complete collected source and verified correspondence while keeping the
public-release flag false. Archive and publish it only after the remaining release gates in
`FFMPEG_DISTRIBUTION.md` are satisfied.

The Linux/Docker source collector has a separate fail-closed license-candidate stage. After a
partial or full collection, run `inventory-ffmpeg-source-licenses.sh` against its output, then run
`test-ffmpeg-source-license-inventory.sh` and `test-ffmpeg-source-license-review.sh`. Generated
candidate rows remain pending until their source identity, SPDX expression, and binary notice
obligation are added to the tracked `ffmpeg-source-license-review.tsv`. The reviewed set now covers
the complete 90-stage collection, all 92 source locators, and 1,684 detected candidates: 441 shipped
licenses, 69 supplemental notices, 1,001 recipe-proven not-built candidates, and 173 build-only
candidates absent from the
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
has SHA-256 `766c883866747d2a3ce1f6202ed3f19da5f72fa397e399a8d4568dc8c821d2b0` in the authenticated
full-graph collection. Reuse is rejected unless a Cargo-supplemented archive contains the exact
lockfile, vendoring config, and expected vendor-package count.
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
stay quiet while failures retain and print a bounded diagnostic log. The full-graph source and
correspondence rebuild are complete. Codec patent review, public hosting, release-page/application
attribution, and final release-terms review remain incomplete.

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
