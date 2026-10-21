"""Value-preservation checks for bounded speech formatting, not listening scores."""
import copy
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from answer_contract import spoken_text
from speech_text import (normalize_spoken_notation, normalize_spoken_years_and_phones,
                         normalize_spoken_educational_acronyms)
from tools.evaluate_speech_delivery import CASES, evaluate


class SpeechDeliveryTests(unittest.TestCase):
    def test_reviewed_educational_acronym_keeps_noun_and_possessive_grammar(self):
        examples = {
            'ЕБС': 'ерөнхий боловсролын сургууль',
            'ЕБС-ийн': 'ерөнхий боловсролын сургуулийн',
            'ЕБС.': 'ерөнхий боловсролын сургууль.',
            'ЕБС?': 'ерөнхий боловсролын сургууль?',
            '«ЕБС-ийн»': '«ерөнхий боловсролын сургуулийн»',
            'ЕБС, ЕБС-ийн!': 'ерөнхий боловсролын сургууль, ерөнхий боловсролын сургуулийн!',
        }
        for before, expected in examples.items():
            with self.subTest(before=before):
                self.assertEqual(normalize_spoken_educational_acronyms(before), expected)

    def test_observed_task_acronym_failure_has_exact_spoken_only_fix(self):
        # This literal sentence reproduced the observed ЕБС-ийн listening issue.
        # The test checks exact rendering, not a new listening/quality score.
        original = dict(answer='1-р курст Бүртгүүлэгч нь ЕБС-ийн 9-р ангийг төгсөж '
                        'суурь боловсролын гэрчилгээ авсан сурагч байна. [1]',
                        answer_kind='rag_generated', citations=[{'document_id':'test-source'}])
        frozen = copy.deepcopy(original)
        self.assertEqual(spoken_text(original),
            '1-р курст Бүртгүүлэгч нь ерөнхий боловсролын сургуулийн 9-р ангийг төгсөж '
            'суурь боловсролын гэрчилгээ авсан сурагч байна.')
        self.assertEqual(original, frozen)

    def test_unsupported_acronym_suffixes_case_compounds_and_ids_remain_literal(self):
        examples = (
            'ебс', 'Ебс', 'еБС', 'ЕБс', 'ЕБСийн', 'ЕБС-д', 'ЕБС-ээс',
            'ЕБС-ийг', 'ЕБС-ний', 'ЕБС-ийнхэн', 'ЕБС_ийн', 'ЕБС-001',
            'ЕБС2026', '2026ЕБС', 'ABCЕБС', 'ЕБСABC', 'ЕБС-ийн9',
            'ЕБС/МСҮТ', 'ЕБС–МСҮТ', 'ЕБС -ийн', 'ЕБС – ийн',
            'ЕБС - МСҮТ', 'МСҮТ - ЕБС', 'ЕБС-ийн/9', 'ЕБС-ийн-9',
            'https://example.org/ЕБС', 'https://ЕБС.mn', 'ЕБС.mn',
            'https://example.org/?type=ЕБС', 'ЕБС?type=1', 'ЕБС:42',
            '@ЕБС', '#ЕБС', '$ЕБС', 'ЕБС@example.org', 'МУИС, ШМТК, QR-25.',
        )
        for before in examples:
            with self.subTest(before=before):
                self.assertEqual(normalize_spoken_educational_acronyms(before), before)

    def test_acronym_expansion_preserves_unmatched_names_negation_numbers_and_spacing(self):
        before = 'Сора биш, Батаа\tЕБС-ийн 9-р ангийг төгсөөгүй. 2026; 20.5; 00112233!'
        expected = 'Сора биш, Батаа\tерөнхий боловсролын сургуулийн 9-р ангийг төгсөөгүй. 2026; 20.5; 00112233!'
        self.assertEqual(normalize_spoken_educational_acronyms(before), expected)

    def test_acronym_expansion_is_idempotent_with_other_spoken_formatting(self):
        text = '2026 оны ЕБС-ийн 9-р анги биш. ЕБС. Утас: 00112233. QR код.'
        once = normalize_spoken_notation(text)
        self.assertIn('ерөнхий боловсролын сургуулийн 9-р анги биш.', once)
        self.assertIn('ерөнхий боловсролын сургууль.', once)
        self.assertIn('хоёр мянга хорин зургаан оны', once)
        self.assertEqual(normalize_spoken_notation(once), once)

    def test_acronym_in_message_and_clarification_uses_same_spoken_rule(self):
        value = dict(message='ЕБС-ийн шаардлага.', clarification={'question':'ЕБС мөн үү?'})
        original = copy.deepcopy(value)
        self.assertEqual(spoken_text(value),
            'ерөнхий боловсролын сургуулийн шаардлага. ерөнхий боловсролын сургууль мөн үү?')
        self.assertEqual(value, original)

    def test_linking_calendar_year_forms_are_explicit(self):
        examples = {
            '2000 онд': 'хоёр мянган онд',
            '2001 оны': 'хоёр мянга нэгэн оны',
            '2002 он': 'хоёр мянга хоёр он',
            '2010 оны': 'хоёр мянга арван оны',
            '2011 оны': 'хоёр мянга арван нэгэн оны',
            '2021 оны': 'хоёр мянга хорин нэгэн оны',
            '2026 оны': 'хоёр мянга хорин зургаан оны',
            '2099 онд': 'хоёр мянга ерэн есөн онд',
        }
        for written, expected in examples.items():
            with self.subTest(written=written):
                self.assertEqual(normalize_spoken_years_and_phones(written), expected)

    def test_every_supported_year_has_the_same_independently_parsed_value(self):
        # Independent additive parser: the fixed prefix denotes 2000, and the
        # remaining tens/ones must recover the original year exactly.
        values = {'нэгэн': 1, 'хоёр': 2, 'гурван': 3, 'дөрвөн': 4, 'таван': 5,
                  'зургаан': 6, 'долоон': 7, 'найман': 8, 'есөн': 9,
                  'арван': 10, 'хорин': 20, 'гучин': 30, 'дөчин': 40, 'тавин': 50,
                  'жаран': 60, 'далан': 70, 'наян': 80, 'ерэн': 90}
        for year in range(2000, 2100):
            words = normalize_spoken_years_and_phones(f'{year} оны').split()
            self.assertEqual(words[:2], ['хоёр', 'мянган' if year == 2000 else 'мянга'])
            self.assertEqual(2000 + sum(values[word] for word in words[2:-1]), year)
            self.assertEqual(words[-1], 'оны')

    def test_eight_phone_digits_are_read_separately_and_keep_leading_zeros(self):
        self.assertEqual(normalize_spoken_years_and_phones('Утас: 00112233.'),
                         'Утас: тэг тэг нэг нэг, хоёр хоёр гурав гурав.')
        self.assertEqual(normalize_spoken_years_and_phones('Утасны дугаар 77123456.'),
                         'Утасны дугаар долоо долоо нэг хоёр, гурав дөрөв тав зургаа.')
        self.assertEqual(normalize_spoken_years_and_phones('УТАС: 98765432!'),
                         'УТАС: ес найм долоо зургаа, тав дөрөв гурав хоёр!')

    def test_phone_order_is_reversible_for_all_digits_in_multiple_positions(self):
        values = dict(zip('тэг нэг хоёр гурав дөрөв тав зургаа долоо найм ес'.split(), '0123456789'))
        for offset in range(100):
            number = ''.join(str((offset + i * 3) % 10) for i in range(8))
            result = normalize_spoken_years_and_phones('Утас: ' + number)[6:]
            recovered = ''.join(values[word] for word in re.findall(r'\w+', result))
            self.assertEqual(recovered, number)

    def test_dates_year_ranges_and_outside_scope_years_stay_literal(self):
        examples = (
            '2026-10-20', '2026/10/20', '2026 оны 10-р сарын 20',
            '2026 оны 10 сарын 20', '2026 оны 10 дугаар сарын 20',
            '2026 оны аравдугаар сарын 20', '2026 оны арван нэгдүгээр сарын 20',
            '2025–2026 оны', '2025 - 2026 оны', '2025 / 2026 оны',
            '2025 оны – 2026 оны', '1999 оны', '2100 онд', '2026',
            'M2026 оны код', '2026.5 оны', '-2026 оны', '+2026 оны', '02026 оны',
        )
        for text in examples:
            with self.subTest(text=text):
                self.assertEqual(normalize_spoken_years_and_phones(text), text)

    def test_unknown_phone_forms_ranges_codes_and_decimals_stay_literal(self):
        examples = (
            '77123456', 'Код: 77123456', 'утасны загвар 77123456',
            'Утас: +976 77123456', 'Утас: 7712-3456', 'Утас: 7712 3456',
            'Утас: 7712345', 'Утас: 771234567', 'Утас: 77123456-1',
            'Утас: 77123456 - 88123456', 'Утас: 77123456/88123456',
            'Утас: 77123456.5', 'Утас: 77123456,5', 'Утас: 77123456abc',
            'Утас: 77123456 төгрөг', 'Утас: 77123456 ₮', 'Утас: ７７１２３４５６',
            'Утас: 77123456 123', 'Утас: 77123456 дотуур 123',
            'Утас: 77123456 ext 12', 'Утас: 77123456, 88123456',
            'Утас: 77123456.example',
            'Утас12345678/87654321', 'Утас 12345678/87654321 биш',
            'Утас: 12345678 – 87654321 биш',
        )
        for text in examples:
            with self.subTest(text=text):
                self.assertEqual(normalize_spoken_years_and_phones(text), text)

    def test_name_negation_and_all_unmatched_spans_are_exact(self):
        before = 'Сора, Батаа, Есүй: өөрчлөгдөөгүй. '
        after = ' Хамрагдахгүй; 20.5, QR-25, үгүй!'
        self.assertEqual(normalize_spoken_years_and_phones(before + '2026 оны' + after),
                         before + 'хоёр мянга хорин зургаан оны' + after)
        self.assertEqual(normalize_spoken_years_and_phones(before + 'Утас: 77123456' + after),
                         before + 'Утас: долоо долоо нэг хоёр, гурав дөрөв тав зургаа' + after)

    def test_phone_and_year_negation_stays_in_its_original_position(self):
        self.assertEqual(normalize_spoken_years_and_phones('2026 оны биш. Утас: 12345678 биш.'),
                         'хоёр мянга хорин зургаан оны биш. '
                         'Утас: нэг хоёр гурав дөрөв, тав зургаа долоо найм биш.')

    def test_repeated_and_composed_normalization_is_idempotent(self):
        text = '2026 оны Сора биш. Утас: 00112233. QR код; 20,000 төгрөг.'
        once = normalize_spoken_notation(text)
        self.assertEqual(normalize_spoken_notation(once), once)
        self.assertIn('кью ар код', once)
        self.assertIn('20,000 төгрөг', once)

    def test_bound_answer_speech_changes_without_mutating_display_or_citations(self):
        result = dict(answer='2026 оны Сора биш. Утас: 00112233. [1]',
                      answer_kind='rag_generated', citations=[{'document_id': 'constructed'}])
        original = copy.deepcopy(result)
        spoken = spoken_text(result)
        self.assertEqual(spoken, 'хоёр мянга хорин зургаан оны Сора биш. '
                                'Утас: тэг тэг нэг нэг, хоёр хоёр гурав гурав.')
        self.assertEqual(result, original)

    def test_clarification_and_message_use_the_same_spoken_notation(self):
        self.assertEqual(spoken_text(dict(message='2026 оны эх.',
                                         clarification={'question': 'Утас: 00112233 мөн үү?'})),
                         'хоёр мянга хорин зургаан оны эх. '
                         'Утас: тэг тэг нэг нэг, хоёр хоёр гурав гурав мөн үү?')


