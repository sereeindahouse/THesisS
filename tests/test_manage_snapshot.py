"""Invented, fully isolated data; no real project captures, models or inference."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from CORE.website_corpus import PageParser, import_snapshot
from CORE.document_corpus import import_excerpts as import_documents
from CORE.client_tab_corpus import METHOD, build_extraction, import_excerpts as import_tabs
from content_store import ContentStore
from sqlite_retrieval import ReadOnlyContentStore
from website_retrieval import WebsiteRetriever
from tools import manage_snapshot as snapshots
from test_client_tab_corpus import captured_html
from test_content_store import fixture


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root, self.archive, self.target = (self.base / name for name in ('source', 'archive', 'restored'))
        self.capture = self.root / 'CORE/website/snapshots/fixture-run'
        self.capture.mkdir(parents=True)
        self.website = self.root / snapshots.DATABASES[0]
        self.content = self.root / snapshots.DATABASES[1]
        body = captured_html(text_record=True)
        parser = PageParser(); parser.feed(body.decode('utf-8')); extracted = parser.result()
        (self.capture / 'page.html').write_bytes(body)
        (self.capture / 'page.txt').write_text(extracted['text'], encoding='utf-8', newline='')
        asset = self.capture / 'rule.png'; asset.write_bytes(b'invented document original')
        url = 'https://nmct.edu.mn/departments/civil'
        manifest = dict(run_id='fixture-run', retrieved_at='2026-10-15T01:00:00+00:00', inventory=[],
            pages=[dict(url=url, status='ok', html_file='page.html', text_file='page.txt',
                html_sha256=snapshots.sha(self.capture/'page.html'),
                text_sha256=snapshots.sha(self.capture/'page.txt'),
                retrieved_at='2026-10-15T01:00:00+00:00', http={'charset':'utf-8','last_modified':None})],
            documents=[dict(url='https://nmct.edu.mn/rule.png', kind='png', file='rule.png',
                sha256=snapshots.sha(asset), size_bytes=asset.stat().st_size)])
        (self.capture / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        import_snapshot(self.website, self.capture)
        doc = dict(url='https://nmct.edu.mn/rule.png', version=1, asset_sha256=snapshots.sha(asset),
            title='Invented document', method='visual_transcription', reviewer_kind='assistant',
            coverage='selected_passages', passages=[dict(locator='test page1', text='Зөвхөн тестийн баримтын хэсэг.')])
        bundle = self.root / 'CORE/website/document-excerpts-20261012.json'
        bundle.write_text(json.dumps(dict(schema_version=1,run_id='fixture-run',documents=[doc])), encoding='utf-8')
        import_documents(self.website, bundle)
        bundle = self.root / 'CORE/website/client-tab-excerpts-20261015.json'
        tabs = build_extraction(body, url=url, title=extracted['title'])
        bundle.write_text(json.dumps(dict(schema_version=1,method=METHOD,run_id='fixture-run',pages=[tabs])), encoding='utf-8')
        import_tabs(self.website, bundle)
        with ContentStore(self.content) as store:
            store.import_content(fixture(), allow_draft=True)
        (self.root / 'models').mkdir(); (self.root/'models/do-not-copy.bin').write_bytes(b'model excluded')
        (self.root / 'audio').mkdir(); (self.root/'audio/private.wav').write_bytes(b'voice excluded')

    def manifest(self):
        return json.loads((self.archive/'manifest.json').read_bytes())

    def write_manifest(self, value):
        (self.archive/'manifest.json').write_text(json.dumps(value), encoding='utf-8')

    def test_actual_backup_restore_keeps_documents_tabs_ids_and_original_bytes(self):
        original = {p:snapshots.sha(p) for p in self.root.rglob('*') if p.is_file()}
        expected = snapshots.data_summary(self.root)
        result = snapshots.backup(self.root, self.archive)
        self.assertFalse(result['models_copied'])
        self.assertEqual(original, {p:snapshots.sha(p) for p in original})
        inventory = [r['path'] for r in self.manifest()['files']]
        self.assertFalse(any(p.startswith(('models/','audio/')) for p in inventory))
        self.assertIn('CORE/website/document-excerpts-20261012.json', inventory)
        manifest=self.manifest()
        self.assertNotIn('contains_personal_audio',manifest)
        self.assertEqual(set(manifest['capture_policy']['allowed_extensions']),
                         {'.html','.txt','.json','.png','.pdf'})
        self.assertFalse(manifest['capture_policy']['audio_model_files_allowed'])
        self.assertIn('not a complete experiment/project backup',manifest['scope'])
        # The original source disappears; restored readers cannot borrow it.
        self.root.rename(self.base/'original-offline')
        restored = snapshots.restore(self.archive, self.target)
        self.assertEqual(restored['verified'], expected)
        counts = restored['verified']['website']['counts']
        self.assertEqual(counts['indexed_document_passages'], 1)
        self.assertEqual(counts['indexed_client_tab_passages'], 3)
        with ReadOnlyContentStore(self.target / snapshots.DATABASES[1]) as store:
            self.assertEqual(store.counts()['sources'], 1)
            self.assertEqual(store.counts()['facts'], 1)
            self.assertEqual(store.counts()['faqs'], 1)
        self.assertTrue(WebsiteRetriever(self.target,use_dense=False).status()['available'])
        with closing(sqlite3.connect(self.target / snapshots.DATABASES[0])) as db:
            for table, columns in snapshots.PATH_COLUMNS.items():
                for column in columns:
                    for (value,) in db.execute('SELECT '+column+' FROM '+table):
                        self.assertTrue(Path(value).is_relative_to(self.target))

    def test_sqlite_backup_includes_committed_wal_without_copying_live_sidecars(self):
        with ContentStore(self.content) as writer:
            writer.connection.execute('PRAGMA journal_mode=WAL')
            writer.import_content(fixture(version=2), allow_draft=True)
            package = writer.package_id()
            self.assertTrue(Path(str(self.content)+'-wal').exists())
            snapshots.backup(self.root, self.archive)
            snapshots.restore(self.archive, self.target)
        with ReadOnlyContentStore(self.target / snapshots.DATABASES[1]) as store:
            self.assertEqual(store.package_id(), package)
        self.assertFalse(any('-wal' in r['path'] or '-shm' in r['path'] for r in self.manifest()['files']))

    def test_corrupt_payload_stops_before_destination_creation(self):
        snapshots.backup(self.root, self.archive)
        (self.archive/'payload/CORE/website/snapshots/fixture-run/page.html').write_bytes(b'changed')
        with self.assertRaises(ValueError):
            snapshots.restore(self.archive, self.target)
        self.assertFalse(self.target.exists())

    def test_traversal_unknown_external_and_case_collisions_stop_before_writes(self):
        snapshots.backup(self.root, self.archive)
        original = self.manifest()
        for name in ('../escaped', 'C:/outside', 'models/model.bin', 'CORE/website/snapshots/run/../../escape',
                     'CORE/website/snapshots/run/NUL.txt', 'CORE/website/snapshots/run/a?.txt',
                     'CORE/website/snapshots/run/a\n.txt'):
            value = json.loads(json.dumps(original)); value['files'][0]['path'] = name
            self.write_manifest(value)
            with self.subTest(path=name), self.assertRaises(ValueError):
                snapshots.restore(self.archive, self.target)
            self.assertFalse(self.target.exists())
        value=json.loads(json.dumps(original))
        duplicate=dict(next(row for row in value['files'] if '/snapshots/' in row['path']))
        directory, filename=duplicate['path'].rsplit('/',1)
        duplicate['path']=directory+'/'+filename.upper()
        value['files'].append(duplicate); self.write_manifest(value)
        with self.assertRaises(ValueError): snapshots.restore(self.archive,self.target)
        self.assertFalse(self.target.exists())

    def test_existing_outputs_and_original_capture_destination_never_overwritten(self):
        self.archive.mkdir(); marker=self.archive/'keep';marker.write_bytes(b'original')
        with self.assertRaises(FileExistsError): snapshots.backup(self.root,self.archive)
        self.assertEqual(marker.read_bytes(),b'original')
        other=self.base/'valid';snapshots.backup(self.root,other)
        self.target.mkdir();(self.target/'keep').write_bytes(b'original')
        with self.assertRaises(FileExistsError):snapshots.restore(other,self.target)
        with self.assertRaises(ValueError):snapshots.backup(self.root,self.capture/'new-backup')
        self.assertFalse((self.capture/'new-backup').exists())
        with self.assertRaises(FileExistsError):snapshots.restore(other,self.root)
        for target in (self.capture/'new-restore',self.root/'models/new-restore',self.root/'config/new-restore'):
            with self.subTest(target=target),self.assertRaises(ValueError):snapshots.restore(other,target)
            self.assertFalse(target.exists())

    def test_external_database_capture_reference_fails_before_output(self):
        outside=self.base/'external.html';outside.write_bytes(b'external')
        with closing(sqlite3.connect(self.website)) as db:
            db.execute('UPDATE captures SET html_path=?',(str(outside),));db.commit()
        with self.assertRaises(ValueError):snapshots.backup(self.root,self.archive)
        self.assertFalse(self.archive.exists())

    def test_unexpected_audio_or_model_inside_capture_tree_rejected_before_copying(self):
        for name in ('personal.wav','speech.MP3','weights.gguf','model.bin','vad.onnx'):
            path=self.capture/name
            path.write_bytes(b'injected non-corpus file')
            with self.subTest(name=name),self.assertRaises(ValueError):
                snapshots.backup(self.root,self.archive)
            self.assertFalse(self.archive.exists())
            path.unlink()

    def test_fk_corruption_fails_before_backup_output(self):
        with closing(sqlite3.connect(self.content)) as db:
            db.execute('PRAGMA foreign_keys=OFF')
            db.execute("UPDATE faq_facts SET fact_id='missing'");db.commit()
        with self.assertRaisesRegex(ValueError,'foreign-key'):snapshots.backup(self.root,self.archive)
        self.assertFalse(self.archive.exists())

    def test_symlink_source_or_archive_path_rejected_without_escape(self):
        link=self.capture/'link.txt'
        try:link.symlink_to(self.base/'outside')
        except OSError:
            # Windows without developer mode still checks the real no_links seam.
            with patch.object(Path,'is_symlink',lambda p:p==link):
                with self.assertRaises(ValueError):snapshots.no_links(link)
            return
        with self.assertRaises(ValueError):snapshots.backup(self.root,self.archive)
        self.assertFalse(self.archive.exists())


if __name__ == '__main__':
    unittest.main()
