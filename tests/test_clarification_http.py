"""Real loopback contracts over invented content; no model, audio or human approvals."""
import copy
import hashlib
import http.client
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from clarification_context import ClarificationContext
from content_store import ContentStore
from demo_server import make_server
from project_policy import ContentUsePolicy
from rag_runtime import ChatRAG
from test_question_router import fixture


FEE_QUERY = 'Бүртгэлийн хураамж хэд вэ?'
ARC_QUERY = 'ARC хамтын ажиллагаанд ямар хичээлүүд багтсан бэ?'
ADMISSION_QUERY = 'Элсэлтийн бүртгэлийн хураамж хэд вэ?'


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class Retriever:
    """Invented official-shaped excerpts; only deterministic source lookup runs."""
    def __init__(self):
        self.corpus_id = 'synthetic-clarification-corpus-v1'
        self.calls = []
        self.sources = []
        for index, (name, path, amount) in enumerate([
                ('admission', '/elselt', '12,345'),
                ('olympiad', '/olympiad', '54,321')], 1):
            text = ('Цахимаар бүртгэл хийхдээ бүртгэлийн хураамж: ' + amount +
                    ' төгрөг төлнө. Энэ нь зөвхөн 2026 оны зохиомол тестийн эх.')
            self.sources.append(dict(source_id='invented-' + name,
                text=text, excerpt=text, url='https://nmct.edu.mn' + path,
                title='Invented ' + name + ' fixture 2026', chunk_id=index,
                version=1, retrieved_at='2026-10-10', source_updated_at=None,
                lexical_overlap_count=1, text_scope='document_visual_excerpt',
                source_locator='invented clause; not school evidence',
                extraction_method='synthetic_fixture', reviewer_kind='test_only'))

    def status(self):
        return dict(available=True, corpus_id=self.corpus_id)

    def search(self, query, limit=5):
        self.calls.append(query)
        sources = self.sources if 'хураамж' in query.casefold() else []
        return dict(candidates=copy.deepcopy(sources), corpus_id=self.corpus_id,
                    backend='synthetic_fixture')


class NoGenerator:
    def status(self):
        return dict(available=False)

    def generate(self, query, sources):
        raise AssertionError('Clarification HTTP contracts must not call a model')


class RecordingRAG(ChatRAG):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.routed = []

    def route(self, database, query, *, allow_draft=False):
        self.routed.append((query, allow_draft))
        return super().route(database, query, allow_draft=allow_draft)


class Voice:
    def __init__(self):
        self.spoken = []

    def status(self):
        return dict(stt_ready=False, tts_ready=False)

    def synthesize(self, text, voice):
        self.spoken.append((text, voice))
        return dict(id='b' * 32, audio_url='/api/voice/audio/' + 'b' * 32)


class ClarificationHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'config').mkdir()
        (self.root / 'config' / 'content-use.json').write_text(json.dumps(dict(
            basis='user_acceptance_of_official_website', enabled=True,
            official_hosts=['nmct.edu.mn'], accepted_on='2026-10-10')), encoding='utf-8')
        self.db = self.root / 'content.db'
        self.content = fixture('approved')
        # Broad test-only validity prevents the machine's date from changing the contract.
        for kind in ('sources', 'facts', 'faqs'):
            for item in self.content[kind]:
                item.update(valid_from='2020-01-01', valid_until='2099-12-31')
        with ContentStore(self.db) as store:
            store.import_content(self.content, allow_draft=True)
        self.database_hash = hashlib.sha256(self.db.read_bytes()).hexdigest()
        self.clock = Clock()
        self.context = ClarificationContext(ttl_seconds=300, max_entries=2, clock=self.clock)
        self.voice, self.retriever = Voice(), Retriever()
        self.rag = RecordingRAG(self.root, ContentUsePolicy(self.root), self.retriever, NoGenerator())
        self.server = make_server(self.db, port=0, project_root=self.root,
            voice_service=self.voice, rag_service=self.rag, clarification_service=self.context)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(), self.database_hash)
        self.temp.cleanup()

    def request(self, path, body, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_address[1], timeout=4)
        try:
            data = json.dumps(body, ensure_ascii=False).encode('utf-8')
            connection.request('POST', path, body=data,
                headers={'Content-Type': 'application/json', **(headers or {})})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def route(self, query, identifier=None, draft=False):
        body = dict(query=query, allow_draft=draft)
        if identifier is not None:
            body['clarification_id'] = identifier
        return self.request('/api/route', body)

    def pending(self, query=FEE_QUERY, draft=False):
        status, result = self.route(query, draft=draft)
        self.assertEqual(status, 200)
        self.assertEqual(result['route'], 'D')
        token = result['conversation']['clarification_id']
        self.assertRegex(token, r'^[0-9a-f]{32}$')
        return token, result

    def test_reversed_year_range_without_faq_cannot_reach_web_fee_answer(self):
        status, result = self.route('2026–2025 оны Олимпиадын бүртгэлийн хураамж хэд вэ?')
        self.assertEqual(status, 200)
        self.assertEqual(result['route'], 'E')
        self.assertEqual(result['reason_code'], 'invalid_year_range')
        self.assertIsNone(result['answer'])
        self.assertIsNone(result['conversation']['clarification_id'])
        self.assertEqual(result['llm_calls'], 0)
        self.assertEqual(self.retriever.calls, [])

    def test_fee_reply_requeries_source_and_records_raw_and_resolved_text(self):
        token, original = self.pending()
        status, result = self.route('Элсэлтийнх', token)
        self.assertEqual(status, 200)
        self.assertEqual(result['route'], 'A')
        self.assertEqual(result['query'], ADMISSION_QUERY)
        conversation = result['conversation']
        self.assertEqual(conversation['raw_query'], 'Элсэлтийнх')
        self.assertEqual(conversation['resolved_query'], result['query'])
        self.assertTrue(conversation['applied'])
        self.assertEqual(conversation['reason'], 'supported_reply')
        self.assertIsNone(conversation['clarification_id'])
        self.assertIn('12,345', result['answer'])
        self.assertNotIn('54,321', result['answer'])
        self.assertEqual(result['citations'][0]['document_id'], 'invented-admission')
        self.assertFalse(result['citations'][0]['school_staff_approval'])
        self.assertEqual(result['llm_calls'], 0)
        self.assertFalse(result['generated'])
        self.assertIsNone(original['answer'])
        self.assertEqual(self.rag.routed[-1], (result['query'], False))

    def test_supported_scope_reply_does_not_bypass_missing_amount_source_guard(self):
        self.retriever.sources[0]['text'] = 'Элсэлтийн бүртгэлийн ерөнхий мэдээлэл. Тестийн эх 2026.'
        self.retriever.sources[0]['excerpt'] = self.retriever.sources[0]['text']
        token, _ = self.pending()
        status, result = self.route('Элсэлтийнх', token)
        self.assertEqual(status, 200)
        self.assertTrue(result['conversation']['applied'])
        self.assertEqual(result['query'], ADMISSION_QUERY)
        self.assertEqual(result['route'], 'E')
        self.assertEqual(result['reason_code'], 'requested_attribute_not_supported')
        self.assertIsNone(result['answer'])
        self.assertEqual(result['llm_calls'], 0)
        self.assertFalse(result['generated'])

    def test_explicit_supported_year_reply_passes_real_faq_year_guard(self):
        token, _ = self.pending(ARC_QUERY)
        status, result = self.route('2026', token)
        self.assertEqual(status, 200)
        self.assertEqual(result['route'], 'A')
        self.assertEqual(result['query'], '2026 оны ' + ARC_QUERY)
        self.assertTrue(result['conversation']['applied'])
        self.assertEqual(result['answer_faq_id'], 'faq.arc.courses')
        self.assertEqual(result['llm_calls'], 0)

    def test_unsupported_year_reply_routes_fresh_and_does_not_replace_year(self):
        token, _ = self.pending(ARC_QUERY)
        status, result = self.route('2027', token)
        self.assertEqual(status, 200)
        self.assertEqual(result['query'], '2027')
        self.assertFalse(result['conversation']['applied'])
        self.assertEqual(result['conversation']['reason'], 'unrecognized_reply')
        self.assertIsNone(result['answer'])
        self.assertEqual(self.route('2026', token)[0], 409)

    def test_unrecognized_new_topic_is_fresh_and_consumes_prior_capability(self):
        token, _ = self.pending()
        new_query = 'Холбоо барих утас хэд вэ?'
        status, result = self.route(new_query, token)
        self.assertEqual(status, 200)
        self.assertEqual(result['query'], new_query)
        self.assertFalse(result['conversation']['applied'])
        self.assertEqual(result['conversation']['reason'], 'unrecognized_reply')
        self.assertEqual(result['answer_faq_id'], 'faq.contact')
        self.assertNotIn('12,345', result['answer'])
        self.assertEqual(self.route('Элсэлтийнх', token)[0], 409)

    def test_negative_or_added_constraint_reply_is_not_fuzzy_resolved(self):
        for reply in ('Элсэлтийнх биш', 'Элсэлтийнх 2027', 'Элсэлтийнх 5 сарын 1',
                      'Элсэлтийнх төлөхгүй бол', 'элсэтийнх'):
            with self.subTest(reply=reply):
                token, _ = self.pending()
                status, result = self.route(reply, token)
                self.assertEqual(status, 200)
                self.assertEqual(result['query'], reply)
                self.assertFalse(result['conversation']['applied'])
                self.assertEqual(result['conversation']['reason'], 'unrecognized_reply')

    def test_original_year_constraint_survives_supported_scope_reply(self):
        token, _ = self.pending('2026 оны ' + FEE_QUERY)
        status, result = self.route('Элсэлтийнх', token)
        self.assertEqual(status, 200)
        self.assertTrue(result['conversation']['applied'])
        self.assertIn('2026', result['query'])
        self.assertEqual(result['route'], 'A')
        self.assertIn('12,345', result['answer'])

    def test_negative_or_conditional_original_d_has_no_short_reply_capability(self):
        for query in ('Бүртгэлийн хураамж төлөхгүй бол хэд вэ?',
                      'Бүртгэлийн хураамж биш бол хэд вэ?'):
            with self.subTest(query=query):
                status, result = self.route(query)
                self.assertEqual(status, 200)
                self.assertEqual(result['route'], 'D')
                self.assertEqual(result['query'], query)
                self.assertIsNone(result['conversation']['clarification_id'])
                self.assertFalse(result['conversation']['applied'])

    def test_period_relative_year_and_foreign_scope_cannot_be_dropped(self):
        for query in ('Бүртгэлийн хураамж сар бүр хэд вэ?',
                      'Өмнөх жилийн бүртгэлийн хураамж хэд вэ?',
                      'Гадаадын иргэний бүртгэлийн хураамж хэд вэ?',
                      'Бүртгэлийн хураамж 5 сарын 1-нд хэд вэ?'):
            with self.subTest(query=query):
                status, result = self.route(query)
                self.assertEqual(status, 200)
                self.assertEqual(result['route'], 'D')
                self.assertEqual(result['query'], query)
                self.assertIsNone(result['conversation']['clarification_id'])
                self.assertIsNone(result['answer'])

    def test_fresh_queries_have_explicit_unapplied_metadata(self):
        query = 'Холбоо барих утас хэд вэ?'
        status, result = self.route(query)
        self.assertEqual(status, 200)
        expected = dict(raw_query=query, resolved_query=query,
            applied=False, reason='fresh_query', clarification_id=None)
        self.assertEqual({key: result['conversation'][key] for key in expected}, expected)
        self.assertGreaterEqual(result['conversation']['context_latency_ms'], 0)
        self.assertIn('excludes_rag_route_http_stt_tts', result['conversation']['latency_scope'])

    def test_unknown_valid_id_refused_without_routing_or_source_query(self):
        routed, searched = len(self.rag.routed), len(self.retriever.calls)
        self.assertEqual(self.route('Элсэлтийнх', 'f' * 32)[0], 409)
        self.assertEqual(len(self.rag.routed), routed)
        self.assertEqual(len(self.retriever.calls), searched)

    def test_expired_id_is_refused_before_routing_and_is_one_shot(self):
        token, _ = self.pending()
        self.clock.now += 301
        routed = len(self.rag.routed)
        self.assertEqual(self.route('Элсэлтийнх', token)[0], 409)
        self.assertEqual(len(self.rag.routed), routed)
        self.clock.now -= 301
        self.assertEqual(self.route('Элсэлтийнх', token)[0], 409)

    def test_successful_capability_cannot_be_replayed(self):
        token, _ = self.pending()
        self.assertEqual(self.route('Элсэлтийнх', token)[0], 200)
        routed = len(self.rag.routed)
        self.assertEqual(self.route('Олимпиадынх', token)[0], 409)
        self.assertEqual(len(self.rag.routed), routed)

    def test_draft_change_invalidates_before_routing(self):
        token, _ = self.pending(draft=True)
        routed = len(self.rag.routed)
        self.assertEqual(self.route('Элсэлтийнх', token, draft=False)[0], 409)
        self.assertEqual(len(self.rag.routed), routed)

    def test_content_package_change_invalidates_before_routing(self):
        token, _ = self.pending()
        changed = copy.deepcopy(self.content)
        changed['facts'][0]['value'] = '87654321'
        with ContentStore(self.db) as store:
            store.import_content(changed, allow_draft=True)
        self.database_hash = hashlib.sha256(self.db.read_bytes()).hexdigest()
        routed = len(self.rag.routed)
        self.assertEqual(self.route('Элсэлтийнх', token)[0], 409)
        self.assertEqual(len(self.rag.routed), routed)

    def test_website_corpus_change_invalidates_before_routing(self):
        token, _ = self.pending()
        self.retriever.corpus_id = 'synthetic-clarification-corpus-v2'
        routed = len(self.rag.routed)
        self.assertEqual(self.route('Элсэлтийнх', token)[0], 409)
        self.assertEqual(len(self.rag.routed), routed)

    def test_independent_tab_ids_and_scoped_idempotent_reset(self):
        first, _ = self.pending()
        second, _ = self.pending(ARC_QUERY)
        self.assertNotEqual(first, second)
        body = dict(clarification_ids=[first, 'f' * 32])
        status, result = self.request('/api/conversation/reset', body)
        self.assertEqual((status, result['removed']), (200, 1))
        self.assertEqual(self.request('/api/conversation/reset', body)[1]['removed'], 0)
        self.assertEqual(self.route('Элсэлтийнх', first)[0], 409)
        self.assertEqual(self.route('2026', second)[0], 200)

    def test_tab_without_id_does_not_borrow_another_tabs_pending_question(self):
        token, _ = self.pending()
        status, result = self.route('Элсэлтийнх')
        self.assertEqual(status, 200)
        self.assertEqual(result['query'], 'Элсэлтийнх')
        self.assertFalse(result['conversation']['applied'])
        self.assertEqual(result['conversation']['reason'], 'fresh_query')
        self.assertIsNone(result['answer'])
        self.assertEqual(self.request('/api/conversation/reset',
            dict(clarification_ids=[]))[1]['removed'], 0)
        self.assertEqual(self.route('Элсэлтийнх', token)[0], 200)

    def test_capacity_evicts_oldest_only_and_keeps_independent_ids(self):
        first, _ = self.pending()
        second, _ = self.pending()
        third, _ = self.pending(ARC_QUERY)
        self.assertEqual(self.route('Элсэлтийнх', first)[0], 409)
        self.assertEqual(self.route('Элсэлтийнх', second)[0], 200)
        self.assertEqual(self.route('2026', third)[0], 200)

    def test_two_simultaneous_uses_only_one_reaches_router(self):
        token, _ = self.pending()
        barrier = threading.Barrier(2)
        def attempt():
            barrier.wait(timeout=2)
            return self.route('Элсэлтийнх', token)[0]
        routed = len(self.rag.routed)
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(attempt) for _ in range(2)]
            statuses = [future.result(timeout=4) for future in futures]
        self.assertEqual(sorted(statuses), [200, 409])
        self.assertEqual(len(self.rag.routed), routed + 1)

    def test_speech_binds_resolved_query_and_cached_answer(self):
        token, _ = self.pending()
        status, result = self.route('Элсэлтийнх', token)
        self.assertEqual(status, 200)
        speech = dict(query='Элсэлтийнх', package_id=result['package_id'],
                      response_id=result['response_id'], voice='mn-MN-BataaNeural')
        self.assertEqual(self.request('/api/voice/speak', speech)[0], 409)
        self.assertFalse(self.voice.spoken)
        routed = len(self.rag.routed)
        status, spoken = self.request('/api/voice/speak', {**speech, 'query': result['query']})
        self.assertEqual(status, 200)
        self.assertIn('12,345 төгрөг', result['answer'])
        expected_spoken = result['answer'].replace(
            '12,345 төгрөг', 'арван хоёр мянга гурван зуун дөчин таван төгрөг')
        self.assertEqual(spoken['spoken_text'], expected_spoken)
        self.assertEqual(spoken['citations'], result['citations'])
        self.assertEqual(len(self.rag.routed), routed)
        self.assertEqual(spoken['llm_calls'], 0)
        self.assertEqual(self.voice.spoken, [(expected_spoken, 'mn-MN-BataaNeural')])

    def test_id_and_reset_validation_reject_control_fields(self):
        for token in (None, '', 'z' * 32, 'a' * 31, 7, True, [], {}):
            with self.subTest(token=token):
                status, _ = self.request('/api/route', dict(query='Элсэлтийнх', clarification_id=token))
                self.assertEqual(status, 400)
        for body in ({}, {'clarification_ids': None}, {'clarification_ids': 'a' * 32},
                     {'clarification_ids': ['bad']}, {'clarification_ids': ['a' * 32] * 65},
                     {'clarification_ids': [], 'all': True}):
            with self.subTest(body=body):
                self.assertEqual(self.request('/api/conversation/reset', body)[0], 400)
        self.assertEqual(self.rag.routed, [])

    def test_client_cannot_supply_resolved_query_or_conversation_history(self):
        for field, value in [('resolved_query', ADMISSION_QUERY),
                             ('conversation', {'applied': True}),
                             ('history', [FEE_QUERY]), ('package_id', 'invented')]:
            with self.subTest(field=field):
                body = {'query': 'Элсэлтийнх', field: value}
                self.assertEqual(self.request('/api/route', body)[0], 400)
        self.assertEqual(self.rag.routed, [])

    def test_cross_site_request_cannot_consume_or_reset_capability(self):
        token, _ = self.pending()
        hostile = {'Origin': 'https://outside.example'}
        self.assertEqual(self.request('/api/route', dict(query='Элсэлтийнх',
            clarification_id=token), hostile)[0], 403)
        self.assertEqual(self.request('/api/conversation/reset',
            dict(clarification_ids=[token]), hostile)[0], 403)
        self.assertEqual(self.route('Элсэлтийнх', token)[0], 200)


if __name__ == '__main__':
    unittest.main()
