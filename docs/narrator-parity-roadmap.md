# SPLICR Studio — Narrator capability-parity roadmap

**Status:** Active living specification and checklist  
**Started:** 2026-09-29  
**Baseline:** `14f613a` (`codex/narrator-integration`)  
**Canonical parity inventory:** [`ui-control-parity.json`](ui-control-parity.json)

## Goal

Complete SPLICR Studio's remaining Narrator capability parity while preserving a provider-neutral
pipeline, progressive-disclosure UI, reproducible profiles and render plans, durable resume
behavior, and verified operation across local engines and remote providers.

This document is the source of truth for that goal. The Codex goal slot points here. Update the
checklist in the same commit as the work it describes; do not rely on chat history as the project
ledger.

## How to use this living checklist

- `[x]` means implemented **and verified** by the acceptance evidence named in that item.
- `[ ]` means incomplete. An implementation without its required tests stays incomplete.
- Keep only one numbered milestone as the primary implementation focus at a time.
- If work discovers another preserved Narrator capability, add it to this document and to
  [`ui-control-parity.json`](ui-control-parity.json) before implementing it.
- When a gap is intentionally replaced rather than ported, record the replacement and rationale in
  the machine-readable parity inventory.
- Every milestone ends with a full regression run and an update to the verification record near the
  end of this document.
- Never mark a live provider, local model, crash-recovery, or installer item complete from mocks
  alone. Record the exact environment that supplied the real acceptance evidence.

## Scope and product rules

### What parity means

Parity means that the useful capability remains available, not that Studio reproduces Narrator's
Tk window or unfinished React layout pixel for pixel. The default narration path must remain calm
and understandable even after expert features return.

Controls belong in three layers:

1. **Narrate essentials:** document, engine, voice, tone, style, pace, chunk preview, and Start.
2. **Advanced engine controls:** typed, provider-aware controls shown only when supported, grouped
   by generation, voice, pacing, chunking, and output behavior.
3. **Focused workspaces:** Timeline, Voice Studio, Pronunciation, Convert, Audiogram, Publish,
   Dialogue, Components, and Library own tasks that are not part of starting a normal narration.

### Architectural invariants

- [x] FastAPI transport remains thin; domain and service code own behavior.
- [x] Remote and local engines conform to the `TtsProvider`/engine-session boundaries.
- [x] All synthesis output normalizes to mono signed 16-bit PCM at 24 kHz before assembly.
- [x] Completed chunks are durable checkpoints and resume does not resynthesize them.
- [x] A partial or failed artifact is never presented as a completed result.
- [x] Every newly exposed value is validated server-side and frozen into the immutable RenderPlan,
  job, and chunk options used for resume.
- [ ] Provider/engine secrets and private paths never enter logs, error reports, exported profiles,
  browser storage, or GitHub Actions artifacts.
- [x] New long-running utilities use durable jobs with progress, cancellation, restart recovery,
  structured errors, and atomic final outputs.
- [x] All advanced controls remain keyboard accessible, have labels/help text, and do not rely on
  color alone.

### Intentional replacements already accepted

- Output-root and subfolder widgets are replaced by Studio's managed
  `Project -> RenderPlan -> Take -> Artifact` hierarchy and explicit downloads.
- User-entered `chars_per_token` is replaced by provider-specific measurement/estimation.
- Internal chunk retention is automatic. A future export action may expose copies without making
  checkpoint durability optional.
- The hosted public page and Authcore integration remain deferred. The distributed Studio is a
  local-first application; the eventual website is an information/demo/download page.

## Source corpus

- [`legacy/narrator/HANDOVER.md`](../legacy/narrator/HANDOVER.md): architecture, historical
  decisions, bugs, verified/unverified behavior, roadmap, native Tk UI, unfinished web UI, and
  future ideas.
- [`legacy/narrator/narrator/render_config.py`](../legacy/narrator/narrator/render_config.py): the
  preserved 26-field render schema checked by tests.
