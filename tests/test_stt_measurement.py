"""Constructed scoring examples; no provider or human results."""
import unittest
from stt_measurement import measure


class STTMeasurementTests(unittest.TestCase):
    def measured(self, ref, hyp, **kwargs):
        return measure(ref, hyp, audio_seconds=2, wall_seconds=1, **kwargs)

    def test_known_substitution_and_insertion_counts(self):
        r=self.measured('a b c','a x c d')
        self.assertEqual((r['substitutions'],r['deletions'],r['insertions']),(1,0,1))
        self.assertEqual(r['raw_score']['reference_words'],3)
        self.assertAlmostEqual(r['raw_score']['corpus_wer'],2/3)

    def test_empty_raw_is_all_deletions_not_a_perfect_silence_score(self):
        r=self.measured('one two','')
        self.assertEqual(r['deletions'],2)
        self.assertEqual(r['raw_score']['corpus_wer'],1)

    def test_numeric_spelling_is_never_rewritten(self):
        r=self.measured('хоёр мянга хорин тав','2025')
        self.assertEqual(r['raw_score']['word_edit_errors'],4)
        self.assertIsNone(r['critical_semantic_judgments'])
        self.assertFalse(r['reference_or_numbers_rewritten'])

    def test_cyrillic_punctuation_normalization_matches_existing_scorer(self):
        r=self.measured('Сайн, байна уу?','сайн байна уу')
        self.assertEqual(r['raw_score']['word_edit_errors'],0)
        self.assertEqual(r['raw_score']['character_edit_errors'],0)

    def test_rtf_and_cache_remain_separate_from_accuracy(self):
        r=self.measured('a','a',provider_seconds=0,cache_hit=True)
        self.assertEqual(r['wall_rtf'],.5)
        self.assertTrue(r['cache_hit'])
        self.assertIsNone(r['human_task_success'])
        self.assertFalse(r['general_accuracy_claimed'])

    def test_invalid_or_nonfinite_durations_are_rejected(self):
        for values in [dict(audio_seconds=0,wall_seconds=1),dict(audio_seconds=31,wall_seconds=1),
                       dict(audio_seconds=1,wall_seconds=float('nan')),dict(audio_seconds=1,wall_seconds=-1),
                       dict(audio_seconds=True,wall_seconds=1),dict(audio_seconds=1,wall_seconds=1,provider_seconds=float('inf'))]:
            with self.subTest(values=values),self.assertRaises(ValueError):measure('a','a',**values)

    def test_pending_empty_reference_or_unbounded_text_is_rejected(self):
        for ref,hyp in [('', 'a'),('?', 'a'),('x'*1001,'a'),('a','x'*2001)]:
            with self.subTest(ref=ref[:4]),self.assertRaises(ValueError):self.measured(ref,hyp)

    def test_extra_year_is_reported_without_removing_it_or_changing_raw_score(self):
        result=self.measured('2014 онд 2024-2025','2014 онд 2020 онд 2024-2025')
        self.assertEqual(result['year_token_comparison']['additional_in_raw'],['2020'])
        self.assertEqual(result['raw_score']['word_edit_errors'],2)
        self.assertFalse(result['year_token_comparison']['semantic_correctness_judged'])

    def test_year_words_are_left_for_review_instead_of_declared_wrong(self):
        result=self.measured('2025 он','хоёр мянга хорин таван он')
        years=result['year_token_comparison']
        self.assertEqual(years['missing_in_raw'],['2025'])
        self.assertFalse(years['spoken_number_words_interpreted'])

