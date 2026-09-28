"""Tests for word-level location and fix planning.

Word matching is the part most likely to be quietly wrong: match too
loosely and fixing "form" also rewrites "formation"; match too tightly and
the same word with a curly apostrophe, or capitalised at the start of a
sentence, is missed and the fix silently skips it.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from narrator import words as W


def _result(sentences_per_chunk, ext=".wav"):
    """A minimal finished-take shape: one list of sentence texts per chunk."""
    chunks = []
    for group in sentences_per_chunk:
        segs, t = [], 0.0
        for text in group:
            segs.append({"text": text, "start": t, "end": t + 3.0})
            t += 3.5
        chunks.append(segs)
    return {
        "chunk_paths": [f"/tmp/{i}{ext}" for i in range(len(chunks))],
        "chunk_texts": [" ".join(g) for g in sentences_per_chunk],
        "chunk_durations": [len(g) * 3.5 for g in sentences_per_chunk],
        "segments": chunks,
    }


class TestWordMatching(unittest.TestCase):
    def test_whole_words_only(self):
        self.assertEqual(W.count_in("The form of formation is formal.",
                                    "form"), 1)

    def test_case_insensitive(self):
        self.assertEqual(W.count_in("Form and form and FORM.", "form"), 3)

    def test_curly_and_straight_apostrophes_match(self):
        text = "It doesn\u2019t matter, it doesn't."
        self.assertEqual(W.count_in(text, "doesn't"), 2)
        self.assertEqual(W.count_in(text, "doesn\u2019t"), 2)

    def test_hyphenated_word_is_one_word(self):
        self.assertEqual(W.count_in("A well-known well known fact.",
                                    "well-known"), 1)
        # "well" alone should not match inside "well-known".
        self.assertEqual(W.count_in("A well-known fact and a well.",
                                    "well"), 1)

    def test_possessive_is_not_the_bare_word(self):
        self.assertEqual(W.count_in("Marx's view and Marx himself.",
                                    "marx"), 1)

    def test_punctuation_boundaries(self):
        self.assertEqual(W.count_in('"Form," he said. (Form!) Form?',
                                    "form"), 3)

    def test_no_match_returns_zero(self):
        self.assertEqual(W.count_in("Nothing here.", "absent"), 0)

    def test_normalise_folds_case_and_apostrophe(self):
        self.assertEqual(W.normalise("  Doesn\u2019T "), "doesn't")


class TestWordsIn(unittest.TestCase):
    def test_spans_are_correct(self):
        text = "Alpha bravo-charlie don't."
        got = W.words_in(text)
        self.assertEqual([w["text"] for w in got],
                         ["Alpha", "bravo-charlie", "don't"])
        for w in got:
            self.assertEqual(text[w["at"]:w["to"]], w["text"])

    def test_numbers_are_not_words(self):
        self.assertEqual([w["text"] for w in W.words_in("In 1867 Marx wrote")],
                         ["In", "Marx", "wrote"])

    def test_empty(self):
        self.assertEqual(W.words_in(""), [])
        self.assertEqual(W.words_in(None), [])


class TestSubstitute(unittest.TestCase):
    def test_replaces_every_occurrence(self):
        out = W.substitute("Form the form of forms.", "form", "fohrm")
        self.assertEqual(out, "fohrm the fohrm of forms.")

    def test_does_not_touch_longer_words(self):
        self.assertEqual(W.substitute("formation", "form", "X"), "formation")

    def test_replacement_case_is_left_alone(self):
        """A respelling is not a capitalisation variant of the word."""
        self.assertEqual(W.substitute("Marx said", "Marx", "marks"),
                         "marks said")


class TestOccurrences(unittest.TestCase):
    def test_finds_across_chunks(self):
        r = _result([["The form is here.", "Nothing."],
                     ["Another form appears.", "And form again."]])
        got = W.occurrences(r, "form")
        self.assertEqual([(o["chunk"], o["seg"]) for o in got],
                         [(0, 0), (1, 0), (1, 1)])

    def test_counts_multiple_in_one_sentence(self):
        r = _result([["Form and form.", "None."]])
        got = W.occurrences(r, "form")
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["count"], 2)

    def test_carries_the_span(self):
        r = _result([["First.", "The form here."]])
        got = W.occurrences(r, "form")
        self.assertEqual(got[0]["start"], 3.5)
        self.assertEqual(got[0]["end"], 6.5)

    def test_no_occurrences(self):
        self.assertEqual(W.occurrences(_result([["Nothing here."]]), "form"),
                         [])


class TestDistinctWords(unittest.TestCase):
    def test_sorted_by_frequency(self):
        r = _result([["form form form.", "alpha alpha.", "zeta."]])
        got = W.distinct_words(r)
        self.assertEqual([e["word"] for e in got[:3]],
                         ["form", "alpha", "zeta"])
        self.assertEqual(got[0]["count"], 3)

    def test_case_variants_are_one_entry(self):
        r = _result([["Form form FORM."]])
        got = W.distinct_words(r)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["count"], 3)

    def test_short_words_excluded(self):
        r = _result([["A form of a thing."]])
        self.assertNotIn("a", [W.normalise(e["word"])
                               for e in W.distinct_words(r, min_length=2)])


class TestPlanFix(unittest.TestCase):
    def test_kokoro_uses_the_lexicon(self):
        r = _result([["The form is here."]])
        found, mode, problem = W.plan_fix(r, "form", "kokoro")
        self.assertIsNone(problem)
        self.assertEqual(mode, "lexicon")
        self.assertEqual(len(found), 1)

    def test_qwen_needs_a_replacement(self):
        r = _result([["The form is here."]])
        _, mode, problem = W.plan_fix(r, "form", "qwen3")
        self.assertEqual(mode, "substitution")
        self.assertIn("replacement spelling", problem)

    def test_qwen_with_replacement_is_fine(self):
        r = _result([["The form is here."]])
        _, mode, problem = W.plan_fix(r, "form", "qwen3",
                                      replacement="fohrm")
        self.assertEqual(mode, "substitution")
        self.assertIsNone(problem)

    def test_edge_mp3_is_refused_clearly(self):
        r = _result([["The form is here."]], ext=".mp3")
        _, mode, problem = W.plan_fix(r, "form", "edge")
        self.assertIsNone(mode)
        self.assertIn("mp3", problem)

    def test_missing_word_is_refused_before_anything_else(self):
        r = _result([["Nothing here."]])
        found, mode, problem = W.plan_fix(r, "form", "kokoro")
        self.assertEqual(found, [])
        self.assertIn("Nothing in this take", problem)


class TestPronunciationFingerprint(unittest.TestCase):
    def test_changes_when_the_phonemes_change(self):
        from narrator.pronunciation import pronunciation_fingerprint as fp
        a = fp("say narrativization now", {"narrativization": "AAA"})
        b = fp("say narrativization now", {"narrativization": "BBB"})
        self.assertNotEqual(a, b)
        self.assertTrue(a)

    def test_empty_when_no_override_applies_to_this_text(self):
        from narrator.pronunciation import pronunciation_fingerprint as fp
        self.assertEqual(fp("nothing relevant", {"narrativization": "AAA"}),
                         "")

    def test_empty_with_no_overrides_at_all(self):
        """Anyone with no custom pronunciations keeps their existing cache."""
        from narrator.pronunciation import pronunciation_fingerprint as fp
        self.assertEqual(fp("any text at all", {}), "")

    def test_respelling_keys_are_ignored(self):
        from narrator.pronunciation import pronunciation_fingerprint as fp
        self.assertEqual(fp("word here", {"word__respelling": "wurd"}), "")

    def test_is_case_insensitive_about_the_text(self):
        from narrator.pronunciation import pronunciation_fingerprint as fp
        self.assertEqual(fp("Narrativization", {"narrativization": "AAA"}),
                         fp("narrativization", {"narrativization": "AAA"}))


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestQuoteBlocks(unittest.TestCase):
    """Block quotes must survive cleaning and become their own chunks."""

    def _marked(self, raw):
        from narrator.documents import strip_markdown
        return strip_markdown(raw, [], mark_quotes=True)

    def test_quote_becomes_its_own_chunk(self):
        from narrator.documents import chunk_text_with_voices
        text = self._marked("Prose one.\n\n> A quote.\n> More quote.\n\n"
                            "Prose two.")
        chunks, kinds, is_quote = chunk_text_with_voices(text, 5000)
        self.assertEqual(is_quote, [False, True, False])
        self.assertEqual(chunks[1], "A quote. More quote.")

    def test_markers_never_survive_into_a_chunk(self):
        from narrator.documents import chunk_text_with_voices, QUOTE_MARK
        text = self._marked("Prose.\n\n> Quoted.\n\nMore prose.")
        chunks, _, _ = chunk_text_with_voices(text, 5000)
        for c in chunks:
            self.assertNotIn(QUOTE_MARK, c, "a marker would be narrated")

    def test_without_marking_quotes_are_flattened_as_before(self):
        from narrator.documents import strip_markdown, QUOTE_MARK
        out = strip_markdown("> Quoted line.", [], mark_quotes=False)
        self.assertNotIn(QUOTE_MARK, out)
        self.assertEqual(out.strip(), "Quoted line.")

    def test_definition_markers_are_not_quotes(self):
        from narrator.documents import QUOTE_MARK
        out = self._marked(": a definition")
        self.assertNotIn(QUOTE_MARK, out)

    def test_document_with_no_quotes_is_all_narration(self):
        from narrator.documents import chunk_text_with_voices
        chunks, _, is_quote = chunk_text_with_voices("Just prose here.", 5000)
        self.assertEqual(is_quote, [False])

    def test_document_that_is_entirely_a_quote(self):
        from narrator.documents import chunk_text_with_voices
        text = self._marked("> All of it is quoted.")
        _, _, is_quote = chunk_text_with_voices(text, 5000)
        self.assertEqual(is_quote, [True])

    def test_quote_boundary_is_a_paragraph_pause(self):
        from narrator.documents import chunk_text_with_voices
        from narrator.pacing import PARAGRAPH
        text = self._marked("Prose.\n\n> Quoted.\n\nMore.")
        _, kinds, _ = chunk_text_with_voices(text, 5000)
        self.assertTrue(all(k == PARAGRAPH for k in kinds),
                        "going into and out of a quote deserves a real pause")

    def test_flags_line_up_with_chunks_when_a_quote_is_split(self):
        from narrator.documents import chunk_text_with_voices
        long_quote = " ".join(f"Quoted sentence {i}." for i in range(40))
        text = self._marked(f"Prose.\n\n> {long_quote}\n\nMore prose.")
        chunks, kinds, is_quote = chunk_text_with_voices(text, 120)
        self.assertEqual(len(is_quote), len(chunks))
        self.assertEqual(len(kinds), len(chunks) - 1)
        self.assertTrue(any(is_quote), "the split quote is still quoted")
        self.assertFalse(is_quote[0])
        self.assertFalse(is_quote[-1])
