# SPLICR long-document TTS

SPLICR is a local Python microservice that turns long text into one WAV file. It creates an
asynchronous job, splits the source at natural boundaries, calls one TTS provider request at a
time, checkpoints each raw PCM response, and assembles the successful chunks under one WAV
header.

Despite the source document's use of “transcription,” this service performs **speech synthesis**
(text to speech), not speech-to-text transcription.

## What is implemented

- FastAPI job submission, progress, retry, listing, and audio download endpoints
- A provider-neutral `TtsProvider` boundary with Gemini, Deepgram, and Inworld adapters
- UTF-8-byte- and provider-character-aware paragraph → sentence → clause → word fallback chunking
- Provider-specific chunk limits layered over the conservative 3,800-byte/350-word defaults
- Sequential provider calls, provider-specific pacing, and exponential backoff with jitter
- Durable SQLite job/chunk state and raw PCM checkpoints for restart-safe resumption
- Canonical mono, signed 16-bit, 24 kHz PCM and a single final WAV container
- A file-to-file CLI using the same pipeline
- A same-origin browser studio with provider/voice discovery, typed delivery presets, progress,
  retry, playback, download, and persisted job history
- Provider-neutral tone, five-step speaking pace, vocal-style, and deterministic non-verbal
  frequency controls
- Structured import for Markdown, UTF-8 text, JSON, DOCX, ODT, and legacy DOC documents
- Optional provider-neutral removal of standalone numeric citations such as `[123]`
- Preflight chunk visualization with semantic, heading-level, newline, and paragraph boundaries
- Durable paused/cancelled states, structured error codes, checkpoint resume, and partial WAV export
- Character-position progress and in-progress/completed playback in the browser studio

Gemini remains available as a Preview provider. Deepgram Aura-2 and Inworld TTS-2 are also
registered, and every provider's model and voice defaults can be changed through environment
variables.

## Run locally

Requirements: Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```powershell
Copy-Item .env.example .env
# Edit .env and set the key for each provider you intend to use.
uv sync --extra dev
uv run splicr serve --reload
```

Open `http://127.0.0.1:8000/` for the SPLICR studio. The generated interactive API remains at
`http://127.0.0.1:8000/docs`.

The studio populates every control from `/v1/providers`. Gemini and Inworld TTS-2 support directed
delivery; Deepgram exposes its native speaking-speed control but does not publish runtime
emotion/style/non-verbal controls. Tone and vocal style remain curated SPLICR presets rather than
an exhaustive provider vocabulary.

Provider credentials stay server-side:

- `GEMINI_API_KEY` is the Gemini API key.
- `DEEPGRAM_API_KEY` is sent with Deepgram's `Token` authorization scheme.
- `INWORLD_API_KEY` is the Base64 credential value supplied by the Inworld Portal; do not encode it
  again.

Deepgram and Inworld each impose a 2,000-Unicode-character request ceiling. SPLICR plans at a
1,900-character target and accounts for Inworld steering text before submitting a chunk. Both are
called sequentially by default, so a single SPLICR worker consumes one concurrent request slot.

Imported DOCX and ODT headings, emphasis, lists, quotations, tables, and paragraph boundaries are
normalized to Markdown-like structure. Gemini is directed to perform that structure without
speaking the formatting punctuation. Legacy `.doc` import requires LibreOffice or OpenOffice's
`soffice` executable; when it is unavailable the importer returns a specific, user-facing error.

Enable **Remove numeric citations** to exclude standalone references such as `[123]` from both the
chunk preview and synthesis. Numeric Markdown links and definitions remain intact.

Before creating a job, choose a preferred chunk boundary and select **Preview chunks**. Explicit
boundaries are honored whenever possible; an oversized section still falls back through semantic
sentence, clause, word, and Unicode-safe splitting so provider limits are never exceeded.

### Run with Docker

Build the image, then publish it only on the host loopback interface:

