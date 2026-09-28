"""Pronunciation scanning and the custom lexicon (Kokoro only).
"""

import argparse
import datetime
import hashlib
import importlib.util
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import wave

from .config import PRONOUNCE_FILE, load_pronunciations


# ---------------------------------------------------------------------------
# Pronunciation scanning (Kokoro only)
#
# Kokoro's dictionary is checked first; anything it doesn't recognise falls
# through to espeak-ng, a rule-based fallback that's serviceable on ordinary
# words but frequently wrong on longer derived words like "narrativization"
# and on invented or domain-specific terms it's never seen. There is no way
# to ask Kokoro in advance whether a given word will land correctly -- so
# this scanner reproduces the same lookup Kokoro performs at narration time,
# offline, before you spend minutes generating audio to find out by ear.
# ---------------------------------------------------------------------------

WORD_PATTERN = re.compile(r"[A-Za-z][A-Za-z'\-]*")

# Ordinary words too short or too common to be worth flagging even when the
# dictionary lookup fails to confirm them (single letters, "a", "I", etc).
_SKIP_SHORT = {"a", "i"}


def _looks_like_acronym(word):
    """All-caps, 2+ letters, no vowspace -- SCADA, PLC, NASA, IoT excluded
    (mixed case). Matches the class of word where letter-by-letter spelling
    is a live question, whether or not Kokoro already handles it correctly."""
    return len(word) >= 2 and word.isupper() and word.isalpha()


def spell_out(word):
    """A.C.R.O.N.Y.M. form that forces letter-by-letter reading.

    Confirmed by direct testing: fully uppercase, period-separated letters
    make Kokoro read each letter individually. Mixed case or no periods does
    not reliably do this -- some already-known acronyms (NASA, SQL, SCUBA)
    read as words either way, which is usually what you want, so this is
    offered as a suggestion to apply selectively, not a default rewrite.

    This is the display/spelling form. Do NOT store it as a lexicon override:
    the lexicon holds IPA, and literal periods leak through into the phoneme
    stream as audible artefacts. Use acronym_ipa() for the stored value.
    """
    return ".".join(word) + "."


def parse_pieces_with_stress(text):
    """'an on nim *my nation' -> (['an','on','nim','my','nation'], 3)

    Mark which piece carries the primary stress with a leading '*'. Without
    one, the first piece is stressed -- matching respell_to_ipa's own
    default, so a respelling typed with no '*' behaves exactly as it always
    has. This one function is shared between the pronunciation dialog and
    word_check.py so the two can never disagree about what a given line of
    text will produce.
    """
    raw = text.split()
    pieces, stress_on = [], None
    for i, tok in enumerate(raw):
        if tok.startswith("*") and len(tok) > 1:
            stress_on = i
            tok = tok[1:]
        pieces.append(tok)
    if stress_on is None:
        stress_on = 0
    return pieces, stress_on


def respell_to_ipa(pieces, stress_on=0):
    """Build a lexicon override from ordinary words, not raw IPA.

    `pieces` is a list of real, correctly-pronounceable English words or
    syllables that sound like the target word when read in sequence --
    e.g. ["narrative", "izing"] for "narrativizing". Each piece is resolved
    through Kokoro's own G2P and concatenated, so the result uses the exact
    phoneme set Kokoro expects. Without this, a person typing standard
    dictionary IPA by hand (plain "r", no mandatory stress marks) produces a
    string Kokoro treats as a raw phoneme sequence anyway -- not validated,
    not corrected -- and the mismatch between dictionary IPA and Kokoro's
    specific symbol set can render markedly worse than the espeak-ng
    fallback it was meant to fix.

    Every piece keeps its own internal stress pattern; only the primary
    stress mark on pieces other than `stress_on` is demoted to secondary, so
    the result carries one primary stress like a real word rather than a
    string of separately-stressed syllables.

    Returns (ipa, None) on success, or (None, failed_piece) naming the first
    piece that wasn't itself a real, resolvable word.
    """
    try:
        from misaki import en as misaki_en
    except ImportError:
        return None, "(misaki not installed)"
    try:
        g2p = misaki_en.G2P(trf=False, british=False)
        parts = []
        for i, piece in enumerate(pieces):
            piece = piece.strip()
            if not piece:
                continue
            result, _ = g2p(piece)
            if not result or result == "❓":
                return None, piece
            if i != stress_on:
                result = result.replace("ˈ", "ˌ")
            parts.append(result)
        return ("".join(parts) or None), None
    except Exception as exc:
        return None, str(exc)


