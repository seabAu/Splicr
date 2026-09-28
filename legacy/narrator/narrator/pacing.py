"""How long the silences are, where they go, and keeping the level steady
across them.

WHY THIS EXISTS. Before this module, a pause was decided by whichever
engine happened to be rendering and by wherever the chunker happened to
split:

  * Kokoro butted its sentences together with no silence at all, then put
    0.35s between chunks.
  * Qwen3 put 0.25s between its 250-character sentence groups, and the
    same 0.35s between chunks.

So the length of a pause did not depend on the writing. The same paragraph
break was a third of a second long if a chunk boundary happened to land on
it and had no silence at all if it did not; a run-of-the-mill sentence
break in the middle of a paragraph was suddenly a third of a second long
once every twenty thousand characters, wherever Kokoro's chunk limit fell.
That is audible, and it is what "weird chunk boundary consistency" sounds
like: not a change of voice, but a rhythm that stumbles at arbitrary
points, in places the text gives no reason to stumble.

THE RULE HERE. The pause between two pieces of speech is decided by the
text between them and by nothing else. Two sentences inside one paragraph
get `sentence_gap`. A paragraph break gets `paragraph_gap`. A chunk
boundary is not a third category -- it is whichever of those two applies
at that point in the document. Joining two chunks then sounds exactly like
joining two sentences, because that is all it is.

WHAT THIS CANNOT DO. Level matching below evens out how *loud* successive
generations are. It does not make two generations sound like the same
performance. On Kokoro that distinction barely matters: the model is
deterministic, so timbre is already identical everywhere and only loudness
and rhythm can vary. On Qwen3 it matters a lot -- energy and pace are
sampled afresh for every group, so two neighbouring groups can differ in
delivery no matter how carefully their levels are matched. Lowering the
sampling temperature (see engines.QWEN_SAMPLING) narrows that; nothing
here closes it.

Nothing in this module imports tkinter, torch, or any engine.
"""

import numpy as np

from .config import load_settings

# Defaults, in seconds. sentence_gap is deliberately small but not zero:
# Kokoro's own sentence renderings already end with a little natural decay,
# so a long pause on top of that sounds hesitant, while literally zero
# (the old Kokoro behaviour) runs sentences together.
DEFAULT_PACING = {
    "sentence_gap": 0.12,
    "paragraph_gap": 0.45,
    # Even out loudness across generation boundaries. See match_levels.
    "match_levels": True,
    "match_levels_db": 3.0,
}

PARAGRAPH, SENTENCE = "paragraph", "sentence"


def pacing_settings():
    """DEFAULT_PACING with any user overrides from narrator_settings.json
    ("pacing": {...}) applied. Unknown keys are dropped and out-of-range
    values are clamped, so a typo or a wild number in the settings file
    cannot put a ten-second hole in the middle of a narration."""
    user = (load_settings().get("pacing") or {})
    out = dict(DEFAULT_PACING)
    for key in ("sentence_gap", "paragraph_gap"):
        if key in user:
            try:
                out[key] = max(0.0, min(3.0, float(user[key])))
            except (TypeError, ValueError):
                pass
    if "match_levels" in user:
        out["match_levels"] = bool(user["match_levels"])
    if "match_levels_db" in user:
        try:
            out["match_levels_db"] = max(0.0, min(12.0,
                                                  float(user["match_levels_db"])))
        except (TypeError, ValueError):
            pass
    return out


def pacing_fingerprint():
    """A short string that changes whenever a setting here would change the
    audio, for mixing into the render cache key.

    This is not optional bookkeeping. The silences inside a chunk are
    written into that chunk's WAV file, so a cached chunk carries the
    pacing it was rendered with. Without this in the key, shortening the
    paragraph pause would appear to do nothing on any document you had
    already rendered -- the old chunks would simply be reused -- and the
    only clue would be that the setting seemed broken. The cost is real and
    worth stating plainly: changing pacing means re-rendering, so it is
    worth settling before starting an hour-long document.
    """
    p = pacing_settings()
    return ("|pacing:{sentence_gap:.3f}:{paragraph_gap:.3f}:"
            "{match_levels}:{match_levels_db:.2f}").format(**p)


