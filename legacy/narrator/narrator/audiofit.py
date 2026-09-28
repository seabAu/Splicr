"""Fitting audio output into a size budget.

WHY THIS IS ITS OWN MODULE. The immediate cause was Reactor's AudioWaveform
fuse refusing anything from 200 MB up, but that limit is not special. Video
tools, upload forms, embedded players and web hosts all have ceilings, they
are all arbitrary, and none of them are worth re-deriving arithmetic for by
hand at the point of use. What a person actually has is a number they must
stay under and a preference about what to give up to get there.

There are exactly two things you can give up, and they trade against each
other:

  * FIDELITY -- lower the sample rate or bit depth, keep one file. The audio
    gets worse; nothing about the workflow changes.
  * WHOLENESS -- keep the quality, cut the file into pieces. The audio is
    untouched; now there are six files to place on a timeline instead of one.

Which is right depends entirely on what the file is for, and the tool cannot
know that. A waveform display can take a savage rate cut and look identical,
so reducing is obviously right. Audio someone will actually listen to should
be split instead. So this module PLANS -- it works out what each choice would
cost and says so in numbers -- and leaves the choosing to the person.

Everything here is arithmetic on durations and rates. No ffmpeg, no files,
no imports from the rest of the app, so the planning can be tested exactly
and the execution kept separate.
"""

import math

# Standard rates only. An odd sample rate computed to fit exactly is one more
# thing for a fragile parser to dislike, and the saving between 11025 Hz and
# a computed 10800 Hz is not worth finding that out the hard way.
STANDARD_RATES = [48000, 44100, 32000, 22050, 16000, 11025, 8000, 4000, 2000]

# 8-bit PCM halves the size again but is audibly noisy -- fine for a waveform
# display, poor for anything anyone listens to. Offered, never chosen
# automatically.
STANDARD_DEPTHS = [16, 8]


def bytes_per_second(rate, bit_depth=16, channels=1):
    return int(rate) * (max(1, int(bit_depth)) // 8) * max(1, int(channels))


def predicted_mb(duration, rate, bit_depth=16, channels=1):
    return (float(duration) * bytes_per_second(rate, bit_depth, channels)
            / (1024 * 1024))


def best_rate_under(duration, target_mb, bit_depth=16, channels=1,
                    min_rate=None):
    """Highest standard rate whose whole-file size stays within budget.

    Returns (rate, mb) or (None, mb_at_lowest_allowed) when nothing fits --
    so a caller can report the shortfall as a number instead of a shrug.
    """
    rates = [r for r in STANDARD_RATES
             if min_rate is None or r >= min_rate]
    for rate in rates:
        mb = predicted_mb(duration, rate, bit_depth, channels)
        if mb <= target_mb:
            return rate, mb
    floor = rates[-1] if rates else STANDARD_RATES[-1]
    return None, predicted_mb(duration, floor, bit_depth, channels)


def pieces_needed(duration, target_mb, rate, bit_depth=16, channels=1):
    """How many equal pieces keep every piece within budget."""
    total = predicted_mb(duration, rate, bit_depth, channels)
    if total <= target_mb or target_mb <= 0:
        return 1
    return max(1, int(math.ceil(total / float(target_mb))))


def plan_fit(duration, target_mb, strategy="auto", source_rate=48000,
             bit_depth=16, channels=1, min_rate=8000):
    """Work out how to get `duration` seconds of audio under `target_mb`.

    `strategy`:
      "keep"    -- do not touch quality; split as many times as it takes.
      "reduce"  -- do not split; lower the rate until it fits. May fail.
      "auto"    -- lower the rate as far as `min_rate`, and split only if
                   that is still not enough.

    `min_rate` is the floor for automatic reduction. 8 kHz by default: below
    that speech stops being comfortably intelligible, and a plan that
    silently produced 2 kHz audio because the arithmetic allowed it would be
    obeying the letter of the request and not its point.

    Returns a dict with rate, bit_depth, pieces, piece_seconds, piece_mb,
    total_mb and a plain-language `note`. Never raises; a duration of zero
    yields a one-piece plan at the source rate.
    """
    duration = max(0.0, float(duration))
    target_mb = max(0.001, float(target_mb))

    if duration <= 0:
        return {"rate": source_rate, "bit_depth": bit_depth, "pieces": 1,
                "piece_seconds": 0.0, "piece_mb": 0.0, "total_mb": 0.0,
                "fits": True, "note": "Nothing to do -- the file is empty."}

    def build(rate, pieces, note):
        piece_seconds = duration / pieces
        return {
            "rate": rate, "bit_depth": bit_depth, "pieces": pieces,
            "piece_seconds": piece_seconds,
            "piece_mb": predicted_mb(piece_seconds, rate, bit_depth,
                                     channels),
            "total_mb": predicted_mb(duration, rate, bit_depth, channels),
            "fits": True, "note": note,
        }

    if strategy == "keep":
        pieces = pieces_needed(duration, target_mb, source_rate, bit_depth,
                               channels)
        if pieces == 1:
            return build(source_rate, 1,
                         "Already under the limit -- nothing to change.")
        return build(source_rate, pieces,
                     f"Full quality kept; {pieces} pieces of about "
                     f"{duration / pieces / 60:.0f} minutes each.")

    if strategy == "reduce":
        rate, mb = best_rate_under(duration, target_mb, bit_depth, channels)
        if rate is None:
            return {"rate": STANDARD_RATES[-1], "bit_depth": bit_depth,
                    "pieces": 1, "piece_seconds": duration,
                    "piece_mb": mb, "total_mb": mb, "fits": False,
                    "note": f"Even {STANDARD_RATES[-1]:,} Hz would be "
                            f"{mb:,.0f} MB. This length cannot be fitted in "
                            f"one file -- it has to be split."}
        if rate >= source_rate:
            return build(source_rate, 1,
                         "Already under the limit -- nothing to change.")
        return build(rate, 1,
                     f"One file at {rate:,} Hz instead of "
                     f"{source_rate:,} Hz.")

    # auto: reduce as far as the floor, then split if still needed.
    rate, mb = best_rate_under(duration, target_mb, bit_depth, channels,
                               min_rate=min_rate)
    if rate is not None:
        if rate >= source_rate:
            return build(source_rate, 1,
                         "Already under the limit -- nothing to change.")
        return build(rate, 1,
                     f"One file at {rate:,} Hz instead of "
                     f"{source_rate:,} Hz.")
    rate = min_rate
    pieces = pieces_needed(duration, target_mb, rate, bit_depth, channels)
    return build(rate, pieces,
                 f"Reduced to {rate:,} Hz and split into {pieces} pieces -- "
                 f"even at {rate:,} Hz one file would be too big.")


def describe_plan(plan, target_mb):
    """One line a person can act on."""
    if not plan.get("fits", True):
        return plan["note"]
    if plan["pieces"] == 1:
        return (f"{plan['total_mb']:,.0f} MB in one file at "
                f"{plan['rate']:,} Hz (limit {target_mb:,.0f} MB).")
    return (f"{plan['pieces']} pieces of about {plan['piece_mb']:,.0f} MB "
            f"each ({plan['piece_seconds'] / 60:.1f} min) at "
            f"{plan['rate']:,} Hz. Total {plan['total_mb']:,.0f} MB.")
