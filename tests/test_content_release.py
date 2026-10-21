"""Actual isolated release transitions; invented school content, no model calls."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from content_release import ContentReleaseManager, ReleaseConflict, ReleaseInvalid
from content_store import ContentStore
from CORE.website_corpus import PageParser, import_snapshot
from tools import manage_snapshot as snapshots
from test_content_store import fixture


URL = 'https://nmct.edu.mn/test-release'


def captured(root, run_id='fixture-run', text='Зөвхөн тестийн хариулт.'):
    directory = root / 'CORE/website/snapshots' / run_id
    directory.mkdir(parents=True)
    body = ('<html><title>Invented</title><main>' + text + '</main></html>').encode()
    parser = PageParser(); parser.feed(body.decode()); extracted = parser.result()['text']
    (directory / 'page.html').write_bytes(body)
    (directory / 'page.txt').write_text(extracted, encoding='utf-8', newline='')
    manifest = dict(run_id=run_id, retrieved_at='2026-10-20T01:00:00+00:00', inventory=[], pages=[dict(
        url=URL, status='ok', html_file='page.html', text_file='page.txt',
        html_sha256=snapshots.sha(directory/'page.html'), text_sha256=snapshots.sha(directory/'page.txt'),
        retrieved_at='2026-10-20T01:00:00+00:00', http={'charset': 'utf-8', 'last_modified': None})])
    (directory / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    return directory


def content(version=1):
    value = fixture(version=version)
    value['sources'][0]['source_url_or_filename'] = URL
    return value


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'project'; self.root.mkdir()
        import_snapshot(self.root / snapshots.DATABASES[0], captured(self.root))
        with ContentStore(self.root / snapshots.DATABASES[1]) as store:
            store.import_content(content(), allow_draft=True)
        self.original = {name: snapshots.sha(self.root/name) for name in snapshots.DATABASES}
        self.manager = ContentReleaseManager(self.root)

    def sealed(self, label='Invented release', expected_active=None):
        value = self.manager.stage(label, expected_active)
        self.manager.validate(value['release_id'])
        return value['release_id']

    def test_stage_and_seal_never_activate_or_modify_originals(self):
        release_id = self.sealed()
        self.assertIsNone(self.manager.resolve())
        row = self.manager.inspect(release_id)
        self.assertEqual(row['status'], 'validated')
        self.assertFalse(row['validation']['semantic_correctness_proven'])
        self.assertEqual(self.original, {name: snapshots.sha(self.root/name) for name in snapshots.DATABASES})
        self.assertEqual(row['diff']['faqs'], dict(added=[], updated=[], removed=[]))

    def test_publish_import_new_package_rollback_and_aba_token(self):
        first = self.sealed('first')
        active1 = self.manager.publish(first, None)
        row = self.manager.stage('edited', active1['activation_token'])
        changed = content(version=2); changed['faqs'][0]['answer'] = 'Тестийн шинэ хариулт.'
        self.manager.import_content(row['release_id'], changed)
        inspected = self.manager.validate(row['release_id'])
        self.assertTrue(inspected['diff']['package_changed'])
        self.assertIn('test.faq', inspected['diff']['faqs']['updated'])
        active2 = self.manager.publish(row['release_id'], active1['activation_token'])
        self.assertNotEqual(active1['package_id'], active2['package_id'])
        active3 = self.manager.rollback(first, active2['activation_token'])
        self.assertEqual(active3['release_id'], first)
        self.assertEqual(active3['package_id'], active1['package_id'])
        self.assertNotEqual(active3['activation_token'], active1['activation_token'])
        with self.assertRaises(ReleaseConflict):
            self.manager.publish(row['release_id'], active1['activation_token'])
        self.assertEqual(self.original, {name: snapshots.sha(self.root/name) for name in snapshots.DATABASES})

    def test_stale_stage_or_publish_never_changes_pointer(self):
        first = self.sealed()
        active = self.manager.publish(first, None)
        for operation in (lambda: self.manager.stage('stale', None), lambda: self.manager.publish(first, None)):
            with self.assertRaises(ReleaseConflict): operation()
        self.assertEqual(self.manager.resolve()['activation_token'], active['activation_token'])

    def test_unvalidated_and_sealed_edit_rejected(self):
        row = self.manager.stage('draft')
        with self.assertRaises(ReleaseInvalid): self.manager.publish(row['release_id'], None)
        self.manager.validate(row['release_id'])
        with self.assertRaises(ReleaseInvalid): self.manager.import_content(row['release_id'], content(version=2))

    def test_mutated_sealed_database_fails_closed_even_same_size(self):
        release_id = self.sealed()
        active = self.manager.publish(release_id, None)
        database = Path(active['content_database'])
        original_size = database.stat().st_size
        with closing(sqlite3.connect(database)) as db:
            db.execute("UPDATE packages SET source_filename='tampered'"); db.commit()
        self.assertEqual(database.stat().st_size, original_size)
        with self.assertRaises(ReleaseInvalid): self.manager.resolve()
        # A previously activated release is selected through rollback: publish
        # intentionally rejects its obsolete staging baseline before integrity
        # checks. Rollback must still reject changed sealed bytes.
        with self.assertRaises(ReleaseInvalid): self.manager.rollback(release_id, active['activation_token'])

    def test_deleted_active_pointer_or_database_never_falls_back_to_legacy(self):
        release_id = self.sealed()
        active = self.manager.publish(release_id, None)
        database = Path(active['website_database']); database.unlink()
        with self.assertRaises(ReleaseInvalid): self.manager.resolve()
        self.manager.pointer.unlink()
        with self.assertRaises(ReleaseInvalid): self.manager.resolve()

    def test_capture_tampering_detected_on_next_resolution(self):
        release_id = self.sealed(); active = self.manager.publish(release_id, None)
        page = Path(active['data_root'])/'CORE/website/snapshots/fixture-run/page.html'
        page.write_bytes(b'tampered capture')
        with self.assertRaises(ReleaseInvalid): self.manager.resolve()

    def test_admin_can_inspect_and_rollback_corrupt_active_while_chat_fails_closed(self):
        first = self.sealed('valid previous')
        active1 = self.manager.publish(first, None)
        second = self.sealed('will be damaged', active1['activation_token'])
        active2 = self.manager.publish(second, active1['activation_token'])
        Path(active2['content_database']).unlink()
        with self.assertRaises(ReleaseInvalid): self.manager.resolve()
        state = self.manager.state()
        self.assertTrue(state['active']['invalid'])
        self.assertTrue(state['active_error'])
        self.assertEqual(state['active']['activation_token'], active2['activation_token'])
        restored = self.manager.rollback(first, state['active']['activation_token'])
        self.assertEqual(restored['release_id'], first)
        self.assertFalse(self.manager.state()['active_error'])

    def test_chunk_corruption_prevents_validation(self):
        row = self.manager.stage('corrupt chunk')
        database = self.manager._path(row['release_id'])/'data'/snapshots.DATABASES[0]
        with closing(sqlite3.connect(database)) as db:
            db.execute("UPDATE chunks SET text='fabricated'"); db.commit()
        with self.assertRaisesRegex(ReleaseInvalid, 'exact captured text'):
            self.manager.validate(row['release_id'])

    def test_rollback_unpublished_release_is_rejected(self):
        release_id = self.sealed()
        with self.assertRaises(ReleaseInvalid): self.manager.rollback(release_id, None)

    def test_refreshing_cas_token_cannot_overwrite_changes_with_older_baseline(self):
        initial = self.sealed('initial')
        first = self.manager.publish(initial, None)
        left = self.sealed('left candidate', first['activation_token'])
        right = self.sealed('right candidate', first['activation_token'])
        second = self.manager.publish(left, first['activation_token'])
        with self.assertRaisesRegex(ReleaseConflict, 'older active release'):
            self.manager.publish(right, second['activation_token'])
        self.assertEqual(self.manager.resolve()['activation_token'], second['activation_token'])
        # Explicit rollback is still the reviewed mechanism to select an
        # existing published version; its old staging base is not reinterpreted.
        rolled = self.manager.rollback(initial, second['activation_token'])
        self.assertEqual(rolled['release_id'], initial)

    def test_concurrent_publishers_have_one_cas_winner(self):
        releases = [self.sealed('candidate ' + str(n)) for n in range(2)]
        def publish(release_id):
            try:
                return ContentReleaseManager(self.root).publish(release_id, None)['release_id']
            except ReleaseConflict:
                return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(publish, releases))
        self.assertEqual(results.count('conflict'), 1)
        self.assertIn(self.manager.resolve()['release_id'], releases)

    def test_invalid_source_schema_or_path_does_not_publish(self):
        row = self.manager.stage('invalid input')
        for value in ({}, {**content(), 'unexpected': True}):
            with self.assertRaises(ReleaseInvalid): self.manager.import_content(row['release_id'], value)
        invalid = content(version=2); invalid['sources'][0]['source_url_or_filename'] = 'https://example.org/source'
        with self.assertRaises(ReleaseInvalid): self.manager.import_content(row['release_id'], invalid)
        for value in ('../escape', 'release-20261020T010000Z-../../escape', 'C:/outside'):
            with self.assertRaises(ReleaseInvalid): self.manager.content(value)
        with self.assertRaises(ReleaseInvalid): self.manager.import_website(row['release_id'], self.root.parent)
        self.assertIsNone(self.manager.resolve())

    def test_actual_website_import_changes_sealed_corpus_without_touching_original(self):
        row = self.manager.stage('new website')
        source = captured(self.root, run_id='fixture-new', text='Шинэ туршилтын мэдээлэл.')
        manifest = json.loads((source/'manifest.json').read_bytes())
        manifest['retrieved_at'] = '2026-10-20T02:00:00+00:00'
        (source/'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        self.manager.import_website(row['release_id'], source)
        checked = self.manager.validate(row['release_id'])
        self.assertTrue(checked['diff']['corpus_changed'])
        self.assertIn(URL, checked['diff']['website_urls']['updated'])
        active = self.manager.publish(row['release_id'], None)
        self.assertEqual(active['corpus_id'], checked['validation']['summary']['website']['corpus_id'])
        self.assertEqual(self.original, {name: snapshots.sha(self.root/name) for name in snapshots.DATABASES})

    def test_unknown_wal_and_non_corpus_file_prevent_sealing(self):
        row = self.manager.stage('unknown file')
        data = self.manager._path(row['release_id'])/'data'
        (data/'runtime/private.wav').write_bytes(b'audio must not enter release')
        with self.assertRaises(ReleaseInvalid): self.manager.validate(row['release_id'])
        self.assertIsNone(self.manager.resolve())

    def upgraded_code(self):
        code = self.manager._code()
        code['website_retrieval.py'] = '0' * 64
        return code

    def test_explicit_code_upgrade_copies_only_then_normal_validate_publish(self):
        first = self.sealed('old installed code')
        active = self.manager.publish(first, None)
        old_path = self.manager._path(first)
        immutable = {path: path.read_bytes() for path in
            [old_path/'seal.json', old_path/'stage.json', self.manager.pointer] +
            [old_path/'data'/name for name in snapshots.DATABASES]}
        installed = self.upgraded_code()
        with patch.object(self.manager, '_code', return_value=installed):
            with self.assertRaises(ReleaseInvalid):
                self.manager.resolve()
            with self.assertRaises(ReleaseInvalid):
                self.manager.stage('ordinary staging must fail', active['activation_token'])
            candidate = self.manager.stage_code_upgrade('explicit new-code candidate', active['activation_token'])
            self.assertEqual(candidate['status'], 'staged')
            self.assertFalse(candidate['sealed'])
            self.assertTrue(all(path.read_bytes() == raw for path, raw in immutable.items()))
            self.assertEqual(self.manager._pointer()['activation_token'], active['activation_token'])
            with self.assertRaises(ReleaseInvalid):
                self.manager.resolve()
            with self.assertRaises(ReleaseInvalid):
                self.manager.publish(candidate['release_id'], active['activation_token'])
            metadata = self.manager._stage_metadata(candidate['release_id'])
            upgrade = metadata['code_upgrade']
            self.assertEqual(upgrade['source_release_id'], first)
            self.assertEqual(upgrade['installed_code'], installed)
            self.assertEqual(upgrade['changed_code_files'], ['website_retrieval.py'])
            self.assertEqual(upgrade['source_seal_sha256'], snapshots.sha(old_path/'seal.json'))
            checked = self.manager.validate(candidate['release_id'])
            self.assertFalse(checked['diff']['corpus_changed'])
            self.assertFalse(checked['diff']['package_changed'])
            activated = self.manager.publish(candidate['release_id'], active['activation_token'])
            self.assertEqual(activated['corpus_id'], active['corpus_id'])
            self.assertEqual(activated['package_id'], active['package_id'])
            self.assertNotEqual(activated['activation_token'], active['activation_token'])
            self.assertEqual(self.manager.resolve()['release_id'], candidate['release_id'])
            # Old code-bound releases remain immutable and cannot become a
            # rollback backdoor after current-code activation.
            with self.assertRaises(ReleaseInvalid):
                self.manager.rollback(first, activated['activation_token'])
            for path, raw in immutable.items():
                if path != self.manager.pointer:
                    self.assertEqual(path.read_bytes(), raw)
        self.assertEqual(self.original, {name: snapshots.sha(self.root/name) for name in snapshots.DATABASES})

    def test_code_upgrade_rejects_stale_cas_missing_active_and_unchanged_code(self):
        with self.assertRaises(ReleaseInvalid):
            self.manager.stage_code_upgrade('no active source', None)
        first = self.sealed()
        active = self.manager.publish(first, None)
        with self.assertRaisesRegex(ReleaseInvalid, 'unchanged'):
            self.manager.stage_code_upgrade('use normal stage', active['activation_token'])
        with patch.object(self.manager, '_code', return_value=self.upgraded_code()):
            for stale in (None, 'f'*32):
                with self.subTest(stale=stale), self.assertRaises(ReleaseConflict):
                    self.manager.stage_code_upgrade('stale', stale)
        self.assertEqual(self.manager.resolve()['activation_token'], active['activation_token'])

    def test_code_upgrade_rejects_db_capture_and_stage_corruption_before_copy(self):
        first = self.sealed()
        active = self.manager.publish(first, None)
        root = self.manager._path(first)
        existing = set(self.manager.directory.iterdir())
        targets = [root/'data'/snapshots.DATABASES[1], root/'data/CORE/website/snapshots/fixture-run/page.html',
                   root/'stage.json']
        for target in targets:
            raw = target.read_bytes()
            with self.subTest(path=str(target)):
                target.write_bytes(raw + b' changed')
                try:
                    with patch.object(self.manager, '_code', return_value=self.upgraded_code()):
                        with self.assertRaises(ReleaseInvalid):
                            self.manager.stage_code_upgrade('must not copy corrupt data', active['activation_token'])
                    self.assertEqual(set(self.manager.directory.iterdir()), existing)
                    self.assertEqual(self.manager._pointer()['activation_token'], active['activation_token'])
                finally:
                    target.write_bytes(raw)

    def test_code_upgrade_rejects_malformed_stored_code_inventory(self):
        first = self.sealed()
        active = self.manager.publish(first, None)
        path = self.manager._path(first)/'seal.json'
        original = path.read_bytes()
        seal = json.loads(original)
        malformed = [None, [], {}, {**seal['code'], 'unknown.py':'a'*64},
                     {**seal['code'], 'website_retrieval.py':'NOT-SHA'},
                     {k:v for k,v in seal['code'].items() if k != 'content_release.py'}]
        for stored in malformed:
            with self.subTest(stored=stored):
                changed = dict(seal, code=stored)
                path.write_text(json.dumps(changed), encoding='utf-8')
                with patch.object(self.manager, '_code', return_value=self.upgraded_code()):
                    with self.assertRaisesRegex(ReleaseInvalid, 'code inventory'):
                        self.manager.stage_code_upgrade('malformed code inventory', active['activation_token'])
                self.assertEqual(self.manager._pointer()['activation_token'], active['activation_token'])
        path.write_bytes(original)

    def test_code_upgrade_rejects_changed_seal_identity_and_summary(self):
        first = self.sealed()
        active = self.manager.publish(first, None)
        path = self.manager._path(first)/'seal.json'
        original = path.read_bytes()
        seal = json.loads(original)
        changed_summary = copy.deepcopy(seal)
        changed_summary['summary']['content']['package_id'] = 'fake-summary'
        for changed in (dict(seal, release_id='release-20261020T000000Z-'+'a'*12), changed_summary):
            with self.subTest(changed=changed['release_id']):
                path.write_text(json.dumps(changed), encoding='utf-8')
                with patch.object(self.manager, '_code', return_value=self.upgraded_code()):
                    with self.assertRaises(ReleaseInvalid):
                        self.manager.stage_code_upgrade('invalid seal', active['activation_token'])
        path.write_bytes(original)


if __name__ == '__main__':
    unittest.main()
