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

    def test_generic_dated_tuition_can_reach_exact_website_amount(self):
        self.policy.reason = 'constrained_wording_not_exact'
        result = self.chat.route(None, '2026 оны сургалтын төлбөр хэд вэ?')
        self.assertEqual(result['route'], 'A')
        self.assertIn('8,280,000', result['answer'])
        self.assertEqual(self.generator.calls, 0)

    def test_generic_future_tuition_does_not_end_in_empty_clarification(self):
        self.policy.reason = 'constrained_wording_not_exact'
        result = self.chat.route(None, '2027 оны сургалтын төлбөр хэд вэ?')
        self.assertEqual(result['route'], 'E')
        self.assertEqual(result['reason_code'], 'requested_year_not_supported')
        self.assertIsNone(result['answer'])
        self.assertIsNone(result['clarification'])
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

    def test_colloquial_tuition_keeps_source_amount_and_annual_period(self):
        # Constructed amount differs from the real site's number: the answer
        # must come from the selected source rather than a memorised value.
        text = 'Сургалтын төлбөр: жилд 9,360,000 ₮.'
        self.retriever.sources[0].update(text=text, excerpt=text)
        for query in [
            '2026 оны элсэлтийн хуудсаар сургалтын мөнгө жилд хэд болдог юм бэ, тэр дүнг сарын төлбөр гэж ойлгох уу?',
            'Сургалтын мөнгө сард хэд вэ?',
            'Сургалтын мөнгийг жилээр хэдэн төгрөг гэж ойлгох вэ?',
        ]:
            with self.subTest(query=query):
                result = self.chat.route(None, query)
                self.assertEqual(result['route'], 'A')
                self.assertIn(text, result['answer'])
                self.assertNotIn('8,280,000', result['answer'])
                self.assertNotIn('780,000', result['answer'])
                if 'сар' in query:
                    self.assertIn('Сарын төлбөрийн дүн, хуваарийг энд тодорхойлоогүй', result['answer'])
        self.assertEqual(self.generator.calls, 0)

    def test_colloquial_tuition_preserves_supported_and_unsupported_years(self):
        self.policy.reason = 'constrained_wording_not_exact'
        accepted = self.chat.route(None, '2026 оны сургалтын мөнгө хэд вэ?')
        self.assertEqual(accepted['route'], 'A')
        refused = self.chat.route(None, '2027 оны сургалтын мөнгө хэд вэ?')
        self.assertEqual(refused['route'], 'E')
        self.assertEqual(refused['reason_code'], 'requested_year_not_supported')
        self.assertIsNone(refused['answer'])
        self.assertEqual(self.generator.calls, 0)

    def test_money_alias_cannot_bypass_other_cost_group_or_negative_qualifiers(self):
        for query in [
            'Хоолны мөнгө сард хэд вэ?',
            'Дотуур байрны мөнгө сард хэд вэ?',
            'Сарын мөнгө хэд вэ?',
            'Сургалтын мөнгө сард өгдөг үү?',
            'Сургалтын мөнгө тэтгэлгээр олгодог уу?',
            'Сургалтын мөнгө биш, дотуур байрны төлбөр хэд вэ?',
            'Сургалтын мөнгөний хөнгөлөлт 50 хувь уу?',
            'Гадаад оюутны сургалтын мөнгө хэд вэ?',
            'Компьютерийн сургалтын мөнгө хэд вэ?',
            'Сургалтын мөнгө буцааж олгох уу?',
            'Сургалтын мөнгө өнөөдөр хэд вэ?',
            '2027 оны гадаад оюутны сургалтын мөнгө хэд вэ?',
        ]:
            with self.subTest(query=query):
                self.assertFalse(tuition_amount_query(query))
                result = self.chat.route(None, query)
                self.assertIsNone(result['answer'])
        self.assertEqual(self.retriever.calls, 0)
        self.assertEqual(self.generator.calls, 0)

    def test_colloquial_instalment_request_cannot_use_annual_amount_as_schedule(self):
        self.policy.reason = 'no_supported_question_match'
        result = self.chat.route(None, 'Сургалтын мөнгийг сараар хувааж төлөх хуваарь бий юу?')
        self.assertIsNone(result['answer'])
        self.assertEqual(result['reason_code'], 'requested_attribute_not_supported')
        self.assertEqual(self.generator.calls, 0)

    def test_colloquial_tuition_still_requires_its_exact_source_label(self):
        self.retriever.sources[0].update(text='Дотуур байрны төлбөр: жилд 9,360,000 ₮.')
        result = self.chat.route(None, 'Сургалтын мөнгө 9360000 төгрөг үү?')
        self.assertIsNone(result['answer'])
        self.assertEqual(result['reason_code'], 'tuition_amount_source_not_supported')
        self.assertEqual(self.generator.calls, 0)


if __name__ == '__main__': unittest.main()
