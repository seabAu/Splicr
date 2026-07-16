from __future__ import annotations

import re

import pytest

from splicr.delivery import (
    NONVERBAL_CUE_MARKER_PREFIX,
    NONVERBAL_CUE_MARKER_SUFFIX,
    annotate_nonverbal_cues,
)
from splicr.domain import NonverbalFrequency


def test_never_leaves_transcript_byte_for_byte_unchanged() -> None:
    text = "First sentence.\n\nSecond sentence — with café."

    assert annotate_nonverbal_cues(text, NonverbalFrequency.NEVER, ("sighs",)) == text


def test_cue_plan_is_deterministic_and_only_uses_sentence_boundaries() -> None:
    text = " ".join(f"Sentence {index} has five plain words." for index in range(166))
    cues = ("sighs", "giggles", "laughs", "gasp")

    first = annotate_nonverbal_cues(text, NonverbalFrequency.OCCASIONAL, cues)
    second = annotate_nonverbal_cues(text, NonverbalFrequency.OCCASIONAL, cues)

    assert first == second
    marker_pattern = (
        rf" {re.escape(NONVERBAL_CUE_MARKER_PREFIX)}"
        rf"(?:sighs|giggles|laughs|gasp){re.escape(NONVERBAL_CUE_MARKER_SUFFIX)}"
    )
    assert first.count(NONVERBAL_CUE_MARKER_PREFIX) == 3
    assert re.sub(marker_pattern, "", first) == text
    assert not re.search(rf"[^.!?…]{marker_pattern}", first)


def test_nonzero_frequency_without_safe_boundary_does_not_mutate_text() -> None:
    text = "A short fragment without terminal punctuation"

    assert annotate_nonverbal_cues(text, NonverbalFrequency.VERY_FREQUENT, ("sighs",)) == text


def test_literal_bracketed_text_is_not_repurposed_as_a_cue() -> None:
    text = "Read [Appendix A]. Then continue with the source wording."

    annotated = annotate_nonverbal_cues(text, NonverbalFrequency.VERY_FREQUENT, ("sighs",))

    assert "[Appendix A]" in annotated
    assert f"{NONVERBAL_CUE_MARKER_PREFIX}sighs{NONVERBAL_CUE_MARKER_SUFFIX}" in annotated


def test_reserved_cue_marker_in_source_is_rejected() -> None:
    text = f"Literal {NONVERBAL_CUE_MARKER_PREFIX}sighs{NONVERBAL_CUE_MARKER_SUFFIX}. Next."

    with pytest.raises(ValueError, match="reserved non-verbal cue marker"):
        annotate_nonverbal_cues(text, NonverbalFrequency.RARE, ("sighs",))
