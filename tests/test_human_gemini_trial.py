"""Gemini-only trial contracts with constructed audio and fake local upstream."""
import json
from unittest.mock import patch
from tests.test_human_quality_trial import TrialFixture
from tools import human_quality_trial as trial


class HumanGeminiTests(TrialFixture):
    def setUp(self):
        super().setUp()
        self.study.stt_provider='gemini_live'

    def responses(self, path, body=None, mime='application/json', **kwargs):
        if path=='/api/voice/gemini/session':
            return dict(ready=True,model=trial.LIVE_MODEL,csrf_token='fixture-session-token')
        self.assertEqual(path,'/api/voice/transcribe')
        self.assertIsInstance(body,bytes)
        headers=kwargs['extra_headers']
        self.assertEqual(headers['X-Gemini-Token'],'fixture-session-token')
        self.assertEqual(headers['X-STT-Provider'],'gemini_live')
        self.assertEqual(headers['X-Gemini-Audio-Consent'],'send-this-audio')
        self.assertNotIn(b'Constructed words',body,'The reference must never be provider context')
        return dict(kind='stt',id='a'*32,text='Constructed raw words',model=trial.LIVE_MODEL,
            provider='google_gemini_live',input_sha256=trial.sha(body),translated_output_used=False,
            transcription_seconds=.05,cache_hit=False)

    def test_default_recognizer_is_single_live_model(self):
        new=trial.HumanTrial(self.root/'runtime/default-gemini',self.audio_results,self.review_file)
        self.assertEqual(new.state()['recognition_provider'],'gemini_live')
        self.assertEqual(new.state()['recognition_model'],trial.LIVE_MODEL)
        self.assertFalse(new.state()['local_audio_processing'])

    def test_local_storage_consent_cannot_authorize_cloud_audio(self):
        task=self.task();self.ready_recording(task)
        with patch.object(self.study,'_upstream') as up,self.assertRaisesRegex(ValueError,'Google'):
            self.study.transcribe(self.sid,task)
        up.assert_not_called()
        self.assertFalse(self.study._task(self.sid,task)[1]['transcription_attempted'])

    def test_live_uses_fresh_token_keeps_reference_out_and_saves_real_measurement(self):
        task=self.task();self.ready_recording(task)
        with patch.object(self.study,'_upstream',side_effect=self.responses) as up:
            result=self.study.recognize(dict(session_id=self.sid,task_id=task,cloud_audio_consent=True))
        self.assertEqual(up.call_count,2)
        self.assertEqual(result['model'],trial.LIVE_MODEL)
        self.assertGreater(result['measurement']['raw_score']['reference_words'],0)
        journal=''.join(p.read_text(encoding='utf-8') for p in self.study.directory.glob('*task-stt*.json'))
        self.assertNotIn('fixture-session-token',journal)
        events=list(self.study.directory.glob('*task-stt.json'))
        event=json.loads(events[0].read_text(encoding='utf-8'))
        self.assertTrue(event['reference_not_sent_to_asr'])
        with patch.object(trial.HumanTrial,'_upstream') as up:
            restored=trial.HumanTrial(self.study.directory,self.audio_results,self.review_file,resume=True)
            self.assertEqual(restored.state(self.sid)['active_task']['measurement'],result['measurement'])
        up.assert_not_called()

    def test_wrong_preflight_model_never_sends_audio(self):
        task=self.task();self.ready_recording(task)
        with patch.object(self.study,'_upstream',return_value=dict(ready=True,model='another-model',csrf_token='fake')) as up:
            with self.assertRaises(ValueError):self.study.transcribe(self.sid,task,cloud_audio_consent=True)
        self.assertEqual(up.call_count,1)
        self.assertFalse(self.study._task(self.sid,task)[1]['transcription_attempted'])

    def test_wrong_audio_hash_preserves_failed_attempt_and_never_retries(self):
        task=self.task();self.ready_recording(task)
        def wrong(*args,**kwargs):
            result=self.responses(*args,**kwargs)
            if args[0].endswith('transcribe'):result['input_sha256']='0'*64
            return result
        with patch.object(self.study,'_upstream',side_effect=wrong) as up:
            with self.assertRaises(ValueError):self.study.transcribe(self.sid,task,cloud_audio_consent=True)
            with self.assertRaises(trial.TrialConflict):self.study.transcribe(self.sid,task,cloud_audio_consent=True)
        self.assertEqual(up.call_count,2)

    def test_empty_raw_has_deletion_score_and_cached_result_is_labeled(self):
        task=self.task();self.ready_recording(task)
        def empty(*args,**kwargs):
            result=self.responses(*args,**kwargs)
            if args[0].endswith('transcribe'):result.update(text='',cache_hit=True,transcription_seconds=0)
            return result
        with patch.object(self.study,'_upstream',side_effect=empty):
            result=self.study.transcribe(self.sid,task,cloud_audio_consent=True)
        self.assertEqual(result['measurement']['raw_score']['corpus_wer'],1)
        self.assertTrue(result['measurement']['cache_hit'])

    def test_page_action_is_explicit_google_submission_without_provider_dropdown(self):
        self.assertIn('Google руу илгээж Gemini-ээр таних',trial.PAGE)
        self.assertIn('cloud_audio_consent:true',trial.PAGE)
        self.assertNotIn('Дууг локал Whisper',trial.PAGE)
        self.assertIn('renderMeasurement(v.measurement)',trial.PAGE)
