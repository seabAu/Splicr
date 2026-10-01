# SPLICR Studio release checklist

This is the reproducible release gate for the merged local SPLICR Studio application. Keep the
checkboxes and evidence table current; do not infer that a clean-machine or live-provider check
passed from unit tests alone.

## 1. Prepare the release commit

- [ ] Confirm `git status --short` contains only intended release changes.
- [ ] Update the version in `pyproject.toml` and the package workflow input/tag.
- [x] Update `CHANGELOG.md` or the release notes with migrations, known limitations, and provider or
  model changes.
- [x] Review `packaging/windows/THIRD_PARTY_NOTICES.md`, especially the exact FFmpeg distribution
  bundled for this build. The `0.1.0-dev.3` internal candidate contains Gyan's GPLv3 full build;
  the later BtbN asset is named `lgpl-shared` upstream, but transitive review proves its enabled
  Chromaprint statically incorporates GPL FFTW3. Public distribution therefore remains blocked
  until a verified non-GPL build is substituted or complete applicable GPL compliance materials
  are deliberately supplied.
- [x] Confirm no API keys, model files, generated media, job databases, `.env` files, or virtual
  environments are tracked. Verified 2026-09-29 with the repository/vault regression suite and a
  tracked-source secret-pattern scan; the only unrelated working-tree item was user-owned
  `LICENSE.txt`.

## 2. Run the deterministic local gate

From the repository root in PowerShell:

```powershell
uv sync --frozen --extra dev
uv run ruff check .
uv run pytest -q
npm --prefix studio-web ci
npm --prefix studio-web test
npm --prefix studio-web run build
npm --prefix studio-web exec -- playwright install chromium
npm --prefix studio-web run test:e2e
```

- [x] Python suite passes with only documented opt-in live-environment skips. Verified 2026-09-29:
  543 passed, 7 intentional live skips.
- [x] Frontend unit suite and production build pass. Verified 2026-09-29: 8 unit tests passed and
  Vite 8.3.1 built the committed package assets.
- [x] Every Chromium journey passes without console/page errors. Verified 2026-09-29: all 6
  Playwright journeys passed against the supervised FastAPI server.
- [x] Failure retention is configured for `studio-web/playwright-report/` and
  `studio-web/test-results/` (trace, screenshot, and video); the current passing run produced no
  failure diagnostics to retain.
- [x] Real FFmpeg/FFprobe smoke tests ran rather than being skipped. The focused audiogram,
  conversion, and finishing set passed all 42 tests on 2026-09-29.

## 3. Run deliberate live checks

Use small, non-sensitive fixtures and record provider, model, voice, date, SPLICR commit, and result.
Never paste credentials into the evidence table.

```powershell
$env:SPLICR_LIVE_PROVIDER = "gemini" # then deepgram / inworld
uv run pytest -m live_provider tests/test_live_provider_acceptance.py

uv run pytest -m live_engine tests/test_live_edge_provider.py
uv run pytest -m live_engine tests/test_live_edge_sentence_revision.py
uv run pytest -m live_engine tests/test_live_kokoro_acceptance.py
uv run pytest -m live_engine tests/test_live_qwen_voice_design.py
uv run pytest -m live_engine tests/test_live_audio8_acceptance.py
uv run pytest -m live_engine tests/test_transcription_live.py
```

- [ ] Gemini canonical-audio contract passes.
- [ ] Deepgram canonical-audio contract passes.
- [x] Inworld canonical-audio contract passes. Verified 2026-09-29 with saved resource revision 1,
  `inworld-tts-2`, voice `Ashley`, and the current `/tts/v1/voice` endpoint; the harness resolved
  the credential directly from SPLICR's vault without exporting it.
- [x] Edge online-service contract passes. Verified 2026-09-29 with `edge-tts 7.2.8`, model
  `edge-tts`, voice `en-US-AriaNeural`, canonical 24 kHz mono signed-16-bit PCM, and word timings.
- [x] Configured Kokoro environment passes its applicable end-to-end checks. Verified 2026-09-29
  with Python 3.12.14, Kokoro 0.9.4, and `af_heart`: Markdown import, preview/persisted-plan
  agreement, real render, forced restart, completed-checkpoint preservation, canonical WAV, and
  range playback all passed.
- [x] Configured Qwen3-TTS environment passes its applicable end-to-end checks. Verified
  2026-09-29 with Python 3.12.14, `qwen-tts 0.1.1`, CUDA PyTorch 2.11.0, VoiceDesign take 2, the
  1.7B Base clone model, synthesis seed `424242`, five non-default sampling values, and a forced
  restart that preserved the frozen controls and completed-checkpoint hash/timestamp/attempt count.
- [x] Configured Audio8 environment passes its applicable end-to-end checks. Verified 2026-09-29
  with Python 3.12.14, Transformers 4.57.6, PyTorch/Torchaudio 2.11.0+cu128, the Audio8 0.6B
  checkpoint, an RTX 5070 Ti, and an exact-transcript Edge reference. Clone rendering, forced
  restart, checkpoint preservation, and canonical WAV assembly passed.
- [x] Configured faster-whisper environment passes its real-model check. Verified 2026-09-29 with
  Python 3.13.5, `faster-whisper 1.2.1`, CTranslate2 4.8.2, PyAV 19.0.0, `tiny.en`, CPU/int8, and a
  known Edge-generated fixture whose two expected terms were recognized with word timings.
- [x] Local engine processes and model sessions are released after success, cancel, and failure.
  Deterministic session teardown covers all three outcomes and timeout restart; real Kokoro, Qwen,
  and Audio8 forced-restart gates confirm model ownership remains process/job scoped.

## 4. Build signed release candidates

Requirements are listed in [`../packaging/windows/README.md`](../packaging/windows/README.md).

```powershell
$ffmpegBin = uv run python .\packaging\windows\fetch_ffmpeg_release.py
.\packaging\windows\build.ps1 -Version 0.1.0 -FfmpegBin $ffmpegBin
.\packaging\windows\test-package.ps1 -Version 0.1.0
Get-Content .\dist\SPLICR-Studio-0.1.0-SHA256SUMS.txt
```

- [x] Portable ZIP, per-user installer, checksum file, `BUILD_INFO.txt`, third-party notices, and
  bundled FFmpeg license/source provenance are present. Verified for `0.1.0-dev.16` after a complete
  PyInstaller/Inno Setup 6.7.3 build with the pinned upstream `lgpl-shared` media-tool archive.
  That upstream label is superseded for compliance purposes by the static-FFTW GPL finding; the
  dev.16 package harness verifies the corrected metadata and terms.
