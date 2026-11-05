from datetime import date
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import claude_context  # noqa: E402

PLAN = """# Plan

**Унших дараалал ба төлөв (2026.11.02).**

| 7 хоног | Өгүүлэл | Яаж унших | Төлөв |
|---|---|---|---|
| — | Whisper (STT01) | Гол хэсэг | ✅ 11/02 хэрэглэгч уншсан |
| W02 | RAG (RAG01) — [arXiv](https://arxiv.org/abs/2005.11401) | Гол | Одоо |

### W52 · 2026.12.28–01.03 — Year crossing week

- **Хийх:** crossing

### W02 · 2026.11.02–11.08 — Seminar week

- **Хийх:** seminar
- **Төлөв:** signed

### W03 · 2026.11.09–11.15 — School data
"""

NOTE = """# Note

<!-- project-state:start -->
**Одоогийн бүртгэл — 2026-11-05**
- **Одоо:** II
<!-- project-state:end -->

**11.05 — III · Latest entry.**
- detail

## 2026.11.01 — I · Older heading
"""


class BriefTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'CORE/archive').mkdir(parents=True)
        (self.root / 'CORE/WEEKLY-PLAN-2026-2027.mn.md').write_text(PLAN, encoding='utf-8')
        (self.root / 'CORE/PROJECT-NOTE.mn.md').write_text(NOTE, encoding='utf-8')
        (self.root / 'CORE/archive/PROJECT-NOTE-2026-11.mn.md').write_text(
            '**11.03 (2) — III · Archived entry.**\n', encoding='utf-8')

    def tearDown(self):
        self.tmp.cleanup()

    def test_brief_shows_current_block_week_reading_and_every_entry(self):
        text = claude_context.brief(self.root, today=date(2026, 11, 5))
        self.assertIn('**Одоо:** II', text)
        self.assertIn('### W02 · 2026.11.02–11.08 — Seminar week', text)
        self.assertIn('**Төлөв:** signed', text)
        self.assertIn('Дараагийнх: ### W03', text)
        self.assertNotIn('crossing', text)
        self.assertIn('W02 · RAG (RAG01) — arXiv · Одоо', text)
        self.assertIn('— · Whisper (STT01) · ✅ 11/02 хэрэглэгч уншсан', text)
        self.assertIn('PROJECT-NOTE.mn.md: 11.05 — III · Latest entry.', text)
        self.assertIn('PROJECT-NOTE.mn.md: 2026.11.01 — I · Older heading', text)
        self.assertIn('PROJECT-NOTE-2026-11.mn.md: 11.03 (2) — III · Archived entry.', text)

    def test_week_crossing_new_year(self):
        week, _ = claude_context.week_section(PLAN, date(2027, 1, 2))
        self.assertIn('W52', week)

    def test_missing_files_do_not_crash(self):
        text = claude_context.brief(Path(self.tmp.name) / 'nothing', today=date(2026, 11, 5))
        self.assertIn('(олдсонгүй)', text)


if __name__ == '__main__':
    unittest.main()
