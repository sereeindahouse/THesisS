"""Scope rules of the website path found by reading real replies on 2026-11-25, and the office card.

INVENTED records only: no saved school page, no school table, no server, no network, no model.
"""
from datetime import datetime
import unittest

from rag_runtime import ChatRAG, named_scope_sources
from reception_tables import ReceptionAnswerPath, ReceptionTables, Room, Service, Staff
from website_sections import SectionIndex

NOW = datetime(2026, 11, 25, 10, 0)


def source(path):
    return dict(url='https://nmct.edu.mn' + path, source_id=path)


PAGES = [source(path) for path in ('/departments/mechanical', '/departments/electrical', '/programs/computer-science-program',
                                   '/olympiad', '/olympiad/o-2025-2026.pdf', '/news/x', '/career-center')]


def kept(query):
    return [item['source_id'] for item in named_scope_sources(query, PAGES)]


class NamedScopeTests(unittest.TestCase):
    def test_the_event_page_is_evidence_only_when_the_event_is_named(self):
        self.assertNotIn('/olympiad', kept('Төлбөрөө хэзээ төлөх вэ?'))
        self.assertNotIn('/olympiad/o-2025-2026.pdf', kept('Бүртгэлийн хураамж хэд вэ?'))
        self.assertIn('/olympiad', kept('Олимпиадын бүртгэлийн хураамж хэд вэ?'))

    def test_one_named_department_drops_the_pages_of_the_others(self):
        self.assertEqual(kept("Цахилгааны инженер мэргэжлээр төгсөөд юу хийх вэ?"),
                         ['/departments/electrical', '/news/x', '/career-center'])
        self.assertEqual(kept('Компьютерын ухааны хөтөлбөр хэдэн жил вэ?'),
                         ['/programs/computer-science-program', '/news/x', '/career-center'])

    def test_a_department_word_counts_only_at_the_start_of_a_word(self):
        # «хими» is also inside «тэнхимийн»: that names no department (full suite, 11/25).
        self.assertIn('/departments/mechanical', kept('Роботикийн тэнхимийн нийт суралцагчийн тоог хэлж өгөөч.'))
        self.assertNotIn('/departments/mechanical', kept('Химийн инженерийн хөтөлбөрийн талаар'))

    def test_an_everyday_word_names_no_department(self):
        # «барилга», «цахилгаан шат», «компьютерийн лаборатори»: a department only beside «тэнхим», «инженер» …
        for query in ('Сургуулийн барилга ямар вэ?', 'Цахилгаан шат байдаг уу?', 'Компьютерийн лаборатори байдаг уу?'):
            with self.subTest(query=query):
                self.assertIn('/departments/mechanical', kept(query))

    def test_no_department_or_two_departments_keep_every_department_page(self):
        for query in ('Сургууль хэдэн лабораторитой вэ?', 'Механик болон цахилгааны тэнхимийн ялгаа юу вэ?'):
            with self.subTest(query=query):
                self.assertEqual(kept(query), ['/departments/mechanical', '/departments/electrical',
                                               '/programs/computer-science-program', '/news/x', '/career-center'])


class Policy:
    enabled = True

    def __init__(self, reason='no_supported_question_match'):
        self.reason = reason

    def route(self, db, query, allow_draft=False):
        return dict(query=query, route='E', package_id='package1', answer=None, citations=[], reason_code=self.reason,
                    reason_codes=[], clarification=None, exact_matches=[], generated=False, llm_calls=0,
                    message='Олдсонгүй.', answer_kind=None)


class Retriever:
    def status(self):
        return dict(available=True, corpus_id='corpus1')

    def search(self, query, limit=4):
        return dict(candidates=[], corpus_id='corpus1', backend='test')


class Generator:
    def status(self):
        return dict(available=True)


def chat(reception=None, reason='no_supported_question_match', retriever=None):
    from faq_intent import FaqIntents
    made = ChatRAG('.', Policy(reason), retriever or Retriever(), Generator(), reception=reception or ReceptionAnswerPath(),
                   reception_clock=lambda: NOW)
    made.faq_intents = FaqIntents(enabled=False)
    made.sections = SectionIndex()
    return made


class OnlyAnotherThingsPageTests(unittest.TestCase):
    class OlympiadOnly(Retriever):
        def search(self, query, limit=4):
            return dict(corpus_id='corpus1', backend='test', candidates=[dict(
                source_id='s1', chunk_id='c1', url='https://nmct.edu.mn/olympiad', title='Олимпиад', page_header='',
                text='Бүртгэлийн хураамж 5,000 ₮. Олимпиадын өдөр 4-р сарын 25.', excerpt='Бүртгэлийн хураамж 5,000 ₮.',
                version=1, source_locator='tile', retrieved_at='2026-11-17')])

    def test_when_only_a_page_about_another_thing_was_found_the_reply_is_a_plain_not_found(self):
        result = chat(retriever=self.OlympiadOnly()).route('content.db', 'Төлбөрөө хэзээ төлөх вэ?')
        self.assertIsNone(result['answer'])
        self.assertEqual(result['reason_code'], 'selection_not_relevant')
        self.assertEqual(result['related_sources'], [])
        self.assertNotIn('холбогдох хуудсыг доор', result['message'])


