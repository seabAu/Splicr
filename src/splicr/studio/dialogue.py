from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, TypedDict


Speaker = Literal["Person1", "Person2"]
ProgressCallback = Callable[[str], None]
CancelCallback = Callable[[], bool]

_TURN_RE = re.compile(r"<(Person[12])>(.*?)</Person[12]>", re.DOTALL | re.IGNORECASE)
_FENCE_RE = re.compile(r"^\s*```[a-zA-Z]*\s*|\s*```\s*$")
_SENTENCE_RE = re.compile(r".*?(?:[.!?…]+(?:[\"'’”\)\]]+)?(?=\s+|$)|$)", re.DOTALL)
_STOP_WORDS = {
    "a", "an", "and", "as", "at", "be", "been", "but", "did", "do", "does",
    "for", "had", "has", "have", "he", "here", "how", "i", "in", "is", "it",
    "its", "not", "of", "on", "or", "she", "so", "that", "the", "there", "they",
    "this", "to", "was", "we", "were", "what", "which", "who", "why", "with", "you",
}


class ChatMessage(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatCompleter(Protocol):
    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2_048,
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class DialogueTurn:
    speaker: Speaker
    text: str

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("dialogue turn text must not be blank")


@dataclass(frozen=True, slots=True)
class DialogueGenerationOptions:
    host1_name: str = "Alex"
    host2_name: str = "Sam"
    host1_role: str = "explains the material clearly and with enthusiasm"
    host2_role: str = "asks the questions a smart newcomer would ask"
    style: str = "warm, curious and unhurried; plain language over jargon"
    words_per_section: int = 320
    section_chars: int = 6_000
    max_sections: int = 40
    temperature: float = 0.8

    def __post_init__(self) -> None:
        for label, value in (
            ("host1_name", self.host1_name),
            ("host2_name", self.host2_name),
            ("host1_role", self.host1_role),
            ("host2_role", self.host2_role),
            ("style", self.style),
        ):
            if not value.strip():
                raise ValueError(f"{label} must not be blank")
        if self.words_per_section < 50 or self.words_per_section > 2_000:
            raise ValueError("words_per_section must be between 50 and 2000")
        if self.section_chars < 500 or self.section_chars > 100_000:
            raise ValueError("section_chars must be between 500 and 100000")
        if self.max_sections < 1 or self.max_sections > 200:
            raise ValueError("max_sections must be between 1 and 200")
        if not 0 <= self.temperature <= 2:
            raise ValueError("temperature must be between 0 and 2")


@dataclass(frozen=True, slots=True)
class DialogueScript:
    turns: tuple[DialogueTurn, ...]
    sections: int
    outline: tuple[str, ...]
    removed_duplicates: int
    word_count: int
    cancelled: bool = False


class DialogueGenerationError(RuntimeError):
    pass


def _clean(text: str) -> str:
    return _FENCE_RE.sub("", text.strip())


def parse_turns(text: str) -> tuple[DialogueTurn, ...]:
    turns: list[DialogueTurn] = []
    for match in _TURN_RE.finditer(_clean(text)):
        speaker: Speaker = (
            "Person1" if match.group(1).casefold() == "person1" else "Person2"
        )
        body = " ".join(match.group(2).split())
        if body:
            turns.append(DialogueTurn(speaker=speaker, text=body))
    return tuple(turns)


def merge_consecutive(turns: Sequence[DialogueTurn]) -> tuple[DialogueTurn, ...]:
    merged: list[DialogueTurn] = []
    for turn in turns:
        if merged and merged[-1].speaker == turn.speaker:
            merged[-1] = DialogueTurn(
                speaker=turn.speaker,
                text=f"{merged[-1].text.rstrip()} {turn.text.lstrip()}",
            )
        else:
            merged.append(turn)
    return tuple(merged)


def _fingerprint(text: str) -> set[str]:
    words = re.findall(r"[a-z']+", text.casefold())
    return {word for word in words if word not in _STOP_WORDS and len(word) > 2}


def dedupe_turns(
    turns: Sequence[DialogueTurn],
    *,
    threshold: float = 0.72,
    min_words: int = 14,
) -> tuple[tuple[DialogueTurn, ...], int]:
    kept: list[DialogueTurn] = []
    seen: list[set[str]] = []
    removed = 0
    for turn in turns:
        fingerprint = _fingerprint(turn.text)
        if len(fingerprint) < min_words:
            kept.append(turn)
            continue
        duplicate = any(
            len(fingerprint & earlier) / max(1, len(fingerprint | earlier)) >= threshold
            for earlier in seen
            if earlier
        )
        if duplicate:
            removed += 1
            continue
        seen.append(fingerprint)
        kept.append(turn)
    return merge_consecutive(kept), removed


def _split_oversized(body: str, max_chars: int) -> list[str]:
    pieces: list[str] = []
    for paragraph in body.split("\n\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) <= max_chars:
            pieces.append(paragraph)
            continue
        sentences = [match.group(0).strip() for match in _SENTENCE_RE.finditer(paragraph)]
        sentences = [sentence for sentence in sentences if sentence]
        run = ""
        for sentence in sentences or [paragraph]:
            if run and len(run) + len(sentence) + 1 > max_chars:
                pieces.append(run)
                run = ""
            run = f"{run} {sentence}".strip()
            while len(run) > max_chars:
                pieces.append(run[:max_chars].strip())
                run = run[max_chars:].strip()
        if run:
            pieces.append(run)
    return pieces


def split_sections(
    text: str,
    *,
    max_chars: int = 6_000,
    max_sections: int = 40,
) -> tuple[tuple[str | None, str], ...]:
    if not text.strip():
        return ()
    blocks: list[tuple[str | None, str]] = []
    current: list[str] = []
    title: str | None = None
    for line in text.splitlines():
        if line.strip().startswith("#"):
            body = "\n".join(current).strip()
            if body:
                blocks.append((title, body))
            title = line.strip().lstrip("#").strip() or None
            current = []
        else:
            current.append(line)
    body = "\n".join(current).strip()
    if body:
        blocks.append((title, body))
    if not blocks:
        blocks = [(None, text.strip())]

    sized: list[tuple[str | None, str]] = []
    for heading, block in blocks:
        if len(block) <= max_chars:
            sized.append((heading, block))
            continue
        buffer = ""
        part = 1
        for piece in _split_oversized(block, max_chars):
            if buffer and len(buffer) + len(piece) + 2 > max_chars:
                part_title = f"{heading} (part {part})" if heading else None
                sized.append((part_title, buffer))
                buffer = ""
                part += 1
            buffer = f"{buffer}\n\n{piece}".strip()
        if buffer:
            part_title = f"{heading} (part {part})" if heading else None
            sized.append((part_title, buffer))
    return tuple(sized[:max_sections])


def _persona(options: DialogueGenerationOptions) -> str:
    return (
        "You are writing a two-host podcast conversation.\n"
        f"{options.host1_name} (Person1) {options.host1_role}.\n"
        f"{options.host2_name} (Person2) {options.host2_role}.\n"
        f"Tone: {options.style}.\n\n"
        "Output ONLY dialogue turns in exactly this form, nothing else:\n"
        "<Person1>spoken words</Person1>\n"
        "<Person2>spoken words</Person2>\n\n"
        "This is read aloud, so use no headings, bullets, stage directions, markdown, "
        "or citation markers. Never mention being an AI or that this is generated."
    )


async def _build_outline(
    document: str,
    sections: Sequence[tuple[str | None, str]],
    completer: ChatCompleter,
    *,
    model: str | None,
    progress: ProgressCallback,
) -> tuple[str, ...]:
    headings = [title for title, _ in sections if title]
    if len(headings) >= 3:
        progress(f"Using the document's {len(headings)} headings as the outline.")
        return tuple(title or f"Part {index + 1}" for index, (title, _) in enumerate(sections))
    progress("The document has no complete heading structure; generating an outline.")
    try:
        reply = await completer.complete(
            [
                {
                    "role": "system",
                    "content": "Plan podcast episodes. Reply with a numbered list of segment titles only.",
                },
                {
                    "role": "user",
                    "content": f"Plan a conversation about this material:\n\n{document[:12_000]}",
                },
            ],
            model=model,
            temperature=0.4,
            max_tokens=600,
        )
    except Exception as error:
        progress(f"Outline generation failed ({error}); using numbered parts.")
        return tuple(f"Part {index + 1}" for index in range(len(sections)))
    titles = tuple(
        re.sub(r"^\s*\d+[.)]\s*", "", line).strip()
        for line in reply.splitlines()
        if re.match(r"^\s*\d+[.)]", line)
    )
    return titles or tuple(f"Part {index + 1}" for index in range(len(sections)))


async def _summarize(
    previous: str,
    turns: Sequence[DialogueTurn],
    completer: ChatCompleter,
    *,
    model: str | None,
    progress: ProgressCallback,
) -> str:
    spoken = " ".join(turn.text for turn in turns)[:4_000]
    try:
        reply = await completer.complete(
            [
                {
                    "role": "system",
                    "content": "Keep a running note of what a podcast covered. Reply with at most 120 words of plain prose.",
                },
                {
                    "role": "user",
                    "content": (
                        f"Covered so far:\n{previous or '(nothing yet)'}\n\n"
                        f"Just discussed:\n{spoken}\n\nGive the updated running note."
                    ),
                },
            ],
            model=model,
            temperature=0.3,
            max_tokens=300,
        )
        return " ".join(_clean(reply).split())[:1_200]
    except Exception as error:
        progress(f"Summary update failed ({error}); retaining a plain excerpt.")
        return f"{previous} {spoken}".strip()[-1_200:]


async def generate_script(
    document: str,
    completer: ChatCompleter,
    *,
    options: DialogueGenerationOptions | None = None,
    model: str | None = None,
    progress: ProgressCallback = lambda _message: None,
    should_cancel: CancelCallback = lambda: False,
) -> DialogueScript:
    selected = options or DialogueGenerationOptions()
    sections = split_sections(
        document,
        max_chars=selected.section_chars,
        max_sections=selected.max_sections,
    )
    if not sections:
        raise DialogueGenerationError("There is no text to turn into dialogue.")
    progress(f"Planning {len(sections)} section(s).")
    outline = await _build_outline(
        document,
        sections,
        completer,
        model=model,
        progress=progress,
    )
    outline_text = "\n".join(f"{index + 1}. {title}" for index, title in enumerate(outline))
    persona = _persona(selected)
    all_turns: list[DialogueTurn] = []
    running = ""
    last_speaker: Speaker | None = None
    cancelled = False

    for index, (title, body) in enumerate(sections):
        if should_cancel():
            cancelled = True
            progress("Cancelled; keeping the script generated so far.")
            break
        progress(f"Writing section {index + 1} of {len(sections)}: {title or 'Untitled'}.")
        if index == 0:
            staging = "Greet the listener once, briefly introduce both hosts, and begin."
        elif index == len(sections) - 1:
            staging = "Continue mid-conversation, cover this final section, then close the episode. Do not greet again."
        else:
            staging = "Continue mid-conversation without greetings, introductions, recaps, or break language."
        if last_speaker:
            other: Speaker = "Person2" if last_speaker == "Person1" else "Person1"
            staging += f" The previous turn was {last_speaker}; begin with {other}."
        position = (
            "the first section"
            if index == 0
            else "the last section"
            if index == len(sections) - 1
            else f"section {index + 1} of {len(sections)}"
        )
        prompt = (
            f"EPISODE OUTLINE:\n{outline_text}\n\n"
            f"ALREADY COVERED (do not repeat):\n{running or '(nothing yet)'}\n\n"
            f"YOU ARE WRITING {position}{f', titled {title!r}' if title else ''}.\n"
            f"{staging}\n\nAim for roughly {selected.words_per_section} words.\n\n"
            f"SOURCE MATERIAL:\n{body}"
        )
        try:
            reply = await completer.complete(
                [
                    {"role": "system", "content": persona},
                    {"role": "user", "content": prompt},
                ],
                model=model,
                temperature=selected.temperature,
                max_tokens=max(600, selected.words_per_section * 3),
            )
        except Exception as error:
            if index == 0:
                raise DialogueGenerationError(f"The first dialogue section failed: {error}") from error
            progress(f"Section {index + 1} failed and was skipped: {error}")
            continue
        turns = merge_consecutive(parse_turns(reply))
        if not turns:
            progress(f"Section {index + 1} contained no usable speaker tags and was skipped.")
            continue
        all_turns.extend(turns)
        last_speaker = turns[-1].speaker
        if index < len(sections) - 1:
            running = await _summarize(
                running,
                turns,
                completer,
                model=model,
                progress=progress,
            )

    if not all_turns:
        if cancelled:
            return DialogueScript((), len(sections), outline, 0, 0, cancelled=True)
        raise DialogueGenerationError(
            "No usable dialogue was produced; verify that the model follows the Person1/Person2 tag format."
        )
    final, removed = dedupe_turns(all_turns)
    words = sum(len(turn.text.split()) for turn in final)
    progress(f"Script ready: {len(final)} turns and approximately {words} words.")
    return DialogueScript(final, len(sections), outline, removed, words, cancelled)


async def refine_selection(
    *,
    before: str,
    selected: str,
    after: str,
    instruction: str,
    speaker: Speaker,
    completer: ChatCompleter,
    model: str | None = None,
    neighbor_before: DialogueTurn | None = None,
    neighbor_after: DialogueTurn | None = None,
) -> str:
    if not selected.strip():
        raise DialogueGenerationError("Nothing is selected to refine.")
    if not instruction.strip():
        raise DialogueGenerationError("Describe how the selected line should change.")
    context: list[str] = []
    if neighbor_before:
        context.append(f"{neighbor_before.speaker}: {neighbor_before.text}")
    context.append(f"{speaker} (editing): {before}[[[{selected}]]]{after}")
    if neighbor_after:
        context.append(f"{neighbor_after.speaker}: {neighbor_after.text}")
    context_text = "\n".join(context)
    reply = await completer.complete(
        [
            {
                "role": "system",
                "content": (
                    "Rewrite only the span inside [[[triple brackets]]] in the line marked editing. "
                    "Other text is context only. Follow the instruction and return only replacement text, "
                    "with no brackets, quotes, explanation, or speaker label."
                ),
            },
            {
                "role": "user",
                "content": f"{context_text}\n\nINSTRUCTION: {instruction.strip()}",
            },
        ],
        model=model,
        temperature=0.5,
        max_tokens=400,
    )
    replacement = reply.strip()
    while replacement:
        previous = replacement
        replacement = replacement.strip().strip("[]").strip()
        if len(replacement) >= 2 and replacement[0] == replacement[-1] == '"':
            replacement = replacement[1:-1].strip()
        if replacement == previous:
            break
    if not replacement:
        raise DialogueGenerationError("The rewrite was empty; try a more specific instruction.")
    return replacement
