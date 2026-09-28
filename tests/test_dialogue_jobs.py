from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path

from splicr.dialogue_jobs import (
    DialogueScriptJobRequest,
    DialogueScriptJobService,
    DialogueScriptJobStatus,
    SqliteDialogueScriptJobStore,
)
from splicr.studio.dialogue import (
    ChatMessage,
    DialogueGenerationCheckpoint,
    DialogueGenerationOptions,
    DialogueScript,
    DialogueTurn,
)


class FakeCompleter:
    def __init__(self, responses: Sequence[str]) -> None:
        self.responses = list(responses)
        self.calls = 0

    async def __aenter__(self) -> FakeCompleter:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2_048,
    ) -> str:
        del messages, model, temperature, max_tokens
        self.calls += 1
        return self.responses.pop(0)


def _request() -> DialogueScriptJobRequest:
    return DialogueScriptJobRequest(
        chat_resource_id="local",
        resource_revision=3,
        model="writer-model",
        text="# Opening\nFirst source.\n# Closing\nSecond source.",
        options=DialogueGenerationOptions(section_chars=500),
    )


def test_dialogue_job_store_persists_checkpoint_and_resumes(tmp_path: Path) -> None:
    store = SqliteDialogueScriptJobStore(tmp_path / "jobs.sqlite3")
    store.initialize()
    job = store.create(_request())
    assert job.status is DialogueScriptJobStatus.QUEUED
    assert job.total_sections == 2
    assert store.claim(job.id) is True

    checkpoint = DialogueGenerationCheckpoint(
        sections=2,
        outline=("Opening", "Closing"),
        completed_sections=1,
        turns=(DialogueTurn("Person1", "Opening point."),),
        running_summary="Covered the opening point.",
        last_speaker="Person1",
    )
    store.save_checkpoint(job.id, checkpoint)
    requested = store.cancel(job.id)
    assert requested.status is DialogueScriptJobStatus.CANCEL_REQUESTED

    partial = DialogueScript(
        turns=checkpoint.turns,
        sections=2,
        outline=checkpoint.outline,
        removed_duplicates=0,
        word_count=2,
        cancelled=True,
    )
    cancelled = store.complete(job.id, partial, cancelled=True)
    assert cancelled.status is DialogueScriptJobStatus.CANCELLED
    assert cancelled.completed_sections == 1
    assert cancelled.result == partial

    resumed = store.resume(job.id)
    assert resumed.status is DialogueScriptJobStatus.QUEUED
    assert resumed.checkpoint == checkpoint
    assert resumed.result is None


def test_dialogue_job_store_requeues_interrupted_work(tmp_path: Path) -> None:
    store = SqliteDialogueScriptJobStore(tmp_path / "jobs.sqlite3")
    store.initialize()
    job = store.create(_request())
    assert store.claim(job.id) is True

    assert store.requeue_interrupted() == [job.id]
    assert store.get(job.id).status is DialogueScriptJobStatus.QUEUED


def test_dialogue_job_service_generates_and_checkpoints(tmp_path: Path) -> None:
    async def exercise() -> tuple[FakeCompleter, object]:
        store = SqliteDialogueScriptJobStore(tmp_path / "jobs.sqlite3")
        completer = FakeCompleter(
            [
                "1. Opening\n2. Closing",
                "<Person1>Opening point.</Person1><Person2>Opening reply.</Person2>",
                "The hosts covered the opening point.",
                "<Person1>Closing point.</Person1><Person2>Closing reply.</Person2>",
            ]
        )
        service = DialogueScriptJobService(store, lambda _request: completer)
        await service.start()
        try:
            created = await service.create(_request())
            for _ in range(200):
                current = store.get(created.id)
                if current.status in {
                    DialogueScriptJobStatus.COMPLETED,
                    DialogueScriptJobStatus.FAILED,
                }:
                    return completer, current
                await asyncio.sleep(0.005)
            raise AssertionError("dialogue job did not finish")
        finally:
            await service.stop()

    completer, result = asyncio.run(exercise())
    assert result.status is DialogueScriptJobStatus.COMPLETED
    assert result.completed_sections == 2
    assert result.checkpoint is not None
    assert result.checkpoint.completed_sections == 2
    assert result.result is not None
    assert [turn.text for turn in result.result.turns] == [
        "Opening point.",
        "Opening reply.",
        "Closing point.",
        "Closing reply.",
    ]
    assert completer.calls == 4
