"""Constructed offline contracts, never study audio, consent or ASR evidence."""
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from tools import compare_stt_candidate as candidate


def wav_bytes(value=1, frames=1600):
    """Constant PCM test samples are not human speech or an acoustic benchmark."""
    payload = struct.pack('<h', value) * frames
    fmt = struct.pack('<HHIIHH', 1, 1, 16000, 32000, 2, 16)
    chunks = b'fmt ' + struct.pack('<I', len(fmt)) + fmt
    chunks += b'data' + struct.pack('<I', len(payload)) + payload
    return b'RIFF' + struct.pack('<I', len(chunks) + 4) + b'WAVE' + chunks


class FakeRecognizer:
    def __init__(self, texts, *, fail_at=None, usage=None):
        self.texts = texts
        self.fail_at = fail_at
        self.calls = []
        self.usage = usage

    def transcribe(self, audio_bytes, *, display_name):
        self.calls.append((audio_bytes, display_name))
        if self.fail_at == len(self.calls):
            raise TimeoutError('PRIVATE fixture token must not leak')
        identity = display_name.removeprefix('clip-')
        return dict(text=self.texts[identity], model='constructed-offline-fake', usage=self.usage)


class FakeResponse(io.BytesIO):
    def __init__(self, value=b'', *, headers=None, status=200):
        data = value if isinstance(value, bytes) else json.dumps(value).encode('utf-8')
        super().__init__(data)
        self.headers = headers or {}
        self.status = status

    def getcode(self):
        return self.status


class ScriptedOpener:
    """In-memory HTTP script; never opens a socket or follows a redirect."""
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def open(self, request, timeout=None):
        self.calls.append((request, timeout))
        if not self.responses:
            raise AssertionError('Unexpected request or retry')
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response

    __call__ = open


class CandidateContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'runtime/fixture'
        self.source.mkdir(parents=True)
        self.manifest_path = self.source / 'manifest.json'
        self.packet = self.root / 'runtime/packet'
        self.run_dir = self.root / 'runtime/run'
        self.references = {}
        self.baseline_texts = {}
        rows = []
        # This constructed text has 186 words and 1089 non-space characters.
        # The fake baseline changes 67 tokens and 184 characters. These are
        # scorer fixtures, not copies of the user's private reference texts.
        words = ['a' * (6 if index < 159 else 5) for index in range(186)]
        hypotheses = [
            ('b' * (3 if index < 50 else 2) + word[(3 if index < 50 else 2):])
            if index < 67 else word
            for index, word in enumerate(words)
        ]
        offset = 0
        for index in range(13):
            identity = 'q' + str(index + 1).zfill(2)
            size = 15 if index < 4 else 14
            reference = ' '.join(words[offset:offset + size])
            self.references[identity] = reference
            self.baseline_texts[identity] = ' '.join(hypotheses[offset:offset + size])
            offset += size
            rows.append(self.row(identity, index + 1, reference))
        controls = [self.row('silence', 0, '', control='silence'),
                    self.row('noise', 19, '', control='noise')]
        self.references.update(silence='', noise='')
        self.baseline_texts.update(silence='', noise='')
        self.manifest = dict(schema_version=1, human_rows=rows, control_rows=controls,
                             fixture_notice='Constructed unit test only, not real participant data.')
        self.save()

    def row(self, identity, value, reference, control=None):
        path = self.source / (identity + '.wav')
        audio = wav_bytes(value)
        path.write_bytes(audio)
        row = dict(id=identity, audio_path=path.relative_to(self.root).as_posix(),
                   audio_sha256=hashlib.sha256(audio).hexdigest(), reference=reference,
                   reference_status='eligible_speaker_confirmed')
        if control:
            row.update(reference_status='synthetic_control', control_kind=control)
        return row

    def save(self):
        self.manifest_path.write_text(json.dumps(self.manifest, ensure_ascii=False), encoding='utf-8')

    def capture(self):
        self.save()
        return candidate.capture_manifest(self.manifest_path, root=self.root)

    def prepare(self, *, service_tier='paid'):
        self.save()
        return candidate.prepare(self.manifest_path, self.packet, root=self.root,
                                 service_tier=service_tier)

    def approval(self):
        approval = json.loads((self.packet / 'approval-template.json').read_text(encoding='utf-8'))
        approval.update(user_cloud_audio_upload_authorized=True,
                        user_paid_service_authorized=True,
                        paid_service_account_confirmed=True,
                        billing_project_id='constructed-paid-project',
                        billing_verified_at_utc='2026-10-29T10:00:00+00:00',
                        authorized_by='user', recorded_at_utc='2026-10-29T10:00:00+00:00',
                        authorization_note='Constructed test authorization, not real permission.',
                        max_transcription_attempts=15, max_estimated_cost_usd=0.10)
        path = self.source / 'constructed-approval.json'
        path.write_text(json.dumps(approval), encoding='utf-8')
        return path

    def free_approval(self):
        approval = json.loads((self.packet / 'approval-template.json').read_text(encoding='utf-8'))
        approval.update(user_cloud_audio_upload_authorized=True,
                        user_unpaid_data_terms_acknowledged=True,
                        free_service_account_confirmed=True,
                        free_service_verification_source='Constructed account-tier evidence, not a real verification.',
                        free_service_verified_at_utc='2026-10-30T10:00:00Z',
                        authorized_by='user', recorded_at_utc='2026-10-30T10:00:00Z',
                        authorization_note='Constructed free-tier consent only, not real permission.')
        path = self.source / 'constructed-free-approval.json'
        path.write_text(json.dumps(approval), encoding='utf-8')
        return path

    def execute(self, approval_path=None, *, baseline=None, transport=None, output=None, environ=None):
        self.fake_baseline = baseline or FakeRecognizer(self.baseline_texts)
        self.fake_candidate = transport or FakeRecognizer(self.references)
        return candidate.execute(
            self.manifest_path, self.packet, output or self.run_dir, approval_path,
            root=self.root, baseline_factory=lambda: self.fake_baseline,
            transport_factory=lambda api_key: self.fake_candidate,
            environ={'GEMINI_API_KEY': 'CONSTRUCTED-SECRET-KEY'} if environ is None else environ)

    def test_prepare_binds_exact_manifest_and_references_without_model_or_http(self):
        import builtins
        original_import = builtins.__import__

        def guarded_import(name, *args, **kwargs):
            if name.split('.')[0] in {'faster_whisper', 'torch', 'ctranslate2', 'stt_mn'}:
                raise AssertionError('Prepare imported a speech/model runtime: ' + name)
            return original_import(name, *args, **kwargs)

        with patch('builtins.__import__', side_effect=guarded_import), \
                patch('urllib.request.urlopen', side_effect=AssertionError('Prepare used HTTP')):
            protocol = self.prepare()
        expected = hashlib.sha256(self.manifest_path.read_bytes()).hexdigest()
        self.assertEqual(protocol['manifest_sha256'], expected)
        self.assertTrue((self.packet / 'human-review-template.json').is_file())
        approval = json.loads((self.packet / 'approval-template.json').read_text(encoding='utf-8'))
        self.assertIs(approval['user_cloud_audio_upload_authorized'], False)
        self.assertIs(approval['user_paid_service_authorized'], False)
        self.assertNotIn('CONSTRUCTED-SECRET-KEY', json.dumps(protocol))
        self.assertFalse(list(self.packet.rglob('*.wav')))

    def test_prepare_preserves_previous_packet(self):
        self.prepare()
        before = {path.name: path.read_bytes() for path in self.packet.iterdir() if path.is_file()}
        with self.assertRaises((FileExistsError, ValueError)):
            self.prepare()
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.packet.iterdir() if path.is_file()})

    def test_free_prepare_binds_tier_and_leaves_account_and_consent_unconfirmed(self):
        protocol = self.prepare(service_tier='free')
        approval = json.loads((self.packet / 'approval-template.json').read_text(encoding='utf-8'))
        self.assertEqual(protocol['service_tier'], 'free')
        self.assertEqual(protocol['service_tier_checked_date'], candidate.SERVICE_TIER_CHECKED_DATE)
        self.assertEqual(protocol['caps']['max_estimated_cost_usd'], 0)
        self.assertEqual(approval['max_estimated_cost_usd'], 0)
        self.assertFalse(approval['paid_fallback_allowed'])
        self.assertFalse(approval['user_unpaid_data_terms_acknowledged'])
        self.assertFalse(approval['free_service_account_confirmed'])
        self.assertIsNone(approval['free_service_verification_source'])
        self.assertGreater(protocol['pricing']['paid_equivalent_estimated_cost_usd'], 0)
        self.assertEqual(protocol['network_calls'], 0)

    def test_free_usage_has_paid_equivalent_estimate_but_no_claim_about_actual_bill(self):
        self.prepare(service_tier='free')
        recognizer = FakeRecognizer(self.references,
            usage=dict(total_input_tokens=12, total_output_tokens=4, total_tokens=16))
        state = self.execute(self.free_approval(), transport=recognizer)
        self.assertTrue(state['completed'])
        self.assertEqual(state['service_tier'], 'free')
        self.assertEqual(state['max_authorized_spend_usd'], 0)
        self.assertEqual(state['transcription_attempts'], 15)
        self.assertFalse(state['paid_fallback_allowed'])
        self.assertTrue(state['usage_complete'])
        self.assertAlmostEqual(state['paid_equivalent_token_cost_estimate_usd'], 0.00108)
        self.assertIsNone(state['observed_token_cost_estimate_usd'])
        self.assertIsNone(state['known_token_cost_estimate_usd'])
        self.assertIsNone(state['actual_billed_cost_usd'])
        summary = candidate.summarize(self.run_dir, root=self.root)
        self.assertEqual(summary['service_tier'], 'free')
        self.assertAlmostEqual(summary['paid_equivalent_token_cost_estimate_usd'], 0.00108)
        self.assertIsNone(summary['actual_billed_cost_usd'])
        self.assertFalse(summary['production_accepted'])

    def test_free_missing_usage_remains_unknown_cost(self):
        self.prepare(service_tier='free')
        state = self.execute(self.free_approval())
        self.assertTrue(state['completed'])
        self.assertFalse(state['usage_complete'])
        self.assertIsNone(state['paid_equivalent_token_cost_estimate_usd'])
        self.assertIsNone(state['known_paid_equivalent_token_cost_estimate_usd'])
        self.assertIsNone(state['actual_billed_cost_usd'])

    def test_free_missing_consent_tier_or_account_evidence_rejects_before_factories(self):
        self.prepare(service_tier='free')
        path = self.free_approval()
        valid = json.loads(path.read_text(encoding='utf-8'))
        fields = ('service_tier', 'user_cloud_audio_upload_authorized',
                  'user_unpaid_data_terms_acknowledged', 'free_service_account_confirmed',
                  'free_service_verification_source', 'free_service_verified_at_utc',
                  'paid_fallback_allowed', 'authorized_by', 'authorization_note', 'recorded_at_utc')
        for field in fields:
            with self.subTest(field=field):
                approval = dict(valid)
                approval.pop(field)
                path.write_text(json.dumps(approval), encoding='utf-8')
                baseline_factory, transport_factory = Mock(), Mock()
                with self.assertRaises(ValueError):
                    candidate.execute(self.manifest_path, self.packet, self.run_dir, path,
                        root=self.root, baseline_factory=baseline_factory,
                        transport_factory=transport_factory,
                        environ={'GEMINI_API_KEY': 'CONSTRUCTED-SECRET-KEY'})
                baseline_factory.assert_not_called()
                transport_factory.assert_not_called()
        self.assertFalse((self.packet / 'execution-claim.json').exists())

    def test_free_rejects_tier_drift_paid_fallback_spending_or_invalid_account_evidence(self):
        self.prepare(service_tier='free')
        path = self.free_approval()
        valid = json.loads(path.read_text(encoding='utf-8'))
        mutations = [('service_tier', 'paid'), ('service_tier', 'unknown'),
                     ('user_paid_service_authorized', True), ('paid_service_account_confirmed', True),
                     ('billing_project_id', 'constructed-paid-project'),
                     ('billing_verified_at_utc', '2026-10-30T10:00:00Z'),
                     ('paid_fallback_allowed', True), ('max_estimated_cost_usd', 0.01),
                     ('max_estimated_cost_usd', -0.01), ('max_estimated_cost_usd', 'NaN'),
                     ('free_service_verification_source', ' '),
                     ('free_service_verified_at_utc', '2026-10-30'),
                     ('free_service_verified_at_utc', '2026-10-30T10:00:00+08:00'),
                     ('manifest_sha256', '0' * 64), ('protocol_sha256', '0' * 64)]
        for field, value in mutations:
            with self.subTest(field=field, value=value):
                path.write_text(json.dumps(dict(valid, **{field: value})), encoding='utf-8')
                baseline_factory, transport_factory = Mock(), Mock()
                with self.assertRaises(ValueError):
                    candidate.execute(self.manifest_path, self.packet, self.run_dir, path,
                        root=self.root, baseline_factory=baseline_factory,
                        transport_factory=transport_factory,
                        environ={'GEMINI_API_KEY': 'CONSTRUCTED-SECRET-KEY'})
                baseline_factory.assert_not_called()
                transport_factory.assert_not_called()

    def test_legacy_missing_tier_still_requires_and_uses_paid_authorization(self):
        self.prepare()
        path = self.approval()
        protocol_path = self.packet / 'protocol.json'
        protocol = json.loads(protocol_path.read_text(encoding='utf-8'))
        for field in ('service_tier', 'service_tier_checked_date', 'paid_fallback_allowed'):
            protocol.pop(field)
        protocol_path.write_text(json.dumps(protocol), encoding='utf-8')
        approval = json.loads(path.read_text(encoding='utf-8'))
        approval.pop('service_tier')
        approval.pop('paid_fallback_allowed')
        approval['protocol_sha256'] = candidate.sha(protocol_path)
        path.write_text(json.dumps(approval), encoding='utf-8')
        state = self.execute(path)
        self.assertTrue(state['completed'])
        self.assertEqual(state['service_tier'], 'paid')
        self.assertEqual(candidate.summarize(self.run_dir, root=self.root)['service_tier'], 'paid')

    def test_audio_hash_drift_rejected_before_run(self):
        self.manifest['human_rows'][0]['audio_sha256'] = '0' * 64
        with self.assertRaises(ValueError):
            self.capture()

    def test_duplicate_id_is_rejected_case_insensitively(self):
        self.manifest['human_rows'][1]['id'] = self.manifest['human_rows'][0]['id'].upper()
        with self.assertRaises(ValueError):
            self.capture()

    def test_pending_reference_excluded_from_metrics_and_run(self):
        self.manifest['human_rows'][0]['reference_status'] = 'pending'
        with self.assertRaises(ValueError):
            self.capture()

    def test_synthetic_speech_cannot_enter_human_cohort(self):
        self.manifest['human_rows'][0]['reference_status'] = 'synthetic_control'
        self.manifest['human_rows'][0]['audio_origin'] = 'synthetic_speech'
        with self.assertRaises(ValueError):
            self.capture()

    def test_contradictory_synthetic_origin_cannot_override_confirmed_status(self):
        self.manifest['human_rows'][0]['audio_origin'] = 'synthetic_speech'
        with self.assertRaises(ValueError):
            self.capture()

    def test_more_than_thirteen_humans_rejected(self):
        self.manifest['human_rows'].append(self.row('q14', 21, 'fixture overflow'))
        with self.assertRaises(ValueError):
            self.capture()

    def test_more_than_two_nonspeech_controls_rejected(self):
        self.manifest['control_rows'].append(self.row('noise2', 23, '', control='noise'))
        with self.assertRaises(ValueError):
            self.capture()

    def test_synthetic_speech_control_is_not_nonspeech(self):
        self.manifest['control_rows'][0].update(control_kind='synthetic_speech', reference='spoken fixture')
        with self.assertRaises(ValueError):
            self.capture()

    def test_nonspeech_control_cannot_hide_nonempty_reference(self):
        self.manifest['control_rows'][0]['reference'] = 'not silence'
        with self.assertRaises(ValueError):
            self.capture()

    def test_paths_cannot_escape_supplied_root(self):
        self.manifest['human_rows'][0]['audio_path'] = '../outside.wav'
        with self.assertRaises(ValueError):
            self.capture()

    def test_missing_permission_rejects_before_any_provider(self):
        self.prepare()
        with self.assertRaises((ValueError, FileNotFoundError, TypeError)):
            self.execute()
        self.assertEqual(self.fake_baseline.calls, [])
        self.assertEqual(self.fake_candidate.calls, [])

    def test_changed_manifest_after_prepare_rejects_before_provider(self):
        self.prepare()
        approval = self.approval()
        self.manifest['human_rows'][0]['reference'] += ' changed'
        self.save()
        with self.assertRaises(ValueError):
            self.execute(approval)
        self.assertEqual(self.fake_candidate.calls, [])
        self.assertEqual(self.fake_baseline.calls, [])

    def test_wrong_permission_bindings_and_budgets_cannot_use_http(self):
        self.prepare()
        path = self.approval()
        valid = json.loads(path.read_text(encoding='utf-8'))
        mutations = [
            ('manifest_sha256', '0' * 64), ('protocol_sha256', '0' * 64),
            ('model', 'different-model'), ('max_transcription_attempts', 16),
            ('max_estimated_cost_usd', 0.11), ('max_estimated_cost_usd', -1),
            ('user_cloud_audio_upload_authorized', False),
            ('user_paid_service_authorized', False), ('authorized_by', 'agent'),
        ]
        for field, value in mutations:
            with self.subTest(field=field, value=value):
                approval = dict(valid, **{field: value})
                path.write_text(json.dumps(approval), encoding='utf-8')
                with self.assertRaises(ValueError):
                    self.execute(path)
                self.assertEqual(self.fake_candidate.calls, [])
                self.assertEqual(self.fake_baseline.calls, [])
        self.assertFalse(self.run_dir.exists())

    def test_missing_api_key_does_not_start_either_arm(self):
        self.prepare()
        with self.assertRaises(ValueError):
            self.execute(self.approval(), environ={})
        self.assertEqual(self.fake_candidate.calls, [])
        self.assertEqual(self.fake_baseline.calls, [])

    def test_reference_is_never_a_recognizer_argument(self):
        self.prepare()
        self.execute(self.approval())
        self.assertEqual(len(self.fake_candidate.calls), 15)
        for recognizer in (self.fake_baseline, self.fake_candidate):
            for audio, name in recognizer.calls:
                self.assertIsInstance(audio, bytes)
                self.assertTrue(audio.startswith(b'RIFF'))
                self.assertTrue(name.startswith('clip-'))
                self.assertNotIn('aaaaa', name)
                self.assertNotIn(str(self.root), name)

    def test_complete_offline_run_recounts_frozen_denominators_and_keeps_review_pending(self):
        self.prepare()
        state = self.execute(self.approval())
        self.assertIs(state['completed'], True)
        self.assertEqual(state['transcription_attempts'], 15)
        self.assertEqual(state['network_calls'], 0)
        summary = candidate.summarize(self.run_dir, root=self.root)
        baseline = summary['human_metrics']['baseline']
        actual = {key: baseline[key] for key in ('reference_words', 'reference_characters',
                                                'word_edit_errors', 'character_edit_errors')}
        self.assertEqual(actual, dict(reference_words=186, reference_characters=1089,
                                      word_edit_errors=67, character_edit_errors=184))
        self.assertAlmostEqual(baseline['corpus_wer'], 67 / 186)
        self.assertAlmostEqual(baseline['corpus_cer'], 184 / 1089)
        self.assertEqual(summary['human_metrics']['candidate']['word_edit_errors'], 0)
        self.assertEqual(summary['quality_status'], 'pending_human_review')
        self.assertIs(summary['human_review_complete'], False)
        self.assertIsNone(summary['critical_new_errors'])
        self.assertIsNone(summary['task_success_no_regression'])
        self.assertIs(summary['production_accepted'], False)
        self.assertEqual(len(summary['nonspeech_results']), 2)
        self.assertEqual(baseline['utterances'], 13)

    def test_provider_failure_stops_once_and_incomplete_run_has_no_aggregate(self):
        self.prepare()
        failing = FakeRecognizer(self.references, fail_at=2)
        state = self.execute(self.approval(), transport=failing)
        self.assertIs(state['completed'], False)
        self.assertEqual(state['transcription_attempts'], 2)
        self.assertEqual(len(failing.calls), 2)
        self.assertEqual(len(self.fake_baseline.calls), 2)
        summary = candidate.summarize(self.run_dir, root=self.root)
        self.assertIsNone(summary['human_metrics'])
        self.assertEqual(summary['quality_status'], 'incomplete_no_aggregate')
        self.assertIs(summary['production_accepted'], False)
        self.assertNotIn('PRIVATE', json.dumps(state))
        self.assertNotIn('PRIVATE', (self.run_dir / 'results.jsonl').read_text(encoding='utf-8'))
        with self.assertRaises(FileExistsError):
            self.execute(self.approval(), transport=failing)
        self.assertEqual(len(failing.calls), 2)

    def test_nonspeech_false_accept_is_separate_from_human_wer(self):
        self.prepare()
        texts = dict(self.references, silence='invented spoken content')
        self.execute(self.approval(), transport=FakeRecognizer(texts))
        summary = candidate.summarize(self.run_dir, root=self.root)
        self.assertEqual(summary['human_metrics']['candidate']['word_edit_errors'], 0)
        self.assertEqual(summary['human_metrics']['candidate']['reference_words'], 186)
        silence = next(row for row in summary['nonspeech_results'] if row['id'] == 'silence')
        self.assertIs(silence['candidate_false_accept'], True)
        self.assertEqual(summary['quality_status'], 'rejected_by_predeclared_criteria')

    def test_unfilled_review_template_cannot_become_human_acceptance(self):
        self.prepare()
        self.execute(self.approval())
        template = self.run_dir / 'human-review-template.json'
        review = json.loads(template.read_text(encoding='utf-8'))
        review.update(human_review_complete=True, reviewer='constructed reviewer',
                      reviewed_at_utc='2026-10-29T10:01:00+00:00')
        (self.run_dir / 'human-review.json').write_text(json.dumps(review), encoding='utf-8')
        summary = candidate.summarize(self.run_dir, root=self.root)
        self.assertIs(summary['human_review_complete'], False)
        self.assertEqual(summary['quality_status'], 'pending_human_review')

    def test_completed_run_evidence_drift_is_rejected(self):
        self.prepare()
        self.execute(self.approval())
        results = self.run_dir / 'results.jsonl'
        results.write_text(results.read_text(encoding='utf-8') + '\n', encoding='utf-8')
        with self.assertRaises(ValueError):
            candidate.summarize(self.run_dir, root=self.root)

    def test_transport_payload_contains_only_file_and_literal_transcription_policy(self):
        payload = candidate.build_request('https://generativelanguage.googleapis.com/v1beta/files/fixture')
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn('expected_answer', serialized)
        self.assertNotIn('reference', serialized)
        self.assertNotIn('aaaaa', serialized)
        self.assertNotIn('CONSTRUCTED-SECRET-KEY', serialized)
        self.assertIn('fixture', serialized)

    def test_google_credentials_cannot_be_sent_to_other_hosts(self):
        for url in ('http://generativelanguage.googleapis.com/v1beta/files/a',
                    'https://evil.invalid/v1beta/files/a',
                    'https://generativelanguage.googleapis.com.evil.invalid/v1beta/files/a',
                    'https://generativelanguage.googleapis.com@evil.invalid/v1beta/files/a',
                    'https://generativelanguage.googleapis.com:444/v1beta/files/a'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                candidate.validate_url(url)

    def test_error_sanitization_never_exposes_exception_message(self):
        result = candidate.sanitized_error(RuntimeError('PRIVATE_TOKEN full/path audio contents'))
        rendered = json.dumps(result)
        for secret in ('PRIVATE_TOKEN', 'full/path', 'audio contents'):
            self.assertNotIn(secret, rendered)

    def transport_script(self, *, response=None, upload_url=None):
        model = getattr(candidate, 'MODEL', 'gemini-3.5-transcribe')
        response = response or dict(status='completed', model=model,
            steps=[dict(type='model_output', content=[dict(type='text', text='2026 4')])],
            usage=dict(total_input_tokens=12, total_output_tokens=4, total_tokens=16))
        return ScriptedOpener([
            FakeResponse(headers={'X-Goog-Upload-URL': upload_url or
                'https://generativelanguage.googleapis.com/upload/v1beta/files?upload_id=fixture'}),
            FakeResponse(dict(file=dict(name='files/fixture',
                uri='https://generativelanguage.googleapis.com/v1beta/files/fixture',
                mimeType='audio/wav', state='ACTIVE'))),
            FakeResponse(response), FakeResponse(b'')])

    def test_rest_adapter_parses_documented_interaction_steps_and_preserves_numbers(self):
        opener = self.transport_script()
        adapter = candidate.GeminiTransport('CONSTRUCTED-SECRET-KEY', opener=opener)
        result = adapter.transcribe(wav_bytes(), display_name='clip-fixture')
        self.assertEqual(result['text'], '2026 4')
        requests = [request for request, _ in opener.calls]
        interactions = [request for request in requests if request.full_url.endswith('/interactions')]
        self.assertEqual(len(interactions), 1)
        payload = json.loads(interactions[0].data)
        self.assertIs(payload['store'], False)
        self.assertEqual(payload['generation_config']['transcription_config']['mode'], {'type': 'verbatim'})
        self.assertNotIn('CONSTRUCTED-SECRET-KEY', interactions[0].full_url)
        self.assertNotIn('CONSTRUCTED-SECRET-KEY', json.dumps(payload))
        self.assertNotIn('reference', json.dumps(payload))
        self.assertEqual(requests[-1].get_method(), 'DELETE')
        self.assertTrue(all(timeout is not None and timeout <= 60 for _, timeout in opener.calls))

    def test_free_quota_failure_stops_once_without_paid_fallback_or_aggregate(self):
        self.prepare(service_tier='free')
        opener = self.transport_script()
        opener.responses[2] = HTTPError(
            'https://generativelanguage.googleapis.com/v1beta/interactions',
            429, 'PRIVATE fixture quota body', {}, io.BytesIO(b'PRIVATE fixture quota body'))
        adapter = candidate.GeminiTransport('CONSTRUCTED-SECRET-KEY', opener=opener)
        state = self.execute(self.free_approval(), transport=adapter)
        self.assertFalse(state['completed'])
        self.assertEqual(state['error'], 'http_429')
        self.assertEqual(state['transcription_attempts'], 1)
        self.assertEqual(len(self.fake_baseline.calls), 1)
        self.assertEqual(len(opener.calls), 4)  # start, upload, one inference, delete
        self.assertEqual(sum(request.full_url.endswith('/interactions')
                             for request, _ in opener.calls), 1)
        self.assertEqual(opener.calls[-1][0].get_method(), 'DELETE')
        self.assertFalse(state['paid_fallback_allowed'])
        self.assertIsNone(state['actual_billed_cost_usd'])
        summary = candidate.summarize(self.run_dir, root=self.root)
        self.assertEqual(summary['service_tier'], 'free')
        self.assertEqual(summary['quality_status'], 'incomplete_no_aggregate')
        self.assertIsNone(summary['human_metrics'])
        self.assertFalse(summary['production_accepted'])
        self.assertNotIn('PRIVATE', (self.run_dir / 'results.jsonl').read_text(encoding='utf-8'))

    def test_untrusted_upload_url_rejected_before_audio_or_key_forwarding(self):
        opener = self.transport_script(upload_url='https://evil.invalid/upload')
        adapter = candidate.GeminiTransport('CONSTRUCTED-SECRET-KEY', opener=opener)
        with self.assertRaises((ValueError, candidate.CandidateError)):
            adapter.transcribe(wav_bytes(), display_name='clip-fixture')
        self.assertEqual(len(opener.calls), 1)

    def test_http_redirect_is_not_retried_or_parsed_as_transcription(self):
        redirect = HTTPError('https://generativelanguage.googleapis.com/upload/v1beta/files',
                             302, 'PRIVATE_TOKEN', {'Location': 'https://evil.invalid'}, io.BytesIO(b''))
        opener = ScriptedOpener([redirect])
        adapter = candidate.GeminiTransport('CONSTRUCTED-SECRET-KEY', opener=opener)
        with self.assertRaises((HTTPError, ValueError, RuntimeError)):
            adapter.transcribe(wav_bytes(), display_name='clip-fixture')
        self.assertEqual(len(opener.calls), 1)

    def test_incomplete_rest_output_cannot_become_successful_raw_text(self):
        opener = self.transport_script(response=dict(status='incomplete',
            steps=[dict(type='model_output', content=[dict(type='text', text='partial')])]))
        adapter = candidate.GeminiTransport('CONSTRUCTED-SECRET-KEY', opener=opener)
        with self.assertRaises((ValueError, RuntimeError)):
            adapter.transcribe(wav_bytes(), display_name='clip-fixture')
        self.assertEqual(sum(request.full_url.endswith('/interactions') for request, _ in opener.calls), 1)

    def test_numbers_are_not_silently_rewritten_for_raw_scores(self):
        from score import score
        result = score([dict(id='constructed-number', reference='2026 4', hypothesis='хоёр мянга хорин зургаа дөрөв')])
        self.assertGreater(result['word_edit_errors'], 0)
        self.assertGreater(result['character_edit_errors'], 0)

    def test_approval_packet_cannot_be_reused_to_reset_request_budget(self):
        self.prepare()
        approval = self.approval()
        self.execute(approval)
        calls = len(self.fake_candidate.calls)
        with self.assertRaises(FileExistsError):
            candidate.execute(self.manifest_path, self.packet, self.root / 'runtime/second-run',
                approval, root=self.root, baseline_factory=lambda: self.fake_baseline,
                transport_factory=lambda key: self.fake_candidate,
                environ={'GEMINI_API_KEY': 'CONSTRUCTED-SECRET-KEY'})
        self.assertEqual(len(self.fake_candidate.calls), calls)

    def test_complete_run_exports_bound_rag_inputs_without_rag_inference(self):
        self.prepare()
        self.execute(self.approval())
        value = json.loads((self.run_dir / 'rag-inputs.json').read_text(encoding='utf-8'))
        self.assertEqual(value['rag_calls'], 0)
        self.assertEqual(len(value['rows']), 13)
        self.assertEqual(value['results_sha256'], candidate.sha(self.run_dir / 'results.jsonl'))
        self.assertEqual(value['run_sha256'], candidate.sha(self.run_dir / 'run.json'))
        self.assertEqual(value['rows'][0]['typed'], self.manifest['human_rows'][0]['reference'])
        summary = candidate.summarize(self.run_dir, root=self.root)
        self.assertEqual(len(summary['paired_elapsed_seconds']), 13)
        self.assertGreaterEqual(summary['candidate_max_elapsed_seconds'],
                                summary['candidate_median_elapsed_seconds'])

    def test_output_at_token_limit_cannot_be_scored_as_complete(self):
        response = dict(model=candidate.MODEL, status='completed',
            usage=dict(total_output_tokens=candidate.MAX_OUTPUT_TOKENS),
            output_text='possibly truncated')
        with self.assertRaises(candidate.CandidateError):
            candidate.parse_interaction(response)
        response['usage'] = dict(total_output_tokens=1)
        response['finish_reason'] = 'MAX_TOKENS'
        with self.assertRaises(candidate.CandidateError):
            candidate.parse_interaction(response)

    def test_agent_ratings_cannot_become_human_acceptance(self):
        self.prepare()
        self.execute(self.approval())
        value = json.loads((self.run_dir / 'bound-human-review-template.json').read_text(encoding='utf-8'))
        value.update(human_review_complete=True, reviewer='AI fixture',
                     reviewed_at_utc='2026-10-29T10:00:00Z', judgments_origin='ai')
        for row in value['records']:
            row.update(critical_slots=[], critical_new_errors=0, typed_task_success=True,
                       baseline_task_success=True, candidate_task_success=True)
        (self.run_dir / 'human-review.json').write_text(json.dumps(value), encoding='utf-8')
        summary = candidate.summarize(self.run_dir, root=self.root)
        self.assertFalse(summary['human_review_complete'])
        self.assertEqual(summary['quality_status'], 'pending_human_review')

    def test_full_158_second_packet_stays_within_estimated_budget(self):
        cost = candidate.estimated_cost(158, 15)
        self.assertLessEqual(cost, candidate.MAX_COST_USD)
        self.assertAlmostEqual(float(cost), 0.0943)

    def test_word_error_types_recount_substitution_deletion_insertion(self):
        self.assertEqual(candidate.edit_counts('a b c', 'a z c'), dict(S=1, D=0, I=0))
        self.assertEqual(candidate.edit_counts('a b c', 'a c'), dict(S=0, D=1, I=0))
        self.assertEqual(candidate.edit_counts('a c', 'a b c'), dict(S=0, D=0, I=1))

    def test_critical_values_must_exist_in_the_frozen_reference(self):
        self.manifest['human_rows'][0]['critical_slots'] = [dict(field='year', expected='2026')]
        with self.assertRaises(ValueError):
            self.capture()

    def test_paid_permission_alone_does_not_prove_a_paid_account(self):
        self.prepare()
        path = self.approval()
        valid = json.loads(path.read_text(encoding='utf-8'))
        for changes in [dict(paid_service_account_confirmed=False), dict(billing_project_id=None),
                        dict(billing_verified_at_utc=None), dict(billing_verified_at_utc='2026-10-29')]:
            path.write_text(json.dumps(dict(valid, **changes)), encoding='utf-8')
            with self.assertRaises(ValueError):
                self.execute(path)
            self.assertEqual(self.fake_candidate.calls, [])
            self.assertEqual(self.fake_baseline.calls, [])

    def test_missing_usage_means_unknown_cost_instead_of_zero(self):
        self.prepare()
        state = self.execute(self.approval())
        self.assertFalse(state['usage_complete'])
        self.assertIsNone(state['observed_token_cost_estimate_usd'])
        self.assertIsNone(state['actual_billed_cost_usd'])


if __name__ == '__main__':
    unittest.main()
