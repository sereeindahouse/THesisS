"""The configured default makes no LLM request; the Gemma code stays selectable."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import demo_server
from llm_runtime import LLMRuntime
from rag_runtime import ChatRAG, GroundedGenerator
from rule_selector import (GEMMA_SELECTOR, RULE_SELECTOR, RuleSelectionGenerator, SAFE_DEFAULT,
                           answer_selection, bounded_lexical_selection, default_generator, key_term_coverage,
                           relevant_to_question)

ROOT = Path(__file__).resolve().parents[1]
PHONE_SOURCE = dict(source_id='fixture.contact', version='v1', title='Холбоо барих', url='https://nmct.edu.mn/fixture',
                    chunk_id=1, retrieved_at='2026-10-10', page_header='Холбоо барих', start_offset=0,
                    text='Сургуулийн утасны дугаар 77001234 байна.\nНомын сан хичээлийн өдрүүдэд ажиллана.')


class Retriever:
    def __init__(self, candidates):
        self.candidates = candidates

    def status(self):
        return dict(corpus_id='fixture')

    def search(self, query, limit=5):
        return dict(candidates=self.candidates, corpus_id='fixture')


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'config').mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def write(self, text):
        (self.root / 'config/answer-selection.json').write_text(text, encoding='utf-8')

    def test_project_configuration_disables_every_local_llm(self):
        self.assertEqual(answer_selection(ROOT), dict(selector=RULE_SELECTOR, local_llm_enabled=False,
                                                      single_unit_coverage=False))
        self.assertIsInstance(default_generator(ROOT), RuleSelectionGenerator)
        self.assertFalse(default_generator(ROOT).single_unit_coverage)

    def test_single_unit_stage_is_off_unless_configured_as_a_boolean(self):
        self.write(json.dumps(dict(selector=RULE_SELECTOR, local_llm_enabled=False)))
        self.assertFalse(answer_selection(self.root)['single_unit_coverage'])
        self.write(json.dumps(dict(selector=RULE_SELECTOR, local_llm_enabled=False, single_unit_coverage='yes')))
        self.assertEqual(answer_selection(self.root), SAFE_DEFAULT)
        self.write(json.dumps(dict(selector=RULE_SELECTOR, local_llm_enabled=False, single_unit_coverage=True)))
        self.assertTrue(default_generator(self.root).single_unit_coverage)
        self.assertTrue(default_generator(self.root).status()['single_unit_coverage'])

    def test_missing_or_damaged_configuration_fails_closed_to_no_llm(self):
        self.assertEqual(answer_selection(self.root), SAFE_DEFAULT)
        for text in ('{', '[]', '{"selector":"other","local_llm_enabled":true}',
                     '{"selector":"%s","local_llm_enabled":"yes"}' % RULE_SELECTOR,
                     '{"selector":"%s","local_llm_enabled":false}' % GEMMA_SELECTOR):
            self.write(text)
            self.assertEqual(answer_selection(self.root), SAFE_DEFAULT, text)

    def test_gemma_remains_selectable_by_configuration(self):
        self.write(json.dumps(dict(selector=GEMMA_SELECTOR, local_llm_enabled=True)))
        self.assertIsInstance(default_generator(self.root), GroundedGenerator)

    def test_environment_cannot_reenable_correction_llm(self):
        (self.root / 'runtime').mkdir()
        (self.root / 'runtime/rag-model.json').write_text(json.dumps(dict(
            model='fixture-model', stt_correction_from_rag=True)), encoding='utf-8')
        with patch.dict('os.environ', THESIS_LLM_MODEL='fixture-model'):
            runtime = demo_server._transcription_corrector(self.root, None)
        self.assertFalse(runtime.configured)
        self.assertEqual(runtime.status()['llm_calls'], 0)
        self.assertFalse(runtime.status()['network_probe'])


class CommonQuestionAliasTests(unittest.TestCase):
    def test_closed_wordings_reach_the_stored_question_and_others_do_not(self):
        from rag_runtime import common_question_alias as alias
        for query in ('Сургуультай яаж холбоо барих вэ?', 'Холбоо барих', 'Яаж холбогдох вэ?', 'Сургуулийн утасны дугаар хэд вэ?'):
            self.assertEqual(alias(query), 'Сургуулийн холбоо барих мэдээллийг хэлнэ үү.', query)
        for query in ('Сургууль хаана байрладаг вэ?', 'Сургуулийн хаяг юу вэ?'):
            self.assertEqual(alias(query), 'Сургуулийн хаяг хаана вэ?', query)
        for query in ('Механикийн тэнхимтэй яаж холбоо барих вэ?', 'Багшийн хаяг хаана вэ?', 'Номын сан хаана байрладаг вэ?'):
            self.assertIsNone(alias(query), query)


class NoProviderRequestTests(unittest.TestCase):
    def setUp(self):
        # Any attempted Ollama request fails the test instead of returning unavailable.
        self.transport = patch('llm_runtime._http_json', side_effect=AssertionError('LLM request attempted'))
        self.transport.start()

    def tearDown(self):
        self.transport.stop()

    def test_selection_answers_from_exact_source_with_zero_calls(self):
        result = RuleSelectionGenerator().generate('Сургуулийн утасны дугаар хэд вэ?', [dict(PHONE_SOURCE)])
        self.assertEqual((result['generated'], result['llm_calls'], result['reason']),
                         (True, 0, 'source_preserving_selection'))
        self.assertEqual(result['selection_method'], RULE_SELECTOR)
        self.assertIsNone(result['llm_role'])
        for claim in result['claims']:
            self.assertIn(claim['text'], PHONE_SOURCE['text'])

    def test_no_shared_query_term_is_insufficient_without_a_provider(self):
        result = RuleSelectionGenerator().generate('xyzzy qwerty', [dict(PHONE_SOURCE)])
        self.assertEqual((result['generated'], result['llm_calls'], result['reason']),
                         (False, 0, 'insufficient_evidence'))

    def test_rule_reads_only_query_and_units_and_checks_at_most_92_subsets(self):
        units = [dict(unit_id=f'u{i}', source_id='s', text=f'утас дугаар {i}') for i in range(12)]
        with patch('tools.evaluate_llm_selection.common_render',
                   return_value=dict(accepted=False, reason='fixture')) as render:
            selection = bounded_lexical_selection('утас дугаар', units)
        self.assertTrue(selection['abstained'])
        self.assertEqual(render.call_count, 92)
        self.assertEqual(selection['llm_calls'], 0)

    def test_cited_source_without_the_key_terms_is_refused(self):
        # Observed failure: a pool question returned an olympiad time because "цаг" matched.
        source = dict(PHONE_SOURCE, text='Олимпиад 2026.04.25-ны өдрийн 10:00 цагт ШМТК-ийн байранд болно.')
        result = RuleSelectionGenerator().generate('Сургуулийн усан сан хэдэн цагт ажилладаг вэ?', [source])
        self.assertEqual((result['generated'], result['llm_calls'], result['reason']),
                         (False, 0, 'selection_not_relevant'))
        self.assertEqual(result['claims'], [])

    def single_unit_fixture(self, single_unit):
        units = [dict(unit_id='u1', source_id='s', text='Номын сан гуравдугаар давхарт.'),
                 dict(unit_id='u2', source_id='s', text='Спорт заал нэгдүгээр давхарт.')]
        texts = {unit['unit_id']: unit['text'] for unit in units}
        render = lambda query, ids, units, sources=None: dict(
            accepted=True, reason='fixture', claims=[dict(text=texts[i]) for i in ids], selected_unit_ids=ids)
        with patch('tools.evaluate_llm_selection.common_render', side_effect=render):
            return bounded_lexical_selection('Номын сан спорт заал', units, single_unit=single_unit)

    def test_terms_split_over_two_units_pass_only_when_the_stage_is_off(self):
        # Diagnosis 15, cause 2: one key term per unit made a summed subset look relevant.
        self.assertEqual(self.single_unit_fixture(False)['selected_unit_ids'], ['u1', 'u2'])
        selection = self.single_unit_fixture(True)
        self.assertTrue(selection['abstained'])
        self.assertIn('no_single_unit_covers_question', [row['reason'] for row in selection['checked_subsets']])

    def test_one_unit_holding_every_key_term_still_answers_with_the_stage_on(self):
        units = [dict(unit_id='u1', source_id='s', text='Номын сан гуравдугаар давхарт.')]
        render = lambda query, ids, units, sources=None: dict(
            accepted=True, reason='fixture', claims=[dict(text=units[0]['text'])], selected_unit_ids=ids)
        with patch('tools.evaluate_llm_selection.common_render', side_effect=render):
            selection = bounded_lexical_selection('Номын сан хаана вэ', units, single_unit=True)
        self.assertEqual(selection['selected_unit_ids'], ['u1'])

    def test_stage_two_refusal_reaches_the_user_as_nothing_found(self):
        source = dict(PHONE_SOURCE, text='Номын сан гуравдугаар давхарт.\nСпорт заал нэгдүгээр давхарт.')
        old = RuleSelectionGenerator().generate('Номын сан спорт заал', [source])
        new = RuleSelectionGenerator(single_unit_coverage=True).generate('Номын сан спорт заал', [source])
        self.assertEqual((old['generated'], old['reason']), (True, 'source_preserving_selection'))
        self.assertEqual((new['generated'], new['reason'], new['claims']), (False, 'selection_not_relevant', []))
        self.assertEqual(new['llm_calls'], 0)

    def test_when_or_how_many_question_needs_a_number_in_the_answer(self):
        self.assertFalse(relevant_to_question('Шалгалт хэзээ болох вэ?', 'Шалгалт бичгээр болно'))
        self.assertTrue(relevant_to_question('Шалгалт хэзээ болох вэ?', 'Шалгалт 8/15 болно'))

    def test_key_term_coverage_ignores_request_words_and_handles_suffixes(self):
        self.assertEqual(key_term_coverage('Голч дүн хэлнэ үү?', 'Голч дүн дундаас дээш'), 1.0)
        self.assertLess(key_term_coverage('Японд голч дүн шаардлага', 'Японд суралцах шаардлага'), 0.75)

    def test_default_chat_status_and_generator_never_use_a_provider(self):
        rag = ChatRAG(ROOT, None, retriever=Retriever([]))
        status = rag.generator.status()
        self.assertFalse(status['network_probe'])
        self.assertFalse(status['available'])
        self.assertEqual(status['provider'], 'none')
        self.assertIsNone(rag.generator.llm_role)

    def test_real_chat_route_answers_from_the_rule_with_zero_llm_calls(self):
        from test_rag_runtime import Policy, Retriever as ChatRetriever
        chat = ChatRAG(ROOT, Policy(), ChatRetriever())
        result = chat.route(None, 'Төлбөр хэд вэ?')
        self.assertEqual(result['llm_calls'], 0)
        self.assertEqual(result['rag']['selection_method'], RULE_SELECTOR)
        self.assertEqual(chat.status()['session_totals']['llm_calls'], 0)
        self.assertIsNone(chat.status()['llm_role'])

    def test_disabled_correction_returns_without_any_request(self):
        result = LLMRuntime(ROOT, model='').suggest_correction('сайн байна уу')
        self.assertFalse(result['used'])
        self.assertEqual(result['llm_calls'], 0)


if __name__ == '__main__':
    unittest.main()
