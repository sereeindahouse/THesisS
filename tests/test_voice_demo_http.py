"""Voice/review HTTP contracts with synthetic fixtures only; no real human approvals."""
import hashlib
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from content_store import ContentStore
from demo_server import make_server
from voice_runtime import VoiceRuntimeError
from test_demo_server import fixture


class FakeVoice:
    def __init__(self):
        self.transcribed = []
        self.spoken = []
        self.deleted = []

    def status(self):
        return dict(stt_ready=True, tts_ready=True, model_loaded=False)

    def transcribe(self, data, mime):
        self.transcribed.append((data, mime))
        return dict(id='a' * 32, text='Тест үү?', accuracy_measured=False, reference_confirmed=False)

    def synthesize(self, text, voice):
        if voice not in ('mn-MN-BataaNeural', 'mn-MN-YesuiNeural'):
            raise VoiceRuntimeError('tts_voice', 'Test-only invalid voice')
        self.spoken.append((text, voice))
        return dict(id='b' * 32, audio_url='/api/voice/audio/' + 'b' * 32,
                    synthesis_seconds=0.01, audio_synthesized=True)

    def audio(self, identifier):
        if identifier != 'b' * 32:
            raise VoiceRuntimeError('voice_audio_missing', 'Test-only absent audio', 404)
        return b'test-mp3', 'audio/mpeg'

    def reset(self, ids):
        self.deleted.extend(ids)
        return dict(deleted_ids=ids, original_recordings_modified=False)


class FakeReview:
    def __init__(self):
        self.saved = []
        self.rescored = 0

    def status(self):
        return dict(available=True, pending_stt=[dict(id='q10')], tts=[])

    def audio(self, kind, identifier):
        if kind != 'stt' or identifier != 'q10':
            raise ValueError('Test-only private ID')
        return b'fixture-WAV', 'audio/wav'

    def confirm_stt(self, identifier, text, confirmed):
        if confirmed is not True or identifier != 'q10':
            raise ValueError('Test-only explicit human action required')
        self.saved.append((identifier, text))
        return dict(saved=True, inference_repeated=False)

    def rescore_existing(self):
        self.rescored += 1
        return dict(status='not_available', inference_repeated=False)

    def save_tts(self, identifier, listener, overall, intelligibility, errors, confirmed):
        if confirmed is not True:
            raise ValueError('Test-only explicit rating required')
        self.saved.append((identifier, listener, overall, intelligibility, errors))
        return dict(saved=True, mos_computed=False, final_voice_selected=False)


class VoiceDemoHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / 'content.db'
        with ContentStore(self.db) as store:
            store.import_content(fixture(), allow_draft=True)
        self.before = hashlib.sha256(self.db.read_bytes()).hexdigest()
        self.voice, self.review = FakeVoice(), FakeReview()
        self.server = make_server(self.db, port=0, project_root=self.root,
                                  voice_service=self.voice, review_service=self.review)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(), self.before)
        self.temp.cleanup()

    def request(self, method, path, payload=None, *, raw=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_address[1], timeout=3)
        request_headers = dict(headers or {})
        data = raw
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
            request_headers['Content-Type'] = 'application/json'
        connection.request(method, path, body=data, headers=request_headers)
        response = connection.getresponse()
        body, response_headers = response.read(), dict(response.getheaders())
        result = json.loads(body) if response_headers.get('Content-Type', '').startswith('application/json') else body
        status = response.status
        connection.close()
        return status, result, response_headers

    def route(self, draft=False):
        return self.request('POST', '/api/route', dict(query='Тест үү?', allow_draft=draft))[1]

    def test_status_distinguishes_content_readonly_from_local_writes(self):
        status, result, _ = self.request('GET', '/api/status')
        self.assertEqual(status, 200)
        self.assertFalse(result['readonly'])
        self.assertTrue(result['content_database_readonly'])
        self.assertTrue(result['local_review_writes_supported'])
        self.assertTrue(result['microphone_connected'])
        self.assertFalse(result['voice']['model_loaded'])

    def test_raw_upload_does_not_route_or_confirm_transcript(self):
        status, result, _ = self.request('POST', '/api/voice/transcribe', raw=b'fixture-audio',
                                         headers={'Content-Type': 'audio/webm;codecs=opus'})
        self.assertEqual(status, 200)
        self.assertEqual(self.voice.transcribed, [(b'fixture-audio', 'audio/webm')])
        self.assertFalse(result['reference_confirmed'])
        self.assertFalse(result['accuracy_measured'])
        self.assertEqual(self.voice.spoken, [])
        self.assertEqual(self.review.saved, [])

    def test_raw_upload_origin_host_and_framing_reject_before_inference(self):
        for headers, expected in [({'Origin': 'https://outside.example'}, 403),
                                  ({'Host': 'outside.example'}, 403),
                                  ({'Sec-Fetch-Site': 'cross-site'}, 403),
                                  ({'Transfer-Encoding': 'chunked'}, 400),
                                  ({'Content-Length': '8388609'}, 400)]:
            status, _, response_headers = self.request('POST', '/api/voice/transcribe', raw=b'fixture', headers=headers)
            self.assertEqual(status, expected)
            self.assertEqual(response_headers.get('Connection'), 'close')
        self.assertEqual(self.voice.transcribed, [])

    def test_speech_rechecks_default_guard_and_never_speaks_hidden_draft(self):
        current = self.route()
        status, result, _ = self.request('POST', '/api/voice/speak', dict(query='Тест үү?',
            voice='mn-MN-BataaNeural', package_id=current['package_id']))
        self.assertEqual(status, 200)
        self.assertEqual(result['route'], 'E')
        self.assertNotIn('Зөвхөн тестийн хариулт.', result['spoken_text'])
        self.assertFalse(result['text_generated'])
        self.assertEqual(result['llm_calls'], 0)

    def test_explicit_draft_speech_prefixes_notice_without_changing_original(self):
        current = self.route(True)
        status, result, _ = self.request('POST', '/api/voice/speak', dict(query='Тест үү?', allow_draft=True,
            voice='mn-MN-YesuiNeural', package_id=current['package_id']))
        self.assertEqual(status, 200)
        self.assertEqual(result['route'], 'B')
        self.assertTrue(result['spoken_text'].startswith('Ноорог, сургуулиар баталгаажаагүй. '))
        self.assertTrue(result['spoken_text'].endswith(current['answer']))
        self.assertEqual(result['citations'], current['citations'])

    def test_speech_rejects_client_answer_invalid_voice_or_changed_package(self):
        current = self.route(True)
        base = dict(query='Тест үү?', allow_draft=True, voice='mn-MN-BataaNeural', package_id=current['package_id'])
        self.assertEqual(self.request('POST', '/api/voice/speak', {**base, 'text': 'client supplied'})[0], 400)
        self.assertEqual(self.request('POST', '/api/voice/speak', {**base, 'package_id': 'stale'})[0], 409)
        self.assertEqual(self.request('POST', '/api/voice/speak', {**base, 'voice': 'unselected'})[0], 400)
        self.assertEqual(self.voice.spoken, [])

    def test_private_media_only_dedicated_known_ids_and_same_origin(self):
        status, result, headers = self.request('GET', '/api/review/stt-audio/q10')
        self.assertEqual((status, result), (200, b'fixture-WAV'))
        self.assertEqual(headers['Cross-Origin-Resource-Policy'], 'same-origin')
        self.assertIn("media-src 'self' blob:", headers['Content-Security-Policy'])
        self.assertEqual(self.request('GET', '/api/review/stt-audio/q05')[0], 404)
        self.assertEqual(self.request('GET', '/api/review/stt-audio/q10', headers={'Sec-Fetch-Site': 'cross-site'})[0], 403)
        self.assertEqual(self.request('GET', '/api/voice/audio/' + 'b' * 32)[1], b'test-mp3')
        self.assertEqual(self.request('GET', '/api/voice/audio/../private')[0], 404)

    def test_human_confirmation_required_and_rescore_uses_retained_outputs(self):
        payload = dict(id='q10', text='Зохиомол тестийн текст.', confirmed=False)
        self.assertEqual(self.request('POST', '/api/review/stt-confirm', payload)[0], 400)
        self.assertEqual(self.review.saved, [])
        self.assertEqual(self.review.rescored, 0)
        status, result, _ = self.request('POST', '/api/review/stt-confirm', {**payload, 'confirmed': True})
        self.assertEqual(status, 200)
        self.assertTrue(result['saved'])
        self.assertFalse(result['rescore']['inference_repeated'])
        self.assertEqual(self.review.rescored, 1)
        self.assertEqual(self.voice.transcribed, [])

    def test_rating_is_explicit_and_not_final_voice_acceptance(self):
        payload = dict(id='bataa-raw', listener='fixture only', overall=3, intelligibility=4,
                       pronunciation_errors='fixture observation', confirmed=False)
        self.assertEqual(self.request('POST', '/api/review/tts-confirm', payload)[0], 400)
        _, result, _ = self.request('POST', '/api/review/tts-confirm', {**payload, 'confirmed': True})
        self.assertTrue(result['saved'])
        self.assertFalse(result['mos_computed'])
        self.assertFalse(result['final_voice_selected'])

    def test_reset_whitelists_fields_and_keeps_originals(self):
        self.assertEqual(self.request('POST', '/api/voice/reset', dict(ids=[], path='../audio'))[0], 400)
        _, result, _ = self.request('POST', '/api/voice/reset', dict(ids=['b' * 32]))
        self.assertFalse(result['original_recordings_modified'])
        self.assertEqual(self.voice.deleted, ['b' * 32])


if __name__ == '__main__':
    unittest.main()
