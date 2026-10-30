"""One bounded recorded clip over Gemini Live; retain input transcription only.

Protocol: https://ai.google.dev/gemini-api/docs/live-api/live-translate
Wire layout follows googleapis/python-genai/_live_converters.py (input
transcription belongs to setup, translationConfig to generationConfig).
No retries, session resumption, file uploads, text prompts or answer generation.
"""
import base64
import hashlib
import io
import json
import threading
import time
import wave

from tools.compare_stt_candidate import CandidateError

LIVE_MODEL = 'gemini-3.5-live-translate-preview'
LIVE_URL = ('wss://generativelanguage.googleapis.com/ws/'
            'google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent')
MAX_MESSAGE = 1024 * 1024
MAX_TOTAL = 16 * MAX_MESSAGE
TAIL_SECONDS = 15
QUIET_SECONDS = 3
UNFINISHED_QUIET_SECONDS = 8


def connect_live(key):
    from websockets.sync.client import connect
    # Same header authentication used by the official Python SDK. The key is
    # absent from URLs, returned diagnostics and filesystem records.
    return connect(LIVE_URL, additional_headers={'x-goog-api-key': key},
                   proxy=None, open_timeout=10, close_timeout=2,
                   max_size=MAX_MESSAGE, max_queue=16, compression=None)


def setup_message():
    return {'setup': {'model': 'models/' + LIVE_MODEL,
        'inputAudioTranscription': {'languageCodes': ['mn-MN']},
        'generationConfig': {'responseModalities': ['AUDIO'],
            'translationConfig': {'targetLanguageCode': 'en', 'echoTargetLanguage': False}}}}


LIVE_CONFIG_SHA256 = hashlib.sha256(json.dumps(setup_message(),sort_keys=True).encode()).hexdigest()


class InputTranscript:
    """Input chunks are deltas; interim hypotheses and output text are excluded."""
    def __init__(self):
        self.chunks = []
        self.languages = set()
        self.finished = False
        self.usage = None
        self.messages = 0
        self.byte_count = 0
        self.digest = hashlib.sha256()

    def accept(self, raw):
        if not isinstance(raw, (str, bytes)):
            raise CandidateError('live_invalid_message')
        raw = raw.encode('utf-8') if isinstance(raw, str) else raw
        self.messages += 1
        self.byte_count += len(raw)
        if len(raw) > MAX_MESSAGE or self.byte_count > MAX_TOTAL or self.messages > 2000:
            raise CandidateError('live_response_limit')
        self.digest.update(raw)
        try:
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError()
            if 'error' in value:
                code = value['error'].get('code') if isinstance(value['error'], dict) else None
                raise CandidateError('http_' + str(code) if code in {401, 403, 429} else 'live_provider_error')
            if 'goAway' in value:
                raise CandidateError('live_disconnected')
            content = value.get('serverContent', {})
            if not isinstance(content, dict):
                raise ValueError()
            caption = content.get('inputTranscription')
            changed = caption is not None
            if changed:
                if not isinstance(caption, dict):
                    raise ValueError()
                text = caption.get('text', '')
                if not isinstance(text, str) or len(self.text) + len(text) > 2000:
                    raise ValueError()
                self.chunks.append(text)
                self.finished = caption.get('finished') is True
                language = caption.get('languageCode')
                if isinstance(language, str) and len(language) <= 32:
                    self.languages.add(language)
            if isinstance(value.get('usageMetadata'), dict):
                # No raw provider object (or arbitrary text) in public metadata.
                self.usage = {k: v for k, v in value['usageMetadata'].items()
                              if k.endswith('TokenCount') and type(v) is int and v >= 0}
            return value, changed
        except (ValueError, TypeError, UnicodeError):
            raise CandidateError('live_invalid_message') from None

    @property
    def text(self):
        return ''.join(self.chunks)


