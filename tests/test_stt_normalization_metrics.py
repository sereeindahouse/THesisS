"""All sentences, names and IDs are invented FAKE fixtures; no local evidence read."""
from copy import deepcopy
import io
from contextlib import redirect_stdout
import unittest

from score import distance, normalize
from tools.stt_normalization_metrics import (MODEL, annotate_reference, critical_values,
    paired_inputs, score_texts, word_alignment)


def fixture(reference='Зохиомол лаборатори хоёр мянга хорин зургаан онд нээлттэй.'):
    row = dict(id='FAKE-1', reference=reference, reference_status='eligible_speaker_confirmed',
        critical_slots=[dict(field='year', expected='хоёр мянга хорин зургаан')])
    manifest = dict(human_rows=[row], control_rows=[])
    saved = [dict(id='FAKE-1', arm=arm, model=MODEL, text=reference) for arm in ('baseline', 'vocabulary')]
    return manifest, saved


class PairedInputTests(unittest.TestCase):
    def test_pairing_preserves_manifest_order_and_inputs(self):
        manifest, saved = fixture()
        before = deepcopy((manifest, saved))
        captured = paired_inputs(manifest, saved, expected_count=1)
        self.assertEqual(captured['cohort']['paired_clips'], 1)
        self.assertEqual((manifest, saved), before)
        captured['rows'][0]['reference'] = 'FAKE derivative only'
        self.assertEqual((manifest, saved), before)

    def test_failure_is_not_empty_success(self):
        manifest, saved = fixture()
        saved[-1] = dict(id='FAKE-1', arm='vocabulary', error='FAKE unavailable')
        with self.assertRaisesRegex(ValueError, 'cohort size'):
            paired_inputs(manifest, saved, expected_count=1)

    def test_successful_empty_text_is_kept(self):
        manifest, saved = fixture()
        saved[-1]['text'] = ''
        captured = paired_inputs(manifest, saved, expected_count=1)
        self.assertEqual(captured['texts']['vocabulary']['FAKE-1'], '')

    def test_failed_attempt_then_success_are_not_duplicate_success(self):
        manifest, saved = fixture()
        saved.insert(0, dict(id='FAKE-1', arm='baseline', error='FAKE error'))
        captured = paired_inputs(manifest, saved, expected_count=1)
        self.assertEqual(captured['cohort']['failed_records'], 1)

    def test_duplicate_success_rejected(self):
        manifest, saved = fixture()
        saved.append(deepcopy(saved[0]))
        with self.assertRaisesRegex(ValueError, 'Duplicate successful'):
            paired_inputs(manifest, saved, expected_count=1)

    def test_wrong_model_rejected(self):
        manifest, saved = fixture()
        saved[0]['model'] = 'FAKE other model'
        with self.assertRaisesRegex(ValueError, 'different model'):
            paired_inputs(manifest, saved, expected_count=1)

    def test_unconfirmed_reference_rejected(self):
        manifest, saved = fixture()
        manifest['human_rows'][0]['reference_status'] = 'draft'
        with self.assertRaisesRegex(ValueError, 'confirmed'):
            paired_inputs(manifest, saved, expected_count=1)

    def test_incomplete_record_count_and_unpaired_exclusion(self):
        manifest, saved = fixture()
        other = dict(manifest['human_rows'][0], id='FAKE-2')
        manifest['human_rows'].append(other)
        saved.extend([dict(id='FAKE-2', arm='baseline', model=MODEL, text='Зохиомол.'),
                      dict(id='FAKE-2', arm='vocabulary', model=MODEL)])
        captured = paired_inputs(manifest, saved, expected_count=1)
        self.assertEqual(captured['cohort']['incomplete_records'], 1)
        self.assertEqual(captured['cohort']['excluded'], [dict(id='FAKE-2', missing_arms=['vocabulary'])])


class AlignmentTests(unittest.TestCase):
    def test_counts_equal_word_distance(self):
        for ref, hyp in [('нэг хоёр гурав', 'нэг дөрөв'), ('зохиомол', ''), ('', 'зохиомол'),
                         ('а б', 'б а'), ('сайн уу', 'Сайн, уу!')]:
            with self.subTest(kind=len(ref) + len(hyp)):
                events = word_alignment(ref, hyp)
                self.assertEqual(sum(event['op'] != '=' for event in events),
                    distance(normalize(ref).split(), normalize(hyp).split()))

    def test_tie_prefers_diagonal_and_is_stable(self):
        first = word_alignment('зохиомол үг', 'үг зохиомол')
        self.assertEqual([event['op'] for event in first], ['S', 'S'])
        self.assertEqual(first, word_alignment('зохиомол үг', 'үг зохиомол'))

    def test_punctuation_and_case_follow_existing_scorer(self):
        self.assertEqual([event['op'] for event in word_alignment('ЗОХИОМОЛ, үг!', 'зохиомол үг')], ['=', '='])


