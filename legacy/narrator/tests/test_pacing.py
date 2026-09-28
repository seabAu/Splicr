"""Tests for text-derived pauses, per-join gaps and level matching.

The thing most worth protecting here is that the silence written into the
audio and the silence the segment times assume are the SAME silence. If
they drift apart, sentence-level fixes splice at the wrong place -- audio
cut in the middle of a word rather than a cosmetic mistake -- and nothing
about the render looks wrong until you listen.
"""

import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from narrator import pacing
from narrator.pacing import (PARAGRAPH, SENTENCE, gaps_for, kinds_from_indices,
                             match_levels, normalise_gaps)
from narrator.documents import chunk_text, chunk_text_with_kinds
from narrator.segments import (segments_from_pieces, group_sentences,
                               group_sentences_with_kinds, build_manifest)
from narrator.engines import _lay_out
from narrator.subtitles import build_chunk_srt

RATE = 24000
PACING = {"sentence_gap": 0.10, "paragraph_gap": 0.50,
          "match_levels": True, "match_levels_db": 3.0}


class TestNormaliseGaps(unittest.TestCase):
    def test_scalar_expands(self):
        self.assertEqual(normalise_gaps(0.25, 3), [0.25, 0.25, 0.25])

    def test_none_uses_fallback(self):
        self.assertEqual(normalise_gaps(None, 2, fallback=0.4), [0.4, 0.4])

    def test_list_padded_and_truncated(self):
        self.assertEqual(normalise_gaps([1.0], 3, fallback=0.0), [1.0, 0.0, 0.0])
        self.assertEqual(normalise_gaps([1.0, 2.0, 3.0], 2), [1.0, 2.0])

    def test_no_boundaries(self):
        self.assertEqual(normalise_gaps(0.5, 0), [])


class TestBoundaryKinds(unittest.TestCase):
    def test_kinds_from_indices(self):
        self.assertEqual(kinds_from_indices([0, 0, 1, 1, 2]),
                         [SENTENCE, PARAGRAPH, SENTENCE, PARAGRAPH])

    def test_single_piece_has_no_boundaries(self):
        self.assertEqual(kinds_from_indices([0]), [])

    def test_gaps_for_maps_kinds(self):
        self.assertEqual(gaps_for([PARAGRAPH, SENTENCE], PACING), [0.50, 0.10])


class TestChunkKinds(unittest.TestCase):
    def test_chunks_match_old_function(self):
        text = ("One two three. Four five six. Seven eight nine.\n\n"
                "Ten eleven twelve. Thirteen fourteen fifteen.\n\n"
                "Sixteen seventeen eighteen.")
        for size in (30, 50, 80, 200, 5000):
            chunks, kinds = chunk_text_with_kinds(text, size)
            self.assertEqual(chunks, chunk_text(text, size))
            self.assertEqual(len(kinds), len(chunks) - 1,
                             f"one kind per join at size {size}")
            self.assertTrue(set(kinds) <= {PARAGRAPH, SENTENCE})

    def test_split_on_paragraph_is_reported_as_paragraph(self):
        # Two paragraphs, a size that fits exactly one paragraph per chunk.
        text = "Alpha bravo charlie delta.\n\nEcho foxtrot golf hotel."
        chunks, kinds = chunk_text_with_kinds(text, 30)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(kinds, [PARAGRAPH])

    def test_split_inside_a_paragraph_is_reported_as_sentence(self):
        text = "Alpha bravo charlie. Delta echo foxtrot. Golf hotel india."
        chunks, kinds = chunk_text_with_kinds(text, 25)
        self.assertGreater(len(chunks), 1)
        self.assertEqual(set(kinds), {SENTENCE})

    def test_single_chunk_has_no_kinds(self):
        chunks, kinds = chunk_text_with_kinds("Just the one sentence.", 5000)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(kinds, [])


