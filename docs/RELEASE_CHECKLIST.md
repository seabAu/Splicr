# SPLICR Studio release checklist

This is the reproducible release gate for the merged local SPLICR Studio application. Keep the
checkboxes and evidence table current; do not infer that a clean-machine or live-provider check
passed from unit tests alone.

## 1. Prepare the release commit

- [ ] Confirm `git status --short` contains only intended release changes.
- [ ] Update the version in `pyproject.toml` and the package workflow input/tag.
- [ ] Update `CHANGELOG.md` or the release notes with migrations, known limitations, and provider or
  model changes.
- [ ] Review `packaging/windows/THIRD_PARTY_NOTICES.md`, especially the exact FFmpeg distribution
  bundled for this build.
- [ ] Confirm no API keys, model files, generated media, job databases, `.env` files, or virtual
  environments are tracked.

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

- [ ] Python suite passes with only documented opt-in live-environment skips.
- [ ] Frontend unit suite and production build pass.
- [ ] Every Chromium journey passes without console/page errors.
- [ ] If Chromium fails, retain `studio-web/playwright-report/` and
  `studio-web/test-results/` (trace, screenshot, and video).
- [ ] Real FFmpeg/FFprobe smoke tests ran rather than being skipped.

## 3. Run deliberate live checks

Use small, non-sensitive fixtures and record provider, model, voice, date, SPLICR commit, and result.
Never paste credentials into the evidence table.

```powershell
$env:SPLICR_LIVE_PROVIDER = "gemini" # then deepgram / inworld
uv run pytest -m live_provider tests/test_live_provider_acceptance.py

uv run pytest -m live_engine tests/test_live_edge_provider.py
uv run pytest -m live_engine tests/test_live_qwen_voice_design.py
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
- [ ] Configured Qwen3-TTS environment passes its applicable end-to-end checks.
- [ ] Configured Audio8 environment passes its applicable end-to-end checks.
- [x] Configured faster-whisper environment passes its real-model check. Verified 2026-09-29 with
  Python 3.13.5, `faster-whisper 1.2.1`, CTranslate2 4.8.2, PyAV 19.0.0, `tiny.en`, CPU/int8, and a
  known Edge-generated fixture whose two expected terms were recognized with word timings.
- [ ] Local engine processes and model sessions are released after success, cancel, and failure.

## 4. Build signed release candidates

Requirements are listed in [`../packaging/windows/README.md`](../packaging/windows/README.md).

```powershell
.\packaging\windows\build.ps1 -Version 0.1.0
Get-Content .\dist\SPLICR-Studio-0.1.0-SHA256SUMS.txt
```

- [ ] Portable ZIP, per-user installer, checksum file, `BUILD_INFO.txt`, and third-party notices are
  present.
- [ ] Recompute every SHA-256 digest and compare it with the checksum file.
- [ ] Scan the installer and portable archive with the organization's selected malware scanner.
- [ ] If signing is configured, verify the Authenticode signature and timestamp.

## 5. Clean Windows VM matrix

Use a supported Windows x64 VM with no Python, Node.js, uv, FFmpeg, or prior SPLICR files. Take a VM
snapshot before the first install.

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
- [ ] Document manual user-data removal separately; the uninstaller must not silently delete it.

### Portable ZIP

- [ ] Extract to a normal writable directory and launch without installing.
- [ ] Repeat from a path containing spaces and Unicode characters.
- [ ] Confirm the package does not write mutable data into its extraction directory.
- [ ] Confirm closing the lifecycle window stops its private server process.

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
| Pending | Pending | Clean Windows x64 VM | Fresh install / upgrade / uninstall / portable | Record artifact hashes, Windows version, install paths, and observations here. |
| Pending | Pending | GitHub Actions `windows-2025` | Browser/package workflows | Link successful workflow runs and retained failure artifacts when applicable. |

