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
- Markdown, Word, OpenDocument, text, and JSON import; semantic/heading/newline planning; numeric
  citation removal; chunk preview; structured progress; partial export; and detailed error recovery.
- Voice design/cloning, sentence-level non-destructive revision, subtitles/chapters, audio
  conversion, intro/outro finishing, and formula/polar/transparent audiogram rendering.
- Windows portable/installer build automation with bundled FFmpeg discovery, checksums, build
  metadata, supervised browser acceptance, and packaged-executable smoke tests.

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

- Gemini and Deepgram still need deliberate credential-backed live contract evidence for this
  branch. Provider quotas and commercial terms remain the user's responsibility.
- Qwen3-TTS and Audio8 download multi-gigabyte models and perform best on a CUDA-capable GPU.
  Audio8 uses reviewed Hugging Face custom model code through `trust_remote_code=True`.
- Sentence revision requires reliable provider or transcription timing; otherwise Studio safely
  falls back to regenerating the whole chunk.
- Clean-Windows installer upgrade/uninstall/Unicode-path evidence, signed binaries, malware scan,
  and current-commit GitHub Actions evidence remain release gates.
- The FFmpeg build currently found on the development workstation is GPL-enabled. It is suitable
  for internal acceptance packages only until the publisher either supplies a compatible LGPL
  build or completes all obligations for distributing that exact GPL build.

### Rollback

1. Stop SPLICR Studio and copy the entire data directory to a separate backup location.
2. Reinstall or extract the prior application build without deleting the preserved data directory.
3. If the newer build migrated the database, restore the matching pre-upgrade data snapshot before
   opening the older application. Do not point an older binary at a newer migrated database.
4. Keep generated media and external engine environments in place; they are not owned or removed
   by the application installer.
