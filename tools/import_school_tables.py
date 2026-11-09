"""Import the reviewed Mongolian school form offline; never enable reception.

Only the dated runtime directory is written. Cells and personal records are not
printed. The five table sheets use row 2 headers and data from row 4; the dates
sheet instead uses its original three label/value rows.
"""
from __future__ import annotations

import argparse
import csv
from datetime import date, timedelta
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import reception_tables as reception

# All Mongolian -> canonical field mappings live here. Column order may change,
# but missing, duplicate and unexpected headers are rejected.
SHEET_MAPPING = {
    'Өрөө': ('rooms', {
        'Өрөөний дугаар': 'name', 'Давхар': 'floor',
        'Зориулалт (анги, лаборатори, алба, багшийн өрөө)': 'purpose', 'Тэнхим': 'department'}),
    'Алба, үйлчилгээ': ('services', {
        'Алба': 'name', 'Давхар': 'floor', 'Өрөө': 'room',
        'Ажлын цаг': 'office_hours', 'Албаны утас эсвэл имэйл': 'contact'}),
    'Багш, ажилтан': ('staff', {
        'Овог нэр': 'name', 'Тэнхим': 'department', 'Албан тушаал': 'role',
        'Өрөө': 'room', 'Оюутантай уулзах цаг': 'office_hours'}),
    'Анги (бүлэг)': ('classes', {
        'Бүлгийн нэр': 'group', 'Курс': 'course', 'Тэнхим': 'department',
        'Үндсэн өрөө': 'room', 'Ангийн багш': 'teacher'}),
    'Хичээлийн хуваарь': ('timetable', {
        'Гараг': 'day', 'Цаг (эхлэх–дуусах)': 'time', 'Хичээл': 'subject',
        'Багш': 'teacher', 'Өрөө': 'room', 'Бүлэг': 'group'}),
}
DATE_LABELS = ('Улирал эхлэх өдөр', 'Улирал дуусах өдөр', 'Амралтын өдрүүд')
NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
RID = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'
MAX_BYTES = reception.MAX_BYTES
MAX_ROWS = reception.MAX_ROWS
EMPTY_MARKERS = {'', '-', '—', '–'}


class ImportSchoolTablesError(ValueError):
    """Actionable sheet/row diagnostics without echoing cell contents."""

    def __init__(self, sheet, row, message):
        self.sheet, self.row = sheet, row
        super().__init__(f'{sheet} · мөр {row}: {message}')


def _fail(sheet, row, message):
    raise ImportSchoolTablesError(sheet, row, message)


def _text(value, sheet, row, *, optional=False, multiline=False, contact=False):
    value = '' if value is None else str(value).strip()
    if optional and value in EMPTY_MARKERS:
        return ''
    if (not value or len(value) > (8192 if multiline else reception.MAX_CELL)
            or any(ord(c) < 32 and (not multiline or c not in '\n\r\t') for c in value)
            or value.startswith(('=', '@'))
            or value.startswith('+') and not (contact and re.fullmatch(r'\+[0-9][0-9 ()-]{3,40}', value))):
        _fail(sheet, row, 'Хоосон, хэт урт эсвэл томьёотой талбарыг шалгана уу.')
    return value


def _floor(value, sheet, row):
    value = _text(value, sheet, row)
    if not re.fullmatch(r'-?\d{1,2}', value) or not -5 <= int(value) <= 99:
        _fail(sheet, row, 'Давхар -5…99 бүхэл тоо байна.')
    return str(int(value))


def _xml(archive, member):
    try:
        raw = archive.read(member)
        if len(raw) > MAX_BYTES or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
            raise ValueError
        return ET.fromstring(raw)
    except (KeyError, ValueError, ET.ParseError):
        _fail('XLSX', 0, 'XML бүтэц дутуу, эвдэрсэн эсвэл зөвшөөрөгдөхгүй байна.')