```powershell
docker build -t splicr-tts .
docker run --rm `
  --env-file .env `
  --publish 127.0.0.1:8000:8000 `
  --volume splicr-data:/data `
  splicr-tts
```

Open `http://127.0.0.1:8000/`. The container listens on `0.0.0.0` internally, but the explicit
`127.0.0.1` host publishing keeps this unauthenticated service off the LAN. Do not replace it with
an unrestricted host publish such as `-p 8000:8000` unless authentication and request-size
enforcement are placed in front of SPLICR. The `splicr-data` volume persists plaintext job data;
remove that volume when its jobs are no longer needed.

Submit a job:

```powershell
$body = @{
  text = Get-Content -Raw -Encoding UTF8 .\input_document.md
  provider = 'gemini'
  voice = 'Kore'
  instructions = 'Read as a calm, clear audiobook narrator.'
  controls = @{
    tone = 'warm'
    pace = 'slow'
    vocal_style = 'audiobook'
    nonverbal_frequency = 'occasional'
  }
} | ConvertTo-Json -Depth 3

$job = Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/v1/speech/jobs `
  -ContentType application/json `
  -Body $body

Invoke-RestMethod http://127.0.0.1:8000/v1/speech/jobs/$($job.id)
```

When `status` is `completed`, download the URL in `audio_url`.

The same pipeline can process a file without an HTTP client:

```powershell
uv run splicr synthesize .\input_document.md .\continuous_reading.wav `
  --voice Kore `
  --tone warm `
  --pace slow `
  --vocal-style audiobook `
  --nonverbal-frequency occasional `
  --instructions 'Read as a calm, clear audiobook narrator.'
```