class TestGroupSentences(unittest.TestCase):
    def test_backward_compatible_groups(self):
        text = "A one. A two. A three.\n\nB one. B two."
        self.assertEqual(group_sentences(text, 200),
                         group_sentences_with_kinds(text, 200)[0])

    def test_paragraph_always_ends_a_group(self):
        # Everything would fit in one group on length alone; the paragraph
        # break must still split it, or the pause has nowhere to go.
        text = "A one. A two.\n\nB one. B two."
        groups, kinds = group_sentences_with_kinds(text, 5000)
        self.assertEqual(len(groups), 2)
        self.assertEqual(kinds, [PARAGRAPH])
        self.assertEqual(groups[0], "A one. A two.")

    def test_length_split_inside_paragraph_is_a_sentence_join(self):
        text = "Alpha bravo charlie. Delta echo foxtrot. Golf hotel india."
        groups, kinds = group_sentences_with_kinds(text, 25)
        self.assertGreater(len(groups), 1)
        self.assertEqual(set(kinds), {SENTENCE})

    def test_kinds_count_matches_joins(self):
        text = ("A one. A two. A three.\n\nB one.\n\nC one. C two. C three. "
                "C four.")
        for limit in (20, 40, 100, 5000):
            groups, kinds = group_sentences_with_kinds(text, limit)
            self.assertEqual(len(kinds), len(groups) - 1, f"limit {limit}")


def _piece(value, seconds):
    """A constant-valued block of audio, so a segment span can be checked by
    reading the value back out of the laid-out master."""
    return np.full(int(RATE * seconds), value, dtype=np.float32)


class TestSegmentsMatchAudio(unittest.TestCase):
    """The heart of it: segment times must land on the audio they name."""

    def _check_alignment(self, pieces, gaps, merge_short):
        audio = _lay_out([a for _, a in pieces], gaps, RATE)
        segs = segments_from_pieces(pieces, RATE, gaps,
                                    merge_short=merge_short)
        for seg in segs:
            a = int(round(seg["start"] * RATE))
            b = int(round(seg["end"] * RATE))
            self.assertLess(a, b, "segment must be non-empty")
            self.assertLessEqual(b, len(audio) + 1,
                                 "segment must stay inside the audio")
            span = audio[a:min(b, len(audio))]
            # No segment may start or end inside an inserted silence.
            self.assertNotEqual(float(span[0]), 0.0,
                                f"segment starts in silence: {seg['text']!r}")
            self.assertNotEqual(float(span[-1]), 0.0,
                                f"segment ends in silence: {seg['text']!r}")
        return segs, audio

    def test_uniform_gap(self):
        pieces = [("one two three", _piece(0.5, 0.4)),
                  ("four five six", _piece(0.6, 0.3)),
                  ("seven eight nine", _piece(0.7, 0.5))]
        self._check_alignment(pieces, [0.2, 0.2], merge_short=True)

    def test_mixed_gaps_do_not_shift_later_segments(self):
        pieces = [("one two three", _piece(0.5, 0.4)),
                  ("four five six", _piece(0.6, 0.3)),
                  ("seven eight nine", _piece(0.7, 0.5))]
        gaps = [0.50, 0.10]
        segs, audio = self._check_alignment(pieces, gaps, merge_short=True)
        # Third segment starts after both pieces and both gaps.
        expected = 0.4 + 0.50 + 0.3 + 0.10
        self.assertAlmostEqual(segs[2]["start"], expected, places=6)

    def test_zero_gaps_still_align(self):
        pieces = [("one two three", _piece(0.5, 0.4)),
                  ("four five six", _piece(0.6, 0.3))]
        segs, _ = self._check_alignment(pieces, [0.0], merge_short=True)
        self.assertAlmostEqual(segs[1]["start"], 0.4, places=6)

    def test_short_piece_merge_absorbs_the_gap(self):
        """A merged fragment must swallow the silence that followed it.

        This is the regression that matters: the old code concatenated the
        two texts and their audio but dropped the gap between them, so every
        later sentence's timings were early by one gap width. With Kokoro's
        gap previously being zero this never showed up; now that sentences
        have real silence between them, it would.
        """
        pieces = [("Dr.", _piece(0.5, 0.2)),                  # under 3 words
                  ("Smith went to town", _piece(0.6, 0.4)),
                  ("Then he came back again", _piece(0.7, 0.5))]
        gaps = [0.30, 0.10]
        segs, audio = self._check_alignment(pieces, gaps, merge_short=True)
        self.assertEqual(len(segs), 2, "the fragment merged into its follower")
        self.assertEqual(segs[0]["text"], "Dr. Smith went to town")
        # Merged span covers fragment + swallowed gap + follower.
        self.assertAlmostEqual(segs[0]["end"], 0.2 + 0.30 + 0.4, places=6)
        # And the next sentence still starts after the remaining gap.
        self.assertAlmostEqual(segs[1]["start"], 0.2 + 0.30 + 0.4 + 0.10,
                               places=6)
        self.assertAlmostEqual(len(audio) / RATE, segs[1]["end"], places=6)

    def test_merge_short_disabled_keeps_pieces(self):
        pieces = [("Dr.", _piece(0.5, 0.2)),
                  ("Smith went to town", _piece(0.6, 0.4))]
        segs = segments_from_pieces(pieces, RATE, [0.3], merge_short=False)
        self.assertEqual(len(segs), 2)
        self.assertAlmostEqual(segs[1]["start"], 0.2 + 0.3, places=6)

    def test_scalar_gap_still_accepted(self):
        pieces = [("one two three", _piece(0.5, 0.4)),
                  ("four five six", _piece(0.6, 0.3))]
        segs = segments_from_pieces(pieces, RATE, 0.25)
        self.assertAlmostEqual(segs[1]["start"], 0.65, places=6)


