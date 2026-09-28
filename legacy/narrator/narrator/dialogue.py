"""Turning a document into a two-host conversation.

This is the piece that makes NotebookLM-style audio appealing, and it is a
*script* problem rather than a TTS one -- the engines Narrator already has
are competitive; what they lack is something to say to each other.

The shape, and why:

1. **Outline first.** One pass over the whole document produces a
   segmented plan. Without it, section-by-section generation has no global
   thread and the episode wanders.
2. **Section by section, with a rolling summary.** Each section is
   generated knowing the outline, what has already been said, and who
   spoke last. This is what stops the hosts re-introducing themselves
   every few minutes -- the single most obvious tell of a chunked script.
3. **Stitch, then dedupe across sections.** Chunked generation repeats
   points at *section* level, and ordinary repetition penalties do not
   catch that because the repeats are far apart. It has to be handled
   deliberately, here, after the fact.

Turns use the `<Person1>` / `<Person2>` convention rather than JSON: it is
tolerant of the surrounding chatter models like to add, trivial to parse,
and rarely broken even by small local models. Strict JSON would need
constrained decoding to be reliable, which is a heavier dependency for no
gain at this stage.

No tkinter, no HTTP framework: takes a provider config and a `log`
callable, returns plain data.
"""

import re

from .llm import LLMError, complete

TURN_RE = re.compile(r"<(Person[12])>(.*?)</Person[12]>", re.S | re.I)
# Models like to wrap output in fences or preamble; strip the obvious.
FENCE_RE = re.compile(r"^\s*```[a-zA-Z]*\s*|\s*```\s*$")

DEFAULTS = {
    "host1_name": "Alex",
    "host2_name": "Sam",
    "host1_role": "explains the material clearly and with enthusiasm",
    "host2_role": "asks the questions a smart newcomer would ask",
    "style": "warm, curious and unhurried; plain language over jargon",
    "words_per_section": 320,
    "section_chars": 6000,
    "max_sections": 40,
    "temperature": 0.8,
}


def _clean(text):
    return FENCE_RE.sub("", (text or "").strip())


def parse_turns(text):
    """Speaker turns from a model's reply. Anything outside the tags --
    preamble, apologies, stage directions -- is discarded, which is why
    this convention survives models that can't resist adding commentary."""
    turns = []
    for match in TURN_RE.finditer(_clean(text)):
        speaker = "Person1" if match.group(1).lower() == "person1" else "Person2"
        body = " ".join(match.group(2).split())
        if body:
            turns.append({"speaker": speaker, "text": body})
    return turns


def merge_consecutive(turns):
    """Join runs by the same speaker. Models occasionally emit two turns
    in a row for one person; rendering those separately would put an
    audible seam mid-thought."""
    merged = []
    for turn in turns:
        if merged and merged[-1]["speaker"] == turn["speaker"]:
            merged[-1]["text"] = merged[-1]["text"].rstrip() + " " + turn["text"]
        else:
            merged.append(dict(turn))
    return merged


def _fingerprint(text):
    words = re.findall(r"[a-z']+", text.lower())
    # Very common words carry no signal about whether a POINT was repeated.
    stop = {"the", "a", "an", "and", "or", "but", "so", "of", "to", "in",
            "is", "it", "that", "this", "on", "for", "with", "as", "at",
            "we", "you", "i", "he", "she", "they", "was", "were", "be",
            "been", "have", "has", "had", "do", "does", "did", "not",
            "what", "which", "who", "how", "why", "there", "here", "its"}
    return {w for w in words if w not in stop and len(w) > 2}


def dedupe_turns(turns, threshold=0.72, min_words=14):
    """Drop turns that repeat a point already made.

    Section-level repetition is the documented weakness of generating a
    long script in chunks: each section is coherent, but the third one
    re-explains what the first already covered. Repetition penalties
    inside the model do not reach across that distance.

    Short turns are never dropped -- "Right, exactly." is not a repeated
    point, and removing acknowledgements would make the conversation
    lurch.
    """
    kept, seen = [], []
    removed = 0
    for turn in turns:
        prints = _fingerprint(turn["text"])
        if len(prints) < min_words:
            kept.append(turn)
            continue
        duplicate = False
        for earlier in seen:
            if not earlier:
                continue
            overlap = len(prints & earlier) / max(1, len(prints | earlier))
            if overlap >= threshold:
                duplicate = True
                break
        if duplicate:
            removed += 1
            continue
        seen.append(prints)
        kept.append(turn)
    return merge_consecutive(kept), removed