def _read_workbook(source):
    try:
        if source.suffix.casefold() != '.xlsx' or not source.is_file() or source.stat().st_size > MAX_BYTES:
            _fail('XLSX', 0, '2 MiB-аас бага .xlsx файл сонгоно уу.')
        raw = source.read_bytes()
        if len(raw) > MAX_BYTES:
            _fail('XLSX', 0, 'Файлын хэмжээ унших үед зөвшөөрөгдөх хязгаараас хэтэрсэн.')
        with zipfile.ZipFile(io.BytesIO(raw)) as book:
            infos = book.infolist()
            if (len(infos) > 100 or len({i.filename for i in infos}) != len(infos)
                    or sum(i.file_size for i in infos) > 8 * MAX_BYTES
                    or any(i.file_size > MAX_BYTES for i in infos)):
                _fail('XLSX', 0, 'Файлын задарсан хэмжээ эсвэл ZIP бүтэц зөвшөөрөгдөхгүй.')
            # Reject external relationships in every part, not just workbook.
            for member in (i.filename for i in infos if i.filename.endswith('.rels')):
                for rel in _xml(book, member):
                    if rel.attrib.get('TargetMode') == 'External':
                        _fail('XLSX', 0, 'Гадаад холбоосыг утга болгон хуулж арилгана уу.')
            rels = {}
            for rel in _xml(book, 'xl/_rels/workbook.xml.rels'):
                target = rel.attrib.get('Target', '')
                target = target.lstrip('/') if target.startswith('/') else 'xl/' + target
                if '..' in PurePosixPath(target).parts or '\\' in target:
                    _fail('XLSX', 0, 'Хуудасны холбоосын зам буруу байна.')
                rels[rel.attrib.get('Id')] = target
            shared = []
            if 'xl/sharedStrings.xml' in book.namelist():
                shared = [''.join(n.itertext()) for n in _xml(book, 'xl/sharedStrings.xml')]
                if len(shared) > MAX_ROWS * 8 or any(len(s) > 8192 for s in shared):
                    _fail('XLSX', 0, 'Текстийн хэмжээ зөвшөөрөгдөхгүй.')
            sheets = _xml(book, 'xl/workbook.xml').find('m:sheets', NS)
            expected = set(SHEET_MAPPING) | {'Улирлын огноо', 'Ресепшний асуулт'}
            names = [] if sheets is None else [s.attrib.get('name') for s in sheets]
            if len(names) != len(expected) or set(names) != expected:
                _fail('XLSX', 0, 'Загварын долоон хуудсыг нэрийг нь солилгүй хэрэглэнэ үү.')
            result = {}
            for sheet in sheets:
                name = sheet.attrib['name']
                target = rels.get(sheet.attrib.get(RID), '')
                if not target.startswith('xl/worksheets/'):
                    _fail(name, 0, 'Хуудасны XML холбоос буруу байна.')
                rows = {}
                for node in _xml(book, target).findall('m:sheetData/m:row', NS):
                    line = node.attrib.get('r', '')
                    if not line.isdigit() or not 1 <= int(line) <= MAX_ROWS + 3 or int(line) in rows:
                        _fail(name, 0, 'Мөрийн дугаар эсвэл тоо зөвшөөрөгдөхгүй.')
                    line, cells = int(line), {}
                    if name in SHEET_MAPPING and line in {1, 3}:
                        rows[line] = {}
                        continue
                    for cell in node.findall('m:c', NS):
                        match = re.fullmatch(r'([A-Z]{1,2})([1-9]\d*)', cell.attrib.get('r', ''))
                        if not match or int(match[2]) != line:
                            _fail(name, line, 'Нүдний хаяг буруу байна.')
                        column = 0
                        for letter in match[1]:
                            column = column * 26 + ord(letter) - 64
                        if column > 16 or column in cells:
                            _fail(name, line, 'Баганын тоо эсвэл давхардлыг шалгана уу.')
                        if cell.find('m:f', NS) is not None:
                            _fail(name, line, 'Томьёог бодсон утга болгон хуулна уу.')
                        kind = cell.attrib.get('t', 'n')
                        value = cell.findtext('m:v', '', NS)
                        if kind == 's':
                            if not value.isdigit() or int(value) >= len(shared):
                                _fail(name, line, 'Текстийн холбоос буруу байна.')
                            value = shared[int(value)]
                        elif kind == 'inlineStr':
                            inline = cell.find('m:is', NS)
                            value = '' if inline is None else ''.join(inline.itertext())
                        elif kind not in {'n', 'str', 'd'}:
                            _fail(name, line, 'Текст эсвэл энгийн тоон утга хэрэглэнэ үү.')
                        cells[column] = value
                    rows[line] = cells
                result[name] = rows
            return result, hashlib.sha256(raw).hexdigest()
    except ImportSchoolTablesError:
        raise
    except (OSError, ValueError, OverflowError, zipfile.BadZipFile, RuntimeError, NotImplementedError):
        _fail('XLSX', 0, 'Файлыг уншиж чадсангүй; эх хувийг дахин шалгана уу.')


