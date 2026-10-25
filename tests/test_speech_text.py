"""Constructed speech-only credit-unit formatting controls; no provider calls."""
import re
import unittest

from answer_contract import spoken_text
from speech_text import normalize_spoken_educational_credits, normalize_spoken_notation


class EducationalCreditSpeechTests(unittest.TestCase):
    def test_reviewed_educational_forms_expand_only_the_unit_and_preserve_digits(self):
        pairs=(
            ('Оюутан 47 төрлийн хичээл, нийт 81 кр цаг судална.',
             'Оюутан 47 төрлийн хичээл, нийт 81 кредит цаг судална.'),
            ('Хичээлийн багтаамж 3 кр.цаг байна.',
             'Хичээлийн багтаамж 3 кредит цаг байна.'),
            ('Сургалтын төлөвлөгөөнд 1,5 Кр. цаг судална.',
             'Сургалтын төлөвлөгөөнд 1,5 кредит цаг судална.'),
            ('Суралцагч 2.5кр.цагийн хичээл үзнэ.',
             'Суралцагч 2.5 кредит цагийн хичээл үзнэ.'),
            ('Хичээлийн зөрүү 0,5 кр.цагаас ихгүй.',
             'Хичээлийн зөрүү 0,5 кредит цагаас ихгүй.'),
            ('Хичээл 3 кр.цаг, сургалт 12 кр цагийн агуулгатай.',
             'Хичээл 3 кредит цаг, сургалт 12 кредит цагийн агуулгатай.'),
            ('Оюутан 2 кр.цагийн төлбөр ба 4 кр.цагийн зөрүүг тооцно.',
             'Оюутан 2 кредит цагийн төлбөр ба 4 кредит цагийн зөрүүг тооцно.'),
        )
        for before,after in pairs:
            with self.subTest(before=before):
                self.assertEqual(normalize_spoken_educational_credits(before),after)
                self.assertEqual(re.findall(r'\d+(?:[.,]\d+)?',before),
                                 re.findall(r'\d+(?:[.,]\d+)?',after))

    def test_unknown_abbreviations_suffixes_ranges_and_identifiers_stay_literal(self):
        samples=(
            'Хичээл 90 KP цаг судална.',
            'Хичээл 90 кр/цаг судална.',
            'Хичээл 90 крцаг судална.',
            'Хичээл 90 кр цагтай байна.',
            'Хичээл A90 кр цаг судална.',
            'Хичээл 90 кр цаг.pdf файлаас уншина.',
            'Хичээлийн код: 90 кр цаг.',
            'Сургалтын ID = 90 кр цаг.',
            'Хичээл https://example.test/90 кр цаг холбоостой.',
            'Хичээлийн агуулга 3–5 кр цаг.',
            'Хичээлийн агуулга 3 – 5 кр цаг.',
            'Хичээлийн агуулга 3 кр цаг – 5 кр цаг.',
            'Хичээл 1/2 кр цаг судална.',
            'Хичээл 3,000 кр цаг судална.',
        )
        for text in samples:
            with self.subTest(text=text):
                self.assertEqual(normalize_spoken_educational_credits(text),text)

    def test_noneducational_or_other_sentence_context_does_not_authorize_expansion(self):
        samples=(
            'Төхөөрөмж 90 кр цаг ажиллана.',
            'Хөтөлбөр 90 кр цаг ажиллана.',
            'Хичээлийн тухай мэдээлэл. Төхөөрөмж 90 кр цаг ажиллана.',
            'Төхөөрөмж 90 кр цаг ажиллана. Оюутан дараа нь ирнэ.',
            'Сургалтын мэдээ\nТөхөөрөмж 90 кр цаг ажиллана.',
        )
        for text in samples:
            with self.subTest(text=text):
                self.assertEqual(normalize_spoken_educational_credits(text),text)

    def test_full_spoken_rendering_expands_credit_without_changing_display_or_citation(self):
        display='Оюутан 47 төрлийн хичээл, нийт 81 кр цаг судална. [1]'
        result=dict(route='C',answer_kind='rag_generated',answer=display,
                    citations=[dict(document_id='constructed-source')])
        spoken=spoken_text(result)
        self.assertEqual(spoken,'Оюутан 47 төрлийн хичээл, нийт 81 кредит цаг судална.')
        self.assertEqual(result['answer'],display)
        self.assertEqual(result['citations'],[dict(document_id='constructed-source')])

    def test_normalization_is_idempotent(self):
        raw='Хичээлийн хэмжээ 3 кр.цаг байна.'
        once=normalize_spoken_notation(raw)
        self.assertIn('3 кредит цаг',once)
        self.assertEqual(normalize_spoken_notation(once),once)


if __name__=='__main__':unittest.main()
