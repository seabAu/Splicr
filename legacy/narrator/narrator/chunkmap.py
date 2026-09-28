"""The chunk map: seeing how a document was divided, and deciding what
voice each part gets.

WHY OVERRIDES ARE FRAGILE, AND WHAT IS DONE ABOUT IT. A per-chunk voice is
stored against a chunk *index*, because that is the only handle a chunk has.
Indices are not stable: change the chunk size, or edit the document, and
chunk 7 becomes a different piece of text while the override still points at
"7". Silently reading the wrong paragraph in the wrong voice is exactly the
sort of bug that survives to publication, because nothing looks wrong -- the
render succeeds and the file plays.

So overrides are stored with a fingerprint of the chunking that produced
them, and `reconcile()` drops them when that fingerprint changes. Losing an
assignment is annoying; applying it to the wrong text is worse, and the
person who set it is the only one who can say where it should have gone.

Nothing here imports tkinter.
"""

import hashlib

# Faint, distinguishable backgrounds. Deliberately low-saturation: this
# highlights a wall of prose that still has to be readable, so the colours
# have to separate adjacent chunks without competing with the text. They
# repeat after twelve, which is fine because only neighbours need to differ.
CHUNK_COLOURS = [
    "#eef4fb", "#f4eef9", "#eef9f1", "#fbf4ee", "#f9eef2", "#eef7f9",
    "#f2f9ee", "#f6eef4", "#eef1f9", "#f9f7ee", "#eff9f6", "#f9eeee",
]
CHUNK_COLOURS_HOVER = [
    "#cfe0f5", "#e2cff2", "#cff2da", "#f5e2cf", "#f2cfd9", "#cfeef5",
    "#dbf2cf", "#eccfe4", "#cfd8f2", "#f2edcf", "#d2f2e7", "#f2cfcf",
]


def colour_for(index, hover=False):
    palette = CHUNK_COLOURS_HOVER if hover else CHUNK_COLOURS
    return palette[index % len(palette)]


def chunking_fingerprint(chunks):
    """Identifies the exact division a set of overrides was made against.

    Uses the chunk texts themselves rather than the settings that produced
    them, so an edit to the document invalidates the overrides just as a
    change of chunk size does -- both move the text out from under the
    indices.
    """
    h = hashlib.sha1()
    h.update(str(len(chunks)).encode())
    for c in chunks:
        h.update(b"\x00")
        h.update((c or "").encode("utf-8", "replace"))
    return h.hexdigest()[:16]


def reconcile(stored, chunks):
    """Return (overrides, dropped) for the current chunking.

    `stored` is whatever was saved: {"fingerprint": str, "voices": {idx: v}}.
    If the fingerprint no longer matches, every override is dropped and
    `dropped` is how many there were, so the caller can say so rather than
    letting them vanish quietly.
    """
    fingerprint = chunking_fingerprint(chunks)
    if not isinstance(stored, dict):
        return {}, 0
    voices = stored.get("voices") or {}
    voices = {int(k): v for k, v in voices.items() if v}
    if stored.get("fingerprint") != fingerprint:
        return {}, len(voices)
    # An override pointing past the end of a shorter document is stale even
    # when the fingerprint somehow matches.
    kept = {i: v for i, v in voices.items() if 0 <= i < len(chunks)}
    return kept, len(voices) - len(kept)


def store(overrides, chunks):
    """The saveable form of a set of overrides."""
    return {"fingerprint": chunking_fingerprint(chunks),
            "voices": {str(i): v for i, v in sorted(overrides.items()) if v}}


def chunk_voices_from(overrides, quote_voice, is_quote, count):
    """Build the per-chunk voice list the engine takes.

    An explicit per-chunk choice wins over the automatic quote voice. Some-
    one who has gone to the trouble of assigning a chunk by hand means it,
    including when they assign a quotation to something other than the quote
    voice.
    """
    out = []
    for i in range(count):
        if i in overrides and overrides[i]:
            out.append(overrides[i])
        elif quote_voice and is_quote and i < len(is_quote) and is_quote[i]:
            out.append(quote_voice)
        else:
            out.append(None)
    return out if any(out) else None


def spread_voices(voices, count):
    """Assign `voices` across `count` chunks in order, in even runs.

    For deliberately drifting the narrator across a document. The voice is
    fixed within a chunk -- that is the unit a generation call is made in --
    so the granularity of the drift is the chunk size: smaller chunks, more
    gradual shift. Returns {} rather than guessing if there is nothing
    sensible to do.
    """
    voices = [v for v in (voices or []) if v]
    if not voices or count <= 0:
        return {}
    if len(voices) == 1:
        return {i: voices[0] for i in range(count)}
    out = {}
    for i in range(count):
        # Spread so the first chunk is the first voice and the last chunk is
        # the last voice, rather than leaving a short remainder at the end.
        pos = i * (len(voices) - 1) / float(count - 1) if count > 1 else 0
        out[i] = voices[int(round(pos))]
    return out
