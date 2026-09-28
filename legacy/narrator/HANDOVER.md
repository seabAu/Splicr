# Narrator — handover and context corpus

Read this first when picking the project up in a new conversation. It is
the condensed history of what was built, why, what is verified, and what
comes next. `README.md` is the user-facing manual; this is for whoever is
doing the work.

## 1. What this is, and the constraints that shaped it

Routh is turning a dissertation on digital twins (and other long, nuanced
academic documents) into natural-sounding narration for YouTube and podcast
distribution — accessibility first, not monetisation, AI-generated audio
disclosed up front. Constraints, in priority order:

1. **Free and local.** No paid TTS APIs. Recently laid off; no spare money.
   Engines: **Kokoro** (offline, best all-round), **Qwen3-TTS** (offline,
   voices designed from a written description), **edge-tts** (online,
   zero-setup fallback).
2. **Windows, no admin rights, Python venvs.** Kokoro and qwen-tts pin
   conflicting `transformers` versions, so each engine lives in its own venv
   (`kokoro-env`, `qwen-env`) and the app runs them as subprocesses.
3. **Long, nuanced documents.** Citations, reference lists, tables, markdown
   syntax all have to be stripped or spoken gracefully. `.docx` needs pandoc.
4. **Narrative momentum matters.** One mispronounced word "skips the record"
   for the listener. Pronunciation control and cheap re-recording of small
   segments are the highest-value features after basic quality.
5. **Plain language.** Routh dislikes invented jargon and wants honest
   pushback, not validation. Comments in the code explain *why*.

## 2. Architecture (v2.0 package)

```
Narrator.py / Start Narrator.bat   launchers (add folder to sys.path, run package)
narrator/__main__.py               dispatch: GUI | --clean doc | --worker job.json
narrator/config.py                 paths, settings, voice lists, engine/venv detection
narrator/documents.py              read + clean documents (was prep_for_tts.py)
narrator/pronunciation.py          custom lexicon, respelling -> misaki IPA, scanner
narrator/subtitles.py              SRT build/merge
narrator/audio.py                  every ffmpeg operation: join, convert, WAV, video
narrator/engines.py                the three engines + cross-venv worker bridge
narrator/pipeline.py               ENGINES registry; regenerate + resplice one chunk
narrator/ui.py                     the whole tkinter window and every dialog
narrator/setup_engines.py          builds venvs with pip (torch from cu128 index)
narrator/wizard.py                 first-launch setup wizard (tkinter, not compiled)
narrator_data/                     settings, pronunciations, voices/, cache/
narrator_output/                   all rendered output (flat, or per-document subfolders)
```

Two rules that must not be broken:

- **Only `ui.py` imports tkinter.** The worker runs inside kokoro-env /
  qwen-env, which may have no Tk at all.
- **The worker is invoked as a module** (`python -m narrator --worker
  job.json` with `PYTHONPATH` pointed at the project), never by file path,
  and the package is *not* installed into the engine venvs.

Render flow: `ui.start()` snapshots every widget into a plain `cfg` dict on
the main thread → `work()` on a thread → `render()` → `ENGINES[...]["run"]`
→ `run_kokoro / run_qwen / run_edge` → per-chunk audio cached in
`narrator_data/cache/<fingerprint>/NNNN.wav` (resumable) → `_join_chunk_wavs`
/ `join_audio` → `finalize_render` (format, quality, subtitles, kept chunks,
editing WAV, video) → `state["last_render"]` kept for **"Fix a chunk..."**
(`pipeline.resplice_chunk`: regenerate one chunk, rebuild master, re-finalize
in place).

## 3. Decisions and bugs already dealt with (don't re-litigate)

- **docx was read as raw zip bytes** (encoding fallbacks with
  `errors="replace"` never fail). Fixed by routing `.docx/.odt/.html/.tex/.epub`
  and `.md` through the pandoc-based cleaning pipeline, cached by file mtime.
- **`sys.exit()` inside library code killed the GUI silently** —
  `SystemExit` is not an `Exception`, so every `except Exception` guard let
  it through. All library-level exits became real exceptions. Rule: never
  `sys.exit` below `main()`.
- **`subprocess.run(["which", ...])`** doesn't exist on Windows → use
  `shutil.which`.
- **Pronunciation (Kokoro/misaki):** pasting Wiktionary/CMU IPA does not
  work — misaki has its own symbol set (ɹ not r, capital-letter vowels,
  mandatory stress marks). The dialog takes a *respelling* of real dictionary
  words instead (`an on nim my *nation` for "anonymization"; `*` marks
  stress; default stress is the first piece). Fragments ("non", "ni",
  "-ization") don't resolve — only genuine standalone words do. `word_check.py`
  (if present) tests candidate pieces against the same lookup the app uses.
  Kokoro is the only engine with a lexicon hook; edge-tts and Qwen3 have none
  — for those, the only lever is rewriting the text (phonetic spelling in the
  source, or a per-word substitution map, see roadmap).
- **Output layout:** everything under `narrator_output/`; flat by default,
  optional per-document subfolders; samples always in `samples/`; nothing
  ever written next to the source document. Formats: mp3/m4a/wav/etc. with
  sample rate, bit depth, and a 0–100% quality slider; optional uncompressed
  editing WAV at 48 kHz; optional still-image + waveform + burned-caption
  video via ffmpeg.
- **Installer:** deliberately *not* a compiled `.exe` (PyInstaller doesn't
  cross-compile; nothing built here could be tested on Windows). What exists
  is a tkinter wizard + `setup_engines.py` that fetch engines from PyPI and let
  the engines fetch weights from Hugging Face — the real "@latest" channels,
  with pip's own "Downloading X (750 MB)" lines surfaced as progress.

### Fixed in this hand-off (2026-08-26)

- **Qwen3 voice changed every chunk.** `generate_voice_design()` samples a
  new voice per call; it was called once per chunk. Now design-then-clone
  (the workflow the Qwen3-TTS README recommends): VoiceDesign reads a
  reference passage once → saved to `narrator_data/voices/<slug>-<hash>/`
  → Base model builds one clone prompt → every chunk uses
  `generate_voice_clone(voice_clone_prompt=...)` with that same object.
  Verified against qwen-tts 0.1.1 source (model-type checks, kwargs, prompt
  reuse) and exercised end-to-end with a fake `qwen_tts` mirroring that API.
  **Not yet run on a real GPU** — no NVIDIA hardware was available.
  Per-chunk seeds are deterministic; chunk cap dropped 2000 → 1500 chars and
  `max_new_tokens` is sized to the chunk so long slow chunks aren't cut off.
  Cache key changed (`clone:...`) so old inconsistent chunks are never reused.
- **"Take"** control (Qwen3 only): same description + take = same saved
  voice; a new take designs a fresh one. `settings["qwen_take"]`.
