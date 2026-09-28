"""Custom Kokoro voices, made by blending the stock ones.

WHY THIS WORKS AT ALL. A Kokoro voice is not a model -- it is a small
tensor, one 256-value style vector per possible phoneme-string length,
shipped as a `.pt` file in the Kokoro-82M repo. Averaging two of them gives
a voice between the two, and Kokoro itself already does exactly that:
`KPipeline.load_voice` accepts comma-separated names and returns
`torch.mean(torch.stack(packs), dim=0)`. Verified against kokoro 0.9.4
source, not assumed.

WHAT THIS ADDS ON TOP. Two things the built-in blend cannot do:

  1. **Weights.** Kokoro's own blend is an equal average, so you get exactly
     one point between any set of voices. Most of the useful range is at
     uneven mixes -- mostly one voice with a little of another -- and that
     needs the tensor computed here.
  2. **Permanence.** A blend has to survive being closed, be re-selectable,
     and be identical next week, or a document rendered in two sittings
     changes narrator halfway through. `load_single_voice` accepts any path
     ending in `.pt`, so a blend saved to disk can be passed as the voice
     name and everything downstream -- the render cache key, saved
     settings, the compare-voices feature -- keeps working on a plain
     string with no special cases.

WHERE THIS RUNS. Blending needs torch and the Hugging Face cache, which
live in the Kokoro environment rather than the app's. So the real work is a
`_local` function invoked through the same cross-environment worker that
`list_kokoro_voices` already uses.

WHAT IS NOT CLAIMED. That any given blend sounds good, or that the useful
range is linear. Averaging style vectors is not a physical model of a
voice; a 50/50 mix of two voices is not "halfway between" them in any
guaranteed way. This makes the experiment cheap and repeatable. Judging it
is done by ear.
"""

import json
import os
import re

from .config import DATA_DIR

KOKORO_REPO = "hexgrad/Kokoro-82M"

# Beside the Qwen designed voices, for the same reason they live outside the
# cache: the cache is disposable, a voice you made is not.
CUSTOM_VOICES_DIR = os.path.join(DATA_DIR, "voices", "kokoro")


def slugify_voice(name):
    slug = re.sub(r"[^a-z0-9]+", "_", (name or "").strip().lower()).strip("_")
    return slug or "voice"


def voice_path(name):
    return os.path.join(CUSTOM_VOICES_DIR, slugify_voice(name) + ".pt")


def meta_path(pt_path):
    return os.path.splitext(pt_path)[0] + ".json"


def lang_code_for(voice):
    """Which Kokoro pipeline a voice belongs to: 'b' British, 'a' American.

    The stock rule is a prefix test on the voice name. A saved blend is a
    file path, which matches no prefix, so it would silently fall back to
    American and read a British blend in the wrong pipeline. The blend's
    metadata records what it was made from, so the answer is looked up
    rather than guessed.
    """
    if isinstance(voice, str) and voice.lower().endswith(".pt"):
        try:
            with open(meta_path(voice), encoding="utf-8") as fh:
                return json.load(fh).get("lang_code") or "a"
        except (OSError, ValueError):
            return "a"
    return "b" if str(voice).startswith(("bf_", "bm_")) else "a"


def lang_for_sources(names):
    """A blend is British only if everything in it is.

    Mixing across accents is allowed -- it is one of the more interesting
    things you can do here -- but the pipeline has to be chosen, and the
    American one is the safer default for a mixture since it is what the
    majority of the stock voices use.
    """
    names = [n for n in names if n]
    if names and all(n.startswith(("bf_", "bm_")) for n in names):
        return "b"
    return "a"


def normalise_weights(specs):
    """[(name, weight), ...] -> [(name, share)] summing to 1.

    Weights are relative, so the interface can offer plain 0-100 sliders
    without asking anyone to make them add up. All-zero (or negative)
    weights fall back to an equal mix rather than dividing by zero.
    """
    cleaned = [(n, max(0.0, float(w))) for n, w in specs if n]
    total = sum(w for _, w in cleaned)
    if not cleaned:
        return []
    if total <= 0:
        share = 1.0 / len(cleaned)
        return [(n, share) for n, _ in cleaned]
    return [(n, w / total) for n, w in cleaned]


# --- the blend itself (runs where torch and the HF cache are) --------------


def blend_tensors(packs, weights):
    """Weighted average of voice packs.

    Kept separate from all the downloading and file handling so the one
    piece of arithmetic that decides what the voice *is* can be tested on
    its own, without torch needing to fetch anything.
    """
    import torch
    if not packs:
        raise ValueError("nothing to blend")
    shapes = {tuple(p.shape) for p in packs}
    if len(shapes) > 1:
        raise ValueError(
            f"these voices have different shapes ({sorted(shapes)}) and "
            f"cannot be blended together")
    stacked = torch.stack([p.to(torch.float32) for p in packs])
    w = torch.tensor([float(x) for x in weights], dtype=torch.float32)
    w = w.reshape(-1, *([1] * (stacked.dim() - 1)))
    return (stacked * w).sum(dim=0)


