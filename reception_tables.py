"""Small, validated reception tables. No database, network or model dependency.

Only an explicit opt-in config loads a local dataset. Timetable entries describe
scheduled activity, never a person's observed or confirmed physical location.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from collections import Counter
from datetime import date, datetime, timedelta
import io
import json
from pathlib import Path, PurePosixPath
import re
import unicodedata
import xml.etree.ElementTree as ET
import zipfile


CONFIG_PATH = 'config/reception-tables.json'
SCHEMA = {
    'rooms': ('floor', 'name'),
    # Real school lists often lack an office or meeting hours; those stay
    # optional and are answered as "not recorded", never guessed.
    'staff': ('name', 'department'),
    'classes': ('group', 'room'),
    'timetable': ('day', 'time', 'group', 'room', 'teacher'),
}
OPTIONAL_SCHEMA = {
    'rooms': ('purpose', 'department', 'services'),
    'staff': ('role', 'room', 'office_hours', 'email'),
    'classes': ('course', 'department', 'teacher'),
    'timetable': ('subject',),
}
MAX_SERVICES = 16
MAX_SERVICES_CELL = 8192
MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 5000
MAX_CELL = 300
_DAYS = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')
_MN_DAYS = ('даваа', 'мягмар', 'лхагва', 'пүрэв', 'баасан', 'бямба', 'ням')
_DAY_LOOKUP = {**{day: i for i, day in enumerate(_DAYS)},
               **{day: i for i, day in enumerate(_MN_DAYS)}}
_RELATIVE_DAYS = {'өнөөдөр': 'өнөөдрийн', 'маргааш': 'маргаашийн'}


def normalize_wording(text):
    """Spoken and typed wordings in one form (round 8): «хэд/хэдэн давхарт» asks «хэддүгээр
    давхарт», «лаб» is «лаборатори», «хаана суудаг» is «хаана байдаг». The question planner and
    both reception matchers read the result."""
    text = re.sub(r'(?<!\w)хэд(?:эн)?\s+давхарт', 'хэддүгээр давхарт', text, flags=re.I)
    text = re.sub(r'(?<!\w)лаб(?!\w)', 'лаборатори', text, flags=re.I)
    # «нягтлан» alone is the post «нягтлан бодогч» (round 9).
    text = re.sub(r'(?<!\w)(нягтлан)(?!\w)(?!\s+бодогч)', r'\1 бодогч', text, flags=re.I)
    return re.sub(r'(?<!\w)хаана\s+суудаг', 'хаана байдаг', text, flags=re.I)


_XML_NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
_REL_NS = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'


class ReceptionDataError(ValueError):
    """The whole dataset is rejected; no partially loaded answer is usable."""
    def __init__(self, message, *, table=None, row_index=None):
        super().__init__(message)
        self.table, self.row_index = table, row_index


def _key(value):
    return unicodedata.normalize('NFC', value).casefold().strip()


def _cell(value):
    if value is None:
        value = ''
    if not isinstance(value, str):
        value = str(value)
    value = unicodedata.normalize('NFC', value.strip())
    if not value or len(value) > MAX_CELL or any(ord(c) < 32 for c in value):
        raise ReceptionDataError('Every table cell must contain bounded single-line text.')
    if value.startswith(('=', '@')):
        raise ReceptionDataError('Formula-like values are not reception data.')
    return value


def _minutes(value):
    if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', value):
        raise ReceptionDataError('Time must be HH:MM (00:00 through 23:59).')
    hours, minutes = map(int, value.split(':'))
    return hours * 60 + minutes


def _interval(value):
    if not re.fullmatch(r'\d{2}:\d{2}-\d{2}:\d{2}', value):
        raise ReceptionDataError('Timetable time must be HH:MM-HH:MM.')
    start, end = map(_minutes, value.split('-'))
    if start >= end:
        raise ReceptionDataError('A timetable interval must end after it starts on the same day.')
    return start, end


@dataclass(frozen=True)
class Service:
    name: str
    office_hours: str
    contact: str


@dataclass(frozen=True)
class Room:
    floor: int
    name: str
    purpose: str = ''
    department: str = ''
    services: tuple[Service, ...] = ()


@dataclass(frozen=True)
class Staff:
    name: str
    department: str
    room: str = ''
    office_hours: str = ''
    role: str = ''
    # School (work) address only; the import step drops private addresses.
    email: str = ''


@dataclass(frozen=True)
class ClassGroup:
    group: str
    room: str
    course: str = ''
    department: str = ''
    teacher: str = ''


@dataclass(frozen=True)
class Lesson:
    day: str
    time: str
    group: str
    room: str
    teacher: str
    subject: str = ''

    @property
    def interval(self):
        return _interval(self.time)


@dataclass(frozen=True)
class ReceptionTables:
    rooms: tuple[Room, ...]
    staff: tuple[Staff, ...]
    classes: tuple[ClassGroup, ...]
    timetable: tuple[Lesson, ...]
    timetable_complete: bool = False
    dataset_label: str = 'Reception tables'
    is_fake: bool = False
    term_start: date | None = None
    term_end: date | None = None
    holidays: tuple[date, ...] = ()
    calendar_bound: bool = False
    holidays_reviewed: bool = False


_EMAIL = re.compile(r'[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63}){1,4}')


def _recorded(value):
    """A dash means the school confirmed nothing is recorded."""
    return bool(value) and value not in {'—', '–', '-'}


def _optional_cell(value, field):
    if value is None or not str(value).strip():
        return ''
    if field == 'services':
        value = str(value).strip()
        if len(value) > MAX_SERVICES_CELL:
            raise ReceptionDataError('Services cell is oversized.')
        return value
    return _cell(value)


def _rows(values, table):
    if not values:
        raise ReceptionDataError(f'{table}: missing header.')
    header = tuple(str(v).strip() for v in values[0])
    if (len(header) != len(set(header)) or not set(SCHEMA[table]).issubset(header)
            or not set(header).issubset(SCHEMA[table] + OPTIONAL_SCHEMA[table])):
        raise ReceptionDataError(f'{table}: columns must be {", ".join(SCHEMA[table])}.')
    result = []
    for line in values[1:]:
        if not any(v is not None and str(v).strip() for v in line):
            continue
        if len(line) != len(header):
            raise ReceptionDataError(f'{table}: row width does not match its header.')
        result.append({name: (_cell(value) if name in SCHEMA[table] else _optional_cell(value, name))
                       for name, value in zip(header, line)})
        if len(result) > MAX_ROWS:
            raise ReceptionDataError(f'{table}: too many rows.')
    return result


def _read_bytes(path):
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ReceptionDataError('Missing or oversized reception input.')
    return path.read_bytes()


def _csv_tables(directory):
    values = {}
    for table in SCHEMA:
        path = directory / (table + '.csv')
        # Do not follow a CSV symlink out of the selected dataset directory.
        if not path.resolve().is_relative_to(directory.resolve()):
            raise ReceptionDataError('CSV input escapes its dataset directory.')
        try:
            text = _read_bytes(path).decode('utf-8-sig')
            values[table] = _rows(list(csv.reader(io.StringIO(text), strict=True)), table)
        except (UnicodeError, csv.Error) as error:
            raise ReceptionDataError('CSV must be well-formed UTF-8.') from error
    return values


def _xml(archive, name):
    try:
        raw = archive.read(name)
    except KeyError as error:
        raise ReceptionDataError('XLSX is missing a required XML member.') from error
    if len(raw) > MAX_BYTES or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise ReceptionDataError('XLSX XML is oversized or contains a document/entity declaration.')
    return ET.fromstring(raw)


def _column(reference):
    match = re.fullmatch(r'([A-Z]{1,3})([1-9]\d{0,5})', reference or '')
    if not match:
        raise ReceptionDataError('XLSX cell references are required.')
    value = 0
    for letter in match[1]:
        value = value * 26 + ord(letter) - ord('A') + 1
    if value > 16 or int(match[2]) > MAX_ROWS + 1:
        raise ReceptionDataError('XLSX cell is outside the bounded table.')
    return value - 1


def _xlsx_tables(path):
    try:
        with zipfile.ZipFile(io.BytesIO(_read_bytes(path))) as archive:
            infos = archive.infolist()
            if (len(infos) > 100 or len({info.filename for info in infos}) != len(infos)
                    or sum(info.file_size for info in infos) > 8 * MAX_BYTES
                    or any(info.file_size > MAX_BYTES for info in infos)):
                raise ReceptionDataError('XLSX package exceeds its bounds or has duplicate members.')
            workbook = _xml(archive, 'xl/workbook.xml')
            relationships = _xml(archive, 'xl/_rels/workbook.xml.rels')
            rels = {}
            for rel in relationships:
                if rel.attrib.get('TargetMode') == 'External':
                    raise ReceptionDataError('External XLSX relationships are not accepted.')
                target = rel.attrib.get('Target', '')
                name = ('xl/' + target if not target.startswith('/') else target.lstrip('/'))
                if '..' in PurePosixPath(name).parts or '\\' in name:
                    raise ReceptionDataError('Invalid XLSX relationship target.')
                rels[rel.attrib.get('Id')] = name
            strings = []
            if 'xl/sharedStrings.xml' in archive.namelist():
                strings = [''.join(node.itertext()) for node in _xml(archive, 'xl/sharedStrings.xml')]
                if len(strings) > MAX_ROWS * 8 or any(len(s) > MAX_CELL for s in strings):
                    raise ReceptionDataError('XLSX shared strings exceed their bounds.')
            sheets = workbook.find('m:sheets', _XML_NS)
            if sheets is None or len(sheets) != len(SCHEMA):
                raise ReceptionDataError('XLSX must contain exactly rooms, staff, classes, timetable sheets.')
            values = {}
            for sheet in sheets:
                table = sheet.attrib.get('name')
                if table not in SCHEMA or table in values:
                    raise ReceptionDataError('XLSX has unknown or duplicate table sheets.')
                target = rels.get(sheet.attrib.get(_REL_NS))
                if not target or not target.startswith('xl/worksheets/'):
                    raise ReceptionDataError('XLSX table sheet relationship is invalid.')
                document = _xml(archive, target)
                rows = []
                for row in document.findall('m:sheetData/m:row', _XML_NS):
                    cells = {}
                    for cell in row:
                        if cell.tag != '{'+_XML_NS['m']+'}c':
                            continue
                        index = _column(cell.attrib.get('r'))
                        if index in cells or cell.find('m:f', _XML_NS) is not None:
                            raise ReceptionDataError('XLSX duplicate cells or formulas are not accepted.')
                        kind = cell.attrib.get('t', 'n')
                        value = cell.findtext('m:v', '', _XML_NS)
                        if kind == 's':
                            if not value.isdigit() or int(value) >= len(strings):
                                raise ReceptionDataError('Invalid XLSX shared string index.')
                            value = strings[int(value)]
                        elif kind == 'inlineStr':
                            inline = cell.find('m:is', _XML_NS)
                            value = '' if inline is None else ''.join(inline.itertext())
                        elif kind not in {'n', 'str'}:
                            raise ReceptionDataError('XLSX cells must be text or simple numbers.')
                        cells[index] = value
                    if cells:
                        rows.append([cells.get(i, '') for i in range(max(cells)+1)])
                    if len(rows) > MAX_ROWS + 1:
                        raise ReceptionDataError('XLSX has too many rows.')
                values[table] = _rows(rows, table)
            return values
    except (zipfile.BadZipFile, ET.ParseError, RuntimeError, OSError) as error:
        raise ReceptionDataError('Malformed or unreadable XLSX.') from error


def _date_value(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ReceptionDataError('Calendar dates must be YYYY-MM-DD.')
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ReceptionDataError('Invalid calendar date.') from error


def _metadata(value):
    if value is None:
        return False, None, None, (), False, None
    if (not isinstance(value, dict) or type(value.get('schema_version')) is not int
            or value['schema_version'] != 1 or type(value.get('timetable_complete')) is not bool
            or type(value.get('is_fake', False)) is not bool
            or type(value.get('holidays_reviewed', False)) is not bool):
        raise ReceptionDataError('Invalid import metadata schema/flags.')
    start, end = value.get('term_start'), value.get('term_end')
    if bool(start) != bool(end):
        raise ReceptionDataError('Both term dates are required together.')
    start, end = (_date_value(start), _date_value(end)) if start and end else (None, None)
    if start and start > end:
        raise ReceptionDataError('Term end precedes its start.')
    holidays = value.get('holidays', [])
    if not isinstance(holidays, list) or len(holidays) > 366:
        raise ReceptionDataError('Invalid holiday list.')
    holidays = tuple(_date_value(day) for day in holidays)
    if len(set(holidays)) != len(holidays) or any(start and not start <= day <= end for day in holidays):
        raise ReceptionDataError('Duplicate or out-of-term holiday.')
    if value['timetable_complete'] and (not start or not value.get('holidays_reviewed', False)):
        raise ReceptionDataError('A complete imported schedule requires term dates and reviewed holidays.')
    label = _cell(value['dataset_label']) if 'dataset_label' in value else None
    return value['timetable_complete'], start, end, holidays, value.get('is_fake', False), label


def validate_table_rows(rows, *, timetable_complete=False, dataset_label='Reception tables',
                        is_fake=False, metadata=None):
    """Pure all-or-nothing validation, also used by the school importer.

    ReceptionDataError.table/row_index locate a zero-based data row when known.
    """
    if type(timetable_complete) is not bool or type(is_fake) is not bool:
        raise ReceptionDataError('Dataset metadata flags must be booleans.')
    complete, term_start, term_end, holidays, metadata_fake, label = _metadata(metadata)
    if metadata is not None:
        timetable_complete = timetable_complete and complete
        is_fake = is_fake or metadata_fake
        dataset_label = label or dataset_label
    dataset_label = _cell(dataset_label)
    normalized = {}
    for table in SCHEMA:
        if table not in rows or not isinstance(rows[table], list) or len(rows[table]) > MAX_ROWS:
            raise ReceptionDataError('Missing or oversized table.', table=table)
        normalized[table] = []
        for index, row in enumerate(rows[table]):
            try:
                if (not isinstance(row, dict) or not set(SCHEMA[table]).issubset(row)
                        or not set(row).issubset(SCHEMA[table] + OPTIONAL_SCHEMA[table])):
                    raise ReceptionDataError('Invalid row fields.')
                normalized[table].append({field: (_cell(value) if field in SCHEMA[table]
                    else _optional_cell(value, field)) for field, value in row.items()})
            except ReceptionDataError as error:
                raise ReceptionDataError(str(error), table=table, row_index=index) from error
    rows = normalized
    def fail(message, table, index):
        raise ReceptionDataError(message, table=table, row_index=index)
    def unique(table, field):
        seen = set()
        for index, row in enumerate(rows[table]):
            key = _key(row[field])
            if key in seen:
                fail(f'{table}: duplicate {field}.', table, index)
            seen.add(key)
        return seen
    room_names = unique('rooms', 'name')
    staff_names = unique('staff', 'name')
    group_names = unique('classes', 'group')
    rooms, service_names = [], set()
    for index, row in enumerate(rows['rooms']):
        if not re.fullmatch(r'-?\d{1,2}', row['floor']) or not -5 <= int(row['floor']) <= 99:
            fail('Room floor must be an integer from -5 through 99.', 'rooms', index)
        room = dict(row)
        try:
            services = json.loads(room.pop('services', '') or '[]')
            if not isinstance(services, list) or len(services) > MAX_SERVICES:
                raise ReceptionDataError('Invalid services list.')
            attached = []
            for service in services:
                if not isinstance(service, dict) or set(service) != {'name', 'office_hours', 'contact'}:
                    raise ReceptionDataError('Invalid service fields.')
                service = {field: (_optional_cell(value, field) if field in {'contact', 'office_hours'}
                                   else _cell(value)) for field, value in service.items()}
                if _key(service['name']) in service_names:
                    raise ReceptionDataError('Duplicate service name.')
                service_names.add(_key(service['name']))
                attached.append(Service(**service))
            rooms.append(Room(int(room.pop('floor')), **room, services=tuple(attached)))
        except (ReceptionDataError, ValueError, TypeError) as error:
            fail('Invalid room services: ' + str(error), 'rooms', index)
    for index, row in enumerate(rows['staff']):
        if row.get('email') and not _EMAIL.fullmatch(row['email']):
            fail('Staff email is not a plain address.', 'staff', index)
    for table in ('staff', 'classes', 'timetable'):
        for index, row in enumerate(rows[table]):
            if table == 'staff' and not row.get('room'):
                continue
            if _key(row['room']) not in room_names:
                fail(f'{table}: unknown room.', table, index)
    for index, row in enumerate(rows['classes']):
        if row.get('course') and (not re.fullmatch(r'[1-9]|10', row['course'])):
            fail('Class course must be 1 through 10.', 'classes', index)
        if row.get('teacher') and _key(row['teacher']) not in staff_names:
            fail('Class teacher is not in staff.', 'classes', index)
    lessons = []
    for index, row in enumerate(rows['timetable']):
        day = _DAY_LOOKUP.get(_key(row['day']))
        if day is None:
            fail('Timetable day must be mon..sun or a Mongolian weekday.', 'timetable', index)
        if _key(row['teacher']) not in staff_names or _key(row['group']) not in group_names:
            fail('Timetable teacher/group is not in staff/classes.', 'timetable', index)
        try:
            start, end = _interval(row['time'])
        except ReceptionDataError as error:
            fail(str(error), 'timetable', index)
        for previous in lessons:
            old_start, old_end = previous.interval
            # One joint session (same slot and subject: English by level, a
            # shared gym class) may span several groups, teachers and rooms.
            joint = previous.time == row['time'] and _key(previous.subject) == _key(row.get('subject', ''))
            if (previous.day == _DAYS[day] and start < old_end and old_start < end and not joint
                    and any(_key(getattr(previous, field)) == _key(row[field])
                            for field in ('teacher', 'group', 'room'))):
                fail('Timetable contains an overlapping teacher, group or room.', 'timetable', index)
        lessons.append(Lesson(**dict(row, day=_DAYS[day])))
    return ReceptionTables(tuple(rooms), tuple(Staff(**row) for row in rows['staff']),
        tuple(ClassGroup(**row) for row in rows['classes']), tuple(lessons),
        timetable_complete, dataset_label, is_fake, term_start, term_end, holidays, metadata is not None,
        bool(metadata and metadata.get('holidays_reviewed', False)))


def load_tables(path, *, timetable_complete=None, dataset_label='Reception tables', is_fake=False):
    """Load four CSVs or legacy XLSX, validating optional import calendar metadata."""
    path, metadata = Path(path), None
    try:
        if path.is_dir():
            rows = _csv_tables(path)
            meta_path = path / 'import-metadata.json'
            if meta_path.exists():
                if not meta_path.resolve().is_relative_to(path.resolve()):
                    raise ReceptionDataError('Import metadata escapes its dataset directory.')
                metadata = json.loads(_read_bytes(meta_path).decode('utf-8-sig'))
        elif path.suffix.casefold() == '.xlsx':
            rows = _xlsx_tables(path)
        else:
            raise ReceptionDataError('Select a CSV directory or an .xlsx workbook.')
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ReceptionDataError('Reception input could not be read.') from error
    if timetable_complete is None:
        timetable_complete = metadata.get('timetable_complete', False) if isinstance(metadata, dict) else False
    return validate_table_rows(rows, timetable_complete=timetable_complete,
        dataset_label=dataset_label, is_fake=is_fake, metadata=metadata)


class ReceptionAnswerPath:
    """Exact-name, closed-intent reception lookup. Disabled unless configured."""
    def __init__(self, tables=None, *, enabled=False, error=None):
        self.tables, self.enabled, self.error = tables, enabled is True, error

    @classmethod
    def from_config(cls, root):
        root = Path(root).resolve()
        opted_in = False
        try:
            config = root / CONFIG_PATH
            if not config.exists():
                return cls()
            value = json.loads(_read_bytes(config).decode('utf-8-sig'))
            if value.get('enabled') is not True:
                return cls()
            opted_in = True
            if type(value.get('schema_version')) is not int or value['schema_version'] != 1 or value.get('reviewed') is not True:
                raise ReceptionDataError('Enabled reception data must be explicitly reviewed.')
            source = value.get('source')
            if not isinstance(source, str) or not source or Path(source).is_absolute():
                raise ReceptionDataError('Reception source must be an explicit relative path.')
            parts = PurePosixPath(source.replace('\\', '/')).parts
            if (any(part.casefold() in {'runtime', 'models', 'audio', 'secrets', '.git', '..'} for part in parts)
                    or Path(source).suffix.casefold() in {'.db', '.sqlite', '.sqlite3', '.dpapi'}):
                raise ReceptionDataError('Private data paths cannot be reception sources.')
            allowed = parts[:2] == ('data', 'reception') or (value.get('is_fake') is True
                and parts[:3] == ('tests', 'fixtures', 'reception_fake'))
            if not allowed:
                raise ReceptionDataError('Source must be data/reception, or explicitly FAKE test fixtures.')
            path = (root / source).resolve()
            if not path.is_relative_to(root):
                raise ReceptionDataError('Reception source must stay within the project.')
            resolved_parts = tuple(part.casefold() for part in path.relative_to(root).parts)
            resolved_allowed = (resolved_parts[:2] == ('data', 'reception') or
                value.get('is_fake') is True and resolved_parts[:3] == ('tests', 'fixtures', 'reception_fake'))
            if not resolved_allowed:
                raise ReceptionDataError('Resolved reception source escapes its approved data prefix.')
            if (any(part in {'runtime', 'models', 'audio', 'secrets', '.git'} for part in resolved_parts)
                    or path.suffix.casefold() in {'.db', '.sqlite', '.sqlite3', '.dpapi'}):
                raise ReceptionDataError('Resolved reception source is a private data path.')
            return cls(load_tables(path, timetable_complete=value.get('timetable_complete', False),
                dataset_label=value.get('dataset_label', 'Reception tables'),
                is_fake=value.get('is_fake', False)), enabled=True)
        except FileNotFoundError:
            return cls()
        except (OSError, ValueError, TypeError, AttributeError):
            # An opted-in malformed dataset must not silently fall back to a
            # website answer for a reception query.
            return cls(enabled=opted_in, error='reception_data_unavailable' if opted_in else None)

    def _result(self, query, answer, reason, **metadata):
        messages = {
            'reception_data_unavailable': 'Ресепшний хянасан хүснэгт бэлэн биш байна.',
            'reception_room_not_found': 'Нэрлэсэн өрөөг ресепшний хүснэгтээс баталсангүй. Өрөөний бүтэн нэрийг шалгана уу.',
            'reception_teacher_not_found': 'Нэрлэсэн багш хүснэгтэд олдсонгүй. Бүтэн нэрийг тодруулна уу.',
            'reception_time_required': 'Хуваарьт төлөвийг шалгах өдөр, цагийг нэмнэ үү (жишээ: даваа 09:30). Бодит байршлыг батлахгүй.',
            'reception_invalid_time': 'Цагийг 00:00–23:59 хэлбэрээр бичнэ үү.',
            'reception_timetable_incomplete': 'Энэ цагт хичээл бүртгэгдээгүй боловч хуваарь бүрэн гэж батлагдаагүй. Чөлөөтэй эсвэл байршлыг батлахгүй.',
            'reception_date_required': 'Улирлын хуваарийг шалгах бодит огноо шаардлагатай. Байршлыг батлахгүй.',
            'reception_calendar_unknown': 'Улирлын огноо эсвэл амралтын мэдээлэл дутуу. Хуваарьт төлөвийг батлахгүй.',
            'reception_outside_term': 'Энэ огноо импортолсон улиралд багтахгүй. Хичээлтэй эсэхийг батлахгүй.',
            'reception_holiday': 'Энэ огноо бүртгэлтэй амралтын өдөр. Долоо хоногийн хуваарийг хэрэглэхгүй.',
            'reception_lookup_missing': 'Шаардсан талбар хүснэгтэд батлагдаагүй байна.',
            'reception_contact_unknown': 'Энэ албаны нийтэд өгөх холбоо хүснэгтэд батлагдаагүй байна.',
            'reception_hours_unknown': 'Ажлын эсвэл уулзах цаг хүснэгтэд бүртгэгдээгүй байна.',
            'reception_email_unknown': 'Энэ багш, ажилтны сургуулийн имэйл хүснэгтэд бүртгэгдээгүй байна.',
            'reception_room_unknown': 'Энэ хүний ажлын өрөө хүснэгтэд бүртгэгдээгүй байна.',
            'reception_group_required': 'Аль анги, бүлгийн багшийг асууж байгааг тодруулна уу.',
        }
        return dict(query=query, answer=answer, reason_code=reason, message=messages.get(reason, ''),
            reception=dict(dataset_label=self.tables.dataset_label if self.tables else None,
                is_fake=self.tables.is_fake if self.tables else False,
                physical_location_confirmed=False, **metadata))

    @staticmethod
    def _match(query):
        if not isinstance(query, str) or not 0 < len(query) <= 1000:
            return None, None
        # Only this closed wording is handled. Unknown modifiers, multiple
        # questions and ambiguous partial names remain for the normal router.
        cleaned = normalize_wording(query.strip().rstrip('?!？.').strip())
        room = (re.fullmatch(r'(.{1,120}?)\s+өрөө\s+хаана(?:\s+байдаг)?\s*(?:вэ)?', cleaned, re.I)
                or re.fullmatch(r'өрөө\s+(.{1,120}?)\s+хаана(?:\s+байдаг)?\s*(?:вэ)?', cleaned, re.I)
                or re.fullmatch(r'where\s+is\s+room\s+(.{1,120})', cleaned, re.I))
        teacher = (re.fullmatch(r'(.{1,120}?)\s+багш\s+хаана(?:\s+(?:байна|байдаг))?\s*(?:вэ)?'
                    r'(?:\s*[,;]?\s*(даваа|мягмар|лхагва|пүрэв|баасан|бямба|ням|mon|tue|wed|thu|fri|sat|sun)'
                    r'\s+(\d{2}:\d{2}))?', cleaned, re.I)
                   or re.fullmatch(r'where\s+is\s+teacher\s+(.{1,120}?)(?:\s+on\s+'
                    r'(mon|tue|wed|thu|fri|sat|sun)\s+(\d{2}:\d{2}))?', cleaned, re.I))
        for match in (room, teacher):
            if match and re.search(r'\b(?:болон|ба|мөн|эсвэл|and|or)\b|[,;?!/]', match[1], re.I):
                return None, None
        return room, teacher

    @staticmethod
    def _extra_match(query):
        if not isinstance(query, str) or not 0 < len(query) <= 1000:
            return None
        text = query.strip().rstrip('?!？.').strip()
        patterns = (
            ('office_full', r'(.{1,120}?) хаана байдаг вэ\?\s*Хэдэн цагт ажилладаг вэ'),
            ('room_floor', r'([^\s?!,;/]{1,120}) тоот хэддүгээр давхарт (?:байдаг |байна )?вэ'),
            ('office_floor', r'(.{1,120}?) хэддүгээр давхарт (?:байдаг |байна )?вэ'),
            ('office_hours', r'(.{1,120}?) хэдэн цагт ажилладаг вэ'),
            ('office_contact', r'(.{1,120}?)тай яаж холбогдох вэ'),
            ('department', r'(.{1,120}?) тэнхим хаана вэ'),
            # 11/17 (4): a phone question about a recorded teacher or class teacher. Staff phones
            # are never shown; as at the reception desk, the school e-mail is offered instead.
            # Round 4 (11/17): «Барилгын тэнхимийн утас хэд вэ?» showed another department's contact
            # block (with a mobile). The website's department contact is its head: the school e-mail
            # and room from the staff table, never a phone.
            ('department_phone', r'(.{1,80}?) тэнхимийн (?:эрхлэгчийн )?(?:холбоо барих )?утас(?:ны дугаар)?'
                                 r'(?: (?:юу|хэд|ямар) (?:вэ|бэ))?'),
            ('department_email', r'(.{1,80}?) тэнхимийн (?:эрхлэгчийн )?(?:и-?мэйл|имэйл|мэйл|цахим шуудан)(?: хаяг)?'
                                 r'(?: (?:юу|хэд|ямар) (?:вэ|бэ))?'),
            ('department_contact', r'(.{1,80}?) тэнхим(?:тэй|ийн эрхлэгчтэй) (?:яаж|хэрхэн) холбогдох (?:вэ|бэ)'),
            ('class_teacher_phone', r'(.{1,120}?) ангийн багшийн утас(?:ны дугаар)?(?: (?:юу|хэд|ямар) (?:вэ|бэ))?'),
            ('teacher_phone', r'(.{1,120}?) багшийн утас(?:ны дугаар)?(?: (?:юу|хэд|ямар) (?:вэ|бэ))?'),
            # 11/17: a class teacher's school e-mail; before teacher_email, which would read
            # «КУ-2 ангийн» as a person's name.
            ('class_teacher_email', r'(.{1,120}?) ангийн багшийн (?:и-?мэйл|имэйл|мэйл|цахим шуудан)(?:ийн)?(?: хаяг)?'
                                    r'(?: (?:юу|хэд|ямар) (?:вэ|бэ))?'),
            # Round 9: the class teacher's recorded office; before teacher_room and the legacy
            # teacher lookup, which read «КУ-2 ангийн» as a person's name («багш олдсонгүй»).
            ('class_teacher_room', r'(.{1,120}?) ангийн багш(?:ийн (?:ажлын )?өрөө)? хаана (?:байдаг |байна )?вэ'),
            ('class_day', r'(.{1,120}?) анги(?:йн)? (?:(даваа|мягмар|лхагва|пүрэв|баасан|бямба|ням) гарагт|'
                          r'(өнөөдөр|маргааш)) хэдэн цагт хичээлтэй вэ'),
            ('term_dates', r'(?:энэ )?(?:улирал|улирлын хичээл|хичээлийн улирал) хэзээ (дуус\w*|эхл\w*|эхэл\w*)(?: вэ)?'),
            # 11/17 (5): the school day's lesson times, read from the whole timetable.
            ('bell_schedule', r'хичээл(?:үүд)? хэдэн цаг(?:т|аас) (эхэл\w*|эхл\w*|дуус\w*|тар\w*)(?: вэ)?'),
            # Round 9: «Хичээлийн хуваарь хаанаас харах вэ?» — the class timetable is shown here, by class.
            ('timetable_where', r'(?:хичээлийн |ангийн )?хуваар\w* (?:хаанаас|хаана) (харах|үзэх|олох|харж болох)(?: вэ)?'),
            ('teacher_email', r'(.{1,120}?) багшийн (?:и-?мэйл|имэйл|мэйл|цахим шуудан)(?:ийн)?(?: хаяг)?(?: (?:юу|хэд|ямар) (?:вэ|бэ))?'),
            ('teacher_room', r'(.{1,120}?) багшийн өрөө хаана вэ'),
            ('teacher_hours', r'(.{1,120}?) багш хэзээ оюутантай уулздаг вэ'),
            # 11/17 (5): a named day («маргааш», «даваа гарагт»); the published timetable only.
            ('teacher_day', r'(.{1,120}?) багш (өнөөдөр|маргааш|даваа|мягмар|лхагва|пүрэв|баасан|бямба|ням)'
                            r'(?: гарагт)? хичээлтэй юу'),
            ('teacher_now', r'(.{1,120}?) багш одоо хичээлтэй юу'),
            ('class_room', r'(.{1,120}?) анги хаана хичээллэдэг вэ'),
            ('course_today', r'([1-9]|10)-р курс өнөөдөр хэдэн цагт хичээлтэй вэ'),
            ('class_teacher', r'(.{1,120}?) ангийн багш хэн бэ'),
            # Round 4 (11/17): «Сургуулийн захирал хэн бэ?», «Механик тэнхимийн эрхлэгч хэн бэ?»,
            # «Захиралтай уулзаж болох уу?» — a post recorded in the staff table. Claimed only when
            # the post names its holder(s) (_role_holders); otherwise the website path answers.
            ('role_holder', r'(.{1,120}?) (?:нь )?хэн (?:бэ|вэ)'),
            ('role_name', r'(.{1,120}?) нэр (?:нь )?(?:юу|хэн) (?:вэ|бэ)'),
            ('role_meet', r'(.{1,120}?)(?:тай|тэй|той) (?:одоо )?уулз(?:аж|ах) (?:болох|болно) уу'),
            # Plain "X хаана вэ?" is claimed only when X is a recorded office or group.
            ('place_where', r'(.{1,120}?) хаана (?:байдаг|байна|байрладаг)? ?вэ'),
            # Round 8: «Эмч байдаг уу?» — a recorded service or room purpose exists (claimed only
            # then). Not «байгаа/байна уу?»: that asks whether someone is there now, never confirmed.
            ('place_exists', r'(.{1,60}?) (?:байдаг|бий) (?:уу|юу|үү)'),
        )
        # Round 8: spoken and typed wordings; a question typed without its particle is also tried
        # with «вэ» and «бэ» («бэ» first after «хэн», so «КУ-2 ангийн багш хэн» is the class teacher).
        text = normalize_wording(text)
        candidates = [text]
        if not re.search(r'(?<!\w)(?:вэ|бэ|уу|үү|юу)$', text, re.I):
            candidates += ([text + ' бэ', text + ' вэ'] if re.search(r'(?<!\w)хэн$', text, re.I)
                           else [text + ' вэ', text + ' бэ'])
        if any(candidate.casefold() == 'ангийн багш хэн бэ' for candidate in candidates):
            return 'group_required', ''
        # «Хүүхдийнхээ ангийн багштай уулзмаар байна» (round 9): the class teacher without a class;
        # the class is asked for, not a department.
        if re.fullmatch(r'(?:(?:миний|манай)\s+)?(?:хүүхд\w*\s+)?ангийн\s+багш(?:тай|ийг)\s+'
                        r'(?:уулз|холбогд|ол)\w*(?:\s+\w+){0,2}', text.casefold()):
            return 'group_required', ''
        for candidate in candidates:
            for intent, pattern in patterns:
                match = re.fullmatch(pattern, candidate, re.I)
                if match:
                    if re.search(r'\b(?:болон|ба|мөн|эсвэл|and|or)\b|[,;?!/]', match[1], re.I):
                        return None
                    # A day question carries its group or teacher and its day.
                    if intent in ('class_day', 'teacher_day'):
                        return intent, (match[1], next(group for group in match.groups()[1:] if group))
                    return intent, match[1]
        return None

    def recognizes(self, query):
        if not self.enabled:
            return False
        extra = self._extra_match(query)
        if extra is not None and extra[0] == 'place_exists':
            return self._service(extra[1]) is not None or bool(self._purpose_rooms(extra[1]))
        if extra is not None and extra[0] == 'place_where':
            return (any(self._match(query)) or self._place(extra[1]) is not None
                    or bool(self._purpose_rooms(extra[1])) or self._post_holder(extra[1]) is not None)
        if extra is not None and extra[0].startswith('department_'):
            return any(self._match(query)) or len(self._role_holders(extra[1] + ' тэнхимийн эрхлэгч', True)) == 1
        if extra is not None and extra[0] in ('role_holder', 'role_name', 'role_meet'):
            holders = self._role_holders(extra[1], extra[0] == 'role_meet')
            return any(self._match(query)) or (len(holders) == 1 if extra[0] == 'role_meet' else bool(holders))
        if extra is not None and extra[0] == 'timetable_where':
            return bool(self.tables and self.tables.timetable)
        if extra is not None and extra[0] in ('teacher_phone', 'class_teacher_phone'):
            # An unrecorded name stays with the staff path, which says phones are not shown.
            return any(self._match(query)) or self._phone_owner(*extra) is not None
        return any(self._match(query)) or extra is not None

    def _room_of(self, person):
        """The recorded room row of a staff member, or None."""
        if person is None or not person.room:
            return None
        return next((room for room in self.tables.rooms if _key(room.name) == _key(person.room)), None)

    def _workplace(self, person):
        """« Ажлын өрөө: 508, 5-р давхар.» from the rooms table, or nothing."""
        room = self._room_of(person)
        return (' Ажлын өрөө: ' + room.name + ', ' + str(room.floor) + '-р давхар.') if room else ''

    def _post_room(self, person):
        """«Захирал (Т.Оюунжаргал): 508 өрөө, 5-р давхар.» for a post holder with a recorded room."""
        room = self._room_of(person)
        return (person.role + ' (' + person.name + '): ' + room.name + ' өрөө, ' + str(room.floor)
                + '-р давхар. Одоо тэнд байгааг батлахгүй.')

    def _class_teacher_of(self, value):
        """(class, its teacher's staff row or None, reason or None). «Хүүхдийн ангийн багш …» names no
        class code and asks which class (review, round 9)."""
        if not re.search(r'[А-ЯӨҮЁа-яөүё]{2}-\d', value):
            return None, None, 'reception_group_required'
        group = next((group for group in self.tables.classes if _key(group.group) == _key(value)), None)
        if group is None or not group.teacher:
            return None, None, 'reception_lookup_missing'
        return group, next((person for person in self.tables.staff if _key(person.name) == _key(group.teacher)), None), None

    def _post_holder(self, value):
        """The one person holding the asked post, with a recorded room, when the asked head noun is
        the post's own («захирлын» / «Захирал»), not a facility a post mentions («… лабораторийн
        эрхлэгч»), review round 5; else None."""
        holders = self._role_holders(value)
        person = holders[0] if len(holders) == 1 else None
        asked = re.findall(r'[а-яөүё]+', _key(value))[-1:]
        post = re.findall(r'[а-яөүё]+', _key(person.role))[-1:] if person else []
        if not (asked and post and asked[0][:4] == post[0][:4]):
            return None
        return person if self._room_of(person) is not None else None

    def _role_holders(self, value, departments=False):
        """Staff whose recorded post, read with its office or department, holds every word of the
        asked post: «захирал» -> the director, «Механик тэнхимийн эрхлэгч» -> that head, a bare
        «тэнхимийн эрхлэгч» -> every head. A personal name, a post nobody holds, or a word as
        common as «багш» (more than eight people) gives [] and the website path answers."""
        if self.tables is None:
            return []
        words = [word for word in re.findall(r'[а-яөүё]+', _key(value)) if not word.startswith('сургуул')]
        # «багш», «ажилтан» name no post. Who heads a department is on its website page, which the
        # teacher directory answers with its source (W04-A11), so ``departments`` is only for the
        # contact and meeting wordings the website does not answer (round 4 review).
        generic = any(word.startswith(('багш', 'ажилт')) for word in words)
        if (not words or len(words) > 6 or generic
                or (not departments and any(word.startswith('тэнхим') for word in words))):
            return []
        exact = [person for person in self.tables.staff if _key(person.role) == ' '.join(words)]
        if exact:
            return exact if len(exact) == 1 else []
        found = []
        for person in self.tables.staff:
            if not person.role.strip():
                continue      # no recorded post: never a post holder
            own = re.findall(r'[а-яөүё]+', _key(person.role + ' ' + person.department))
            if all(any(other == word or (len(word) >= 4 and other.startswith(word[:4])) for other in own)
                   for word in words):
                found.append(person)
        # «захирлын нэр» names the director, not also «Захирлын туслах»: a post whose every word was
        # asked wins over posts with words of their own.
        whole = [person for person in found if all(
            any(word == other or (len(word) >= 4 and other.startswith(word[:4])) for word in words)
            for other in re.findall(r'[а-яөүё]+', _key(person.role)))]
        found = whole or found
        return found if len(found) <= 8 else []

    def _phone_owner(self, intent, value):
        """(person, class group or None) for a phone question about a recorded teacher."""
        if self.tables is None:
            return None
        group = None
        name = value
        if intent == 'class_teacher_phone':
            group = next((group for group in self.tables.classes if _key(group.group) == _key(value)), None)
            if group is None or not group.teacher:
                return None
            name = group.teacher
        person = next((person for person in self.tables.staff if _key(person.name) == _key(name)), None)
        return (person, group) if person is not None else None

    def _service(self, value):
        """(room, service) by exact name, or by a unique shorter name such as
        «Карьер хөгжлийн төв» for «Гадаад харилцаа, карьер хөгжлийн төв»."""
        if self.tables is None:
            return None
        name = _key(value)
        pairs = [(room, service) for room in self.tables.rooms for service in room.services]
        exact = [pair for pair in pairs if _key(pair[1].name) == name]
        if len(exact) == 1:
            return exact[0]
        partial = [pair for pair in pairs if len(name) >= 6 and name in _key(pair[1].name)]
        return partial[0] if len(partial) == 1 else None

    def _purpose_rooms(self, value):
        """Rooms whose recorded purpose ends with the asked place word for word, at most three:
        «Хурлын заал» -> 809, «Лекцийн танхим» -> «Бага лекцийн танхим» 602. A purpose as common as
        «Анги», a room code («809 өрөө») or a near spelling («Цахим» / «Цахилгааны») names none."""
        if self.tables is None or re.search(r'\d', value):
            return []
        words = re.findall(r'[а-яөүё]+', _key(value))
        found = [room for room in self.tables.rooms
                 if words and re.findall(r'[а-яөүё]+', _key(room.purpose or ''))[-len(words):] == words]
        return found if 1 <= len(found) <= 3 else []

    def _purpose_reply(self, rooms):
        # Rooms grouped under their own recorded purpose («Гадаад хэлний кабинет», «Хэлний кабинет»).
        groups = {}
        for room in rooms:
            groups.setdefault(room.purpose, []).append(room.name + ' өрөө, ' + str(room.floor) + '-р давхар')
        return '; '.join(purpose + ': ' + '; '.join(places) for purpose, places in groups.items()) + '.'

    def _place(self, value):
        """A recorded office or class group named in a plain location question."""
        if self.tables is None:
            return None
        name = _key(re.sub(r'\s+анги(?:йн)?$', '', value.strip(), flags=re.I))
        found = self._service(value)
        if found is not None:
            return 'office', found[0], found[1]
        group = next((group for group in self.tables.classes if _key(group.group) == name), None)
        return ('class', group, None) if group is not None else None

    def _calendar_reason(self, now, day=None):
        """Why the timetable does not apply on ``day`` (default: today), or None."""
        if not self.tables.calendar_bound:
            return None
        if not isinstance(now, datetime):
            return 'reception_date_required'
        day = now.date() if day is None else day
        if (self.tables.term_start is None or self.tables.term_end is None
                or not self.tables.holidays_reviewed):
            return 'reception_calendar_unknown'
        if not self.tables.term_start <= day <= self.tables.term_end:
            return 'reception_outside_term'
        if day in self.tables.holidays:
            return 'reception_holiday'
        return None

    def _relative_day(self, word, now):
        """«өнөөдөр»/«маргааш» -> (that date or None, the calendar reason or None)."""
        if not isinstance(now, datetime):
            return None, 'reception_date_required'
        day = now.date() + timedelta(days=1 if _key(word) == 'маргааш' else 0)
        return day, self._calendar_reason(now, day)

    def answer(self, query, *, now=None):
        if not self.enabled:
            return None
        extra = self._extra_match(query)
        if extra is None:
            return self._answer_legacy(query, now=now)
        if self.error or self.tables is None:
            return self._result(query, None, 'reception_data_unavailable')
        intent, value = extra
        prefix = '[FAKE / ЗОХИОМОЛ ЖИШЭЭ] ' if self.tables.is_fake else ''
        def missing(reason='reception_lookup_missing'):
            return self._result(query, None, reason)
        def reply(text, table, reason):
            return self._result(query, prefix + text, reason, source_table=table)
        if intent == 'group_required':
            return missing('reception_group_required')
        if intent in ('teacher_phone', 'class_teacher_phone'):
            owner = self._phone_owner(intent, value)
            if owner is None:
                return self._answer_legacy(query, now=now)
            person, group = owner
            text = 'Багшийн утасны дугаарыг энд харуулахгүй; ресепшнээс асууна уу.'
            if person.email:
                where = self._workplace(person)
                who = (group.group + ' — бүртгэлд заасан ангийн багш: ' + group.teacher + '; сургуулийн имэйл: '
                       if group is not None else person.name + ' — сургуулийн имэйл: ')
                text += ' ' + who + person.email + '.' + where
            return reply(text, 'classes' if group is not None else 'staff',
                         'reception_class_teacher_phone' if group is not None else 'reception_teacher_phone')
        if intent.startswith('department_'):
            heads = self._role_holders(value + ' тэнхимийн эрхлэгч', True)
            if len(heads) != 1:
                return self._answer_legacy(query, now=now)
            head = heads[0]
            text = ('Тэнхимийн утасны дугаарыг энд харуулахгүй. ' if intent == 'department_phone' else '')
            text += 'Тэнхимийн эрхлэгч ' + head.name + ' (' + head.department + ').' + self._workplace(head)
            text += (' Сургуулийн имэйл: ' + head.email + '.') if head.email else ''
            return reply(text, 'staff', 'reception_' + intent)
        if intent in ('role_holder', 'role_name', 'role_meet'):
            people = self._role_holders(value, intent == 'role_meet')
            if not people or (intent == 'role_meet' and len(people) != 1):
                return self._answer_legacy(query, now=now)
            if len(people) > 1:
                return reply('Бүртгэлд: ' + '; '.join(person.name + ' — ' + person.role for person in people) + '.',
                             'staff', 'reception_role_list')
            person = people[0]
            text = person.name + ' — ' + person.role + '.' + self._workplace(person)
            if intent == 'role_meet':
                # Meeting hours and presence are not recorded: never confirm them.
                text += ' Уулзах цаг хүснэгтэд бүртгэгдээгүй тул өрөөндөө байгааг батлахгүй.'
                if person.email:
                    text += ' Уулзах цагаа сургуулийн имэйлээр тохирно уу: ' + person.email + '.'
            elif person.email:
                text += ' Сургуулийн имэйл: ' + person.email + '.'
            return reply(text, 'staff', 'reception_role_meet' if intent == 'role_meet' else 'reception_role_holder')
        if intent == 'teacher_day':
            # «Б.Сэлмаа багш маргааш хичээлтэй юу?»: lessons in the published timetable that day
            # only (busy/free and times); presence in the office is never confirmed.
            name, day = value
            person = next((person for person in self.tables.staff if _key(person.name) == _key(name)), None)
            if person is None:
                return missing('reception_teacher_not_found')
            if _key(day) in _RELATIVE_DAYS:
                target, reason = self._relative_day(day, now)
                if target is None:
                    return missing(reason)
                weekday = target.weekday()
                when = _key(day) + ' (' + _MN_DAYS[weekday] + ')'
                if reason == 'reception_holiday':
                    return reply(person.name + ' — ' + when + ' нь бүртгэсэн амралтын өдөр; хуваарьт хичээл байхгүй.',
                                 'timetable', 'reception_holiday')
                if reason:
                    return missing(reason)
            else:
                weekday = _DAY_LOOKUP[_key(day)]
                when = _MN_DAYS[weekday] + ' гарагт'
            lessons = sorted((lesson for lesson in self.tables.timetable if _key(lesson.teacher) == _key(person.name)
                              and lesson.day == _DAYS[weekday]), key=lambda lesson: lesson.interval[0])
            if not lessons and not self.tables.timetable_complete:
                return missing('reception_timetable_incomplete')
            # A joint lesson is stored once per group; list each time once.
            times = list(dict.fromkeys(lesson.time for lesson in lessons))
            status = ('хуваариар хичээлтэй: ' + ', '.join(times)) if times else 'хуваарьт хичээл бүртгэгдээгүй (сул)'
            return reply(person.name + ' — ' + when + ' ' + status
                         + '. Хуваарь өөрчлөгдсөн байж болно; өрөөндөө байгааг батлахгүй.', 'timetable', 'reception_teacher_day')
        if intent == 'place_exists':
            found = self._service(value)
            if found is not None:
                room, service = found
                return reply('Тийм. ' + service.name + ': ' + room.name + ' өрөө, ' + str(room.floor) + '-р давхар.',
                             'rooms', 'reception_service_exists')
            rooms = self._purpose_rooms(value)
            if rooms:
                return reply('Тийм. ' + self._purpose_reply(rooms), 'rooms', 'reception_purpose_exists')
            return None  # not a recorded service or room: the main path answers
        if intent == 'place_where':
            place = self._place(value)
            if place is None:
                rooms = self._purpose_rooms(value)
                if rooms:
                    # «Хурлын заал хаана вэ?»: a room the school's table names by its purpose (round 6).
                    return reply(self._purpose_reply(rooms), 'rooms', 'reception_purpose_lookup')
                # «Нягтлан бодогч хаана байдаг вэ?» (round 9): a post one person holds, its holder's room.
                person = self._post_holder(value)
                if person is not None:
                    return reply(self._post_room(person), 'staff', 'reception_role_room')
                # Not a recorded office/group: a room/teacher lookup or the main RAG path.
                return self._answer_legacy(query, now=now)
            kind, first, second = place
            if kind == 'office':
                return reply(second.name + ': ' + first.name + ' өрөө, ' + str(first.floor) + '-р давхар.',
                             'rooms', 'reception_service_lookup')
            return reply(first.group + ' — бүртгэсэн үндсэн өрөө: ' + first.room
                         + '. Тухайн хичээлийн өрөө хуваариар өөр байж болно.', 'classes', 'reception_class_room')
        if intent.startswith('office_'):
            found = self._service(value)
            rooms = self._purpose_rooms(value) if found is None and intent == 'office_floor' else []
            if rooms:
                return reply(self._purpose_reply(rooms), 'rooms', 'reception_purpose_lookup')
            if found is None:
                code = re.fullmatch(r'(.{1,40}?)\s+өрөө', value.strip())
                if intent == 'office_floor' and code:
                    return self._answer_legacy(code[1] + ' өрөө хаана вэ?', now=now) | {'query': query}
                return None  # not a recorded office ("Сургууль хэдэн цагт…"): main RAG path
            room, service = found
            if intent == 'office_floor':
                text = service.name + ': ' + str(room.floor) + '-р давхар.'
            elif intent == 'office_full':
                text = (service.name + ': ' + room.name + ' өрөө, ' + str(room.floor) + '-р давхар. '
                        + ('Ажлын цаг: ' + service.office_hours + '.' if _recorded(service.office_hours)
                           else 'Ажлын цаг хүснэгтэд бүртгэгдээгүй.'))
            elif intent == 'office_hours':
                if not _recorded(service.office_hours):
                    return missing('reception_hours_unknown')
                text = service.name + ' — ажлын цаг: ' + service.office_hours + '.'
            else:
                if not service.contact or service.contact in {'—', '-'}:
                    return missing('reception_contact_unknown')
                text = service.name + ' — албаны холбоо: ' + service.contact + '.'
            return reply(text, 'rooms', 'reception_service_lookup')
        if intent == 'room_floor':
            return self._answer_legacy(value + ' өрөө хаана вэ?', now=now) | {'query': query}
        if intent == 'department':
            # These are affiliated rooms, not proof of a unique department office.
            def unit(text):
                return _key(re.sub(r'\s*тэнхим\w*$', '', text.strip(), flags=re.I))
            matches = [room for room in self.tables.rooms if room.department and
                       unit(value) in {unit(room.department), unit(room.department) + 'ы'}]
            if not matches:
                return missing()
            return reply('Тэнхимд хамаарах бүртгэлтэй өрөө: ' + '; '.join(
                room.name + ' (' + str(room.floor) + '-р давхар; ' + (room.purpose or 'зориулалт дутуу') + ')'
                for room in matches) + '. Тэнхимийн ганц төв байр гэж батлахгүй.', 'rooms', 'reception_department_rooms')
        if intent.startswith('teacher_'):
            person = next((person for person in self.tables.staff if _key(person.name) == _key(value)), None)
            if person is None:
                return missing('reception_teacher_not_found')
            if intent == 'teacher_now':
                result = self._answer_legacy(value + ' багш хаана вэ?', now=now)
                result['query'] = query
                if result['answer']:
                    # Avoid "Хуваариар бол Хуваарийн дагуу …" (same qualifier twice).
                    result['answer'] = 'Хуваариар бол ' + re.sub(r'^Хуваарийн дагуу\s*', '', result['answer'])
                return result
            if intent == 'teacher_hours':
                if not _recorded(person.office_hours):
                    return missing('reception_hours_unknown')
                return reply(person.name + ' — бүртгэсэн уулзах цаг: ' + person.office_hours
                             + '. Тэр цагт ирсэн эсэх, байршлыг батлахгүй.', 'staff', 'reception_teacher_hours')
            if intent == 'teacher_email':
                if not person.email:
                    return missing('reception_email_unknown')
                return reply(person.name + ' — сургуулийн имэйл: ' + person.email + '.' + self._workplace(person),
                             'staff', 'reception_teacher_email')
            room = next((room for room in self.tables.rooms if _key(room.name) == _key(person.room)), None)
            if not person.room or room is None:
                return missing('reception_room_unknown')
            return reply(person.name + ' — бүртгэлд заасан ажлын өрөө: ' + room.name + ', '
                         + str(room.floor) + '-р давхар. Одоо тэнд байгааг батлахгүй.', 'staff', 'reception_teacher_office')
        if intent == 'class_teacher_room':
            group, person, reason = self._class_teacher_of(value)
            if reason:
                return missing(reason)
            room = self._room_of(person)
            if room is None:
                return missing('reception_room_unknown')
            return reply(group.group + ' — бүртгэлд заасан ангийн багш: ' + group.teacher + '; ажлын өрөө: ' + room.name
                         + ', ' + str(room.floor) + '-р давхар. Одоо тэнд байгааг батлахгүй.', 'classes',
                         'reception_class_teacher_room')
        if intent == 'class_teacher_email':
            group, person, reason = self._class_teacher_of(value)
            if reason:
                return missing(reason)
            if person is None or not person.email:
                return missing('reception_email_unknown')
            return reply(group.group + ' — бүртгэлд заасан ангийн багш: ' + group.teacher + '; сургуулийн имэйл: '
                         + person.email + '.' + self._workplace(person), 'classes', 'reception_class_teacher_email')
        if intent == 'class_day':
            name, day = value
            group = next((group for group in self.tables.classes if _key(group.group) == _key(name)), None)
            if group is None:
                return missing()
            label = None
            if _key(day) in _RELATIVE_DAYS:
                # «КУ-2 анги маргааш хэдэн цагт хичээлтэй вэ?» (round 8): the date decides the weekday;
                # a date outside the term or on a recorded holiday has no timetable.
                target, reason = self._relative_day(day, now)
                if target is None:
                    return missing(reason)
                if reason == 'reception_holiday':
                    return reply(group.group + ' — ' + _key(day) + ' нь бүртгэсэн амралтын өдөр; хуваарьт хичээл байхгүй.',
                                 'timetable', 'reception_holiday')
                if reason:
                    return missing(reason)
                label = _RELATIVE_DAYS[_key(day)] + ' (' + _MN_DAYS[target.weekday()] + ' гараг)'
                day = _MN_DAYS[target.weekday()]
            weekday = _DAY_LOOKUP[_key(day)]
            lessons = sorted((lesson for lesson in self.tables.timetable if _key(lesson.group) == _key(group.group)
                              and lesson.day == _DAYS[weekday]), key=lambda lesson: lesson.interval[0])
            if not lessons and not self.tables.timetable_complete:
                return missing('reception_timetable_incomplete')
            # A joint lesson is stored once per teacher/room; list each time once.
            slots = list(dict.fromkeys(lesson.time + ' (' + lesson.room + ' тоот)' for lesson in lessons))
            period = (' Хуваарийн хугацаа: ' + self.tables.term_start.isoformat() + ' – '
                      + self.tables.term_end.isoformat() + '.') if self.tables.term_start and self.tables.term_end else ''
            return reply(group.group + ' — ' + (label or _MN_DAYS[weekday] + ' гарагийн') + ' бүртгэсэн хуваарь: '
                         + ('; '.join(slots) if slots else 'хичээл бүртгэгдээгүй') + '.' + period
                         + ' Хуваарь өөрчлөгдсөн байж болно; бодит байршлыг батлахгүй.', 'timetable', 'reception_class_day')
        if intent == 'timetable_where':
            if not self.tables.timetable:
                return missing('reception_timetable_incomplete')
            example = sorted(group.group for group in self.tables.classes)[:1]
            return reply('Ангийн хичээлийн хуваарийг энд харуулна: ангийн кодоо хэлнэ үү'
                         + (', жишээ нь «' + example[0] + ' анги маргааш хэдэн цагт хичээлтэй вэ?»' if example else '')
                         + '. Хуваарь өөрчлөгдсөн байж болно.', 'timetable', 'reception_timetable_where')
        if intent == 'bell_schedule':
            lessons = list(self.tables.timetable)
            if not lessons or not self.tables.timetable_complete:
                return missing('reception_timetable_incomplete')
            def clock(minutes):
                return '%02d:%02d' % divmod(minutes, 60)
            slots = {lesson.time: lesson.interval for lesson in lessons}
            counts = Counter(lesson.time for lesson in lessons)
            # The usual lesson length (a double period); half and joined periods are left out.
            usual = Counter(lesson.interval[1] - lesson.interval[0] for lesson in lessons).most_common(1)[0][0]
            common = sorted((time for time, (start, end) in slots.items() if end - start == usual and counts[time] >= 20),
                            key=lambda time: slots[time][0])
            return reply('Ресепшний хуваарийн хүснэгтээр хичээл ' + clock(min(start for start, _ in slots.values()))
                         + '-д эхэлж, хамгийн оройдоо ' + clock(max(end for _, end in slots.values())) + '-д дуусна.'
                         + (' Ихэвчлэн: ' + ', '.join(common) + '.' if common else '')
                         + ' Анги, өдөр бүрийн хуваарь өөр; тухайн ангийн өдрийн хуваарийг асууж болно.',
                         'timetable', 'reception_bell_schedule')
        if intent == 'term_dates':
            if not (self.tables.calendar_bound and self.tables.term_start and self.tables.term_end):
                return missing('reception_calendar_unknown')
            return reply('Ресепшний хуваарийн хүснэгтэд бүртгэсэн энэ улирлын хугацаа: '
                         + self.tables.term_start.isoformat() + '-оос ' + self.tables.term_end.isoformat()
                         + ' хүртэл. Шалгалт, амралтын өдрийг сургалтын албанаас тодруулна уу.',
                         'timetable', 'reception_term_dates')
        if intent in {'class_room', 'class_teacher'}:
            group = next((group for group in self.tables.classes if _key(group.group) == _key(value)), None)
            if group is None or intent == 'class_teacher' and not group.teacher:
                return missing()
            if intent == 'class_teacher':
                return reply(group.group + ' — бүртгэлд заасан ангийн багш: ' + group.teacher + '.', 'classes', 'reception_class_teacher')
            return reply(group.group + ' — бүртгэсэн үндсэн өрөө: ' + group.room
                         + '. Тухайн хичээлийн өрөө хуваариар өөр байж болно.', 'classes', 'reception_class_room')
        if intent == 'course_today':
            reason = self._calendar_reason(now)
            if reason:
                return missing(reason)
            if not isinstance(now, datetime):
                return missing('reception_date_required')
            if not self.tables.timetable_complete:
                return missing('reception_timetable_incomplete')
            groups = {_key(group.group) for group in self.tables.classes if group.course == value}
            if not groups:
                return missing()
            lessons = [lesson for lesson in self.tables.timetable if _key(lesson.group) in groups
                       and lesson.day == _DAYS[now.weekday()]]
            # A joint lesson is stored once per teacher/room; list each slot once.
            slots = list(dict.fromkeys(lesson.group + ': ' + lesson.time for lesson in lessons))
            text = ('; '.join(slots)
                    if lessons else 'энэ өдрийн бүрэн хуваарьт хичээл бүртгэгдээгүй')
            return reply(now.strftime('%Y-%m-%d') + ' — хуваариар бол ' + text
                         + '. Бодит байршлыг батлахгүй.', 'timetable', 'reception_course_timetable')
        return None

    def _answer_legacy(self, query, *, now=None):
        if not self.enabled:
            return None
        room, teacher = self._match(query)
        if not room and not teacher:
            return None
        if self.error or self.tables is None:
            return self._result(query, None, 'reception_data_unavailable')
        prefix = '[FAKE / ЗОХИОМОЛ ЖИШЭЭ] ' if self.tables.is_fake else ''
        if room:
            matches = [row for row in self.tables.rooms if _key(row.name) == _key(room[1])]
            if len(matches) != 1:
                # «Захирлын өрөө хаана вэ?» names a post, not a room: its holder's recorded room (round 5).
                person = self._post_holder(room[1])
                place = self._room_of(person)
                if place is None:
                    return self._result(query, None, 'reception_room_not_found')
                return self._result(query, prefix + self._post_room(person), 'reception_role_room', source_table='staff')
            row = matches[0]
            return self._result(query, prefix + row.name + ' өрөө: ' + str(row.floor) + '-р давхар.',
                'reception_room_lookup', source_table='rooms')
        person = next((row for row in self.tables.staff if _key(row.name) == _key(teacher[1])), None)
        if person is None:
            return self._result(query, None, 'reception_teacher_not_found')
        day, moment = teacher[2], teacher[3]
        if day and moment:
            try:
                minute = _minutes(moment)
            except ReceptionDataError:
                return self._result(query, None, 'reception_invalid_time')
            weekday = _DAY_LOOKUP[_key(day)]
        elif isinstance(now, datetime):
            weekday, minute = now.weekday(), now.hour * 60 + now.minute
            moment = now.strftime('%H:%M')
        else:
            return self._result(query, None, 'reception_time_required')
        if self.tables.calendar_bound and day and moment:
            if not isinstance(now, datetime) or weekday != now.weekday():
                return self._result(query, None, 'reception_date_required')
        calendar_reason = self._calendar_reason(now)
        if calendar_reason:
            return self._result(query, None, calendar_reason)
        own_lessons = [lesson for lesson in self.tables.timetable if _key(lesson.teacher) == _key(person.name)]
        active = any(lesson.day == _DAYS[weekday] and lesson.interval[0] <= minute < lesson.interval[1]
                     for lesson in own_lessons)
        if not active and not self.tables.timetable_complete:
            return self._result(query, None, 'reception_timetable_incomplete')
        # Deliberately exclude staff.room, classroom, group and lesson room from
        # every teacher response. Office hours do not prove presence either.
        status = 'in_class' if active else 'free'
        answer = prefix + 'Хуваарийн дагуу (' + _MN_DAYS[weekday] + ' ' + moment + '): '
        answer += ('хичээлтэй' if active else 'хичээлгүй (чөлөөтэй)') + '.'
        answer += ' Бодит байршлыг батлахгүй.'
        return self._result(query, answer, 'reception_teacher_timetable', source_table='timetable',
            timetable_status=status, weekday=_DAYS[weekday], time=moment)