def acronym_ipa(word):
    """IPA for reading `word` one letter at a time, suitable for the lexicon.

    Resolves the spelled-out form through the same G2P Kokoro uses, so what
    gets stored is real phonemes ("ˌApˌiˈI") rather than the literal text
    "A.P.I.", which would otherwise be spoken with the periods in it.
    """
    try:
        from misaki import en as misaki_en
    except ImportError:
        return None
    try:
        g2p = misaki_en.G2P(trf=False, british=False)
        phonemes, _ = g2p(spell_out(word))
        phonemes = (phonemes or "").strip().rstrip(".")
        return phonemes or None
    except Exception:
        return None


def scan_pronunciation(text, overrides=None):
    """Run Kokoro's real G2P lookup over every distinct word in the text.

    Returns a dict with:
        unknown   - words with no dictionary entry, falling to espeak-ng
        acronyms  - all-caps tokens, whether or not they're "unknown"
        checked   - total distinct words examined
        error     - set instead of the above if Kokoro/misaki isn't installed
    """
    try:
        from misaki import en as misaki_en
    except ImportError:
        return {"error": "Kokoro is not installed, so its dictionary can't "
                         "be checked. This scan only applies to Kokoro."}

    overrides = {k: v for k, v in (overrides or {}).items()
                if not k.endswith("__respelling")}
    g2p = misaki_en.G2P(trf=False, british=False)
    for word, phonemes in overrides.items():
        g2p.lexicon.golds[word] = phonemes

    seen, unknown, acronyms = set(), [], []
    for match in WORD_PATTERN.finditer(text):
        word = match.group(0)
        key = word.lower()
        if key in seen or key in _SKIP_SHORT or len(word) < 2:
            continue
        seen.add(key)

        if _looks_like_acronym(word):
            acronyms.append(word)
            # An acronym can also be a genuinely unknown word; still worth
            # a dictionary check even though the fix offered differs.

        if key in overrides:
            continue  # already fixed by the user

        try:
            phonemes, _ = g2p(word)
        except Exception:
            continue  # scanner-only failure; don't block narration over it
        if phonemes in ("", "❓"):
            unknown.append(word)

    return {
        "checked": len(seen),
        "unknown": sorted(set(unknown), key=str.lower),
        "acronyms": sorted(set(acronyms), key=str.lower),
    }


