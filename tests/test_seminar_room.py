"""Seminar room (/seminar) and report room (/reports) read local files live and never write."""
from pathlib import Path
import tempfile
import unittest
from urllib.parse import quote

import report_room
import seminar_room
import test_demo_server as server_fixture

SPEECH = '''# Семинарын яриа — слайд бүрээр (2026.11.24)

PPT: `28_Семинар_ШМТК_v105_16x10.pptx`.

**1. Нүүр (10 сек)**
Сайн байцгаана уу.

**2–3. Зорилго, зорилт (15 сек)**
Зорилго өөрчлөгдөөгүй <script>alert(1)</script>.

---

## Багшаас асуух зүйл

1. **Латин бичиг.** «Судалгаанд оруулах уу?»

## Багш асуувал товч хариулах нь

- **«Яагаад 40?»** — Төлөвлөгөөнд анхнаасаа ингэж төлөвлөсөн.
- **«Юу ойлгосон бэ?»** — Доорх нь санал.
  - *Дохионы хэл.* Зорилгоо эхэнд хэлдэг.

## Мэдэж байх хязгаар

- Дэлгэрэнгүй: `papers/52-latin-script-questions-20261123.mn.md`.
'''

NOTEBOOK = '''# W05 — семинарын өдрийн хуудас (2026.11.24)

## 1. Дэвтэрт үзгээр бичих тэмдэглэл

**Огноо:** 2026.11.24
**Гарын үсэг:** ________
'''

REPORT = '''# Латин бичгийн асуулт

**Хэрэглэгч:** асуусан.

## Эх сурвалж

- Byambadorj нар (2020): https://anlp.jp/proceedings/annual_meeting/2020/pdf_dir/E5-3.pdf
- [W3C](https://www.w3.org/WAI/WCAG22/Understanding/visual-presentation.html), өмнөх тэмдэглэл `papers/41-autofix-*`, хөтөч [RAG01](20-RAG01-delgerengui-hotoch-20261104.mn.md)

```
python tools/x.py
```
'''


def make_root(folder):
    root = Path(folder)
    seminar = root / 'CORE/seminar-2026-11-24'
    seminar.mkdir(parents=True)
    (root / 'CORE/seminar-2026-11-17').mkdir()
    (seminar / '27_Яриа_2026-11-24.mn.md').write_text(SPEECH, encoding='utf-8')
    (seminar / '27_Дэвтэр_2026-11-24.mn.md').write_text(NOTEBOOK, encoding='utf-8')
    (seminar / '28_Семинар_ШМТК_v105_16x10.pptx').write_bytes(b'pptx')
    render = root / 'runtime/slide-render/28_Семинар_ШМТК_v105_16x10'
    render.mkdir(parents=True)
    for number in (1, 2):
        (render / f'slide-{number:02d}.png').write_bytes(b'\x89PNG' + bytes([number]))
    papers = root / 'papers'
    papers.mkdir()
    (papers / '52-latin-script-questions-20261123.mn.md').write_text(REPORT, encoding='utf-8')
    (papers / '41-autofix-round4-20261117.mn.md').write_text('# Тойрог 4\n\nТекст.\n', encoding='utf-8')
    (papers / '20-RAG01-delgerengui-hotoch-20261104.mn.md').write_text('# Хөтөч\n', encoding='utf-8')
    (root / 'CLAUDE.md').write_text('secret rules', encoding='utf-8')
    return root


class SeminarRoomTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = make_root(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_speech_parts_carry_slides_budget_and_words(self):
        _, intro, parts, sections = seminar_room.speech_parts(SPEECH)
        self.assertEqual([(part['first'], part['last'], part['seconds']) for part in parts], [(1, 1, 10), (2, 3, 15)])
        self.assertEqual(parts[0]['words'], 3)
        self.assertIn('Багш асуувал товч хариулах нь', [heading for heading, _ in sections])
        cards = seminar_room.question_cards(dict(sections)['Багш асуувал товч хариулах нь'])
        self.assertEqual([card['question'] for card in cards], ['«Яагаад 40?»', '«Юу ойлгосон бэ?»'])
        self.assertIn('- *Дохионы хэл.* Зорилгоо эхэнд хэлдэг.', cards[1]['answer'])

    def test_page_puts_each_slide_beside_its_part_and_escapes_text(self):
        page = seminar_room.seminar_page(self.root)
        self.assertEqual(page.count('class="part"'), 2)
        self.assertIn('/seminar-slide/28_Семинар_ШМТК_v105_16x10/01.png', page)
        self.assertIn('/seminar-slide/28_Семинар_ШМТК_v105_16x10/02.png', page)
        self.assertNotIn('/03.png', page)                       # slide 3 was not rendered: no broken picture
        self.assertIn('data-budget="15"', page)
        self.assertIn('төсөв 0:25 / 5:00', page)
        self.assertEqual(page.count('class="card"'), 2)
        self.assertIn('Хариуг харах', page)
        self.assertIn('Огноо:', page)                           # notebook page
        self.assertIn('href="/reports/52-latin-script-questions-20261123.mn"', page)
        self.assertNotIn('<script>alert(1)</script>', page)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', page)
        self.assertIn('href="/seminar/seminar-2026-11-17"', page)

    def test_other_folders_and_bad_names(self):
        self.assertIn('Ярианы хэсэг олдсонгүй', seminar_room.seminar_page(self.root, 'seminar-2026-11-17'))
        for bad in ('../CLAUDE.md', 'seminar-2026-11-30', 'x'):
            with self.assertRaises(KeyError):
                seminar_room.seminar_page(self.root, bad)

    def test_slide_pictures_only_for_known_decks(self):
        self.assertEqual(seminar_room.slide_image(self.root, '28_Семинар_ШМТК_v105_16x10', '01'), b'\x89PNG\x01')
        for stem, number in (('28_Семинар_ШМТК_v105_16x10', '03'), ('28_Семинар_ШМТК_v105_16x10', '1'),
                             ('../../CLAUDE', '01'), ('unknown', '01'), ('28_Семинар_ШМТК_v105_16x10', '../01')):
            with self.assertRaises(KeyError):
                seminar_room.slide_image(self.root, stem, number)


class ReportRoomTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = make_root(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_index_lists_reports_not_guides(self):
        names = [path.name for path in report_room.report_files(self.root)]
        self.assertEqual(names, ['52-latin-script-questions-20261123.mn.md', '41-autofix-round4-20261117.mn.md'])
        index = report_room.reports_index(self.root)
        self.assertIn('href="/reports/52-latin-script-questions-20261123.mn"', index)
        self.assertNotIn('hotoch', index)

    def test_page_lists_its_sources_and_links_inside_127(self):
        page = report_room.report_page(self.root, '52-latin-script-questions-20261123.mn')
        self.assertIn('<h3>Вэб (2)</h3>', page)
        self.assertIn('href="https://anlp.jp/proceedings/annual_meeting/2020/pdf_dir/E5-3.pdf"', page)
        self.assertIn('href="/reports/41-autofix-round4-20261117.mn"', page)    # unique `papers/41-autofix-*`
        self.assertIn('href="/reader/RAG01"', page)
        self.assertIn('<pre><code>python tools/x.py</code></pre>', page)

    def test_bad_names_are_refused(self):
        for bad in ('', '../CLAUDE', '52-x/../../CLAUDE', '20-RAG01-delgerengui-hotoch-20261104.mn', 'CLAUDE'):
            with self.assertRaises(KeyError):
                report_room.report_page(self.root, bad)

    def test_research_reports_and_review_folders_open_as_pages(self):
        # 11/26, the user: reports in reports/ and a papers/NN-*/ folder read as raw text in VS Code.
        (self.root / 'reports').mkdir(exist_ok=True)
        (self.root / 'reports' / 'Төстэй систем.md').write_text('# Төстэй систем\n\n| A | B |\n|---|---|\n| 1 | 2 |\n',
                                                               encoding='utf-8')
        folder = self.root / 'papers' / '65-review-20261126'
        folder.mkdir()
        (folder / '0-шийдвэр.mn.md').write_text('# Шийдвэр\n\nТомоохон засвар.\n', encoding='utf-8')
        (folder / 'synthesis.md').write_text('# Letter\n\nMajor revision.\n', encoding='utf-8')
        index = report_room.reports_index(self.root)
        self.assertIn('Судалгааны тайлан', index)
        self.assertIn('href="/reports/r/%D0%A2', index)
        self.assertIn('href="/reports/65-review-20261126"', index)
        self.assertIn('<table', report_room.report_page(self.root, 'r/Төстэй систем'))
        summary = report_room.report_page(self.root, '65-review-20261126')
        self.assertIn('Томоохон засвар', summary)
        self.assertIn('href="/reports/65-review-20261126/synthesis"', summary)
        self.assertIn('Major revision', report_room.report_page(self.root, '65-review-20261126/synthesis'))
        for bad in ('r/../CLAUDE', 'r/', '65-review-20261126/../../CLAUDE', '65-review-20261126/../41-x',
                    '66-missing', 'r/missing'):
            with self.assertRaises(KeyError):
                report_room.report_page(self.root, bad)

    def test_real_reports_load(self):
        root = Path(__file__).resolve().parents[1]
        files = report_room.report_files(root)
        self.assertGreaterEqual(len(files), 10)
        self.assertIn('Эх сурвалж', report_room.report_page(root, files[0].name[:-3]))


class SeminarRoomHTTPTests(unittest.TestCase):
    def setUp(self):
        self.helper = server_fixture.DemoServerTests()
        self.helper.setUp()
        make_root_into = self.helper.root
        for relative in ('CORE', 'papers', 'runtime'):
            (make_root_into / relative).mkdir(exist_ok=True)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        source = make_root(temp.name)
        for path in source.rglob('*'):
            target = make_root_into / path.relative_to(source)
            if path.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            elif not target.exists():
                target.write_bytes(path.read_bytes())

    def tearDown(self):
        self.helper.tearDown()

    def test_routes(self):
        status, body = self.helper.request('GET', '/seminar')
        self.assertEqual(status, 200)
        self.assertIn('Яриагаа давтах', body.decode('utf-8'))
        self.assertEqual(self.helper.request('GET', '/seminar/seminar-2026-11-17')[0], 200)
        status, body = self.helper.request('GET', quote('/seminar-slide/28_Семинар_ШМТК_v105_16x10/01.png'))
        self.assertEqual((status, body), (200, b'\x89PNG\x01'))
        self.assertEqual(self.helper.request('GET', '/reports')[0], 200)
        self.assertEqual(self.helper.request('GET', '/reports/52-latin-script-questions-20261123.mn')[0], 200)
        for path in ('/seminar/../CLAUDE.md', '/seminar/seminar-2099-01-01', '/seminar-slide/28_Семинар_ШМТК_v105_16x10/01',
                     '/seminar-slide/../../CLAUDE.md', '/reports/../CLAUDE', '/reports/CLAUDE'):
            self.assertEqual(self.helper.request('GET', quote(path))[0], 404, path)

    def test_routes_refuse_cross_site_and_wrong_host(self):
        self.assertEqual(self.helper.request('GET', '/seminar', headers={'Sec-Fetch-Site': 'cross-site'})[0], 403)
        self.assertEqual(self.helper.request('GET', '/reports', headers={'Host': 'evil.example'})[0], 403)


if __name__ == '__main__':
    unittest.main()
