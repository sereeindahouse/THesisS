"""Bounded local STT and explicitly requested online speech for the localhost demo.

The module imports with the standard library alone. Runtime libraries are loaded
only after a user supplies audio or asks for speech. Uploaded audio/transcripts
stay in the ignored runtime directory and never become training references.
"""
import asyncio
import hashlib
import importlib.util
import importlib.metadata
import io
import json
import re
import threading
import time
import uuid
import wave
from datetime import datetime, timezone
from pathlib import Path


MAX_AUDIO_BYTES = 8 * 1024 * 1024
MAX_AUDIO_SECONDS = 30
from answer_contract import MAX_SPEECH_CHARACTERS
MAX_TEXT_CHARACTERS = MAX_SPEECH_CHARACTERS
SAMPLE_RATE = 16000
DECODE_TIMEOUT_SECONDS = 15
TTS_TIMEOUT_SECONDS = 25
MAX_TTS_BYTES = 4 * 1024 * 1024
MAX_SESSION_ITEMS = 40
ALLOWED_VOICES = ("mn-MN-BataaNeural", "mn-MN-YesuiNeural")
PINNED_SOURCE = "Cafet/whisper-small-mongolian"
PINNED_REVISION = "d54c63a518d6dea7ab54a27c83d0b6b52bea3e9d"
PINNED_SHA256 = "7a2a3f0a939addbd2ae9532dfb2b16590ecc3fbb145a214b784b05797e202843"
EXPECTED_DECODING = dict(language="mn", task="transcribe", beam_size=5,
                         vad_filter=False, temperature=0.0,
                         without_timestamps=True,
                         condition_on_previous_text=False)
ONLINE_NOTICE = "Сонгосон текстийг онлайн Edge TTS үйлчилгээнд илгээнэ; дууны файл STT-д локал боловсруулагдана."
_ID = re.compile(r"[0-9a-f]{32}\Z")
_FORMATS = {
    "wav": ("wav", "audio/wav", {"audio/wav", "audio/x-wav", "audio/wave"}),
    "webm": ("matroska", "audio/webm", {"audio/webm", "video/webm"}),
    "ogg": ("ogg", "audio/ogg", {"audio/ogg", "application/ogg"}),
    "mp4": ("mov", "audio/mp4", {"audio/mp4", "video/mp4", "audio/x-m4a"}),
}


class VoiceRuntimeError(ValueError):
    """A bounded, user-facing error safe to report as JSON."""

    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code = code
        self.status = status


def _audio_format(payload, content_type):
    if not isinstance(payload, bytes) or not payload:
        raise VoiceRuntimeError("audio_empty", "Дууны файл хоосон байна.")
    if len(payload) > MAX_AUDIO_BYTES:
        raise VoiceRuntimeError("audio_too_large", "Дууны файл 8 MiB-аас бага байх ёстой.", 413)
    if len(payload) < 12:
        raise VoiceRuntimeError("audio_invalid", "Дууны контейнер дутуу байна.")
    if payload[:4] == b"RIFF" and payload[8:12] == b"WAVE":
        kind = "wav"
    elif payload[:4] == b"\x1a\x45\xdf\xa3":
        kind = "webm"
    elif payload[:4] == b"OggS":
        kind = "ogg"
    elif payload[4:8] == b"ftyp":
        kind = "mp4"
    else:
        raise VoiceRuntimeError("audio_format", "WAV, WebM, Ogg эсвэл MP4 дуу оруулна уу.")
    mime = str(content_type or "application/octet-stream").split(";", 1)[0].strip().lower()
    demuxer, canonical, allowed = _FORMATS[kind]
    if mime not in allowed | {"application/octet-stream"}:
        raise VoiceRuntimeError("audio_type_mismatch", "Дууны MIME төрөл болон контейнер таарахгүй байна.")
    return demuxer, canonical


def _has_module(name):
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError, AttributeError):
        return False