def _table_rows(sheets):
    result = {}
    for sheet, (table, mapping) in SHEET_MAPPING.items():
        header = sheets[sheet].get(2, {})
        columns = {i: str(v).strip() for i, v in header.items() if str(v).strip()}
        if (len(columns) != len(mapping) or set(columns.values()) != set(mapping)
                or set(columns) != set(range(1, len(mapping) + 1))):
            _fail(sheet, 2, 'Загварын баганын толгой дутуу, давхардсан эсвэл өөрчлөгдсөн байна.')
        rows = []
        for line, cells in sorted(sheets[sheet].items()):
            if line <= 3 or not any(str(v).strip() for v in cells.values()):
                continue
            if any(str(v).strip() for i, v in cells.items() if i not in columns):
                _fail(sheet, line, 'Загвараас гадуур бөглөсөн багана байна.')
            row = {mapping[title]: cells.get(i, '') for i, title in columns.items()}
            optional = {'purpose', 'department', 'role', 'contact'}
            if table == 'staff':
                # Room and meeting hours are often missing from school lists.
                optional |= {'room', 'office_hours'}
            if table == 'services':
                optional |= {'office_hours'}
            for field, value in row.items():
                row[field] = (_floor(value, sheet, line) if field == 'floor'
                              else _text(value, sheet, line, optional=field in optional, contact=field == 'contact'))
            # Legacy required text must never become empty through optional parsing.
            for field in reception.SCHEMA.get(table, ()):
                if not row[field]:
                    _fail(sheet, line, 'Заавал байх талбар хоосон байна.')
            if table == 'classes':
                if not re.fullmatch(r'[1-9]|10', row['course']):
                    _fail(sheet, line, 'Курс 1…10 бүхэл тоо байна.')
            if table == 'timetable':
                row['time'] = row['time'].translate(str.maketrans({'–': '-', '—': '-', '−': '-'}))
                try:
                    reception._interval(row['time'])
                except reception.ReceptionDataError:
                    _fail(sheet, line, 'Цаг HH:MM-HH:MM байна; дуусах цаг эхлэхээс хойш байна.')
                day = reception._DAY_LOOKUP.get(reception._key(row['day']))
                if day is None:
                    _fail(sheet, line, 'Гарагийг Даваа…Ням гэж бүтнээр бичнэ үү.')
                row['day'] = reception._DAYS[day]
            rows.append((line, row))
        result[table] = (sheet, rows)
    return result


def _iso(value, line):
    try:
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            raise ValueError
        return date.fromisoformat(value)
    except ValueError:
        _fail('Улирлын огноо', line, 'Огноог YYYY-MM-DD текстээр бичнэ үү.')


def _dates(sheets, complete, fake):
    rows = sheets['Улирлын огноо']
    values = {}
    for line, label in enumerate(DATE_LABELS, 1):
        cells = rows.get(line, {})
        if cells.get(1, '').strip() != label:
            _fail('Улирлын огноо', line, 'Огнооны мөрийн шошго өөрчлөгдсөн байна.')
        if any(str(v).strip() for i, v in cells.items() if i > 2):
            _fail('Улирлын огноо', line, 'Огноог зөвхөн B баганад бөглөнө үү.')
        values[line] = str(cells.get(2, '')).strip()
    for line, cells in rows.items():
        if line > 3 and any(str(v).strip() for v in cells.values()):
            _fail('Улирлын огноо', line, 'Нэмэлт мөрийг амралтын B3 жагсаалтад оруулна уу.')
    start = _iso(values[1], 1) if values[1] else None
    end = _iso(values[2], 2) if values[2] else None
    if bool(start) != bool(end):
        _fail('Улирлын огноо', 1 if not start else 2, 'Улирлын эхлэл, төгсгөлийг хамт бөглөнө үү.')
    if start and end < start:
        _fail('Улирлын огноо', 2, 'Улирлын эхлэл, төгсгөлийг хамт, зөв дарааллаар бөглөнө үү.')
    holiday_text = values[3]
    reviewed = bool(holiday_text)
    holidays = set()
    if holiday_text and holiday_text.casefold() not in {'-', '—', '–', 'байхгүй'}:
        _text(holiday_text, 'Улирлын огноо', 3, multiline=True)
        for token in re.split(r'[,;\s]+', holiday_text):
            if not token:
                continue
            parts = token.split('..')
            if len(parts) > 2:
                _fail('Улирлын огноо', 3, 'Амралт нь ISO огноо эсвэл эхлэл..төгсгөл байна.')
            first, last = _iso(parts[0], 3), _iso(parts[-1], 3)
            if last < first or (last - first).days > 370:
                _fail('Улирлын огноо', 3, 'Амралтын хугацааны дараалал эсвэл урт буруу байна.')
            holidays.update(first + timedelta(days=i) for i in range((last - first).days + 1))
        if len(holidays) > 366:
            _fail('Улирлын огноо', 3, 'Амралтын жагсаалт 366-аас олон өдөртэй байна.')
        if not start or any(d < start or d > end for d in holidays):
            _fail('Улирлын огноо', 3, 'Амралтын өдөр улирлын хугацаанд багтах ёстой.')
    if complete and (not start or not reviewed):
        _fail('Улирлын огноо', 3, 'Бүрэн хуваарьт улирлын огноо ба амралтын баталсан жагсаалт хэрэгтэй.')
    return dict(schema_version=1, timetable_complete=complete, is_fake=fake,
                dataset_label='Сургуулийн импорт' if not fake else 'FAKE сургуулийн импорт',
                term_start=start.isoformat() if start else None,
                term_end=end.isoformat() if end else None,
                holidays=[d.isoformat() for d in sorted(holidays)], holidays_reviewed=reviewed)


