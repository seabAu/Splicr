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

No preserved Narrator setting may disappear merely because the old native window exposed too many
widgets at once. Every meaningful value must have one of four explicit dispositions: an essential
control, a typed provider-generated advanced control, a focused-workspace control, or a documented
replacement/deferment in the parity inventory. Profiles and RenderPlans—not React component
state—remain the canonical representation of those values.

### Architectural invariants

- [x] FastAPI transport remains thin; domain and service code own behavior.
- [x] Remote and local engines conform to the `TtsProvider`/engine-session boundaries.
- [x] All synthesis output normalizes to mono signed 16-bit PCM at 24 kHz before assembly.
- [x] Completed chunks are durable checkpoints and resume does not resynthesize them.
- [x] A partial or failed artifact is never presented as a completed result.
- [x] Every newly exposed value is validated server-side and frozen into the immutable RenderPlan,
  job, and chunk options used for resume.
- [x] Provider/engine secrets and private paths never enter logs, error reports, exported profiles,
  browser storage, or GitHub Actions artifacts. Resource credentials remain write-only in the
  vault, sensitive control values are rejected from profiles, Voice Profile API payloads omit
  managed reference paths, Studio uses no browser persistence API, diagnostics recursively redact
  credentials and path-bearing fields/quoted home paths, and CI injects no live provider secrets
  into retained browser artifacts. Focused privacy regression coverage passed 2026-09-29.
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

### Handover future-work disposition

The handover does contain both future-development ideas and unfinished web-UI notes. They are
normalized here so the native and unfinished web interfaces do not become competing backlogs:

| Handover thread | Studio disposition |
| --- | --- |
| Local web frontend over extracted Python services | Completed merger baseline; React/Vite is packaged by FastAPI. |
| Schema-driven render settings and the dense native control surface | Typed advanced controls plus focused workspaces; field coverage is machine-checked. |
| Optional components and engines visible before installation | Components workspace and local-engine onboarding; real install acceptance remains Milestone 9. |
| Queue/batch render | Completed in Milestone 6 with frozen per-item jobs and Library controls. |
| Sentence/timeline repair | Milestone 5; automated coverage complete, audible live seam check remains. |
| Audio transcription and guessed chapters | Milestone 7 complete, including real faster-whisper acceptance. |
| Still backgrounds, polar layouts, transparency, and safe expressions | Milestone 8. |
| Installer/proper-app hardening | Portable/installer baseline exists; clean-VM install/upgrade evidence remains Milestone 9. |
| Remaining component CSS-to-Tailwind cleanup | Non-blocking UI maintenance; browser behavior and accessibility, not framework purity, are the gate. |
| Word surgery, richer sentence operations, draggable pivots, gradients, TTS formulas, public site | Preserved under **Deferred ideas** below. |

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
| Export filename | Covered | Narrate / Library | 4 |
| Checkpoint/chunk export | Covered | Timeline / Library | 4 |
| SRT/VTT export and burned captions | Covered | Publish / Audiogram | 4 |
| Intro/outro assets and crossfade | Covered | Timeline / Publish | 5 |
| Sentence-level regeneration and splice | Covered; audible live-engine seam check pending | Timeline | 5 |
| Multi-document durable queue | Covered | Narrate / Library | 6 |
| Audio transcription and guessed chapters | Covered; live-model acceptance pending | Convert / Publish | 7 |
| Still-image audiogram background | Covered | Audiogram | 8 |
| Polar/transparent/formula audiograms | Covered; release-level visual acceptance pending | Audiogram | 8 |
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
- [x] Run the opt-in VoiceDesign acceptance test against a configured Qwen environment and record
  its Python/model/date/result. Verified 2026-09-29 with Python 3.12.14, `qwen-tts 0.1.1`, the
  1.7B VoiceDesign and Base models, deterministic take 2, synthesis seed `424242`, and CUDA
  PyTorch 2.11.0; the full design/clone/forced-resume evidence appears under Milestone 9.

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

- [x] Define a shared subtitle cue model with source text, start/end, speaker, timing confidence,
  and source (`engine`, `checkpoint`, or `transcription`).
- [x] Prefer exact engine/segment timings; clearly label estimated chunk timings.
- [x] Export valid UTF-8 SRT and WebVTT from a completed or partially completed take.
- [x] Preserve dialogue speaker identity where the target format permits it.
- [x] Attach subtitle artifacts to the take with hashes and immutable provenance.
- [x] Add optional caption burn-in to Audiogram/Publish without changing the source take.
- [x] Test escaping, multiline cues, Unicode, monotonically increasing times, partial takes, and
  container/codec combinations.

## Milestone 5 — non-destructive finishing and sentence editing

### Intro, outro, and crossfade

- [x] Manage intro/outro uploads as durable assets rather than arbitrary transient paths.
- [x] Add non-destructive assembly settings to a take/publish plan; never rewrite checkpoints.
- [x] Implement concat/acrossfade with overlong crossfades clamped safely.
- [x] Calculate and persist the actual intro offset.
- [x] Shift subtitle cues, chapter marks, timeline spans, and waveform navigation by that offset.
- [x] Leave the narration artifact untouched and report a structured error if an asset is missing or
  unreadable.
- [x] Offer optional loudness normalization as an enhancement, not a parity requirement.
- [x] Verify real FFmpeg output for intro only, outro only, both, zero/overlong crossfade, offsets,
  missing assets, and atomic failure.

### Sentence-level regeneration

- [x] Extend Timeline's chunk model with sentence spans and timing provenance.
- [x] Use exact engine timing where available; allow transcription-derived timing as an explicit
  lower-confidence fallback.
- [x] Regenerate a sentence with the original frozen engine/profile/advanced-control snapshot.
- [x] Trim, level-match within a safe bound, and crossfade the replacement non-destructively.
- [x] Preserve original take/checkpoints and create a new derived Take with provenance.
- [x] Shift subsequent spans and regenerate subtitles/chapters after a duration change.
- [x] Fall back to chunk-level regeneration when sentence timing is unavailable or unreliable.
- [x] Verify bytes/audio outside the replaced span remain unchanged where the format permits exact
  comparison.
- [ ] Perform an audible real-engine seam check with sentence-timed Edge output and retain the
  generated acceptance artifact outside source control. The reproducible live gate passed on
  2026-09-29 using exact Edge word timings grouped into sentence spans; it retained source/revised
  WAVs plus provenance under ignored `.test-runs/seam-acceptance`. The 30 ms crossfade and +0.16 dB
  level correction are verified; final human listening approval remains pending.

## Milestone 6 — durable multi-document queue

- [x] Add multi-select queue creation from imported documents and Library projects.
- [x] Freeze a separate profile, provider/resource revision, source revision, and render plan per
  queue item.
- [x] Persist queue order and item status across process restart.
- [x] Default to sequential execution to protect local VRAM and remote rate limits.
- [x] Continue after one item fails and summarize completed/failed/skipped/cancelled counts.
- [x] Distinguish pause/cancel current item from pause/cancel remaining queue.
- [x] Allow reordering/removal only for items that have not started.
- [x] Surface missing source, missing engine, invalid saved profile, and deleted resource revisions as
  explicit skip/failure reasons.
