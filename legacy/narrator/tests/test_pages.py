"""Tests for the page layer: flat reading order, page grouping, and the SRT.

The load-bearing test here is test_agrees_with_build_manifest. flat_segments
and build_manifest each compute absolute times, and if they ever disagree the
page layer would sit slightly off the audio in a way that looks fine in the
file and only shows up on a timeline in an editor.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from narrator.segments import flat_segments, build_manifest
from narrator.subtitles import (group_pages, build_page_srt, wrap_page,
                                page_srt_for_result, _parse_srt_time)


def _result(chunk_gaps=None, intro_offset=0.0):
    return {
        "master": "/tmp/_master.wav",
        "chunk_paths": ["/tmp/1.wav", "/tmp/2.wav"],
        "chunk_texts": ["one two", "three four"],
        "chunk_durations": [10.0, 20.0],
        "segments": [
            [{"text": "One.", "start": 0.0, "end": 4.0},
             {"text": "Two.", "start": 4.5, "end": 10.0}],
            [{"text": "Three.", "start": 0.0, "end": 9.0},
             {"text": "Four.", "start": 9.5, "end": 20.0}],
        ],
        "chunk_gaps": chunk_gaps if chunk_gaps is not None else [0.45],
        "intro_offset": intro_offset,
    }


class TestFlatSegments(unittest.TestCase):
    def test_order_and_absolute_times(self):
        segs, total = flat_segments(_result())
        self.assertEqual([s["text"] for s in segs],
                         ["One.", "Two.", "Three.", "Four."])
        self.assertAlmostEqual(segs[0]["start"], 0.0)
        self.assertAlmostEqual(segs[1]["end"], 10.0)
        # Second chunk begins after the first chunk plus the join gap.
        self.assertAlmostEqual(segs[2]["start"], 10.45)
        self.assertAlmostEqual(total, 10.0 + 0.45 + 20.0)

    def test_intro_offset_shifts_everything(self):
        segs, total = flat_segments(_result(intro_offset=7.5))
        self.assertAlmostEqual(segs[0]["start"], 7.5)
        self.assertAlmostEqual(segs[2]["start"], 17.95)
        self.assertAlmostEqual(total, 7.5 + 30.45)

    def test_agrees_with_build_manifest(self):
        """Two copies of the absolute-time arithmetic must not drift."""
        for gaps in ([0.45], [0.12], [1.0]):
            for offset in (0.0, 3.25):
                result = _result(chunk_gaps=gaps, intro_offset=offset)
                last_render = {
                    "out_path": "/tmp/out.mp3", "engine_key": "kokoro",
                    "voice": "af_heart", "speed": 1.0, "take": 1, "cfg": {},
                    "folder": "/tmp", "stem": "out", "result": result}
                m = build_manifest(last_render)
                flat, total = flat_segments(result)
                from_manifest = [(s["text"], round(s["abs_start"], 9),
                                  round(s["abs_end"], 9))
                                 for c in m["chunks"] for s in c["segments"]]
                from_flat = [(s["text"], round(s["start"], 9),
                              round(s["end"], 9)) for s in flat]
                self.assertEqual(from_manifest, from_flat,
                                 f"gaps={gaps} offset={offset}")
                self.assertAlmostEqual(total, m["duration"], places=9)

    def test_missing_gaps_fall_back_to_scalar(self):
        result = _result()
        del result["chunk_gaps"]
        result["chunk_gap"] = 0.35
        segs, _ = flat_segments(result)
        self.assertAlmostEqual(segs[2]["start"], 10.35)


class TestGroupPages(unittest.TestCase):
    def _segs(self, n, length=10, dur=2.0):
        return [{"text": f"S{i} " + "x" * length, "start": i * dur,
                 "end": i * dur + dur * 0.9, "chunk": 0} for i in range(n)]

    def test_pages_are_continuous(self):
        segs = self._segs(9)
        pages = group_pages(segs, total_duration=18.0, page_chars=40)
        self.assertGreater(len(pages), 1)
        for a, b in zip(pages, pages[1:]):
            self.assertEqual(a["end"], b["start"],
                             "no gap where the layer would go blank")
        self.assertEqual(pages[-1]["end"], 18.0)
        self.assertEqual(pages[0]["start"], 0.0)

    def test_sentences_are_never_split(self):
        segs = self._segs(6, length=30)
        pages = group_pages(segs, 12.0, page_chars=40)
        joined = " ".join(p["text"] for p in pages)
        for seg in segs:
            self.assertIn(seg["text"], joined,
                          "every sentence survives whole")

    def test_one_long_sentence_becomes_its_own_page(self):
        segs = [{"text": "x" * 5000, "start": 0.0, "end": 30.0, "chunk": 0}]
        pages = group_pages(segs, 30.0, page_chars=100)
        self.assertEqual(len(pages), 1)
        self.assertEqual(len(pages[0]["text"]), 5000)

    def test_page_size_is_respected_where_it_can_be(self):
        segs = self._segs(20, length=20)
        pages = group_pages(segs, 40.0, page_chars=200)
        for p in pages[:-1]:
            # Allowed to overshoot by at most the last sentence added.
            self.assertLessEqual(len(p["text"]), 200 + 30)

    def test_empty_input(self):
        self.assertEqual(group_pages([], 10.0), [])

    def test_blank_sentences_are_skipped(self):
        segs = [{"text": "  ", "start": 0.0, "end": 1.0, "chunk": 0},
                {"text": "Real text.", "start": 1.0, "end": 5.0, "chunk": 0}]
        pages = group_pages(segs, 5.0, page_chars=100)
        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0]["text"], "Real text.")
        self.assertEqual(pages[0]["start"], 1.0)

    def test_zero_length_page_is_dropped(self):
        segs = [{"text": "A.", "start": 5.0, "end": 5.0, "chunk": 0}]
        self.assertEqual(group_pages(segs, 5.0), [])


class TestWrap(unittest.TestCase):
    def test_wraps_at_word_boundaries(self):
        out = wrap_page("alpha bravo charlie delta echo foxtrot", width=20)
        for line in out.splitlines():
            self.assertLessEqual(len(line), 20)
        self.assertEqual(out.replace("\n", " ").split(),
                         "alpha bravo charlie delta echo foxtrot".split())

    def test_no_wrap_when_disabled(self):
        text = "alpha bravo charlie delta"
        self.assertEqual(wrap_page(text, width=0), text)

    def test_unbreakable_token_survives(self):
        long = "x" * 100
        self.assertIn(long, wrap_page(long, width=20))


class TestPageSrt(unittest.TestCase):
    def _cues(self, path):
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
        cues = []
        for block in raw.strip().split("\n\n"):
            lines = block.splitlines()
            a, b = [t.strip() for t in lines[1].split("-->")]
            cues.append((_parse_srt_time(a), _parse_srt_time(b),
                         "\n".join(lines[2:])))
        return cues

    def test_writes_holdable_cues(self):
        out = os.path.join(tempfile.mkdtemp(), "p.srt")
        pages = [{"text": "First page text.", "start": 0.0, "end": 45.0},
                 {"text": "Second page text.", "start": 45.0, "end": 90.0}]
        build_page_srt(pages, out, wrap=0)
        cues = self._cues(out)
        self.assertEqual(len(cues), 2)
        self.assertEqual((cues[0][0], cues[0][1]), (0.0, 45.0))
        self.assertEqual(cues[1][2], "Second page text.")
        # Long holds are the whole point -- confirm nothing truncates them.
        self.assertGreater(cues[0][1] - cues[0][0], 30.0)

    def test_end_to_end_from_a_result(self):
        out = os.path.join(tempfile.mkdtemp(), "p.srt")
        written = page_srt_for_result(_result(), out, page_chars=20, wrap=0)
        self.assertEqual(written, out)
        cues = self._cues(out)
        self.assertGreater(len(cues), 1)
        self.assertAlmostEqual(cues[0][0], 0.0)
        self.assertAlmostEqual(cues[-1][1], 30.45, places=6)
        for a, b in zip(cues, cues[1:]):
            self.assertAlmostEqual(a[1], b[0], places=6)

    def test_single_page_covers_whole_take(self):
        out = os.path.join(tempfile.mkdtemp(), "p.srt")
        page_srt_for_result(_result(), out, page_chars=100000, wrap=0)
        cues = self._cues(out)
        self.assertEqual(len(cues), 1)
        self.assertAlmostEqual(cues[0][0], 0.0)
        self.assertAlmostEqual(cues[0][1], 30.45, places=6)
        self.assertEqual(cues[0][2], "One. Two. Three. Four.")


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestParagraphStructure(unittest.TestCase):
    """Pages must read like pages, not like one undifferentiated block."""

    def _result_with_paragraphs(self):
        chunk = ("First para one. First para two.\n\n"
                 "Second para one. Second para two.")
        return {
            "master": "/tmp/_m.wav",
            "chunk_paths": ["/tmp/1.wav"],
            "chunk_texts": [chunk],
            "chunk_durations": [40.0],
            "segments": [[
                {"text": "First para one.", "start": 0.0, "end": 9.0},
                {"text": "First para two.", "start": 10.0, "end": 19.0},
                {"text": "Second para one.", "start": 20.0, "end": 29.0},
                {"text": "Second para two.", "start": 30.0, "end": 40.0},
            ]],
            "chunk_gaps": [],
            "intro_offset": 0.0,
        }

    def test_paragraph_breaks_are_recovered(self):
        segs, _ = flat_segments(self._result_with_paragraphs())
        self.assertEqual([s["new_paragraph"] for s in segs],
                         [False, False, True, False])

    def test_pages_keep_the_blank_line(self):
        segs, total = flat_segments(self._result_with_paragraphs())
        pages = group_pages(segs, total, page_chars=10000)
        self.assertEqual(len(pages), 1)
        self.assertIn("\n\n", pages[0]["text"])
        self.assertTrue(pages[0]["text"].startswith("First para one."))

    def test_page_prefers_to_break_on_a_paragraph(self):
        segs, total = flat_segments(self._result_with_paragraphs())
        # Page target sized so the paragraph break falls past 60% full.
        pages = group_pages(segs, total, page_chars=40)
        self.assertEqual(len(pages), 2)
        self.assertNotIn("Second", pages[0]["text"])
        self.assertTrue(pages[1]["text"].startswith("Second para one."))

    def test_wrapping_preserves_paragraph_breaks(self):
        out = wrap_page("alpha bravo charlie\n\ndelta echo foxtrot", width=12)
        self.assertIn("\n\n", out)
        blocks = out.split("\n\n")
        self.assertEqual(len(blocks), 2)
        self.assertTrue(blocks[1].startswith("delta"))

    def test_unlocatable_sentence_reports_no_break(self):
        """An engine that returns normalised text must not invent breaks."""
        result = self._result_with_paragraphs()
        result["segments"][0][2]["text"] = "Totally different wording here."
        segs, _ = flat_segments(result)
        self.assertFalse(segs[2]["new_paragraph"])