class WebsiteAddressTests(unittest.TestCase):
    def test_the_schools_website_address(self):
        for query in ('Сургуулийн вэбсайт юу вэ?', 'Вэб сайтын хаяг юу вэ?', 'Танай сайт ямар вэ?',
                      'Сургуулийн албан ёсны вэб сайт хаана вэ?'):
            with self.subTest(query=query):
                result = chat().route('content.db', query)
                self.assertEqual(result['answer'], 'Сургуулийн албан ёсны вэб сайт: https://nmct.edu.mn')
                self.assertEqual(result['reason_code'], 'school_website_address')

    def test_other_pages_and_questions_about_the_site_are_not_this_question(self):
        for query in ('Сургуулийн фэйсбүүк хуудас юу вэ?', 'Сайтад элсэлтийн мэдээлэл байна уу?',
                      'Вэб сайт хөгжүүлэх хичээл байдаг уу?'):
            with self.subTest(query=query):
                self.assertNotEqual(chat().route('content.db', query).get('reason_code'), 'school_website_address')


class ForeignApplicantTests(unittest.TestCase):
    def test_admission_of_an_applicant_from_abroad_is_said_to_be_on_no_page(self):
        for query in ('Гадаад оюутан элсэж болох уу?', 'Гадаадын иргэн танай сургуульд суралцаж болох уу?'):
            with self.subTest(query=query):
                result = chat().route('content.db', query)
                self.assertIsNone(result['answer'])
                self.assertEqual(result['reason_code'], 'foreign_applicant_admission_not_published')
                self.assertIn('Гадаадын иргэн элсэх тухай мэдээлэл олдсонгүй.', result['message'])

    def test_other_questions_with_the_word_abroad_are_not_stopped(self):
        for query in ('Гадаад харилцааны алба хаана вэ?', 'Гадаадад суралцах боломж бий юу?',
                      'Төгсөөд Японд гадаад оюутан болж суралцаж болох уу?',
                      'Гадаад оюутан солилцооны хөтөлбөрөөр суралцдаг уу?'):
            with self.subTest(query=query):
                self.assertNotEqual(chat().route('content.db', query)['reason_code'],
                                    'foreign_applicant_admission_not_published')


def reception():
    tables = ReceptionTables(
        rooms=(Room(floor=4, name='406', purpose='Алба',
                    services=(Service(name='Зохиомол алба', office_hours='08:00–17:00', contact='—'),)),),
        staff=(Staff(name='З.Тэмүүлэн', department='Зохиомол алба', room='406', role='Сургалт хариуцсан мэргэжилтэн',
                     email='temuulen@school.example'),),
        classes=(), timetable=(), timetable_complete=False, dataset_label='FAKE only')
    return ReceptionAnswerPath(tables, enabled=True, complete=True)


class OfficeCardTests(unittest.TestCase):
    def test_what_an_office_does_gets_its_recorded_card_when_nothing_describes_it(self):
        for query in ('Зохиомол алба юу хийдэг вэ?', 'Зохиомол алба ямар үүрэгтэй вэ', 'Зохиомол алба юу хариуцдаг вэ?'):
            with self.subTest(query=query):
                result = chat(reception()).route('content.db', query)
                self.assertEqual(result['route'], 'C')
                self.assertEqual(result['answer_kind'], 'reception_table_lookup')
                self.assertTrue(result['answer'].startswith('Зохиомол алба: 4-р давхар, 406 тоот.'))
                self.assertIn('З.Тэмүүлэн — Сургалт хариуцсан мэргэжилтэн', result['answer'])
                self.assertEqual(result['query'], query)

    def test_the_card_can_be_recalled_for_listening_also_after_a_stop_of_the_router(self):
        # The router's own stops carry no response ID; the card made from one must, or «Сонсох» reads another text.
        for reason in ('no_supported_question_match', 'constraints_not_supported_together', 'missing_entity'):
            with self.subTest(reason=reason):
                made = chat(reception(), reason=reason)
                result = made.route('content.db', 'Зохиомол алба юу хийдэг вэ?')
                self.assertTrue(result['answer'].startswith('Зохиомол алба: 4-р давхар, 406 тоот.'))
                recalled = made.recall(result['response_id'], 'Зохиомол алба юу хийдэг вэ?', 'package1', False)
                self.assertEqual(recalled['answer'], result['answer'])

    def test_an_office_the_tables_do_not_name_stays_unanswered(self):
        result = chat(reception()).route('content.db', 'Байхгүй алба юу хийдэг вэ?')
        self.assertIsNone(result['answer'])

    def test_a_refusal_with_a_reason_of_its_own_and_an_answered_reply_are_left(self):
        made = chat(reception())
        refused = dict(query='Зохиомол алба юу хийдэг вэ?', route='E', answer=None, reason_code='personal_record_outside_scope',
                       message='Татгалзав.', citations=[])
        self.assertIsNone(made._office_card(refused, refused['query'], now=NOW)['answer'])
        answered = dict(query='Зохиомол алба юу хийдэг вэ?', route='B', answer='Хадгалсан хариулт.', citations=[],
                        reason_code='official_website_stored_answer')
        self.assertEqual(made._office_card(answered, answered['query'], now=NOW)['answer'], 'Хадгалсан хариулт.')

    def test_without_reception_tables_nothing_changes(self):
        self.assertIsNone(chat().route('content.db', 'Зохиомол алба юу хийдэг вэ?')['answer'])


if __name__ == '__main__':
    unittest.main()
