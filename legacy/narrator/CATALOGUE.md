# Narrator — what exists

Written 2026-08-30, updated 2026-08-31. A snapshot of the whole thing in one place, because
HANDOVER.md is chronological and now long enough that "does X exist already?"
is a genuinely hard question to answer from it. That is not a hypothetical
problem: this session opened with a stale handover copy that would have led
to rebuilding the chapters feature from scratch.

Two audiences, both of them us: the first half is what the tool can do, the
second half is where the code for it lives.

Read this first, HANDOVER.md for *why* a thing was built the way it was.

---

## 1. What it does, in one paragraph

Takes a long document (.docx, .odt, .html, .tex, .epub, .md, .txt), cleans it
into speakable prose, splits it into parts, narrates it with a local TTS
engine, and produces an audio file plus optional subtitles, chapter marks, a
page-text layer, an editing WAV and a video. It is built for documents
measured in hours, so nearly every design decision favours resumability,
repeatability and being able to fix one sentence without re-rendering the
rest.

## 2. Engines

| Engine | Offline | Voice | Drift on long files | Chunk cap | Splice-able |
|---|---|---|---|---|---|
| **Kokoro** | yes | fixed list + custom blends | none (deterministic) | 20,000 chars | yes (WAV) |
| **Qwen3** | yes (GPU) | designed from a text description | some; sampled per group | 1,500 chars | yes (WAV) |
| **edge-tts** | no | Microsoft voices | none | 4,000 chars | **no** (mp3 chunks) |

Kokoro is the intended engine for long-form work. Most of the newer features
are Kokoro-only, and that is a deliberate consequence of the above, not an
oversight — see §7.

## 3. Feature catalogue

Status key: **done** = built and tested; **done, unheard** = built and tested
but no audio has ever been listened to; **partial** = works with a stated
limit; **not built** = named here so it is not reinvented.

### Document handling
- **Roman numerals** — done. "Chapter IV" -> "Chapter 4", "Henry VIII" ->
  "Henry the eighth". Deliberately conservative: only converts with a
  counting word or a capitalised name before it, so "MIX", "vitamin D" and
  the pronoun "I" are untouched.
- **Cleaning pipeline** — done. Converts via pandoc, strips citations, URLs,
  markdown, front/back matter; handles tables and lists; expands
  abbreviations. `documents.clean_document()`.
- **"Clean text only"** (Tools menu) — done. Produces the cleaned text
  without rendering, so you can read what will actually be narrated.
- **Chunking** — done. Whole sentences only, never splits mid-sentence.
  Chunk size set by parts-count or characters, capped per engine.
- **Chapters from headings** — done. Embedded as chapter marks.
- **Footnote bodies** — **unknown, flagged.** The cleaner strips footnote
  *markers*; what happens to footnote *bodies* has never been checked. If
  pandoc lands them as endnotes they may be narrated as a block of
  disconnected text at the end. Check with a real document via "Clean text
  only" before trusting an hour-long render.

### Voices
- **Stock Kokoro voices** — done.
- **Voice discovery** — done. Finds voices in the Kokoro repo beyond the
  built-in list.
- **Bulk voice prefetch** — done, **confirmed working** (Routh,
  2026-08-31). One
  button pulls every voice (~30 MB total; each pack is ~512 KB) so blending
  and switching are offline afterwards.
- **Custom Kokoro voices (blending)** — done, unheard. Weighted blend of up
  to four stock voices, saved as a `.pt` and usable anywhere a voice name is.
  **No real voice pack has ever been loaded** — no Hugging Face access from
  the dev sandbox.
- **Qwen3 designed voices** — done (pre-existing).
- **Second voice for block quotes** — done, unheard. Kokoro only.
- **Arbitrary per-chunk voices** — done, unheard. Kokoro only. Set in the
  chunk map.
- **Voice drift across a document** — done. Two modes: *stepped* (each voice
  holds for a run of parts) and *smooth* (every part gets its own
  interpolated blend, quantised to 5% so a long document reuses a few dozen
  files). Kokoro only for smooth. Set in the chunk map.

### Pronunciation
- **Word substitutions** — done. Permanent whole-word rewrites applied before
  chunking; the only way to change how Qwen3/edge say a word. Tools > Word
  substitutions. Applied longest-word-first so a short entry cannot corrupt a
  longer one.
- **Custom pronunciation dictionary** — done. Respellings in ordinary words
  ("narrative izing"), resolved to phonemes via misaki. Kokoro only. Also
  accepts raw phoneme pieces between slashes for sounds no word isolates
  (`/ˌIzˈAʃən/` for "-ization"). Validation runs 700 ms after typing stops.
  NOTE: these are Kokoro's symbols, not dictionary IPA — `I` is "eye", `A`
  is "ay". Dictionary IPA is rejected with an explanation.
- **Pronunciation scan** — done. Finds likely-problem words before rendering.
- **Fix a word everywhere** — done, unheard. Fixes one word in every sentence
  of a take that says it. Kokoro (via lexicon, permanent) and Qwen3 (via text
  substitution, this take only).

### Rendering & output
- **Resumable renders** — done. Per-chunk files on disk; re-running skips
  what exists.
- **Render cache** — done. Keyed on engine, voice(s), speed, text, pacing and
  the *relevant* pronunciations.
- **Pacing (gap policy)** — done, unheard. Pause length decided by the text,
  not the engine or chunk boundary.
- **Level matching** — done, unheard. Median-targeted, capped at 3 dB.
- **Loudness target** — **done and genuinely verified.** -16 LUFS default,
  two-pass. The one audio feature measured end to end with real signals.
- **Formats** — done. MP3, M4A/AAC, WAV, FLAC; sample rate, bit depth,
  quality.
- **Editing WAV** — done. Separate uncompressed export for a video editor.
  NOTE: above 16-bit this gets an EXTENSIBLE header (`0xFFFE`) that simple
  WAV readers reject. Use 16-bit if a plugin refuses the file.
