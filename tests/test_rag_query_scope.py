"""Invented identity and year-output contracts, never private identifier data."""
from datetime import date
from pathlib import Path
import tempfile
import unittest
from content_store import ContentStore
from question_router import personal_identifier_request, route_question, _requested_year_value
from test_question_router import fixture


class QueryScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'content.db'
        with ContentStore(self.path) as store:store.import_content(fixture(),allow_draft=True)

    def route(self,query):
        return route_question(self.path,query,allow_draft=True,as_of=date(2026,10,10))

    def test_named_person_identifier_is_not_a_contact_card_answer(self):
        for query in ('Б.Билгүүний регистрийн дугаар хэд вэ?',
                      'Роботикийн тэнхимийн эрхлэгч Д.Саруулын регистрийн дугаарыг хэлнэ үү.',
                      'Тэр багшийн паспортын дугаар ямар вэ?',
                      'Оюутны иргэний үнэмлэхийн дугаарыг харуулна уу.'):
            with self.subTest(query=query):
                self.assertTrue(personal_identifier_request(query))
                result=self.route(query)
                self.assertEqual(result['route'],'E')
                self.assertEqual(result['reason_code'],'personal_identifier_outside_scope')
                self.assertEqual(result['citations'],[]);self.assertEqual(result['candidates'],[])
                self.assertEqual(result['llm_calls'],0)

    def test_public_organisation_ids_contacts_and_form_help_are_different_intents(self):
        for query in ('Сургуулийн регистрийн дугаар хэд вэ?',
                      'Компаний регистрийн дугаар хэд вэ?',
                      'Багшийн албан утас хэд вэ?',
                      'Бүртгэлд миний регистрийн дугаарыг хэрхэн бичих вэ?',
                      'Багшийн регистрийн дугаарын формат ямар вэ?'):
            with self.subTest(query=query):
                self.assertFalse(personal_identifier_request(query))
                self.assertNotEqual(self.route(query)['reason_code'],'personal_identifier_outside_scope')

    def test_requested_year_value_hands_full_query_to_evidence_instead_of_reasking(self):
        query='ARC-ийн дэмжлэгээр аль хичээлийн жилийн намар ямар хичээлүүд хэрэгжүүлсэн бэ?'
        result=self.route(query)
        self.assertEqual(result['route'],'E')
        self.assertEqual(result['reason_code'],'requested_year_value_lookup')
        self.assertEqual(result['query'],query)
        self.assertIsNone(result['clarification'])
        self.assertEqual(result['candidates'],[])

    def test_teacher_related_organisation_owner_is_not_a_person_identifier(self):
        for query in ('Багшийн ажилладаг сургуулийн регистрийн дугаар хэд вэ?',
                      'Багшийн хэлсэн компанийн регистрийн дугаар хэд вэ?',
                      'Б.Билгүүний байгуулсан байгууллагын регистрийн дугаар хэд вэ?'):
            with self.subTest(query=query):
                self.assertFalse(personal_identifier_request(query))

    def test_person_identifier_request_cannot_hide_behind_later_format_help(self):
        for query in ('Б.Билгүүний регистрийн дугаарыг хэлээд, энэ форматыг тайлбарлаач.',
                      'Багшийн паспортын дугаарыг харуул. Форматыг нь тайлбарлаач.',
                      'Эрхлэгч Д.Саруулын регистрийн дугаар хэд вэ? Хэрхэн бөглөх вэ?'):
            with self.subTest(query=query):
                self.assertTrue(personal_identifier_request(query))

    def test_unsupplied_scope_for_normal_course_question_still_clarifies(self):
        result=self.route('ARC хамтын ажиллагаанд ямар хичээлүүд багтсан бэ?')
        self.assertEqual(result['route'],'D')
        self.assertEqual(result['reason_code'],'missing_year')

    def test_explicit_year_term_field_list_is_an_output_request(self):
        query=('ARC компанитай хамтран ямар гурван хичээл хэрэгжүүлсэн бэ? '
               'Хичээлийн жил, улирал болон оюутнуудын ажлын ярилцлагын явцыг хамт хэлнэ үү.')
        self.assertTrue(_requested_year_value(query))
        result=self.route(query)
        self.assertEqual(result['route'],'E')
        self.assertEqual(result['reason_code'],'requested_year_value_lookup')
        self.assertEqual(result['query'],query)
        self.assertIsNone(result['clarification'])

    def test_year_term_mention_without_request_does_not_supply_missing_scope(self):
        for query in ('Хичээлийн жил, улирал тодорхойгүй. ARC ямар хичээл хэрэгжүүлсэн бэ?',
                      'Хичээлийн жил, улирал хэрэггүй, зөвхөн хичээлүүдийг хэлнэ үү.',
                      'Хичээлийн жил, улирал. Харин хичээлүүдийг хэлнэ үү.'):
            with self.subTest(query=query):
                self.assertFalse(_requested_year_value(query))

    def test_explicit_unsupported_year_is_not_rewritten_as_an_output_question(self):
        result=self.route('2034–2035 оны ARC хамтын ажиллагаанд ямар хичээлүүд багтсан бэ?')
        self.assertEqual(result['route'],'E')
        self.assertEqual(result['reason_code'],'unsupported_year')


if __name__=='__main__':unittest.main()