- [x] Ensure every completed take remains separately editable, publishable, and downloadable.
- [x] Browser-test creation, progress, one-item failure, reload persistence, resume, and final
  summary; pair it with a process-restart SQLite/service test so browser and backend evidence cover
  both halves of restart behavior.

## Milestone 7 — audio transcription utility

- [x] Add faster-whisper as an optional external/local component, loaded only on demand.
- [x] Implement a provider-neutral transcription boundary so other ASR engines can be added later.
- [x] Import managed audio and produce a durable transcript with segment and optional word timings.
- [x] Regroup short ASR utterances into readable paragraphs.
- [x] Export SRT/VTT and optional per-line timestamps.
- [x] Generate clearly labelled **guessed** chapter marks from pauses; do not equate them with source
  document headings.
- [x] Expose model size, language/auto-detect, device, compute type, VAD, and word-timing controls
  through typed metadata.
- [x] Run transcription as a durable job with download/model errors, progress, cancel, restart, and
  atomic artifacts.
- [x] Unit-test against a faithful fake faster-whisper surface and add an opt-in real-model
  acceptance contract.
- [x] Complete the opt-in real-model acceptance run on a supported machine and record its
  interpreter/model/audio/date/result. On 2026-09-29, Python 3.13.5 with `faster-whisper 1.2.1`,
  CTranslate2 4.8.2, PyAV 19.0.0, model `tiny.en`, CPU/int8, and a known Edge-generated English
  fixture produced segments, word timings, progress, positive duration, and both expected terms.

## Milestone 8 — advanced audiogram parity

### Still image and transparent export

- [x] Add managed still-image background upload, crop/fit/position, and preview compositing.
- [x] Preserve the existing solid/chroma background path.
- [x] Add transparent overlay outputs for VP9/WebM, ProRes 4444, and PNG sequences where supported.
- [x] Share one layout resolver between preview, estimate, and final render.

Evidence: immutable PNG/JPEG/WebP assets are stored under the Studio data root with SQLite
metadata and content hashes; jobs freeze the selected asset id, fit mode, and focal position.
The server-owned `AudiogramLayout` is returned by estimate and consumed by the React preview,
while the same resolver drives the FFmpeg graph and estimate cost. Focused API/render coverage
also proves the original solid/chroma graph remains available. Encoder discovery only exposes alpha
formats supported by the local FFmpeg build. VP9 uses `yuva420p`, ProRes uses profile 4444 with
`yuva444p10le`, and PNG frames are atomically packaged with a deterministic manifest; a real FFmpeg
test opens that archive and verifies its frames.

### Geometry, animation, and expressions

- [x] Add linear/polar geometry, bars/line, mirror, smoothing, line width, placement, inner/outer
  radius, pivot, rotation, color, and opacity behind Advanced layout controls.
- [x] Scale polar geometry against the shorter frame dimension and prevent inverted radii.
- [x] Add a safe expression language using a parsed AST whitelist—never `eval()` user text.
- [x] Publish searchable variables/functions from the same registry used by validation.
- [x] Support time-, progress-, frame-, and audio-reactive variables for animatable layout values.
- [x] Disable unsafe cropping when rotation or animation can move content outside predicted bounds.
- [x] Keep the quick FFmpeg visualizers as the normal path; advanced rendering must not slow users
  who do not enable it.
- [x] Test expression escape attempts, preview/final agreement, alpha codecs, even dimensions,
  invalid formulas, cancellation, restart, and atomic output.

Implementation checkpoint: Studio keeps the existing FFmpeg graph for default layouts and selects a
full-frame Pillow/NumPy renderer only when exact advanced geometry is required. Both paths feed the
same durable job lifecycle. The exact path resolves the shared layout for every frame, derives
audio-reactive expression context from the canonical WAV, renders full-canvas RGBA whenever motion
could escape a static crop, and pipes frames back through FFmpeg for audio muxing, captions, and the
selected opaque or alpha-capable codec. Automated coverage includes a real formula-driven polar PNG
sequence, cancellation cleanup, deterministic archives, API validation, and the browser editor.

## Milestone 9 — real-world acceptance and release hardening

### Live providers and local engines

- [ ] Run the opt-in live contract against Gemini and record model/voice/date/result.
- [ ] Run it against Deepgram and record model/voice/date/result.
- [x] Run it against Inworld and record model/voice/date/result. On 2026-09-29, saved resource
  revision 1 used `inworld-tts-2`, voice `Ashley`, and the current `/tts/v1/voice` endpoint; the
  vault-backed live contract returned non-empty canonical 24 kHz mono signed-16-bit PCM without
  exporting or logging the credential.
- [x] Run the Edge provider against the live service. On 2026-09-29, `edge-tts 7.2.8`
  synthesized the acceptance fixture with model `edge-tts` and voice `en-US-AriaNeural`; SPLICR
  verified non-empty canonical 24 kHz mono signed-16-bit PCM plus word-boundary timing metadata.
- [x] Run real Kokoro narration through import -> preview -> render -> resume -> playback. On
  2026-09-29, Python 3.12.14 with Kokoro 0.9.4 and voice `af_heart` imported Markdown, previewed
  the exact persisted plan, rendered a checkpoint, survived a forced service stop, resumed without
  rewriting or re-attempting the completed chunk, assembled canonical WAV, and served range
  playback through the application API.
- [x] Run real Qwen voice design/clone with non-default advanced parameters and forced resume. On
  2026-09-29, Python 3.12.14, `qwen-tts 0.1.1`, CUDA PyTorch 2.11.0, VoiceDesign take 2, and the
  1.7B Base clone model rendered with synthesis seed `424242` plus non-default temperature,
  subtalker temperature, top-k, top-p, and repetition penalty. The forced restart preserved the
  complete frozen profile/control snapshot and did not rewrite or re-attempt the completed chunk.
- [x] Run real Audio8 clone narration with forced resume. On 2026-09-29, Python 3.12.14,
  Transformers 4.57.6, CUDA PyTorch 2.11.0, and the Audio8 0.6B checkpoint cloned an exact-
  transcript Edge reference on an RTX 5070 Ti. A forced restart preserved the completed chunk's
  attempt count, timestamp, and hash before finishing a canonical WAV. This acceptance pass also
  exposed and fixed the upstream processor/decoder contract drift and the invalid-waveform fallback.
- [x] Confirm local engine processes/models are reused only within their intended job/session scope
  and released after completion/cancel/failure. Deterministic adapter/subprocess coverage now proves
  one-session-per-job reuse plus closure after success, cancellation, engine failure, and timeout
  restart; real Kokoro, Qwen, and Audio8 forced-restart runs confirmed process-bound model sessions.

### Crash, scale, and packaging

- [x] Run a long-document forced-termination soak at several chunk boundaries and verify exact resume
  ordering with no duplicate synthesis.
- [x] Force termination during final assembly and verify no partial artifact is marked complete.
- [x] Exercise pause/export/cancel after provider and local-engine failures.
- [x] Test very large imports and outputs near configured limits without loading full media into
  browser or server memory. Automated coverage now crosses the chunked-upload boundary, rejects and
  cleans an over-limit upload, and range-reads converted output. On 2026-09-29 a sparse 3.9 GB
  canonical WAV was range-read at its beginning, midpoint, and end in 1 KB responses, proving the
  application does not materialize a multi-gigabyte playback body in browser/server memory.
