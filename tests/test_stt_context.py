"""Offline contracts; model inference is replaced by a deterministic transport."""
import copy
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import wave

from tools import evaluate_stt_context as experiment


class ContextExperimentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.model_path = self.root / 'models/fixture'
        self.model_path.mkdir(parents=True)
        (self.model_path / 'model.bin').write_bytes(b'offline model fixture')
        (self.model_path / 'tokenizer.json').write_text('{}')
        self.model_sha = experiment.sha(self.model_path / 'model.bin')
        self.model_manifest = {'files': {name: {'sha256': experiment.sha(self.model_path / name)}
                                        for name in ('model.bin', 'tokenizer.json')}}
        (self.model_path / 'download-manifest.json').write_text(json.dumps(self.model_manifest))
        self.choice = dict(source_repo=experiment.PINNED_SOURCE,
            source_revision=experiment.PINNED_REVISION, model_sha256=self.model_sha,
            decoding=copy.deepcopy(experiment.BASE_DECODING), device='cpu', compute_type='int8')
        self.config_path = self.root / 'config.json'
        self.config = dict(schema_version=1, arms=dict(baseline={},
            school_hotwords=dict(hotwords='Сургуулийн нэр, лаборатори'), beam10=dict(beam_size=10)))
        self.config_path.write_text(json.dumps(self.config), encoding='utf-8')
        self.manifest_path = self.root / 'manifest.json'
        self.manifest = dict(schema_version=1,
            human_rows=[self.row('human', 'зөв хариулт', 'human')],
            control_rows=[self.row('synthetic', 'туршилтын текст', 'synthetic_speech'),
                          self.row('silence', '', 'silence'), self.row('noise', '', 'noise')])
        self.save_manifest()
        self.calls, self.created = [], []
        self.texts = dict(human='буруу текст', synthetic='туршилтын текст', silence='хийсвэр', noise='')
        self.on_transcribe = None

    def tearDown(self):
        self.temp.cleanup()

    def row(self, identity, reference, kind):
        path = self.root / (identity + '.wav')
        with wave.open(str(path), 'wb') as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(16000)
            handle.writeframes((b'\x00\x00' if kind == 'silence' else b'\x01\x00') * 1600)
        value = dict(id=identity, audio_path=path.name, audio_sha256=experiment.sha(path),
                     reference=reference, reference_status='eligible_speaker_confirmed' if kind == 'human' else 'synthetic_control')
        if kind != 'human':
            value['control_kind'] = kind
        return value

    def save_manifest(self):
        self.manifest_path.write_text(json.dumps(self.manifest, ensure_ascii=False), encoding='utf-8')

    def factory(self, path, **kwargs):
        self.assertTrue((self.output / 'protocol.json').is_file())
        protocol = experiment.read_json(self.output / 'protocol.json')
        self.assertEqual(protocol['manifest_sha256'], experiment.sha(self.manifest_path))
        self.created.append((path, kwargs))

        def transcribe(audio, **decoding):
            self.calls.append((audio, copy.deepcopy(decoding)))
            if self.on_transcribe:
                self.on_transcribe()
            text = self.texts[Path(audio).stem]
            rows = [types.SimpleNamespace(start=0.0, end=0.1, text=' ' + text + ' ',
                    avg_logprob=-0.4, no_speech_prob=0.1)] if text else []
            return iter(rows), types.SimpleNamespace(duration=0.1)

        return types.SimpleNamespace(transcribe=transcribe,
                                     model=types.SimpleNamespace(compute_type='int8_float32'))

    def run_arm(self, arm='school_hotwords', output='result'):
        self.output = self.root / output
        with patch.object(experiment, 'load_choice', return_value=(self.choice, self.model_path)), \
                patch.object(experiment, 'PINNED_SHA256', self.model_sha), \
                patch.object(experiment.importlib.metadata, 'version', return_value='fixture-version'), \
                patch.dict(sys.modules, {'faster_whisper': types.SimpleNamespace(WhisperModel=self.factory)}), \
                redirect_stdout(io.StringIO()):
            return experiment.run(self.config_path, arm, self.manifest_path, self.output, root=self.root)

    def test_prompt_arm_keeps_raw_and_separates_human_synthetic_nonspeech(self):
        manifest_hash = experiment.sha(self.manifest_path)
        summary = self.run_arm()
        self.assertEqual(self.created[0][1], dict(device='cpu', compute_type='int8', local_files_only=True))
        self.assertEqual(len(self.created), 1)
        self.assertEqual(len(self.calls), 4)
        expected = dict(experiment.BASE_DECODING, hotwords=self.config['arms']['school_hotwords']['hotwords'])
        self.assertTrue(all(decoding == expected for _, decoding in self.calls))
        self.assertEqual(summary['human_metrics']['utterances'], 1)
        self.assertEqual(summary['human_metrics']['corpus_wer'], 1.0)
        self.assertEqual(summary['control_speech_metrics']['utterances'], 1)
        self.assertEqual(summary['control_speech_metrics']['corpus_wer'], 0.0)
        self.assertEqual(summary['nonspeech_nonempty_count'], 1)
        raw = experiment.read_json(self.output / 'human.json')
        self.assertEqual(raw['text'], 'буруу текст')
        self.assertNotEqual(raw['text'], self.manifest['human_rows'][0]['reference'])
        self.assertFalse(raw['reference_used_for_inference'])
        self.assertFalse(raw['automatic_postcorrection'])
        self.assertEqual(experiment.sha(self.manifest_path), manifest_hash)
        self.assertEqual(raw['protocol_sha256'], experiment.sha(self.output / 'protocol.json'))
        protocol = experiment.read_json(self.output / 'protocol.json')
        self.assertEqual(protocol['model_asset_sha256'], {name: row['sha256'] for name, row in self.model_manifest['files'].items()})
        self.assertIn('tools/evaluate_stt_context.py', protocol['code_sha256'])

    def test_beam_arm_changes_only_beam_and_allows_control_only_manifest(self):
        self.manifest['human_rows'] = []
        self.save_manifest()
        summary = self.run_arm('beam10')
        self.assertIsNone(summary['human_metrics'])
        self.assertEqual(summary['human_recordings'], 0)
        self.assertEqual(len(self.calls), 3)
        self.assertTrue(all(decoding == dict(experiment.BASE_DECODING, beam_size=10)
                            for _, decoding in self.calls))

    def test_sentence_prompt_is_one_bounded_change_without_reference_injection(self):
        prompt='Туршилтын сургууль. Номын сан, лаборатори.'
        self.config['arms']['sentence']=dict(initial_prompt=prompt)
        self.config_path.write_text(json.dumps(self.config),encoding='utf-8')
        result=self.run_arm('sentence')
        self.assertEqual(result['human_recordings'],1)
        self.assertTrue(all(decoding==dict(experiment.BASE_DECODING,initial_prompt=prompt)
                            for _,decoding in self.calls))
        for value in ['',42,'x'*1201,'bad\nline']:
            self.config['arms']['bad']=dict(initial_prompt=value)
            with self.assertRaises(ValueError):experiment.decoding_for(self.config,'bad')
        self.config['arms']['bad']=dict(initial_prompt=prompt,hotwords='another')
        with self.assertRaises(ValueError):experiment.decoding_for(self.config,'bad')

    def test_existing_output_refused_before_choice_or_model_load(self):
        output = self.root / 'old-result'
        output.mkdir()
        with patch.object(experiment, 'load_choice') as load:
            with self.assertRaises(FileExistsError):
                experiment.run(self.config_path, 'baseline', self.manifest_path, output, root=self.root)
        load.assert_not_called()
        self.assertEqual(list(output.iterdir()), [])

    def test_reserved_result_names_rejected_before_audio_audit_or_model_work(self):
        device_names = ('CON', 'prn', 'Aux', 'NUL', 'con.txt', 'NUL.recording') + tuple(
            prefix + str(number) + suffix
            for prefix in ('COM', 'lpt') for number in range(1, 10) for suffix in ('', '.txt'))
        for identity in ('protocol', 'summary', 'Protocol', 'SUMMARY') + device_names:
            with self.subTest(identity=identity):
                bad = copy.deepcopy(self.manifest)
                bad['human_rows'][0]['id'] = identity
                self.manifest_path.write_text(json.dumps(bad), encoding='utf-8')
                with patch.object(experiment, 'load_choice') as load, \
                        patch.object(experiment, 'audit_wav') as audit, self.assertRaises(ValueError):
                    experiment.run(self.config_path, 'baseline', self.manifest_path,
                                   self.root / 'reserved', root=self.root)
                load.assert_not_called()
                audit.assert_not_called()
                self.assertFalse((self.root / 'reserved').exists())

    def test_case_insensitive_duplicate_ids_rejected_before_model_work(self):
        self.manifest['control_rows'][0]['id'] = 'HUMAN'
        self.save_manifest()
        with patch.object(experiment, 'load_choice') as load, self.assertRaises(ValueError):
            experiment.run(self.config_path, 'baseline', self.manifest_path,
                           self.root / 'duplicate', root=self.root)
        load.assert_not_called()
        self.assertFalse((self.root / 'duplicate').exists())

    def test_frozen_json_hash_and_parse_use_same_bytes_when_path_changes_after_read(self):
        original = self.config_path.read_bytes()
        original_read = Path.read_bytes

        def read_then_change(path):
            data = original_read(path)
            if path == self.config_path:
                self.config_path.write_text('{"schema_version":999}', encoding='utf-8')
            return data

        with patch.object(Path, 'read_bytes', new=read_then_change):
            value, digest = experiment.read_frozen_json(self.config_path)
        self.assertEqual(value, self.config)
        self.assertEqual(digest, hashlib.sha256(original).hexdigest())
        self.assertNotEqual(digest, experiment.sha(self.config_path))

    def test_manifest_edit_after_snapshot_is_detected_before_model_verification(self):
        original_read = Path.read_bytes

        def read_then_change(path):
            data = original_read(path)
            if path == self.manifest_path:
                changed = copy.deepcopy(self.manifest)
                changed['human_rows'][0]['reference'] = 'өөр текст'
                self.manifest_path.write_text(json.dumps(changed), encoding='utf-8')
            return data

        with patch.object(Path, 'read_bytes', new=read_then_change), \
                patch.object(experiment, 'load_choice') as load, self.assertRaises(ValueError):
            experiment.run(self.config_path, 'baseline', self.manifest_path,
                           self.root / 'raced', root=self.root)
        load.assert_not_called()
        self.assertFalse((self.root / 'raced').exists())

    def test_bad_audio_hash_and_unconfirmed_human_stop_before_loading(self):
        for field, value in [('audio_sha256', '0' * 64), ('reference_status', 'needs_confirmation'), ('reference', '')]:
            with self.subTest(field=field):
                bad = copy.deepcopy(self.manifest)
                bad['human_rows'][0][field] = value
                self.manifest_path.write_text(json.dumps(bad), encoding='utf-8')
                with patch.object(experiment, 'load_choice') as load, self.assertRaises(ValueError):
                    experiment.run(self.config_path, 'baseline', self.manifest_path, self.root / 'invalid', root=self.root)
                load.assert_not_called()
                self.assertFalse((self.root / 'invalid').exists())

    def test_controls_cannot_be_scored_as_confirmed_humans_or_vice_versa(self):
        self.manifest['control_rows'][1]['reference'] = 'энэ бол чимээгүй биш'
        self.save_manifest()
        with self.assertRaises(ValueError):
            self.run_arm()
        self.assertFalse(self.created)
        self.assertFalse(self.output.exists())

    def test_unsafe_id_cannot_escape_output_directory(self):
        self.manifest['human_rows'][0]['id'] = '../overwrite'
        self.save_manifest()
        with self.assertRaises(ValueError):
            self.run_arm()
        self.assertFalse(self.created)

    def test_unsupported_or_combined_decoder_changes_rejected(self):
        for change in [dict(hotwords='нэр', beam_size=10), dict(initial_prompt=''),
                       dict(prefix='forced words'), dict(beam_size=True), dict(beam_size=1)]:
            with self.subTest(change=change):
                self.config['arms']['bad'] = change
                self.config_path.write_text(json.dumps(self.config), encoding='utf-8')
                with self.assertRaises(ValueError):
                    self.run_arm('bad')
                self.assertFalse(self.created)

    def test_model_profile_and_tokenizer_assets_are_verified_before_inference(self):
        self.choice['decoding']['vad_filter'] = True
        with self.assertRaises(ValueError):
            self.run_arm()
        self.choice['decoding'] = copy.deepcopy(experiment.BASE_DECODING)
        (self.model_path / 'tokenizer.json').write_text('{"changed":true}')
        with self.assertRaises(ValueError):
            self.run_arm()
        self.assertFalse(self.created)
        self.assertFalse(self.output.exists())

    def test_audio_change_during_inference_stops_without_success_summary(self):
        self.on_transcribe = lambda: (self.root / 'human.wav').write_bytes(b'changed')
        with self.assertRaises(ValueError):
            self.run_arm()
        self.assertTrue((self.output / 'protocol.json').exists())
        self.assertFalse((self.output / 'summary.json').exists())

    def test_configuration_edit_during_inference_retains_raw_but_no_success_summary(self):
        initial_hash = experiment.sha(self.config_path)
        self.on_transcribe = lambda: self.config_path.write_text('{"changed":true}', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.run_arm()
        protocol = experiment.read_json(self.output / 'protocol.json')
        self.assertEqual(protocol['config_sha256'], initial_hash)
        self.assertNotEqual(protocol['config_sha256'], experiment.sha(self.config_path))
        self.assertEqual(experiment.read_json(self.output / 'human.json')['text'], 'буруу текст')
        self.assertFalse((self.output / 'summary.json').exists())


if __name__ == '__main__':
    unittest.main()
