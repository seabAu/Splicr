"""Tests for the chunk map's voice overrides.

The one that matters is test_overrides_are_dropped_when_the_text_moves. An
override points at a chunk *index*; if the document or the chunk size
changes, that index refers to different text. Applying it anyway would read
the wrong paragraph in the wrong voice, and nothing about the render would
look wrong -- it would succeed and play. Dropping the assignment is the
lesser harm, and only the person who made it can say where it should go.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from narrator import chunkmap as C


class TestColours(unittest.TestCase):
    def test_neighbours_differ(self):
        for i in range(len(C.CHUNK_COLOURS) * 2):
            self.assertNotEqual(C.colour_for(i), C.colour_for(i + 1))

    def test_hover_differs_from_resting(self):
        self.assertNotEqual(C.colour_for(3), C.colour_for(3, hover=True))

    def test_wraps_without_error(self):
        self.assertTrue(C.colour_for(1000).startswith("#"))


class TestFingerprint(unittest.TestCase):
    def test_same_chunks_same_fingerprint(self):
        self.assertEqual(C.chunking_fingerprint(["a", "b"]),
                         C.chunking_fingerprint(["a", "b"]))

    def test_edited_text_changes_it(self):
        self.assertNotEqual(C.chunking_fingerprint(["a", "b"]),
                            C.chunking_fingerprint(["a", "b!"]))

    def test_different_split_of_the_same_text_changes_it(self):
        """Re-chunking the same document must invalidate overrides."""
        self.assertNotEqual(C.chunking_fingerprint(["ab"]),
                            C.chunking_fingerprint(["a", "b"]))

    def test_boundary_position_matters(self):
        self.assertNotEqual(C.chunking_fingerprint(["ab", "c"]),
                            C.chunking_fingerprint(["a", "bc"]))


class TestReconcile(unittest.TestCase):
    def test_overrides_survive_an_unchanged_chunking(self):
        chunks = ["one", "two", "three"]
        stored = C.store({0: "af_heart", 2: "bm_george"}, chunks)
        kept, dropped = C.reconcile(stored, chunks)
        self.assertEqual(kept, {0: "af_heart", 2: "bm_george"})
        self.assertEqual(dropped, 0)

    def test_overrides_are_dropped_when_the_text_moves(self):
        stored = C.store({0: "af_heart", 1: "bm_george"}, ["one", "two"])
        kept, dropped = C.reconcile(stored, ["one", "two", "three"])
        self.assertEqual(kept, {})
        self.assertEqual(dropped, 2, "the caller must be able to say so")

    def test_stale_index_past_the_end_is_dropped(self):
        chunks = ["one", "two"]
        stored = C.store({0: "af_heart", 5: "bm_george"}, chunks)
        # Force the fingerprint to match while an index is out of range.
        stored["voices"]["5"] = "bm_george"
        kept, dropped = C.reconcile(stored, chunks)
        self.assertEqual(set(kept), {0})
        self.assertEqual(dropped, 1)

    def test_nothing_stored(self):
        self.assertEqual(C.reconcile(None, ["a"]), ({}, 0))
        self.assertEqual(C.reconcile({}, ["a"]), ({}, 0))

    def test_round_trip_through_string_keys(self):
        """Settings are JSON, so integer keys come back as strings."""
        chunks = ["one", "two"]
        import json
        stored = json.loads(json.dumps(C.store({1: "af_heart"}, chunks)))
        kept, _ = C.reconcile(stored, chunks)
        self.assertEqual(kept, {1: "af_heart"})

    def test_blank_voices_are_not_kept(self):
        chunks = ["one", "two"]
        kept, _ = C.reconcile(C.store({0: "", 1: "af_heart"}, chunks), chunks)
        self.assertEqual(kept, {1: "af_heart"})


class TestChunkVoices(unittest.TestCase):
    def test_none_when_nothing_is_set(self):
        self.assertIsNone(C.chunk_voices_from({}, None, [False] * 3, 3))

    def test_quote_voice_applies_to_quoted_chunks(self):
        got = C.chunk_voices_from({}, "bm_george", [False, True, False], 3)
        self.assertEqual(got, [None, "bm_george", None])

    def test_explicit_override_beats_the_quote_voice(self):
        """Assigning a chunk by hand means it, quotation or not."""
        got = C.chunk_voices_from({1: "af_bella"}, "bm_george",
                                  [False, True, False], 3)
        self.assertEqual(got, [None, "af_bella", None])

    def test_override_on_a_plain_chunk(self):
        got = C.chunk_voices_from({2: "af_bella"}, None, [False] * 3, 3)
        self.assertEqual(got, [None, None, "af_bella"])

    def test_length_always_matches_the_chunk_count(self):
        got = C.chunk_voices_from({0: "x"}, None, [], 5)
        self.assertEqual(len(got), 5)


class TestSpreadVoices(unittest.TestCase):
    def test_first_and_last_are_the_ends_of_the_list(self):
        got = C.spread_voices(["a", "b", "c"], 9)
        self.assertEqual(got[0], "a")
        self.assertEqual(got[8], "c")

    def test_every_chunk_gets_a_voice(self):
        got = C.spread_voices(["a", "b"], 7)
        self.assertEqual(len(got), 7)
        self.assertTrue(all(v in ("a", "b") for v in got.values()))

    def test_the_shift_is_monotonic(self):
        """A drift should move through the voices in order, not jump about."""
        voices = ["a", "b", "c", "d"]
        got = C.spread_voices(voices, 20)
        seen = [voices.index(got[i]) for i in range(20)]
        self.assertEqual(seen, sorted(seen))

    def test_single_voice_fills_everything(self):
        self.assertEqual(set(C.spread_voices(["a"], 4).values()), {"a"})

    def test_more_voices_than_chunks(self):
        got = C.spread_voices(["a", "b", "c", "d", "e"], 2)
        self.assertEqual(len(got), 2)
        self.assertEqual(got[0], "a")
        self.assertEqual(got[1], "e")

    def test_nothing_to_do(self):
        self.assertEqual(C.spread_voices([], 5), {})
        self.assertEqual(C.spread_voices(["a"], 0), {})

    def test_blank_entries_ignored(self):
        self.assertEqual(set(C.spread_voices(["", "a", ""], 3).values()),
                         {"a"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
