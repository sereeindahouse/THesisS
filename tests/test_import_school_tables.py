"""FAKE school template imports and the twelve constructed reception questions.

All XLSX input is generated with the standard library in temporary folders.
No school workbook, personal record, network, database or model is read.
"""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from datetime import datetime
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from xml.sax.saxutils import escape
import zipfile

from reception_tables import ReceptionAnswerPath, ReceptionDataError, load_tables
from tools import import_school_tables as importer
from tools.import_school_tables import ImportSchoolTablesError, import_school_tables


# Independent snapshot of the public 2026-11-06 school template. The third
# (sample) row is deliberately invalid: it is guidance, never imported data.
HEADERS = {
    'Өрөө': ['Өрөөний дугаар', 'Давхар', 'Зориулалт (анги, лаборатори, алба, багшийн өрөө)', 'Тэнхим'],
    'Алба, үйлчилгээ': ['Алба', 'Давхар', 'Өрөө', 'Ажлын цаг', 'Албаны утас эсвэл имэйл'],
    'Багш, ажилтан': ['Овог нэр', 'Тэнхим', 'Албан тушаал', 'Өрөө', 'Оюутантай уулзах цаг'],
    'Анги (бүлэг)': ['Бүлгийн нэр', 'Курс', 'Тэнхим', 'Үндсэн өрөө', 'Ангийн багш'],
    'Хичээлийн хуваарь': ['Гараг', 'Цаг (эхлэх–дуусах)', 'Хичээл', 'Багш', 'Өрөө', 'Бүлэг'],
}
QUESTIONS = [
    'Номын сан хэддүгээр давхарт вэ?',
    'Сургалтын алба хаана байдаг вэ? Хэдэн цагт ажилладаг вэ?',
    'Цайны газар хэдэн цагт ажилладаг вэ?',
    '305 тоот хэддүгээр давхарт вэ?',
    'Компьютерын ухааны тэнхим хаана вэ?',
    'Бат багшийн өрөө хаана вэ?',
    'Бат багш хэзээ оюутантай уулздаг вэ?',
    'Бат багш одоо хичээлтэй юу?',
    'КУ-2 анги хаана хичээллэдэг вэ?',
    '2-р курс өнөөдөр хэдэн цагт хичээлтэй вэ?',
    'Санхүүгийн албатай яаж холбогдох вэ?',
    'Ангийн багш хэн бэ?',
]


def fake_sheets():
    values = {
        name: [['FAKE / зохиомол тайлбар'], list(columns), ['ЖИШЭЭ — АЛГАСАХ']]
        for name, columns in HEADERS.items()
    }
    values['Өрөө'] += [
        ['305', '3', 'Тэнхимийн өрөө', 'Компьютерын ухаан'],
        ['302', '3', 'Багшийн өрөө', 'Компьютерын ухаан'],
        ['210', '2', 'Номын сан', ''],
        ['101', '1', 'Сургалтын алба', ''],
        ['102', '1', 'Цайны газар', ''],
        ['103', '1', 'Санхүүгийн алба', ''],
    ]
    values['Алба, үйлчилгээ'] += [
        ['Номын сан', '2', '210', 'Да–Ба 09:00–18:00', 'library@example.invalid'],
        ['Сургалтын алба', '1', '101', 'Да–Ба 08:30–17:30', 'study@example.invalid'],
        ['Цайны газар', '1', '102', 'Да–Ба 08:00–19:00', '—'],
        ['Санхүүгийн алба', '1', '103', 'Да–Ба 09:00–17:00', 'finance@example.invalid'],
    ]
    # Бат is a constructed fixture label, not an assertion about a real person.
    values['Багш, ажилтан'] += [['Бат', 'Компьютерын ухаан', 'Багш', '302', 'Мя 14:00–16:00']]
    values['Анги (бүлэг)'] += [['КУ-2', '2', 'Компьютерын ухаан', '305', 'Бат']]
    values['Хичээлийн хуваарь'] += [['Даваа', '09:00–10:30', 'FAKE хичээл', 'Бат', '305', 'КУ-2']]
    values['Улирлын огноо'] = [
        ['Улирал эхлэх өдөр', '2030-01-01'],
        ['Улирал дуусах өдөр', '2030-06-30'],
        ['Амралтын өдрүүд', '2030-02-01'],
    ]
    values['Ресепшний асуулт'] = [['№', 'Асуулт', 'Хүснэгт']] + [
        [str(i), question, 'FAKE'] for i, question in enumerate(QUESTIONS, 1)
    ]
    return values