- [`NARRATOR_IMPORT.md`](NARRATOR_IMPORT.md): preservation/import boundaries.
- [`STUDIO_ARCHITECTURE.md`](STUDIO_ARCHITECTURE.md): merged domain and engine-session design.
- [`ui-control-parity.json`](ui-control-parity.json): machine-readable destination/status ledger.
- [`ui-control-parity.md`](ui-control-parity.md): current parity summary and acceptance commands.

## Completed merger baseline

- [x] Preserve Narrator under `legacy/narrator` without tracking environments, weights, generated
  output, caches, or secrets.
- [x] Merge durable projects, immutable plans, takes, artifacts, and read-only legacy importers.
- [x] Integrate Gemini, Deepgram, Inworld, generic configurable REST resources, Kokoro, Qwen3-TTS,
  and Audio8 behind provider-neutral boundaries.
- [x] Integrate resumable single-voice narration and multi-speaker Dialogue rendering.
- [x] Integrate Voice Studio, pronunciation overrides, profiles, Library, Timeline, Convert,
  Audiogram, Components, Publish, and global error reporting.
- [x] Package the React Studio in FastAPI and preserve the classic UI at `/`.
- [x] Produce a Windows portable build/installer workflow with persistent per-user data.
- [x] Add a real-browser acceptance server and Chromium journeys across every Studio workspace.
- [x] Add machine-checked parity coverage for all preserved render fields.
- [x] Add an opt-in live-provider canonical-PCM contract check.

## Capability ledger

The detailed field-level mapping remains in `ui-control-parity.json`. This table is the prioritized
human-readable work queue, including broader capabilities that were not render-schema fields.

| Capability | Current state | Destination | Milestone |
| --- | --- | --- | --- |
| Typed engine/model parameters | Gap | Narrate advanced controls | 1 |
| Qwen voice-design take and deterministic seed | Covered; live-model acceptance pending | Narrate / Voice Studio | 2 |
| Optional precise speed | Covered for Kokoro | Narrate advanced controls | 2 |
| Parts/token/character chunk planning | Covered | Narrate advanced controls | 2 |
| Edge TTS engine | Covered; live-service acceptance pending | Narrate / Components | 3 |
| Export filename | Gap | Narrate / Library | 4 |
| Checkpoint/chunk export | Gap | Timeline / Library | 4 |
| SRT/VTT export and burned captions | Gap | Publish / Audiogram | 4 |
| Intro/outro assets and crossfade | Gap | Timeline / Publish | 5 |
| Sentence-level regeneration and splice | Partial: chunk-level only | Timeline | 5 |
| Multi-document durable queue | Gap | Narrate / Library | 6 |
| Audio transcription and guessed chapters | Gap | Convert / Publish | 7 |
| Still-image audiogram background | Gap | Audiogram | 8 |
| Polar/transparent/formula audiograms | Gap | Audiogram | 8 |
| Real provider/model/installer/crash acceptance | Partial | Test/release infrastructure | 9 |

## Milestone 1 — typed advanced-engine control foundation

This is the enabling layer. Do not add one-off Qwen-only form state before this foundation exists.

### Contract and persistence

- [x] Define a provider-neutral `ControlDefinition` contract with stable key, label, description,
  group, value type, default, required flag, and optional enum/range/step/unit metadata.
- [x] Support at least boolean, integer, decimal, text, enum, and secret-free structured values.
- [x] Support conditional visibility/enabling without allowing arbitrary code in a schema.
- [x] Extend provider capability responses with their control definitions and current defaults.
- [x] Adapt configurable API-resource `variable_definitions` to the same public control contract
  rather than maintaining a second renderer.
- [x] Validate submitted values against the frozen resource revision/provider schema.
- [x] Reject unknown keys by default; permit explicitly declared pass-through objects only for the
  existing expert custom-resource editor.
- [x] Freeze validated values into Studio profiles, RenderPlans, jobs, per-segment overrides, and
  resumable chunk options.
