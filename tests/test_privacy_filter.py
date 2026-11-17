"""Staff mobile numbers from website pages are hidden in everything shown or spoken."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from privacy_filter import HIDDEN, hide_mobiles  # noqa: E402


class PrivacyFilterTest(unittest.TestCase):
    def test_mobiles_are_hidden_school_line_and_other_numbers_stay(self):
        # Synthetic numbers; 11/17 probe: «Химийн тэнхимийн холбоо барих утас» showed a head's mobile.
        text = 'Тэнхимийн эрхлэгч\nИмэйл head@nmct.edu.mn\nУтас 99001122'
        self.assertEqual(hide_mobiles(text), 'Тэнхимийн эрхлэгч\nИмэйл head@nmct.edu.mn\nУтас ' + HIDDEN)
        self.assertEqual(hide_mobiles('Утас: 8811-2233'), 'Утас: ' + HIDDEN)
        self.assertEqual(hide_mobiles('+976 99001122 дугаарт'), HIDDEN + ' дугаарт')
        # Review (round 4): two numbers joined by a slash, and a spaced number after a longer label.
        self.assertEqual(hide_mobiles('Утас: 99001122/88001122'), 'Утас: ' + HIDDEN + '/' + HIDDEN)
        self.assertEqual(hide_mobiles('Утасны дугаар: 9900-1122'), 'Утасны дугаар: ' + HIDDEN)
        self.assertEqual(hide_mobiles('Утас/Phone: 9900 1122'), 'Утас/Phone: ' + HIDDEN)
        self.assertEqual(hide_mobiles('Холбоо барих: 8800 1122'), 'Холбоо барих: ' + HIDDEN)
        kept = ('Сургуулийн ерөнхий утас +976 75777799, имэйл info@nmct.edu.mn.',
                '2025-2026 оны хичээлийн жилд 128 оюутан', 'Үнэ 8000-9000₮', 'Нийт 20,000,000 төгрөг',
                'ev-75b413f173baecb0fd99001122', 'token_99001122x', 'https://nmct.edu.mn/x/99001122')
        for value in kept:
            self.assertEqual(hide_mobiles(value), value)

    def test_whole_results_are_walked(self):
        result = {'answer': 'Утас 99001122', 'latency_ms': 12.5, 'citations': [{'quote': 'утас 88001122'}],
                  'related_sources': ({'excerpt': 'Залгах: 99001122'},), 'llm_calls': 0}
        hidden = hide_mobiles(result)
        self.assertEqual(hidden['answer'], 'Утас ' + HIDDEN)
        self.assertEqual(hidden['citations'][0]['quote'], 'утас ' + HIDDEN)
        self.assertEqual(hidden['related_sources'][0]['excerpt'], 'Залгах: ' + HIDDEN)
        self.assertEqual((hidden['latency_ms'], hidden['llm_calls']), (12.5, 0))
        self.assertEqual(result['answer'], 'Утас 99001122')   # the input is not changed in place


if __name__ == '__main__':
    unittest.main()
