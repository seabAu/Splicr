from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence

from .domain import (
    NONVERBAL_CUE_MARKER_PREFIX,
    NONVERBAL_CUE_MARKER_SUFFIX,
    NonverbalFrequency,
)


_SENTENCE_END_RE = re.compile(r"[.!?…]+(?:[\"'’”\)\]]+)?(?=\s+|$)")
_WORD_RE = re.compile(r"\S+")
_EVENTS_PER_1_000_WORDS = {
    NonverbalFrequency.NEVER: 0,
    NonverbalFrequency.RARE: 1,
    NonverbalFrequency.OCCASIONAL: 3,
    NonverbalFrequency.FREQUENT: 6,
    NonverbalFrequency.VERY_FREQUENT: 10,
}


def annotate_nonverbal_cues(
    text: str,
    frequency: NonverbalFrequency,
    cues: Sequence[str],
) -> str:
    """Insert a stable cue plan at sentence boundaries before chunking.

    The same transcript and frequency always produce the same annotated text. This keeps
    checkpoint retries and process restarts aligned without persisting random-generator state.
    """

    if frequency is NonverbalFrequency.NEVER:
        return text

    normalized_cues = tuple(cue.strip().strip("[]") for cue in cues if cue.strip().strip("[]"))
    if not normalized_cues:
        raise ValueError("the selected provider does not expose non-verbal cues")
    if NONVERBAL_CUE_MARKER_PREFIX in text:
        raise ValueError(
            "the transcript contains SPLICR's reserved non-verbal cue marker; "
            "remove it or set non-verbal sounds to never"
        )
    if any(NONVERBAL_CUE_MARKER_SUFFIX in cue for cue in normalized_cues):
        raise ValueError("the selected provider exposes an invalid non-verbal cue")

    boundaries = [
        match.end() for match in _SENTENCE_END_RE.finditer(text) if match.end() < len(text)
    ]
    if not boundaries:
        return text

    words = len(_WORD_RE.findall(text))
    rate = _EVENTS_PER_1_000_WORDS[frequency]
    cue_count = min(len(boundaries), max(1, (words * rate + 999) // 1_000))
    text_digest = hashlib.sha256(text.encode("utf-8")).digest()

    def digest_for(position: int) -> bytes:
        payload = f"splicr-cue-v2\0{frequency.value}\0{position}\0".encode("utf-8") + text_digest
        return hashlib.sha256(payload).digest()

    selected = sorted(boundaries, key=digest_for)[:cue_count]
    selected.sort()

    annotated: list[str] = []
    cursor = 0
    for position in selected:
        digest = digest_for(position)
        cue = normalized_cues[int.from_bytes(digest[:4], "big") % len(normalized_cues)]
        marker = f"{NONVERBAL_CUE_MARKER_PREFIX}{cue}{NONVERBAL_CUE_MARKER_SUFFIX}"
        annotated.extend((text[cursor:position], f" {marker}"))
        cursor = position
    annotated.append(text[cursor:])
    return "".join(annotated)
