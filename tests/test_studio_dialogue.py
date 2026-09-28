from __future__ import annotations

import asyncio
from collections.abc import Sequence

import pytest

from splicr.studio.dialogue import (
    ChatMessage,
    DialogueGenerationCheckpoint,
    DialogueGenerationError,
    DialogueGenerationOptions,
    DialogueTurn,
    dedupe_turns,
    generate_script,
    merge_consecutive,
    parse_turns,
    refine_selection,
    split_sections,
)


class ScriptedCompleter:
    def __init__(self, responses: Sequence[str | Exception]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2_048,
    ) -> str:
        self.calls.append(
            {
                "messages": list(messages),
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_parse_merge_and_dedupe_dialogue_turns() -> None:
    parsed = parse_turns(
        "Preamble```text\n<Person1>Hello   there.</Person1>\n"
        "<person1>One more thought.</person1>\n<Person2>Indeed.</Person2>```"
    )
    merged = merge_consecutive(parsed)
    assert merged == (
        DialogueTurn("Person1", "Hello there. One more thought."),
        DialogueTurn("Person2", "Indeed."),
    )

    repeated = (
        "amber birch cedar dahlia ember fable garden harbor island jasmine "
        "kingdom lantern meadow nectar orchid pebble quartz river summit timber"
    )
    deduped, removed = dedupe_turns(
        (
            DialogueTurn("Person1", repeated),
            DialogueTurn("Person2", "A short acknowledgement."),
            DialogueTurn("Person1", repeated),
        )
    )
    assert removed == 1
    assert deduped[-1].speaker == "Person2"


def test_split_sections_prefers_headings_and_caps_pathological_text() -> None:
    sections = split_sections(
        "# One\n" + ("alpha " * 140) + "\n# Two\nshort body",
        max_chars=500,
        max_sections=3,
    )
    assert len(sections) == 3
    assert sections[0][0] == "One (part 1)"
    assert all(len(body) <= 500 for _, body in sections)


def test_generate_script_uses_outline_continuity_and_skips_later_failure() -> None:
    completer = ScriptedCompleter(
        [
            "<Person1>Welcome to the episode.</Person1><Person2>Let us start.</Person2>",
            "The hosts introduced the main topic.",
            RuntimeError("temporary model outage"),
            "<Person1>Now for the conclusion.</Person1><Person2>Thanks for listening.</Person2>",
        ]
    )
    progress: list[str] = []
    script = asyncio.run(
        generate_script(
            "# Opening\nFirst source.\n# Details\nSecond source.\n# Closing\nThird source.",
            completer,
            options=DialogueGenerationOptions(section_chars=500),
            model="local-chat",
            progress=progress.append,
        )
    )

    assert script.outline == ("Opening", "Details", "Closing")
    assert script.sections == 3
    assert [turn.speaker for turn in script.turns] == [
        "Person1",
        "Person2",
        "Person1",
        "Person2",
    ]
    assert any("failed and was skipped" in message for message in progress)
    assert len(completer.calls) == 4
    second_section_prompt = completer.calls[2]["messages"][1]["content"]
    assert "The hosts introduced the main topic" in second_section_prompt
    assert "previous turn was Person2; begin with Person1" in second_section_prompt
    final_prompt = completer.calls[3]["messages"][1]["content"]
    assert "the last section" in final_prompt


def test_generate_script_requires_first_section_and_refine_cleans_wrappers() -> None:
    broken = ScriptedCompleter([RuntimeError("offline")])
    with pytest.raises(DialogueGenerationError, match="first dialogue section failed"):
        asyncio.run(generate_script("A source document.", broken))

    refiner = ScriptedCompleter(['[[["a clearer phrase"]]]'])
    replacement = asyncio.run(
        refine_selection(
            before="This is ",
            selected="muddy wording",
            after=" for listeners.",
            instruction="make it concise",
            speaker="Person1",
            completer=refiner,
            neighbor_before=DialogueTurn("Person2", "Can you explain that?"),
        )
    )
    assert replacement == "a clearer phrase"
    prompt = refiner.calls[0]["messages"][1]["content"]
    assert "Person2: Can you explain that?" in prompt
    assert "[[[muddy wording]]]" in prompt


def test_generate_script_resumes_from_a_section_checkpoint() -> None:
    checkpoints: list[DialogueGenerationCheckpoint] = []
    first = ScriptedCompleter(
        [
            "1. Opening\n2. Closing",
            "<Person1>Opening point.</Person1><Person2>Opening reply.</Person2>",
            "The hosts covered the opening point.",
        ]
    )

    partial = asyncio.run(
        generate_script(
            "# Opening\nFirst source.\n# Closing\nSecond source.",
            first,
            options=DialogueGenerationOptions(section_chars=500),
            save_checkpoint=checkpoints.append,
            should_cancel=lambda: bool(
                checkpoints and checkpoints[-1].completed_sections == 1
            ),
        )
    )

    assert partial.cancelled is True
    assert checkpoints[-1].completed_sections == 1
    assert len(partial.turns) == 2

    resumed_checkpoints: list[DialogueGenerationCheckpoint] = []
    second = ScriptedCompleter(
        ["<Person1>Closing point.</Person1><Person2>Closing reply.</Person2>"]
    )
    resumed = asyncio.run(
        generate_script(
            "# Opening\nFirst source.\n# Closing\nSecond source.",
            second,
            options=DialogueGenerationOptions(section_chars=500),
            checkpoint=checkpoints[-1],
            save_checkpoint=resumed_checkpoints.append,
        )
    )

    assert resumed.cancelled is False
    assert [turn.text for turn in resumed.turns] == [
        "Opening point.",
        "Opening reply.",
        "Closing point.",
        "Closing reply.",
    ]
    assert len(second.calls) == 1
    assert resumed_checkpoints[-1].completed_sections == 2
