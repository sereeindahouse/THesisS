"""User-operated, bounded Gemini STT session. Keys exist in memory only."""
import threading
import time
import uuid

from tools.compare_stt_candidate import CandidateError, GeminiTransport, MODEL


class GeminiSTTError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


class GeminiSTT:
    def __init__(self, transport_factory=GeminiTransport):
        self._factory = transport_factory
        self._lock = threading.Lock()
        self._key = None
        self._remaining = 0
        self._attempts = 0
        self._last_error = None

    def status(self):
        return dict(model=MODEL, configured=self._key is not None,
            ready=self._key is not None and self._remaining > 0 and self._last_error != 'http_429',
            remaining_attempts=self._remaining, attempted=self._attempts,
            last_error=self._last_error, key_persisted=False, automatic_retry=False,
            paid_fallback=False, account_tier_independently_verified=False,
            session_scope='user_confirmed_free_tier', language='mn-MN', mode='verbatim')

    def configure(self, body):
        if not isinstance(body, dict) or set(body) != {'api_key', 'free_tier_confirmed', 'data_terms_confirmed', 'max_attempts'}:
            raise GeminiSTTError('gemini_config', 'Түлхүүр, Free tier болон өгөгдлийн нөхцөлийг батална уу.')
        key = body['api_key']
        if (not isinstance(key, str) or not 20 <= len(key) <= 300
                or not key.isascii() or any(c.isspace() for c in key)
                or body['free_tier_confirmed'] is not True or body['data_terms_confirmed'] is not True
                or type(body['max_attempts']) is not int or not 1 <= body['max_attempts'] <= 5):
            raise GeminiSTTError('gemini_config', 'Free tier, өгөгдлийн нөхцөл ба 1–5 оролдлогын хүрээг батална уу.')
        if not self._lock.acquire(blocking=False):
            raise GeminiSTTError('gemini_busy', 'Өмнөх Gemini хүсэлт дуусаагүй байна.')
        try:
            self._key, self._remaining, self._attempts, self._last_error = key, body['max_attempts'], 0, None
            return self.status()
        finally:
            self._lock.release()

    def clear(self):
        if not self._lock.acquire(blocking=False):
            raise GeminiSTTError('gemini_busy', 'Өмнөх Gemini хүсэлт дууссаны дараа түлхүүрийг мартана.')
        try:
            self._key, self._remaining, self._last_error = None, 0, None
            return self.status()
        finally:
            self._lock.release()

    def transcribe(self, wav, *, consent):
        if consent is not True:
            raise GeminiSTTError('gemini_consent', 'Энэ бичлэгийг Google руу илгээх чагтыг сонгоно уу.')
        if not self._lock.acquire(blocking=False):
            raise GeminiSTTError('gemini_busy', 'Өмнөх Gemini хүсэлт дуусаагүй; давхар илгээхгүй.')
        try:
            if not self.status()['ready']:
                raise GeminiSTTError('gemini_not_ready', 'Gemini тохиргоо, Free tier квот эсвэл оролдлогын хүрээг шалгана уу.')
            self._remaining -= 1
            self._attempts += 1
            started = time.perf_counter()
            try:
                result = self._factory(self._key).transcribe(wav, display_name='clip-' + uuid.uuid4().hex)
            except CandidateError as error:
                self._last_error = error.code
                message = ('Gemini-ийн үнэгүй квот хүрсэн (429). Автоматаар давтахгүй, төлбөртэй горимд шилжихгүй.'
                           if error.code == 'http_429' else
                           'Gemini танилт амжилтгүй (' + error.code + '). Түлхүүр/сүлжээ/үйлчилгээний нөхцөлийг шалгана уу.')
                raise GeminiSTTError(error.code, message) from None
            except Exception:
                self._last_error = 'provider_failed'
                raise GeminiSTTError('provider_failed', 'Gemini танилт амжилтгүй. Нууц мэдээлэлтэй алдааны эхийг харуулахгүй.') from None
            if (result.get('model') != MODEL or not isinstance(result.get('text'), str)
                    or len(result['text']) > 2000):
                self._last_error = 'invalid_transcript'
                raise GeminiSTTError('invalid_transcript', 'Gemini-ийн model эсвэл текстийн хүрээ зөрсөн байна.')
            return dict(text=result['text'], model=MODEL, usage=result.get('usage'),
                cleanup=result.get('cleanup'), response_sha256=result.get('response_sha256'),
                transcription_seconds=time.perf_counter()-started,
                provider='google_gemini', mode='verbatim', automatic_retry=False,
                account_tier_independently_verified=False, actual_billed_cost_usd=None)
        finally:
            self._lock.release()
