# SPLICR Studio — post-merge expansion checklist

Status: active living backlog, started 2026-10-10.

## Goal

Expand the merged local-first Studio beyond Narrator parity, recovering unfinished ideas from
`legacy/narrator/HANDOVER.md` without carrying forward stale implementation gaps. Deliver one
coherent, verified feature at a time, preserving isolated engine environments, pluggable providers,
immutable render settings, checkpoint recovery, and a calm default UI with progressive disclosure.

Parity and release acceptance remain tracked in [narrator-parity-roadmap.md](narrator-parity-roadmap.md)
and [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md). This backlog does not waive the human Edge splice
listening check or clean-machine fresh-install/upgrade checks. No new authentication work is planned.

## Branch policy

- `classic`: preserved pre-merger SPLICR at `f0f6570f945dc58dba0deeee48756a7e6add26c2`.
  Published to `origin/classic` on 2026-10-10. Treat it as an archival baseline, not a second
  independently evolving product. Security fixes can be explicitly backported when needed.
- `main`: eventual stable merged application. Leave its current classic baseline untouched until
  the merged release is ready; work stays on `codex/narrator-integration` meanwhile.
- `codex/narrator-integration`: active merger/expansion work and CI, then promote to `main` through
  a reviewed integration. Future focused feature branches may use `codex/<feature>`.
- Before promoting, reconcile the existing `main`-triggered production deployment with the agreed
  local-first download/demo website direction. Do not accidentally deploy an unfinished Studio or
  alter the shared portfolio server just by renaming a branch.

## Workflow

- `[x]` requires implementation and named verification. Untested implementation stays `[ ]`.
- Keep acceptance evidence with each item; separate fake-provider/browser coverage from live model
  quality, hardware performance, and release evidence.
- Keep backlog ideas distinct from commitments. Evaluate prerequisites and user value before
  opening a large subsystem. Do not interpret “deferred items” as permission to download every model,
  spend API quota, publish packages, or change unrelated hosted apps.
- Preserve completed takes; editing creates derived artifacts and reproducible edit plans.
- Update this document with the implementation commit, including new discoveries and rejected ideas.

## 1. Direct audiogram composition — current delivery

- [x] Drag the polar center or rotation pivot directly in the preview; choose the active handle so
  overlapping center/pivot positions remain selectable.
- [x] Move linear layouts through the same center handle without shrinking their effective size.
- [x] Add keyboard arrows (1%) and Shift+arrows (5%), focus indication, and readable control labels.
- [x] Clamp movement, account for scaled/portrait canvases and pixel-space rotation, capture pointer
  movement outside the handle, and release on pointer cancellation.
- [x] Refuse direct movement when it would overwrite relevant position/size/rotation formulas;
  unrelated opacity expressions do not block positioning.
- [x] Ignore obsolete estimate responses while a newer edit is pending.
- [x] Verify live canvas geometry, generated-job settings, and a real PNG-sequence export from
  dragged coordinates. Full browser regression passed, followed by a focused final-geometry rerun;
  see the verification record. Broader Python regression is separately disk-space-blocked.

## 2. Frequency-selective visualization and gradients

Recovered from HANDOVER.md, “Audiogram: layout controls + transparent overlay,” 2026-09-02.

- [ ] Add a validated frequency-window setting (Hz) to the persisted audiogram specification.
- [ ] Apply it in the real analysis/render path, including audio-reactive expression context; clarify
  whether bass/mid/treble variables remain full-spectrum or window-relative.
- [ ] Add per-band gradient endpoints/direction, preserving current solid-color defaults and alpha.
- [ ] Keep preview, motion proof, and final output consistent; reject unsupported fast paths instead
  of silently ignoring requested effects.
- [ ] Test known low/high tones, silence, Nyquist bounds, gradients, serialization of old specs,
  portrait/polar output, and a real FFmpeg export. Add a browser journey for the controls.

## 3. Non-destructive sentence arrangement

Recovered from HANDOVER.md section 5.A. Existing sentence regeneration is not sentence arrangement.

- [ ] Design a versioned edit-decision list with stable source sentence identities.
- [ ] Add delete/restore, reorder, undo/redo, and a keyboard-accessible action menu. Hover-only actions
  are optional polish, never the only way to operate the editor.
