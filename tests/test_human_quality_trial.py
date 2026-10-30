import copy
from concurrent.futures import ThreadPoolExecutor
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import struct
import unittest
import wave
from unittest.mock import patch

from tools import human_quality_trial as trial


class HumanQualityPageTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node.js is optional for isolated UI checks.')
    def test_reference_recovery_and_busy_recorder_handlers(self):
        root = Path(__file__).resolve().parents[1]
        script = trial.PAGE.split('<script>', 1)[1].split('</script>', 1)[0]
        result = subprocess.run([shutil.which('node'), str(root/'tests/human_quality_ui_harness.js')],
            input=script, capture_output=True, text=True, encoding='utf-8', timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        report = json.loads(result.stdout)
        self.assertGreaterEqual(report['passed'], 7)
        self.assertTrue(report['constructed_fixtures'])
        self.assertEqual(report['model_calls'], 0)


class TrialFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        wav = io.BytesIO()
        with wave.open(wav, 'wb') as stream:
            stream.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
            stream.writeframes(b''.join(struct.pack('<h', int(1000 * math.sin(i / 10))) for i in range(1600)))
        self.recording = wav.getvalue()  # Constructed tone, never a human utterance.
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

    def capture(self, task_id):
        return self.study.capture_recording(self.sid, task_id, self.recording, 'audio/wav')

    def reference_body(self, task_id, digest):
        return dict(session_id=self.sid, task_id=task_id, audio_sha256=digest,
            reference='Constructed words for gate testing, not a real human reference.',
            uncertainties=[], listened=True, playback_ended=True, confirmed=True)

    def ready_recording(self, task_id):
        captured = self.capture(task_id)
        self.study.confirm_reference(self.reference_body(task_id, captured['audio_sha256']))
        return captured

class HumanQualityTests(TrialFixture):
    def resume(self):
        return trial.HumanTrial(self.study.directory, self.audio_results, self.review_file, resume=True)

    def snapshot(self):
        return {p.relative_to(self.study.directory).as_posix(): p.read_bytes()
                for p in self.study.directory.rglob('*') if p.is_file()}

    def test_resume_retains_ratings_consent_chain_and_makes_no_new_human_events(self):
        self.study.listen(self.listen_body())
        self.study.review(self.review_body())
        before = self.snapshot()
        with patch.object(trial.HumanTrial, '_upstream') as upstream:
            restored = self.resume()
            state = restored.state(self.sid)
        upstream.assert_not_called()
        self.assertEqual(before, self.snapshot())
        self.assertEqual(state['completed_listening'], self.study.state(self.sid)['completed_listening'])
        self.assertEqual(state['completed_reviews'], ['R001'])
        self.assertEqual(restored.sessions[self.sid]['consent'], self.study.sessions[self.sid]['consent'])
        self.assertNotEqual(restored.token, self.study.token)
        self.assertEqual(restored.sessions[self.sid]['last_sha'], self.study.sessions[self.sid]['last_sha'])
        with self.assertRaises(trial.TrialConflict):
            restored.listen(self.listen_body())
        task_id = restored.begin_task(dict(session_id=self.sid, intended_request='A new explicit human task.'))['task_id']
        self.assertEqual(restored.state(self.sid)['active_task']['task_id'], task_id)
        last = sorted(self.study.directory.glob(self.sid + '-*.json'))[-1]
        self.assertEqual(json.loads(last.read_bytes())['previous_event_sha256'], self.study.sessions[self.sid]['last_sha'])

    def test_resume_keeps_recording_and_confirmed_reference_without_automatic_asr(self):
        task_id = self.task()
        captured = self.ready_recording(task_id)
        before = self.snapshot()
        with patch.object(trial.HumanTrial, '_upstream') as upstream:
            restored = self.resume()
        upstream.assert_not_called()
        self.assertEqual(before, self.snapshot())
        value = restored.state(self.sid)['active_task']
        self.assertEqual(value['recording']['audio_sha256'], captured['audio_sha256'])
        self.assertEqual(value['reference']['text'], self.reference_body(task_id, captured['audio_sha256'])['reference'])
        self.assertFalse(value['transcription_attempted'])
        with patch.object(restored, '_upstream', return_value=dict(kind='stt', id='a'*32, text='fixture raw')) as upstream:
            restored.transcribe(self.sid, task_id)
        self.assertEqual(upstream.call_count, 1)
        self.assertEqual(upstream.call_args.args[1], restored.recording_audio(self.sid, task_id)[0])

    def test_resume_pending_draft_never_becomes_confirmed_reference(self):
        task_id = self.task()
        clip = self.capture(task_id)
        body = dict(self.reference_body(task_id, clip['audio_sha256']), uncertainties=['unclear number'])
        self.study.confirm_reference(body)
        restored = self.resume()
        value = restored.state(self.sid)['active_task']
        self.assertEqual(value['reference_draft']['uncertainties'], ['unclear number'])
        self.assertIsNone(value['reference'])
        with patch.object(restored, '_upstream') as upstream, self.assertRaises(ValueError):
            restored.transcribe(self.sid, task_id)
        upstream.assert_not_called()

    def test_resume_failed_or_interrupted_asr_never_retries_the_attempt(self):
        task_id = self.task()
        self.ready_recording(task_id)
        with patch.object(self.study, '_upstream', side_effect=ValueError('fixture failure')):
            with self.assertRaises(ValueError):
                self.study.transcribe(self.sid, task_id)
        restored = self.resume()
        self.assertTrue(restored.state(self.sid)['active_task']['transcription_attempted'])
        with patch.object(restored, '_upstream') as upstream, self.assertRaises(trial.TrialConflict):
            restored.transcribe(self.sid, task_id)
        upstream.assert_not_called()
        self.assertEqual(restored.state(self.sid)['active_task']['last_error']['operation'], 'transcribe')

    def test_resume_preserves_saved_routes_tts_and_observations_without_regeneration(self):
        task_id = self.task()
        self.ready_recording(task_id)
        with patch.object(self.study, '_upstream', side_effect=[
                dict(kind='stt', id='a'*32, text='fixture raw'),
                dict(answer='fixture', route='C', package_id='v1'), dict(id='b'*32)]):
            self.study.transcribe(self.sid, task_id)
            self.study.route(self.route_body(task_id, 'raw'))
            self.study.speak(dict(session_id=self.sid, task_id=task_id, condition='raw'))
        observation = dict(session_id=self.sid, task_id=task_id, condition='raw', task_success='partial',
            heard_answer='fixture heard words', intelligibility=3, naturalness=3, tts_listened=True, notes='fixture note')
        self.study.observe(observation)
        before = self.snapshot()
        with patch.object(trial.HumanTrial, '_upstream') as upstream:
            restored = self.resume()
        upstream.assert_not_called()
        self.assertEqual(before, self.snapshot())
        row = restored.state(self.sid)['active_task']['results'][0]
        self.assertEqual(row['condition'], 'raw')
        self.assertTrue(row['observation_saved'])
        self.assertIn('b'*32, restored.sessions[self.sid]['tasks'][task_id]['audio_ids'])
        with self.assertRaises(trial.TrialConflict):
            restored.observe(observation)
        with self.assertRaises(trial.TrialConflict):
            restored.route(self.route_body(task_id, 'raw'))

    def test_resume_rejects_changed_journal_manifest_bundle_and_audio_without_writes(self):
        self.study.listen(self.listen_body())
        task_id = self.task()
        self.capture(task_id)
        files = self.snapshot()
        consent = next(p for p in self.study.directory.glob('*-consent.json'))
        frozen = self.study.directory / 'frozen-answer-review.json'
        audio = self.study.directory / self.study.sessions[self.sid]['tasks'][task_id]['recording']['audio_file']
        for path in (consent, frozen, audio, self.study.directory / 'manifest.json'):
            with self.subTest(path=path.name):
                original = path.read_bytes()
                path.write_bytes(original.replace(b'P001', b'P002') if path == consent else b'{}')
                changed = self.snapshot()
                with self.assertRaises((ValueError, KeyError)):
                    self.resume()
                self.assertEqual(changed, self.snapshot())
                path.write_bytes(original)
        missing = next(p for p in self.study.directory.glob('*-listening.json'))
        original = missing.read_bytes()
        missing.unlink()  # Fixture only; verifies a sequence gap cannot be ignored.
        with self.assertRaises(ValueError):
            self.resume()
        missing.write_bytes(original)
        self.assertEqual(files, self.snapshot())

    def test_resume_is_explicit_and_does_not_create_a_missing_study(self):
        with self.assertRaises(FileExistsError):
            trial.HumanTrial(self.study.directory, self.audio_results, self.review_file)
        missing = self.root / 'runtime/missing-study'
        with self.assertRaises(ValueError):
            trial.HumanTrial(missing, self.audio_results, self.review_file, resume=True)
        self.assertFalse(missing.exists())

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

    def test_capture_preserves_original_and_decodes_native_wav_without_asr(self):
        task_id = self.task()
        with patch.object(self.study, '_upstream') as upstream:
            captured = self.capture(task_id)
        upstream.assert_not_called()
        self.assertFalse(captured['asr_performed'])
        raw, mime = self.study.recording_audio(self.sid, task_id)
        self.assertEqual(mime, 'audio/wav')
        with wave.open(io.BytesIO(raw), 'rb') as stream:
            self.assertEqual((stream.getnchannels(), stream.getsampwidth(), stream.getframerate()), (1, 2, 16000))
        task = self.study.sessions[self.sid]['tasks'][task_id]
        self.assertIsNone(task['reference'])
        self.assertIsNone(task['transcript'])
        self.assertEqual((self.study.directory / task['recording']['original_audio_file']).read_bytes(), self.recording)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), captured['audio_sha256'])
        with self.assertRaises(trial.TrialConflict):
            self.capture(task_id)

    def test_asr_gate_blocks_missing_reference_and_preserves_uncertainty_drafts(self):
        task_id = self.task()
        with patch.object(self.study, '_upstream') as upstream:
            with self.assertRaisesRegex(ValueError, 'reference before local ASR'):
                self.study.transcribe(self.sid, task_id)
            captured = self.capture(task_id)
            body = self.reference_body(task_id, captured['audio_sha256'])
            for mutation in [dict(uncertainties=['year unclear']), dict(confirmed=False)]:
                pending = self.study.confirm_reference(dict(body, **mutation))
                self.assertFalse(pending['reference_confirmed_before_asr'])
                with self.assertRaises(ValueError):
                    self.study.transcribe(self.sid, task_id)
        upstream.assert_not_called()
        self.assertEqual(len(list(self.study.directory.glob('*-task-reference-pending.json'))), 2)
        self.assertIsNone(self.study.sessions[self.sid]['tasks'][task_id]['reference'])

    def test_unchanged_pending_draft_is_idempotent_and_never_opens_asr(self):
        task_id = self.task()
        clip = self.capture(task_id)
        body = dict(self.reference_body(task_id, clip['audio_sha256']), uncertainties=['unclear year'])
        first = self.study.confirm_reference(body)
        second = self.study.confirm_reference(body)
        self.assertEqual(first['unresolved_count'], 1)
        self.assertEqual(second['pending_reason'], 'unresolved_words')
        self.assertTrue(second['duplicate_draft'])
        self.assertEqual(len(list(self.study.directory.glob('*-task-reference-pending.json'))), 1)
        with patch.object(self.study, '_upstream') as upstream, self.assertRaises(ValueError):
            self.study.transcribe(self.sid, task_id)
        upstream.assert_not_called()
        self.assertIsNone(self.study.state(self.sid)['active_task']['reference'])
        # Only a new explicit human confirmation with no uncertainty opens ASR.
        self.assertTrue(self.study.confirm_reference(dict(body, uncertainties=[]))['reference_confirmed_before_asr'])

    def test_reference_requires_exact_audio_listening_and_well_typed_fields(self):
        task_id = self.task()
        captured = self.capture(task_id)
        body = self.reference_body(task_id, captured['audio_sha256'])
        for mutation in [dict(audio_sha256='0' * 64), dict(listened=False), dict(playback_ended=False),
                         dict(confirmed=1), dict(reference='?!'), dict(uncertainties='not a list')]:
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.study.confirm_reference(dict(body, **mutation))
        self.assertEqual(list(self.study.directory.glob('*-task-reference.json')), [])

    def test_frozen_reference_precedes_asr_and_is_never_sent_upstream(self):
        task_id = self.task()
        captured = self.ready_recording(task_id)
        with patch.object(self.study, '_upstream', return_value=dict(kind='stt', id='a' * 32, text='raw')) as upstream:
            self.study.transcribe(self.sid, task_id)
        args = upstream.call_args.args
        self.assertEqual(args, ('/api/voice/transcribe', self.study.recording_audio(self.sid, task_id)[0], 'audio/wav'))
        self.assertNotIn(b'Constructed words', args[1])
        with self.assertRaises(trial.TrialConflict):
            self.study.confirm_reference(self.reference_body(task_id, captured['audio_sha256']))
        files = sorted(self.study.directory.glob(self.sid + '-*.json'))
        events = [json.loads(path.read_bytes()) for path in files]
        kinds = [event['kind'] for event in events]
        self.assertLess(kinds.index('task-recording'), kinds.index('task-reference'))
        self.assertLess(kinds.index('task-reference'), kinds.index('task-stt-attempt'))
        stt = next(event for event in events if event['kind'] == 'task-stt')
        self.assertTrue(stt['reference_confirmed_before_asr'])
        self.assertTrue(stt['reference_not_sent_to_asr'])
        self.assertEqual(stt['asr_utterance_reference'], self.reference_body(task_id, captured['audio_sha256'])['reference'])

    def test_retained_wav_tamper_blocks_reference_and_asr(self):
        task_id = self.task()
        captured = self.capture(task_id)
        task = self.study.sessions[self.sid]['tasks'][task_id]
        path = self.study.directory / task['recording']['audio_file']
        old = path.read_bytes()
        path.write_bytes(b'tampered')
        with self.assertRaises(trial.TrialConflict):
            self.study.confirm_reference(self.reference_body(task_id, captured['audio_sha256']))
        path.write_bytes(old)
        self.study.confirm_reference(self.reference_body(task_id, captured['audio_sha256']))
        path.write_bytes(b'tampered again')
        with patch.object(self.study, '_upstream') as upstream, self.assertRaises(trial.TrialConflict):
            self.study.transcribe(self.sid, task_id)
        upstream.assert_not_called()

    def test_asr_failure_is_recorded_and_never_automatically_retried(self):
        task_id = self.task()
        self.ready_recording(task_id)
        with patch.object(self.study, '_upstream', side_effect=ValueError('fixture unavailable')) as upstream:
            with self.assertRaisesRegex(ValueError, 'fixture unavailable'):
                self.study.transcribe(self.sid, task_id)
            with self.assertRaises(trial.TrialConflict):
                self.study.transcribe(self.sid, task_id)
        self.assertEqual(upstream.call_count, 1)
        self.assertEqual(len(list(self.study.directory.glob('*-task-error.json'))), 1)

    def test_context_and_declared_canonical_person_are_retained(self):
        task_id = self.study.begin_task(dict(session_id=self.sid, intended_request='Constructed request',
            device='fixture microphone', room='fixture room', scenario='fixture school question'))['task_id']
        self.capture(task_id)
        value = json.loads(next(self.study.directory.glob('*-task-start.json')).read_bytes())
        self.assertEqual((value['speaker_id'], value['speaker_group_id'], value['session_id']), ('P001', 'P001', self.sid))
        self.assertTrue(value['recording_context_reported'])
        self.assertEqual(value['recording_context']['room'], 'fixture room')
        sid2 = self.study.start(dict(pseudonym='P001', consent=True,
            audio_storage_consent=True, implementation_participation=False))['session_id']
        with self.assertRaises(KeyError):
            self.study.recording_audio(sid2, task_id)

    def test_invalid_audio_is_retained_as_error_and_never_invokes_asr(self):
        task_id = self.task()
        with patch.object(self.study, '_upstream') as upstream, self.assertRaisesRegex(ValueError, 'decoded to study WAV'):
            self.study.capture_recording(self.sid, task_id, b'not real audio', 'audio/wav')
        upstream.assert_not_called()
        self.assertIsNone(self.study.sessions[self.sid]['tasks'][task_id]['recording'])
        self.assertEqual(len(list((self.study.directory / 'recordings').glob('*.audio'))), 1)
        error = json.loads(next(self.study.directory.glob('*-task-error.json')).read_bytes())
        self.assertEqual(error['operation'], 'prepare_audio')

    def test_long_recording_reports_limit_preserves_original_and_allows_short_retry(self):
        task_id = self.task()
        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as stream:
            stream.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
            stream.writeframes(b'\0\0' * (16000 * 31))  # Synthetic silence, not human speech.
        original = buffer.getvalue()
        with patch.object(self.study, '_upstream') as upstream:
            with self.assertRaisesRegex(ValueError, '30 секундээс урт'):
                self.study.capture_recording(self.sid, task_id, original, 'audio/wav')
        upstream.assert_not_called()
        saved = next((self.study.directory / 'recordings').glob('*.audio'))
        self.assertEqual(saved.read_bytes(), original)
        event = json.loads(next(self.study.directory.glob('*-task-error.json')).read_bytes())
        self.assertEqual(event['error_code'], 'audio_too_long')
        self.assertIsNone(self.study.sessions[self.sid]['tasks'][task_id]['reference'])
        self.assertFalse(self.study.sessions[self.sid]['tasks'][task_id]['transcription_attempted'])
        self.assertFalse(self.capture(task_id)['asr_performed'])
        self.assertEqual(saved.read_bytes(), original)

    def test_custom_sourced_tts_metadata_is_hidden_until_reveal(self):
        bundle = json.loads(self.audio_results.read_bytes())
        bundle.update(constructed=False, text_scope_mn='Frozen source scope, not current school policy.')
        bundle['cases'][0].update(source_refs=[dict(url='https://nmct.edu.mn/test', quote='Frozen source words')],
            critical_reference_sha256='c' * 64)
        self.audio_results.write_text(json.dumps(bundle), encoding='utf-8')
        custom = trial.HumanTrial(self.root / 'runtime/custom-study', self.audio_results, self.review_file)
        sid = custom.start(dict(pseudonym='P001', consent=True,
            audio_storage_consent=False, implementation_participation=False))['session_id']
        state = custom.state(sid)
        self.assertEqual(state['listening_text_scope'], bundle['text_scope_mn'])
        serialized = json.dumps(state['listening'])
        self.assertNotIn('Frozen source words', serialized)
        self.assertNotIn('critical_reference_sha256', serialized)
        sample = state['listening'][0]
        custom.listen(dict(self.listen_body(), session_id=sid, sample_id=sample['sample_id']))
        revealed = custom.reveal(sid)[0]
        self.assertEqual(revealed['source_refs'], bundle['cases'][0]['source_refs'])
        self.assertEqual(revealed['critical_reference_sha256'], 'c' * 64)

    def test_audio_consent_false_blocks_upload_before_upstream(self):
        self.study.sessions[self.sid]['consent']['audio_storage_consent'] = False
        with patch.object(self.study, '_upstream') as upstream, self.assertRaisesRegex(ValueError, 'consent'):
            self.capture(self.task())
        upstream.assert_not_called()

    def test_raw_uses_server_text_and_explicit_edit_requires_human_action(self):
        task_id = self.task()
        upstream_stt = dict(kind='stt', id='a'*32, text='original raw')
        result = dict(answer='fixture answer', route='C', package_id='fixture', input_lineage={'kind':'raw_stt'})
        self.ready_recording(task_id)
        with patch.object(self.study, '_upstream', side_effect=[upstream_stt, result, result]) as upstream:
            self.study.transcribe(self.sid, task_id)
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
            self.ready_recording(task_id)
            self.study.transcribe(self.sid, task_id)
            with self.assertRaises(trial.TrialConflict):
                self.study.transcribe(self.sid, task_id)

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
        raw = body if isinstance(body, bytes) else json.dumps(body).encode() if body is not None else None
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

    def test_http_record_reference_then_asr_uses_retained_wav_only(self):
        task_id = self.task()
        body = dict(session_id=self.sid, task_id=task_id)
        with patch.object(self.study, '_upstream', return_value=dict(kind='stt', id='a' * 32, text='fixture raw')) as upstream:
            self.assertEqual(self.request('POST', '/api/task/transcribe', body)[0], 400)
            code, raw, _ = self.request('POST', '/api/task/record', self.recording,
                {'Content-Type': 'audio/wav', 'X-Session-Id': self.sid, 'X-Task-Id': task_id})
            self.assertEqual(code, 200)
            captured = json.loads(raw)
            code, wav, headers = self.request('GET', captured['audio_url'])
            self.assertEqual(code, 200)
            self.assertEqual(headers['Content-Type'], 'audio/wav')
            self.assertTrue(wav.startswith(b'RIFF'))
            self.assertEqual(self.request('POST', '/api/task/transcribe', body)[0], 400)
            upstream.assert_not_called()
            ref = self.reference_body(task_id, captured['audio_sha256'])
            self.assertEqual(self.request('POST', '/api/task/reference', ref)[0], 200)
            self.assertEqual(self.request('POST', '/api/task/transcribe', body)[0], 200)
        self.assertEqual(upstream.call_count, 1)


if __name__ == '__main__':
    unittest.main()
