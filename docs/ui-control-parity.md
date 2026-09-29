# UI control parity

Narrator's Tk interface and unfinished React port contain more controls than can be safely placed on
one screen. SPLICR Studio therefore treats parity as **capability parity**, not pixel-for-pixel widget
parity. Common controls stay in Narrate; engine-specific and rarely changed controls belong behind
progressive disclosure; output transformations live in Timeline, Audiogram, Convert, and Publish.

The machine-readable inventory is [`ui-control-parity.json`](ui-control-parity.json). A Python test
parses Narrator's preserved `render_config.FIELDS` declaration and fails if a legacy field is added,
removed, duplicated, or left without a documented destination. `gap` entries are explicit product
work, not silently forgotten controls.

Current conclusion:

- Core engine, voice, delivery, profile, conversion, video, publishing, and project controls are
  represented in Studio.
- The largest remaining control gap is the advanced polar/formula audiogram. Managed still-image
  backgrounds, shared preview/render layout, and alpha WebM/ProRes/PNG output are covered. Durable
  transcription, multi-document queues, intro/outro assets, safely clamped
  crossfades, derived finished masters, shifted Timeline/chapters/captions, subtitle timelines,
  complete/partial SRT and WebVTT exports, and optional Audiogram burn-in are now covered.
- Narrate now keeps everyday boundaries compact while its advanced disclosure covers approximate
  parts, character targets, and provider-estimated token targets. Preflight exposes exact spans,
  metrics, headroom, warnings, and the durable plan used by resume.
- The merged UI should not recreate the original wall of widgets. Use a compact default workflow,
  an **Advanced engine controls** drawer generated from typed provider metadata, and dedicated
  post-production workspaces.

The implementation order, acceptance criteria, and living task checklist are maintained in
[`narrator-parity-roadmap.md`](narrator-parity-roadmap.md).

## Acceptance layers

1. `uv run pytest -q` verifies domain, provider, persistence, API, restart, and media behavior.
2. `npm --prefix studio-web test` verifies fast frontend utilities.
3. `npm --prefix studio-web run test:e2e` starts the real FastAPI app with a deterministic fake TTS
   provider and walks every rendered workspace in Chromium. It also performs a complete
   plan-render-playback-Library-Timeline journey without API quota.
4. Tests marked `live_provider`, `live_engine`, or `release_acceptance` are opt-in gates for real
   credentials/models, long soaks, and clean-machine packaging.

To spend quota on a deliberately small provider contract check, set `SPLICR_LIVE_PROVIDER` to
`gemini`, `deepgram`, or `inworld`, provide that provider's normal API-key environment variable,
and run `uv run pytest -m live_provider tests/test_live_provider_acceptance.py`. The test verifies
that the selected adapter can authenticate, synthesize, and normalize its result to SPLICR's
canonical PCM format. It is skipped unless explicitly enabled.

Playwright retains a trace, screenshot, and video for failures. Use
`npm --prefix studio-web run test:e2e:ui` while developing a workflow interactively.
