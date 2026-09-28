"""How long a render is going to take.

WHY THIS EXISTS. A ten-hour document is a decision, not a button press:
whether to start it before bed, before work, or at all. Without an estimate
the only way to find out is to start it and watch. The information needed is
already there -- how fast this engine ran last time, and how fast it is
running right now -- it was just never written down or shown.

TWO ESTIMATES, NOT ONE.

  * **Before anything renders**, from a rate remembered from previous runs
    on this machine. This is the one that actually informs the decision,
    because it arrives before the commitment. It is also the rougher of the
    two, so it is always phrased as a rough figure.
  * **While rendering**, from the chunks finished so far, which converges
    quickly and corrects for whatever is different today -- a colder GPU, a
    busier machine, a different voice.

WHAT IS DELIBERATELY EXCLUDED. Cached chunks. Resuming a half-finished
render skips most of the work, and counting those instants as "generation"
would report a rate hundreds of times too fast and an estimate of about
nothing. Only chunks actually generated update the rate.

The rate is characters of source text per second of wall clock, which is
crude -- it ignores how phoneme-dense a passage is -- but it is stable
enough over a document of any length, and the alternative (per-phoneme,
which would need the counting pass) buys accuracy nobody is going to notice
on an estimate rendered as "about 4 hours".
"""

import time

from .config import load_settings, save_settings

# Keep some history rather than only the last number, so one unusual run
# (a laptop on battery, a machine that was busy) does not poison the
# estimate for every future render.
MAX_HISTORY = 5


def format_duration(seconds):
    """Seconds -> a phrase a person can act on.

    Deliberately coarse. Reporting "3h 47m 12s" for something with a wide
    error bar implies a precision that is not there, and nobody schedules
    their evening around the twelve seconds.
    """
    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        return "unknown"
    if seconds < 0 or seconds != seconds:            # negative or NaN
        return "unknown"
    # Under two minutes reads better in seconds: "90 seconds" is plainer
    # than "2 minutes", which also overstates it by a third.
    if seconds < 120:
        return f"{int(round(seconds))} seconds"
    minutes = seconds / 60.0
    if minutes < 60:
        return f"{int(round(minutes))} minutes"
    hours = int(minutes // 60)
    rest = int(round(minutes % 60))
    if rest == 60:
        hours, rest = hours + 1, 0
    if rest == 0:
        return f"{hours} hour" + ("s" if hours != 1 else "")
    return f"{hours}h {rest:02d}m"


def load_rates():
    return dict(load_settings().get("render_rates") or {})


def remembered_rate(engine_key):
    """Characters per second of wall clock, from previous runs, or None.

    The median of the remembered runs, not the mean: one aborted or
    interrupted render should not drag the figure around.
    """
    history = load_rates().get(engine_key) or []
    values = sorted(float(v) for v in history if v and float(v) > 0)
    if not values:
        return None
    mid = len(values) // 2
    return (values[mid] if len(values) % 2
            else (values[mid - 1] + values[mid]) / 2.0)


def remember_rate(engine_key, chars_per_second):
    """Record one completed run's rate, keeping the last MAX_HISTORY."""
    if not chars_per_second or chars_per_second <= 0:
        return
    settings = load_settings()
    rates = dict(settings.get("render_rates") or {})
    history = list(rates.get(engine_key) or [])
    history.append(float(chars_per_second))
    rates[engine_key] = history[-MAX_HISTORY:]
    settings["render_rates"] = rates
    save_settings(settings)


class Estimator:
    """Tracks generation speed across a render and reports what is left.

    Usage from an engine's chunk loop:

        est = Estimator("kokoro", total_chars)
        log(est.upfront() or "")
        ...
        with est.timing(len(chunk)):      # only around real generation
            ...generate...
        log(est.progress(chars_done))
    """

    def __init__(self, engine_key, total_chars, clock=time.monotonic):
        self.engine_key = engine_key
        self.total_chars = max(0, int(total_chars or 0))
        self._clock = clock
        self.generated_chars = 0
        self.generated_seconds = 0.0

    # -- before anything has run --

    def upfront(self):
        """A rough estimate from remembered runs, or None if this engine has
        never finished one here. Silence is better than a made-up number."""
        rate = remembered_rate(self.engine_key)
        if not rate or not self.total_chars:
            return None
        return (f"Roughly {format_duration(self.total_chars / rate)} at this "
                f"machine's usual speed for this engine.")

    # -- during the run --

    class _Timing:
        def __init__(self, est, chars):
            self.est, self.chars, self.started = est, chars, None

        def __enter__(self):
            self.started = self.est._clock()
            return self

        def __exit__(self, *exc):
            # Only count a chunk that finished cleanly. A generation that
            # raised took an unrepresentative amount of time and would skew
            # the rate for everything after it.
            if exc[0] is None and self.started is not None:
                self.est.record(self.chars, self.est._clock() - self.started)
            return False

    def timing(self, chars):
        return self._Timing(self, chars)

    def record(self, chars, seconds):
        if chars > 0 and seconds > 0:
            self.generated_chars += chars
            self.generated_seconds += seconds

    @property
    def rate(self):
        """Characters per second so far, or None if nothing was generated
        (everything came from cache)."""
        if self.generated_chars <= 0 or self.generated_seconds <= 0:
            return None
        return self.generated_chars / self.generated_seconds

    def progress(self, chars_done):
        """A line for the log, or None while there is nothing to say."""
        rate = self.rate
        remaining = self.total_chars - max(0, int(chars_done))
        if not rate or remaining <= 0:
            return None
        return f"  about {format_duration(remaining / rate)} to go"

    def finish(self):
        """Remember this run's rate for next time. Only called on a run that
        actually generated something."""
        if self.rate:
            remember_rate(self.engine_key, self.rate)
        return self.rate