def blend_kokoro_voice_local(specs, out_path, label=None, log=print):
    """Download the named stock voices, blend them by weight, save the .pt.

    Writes a JSON sidecar next to it recording what went in, which is what
    makes a blend reproducible and inspectable later -- and what
    lang_code_for reads.
    """
    import torch
    from huggingface_hub import hf_hub_download

    shares = normalise_weights(specs)
    if not shares:
        raise ValueError("pick at least one voice to blend")

    packs = []
    for name, share in shares:
        log(f"  loading {name} ({share * 100:.0f}%)")
        f = hf_hub_download(repo_id=KOKORO_REPO, filename=f"voices/{name}.pt")
        packs.append(torch.load(f, weights_only=True))

    blended = blend_tensors(packs, [s for _, s in shares])
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    torch.save(blended, out_path)

    meta = {
        "label": label or os.path.splitext(os.path.basename(out_path))[0],
        "sources": [{"voice": n, "weight": round(s, 6)} for n, s in shares],
        "lang_code": lang_for_sources([n for n, _ in shares]),
        "shape": list(blended.shape),
    }
    with open(meta_path(out_path), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)
    log(f"  saved {os.path.basename(out_path)} {tuple(blended.shape)}")
    return out_path


# --- what the app sees ------------------------------------------------------


def list_custom_voices():
    """[(path, label, description)] for every blend saved on this machine."""
    out = []
    if not os.path.isdir(CUSTOM_VOICES_DIR):
        return out
    for fname in sorted(os.listdir(CUSTOM_VOICES_DIR)):
        if not fname.endswith(".pt"):
            continue
        path = os.path.join(CUSTOM_VOICES_DIR, fname)
        label = os.path.splitext(fname)[0]
        description = ""
        try:
            with open(meta_path(path), encoding="utf-8") as fh:
                meta = json.load(fh)
            label = meta.get("label") or label
            description = " + ".join(
                f"{s['voice']} {round(s['weight'] * 100)}%"
                for s in meta.get("sources", []))
        except (OSError, ValueError):
            pass
        out.append((path, label, description))
    return out


def delete_custom_voice(path):
    """Remove a blend and its sidecar. Returns True if anything was removed."""
    removed = False
    for p in (path, meta_path(path)):
        try:
            os.remove(p)
            removed = True
        except OSError:
            pass
    return removed


# --- smooth drift -----------------------------------------------------------
#
# The discrete drift (chunkmap.spread_voices) walks through a handful of
# voices in runs, so the narrator changes in audible steps. This makes the
# change continuous instead: every chunk gets its own blend, interpolated
# along a path through the chosen waypoint voices.
#
# WHY NOT SMALLER CHUNKS INSTEAD. That is the obvious way to get finer grain
# and it does not work. Kokoro generates one piece per paragraph regardless of
# chunk size, so shrinking chunks below a sentence does not subdivide the
# generation -- it just makes each chunk a fragment rendered as a standalone
# utterance, which comes out in citation form (fully stressed, slower,
# falling terminal pitch), and puts a pause at every boundary. The result is
# less intelligible, which is the one thing the effect is supposed to keep.
# So the chunks stay at sentence or paragraph scale and the VOICE becomes
# continuous instead.

DRIFT_STEPS = 20


def interpolation_path(waypoints, count, steps=DRIFT_STEPS):
    """A blend spec for each of `count` chunks, walking through `waypoints`.

    Returns a list of `count` spec lists, each [(voice, weight), ...] ready
    for blend_kokoro_voice. Position 0 is exactly the first waypoint and
    position count-1 is exactly the last.

    `steps` quantises the mix so neighbouring chunks that round to the same
    ratio share one blend file. Without it a 400-chunk document would mean
    400 near-identical tensors on disk and 400 distinct render-cache entries;
    with it there are at most `steps` per waypoint pair, reused. 20 gives 5%
    increments, which is finer than the ear can follow between two
    consecutive sentences.
    """
    waypoints = [w for w in (waypoints or []) if w]
    if not waypoints or count <= 0:
        return []
    if len(waypoints) == 1:
        return [[(waypoints[0], 1.0)]] * count

    out = []
    for i in range(count):
        pos = (i * (len(waypoints) - 1) / float(count - 1)) if count > 1 else 0.0
        seg = min(int(pos), len(waypoints) - 2)
        t = pos - seg
        t = round(t * steps) / float(steps)
        if t <= 0:
            out.append([(waypoints[seg], 1.0)])
        elif t >= 1:
            out.append([(waypoints[seg + 1], 1.0)])
        else:
            out.append([(waypoints[seg], 1.0 - t), (waypoints[seg + 1], t)])
    return out


def blend_slug(specs):
    """A stable, readable filename for a blend, so the same mix always maps
    to the same file and is generated once however many chunks want it."""
    parts = []
    for name, weight in specs:
        base = os.path.basename(str(name))
        if base.endswith(".pt"):
            base = base[:-3]
        parts.append(f"{slugify_voice(base)}{int(round(float(weight) * 100)):03d}")
    return "drift_" + "_".join(parts)


def ensure_drift_blends(paths_by_chunk, blend_fn, log=print):
    """Create every blend a drift needs, once each, and return the per-chunk
    voice list.

    `paths_by_chunk` is what interpolation_path returned. `blend_fn` is
    engines.blend_kokoro_voice, passed in so this stays free of engine
    imports and testable without torch.

    A single-voice position needs no blend at all and is passed through as
    the plain voice name -- cheaper, and it keeps the stock voices
    recognisable in the chunk map rather than turning them into files.
    """
    made, out = {}, []
    for specs in paths_by_chunk:
        if len(specs) == 1:
            out.append(specs[0][0])
            continue
        slug = blend_slug(specs)
        if slug not in made:
            path = os.path.join(CUSTOM_VOICES_DIR, slug + ".pt")
            if not os.path.exists(path):
                log(f"  blending {slug}")
                blend_fn(specs, path, slug, log)
            made[slug] = path
        out.append(made[slug])
    return out
