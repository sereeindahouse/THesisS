"""Constructed offline contract fixtures only: no real participants, speech or ASR."""
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from tools import stt_study_manifest as study


def wav_bytes(value=1, frames=1600, encoding=1, channels=1, rate=16000, bits=None,
              extensible=False):
    """Artificial constant samples exercise parsing, never a recognition benchmark."""
    bits = bits or (16 if encoding == 1 else 32)
    alignment = channels * bits // 8
    fmt = struct.pack('<HHIIHH', 0xFFFE if extensible else encoding,
                      channels, rate, rate * alignment, alignment, bits)
    if extensible:
        fmt += struct.pack('<HHI', 22, bits, 4)
        fmt += struct.pack('<I', encoding) + bytes.fromhex('00001000800000aa00389b71')
    if encoding == 3:
        payload = struct.pack('<f', value) * frames * channels
    else:
        payload = struct.pack('<h', value) * frames * channels
    chunks = b'fmt ' + struct.pack('<I', len(fmt)) + fmt + b'data' + struct.pack('<I', len(payload)) + payload
    return b'RIFF' + struct.pack('<I', 4 + len(chunks)) + b'WAVE' + chunks


class StudyManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'dataset'
        self.root.mkdir()
        self.manifest_path = self.root / 'manifest.json'
        self.output = self.root / 'freeze-v1.json'
        self.manifest = dict(schema_version=1, study_kind='real_school_question_pilot',
                             speakers=[], clips=[])
        # These are declared metadata in unit fixtures, NOT recorded consent or
        # actual human review. No fixture is delivered as study data.
        for split in ('train', 'dev', 'test'):
            for index in range(2):
                identity = f'{split}-{index}'
                filename = identity + '.wav'
                data = wav_bytes(value=len(self.manifest['clips']) + 1)
                (self.root / filename).write_bytes(data)
                self.manifest['speakers'].append(dict(speaker_id='speaker-' + identity,
                    speaker_group_id='person-' + identity,
                    consent_scope='training_and_evaluation' if split == 'train' else 'evaluation_only'))
                self.manifest['clips'].append(dict(clip_id='clip-' + identity,
                    speaker_id='speaker-' + identity, split=split,
                    audio_path=filename, audio_sha256=hashlib.sha256(data).hexdigest(),
                    duration_seconds=.1, recorded_at='2026-01-01T09:00:00+00:00',
                    device='constructed unit fixture', room='fixture room',
                    scenario='constructed school question fixture ' + identity,
                    elicitation='spontaneous_question', audio_origin='real_human_recording',
                    reference='Constructed fixture question ' + identity,
                    transcript_review=dict(confirmed=True, reviewer_id='fixture-reviewer',
                        reviewed_at='2026-01-01T09:01:00+00:00', uncertainties=[])))
        self.save()

    def save(self):
        self.manifest_path.write_text(json.dumps(self.manifest, ensure_ascii=False), encoding='utf-8')

    def validate(self):
        self.save()
        return study.validate_manifest(self.manifest_path, self.root)

    def codes(self, report):
        return {error['code'] for error in report['errors']}

    def replace_audio(self, index, data):
        clip = self.manifest['clips'][index]
        (self.root / clip['audio_path']).write_bytes(data)
        clip['audio_sha256'] = hashlib.sha256(data).hexdigest()

    def test_complete_manifest_and_exclusive_freeze_bind_exact_bytes(self):
        report = self.validate()
        self.assertTrue(report['valid'])
        self.assertTrue(report['freeze_ready'])
        self.assertEqual(report['counts'], {split: dict(clips=2, speakers=2) for split in ('train', 'dev', 'test')})
        self.assertEqual(len(report['audio_audits']), 6)
        result = study.freeze_manifest(self.manifest_path, self.root, self.output)
        frozen = json.loads(self.output.read_text(encoding='utf-8'))
        self.assertEqual(frozen['manifest'], self.manifest)
        self.assertEqual(frozen['source_manifest_sha256'], hashlib.sha256(self.manifest_path.read_bytes()).hexdigest())
        self.assertEqual(frozen['validator']['sha256'], hashlib.sha256(Path(study.__file__).read_bytes()).hexdigest())
        self.assertEqual(result['sha256'], hashlib.sha256(self.output.read_bytes()).hexdigest())
        self.assertTrue(frozen['no_asr_performed'])
        self.assertTrue(frozen['no_transcript_created'])
        self.assertIsNone(frozen['measured_accuracy'])
        self.assertTrue(frozen['frozen_utc'].endswith('+00:00'))

    def test_freeze_never_overwrites_an_existing_file(self):
        self.output.write_bytes(b'preserve original artifact')
        with self.assertRaises(FileExistsError):
            study.freeze_manifest(self.manifest_path, self.root, self.output)
        self.assertEqual(self.output.read_bytes(), b'preserve original artifact')

    def test_validation_is_read_only_and_does_not_create_missing_materials(self):
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        study.validate_manifest(self.manifest_path, self.root)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})
        self.manifest['speakers'] = []; self.manifest['clips'] = []
        report = self.validate()
        self.assertFalse(report['valid'])
        self.assertIn('clips_required', self.codes(report))
        with self.assertRaises(ValueError):
            study.freeze_manifest(self.manifest_path, self.root, self.output)
        self.assertFalse(self.output.exists())

    def test_partial_valid_collection_cannot_freeze_without_all_splits(self):
        self.manifest['clips'] = self.manifest['clips'][:1]
        report = self.validate()
        self.assertTrue(report['valid'])
        self.assertFalse(report['freeze_ready'])
        self.assertEqual({x['path'] for x in report['freeze_errors']}, {'train', 'dev', 'test'})
        with self.assertRaisesRegex(ValueError, 'insufficient_split_speakers'):
            study.freeze_manifest(self.manifest_path, self.root, self.output)

    def test_canonical_person_cannot_leak_through_another_pseudonym(self):
        self.manifest['speakers'][2]['speaker_group_id'] = self.manifest['speakers'][0]['speaker_group_id'].upper()
        self.assertIn('speaker_split_leakage', self.codes(self.validate()))

    def test_speaker_case_variation_does_not_hide_leakage(self):
        self.manifest['clips'][2]['speaker_id'] = self.manifest['clips'][0]['speaker_id'].upper()
        self.assertIn('speaker_split_leakage', self.codes(self.validate()))

    def test_two_aliases_of_one_person_count_as_one_speaker(self):
        self.manifest['speakers'][1]['speaker_group_id'] = self.manifest['speakers'][0]['speaker_group_id']
        report = self.validate()
        self.assertTrue(report['valid'])
        self.assertEqual(report['counts']['train']['speakers'], 1)
        self.assertFalse(report['freeze_ready'])

    def test_evaluation_only_consent_excludes_training(self):
        self.manifest['speakers'][0]['consent_scope'] = 'evaluation_only'
        self.assertIn('training_consent_required', self.codes(self.validate()))

    def test_consent_scope_must_be_explicit_and_well_typed(self):
        for value in (None, '', 'yes', ['training_and_evaluation']):
            with self.subTest(value=value):
                self.manifest['speakers'][0]['consent_scope'] = value
                self.assertIn('consent_scope', self.codes(self.validate()))

    def test_unconfirmed_or_model_guessed_reference_is_not_accepted(self):
        review = self.manifest['clips'][0]['transcript_review']
        for value in (False, 'true', 1):
            with self.subTest(value=value):
                review['confirmed'] = value
                self.assertIn('human_review_unconfirmed', self.codes(self.validate()))

    def test_uncertain_words_or_numbers_block_freezing(self):
        self.manifest['clips'][0]['transcript_review']['uncertainties'] = ['uncertain number']
        self.assertIn('unresolved_uncertainty', self.codes(self.validate()))
        with self.assertRaisesRegex(ValueError, 'unresolved_uncertainty'):
            study.freeze_manifest(self.manifest_path, self.root, self.output)

    def test_empty_or_punctuation_only_reference_is_rejected(self):
        for value in ('', '   ', '?!...'):
            with self.subTest(value=value):
                self.manifest['clips'][0]['reference'] = value
                self.assertIn('reference_required', self.codes(self.validate()))

    def test_review_must_follow_recording_and_use_aware_past_timestamps(self):
        for value in ('2026-01-01T09:00:00+00:00', '2026-01-01T08:59:00Z',
                      '2026-01-01T09:01:00', '2099-01-01T09:01:00Z'):
            with self.subTest(value=value):
                self.manifest['clips'][0]['transcript_review']['reviewed_at'] = value
                self.assertIn('review_chronology', self.codes(self.validate()))

    def test_guided_answers_and_synthetic_speech_do_not_enter_question_pilot(self):
        self.manifest['clips'][0]['elicitation'] = 'guided_answer'
        self.manifest['clips'][1]['audio_origin'] = 'tts_generated'
        codes = self.codes(self.validate())
        self.assertIn('not_spontaneous_question', codes)
        self.assertIn('not_real_recording', codes)

    def test_missing_group_context_and_unknown_fields_are_reported(self):
        del self.manifest['speakers'][0]['speaker_group_id']
        self.manifest['clips'][0]['room'] = ''
        self.manifest['clips'][1]['transcript_review']['model_approved'] = True
        self.manifest['unexpected'] = 'not silently trusted'
        codes = self.codes(self.validate())
        self.assertTrue({'missing_field', 'context_required', 'unknown_field'}.issubset(codes))

    def test_duplicate_ids_and_undeclared_speaker_are_rejected(self):
        self.manifest['clips'][1]['clip_id'] = self.manifest['clips'][0]['clip_id'].upper()
        self.manifest['clips'][2]['speaker_id'] = 'undeclared-person'
        self.manifest['speakers'][1]['speaker_id'] = self.manifest['speakers'][0]['speaker_id'].upper()
        self.assertTrue({'clip_identity', 'unknown_speaker', 'duplicate_speaker_id'}.issubset(self.codes(self.validate())))

    def test_cross_split_reference_duplicates_survive_case_punctuation_and_nfc(self):
        self.manifest['clips'][0]['reference'] = 'Өвлийн кафе\u0301?'
        self.manifest['clips'][2]['reference'] = 'ӨВЛИЙН КАФЕ\u0301.'
        self.assertIn('transcript_split_duplicate', self.codes(self.validate()))

    def test_compact_transcript_duplicates_cannot_hide_behind_spacing(self):
        self.manifest['clips'][0]['reference'] = 'Шинэ Монгол'
        self.manifest['clips'][2]['reference'] = 'шинэмонгол'
        codes = self.codes(self.validate())
        self.assertIn('compact_transcript_split_duplicate', codes)
        self.assertNotIn('transcript_split_duplicate', codes)

    def test_same_audio_cannot_be_duplicated_across_splits_or_inside_one_split(self):
        first = (self.root / self.manifest['clips'][0]['audio_path']).read_bytes()
        for index in (1, 2):
            with self.subTest(index=index):
                self.replace_audio(index, first)
                self.assertIn('duplicate_audio', self.codes(self.validate()))

    def test_absolute_traversing_and_windows_drive_paths_are_rejected(self):
        outside = self.root.parent / 'outside.wav'
        outside.write_bytes(wav_bytes(value=17))
        for value in ('../outside.wav', str(outside.resolve()), 'C:\\elsewhere\\voice.wav',
                      '\\\\server\\share\\voice.wav', 'sub/../train-0.wav', 'train-0.wav:stream'):
            with self.subTest(value=value):
                self.manifest['clips'][0]['audio_path'] = value
                self.assertIn('invalid_audio', self.codes(self.validate()))

    def test_escaping_resolved_link_target_is_rejected(self):
        outside = self.root.parent / 'outside.wav'
        outside.write_bytes(wav_bytes(value=17))
        alias = self.root / 'alias.wav'
        original = Path.resolve
        # Model the OS resolution of an escaping link even on Windows accounts
        # without symlink-creation privileges; the containment guard still runs.
        def resolved(path, *args, **kwargs):
            return outside if path == alias else original(path, *args, **kwargs)
        self.manifest['clips'][0]['audio_path'] = 'alias.wav'
        self.save()
        with patch.object(Path, 'resolve', resolved):
            self.assertIn('invalid_audio', self.codes(study.validate_manifest(self.manifest_path, self.root)))

    def test_actual_symlink_escape_when_platform_allows_creation(self):
        outside = self.root.parent / 'outside.wav'
        outside.write_bytes(wav_bytes(value=18))
        alias = self.root / 'actual-link.wav'
        try:
            alias.symlink_to(outside)
        except (OSError, NotImplementedError) as exc:
            self.skipTest('OS does not allow actual symlink creation: ' + str(exc))
        self.manifest['clips'][0]['audio_path'] = alias.name
        self.assertIn('invalid_audio', self.codes(self.validate()))

    def test_unresolvable_audio_link_loop_returns_a_validation_error(self):
        alias = self.root / 'loop.wav'
        original = Path.resolve
        def resolved(path, *args, **kwargs):
            if path == alias:
                raise RuntimeError('Symlink loop')
            return original(path, *args, **kwargs)
        self.manifest['clips'][0]['audio_path'] = alias.name
        self.save()
        with patch.object(Path, 'resolve', resolved):
            report = study.validate_manifest(self.manifest_path, self.root)
        self.assertFalse(report['valid'])
        self.assertIn('invalid_audio', self.codes(report))

    def test_unresolvable_dataset_root_returns_structured_cli_failure(self):
        original = Path.resolve
        def resolved(path, *args, **kwargs):
            if path == self.root:
                raise RuntimeError('Symlink loop')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'resolve', resolved):
            report = study.validate_manifest(self.manifest_path, self.root)
            self.assertIn('unreadable_manifest_or_root', self.codes(report))
            with redirect_stdout(io.StringIO()) as printed:
                code = study.main(['freeze', '--manifest', str(self.manifest_path),
                    '--dataset-root', str(self.root), '--output', str(self.output)])
        self.assertEqual(code, 2)
        self.assertIn('symbolic-link loop', json.loads(printed.getvalue())['error'])
        self.assertFalse(self.output.exists())

    def test_corrupt_or_truncated_wav_and_hash_tampering_are_rejected(self):
        for data in (b'not a wave', wav_bytes()[:-2], b'RIFF\x00\x00\x00\x00WAVE' + b'x' * 40):
            with self.subTest(length=len(data)):
                self.replace_audio(0, data)
                self.assertIn('invalid_audio', self.codes(self.validate()))
        self.replace_audio(0, wav_bytes(value=31))
        self.manifest['clips'][0]['audio_sha256'] = '0' * 64
        self.assertIn('audio_hash_mismatch', self.codes(self.validate()))

    def test_actual_format_duration_and_silence_are_checked(self):
        for data in (wav_bytes(channels=2), wav_bytes(rate=8000), wav_bytes(value=0), wav_bytes(frames=480001)):
            with self.subTest(length=len(data)):
                self.replace_audio(0, data)
                self.assertIn('invalid_audio', self.codes(self.validate()))
        self.replace_audio(0, wav_bytes(value=32))
        self.manifest['clips'][0]['duration_seconds'] = .2
        self.assertIn('audio_duration_mismatch', self.codes(self.validate()))

    def test_huge_integer_duration_returns_validation_errors_without_crashing(self):
        # These1001-digit integers are valid JSON and fit below Python's JSON
        # integer limit, but converting them to float would overflow.
        for value in (10 ** 1000, -(10 ** 1000), 1e300, -1e300, True, 0, 31):
            with self.subTest(value_type=type(value).__name__, positive=value > 0):
                self.manifest['clips'][0]['duration_seconds'] = value
                report = self.validate()
                self.assertFalse(report['valid'])
                self.assertIn('duration', self.codes(report))
                self.assertFalse(report['freeze_ready'])

    def test_cli_huge_integer_duration_returns_structured_error(self):
        self.manifest['clips'][0]['duration_seconds'] = 10 ** 1000
        self.save()
        arguments = ['--manifest', str(self.manifest_path), '--dataset-root', str(self.root)]
        with redirect_stdout(io.StringIO()) as printed:
            code = study.main(['validate'] + arguments)
        report = json.loads(printed.getvalue())
        self.assertEqual(code, 2)
        self.assertFalse(report['valid'])
        self.assertIn('duration', self.codes(report))
        with redirect_stdout(io.StringIO()) as printed:
            code = study.main(['freeze'] + arguments + ['--output', str(self.output)])
        self.assertEqual(code, 2)
        self.assertIn('duration', json.loads(printed.getvalue())['error'])
        self.assertFalse(self.output.exists())

    def test_float32_and_extensible_formats_work_but_nonfinite_samples_do_not(self):
        self.replace_audio(0, wav_bytes(value=.125, encoding=3))
        self.replace_audio(1, wav_bytes(value=.25, encoding=3, extensible=True))
        self.replace_audio(2, wav_bytes(value=73, extensible=True))
        report = self.validate()
        self.assertTrue(report['valid'], report['errors'])
        self.assertEqual([a['sample_format'] for a in report['audio_audits'][:3]], ['float32', 'float32', 'pcm16'])
        for value in (float('nan'), float('inf'), -float('inf')):
            with self.subTest(value=value):
                self.replace_audio(0, wav_bytes(value=value, encoding=3))
                self.assertIn('invalid_audio', self.codes(self.validate()))

    def test_duplicate_json_keys_and_nonfinite_json_constants_are_rejected(self):
        for data in ('{"schema_version":1,"schema_version":1}', '{"duration":NaN}'):
            with self.subTest(data=data):
                self.manifest_path.write_text(data, encoding='utf-8')
                report = study.validate_manifest(self.manifest_path, self.root)
                self.assertIn('unreadable_manifest_or_root', self.codes(report))

    def test_invalid_unicode_and_excessive_json_nesting_return_validation_errors(self):
        for data in ('{"bad":"\\ud800"}', '[' * 1100 + '0' + ']' * 1100):
            with self.subTest(length=len(data)):
                self.manifest_path.write_text(data, encoding='utf-8')
                report = study.validate_manifest(self.manifest_path, self.root)
                self.assertFalse(report['valid'])
                self.assertIn('unreadable_manifest_or_root', self.codes(report))

    def test_changed_validator_code_binding_blocks_freeze(self):
        with patch.object(study, '_CODE_SHA256', '0' * 64):
            with self.assertRaisesRegex(ValueError, 'validator_code_changed_after_import'):
                study.freeze_manifest(self.manifest_path, self.root, self.output)
        self.assertFalse(self.output.exists())

    def test_audio_changed_after_validation_blocks_freeze(self):
        real_validate = study.validate_manifest
        def validate_then_tamper(*args):
            result = real_validate(*args)
            (self.root / self.manifest['clips'][0]['audio_path']).write_bytes(wav_bytes(value=99))
            return result
        with patch.object(study, 'validate_manifest', side_effect=validate_then_tamper):
            with self.assertRaisesRegex(ValueError, 'audio_changed_after_validation'):
                study.freeze_manifest(self.manifest_path, self.root, self.output)
        self.assertFalse(self.output.exists())

    def test_source_changed_after_validation_blocks_freeze(self):
        real_validate = study.validate_manifest
        def validate_then_tamper(*args):
            result = real_validate(*args)
            self.manifest_path.write_bytes(self.manifest_path.read_bytes() + b' ')
            return result
        with patch.object(study, 'validate_manifest', side_effect=validate_then_tamper):
            with self.assertRaisesRegex(ValueError, 'source_changed_after_validation'):
                study.freeze_manifest(self.manifest_path, self.root, self.output)
        self.assertFalse(self.output.exists())

    def test_cli_reports_incomplete_collection_and_freeze_refuses_it(self):
        self.manifest['clips'] = []; self.save()
        with redirect_stdout(io.StringIO()) as printed:
            code = study.main(['validate', '--manifest', str(self.manifest_path), '--dataset-root', str(self.root)])
        self.assertEqual(code, 2)
        self.assertFalse(json.loads(printed.getvalue())['valid'])
        with redirect_stdout(io.StringIO()) as printed:
            code = study.main(['freeze', '--manifest', str(self.manifest_path), '--dataset-root', str(self.root), '--output', str(self.output)])
        self.assertEqual(code, 2)
        self.assertIn('not ready to freeze', json.loads(printed.getvalue())['error'])
        self.assertFalse(self.output.exists())

    def single_speaker_fixture(self, aliases=1):
        """Constructed metadata only; no actual person or consent is created."""
        self.manifest['study_kind'] = 'single_speaker_school_question_pilot'
        self.manifest['speakers'] = self.manifest['speakers'][2:2 + aliases]
        self.manifest['clips'] = self.manifest['clips'][2:2 + aliases]
        for speaker in self.manifest['speakers']:
            speaker['speaker_group_id'] = 'one-constructed-person'
            speaker['consent_scope'] = 'evaluation_only'

    def test_single_speaker_confirmed_dev_freezes_as_diagnostic_not_training_or_test(self):
        self.single_speaker_fixture()
        report = self.validate()
        self.assertTrue(report['valid'], report['errors'])
        self.assertTrue(report['freeze_ready'], report['freeze_errors'])
        self.assertEqual(report['counts'], {'train': dict(clips=0, speakers=0),
            'dev': dict(clips=1, speakers=1), 'test': dict(clips=0, speakers=0)})
        self.assertEqual(report['required_splits'], ['dev'])
        study.freeze_manifest(self.manifest_path, self.root, self.output)
        frozen = json.loads(self.output.read_text(encoding='utf-8'))
        self.assertEqual(frozen['artifact_kind'], 'frozen_single_speaker_school_question_pilot')
        self.assertEqual(frozen['analysis_scope'], 'single_speaker_development')
        self.assertTrue(frozen['evaluation_only'])
        for key in ('speaker_independent', 'eligible_for_weight_training', 'heldout_test', 'general_accuracy_claim'):
            self.assertIs(frozen[key], False)
            self.assertIs(frozen['validation'][key], False)
        self.assertEqual(frozen['manifest'], self.manifest)
        self.assertEqual(frozen['source_manifest_sha256'], hashlib.sha256(self.manifest_path.read_bytes()).hexdigest())
        self.assertTrue(frozen['no_asr_performed'])
        self.assertTrue(frozen['no_transcript_created'])
        self.assertIsNone(frozen['measured_accuracy'])

    def test_single_speaker_aliases_remain_one_canonical_person(self):
        self.single_speaker_fixture(aliases=2)
        self.manifest['speakers'][1]['speaker_group_id'] = 'ONE-CONSTRUCTED-PERSON'
        report = self.validate()
        self.assertTrue(report['freeze_ready'], report['errors'])
        self.assertEqual(report['counts']['dev'], dict(clips=2, speakers=1))

    def test_single_speaker_rejects_another_declared_person_even_when_unused(self):
        self.single_speaker_fixture()
        self.manifest['speakers'].append(dict(speaker_id='unused-second-person',
            speaker_group_id='different-constructed-person', consent_scope='evaluation_only'))
        report = self.validate()
        self.assertFalse(report['valid'])
        self.assertIn('single_speaker_required', self.codes(report))
        with self.assertRaisesRegex(ValueError, 'single_speaker_required'):
            study.freeze_manifest(self.manifest_path, self.root, self.output)

    def test_single_speaker_cannot_put_the_same_person_in_train_or_test(self):
        self.single_speaker_fixture()
        for split in ('train', 'test', 'unknown', None, ['dev']):
            with self.subTest(split=split):
                self.manifest['clips'][0]['split'] = split
                report = self.validate()
                self.assertFalse(report['freeze_ready'])
                self.assertIn('single_speaker_dev_only', self.codes(report))

    def test_single_speaker_does_not_assume_training_consent(self):
        self.single_speaker_fixture()
        for consent in ('training_and_evaluation', None, ['evaluation_only'], True):
            with self.subTest(consent=consent):
                self.manifest['speakers'][0]['consent_scope'] = consent
                report = self.validate()
                self.assertFalse(report['freeze_ready'])
                self.assertIn('single_speaker_evaluation_only', self.codes(report))

    def test_single_speaker_still_requires_actual_clips_and_confirmed_reference(self):
        self.single_speaker_fixture()
        clip = self.manifest['clips'][0]
        clip['transcript_review']['confirmed'] = False
        self.assertIn('human_review_unconfirmed', self.codes(self.validate()))
        with self.assertRaisesRegex(ValueError, 'human_review_unconfirmed'):
            study.freeze_manifest(self.manifest_path, self.root, self.output)
        clip['transcript_review']['confirmed'] = True
        clip['transcript_review']['uncertainties'] = ['not yet listened']
        self.assertIn('unresolved_uncertainty', self.codes(self.validate()))
        self.manifest['clips'] = []
        report = self.validate()
        self.assertIn('clips_required', self.codes(report))
        self.assertFalse(report['freeze_ready'])
        self.assertFalse(self.output.exists())

    def test_single_speaker_cannot_count_duplicate_audio_twice(self):
        self.single_speaker_fixture(aliases=2)
        self.replace_audio(1, (self.root / self.manifest['clips'][0]['audio_path']).read_bytes())
        report = self.validate()
        self.assertIn('duplicate_audio', self.codes(report))
        self.assertFalse(report['freeze_ready'])

    def test_single_speaker_keeps_audio_integrity_and_no_overwrite_guards(self):
        self.single_speaker_fixture()
        self.replace_audio(0, b'not a WAV recording')
        self.assertIn('invalid_audio', self.codes(self.validate()))
        self.replace_audio(0, wav_bytes(value=93))
        self.save()
        study.freeze_manifest(self.manifest_path, self.root, self.output)
        before = self.output.read_bytes()
        with self.assertRaises(FileExistsError):
            study.freeze_manifest(self.manifest_path, self.root, self.output)
        self.assertEqual(self.output.read_bytes(), before)

    def test_one_person_does_not_silently_relax_multi_speaker_mode(self):
        self.single_speaker_fixture()
        self.manifest['study_kind'] = 'real_school_question_pilot'
        report = self.validate()
        self.assertTrue(report['valid'])
        self.assertFalse(report['freeze_ready'])
        self.assertEqual({row['path'] for row in report['freeze_errors']}, {'train', 'dev', 'test'})
        with self.assertRaisesRegex(ValueError, 'insufficient_split_speakers'):
            study.freeze_manifest(self.manifest_path, self.root, self.output)

    def test_multi_speaker_corpus_cannot_be_mislabeled_as_single_speaker(self):
        self.manifest['study_kind'] = 'single_speaker_school_question_pilot'
        report = self.validate()
        self.assertFalse(report['valid'])
        self.assertTrue({'single_speaker_required', 'single_speaker_dev_only',
                         'single_speaker_evaluation_only'}.issubset(self.codes(report)))

    def test_single_speaker_manifest_cannot_add_general_accuracy_or_training_claims(self):
        self.single_speaker_fixture()
        self.manifest.update(speaker_independent=True, eligible_for_weight_training=True,
                             heldout_test=True, general_accuracy_claim=True)
        report = self.validate()
        self.assertFalse(report['freeze_ready'])
        self.assertIn('unknown_field', self.codes(report))
        self.assertFalse(report['speaker_independent'])
        self.assertFalse(report['eligible_for_weight_training'])

    def test_single_speaker_validate_and_freeze_cli_use_same_explicit_mode(self):
        self.single_speaker_fixture(); self.save()
        args = ['--manifest', str(self.manifest_path), '--dataset-root', str(self.root)]
        with redirect_stdout(io.StringIO()) as printed:
            code = study.main(['validate'] + args)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(printed.getvalue())['analysis_scope'], 'single_speaker_development')
        with redirect_stdout(io.StringIO()) as printed:
            code = study.main(['freeze'] + args + ['--output', str(self.output)])
        self.assertEqual(code, 0)
        result = json.loads(printed.getvalue())
        self.assertIsNone(result['measured_accuracy'])
        self.assertEqual(result['artifact_kind'], 'frozen_single_speaker_school_question_pilot')
        self.assertEqual(result['analysis_scope'], 'single_speaker_development')
        self.assertFalse(result['speaker_independent'])
        self.assertFalse(result['eligible_for_weight_training'])
        self.assertFalse(result['heldout_test'])

    def test_unknown_mode_never_makes_one_speaker_freeze_ready(self):
        self.single_speaker_fixture()
        for kind in ('single_speaker', None, {'single': True}):
            with self.subTest(kind=kind):
                self.manifest['study_kind'] = kind
                report = self.validate()
                self.assertIn('study_kind', self.codes(report))
                self.assertFalse(report['freeze_ready'])


if __name__ == '__main__':
    unittest.main()