def split_sections(text, max_chars=6000, max_sections=40):
    """Sections from the document's own headings where it has them, since
    an author's structure beats an arbitrary character count. Falls back
    to paragraph-packing, and splits anything still oversized."""
    lines = text.split("\n")
    blocks, current, title = [], [], None
    for line in lines:
        if line.strip().startswith("#"):
            if current and any(l.strip() for l in current):
                blocks.append((title, "\n".join(current).strip()))
            title = line.strip().lstrip("#").strip()
            current = []
        else:
            current.append(line)
    if current and any(l.strip() for l in current):
        blocks.append((title, "\n".join(current).strip()))
    if not blocks:
        blocks = [(None, text.strip())]

    sized = []
    for heading, body in blocks:
        if len(body) <= max_chars:
            sized.append((heading, body))
            continue
        # Pack paragraphs, but a single paragraph can itself exceed the
        # limit -- prose with no blank lines is common in converted
        # documents -- so oversized pieces are broken on sentence
        # boundaries, reusing the same splitter the narration path uses.
        from .documents import split_sentences
        pieces = []
        for paragraph in body.split("\n\n"):
            if len(paragraph) <= max_chars:
                pieces.append(paragraph)
                continue
            run = ""
            for sentence in split_sentences(paragraph):
                if run and len(run) + len(sentence) > max_chars:
                    pieces.append(run.strip())
                    run = ""
                run += sentence + " "
                # A single sentence longer than the limit is pathological
                # but real (a table flattened into prose); cut it rather
                # than emit something the model will truncate silently.
                while len(run) > max_chars:
                    pieces.append(run[:max_chars].strip())
                    run = run[max_chars:]
            if run.strip():
                pieces.append(run.strip())

        buffer, part = "", 1
        for piece in pieces:
            if buffer and len(buffer) + len(piece) > max_chars:
                sized.append((f"{heading} (part {part})" if heading else None,
                             buffer.strip()))
                buffer, part = "", part + 1
            buffer += piece + "\n\n"
        if buffer.strip():
            sized.append((f"{heading} (part {part})" if heading else None,
                         buffer.strip()))
    return sized[:max_sections]


def load_document(path):
    """Read a document for dialogue generation, KEEPING its headings.

    The narration path deliberately strips headings (they become spoken
    transitions or vanish), but this pipeline needs them: they are what
    `split_sections` and `build_outline` use to follow the author's own
    structure instead of guessing. Reading with the ordinary
    `read_text_file` produced a single unsectioned blob and an outline
    invented from scratch -- correct-looking output, quietly worse.

    Tables stay narrated rather than kept as markup, since this is read
    aloud.
    """
    from .documents import clean_document
    text, _log, _words = clean_document(path, keep_headings="markup")
    return text


def _persona(options):
    o = {**DEFAULTS, **(options or {})}
    return (
        f"You are writing a two-host podcast conversation.\n"
        f"{o['host1_name']} (Person1) {o['host1_role']}.\n"
        f"{o['host2_name']} (Person2) {o['host2_role']}.\n"
        f"Tone: {o['style']}.\n\n"
        "Output ONLY dialogue turns in exactly this form, nothing else:\n"
        "<Person1>spoken words</Person1>\n"
        "<Person2>spoken words</Person2>\n\n"
        "This is read aloud, so: no headings, no bullet points, no stage "
        "directions, no markdown, no citation markers, and never mention "
        "being an AI or that this is generated."), o


def build_outline(document, provider, options, log, model=None):
    """A segmented plan for the whole episode.

    Uses the document's headings when it has them -- an author's own
    structure is better than anything inferred, and it costs no tokens.
    Only asks the model when there is nothing to go on.
    """
    sections = split_sections(document,
                             max_chars=(options or {}).get(
                                 "section_chars", DEFAULTS["section_chars"]))
    headings = [title for title, _body in sections if title]
    if len(headings) >= 3:
        log(f"  outline: using the document's own {len(headings)} headings")
        return [t or f"Part {i + 1}" for i, (t, _b) in enumerate(sections)]

    log("  outline: the document has no usable headings, asking the model")
    system, _o = _persona(options)
    excerpt = document[:12000]
    try:
        reply = complete(
            provider,
            [{"role": "system",
              "content": "You plan podcast episodes. Reply with a numbered "
                         "list of segment titles and nothing else."},
             {"role": "user",
              "content": "Plan the segments for a conversation about this "
                         f"material:\n\n{excerpt}"}],
            model=model, temperature=0.4, max_tokens=600)
    except LLMError as exc:
        log(f"  outline failed ({exc}); falling back to numbered parts")
        return [f"Part {i + 1}" for i in range(len(sections))]
    titles = [re.sub(r"^\s*\d+[.)]\s*", "", line).strip()
             for line in reply.splitlines()
             if re.match(r"^\s*\d+[.)]", line)]
    return titles or [f"Part {i + 1}" for i in range(len(sections))]


