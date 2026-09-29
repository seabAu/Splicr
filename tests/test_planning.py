from __future__ import annotations

from splicr.chunking import ChunkPolicy
from splicr.planning import ChunkTargetMode, SplitStrategy, plan_chunks


def test_heading_strategy_keeps_sections_separate_and_tracks_offsets() -> None:
    text = "Intro.\n\n## First\nAlpha beta.\n\n## Second\nGamma delta."

    plan = plan_chunks(text, ChunkPolicy(max_bytes=500, max_words=100), SplitStrategy.HEADING_2)

    assert [chunk.text for chunk in plan.chunks] == [
        "Intro.",
        "## First\nAlpha beta.",
        "## Second\nGamma delta.",
    ]
    assert [plan.text[chunk.start_char : chunk.end_char] for chunk in plan.chunks] == [
        chunk.text for chunk in plan.chunks
    ]
    assert all(chunk.boundary == "h2" for chunk in plan.chunks)


def test_requested_boundary_still_falls_back_to_provider_safe_chunks() -> None:
    text = "# Long\nFirst sentence is here. Second sentence is here."

    plan = plan_chunks(text, ChunkPolicy(max_bytes=30, max_words=20), SplitStrategy.HEADING_1)

    assert len(plan.chunks) >= 2
    assert all(chunk.byte_count <= 30 for chunk in plan.chunks)
    assert all(chunk.boundary == "h1+semantic" for chunk in plan.chunks)


def test_newline_strategy_does_not_pack_neighboring_lines() -> None:
    plan = plan_chunks(
        "First short line.\nSecond short line.",
        ChunkPolicy(max_bytes=500, max_words=100),
        SplitStrategy.NEWLINE,
    )

    assert [chunk.text for chunk in plan.chunks] == ["First short line.", "Second short line."]


def test_long_single_newline_section_maps_normalized_chunks_to_source() -> None:
    text = ("A sentence with several ordinary words.\n" * 200).strip()

    plan = plan_chunks(
        text,
        ChunkPolicy(max_bytes=3_800, max_words=350),
        SplitStrategy.SEMANTIC,
    )

    assert len(plan.chunks) > 1
    cursor = 0
    for chunk in plan.chunks:
        assert not plan.text[cursor : chunk.start_char].strip()
        source_segment = plan.text[chunk.start_char : chunk.end_char]
        assert " ".join(source_segment.split()) == " ".join(chunk.text.split())
        cursor = chunk.end_char
    assert not plan.text[cursor:].strip()


def test_character_target_is_additional_to_provider_hard_limits() -> None:
    text = "Alpha beta gamma delta epsilon zeta eta theta."
    policy = ChunkPolicy(max_bytes=18, max_words=100)

    plan = plan_chunks(
        text,
        policy,
        target_mode=ChunkTargetMode.CHARACTERS,
        target_value=30,
    )

    assert len(plan.chunks) > 1
    assert all(chunk.character_count <= 30 for chunk in plan.chunks)
    assert all(chunk.byte_count <= 18 for chunk in plan.chunks)
    assert all(chunk.limit_headroom["bytes"] >= 0 for chunk in plan.chunks)


def test_token_target_uses_provider_estimator_and_reports_metrics() -> None:
    policy = ChunkPolicy(
        max_bytes=500,
        max_words=100,
        max_tokens=20,
        token_estimator=lambda value: len(value.split()),
    )

    plan = plan_chunks(
        "one two three four five six",
        policy,
        target_mode=ChunkTargetMode.TOKENS,
        target_value=2,
    )

    assert [chunk.token_count for chunk in plan.chunks] == [2, 2, 2]
    assert all(chunk.limit_headroom["tokens"] == 18 for chunk in plan.chunks)


def test_requested_parts_warns_when_preferred_boundaries_require_more_chunks() -> None:
    plan = plan_chunks(
        "First line.\nSecond line.",
        ChunkPolicy(max_bytes=500, max_words=100),
        SplitStrategy.NEWLINE,
        ChunkTargetMode.PARTS,
        1,
    )

    assert len(plan.chunks) == 2
    assert plan.warnings == (
        "Requested 1 parts, but provider limits and preferred boundaries produced 2 chunks.",
    )


def test_all_markdown_heading_levels_are_available() -> None:
    for level in range(1, 7):
        strategy = SplitStrategy(f"h{level}")
        plan = plan_chunks(
            f"Intro.\n\n{'#' * level} Heading\nBody.",
            ChunkPolicy(max_bytes=500, max_words=100),
            strategy,
        )
        assert len(plan.chunks) == 2
        assert all(chunk.boundary == strategy.value for chunk in plan.chunks)
