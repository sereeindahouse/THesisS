"""FAKE table contracts only: no real school records, DBs, audio or APIs."""
import csv
from dataclasses import FrozenInstanceError
from datetime import datetime
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from reception_tables import (CONFIG_PATH, MAX_BYTES, ReceptionAnswerPath,
    ReceptionDataError, SCHEMA, load_tables)

FIXTURE = Path(__file__).parent / 'fixtures' / 'reception_fake'


class ReceptionLoaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.csv = self.root / 'csv'
        shutil.copytree(FIXTURE, self.csv)

    def tearDown(self):
        self.temp.cleanup()

    def change(self, table, transform):
        path = self.csv / (table + '.csv')
        lines = list(csv.reader(io.StringIO(path.read_text(encoding='utf-8-sig'))))
        transform(lines)
        with path.open('w', newline='', encoding='utf-8') as f:
            csv.writer(f).writerows(lines)

    def test_csv_has_four_immutable_tables(self):
        tables = load_tables(self.csv, is_fake=True, dataset_label='FAKE only')
        self.assertEqual((len(tables.rooms), len(tables.staff), len(tables.classes), len(tables.timetable)),
                         (3, 2, 2, 3))
        self.assertTrue(tables.is_fake)
        self.assertIsInstance(tables.rooms, tuple)
        with self.assertRaises(FrozenInstanceError):
            tables.rooms[0].floor = 88

    def test_xlsx_and_csv_are_equivalent(self):
        options = dict(is_fake=True, timetable_complete=True, dataset_label='FAKE equivalence')
        self.assertEqual(load_tables(FIXTURE / 'reception_fake.xlsx', **options),
                         load_tables(self.csv, **options))

    def test_utf8_bom_and_reordered_columns_are_supported(self):
        path = self.csv / 'rooms.csv'
        path.write_text('name,floor\nFAKE-201,2\nFAKE-301,3\nFAKE-101,1\n', encoding='utf-8-sig')
        self.assertEqual(load_tables(self.csv).rooms[0].floor, 2)

    def test_missing_table_is_not_a_partial_load(self):
        (self.csv / 'staff.csv').unlink()
        with self.assertRaises(ReceptionDataError):
            load_tables(self.csv)

    def test_extra_and_duplicate_headers_rejected(self):
        for header in ['floor,name,secret', 'floor,floor']:
            with self.subTest(header=header):
                (self.csv / 'rooms.csv').write_text(header + '\n2,FAKE-201\n', encoding='utf-8')
                with self.assertRaises(ReceptionDataError):
                    load_tables(self.csv)

    def test_duplicate_names_casefolded_rejected(self):
        self.change('rooms', lambda rows: rows.append(['9', 'fake-201']))
        with self.assertRaisesRegex(ReceptionDataError, 'duplicate'):
            load_tables(self.csv)

    def test_unknown_references_rejected(self):
        for table, column, value in [('staff', 2, 'UNKNOWN'), ('classes', 1, 'UNKNOWN'),
                                     ('timetable', 2, 'UNKNOWN'), ('timetable', 3, 'UNKNOWN'),
                                     ('timetable', 4, 'UNKNOWN')]:
            with self.subTest(table=table, column=column):
                shutil.copytree(FIXTURE, self.csv, dirs_exist_ok=True)
                self.change(table, lambda rows: rows[1].__setitem__(column, value))
                with self.assertRaises(ReceptionDataError):
                    load_tables(self.csv)

    def test_invalid_times_and_overnight_rows_rejected(self):
        for value in ['09:99-10:00', '25:00-26:00', '10:00-09:00', '09:00-09:00', '9-10']:
            with self.subTest(value=value):
                self.change('timetable', lambda rows: rows[1].__setitem__(1, value))
                with self.assertRaises(ReceptionDataError):
                    load_tables(self.csv)

    def test_invalid_day_rejected(self):
        self.change('timetable', lambda rows: rows[1].__setitem__(0, 'someday'))
        with self.assertRaises(ReceptionDataError):
            load_tables(self.csv)

    def test_mongolian_weekday_canonicalized(self):
        self.change('timetable', lambda rows: rows[1].__setitem__(0, 'Даваа'))
        self.assertEqual(load_tables(self.csv).timetable[0].day, 'mon')

    def test_teacher_room_and_group_conflicts_rejected(self):
        for row in [ ['mon', '09:30-10:30', 'FAKE-B', 'FAKE-101', 'Зохиомол Наран'],
                     ['mon', '09:30-10:30', 'FAKE-B', 'FAKE-301', 'Зохиомол Сар'],
                     ['mon', '09:30-10:30', 'FAKE-A', 'FAKE-101', 'Зохиомол Сар'] ]:
            with self.subTest(row=row):
                shutil.copytree(FIXTURE, self.csv, dirs_exist_ok=True)
                self.change('timetable', lambda rows: rows.append(row))
                with self.assertRaisesRegex(ReceptionDataError, 'overlapping'):
                    load_tables(self.csv)

    def test_adjacent_periods_and_home_room_differences_are_valid(self):
        tables = load_tables(self.csv)
        self.assertNotEqual(tables.staff[0].room, tables.timetable[0].room)
        self.assertEqual(tables.timetable[0].time, '09:00-10:00')
        self.assertEqual(tables.timetable[1].time, '10:00-11:00')

    def test_blank_rows_accepted_but_blank_cells_rejected(self):
        self.change('staff', lambda rows: rows.append([]))
        self.assertEqual(len(load_tables(self.csv).staff), 2)
        self.change('staff', lambda rows: rows[1].__setitem__(2, ''))
        with self.assertRaises(ReceptionDataError):
            load_tables(self.csv)

    def test_invalid_floor_and_formula_like_cell_rejected(self):
        for floor in ['second', '100', '-6', '=2+1']:
            with self.subTest(floor=floor):
                self.change('rooms', lambda rows: rows[1].__setitem__(0, floor))
                with self.assertRaises(ReceptionDataError):
                    load_tables(self.csv)

    def test_oversized_input_rejected_before_read(self):
        (self.csv / 'rooms.csv').write_bytes(b'x' * (MAX_BYTES + 1))
        with self.assertRaises(ReceptionDataError):
            load_tables(self.csv)

    def test_malformed_workbook_rejected(self):
        path = self.root / 'bad.xlsx'
        path.write_bytes(b'not an excel file')
        with self.assertRaises(ReceptionDataError):
            load_tables(path)

    def test_workbook_formula_and_entity_declaration_rejected(self):
        raw = (FIXTURE / 'reception_fake.xlsx').read_bytes()
        for replacement in ['<f>1+1</f><v>2</v>', '<!DOCTYPE x [<!ENTITY e "x">]>']:
            with self.subTest(replacement=replacement):
                path = self.root / 'bad.xlsx'
                with zipfile.ZipFile(io.BytesIO(raw)) as original, zipfile.ZipFile(path, 'w') as changed:
                    for name in original.namelist():
                        value = original.read(name)
                        if name == 'xl/worksheets/sheet1.xml':
                            if replacement.startswith('<f>'):
                                value = value.replace(b'<is><t>2</t></is>', replacement.encode(), 1)
                            else:
                                value = replacement.encode() + value
                        changed.writestr(name, value)
                with self.assertRaises(ReceptionDataError):
                    load_tables(path)


