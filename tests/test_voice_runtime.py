"""Offline voice contracts: bounded decoding, pinned inference and private files.

All model/network/decoder libraries are invented mocks. No test trains a model,
downloads weights, sends student audio, or confirms a human transcript.
"""
import asyncio
import copy
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import voice_runtime as voice


def profile():
    return {"source_repo": voice.PINNED_SOURCE, "source_revision": voice.PINNED_REVISION,
            "model_sha256": voice.PINNED_SHA256, "development_model_path": "models/fixture",
            "decoding": copy.deepcopy(voice.EXPECTED_DECODING), "device": "cpu", "compute_type": "int8"}


def wav_bytes(seconds=0.02):
    data = io.BytesIO()
    with wave.open(data, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(voice.SAMPLE_RATE)
        handle.writeframes(b"\x00\x00" * int(seconds * voice.SAMPLE_RATE))
    return data.getvalue()


class FakeArray:
    def __init__(self, payload):
        self.payload = payload

    def tobytes(self):
        return self.payload


class FakeFrame:
    def __init__(self, samples, rate=16000, channels=1):
        self.samples, self.sample_rate = samples, rate
        self.layout = types.SimpleNamespace(channels=tuple(range(channels)))
        self.pts = 0

    def to_ndarray(self):
        return FakeArray(b"\x00\x00" * self.samples)


class FakeContainer:
    def __init__(self, frames, duration=None, audio_tracks=1):
        self.frames = frames
        self.yielded = 0
        self.closed = False
        self.streams = types.SimpleNamespace(audio=[types.SimpleNamespace(
            duration=duration, time_base=1)] * audio_tracks)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def decode(self, audio):
        for frame in self.frames:
            self.yielded += 1
            yield frame


class FakeResampler:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def resample(self, frame):
        return [] if frame is None else [FakeFrame(int(frame.samples * voice.SAMPLE_RATE / frame.sample_rate))]


def fake_av(container, major=18):
    calls = []

    def open_audio(handle, **kwargs):
        calls.append(kwargs)
        assert isinstance(handle, io.BytesIO)
        return container

    return types.SimpleNamespace(__version__=str(major) + ".0.0", open=open_audio,
                                 audio=types.SimpleNamespace(resampler=types.SimpleNamespace(
                                     AudioResampler=FakeResampler))), calls


class AudioBoundsTests(unittest.TestCase):
    def test_import_works_with_site_packages_disabled(self):
        script = "import sys; sys.path.insert(0, " + repr(str(Path(voice.__file__).parent)) + "); import voice_runtime; print('stdlib-only')"
        result = subprocess.run([sys.executable, "-S", "-c", script], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "stdlib-only")

    def test_container_magic_and_mime_cannot_accept_text_or_playlists(self):
        valid = wav_bytes()
        self.assertEqual(voice._audio_format(valid, "audio/wav;codecs=pcm")[0], "wav")
        self.assertEqual(voice._audio_format(valid, "application/octet-stream")[0], "wav")
        for payload, mime in [(b"#EXTM3U\nhttps://example.org/audio", "audio/wav"),
                              (valid, "audio/webm"), (b"", "audio/wav")]:
            with self.subTest(mime=mime, size=len(payload)):
                with self.assertRaises(voice.VoiceRuntimeError):
                    voice._audio_format(payload, mime)

    def test_oversize_compressed_input_is_rejected_without_decoder(self):
        with self.assertRaises(voice.VoiceRuntimeError) as caught:
            voice._audio_format(b"x" * (voice.MAX_AUDIO_BYTES + 1), "audio/wav")
        self.assertEqual(caught.exception.status, 413)

    def test_webm_without_duration_stops_at_frame_limit_not_end_of_stream(self):
        container = FakeContainer([FakeFrame(16000) for _ in range(100)])
        av, calls = fake_av(container)
        with patch.dict(sys.modules, {"av": av}):
            with self.assertRaises(voice.VoiceRuntimeError) as caught:
                voice._decode_pcm(b"fake", "matroska")
        self.assertEqual(caught.exception.code, "audio_too_long")
        self.assertEqual(container.yielded, 31)
        self.assertTrue(container.closed)
        self.assertEqual(calls[0]["format"], "matroska")

    def test_metadata_overlength_rejects_before_decoding(self):
        container = FakeContainer([FakeFrame(16000)], duration=31)
        av, _ = fake_av(container)
        with patch.dict(sys.modules, {"av": av}):
            with self.assertRaises(voice.VoiceRuntimeError):
                voice._decode_pcm(b"fake", "wav")
        self.assertEqual(container.yielded, 0)

    def test_exact_30_seconds_is_valid_and_pyav19_has_no_removed_argument(self):
        container = FakeContainer([FakeFrame(480000)])
        av, calls = fake_av(container, major=19)
        with patch.dict(sys.modules, {"av": av}):
            pcm = voice._decode_pcm(b"fake", "wav")
        self.assertEqual(len(pcm), 960000)
        self.assertNotIn("metadata_errors", calls[0])

    def test_sample_rate_channels_and_audio_track_ambiguity_are_rejected(self):
        for container in (FakeContainer([FakeFrame(100, rate=1000)]),
                          FakeContainer([FakeFrame(100, channels=3)]),
                          FakeContainer([FakeFrame(100)], audio_tracks=2)):
            av, _ = fake_av(container)
            with patch.dict(sys.modules, {"av": av}):
                with self.assertRaises(voice.VoiceRuntimeError):
                    voice._decode_pcm(b"fake", "wav")

    def test_mp4_external_data_references_are_disabled(self):
        container = FakeContainer([FakeFrame(100)])
        av, calls = fake_av(container)
        with patch.dict(sys.modules, {"av": av}):
            voice._decode_pcm(b"fake", "mov")
        self.assertEqual(calls[0]["options"], {"enable_drefs": "0"})


class VoiceRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.runtime = voice.VoiceRuntime(self.root)
        self.input = wav_bytes()
        self.pcm = b"\x01\x00" * 320

    def tearDown(self):
        self.temp.cleanup()

    def call_transcribe(self, factory=None, choice=None):
        choice = choice or profile()
        fake_model = types.SimpleNamespace(model=types.SimpleNamespace(compute_type="int8_float32"))
        calls = []

        def transcribe(audio, **kwargs):
            calls.append(kwargs)
            return iter([types.SimpleNamespace(start=0, end=0.02, text=" Тест ")]), types.SimpleNamespace(duration=0.02)

        fake_model.transcribe = transcribe
        factory = factory or (lambda *args, **kwargs: fake_model)
        fake = types.SimpleNamespace(WhisperModel=factory)
        with patch.dict(sys.modules, {"faster_whisper": fake}), \
                patch("stt_mn.load_choice", return_value=(choice, self.root / "models/fixture")), \
                patch.object(voice, "_decode_pcm", return_value=self.pcm), \
                patch.object(voice, "_waveform", return_value=[0.0] * 320):
            result = self.runtime.transcribe(self.input, "audio/wav")
        return result, calls

    def test_status_without_models_does_not_load_runtime_or_create_storage(self):
        with patch.object(voice, "_has_module", return_value=False):
            result = self.runtime.status()
        self.assertFalse(result["stt_ready"])
        self.assertFalse(result["tts_ready"])
        self.assertFalse(result["model_loaded"])
        self.assertFalse((self.root / "runtime").exists())

    def test_local_pinned_model_and_exact_decoder_keep_draft_text_unconfirmed(self):
        init = []

        def factory(path, **kwargs):
            init.append((path, kwargs))
            return types.SimpleNamespace(model=types.SimpleNamespace(compute_type="int8_float32"),
                                         transcribe=lambda *args, **kwargs: (
                                             iter([types.SimpleNamespace(start=0, end=.02, text="Тест")]), None))

        result, _ = self.call_transcribe(factory=factory)
        self.assertEqual(init[0][1], {"device": "cpu", "compute_type": "int8", "local_files_only": True})
        self.assertEqual(result["decoding"], voice.EXPECTED_DECODING)
        self.assertEqual(result["text"], "Тест")
        self.assertFalse(result["reference_confirmed"])
        self.assertFalse(result["accuracy_measured"])
        self.assertEqual(result["input_sha256"], hashlib.sha256(self.input).hexdigest())
        self.assertFalse(result["fine_tuning_performed"])

    def test_profile_revision_or_decoder_changes_stop_before_model_creation(self):
        for field, value in [("source_revision", "wrong"), ("decoding", {"language": "en"}),
                             ("device", "cuda"), ("model_sha256", "wrong")]:
            changed = profile()
            changed[field] = value
            with self.subTest(field=field), self.assertRaises(voice.VoiceRuntimeError) as caught:
                self.call_transcribe(choice=changed, factory=lambda *args, **kwargs: self.fail("must not instantiate"))
            self.assertEqual(caught.exception.code, "stt_profile_changed")

    def test_failed_checksum_is_reported_and_does_not_persist_audio(self):
        with patch.object(voice, "_decode_pcm", return_value=self.pcm), \
                patch.object(voice, "_waveform", return_value=[]), \
                patch("stt_mn.load_choice", side_effect=ValueError("checksum differs")):
            with self.assertRaises(voice.VoiceRuntimeError) as caught:
                self.runtime.transcribe(self.input, "audio/wav")
        self.assertEqual(caught.exception.code, "stt_model_verification")
        self.assertFalse((self.root / "runtime").exists())

    def test_overlength_fails_before_model_hash_or_load(self):
        with patch.object(voice, "_decode_pcm", side_effect=voice.VoiceRuntimeError("audio_too_long", "limit")), \
                patch("stt_mn.load_choice", side_effect=AssertionError("must not inspect model")):
            with self.assertRaises(voice.VoiceRuntimeError) as caught:
                self.runtime.transcribe(self.input, "audio/wav")
        self.assertEqual(caught.exception.code, "audio_too_long")

    def test_exact_digital_silence_is_rejected_without_changing_quiet_nonzero_policy(self):
        with patch.object(voice, "_decode_pcm", return_value=b"\x00\x00" * 320), \
                patch("stt_mn.load_choice", side_effect=AssertionError("must not inspect model")):
            with self.assertRaises(voice.VoiceRuntimeError) as caught:
                self.runtime.transcribe(self.input, "audio/wav")
        self.assertEqual(caught.exception.code, "audio_silent")
        self.assertFalse((self.root / "runtime").exists())
        result, _ = self.call_transcribe()
        self.assertTrue(result["speech_text_available"])
        self.assertFalse(result["decoding"]["vad_filter"])

    def test_empty_model_output_is_retained_as_empty_and_not_claimed_as_recognized_speech(self):
        def factory(*args, **kwargs):
            return types.SimpleNamespace(transcribe=lambda *args, **kwargs: (iter([]), None))

        result, _ = self.call_transcribe(factory=factory)
        self.assertEqual(result["text"], "")
        self.assertFalse(result["speech_text_available"])
        self.assertIn("гарсангүй", result["message"])
        self.assertFalse(result["reference_confirmed"])

    def test_loaded_model_is_reused_and_lazy_segments_are_consumed_under_lock(self):
        count = []

        def segments():
            self.assertTrue(self.runtime._model_lock.locked())
            time.sleep(.001)
            yield types.SimpleNamespace(start=0, end=.02, text="Тест")

        def factory(*args, **kwargs):
            count.append(1)
            return types.SimpleNamespace(transcribe=lambda *args, **kwargs: (segments(), None))

        first, _ = self.call_transcribe(factory=factory)
        second, _ = self.call_transcribe(factory=lambda *args, **kwargs: self.fail("reload"))
        self.assertEqual(len(count), 1)
        self.assertGreater(first["transcription_seconds"], 0.001)
        self.assertEqual(second["model_load_seconds"], 0.0)

    def test_concurrent_transcriptions_load_once_and_do_not_share_active_decoder(self):
        barrier = threading.Barrier(2)
        created, results, errors, active = [], [], [], []

        def decode(*args):
            barrier.wait(timeout=2)
            return self.pcm

        def segments():
            self.assertEqual(len(active), 0)
            active.append(1)
            time.sleep(.005)
            yield types.SimpleNamespace(start=0, end=.02, text="Тест")
            active.pop()

        def factory(*args, **kwargs):
            created.append(1)
            time.sleep(.005)
            return types.SimpleNamespace(transcribe=lambda *args, **kwargs: (segments(), None))

        def request():
            try:
                results.append(self.runtime.transcribe(self.input, "audio/wav"))
            except Exception as exc:
                errors.append(exc)

        with patch.dict(sys.modules, {"faster_whisper": types.SimpleNamespace(WhisperModel=factory)}), \
                patch("stt_mn.load_choice", return_value=(profile(), self.root / "models/fixture")), \
                patch.object(voice, "_decode_pcm", side_effect=decode), \
                patch.object(voice, "_waveform", return_value=[0.0] * 320):
            threads = [threading.Thread(target=request) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=2)
        self.assertFalse(errors)
        self.assertEqual(len(results), 2)
        self.assertEqual(len(created), 1)
        self.assertEqual(len({result["id"] for result in results}), 2)
        self.assertTrue(any(result["queue_wait_seconds"] > .003 for result in results))

    def test_transcription_persists_sanitized_wav_and_reset_preserves_original(self):
        original = self.root / "audio" / "q01.wav"
        original.parent.mkdir()
        original.write_bytes(self.input)
        result, _ = self.call_transcribe()
        saved, mime = self.runtime.audio(result["id"])
        self.assertEqual(mime, "audio/wav")
        with wave.open(io.BytesIO(saved), "rb") as handle:
            self.assertEqual((handle.getnchannels(), handle.getframerate()), (1, 16000))
        self.assertEqual(self.runtime.reset([result["id"], result["id"]])["deleted_count"], 1)
        self.assertEqual(original.read_bytes(), self.input)
        with self.assertRaises(voice.VoiceRuntimeError) as caught:
            self.runtime.audio(result["id"])
        self.assertEqual(caught.exception.status, 404)

    def test_audio_id_and_reset_reject_traversal_before_mutating_any_valid_file(self):
        result, _ = self.call_transcribe()
        for bad in ("../q01.wav", "A" * 32, "0" * 32 + ".mp3", None):
            with self.subTest(id=bad), self.assertRaises(voice.VoiceRuntimeError):
                self.runtime.reset([result["id"], bad])
            self.assertTrue(self.runtime.audio(result["id"])[0])
        self.assertEqual(self.runtime.reset(["0" * 32])["deleted_count"], 0)

    def test_restart_cannot_serve_another_runtime_session_audio(self):
        result, _ = self.call_transcribe()
        other = voice.VoiceRuntime(self.root)
        with self.assertRaises(voice.VoiceRuntimeError):
            other.audio(result["id"])
        self.assertEqual(other.reset([result["id"]])["deleted_count"], 0)
        self.assertTrue(self.runtime.audio(result["id"])[0])

    def test_tts_only_sends_selected_text_and_keeps_generated_audio_private(self):
        calls = []

        async def edge(text, selected):
            calls.append((text, selected))
            return b"ID3fake-mp3"

        with patch.object(voice, "_edge_audio", side_effect=edge):
            result = self.runtime.synthesize(" Тестийн текст. ", "mn-MN-YesuiNeural")
        self.assertEqual(calls, [("Тестийн текст.", "mn-MN-YesuiNeural")])
        self.assertEqual(self.runtime.audio(result["id"]), (b"ID3fake-mp3", "audio/mpeg"))
        self.assertTrue(result["audio_synthesized"])
        self.assertFalse(result["text_generated"])
        self.assertFalse(result["human_quality_accepted"])
        self.assertIn("онлайн", result["online_notice"])

    def test_unsupported_voice_empty_text_and_long_text_never_call_service(self):
        for text, selected in (("Тест", "en-US-AriaNeural"), (" ", voice.ALLOWED_VOICES[0]),
                               ("x" * 2001, voice.ALLOWED_VOICES[0])):
            with patch.object(voice, "_edge_audio", side_effect=AssertionError("network")):
                with self.assertRaises(voice.VoiceRuntimeError):
                    self.runtime.synthesize(text, selected)

    def test_tts_timeout_keeps_no_partial_file_and_reports_504(self):
        cancelled = []

        async def edge(text, selected):
            try:
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                cancelled.append(True)
                raise

        with patch.object(voice, "TTS_TIMEOUT_SECONDS", .002), \
                patch.object(voice, "_edge_audio", side_effect=edge):
            with self.assertRaises(voice.VoiceRuntimeError) as caught:
                self.runtime.synthesize("Тест", voice.ALLOWED_VOICES[0])
        self.assertEqual(caught.exception.status, 504)
        self.assertEqual(cancelled, [True])
        self.assertFalse((self.root / "runtime").exists())

    def test_session_capacity_is_enforced_before_network_or_inference(self):
        with patch.object(voice, "MAX_SESSION_ITEMS", 1):
            self.call_transcribe()
            with patch.object(voice, "_edge_audio", side_effect=AssertionError("network")):
                with self.assertRaises(voice.VoiceRuntimeError) as caught:
                    self.runtime.synthesize("Тест", voice.ALLOWED_VOICES[0])
        self.assertEqual(caught.exception.code, "voice_session_full")

    def test_edge_stream_byte_limit_is_applied_before_audio_persistence(self):
        class Communicate:
            def __init__(self, *args):
                pass

            async def stream(self):
                yield {"type": "WordBoundary", "text": "metadata ignored"}
                yield {"type": "audio", "data": b"1234"}
                yield {"type": "audio", "data": b"5678"}

        with patch.dict(sys.modules, {"edge_tts": types.SimpleNamespace(Communicate=Communicate)}), \
                patch.object(voice, "MAX_TTS_BYTES", 6):
            with self.assertRaises(voice.VoiceRuntimeError) as caught:
                self.runtime.synthesize("Тест", voice.ALLOWED_VOICES[0])
        self.assertEqual(caught.exception.code, "tts_size_limit")
        self.assertFalse((self.root / "runtime").exists())


if __name__ == "__main__":
    unittest.main()
