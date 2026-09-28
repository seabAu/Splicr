"""Tests for custom Kokoro voices.

Hugging Face is unreachable from here, so the real voice packs cannot be
downloaded. What IS tested is everything that decides what the voice becomes
and whether it survives being saved: the weighted average itself, at the
real pack shape; weight normalisation; the language-code lookup that a
saved blend depends on; and the save/load round trip.

What is NOT tested, and cannot be from here: whether any particular blend
sounds like anything worth listening to.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import torch

from narrator import voices as V

# The real shape of a Kokoro voice pack: one 256-value style vector per
# possible phoneme-string length, up to Kokoro's 510-token limit.
PACK_SHAPE = (510, 1, 256)


def _pack(fill):
    return torch.full(PACK_SHAPE, float(fill), dtype=torch.float32)


class TestBlendTensors(unittest.TestCase):
    def test_equal_blend_is_the_mean(self):
        out = V.blend_tensors([_pack(0.0), _pack(1.0)], [0.5, 0.5])
        self.assertEqual(tuple(out.shape), PACK_SHAPE)
        self.assertAlmostEqual(float(out[0, 0, 0]), 0.5, places=6)

    def test_weights_actually_weight(self):
        """The whole reason for not using Kokoro's built-in blend."""
        out = V.blend_tensors([_pack(0.0), _pack(1.0)], [0.9, 0.1])
        self.assertAlmostEqual(float(out[0, 0, 0]), 0.1, places=6)

    def test_single_voice_is_unchanged(self):
        out = V.blend_tensors([_pack(0.42)], [1.0])
        self.assertAlmostEqual(float(out[100, 0, 5]), 0.42, places=6)

    def test_three_way_blend(self):
        out = V.blend_tensors([_pack(0.0), _pack(1.0), _pack(2.0)],
                              [0.2, 0.3, 0.5])
        self.assertAlmostEqual(float(out[0, 0, 0]), 0.0 * 0.2 + 1.0 * 0.3
                               + 2.0 * 0.5, places=6)

    def test_blends_per_position_not_globally(self):
        """Each token length has its own style vector; they must not mix."""
        a, b = _pack(0.0).clone(), _pack(1.0).clone()
        a[7] = 10.0
        out = V.blend_tensors([a, b], [0.5, 0.5])
        self.assertAlmostEqual(float(out[7, 0, 0]), 5.5, places=6)
        self.assertAlmostEqual(float(out[8, 0, 0]), 0.5, places=6)

    def test_mismatched_shapes_are_refused_clearly(self):
        odd = torch.zeros((510, 1, 128), dtype=torch.float32)
        with self.assertRaises(ValueError) as ctx:
            V.blend_tensors([_pack(0.0), odd], [0.5, 0.5])
        self.assertIn("different shapes", str(ctx.exception))

    def test_empty_is_refused(self):
        with self.assertRaises(ValueError):
            V.blend_tensors([], [])

    def test_output_is_float32(self):
        out = V.blend_tensors([_pack(0.0), _pack(1.0)], [0.5, 0.5])
        self.assertEqual(out.dtype, torch.float32)


class TestNormaliseWeights(unittest.TestCase):
    def test_shares_sum_to_one(self):
        got = V.normalise_weights([("a", 30), ("b", 70)])
        self.assertAlmostEqual(sum(w for _, w in got), 1.0, places=9)
        self.assertAlmostEqual(dict(got)["b"], 0.7, places=9)

    def test_arbitrary_scales_work(self):
        """Sliders can be 0-100 without anyone making them add up."""
        self.assertEqual(V.normalise_weights([("a", 1), ("b", 1)]),
                         V.normalise_weights([("a", 50), ("b", 50)]))

    def test_all_zero_falls_back_to_equal(self):
        got = dict(V.normalise_weights([("a", 0), ("b", 0)]))
        self.assertAlmostEqual(got["a"], 0.5, places=9)

    def test_negative_weights_are_clamped(self):
        got = dict(V.normalise_weights([("a", -5), ("b", 10)]))
        self.assertAlmostEqual(got["b"], 1.0, places=9)

    def test_blank_names_dropped(self):
        self.assertEqual(V.normalise_weights([("", 5), ("a", 5)]),
                         [("a", 1.0)])

    def test_empty(self):
        self.assertEqual(V.normalise_weights([]), [])


