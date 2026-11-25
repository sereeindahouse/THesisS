"""Everyday wordings (2026-11-26). The user: «энэ яадаг сургууль вэ» got «not found» — «when I ask one different
question the system collapses». Each kind found in a sweep of 130 everyday questions is read as the question that
answers it; a question nothing answers offers the stored questions closest in meaning; another school is out of
scope. These are development checks: the questions were written by the agent (the user keeps a separate set)."""
import json
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace
import unittest

import numpy as np

from faq_intent import FaqIntents
from question_planner import ADMISSION_QUESTION, SCHOOL_HISTORY_QUESTION, SCHOOL_OVERVIEW_QUESTION, QuestionPlanner
from rag_runtime import ChatRAG
from reception_tables import ReceptionTables, Room, Service, Staff


class FakeReception:
    enabled = True

    def __init__(self):
        self.tables = ReceptionTables(
            rooms=(Room(6, '604', 'Багш нарын өрөө'), Room(10, '1001', 'Сэтгэл зүйчийн өрөө',
                                                         services=(Service('Сэтгэл зүйч', '', ''),)),
                   Room(4, '406', 'Сургалтын алба', services=(Service('Сургалтын алба', '', ''),))),
            staff=(Staff(name='Б.Сэлмаа', department='Ерөнхий эрдмийн тэнхим'),), classes=(), timetable=())


def planner():
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        (root / 'config').mkdir()
        (root / 'config/question-planner.json').write_text(json.dumps(dict(
            schema_version=1, enabled=True, split_compound=True, class_groups=True, staff_names=True)), encoding='utf-8')
        (root / 'config/knowledge-domains.json').write_text(json.dumps({'domains': {
            'admissions': {'keywords': ['төлбөр', 'элсэлт']}}}, ensure_ascii=False), encoding='utf-8')
        return QuestionPlanner.from_config(root, FakeReception())


class EverydayWordingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.planner = planner()

    def read(self, question):
        return ' || '.join(part['query'] for part in self.planner.plan(question)['parts'])

    def test_what_the_school_is_in_everyday_words(self):
        for question in ('энэ яадаг сургууль вэ', 'Энэ юуны сургууль вэ?', 'танайх ямар сургууль вэ', 'энд юу сурдаг вэ',
                         'юу заадаг газар вэ', 'энд юу хийдэг газар вэ', 'энэ ямар газар вэ', 'ШМТК юу гэсэн үг вэ',
                         'коосэн гэдэг чинь юу юм', 'энэ сургуулийн онцлог юу вэ', 'яагаад энэ сургуульд сурах ёстой вэ',
                         'энэ сургууль япон сургууль уу', 'ШМТК'):
            self.assertEqual(self.read(question), SCHOOL_OVERVIEW_QUESTION, question)

    def test_the_schools_age(self):
        for question in ('хэдэн онд байгуулагдсан бэ', 'сургууль хэдэн жилийн настай вэ', 'түүх'):
            self.assertEqual(self.read(question), SCHOOL_HISTORY_QUESTION, question)
        # Another body's founding is not the school's.
        self.assertNotEqual(self.read('Оюутны зөвлөл хэзээ байгуулагдсан бэ?'), SCHOOL_HISTORY_QUESTION)

    def test_enrolment_wishes_and_the_grade_of_entry(self):
        for question in ('хүүхдээ оруулах гэсэн юм', '9 төгсөөд орж болох уу', '12-р анги төгссөн хүүхэд орж болох уу',
                         'элсэлтийн шалгалт өгөх үү', 'элсэлтийн бүртгэл хаана хийдэг вэ', 'элсэлт'):
            self.assertEqual(self.read(question), ADMISSION_QUESTION, question)
        self.assertEqual(self.read('ямар бичиг баримт бүрдүүлэх вэ'), 'Элсэхэд ямар бичиг баримт хэрэгтэй вэ?')
        self.assertEqual(self.read('танай сургуульд орох гэсэн юм'), ADMISSION_QUESTION)
        # Going into a room or a lesson is not enrolling.
        for question in ('Би энд орох гэж байна', 'сурах гэсэн юм'):
            self.assertNotEqual(self.read(question), ADMISSION_QUESTION, question)
        # A paper the office issues is another question.
        self.assertNotEqual(self.read('Тодорхойлолт авахад ямар бичиг баримт хэрэгтэй вэ?'),
                            'Элсэхэд ямар бичиг баримт хэрэгтэй вэ?')

    def test_it_and_programming_is_the_computer_science_department(self):
        for question in ('IT мэргэжил байна уу', 'программист болох мэргэжил байна уу'):
            self.assertEqual(self.read(question), 'Компьютерын ухааны тэнхимийн талаар тайлбарлана уу.', question)
        # Who teaches a subject stays a timetable question.
        self.assertNotIn('тэнхимийн талаар', self.read('Программчлал хэн заадаг вэ?'))

    def test_departments(self):
        self.assertEqual(self.read('механик инженер ямар мэргэжил вэ'), 'Механик инженерийн тэнхимийн талаар танилцуулна уу.')
        self.assertEqual(self.read('ерөнхий эрдмийн тэнхим юу заадаг вэ'), 'Ерөнхий эрдмийн тэнхимийн талаар танилцуулна уу.')
        self.assertEqual(self.read('цахилгааны тэнхимийн эрхлэгч хэн бэ'),
                         'Цахилгаан электроникийн инженерийн тэнхимийн эрхлэгч хэн бэ')
        # The department's teachers are answered from the tables by the short name: unchanged.
        self.assertEqual(self.read('Цахилгааны тэнхимийн багш нар хэн бэ?'), 'Цахилгааны тэнхимийн багш нар хэн бэ?')

    def test_one_word_topics(self):
        self.assertEqual(self.read('төлбөр'), 'Сургалтын төлбөр хэд вэ?')
        self.assertEqual(self.read('Захирал'), 'Захирал хэн бэ?')
        self.assertEqual(self.read('wifi байдаг уу'), 'Сургалтын орчин ямар вэ?')

    def test_rooms_offices_and_the_way_here(self):
        self.assertEqual(self.read('604 хаана байдаг вэ'), '604 тоот хаана вэ?')
        self.assertEqual(self.read('999 хаана байдаг вэ'), '999 хаана байдаг вэ')       # no such room: as asked
        self.assertEqual(self.read('сэтгэл зүйч байна уу'), 'Сэтгэл зүйч хаана байдаг вэ?')
        self.assertEqual(self.read('багш нар хаана суудаг вэ'), 'Багш нарын өрөө хаана вэ?')
        self.assertEqual(self.read('автобусаар яаж очих вэ'), 'Сургуулийн хаяг хаана вэ?')
        # A way inside the building is not the school's address.
        self.assertNotEqual(self.read('Номын сан руу яаж очих вэ?'), 'Сургуулийн хаяг хаана вэ?')

    def test_typing_without_vowels(self):
        self.assertEqual(self.read('сургалтын тлбр хэд вэ'), 'сургалтын төлбөр хэд вэ')
        self.assertEqual(self.read('Сургалтын алба хаана бдг вэ'), 'Сургалтын алба хаана байдаг вэ')
        self.assertEqual(self.read('Тлбр хэд вэ'), 'Төлбөр хэд вэ')        # a capital first letter starts the sentence
        # An upper-case abbreviation and a class code stay as typed.
        self.assertEqual(self.read('ШМТК хаана байдаг вэ'), 'ШМТК хаана байдаг вэ')

    def test_compound_questions_read_each_part(self):
        parts = self.planner.plan('Энэ яадаг сургууль вэ? Төлбөр хэд вэ?')['parts']
        self.assertEqual(parts[0]['query'], SCHOOL_OVERVIEW_QUESTION)
        self.assertEqual(parts[0]['original'], 'Энэ яадаг сургууль вэ?')


