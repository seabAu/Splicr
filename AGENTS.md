# Project Directive: Long-Document Speech Synthesis

## Objective

Build and maintain a local Python microservice that converts long UTF-8 text into one
continuous audio file through pluggable text-to-speech providers.

## Architecture

- Keep FastAPI transport code thin.
- Keep chunking, retry orchestration, persistence, storage, and audio assembly provider-neutral.
- Put each external API behind the `TtsProvider` protocol.
- Normalize provider output to mono, signed 16-bit PCM at 24,000 Hz before assembly.
- Persist job and chunk progress so interrupted jobs can resume without re-synthesizing completed
  chunks.

## Current Gemini constraints

- Default model: `gemini-3.1-flash-tts-preview`; keep it configurable.
- Target at most 3,800 UTF-8 bytes and 350 words of transcript per chunk.
- Split on paragraph and sentence boundaries first, then words only as a final fallback.
- Send requests sequentially, pace them, and retry transient failures with exponential backoff and
  jitter.
- Request inline raw PCM and validate its reported format.
- Assemble raw frames in source order and write exactly one WAV header: mono, 16-bit, 24,000 Hz.

## Quality bar

- Never commit API keys, generated audio, job databases, or virtual environments.
- Add tests for chunk boundaries, multibyte text, retries, resume behavior, ordering, and WAV
  metadata when changing the pipeline.
- A failed job must never expose a partial file as a completed result.
