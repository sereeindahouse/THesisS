import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tools.tts_listening_trial import ListeningTrial


class ListeningTrialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        audio = b'fixture-not-an-actual-provider-audio'
        (self.root / 'trial-1.mp3').write_bytes(audio)
        self.digest = hashlib.sha256(audio).hexdigest()
        self.bundle = dict(scope='school_text_tts_human_self_report', samples=[dict(
            id='trial-1', label='Жишээ', text='<script>untrusted source</script>',
            voice='mn-MN-BataaNeural', seconds=2.0, audio_sha256=self.digest)])
        self.write_bundle()

    def write_bundle(self):
        (self.root / 'manifest.json').write_text(json.dumps(self.bundle), encoding='utf-8')

    def valid_review(self):
        return dict(sample_id='trial-1', audio_sha256=self.digest, listened=True,
                    playback_ended=True, playback_rate=1, comments='',
                    intelligibility=4, pronunciation=3, naturalness=4)

    def test_review_is_bound_to_frozen_audio_and_is_not_automatic_acceptance(self):
        trial = ListeningTrial(self.root)
        self.assertEqual(trial.manifest()['samples'][0]['audio_url'], '/api/listening/audio/trial-1')
        result = trial.save_review(self.valid_review())
        saved = json.loads(next((self.root / 'reviews').glob('*.json')).read_text())
        self.assertEqual(saved['audio_sha256'], self.digest)
        self.assertFalse(result['observer_verified'])
        self.assertFalse(result['automatic_quality_acceptance'])
        self.assertNotIn('<script>untrusted', trial.page_bytes().decode())
        self.assertIn('textContent=text', trial.page_bytes().decode())

    def test_cannot_fabricate_default_unlistened_or_unrated_human_response(self):
        trial = ListeningTrial(self.root)
        for update in ({'listened': False}, {'intelligibility': True}, {'pronunciation': 0},
                       {'audio_sha256': '0' * 64}, {'sample_id': '../private'},
                       {'comments': 'x' * 501}, {'playback_rate': float('nan')},
                       {'playback_ended': 1}, {'unknown': 1}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                trial.save_review({**self.valid_review(), **update})
        self.assertFalse((self.root / 'reviews').exists())

    def test_changed_audio_fails_closed_before_serving_or_saving(self):
        trial = ListeningTrial(self.root)
        (self.root / 'trial-1.mp3').write_bytes(b'changed')
        with self.assertRaises(ValueError):
            trial.audio('trial-1')
        with self.assertRaises(ValueError):
            trial.save_review(self.valid_review())
        with self.assertRaises(ValueError):
            ListeningTrial(self.root)

    def test_unknown_paths_and_duplicate_or_unsafe_ids_are_rejected(self):
        trial = ListeningTrial(self.root)
        with self.assertRaises(KeyError):
            trial.audio('../private')
        self.bundle['samples'].append(self.bundle['samples'][0])
        self.write_bundle()
        with self.assertRaises(ValueError):
            ListeningTrial(self.root)

    def test_local_http_reads_only_bundle_and_requires_origin_for_human_write(self):
        import http.client
        import threading
        from tools.tts_listening_trial import make_local_server
        server = make_local_server(self.root, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            origin = f'http://127.0.0.1:{server.server_port}'
            def request(method, path, body=None, headers=None):
                connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=2)
                try:
                    connection.request(method, path, body, headers or {})
                    response = connection.getresponse()
                    return response.status, response.read()
                finally:
                    connection.close()
            code, data = request('GET', '/api/listening/audio/trial-1')
            self.assertEqual(code, 200)
            self.assertEqual(hashlib.sha256(data).hexdigest(), self.digest)
            self.assertEqual(request('GET', '/runtime/content.db')[0], 404)
            self.assertEqual(request('GET', '/api/review')[0], 404)
            body = json.dumps(self.valid_review())
            self.assertEqual(request('POST', '/api/listening/review', body,
                                    {'Origin': 'https://other.test', 'Content-Type': 'application/json'})[0], 403)
            self.assertEqual(request('POST', '/api/listening/review', body,
                                    {'Content-Type': 'application/json'})[0], 400)
            self.assertFalse((self.root / 'reviews').exists())
            self.assertEqual(request('POST', '/api/listening/review', body,
                                    {'Origin': origin, 'Content-Type': 'application/json'})[0], 200)
            self.assertEqual(len(list((self.root / 'reviews').glob('*.json'))), 1)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        self.bundle['samples'] = [{**self.bundle['samples'][0], 'id': '../private'}]
        self.write_bundle()
        with self.assertRaises(ValueError):
            ListeningTrial(self.root)


if __name__ == '__main__':
    unittest.main()
