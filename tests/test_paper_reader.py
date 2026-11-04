"""Paper reader built from our Mongolian guide: structure, escaping and link safety."""
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from build_paper_reader import GUIDE, build  # noqa: E402

FIXTURE = '''# Туршилтын хөтөч

**Өгүүлэл:** Жишээ <b>tag</b>

## Энэ файлыг яаж ашиглах вэ

- Эхлээд уншина.

## 0. Гол нэр томьёо

| Англи | Монгол | Энгийн тайлбар |
|---|---|---|
| retriever | **хайгч** | Хамааралтай бичвэрийг олдог хэсэг. |

## ⭐ 1. Удиртгал

**хайгч** нь <script>alert(1)</script> [муу](javascript:alert(1)) [хөтөч](17-guide.md)

- Нэг
  - Дотор
- Хоёр

$$p_{\\text{RAG}}(y|x) \\approx \\sum_{z} p_\\eta(z|x)$$

## 3. Туршилт

Сонголтоор.

## Манай системтэй холбох

| Өгүүлэл | Манай систем | Бичих |
|---|---|---|
| BM25 | BM25 + E5 | Хоёуланг нийлүүлсэн. |

---

**Хязгаар:** англи өгөгдөл.

## Өөрийгөө шалгах асуулт

1. Хайгч юу хийдэг вэ?
2. BM25 яагаад?

## Уншсаны тэмдэглэл (өөрөө бөглөнө)

- Уншсан огноо:
'''


class PaperReaderTests(unittest.TestCase):
    def page(self, markdown=FIXTURE):
        return build(markdown, pdf_url='https://arxiv.org/pdf/0000.00000', abs_url='https://arxiv.org/abs/0000.00000',
                     link_base='../')

    def test_sections_glossary_links_and_questions(self):
        page = self.page()
        self.assertEqual(page.count('class="chapter starred"'), 1)
        self.assertEqual(page.count('class="chapter optional"'), 2)  # glossary + experiments
        self.assertIn('class="term"', page)
        self.assertIn('data-tip="retriever — Хамааралтай бичвэрийг олдог хэсэг."', page)
        self.assertEqual(page.count('class="link-row"'), 1)
        self.assertEqual(page.count('data-store="q'), 2)
        self.assertEqual(page.count('data-store="note'), 1)
        self.assertIn('Хязгаар', page)
        self.assertNotIn('<p class="links-limit">---', page)

    def test_markdown_is_escaped_and_unsafe_links_are_dropped(self):
        page = self.page()
        self.assertNotIn('<script>alert', page)
        self.assertNotIn('<b>tag</b>', page)
        self.assertIn('&lt;script&gt;', page)
        self.assertNotIn('javascript:', page)
        self.assertIn('href="../17-guide.md"', page)

    def test_nested_lists_and_math(self):
        page = self.page()
        self.assertIn('<ul><li>Нэг<ul><li>Дотор</li></ul></li><li>Хоёр</li></ul>', page)
        math = re.search(r'<div class="math">(.*?)</div>', page).group(1)
        self.assertIn('∑', math)
        self.assertIn('≈', math)
        self.assertIn('<sub>RAG</sub>', math)
        self.assertNotIn('\\', math)

    def test_real_rag01_guide_builds_without_markdown_leftovers(self):
        page = self.page(GUIDE.read_text(encoding='utf-8'))
        self.assertEqual(page.count('class="chapter starred"'), 5)
        self.assertEqual(page.count('data-store="q'), 8)
        self.assertNotIn('**', page)
        self.assertNotIn('$$', page)
        # Only local storage for the reader's own notes; no network or remote assets.
        self.assertNotRegex(page, r'<(script|link|img)[^>]+(src|href)="https?://')
        self.assertNotIn('fetch(', page)


if __name__ == '__main__':
    unittest.main()