- [ ] Test clean Windows installer install, upgrade with existing data/jobs/profiles, uninstall with
  intentional user-data policy, and portable ZIP execution in a clean VM. The reusable PowerShell
  artifact harness now automates the non-interactive subset on a disposable Windows machine and is
  required before workflow upload. Its optional dev.4-to-dev.5 preflight passed both frozen smokes,
  byte-identical external-data preservation, and exact upgraded-payload comparison. Lifecycle /
  Start-menu/browser use, real project/profile/media migration, Windows Settings, and a genuinely
  clean VM remain manual release evidence.
- [x] Verify Chromium acceptance in GitHub Actions and retain failure traces/screenshots/video. The
  workflow runs for pull requests, `main`, `codex/**` integration branches, and release tags. Failed
  run `36664605914` published assertion annotations and retained a 19 MB Playwright diagnostics
  artifact; that evidence exposed missing media tools on the runner. Commit `8f7f18a` provisions the
  checksum-pinned LGPL FFmpeg/FFprobe bundle, and run `36665161955` passed the full six-journey
  Chromium suite on `windows-2025`.
- [x] Update user documentation, migration notes, third-party notices, and release checklist.
  `CHANGELOG.md`, the Windows packaging guide, the release checklist, and the FFmpeg notice now
  record data migration/rollback, external engine ownership, live-evidence gaps, and the pinned
  FFmpeg/OpenH264 packaging policy. The upstream asset is named `lgpl-shared`, but the later
  Chromaprint review found static GPL FFTW3 in the media DLLs; current release documentation and
  package gates use that effective classification instead of the upstream label.

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
- [x] 2026-09-29 — Milestone 4 subtitle/caption gate passed: Ruff, the complete Python suite
  (three opt-in live checks skipped), eight frontend unit tests, the production Vite build, and
  three Chromium journeys. Coverage proves exact engine timing preference, explicitly estimated
  checkpoint fallback, speaker-preserving UTF-8 SRT/WebVTT, monotonic millisecond cues, partial-take
  export, immutable hash/provenance metadata, source-audio preservation, and MP4/WebM caption
  filter/codec combinations.
- [x] 2026-09-29 — Milestone 5 intro/outro gate passed: Ruff, the complete Python suite (three
  opt-in live checks skipped), eight frontend unit tests, the Vite production build, and three
  Chromium journeys. Real FFmpeg coverage includes intro/outro combinations, safe crossfade
  clamps, optional loudness normalization, restart/error recovery, exact offsets, and shifted
  Timeline/caption/chapter navigation without altering source checkpoints.
- [x] 2026-09-29 — Milestone 5 sentence-editing implementation gate passed: Ruff, the complete
  Python suite (three opt-in live checks skipped), eight frontend unit tests, the Vite production
  build, and three Chromium journeys. Coverage proves engine sentence and grouped-word timing,
  explicit transcription fallback, frozen provider settings, safe trim/level/crossfade processing,
  byte-identical PCM outside the replaced span, shifted sentence/subtitle timing, durable recovery,
  immutable source checkpoints, derived-take provenance, and the visible chunk-level fallback.
- [x] 2026-09-29 — Milestone 6 durable queue gate passed: Ruff, the complete Python suite (three
  opt-in live checks skipped), eight frontend unit tests, the Vite production build, and four
  Chromium journeys. SQLite/service coverage proves frozen per-item plans, sequential dispatch,
  failure continuation, process-restart adoption without duplicate synthesis, pause/resume,
  current-versus-remaining cancellation, and not-started-only reorder/remove. Browser coverage
  proves Library multi-select creation, visible progress, pause-after-current/resume, reload
  persistence, one-item provider failure followed by success, final counts, and per-item download.
- [x] 2026-09-29 — Milestone 7 automated transcription gate passed: Ruff, 506 Python tests with
  four explicit live-environment skips, eight frontend unit tests, the Vite production build, and
  five Chromium journeys. Coverage includes the faithful faster-whisper 1.2-style surface,
  provider-neutral normalized timing records, typed options, readable paragraph regrouping,
  guessed-chapter labelling, SRT/WebVTT, line timestamps, structured model errors, cancellation,
  atomic outputs, interrupted-process recovery, managed upload, live browser progress/downloads,
  and reload persistence. The real-model opt-in test remains open by design.
- [x] 2026-09-29 — Milestone 8 advanced audiogram gate passed: Ruff, 530 Python tests with four
  explicit live-environment skips, eight frontend unit tests, the Vite production build, and six
  Chromium journeys. Coverage proves managed image and transparent backgrounds, shared preview and
  render layouts, linear/polar geometry, bars/line/mirror/smoothing/pivots, AST-whitelisted
  time/progress/frame/audio expressions, fast-path isolation, real formula-driven RGBA frame
  rendering, alpha archive metadata, invalid-formula rejection, cancellation cleanup, restart, and
  atomic finalization.
- [x] 2026-09-29 — Milestone 9 deterministic crash/scale gate passed: 533 Python tests with four
  explicit live-environment skips. Release-acceptance coverage repeatedly terminates one long job at
  three checkpoint boundaries, verifies exact ordered resume without duplicate completed calls,
  forces final-assembly replacement failure without publishing a partial output, crosses the
  chunked audio-upload boundary, cleans an over-limit upload, and range-reads the converted output.
  The browser workflow now also runs for release tags and retains Playwright failure diagnostics.
- [x] 2026-09-29 — Milestone 9 deterministic failure/package gate passed: 536 Python tests passed
  with four explicit live-environment skips. Provider and local-engine failures prove pause,
  partial/checkpoint export, cancellation, unpublished final audio, and one-session-per-job cleanup.
  The `0.1.0-dev.2` portable build passed its frozen-executable smoke, including bundled
  FFmpeg/FFprobe discovery and a real lazy-loaded NumPy/Pillow advanced audiogram frame; the
  clean-VM install/upgrade/uninstall matrix remains open.
- [x] 2026-09-29 — Live Edge TTS acceptance passed with `edge-tts 7.2.8`, model `edge-tts`, and
  voice `en-US-AriaNeural`. The real service returned canonical audio and word timing through the
  supervised provider/session protocol; no credentials or sensitive fixture text were used.
- [x] 2026-09-29 — Real faster-whisper acceptance passed with Python 3.13.5,
  `faster-whisper 1.2.1`, CTranslate2 4.8.2, PyAV 19.0.0, and `tiny.en` on CPU/int8. The live gate
  recognized both expected terms from a known Edge-generated fixture and returned segments, word
  timings, progress, and positive duration. The run first exposed PyAV 19's removed metadata
  keywords; SPLICR now applies a worker-scoped compatibility shim with deterministic regression
  coverage rather than requiring users to downgrade their isolated environment. The post-fix full
  suite passed 537 Python tests with four remaining intentional live-environment skips.
