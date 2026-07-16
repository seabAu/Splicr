"""Provider-neutral transcript cleanup applied before chunk planning."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PreprocessingResult:
    """The effective transcript and a summary of deterministic cleanup."""

    text: str
    removed_numeric_citations: int


_NUMERIC_BRACKET_RE = re.compile(r"\[[ \t]*(?P<number>[0-9]+)[ \t]*\]")
_NUMERIC_DEFINITION_RE = re.compile(r"(?m)^[ \t]{0,3}\[[ \t]*(?P<number>[0-9]+)[ \t]*\]:")
_REFERENCE_LABEL_RE = re.compile(r"\[(?P<label>[^\]\r\n]*)\]")
_HORIZONTAL_WHITESPACE = " \t"
_CLOSING_PUNCTUATION = frozenset(".,;:!?%)]}\u00bb\u201d\u2019")
_OPENING_PUNCTUATION = frozenset("([{\u00ab\u201c\u2018")


def preprocess_text(
    text: str,
    *,
    remove_numeric_citations: bool = False,
) -> PreprocessingResult:
    """Apply optional deterministic cleanup without interpreting provider markup.

    Numeric citations are ASCII integers enclosed by square brackets, with optional
    horizontal whitespace inside the brackets. Markdown links, images, reference
    definitions, escaped brackets, and nested brackets are deliberately retained.
    """

    if not remove_numeric_citations:
        return PreprocessingResult(text=text, removed_numeric_citations=0)

    defined_numeric_labels = {
        match.group("number") for match in _NUMERIC_DEFINITION_RE.finditer(text)
    }
    removable = [
        match.span()
        for match in _NUMERIC_BRACKET_RE.finditer(text)
        if not _is_protected_markdown(match, text, defined_numeric_labels)
    ]
    if not removable:
        return PreprocessingResult(text=text, removed_numeric_citations=0)

    groups = _group_adjacent_citations(removable, text)
    cleaned: list[str] = []
    cursor = 0
    for start, end, internal_spacing in groups:
        left = start
        while left > cursor and text[left - 1] in _HORIZONTAL_WHITESPACE:
            left -= 1
        right = end
        while right < len(text) and text[right] in _HORIZONTAL_WHITESPACE:
            right += 1

        cleaned.append(text[cursor:left])
        had_spacing = internal_spacing or left < start or right > end
        if had_spacing and _needs_separator(text, left, right):
            cleaned.append(" ")
        cursor = right

    cleaned.append(text[cursor:])
    return PreprocessingResult(
        text="".join(cleaned),
        removed_numeric_citations=len(removable),
    )


def _is_protected_markdown(
    match: re.Match[str],
    text: str,
    defined_numeric_labels: set[str],
) -> bool:
    start, end = match.span()
    number = match.group("number")

    if _is_escaped(text, start):
        return True
    if start > 0 and text[start - 1] in "![":
        return True
    if number in defined_numeric_labels:
        # Preserve both the definition and shortcut/reference uses of its label.
        return True
    if end < len(text) and text[end] == "(":
        return True
    if end >= len(text) or text[end] != "[":
        return False

    reference = _REFERENCE_LABEL_RE.match(text, end)
    if reference is None:
        return False
    label = reference.group("label").strip()
    if not label:
        return True
    if not label.isascii() or not label.isdecimal():
        return True
    return label in defined_numeric_labels


def _is_escaped(text: str, position: int) -> bool:
    backslashes = 0
    cursor = position - 1
    while cursor >= 0 and text[cursor] == "\\":
        backslashes += 1
        cursor -= 1
    return backslashes % 2 == 1


def _group_adjacent_citations(
    spans: list[tuple[int, int]],
    text: str,
) -> list[tuple[int, int, bool]]:
    groups: list[tuple[int, int, bool]] = []
    start, end = spans[0]
    internal_spacing = False
    for next_start, next_end in spans[1:]:
        gap = text[end:next_start]
        if all(character in _HORIZONTAL_WHITESPACE for character in gap):
            internal_spacing = internal_spacing or bool(gap)
            end = next_end
            continue
        groups.append((start, end, internal_spacing))
        start, end, internal_spacing = next_start, next_end, False
    groups.append((start, end, internal_spacing))
    return groups


def _needs_separator(text: str, left: int, right: int) -> bool:
    if left == 0 or right == len(text):
        return False
    before = text[left - 1]
    after = text[right]
    if before in "\r\n" or after in "\r\n":
        return False
    if before in _OPENING_PUNCTUATION or after in _CLOSING_PUNCTUATION:
        return False
    return True
