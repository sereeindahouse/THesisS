"""Constructed scope controls for the supplied-grade eligibility boundary."""
import unittest

from rag_runtime import ChatRAG, supplied_grade_study_eligibility
from test_rag_runtime import Policy, Retriever, Generator


class SuppliedGradeEligibilityTests(unittest.TestCase):
    def test_grade_number_and_condition_are_bound_in_the_study_question(self):
        for query in (
            'Миний голч дүн 3.0 бол Японд дэвших боломжтой юу?',
            'Голч маань 2.75 байвал Японд суралцах эрхтэй юу?',
            'GPA 3,2 гэж үзвэл Японд сурах боломжгүй юу?',
        ):
            with self.subTest(query=query):
                self.assertTrue(supplied_grade_study_eligibility(query))

    def test_years_unbound_numbers_and_negated_topic_are_not_given_grades(self):
        for query in (
            '2027 онд Японд суралцахад голч дүнгийн ямар шаардлага тавьдаг, боломжтой юу?',
            'Японд сурах боломж, голч дүнгийн шаардлага болон 3 хөтөлбөрийн талаар хэлнэ үү.',
            'Голч дүнгийн талаар 3 асуулт байна. Японд сурах боломжтой юу?',
            'Голч дүн 3.0 гэдгийг тайлбарлаач. Японд сурах боломжийн талаар дараа асууя.',
            'Миний голч дүн 3.0 бол Японд сурах боломжийг асуугаагүй, ажиллах нөхцөлийг хэлнэ үү.',
            'Миний голч 3.0 бол Японд сурах биш ажиллах боломжтой юу?',
            'Миний голч дүн хэд вэ? Японд 2027 онд суралцах боломжтой юу?',
            'GPA 3.0 бол Монголд сурах боломжтой юу?',
            'Японд 3 жил суралцах боломжтой юу?',
        ):
            with self.subTest(query=query):
                self.assertFalse(supplied_grade_study_eligibility(query))

    def test_normal_handoff_returns_uncertainty_without_job_roadmap(self):
        retriever, generator = Retriever(), Generator()
        result = ChatRAG('.', Policy(), retriever, generator).route(
            None, 'Миний голч дүн 3.0 бол Японд дэвших боломжтой юу?')
        self.assertEqual(result['reason_code'], 'supplied_grade_eligibility_not_verified')
        self.assertIsNone(result['answer'])
        self.assertEqual(result['citations'], [])
        self.assertEqual(retriever.calls, 0)
        self.assertEqual(generator.calls, 0)

    def test_existing_hard_boundaries_keep_their_original_reason(self):
        query = 'Миний голч дүн 3.0 бол Японд дэвших боломжтой юу?'
        for reason in ('personal_record_outside_scope', 'personal_identifier_outside_scope',
                       'invalid_year_range', 'expired_content', 'content_rejected_or_unapproved'):
            with self.subTest(reason=reason):
                retriever, generator = Retriever(), Generator()
                result = ChatRAG('.', Policy(reason=reason), retriever, generator).route(None, query)
                self.assertEqual(result['reason_code'], reason)
                self.assertEqual(retriever.calls, 0)
                self.assertEqual(generator.calls, 0)


if __name__ == '__main__':
    unittest.main()
