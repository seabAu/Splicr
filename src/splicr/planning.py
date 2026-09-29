from __future__ import annotations

import re
from dataclasses import dataclass, replace
from enum import StrEnum
from math import ceil

from .chunking import ChunkPolicy, SemanticChunker, normalize_text, utf8_size, word_count


class SplitStrategy(StrEnum):
    SEMANTIC = "semantic"
    HEADING_1 = "h1"
    HEADING_2 = "h2"
    HEADING_3 = "h3"
    HEADING_4 = "h4"
    HEADING_5 = "h5"
    HEADING_6 = "h6"
    NEWLINE = "newline"
    DOUBLE_NEWLINE = "double_newline"


class ChunkTargetMode(StrEnum):
    AUTOMATIC = "automatic"
    PARTS = "parts"
    CHARACTERS = "characters"
    TOKENS = "tokens"


@dataclass(frozen=True, slots=True)
class PlannedChunk:
    index: int
    text: str
    start_char: int
    end_char: int
    byte_count: int
    word_count: int
    character_count: int
    token_count: int | None
    limit_headroom: dict[str, int]
    boundary: str


@dataclass(frozen=True, slots=True)
class ChunkPlan:
    text: str
    chunks: tuple[PlannedChunk, ...]
    strategy: SplitStrategy
    target_mode: ChunkTargetMode = ChunkTargetMode.AUTOMATIC
    target_value: int | None = None
    warnings: tuple[str, ...] = ()

    @property
    def total_chars(self) -> int:
        return len(self.text)

    @property
    def total_bytes(self) -> int:
        return utf8_size(self.text)

    @property
    def total_words(self) -> int:
        return word_count(self.text)


@dataclass(frozen=True, slots=True)
class _Section:
    text: str
    start_char: int
    boundary: str


def plan_chunks(
    text: str,
    policy: ChunkPolicy,
    strategy: SplitStrategy = SplitStrategy.SEMANTIC,
    target_mode: ChunkTargetMode = ChunkTargetMode.AUTOMATIC,
    target_value: int | None = None,
) -> ChunkPlan:
    """Plan bounded chunks, honoring requested boundaries before safe semantic fallback."""

    normalized = normalize_text(text)
    if not normalized:
        raise ValueError("text must contain at least one non-whitespace character")

    target_mode, target_value = _validate_target(target_mode, target_value)
    effective_policy = _target_policy(normalized, policy, target_mode, target_value)

    chunker = SemanticChunker(effective_policy)
    sections = _sections(normalized, strategy)
    planned: list[PlannedChunk] = []
    for section in sections:
        pieces = chunker.split(section.text)
        cursor = 0
        for piece in pieces:
            relative_start, relative_end = _equivalent_span(section.text, piece, cursor)
            start = section.start_char + relative_start
            end = section.start_char + relative_end
            planned.append(
                PlannedChunk(
                    index=len(planned),
                    text=piece,
                    start_char=start,
                    end_char=end,
                    byte_count=utf8_size(piece),
                    word_count=word_count(piece),
                    character_count=(
                        policy.character_estimator(piece)
                        if policy.character_estimator is not None
                        else len(piece)
                    ),
                    token_count=(
                        policy.token_estimator(piece)
                        if policy.token_estimator is not None
                        else None
                    ),
                    limit_headroom=_limit_headroom(piece, policy),
                    boundary=(
                        section.boundary if len(pieces) == 1 else f"{section.boundary}+semantic"
                    ),
                )
            )
            cursor = relative_end

    if not planned:
        raise AssertionError("chunk planner produced no chunks")
    warnings: list[str] = []
    if target_mode is ChunkTargetMode.PARTS and len(planned) != target_value:
        warnings.append(
            f"Requested {target_value} parts, but provider limits and preferred boundaries "
            f"produced {len(planned)} chunks."
        )
    return ChunkPlan(
        text=normalized,
        chunks=tuple(planned),
        strategy=strategy,
        target_mode=target_mode,
        target_value=target_value,
        warnings=tuple(warnings),
    )


def _validate_target(
    mode: ChunkTargetMode,
    value: int | None,
) -> tuple[ChunkTargetMode, int | None]:
    if mode is ChunkTargetMode.AUTOMATIC:
        if value is not None:
            raise ValueError("automatic chunk targeting does not accept a target value")
        return mode, None
    if value is None or value < 1:
        raise ValueError(f"{mode.value} chunk targeting requires a positive target value")
    return mode, value


