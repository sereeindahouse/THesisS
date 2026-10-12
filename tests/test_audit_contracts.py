"""Independent-review counterexamples; development regressions, not accuracy."""
import copy
import json
import time
import unittest
from unittest.mock import patch

from test_rag_runtime import Policy, Retriever, Generator, SOURCE
from rag_runtime import ChatRAG, GroundedGenerator, focused_extract


class AuditContracts(unittest.TestCase):
    def chat(self, text=None, visual=False):
        retriever, generator = Retriever(), Generator()
        if text:
            retriever.sources[0].update(text=text, excerpt=text,
                url='https://nmct.edu.mn/rule.png',
                text_scope='document_visual_excerpt' if visual else 'main_element')
        return ChatRAG('.', Policy(), retriever, generator), retriever, generator

    def test_result_announcement_never_uses_interview_duration(self):
        for query in ['Ярилцлагын шалгалтын дүн хэдэн минутын дараа гарах вэ?',
                      'Ярилцлагын хариу гарах хугацаа хэд вэ?',
                      'Ярилцлагын үр дүнг хэзээ зарлах вэ?']:
            with self.subTest(query=query):
                chat, retriever, generator = self.chat(
                    'Ярилцлагын шалгалт 15 минут үргэлжилнэ. Нийт 20 оноо.', True)
                self.assertIsNone(focused_extract(query, retriever.sources))
                result = chat.route(None, query)
                self.assertIsNone(result['answer'])
                self.assertEqual(result['reason_code'], 'requested_attribute_not_supported')
                self.assertEqual(generator.calls, 0)

    def test_date_is_not_an_exact_minutes_after_answer(self):
        chat, _, generator = self.chat('Ярилцлагын дүнг 8 сарын 15-нд зарлана.')
        result = chat.route(None, 'Ярилцлагын дүн хэдэн минутын дараа гарах вэ?')
        self.assertIsNone(result['answer'])
        self.assertEqual(generator.calls, 0)

    def test_actual_result_source_can_reach_generation(self):
        chat, _, generator = self.chat('Ярилцлагын дүнг 8 сарын 15-нд зарлана.')
        chat.route(None, 'Ярилцлагын дүнг хэзээ зарлах вэ?')
        self.assertEqual(generator.calls, 1)

    def test_aliases_share_concept_guard(self):
        for name in ['Коосэн', 'Kosen', 'KOSEN']:
            with self.subTest(name=name):
                chat, _, generator = self.chat('Коосэн KIS уулзалт зохион байгууллаа.')
                result = chat.route(None, name + ' сургалтын онцлог юу вэ?')
                self.assertEqual(result['reason_code'], 'concept_overview_not_supported')
                self.assertEqual(generator.calls, 0)

    def test_ambiguous_registration_fee_clarifies(self):
        chat, retriever, generator = self.chat()
        retriever.sources = [dict(SOURCE, url='https://nmct.edu.mn/elselt'),
                             dict(SOURCE, source_id='olympiad', url='https://nmct.edu.mn/olympiad/rules.pdf')]
        result = chat.route(None, 'Бүртгэлийн хураамж хэдэн төгрөг вэ?')
        self.assertEqual(result['route'], 'D')
        self.assertEqual(result['reason_code'], 'registration_scope_ambiguous')
        self.assertEqual(generator.calls, 0)
        self.assertEqual(len(result['suggestions']), 2)

    def test_explicit_registration_scope_filters_generator_sources(self):
        for word, url in [('Элсэлтийн', 'https://nmct.edu.mn/elselt'),
                          ('Олимпиадын', 'https://nmct.edu.mn/olympiad/rules.pdf')]:
            with self.subTest(word=word):
                chat, retriever, generator = self.chat()
                retriever.sources = [dict(SOURCE), dict(SOURCE, source_id='other',
                    url='https://nmct.edu.mn/olympiad/rules.pdf')]
                with patch.object(generator, 'generate', return_value=dict(generated=False, llm_calls=0,
                        claims=[], reason='insufficient_evidence')) as generate:
                    chat.route(None, word+' бүртгэлийн хураамж хэд вэ?')
                self.assertEqual({s['url'] for s in generate.call_args.args[1]}, {url})

    def test_latency_contains_retrieval_and_generation(self):
        chat, retriever, generator = self.chat()
        search, generate = retriever.search, generator.generate
        def slow_search(*args, **kwargs):
            time.sleep(.08)
            return search(*args, **kwargs)
        def slow_generate(*args, **kwargs):
            time.sleep(.12)
            return generate(*args, **kwargs)
        with patch.object(retriever, 'search', slow_search), patch.object(generator, 'generate', slow_generate):
            start = time.perf_counter()
            result = chat.route(None, 'Төлбөр хэд вэ?')
            wall = (time.perf_counter() - start) * 1000
        self.assertGreaterEqual(result['latency_ms'], 190)
        self.assertLessEqual(result['latency_ms'], wall + 1)
        self.assertGreaterEqual(result['timings_ms']['retrieval'], 75)
        self.assertGreaterEqual(result['timings_ms']['generation'], 115)
        self.assertEqual(chat.recall(result['response_id'], result['query'], 'package1', False)['latency_ms'], result['latency_ms'])

    def test_oversize_exact_extract_stays_readable_without_false_listen(self):
        chat, _, _ = self.chat()
        with patch('rag_runtime.source_extract', return_value=(SOURCE, 'Эхийн нөхцөл. ' * 200)):
            result = chat.route(None, 'Төлбөр хэд вэ?')
        self.assertGreater(len(result['answer']), 2000)
        self.assertFalse(result['can_speak'])
        self.assertEqual(result['speech_unavailable_reason'], 'answer_exceeds_speech_budget')


