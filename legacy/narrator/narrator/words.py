"""Finding one word across a finished take, and fixing every place it says
it.

WHY THIS SHAPE. The obvious reading of "word-level editing" is to re-record
one word and splice its audio in place. That was considered and rejected on
the merits: sentence-level splicing works because sentence boundaries are
silent, giving a natural gap to hide a short crossfade in, whereas word
boundaries inside a phrase are coarticulated with the pitch contour running
straight through them. A word generated on its own comes out in citation
form -- fully stressed, slower, with a falling terminal pitch -- and dropped
mid-phrase that reads as an audible step, a worse artefact than the
mispronunciation it was meant to repair.

So the unit of *diagnosis and fix* here is the word, and the unit of
*re-recording* stays the sentence. You point at the word that is wrong, say
how it should sound, and every sentence in the take that contains it is
re-recorded and spliced back. The cost is that forty occurrences take forty
sentence generations rather than forty word-length ones, which is nothing
next to the hour the original render took.

The second reason for this shape is reach. Word timestamps exist only for
Kokoro in English (its non-English path never computes them) and, in a form
we cannot splice into, for edge-tts, whose chunks are compressed mp3.
Matching on segment *text* needs no timestamps at all, so this works on
Kokoro and Qwen3 alike.

Nothing here imports tkinter or any engine.
"""

import re

# A word, as a person would point at one: letters, with internal
# apostrophes and hyphens kept ("don't", "well-known") since those are part
# of the word being mispronounced rather than separators.
WORD_RE = re.compile(r"[^\W\d_][\w'\u2019-]*", re.UNICODE)


def words_in(text):
    """Every word of a sentence, in order, with its character span.

    The span is what lets the interface show a word as clickable within the
    sentence it came from, and what tells a substitution exactly which
    characters to replace.
    """
    return [{"text": m.group(0), "at": m.start(), "to": m.end()}
            for m in WORD_RE.finditer(text or "")]


def normalise(word):
    """The form two spellings of the same word share, for matching.

    Case is folded, and the curly apostrophe is folded onto the straight one
    so a word typed in a text box matches the same word as it arrived from a
    word processor -- a difference nobody can see and everybody hits.
    """
    return (word or "").strip().replace("\u2019", "'").lower()


def _word_pattern(word):
    """Whole-word, case-insensitive match for `word`.

    Deliberately not \\b...\\b around a raw escape: a word ending in an
    apostrophe or hyphen makes \\b land in a surprising place. Instead the
    match is bounded by "not a word character" on either side, evaluated
    against the same character class WORD_RE uses.
    """
    body = re.escape(word.replace("\u2019", "'"))
    # Match either apostrophe form wherever the word has one.
    body = body.replace("'", "['\u2019]")
    return re.compile(rf"(?<![\w'\u2019-]){body}(?![\w'\u2019-])",
                      re.IGNORECASE | re.UNICODE)


def count_in(text, word):
    return len(_word_pattern(word).findall(text or ""))


def substitute(text, word, replacement):
    """Replace every whole-word occurrence of `word` with `replacement`.

    Used for the engines that have no pronunciation lexicon, where the only
    way to change how a word is said is to change what is written. The
    replacement goes in exactly as given -- no case matching -- because a
    respelling like "nuh-RAT-iv" is not a capitalisation variant of the word
    it replaces and quietly title-casing it would change how it is read.
    """
    return _word_pattern(word).sub(replacement, text or "")


def segments_of(result, chunk_index):
    """The sentence spans of one chunk, from the render or its sidecar."""
    from .segments import load_segments
    segs = (result.get("segments")
            or [None] * len(result["chunk_paths"]))[chunk_index]
    if segs:
        return segs
    return load_segments(result["chunk_paths"][chunk_index],
                         result["chunk_texts"][chunk_index],
                         result["chunk_durations"][chunk_index])


def occurrences(result, word):
    """Every sentence in a take that says `word`.

    Returns a list of dicts: chunk, seg, text, count, start, end -- where
    start/end are the sentence's span inside its own chunk's audio, which is
    what "play this sentence" and the splice both work in.
    """
    found = []
    for i in range(len(result.get("chunk_paths", []))):
        for k, seg in enumerate(segments_of(result, i)):
            n = count_in(seg.get("text", ""), word)
            if n:
                found.append({"chunk": i, "seg": k, "text": seg["text"],
                              "count": n, "start": seg.get("start", 0.0),
                              "end": seg.get("end", 0.0)})
    return found


def distinct_words(result, min_length=2):
    """Every distinct word in a take, with how often it is said.

    Sorted by frequency then alphabetically: a word that is wrong in fifty
    places is both the most worth fixing and the most annoying to find by
    scrolling, so it belongs at the top.
    """
    counts = {}
    for i in range(len(result.get("chunk_paths", []))):
        for seg in segments_of(result, i):
            for w in words_in(seg.get("text", "")):
                if len(w["text"]) < min_length:
                    continue
                key = normalise(w["text"])
                entry = counts.setdefault(key, {"word": w["text"], "count": 0})
                entry["count"] += 1
    return sorted(counts.values(),
                  key=lambda e: (-e["count"], normalise(e["word"])))


def plan_fix(result, word, engine_key, replacement=None):
    """What fixing `word` would involve, without doing any of it.

    Returns (occurrences, mode, problem) where mode is:

      "lexicon"      -- Kokoro: the respelling goes in the pronunciation
                        dictionary and the sentence text is re-rendered
                        unchanged, so the fix also applies to every future
                        document.
      "substitution" -- Qwen3: no lexicon exists to intercept, so the word
                        is rewritten in the sentence text before it is
                        re-recorded. This take is fixed; the change is not
                        remembered for future renders.

    and `problem` is a sentence explaining why nothing can be done, or None.
    Checked up front so the interface can refuse clearly instead of failing
    partway through a batch of splices.
    """
    found = occurrences(result, word)
    if not found:
        return [], None, f"Nothing in this take says {word!r}."

    paths = result.get("chunk_paths") or []
    if any(not str(paths[o["chunk"]]).lower().endswith(".wav")
           for o in found):
        return found, None, (
            "Sentence-level fixes need uncompressed chunk audio. This take "
            "was made with edge-tts, whose chunks are mp3 -- use "
            "'Regenerate this chunk' instead.")

    if engine_key == "kokoro":
        return found, "lexicon", None
    if engine_key == "qwen3":
        if not (replacement or "").strip():
            return found, "substitution", (
                "Qwen3 has no pronunciation dictionary to correct, so this "
                "needs a replacement spelling to put in the text instead.")
        return found, "substitution", None
    return found, None, (
        f"Fixing a word everywhere isn't supported for the {engine_key} "
        f"engine.")
