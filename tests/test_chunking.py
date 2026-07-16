from __future__ import annotations

from splicr.chunking import ChunkPolicy, SemanticChunker, utf8_size, word_count


def test_packs_paragraphs_without_exceeding_utf8_or_word_limits() -> None:
    text = "Alpha beta gamma.\n\nDelta écho foxtrot.\n\nGolf hotel india."
    policy = ChunkPolicy(max_bytes=42, max_words=6)

    chunks = SemanticChunker(policy).split(text)

    assert len(chunks) >= 2
    assert all(utf8_size(chunk) <= 42 for chunk in chunks)
    assert all(word_count(chunk) <= 6 for chunk in chunks)
    assert " ".join(" ".join(chunks).split()) == " ".join(text.split())


def test_oversized_paragraph_falls_back_to_sentence_boundaries() -> None:
    text = "First sentence is here. Second sentence is here. Third sentence is here."

    chunks = SemanticChunker(ChunkPolicy(max_bytes=30, max_words=20)).split(text)

    assert chunks == [
        "First sentence is here.",
        "Second sentence is here.",
        "Third sentence is here.",
    ]


def test_single_oversized_token_is_split_on_unicode_codepoint_boundaries() -> None:
    text = "🙂" * 11

    chunks = SemanticChunker(ChunkPolicy(max_bytes=12, max_words=10)).split(text)

    assert "".join(chunks) == text
    assert all(utf8_size(chunk) <= 12 for chunk in chunks)
    assert all("�" not in chunk for chunk in chunks)


def test_blank_input_is_rejected() -> None:
    try:
        SemanticChunker(ChunkPolicy()).split(" \n\t ")
    except ValueError as error:
        assert "non-whitespace" in str(error)
    else:
        raise AssertionError("blank input should be rejected")


def test_provider_token_estimator_is_enforced_during_chunking() -> None:
    policy = ChunkPolicy(
        max_bytes=1_000,
        max_words=1_000,
        max_tokens=12,
        token_estimator=lambda value: len(value.encode("utf-8")),
    )

    chunks = SemanticChunker(policy).split("First part. Second part. Third part.")

    assert len(chunks) > 1
    assert all(len(chunk.encode("utf-8")) <= 12 for chunk in chunks)


def test_provider_character_estimator_reserves_transformed_text_overhead() -> None:
    policy = ChunkPolicy(
        max_bytes=1_000,
        max_words=1_000,
        max_characters=20,
        character_estimator=lambda value: len(value) + 10,
    )

    chunks = SemanticChunker(policy).split("Alpha beta. Gamma delta. Epsilon zeta.")

    assert len(chunks) > 1
    assert all(len(chunk) + 10 <= 20 for chunk in chunks)


def test_character_limit_requires_a_provider_estimator() -> None:
    try:
        ChunkPolicy(max_characters=2_000)
    except ValueError as error:
        assert "character_estimator" in str(error)
    else:
        raise AssertionError("a character limit without an estimator should be rejected")
