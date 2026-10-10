"""Tiny offline Release fixtures; no network requests or full weights."""
import hashlib
from pathlib import Path
import stat
import tempfile
import unittest
import warnings
import zipfile

from tools.install_release_models import SafeRedirectHandler, install_record, sha256, validate_record


class ReleaseModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'project'
        self.archives = Path(self.temp.name) / 'archives'
        self.archives.mkdir()
        self.name = 'tiny-cafet.zip'
        self.directory = 'faster-whisper-small-mn-cafet'
        self.weight = b'synthetic-fixture-weight'
        self.prefix = f'models/{self.directory}/'

    def fixture(self, extra=None, *, weight=None, kind='stt'):
        if kind == 'retrieval':
            directory, weight_file = 'multilingual-e5-small', 'model.safetensors'
        else:
            directory, weight_file = self.directory, 'model.bin'
        prefix = f'models/{directory}/'
        entries = [(prefix + weight_file, self.weight if weight is None else weight),
                   (prefix + 'config.json', b'{}')]
        if extra:
            entries.extend(extra)
        archive = self.archives / self.name
        with zipfile.ZipFile(archive, 'w') as output:
            for name, content in entries:
                output.writestr(name, content)
        return {'kind': kind, 'name': self.name, 'size': archive.stat().st_size,
                'sha256': sha256(archive), 'model_directory': directory,
                'weight_file': weight_file,
                'model_sha256': hashlib.sha256(self.weight).hexdigest(),
                'url': f'https://github.com/sereeindahouse/THesisS/releases/download/models-20261010/{self.name}',
                'members': [name.filename if isinstance(name, zipfile.ZipInfo) else name for name, _ in entries]}

    def assert_no_partial(self):
        self.assertFalse((self.root / 'models' / self.directory).exists())
        if (self.root / 'runtime').exists():
            self.assertEqual(list((self.root / 'runtime').iterdir()), [])

    def test_verified_install_and_repeat_skip(self):
        record = self.fixture()
        self.assertEqual(install_record(record, self.root, self.archives)['status'], 'installed_verified')
        self.assertEqual(install_record(record, self.root, self.archives)['status'], 'existing_verified')
        self.assertEqual((self.root / 'models' / self.directory / 'model.bin').read_bytes(), self.weight)
        self.assertEqual(list((self.root / 'runtime').iterdir()), [])

    def test_e5_layout_installs(self):
        record = self.fixture(kind='retrieval')
        self.assertEqual(install_record(record, self.root, self.archives)['status'], 'installed_verified')
        self.assertEqual((self.root / 'models' / 'multilingual-e5-small' / 'model.safetensors').read_bytes(), self.weight)

    def test_existing_bad_weight_never_overwritten(self):
        record = self.fixture()
        target = self.root / 'models' / self.directory
        target.mkdir(parents=True)
        (target / 'model.bin').write_bytes(b'keep-existing')
        with self.assertRaisesRegex(ValueError, 'refusing overwrite'):
            install_record(record, self.root, self.archives)
        self.assertEqual((target / 'model.bin').read_bytes(), b'keep-existing')

    def test_wrong_archive_hash_or_size_rejects_before_extraction(self):
        record = self.fixture()
        for changed in ({'sha256': '0' * 64}, {'size': record['size'] + 1}):
            with self.subTest(changed=changed), self.assertRaisesRegex(ValueError, 'Archive size or SHA256'):
                install_record(dict(record, **changed), self.root, self.archives)
            self.assert_no_partial()

    def test_extracted_wrong_weight_cleans_scratch(self):
        record = self.fixture(weight=b'wrong-fixture-weight')
        with self.assertRaisesRegex(ValueError, 'Extracted model weight'):
            install_record(record, self.root, self.archives)
        self.assert_no_partial()

    def test_traversal_absolute_and_backslash_rejected(self):
        for name in ('../outside.txt', '/outside.txt', self.prefix + '../outside.txt',
                     self.prefix + 'C:outside.txt', self.prefix + 'folder\\outside.txt'):
            with self.subTest(name=name):
                record = self.fixture([(name, b'bad')])
                with self.assertRaises(ValueError):
                    install_record(record, self.root, self.archives)
                self.assert_no_partial()
        self.assertFalse((Path(self.temp.name) / 'outside.txt').exists())

    def test_zip_path_not_in_catalog_rejected(self):
        record = self.fixture([(self.prefix + 'surprise.txt', b'unexpected')])
        record['members'].pop()
        with self.assertRaisesRegex(ValueError, 'members differ'):
            install_record(record, self.root, self.archives)
        self.assert_no_partial()

    def test_zip_symlink_rejected(self):
        entry = zipfile.ZipInfo(self.prefix + 'link')
        entry.create_system = 3
        entry.external_attr = (stat.S_IFLNK | 0o777) << 16
        record = self.fixture([(entry, b'../../outside')])
        with self.assertRaisesRegex(ValueError, 'symlinks'):
            install_record(record, self.root, self.archives)
        self.assert_no_partial()

    def test_duplicate_zip_member_rejected(self):
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            record = self.fixture([(self.prefix + 'config.json', b'overwriting-entry')])
        record['members'] = list(dict.fromkeys(record['members']))
        with self.assertRaisesRegex(ValueError, 'Duplicate archive paths'):
            install_record(record, self.root, self.archives)
        self.assert_no_partial()

    def test_download_redirect_rejects_http_and_unrelated_hosts(self):
        handler = SafeRedirectHandler()
        for url in ('http://github.com/download', 'https://attacker.example/download'):
            with self.subTest(url=url), self.assertRaisesRegex(ValueError, 'download redirect'):
                handler.redirect_request(None, None, 302, 'Found', {}, url)

    def test_wrong_repository_url_or_model_prefix_rejected(self):
        record = self.fixture()
        for changed in ({'url': record['url'].replace('sereeindahouse', 'somebody')},
                        {'model_directory': 'unrelated-model'},
                        {'members': ['models/multilingual-e5-small/model.bin']},
                        {'name': '../tiny.zip'}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                validate_record(dict(record, **changed))


if __name__ == '__main__':
    unittest.main()
