"""Constructed speech-rendering regressions; not human listening outcomes."""
import unittest
from answer_contract import spoken_text
from speech_text import normalize_spoken_notation, normalize_spoken_currency


class SpeechScopeTests(unittest.TestCase):
    def test_qr_url_and_email_fragments_remain_literal(self):
        for text in ('https://example.test/QR код', 'user+QR код@example.test',
                     r'C:\folder\QR код.txt', 'id=QR код', '/QR код'):
            with self.subTest(text=text):
                self.assertEqual(normalize_spoken_notation(text),text)

    def test_phone_labels_inside_identifiers_remain_literal(self):
        for text in ('https://example.test/утас:77123456', 'утас:77123456@example.test',
                     'id=утас:77123456', r'C:\утас:77123456', 'утас:77123456?x=1'):
            with self.subTest(text=text):
                self.assertEqual(normalize_spoken_notation(text),text)

    def test_standalone_year_identifier_boundaries_are_also_preserved(self):
        for text in ('https://example.test/?year=2026 оны','calendar@2026 оны',
                     '2026 оны@example.test','id=2026 оны'):
            with self.subTest(text=text):
                self.assertEqual(normalize_spoken_notation(text),text)

    def test_currency_identifier_boundaries_are_not_rewritten(self):
        for text in ('id=2000₮','2000MNT@example.test','https://example.test/?fee=20,000₮'):
            with self.subTest(text=text):
                self.assertEqual(normalize_spoken_currency(text),text)

    def test_explicit_consecutive_academic_years_have_both_endpoints(self):
        raw='2025–2026 оны хичээлийн жилд 128 оюутан суралцана.'
        expected='хоёр мянга хорин таваас хоёр мянга хорин зургаан оны хичээлийн жилд 128 оюутан суралцана.'
        self.assertEqual(normalize_spoken_notation(raw),expected)
        self.assertEqual(normalize_spoken_notation(expected),expected)

    def test_other_academic_years_are_not_fixed_to_one_example(self):
        pairs=(('2000 - 2001','хоёр мянгаас хоёр мянга нэгэн'),
               ('2030—2031','хоёр мянга гучаас хоёр мянга гучин нэгэн'),
               ('2098–2099','хоёр мянга ерэн наймаас хоёр мянга ерэн есөн'))
        for raw,spoken in pairs:
            with self.subTest(raw=raw):
                self.assertEqual(normalize_spoken_notation(raw+' оны хичээлийн жилийн мэдээлэл.'),
                                 spoken+' оны хичээлийн жилийн мэдээлэл.')

    def test_dates_reversed_nonconsecutive_ranges_and_codes_not_guessed(self):
        for text in ('2026–2025 оны хичээлийн жил', '2024–2026 оны хичээлийн жил',
                     '2025–2026 оны журам', '2025/2026 оны хичээлийн жил',
                     '2025-10-26', 'M2025–2026 оны хичээлийн жил',
                     'id=2025–2026 оны хичээлийн жил', '/2025–2026 оны хичээлийн жил'):
            with self.subTest(text=text):
                self.assertEqual(normalize_spoken_notation(text),text)

    def test_regular_qr_and_labelled_phone_still_expand(self):
        self.assertEqual(normalize_spoken_notation('QR код. Утас: 77123456.'),
                         'кью ар код. Утас: долоо долоо нэг хоёр, гурав дөрөв тав зургаа.')

    def test_spoken_rendering_preserves_display_source_and_unrelated_numbers(self):
        display='2025–2026 оны хичээлийн жилд 1-р курс 27 оюутан. [1]'
        result=dict(route='C',answer_kind='rag_generated',answer=display,
                    citations=[dict(document_id='constructed-source')])
        spoken=spoken_text(result)
        self.assertIn('хоёр мянга хорин таваас хоёр мянга хорин зургаан оны хичээлийн жилд',spoken)
        self.assertIn('1-р курс 27 оюутан.',spoken)
        self.assertEqual(result['answer'],display)
        self.assertEqual(result['citations'],[dict(document_id='constructed-source')])


if __name__=='__main__':
    unittest.main()