- [ ] Rebuild audio and remap sentence/word timing, subtitles, chapters, and intro offsets together.
- [ ] Preserve source checkpoints and attach provenance to derived takes; persist edits across restart.
- [ ] Verify deletion of first/middle/last/all sentences, ordering, zero-length/gap boundaries, undo,
  cancelled assembly, restart, and exact audio/timestamp ordering through real media tests.

## 4. Per-sentence voice and engine assignment

- [ ] Extend the sentence edit plan to freeze voice profile, engine/resource revision, instructions,
  pronunciation snapshot, and supported generation parameters per replacement sentence.
- [ ] Show compatible voices and providers, including saved clones; retain isolated engine runtimes.
- [ ] Schedule requests through each provider's quota/pacing policy and normalize to canonical PCM.
- [ ] Preserve original takes and resumes; do not mix newly edited settings into completed chunks.
- [ ] Test heterogeneous providers with faithful fakes, rate-limit recovery, migration, deterministic
  ordering, and an explicitly approved live multi-voice listening sample.

## 5. Finishing loudness — refine the existing feature

The handover's “no normalization” limitation is already superseded: `FinishingSpec.normalize_loudness`
applies FFmpeg `loudnorm=I=-16:TP=-1.5:LRA=11` separately before joining. Command generation,
serialization, real joining, and derived timing offsets are covered by `tests/test_finishing.py`.
That is not the same promise as matching an intro to an unchanged narration loudness.

- [ ] Add real measured-loudness coverage of the existing normalization option (not only filter text).
- [ ] Decide whether to expose a separate “match assets to narration” mode using measured narration
  loudness, keeping speech gain unchanged and limiting unsafe asset gain.
- [ ] If implemented, record analysis/gain/target in provenance, handle silence/very short assets, and
  test clipping, duration, crossfade, source immutability, and restart. Keep existing default behavior.

## 6. Request-level TTS automation — design before implementation

Recovered from HANDOVER.md, “Expressions,” 2026-09-04. TTS parameters vary per request, not per frame.

- [ ] Define deterministic inputs such as chunk index/count or source progress (not unknown future
  audio duration); specify whether each provider supports the requested field.
- [ ] Preview the exact value per chunk and validate/clamp against the provider control schema.
- [ ] Freeze resolved values in the render plan so resumes and profiles are reproducible.
- [ ] Use the existing safe expression evaluator; no arbitrary Python/JavaScript evaluation.
- [ ] Test unsupported parameters, unsafe expressions, chunk-plan changes, retry/resume consistency,
  old profiles, and bounds before adding any live-provider acceptance.

## 7. Investigate small-paragraph prosody

HANDOVER.md, “Token-aware chunking + Qwen consistency, round 2,” flags short Kokoro paragraph calls.
Studio's `SemanticChunker` already packs units across paragraphs; explicit user heading/newline split
modes intentionally create boundaries. Do not remove those boundaries to solve a historical bug.

- [ ] Add a regression demonstrating default semantic packing of headings/list fragments within
  engine limits and explicit split modes retaining the user's requested boundaries.
- [ ] Inspect the current worker's internal sentence/paragraph calls before deciding a bug remains.
- [ ] Only implement further batching if evidence shows it is needed; compare real Kokoro narration
  around headings/lists and preserve word timing/pronunciation behavior.

## 8. Parked experiments and public distribution

- [ ] Per-word audio surgery stays experimental, not a scheduled deliverable. Whole-sentence
  regeneration with corrected pronunciation is the preferred workflow. Require a convincing real
  splice listening comparison before changing that decision (HANDOVER.md section 5.A).
- [ ] Audio8-specific expansion remains parked pending user priority; existing integration is retained.
  The old ambiguous “version 2.0 milestone” request is superseded by Studio's release process.
- [ ] Build the public information/demo/download page after local release hardening; no authcore is
  needed for that static public surface. Explain optional engines, model sizes/licenses, offline vs.
  online providers (including Edge), and hardware needs; provide verified downloads/source notices.
- [ ] Retire/migrate hosted synthesis deployment deliberately, preserving existing server projects,
  logs, user data, and a rollback path. Do not expose local filesystem/model management publicly.

## Guided local-engine installation — user priority 2026-10-19

- [x] Implement explicit Windows-x64 managed setup in Components alongside existing interpreter
  configuration: private Python bootstrap, isolated CPU/NVIDIA recipes, disk preflight, consent,
  live stages/download bytes, bounded redacted logs, cancel/retry, restart recovery and automatic
  next-restart configuration. Focused mocked backend and browser wizard tests pass locally.
