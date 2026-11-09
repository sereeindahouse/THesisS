"""FAKE spreadsheets only: no real staff names, phones or rooms."""
import csv
from pathlib import Path
import sys
import tempfile
import unittest

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import prepare_school_dataset as prep  # noqa: E402


class PrepareSchoolDatasetTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        book = openpyxl.Workbook()
        rooms = book.active
        rooms.append([None, 'Хүснэгт 1. FAKE'])
        rooms.append([None, 'Д/д', 'Давхар', 'Дугаар', 'Зориулалт', 'Хэмжээ', 'Суудал'])
        rooms.append([None, 1, 2, 3, 4, 5, 6])
        rooms.append([None, 1, 'B1 давхар', 'B6', 'Зохиомол клуб', 10, 5])
        rooms.append([None, 2, 'IV давхар', 401, 'Анги', 50, 30])
        rooms.append([None, 3, None, 402, 'Сургалтын алба', 20, 4])
        rooms.append([None, 4, None, 402, 'Анги', 20, 4])
        groups = book.create_sheet('Sheet2')
        groups.append([None, '№', 'Ангийн №', 'Анги', 'Оюутны тоо', 'АУБ'])
        groups.append([None, 1, 401, 'КУ-2', 20, 'Ф.Зохиомол'])
        groups.append([None, None, None, 'Өрөөний зориулалт ', None])
        groups.append([None, 1, 'В6', 'КУТ багш өрөө'])
        self.rooms = self.dir / 'rooms.xlsx'
        book.save(self.rooms)
        book = openpyxl.Workbook()
        staff = book.active
        staff.append(['FAKE УТАСНЫ ЖАГСААЛТ'])
        staff.append(['Д/д', 'Нэр', 'Албан тушаал', 'Утас', 'Имэйл хаяг', 'Өрөө', 'Дотуур утас'])
        staff.append([1, 'Ф.Зохиомол', 'КУТ-ийн багш', 99999999, 'fake@example.invalid', 401, None])
        staff.append([2, 'Ф.Цэвэрлэгч', 'Үйлчлэгч', 88888888, None, None, None])
        staff.append([3, None, None, 77777777, None, None, None])
        self.staff = self.dir / 'staff.xlsx'
        book.save(self.staff)
        self.official = self.dir / 'official.csv'
        with open(self.official, 'w', encoding='utf-8', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(['no', 'position', 'name'])
            writer.writerow([1, 'Компьютерын ухааны тэнхимийн багш', 'Ф.Зохиомол'])
            writer.writerow([2, 'Үйлчлэгч', 'Ф.Цэвэрлэгч'])
            writer.writerow([3, 'Эмч', 'Ф.Байхгүй'])

    def tearDown(self):
        self.tmp.cleanup()

    def run_all(self):
        report = prep.Report()
        rooms, groups = prep.read_rooms(self.rooms, report)
        staff, comparison = prep.read_staff(self.staff, prep.read_official(self.official), rooms, report)
        groups = prep.check_groups(groups, staff, rooms, report)
        services = prep.services_from(rooms, report)
        return report, rooms, groups, staff, comparison, services

    def test_cleans_rooms_without_guessing(self):
        report, rooms, *_ = self.run_all()
        self.assertEqual(rooms['В6']['floor'], -1)          # Latin B unified, B1 floor kept
        self.assertEqual(rooms['402']['floor'], 4)          # merged floor cell carried down
        self.assertEqual(rooms['В6']['department'], 'Компьютерын ухааны тэнхим')
        problems = ' '.join(issue['problem'] for issue in report.issues)
        self.assertIn('402 өрөө давхардсан', problems)
        self.assertNotIn('ДУГААР', problems)                # header rows are not rooms

    def test_staff_drops_phones_and_service_staff_and_compares_lists(self):
        _, rooms, groups, staff, comparison, services = self.run_all()
        self.assertEqual([p['name'] for p in staff], ['Ф.Зохиомол'])
        self.assertEqual(staff[0]['department'], 'Компьютерын ухааны тэнхим')
        self.assertNotIn('99999999', repr(staff))
        status = {row['name']: row['status'] for row in comparison}
        self.assertEqual(status['Ф.Байхгүй'], 'Зөвхөн орон тооны жагсаалтад')
        self.assertEqual(groups[0]['department'], 'Компьютерын ухааны тэнхим')
        self.assertEqual(groups[0]['teacher'], 'Ф.Зохиомол')
        self.assertEqual([s['name'] for s in services], ['Сургалтын алба'])

    def test_filled_template_has_no_phone_numbers(self):
        _, rooms, groups, staff, _, services = self.run_all()
        path, counts = prep.fill_template(self.dir, rooms, staff, groups, services)
        text = ' '.join(str(cell.value) for sheet in openpyxl.load_workbook(path).worksheets
                        for row in sheet.iter_rows() for cell in row if cell.value is not None)
        for phone in ('99999999', '88888888', '77777777'):
            self.assertNotIn(phone, text)
        self.assertEqual(counts['Багш, ажилтан'], 1)


if __name__ == '__main__':
    unittest.main()
