"""faq_intent.py: a visitor's own wording mapped to one stored FAQ; nothing generated (2026-11-23)."""
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from faq_intent import FaqIntents

ROOT = Path(__file__).resolve().parents[1]
FAQS = {
    'faq.fee': dict(question='Сургалтын төлбөр хэд вэ?', question_aliases=['Жилийн төлбөр хэд вэ?'],
                    answer='2026 оны сургалтын төлбөр жилд 8,280,000 төгрөг.'),
    'faq.canteen': dict(question='Хоолны газар байдаг уу?', question_aliases=[],
                        answer='Тийм. Нийтийн хоолны газар 360 хүний суудалтай.'),
}
INTENTS = [
    dict(faq_id='faq.fee', require=[['төлбөр'], ['хэд', 'хэдэн']], exclude=['дотуур', 'байр']),
    dict(faq_id='faq.canteen', require=[['хоол'], ['газар']], examples=['Хоол идэх газар бий юу?']),
]


class FakeEncoder:
    """Bag-of-stems vectors: enough to rank the fake FAQs, no model."""
    STEMS = ('төлбөр', 'хэд', 'хоол', 'газар', 'сургалт', 'жил')

    def __init__(self):
        self.calls = 0

    def encode(self, texts, prefix):
        self.calls += 1
        rows = []
        for text in texts:
            words = text.casefold().split()
            row = np.array([float(any(word.startswith(stem) for word in words)) for stem in self.STEMS]) + 0.01
            rows.append(row / np.linalg.norm(row))
        return np.vstack(rows)


class ConceptWordTests(unittest.TestCase):
    def test_required_groups_stems_phrases_and_excludes(self):
        intents = FaqIntents(INTENTS + [dict(faq_id='faq.tea', require=[['цайны газар']])])
        self.assertEqual([i['faq_id'] for i, _ in intents.gated('Сургалтын төлбөр хэдэн төгрөг вэ?')], ['faq.fee'])
        # Another fee is not the tuition: the exclude word stops it before any meaning score.
        self.assertEqual(intents.gated('Дотуур байранд амьдрах төлбөр хэд вэ?'), [])
        # A term with a space is a phrase of whole-word starts.
        self.assertEqual([i['faq_id'] for i, _ in intents.gated('Цайны газар хаана вэ?')], ['faq.tea'])
        self.assertEqual(intents.gated('Цай уух газар байна уу?'), [])

    def test_years_and_numbers_must_be_in_the_stored_text(self):
        text = ' '.join([FAQS['faq.fee']['question'], FAQS['faq.fee']['answer']])
        self.assertFalse(FaqIntents._numbers_fit('2027 оны сургалтын төлбөр хэд вэ?', text))
        self.assertTrue(FaqIntents._numbers_fit('2026 оны сургалтын төлбөр хэд вэ?', text))
        self.assertFalse(FaqIntents._numbers_fit('10 мэргэжлийн төлбөр хэд вэ?', text))
        self.assertTrue(FaqIntents._numbers_fit('10 мэргэжлийн төлбөр хэд вэ?', text, allowed=[10]))
        self.assertIsNone(FaqIntents(INTENTS).match('2027 оны сургалтын төлбөр хэд вэ?', FAQS))

    def test_the_asked_value_must_be_in_the_stored_answer(self):
        intents = FaqIntents(INTENTS)
        # «хэдэн цагт» asks for a time; the canteen answer has none, so it is not this question's answer.
        self.assertIsNone(intents.match('Хоолны газар хэдэн цагт нээгддэг вэ?', FAQS))
        self.assertEqual(intents.match('Хоолны газар байгаа юу', FAQS)['faq_id'], 'faq.canteen')


