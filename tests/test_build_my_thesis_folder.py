import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import build_my_thesis_folder as folder  # noqa: E402


def _write(path: Path, text: str, mtime: float | None = None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    if mtime is not None:
        os.utime(path, (mtime, mtime))


class BuildMyThesisFolderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        now = time.time()
        _write(self.root / 'thesis/main.pdf', 'pdf')
        _write(self.root / 'thesis/main.tex', 'tex')
        _write(self.root / 'CORE/seminar-2026-11-03/10_Семинар_v7.pptx', 'old', now - 100)
        _write(self.root / 'CORE/seminar-2026-11-03/11_Семинар_v8.pptx', 'new', now - 50)
        _write(self.root / 'data/school-request/list.pdf', 'school')
        _write(self.root / 'data/school-request/tables.xlsx', 'tables')
        _write(self.root / 'papers/17-RAG01-hotoch.md', 'guide')
        _write(self.root / 'docs/diagrams/UML.pdf', 'uml')
        self.out = self.root / folder.FOLDER

    def tearDown(self):
        self.tmp.cleanup()

    def test_copies_newest_deliverables_and_writes_index(self):
        result = folder.build(self.root)
        self.assertEqual(result['edited_copies'], [])
        self.assertTrue((self.out / '01_Диплом/Диплом.pdf').is_file())
        self.assertTrue((self.out / '02_Семинар/11_Семинар_v8.pptx').is_file())
        self.assertFalse((self.out / '02_Семинар/10_Семинар_v7.pptx').exists())
        self.assertTrue((self.out / '03_Сургуульд_өгөх/list.pdf').is_file())
        self.assertFalse((self.out / '03_Сургуульд_өгөх/tables.xlsx').exists())
        self.assertTrue((self.out / '01_Диплом/UML.pdf').is_file())
        index = (self.out / folder.INDEX).read_text(encoding='utf-8')
        self.assertIn('CORE/THESIS-START.mn.md', index)
        self.assertIn('11_Семинар_v8.pptx', index)

    def test_never_overwrites_a_copy_the_user_edited(self):
        folder.build(self.root)
        copy = self.out / '02_Семинар/11_Семинар_v8.pptx'
        _write(copy, 'user edit in PowerPoint', time.time() + 5)
        _write(self.root / 'CORE/seminar-2026-11-03/11_Семинар_v8.pptx', 'agent change', time.time() + 10)
        result = folder.build(self.root)
        self.assertEqual(copy.read_text(encoding='utf-8'), 'user edit in PowerPoint')
        self.assertIn('02_Семинар/11_Семинар_v8.pptx', result['edited_copies'])
        self.assertIn('⚠', (self.out / folder.INDEX).read_text(encoding='utf-8'))

    def test_replaced_copy_removed_only_when_untouched(self):
        _write(self.root / 'CORE/seminar-2026-11-03/01_Дэвтэр_v1.md', 'v1', time.time() - 10)
        folder.build(self.root)
        _write(self.root / 'CORE/seminar-2026-11-03/02_Дэвтэр_v2.md', 'v2', time.time() + 10)
        folder.build(self.root)
        self.assertFalse((self.out / '05_Дэвтэр/01_Дэвтэр_v1.md').exists())
        self.assertTrue((self.out / '05_Дэвтэр/02_Дэвтэр_v2.md').is_file())
        # sources are never touched
        self.assertTrue((self.root / 'CORE/seminar-2026-11-03/01_Дэвтэр_v1.md').is_file())

    def test_earlier_seminar_decks_are_kept(self):
        folder.build(self.root)
        _write(self.root / 'CORE/seminar-2026-11-17/12_Семинар_v9.pptx', 'v9', time.time() + 10)
        folder.build(self.root)
        folder.build(self.root)
        self.assertTrue((self.out / '02_Семинар/11_Семинар_v8.pptx').is_file())
        self.assertTrue((self.out / '02_Семинар/12_Семинар_v9.pptx').is_file())

    def test_latex_link_points_at_thesis_source(self):
        result = folder.build(self.root)
        link = self.out.joinpath(*folder.LATEX_LINK)
        if not result['latex_link']:
            self.skipTest('directory links unavailable on this system')
        self.assertEqual((link / 'main.tex').read_text(encoding='utf-8'), 'tex')

    def test_quiet_mode_never_raises(self):
        self.assertEqual(folder.main(['--root', str(self.root / 'missing' / 'x'), '--quiet']), 0)


if __name__ == '__main__':
    unittest.main()
