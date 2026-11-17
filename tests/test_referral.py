"""The referral layer adds "where to ask" only to unanswered results."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from referral import attach_referral, load_referral, load_topic_rules, topic_of  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RULES = [{'exact_path': '/elselt', 'topic_id': 'admissions'},
         {'path_prefix': '/career', 'topic_id': 'career'}]
REFERRAL = {'enabled': True, 'general': {'text_mn': 'Ресепшнээс асууна уу.', 'source': {'url': 'x'}},
            'topic_offices': {'approved': False, 'map': {'admissions': 'Сургалтын алба'}}}


class ReferralTest(unittest.TestCase):
    def test_unanswered_result_gets_general_referral_in_message(self):
        result = attach_referral({'answer': None, 'message': 'Олдсонгүй.'}, REFERRAL)
        self.assertEqual(result['message'], 'Олдсонгүй. Ресепшнээс асууна уу.')
        self.assertIsNone(result['referral']['office'])

    def test_answered_or_clarifying_results_are_unchanged(self):
        answered = {'answer': 'Тийм.', 'message': None}
        self.assertNotIn('referral', attach_referral(dict(answered), REFERRAL))
        clarifying = {'answer': None, 'clarification': {'question': 'Аль хөтөлбөр?'}, 'message': ''}
        self.assertNotIn('referral', attach_referral(dict(clarifying), REFERRAL))

    def test_office_named_only_after_school_approval(self):
        result = {'answer': None, 'message': '', 'related_sources': [{'url': 'https://nmct.edu.mn/elselt'}]}
        self.assertIsNone(attach_referral(dict(result), REFERRAL, rules=RULES)['referral']['office'])
        approved = dict(REFERRAL, topic_offices=dict(REFERRAL['topic_offices'], approved=True))
        out = attach_referral(dict(result), approved, rules=RULES, locate=lambda name: '406 өрөө, 4-р давхар')
        self.assertEqual(out['referral']['office'], 'Сургалтын алба (406 өрөө, 4-р давхар)')
        self.assertEqual(out['referral']['office_source'], 'source_topic')
        self.assertTrue(out['message'].startswith('Энэ сэдвээр лавлах газар: Сургалтын алба'))

    def test_question_words_choose_the_office_before_related_pages(self):
        # 11/17 probe: «Төлбөрөө хэсэгчлэн төлж болох уу?» retrieved the career page; the
        # question itself names the topic.
        config = load_referral(ROOT)
        rooms = {'Санхүүгийн алба': '804 өрөө, 8-р давхар', 'Номын сан': '1006 өрөө, 10-р давхар',
                 'Сургалтын алба': '406 өрөө, 4-р давхар',
                 'Гадаад харилцаа, карьер хөгжлийн төв': '1007 өрөө, 10-р давхар'}

        def refer(query, locate=rooms.get):
            result = {'answer': None, 'message': 'Олдсонгүй.', 'query': query,
                      'related_sources': [{'url': 'https://nmct.edu.mn/career-center'}]}
            return attach_referral(result, config, rules=load_topic_rules(ROOT), locate=locate)['referral']

        payment = refer('Төлбөрөө хэсэгчлэн төлж болох уу?')
        self.assertEqual(payment['office'], 'Санхүүгийн алба (804 өрөө, 8-р давхар)')
        self.assertEqual(payment['office_source'], 'question')
        self.assertIs(payment['office_reviewed'], False)
        self.assertNotIn('ресепшний ажилтнаас', payment['text'])
        self.assertIn('info@nmct.edu.mn', payment['text'])
        self.assertEqual(refer('Номын сангаас нэг удаад хэдэн ном зээлж болох вэ?')['office'],
                         'Номын сан (1006 өрөө, 10-р давхар)')
        self.assertEqual(refer('Дадлагын гэрээг хаана бүртгүүлэх вэ?')['office'],
                         'Гадаад харилцаа, карьер хөгжлийн төв (1007 өрөө, 10-р давхар)')
        self.assertEqual(refer('2-р курст шилжиж орж болох уу?')['office'], 'Сургалтын алба (406 өрөө, 4-р давхар)')
        # Job applications: no office is guessed, and the related career page is not used either.
        job = refer('Ажлын байрны анкетыг хаана өгөх вэ?')
        self.assertIsNone(job['office'])
        self.assertIn('ресепшний ажилтнаас', job['text'])
        # Review (round 4): that stop holds even if page topics are ever switched on.
        approved = dict(config, topic_offices=dict(config['topic_offices'], approved=True))
        result = {'answer': None, 'message': '', 'query': 'Ажлын байрны анкетыг хаана өгөх вэ?',
                  'related_sources': [{'url': 'https://nmct.edu.mn/career'}]}
        self.assertIsNone(attach_referral(result, approved, rules=load_topic_rules(ROOT),
                                          locate=rooms.get)['referral']['office'])
        # An office missing from the school's room table is never named.
        self.assertIsNone(refer('Төлбөрөө хэсэгчлэн төлж болох уу?', locate=lambda name: None)['office'])
        self.assertIsNone(refer('Сайн байна уу')['office'])
        # «төлөв» (state) and «англи» are not «төл…»/«анги» topics.
        self.assertIsNone(refer('Бүртгэлийн төлөв?', locate=lambda name: None)['office'])
        self.assertIsNone(refer('Англи хэлний түвшин хэд вэ?')['office'])

    def test_a_named_office_is_its_own_referral(self):
        # «Сургалтын алба хэдэн цагт ажилладаг вэ?»: hours are not recorded; the office itself is the place.
        config = load_referral(ROOT)
        result = {'answer': None, 'message': 'Цаг бүртгэгдээгүй.', 'query': 'Сургалтын алба хэдэн цагт ажилладаг вэ?'}
        referral = attach_referral(result, config, locate={'Сургалтын алба': '406 өрөө, 4-р давхар'}.get)['referral']
        self.assertEqual(referral['office'], 'Сургалтын алба (406 өрөө, 4-р давхар)')

    def test_topic_rules_and_project_config(self):
        self.assertEqual(topic_of('https://nmct.edu.mn/career/jobs?page=2', RULES), 'career')
        self.assertIsNone(topic_of('https://nmct.edu.mn/unknown', RULES))
        config = load_referral(ROOT)
        self.assertIsNotNone(config)
        self.assertIs(config['topic_offices']['approved'], False)  # related pages are unreliable
        self.assertIs(config['question_offices']['reviewed'], False)  # agent's guess, not the school's
        self.assertTrue(load_topic_rules(ROOT))
        self.assertIsNone(load_referral(ROOT / 'missing'))


class ConversationTests(unittest.TestCase):
    def test_thanks_and_who_are_you(self):
        # Round 9: «Баярлалаа» was greeted again; «Та хэн бэ?» got an internship page.
        from rag_runtime import ChatRAG

        def reply(text):
            return next((message for pattern, message in ChatRAG.CONVERSATION if pattern.fullmatch(text)), None)
        self.assertTrue(reply('баярлалаа').startswith('Зүгээр ээ!'))
        self.assertTrue(reply('их баярлалаа').startswith('Зүгээр ээ!'))
        self.assertTrue(reply('сайн байна уу').startswith('Сайн байна уу!'))
        for text in ('та хэн бэ', 'чи юу хийж чадах вэ', 'юу асууж болох вэ'):
            with self.subTest(text=text):
                self.assertTrue(reply(text).startswith('Би Шинэ Монгол технологийн коллежийн ресепшний туслах.'))
        self.assertIsNone(reply('захирал хэн бэ'))
        # A greeting gets no «where to ask» line.
        result = dict(route='D', reason_code='conversation_help', message='Зүгээр ээ!', query='Баярлалаа')
        self.assertEqual(attach_referral(dict(result), load_referral(ROOT)), result)


if __name__ == '__main__':
    unittest.main()