def _decode_pcm(payload, demuxer):
    """Decode incrementally, aborting before inference on excessive duration.

    A forced demuxer prevents a playlist from requesting remote resources.
    Stream metadata is an early check; actual frame and output sample counts
    also apply when browser WebM has no duration metadata.
    """
    try:
        import av
    except ImportError as exc:
        raise VoiceRuntimeError("stt_dependencies", "STT-ийн сангууд суулгагдаагүй байна; requirements.txt-ийг суулгана уу.", 503) from exc
    pcm = bytearray()
    started = time.perf_counter()
    input_seconds = 0.0
    kwargs = {"mode": "r", "format": demuxer}
    if int(av.__version__.split(".", 1)[0]) < 19:
        kwargs["metadata_errors"] = "ignore"
    if demuxer == "mov":
        kwargs["options"] = {"enable_drefs": "0"}
    try:
        with av.open(io.BytesIO(payload), **kwargs) as container:
            streams = list(container.streams.audio)
            if len(streams) != 1:
                raise VoiceRuntimeError("audio_tracks", "Нэг дууны замтай файл оруулна уу.")
            stream = streams[0]
            codec = getattr(stream, "codec_context", None)
            known_rate = getattr(codec, "sample_rate", None)
            known_layout = getattr(codec, "layout", None)
            known_channels = len(known_layout.channels) if known_layout is not None else None
            if (known_rate and not 8000 <= known_rate <= 192000) or (
                    known_channels is not None and not 1 <= known_channels <= 2):
                raise VoiceRuntimeError("audio_parameters", "8–192 kHz, нэг эсвэл хоёр сувгийн дуу шаардлагатай.")
            if stream.duration is not None and stream.time_base is not None:
                if float(stream.duration * stream.time_base) > MAX_AUDIO_SECONDS:
                    raise VoiceRuntimeError("audio_too_long", "Бичлэг 30 секундээс урт байна.")
            resampler = av.audio.resampler.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)

            def append(frame):
                pcm.extend(frame.to_ndarray().tobytes())
                if len(pcm) > MAX_AUDIO_SECONDS * SAMPLE_RATE * 2:
                    raise VoiceRuntimeError("audio_too_long", "Бичлэг 30 секундээс урт байна.")

            for count, frame in enumerate(container.decode(audio=0), 1):
                if time.perf_counter() - started > DECODE_TIMEOUT_SECONDS or count > 15000:
                    raise VoiceRuntimeError("audio_decode_limit", "Дууг тайлах хязгаарт хүрлээ; богино шинэ бичлэг оруулна уу.", 504)
                rate = frame.sample_rate
                channels = len(frame.layout.channels)
                if not rate or not 8000 <= rate <= 192000 or not 1 <= channels <= 2:
                    raise VoiceRuntimeError("audio_parameters", "8–192 kHz, нэг эсвэл хоёр сувгийн дуу шаардлагатай.")
                input_seconds += frame.samples / rate
                if input_seconds > MAX_AUDIO_SECONDS + 1e-7:
                    raise VoiceRuntimeError("audio_too_long", "Бичлэг 30 секундээс урт байна.")
                frame.pts = None
                for output in resampler.resample(frame):
                    append(output)
            for output in resampler.resample(None):
                append(output)
    except VoiceRuntimeError:
        raise
    except Exception as exc:
        raise VoiceRuntimeError("audio_decode_failed", "Дууны файлыг тайлж чадсангүй; WAV эсвэл браузерын шинэ бичлэг ашиглана уу.") from exc
    if not pcm:
        raise VoiceRuntimeError("audio_empty", "Файлд тайлагдах дуу байхгүй байна.")
    return bytes(pcm)


def _waveform(pcm):
    try:
        import numpy as np
    except ImportError as exc:
        raise VoiceRuntimeError("stt_dependencies", "STT-ийн сангууд суулгагдаагүй байна; requirements.txt-ийг суулгана уу.", 503) from exc
    return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0


