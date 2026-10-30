"""Synthetic Gemini session/HTTP contracts. Never contacts Google or rates human speech."""
import hashlib
import http.client
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
import wave
from unittest.mock import patch

from gemini_stt_runtime import GeminiSTT, GeminiSTTError
from tools.compare_stt_candidate import CandidateError, MODEL
from voice_runtime import VoiceRuntime, VoiceRuntimeError
from demo_server import make_server
from content_store import ContentStore
from test_demo_server import fixture


KEY = 'fixture-key-never-valid-0000000000'
CONFIG = dict(api_key=KEY, free_tier_confirmed=True, data_terms_confirmed=True, max_attempts=2)


class Transport:
    calls = []
    def __init__(self, key):
        self.key = key
    def transcribe(self, wav, **kwargs):
        self.calls.append(dict(data=wav, **kwargs))
        return dict(text='Constructed raw words', model=MODEL, usage={}, cleanup=dict(deleted=True))


class GeminiSessionTests(unittest.TestCase):
    def setUp(self):
        Transport.calls = []
        self.cloud = GeminiSTT(Transport)

    def test_configuration_is_local_memory_only_and_never_probes_network(self):
        self.cloud.configure(CONFIG)
        self.assertEqual(Transport.calls, [])
        self.assertTrue(self.cloud.status()['ready'])
        self.assertNotIn(KEY, json.dumps(self.cloud.status()))
        self.assertFalse(self.cloud.status()['key_persisted'])
        self.cloud.clear()
        self.assertFalse(self.cloud.status()['ready'])
        self.assertIsNone(self.cloud._key)

    def test_missing_consent_configuration_or_budget_never_calls_provider(self):
        with self.assertRaises(GeminiSTTError):
            self.cloud.transcribe(b'fixture', consent=True)
        self.cloud.configure(dict(CONFIG, max_attempts=1))
        with self.assertRaises(GeminiSTTError):
            self.cloud.transcribe(b'fixture', consent=False)
        self.assertEqual(Transport.calls, [])
        self.cloud.transcribe(b'fixture', consent=True)
        with self.assertRaises(GeminiSTTError):
            self.cloud.transcribe(b'fixture', consent=True)
        self.assertEqual(len(Transport.calls), 1)

    def test_free_tier_and_data_terms_must_be_explicit_and_budget_bounded(self):
        for changed in [dict(free_tier_confirmed=False),dict(data_terms_confirmed=1),
                        dict(max_attempts=6), dict(max_attempts=True), dict(api_key='bad key')]:
            with self.subTest(changed=changed), self.assertRaises(GeminiSTTError):
                self.cloud.configure(dict(CONFIG, **changed))
        self.assertEqual(Transport.calls, [])

    def test_429_consumes_attempt_and_blocks_retry_without_paid_fallback(self):
        class Limited(Transport):
            def transcribe(self, wav, **kwargs):
                self.calls.append({})
                raise CandidateError('http_429')
        cloud = GeminiSTT(Limited)
        cloud.configure(CONFIG)
        with self.assertRaisesRegex(GeminiSTTError, '429'):
            cloud.transcribe(b'fixture', consent=True)
        with self.assertRaises(GeminiSTTError):
            cloud.transcribe(b'fixture', consent=True)
        self.assertEqual(len(Transport.calls), 1)
        self.assertEqual(cloud.status()['attempted'], 1)
        self.assertFalse(cloud.status()['paid_fallback'])

    def test_raw_provider_failure_cannot_expose_secret(self):
        class Failed(Transport):
            def transcribe(self, wav, **kwargs):
                raise RuntimeError(KEY)
        cloud = GeminiSTT(Failed)
        cloud.configure(CONFIG)
        with self.assertRaises(GeminiSTTError) as error:
            cloud.transcribe(b'fixture', consent=True)
        self.assertNotIn(KEY, str(error.exception))

    def test_parallel_request_is_rejected_before_duplicate_upload(self):
        self.cloud.configure(CONFIG)
        self.cloud._lock.acquire()
        try:
            with self.assertRaises(GeminiSTTError):
                self.cloud.transcribe(b'fixture', consent=True)
            with self.assertRaises(GeminiSTTError):
                self.cloud.configure(CONFIG)
        finally:
            self.cloud._lock.release()
        self.assertEqual(Transport.calls, [])