- [x] Preserve old profiles/jobs with a versioned migration or backward-compatible empty control
  set.
- [x] Redact any value marked sensitive at API, diagnostics, profile-export, and error boundaries.

### Studio UI

- [x] Add an **Advanced engine controls** disclosure beneath the essential narration controls.
- [x] Show the number of non-default advanced values while collapsed.
- [x] Group controls by Generation, Voice, Pacing, Chunk planning, and Output where applicable.
- [x] Render control types from metadata with labels, bounds, units, help text, defaults, and Reset.
- [x] Hide unsupported groups rather than showing disabled fictional controls.
- [x] Preserve unsaved form state when navigating to another workspace and back.
- [x] Make validation errors local to the field while retaining full structured errors in the Error
  Center.
- [x] Include advanced values when saving/loading profiles and make the loaded differences visible.

### Acceptance gate

- [x] Unit-test schema parsing, validation, defaults, bounds, unknown keys, and redaction.
- [x] Integration-test persistence through API -> RenderPlan -> job -> chunk -> resume.
- [x] Browser-test switching engines, conditional control visibility, reset, profile round-trip, and
  starting a render with non-default values.
- [x] Update the parity manifest and mark this milestone complete only after full regression passes.

## Milestone 2 — narration controls: Qwen, speed, and chunk planning

### Qwen take and seed

The selected designed Voice Profile is the voice identity: its read-only take is surfaced in
Narrate, but cannot be edited into a different identity. The seed belongs to a render and may be
randomized without changing that profile. Creating another voice take therefore creates another
Voice Profile in Voice Studio; it never mutates a take number on an existing profile.

- [x] Expose Qwen voice-design take identity through the typed control schema.
- [x] Expose a deterministic seed with Generate another/Randomize behavior that always reveals the
  resulting stored seed.
- [x] Define how take identity relates to existing Qwen Voice Profiles; avoid two competing sources
  of identity.
- [x] Freeze take, seed, model, voice-design description, reference, and sampling values before the
  first chunk.
- [x] Prove resumed chunks use the same designed/cloned voice and seed policy.
- [x] Add tests for same settings/same take, new take, retry, resume, and profile round-trip.
- [x] Add a durable Qwen VoiceDesign job that turns description + take into a managed reference
  recording and exact reference transcript without loading the model in FastAPI.
- [x] Add **Designed voice** and **Generate another take** flows to Voice Studio; reuse an existing
  description/take profile rather than duplicating it.
- [x] Add faithful fake-worker coverage plus an opt-in real-local-model acceptance test that
  validates the exact transcript, deterministic take seed, and canonical WAV contract.
- [ ] Run the opt-in VoiceDesign acceptance test against a configured Qwen environment and record
  its Python/model/date/result; mocks alone cannot close this local-model evidence item.

### Precise speed

Precedence is explicit: a segment's validated `speed` value overrides the job/profile value; the
job/profile value overrides the five-step pace preset; omitting `speed` falls back to that preset.
Providers without a declared numeric rate continue to expose only the provider-neutral pace.

- [x] Keep the five-step provider-neutral pace slider as the default interface.
- [x] Add an optional numeric speed/rate override only when the selected engine supports it.
- [x] Display the engine's true units and supported range; do not pretend all providers share one
  multiplier.
- [x] Define precedence between pace preset, numeric override, profile value, and segment override.
- [x] Test clamping/rejection, provider request mapping, persistence, and resume reproducibility.

### Advanced chunk planning

- [x] Preserve Semantic, Heading 1–6, newline, and double-newline preferred boundaries.
- [x] Add advanced target modes: automatic/provider-safe, desired part count, token target, and
  character target.
- [x] Treat provider hard limits as absolute even when a user target is larger.
- [x] Retain paragraph/sentence/word fallback ordering and correct UTF-8 byte accounting.
- [x] Keep citation cleanup and blank-fragment elimination ahead of chunk validation.
- [x] Preview boundary reason, source span, bytes/words/tokens, and provider-limit headroom for every
  proposed chunk.
