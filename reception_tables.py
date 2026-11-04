"""Small, validated reception tables. No database, network or model dependency.

Only an explicit opt-in config loads a local dataset. Timetable entries describe
scheduled activity, never a person's observed or confirmed physical location.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
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
    'staff': ('name', 'department', 'room', 'office_hours'),
    'classes': ('group', 'room'),
    'timetable': ('day', 'time', 'group', 'room', 'teacher'),
}
MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 5000
MAX_CELL = 300
_DAYS = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')
_MN_DAYS = ('даваа', 'мягмар', 'лхагва', 'пүрэв', 'баасан', 'бямба', 'ням')
_DAY_LOOKUP = {**{day: i for i, day in enumerate(_DAYS)},
               **{day: i for i, day in enumerate(_MN_DAYS)}}
_XML_NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
_REL_NS = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'


class ReceptionDataError(ValueError):
    """The whole dataset is rejected; no partially loaded answer is usable."""


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
class Room:
    floor: int
    name: str


@dataclass(frozen=True)
class Staff:
    name: str
    department: str
    room: str
    office_hours: str


@dataclass(frozen=True)
class ClassGroup:
    group: str
    room: str


@dataclass(frozen=True)
class Lesson:
    day: str
    time: str
    group: str
    room: str
    teacher: str

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


def _rows(values, table):
    if not values:
        raise ReceptionDataError(f'{table}: missing header.')
    header = tuple(str(v).strip() for v in values[0])
    if len(header) != len(set(header)) or set(header) != set(SCHEMA[table]):
        raise ReceptionDataError(f'{table}: columns must be {", ".join(SCHEMA[table])}.')
    result = []
    for line in values[1:]:
        if not any(v is not None and str(v).strip() for v in line):
            continue
        if len(line) != len(header):
            raise ReceptionDataError(f'{table}: row width does not match its header.')
        result.append({name: _cell(value) for name, value in zip(header, line)})
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


def _unique(rows, field, table):
    result = {_key(row[field]) for row in rows}
    if len(result) != len(rows):
        raise ReceptionDataError(f'{table}: duplicate {field}.')
    return result


def load_tables(path, *, timetable_complete=False, dataset_label='Reception tables', is_fake=False):
    """Read four CSV files in a directory, or four named sheets in one XLSX.

    All references and overlaps are checked before the immutable value is
    returned. CSV/XLSX files are inputs only; this function writes no files.
    """
    if type(timetable_complete) is not bool or type(is_fake) is not bool:
        raise ReceptionDataError('Dataset metadata flags must be booleans.')
    dataset_label = _cell(dataset_label)
    path = Path(path)
    try:
        if path.is_dir():
            rows = _csv_tables(path)
        elif path.suffix.casefold() == '.xlsx':
            rows = _xlsx_tables(path)
        else:
            raise ReceptionDataError('Select a CSV directory or an .xlsx workbook.')
    except OSError as error:
        raise ReceptionDataError('Reception input could not be read.') from error
    room_names = _unique(rows['rooms'], 'name', 'rooms')
    staff_names = _unique(rows['staff'], 'name', 'staff')
    group_names = _unique(rows['classes'], 'group', 'classes')
    rooms = []
    for row in rows['rooms']:
        if not re.fullmatch(r'-?\d{1,2}', row['floor']) or not -5 <= int(row['floor']) <= 99:
            raise ReceptionDataError('Room floor must be an integer from -5 through 99.')
        rooms.append(Room(int(row['floor']), row['name']))
    for table in ('staff', 'classes', 'timetable'):
        for row in rows[table]:
            if _key(row['room']) not in room_names:
                raise ReceptionDataError(f'{table}: unknown room.')
    lessons = []
    for row in rows['timetable']:
        day = _DAY_LOOKUP.get(_key(row['day']))
        if day is None:
            raise ReceptionDataError('Timetable day must be mon..sun or a Mongolian weekday.')
        if _key(row['teacher']) not in staff_names or _key(row['group']) not in group_names:
            raise ReceptionDataError('Timetable teacher/group is not in staff/classes.')
        start, end = _interval(row['time'])
        for previous in lessons:
            old_start, old_end = previous.interval
            if (previous.day == _DAYS[day] and start < old_end and old_start < end
                    and any(_key(getattr(previous, field)) == _key(row[field])
                            for field in ('teacher', 'group', 'room'))):
                raise ReceptionDataError('Timetable contains an overlapping teacher, group or room.')
        lessons.append(Lesson(_DAYS[day], row['time'], row['group'], row['room'], row['teacher']))
    return ReceptionTables(tuple(rooms), tuple(Staff(**row) for row in rows['staff']),
        tuple(ClassGroup(**row) for row in rows['classes']), tuple(lessons),
        timetable_complete, dataset_label, is_fake)


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
        cleaned = query.strip().rstrip('?!？.').strip()
        room = (re.fullmatch(r'(.{1,120}?)\s+өрөө\s+хаана(?:\s+байдаг)?\s*(?:вэ)?', cleaned, re.I)
                or re.fullmatch(r'өрөө\s+(.{1,120}?)\s+хаана(?:\s+байдаг)?\s*(?:вэ)?', cleaned, re.I)
                or re.fullmatch(r'where\s+is\s+room\s+(.{1,120})', cleaned, re.I))
        teacher = (re.fullmatch(r'(.{1,120}?)\s+багш\s+хаана(?:\s+байна)?\s*(?:вэ)?'
                    r'(?:\s*[,;]?\s*(даваа|мягмар|лхагва|пүрэв|баасан|бямба|ням|mon|tue|wed|thu|fri|sat|sun)'
                    r'\s+(\d{2}:\d{2}))?', cleaned, re.I)
                   or re.fullmatch(r'where\s+is\s+teacher\s+(.{1,120}?)(?:\s+on\s+'
                    r'(mon|tue|wed|thu|fri|sat|sun)\s+(\d{2}:\d{2}))?', cleaned, re.I))
        for match in (room, teacher):
            if match and re.search(r'\b(?:болон|ба|мөн|эсвэл|and|or)\b|[,;?!/]', match[1], re.I):
                return None, None
        return room, teacher

    def recognizes(self, query):
        return self.enabled and any(self._match(query))

    def answer(self, query, *, now=None):
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
                return self._result(query, None, 'reception_room_not_found')
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