- [x] Recompute every SHA-256 digest and compare it with the checksum file. The `0.1.0-dev.16`
  acceptance harness verified the manifest; final hashes are recorded in the evidence table below.
- [x] Run `packaging/windows/test-package.ps1` against the exact portable ZIP and installer. The
  `0.1.0-dev.16` run verified checksums, a Unicode/spaces portable path, an unchanged portable tree,
  redirected mutable state, installed package smoke, exact portable/install parity, the pinned
  shared FFmpeg configuration, all 124 dependency-license files, transitive static-FFTW GPL evidence,
  a real OpenH264/AAC MP4, application removal, and preserved user data. The packaging workflow runs
  this gate before upload and retains its schema-v2 machine-readable acceptance JSON.
- [x] Run the harness's optional prior-installer preflight. A development-workstation upgrade from
  `0.1.0-dev.4` to `0.1.0-dev.5` passed both frozen package smokes, kept an external user-data marker
  byte-identical, and left an installed application payload exactly matching the current portable
  package. Representative-job/profile/media migration in a clean VM remains required below.
- [ ] Publish the exact corresponding FFmpeg source and required attribution/source link, then
  complete the FFmpeg distribution checklist review. The current media DLLs are GPL-covered because
  enabled Chromaprint statically incorporates FFTW3; absence of FFmpeg's `--enable-gpl` flag does
  not override that transitive dependency. The exact
  FFmpeg, OpenH264, and BtbN recipe snapshots are now hash-pinned and assembled into a validated,
  explicitly incomplete primary-source audit kit. The exact 90-stage enabled dependency graph,
  source revisions, and fetch commands are versioned and validated. A digest-pinned, graph-verifying,
  resumable source collector and plan acceptance test now exist. A real pinned-image OpenH264 run
  verified archive integrity, the expected commit/license, checksums, fail-closed state, and resume
  reuse. Incremental bounded runs now cover 79 of 92 source locators and reconcile 384 detected
  license/notice candidates; the package manifest carries exact pinned ffnvcodec, dav1d, FriBidi,
  TwoLAME, AMF, OpenJPEG, Game Music Emu, GMP, Kvazaar, LCEVCdec, libvpx, libwebp, libzmq, and
  OpenCORE AMR, libudfread, oneVPL, PCRE2, pixman, Little CMS, OpenAL Soft, SoX Resampler, and
  uavs3d, Brotli, JPEG XL, Highway, Mbed TLS, TF-PSA-Crypto, librist, LV2, Serd, Zix, Sord, Sratom,
  Lilv, FFTW3, Chromaprint, LAME, Theora, Vorbis, libxml2, ZVBI, GNU libiconv, Fontconfig,
  Unicode, HarfBuzz, FreeType, aribb24, libaribcaption, libass, libbluray, OpenSSL, SVT-AV1, libva,
  VVenC, libplacebo, OpenCL, OpenMPT, Vulkan-Headers, Vulkan-Shim-Loader, Shaderc, glslang,
  SPIRV-Tools, SPIRV-Cross, SPIRV-Headers, libcurl, and SRT legal files rather than
  treating FFmpeg's own
  license as equivalent. Build-only static
  libraries absent from the distributed binary are tracked separately from source trees that recipes
  never build. The remaining full-graph run,
  notice review, correspondence validation, and hosted source link remain open in
  [`FFMPEG_DISTRIBUTION.md`](FFMPEG_DISTRIBUTION.md).
- [ ] Scan the installer and portable archive with the organization's selected malware scanner.
  Microsoft Defender's command-line scan returned `0x80004005` because the product/feature is
  disabled on this workstation; no scan result is claimed.
- [ ] If signing is configured, verify the Authenticode signature and timestamp. Signing is not
  configured for the internal development candidate.

## 5. Clean Windows VM matrix

Use a supported Windows x64 VM with no Python, Node.js, uv, FFmpeg, or prior SPLICR files. Take a VM
snapshot before the first install.

The 2026-09-29 development workstation cannot serve as that clean environment: Windows Sandbox is
not installed, and no Hyper-V, VirtualBox, VMware, or QEMU management CLI is available. Run this
matrix on a separate disposable Windows VM; do not relabel the development-workstation harness as
clean-VM evidence.

### Fresh installer

- [ ] Install as a standard user without elevation.
- [ ] Launch from Start, confirm the native lifecycle window opens Studio, and confirm a second launch
  reuses the running instance.
- [ ] Create/import a document, render with a bundled deterministic or configured provider, play the
  result, close the lifecycle window, reopen it, and confirm jobs/profiles/media persist.
- [ ] Exercise Audiogram and Convert using the bundled FFmpeg/FFprobe without changing `PATH`.

### Upgrade with existing data

- [ ] Record hashes of representative jobs, profiles, credentials metadata, and generated media under
  `%LOCALAPPDATA%\SPLICR Studio\data`.
- [ ] Install the next release over the previous one.
- [ ] Confirm schema migration succeeds once, old jobs reopen, resumable work continues from its
  checkpoint, secrets remain readable, and recorded user-data hashes are unchanged where migration
  was not expected.
- [ ] Confirm `%LOCALAPPDATA%\Programs\SPLICR Studio` contains only the new application version.

### Uninstall and reinstall policy

- [ ] Uninstall from Windows Settings and confirm application files/shortcuts are removed.
- [ ] Confirm `%LOCALAPPDATA%\SPLICR Studio\data` remains intentionally preserved.
- [ ] Reinstall and confirm the preserved Library, profiles, settings, and media reopen.
- [x] Document manual user-data removal separately; the uninstaller must not silently delete it.
  The Windows packaging guide now gives the backup/close/delete procedure and distinguishes app
  uninstall from permanent removal of `%LOCALAPPDATA%\SPLICR Studio\data`.

### Portable ZIP

- [x] Extract to a normal writable directory and launch without installing. The packaged executable
  passed `--package-smoke-test` on the development workstation.
- [x] Repeat from a path containing spaces and Unicode characters. The same packaged smoke passed
  from `.test-runs/Portable Test – résumé dev3`; this is not a substitute for clean-VM GUI testing.
- [x] Confirm the package does not write mutable data into its extraction directory. An isolated
  `0.1.0-dev.3` smoke run left all 1,121 packaged files unchanged and created its database/state
  only under the redirected per-user local-app-data root.