- [x] 2026-09-29 — Live Inworld acceptance passed through saved resource revision 1 with
  `inworld-tts-2`, voice `Ashley`, and the current `/tts/v1/voice` endpoint. The live harness
  resolved the credential directly from SPLICR's vault and verified canonical output without
  exporting or logging the secret.
- [x] 2026-09-29 — Real Kokoro lifecycle acceptance passed with Python 3.12.14, Kokoro 0.9.4,
  and `af_heart`: Markdown import, exact preview/persisted-plan agreement, rendering, forced process
  interruption, durable resume without replacing the completed checkpoint, canonical WAV assembly,
  and HTTP range playback all passed through the merged SPLICR service. The expanded full suite
  passed 537 Python tests with five intentional opt-in live-environment skips.
- [x] 2026-09-29 — Real Qwen3-TTS design/clone/resume acceptance passed with Python 3.12.14,
  `qwen-tts 0.1.1`, CUDA PyTorch 2.11.0, VoiceDesign take 2, and the 1.7B Base clone model. Seed
  `424242` and five non-default sampling values remained frozen across a forced process restart;
  the completed PCM checkpoint retained its attempt count, timestamp, and hash before canonical
  WAV assembly.
- [x] 2026-09-29 — Real Audio8 clone/resume acceptance passed with Python 3.12.14,
  Transformers 4.57.6, PyTorch/Torchaudio 2.11.0+cu128, and the Audio8 0.6B checkpoint on an RTX
  5070 Ti. SPLICR cloned an exact-transcript Edge reference, persisted the first PCM checkpoint,
  restarted the engine process, preserved that checkpoint's attempt count/timestamp/hash, and
  assembled canonical WAV. The run also drove a compatibility update for Audio8's current
  `reference_audio`/`reference_text`, generation-result, and decoder-length contracts; three
  implausible outputs now pause the job instead of silently accepting the last bad waveform.
  The post-fix regression suite passed 538 tests with six intentional opt-in live skips.
- [x] 2026-09-29 — Privacy and real Edge sentence-seam acceptance passed its automated gates.
  Diagnostic serialization now redacts local paths as well as credentials, while the existing
  vault/profile/browser audit confirms secrets remain write-only and out of retained artifacts.
  Edge word-boundary timing produced exact grouped sentence spans; a real sentence replacement
  retained source/revised WAVs and provenance under ignored `.test-runs/seam-acceptance`, with a
  30 ms crossfade and +0.155471 dB level adjustment. The full deterministic gate passed 539 Python
  tests with seven opt-in live skips, eight frontend tests, the Vite build, six Chromium journeys,
  and 42 real FFmpeg/FFprobe tests. Human listening approval remains open.
- [x] 2026-09-29 — Multi-gigabyte and internal portable-candidate acceptance passed. A sparse
  3.9 GB canonical WAV returned bounded 1 KB ranges at its beginning, midpoint, and end. The full
  regression suite passed 540 tests with seven intentional opt-in live skips. The
  `0.1.0-dev.3` portable ZIP (220,690,342 bytes) passed packaged smoke from a Unicode/spaces path.
  An isolated rerun left all 1,121 package files unchanged and created state only in the redirected
  per-user data root. Its independently verified SHA-256 is
  `b2bb391bd572b695c094e4f668085a79c22f0bb53c2d40586d3d55ef5cdd76cd`. This is an internal-only
  candidate because installer/clean-VM/signing/malware-scan evidence and public-compatible FFmpeg
  licensing remain open.
- [x] 2026-09-29 — Real frozen lifecycle-window acceptance passed. The packaged launcher now
  exposes its existing no-browser behavior as `--no-browser`, with deterministic argument tests.
  The actual `0.1.0-dev.4` executable started a healthy private service on port 8765, accepted a
  normal close request through its Tk window, exited with code 0, and made `/health` unreachable.
  Full regression passed 543 tests with seven intentional live skips.
- [x] 2026-09-29 — The complete per-user installer candidate built and passed an isolated local
  install/smoke/uninstall cycle. SPLICR now discovers Inno Setup 6 from `PATH`, user-scope, and
  machine-scope installs without scalar-array corruption. The silent install placed the executable,
  notices, and build provenance; packaged smoke returned 0; uninstall returned 0, removed app files,
  and preserved external user data. The 220,689,908-byte portable ZIP SHA-256 is
  `669f9f607e9f35d6fe8741af5fb646a3378b62305248ee2873d195abf42afbeb`; the 151,418,758-byte
  installer SHA-256 is `5d630e34271a0a1a2f57128c73474577f58e427460d6310bb4797518012a0ff2`.
  Clean-VM fresh/upgrade/uninstall acceptance remains open.
- [x] 2026-09-29 — The Windows media bundle moved from the GPL-enabled workstation build to a
  checksum-pinned BtbN asset named `lgpl-shared` upstream. SPLICR detects `libopenh264` as the MP4 fallback,
  preserves FFmpeg's shared DLLs, license, exact asset URL, and SHA-256, and produced a real H.264 /
  AAC MP4 from both the portable build and installed payload. The isolated installer smoke returned
  0; uninstall removed the app and preserved redirected per-user data. The final 179,300,537-byte
  portable ZIP SHA-256 is `bdf188b2db2ece4ee3f33b0bc59b7612497de92e5fa4c926ce9ba46f8fcfeef8`;
  the 119,685,499-byte installer SHA-256 is
  `5fe9d9bc36479da65ec879ac84ba111fff7f2ee313748c8fd131eeecbbb8e605`. Ruff and the full regression
  suite passed (546 tests, 7 intentional live skips). Later transitive review proved this asset's
  Chromaprint statically includes GPL FFTW3, superseding the then-current LGPL-only assumption.
  Public release still needs corresponding-source publication and final compliance review.
- [x] 2026-09-29 — Automated Windows artifact acceptance became a required pre-upload workflow gate.
  The same `0.1.0-dev.5` portable ZIP and installer passed checksum verification, package smoke,
  Unicode/spaces extraction with an unchanged package tree, redirected state isolation, installed
  shared-library/provenance checks, a real OpenH264 H.264/AAC MP4 probe, uninstall cleanup, and
  preserved user data. An optional dev.4-to-dev.5 run also preserved a byte-identical external data
  marker and proved the upgraded install matched the current portable payload with no stale files.
  The harness writes a machine-readable acceptance JSON beside the artifacts; the interactive
  clean-VM and representative-data upgrade-migration matrix remains open.
- [x] 2026-09-29 — FFmpeg source compliance moved from an unstructured release note to an executable,
  fail-closed audit. The exact FFmpeg, OpenH264, and BtbN recipe snapshots are hash-pinned; CI builds
  and validates an explicitly incomplete primary-source audit kit, and its manifest cannot claim
  corresponding-source completeness. The exact 90-stage enabled graph, pinned revision table, and
  source-fetch commands are now versioned and validated. Fetching those sources, their notices,
  correspondence proof, and the hosted source URL remain open in `docs/FFMPEG_DISTRIBUTION.md`.
- [x] 2026-09-29 — The enabled FFmpeg graph gained a digest-pinned, resumable source collector with
  deterministic per-stage archive plans. Plan acceptance covers all 90 stages plus stage-selection,
  unknown-stage, and tampered-recipe failures. A real OpenH264 run through the pinned image then
  verified archive checksums, exact commit/license content, fail-closed status, and resume reuse;
  the full network collection and legal review remain release gates rather than inferred successes.