class ReceptionAnswersTests(unittest.TestCase):
    def setUp(self):
        self.tables = load_tables(FIXTURE, timetable_complete=True, is_fake=True, dataset_label='FAKE test only')
        self.path = ReceptionAnswerPath(self.tables, enabled=True)

    def test_disabled_path_never_handles_query(self):
        path = ReceptionAnswerPath(self.tables)
        self.assertFalse(path.recognizes('FAKE-201 өрөө хаана вэ?'))
        self.assertIsNone(path.answer('FAKE-201 өрөө хаана вэ?'))

    def test_exact_room_answer_is_marked_fake(self):
        result = self.path.answer('FAKE-201 өрөө хаана байдаг вэ?')
        self.assertEqual(result['reason_code'], 'reception_room_lookup')
        self.assertIn('2-р давхар', result['answer'])
        self.assertIn('FAKE', result['answer'])
        self.assertEqual(result['reception']['source_table'], 'rooms')

    def test_english_room_and_casefolded_query(self):
        self.assertEqual(self.path.answer('Where is room fake-201?')['reason_code'], 'reception_room_lookup')

    def test_unknown_room_does_not_guess(self):
        result = self.path.answer('FAKE-20 өрөө хаана вэ?')
        self.assertIsNone(result['answer'])
        self.assertEqual(result['reason_code'], 'reception_room_not_found')

    def test_teacher_only_schedule_no_room_no_person_location_claim(self):
        result = self.path.answer('Зохиомол Наран багш хаана байна вэ даваа 09:30?')
        self.assertEqual(result['reception']['timetable_status'], 'in_class')
        self.assertIn('Хуваарийн дагуу (даваа 09:30): хичээлтэй', result['answer'])
        self.assertFalse(result['reception']['physical_location_confirmed'])
        self.assertNotIn('FAKE-201', str(result))
        self.assertNotIn('FAKE-301', str(result))
        self.assertNotIn('FAKE-A', str(result))

    def test_time_boundaries_are_start_inclusive_end_exclusive(self):
        for time, status in [('08:59', 'free'), ('09:00', 'in_class'), ('10:00', 'in_class'), ('11:00', 'free')]:
            with self.subTest(time=time):
                result = self.path.answer('Зохиомол Наран багш хаана байна вэ mon ' + time)
                self.assertEqual(result['reception']['timetable_status'], status)

    def test_requires_time_or_injected_local_datetime(self):
        query = 'Зохиомол Наран багш хаана вэ?'
        self.assertEqual(self.path.answer(query)['reason_code'], 'reception_time_required')
        result = self.path.answer(query, now=datetime(2030, 1, 7, 9, 30))  # FAKE Monday
        self.assertEqual(result['reception']['timetable_status'], 'in_class')
        self.assertIn('(даваа 09:30)', result['answer'])

    def test_every_teacher_status_keeps_its_requested_day_and_time_in_answer(self):
        for day, time, state in [('tue', '09:30', 'хичээлгүй'), ('mon', '09:30', 'хичээлтэй')]:
            with self.subTest(day=day):
                result = self.path.answer('Зохиомол Наран багш хаана вэ ' + day + ' ' + time)
                self.assertIn(('мягмар' if day == 'tue' else 'даваа') + ' ' + time, result['answer'])
                self.assertIn(state, result['answer'])
                self.assertNotIn('FAKE-201', result['answer'])
                self.assertNotIn('FAKE-301', result['answer'])

    def test_incomplete_schedule_is_unknown_outside_a_listed_lesson(self):
        path = ReceptionAnswerPath(load_tables(FIXTURE), enabled=True)
        result = path.answer('Зохиомол Наран багш хаана вэ mon 12:30')
        self.assertIsNone(result['answer'])
        self.assertEqual(result['reason_code'], 'reception_timetable_incomplete')
        self.assertEqual(path.answer('Зохиомол Наран багш хаана вэ mon 09:30')['reception']['timetable_status'], 'in_class')

    def test_unknown_teacher_not_confused_with_partial_name(self):
        self.assertEqual(self.path.answer('Наран багш хаана вэ?')['reason_code'], 'reception_teacher_not_found')

    def test_unrelated_or_compound_questions_left_for_existing_router(self):
        for query in ['Сургалтын төлбөр хэд вэ?', 'Зохиомол Наран багшийн цалин хэд вэ?',
                      'FAKE-201 болон FAKE-301 өрөө хаана вэ?',
                      'where is room FAKE-201 and what is tuition?',
                      'Зохиомол Наран багш хаана вэ мөн элсэлт хэзээ вэ?', None, '', 'a'*1001]:
            with self.subTest(query=query):
                self.assertFalse(self.path.recognizes(query))
                self.assertIsNone(self.path.answer(query))

    def test_invalid_explicit_time_does_not_guess(self):
        result = self.path.answer('Зохиомол Наран багш хаана вэ mon 29:59')
        self.assertEqual(result['reason_code'], 'reception_invalid_time')


class ReceptionConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'config').mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def config(self, **values):
        data = dict(schema_version=1, enabled=False, reviewed=False, source='', is_fake=False)
        data.update(values)
        (self.root / CONFIG_PATH).write_text(json.dumps(data), encoding='utf-8')

    def test_missing_and_default_disabled_configs_do_not_load_data(self):
        self.assertFalse(ReceptionAnswerPath.from_config(self.root).enabled)
        self.config(source='runtime/forbidden.csv')
        with patch('reception_tables.load_tables', side_effect=AssertionError('Disabled must not load')):
            self.assertFalse(ReceptionAnswerPath.from_config(self.root).enabled)

    def test_enabled_unreviewed_data_fails_closed(self):
        self.config(enabled=True)
        path = ReceptionAnswerPath.from_config(self.root)
        self.assertTrue(path.enabled)
        self.assertEqual(path.answer('FAKE-201 өрөө хаана вэ?')['reason_code'], 'reception_data_unavailable')

    def test_boolean_schema_version_is_not_integer_one(self):
        self.config(enabled=True, reviewed=True, schema_version=True, source='data/reception/fake.xlsx')
        with patch('reception_tables.load_tables', side_effect=AssertionError('Invalid schema must not load')):
            self.assertEqual(ReceptionAnswerPath.from_config(self.root).error, 'reception_data_unavailable')

    def test_broken_config_does_not_enable_a_new_answer_path(self):
        for text in ['not-json', '[]', '{"enabled": "true"}']:
            with self.subTest(text=text):
                (self.root / CONFIG_PATH).write_text(text, encoding='utf-8')
                path = ReceptionAnswerPath.from_config(self.root)
                self.assertFalse(path.enabled)
                self.assertIsNone(path.answer('FAKE-201 өрөө хаана вэ?'))

    def test_protected_escape_and_unapproved_paths_never_read(self):
        for source in ['runtime/private.xlsx', 'models/private.xlsx', 'audio/private.xlsx', '../escape.xlsx',
                       'CORE/database/website.db', 'config/arbitrary.xlsx', '/outside.xlsx',
                       'tests/fixtures/reception_fake']:
            with self.subTest(source=source):
                self.config(enabled=True, reviewed=True, source=source)
                with patch('reception_tables.load_tables', side_effect=AssertionError('Must not read rejected path')):
                    path = ReceptionAnswerPath.from_config(self.root)
                self.assertEqual(path.error, 'reception_data_unavailable')

    def test_explicit_fake_fixture_config_works(self):
        target = self.root / 'tests/fixtures/reception_fake'
        shutil.copytree(FIXTURE, target)
        self.config(enabled=True, reviewed=True, source='tests/fixtures/reception_fake', is_fake=True,
                    timetable_complete=True, dataset_label='FAKE fixture')
        path = ReceptionAnswerPath.from_config(self.root)
        self.assertIsNone(path.error)
        self.assertIn('FAKE', path.answer('FAKE-201 өрөө хаана вэ?')['answer'])

    def test_resolved_internal_symlink_cannot_escape_approved_prefix(self):
        original = Path.resolve
        # Mock resolution to an ordinary unapproved temp path. No real private
        # directory is created, inspected or read by this regression.
        for source, fake in [('data/reception/input.xlsx', False),
                             ('tests/fixtures/reception_fake', True)]:
            with self.subTest(source=source):
                self.config(enabled=True, reviewed=True, source=source, is_fake=fake)
                lexical = self.root / source
                def resolve(path, *args, **kwargs):
                    return self.root / 'unapproved_fixture' if path == lexical else original(path, *args, **kwargs)
                with patch.object(Path, 'resolve', resolve), patch('reception_tables.load_tables') as load:
                    path = ReceptionAnswerPath.from_config(self.root)
                self.assertEqual(path.error, 'reception_data_unavailable')
                load.assert_not_called()


if __name__ == '__main__':
    unittest.main()
