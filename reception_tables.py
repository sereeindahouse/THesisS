"""Small, validated reception tables. No database, network or model dependency.

Only an explicit opt-in config loads a local dataset. Timetable entries describe
scheduled activity, never a person's observed or confirmed physical location.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, replace
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


def _floor_number(word):
    """«2», «2-р», «хоёр», «хоёрдугаар», «аравдугаар» -> the floor number; «хонгил» -> -1 (every level
    below ground, see floor_rooms); None otherwise."""
    word = ((word or '').casefold().split() or [''])[0]   # the floor word before «давхарт»
    if word.startswith('хонгил'):
        return -1
    digits = re.match(r'(\d{1,2})', word)
    if digits:
        return int(digits.group(1))
    stem = re.sub(r'(?:дугаар|дүгээр)$', '', word)
    return 10 if stem in ('арав', 'арван') else NUMBER_UNITS.get(stem)


def floor_text(floor):
    """«5-р давхар»; below ground «хонгилын давхар» (round 11: the table's В3, В6, В7, В6Б read
    «-1-р давхар»). No minus sign, which the speech output would not read (review)."""
    if isinstance(floor, int) and floor < 0:
        return 'хонгилын давхар' if floor == -1 else 'газар доорх ' + str(-floor) + '-р давхар'
    return str(floor) + '-р давхар'


def _clock(minutes):
    return '%02d:%02d' % divmod(minutes, 60)


from answer_types import _UNITS as NUMBER_UNITS  # noqa: E402  (unit words shared with answer_types; «нэгэн» too)

_NUMBER_UNITS = NUMBER_UNITS
_NUMBER_TENS = {'арав': 10, 'арван': 10, 'хорь': 20, 'хорин': 20, 'гуч': 30, 'гучин': 30, 'дөч': 40, 'дөчин': 40,
                'тавь': 50, 'тавин': 50, 'жар': 60, 'жаран': 60, 'дал': 70, 'далан': 70, 'ная': 80, 'наян': 80,
                'ер': 90, 'ерэн': 90}
_NUMBER_WORD = '|'.join(sorted(list(_NUMBER_UNITS) + list(_NUMBER_TENS) + ['зуу', 'зуун', 'мянга', 'мянган'],
                               key=len, reverse=True))
_SPOKEN_ROOM = re.compile(r'(?<!\w)((?:(?:' + _NUMBER_WORD + r')\s+)+)(?=(?:тоот|өрөө)(?!\w))', re.I)


def _spoken_number(words):
    """«таван зуун найм» -> 508, «мянга зургаа» -> 1006; None when the words are no number."""
    total, unit = 0, None
    for word in words:
        if word in ('мянга', 'мянган'):
            total, unit = total + (unit or 1) * 1000, None
        elif word in ('зуу', 'зуун'):
            total, unit = total + (unit or 1) * 100, None
        elif word in _NUMBER_TENS:
            if unit is not None:
                return None
            total += _NUMBER_TENS[word]
        elif word in _NUMBER_UNITS:
            if unit is not None:
                return None
            unit = _NUMBER_UNITS[word]
        else:
            return None
    return total + (unit or 0) or None


def _spoken_room(match):
    words = match.group(1).casefold().split()
    if not any(word in ('зуу', 'зуун', 'мянга', 'мянган') for word in words):
        return match.group(0)
    number = _spoken_number(words)
    return str(number) + ' ' if number is not None else match.group(0)


_TELL_ME = r'(?:хэлж\s+өгөөч|хэлээч|хэлж\s+өгнө\s+үү|хэлнэ\s+үү|мэдэх\s+үү|мэдэх\s+бол\s+хэлээч)(?=\s*[?!.]*$)'
_ASKING = re.compile(r'(?<!\w)(?:хэзээ|хаана|хэд\w*|хэн|яаж|хэрхэн|ямар|юу|аль)(?!\w)', re.I)


# Round 21: speech recognition writes a filler at the start («аан», «өө», «тэгээд», «нөгөө», «за») and a
# colloquial ending («… хаана байдаг юм бэ», «… билээ», «… юм бол», «… болох юм уу»); «тэгээд захирал хэн юм
# бэ» was answered with a news item on a Japanese college's director.
# A filler stands alone before a space or a comma: an initial («Э.Батаа», «Ө.Болд») is no filler, and «нөгөө»
# («the other») keeps its meaning (review).
_FILLERS = re.compile(r'^(?:\s*(?:а+н+|ө{2,}|э{2,}|м{2,}|тэгээд|за)(?=[\s,]),?)+\s*(?=\S)', re.I)
_SPOKEN_END = re.compile(r'(\S+)\s+(?:юм(?:\s+(бэ|вэ|бол|уу|юу|үү))?|билээ)\s*([?!.]*)\s*$', re.I)
# «мэдэхгүй юм» (I don't know), «авах гэсэн юм» (a wish), «ямар юм бэ» (what thing) say «юм» as a statement or a noun.
_STATEMENT_BEFORE_YUM = re.compile(r'(?:гүй|гэсэн|гэж|ямар)$', re.I)


def last_vowel(word):
    """The word's last vowel other than «и» (it does not set the harmony), or ''."""
    return next((char for char in reversed(word.casefold()) if char in 'аэоөуүяеёюы'), '')


def _particle(word, yes_no=False):
    """The question particle a word takes: «байдаг вэ», «хэн бэ»; «байдаг уу», «бий юу», «тийм үү»."""
    word = word.casefold()
    if not yes_no:
        return 'бэ' if word[-1:] in 'мнв' else 'вэ'
    if word[-1:] in 'аэиоуөүяеёюй':
        return 'юу'
    return 'уу' if last_vowel(word) and last_vowel(word) in 'аоуяёюы' else 'үү'


def strip_fillers(text):
    """«аан номын сан …» -> «номын сан …» (round 21)."""
    return _FILLERS.sub('', text, count=1) if isinstance(text, str) else text


def spoken_form(text):
    """«аан номын сан хаана байдаг юм бэ» -> «номын сан хаана байдаг вэ», «… болох юм уу» -> «… болох уу»
    (round 21). An ending changes only in a question — a question word in its own sentence, or a yes/no
    particle — and not after a statement («… мэдэхгүй юм», «… авах гэсэн юм»), review."""
    text = strip_fillers(text)
    # «нөгөө … билээ» (that … again?) recalls a thing: «нөгөө» is a filler there, not «the other» (review).
    if re.search(r'\sбилээ\s*[?!.]*\s*$', text, re.I):
        text = re.sub(r'^\s*нөгөө\s+(?=\S)', '', text, flags=re.I)
    match = _SPOKEN_END.search(text)
    if match and not _STATEMENT_BEFORE_YUM.search(match.group(1)):
        yes_no = (match.group(2) or '').casefold() in ('уу', 'юу', 'үү')
        sentence = re.split(r'[.?!]\s+', text[:match.start(1)] + match.group(1))[-1]
        if yes_no or _ASKING.search(sentence):
            text = text[:match.start()] + match.group(1) + ' ' + _particle(match.group(1), yes_no) + match.group(3)
    return text


