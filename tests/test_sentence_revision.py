from __future__ import annotations

import asyncio
import struct
import time
from pathlib import Path

import pytest

from splicr.config import Settings
from splicr.domain import AudioChunk, JobStatus
from splicr.providers import ProviderRegistry
from splicr.service import SynthesisService
from splicr.studio.sentence_revision import SENTENCE_REVISION_VARIABLE, sentence_spans
from splicr.studio.store import SqliteStudioStore
from splicr.studio.subtitles import SubtitleService
from splicr.studio.timeline import build_job_timeline

from .fakes import RecordingProvider


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        chunk_max_bytes=10_000,
        chunk_max_words=100,
        pacing_seconds=0,
        max_attempts=3,
        backoff_base_seconds=0,
        backoff_max_seconds=0,
        backoff_jitter_seconds=0,
    )


async def _wait_for_terminal(service: SynthesisService, job_id: str):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        job = service.get_job(job_id)
        if job.status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.PAUSED}:
            return job
        await asyncio.sleep(0.01)
    raise AssertionError("job did not reach a terminal state")


def test_sentence_spans_prefers_engine_and_accepts_explicit_transcription_fallback() -> None:
    text = "First sentence. Second sentence."
    engine = sentence_spans(
        text,
        {
            "timings": [
                {
                    "type": "SentenceBoundary",
                    "start_seconds": 0.0,
                    "duration_seconds": 1.0,
                    "text": "First sentence.",
                },
                {
                    "type": "SentenceBoundary",
                    "start_seconds": 1.0,
                    "duration_seconds": 1.0,
                    "text": "Second sentence.",
                },
            ],
            "transcription_timings": [
                {
                    "start_seconds": 0.0,
                    "duration_seconds": 2.0,
                    "text": text,
                }
            ],
        },
        2.0,
    )
    assert [span.text for span in engine] == ["First sentence.", "Second sentence."]
    assert {span.timing_source for span in engine} == {"engine"}
    assert {span.confidence for span in engine} == {"exact"}

    word_aligned = sentence_spans(
        text,
        {
            "timings": [
                {
                    "type": "WordBoundary",
                    "start_seconds": index * 0.5,
                    "duration_seconds": 0.45,
                    "text": word,
                }
                for index, word in enumerate(("First", "sentence", "Second", "sentence"))
            ]
        },
        2.0,
    )
    assert [span.text for span in word_aligned] == [
        "First sentence.",
        "Second sentence.",
    ]
    assert {span.confidence for span in word_aligned} == {"exact"}

    mixed_after_revision = sentence_spans(
        "First sentence. Changed sentence. Third sentence.",
        {
            "timings": [
                {
                    "type": "WordBoundary",
                    "start_seconds": 0.0,
                    "duration_seconds": 0.2,
                    "text": "First",
                },
                {
                    "type": "WordBoundary",
                    "start_seconds": 0.2,
                    "duration_seconds": 0.2,
                    "text": "sentence",
                },
                {
                    "type": "SentenceBoundary",
                    "start_seconds": 0.4,
                    "duration_seconds": 0.4,
                    "text": "Changed sentence.",
                },
                {
                    "type": "WordBoundary",
                    "start_seconds": 0.8,
                    "duration_seconds": 0.2,
                    "text": "Third",
                },
                {
                    "type": "WordBoundary",
                    "start_seconds": 1.0,
                    "duration_seconds": 0.2,
                    "text": "sentence",
                },
            ]
        },
        1.2,
    )
    assert [span.text for span in mixed_after_revision] == [
        "First sentence.",
        "Changed sentence.",
        "Third sentence.",
    ]

    fallback = sentence_spans(
        text,
        {
            "transcription_timings": [
                {
                    "start_seconds": 0.0,
                    "duration_seconds": 1.0,
                    "text": "First sentence.",
                },
                {
                    "start_seconds": 1.0,
                    "duration_seconds": 1.0,
                    "text": "Second sentence.",
                },
            ]
        },
        2.0,
    )
    assert len(fallback) == 2
    assert {span.timing_source for span in fallback} == {"transcription"}
    assert {span.confidence for span in fallback} == {"aligned"}


