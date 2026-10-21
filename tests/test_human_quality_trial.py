import copy
from concurrent.futures import ThreadPoolExecutor
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from tools import human_quality_trial as trial


class TrialFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root/'runtime').mkdir()
        self.patch_root = patch.object(trial, 'ROOT', self.root)
        self.patch_root.start()
        self.addCleanup(self.patch_root.stop)
        self.audio_dir = self.root/'runtime/audio'
        self.audio_dir.mkdir()
        self.audio = self.audio_dir/'test.mp3'
        self.audio.write_bytes(b'fixture audio bytes, not synthesized or human heard')
        self.audio_results = self.audio_dir/'results.json'
        self.audio_results.write_text(json.dumps(dict(cases=[dict(id='fixture',
            written='Invented fixture: 2000. Name Sora.', critical_values={'year':'2000','name':'Sora'},
            audio=[dict(path='test.mp3', voice='fixture-voice', variant='after',
                sha256=hashlib.sha256(self.audio.read_bytes()).hexdigest(), success=True)])])), encoding='utf-8')
        self.review_file = self.root/'runtime/review.json'
        self.bundle = dict(rows=[dict(review_id='R001', query='Invented fixture question?',
            answer='17 seats.', required_facts=['17 seats.'],
            source_refs=[dict(quote='17 seats.', url='https://nmct.edu.mn/test')])])
        self.save_bundle()
        self.study = trial.HumanTrial(self.root/'runtime/study', self.audio_results, self.review_file)
        self.sid = self.study.start(dict(pseudonym='P001', consent=True,
            audio_storage_consent=True, implementation_participation=False))['session_id']

    def save_bundle(self):
        self.review_file.write_text(json.dumps(self.bundle), encoding='utf-8')

    def listen_body(self):
        sample = self.study.state(self.sid)['listening'][0]
        return dict(session_id=self.sid, sample_id=sample['sample_id'], audio_sha256=sample['audio_sha256'],
            heard_values={'year':'2000', 'name':'Sora'}, intelligibility=4, naturalness=3,
            listened=True, playback_ended=True)

    def review_body(self):
        return dict(session_id=self.sid, review_id='R001', correctness='correct', completeness='correct',
            citation_support='correct', reason='Fixture source agrees.')

    def task(self):
        return self.study.begin_task(dict(session_id=self.sid, intended_request='My own intended request.'))['task_id']

    def route_body(self, task_id, condition='typed', text=None, confirmed=False):
        return dict(session_id=self.sid, task_id=task_id, condition=condition,
            edited_text=text, edit_confirmed=confirmed)

