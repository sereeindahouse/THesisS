import hashlib
from pathlib import Path
import sqlite3
import unittest
from contextlib import closing
from unittest.mock import patch

import test_website_corpus as corpus_tests
from CORE.website_corpus import import_snapshot
from website_retrieval import WebsiteRetriever, search_terms


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.helper=corpus_tests.WebsiteCorpusTests()
        self.helper.setUp()
        self.root,self.db=self.helper.root,self.helper.database
        import_snapshot(self.db,self.helper.capture(text='Сургалтын төлбөр: жилд 8,280,000 ₮.'))
        self.retriever=WebsiteRetriever(self.root,self.db,use_dense=False)
    def tearDown(self):
        self.helper.tearDown()

    def mutate(self,sql):
        with closing(sqlite3.connect(self.db)) as db:
            db.execute(sql)
            db.commit()

    def test_readonly_exact_evidence(self):
        before=hashlib.sha256(self.db.read_bytes()).hexdigest()
        r=self.retriever.search('Сургалтын төлбөр хэд вэ?')
        self.assertEqual(len(r['candidates']),1)
        s=r['candidates'][0]
        with closing(sqlite3.connect(self.db)) as db:
            text=db.execute('select text from pages').fetchone()[0]
        self.assertEqual(text[s['start_offset']:s['end_offset']],s['text'])
        self.assertEqual(before,hashlib.sha256(self.db.read_bytes()).hexdigest())
        self.assertFalse(r['query_answer_support_established'])

    def test_unknown_topic_no_lexical_answer(self):
        self.assertFalse(self.retriever.search('Ангараг дээр муур байдаг уу?')['candidates'])

    def test_dense_nearest_neighbor_alone_not_evidence(self):
        with patch.object(self.retriever,'_dense',return_value=[.99]):
            self.assertFalse(self.retriever.search('Ангараг муур')['candidates'])

    def test_rejected_source_not_returned(self):
        # Current importer only permits drafts; simulate a corrupt/future row
        # in this disposable fixture to exercise the defensive reader.
        with closing(sqlite3.connect(self.db)) as db:
            db.execute('PRAGMA ignore_check_constraints=ON')
            db.execute("UPDATE pages SET approval_status='rejected'")
            db.commit()
        self.assertFalse(self.retriever.search('төлбөр')['candidates'])

    def test_expired_source_not_returned(self):
        self.mutate("UPDATE pages SET valid_until='2000-01-01'")
        self.assertFalse(self.retriever.search('төлбөр')['candidates'])

    def test_future_source_not_returned(self):
        self.mutate("UPDATE pages SET valid_from='2099-01-01'")
        self.assertFalse(self.retriever.search('төлбөр')['candidates'])

    def test_tampered_offsets_not_evidence(self):
        self.mutate("UPDATE chunks SET text='invented payment information'")
        self.assertFalse(self.retriever.search('төлбөр')['candidates'])

    def test_unrelated_database_graceful_status(self):
        p=self.root/'bad.db'
        with closing(sqlite3.connect(p)) as db:
            db.execute('CREATE TABLE other(x)')
            db.commit()
        self.assertFalse(WebsiteRetriever(self.root,p,use_dense=False).status()['available'])

    def test_morphology_and_boilerplate_terms(self):
        self.assertIn('элсэлт',search_terms('Элсэхэд'))
        self.assertIn('мэргэжил',search_terms('мэргэжлээр'))
        self.assertEqual(search_terms('дээр боломжтой суралцах'),[])

    def test_corpus_revision_changes_id(self):
        before=self.retriever.status()['corpus_id']
        import_snapshot(self.db,self.helper.capture('run2',text='Сургалтын төлбөр: өөр эх.'))
        self.assertNotEqual(before,self.retriever.status()['corpus_id'])

if __name__=='__main__':
    unittest.main()