- **Output size control** — done. Tools > Fit audio to a size limit. Set a
  budget and choose what to give up: lower sample rate (one file), full
  quality (split into pieces), or auto (reduce to a floor, split only if
  needed). Plan priced live before writing; split offsets measured, not
  assumed; pieces can be merged back. Reactor's AudioWaveform fuse has a
  hard-coded 200 MB ceiling, confirmed from its console. adjustable-rate mono proxy (2-22 kHz, same duration, up to ~24x
  smaller) for audiogram plugins, or fixed-length pieces with measured offsets. Both write plain
  16-bit PCM.
- **Intro / outro beds** — done, with crossfade.
- **Video export** — done. Static image + audio.
- **Subtitles (.srt)** — done. Word-timed for edge-tts, chunk-timed
  otherwise.
- **Page video (.pages.mov)** — done. Transparent-background video of the
  page layer, for Fusion effects that need real pixels. Text is white by
  necessity (its luma is its alpha); recolour in the editor. qtrle by default,
  ~12x smaller than ProRes 4444 for this content.
- **Page layer (.pages.srt)** — done. Page-sized text cues held on screen for
  as long as they take to read; paragraph structure preserved.
- **Render time estimate** — done. Rough figure up front from remembered
  runs, refined live.
- **Queue / batch** — done. Several documents in one go.
- **Podcast RSS + transcript export** — done.

### Editing a finished take
- **Fix a chunk** — done. Re-render one part, splice back.
- **Fix a sentence** — done. Re-render one sentence, splice back with a
  crossfade and RMS match.
- **Retry a sentence** — done. Same text, different cache key.
- **Fix a word everywhere** — see above.
- **Chunk map** — done. Whole document with chunk boundaries tinted; hover
  for detail; click for re-take / sample / set voice.
- **Open a take to fix** — done (Tools menu). Reopens a finished take from
  its `.manifest.json`, so every editing feature works on yesterday's render
  and not only on one made in the current session. Refuses up front, with a
  reason, if the render cache has been cleared since — the manifest lives
  beside the output and survives; the chunk audio lives in the cache and does
  not, so surviving does not imply editable.
- **Word timestamps ("play just this word")** — done, unheard. "Play word"
  in the sentence dialog. Kokoro English only; takes rendered before this
  existed have no word data and the UI says so.
- **Timeline/waveform canvas** — not built, deliberately deferred. The chunk
  map covers most of what it was for.

### Not built (named so they are not reinvented)
- Voice Studio (B) — largely superseded by the voice designer.
- Installer (C) — parked by decision.
- Inline quote detection (only *block* quotes are found).

## 4. How a render actually flows

```
document file
  └─ documents.read_text_file(path, mark_quotes=)      cleaned, speakable text
       └─ documents.chunk_text_with_voices/_kinds      chunks + boundary kinds
            └─ chunkmap.chunk_voices_from()            per-chunk voice list
                 └─ pipeline.ENGINES[..]["run"]()      engine dispatch
                      └─ engines._run_kokoro_local()   per chunk:
                           · pacing.gaps_for()           gap per sentence join
                           · pacing.match_levels()       even out loudness
                           · engines._lay_out()          audio + silence
                           · segments.save_segments()    .segments.json sidecar
                      └─ engines._join_chunk_wavs()    master + result dict
                 └─ audio.finalize_render()            transcode, loudness,
                                                       intro/outro, srt, pages,
                                                       chapters, video, wav
```

Editing afterwards works on the same `result` dict:

```
pipeline.resplice_segment(finalize=False) × N  →  pipeline.rebuild_take()
```

## 5. Key data structures

**`result`** — what an engine returns and everything downstream consumes:

```python
{
  "master": "/…/_master.wav",
  "chunk_paths":    [...],     # one WAV/mp3 per chunk, on disk
  "chunk_texts":    [...],
  "chunk_durations":[...],     # seconds
  "segments":       [[{"text","start","end"}, ...], ...],  # per chunk
  "chunk_gap":  0.45,          # legacy scalar = max(chunk_gaps)
  "chunk_gaps": [0.45, 0.12],  # per JOIN, len == len(chunks) - 1
  "native_srt": None,          # edge-tts word-timed subtitles, if any
  "intro_offset": 0.0,         # set by finalize_render
}
```

**`last_render`** — a finished take: `out_path, engine_key, voice, speed,
take, cfg, folder, stem, result`. This is what every fix operation takes.

**Segment sidecar** — `<chunk>.segments.json`, one per chunk file, holding
sentence spans *relative to that chunk*. `flat_segments()` converts to
absolute; `build_manifest()` builds the per-chunk tree.

**Times**: segment `start`/`end` are within a chunk. `abs_start`/`abs_end`
(manifest) and `flat_segments()` are within the finished file, intro offset
included. Mixing these up is how a splice lands in the wrong place.

## 6. Settings and cfg keys

`cfg` is built once on the main thread (`build_cfg()`) and handed to the
worker; nothing below that line may read a widget.

Settings keys currently used: `artwork_url, audio_base_url, author, bit_depth,
category, chunk_count, chunk_mode, chunk_target, chunk_voices_for_document,
description, editing_wav, editing_wav_channels_label, editing_wav_rate, email,
engine_pythons, env_root, explicit, extra_voices, format, intro_audio,
intro_crossfade, keep_chunks, language, last_engine, last_voice_by_engine,
loudness_on, loudness_target, output_root, outro_audio, page_chars,
page_layer, page_wrap, quality_pct, quote_voice, qwen_take,
qwen_voice_builder, render_rates, sample_rate, speed, subtitles, title,
use_subfolders, video_image, website, wizard_shown` — plus a `pacing` block.

## 7. Gotchas that will bite

1. **Chunk-voice overrides are keyed by index.** Change chunk size or edit the
   document and index 7 is different text. Handled by a fingerprint that
   drops them all — but that means assignments *disappear* after a re-chunk.
   Working as designed; misapplying them would be worse.
2. **Changing pacing invalidates the render cache.** Silences are baked into
   each chunk WAV. Settle pacing before starting a long document.
3. **Adding a pronunciation only re-renders chunks containing that word** —
   by design, but it means the fingerprint has to see the word. Case-folded.
4. **edge-tts takes cannot be spliced.** mp3 chunks. Every sentence-level fix
   refuses up front with a reason.
