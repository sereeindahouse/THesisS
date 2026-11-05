"""FAKE-only speaker codes/text. No file, audio, credential or transport access."""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
import unittest

from tools.new_speaker_stt_scoring import ARMS, MODEL, reference_year_slots, summarize


def row(clip='FAKE01', speaker='FAKE_S01', reference='ЗОХИОМОЛ лаборатори хоёр мянга хорин зургаан онд нээгдэнэ.', **extra):
    return dict(clip_id=clip, speaker_code=speaker, consent=True, question_id='FAKE_Q01',
                reference_text=reference, audio_path='FAKE_NOT_OPENED.wav', **extra)


def result(source, arm, text=None, **extra):
    return dict(clip_id=source['clip_id'], speaker_code=source['speaker_code'], arm=arm,
                text=source['reference_text'] if text is None else text, model=MODEL, **extra)


def pairs(source, raw=None, clean=None):
    return [result(source, ARMS[0], raw), result(source, ARMS[1], clean)]


class ReferenceYearTests(unittest.TestCase):
    def test_spoken_year_and_digit_repetition_count_once_by_value(self):
        slots = reference_year_slots('ЗОХИОМОЛ хоёр мянга хорин зургаан он, 2026 он.')
        self.assertEqual(len(slots), 1)
        self.assertEqual(slots[0]['expected'], 'хоёр мянга хорин зургаан')
        self.assertEqual(slots[0]['field'], 'year_automatic')

    def test_ranges_keep_two_distinct_values(self):
        for reference in ('ЗОХИОМОЛ 2024–2025 он.',
                          'ЗОХИОМОЛ хоёр мянга хорин дөрвөн, хоёр мянга хорин таван он.'):
            with self.subTest(reference_kind=reference.startswith('ЗОХИОМОЛ 20')):
                self.assertEqual(len(reference_year_slots(reference)), 2)

    def test_invalid_number_tail_is_not_a_year_prefix(self):
        self.assertEqual(reference_year_slots('ЗОХИОМОЛ хоёр мянга хорин зургаан зуун.'), [])

    def test_name_phone_and_larger_digit_run_are_not_invented_slots(self):
        self.assertEqual(reference_year_slots('ЗОХИОМОЛ 20260 лаборатори 99991111.'), [])


