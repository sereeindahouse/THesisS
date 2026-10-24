from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from CORE.website_corpus import PageParser, import_snapshot
from website_retrieval import WebsiteRetriever, _capture_structure, _source_structure


class RetrievalStructureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.snapshot = self.root / 'snapshot'
        self.snapshot.mkdir()
        self.body = ('<main><section><h2>Товч тоо</h2><div>2028</div><div>17 үйл явдал</div></section>'
                     '<section><h2>Түүх</h2><div><h3>2017</h3><p>Эхний хичээл 73 оюутантай эхэлсэн.</p></div>'
                     '<div><h3>2020</h3><p>Шинэ хөтөлбөр нээгдсэн. Зөвхөн шалгуур хангасан хүн оролцоно.</p></div>'
                     '</section></main>').encode()
        parser = PageParser()
        parser.feed(self.body.decode())
        self.text = parser.result()['text']
        self.html = self.snapshot / 'page.html'
        self.html.write_bytes(self.body)
        self.capture = dict(html_path=str(self.html), html_sha256=hashlib.sha256(self.body).hexdigest(),
                            http_metadata=json.dumps(dict(charset='utf-8')))
        self.page = dict(text=self.text, text_sha256=hashlib.sha256(self.text.encode()).hexdigest())
        self.run = dict(snapshot_dir=str(self.snapshot))

    def tearDown(self):
        self.temporary.cleanup()

    def test_verified_capture_supplies_only_exact_line_boundaries(self):
        spans = _capture_structure(self.run, self.capture, self.page)
        self.assertGreater(len(spans), 1)
        metadata = _source_structure(spans, 0, len(self.text), self.text)
        self.assertTrue(metadata['structure_boundaries'])
        for cut in metadata['structure_boundaries']:
            self.assertTrue(self.text[cut - 1] == '\n' or self.text[cut] == '\n')
        self.assertEqual(metadata['structure_text_sha256'], self.page['text_sha256'])

    def test_html_and_canonical_text_tampering_never_supplies_structure(self):
        for capture, page in [
            (dict(self.capture, html_sha256='0' * 64), self.page),
            (self.capture, dict(self.page, text=self.text + ' нэмэлт')),
            (self.capture, dict(self.page, text_sha256='0' * 64)),
            (dict(self.capture, http_metadata='invalid-json'), self.page),
            (dict(self.capture, http_metadata=json.dumps(dict(charset='unknown-charset'))), self.page),
        ]:
            with self.subTest(capture=capture, page=page):
                self.assertEqual(_capture_structure(self.run, capture, page), [])

    def test_capture_cannot_escape_its_snapshot(self):
        outside = self.root / 'outside.html'
        outside.write_bytes(self.body)
        capture = dict(self.capture, html_path=str(outside))
        self.assertEqual(_capture_structure(self.run, capture, self.page), [])

    def test_metadata_changes_neither_source_identity_nor_ranked_text(self):
        (self.snapshot / 'page.txt').write_text(self.text, encoding='utf-8', newline='')
        manifest = dict(run_id='structure-test', retrieved_at='2026-10-10T00:00:00+00:00', inventory=[],
            pages=[dict(url='https://nmct.edu.mn/about/test', status='ok', html_file='page.html',
                text_file='page.txt', html_sha256=self.capture['html_sha256'],
                text_sha256=self.page['text_sha256'], retrieved_at='2026-10-10T00:00:00+00:00',
                http=dict(charset='utf-8', last_modified=None))])
        (self.snapshot / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        database = self.root / 'CORE/database/website.db'
        import_snapshot(database, self.snapshot)
        before = hashlib.sha256(database.read_bytes()).hexdigest()
        first = WebsiteRetriever(self.root, use_dense=False)
        self.assertTrue(first.status()['available'])
        structured = first._rows[0]
        self.assertTrue(structured.get('structure_boundaries'))
        self.html.write_bytes(b'<main>tampered capture</main>')
        fallback = WebsiteRetriever(self.root, use_dense=False)
        fallback.status()
        unstructured = fallback._rows[0]
        self.assertNotIn('structure_boundaries', unstructured)
        self.assertEqual(first.status()['corpus_id'], fallback.status()['corpus_id'])
        for key in ('source_id', 'text', 'start_offset', 'end_offset'):
            self.assertEqual(structured[key], unstructured[key])
        self.assertEqual(before, hashlib.sha256(database.read_bytes()).hexdigest())


if __name__ == '__main__':
    unittest.main()