- [x] Warn when a requested part count cannot be achieved without violating a hard limit.
- [x] Persist the selected strategy and exact planned chunks so resume never replans differently.
- [x] Test headings, empty sections, long unbroken text, multibyte text, citations, minimum/maximum
  targets, and plan stability after restart.

## Milestone 3 — Edge TTS and engine onboarding breadth

Edge TTS was Narrator's zero-setup online fallback. It is not currently a merged SPLICR provider.

- [x] Implement Edge TTS behind `TtsProvider` or the existing supervised subprocess boundary.
- [x] Invoke the module through the configured Python environment rather than relying on a movable
  `edge-tts.exe` shim.
- [x] Discover and cache voices/languages without blocking Studio startup.
- [x] Normalize output to canonical PCM and retain word/sentence timing when available.
- [x] Classify offline, throttling, voice-not-found, and subprocess failures into structured errors.
- [x] Add Components detection and setup guidance without silently installing packages or weights.
- [x] Decide and document whether Studio ever manages engine environments; until then, external
  environment reuse remains the supported safe behavior.
- [x] Add fake-surface tests against the real CLI/API shape and an opt-in live Edge contract test.
- [x] Add an onboarding template/checklist for future local engines so Audio8-style additions do not
  require bespoke architecture.

## Milestone 4 — naming, checkpoints, subtitles, and captions

### Artifact naming and chunk export

- [x] Add a user-facing export filename/stem while retaining immutable internal artifact IDs.
- [x] Sanitize platform-reserved names and characters and apply a deterministic collision policy.
- [x] Add **Export completed chunks/checkpoints** as WAV files plus a manifest; export copies only.
- [x] Permit checkpoint export from paused/failed/cancelled jobs without presenting it as a finished
  master.
- [x] Test ordering, missing checkpoints, Unicode names, collisions, and interrupted export cleanup.

### Subtitle timeline

- [ ] Define a shared subtitle cue model with source text, start/end, speaker, timing confidence,
  and source (`engine`, `checkpoint`, or `transcription`).
- [ ] Prefer exact engine/segment timings; clearly label estimated chunk timings.
- [ ] Export valid UTF-8 SRT and WebVTT from a completed or partially completed take.
- [ ] Preserve dialogue speaker identity where the target format permits it.
- [ ] Attach subtitle artifacts to the take with hashes and immutable provenance.
- [ ] Add optional caption burn-in to Audiogram/Publish without changing the source take.
- [ ] Test escaping, multiline cues, Unicode, monotonically increasing times, partial takes, and
  container/codec combinations.

## Milestone 5 — non-destructive finishing and sentence editing

### Intro, outro, and crossfade

- [ ] Manage intro/outro uploads as durable assets rather than arbitrary transient paths.
- [ ] Add non-destructive assembly settings to a take/publish plan; never rewrite checkpoints.
- [ ] Implement concat/acrossfade with overlong crossfades clamped safely.
- [ ] Calculate and persist the actual intro offset.
- [ ] Shift subtitle cues, chapter marks, timeline spans, and waveform navigation by that offset.
- [ ] Leave the narration artifact untouched and report a structured error if an asset is missing or
  unreadable.
- [ ] Offer optional loudness normalization as an enhancement, not a parity requirement.
- [ ] Verify real FFmpeg output for intro only, outro only, both, zero/overlong crossfade, offsets,
  missing assets, and atomic failure.

### Sentence-level regeneration

- [ ] Extend Timeline's chunk model with sentence spans and timing provenance.
- [ ] Use exact engine timing where available; allow transcription-derived timing as an explicit
  lower-confidence fallback.