5. **Kokoro word timestamps are English-only.** The non-English pipeline
   branch never computes them.
6. **A custom voice is a file path, not a name.** Anything that tests a voice
   with `startswith("bf_")` is wrong — use `voices.lang_code_for()`.
7. **Kokoro and Qwen3 have different chunk-loop shapes.** Kokoro iterates all
   chunks and skips cached ones inside the loop; Qwen3 pre-computes a `todo`
   list first. A patch that matches one will land wrong in the other — this
   already happened once and imported cleanly while being broken.
8. **WAV above 16-bit gets an EXTENSIBLE header.** ffmpeg writes format tag
   `0xFFFE` for 24/32-bit and `0x0001` for 16-bit. Simple readers (Lua WAV
   parsers in Fusion/Reactor scripts among them) often accept only `0x0001`,
   so a 24-bit file can be refused for reasons unrelated to its size.
9. **`launch()` blocks on the setup wizard** unless `wizard_shown` is set and
   engine `detect` callables are stubbed. Preferences is a **menubar
   cascade**, not a button. `root._narrator_state` exists for test harnesses.

## 8. Verification status — read this before trusting anything

**324 tests**, `python3 -m unittest discover -s tests`, ~5 s.

| Test file | Tests | Covers |
|---|---|---|
| `test_pacing.py` | 37 | gaps, boundary kinds, level matching, audio/segment alignment |
| `test_words.py` | 39 | word matching, occurrences, fix planning, quote blocks |
| `test_chunkmap.py` | 25 | override fingerprinting, reconciliation, voice drift |
| `test_voices.py` | 25 | blend arithmetic at real pack shape, save/load, lang codes |
| `test_estimate.py` | 24 | rate tracking, cache exclusion, duration formatting |
| `test_pages.py` | 22 | flat reading order, page grouping, paragraph recovery |
| `test_loudness.py` | 11 | **real ffmpeg round trip**, measured with ebur128 |
| `test_fix_word.py` | 11 | end-to-end fix-everywhere against a stub engine |
| `test_join_end_to_end.py` | 5 | real WAVs on disk, manifest times vs actual audio |

**The gap, updated 2026-08-31.** All of this was built on a machine with no
GPU, no kokoro, no misaki and no Hugging Face access, so nothing could be
heard here. Routh has since run it: **Kokoro output sounds good**, on the
voices tested, and the bulk voice prefetch works against the real repo. That
retires most of what was listed here.

Confirmed by ear (Kokoro): default pacing (0.12 s / 0.45 s), chunk joins,
level matching at 3 dB, bulk voice prefetch.

Still unheard, in order of how likely they are to need adjusting:

1. Whether a Kokoro blend sounds like anything worth using. Averaging style
   vectors is not a physical model of a voice; expect to find good results by
   trying uneven mixes, not by reasoning about them.
2. Whether a sentence re-rendered after a lexicon fix sits cleanly against
   its neighbours — it was generated in isolation, without surrounding
   context for prosody. Most likely to show on "fix a word everywhere",
   which does this many times at once.
3. Whether the block-quote voice reads naturally at the handover into and out
   of a quotation.
4. Qwen3 anything: pacing, group boundaries, level matching, word fixes. None
   of it has been run.
5. Whether the page layer imports and styles usefully in Resolve.

## 9. Where things live

- **Code**: `narrator/` — see §10.
- **Tests**: `tests/`.
- **User data** (`config.DATA_DIR`): settings JSON, pronunciation dictionary,
  `voices/kokoro/*.pt` + `.json` sidecars, Qwen designed voices.
- **Render cache**: per-render working directories keyed by the cache key;
  disposable.
- **Output**: alongside the source document, or a subfolder per document.

---

## 10. Module reference

Generated from the source, not from memory. `_name` = internal.

### `narrator/__init__.py` (7 lines)

_Narrator - turn documents into narrated audio, locally._


### `narrator/__main__.py` (44 lines)

_Entry point. Dispatches between the GUI, the document cleaner, and the_

- `main(argv=None)` — 

### `narrator/audio.py` (561 lines)

_All ffmpeg work: format conversion, joining, chunk polishing,_

Constants: `AUDIO_FORMATS = {'MP3 (most compatible)': {'ext': 'mp3', 'lossy': True, '...`; `DEFAULT_FORMAT = 'MP3 (most compatible)'`; `SAMPLE_RATES = [16000, 22050, 24000, 44100, 48000]`; `BIT_DEPTHS = [16, 24]`; `EDITING_WAV_RATES = [44100, 48000]`; `EDITING_WAV_CHANNELS = {'Mono': 1, 'Stereo': 2}`; `DEFAULT_LOUDNESS_LUFS = -16.0`; `LOUDNESS_TRUE_PEAK = -1.5`; `LOUDNESS_RANGE = 11.0`

- `slider_index(pct)` — 0-100 in steps of 10 -> index 0-10 into the tables above.
- `join_intro_outro(audio_path, intro, outro, crossfade, log)` — Put an intro before and/or an outro after the finished narration,
- `finalize_render(result, cfg, folder, stem, log, existing_path=None)` — Turns one engine's raw result (master audio + cached chunks) into the
- `transcode_audio(src_path, dst_path, fmt_key, quality_pct, sample_rate, bit_depth, log, loudness=None)` — Convert `src_path` (whatever the engine produced) to the user's chosen
- `export_editing_wav(src_path, dst_path, sample_rate=48000, channels=1, loudness=None, bit_depth=16, log=print)` — Write an uncompressed PCM WAV sized for a video editor's timeline.
- `polish_chunk(src_path, dst_path, fade_ms=40)` — A chunk that sounds seamless spliced into a longer file can click at
- `build_video(audio_path, image_path, out_path, srt_path=None, width=1920, height=1080, log=print)` — Still image + audio, with an optional animated waveform and optional
- `join_audio(parts, out, log)` — 
- `duration_of(path)` — 
- `measure_loudness(path, target=DEFAULT_LOUDNESS_LUFS, log=print)` — First loudnorm pass: measure, encode nothing.
- `loudness_filter(target=DEFAULT_LOUDNESS_LUFS, measured=None)` — The loudnorm filter string, two-pass when a measurement is given.

