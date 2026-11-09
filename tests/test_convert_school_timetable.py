"""FAKE timetable only: merged cells become lessons, joint lessons and clashes are handled."""
from pathlib import Path
import sys
import tempfile
import unittest

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import convert_school_timetable as tt  # noqa: E402


class ConvertSchoolTimetableTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        book = openpyxl.Workbook()
        ws = book.active
        ws.cell(6, 2, 'Өдөр'); ws.cell(6, 3, 'Time')
        ws.cell(6, 5, 'КУ-1-р анги'); ws.cell(6, 7, 'ЦЭИ-1-р анги')
        ws.cell(7, 5, 'Ф.Нэг №510'); ws.cell(7, 7, 'Ф.Хоёр №513')
        ws.cell(8, 2, 'ДАВАА')
        for i, time in enumerate(['08:00-08:45', '08:45-09:30', '09:35-10:20']):
            ws.cell(8 + i, 3, i + 1); ws.cell(8 + i, 4, time)
        ws.cell(8, 5, 'Алгебр Ф.Нэг'); ws.merge_cells('E8:F9')                     # 2 periods, home room
        ws.cell(8, 7, 'Физик Ф.Хоёр №613'); ws.merge_cells('G8:H9')
        ws.cell(10, 5, 'Англи хэл Ф.Гурав №408, Ф.Дөрөв №303'); ws.merge_cells('E10:H10')  # joint
        self.path = Path(self.tmp.name) / 'fake.xlsx'
        book.save(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_reads_periods_rooms_and_joint_lessons(self):
        groups, rows, cells = tt.read_grid(self.path)
        self.assertEqual(set(groups), {'КУ-1', 'ЦИ-1'})            # ЦЭИ -> ЦИ like the class list
        lessons = tt.lessons_from(groups, rows, cells)
        algebra = next(l for l in lessons if l['subject'] == 'Алгебр')
        self.assertEqual((algebra['time'], algebra['room']), ('08:00-09:30', '510'))
        physics = next(l for l in lessons if l['subject'] == 'Физик')
        self.assertEqual(physics['room'], '613')
        english = [l for l in lessons if l['subject'] == 'Англи хэл']
        self.assertEqual(len(english), 4)                          # 2 groups x 2 teachers
        self.assertTrue(all(l['joint'] for l in english))
        self.assertEqual({l['room'] for l in english}, {'408', '303'})

    def test_clash_rule_allows_joint_but_not_double_booking(self):
        a = dict(day='Даваа', time='08:00-09:30', subject='Алгебр', teacher='Ф.Нэг', room='510', group='КУ-1')
        joint = dict(a, group='ЦИ-1', room='513')
        other = dict(a, subject='Тусгай цаг', time='08:00-08:45', group='ЦИ-1', room='513')
        self.assertFalse(tt._clash(a, joint))
        self.assertTrue(tt._clash(a, other))


if __name__ == '__main__':
    unittest.main()
