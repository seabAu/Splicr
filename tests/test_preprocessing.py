from splicr.preprocessing import preprocess_text


def test_cleanup_is_an_exact_noop_when_disabled() -> None:
    text = "Fact [123].\r\n\tKeep this spacing."

    result = preprocess_text(text)

    assert result.text == text
    assert result.removed_numeric_citations == 0


def test_removes_numeric_citations_and_repairs_local_spacing() -> None:
    result = preprocess_text(
        "Fact [123]. Next[4] word. A [ 5 ] B. End [6]",
        remove_numeric_citations=True,
    )

    assert result.text == "Fact. Next word. A B. End"
    assert result.removed_numeric_citations == 4


def test_removes_adjacent_and_spaced_citation_runs() -> None:
    result = preprocess_text(
        "One [1][2]; two [3] [4] words; attached[5][6]text.",
        remove_numeric_citations=True,
    )

    assert result.text == "One; two words; attachedtext."
    assert result.removed_numeric_citations == 6


def test_preserves_markdown_links_images_and_reference_definitions() -> None:
    text = """\
[123](https://example.test)
![456](cover.png)
[789][source]
[42][]
[7][8]
[55]

[source]: https://example.test/source
[8]: https://example.test/eight
[55]: https://example.test/fifty-five
"""

    result = preprocess_text(text, remove_numeric_citations=True)

    assert result.text == text
    assert result.removed_numeric_citations == 0


def test_removes_escaped_numeric_citations_but_preserves_other_brackets() -> None:
    text = (
        r"Remove \[123\] and \[ 456 \], but keep [aside], [[123]], "
        r"[[SPLICR_AUDIO_CUE:gasp]], and [١٢٣]. "
        "Remove [9]."
    )

    result = preprocess_text(text, remove_numeric_citations=True)

    assert result.text == (
        r"Remove and, but keep [aside], [[123]], [[SPLICR_AUDIO_CUE:gasp]], "
        "and [١٢٣]. Remove."
    )
    assert result.removed_numeric_citations == 3


def test_cleanup_is_idempotent_and_can_remove_all_content() -> None:
    first = preprocess_text("  [1] [2]  ", remove_numeric_citations=True)
    second = preprocess_text(first.text, remove_numeric_citations=True)

    assert first.text == ""
    assert first.removed_numeric_citations == 2
    assert second.text == ""
    assert second.removed_numeric_citations == 0


def test_preserves_line_structure_while_removing_citation_only_line() -> None:
    result = preprocess_text(
        "# Heading [1]\n\n  [2]  \n\n- Item [3].",
        remove_numeric_citations=True,
    )

    assert result.text == "# Heading\n\n\n\n- Item."
    assert result.removed_numeric_citations == 3