def _convert(sheets):
    parsed = _table_rows(sheets)
    rooms, staff, groups = {}, {}, {}
    for table, field, index in (('rooms', 'name', rooms), ('staff', 'name', staff), ('classes', 'group', groups)):
        sheet, rows = parsed[table]
        for line, row in rows:
            key = reception._key(row[field])
            if key in index:
                _fail(sheet, line, 'Нэг түлхүүр давхардан орсон байна.')
            index[key] = row
    services_seen = set()
    for line, row in parsed['services'][1]:
        key, service = reception._key(row['room']), reception._key(row['name'])
        if service in services_seen:
            _fail(parsed['services'][0], line, 'Албаны нэр давхардсан байна.')
        services_seen.add(service)
        if key not in rooms:
            room = dict(name=row['room'], floor=row['floor'], purpose='Алба, үйлчилгээ', department='')
            rooms[key] = room
        room = rooms[key]
        if room['floor'] != row['floor']:
            _fail(parsed['services'][0], line, 'Албаны давхар өрөөний хүснэгттэй зөрж байна.')
        room.setdefault('_services', []).append({f: row[f] for f in ('name', 'office_hours', 'contact')})
        if len(room['_services']) > 16:
            _fail(parsed['services'][0], line, 'Нэг өрөөнд 16-аас олон алба байна.')
        if len(json.dumps(room['_services'], ensure_ascii=False, separators=(',', ':'))) > 8192:
            _fail(parsed['services'][0], line, 'Нэг өрөөний албаны мэдээлэл хэт урт байна.')
    for table in ('staff', 'classes', 'timetable'):
        sheet, rows = parsed[table]
        previous = []
        for line, row in rows:
            if (table != 'staff' or row['room']) and reception._key(row['room']) not in rooms:
                _fail(sheet, line, 'Өрөөний холбоос өрөө/албаны хүснэгтэд алга байна.')
            if (table in {'classes', 'timetable'} and (table == 'timetable' or row['teacher'])
                    and reception._key(row['teacher']) not in staff):
                _fail(sheet, line, 'Багшийн холбоос ажилтны хүснэгтэд алга байна.')
            if table == 'timetable':
                if reception._key(row['group']) not in groups:
                    _fail(sheet, line, 'Бүлгийн холбоос ангийн хүснэгтэд алга байна.')
                start, end = reception._interval(row['time'])
                for old in previous:
                    a, b = reception._interval(old['time'])
                    joint = row['time'] == old['time'] and reception._key(row['subject']) == reception._key(old['subject'])
                    if (row['day'] == old['day'] and start < b and a < end and not joint
                            and any(reception._key(row[f]) == reception._key(old[f]) for f in ('teacher', 'room', 'group'))):
                        _fail(sheet, line, 'Багш, бүлэг эсвэл өрөөний цаг өмнөх мөртэй давхцаж байна.')
                previous.append(row)
    converted = {table: [dict(row) for _, row in parsed[table][1]] for table in reception.SCHEMA}
    converted['rooms'] = []
    for room in rooms.values():
        row = dict(room)
        services = row.pop('_services', [])
        row['services'] = json.dumps(services, ensure_ascii=False, separators=(',', ':'))
        converted['rooms'].append(row)
    origins = {table: [(parsed[table][0], line) for line, _ in parsed[table][1]] for table in reception.SCHEMA}
    # Offices can introduce an additional explicit room; retain its original
    # sheet/line if the shared production validation detects a problem.
    originals = {reception._key(row['name']) for _, row in parsed['rooms'][1]}
    introduced = set()
    for line, service in parsed['services'][1]:
        key = reception._key(service['room'])
        if key not in originals and key not in introduced:
            origins['rooms'].append((parsed['services'][0], line))
            introduced.add(key)
    return converted, origins


