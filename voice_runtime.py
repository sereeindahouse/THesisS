"""Bounded local STT and explicitly requested online speech for the localhost demo.

The module imports with the standard library alone. Runtime libraries are loaded
only after a user supplies audio or asks for speech. Uploaded audio/transcripts
stay in the ignored runtime directory and never become training references.
"""
import asyncio
from array import array
from collections import OrderedDict
import copy
import hashlib
import importlib.util
import importlib.metadata
import io
import json
import math
import re
import threading
import sys
import time
import uuid
import wave
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType

import stt_mn as _stt_mn


MAX_AUDIO_BYTES = 8 * 1024 * 1024
MAX_AUDIO_SECONDS = 30
from answer_contract import MAX_SPEECH_CHARACTERS
MAX_TEXT_CHARACTERS = MAX_SPEECH_CHARACTERS
SAMPLE_RATE = 16000
DECODE_TIMEOUT_SECONDS = 15
TTS_TIMEOUT_SECONDS = 25
MAX_TTS_BYTES = 4 * 1024 * 1024
MAX_SESSION_ITEMS = 40
MAX_TTS_CACHE_ITEMS = 6
MAX_TTS_CACHE_BYTES = 8 * 1024 * 1024
TTS_CACHE_SECONDS = 300
ALLOWED_VOICES = ("mn-MN-BataaNeural", "mn-MN-YesuiNeural")
PINNED_SOURCE = "Cafet/whisper-small-mongolian"
PINNED_REVISION = "d54c63a518d6dea7ab54a27c83d0b6b52bea3e9d"
PINNED_SHA256 = "7a2a3f0a939addbd2ae9532dfb2b16590ecc3fbb145a214b784b05797e202843"
EXPECTED_DECODING = dict(language="mn", task="transcribe", beam_size=5,
                         vad_filter=False, temperature=0.0,
                         without_timestamps=True,
                         condition_on_previous_text=False)
_FIXED_DECODING = MappingProxyType(dict(EXPECTED_DECODING))
_SPEECH_PRESENCE_OPTIONS = MappingProxyType(dict(
    threshold=0.5, neg_threshold=None, min_speech_duration_ms=0,
    max_speech_duration_s="Infinity", min_silence_duration_ms=2000, speech_pad_ms=400))
VOICE_ARTIFACT_NAMES = ("voice_runtime.py", "stt_mn.py")


def _imported_stt_sha256():
    data = Path(_stt_mn.__file__).read_bytes()
    # stt_mn may have been imported before this module. Fail closed if its
    # already loaded functions differ from the source bytes being fingerprinted.
    compiled = compile(data, _stt_mn.__file__, "exec")
    functions = [item for item in compiled.co_consts if hasattr(item, "co_name")
                 and item.co_name in {"load_choice", "main"}]
    if not functions or any(getattr(getattr(_stt_mn, item.co_name, None), "__code__", None) != item
                            for item in functions):
        return None
    return hashlib.sha256(data).hexdigest()


# Capture once when these standard-library-only modules are imported. Status
# must identify the loaded code, not re-label it with subsequently edited files.
_LOADED_ARTIFACT_SHA256 = MappingProxyType({
    "voice_runtime.py": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    "stt_mn.py": _imported_stt_sha256(),
})
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


def _speech_presence_policy():
    return dict(enabled=True, method="faster_whisper_packaged_Silero",
                purpose="any_speech_presence_only", sampling_rate=SAMPLE_RATE,
                options=dict(_SPEECH_PRESENCE_OPTIONS), calibrated_confidence=False,
                crops_or_reorders_audio=False, downloads=False,
                whisper_vad_filter=False)