- **Wizard never appeared on a fresh machine.** `win.transient(root)` on a
  Toplevel whose master is withdrawn makes the Toplevel inherit "withdrawn":
  never drawn, but holding a grab and blocking in `wait_window()`. Reproduced
  under Xvfb (state `withdrawn`, `winfo_viewable()==0`); fixed by dropping
  `transient`, deiconify/lift/focus, brief `-topmost`. Also: setup exceptions
  no longer strand the progress page; edge-tts is offered by the wizard
  (installs into the app's Python, pre-ticked when nothing works); the
  "no engine installed" dead end now re-offers the wizard.
- **Environments folder** (`settings["env_root"]`, in "Set up engines..."):
  a fresh copy of the app can reuse venvs built beside an older copy. Model
  weights are already shared via the Hugging Face cache. Verified with a
  worker run through a venv in another folder.
- **edge-tts** now runs as `python -m edge_tts` when importable, since
  `edge-tts.exe` embeds the absolute path of the venv it was installed in and
  breaks if that folder is moved.
- `Start Narrator.bat` falls back to `py -3` when `python` isn't on PATH.

### Added 2026-08-27: sentence-level fixes (roadmap A, steps 1 and 3)

- `narrator/segments.py` (new): every rendered chunk now gets a
  `NNNN.segments.json` sidecar listing each sentence's text and start/end
  inside that chunk file. Kokoro gives one piece per sentence for free;
  Qwen3 now renders each chunk as sentence groups (`QWEN_GROUP_CHARS`=250,
  0.25 s pause between groups) against the one clone prompt, so the spans
  are exact; edge-tts always writes word subtitles and sentences are
  derived from them (falls back to one span per chunk when edge's word
  count differs from ours). Engine results carry `"segments"`; older cached
  chunks without a sidecar get one whole-chunk span.
- `pipeline.resplice_segment(lr, chunk, sentence, text, log, retry)`:
  renders the sentence as a one-chunk job through the engine's normal entry
  (same voice/take/speed/pronunciations), trims its silence, level-matches
  it to what it replaces (capped +-6 dB), 20 ms crossfades, writes the
  chunk as `NNNN.fixN.wav` beside the original (cache untouched), shifts
  later spans, rebuilds the master, re-finalises in place. WAV chunks only
  (Kokoro/Qwen3); edge falls back to chunk-level.
- Take manifest `<stem>.manifest.json` written beside every real output and
  after every fix: chunks, sentence spans with absolute times, engine,
  voice, take, cfg. `segments.load_manifest()` rebuilds `last_render` so a
  take can be fixed after a restart (not yet wired into the UI: next step
  is a "Open a take..." button that calls it).
- "Fix a chunk" dialog now lists the sentences of the selected chunk with
  their start times: Play sentence (exports the span to a temp WAV and
  opens it), Regenerate this sentence, Try again (same text, new roll).
- Verified with fake engines: spans match audio, audio outside the span is
  byte-identical after a splice, later spans shift correctly, fix2 follows
  fix1, manifest round-trips. Not yet heard on real audio: judge the seams
  by ear on the first real fix; if a click is audible, raise `fade_ms`.
- Next for A: the timeline canvas (step 2), reading the manifest; then
  word-level (step 4).

## 4. Verified vs. unverified

Verified here (Linux sandbox, Xvfb, fake engines): imports, document
cleaning, cache keys, wizard visibility, main window with Qwen3 selected,
setup dialog, env_root discovery, worker round-trip carrying `take` and
`clone_repo`, voice folder creation and reuse.

Not verifiable here: anything needing a GPU or Microsoft's edge-tts servers.
Every Qwen3 call is checked against the installed package source, not
executed. First real run on Routh's machine should watch for: VRAM headroom
loading Base after VoiceDesign (they are freed in sequence), reference clip
quality (listen to `narrator_data/voices/.../reference.wav`), and whether
ICL cloning carries the *pace* as well as the timbre.

## 5. Roadmap, in the order agreed 2026-08-27

Routh's cadence: at least one full episode (audio + video) a week, a few
hours available per week. That means reliability matters more than breadth
— a broken build the week an episode is due costs more than a missing
feature. Build and verify one item at a time; don't start the next until
the current one is tested the way section 6 describes.

### A. Segment editor — steps 1 & 3 DONE, 2 & 4 open

Manifest (`segments.py`, `<take>.manifest.json`) and sentence-level
regenerate + splice (`pipeline.resplice_segment`) are built, tested, and in
the "Fix a chunk or sentence..." dialog. Open:

2. **Timeline UI — DONE 2026-09-04.** `open_timeline_editor()`, reached
   from the **Timeline...** button or **Tools -> Open a take...**.
   - `audio.envelope(path, buckets)` decodes through **ffmpeg** to raw
     mono PCM rather than reading directly: the finished output is
     usually mp3/m4a, which soundfile cannot open at all, and the
     timeline has to draw what the person actually produced. Peak per
     bucket, normalised to the file's own peak. Returns `[]` on an
     unreadable file rather than raising.
   - `audio.extract_span()` likewise goes through ffmpeg, so "play just
     this bit" works on compressed output.
   - The manifest's chunks are flattened into one time-ordered sentence
     list; the click-to-sentence lookup handles clicks landing in the gap
     BETWEEN chunks (takes the next sentence) and past the end (clamps).
   - Click places the playhead and selects that sentence; drag selects a
     range; the sentence list and edit box follow, and selecting in the
     list moves the timeline back. Re-record with edits / try again reuse
     `resplice_segment` unchanged.
   - The waveform is read on a background thread, so the window opens
     immediately and fills in.
   - **Open a take...** uses `segments.load_manifest()`, so a take from an
     earlier session is editable without the app having stayed open --
     verified end to end by reopening a manifest from disk.
   - Testing note that cost real time: `menu.invoke()` takes a REAL menu
     index. Building a label list with separators filtered out and then
     using `labels.index(...)` silently invokes the wrong entry, and since
     invoking a separator is a no-op it fails as "nothing happened"
     rather than as an error. Index by real position.
   - Not done: hover menus on list rows (the side buttons cover the same
     actions), deleting a sentence, and per-sentence voice switching.
4. **Word-level: inspection DONE 2026-09-04. Per-word audio surgery
   deliberately NOT built.**
   The original sketch was to replace one word's audio in place. That is
   the wrong shape, and would sound worse than what already exists:
   prosody is continuous across a phrase, so a word spliced in from a
   separate generation lands with the wrong pitch contour and timing at
   both boundaries. Re-rendering the whole sentence with the
   pronunciation corrected -- which `resplice_segment` already does --
   answers the same complaint better. Don't re-litigate this without
   listening to a per-word splice first.

   What was genuinely missing, and is now built, is the *inspection*
   half Routh asked for originally: for each word, see the pronunciation
   applied to it during narration, and edit it.
   - `pronunciation.words_in(text)` -- distinct words in order,
     case-insensitively deduped.
   - `pronunciation.phonemes_for_words(words, overrides)` -- a whole
     sentence in ONE pass, each word tagged `override` / `dictionary` /
     `guessed` / `unknown`. Batched on purpose: every call reaches the
     environment Kokoro lives in, and a per-word version would be a
     dozen subprocess round-trips to answer one question. A test asserts
     the batched result matches what per-word calls return.
   - Timeline side panel lists every word of the selected sentence with
     its phonemes and a source marker (`*` override, `~` guessed, `!`
     can't say). **Edit this word...** (and double-click) opens the
     pronunciation editor already focused on that word; fix it, then
     re-record the sentence from the same panel.
   - Non-Kokoro engines say so rather than showing an empty box --
     phoneme detail is Kokoro-only.
   - Testing note: `event_generate("<Double-Button-1>")` is rejected by
     Tk ("Double, Triple, or Quadruple modifier not allowed"), so a
     double-click binding cannot be driven from a test. The explicit
     button exists partly for that reason, and partly because
     double-click alone is undiscoverable.

### E. Publish, part 1: RSS feed + transcript export — DONE 2026-08-29

- **`narrator/publish.py`** (new module). The feed is never hand-edited or
  parsed back in — `narrator_data/narrator_episodes.json` is the source of
  truth (one record per episode: title, description, pub_date, audio
  relpath/bytes/mime type, duration, guid), `narrator_data/
  narrator_podcast.json` holds channel-level settings, and
  `build_feed_xml()` / `write_feed()` regenerate `narrator_output/
  podcast.xml` from both, fresh, every time. A malformed feed is always
  fixable by rebuilding, never by patching. Built with `ElementTree` +
  `register_namespace` for the itunes namespace — do NOT also hand-add an
  `xmlns:itunes` attribute on the root element, that produces a duplicate
  attribute (invalid XML); confirmed this exact failure mode by testing it
  before writing the real function. `episode_from_render()` takes a
  `state["last_render"]` dict directly (raises `ValueError`, doesn't
  publish, if the rendered file has since moved/gone); republishing the
  same output file (same guid = its relative path) updates that entry
  instead of duplicating it. Non-mp3/m4a episodes still get a correct
  mime type from `publish.py`; the "most directories won't take this
  format" warning is surfaced by the UI, not the module.
- **Preferences (Settings menu) gained a "Podcast" tab**, alongside the
  renamed-from-`open_engine_setup` `open_preferences_dialog`: title,
  author, email, description, website, hosting URL, artwork URL, category,
  language, explicit — every field true across all episodes, autosaving on
  edit (no Save button). `missing_channel_fields()` checks the ones Apple/
  Spotify actually require and is surfaced as a log note after publishing,
  never a block — seeing the draft feed is often how you notice what's
  missing.
- **Publish tab has real content now**: episode title (auto-suggested from
  the source filename) + notes, "Publish this take to the RSS feed"
  (enabled only once `state["last_render"]` points at a file that still
  exists), "Export transcript (.md)". Refreshes on `<<NotebookTabChanged>>`
  AND right after every render finishes (`root.after(0,
  refresh_publish_tab)` in `work()`'s `finally`) — the first cut only had
  the tab-changed hook, which meant staying on the Publish tab while
  clicking Generate never updated it; caught by a smoke test that (correctly) exercised that exact sequence.
- **Transcript export**: `documents.handle_headings()` gained a third mode
  — `keep="markup"` restores the original `#`-level as a real Markdown
  heading, instead of speaking it (`keep=True`) or dropping it
  (`keep=False`, still the narration default — unchanged). `export_transcript()`
  runs the *same* cleaning pipeline narration uses, two flags different
  (headings kept as markup, tables kept verbatim — see the 2026-08-29
  follow-up below) — a written companion of what's actually spoken, not a
  separate re-edit of the source.
- Verified: `build_feed_xml`'s output parses back cleanly with
  `ElementTree.parse` (namespace, escaping — including a literal `&` in a
  title — enclosure URL/type/length, `itunes:duration` formatted
  `HH:MM:SS`); episode dedup-by-guid and numbering; the missing-field
  check flags exactly the unset ones; `handle_headings`'s two *existing*
  modes are unchanged (regression-tested directly, since a naive first
  draft of the "markup" addition broke the drop-case by adding stray blank
  lines — caught before it shipped). Full path driven through the real
  window under a virtual display: fill Preferences > Podcast, render a
  `.md` document with headings through the stub Kokoro engine, publish it,
  parse the resulting `podcast.xml` back and check its contents, export
  the transcript and confirm the headings survived.

### F. Publish, part 2: chapters, from the document's own headings — DONE 2026-08-29

Built differently than originally sketched above (that draft assumed
character-offset threading through `expand_abbreviations`/`tidy`/
`chunk_text`, none of which preserve exact offsets -- `chunk_text`
reconstructs chunks by re-joining `split_sentences()`'s output, not by
slicing). What's actually there instead, in **`narrator/chapters.py`**
(new module):

- `documents.handle_headings()` takes an optional `headings_out` list. On
  every heading with body text after it, it appends `(title, level,
  hint)` where `hint` is up to 80 characters of that following text, run
  through `expand_abbreviations`/`tidy` *at collection time* so it already
  matches the form that text takes once those two steps run for real later
  -- no marker/sentinel threading needed, and it changes nothing about the
  returned text (confirmed: `clean_document(path)` and
  `clean_document(path, headings_out=[])` return byte-identical text).
  `clean_document()` just forwards the parameter.
- `chapters.compute_chapters(last_render)` re-runs that *exact* call
  against `last_render["source_path"]` (same defaults the real narration
  used, so the text is guaranteed identical to what was actually chunked),
  then for each heading's hint, searches `manifest["chunks"][i]["text"]`
  (from `segments.build_manifest`, not a fresh re-chunk) for that literal
  string. Found -> `_locate_in_chunk` walks that chunk's *own recorded
  segments* (not any assumption about how the engine split it) by
  cumulative text length to find which segment's `abs_start` covers the
  match offset. Not found anywhere -> that heading is silently dropped
  from the result, never guessed at. This works the same way regardless
  of engine, because it never assumes segment boundaries line up with our
  own `split_sentences` -- Kokoro's own internal splitting doesn't need to
  match ours for this to work, only that its segments' texts add up to
  roughly reconstruct the chunk, which is true by construction for all
  three engines.
- `format_youtube_chapters()`: forces the first entry to `0:00` (YouTube
  requires this) and notes when there are fewer than 3 total entries
  (YouTube's minimum for the chapter UI to appear at all) -- both are
  requirements that fail silently on YouTube's end if missed, so both are
  handled here rather than left to be discovered by trial and error.
- `embed_chapters()` dispatches on extension: m4a via ffmpeg (`-i
  chapters.ffmeta -map_metadata 1 -c copy` -- confirmed `-map_chapters 1`
  is NOT additionally needed, metadata mapping alone carries chapters);
  mp3 via `mutagen`'s ID3 `CHAP`/`CTOC` frames (new dependency, pure
  Python: `pip install mutagen`; the exact field names --
  `element_id`/`start_time`/`end_time`/`start_offset`/`end_offset`/
  `sub_frames` for CHAP, `element_id`/`flags`/`child_element_ids`/
  `sub_frames` for CTOC, `start_offset`/`end_offset` need the
  `0xffffffff` "use time, not byte offset" sentinel -- were read from the
  actual installed package, not assumed). Missing mutagen raises a plain
  "pip install mutagen" message rather than an ImportError traceback.
  Unsupported formats (wav, flac) raise a clear message rather than
  silently doing nothing; the YouTube text still works regardless of
  output format.
- Publish tab gained a **Chapters** section: a text box for the formatted
  YouTube list, "Generate chapter list", "Embed chapters into audio file".
- Verified: `headings_out` is a provably pure side channel (byte-identical
  text with/without it); a synthetic multi-heading document rendered
  through the stub Kokoro engine had all three headings correctly located,
  in time order, first one near the start; recomputing gives identical
  results; a missing source file or unmatchable hints degrade to an empty
  list rather than crashing or guessing. The mp3/m4a embedding was
  verified against *real* files -- built one, embedded chapters through
  this module's own functions, and confirmed with `ffprobe` (independent
  of both this code and of mutagen) that the titles and start/end times
  round-tripped correctly, including a title containing `&`. A first draft
  of `_locate_in_chunk`'s boundary check had a padding term that
  misclassified an offset landing exactly at a segment's start as
  belonging to the *previous* segment -- caught by a direct unit test
  before it ever reached the end-to-end path.
- Known limitation, by design, not an oversight: matching is
  nearest-segment, not exact-sample -- chapter timestamps land at the
  start of whichever segment contains the heading's first few words, not
  necessarily the exact instant the prior sentence's audio ends. Fine for
  a chapter marker; not worth the complexity exact-sample would need.
- The Publish tab's required height grew past the window's size again
  this session (same thing that happened with the redesign) -- geometry
  bumped to `860x1000` as an immediate fix. Properly addressed in the
  follow-up below.

### Cleanup pass 2026-08-29: scrollable tabs, real tables in transcripts

Two loose ends explicitly flagged above, closed before moving on to G:

- **Scrollable tab bodies.** `_scrollable_tab(notebook, title)` (in
  `ui.py`, right before the notebook is built) wraps each tab in a
  `Canvas` + `Scrollbar` and returns the padded inner frame -- used by
  every caller exactly like the plain `ttk.Frame(notebook, padding=10)`
  it replaces, so none of the ~50+ lines that build each tab's actual
  content needed to change. Mouse-wheel scrolling is bound only while the
  pointer is over that tab's own canvas (`<Enter>`/`<Leave>` toggle
  `bind_all`), so it doesn't leak across tabs; `<Button-4>`/`<Button-5>`
  are handled alongside `<MouseWheel>` since Linux delivers wheel events
  differently than Windows/Mac (this app's actual target). Window
  geometry brought back down to `860x780` now that height overflow is
  handled by scrolling instead of by the window growing -- confirmed the
  Publish tab's content genuinely exceeds its visible canvas (a real
  overflow, not a hypothetical one) and that scrolling it actually moves
  the view. One thing worth knowing if this ever needs touching again:
  `winfo_ismapped()` on a canvas-embedded window can report `True` even
  while its tab isn't the selected one -- a Tk quirk specific to
  `create_window` items, confirmed harmless (`winfo_viewable()`, the
  check that actually requires the whole ancestor chain to be mapped,
  correctly reports `False`/`True` exactly when it should) but worth not
  re-debugging from scratch next time it's confusing.
- **Real tables in the transcript.** `documents.handle_tables()` gained a
  `mode="keep"` branch: the original matched lines are appended verbatim
  instead of narrated or dropped. Since `load()` already runs anything
  that isn't already Markdown through pandoc before this ever sees it,
  "verbatim" is always valid Markdown table syntax regardless of the
  source format. `publish.export_transcript()` now passes `tables="keep"`
  alongside `keep_headings="markup"`; narration's own default
  (`tables="describe"`) is untouched -- confirmed with a direct
  regression check, not just by reasoning that a new `elif` branch
  shouldn't affect the existing ones.
- **Installer (C, below) stays deliberately parked.** Routh confirmed
  this is a personal project ("beholden to none but my own ambition"),
  which is the condition C's own writeup said to check before investing
  there. Noted here so it reads as a decision, not a thing forgotten.

### G. Library & project files — DONE 2026-08-29

Lives on the Document tab, as planned (the scrollable-tab fix from the
cleanup pass made the "or a fifth tab" alternative unnecessary).

- **`narrator/library.py`** (new module, pure data layer, no Tk):
  `narrator_data/narrator_projects.json`, one record per document --
  `path`, `label` (derived from the filename), `cfg` (the exact dict
  `render()` uses), `status`, `output`, `updated`. `touch(path, cfg=,
  status=, output=)` adds or updates an entry; a fresh `cfg` *replaces*
  the saved one (you want the latest settings back, not a merge), but
  `status` only ever moves forward along `not_started -> prepared ->
  rendered -> published` -- republishing a document after a small fix
  doesn't demote it from "published" back to "rendered" just because a
  render happened first in that same action. `all_projects()` returns
  most-recently-touched first. `relative_time()` formats the "updated"
  timestamp ("3 minutes ago", falling back to a plain date past a month).
- Wired to three real events, not a separate "save to library" step:
  picking a file (`not_started`), a "Clean text only" run completing
  (`prepared`), a real render completing (`rendered`, with the exact
  `finalize_cfg` used) and publishing an episode (`published`). All
  through the SAME `library.touch()` call, so the forward-only rule is
  the only place that logic exists.
- **Restoring a project's settings is the part with actual complexity.**
  `cfg["voice"]` is not what the voice combobox displays for the two
  built-in-preset engines (edge, Kokoro) -- it's the underlying `vid`;
  the combobox shows the friendly `desc`. Restoring has to look up which
  `(vid, desc)` pair in that engine's current voice list matches the
  saved `vid` and set the display text, not the id. For Qwen3
  (`editable`), the combobox var *is* the raw description text, so no
  lookup needed there. Every other field (engine, take, speed, chunk
  count, format/rate/depth/quality, subtitles, filename, subfolder/
  keep-chunks toggles, editing-wav settings including the
  channel-count-to-label reverse lookup through `EDITING_WAV_CHANNELS`,
  video toggle + image) is a plain `.set()` followed by calling
  whichever `refresh_*()` function that widget's own `<<ComboboxSelected>>`
  binding would normally have called, since setting a Tk variable
  programmatically doesn't fire that event on its own. A saved engine or
  voice that no longer resolves (renamed/removed since) is skipped rather
  than raising -- whatever `refresh_voices()` already set stands instead.
  A missing source file warns clearly and still restores every other
  setting, rather than refusing the whole load.
- `pick_file`'s body was split into `load_source_path(path)` (the part
  that doesn't need a file dialog) so "Load selected" and "Browse..."
  share one path instead of two implementations that could drift.
- The list refreshes on the same two hooks the Publish tab already used
  (`<<NotebookTabChanged>>`, and the render worker's `finally` block) --
  no new plumbing needed for "keep this in sync."
- One thing worth being explicit about since it's easy to assume
  otherwise: loading a project's *settings* is not the same as loading
  its *last render*. `state["last_render"]` (what "Publish"/"Fix a
  chunk"/chapters all act on) still points at whatever was rendered most
  recently in this session, regardless of which project's settings are
  currently showing on screen. Switching to an older project and hitting
  Publish without re-rendering first would publish the WRONG document's
  take. Not fixed here -- H (the queue) or a later pass could make
  `state["last_render"]` project-aware, but doing that honestly needs the
  same per-project tracking either way, so it wasn't invented ahead of
  being needed.
- Verified: two different documents rendered with deliberately different,
  distinctive settings (different engine, speed, take, output format) --
  confirmed each document's saved `cfg` is independently correct and
  that rendering the second never touched the first's saved values; then
  changed every visible setting to something else entirely and reloaded
  the first document, confirming engine/speed/format/subtitles (a
  representative spread of the different widget types involved, not
  just one) all came back to their exact original values. Status
  transitions (not_started -> rendered -> published) and forward-only
  demotion resistance verified directly, not just through the UI path.
  Removing an entry deletes only the targeted one.

### H. Queue / batch render — DONE 2026-08-29

- `render_document(cfg)` extracted from `work()`'s generate branch: one
  document start to finish from a settings snapshot, no widget access.
  The Generate button and the queue both call it, so there is a single
  narration path rather than two that could drift apart.
- `work_queue(paths)` renders library entries back to back, each with
  **its own saved cfg** rather than whatever is on screen. A document that
  fails is reported and the queue continues -- one bad file never abandons
  the batch. Three skip cases, each with its own message: the file is gone,
  the document has no saved settings yet (never rendered by hand), or its
  saved engine isn't available on this machine. Honours `state["cancel"]`
  between documents. Ends with a rendered/failed/skipped summary.
- Library list is `selectmode="extended"` with a **Render selected
  (queue)** button; `selected_project_paths()` sits alongside the existing
  single-selection accessor.
- **The last_render gap flagged here is now closed.** `state["renders"]`
  maps source path -> take record, populated in `render()` beside
  `state["last_render"]`. The Publish tab has a **Take to publish** picker
  (disabled when there's only one), and `current_take()` resolves it;
  publish, both chapter actions, and "Fix a chunk" all go through that
  instead of reading `last_render` directly. So after a batch run every
  finished take is publishable and fixable, not just whichever finished
  last. Verified explicitly: with q1 and q2 both rendered, selecting q1 in
  the picker publishes q1, not the more recent q2.
- `state["renders"]` is in-memory only, like `last_render` always was --
  it does not survive a restart. `segments.load_manifest()` is still the
  route for reopening an older take, and still isn't wired to a button
  (see A.2).
- Verified end to end through the real window: two documents rendered by
  hand to give them saved settings, a third added to the library and its
  file then deleted, all three queued -> 2 rendered, 1 skipped with the
  correct reason, both takes remembered, picker populated and readonly,
  and publishing following the picker rather than recency.

### I. Intro/outro — DONE 2026-08-29

Built as a **join**, not the ducked `amix` bed sketched here originally.
Concatenating with a crossfade is what podcast intros actually are, and it
is far more robust than trying to duck music under speech without any
loudness analysis.

- `audio.join_intro_outro(audio_path, intro, outro, crossfade, log)` runs
  after transcoding, chaining ffmpeg `acrossfade` filters (or plain
  `concat` when crossfade is 0). It returns **the number of seconds
  prepended**, not just success -- that return value is the whole point,
  see below. A crossfade longer than the shortest part is clamped to half
  that part rather than failing. A missing or unreadable asset, or a
  failed ffmpeg run, leaves the narration completely untouched and returns
  0.0.
- **The part that made this not a slot-in feature:** prepending an intro
  moves the narration later in the finished file, so everything already
  timed against the narration alone runs early by exactly the intro's
  length. Three things had to account for it, or they would have been
  silently, invisibly wrong:
  - `build_chunk_srt(..., offset=)` for Kokoro/Qwen3 captions, and
    `subtitles.shift_srt(path, offset)` for edge-tts's own SRT which is
    copied in already-timed.
  - `segments.build_manifest()` starts its running clock at
    `result["intro_offset"]` instead of 0, so absolute times point into
    the delivered file. In-chunk times stay chunk-relative, which is what
    `resplice_segment`'s surgery needs -- verified both in the same test.
  - Chapter marks come from the manifest, so they follow automatically.
  `intro_offset` rides on the result dict and into the manifest.
- Preferences gained an **Intro / outro** tab: two file pickers (with
  Clear) and a crossfade in seconds, autosaving. Global settings, per the
  established split.
- Verified against real audio through real ffmpeg, not stubs: a 4s intro
  with a 1s crossfade adds exactly 3s to a 10s narration and reports a 3s
  offset; intro+outro; crossfade 0 giving a full-length offset; an
  over-long crossfade clamped; a missing file leaving the file byte-wise
  untouched; both SRT paths shifted correctly with gaps preserved; and the
  manifest's absolute vs chunk-relative split.
- Not done, deliberately: no loudness normalisation between the assets and
  the narration. If an intro is much louder than the voice, that is
  currently the user's problem to fix in the source file. ffmpeg's
  `loudnorm` would be the tool if it ever becomes annoying.

### B. Voice Studio — DONE 2026-09-04

**Tools -> Voice studio...**

- `engines.saved_voices()` lists every voice on disk, newest first,
  reading the `voice.json` each folder was written with. A folder
  missing its reference clip or metadata is skipped rather than listed
  half-broken.
- `rename_voice()` stores a friendly `label` and deliberately does NOT
  touch the description or the folder name: the folder is derived from
  description + take and is what the render cache key depends on, so
  renaming it would orphan every chunk already rendered with that voice.
- `delete_voice()` refuses any path outside `VOICES_DIR` before calling
  `shutil.rmtree` -- it removes a directory tree, and a wrong path there
  is unrecoverable.
- `clone_voice_from_recording()` saves the person's OWN voice: it writes
  the recording as `reference.wav` plus a `voice.json` carrying the
  transcript. Qwen3's Base model needs that transcript for in-context
  cloning. Refuses a missing file, a missing transcript, or a clip under
  2 seconds, each with its own message.
  **The key design point:** `ensure_qwen_voice()` already read
  `meta.get("reference_text", QWEN_REFERENCE_TEXT)`, so a cloned voice
  flows through the ordinary render path with no special-casing at all.
  Verified by rendering with one.
- The dialog also auditions a description (designs it and plays the
  reference clip without narrating a document) and loads a voice into
  the Voice tab -- setting the engine AND the take, since description
  and take together identify a voice.
**CustomVoice — DONE 2026-09-04, built on request.** Speaker names
still aren't in the package; `list_qwen_custom_speakers()` loads the
CustomVoice model and calls `model.get_supported_speakers()`, same
query-on-the-real-machine-and-cache pattern as Kokoro voice discovery,
routed through the worker (`action: list_custom_speakers`), only ever
run when the person explicitly clicks **Fetch speaker list...**. This
download and the actual speaker names are unverified from Claude's
sandbox (huggingface.co blocked) -- the plumbing is tested end-to-end
against a stub matching the real API, first real run is the real test.

- `encode_custom_voice(speaker, instruct)` / `decode_custom_voice()`:
  a CustomVoice selection is carried as `"custom:" + json.dumps(...)`
  everywhere `voice` is otherwise a plain description -- JSON rather
  than a hand-rolled delimiter, since an instruction line can contain
  anything. `run_qwen()` and `_run_qwen_local()` both dispatch on this
  prefix to a genuinely separate code path: no reference clip, no clone
  prompt, no `ensure_qwen_voice` -- `generate_custom_voice(text,
  speaker=, instruct=)` directly, using `QWEN_CUSTOM_REPO` ("Qwen/
  Qwen3-TTS-12Hz-1.7B-CustomVoice", named in qwen-tts 0.1.1's own
  README). Sentence-group chunking, seeding, trimming, and the pacing/
  consistency sampling settings are all shared with the clone path
  unchanged.
- **A CustomVoice preset is a favourites list, not audio-artifact
  management.** Unlike a designed or cloned voice, speaker+instruct IS
  the whole, reproducible identity already -- there's no reference clip
  or randomly-sampled "take" to pin down and save. Presets live in
  `narrator_data/narrator_settings.json` (`custom_voice_presets`), not
  `VOICES_DIR`; saving the same label again replaces it rather than
  duplicating.
- `saved_voices()` now unifies three kinds (`designed` / `cloned` /
  `custom`) into one list. A `custom` entry has `reference=None` and
  `take=None`; the Voice studio's Play/Use/Delete actions branch on
  `kind` accordingly (no clip to play, no take to restore, delete edits
  the settings list instead of `shutil.rmtree`).
- Voice studio gained a third tab, **CustomVoice (preset speakers)**:
  fetch, pick a speaker, optional instruction, save as a preset or use
  immediately.
- Verified: encoding round-trips including an instruction containing
  punctuation that would trip a hand-rolled delimiter; speaker discovery
  in-process and via the worker; presets save/replace-by-label/delete;
  unification into `saved_voices()`; rendering produces real audio,
  sentence grouping still applies, the design/clone models are never
  loaded for a CustomVoice render, no voice folder gets created, the
  same speaker+instruct is byte-identical on a fresh cache, and a
  DIFFERENT instruction is a genuinely separate cache entry. Full path
  driven through the real window: fetch, pick, save, load into the
  Voice tab, and an actual Generate run through it producing a real
  output file.

### C. Installer / "proper app"

- Keep the PyPI/Hugging Face "@latest" fetch model (that *is* the npm-like
  approach); add: pre-flight check listing ffmpeg/pandoc/espeak-ng with
  `winget install` one-liners the wizard can run for the person (winget
  usually needs no admin for these; pandoc's MSI may prompt), a "verify" page that runs a
  1-sentence render per engine, and a per-file progress bar by wrapping
  `pip download` (which does report byte progress) followed by
  `pip install --no-index --find-links`.
- A real `.exe` needs building on Windows: `pyinstaller --onedir Narrator.py`
  with tkinter included, then Inno Setup for the Next/Next/Finish shell. Do
  this last; it is packaging, not capability. Only worth it at all if
  Narrator is ever meant to be installed by someone other than Routh —
  nothing said so far points at that; check before investing here.

### D. UI declutter — DONE 2026-08-27

Was: one tall single-column window, eight buttons in one row mixing
frequent actions with rare setup ones. Now: menu bar (**Settings ->
Preferences...**; **Tools** -> Clean text only / Audio -> WAV / Open
output folder) + a four-tab `ttk.Notebook` (**Document / Voice / Output /
Publish**) + a five-button primary bar (Generate, Hear a sample, Compare
all voices, Fix a chunk or sentence..., Open folder) that stays visible
under every tab. Section boundaries moved, not rewritten — `optbox` is
reassigned to point at the new frame right before each group of widgets
that use it, so ~300 lines of existing widget-construction code are
untouched. Output-location moved from beside the file picker to the
Output tab, next to format/quality (it's an output setting, not a
document one) — the clearest concrete win from the reorg, beyond the tabs
themselves. Publish tab is a labelled stub for E/F. Global vs. per-job
settings: **Preferences (Settings menu) is for things true across every
document** (engines, environments folder, and — as E/F/I land — hosting
URL, podcast metadata, intro/outro asset); **the tabs are for the current
render's own choices**. New features should follow that split rather than
re-litigating where their controls go. Verified: tab structure, menu
contents, cross-tab visibility toggling (change engine on the Document
tab, switch to Voice, correct controls appear), busy-state disabling
covers both menu cascades now, and a full Generate run through the
reorganised window still produces correct output + manifest end to end.

### Kokoro voice discovery — DONE 2026-08-29 (off the roadmap sequence -- Routh asked directly, mid-conversation, after noticing Kokoro's own site lists more voices than the 7 curated ones here)

The real constraint that shaped this: huggingface.co is not reachable from
Claude's own sandbox (confirmed directly -- a flat 403 through the egress
proxy), so there was no way to hand-verify the actual current voice
roster from in here, the way every other package detail this project has
touched was checked against the real thing. Rather than typing out a list
from memory (voices this app never bundled and whose exact names weren't
independently confirmable), the fix is a live query -- run on Routh's own
machine, which does have internet -- rather than a hardcoded snapshot
that would go stale as Kokoro adds more voices.

- Confirmed against the actually-installed `kokoro` package (0.9.4) and
  its own README, not memory: 9 languages total -- `a`/`b` (American/
  British English, this app's existing two), `e`/`f`/`h`/`i`/`p` (Spanish/
  French/Hindi/Italian/Brazilian Portuguese, via espeak-ng -- already a
  dependency here), `j`/`z` (Japanese/Mandarin, each needing an extra
  package: `misaki[ja]` / `misaki[zh]`). Mirrored as `engines.
  KOKORO_LANGUAGES` / `KOKORO_LANGUAGE_EXTRA_DEPS` -- a local copy rather
  than importing kokoro's own `LANG_CODES`, since that would need kokoro
  importable in THIS process even when it actually lives in a separate
  kokoro-env this process has no access to.
- `engines.list_kokoro_voices()` calls `huggingface_hub.list_repo_files
  ("hexgrad/Kokoro-82M")` -- a fast metadata call, not a download -- and
  parses `voices/{id}.pt` entries. Verified the function's real signature
  against the installed `huggingface_hub` package before writing this
  (same discipline as the mutagen/ffmpeg checks in F). Runs wherever
  `huggingface_hub` (a kokoro dependency) actually is: in-process, or via
  the SAME cross-environment worker a render already uses.
  `_run_via_worker`'s subprocess/IPC mechanics were extracted into a
  shared `_run_worker_job()` so this smaller query doesn't need to fake up
  a render-shaped job (chunks/voice/workdir it doesn't have) -- confirmed
  this refactor changed nothing about the existing render path via the
  existing worker tests, not just by reading the diff.
- `ui.py`'s `spec()` now merges in `settings["extra_voices"][engine_key]`
  (a list the user has grown themselves) on top of each engine's built-in
  list -- every existing call site that reads `s["voices"]` picks this up
  automatically, since they all go through `spec()`. The one place that
  doesn't (`work()`'s compare-mode, which snapshots `cfg["engine"]` on a
  background thread rather than reading the live selection) goes through
  the same merge via a small standalone `extra_voices_for()` instead.
- **"Find more voices..."** (next to Kokoro's pronunciation checker, so
  only visible when Kokoro is the selected engine): fetches on open,
  shows what's not already in the picker grouped English-first, flags
  Japanese/Mandarin with the exact `pip install` line they need,
  multi-select, **Add selected** saves to settings and refreshes the
  picker immediately.
- Real bug worth knowing about if this dialog gets touched again:
  the first version's "Added" confirmation used `messagebox.showinfo()`
  -- a MODAL call that blocks until something clicks it. Under Xvfb
  (nothing to click it) this hung forever, and traced misleadingly at
  first: every step up to and including the fetch completing and the
  list populating printed fine, because the hang was later, inside the
  Add button's own handler. Fixed by dropping the modal entirely in favor
  of the status line, matching how every other confirmation in this app
  already works (Publish, chapters, transcript export) -- not just a
  test workaround, a real consistency fix. The window also no longer
  auto-closes after adding, so a second batch (say, the Spanish voices
  after the English ones) doesn't need a re-fetch.
- Verified: parsing a realistic file listing (voice files correctly
  extracted, non-voice repo files correctly ignored), language grouping
  for every prefix including the two needing extra packages, the
  cross-venv worker path producing an identical result to the in-process
  path, and the existing render-worker path unaffected by the
  `_run_via_worker` refactor. Full path through the real window: fetch,
  verify English-first ordering and the Japanese/Mandarin dependency
  notes, select and add two voices, confirm they appear in the picker
  and in `narrator_data/narrator_settings.json`, confirm the dialog
  stays open and the added rows disappear from its own list, then
  re-fetch and confirm those two no longer show up as new.

### Token-aware chunking + Qwen consistency, round 2 — DONE 2026-08-29

**Kokoro's "token" is the length of the phoneme string, not words or
characters** -- verified in kokoro 0.9.4's own source, not assumed. The
hard ceiling is 510 (`pipeline.py`: `if len(ps) > 510: ... Truncating`),
and `KPipeline.en_tokenize()` ALREADY pre-splits at that number using
sentence-boundary "waterfall" logic. Two consequences worth not
rediscovering:

- For Kokoro, our chunk size does **not** control the generation unit.
  Kokoro re-splits internally whatever we hand it. Chunking mainly buys
  progress granularity and resume points; it only changes the sound if
  chunks get small enough to force splits Kokoro wouldn't have made.
- `KPipeline` splits on `split_pattern` (default `r'
+'`) BEFORE the 510
  logic, so each paragraph is its own generation. Short paragraphs (a
  heading turned into a one-line spoken transition, a list item) therefore
  become very short generations, well under the ~500 sweet spot, no matter
  what the chunk slider says. **Not yet addressed** -- worth a look if
  narration ever sounds flat around headings/lists specifically; the fix
  would be joining short paragraphs before handing text to Kokoro.

Built:
- `engines.KOKORO_TOKEN_LIMIT` (510) / `KOKORO_TARGET_TOKENS` (500).
  `measure_kokoro_phonemes(texts, log)` gives EXACT counts via
  `KPipeline(lang_code="a", model=False)` -- `model=False` loads only the
  small G2P front end, never the 300 MB voice model -- routed through the
  same cross-environment worker (`action: count_phonemes`) as everything
  else.
- `documents.chunk_limit_for(text, mode, value, engine_cap,
  chars_per_token)` -- one function both the on-screen preview and the
  real render call, so a displayed chunk count can never disagree with
  what actually renders. Modes: `parts` (a count, as before), `tokens`
  (a phoneme budget), `chars`. The engine's own cap still wins over any
  larger request.
- Characters-per-token starts as an explicit estimate
  (`DEFAULT_CHARS_PER_TOKEN = 1.05`) and the UI says "(estimated)" until
  **Measure tokens** replaces it with the real ratio for THAT document,
  measured on a 4,000-character sample from the middle. This
  calibrate-at-runtime approach was chosen deliberately over hardcoding a
  constant -- Claude's sandbox has no working misaki install (disk space)
  and huggingface.co is blocked, so any constant written here would have
  been unverifiable. The measured ratio rides in `cfg` and is restored
  from the library with the rest of a project's settings.

**Qwen3 voice consistency, second round.** Routh reported the voice still
shifting occasionally with designed voices. Two contributing causes, one
of which was introduced by an earlier session in this same conversation:

1. *Self-inflicted.* Adding sentence-level segments (roadmap A) changed
   Qwen3 from ONE generation per chunk to one per ~250-character sentence
   group, each with its own seed. A two-minute chunk went from 1
   independent generation to 5-8. The clone prompt pins the speaker, but
   every generation still samples independently, so more generations =
   more places the voice can wobble. This is the same symptom shape as the
   original design-per-chunk bug, milder.
2. Qwen3's own defaults are tuned for expressive one-off speech:
   `temperature=0.9` AND a separate `subtalker_temperature=0.9` (both
   verified in qwen_tts 0.1.1's source). High for an hour of one narrator.

Fix: `QWEN_SAMPLING` now passes `temperature=0.6`,
`subtalker_temperature=0.6` (plus the package's own top_k/top_p/
repetition_penalty) into every `generate_voice_clone` call, and
`qwen_group_chars()` makes the group size adjustable -- bigger groups mean
fewer seams but let Qwen3's own within-generation drift take over instead,
so it's a genuine trade rather than a strictly-better setting. Both are
overridable from `narrator_settings.json` (`qwen_sampling`,
`qwen_group_chars`); unknown keys in `qwen_sampling` are dropped rather
than forwarded, so a typo can't become an unexpected kwarg deep inside the
model. **Unverified by ear** -- no GPU here; the tests confirm the values
reach the model call, not that they sound better. If drift persists, try
`temperature` around 0.4 and `qwen_group_chars` around 500 before
concluding the approach is wrong.

Testing note for future sessions: a second `ttk.Spinbox` now exists (chunk
target, alongside Qwen's take), so any test selecting "the first spinbox"
is ambiguous. Three existing suites had to be disambiguated by range
(`to == 99` is the take spinbox). Select by a distinguishing property, not
index.

### Pacing regression (self-inflicted) + menu reorg — DONE 2026-09-02

Routh reported narration sounding "more mechanical, robotic" after the
pacing/chunking work. Investigated rather than guessed, and it was two of
my own changes compounding, not a setting used wrongly:

1. **Additive pauses.** `_join_chunk_wavs` inserted a flat 0.35s between
   chunks. Chunk boundaries fall at sentence ends, where the model has
   ALREADY trailed off into silence -- so the real pause was "however
   long this take happened to trail off" PLUS 0.35s: unpredictable, and
   longer than intended. Tolerable when a document was 3 chunks. Then
   token-based chunking made 15-chunk documents normal (and my own note
   recommended ~500 tokens), turning it into a long pause every ~300
   characters: audibly metronomic. Qwen3 had the same shape one level
   down, with a 0.25s gap between every ~250-character sentence group.
2. **Flat delivery.** Dropping Qwen3's temperature 0.9 -> 0.6 to stop the
   voice drifting also removed variation WITHIN a reading. Consistency and
   expressiveness are the same dial; I had quietly picked one end of it.

Fixes:
- `engines.trim_silence(data, rate, keep=TRIM_KEEP)` trims near-silence
  from both ends of each part (threshold relative to that take's own peak,
  so it adapts to level) before anything is joined. The gap between parts
  is then exactly what was asked for. All-silent and empty arrays are
  returned untouched rather than zeroed.
- **Correctness trap worth remembering:** the value reported as
  `chunk_gap` must be the silence actually INSERTED (`gap - 2*TRIM_KEEP`),
  not the total pause. Subtitles and the manifest step from one chunk's
  start to the next, and each chunk's own trailing keep is already inside
  its duration. Reporting the total would have drifted captions further
  out with every chunk. There is a test asserting
  `sum(durations) + n*chunk_gap == real master length` to within 20ms.
- Gap default 0.35 -> **0.12** (total pause), Qwen group gap 0.25 ->
  **0.06**, both settings, both clamped, both falling back on garbage
  input.
- `expressiveness` (0-1) maps onto `temperature` and
  `subtalker_temperature` together across `EXPRESSIVENESS_RANGE` =
  (0.45, 0.95); default 0.6 -> temperature 0.75, between the old 0.9 and
  my over-corrected 0.6. An explicit `qwen_sampling` block still wins.
- Preferences gained a **Pacing** tab for all three, with the trade
  spelled out on screen rather than left to be discovered.

Menu reorg (also requested): **Tools** now nests **Text tools** (Clean
text only, Check pronunciation, Export transcript) and **Convert**
(Convert audio), with Open output folder left at the top level. Note that
Check pronunciation and Export transcript now appear in BOTH the menu and
their original tab buttons -- deliberate, since the tab versions are
context-specific, but worth knowing before "deduplicating" them.

Verified with real audio: three chunks with deliberately different
trail-offs (0.9s / 0.2s / 0.6s) produce two identical 0.12s pauses where
before they would have produced three different ones.

### Transcription + model parameters — DONE 2026-09-02

**`narrator/transcribe.py`** (new): audio -> transcript, subtitles and
rough chapter marks, via `faster-whisper` (optional dependency; a missing
install raises `TranscribeUnavailable` with the pip line rather than an
ImportError). API checked against faster-whisper 1.2.1's real source:
`WhisperModel(size, device="auto", compute_type="default")`,
`transcribe(audio, language=, word_timestamps=, vad_filter=)` returning
`(segments_generator, info)`, segments carrying
`.start/.end/.text/.words`, words `.start/.end/.word`.

- `transcribe_audio()` converts the library's objects into plain dicts at
  the boundary, so everything downstream (and every test) works without
  faster-whisper importable at all. Recognition happens lazily as the
  generator is consumed, so progress is reported from inside that loop.
- `paragraphs()` regroups Whisper's per-utterance segments on pauses --
  writing one segment per line reads as choppy fragments.
- `detect_chapters()` guesses sections from pauses >= `CHAPTER_SILENCE`
  (2s), titled from the following words, and feeds the EXISTING
  `chapters.format_youtube_chapters()` unchanged. **These are guesses**
  and are labelled as such in the dialog: recognised speech has no heading
  structure, unlike our own renders where chapter marks come from the
  source document's real headings.
- UI: **Tools -> Convert -> Audio to text (transcribe)...** with model
  size, and optional SRT / chapter marks / per-line timestamps.
- **Not verifiable here:** huggingface.co is blocked from Claude's
  sandbox, so no real Whisper model could be downloaded. Everything is
  tested against a stub matching the real API exactly. The recognition
  quality itself, and the real model download path, are unverified --
  first real run is the test.

**Model parameters.** `engines.TUNABLE_PARAMS` is a per-engine registry of
what each model ACTUALLY exposes (qwen3: temperature, subtalker_
temperature, top_k, top_p, repetition_penalty -- verified against
qwen_tts 0.1.1; kokoro and edge expose nothing beyond speed and voice, and
the UI says so rather than inventing knobs). `engine_params()` clamps to
range, preserves int-ness, drops unknown keys, and falls back on
unparseable values -- so nothing hand-typed into settings can become a
bad kwarg inside a model call. Preferences gained a **Model parameters**
tab with per-parameter defaults shown and a Reset. Precedence, lowest to
highest: package defaults -> `expressiveness` dial -> `engine_params` ->
a hand-written `qwen_sampling` block.

### Audiogram: layout controls + transparent overlay — DONE 2026-09-02

Routh's objection to "just bake it" was correct and reframed the design:
baking is precisely WHY the layout has to be adjustable first. So both
were built, and the controls exist because the output is baked.

**`narrator/audiogram.py`** (new). It does NOT use ffmpeg's `showwaves` --
that filter is linear only, and cannot express a ring, a pivot, or
arbitrary placement. Frames are drawn with PIL instead, which makes every
one of those an ordinary parameter.

- `analyse()` -> per-frame band magnitudes via a plain numpy STFT with
  log-spaced band edges (linear FFT bins put nearly everything in the
  bottom bar for speech, which looks dead), sqrt-scaled and optionally
  smoothed. Verified that smoothing genuinely reduces frame-to-frame
  jitter rather than just existing as a parameter.
- `layout()` resolves fractional settings to pixels and is **shared with
  the preview**, so the mockup cannot drift from the real output. Polar
  radii scale off the SHORTER frame side, so a layout survives an aspect
  change. An outer radius set below the inner one is corrected rather than
  drawn inverted.
- `draw_frame()` renders linear (bars or line, optionally mirrored) or
  polar (a genuine ring -- the centre stays empty, asserted) to RGBA with
  a transparent background. Rotation is about the PIVOT, not the image
  centre, which is what makes the pivot a real control.
- `render_overlay()` pipes raw RGBA into ffmpeg. Codecs: **VP9/webm
  (default)**, ProRes 4444, or a PNG sequence. Measured at 1080p, 3s of
  audio: ProRes 7.0x realtime / 4.2 MB; VP9 5.5x / 0.02 MB -- VP9 is
  ~200x smaller for a mostly-transparent overlay, which is why it is the
  default. ProRes 4444 encodes `yuva444p12le` here, not `10le`; assert on
  the `yuva` prefix, not an exact depth.
- `crop_box()` / `crop=True` renders only the audiogram's own area:
  1080p linear went 5.5x -> **1.7x realtime** (a 30-minute episode ~50
  minutes instead of ~2.8 hours). Dimensions are snapped even for codec
  compatibility, and **rotation disables cropping** rather than gambling
  on the rotated bounds. The offset is logged and left on
  `render_overlay.last_crop` so the editor placement can be reported.
- UI: **Tools -> Audiogram layout...**. Shape (geometry/style/bars/line
  width/smoothing/mirror), position and size, centre, inner and outer
  radius, pivot, rotation, colour, opacity -- with a live preview that
  composites the background image, a frame drawn by the real renderer, a
  dashed bounds box, a green centre marker and an orange pivot cross, plus
  a running estimate of what fraction of the frame a cropped export would
  cover. Layout persists in `settings["audiogram"]`.

Why this helps Resolve: it composites a finished clip with real alpha
instead of Fusion recomputing a waveform every frame. `build_video()`'s
existing in-app showwaves path is untouched and still fine for a quick
self-contained mp4.

Not done: dragging the centre/pivot directly on the preview (they are
numeric fields), per-band colour gradients, and reacting to a specific
frequency range rather than the full spectrum.

### Still open from Routh's 2026-09-02 review

### Word pronunciation editor — DONE 2026-09-03

Closes the gap Routh reported: the scanner only ever surfaced words with
NO dictionary entry, but a word can be in Kokoro's lexicon (so never
flagged) and still read wrong.

- `pronunciation.lookup_words(query, limit, overrides)` searches
  `G2P().lexicon.golds` plus any saved overrides. Prefix matches sort
  before substring matches, which is what makes typing feel like
  filtering rather than reshuffling. Capped (default 150) with the true
  total returned, so truncation is visible rather than silent.
- `pronunciation.current_phonemes(word, overrides)` answers "what does
  Kokoro actually say for this right now" for **any** word -- returning
  `source` as `override` / `dictionary` / `guessed` (espeak fallback).
  This is the part that makes editing a known-good-looking word possible.
- `_gold_to_text()`: lexicon values are usually a plain phoneme string but
  some are a part-of-speech dict (`{"VERB": ..., "DEFAULT": ...}`) --
  flattened for display with the alternatives named, not crashed on and
  not silently hiding that the word varies by role.
- Both routed through the existing cross-environment worker
  (`action: lookup_words` / `current_phonemes`), tested to return results
  identical to the in-process path.
- UI: **Tools -> Text tools -> Edit a word's pronunciation...**. Live
  filter (debounced 220ms, so a fast typist doesn't queue one lookup per
  keystroke), the list marking overrides with `*`, the current
  pronunciation and its source, a respelling field with live preview
  reusing the existing `respell_to_ipa`, and Save / Remove.
- Bug caught by its own test: `do_search()` clears the status line, so
  refreshing the list after a save wiped the confirmation message. Order
  is now refresh-then-report in both save and remove.
### Audio converter — DONE 2026-09-03

- `audio.convert_audio()` reuses `transcode_audio()` (so the standalone
  converter and a render's own format handling can never diverge), plus a
  second pass for channel count -- `-c:a copy` cannot change channels and
  `transcode_audio` has no channel argument.
- `audio.split_audio(src, out_dir, stem, ext, seconds=|max_bytes=)`.
  **Only duration is directly controllable**, so a size limit is met by
  measuring the file's REAL bytes-per-second (`measured_bitrate()` --
  requested bitrate is not what lands on disk once VBR and container
  overhead are involved), estimating a duration with 3% headroom, then
  VERIFYING every part and re-splitting more finely if any is still over.
  Bounded by `max_passes=4`; on giving up it says what it achieved rather
  than pretending success. Falls back from `-c copy` to re-encoding when a
  format can't be cut on arbitrary boundaries. Re-splitting a folder
  clears the previous parts rather than accumulating them.
- **Bug found by testing, worth remembering:** ffmpeg's segment muxer
  leaves a final fragment of a few hundred bytes with no readable duration
  -- a file some players refuse to open. `MIN_PART_SECONDS = 0.25` filters
  these out after the split, and the test asserts every surviving part is
  playable AND that total duration is preserved (so the discard is
  provably lossless, not just tidy).
- UI: **Tools -> Convert -> Convert audio...** with format, quality (live
  readout showing the actual kbps / FLAC compression level / "no effect"
  for WAV), sample rate, bit depth, channels, and split-by-minutes or
  split-under-N-MB. The old one-click behaviour survives as **Quick
  editing WAV...** since it was genuinely a one-click convenience.
- Verified end to end through the real window: a 40s file converted to MP3
  and split under 1 MB produced 2 parts, both under the limit, both
  playable, totalling the original 40s.

Every item from Routh's 2026-09-02 review is now closed.
- **A.4 word-level editing** now has its dependency available:
  `transcribe.transcribe_audio(..., want_words=True)` already returns word
  timings, so the faster-whisper route exists and is tested.

### Optional components + the licence position — DONE 2026-09-04

The groundwork for handing Narrator to anyone else. `narrator/
components.py` is a UI-agnostic registry (plain dicts in, plain dicts
out) so the Tk dialog and any future interface read one source of truth.

- Nine components across four kinds: `external` (ffmpeg, espeak-ng,
  pandoc), `python` (mutagen, faster-whisper, Pillow), `engine` (Kokoro,
  Qwen3), `model` (Qwen3 CustomVoice). Each declares licence, size, what
  it unlocks, a download URL and a hint. A test asserts every component
  declares all of those, so a new one can't be added half-documented.
- **The licence position, per Routh's Audacity-style proposal:** anything
  permissive can be bundled; `mutagen` is GPL-2.0 and is deliberately NOT
  bundled but offered as a one-click optional install, with the dialog
  saying why and noting that m4a chapters work without it. Verified
  licences: Kokoro and misaki Apache-2.0 (Kokoro's *weights* explicitly
  Apache-2.0 too, per its own README), qwen-tts and huggingface_hub
  Apache-2.0, faster-whisper MIT, mutagen GPL-2.0. **Qwen3-TTS model
  weights confirmed Apache-2.0 by Routh on 2026-09-04** (Claude could not
  reach the model card to check it directly) -- so every engine's weights
  are permissive and mutagen is the only GPL piece in the optional set.
  None of this is legal advice.
- `require_components(*keys, feature=)` in ui.py turns a missing piece
  into an offer to install rather than a failure partway through.
  Transcription gates on faster-whisper, the audiogram on Pillow+ffmpeg;
  verified that the audiogram window does NOT open when gated.
- **Real bug this surfaced, and it matters for distribution:** PEP 668.
  Modern Linux distributions mark the system Python "externally managed"
  and refuse `pip install` outright. Verified here that `--user` alone is
  ALSO refused on Debian. `install_python_component()` now escalates:
  plain install inside a virtualenv; otherwise `--user`, then
  `--user --break-system-packages` (which despite the name writes only to
  the user's own site-packages and touches nothing the OS owns), and if
  all fail, recommends a virtualenv with the exact commands. It only
  escalates when the failure actually says `externally-managed`. A test
  performs a REAL install through this path.
- Detection notes worth keeping: `setup_engines.engine_status()` returns
  a TUPLE `(exists, python_path, importable)`, not a dict -- got that
  wrong first and the test caught it. Pillow's import name (`PIL`)
  differs from its package name, so components carry an optional
  `module` override rather than deriving it. Probing happens in a
  subprocess so a broken package can't take the caller down, and any
  probe failure degrades to "not installed" with the reason.

**Engines listed-but-greyed — DONE 2026-09-04**, exactly as Routh
described. The Voice tab's engine dropdown now lists ALL engines, not
just installed ones (an engine you can't see is one you don't know you
could have). Selecting an uninstalled engine greys out every
engine-dependent control -- voice picker, speed, take, build-a-voice,
pronunciation, Generate/Sample/Compare -- shows what it would cost
("Not installed yet (about 8 GB)"), and offers **Download and set up**
with a progress bar. On success it calls `forget_engine_probes()` and
re-enables everything: the engine becomes usable WITHOUT restarting the
app, which the test asserts explicitly.

Two wiring details that are easy to get wrong:
- `set_running(False)` re-enables buttons after any job, which would
  wrongly un-grey controls for an engine that still isn't installed. It
  now calls `refresh_engine_setup()` on the way out.
- `create_environment()`'s progress callback reports coarse STAGES
  (`{"kind": "stage", "step", "total"}`), not a smooth percentage,
  because pip's byte-level progress isn't reliable once piped. The bar
  reflects exactly that granularity rather than inventing a smooth fill.

Still not built for the `model` kind (Qwen3 CustomVoice weights) -- that
one is still fetched from the Voice studio's CustomVoice tab, which is a
reasonable home for it since choosing a speaker is the moment you need
it. Per-component byte-level progress remains limited by what pip
reports.

The UI-framework question is decided in principle but NOT started: keep
all Python engine code, move only the interface to a local web frontend
served by the Python backend. Tkinter is the limit for curve/expression
editing and live preview. Do not begin that migration piecemeal -- it
wants its own planned effort, and the component registry above was
deliberately written UI-agnostic so it survives the move unchanged.

**On expressions-over-time** (Routh's idea): a good fit for the
audiogram, where every parameter is already evaluated per frame. A poor
fit for TTS sampling parameters -- `temperature` is one value per
generation call, so "over time" can only mean a step function of a dozen
or so values across an episode, not a curve. Worth building for the
audiogram; worth being honest about the limit for the engines. Needs a
sandboxed expression parser, never `eval()`.

### Expressions — DONE 2026-09-04

Parameters can be a formula over time instead of a constant.
`narrator/expressions.py` is deliberately standalone and UI-agnostic, so
it survives the eventual web-UI move and can drive anything, not just the
audiogram.

**Safety.** Formulas come from a text field, so `eval()` is not an option
-- that is arbitrary code execution. Expressions are parsed with `ast` and
walked against a whitelist of node types and names; attribute access,
calls to anything outside FUNCTIONS, imports, comprehensions, lambdas,
subscripts, dict/set literals and dunder names are all rejected at
COMPILE time, before the formula can run once. Evaluation then happens
with `__builtins__` emptied. A test fires twelve concrete escape attempts
(`__import__`, `().__class__.__bases__`, `open`, `lambda`, `exec`,
`globals`, ...) and asserts every one is refused.

**Discoverability -- what Routh specifically asked for.** VARIABLES and
FUNCTIONS are registries where each entry carries its own description,
and `reference(filter_text)` returns them for the UI. Both are provided,
as suggested: a full reference list of all 30 names AND live filtering.
The filter matches the word under the cursor (not the whole formula), so
typing `sin(ta` filters to `tau` first; it searches descriptions too, so
"loudness" finds level/bass/mid/treble. A test adds a variable to the
registry and confirms it becomes both usable and documented in one edit
-- the registry cannot drift from the reference.

Variables: `t`, `duration`, `progress`, `frame`, `fps`, `level`, `bass`,
`mid`, `treble`, `pi`, `tau`, `e`. Functions: sin/cos/tan, abs, min/max,
clamp, lerp, smoothstep, floor/ceil/round, sqrt/pow/exp/log, sign, fmod.

**In the audiogram.** `ANIMATABLE` lists the 13 parameters that may be a
formula -- deliberately NOT `bars` or `fps`, which fix the shape of the
analysis array and the frame count. `frame_context()` builds each frame's
variables including the band groupings, so formulas are audio-reactive
(`outer_radius = 0.15 + 0.2*level`) as well as time-based
(`rotation = 30*progress`). `resolved_cfg()` returns the SAME object
untouched when no formula is present, so a static layout costs nothing.
A broken formula falls back to that parameter's default rather than
aborting a render thousands of frames in. **An animated layout disables
cropping** -- a formula can move the figure anywhere, and computing the
union of every frame's bounds isn't worth the clipping risk.

**Scope, stated honestly.** This is right for the audiogram, where every
parameter is already evaluated per frame. It is NOT wired to the TTS
sampling parameters, and shouldn't be without care: `temperature` is one
value per generation call, so "over time" there could only mean a step
function of a dozen or so values across an episode -- a real feature, but
a much smaller one than the phrase suggests. Don't let the audiogram's
success imply the engines can do the same thing.

Testing note: `ttk.Combobox` subclasses `ttk.Entry`, so
`[w for w in walk(win) if isinstance(w, ttk.Entry)][-1]` can return a
combobox. Identify entries by behaviour or by their textvariable, not by
position.

### Extracting session.py — DONE 2026-09-05

Groundwork for the web UI, done while the Tk version is still the one in
use. `ui.py` was 4,713 lines -- 42% of the codebase -- and the render
orchestration lived inside it as closures over Tk widgets, meaning a
second interface would have had to reimplement it.

`narrator/session.py` (222 lines) now holds, with no tkinter anywhere:

- **`Session`** -- the take store. `record()`, `takes()` (only those whose
  output file still exists), `take_named()` (falls back to the most
  recent), `take_names()`. Replaces the raw `state["last_render"]` /
  `state["renders"]` dict entries; there were exactly 8 touch points in
  ui.py and all are gone.
- **`render()`** -- the orchestration lifted verbatim out of ui.py, now
  taking `log`, `engine_spec` and `session` as arguments instead of
  closing over them. Still must not touch widgets; that comment moved
  with it because it is still the reason the function has this shape.
- **`chunks_for()`**, **`render_document()`**, **`run_queue()`** -- the
  batch logic, including all three skip cases and cancellation, now
  driveable headlessly. ui.py's queue worker is down to thread handling
  plus one call.
- **`flatten_take()`** / **`sentence_at()`** -- the timeline's data model.
  The dialog is now a view over these rather than owning them.

ui.py: 4,713 -> 4,591 lines, and much more of what remains is genuinely
presentation. `test_session.py` asserts `"tkinter" not in sys.modules`
after driving two full renders, a three-document queue and the timeline
model -- so the claim that this is UI-agnostic is enforced, not just
stated.

Testing note: five GUI suites reached in via
`state.get("last_render")` and broke on this change. That is exactly what
those hooks are for, but it is worth knowing that test hooks poking at
internal state are the thing that breaks on a refactor like this, not the
app.

### The render-settings schema — DONE 2026-09-05

`cfg` used to exist only as a dict literal in `ui.py` assembled from ~25
Tk variables. That made the settings implicit: the only way to know what
a render accepts, what a value may be, or what happens when one is
missing was to read widget code -- and a cfg arriving from a saved
project had nowhere to be checked.

`narrator/render_config.py` makes the schema the source of truth and the
widgets one way of filling it in.

- 26 fields, each with a default, a kind (text/path/bool/int/float/
  choice), a range or choice list, and a description. `describe()`
  returns all of it -- a settings screen, an API doc or a validation
  message can be generated from the schema instead of hand-maintained.
- **Choice lists are asked of the module that owns them** (`ENGINES`,
  `AUDIO_FORMATS`, `CHUNK_MODES`) rather than copied here, so they can't
  fall out of date.
- `coerce(raw)` -> `(cfg, problems)` takes anything dict-shaped -- from
  widgets, a saved project, or JSON -- and returns a clean cfg plus
  problems in plain language. **Values are validated, not merely
  defaulted:** out-of-range numbers are clamped AND reported, unknown
  choices are refused rather than passed to ffmpeg, and unknown keys are
  dropped with a message so a typo in a saved project can't silently do
  nothing. `strict_paths=False` skips file-existence checks, for
  validating a form before files are chosen.
- ui.py now runs its widget-built cfg through `coerce()` before starting.
  Blocking problems (missing requirement, unknown choice, missing file)
  stop the render with a dialog; the rest are logged as notes.
- A test builds a cfg from ONLY the schema and renders end to end with
  it, and round-trips a library-saved cfg back through `coerce()` clean
  -- so "the schema covers what a render actually needs" is enforced.

**Real bug this surfaced.** `start()` read the source file *before*
building cfg, so a document moved or deleted since it was picked threw an
uncaught exception into the Tk callback -- the person saw nothing at all.
Now guarded with a message naming the file and asking whether it moved.
Found only because the test deleted the file mid-session; worth doing
that to more of these paths.

### tasks.py and a headless CLI — DONE 2026-09-05

The last of the extraction, plus the thing that proves it.

`narrator/tasks.py` holds the operations that were closures in dialogs:
`publish_take()`, `chapters_for_take()`, `embed_chapters_in_take()`,
`export_transcript()`, `transcribe_file()`. Each takes plain values and a
`log` callable and returns plain data. **Threading stays in the
interface** on purpose -- a web backend and a desktop app handle it
completely differently, and baking Tk's `after()` into these would have
undone the point. The dialogs now call these instead of carrying their
own copies, so there is one implementation of each operation rather than
two that could drift.

`python -m narrator` gained real commands:

    render doc.md --engine ... --voice ... --chunk-mode chars
    queue [paths...]
    transcribe audio.mp3 [--model small] [--no-subtitles]
    settings

`settings` prints the render schema -- every field, its type, allowed
values and description -- generated from `render_config`, so it can never
drift from what a render actually accepts.

**These exist for their own sake** (scripting an overnight batch, or
driving Narrator from something that isn't this GUI) **and as a standing
check on the architecture.** `test_cli.py` renders a document end to end
through the CLI and asserts `tkinter` is never imported. If a future
change makes a command need something from `ui.py`, that test fails --
the separation is enforced rather than trusted.

Bad input is refused with a reason and no traceback: a missing document
reports `path: no file at ...`, an unknown engine lists the real ones.
The internal `--worker` path is unchanged and separately tested, since
that runs inside engine venvs that may have no Tk at all.

### Where the extraction stands

ui.py: 4,713 -> 4,579 lines, and the four modules pulled out of it
(`session` 222, `render_config` 201, `tasks` 133, plus `components` and
`expressions` written UI-agnostic from the start) are what a web frontend
would otherwise have had to reimplement. What remains in ui.py is now
mostly genuinely presentational: widget construction, layout, and the
library load/restore mapping whose widget half IS presentation.

The web UI can now be approached as "write a new frontend against these
modules" rather than "untangle the app first", which was the whole point
of doing this before starting it.

### The web stack, first vertical slice — 2026-09-05

Stack chosen and now proven end to end: **FastAPI + uvicorn** serving a
**React (Vite)** build. Deliberately NOT Next.js -- it is a server
framework whose SSR, routing and API routes are all dead weight for a
locally-installed tool, and it would mean shipping two runtimes. Vite
builds static files that the Python server already serves: one process,
one runtime. Verified installable and current: fastapi 0.141, uvicorn
0.52, pywebview 6.2 (BSD-3-Clause, the option for a native window later).

**`narrator/jobs.py`** -- a render takes minutes to hours, so it cannot
live inside an HTTP request. Every operation becomes a job: start it, get
an id, then poll or subscribe. The existing `log(message)` callable is
what made this possible; a job just supplies one that appends to its own
buffer, so nothing underneath changed to become observable. `snapshot(
since=)` returns only new lines, so polling a job with thousands of them
stays cheap. Finished jobs are evicted oldest-first; a running one never
is.

**`narrator/webapi.py`** -- thin endpoints over the already-extracted
modules. If an endpoint ever needs logic of its own, that logic belongs in
`session`/`tasks`/`render_config` instead, where the desktop app and CLI
can reach it too.

- **Security is the part not to loosen.** Binds to 127.0.0.1; every
  endpoint except `/api/health` needs a token compared with
  `secrets.compare_digest` (not `==`, which leaks the token a character
  at a time under timing). The API browses the filesystem and starts
  processes, so "local" is not "safe" -- any page open in the browser can
  reach 127.0.0.1. `serve()` warns if bound beyond localhost.
- `EventSource` cannot set headers, so `/api/jobs/{id}/events` takes the
  token as a query parameter. A real browser constraint, not a shortcut;
  checked the same constant-time way.
- `/api/schema` returns `render_config.describe()`, and the frontend
  GENERATES its settings form from it. Hand-writing that form would
  recreate exactly the drift the schema was built to remove.
- `/api/validate` gives the same verdict a render would, without starting
  one -- so the form can be honest as it is typed.
- A rejected render returns 400 and creates NO job (asserted).

**`web/`** -- the React source. `api.js` moves the token from the URL into
`sessionStorage` and strips it from the address bar. `JobLog.jsx` streams
by default and **falls back to polling if the stream drops**, because a
dropped connection must not look like a hung render -- the failure mode
that would waste the most time.

**Tested for real, not mocked:** `test_webapi.py` drives the app in
process (auth, schema, validation, job lifecycle, incremental cursor, SSE,
file browsing, cancellation). `test_webstack.py` starts an actual server
subprocess, fetches the actual built JS bundle over HTTP, confirms an
unauthenticated request is refused over the wire, then renders a document
through the API while consuming the SSE stream, and checks the output file
exists.

**Scope of this slice, stated plainly.** Only one workflow: choose a
document, set options, generate, watch progress, see the take. The
timeline, voice studio, audiogram layout, publishing and library remain
desktop-only. That was the point -- surface every hard problem (jobs,
streaming, file paths, auth, schema-driven forms) on the smallest surface
that exercises all of them, with the desktop app still working throughout.

**Next, in order:** port the library and takes views (both are already
plain data over existing endpoints); then publishing (needs `tasks.py`
wired to endpoints, which is mechanical); then the audiogram layout, where
a canvas frontend can finally give the draggable centre/pivot handles that
Tkinter made awkward. The timeline is the biggest and should come last --
it needs waveform data over HTTP, which means a new endpoint returning
`audio.envelope()` rather than reusing anything existing.

### Job history made usable — 2026-09-05

Routh's report: hard to find the right job, and no way to see what a past
one actually did. Both were true -- `/api/jobs` existed but nothing
surfaced it, and finished jobs vanished when the process ended.

- `Job` gained `detail` (arbitrary identifying metadata -- document,
  engine, voice for a render) and `outcome`, a one-line plain-language
  result the WORK sets, since only it knows what "went well" means for
  its kind: a render reports `"12.4 min, 8.1 MB -> chapter.mp3"`, a queue
  `"3 rendered, 1 skipped"`, a transcription its file count.
- `snapshot(with_lines=False)` gives a summary without log lines, so a
  list view never ships thousands of them.
- **History persists** to `narrator_data/narrator_jobs.json`: the last 200
  jobs, each keeping the last 300 log lines and flagged `truncated` if
  more. The point is recognising a past job, not re-reading it whole.
- `JobStore.list(query=, status=, kind=)` filters SERVER-side, so a long
  history isn't shipped over the wire to be searched. The query matches
  label, kind, outcome, error and every `detail` value -- searching
  "qwen" finds a job by its engine alone.
- `get_record()` returns a live job or a remembered one, so a job from
  last week can still be opened and its log read.
- `JobList.jsx`: search box, kind and status filters, one row per job
  (status mark, label, kind, outcome, when + duration), expanding to the
  metadata and full log -- fetched only when a row is opened.

**Real bug found by testing, worth remembering.** Jobs finish on their own
threads, so several can rewrite the history file at once: one truncated it
while another was reading, leaving a 0-byte file and losing everything.
Fixed with a dedicated lock AND an atomic write (temp file + `os.replace`),
so a reader always sees either the old history or the new one, never a
half-written file. Writing in place would still have left an empty file if
serialising failed partway.

**Second, subtler race, left as-is deliberately.** `job.status` flips to
done when the WORK finishes; the history write happens immediately after
on the same thread. So there is a sub-millisecond window where a job reads
as finished but isn't yet persisted. Harmless in practice -- live jobs are
always in the list regardless, and history only matters after a restart --
but a test reading the file directly must wait for the record, not the
status. Noted so nobody "fixes" it by moving the status assignment, which
would make status lie about the work.

### Library and publishing in the web UI — 2026-09-05

Routh chose to keep both interfaces alive. The refinement that makes that
affordable: **the logic is already shared, so only presentation costs
twice -- and presentation splits by kind.** Forms-and-lists (library,
publishing, components, settings) are cheap to build in both. Bespoke
interaction (the timeline canvas, audiogram layout with draggable
handles) is expensive, and the web version would be genuinely better --
those should pick ONE home rather than being maintained as two half-good
versions. This session did the cheap half to prove the pattern.

New endpoints, all thin wrappers over `tasks.py`, which already existed:
`GET/POST /api/podcast` (channel settings plus which required fields are
still unset), `POST /api/publish`, `GET /api/chapters`,
`POST /api/chapters/embed`, `POST /api/transcript`. `_take_or_404()`
resolves a take by name and 404s with a useful message rather than
failing obscurely.

Frontend: `Library.jsx` (documents, status, saved voice, "Load settings"
which puts a saved cfg straight back in the form -- no mapping layer,
since the schema made cfg the same shape everywhere) and `Publish.jsx`
(take picker defaulting to the newest but never silently switching away
from a deliberate choice, episode title/notes, publish, find chapters,
embed chapters, collapsible channel settings, the current feed contents).

Verified against real artifacts, not mocks: publishing writes a feed whose
enclosure URL actually points at the configured hosting URL, the library
entry really advances to `published` as a side effect, republishing the
same take updates rather than duplicates, and embedded chapters are
confirmed by `ffprobe` reading the finished mp3.

**Parity now:** web has render, library, publishing, chapters,
transcripts, job history, components. Desktop still exclusively has the
timeline, voice studio, audiogram layout, pronunciation editing, the
converter and engine setup.

**On process** (Routh asked whether to plan ahead): the reactive loop has
outperformed the planning. The pacing regression was caught by Routh
narrating a real chapter, not by any test or plan. Meanwhile several
planned designs were wrong on contact with reality -- word-level editing
(splicing single words was the wrong shape), chapter marks (character
offsets don't survive chunking), CustomVoice (deferred, then correctly
overridden). Conclusion recorded: **plan sequence and interfaces, not
implementations.** The dependency order in this roadmap is worth having;
detailed designs written a week early mostly are not.

**Test-suite timing, measured rather than assumed (2026-09-06).** The
earlier worry about splitting the suite was premature: all unit suites
total **43s**, all GUI suites **104s** -- about 2.5 minutes for everything.
No split needed. The one real finding: `test_components` (13.9s, the
slowest by a wide margin) is slow because it performs a REAL pip install
and uninstall, so it is the only suite that needs network and the only one
that would fail offline. Worth knowing before debugging a mysterious
failure on a train.

### Pronunciation and the converter in the web UI — 2026-09-06

The rest of the forms-and-lists half. Both are thin wrappers over modules
that already existed; no new logic anywhere.

Endpoints: `GET /api/pronunciation/search` (dictionary + overrides,
prefix-first), `GET /api/pronunciation/word` (what Kokoro says right now
and where it came from -- override / dictionary / guessed), `POST
/api/pronunciation/preview` (build the phonemes without saving, naming the
first unresolvable piece), `POST /api/pronunciation/save`, `DELETE
/api/pronunciation/{word}`, `GET /api/convert/options`, `POST /api/convert`
(a job, since a long file takes a while).

`Pronunciation.jsx` keeps the property that matters: **any** word can be
inspected and overridden, not only ones a scan flags -- a word can be in
Kokoro's dictionary, never reported as unknown, and still read wrong. The
list offers "check this anyway" for a word that isn't listed at all.
`Convert.jsx` carries the split-by-size explanation, since "keep parts
under N MB" is approached rather than set.

**Stub fidelity, worth remembering.** The misaki stub previously resolved
any alphabetic word through a fake espeak fallback, which made a test
asserting a *failed* respelling impossible to write honestly. A bare
`misaki_en.G2P()` has no espeak fallback -- that lives in KPipeline -- so
unresolvable fragments come back as the ❓ marker. The stub now returns ❓
for the specific pieces this project VERIFIED against real Kokoro earlier
("non", "ni", "mization"), and its comment says plainly that how far real
misaki's own rules stretch for other words is not something the stub can
claim. Tests should not depend on that boundary.

**Parity now.** Web: render, library, publishing, chapters, transcripts,
pronunciation, converting/splitting, job history, components. Desktop
still exclusively: the timeline, voice studio, audiogram layout, and
engine setup.

The three remaining desktop-only features are all the expensive kind --
bespoke interaction rather than forms and lists. Per the agreed split,
each should pick ONE home rather than being maintained twice; the web
version would be genuinely better for the timeline (real waveform
scrubbing) and the audiogram (draggable centre/pivot handles, which
Tkinter made awkward enough that they shipped as numeric fields).

### LLM providers (bring-your-own) — started 2026-09-06

Groundwork for a **dialogue script generator**: turning a chapter into a
two-host conversation, then rendering it through the existing engines with
alternating voices. That is what makes NotebookLM's audio overviews
appealing -- and it is a script problem, not a TTS problem. Nothing on the
TTS options Routh found beats Kokoro/Qwen3; NotebookTTS in particular has
a polished README but **no code at all** (no setup.py, no package, not on
PyPI -- every path checked returned 404). Podcastfy is real and
Apache-2.0, but it is an orchestration layer over other people's TTS, and
its useful part is the prompting, not the engines.

**The licence insight worth keeping.** Bring-your-own-key does not merely
work around the restricted-weights problem, it dissolves it. Narrator
ships no keys and no weights; if a person points it at their own Ollama
running Gemma, or their own API key, the licence obligation is theirs and
Narrator has distributed nothing restricted. Same shape as the `mutagen`
decision.

**`narrator/llm.py`** -- providers, local or hosted, chosen per job.

- Everything speaks the **OpenAI chat-completions shape**, which Ollama,
  llama.cpp, LM Studio, vLLM, OpenRouter, Groq and DeepInfra all expose
  natively, and which Anthropic and Google publish compatibility endpoints
  for. One client covers all of them; anything unusual is a "custom" base
  URL rather than new code. Requests go through stdlib `urllib` on
  purpose -- a local-first tool shouldn't need an extra HTTP package
  installed before it can talk to a local model.
- Ten templates (3 local, 7 hosted), each carrying a plain note. A test
  asserts no local template ever requires a key.
- **Keys live in `narrator_data/narrator_llm.json`, not the settings
  file** -- settings get copied between machines and pasted into bug
  reports. Written atomically, `chmod 600` where the OS supports it.
  `safe_providers()` masks keys (`sk-…2345`); the full key is never
  returned to an interface, because a key echoed into a browser DOM is a
  key in screenshots. Saving with a blank key KEEPS the stored one, so a
  UI can send the masked value back harmlessly.
- Every failure mode gets its own message rather than a generic one: 401
  names the key, 404 says "usually the model name is wrong", 429 says rate
  limited, a non-compatible reply says so explicitly, and an unreachable
  local endpoint asks whether the server is running.

**Staged verification, per Routh's design.** `verify()` runs checks in the
order that isolates a fault and stops at the first failure: *Endpoint
configured → Reachable → Key accepted → Model available → Model answers →
Follows the script format*. The last stage is the valuable one: it asks
the model for two `<PersonN>` turns and reports whether it complied.
**A model that answers but ignores the format fails only that stage** --
caught in seconds, rather than discovered after a twenty-minute
generation produces an unparseable script. "Model available" compares
against the endpoint's own `/models` list and shows what IS on offer;
endpoints that don't implement `/models` still verify.

Tested against a **real HTTP server implementing the OpenAI protocol**
(`mockllm.py`), not mocks -- real providers can't be reached from Claude's
sandbox and would need keys. Switchable per instance so bad-key,
missing-model, rate-limited, non-compatible and ignores-format are each
exercised over a socket.

### The dialogue pipeline — DONE 2026-09-08

**`narrator/dialogue.py`**, built to the shape the research recommended.

- `split_sections()` prefers the **document's own headings** -- an
  author's structure beats an inferred one and costs no tokens. Falls
  back to paragraph packing, then to sentence-splitting (reusing
  `documents.split_sentences`), then to a hard cut.
- `build_outline()` likewise uses existing headings when there are three
  or more, and only asks the model when there is nothing to go on.
- `generate_script()` walks section by section carrying **the outline, a
  rolling summary of what has been covered, and who spoke last**. Each
  section gets position-specific staging: the first greets once, the last
  says goodbye and must NOT re-greet, the middle ones are explicitly told
  not to say "picking up where we left off". Later sections are told the
  previous speaker so alternation survives section boundaries.
- `dedupe_turns()` handles the failure mode the research named: **chunked
  generation repeats points at section level**, far enough apart that a
  model's own repetition penalty never sees it. Compares content-word
  fingerprints with a Jaccard threshold. **Short turns are never dropped**
  -- "Right, exactly." is not a repeated point, and removing
  acknowledgements would make the conversation lurch.
- `render_plan()` maps turns onto two voices; consecutive same-speaker
  turns are already merged, so each entry is one continuous piece of
  speech -- exactly the unit the engines render and `_join_chunk_wavs`
  joins.

**Two real bugs found by testing.** A single paragraph longer than
`max_chars` never split, so prose with no blank lines (common in converted
documents) would have blown straight past the context window -- now split
on sentence boundaries with a hard-cut fallback for a pathological single
sentence. And cancelling before any work raised "the model may not be
following the required format", which is both wrong and alarming; an
immediate cancel now returns a clean empty result with `cancelled: True`.

Tested against `mockllm.py` taught to behave like a dialogue model --
echoing its section marker so stitching, alternation and repetition are
checked against output that actually varies, with switchable modes for
repeats-itself, ignores-the-format, emits-two-turns-in-a-row and
wraps-everything-in-preamble.

### Rendering a dialogue, and the endpoints — DONE 2026-09-08

**`session.render_dialogue()`** turns a script into audio with a voice per
speaker. The important decision: **one engine call per VOICE, not per
turn.** Rendering each line as it comes would reload the model between
every line -- several gigabytes per turn for Qwen3, completely
impractical. Instead every Person1 line goes through in one call, every
Person2 line in another, and the pieces are interleaved back into
conversation order. Two model loads for an episode of any length.

The result is deliberately the same shape an engine returns, so
`finalize_render`, the manifest, the timeline and publishing all work on a
dialogue exactly as on a narration -- one turn becomes one segment, which
is also the right unit for "re-record this line". `audio.join_pieces()`
does the interleaving using the same trimming and controlled-gap rules as
the narration path, going through ffmpeg so it does not care whether the
engine wrote WAV or MP3. A test asserts durations + gaps reconstruct the
master exactly, so subtitles cannot drift.

Guard worth keeping: if an engine returns a different number of pieces
than there were turns, it **refuses** rather than silently mis-ordering
the conversation.

**Endpoints:** `/api/llm/providers` (GET/POST/DELETE, keys masked),
`/api/llm/verify`, `/api/dialogue/script`, `/api/dialogue/render`, and
`/api/dialogue/signoff` -- the last being Routh's final stage: it renders
a short two-voice sample so setup ends with something you can listen to
rather than a green tick.

**Integration bug found by testing, and the kind to watch for.**
`read_text_file` runs the narration cleaning pipeline, which STRIPS
headings. Feeding that to the dialogue pipeline produced a single
unsectioned blob and an outline invented from scratch -- plausible-looking
output that was quietly much worse. `dialogue.load_document()` now reads
with `keep_headings="markup"`, and the test asserts the log reports the
document's real section count rather than 1. Any future consumer that
wants document STRUCTURE must use this, not `read_text_file`.

**Still to build:** UI for all of it (desktop and web), and letting a
generated script be edited before rendering -- the turns are plain data
and `script_to_text()`/`parse_turns()` already round-trip, so this is a
text box and a re-parse rather than new machinery.

Local model suggestion stands: **Qwen3-14B** (Apache-2.0, ~9.5GB at
Q4_K_M, fits Routh's 12-16GB). On a 12GB card, KV cache at long context
can push a 9.5GB model over -- budget conservatively.

### Tests moved INTO the project — 2026-09-11

**The test suites were lost.** They lived in a scratch directory outside
the project and were cleared when the working environment reset; the
source survived only because it was packaged each session, and the tests
did not because they were not. Roughly 49 suites, gone. Nothing that was
built is affected -- the source is intact and current -- but every
"49 suites pass" claim made before this date rests on evidence that no
longer exists.

They now live in `tests/` inside the project, so they ship with every
package:

    cd tests
    python run_all.py            # everything
    python run_all.py --quick    # skips the network-dependent suite

`tests/stubs/` holds the stand-ins (kokoro, misaki, torch, and the rest)
so suites run with no GPU, no model downloads and no network.
`tests/mockllm.py` is a real HTTP server speaking the OpenAI protocol.

**Rebuilt so far: `test_audiogram.py`.** The rest need rebuilding, and the
sensible way is opportunistically -- whenever a module is next touched,
rebuild its suite first. Do not trust an untested module because it used
to be tested.

### Audiogram, second pass — 2026-09-11

From Routh's feedback after real use.

- **Layers instead of one style.** `show_bars` / `show_line` /
  `show_fill` combine freely, each with its own colour (`line_color`,
  `fill_color`, `fill_opacity`), plus `bar_width`. Both geometries
  support all three; the polar fill is drawn between the inner radius and
  the tips so the ring stays hollow. `active_layers()` translates a
  pre-toggle layout from its old `style` field rather than rendering
  nothing -- an old layout must keep looking the way it did.
- **Render estimates.** `estimate_render()` extrapolates from measurements
  on this machine (1080p ≈ 7s per second of audio, cost tracking pixels
  far more than bar count) and `describe_estimate()` reports a RANGE that
  says it is approximate. It scales with resolution, sampling rate and
  crop. The point is to warn someone off a nine-hour 4K render before
  they start it, not to be exact.
- **An ffmpeg fast path**, which is what Routh's own experiments were
  really pointing at. `build_ffmpeg_filter()` assembles a `showwaves`
  graph; `command_preview()` returns it as a copy-pasteable command; and
  `render_ffmpeg(filter_override=...)` runs a hand-written graph verbatim.
  **Routh's discovery is what makes polar possible here:**
  `v360=input=flat:output=fisheye:h_fov=360:v_fov=360` bends a linear
  waveform into a ring, which `showwaves` cannot do alone. `cas`, `gblur`
  and `tblend` are exposed as sharpen/blur/trail.
  Measured: 3s at 720p took **1.2s via ffmpeg vs 5.4s via the frame
  renderer -- about 5x**. The frame renderer stays, because ffmpeg cannot
  do pivots, formulas, layered fills or transparent overlays; the fast
  path produces an opaque video. Offer both, do not replace.

### Audiogram, third pass: motion preview and live readouts — 2026-09-11

- **`preview_clip()`** renders a few seconds so motion, smoothing and blur
  can actually be seen. Capped at `PREVIEW_MAX_SECONDS = 8` -- past that
  it stops being a preview and becomes a render you are waiting for.
  `render_overlay(max_seconds=)` gives the frame renderer the same
  ability. **Analysis still runs over the whole file** even for a
  preview, so level scaling matches a full render; a preview that
  normalised differently would be a lie.
- **`preview_reason()` picks the renderer and says why.** ffmpeg's fast
  path cannot draw a shaded fill, combined bars+line, per-layer colours,
  rotation or a formula, so a layout using any of those previews through
  the frame renderer instead. The dialog shows the sentence ("Will use
  the frame renderer -- a shaded fill is on"), so the choice never looks
  arbitrary and the preview is never faster by being wrong.
- **The dialog now has an editable ffmpeg command box.** It shows the
  exact command the fast path will run, updates as controls change
  (switching to polar makes `v360` appear), and a hand-written filter
  graph in the field below replaces the built one entirely -- clearing it
  restores the default. Directly serves the experiments Routh was already
  running by hand.
- **Live render estimate** beside the export controls, reacting to
  resolution, sampling rate, codec and crop.

**The bug behind "only half the variables update the preview".** The
derived readouts were refreshed at the START of the change handler,
before `cfg` was updated -- so they showed the previous state, one edit
behind, which reads exactly like "this control does nothing". They now
refresh after `cfg` is written, and every numeric row, toggle and colour
field triggers them. The GUI test asserts that switching to polar makes
`v360` appear in the shown command, which is the cheapest way to catch
this class of fault.

**Stub note:** the rebuilt kokoro stub yielded a plain object, but the
real `Result` **unpacks to (graphemes, phonemes, audio)** as well as
exposing attributes. Anything rebuilding these stubs must match both, or
`_run_kokoro_local` fails with "cannot unpack non-iterable".

### Audio source for the audiogram, and a measurement worth keeping — 2026-09-11

Routh proposed a workflow: convert audio to a lighter proxy (lower
bitrate, mono), drive the audiogram from that, and bring the full-quality
original into the editor -- expecting large render-time savings.

**Measured, and the saving is not there.** 30s of audio, frame renderer
at 640x360:

| source | size | analyse | full render |
| --- | --- | --- | --- |
| 24-bit 48kHz stereo WAV | 8.6 MB | 0.76s | 15.37s |
| 64kbps 22kHz mono MP3 | 0.2 MB | 0.23s | 15.05s |

Analysis is only ~5% of the work, so a proxy saves about half a second in
fifteen. On the ffmpeg fast path there is no saving at all (1.70s hifi vs
1.83s proxy -- the mp3 decode costs slightly more than it saves).

**What actually governs render time is pixels**, near-linearly:

| resolution | 30s of audio |
| --- | --- |
| 320x180 | 3.6s |
| 640x360 | 15.3s |
| 1280x720 | 50.0s |

So the levers that matter are **resolution, cropping and frame rate** --
all of which the estimate already reacts to. Do not repeat the proxy idea
as a speed optimisation; it is not one.

**But the underlying feature was worth building anyway**, for a different
reason: driving the audiogram from a *different* file than the video's
audio is genuinely useful -- a mono mixdown, a single stem, a music bed.
`cfg["audio_source"]` does that, with `resolve_audio_source()` checking
existence UP FRONT (a stale path is reported while it can be corrected,
not several minutes into a job) and `source_note()` warning plainly when
the chosen file is not the selected take, since that is an easy thing to
forget you did.

### narrator/ffgram.py — the ffmpeg audiogram builder, 2026-09-11

**The context that changes the priority.** Routh's Reactor/Lua fuse in
DaVinci Resolve takes **8-24 hours** for a 30-60 minute episode. Measured
here at 1920x1080 on 60s of audio:

| renderer | speed | 60-min episode |
| --- | --- | --- |
| Reactor Lua fuse (Routh's measurement) | — | 8-24 hours |
| `audiogram.py` frame renderer | 3.63x realtime | 3.6 hours |
| ffmpeg showwaves, default preset | 0.72x realtime | 43 min |
| ffmpeg, ultrafast + render-small-and-scale + 24fps | 0.15x realtime | **9 min** |

So the frame renderer is NOT a practical default at length -- it is for
the things ffmpeg cannot draw (pivots, formulas, layered fills, real
transparency). ffmpeg is the working path.

**What actually makes it fast, measured, in order:**

| change | 60s at 1080p |
| --- | --- |
| baseline (`-preset medium`) | 43.0s |
| render 1920x360 then `scale` (Routh's own trick) | 36.2s |
| 24fps instead of 30 | 33.6s |
| **`-preset ultrafast`** | **15.6s** |
| all three together | 9.1s |

**The encoder preset dominates -- more than resolution or the visualiser.**
That is not obvious, so `describe_estimate()` volunteers it: choose a slow
preset and it tells you what ultrafast would cost instead. The trade is
file size (17-25 MB vs 1.3 MB for 60s), which is irrelevant when the file
goes straight into an editor and gets re-encoded anyway.

**The module.** A graph is structured data -- a source visualiser, an
ordered effect stack, encoder settings -- so it can be built, explained,
estimated and run, and any hand-written graph still replaces it entirely.

- 4 visualisers (`showwaves`, `showfreqs`, `showspectrum`,
  `avectorscope`) and 8 effects (`scale`, `fisheye`, `cas`, `gblur`,
  `tblend`, `hue`, `pad`, `colorkey`), each option carrying its real
  range and a one-line description.
- `explain()` says what each stage does in order, including warning that
  H.264 has no transparency.
- Unknown options are dropped rather than passed to ffmpeg, so a stale
  saved setting cannot break the command.
- A broken graph surfaces **ffmpeg's own error text**, which is far more
  useful than any summary.

**Two facts found only by running every option through real ffmpeg**, and
the reason the test does exactly that:
- `showspectrum` has **no `rate` option** — passing `r=` makes ffmpeg
  reject the entire graph. Sources now declare `supports_rate`.
- `v360` fisheye **changes the frame's proportions**: 720x720 in gives
  360x720 out. `w`/`h` are now set explicitly, or both the output size
  and the render estimate are wrong.

**The builder UI — DONE.** Tools -> Audiogram command builder...
Every control is generated from `SOURCES` and `EFFECTS`, so adding an
option to those registries makes it appear with the right control, range
and description; nothing is hand-written and nothing can drift from what
the code accepts. Visualiser picker (options rebuild when it changes, and
do not carry the previous one's settings across), an ordered effect stack
with add/remove/up/down, encoder and preset, the live command, a
plain-language explanation of each stage, a preset-aware time estimate,
a 5-second preview and a full render. A hand-written graph in the field
below replaces everything above it.

### Exporting the analysis — 2026-09-11

`audiogram.export_analysis()` writes the numeric middle of the pipeline:
per frame, the overall level plus bass/mid/treble (and every band in the
"bands" form), as CSV or JSON. That lets a Fusion setup or an After
Effects expression be driven by **the same curve the audiogram draws**,
without redoing the analysis or having to match it -- a test asserts an
exported value equals what a formula sees in the renderer at the same
frame.

Routh asked about MIDI. Worth keeping the distinction: MIDI is symbolic
note data (pitch, velocity, note on/off), and getting it from a mixed
recording is pitch transcription -- a different problem that produces
nonsense on speech. The continuous curve is what animation software
actually keys off, so that is what is exported. The CSV carries a comment
line stating what the numbers are and that they are normalised to the
file's own peak, because a bare column of floats is unreadable six months
later.

### The dialogue interface — 2026-09-11

**The gap this closes:** the whole two-host dialogue feature — providers,
script generation, rendering — had a backend, endpoints and tests, but
**no interface at all**. It was unreachable except by calling the API by
hand, which means it was effectively unbuilt from a user's point of view.
Worth watching for: a feature with passing tests and no surface is still
not a feature.

`web/src/Providers.jsx` and `web/src/Dialogue.jsx`.

- Providers: add from a template, edit, remove, and **Verify**, which
  shows all five stages with a tick or cross each and the reason. The key
  field is a password input that shows the mask; because the server keeps
  the stored key when it receives a blank one, sending the mask back is
  harmless — a test asserts verification still passes after re-saving
  with a blank key.
- Dialogue: pick a document, pick a provider, set the host names and
  section length, generate, then **edit the script by hand** before
  rendering. The turns round-trip through their tagged text form, so the
  textarea is the editor — a test rewrites a line and confirms the edited
  version is what renders. Given the whole feature depends on script
  quality, fixing a line yourself beats any amount of prompt tuning.
- Voice per host, with a warning when both are set to the same one (the
  conversation would sound like one person talking to themselves), a
  short **Hear a sample** before committing, and a full render.

Verified through a real server process: the built bundle actually
contains the dialogue interface, and the provider endpoints answer over
HTTP.

### Component and engine install reach the web UI — 2026-09-11

Another one-sided gap, in the direction that mattered: **web could see
what was installed but not install anything.** The "greyed out with a
download button" story built for the desktop app -- exactly what Routh
asked for two sessions ago -- had no web equivalent, and Components was
read-only there.

`POST /api/components/install` and `POST /api/engines/{name}/install`,
both as jobs (progress, cancellation, the same job list everything else
uses -- a multi-gigabyte engine download is precisely the kind of thing
that needs visible progress, not a spinner). Asking to auto-install an
EXTERNAL tool (ffmpeg, pandoc) is refused with the real reason and a link
to its download page, rather than pretending it's the same kind of
install as a pip package.

`Components.jsx` lists everything with its size, licence, and what it
unlocks; an uninstalled piece gets an Install button (pip components,
engines) or a download-page link (external tools). Verified with a REAL
pip install through the API (installed and then confirmed present in the
component report), and an engine install with `create_environment`
stubbed so the test doesn't pull several gigabytes -- it asserts the
stage log reached the worker and the engine list reflects the install
immediately, with no restart, because the probe cache is cleared exactly
as the desktop path does.

### Solid chroma-key background — ffgram + the drop tool, 2026-09-11

Routh: real alpha would be nice but a solid keyable colour is enough, and
simpler to rely on ("as long as the background is a solid color I can
just chroma key it out").

Both `narrator/ffgram.py` and `tools/audiogrammify.sh` gained a solid
background option: `showwaves` paints only the waveform line, so the
composite is `color=c=<hex>` UNDER the waveform via `overlay`, not a
colour applied to it.

**A real bug found only by actually running an unbounded render, not by
reading the command.** `-shortest` as a plain ffmpeg output flag does
NOT reliably bound this specific graph shape. Every earlier test used
`seconds=N` (an explicit `-t` limit), which masked the flag not working
at all -- discovered only when writing a test that renders with NO
`seconds` limit and a real subprocess timeout: it ran to **37.9s against
a 4.0s source** before being killed. The fix, confirmed the same way, is
`overlay`'s OWN `shortest=1` parameter, which correctly stopped the
identical graph at 4.07s-4.1s across three separate confirmations (Python
builder, shell script, and a bare ffmpeg command run directly). Both
scripts now use `overlay=format=auto:shortest=1`; the output-level
`-shortest` flag is kept as a second line of defence but is not what
actually does the job.

**Process note worth repeating:** this is the second time in this
project that "the command looks right" and "the command behaves right"
diverged, and both times it was caught by actually executing something
with a real timeout rather than inspecting the generated string. A test
that bounds every render with `seconds=` cannot catch a bug in the thing
that is supposed to bound an UNBOUNDED render -- which is exactly the
condition a real drag-and-drop use hits. `test_ffgram.py`'s K3b test
exists specifically to keep exercising that unbounded path.

The builder dialog gained a **Background** picker (plain black / solid
green / solid magenta / custom colour) with the same reasoning available
on screen. `tools/audiogrammify.sh` defaults to green now, with a
`BACKGROUND=""` knob to go back to plain black.

### Auditing for the same bug class elsewhere — 2026-09-12

Searched the codebase for other `-shortest`/unbounded-source patterns
after the ffgram fix. One match: `audio.build_video()`'s waveform overlay
-- structurally the same shape (a `-loop 1` still image, unbounded on its
own, composited with an audio-driven waveform via `overlay`, output
flag `-shortest`).

**It was not actually broken, but only for a reason that could break
later.** Isolated and tested directly against real ffmpeg: `-shortest` as
a bare output flag only bounds the render when the SHORTER stream is
separately mapped into the output -- an input merely being present is not
enough. `build_video` happens to `-map "1:a"` (the real audio) alongside
the video, which is what was saving it. Confirmed the counterfactual
directly: the identical filter graph, exported video-only (`-an`, no
audio map -- e.g. what a future "video without audio" option might do),
ran a 3-second source out to nearly 4 minutes before being killed by a
timeout.

Hardened with the same fix as ffgram: `overlay=...:shortest=1` on the
filter itself, which bounds the render regardless of what gets mapped
downstream, with a comment explaining why the flag alone was never
actually sufficient. `tests/test_build_video.py` checks four cases
against real ffmpeg and real timeouts: the actual function (bounded
correctly), the filter-level fix alone with no audio mapped at all
(still bounded), the WITHOUT-fix video-only shape (asserted to still
hang, specifically so this test cannot go stale silently if ffmpeg's own
behaviour ever changes), and the fix with audio mapped too (bounded
either way).

**The pattern worth generalising:** ffmpeg's `-shortest` output flag is
not a safe default assumption for any graph that composites a
naturally-unbounded source (a colour, a looped still image, a looped
video) against a real-length stream. The filter's own `shortest=1`
parameter -- available on `overlay` and worth checking for on any other
compositing filter used here in future -- is the reliable guard.

### Audio8-TTS-Preview-0.6b: a second, lighter cloning engine — 2026-09-12

Routh's friend mentioned this model
(`Edge0/Audio8-TTS-Preview-0.6b`, a mirror of `Audio8/Audio8-TTS-Preview-0.6b`);
researched it properly before touching code, since the sandbox cannot
reach huggingface.co directly. Confirmed real, actively maintained,
601M params, Apache-2.0 for the 0.6B checkpoint specifically (its 0.1B
sibling uses a separate revenue-capped licence -- do not casually
"upgrade" the repo pin without re-checking that). ~1-1.3 GB VRAM,
custom `arktts` code needing `trust_remote_code=True` and
`transformers>=4.57.0,<5` (5.x is confirmed to produce silent
all-zero output). Independent testing rates it "okay/good-ish" --
decent for its size, not top-tier, with a real known issue: unstable
end-of-speech ("runaway") generation.

**Decision: add as a third, opt-in cloning engine, isolated in its
own environment like Qwen3, never a narration default.** Kokoro stays
the default narrator.

What this reused rather than rebuilt: `clone_voice_from_recording()`
(now takes `engine_tag`/`min_seconds` so Qwen3 and Audio8 share one
function instead of two near-duplicates), the cross-process worker
pattern (`_run_via_worker`/`worker_main`), the `VOICES_DIR` +
`voice.json` storage shape, and the narration path's sentence
splitter (for chunking under Audio8's 150-char context cap).

What's new: `narrator/audio8_engine.py` -- `_audio8_chunks()` (sentence-
bounded splitting under 150 chars, handles an oversized single sentence
and even a no-space wall of text), `_plausible_duration()` (screens a
rendered piece's length against its text -- catches both truncation
and the runaway-generation risk the research flagged), `_run_audio8_local()`
(per-sentence retry loop, up to `AUDIO8_MAX_RETRIES` retries, logs each
retry's reason, keeps the last attempt with an explicit "gave up" line
if it never becomes plausible rather than looping forever or silently
shipping bad audio). `have_audio8()` lives in `config.py`, matching
`have_qwen()`'s exact convention (checks the dedicated environment via
`external_python`, not a bare package import). Registered in
`pipeline.ENGINES`, `setup_engines.ENGINE_SPECS` (own venv, pinned
transformers), and `components.COMPONENTS` (licence explicitly scoped
to the 0.6B checkpoint).

**A real gap this surfaced, fixed same session:** Voice Studio listed
every saved voice with no indication of which engine cloned it -- now
that two engines can clone, picking the wrong one for the active
engine would fail deep inside a render rather than at selection. Added
an `engine` field to every `saved_voices()` entry (defaults to `"qwen3"`
for pre-existing voices, correctly, since that's the only engine that
made them) and a `[qwen3]`/`[audio8]` tag on each row in Voice Studio's
list. **Not yet done:** the web UI's `Dialogue.jsx` voice picker only
offers each engine's fixed preset list, not saved cloned voices at
all -- so it doesn't yet hit this collision, but it also can't offer
either engine's clones. Pre-existing gap, not introduced by this
change; left as a known limitation rather than scope-creeping a new
picker into this session.

Test stubs: `tests/stubs/transformers/` (narrow -- `AutoModel`/
`AutoProcessor` with exactly the call shape `audio8_engine.py` uses,
plus a `set_stub_mode()` switch for normal/too-short/too-long/silent/
recovers-on-retry output, to exercise the retry logic deterministically
rather than just checking the happy path). `test_audio8.py`, 17
assertions, all passing -- registration, chunking (normal/oversized/
no-spaces), plausibility screening, cloning via the shared function
with engine tagging, `saved_voices()` exposure, retry-recovers and
retry-exhausted-gives-up cases, caching, and both error paths (missing
voice, missing reference transcript). Full regression: 8/8 suites
passing.

**"Pin it" per Routh's instruction:** Audio8-specific work stops here.
Routh also raised marking the current state as a version milestone;
`pyproject.toml` already shows `version = "2.0"` from before this
session, so what exactly Routh wants (a reset, a separate milestone
marker, or something else) needs clarifying before any versioning
action is taken -- not yet done.

### Batch conversion in the Convert dialog — 2026-09-12

Routh hit a real limitation: converting many files (.m4a/.mp3/.flac/etc.
to .wav) one at a time for audiogram generation, closing and reopening
the dialog for each. Two asks: shift/ctrl-select several files at open
and have them all convert with one settings pass, and a "Browse" button
inside the dialog to add more without closing it.

**Both added.** The opening picker is now `askopenfilenames` (plural),
so a multi-select at open populates a list rather than one filename.
The dialog holds a `sources` list, shown in a Listbox with running
total duration/size; "Browse... (add more)" appends without closing,
"Remove selected" trims it. `do_convert()` now loops the list: same
settings (format/quality/rate/depth/channels/split) applied to every
file, one after another, each logged with a `[i/n]` prefix. One file
failing does not abort the batch -- the loop continues, collects
failures separately from successes, and the status label reports both
counts plainly (e.g. "3/4 converted, 1 failed -- badfile.wav: ...")
rather than only reporting the last file's outcome or silently eating
a failure. Splitting-into-parts still works per file, unchanged.

The standalone "Quick editing WAV..." menu item was deliberately left
alone -- confirmed it has its own local `src` and shares no state with
the dialog above; it's a different, intentionally single-file, minimal
tool for a different use case, not something this request touched.

`tests/gui_smoke_convert.py` (new): drives the real dialog headlessly
via a monkeypatched `askopenfilenames` (first call returns 2 files,
matching a real multi-select; a later call simulates Browse-add), plus
a deliberately-invalid file mixed into the batch to check the
partial-failure path specifically, not just the happy path. Confirms:
multi-select at open populates the list, Browse-add appends without
closing the dialog, the batch converts the good files, and the one bad
file is reported without blocking the rest. Full regression: 9/9
suites passing.

Noted but not acted on: Routh's message also mentioned ".midi" as a
possible target alongside .wav -- audio-to-MIDI is pitch transcription,
a different problem from format conversion (this came up before, in
the audiogram export work: `export_analysis()` does level/frequency-band
CSV/JSON, explicitly not MIDI, for the same reason). Assumed Routh meant
WAV/FLAC/etc. and not literal MIDI export; flagging here in case that
assumption is wrong.

### Dialogue editor: per-turn structure + inline refine — 2026-09-12/13

Routh's ask: a Copilot/Google-Docs-style inline edit -- select a phrase,
right-click, a floating micro-prompt appears focused beside the cursor,
type how it should change, Enter applies it in place.

The web dialogue script was a single flat textarea of tagged text
(`<Person1>...</Person1>`). A right-click-a-selection popup needs to know
WHICH turn and WHICH span within it was selected -- unanswerable from a
re-parse of one big blob on every keystroke. Rebuilt as a structured
turn list instead (`web/src/TurnEditor.jsx`, new): stable per-turn ids,
one textbox per turn, swap-speaker/delete/insert-line included as natural
extras once turns are addressable individually. Tagged text is now only
the interchange format at the generate/render API boundaries.

Backend: `dialogue.refine_selection()` (new) -- takes the selected span,
its surrounding text WITHIN the same turn (for a seam that reads
naturally once spliced back in), the instruction, the speaker, and
optional neighboring turns as context-only (never rewritten). Marks the
span with `[[[...]]]` in the prompt so the model rewrites only that part.
Cleans stray quotes/brackets from the reply -- **found and fixed a real
bug here**: the cleanup order was wrong and left brackets in place when a
reply came back nested as `"[text]"` (quotes outer, brackets inner);
fixed to peel either wrapper in a loop until a pass changes nothing,
rather than assuming one fixed nesting order. `POST /api/dialogue/refine`
is synchronous, not a background job -- meant to feel instant like an
inline editor, not something watched through a job log.

`tests/test_dialogue_refine.py` (new, 7 assertions) + extended
`tests/test_webdialogue.py` (4 more, through the real HTTP layer) +
extended `tests/mockllm.py` with a refine-aware response branch and
messy/empty reply modes to exercise the cleanup and validation paths
for real, not just the happy path.

### Web dialogue voice picker: closing the cloned-voice gap — 2026-09-13

Flagged as a known gap in the last Audio8 entry: the web dialogue
editor's host-voice pickers only ever offered each engine's fixed preset
list, never saved clones from Qwen3 or Audio8 -- so cloned voices
couldn't be used in a web-generated dialogue at all.

New `GET /api/voices` endpoint exposes `saved_voices()` over the web API
for the first time (previously desktop-only). `Dialogue.jsx`'s voice-
loading effect now merges each engine's presets with that SAME engine's
own saved clones (`engine=qwen3` or `engine=audio8`) -- deliberately
filtered per engine, not offering every clone in the library, since a
voice cloned for one engine fails if handed to the other's renderer
(the same class of bug the desktop Voice studio tagging fixed last
entry). `tests/test_webdialogue.py` extended with 4 more assertions
confirming the engine-filtering actually excludes the wrong engine's
clone, not just that the endpoint returns something.

### Voice studio ported to the web, full parity — 2026-09-13

Per Routh's sequencing choice (voice studio, then timeline; full parity,
no rush), this ports the desktop's Voice studio dialog
(`narrator/ui.py::open_voice_studio`, ~373 lines) to the web UI. All
four of its capabilities, all backed by the SAME functions the desktop
calls (nothing new at the engine layer -- this is entirely "expose it
over HTTP and build the React UI"):

- **List/rename/delete/play** -- `saved_voices()`, `rename_voice()`,
  `delete_voice()` exposed via `/api/voices` (extended with a `full=true`
  mode returning every field Voice studio's management view needs --
  description, take, created, reference availability -- vs. the trimmed
  `{id, engine, kind, label}` shape the dialogue pickers use), plus new
  `/api/voices/rename`, `/api/voices/delete`.
- **Audition** -- `ensure_qwen_voice()` behind `POST /api/voices/audition`,
  a background job (designing a new voice takes real time on first use).
- **Clone from a recording** -- `clone_voice_from_recording()` behind
  `POST /api/voices/clone`, a NEW mechanism for this app: a real
  multipart file upload, not a server-side path picker. Routh's explicit
  choice over reusing FileBrowser, specifically so the browser and the
  machine running Narrator don't have to be the same computer. Required
  adding `python-multipart` as a documented dependency (`__main__`'s
  install-hint message updated) and fixing `web/src/api.js`'s shared
  `call()` helper, which forced `Content-Type: application/json`
  unconditionally -- broke multipart bodies, since the browser needs to
  set its own boundary. Works for both Qwen3 and Audio8 via an `engine=`
  form field, reusing the SAME `clone_voice_from_recording(engine_tag=)`
  both engines already shared from the Audio8 integration.
- **CustomVoice presets** -- `fetch_qwen_custom_speakers()` (a background
  job -- downloads the CustomVoice model itself, several GB, first time)
  behind `POST /api/voices/custom-speakers/fetch`, plus
  `qwen_custom_speakers()`, `save_custom_voice_preset()`,
  `delete_custom_voice_preset()` behind matching routes.
- **Reference clip playback** -- `GET /api/voices/reference/{token}`
  streams the WAV back, `token` resolved against `VOICES_DIR` and
  checked to stay inside it (a path-traversal token is refused, tested
  directly). An `<audio>` element can't send the app's auth header the
  way every other request does, so the client fetches the clip as a
  blob through the normal authed call() and hands the `<audio>` tag an
  object URL, rather than loosening the auth dependency for one route.

**Scope decision, not a gap:** the desktop dialog's "Use in Voice tab"
button has no clean web equivalent -- the web render form's `voice`
field lives in `SettingsForm.jsx`'s `cfg` state, with no existing prop
path from `VoiceStudio.jsx` (a separate page section) into it. Left out
rather than forcing an awkward cross-component callback; Voice studio on
web is the management surface (create/audition/label/delete), and the
render form's own voice pickers (already engine-aware, from the prior
entry) are how a voice actually gets selected for a render.

New `tests/qwen_tts` stub (narrow: `generate_voice_design()` and
`get_supported_speakers()`, exactly what audition and CustomVoice-fetch
call) -- **this closed a real pre-existing test gap**: nothing had ever
exercised those two code paths before, since they run in-process rather
than through the already-stubbed worker/qwen3-render path.
`tests/test_webvoices.py` (new, 24 assertions, all passing on first real
run): empty state, audition end-to-end, rename (including a clean 400
for a nonexistent voice), upload-and-clone for both engines, a
too-short-recording rejection through the FULL multipart path (not just
the unit-level function), path-traversal and missing-reference 404/400s
on the playback route, delete, CustomVoice fetch/cache/save/delete.

Full regression: 11/11 suites passing. `npm run build` verified after
every change (module count and bundle hash both confirmed to actually
change, catching one early mistake where a new component wasn't yet
imported anywhere so Vite silently skipped compiling it).

**Version bumped 2.0 -> 2.1** per Routh's call (already-existing v2.0,
this arc's work -- Audio8 + batch convert + dialogue editor + voice
studio port -- becomes 2.1) in `pyproject.toml` and `narrator/__init__.py`.

**Next: Timeline editor port to web** (~306 lines on desktop,
`narrator/ui.py::open_timeline_editor`), per Routh's stated sequence.
Not yet started.

### Timeline editor ported to the web, full parity — 2026-09-13

Second half of Routh's sequence (voice studio done, then timeline).
Ports `narrator/ui.py::open_timeline_editor` (~306 lines): a waveform of
a finished take with every sentence marked, click to jump the playhead
and select the sentence under it, drag to select a range, the full
sentence list synced to the same selection, per-word Kokoro pronunciation
detail, and re-recording one sentence in place without touching the rest
of the file.

`load_manifest()` already reconstructs a complete take object (cfg,
folder, stem, engine, voice, chunk paths, segments -- everything
`resplice_segment()` needs) purely from a manifest file on disk, with NO
dependency on any in-process app state -- confirmed by reading it before
designing anything. That's the whole API surface: every new endpoint
takes a `manifest` path and does real work from there, the exact same
way the desktop's "Open a take..." override path already does.
`/api/takes` extended to include each take's manifest path, computed
server-side via the real `manifest_path()` function (folder+stem) rather
than guessed client-side from a naming convention.

New endpoints, all thin wrappers over existing engine-layer functions
(nothing new at that layer -- same shape as the Voice studio port):
`GET /api/timeline?manifest=` (flattened sentence list + waveform via
`flatten_take()`+`envelope()`, one call gets everything needed to draw),
`GET /api/timeline/span?manifest=&start=&end=` (extract a range as
playable audio via `extract_span()`), `POST /api/timeline/resplice`
(re-record one sentence via `resplice_segment()`, a background job since
it renders through the real engine and rebuilds the master file),
`GET /api/timeline/words?manifest=&text=` (Kokoro-only per-word detail
via `kokoro_words_phonemes()`).

Frontend: `TimelineEditor.jsx` (new) uses an SVG canvas, not HTML5
`<canvas>` -- no canvas precedent existed anywhere in this app, and SVG
gives ordinary React elements with per-shape pointer handlers, fitting
the codebase's declarative style rather than an imperative draw loop.
Mirrors the desktop's `draw()`/`on_press`/`on_move`/`on_release`/
`select_index` logic directly: click-vs-drag distinguished by movement
threshold, waveform bars + sentence-boundary lines + selection rectangle
+ current-sentence outline + playhead all as SVG shapes recomputed from
state on every render, same as the desktop's full-redraw-per-frame
approach. Span/reference playback reuses the blob-URL pattern from the
Voice studio port (an `<audio>` element can't send the app's auth
header, so the clip is fetched through the normal authed request and
handed to the element as an object URL).

**Scope decision, not a gap:** the desktop's "Edit a word's
pronunciation" opens a modal dialog embedded in the timeline itself.
Web already has a full, separately-tested Pronunciation page section
with its own API -- rather than duplicate that editor inside the
timeline, or wire an awkward cross-component deep-link into a component
that takes no such prop today, the web timeline shows the word/phoneme
list read-only with a note pointing at the Pronunciation section by
name. Consistent with the same kind of call made for Voice studio's
"Use in Voice tab" in the previous entry.

New `tests/test_webtimeline.py` (12 assertions, all passing on first
real run) -- deliberately end-to-end rather than unit-level: drives a
REAL render through `/api/render` first (Kokoro, a real multi-sentence
document), then opens the resulting manifest through every new endpoint,
including a real resplice that actually re-renders a sentence and
rebuilds the take, verified by reopening the timeline afterward and
confirming the sentence text actually changed (not just that the job
reported success). Covers the 404 paths (missing manifest, both on
timeline-open and on resplice) and the empty-replacement-text guard.

Full regression: 12/12 suites passing. `npm run build` verified after
every change (46 modules now, up from 45, confirming TimelineEditor.jsx
is actually being compiled).

**Both items in Routh's stated web-porting sequence are now done**
(voice studio, then timeline). Remaining desktop-only surfaces per the
earlier parity note: the audiogram layout dialog (~605 lines, the
largest of the three) and engine-setup-wizard UI polish -- neither
started, no committed order yet.

### Audiogram dialog ported to the web, full parity — 2026-09-13

Third and last of the desktop-only surfaces from the parity list, per
Routh's go-ahead ("not a bad time for the audiogram UI"). Ports
`narrator/ui.py::open_audiogram_dialog` (~605 lines, the largest of the
three) -- live preview against the background image, layout guides,
shape/position/appearance controls, an expression/formula system for
animating values over time, chroma-key-aware export, motion preview,
and the ffmpeg command box with a hand-edit override.

**The one design principle worth stating plainly, carried over
deliberately:** the desktop dialog's own docstring says the preview is
"drawn by the REAL renderer, not a sketch of it, so the mockup can't
disagree with the output." That governed every design choice here.
`draw_frame()` returns a PIL image -- not callable from the browser --
so rather than reimplement the waveform drawing in JS (canvas or SVG)
and risk it drifting from the real renderer over time, the preview is a
PNG rendered server-side by the SAME `draw_frame()` function real
exports use, fetched fresh (debounced) on every settings change and
shown as an `<img>`. The layout guide overlay (dashed box / centre dot /
pivot cross) IS drawn client-side as SVG, but from `layout()`'s real
pixel numbers fetched from the server -- so the guides can't drift from
where the waveform actually lands either, even though they're drawn in
the browser. Nothing about the audiogram's actual geometry or rendering
was reimplemented; only the guide *decoration* is client-side, and it's
fed real numbers.

New endpoints, again thin wrappers over existing pure `audiogram.py`
functions (no new engine-layer logic): `GET /api/audiogram/defaults`
(full field set + defaults + animatable names + codec list, one call so
the client never hardcodes any of this), `GET /api/audiogram/source`
(resolve_audio_source's precedence note, with a `warning` flag for the
"NOT the take"/MISSING cases), `POST /api/audiogram/layout` (real pixel
geometry via `layout()`), `POST /api/audiogram/preview.png` (the real
PNG via `draw_frame()` against the same synthetic demo sine-wave values
the desktop's still preview uses -- no real audio file needs to exist
yet), `GET /api/audiogram/command` (the real ffmpeg command text, with
an optional `filter_override`), `GET /api/audiogram/estimate` (real
render time/size estimate for the given take's actual duration),
`GET /api/audiogram/preview-reason` (why the fast path vs. frame
renderer will be used), `POST /api/audiogram/preview-motion` (a
background job -- a real few-second moving clip), `POST
/api/audiogram/export` (a background job -- bakes the full transparent
overlay, and persists the layout as the new saved default, matching the
desktop's implicit save-on-export). Also added
`GET /api/expressions/reference` and `POST /api/expressions/validate`
for the formula autocomplete/validation, exposing `expressions.py`'s
existing pure functions.

A design note worth keeping: `/api/takes` already had to grow a
`manifest` field for the Timeline port two entries back -- the
audiogram endpoints reuse that same field (there is no separate
in-memory "selected take" concept on the web the way the desktop's
Publish dropdown provides; the client just passes whichever take's
manifest it wants).

Frontend: `AudiogramEditor.jsx` (new, the largest single component
added this arc) -- `ShapeSection`/`PositionSection`/`AppearanceSection`
mirror the desktop's three `LabelFrame` groupings field-for-field;
`EffectsSection` reimplements the formula editor's filter-as-you-type
autocomplete and live validation against the real backend, matching the
desktop's `fx_on_type`/`fx_refresh_reference` behaviour; `CommandSection`
shows the live command text and feeds a hand-edited filter override back
into cfg the same way `filter_var.trace_add` does on desktop;
`ExportSection` and `MotionSection` are background-job forms following
the same `JobLog` pattern used everywhere else in the web app. All
settings changes are debounced (150-200ms) before triggering a server
round-trip, since every keystroke on a spinbox would otherwise fire a
preview re-render or a command re-fetch per character.

Full regression: 13/13 suites passing, including a new
`tests/test_webaudiogram.py` (17 assertions) that drives a REAL render
first, then exercises every endpoint against it -- notably confirming a
`bars` change in the cfg actually changes the returned PNG's bytes (not
just that a 200 comes back), and that both the motion-preview and
export background jobs produce real playable/composable files, not just
a job that reports "done." `npm run build` verified after every change
(47 modules, up from 46, confirming AudiogramEditor.jsx is genuinely
compiled, not just present but unreferenced).

**All three items from the desktop-only parity list are now on the web
at full feature parity: Voice studio, Timeline editor, Audiogram.**
Remaining desktop-only surface per the original note: engine-setup-
wizard UI polish -- not started, no committed priority.

### Investigating "engine setup wizard polish", and the one real gap — 2026-09-13

While Routh tested the last few sessions' work, picked up the one
remaining item from the original desktop-parity note: "engine-setup-
wizard UI polish." Read the actual desktop code before assuming what it
meant -- it isn't a separate wizard at all, it's `open_preferences_dialog`
(~440 lines, three tabs: Engines, Podcast, Intro/outro), and the "wizard"
label was an earlier loose paraphrase, not the dialog's real name.

Checked each tab's actual web coverage before touching anything:
- **Podcast tab**: already fully covered -- `Publish.jsx`'s
  `ChannelSettings` already hits the same `/api/podcast` endpoints.
- **Intro/outro**: already covered, just in a different (arguably
  better) place -- `intro_audio`/`outro_audio` are schema fields in
  `render_config.py`, and `SettingsForm.jsx` is explicitly
  schema-generated ("never hand-written"), so they already render
  automatically in the main render form. Desktop treats them as one
  global pair set once in Preferences; web treats them as an ordinary
  per-render field. Functionally equivalent, not a gap.
- **Engine environments**: install itself was already fully covered by
  `Components.jsx` (status, "Download and set up", background job) --
  but the "Environments folder" override (point at an older Narrator
  install to reuse `kokoro-env`/`qwen3-env` instead of re-downloading
  several GB) had NO web coverage at all. This was the one real gap.

Added `POST /api/engines/env-root` -- its own endpoint rather than
routing through the generic `/api/settings` PATCH, because setting it
must also call `forget_engine_probes()` (already existed, already used
elsewhere for the same reason after an engine install) or the change
wouldn't take effect until the app restarted. Validates the path exists
before saving; a blank path clears the override back to the app's own
folder. `Components.jsx` gained a small `EnvRootControl` at the top of
the page, matching the same placement as the desktop's Engines tab.

Extended `tests/test_webcomponents.py` (3 new assertions): invalid path
refused with a 400, a valid path persists to settings AND is confirmed
to actually clear the probe cache (not just that the setting saved),
and clearing goes back to no override. Full regression: 13/13 suites
passing. `npm run build` caught a real mistake immediately -- assumed
`getSettings` already existed as a client export and it didn't; fixed
before it would have shipped broken.

This closes the last item from the original desktop-parity list.
**Nothing outstanding remains from that list.**

### Web UI feedback pass: file browser, form layout, waveform overlay, formula editor — 2026-09-13

Routh started testing the web UI (screenshots showed real usage) and
raised four things in one message. Handled in order:

**Waveform preview "clipping" -- diagnosed as overlay confusion, not a
rendering bug.** Reproduced Routh's exact settings server-side (linear
geometry, mirror on, box pinned near the bottom of frame) and confirmed
the PNG itself renders correctly -- the actual bug was the SVG guide
overlay: the green "centre" marker is the audiogram box's own centre
(correct, sits near the waveform), but the orange "pivot" marker is
always relative to the WHOLE FRAME regardless of geometry (matching the
desktop's own `layout()`/canvas drawing, confirmed by reading
`ui.py`'s pivot-drawing code -- not a porting regression). With pivot
left at its default centre while the box sits near the bottom, the two
markers land far apart and read as something clipping. Fixed by dimming
the pivot marker to 35% opacity when rotation is 0 (it does nothing at
that point), relabelling both markers ("audiogram centre" vs "rotation
pivot"), and updating the hint text to explain the two are intentionally
independent.

**File browser rebuilt.** The old one was a flat, unsorted,
single-select list defaulting to the OS home folder. `/api/files`
rewritten: defaults to `APP_DIR` (where Narrator itself lives) instead
of `~` -- Routh's explicit ask, since documents and output almost
always live under or near the app itself; every entry now carries a
real `mtime`; added a `search=` parameter that walks recursively up to
`search_depth` levels (default 4, capped at 500 results), each match
reporting its own containing subfolder so a hit three levels down stays
unambiguous. `FileBrowser.jsx` rebuilt on top: a search box, sortable
columns (Name/Type/Modified/Size, click to sort, click again to
reverse), folders always grouped first regardless of sort, and an
opt-in `multiple` prop (checkboxes + a "Choose N" button, `onPick`
receives an array) -- off by default so every existing single-pick
caller (`path`/`root` in the main form, `audio_source` in Audiogram,
Convert's source file) is unaffected; no caller currently needs
multi-select, but it's there for when one does. True OS-native
multi-select (shift-click in Explorer/Finder) was considered and
explicitly ruled out: browser sandboxing means `<input type="file">`
can hand over file *bytes* for upload, never a real filesystem path
usable for `root`/`path`-style fields -- Voice studio's clone-upload
already uses the one flow where that's the right tool. A custom browser
with real search/sort was the only way to deliver what was actually
asked for.

**Found and fixed while investigating: `/api/schema` silently discarded
whether a path field wants a file or a folder.** `render_config.describe()`
only propagated `spec` for `choice`/`int`/`float` kinds; `path`-kind
fields lost it entirely. Fixed to include `path_kind` ("file" or "dir")
-- needed so the browse button knows whether to treat a folder click as
"navigate in" or "this is the pick." This also surfaced three fields
that had NO browse button at all before this pass -- `video_image`,
`intro_audio`, `outro_audio` were plain text inputs requiring a
hand-typed absolute path. All three now get the same Choose... button
as `path`/`root`.

**Settings form made compact.** Routh's ask: one line per field (label
left, input right) instead of label-then-input stacked on two lines,
except genuinely long free-text fields, which can stay stacked with
extra room and optionally a textarea. Checked the actual schema before
guessing what counts as "long": of 26 fields, only `voice` (a
description for engines that design one, e.g. Qwen3) can plausibly run
to a full sentence -- everything else is a short value. Rather than
hardcode "voice" as a special case (breaking the file's own stated
"schema-driven, never hand-written" principle), the split is keyed off
`field.kind === "text"`, the schema's one genuinely free-form string
type, as opposed to path/choice/number/bool -- stays correct for any
field added later without touching this file. `text`-kind fields get a
stacked `<textarea>`; everything else is one row, label truncated with
a dotted-underline hover tooltip for its (sometimes longer) description
rather than always showing it and defeating the compactness.

**Expression/formula editor: replaced one always-open panel with a
per-field ƒx icon.** The old "Animate a value over time" fieldset was
a single global panel (a Value dropdown + one formula input + the full
reference list, always visible, taking real space even when nobody was
animating anything). Routh asked for something contained, triggered
per field. Rebuilt: each of the 13 backend-animatable fields
(`ANIMATABLE` in `audiogram.py` -- x/y/width/height/center_x/center_y/
inner_radius/outer_radius/pivot_x/pivot_y/rotation/opacity/line_width)
now gets a small "ƒx" toggle beside its number input, opening a compact
popover (filter-as-you-type reference list + live-validated formula
input + Apply/Clear/Cancel) anchored to that one field, closing on
Escape or an outside click -- reusing the same popover mechanics as the
dialogue editor's inline-refine feature. Also fixed a real, separate
gap this surfaced: a field already holding a formula (a non-numeric
string) was previously fed straight into a `type="number"` input, which
just shows blank/invalid for non-numeric content -- now such a field
shows a small "ƒ(t)" chip instead of a broken number box, click to
re-edit.

New `tests/test_webfiles.py` (14 assertions, all passing first run):
default-to-APP_DIR, real mtime/size per entry, hidden files excluded,
parent navigation (including at the filesystem root), only_dirs
filtering, a clean 404 for a missing folder, recursive search
(including a depth cap actually limiting the walk, and a no-match case
returning empty rather than erroring), and `path_kind` present on every
path-kind schema field. Full regression: 14/14 suites passing.
`npm run build` verified clean after every JS/CSS change.

### The tabbed-interface fix that was missed the first time — 2026-09-14

Routh's original feedback message had five items; the previous entry
addressed the file browser, waveform overlay, expression editor, and
settings layout -- but genuinely missed "I think there was an intent to
make this a tabbed interface but it's all laid out in a linear 1-page
format." Not a deferred/intentional choice -- an oversight, caught when
Routh followed up. Fixing it now.

Confirmed the desktop app really is tabbed (`ttk.Notebook`: Document /
Voice / Output / Publish as always-visible tabs, everything else as
menu-opened dialogs) -- the web port had flattened all of it, including
several sections added later this session (Timeline, Audiogram, Voice
studio), into one continuously scrolling page of eleven `<section>`
blocks. Rebuilt `App.jsx` around a real tab bar: Narrate (Document +
Settings + Generate + the render's JobLog, combined -- these were never
separate concerns, just adjacent steps in one flow), Library, Timeline,
Audiogram, Publish, Voice studio, Dialogue, Pronunciation, Components,
Convert. One tab per existing section, same names, same components,
same props -- a container change, not a reorganization of what goes
where, since Routh's complaint was specifically about the FORMAT, not
about which things are grouped together.

Each tab's content mounts the first time it's opened, then stays
mounted (hidden via `display:none`, never unmounted) for the rest of
the session -- switching tabs can't lose whatever's half-typed in
another tab, matching how Tk's own Notebook keeps every tab's widgets
alive under the hood rather than destroying and rebuilding them. Lazy
mounting (nothing loads until first visited) avoids all ten tabs firing
their own startup API calls the moment the page loads, which eager
mount-everything would have done for tabs like Timeline/Audiogram/Voice
studio that each make several calls on mount.

`JobList` (the persistent job history/log panel) stays outside every
tab, always visible -- a background job (an install, an export, a
render) shouldn't disappear from view just because the tab was
switched. One small necessary behavioural fix that fell out of this:
`Library`'s "load this project" used to `window.scrollTo(top)`, which
made no sense once there's no single scrolling page to scroll -- now it
switches to the Narrate tab instead, so the loaded settings are actually
visible.

Not changed: `Convert`'s job progress still only gets a live, line-by-
line `JobLog` view when the Narrate tab happens to be open (it shares
the App-level `jobId` slot with the render flow) -- this is a
pre-existing quirk, not something introduced by tabs (scrolling back up
to find that same JobLog was already required in the old linear
layout), and `JobList` at the bottom already shows every job including
Convert's, with full log lines on click. Left alone rather than
scope-creeping a fix for something Routh didn't raise.

No backend code touched -- this is `App.jsx` and `styles.css` only.
Verified by: `npm run build` clean, cross-checking all 10 tab keys
match one-to-one between the tab-bar definition and each `TabPanel`
(no typo silently leaving a tab permanently blank), confirming open/
close tag counts balance, and a full backend regression run as a
sanity check even though nothing backend-side changed (14/14 suites
still passing).

### Voice selection: fixing my own over-generalization from last round — 2026-09-14

Routh caught this one too: the web voice field was rendering as a giant
textarea, not a dropdown of the selected engine's real voices. Root
cause was my own earlier change -- in the settings-compaction pass, I
keyed the "keep this field stacked with a textarea" exception off
`field.kind === "text"`, reasoning that `voice` was the one field likely
to hold a long value. That was the wrong axis entirely: `voice` isn't a
free-text field that's sometimes long, it's an ENGINE-DEPENDENT field --
what counts as a valid value, and whether typing a new one even makes
sense, both depend on which engine is currently selected, something the
schema's per-field kind/choices shape has no way to express (it was
never designed to say "this field's options come from a DIFFERENT
field's value"). A textarea was wrong for it either way.

Read the desktop's actual voice widget before rebuilding
(`ui.py`'s `voice_menu`): a `ttk.Combobox` that is READONLY (closed
dropdown, only real preset voices selectable) for a fixed-voice engine
like Kokoro or edge-tts, and EDITABLE (free typing, with its example
voices offered as selectable suggestions, not a hard limit) for an
engine that designs a voice from a description, like Qwen3 or Audio8.
`/api/engines` already returns everything needed for this
(`editable` flag, `voices: [{id, label}]` per engine) -- confirmed
against the real per-engine data before building anything, rather than
assuming the shape.

Rebuilt `SettingsForm.jsx` with a `VoiceField` component, the one
deliberate exception to "every field renders generically from its
schema kind" (stated plainly in the file's own comment, so it's not a
silent surprise later): looks up the currently-selected engine's spec
from a new `engines` prop (passed down from `App.jsx`'s already-fetched
state, no new API call), and renders a closed `<select>` of real preset
voices for a non-editable engine, or a plain text `<input list=...>`
with a `<datalist>` of that engine's example descriptions for an
editable one -- native HTML's own type-with-suggestions element, the
same dual "pick from the list OR type something new" behaviour Tk's
editable Combobox has, without hand-building a custom dropdown widget.
No engine selected yet (or `engines` hasn't loaded) falls back to a
plain text input rather than an empty, useless dropdown.

Also reverted the incorrect over-generalization itself: `filename` (the
schema's only OTHER `text`-kind field) goes back to the plain compact
one-line row -- it's a short filename stem, never needed a textarea
either. There is currently no field in the schema that genuinely
benefits from the stacked-textarea treatment Routh originally described
as the exception case; if one is added later, that's the point to build
it, not something worth keeping a wrong heuristic in place for now.

No backend or schema changes -- `/api/engines` already had every piece
of data this needed. `App.jsx`/`SettingsForm.jsx`/`styles.css` only.
Verified by confirming the real `/api/engines` output for all four
current engines matches exactly what `VoiceField` expects (Kokoro/
edge-tts: real preset id/label pairs, non-editable; Qwen3: example
design descriptions as the datalist, editable; Audio8: editable with an
empty suggestion list, which is correct -- it has no built-in presets),
`npm run build` clean, and a full backend regression run (14/14 still
passing, nothing backend-side touched).

### Correcting a misunderstanding, then an audit pass — 2026-09-14

Routh thought the web UI might not be React yet ("I think if we havent
already, we should migrate this into a react project"). It already is,
and has been the whole time this session's web work was built -- shown
directly rather than just asserted: `web/package.json` lists `react`/
`react-dom` as real dependencies, `vite.config.js` builds via
`@vitejs/plugin-react` straight into `narrator/webui` for the Python
backend to serve, and all 17 `.jsx` components (App, AudiogramEditor,
TimelineEditor, VoiceStudio, Dialogue, TurnEditor, and the rest) are
what every feature built this session actually is. Nothing to migrate.
No source or build changes for this part -- just confirming the
premise before doing anything on the strength of it.

With that resolved, spent the rest of the turn on an audit pass across
the components touched quickly during the recent feedback rounds, since
the voice-field bug two turns ago was a real miss that slipped past my
own testing -- worth checking for siblings before assuming there
weren't any.

**Found one: switching engines left a stale voice value from the
PREVIOUS engine sitting in the field.** The desktop's own voice
Combobox resets on every engine change (`refresh_voices()`); the web
port's new `VoiceField` never replicated that -- pick Kokoro's
`af_heart`, switch to edge-tts, and the dropdown would show nothing
selected (an invalid leftover value) rather than resetting to something
real. Fixed with a `useEffect` in `VoiceField` that resets to the new
engine's first voice, but ONLY when the engine genuinely changes (not
on first mount) AND only for non-editable engines whose current value
doesn't already belong to the new engine's real preset list. That
scoping mattered: an earlier, simpler version that reset unconditionally
on every engine change would have also fired when a saved project loads
`engine`+`voice` together as an already-matching pair from the Library
tab, incorrectly wiping out a perfectly valid loaded voice -- caught
this by explicitly tracing through that scenario before shipping the
fix, not after.

**Found and fixed a second, smaller inconsistency:** `Convert.jsx` was
the one job-launching component still using the OLDER pattern (feeding
its job id into the shared App-level `jobId`, which only the Narrate
tab's `JobLog` reads) -- meaning a conversion's live progress was only
visible if you happened to have the Narrate tab open, not the Convert
tab you actually started it from. `Dialogue.jsx` (built later, more
consistently) already has its own local `jobId` + embedded `JobLog` for
on-tab visibility, calling `onJob?.()` (no arguments) purely to bump the
persistent `JobList`'s refresh key once the job finishes. Brought
Convert in line with that exact pattern -- own local JobLog, `onJob`
now bumps `jobsKey` like Dialogue's and Components' already do, instead
of quietly diverging in its own App.jsx wiring.

`FileBrowser.jsx`'s click/navigate/multi-select logic and the tab
structure's mount/visibility handling were re-read fresh looking for
similar issues; nothing else turned up. No backend changes this round.
Full regression: 14/14 suites passing (nothing backend-side touched, so
this is a sanity check, not new coverage -- there's no JS test runner in
this project, consistent with how every other frontend change this
session has been verified: careful code tracing through the actual
data flow plus a clean `npm run build`, not a framework that isn't
part of the toolchain). Verified clean build after each change.

### shadcn/Tailwind migration, stage 1: foundation + tabs — 2026-09-14

Routh asked to go all the way to shadcn ("as large of a change as it
is... we can take multiple steps"). Staged deliberately so the app
works after every step rather than sitting half-migrated and broken.

One correction first: Routh suggested shadcn "might solve our tabs
issue" -- there was no outstanding tabs issue. The tab bar was rebuilt
two turns ago and is present in the build being tested (verified in
both source and the shipped bundle before touching anything). Migrating
tabs to Radix is worth doing for what it genuinely adds (see below),
not because the existing ones were broken.

**Stage 1 (this entry) -- foundation, plus the first two conversions:**

- Tailwind 3 + PostCSS + autoprefixer installed. The 2 npm audit
  warnings are pre-existing (Vite's bundled esbuild), affect only the
  DEV server, and fixing them means a breaking Vite 8 upgrade -- not
  taken mid-migration, noted rather than silently ignored.
- `tailwind.config.js` + `src/theme.css` define the palette as shadcn's
  semantic CSS variables (background/card/popover/primary/muted/border/
  destructive/...), converted from the exact hex values the old
  stylesheet already used -- extracted from the real CSS, not guessed --
  so generated components look like the rest of the app from the first
  one, instead of arriving in Tailwind's stock grey needing to be
  re-skinned individually. Two extras beyond shadcn's set (`success`,
  `warning`) because this app genuinely shows three job/validation
  states, not one. Dark-only on `:root`, no `.dark` class, because there
  is no light theme and never was.
- `main.jsx` loads `theme.css` BEFORE `styles.css` on purpose: during
  the migration, the hand-written rules still win over Tailwind's base
  layer for not-yet-converted components, so nothing breaks in between.
  `styles.css` shrinks as components move and disappears when the last
  one does.
- Radix primitives + `class-variance-authority`/`clsx`/`tailwind-merge`/
  `lucide-react` installed; `@` path alias added to `vite.config.js`
  (shadcn components are generated with `@/components/...` imports and
  won't resolve without it); `src/lib/utils.js` provides the `cn()`
  helper every shadcn component uses.
- `components/ui/button.jsx` -- variants mapped to what this app
  actually uses (primary action, default, destructive, ghost, link,
  plus sm/lg/icon sizes), not shadcn's stock set.
- `components/ui/tabs.jsx` -- Radix-backed. This is the real win over
  the hand-rolled version: arrow-key/Home/End navigation, correct
  roles and `aria-selected`, and proper focus management, none of which
  the hand-written buttons had. Verified `aria-selected` and Radix's
  `data-[state=active]` actually land in the shipped bundle.

**Two tab sets converted, with deliberately different mount behaviour --
worth understanding before touching either:**
- App's top-level tabs use `forceMount` + the existing `visited` set.
  Radix unmounts inactive content by default, which would throw away
  whatever is half-typed in another tab; `forceMount` alone would mount
  all ten on first paint and fire every tab's startup requests at once.
  Pairing them keeps both properties (nothing mounts until first
  opened; nothing unmounts after). Radix does not hide forceMounted
  content itself, hence the explicit display toggle.
- VoiceStudio's inner tabs deliberately do NOT use forceMount -- each is
  a short form whose half-filled state means nothing once you've chosen
  a different way of making a voice, so Radix's default unmount (a fresh
  form on return) is the better behaviour there.

Dead CSS removed in the same pass (`.tabbar`, `.tab-active`, and
VoiceStudio's inner tab button rules) -- confirmed zero remaining
references across all JSX and CSS rather than leaving orphaned rules.

**Still to do (stages 2+):** convert the remaining hand-written controls
to shadcn equivalents -- inputs/labels across SettingsForm, the
dialogue editor's hand-rolled right-click menu (no keyboard support at
all today) to Radix ContextMenu, FileBrowser and the modal pickers to
Dialog, selects to Radix Select, the audiogram formula popover to
Popover, and the remaining ~370 lines of styles.css to Tailwind
utilities. No backend changes in this stage or expected in later ones.
Full regression: 14/14 passing (sanity check -- nothing backend-side
was touched).

### shadcn migration, stage 2: popovers, inputs, TurnEditor — 2026-09-14

Continuing the staged migration. This stage took the two hand-rolled
popups -- the biggest real accessibility gaps left in the app -- plus
the components around them.

**New components:** `popover.jsx` (Radix), `input.jsx`, `textarea.jsx`,
`label.jsx`.

**Dialogue editor's inline-refine popup → Radix Popover.** This was the
weakest hand-rolled thing in the app: a fixed-position div with no focus
trap, no focus restoration on close, no collision detection (it would
render partly off-screen if you right-clicked near a viewport edge), and
manual document-level mousedown/keydown listeners for dismissal. Now
anchored via a zero-size `PopoverAnchor` at the cursor position, so
Radix does collision handling, focus trapping and dismissal itself. The
manual listeners were REMOVED in the same edit rather than left in
place -- keeping them would have double-fired `closePopup` on every
dismissal, which is the kind of thing that survives a migration
unnoticed because it doesn't visibly break anything.

A deliberate choice worth recording: Radix has a `ContextMenu` primitive
and this IS triggered by right-click, but ContextMenu is for menus of
actions, whereas this is a free-text instruction box. Popover anchored
to the cursor is the honest fit; using ContextMenu here would have meant
fighting its item/keyboard model for no benefit.

**Audiogram's formula popover → Radix Popover**, with the ƒx button as a
real `PopoverTrigger` (rather than the popover being a sibling div).
That's what makes focus return to the ƒx button on close, which the
hand-rolled version never did. Same manual-listener removal as above.
`useRef` import dropped from the file once its last use went.

**TurnEditor fully converted** -- buttons, textarea, row containers and
speaker labels now shadcn/Tailwind. The two host colours are the only
literal hex values left in that file, deliberately: they're two
distinguishable hues for scanning a long script, not semantic theme
roles, so mapping them onto `primary`/`accent` would have been dishonest
about what they are.

**Dead CSS removed:** 16 class names confirmed to have zero remaining
JSX references, then their rules removed -- 26 blocks total, including
four compound selectors (`.refine-popup .hint`, `.ag-fx-btn.active`,
etc.) that an automated "is every class in this selector dead?" pass
correctly skipped, since `.hint`/`.row` are still live elsewhere; those
needed checking by hand rather than trusting the sweep. `styles.css`
385 → 333 lines.

Full regression 14/14 (sanity check -- no backend changes in this
stage). Clean build verified after each conversion, not just at the end.

**Remaining for stage 3+:** SettingsForm's fields to Input/Label/Select,
FileBrowser + the modal pickers to Dialog, native selects to Radix
Select, VoiceStudio/Publish/Library/Components/Convert/Pronunciation/
Providers/JobLog/JobList bodies, and the last ~333 lines of styles.css.

### shadcn migration, stage 3: selects, checkboxes, radios — 2026-09-14

New components: `select.jsx`, `checkbox.jsx`, `radio-group.jsx`,
`icons.jsx`.

**19 of 20 native `<select>` elements converted across 9 files.** The
one exception is `Providers.jsx`'s "Add one" template picker, left
native ON PURPOSE with the reasoning recorded in the file: it is an
ACTION menu, not a value selector -- it always shows its placeholder,
fires `startFrom()` on pick and resets immediately. Radix Select is
built around holding a value, so forcing it there would mean fighting
it to stay unselected; DropdownMenu is the right primitive if that ever
needs to match visually.

**The migration hazard worth knowing about:** Radix Select reserves the
empty string internally and rejects `<SelectItem value="">`. Nine
places relied on `<option value="">` and they were NOT all the same
case, so they didn't get the same fix:
- "no options exist yet" (take pickers, provider picker, speaker list)
  → `disabled` trigger + a `placeholder` on SelectValue, value left
  undefined.
- "optional, nothing selected" (SettingsForm's voice/choice fields)
  → value coerced to undefined when empty, placeholder shows.
- "no filter / any" (JobList's kind and status filters) → a real
  sentinel (`__any__`) mapped back to `""` at the component boundary,
  since "any" is a genuine selectable state, not an absence.

**Numeric selects:** Radix hands back strings where native selects were
already doing `Number(e.target.value)`. Preserved explicitly in
Convert's sample-rate/bit-depth/channels. Checked the backend before
assuming this mattered for SettingsForm's numeric choice fields --
`render_config._coerce_one` already handles it ("Numeric choices often
arrive as strings from a form"), so that path was safe either way.

**lucide-react removed.** shadcn components import icons from it, but
its barrel export pulled ~1900 modules into the build for the three
glyphs actually used (Check, ChevronDown, ChevronUp). Replaced with
`components/ui/icons.jsx` -- nine lines of inline SVG. Build went 1985
→ 136 modules and the bundle dropped ~5 kB. Dependency uninstalled. The
reasoning (and the deep-import alternative, if more icons are ever
needed) is recorded in that file.

**Also converted:** SettingsForm fully (inputs, labels, checkbox, both
selects); Convert fully, including its split-mode radios → Radix
RadioGroup (arrow-key navigation and a single tab stop for the group,
which loose native radios sharing a `name` do not give) -- except its
quality slider, which deliberately stays a plain `<input type=range>`
since the Input component's border/height/padding are wrong for a
range control; AudiogramEditor's three checkbox groups.

Dead CSS removed (`.ag-check`, `.radio`, `.radio input`); styles.css
333 → 329 lines. Full regression 14/14, serve check passing, clean
build verified after every file.

**Remaining:** FileBrowser + modal pickers → Dialog, the remaining
component bodies (VoiceStudio, Publish, Library, Components,
Pronunciation, Providers, JobLog, JobList, TimelineEditor,
AudiogramEditor layout), and the last ~329 lines of styles.css.

### shadcn migration, stage 4: icon set, Dialog, FileBrowser — 2026-09-14

**Icon set: react-icons, Phosphor pack (`react-icons/pi`).** Routh
suggested a lighter react-icons sub-pack after lucide was dropped (and
was glad to see lucide's look go). Measured before choosing rather than
assuming, since react-icons installs as one 85 MB package: with the nine
icons this app actually needs, `/pi`, `/tb` and `/ri` each cost +5
modules and ~+1 kB gzipped over hand-inlined SVG -- per-pack ESM entries
tree-shake cleanly, unlike lucide's barrel (the 1,985-module problem).
The 85 MB is node_modules only and never ships. Picked Phosphor on looks
alone; Tabler is close enough to lucide to read as the same style.

`components/ui/icons.jsx` is the single mapping layer: it's the only
file that imports from an icon pack, and it exports semantic names
(Folder, Close, Play, Trash...) rather than pack names (PiFolder).
Switching packs is a one-file change. Unused exports tree-shake away, so
the file can list likely-needed icons at no cost. Rule: never import
from the `react-icons` root, only a pack subpath.

Text/emoji stand-ins replaced (folder emoji, sort arrows, ✕, ▶, the ƒx
button, "+ line"). Icon-only buttons got `aria-label`s -- a bare glyph
has no accessible name, and `title` alone isn't reliably announced.

**`components/ui/dialog.jsx` (Radix Dialog), and FileBrowser is now a
real modal.** Before, it was an inline panel that pushed the page down
and left everything behind it clickable mid-pick. Now: focus trapped
while open, returned on close, page behind inert, Escape/backdrop
dismiss. Props unchanged (`onPick`, `onlyDirs`, `onClose`, `multiple`)
so none of its four callers (App, SettingsForm, AudiogramEditor,
Convert) changed -- mounting it opens it. Verified each passes onClose.
Rows are now real `<button>`s inside `<li>`s, so they're reachable by
keyboard; in multi-select mode the row reports state via `aria-pressed`
and the checkbox is visual-only (`aria-hidden`, not focusable), avoiding
a nested interactive control.

**One gap fixed while in there:** in folder-picking mode (the output
root) you could only choose a folder via its "choose" button seen from
its PARENT -- the folder you'd navigated into couldn't be chosen at all.
Added "Use this folder" in the footer.

**Two bugs of my own from the earlier FileBrowser rebuild, found and
fixed:**
- Descending sort pushed folders to the bottom. The code sorted
  folders-first and THEN reversed the whole list, contradicting its own
  "folders first, always" comment. Now reverses first, applies
  folders-first last (stable sort keeps within-group order). Verified by
  running old vs new logic side by side in node: ascending identical,
  descending now folders-on-top, numeric-aware order intact.
- The opening listing was fetched twice (the debounced search effect
  also fired on mount with an empty query). First run now skipped.

Dead CSS: every `.browser*`/`.bc-*` rule removed (20 blocks, 329 → 294
lines). Because that was a regex sweep, diffed the selector set against
the previous packaged stylesheet: exactly the file-browser selectors
were removed, and none of them is still referenced in any JSX.

Build 143 modules, 377.6 kB / 120.2 kB gzip. Full regression 14/14,
serve check passing.

**Remaining:** component bodies (VoiceStudio, Publish, Library,
Components, Pronunciation, Providers, JobLog, JobList, TimelineEditor,
AudiogramEditor layout, App's section wrappers), VoiceStudio's
`window.confirm` delete prompt → a proper confirm dialog, and the last
~294 lines of styles.css.

### shadcn migration, stage 5: seeing the UI for the first time — 2026-09-21

**The most important thing in this entry: the frontend had never been
LOOKED at.** Every earlier stage was verified by `npm run build` plus the
backend suite -- neither renders a pixel or runs a line of the UI's
JavaScript in a browser. This stage found a headless Chromium in the
sandbox and used it, and it overturned several things I had reported
as done.

**What rendering it revealed:**

1. **Stage 3's checkboxes and radios were visibly broken.** The old
   stylesheet had a global `button { padding; background; border }`
   rule. Radix renders real `<button>`s inside checkboxes, radio items,
   tab triggers and select triggers, so the rule leaked into all of
   them: checkboxes and radios squeezed into pills (the selected radio's
   dot pushed out entirely), inactive tabs drawn as grey boxes, every
   file-browser row boxed. A global `h2` rule also uppercased dialog
   titles. Fixed at the root: base styles moved into `theme.css` with
   NO global button rule at all (every button styles itself via
   `button.jsx` or its own classes), and the heading rule scoped to
   `section > h2`.
2. **The settings grid overflowed the page** with uneven columns -- a
   plain `1fr` column can't shrink below its content, so one long output
   path widened it. Now `minmax(0, 1fr)`.
3. **Publish crashed whenever a take existed** -- `ReferenceError: Select
   is not defined`. The stage 3 edit that added its import anchored on
   `import JobLog`, which Publish doesn't have, so the insertion silently
   did nothing. It hid behind the empty state (no takes = the Select
   never rendered), so empty-state checks missed it. **This was in the
   stage 3 and stage 4 builds Routh had.**
4. **Hiding the Dialogue tab's Providers panel blanked the whole app.**
   `useEffect(load, [])` where `load` returns a promise: React treats an
   effect's return value as its cleanup and CALLED the promise on
   unmount. With no error boundary, the whole tree unmounted. Same
   pattern in Components (latent -- it never unmounts). **Pre-existing
   since the dialogue feature was built -- in every build Routh has
   had**, not introduced by the migration; found only because the
   harness clicked through it.

**Guards added so these classes of bug can't ship quietly again:**
- **ESLint, wired into `npm run build`** (build = lint, then vite).
  Deliberately narrow, runtime-affecting rules only: `no-undef` and
  `react/jsx-no-undef` (would have caught #3), `rules-of-hooks`, and a
  `no-restricted-syntax` rule rejecting `useEffect(fnRef, ...)` and
  concise-arrow effect bodies (would have caught #4). Proven, not
  assumed: temporarily removed Publish's Select import and confirmed the
  build refused, naming every undefined component and line.
- **A per-tab ErrorBoundary** (`components/ErrorBoundary.jsx`, wired
  into `TabPanel`). A render/commit crash now shows a message and a
  "Reset this tab" button in that tab only; other tabs and their state
  are untouched. Proven by building a version where Pronunciation
  deliberately throws: that tab showed the message, Convert kept
  working. The test build was then replaced and the string confirmed
  absent from both source and the shipped bundle.
- **`tests/ui_walk.py`** -- the screenshot harness, kept in the repo.
  Serves the real built app, can do a real stubbed render first so
  take-dependent screens show real UI, and reports console/page errors.
  Not in `run_all.py` (needs Playwright + Chromium). A full walk of
  every tab, including the Providers toggle and file browser, now
  reports zero errors.

**Also this stage:**
- Voice studio's `window.confirm` delete → `ConfirmDialog` (Radix
  AlertDialog): backdrop click doesn't dismiss, focus starts on Cancel
  so a reflex Enter can't delete. Original warning text kept verbatim.
- Converted the remaining 42 native buttons, 25 text inputs/textareas
  and 33 labels. JobList's full-width expandable row deliberately stays
  a native `<button>` (a row, not an action). Conversions used
  brace-aware parsing after a single-line pattern missed several
  multi-line tags the first time -- caught by screenshot, not by build.
- Removed the `path`/`root` duplicates from the settings grid (they're
  in the Document section above it); SettingsForm gained a `hide` prop.
- The no-engine warning said to use "the desktop app" -- the web UI's
  own Components tab installs engines. Now a link that switches there.
  Timeline's hint said "the Pronunciation section above" -- it's a tab
  now. Components shows "Checking what's installed…" while loading
  instead of looking empty.
- JobLog: a `stopped` flag was set on cleanup but never read. Wired up
  properly, plus the same guard for the polling fallback, so a late
  answer for a job the log has moved away from can't append its lines
  or fire `onFinished`.
- Dead imports removed (lint found them).
- styles.css 294 → 232 lines.

**New dev dependencies** (eslint, eslint-plugin-react,
eslint-plugin-react-hooks, globals, @radix-ui/react-alert-dialog):
run `npm install` in `web/` before building.

Full backend regression 14/14. Full UI walk: zero errors.

**Remaining:** the last ~232 lines of component-specific CSS (voice-*,
timeline-*, ag-*, publish, pronunciation, providers, job list) →
Tailwind, then delete styles.css. Verify each with tests/ui_walk.py,
not just the build.

## 6. How to test without a GPU


- `xvfb-run -a python3 test.py` for anything tkinter; `import -window root
  shot.png` (ImageMagick) for screenshots; assert `w.state()=="normal"` and
  `w.winfo_viewable()==1` for dialogs.
- A fake `qwen_tts` + `torch` on `PYTHONPATH` that mirrors the real API
  surface (model-type checks, `create_voice_clone_prompt` returning a
  prompt object, kwargs) exercises `_run_qwen_local`, the worker, caching,
  and the voices folder end-to-end. Read the real package source (`pip
  download qwen-tts --no-deps`, unzip the wheel) before changing any call.
- `python -m narrator --clean file.docx` exercises document cleaning
  headless. `python -m narrator.setup_engines --check` exercises detection.