class OtherSchoolTests(unittest.TestCase):
    def out_of_scope(self, question):
        return bool(ChatRAG.OUT_OF_SCOPE.fullmatch(re.sub(r'\s+', ' ', question.casefold()).strip(' ?!.')))

    def test_another_school_asked_where_or_what_it_teaches(self):
        for question in ('ШУТИС хаана байдаг вэ?', 'ШУТИС ямар мэргэжилтэй вэ?', 'Отгонтэнгэр их сургууль хаана байдаг вэ?',
                         'МУИС-ийн төлбөр хэд вэ?'):
            self.assertTrue(self.out_of_scope(question), question)
        # This school, a contest held together, or a person named like a school, stays a school question.
        for question in ('ШУТИС-тэй хамтран олимпиад зохион байгуулдаг уу?', 'МУИС-ийн төлбөрөөс манайх хямд уу?',
                         'Сургууль хаана байдаг вэ?', 'Отгонтэнгэр хаана байдаг вэ?', 'Отгонтэнгэр ямар тэнхимд ажилладаг вэ?'):
            self.assertFalse(self.out_of_scope(question), question)


class AnsweringPolicy:
    """A stored answer for every question: «… сургууль хаана байдаг вэ?» matched the school's address FAQ."""
    enabled = True

    def route(self, db, query, allow_draft=False):
        return dict(query=query, route='B', package_id='package1', answer='Сургуулийн хаяг: Улаанбаатар хот.', citations=[],
                    reason_code='official_website_stored_answer', reason_codes=[], clarification=None, exact_matches=[],
                    generated=False, llm_calls=0, message='', answer_kind='official_website_snapshot',
                    answer_faq_id='faq.contact.location')


