from __future__ import annotations

from splicr.chunking import ChunkPolicy
from splicr.planning import SplitStrategy, plan_chunks


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
