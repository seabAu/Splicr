# Changelog

All notable SPLICR Studio changes are recorded here. The project follows semantic versioning once
public release tags begin; the current section describes the unreleased Narrator merger candidate.

## Unreleased — SPLICR Studio / Narrator merger

### Added

- A progressive-disclosure React Studio covering Narrate, Library, Dialogue, Timeline, Voice
  Studio, Pronunciation, Components, Audiogram, Publish, Convert, and error history workflows.
- Durable projects, immutable render plans, takes, checkpointed chunks, restart recovery, batch
  queues, profiles, and range-capable in-progress/completed playback.
- Provider-neutral remote resources for Gemini, Deepgram, Inworld, and configurable REST TTS APIs,
  with write-only vault-backed credentials and revision-frozen request templates.
- Isolated local-engine adapters for Kokoro, Qwen3-TTS, Audio8, Edge TTS, and faster-whisper.
- Explicit Components-based Windows x64 engine setup with private Python, isolated CPU/NVIDIA
  recipes, download consent, disk preflight, import/native-library checks, live logs, cancellation,
  durable retry and next-restart activation; connecting existing environments remains supported.
- Markdown, Word, OpenDocument, text, and JSON import; semantic/heading/newline planning; numeric
  citation removal; chunk preview; structured progress; partial export; and detailed error recovery.
- Voice design/cloning, sentence-level non-destructive revision, subtitles/chapters, audio
  conversion, intro/outro finishing, and formula/polar/transparent audiogram rendering.
- Windows portable/installer build automation with bundled FFmpeg discovery, checksums, build
  metadata, supervised browser acceptance, packaged-executable smoke tests, and a headless
  `--no-browser` launcher mode for deployment and lifecycle acceptance.
- Reproducible Windows media-tool acquisition pinned to a checksum-verified BtbN build whose
  upstream asset is named `lgpl-shared`, including its shared DLLs, exact source/provenance record,
  and the later effective-GPL finding caused by statically incorporated FFTW through Chromaprint.
- A disposable-Windows artifact acceptance harness that verifies checksums, portable isolation,
  installed package smoke, real native lifecycle/loopback-service behavior, bundled-media
  conversion and audiogram rendering, real OpenH264/AAC output, representative state across
  uninstall/reinstall, exact installed-payload contents, and prior-version upgrade preservation
  before CI uploads the release candidate and its evidence JSON.
- A fail-closed FFmpeg corresponding-source kit with checksum-pinned FFmpeg, OpenH264, BtbN recipe,
  exact 90-stage enabled graph, 85 source archives, reviewed legal material, patches, build logs, and
  offline rebuild evidence. Its manifest keeps the public-release gate open until the final archive
  is hosted and the exact attribution/source link is published.
- A guided clean-Windows acceptance harness with separately hash-bound fresh and previous-installer
  upgrade scenarios, human-visible lifecycle/media prompts, Windows Settings uninstall/reinstall,
  and portable launch/immutability evidence.
- Isolated checksum-pinned browser-CI media provisioning, so upstream removal of the reviewed
  shipping archive cannot silently swap desktop media dependencies. Fresh packaging acquisition
  of that reviewed archive remains a separate release gate.
- An explicit Apache-2.0 application license in Python package metadata, Windows package payloads,
  package acceptance, and the in-app About/legal document list.
- Direct audiogram center/pivot positioning in the preview, keyboard nudges, formula-overwrite
  protection, and a living post-merge expansion checklist recovered from the Narrator handover.

### Changed

- SPLICR is now primarily a local Studio application. The hosted portfolio deployment remains a
  private demonstration surface until the separate public information/download page is built.
- Provider/model controls are schema-driven and frozen into jobs rather than inferred from mutable
  browser state.
- Generated audio is normalized to one canonical format: mono signed 16-bit PCM at 24 kHz, with a
  single WAV header written only after all required checkpoints are complete.

### Fixed

- Live progress now follows persisted chunk completion instead of updating only after cancellation.
- Numeric citation removal treats `[123]` and escaped `\[123\]` forms equivalently.
- Audio8 now follows the current upstream `reference_audio`/`reference_text`, generation-result,
  and decoder-length contracts; three implausible outputs pause instead of silently accepting bad
  audio.
