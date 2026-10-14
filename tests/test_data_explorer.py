from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

import test_website_corpus as corpus_fixture
import test_document_corpus as document_fixture
from CORE.website_corpus import import_snapshot
from CORE.document_corpus import import_excerpts
from data_explorer import SourceExplorer,progress


class ExplorerTests(unittest.TestCase):
    def setUp(self):
        self.helper=corpus_fixture.WebsiteCorpusTests();self.helper.setUp()
        self.root,self.db=self.helper.root,self.helper.database
        import_snapshot(self.db,self.helper.capture())
        self.explorer=SourceExplorer(self.root,self.db)

    def tearDown(self):self.helper.tearDown()

    def test_catalogue_uses_actual_readonly_snapshot_without_models(self):
        before=hashlib.sha256(self.db.read_bytes()).hexdigest()
        with patch('website_retrieval._LocalE5.load',side_effect=AssertionError('No model needed')):
            result=self.explorer.snapshot()
        self.assertEqual(result['summary']['pages'],1)
        self.assertEqual(result['summary']['indexed_passages'],1)
        row=result['sources'][0]
        self.assertEqual(row['topic'],'contact')
        self.assertIn('75777799',row['text'])
        self.assertNotIn('secret javascript',row['text'])
        self.assertEqual(row['coverage'],'captured_html_text')
        self.assertEqual(before,hashlib.sha256(self.db.read_bytes()).hexdigest())

    def test_latest_capture_replaces_display_without_deleting_history(self):
        capture=self.helper.capture('run2','Утас өөрчлөгдсөн 2027')
        data=json.loads((capture/'manifest.json').read_text(encoding='utf-8'))
        data['retrieved_at']='2026-10-11T00:00:00+00:00'
        (capture/'manifest.json').write_text(json.dumps(data),encoding='utf-8')
        import_snapshot(self.db,capture)
        rows=self.explorer.snapshot()['sources']
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['version'],2)
        self.assertIn('2027',rows[0]['text'])
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM pages').fetchone()[0],2)

    def test_missing_database_is_empty_not_hardcoded_school_counts(self):
        result=SourceExplorer(self.root,self.root/'missing.db').snapshot()
        self.assertFalse(result['summary']['available'])
        self.assertEqual(result['summary']['pages'],0)
        self.assertEqual(result['sources'],[])

    def test_progress_counts_derived_from_explicit_states(self):
        (self.root/'config').mkdir()
        path=self.root/'config/project-progress.json'
        path.write_text(json.dumps(dict(schema_version=1,completed=100,total=100,
            milestones=[dict(id='a',state='done'),dict(id='b',state='in_progress'),dict(id='c',state='todo')])),encoding='utf-8')
        value=progress(self.root)
        self.assertEqual((value['completed'],value['total']),(1,3))
        value['milestones'][0]['state']='imagined'
        path.write_text(json.dumps(value),encoding='utf-8')
        with self.assertRaises(ValueError):progress(self.root)

    def test_curated_facts_and_faqs_whitelisted_without_private_notes(self):
        import test_demo_server as content_fixture
        from content_store import ContentStore
        content=content_fixture.fixture()
        content['sources'][0]['notes']='private working annotation'
        content['faqs'][0]['notes']='private draft commentary'
        path=self.root/'content.db'
        with ContentStore(path) as store:store.import_content(content,allow_draft=True)
        before=hashlib.sha256(path.read_bytes()).hexdigest()
        result=SourceExplorer(self.root,self.db,path).snapshot()['curated']
        self.assertTrue(result['available'])
        self.assertEqual(result['counts']['faqs'],1)
        self.assertEqual(result['faqs'][0]['question'],'Тест үү?')
        self.assertEqual(result['facts'][0]['source_refs'][0]['document_id'],'test.source')
        self.assertNotIn('private',json.dumps(result,ensure_ascii=False))
        self.assertNotIn('approved_by',result['sources'][0])
        self.assertEqual(before,hashlib.sha256(path.read_bytes()).hexdigest())

    def test_nonofficial_url_is_not_offered_as_school_source(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.execute('UPDATE pages SET url=?',('javascript:alert(1)',))
            db.execute('UPDATE captures SET url=?',('javascript:alert(1)',))
            db.execute('UPDATE chunks SET url=?',('javascript:alert(1)',))
            db.commit()
        result=self.explorer.snapshot()
        self.assertEqual(result['summary']['pages'],0)
        self.assertEqual(result['sources'],[])


class ExplorerDocumentTests(unittest.TestCase):
    def setUp(self):
        self.helper=document_fixture.DocumentCorpusTests();self.helper.setUp()
        self.root,self.db=self.helper.root,self.helper.db
        # Captured format header is synthetic; no image/OCR quality is inferred.
        data=b'\x89PNG\r\n\x1a\n'+b'synthetic immutable document'
        self.helper.asset.write_bytes(data)
        sha=hashlib.sha256(data).hexdigest()
        with closing(sqlite3.connect(self.db)) as db:
            db.execute('UPDATE assets SET sha256=?,size_bytes=?',(sha,len(data)));db.commit()
        self.helper.doc['asset_sha256']=sha;self.helper.write()
        import_excerpts(self.db,self.helper.bundle)
        self.explorer=SourceExplorer(self.root,self.db)

    def tearDown(self):self.helper.tearDown()

    def document_row(self):return next(row for row in self.explorer.snapshot()['sources'] if row['kind']=='png')

    def test_selected_excerpt_provenance_and_original_bytes(self):
        row=self.document_row()
        self.assertEqual(row['coverage'],'selected_passages')
        self.assertEqual(row['reviewer_kind'],'assistant')
        self.assertEqual(row['document_passages'],2)
        self.assertEqual(row['passages'][0]['locator'],'х.2, IV.6')
        data,mime=self.explorer.document(row['id'])
        self.assertEqual(data,self.helper.asset.read_bytes());self.assertEqual(mime,'image/png')
        with self.assertRaises(FileNotFoundError):self.explorer.document('../../private.txt')

    def test_changed_asset_refuses_preview_and_excludes_transcription(self):
        row=self.document_row()
        self.helper.asset.write_bytes(b'\x89PNG\r\n\x1a\nchanged')
        with self.assertRaises(ValueError):self.explorer.document(row['id'])
        self.assertEqual(self.explorer.snapshot()['summary']['document_passages'],0)

    def test_capture_path_must_stay_in_project_snapshot(self):
        row=self.document_row()
        with closing(sqlite3.connect(self.db)) as db:
            db.execute('UPDATE assets SET path=?',(str(self.root.parent/'outside.png'),));db.commit()
        with self.assertRaises(ValueError):self.explorer.document(row['id'])

    def test_document_preview_id_is_tied_to_original_not_excerpt_version(self):
        row=self.document_row()
        self.helper.doc['version']=2
        self.helper.doc['passages'][0]['text']='Шинэ хувилбарын тайлбар. Цээж зургийг PNG файлаар оруулна.'
        self.helper.write();import_excerpts(self.db,self.helper.bundle)
        updated=self.document_row()
        self.assertEqual(updated['version'],2)
        self.assertEqual(row['preview_url'],updated['preview_url'])
        self.assertEqual(self.explorer.document(updated['id'])[1],'image/png')
