"""The chat server serves the chat and nothing else (2026-11-25). Fakes only: no model, no network, no audio."""
import http.client
import json
from pathlib import Path
import threading
import unittest

import chat_server

ROOT = Path(__file__).resolve().parents[1]


class FakeSpeech:
    def status(self):
        return {'configured': False, 'ready': False}


class FakeVoice:
    gemini = FakeSpeech()

    def status(self):
        return {'tts_ready': False, 'gemini': self.gemini.status()}

    def reset(self, ids):
        return {'removed': len(ids)}


class FakeRAG:
    reception = None
    retriever = None
    normalizer = None

    def __init__(self):
        self.asked = []

    def status(self):
        return {'retrieval': {'backend': 'fake'}}

    def route(self, database, query, *, allow_draft=False, **options):
        self.asked.append(query)
        return dict(query=query, route='A', answer='Зохиомол хариулт.', message='', reason_code='fake_answer',
                    answer_kind='fake', citations=[], package_id='fake-package', suggestions=[], clarification=None)

    def _remember(self, result, draft):
        return result


class FakeTeachers:
    def profile(self, query):
        return None

    def attach(self, query, result):
        return []

    def status(self):
        return {'available': False}


class ChatServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rag = FakeRAG()
        cls.server = chat_server.make_server(port=0, project_root=ROOT, voice_service=FakeVoice(), rag_service=cls.rag,
                                             teacher_service=FakeTeachers())
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        try:
            payload = json.dumps(body).encode('utf-8') if body is not None else None
            connection.request(method, path, body=payload,
                               headers={**({'Content-Type': 'application/json'} if body is not None else {}), **(headers or {})})
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def test_the_chat_page_is_served(self):
        status, body = self.request('GET', '/')
        self.assertEqual(status, 200)
        page = body.decode('utf-8')
        self.assertIn('ШМТК · Ухаалаг туслах', page)
        for other in ('/work', '/admin', '/reader', '/seminar', '/reports', '/data', '/kiosk', '/code-map'):
            self.assertNotIn('"' + other, page)

    def test_only_the_chat_is_reachable(self):
        for path in ('/work', '/admin', '/admin.js', '/reader', '/reader/RAG01', '/seminar', '/reports', '/data',
                     '/kiosk', '/code-map', '/api/work', '/api/admin/state', '/api/explorer', '/api/explorer/tree',
                     '/api/review', '/api/code-map', '/api/teachers', '/demo/audio/q01.wav', '/listening'):
            with self.subTest(path=path):
                self.assertEqual(self.request('GET', path)[0], 404)
        for path in ('/api/search', '/api/preview', '/api/website-search', '/api/voice/correct', '/api/work/item',
                     '/api/admin/stage', '/api/review/stt-confirm'):
            with self.subTest(path=path):
                self.assertEqual(self.request('POST', path, {'query': 'x'})[0], 404)

    def test_the_knowledge_tree_and_the_data_sets_are_served(self):
        # 11/26: the tree beside the chat — eleven domains with their sub-sections, and the data sets in counts.
        status, body = self.request('GET', '/api/knowledge')
        self.assertEqual(status, 200)
        value = json.loads(body)
        self.assertEqual(len(value['tree']), 11)
        self.assertTrue(all(domain['children'] is not None for domain in value['tree']))
        self.assertIn('tree', {item['kind'] for item in value['datasets']})
        result = json.loads(self.request('POST', '/api/route', {'query': 'Зохиомол асуулт юу вэ?'})[1])
        self.assertIn('places', result['knowledge'])

    def test_a_question_is_answered_through_the_route(self):
        status, body = self.request('POST', '/api/route', {'query': 'Зохиомол асуулт юу вэ?'})
        self.assertEqual(status, 200)
        result = json.loads(body)
        self.assertEqual(result['answer'], 'Зохиомол хариулт.')
        self.assertEqual(result['input_lineage']['kind'], 'typed')
        self.assertIn('Зохиомол асуулт юу вэ?', self.rag.asked)

    def test_bad_requests_are_refused(self):
        self.assertEqual(self.request('POST', '/api/route', {'query': ''})[0], 400)
        self.assertEqual(self.request('POST', '/api/route', {'query': 'x', 'allow_draft': True})[0], 400)
        self.assertEqual(self.request('POST', '/api/route', {'query': 'x'}, {'Origin': 'https://example.org'})[0], 403)
        self.assertEqual(self.request('POST', '/api/route', {'query': 'x'}, {'Sec-Fetch-Site': 'cross-site'})[0], 403)
        self.assertEqual(self.request('GET', '/api/status', headers={'Host': 'example.org'})[0], 403)
        self.assertEqual(self.request('PUT', '/api/route', {'query': 'x'})[0], 405)

    def test_status_names_no_other_feature(self):
        status, body = self.request('GET', '/api/status')
        self.assertEqual(status, 200)
        value = json.loads(body)
        self.assertEqual(value['service'], 'nmct-assistant-chat')
        self.assertEqual(set(value), {'service', 'voice', 'content', 'reception_tables', 'retrieval', 'generated', 'llm_calls'})


if __name__ == '__main__':
    unittest.main()