class SpeechDeliveryEvaluatorTests(unittest.TestCase):
    def baseline(self, directory):
        rows = [dict(id=cid, type=kind, written=written, critical_values=critical,
                     source='assistant_constructed_not_school_fact',
                     spoken_before=expected if cid == 'currency_qr' else written)
                for cid, kind, written, critical, expected in CASES]
        path = Path(directory) / 'baseline.json'
        path.write_text(json.dumps(dict(constructed=True, cases=rows), ensure_ascii=False), encoding='utf-8')
        return path

    def test_offline_pair_does_not_synthesize_or_fill_human_results(self):
        with tempfile.TemporaryDirectory() as directory, patch(
                'tools.evaluate_speech_delivery._synthesize', side_effect=AssertionError('offline')):
            report = evaluate(Path(directory) / 'out', baseline_path=self.baseline(directory))
            self.assertEqual(report['summary']['cases'], 12)
            self.assertEqual(report['summary']['deterministic_checks_passed'], 12)
            self.assertEqual(report['summary']['changed_cases'], 6)
            self.assertEqual(report['provider_requests'], 0)
            self.assertIsNone(report['mos'])
            self.assertFalse(report['raw_stt_quality_measured'])
            self.assertTrue(all(row['human_heard_critical_values'] is None for row in report['cases']))

    def test_baseline_cannot_inject_other_text_into_online_before_audio(self):
        with tempfile.TemporaryDirectory() as directory, patch(
                'tools.evaluate_speech_delivery._synthesize', side_effect=AssertionError('unapproved text')):
            path = self.baseline(directory)
            value = json.loads(path.read_text(encoding='utf-8'))
            value['cases'][0]['spoken_before'] = 'Injected non-constructed text'
            path.write_text(json.dumps(value), encoding='utf-8')
            with self.assertRaises(ValueError):
                evaluate(Path(directory) / 'out', baseline_path=path, synthesize=True)
            self.assertFalse((Path(directory) / 'out').exists())

    def test_case_selection_cannot_add_text_or_unknown_voices(self):
        with tempfile.TemporaryDirectory() as directory:
            for kwargs in ({'case_ids': ['private-recording']}, {'voice_names': ['unknown']}):
                with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                    evaluate(Path(directory) / 'out', **kwargs)
            with self.assertRaises(ValueError):
                evaluate(Path(directory) / 'out', synthesize=True)
            self.assertFalse((Path(directory) / 'out').exists())

    def test_optional_provider_receives_the_exact_two_frozen_constructed_texts(self):
        calls = []

        def synthesize(text, voice, destination):
            calls.append((text, voice, destination.name))
            return dict(provider_request=True, decoded_seconds=1.0, exact_provider_text=text)

        with tempfile.TemporaryDirectory() as directory, patch(
                'tools.evaluate_speech_delivery._synthesize', side_effect=synthesize):
            report = evaluate(Path(directory) / 'out', baseline_path=self.baseline(directory),
                              synthesize=True, voice_names=('bataa',), case_ids=['combined'])
            case = next(row for row in CASES if row[0] == 'combined')
            self.assertEqual([item[0] for item in calls], [case[2], case[4]])
            self.assertTrue(all(item[1] == 'mn-MN-BataaNeural' for item in calls))
            self.assertEqual(report['summary']['audio_decodes_passed'], 2)
            self.assertIsNone(report['cases'][0]['human_listening_rating'])

    def test_output_directory_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'out'
            evaluate(output, case_ids=['date'])
            original = (output / 'results.json').read_bytes()
            with self.assertRaises(FileExistsError):
                evaluate(output, case_ids=['phone'])
            self.assertEqual((output / 'results.json').read_bytes(), original)

    def test_provider_failure_is_kept_and_cannot_become_a_listening_score(self):
        with tempfile.TemporaryDirectory() as directory, patch(
                'tools.evaluate_speech_delivery._synthesize',
                side_effect=[TimeoutError('synthetic provider error'),
                             dict(provider_request=True, decoded_seconds=1.0)]):
            report = evaluate(Path(directory) / 'out', baseline_path=self.baseline(directory),
                              synthesize=True, voice_names=('yesui',), case_ids=['year2026'])
            self.assertEqual(report['summary']['provider_attempts'], 2)
            self.assertEqual(report['summary']['audio_decodes_passed'], 1)
            before, after = report['cases'][0]['audio']
            self.assertFalse(before['success'])
            self.assertEqual(before['error_type'], 'TimeoutError')
            self.assertTrue(after['success'])
            self.assertFalse(report['listening_quality_measured'])
            self.assertIsNone(report['mos'])


if __name__ == '__main__':
    unittest.main()
