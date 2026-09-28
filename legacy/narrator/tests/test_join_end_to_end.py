"""End-to-end timing: real WAV files on disk, joined the way a render joins
them, checked against the manifest a fix would splice against.

The unit tests check the arithmetic. This checks that the arithmetic
describes the file that actually gets written -- that a sentence's absolute
time in the manifest lands on that sentence in the master, after chunk
gaps, level matching and sidecar round-tripping have all had their turn.
"""

import os
import shutil
import sys
import tempfile
import unittest

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from narrator.engines import _lay_out, _join_chunk_wavs
from narrator.segments import (segments_from_pieces, save_segments,
                               load_segments, build_manifest, write_manifest,
                               load_manifest)

RATE = 24000


def _tone(value, seconds):
    return np.full(int(RATE * seconds), value, dtype=np.float32)


class TestJoinEndToEnd(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _write_chunk(self, name, pieces, gaps):
        path = os.path.join(self.dir, name)
        sf.write(path, _lay_out([a for _, a in pieces], gaps, RATE), RATE)
        segs = segments_from_pieces(pieces, RATE, gaps)
        save_segments(path, segs)
        return path, segs

    def test_manifest_times_land_on_the_right_audio(self):
        # Each sentence gets a distinct constant value, so we can read the
        # master at a manifest time and confirm which sentence is there.
        c1, segs1 = self._write_chunk("1.wav", [
            ("one one one", _tone(0.11, 0.5)),
            ("two two two", _tone(0.22, 0.4)),
        ], [0.12])
        c2, segs2 = self._write_chunk("2.wav", [
            ("three three three", _tone(0.33, 0.6)),
            ("four four four", _tone(0.44, 0.3)),
        ], [0.45])

        # A paragraph break between the chunks, a sentence break inside them.
        result = _join_chunk_wavs([c1, c2], ["c1", "c2"], self.dir,
                                  gaps=[0.45],
                                  pacing={"sentence_gap": 0.12,
                                          "paragraph_gap": 0.45,
                                          "match_levels": False,
                                          "match_levels_db": 3.0})
        last_render = {
            "out_path": os.path.join(self.dir, "out.mp3"),
            "engine_key": "kokoro", "voice": "af_heart", "speed": 1.0,
            "take": 1, "cfg": {}, "folder": self.dir, "stem": "out",
            "result": result,
        }
        m = build_manifest(last_render)
        master, rate = sf.read(result["master"], dtype="float32")
        self.assertEqual(rate, RATE)

        expected = {"one one one": 0.11, "two two two": 0.22,
                    "three three three": 0.33, "four four four": 0.44}
        for chunk in m["chunks"]:
            for seg in chunk["segments"]:
                mid = int((seg["abs_start"] + seg["abs_end"]) / 2 * RATE)
                # places=3: these files are 16-bit PCM, as real renders
                # are, so the constant read back is quantised. The point of
                # the check is which sentence is at that time, and the
                # values are far enough apart that quantisation cannot
                # confuse one for another.
                self.assertAlmostEqual(
                    float(master[mid]), expected[seg["text"]], places=3,
                    msg=f"{seg['text']!r} is not where the manifest says")

    def test_master_length_matches_manifest_duration(self):
        c1, _ = self._write_chunk("1.wav", [("a a a", _tone(0.2, 0.5))], [])
        c2, _ = self._write_chunk("2.wav", [("b b b", _tone(0.3, 0.4))], [])
        c3, _ = self._write_chunk("3.wav", [("c c c", _tone(0.4, 0.3))], [])
        result = _join_chunk_wavs([c1, c2, c3], ["a", "b", "c"], self.dir,
                                  gaps=[0.45, 0.12],
                                  pacing={"sentence_gap": 0.12,
                                          "paragraph_gap": 0.45,
                                          "match_levels": False,
                                          "match_levels_db": 3.0})
        m = build_manifest({
            "out_path": os.path.join(self.dir, "out.mp3"),
            "engine_key": "kokoro", "voice": "af_heart", "speed": 1.0,
            "take": 1, "cfg": {}, "folder": self.dir, "stem": "out",
            "result": result})
        master, _ = sf.read(result["master"], dtype="float32")
        self.assertAlmostEqual(len(master) / RATE, m["duration"], places=4)
        self.assertAlmostEqual(m["duration"], 0.5 + 0.45 + 0.4 + 0.12 + 0.3,
                               places=4)

    def test_manifest_round_trip_keeps_per_join_gaps(self):
        c1, _ = self._write_chunk("1.wav", [("a a a", _tone(0.2, 0.5))], [])
        c2, _ = self._write_chunk("2.wav", [("b b b", _tone(0.3, 0.4))], [])
        result = _join_chunk_wavs([c1, c2], ["a", "b"], self.dir,
                                  gaps=[0.45])
        last_render = {
            "out_path": os.path.join(self.dir, "out.mp3"),
            "engine_key": "kokoro", "voice": "af_heart", "speed": 1.0,
            "take": 1, "cfg": {}, "folder": self.dir, "stem": "out",
            "result": result}
        path = write_manifest(last_render)
        self.assertIsNotNone(path, "manifest should have been written")
        reloaded = load_manifest(path)
        self.assertEqual(reloaded["result"]["chunk_gaps"], [0.45])
        # And the reloaded take produces the same absolute times.
        self.assertEqual(
            [c["start"] for c in build_manifest(reloaded)["chunks"]],
            [c["start"] for c in build_manifest(last_render)["chunks"]])

    def test_level_matching_does_not_move_any_timing(self):
        c1, _ = self._write_chunk("1.wav", [("a a a", _tone(0.9, 0.5))], [])
        c2, _ = self._write_chunk("2.wav", [("b b b", _tone(0.1, 0.4))], [])
        common = dict(gaps=[0.45])
        flat = _join_chunk_wavs([c1, c2], ["a", "b"], self.dir,
                                pacing={"sentence_gap": 0.12,
                                        "paragraph_gap": 0.45,
                                        "match_levels": False,
                                        "match_levels_db": 3.0}, **common)
        flat_len = len(sf.read(flat["master"], dtype="float32")[0])
        matched = _join_chunk_wavs([c1, c2], ["a", "b"], self.dir,
                                   pacing={"sentence_gap": 0.12,
                                           "paragraph_gap": 0.45,
                                           "match_levels": True,
                                           "match_levels_db": 3.0}, **common)
        matched_audio = sf.read(matched["master"], dtype="float32")[0]
        self.assertEqual(len(matched_audio), flat_len,
                         "matching levels must not change any duration")
        self.assertEqual(flat["chunk_durations"], matched["chunk_durations"])

    def test_sidecars_survive_the_round_trip(self):
        pieces = [("one one one", _tone(0.11, 0.5)),
                  ("two two two", _tone(0.22, 0.4))]
        path, segs = self._write_chunk("1.wav", pieces, [0.12])
        self.assertEqual(load_segments(path), segs)
        self.assertAlmostEqual(segs[1]["start"], 0.5 + 0.12, places=6)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestOpenATake(unittest.TestCase):
    """Reopening a finished take: the manifest survives, the cache may not."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _take(self, n_chunks=2):
        paths = []
        for i in range(n_chunks):
            p = os.path.join(self.dir, f"{i}.wav")
            sf.write(p, _tone(0.3, 1.0), RATE)
            save_segments(p, [{"text": f"Sentence {i}.", "start": 0.0,
                               "end": 1.0}])
            paths.append(p)
        master = os.path.join(self.dir, "_master.wav")
        sf.write(master, _tone(0.3, 2.0), RATE)
        return {
            "out_path": os.path.join(self.dir, "out.mp3"),
            "engine_key": "kokoro", "voice": "af_heart", "speed": 1.0,
            "take": 1, "cfg": {}, "folder": self.dir, "stem": "out",
            "result": {"master": master, "chunk_paths": paths,
                       "chunk_texts": [f"Sentence {i}." for i in
                                       range(n_chunks)],
                       "chunk_durations": [1.0] * n_chunks,
                       "segments": [[{"text": f"Sentence {i}.",
                                      "start": 0.0, "end": 1.0}]
                                    for i in range(n_chunks)],
                       "chunk_gaps": [0.45] * (n_chunks - 1)},
        }

    def test_round_trip_restores_a_usable_take(self):
        from narrator.segments import check_take
        original = self._take()
        path = write_manifest(original)
        reopened = load_manifest(path)
        ok, problem = check_take(reopened)
        self.assertTrue(ok, problem)
        self.assertEqual(reopened["engine_key"], "kokoro")
        self.assertEqual(reopened["voice"], "af_heart")
        self.assertEqual(reopened["result"]["chunk_paths"],
                         original["result"]["chunk_paths"])
        self.assertEqual(reopened["result"]["chunk_gaps"], [0.45])

    def test_cleared_cache_is_refused_with_a_reason(self):
        """The manifest lives beside the output; the audio lives in the
        cache, which gets cleared. Surviving does not imply editable."""
        from narrator.segments import check_take
        lr = self._take()
        path = write_manifest(lr)
        for p in lr["result"]["chunk_paths"]:
            os.remove(p)
        ok, problem = check_take(load_manifest(path))
        self.assertFalse(ok)
        self.assertIn("cache", problem)

    def test_partially_missing_audio_is_refused_and_counted(self):
        from narrator.segments import check_take
        lr = self._take(n_chunks=3)
        path = write_manifest(lr)
        os.remove(lr["result"]["chunk_paths"][1])
        ok, problem = check_take(load_manifest(path))
        self.assertFalse(ok)
        self.assertIn("1 of 3", problem)

    def test_empty_manifest_is_refused(self):
        from narrator.segments import check_take
        ok, problem = check_take({"result": {"chunk_paths": []}})
        self.assertFalse(ok)
        self.assertIn("no audio parts", problem)

    def test_find_manifests_returns_newest_first(self):
        from narrator.segments import find_manifests
        import time as _t
        a = self._take()
        write_manifest(a)
        b = dict(a, stem="later", out_path=os.path.join(self.dir,
                                                        "later.mp3"))
        _t.sleep(0.01)
        write_manifest(b)
        found = find_manifests(self.dir)
        self.assertEqual(len(found), 2)
        self.assertTrue(found[0].endswith("later.manifest.json"))

    def test_find_manifests_on_a_missing_folder(self):
        from narrator.segments import find_manifests
        self.assertEqual(find_manifests("/no/such/place"), [])
