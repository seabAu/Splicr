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
  public distribution remains blocked until an LGPL build is substituted or complete GPL
  compliance materials are deliberately supplied.
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
$ffmpegBin = .\packaging\windows\fetch-ffmpeg-lgpl.ps1
.\packaging\windows\build.ps1 -Version 0.1.0 -FfmpegBin $ffmpegBin
.\packaging\windows\test-package.ps1 -Version 0.1.0
Get-Content .\dist\SPLICR-Studio-0.1.0-SHA256SUMS.txt
```

- [x] Portable ZIP, per-user installer, checksum file, `BUILD_INFO.txt`, third-party notices, and
  bundled FFmpeg license/source provenance are present. Verified for `0.1.0-dev.5` after a complete
  PyInstaller/Inno Setup 6.7.3 build with the pinned LGPL-shared media-tool archive.
- [x] Recompute every SHA-256 digest and compare it with the checksum file. Verified independently
  with `certutil` for `0.1.0-dev.5`; final hashes are recorded in the evidence table below.
- [x] Run `packaging/windows/test-package.ps1` against the exact portable ZIP and installer. The
  `0.1.0-dev.5` run verified checksums, a Unicode/spaces portable path, an unchanged portable tree,
  redirected mutable state, installed package smoke, the pinned shared FFmpeg configuration, a real
  OpenH264/AAC MP4, application removal, and preserved user data. The packaging workflow runs this
  gate before upload and retains its machine-readable acceptance JSON.
- [x] Run the harness's optional prior-installer preflight. A development-workstation upgrade from
  `0.1.0-dev.4` to `0.1.0-dev.5` passed both frozen package smokes, kept an external user-data marker
  byte-identical, and left an installed application payload exactly matching the current portable
  package. Representative-job/profile/media migration in a clean VM remains required below.
- [ ] Publish the exact corresponding FFmpeg source and required attribution/source link, then
  complete the FFmpeg distribution checklist review. The GPL-enabled binary blocker is removed,
  but the remaining LGPL compliance publication step is still a public-release gate. The exact
  FFmpeg, OpenH264, and BtbN recipe snapshots are now hash-pinned and assembled into a validated,
  explicitly incomplete primary-source audit kit. The exact 90-stage enabled dependency graph,
  source revisions, and fetch commands are versioned and validated. A digest-pinned, graph-verifying,
  resumable source collector and plan acceptance test now exist. A real pinned-image OpenH264 run
  verified archive integrity, the expected commit/license, checksums, fail-closed state, and resume
  reuse. Incremental bounded runs now cover 12 of 92 source locators and reconcile 27 detected
  license/notice candidates; the package also carries exact pinned TwoLAME, AMF, and OpenJPEG
  license files rather than treating FFmpeg's own license as equivalent. The remaining full-graph run,
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
| Pending | Pending | Clean Windows x64 VM | Fresh install / upgrade / uninstall / portable | Record artifact hashes, Windows version, install paths, and observations here. |
| Pending | Pending | GitHub Actions `windows-2025` | Package workflow | Link the successful package run and approved retained artifacts when available. |