def _gold_to_text(value):
    """Kokoro's lexicon stores most words as a plain phoneme string, but
    words whose pronunciation depends on part of speech map to a dict
    ({"VERB": ..., "DEFAULT": ...}). Flatten to something displayable
    without pretending the distinction doesn't exist."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        preferred = value.get("DEFAULT") or next(iter(value.values()), "")
        others = [k for k in value if k != "DEFAULT"]
        return (f"{preferred}  (varies by role: {', '.join(sorted(others))})"
                if others else str(preferred))
    return str(value)


def current_phonemes(word, overrides=None):
    """What Kokoro would actually say for `word` right now, and where that
    came from. Works for ANY word, not only ones in the dictionary --
    which is the point: a word can be absent from the lexicon and still
    read fine, or present and still read wrong.

    Returns {"word", "phonemes", "source", "error"} where source is
    "override", "dictionary" or "guessed" (espeak-ng fallback).
    """
    try:
        from misaki import en as misaki_en
    except ImportError:
        return {"word": word, "phonemes": None, "source": None,
                "error": "Kokoro/misaki isn't installed here."}
    overrides = {k: v for k, v in (overrides or {}).items()
                if not k.endswith("__respelling")}
    key = (word or "").strip().lower()
    if not key:
        return {"word": word, "phonemes": None, "source": None,
                "error": "No word given."}
    if key in overrides:
        return {"word": word, "phonemes": overrides[key],
                "source": "override", "error": None}
    try:
        g2p = misaki_en.G2P(trf=False, british=False)
        golds = getattr(g2p.lexicon, "golds", {}) or {}
        if key in golds:
            return {"word": word, "phonemes": _gold_to_text(golds[key]),
                   "source": "dictionary", "error": None}
        phonemes, _ = g2p(word)
        if phonemes in ("", "❓", None):
            return {"word": word, "phonemes": None, "source": None,
                   "error": "Kokoro can't pronounce this at all."}
        return {"word": word, "phonemes": phonemes, "source": "guessed",
               "error": None}
    except Exception as exc:
        return {"word": word, "phonemes": None, "source": None,
                "error": str(exc)}


def lookup_words(query, limit=150, overrides=None):
    """Dictionary words matching `query`, with their current phonemes.

    Words starting with the query sort before words merely containing it,
    which is what makes typing feel like a filter rather than a shuffle.
    The list is capped because the lexicon has tens of thousands of
    entries and no one scrolls that far -- the count of matches beyond the
    cap is reported so the cap is visible rather than silent.
    """
    try:
        from misaki import en as misaki_en
    except ImportError:
        return {"matches": [], "total": 0,
                "error": "Kokoro/misaki isn't installed here, so its "
                         "dictionary can't be searched."}
    q = (query or "").strip().lower()
    overrides = {k: v for k, v in (overrides or {}).items()
                if not k.endswith("__respelling")}
    try:
        g2p = misaki_en.G2P(trf=False, british=False)
        golds = getattr(g2p.lexicon, "golds", {}) or {}
    except Exception as exc:
        return {"matches": [], "total": 0, "error": str(exc)}

    words = set(golds)
    words.update(overrides)
    if q:
        starts = sorted(w for w in words if w.startswith(q))
        contains = sorted(w for w in words if q in w and not w.startswith(q))
        hits = starts + contains
    else:
        hits = sorted(words)

    matches = []
    for word in hits[:limit]:
        if word in overrides:
            matches.append({"word": word, "phonemes": overrides[word],
                           "source": "override"})
        else:
            matches.append({"word": word,
                           "phonemes": _gold_to_text(golds.get(word, "")),
                           "source": "dictionary"})
    return {"matches": matches, "total": len(hits), "error": None}


def phonemes_for_words(words, overrides=None):
    """Per-word pronunciation for a list of words, in one pass.

    A sentence-at-a-time version of current_phonemes(). Batched
    deliberately: each call has to reach the environment Kokoro lives in,
    and doing that once per word in a sentence would mean a dozen
    subprocess round-trips to answer one question.
    """
    try:
        from misaki import en as misaki_en
    except ImportError:
        return {"words": [], "error": "Kokoro/misaki isn't installed here."}
    overrides = {k: v for k, v in (overrides or {}).items()
                if not k.endswith("__respelling")}
    try:
        g2p = misaki_en.G2P(trf=False, british=False)
        golds = getattr(g2p.lexicon, "golds", {}) or {}
    except Exception as exc:
        return {"words": [], "error": str(exc)}

    out = []
    for word in words:
        key = (word or "").strip().lower()
        if not key:
            continue
        if key in overrides:
            out.append({"word": word, "phonemes": overrides[key],
                       "source": "override"})
            continue
        if key in golds:
            out.append({"word": word, "phonemes": _gold_to_text(golds[key]),
                       "source": "dictionary"})
            continue
        try:
            phonemes, _ = g2p(word)
        except Exception:
            phonemes = None
        if phonemes in ("", "❓", None):
            out.append({"word": word, "phonemes": None, "source": "unknown"})
        else:
            out.append({"word": word, "phonemes": phonemes,
                       "source": "guessed"})
    return {"words": out, "error": None}


def words_in(text):
    """The distinct words of a sentence, in order, as the pronunciation
    system sees them."""
    seen, out = set(), []
    for match in WORD_PATTERN.finditer(text or ""):
        word = match.group(0)
        if word.lower() in seen:
            continue
        seen.add(word.lower())
        out.append(word)
    return out
