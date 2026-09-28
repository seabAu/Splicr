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
- An **Artifact** is a durable output with identity, type, path, size, and optional checksum.

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
- `local_subprocess`: isolated Python environments such as Kokoro, Qwen3-TTS, and Audio8
- `local_http`: a separately managed local model server

Remote SPLICR providers are first wrapped with `ProviderEngineAdapter`; this preserves current
behavior while orchestration migrates. Local adapters may keep a model or subprocess alive for the
entire take, then release it when the session closes. Every adapter must still return canonical
mono PCM16 at 24 kHz before shared checkpointing and assembly.

## Persistence and compatibility

The SPLICR SQLite store remains the authoritative durable execution store during migration. New
tables will be additive and versioned. Compatibility importers must be idempotent and retain links
back to their source identifiers.

Existing data is never modified in place:

- SPLICR jobs, chunks, profiles, resources, errors, checkpoints, and artifacts remain resumable.
- Narrator settings, voices, manifests, project history, and generated media remain readable.
- Imported records receive new Studio identifiers and keep legacy identifiers as metadata.

## Frontend direction

Narrator's React application becomes the Studio frontend. Features move workspace by workspace;
the current SPLICR UI remains available until the React replacement reaches functional parity for
document import, chunk preview, progress, error diagnostics, resume/cancel, playback, and export.

## Migration sequence

1. Preserve Narrator source and establish both baselines.
2. Introduce shared domain types and the engine-session contract.
3. Wrap existing remote providers and route one SPLICR take through the session boundary.
4. Add local subprocess supervision and adapt one lightweight local engine end-to-end.
5. Add project/render-plan/take/artifact persistence and compatibility importers.
6. Adopt the React shell and migrate SPLICR workspaces without removing the old UI prematurely.
7. Port Narrator's remaining voice, dialogue, media, library, and publishing workspaces.
8. Package a dependable local application, then replace the hosted app with the public download
   and documentation site.
