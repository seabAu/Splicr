"""End-to-end test of "fix this word everywhere", with a stub engine.

No GPU and no model here, so the engine's `run` is replaced by one that
writes plain WAVs. What is being tested is everything around it: that the
right sentences are chosen, that each is spliced into its own chunk without
disturbing its neighbours, that the take is rebuilt exactly once rather than
once per sentence, and that the segment times still describe the audio
afterwards.
"""

import os
import shutil
import sys
import tempfile
import unittest

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from narrator import pipeline, words as W
from narrator.engines import _lay_out
from narrator.segments import segments_from_pieces, save_segments

RATE = 24000


def _tone(value, seconds):
    return np.full(int(RATE * seconds), value, dtype=np.float32)


class TestFixWordEverywhere(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.calls = []
        self.rebuilds = []

        def fake_run(chunks, voice, speed, log, **kw):
            """Render each requested text as a distinct constant tone."""
            self.calls.append(chunks[0])
            path = os.path.join(self.dir, f"gen{len(self.calls)}.wav")
            sf.write(path, _tone(0.75, 1.0), RATE)
            return {"chunk_paths": [path], "chunk_durations": [1.0],
                    "chunk_texts": list(chunks), "segments": None}

        self.engine = {"key": "kokoro", "run": fake_run}
        self._saved_engine = pipeline.ENGINE_BY_KEY.get("kokoro")
        pipeline.ENGINE_BY_KEY["kokoro"] = self.engine

        # finalize_render and rejoin are about formats and encoders, not
        # about this feature; stub them and count the rebuilds.
        self._saved_finalize = pipeline.finalize_render
        self._saved_rejoin = pipeline.rejoin_master
        pipeline.rejoin_master = lambda paths, workdir, gaps, log: \
            os.path.join(workdir, "_master.wav")

        def fake_finalize(result, cfg, folder, stem, log, existing_path=None):
            self.rebuilds.append(True)
            return existing_path or os.path.join(folder, stem + ".mp3")
        pipeline.finalize_render = fake_finalize

        # misaki (Kokoro's G2P) is not installed in every environment, and
        # the real save_pronunciations would write to the user's own
        # dictionary. Both are stubbed: this test is about which sentences
        # get re-recorded, not about phoneme resolution.
        from narrator import pronunciation, config
        self._saved_g2p = pronunciation.respell_to_ipa
        self._saved_save = config.save_pronunciations
        self._saved_load = config.load_pronunciations
        self.lexicon = {}
        pronunciation.respell_to_ipa = lambda pieces, stress_on=0: (
            ("-".join(pieces), None) if pieces else (None, "empty"))
        config.save_pronunciations = self.lexicon.update
        config.load_pronunciations = lambda: dict(self.lexicon)

    def tearDown(self):
        if self._saved_engine is not None:
            pipeline.ENGINE_BY_KEY["kokoro"] = self._saved_engine
        pipeline.finalize_render = self._saved_finalize
        pipeline.rejoin_master = self._saved_rejoin
        from narrator import pronunciation, config
        pronunciation.respell_to_ipa = self._saved_g2p
        config.save_pronunciations = self._saved_save
        config.load_pronunciations = self._saved_load
        shutil.rmtree(self.dir, ignore_errors=True)

    def _chunk(self, name, sentences):
        pieces = [(t, _tone(0.1 + 0.05 * i, 1.0))
                  for i, t in enumerate(sentences)]
        path = os.path.join(self.dir, name)
        sf.write(path, _lay_out([a for _, a in pieces],
                                [0.12] * (len(pieces) - 1), RATE), RATE)
        segs = segments_from_pieces(pieces, RATE, [0.12] * (len(pieces) - 1),
                                    merge_short=False)
        save_segments(path, segs)
        return path, segs

    def _take(self):
        p1, s1 = self._chunk("1.wav", ["The form is here.",
                                       "Nothing to see."])
        p2, s2 = self._chunk("2.wav", ["Another form appears.",
                                       "Formation is different."])
        master = os.path.join(self.dir, "_master.wav")
        sf.write(master, _tone(0.5, 4.0), RATE)
        return {
            "engine_key": "kokoro", "voice": "af_heart", "speed": 1.0,
            "take": 1, "cfg": {}, "folder": self.dir, "stem": "out",
            "out_path": os.path.join(self.dir, "out.mp3"),
            "result": {
                "master": master,
                "chunk_paths": [p1, p2],
                "chunk_texts": [" ".join(x["text"] for x in s1),
                                " ".join(x["text"] for x in s2)],
                "chunk_durations": [s1[-1]["end"], s2[-1]["end"]],
                "segments": [s1, s2],
                "chunk_gaps": [0.45],
                "intro_offset": 0.0,
            },
        }

    def test_only_matching_sentences_are_rerendered(self):
        lr = self._take()
        out, fixed = pipeline.fix_word_everywhere(
            lr, "form", log=lambda *_: None, respelling="fohrm")
        self.assertEqual(fixed, 2)
        self.assertEqual(len(self.calls), 2)
        # "Formation is different." must not have been touched.
        self.assertNotIn("Formation is different.", self.calls)
        self.assertIn("The form is here.", self.calls)
        self.assertIn("Another form appears.", self.calls)
        self.assertIsNotNone(out)

    def test_take_is_rebuilt_exactly_once(self):
        """Forty occurrences must not mean forty re-encodes."""
        lr = self._take()
        pipeline.fix_word_everywhere(lr, "form", log=lambda *_: None,
                                     respelling="fohrm")
        self.assertEqual(len(self.rebuilds), 1)

    def test_untouched_sentences_keep_their_audio(self):
        lr = self._take()
        before = sf.read(lr["result"]["chunk_paths"][0], dtype="float32")[0]
        segs_before = [dict(s) for s in lr["result"]["segments"][0]]
        pipeline.fix_word_everywhere(lr, "form", log=lambda *_: None,
                                     respelling="fohrm")
        after_path = lr["result"]["chunk_paths"][0]
        after = sf.read(after_path, dtype="float32")[0]
        segs_after = lr["result"]["segments"][0]
        # Sentence 2 was not re-recorded: its audio content must be intact.
        a = int(segs_after[1]["start"] * RATE) + 100
        b = int(segs_after[1]["end"] * RATE) - 100
        old_value = float(before[int(segs_before[1]["start"] * RATE) + 100])
        self.assertAlmostEqual(float(after[a]), old_value, places=3)
        self.assertAlmostEqual(float(after[b]), old_value, places=3)

    def test_segments_still_describe_the_audio_after_the_fix(self):
        lr = self._take()
        pipeline.fix_word_everywhere(lr, "form", log=lambda *_: None,
                                     respelling="fohrm")
        for i, path in enumerate(lr["result"]["chunk_paths"]):
            audio = sf.read(path, dtype="float32")[0]
            for seg in lr["result"]["segments"][i]:
                self.assertLessEqual(seg["end"] * RATE, len(audio) + 1,
                                     "segment runs past the end of its chunk")
                self.assertLess(seg["start"], seg["end"])

    def test_edited_chunk_is_written_beside_the_original(self):
        """The untouched render must stay in the cache."""
        lr = self._take()
        original = lr["result"]["chunk_paths"][0]
        pipeline.fix_word_everywhere(lr, "form", log=lambda *_: None,
                                     respelling="fohrm")
        self.assertTrue(os.path.exists(original),
                        "the original chunk must not be overwritten")
        self.assertNotEqual(lr["result"]["chunk_paths"][0], original)

    def test_missing_word_raises_before_touching_anything(self):
        lr = self._take()
        paths_before = list(lr["result"]["chunk_paths"])
        with self.assertRaises(RuntimeError) as ctx:
            pipeline.fix_word_everywhere(lr, "absent", log=lambda *_: None,
                                         respelling="x")
        self.assertIn("Nothing in this take", str(ctx.exception))
        self.assertEqual(lr["result"]["chunk_paths"], paths_before)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.rebuilds, [])

    def test_kokoro_without_a_respelling_refuses(self):
        lr = self._take()
        with self.assertRaises(RuntimeError):
            pipeline.fix_word_everywhere(lr, "form", log=lambda *_: None,
                                         respelling="")
        self.assertEqual(self.calls, [], "nothing rendered on a refusal")

    def test_qwen_substitutes_the_text(self):
        lr = self._take()
        lr["engine_key"] = "qwen3"
        pipeline.ENGINE_BY_KEY["qwen3"] = self.engine
        try:
            out, fixed = pipeline.fix_word_everywhere(
                lr, "form", log=lambda *_: None, replacement="fohrm")
        finally:
            pipeline.ENGINE_BY_KEY.pop("qwen3", None)
        self.assertEqual(fixed, 2)
        self.assertIn("The fohrm is here.", self.calls)
        self.assertNotIn("The form is here.", self.calls)

    def test_qwen_without_a_replacement_refuses(self):
        lr = self._take()
        lr["engine_key"] = "qwen3"
        pipeline.ENGINE_BY_KEY["qwen3"] = self.engine
        try:
            with self.assertRaises(RuntimeError):
                pipeline.fix_word_everywhere(lr, "form",
                                             log=lambda *_: None)
        finally:
            pipeline.ENGINE_BY_KEY.pop("qwen3", None)
        self.assertEqual(self.calls, [])

    def test_the_respelling_is_saved_to_the_lexicon(self):
        """The lasting half of the fix: future documents get it too."""
        lr = self._take()
        pipeline.fix_word_everywhere(lr, "Form", log=lambda *_: None,
                                     respelling="fohrm")
        self.assertIn("form", self.lexicon, "stored under the folded form")
        self.assertEqual(self.lexicon["form__respelling"], "fohrm")

    def test_progress_is_reported_for_each_sentence(self):
        lr = self._take()
        seen = []
        pipeline.fix_word_everywhere(
            lr, "form", log=lambda *_: None, respelling="fohrm",
            progress=lambda i, t, text: seen.append((i, t)))
        self.assertEqual(seen, [(1, 2), (2, 2)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