class TestLayOut(unittest.TestCase):
    def test_total_length(self):
        arrays = [_piece(0.5, 0.4), _piece(0.6, 0.3), _piece(0.7, 0.2)]
        out = _lay_out(arrays, [0.5, 0.1], RATE)
        self.assertAlmostEqual(len(out) / RATE, 0.4 + 0.5 + 0.3 + 0.1 + 0.2,
                               places=5)

    def test_no_trailing_silence(self):
        out = _lay_out([_piece(0.5, 0.2), _piece(0.6, 0.2)], [0.4], RATE)
        self.assertNotEqual(float(out[-1]), 0.0)

    def test_empty(self):
        self.assertEqual(len(_lay_out([], [], RATE)), 1)


class TestMatchLevels(unittest.TestCase):
    def test_pulls_outlier_toward_median(self):
        quiet, normal, loud = _piece(0.1, 0.2), _piece(0.5, 0.2), _piece(0.5, 0.2)
        out = match_levels([quiet, normal, loud], max_db=6.0)
        before = abs(float(quiet[0]) - 0.5)
        after = abs(float(out[0][0]) - 0.5)
        self.assertLess(after, before, "quiet piece moved toward the median")

    def test_correction_is_capped(self):
        # A piece 40 dB down cannot be dragged all the way up.
        out = match_levels([_piece(0.005, 0.2), _piece(0.5, 0.2),
                            _piece(0.5, 0.2)], max_db=3.0)
        gain = float(out[0][0]) / 0.005
        self.assertLessEqual(gain, 10 ** (3.0 / 20) + 1e-6)

    def test_loud_piece_is_brought_down(self):
        out = match_levels([_piece(0.9, 0.2), _piece(0.3, 0.2),
                            _piece(0.3, 0.2)], max_db=6.0)
        self.assertLess(float(out[0][0]), 0.9)

    def test_silence_is_left_alone(self):
        silent = np.zeros(int(RATE * 0.2), dtype=np.float32)
        out = match_levels([silent, _piece(0.3, 0.2), _piece(0.5, 0.2)])
        self.assertTrue(np.array_equal(out[0], silent),
                        "near-silence must not be boosted into noise")

    def test_never_clips(self):
        out = match_levels([_piece(0.95, 0.2), _piece(0.99, 0.2),
                            _piece(0.2, 0.2)], max_db=6.0)
        for a in out:
            self.assertLessEqual(float(np.abs(a).max()), 1.0 + 1e-6)

    def test_single_piece_unchanged(self):
        a = _piece(0.4, 0.2)
        self.assertTrue(np.array_equal(match_levels([a])[0], a))

    def test_lengths_preserved(self):
        arrays = [_piece(0.2, 0.3), _piece(0.8, 0.1), _piece(0.5, 0.4)]
        out = match_levels(arrays)
        self.assertEqual([len(a) for a in out], [len(a) for a in arrays])