class MatchTests(unittest.TestCase):
    def test_the_closest_meaning_above_the_threshold(self):
        encoder = FakeEncoder()
        mapped = FaqIntents(INTENTS, threshold=0.8, encoder=encoder).match('Сургалтын төлбөр хэд вэ?', FAQS)
        self.assertEqual((mapped['faq_id'], mapped['method']), ('faq.fee', 'concept_words+e5'))
        self.assertEqual(mapped['question'], 'Сургалтын төлбөр хэд вэ?')
        self.assertGreaterEqual(mapped['similarity'], 0.8)
        self.assertIsNone(FaqIntents(INTENTS, threshold=1.01, encoder=FakeEncoder()).match('Сургалтын төлбөр хэд вэ?', FAQS))

    def test_without_the_encoder_only_one_gated_intent_maps(self):
        self.assertEqual(FaqIntents(INTENTS).match('Сургалтын төлбөр хэд вэ?', FAQS)['method'], 'concept_words_only')
        twice = [dict(INTENTS[0]), dict(INTENTS[0], faq_id='faq.fee2')]
        faqs = dict(FAQS, **{'faq.fee2': FAQS['faq.fee']})
        self.assertIsNone(FaqIntents(twice).match('Сургалтын төлбөр хэд вэ?', faqs))

    def test_an_encoder_failure_falls_back_to_the_concept_words(self):
        class Broken:
            def encode(self, texts, prefix):
                raise RuntimeError('no model')
        self.assertEqual(FaqIntents(INTENTS, encoder=Broken()).match('Сургалтын төлбөр хэд вэ?', FAQS)['faq_id'], 'faq.fee')

    def test_nothing_maps_when_off_empty_or_missing(self):
        self.assertIsNone(FaqIntents(INTENTS, enabled=False).match('Сургалтын төлбөр хэд вэ?', FAQS))
        self.assertIsNone(FaqIntents(INTENTS).match('Сургалтын төлбөр хэд вэ?', {}))
        self.assertIsNone(FaqIntents(INTENTS).match('', FAQS))
        self.assertIsNone(FaqIntents(INTENTS).match(None, FAQS))


class ConfigTests(unittest.TestCase):
    def config(self, data):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        (root / 'config').mkdir()
        if data is not None:
            (root / 'config/faq-intents.json').write_text(
                data if isinstance(data, str) else json.dumps(data, ensure_ascii=False), encoding='utf-8')
        return FaqIntents.from_config(root)

    def test_missing_invalid_or_not_switched_on_is_off(self):
        self.assertFalse(self.config(None).enabled)
        self.assertFalse(self.config('not json').enabled)
        self.assertFalse(self.config(dict(enabled=True, intents=[dict(faq_id='x')])).enabled)
        self.assertFalse(self.config(dict(enabled='yes', intents=INTENTS)).enabled)
        on = self.config(dict(enabled=True, threshold=0.9, intents=INTENTS))
        self.assertTrue(on.enabled)
        self.assertEqual(on.threshold, 0.9)

    def test_project_config_keeps_near_questions_off_the_stored_answers(self):
        intents = FaqIntents.from_config(ROOT)
        self.assertTrue(intents.enabled)

        def gated(query):
            return {intent['faq_id'] for intent, _ in intents.gated(query)}
        # Close in meaning, not the same question (11/23 check of every question bank); own wording here.
        self.assertNotIn('faq.admission.annual_tuition.2026', gated('Дотуур байранд амьдрах төлбөр хэд вэ?'))
        self.assertNotIn('faq.campus.facilities', gated('Номын сангаас хэдэн ном зээлүүлж болдог вэ?'))
        self.assertNotIn('faq.campus.facilities', gated('Барилгын тэнхим хэдэн лабораторитой вэ?'))
        self.assertNotIn('faq.cs.program', gated('Компьютерын ухааны тэнхимд одоо хэдэн оюутан байна?'))
        # The wordings the stored answers are for still reach them.
        self.assertIn('faq.campus.cafeteria', gated('Хоолны газар байгаа юу'))
        exemption = gated('Шалгалтгүй элсэх боломж бий юу?')
        self.assertIn('faq.admission.olympiad_exemption.2026_2027', exemption)
        self.assertNotIn('faq.admission.writing_exam.2026', exemption)


if __name__ == '__main__':
    unittest.main()