- [ ] Regenerate a sentence with the original frozen engine/profile/advanced-control snapshot.
- [ ] Trim, level-match within a safe bound, and crossfade the replacement non-destructively.
- [ ] Preserve original take/checkpoints and create a new derived Take with provenance.
- [ ] Shift subsequent spans and regenerate subtitles/chapters after a duration change.
- [ ] Fall back to chunk-level regeneration when sentence timing is unavailable or unreliable.
- [ ] Verify bytes/audio outside the replaced span remain unchanged where the format permits exact
  comparison; also perform an audible real-engine seam check.

## Milestone 6 — durable multi-document queue

- [ ] Add multi-select queue creation from imported documents and Library projects.
- [ ] Freeze a separate profile, provider/resource revision, source revision, and render plan per
  queue item.
- [ ] Persist queue order and item status across process restart.
- [ ] Default to sequential execution to protect local VRAM and remote rate limits.
- [ ] Continue after one item fails and summarize completed/failed/skipped/cancelled counts.
- [ ] Distinguish pause/cancel current item from pause/cancel remaining queue.
- [ ] Allow reordering/removal only for items that have not started.
- [ ] Surface missing source, missing engine, invalid saved profile, and deleted resource revisions as
  explicit skip/failure reasons.
- [ ] Ensure every completed take remains separately editable, publishable, and downloadable.
- [ ] Browser-test creation, progress, one-item failure, restart, resume, and final summary.

## Milestone 7 — audio transcription utility

- [ ] Add faster-whisper as an optional external/local component, loaded only on demand.
- [ ] Implement a provider-neutral transcription boundary so other ASR engines can be added later.
- [ ] Import managed audio and produce a durable transcript with segment and optional word timings.
- [ ] Regroup short ASR utterances into readable paragraphs.
- [ ] Export SRT/VTT and optional per-line timestamps.
- [ ] Generate clearly labelled **guessed** chapter marks from pauses; do not equate them with source
  document headings.
- [ ] Expose model size, language/auto-detect, device, compute type, VAD, and word-timing controls
  through typed metadata.
- [ ] Run transcription as a durable job with download/model errors, progress, cancel, restart, and
  atomic artifacts.
- [ ] Unit-test against a faithful fake faster-whisper surface and complete a real-model acceptance
  run on a supported machine.

## Milestone 8 — advanced audiogram parity

### Still image and transparent export

- [ ] Add managed still-image background upload, crop/fit/position, and preview compositing.
- [ ] Preserve the existing solid/chroma background path.
- [ ] Add transparent overlay outputs for VP9/WebM, ProRes 4444, and PNG sequences where supported.
- [ ] Share one layout resolver between preview, estimate, and final render.

### Geometry, animation, and expressions

- [ ] Add linear/polar geometry, bars/line, mirror, smoothing, line width, placement, inner/outer
  radius, pivot, rotation, color, and opacity behind Advanced layout controls.
- [ ] Scale polar geometry against the shorter frame dimension and prevent inverted radii.
- [ ] Add a safe expression language using a parsed AST whitelist—never `eval()` user text.
- [ ] Publish searchable variables/functions from the same registry used by validation.
- [ ] Support time-, progress-, frame-, and audio-reactive variables for animatable layout values.
- [ ] Disable unsafe cropping when rotation or animation can move content outside predicted bounds.
- [ ] Keep the quick FFmpeg visualizers as the normal path; advanced rendering must not slow users
  who do not enable it.
- [ ] Test expression escape attempts, preview/final agreement, alpha codecs, even dimensions,
  invalid formulas, cancellation, restart, and atomic output.

## Milestone 9 — real-world acceptance and release hardening

### Live providers and local engines

- [ ] Run the opt-in live contract against Gemini and record model/voice/date/result.
- [ ] Run it against Deepgram and record model/voice/date/result.
- [ ] Run it against Inworld and record model/voice/date/result.
- [ ] Run the eventual Edge provider against the live service.
- [ ] Run real Kokoro narration through import -> preview -> render -> resume -> playback.
- [ ] Run real Qwen voice design/clone with non-default advanced parameters and forced resume.
- [ ] Run real Audio8 clone narration with forced resume.
- [ ] Confirm local engine processes/models are reused only within their intended job/session scope
  and released after completion/cancel/failure.