- [x] Confirm closing the lifecycle window stops its private server process. The actual frozen
  `0.1.0-dev.4` executable started its Tk lifecycle window and healthy service on loopback port
  8765; a normal window-close request exited with code 0 and made `/health` unreachable.

## 6. Publish and rollback

- [ ] Push a reviewed `vX.Y.Z` tag and confirm the Windows packaging workflow succeeds.
- [ ] Download the GitHub artifact, verify checksums again, and attach the approved files to the
  release.
- [ ] Publish concise install, upgrade, known-limit, and data-location notes.
- [ ] Keep the previous installer available until the new build passes the post-publish smoke test.
- [ ] Rollback means reinstalling the previous application package without deleting the shared user
  data directory; document any schema downgrade limitation before release.

## Evidence record

Rows through `0.1.0-dev.15` preserve the package evidence recorded at the time. Any wording there
that calls the upstream asset or configuration “LGPL” is superseded by the dev.16 Chromaprint/FFTW
finding: the same media DLLs are GPL-covered through statically incorporated FFTW3.

| Date | Commit/version | Environment | Gate | Result/evidence |
| --- | --- | --- | --- | --- |
| 2026-09-29 | `20cc182` | Windows development workstation | Deterministic Milestone 8 gate | 530 Python passed, 4 intentional live skips; 8 frontend unit and 6 Chromium journeys passed; Vite build and real FFmpeg formula/polar/alpha proof passed. |
| 2026-09-29 | `0.1.0-dev.2` working tree | Windows development workstation | Deterministic failure and frozen portable-package gate | 536 Python tests passed with 4 intentional live-environment skips. PyInstaller portable build passed its packaged executable smoke, including bundled FFmpeg/FFprobe discovery and an actual lazy-loaded NumPy/Pillow polar/formula/transparent audiogram frame. Portable ZIP SHA-256: `4023d860395f10ff47c2324f592f2e017833227708f8ca7ebb10595b5284fc41`. This is not a substitute for the clean-VM matrix below. |
| 2026-09-29 | `29c180f` + acceptance-doc update | Windows development workstation | Live Edge TTS contract | `edge-tts 7.2.8`, model `edge-tts`, voice `en-US-AriaNeural`; real service returned canonical 24 kHz mono signed-16-bit PCM and word-boundary timing metadata. |
| 2026-09-29 | `29c180f` + PyAV compatibility update | Windows development workstation | Real faster-whisper contract | Python 3.13.5, `faster-whisper 1.2.1`, CTranslate2 4.8.2, PyAV 19.0.0, `tiny.en`, CPU/int8; a known Edge-generated fixture produced positive duration, progress, segments, word timings, and both expected terms. Post-fix regression: 537 Python passed, 4 intentional live-environment skips. |
| 2026-09-29 | `e9a1ff8` + vault-backed live harness update | Windows development workstation | Live Inworld contract | Saved resource revision 1, `inworld-tts-2`, voice `Ashley`, current `/tts/v1/voice` endpoint; returned non-empty canonical 24 kHz mono signed-16-bit PCM without exporting or logging the credential. |
| 2026-09-29 | `e9a1ff8` + Kokoro lifecycle harness update | Windows development workstation | Real Kokoro lifecycle | Python 3.12.14, Kokoro 0.9.4, `af_heart`; Markdown import, exact preview plan, real render, forced restart, completed-checkpoint preservation, canonical WAV assembly, and API range playback passed. Expanded regression: 537 Python passed, 5 intentional opt-in live-environment skips. |
| 2026-09-29 | `47b6d19` | Windows development workstation with CUDA | Real Qwen design/clone/resume | Python 3.12.14, `qwen-tts 0.1.1`, PyTorch 2.11.0+cu128; VoiceDesign take 2 and 1.7B Base cloning passed with seed `424242`, five non-default sampling values, forced restart, frozen-control preservation, and unchanged completed-checkpoint hash/timestamp/attempt count. |
| 2026-09-29 | Audio8 lifecycle harness working tree | Windows development workstation with CUDA | Real Audio8 clone/resume | Python 3.12.14, Transformers 4.57.6, PyTorch/Torchaudio 2.11.0+cu128, Audio8 0.6B, RTX 5070 Ti; exact-transcript cloning, forced restart, completed-checkpoint preservation, and canonical WAV assembly passed. The live run also verified the current upstream processor/decoder API compatibility fix. Post-fix regression: 538 passed, 6 intentional opt-in live skips. |
| 2026-09-29 | Privacy/seam acceptance working tree | Windows development workstation | Privacy, real Edge seam, deterministic release gate | Diagnostic path redaction and the existing write-only secret/profile/browser audit passed. Real Edge source/revised WAVs and splice provenance were retained outside source control for listening. Current deterministic gates: 539 Python passed / 7 opt-in live skips; 8 frontend unit tests; Vite build; 6 Chromium journeys; 42 real FFmpeg/FFprobe tests. |
| 2026-09-29 | `dc6b965` / `0.1.0-dev.3` | Windows development workstation | Multi-gigabyte range-read and internal portable candidate | Full regression passed 540 Python tests with 7 intentional opt-in live skips. A sparse 3.9 GB canonical WAV returned bounded 1 KB ranges from the beginning, midpoint, and end. PyInstaller packaged smoke passed after extraction to a Unicode/spaces path. An isolated rerun left all 1,121 packaged files unchanged and wrote state only to the redirected per-user data root. Portable ZIP size: 220,690,342 bytes; independently verified SHA-256: `b2bb391bd572b695c094e4f668085a79c22f0bb53c2d40586d3d55ef5cdd76cd`. Internal acceptance only: installer, clean VM, signing, malware scan, and public-compatible FFmpeg licensing remain open. |
| 2026-09-29 | `0.1.0-dev.4` working tree | Windows development workstation | Frozen lifecycle and per-user installer acceptance | The frozen launcher gained and tested `--no-browser`. Its real Tk lifecycle window started a healthy private service on port 8765, accepted the normal close event, exited with code 0, and left `/health` unreachable. Inno Setup 6.7.3 built the per-user installer after SPLICR was fixed to discover user-scope installs and preserve a one-item path array. An isolated silent install placed the executable, notices, and build metadata; package smoke returned 0; silent uninstall returned 0, removed the application directory, and preserved external user data. Full regression: 543 passed, 7 intentional live skips. Portable: 220,689,908 bytes, SHA-256 `669f9f607e9f35d6fe8741af5fb646a3378b62305248ee2873d195abf42afbeb`. Installer: 151,418,758 bytes, SHA-256 `5d630e34271a0a1a2f57128c73474577f58e427460d6310bb4797518012a0ff2`. Internal acceptance only; clean-VM and public-release gates remain open. |
| 2026-09-29 | `0.1.0-dev.5` working tree | Windows development workstation | LGPL-shared media bundle and automated package/upgrade acceptance | Packaging fetched the pinned BtbN LGPL-shared archive, verified its upstream SHA-256, bundled FFmpeg/FFprobe plus seven required DLLs, and preserved its license and exact source record beside the tools. The packaged binary reports OpenH264 and no libx264. The reusable disposable-Windows harness passed the exact no-extra-arguments CI invocation: checksums matched, Unicode/spaces portable extraction remained byte-for-byte unchanged after smoke, mutable state stayed outside the package, installed smoke passed, a real 1-second H.264/AAC MP4 passed FFprobe, uninstall removed the app, and redirected user data survived. Its optional dev.4-to-dev.5 preflight also passed both frozen smokes, preserved a byte-identical external data marker, and proved the upgraded install contained exactly the dev.5 portable payload with no stale files. Evidence: `SPLICR-Studio-0.1.0-dev.5-Windows-x64-ACCEPTANCE.json`. Ruff passed; full regression passed 546 tests with 7 intentional live skips. Portable: 179,300,537 bytes, SHA-256 `bdf188b2db2ece4ee3f33b0bc59b7612497de92e5fa4c926ce9ba46f8fcfeef8`. Installer: 119,685,499 bytes, SHA-256 `5fe9d9bc36479da65ec879ac84ba111fff7f2ee313748c8fd131eeecbbb8e605`. Interactive clean-VM/representative-data migration, corresponding-source publication/review, signing, malware scan, and pushed CI evidence remain open. |
| 2026-09-29 | `3e887c0` plus acceptance record | Docker Desktop Linux engine through WSL | FFmpeg dependency source collector runtime/resume | The collector used pinned image digest `ce3051e9…`, fetched exact OpenH264 commit `8b2d28fa…`, wrote a valid 118,568,280-byte source archive containing `LICENSE` and the expected detached Git `HEAD`, and passed archive/plan/manifest checksums. Both corresponding-source and public-release flags remained false. A second identical invocation reported `Reusing` and retained the validated archive. The ignored evidence is `.test-runs/ffmpeg-source-collector-runtime`; the 85-source full graph remains open. |
| 2026-09-29 | `8f7f18a` | GitHub Actions `windows-2025` | Browser acceptance and retained failure diagnostics | Diagnostic run [`36664605914`](https://github.com/seabAu/Splicr/actions/runs/36664605914) emitted public Playwright annotations for missing `png_sequence` and finishing-asset capability and retained a 19 MB trace/screenshot/video artifact. The workflow now installs the same checksum-pinned LGPL FFmpeg/FFprobe bundle as packaging. Corrected run [`36665161955`](https://github.com/seabAu/Splicr/actions/runs/36665161955) then passed the production build and all six Chromium Studio journeys. |
| 2026-09-30 | `71ac44c`, `24b9b6b`, `bbd9854`, plus bounded-batch review | Docker Desktop Linux engine through WSL | FFmpeg dependency source/license evidence | A deterministic synthetic suite passed multi-candidate extraction, missing-candidate/no-source handling, stale-output cleanup, checksum/schema rejection, and repeat output. Real checksum-verified OpenH264, libogg, and zlib archives yielded `BSD-2-Clause`, `BSD-3-Clause`, and `Zlib` shipped-license records. CI byte-compares both mandatory binary notices to reviewed source hashes; zlib's acknowledgment is optional. Its Boost and Info-ZIP contrib candidates are explicitly recipe-proven not built. The real ordered three-stage batch reused every archive, and exact reconciliation covers all five detected candidates. The collector now maintains a default 12 GiB host/container reserve. Three of 92 locators are reviewed; the full graph remains open. |
| 2026-09-30 | `636a46a` / `0.1.0-dev.6` | Docker Desktop Linux engine through WSL, Windows development workstation, and GitHub Actions `windows-2025` | Eight-source license reconciliation, packaged dependency license, artifact acceptance, and browser acceptance | Eight cached graph-pinned source archives reconciled all 12 detected candidates to eight shipped licenses, one supplemental notice, and three recipe-proven not-built records. The real fetcher downloaded TwoLAME's exact LGPL-2.1-or-later `COPYING` file and verified SHA-256 `257a8427…`; the portable ZIP and installed payload both carried it. Package acceptance passed checksums, immutable portable smoke, redirected state, exact install parity, shared LGPL configuration, a real OpenH264/AAC MP4, uninstall removal, and user-data preservation. Portable: 183,855,038 bytes, SHA-256 `0aff4344c3bb0d3cca1dac385bff66a3d3cd91a852e2ca02e35e448909a93866`. Installer: 119,682,747 bytes, SHA-256 `240d3eb2a03533e87b02f6afcf32685ef65095b92c53bf2d3ff67feeb75da038`. Hosted browser run [`36670631733`](https://github.com/seabAu/Splicr/actions/runs/36670631733) passed the exact commit. Full source review/publication, clean-VM, signing, and malware gates remain open. |
| 2026-09-30 | `80898b0` / `f0666c4` / `0.1.0-dev.7` | Docker Desktop Linux engine through WSL, Windows development workstation, and GitHub Actions `windows-2025` | Twelve-source license reconciliation, artifact acceptance, and browser acceptance | The AMF, libffi, libpng, and OpenJPEG batch raised exact review coverage to 12 of 92 source locators and reconciled all 27 detected candidates: 12 shipped licenses, one supplemental notice, and 14 recipe-proven not-built records. The portable and installed payloads independently matched exact manifest-bound AMF (`eb297397…`), OpenJPEG (`a6af136f…`), and TwoLAME (`257a8427…`) license files. Acceptance passed checksums, immutable portable smoke, redirected state, exact install parity, shared LGPL configuration, a real OpenH264/AAC MP4, uninstall removal, and user-data preservation. Portable: 183,857,130 bytes, SHA-256 `ab56228909d21da25ff76747bb8dc7bf100428deebbdcc19f1014f204ea3ae3d`. Installer: 119,691,072 bytes, SHA-256 `086d942cb8637bb2b381ca1811562bcc5dd8ae5ff412be729c03c13aac48683f`. Hosted browser run [`36722600815`](https://github.com/seabAu/Splicr/actions/runs/36722600815) passed all six Studio journeys on the exact acceptance-record commit. Full source review/publication, clean-VM, signing, and malware gates remain open. |
| 2026-09-30 | `627f70f` / `a4617bc` / `0.1.0-dev.8` | Docker Desktop Linux engine through WSL, Windows development workstation, and GitHub Actions `windows-2025` | Sixteen-source license reconciliation, artifact acceptance, and browser acceptance | The dav1d, FFTW3, FriBidi, and libsamplerate batch raised exact review coverage to 16 of 92 source locators and reconciled all 35 detected candidates: 14 shipped licenses, two supplemental notices, 14 recipe-proven not-built records, and five build-only/not-shipped records. The portable and installed payloads independently matched all six manifest-bound dependency files, including dav1d's BSD license (`dd92c3c2…`) and required AOMedia patent license (`335eca57…`) plus FriBidi's LGPL-2.1-or-later text (`20e50fe7…`). Acceptance passed checksums, immutable portable smoke, redirected state, exact install parity, shared LGPL configuration, a real OpenH264/AAC MP4, uninstall removal, and user-data preservation. Portable: 183,871,741 bytes, SHA-256 `3782043b33e9b61cde8a4667de8030f7ba8df2b09cc0556bf3b8e7fd040ff438`. Installer: 119,689,131 bytes, SHA-256 `c4ce94060f09755fdbad461804191e4b2dc50e93710fca2827eb03b0d3d28529`. Hosted browser run [`36728460149`](https://github.com/seabAu/Splicr/actions/runs/36728460149) passed all six Studio journeys on the exact acceptance-record commit. Full source review/publication, clean-VM, signing, and malware gates remain open. |
| 2026-09-30 | `70d43fb` / `1653ec9` / `0.1.0-dev.9` | Docker Desktop Linux engine through WSL, Windows development workstation, and GitHub Actions `windows-2025` | Nineteen-source embedded-license reconciliation, artifact acceptance, and browser acceptance | A supplemental-path manifest brought all 15 ffnvcodec license-bearing headers into deterministic inventory. Five primary MIT headers used by FFmpeg 9 are exact package files; ten older compatibility-branch headers are proven not built. All 50 reviewed candidates reconcile exactly. Portable/install acceptance verified all 11 manifest-bound dependency files plus the existing media and lifecycle checks. Portable: 183,962,118 bytes, SHA-256 `5f909c8fa64223d5874b951d237b9400d1774bdf2b915fd8245acbde164d0fb3`. Installer: 119,758,148 bytes, SHA-256 `6f8ab579a80c0199039397f79d5470ec447681bc057fc6e4ba9d4425d86235b4`. Hosted browser run [`36735091359`](https://github.com/seabAu/Splicr/actions/runs/36735091359) passed all six Studio journeys on the exact acceptance-record commit. Full source review/publication, clean-VM, signing, and malware gates remain open. |
| 2026-09-30 | `142e4a3` / `a561216` / `0.1.0-dev.10` | Docker Desktop Linux engine through WSL, Windows development workstation, and GitHub Actions `windows-2025` | Twenty-three-source license reconciliation, artifact acceptance, and browser acceptance | The Game Music Emu, GMP, Kvazaar, and LCEVCdec batch raised exact review coverage to 23 of 92 source locators and reconciled all 69 candidates: 24 shipped licenses, five supplemental notices, 35 recipe-proven not-built records, and five build-only/not-shipped records. Portable/install acceptance independently matched all 19 manifest-bound legal files and passed the existing checksum, immutable portable, redirected state, exact install parity, shared LGPL configuration, real OpenH264/AAC MP4, uninstall-removal, and user-data-preservation checks. Portable: 179,457,649 bytes, SHA-256 `4cd9362f2dfd1a705c4c931c27cbf4abd600db0dd64085dc67c4d56f58992600`. Installer: 119,772,412 bytes, SHA-256 `dfa8538d839b1d92bb267802358b1fa91d843bfe6d7f243a210cf55498d8d83e`. Hosted browser run [`36741351275`](https://github.com/seabAu/Splicr/actions/runs/36741351275) passed all six Studio journeys on the exact acceptance-record commit: workspace rendering, Audiogram still/alpha preview, durable Library batch queues, Convert transcription packages, document plan/direct/render/play/reopen, and durable Voice Studio identity/new-take generation. Full source review/publication, clean-VM, signing, malware, and patent-review gates remain open. |
| 2026-09-30 | `427b041` / `d4d76f7` / `0.1.0-dev.11` | Docker Desktop Linux engine through WSL, Windows development workstation, and GitHub Actions `windows-2025` | Twenty-seven-source license reconciliation, artifact acceptance, and browser acceptance | The libvpx, libwebp, libzmq, and OpenCORE AMR batch raised exact review coverage to 27 of 92 source locators and reconciled all 87 candidates: 30 shipped licenses, nine supplemental notices, 43 recipe-proven not-built records, and five build-only/not-shipped records. Portable/install acceptance independently matched all 29 manifest-bound legal files and passed checksum, immutable portable, redirected-state, exact install-parity, shared-LGPL configuration, real OpenH264/AAC MP4, uninstall-removal, and user-data-preservation checks. Portable: 184,019,594 bytes, SHA-256 `dee4fc3e1f0207745ff56da2c453ae3c7cc23287f59268820eaa8d8a16667cb5`. Installer: 119,763,218 bytes, SHA-256 `76080ed5db35f53e23db289f15992e4111adcc01e5ab969e5d7d070343e8bf45`. Hosted browser run [`36747089346`](https://github.com/seabAu/Splicr/actions/runs/36747089346) passed all six Studio journeys on the exact acceptance-record commit. Full source review/publication, clean-VM, signing, malware, and patent-review gates remain open. |
| 2026-09-30 | `f0729ba` / `2b54b3c` / `0.1.0-dev.12` | Docker Desktop Linux engine through WSL, Windows development workstation, and GitHub Actions `windows-2025` | Thirty-one-source license reconciliation, artifact acceptance, and browser acceptance | The libudfread, oneVPL, PCRE2, and pixman batch raised exact review coverage to 31 of 92 source locators and reconciled all 108 candidates: 34 shipped licenses, ten supplemental notices, 59 recipe-proven not-built records, and five build-only/not-shipped records. Portable/install acceptance independently matched all 34 manifest-bound legal files and passed checksum, immutable portable, redirected-state, exact install-parity, shared-LGPL configuration, real OpenH264/AAC MP4, uninstall-removal, and user-data-preservation checks. Portable: 184,033,332 bytes, SHA-256 `1a3eaadc64adb95c5edcf1bdabe888c1c159e4e02a2841a95943628edc3248a3`. Installer: 119,776,073 bytes, SHA-256 `fc635920ecb80a4bc7617418bbdb2791f9628848f7b42480b3ea0d5d9b76c46a`. Hosted browser run [`36753606918`](https://github.com/seabAu/Splicr/actions/runs/36753606918) passed all six Studio journeys in 41.7 seconds on the exact acceptance-record commit. Full source review/publication, clean-VM, signing, malware, and patent-review gates remain open. |
| 2026-09-30 | `876208e` / `32deb7a` / `0.1.0-dev.13` | Docker Desktop Linux engine through WSL, Windows development workstation, and GitHub Actions `windows-2025` | Thirty-five-source license reconciliation, artifact acceptance, and browser acceptance | The Little CMS, OpenAL Soft, SoX Resampler, and uavs3d batch raised exact review coverage to 35 of 92 source locators and reconciled all 123 candidates: 44 shipped licenses, eleven supplemental notices, 61 recipe-proven not-built records, and seven build-only/not-shipped records. Portable/install acceptance independently matched all 45 manifest-bound legal files and passed checksum, immutable portable, redirected-state, exact install-parity, shared-LGPL configuration, real OpenH264/AAC MP4, uninstall-removal, and user-data-preservation checks. Portable: 184,080,845 bytes, SHA-256 `f8a1897604e803c60aa9b030147c91d6d3bf2b8498e18f5c0ab429cbeaa8012b`. Installer: 119,799,278 bytes, SHA-256 `ac3dbce78deb68d1de3b642b57512af8e5b3d72fd0fa693acab3207435387077`. Hosted browser run [`36757811792`](https://github.com/seabAu/Splicr/actions/runs/36757811792) passed all six Studio journeys in 50.3 seconds on the exact acceptance-record commit. Full source review/publication, AVS3 patent review, clean-VM, signing, and malware gates remain open. |
| 2026-09-30 | `a158bc1` / `be38ad8` / `0.1.0-dev.14` | Docker Desktop Linux engine through WSL, Windows development workstation, and GitHub Actions `windows-2025` | Thirty-nine-source license reconciliation, artifact acceptance, and browser acceptance | The Brotli, JPEG XL, Mbed TLS, and librist batch raised exact review coverage to 39 of 92 source locators and reconciled all 140 candidates: 51 shipped licenses, twelve supplemental notices, 68 recipe-proven not-built records, and nine build-only/not-shipped records. The downloader SHA-256-verified all 53 manifest files, including a safe graph-pinned `v4.2.0` release tag and a byte-identical commit-pinned librist mirror. Portable/install acceptance independently matched those 53 files and passed checksum, immutable portable, redirected-state, exact install-parity, shared-LGPL configuration, real OpenH264/AAC MP4, uninstall-removal, and user-data-preservation checks. Portable: 184,112,355 bytes, SHA-256 `cbd438b17494bb77f47aa7cc859852f6e3eac0b5f9a5ae9ae04eda7cf416db89`. Installer: 119,796,443 bytes, SHA-256 `9d5b96a33b8e6c5e2cf7d3d777d01a020cad3913ceb523108723f62cebec16cd`. Hosted browser run [`36761944917`](https://github.com/seabAu/Splicr/actions/runs/36761944917) passed all six Studio journeys in 44.2 seconds on the exact acceptance-record commit. Full source review/publication, codec patent review, clean-VM, signing, and malware gates remain open. |
| 2026-09-30 | `ca7df57` / `8e33227` / `0.1.0-dev.15` | Docker Desktop Linux engine through WSL, Windows development workstation, and GitHub Actions `windows-2025` | Forty-five-source license reconciliation, artifact acceptance, and browser acceptance | The LV2, Serd, Zix, Sord, Sratom, and Lilv batch raised exact review coverage to 45 of 92 source locators and reconciled all 168 candidates: 58 shipped licenses, twelve supplemental notices, 74 recipe-proven not-built records, and 24 build-only/not-shipped records. The inventory now safely resolves relative in-archive license symlinks and rejects archive-root escapes; deterministic positive and negative fixtures cover both paths. The downloader SHA-256-verified all 60 manifest files. Portable/install acceptance independently matched those 60 files and passed checksum, immutable portable, redirected-state, exact install-parity, shared-LGPL configuration, real OpenH264/AAC MP4, uninstall-removal, and user-data-preservation checks. Portable: 184,117,989 bytes, SHA-256 `1f43bb56bad037d0a8eab3a5d07169af50d22018d793f7d683a773b59da44520`. Installer: 119,792,944 bytes, SHA-256 `690a7c09b2cecbc27c85852fdb8f7bab78359fb94a77ab914599ee851954a6bc`. Hosted browser run [`36765143610`](https://github.com/seabAu/Splicr/actions/runs/36765143610) passed all six Studio journeys in 43.6 seconds on the exact acceptance-record commit. Full source review/publication, codec patent review, clean-VM, signing, and malware gates remain open. |
| 2026-09-30 | `0.1.0-dev.16` working tree | Docker Desktop Linux engine through WSL and Windows development workstation | Forty-nine-source reconciliation and manual package-acceptance fallback | Chromaprint, LAME, Theora, and Vorbis raised review coverage to 49 of 92 locators and reconciled all 180 candidates: 63 shipped licenses, fifteen supplemental notices, 81 not-built records, and 21 build-only/not-shipped records. The review corrected FFTW3 to statically incorporated GPL-2.0-or-later code. Exact-batch/global validators passed and all 68 manifest files fetched and hash-verified. The real artifacts passed independently recomputed checksums, Unicode-path portable smoke, unchanged portable tree, exact installed/portable parity, all 68 legal files, Chromaprint/static-pkg-config configuration, a single avformat DLL with embedded FFTW marker and no FFTW DLL, real OpenH264/AAC MP4, uninstall removal, and user-data preservation. Portable: 184,141,042 bytes, SHA-256 `9c0b6547f603c32a31b9e77775ecf9b49dca57eeed76cad4fa274470a9e5ca02`. Installer: 119,790,595 bytes, SHA-256 `8896abea52a3b9ffbb1a8223e8551c005b9f452eb826420fb90fd8aee421a348`. Bitdefender denied read/execute access to the tracked `test-package.ps1`; therefore the normal harness-emitted acceptance JSON and hosted browser run remain open. |
| 2026-10-01 | `b8d5eea` / `9e3d8ee` / `0.1.0-dev.16` | Windows 10.0.19045 development workstation and GitHub Actions `windows-2025` | Tracked package/browser acceptance and fifty-nine-source reconciliation | The libxml2, XZ/liblzma, SDL2, ZVBI, GNU libiconv, Fontconfig, HarfBuzz, and bootstrap/final FreeType promotions raised exact review coverage to 59 of 92 locators and 232 candidates: 72 shipped licenses, 23 supplemental notices, 93 not-built records, and 44 build-only/not-shipped records. All 83 manifest files fetched and hash-verified; the companion manifest binds Fontconfig's separate Unicode-3.0 terms to its reviewed source candidate. The fetch path moved to a bounded standard-library Python implementation after the security suite quarantined newly written PowerShell downloaders; it retains pinned revisions, explicit transport decoding, timeouts, retries, and fail-closed hashes. The rebuilt artifacts passed the elevated tracked schema-v2 harness under PowerShell 7 end to end at `2026-10-01T19:13:26.1898884Z`, including checksums, Unicode/spaces portable smoke, unchanged portable contents, redirected state, exact portable/install parity, all 83 pinned dependency-license files, static FFTW evidence, OpenH264/AAC MP4, application removal, and user-data preservation. Portable: 184,202,955 bytes, SHA-256 `b2dad13acef808cafed5f40b326827b0042e12daf8b011feb0aa3344d821c532`. Installer: 119,829,501 bytes, SHA-256 `43266d10023515a62264200e8c697b8f1f5febcdae8d99a380bf65de454a61df`. Hosted browser run [`36913670670`](https://github.com/seabAu/Splicr/actions/runs/36913670670) passed all six Studio journeys in 45.8 seconds on commit `9e3d8ee`. Clean-VM, signing/malware, live-provider, and corresponding-source publication gates remain open. Windows PowerShell 5 misparses the harness's UTF-8-without-BOM Unicode-path literal; the ASCII-only `[char]` source correction remains pending until the protected script is writable through the safe patch path. |
| 2026-10-01 | `0575c89` / `0.1.0-dev.16` | Windows 10.0.19045 development workstation and GitHub Actions `windows-2025` | Sixty-three-source reconciliation and package/browser acceptance | The aribb24, libaribcaption, libass, and libbluray batch raised exact review coverage to 63 of 92 locators and 249 candidates: 78 shipped licenses, 28 supplemental notices, 98 not-built records, and 45 build-only/not-shipped records. All 92 manifest files fetched from revision-pinned upstream URLs and hash-verified. The rebuilt artifacts passed the tracked schema-v2 harness at `2026-10-01T19:47:14.9958555Z`, including checksums, Unicode/spaces portable smoke, unchanged portable contents, redirected state, exact portable/install parity, all 92 dependency-license files, static FFTW evidence, OpenH264/AAC MP4, application removal, and user-data preservation. Portable: 184,241,112 bytes, SHA-256 `efd590cb5321c3dc1cf62bfb9e88f50c8ed939b989eec26a5beab6fe9eccb854`. Installer: 119,839,389 bytes, SHA-256 `ed928b4b0e0f54de2c525fcef98abd22f02131b5bc3b428709a38c0d8817c21c`. Hosted browser run [`36917251299`](https://github.com/seabAu/Splicr/actions/runs/36917251299) passed all six Studio journeys in 41.3 seconds on commit `0575c89`. Clean-VM, signing/malware, live-provider, and corresponding-source publication gates remain open. |
| 2026-10-01 | `950b0c1` / `0.1.0-dev.16` | Windows 10.0.19045 development workstation and GitHub Actions `windows-2025` | Sixty-four-source reconciliation and package/browser acceptance | The OpenSSL batch raised exact review coverage to 64 of 92 locators and 253 candidates: 79 shipped licenses, 28 supplemental notices, 101 not-built records, and 45 build-only/not-shipped records. All 93 manifest files fetched from revision-pinned upstream URLs and hash-verified. The rebuilt artifacts passed the tracked schema-v2 harness at `2026-10-01T20:10:25.1161132Z`, including checksums, Unicode/spaces portable smoke, unchanged portable contents, redirected state, exact portable/install parity, all 93 dependency-license files, static FFTW evidence, OpenH264/AAC MP4, application removal, and user-data preservation. Portable: 184,245,775 bytes, SHA-256 `75cae844c1b909cd56bcba8af99529dce9491c8090fcf6ea1d8334747c2a82ae`. Installer: 119,844,402 bytes, SHA-256 `3c5bfc0b049fb3bd0e0c8a53567fc199d1b8758dbb134c61d518aa52f82200df`. Hosted browser run [`36919996114`](https://github.com/seabAu/Splicr/actions/runs/36919996114) passed all six Studio journeys in 53.8 seconds on commit `950b0c1`. Clean-VM, signing/malware, live-provider, and corresponding-source publication gates remain open. |
| 2026-10-01 | `e76e3e5` / `0.1.0-dev.16` | Windows 10.0.19045 development workstation and GitHub Actions `windows-2025` | Sixty-seven-source reconciliation and package/browser acceptance | The SVT-AV1, libva, and VVenC batch raised exact review coverage to 67 of 92 locators and 262 candidates: 86 shipped licenses, 29 supplemental notices, 101 not-built records, and 46 build-only/not-shipped records. Eight revision-pinned legal files brought the manifest to 101 records. The rebuilt artifacts passed the tracked schema-v2 harness at `2026-10-01T20:38:38.9403150Z`, including checksums, Unicode/spaces portable smoke, unchanged portable contents, redirected state, exact portable/install parity, all 101 dependency-license files, static FFTW evidence, OpenH264/AAC MP4, application removal, and user-data preservation. Portable: 184,254,515 bytes, SHA-256 `9a235c9a3e764fb512a718036e3fb98bc0edf73d990a8a1ea1ed15386b5f3607`. Installer: 119,848,157 bytes, SHA-256 `e22916cb52b474451b49e7d7931eddeda3f3465a3f7ff78aada8bcfc1006d9dc`. Hosted browser run [`36923571926`](https://github.com/seabAu/Splicr/actions/runs/36923571926) passed all six Studio journeys in 44.1 seconds on commit `e76e3e5`. rav1e remains unresolved until its time-dependent Cargo dependency closure is completely notice-reconciled. Clean-VM, signing/malware, live-provider, and corresponding-source publication gates remain open. |
| 2026-10-01 | `13ff415` / `0.1.0-dev.16` | Windows 10.0.19045 development workstation and GitHub Actions `windows-2025` | Sixty-eight-source reconciliation and package/browser acceptance | The libplacebo batch raised exact review coverage to 68 of 92 locators and 283 candidates: 96 shipped licenses, 33 supplemental notices, 104 not-built records, and 50 build-only/not-shipped records. Fourteen revision-pinned legal files brought the manifest to 115 records. Recursive submodule licenses are bound to their own immutable commits. The rebuilt artifacts passed the tracked schema-v2 harness at `2026-10-01T21:01:26.4972742Z`, including checksums, Unicode/spaces portable smoke, unchanged portable contents, redirected state, exact portable/install parity, all 115 dependency-license files, static FFTW evidence, OpenH264/AAC MP4, application removal, and user-data preservation. Portable: 184,313,166 bytes, SHA-256 `aba0200ad839480fb8b1354d93b4d4f06f5a390de2c325ca1aab330651a6bf25`. Installer: 119,873,387 bytes, SHA-256 `4899de203fd0ea1007e679df9959112868f70a2b44b24bed25a7955208b9854c`. Hosted browser run [`36927179317`](https://github.com/seabAu/Splicr/actions/runs/36927179317) passed all six Studio journeys in 42.1 seconds on implementation commit `13ff415`. Clean-VM, signing/malware, live-provider, and corresponding-source publication gates remain open. |
| 2026-10-01 | `b18f7d4` / `0.1.0-dev.16` | Windows 10.0.19045 development workstation and GitHub Actions `windows-2025` | Seventy-one-source reconciliation and package/browser acceptance | The OpenCL-Headers, OpenCL-ICD-Loader, and OpenMPT batch raised exact review coverage to 71 of 92 locators and 328 candidates: 101 shipped licenses, 37 supplemental notices, 140 not-built records, and 50 build-only/not-shipped records. Nine revision-pinned legal files brought the manifest to 124 records. The real downloader fetched and hash-verified every record. The rebuilt artifacts passed the tracked schema-v2 harness at `2026-10-01T21:31:28.4930829Z`, including checksums, Unicode/spaces portable smoke, unchanged portable contents, redirected state, exact portable/install parity, all 124 dependency-license files, static FFTW evidence, OpenH264/AAC MP4, application removal, and user-data preservation. Portable: 184,352,521 bytes, SHA-256 `d534fe19b863baf808d368693a26b9a9fda6391b3cb4e70fab8dbaa4e04b6b4f`. Installer: 119,891,255 bytes, SHA-256 `f08f504073be7a42bac4b7b29a0d6e9764a1d9d35548aa1ebcfa8516acddb816`. Hosted browser run [`36929574347`](https://github.com/seabAu/Splicr/actions/runs/36929574347) passed all six Studio journeys in 43.9 seconds on implementation commit `b18f7d4`. Clean-VM, signing/malware, live-provider, and corresponding-source publication gates remain open. |
| 2026-10-01 | `fdff678` / `0.1.0-dev.16` | Windows 10.0.19045 development workstation and GitHub Actions `windows-2025` | Seventy-seven-source reconciliation and package/browser acceptance | The Vulkan-Headers, Vulkan-Shim-Loader, Shaderc/glslang/SPIRV-Tools, SPIRV-Cross, and standalone SPIRV-Headers batch raised exact review coverage to 77 of 92 locators and 371 candidates: 123 shipped licenses, 43 supplemental notices, 148 not-built records, and 57 build-only/not-shipped records. Twenty-eight revision-pinned legal files brought the manifest to 152 records. The real downloader fetched and hash-verified every record. The rebuilt artifacts passed the tracked schema-v2 harness at `2026-10-01T21:55:20.5653230Z`, including checksums, Unicode/spaces portable smoke, unchanged portable contents, redirected state, exact portable/install parity, all 152 dependency-license files, static FFTW evidence, OpenH264/AAC MP4, application removal, and user-data preservation. Portable: 184,579,105 bytes, SHA-256 `2df198360b03a74ebd21617d10d35091022bf444946295e5901c87bdd1e67f8d`. Installer: 119,997,991 bytes, SHA-256 `859418fce2d738cd8ca33a87ff6dfcfee3ec41de478aff0398f6a034366199ae`. Hosted browser run [`36932068565`](https://github.com/seabAu/Splicr/actions/runs/36932068565) passed all six Studio journeys in 44.4 seconds on implementation commit `fdff678`. Clean-VM, signing/malware, live-provider, and corresponding-source publication gates remain open. |
| 2026-10-01 | `0.1.0-dev.16` working tree | Windows 10.0.19045 development workstation | Seventy-nine-source reconciliation and package acceptance | The independently complete libcurl and SRT subset raised exact review coverage to 79 of 92 locators and 384 candidates: 128 shipped licenses, 48 supplemental notices, 151 not-built records, and 57 build-only/not-shipped records. Ten revision-pinned legal files brought the manifest to 162 records. The real downloader fetched and hash-verified every record. The rebuilt artifacts passed the tracked schema-v2 harness at `2026-10-01T22:13:42.0809380Z`, including checksums, Unicode/spaces portable smoke, unchanged portable contents, redirected state, exact portable/install parity, all 162 dependency-license files, static FFTW evidence, OpenH264/AAC MP4, application removal, and user-data preservation. Portable: 184,648,770 bytes, SHA-256 `457447fa80315530fe7a631c90788af879fa023e3cf6de1c3c96d072511aaeeb`. Installer: 120,032,060 bytes, SHA-256 `221cc01dab433076127f71f0f1e0d6f096bf6e7557ee015294a128ece219231b`. libssh remains deferred until a real build log or link map resolves its conditional MinGW object selection. Hosted browser acceptance is pending on the exact implementation commit. Clean-VM, signing/malware, live-provider, and corresponding-source publication gates remain open. |
| Pending | Pending | Clean Windows x64 VM | Fresh install / upgrade / uninstall / portable | Record artifact hashes, Windows version, install paths, and observations here. |
| Pending | Pending | GitHub Actions `windows-2025` | Package workflow | Link the successful package run and approved retained artifacts when available. |