- [x] Verify pinned bootstrap rejection, no arbitrary ZIP extraction/commands, loopback/same-origin
  access, environment-variable locks, and preservation of externally configured environments.
- [x] Complete actual hosted Windows setup/import acceptance for all five CPU recipes using the
  manual workflow. Run `39272300592` passed on source `8005e7e` / identical private snapshot
  `9105a16` on 2026-10-19: Edge, Kokoro (including private eSpeak phonemization), Qwen3, Audio8
  (including AutoModel/AutoProcessor and Torchaudio), and faster-whisper. No local Sandbox/VM/
  container or local heavyweight engine install was used. This proves package provisioning/imports,
  not TTS model first-use, audible quality, or NVIDIA-driver compatibility.
- [ ] Verify newly managed model first-use downloads, real narration/transcription, and NVIDIA
  acceleration on representative hardware. Existing externally managed-engine evidence is not this
  new installer path's evidence. A fresh packaged installer is still needed after validation.
- [ ] Follow-up polish: managed-cache storage relocation/usage/explicit removal, optional guided model
  prefetch with model-specific terms and accurate sizes, one-click safe idle restart, and a reviewed
  complete transitive wheel lock. Do not silently install GPU drivers or prefetch all models.

## Historical gaps already closed or replaced

Do not reopen these from early “not yet” annotations later contradicted by the handover itself:

| Historical note | Present disposition |
| --- | --- |
| Timeline loading, word inspection, saved clone selection | Implemented in later Narrator work and covered/replaced in Studio parity inventory |
| Web Voice Studio, Timeline, Audiogram, engine-folder selection | Later handover entries close these; Studio parity inventory is authoritative |
| RSS/transcripts/chapters, queue, library, isolated engines | Existing merged workspaces; maintain regression coverage, not new backlog |
| Remaining legacy Tk/shadcn CSS migration | Superseded by Studio UI; do not modernize unused legacy UI in parallel |
| Audio8 version milestone ambiguity | Studio packaging/release version policy replaces the old ad-hoc request |

## Verification record

- 2026-10-19: guided managed-engine setup passes the complete clean-configuration Python suite
  (613 passed, seven deliberate live skips), all 13 frontend unit tests, all eight Chromium journeys,
  Vite build and Ruff. The new browser journey covers consent gating, live setup status, reload,
  cancellation and explicit retry; the modal screenshot was visually reviewed. The initial run
  with developer `.env` enabled and concurrent browser work had four failures, all cleared by
  isolated reruns and the clean full rerun. Hosted installation was verified separately below.
- 2026-10-19: [managed setup run `39272300592`](https://github.com/seabAu/Splicr-CI/actions/runs/39272300592)
  passed all five real Windows CPU recipes in 3m21s. Fresh-runner testing found and fixed the
  bootstrap/Python catalog pairing, PyTorch-index dependency resolution, missing private pip for
  first-use language packages, and the Windows USERNAME requirement. Runtime bootstrap is now uv
  `0.12.5`, SHA-256 `4c4d49d8738847d9b71ba319e49a5688c93eac0fe6204b1df24e98528dddf39a`,
  with private Python `3.12.14`. Focused setup safety tests pass after each correction (17 tests).

- 2026-10-10: five new positioning unit tests plus eight existing frontend tests pass (13 total);
  Vite production build and Ruff pass. All seven Chromium journeys pass; the final focused Audiogram
  rerun additionally verifies updated live canvas geometry, drag, keyboard movement, formula
  protection, persisted render specification, and a real one-second PNG-sequence export. Screenshot
  review caught and fixed an existing overly broad SVG selector affecting the preview badge icon.
- 2026-10-10: all 50 affected Python audiogram/expression/finishing tests pass. The full Python suite
  exhausted drive C: during execution (`ENOSPC`) and is **not** a passing regression result. Removed
  only this turn's `pytest-234`/`pytest-235` temporary outputs (about 3.85 GB); preserved application
  data, installed engines/models, and prior release evidence. Full-suite rerun needs additional disk
  headroom. No model/provider quota was consumed by this work.
- 2026-10-12: C: has sufficient headroom again. The complete Python suite now passes on `9359905`
  (572 passed, seven intentional live skips), superseding the disk-space-blocked attempt above.
  All 13 frontend unit tests, all seven Chromium journeys, and Ruff also pass.
