# SPLICR Studio integration architecture

## Product boundary

SPLICR Studio is a local-first authoring and rendering application. It combines SPLICR's durable,
provider-neutral long-document synthesis pipeline with Narrator's local engines, voice tooling,
editing, dialogue, media conversion, audiograms, library, and publishing workflows.

The public website is a separate distribution surface for documentation, a lightweight demo, and
downloads. Authcore is therefore not part of the local Studio runtime.

## Shared domain

The live application uses one hierarchy:

```text
Project
  -> Render Plan (immutable revision)
       -> ordered Render Segments
  -> Take (one execution of one plan revision)
       -> Artifacts (audio, video, subtitles, chapters, transcript, manifest)
```

- A **Project** owns source text and authoring metadata.
- A **Render Plan** freezes segmentation, engine/voice routing, instructions, and settings so a
  render can be reproduced even after the editor changes.
- A **Take** records one resumable execution. Multiple takes never overwrite one another.
- An **Artifact** is a durable output with identity, type, path, size, optional checksum, and
  immutable provenance metadata.

Existing SPLICR jobs will initially map one-to-one to takes. Existing Narrator take records and
project manifests will be imported through compatibility adapters rather than becoming the new
storage schema directly.

## Engine boundary

All synthesis engines use one adapter contract and one job-scoped session:

```text
orchestrator
  -> EngineAdapter.open_session(job context)
       -> EngineSession.synthesize(segment)
```

The adapter advertises a transport without leaking it into orchestration:

- `remote_http`: Gemini, Deepgram, Inworld, and configurable API resources
- `local_subprocess`: isolated Python environments such as Kokoro, Qwen3-TTS, Audio8, and Edge TTS
- `local_http`: a separately managed local model server

Remote SPLICR providers are first wrapped with `ProviderEngineAdapter`; this preserves current
behavior while orchestration migrates. Local adapters may keep a model or subprocess alive for the
entire take, then release it when the session closes. Every adapter must still return canonical
mono PCM16 at 24 kHz before shared checkpointing and assembly.

The current bridge opens a session lazily on the first chunk that actually needs synthesis, reuses
it for every remaining uncached chunk and retry in that job, and closes it before final assembly.
A fully checkpointed resume therefore does not start an engine merely to assemble its artifacts.

The first local implementation uses a supervised JSON-Lines subprocess. Control messages remain
small; the worker atomically writes raw PCM into the job-private engine directory and the parent
validates the exact path, size, frame alignment, and reported audio format before checkpointing.
Startup and synthesis timeouts terminate an unhealthy process, cancellation cannot leave the
worker running, and stderr tail data is attached to redacted engine diagnostics. Kokoro is the
first adapter and reuses an existing isolated environment through its Python executable. Generic
REST resources pointed at loopback hosts provide the local HTTP transport.

Edge TTS deliberately uses the same supervised subprocess boundary even though synthesis is
online: Studio invokes the Python module from the configured external environment and never relies
on a movable `edge-tts.exe` shim. Voice/language discovery is an explicit Components action that
atomically caches a normalized catalog without delaying startup. The worker streams Edge MP3 plus
word or sentence boundaries, FFmpeg normalizes audio to canonical mono PCM16 at 24 kHz, and the
provider-neutral chunk record retains timing metadata for later subtitle/timeline work. Studio
does not create, mutate, upgrade, or delete engine environments; see
[`LOCAL_ENGINE_ONBOARDING.md`](LOCAL_ENGINE_ONBOARDING.md).

The 2026-09-28 integration smoke reused the existing Narrator Kokoro environment in place and
produced a mono, 16-bit, 24 kHz WAV through SPLICR's production queue, checkpoint, and assembly
path. The repository still contains neither that environment nor its model cache.

## Persistence and compatibility

The SPLICR SQLite store remains the authoritative durable execution store during migration. The
additive `studio_projects`, `studio_render_plans`, `studio_render_segments`, `studio_takes`,
`studio_artifacts`, `studio_voice_profiles`, and `studio_imports` tables now persist the shared
hierarchy without changing
legacy job tables. Foreign keys enforce project/plan/take ownership, render-plan rows are
insert-only, and take artifact identifiers are derived from artifact rows rather than duplicated.

Speech jobs also persist a portable, user-facing export stem independently of their immutable job
ID. Allocation is case-insensitive and deterministic (`name`, `name-2`, …), while internal storage
continues to use the job ID. A checkpoint export is an atomic point-in-time ZIP of WAV-wrapped PCM
copies plus a UTF-8 manifest; it never rewrites source checkpoints and always declares that it is
not a finished master. Missing or incomplete checkpoints remain explicit manifest entries, so
paused, failed, and cancelled work can be recovered without overstating completion.

Subtitle delivery uses a provider-neutral cue model over the same immutable checkpoints. Edge-style
engine timing becomes exact cues; providers without alignment data produce clearly labelled
checkpoint estimates. Complete and contiguous partial prefixes can be exported as UTF-8 SRT or
WebVTT, preserving dialogue speaker identity and attaching the content hash, source job/take/plan,
timing-source summary, and partial state to the Studio Artifact. Audiogram caption burn-in consumes
that derived subtitle artifact and records its identity/hash on the video artifact; neither path
rewrites source PCM or the master WAV.

