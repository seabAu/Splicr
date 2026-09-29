# Local engine onboarding checklist

SPLICR reuses externally managed Python environments. It never silently creates, upgrades, copies,
or deletes an engine environment, its model cache, or weights. A new engine should fit the shared
contract below rather than adding a bespoke execution path.

## Provider facade

- [ ] Add a `TtsProvider` facade with stable provider/model IDs, hard input limits, recommended
  chunk size, voices, pace support, and typed advanced controls.
- [ ] Keep `synthesize()` unavailable outside a job-scoped engine session.
- [ ] Return a `LocalSubprocessEngineAdapter` whose command invokes the bundled
  `engine_worker.py` through the configured environment's Python executable.
- [ ] Register the provider in `bootstrap.create_service` only when its interpreter is configured.

## Worker and audio contract

- [ ] Import engine-only packages after worker argument parsing; FastAPI must not import them.
- [ ] Reuse expensive runtime/model state only for the lifetime of one worker/job.
- [ ] Atomically write only to the absolute job-private output path supplied by the parent.
- [ ] Return mono signed PCM16 at 24,000 Hz. Normalize in the worker and let the parent validate
  path, size, format, and complete frames before checkpointing.
- [ ] Return JSON-safe timing or provenance metadata through `AudioChunk.metadata` when available;
  the job store persists that metadata beside the exact chunk checkpoint.
- [ ] Ensure cancellation, timeout, failure, and normal close all terminate the worker.

## Components and discovery

- [ ] Add one `Settings` path, `SPLICR_*_PYTHON` environment variable, Components definition, and
  `.env.example` entry.
- [ ] Validate only that the interpreter can start when saving it. Do not install packages or fetch
  model weights.
- [ ] Make optional voice/model discovery explicit, bounded, and atomic. Cache normalized results
  under the Studio data directory; never block application startup on network/model discovery.
- [ ] Explain whether a restart is required and keep environment-variable configuration read-only.

## Errors and verification

- [ ] Classify invalid input/voice as non-retryable; offline, throttling, and transient transport
  failures as retryable; preserve redacted worker diagnostics.
- [ ] Add faithful unit fakes for the engine's real Python API shape, output normalization, metadata,
  error classes, provider registration, component configuration, and restart/resume behavior.
- [ ] Add an opt-in real-engine contract test that consumes no credentials by default.
- [ ] Record the exact interpreter/package/model/date/result in the living roadmap before marking
  real-engine acceptance complete.
- [ ] Run Ruff, the complete Python suite, frontend unit tests, the production Vite build, and
  Chromium acceptance before closing the implementation slice.