### Crash, scale, and packaging

- [ ] Run a long-document forced-termination soak at several chunk boundaries and verify exact resume
  ordering with no duplicate synthesis.
- [ ] Force termination during final assembly and verify no partial artifact is marked complete.
- [ ] Exercise pause/export/cancel after provider and local-engine failures.
- [ ] Test very large imports and outputs near configured limits without loading full media into
  browser or server memory.
- [ ] Test clean Windows installer install, upgrade with existing data/jobs/profiles, uninstall with
  intentional user-data policy, and portable ZIP execution in a clean VM.
- [ ] Verify Chromium acceptance in GitHub Actions and retain failure traces/screenshots/video.
- [ ] Update user documentation, migration notes, third-party notices, and release checklist.

## Deferred ideas from the Narrator handover

These are preserved so they are not forgotten, but they are not current parity blockers:

- [ ] Per-word audio surgery. Word-timing inspection and pronunciation correction have higher value
  and lower artifact risk.
- [ ] Delete/reorder individual sentences and assign a different voice per sentence in Timeline.
- [ ] Drag audiogram center/pivot directly in preview.
- [ ] Per-band gradients and frequency-range-specific audiogram response.
- [ ] Intro/outro automatic loudness matching.
- [ ] Formula-driven TTS parameters. Generation parameters operate per request, not per audio frame,
  so this needs a separate product design rather than copying audiogram expressions.
- [ ] Public information/demo/download site after local Studio parity and release hardening.

## Verification matrix

Every implementation milestone must select the applicable rows and attach evidence in its commit or
pull request.

| Layer | Required evidence |
| --- | --- |
| Domain | Unit tests for validation, boundary cases, serialization, and backward compatibility |
| Persistence | Restart/requeue/resume tests using a real temporary SQLite database and files |
| Provider | Faithful fake contract tests plus opt-in real provider/engine acceptance |
| Media | Real FFmpeg/FFprobe smoke tests and metadata/duration/order assertions |
| API | FastAPI tests for success, validation errors, structured failures, redaction, and auth rules |
| UI | Frontend unit tests plus Playwright success, empty, error, resume, and keyboard paths |
| Release | Windows frozen/package smoke and clean-machine install/upgrade evidence |

Routine local gate:

```powershell
uv run ruff check .
uv run pytest -q
npm --prefix studio-web test
npm --prefix studio-web run build
npm --prefix studio-web run test:e2e
```

Quota-consuming provider check:

```powershell
$env:SPLICR_LIVE_PROVIDER = "deepgram" # or gemini / inworld
uv run pytest -m live_provider tests/test_live_provider_acceptance.py
```

## Verification record

- [x] 2026-09-29 — baseline Ruff suite passed.
- [x] 2026-09-29 — full Python suite passed; the deliberately disabled live-provider test skipped.
- [x] 2026-09-29 — frontend unit tests and Vite production build passed.
- [x] 2026-09-29 — both Chromium acceptance journeys passed against the real FastAPI transport and
  deterministic TTS provider.
- [x] 2026-09-29 — Milestone 1 full gate passed: Ruff, the complete Python suite (one opt-in live
  provider test skipped), seven frontend unit tests, the production Vite build, and two Chromium
  journeys covering keyboard disclosure, provider switching, conditional fields, local bounds,
  profile round-trip, checkpoint resume, playback, and Studio reopening.
- [x] 2026-09-29 — Milestone 2 implementation gate passed: Ruff, the complete Python suite (the
  opt-in live-provider and live-Qwen tests skipped), eight frontend unit tests, the production Vite
  build, and three Chromium journeys. VoiceDesign coverage includes durable idempotency, atomic
  restart finalization, cancellation, cancellation recovery, retry, managed-profile creation, and
  generating another take through the real FastAPI transport.