### `narrator/chapters.py` (216 lines)

_Chapter markers: locating each heading of the source document inside a_

- `compute_chapters(last_render)` — Best-effort [{"title", "level", "seconds"}, ...] for the headings of
- `_locate_in_chunk(chunk, offset)` _(internal)_ — Which segment of `chunk` covers character `offset` of its text,
- `_format_time(seconds, force_hours=False)` _(internal)_ — 
- `format_youtube_chapters(chapters, intro_label='Introduction')` — The description-box text YouTube parses into a chapter list.
- `_chapter_bounds_ms(chapters, total_seconds)` _(internal)_ — [(title, start_ms, end_ms), ...] -- each chapter runs to the next
- `write_ffmetadata(chapters, total_seconds, path)` — FFMETADATA1 chapter file ffmpeg can mux into a container (m4a).
- `embed_chapters_m4a(audio_path, chapters, total_seconds)` — 
- `embed_chapters_mp3(audio_path, chapters, total_seconds)` — 
- `embed_chapters(audio_path, chapters, total_seconds)` — Dispatches on the file extension. Raises RuntimeError with a plain

### `narrator/chunkmap.py` (123 lines)

_The chunk map: seeing how a document was divided, and deciding what_

Constants: `CHUNK_COLOURS = ['#eef4fb', '#f4eef9', '#eef9f1', '#fbf4ee', '#f9eef2', '...`; `CHUNK_COLOURS_HOVER = ['#cfe0f5', '#e2cff2', '#cff2da', '#f5e2cf', '#f2cfd9', '...`

- `colour_for(index, hover=False)` — 
- `chunking_fingerprint(chunks)` — Identifies the exact division a set of overrides was made against.
- `reconcile(stored, chunks)` — Return (overrides, dropped) for the current chunking.
- `store(overrides, chunks)` — The saveable form of a set of overrides.
- `chunk_voices_from(overrides, quote_voice, is_quote, count)` — Build the per-chunk voice list the engine takes.
- `spread_voices(voices, count)` — Assign `voices` across `count` chunks in order, in even runs.

### `narrator/config.py` (462 lines)

_Paths, settings, voice catalogues, and engine detection._

Constants: `EDGE_VOICES = [('en-US-AndrewNeural', 'Andrew - warm American male (bes...`; `KOKORO_VOICES = [('af_heart', 'Heart - warm American female (best default...`; `QWEN_VOICES = [('A measured male academic in his fifties, neutral trans...`; `SAMPLE_TEXT = 'The digital twin is not a copy of a thing. It is a claim...`; `APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`; `SETTINGS_FILE = os.path.join(APP_DIR, 'narrator_settings.json')`; `VENV_CANDIDATES = {'kokoro': ['kokoro-env', 'kokoro_env', 'venv-kokoro'], '...`; `_EXTERNAL_CACHE = {}`; `DATA_DIR = os.path.join(APP_DIR, 'narrator_data')`; `SETTINGS_FILE = os.path.join(DATA_DIR, 'narrator_settings.json')`; `PRONOUNCE_FILE = os.path.join(DATA_DIR, 'narrator_pronunciations.json')`; `CACHE_ROOT = os.path.join(DATA_DIR, 'cache')`; `VOICES_DIR = os.path.join(DATA_DIR, 'voices')`; `_WORKER_PRONUNCIATIONS = None`

