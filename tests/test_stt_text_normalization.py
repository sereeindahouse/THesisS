"""FAKE constructed text only; no audio, transcript, database, API or provider."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from stt_text_normalization import Normalizer, spoken_integer


class NumberNormalizationTests(unittest.TestCase):
    def setUp(self):
        self.normalizer = Normalizer(enabled=True, normalize_vocabulary=False)

    def output(self, text):
        return self.normalizer.normalize(text)['normalized_search_text']

    def test_fake_spoken_year_and_digits_have_one_form(self):
        self.assertEqual(self.output('Зохиомол клуб хоёр мянга хорин зургаан онд нээгдэв.'),
                         'Зохиомол клуб 2026 онд нээгдэв.')
        self.assertEqual(self.output('Зохиомол клуб 2026 онд нээгдэв.'),
                         'Зохиомол клуб 2026 онд нээгдэв.')

    def test_year_variants_follow_existing_year_grammar(self):
        tens = [('хорь', 20), ('хорин', 20), ('гуч', 30), ('гучин', 30), ('ерэн', 90)]
        for word, value in tens:
            for scale in ['мянга', 'мянган']:
                with self.subTest(word=word, scale=scale):
                    self.assertEqual(self.output(f'хоёр {scale} {word} зургаан онд'),
                                     f'{2000 + value + 6} онд')

    def test_fake_quantities_hundreds_thousands_and_zero(self):
        for phrase, number in [('хорин зургаан', 26), ('гурван зуун тавин хоёр', 352),
                               ('хоёр мянга гурван зуун арван нэгэн', 2311),
                               ('мянга', 1000), ('зуу', 100), ('тэг', 0), ('дөрвөн', 4)]:
            with self.subTest(phrase=phrase):
                self.assertEqual(self.output(phrase+' оюутан'), str(number)+' оюутан')

    def test_unrelated_case_spacing_and_negation_preserved(self):
        self.assertEqual(self.output('  ЗОХИОМОЛ\tхоёр мянга хорин зургаан онд БИШ,  үгүй!\n'),
                         '  ЗОХИОМОЛ\t2026 онд БИШ,  үгүй!\n')

    def test_ambiguous_sequences_and_incomplete_mixed_forms_unchanged(self):
        for text in ['нэг хоёр оюутан', 'хоёр мянга 26 онд', 'нэг нэг',
                     'хоёр зуу мянга мянга', 'хоёр хоёр мянга', 'нэг юм уу хоёр',
                     'нэг л өдөр', 'нэг зүйл хэлэхэд', 'тэг гэж хэлсэн']:
            with self.subTest(text=text):
                self.assertEqual(self.output(text), text)

    def test_inflected_tail_cannot_turn_a_year_prefix_into_the_wrong_year(self):
        for text in ['хоёр мянга хорин зургааны мэдээлэл',
                     'хоёр мянга хорин зургаанд', 'гурван зуун хорин тавын',
                     'хоёр мянга хорин зургаадугаар']:
            with self.subTest(text=text):
                self.assertEqual(self.output(text), text)

    def test_phone_code_url_email_decimal_and_existing_digits_unchanged(self):
        for text in ['Утас 99112233, код 002026, 2026-11-04.',
                     'https://example.invalid/хоёр/мянга',
                     'хоёр@example.invalid', '`хоёр мянга хорин зургаан`',
                     'ABC-хорин зургаан', 'хорин зургаан/дугаар',
                     'хорин зургаан:гучин хоёр', 'хоёр.таван', '2.5 хувь']:
            with self.subTest(text=text):
                self.assertEqual(self.output(text), text)

    def test_original_offsets_and_unmodified_gaps_reconstruct(self):
        text = 'Зохиомол: хоёр мянга хорин зургаан онд, дөрвөн багш БИШ!'
        result = self.normalizer.normalize(text)
        self.assertEqual(result['original_text'], text)
        self.assertTrue(result['changed'])
        self.assertEqual(len(result['replacements']), 2)
        for item in result['replacements']:
            self.assertEqual(text[item['start']:item['end']], item['original'])
        rebuilt, position = [], 0
        for item in result['replacements']:
            rebuilt += [text[position:item['start']], item['replacement']]
            position = item['end']
        rebuilt.append(text[position:])
        self.assertEqual(''.join(rebuilt), result['normalized_search_text'])

    def test_idempotent_and_bounded(self):
        first = self.output('Зохиомол хоёр мянга хорин зургаан онд, хорин хоёр хүн.')
        self.assertEqual(self.output(first), first)
        huge = 'хоёр мянга хорин зургаан онд ' * 100
        result = self.normalizer.normalize(huge)
        self.assertEqual(result['normalized_search_text'], huge)
        self.assertEqual(result['reason'], 'text_exceeds_bound')

    def test_plain_integer_parser_rejects_non_number_words(self):
        self.assertIsNone(spoken_integer(['хоёр', 'туслах']))
        self.assertIsNone(spoken_integer([]))
        self.assertIsNone(spoken_integer(['тэг', 'мянга']))


class VocabularyNormalizationTests(unittest.TestCase):
    def setUp(self):
        # Entirely FAKE vocabulary; no school facts or actual transcripts.
        self.normalizer = Normalizer(enabled=True, terms=['Зохиомолын лаборатори', 'Фотоникийн тэнхим'])

    def output(self, text):
        return self.normalizer.normalize(text)['normalized_search_text']

    def test_unique_one_character_typo_becomes_exact_configured_term(self):
        text = 'Үгүй, Зохиомолын лаборатоори хаана вэ?'
        self.assertEqual(self.output(text), 'Үгүй, Зохиомолын лаборатори хаана вэ?')

    def test_exact_terms_case_and_nonvocabulary_words_stay_unchanged(self):
        for text in ['зохиомолын лаборатори ХААНА вэ?',
                     'фотоникийн тэнхим', 'Миний бичсээн буруу үгээ засахгүй.',
                     'Зохиомолын лабораторид хаана вэ?']:
            with self.subTest(text=text):
                self.assertEqual(self.output(text), text)

    def test_distant_typos_short_words_and_acronyms_not_guessed(self):
        normalizer = Normalizer(enabled=True, terms=['NMCT', 'Коосэн', 'Зохиомолын лаборатори'])
        for text in ['NMKT', 'Косэн', 'Зохиомолын лортори', 'Зохиомолын лабртории']:
            with self.subTest(text=text):
                self.assertEqual(normalizer.normalize(text)['normalized_search_text'], text)

    def test_ambiguous_close_targets_abstain(self):
        normalizer = Normalizer(enabled=True, terms=['лабораторий', 'лабораториз'])
        self.assertEqual(normalizer.normalize('лабораториа')['normalized_search_text'], 'лабораториа')

    def test_term_boundary_no_substring_or_punctuation_crossing(self):
        for text in ['Зохиомолын-лаборатоори', 'XXЗохиомолын лаборатоори',
                     '`Зохиомолын лаборатоори`', 'https://fake.invalid/лаборатоори']:
            with self.subTest(text=text):
                self.assertEqual(self.output(text), text)

    def test_combined_derivative_is_idempotent(self):
        first = self.normalizer.normalize('Зохиомолын лаборатоори хоёр мянга хорин зургаан онд БИШ.')
        self.assertEqual(first['normalized_search_text'], 'Зохиомолын лаборатори 2026 онд БИШ.')
        self.assertEqual([item['kind'] for item in first['replacements']], ['vocabulary', 'number'])
        again = self.normalizer.normalize(first['normalized_search_text'])
        self.assertFalse(again['changed'])
        self.assertEqual(again['normalized_search_text'], first['normalized_search_text'])


class ConfigurationTests(unittest.TestCase):
    def test_default_file_is_off(self):
        config = json.loads((Path(__file__).resolve().parents[1] / 'config/stt-text-normalization.json').read_text(encoding='utf-8'))
        self.assertIs(config['enabled'], False)

    def test_disabled_feature_does_not_read_vocabulary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root/'config').mkdir()
            (root/'config/stt-text-normalization.json').write_text('{"schema_version":1,"enabled":false}')
            value = Normalizer.from_config(root)
            self.assertFalse(value.enabled)
            self.assertEqual(value.normalize('хоёр мянга хорин зургаан')['normalized_search_text'], 'хоёр мянга хорин зургаан')

    def test_enabled_config_reads_only_fixed_terms_and_preserves_model(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root/'config').mkdir()
            (root/'config/stt-text-normalization.json').write_text('{"schema_version":1,"enabled":true}')
            path = root/'config/stt-vocabulary.json'
            path.write_text(json.dumps(dict(model='fake-model-unchanged', terms=['Зохиомолын лаборатори'],
                                            measurement={'run':'runtime/NEVER_READ'})), encoding='utf-8')
            before = path.read_bytes()
            value = Normalizer.from_config(root)
            self.assertTrue(value.enabled)
            self.assertEqual(value.normalize('Зохиомолын лаборатоори')['normalized_search_text'], 'Зохиомолын лаборатори')
            self.assertEqual(path.read_bytes(), before)

    def test_missing_or_malformed_config_fails_closed(self):
        cases = ['[]', '{"enabled":true}', '{"schema_version":1,"enabled":"yes"}',
                 '{"schema_version":1,"enabled":true,"vocabulary_path":"runtime/private"}',
                 '{"schema_version":true,"enabled":true}',
                 '{"schema_version":1,"enabled":true,"normalize_numbers":1}']
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root/'config').mkdir()
            self.assertFalse(Normalizer.from_config(root).enabled)
            for content in cases:
                with self.subTest(content=content):
                    (root/'config/stt-text-normalization.json').write_text(content)
                    self.assertFalse(Normalizer.from_config(root).enabled)

    def test_bad_vocabulary_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root/'config').mkdir()
            (root/'config/stt-text-normalization.json').write_text('{"schema_version":1,"enabled":true}')
            for vocabulary in [[], {'terms':['valid', None]}, {'terms':'bad'}, {'terms':['x']*1001}]:
                with self.subTest(vocabulary=str(vocabulary)[:40]):
                    (root/'config/stt-vocabulary.json').write_text(json.dumps(vocabulary))
                    self.assertFalse(Normalizer.from_config(root).enabled)

    def test_number_only_config_needs_no_vocabulary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root/'config').mkdir()
            (root/'config/stt-text-normalization.json').write_text(
                '{"schema_version":1,"enabled":true,"normalize_vocabulary":false}')
            self.assertEqual(Normalizer.from_config(root).normalize('хорин хоёр хүн')['normalized_search_text'], '22 хүн')

    def test_invalid_constructor_and_text_types_rejected(self):
        for arguments in [dict(enabled='true'), dict(terms='bad'), dict(terms=['bad\nterm'])]:
            with self.subTest(arguments=arguments):
                with self.assertRaises(ValueError):
                    Normalizer(**arguments)
        with self.assertRaises(TypeError):
            Normalizer().normalize(None)


if __name__ == '__main__':
    unittest.main()
