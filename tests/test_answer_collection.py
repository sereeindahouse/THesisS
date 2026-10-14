"""Frozen-reference preflight and honest output capture, without network/model calls."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import evaluate_answer_quality as collector


class AnswerCollectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cases = self.root / 'cases.json'
        self.validation = self.root / 'validation.json'
        self.output = self.root / 'new-run' / 'answers.json'
        self.code_root = self.root / 'project'
        self.code_root.mkdir()
        for name in ('rag_runtime.py', 'source_fields.py', 'answer_contract.py'):
            (self.code_root/name).write_text('Import-time contents of '+name, encoding='utf-8')
        self.code_hashes = {name: collector.sha(self.code_root/name)
            for name in ('rag_runtime.py', 'source_fields.py', 'answer_contract.py')}
        self.status = dict(rag=dict(loaded_artifact_sha256=dict(self.code_hashes),
            provider_available=False))
        self.source_hash = hashlib.sha256(b'Frozen source bytes, not model output.').hexdigest()
        self.bundle = dict(label_scope='Assistant development references, not human gold.',
            source_snapshot_sha256=self.source_hash, cases=[dict(
                id='document-pair', query='Which two documents are required?',
                requested_attribute='foreign_education_documents',
                expected_behavior='State both documented requirements.',
                label_author='assistant', human_reference_review=False,
                reference_answerability='answerable', required_facts=['document one', 'document two'],
                source_refs=[dict(source_id='source-one', quote_sha256='reference-quote-hash')])])
        self.cases.write_text(json.dumps(self.bundle), encoding='utf-8')
        self.validation_report = dict(
            public_cases_sha256=collector.sha(self.cases), source_snapshot_sha256=self.source_hash,
            summary=dict(independent_human_reference=False,
                quote_membership_validated=True, semantic_reference_correctness_validated=False,
                held_out_evaluation=False))
        self.validation.write_text(json.dumps(self.validation_report), encoding='utf-8')

    def rejected_before_any_collection(self, validation_path):
        with patch.object(collector.urllib.request, 'build_opener') as network, \
                patch.object(collector.subprocess, 'check_output') as git:
            with self.assertRaises(ValueError):
                collector.run(self.cases, self.output, 'http://127.0.0.1:8765', validation_path)
            network.assert_not_called()
            git.assert_not_called()
        self.assertFalse(self.output.exists())
        self.assertFalse(self.output.parent.exists())

    def test_frozen_references_require_validation_before_reserving_output(self):
        self.rejected_before_any_collection(None)

    def test_case_edit_after_validation_rejected_before_http_or_output(self):
        self.bundle['cases'][0]['query'] = 'A changed question after reference validation.'
        self.cases.write_text(json.dumps(self.bundle), encoding='utf-8')
        self.rejected_before_any_collection(self.validation)

    def test_source_snapshot_hash_mismatch_rejected_before_http_or_output(self):
        self.validation_report['source_snapshot_sha256'] = hashlib.sha256(b'Different frozen bytes.').hexdigest()
        self.validation.write_text(json.dumps(self.validation_report), encoding='utf-8')
        self.rejected_before_any_collection(self.validation)

    def test_matching_validation_captures_loopback_response_without_human_scores(self):
        captured = []
        reply = dict(route='C', answer='Both documents are required.', generated=True,
                     llm_calls=1, citations=[dict(document_id='source-one')])

        class MockLoopback:
            def open(self, request, timeout):
                captured.append((request, timeout))
                response = status if request.get_method() == 'GET' else reply
                return io.BytesIO(json.dumps(response).encode('utf-8'))

        status = self.status

        def git_output(command, **kwargs):
            return 'test-head\n' if command == ['git', 'rev-parse', 'HEAD'] else ''

        with patch.object(collector, 'ROOT', self.code_root), \
                patch.object(collector.urllib.request, 'build_opener', return_value=MockLoopback()), \
                patch.object(collector.subprocess, 'check_output', side_effect=git_output), \
                contextlib.redirect_stdout(io.StringIO()):
            report = collector.run(self.cases, self.output, 'http://127.0.0.1:8765', self.validation)
        self.assertEqual(len(captured), 2)
        status_request, _ = captured[0]
        self.assertEqual(status_request.full_url, 'http://127.0.0.1:8765/api/status')
        self.assertEqual(status_request.get_method(), 'GET')
        request, timeout = captured[1]
        self.assertEqual(request.full_url, 'http://127.0.0.1:8765/api/route')
        self.assertEqual(request.get_method(), 'POST')
        self.assertEqual(request.get_header('Origin'), 'http://127.0.0.1:8765')
        self.assertEqual(json.loads(request.data), dict(
            query=self.bundle['cases'][0]['query'], allow_draft=False))
        self.assertGreater(timeout, 0)
        saved = json.loads(self.output.read_text(encoding='utf-8'))
        self.assertEqual(saved, report)
        self.assertEqual(report['cases_sha256'], collector.sha(self.cases))
        self.assertEqual(report['reference_validation_sha256'], collector.sha(self.validation))
        self.assertEqual(report['reference_validation'], self.validation_report)
        self.assertEqual(report['artifact_sha256']['source_fields.py'], self.code_hashes['source_fields.py'])
        preflight = report['runtime_preflight']
        self.assertTrue(preflight['matched'])
        self.assertEqual(preflight['status'], self.status)
        self.assertEqual(preflight['expected_artifact_sha256'], self.code_hashes)
        self.assertTrue(preflight['captured_utc'])
        self.assertIsNone(report['correctness_score'])
        self.assertFalse(report['independent_human_evaluation'])
        row = report['cases'][0]
        self.assertEqual(row['response'], reply)
        self.assertFalse(row['human_reference_review'])
        self.assertEqual(row['label_author'], 'assistant')
        self.assertTrue(all(value is None for value in row['human_review'].values()))
        self.assertEqual(row['source_refs'], self.bundle['cases'][0]['source_refs'])
        self.assertNotIn('error', row)

    def rejected_after_status_before_answer(self, status):
        captured = []

        class MockLoopback:
            def open(self, request, timeout):
                captured.append(request)
                return io.BytesIO(json.dumps(status).encode('utf-8'))

        with patch.object(collector, 'ROOT', self.code_root), \
                patch.object(collector.urllib.request, 'build_opener', return_value=MockLoopback()), \
                patch.object(collector.subprocess, 'check_output') as git:
            with self.assertRaises(ValueError):
                collector.run(self.cases, self.output, 'http://127.0.0.1:8765', self.validation)
            git.assert_not_called()
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0].get_method(), 'GET')
        self.assertEqual(captured[0].full_url, 'http://127.0.0.1:8765/api/status')
        self.assertFalse(self.output.exists())
        self.assertFalse(self.output.parent.exists())

    def test_stale_imported_server_code_rejected_before_post_or_output(self):
        for name in self.code_hashes:
            old = dict(self.code_hashes)
            old[name] = hashlib.sha256(b'Older imported module bytes.').hexdigest()
            with self.subTest(stale_module=name):
                self.rejected_after_status_before_answer(dict(rag=dict(loaded_artifact_sha256=old)))

    def test_missing_runtime_fingerprint_rejected_before_post_or_output(self):
        for status in (dict(rag=dict(provider_available=True)), dict(),
                dict(rag=dict(loaded_artifact_sha256={'rag_runtime.py': self.code_hashes['rag_runtime.py']}))):
            with self.subTest(status=status):
                self.rejected_after_status_before_answer(status)

    def test_legacy_cases_keep_no_status_request(self):
        self.bundle.pop('source_snapshot_sha256')
        self.cases.write_text(json.dumps(self.bundle), encoding='utf-8')
        captured = []

        class MockLoopback:
            def open(self, request, timeout):
                captured.append(request)
                return io.BytesIO(b'{"route":"E","answer":null}')

        with patch.object(collector, 'ROOT', self.code_root), \
                patch.object(collector.urllib.request, 'build_opener', return_value=MockLoopback()), \
                patch.object(collector.subprocess, 'check_output', return_value=''), \
                contextlib.redirect_stdout(io.StringIO()):
            report = collector.run(self.cases, self.output, 'http://127.0.0.1:8765')
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0].get_method(), 'POST')
        self.assertIsNone(report['runtime_preflight'])


if __name__ == '__main__':
    unittest.main()
