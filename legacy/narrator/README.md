# Narrator

Turn documents into narrated audio, entirely on your own machine.

Reads `.docx`, `.odt`, `.html`, `.tex`, `.epub`, `.md` and `.txt`, strips the
things that read badly aloud (citation markers, reference lists, tables,
markdown syntax), narrates with a local TTS engine, and optionally produces
subtitles, per-sentence audio, an editing-ready WAV, and a simple video.

---

## Running it

**Windows:** double-click `Start Narrator.bat`.

If you don't have the environments set up yet, or you're on Mac/Linux:

```
python Narrator.py
```

Both do the same thing. The `.bat` additionally activates `kokoro-env` first
if it exists, which is what makes the pronunciation checker available.

The window has four tabs and a menu bar. **Document**: pick your source
file and how it's chunked. **Voice**: engine, voice, speed, and whatever
that engine unlocks (Qwen3's take/build-a-voice; Kokoro's pronunciation
check; edge's subtitles). **Output**: where files go, format/quality, and
the video/subtitle/kept-chunks extras. **Publish**: publish your most
recent take to the podcast RSS feed, or export a transcript of the current
document (see "Publishing" below). **Generate / Hear a sample / Compare
all voices / Fix a chunk or sentence... / Open folder** stay visible under
the tabs no matter which one you're on. Rarer setup and utility actions
live in the menu bar: **Settings -> Preferences...** (engines and
environments folder, plus a Podcast tab for channel-wide RSS settings) and
**Tools** (Clean text only, Audio -> WAV, Open output folder).

**Command line, no GUI.** Everything the app does to produce audio can be
scripted:

```
python -m narrator web                         open it in a browser
python -m narrator settings                    what a render accepts
python -m narrator render chapter.md --voice af_heart --out audio/
python -m narrator queue                       re-render your library
python -m narrator transcribe interview.mp3    audio back into text
python -m narrator --clean dissertation.docx --outdir cleaned/
```

`render` takes the same settings the app does -- run `settings` to see
every field, its allowed values and what it means. Bad values are refused
with an explanation before anything starts.

---

## Installing an engine from the Voice tab

The engine dropdown lists every engine, whether or not it's installed.
Pick one you don't have yet and the controls below grey out, with a note
saying what it would download and a **Download and set up** button. The
progress appears in the log and on a bar; when it finishes, the engine
works straight away without restarting.

## Components and add-ons

**Tools -> Components and add-ons...** shows every optional piece, what
it unlocks, how big it is, and its licence. Narrator runs without any of
them -- features that need something say so and offer to install it,
rather than failing when you click.

Some install with one click (Pillow, faster-whisper, mutagen). Others are
ordinary programs you install yourself, with a link to the download page
(ffmpeg, espeak-ng, pandoc).

**mutagen** is a deliberate exception: it's only needed for chapter
markers inside mp3 files, and it's GPL-2.0, so it isn't bundled -- it's a
one-click optional install instead, the way Audacity handles ffmpeg.
Chapters in m4a files work without it.

## Setting up the engines


**The first time you launch it**, a short setup wizard offers to install
Kokoro and/or Qwen3-TTS — tick what you want, or "Skip for now." It only
appears once; after that, the same thing is always available from **"Set up
engines..."** in the main window, or from a terminal:

```
python -m narrator.setup_engines --check     see what's set up
python -m narrator.setup_engines kokoro      build one
python -m narrator.setup_engines qwen3
```

**edge-tts needs none of this** — it works the moment the app opens.

### What "installing" actually means here

This project stays under 200 KB by never bundling the engines or their model
weights. What the wizard/setup does instead is exactly what `pip` (Python's
package installer, the same mechanism behind `pip install anything`) already
does reliably: fetch the current release of each engine from PyPI, and let
the engine itself fetch its model weights from Hugging Face on first use
(Kokoro ~300 MB, Qwen3 several GB). Those are the same well-established,
versioned distribution channels the engines' own maintainers publish to —
building a separate download mirror would mean re-hosting files that are
already served reliably, and would need updating by hand every time either
project releases something new. Pointing at the real source keeps you on
whatever "latest" actually means at the moment you install.

The progress you see during setup reflects this honestly: pip announces each
real download by name and size the moment it starts, so the wizard shows
that — "Downloading torch (750 MB)..." — with an indeterminate bar for the
wait itself, rather than a fake smooth percentage. Pip doesn't reliably
report byte-by-byte progress once its output is captured by another program,
so a bar that pretended to tick evenly would be guessing, not measuring.

Setup can't install `ffmpeg`, `pandoc`, or `espeak-ng` — ordinary Windows
programs, not Python packages. `--check` (and the wizard) report whether
each is present and link to where to get it.

### On a "real" installer

An actual compiled Windows installer (a `.exe` you double-click, with the
classic Next / Next / Finish wizard and a Start Menu entry) is a genuinely
different thing from what's here, and building one reliably means compiling
and testing it *on Windows* — tools like PyInstaller don't cross-compile, so
running them anywhere else produces a binary for that other system, not for
Windows. That step hasn't been done. What ships instead is the wizard
described above, built the same way as the rest of the app and tested the
same way — no separate toolchain, but also not a literal `.exe`.

### Reusing environments from an older copy

The engine environments are found by folder name (`kokoro-env`, `qwen-env`)
beside the launcher — **or** in whatever folder you set as "Environments
folder" under **Settings -> Preferences...**. So to move to a new copy of the app
without downloading everything again, either move the two `*-env` folders in
next to the new `Narrator.py`, or point that setting at the old folder. Both
work: the app always runs an engine as `<env>\Scripts\python.exe -m narrator`,
which doesn't care where the environment folder lives.

Model weights never need moving. Kokoro and Qwen3 keep them in the Hugging
Face cache in your user profile (`%USERPROFILE%\.cache\huggingface`), which
every copy of the app shares.

### More Kokoro voices

The Voice tab ships with 7 curated Kokoro voices, but Kokoro itself has
more. **Find more voices...** (next to Check pronunciation, when Kokoro is
selected) checks Hugging Face for the current full list -- live, not a
fixed snapshot, so it stays current as Kokoro adds voices -- and lets you
add any of them. English ones (American/British) work immediately;
Spanish, French, Hindi, Italian, and Brazilian Portuguese also work right
away (espeak-ng, already set up here, handles them); Japanese and
Mandarin voices are listed too but need one more package first (the
dialog tells you exactly which `pip install` line). Needs internet only
for the search itself -- narrating still runs fully offline once a voice
is added, same as any other Kokoro voice.

### Administrator rights

Not needed, for anything here. Environments are created beside the app,
settings and output stay in the app's folder, and `pip` installs to your user
profile when it can't write anywhere else. The only thing to avoid is putting
the folder somewhere Windows itself protects (Program Files) — and, less
obviously, inside a OneDrive-synced folder, which will try to upload several
gigabytes of environment files.

## Where things go

```
Narrator/
├── Start Narrator.bat        double-click this
├── Narrator.py               same thing, cross-platform
├── narrator/                 the code
├── kokoro-env/               built via Settings -> Preferences (or elsewhere,
├── qwen-env/                 see "Reusing environments" above)
├── narrator_data/            settings, pronunciation dictionary,
│   ├── voices/               saved Qwen3 voices (reference clip + description)
│   └── cache/                per-chunk audio for resuming; safe to delete
└── narrator_output/          everything the app produces
```

`narrator_data/` and `narrator_output/` are created automatically, next to
the launcher. Your source documents can live anywhere — browse to them from
the app; output always lands in `narrator_output/`.

**Nothing here is tied to a fixed location.** Every path is worked out from
where this folder actually sits, so you can move or rename it, put it on
another drive, or keep it in a path with spaces, and it keeps working. If
you've pointed the output somewhere else and that place later disappears,
the app quietly falls back to `narrator_output/` rather than failing.

---

## The code

| File | What lives there |
|---|---|
| `__main__.py` | Entry point. Chooses GUI, `--clean`, or `--worker`. |
| `config.py` | Paths, settings, voice lists, engine detection. |
| `documents.py` | Reading and cleaning documents (was `prep_for_tts.py`). |
| `pronunciation.py` | The custom lexicon and the word scanner. |
| `subtitles.py` | Building and merging SRT files. |
| `audio.py` | Every ffmpeg operation: format conversion, joining, video. |
| `engines.py` | The three TTS engines and the cross-environment bridge. |
| `pipeline.py` | Engine registry; regenerating and re-splicing one chunk. |
| `ui.py` | The window and all dialogs. |
| `webapi.py` | A local HTTP API over the same modules, for the browser interface. Localhost only, token-protected. |
| `jobs.py` | Long operations as jobs: start, watch, cancel. |
| `tasks.py` | Publishing, chapters, transcripts -- the operations, without any interface around them. |
| `render_config.py` | Every setting a render takes: defaults, allowed values, validation. Settings arriving from anywhere are checked here. |
| `session.py` | What's being rendered and which takes exist. No UI code -- the whole render pipeline, the batch queue and the timeline's data model run headlessly. |
| `setup_engines.py` | Builds the Kokoro and Qwen3 environments. |

Two rules keep this working, and both matter more than they look:

**Only `ui.py` imports tkinter.** Kokoro and Qwen3 run inside their own
virtual environments, which may have no Tk installed at all. If tkinter were
imported at the top of a module the worker touches, those engines would
crash on import rather than run.

**The worker is invoked as a module, never by file path.** When the app needs
an engine that lives in another environment, it runs
`python -m narrator --worker <job.json>` in that environment's interpreter,
with `PYTHONPATH` pointed here. Running `narrator/engines.py` directly would
break its relative imports, and the package is deliberately *not* installed
into those environments — they only have their engine.

---

## Qwen3 voices: designed once, then cloned

A Qwen3 voice starts as a written description, but the description is not
what narrates. Qwen3's VoiceDesign model *samples* a voice that fits the
description — a different sample every time it's called — so using it
directly on every chunk gives you a narrator that changes every few seconds.
(That was a real bug in an earlier version.)

What happens now, following the workflow Qwen3-TTS's own documentation
recommends for a consistent voice:

1. The description is used **once** to have VoiceDesign read a short
   reference passage. That clip is saved under `narrator_data/voices/`.
2. The Base model turns the clip into a clone prompt.
3. Every chunk is generated by cloning that one clip, so every chunk is the
   same speaker.

Consequences worth knowing:

- The same description always gives the same narrator back, on every
  document, until you change the text of the description.
- If you don't like the narrator the description produced, don't rewrite the
  description — bump **Take** (next to the voice box). Each take is a separate
  saved voice; going back to an earlier take number brings that voice back.
- **"Hear a sample"** is the cheap way to audition a take before committing a
  whole document to it.
- This needs two models: `Qwen3-TTS-12Hz-1.7B-VoiceDesign` (only when a new
  voice is designed) and `Qwen3-TTS-12Hz-1.7B-Base` (for every render). Both
  download from Hugging Face on first use. They are loaded one after the
  other, never together. To use the lighter 0.6B Base model for cloning, add
  `"qwen_clone_repo": "Qwen/Qwen3-TTS-12Hz-0.6B-Base"` to
  `narrator_data/narrator_settings.json`.
- Qwen3 has no speed control of its own, so the Speed slider doesn't affect
  it; put pacing in the description ("unhurried", "brisk").

## Voice studio

**Tools -> Voice studio...** lists every Qwen3 voice you've built. Play
its reference clip, give it a short label, delete it, or load it into the
Voice tab (which sets the take too, since a description and take together
are what identify a voice).

**Audition a description** designs a voice and plays its reference clip
without narrating a whole document -- much faster than rendering a chapter
to find out whether you like the narrator.

**Clone from a recording** builds a voice from a few seconds of your own
speech. Record yourself, pick the file, and type exactly what you said --
Qwen3 matches the words against the audio to learn the voice. It's then
used exactly like any other voice. Nothing leaves your machine.

Deleting a designed voice is safe: re-rendering the same description and
take builds it again. A *cloned* voice can't be rebuilt without the
original recording, so keep that file.

## CustomVoice (preset speakers)

A third tab in the Voice studio, alongside auditioning a description and
cloning your own voice. **Fetch speaker list...** downloads Qwen3's
CustomVoice model (several GB, one time) to find out what studio
speakers it actually has -- the list isn't published anywhere else. Pick
one, add an optional instruction for how to read it ("speak slowly and
warmly"), and either use it right away or save it as a named preset.

A CustomVoice preset is just a remembered speaker + instruction -- unlike
a designed or cloned voice there's no reference clip or take involved,
since the speaker and instruction together are already the whole,
repeatable identity.

## The timeline

**Timeline...** opens the finished take as a waveform with every sentence
marked. Click anywhere to jump to that sentence, or drag to select a
range. The full text sits below with the current sentence selected, and
picking a line there moves the timeline to match -- both are views of the
same take.

With a sentence selected you can play just that span, edit its text and
re-record only it, re-roll it unchanged if it merely read oddly, or jump
straight to the pronunciation editor for a word that came out wrong.

With a sentence selected, the panel on the right also lists every word in
it with the pronunciation Kokoro is actually using, marked `*` if you've
overridden it, `~` if Kokoro is guessing (the word isn't in its
dictionary), or `!` if it can't say it at all. **Edit this word...** opens
the pronunciation editor on that word -- fix it, then re-record the
sentence to hear the change.

**Tools -> Open a take...** loads any earlier take from its
`.manifest.json`, so you can come back to something you rendered last
week and fix a sentence in it.

## Fixing one sentence

After a render, **"Fix a chunk..."** lists the chunks and, for the selected
chunk, its sentences with their start times. Pick the sentence that came out
wrong, edit its text if the wording or a respelling needs changing (Kokoro's
pronunciation dictionary applies here too), and **Regenerate this sentence**:
only that sentence is re-recorded, level-matched and crossfaded back into
the chunk, and the output file is rebuilt in place. **Try again (same
text)** re-rolls a sentence that was worded fine but read oddly. **Play
sentence** opens just that span in your audio player. This works for the
offline engines; edge-tts chunks fall back to whole-chunk regeneration.

Each output also gets a `<name>.manifest.json` beside it describing every
chunk and sentence with its timing -- the basis for the timeline editor.

## Splitting the document

**Split by** on the Document tab offers three ways to divide a document:
**Number of parts** (a count), **Kokoro tokens per part**, or
**Characters per part**.

A "Kokoro token" is one character of its phoneme string -- not a word or a
letter. Kokoro's hard limit is 510 per generation, with about 500 being
the sweet spot. **Measure tokens** works out the real characters-per-token
ratio for your specific document (it says "estimated" until you do, then
"measured"), so the chunk preview reflects your actual text rather than an
average.

Worth knowing for Kokoro specifically: it re-splits internally at 510
tokens no matter what you pick here, so this setting mostly controls
progress updates and resume points rather than how the audio sounds. It
only affects the sound if you make parts small enough to force splits
Kokoro wouldn't have made itself. For Qwen3-TTS, smaller parts genuinely
do reduce drift.

## The library

The Document tab remembers every document you've picked, with the
settings last used for it -- engine, voice, take, speed, chunking, output
format, everything. Picking a file adds it automatically; nothing needs
to be explicitly "saved." Each entry shows its status (not started /
prepared / rendered / published) and when it last changed. **Load
selected** (or double-click) brings a document's settings back exactly as
they were; **Remove from library** forgets an entry without touching the
document or anything already rendered from it.

**Render selected (queue)** renders several at once: Ctrl-click or
Shift-click to pick them, and each is rendered with its own saved
settings, back to back, unattended. A document that can't be rendered
(file moved, no settings saved yet, engine not installed here) is skipped
with a reason and the rest carry on. Come back to the log for a summary.

Every take a session produces stays available afterwards: the Publish tab
has a **Take to publish** picker, and publishing, chapters, and "Fix a
chunk" all act on whichever take is selected there -- so after a queue
run you can publish any of them, not just the last one to finish. (This
lasts for the session; it isn't remembered after closing the app.)

## Fixing a word that sounds wrong

**Tools -> Text tools -> Edit a word's pronunciation...** works on *any*
word, not just the ones the scanner flags. That matters: a word can be in
Kokoro's dictionary -- so never reported as unknown -- and still come out
wrong.

Type a word and the list filters as you go, showing each entry's current
phonemes. Words already overridden are marked with `*`. Selecting one
shows what Kokoro says for it now and where that came from: your
override, Kokoro's dictionary, or a guess for a word it doesn't know.

To change it, respell the word using ordinary words that sound right,
separated by spaces, with `*` before the stressed piece -- for example
`an on nim my *nation`. The preview shows what it will become before you
save.

## Audiogram

**Tools -> Audiogram layout...** lays out the animated waveform and bakes
it to a transparent overlay clip your editor only has to composite -- no
waveform recomputed per frame, which is what makes a Fusion/Reactor
audiogram slow.

Choose **linear** (a strip, bars or line, optionally mirrored) or
**polar** (a ring around a centre point you set). Position, size, inner
and outer radius, rotation pivot, colour, opacity, bar count and
smoothing are all adjustable, and the preview shows them against your
background image with the bounds, centre and pivot marked.

Export as VP9 `.webm` (default -- tiny files), ProRes 4444 `.mov` (what
most editors prefer), or a PNG sequence. **Crop to the audiogram's area**
is on by default: it renders roughly three times faster and much smaller,
and the app tells you the x/y to place it at. Cropping is skipped
automatically if you've rotated the figure.

### Animating a value

Any of the position, size, rotation, opacity or line-width values can be a
**formula** instead of a fixed number, worked out fresh for every frame.
Pick a value under "Animate a value over time", type a formula, and the
list below shows every name you can use -- filtered as you type, matching
both names and descriptions, so typing `loudness` finds the audio-reactive
ones. Double-click a name (or use "Insert selected name") to drop it in.
The line under the box tells you immediately whether the formula works and
what it currently evaluates to.

Time-based: `progress` runs 0 to 1 across the file, `t` is seconds,
`duration` is the total. Audio-reactive: `level`, `bass`, `mid` and
`treble` follow the sound right now. So:

```
rotation       30*progress                 slow turn across the episode
outer_radius   0.15 + 0.2*level            ring pulses with the audio
opacity        0.4 + 0.4*sin(tau*progress) fades in and out once
```

A formula that stops working falls back to that value's normal number
rather than ruining a long render. Note that an animated layout can't be
cropped on export, since it may move anywhere.

Settle the layout before exporting -- a baked overlay is fixed, which is
exactly why the controls are here.

## Converting and splitting audio

**Tools -> Convert -> Convert audio...** takes any audio file and gives
you format, quality (with the actual kbps shown as you move it), sample
rate, bit depth and channel count. **Quick editing WAV...** is still there
for the one-click 48 kHz mono WAV.

It can also split the result into numbered parts -- either every N minutes,
or keeping each part under a size limit. Only length can be set directly,
so a size limit is worked out from the converted file's real bitrate and
then checked: if a part still comes out over, it splits again more finely.
Parts land in a `<name>_parts` folder next to the file.

## Turning audio back into text

**Tools -> Convert -> Audio to text (transcribe)...** takes any speech
audio -- from this app or anywhere else -- and writes a transcript
(`.md`), optionally subtitles (`.srt`) and a guessed chapter list.

It needs one extra package the first time: `pip install faster-whisper`
(the app tells you if it's missing). Recognition runs entirely on your own
machine; the first run downloads the model you pick. Expect roughly the
length of the audio itself on a CPU, much less with a GPU.

The chapter marks here are guessed from long pauses, since recognised
speech carries no heading information -- treat them as a starting point,
unlike the chapter marks for your own renders, which come from your
document's real headings.

## Model parameters

**Settings -> Preferences... -> Model parameters** exposes every value the
installed models actually accept -- for Qwen3 that's temperature, detail
temperature, top-K, top-P and repetition penalty, each with its default
shown and a Reset. Kokoro and edge-tts don't expose generation parameters
beyond speed and voice, and the tab says so rather than offering knobs
that do nothing.

These override the simpler Expressiveness dial on the Pacing tab.

## Pacing

**Settings -> Preferences... -> Pacing** controls the silence between
parts. Each part already ends on its own natural pause, so the audio is
trimmed before the gap is added -- the number you set is the pause you
actually get, every time, rather than being added to however long the
model happened to trail off.

If narration sounds over-punctuated or metronomic, lower **Pause between
parts** (0.12s default). This matters much more when a document is split
into many small parts than when it's a few big ones.

**Expressiveness** (Qwen3 only) is the trade between a steady voice and a
lively reading: lower keeps the narrator sounding like one person across a
long file, higher gives more variation but a greater chance of the voice
shifting between parts.

## Intro and outro

**Settings -> Preferences... -> Intro / outro** takes an audio file for
before the narration, one for after, or both, plus a crossfade length.
They're joined onto every render from then on. Subtitles and chapter
marks are shifted to match automatically, so nothing runs early because
of the intro.

Volume isn't adjusted -- if your intro is much louder than the narration,
turn it down in the source file.

## Publishing

Fill in **Settings -> Preferences -> Podcast** once: title, author, owner
email, description, website, the URL where you'll host the audio files
(e.g. wherever you upload `narrator_output/` to), artwork, category,
language. These apply to every episode and autosave as you type.

On the **Publish** tab, once you have a take you're happy with: give it an
episode title (suggested from the filename) and notes, then **Publish this
take to the RSS feed**. This writes/updates `narrator_output/podcast.xml`
-- an iTunes-tagged RSS feed built fresh from every published episode each
time, which is what you point Spotify/Apple Podcasts/YouTube's podcast
feature at once it's uploaded. Publishing the same output file again
updates its existing entry instead of adding a duplicate. If a channel
field is still empty, publishing still works -- the log just notes what's
missing before you submit the feed anywhere. mp3 and m4a are the formats
podcast directories reliably accept; anything else publishes with a note
saying so.

**Export transcript (.md)** cleans the current document the same way
narration does, except headings come back as real Markdown headings
instead of being spoken or dropped -- a written companion page for search
engines and readers, not narrated audio. Tables come back as real Markdown
tables too, not the narrated description.

**Chapters**, further down the Publish tab: **Generate chapter list**
finds this document's own headings and matches each one against the
take's actual timing, formatted the way YouTube expects in its
description box (`0:00 Introduction`, `1:04 Next section`, ...) -- a
heading it can't confidently place is left out rather than guessed at.
**Embed chapters into audio file** writes the same chapters directly into
the output file itself (mp3 or m4a), so podcast apps that read embedded
chapters show them too, not just the YouTube description. mp3 embedding
needs one extra package: `pip install mutagen` (asked for plainly if it's
missing, nothing else changes).

## Feeding it into a video editor

Two things are built for this specifically:

**"Also save an uncompressed .wav"** writes a PCM WAV alongside the audio, at
48 kHz by default. This exists to remove a manual step: editors — DaVinci
Resolve's free version especially — handle compressed m4a/AAC unreliably
(silent tracks, missing waveforms, waveform-versus-playback desync), while
uncompressed PCM always decodes, and matching the timeline's sample rate
avoids the resampling that causes the desync.

It's converted from the engine's original output, not from the compressed
file, so no compression artifacts get baked into the file you edit against.

**"Audio → WAV..."** does the same conversion to any audio file you point it
at, including ones this app didn't create.

The video export is deliberately basic — a still image, a waveform, and
burned-in captions. Title cards, end cards, and anything shaped or styled
belong in a real editor; this just gets you a clean set of ingredients.