def normalize_wording(text):
    """Spoken and typed wordings in one form (round 8): «хэд/хэдэн давхарт» asks «хэддүгээр
    давхарт», «лаб» is «лаборатори», «хаана суудаг» is «хаана байдаг». The question planner and
    both reception matchers read the result. Round 13: a room number said in words («таван зуун
    найм тоот» -> «508 тоот»), «хэд давхар вэ» (no «-т»), the typo «хана вэ»."""
    text = spoken_form(_SPOKEN_ROOM.sub(_spoken_room, text))
    # Round 18: the typed «ве»/«бе», a spoken «хэд дүгээр» and a wondering «… хэзээ эхлэх бол?» in their usual
    # forms first, so the rules below see them («жилийн төлбөр хэд ве» found no answer). «бол» only in a
    # question: «Хэрэв элсэх бол» (if) stays (review).
    text = re.sub(r'(?<!\w)ве(?=\s*[?!.]*$)', 'вэ', text, flags=re.I)
    text = re.sub(r'(?<!\w)бе(?=\s*[?!.]*$)', 'бэ', text, flags=re.I)
    text = re.sub(r'(?<!\w)хэд(?:эн)?\s+дүгээр(?!\w)', 'хэддүгээр', text, flags=re.I)
    # Round 20: an indirect question asks the plain one: «Номын сан хаана байдгийг хэлж өгөөч» -> «… хаана байдаг
    # вэ», «Эмчийн өрөө хаана байгааг мэдэх үү?», «Сургалтын албаны өрөөг хэлж өгнө үү» -> «… өрөө хаана вэ».
    if _ASKING.search(text):
        text = re.sub(r'(?<!\w)(байд|ажиллад|байрлад)гийг\s+' + _TELL_ME, r'\1аг вэ', text, flags=re.I)
        text = re.sub(r'(?<!\w)байгааг\s+' + _TELL_ME, 'байдаг вэ', text, flags=re.I)
    text = re.sub(r'(?<!\w)өрөөг\s+' + _TELL_ME, 'өрөө хаана вэ', text, flags=re.I)
    if _ASKING.search(text):
        text = re.sub(r'(?<!\w)([^\W\d_]+[аэоөиу]х)\s+бол(?=\s*[?!.]*$)', r'\1 вэ', text, flags=re.I)
    text = re.sub(r'(?<!\w)хэддүгээр\s+давхар(?=\s+(?:вэ|бэ)\s*[?!.]*$|\s*[?!.]*$)', 'хэддүгээр давхарт', text, flags=re.I)
    text = re.sub(r'(?<!\w)((?:өрөө|алба|сан|төв|танхим|кабинет|лаборатори)\w*\s+)хэд(?:эн)?\s+давхар'
                  r'(?=\s+(?:вэ|бэ)\s*[?!.]*$|\s*[?!.]*$)', r'\1хэддүгээр давхарт', text, flags=re.I)
    text = re.sub(r'(?<!\w)хана(?=\s+(?:вэ|бэ|байдаг|байна|байрладаг)(?!\w)|\s*[?!.]*$)', 'хаана', text, flags=re.I)
    text = re.sub(r'(?<!\w)хэд(?:эн)?\s+давхарт(?!\w)', 'хэддүгээр давхарт', text, flags=re.I)
    text = re.sub(r'(?<!\w)лаб(?!\w)', 'лаборатори', text, flags=re.I)
    # «нягтлан» alone is the post «нягтлан бодогч» (round 9).
    text = re.sub(r'(?<!\w)(нягтлан)(?!\w)(?!\s+бодогч)', r'\1 бодогч', text, flags=re.I)
    # «Хоол хаана идэх вэ?» asks where the canteen is (round 17: a library paragraph under the heading
    # «Номын сан, спорт, хоол, хөгжил» was shown).
    text = re.sub(r'(?<!\w)(?:хоол(?:оо)?\s+хаана|хаана\s+хоол(?:оо)?)\s+(?:идэх|иддэг|идэж\s+болох)(?!\w)|'
                  r'(?<!\w)хоол\s+идэх\s+газар\s+хаана(?:\s+байдаг)?(?!\w)',
                  lambda match: ('Х' if match.group()[0].isupper() else 'х') + 'оолны газар хаана байдаг', text, flags=re.I)
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


def _corrected(tables, corrections):
    """The imported tables with the facts the user confirmed with the school after the import (config
    ``corrections``, 2026-11-18): they stay when a new timetable is imported. ``office_hours`` gives the common
    hours to services whose name holds a word and whose own hours are not recorded; ``staff_room_by_role`` moves
    the holders of a post to a recorded room. Anything malformed rejects the whole dataset."""
    if corrections is None:
        return tables
    if not isinstance(corrections, dict) or set(corrections) - {'note_mn', 'office_hours', 'staff_room_by_role'}:
        raise ReceptionDataError('Reception corrections have an unknown shape.')
    rooms, staff = tables.rooms, tables.staff
    hours = corrections.get('office_hours')
    if hours is not None:
        if (not isinstance(hours, dict) or set(hours) != {'name_contains', 'hours'}
                or not all(isinstance(hours[key], str) and hours[key].strip() for key in hours)
                or not re.fullmatch(r'\d{2}:\d{2}[–-]\d{2}:\d{2}', hours['hours'])):
            raise ReceptionDataError('Reception office hours must be a name word and HH:MM–HH:MM.')
        word = _key(hours['name_contains'])
        rooms = tuple(replace(room, services=tuple(
            replace(service, office_hours=hours['hours'])
            if word in _key(service.name) and not _recorded(service.office_hours) else service
            for service in room.services)) for room in rooms)
    moves = corrections.get('staff_room_by_role')
    if moves is not None:
        known = {_key(room.name) for room in rooms}
        if (not isinstance(moves, dict) or not all(isinstance(role, str) and isinstance(room, str) and _key(room) in known
                                                   for role, room in moves.items())):
            raise ReceptionDataError('A corrected staff room must be a recorded room.')
        by_role = {_key(role): room for role, room in moves.items()}
        staff = tuple(replace(person, room=by_role[_key(person.role)]) if _key(person.role) in by_role else person
                      for person in staff)
    return replace(tables, rooms=rooms, staff=staff)