## HTTP contract

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/` | Local browser studio |
| `GET` | `/health` | Liveness check |
| `GET` | `/v1/providers` | Provider defaults and capabilities |
| `POST` | `/v1/documents/import` | Normalize an uploaded document into structured text |
| `POST` | `/v1/speech/preview` | Preview exact chunk boundaries without creating a job |
| `GET` | `/v1/speech/error-codes` | List stable processing error codes and guidance |
| `POST` | `/v1/speech/jobs` | Queue a raw-text synthesis job |
| `GET` | `/v1/speech/jobs` | List recent jobs |
| `GET` | `/v1/speech/jobs/{id}` | Read status and progress |
| `POST` | `/v1/speech/jobs/{id}/pause` | Cooperatively pause after the active provider request |
| `POST` | `/v1/speech/jobs/{id}/resume` | Continue a paused job from completed checkpoints |
| `POST` | `/v1/speech/jobs/{id}/cancel` | Cancel without presenting partial audio as completed |
| `POST` | `/v1/speech/jobs/{id}/retry` | Resume a failed job from its checkpoints |
| `GET` | `/v1/speech/jobs/{id}/partial-audio` | Build a WAV from the contiguous completed prefix |
| `GET` | `/v1/speech/jobs/{id}/audio` | Download a completed WAV |

The API returns `202 Accepted` immediately. One in-process worker handles jobs and chunks in order,
which deliberately prevents request floods. Run a single Uvicorn worker for this MVP; multiple
processes need a distributed queue/lease before they are safe.

Jobs, chunk state, and PCM checkpoints survive service restarts. A job interrupted while running is
requeued automatically; a deliberately paused or cancelled job keeps that state. New processing
errors pause the job and expose a stable error code rather than discarding completed work. Partial
audio is assembled into a separate snapshot and never sets the job's completed output path.

## Configuration

See `.env.example`. Generated source text, PCM chunks, the SQLite database, and WAV files live
under `SPLICR_DATA_DIR` (`data/` by default) and are ignored by Git. Source documents, chunk text,
and custom director's notes are stored locally in plaintext across job storage and SQLite. This MVP
has no retention or purge endpoint; delete the complete data directory when its jobs are no longer
needed.

Every transcript chunk and any custom director's notes are sent to the selected external TTS
provider. Gemini requests set `store=false`, which prevents creation of a retained Interaction
resource; it does not make remote processing local or supersede the provider's applicable data-use
terms. Review those terms before submitting sensitive, confidential, or personal text.

Plan disk capacity for both checkpoints and the assembled output. At final assembly, SPLICR can
temporarily need roughly twice the raw PCM size, plus the source text and SQLite database. The
default 4 GB PCM guard can therefore require about 8 GB of available storage for a maximum-size job.

The service has no user authentication. Its CLI binds to `127.0.0.1` by default; do not expose it
to an untrusted network without putting authentication and request-size enforcement in front of
it.

The important tuning controls are:

- `SPLICR_CHUNK_MAX_BYTES` and `SPLICR_CHUNK_MAX_WORDS`
- `SPLICR_MAX_UPLOAD_BYTES`, `SPLICR_MAX_SOURCE_BYTES`, `SPLICR_MAX_SOURCE_WORDS`, and
  `SPLICR_MAX_OUTPUT_PCM_BYTES`
- `SPLICR_PACING_SECONDS`
- `SPLICR_DEEPGRAM_PACING_SECONDS` and `SPLICR_INWORLD_PACING_SECONDS`
- `SPLICR_PROVIDER_TIMEOUT_SECONDS`
- `SPLICR_MAX_ATTEMPTS`
- `SPLICR_BACKOFF_BASE_SECONDS`, `SPLICR_BACKOFF_MAX_SECONDS`, and
  `SPLICR_BACKOFF_JITTER_SECONDS`
- `SPLICR_CORS_ORIGINS` for explicitly trusted external clients; the bundled studio is same-origin

`SPLICR_PACING_SECONDS` is the fallback interval between provider requests. Deepgram and Inworld
default to no artificial interval because their published limits are concurrency-based and SPLICR
already calls them sequentially; their provider-specific variables can add a delay if your account
needs one. All request pacing is separate from the five-step speaking-pace control stored with each
synthesis job.

## Adding another provider

Implement `TtsProvider` and register it in `splicr.bootstrap.create_service`. The adapter must turn
its native response (MP3, Opus, WAV, or PCM) into the canonical `AudioChunk`: mono signed 16-bit
little-endian PCM at 24 kHz. The chunker, queue, retries, checkpointing, assembly, API, and CLI do
not need to change. Publish the provider's models, voices, control presets, and implementation modes
through `ProviderCapabilities`, then translate `DeliveryControls` inside the adapter. A provider
that cannot emit canonical PCM will need decoding/resampling inside its adapter.

## Verify

```powershell
uv run pytest
```

The tests use fake providers and never spend API quota.

## Provider references

- [Gemini TTS guide](https://ai.google.dev/gemini-api/docs/speech-generation)
- [Gemini Interactions API](https://ai.google.dev/api/interactions-api-v1)
- [Gemini Interactions storage behavior](https://ai.google.dev/gemini-api/docs/interactions-overview)
- [Gemini model catalog](https://ai.google.dev/gemini-api/docs/models)
- [Gemini rate limits](https://ai.google.dev/gemini-api/docs/rate-limits)
- [Deepgram text-to-speech](https://developers.deepgram.com/docs/text-to-speech)
- [Deepgram media output settings](https://developers.deepgram.com/docs/tts-media-output-settings)
- [Deepgram API limits](https://developers.deepgram.com/reference/api-rate-limits)
- [Inworld synthesize speech API](https://docs.inworld.ai/api-reference/ttsAPI/texttospeech/synthesize-speech)
- [Inworld long-text input](https://docs.inworld.ai/tts/capabilities/long-text-input)
- [Inworld steering](https://docs.inworld.ai/tts/capabilities/steering)
- [Inworld rate limits](https://docs.inworld.ai/resources/rate-limits)
