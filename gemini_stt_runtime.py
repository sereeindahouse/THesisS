"""Gemini STT session with optional Windows-protected credentials and no fallback."""
from collections import OrderedDict
import hashlib
import threading
import time
import uuid

from tools.compare_stt_candidate import CandidateError, GeminiTransport, MODEL
from gemini_live_transport import GeminiLiveTransport, LIVE_MODEL, LIVE_CONFIG_SHA256


class GeminiSTTError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


class GeminiSTT:
    def __init__(self, transport_factory=GeminiTransport, live_transport_factory=GeminiLiveTransport,
                 *, credential_store=None, clock=time.time):
        self._factory = transport_factory
        self._live_factory = live_transport_factory
        self._lock = threading.Lock()
        self._key = None
        self._remaining = 0
        self._attempts = 0
        self._last_error = None
        self._store, self._clock = credential_store, clock
        self._continuous, self._persisted = False, False
        self._cooldown_until = 0
        self._cache, self._cache_hits = OrderedDict(), 0
        self._credential_error = None
        if self._store is not None:
            try:
                saved = self._store.load()
                if saved:
                    self._validate_key(saved['api_key'])
                    self._key, self._continuous, self._persisted = saved['api_key'], True, True
            except Exception:
                self._credential_error = 'credential_restore_failed'

    @staticmethod
    def _validate_key(key):
        if (not isinstance(key, str) or not 20 <= len(key) <= 300
                or not key.isascii() or any(c.isspace() for c in key)):
            raise GeminiSTTError('gemini_config', 'Gemini түлхүүрийн хэлбэр буруу байна.')

    def status(self):
        cooldown = max(0, int(self._cooldown_until - self._clock() + .999))
        return dict(model=LIVE_MODEL, available_models=[LIVE_MODEL], configured=self._key is not None,
            ready=self._key is not None and (self._continuous or self._remaining > 0)
                and cooldown == 0 and self._last_error not in {'http_401', 'http_403'},
            remaining_attempts=None if self._continuous else self._remaining, attempted=self._attempts,
            last_error=self._last_error, key_persisted=self._persisted, automatic_retry=False,
            continuous_use=self._continuous, retry_after_seconds=cooldown,
            credential_error=self._credential_error, cache_hits=self._cache_hits,
            paid_fallback=False, account_tier_independently_verified=False,
            session_scope='user_confirmed_free_tier', language='mn-MN', mode='input_transcription')

    def configure(self, body):
        required = {'api_key', 'free_tier_confirmed', 'data_terms_confirmed', 'max_attempts'}
        if not isinstance(body, dict) or not required <= set(body) or set(body) - required - {'remember', 'continuous_use'}:
            raise GeminiSTTError('gemini_config', 'Түлхүүр, Free tier болон өгөгдлийн нөхцөлийг батална уу.')
        key = body['api_key']
        self._validate_key(key)
        # A page left open before the upgrade sends the original four fields.
        # It must not silently erase the protected key or restore the old cap.
        implicit_regular = self._store is not None and 'continuous_use' not in body
        continuous = body.get('continuous_use', self._store is not None)
        remember = body.get('remember', self._store is not None)
        attempts = body['max_attempts']
        if (body['free_tier_confirmed'] is not True or body['data_terms_confirmed'] is not True
                or type(continuous) is not bool or type(remember) is not bool
                or type(attempts) is not int
                or not (0 <= attempts <= 5 if implicit_regular else attempts == 0 if continuous else 1 <= attempts <= 5)
                or remember and (not continuous or self._store is None)):
            raise GeminiSTTError('gemini_config', 'Free tier, өгөгдлийн нөхцөл болон Gemini тохиргоог шалгана уу.')
        if not self._lock.acquire(blocking=False):
            raise GeminiSTTError('gemini_busy', 'Өмнөх Gemini хүсэлт дуусаагүй байна.')
        try:
            try:
                if remember:
                    self._store.save(dict(api_key=key, free_tier_confirmed=True,
                        data_terms_confirmed=True, continuous_use=True))
                elif self._store is not None:
                    self._store.clear()
            except Exception:
                raise GeminiSTTError('credential_save_failed', 'Windows хамгаалалттай хадгалалтыг нээж чадсангүй.') from None
            self._key, self._remaining, self._attempts, self._last_error = key, 0 if continuous else attempts, 0, None
            self._continuous, self._persisted, self._credential_error = continuous, remember, None
            self._cooldown_until = 0
            self._cache.clear()
            return self.status()
        finally:
            self._lock.release()

    def clear(self):
        if not self._lock.acquire(blocking=False):
            raise GeminiSTTError('gemini_busy', 'Өмнөх Gemini хүсэлт дууссаны дараа түлхүүрийг мартана.')
        try:
            if self._store is not None:
                try:
                    self._store.clear()
                except Exception:
                    raise GeminiSTTError('credential_clear_failed', 'Хадгалсан түлхүүрийг арилгаж чадсангүй.') from None
            self._key, self._remaining, self._last_error = None, 0, None
            self._continuous, self._persisted = False, False
            self._cache.clear()
            return self.status()
        finally:
            self._lock.release()

    def transcribe(self, wav, *, consent, live=False):
        if consent is not True:
            raise GeminiSTTError('gemini_consent', 'Энэ бичлэгийг Google руу илгээх чагтыг сонгоно уу.')
        if not self._lock.acquire(blocking=False):
            raise GeminiSTTError('gemini_busy', 'Өмнөх Gemini хүсэлт дуусаагүй; давхар илгээхгүй.')
        try:
            expected_model = LIVE_MODEL if live else MODEL
            cache_key = (expected_model, LIVE_CONFIG_SHA256 if live else 'verbatim-mn-MN', hashlib.sha256(wav).digest())
            cached = self._cache.get(cache_key)
            if self._continuous and self._key and cached and self._clock() - cached[0] < 1800:
                self._cache.move_to_end(cache_key)
                self._cache_hits += 1
                return dict(cached[1], cache_hit=True, provider_call_performed=False,
                    source_transcription_seconds=cached[1]['transcription_seconds'], transcription_seconds=0)
            if not self.status()['ready']:
                raise GeminiSTTError('gemini_not_ready', 'Gemini тохиргоо, Free tier квот эсвэл оролдлогын хүрээг шалгана уу.')
            if not self._continuous:
                self._remaining -= 1
            self._attempts += 1
            started = time.perf_counter()
            try:
                factory = self._live_factory if live else self._factory
                result = factory(self._key).transcribe(wav, display_name='clip-' + uuid.uuid4().hex)
            except CandidateError as error:
                self._last_error = error.code
                if error.code == 'http_429':
                    self._cooldown_until = self._clock() + 60
                message = ('Gemini-ийн үнэгүй квот хүрсэн (429). Автоматаар давтахгүй, төлбөртэй горимд шилжихгүй.'
                           if error.code == 'http_429' else
                           'Gemini танилт амжилтгүй (' + error.code + '). Түлхүүр/сүлжээ/үйлчилгээний нөхцөлийг шалгана уу.')
                raise GeminiSTTError(error.code, message) from None
            except Exception:
                self._last_error = 'provider_failed'
                raise GeminiSTTError('provider_failed', 'Gemini танилт амжилтгүй. Нууц мэдээлэлтэй алдааны эхийг харуулахгүй.') from None
            if (result.get('model') != expected_model or not isinstance(result.get('text'), str)
                    or len(result['text']) > 2000):
                self._last_error = 'invalid_transcript'
                raise GeminiSTTError('invalid_transcript', 'Gemini-ийн model эсвэл текстийн хүрээ зөрсөн байна.')
            details = {key: result[key] for key in (
                'transcript_source', 'detected_language_codes', 'input_transcription_finished',
                'completion_reason', 'whole_clip_finality_guaranteed', 'model_verification',
                'target_language_code', 'echo_target_language', 'translated_output_used',
                'websocket_closed', 'request_config_sha256') if key in result} if live else {}
            self._last_error = None
            answer = dict(text=result['text'], model=expected_model, usage=result.get('usage'),
                cleanup=result.get('cleanup'), response_sha256=result.get('response_sha256'),
                transcription_seconds=time.perf_counter()-started,
                provider='google_gemini_live' if live else 'google_gemini',
                mode='input_transcription' if live else 'verbatim', automatic_retry=False,
                account_tier_independently_verified=False, actual_billed_cost_usd=None,
                cache_hit=False, provider_call_performed=True, **details)
            if self._continuous:
                self._cache[cache_key] = (self._clock(), answer)
            while len(self._cache) > 16:
                self._cache.popitem(last=False)
            return answer
        finally:
            self._lock.release()
