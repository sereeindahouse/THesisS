import hashlib
from pathlib import Path
import sqlite3
import unittest
from contextlib import closing
from unittest.mock import patch

import test_website_corpus as corpus_tests
from CORE.website_corpus import import_snapshot
from website_retrieval import WebsiteRetriever, search_terms, single_query_code, diversity_group, preceding_entity_codes


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

    def test_reviewed_requirement_spelling_retrieves_the_same_literal_evidence(self):
        self.inject_rows([dict(source_id='eligibility',
            text='Элсэлтийн шаардлага: суурь боловсролын гэрчилгээтэй байна.',
            title='Элсэлт', start_offset=0, end_offset=68)])
        typed = 'Сургуульд ороход ямар шаардалага байдаг вэ'
        corrected = 'Сургуульд ороход ямар шаардлага байдаг вэ'
        before = typed
        typo = self.retriever.search(typed)
        canonical = self.retriever.search(corrected)
        self.assertEqual(typed, before)
        self.assertEqual(typo['candidates'][0]['text'], canonical['candidates'][0]['text'])
        self.assertEqual(typo['candidates'][0]['source_id'], 'eligibility')
        self.assertIn('шаардлага', typo['candidates'][0]['matched_terms'])

    def test_search_spelling_does_not_fuzzily_rewrite_names_identifiers_or_negation(self):
        for typo, canonical in [('шаардалага','шаардлага'),
                                ('шаардалагатай','шаардлагатай'),
                                ('шаардалагад','шаардлагад')]:
            self.assertEqual(search_terms(typo), search_terms(canonical))
        for token in ('ШаардалагаБанк', 'шаардалага2027', 'шаардлга', 'ЕБС'):
            self.assertNotEqual(search_terms(token), search_terms('шаардлага'))
        self.assertIn('шаардлага', search_terms('шаардалага байхгүй'))
        self.assertIn('байхгүй', search_terms('шаардалага байхгүй'))

    def test_corrected_requirement_spelling_does_not_create_evidence_for_unknown_topic(self):
        self.inject_rows([dict(source_id='unrelated', text='Сургуулийн холбоо барих утас.',
                              title='Холбоо барих', start_offset=0, end_offset=32)])
        self.assertEqual(self.retriever.search('Сургуульд ороход ямар шаардалага байдаг вэ')['candidates'], [])

    def test_location_case_endings_match_the_same_source_topic(self):
        self.assertIn('түүх',search_terms('Түүхэнд юу гэж дурдсан бэ?'))
        self.assertIn('түүх',search_terms('Түүхийн товчоон'))

    def test_single_named_code_does_not_turn_months_or_file_types_into_entities(self):
        self.assertEqual(single_query_code('CNC лабораторийн зориулалт юу вэ?'),'cnc')
        self.assertEqual(single_query_code('cnc лабораторийн зориулалт юу вэ?', {'cnc'}),'cnc')
        self.assertIsNone(single_query_code('ordinary English words', {'cnc'}))
        for query in ['I ба V курсийн тоо','IX–X сард юу хийх вэ?','PDF файлын хэмжээ MB-ээр',
                      'CAD болон CAM ялгаа','NMCT сургалтын төлбөр']:
            self.assertIsNone(single_query_code(query))

    def inject_rows(self, rows):
        self.retriever._refresh()
        template=self.retriever._rows[0]
        self.retriever._rows=[dict(template,**row) for row in rows]
        self.retriever._lexical_passages=[' '.join(search_terms(row['title']+' '+row['text'])) for row in self.retriever._rows]
        self.retriever._body_terms=[set(search_terms(row['text'])) for row in self.retriever._rows]
        self.retriever._term_weights={term:1.0 for terms in self.retriever._body_terms for term in terms}

    def test_client_field_budget_preserves_complementary_fields_after_html(self):
        rows=[]
        for scope in ['main_element','client_tab_field_excerpt']:
            for number in range(3):
                text='Зорилго: суралцагчдад ойлголт өгнө. '+str(number)
                rows.append(dict(source_id=scope+str(number),title='Танилцуулга',text=text,
                    text_scope=scope,source_locator='field.'+str(number),
                    start_offset=number*1000,end_offset=number*1000+len(text)))
        self.inject_rows(rows)
        found=self.retriever.search('Зорилго юу вэ?',limit=10)['candidates']
        self.assertEqual(len(found),4)
        self.assertEqual(sum(row['text_scope']=='client_tab_field_excerpt' for row in found),2)

    def test_literal_code_filters_wrong_subject_even_when_its_dense_score_is_higher(self):
        rows=[dict(source_id='correct',title='Танилцуулга',text='CNC лабораторийн зорилго бол боловсруулах дадлага.',
                   start_offset=0,end_offset=60),
              dict(source_id='wrong',title='Танилцуулга',text='CAD лабораторийн зорилго бол зургийн дадлага.',
                   start_offset=1000,end_offset=1060)]
        self.inject_rows(rows)
        with patch.object(self.retriever,'_dense',return_value=[.1,.99]):
            found=self.retriever.search('CNC лабораторийн зорилго?')['candidates']
        self.assertEqual([row['source_id'] for row in found],['correct'])

    def test_literal_code_cannot_be_revived_by_tuition_category_boost(self):
        self.inject_rows([
            dict(source_id='correct',title='CNC лаборатори',text='CNC тоног төхөөрөмжтэй дадлагын лаборатори.',
                 start_offset=0,end_offset=70),
            dict(source_id='wrong',title='Төлбөр',text='Сургалтын төлбөр жилд 9,000 төгрөг.',
                 start_offset=1000,end_offset=1070)])
        for code in ['CNC','cnc']:
            with self.subTest(code=code), patch.object(self.retriever,'_dense',return_value=[.1,.99]):
                query=code+' лабораторийн сургалтын төлбөр хэд вэ?'
                found=self.retriever.search(query)['candidates']
                self.assertEqual([row['source_id'] for row in found],['correct'])
                # Ranking experiments do not silently acquire production gates.
                ranked=self.retriever.search(query,mode='rrf_boosted')['candidates']
                self.assertIn('wrong',[row['source_id'] for row in ranked])

    def test_acronym_case_equivalence_uses_observed_source_acronyms(self):
        self.inject_rows([
            dict(source_id='title',title='CNC лаборатори',text='Төхөөрөмжийн танилцуулга.',start_offset=0,end_offset=60),
            dict(source_id='lower',title='Танилцуулга',text='cnc лабораторийн дадлага.',start_offset=1000,end_offset=1060),
            dict(source_id='other',title='Танилцуулга',text='CAD лабораторийн дадлага.',start_offset=2000,end_offset=2060)])
        upper=self.retriever.search('CNC лабораторийн дадлага?')['candidates']
        lower=self.retriever.search('cnc лабораторийн дадлага?')['candidates']
        self.assertEqual([s['source_id'] for s in upper],[s['source_id'] for s in lower])
        self.assertIn('lower',[s['source_id'] for s in lower])
        self.assertNotIn('other',[s['source_id'] for s in lower])

    def test_cut_company_continuation_keeps_local_antecedent_without_changing_evidence(self):
        text='ALFA компани систем хөгжүүлдэг. '+('тайлбар '*25)+'Тус компанитай хамтран '+('ажил '*20)+'Ярилцлагад оюутнууд оролцсон.'
        start=text.index('ажил ')+70
        self.assertIn('alfa',preceding_entity_codes(text,start))
        self.assertFalse(preceding_entity_codes('ALFA компани\nШинэ хэсэг',len('ALFA компани\n')))
        self.assertFalse(preceding_entity_codes('ALFA компани\nШинэ хэсэг. Тус компанитай ажиллав.',30))
        self.assertFalse(preceding_entity_codes('ALFA компани '+('тайлбар '*60)+'Тус компанитай ажиллав.',500))
        self.inject_rows([
            dict(source_id='continuation',title='Хамтын ажиллагаа',text=text[start:],start_offset=start,end_offset=len(text)),
            dict(source_id='name',title='ALFA',text='ALFA компани хөгжүүлэлт хийдэг.',start_offset=1000,end_offset=1060)])
        self.retriever._context_codes={'continuation':preceding_entity_codes(text,start)}
        found=self.retriever.search('alfa компанийн ярилцлагын явц?')['candidates']
        continuation=next(s for s in found if s['source_id']=='continuation')
        self.assertEqual(continuation['text'],text[continuation['start_offset']:continuation['end_offset']])

    def test_imported_cut_html_uses_antecedent_for_lowercase_query_only_as_scope(self):
        text='ALFA компани систем хөгжүүлдэг. '+('тайлбар '*25)+'Тус компанитай хамтран '+('ажил '*20)+'Ярилцлагад оюутнууд оролцсон.'
        import_snapshot(self.db,self.helper.capture('run2',text=text))
        with closing(sqlite3.connect(self.db)) as db:
            full=db.execute('SELECT text FROM pages ORDER BY version DESC LIMIT 1').fetchone()[0]
            start=full.index('ажил ')+70
            db.execute('DELETE FROM chunks')
            db.execute('INSERT INTO chunks VALUES(?,?,?,?,?,?)',
                       ('https://nmct.edu.mn/contact',2,0,start,len(full),full[start:]))
            db.commit()
        result=self.retriever.search('alfa компанийн ярилцлагын явц?')
        self.assertEqual(len(result['candidates']),1)
        row=result['candidates'][0]
        self.assertNotIn('ALFA',row['text'])
        self.assertEqual(row['text'],full[row['start_offset']:row['end_offset']])
        self.assertFalse(row['query_answer_support_established'])

    def test_corpus_revision_changes_id(self):
        before=self.retriever.status()['corpus_id']
        import_snapshot(self.db,self.helper.capture('run2',text='Сургалтын төлбөр: өөр эх.'))
        self.assertNotEqual(before,self.retriever.status()['corpus_id'])

    def test_committed_wal_capture_refreshes_warm_search_without_checkpoint(self):
        # Keep another connection alive so committed changes stay in the WAL.
        with closing(sqlite3.connect(self.db)) as writer:
            self.assertEqual(writer.execute('PRAGMA journal_mode=WAL').fetchone()[0],'wal')
            writer.execute('PRAGMA wal_autocheckpoint=0')
            # Pin an old read snapshot, as an independent active reader may do.
            # A second connection can still publish a committed WAL revision.
            writer.execute('BEGIN')
            writer.execute('SELECT * FROM crawl_runs').fetchall()
            before=self.retriever.status()['corpus_id']
            main_stamp=(self.db.stat().st_mtime_ns,self.db.stat().st_size)
            self.retriever._embeddings=object()
            import_snapshot(self.db,self.helper.capture('run2',text='Сургалтын төлбөр: жилд 9,400,000 ₮.'))
            self.assertEqual(main_stamp,(self.db.stat().st_mtime_ns,self.db.stat().st_size))
            self.assertTrue(Path(str(self.db)+'-wal').is_file())
            result=self.retriever.search('Сургалтын төлбөр хэд вэ?')
            self.assertNotEqual(before,result['corpus_id'])
            self.assertIn('9,400,000',result['candidates'][0]['text'])
            self.assertNotIn('8,280,000',result['candidates'][0]['text'])
            self.assertIsNone(self.retriever._embeddings)

    def test_committed_wal_validity_change_removes_cached_expired_source(self):
        with closing(sqlite3.connect(self.db)) as writer:
            writer.execute('PRAGMA journal_mode=WAL')
            writer.execute('PRAGMA wal_autocheckpoint=0')
            self.assertEqual(len(self.retriever.search('төлбөр')['candidates']),1)
            main_stamp=(self.db.stat().st_mtime_ns,self.db.stat().st_size)
            writer.execute("UPDATE pages SET valid_until='2000-01-01'")
            writer.commit()
            self.assertEqual(main_stamp,(self.db.stat().st_mtime_ns,self.db.stat().st_size))
            self.assertFalse(self.retriever.search('төлбөр')['candidates'])

    def test_wal_uncommitted_and_rolled_back_edits_never_enter_search(self):
        with closing(sqlite3.connect(self.db)) as writer:
            writer.execute('PRAGMA journal_mode=WAL')
            before=self.retriever.search('төлбөр')
            writer.execute('BEGIN')
            writer.execute("UPDATE pages SET valid_until='2000-01-01'")
            during=self.retriever.search('төлбөр')
            self.assertEqual(before['corpus_id'],during['corpus_id'])
            self.assertEqual(len(during['candidates']),1)
            writer.rollback()
            after=self.retriever.search('төлбөр')
            self.assertEqual(before['corpus_id'],after['corpus_id'])
            self.assertEqual(len(after['candidates']),1)

    def test_unchanged_wal_snapshot_preserves_loaded_dense_vectors(self):
        with closing(sqlite3.connect(self.db)) as writer:
            writer.execute('PRAGMA journal_mode=WAL')
            before=self.retriever.status()['corpus_id']
            vectors=object()
            self.retriever._embeddings=vectors
            for _ in range(3):
                self.assertEqual(before,self.retriever.status()['corpus_id'])
                self.assertIs(self.retriever._embeddings,vectors)

if __name__=='__main__':
    unittest.main()