class ClaimContracts(unittest.TestCase):
    def generate(self, text, source_text=SOURCE['text'], copies=1):
        source = dict(SOURCE, text=source_text)
        proposal = dict(insufficient=False, claims=[dict(source_id=source['source_id'], text=text) for _ in range(copies)])
        generator = GroundedGenerator('.')
        generator.model = 'test'
        with patch.object(generator, 'status', return_value=dict(available=True)), patch.object(
                generator, '_request', return_value=dict(done=True, message=dict(content=json.dumps(proposal)))):
            return generator.generate('Төлбөр хэд вэ?', [source])

    def test_yearly_fee_cannot_become_monthly_with_same_number(self):
        result = self.generate('Сургалтын төлбөр сард 8,280,000 ₮.')
        self.assertFalse(result['generated'])
        self.assertEqual(result['reason'], 'unsupported_quantity_context')

    def test_registration_fee_cannot_become_tuition(self):
        result = self.generate('Сургалтын төлбөр 20,000 төгрөг.', 'Бүртгэлийн хураамж 20,000 төгрөг.')
        self.assertFalse(result['generated'])

    def test_units_attach_to_same_number_not_whole_source(self):
        result = self.generate('Сургалтын төлбөр сард 8,280,000 ₮.',
            'Сургалтын төлбөр жилд 8,280,000 ₮. Дотуур байрны төлбөр сард 200,000 ₮.')
        self.assertFalse(result['generated'])

    def test_correct_monthly_fee_is_accepted(self):
        text = 'Сургалтын төлбөр сард 690,000 ₮.'
        self.assertTrue(self.generate(text, text)['generated'])

    def test_html_fee_label_on_previous_line_is_supported(self):
        result = self.generate('Бүртгэлийн хураамж 5,000 ₮.',
            'Байгалийн ухааны олимпиад\nБүртгэлийн хураамж\n5,000 ₮\nХичээл')
        self.assertTrue(result['generated'])

    def test_semantic_guard_is_not_a_general_entailment_proof(self):
        # Known residual blind spot explicitly retained in the evidence.
        result = self.generate('Элсэх эрхийг бусдад шилжүүлж болно.',
            'Элсэх эрхийг бусдад шилжүүлэхийг хориглоно.')
        self.assertTrue(result['generated'])

    def test_total_generated_answer_fits_speech_budget(self):
        text = 'Т' * 850
        result = self.generate(text, text, copies=3)
        self.assertFalse(result['generated'])
        self.assertEqual(result['reason'], 'answer_exceeds_speech_budget')


if __name__ == '__main__':
    unittest.main()
