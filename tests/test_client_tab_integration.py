from contextlib import closing
import hashlib
import sqlite3
import unittest
from unittest.mock import patch

import test_website_corpus as fixtures
from CORE.website_corpus import import_snapshot
from data_explorer import SourceExplorer
from website_retrieval import WebsiteRetriever


class ClientTabIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.helper=fixtures.WebsiteCorpusTests(); self.helper.setUp()
        self.root,self.db=self.helper.root,self.helper.database
        import_snapshot(self.db,self.helper.capture(text='Холбоо барих мэдээлэл.'))

    def tearDown(self): self.helper.tearDown()

    def row(self,locator='goalsJson /goals/0',identifier='tab-a'):
        text='Тэнхимийн зорилго нь бүтээлч инженер бэлтгэх.'
        return dict(source_id=identifier,url='https://nmct.edu.mn/contact',version=1,
            title='Тэнхимийн зорилго',retrieved_at='2026-10-15T00:00:00+00:00',
            source_updated_at=None,text_scope='client_tab_field_excerpt',valid_from=None,
            valid_until=None,chunk_id=0,start_offset=0,end_offset=len(text),text=text,
            excerpt=text,page_years=[],page_header='Тэнхим',snapshot_only=True,
            validity_unknown=True,source_locator=locator,extraction_method='next_flight_whitelist_v1',
            reviewer_kind='deterministic_parser',html_sha256='a'*64,field_sha256='b'*64,
            excerpt_coverage='selected_client_fields')

    def search(self,rows):
        with patch('website_retrieval.read_client_tab_rows',return_value=(rows,[])):
            return WebsiteRetriever(self.root,self.db,use_dense=False).search('Тэнхимийн зорилго?')

    def test_valid_client_fields_readonly_and_separate_document_count(self):
        before=hashlib.sha256(self.db.read_bytes()).hexdigest()
        value=self.search([self.row()])
        self.assertEqual(value['counts']['indexed_client_tab_passages'],1)
        self.assertEqual(value['counts']['indexed_document_passages'],0)
        self.assertEqual(value['candidates'][0]['source_locator'],'goalsJson /goals/0')
        self.assertEqual(before,hashlib.sha256(self.db.read_bytes()).hexdigest())

    def test_parent_rejection_and_dates_cannot_be_bypassed(self):
        for update in ("approval_status='rejected'","valid_from='2099-01-01'","valid_until='2000-01-01'"):
            with self.subTest(update=update),closing(sqlite3.connect(self.db)) as db:
                db.execute('PRAGMA ignore_check_constraints=ON')
                db.execute("UPDATE pages SET approval_status='draft',valid_from=NULL,valid_until=NULL")
                db.execute('UPDATE pages SET '+update); db.commit()
                self.assertFalse(self.search([self.row()])['candidates'])

    def test_unmatched_parent_version_excluded(self):
        row=self.row(); row['version']=99
        self.assertFalse(self.search([row])['candidates'])

    def test_different_json_fields_have_distinct_coordinate_spaces(self):
        value=self.search([self.row(),self.row('goalsJson /objectives/0','tab-b')])
        self.assertEqual(len(value['candidates']),2)

    def test_duplicate_same_field_overlap_still_deduplicated(self):
        value=self.search([self.row(),self.row(identifier='tab-b')])
        self.assertEqual(len(value['candidates']),1)

    def test_explorer_displays_selected_fields_as_html_not_image_excerpt(self):
        with patch('website_retrieval.read_client_tab_rows',return_value=([self.row()],[])):
            value=SourceExplorer(self.root,self.db).snapshot()
        self.assertEqual(value['summary']['client_tab_passages'],1)
        self.assertEqual(value['summary']['indexed_html_passages'],1)
        self.assertEqual(value['summary']['document_passages'],0)
        self.assertEqual(value['sources'][0]['client_tab_passages'],1)
        self.assertIn('goalsJson /goals/0',value['sources'][0]['text'])
        self.assertIn('бүтээлч инженер',value['sources'][0]['text'])
        source=value['sources'][0]
        self.assertEqual(source['retrieved_at'],'2026-10-10T00:00:00+00:00')
        self.assertEqual(source['passages'][0]['retrieved_at'],'2026-10-15T00:00:00+00:00')
        self.assertEqual(source['display_text_sha256'],hashlib.sha256(source['text'].encode()).hexdigest())
        self.assertNotEqual(source['display_text_sha256'],source['main_text_sha256'])

if __name__=='__main__': unittest.main()