- [x] 2026-09-29 — GitHub-hosted Chromium acceptance became executable on pushed `codex/**`
  integration branches. The first diagnostic rerun published two specific media-capability failures
  plus its retained Playwright artifact; provisioning the same pinned LGPL FFmpeg/FFprobe bundle used
  by packaging fixed both, and public run `36665161955` passed all six Studio journeys.
- [x] 2026-09-29 — FFmpeg compliance review gained a deterministic, checksum-gated license/notice
  candidate inventory and a pinned-graph review validator. Synthetic positive/negative coverage
  passed, and the real OpenH264 source archive produced a cryptographically identified
  `BSD-2-Clause` record whose required notice is hash-anchored in the packaged legal surface.
- [x] 2026-09-30 — The incremental collector fetched pinned libogg into a 500,976-byte normalized
  archive; the inventory and review pipeline recorded `BSD-3-Clause` and hash-anchored its verbatim
  binary notice. A third real run reviewed pinned zlib as `Zlib`, recorded that its acknowledgment
  is optional for binary distribution, and excluded unrelated contrib licenses based on the actual
  root build recipe. Three of 92 pinned source locators now have source/license evidence; full
  collection, review, codec patent analysis, correspondence, and publication remain open.
- [x] 2026-09-30 — Source compliance work became safely batchable: ordered repeated stage selection,
  archive reuse, and a 12 GiB host/container reserve passed full-plan and negative tests. A real
  three-stage batch reused every accumulated archive, and all five detected candidates reconcile
  exactly to three shipped-license records or two recipe-proven not-built dispositions.
- [x] 2026-09-30 — Four more graph-pinned source stages (mingw-std-threads, libopus, libunibreak,
  and snappy) were collected in one bounded batch, then TwoLAME was reviewed separately. Eight of
  92 source locators now reconcile 12 detected candidates into eight shipped licenses, one
  supplemental notice, and three recipe-proven not-built records. A package-wide license manifest
  now fetches and hash-verifies TwoLAME's exact LGPL-2.1-or-later `COPYING` file; Windows build and
  artifact acceptance require it because FFmpeg's LGPLv3 file is not equivalent. The real
  `0.1.0-dev.6` portable/installer acceptance passed with the manifest-bound license in both
  payloads, and hosted browser run `36670631733` passed commit `636a46a`.
- [x] 2026-09-30 — A bounded AMF, libffi, libpng, and OpenJPEG batch raised exact source/license
  coverage to 12 of 92 locators. All 27 detected candidates now reconcile to 12 shipped licenses,
  one supplemental notice, or 14 recipe-proven not-built records. AMF and OpenJPEG use exact
  manifest-bound package license files; libffi's required MIT notice is hash-anchored in the
  combined notices; and libpng's root `libpng-2.0` license and non-built CI/contrib candidates are
  explicit. Patent-rights caveats remain visible and unresolved rather than being overclaimed. Real
  `0.1.0-dev.7` portable/installer acceptance passed with exact AMF, OpenJPEG, and TwoLAME license
  identity verified in both payloads against the manifest. Hosted browser run `36722600815` passed
  all six Studio journeys on acceptance-record commit `f0666c4`.
- [x] 2026-09-30 — A bounded dav1d, FFTW3, FriBidi, and libsamplerate batch raised exact review
  coverage to 16 of 92 locators and 35 candidates: 14 shipped licenses, two supplemental notices,
  14 not-built records, and five build-only/not-shipped records. Exact dav1d BSD/AOMedia patent and
  FriBidi LGPL-2.1-or-later files are now manifest-bound package payloads. The packaged FFmpeg
  configuration verifies dav1d/FriBidi are enabled while FFTW3/libsamplerate and their disabled
  librubberband consumer are absent. A collected ffnvcodec stage remains pending a dedicated
  embedded-header notice review and is not counted as completed. Real `0.1.0-dev.8` portable and
  installed-package acceptance passed with all six dependency files verified by exact manifest
  revision and SHA-256. Hosted browser run `36728460149` passed all six Studio journeys on
  acceptance-record commit `a4617bc`.
- [x] 2026-09-30 — The dedicated ffnvcodec embedded-header review raised coverage to 19 of 92
  locators and 50 candidates. A tracked supplemental-path manifest now brings license-bearing files
  with nonstandard names into deterministic inventory. All five MIT-bearing primary headers used by
  FFmpeg 9 are exact manifest-bound package files; the ten sdk/13.0 and sdk/11.1 candidates are
  recipe-proven not built for this FFmpeg 9 payload. Real `0.1.0-dev.9` portable and installed-
  package acceptance verified all 11 manifest-bound dependency files. Hosted browser run
  `36735091359` passed all six Studio journeys on acceptance-record commit `1653ec9`.
- [x] 2026-09-30 — A bounded Game Music Emu, GMP, Kvazaar, and LCEVCdec review raised coverage to
  23 of 92 source locators and 69 candidates: 24 shipped licenses, five supplemental notices, 35
  not-built records, and five build-only/not-shipped records. Eight exact new manifest-bound files
  preserve GME's LGPL/MIT terms, GMP's LGPLv3 and accompanying GPL texts, Kvazaar's BSD notice, and
  LCEVCdec's Clear BSD plus explicit no-patent-license notice. The exact recipes prove 11 auxiliary
  candidates are excluded, and the fetcher plus fail-closed reconciliation suites passed. Real
  `0.1.0-dev.10` portable and installed-package acceptance verified all 19 manifest-bound legal
  files plus the existing media and lifecycle checks. Hosted browser run `36741351275` passed all
  six Studio journeys on acceptance-record commit `a561216`.
- [x] 2026-09-30 — A bounded libvpx, libwebp, libzmq, and OpenCORE AMR review raised coverage to
  27 of 92 source locators and reconciled all 87 candidates: 30 shipped licenses, nine supplemental
  notices, 43 recipe-proven not-built records, and five build-only/not-shipped records. Ten new
  manifest-bound files preserve the WebM license/patent terms, compiled x86inc and wepoll notices,
  libzmq's MPL-2.0 terms, and OpenCORE's Apache, attribution, and explicit no-patent-rights texts.
  The exact recipes exclude eight test, example, optional-WebSocket, and packaging candidates. The
  fetcher plus fail-closed reconciliation suites passed. Real `0.1.0-dev.11` portable and installed-
  package acceptance verified all 29 manifest-bound legal files plus the existing media and
  lifecycle checks. Hosted browser run `36747089346` passed all six Studio journeys on acceptance-
  record commit `d4d76f7`.
