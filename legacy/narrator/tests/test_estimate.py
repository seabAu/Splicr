"""Tests for render time estimation.

The failure worth guarding against is a confidently wrong number. An
estimate of "about 4 hours" that turns out to be twenty minutes is worse
than no estimate, because it changes a decision. So the tests care most
about the cases that would poison the rate: cached chunks costing no time,
generations that raised partway, and one unusual run being allowed to
dominate the remembered history.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from narrator import estimate as E


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class TestFormatDuration(unittest.TestCase):
    def test_seconds(self):
        self.assertEqual(E.format_duration(45), "45 seconds")

    def test_minutes(self):
        self.assertEqual(E.format_duration(600), "10 minutes")

    def test_whole_hours(self):
        self.assertEqual(E.format_duration(7200), "2 hours")
        self.assertEqual(E.format_duration(3600), "1 hour")

    def test_hours_and_minutes(self):
        self.assertEqual(E.format_duration(3600 * 4 + 60 * 10), "4h 10m")

    def test_rounding_up_to_a_whole_hour(self):
        """59.7 minutes must not render as '0h 60m'."""
        self.assertEqual(E.format_duration(3600 + 3599), "2 hours")

    def test_nonsense_is_admitted_not_guessed(self):
        self.assertEqual(E.format_duration(None), "unknown")
        self.assertEqual(E.format_duration(-5), "unknown")
        self.assertEqual(E.format_duration(float("nan")), "unknown")


class TestEstimator(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()

    def _est(self, total=1000):
        return E.Estimator("test-engine", total, clock=self.clock)

    def test_no_estimate_before_anything_is_generated(self):
        est = self._est()
        self.assertIsNone(est.rate)
        self.assertIsNone(est.progress(0))

    def test_rate_from_one_chunk(self):
        est = self._est()
        with est.timing(100):
            self.clock.advance(10.0)
        self.assertAlmostEqual(est.rate, 10.0)

    def test_progress_reports_remaining_work(self):
        est = self._est(total=1000)
        with est.timing(100):
            self.clock.advance(10.0)          # 10 chars/sec
        # 900 characters left at 10/sec = 90 seconds
        self.assertEqual(est.progress(100), "  about 90 seconds to go")

    def test_rate_averages_across_chunks(self):
        est = self._est()
        with est.timing(100):
            self.clock.advance(10.0)
        with est.timing(100):
            self.clock.advance(30.0)
        self.assertAlmostEqual(est.rate, 200 / 40.0)

    def test_cached_chunks_do_not_poison_the_rate(self):
        """The bug this is here to prevent: a resumed render skips most of
        the work, and counting those instants as generation would report a
        rate hundreds of times too fast."""
        est = self._est(total=1000)
        with est.timing(100):
            self.clock.advance(10.0)
        # Three cached chunks: no timing block at all, just progress.
        line = est.progress(400)
        self.assertEqual(line, "  about 60 seconds to go")
        self.assertAlmostEqual(est.rate, 10.0, msg="rate unchanged by cache")

    def test_a_failed_generation_is_not_recorded(self):
        est = self._est()
        try:
            with est.timing(100):
                self.clock.advance(999.0)
                raise RuntimeError("engine blew up")
        except RuntimeError:
            pass
        self.assertIsNone(est.rate, "a crash is not a measurement")

    def test_no_progress_line_once_finished(self):
        est = self._est(total=100)
        with est.timing(100):
            self.clock.advance(10.0)
        self.assertIsNone(est.progress(100))

    def test_zero_length_document(self):
        est = self._est(total=0)
        self.assertIsNone(est.upfront())
        self.assertIsNone(est.progress(0))


class TestRememberedRate(unittest.TestCase):
    def setUp(self):
        from narrator import config
        self._load, self._save = config.load_settings, config.save_settings
        self.store = {}
        E.load_settings = lambda: dict(self.store)
        E.save_settings = self.store.update

    def tearDown(self):
        E.load_settings, E.save_settings = self._load, self._save

    def test_nothing_remembered_yet(self):
        self.assertIsNone(E.remembered_rate("test-engine"))

    def test_remembers_and_reads_back(self):
        E.remember_rate("test-engine", 12.5)
        self.assertAlmostEqual(E.remembered_rate("test-engine"), 12.5)

    def test_median_not_mean_so_one_odd_run_cannot_dominate(self):
        for rate in (10.0, 10.0, 10.0, 1000.0):
            E.remember_rate("test-engine", rate)
        self.assertAlmostEqual(E.remembered_rate("test-engine"), 10.0)

    def test_history_is_capped(self):
        for i in range(20):
            E.remember_rate("test-engine", float(i + 1))
        self.assertEqual(len(self.store["render_rates"]["test-engine"]),
                         E.MAX_HISTORY)

    def test_engines_are_kept_apart(self):
        E.remember_rate("kokoro", 50.0)
        E.remember_rate("qwen3", 2.0)
        self.assertAlmostEqual(E.remembered_rate("kokoro"), 50.0)
        self.assertAlmostEqual(E.remembered_rate("qwen3"), 2.0)

    def test_zero_and_negative_rates_are_ignored(self):
        E.remember_rate("test-engine", 0)
        E.remember_rate("test-engine", -3)
        self.assertIsNone(E.remembered_rate("test-engine"))

    def test_upfront_estimate_uses_history(self):
        E.remember_rate("test-engine", 10.0)
        est = E.Estimator("test-engine", 36000)
        self.assertIn("1 hour", est.upfront())

    def test_upfront_is_silent_without_history(self):
        """Better to say nothing than invent a number."""
        self.assertIsNone(E.Estimator("never-run", 100000).upfront())

    def test_finish_records_the_run(self):
        clock = FakeClock()
        est = E.Estimator("test-engine", 1000, clock=clock)
        with est.timing(100):
            clock.advance(5.0)
        est.finish()
        self.assertAlmostEqual(E.remembered_rate("test-engine"), 20.0)

    def test_finish_records_nothing_for_a_fully_cached_run(self):
        E.Estimator("test-engine", 1000).finish()
        self.assertIsNone(E.remembered_rate("test-engine"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