class HumanQualityTests(TrialFixture):
    def test_preparation_and_session_create_no_human_scores(self):
        state = self.study.state(self.sid)
        self.assertEqual(state['completed_reviews'], [])
        self.assertEqual(state['completed_listening'], [])
        self.assertEqual(len(list(self.study.directory.glob('*-consent.json'))), 1)
        self.assertEqual(list(self.study.directory.glob(self.sid+'-*-answer-review.json')), [])
        self.assertNotIn('condition', state['listening'][0])
        self.assertNotIn('written', state['listening'][0])
        self.assertNotIn('condition', state['answers'][0])

    def test_consent_pseudonym_and_explicit_booleans_required(self):
        for mutation in [dict(pseudonym='Real Name'), dict(consent=False),
                         dict(audio_storage_consent=1), dict(implementation_participation=None)]:
            body = dict(pseudonym='P002', consent=True, audio_storage_consent=False, implementation_participation=False)
            body.update(mutation)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.study.start(body)

    def test_answer_ratings_require_all_dimensions_reason_and_are_immutable(self):
        body = self.review_body()
        for mutation in [dict(correctness=''), dict(completeness=1), dict(reason=''), dict(route='C')]:
            candidate = dict(body, **mutation)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.study.review(candidate)
        self.study.review(body)
        with self.assertRaises(trial.TrialConflict):
            self.study.review(body)
        records = list(self.study.directory.glob(self.sid+'-*-answer-review.json'))
        self.assertEqual(len(records), 1)
        actual = json.loads(records[0].read_text(encoding='utf-8'))
        self.assertFalse(actual['human_observer_verified'])
        self.assertEqual(actual['human_review_source'], 'explicit_browser_self_report')
        self.assertEqual(actual['answer_bundle_sha256'], hashlib.sha256(self.review_file.read_bytes()).hexdigest())

    def test_blind_answers_frozen_and_tampering_rejected(self):
        self.study.state(self.sid)
        self.bundle['rows'][0]['answer'] = '18 seats.'
        self.save_bundle()
        with self.assertRaises(trial.TrialConflict):
            self.study.review(self.review_body())

    def test_missing_answer_bundle_is_pending_not_fabricated(self):
        self.review_file.unlink()
        value = self.study.state(self.sid)
        self.assertFalse(value['answer_ready'])
        self.assertEqual(value['answers'], [])

    def test_condition_leak_in_answer_bundle_rejected(self):
        self.bundle['rows'][0]['condition'] = 'LLM'
        self.save_bundle()
        with self.assertRaisesRegex(ValueError, 'omit condition'):
            self.study.state(self.sid)

    def test_simultaneous_first_freeze_is_single_snapshot_without_collision(self):
        entered, release = threading.Event(), threading.Event()
        original = Path.read_bytes
        reads = []
        def read(path):
            if path == self.review_file:
                reads.append(str(path))
                if len(reads) == 1:
                    entered.set()
                    self.assertTrue(release.wait(3))
            return original(path)
        with patch.object(Path, 'read_bytes', read), ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.study._answers)
            self.assertTrue(entered.wait(3))
            second = pool.submit(self.study._answers)
            release.set()
            self.assertEqual(first.result(3), second.result(3))
        self.assertEqual(len(list(self.study.directory.glob('frozen-answer-review.json'))), 1)

    def test_fixed_upstream_ignores_environment_proxy_and_refuses_redirect(self):
        requests = []
        class Fixture(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                requests.append(self.path)
                if self.path == '/redirect':
                    self.send_response(302)
                    self.send_header('Location', '/forbidden-follow')
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                else:
                    raw = b'{"fixed_loopback":true}'
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        # Redirect/proxy behavior is exercised against a constructed local fixture only.
        self.study.upstream = f'http://127.0.0.1:{server.server_port}'
        with patch.dict(os.environ, {'http_proxy':'http://127.0.0.1:1', 'HTTP_PROXY':'http://127.0.0.1:1',
                                    'no_proxy':'', 'NO_PROXY':''}):
            self.assertTrue(self.study._upstream('/direct')['fixed_loopback'])
            with self.assertRaisesRegex(ValueError, 'HTTP 302'):
                self.study._upstream('/redirect')
        self.assertEqual(requests, ['/direct', '/redirect'])

    def test_listening_requires_every_heard_field_and_matching_hash(self):
        body = self.listen_body()
        for mutation in [dict(heard_values={'year':'2000'}), dict(listened=False),
                         dict(playback_ended=False), dict(audio_sha256='0'*64), dict(intelligibility=True)]:
            candidate = dict(body, **mutation)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.study.listen(candidate)
        self.assertEqual(self.study.state(self.sid)['completed_listening'], [])

    def test_reference_hidden_until_all_responses_saved_and_no_overwrite(self):
        with self.assertRaises(trial.TrialConflict):
            self.study.reveal(self.sid)
        body = self.listen_body()
        self.study.listen(body)
        with self.assertRaises(trial.TrialConflict):
            self.study.listen(body)
        value = self.study.reveal(self.sid)
        self.assertEqual(value[0]['critical_values']['year'], '2000')

    def test_fixed_audio_tamper_rejected_before_human_result(self):
        body = self.listen_body()
        self.audio.write_bytes(b'tampered same or different length')
        with self.assertRaises(trial.TrialConflict):
            self.study.listen(body)
        self.assertEqual(list(self.study.directory.glob('*-listening.json')), [])

    def test_event_hash_chain_binds_saved_evidence(self):
        self.study.listen(self.listen_body())
        self.study.review(self.review_body())
        files = sorted(self.study.directory.glob(self.sid+'-*.json'))
        previous = None
        for file in files:
            raw = file.read_bytes()
            value = json.loads(raw)
            self.assertEqual(value['previous_event_sha256'], previous)
            previous = hashlib.sha256(raw).hexdigest()

    def test_task_intent_is_before_stt_and_never_asr_reference(self):
        self.task()
        value = json.loads(next(self.study.directory.glob('*-task-start.json')).read_text(encoding='utf-8'))
        self.assertTrue(value['intent_entered_before_stt'])
        self.assertIsNone(value['asr_utterance_reference'])
        self.assertFalse(value['human_utterance_reference_confirmed'])

    def test_audio_consent_false_blocks_upload_before_upstream(self):
        self.study.sessions[self.sid]['consent']['audio_storage_consent'] = False
        with patch.object(self.study, '_upstream') as upstream, self.assertRaisesRegex(ValueError, 'consent'):
            self.study.transcribe(self.sid, self.task(), b'voice', 'audio/wav')
        upstream.assert_not_called()

    def test_raw_uses_server_text_and_explicit_edit_requires_human_action(self):
        task_id = self.task()
        upstream_stt = dict(kind='stt', id='a'*32, text='original raw')
        result = dict(answer='fixture answer', route='C', package_id='fixture', input_lineage={'kind':'raw_stt'})
        with patch.object(self.study, '_upstream', side_effect=[upstream_stt, result, result]) as upstream:
            self.study.transcribe(self.sid, task_id, b'fixture voice', 'audio/wav')
            with self.assertRaisesRegex(ValueError, 'immutable'):
                self.study.route(self.route_body(task_id, 'raw', 'secretly changed', False))
            self.study.route(self.route_body(task_id, 'raw'))
            with self.assertRaisesRegex(ValueError, 'Explicitly confirm'):
                self.study.route(self.route_body(task_id, 'explicit-edited', 'my edit', False))
            self.study.route(self.route_body(task_id, 'explicit-edited', 'my edit', True))
            requests = [json.loads(c.args[1]) for c in upstream.call_args_list if c.args[0] == '/api/route']
            self.assertEqual(requests[0], {'query':'original raw', 'transcription_id':'a'*32})
            self.assertEqual(requests[1]['query'], 'my edit')
        saved = [json.loads(p.read_text(encoding='utf-8')) for p in self.study.directory.glob('*-task-route.json')]
        self.assertTrue(all(x['edited_intent_is_asr_gold'] is False for x in saved))

    def test_prior_task_condition_and_recording_are_not_overwritten(self):
        task_id = self.task()
        with patch.object(self.study, '_upstream', return_value=dict(answer='fixture', route='B')):
            self.study.route(self.route_body(task_id))
            with self.assertRaises(trial.TrialConflict):
                self.study.route(self.route_body(task_id))
        with patch.object(self.study, '_upstream', return_value=dict(kind='stt', id='a'*32, text='raw')):
            self.study.transcribe(self.sid, task_id, b'voice', 'audio/wav')
            with self.assertRaises(trial.TrialConflict):
                self.study.transcribe(self.sid, task_id, b'another voice', 'audio/wav')

    def test_synthesis_is_bound_to_real_result_and_other_session_audio_denied(self):
        task_id = self.task()
        route = dict(answer='fixture', route='C', package_id='v7', response_id='b'*32,
            content_release={'activation_token':'release7'})
        with patch.object(self.study, '_upstream', side_effect=[route, dict(id='c'*32)]) as upstream:
            self.study.route(self.route_body(task_id))
            self.study.speak(dict(session_id=self.sid, task_id=task_id, condition='typed'))
            request = json.loads(upstream.call_args_list[-1].args[1])
            self.assertEqual(request['release_token'], 'release7')
            self.assertEqual(request['response_id'], 'b'*32)
        sid2 = self.study.start(dict(pseudonym='P002', consent=True,
            audio_storage_consent=False, implementation_participation=False))['session_id']
        with self.assertRaises(KeyError):
            self.study.voice_audio(sid2, 'c'*32)
        with self.assertRaises(KeyError):
            self.study.voice_audio(self.sid, 'd'*32)

    def test_unheard_or_unsynthesized_audio_cannot_get_listening_scores(self):
        task_id = self.task()
        with patch.object(self.study, '_upstream', return_value=dict(answer='fixture', route='B')):
            self.study.route(self.route_body(task_id))
        body = dict(session_id=self.sid, task_id=task_id, condition='typed', task_success='partial',
            heard_answer='', tts_listened=True, intelligibility=5, naturalness=5, notes='')
        with self.assertRaisesRegex(ValueError, 'no synthesized'):
            self.study.observe(body)
        body['tts_listened'] = False
        with self.assertRaisesRegex(ValueError, 'Unheard'):
            self.study.observe(body)
        body.update(intelligibility=None, naturalness=None)
        self.study.observe(body)
        with self.assertRaises(trial.TrialConflict):
            self.study.observe(body)


class HumanTrialHTTPTests(TrialFixture):
    def setUp(self):
        super().setUp()
        self.server = trial.make_server(self.study, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.origin = f'http://127.0.0.1:{self.server.server_port}'

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        self.addCleanup(conn.close)
        raw = json.dumps(body).encode() if body is not None else None
        supplied = {'Origin':self.origin, 'X-Trial-Token':self.study.token, 'Content-Type':'application/json'}
        supplied.update(headers or {})
        conn.request(method, path, raw, supplied)
        response = conn.getresponse()
        data = response.read()
        return response.status, data, dict(response.getheaders())

    def test_real_http_page_state_listening_save_and_reveal(self):
        code, raw, headers = self.request('GET', '/')
        self.assertEqual(code, 200)
        self.assertIn('Санаагаа', raw.decode('utf-8'))
        self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
        self.assertEqual(self.request('GET', '/api/reveal?session_id='+self.sid)[0], 409)
        self.assertEqual(self.request('POST', '/api/listen', self.listen_body())[0], 200)
        code, raw, _ = self.request('GET', '/api/reveal?session_id='+self.sid)
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(raw)['references'][0]['critical_values']['year'], '2000')

    def test_cross_origin_host_csrf_missing_required_and_no_arbitrary_paths(self):
        for headers in [dict(Origin='https://attacker.test'), {'Host':'attacker.test'},
                        {'X-Trial-Token':'invalid'}, {'X-Trial-Token':'é'}]:
            with self.subTest(headers=headers):
                self.assertEqual(self.request('POST', '/api/review', self.review_body(), headers)[0], 403)
        self.assertEqual(self.request('POST', '/api/listen', {'session_id':self.sid})[0], 400)
        self.assertEqual(self.request('GET', '/api/voice-audio/'+('a'*32)+'?session_id='+self.sid)[0], 404)
        self.assertEqual(self.request('GET', '/../../private.json')[0], 404)

    def test_get_framing_and_blank_transfer_encoding_are_rejected(self):
        for headers in [{'Content-Length':'1'}, {'Content-Length':'bogus'}, {'Content-Length':'-1'},
                        {'Transfer-Encoding':''}, {'Transfer-Encoding':'chunked'}]:
            with self.subTest(headers=headers):
                self.assertEqual(self.request('GET', '/api/state', headers=headers)[0], 400)
        self.assertEqual(self.request('GET', '/api/state', headers={'Content-Length':'0'})[0], 200)
        self.assertEqual(self.request('POST', '/api/review', self.review_body(), {'Transfer-Encoding':''})[0], 400)


if __name__ == '__main__':
    unittest.main()