def _wav_bytes(pcm):
    output = io.BytesIO()
    with wave.open(output, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(pcm)
    return output.getvalue()


async def _edge_audio(text, voice):
    try:
        import edge_tts
    except ImportError as exc:
        raise VoiceRuntimeError("tts_dependencies", "edge-tts сан суулгагдаагүй байна; requirements.txt-ийг суулгана уу.", 503) from exc
    audio = bytearray()
    async for chunk in edge_tts.Communicate(text, voice).stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
            if len(audio) > MAX_TTS_BYTES:
                raise VoiceRuntimeError("tts_size_limit", "TTS дууны хэмжээ хэтэрлээ; богино хариулт сонгоно уу.", 503)
    if not audio:
        raise VoiceRuntimeError("tts_empty", "TTS үйлчилгээ дуу буцаасангүй.", 503)
    return bytes(audio)


class VoiceRuntime:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self._session = self.root / "runtime" / "voice-demo" / uuid.uuid4().hex
        self._model = None
        self._choice = None
        self._model_lock = threading.Lock()
        self._records_lock = threading.RLock()
        self._records = {}
        self._last_tts_attempt = None

    def status(self):
        profile = self.root / "data" / "stt-model-choice.json"
        if not profile.is_file():
            profile = self.root / "config" / "stt-development.json"
        present = False
        try:
            choice = json.loads(profile.read_text(encoding="utf-8"))
            directory = (self.root / choice["development_model_path"]).resolve()
            present = directory.is_relative_to((self.root / "models").resolve()) and all(
                (directory / filename).is_file() for filename in ("model.bin", "config.json", "tokenizer.json", "download-manifest.json"))
        except (OSError, ValueError, KeyError, TypeError):
            pass
        stt_ready = present and all(_has_module(name) for name in ("av", "numpy", "faster_whisper"))
        tts_ready = _has_module("edge_tts")
        try:
            tts_version = importlib.metadata.version("edge-tts")
        except importlib.metadata.PackageNotFoundError:
            tts_version = None
        with self._records_lock:
            last_tts = dict(self._last_tts_attempt) if self._last_tts_attempt else None
        return {"available": stt_ready or tts_ready, "stt_ready": stt_ready,
                "tts_ready": tts_ready, "tts_dependency_ready": tts_ready,
                "tts_package_version": tts_version,
                "tts_ready_checks_dependencies_only": True,
                "tts_last_attempt": last_tts, "model_files_present": present,
                "model_loaded": self._model is not None,
                "model": PINNED_SOURCE, "revision": PINNED_REVISION,
                "model_sha256": PINNED_SHA256, "local_files_only": True,
                "device": "cpu", "compute_type": "int8",
                "model_verified_before_first_transcription": True,
                "maximum_audio_bytes": MAX_AUDIO_BYTES, "maximum_audio_seconds": MAX_AUDIO_SECONDS,
                "maximum_text_characters": MAX_TEXT_CHARACTERS,
                "maximum_session_items": MAX_SESSION_ITEMS,
                "voices": list(ALLOWED_VOICES), "tts_service": "online Edge TTS experiment",
                "online_notice": ONLINE_NOTICE,
                "fine_tuning_performed": False, "production_accepted": False,
                "private_storage": "runtime/voice-demo", "text_generated": False, "llm_calls": 0}

    def _load_model(self):
        if self._model is not None:
            return 0.0
        started = time.perf_counter()
        try:
            from stt_mn import load_choice
            choice, path = load_choice(self.root)
            if (choice.get("source_repo"), choice.get("source_revision"), choice.get("model_sha256")) != (
                    PINNED_SOURCE, PINNED_REVISION, PINNED_SHA256):
                raise VoiceRuntimeError("stt_profile_changed", "Туршиж сонгосон Cafet моделийн хувилбар өөрчлөгдсөн байна.", 503)
            if choice.get("decoding") != EXPECTED_DECODING or choice.get("device") != "cpu" or choice.get("compute_type") != "int8":
                raise VoiceRuntimeError("stt_profile_changed", "Туршиж сонгосон STT тохиргоо өөрчлөгдсөн байна.", 503)
            from faster_whisper import WhisperModel
            model = WhisperModel(str(path), device="cpu", compute_type="int8", local_files_only=True)
        except VoiceRuntimeError:
            raise
        except ImportError as exc:
            raise VoiceRuntimeError("stt_dependencies", "STT-ийн сангууд суулгагдаагүй байна; requirements.txt-ийг суулгана уу.", 503) from exc
        except FileNotFoundError as exc:
            raise VoiceRuntimeError("stt_model_missing", "Локал Cafet модель алга; CORE-ийн model setup зааврыг ашиглана уу.", 503) from exc
        except Exception as exc:
            raise VoiceRuntimeError("stt_model_verification", "Локал моделийн файл, checksum эсвэл runtime тохиргоог баталгаажуулж чадсангүй.", 503) from exc
        self._model = model
        self._choice = dict(choice)
        return time.perf_counter() - started

    def _safe_file(self, path):
        resolved = path.resolve()
        session = self._session.resolve()
        if not session.is_relative_to(self.root) or resolved.parent != session:
            raise VoiceRuntimeError("storage_path", "Demo-ийн хадгалах зам аюулгүй биш байна.", 503)
        return resolved

    def _save(self, audio, mime, details):
        identifier = uuid.uuid4().hex
        with self._records_lock:
            self._check_capacity()
            self._safe_file(self._session / (identifier + ".audio"))
            try:
                self._session.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise VoiceRuntimeError("voice_storage", "Demo-ийн түр хавтсыг үүсгэж чадсангүй.", 503) from exc
            audio_path = self._safe_file(self._session / (identifier + ".audio"))
            info_path = self._safe_file(self._session / (identifier + ".json"))
            result = {"id": identifier, "audio_url": "/api/voice/audio/" + identifier,
                      "created_at": datetime.now(timezone.utc).isoformat(), **details}
            created = []
            try:
                with audio_path.open("xb") as handle:
                    created.append(audio_path)
                    handle.write(audio)
                with info_path.open("x", encoding="utf-8") as handle:
                    created.append(info_path)
                    json.dump(result, handle, ensure_ascii=False, indent=2)
            except Exception as exc:
                for path in created:
                    if path.is_file():
                        self._safe_file(path).unlink()
                raise VoiceRuntimeError("voice_storage", "Demo-ийн түр файлыг хадгалж чадсангүй.", 503) from exc
            self._records[identifier] = (audio_path, info_path, mime)
        return result

    def _check_capacity(self):
        with self._records_lock:
            if len(self._records) >= MAX_SESSION_ITEMS:
                raise VoiceRuntimeError("voice_session_full", "Түр дууны хязгаарт хүрлээ; session-ийг цэвэрлээд үргэлжлүүлнэ үү.", 409)

    def transcribe(self, audio_bytes, content_type):
        self._check_capacity()
        demuxer, _ = _audio_format(audio_bytes, content_type)
        decode_started = time.perf_counter()
        pcm = _decode_pcm(audio_bytes, demuxer)
        if not any(pcm):
            raise VoiceRuntimeError("audio_silent", "Бичлэгийн бүх sample тэг байна; микрофоноо шалгаж, дахин ярьж бичнэ үү.")
        audio = _waveform(pcm)
        decode_seconds = time.perf_counter() - decode_started
        queued = time.perf_counter()
        with self._model_lock:
            queue_seconds = time.perf_counter() - queued
            load_seconds = self._load_model()
            started = time.perf_counter()
            try:
                segments, _ = self._model.transcribe(audio, **dict(EXPECTED_DECODING))
                rows = [{"start": float(segment.start), "end": float(segment.end),
                         "text": segment.text.strip()} for segment in segments]
            except Exception as exc:
                raise VoiceRuntimeError("stt_failed", "STT дууг таньж чадсангүй; текстээ гараар оруулж үргэлжлүүлж болно.", 503) from exc
            elapsed = time.perf_counter() - started
            actual_compute = getattr(getattr(self._model, "model", None), "compute_type", "unknown")
        text = " ".join(row["text"] for row in rows).strip()
        details = {"kind": "stt", "text": text, "segments": rows,
                   "speech_text_available": bool(text),
                   "message": ("STT текст гарлаа; хэлсэн үгтэйгээ нягталж засна уу." if text else
                               "Ярианы текст гарсангүй; өгүүлбэрээ гараар оруулах эсвэл дахин бичиж болно."),
                   "audio_seconds": len(pcm) / (SAMPLE_RATE * 2),
                   "decode_seconds": decode_seconds, "queue_wait_seconds": queue_seconds,
                   "model_load_seconds": load_seconds, "transcription_seconds": elapsed,
                   "input_sha256": hashlib.sha256(audio_bytes).hexdigest(),
                   "model": PINNED_SOURCE, "revision": PINNED_REVISION,
                   "model_sha256": PINNED_SHA256, "decoding": dict(EXPECTED_DECODING),
                   "device": "cpu", "compute_type": "int8", "actual_compute_type": actual_compute,
                   "local_files_only": True, "reference_confirmed": False,
                   "human_review_required": True, "fine_tuning_performed": False,
                   "accuracy_measured": False, "text_generated": False, "llm_calls": 0}
        return self._save(_wav_bytes(pcm), "audio/wav", details)

    def _tts_attempt(self, voice, started, *, success, error=None, service_status=None):
        # No text, URLs, service tokens or raw exception messages in public status.
        with self._records_lock:
            self._last_tts_attempt = {
                "at": datetime.now(timezone.utc).isoformat(), "voice": voice,
                "success": success, "error_code": error,
                "service_http_status": service_status,
                "elapsed_seconds": time.perf_counter() - started,
                "is_current_availability_guarantee": False,
            }

    def synthesize(self, text, voice):
        self._check_capacity()
        if voice not in ALLOWED_VOICES:
            raise VoiceRuntimeError("tts_voice", "Bataa эсвэл Yesui монгол дууг сонгоно уу.")
        if not isinstance(text, str) or not text.strip():
            raise VoiceRuntimeError("tts_text_empty", "Уншуулах текст хоосон байна.")
        text = text.strip()
        if len(text) > MAX_TEXT_CHARACTERS:
            raise VoiceRuntimeError("tts_text_limit", "Уншуулах текст 2000 тэмдэгтээс урт байна.")
        started = time.perf_counter()

        async def limited():
            return await asyncio.wait_for(_edge_audio(text, voice), TTS_TIMEOUT_SECONDS)

        try:
            audio = asyncio.run(limited())
        except VoiceRuntimeError as exc:
            self._tts_attempt(voice, started, success=False, error=exc.code)
            raise
        except TimeoutError as exc:
            self._tts_attempt(voice, started, success=False, error="tts_timeout")
            raise VoiceRuntimeError("tts_timeout", "Дуу унших үйлчилгээ хугацаандаа хариулсангүй. Текстэн хариулт хэвээр; дараа дахин сонсож болно.", 504) from exc
        except Exception as exc:
            status = getattr(exc, "status", None)
            status = status if type(status) is int and 100 <= status <= 599 else None
            if status in (401, 403):
                code = "tts_service_rejected"
                message = "Дуу унших үйлчилгээ хүсэлтийг зөвшөөрсөнгүй. Текстэн хариулт хэвээр байна."
            elif status == 429:
                code = "tts_rate_limited"
                message = "Дуу унших үйлчилгээ түр ачаалалтай байна. Түр хүлээгээд дахин сонсоно уу."
            else:
                code = "tts_unavailable"
                message = "Дуу унших үйлчилгээтэй холбогдож чадсангүй. Текстэн хариулт хэвээр; дараа дахин сонсож болно."
            self._tts_attempt(voice, started, success=False, error=code, service_status=status)
            # edge-tts already retries a 403 after correcting server-clock skew.
            # Repeating a rejected protocol request here adds no recovery.
            raise VoiceRuntimeError(code, message, 503) from exc
        self._tts_attempt(voice, started, success=True)
        details = {"kind": "tts", "voice": voice, "text": text,
                   "characters": len(text), "synthesis_seconds": time.perf_counter() - started,
                   "service": "online Edge TTS experiment", "online_notice": ONLINE_NOTICE,
                   "audio_synthesized": True, "text_generated": False,
                   "human_quality_accepted": False, "llm_calls": 0}
        return self._save(audio, "audio/mpeg", details)

    @staticmethod
    def _validate_id(identifier):
        if not isinstance(identifier, str) or _ID.fullmatch(identifier) is None:
            raise VoiceRuntimeError("voice_id", "Дууны ID буруу байна.")

    def audio(self, identifier):
        self._validate_id(identifier)
        with self._records_lock:
            record = self._records.get(identifier)
            if record is None:
                raise VoiceRuntimeError("voice_audio_missing", "Энэ session-ийн дуу олдсонгүй.", 404)
            path, _, mime = record
            try:
                return self._safe_file(path).read_bytes(), mime
            except FileNotFoundError as exc:
                raise VoiceRuntimeError("voice_audio_missing", "Энэ session-ийн дуу устсан байна.", 404) from exc

    def reset(self, ids):
        if not isinstance(ids, list) or len(ids) > 100:
            raise VoiceRuntimeError("voice_ids", "Устгах дууны ID жагсаалт буруу байна.")
        for identifier in ids:
            self._validate_id(identifier)
        deleted = []
        with self._records_lock:
            records = [(identifier, self._records[identifier]) for identifier in dict.fromkeys(ids)
                       if identifier in self._records]
            for _, (audio_path, info_path, _) in records:
                self._safe_file(audio_path)
                self._safe_file(info_path)
            for identifier, (audio_path, info_path, _) in records:
                for path in (audio_path, info_path):
                    if path.exists():
                        self._safe_file(path).unlink()
                del self._records[identifier]
                deleted.append(identifier)
        return {"deleted_ids": deleted, "deleted_count": len(deleted),
                "original_recordings_modified": False, "model_unloaded": False}
