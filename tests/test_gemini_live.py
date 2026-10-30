"""Synthetic full-duplex Live contracts; no cloud credentials or human audio."""
import base64
import io
import json
import queue
import time
import unittest
import wave
from unittest.mock import patch

from gemini_live_transport import (
    GeminiLiveTransport, InputTranscript, LIVE_MODEL, LIVE_URL, connect_live,
)
from gemini_stt_runtime import GeminiSTT, GeminiSTTError
from tools.compare_stt_candidate import CandidateError, MODEL


def wav_bytes(rate=16000, seconds=.01):
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as wav:
        wav.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
        wav.writeframes(b'\x10\0' * int(rate * seconds))
    return stream.getvalue()


class Socket:
    def __init__(self, *, error=None, missing=False, close_early=False):
        self.sent, self.incoming = [], queue.Queue()
        self.error, self.missing, self.close_early = error, missing, close_early
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def send(self, raw):
        value = json.loads(raw)
        self.sent.append(value)
        if 'setup' in value:
            self.incoming.put({'error': {'code': self.error, 'message': 'secret'}} if self.error
                              else {'setupComplete': {}})
        elif value['realtimeInput'].get('audioStreamEnd'):
            if not self.missing:
                self.incoming.put({'serverContent': {'interimInputTranscription': {'text': 'ignore hypothesis'},
                    'outputTranscription': {'text': 'ignore English'},
                    'inputTranscription': {'text': 'Монгол ', 'languageCode': 'mn'}}})
                # A later message after end-of-audio must also be collected.
                self.incoming.put({'serverContent': {'inputTranscription': {'text': 'асуулт', 'finished': True}}})

    def recv(self, timeout):
        if self.close_early and len(self.sent) > 1:
            raise RuntimeError('secret URL and key')
        try:
            return json.dumps(self.incoming.get(timeout=min(timeout, .01)))
        except queue.Empty:
            raise TimeoutError() from None

    def close(self):
        self.closed = True