class GeminiLiveTransport:
    def __init__(self, key, *, connector=connect_live, clock=time.monotonic):
        self.key, self.connector, self.clock = key, connector, clock

    def transcribe(self, wav, **_):
        # Validate before opening a cloud connection.
        try:
            with wave.open(io.BytesIO(wav), 'rb') as stream:
                if (stream.getnchannels(), stream.getsampwidth(), stream.getframerate(),
                        stream.getcomptype()) != (1, 2, 16000, 'NONE'):
                    raise ValueError()
                frames = stream.getnframes()
                if not 0 < frames <= 30 * 16000:
                    raise ValueError()
                pcm = stream.readframes(frames)
                if len(pcm) != frames * 2:
                    raise ValueError()
        except (ValueError, wave.Error, EOFError):
            raise CandidateError('live_audio_format') from None
        collector = InputTranscript()
        try:
            with self.connector(self.key) as socket:
                socket.send(json.dumps(setup_message()))
                setup_deadline = self.clock() + 10
                while True:
                    remaining = setup_deadline - self.clock()
                    if remaining <= 0:
                        raise CandidateError('live_setup_timeout')
                    message, _ = collector.accept(socket.recv(timeout=remaining))
                    if 'setupComplete' in message:
                        break
                self._stream(socket, pcm, collector)
            return dict(text=collector.text, model=LIVE_MODEL, mode='input_transcription',
                transcript_source='serverContent.inputTranscription',
                detected_language_codes=sorted(collector.languages),
                input_transcription_finished=collector.finished,
                completion_reason='audio_stream_end_and_quiet_window',
                whole_clip_finality_guaranteed=False, user_review_required=True,
                model_verification='requested_model_setup_acknowledged',
                request_config_sha256=LIVE_CONFIG_SHA256,
                target_language_code='en', echo_target_language=False,
                translated_output_used=False, websocket_closed=True,
                cleanup={'files_api_used': False, 'websocket_closed': True},
                usage=collector.usage, response_sha256=collector.digest.hexdigest())
        except CandidateError:
            raise
        except TimeoutError:
            raise CandidateError('live_timeout') from None
        except Exception as error:
            # Never include close reason, URL, headers or provider error text.
            status = getattr(getattr(error, 'response', None), 'status_code', None)
            close = getattr(getattr(error, 'rcvd', None), 'code', None)
            code = ('http_' + str(status) if status in {401, 403, 429} else
                    'http_429' if close == 1013 else 'live_connection_failed')
            raise CandidateError(code) from None

    def _stream(self, socket, pcm, collector):
        stopped, sent = threading.Event(), threading.Event()
        sender_errors = []
        end_time = []

        def send_audio():
            try:
                # 100 ms PCM16 LE at 16 kHz, paced in real time, full duplex.
                start = self.clock()
                for offset in range(0, len(pcm), 3200):
                    if stopped.wait(max(0, start + offset / 32000 - self.clock())):
                        return
                    socket.send(json.dumps({'realtimeInput': {'audio': {
                        'mimeType': 'audio/pcm;rate=16000',
                        'data': base64.b64encode(pcm[offset:offset+3200]).decode('ascii')}}}))
                if stopped.wait(max(0, start + len(pcm) / 32000 - self.clock())):
                    return
                socket.send(json.dumps({'realtimeInput': {'audioStreamEnd': True}}))
                end_time.append(self.clock())
            except Exception:
                sender_errors.append(True)
            finally:
                sent.set()

        sender = threading.Thread(target=send_audio, daemon=True)
        sender.start()
        last_caption = self.clock()
        deadline = self.clock() + len(pcm) / 32000 + TAIL_SECONDS + 2
        try:
            while self.clock() < deadline:
                if sender_errors:
                    raise CandidateError('live_send_failed')
                now = self.clock()
                settle = QUIET_SECONDS if collector.finished else UNFINISHED_QUIET_SECONDS
                if (sent.is_set() and end_time and collector.text.strip()
                        and now - max(end_time[0], last_caption) >= settle):
                    return
                try:
                    raw = socket.recv(timeout=min(.25, max(.001, deadline - now)))
                except TimeoutError:
                    continue
                _, changed = collector.accept(raw)
                if changed:
                    last_caption = self.clock()
            raise CandidateError('live_incomplete' if collector.text.strip() else 'live_no_transcript')
        finally:
            stopped.set()
            socket.close()
            sender.join(timeout=3)
            if sender.is_alive():
                raise CandidateError('live_send_timeout')