def _summarise(previous, new_turns, provider, options, log, model=None):
    """A running account of what has been covered, so later sections know
    what not to repeat. Kept short on purpose: it rides in every
    subsequent prompt, and a summary that grows without bound eats the
    context the actual material needs."""
    spoken = " ".join(t["text"] for t in new_turns)[:4000]
    try:
        reply = complete(
            provider,
            [{"role": "system",
              "content": "You keep a running note of what a podcast has "
                         "covered so far. Reply with at most 120 words of "
                         "plain prose. No preamble."},
             {"role": "user",
              "content": f"Covered so far:\n{previous or '(nothing yet)'}"
                         f"\n\nJust discussed:\n{spoken}\n\n"
                         "Give the updated running note."}],
            model=model, temperature=0.3, max_tokens=300)
        return " ".join(_clean(reply).split())[:1200]
    except LLMError as exc:
        # Not fatal: fall back to accumulating raw text, trimmed. A worse
        # summary is much better than abandoning a long generation.
        log(f"  (summary step failed: {exc}; using a plain excerpt)")
        return (previous + " " + spoken)[-1200:]


def generate_script(document, provider, options=None, log=print, model=None,
                    should_cancel=lambda: False):
    """Document in, dialogue turns out.

    Returns {"turns", "sections", "outline", "removed_duplicates",
    "word_count"}. Raises LLMError only if the FIRST section fails --
    after that, a failed section is logged and skipped, because losing one
    section of a long episode is better than losing the whole run.
    """
    system, o = _persona(options)
    sections = split_sections(document, o["section_chars"], o["max_sections"])
    if not sections:
        raise LLMError("There is no text in that document to work from.")
    log(f"Planning {len(sections)} section(s)...")
    outline = build_outline(document, provider, o, log, model)
    outline_text = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(outline))

    all_turns, running, last_speaker = [], "", None
    cancelled = False
    for index, (title, body) in enumerate(sections):
        if should_cancel():
            cancelled = True
            log("Cancelled; keeping what has been written so far.")
            break
        position = ("the FIRST section" if index == 0 else
                   "the LAST section" if index == len(sections) - 1 else
                   f"section {index + 1} of {len(sections)}")
        log(f"  [{index + 1}/{len(sections)}] {title or 'untitled'}")

        # These four instructions are what keep a chunked script sounding
        # like one conversation: where we are, what not to repeat, who
        # speaks next, and no "picking up where we left off" seams.
        if index == 0:
            staging = ("Open the episode: greet the listener once, "
                      "introduce yourselves briefly by name and say what "
                      "the episode is about. Then begin this section.")
        elif index == len(sections) - 1:
            staging = ("This is the end. Cover this section, then draw the "
                      "episode to a close and say goodbye. Do NOT greet "
                      "the listener again.")
        else:
            staging = ("Continue mid-conversation. Do NOT greet the "
                      "listener, do NOT re-introduce yourselves, and do "
                      "NOT say things like 'picking up where we left off' "
                      "or 'after the break'.")
        if last_speaker:
            other = "Person2" if last_speaker == "Person1" else "Person1"
            staging += f" The previous turn was {last_speaker}, so begin " \
                       f"with {other}."

        prompt = (
            f"EPISODE OUTLINE:\n{outline_text}\n\n"
            f"ALREADY COVERED (do not repeat these points):\n"
            f"{running or '(nothing yet)'}\n\n"
            f"YOU ARE WRITING {position}"
            + (f', titled "{title}"' if title else "") + ".\n"
            f"{staging}\n\n"
            f"Aim for roughly {o['words_per_section']} words of dialogue.\n\n"
            f"SOURCE MATERIAL FOR THIS SECTION:\n{body}")

        try:
            reply = complete(provider, [{"role": "system", "content": system},
                                       {"role": "user", "content": prompt}],
                            model=model, temperature=o["temperature"],
                            max_tokens=max(600, o["words_per_section"] * 3))
        except LLMError as exc:
            if index == 0:
                raise
            log(f"    section failed, skipping it: {exc}")
            continue

        turns = merge_consecutive(parse_turns(reply))
        if not turns:
            log("    the model returned no speaker turns for this section; "
               "skipped")
            continue
        all_turns.extend(turns)
        last_speaker = turns[-1]["speaker"]
        if index < len(sections) - 1:
            running = _summarise(running, turns, provider, o, log, model)

    if not all_turns:
        if cancelled:
            # Stopping before anything was written is not a fault, and
            # must not be reported as one.
            log("Cancelled before any dialogue was written.")
            return {"turns": [], "sections": len(sections),
                   "outline": outline, "removed_duplicates": 0,
                   "word_count": 0, "cancelled": True}
        raise LLMError(
            "No usable dialogue was produced. The model may not be "
            "following the required <Person1>/<Person2> format -- verify "
            "the provider to check.")

    final, removed = dedupe_turns(merge_consecutive(all_turns))
    words = sum(len(t["text"].split()) for t in final)
    if removed:
        log(f"  removed {removed} repeated point(s) across sections")
    log(f"Script: {len(final)} turns, about {words:,} words "
       f"(~{words / 150:.0f} minutes spoken)")
    return {"turns": final, "sections": len(sections), "outline": outline,
            "removed_duplicates": removed, "word_count": words,
            "cancelled": cancelled}