def _speech_presence(audio):
    """Presence-only local gate; the caller retains the unchanged full array."""
    try:
        from faster_whisper.vad import VadOptions, get_speech_timestamps
        options = dict(_SPEECH_PRESENCE_OPTIONS)
        options["max_speech_duration_s"] = float("inf")
        regions = get_speech_timestamps(audio, vad_options=VadOptions(**options), sampling_rate=SAMPLE_RATE)
        if not isinstance(regions, list):
            raise TypeError("Unexpected speech detector output")
    except Exception as exc:
        raise VoiceRuntimeError("speech_presence_failed", "Яриа байгаа эсэхийг шалгаж чадсангүй; түр хүлээгээд дахин оролдоно уу.", 503) from exc
    return dict(_speech_presence_policy(), any_speech=bool(regions), region_count=len(regions))


def _wav_bytes(pcm):
    output = io.BytesIO()
    with wave.open(output, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(pcm)
    return output.getvalue()


def _recognition_review(pcm, segments):
    """Heuristic recording/decoder warnings; never a calibrated accuracy score."""
    samples=array('h');samples.frombytes(pcm)
    if sys.byteorder!='little':samples.byteswap()
    rms=math.sqrt(sum(sample*sample for sample in samples)/len(samples))/32768 if samples else 0.0
    clipping=sum(abs(sample)>=32700 for sample in samples)/len(samples) if samples else 0.0
    flags=[]
    if rms<0.01:flags.append('quiet_recording')
    if clipping>0.01:flags.append('clipped_recording')
    for name,threshold,label,direction in [
        ('avg_logprob',-1.0,'low_decoder_score',-1),
        ('no_speech_prob',0.6,'uncertain_speech',1),
        ('compression_ratio',2.4,'repetitive_output',1)]:
        if any(isinstance(row.get(name),(int,float)) and not isinstance(row[name],bool)
               and math.isfinite(row[name]) and direction*row[name]>direction*threshold for row in segments):
            flags.append(label)
    notices={'quiet_recording':'Бичлэгийн дуу сул байна.',
        'clipped_recording':'Бичлэгийн дуу хэт чанга, тасарсан байж болно.',
        'low_decoder_score':'Танилтад эргэлзээтэй хэсэг байна.',
        'uncertain_speech':'Яриа тод бус хэсэг байна.',
        'repetitive_output':'Танилтад үг давтагдсан байж болно.'}
    return dict(flags=flags,needs_extra_review=bool(flags),rms=round(rms,6),
        clipping_fraction=round(clipping,6),heuristic=True,calibrated_confidence=False,
        changes_transcript=False,message=' '.join(notices[flag] for flag in flags))


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
        from gemini_stt_runtime import GeminiSTT
        self.root = Path(root).resolve()
        from gemini_credentials import WindowsCredentialStore
        self.gemini = GeminiSTT(credential_store=WindowsCredentialStore(
            self.root / 'runtime' / 'gemini-credentials.dpapi'))
        self._session = self.root / "runtime" / "voice-demo" / uuid.uuid4().hex
        self._model = None
        self._choice = None
        self._loaded_model_fingerprint = None
        self._model_lock = threading.Lock()
        self._records_lock = threading.RLock()
        self._records = {}
        # Keep the original STT result in memory, independently of mutable
        # composer text and JSON artifacts. Only _save of a real STT record can
        # establish this binding; the routing client never supplies raw_text.
        self._transcription_texts = {}
        self._last_tts_attempt = None
        self._tts_lock = threading.Lock()
        self._tts_cache = OrderedDict()

    def _stt_provenance(self):
        loaded = self._model is not None
        fingerprint = (copy.deepcopy(self._loaded_model_fingerprint) if loaded else
                       dict(source_repo=PINNED_SOURCE, source_revision=PINNED_REVISION,
                            model_sha256=PINNED_SHA256, device="cpu", compute_type="int8",
                            actual_compute_type=None))
        return dict(loaded_artifact_sha256=dict(_LOADED_ARTIFACT_SHA256),
                    effective_decoding=dict(_FIXED_DECODING), model_loaded=loaded,
                    model_fingerprint=fingerprint, model_fingerprint_verified=loaded,
                    model_fingerprint_scope="verified_loaded_model" if loaded else "fixed_profile_not_loaded")

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
        stt_ready = present and all(_has_module(name) for name in ("av", "numpy", "faster_whisper", "onnxruntime"))
        tts_ready = _has_module("edge_tts")
        try:
            tts_version = importlib.metadata.version("edge-tts")
        except importlib.metadata.PackageNotFoundError:
            tts_version = None
        with self._records_lock:
            last_tts = dict(self._last_tts_attempt) if self._last_tts_attempt else None
        return {"available": stt_ready or tts_ready, "stt_ready": stt_ready,
                "gemini": self.gemini.status(),
                "tts_ready": tts_ready, "tts_dependency_ready": tts_ready,
                "tts_package_version": tts_version,
                "tts_ready_checks_dependencies_only": True,
                "tts_last_attempt": last_tts, "model_files_present": present,
                **self._stt_provenance(),
                "speech_presence": _speech_presence_policy(),
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
            choice, path = _stt_mn.load_choice(self.root)
            if (choice.get("source_repo"), choice.get("source_revision"), choice.get("model_sha256")) != (
                    PINNED_SOURCE, PINNED_REVISION, PINNED_SHA256):
                raise VoiceRuntimeError("stt_profile_changed", "Туршиж сонгосон Cafet моделийн хувилбар өөрчлөгдсөн байна.", 503)
            if choice.get("decoding") != dict(_FIXED_DECODING) or choice.get("device") != "cpu" or choice.get("compute_type") != "int8":
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
        self._choice = copy.deepcopy(choice)
        self._loaded_model_fingerprint = dict(
            source_repo=choice["source_repo"], source_revision=choice["source_revision"],
            model_sha256=choice["model_sha256"], device=choice["device"],
            compute_type=choice["compute_type"],
            actual_compute_type=getattr(getattr(model, "model", None), "compute_type", "unknown"))
        self._model = model
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
            if result.get('kind') == 'stt' and isinstance(result.get('text'), str):
                self._transcription_texts[identifier] = result['text']
        return result

    def transcription_lineage(self, identifier, query):
        """Bind submitted text to this runtime's saved, unchanged STT output.

        Sending or editing text is not a human-confirmed utterance reference.
        A returned snapshot remains meaningful after a later session reset;
        deleted IDs cannot establish new bindings.
        """
        self._validate_id(identifier)
        if not isinstance(query, str) or not query.strip() or len(query) > MAX_TEXT_CHARACTERS:
            raise VoiceRuntimeError('stt_lineage_query', 'Илгээх асуултын текст буруу байна.')
        with self._records_lock:
            record = self._records.get(identifier)
            if record is None:
                raise VoiceRuntimeError('stt_lineage_missing', 'Энэ session-ийн STT бичлэг олдсонгүй.', 404)
            audio_path, info_path, _ = record
            if not self._safe_file(audio_path).is_file() or not self._safe_file(info_path).is_file():
                raise VoiceRuntimeError('stt_lineage_missing', 'Энэ session-ийн STT бичлэг устсан байна.', 404)
            if identifier not in self._transcription_texts:
                raise VoiceRuntimeError('stt_lineage_kind', 'Асуултыг зөвхөн STT бичлэгтэй холбоно.', 409)
            raw = self._transcription_texts[identifier]
            edited = query != raw
            return dict(kind='edited_stt' if edited else 'raw_stt', transcription_id=identifier,
                        raw_text=raw, submitted_text=query, edited=edited,
                        manual_verification_claimed=False)

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
        presence_started = time.perf_counter()
        presence = _speech_presence(audio)
        if not presence["any_speech"]:
            raise VoiceRuntimeError("audio_no_speech", "Бичлэгээс яриа илэрсэнгүй. Микрофоноо шалгаж, дахин ярьж бичнэ үү.")
        presence_seconds = time.perf_counter() - presence_started
        queued = time.perf_counter()
        with self._model_lock:
            queue_seconds = time.perf_counter() - queued
            load_seconds = self._load_model()
            started = time.perf_counter()
            try:
                segments, _ = self._model.transcribe(audio, **dict(_FIXED_DECODING))
                rows=[]
                for segment in segments:
                    row=dict(start=float(segment.start),end=float(segment.end),text=segment.text.strip())
                    for name in ('avg_logprob','no_speech_prob','compression_ratio'):
                        value=getattr(segment,name,None)
                        row[name]=(float(value) if isinstance(value,(int,float)) and not isinstance(value,bool)
                                   and math.isfinite(value) else None)
                    rows.append(row)
            except Exception as exc:
                raise VoiceRuntimeError("stt_failed", "STT дууг таньж чадсангүй; текстээ гараар оруулж үргэлжлүүлж болно.", 503) from exc
            elapsed = time.perf_counter() - started
            actual_compute = getattr(getattr(self._model, "model", None), "compute_type", "unknown")
        text = " ".join(row["text"] for row in rows).strip()
        review=_recognition_review(pcm,rows)
        details = {"kind": "stt", "text": text, "segments": rows,
                   "recognition_review": review,
                   "speech_text_available": bool(text),
                   "message": ((review['message']+' ' if review['message'] else '')+"STT текст гарлаа; хэлсэн үгтэйгээ нягталж засна уу." if text else
                               "Ярианы текст гарсангүй; өгүүлбэрээ гараар оруулах эсвэл дахин бичиж болно."),
                   "audio_seconds": len(pcm) / (SAMPLE_RATE * 2),
                   "decode_seconds": decode_seconds, "queue_wait_seconds": queue_seconds,
                   "speech_presence": presence, "speech_presence_seconds": presence_seconds,
                   "model_load_seconds": load_seconds, "transcription_seconds": elapsed,
                   "input_sha256": hashlib.sha256(audio_bytes).hexdigest(),
                   "model": PINNED_SOURCE, "revision": PINNED_REVISION,
                   "model_sha256": PINNED_SHA256, "decoding": dict(_FIXED_DECODING),
                   **self._stt_provenance(),
                   "device": "cpu", "compute_type": "int8", "actual_compute_type": actual_compute,
                   "local_files_only": True, "reference_confirmed": False,
                   "human_review_required": True, "fine_tuning_performed": False,
                   "accuracy_measured": False, "text_generated": False, "llm_calls": 0}
        return self._save(_wav_bytes(pcm), "audio/wav", details)

    def transcribe_gemini(self, audio_bytes, content_type, *, consent=False, live=False):
        from gemini_stt_runtime import GeminiSTTError
        if consent is not True:
            raise VoiceRuntimeError('gemini_consent', 'Энэ бичлэгийг Google руу илгээх чагтыг сонгоно уу.')
        self._check_capacity()
        demuxer, _ = _audio_format(audio_bytes, content_type)
        pcm = _decode_pcm(audio_bytes, demuxer)
        if not any(pcm):
            raise VoiceRuntimeError('audio_silent', 'Бичлэг хоосон байна; микрофоноо шалгана уу.')
        wav = _wav_bytes(pcm)
        try:
            result = self.gemini.transcribe(wav, consent=True, live=live)
        except GeminiSTTError as error:
            raise VoiceRuntimeError('gemini_' + error.code, str(error), 429 if error.code == 'http_429' else 503) from None
        languages=result.get('detected_language_codes', [])
        from stt_measurement import year_tokens
        detected_years = year_tokens(result['text'])
        unexpected_language=bool(live and languages and not any(code.lower().split('-')[0]=='mn' for code in languages))
        details = dict(kind='stt', **result, segments=[],
            input_sha256=hashlib.sha256(audio_bytes).hexdigest(),
            transmitted_audio_sha256=hashlib.sha256(wav).hexdigest(),
            audio_seconds=len(pcm)/(SAMPLE_RATE*2), model_load_seconds=0,
            speech_text_available=bool(result['text'].strip()),
            message=(('Монгол хэлээр танигдсангүй ('+', '.join(languages)+'). Бүтэн Монгол асуултаа дахин хэлэх эсвэл текстээ засна уу.'
                     if unexpected_language else 'Gemini 3.5 Live Translate · Монгол оролтын бичвэрийг цуглууллаа. '
                     + ('Төгсгөлийн үг орсон эсэхийг сонсож нягтална уу.'
                        if result.get('input_transcription_finished') else
                        'Текстээ бүтнээр нь, ялангуяа төгсгөлийн үгийг бичлэгтэйгээ тулгаж нягтална уу.')) if live else
                     'Gemini 3.5 Transcribe · анхны танилт. Хэлсэн үгтэйгээ нягтална уу.'),
            recognition_review=dict(needs_extra_review=True,
                unexpected_language=unexpected_language,
                year_tokens=detected_years, year_tokens_are_literal=True,
                message='Gemini-ийн нэр, тоо, он болон үгүйсгэлийг өөрөө нягтална уу.'),
            local_files_only=False, language_codes=result.get('detected_language_codes', []) if live else ['mn-MN'], cloud_audio_consent=True,
            reference_confirmed=False, human_review_required=True, fine_tuning_performed=False,
            accuracy_measured=False, text_generated=False, llm_calls=0)
        if detected_years:
            details['message'] += ' Танигдсан он: '+', '.join(detected_years)+'. Онуудаа бичлэгтэй тулгаж нягтлаарай.'
        return self._save(wav, 'audio/wav', details)

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
        if voice not in ALLOWED_VOICES:
            raise VoiceRuntimeError('tts_voice','Bataa эсвэл Yesui монгол дууг сонгоно уу.')
        if not isinstance(text,str) or not text.strip():
            raise VoiceRuntimeError('tts_text_empty','Уншуулах текст хоосон байна.')
        from speech_text import normalize_spoken_currency
        text=normalize_spoken_currency(text.strip())
        if len(text)>MAX_TEXT_CHARACTERS:
            raise VoiceRuntimeError('tts_text_limit','Уншуулах текст 2000 тэмдэгтээс урт байна.')
        # Cache exact text+voice only. Each response still receives a fresh
        # private audio ID, so deleting one turn cannot invalidate another.
        key=(voice,hashlib.sha256(text.encode('utf-8')).hexdigest())
        with self._tts_lock:
            self._check_capacity()
            now=time.monotonic()
            with self._records_lock:
                for old in list(self._tts_cache):
                    if now-self._tts_cache[old][0]>=TTS_CACHE_SECONDS:
                        del self._tts_cache[old]
                cached=self._tts_cache.get(key)
                if cached:self._tts_cache.move_to_end(key)
            if cached:
                created,audio,details=cached
                return self._save(audio,'audio/mpeg',dict(details,cache_hit=True,
                    provider_request=False,cache_age_seconds=round(now-created,3),synthesis_seconds=0.0))
            result=self._synthesize_uncached(text,voice)
            audio,_=self.audio(result['id'])
            names=('kind','voice','text','characters','service','online_notice',
                   'audio_synthesized','text_generated','human_quality_accepted','llm_calls')
            details={name:result[name] for name in names}
            with self._records_lock:
                self._tts_cache[key]=(time.monotonic(),audio,details)
                while (len(self._tts_cache)>MAX_TTS_CACHE_ITEMS or
                       sum(len(item[1]) for item in self._tts_cache.values())>MAX_TTS_CACHE_BYTES):
                    self._tts_cache.popitem(last=False)
            return result

    def _synthesize_uncached(self, text, voice):
        self._check_capacity()
        if voice not in ALLOWED_VOICES:
            raise VoiceRuntimeError("tts_voice", "Bataa эсвэл Yesui монгол дууг сонгоно уу.")
        if not isinstance(text, str) or not text.strip():
            raise VoiceRuntimeError("tts_text_empty", "Уншуулах текст хоосон байна.")
        from speech_text import normalize_spoken_currency
        text = normalize_spoken_currency(text.strip())
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
                   "cache_hit": False, "provider_request": True,
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
                self._transcription_texts.pop(identifier, None)
                deleted.append(identifier)
            if not self._records:
                self._tts_cache.clear()
        return {"deleted_ids": deleted, "deleted_count": len(deleted),
                "original_recordings_modified": False, "model_unloaded": False}