class LiveTransportTests(unittest.TestCase):
    def test_official_setup_fixed_model_header_auth_and_no_proxy(self):
        with patch('websockets.sync.client.connect') as connect:
            connect_live('fixture-secret')
        args, kwargs = connect.call_args
        self.assertEqual(args, (LIVE_URL,))
        self.assertNotIn('fixture-secret', args[0])
        self.assertEqual(kwargs['additional_headers'], {'x-goog-api-key': 'fixture-secret'})
        self.assertIsNone(kwargs['proxy'])

    def test_stream_collects_only_input_deltas_and_preserves_final_tail_and_pcm(self):
        socket = Socket()
        with patch('gemini_live_transport.QUIET_SECONDS', .03):
            result = GeminiLiveTransport('fixture', connector=lambda _: socket).transcribe(wav_bytes())
        self.assertEqual(result['model'], LIVE_MODEL)
        self.assertEqual(result['text'], 'Монгол асуулт')
        self.assertTrue(result['input_transcription_finished'])
        self.assertFalse(result['whole_clip_finality_guaranteed'])
        self.assertEqual(result['detected_language_codes'], ['mn'])
        self.assertFalse(result['translated_output_used'])
        setup = socket.sent[0]['setup']
        self.assertEqual(setup['model'], 'models/' + LIVE_MODEL)
        self.assertEqual(setup['inputAudioTranscription'], {'languageCodes': ['mn-MN']})
        self.assertNotIn('inputAudioTranscription', setup['generationConfig'])
        self.assertEqual(setup['generationConfig']['translationConfig'],
                         dict(targetLanguageCode='en', echoTargetLanguage=False))
        self.assertTrue(socket.sent[-1]['realtimeInput']['audioStreamEnd'])
        pcm = b''.join(base64.b64decode(m['realtimeInput']['audio']['data'])
                       for m in socket.sent if 'audio' in m.get('realtimeInput', {}))
        self.assertEqual(pcm, b'\x10\0' * 160)
        self.assertTrue(socket.closed)
        self.assertEqual(result['transcript_source'], 'serverContent.inputTranscription')

    def test_invalid_wav_cannot_open_connection(self):
        for wav in [b'bad', wav_bytes(8000), wav_bytes(seconds=30.01)]:
            with self.subTest(size=len(wav)), patch('gemini_live_transport.connect_live') as connect:
                with self.assertRaises(CandidateError):
                    GeminiLiveTransport('fixture', connector=connect).transcribe(wav)
                connect.assert_not_called()

    def test_setup_429_never_sends_audio_and_closes_without_retry(self):
        socket = Socket(error=429)
        with self.assertRaises(CandidateError) as error:
            GeminiLiveTransport('fixture', connector=lambda _: socket).transcribe(wav_bytes())
        self.assertEqual(error.exception.code, 'http_429')
        self.assertEqual(len(socket.sent), 1)
        self.assertTrue(socket.closed)

    def test_dropped_connection_never_returns_partial_success_or_secret(self):
        socket = Socket(close_early=True)
        with self.assertRaises(CandidateError) as error:
            GeminiLiveTransport('fixture', connector=lambda _: socket).transcribe(wav_bytes())
        self.assertEqual(error.exception.code, 'live_connection_failed')
        self.assertNotIn('secret', str(error.exception))
        self.assertTrue(socket.closed)

    def test_no_caption_has_bounded_timeout_instead_of_translation_as_transcript(self):
        socket = Socket(missing=True)
        socket.incoming.put({'serverContent': {'outputTranscription': {'text': 'English only'}}})
        # Shorten the whole post-stream receive deadline for a synthetic failure.
        with patch('gemini_live_transport.TAIL_SECONDS', -1.9):
            start = time.monotonic()
            with self.assertRaises(CandidateError) as error:
                GeminiLiveTransport('fixture', connector=lambda _: socket).transcribe(wav_bytes())
        self.assertEqual(error.exception.code, 'live_no_transcript')
        self.assertLess(time.monotonic() - start, 1)

    def test_interim_revisions_are_not_appended_or_claimed_final(self):
        collector = InputTranscript()
        collector.accept(json.dumps({'serverContent': {'interimInputTranscription': {'text': 'wrong'}}}))
        collector.accept(json.dumps({'serverContent': {'inputTranscription': {'text': 'зөв'}}}))
        self.assertEqual(collector.text, 'зөв')
        self.assertFalse(collector.finished)

    def test_captured_caption_without_finished_signal_remains_explicitly_unfinalized(self):
        class Unfinalized(Socket):
            def send(self, raw):
                super().send(raw)
                if json.loads(raw).get('realtimeInput', {}).get('audioStreamEnd'):
                    self.incoming.get_nowait()
                    self.incoming.get_nowait()
                    self.incoming.put({'serverContent': {'inputTranscription': {'text': 'дуусаагүй'}}})
        socket = Unfinalized()
        with patch('gemini_live_transport.UNFINISHED_QUIET_SECONDS', .03):
            result = GeminiLiveTransport('fixture', connector=lambda _: socket).transcribe(wav_bytes())
        self.assertEqual(result['text'], 'дуусаагүй')
        self.assertFalse(result['input_transcription_finished'])
        self.assertFalse(result['whole_clip_finality_guaranteed'])
        self.assertTrue(result['user_review_required'])

    def test_utterance_end_does_not_prevent_following_utterance(self):
        collector = InputTranscript()
        for text, finished in [('нэг. ', True), ('хоёр', False), (' дуусав.', True)]:
            collector.accept(json.dumps({'serverContent': {'inputTranscription': {'text': text, 'finished': finished}}}))
        self.assertEqual(collector.text, 'нэг. хоёр дуусав.')
        self.assertTrue(collector.finished)

    def test_response_size_schema_and_text_limits_fail_closed(self):
        for raw in ['[]', 'bad json', json.dumps({'serverContent': {'inputTranscription': {'text': 2}}}),
                    json.dumps({'serverContent': {'inputTranscription': {'text': 'x' * 2001}}}),
                    'x' * (1024 * 1024 + 1)]:
            with self.subTest(length=len(raw)), self.assertRaises(CandidateError):
                InputTranscript().accept(raw)

    def test_live_and_transcribe_share_budget_and_never_fallback(self):
        calls = []
        class FakeLive:
            def __init__(self, _):
                pass
            def transcribe(self, *_a, **_k):
                calls.append('live')
                return dict(text='Монгол', model=LIVE_MODEL, translated_output_used=False)
        class FakeTranscribe(FakeLive):
            def transcribe(self, *_a, **_k):
                calls.append('transcribe')
                return dict(text='fixture', model=MODEL)
        cloud = GeminiSTT(FakeTranscribe, FakeLive)
        cloud.configure(dict(api_key='fixture-secret-000000000000', free_tier_confirmed=True,
                             data_terms_confirmed=True, max_attempts=2))
        with self.assertRaises(GeminiSTTError):
            cloud.transcribe(b'', consent=False, live=True)
        self.assertEqual(calls, [])
        result = cloud.transcribe(b'', consent=True, live=True)
        self.assertEqual(result['provider'], 'google_gemini_live')
        self.assertEqual(result['model'], LIVE_MODEL)
        self.assertEqual(result['mode'], 'input_transcription')
        cloud.transcribe(b'', consent=True)
        with self.assertRaises(GeminiSTTError):
            cloud.transcribe(b'', consent=True, live=True)
        self.assertEqual(calls, ['live', 'transcribe'])

    def test_wrong_model_is_rejected_instead_of_relabelled_live(self):
        class Wrong:
            def __init__(self, _):
                pass
            def transcribe(self, *_a, **_k):
                return dict(text='wrong model output', model=MODEL)
        cloud = GeminiSTT(live_transport_factory=Wrong)
        cloud.configure(dict(api_key='fixture-secret-000000000000', free_tier_confirmed=True,
                             data_terms_confirmed=True, max_attempts=1))
        with self.assertRaisesRegex(GeminiSTTError, 'model'):
            cloud.transcribe(b'', consent=True, live=True)