class TestSubtitleTiming(unittest.TestCase):
    def _starts(self, path):
        from narrator.subtitles import _parse_srt_time
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
        return [_parse_srt_time(line.split("-->")[0].strip())
                for line in raw.splitlines() if "-->" in line]

    def test_per_join_gaps_accumulate(self):
        import tempfile
        out = os.path.join(tempfile.mkdtemp(), "t.srt")
        build_chunk_srt(["one", "two", "three"], [10.0, 20.0, 30.0], out,
                        gap_seconds=[0.5, 0.1])
        self.assertEqual(self._starts(out), [0.0, 10.5, 30.6])

    def test_scalar_gap_unchanged(self):
        import tempfile
        out = os.path.join(tempfile.mkdtemp(), "t.srt")
        build_chunk_srt(["one", "two", "three"], [10.0, 20.0, 30.0], out,
                        gap_seconds=0.35)
        self.assertEqual(self._starts(out), [0.0, 10.35, 30.70])


class TestManifestTiming(unittest.TestCase):
    def test_absolute_times_use_per_join_gaps(self):
        last_render = {
            "out_path": "/tmp/out.mp3", "engine_key": "kokoro",
            "voice": "af_heart", "speed": 1.0, "take": 1, "cfg": {},
            "folder": "/tmp", "stem": "out",
            "result": {
                "master": "/tmp/_master.wav",
                "chunk_paths": ["/tmp/1.wav", "/tmp/2.wav", "/tmp/3.wav"],
                "chunk_texts": ["one", "two", "three"],
                "chunk_durations": [10.0, 20.0, 30.0],
                "segments": [[{"text": "one", "start": 0.0, "end": 10.0}],
                             [{"text": "two", "start": 0.0, "end": 20.0}],
                             [{"text": "three", "start": 0.0, "end": 30.0}]],
                "chunk_gaps": [0.5, 0.1],
            },
        }
        m = build_manifest(last_render)
        self.assertEqual([c["start"] for c in m["chunks"]], [0.0, 10.5, 30.6])
        self.assertAlmostEqual(m["duration"], 60.6, places=6)

    def test_falls_back_to_scalar_for_old_renders(self):
        last_render = {
            "out_path": "/tmp/out.mp3", "engine_key": "kokoro",
            "voice": "af_heart", "speed": 1.0, "take": 1, "cfg": {},
            "folder": "/tmp", "stem": "out",
            "result": {
                "master": "/tmp/_master.wav",
                "chunk_paths": ["/tmp/1.wav", "/tmp/2.wav"],
                "chunk_texts": ["one", "two"],
                "chunk_durations": [10.0, 20.0],
                "segments": [[{"text": "one", "start": 0.0, "end": 10.0}],
                             [{"text": "two", "start": 0.0, "end": 20.0}]],
                "chunk_gap": 0.35,
            },
        }
        m = build_manifest(last_render)
        self.assertEqual([c["start"] for c in m["chunks"]], [0.0, 10.35])


class TestPacingSettings(unittest.TestCase):
    def test_fingerprint_changes_with_settings(self):
        base = pacing.pacing_fingerprint()
        self.assertIn("pacing:", base)
        real = pacing.pacing_settings
        try:
            pacing.pacing_settings = lambda: dict(pacing.DEFAULT_PACING,
                                                  paragraph_gap=0.9)
            self.assertNotEqual(pacing.pacing_fingerprint(), base)
        finally:
            pacing.pacing_settings = real

    def test_defaults_are_returned_without_settings(self):
        p = pacing.pacing_settings()
        self.assertEqual(set(p), set(pacing.DEFAULT_PACING))
        self.assertGreater(p["paragraph_gap"], p["sentence_gap"],
                           "a paragraph break should outlast a sentence break")


if __name__ == "__main__":
    unittest.main(verbosity=2)
