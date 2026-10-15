"""Regression checks for the observed incomplete topic answer and speech text."""
import copy
import unittest

from answer_contract import MAX_SPEECH_CHARACTERS, spoken_text
from rag_runtime import ChatRAG, registration_process_query, source_extract
from speech_text import normalize_spoken_currency
from test_rag_runtime import Policy, Retriever, Generator, SOURCE

STEPS = ('1. Бүртгүүлэх\nМэдээллээ бөглөнө.\n2. Хураамж төлөх\nQPay ашиглана.\n'
         '3. Хувийн хэсэг\nБүртгэлийн мэдээллээ харна.')


class RegistrationProcessTests(unittest.TestCase):
    def chat(self, text):
        retriever, generator = Retriever(), Generator()
        retriever.sources[0].update(text=text, excerpt=text, page_header='Элсэлт 2026')
        return ChatRAG('.', Policy(), retriever, generator), generator

    def test_online_topic_and_how_questions_copy_all_steps_without_generation(self):
        for query in ('Элсэлтийн онлайн бүртгэл',
                      '2026 оны элсэлтийн онлайн бүртгэл',
                      'Элсэлтийн онлайн бүртгэлд хэрхэн бүртгүүлэх вэ?',
                      'Элсэлтийн цахим бүртгэлд яаж бүртгүүлэх вэ?'):
            with self.subTest(query=query):
                chat, generator = self.chat('Элсэлт 2026\n' + STEPS)
                result = chat.route(None, query)
                self.assertEqual(result['route'], 'A')
                self.assertIn(STEPS, result['answer'])
                self.assertIn('Элсэлт 2026', result['answer'])
                self.assertIn('2026-10-10', result['answer'])
                self.assertEqual(generator.calls, 0)

    def test_common_how_action_word_keeps_process_but_unknown_stt_word_is_not_repaired(self):
        for query in ('Элсэлтийн бүртгэл яаж хийх вэ?',
                      'Элсэлтийн бүртгэл хэрхэн хийх вэ?'):
            with self.subTest(query=query):
                chat, generator = self.chat('Элсэлт 2026\n' + STEPS)
                result = chat.route(None, query)
                self.assertEqual(result['route'], 'A')
                self.assertIn(STEPS, result['answer'])
                self.assertEqual(generator.calls, 0)
        self.assertFalse(registration_process_query('эсэгтийн бүртгэл яаж хийх вэ'))

    def test_fee_only_or_incomplete_steps_cannot_answer_process(self):
        for text in ('Бүртгэлийн хураамж 20,000 төгрөг.',
                     '1. Бүртгүүлэх\nМэдээллээ бөглөнө.\n2. Хураамж төлөх\n20,000 төгрөг.'):
            chat, generator = self.chat(text)
            result = chat.route(None, 'Элсэлтийн онлайн бүртгэл')
            self.assertIsNone(result['answer'])
            self.assertEqual(result['route'], 'E')
            self.assertEqual(result['rag']['reason'], 'registration_process_not_supported')
            self.assertEqual(generator.calls, 0)

    def test_process_does_not_bypass_requested_year_or_live_status(self):
        chat, generator = self.chat('Элсэлт 2026\n' + STEPS)
        result = chat.route(None, '2028 оны элсэлтийн онлайн бүртгэл')
        self.assertEqual(result['reason_code'], 'requested_year_not_supported')
        self.assertIsNone(result['answer'])
        result = chat.route(None, 'Одоо элсэлтийн онлайн бүртгэл нээлттэй юу?')
        self.assertEqual(result['reason_code'], 'live_status_not_supported')
        self.assertEqual(generator.calls, 0)

    def test_fee_dates_eligibility_and_special_groups_keep_separate_intents(self):
        for query in ('Элсэлтийн онлайн бүртгэлийн хураамж хэд вэ?',
                      'Элсэлтийн онлайн бүртгэл хэзээ дуусах вэ?',
                      'Элсэлтийн онлайн бүртгэл хаана хийх вэ?',
                      'Гадаад оюутан онлайн бүртгэлд хэрхэн бүртгүүлэх вэ?',
                      'Олимпиадын онлайн бүртгэл'):
            self.assertFalse(registration_process_query(query), query)
        source = dict(SOURCE, text=STEPS)
        self.assertIsNone(source_extract('Элсэлтийн онлайн бүртгэлийн хураамж хэд вэ?', [source]))