- `_venv_python(folder)` _(internal)_ — Path to the interpreter inside a venv folder, or None.
- `_module_in(python_exe, module)` _(internal)_ — Ask another interpreter whether it can import a module.
- `env_roots()` — Folders searched for kokoro-env / qwen-env, most specific first.
- `venv_candidates(engine_key)` — Every interpreter that might host this engine, in priority order:
- `forget_engine_probes()` — Drop cached detection results (after the environments folder or a
- `external_python(engine_key)` — Interpreter for an engine that lives in its own venv, or None if the
- `_installed(*module_names)` _(internal)_ — 
- `have_edge()` — 
- `have_kokoro()` — 
- `have_qwen()` — 
- `have_ffmpeg()` — 
- `slugify(value, limit=40)` — Make a string safe for a filename on every OS.
- `run_stamp()` — 
- `default_output_root()` — One central folder for everything this app produces.
- `_migrate_into_data_dir(old_path, new_path)` _(internal)_ — Move a settings/pronunciation file from beside the script (where older
- `load_settings()` — 
- `save_settings(data)` — 
- `load_pronunciations()` — word (lowercase) -> IPA phoneme string. Applies to Kokoro only; the
- `save_pronunciations(data)` — 
- `load_podcast_settings()` — 
- `save_podcast_settings(data)` — 
- `load_episodes()` — 
- `save_episodes(episodes)` — 
- `load_projects()` — 
- `save_projects(projects)` — 
- `output_paths(root, source_path, engine_key, voice_id, is_sample, use_subfolders=False)` — Where a rendered file goes.
- `document_folder(root, source_path, use_subfolders=False)` — 
- `cache_dir(engine_key, voice_id, speed, text)` — Per-settings cache, content-addressed and independent of wherever
- `unique_path(path)` — Last-resort guard: never silently clobber an existing file.
- `_no_window()` _(internal)_ — 

### `narrator/documents.py` (925 lines)

_Document loading and cleaning (formerly prep_for_tts.py)._

Constants: `BACK_MATTER = ['references', 'bibliography', 'works cited', 'reference ...`; `FRONT_MATTER = ['table of contents', 'contents', 'list of figures', 'lis...`; `SPEAK_AS = [('\\bet\\s+al\\.\\s*', 'and colleagues '), ('\\be\\.\\s*...`; `CITATION_PATTERNS = [('\\s*\\[\\s*\\d+(?:\\s*[-–,;]\\s*\\d+)*\\s*\\]', 'brack...`; `PAREN_WITH_YEAR = re.compile('\\s*\\([^()]{0,200}?\\b(?:1[6-9]\\d{2}|20\\d{...`; `_CITE_LEAD = re.compile('^\\s*(?:see\\s+also\\s+|see\\s+|cf\\.?\\s*|e\...`; `URL_PATTERN = re.compile('https?://\\S+|www\\.\\S+|doi:\\s*\\S+', re.I)`; `QUOTE_MARK = '\ue000'`; `TITLES = 'Dr|Mr|Mrs|Ms|Prof|Sr|Jr|St|Rev|Hon|Gen|Col|Lt|Sgt|Capt|A...`; `CHUNK_MODES = ('parts', 'tokens', 'chars')`; `DEFAULT_CHARS_PER_TOKEN = 1.05`; `TEXT_EXTENSIONS = {'.txt'}`; `MARKDOWN_EXTENSIONS = {'.md', '.markdown'}`; `CONVERTIBLE_EXTENSIONS = {'.docx', '.odt', '.html', '.htm', '.tex', '.epub'}`

- `_looks_like_citation(inner)` _(internal)_ — True if a parenthetical is a reference rather than ordinary prose.
- `load(path)` — Read a document into raw text, converting via pandoc if needed.
- `normalise(text)` — Undo converter artefacts before any pattern matching happens.
- `_have(binary)` _(internal)_ — True if `binary` is runnable from PATH. Uses shutil.which, not a
- `cut_back_matter(text, log)` — Drop everything from the first References/Bibliography heading onward.
- `_looks_like_heading(line)` _(internal)_ — 
- `drop_front_matter_sections(text, log)` — Remove TOC / list-of-figures style sections (heading + its body).
- `handle_tables(text, mode, log)` — Markdown/grid tables read as gibberish aloud. Remove, describe, or narrate.
- `_narrate_table(rows, index)` _(internal)_ — 
- `strip_citations(text, log)` — 
- `strip_urls(text, log)` — Remove URLs. Short 'see <link> for details' sentences go entirely -
- `handle_lists(text, log)` — Turn bullet and numbered list items into standalone sentences.
- `strip_quote_marks(text)` — Remove the marker unconditionally. Called on every piece of text on
- `strip_markdown(text, log, mark_quotes=False)` — Remove syntax that would be read aloud as punctuation soup.
- `handle_headings(text, keep, log, headings_out=None)` — Convert headings into spoken section transitions, remove them, or
- `expand_abbreviations(text, log)` — 
- `tidy(text, log)` — 
- `chunk(text, size)` — Pack sentences into chunks under `size` characters, never mid-sentence.
- **class `DocumentLoadError`** — A document couldn't be read or converted (missing pandoc, corrupt
- `clean_document(path, tables='describe', keep_headings=False, headings_out=None, mark_quotes=False)` — Run the full cleaning pipeline on one file.
- `split_sentences(text)` — Split on sentence ends, protecting initials, decimals and titles.
- `chunk_limit_for(text, mode, value, engine_cap, chars_per_token=DEFAULT_CHARS_PER_TOKEN)` — The character limit to hand chunk_text(), whichever way the user
- `chunk_text(text, size)` — Pack whole sentences into chunks under `size` characters.
- `chunk_text_with_voices(text, size)` — chunk_text_with_kinds, but a quotation never shares a chunk with the
- `split_quote_blocks(text)` — [(text, is_quote), ...] -- consecutive runs of quoted and unquoted
- `chunk_text_with_kinds(text, size)` — chunk_text, plus what kind of boundary each split lands on.
- `read_text_file(path, mark_quotes=False)` — Read a source document as clean, speakable text.
- `_read_text_file_uncached(path, ext, mark_quotes=False)` _(internal)_ — 
- `_read_plain(path)` _(internal)_ — 
- `clean_main(argv)` — 

### `narrator/engines.py` (979 lines)

_The three TTS engines and the cross-environment worker bridge._

Constants: `QWEN_DESIGN_REPO = 'Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign'`; `QWEN_CLONE_REPO = 'Qwen/Qwen3-TTS-12Hz-1.7B-Base'`; `QWEN_CLONE_REPO_SMALL = 'Qwen/Qwen3-TTS-12Hz-0.6B-Base'`; `QWEN_REFERENCE_TEXT = 'This is a short reference recording. It is made once, fr...`; `_QWEN_TOKENS_PER_SEC = 12`; `QWEN_GROUP_CHARS = 250`; `QWEN_GROUP_GAP = 0.25`; `QWEN_SAMPLING = {'temperature': 0.6, 'subtalker_temperature': 0.6, 'top_k...`; `KOKORO_LANGUAGES = {'a': 'American English', 'b': 'British English', 'e': 'S...`; `KOKORO_LANGUAGE_EXTRA_DEPS = {'j': 'misaki[ja]', 'z': 'misaki[zh]'}`; `KOKORO_TOKEN_LIMIT = 510`; `KOKORO_TARGET_TOKENS = 500`

- `run_edge(chunks, voice, speed_pct, log, want_subtitles=False)` — Generates audio, caching every chunk on disk as it goes.
- `rejoin_master(chunk_paths, workdir, gap_seconds, log)` — Rebuild a master audio file from a (possibly just-edited) list of
- `_lay_out(arrays, gaps, rate)` _(internal)_ — Concatenate audio pieces with `gaps[k]` seconds of silence after the
- `_join_chunk_wavs(chunk_paths, chunk_texts, workdir, gaps=None, pacing=None)` _(internal)_ — Join per-chunk WAV files into one master, with the silence each join
- `_apply_overrides(pipeline, log)` _(internal)_ — Load the custom pronunciation dictionary into a pipeline's lexicon.
- `_run_kokoro_local(chunks, voice, speed, workdir, log, chunk_kinds=None, chunk_voices=None)` _(internal)_ — 
- `qwen_sampling_settings()` — QWEN_SAMPLING with any user overrides applied. Unknown keys are
- `qwen_group_chars()` — Characters per generation within a chunk. Bigger = fewer separate
- `qwen_voice_fingerprint(description, take=1)` — Stable id for one designed voice: same description + take -> same
- `qwen_voice_dir(description, take=1)` — 
- `qwen_voice_exists(description, take=1)` — 
- `_qwen_device_kwargs(log)` _(internal)_ — 
- `_free_gpu()` _(internal)_ — Return freed GPU memory after the caller has dropped its last
- `ensure_qwen_voice(description, take, log, device_kwargs=None)` — Return (reference_wav_path, reference_text) for a designed voice,
- `_run_qwen_local(chunks, description, speed, workdir, log, take=1, chunk_kinds=None, clone_repo=None)` _(internal)_ — 
- `_run_worker_job(python_exe, job, log, label=None)` _(internal)_ — Shared mechanics for running part of this file inside another
- `_run_via_worker(python_exe, engine_key, chunks, voice, speed, workdir, log, extra=None)` _(internal)_ — Run an engine inside the interpreter that actually has it installed.
- `measure_kokoro_phonemes_local(texts, log=None)` — Exact phoneme-string length for each text, using the same G2P
- `measure_kokoro_phonemes(texts, log)` — measure_kokoro_phonemes_local, run wherever kokoro actually is.
- `list_kokoro_voices(log)` — Every voice file currently in the Kokoro-82M repo on Hugging Face --
- `fetch_kokoro_voices(log)` — list_kokoro_voices, run wherever huggingface_hub (a kokoro
- `fetch_all_kokoro_voices_local(log)` — Download every voice file in the Kokoro-82M repo into the Hugging
- `fetch_all_kokoro_voices(log)` — fetch_all_kokoro_voices_local, run wherever kokoro's dependencies
- `blend_kokoro_voice(specs, out_path, label, log)` — blend_kokoro_voice_local, run wherever torch and the Hugging Face
- `run_kokoro(chunks, voice, speed, log, chunk_kinds=None, chunk_voices=None)` — 
- `run_qwen(chunks, description, speed, log, take=1, clone_repo=None, chunk_kinds=None)` — 
- `worker_main(jobfile)` — Entry point when this file is run by another environment's Python.

### `narrator/estimate.py` (180 lines)

_How long a render is going to take._

Constants: `MAX_HISTORY = 5`

- `format_duration(seconds)` — Seconds -> a phrase a person can act on.
- `load_rates()` — 
- `remembered_rate(engine_key)` — Characters per second of wall clock, from previous runs, or None.
- `remember_rate(engine_key, chars_per_second)` — Record one completed run's rate, keeping the last MAX_HISTORY.
- **class `Estimator`** — Tracks generation speed across a render and reports what is left.
  - `upfront(self)` — A rough estimate from remembered runs, or None if this engine has
  - `timing(self, chars)` — 
  - `record(self, chars, seconds)` — 
  - `rate(self)` — Characters per second so far, or None if nothing was generated
  - `progress(self, chars_done)` — A line for the log, or None while there is nothing to say.
  - `finish(self)` — Remember this run's rate for next time. Only called on a run that

### `narrator/library.py` (82 lines)

_The project library: a persisted, per-document record of the settings_

Constants: `STATUS_ORDER = ['not_started', 'prepared', 'rendered', 'published']`; `STATUS_LABELS = {'not_started': 'not started', 'prepared': 'prepared', 'r...`

- `_label(path)` _(internal)_ — 
- `touch(path, cfg=None, status=None, output=None)` — Add or update the entry for `path`. `cfg`, if given, REPLACES the
- `remove(path)` — 
- `all_projects()` — Every known project, most recently touched first.
- `relative_time(ts)` — 

### `narrator/pacing.py` (198 lines)

_How long the silences are, where they go, and keeping the level steady_

Constants: `DEFAULT_PACING = {'sentence_gap': 0.12, 'paragraph_gap': 0.45, 'match_leve...`

- `pacing_settings()` — DEFAULT_PACING with any user overrides from narrator_settings.json
- `pacing_fingerprint()` — A short string that changes whenever a setting here would change the
- `save_pacing(pacing)` — Persist the pacing block, leaving every other setting alone.
- `gap_for(kind, pacing=None)` — 
- `gaps_for(kinds, pacing=None)` — [PARAGRAPH, SENTENCE, ...] -> [0.45, 0.12, ...]
- `kinds_from_indices(indices)` — Boundary kinds from a list of paragraph numbers, one per piece.
- `normalise_gaps(gaps, n_boundaries, fallback=0.0)` — Coerce whatever a caller passed -- a single number (the old
- `_rms(x)` _(internal)_ — 
- `match_levels(arrays, max_db=3.0, floor=1e-05)` — Nudge each piece's loudness toward the median of all of them, by at

### `narrator/pipeline.py` (311 lines)

_Engine registry and the render pipeline: which engine runs, and how_

Constants: `ENGINES = {'Kokoro (offline, best all-round)': {'key': 'kokoro', 'd...`; `ENGINE_BY_KEY = {s['key']: s for s in ENGINES.values()}`

- `resplice_chunk(last_render, chunk_index, new_text, log)` — Regenerate exactly one chunk of an already-finished render and splice
- `resplice_segment(last_render, chunk_index, seg_index, new_text, log, retry=0, finalize=True)` — Re-record ONE sentence of a finished take and splice it into its
- `rebuild_take(last_render, log, message='Rebuilding the full take...')` — Rejoin the (possibly edited) chunks into a master and re-export the
- `fix_word_everywhere(last_render, word, log, respelling=None, replacement=None, progress=None)` — Correct one word in every sentence of a take that says it.

### `narrator/pronunciation.py` (234 lines)

_Pronunciation scanning and the custom lexicon (Kokoro only)._

Constants: `WORD_PATTERN = re.compile("[A-Za-z][A-Za-z'\\-]*")`; `_SKIP_SHORT = {'a', 'i'}`

- `_looks_like_acronym(word)` _(internal)_ — All-caps, 2+ letters, no vowspace -- SCADA, PLC, NASA, IoT excluded
- `spell_out(word)` — A.C.R.O.N.Y.M. form that forces letter-by-letter reading.
- `parse_pieces_with_stress(text)` — 'an on nim *my nation' -> (['an','on','nim','my','nation'], 3)
- `respell_to_ipa(pieces, stress_on=0)` — Build a lexicon override from ordinary words, not raw IPA.
- `acronym_ipa(word)` — IPA for reading `word` one letter at a time, suitable for the lexicon.
- `scan_pronunciation(text, overrides=None)` — Run Kokoro's real G2P lookup over every distinct word in the text.
- `pronunciation_fingerprint(text, overrides=None)` — A short string identifying which custom pronunciations actually apply

### `narrator/publish.py` (193 lines)

_Podcast RSS feed and transcript export._

Constants: `ITUNES_NS = 'http://www.itunes.com/dtds/podcast-1.0.dtd'`; `MIME_TYPES = {'.mp3': 'audio/mpeg', '.m4a': 'audio/mp4', '.wav': 'audi...`; `WIDELY_SUPPORTED = {'.mp3', '.m4a'}`; `REQUIRED_CHANNEL_FIELDS = {'title': 'podcast title', 'author': 'author name', 'emai...`

- `_itag(tag)` _(internal)_ — 
- `mime_type_for(path)` — 
- `missing_channel_fields(settings)` — 
- `_duration_str(seconds)` _(internal)_ — 
- `episode_from_render(last_render, title, description)` — Build an episode record from a just-finished real render (a
- `add_episode(episode)` — Insert or replace (by guid -- the same output file republished
- `remove_episode(guid)` — 
- `build_feed_xml(settings, episodes)` — The full RSS document as a string, from channel settings + episode
- `feed_path(audio_root)` — 
- `write_feed(audio_root)` — Rebuild podcast.xml in the output root from current settings +
- `export_transcript(source_path, out_dir)` — Clean `source_path` exactly the way narration does, except headings

### `narrator/segments.py` (459 lines)

_Sentence-level structure of a render, and the splice that replaces one_

Constants: `_WORD = re.compile("[\\w']+")`

- `sidecar_path(chunk_path)` — 
- `save_segments(chunk_path, segments)` — 
- `load_segments(chunk_path, text=None, duration=None)` — Segments for a chunk file, or -- when no sidecar exists (chunk was
- `segments_from_pieces(pieces, rate, gap_seconds=0.0, merge_short=True)` — Build segments from a list of (text, audio_array) already laid out
- `segments_from_word_srt(chunk_text, srt_path, split_sentences)` — edge-tts writes one cue per spoken word. Walk the sentences of the
- `group_sentences(text, limit)` — Sentences packed into groups of at most `limit` characters, whole
- `group_sentences_with_kinds(text, limit)` — group_sentences, plus the kind of each join between groups.
- `_read(path)` _(internal)_ — 
- `_rms(x)` _(internal)_ — 
- `_resample(x, src, dst)` _(internal)_ — 
- `replace_span(chunk_path, start, end, new_audio_path, out_path, fade_ms=20, max_gain_db=6.0)` — Write out_path = chunk audio with [start, end] seconds replaced by the
- `apply_replacement(segments, index, new_text, new_span_end, new_chunk_duration)` — Rewrite one segment after replace_span and shift the ones after it.
- `export_span(chunk_path, start, end, out_path)` — Write just [start, end] of a chunk to its own WAV, for listening.
- `flat_segments(result)` — Every sentence of a take, in order, timed against the FINISHED file.
- `build_manifest(last_render)` — Everything the timeline editor needs, with absolute times: chunk
- `manifest_path(last_render)` — 
- `write_manifest(last_render)` — 
- `load_manifest(path)` — Rebuild a last_render dict from a manifest, so a take can be fixed
- `check_take(last_render)` — What is missing before a loaded take can be fixed.
- `find_manifests(folder)` — Every take manifest in a folder, newest first.

### `narrator/setup_engines.py` (360 lines)

_Create the engine environments automatically._

Constants: `ENGINE_PYTHON = '3.12'`; `TORCH_INDEX_CUDA = 'https://download.pytorch.org/whl/cu128'`; `ENGINE_SPECS = {'kokoro': {'folder': 'kokoro-env', 'label': 'Kokoro (off...`; `EXTERNAL_TOOLS = {'ffmpeg': 'Joins audio, converts formats, builds video. ...`; `_DOWNLOAD_START = re.compile('^\\s*Downloading\\s+(\\S+?)(?:\\.whl\\.metada...`; `_DOWNLOAD_DONE = re.compile('^\\s*[━╺]+\\s+[\\d.]+/[\\d.]+\\s*(kB|MB|GB)')`; `_UNIT_BYTES = {'kB': 1000, 'MB': 1000000, 'GB': 1000000000}`; `_MIN_NOTABLE_BYTES = 300000`

- `_run(cmd, log, progress=None, **kw)` _(internal)_ — Run a command, streaming its output as it arrives rather than
- `env_path(engine_key)` — Where this engine's environment is (or would be) built: inside the
- `_can_import(exe, module)` _(internal)_ — 
- `engine_status(engine_key)` — (exists, python_path, importable) for one engine environment.
- `create_environment(engine_key, log=print, progress=None, use_gpu=True)` — Build one engine environment from scratch. Returns True on success.
- `check_all(log=print)` — Report what's set up without changing anything.
- `main(argv=None)` — 

### `narrator/subtitles.py` (270 lines)

_Subtitle generation._

Constants: `DEFAULT_PAGE_CHARS = 1200`; `DEFAULT_PAGE_WRAP = 60`

- `_srt_time(seconds)` _(internal)_ — 
- `_parse_srt_time(text)` _(internal)_ — 
- `merge_subtitles(audio_parts, srt_parts, out_path)` — Concatenate per-chunk SRT files, shifting each by the real duration
- `_chunk_srt_time(seconds)` _(internal)_ — 
- `build_chunk_srt(texts, durations, out_path, gap_seconds=0.0, offset=0.0)` — One caption per chunk, timed from the exact durations the engine
- `shift_srt(path, offset)` — Move every timestamp in an SRT later by `offset` seconds, in place.
- `group_pages(segments, total_duration, page_chars=DEFAULT_PAGE_CHARS)` — Flat, absolutely-timed sentences -> pages.
- `wrap_page(text, width=DEFAULT_PAGE_WRAP)` — Break a page into lines at word boundaries.
- `build_page_srt(pages, out_path, wrap=DEFAULT_PAGE_WRAP)` — Write the page layer as an SRT.
- `page_srt_for_result(result, out_path, page_chars=DEFAULT_PAGE_CHARS, wrap=DEFAULT_PAGE_WRAP)` — The page layer for a finished render, timed against the output file.

### `narrator/ui.py` (3797 lines)

_The tkinter application: window, dialogs, and all user interaction._

- `launch()` — 

  Nested (defined inside `launch()`):

  - `_scrollable_tab(nb, title)` — A notebook tab whose content scrolls vertically once it doesn't
  - `load_source_path(path)` — Everything pick_file does once it has a path -- shared with
  - `pick_file()` — 
  - `change_root()` — 
  - `_current_take()` — 
  - `_remember_take(*_)` — 
  - `on_speed(_=None)` — 
  - `extra_voices_for(engine_key)` — 
  - `spec()` — 
  - `refresh_voices(_=None)` — 
  - `_remember_voice(*_)` — 
  - `on_voice_pick(_=None)` — 
  - `chosen_voice_id()` — 
  - `current_chunk_mode()` — 
  - `chunk_setting_value()` — 
  - `describe_chunks(*_)` — 
  - `refresh_chunk_mode(*_)` — 
  - `on_chunk_change(*_)` — 
  - `on_chunk_target_change(*_)` — 
  - `do_measure_tokens()` — Replace the estimated characters-per-token ratio with the real
  - `refresh_quote_voices(*_)` — The quote list is the narration list, minus nothing -- picking
  - `save_quote_voice(*_)` — 
  - `refresh_option_visibility(*_)` — 
  - `refresh_format(*_)` — 
  - `refresh_wav_row()` — 
  - `pick_video_image()` — 
  - `refresh_video_row(*_)` — 
  - `save_page_settings(*_)` — 
  - `refresh_page_row(*_)` — 
  - `save_loudness(*_)` — 
  - `refresh_loud_row(*_)` — 
  - `persist_output_settings(*_)` — 
  - `log(msg)` — 
  - `drain()` — 
  - `clear_log()` — 
  - `set_running(on)` — 
  - `render(cfg, chunks, voice, is_sample, chunk_kinds=None, chunk_voices=None)` — Renders from a settings snapshot only. Must not touch widgets:
  - `render_document(cfg)` — One document start to finish, from a settings snapshot only.
  - `work(mode, cfg)` — 
  - `work_queue(paths)` — Render several library documents back to back, each with its
  - `start_queue()` — 
  - `build_cfg()` — Every widget value the render needs, read on the main
  - `start(mode)` — 
  - `reveal(path)` — 
  - `reveal_file(path)` — Same as reveal(), but for a single file that already exists --
  - `open_folder()` — 
  - `open_kokoro_voice_finder()` — Query Hugging Face for the current full Kokoro voice roster and
  - `open_pronunciation_dialog()` — 
  - `compose_voice_description(gender, age, accent, pace, tone, extra)` — 
  - `open_voice_builder()` — 
  - `open_take_dialog()` — Reopen a finished take so it can be fixed after the fact.
  - `open_chunk_map()` — Show how the document was divided, and assign voices per chunk.
  - `open_voice_designer()` — Make a custom Kokoro voice by blending the stock ones.
  - `open_fix_word_dialog(prefill='')` — Correct one word everywhere the take says it.
  - `open_fix_chunk_dialog()` — 
  - `convert_audio_to_wav()` — Standalone converter: point it at any audio file and get an
  - `open_preferences_dialog()` — Settings true across every document, not just the current
  - `current_take()` — Whichever finished take the Publish tab is pointed at. After a
  - `refresh_publish_tab(*_)` — 
  - `do_publish()` — 
  - `do_export_transcript()` — 
  - `do_generate_chapters()` — 
  - `do_embed_chapters()` — 
  - `refresh_library_list(*_)` — 
  - `selected_project_paths()` — 
  - `selected_project_path()` — 
  - `load_project_into_ui(entry)` — 
  - `do_load_selected()` — 
  - `do_remove_selected()` — 

### `narrator/voices.py` (208 lines)

_Custom Kokoro voices, made by blending the stock ones._

Constants: `KOKORO_REPO = 'hexgrad/Kokoro-82M'`; `CUSTOM_VOICES_DIR = os.path.join(DATA_DIR, 'voices', 'kokoro')`

- `slugify_voice(name)` — 
- `voice_path(name)` — 
- `meta_path(pt_path)` — 
- `lang_code_for(voice)` — Which Kokoro pipeline a voice belongs to: 'b' British, 'a' American.
- `lang_for_sources(names)` — A blend is British only if everything in it is.
- `normalise_weights(specs)` — [(name, weight), ...] -> [(name, share)] summing to 1.
- `blend_tensors(packs, weights)` — Weighted average of voice packs.
- `blend_kokoro_voice_local(specs, out_path, label=None, log=print)` — Download the named stock voices, blend them by weight, save the .pt.
- `list_custom_voices()` — [(path, label, description)] for every blend saved on this machine.
- `delete_custom_voice(path)` — Remove a blend and its sidecar. Returns True if anything was removed.

### `narrator/wizard.py` (296 lines)

_A first-run setup wizard._

- `needs_wizard()` — True if neither offline engine is set up yet -- the condition the app
- `run_wizard(root)` — Show the wizard as a modal sequence of pages inside `root`. Returns

### `narrator/words.py` (180 lines)

_Finding one word across a finished take, and fixing every place it says_

Constants: `WORD_RE = re.compile("[^\\W\\d_][\\w'\\u2019-]*", re.UNICODE)`

- `words_in(text)` — Every word of a sentence, in order, with its character span.
- `normalise(word)` — The form two spellings of the same word share, for matching.
- `_word_pattern(word)` _(internal)_ — Whole-word, case-insensitive match for `word`.
- `count_in(text, word)` — 
- `substitute(text, word, replacement)` — Replace every whole-word occurrence of `word` with `replacement`.
- `segments_of(result, chunk_index)` — The sentence spans of one chunk, from the render or its sidecar.
- `occurrences(result, word)` — Every sentence in a take that says `word`.
- `distinct_words(result, min_length=2)` — Every distinct word in a take, with how often it is said.
- `plan_fix(result, word, engine_key, replacement=None)` — What fixing `word` would involve, without doing any of it.
