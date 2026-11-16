import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import thesis_to_markdown as flat  # noqa: E402


class PrintedTextTests(unittest.TestCase):
    def test_comments_and_disabled_blocks_are_dropped(self):
        tex = 'А мөр % тайлбар\n% бүтэн тайлбар\n\\iffalse\nунтраасан\n\\fi\n100\\% үлдэнэ'
        self.assertEqual(flat.printed(tex), 'А мөр\n100\\% үлдэнэ')

    def test_full_only_file_is_printed_only_in_the_full_draft(self):
        tex = 'Хамтын мөр\n\\fullinput{Chapters/full/ch1_structure}\nТөгсгөл'
        self.addCleanup(setattr, flat, 'FULL_DRAFT', flat.FULL_DRAFT)
        flat.FULL_DRAFT = False
        self.assertEqual(flat.printed(tex), 'Хамтын мөр\n\nТөгсгөл')
        if (ROOT / 'thesis/Chapters/full/ch1_structure.tex').is_file():
            flat.FULL_DRAFT = True
            self.assertIn('\\section{Судалгааны ажлын бүтэц}', flat.printed(tex))

    def test_inline_markup(self):
        text = flat.inline(r'\textbf{Тод} \cite{lewis2020rag} \ac{WER} 5\%')
        self.assertEqual(text, '**Тод** [lewis2020rag] WER 5%')


@unittest.skipUnless((ROOT / 'thesis/Chapters/Chapter1_Introduction.tex').is_file(), 'thesis sources missing')
class RealThesisTests(unittest.TestCase):
    def test_real_thesis_converts_without_unresolved_references(self):
        markdown = flat.convert()
        self.assertNotIn('??', markdown)
        self.assertNotIn('\\iffalse', markdown)
        self.assertIn('## 1. Удиртгал', markdown)
        self.assertRegex(markdown, r'\*\*Хүснэгт 1\.1\. ')
        self.assertIn('Зурагт буй бичвэр:', markdown)


if __name__ == '__main__':
    unittest.main()
