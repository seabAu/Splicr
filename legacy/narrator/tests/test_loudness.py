"""Tests for loudness normalisation.

Unlike most of this suite these run real ffmpeg, because the thing worth
proving is not that the right flags were assembled but that audio put
through them comes out at the requested loudness. A signal is generated at a
known level, normalised, and then measured with an independent filter
(ebur128 rather than loudnorm's own report).
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from narrator.audio import (measure_loudness, loudness_filter,
                            transcode_audio, DEFAULT_LOUDNESS_LUFS)

WAV = "WAV (uncompressed)"
HAVE_FFMPEG = shutil.which("ffmpeg") is not None


def _measure_lufs(path):
    """Integrated loudness, via ebur128 -- deliberately not loudnorm, so the
    check does not depend on the same code path that did the work."""
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", path,
         "-af", "ebur128=framelog=quiet", "-f", "null", "-"],
        capture_output=True, text=True)
    for line in reversed(proc.stderr.splitlines()):
        if "I:" in line and "LUFS" in line:
            return float(line.split("I:")[1].split("LUFS")[0])
    return None


class TestLoudnessFilter(unittest.TestCase):
    def test_single_pass_when_unmeasured(self):
        f = loudness_filter(-16.0, None)
        self.assertIn("loudnorm=I=-16.0", f)
        self.assertNotIn("measured_I", f)

    def test_two_pass_uses_the_measurement(self):
        f = loudness_filter(-16.0, {"input_i": "-30.1", "input_tp": "-3.2",
                                    "input_lra": "6.5",
                                    "input_thresh": "-40.2",
                                    "target_offset": "0.3"})
        self.assertIn("measured_I=-30.1", f)
        self.assertIn("linear=true", f)

    def test_infinite_measurements_are_replaced(self):
        """Silence makes loudnorm report -inf, which ffmpeg won't take back."""
        f = loudness_filter(-16.0, {"input_i": "-inf", "input_tp": "-inf",
                                    "input_lra": "0.0",
                                    "input_thresh": "-inf",
                                    "target_offset": "0.0"})
        self.assertNotIn("inf", f)

    def test_target_is_respected(self):
        self.assertIn("I=-14.0", loudness_filter(-14.0, None))


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg not available")
class TestLoudnessRoundTrip(unittest.TestCase):
    """Generate, normalise, measure independently."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def _make(self, name, volume, seconds=15):
        path = os.path.join(self.dir, name)
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
             "-i", f"anoisesrc=d={seconds}:c=pink:r=44100",
             "-af", f"volume={volume}", "-c:a", "pcm_s16le", path],
            check=True)
        return path

    def _normalised(self, src, target=DEFAULT_LOUDNESS_LUFS):
        out = os.path.join(self.dir, "out_" + os.path.basename(src))
        result = transcode_audio(src, out, WAV, 100, 44100, 16,
                                 lambda *_: None, loudness=target)
        self.assertIsNotNone(result, "transcode should succeed")
        return out

    def test_quiet_source_is_brought_up_to_target(self):
        src = self._make("quiet.wav", 0.05)
        self.assertLess(_measure_lufs(src), -30.0, "source should be quiet")
        got = _measure_lufs(self._normalised(src))
        self.assertAlmostEqual(got, DEFAULT_LOUDNESS_LUFS, delta=1.0)

    def test_loud_source_is_brought_down_to_target(self):
        src = self._make("loud.wav", 0.9)
        got = _measure_lufs(self._normalised(src))
        self.assertAlmostEqual(got, DEFAULT_LOUDNESS_LUFS, delta=1.0)

    def test_two_sources_end_up_matching_each_other(self):
        """The actual goal: episode to episode consistency."""
        a = _measure_lufs(self._normalised(self._make("a.wav", 0.05)))
        b = _measure_lufs(self._normalised(self._make("b.wav", 0.9)))
        self.assertLess(abs(a - b), 1.0,
                        f"episodes should match each other ({a} vs {b})")

    def test_a_different_target_is_honoured(self):
        src = self._make("t.wav", 0.3)
        got = _measure_lufs(self._normalised(src, target=-14.0))
        self.assertAlmostEqual(got, -14.0, delta=1.0)

    def test_no_target_leaves_level_alone(self):
        src = self._make("untouched.wav", 0.05)
        out = os.path.join(self.dir, "untouched_out.wav")
        transcode_audio(src, out, WAV, 100, 44100, 16, lambda *_: None,
                        loudness=None)
        self.assertAlmostEqual(_measure_lufs(src), _measure_lufs(out),
                               delta=0.5)

    def test_measurement_parses(self):
        src = self._make("m.wav", 0.4)
        measured = measure_loudness(src, -16.0, lambda *_: None)
        self.assertIsNotNone(measured)
        for key in ("input_i", "input_tp", "input_lra", "input_thresh",
                    "target_offset"):
            self.assertIn(key, measured)

    def test_silence_does_not_crash_the_pipeline(self):
        """A failed or empty render must not take the export down with it."""
        path = os.path.join(self.dir, "silent.wav")
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
             "-i", "anullsrc=r=44100:cl=mono", "-t", "5",
             "-c:a", "pcm_s16le", path], check=True)
        out = self._normalised(path)
        self.assertTrue(os.path.exists(out))


if __name__ == "__main__":
    unittest.main(verbosity=2)