def test_sentence_spans_rejects_unaligned_or_overlapping_metadata() -> None:
    assert not sentence_spans(
        "First sentence. Second sentence.",
        {
            "timings": [
                {
                    "start_seconds": 0.0,
                    "duration_seconds": 1.5,
                    "text": "First sentence.",
                },
                {
                    "start_seconds": 1.0,
                    "duration_seconds": 1.0,
                    "text": "Second sentence.",
                },
            ]
        },
        2.0,
    )
    assert not sentence_spans(
        "First sentence.",
        {
            "timings": [
                {
                    "start_seconds": 0.0,
                    "duration_seconds": 1.0,
                    "text": "Different text.",
                }
            ]
        },
        1.0,
    )


def test_sentence_revision_creates_derived_take_and_preserves_outside_pcm(tmp_path) -> None:
    async def scenario() -> None:
        provider = RecordingProvider()
        service = SynthesisService(
            settings=_settings(tmp_path), providers=ProviderRegistry([provider])
        )
        await service.start()
        try:
            source = await service.submit(
                text="First sentence. Second sentence. Third sentence.",
                provider_name="fake",
            )
            finished = await _wait_for_terminal(service, source.id)
            assert finished.status is JobStatus.COMPLETED

            source_samples = [1000] * 1000 + [2000] * 1000 + [3000] * 1000
            source_pcm = struct.pack(f"<{len(source_samples)}h", *source_samples)
            source_path = service.storage.chunk_path(source.id, 0)
            source_path.write_bytes(source_pcm)
            metadata = {
                "timings": [
                    {
                        "type": "SentenceBoundary",
                        "start_seconds": 0.0,
                        "duration_seconds": 1000 / 24_000,
                        "text": "First sentence.",
                    },
                    {
                        "type": "SentenceBoundary",
                        "start_seconds": 1000 / 24_000,
                        "duration_seconds": 1000 / 24_000,
                        "text": "Second sentence.",
                    },
                    {
                        "type": "SentenceBoundary",
                        "start_seconds": 2000 / 24_000,
                        "duration_seconds": 1000 / 24_000,
                        "text": "Third sentence.",
                    },
                ]
            }
            service.store.mark_chunk_completed(
                source.id,
                0,
                str(source_path.resolve()),
                metadata,
            )

            source_timeline = build_job_timeline(service.store, service.storage, source.id)
            segment = source_timeline.segments[0]
            assert segment.sentence_revision_available
            assert [sentence.text for sentence in segment.sentences] == [
                "First sentence.",
                "Second sentence.",
                "Third sentence.",
            ]

            revised = await service.revise_sentence(
                source_job_id=source.id,
                chunk_index=0,
                sentence_index=1,
                text="Changed sentence.",
            )
            revised_finished = await _wait_for_terminal(service, revised.id)
            assert revised_finished.status is JobStatus.COMPLETED
            assert provider.calls == [
                "First sentence. Second sentence. Third sentence.",
                "Changed sentence.",
            ]

            revised_chunk = service.store.chunks_for_job(revised.id)[0]
            assert revised_chunk.text == "First sentence. Changed sentence. Third sentence."
            revised_pcm = service.storage.chunk_path(revised.id, 0).read_bytes()
            assert revised_pcm[: 1000 * 2] == source_pcm[: 1000 * 2]
            assert revised_pcm[-1000 * 2 :] == source_pcm[-1000 * 2 :]
            assert len(revised_pcm) == (1000 + 4 + 1000) * 2
            provenance = revised_chunk.metadata["sentence_revision"]
            assert provenance["source_job_id"] == source.id
            assert provenance["sentence_index"] == 1

            revised_timeline = build_job_timeline(
                service.store,
                service.storage,
                revised.id,
            )
            revised_sentences = revised_timeline.segments[0].sentences
            assert [sentence.text for sentence in revised_sentences] == [
                "First sentence.",
                "Changed sentence.",
                "Third sentence.",
            ]
            assert revised_sentences[2].start == pytest.approx(1004 / 24_000)
            studio_store = SqliteStudioStore(tmp_path / "studio-test.db")
            studio_store.initialize()
            subtitle_timeline = SubtitleService(
                job_store=service.store,
                job_storage=service.storage,
                studio_store=studio_store,
                output_root=tmp_path / "subtitles",
            ).timeline(revised.id)
            assert [cue.source_text for cue in subtitle_timeline.cues] == [
                "First sentence.",
                "Changed sentence.",
                "Third sentence.",
            ]
            assert subtitle_timeline.cues[2].start == pytest.approx(1004 / 24_000)
            assert service.storage.chunk_path(source.id, 0).read_bytes() == source_pcm
        finally:
            await service.stop()

    asyncio.run(scenario())