- [x] 2026-09-30 — A bounded libudfread, oneVPL, PCRE2, and pixman review raised coverage to 31 of
  92 source locators and reconciled all 108 candidates: 34 shipped licenses, ten supplemental
  notices, 59 recipe-proven not-built records, and five build-only/not-shipped records. Five new
  manifest-bound files preserve libudfread's LGPL-2.1, oneVPL's MIT, PCRE2's BSD terms and binary-
  package exception plus its upstream licence pointer, and pixman's MIT terms. Exact recipe/source
  paths exclude the oneVPL examples and tests plus PCRE2's CMake scripts; PCRE2 JIT defaults off, so
  absent SLJIT is not incorporated. The fetcher and fail-closed reconciliation suites passed, using
  byte-identical immutable mirrors around Code.Videolan and GitLab automated-client challenges. Real
  `0.1.0-dev.12` portable and installed-package acceptance verified all 34 manifest-bound legal files
  plus the existing media and lifecycle checks. Hosted browser run `36753606918` passed all six
  Studio journeys in 41.7 seconds on acceptance-record commit `2b54b3c`.
- [x] 2026-09-30 — A bounded Little CMS, OpenAL Soft, SoX Resampler, and uavs3d review raised
  coverage to 35 of 92 source locators and reconciled all 123 candidates: 44 shipped licenses,
  eleven supplemental notices, 61 recipe-proven not-built records, and seven build-only/not-shipped
  records. Eleven new manifest-bound files preserve the compiled MIT, LGPL, BSD, Apache, fmt, GSL,
  and embedded PFFFT terms. SoXR's source-embedded notice is now a deterministic supplemental
  candidate. Disabled jpgicc/LSR tests are excluded, while the separately built GPL-3.0 Little CMS
  plugins are unincorporated static archives absent from the package. The fetcher plus exact-batch,
  tracked, synthetic, and negative reconciliation suites passed for all 45 manifest files. Real
  `0.1.0-dev.13` portable and installed-package acceptance independently verified all 45 files plus
  the existing media and lifecycle checks. Hosted browser run `36757811792` passed all six Studio
  journeys in 50.3 seconds on acceptance-record commit `32deb7a`; AVS3 patent review remains open.
- [x] 2026-09-30 — A bounded Brotli, JPEG XL, Mbed TLS, and librist review raised coverage to 39 of
  92 source locators and reconciled all 140 candidates: 51 shipped licenses, twelve supplemental
  notices, 68 recipe-proven not-built records, and nine build-only/not-shipped records. Eight new
  manifest-bound files preserve the compiled MIT, BSD, Apache, dual Apache/GPL, and JPEG XL patent-
  grant terms. Disabled JPEG XL extras, experimental ML-DSA, and librist's vendored Mbed TLS are
  excluded; both Mbed TLS framework submodules are build-time-only. The validator now supports the
  graph-pinned `v4.2.0` release tag while rejecting unsafe arbitrary refs. The PowerShell downloader
  independently fetched and SHA-256-verified all 53 manifest files, while exact-batch, tracked,
  synthetic, and negative reconciliation suites passed. Real `0.1.0-dev.14` portable and installed-
  package acceptance independently verified all 53 files plus the existing media and lifecycle
  checks. Hosted browser run `36761944917` passed all six Studio journeys in 44.2 seconds on
  acceptance-record commit `be38ad8`.
- [x] 2026-09-30 — A bounded LV2, Serd, Zix, Sord, Sratom, and Lilv review raised coverage to 45 of
  92 source locators and reconciled all 168 candidates: 58 shipped licenses, twelve supplemental
  notices, 74 recipe-proven not-built records, and 24 build-only/not-shipped records. Seven new
  manifest-bound files preserve the linked ISC notices, including both non-identical Zix texts.
  Recipe/source evidence excludes disabled documentation, tools, tests, benchmarks, and Python
  bindings; LV2 schemas and build metadata remain intermediate-only. The inventory now resolves
  safe relative in-archive license symlinks and rejects escape attempts. The downloader independently
  fetched and SHA-256-verified all 60 manifest files, and exact-batch, tracked, synthetic, and
  negative reconciliation suites pass. Real `0.1.0-dev.15` portable and installed-package acceptance
  independently verified all 60 files plus the existing media and lifecycle checks. Hosted browser
  run `36765143610` passed all six Studio journeys in 43.6 seconds on acceptance-record commit
  `8e33227`.
- [x] 2026-09-30 — A bounded Chromaprint, LAME, Theora, and Vorbis review raised source coverage to
  49 of 92 locators and reconciled all 180 candidates: 63 shipped licenses, fifteen supplemental
  notices, 81 recipe-proven not-built records, and 21 build-only/not-shipped records. Eight new
  manifest files preserve the four libraries' exact terms and notices. The batch also corrected
  FFTW3 from build-only to statically incorporated through Chromaprint, making the current media
  DLLs GPL-covered despite the upstream `lgpl-shared` asset name. Review metadata, notices, source
  evidence, and package-gate assertions are implemented; exact-batch/global validators and the
  68-file manifest fetch pass. A real `0.1.0-dev.16` build passed the tracked Windows package
  harness, including portable/install payload parity, dependency-license and static-FFTW evidence,
  media generation, uninstall, and user-data preservation. Its schema-v2 acceptance JSON is present;
  hosted-browser evidence remains open.
- [x] 2026-10-01 — The ready libxml2, XZ/liblzma, SDL2, and ZVBI batch is promoted and validated,
  raising tracked review coverage to 53 of 92 locators and all 200 candidates in the combined
  inventories. The package manifest now contains 70 exact files. ZVBI adds an independently proven
  GPL-2.0-only static-link path, while SDL2 is explicitly build-only because SPLICR excludes
  `ffplay.exe`. Rebuilt dev.16 portable and installer artifacts pass schema-v2 acceptance; hosted
  browser evidence and the remaining prepared source batches are still open.
- [x] 2026-10-01 — The ready GNU libiconv batch is promoted and validated, raising tracked coverage
  to 55 of 92 locators and 213 exact candidates. Four exact libiconv legal files bring the package
  manifest to 74 records; the rebuilt dev.16 portable and installer pass schema-v2 lifecycle
  acceptance under PowerShell 7. Hosted browser evidence, companion-license schema support for the
  font batch, and the remaining prepared batches are still open.