class TestLanguageCode(unittest.TestCase):
    def test_stock_prefixes(self):
        self.assertEqual(V.lang_code_for("bf_emma"), "b")
        self.assertEqual(V.lang_code_for("am_michael"), "a")

    def test_all_british_sources_make_a_british_blend(self):
        self.assertEqual(V.lang_for_sources(["bf_emma", "bm_george"]), "b")

    def test_mixed_accents_default_to_american(self):
        self.assertEqual(V.lang_for_sources(["bf_emma", "af_heart"]), "a")

    def test_saved_blend_reads_its_sidecar(self):
        d = tempfile.mkdtemp()
        try:
            pt = os.path.join(d, "mine.pt")
            open(pt, "wb").close()
            with open(V.meta_path(pt), "w") as fh:
                json.dump({"lang_code": "b"}, fh)
            self.assertEqual(V.lang_code_for(pt), "b")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_missing_sidecar_falls_back_safely(self):
        """A blend without metadata must not crash a render."""
        d = tempfile.mkdtemp()
        try:
            pt = os.path.join(d, "orphan.pt")
            open(pt, "wb").close()
            self.assertEqual(V.lang_code_for(pt), "a")
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestSaveAndList(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self._saved = V.CUSTOM_VOICES_DIR
        V.CUSTOM_VOICES_DIR = self.dir

    def tearDown(self):
        V.CUSTOM_VOICES_DIR = self._saved
        shutil.rmtree(self.dir, ignore_errors=True)

    def _make(self, name, sources):
        """Save a blend the way blend_kokoro_voice_local would, minus the
        download it cannot do here."""
        path = os.path.join(self.dir, V.slugify_voice(name) + ".pt")
        shares = V.normalise_weights(sources)
        blended = V.blend_tensors([_pack(i) for i in range(len(shares))],
                                  [s for _, s in shares])
        torch.save(blended, path)
        with open(V.meta_path(path), "w") as fh:
            json.dump({"label": name,
                       "sources": [{"voice": n, "weight": s}
                                   for n, s in shares],
                       "lang_code": V.lang_for_sources(
                           [n for n, _ in shares]),
                       "shape": list(blended.shape)}, fh)
        return path

    def test_round_trip_preserves_the_tensor(self):
        path = self._make("My Narrator", [("af_heart", 70), ("am_adam", 30)])
        reloaded = torch.load(path, weights_only=True)
        self.assertEqual(tuple(reloaded.shape), PACK_SHAPE)
        # 0.0 * 0.7 + 1.0 * 0.3
        self.assertAlmostEqual(float(reloaded[0, 0, 0]), 0.3, places=6)

    def test_listing_describes_the_mix(self):
        self._make("My Narrator", [("af_heart", 70), ("am_adam", 30)])
        got = V.list_custom_voices()
        self.assertEqual(len(got), 1)
        path, label, description = got[0]
        self.assertEqual(label, "My Narrator")
        self.assertIn("af_heart 70%", description)
        self.assertIn("am_adam 30%", description)

    def test_listing_survives_a_broken_sidecar(self):
        path = self._make("Fine", [("af_heart", 100)])
        with open(V.meta_path(path), "w") as fh:
            fh.write("{not json")
        got = V.list_custom_voices()
        self.assertEqual(len(got), 1, "a bad sidecar must not hide the voice")

    def test_empty_directory(self):
        self.assertEqual(V.list_custom_voices(), [])

    def test_delete_removes_both_files(self):
        path = self._make("Gone", [("af_heart", 100)])
        self.assertTrue(V.delete_custom_voice(path))
        self.assertFalse(os.path.exists(path))
        self.assertFalse(os.path.exists(V.meta_path(path)))
        self.assertEqual(V.list_custom_voices(), [])

    def test_slugify(self):
        self.assertEqual(V.slugify_voice("My Narrator!"), "my_narrator")
        self.assertEqual(V.slugify_voice("  "), "voice")


if __name__ == "__main__":
    unittest.main(verbosity=2)