- faster-whisper works with PyAV 19 through a worker-scoped compatibility shim.
- Provider diagnostics recursively redact credentials, audio payloads, sensitive headers, and local
  private paths before persistence or display.
- Windows packaging discovers Inno Setup from `PATH`, user-scope, and machine-scope installations;
  a single discovered compiler path no longer collapses to its first character in PowerShell.
- MP4 audiograms prefer `libx264` when an external build provides it and otherwise use the bundled
  `libopenh264` encoder with deterministic bitrate-based quality mapping.

### Install and data locations

- The per-user installer places application files under
  `%LOCALAPPDATA%\Programs\SPLICR Studio` and adds one Start-menu entry plus one Windows uninstall
  registration. It does not require a system-wide Python, Node.js, FFmpeg, or administrator rights.
- The portable ZIP can be extracted to any normal writable directory. Application files are treated
  as immutable; portable and installed builds use the same per-user data directory.
- Jobs, the SQLite database, profiles, provider-resource metadata, checkpoints, generated media,
  settings, and logs live under `%LOCALAPPDATA%\SPLICR Studio\data`. Uninstall intentionally leaves
  this directory in place so a later reinstall can resume and reopen work.
- Removing the application permanently therefore requires two deliberate steps: uninstall the app,
  then back up and manually delete `%LOCALAPPDATA%\SPLICR Studio\data` if its jobs and media are no
  longer wanted.

### Migration and configuration

- Existing SQLite data is migrated in place on startup. Back up the complete data directory before
  installing a new candidate; database downgrade is not supported.
- Desktop data defaults to `%LOCALAPPDATA%\SPLICR Studio\data` and intentionally survives upgrades
  and uninstall. Local development continues to use the configured `SPLICR_DATA_DIR` or repository
  data directory.
- Optional engines remain external and are never copied into the application installation. Point
  Components (or `SPLICR_KOKORO_PYTHON`, `SPLICR_QWEN3_PYTHON`, `SPLICR_AUDIO8_PYTHON`,
  `SPLICR_EDGE_PYTHON`, and `SPLICR_WHISPER_PYTHON`) at their isolated interpreters.
- API credentials remain in the configured OS keyring/encrypted vault; they are not included in
  profiles, logs, diagnostics, browser storage, or portable archives.

### Known limitations before a public release

- Gemini, Deepgram, and Inworld credential-backed contracts have passed against their current live
  endpoints, but remote providers remain external services: API changes, availability, quotas,
  pricing, content policies, and commercial terms remain the user's responsibility.
- Qwen3-TTS and Audio8 download multi-gigabyte models and perform best on a CUDA-capable GPU.
  Audio8 uses reviewed Hugging Face custom model code through `trust_remote_code=True`.
- Sentence revision requires reliable provider or transcription timing; otherwise Studio safely
  falls back to regenerating the whole chunk.
- The real Edge sentence-revision artifact is retained and hash-verified, but final human audible
  seam approval remains open.
- Human-visible fresh/upgrade/uninstall/portable evidence on reverted clean Windows snapshots, a
  manual scan by the active malware product, and current-commit GitHub Actions evidence remain
  release gates. The development candidate is intentionally unsigned.
- Although the upstream FFmpeg asset is named `lgpl-shared`, its statically incorporated FFTW path
  makes the distributed media binaries GPL-covered. The exact corresponding-source candidate has
  rebuilt successfully offline, but public release still requires stable hosting plus the precise
  attribution/source link.
- The current third-party OpenH264 build is not covered by Cisco's binary-module royalty arrangement,
  and AAC has a separate patent pool. Public H.264/AAC binary distribution therefore requires an
  explicit licensing decision or removal/replacement of those codecs.

### Rollback

1. Stop SPLICR Studio and copy the entire data directory to a separate backup location.
2. Reinstall or extract the prior application build without deleting the preserved data directory.
3. If the newer build migrated the database, restore the matching pre-upgrade data snapshot before
   opening the older application. Do not point an older binary at a newer migrated database.
4. Keep generated media and external engine environments in place; they are not owned or removed
   by the application installer.