- [x] 2026-10-01 — The Fontconfig, HarfBuzz, and bootstrap/final FreeType batch is promoted and
  validated, raising tracked coverage to 59 of 92 locators and 232 exact candidates. Nine exact
  font-stack legal files bring the package manifest to 83 records, while the new companion schema
  binds Fontconfig's separate Unicode-3.0 terms to the exact reviewed candidate. The bounded Python
  fetcher handles explicitly declared Gitiles base64 transport and passed both PowerShell 5/7
  negative validation. Rebuilt dev.16 portable and installer artifacts pass schema-v2 lifecycle
  acceptance under PowerShell 7. Hosted browser run
  [`36913670670`](https://github.com/seabAu/Splicr/actions/runs/36913670670) passed all six Studio
  journeys in 45.8 seconds on commit `9e3d8ee`; the remaining prepared source batches are still open.
- [x] 2026-10-01 — The aribb24, libaribcaption, libass, and libbluray batch is promoted and
  validated, raising tracked coverage to 63 of 92 locators and 249 exact candidates. Nine exact
  legal files bring the manifest to 92 records. Build-manifest evidence records the OpenSSL-replaced
  MD5 body, wrong-architecture assembly, disabled BD-J ASM payload, and tools-only getopt fallback
  as not built. The real dev.16 portable and installer passed schema-v2 lifecycle acceptance with
  all 92 manifest files. Portable SHA-256:
  `efd590cb5321c3dc1cf62bfb9e88f50c8ed939b989eec26a5beab6fe9eccb854`; installer SHA-256:
  `ed928b4b0e0f54de2c525fcef98abd22f02131b5bc3b428709a38c0d8817c21c`. Hosted browser run
  [`36917251299`](https://github.com/seabAu/Splicr/actions/runs/36917251299) passed all six Studio
  journeys in 41.3 seconds on commit `0575c89`.
- [x] 2026-10-01 — The OpenSSL stage is promoted and validated, raising tracked coverage to 64 of
  92 locators and 253 exact candidates. The exact Apache-2.0 license brings the manifest to 93
  records; cloudflare-quiche and its nested BoringSSL dependency are recipe-proven not built. The
  real dev.16 portable and installer passed schema-v2 lifecycle acceptance with all 93 manifest
  files. Portable SHA-256:
  `75cae844c1b909cd56bcba8af99529dce9491c8090fcf6ea1d8334747c2a82ae`; installer SHA-256:
  `3c5bfc0b049fb3bd0e0c8a53567fc199d1b8758dbb134c61d518aa52f82200df`. Hosted browser run
  [`36919996114`](https://github.com/seabAu/Splicr/actions/runs/36919996114) passed all six Studio
  journeys in 53.8 seconds on commit `950b0c1`.
- [x] 2026-10-01 — SVT-AV1, libva, and VVenC are promoted and validated, raising tracked coverage
  to 67 of 92 locators and 262 exact candidates. Eight exact legal files bring the manifest to 101
  records. The real dev.16 portable and installer passed schema-v2 lifecycle acceptance at
  `2026-10-01T20:38:38.9403150Z` with all 101 files. Portable SHA-256:
  `9a235c9a3e764fb512a718036e3fb98bc0edf73d990a8a1ea1ed15386b5f3607`; installer SHA-256:
  `e22916cb52b474451b49e7d7931eddeda3f3465a3f7ff78aada8bcfc1006d9dc`. Hosted browser run
  [`36923571926`](https://github.com/seabAu/Splicr/actions/runs/36923571926) passed all six Studio
  journeys in 44.1 seconds on commit `e76e3e5`. rav1e remains open until its time-dependent Cargo
  dependency closure is completely reconciled and packaged.
- [x] 2026-10-01 — libplacebo is promoted and validated, raising tracked coverage to 68 of 92
  locators and 283 exact candidates. Fourteen exact legal files bring the manifest to 115 records,
  including recursive-submodule and compiled source notices. The real dev.16 portable and installer
  passed schema-v2 lifecycle acceptance at `2026-10-01T21:01:26.4972742Z` with all 115 files.
  Portable SHA-256: `aba0200ad839480fb8b1354d93b4d4f06f5a390de2c325ca1aab330651a6bf25`;
  installer SHA-256: `4899de203fd0ea1007e679df9959112868f70a2b44b24bed25a7955208b9854c`.
  Hosted browser run [`36927179317`](https://github.com/seabAu/Splicr/actions/runs/36927179317)
  passed all six Studio journeys in 42.1 seconds on implementation commit `13ff415`.
- [x] 2026-10-01 — OpenCL-Headers, OpenCL-ICD-Loader, and OpenMPT are promoted and validated,
  raising tracked coverage to 71 of 92 locators and 328 exact candidates. Nine exact legal files
  bring the manifest to 124 records, including the selected OpenMPT/minimp3 grants and four compiled
  public-domain provenance notices. The real dev.16 portable and installer passed schema-v2 lifecycle
  acceptance at `2026-10-01T21:31:28.4930829Z` with all 124 files. Portable SHA-256:
  `d534fe19b863baf808d368693a26b9a9fda6391b3cb4e70fab8dbaa4e04b6b4f`; installer SHA-256:
  `f08f504073be7a42bac4b7b29a0d6e9764a1d9d35548aa1ebcfa8516acddb816`. Hosted browser
  run [`36929574347`](https://github.com/seabAu/Splicr/actions/runs/36929574347) passed all six
  Studio journeys in 43.9 seconds on implementation commit `b18f7d4`.
- [x] 2026-10-01 — The Vulkan-Headers, Vulkan-Shim-Loader, Shaderc/glslang/SPIRV-Tools,
  SPIRV-Cross, and standalone SPIRV-Headers batch is promoted and validated, raising tracked
  coverage to 77 of 92 locators and 371 exact candidates. Twenty-eight exact legal files bring the
  manifest to 152 records, including Shaderc's complete pinned dependency closure and the generated
  parser's paired GPL/Bison-exception evidence. The real dev.16 portable and installer passed
  schema-v2 lifecycle acceptance at `2026-10-01T21:55:20.5653230Z` with all 152 files. Portable
  SHA-256: `2df198360b03a74ebd21617d10d35091022bf444946295e5901c87bdd1e67f8d`; installer SHA-256:
  `859418fce2d738cd8ca33a87ff6dfcfee3ec41de478aff0398f6a034366199ae`. Hosted browser run
  [`36932068565`](https://github.com/seabAu/Splicr/actions/runs/36932068565) passed all six Studio
  journeys in 44.4 seconds on implementation commit `fdff678`.
- [x] 2026-10-01 — The independently complete libcurl and SRT subset is promoted and validated,
  raising tracked coverage to 79 of 92 locators and 384 exact candidates. Ten exact legal files
  bring the manifest to 162 records, preserving libcurl's curl/ISC terms and SRT's MPL, BSD,
  Unlicense, and public-domain notices. libssh stays deferred until a real build log or link map
  resolves its conditional MinGW objects. The real dev.16 portable and installer passed schema-v2
  lifecycle acceptance at `2026-10-01T22:13:42.0809380Z` with all 162 files. Portable SHA-256:
  `457447fa80315530fe7a631c90788af879fa023e3cf6de1c3c96d072511aaeeb`; installer SHA-256:
  `221cc01dab433076127f71f0f1e0d6f096bf6e7557ee015294a128ece219231b`. Hosted browser run
  [`36933969511`](https://github.com/seabAu/Splicr/actions/runs/36933969511) passed all six Studio
  journeys in 43.4 seconds on implementation commit `6da624f`.
- [x] 2026-10-01 — The independently complete OpenAPV, zimg, and AOM subset is promoted and
  validated, raising tracked coverage to 82 of 92 locators and 401 exact candidates. Seven exact
  legal files bring the manifest to 169 records, preserving OpenAPV's BSD terms and AOM's BSD,
  patent, fastfeat, libyuv, vector, and x86inc notices. zimg's WTFPL terms remain in corresponding
  source and require no binary notice. VMAF stays deferred pending its MinGW stdatomic proof and
  companion MIT rule. The real dev.16 portable and installer passed schema-v2 lifecycle acceptance
  at `2026-10-01T22:34:12.9787652Z` with all 169 files. Portable SHA-256:
  `e2e905f549144a6e4ba55878199679cfe997aed9f62fb5c3fcd2f3b4356abd08`; installer SHA-256:
  `de34f869c48488eafffc30ca049877edae6ab666605d54eb639c4cf93a6356fd`. Hosted browser run
  [`36936124562`](https://github.com/seabAu/Splicr/actions/runs/36936124562) passed all six Studio
  journeys in 43.7 seconds on implementation commit `4094bf0`.
- [x] 2026-10-01 — The MinGW-w64 foundation stage is promoted and validated, raising tracked
  coverage to 83 of 92 locators and 412 exact candidates. Three exact root, runtime, and winpthreads
  notices bring the manifest to 172 records. The ambiguous Cephes wording is preserved conservatively,
  while package inspection shows the relevant math calls resolve to Windows UCRT and no distinctive
  Cephes implementation markers are incorporated. The real dev.16 portable and installer passed
  schema-v2 lifecycle acceptance at `2026-10-01T22:53:59.5145337Z` with all 172 files. Portable
  SHA-256: `994e056fb9120f725db295d18ab6c7720b25edddfaa7af453b6209f2a75cbc1c`; installer SHA-256:
  `9e8329c0429ce11662f9d58816a90351a86f7fa2fbfca3f1bcbd3d8d3ea4ee3f`. Hosted browser run
  [`36938236224`](https://github.com/seabAu/Splicr/actions/runs/36938236224) passed all six Studio
  journeys in 44.1 seconds on implementation commit `19850b3`.
- [x] 2026-10-01 — The two libiconv fallback transports are closed as commit-identical aliases of
  their already-reviewed primary locators. Coverage rises to 85 of 92 locators without duplicating
  the source tree's 13 candidates: reconciliation remains 412 candidates and the legal manifest
  remains 172 files. The validator's positive and negative cases enforce pinned-revision identity,
  one alias record per locator, a directly reviewed canonical locator, and no alias chains. Hosted
  browser run [`36939425939`](https://github.com/seabAu/Splicr/actions/runs/36939425939) passed all
  six Studio journeys in 41.8 seconds on implementation commit `b998c22`.
- [x] 2026-10-01 — The VMAF stage is promoted and validated, raising tracked coverage to 86 of 92
  locators and 424 exact candidates. Ten exact legal files bring the manifest to 182 records,
  including VMAF's compiled embedded notices and a separately pinned full MIT companion for
  `mkdirp.c`. Configuring the pinned source with the recipe's Windows cross-file under GCC 16.2.0
  reports the compiler-provided `stdatomic.h` usable, proving neither bundled compatibility header
  is selected. The real dev.16 portable and installer passed all twelve schema-v2 lifecycle checks
  at `2026-10-01T23:40:19.8161998Z`. Portable SHA-256:
  `caacdef6ad61c13986d8a33667a7e82b4cc03d5c2fa8149910aa9e231b04bcf5`; installer SHA-256:
  `babdee6a060ad6f1de53cd0afb473d1651faafa92e91e005efd638dc4c274464`. Hosted browser run
  [`36942172393`](https://github.com/seabAu/Splicr/actions/runs/36942172393) passed all six Studio
  journeys in 41.8 seconds on implementation commit `0898707`.
- [x] Earlier merger baseline — real FFmpeg conversion/audiogram smoke and frozen Windows package
  smoke passed; see the repository history and linked architecture/handover documents.

## Current work pointer

- **Active milestone:** Milestone 9 — real-world acceptance and release hardening, including the
  remaining Milestones 2/3/5/7 live-environment evidence.
- **Next implementation slice:** continue the bounded FFmpeg source/license review in
  `docs/FFMPEG_DISTRIBUTION.md`, while preserving the remaining credential and clean-VM checks in
  `docs/RELEASE_CHECKLIST.md`. Eighty-six of 92 source locators are reviewed or validated aliases;
  the current artifacts pass the normal PowerShell 7 package harness and exact-commit hosted-browser
  acceptance.
  Gemini/Deepgram
  credentials, the clean-VM matrix, complete FFmpeg corresponding
  source/compliance publication, malware/signing evidence, and audible sentence-seam acceptance
  remain.
- **Clean-VM routing:** the current workstation has no Windows Sandbox binary or Hyper-V,
  VirtualBox, VMware, or QEMU management CLI. The clean-VM matrix must run on a separate disposable
  Windows environment; local package-harness results are not a substitute.
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
- **2026-09-29:** Completed Milestone 4 subtitle timelines and caption delivery. Shared cues retain
  source text, speaker, timing source, and confidence; exact provider timing wins while checkpoint
  alignment is explicitly estimated. Narrate, Dialogue, Timeline, and Publish export immutable
  UTF-8 SRT/WebVTT artifacts from complete or partial takes, and Audiogram can burn a derived SRT
  into MP4/WebM output while preserving and hashing the original take and caption provenance.
- **2026-09-29:** Completed Milestone 5 intro/outro finishing. Managed audio assets and durable jobs
  persist the exact source, hashes, requested/effective crossfades, loudness option, output duration,
  and real intro offset. FFmpeg writes a derived canonical WAV atomically while source checkpoints
  remain unchanged; shifted captions, chapters, Timeline segments, waveform, span playback, and
  publishing selections all resolve against the same finished artifact. Real FFmpeg combinations,
  restart/error behavior, API integration, and the progressive Publish workflow are covered.
- **2026-09-29:** Completed the mocked/automated sentence-editing portion of Milestone 5. Timeline
  now exposes reliable engine or transcription sentence spans, defaults to narrowly scoped repair,
  and clearly falls back to whole-chunk regeneration without guessing. Replacements reuse the
  original frozen provider revision and controls, are trimmed/level-matched/crossfaded into a new
  durable checkpoint, preserve source bytes outside the old sentence span, shift later timing and
  subtitle cues, and retain immutable-source provenance in the derived job/RenderPlan/Take. The
  remaining acceptance item is a human audible seam check with a configured real timed engine.
- **2026-09-29:** Completed Milestone 6. Library now creates persistent multi-document queues from
  saved projects and profiles; every item freezes its source hash/text, resolved voice/settings,
  provider revision, and precomputed synthesis plan. A coordinator owns sequential dispatch,
  restart adoption, current-versus-remaining pause/cancel scopes, not-started-only reorder/remove,
  failure continuation, and terminal counts. Completed jobs are indexed as separate takes on their
  original Library projects. Full Ruff/Python/frontend/build gates and four Chromium journeys pass;
  the batch journey covers creation, progress, pause/resume, reload persistence, mixed failure
  continuation, summary, and per-item download.
- **2026-09-29:** Completed Milestone 7. Added an isolated, lazy
  faster-whisper component and provider-neutral ASR contract; durable restartable/cancellable jobs;
  structured model/download errors; managed audio import; segment and word timing JSON; readable
  paragraph regrouping; per-line Markdown timestamps; SRT/WebVTT; and explicitly labelled guessed
  chapters. Convert exposes a separate Transcribe mode with essential controls first and hardware,
  precision, VAD, word timing, and pause thresholds behind one advanced disclosure. Faithful worker,
  restart/cancel/atomic-output, API/download, and Chromium import/progress/reload tests pass. Real
  `tiny.en` CPU/int8 recognition also passed with expected-term, segment, word-timing, progress, and
  duration evidence; a worker-scoped compatibility shim supports PyAV 19's simplified `open` API.