def _destination(output, root):
    root = Path(root).resolve(strict=True)
    output = Path(output)
    if not output.is_absolute():
        output = root / output
    expected_parent = root / 'runtime' / 'school-tables'
    if output.parent != expected_parent or output.is_symlink() or output.exists():
        _fail('Гаралт', 0, 'Шинэ runtime/school-tables/<огноо>/ хавтас сонгоно уу; хуучныг дарж бичихгүй.')
    token = output.name
    try:
        if not re.fullmatch(r'\d{8}|\d{4}-\d{2}-\d{2}', token):
            raise ValueError
        date.fromisoformat(token)
    except ValueError:
        _fail('Гаралт', 0, 'Хавтасны огноо YYYYMMDD эсвэл YYYY-MM-DD байна.')
    for parent in (root / 'runtime', expected_parent):
        if parent.is_symlink() or not parent.resolve().is_relative_to(root):
            _fail('Гаралт', 0, 'Runtime гаралтын холбоос төслийн гадна гарч болохгүй.')
    return output


def import_school_tables(source, output, *, project_root=ROOT, timetable_complete=False, is_fake=False):
    """Validate every row before atomically publishing four CSVs and metadata."""
    if type(timetable_complete) is not bool or type(is_fake) is not bool:
        _fail('Тохиргоо', 0, 'Бүрэн/зохиомол тэмдэглэгээ boolean байна.')
    output = _destination(output, project_root)
    sheets, source_sha = _read_workbook(Path(source))
    rows, origins = _convert(sheets)
    metadata = _dates(sheets, timetable_complete, is_fake)
    try:
        reception.validate_table_rows(rows, timetable_complete=timetable_complete,
                                      is_fake=is_fake, metadata=metadata)
    except reception.ReceptionDataError as error:
        origin = origins.get(error.table, ())
        if error.row_index is not None and 0 <= error.row_index < len(origin):
            sheet, line = origin[error.row_index]
        else:
            sheet, line = 'XLSX', 0
        _fail(sheet, line, 'Мөрийн төрөл, холбоос эсвэл нийлмэл шалгалт тэнцсэнгүй.')
    metadata['source_sha256'] = source_sha
    metadata['importer_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    metadata['row_counts'] = {table: len(values) for table, values in rows.items()}
    # No partial CSV directory is visible on validation errors. Staged files are
    # checked by the exact production loader, then published as one directory.
    output.parent.mkdir(parents=True, exist_ok=True)
    lock = output.parent / ('.' + output.name + '.import.lock')
    owned_lock = False
    try:
        with lock.open('x', encoding='utf-8'):
            owned_lock = True
            if output.exists() or output.is_symlink():
                _fail('Гаралт', 0, 'Хуучин гаралт байна; шинэ огнооны хавтас сонгоно уу.')
            with tempfile.TemporaryDirectory(prefix='.school-import-', dir=output.parent) as work:
                stage = Path(work) / 'validated'
                stage.mkdir()
                for table, values in rows.items():
                    columns = reception.SCHEMA[table] + reception.OPTIONAL_SCHEMA[table]
                    with (stage / (table + '.csv')).open('w', encoding='utf-8', newline='') as stream:
                        writer = csv.DictWriter(stream, fieldnames=columns)
                        writer.writeheader()
                        writer.writerows(values)
                (stage / 'import-metadata.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
                try:
                    reception.load_tables(stage, is_fake=is_fake, timetable_complete=timetable_complete)
                except reception.ReceptionDataError:
                    _fail('XLSX', 0, 'Хүснэгтүүдийн нийлмэл шалгалт тэнцсэнгүй; импорт нийтлэгдээгүй.')
                os.rename(stage, output)
    except FileExistsError:
        _fail('Гаралт', 0, 'Энэ огнооны импорт эсвэл түгжээ байна; давхар ажиллуулахгүй.')
    finally:
        # Never remove another importer's reservation on a collision.
        if owned_lock:
            lock.unlink()
    return dict(output=str(output), counts=metadata['row_counts'], is_fake=is_fake,
                timetable_complete=timetable_complete, source_sha256=source_sha)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--date', default=date.today().isoformat())
    parser.add_argument('--output', type=Path)
    parser.add_argument('--timetable-complete', action='store_true')
    parser.add_argument('--is-fake', action='store_true')
    args = parser.parse_args(argv)
    try:
        result = import_school_tables(args.source, args.output or ROOT / 'runtime/school-tables' / args.date,
                                     timetable_complete=args.timetable_complete, is_fake=args.is_fake)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (ImportSchoolTablesError, OSError) as error:
        print(str(error) if isinstance(error, ImportSchoolTablesError) else 'Импортыг хадгалж чадсангүй.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
