from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from splicr.config import Settings
from splicr.storage import LocalJobStorage
from splicr.store import SqliteJobStore
from splicr.studio.conversion import ConversionInput, ConversionJobStore
from splicr.studio.store import SqliteStudioStore
from splicr.studio.transcription import (
    TranscriptionControlDefinition,
    TranscriptionJobService,
    TranscriptionJobStatus,
    TranscriptionJobStore,
    TranscriptionOptions,
    TranscriptionProviderDescriptor,
    TranscriptionProviderError,
    TranscriptionResult,
    TranscriptionSegment,
    TranscriptionWord,
    guess_chapters,
    regroup_paragraphs,
)
from splicr.transcription_worker import _transcribe as worker_transcribe


class FakeTranscriptionProvider:
    def __init__(self, *, delay: float = 0, failure: tuple[str, str] | None = None) -> None:
        self.delay = delay
        self.failure = failure
        self.calls: list[tuple[Path, TranscriptionOptions]] = []

    @property
    def descriptor(self) -> TranscriptionProviderDescriptor:
        return TranscriptionProviderDescriptor(
            id="fake-asr",
            label="Faithful fake ASR",
            description="Test provider",
            controls=(
                TranscriptionControlDefinition("model", "Model", "text", "base", "Test model"),
            ),
        )

    @property
    def available(self) -> bool:
        return True

    async def transcribe(self, audio_path, options, *, on_progress, is_cancelled):
        self.calls.append((audio_path, options))
        if self.failure:
            raise TranscriptionProviderError(*self.failure)
        for index in range(3):
            if self.delay:
                await asyncio.sleep(self.delay)
            if is_cancelled():
                from splicr.studio.transcription import TranscriptionCancelled

                raise TranscriptionCancelled
            on_progress((index + 1) / 3, "transcribing", index + 1, 8, index + 1)
        return _result()


def _result() -> TranscriptionResult:
    return TranscriptionResult(
        segments=(
            TranscriptionSegment(
                index=0,
                start=0,
                end=1,
                text="Opening words.",
                words=(TranscriptionWord(0, 0.5, "Opening"),),
            ),
            TranscriptionSegment(index=1, start=1.2, end=2, text="Same paragraph."),
            TranscriptionSegment(index=2, start=5, end=8, text="A new section begins."),
        ),
        language="en",
        language_probability=0.98,
        duration_seconds=8,
    )


def _service(
    tmp_path: Path, provider: FakeTranscriptionProvider
) -> tuple[TranscriptionJobService, ConversionInput]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    settings = Settings(data_dir=tmp_path)
    source_store = SqliteJobStore(settings.database_path)
    source_store.initialize()
    source_storage = LocalJobStorage(settings.jobs_dir)
    studio = SqliteStudioStore(settings.database_path)
    studio.initialize()
    conversion_store = ConversionJobStore(settings.database_path)
    conversion_store.initialize()
    audio_path = tmp_path / "managed.wav"
    audio_path.write_bytes(b"RIFF-fake-audio")
    try:
        upload = conversion_store.get_input("managed-audio")
    except LookupError:
        upload = conversion_store.save_input(
            ConversionInput(
                id="managed-audio",
                original_name="Interview Ω.wav",
                path=str(audio_path.resolve()),
                media_type="audio/wav",
                size_bytes=audio_path.stat().st_size,
                created_at="2026-09-29T00:00:00+00:00",
            )
        )
    return (
        TranscriptionJobService(
            store=TranscriptionJobStore(settings.database_path),
            conversion_store=conversion_store,
            source_store=source_store,
            source_storage=source_storage,
            studio_store=studio,
            output_root=tmp_path / "transcriptions",
            providers=[provider],
        ),
        upload,
    )


async def _terminal(service: TranscriptionJobService, job_id: str):
    for _ in range(500):
        job = service.store.get(job_id)
        if job.status in {
            TranscriptionJobStatus.COMPLETED,
            TranscriptionJobStatus.FAILED,
            TranscriptionJobStatus.CANCELLED,
        }:
            return job
        await asyncio.sleep(0.01)
    raise AssertionError("transcription job did not finish")


def test_transcription_materializes_durable_outputs_and_readable_structure(tmp_path) -> None:
    async def scenario() -> None:
        provider = FakeTranscriptionProvider()
        service, upload = _service(tmp_path, provider)
        await service.start()
        try:
            created = await service.submit(
                provider_id="fake-asr",
                input_id=upload.id,
                options=TranscriptionOptions(word_timestamps=True),
            )
            completed = await _terminal(service, created.id)
            assert completed.status is TranscriptionJobStatus.COMPLETED
            assert completed.progress == 1
            assert completed.segment_count == 3
            assert completed.detected_language == "en"
            assert set(completed.output_paths) == {
                "segments",
                "transcript",
                "srt",
                "vtt",
                "chapters",
            }
            transcript = service.output_for(created.id, "transcript").read_text(encoding="utf-8")
            assert "Opening words. Same paragraph." in transcript
            assert "A new section begins." in transcript
            chapters = service.output_for(created.id, "chapters").read_text(encoding="utf-8")
            assert "Guessed chapters" in chapters
            assert "0:05 A new section begins" in chapters
            segments = json.loads(
                service.output_for(created.id, "segments").read_text(encoding="utf-8")
            )
            assert segments["segments"][0]["words"][0]["text"] == "Opening"
            assert provider.calls[0][0] == Path(upload.path)
        finally:
            await service.stop()

    asyncio.run(scenario())