def _target_policy(
    text: str,
    policy: ChunkPolicy,
    mode: ChunkTargetMode,
    value: int | None,
) -> ChunkPolicy:
    if mode is ChunkTargetMode.AUTOMATIC:
        return policy
    assert value is not None
    if mode is ChunkTargetMode.PARTS:
        return replace(policy, target_characters=max(1, ceil(len(text) / value)))
    if mode is ChunkTargetMode.CHARACTERS:
        return replace(policy, target_characters=value)
    if mode is ChunkTargetMode.TOKENS:
        if policy.token_estimator is None:
            raise ValueError("the selected provider does not expose a token estimator")
        return replace(policy, target_tokens=value)
    raise AssertionError(f"unsupported chunk target mode: {mode}")


def _limit_headroom(text: str, policy: ChunkPolicy) -> dict[str, int]:
    headroom = {
        "bytes": policy.max_bytes - utf8_size(text),
        "words": policy.max_words - word_count(text),
    }
    if policy.max_characters is not None:
        assert policy.character_estimator is not None
        headroom["characters"] = policy.max_characters - policy.character_estimator(text)
    if policy.max_tokens is not None:
        assert policy.token_estimator is not None
        headroom["tokens"] = policy.max_tokens - policy.token_estimator(text)
    return headroom


def _equivalent_span(source: str, piece: str, cursor: int) -> tuple[int, int]:
    """Map a chunk back to source while treating whitespace runs as equivalent.

    The semantic chunker deliberately joins sentence and word units with spaces. A
    normalized Markdown source can retain single newlines between those same units,
    so exact substring lookup is too strict even though the spoken text is identical.
    """

    source_cursor = cursor
    while source_cursor < len(source) and source[source_cursor].isspace():
        source_cursor += 1
    start = source_cursor
    piece_cursor = 0

    while piece_cursor < len(piece):
        if source_cursor >= len(source):
            raise AssertionError("planned chunk extends beyond the normalized source")
        if piece[piece_cursor].isspace():
            if not source[source_cursor].isspace():
                raise AssertionError("planned chunk whitespace did not match normalized source")
            while piece_cursor < len(piece) and piece[piece_cursor].isspace():
                piece_cursor += 1
            while source_cursor < len(source) and source[source_cursor].isspace():
                source_cursor += 1
            continue
        if source[source_cursor] != piece[piece_cursor]:
            raise AssertionError("planned chunk could not be mapped to normalized source")
        source_cursor += 1
        piece_cursor += 1

    return start, source_cursor


def _sections(text: str, strategy: SplitStrategy) -> list[_Section]:
    if strategy is SplitStrategy.SEMANTIC:
        return [_Section(text=text, start_char=0, boundary=strategy.value)]
    if strategy is SplitStrategy.NEWLINE:
        return _split_sections(text, re.compile(r"\n+"), strategy.value)
    if strategy is SplitStrategy.DOUBLE_NEWLINE:
        return _split_sections(text, re.compile(r"\n{2,}"), strategy.value)

    level = int(strategy.value[1:])
    heading = re.compile(rf"(?m)^#{{{level}}}(?!#)[ \t]+")
    starts = [match.start() for match in heading.finditer(text)]
    if not starts:
        return [_Section(text=text, start_char=0, boundary=f"{strategy.value}:fallback")]
    if starts[0] != 0:
        starts.insert(0, 0)
    return _sections_from_starts(text, starts, strategy.value)


def _split_sections(text: str, delimiter: re.Pattern[str], boundary: str) -> list[_Section]:
    starts = [0]
    starts.extend(match.end() for match in delimiter.finditer(text))
    return _sections_from_starts(text, starts, boundary)


def _sections_from_starts(text: str, starts: list[int], boundary: str) -> list[_Section]:
    unique_starts = sorted(set(starts))
    sections: list[_Section] = []
    for index, raw_start in enumerate(unique_starts):
        raw_end = unique_starts[index + 1] if index + 1 < len(unique_starts) else len(text)
        raw = text[raw_start:raw_end]
        leading = len(raw) - len(raw.lstrip())
        stripped = raw.strip()
        if stripped:
            sections.append(
                _Section(text=stripped, start_char=raw_start + leading, boundary=boundary)
            )
    return sections