class OutOfScopeBeforeStoredAnswerTests(unittest.TestCase):
    def test_another_school_is_turned_away_even_when_a_stored_answer_matched(self):
        from reception_tables import ReceptionAnswerPath
        chat = ChatRAG('.', AnsweringPolicy(), SimpleNamespace(status=lambda: {}), SimpleNamespace(status=lambda: {}),
                       reception=ReceptionAnswerPath())
        chat.faq_intents = FaqIntents(enabled=False)
        turned = chat._route('db', 'Отгонтэнгэр их сургууль хаана байдаг вэ?')
        self.assertEqual((turned['route'], turned['reason_code'], turned['answer'], turned['answer_faq_id']),
                         ('D', 'out_of_scope', None, None))
        # Also when no stored answer matched and the own-wording mapping would have read it as the address.
        chat.policy = SimpleNamespace(enabled=True, route=lambda db, query, allow_draft=False: dict(
            AnsweringPolicy().route(db, query), route='E', answer=None, answer_faq_id=None,
            reason_code='no_supported_question_match'))
        self.assertEqual(chat._route('db', 'ШУТИС хаана байдаг вэ?')['reason_code'], 'out_of_scope')
        chat.policy = AnsweringPolicy()
        kept = chat._route('db', 'Сургууль хаана байдаг вэ?')
        self.assertEqual((kept['route'], kept['answer_faq_id']), ('B', 'faq.contact.location'))


class StemEncoder:
    STEMS = ('сургууль', 'ямар', 'төлбөр', 'хоол')

    def encode(self, texts, prefix):
        rows = []
        for text in texts:
            words = text.casefold().split()
            row = np.array([float(any(word.startswith(stem) for word in words)) for stem in self.STEMS]) + 0.01
            rows.append(row / np.linalg.norm(row))
        return np.vstack(rows)


FAQS = {'faq.school': dict(question='Шинэ Монгол технологийн коллеж ямар сургууль вэ?',
                           question_aliases=['ШМТК ямар сургууль вэ?'], answer='…'),
        'faq.fee': dict(question='Сургалтын төлбөр хэд вэ?', question_aliases=[], answer='…'),
        'faq.food': dict(question='Хоолны газар бий юу?', question_aliases=[], answer='…')}


class NearestQuestionTests(unittest.TestCase):
    def test_nearest_offers_the_shortest_wording_above_the_floor(self):
        intents = FaqIntents([], encoder=StemEncoder())
        nearest = intents.nearest('оюутнууд хаана хооллодог вэ', FAQS, floor=0.5)
        self.assertEqual([text for text, _ in nearest], ['Хоолны газар бий юу?'])
        # E5 scores questions of the same form close: a stored question must also share a topic word.
        self.assertEqual(intents.nearest('дүрэмт хувцастай юу', FAQS, floor=0.0), [])
        self.assertEqual(intents.nearest('бие засах газар хаана байдаг вэ', FAQS, floor=0.0), [])   # «газар» is no topic
        self.assertEqual(FaqIntents([]).nearest('оюутнууд хаана хооллодог вэ', FAQS), [])     # no encoder: nothing

    def test_only_a_reply_without_an_answer_gets_them(self):
        intents = FaqIntents([dict(faq_id='faq.food', require=[['хоол']])], encoder=StemEncoder())
        rag = SimpleNamespace(faq_intents=intents, NEAREST_FLOOR=0.5, NEAREST_SKIP=ChatRAG.NEAREST_SKIP,
                              SUGGESTIONS=['a', 'b', 'c'], _offerable_faqs=lambda database, package, draft: FAQS)
        found = ChatRAG._nearest_questions(rag, 'db', dict(route='E', answer=None, suggestions=['a', 'b', 'c'], package_id='p'),
                                           'оюутнууд хаана хооллодог вэ')
        self.assertEqual(found['suggestions'], ['Хоолны газар бий юу?'])
        self.assertEqual(found['suggestions_kind'], 'nearest_stored_questions')
        # The route's own suggestions (a name's candidates) stay; switched-off intents offer nothing.
        kept = ChatRAG._nearest_questions(rag, 'db', dict(route='E', answer=None, suggestions=['Б.Сэлмаа'], package_id='p'),
                                          'оюутнууд хаана хооллодог вэ')
        self.assertEqual(kept['suggestions'], ['Б.Сэлмаа'])
        rag.faq_intents.enabled = False
        self.assertNotIn('suggestions_kind', ChatRAG._nearest_questions(
            rag, 'db', dict(route='E', answer=None, suggestions=[], package_id='p'), 'оюутнууд хаана хооллодог вэ'))
        rag.faq_intents.enabled = True
        for result in (dict(route='C', answer='…', suggestions=[]),
                       dict(route='E', answer=None, answer_kind='reception_table_lookup', suggestions=[]),
                       dict(route='E', answer=None, reason_code='personal_record_outside_scope', suggestions=[])):
            self.assertNotIn('suggestions_kind', ChatRAG._nearest_questions(rag, 'db', dict(result), 'оюутнууд хаана хооллодог вэ'))


if __name__ == '__main__':
    unittest.main()