class ReceptionAnswerPath:
    """Exact-name, closed-intent reception lookup. Disabled unless configured."""
    def __init__(self, tables=None, *, enabled=False, error=None):
        self.tables, self.enabled, self.error = tables, enabled is True, error
        self._subjects = {}   # _subject_teachers by asked value: one timetable scan per question (review)

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
            return cls(_corrected(load_tables(path, timetable_complete=value.get('timetable_complete', False),
                dataset_label=value.get('dataset_label', 'Reception tables'),
                is_fake=value.get('is_fake', False)), value.get('corrections')), enabled=True)
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
            'reception_floor_unknown': 'Энэ давхрын өрөө ресепшний хүснэгтэд бүртгэгдээгүй байна.',
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
            ('room_floor', r'([^\s?!,;/]{1,120}) тоот (?:өрөө )?хэддүгээр давхарт (?:байдаг |байна )?вэ'),
            # Round 13: «508 тоот хаана вэ?» (also said in words: «таван зуун найм тоот»).
            ('room_floor', r'([^\s?!,;/]{0,20}\d[^\s?!,;/]{0,20}) тоот (?:өрөө )?хаана (?:байдаг |байна )?вэ'),
            ('office_floor', r'(.{1,120}?) хэддүгээр давхарт (?:байдаг |байна )?вэ'),
            # 11/18: with the offices' hours recorded, the other wordings of the same question too.
            ('office_hours', r'(.{1,120}?) (?:хэдэн цагт|хэдэн цагаас(?: хэдэн цаг хүртэл)?|хэдэн цаг хүртэл|хэдээс хэд хүртэл) '
                             r'ажилладаг вэ'),
            ('office_hours', r'(.{1,120}?)(?:гийн|ны|ийн|ын) ажлын цаг (?:хэд|хэдэн|ямар)(?: вэ)?'),
            # A department's contact is its head (department_contact below), not an office's.
            ('office_contact', r'(?!.*тэнхим)(.{1,120}?)(?:тай|тэй|той) (?:яаж|хэрхэн) холбогдох (?:вэ|бэ)'),
            ('department', r'(.{1,120}?) тэнхим(?:ийн (?:байр|өрөө|багш нарын өрөө))? хаана (?:байдаг |байна |байрладаг )?вэ'),
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
            ('term_dates', r'(?:энэ )?(?:улирал|улирлын хичээл|хичээлийн улирал) хэзээ (дуус\w*|эхл\w*|эхэл\w*)(?: (?:вэ|бэ))?'),
            # Round 16: «Хичээл хэзээ эхэлсэн бэ?» showed a unit's founding in 2014. Only the past: «Хичээл
            # хэзээ дуусах вэ?» may ask about today's lessons.
            ('term_dates', r'(?:энэ )?(?:хичээлийн (?:шинэ )?жил|хичээл) хэзээ (эхэлсэн)(?: (?:вэ|бэ))?'),
            # Round 14: «Улирлын амралт хэзээ эхлэх вэ?» was answered with the curriculum page: the term's end.
            ('term_break', r'(?:энэ )?(?:улирлын|өвлийн) амралт хэзээ (эхл\w*|эхэл\w*)(?: вэ)?'),
            # Round 14: «Хичээл хэдэн минут үргэлжилдэг вэ?» showed the admission timeline.
            ('lesson_length', r'(?:нэг )?(хичээл|завсарлага)(?: нь)? хэдэн минут(?: (?:үргэлжилдэг|үргэлжлэх|байдаг|байх))?(?: вэ)?'),
            # 11/17 (5): the school day's lesson times, read from the whole timetable.
            ('bell_schedule', r'хичээл(?:үүд)? хэдэн цаг(?:т|аас) (эхэл\w*|эхл\w*|дуус\w*|тар\w*)(?: вэ)?'),
            # Round 9: «Хичээлийн хуваарь хаанаас харах вэ?» — the class timetable is shown here, by class.
            ('timetable_where', r'(?:хичээлийн |ангийн )?хуваар\w* (?:хаанаас|хаана) (харах|үзэх|олох|харж болох)(?: вэ)?'),
            # Round 12: «Б.Сэлмаа багш ямар хичээл заадаг вэ?» — the subjects in the published timetable.
            ('teacher_subjects', r'(.{1,120}?) багш (?:(?:ямар(?: ямар)?|юу) хичээл (?:заадаг|ордог|заах|орох)|юу заадаг) (?:вэ|бэ)'),
            ('teacher_email', r'(.{1,120}?) багшийн (?:и-?мэйл|имэйл|мэйл|цахим шуудан)(?:ийн)?(?: хаяг)?(?: (?:юу|хэд|ямар) (?:вэ|бэ))?'),
            ('teacher_room', r'(.{1,120}?) багшийн өрөө хаана (?:байдаг |байна )?вэ'),
            ('teacher_hours', r'(.{1,120}?) багш хэзээ оюутантай уулздаг вэ'),
            # 11/17 (5): a named day («маргааш», «даваа гарагт»); the published timetable only.
            ('teacher_day', r'(.{1,120}?) багш (өнөөдөр|маргааш|даваа|мягмар|лхагва|пүрэв|баасан|бямба|ням)'
                            r'(?: гарагт)? хичээлтэй юу'),
            # Round 15: «Б.Сэлмаа багш өнөөдөр хаана хичээл заах вэ?» — the day's lessons with their rooms.
            ('teacher_day_rooms', r'(.{1,120}?) багш (өнөөдөр|маргааш|даваа|мягмар|лхагва|пүрэв|баасан|бямба|ням)'
                                  r'(?: гарагт)? хаана (?:хичээл (?:заах|заадаг|орох|ордог)|хичээллэх|хичээллэдэг) (?:вэ|бэ)'),
            # Round 15: a room's timetable now or on a day («612 тоотод одоо хичээл орж байна уу?»).
            ('room_now', r'([^\s?!,;/]{0,20}\d[^\s?!,;/]{0,20}) тоот(?:од| өрөөнд)? одоо (?:хичээл(?: орж)? (?:байна|байгаа)|'
                         r'хичээлтэй|сул) (?:уу|юу|үү)'),
            ('room_day', r'([^\s?!,;/]{0,20}\d[^\s?!,;/]{0,20}) тоот(?:од| өрөөнд)? (даваа|мягмар|лхагва|пүрэв|баасан|бямба|ням|'
                         r'өнөөдөр|маргааш)(?: гарагт)? (?:ямар хичээл (?:ордог|орох|байдаг|байх|орно)(?: (?:вэ|бэ))?|'
                         r'хичээлтэй юу|хичээл (?:байна|байгаа) юу|хичээл орох уу)'),
            ('teacher_now', r'(.{1,120}?) багш одоо хичээлтэй юу'),
            ('class_room', r'(.{1,120}?) анги хаана хичээллэдэг вэ'),
            ('course_today', r'([1-9]|10)-р курс өнөөдөр хэдэн цагт хичээлтэй вэ'),
            ('class_teacher', r'(.{1,120}?) ангийн багш хэн бэ'),
            # Round 4 (11/17): «Сургуулийн захирал хэн бэ?», «Механик тэнхимийн эрхлэгч хэн бэ?»,
            # «Захиралтай уулзаж болох уу?» — a post recorded in the staff table. Claimed only when
            # the post names its holder(s) (_role_holders); otherwise the website path answers.
            # Round 12: «Сургуулийн захирлын нэр хэн бэ?» was read as the post «… захирлын нэр»; the name
            # question comes first. «Захирлыг хэн гэдэг вэ?» asks the same.
            # Round 15: «Математикийн багш хэн бэ?», «Физикийн хичээл хэн заадаг вэ?» — the published timetable.
            ('subject_teachers', r'(.{2,60}?) хичээл(?:ийг)? хэн (?:заадаг|заах|ордог|орох) (?:вэ|бэ)'),
            ('subject_teachers', r'(.{2,60}?) багш(?: нар)? хэн(?: хэн)? (?:вэ|бэ)'),
            # Round 19: «Англи хэлний багш нар хаана суудаг вэ?» asked which department; their recorded rooms.
            ('subject_teacher_rooms', r'(.{2,60}?) багш(?: нар)?(?:ын|ийн)?(?: (?:ажлын )?өрөө)? хаана (?:байдаг |байна |байрладаг )?'
                                      r'(?:вэ|бэ)'),
            # Round 19: «Карьер хөгжлийн төв хэн хариуцдаг вэ?» — the staff the table records for an office.
            ('office_staff', r'(.{2,80}?)(?:ыг|ийг|г)? (?:хэн|ямар ажилтан) (?:хариуцдаг|хариуцах|хариуцаж байна|ажилладаг) (?:вэ|бэ)'),
            # Round 20: «Номын сангийн ажилтан хэн бэ?» — the office's recorded staff.
            ('office_staff', r'(.{2,80}?)(?:гийн|ийн|ын|ны) ажилтан(?: нар)? хэн(?: хэн)? (?:вэ|бэ)'),
            ('role_name', r'(.{1,120}?) нэр (?:нь )?(?:юу|хэн) (?:вэ|бэ)'),
            ('role_name', r'(.{1,120}?)(?:ыг|ийг|г) хэн гэдэг (?:вэ|бэ)'),
            # Round 12: a post holder's school e-mail («Захирал хэн бэ?» then «Имэйл нь?» -> «Захирал имэйл»).
            ('role_email', r'(.{1,80}?) (?:и-?мэйл|имэйл|мэйл|цахим шуудан)(?: хаяг)?(?: (?:нь )?(?:юу|хэд|ямар) (?:вэ|бэ))?'),
            ('role_holder', r'(.{1,120}?) (?:нь )?хэн (?:бэ|вэ)'),
            ('role_meet', r'(.{1,120}?)(?:тай|тэй|той) (?:одоо )?(?:уулз(?:аж|ах) (?:болох|болно) уу|уулзах гэсэн(?: юм)?|'
                          r'уулзмаар байна|уулзъя)'),
            # Round 12: «КУ-2 ангийн хичээл хэдэн цагт дуусдаг вэ?» (no day) — each weekday's lesson times.
            # «хэзээ эхлэх» (when the term begins) is not a lesson hour (review).
            ('class_hours', r'(.{1,120}?) анги(?:йн)? хичээл(?:үүд)? (?:хэдэн цагт|хэдэн цагаас) (?:дуус|тар|эхэл|эхл)\w*'
                            r'(?: (?:вэ|бэ))?'),
            # Round 18: «КУ-2 ангийн хуваарь» — the timetable asked as at the desk, without a question word.
            ('class_week', r'(.{1,120}?) анги(?:йн)? (?:хичээлийн )?хуваарь(?: (?:юу|ямар) (?:вэ|бэ)| (?:харуулна уу|харуулаач|'
                           r'хэлнэ үү|хэлээч))?'),
            # Round 12: «Маргааш амралтын өдөр үү?», «Өнөөдөр хичээлтэй юу?» — the school calendar.
            ('calendar_day', r'(өнөөдөр|маргааш) (?:амралтын өдөр|амралт|хичээлтэй|хичээл орох|хичээл орно)(?: (?:үү|уу|юу))?'),
            # Round 22: «Ням гарагт хичээл ордог уу?» showed the office hours and a contest report; the timetable's
            # lessons on that weekday.
            ('weekday_lessons', r'(даваа|мягмар|лхагва|пүрэв|баасан|бямба|ням)(?: гар[аи]гт|д) (?:хичээл (?:ордог|байдаг|орох|орно|'
                                r'байна|байгаа)|хичээлтэй|хичээллэдэг) (?:уу|юу|үү)'),
            # Round 16: «Энэ долоо хоногт амралтын өдөр бий юу?» joined a news date with an internship's
            # «амралтаар». The recorded holidays of this week; before place_exists.
            ('week_holidays', r'энэ (долоо хоног|7 хоног)(?:т|ийн)? (?:амралтын өдөр|амралт|баярын өдөр)'
                              r'(?: (?:бий|байгаа|байна|байдаг|байх))? (?:юу|уу|үү)'),
            # Round 13: «2 давхарт юу байдаг вэ?», «Хоёрдугаар давхарт ямар өрөөнүүд байдаг вэ?» — the rooms table.
            ('floor_rooms', r'((?:\d{1,2}(?:-?(?:р|дугаар|дүгээр))?|[а-яөүё]+(?:дугаар|дүгээр)|[а-яөүё]+|хонгил(?:ын)?)\s+давхарт|хонгилд)\s+'
                            r'(?:юу|ямар(?:\s+ямар)?\s+(?:өрөө\w*|алба\w*|юм))\s+(?:байдаг|байна|бий)(?:\s+(?:вэ|бэ))?'),
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
                    # An office's own name may hold a comma («Дотоод хяналт, чанарын алба»); an unknown name is
                    # left to the website path by the office answers themselves.
                    if re.search(r'\b(?:болон|ба|мөн|эсвэл|and|or)\b|[;?!/]' + ('' if intent.startswith('office_') else '|,'),
                                 match[1], re.I):
                        return None
                    # A day question carries its group or teacher and its day.
                    if intent in ('class_day', 'teacher_day', 'teacher_day_rooms', 'room_day'):
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
        if extra is not None and extra[0] in ('subject_teachers', 'subject_teacher_rooms', 'room_now', 'room_day'):
            return any(self._match(query)) or self._claims(extra)
        if extra is not None and extra[0] == 'office_staff':
            return any(self._match(query)) or bool(self._office_staff(extra[1]))
        if extra is not None and extra[0] == 'office_contact':
            # A post one person holds («Сэтгэл зүйчтэй хэрхэн холбогдох вэ?»): their school e-mail (round 20).
            return (any(self._match(query)) or self._service(extra[1]) is not None
                    or len(self._role_holders(extra[1], True)) == 1)
        if extra is not None and extra[0] == 'floor_rooms':
            return _floor_number(extra[1]) is not None and bool(self.tables and self.tables.rooms)
        if extra is not None and extra[0] == 'role_email':
            holders = self._role_holders(extra[1])
            return any(self._match(query)) or len(holders) == 1
        if extra is not None and extra[0] in ('class_hours', 'class_week'):
            return any(self._match(query)) or self._group_named(extra[1]) is not None and bool(self.tables.timetable)
        if extra is not None and extra[0] == 'department':
            # Claimed only with a recorded room; another department goes on to the website (review, round 18).
            return any(self._match(query)) or bool(self._department_rooms(extra[1]))
        if extra is not None and extra[0] == 'teacher_subjects':
            person = self._staff_named(extra[1])
            return any(self._match(query)) or person is not None and any(
                _key(lesson.teacher) == _key(person.name) and lesson.subject for lesson in self.tables.timetable)
        if extra is not None and extra[0] == 'calendar_day':
            return self._calendar_known() and bool(self.tables.timetable)
        if extra is not None and extra[0] == 'week_holidays':
            return self._calendar_known()
        if extra is not None and extra[0] == 'weekday_lessons':
            return bool(self.tables and self.tables.timetable)
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
        return (' Ажлын өрөө: ' + room.name + ', ' + floor_text(room.floor) + '.') if room else ''

    def _post_room(self, person):
        """«Захирал (Т.Оюунжаргал): 508 өрөө, 5-р давхар.» for a post holder with a recorded room."""
        room = self._room_of(person)
        return (person.role + ' (' + person.name + '): ' + room.name + ' өрөө, ' + floor_text(room.floor)
                + '. Одоо тэнд байгааг батлахгүй.')

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
        # Round 19: «Багш нарын өрөө хаана вэ?» — seven rooms, most of them a department's; up to eight when
        # the rooms name at least two departments, which then tell them apart («Анги» names none).
        return (found if 1 <= len(found) <= 3 or len(found) <= 8 and len({room.department for room in found if room.department}) >= 2
                and sum(not room.department for room in found) <= 1 else [])

    def _purpose_reply(self, rooms):
        # Rooms grouped under their own recorded purpose («Гадаад хэлний кабинет», «Хэлний кабинет»).
        groups = {}
        labelled = len({room.department for room in rooms}) > 1
        for room in rooms:
            groups.setdefault(room.purpose, []).append(room.name + ' өрөө, ' + floor_text(room.floor)
                                                       + (' (' + room.department + ')' if labelled and room.department else ''))
        return '; '.join(purpose + ': ' + '; '.join(places) for purpose, places in groups.items()) + '.'

    def _place(self, value):
        """A recorded office or class group named in a plain location question."""
        if self.tables is None:
            return None
        name = _key(re.sub(r'\s+анги(?:йн)?$', '', value.strip(), flags=re.I))
        found = self._service(value) or self._service(re.sub(r'(?:гийн|ийн|ын|ны)\s+өрөө$', '', value.strip(), flags=re.I))
        if found is not None:
            return 'office', found[0], found[1]
        group = next((group for group in self.tables.classes if _key(group.group) == name), None)
        return ('class', group, None) if group is not None else None

    def _department_rooms(self, value):
        """Rooms recorded for a department, its teachers' room first; also by a short name («Механик тэнхим»
        is «Механик инженерийн тэнхим», round 18). Affiliated rooms, not proof of a unique department office.
        The department words are rule_selector's (one table, cached)."""
        from rule_selector import _department_stem

        def unit(text):
            return _key(re.sub(r'\s*тэнхим\w*$', '', text.strip(), flags=re.I))
        asked = _department_stem(value + ' тэнхим')
        return sorted((room for room in (self.tables.rooms if self.tables else ()) if room.department and (
            unit(value) in {unit(room.department), unit(room.department) + 'ы'}
            or asked is not None and _department_stem(room.department) == asked)),
            key=lambda room: 'багш нарын өрөө' not in (room.purpose or '').casefold())

    def _claims(self, extra):
        """Whether the tables can answer a timetable intent (round 15). recognizes() and answer() share it:
        rag_runtime.route calls answer() alone, so an unclaimed question must get None there and go on
        to the website path (review: «Барилгын тэнхимийн багш нар хэн хэн бэ?» lost its roster)."""
        intent, value = extra
        if self.tables is None or not self.tables.timetable:
            return False
        if intent in ('subject_teachers', 'subject_teacher_rooms'):
            return bool(self._subject_teachers(value))
        if intent in ('room_now', 'room_day'):
            return self._room_named(value if intent == 'room_now' else value[0]) is not None
        return True

    def _room_named(self, name):
        """The recorded name of a room in the rooms table or the timetable, or None."""
        for room in self.tables.rooms:
            if _key(room.name) == _key(name):
                return room.name
        return next((lesson.room for lesson in self.tables.timetable if _key(lesson.room) == _key(name)), None)

    def _resolve_day(self, day, now, subject):
        """(weekday, «маргааш (пүрэв)» / «даваа гарагт», None) for a named or relative day, or (None, None,
        result) when the calendar says the day has no timetable (shared by the day intents, review)."""
        if _key(day) not in _RELATIVE_DAYS:
            weekday = _DAY_LOOKUP[_key(day)]
            return weekday, _MN_DAYS[weekday] + ' гарагт', None
        target, reason = self._relative_day(day, now)
        if target is None:
            return None, None, ('missing', reason)
        weekday = target.weekday()
        when = _key(day) + ' (' + _MN_DAYS[weekday] + ')'
        if reason == 'reception_holiday':
            return None, None, ('reply', subject + ' — ' + when + ' нь бүртгэсэн амралтын өдөр; хуваарьт хичээл байхгүй.')
        if reason:
            return None, None, ('missing', reason)
        return weekday, when, None

    def _subject_teachers(self, value):
        """{subject: [teachers]} for the subjects whose name holds every asked word («Англи хэлний» ->
        «Англи хэл», «Техникийн Англи хэл»); none for a department, class or office («Механик тэнхимийн»)."""
        # A department, class or office is no subject; whole words, so «Албан хэрэг хөтлөлт» or
        # «Курсын төсөл» (subjects) stay (review).
        # A person named with an initial («Д.Мэргэн») is no subject either, though «мэргэ» starts «Мэргэжлийн
        # англи хэл» (review, round 19).
        if self.tables is None or re.search(r'(?<!\w)(?:тэнхим\w*|анги(?:йн)?|алба(?:ны|нд|д)?|\d+\s*-?\s*р\s+курс\w*)(?!\w)|'
                                            r'(?<![\w.])[А-ЯӨҮЁ]\.\s?[А-ЯӨҮЁа-яөүё]', value or '', re.I):
            return {}
        if value in self._subjects:
            return self._subjects[value]
        stems = []
        for word in re.findall(r'[а-яөүёa-z]+', _key(value)):
            stem = re.sub(r'(?:ийн|ын|ний|ны|н)$', '', word) if len(word) > 4 else word
            if len(stem) >= 3:   # an initial («Б.») or a short word matches nearly every subject (review)
                stems.append(stem[:max(3, len(stem) - 1)])
        if not stems or len(stems) > 4:
            return {}
        found = {}
        for lesson in self.tables.timetable:
            words = re.findall(r'[а-яөүёa-z]+', _key(lesson.subject))
            if lesson.subject and lesson.teacher and all(any(word.startswith(stem) for word in words) for stem in stems):
                found.setdefault(lesson.subject, set()).add(lesson.teacher)
        self._subjects[value] = {subject: sorted(teachers) for subject, teachers in found.items()}
        return self._subjects[value]

    def _subject_rooms(self, value):
        """«Англи хэлний багш нар хаана суудаг вэ?» (round 19): the teachers of the subjects holding the asked
        words, with the rooms the staff table records for them."""
        found = self._subject_teachers(value)
        teachers = list(dict.fromkeys(name for names in found.values() for name in names))
        places = []
        for name in teachers[:8]:
            room = self._room_of(self._staff_named(name))
            places.append(name + ' — ' + (room.name + ' өрөө, ' + floor_text(room.floor) if room else 'өрөө бүртгэгдээгүй'))
        seen = {}
        for subject in found:
            seen.setdefault(_key(subject), subject)
        subjects = list(seen.values())
        return ('Бүртгэсэн хуваарьт ' + ', '.join(subjects[:3]) + (' гэх мэт' if len(subjects) > 3 else '')
                + ' заадаг багш нарын ажлын өрөө: ' + '; '.join(places) + (' гэх мэт' if len(teachers) > 8 else '')
                + '. Одоо тэнд байгааг батлахгүй.')

    def _email_reply(self, person, missing, reply, reason):
        """«Н.Нямжаргал — Сэтгэл зүйч. Сургуулийн имэйл: … Ажлын өрөө: …» for a post holder, or why not."""
        if not person.email:
            return missing('reception_email_unknown')
        return reply(person.name + ' — ' + person.role + '. Сургуулийн имэйл: ' + person.email + '.' + self._workplace(person),
                     'staff', reason)

    def _office_staff(self, value):
        """Staff whose recorded unit holds the asked office («Карьер хөгжлийн төв» is in «Гадаад харилцаа, карьер
        хөгжлийн төв»), all of one unit; none for a short or ambiguous name (round 19)."""
        key = re.sub(r'\s+', ' ', _key(value))
        if self.tables is None or len(key) < 5:
            return []
        # «Номын санд хэн ажилладаг вэ?»: the office without its dative («санд» -> «сан», «албанд» -> «алба»), review.
        units = [_key(person.department) for person in self.tables.staff if person.department]
        key = next((candidate for candidate in (key, key[:-1] if key.endswith(('д', 'т')) else '',
                                                key[:-2] if key.endswith('нд') else '')
                    if len(candidate) >= 5 and any(candidate in unit for unit in units)), key)
        # Whole words («лийн төв» names nothing), review.
        within = re.compile(r'(?<!\w)' + re.escape(key) + r'(?!\w)')
        people = [person for person in self.tables.staff
                  if person.department and within.search(re.sub(r'\s+', ' ', _key(person.department)))]
        return people if len({_key(person.department) for person in people}) == 1 else []

    def _common_slots(self):
        """(usual lesson minutes, {time: interval}, the usual-length times many classes share, in order).
        The usual length is a double period; half and joined periods are left out."""
        lessons = self.tables.timetable
        slots = {lesson.time: lesson.interval for lesson in lessons}
        counts = Counter(lesson.time for lesson in lessons)
        usual = Counter(lesson.interval[1] - lesson.interval[0] for lesson in lessons).most_common(1)[0][0]
        common = sorted((time for time, (start, end) in slots.items() if end - start == usual and counts[time] >= 20),
                        key=lambda time: slots[time][0])
        return usual, slots, common

    def _group_named(self, value):
        if self.tables is None:
            return None
        return next((group for group in self.tables.classes if _key(group.group) == _key(value)), None)

    def _staff_named(self, value):
        if self.tables is None:
            return None
        return next((person for person in self.tables.staff if _key(person.name) == _key(value)), None)

    def _calendar_known(self):
        """Term dates and reviewed holidays: only then a day's status may be told (review, round 12)."""
        return bool(self.tables and self.tables.calendar_bound and self.tables.term_start and self.tables.term_end
                    and self.tables.holidays_reviewed)

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
        if intent == 'floor_rooms':
            floor = _floor_number(value)
            # «хонгил» is every level below ground (the table allows down to -5).
            rooms = sorted((room for room in self.tables.rooms
                            if (room.floor < 0 if floor == -1 else room.floor == floor)), key=lambda room: room.name)
            if not rooms:
                return missing('reception_floor_unknown')
            # Offices and named rooms first; plain classrooms by number (they crowded out the offices).
            named = [room for room in rooms if room.purpose and _key(room.purpose) != 'анги']
            plain = [room.name for room in rooms if room not in named]
            parts = []
            if named:
                parts.append(', '.join(room.name + ' (' + room.purpose + ')' for room in named[:8])
                             + (' гэх мэт ' + str(len(named)) + ' өрөө' if len(named) > 8 else ''))
            if plain:
                parts.append('анги, бусад өрөө: ' + ', '.join(plain[:8]) + (', …' if len(plain) > 8 else ''))
            return reply(floor_text(floor)[:1].upper() + floor_text(floor)[1:] + 'т бүртгэлтэй: ' + '; '.join(parts) + '.',
                         'rooms', 'reception_floor_rooms')
        if intent == 'role_email':
            people = self._role_holders(value)
            if len(people) != 1:
                return self._answer_legacy(query, now=now)
            return self._email_reply(people[0], missing, reply, 'reception_role_email')
        if intent == 'class_hours':
            group = self._group_named(value)
            if group is None:
                return missing()
            days = []
            for weekday, day in enumerate(_DAYS):
                spans = [lesson.interval for lesson in self.tables.timetable
                         if _key(lesson.group) == _key(group.group) and lesson.day == day]
                if spans:
                    days.append(_MN_DAYS[weekday] + ' ' + _clock(min(span[0] for span in spans))
                                + '–' + _clock(max(span[1] for span in spans)))
            if not days:
                return missing('reception_timetable_incomplete' if not self.tables.timetable_complete else 'reception_lookup_missing')
            return reply(group.group + ' — бүртгэсэн хуваарийн хичээлийн цаг: ' + '; '.join(days)
                         + '. Хуваарь өөрчлөгдсөн байж болно.', 'timetable', 'reception_class_hours')
        if intent == 'class_week':
            group = self._group_named(value)
            if group is None or not self.tables.timetable:
                return self._answer_legacy(query, now=now)   # not claimed (recognizes)
            days = []
            for weekday, day in enumerate(_DAYS):
                lessons = sorted((lesson for lesson in self.tables.timetable
                                  if _key(lesson.group) == _key(group.group) and lesson.day == day),
                                 key=lambda lesson: lesson.interval)
                # One slot's subgroups in several rooms once: «09:35 Англи хэл (408, 611, 303)».
                slots = {}
                for lesson in lessons:
                    slots.setdefault((_clock(lesson.interval[0]), lesson.subject or 'хичээл'), []).append(lesson.room)
                if slots:
                    days.append(_MN_DAYS[weekday] + ' ' + ', '.join(
                        time + ' ' + subject + ' (' + ', '.join(dict.fromkeys(rooms)) + ')'
                        for (time, subject), rooms in slots.items()))
            if not days:
                return missing('reception_timetable_incomplete' if not self.tables.timetable_complete else 'reception_lookup_missing')
            return reply(group.group + ' — бүртгэсэн долоо хоногийн хуваарь: ' + '; '.join(days)
                         + '. Хуваарь өөрчлөгдсөн байж болно.', 'timetable', 'reception_class_week')
        if intent == 'calendar_day':
            if not self._calendar_known():
                return missing('reception_calendar_unknown')
            target, reason = self._relative_day(value, now)
            if target is None or reason in ('reception_date_required', 'reception_calendar_unknown'):
                return missing(reason or 'reception_calendar_unknown')
            when = _key(value).capitalize() + ' (' + _MN_DAYS[target.weekday()] + ' гараг, ' + target.strftime('%m/%d') + ')'
            holiday = 'амралт' in query.casefold()
            if reason == 'reception_holiday':
                return reply(('Тийм. ' if holiday else 'Үгүй. ') + when + ' нь бүртгэсэн амралтын өдөр.', 'timetable',
                             'reception_holiday')
            if reason == 'reception_outside_term':
                return reply(when + ' хичээлийн улирлаас гадуур (' + self.tables.term_start.isoformat() + ' – '
                             + self.tables.term_end.isoformat() + ').', 'timetable', 'reception_outside_term')
            groups = {lesson.group for lesson in self.tables.timetable if lesson.day == _DAYS[target.weekday()]}
            if not groups:
                if not self.tables.timetable_complete:
                    return missing('reception_timetable_incomplete')
                return reply(('Тийм. ' if holiday else 'Үгүй. ') + when + ' хуваарьт хичээл бүртгэгдээгүй.', 'timetable',
                             'reception_no_lessons')
            return reply(('Үгүй. ' if holiday else 'Тийм. ') + when + ' хичээлийн өдөр: бүртгэсэн хуваарьт '
                         + str(len(groups)) + ' анги хичээлтэй. Ангийн кодоо хэлбэл тухайн ангийн хуваарийг харуулна.',
                         'timetable', 'reception_school_day')
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
        if intent in ('subject_teachers', 'subject_teacher_rooms', 'room_now', 'room_day') and not self._claims(extra):
            return self._answer_legacy(query, now=now)
        if intent == 'subject_teacher_rooms':
            return reply(self._subject_rooms(value), 'staff', 'reception_subject_teacher_rooms')
        if intent == 'office_staff':
            people = self._office_staff(value)
            if not people:
                return self._answer_legacy(query, now=now)   # not claimed (recognizes)
            # The unit's head answers «who is responsible» for a department of twenty teachers (review).
            heads = [person for person in people if re.search(r'эрхлэгч|дарга|захирал|менежер', person.role or '', re.I)]
            shown = (heads or people)[:6]
            roles = {}
            for person in shown:
                roles.setdefault(person.role or 'ажилтан', []).append(person.name)
            rooms = [room for room in dict.fromkeys(self._room_of(person) for person in shown) if room is not None]
            more = len(heads or people) - len(shown)
            return reply(people[0].department + ' — бүртгэлд заасан ' + ('хариуцагч' if heads else 'ажилтан') + ': '
                         + '; '.join(', '.join(names) + ' (' + role + ')' for role, names in roles.items())
                         + (' гэх мэт ' + str(len(heads or people)) + ' хүн' if more > 0 else '')
                         + ('. Ажлын өрөө: ' + ', '.join(room.name + ' (' + floor_text(room.floor) + ')' for room in rooms) if rooms else '')
                         + '.', 'staff', 'reception_office_staff')
        if intent == 'subject_teachers':
            found = self._subject_teachers(value)
            subjects = sorted(found.items())
            listed = '; '.join(subject + ' — ' + ', '.join(teachers[:4]) + (', …' if len(teachers) > 4 else '')
                               for subject, teachers in subjects[:5])
            more = ' гэх мэт ' + str(len(subjects)) + ' хичээл' if len(subjects) > 5 else ''
            return reply('Бүртгэсэн хуваарьт: ' + listed + more + '. Хуваарь өөрчлөгдсөн байж болно.', 'timetable',
                         'reception_subject_teachers')
        if intent in ('room_now', 'room_day'):
            room = self._room_named(value if intent == 'room_now' else value[0])
            here = [lesson for lesson in self.tables.timetable if _key(lesson.room) == _key(room)]
            if intent == 'room_now':
                if not isinstance(now, datetime):
                    return missing('reception_date_required')
                reason = self._calendar_reason(now)
                if reason == 'reception_holiday':
                    return reply(room + ' тоот — өнөөдөр бүртгэсэн амралтын өдөр; хуваарьт хичээл байхгүй.', 'timetable',
                                 'reception_holiday')
                if reason:
                    return missing(reason)
                weekday, minute = now.weekday(), now.hour * 60 + now.minute
                when = 'одоо (' + _MN_DAYS[weekday] + ' ' + now.strftime('%H:%M') + ')'
            else:
                weekday, when, early = self._resolve_day(value[1], now, room + ' тоот')
                if early:
                    return missing(early[1]) if early[0] == 'missing' else reply(early[1], 'timetable', 'reception_holiday')
            today = sorted((lesson for lesson in here if lesson.day == _DAYS[weekday]), key=lambda lesson: lesson.interval[0])
            if not today and not self.tables.timetable_complete:
                return missing('reception_timetable_incomplete')
            def lesson_text(lesson):
                return lesson.time + ' ' + lesson.group + (' (' + lesson.subject + ')' if lesson.subject else '')
            if intent == 'room_now':
                current = [lesson for lesson in today if lesson.interval[0] <= minute < lesson.interval[1]]
                if not current and not self.tables.timetable_complete:
                    return missing('reception_timetable_incomplete')   # never «сул» from a partial timetable
                upcoming = [lesson for lesson in today if lesson.interval[0] > minute]
                text = (room + ' тоот — хуваариар ' + when + ': ' + '; '.join(dict.fromkeys(lesson_text(lesson) for lesson in current))
                        if current else room + ' тоот — хуваариар ' + when + ' хичээл бүртгэгдээгүй (сул)')
                if upcoming:
                    first = upcoming[0].interval[0]
                    text += '. Дараагийн хичээл: ' + '; '.join(dict.fromkeys(
                        lesson_text(lesson) for lesson in upcoming if lesson.interval[0] == first))
                return reply(text + '. Бодит байдлыг батлахгүй.', 'timetable', 'reception_room_now')
            listed = '; '.join(dict.fromkeys(lesson_text(lesson) for lesson in today))
            return reply(room + ' тоот — ' + when + ' ' + ('бүртгэсэн хичээл: ' + listed if today else 'хуваарьт хичээл бүртгэгдээгүй')
                         + '. Хуваарь өөрчлөгдсөн байж болно.', 'timetable', 'reception_room_day')
        if intent in ('teacher_day', 'teacher_day_rooms'):
            # «Б.Сэлмаа багш маргааш хичээлтэй юу?»: lessons in the published timetable that day
            # only (busy/free and times); presence in the office is never confirmed.
            name, day = value
            person = next((person for person in self.tables.staff if _key(person.name) == _key(name)), None)
            if person is None:
                return missing('reception_teacher_not_found')
            weekday, when, early = self._resolve_day(day, now, person.name)
            if early:
                return missing(early[1]) if early[0] == 'missing' else reply(early[1], 'timetable', 'reception_holiday')
            lessons = sorted((lesson for lesson in self.tables.timetable if _key(lesson.teacher) == _key(person.name)
                              and lesson.day == _DAYS[weekday]), key=lambda lesson: lesson.interval[0])
            if not lessons and not self.tables.timetable_complete:
                return missing('reception_timetable_incomplete')
            # A joint lesson is stored once per group; list each time once (with its room when asked where).
            times = list(dict.fromkeys(lesson.time + (' (' + lesson.room + ' тоот)' if intent == 'teacher_day_rooms' else '')
                                       for lesson in lessons))
            status = ('хуваариар хичээлтэй: ' + ', '.join(times)) if times else 'хуваарьт хичээл бүртгэгдээгүй (сул)'
            return reply(person.name + ' — ' + when + ' ' + status
                         + '. Хуваарь өөрчлөгдсөн байж болно; өрөөндөө байгааг батлахгүй.', 'timetable',
                         'reception_teacher_day_rooms' if intent == 'teacher_day_rooms' else 'reception_teacher_day')
        if intent == 'place_exists':
            found = self._service(value)
            if found is not None:
                room, service = found
                return reply('Тийм. ' + service.name + ': ' + room.name + ' өрөө, ' + floor_text(room.floor) + '.',
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
                return reply(second.name + ': ' + first.name + ' өрөө, ' + floor_text(first.floor) + '.',
                             'rooms', 'reception_service_lookup')
            return reply(first.group + ' — бүртгэсэн үндсэн өрөө: ' + first.room
                         + '. Тухайн хичээлийн өрөө хуваариар өөр байж болно.', 'classes', 'reception_class_room')
        if intent.startswith('office_'):
            found = self._service(value)
            rooms = self._purpose_rooms(value) if found is None and intent == 'office_floor' else []
            if rooms:
                return reply(self._purpose_reply(rooms), 'rooms', 'reception_purpose_lookup')
            if intent == 'office_contact' and (found is None or not found[1].contact or found[1].contact in {'—', '-'}):
                # Round 20: «Сэтгэл зүйчтэй хэрхэн холбогдох вэ?» — a post one person holds, also when a room carries
                # its name, by the post itself: one staff member of an office is not its contact (review).
                holders = [person for person in self._role_holders(value, found is None)
                           if _key(value) in _key(person.role) or _key(person.role) in _key(value)]
                if len(holders) == 1:
                    return self._email_reply(holders[0], missing, reply, 'reception_role_contact')
            if found is None:
                code = re.fullmatch(r'(.{1,40}?)\s+өрөө', value.strip())
                if intent == 'office_floor' and code:
                    return self._answer_legacy(code[1] + ' өрөө хаана вэ?', now=now) | {'query': query}
                return None  # not a recorded office ("Сургууль хэдэн цагт…"): main RAG path
            room, service = found
            if intent == 'office_floor':
                text = service.name + ': ' + floor_text(room.floor) + '.'
            elif intent == 'office_full':
                text = (service.name + ': ' + room.name + ' өрөө, ' + floor_text(room.floor) + '. '
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
            matches = self._department_rooms(value)
            if not matches:
                return self._answer_legacy(query, now=now)   # not claimed (recognizes)
            # «… тэнхимийн багш нарын өрөө хаана вэ?» asks for that room only (W04-R08).
            if 'багш нарын өрөө' in query.casefold():
                matches = [room for room in matches if 'багш нарын өрөө' in (room.purpose or '').casefold()] or matches
            return reply('Тэнхимд хамаарах бүртгэлтэй өрөө: ' + '; '.join(
                room.name + ' (' + floor_text(room.floor) + '; ' + (room.purpose or 'зориулалт дутуу') + ')'
                for room in matches) + '. Тэнхимийн ганц төв байр гэж батлахгүй.', 'rooms', 'reception_department_rooms')
        if intent == 'teacher_subjects':
            person = self._staff_named(value)
            if person is None:
                return missing('reception_teacher_not_found')
            taught = {}
            for lesson in self.tables.timetable:
                if _key(lesson.teacher) == _key(person.name) and lesson.subject:
                    taught.setdefault(lesson.subject, []).append(lesson.group)
            if not taught:
                return missing('reception_timetable_incomplete' if not self.tables.timetable_complete else 'reception_lookup_missing')
            def groups_of(groups):
                groups = sorted(set(groups))
                return ', '.join(groups[:4]) + (', …' if len(groups) > 4 else '')
            subjects = ['%s (%s)' % (subject, groups_of(groups)) for subject, groups in sorted(taught.items())]
            shown = '; '.join(subjects[:5]) + (' гэх мэт ' + str(len(subjects)) + ' хичээл' if len(subjects) > 5 else '')
            return reply(person.name + ' — бүртгэсэн хуваарьт заадаг хичээл: ' + shown
                         + '. Хуваарь өөрчлөгдсөн байж болно.', 'timetable', 'reception_teacher_subjects')
        if intent.startswith('teacher_'):
            person = next((person for person in self.tables.staff if _key(person.name) == _key(value)), None)
            if person is None and intent == 'teacher_room' and self._subject_teachers(value):
                # «Англи хэлний багшийн өрөө хаана вэ?» names a subject, not a teacher (round 19).
                return reply(self._subject_rooms(value), 'staff', 'reception_subject_teacher_rooms')
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
                         + floor_text(room.floor) + '. Одоо тэнд байгааг батлахгүй.', 'staff', 'reception_teacher_office')
        if intent == 'class_teacher_room':
            group, person, reason = self._class_teacher_of(value)
            if reason:
                return missing(reason)
            room = self._room_of(person)
            if room is None:
                return missing('reception_room_unknown')
            return reply(group.group + ' — бүртгэлд заасан ангийн багш: ' + group.teacher + '; ажлын өрөө: ' + room.name
                         + ', ' + floor_text(room.floor) + '. Одоо тэнд байгааг батлахгүй.', 'classes',
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
            _, slots, common = self._common_slots()
            return reply('Ресепшний хуваарийн хүснэгтээр хичээл ' + _clock(min(start for start, _ in slots.values()))
                         + '-д эхэлж, хамгийн оройдоо ' + _clock(max(end for _, end in slots.values())) + '-д дуусна.'
                         + (' Ихэвчлэн: ' + ', '.join(common) + '.' if common else '')
                         + ' Анги, өдөр бүрийн хуваарь өөр; тухайн ангийн өдрийн хуваарийг асууж болно.',
                         'timetable', 'reception_bell_schedule')
        if intent == 'lesson_length':
            if not self.tables.timetable or not self.tables.timetable_complete:
                return missing('reception_timetable_incomplete')
            usual, slots, common = self._common_slots()
            if not common:
                return missing('reception_lookup_missing')
            # Only slots that follow each other; two shift patterns may overlap (review).
            gaps = [(slots[later][0] - slots[earlier][1], earlier, later) for earlier, later in zip(common, common[1:])
                    if slots[later][0] >= slots[earlier][1]]
            if _key(value).startswith('завсарлага') and not gaps:
                return missing('reception_lookup_missing')
            short = Counter(gap for gap, _, _ in gaps).most_common(1)[0][0] if gaps else None
            long = [(gap, earlier, later) for gap, earlier, later in gaps if short is not None and gap > short]
            text = 'Ресепшний хуваарийн хүснэгтээр нэг хичээл ихэвчлэн ' + str(usual) + ' минут'
            if short is not None:
                text += ', хичээлийн хооронд ' + str(short) + ' минутын завсарлагатай'
            for gap, earlier, later in long[:1]:
                text += '; ' + _clock(slots[earlier][1]) + '–' + _clock(slots[later][0]) + ' хооронд ' + str(gap) + ' минут'
            return reply(text + ' (' + ', '.join(common) + ').', 'timetable', 'reception_lesson_length')
        if intent == 'term_break':
            if not (self.tables.calendar_bound and self.tables.term_start and self.tables.term_end):
                return missing('reception_calendar_unknown')
            # The break's own dates are not recorded; only this term's end is (review, round 14).
            return reply('Ресепшний хуанлид амралтын хугацаа бүртгэгдээгүй; энэ улирлын хичээл '
                         + self.tables.term_end.isoformat() + '-нд дуусна. Амралтын яг хугацааг сургалтын албанаас тодруулна уу.',
                         'timetable', 'reception_term_break')
        if intent == 'weekday_lessons':
            if not self.tables.timetable:
                return self._answer_legacy(query, now=now)   # not claimed (recognizes)
            weekday = _DAY_LOOKUP[_key(value)]
            # Outside the term the stored timetable does not apply, as for «Өнөөдөр хичээлтэй юу?» (review).
            if self._calendar_known() and isinstance(now, datetime) and self._calendar_reason(now) == 'reception_outside_term':
                return reply('Одоо хичээлийн улирлаас гадуур (' + self.tables.term_start.isoformat() + ' – '
                             + self.tables.term_end.isoformat() + ').', 'timetable', 'reception_outside_term')
            groups = {lesson.group for lesson in self.tables.timetable if lesson.day == _DAYS[weekday]}
            day = _MN_DAYS[weekday].capitalize() + ' гарагт'
            if not groups:
                if not self.tables.timetable_complete:
                    return missing('reception_timetable_incomplete')
                return reply('Үгүй. ' + day + ' бүртгэсэн хуваарьт хичээл байхгүй.', 'timetable', 'reception_weekday_no_lessons')
            return reply('Тийм. ' + day + ' бүртгэсэн хуваарьт ' + str(len(groups)) + ' анги хичээлтэй. Амралт, баярын '
                         'өдөр өөр байж болно.', 'timetable', 'reception_weekday_lessons')
        if intent == 'week_holidays':
            if not self._calendar_known():
                return self._answer_legacy(query, now=now)   # not claimed (recognizes)
            if not isinstance(now, datetime):
                return missing('reception_date_required')
            monday = now.date() - timedelta(days=now.weekday())
            week = [monday + timedelta(days=offset) for offset in range(7)]
            span = week[0].strftime('%m/%d') + '–' + week[-1].strftime('%m/%d')

            def named(days):
                return ', '.join(_MN_DAYS[day.weekday()] + ' (' + day.strftime('%m/%d') + ')' for day in days)
            outside = [day for day in week if not self.tables.term_start <= day <= self.tables.term_end]
            if len(outside) == len(week):
                return reply('Энэ долоо хоног (' + span + ') хичээлийн улирлаас гадуур (' + self.tables.term_start.isoformat()
                             + ' – ' + self.tables.term_end.isoformat() + ').', 'timetable', 'reception_outside_term')
            found = [day for day in week if day in self.tables.holidays]
            text = ('Энэ долоо хоногт (' + span + ') бүртгэсэн амралтын өдөр: ' + named(found) + '.' if found
                    else 'Энэ долоо хоногт (' + span + ') хуанлид бүртгэсэн амралтын өдөр байхгүй.')
            if outside:
                text += ' Хичээлийн улирлаас гадуур: ' + named(outside) + '.'
            return reply(text, 'timetable', 'reception_week_holidays')
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
            return self._result(query, prefix + row.name + ' өрөө: ' + floor_text(row.floor) + '.',
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
