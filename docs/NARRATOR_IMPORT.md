# Narrator preservation snapshot

Narrator is being merged into SPLICR as the foundation of a unified, local-first SPLICR Studio.
The checked-in `legacy/narrator` directory is an immutable migration reference: it preserves the
application source, React source, tests, launchers, and project documentation before shared domain
models and runtime boundaries are introduced.

## Snapshot provenance

- Source at import time: `C:\Users\Ember\_DEV\Applications\_splicrTwo\Narrator`
- Imported: 2026-09-28
- Source repository status: the source directory was not inside a Git worktree
- Import command:

  ```powershell
  .\scripts\import_narrator_snapshot.ps1 `
    -Source "C:\Users\Ember\_DEV\Applications\_splicrTwo\Narrator"
  ```

The import script refuses to overwrite an existing snapshot. That makes accidental refreshes or
loss of migration evidence visible instead of silently replacing files.

## Deliberate exclusions

The snapshot excludes data that is generated, private, machine-specific, or too large to serve as
source code:

- `kokoro-env`, `qwen-env`, `.venv`, and other interpreter environments
- `narrator_data` and `narrator_output`
- downloaded model weights, caches, generated audio, and user-specific settings
- Python and test caches
- `web/node_modules` and frontend build output
- `narrator/webui`, which is generated from `web`

No API keys, credentials, voices, user projects, generated media, or model files are intentionally
included.

## Source-of-truth rules

1. Do not refactor the snapshot in place. Port behavior into the live SPLICR packages and retain
   the snapshot until compatibility tests cover that behavior.
2. Treat `HANDOVER.md` as the most current historical description. `CATALOGUE.md` predates later
   development and is supporting context only.
3. Treat `web` as the frontend source of truth. Do not restore or edit the generated `webui` copy.
4. Preserve compatibility with existing Narrator manifests, settings, and voices through explicit
   adapters or migrations rather than by binding new code directly to the legacy directory.

## Baseline verification

SPLICR remains independently testable while Narrator is migrated:

```powershell
uv run ruff check .
uv run pytest
```

Narrator's legacy Python baseline requires Python 3.10-3.12 and should be run from the snapshot
without using the copied machine-specific engine environments:

```powershell
Set-Location legacy\narrator
py -3.12 .\tests\run_all.py --quick
```

The 2026-09-28 preservation run established the following baseline before any integration edits:

- `test_audio8.py`, `test_build_video.py`, `test_chunkmap.py`,
  `test_dialogue_refine.py`, and `test_estimate.py` passed.
- media and web tests that import Pillow or FastAPI failed because those packages were not present
  in Narrator's Kokoro environment.
- several older tests failed because they still import removed symbols such as `_lay_out`,
  `measure_loudness`, `chunk_text_with_kinds`, and `flat_segments`.
- the legacy GUI smoke stage is interactive and did not complete in an unattended run.

These are imported baseline conditions, not regressions introduced by SPLICR. New integration tests
should target the live packages; the legacy harness should only be repaired when the corresponding
behavior is migrated or deliberately retained.

The React source can be checked independently from `legacy/narrator/web` with `npm ci` followed by
its package-defined test and build commands. Dependency directories and build artifacts must remain
untracked.

## First integration boundary

The first live implementation phase will introduce a provider-neutral engine-session contract and
the shared hierarchy `Project -> Render Plan -> Take -> Artifact`. Existing SPLICR remote providers
and Narrator local engines will adapt to that contract; neither implementation will become the
special case around which the shared orchestration layer is designed.
