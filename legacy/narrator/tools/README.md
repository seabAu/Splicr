# audiogrammify

A standalone drag-and-drop tool. Does not need Narrator installed —
just ffmpeg on PATH.

Drop one or more `.wav` files onto `audiogrammify.bat` (Windows) or run
`audiogrammify.sh` (Mac/Linux/WSL/Git Bash) with files as arguments. Each
gets a `.mp4` written beside it, same name.

It runs one fixed command — the "render small, scale up, sharpen" recipe:
`showwaves` at 1920x360/24fps, scaled to 1920x720, sharpened, composited
onto a solid green background — that's `Episode.wav` -> `Episode.mp4`,
ready to chroma-key out in Resolve or any editor. ~9 seconds of render
per minute of audio on the `ultrafast` preset it uses.

**Why solid green instead of alpha:** a solid background is simpler to
rely on than real transparency, since alpha depends on the receiving app
actually trusting the channel — a solid colour just needs an editor's key
tool. Set `BACKGROUND=""` at the top of the script for plain black
instead (ffmpeg's own default, no compositing step at all).

To change the look, edit the knobs at the top of `audiogrammify.sh` (size,
fps, colour, sharpen strength, background colour) — it's plain ffmpeg
commands, nothing generated or hidden. For real control over the shape
(rings, different visualisers, layered effects, live time estimates), use
**Tools -> Audiogram command builder...** in the full app instead; this
script is one fixed recipe from it, kept separate for when you just want
to drop a file and not open anything.

Requires bash. On Windows that's WSL or Git Bash (Git for Windows) — both
are common if ffmpeg is already on PATH. `audiogrammify.bat` finds
whichever is installed and runs the real script.

**Windows note:** the `.bat` wrapper was written and reviewed carefully
but could not be run on real Windows to confirm it end to end — the `.sh`
it calls has been. If it doesn't find your bash, run
`bash audiogrammify.sh "file.wav"` directly from WSL or Git Bash as a
fallback.

**A bug this had and doesn't any more, worth knowing if you edit the
background section:** `-shortest` as a plain ffmpeg *output* flag does
NOT reliably stop this specific graph shape — a still colour composited
under an audio-driven waveform via `overlay`. Tested directly: with only
the output flag, a 4-second source produced a render that ran to 38
seconds before being killed. The fix is `overlay`'s own `shortest=1`
parameter, which stops the composite at its shorter input correctly.
Both scripts (and Narrator's own builder) now use `overlay=...:shortest=1`
for this reason — if you write your own compositing graph, use the
filter's own shortest option, not just the output flag.