`splicr migrate-studio` converts every existing SPLICR job into a deterministic Project, immutable
Render Plan, and Take, then links a completed WAV as an Artifact when it exists. Import mappings
and fingerprints make reruns idempotent while still allowing take status to catch up with a legacy
job. A changed chunk/configuration is rejected instead of silently rewriting an imported plan.

The speech-job API also invokes this adapter as a live synchronization boundary. Creating or
reading a job now upserts its Project metadata and Take state, while the immutable plan is written
once and a completed WAV is linked once. Identical polls are no-ops. The synthesis service remains
unaware of Studio UI persistence, and an indexing failure cannot turn an already-queued synthesis
into an apparent submission failure.

The same command can scan a supplied Narrator `narrator_data` directory. Its library entries become
Studio projects with stable identifiers and retained source/config/output paths. Pronunciations and
whole-word substitutions are copied additively into Studio's language store, without overwriting a
current Studio rule. Settings, podcast, episode, job, Qwen voice, and Kokoro blend manifests are
recognized without importing Narrator modules or touching their files. Qwen reference voices,
Kokoro blends, and CustomVoice presets are adopted as Voice Profiles with stable identifiers.
Their assets remain externally linked and are never deleted by Studio.

Existing data is never modified in place:

- SPLICR jobs, chunks, profiles, resources, errors, checkpoints, and artifacts remain resumable.
- Narrator settings, voices, manifests, project history, and generated media remain readable.
- Imported records receive new Studio identifiers and keep legacy identifiers as metadata.

## Frontend direction

Narrator's workspace-oriented React layout is now the Studio frontend at `/studio/`. Narrate covers
document import/paste, provider/model/voice and
delivery controls, numeric-citation cleanup, chunk preflight, job creation, live character/chunk
progress, pause/resume/cancel, recent jobs, playback, and WAV download. Pronunciation searches the
Kokoro/Misaki dictionary inside Kokoro's isolated environment, previews ordinary-word respellings,
and manages overrides alongside provider-neutral substitutions. New Kokoro jobs freeze an exact
dictionary snapshot in their persisted variables, so an edit cannot change a resumed book midway.
Voice Studio persists cloned/designed reference identities separately from reproducible engine
presets, plays registered references, and safely distinguishes Studio-managed files from imported
external assets. Qwen VoiceDesign runs as a durable SQLite-backed job through its configured
isolated Python environment, never loads model code in FastAPI, atomically writes one canonical
reference WAV plus its exact transcript, and materializes an idempotent profile for each normalized
description/take identity. Queued or running jobs can be cancelled, interrupted running work is
requeued after restart, a persisted cancel request is honored after restart, completed atomic
worker output is finalized without regenerating audio, and failed/cancelled jobs can be retried.
Voice Studio exposes Designed voice and Generate another take while keeping profile take identity
separate from per-render seed. Workspace navigation keeps mounted form state intact. Audition will
arrive with its isolated engine adapter. Dialogue, timeline, audiogram,
publishing, component management, and conversion remain explicit migration slots.

The React shell now owns the essential SPLICR management workflows as well. Profiles save and load
the full source/delivery state plus an optional resumable take. The connection editor creates,
revises, and soft-deletes versioned API resources; it exposes arbitrary nested request JSON,
variable definitions, capabilities, limits, pacing, retry policy, response extraction, and a
write-only API key whose temporary clear-text view hides itself. The global error center polls the
durable redacted event store, shows unread badges and unobtrusive toasts, and inspects complete
request/response/exception/context records. React-side 5xx and network failures are reported to the
same store without copying request bodies that may contain credentials.

The established SPLICR UI remains at `/` as a transition surface while the remaining Narrator
workspaces are migrated. Vite source lives in `studio-web/`; hashed production assets are packaged
under `src/splicr/static/studio/` so Python/Docker runtime images do not need Node.js.

The Library workspace now reads the additive Studio tables through `/v1/studio/projects`. It can
search source names/previews, distinguish imported origins and statuses, display plan/take counts,
and reopen persisted source text in the still-mounted Narrate workspace. Narrator library entries
whose documents remain external are shown but deliberately cannot pretend their source was copied;
the UI points back to the compatibility migration boundary instead. New jobs appear without a
manual `migrate-studio` pass and retain the imported document title or filename when available.

## Migration sequence

1. Preserve Narrator source and establish both baselines.
2. Introduce shared domain types and the engine-session contract.
3. Wrap existing remote providers and route one SPLICR take through the session boundary.
4. Add local subprocess supervision and local HTTP classification; adapt Kokoro end-to-end.
5. Add project/render-plan/take/artifact persistence and compatibility importers.
6. Adopt the React shell and migrate SPLICR workspaces without removing the old UI prematurely.
7. Port Narrator's remaining voice, dialogue, media, library, and publishing workspaces.
8. Package a dependable local application, then replace the hosted app with the public download
   and documentation site.