class CriticalValueTests(unittest.TestCase):
    def test_spoken_year_and_digit_value_are_equivalent_both_directions(self):
        a = critical_values([dict(field='year', expected='хоёр мянга хорин зургаан')], 'Зохиомол 2026 онд.')
        b = critical_values([dict(field='year', expected='2026')], 'Зохиомол хоёр мянга хорин зургаан онд.')
        self.assertEqual((a['found'], b['found']), (1, 1))
        self.assertEqual((a['literal_found'], b['literal_found']), (0, 0))

    def test_year_is_not_embedded_in_larger_number(self):
        for expected in ('2026', 'хоёр мянга хорин зургаан'):
            self.assertEqual(critical_values([dict(field='year', expected=expected)], '20260')['found'], 0)

    def test_name_requires_whole_tokens(self):
        slots = [dict(field='company', expected='FAKECORP')]
        self.assertEqual(critical_values(slots, 'FAKECORPORATION')['found'], 0)
        self.assertEqual(critical_values(slots, 'Зохиомол FAKECORP!')['found'], 1)

    def test_pending_slot_stays_out_of_denominator(self):
        result = critical_values([dict(field='year_literal_uncertain', expected='2026')], '2026')
        self.assertEqual((result['found'], result['total'], result['pending']), (0, 0, 1))
        self.assertIsNone(result['records'][0]['found'])

    def test_invalid_slots_raise_static_error(self):
        with self.assertRaisesRegex(ValueError, 'Critical slots'):
            critical_values([dict(field='year', expected='')], 'FAKE')


class AnnotationAndScoringTests(unittest.TestCase):
    def test_priority_number_name_term_other(self):
        reference = '2026 Зохиомол Наран лаборатори нээлттэй'
        slots = [dict(field='teacher_name', expected='Зохиомол Наран')]
        annotation = annotate_reference(reference, slots, ['2026', 'Зохиомол Наран', 'лаборатори'])
        self.assertEqual([label['category'] for label in annotation['labels']],
            ['number_year', 'name', 'name', 'school_term', 'other'])
        self.assertEqual(annotation['terms'], ['лаборатори'])

    def test_longest_configured_term_wins(self):
        annotation = annotate_reference('зохиомол компьютерын лаборатори', [],
                                        ['лаборатори', 'компьютерын лаборатори'])
        self.assertEqual(annotation['terms'], ['компьютерын лаборатори'])

    def test_category_and_sdi_totals_equal_total_word_errors(self):
        manifest, _ = fixture()
        rows = manifest['human_rows']
        annotations = {'FAKE-1': annotate_reference(rows[0]['reference'], rows[0]['critical_slots'], ['лаборатори'])}
        result = score_texts(rows, {'FAKE-1': 'Зохиомол лабортори 2026 онд БИШ нээлттэй.'}, annotations, ['лаборатори'])
        self.assertEqual(sum(result['error_categories'].values()), result['word_edit_errors'])
        self.assertEqual(sum(result['edit_counts'].values()), result['word_edit_errors'])
        self.assertEqual(result['critical_values']['found'], 1)
        self.assertEqual(result['school_term_errors'], [dict(term='лаборатори', clips=1, error_events=1)])

    def test_year_normalization_can_raise_literal_errors_without_value_loss(self):
        manifest, saved = fixture()
        rows = manifest['human_rows']
        annotations = {'FAKE-1': annotate_reference(rows[0]['reference'], rows[0]['critical_slots'], [])}
        raw = score_texts(rows, {'FAKE-1': saved[0]['text']}, annotations, [])
        derivative = score_texts(rows, {'FAKE-1': saved[0]['text'].replace('хоёр мянга хорин зургаан', '2026')}, annotations, [])
        self.assertGreater(derivative['word_edit_errors'], raw['word_edit_errors'])
        self.assertEqual((raw['critical_values']['found'], derivative['critical_values']['found']), (1, 1))

    def test_empty_success_scores_deletions(self):
        row = dict(id='FAKE-1', reference='зохиомол лаборатори', critical_slots=[])
        annotations = {'FAKE-1': annotate_reference(row['reference'], [], ['лаборатори'])}
        result = score_texts([row], {'FAKE-1': ''}, annotations, ['лаборатори'])
        self.assertEqual(result['edit_counts'], dict(S=0, D=2, I=0))

    def test_insertion_classification_uses_number_name_then_term(self):
        row = dict(id='FAKE-1', reference='Зохиомол Наран ирсэн',
                   critical_slots=[dict(field='teacher_name', expected='Зохиомол Наран')])
        annotations = {'FAKE-1': annotate_reference(row['reference'], row['critical_slots'], ['лаборатори'])}
        result = score_texts([row], {'FAKE-1': '2026 лаборатори Зохиомол Наран Наран ирсэн'}, annotations, ['лаборатори'])
        self.assertEqual(result['error_categories']['number_year'], 1)
        self.assertEqual(result['error_categories']['school_term'], 1)
        self.assertEqual(result['error_categories']['name'], 1)

    def test_changed_frozen_reference_annotation_rejected(self):
        row = dict(id='FAKE-1', reference='зохиомол', critical_slots=[])
        annotation = annotate_reference(row['reference'], [], [])
        annotation['tokens'] = ['өөрчлөгдсөн']
        with self.assertRaisesRegex(ValueError, 'Frozen annotation'):
            score_texts([row], {'FAKE-1': 'зохиомол'}, {'FAKE-1': annotation}, [])

    def test_no_printing_or_input_mutation(self):
        manifest, saved = fixture()
        before = deepcopy((manifest, saved))
        output = io.StringIO()
        with redirect_stdout(output):
            captured = paired_inputs(manifest, saved, expected_count=1)
            rows = captured['rows']
            annotations = {row['id']: annotate_reference(row['reference'], row['critical_slots'], ['лаборатори']) for row in rows}
            score_texts(rows, captured['texts']['vocabulary'], annotations, ['лаборатори'])
        self.assertEqual(output.getvalue(), '')
        self.assertEqual((manifest, saved), before)


if __name__ == '__main__':
    unittest.main()
