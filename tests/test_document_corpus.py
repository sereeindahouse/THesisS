from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import unittest

import test_website_corpus as corpus_tests
from CORE.website_corpus import import_snapshot
from CORE.document_corpus import import_excerpts
from website_retrieval import WebsiteRetriever


class DocumentCorpusTests(unittest.TestCase):
    def setUp(self):
        self.helper = corpus_tests.WebsiteCorpusTests()
        self.helper.setUp()
        self.root, self.db = self.helper.root, self.helper.database
        self.capture = self.helper.capture(text='Сургуулийн танилцуулга.')
        import_snapshot(self.db, self.capture)
        with closing(sqlite3.connect(self.db)) as db:
            self.run_id = db.execute('SELECT run_id FROM crawl_runs').fetchone()[0]
            self.asset = self.capture/'original.png'
            self.asset.write_bytes(b'synthetic document bytes')
            self.sha = hashlib.sha256(self.asset.read_bytes()).hexdigest()
            self.url = 'https://nmct.edu.mn/elseltiin-juram/page-2.png'
            db.execute('INSERT INTO assets VALUES(?,?,?,?,?,?,?)',(self.run_id,self.url,'admissions_rule_scan',str(self.asset),self.sha,self.asset.stat().st_size,'binary_only'))
            db.commit()
        self.doc = dict(url=self.url,version=1,asset_sha256=self.sha,title='2026-2027 оны журам',
            method='visual_transcription',reviewer_kind='assistant',coverage='selected_passages',
            passages=[dict(locator='х.2, IV.6',text='Сүүлийн 6 сарын цээж зургийг jpeg, png, jpg файлаар оруулна.'),
                      dict(locator='х.2, V.4',text='Ярилцлагын шалгалтад эцэг эхтэйгээ орно. Ярилцлага 15 минут үргэлжилнэ.')])
        self.bundle = self.root/'excerpts.json'
        self.write()

    def tearDown(self):
        self.helper.tearDown()

    def write(self):
        self.bundle.write_text(json.dumps(dict(schema_version=1,run_id=self.run_id,documents=[self.doc]),ensure_ascii=False),encoding='utf-8')

    def search(self,query):
        return WebsiteRetriever(self.root,self.db,use_dense=False).search(query)

    def test_import_idempotent_and_provenance_preserved(self):
        self.assertEqual(import_excerpts(self.db,self.bundle)['added_documents'],1)
        self.assertEqual(import_excerpts(self.db,self.bundle)['added_documents'],0)
        before=hashlib.sha256(self.db.read_bytes()).hexdigest()
        row=self.search('Цээж зургийн формат?')['candidates'][0]
        self.assertEqual(row['source_locator'],'х.2, IV.6')
        self.assertEqual(row['text'],self.doc['passages'][0]['text'])
        self.assertEqual(row['reviewer_kind'],'assistant')
        self.assertEqual(row['asset_sha256'],self.sha)
        self.assertEqual(before,hashlib.sha256(self.db.read_bytes()).hexdigest())

    def test_same_version_cannot_be_rewritten(self):
        import_excerpts(self.db,self.bundle)
        self.doc['passages'][0]['text']='Өөрчлөгдсөн журам. Зургийн нөхцөл өөр.'
        self.write()
        with self.assertRaises(ValueError): import_excerpts(self.db,self.bundle)

    def test_new_version_supersedes_old_and_invalidates_cache(self):
        import_excerpts(self.db,self.bundle)
        retriever=WebsiteRetriever(self.root,self.db,use_dense=False)
        before=retriever.status()['corpus_id']
        self.doc['version']=2
        self.doc['passages'][0]['text']='Цээж зургийг PNG файлаар оруулна.'
        self.write()
        import_excerpts(self.db,self.bundle)
        self.assertNotEqual(before,retriever.status()['corpus_id'])
        rows=retriever.search('Цээж зураг')['candidates']
        self.assertEqual(rows[0]['version'],2)
        self.assertNotIn('jpeg',rows[0]['text'])

    def test_hash_mismatch_fails_before_import(self):
        self.asset.write_bytes(b'tampered')
        with self.assertRaises(ValueError): import_excerpts(self.db,self.bundle)
        self.assertEqual(self.search('цээж зураг')['counts'].get('indexed_document_passages'),0)

    def test_tampered_payload_is_not_answer_evidence(self):
        import_excerpts(self.db,self.bundle)
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("UPDATE document_extractions SET payload_sha256=?",('0'*64,))
            db.commit()
        result=self.search('цээж зураг')
        self.assertFalse(result['candidates'])
        self.assertTrue(any('Excluded document' in w for w in result['warnings']))

    def test_unknown_or_nonofficial_asset_rejected(self):
        self.doc['url']='https://example.com/fake.png'
        self.write()
        with self.assertRaises(ValueError): import_excerpts(self.db,self.bundle)

    def test_changed_asset_is_not_answer_evidence(self):
        import_excerpts(self.db,self.bundle)
        self.asset.write_bytes(b'changed after import')
        self.assertFalse(self.search('Цээж зураг')['candidates'])

    def test_two_nonoverlapping_clauses_same_image_can_return(self):
        import_excerpts(self.db,self.bundle)
        rows=self.search('цээж зураг ярилцлага')['candidates']
        self.assertEqual(len(rows),2)

    def test_photo_inflection_retrieves_document_without_literal_query_word(self):
        import_excerpts(self.db,self.bundle)
        result=self.search('Зургаа ямар форматаар оруулах вэ?')
        self.assertEqual(result['candidates'][0]['source_locator'],'х.2, IV.6')

    def test_interview_inflection_keeps_duration_passage(self):
        import_excerpts(self.db,self.bundle)
        result=self.search('Ярилцлагын хугацаа хэд вэ?')
        self.assertEqual(result['candidates'][0]['source_locator'],'х.2, V.4')

    def test_no_implicit_full_ocr_or_school_signoff(self):
        self.doc['coverage']='complete_ocr'
        self.write()
        with self.assertRaises(ValueError): import_excerpts(self.db,self.bundle)


if __name__=='__main__': unittest.main()