class GeminiVoiceTests(unittest.TestCase):
    def test_wrong_language_is_preserved_and_warned_instead_of_claiming_mongolian_success(self):
        from gemini_live_transport import LIVE_MODEL
        from test_gemini_live import wav_bytes
        class WrongLanguage(Transport):
            def transcribe(self,*_,**__):
                return dict(text='日本語',model=LIVE_MODEL,detected_language_codes=['ja'])
        with tempfile.TemporaryDirectory() as directory:
            runtime=VoiceRuntime(directory)
            runtime.gemini=GeminiSTT(live_transport_factory=WrongLanguage)
            runtime.gemini.configure(CONFIG)
            result=runtime.transcribe_gemini(wav_bytes(),'audio/wav',consent=True,live=True)
        self.assertEqual(result['text'],'日本語')
        self.assertTrue(result['recognition_review']['unexpected_language'])
        self.assertIn('Монгол хэлээр танигдсангүй',result['message'])
        self.assertFalse(result['accuracy_measured'])

    def test_native_audio_is_bounded_then_cloud_raw_is_bound_to_existing_lineage(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = VoiceRuntime(directory)
            runtime.gemini = GeminiSTT(Transport)
            runtime.gemini.configure(CONFIG)
            pcm = b'\x10\x00' * 16000
            raw = io.BytesIO()
            with wave.open(raw, 'wb') as stream:
                stream.setparams((1,2,16000,0,'NONE','not compressed'))
                stream.writeframes(pcm)
            with patch.object(runtime, '_load_model') as whisper:
                result = runtime.transcribe_gemini(raw.getvalue(), 'audio/wav', consent=True)
            whisper.assert_not_called()
            self.assertEqual(result['model'], MODEL)
            self.assertEqual(result['provider'], 'google_gemini')
            self.assertFalse(result['local_files_only'])
            self.assertFalse(result['reference_confirmed'])
            self.assertEqual(result['input_sha256'], hashlib.sha256(raw.getvalue()).hexdigest())
            self.assertEqual(runtime.transcription_lineage(result['id'], result['text'])['kind'], 'raw_stt')
            for file in Path(directory).rglob('*'):
                if file.is_file():
                    self.assertNotIn(KEY.encode(), file.read_bytes())
            with self.assertRaises(VoiceRuntimeError):
                runtime.transcribe_gemini(raw.getvalue(), 'audio/wav', consent=False)


class GeminiHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name)
        database = root/'content.db'
        with ContentStore(database) as store:
            store.import_content(fixture(), allow_draft=True)
        self.voice = VoiceRuntime(root)
        self.voice.gemini = GeminiSTT(Transport)
        self.server = make_server(database, port=0, project_root=root, voice_service=self.voice, legacy_stt=True)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.origin = f'http://127.0.0.1:{self.server.server_port}'

    def request(self, method, path, body=None, headers=None):
        client=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        self.addCleanup(client.close)
        supplied={'Content-Type':'application/json','Origin':self.origin,**(headers or {})}
        raw=body if isinstance(body,bytes) else json.dumps(body).encode() if body is not None else None
        client.request(method,path,raw,supplied)
        response=client.getresponse()
        return response.status,json.loads(response.read())

    def test_key_setup_requires_same_origin_session_token_and_never_returns_key(self):
        status, session = self.request('GET','/api/voice/gemini/session')
        self.assertEqual(status,200)
        self.assertEqual(self.request('POST','/api/voice/gemini/configure',CONFIG)[0],403)
        self.assertEqual(self.request('POST','/api/voice/gemini/configure',CONFIG,
            {'X-Gemini-Token':session['csrf_token'],'Origin':'https://untrusted.example'})[0],403)
        status,value = self.request('POST','/api/voice/gemini/configure',CONFIG,{'X-Gemini-Token':session['csrf_token']})
        self.assertEqual(status,200)
        self.assertNotIn(KEY,json.dumps(value))
        self.assertTrue(value['ready'])
        status,value = self.request('POST','/api/voice/gemini/clear',{}, {'X-Gemini-Token':session['csrf_token']})
        self.assertEqual(status,200)
        self.assertFalse(value['configured'])

    def test_cloud_audio_endpoint_rejects_missing_consent_and_preserves_provider_lineage(self):
        _, session = self.request('GET','/api/voice/gemini/session')
        token={'X-Gemini-Token':session['csrf_token']}
        self.request('POST','/api/voice/gemini/configure',CONFIG,token)
        stream=io.BytesIO()
        with wave.open(stream,'wb') as wav:
            wav.setparams((1,2,16000,0,'NONE','not compressed'))
            wav.writeframes(b'\x10\0'*16000)
        raw=stream.getvalue()
        headers={**token,'Content-Type':'audio/wav','X-STT-Provider':'gemini'}
        with patch.object(self.voice,'transcribe') as whisper:
            self.assertEqual(self.request('POST','/api/voice/transcribe',raw,headers)[0],400)
            status,result=self.request('POST','/api/voice/transcribe',raw,
                {**headers,'X-Gemini-Audio-Consent':'send-this-audio'})
        whisper.assert_not_called()
        self.assertEqual(status,200)
        self.assertEqual(result['provider'],'google_gemini')
        self.assertEqual(self.voice.transcription_lineage(result['id'],result['text'])['kind'],'raw_stt')

    def test_live_endpoint_uses_exact_model_input_caption_and_raw_lineage(self):
        from gemini_live_transport import LIVE_MODEL
        class Live(Transport):
            def transcribe(self, wav, **kwargs):
                return dict(text='Монгол асуулт', model=LIVE_MODEL,
                    transcript_source='serverContent.inputTranscription',
                    translated_output_used=False, input_transcription_finished=True)
        self.voice.gemini._live_factory = Live
        _, session = self.request('GET','/api/voice/gemini/session')
        token={'X-Gemini-Token':session['csrf_token']}
        self.request('POST','/api/voice/gemini/configure',CONFIG,token)
        from test_gemini_live import wav_bytes
        headers={**token, 'Content-Type':'audio/wav','X-STT-Provider':'gemini_live'}
        with patch.object(self.voice, 'transcribe') as whisper, patch.object(self.voice.gemini, '_factory') as transcribe:
            self.assertEqual(self.request('POST','/api/voice/transcribe',wav_bytes(),headers)[0],400)
            status, result = self.request('POST','/api/voice/transcribe',wav_bytes(),
                {**headers, 'X-Gemini-Audio-Consent':'send-this-audio'})
        whisper.assert_not_called()
        transcribe.assert_not_called()
        self.assertEqual(status,200)
        self.assertEqual(result['model'],LIVE_MODEL)
        self.assertEqual(result['text'],'Монгол асуулт')
        self.assertFalse(result['translated_output_used'])
        self.assertFalse(result['reference_confirmed'])
        self.assertEqual(self.voice.transcription_lineage(result['id'],result['text'])['kind'],'raw_stt')

    def test_main_has_only_live_and_default_request_never_routes_to_whisper(self):
        from gemini_live_transport import LIVE_MODEL
        from test_gemini_live import wav_bytes
        class Live(Transport):
            def transcribe(self,*args,**kwargs):
                return dict(text='Зохиомол Монгол асуулт',model=LIVE_MODEL)
        self.voice.gemini._live_factory=Live
        root=Path(self.temp.name)
        self.server=make_server(root/'content.db',port=0,project_root=root,voice_service=self.voice)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.origin=f'http://127.0.0.1:{self.server.server_port}'
        _,session=self.request('GET','/api/voice/gemini/session')
        token={'X-Gemini-Token':session['csrf_token']}
        self.request('POST','/api/voice/gemini/configure',CONFIG,token)
        headers={**token,'Content-Type':'audio/wav','X-Gemini-Audio-Consent':'send-this-audio'}
        with patch.object(self.voice,'transcribe') as whisper, patch.object(self.voice.gemini,'_factory') as transcribe:
            for rejected in ['cafet','gemini']:
                self.assertEqual(self.request('POST','/api/voice/transcribe',wav_bytes(),
                    {**headers,'X-STT-Provider':rejected})[0],400)
            status,result=self.request('POST','/api/voice/transcribe',wav_bytes(),headers)
        self.assertEqual(status,200)
        self.assertEqual(result['model'],LIVE_MODEL)
        whisper.assert_not_called();transcribe.assert_not_called()
