"""Offline tests for a fresh clone without private metadata or large weights."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from stt_mn import load_choice
from retrieval_probe import bm25_scores

ROOT = Path(__file__).resolve().parents[1]


class PublicPortabilityTests(unittest.TestCase):
    def make_choice(self, root, *, private=False):
        path = root / 'models/test-model'
        path.mkdir(parents=True, exist_ok=True)
        weights = b'synthetic-test-weights-never-used-for-inference'
        (path / 'model.bin').write_bytes(weights)
        sha = hashlib.sha256(weights).hexdigest()
        config = dict(development_model_path='models/test-model', source_repo='test/public-model',
                      source_revision='test-revision', model_sha256=sha)
        (path / 'download-manifest.json').write_text(json.dumps(dict(repo_id=config['source_repo'],
            revision=config['source_revision'], files={'model.bin': {'sha256': sha}})), encoding='utf-8')
        destination = root / ('data/stt-model-choice.json' if private else 'config/stt-development.json')
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(config), encoding='utf-8')
        return config, path

    def test_stt_fallback_without_private_choice(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected, path = self.make_choice(root)
            actual, model = load_choice(root)
            self.assertEqual(actual, expected)
            self.assertEqual(model, path)

    def test_private_choice_takes_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected, _ = self.make_choice(root, private=True)
            public = root / 'config/stt-development.json'
            public.parent.mkdir()
            public.write_text('{"invalid_fallback": true}', encoding='utf-8')
            self.assertEqual(load_choice(root)[0], expected)

    def test_stt_changed_weights_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, path = self.make_choice(root)
            (path / 'model.bin').write_bytes(b'changed')
            with self.assertRaises(ValueError):
                load_choice(root)

    def fixture_downloader(self, root, script, repo, output):
        tools = root / 'tools'
        tools.mkdir()
        shutil.copy2(ROOT / 'tools' / script, tools / script)
        catalog = root / 'config/model-catalog'
        catalog.mkdir(parents=True)
        weights = b'synthetic-fixture-not-an-inference-model'
        sha = hashlib.sha256(weights).hexdigest()
        data = dict(repo_id=repo, revision='fixture-revision', license='fixture-only',
                    files=[dict(rfilename='model.safetensors', size=len(weights), lfs={'sha256': sha})])
        (catalog / (repo.replace('/', '--') + '.json')).write_text(json.dumps(data), encoding='utf-8')
        model = root / 'models' / output
        model.mkdir(parents=True)
        (model / 'model.safetensors').write_bytes(weights)
        return tools / script, model

    def test_downloaders_bootstrap_from_public_metadata_offline(self):
        for script, repo, output in [
            ('download_public_checkpoint.py', 'Cafet/whisper-small-mongolian', 'whisper-small-mn-cafet-hf'),
            ('download_embedding_checkpoint.py', 'intfloat/multilingual-e5-small', 'multilingual-e5-small')]:
            with self.subTest(script=script), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                tool, model = self.fixture_downloader(root, script, repo, output)
                run = subprocess.run([sys.executable, str(tool)], cwd=root, capture_output=True,
                                     text=True, encoding='utf-8', timeout=15)
                self.assertEqual(run.returncode, 0, run.stderr)
                manifest = json.loads((model / 'source-manifest.json').read_text(encoding='utf-8'))
                self.assertEqual(manifest['repo_id'], repo)
                self.assertFalse((model / 'active-download.lock').exists())
                self.assertFalse((root / 'results').exists())

    def test_downloaders_reject_escape_before_mutation(self):
        for script, repo, output in [
            ('download_public_checkpoint.py', 'Cafet/whisper-small-mongolian', 'whisper-small-mn-cafet-hf'),
            ('download_embedding_checkpoint.py', 'intfloat/multilingual-e5-small', 'multilingual-e5-small')]:
            with self.subTest(script=script), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                tool, _ = self.fixture_downloader(root, script, repo, output)
                escaped = root / 'must-not-be-created'
                run = subprocess.run([sys.executable, str(tool), '--name', '../must-not-be-created'],
                                     cwd=root, capture_output=True, text=True, encoding='utf-8', timeout=15)
                self.assertNotEqual(run.returncode, 0)
                self.assertFalse(escaped.exists())

    def test_public_profile_is_minimal_and_unaccepted(self):
        profile = json.loads((ROOT / 'config/stt-development.json').read_text(encoding='utf-8'))
        self.assertFalse(profile['production_accepted'])
        self.assertFalse(profile['fine_tuning_performed'])
        for private in ('metrics', 'selection_metrics', 'reference_audits', 'remaining_reference_reviews'):
            self.assertNotIn(private, profile)
        self.assertEqual(profile['source_repo'], 'Cafet/whisper-small-mongolian')

    def test_mongolian_bm25_normalization_and_no_overlap(self):
        passages = ['Сургуулийн холбоо барих утас', 'Компьютерын ухааны сургалт']
        scores = bm25_scores(passages, ['ХОЛБОО, БАРИХ!', 'гадаад паспорт'])
        self.assertGreater(scores[0][0], scores[0][1])
        self.assertEqual(scores[1], [0.0, 0.0])
        self.assertEqual(scores[0], bm25_scores(passages, ['барих холбоо холбоо'])[0])


if __name__ == '__main__':
    unittest.main()
