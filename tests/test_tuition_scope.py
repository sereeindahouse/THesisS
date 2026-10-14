import copy
import unittest
from test_rag_runtime import SOURCE, Policy, Retriever, Generator
from rag_runtime import ChatRAG, source_extract
from answer_contract import tuition_amount_query


class TuitionScopeTests(unittest.TestCase):
    def setUp(self):
        self.retriever, self.generator = Retriever(), Generator()
        self.policy = Policy(reason='unmatched_numeric_constraints')
        self.chat = ChatRAG('.', self.policy, self.retriever, self.generator)

    def test_monthly_amount_is_corrected_with_annual_source_not_division(self):
        for value in ['8,280,000', '8280000', '8 280 000', '9,999,999']:
            with self.subTest(amount=value):
                result = self.chat.route(None, f'Сургалтын төлбөр сард {value} төгрөг үү?')
                self.assertEqual(result['route'], 'A')
                self.assertIn('жилд 8,280,000', result['answer'])
                self.assertIn('Сарын төлбөрийн дүн, хуваарийг энд тодорхойлоогүй', result['answer'])
                self.assertNotIn('690,000', result['answer'])
                self.assertFalse(result['generated'])
        self.assertEqual(self.generator.calls, 0)

    def test_scope_is_preserved_for_discounts_foreign_students_and_installments(self):
        for question in ['Гадаад оюутны сургалтын төлбөр 8,280,000 уу?',
                         'Сургалтын төлбөрийн хөнгөлөлт 50 хувь уу?',
                         'Сургалтын төлбөрийг сард 690000-аар төлж болох уу?',
                         'Компьютерийн сургалтын төлбөр 8,280,000 уу?',
                         'Сургалтын төлбөр 8,280,000 эсвэл бүртгэлийн хураамж уу?',
                         'Сургалтын төлбөр өнөөдөр 8,280,000 уу?']:
            with self.subTest(question=question):
                self.assertFalse(tuition_amount_query(question))
                self.assertIsNone(self.chat.route(None, question)['answer'])
        self.assertEqual(self.retriever.calls, 0)

    def test_non_numeric_faq_guards_remain_binding(self):
        for reason in ['expired_content', 'content_rejected_or_unapproved', 'partial_answer',
                       'live_status_not_supported', 'future_validity']:
            self.policy.reason = reason
            self.assertEqual(self.chat.route(None, 'Сургалтын төлбөр 8280000 уу?')['reason_code'], reason)
        self.assertEqual(self.retriever.calls, 0)

    def test_unsupported_year_is_not_replaced(self):
        self.policy.reason = 'unsupported_year'
        result = self.chat.route(None, '2028 оны сургалтын төлбөр 8280000 уу?')
        self.assertIsNone(result['answer'])
        self.assertEqual(self.generator.calls, 0)

    def test_supported_year_can_use_web_source_beyond_faq_scope(self):
        self.policy.reason = 'unsupported_year'
        from unittest.mock import patch
        original = self.policy.route
        def faq_years(*args, **kwargs):
            return dict(original(*args, **kwargs), requested_years=['2026'], supported_years=['2025'])
        with patch.object(self.policy, 'route', faq_years):
            result = self.chat.route(None, '2026 оны сургалтын төлбөр 8280000 уу?')
        self.assertEqual(result['route'], 'A')
        self.assertIn('2026', result['answer'])
        self.assertEqual(result['requested_years'], ['2026'])
        self.assertNotIn('supported_years', result)
        self.assertEqual(result['faq_scope_handoff'],
                         {'reason_code': 'unsupported_year', 'supported_years': ['2025']})

    def test_no_matching_tuition_line_never_falls_through_to_llm(self):
        for url, text in [('https://nmct.edu.mn/elselt', 'Бүртгэлийн хураамж 20,000 ₮.'),
                          ('https://nmct.edu.mn/other', SOURCE['text'])]:
            self.retriever.sources[0].update(url=url, text=text)
            self.assertIsNone(self.chat.route(None, 'Сургалтын төлбөр 8280000 уу?')['answer'])
        self.assertEqual(self.generator.calls, 0)

    def test_exact_faq_or_disabled_policy_cannot_be_bypassed(self):
        from unittest.mock import patch
        original = self.policy.route
        def exact(*args, **kwargs):
            return dict(original(*args, **kwargs), exact_matches=['existing-faq'])
        with patch.object(self.policy, 'route', exact):
            self.chat.route(None, 'Сургалтын төлбөр 8280000 уу?')
        self.policy.enabled = False
        self.chat.route(None, 'Сургалтын төлбөр 8280000 уу?')
        self.assertEqual(self.retriever.calls, 0)

    def test_monthly_question_without_number_keeps_same_period_warning(self):
        self.policy.reason = 'no_supported_question_match'
        result = self.chat.route(None, 'Сургалтын төлбөр сард хэд вэ?')
        self.assertIn('жилээр заасан', result['answer'])
        self.assertEqual(self.generator.calls, 0)


if __name__ == '__main__': unittest.main()