def test_interrupted_job_requeues_and_completes_after_restart(tmp_path) -> None:
    async def scenario() -> None:
        first_provider = FakeTranscriptionProvider(delay=0.2)
        first, upload = _service(tmp_path, first_provider)
        await first.start()
        submitted = await first.submit(
            provider_id="fake-asr",
            input_id=upload.id,
            options=TranscriptionOptions(),
        )
        for _ in range(100):
            if first.store.get(submitted.id).status is TranscriptionJobStatus.RUNNING:
                break
            await asyncio.sleep(0.01)
        await first.stop()
        assert first.store.get(submitted.id).status is TranscriptionJobStatus.RUNNING

        resumed_provider = FakeTranscriptionProvider()
        resumed, _ = _service(tmp_path, resumed_provider)
        await resumed.start()
        try:
            completed = await _terminal(resumed, submitted.id)
            assert completed.status is TranscriptionJobStatus.COMPLETED
            assert len(resumed_provider.calls) == 1
        finally:
            await resumed.stop()

    asyncio.run(scenario())


def test_cancel_and_provider_errors_never_publish_partial_outputs(tmp_path) -> None:
    async def scenario() -> None:
        slow = FakeTranscriptionProvider(delay=0.08)
        service, upload = _service(tmp_path, slow)
        await service.start()
        try:
            created = await service.submit(
                provider_id="fake-asr",
                input_id=upload.id,
                options=TranscriptionOptions(),
            )
            for _ in range(100):
                if service.store.get(created.id).status is TranscriptionJobStatus.RUNNING:
                    break
                await asyncio.sleep(0.01)
            await service.cancel(created.id)
            cancelled = await _terminal(service, created.id)
            assert cancelled.status is TranscriptionJobStatus.CANCELLED
            assert cancelled.output_paths == {}
        finally:
            await service.stop()

        failing = FakeTranscriptionProvider(
            failure=("model_download_failed", "model host was unavailable")
        )
        failed_service, upload = _service(tmp_path / "failure", failing)
        await failed_service.start()
        try:
            created = await failed_service.submit(
                provider_id="fake-asr",
                input_id=upload.id,
                options=TranscriptionOptions(),
            )
            failed = await _terminal(failed_service, created.id)
            assert failed.status is TranscriptionJobStatus.FAILED
            assert failed.error_code == "model_download_failed"
            assert failed.output_paths == {}
        finally:
            await failed_service.stop()

    asyncio.run(scenario())


def test_paragraph_and_guessed_chapter_helpers_are_explicit() -> None:
    result = _result()
    assert regroup_paragraphs(result.segments, gap_seconds=2) == (
        "Opening words. Same paragraph.",
        "A new section begins.",
    )
    chapters = guess_chapters(result.segments, gap_seconds=2)
    assert chapters[0] == {"title": "Opening words", "seconds": 0.0, "guessed": True}
    assert chapters[1]["seconds"] == 5
    assert all(mark["guessed"] is True for mark in chapters)


def test_worker_matches_faster_whisper_surface_without_loading_real_model(
    tmp_path, monkeypatch, capsys
) -> None:
    calls: dict[str, object] = {}

    class FakeWhisperModel:
        def __init__(self, model, *, device, compute_type, download_root):
            calls["init"] = (model, device, compute_type, download_root)

        def transcribe(self, audio, *, language, word_timestamps, vad_filter):
            calls["transcribe"] = (audio, language, word_timestamps, vad_filter)
            word = SimpleNamespace(start=0.0, end=0.5, word=" hello")
            segment = SimpleNamespace(start=0.0, end=1.0, text=" Hello.", words=[word])
            info = SimpleNamespace(language="en", language_probability=0.99, duration=1.0)
            return iter([segment]), info

    monkeypatch.setitem(
        sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=FakeWhisperModel)
    )
    audio = tmp_path / "source.wav"
    audio.write_bytes(b"audio")
    worker_transcribe(
        {
            "audio_path": str(audio),
            "model": "small",
            "device": "cpu",
            "compute_type": "int8",
            "download_root": str(tmp_path / "models"),
            "language": "en",
            "word_timestamps": True,
            "vad_filter": True,
        }
    )
    messages = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert calls["init"] == ("small", "cpu", "int8", str(tmp_path / "models"))
    assert calls["transcribe"] == (str(audio.resolve()), "en", True, True)
    assert [message["type"] for message in messages] == [
        "phase",
        "metadata",
        "segment",
        "complete",
    ]
    assert messages[2]["segment"]["words"][0]["text"] == "hello"
