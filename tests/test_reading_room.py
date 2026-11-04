"""Reading room (/reader) reads the plan table and guides live; status never comes from the page."""
from pathlib import Path
import tempfile
import unittest

import reading_room
import test_demo_server as server_fixture

PLAN = '''# План

**Унших дараалал ба төлөв (2026.11.02).** Тайлбар.

| 7 хоног | Өгүүлэл | Яаж унших | Төлөв |
|---|---|---|---|
| — | Whisper (STT01) | Гол хэсэг | ✅ 11/02 хэрэглэгч уншсан |
| W02 | RAG (RAG01) — [arXiv](https://arxiv.org/abs/2005.11401) · [хөтөч](../papers/x.md) | Гол хэсэг | Одоо |
| W03 | SQuAD 2.0 (RAG08) | §1–3 | Үлдсэн |
| W04 | BM25 (RAG02) | Гол хэсэг | Үлдсэн |

Өөр текст.
'''

GUIDE = '''# RAG01 хөтөч

**Англи эх:** https://arxiv.org/abs/2005.11401 · PDF: https://arxiv.org/pdf/2005.11401

## ⭐ 1. Удиртгал

Товч [богино хөтөч](17-RAG01-unshlagyn-hotoch.md) байна.
'''


def make_root(folder):
    root = Path(folder)
    (root / 'CORE').mkdir()
    (root / 'papers').mkdir()
    (root / 'CORE/WEEKLY-PLAN-2026-2027.mn.md').write_text(PLAN, encoding='utf-8')
    (root / 'papers/17-RAG01-unshlagyn-hotoch-20261102.mn.md').write_text(GUIDE.replace('RAG01 хөтөч', 'Богино'), encoding='utf-8')
    (root / 'papers/20-RAG01-delgerengui-hotoch-20261104.mn.md').write_text(GUIDE, encoding='utf-8')
    return root


class ReadingRoomTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = make_root(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_status_comes_from_the_plan_table(self):
        rows = reading_room.reading_list(self.root)
        self.assertEqual([row['status'] for row in rows], ['read', 'current', 'next', 'later'])
        self.assertEqual([row['guide'] for row in rows], [None, 'RAG01', None, None])

    def test_detailed_guide_wins_and_relative_links_become_text(self):
        self.assertIn('delgerengui', reading_room.guide_files(self.root)['RAG01'].name)
        page = reading_room.guide_page(self.root, 'RAG01')
        self.assertIn('RAG01 хөтөч', page)
        self.assertIn('href="/reader"', page)
        self.assertIn('href="https://arxiv.org/pdf/2005.11401"', page)
        self.assertNotIn('17-RAG01-unshlagyn-hotoch.md', page)
        with self.assertRaises(KeyError):
            reading_room.guide_page(self.root, 'RAG08')

    def test_index_is_live_and_never_marks_papers_read(self):
        page = reading_room.index_page(self.root)
        self.assertIn('4 өгүүлэл · 1 уншсан · 1 нь Монгол хөтөчтэй', page)
        self.assertIn('href="/reader/RAG01"', page)
        self.assertIn('Хөтөч бэлдээгүй', page)
        self.assertNotIn('../papers/x.md', page)
        (self.root / 'papers/22-RAG08-delgerengui-hotoch-20261104.mn.md').write_text(GUIDE, encoding='utf-8')
        self.assertIn('href="/reader/RAG08"', reading_room.index_page(self.root))

    def test_real_plan_and_guides_load(self):
        root = Path(__file__).resolve().parents[1]
        rows = reading_room.reading_list(root)
        self.assertGreaterEqual(len(rows), 10)
        self.assertIn('RAG01', [row['guide'] for row in rows])


class ReadingRoomHTTPTests(unittest.TestCase):
    def setUp(self):
        self.helper = server_fixture.DemoServerTests()
        self.helper.setUp()
        (self.helper.root / 'CORE').mkdir(exist_ok=True)
        (self.helper.root / 'papers').mkdir(exist_ok=True)
        (self.helper.root / 'CORE/WEEKLY-PLAN-2026-2027.mn.md').write_text(PLAN, encoding='utf-8')
        (self.helper.root / 'papers/20-RAG01-delgerengui-hotoch-20261104.mn.md').write_text(GUIDE, encoding='utf-8')

    def tearDown(self):
        self.helper.tearDown()

    def test_reader_routes(self):
        status, body = self.helper.request('GET', '/reader')
        self.assertEqual(status, 200)
        self.assertIn('Өгүүлэл унших', body.decode('utf-8'))
        self.assertEqual(self.helper.request('GET', '/reader/RAG01')[0], 200)
        self.assertEqual(self.helper.request('GET', '/reader/RAG08')[0], 404)
        for path in ('/reader/../CORE/WEEKLY-PLAN-2026-2027.mn.md', '/reader/rag01', '/reader/RAG01/x'):
            self.assertEqual(self.helper.request('GET', path)[0], 404, path)

    def test_reader_rejects_cross_site_and_wrong_host(self):
        self.assertEqual(self.helper.request('GET', '/reader', headers={'Sec-Fetch-Site': 'cross-site'})[0], 403)
        self.assertEqual(self.helper.request('GET', '/reader', headers={'Host': 'evil.example'})[0], 403)


if __name__ == '__main__':
    unittest.main()
