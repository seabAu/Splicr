from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable


_WORD_RE = re.compile(r"\S+")
_PARAGRAPH_RE = re.compile(r"\n\s*\n+")
_SENTENCE_END_RE = re.compile(r"[.!?…]+(?:[\"'’”\)\]]+)?(?=\s+|$)")
_CLAUSE_END_RE = re.compile(r"[;:,—–]+(?=\s+|$)")


def utf8_size(text: str) -> int:
    return len(text.encode("utf-8"))


def word_count(text: str) -> int:
    return len(_WORD_RE.findall(text))


def normalize_text(text: str) -> str:
    """Normalize transport whitespace while preserving paragraph and Markdown boundaries."""

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[\t ]+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(lines).strip()


@dataclass(frozen=True, slots=True)
class ChunkPolicy:
    max_bytes: int = 3_800
    max_words: int = 350
    max_characters: int | None = None
    character_estimator: Callable[[str], int] | None = None
    max_tokens: int | None = None
    token_estimator: Callable[[str], int] | None = None
    target_characters: int | None = None
    target_tokens: int | None = None

    def __post_init__(self) -> None:
        if self.max_bytes < 4:
            raise ValueError("max_bytes must be at least 4")
        if self.max_words < 1:
            raise ValueError("max_words must be positive")
        if self.max_characters is not None and self.max_characters < 1:
            raise ValueError("max_characters must be positive")
        if self.max_characters is not None and self.character_estimator is None:
            raise ValueError("character_estimator is required when max_characters is set")
        if self.max_tokens is not None and self.max_tokens < 1:
            raise ValueError("max_tokens must be positive")
        if self.max_tokens is not None and self.token_estimator is None:
            raise ValueError("token_estimator is required when max_tokens is set")
        if self.target_characters is not None and self.target_characters < 1:
            raise ValueError("target_characters must be positive")
        if self.target_tokens is not None and self.target_tokens < 1:
            raise ValueError("target_tokens must be positive")
        if self.target_tokens is not None and self.token_estimator is None:
            raise ValueError("token_estimator is required when target_tokens is set")

    def accepts(self, text: str) -> bool:
        if utf8_size(text) > self.max_bytes or word_count(text) > self.max_words:
            return False
        if self.max_characters is not None:
            assert self.character_estimator is not None
            if self.character_estimator(text) > self.max_characters:
                return False
        if self.target_characters is not None and len(text) > self.target_characters:
            return False
        if self.max_tokens is not None:
            assert self.token_estimator is not None
            if self.token_estimator(text) > self.max_tokens:
                return False
        if self.target_tokens is not None:
            assert self.token_estimator is not None
            if self.token_estimator(text) > self.target_tokens:
                return False
        return True


@dataclass(frozen=True, slots=True)
class _Unit:
    text: str
    separator: str


class SemanticChunker:
    """Pack text by paragraphs, sentences, clauses, words, then UTF-8 code points."""

    def __init__(self, policy: ChunkPolicy) -> None:
        self.policy = policy

    def split(self, text: str) -> list[str]:
        normalized = normalize_text(text)
        if not normalized:
            raise ValueError("text must contain at least one non-whitespace character")
        if not self.policy.accepts(""):
            raise ValueError("provider instructions exceed the input-token limit")

        units: list[_Unit] = []
        for paragraph_index, paragraph in enumerate(_PARAGRAPH_RE.split(normalized)):
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            separator = "" if not units else "\n\n"
            units.extend(self._reduce(paragraph, separator, self._split_sentences))

        chunks = self._pack(units)
        if not chunks or any(not chunk for chunk in chunks):
            raise AssertionError("chunker produced an empty chunk")
        if any(not self.policy.accepts(chunk) for chunk in chunks):
            raise AssertionError("chunker produced a chunk beyond its policy")
        return chunks

    @staticmethod
    def _normalize(text: str) -> str:
        return normalize_text(text)

    def _reduce(self, text: str, separator: str, splitter) -> list[_Unit]:
        if self.policy.accepts(text):
            return [_Unit(text=text, separator=separator)]

        pieces = splitter(text)
        splitter_name = splitter.__name__
        if len(pieces) <= 1:
            if splitter_name == "_split_sentences":
                return self._reduce(text, separator, self._split_clauses)
            if splitter_name == "_split_clauses":
                return self._reduce(text, separator, self._split_words)
            if splitter_name == "_split_words":
                return self._split_codepoints(text, separator)
            return self._split_codepoints(text, separator)

        units: list[_Unit] = []
        for index, piece in enumerate(pieces):
            child_separator = separator if index == 0 else " "
            if self.policy.accepts(piece):
                units.append(_Unit(piece, child_separator))
            elif splitter_name == "_split_sentences":
                units.extend(self._reduce(piece, child_separator, self._split_clauses))
            elif splitter_name == "_split_clauses":
                units.extend(self._reduce(piece, child_separator, self._split_words))
            else:
                units.extend(self._split_codepoints(piece, child_separator))
        return units

    @staticmethod
    def _split_at_boundaries(text: str, pattern: re.Pattern[str]) -> list[str]:
        pieces: list[str] = []
        start = 0
        for match in pattern.finditer(text):
            end = match.end()
            piece = text[start:end].strip()
            if piece:
                pieces.append(piece)
            start = end
        tail = text[start:].strip()
        if tail:
            pieces.append(tail)
        return pieces

    def _split_sentences(self, text: str) -> list[str]:
        return self._split_at_boundaries(text, _SENTENCE_END_RE)

    def _split_clauses(self, text: str) -> list[str]:
        return self._split_at_boundaries(text, _CLAUSE_END_RE)

    @staticmethod
    def _split_words(text: str) -> list[str]:
        return _WORD_RE.findall(text)

    def _split_codepoints(self, text: str, separator: str) -> list[_Unit]:
        pieces: list[str] = []
        current = ""
        for char in text:
            candidate = current + char
            if current and not self.policy.accepts(candidate):
                pieces.append(current)
                current = char
            else:
                current = candidate
            if not self.policy.accepts(current):
                raise ValueError("a single input code point exceeds the provider limits")
        if current:
            pieces.append(current)
        return [_Unit(piece, separator if index == 0 else "") for index, piece in enumerate(pieces)]

    def _pack(self, units: list[_Unit]) -> list[str]:
        chunks: list[str] = []
        current = ""
        for unit in units:
            candidate = unit.text if not current else current + unit.separator + unit.text
            if current and not self.policy.accepts(candidate):
                chunks.append(current)
                current = unit.text
            else:
                current = candidate
        if current:
            chunks.append(current)
        return chunks
