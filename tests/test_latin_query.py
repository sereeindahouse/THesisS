"""latin_query.py: Mongolian typed in Latin letters, read in Cyrillic (2026-11-23)."""
from collections import Counter
import unittest

from latin_query import latin_question, to_cyrillic, vocabulary_from


class LatinQueryTests(unittest.TestCase):
    def test_only_mongolian_in_latin_letters_is_read(self):
        self.assertTrue(latin_question('surguuli haana bdag ve'))
        self.assertTrue(latin_question('dotuur bair bga yu'))
        # English, Cyrillic, a single word or a name, and anything that is not text are left alone.
        for text in ('where is room 508', 'Сургууль хаана байдаг вэ', 'QPay', 'ok', 508, None):
            with self.subTest(text=text):
                self.assertFalse(latin_question(text))
        self.assertIsNone(to_cyrillic('where is the library'))

    def test_shortenings_letter_groups_and_the_schools_own_spelling(self):
        self.assertEqual(to_cyrillic('surguuli haana bdag ve'), 'сургууль хаана байдаг вэ')
        words = vocabulary_from(['Дотуур байр байхгүй. Дотуур байрны журам.', 'Сургалтын төлбөр'])
        self.assertEqual(to_cyrillic('dotuur bair bga yu', words), 'дотуур байр байгаа юу')
        # «u» is у, ү or ө in chat spelling; the word the school's texts use is chosen.
        self.assertEqual(to_cyrillic('tulbur heden ve', words), 'төлбөр хэдэн вэ')

    def test_a_long_ambiguous_word_is_read_to_its_end(self):
        # 3^8 readings: the candidates are pruned at each letter group, not cut off halfway (code review 11/23 (8)).
        self.assertEqual(len(to_cyrillic('tutututututututu bdag').split()[0]), 16)

    def test_names_written_in_latin_letters_stay(self):
        self.assertEqual(to_cyrillic('qpay-r tulj bolno uu', Counter({'төлж': 3})), 'qpay-р төлж болно уу')


if __name__ == '__main__':
    unittest.main()
