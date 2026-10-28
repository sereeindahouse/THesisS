"""Artificial audio fixtures only; local decode tests perform no ASR or recording."""
from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import wave

from tools import prepare_stt_study_audio as prepare


def fixture_wav(rate=48000, channels=1, seconds=.25, sample=1000):
    memory = io.BytesIO()
    with wave.open(memory, 'wb') as handle:
        handle.setnchannels(channels); handle.setsampwidth(2); handle.setframerate(rate)
        handle.writeframes(struct.pack('<h', sample) * round(rate * seconds) * channels)
    return memory.getvalue()


class StudyAudioPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'original48k.wav'
        self.source.write_bytes(fixture_wav())
        self.output = self.root / 'new16k.wav'
        self.provenance = self.root / 'new16k.wav.provenance.json'
        self.before = self.source.read_bytes()

    def test_actual48k_mono_pyav_resample_preserves_original_and_duration(self):
        result = prepare.prepare_audio(self.source, self.output)
        self.assertEqual(self.source.read_bytes(), self.before)
        with wave.open(str(self.output), 'rb') as handle:
            self.assertEqual((handle.getframerate(), handle.getnchannels(), handle.getsampwidth()), (16000, 1, 2))
            self.assertEqual(handle.getnframes(), 4000)
            self.assertEqual(len(handle.readframes(4001)), 8000)
        self.assertEqual(result['frames'], 4000)
        self.assertEqual(result['duration_seconds'], .25)
        record = json.loads(self.provenance.read_text(encoding='utf-8'))
        self.assertEqual(record['source']['sha256'], hashlib.sha256(self.before).hexdigest())
        self.assertEqual(record['source']['sample_rate'], 48000)
        self.assertEqual(record['source']['channels'], 1)
        self.assertEqual(record['source']['forced_demuxer'], 'wav')
        self.assertEqual(record['output']['sha256'], hashlib.sha256(self.output.read_bytes()).hexdigest())
        self.assertEqual(record['loaded_code_sha256']['voice_runtime.py'], hashlib.sha256((prepare.ROOT / 'voice_runtime.py').read_bytes()).hexdigest())
        self.assertEqual(record['loaded_code_sha256']['stt_mn.py'], hashlib.sha256((prepare.ROOT / 'stt_mn.py').read_bytes()).hexdigest())
        self.assertEqual(record['loaded_code_sha256']['tools/prepare_stt_study_audio.py'], hashlib.sha256(Path(prepare.__file__).read_bytes()).hexdigest())
        self.assertTrue(record['no_asr_performed'])
        self.assertFalse(record['microphone_activated'])
        self.assertFalse(record['consent_asserted'])
        self.assertFalse(record['human_transcript_review_performed'])
        self.assertNotIn('reference', record)

    def test_actual44k_stereo_becomes_mono_without_duration_change(self):
        self.source.write_bytes(fixture_wav(rate=44100, channels=2, seconds=.2))
        source_sha = hashlib.sha256(self.source.read_bytes()).hexdigest()
        result = prepare.prepare_audio(self.source, self.output)
        self.assertEqual(result['frames'], 3200)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), source_sha)
        evidence = json.loads(self.provenance.read_text(encoding='utf-8'))
        self.assertEqual(evidence['source']['channels'], 2)
        self.assertEqual(evidence['source']['sample_rate'], 44100)

    def test_both_destinations_are_preflighted_before_decode(self):
        for blocked in (self.output, self.provenance):
            with self.subTest(blocked=blocked.name):
                blocked.write_bytes(b'preserve this existing file')
                with patch.object(prepare.voice, '_decode_pcm') as decode:
                    with self.assertRaises(FileExistsError):
                        prepare.prepare_audio(self.source, self.output)
                decode.assert_not_called()
                self.assertEqual(blocked.read_bytes(), b'preserve this existing file')
                other = self.provenance if blocked == self.output else self.output
                self.assertFalse(other.exists())
                blocked.unlink()
        self.assertEqual(self.source.read_bytes(), self.before)

    def test_source_output_and_provenance_aliases_are_rejected_before_decode(self):
        pairs = [(self.source, self.provenance), (self.output, self.source), (self.output, self.output)]
        for output, provenance in pairs:
            with self.subTest(output=output.name, provenance=provenance.name):
                with patch.object(prepare.voice, '_decode_pcm') as decode:
                    with self.assertRaisesRegex(ValueError, 'three different paths'):
                        prepare.prepare_audio(self.source, output, provenance)
                decode.assert_not_called()
        self.assertEqual(self.source.read_bytes(), self.before)

    def test_existing_hardlink_alias_cannot_replace_the_source(self):
        alias = self.root / 'alias.wav'
        os.link(self.source, alias)
        with patch.object(prepare.voice, '_decode_pcm') as decode:
            with self.assertRaises(FileExistsError):
                prepare.prepare_audio(self.source, alias)
        decode.assert_not_called()
        self.assertEqual(self.source.read_bytes(), self.before)

    def test_output_suffixes_and_parent_directories_preflight_before_decode(self):
        for output, provenance in ((self.root / 'bad.mp3', self.provenance),
                                   (self.output, self.root / 'bad.txt'),
                                   (self.root / 'missing' / 'new.wav', self.provenance)):
            with self.subTest(output=str(output)):
                with patch.object(prepare.voice, '_decode_pcm') as decode:
                    with self.assertRaises(ValueError):
                        prepare.prepare_audio(self.source, output, provenance)
                decode.assert_not_called()
        self.assertFalse((self.root / 'missing').exists())

    def test_oversized_source_is_rejected_without_decode_or_writes(self):
        self.source.write_bytes(b'X' * (8 * 1024 * 1024 + 1))
        with patch.object(prepare.voice, '_decode_pcm') as decode:
            with self.assertRaisesRegex(ValueError, 'exceeds8MiB'):
                prepare.prepare_audio(self.source, self.output)
        decode.assert_not_called()
        self.assertFalse(self.output.exists()); self.assertFalse(self.provenance.exists())

    def test_invalid_container_and_corrupt_wave_fail_without_outputs(self):
        for data in (b'not a supported container', b'RIFF\x28\x00\x00\x00WAVE' + b'X' * 40):
            with self.subTest(prefix=data[:12]):
                self.source.write_bytes(data)
                with self.assertRaises(prepare.voice.VoiceRuntimeError):
                    prepare.prepare_audio(self.source, self.output)
                self.assertEqual(self.source.read_bytes(), data)
                self.assertFalse(self.output.exists()); self.assertFalse(self.provenance.exists())

    def test_actual_over30_second_audio_is_rejected_before_outputs(self):
        self.source.write_bytes(fixture_wav(rate=8000, seconds=30.01))
        with self.assertRaises(prepare.voice.VoiceRuntimeError) as raised:
            prepare.prepare_audio(self.source, self.output)
        self.assertEqual(raised.exception.code, 'audio_too_long')
        self.assertFalse(self.output.exists()); self.assertFalse(self.provenance.exists())

    def test_supported_container_magic_is_forwarded_to_existing_forced_decoder(self):
        cases = [(fixture_wav(), 'wav'), (b'\x1a\x45\xdf\xa3' + b'X' * 12, 'matroska'),
                 (b'OggS' + b'X' * 12, 'ogg'), (b'\x00\x00\x00\x18ftyp' + b'X' * 12, 'mov')]
        for index, (data, demuxer) in enumerate(cases):
            with self.subTest(demuxer=demuxer):
                self.source.write_bytes(data)
                out = self.root / f'forward-{index}.wav'
                with patch.object(prepare.voice, '_decode_pcm', return_value=b'\x01\x00' * 1600) as decode, \
                     patch.object(prepare, '_source_metadata', return_value=dict(container='mock fixture', sample_rate=None)):
                    prepare.prepare_audio(self.source, out)
                decode.assert_called_once_with(data, demuxer)

    def test_source_tamper_after_decode_is_detected_without_outputs(self):
        def tamper(*_):
            self.source.write_bytes(fixture_wav(sample=2000))
            return b'\x01\x00' * 1600
        with patch.object(prepare.voice, '_decode_pcm', side_effect=tamper):
            with self.assertRaisesRegex(ValueError, 'changed during preparation'):
                prepare.prepare_audio(self.source, self.output)
        self.assertFalse(self.output.exists()); self.assertFalse(self.provenance.exists())

    def test_decode_failure_does_not_create_output_or_provenance(self):
        with patch.object(prepare.voice, '_decode_pcm', side_effect=prepare.voice.VoiceRuntimeError('fixture_failure', 'constructed decode failure')):
            with self.assertRaises(prepare.voice.VoiceRuntimeError):
                prepare.prepare_audio(self.source, self.output)
        self.assertEqual(self.source.read_bytes(), self.before)
        self.assertFalse(self.output.exists()); self.assertFalse(self.provenance.exists())

    def test_invalid_decoded_pcm_cannot_produce_a_mislabeled_wave(self):
        for pcm in (b'', b'x', b'xx' * (480000 + 1)):
            with self.subTest(length=len(pcm)):
                with patch.object(prepare.voice, '_decode_pcm', return_value=pcm):
                    with self.assertRaisesRegex(ValueError, 'bounded complete PCM16'):
                        prepare.prepare_audio(self.source, self.output)
                self.assertFalse(self.output.exists()); self.assertFalse(self.provenance.exists())

    def test_incorrect_derived_wave_header_is_rejected_before_writes(self):
        with patch.object(prepare.voice, '_wav_bytes', return_value=fixture_wav(rate=8000)):
            with self.assertRaisesRegex(ValueError, 'Derived WAV header or frame payload differs'):
                prepare.prepare_audio(self.source, self.output)
        self.assertFalse(self.output.exists()); self.assertFalse(self.provenance.exists())

    def test_code_binding_must_match_loaded_voice_and_stt(self):
        stale = dict(prepare.voice._LOADED_ARTIFACT_SHA256)
        stale['stt_mn.py'] = '0' * 64
        with patch.object(prepare.voice, '_LOADED_ARTIFACT_SHA256', stale), \
             patch.object(prepare.voice, '_decode_pcm') as decode:
            with self.assertRaisesRegex(ValueError, 'Loaded preparation/voice/STT code differs'):
                prepare.prepare_audio(self.source, self.output)
        decode.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_destination_race_preserves_other_file_and_incomplete_reservation(self):
        def race(*_):
            self.provenance.write_bytes(b'created by another writer')
            return b'\x01\x00' * 1600
        with patch.object(prepare.voice, '_decode_pcm', side_effect=race):
            with self.assertRaisesRegex(prepare.IncompletePreparationError, 'left untouched'):
                prepare.prepare_audio(self.source, self.output)
        self.assertEqual(self.provenance.read_bytes(), b'created by another writer')
        self.assertEqual(self.output.read_bytes(), b'')
        self.assertEqual(self.source.read_bytes(), self.before)

    def test_adversarial_replacement_after_handle_close_is_never_deleted(self):
        original_open = Path.open
        backup = self.root / 'old-exclusive-reservation.wav'
        replaced = []
        class ReplaceWhenClosed:
            def __init__(wrapper, handle):
                wrapper.handle = handle
            def close(wrapper):
                wrapper.handle.close()
                if not replaced:
                    # Windows permits replacement after the owning handle closes.
                    # This is the same vulnerable interval as stat-then-unlink.
                    self.output.rename(backup)
                    self.output.write_bytes(b'other writer replacement')
                    replaced.append(True)
        def opening(path, mode='r', *args, **kwargs):
            handle = original_open(path, mode, *args, **kwargs)
            return ReplaceWhenClosed(handle) if path == self.output and mode == 'xb' else handle
        def race(*_):
            self.provenance.write_bytes(b'other writer provenance')
            return b'\x01\x00' * 1600
        with patch.object(prepare.voice, '_decode_pcm', side_effect=race), \
             patch.object(Path, 'open', opening), \
             patch.object(Path, 'unlink', side_effect=AssertionError('No path-based cleanup is allowed')):
            with self.assertRaises(prepare.IncompletePreparationError):
                prepare.prepare_audio(self.source, self.output)
        self.assertEqual(self.output.read_bytes(), b'other writer replacement')
        self.assertEqual(self.provenance.read_bytes(), b'other writer provenance')
        self.assertEqual(backup.read_bytes(), b'')
        self.assertEqual(self.source.read_bytes(), self.before)

    def test_cli_partial_reservation_failure_reports_unusable_outputs(self):
        def race(*_):
            self.provenance.write_bytes(b'another writer')
            return b'\x01\x00' * 1600
        with patch.object(prepare.voice, '_decode_pcm', side_effect=race), \
             redirect_stdout(io.StringIO()) as printed:
            code = prepare.main(['--input', str(self.source), '--output', str(self.output)])
        result = json.loads(printed.getvalue())
        self.assertEqual(code, 2)
        self.assertFalse(result['usable_outputs'])
        self.assertEqual(result['incomplete_output_paths'], [str(self.output.resolve())])
        self.assertIn('not a completed WAV/provenance pair', result['error'])
        self.assertEqual(self.output.read_bytes(), b'')
        self.assertEqual(self.provenance.read_bytes(), b'another writer')

    def test_explicit_new_provenance_path_and_cli_result(self):
        custom = self.root / 'capture-evidence.json'
        with redirect_stdout(io.StringIO()) as printed:
            code = prepare.main(['--input', str(self.source), '--output', str(self.output), '--provenance', str(custom)])
        result = json.loads(printed.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(result['provenance'], str(custom.resolve()))
        self.assertTrue(custom.is_file())
        self.assertFalse(self.provenance.exists())

    def test_cli_existing_output_returns_structured_error_without_mutation(self):
        self.output.write_bytes(b'keep')
        with redirect_stdout(io.StringIO()) as printed:
            code = prepare.main(['--input', str(self.source), '--output', str(self.output)])
        result = json.loads(printed.getvalue())
        self.assertEqual(code, 2)
        self.assertFalse(result['ok'])
        self.assertEqual(self.output.read_bytes(), b'keep')
        self.assertFalse(self.provenance.exists())


if __name__ == '__main__':
    unittest.main()
