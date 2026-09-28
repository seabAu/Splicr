"""Permanent word substitutions, for the engines that have no pronunciation
dictionary.

WHY THIS EXISTS. Kokoro can be told how to *say* a word: a respelling is
resolved to phonemes and pushed into its lexicon, so the spelling on the page
never changes and the fix applies to every future document. Qwen3 and
edge-tts expose no such hook. The only way to change how they say a word is
to change what is written, and until now that could only be done inside one
take -- so the same term had to be corrected again in every episode, by hand,
forever.

A substitution is a rewrite applied to the cleaned text just before it is
chunked. Because it changes the text, the render cache key changes with it
automatically: no separate fingerprint is needed, unlike the pronunciation
dictionary, which changes the audio without changing the text.

WHAT THIS IS NOT. It is not a pronunciation dictionary and cannot express
anything phonetic. "nuh-RAT-iv" is a guess about how an engine reads
hyphenated capitals, not an instruction. On Kokoro a respelling is almost
always the better tool, and the interface says so -- but substitutions apply
there too, because someone who adds one means it, and because a respelling
occasionally cannot be resolved at all.
"""

import json
import os

from .config import DATA_DIR

SUBSTITUTIONS_FILE = os.path.join(DATA_DIR, "narrator_substitutions.json")


def load_substitutions():
    try:
        with open(SUBSTITUTIONS_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return {str(k): str(v) for k, v in data.items()
            if str(k).strip() and str(v).strip()}


def save_substitutions(subs):
    os.makedirs(os.path.dirname(SUBSTITUTIONS_FILE), exist_ok=True)
    cleaned = {str(k).strip(): str(v).strip() for k, v in (subs or {}).items()
               if str(k).strip() and str(v).strip()}
    with open(SUBSTITUTIONS_FILE, "w", encoding="utf-8") as fh:
        json.dump(cleaned, fh, ensure_ascii=False, indent=2, sort_keys=True)
    return cleaned


def add_substitution(word, replacement):
    subs = load_substitutions()
    from .words import normalise
    subs[normalise(word)] = replacement.strip()
    return save_substitutions(subs)


def remove_substitution(word):
    from .words import normalise
    subs = load_substitutions()
    subs.pop(normalise(word), None)
    return save_substitutions(subs)


def apply_substitutions(text, subs=None, log=None):
    """Rewrite every whole-word occurrence in `text`.

    Longest words first: without that, a substitution for "state" would
    corrupt one for "state of nature" by getting there first, and which one
    won would depend on dictionary ordering -- a bug that would look random.
    """
    from .words import substitute, count_in
    subs = load_substitutions() if subs is None else subs
    if not subs or not text:
        return text, {}
    applied = {}
    for word in sorted(subs, key=len, reverse=True):
        n = count_in(text, word)
        if n:
            text = substitute(text, word, subs[word])
            applied[word] = n
    if log and applied:
        total = sum(applied.values())
        log(f"  applied {len(applied)} substitution(s), {total} occurrence(s)")
    return text, applied