- [x] 2026-09-29 — Milestone 3 implementation gate passed: Ruff, the complete Python suite (three
  opt-in live checks skipped), eight frontend unit tests, the production Vite build, and three
  Chromium journeys. Edge coverage uses faithful `Communicate.stream()`/voice/error fakes,
  validates FFmpeg normalization and timing transport, persists chunk metadata through schema v5,
  and includes an opt-in live online-service contract test.
- [x] 2026-09-29 — Milestone 4 artifact-naming/checkpoint-export gate passed: Ruff, the complete
  Python suite (three opt-in live checks skipped), eight frontend unit tests, the production Vite
  build, and three Chromium journeys. Coverage proves portable Unicode names, Windows-reserved
  names, deterministic case-insensitive collisions, ordered WAV copies, missing checkpoints,
  paused/failed/cancelled partial manifests, source-checkpoint immutability, and interrupted-export
  cleanup.
- [x] Earlier merger baseline — real FFmpeg conversion/audiogram smoke and frozen Windows package
  smoke passed; see the repository history and linked architecture/handover documents.

## Current work pointer

- **Active milestone:** Milestones 2/3 live acceptance closeout plus Milestone 4 — subtitle timelines
  and caption delivery.
- **Next implementation slice:** define the shared subtitle cue model and generate exact engine cues
  when timing metadata exists, with clearly labeled checkpoint estimates as the fallback. Real Qwen
  and Edge acceptance remains ready when configured environments are available.
- **Known unrelated worktree item:** `LICENSE.txt` is untracked and not part of this roadmap unless
  deliberately adopted later.

## Change log

- **2026-09-29:** Created the living roadmap from the Narrator handover, render-schema parity audit,
  merged Studio architecture, and browser acceptance baseline. Added previously undercounted Edge
  TTS and audio-transcription gaps and preserved non-blocking future ideas.
- **2026-09-29:** Completed Milestone 1 with one provider-neutral typed-control contract shared by
  built-in engines and configurable resources, strict server validation/redaction, immutable
  persistence, the generated progressive-disclosure Studio panel, profile round-trip, and
  unit/integration/browser acceptance coverage. Declared Kokoro's existing precise-speed override
  through the new schema as the first real engine control.
- **2026-09-29:** Completed the Qwen narration identity slice: designed-voice take is read-only and
  owned by the selected Voice Profile; synthesis seed is visible, randomizable, profile-safe, and
  frozen with model/reference/design/sampling state through checkpoint resume. The audit made the
  missing durable VoiceDesign creation flow explicit before marking legacy `take` parity covered.
- **2026-09-29:** Added the durable isolated Qwen VoiceDesign queue, atomic managed reference and
  exact-transcript materialization, idempotent description/take identity, restart recovery,
  cancellation and retry, Voice Studio Designed voice / Generate another take flows, a faithful
  worker fake, and an opt-in real-model contract test. Full mocked regressions pass; the real Qwen
  execution remains an explicit acceptance item until a configured environment supplies evidence.
- **2026-09-29:** Added Edge TTS as a supervised provider using an external Python environment,
  explicit cached voice discovery, schema-driven rate/pitch/volume/timing controls, canonical
  FFmpeg normalization, structured transport failures, and durable word/sentence timing metadata.
  Added the reusable local-engine onboarding checklist and opt-in live Edge contract test; the real
  online-service run remains an explicit acceptance item.
- **2026-09-29:** Completed Milestone 4 artifact naming and checkpoint export. Jobs now retain a
  collision-safe portable export stem separately from immutable IDs; Narrate and Dialogue expose
  friendly filenames and checkpoint ZIP downloads. Atomic exports contain ordered canonical WAV
  copies and a UTF-8 provenance manifest, remain explicitly non-master/partial when appropriate,
  and tolerate missing checkpoints without altering resumable source PCM.