def test_sentence_revision_falls_back_when_reliable_timing_is_missing(tmp_path) -> None:
    async def scenario() -> None:
        provider = RecordingProvider()
        service = SynthesisService(
            settings=_settings(tmp_path), providers=ProviderRegistry([provider])
        )
        await service.start()
        try:
            source = await service.submit(
                text="First sentence. Second sentence.",
                provider_name="fake",
            )
            finished = await _wait_for_terminal(service, source.id)
            assert finished.status is JobStatus.COMPLETED
            timeline = build_job_timeline(service.store, service.storage, source.id)
            assert not timeline.segments[0].sentence_revision_available
            assert "chunk" in (timeline.segments[0].sentence_revision_fallback or "")
            with pytest.raises(ValueError, match="chunk-level regeneration"):
                await service.revise_sentence(
                    source_job_id=source.id,
                    chunk_index=0,
                    sentence_index=0,
                    text="Changed sentence.",
                )
        finally:
            await service.stop()

    asyncio.run(scenario())


def test_sentence_revision_restart_adopts_spliced_checkpoint_without_provider_replay(
    tmp_path,
) -> None:
    async def scenario() -> None:
        provider = RecordingProvider()
        service = SynthesisService(
            settings=_settings(tmp_path), providers=ProviderRegistry([provider])
        )
        await service.start()
        source = await service.submit(
            text="First sentence. Second sentence.",
            provider_name="fake",
        )
        finished = await _wait_for_terminal(service, source.id)
        assert finished.status is JobStatus.COMPLETED
        source_samples = [1000] * 1000 + [2000] * 1000
        source_pcm = struct.pack(f"<{len(source_samples)}h", *source_samples)
        source_path = service.storage.chunk_path(source.id, 0)
        source_path.write_bytes(source_pcm)
        service.store.mark_chunk_completed(
            source.id,
            0,
            str(source_path.resolve()),
            {
                "timings": [
                    {
                        "type": "SentenceBoundary",
                        "start_seconds": 0,
                        "duration_seconds": 1000 / 24_000,
                        "text": "First sentence.",
                    },
                    {
                        "type": "SentenceBoundary",
                        "start_seconds": 1000 / 24_000,
                        "duration_seconds": 1000 / 24_000,
                        "text": "Second sentence.",
                    },
                ]
            },
        )
        await service.stop()

        revised = await service.revise_sentence(
            source_job_id=source.id,
            chunk_index=0,
            sentence_index=0,
            text="Changed sentence.",
        )
        payload = revised.variables[SENTENCE_REVISION_VARIABLE]
        transformed = service._splice_sentence_revision(
            payload,
            AudioChunk(pcm=struct.pack("<8h", *([4000] * 8))),
        )
        service.storage.write_chunk(revised.id, 0, transformed.pcm)
        calls_before_restart = list(provider.calls)

        await service.start()
        try:
            recovered = await _wait_for_terminal(service, revised.id)
            assert recovered.status is JobStatus.COMPLETED
            assert provider.calls == calls_before_restart
            revised_chunk = service.store.chunks_for_job(revised.id)[0]
            assert revised_chunk.metadata["sentence_revision"]["source_job_id"] == source.id
            assert revised_chunk.metadata["sentence_revision"]["replacement_duration"] == (
                pytest.approx(8 / 24_000)
            )
            assert revised_chunk.metadata["sentence_revision"][
                "recovered_from_checkpoint"
            ] is True
            assert revised_chunk.metadata["sentence_revision"]["gain_db"] is None
        finally:
            await service.stop()

    asyncio.run(scenario())
