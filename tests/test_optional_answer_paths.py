"""FAKE in-memory routing contracts: no sockets, DB, audio or transcript files."""
from datetime import datetime
import tempfile
import unittest
from unittest.mock import Mock

from rag_runtime import ChatRAG
from stt_text_normalization import Normalizer


class Policy:
    enabled = True

    def route(self, database, query, *, allow_draft=False):
        if database is not None:
            raise AssertionError('Fake policy never opens a database')
        return dict(query=query, package_id='FAKE-package', route='E',
            reason_code='fake_original', answer=None, citations=[],
            generated=False, llm_calls=0, clarification=None)


class CapturingChat(ChatRAG):
    def _route(self, database, query, *, allow_draft=False, timings=None):
        self.seen.append(query)
        return self._remember(dict(query=query, package_id='FAKE-package', route='C',
            reason_code='fake_original', answer='FAKE ordinary answer', citations=[],
            generated=False, llm_calls=0), allow_draft)


class OptionalAnswerPathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def chat(self, *, normalizer=None, reception=None, reception_clock=None):
        if reception is None:
            reception = Mock(enabled=False)
            reception.answer.return_value = None
        value = CapturingChat(self.temp.name, Policy(), retriever=Mock(), generator=Mock(),
            normalizer=normalizer or Normalizer(), reception=reception,
            reception_clock=reception_clock)
        value.seen = []
        return value

    def test_missing_disabled_configs_preserve_original_route(self):
        value = CapturingChat(self.temp.name, Policy(), retriever=Mock(), generator=Mock())
        value.seen = []
        text = 'Зохиомол хоёр мянга хорин зургаан онд нээгдэв үү?'
        result = value.route(None, text, stt_text=True)
        self.assertEqual(value.seen, [text])
        self.assertEqual(result['query'], text)
        self.assertNotIn('search_normalization', result)
        self.assertEqual(result['reason_code'], 'fake_original')

    def test_typed_input_is_never_silently_normalized(self):
        value = self.chat(normalizer=Normalizer(enabled=True))
        text = 'Зохиомол хоёр мянга хорин зургаан онд нээгдэв үү?'
        result = value.route(None, text)
        self.assertEqual(value.seen, [text])
        self.assertNotIn('search_normalization', result)

    def test_stt_search_derivative_keeps_original_query_and_cached_tts_binding(self):
        value = self.chat(normalizer=Normalizer(enabled=True))
        text = 'Зохиомол хоёр мянга хорин зургаан онд БИШ!'
        result = value.route(None, text, stt_text=True)
        self.assertEqual(value.seen, ['Зохиомол 2026 онд БИШ!'])
        self.assertEqual(result['query'], text)
        proof = result['search_normalization']
        self.assertEqual(proof['original_text'], text)
        self.assertTrue(proof['automatic'])
        self.assertFalse(proof['human_correction_claimed'])
        self.assertEqual(value.recall(result['response_id'], text, 'FAKE-package', False), result)
        with self.assertRaises(ValueError):
            value.recall(result['response_id'], proof['normalized_search_text'], 'FAKE-package', False)

    def test_stt_opt_in_must_be_boolean_true(self):
        value = self.chat(normalizer=Normalizer(enabled=True))
        text = 'хоёр мянга хорин зургаан онд'
        value.route(None, text, stt_text='yes')
        self.assertEqual(value.seen, [text])

    def test_enabled_reception_lookup_bypasses_existing_selection(self):
        reception = Mock(enabled=True)
        reception.answer.return_value = dict(answer='FAKE өрөө: 2-р давхар.',
            message='FAKE fixture', reason_code='reception_room',
            reception=dict(physical_location_confirmed=False, is_fake=True))
        now = datetime(2031, 2, 3, 9, 15)
        value = self.chat(reception=reception, reception_clock=lambda: now)
        result = value.route(None, 'FAKE-101 өрөө хаана вэ?')
        reception.answer.assert_called_once_with('FAKE-101 өрөө хаана вэ?', now=now)
        self.assertEqual(value.seen, [])
        self.assertEqual(result['route'], 'C')
        self.assertEqual(result['answer_kind'], 'reception_table_lookup')
        self.assertFalse(result['generated'])
        self.assertEqual(result['llm_calls'], 0)
        self.assertEqual(result['citations'], [])
        self.assertEqual(value.recall(result['response_id'], result['query'], 'FAKE-package', False), result)

    def test_unavailable_reception_answer_cannot_fall_through_to_a_nearby_source(self):
        reception = Mock(enabled=True)
        reception.answer.return_value = dict(answer=None, message='FAKE хүснэгт дутуу.',
            reason_code='reception_unknown', reception=dict(is_fake=True))
        value = self.chat(reception=reception)
        result = value.route(None, 'FAKE багш хаана вэ?')
        self.assertEqual(result['route'], 'E')
        self.assertIsNone(result['answer'])
        self.assertEqual(value.seen, [])

    def test_combined_optional_paths_retain_original_and_table_provenance(self):
        reception = Mock(enabled=True)
        reception.answer.return_value = dict(answer='FAKE хуваариар: хичээлтэй.',
            message='FAKE', reason_code='reception_teacher', reception=dict(is_fake=True))
        value = self.chat(normalizer=Normalizer(enabled=True), reception=reception)
        text = 'Зохиомол багш хорин хоёр цагт хаана вэ?'
        result = value.route(None, text, stt_text=True)
        self.assertEqual(reception.answer.call_args.args, ('Зохиомол багш 22 цагт хаана вэ?',))
        self.assertEqual(result['query'], text)
        self.assertTrue(result['search_normalization']['changed'])
        self.assertTrue(result['reception']['is_fake'])
        self.assertEqual(value.seen, [])

    def test_actual_router_keeps_year_and_negation_guards_after_normalizing(self):
        from tests.test_rag_runtime import SOURCE, Policy as RoutingPolicy, Retriever, Generator
        retriever, generator = Retriever(), Generator()
        retriever.sources = [dict(SOURCE, title='Зохиомол архив',
            text='Зохиомол архив 2022 онд нээгдэв.',
            excerpt='Зохиомол архив 2022 онд нээгдэв.')]
        seen = []
        original_search = retriever.search

        def capture(query, **kwargs):
            seen.append(query)
            return original_search(query, **kwargs)

        retriever.search = capture
        chat = ChatRAG(self.temp.name, RoutingPolicy(), retriever, generator,
            normalizer=Normalizer(enabled=True))
        text = 'Зохиомол архив хоёр мянга хорин долоон онд нээгдсэн БИШ үү?'
        result = chat.route(None, text, stt_text=True)
        self.assertEqual(seen, ['Зохиомол архив 2027 онд нээгдсэн БИШ үү?'])
        self.assertEqual(result['reason_code'], 'requested_year_not_supported')
        self.assertIsNone(result['answer'])
        self.assertEqual(generator.calls, 0)
        self.assertEqual(result['query'], text)

    def test_actual_router_default_uses_existing_selector_and_no_reception_route(self):
        from tests.test_rag_runtime import Policy as RoutingPolicy, Retriever, Generator
        retriever, generator = Retriever(), Generator()
        chat = ChatRAG(self.temp.name, RoutingPolicy(), retriever, generator)
        baseline = chat._route(None, 'Сургалтын төлбөр хэд вэ?')
        result = chat.route(None, 'Сургалтын төлбөр хэд вэ?')
        for field in ('route', 'answer', 'citations', 'reason_code', 'llm_calls'):
            self.assertEqual(result[field], baseline[field])
        self.assertNotIn('search_normalization', result)
        self.assertNotIn('reception', result)


if __name__ == '__main__':
    unittest.main()
