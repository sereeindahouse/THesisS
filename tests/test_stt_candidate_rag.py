"""Constructed downstream contracts; no study data, model inference or sockets."""
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from tools import evaluate_stt_candidate_rag as evaluation


CODE_FILES = ('rag_runtime.py', 'source_fields.py', 'website_retrieval.py', 'sqlite_retrieval.py')
CORPUS_FILES = ('CORE/database/website.db', 'runtime/content.db')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True) + '\n', encoding='utf-8')


class FakeTransport:
    """Only returns in-memory metadata and constructed route responses."""
    def __init__(self, status, *, fail_at=None, status_change_at=None, response_change_at=None,
                 status_change=None, response_change=None, after_route=None):
        self.status = deepcopy(status)
        self.fail_at = fail_at
        self.status_change_at = status_change_at
        self.response_change_at = response_change_at
        self.status_change = status_change
        self.response_change = response_change
        self.after_route = after_route
        self.calls = []
        self.route_payloads = []
        self.status_calls = 0
        self.network_calls = 0

    def request(self, method, path, payload=None):
        self.calls.append((method, path, deepcopy(payload)))
        self.network_calls += 1
        if method == 'GET' and path == '/api/status':
            self.status_calls += 1
            value = deepcopy(self.status)
            if self.status_change_at == self.status_calls:
                self.status_change(value)
            return value
        if method != 'POST' or path != '/api/route':
            raise AssertionError('Unexpected endpoint in constructed transport')
        self.route_payloads.append(deepcopy(payload))
        if self.fail_at == len(self.route_payloads):
            raise TimeoutError('PRIVATE_PASSWORD must not reach evidence logs')
        query = payload['query']
        value = dict(route='E', answer='Constructed abstention, not a judged answer.',
            package_id=self.status['content_release']['package_id'],
            content_release=deepcopy(self.status['content_release']),
            conversation=dict(applied=False, reason='fresh_query', raw_query=query,
                              resolved_query=query, clarification_id='constructed-not-reused'),
            rag=dict(corpus_id=self.status['content_release']['corpus_id']))
        if self.response_change_at == len(self.route_payloads):
            self.response_change(value)
        if self.after_route:
            self.after_route(len(self.route_payloads))
        return value


class PairedRAGContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'runtime/constructed-stt-run'
        self.source.mkdir(parents=True)
        self.packet = self.root / 'runtime/constructed-rag-packet'
        self.output = self.root / 'runtime/constructed-rag-run'
        for name in CODE_FILES + CORPUS_FILES:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(('Constructed binding only: ' + name).encode())
        self.binding = dict(code_sha256={n: digest(self.root / n) for n in CODE_FILES},
                            corpus_sha256={n: digest(self.root / n) for n in CORPUS_FILES})
        self.manifest = dict(schema_version=1, human_rows=[], control_rows=[])
        self.raw = []
        self.inputs = dict(schema_version=1, rag_binding=deepcopy(self.binding),
                           rag_calls=0, human_review_complete=False, rows=[])
        for index in range(13):
            identity = 'constructed-' + str(index).zfill(2)
            sha = hashlib.sha256(identity.encode()).hexdigest()
            reference = 'constructed typed question ' + str(index)
            baseline = 'constructed baseline question ' + str(index)
            candidate = 'constructed candidate question ' + str(index)
            self.manifest['human_rows'].append(dict(id=identity, audio_sha256=sha,
                reference=reference, reference_status='eligible_speaker_confirmed'))
            self.raw.append(dict(id=identity, group='human', kind='human_speech',
                audio_sha256=sha, baseline=dict(text=baseline, error=None),
                candidate=dict(text=candidate, error=None)))
            self.inputs['rows'].append(dict(id=identity, audio_sha256=sha, typed=reference,
                baseline_raw=baseline, candidate_raw=candidate))
        self.protocol = dict(schema_version=1, model='gemini-3.5-transcribe',
                             study='Constructed fixture only, not an ASR result.')
        self.state = dict(schema_version=1, model='gemini-3.5-transcribe', completed=True,
                          completed_recordings=13, error=None, training_performed=False,
                          production_accepted=False)
        self.rebind()
        self.status = dict(mode='local_development', content_database_readonly=True,
            content_release=dict(release_id='constructed-release', corpus_id='constructed-corpus',
                                 package_id='constructed-package', activation_token='PRIVATE-CAPABILITY'),
            rag=dict(provider=dict(provider='ollama_local', configured=True, available=True,
                                   model='constructed-local-model', llm_calls=0),
                     retrieval=dict(corpus_id='constructed-corpus'),
                     loaded_artifact_sha256=deepcopy(self.binding['code_sha256'])))

    def rebind(self):
        write_json(self.source / 'manifest-snapshot.json', self.manifest)
        self.protocol['manifest_sha256'] = digest(self.source / 'manifest-snapshot.json')
        write_json(self.source / 'protocol.json', self.protocol)
        (self.source / 'results.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in self.raw), encoding='utf-8')
        self.state.update(protocol_sha256=digest(self.source / 'protocol.json'),
                          manifest_sha256=digest(self.source / 'manifest-snapshot.json'),
                          results_sha256=digest(self.source / 'results.jsonl'))
        write_json(self.source / 'run.json', self.state)
        self.inputs.update(protocol_sha256=digest(self.source / 'protocol.json'),
                           run_sha256=digest(self.source / 'run.json'),
                           results_sha256=digest(self.source / 'results.jsonl'))
        write_json(self.source / 'rag-inputs.json', self.inputs)

    def prepare(self):
        return evaluation.prepare(self.source, self.packet, root=self.root)

    def run_evaluation(self, transport=None):
        self.transport = transport or FakeTransport(self.status)
        return evaluation.run(self.source, self.packet, self.output, root=self.root,
                              transport=self.transport)

    def test_prepare_is_offline_and_keeps_sources_unchanged(self):
        before = {p.name: p.read_bytes() for p in self.source.iterdir()}
        with patch('urllib.request.urlopen', side_effect=AssertionError('Unexpected HTTP')):
            result = self.prepare()
        self.assertIsInstance(result, dict)
        self.assertTrue((self.packet / 'protocol.json').is_file())
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.source.iterdir()})
        self.assertFalse(list(self.packet.rglob('*.wav')))

    def test_prepare_preserves_an_existing_packet(self):
        self.prepare()
        before = {p.name: p.read_bytes() for p in self.packet.iterdir()}
        with self.assertRaises((FileExistsError, ValueError)):
            self.prepare()
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.packet.iterdir()})

    def test_incomplete_stt_run_has_no_downstream_calls(self):
        self.state['completed'] = False
        self.rebind()
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertFalse(self.packet.exists())

    def test_raw_results_hash_drift_is_rejected(self):
        with (self.source / 'results.jsonl').open('a', encoding='utf-8') as stream:
            stream.write('\n')
        with self.assertRaises(ValueError):
            self.prepare()

    def test_source_typed_text_must_match_frozen_reference(self):
        self.inputs['rows'][0]['typed'] = 'different constructed reference'
        self.rebind()
        with self.assertRaises(ValueError):
            self.prepare()

    def test_source_candidate_text_must_match_raw_output(self):
        self.inputs['rows'][0]['candidate_raw'] = 'silently edited candidate text'
        self.rebind()
        with self.assertRaises(ValueError):
            self.prepare()

    def test_duplicate_human_id_cannot_change_denominator(self):
        self.inputs['rows'][1]['id'] = self.inputs['rows'][0]['id']
        self.rebind()
        with self.assertRaises(ValueError):
            self.prepare()

    def test_more_than_one_thousand_characters_is_rejected_without_truncation(self):
        text = 'x' * 1001
        self.inputs['rows'][0]['candidate_raw'] = text
        self.raw[0]['candidate']['text'] = text
        self.rebind()
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertEqual(json.loads((self.source / 'rag-inputs.json').read_text())['rows'][0]['candidate_raw'], text)

    def test_local_corpus_drift_stops_before_http(self):
        self.prepare()
        (self.root / CORPUS_FILES[0]).write_bytes(b'Changed constructed corpus')
        transport = FakeTransport(self.status)
        try:
            state = self.run_evaluation(transport)
        except ValueError:
            state = dict(completed=False)
        self.assertFalse(state['completed'])
        self.assertEqual(transport.calls, [])

    def test_prepared_source_changed_stops_before_http(self):
        self.prepare()
        self.inputs['extra'] = 'Changed after freeze'
        self.rebind()
        transport = FakeTransport(self.status)
        try:
            state = self.run_evaluation(transport)
        except ValueError:
            state = dict(completed=False)
        self.assertFalse(state['completed'])
        self.assertEqual(transport.calls, [])

    def test_complete_three_arm_pass_is_fresh_balanced_and_bounded(self):
        self.prepare()
        state = self.run_evaluation()
        self.assertTrue(state['completed'])
        self.assertEqual(len(self.transport.route_payloads), 39)
        self.assertEqual(state['route_attempts'], 39)
        self.assertTrue(all(set(p) == {'query', 'allow_draft'} and p['allow_draft'] is False
                            for p in self.transport.route_payloads))
        first = [p['query'].split()[1] for p in self.transport.route_payloads[0:3]]
        second = [p['query'].split()[1] for p in self.transport.route_payloads[3:6]]
        third = [p['query'].split()[1] for p in self.transport.route_payloads[6:9]]
        self.assertEqual(first, ['typed', 'baseline', 'candidate'])
        self.assertEqual(second, ['baseline', 'candidate', 'typed'])
        self.assertEqual(third, ['candidate', 'typed', 'baseline'])
        self.assertTrue(all(path in {'/api/status', '/api/route'} for _, path, _ in self.transport.calls))

    def test_empty_raw_text_is_recorded_without_a_route_call(self):
        self.inputs['rows'][0]['candidate_raw'] = ''
        self.raw[0]['candidate']['text'] = ''
        self.rebind()
        self.prepare()
        state = self.run_evaluation()
        self.assertTrue(state['completed'])
        self.assertEqual(len(self.transport.route_payloads), 38)
        records = [json.loads(line) for line in (self.output / 'results.jsonl').read_text().splitlines()]
        empty = [r for r in records if r['id'] == 'constructed-00' and r['arm'] == 'candidate_raw']
        self.assertEqual(len(empty), 1)
        self.assertEqual(empty[0]['status'], 'no_question')
        self.assertIsNone(empty[0]['response'])

    def test_provider_failure_stops_once_and_does_not_create_accuracy(self):
        self.prepare()
        state = self.run_evaluation(FakeTransport(self.status, fail_at=4))
        self.assertFalse(state['completed'])
        self.assertEqual(len(self.transport.route_payloads), 4)
        summary = evaluation.summarize(self.output, root=self.root)
        self.assertFalse(summary['completed'])
        self.assertIsNone(summary['task_accuracy'])
        for path in self.output.iterdir():
            if path.is_file():
                self.assertNotIn('PRIVATE_PASSWORD', path.read_text(encoding='utf-8'))

    def test_stale_loaded_code_prevents_the_first_route_call(self):
        self.prepare()
        status = deepcopy(self.status)
        status['rag']['loaded_artifact_sha256'][CODE_FILES[0]] = '0' * 64
        state = self.run_evaluation(FakeTransport(status))
        self.assertFalse(state['completed'])
        self.assertEqual(self.transport.route_payloads, [])

    def test_release_change_stops_before_next_route_call(self):
        self.prepare()
        def change(value):
            value['content_release']['activation_token'] = 'different-private-release'
        state = self.run_evaluation(FakeTransport(self.status, status_change_at=2, status_change=change))
        self.assertFalse(state['completed'])
        self.assertLess(len(self.transport.route_payloads), 39)

    def test_model_change_stops_before_next_route_call(self):
        self.prepare()
        def change(value):
            value['rag']['provider']['model'] = 'different-local-model'
        state = self.run_evaluation(FakeTransport(self.status, status_change_at=2, status_change=change))
        self.assertFalse(state['completed'])
        self.assertLess(len(self.transport.route_payloads), 39)

    def test_corpus_drift_after_one_route_preserves_partial_run(self):
        self.prepare()
        def change(index):
            if index == 1:
                (self.root / CORPUS_FILES[1]).write_bytes(b'Changed mid-pass')
        state = self.run_evaluation(FakeTransport(self.status, after_route=change))
        self.assertFalse(state['completed'])
        self.assertEqual(len(self.transport.route_payloads), 1)
        self.assertTrue((self.output / 'results.jsonl').is_file())

    def test_clarification_context_cannot_be_applied_to_fresh_queries(self):
        self.prepare()
        def change(value):
            value['conversation']['applied'] = True
        state = self.run_evaluation(FakeTransport(self.status, response_change_at=1, response_change=change))
        self.assertFalse(state['completed'])
        self.assertEqual(len(self.transport.route_payloads), 1)

    def test_response_release_cannot_differ_from_frozen_status(self):
        self.prepare()
        def change(value):
            value['content_release']['release_id'] = 'changed-response-release'
        state = self.run_evaluation(FakeTransport(self.status, response_change_at=2, response_change=change))
        self.assertFalse(state['completed'])
        self.assertEqual(len(self.transport.route_payloads), 2)

    def test_complete_outputs_without_real_ratings_remain_pending(self):
        self.prepare()
        self.run_evaluation()
        summary = evaluation.summarize(self.output, root=self.root)
        self.assertTrue(summary['completed'])
        self.assertEqual(summary['quality_status'], 'pending_human_review')
        self.assertFalse(summary['human_review_complete'])
        self.assertIsNone(summary['task_accuracy'])

    def test_only_fixed_loopback_routes_can_be_addressed(self):
        for url in ['https://evil.invalid/api/route', 'http://localhost:8765/api/route',
                    'http://127.0.0.1:80/api/route', 'http://127.0.0.1:8765/api/voice/transcribe',
                    'http://127.0.0.1:8765/api/admin/publish',
                    'http://user@127.0.0.1:8765/api/status',
                    'http://127.0.0.1:8765/api/route?token=private',
                    'http://127.0.0.1:8765/api/status#fragment']:
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    evaluation.validate_url(url)
        self.assertEqual(evaluation.validate_url('http://127.0.0.1:8765/api/status'),
                         'http://127.0.0.1:8765/api/status')

    def test_post_run_rubric_edits_cannot_change_preregistered_reference(self):
        self.prepare()
        self.run_evaluation()
        path = self.output / 'rubric-snapshot.json'
        rubric = json.loads(path.read_text(encoding='utf-8'))
        rubric['records'][0]['task_applicable'] = True
        write_json(path, rubric)
        with self.assertRaises(ValueError):
            evaluation.summarize(self.output, root=self.root)

    def test_saved_server_snapshot_drift_cannot_relabel_the_evaluation_version(self):
        self.prepare()
        self.run_evaluation()
        path = self.output / 'server-snapshot.json'
        snapshot = json.loads(path.read_text(encoding='utf-8'))
        snapshot['content_release']['release_id'] = 'changed-after-run'
        write_json(path, snapshot)
        with self.assertRaises(ValueError):
            evaluation.summarize(self.output, root=self.root)

    def test_simulated_human_ratings_cannot_fill_missing_reference_labels(self):
        self.prepare()
        self.run_evaluation()
        review = json.loads((self.output / 'bound-human-review-template.json').read_text(encoding='utf-8'))
        review.update(human_review_complete=True, judgments_origin='human',
                      reviewer='Constructed reviewer for unit test only',
                      reviewed_at_utc='2026-10-29T10:00:00Z')
        for row in review['records']:
            row.update(typed_task_success=True, baseline_task_success=True, candidate_task_success=True)
        write_json(self.output / 'human-review.json', review)
        summary = evaluation.summarize(self.output, root=self.root)
        self.assertFalse(summary['human_review_complete'])
        self.assertIsNone(summary['task_accuracy'])

    def test_explicit_non_tasks_are_excluded_and_typed_rag_errors_are_separate(self):
        # All reference/rating flags here are constructed to test accounting,
        # not claims that a person reviewed any real thesis question.
        rubric = dict(schema_version=1, reference_confirmed=True, reference_origin='human',
            reviewer='Constructed reference reviewer', records=[dict(id=row['id'],
                task_applicable=index != 0,
                answerability='non_question' if index == 0 else 'unsupported',
                required_fields=[], reference_sources=[], notes='Constructed fixture')
                for index, row in enumerate(self.inputs['rows'])])
        path = self.root / 'runtime/constructed-rubric.json'
        write_json(path, rubric)
        evaluation.prepare(self.source, self.packet, root=self.root, rubric_path=path)
        self.run_evaluation()
        review = json.loads((self.output / 'bound-human-review-template.json').read_text(encoding='utf-8'))
        review.update(human_review_complete=True, judgments_origin='human',
                      reviewer='Constructed response reviewer', reviewed_at_utc='2026-10-29T10:00:00Z')
        for row in review['records']:
            row.update(typed_task_success=True, baseline_task_success=True, candidate_task_success=True)
        review['records'][1].update(typed_task_success=False, baseline_task_success=False, candidate_task_success=False)
        review['records'][2].update(baseline_task_success=False, candidate_task_success=False)
        review['records'][3]['candidate_task_success'] = False
        write_json(self.output / 'human-review.json', review)
        summary = evaluation.summarize(self.output, root=self.root)
        self.assertTrue(summary['human_review_complete'])
        self.assertEqual(summary['reviewed_tasks'], 12)
        self.assertEqual(summary['excluded_non_task_records'], 1)
        self.assertEqual(summary['task_accuracy']['typed'], dict(successes=11, denominator=12))
        self.assertEqual(summary['task_accuracy']['baseline_raw'], dict(successes=10, denominator=12))
        self.assertEqual(summary['task_accuracy']['candidate_raw'], dict(successes=9, denominator=12))
        self.assertEqual(summary['typed_rag_failures'], 1)
        self.assertEqual(summary['possible_asr_induced_failures'], dict(baseline_raw=1, candidate_raw=2))
        self.assertFalse(summary['task_success_no_regression'])

    def test_invalid_method_endpoint_or_extra_session_token_does_not_open_http(self):
        class Opener:
            calls = []
            def open(self, request, timeout=None):
                self.calls.append(request)
                raise AssertionError('Invalid request must not use HTTP')
        opener = Opener()
        transport = evaluation.LoopbackTransport(opener=opener)
        invalid = [('POST', '/api/status', {}), ('GET', '/api/route', None),
                   ('POST', '/api/voice/transcribe', {}),
                   ('POST', '/api/route', dict(query='fixture', allow_draft=True)),
                   ('POST', '/api/route', dict(query='fixture', allow_draft=False,
                                              clarification_id='not-permitted'))]
        for method, path, payload in invalid:
            with self.subTest(method=method, path=path, payload=payload):
                with self.assertRaises(ValueError):
                    transport.request(method, path, payload)
        self.assertEqual(opener.calls, [])

    def test_redirect_response_is_never_accepted_as_a_loopback_result(self):
        class Response(io.BytesIO):
            status = 200
            def geturl(self):
                return 'https://evil.invalid/received-query'
        class Opener:
            calls = []
            def open(self, request, timeout=None):
                self.calls.append(request)
                return Response(b'{"constructed": true}')
        opener = Opener()
        transport = evaluation.LoopbackTransport(opener=opener)
        with self.assertRaises(ValueError):
            transport.request('GET', '/api/status')
        self.assertEqual(len(opener.calls), 1)


    def test_source_candidate_identity_must_be_explicit_in_state_and_protocol(self):
        for holder in (self.state, self.protocol):
            for replacement in (None, 'different-speech-model'):
                original = holder.pop('model')
                if replacement is not None:
                    holder['model'] = replacement
                self.rebind()
                with self.assertRaises(ValueError):
                    evaluation.load_inputs(self.source, root=self.root)
                holder['model'] = original
                self.rebind()

    def test_source_human_reference_must_be_explicitly_confirmed(self):
        row = self.manifest['human_rows'][0]
        for replacement in (None, 'pending', 'synthetic_control'):
            row.pop('reference_status', None)
            if replacement is not None:
                row['reference_status'] = replacement
            self.rebind()
            with self.assertRaises(ValueError):
                evaluation.load_inputs(self.source, root=self.root)

    def constructed_rubric(self):
        return dict(schema_version=1, reference_confirmed=True, reference_origin='human',
            reviewer='Constructed reference reviewer, not real study evidence', records=[
                dict(id=row['id'], task_applicable=True, answerability='unsupported',
                     required_fields=[], reference_sources=[])
                for row in self.inputs['rows']])

    def write_constructed_review(self, rubric):
        path = self.root / 'runtime/constructed-rubric.json'
        write_json(path, rubric)
        evaluation.prepare(self.source, self.packet, root=self.root, rubric_path=path)
        self.run_evaluation()
        review = json.loads((self.output / 'bound-human-review-template.json').read_text(encoding='utf-8'))
        review.update(human_review_complete=True, judgments_origin='human',
                      reviewer='Constructed reviewer, not a real study judgment',
                      reviewed_at_utc='2026-10-29T10:00:00Z')
        for row in review['records']:
            row.update(typed_task_success=True, baseline_task_success=True, candidate_task_success=True)
        write_json(self.output / 'human-review.json', review)
        return review

    def test_applicable_answerable_tasks_need_meaningful_fields_and_sources(self):
        for index, (field, bad) in enumerate([('required_fields', []), ('reference_sources', []),
                                            ('required_fields', [' ']), ('reference_sources', [None])]):
            self.packet = self.root / ('runtime/packet-' + str(index))
            self.output = self.root / ('runtime/run-' + str(index))
            rubric = self.constructed_rubric()
            row = rubric['records'][0]
            row.update(answerability='answerable', required_fields=['constructed expected field'],
                       reference_sources=['constructed source locator'])
            row[field] = bad
            self.write_constructed_review(rubric)
            summary = evaluation.summarize(self.output, root=self.root)
            self.assertFalse(summary['human_review_complete'])
            self.assertIsNone(summary['task_accuracy'])

    def test_applicable_no_question_cannot_be_scored_as_task_success(self):
        self.raw[0]['candidate']['text'] = ''
        self.inputs['rows'][0]['candidate_raw'] = ''
        self.rebind()
        review = self.write_constructed_review(self.constructed_rubric())
        summary = evaluation.summarize(self.output, root=self.root)
        self.assertFalse(summary['human_review_complete'])
        self.assertIsNone(summary['task_accuracy'])
        self.assertEqual(summary['human_review_issue'], 'success_without_a_question_or_answer')
        # Once the constructed reviewer correctly marks this empty arm failed,
        # the accounting retains its denominator instead of hiding the record.
        review['records'][0]['candidate_task_success'] = False
        write_json(self.output / 'human-review.json', review)
        summary = evaluation.summarize(self.output, root=self.root)
        self.assertTrue(summary['human_review_complete'])
        self.assertEqual(summary['task_accuracy']['candidate_raw'], dict(successes=12, denominator=13))

    def test_http_failure_retains_private_response_and_elapsed_time_without_leaking_it(self):
        self.prepare()
        class FailedRoute(FakeTransport):
            def request(self, method, path, payload=None):
                if method == 'POST':
                    raise HTTPError(evaluation.BASE_URL + path, 503, 'CONSTRUCTED_PRIVATE_ERROR',
                                    {}, io.BytesIO(b'CONSTRUCTED_PRIVATE_RESPONSE'))
                return super().request(method, path, payload)
        state = self.run_evaluation(FailedRoute(self.status))
        self.assertFalse(state['completed'])
        self.assertEqual(state['route_attempts'], 1)
        self.assertEqual(state['error'], 'http_503')
        self.assertNotIn('CONSTRUCTED_PRIVATE', json.dumps(state))
        row = json.loads((self.output / 'results.jsonl').read_text(encoding='utf-8').splitlines()[0])
        self.assertEqual(row['response']['http_status'], 503)
        self.assertEqual(row['response']['body'], 'CONSTRUCTED_PRIVATE_RESPONSE')
        self.assertGreaterEqual(row['elapsed_seconds'], 0)

    def test_non_question_cannot_be_marked_as_an_applicable_task(self):
        rubric = dict(schema_version=1, records=[dict(id=row['id'], task_applicable=True,
            answerability='non_question', required_fields=[], reference_sources=[])
            for row in self.inputs['rows']])
        path = self.root / 'runtime/invalid-rubric.json'
        write_json(path, rubric)
        with self.assertRaises(ValueError):
            evaluation.prepare(self.source, self.packet, root=self.root, rubric_path=path)


if __name__ == '__main__':
    unittest.main()