class SpeechTextTests(unittest.TestCase):
    def test_only_explicit_currency_is_verbalised(self):
        self.assertEqual(normalize_spoken_currency('Бүртгэлийн хураамж 20,000 ₮.'),
                         'Бүртгэлийн хураамж хорин мянган төгрөг.')
        self.assertEqual(normalize_spoken_currency('5,000 төгрөг'), 'таван мянган төгрөг')
        self.assertEqual(normalize_spoken_currency('8,280,000 MNT'),
                         'найман сая хоёр зуун наян мянган төгрөг')
        self.assertEqual(normalize_spoken_currency('20,500 төгрөгийн'),
                         'хорин мянга таван зуун төгрөгийн')
        self.assertEqual(normalize_spoken_currency('0 ₮'), 'тэг төгрөг')

    def test_year_time_phone_decimal_range_and_malformed_grouping_stay_literal(self):
        for text in ('2026-10-15, 12:30, утас 7017-2794, 15 минут, 2026 оны',
                     '20.5 ₮', '20,5 ₮', '5,000–20,000 ₮', '5,000 - 20,000 ₮',
                     '1,20,000 ₮', '20 000 ₮', '0123 ₮', '1,000,000,000 ₮'):
            self.assertEqual(normalize_spoken_currency(text), text)

    def test_known_generated_citation_removed_only_from_speech(self):
        original = dict(answer='Бүртгэлийн хураамж 20,000 ₮. [1]',
                        answer_kind='rag_generated', citations=[{'document_id': 'source'}])
        before = copy.deepcopy(original)
        self.assertEqual(spoken_text(original), 'Бүртгэлийн хураамж хорин мянган төгрөг.')
        self.assertEqual(original, before)
        self.assertEqual(spoken_text({'answer': 'Тайлбар [1]', 'answer_kind': 'official_website_extract'}),
                         'Тайлбар [1]')
        original['answer'] = 'Утгатай [1] тэмдэг. [1]\n\nӨөр утгатай [2]'
        self.assertEqual(spoken_text(original), 'Утгатай [1] тэмдэг.\n\nӨөр утгатай [2]')

    def test_currency_normalization_is_idempotent(self):
        text = normalize_spoken_currency('Жилд 8,280,000 ₮, хураамж 20,000 төгрөг.')
        self.assertEqual(normalize_spoken_currency(text), text)

    def test_expanded_speech_over_budget_keeps_complete_display_and_citations(self):
        text = ('20,000 ₮. ' * 60).strip()
        retriever, generator = Retriever(), Generator()
        retriever.sources[0].update(text=text, excerpt=text)
        generator.generate = lambda query, sources: dict(generated=True, llm_calls=1,
            claims=[dict(text=text, source_id=SOURCE['source_id']) for _ in range(2)], reason='test')
        result = ChatRAG('.', Policy(), retriever, generator).route(None, 'Бүртгэлийн мэдээллийг тайлбарла')
        self.assertEqual(result['route'], 'C')
        self.assertEqual(result['answer'], text + ' [1]\n\n' + text + ' [1]')
        self.assertEqual(len(result['citations']), 1)
        self.assertLess(len(result['answer']), MAX_SPEECH_CHARACTERS)
        self.assertGreater(len(spoken_text(result)), MAX_SPEECH_CHARACTERS)
        self.assertFalse(result['can_speak'])
        self.assertEqual(result['speech_unavailable_reason'], 'answer_exceeds_speech_budget')


if __name__ == '__main__':
    unittest.main()
