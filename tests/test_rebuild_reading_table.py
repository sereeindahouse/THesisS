import unittest

from tools import rebuild_reading_table as rebuild


PLAN = '\n'.join([
    '# Plan',
    '',
    rebuild.MARK + ' (old).** old intro',
    '',
    '| 7 хоног | Өгүүлэл | Яаж унших | Төлөв |',
    '|---|---|---|---|',
    '| W05 | MON01: A (2022) — *One* | Бүтнээр · ~1 цаг · хөтөч бэлдээгүй | ✅ 11/23 хэрэглэгч уншсан гэж хэлсэн |',
    '| W05 | MON02: B (2022) — *Two* | Бүтнээр · ~1 цаг · хөтөч бэлдээгүй | Одоо |',
    '',
    '## After',
    '',
])


def item(code, status, guide=None):
    return dict(code=code, title=code.lower(), authors='X', year=2022, sections_mn='Бүтнээр', hours=1.0,
                guide=guide, status=status)


class RebuildReadingTableTests(unittest.TestCase):
    def test_a_paper_read_since_keeps_only_its_tick_row(self):
        schedule = dict(weeks=[dict(week='W05', items=[item('MON01', 'read'), item('MON02', 'todo', 'papers/g.md')])])
        table = [line for line in rebuild.build(PLAN, schedule).splitlines() if line.startswith('| W05')]
        self.assertEqual(sum('MON01' in line for line in table), 1)
        self.assertIn('✅', next(line for line in table if 'MON01' in line))
        self.assertIn('[хөтөч](../papers/g.md)', next(line for line in table if 'MON02' in line))

    def test_the_text_after_the_table_is_kept(self):
        schedule = dict(weeks=[dict(week='W05', items=[item('MON02', 'todo')])])
        self.assertTrue(rebuild.build(PLAN, schedule).rstrip().endswith('## After'))


if __name__ == '__main__':
    unittest.main()