def save_pacing(pacing):
    """Persist the pacing block, leaving every other setting alone."""
    from .config import save_settings
    s = load_settings()
    s["pacing"] = {k: pacing[k] for k in DEFAULT_PACING if k in pacing}
    save_settings(s)


# --- deciding the gaps -----------------------------------------------------


def gap_for(kind, pacing=None):
    p = pacing or pacing_settings()
    return float(p["paragraph_gap"] if kind == PARAGRAPH
                 else p["sentence_gap"])


def gaps_for(kinds, pacing=None):
    """[PARAGRAPH, SENTENCE, ...] -> [0.45, 0.12, ...]"""
    p = pacing or pacing_settings()
    return [gap_for(k, p) for k in kinds]


def kinds_from_indices(indices):
    """Boundary kinds from a list of paragraph numbers, one per piece.

    Kokoro hands back a `text_index` with every piece telling us which of
    the paragraphs we passed in produced it, so membership is known exactly
    rather than recovered by matching strings back to the source. A change
    of index between two consecutive pieces is a paragraph break; no change
    is an ordinary sentence break.
    """
    return [PARAGRAPH if b != a else SENTENCE
            for a, b in zip(indices, indices[1:])]


def normalise_gaps(gaps, n_boundaries, fallback=0.0):
    """Coerce whatever a caller passed -- a single number (the old
    interface), a list, or None -- into exactly `n_boundaries` gap values,
    so every joiner can accept both shapes without branching."""
    if n_boundaries <= 0:
        return []
    if gaps is None:
        return [float(fallback)] * n_boundaries
    if isinstance(gaps, (int, float)):
        return [float(gaps)] * n_boundaries
    out = [float(g) for g in gaps][:n_boundaries]
    while len(out) < n_boundaries:
        out.append(float(fallback))
    return out


# --- keeping the level steady ----------------------------------------------


def _rms(x):
    x = np.asarray(x, dtype=np.float32).reshape(-1)
    return float(np.sqrt(np.mean(np.square(x)))) if len(x) else 0.0


def match_levels(arrays, max_db=3.0, floor=1e-5):
    """Nudge each piece's loudness toward the median of all of them, by at
    most `max_db` decibels, and return the adjusted copies.

    WHY THE MEDIAN, AND WHY A CAP. Full normalisation would make every
    piece exactly equal, which also flattens the loudness differences the
    writing actually calls for -- a quiet aside and an emphatic sentence
    would come out the same size. What we want to remove is the artefact:
    one generation landing systematically louder than its neighbours for no
    reason in the text. The median is used rather than the mean because a
    single near-silent or clipped piece would drag a mean around; capping
    the correction at a few dB means a genuinely quiet passage stays
    quieter than its neighbours, just not conspicuously so.

    Pieces below `floor` (silence, or a generation that failed) are left
    strictly alone: boosting near-silence only raises noise.
    """
    arrays = [np.asarray(a, dtype=np.float32).reshape(-1) for a in arrays]
    levels = [_rms(a) for a in arrays]
    speaking = [l for l in levels if l > floor]
    if len(speaking) < 2:
        return arrays
    target = float(np.median(speaking))
    cap = 10 ** (float(max_db) / 20)
    out = []
    for a, level in zip(arrays, levels):
        if level <= floor:
            out.append(a)
            continue
        gain = min(cap, max(1 / cap, target / level))
        adjusted = a * np.float32(gain)
        peak = float(np.abs(adjusted).max()) if len(adjusted) else 0.0
        if peak > 1.0:                    # never clip in the name of matching
            adjusted = adjusted / np.float32(peak)
        out.append(adjusted.astype(np.float32))
    return out
