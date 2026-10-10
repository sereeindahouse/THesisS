import hashlib
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from CORE.website_corpus import PageParser, canonical_url, import_snapshot, search_website, split_chunks, website_status


class WebsiteCorpusTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.database = self.root / 'website.db'

    def tearDown(self):
        self.temporary.cleanup()

    def capture(self, run='run1', text='Сургуулийн утас +976 75777799', extra=None):
        directory = self.root / run
        directory.mkdir()
        html = f'<html><head><title>School</title><script>secret javascript</script></head><body><nav>Menu</nav><main><h1>Холбоо барих</h1><p>{text}</p></main><footer>Footer</footer></body></html>'.encode('utf-8')
        parser = PageParser(); parser.feed(html.decode())
        extracted = parser.result()['text']
        (directory / 'page.html').write_bytes(html)
        (directory / 'page.txt').write_text(extracted, encoding='utf-8', newline='')
        manifest = {'run_id':run,'retrieved_at':'2026-10-10T00:00:00+00:00','inventory':[],
          'pages':[{'url':'https://nmct.edu.mn/contact','status':'ok','html_file':'page.html','text_file':'page.txt',
            'html_sha256':hashlib.sha256(html).hexdigest(),'text_sha256':hashlib.sha256(extracted.encode()).hexdigest(),
            'retrieved_at':'2026-10-10T00:00:00+00:00','http':{'charset':'utf-8','last_modified':None}}]}
        if extra: extra(manifest)
        (directory / 'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False),encoding='utf-8')
        return directory

    def test_same_origin_normalization_and_unicode_paths(self):
        self.assertEqual(canonical_url('/news/монгол'), 'https://nmct.edu.mn/news/%D0%BC%D0%BE%D0%BD%D0%B3%D0%BE%D0%BB')
        self.assertEqual(canonical_url('http://www.nmct.edu.mn/contact/?utm_source=x#top'),'https://nmct.edu.mn/contact')
        self.assertEqual(canonical_url('/news?page=2'), 'https://nmct.edu.mn/news?page=2')
        for value in ('https://outside.mn/x','/admin','/%61dmin','/elselt/password-reset','/login','/news?token=x','/news?page=0'):
            self.assertIsNone(canonical_url(value), value)

    def test_html_main_is_separate_from_navigation_and_scripts(self):
        parser = PageParser(); parser.feed('<title>Site</title><nav>Menu</nav><main><h1>Утас</h1><p><b>Шинэ</b><span>Монгол</span></p></main><script>bad</script>')
        value = parser.result()
        self.assertEqual(value['title'],'Утас')
        self.assertIn('Шинэ Монгол',value['text'])
        self.assertNotIn('Menu',value['text'])
        self.assertNotIn('bad',value['full_text'])

    def test_chunks_preserve_exact_offsets_and_cover_entire_text(self):
        text='Монгол хэл 2026\n'*200
        chunks=split_chunks(text,size=150,overlap=20)
        self.assertEqual(chunks[0]['start'],0); self.assertEqual(chunks[-1]['end'],len(text))
        for chunk in chunks: self.assertEqual(chunk['text'],text[chunk['start']:chunk['end']])
        for left,right in zip(chunks,chunks[1:]): self.assertLessEqual(right['start'],left['end'])

    def test_import_idempotence_and_draft_only(self):
        capture=self.capture()
        self.assertTrue(import_snapshot(self.database,capture)['imported'])
        self.assertFalse(import_snapshot(self.database,capture)['imported'])
        status=website_status(self.database)
        self.assertEqual(status['pages'],1); self.assertEqual(status['crawl_runs'],1)
        self.assertEqual(status['approval_status'],'draft'); self.assertEqual(status['approved_pages'],0)

    def test_changed_text_creates_new_version_without_destroying_old(self):
        import_snapshot(self.database,self.capture())
        import_snapshot(self.database,self.capture('run2','Утас өөрчлөгдсөн 2027'))
        with closing(sqlite3.connect(self.database)) as db:
            versions=db.execute('SELECT version,text FROM pages ORDER BY version').fetchall()
        self.assertEqual([v[0] for v in versions],[1,2]); self.assertIn('75777799',versions[0][1])

    def test_unchanged_text_across_captures_reuses_semantic_version(self):
        import_snapshot(self.database,self.capture())
        import_snapshot(self.database,self.capture('run2'))
        self.assertEqual(website_status(self.database)['versions'],1)
        self.assertEqual(website_status(self.database)['crawl_runs'],2)

    def test_tampered_text_or_escaping_path_is_rejected_before_database_creation(self):
        capture=self.capture()
        (capture/'page.txt').write_text('invented',encoding='utf-8')
        with self.assertRaises(ValueError): import_snapshot(self.database,capture)
        self.assertFalse(self.database.exists())
        capture=self.capture('run2',extra=lambda m:m['pages'][0].update(text_file='../outside.txt'))
        with self.assertRaises(ValueError): import_snapshot(self.database,capture)
        self.assertFalse(self.database.exists())

    def test_search_masks_drafts_and_never_generates_answers(self):
        import_snapshot(self.database,self.capture())
        before=hashlib.sha256(self.database.read_bytes()).hexdigest()
        blocked=search_website('Сургуулийн утас',self.database)
        draft=search_website('Сургуулийн утас',self.database,allow_draft=True)
        self.assertIsNone(blocked['matches'][0]['excerpt'])
        self.assertIn('75777799',draft['matches'][0]['excerpt'])
        self.assertIsNone(draft['answer']); self.assertFalse(draft['score_is_probability'])
        self.assertEqual(hashlib.sha256(self.database.read_bytes()).hexdigest(),before)

    def test_missing_or_unrelated_database_is_not_created_or_modified(self):
        with self.assertRaises(FileNotFoundError): website_status(self.database)
        self.assertFalse(self.database.exists())
        with closing(sqlite3.connect(self.database)) as db:
            db.execute('CREATE TABLE unrelated(x)'); db.commit()
        before=self.database.read_bytes()
        with self.assertRaises(ValueError): import_snapshot(self.database,self.capture())
        self.assertEqual(before,self.database.read_bytes())


if __name__=='__main__': unittest.main()
