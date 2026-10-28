"""Invented private-record wording regressions; no real grades or accounts."""
from datetime import date
from pathlib import Path
import tempfile
import unittest

from content_store import ContentStore
from question_router import personal_record_request, personal_record_service_request, route_question
from rag_runtime import ChatRAG
from test_question_router import fixture


PRIVATE_REQUESTS = (
    'Миний энэ улирлын голч дүн хэд гарсан бэ?',
    'Миний голч дүн хэд вэ?',
    'Голчоо харуулаач.',
    'Энэ улирлын дүнгээ үзүүлнэ үү.',
    'Миний математикийн дүнг хэлээд өгөөч.',
    'Дүнгийн хуудсыг минь харуулна уу.',
    'Миний энэ сарын ирц хэдэн хувьтай байна вэ?',
    'Ирцээ шалгаад өгөөч.',
    'Тэр оюутны дүнг харуул.',
    'Б.Саруулын ирцийг хэлээд өгөөч.',
    'Манай ангийн энэ улирлын дүнг харуул.',
    'Миний сургалтын төлбөрийн үлдэгдэл хэд вэ?',
    'Төлбөрийн үлдэгдлээ хармаар байна, харуулаач.',
    'Миний төлсөн төлбөрийн баримтыг гаргаад өгөөч.',
    'Миний гүйлгээний түүхийг харуул.',
    'Би сургалтын төлбөрөө төлсөн үү?',
    'Миний мөнгө дансанд орсон уу?',
    'Миний голч дүн 3.0 болсон уу, шалгаад өгөөч.',
    'Миний хураамж орсон уу?',
)

PUBLIC_OR_HELP_REQUESTS = (
    'Японд дэвшин суралцахад голч дүн хэд байх ёстой вэ?',
    'Оюутны голч дүн хэрхэн тооцдог вэ?',
    'Миний голч дүн 3.0 бол Японд дэвших боломжтой юу?',
    'Миний голч 2.5 байвал ямар тэтгэлэгт хамрагдах боломжтой вэ?',
    'Миний голч дүнг 3.0 гэж үзвэл ямар тэтгэлэг авах боломжтой вэ?',
    'Миний голч дүн хэд байх ёстой вэ?',
    'Миний голч дүн 3.0 байсан бол ямар тэтгэлэг авах вэ?',
    'Ирцээ хаана шалгах вэ?',
    'Өөрийн дүнгийн хуудсыг хэрхэн авах вэ?',
    'Өөрийн дүнгээ хаанаас харах вэ?',
    'Өөрийн дүнгээ хаанаас хэлээд авах вэ?',
    'Миний төлсөн төлбөр орсон эсэхийг хаана шалгах вэ?',
    'Миний төлбөрийн үлдэгдлийг хэрхэн шалгах вэ?',
    'Төлбөрөө яаж төлөх вэ?',
    'Бүртгэлийн мөнгөө шилжүүлчихвэл би оюутан болсон гэсэн үг үү?',
    'Элсэлтийн хураамжаа төлсөн бол суралцах эрх маань шууд баталгаажих уу?',
    'Элсэлтийн төлбөрөө төлсөн байвал элсэн суралцах эрх баталгаажих уу?',
    'Хураамжаа төлсөн бол оюутан болох уу, тайлбарлаад өгөөч.',
    'Сургалтын төлбөр хэд вэ?',
    'Ирцийн ерөнхий шаардлага хэдэн хувь байдаг вэ?',
    'Химийн тэнхимийн сургалтын үр дүн ямар вэ?',
    'Төлбөрийн гүйлгээний утгад юу бичих вэ?',
    'Миний дүнг харуулах хэрэггүй. Японд дэвшихэд голч дүнгийн ямар шаардлага тавьдаг вэ?',
    'Миний дүнг асуугаагүй, зөвхөн голч дүнгийн шаардлагыг хэлнэ үү.',
    'Миний голчийг биш, сургуулийн нийтэлсэн голч дүнгийн шаардлагыг хэлнэ үү.',
    'Миний дүнг битгий харуул. Оюутны голч дүнгийн шаардлагыг хэлээрэй.',
)


class PrivateRecordScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'content.db'
        content = fixture()
        # Even a stored alias cannot authorize substituting a public answer
        # for a private result. All test values are invented fixture records.
        content['faqs'][0]['question_aliases'].append(PRIVATE_REQUESTS[0])
        with ContentStore(self.db) as store:
            store.import_content(content, allow_draft=True)

    def route(self, query):
        return route_question(self.db, query, allow_draft=True, as_of=date(2026, 10, 10))

    def test_private_results_do_not_return_public_evidence_or_exact_alias_answer(self):
        before = self.db.read_bytes()
        for query in PRIVATE_REQUESTS:
            with self.subTest(query=query):
                self.assertTrue(personal_record_request(query))
                result = self.route(query)
                self.assertEqual(result['route'], 'E')
                self.assertEqual(result['reason_code'], 'personal_record_outside_scope')
                self.assertIsNone(result['answer'])
                self.assertIsNone(result['clarification'])
                self.assertEqual(result['citations'], [])
                self.assertEqual(result['candidates'], [])
                self.assertEqual(result['exact_matches'], [])
                self.assertEqual(result['llm_calls'], 0)
                self.assertIn('хувийн', result['message'])
        self.assertEqual(before, self.db.read_bytes())

    def test_general_policy_given_values_and_portal_help_are_not_private_lookups(self):
        for query in PUBLIC_OR_HELP_REQUESTS:
            with self.subTest(query=query):
                self.assertFalse(personal_record_request(query))
                self.assertNotEqual(self.route(query)['reason_code'], 'personal_record_outside_scope')

    def test_later_general_help_does_not_hide_a_separate_private_lookup(self):
        for query in (
            'Миний голч дүн хэд вэ? Ерөнхий голч дүнг хэрхэн тооцдог вэ?',
            'Голч дүнгээ яаж харах вэ? Миний ирц хэд вэ?',
            'Миний төлсөн төлбөр орсон уу? Хаана шалгах вэ?',
            'Миний голч хэд вэ. Харин голч дүн 3.0 бол Японд суралцах боломжтой юу?',
            'Миний голчийг харуулах хэрэггүй; миний ирц хэд байгааг хэлээд өгөөч.',
            'Миний хураамж орсон уу? Хураамжаа төлсөн бол суралцах эрх баталгаажих уу?',
            'Хураамжаа төлсөн бол суралцах эрх баталгаажих уу? Миний хураамж орсон уу?',
            'Миний хураамж орсон эсэхийг шалгаад өгөөч, хураамжаа төлсөн бол суралцах эрх баталгаажих уу?',
        ):
            with self.subTest(query=query):
                self.assertTrue(personal_record_request(query))
                self.assertEqual(self.route(query)['reason_code'], 'personal_record_outside_scope')

    def test_own_record_access_help_has_a_separate_capability_response(self):
        for query in (
            'Өөрийн дүнгээ хаанаас харах вэ?',
            'Ирцээ хаана шалгах вэ?',
            'Өөрийн дүнгийн хуудсыг хэрхэн авах вэ?',
            'Миний төлсөн төлбөр орсон эсэхийг хаана шалгах вэ?',
            'Миний төлбөрийн үлдэгдлийг хэрхэн шалгах вэ?',
        ):
            with self.subTest(query=query):
                self.assertFalse(personal_record_request(query))
                self.assertTrue(personal_record_service_request(query))
                result = self.route(query)
                self.assertEqual(result['route'], 'E')
                self.assertEqual(result['reason_code'], 'personal_record_service_unavailable')
                self.assertIsNone(result['answer'])
                self.assertEqual(result['citations'], [])
                self.assertEqual(result['candidates'], [])
                self.assertEqual(result['llm_calls'], 0)
                self.assertIn('холбогдоогүй', result['message'])

    def test_capability_response_does_not_capture_methods_policies_or_admission_results(self):
        for query in (
            'Оюутны голч дүн хэрхэн тооцдог вэ?',
            'Голчоо хэрхэн тооцож харах вэ?',
            'Миний голч дүн 3.0 бол Японд дэвших боломжтой юу?',
            'Миний голч дүн 3.0 бол Японд дэвших эрхээ хэрхэн шалгах вэ?',
            'Элсэлтийн шалгалтын дүнг хаанаас харах вэ?',
            'Элсэлтийн бүртгэлийн мэдээллээ хэрхэн харах вэ?',
        ):
            with self.subTest(query=query):
                self.assertFalse(personal_record_service_request(query))
                self.assertNotEqual(self.route(query)['reason_code'], 'personal_record_service_unavailable')

    def test_actual_chat_route_stops_before_web_search_or_provider(self):
        outer = self

        class Policy:
            enabled = True

            def route(self, db, query, allow_draft=False):
                return outer.route(query)

        class NeverCalled:
            def search(self, *args, **kwargs):
                raise AssertionError('Private lookup reached website retrieval')

            def generate(self, *args, **kwargs):
                raise AssertionError('Private lookup reached the LLM')

        chat = ChatRAG('.', Policy(), retriever=NeverCalled(), generator=NeverCalled())
        for query in (PRIVATE_REQUESTS[0], PRIVATE_REQUESTS[6], PRIVATE_REQUESTS[10],
                      'Өөрийн дүнгээ хаанаас харах вэ?'):
            with self.subTest(query=query):
                result = chat.route(self.db, query)
                self.assertIn(result['reason_code'], ('personal_record_outside_scope',
                                                     'personal_record_service_unavailable'))
                self.assertEqual(result['llm_calls'], 0)
                self.assertEqual(result['citations'], [])
                self.assertEqual(result['related_sources'], [])


if __name__ == '__main__':
    unittest.main()