class ScoringTests(unittest.TestCase):
    def test_strict_and_value_wer_are_separate_and_years_match_by_meaning(self):
        source = row()
        output = 'ЗОХИОМОЛ лаборатори 2026 онд нээгдэнэ.'
        data = summarize([source], pairs(source, output, output), ['лаборатори'])
        scored = data['summary']['overall']['arms'][ARMS[0]]
        self.assertGreater(scored['word_edit_errors'], 0)
        self.assertEqual(scored['value_wer']['word_edit_errors'], 0)
        self.assertEqual(scored['year_values'], dict(found=1, total=1, pending=0))
        self.assertEqual(scored['critical_values']['found'], 1)
        self.assertEqual(data['summary']['critical_slot_origins'], {'reference_derived_year_candidates': 1})
        self.assertFalse(data['summary']['human_critical_review_claimed'])

    def test_model_rejects_other_provider_without_echo(self):
        source = row()
        records = pairs(source)
        records[0]['model'] = 'FAKE_OTHER_MODEL'
        with self.assertRaisesRegex(ValueError, '^result_model_mismatch$'):
            summarize([source], records, [])

    def test_successful_empty_text_is_real_deletions_not_failure(self):
        source = row(reference='ЗОХИОМОЛ лаборатори')
        summary = summarize([source], pairs(source, '', ''), [])['summary']
        self.assertEqual(summary['paired_clips'], 1)
        self.assertEqual(summary['overall']['failed_records'], 0)
        for arm in ARMS:
            self.assertEqual(summary['overall']['arms'][arm]['word_edit_errors'], 2)
            self.assertEqual(summary['overall']['arms'][arm]['edit_counts']['D'], 2)

    def test_error_never_becomes_successful_empty_or_partial_text(self):
        source = row()
        records = [result(source, ARMS[0]), result(source, ARMS[1], '', error='http_429')]
        summary = summarize([source], records, [])['summary']
        self.assertEqual(summary['paired_clips'], 0)
        self.assertEqual(summary['overall']['failed_records'], 1)
        self.assertEqual(summary['overall']['unpaired_clips'], 1)
        self.assertIsNone(summary['overall']['arms'][ARMS[0]])
        self.assertIsNone(summary['cleanup_regression_detected'])

    def test_incomplete_attempt_is_reported_and_not_scored(self):
        source = row()
        records = [dict(clip_id=source['clip_id'], speaker_code=source['speaker_code'], arm=ARMS[0], status='started')]
        summary = summarize([source], records, [])['summary']
        self.assertEqual(summary['overall']['incomplete_records'], 1)
        self.assertEqual(summary['overall']['failed_records'], 0)
        self.assertEqual(summary['overall']['paired_clips'], 0)

    def test_duplicate_success_cannot_silently_replace_raw(self):
        source = row()
        records = pairs(source) + [result(source, ARMS[0], 'FAKE changed')]
        with self.assertRaisesRegex(ValueError, '^duplicate_successful_case$'):
            summarize([source], records, [])

    def test_previous_failure_is_not_overwritten_when_a_success_exists(self):
        source = row()
        records = [result(source, ARMS[0], '', error='fake_failed')] + pairs(source)
        summary = summarize([source], records, [])['summary']
        self.assertEqual(summary['paired_clips'], 1)
        self.assertEqual(summary['overall']['records'], 3)
        self.assertEqual(summary['overall']['failed_records'], 1)

    def test_each_speaker_uses_own_same_paired_cohort(self):
        a, b, missing = row('FAKE01','FAKE_S01'), row('FAKE02','FAKE_S02'), row('FAKE03','FAKE_S02')
        records = pairs(a) + pairs(b) + [result(missing, ARMS[0])]
        summary = summarize([a,b,missing], records, [])['summary']
        self.assertEqual(summary['speaker_count'], 2)
        self.assertEqual(summary['paired_clips'], 2)
        self.assertEqual(summary['overall']['unpaired_clips'], 1)
        self.assertEqual(summary['per_speaker']['FAKE_S01']['paired_clips'], 1)
        self.assertEqual(summary['per_speaker']['FAKE_S02']['paired_clips'], 1)
        self.assertEqual(summary['per_speaker']['FAKE_S02']['unpaired_clips'], 1)

    def test_global_aggregate_cannot_hide_a_speaker_regression(self):
        a, b = row('FAKE01','FAKE_S01','ЗОХИОМОЛ лаборатори'), row('FAKE02','FAKE_S02','ЗОХИОМОЛ лаборатори')
        records = pairs(a, clean='ЗОХИОМОЛ өөр') + pairs(b, raw='ЗОХИОМОЛ өөр')
        summary = summarize([a,b], records, [])['summary']
        self.assertEqual(summary['overall']['cleanup_effect']['strict_word_error_delta'], 0)
        self.assertEqual(summary['cleanup_regressed_speakers'], ['FAKE_S01'])
        self.assertTrue(summary['cleanup_regression_detected'])
        self.assertEqual(summary['per_speaker']['FAKE_S01']['cleanup_effect']['strict_word_error_delta'], 1)
        self.assertFalse(summary['per_speaker']['FAKE_S02']['cleanup_effect']['regressed'])

    def test_year_loss_is_shown_separately_from_formatting(self):
        source = row()
        records = pairs(source, raw='ЗОХИОМОЛ лаборатори 2026 онд нээгдэнэ.',
                        clean='ЗОХИОМОЛ лаборатори 2025 онд нээгдэнэ.')
        effect = summarize([source], records, [])['summary']['overall']['cleanup_effect']
        self.assertEqual(effect['year_value_new_misses'], 1)
        self.assertEqual(effect['critical_span_new_misses'], 1)
        self.assertTrue(effect['regressed'])

    def test_explicit_critical_slots_are_not_claimed_human_review(self):
        source = row(reference='ЗОХИОМОЛ лаборатори.', critical_slots=[dict(field='school_term', expected='лаборатори')])
        summary = summarize([source], pairs(source), ['лаборатори'])['summary']
        self.assertEqual(summary['critical_slot_origins'], {'manifest_explicit_not_independently_reviewed': 1})
        self.assertEqual(summary['overall']['arms'][ARMS[0]]['critical_values']['total'], 1)

    def test_critical_slot_must_be_in_reference(self):
        source = row(critical_slots=[dict(field='year', expected='2099')])
        with self.assertRaisesRegex(ValueError, '^critical_span_not_in_reference$'):
            summarize([source], pairs(source), [])

    def test_no_year_candidates_gives_zero_denominator_not_accuracy(self):
        source = row(reference='ЗОХИОМОЛ лаборатори.')
        metrics = summarize([source], pairs(source), [])['summary']['overall']['arms'][ARMS[0]]
        self.assertEqual(metrics['year_values'], dict(found=0,total=0,pending=0))

    def test_unknown_result_or_speaker_is_rejected(self):
        source = row()
        for updates, code in (({'clip_id':'FAKE_UNKNOWN'}, 'undeclared_result_case'),
                              ({'speaker_code':'FAKE_OTHER'}, 'result_speaker_mismatch'),
                              ({'arm':'fake_other'}, 'undeclared_result_case')):
            with self.subTest(code=code):
                record = dict(result(source, ARMS[0]), **updates)
                with self.assertRaisesRegex(ValueError, '^'+code+'$'):
                    summarize([source], [record], [])

    def test_no_input_mutation_no_print_and_no_text_in_public_summary(self):
        source = row(reference='ЗОХИОМОЛ НУУЦ ӨГҮҮЛБЭР лаборатори 2026 онд.')
        records = pairs(source, raw='ЗОХИОМОЛ НУУЦ ГАРАЛТ лаборатори 2026 онд.')
        originals = deepcopy(([source], records))
        captured = io.StringIO()
        with redirect_stdout(captured), redirect_stderr(captured):
            output = summarize([source], records, ['лаборатори'])
        self.assertEqual(captured.getvalue(), '')
        self.assertEqual(([source],records), originals)
        public = json.dumps(output['summary'], ensure_ascii=False)
        for private in (source['reference_text'], records[0]['text'], 'НУУЦ'):
            self.assertNotIn(private, public)
        self.assertIn('alignment', json.dumps(output['private_rows'], ensure_ascii=False))

    def test_corpus_totals_are_weighted_not_mean_speaker_score(self):
        a, b = row('FAKE01','FAKE_S01','ЗОХИОМОЛ'), row('FAKE02','FAKE_S02','ЗОХИОМОЛ лаборатори мэдээлэл')
        records = pairs(a, clean='өөр') + pairs(b)
        summary = summarize([a,b],records,[])['summary']
        self.assertEqual(summary['overall']['arms'][ARMS[1]]['corpus_wer'], .25)
        self.assertEqual(summary['macro_speaker_metrics'][ARMS[1]]['strict_wer'], .5)

    def test_empty_rows_and_duplicate_ids_fail_with_bounded_messages(self):
        with self.assertRaisesRegex(ValueError, '^scoring_requires_manifest_rows$'):
            summarize([],[],[])
        source = row()
        with self.assertRaisesRegex(ValueError, '^invalid_scoring_row$'):
            summarize([source,dict(source,clip_id='fake01')],[],[])


if __name__ == '__main__':
    unittest.main()
