"""Actual browser JS handlers, isolated from the network and optional Node."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node')


@unittest.skipUnless(NODE, 'Node is optional; browser-handler checks require its JS runtime')
class VoiceUIRecoveryTests(unittest.TestCase):
    def scenario(self, name):
        result = subprocess.run([NODE, str(ROOT/'tests/voice_ui_recovery_harness.js'),
            str(ROOT/'demo/index.html'), name], capture_output=True, text=True,
            encoding='utf-8', timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"passed":true', result.stdout)

    def test_stalled_request_times_out_and_releases_composer(self):
        self.scenario('timeout')

    def test_reset_aborts_browser_wait_and_releases_busy_state(self):
        self.scenario('reset')

    def test_late_canceled_result_cannot_overwrite_or_unlock_new_request(self):
        self.scenario('late')

    def test_network_failure_leaves_retry_usable(self):
        self.scenario('network')

    def test_replacing_audio_ignores_the_old_request_error(self):
        self.scenario('replace')

    def test_json_rejection_and_late_body_cannot_override_new_state(self):
        self.scenario('json')

    def test_success_retains_raw_transcription_identity_after_composer_edit(self):
        self.scenario('lineage')

    def test_http_failure_and_empty_speech_never_create_false_lineage(self):
        self.scenario('http-empty')

    def test_failed_cleanup_retains_ids_until_normal_retry_acknowledgment(self):
        self.scenario('cleanup-retry')

    def test_old_cleanup_acknowledgment_cannot_remove_new_audio_ids(self):
        self.scenario('cleanup-concurrent')

    def test_cleanup_batches_match_the_server_100_id_limit(self):
        self.scenario('cleanup-batch')

    def test_reset_sends_one_cleanup_and_unlocks_before_acknowledgment(self):
        self.scenario('cleanup-reset')

    def test_pagehide_cleanup_batches_and_acknowledgments_preserve_new_ids(self):
        self.scenario('cleanup-pagehide')


if __name__ == '__main__':
    unittest.main()
