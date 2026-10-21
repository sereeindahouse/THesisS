"""Loopback STT lineage ownership; constructed saved records, no model/provider."""
import hashlib
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

from content_store import ContentStore
from demo_server import make_server
from project_policy import ContentUsePolicy
from rag_runtime import ChatRAG
from test_clarification_http import Retriever
from test_demo_server import fixture
from voice_runtime import VoiceRuntime


class NoGenerator:
    def status(self):
        return dict(available=False)

    def generate(self, query, sources):
        raise AssertionError('The HTTP lineage tests must never call a model.')


class RecordingRAG(ChatRAG):
    def __init__(self, root):
        super().__init__(root, ContentUsePolicy(root), Retriever(), NoGenerator())
        self.routed = []

    def route(self, database, query, *, allow_draft=False):
        self.routed.append(query)
        return super().route(database, query, allow_draft=allow_draft)


class StoredVoice(VoiceRuntime):
    def __init__(self, root):
        super().__init__(root)
        self.spoken = []

    def status(self):
        return dict(stt_ready=False, tts_ready=False)

    def synthesize(self, text, voice):
        self.spoken.append((text, voice))
        return self._save(b'constructed audio; not a real synthesized clip', 'audio/mpeg',
                          dict(kind='tts', text=text, audio_synthesized=False))


class TranscriptionLineageHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'config').mkdir()
        (self.root / 'config/content-use.json').write_text(json.dumps(dict(
            enabled=True, basis='user_acceptance_of_official_website',
            official_hosts=['nmct.edu.mn'], accepted_on='2026-10-10')), encoding='utf-8')
        self.database = self.root / 'content.db'
        with ContentStore(self.database) as store:
            store.import_content(fixture('approved'), allow_draft=True)
        self.database_sha = hashlib.sha256(self.database.read_bytes()).hexdigest()
        self.voice, self.rag = StoredVoice(self.root), RecordingRAG(self.root)
        self.server = make_server(self.database, port=0, project_root=self.root,
                                  voice_service=self.voice, rag_service=self.rag)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.raw = 'Элсэлтийн бүртгэлийн хураамж хэд вэ?'
        self.record = self.save_stt(self.raw)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.assertEqual(hashlib.sha256(self.database.read_bytes()).hexdigest(), self.database_sha)
        self.temp.cleanup()

    def save_stt(self, text):
        return self.voice._save(b'constructed test audio', 'audio/wav',
                                dict(kind='stt', text=text, reference_confirmed=False))

    def request(self, path, payload, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_address[1], timeout=4)
        try:
            connection.request('POST', path, body=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                               headers={'Content-Type': 'application/json', **(headers or {})})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def route(self, query=None, identifier=None, **extra):
        payload = dict(query=self.raw if query is None else query, **extra)
        if identifier is not None:
            payload['transcription_id'] = identifier
        return self.request('/api/route', payload)

    def test_typed_input_cannot_claim_a_raw_transcription(self):
        status, result = self.route()
        self.assertEqual(status, 200)
        self.assertEqual(result['input_lineage'], dict(kind='typed', submitted_text=self.raw,
                                                      manual_verification_claimed=False))
        self.assertNotIn('raw_text', result['input_lineage'])

    def test_raw_and_edited_submissions_get_separate_honest_lineage(self):
        status, raw = self.route(identifier=self.record['id'])
        self.assertEqual(status, 200)
        self.assertEqual(raw['input_lineage']['kind'], 'raw_stt')
        edited_query = 'Элсэлтийн бүртгэлийн хураамж хэдэн төгрөг вэ?'
        status, edited = self.route(edited_query, identifier=self.record['id'])
        self.assertEqual(status, 200)
        self.assertEqual(edited['input_lineage']['kind'], 'edited_stt')
        self.assertEqual(edited['input_lineage']['raw_text'], self.raw)
        self.assertEqual(edited['input_lineage']['submitted_text'], edited_query)
        self.assertFalse(edited['input_lineage']['manual_verification_claimed'])
        self.assertNotEqual(raw['response_id'], edited['response_id'])
        self.assertEqual(raw['input_lineage']['submitted_text'], self.raw)

    def test_two_recordings_do_not_cross_bind_between_response_turns(self):
        second_query = 'Элсэлтийн бүртгэлийн хураамж хэдэн төгрөг вэ?'
        second = self.save_stt(second_query)
        _, first_result = self.route(identifier=self.record['id'])
        _, second_result = self.route(second_query, identifier=second['id'])
        self.assertEqual(first_result['input_lineage']['transcription_id'], self.record['id'])
        self.assertEqual(first_result['input_lineage']['raw_text'], self.raw)
        self.assertEqual(second_result['input_lineage']['transcription_id'], second['id'])
        self.assertEqual(second_result['input_lineage']['raw_text'], second_query)
        self.assertNotEqual(first_result['response_id'], second_result['response_id'])

    def test_unknown_deleted_and_other_runtime_records_reject_before_rag(self):
        unknown = VoiceRuntime(self.root)._save(b'other session', 'audio/wav', dict(kind='stt', text=self.raw))
        for identifier in ('0' * 32, unknown['id']):
            with self.subTest(identifier=identifier):
                status, result = self.route(identifier=identifier)
                self.assertEqual(status, 404)
                self.assertEqual(result['code'], 'stt_lineage_missing')
        self.assertEqual(self.request('/api/voice/reset', dict(ids=[self.record['id']]))[0], 200)
        self.assertEqual(self.route(identifier=self.record['id'])[0], 404)
        self.assertEqual(self.rag.routed, [])

    def test_tts_ids_cannot_be_used_as_input_transcription(self):
        record = self.voice._save(b'constructed tts', 'audio/mpeg', dict(kind='tts', text=self.raw))
        status, result = self.route(identifier=record['id'])
        self.assertEqual(status, 409)
        self.assertEqual(result['code'], 'stt_lineage_kind')
        self.assertEqual(self.rag.routed, [])

    def test_client_raw_text_or_verification_fields_are_rejected(self):
        for extra in ({'raw_text': 'Injected original'}, {'manual_verification_claimed': True},
                      {'input_lineage': {'kind': 'raw_stt'}}):
            with self.subTest(extra=extra):
                self.assertEqual(self.route(identifier=self.record['id'], **extra)[0], 400)
        self.assertEqual(self.rag.routed, [])

    def test_invalid_id_and_cross_origin_cannot_reach_rag(self):
        for identifier in ('../private', 'A' * 32):
            self.assertEqual(self.route(identifier=identifier)[0], 400)
        status, _ = self.request('/api/route', dict(query=self.raw, transcription_id=self.record['id']),
                                  headers={'Origin': 'https://outside.example'})
        self.assertEqual(status, 403)
        self.assertEqual(self.rag.routed, [])

    def test_saved_response_keeps_its_binding_after_record_reset_and_rejects_wrong_query(self):
        status, result = self.route(identifier=self.record['id'])
        self.assertEqual(status, 200)
        self.request('/api/voice/reset', dict(ids=[self.record['id']]))
        payload = dict(query=self.raw, voice='mn-MN-BataaNeural', package_id=result['package_id'],
                       response_id=result['response_id'], release_token=result['content_release']['activation_token'])
        self.assertEqual(self.request('/api/voice/speak', {**payload, 'query': 'Injected other question'})[0], 409)
        self.assertEqual(self.voice.spoken, [])
        self.assertEqual(self.request('/api/voice/speak', payload)[0], 200)
        self.assertEqual(len(self.voice.spoken), 1)
        self.assertEqual(result['input_lineage']['raw_text'], self.raw)
        self.assertFalse(result['input_lineage']['manual_verification_claimed'])


if __name__ == '__main__':
    unittest.main()