def write_xlsx(path, sheets, *, external=False):
    """Minimal OOXML fixture, including explicit row positions and blank cells."""
    ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    relns = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    workbook = [f'<workbook xmlns="{ns}" xmlns:r="{relns}"><sheets>']
    relationships = ['<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">']
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for index, (name, rows) in enumerate(sheets.items(), 1):
            workbook.append(f'<sheet name="{escape(name)}" sheetId="{index}" r:id="rId{index}"/>')
            relationships.append(f'<Relationship Id="rId{index}" Type="{relns}/worksheet" Target="worksheets/sheet{index}.xml"/>')
            xml = [f'<worksheet xmlns="{ns}"><sheetData>']
            for row_number, row in enumerate(rows, 1):
                xml.append(f'<row r="{row_number}">')
                for column, value in enumerate(row, 1):
                    column_name = ''
                    quotient = column
                    while quotient:
                        quotient, remainder = divmod(quotient - 1, 26)
                        column_name = chr(65 + remainder) + column_name
                    position = f'{column_name}{row_number}'
                    if isinstance(value, dict) and 'formula' in value:
                        xml.append(f'<c r="{position}"><f>{escape(value["formula"])}</f><v>2</v></c>')
                    elif value is not None:
                        xml.append(f'<c r="{position}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>')
                xml.append('</row>')
            xml.append('</sheetData></worksheet>')
            archive.writestr(f'xl/worksheets/sheet{index}.xml', ''.join(xml))
        workbook.append('</sheets></workbook>')
        if external:
            relationships.append(f'<Relationship Id="external" Type="{relns}/externalLink" Target="https://example.invalid/private.xlsx" TargetMode="External"/>')
        relationships.append('</Relationships>')
        archive.writestr('xl/workbook.xml', ''.join(workbook))
        archive.writestr('xl/_rels/workbook.xml.rels', ''.join(relationships))


class SchoolImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / 'FAKE-school.xlsx'
        self.output = self.root / 'runtime/school-tables/2030-01-08'
        self.sheets = fake_sheets()

    def tearDown(self):
        self.temp.cleanup()

    def import_fake(self, **options):
        write_xlsx(self.source, self.sheets)
        return import_school_tables(self.source, self.output, project_root=self.root,
                                    is_fake=True, **options)

    def assert_rejected_at(self, sheet, row, **options):
        with self.assertRaises(ImportSchoolTablesError) as caught:
            self.import_fake(**options)
        self.assertIn(sheet, str(caught.exception))
        self.assertIn(str(row), str(caught.exception))
        self.assertFalse(self.output.exists(), 'Invalid import must publish no partial dataset')

    def test_valid_import_has_four_loadable_csv_and_private_metadata(self):
        before = deepcopy(self.sheets)
        self.import_fake(timetable_complete=True)
        self.assertEqual(self.sheets, before)
        self.assertEqual({p.name for p in self.output.iterdir()}, {
            'rooms.csv', 'staff.csv', 'classes.csv', 'timetable.csv', 'import-metadata.json'})
        tables = load_tables(self.output)
        self.assertTrue(tables.is_fake)
        self.assertTrue(tables.timetable_complete)
        self.assertEqual(len(tables.rooms), 6)
        self.assertEqual(len(tables.staff), 1)
        self.assertEqual(tables.timetable[0].time, '09:00-10:30')

    def test_empty_rows_keep_original_excel_line_number(self):
        self.sheets['Багш, ажилтан'].insert(3, ['', '', '', '', ''])
        self.sheets['Багш, ажилтан'][4][3] = 'UNKNOWN-PRIVATE'
        self.assert_rejected_at('Багш, ажилтан', 5)

    def test_blank_rows_skipped_and_examples_never_imported(self):
        for name in HEADERS:
            self.sheets[name].insert(3, [])
            self.sheets[name].append([' ', None])
        self.import_fake()
        tables = load_tables(self.output)
        self.assertEqual(len(tables.staff), 1)
        self.assertFalse(any(row.name.startswith('ЖИШЭЭ') for row in tables.rooms))

    def test_reordered_header_and_values_map_by_name(self):
        rows = self.sheets['Өрөө']
        order = [3, 1, 0, 2]
        for index in [1] + list(range(3, len(rows))):
            rows[index] = [rows[index][i] for i in order]
        self.import_fake()
        self.assertEqual(load_tables(self.output).rooms[0].name, '305')

    def test_wrong_or_duplicate_header_rejected_at_second_row(self):
        self.sheets['Өрөө'][1][1] = self.sheets['Өрөө'][1][0]
        self.assert_rejected_at('Өрөө', 2)

    def test_invalid_floor_reports_sheet_and_row_without_cell_content(self):
        private = 'SECRET-INVALID-FLOOR'
        self.sheets['Өрөө'][3][1] = private
        with self.assertRaises(ImportSchoolTablesError) as caught:
            self.import_fake()
        self.assertIn('Өрөө', str(caught.exception))
        self.assertIn('4', str(caught.exception))
        self.assertNotIn(private, str(caught.exception))
        self.assertFalse(self.output.exists())

    def test_unknown_teacher_reference_reports_timetable_row(self):
        self.sheets['Хичээлийн хуваарь'][3][3] = 'FAKE-UNKNOWN'
        self.assert_rejected_at('Хичээлийн хуваарь', 4)

    def test_conflicting_lesson_rejected_without_publishing(self):
        self.sheets['Хичээлийн хуваарь'].append(
            ['Даваа', '10:00–11:00', 'FAKE давхцал', 'Бат', '305', 'КУ-2'])
        self.assert_rejected_at('Хичээлийн хуваарь', 5)

    def test_office_floor_disagreement_rejected(self):
        self.sheets['Алба, үйлчилгээ'][3][1] = '9'
        self.assert_rejected_at('Алба, үйлчилгээ', 4)

    def test_office_can_add_its_explicit_room_and_floor(self):
        self.sheets['Алба, үйлчилгээ'].append(
            ['FAKE туслах алба', '4', '401', 'Да 09:00–12:00', '—'])
        self.import_fake()
        room = next(row for row in load_tables(self.output).rooms if row.name == '401')
        self.assertEqual(room.floor, 4)
        self.assertEqual(room.services[0].name, 'FAKE туслах алба')

    def test_duplicate_service_name_in_different_room_is_ambiguous(self):
        self.sheets['Алба, үйлчилгээ'].append(
            ['Номын сан', '1', '101', 'Да 09:00–12:00', '—'])
        self.assert_rejected_at('Алба, үйлчилгээ', 8)

    def test_two_services_can_share_one_room_without_duplicate_room(self):
        self.sheets['Алба, үйлчилгээ'].append(
            ['FAKE зөвлөгөө', '1', '101', 'Мя 10:00–11:00', '—'])
        self.import_fake()
        tables = load_tables(self.output)
        room = next(row for row in tables.rooms if row.name == '101')
        self.assertEqual(len(room.services), 2)
        self.assertEqual(len([row for row in tables.rooms if row.name == '101']), 1)

    def test_constructed_international_phone_contact_is_preserved(self):
        # Non-routable all-zero fixture, never a real person's telephone.
        self.sheets['Алба, үйлчилгээ'][3][4] = '+000 0000 0000'
        self.import_fake()
        room = next(row for row in load_tables(self.output).rooms if row.name == '210')
        self.assertEqual(room.services[0].contact, '+000 0000 0000')

    def test_formula_like_contact_is_rejected_at_original_row(self):
        self.sheets['Алба, үйлчилгээ'][3][4] = '+SUM(1,2)'
        self.assert_rejected_at('Алба, үйлчилгээ', 4)

    def test_oversized_services_cell_reports_the_actual_appended_service_row(self):
        # Each individual value stays within 300 characters; ten colocated
        # services remain below the count limit but exceed the combined limit.
        for number in range(9):
            self.sheets['Алба, үйлчилгээ'].append([
                'FAKE' + chr(65 + number) * 296,
                '1', '101', 'FAKE ' + '0' * 295, 'x' * 284 + '@example.invalid'])
        self.assert_rejected_at('Алба, үйлчилгээ', 16)

    def test_incomplete_schedule_is_default_despite_valid_term_dates(self):
        self.import_fake()
        self.assertFalse(load_tables(self.output).timetable_complete)

    def test_complete_requires_term_dates_and_confirmed_holidays(self):
        self.sheets['Улирлын огноо'][0][1] = ''
        self.assert_rejected_at('Улирлын огноо', 1, timetable_complete=True)

    def test_complete_rejects_unknown_holidays(self):
        self.sheets['Улирлын огноо'][2][1] = ''
        self.assert_rejected_at('Улирлын огноо', 3, timetable_complete=True)

    def test_explicit_no_holidays_is_accepted(self):
        self.sheets['Улирлын огноо'][2][1] = 'байхгүй'
        self.import_fake(timetable_complete=True)
        metadata = json.loads((self.output / 'import-metadata.json').read_text(encoding='utf-8'))
        self.assertEqual(metadata['holidays'], [])

    def test_calendar_invalid_date_rejected_at_its_row(self):
        self.sheets['Улирлын огноо'][0][1] = '2030-02-30'
        self.assert_rejected_at('Улирлын огноо', 1)

    def test_reversed_term_dates_rejected(self):
        self.sheets['Улирлын огноо'][1][1] = '2029-12-31'
        self.assert_rejected_at('Улирлын огноо', 2)

    def test_holiday_outside_term_rejected(self):
        self.sheets['Улирлын огноо'][2][1] = '2031-02-01'
        self.assert_rejected_at('Улирлын огноо', 3)

    def test_formula_in_real_row_rejected(self):
        self.sheets['Өрөө'][3][1] = {'formula': '1+1'}
        self.assert_rejected_at('Өрөө', 4)

    def test_formula_in_skipped_sample_row_is_never_imported_or_evaluated(self):
        self.sheets['Өрөө'][2] = [{'formula': '1+1'}]
        self.import_fake()
        self.assertEqual(len(load_tables(self.output).rooms), 6)

    def test_external_workbook_relationship_rejected(self):
        write_xlsx(self.source, self.sheets, external=True)
        with self.assertRaises(ImportSchoolTablesError):
            import_school_tables(self.source, self.output, project_root=self.root, is_fake=True)
        self.assertFalse(self.output.exists())

    def test_malformed_workbook_rejected(self):
        self.source.write_bytes(b'not-an-xlsx')
        with self.assertRaises(ImportSchoolTablesError):
            import_school_tables(self.source, self.output, project_root=self.root, is_fake=True)
        self.assertFalse(self.output.exists())

    def test_huge_numeric_xml_index_is_safe_malformed_error_without_cell_echo(self):
        write_xlsx(self.source, self.sheets)
        original = self.source.read_bytes()
        huge_index = '9' * 4500
        with zipfile.ZipFile(io.BytesIO(original)) as before:
            with zipfile.ZipFile(self.source, 'w', zipfile.ZIP_DEFLATED) as after:
                for member in before.namelist():
                    raw = before.read(member)
                    if member == 'xl/worksheets/sheet1.xml':
                        raw = raw.replace(b'r="A4"', ('r="A' + huge_index + '"').encode(), 1)
                    after.writestr(member, raw)
        stdout = io.StringIO()
        with redirect_stdout(stdout), self.assertRaises(ImportSchoolTablesError) as caught:
            import_school_tables(self.source, self.output, project_root=self.root, is_fake=True)
        self.assertEqual(caught.exception.sheet, 'XLSX')
        self.assertEqual(caught.exception.row, 0)
        self.assertNotIn(huge_index, str(caught.exception))
        self.assertEqual(stdout.getvalue(), '')
        self.assertFalse(self.output.exists())

    def test_missing_sheet_is_not_silently_ignored(self):
        del self.sheets['Анги (бүлэг)']
        with self.assertRaises(ImportSchoolTablesError):
            self.import_fake()
        self.assertFalse(self.output.exists())

    def test_runtime_output_path_is_required(self):
        write_xlsx(self.source, self.sheets)
        for relative in ['public-data/2030-01-08', 'runtime/school-tables/not-a-date',
                         'runtime/school-tables/2030-02-30', 'runtime/elsewhere/2030-01-08']:
            with self.subTest(path=relative), self.assertRaises(ImportSchoolTablesError):
                import_school_tables(self.source, self.root / relative,
                                     project_root=self.root, is_fake=True)

    def test_existing_output_is_preserved(self):
        self.output.mkdir(parents=True)
        preserved = self.output / 'preserve.txt'
        preserved.write_text('KEEP', encoding='utf-8')
        with self.assertRaises(ImportSchoolTablesError):
            self.import_fake()
        self.assertEqual(preserved.read_text(encoding='utf-8'), 'KEEP')
        self.assertEqual(len(list(self.output.iterdir())), 1)

    def test_lock_collision_preserves_another_importers_lock(self):
        self.output.parent.mkdir(parents=True)
        lock = self.output.parent / ('.' + self.output.name + '.import.lock')
        lock.write_text('FAKE OTHER IMPORTER', encoding='utf-8')
        with self.assertRaises(ImportSchoolTablesError):
            self.import_fake()
        self.assertEqual(lock.read_text(encoding='utf-8'), 'FAKE OTHER IMPORTER')
        self.assertFalse(self.output.exists())

    def test_failed_production_loader_publishes_nothing_and_releases_own_lock(self):
        with patch.object(importer.reception, 'load_tables',
                          side_effect=ReceptionDataError('FAKE PRIVATE FAILURE')):
            with self.assertRaises(ImportSchoolTablesError) as caught:
                self.import_fake()
        self.assertNotIn('FAKE PRIVATE FAILURE', str(caught.exception))
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.output.parent.iterdir()), [])

    def test_unfilled_template_has_no_records_from_guidance_or_examples(self):
        for name in HEADERS:
            self.sheets[name] = self.sheets[name][:3] + [[], ['', '']]
        for row in self.sheets['Улирлын огноо']:
            row[1] = ''
        result = self.import_fake()
        self.assertEqual(result['counts'], dict(rooms=0, staff=0, classes=0, timetable=0))
        tables = load_tables(self.output)
        self.assertFalse(tables.timetable_complete)
        self.assertTrue(tables.is_fake)

    def test_cli_invalid_row_does_not_print_private_cell_text(self):
        private = 'FAKE-PRIVATE-INVALID-FLOOR'
        self.sheets['Өрөө'][3][1] = private
        write_xlsx(self.source, self.sheets)
        stdout, stderr = io.StringIO(), io.StringIO()
        real_import = import_school_tables

        def local_import(source, output, **options):
            return real_import(source, output, project_root=self.root, **options)

        with patch.object(importer, 'import_school_tables', side_effect=local_import):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                status = importer.main([str(self.source), '--output', str(self.output), '--is-fake'])
        self.assertEqual(status, 1)
        self.assertEqual(stdout.getvalue(), '')
        self.assertIn('Өрөө', stderr.getvalue())
        self.assertIn('4', stderr.getvalue())
        self.assertNotIn(private, stderr.getvalue())
        self.assertFalse(self.output.exists())

    def test_import_does_not_print_fake_person_or_cell_text(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.import_fake()
        self.assertNotIn('Бат', output.getvalue())
        self.assertNotIn('finance@example.invalid', output.getvalue())

    def test_source_and_disabled_config_are_preserved_byte_for_byte(self):
        config = self.root / 'config/reception-tables.json'
        config.parent.mkdir()
        raw_config = b'{"enabled":false,"reviewed":false,"source":""}\n'
        config.write_bytes(raw_config)
        write_xlsx(self.source, self.sheets)
        raw_source = self.source.read_bytes()
        import_school_tables(self.source, self.output, project_root=self.root, is_fake=True)
        self.assertEqual(self.source.read_bytes(), raw_source)
        self.assertEqual(config.read_bytes(), raw_config)

    def test_metadata_flags_accept_only_booleans(self):
        for option, value in [('is_fake', 'true'), ('is_fake', 1),
                              ('timetable_complete', 'true'), ('timetable_complete', 1)]:
            with self.subTest(option=option, value=value), self.assertRaises(ImportSchoolTablesError):
                write_xlsx(self.source, self.sheets)
                import_school_tables(self.source, self.output, project_root=self.root,
                                     **{option: value})


class ImportedReceptionQuestionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        source = cls.root / 'FAKE-school.xlsx'
        output = cls.root / 'runtime/school-tables/2030-01-08'
        write_xlsx(source, fake_sheets())
        import_school_tables(source, output, project_root=cls.root,
                             timetable_complete=True, is_fake=True)
        cls.tables = load_tables(output)
        cls.path = ReceptionAnswerPath(cls.tables, enabled=True)
        cls.now = datetime(2030, 1, 7, 9, 30)  # Constructed Monday inside term.

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def ask(self, number):
        result = self.path.answer(QUESTIONS[number - 1], now=self.now)
        self.assertIsNotNone(result)
        self.assertTrue(result['reception']['is_fake'])
        self.assertFalse(result['reception']['physical_location_confirmed'])
        return result

    def test_question_01_library_floor(self):
        self.assertIn('2-р давхар', self.ask(1)['answer'])

    def test_question_02_study_office_location_and_hours(self):
        answer = self.ask(2)['answer']
        self.assertIn('101', answer)
        self.assertIn('08:30', answer)

    def test_question_03_cafeteria_hours(self):
        self.assertIn('19:00', self.ask(3)['answer'])

    def test_question_04_room_floor(self):
        self.assertIn('3-р давхар', self.ask(4)['answer'])

    def test_question_05_department_location(self):
        self.assertIn('305', self.ask(5)['answer'])

    def test_question_06_teacher_office_is_listed_location_only(self):
        answer = self.ask(6)['answer']
        self.assertIn('302', answer)
        self.assertNotIn('өрөөндөө байна', answer)

    def test_question_07_teacher_meeting_hours(self):
        self.assertIn('14:00', self.ask(7)['answer'])

    def test_question_08_teacher_now_starts_with_schedule_qualification(self):
        result = self.ask(8)
        self.assertTrue(result['answer'].casefold().startswith('хуваариар бол'))
        self.assertIn('хичээлтэй', result['answer'])
        self.assertNotIn('302', result['answer'])
        self.assertNotIn('305', result['answer'])
        self.assertFalse(result['reception']['physical_location_confirmed'])

    def test_question_09_group_home_room(self):
        self.assertIn('305', self.ask(9)['answer'])

    def test_question_10_course_today_schedule(self):
        answer = self.ask(10)['answer']
        self.assertIn('09:00', answer)
        self.assertIn('10:30', answer)

    def test_question_11_finance_contact(self):
        self.assertIn('finance@example.invalid', self.ask(11)['answer'])

    def test_question_12_group_teacher_requires_group_clarification(self):
        result = self.ask(12)
        self.assertIsNone(result['answer'])
        self.assertIn('бүл', result['message'].casefold())


if __name__ == '__main__':
    unittest.main()