def refine_selection(before, selected, after, instruction, speaker,
                     provider, model=None, neighbor_before=None,
                     neighbor_after=None):
    """Rewrite one selected span of a turn's text per a short instruction
    -- the Copilot-inline-edit / Google-Docs shape: select a chunk,
    type a one-line instruction, get just that chunk rewritten in place.

    `before`/`after` are the unselected text either side of the
    selection WITHIN THE SAME TURN, so the model can keep the rewrite
    grammatically joined to what surrounds it rather than returning a
    self-contained sentence that reads oddly once spliced back in.
    `neighbor_before`/`neighbor_after` are the adjacent turns (the other
    host's lines), included only for conversational context -- they are
    never rewritten.

    Returns the replacement text for `selected` alone. Raises LLMError
    on any failure (empty instruction, no selection, provider error) --
    the caller decides how to surface that; this function does not log,
    since a single inline edit doesn't need a job/progress log the way a
    whole-script generation does.
    """
    if not (selected or "").strip():
        raise LLMError("Nothing is selected to refine.")
    if not (instruction or "").strip():
        raise LLMError("Say how that line should change.")

    context_lines = []
    if neighbor_before:
        context_lines.append(f"{neighbor_before['speaker']}: "
                             f"{neighbor_before['text']}")
    context_lines.append(
        f"{speaker} (the line being edited): {before}"
        f"[[[{selected}]]]{after}")
    if neighbor_after:
        context_lines.append(f"{neighbor_after['speaker']}: "
                             f"{neighbor_after['text']}")
    context = "\n".join(context_lines)

    system = (
        "You edit ONE marked span inside a two-host podcast script. The "
        "span to rewrite is wrapped in [[[triple brackets]]] within the "
        "line marked '(the line being edited)'. Surrounding lines and "
        "surrounding text on the same line are context only -- do not "
        "repeat or rewrite them. Follow the instruction exactly. Keep "
        "the rewrite the same rough length as the original unless told "
        "otherwise, and make sure it reads naturally joined to the text "
        "immediately before and after it (matching capitalization and "
        "punctuation at the seam). Reply with ONLY the replacement text "
        "for the marked span -- no brackets, no quotes, no explanation, "
        "no speaker label.")
    prompt = f"{context}\n\nINSTRUCTION: {instruction}"

    reply = complete(
        provider, [{"role": "system", "content": system},
                  {"role": "user", "content": prompt}],
        model=model, temperature=0.5, max_tokens=400)
    replacement = reply.strip()
    # A model that ignores the "no brackets/quotes" instruction is common
    # enough to guard for cheaply, rather than shipping stray formatting
    # into the script. Quotes and brackets can wrap in either order
    # ("[text]" or ["text"]), so peel one layer at a time until a pass
    # changes nothing, rather than assuming a fixed nesting order.
    while True:
        before_pass = replacement
        replacement = replacement.strip().strip("[]").strip()
        if (len(replacement) >= 2 and replacement[0] == '"'
                and replacement[-1] == '"'):
            replacement = replacement[1:-1].strip()
        if replacement == before_pass:
            break
    if not replacement:
        raise LLMError("The rewrite came back empty -- try rephrasing "
                       "the instruction.")
    return replacement


def script_to_text(turns):
    """The script as taggged text, for saving or editing by hand."""
    return "\n".join(f"<{t['speaker']}>{t['text']}</{t['speaker']}>"
                    for t in turns)


def render_plan(turns, voice1, voice2):
    """(voice, text) per turn, ready to hand to a TTS engine.

    Consecutive same-speaker turns are already merged, so each entry is
    one continuous piece of speech in one voice -- which is exactly the
    unit the engines render and `_join_chunk_wavs` joins.
    """
    return [(voice1 if t["speaker"] == "Person1" else voice2, t["text"])
            for t in turns]
