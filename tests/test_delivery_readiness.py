"""Deployment readiness failures use isolated invented inputs, no model inference."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import check_delivery_readiness as readiness


class DeliveryReadinessTests(unittest.TestCase):
    def test_missing_project_fails_closed_and_never_starts_or_creates_inputs(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            before = list(root.iterdir())
            with patch('socket.socket', side_effect=AssertionError('No network allowed')):
                result = readiness.check(root)
            self.assertFalse(result['local_preflight_passed'])
            self.assertFalse(result['stable_https_ready'])
            self.assertFalse(result['modifications_performed'])
            failed = {row['name'] for row in result['checks'] if not row['passed']}
            self.assertTrue({'entrypoints', 'pinned_dependencies', 'cafet_and_e5_files',
                             'gemma_and_ollama_files', 'active_source_data'}.issubset(failed))
            self.assertEqual(list(root.iterdir()), before)
            self.assertNotIn('activation_token', json.dumps(result))

    def test_requirement_pin_conflict_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'requirements.txt').write_text('edge-tts==7.3.1\n', encoding='utf-8')
            (root / 'requirements-modeltools.txt').write_text('edge-tts==7.2.8\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Conflicting'):
                readiness.requirements(root)

    def test_unpinned_requirement_is_not_marked_reproducible(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'requirements.txt').write_text('edge-tts>=7\n', encoding='utf-8')
            (root / 'requirements-modeltools.txt').write_text('', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'unpinned'):
                readiness.requirements(root)

    def test_private_admin_and_historical_audio_are_denied_by_actual_route_policy(self):
        result = readiness.gateway_boundaries()
        self.assertEqual(result['denied_route_probes'], 11)
        with patch.object(readiness, 'allowed_path', return_value=True):
            with self.assertRaisesRegex(ValueError, 'private boundaries'):
                readiness.gateway_boundaries()

    def test_local_success_keeps_external_delivery_unverified(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(readiness, 'python_profile', return_value={}), \
                 patch.object(readiness, 'entrypoints', return_value={}), \
                 patch.object(readiness, 'dependencies', return_value={}), \
                 patch.object(readiness, 'release_models', return_value={}), \
                 patch.object(readiness, 'llm_files', return_value={}), \
                 patch.object(readiness, 'data_files', return_value={}):
                result = readiness.check(Path(folder))
            self.assertTrue(result['local_preflight_passed'])
            self.assertFalse(result['stable_https_ready'])
            self.assertIn('TLS/DNS verification', result['checks_not_performed'])


if __name__ == '__main__':
    unittest.main()
