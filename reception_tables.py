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


# 11/23 (check set): typed shortenings («Захиралын өрөө хэдэн давхарт бга вэ», «Сургалтын алба хаана бдаг вэ»).
_SHORT_FORMS = (
    (r'(?<!\w)бдаг(?!\w)', 'байдаг'),
    (r'(?<!\w)бгаа?(?!\w)', 'байгаа'),
    (r'(?<!\w)бнуу?(?!\w)', 'байна уу'),
    (r'(?<!\w)бн(?!\w)', 'байна'),
    (r'(?<!\w)бхгүй(?!\w)', 'байхгүй'),
    (r'(?<!\w)([Зз])ахиралын(?!\w)', r'\1ахирлын'),
)
_LOCATION_ASK = r'(?:хаана|хэддүгээр\s+давхар|хэдэн\s+давхар|хэд\s+давхар)'
# A place the question names itself: a number, a room, an office, a hall (not «тэр», «тэд»).
_OWN_PLACE = r'(?:\d|өрөө|тоот|алба|тэнхим|анги|танхим|заал|лаборатори|номын\s+сан|ресепшн)'


def strip_context_clause(text):
    """The visitor's reason before the question, when the question is about a place (11/23, check set):
    «Сургалтад ирсэн юм, 809 тоот хаана байдаг вэ?» -> «809 тоот хаана байдаг вэ?», «Уулзах гэсэн юм, хаана
    суудаг вэ?» -> «хаана суудаг вэ?» (the planner then gives it the subject of the question before), and
    «X-тай уулзъя гэсэн юм, тэд хаана суудаг вэ?» -> «X хаана суудаг вэ?». Only before a place question: «Элсэх
    гэсэн юм, бүртгэл хэзээ эхлэх вэ?» keeps its admission context."""
    if not isinstance(text, str):
        return text
    # Only when the place question names its own place («809 тоот хаана …»): in «Би ажлын ярилцлагад ирсэн юм аа.
    # Хэдэн давхарт гарах вэ?» the reason is what the visitor asks about (check set Q35), and in «Сэлмаа багштай
    # уулзахаар ирсэн юм, тэр хаана …» the person is (the meeting rule below, also after «… ирсэн юм. X-тай уулзъя …»).
    text = re.sub(r'^\s*[^?!.,]{2,60}?\s+ирсэн\s+юм(?:\s+аа)?\s*[,.]\s*(?=[^?!.]*?(?:' + _OWN_PLACE + r'|(?:тай|тэй|той)\s+уулз)[^?!.]*?\s'
                  + _LOCATION_ASK + r')', '', text, count=1, flags=re.I)
    # The dot of an initial («Б.Сэлмаа багштай …») is part of the name, not the end of a sentence.
    meet = re.fullmatch(r'\s*(?P<who>(?:[^?!.,]|(?<=(?-i:[А-ЯӨҮЁ]))\.){2,80}?)(?:тай|тэй|той)\s+уулз\w*\s+(?:гэсэн|ирсэн)\s+юм(?:\s+аа)?\s*[,.]\s*'
                        r'(?:тэд|тэр|тэр\s+хүн|түүнийг)?\s*(?P<ask>' + _LOCATION_ASK + r'.*)', text, re.I | re.S)
    if meet:
        return meet.group('who').strip() + ' ' + meet.group('ask')
    return re.sub(r'^\s*уулз\w*\s+гэсэн\s+юм(?:\s+аа)?\s*[,.]\s*(?=' + _LOCATION_ASK + r')', '', text, count=1, flags=re.I)


def normalize_wording(text):
    """Spoken and typed wordings in one form (round 8): «хэд/хэдэн давхарт» asks «хэддүгээр
    давхарт», «лаб» is «лаборатори», «хаана суудаг» is «хаана байдаг». The question planner and
    both reception matchers read the result. Round 13: a room number said in words («таван зуун
    найм тоот» -> «508 тоот»), «хэд давхар вэ» (no «-т»), the typo «хана вэ»."""
    for pattern, replacement in _SHORT_FORMS:
        text = re.sub(pattern, replacement, text, flags=re.I)
    text = strip_context_clause(text)
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
    # 11/23: a floor or a room does not move: «…хэддүгээр давхарт байгаа вэ», «… өрөө хаана байгаа вэ» ask where it
    # is («байдаг»); a person's «хаана байгаа вэ» (where now) is left as asked.
    text = re.sub(r'(?<!\w)(хэддүгээр\s+давхарт)\s+байгаа(?=\s+(?:вэ|бэ)(?!\w))', r'\1 байдаг', text, flags=re.I)
    text = re.sub(r'(?<!\w)((?:өрөө|тоот|алба)\w*\s+хаана)\s+байгаа(?=\s+(?:вэ|бэ)(?!\w))', r'\1 байдаг', text, flags=re.I)
    # «КУ-4 мягмар гарагт хэдэн цагаас хичээлтэй вэ?» asks the same as «… хэдэн цагт хичээлтэй вэ?».
    text = re.sub(r'(?<!\w)хэдэн\s+цагаас\s+(?=хичээлтэй(?!\w))', 'хэдэн цагт ', text, flags=re.I)
    text = re.sub(r'(?<!\w)лаб(?!\w)', 'лаборатори', text, flags=re.I)
    # «нягтлан» alone is the post «нягтлан бодогч» (round 9).
    text = re.sub(r'(?<!\w)(нягтлан)(?!\w)(?!\s+бодогч)', r'\1 бодогч', text, flags=re.I)
    # «Хоол хаана идэх вэ?» asks where the canteen is (round 17: a library paragraph under the heading
    # «Номын сан, спорт, хоол, хөгжил» was shown).
    text = re.sub(r'(?<!\w)(?:хоол(?:оо)?\s+хаана|хаана\s+хоол(?:оо)?)\s+(?:идэх|иддэг|идэж\s+болох)(?!\w)|'
                  r'(?<!\w)хоол\s+идэх\s+газар\s+хаана(?:\s+байдаг)?(?!\w)',
                  lambda match: ('Х' if match.group()[0].isupper() else 'х') + 'оолны газар хаана байдаг', text, flags=re.I)
    return re.sub(r'(?<!\w)хаана\s+суудаг', 'хаана байдаг', text, flags=re.I)


# 11/22 the user read the answers: «КУ-2 — бүртгэсэн үндсэн өрөө: 612. Тухайн хичээлийн өрөө хуваариар
# өөр байж болно.», «… Бодит байршлыг батлахгүй.» read like the table talking about itself. The same
# facts, said the way a person at the desk says them; no value is added or changed.
_NATURAL = (
    (r'(?P<group>\S+) — бүртгэсэн үндсэн өрөө: (?P<room>[^.\s]+)\. Тухайн хичээлийн өрөө хуваариар өөр байж болно\.',
     r'\g<group> анги ихэвчлэн \g<room> тоот өрөөнд хичээллэдэг. Зарим хичээл өөр өрөөнд орж болно.'),
    (r' — бүртгэлд заасан ангийн багш: ', ' ангийн багш: '),
    (r' — бүртгэлд заасан ажлын өрөө: ', ' — ажлын өрөө: '),
    (r' — бүртгэлд заасан (хариуцагч|ажилтан): ', r' — \1: '),
    (r' — бүртгэсэн (хуваарийн хичээлийн цаг|долоо хоногийн хуваарь|хуваарьт заадаг хичээл|уулзах цаг): ', r' — \1: '),
    (r'(?<![А-Яа-яӨөҮүЁё])бүртгэсэн (хуваарь|хичээл|амралтын)', r'\1'),
    (r'\s*Уулзах цаг хүснэгтэд бүртгэгдээгүй тул өрөөндөө байгааг батлахгүй\.', ' Яг одоо өрөөндөө байгаа эсэхийг мэдэх боломжгүй.'),
    (r'\s*Одоо тэнд байгааг батлахгүй\.', ' Яг одоо өрөөндөө байгаа эсэхийг мэдэх боломжгүй.'),
    # A teacher's lessons are the schedule, not where the teacher is now (CLAUDE.md, reception rule): the
    # caveat stays, in plain words (code review 11/23).
    (r'; өрөөндөө байгааг батлахгүй\.', '. Яг одоо хаана байгааг мэдэх боломжгүй.'),
    (r'; бодит байршлыг батлахгүй\.', '. Яг одоо хаана байгааг мэдэх боломжгүй.'),
    (r'\s*Бодит байршлыг батлахгүй\.', ' Яг одоо хаана байгааг мэдэх боломжгүй.'),
    (r'\s*Бодит байдлыг батлахгүй\.', ''),  # room answers already say «хуваариар»; a room is not a person
    (r'\s*Тэр цагт ирсэн эсэх, байршлыг батлахгүй\.', ' Тэр цагт өрөөндөө байгаа эсэхийг мэдэх боломжгүй.'),
    (r'\s*Тэнхимийн ганц төв байр гэж батлахгүй\.', ''),
    (r'\s*Албадын цайны цаг хүснэгтэд бүртгэгдээгүй\.', ''),
    (r'Ажлын цаг хүснэгтэд бүртгэгдээгүй\.', 'Ажлын цагийн мэдээлэл алга.'),
    (r'Ресепшний хуваарийн хүснэгтэд бүртгэсэн', 'Хуваарьт заасан'),
    (r'Ресепшний хуваарийн хүснэгтээр', 'Хуваариар'),
    (r'Ресепшний хуанлид', 'Хуанлид'),
    (r'\AБүртгэлд: ', ''),
    (r'Хуваарь өөрчлөгдсөн байж болно', 'Хуваарь өөрчлөгдөж болно'),
)


def natural(answer):
    """The reception answer in plain words (see _NATURAL); None and other values pass through."""
    if not isinstance(answer, str):
        return answer
    for pattern, replacement in _NATURAL:
        answer = re.sub(pattern, replacement, answer)
    return re.sub(r'\s{2,}', ' ', answer).strip()


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
    school_hours: str = ''   # the school's general hours, confirmed by the user (config ``corrections``)
    lunch_break: str = ''    # the school's lunch break, confirmed by the user (2026-11-20)


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


_HOURS_RANGE = re.compile(r'\d{2}:\d{2}[–-]\d{2}:\d{2}')


def _range_minutes(text):
    """«08:00–17:00» -> (480, 1020); None for anything else, an impossible time included (code review 11/26)."""
    if not isinstance(text, str) or not _HOURS_RANGE.fullmatch(text.strip()):
        return None
    try:
        start, end = (_minutes(part) for part in re.split(r'[–-]', text.strip()))
    except ReceptionDataError:
        return None
    return (start, end) if start < end else None
# Working, opening and closing ask the same hours. Taking payments or papers («төлбөр авдаг») is not confirmed
# to follow the working hours and is left out (review, round 25).
_OPEN_VERB = r'(?:ажилладаг|нээдэг|нээгддэг|онгойдог|хаадаг|хаагддаг|нээлттэй(?: байдаг)?)'
# The school's own working hours, with or without naming it (at the desk «Хэдэн цагт ажилладаг вэ?» asks about
# the school): open, close, from, until. A named office, a day («бямба гарагт …») or a lesson time is not this.
_SCHOOL_HOURS = re.compile(
    r'(?:(?:(?:(?:манай|танай|энэ) )?(?:сургууль|сургуулийн|коллеж(?:ийн)?|шмтк(?:-?ийн)?)|танай|танайх|та нар) )?'
    r'(?:(?:хэдэн цагт|хэдэн цагаас(?: хэдэн цаг хүртэл)?|хэдэн цаг хүртэл|хэдээс хэд хүртэл|хэдээс) '
    + _OPEN_VERB + r'|(?:ерөнхий )?ажлын цаг (?:хэд|хэдэн|ямар))(?: (?:вэ|бэ))?')
# 11/22: «Сургууль ням гарагт ажилладаг уу?» reached the website's old hours (09:00–18:00, Бямба 10:00–14:00),
# which the confirmed 08:00–17:00 replaces; weekend hours were not confirmed, so the reply says only that.
_WEEKEND_HOURS = re.compile(
    r'(?:(?:(?:манай|танай|энэ) )?(?:сургууль|сургуулийн|коллеж(?:ийн)?|шмтк(?:-?ийн)?|танай|танайх) )?'
    r'(?:бямба|ням|бямба ням|амралтын өдөр)(?: (?:гарагт|гараг|гарагууд|өдөр|өдрүүдэд|өдөрт))? '
    r'(?:ажилладаг уу|ажиллах уу|ажилладаг юу|нээлттэй юу|нээлттэй байдаг уу|амардаг уу|хэдэн цагт ажилладаг|'
    r'хэдэн цагаас ажилладаг|хэдэн цаг хүртэл ажилладаг)(?: (?:вэ|бэ))?')
# 2026-11-20: the user confirmed that the school's lunch break is always 12:40–13:20. With that value set a bare
# «цайны цаг» is answered as well; without it only the timetable's midday gap is (round 25). Whether an office
# serves through the break was not said, so «… цайны цагаар ажилладаг уу?» is not matched.
_LUNCH_BREAK = re.compile(
    r'(?:(?:(?:(?:манай|танай|энэ) )?(?:сургууль|сургуулийн|коллеж(?:ийн)?|шмтк(?:-?ийн)?)|танай|албадын|ажилчдын'
    r'|ажилтнуудын|багш нарын|оюутны|оюутнуудын|хичээлийн) )?'
    r'(?:(?:(?:өдрийн|үдийн) )?(?:цайны цаг|цайны завсарлага)|(?:өдрийн|үдийн) завсарлага|их завсарлага)'
    r'(?: (?:хэдээс хэд хүртэл|хэдэн цагаас хэдэн цаг хүртэл|хэдэн цагт|хэдэн цагаас|хэдээс|хэзээ|хэд))?'
    r'(?: (?:байдаг|болдог|эхэлдэг))?(?: (?:вэ|бэ))?')


_OFFICE_NOTES = ('office_weekend', 'office_lunch', 'office_payment_hours')
# A person named with the initial («Б.Сэлмаа», «А.Номин-Эрдэнэ»); question_planner.py reads the same pattern.
PERSON_NAME = r'([А-ЯӨҮЁ]\.\s?[А-ЯӨҮЁа-яөүё][а-яөүё-]{2,})'
# What a completed answer says once, at its end (see ReceptionAnswerPath._completed).
_CAVEATS = ('Хуваарь өөрчлөгдөж болно.', 'Яг одоо өрөөндөө байгаа эсэхийг мэдэх боломжгүй.',
            'Яг одоо хаана байгааг мэдэх боломжгүй.')


def _corrected(tables, corrections):
    """The imported tables with the facts the user confirmed with the school after the import (config
    ``corrections``, 2026-11-18): they stay when a new timetable is imported. ``office_hours`` gives the common
    hours to services whose name holds a word and whose own hours are not recorded; ``staff_room_by_role`` moves
    the holders of a post to a recorded room; ``school_hours`` (2026-11-19) is the school's general hours, said
    in place of the website's contact page. Anything malformed rejects the whole dataset."""
    if corrections is None:
        return tables
    if (not isinstance(corrections, dict)
            or set(corrections) - {'note_mn', 'office_hours', 'staff_room_by_role', 'school_hours', 'lunch_break'}):
        raise ReceptionDataError('Reception corrections have an unknown shape.')
    rooms, staff = tables.rooms, tables.staff
    school = corrections.get('school_hours', '')
    if not isinstance(school, str) or school and not _HOURS_RANGE.fullmatch(school):
        raise ReceptionDataError('The school hours must be HH:MM–HH:MM.')
    lunch = corrections.get('lunch_break', '')
    if not isinstance(lunch, str) or lunch and not _HOURS_RANGE.fullmatch(lunch):
        raise ReceptionDataError('The lunch break must be HH:MM–HH:MM.')
    hours = corrections.get('office_hours')
    if hours is not None:
        if (not isinstance(hours, dict) or set(hours) != {'name_contains', 'hours'}
                or not all(isinstance(hours[key], str) and hours[key].strip() for key in hours)
                or not _HOURS_RANGE.fullmatch(hours['hours'])):
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
    return replace(tables, rooms=rooms, staff=staff, school_hours=school, lunch_break=lunch)


class ReceptionAnswerPath:
    """Exact-name, closed-intent reception lookup. Disabled unless configured."""
    def __init__(self, tables=None, *, enabled=False, error=None, complete=False):
        self.tables, self.enabled, self.error = tables, enabled is True, error
        self._subjects = {}   # _subject_teachers by asked value: one timetable scan per question (review)
        # 11/25: an answer about a person, an office, a room or a class also says the other recorded facts a
        # visitor needs (post, room, school e-mail, lessons today): config ``complete_answers``.
        self.complete = complete is True

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
                is_fake=value.get('is_fake', False)), value.get('corrections')), enabled=True,
                complete=value.get('complete_answers') is True)
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
        return dict(query=query, answer=natural(answer), reason_code=reason, message=messages.get(reason, ''),
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
            # 11/23 (2): «Сургалтын алба бямба гарагт ажилладаг уу?», «… цайны цагаар ажилладаг уу?», «Санхүүгийн алба
            # хэдэн цаг хүртэл төлбөр авдаг вэ?» reached the FAQ router's «…хадгалсан асуулт алга. Тааж нэгтгэхгүй.»
            # Only the weekday hours are confirmed: a note with those hours and what is not known (office_note).
            ('office_weekend', r'(.{1,120}?) (?:бямба|ням|бямба,? ням|амралтын)(?: (?:гар[аи]гт|гар[аи]г|өдөр|өдөрт|өдрүүдэд))? '
                               r'(?:(?:хэдэн цагт|хэдэн цагаас|хэдэн цаг хүртэл) )?(?:ажилладаг|ажиллах|нээлттэй(?: байдаг)?|'
                               r'үйлчилдэг) (?:уу|юу|үү|вэ|бэ)'),
            ('office_lunch', r'(.{1,120}?) (?:(?:өдрийн|үдийн) )?(?:цайны цаг(?:аар|т)|цайны завсарлагаар) '
                             r'(?:ажилладаг|ажиллах|нээлттэй(?: байдаг)?|үйлчилдэг|үйлчлэх) (?:уу|юу|үү)'),
            ('office_payment_hours', r'(.{1,120}?) (?:хэдэн цаг хүртэл|хэдэн цагаас(?: хэдэн цаг хүртэл)?|хэдэн цагт|'
                                     r'хэдээс хэд хүртэл) (?:төлбөр|мөнгө)(?: хүлээн)? (?:авдаг|авах|төлүүлдэг) (?:вэ|бэ)'),
            # 11/18: with the offices' hours recorded, the other wordings of the same question too.
            # Round 25: opening and closing are the same hours («Сургалтын алба хэдэн цагт хаадаг вэ?»).
            ('office_hours', r'(.{1,120}?) (?:хэдэн цагт|хэдэн цагаас(?: хэдэн цаг хүртэл)?|хэдэн цаг хүртэл|хэдээс хэд хүртэл) '
                             + _OPEN_VERB + r' вэ'),
            ('office_hours', r'(.{1,120}?)(?:гийн|ны|ийн|ын) ажлын цаг (?:хэд|хэдэн|ямар)(?: вэ)?'),
            # A department's contact is its head (department_contact below), not an office's.
            ('office_contact', r'(?!.*тэнхим)(.{1,120}?)(?:тай|тэй|той) (?:яаж|хэрхэн) холбогдох (?:вэ|бэ)'),
            # 11/23 (check set Q38): «Химийн инженерийн тэнхимийн багш нар хаана суудаг вэ?» — the department's
            # teachers' room, like «… тэнхимийн багш нарын өрөө хаана вэ?».
            ('department', r'(.{1,120}?) тэнхим(?:ийн (?:байр|өрөө|багш(?:ийн| нар(?:ын)?)?(?: (?:ажлын )?өрөө)?))? хаана '
                           r'(?:байдаг |байна |байрладаг )?вэ'),
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
            # 11/23: «Захирлын утасны дугаар хэд вэ?» got «мэдээлэл олдсонгүй»; parents ask the reception for a
            # phone and get the school e-mail (reception topic 2). Only a recorded post holder answers here.
            # Lazy so that «гар» stays out of the post («Захирлын гар утас …», code review 11/23).
            ('post_phone', r'((?:[^\s?!,;/]+ ){0,2}?[^\s?!,;/]{3,40}?) (?:гар )?утас(?:ны дугаар)?(?: (?:юу|хэд|ямар) (?:вэ|бэ))?'),
            # 11/17: a class teacher's school e-mail; before teacher_email, which would read
            # «КУ-2 ангийн» as a person's name.
            ('class_teacher_email', r'(.{1,120}?) ангийн багшийн (?:и-?мэйл|имэйл|мэйл|цахим шуудан)(?:ийн)?(?: хаяг)?'
                                    r'(?: (?:юу|хэд|ямар) (?:вэ|бэ))?'),
            # Round 9: the class teacher's recorded office; before teacher_room and the legacy
            # teacher lookup, which read «КУ-2 ангийн» as a person's name («багш олдсонгүй»).
            ('class_teacher_room', r'(.{1,120}?) ангийн багш(?:ийн (?:ажлын )?өрөө)? хаана (?:байдаг |байна )?вэ'),
            # 11/25: «КУ-2 анги одоо хаана байна вэ?» (the planner's wording): the lesson in progress and the next one.
            ('class_now', r'(.{1,120}?) анги одоо хаана хичээлтэй вэ'),
            ('class_day', r'(.{1,120}?) анги(?:йн)? (?:(даваа|мягмар|лхагва|пүрэв|баасан|бямба|ням) гарагт|'
                          r'(өнөөдөр|маргааш)) хэдэн цагт хичээлтэй вэ'),
            # 11/23 (check set Q36): a class code alone, without «анги» («КУ-4 мягмар гарагт хэдэн цагаас хичээлтэй вэ?»).
            ('class_day', r'([А-ЯӨҮЁ]{2,3}-\d) (?:(даваа|мягмар|лхагва|пүрэв|баасан|бямба|ням) гарагт|'
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
            # Round 25: «Сургууль хэдэн цагт тардаг вэ?», «Сүүлийн цаг хэдэн цагт дуусдаг вэ?» ask the same. The first
            # lesson only with its start and the last only with its end: that is what the answer gives (review).
            ('bell_schedule', r'(?:хичээл(?:үүд)?|сургууль) (?:хэдэн цаг(?:т|аас)|хэдэн цаг хүртэл|хэдээс) '
                              r'(эхэл\w*|эхл\w*|дуус\w*|тар\w*|ордог)(?: вэ)?'),
            ('bell_schedule', r'эхний (?:цаг|хичээл|пар) (?:хэдэн цаг(?:т|аас)|хэдээс) (эхэл\w*|эхл\w*)(?: вэ)?'),
            ('bell_schedule', r'(?:сүүлийн|сүүлчийн) (?:цаг|хичээл|пар) (?:хэдэн цагт|хэдэн цаг хүртэл) (дуус\w*|тар\w*)(?: вэ)?'),
            # Round 25: the midday break between lessons, read from the timetable. Only when the question says
            # midday, long or lessons: a bare «цайны цаг» at the desk may ask when the staff are away, which is
            # not recorded, and a bare «завсарлага» may be the short breaks (review).
            ('lunch_break', r'((?:өдрийн|үдийн) (?:цайны цаг|цайны завсарлага|завсарлага)|их завсарлага'
                            r'|(?:хичээлийн|оюутны|оюутнуудын) (?:(?:өдрийн|үдийн) )?(?:цайны цаг|цайны завсарлага)) '
                            r'(?:хэдээс хэд хүртэл|хэдэн цагаас хэдэн цаг хүртэл|хэдэн цагт|хэдэн цагаас|хэзээ)'
                            r'(?: (?:байдаг|болдог|эхэлдэг))?(?: вэ)?'),
            # Round 9: «Хичээлийн хуваарь хаанаас харах вэ?» — the class timetable is shown here, by class.
            ('timetable_where', r'(?:хичээлийн |ангийн )?хуваар\w* (?:хаанаас|хаана) (харах|үзэх|олох|харж болох)(?: вэ)?'),
            # 11/25: «Н.Соронзонболд багш гэж хэн бэ?», «… багшийн талаар хэлж өгөөч», or the name alone — who the
            # person is (post, room, school e-mail, lessons); «… гэж хэн бэ?» reached «Асуусан хүний нэр олдсонгүй».
            # Only a name written with its initial (the planner adds it), so «Математикийн багш хэн бэ?» stays a
            # subject question.
            ('person_about', PERSON_NAME + r'(?: багш)?(?: гэж)? (?:хэн|ямар хүн) (?:бэ|вэ)'),
            ('person_about', PERSON_NAME + r' багш(?:ийн|ийг)? (?:талаар|тухай|танилцуул\w*)(?: [^?!,;/]{0,60})?'),
            ('person_about', PERSON_NAME + r'(?: багш)?'),
            # Round 12: «Б.Сэлмаа багш ямар хичээл заадаг вэ?» — the subjects in the published timetable.
            ('teacher_subjects', r'(.{1,120}?) багш (?:(?:ямар(?: ямар)?|юу) хичээл (?:заадаг|ордог|заах|орох)|юу заадаг) (?:вэ|бэ)'),
            ('teacher_email', r'(.{1,120}?) багшийн (?:и-?мэйл|имэйл|мэйл|цахим шуудан)(?:ийн)?(?: хаяг)?(?: (?:юу|хэд|ямар) (?:вэ|бэ))?'),
            ('teacher_room', r'(.{1,120}?) багшийн өрөө хаана (?:байдаг |байна )?вэ'),
            ('teacher_hours', r'(.{1,120}?) багш хэзээ оюутантай уулздаг вэ'),
            # 11/25: «… багштай яаж уулзах вэ?» — where the teacher sits, the timetable now, how to arrange it.
            ('teacher_meet', r'(.{1,120}?) багштай (?:(?:яаж|хэрхэн|хаана|хэзээ|одоо) )?уулз(?:ах|аж болох|аж болно) (?:вэ|бэ|уу)'),
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
            # 11/25: «Сэтгэл зүйчтэй яаж уулзах вэ?», «Захиралтай хаана уулзах вэ?» ask the same.
            ('role_meet', r'(.{1,120}?)(?:тай|тэй|той) (?:одоо )?(?:уулз(?:аж|ах) (?:болох|болно) уу|уулзах гэсэн(?: юм)?|'
                          r'уулзмаар байна|уулзъя|(?:яаж|хэрхэн|хаана|хэзээ) уулз(?:ах|даг) (?:вэ|бэ))'),
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
                    if re.search(r'\b(?:болон|ба|мөн|эсвэл|and|or)\b|[;?!/]'
                                 + ('' if intent.startswith('office_') or intent in ('place_where', 'place_exists') else '|,'),
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
        if self._asks_lunch_break(query) or self._asks_school_hours(query) or self._asks_weekend_hours(query):
            return True
        extra = self._extra_match(query)
        if extra is not None and extra[0] == 'person_about':
            # Only a person in the staff table; another name goes on to the website's teacher introductions.
            return self._staff_named(extra[1]) is not None
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
        if extra is not None and extra[0] == 'office_hours':
            # Claimed only when the tables answer it (an office, a post); «Гал тогоо хэдэн цагт нээдэг вэ?» goes
            # on to the other paths (review, round 25).
            return any(self._match(query)) or self.answer(query) is not None
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
        if extra is not None and extra[0] == 'post_phone':
            return self._post_holder(extra[1]) is not None
        if extra is not None and extra[0] in _OFFICE_NOTES:
            return self._service(extra[1]) is not None
        return any(self._match(query)) or extra is not None

    def _room_of(self, person):
        """The recorded room row of a staff member, or None."""
        if person is None or not person.room:
            return None
        return next((room for room in self.tables.rooms if _key(room.name) == _key(person.room)), None)

    def _school_window(self):
        """The school's confirmed working hours in minutes («08:00–17:00», config ``corrections``), or None."""
        return _range_minutes(self.tables.school_hours)

    def _next_school_day(self, after, now):
        """The first day after ``after`` the timetable applies to (a weekday in the term, not a recorded holiday), or None
        when the term ends first or the calendar cannot tell."""
        for offset in range(1, 22):
            day = after + timedelta(days=offset)
            if day.weekday() >= 5:
                continue
            reason = self._calendar_reason(now, day)
            if reason is None:
                return day
            if reason != 'reception_holiday':
                return None
        return None

    def _teacher_schedule(self, person, now):
        """«Хуваариар өнөөдөр (баасан, 11/27): хичээлтэй — 08:00–09:30 КУ-2 (402 тоот); хичээлгүй — 09:30–17:00.» — the
        day a visitor can still meet ``person``: today from now while the school day lasts, else the next school day,
        with a sentence why («Өнөөдөр бүртгэсэн амралтын өдөр.»). Free stretches only within the confirmed school hours,
        30 minutes or longer, with the lunch break named when one falls in them (11/26, the user: «уулзах цаг …
        хуваариас шүүгээд хичээлтэй үгүй юу гэдгийг хар»). None without a clock, for staff with no lessons, with a
        partial timetable or when the calendar cannot tell. Never says where the person is."""
        if (self.tables is None or not isinstance(now, datetime) or not self.tables.timetable_complete
                or not any(_key(lesson.teacher) == _key(person.name) for lesson in self.tables.timetable)):
            return None
        window = self._school_window()
        if window is None:
            return None       # without the school's confirmed hours neither «today from now» nor «free» can be told
        today, minute = now.date(), now.hour * 60 + now.minute
        reason = self._calendar_reason(now)
        if reason not in (None, 'reception_holiday'):
            return None
        intro = ''
        if reason is None and today.weekday() < 5 and minute < window[1]:
            day = today
            start = max(minute, window[0])
            label = 'өнөөдөр (' + _MN_DAYS[day.weekday()] + ', ' + day.strftime('%m/%d') + ')'
            if minute > window[0]:
                label += ', ' + _clock(minute) + '-аас хойш'
        else:
            if reason == 'reception_holiday':
                intro = 'Өнөөдөр бүртгэсэн амралтын өдөр. '
            elif today.weekday() >= 5:
                intro = 'Өнөөдөр ' + _MN_DAYS[today.weekday()] + ' гараг. '
            else:
                intro = 'Өнөөдрийн ажлын цаг (' + self.tables.school_hours + ') дууссан. '
            day = self._next_school_day(today, now)
            if day is None:
                end = self.tables.term_end
                return intro + ('Энэ улирлын хуваарь ' + end.isoformat() + '-нд дууссан; ' if end else '') + \
                    'дараагийн хичээлийн өдрийн хуваарь бүртгэгдээгүй.'
            start = window[0]
            label = 'дараагийн хичээлийн өдөр — ' + _MN_DAYS[day.weekday()] + ' (' + day.strftime('%m/%d') + ')'
        slots = {}
        for lesson in self.tables.timetable:
            if _key(lesson.teacher) == _key(person.name) and lesson.day == _DAYS[day.weekday()]:
                slot = slots.setdefault(lesson.interval, dict(groups=[], rooms=[]))
                for field, value in (('groups', lesson.group), ('rooms', lesson.room)):
                    if value and value not in slot[field]:
                        slot[field].append(value)
        busy = [(span, slot) for span, slot in sorted(slots.items()) if span[1] > start]
        if not busy:
            return intro + 'Хуваариар ' + label + ' хичээлгүй.'
        text = intro + 'Хуваариар ' + label + ': хичээлтэй — ' + '; '.join(
            _clock(span[0]) + '–' + _clock(span[1]) + ' ' + ', '.join(slot['groups'])
            + (' (' + ', '.join(slot['rooms']) + ' тоот)' if slot['rooms'] else '') for span, slot in busy)
        if window:     # always set here; kept as one block with its lunch note
            free, cursor = [], start
            for (begin, end), _ in busy:
                if min(begin, window[1]) - cursor >= 30:
                    free.append((cursor, min(begin, window[1])))
                cursor = max(cursor, end)
            if window[1] - cursor >= 30:
                free.append((cursor, window[1]))
            if free:
                text += '; хичээлгүй — ' + ', '.join(_clock(begin) + '–' + _clock(end) for begin, end in free)
                lunch = _range_minutes(self.tables.lunch_break)
                if lunch and any(begin < lunch[1] and lunch[0] < end for begin, end in free):
                    text += ' (сургуулийн цайны цаг ' + self.tables.lunch_break + ')'
        return text + '.'

    def _schedule_reply(self, query, person, schedule, prefix=''):
        """A teacher asked about outside the school day: the person, the office and the day a visitor can come."""
        # What was asked (in class? where?) first, then who and where the office is (CLAUDE.md 11/25 (2)).
        text = (prefix + person.name + ' — ' + schedule[:1].lower() + schedule[1:]
                + (' Албан тушаал: ' + person.role + '.' if person.role else '') + self._workplace(person)
                + ' Хуваарь өөрчлөгдөж болно; өрөөндөө байгааг батлахгүй.'
                + (' Сургуулийн имэйл: ' + person.email + '.' if person.email else ''))
        return self._result(query, text, 'reception_teacher_schedule', source_table='timetable')

    def _workplace(self, person):
        """« Ажлын өрөө: 508 тоот, 5-р давхар.» from the rooms table, or nothing."""
        room = self._room_of(person)
        return (' Ажлын өрөө: ' + room.name + ' тоот, ' + floor_text(room.floor) + '.') if room else ''

    @staticmethod
    def _office_text(service, room):
        """«Сургалтын алба: 4-р давхар, 406 тоот. Ажлын цаг 08:00–17:00.» — where and, when the school
        confirmed it, when (the user asked on 11/20 that office answers say the hours too)."""
        return (service.name + ': ' + floor_text(room.floor) + ', ' + room.name + ' тоот.'
                + (' Ажлын цаг ' + service.office_hours + '.' if _recorded(service.office_hours) else ''))

    def _office_note(self, query, intent, service, room, prefix):
        """An office's weekend, lunch-break or payment hours: the confirmed weekday hours and the place, then what is
        not known — a note to read with the referral, not an answer (11/23 (2))."""
        hours = (service.name + ' ' + service.office_hours + ' цагийн хооронд ажилладаг (' + floor_text(room.floor)
                 + ', ' + room.name + ' тоот). ') if _recorded(service.office_hours) else ''
        if intent == 'office_weekend':
            unknown = 'Бямба, ням гарагийн ажлын цагийн мэдээлэл алга.' if hours else 'Ажлын цагийн мэдээлэл алга.'
        elif intent == 'office_lunch':
            unknown = (('Сургуулийн цайны цаг ' + self.tables.lunch_break + '. ') if self.tables.lunch_break else '') + \
                      'Цайны цагаар ажилладаг эсэх мэдээлэл алга.'
        else:
            unknown = 'Төлбөр хүлээн авах цагийн тусгай мэдээлэл алга.'
        result = self._result(query, None, 'reception_office_note', source_table='rooms')
        result['message'] = prefix + hours + unknown
        return result

    def _post_room(self, person):
        """«Захирал (Т.Оюунжаргал): 508 өрөө, 5-р давхар.» for a post holder with a recorded room."""
        room = self._room_of(person)
        return (person.role + ' (' + person.name + '): ' + floor_text(room.floor) + ', ' + room.name + ' тоот.'
                + ' Яг одоо өрөөндөө байгаа эсэхийг мэдэх боломжгүй.')

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
        if not found and len(words) >= 2:
            # 11/26: «гагнуурын лаборатори» is «Туршилтын өрөө/Гагнуур лаб» — each part of a joined purpose, «лаб» as
            # «лаборатори», a genitive ending aside; two words or more, so «лаборатори» alone names none.
            def plain(text):
                return [re.sub(r'(?:ийн|ын|ний|ны)$', '', 'лаборатори' if word == 'лаб' else word)
                        for word in re.findall(r'[а-яөүё]+', _key(text))]
            asked = plain(value)
            found = [room for room in self.tables.rooms
                     if any(plain(part)[-len(asked):] == asked for part in (room.purpose or '').split('/'))]
        # Round 19: «Багш нарын өрөө хаана вэ?» — seven rooms, most of them a department's; up to eight when
        # the rooms name at least two departments, which then tell them apart («Анги» names none).
        return (found if 1 <= len(found) <= 3 or len(found) <= 8 and len({room.department for room in found if room.department}) >= 2
                and sum(not room.department for room in found) <= 1 else [])

    def _purpose_reply(self, rooms):
        # Rooms grouped under their own recorded purpose («Гадаад хэлний кабинет», «Хэлний кабинет»).
        groups = {}
        labelled = len({room.department for room in rooms}) > 1
        for room in rooms:
            groups.setdefault(room.purpose, []).append(floor_text(room.floor) + ', ' + room.name + ' тоот'
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
                # A word of four letters or fewer is compared whole: «Болд» cut to «бол» opened «Боловсрол»
                # and «Боловсруулалт», and a stranger's name listed those subjects' teachers (11/25).
                stems.append(stem[:max(3, len(stem) - 1)] if len(stem) > 4 else stem)
        if not stems or len(stems) > 4:
            return {}
        found = {}
        for lesson in self.tables.timetable:
            words = re.findall(r'[а-яөүёa-z]+', _key(lesson.subject))
            # A word of four letters or fewer may take only an ending (up to three letters): «хими» → «химийн», but
            # «мате» is not «математик» and a stranger's name does not open a subject (11/25).
            if lesson.subject and lesson.teacher and all(
                    any(word.startswith(stem) and (len(stem) > 4 or len(word) - len(stem) <= 3) for word in words)
                    for stem in stems):
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

    @staticmethod
    def _slot_gaps(slots, common):
        """(minutes, earlier, later) between the shared lesson times that follow each other; two shift
        patterns may overlap (review, round 14)."""
        return [(slots[later][0] - slots[earlier][1], earlier, later) for earlier, later in zip(common, common[1:])
                if slots[later][0] >= slots[earlier][1]]

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

    def _asks_school_hours(self, query):
        """The school's general hours are asked and the user-confirmed value is set (round 24)."""
        if self.tables is None or not self.tables.school_hours or not isinstance(query, str) or len(query) > 200:
            return False
        text = normalize_wording(query.strip().rstrip('?!？.').strip()).casefold()
        return _SCHOOL_HOURS.fullmatch(' '.join(text.split())) is not None

    def _asks_weekend_hours(self, query):
        """Saturday/Sunday hours are asked and the school's confirmed weekday hours are set (11/22)."""
        if self.tables is None or not self.tables.school_hours or not isinstance(query, str) or len(query) > 200:
            return False
        text = normalize_wording(query.strip().rstrip('?!？.').strip()).casefold()
        return _WEEKEND_HOURS.fullmatch(' '.join(text.split())) is not None

    def _asks_lunch_break(self, query):
        """The lunch break is asked and the user-confirmed value is set (2026-11-20)."""
        if self.tables is None or not self.tables.lunch_break or not isinstance(query, str) or len(query) > 200:
            return False
        text = normalize_wording(query.strip().rstrip('?!？.').strip()).casefold()
        return _LUNCH_BREAK.fullmatch(' '.join(text.split())) is not None

    # -- complete answers (11/25) ------------------------------------------------------------------
    # The user's example: «Соронзонболд багш гэж хэн бэ, хаана байдаг вэ?» was answered with the room alone, though
    # the tables also hold the post, the school e-mail and the lessons. A person at the desk would say all of it,
    # so the answer to what was asked comes first and the other recorded facts follow, one per line.
    @staticmethod
    def _role_text(person):
        """«Компьютерын ухааны тэнхимийн эрхлэгч», «Математикийн багш (Ерөнхий эрдмийн тэнхим)»."""
        role = re.sub(r'\s*\(хуваариас\)', '', person.role or '').strip()
        unit = (person.department or '').strip()
        if not role:
            return unit
        if unit and _key(unit) not in _key(role):
            return role + ' (' + unit + ')'
        return role

    def _class_groups_of(self, person):
        return [group.group for group in self.tables.classes if group.teacher and _key(group.teacher) == _key(person.name)]

    def _taught(self, person):
        """{subject: class groups} this person teaches in the stored timetable."""
        taught = {}
        for lesson in self.tables.timetable:
            if lesson.subject and _key(lesson.teacher) == _key(person.name):
                taught.setdefault(lesson.subject, set()).add(lesson.group)
        return taught

    def _today(self, now):
        """Today's weekday number when the stored timetable applies today, else None (no clock, a holiday,
        outside the term)."""
        if not isinstance(now, datetime) or not self.tables.timetable or self._calendar_reason(now):
            return None
        return now.weekday()

    def _day_lessons(self, weekday, *, teacher=None, group=None, room=None):
        """One day's lessons of a teacher, a class or a room in time order, a joint lesson once:
        «09:35-11:05 Алгоритмын үндэс (КУ-1; 612 тоот)»."""
        slots = {}
        for lesson in self.tables.timetable:
            if (lesson.day != _DAYS[weekday] or teacher is not None and _key(lesson.teacher) != _key(teacher)
                    or group is not None and _key(lesson.group) != _key(group)
                    or room is not None and _key(lesson.room) != _key(room)):
                continue
            slot = slots.setdefault((lesson.interval, lesson.time, lesson.subject), dict(groups=[], rooms=[], teachers=[]))
            for field, value in (('groups', lesson.group), ('rooms', lesson.room), ('teachers', lesson.teacher)):
                if value and value not in slot[field]:
                    slot[field].append(value)
        lines = []
        for (_, time_text, subject), slot in sorted(slots.items(), key=lambda item: item[0][0]):
            details = []
            if group is None and slot['groups']:
                details.append(', '.join(slot['groups'][:4]) + (', …' if len(slot['groups']) > 4 else ''))
            if room is None and slot['rooms']:
                details.append(', '.join(slot['rooms'][:4]) + ' тоот')
            if teacher is None and slot['teachers']:
                details.append(', '.join(slot['teachers'][:3]) + (', …' if len(slot['teachers']) > 3 else ''))
            lines.append(time_text + (' ' + subject if subject else '') + (' (' + '; '.join(details) + ')' if details else ''))
        return lines

    def _person_lines(self, person, now, *, role=True, room=True, email=True, groups=True, subjects=True, today=True):
        """The recorded facts about a staff member, one «Нэр: утга» line each; only what the tables hold."""
        lines = []
        if role and self._role_text(person):
            lines.append('Албан тушаал: ' + self._role_text(person))
        place = self._room_of(person)
        if room and place is not None:
            lines.append('Ажлын өрөө: ' + place.name + ' тоот, ' + floor_text(place.floor))
        if email and person.email:
            lines.append('Сургуулийн имэйл: ' + person.email)
        own = self._class_groups_of(person)
        if groups and own:
            lines.append('Ангийн багш: ' + ', '.join(own) + ' анги')
        taught = self._taught(person)
        if subjects and taught:
            shown = sorted(taught.items())
            lines.append('Заадаг хичээл: ' + '; '.join(
                subject + ' (' + ', '.join(sorted(names)[:4]) + (', …' if len(names) > 4 else '') + ')'
                for subject, names in shown[:8]) + (' гэх мэт ' + str(len(shown)) + ' хичээл' if len(shown) > 8 else ''))
        weekday = self._today(now) if today else None
        if weekday is not None and taught:
            lessons = self._day_lessons(weekday, teacher=person.name)
            if lessons:
                lines.append('Өнөөдрийн хичээл (' + _MN_DAYS[weekday] + '): ' + '; '.join(lessons))
            elif self.tables.timetable_complete:
                lines.append('Өнөөдөр (' + _MN_DAYS[weekday] + '): хуваарьт хичээлгүй')
        return lines

    def _person_contact(self, person):
        """«<нэр> (<өрөө> тоот, <давхар>; <сургуулийн имэйл>)» — a person with where to find them."""
        place = self._room_of(person)
        details = ([place.name + ' тоот, ' + floor_text(place.floor)] if place is not None else []) + (
            [person.email] if person.email else [])
        return person.name + (' (' + '; '.join(details) + ')' if details else '')

    def _office_lines(self, room, service):
        """The staff the table records for an office, with post and school e-mail."""
        people = [person for person in self.tables.staff if _key(person.department) == _key(service.name)]
        if not people:
            return []
        return ['Ажилтнууд:'] + ['• ' + person.name + ' — ' + (re.sub(r'\s*\(хуваариас\)', '', person.role) or 'ажилтан')
                                 + (', ' + person.email if person.email else '') for person in people[:8]]

    def _room_lines(self, room, now):
        """What is recorded about a room: its unit, who works there, its lessons today."""
        lines = []
        if room.department and _key(room.department) not in _key(room.purpose or ''):
            lines.append('Харьяалал: ' + room.department)
        people = [person for person in self.tables.staff if person.room and _key(person.room) == _key(room.name)]
        if people:
            lines.append('Энэ өрөөнд ажилладаг: ' + '; '.join(person.name for person in people[:10])
                         + (' гэх мэт ' + str(len(people)) + ' хүн' if len(people) > 10 else ''))
        weekday = self._today(now)
        if weekday is not None:
            lessons = self._day_lessons(weekday, room=room.name)
            if lessons:
                lines.append('Өнөөдрийн хичээл (' + _MN_DAYS[weekday] + '): ' + '; '.join(lessons))
        return lines

    def _class_lines(self, group, now, *, teacher=True, today=True):
        """A class group's teacher (with where to find them) and its lessons today."""
        lines = []
        person = self._staff_named(group.teacher) if group.teacher else None
        if teacher and group.teacher:
            lines.append('Ангийн багш: ' + (self._person_contact(person) if person is not None else group.teacher))
        weekday = self._today(now) if today else None
        if weekday is not None:
            lessons = self._day_lessons(weekday, group=group.group)
            if lessons:
                lines.append('Өнөөдрийн хичээл (' + _MN_DAYS[weekday] + '): ' + '; '.join(lessons))
            elif self.tables.timetable_complete:
                lines.append('Өнөөдөр (' + _MN_DAYS[weekday] + '): хуваарьт хичээлгүй')
        return lines

    def _department_lines(self, value):
        """A department's head and the teachers the staff table records for it."""
        heads = self._role_holders(value + ' тэнхимийн эрхлэгч', True)
        if len(heads) != 1:
            return []
        head = heads[0]
        lines = ['Тэнхимийн эрхлэгч: ' + head.name + (' (' + head.email + ')' if head.email else '')]
        others = [person.name for person in self.tables.staff
                  if _key(person.department) == _key(head.department) and person is not head]
        if others:
            lines.append('Багш нар: ' + '; '.join(others[:12]) + (' гэх мэт ' + str(len(others)) + ' хүн' if len(others) > 12 else ''))
        return lines

    def _subject_role_lines(self, value):
        """«Математикийн багш хэн бэ?»: the staff whose recorded post is that subject's teacher, with their room —
        the timetable lists only the subjects whose own name holds the asked word."""
        stems = [re.sub(r'(?:ийн|ын|ний|ны|н)$', '', word) if len(word) > 4 else word
                 for word in re.findall(r'[а-яөүёa-z]+', _key(value))]
        stems = [stem[:max(3, len(stem) - 1)] for stem in stems if len(stem) >= 3 and not stem.startswith('багш')]
        if not stems:
            return []
        roles = {}
        for person in self.tables.staff:
            words = re.findall(r'[а-яөүёa-z]+', _key(person.role))
            if 'багш' in words and all(any(word.startswith(stem) for word in words) for stem in stems):
                roles.setdefault(person.role, []).append(person)
        lines = []
        for role, people in list(roles.items())[:3]:
            rooms = [room for room in dict.fromkeys(self._room_of(person) for person in people) if room is not None]
            lines.append(role + ': ' + '; '.join(person.name for person in people[:10])
                         + (' — ажлын өрөө ' + ', '.join(room.name + ' тоот (' + floor_text(room.floor) + ')' for room in rooms[:3])
                            if rooms else ''))
        return lines

    def _completed(self, result, query, now):
        """The short answer followed by the other recorded facts about the thing it names."""
        extra = self._extra_match(query)
        intent, value = extra if extra else (None, None)
        reason, lines = result.get('reason_code'), []
        name = value[0] if isinstance(value, tuple) else value
        teacher = (self._match(query)[1] if any(self._match(query)) else None)
        person = self._staff_named(name) if isinstance(name, str) else None
        if person is None and teacher is not None:
            person = self._staff_named(teacher[1])
        if reason == 'reception_person' and person is not None:
            lines = self._person_lines(person, now, role=False)
        elif reason == 'reception_teacher_office_unrecorded' and person is not None:
            lines = self._person_lines(person, now, role=False, room=False, groups=False, subjects=False)
        elif reason == 'reception_teacher_office' and person is not None:
            lines = self._person_lines(person, now, room=False, groups=False, subjects=False)
        elif reason in ('reception_teacher_email', 'reception_teacher_phone') and person is not None:
            lines = self._person_lines(person, now, room=False, email=False, groups=False, subjects=False, today=False)
        elif reason in ('reception_teacher_subjects', 'reception_teacher_day', 'reception_teacher_day_rooms',
                        'reception_teacher_hours') and person is not None:
            lines = self._person_lines(person, now, groups=False, subjects=False, today=False)
        elif reason == 'reception_teacher_timetable' and person is not None:
            lines = self._person_lines(person, now, groups=False, subjects=False)
        elif reason == 'reception_teacher_meet' and person is not None:
            lines = self._person_lines(person, now, role=False, room=False, email=False, groups=False, subjects=False,
                                       today=not (result.get('reception') or {}).get('schedule_shown'))
        elif reason == 'reception_role_holder':
            holders = self._role_holders(name) if isinstance(name, str) else []
            if len(holders) == 1:
                lines = self._person_lines(holders[0], now, role=False, room=False, email=False, today=False)
        elif reason in ('reception_class_teacher', 'reception_class_teacher_room'):
            group = self._group_named(name) if isinstance(name, str) else None
            holder = self._staff_named(group.teacher) if group is not None and group.teacher else None
            if holder is not None:
                lines = self._person_lines(holder, now, room=reason == 'reception_class_teacher', groups=False,
                                           subjects=False, today=False)
        elif reason in ('reception_class_room', 'reception_class_day', 'reception_class_week', 'reception_class_hours',
                        'reception_class_now'):
            group = self._group_named(name) if isinstance(name, str) else None
            if group is None and isinstance(name, str):
                place = self._place(name)
                group = place[1] if place and place[0] == 'class' else None
            if group is not None:
                lines = self._class_lines(group, now, today=reason in ('reception_class_room', 'reception_class_now'))
        elif (reason in ('reception_service_lookup', 'reception_service_exists') and isinstance(name, str)
              and intent in ('place_where', 'place_exists', 'office_floor', 'office_full')):
            # Where an office is, or whether there is one: also who works there. Its hours or contact asked on
            # their own stay short («… хаана вэ, хэдэн цагт ажилладаг вэ?» listed the staff twice).
            place = self._place(name)
            found = (place[1], place[2]) if place and place[0] == 'office' else self._service(name)
            if found is not None:
                lines = self._office_lines(*found)
        elif reason == 'reception_room_lookup':
            shown = re.match(r'(?:\[[^\]]*\]\s*)?(\S+) тоот өрөө', result['answer'])
            room = next((row for row in self.tables.rooms if shown and _key(row.name) == _key(shown[1])), None)
            if room is not None:
                lines = self._room_lines(room, now)
        elif reason == 'reception_department_rooms' and isinstance(name, str):
            lines = self._department_lines(name)
        elif reason == 'reception_subject_teachers' and isinstance(name, str):
            lines = self._subject_role_lines(name)
        if not lines:
            return result
        text, closing = result['answer'], []
        for caveat in _CAVEATS:
            if caveat in text:
                text = text.replace(caveat, '').strip()
                closing.append(caveat)
        if any(line.startswith(('Өнөөдрийн хичээл', 'Заадаг хичээл')) for line in lines) and _CAVEATS[0] not in closing:
            closing.insert(0, _CAVEATS[0])
        if (any(line.startswith('Ажлын өрөө') for line in lines) or reason == 'reception_teacher_office') \
                and _CAVEATS[1] not in closing and _CAVEATS[2] not in closing:
            closing.append(_CAVEATS[1])
        result['answer'] = '\n'.join([text] + lines + ([' '.join(closing)] if closing else []))
        result['reception']['completed'] = True
        return result

    def answer(self, query, *, now=None):
        result = self._answer_core(query, now=now)
        if not self.complete or result is None or not result.get('answer') or self.tables is None:
            return result
        try:
            return self._completed(result, query, now)
        except (AttributeError, IndexError, KeyError, TypeError, ValueError):
            return result      # the short answer stands when the extra lines cannot be built

    def _answer_core(self, query, *, now=None):
        if not self.enabled:
            return None
        if self._asks_lunch_break(query):
            return self._result(query, ('[FAKE / ЗОХИОМОЛ ЖИШЭЭ] ' if self.tables.is_fake else '')
                                + 'Сургуулийн цайны цаг: ' + self.tables.lunch_break + '.',
                                'reception_lunch_break', source_table='corrections')
        if self._asks_school_hours(query):
            # Before the office answers: «Сургууль хэдэн цагаас ажилладаг вэ?» showed an entrance-exam time.
            return self._result(query, ('[FAKE / ЗОХИОМОЛ ЖИШЭЭ] ' if self.tables.is_fake else '')
                                + 'Сургуулийн ажлын цаг: ' + self.tables.school_hours + '.',
                                'reception_school_hours', source_table='corrections')
        if self._asks_weekend_hours(query):
            return self._result(query, ('[FAKE / ЗОХИОМОЛ ЖИШЭЭ] ' if self.tables.is_fake else '')
                                + 'Сургуулийн ажлын цаг: ' + self.tables.school_hours
                                + '. Бямба, ням гарагийн ажлын цагийн мэдээлэл алга.',
                                'reception_school_hours_weekend', source_table='corrections')
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
        if intent == 'person_about':
            person = self._staff_named(value)
            if person is None:
                return self._answer_legacy(query, now=now)   # not claimed (recognizes)
            # Who the person is; the room, e-mail and lessons follow in _completed.
            return reply(person.name + ' — ' + (self._role_text(person) or 'сургуулийн ажилтан') + '.', 'staff',
                         'reception_person')
        if intent in ('teacher_phone', 'class_teacher_phone'):
            owner = self._phone_owner(intent, value)
            if owner is None:
                return self._answer_legacy(query, now=now)
            person, group = owner
            text = 'Багшийн утасны дугаарыг энд өгдөггүй.'
            if person.email:
                where = self._workplace(person)
                who = (group.group + ' — бүртгэлд заасан ангийн багш: ' + group.teacher + '; сургуулийн имэйл: '
                       if group is not None else person.name + ' — сургуулийн имэйл: ')
                text += ' ' + who + person.email + '.' + where
            return reply(text, 'classes' if group is not None else 'staff',
                         'reception_class_teacher_phone' if group is not None else 'reception_teacher_phone')
        if intent == 'post_phone':
            person = self._post_holder(value)
            if person is None:
                return None  # «Сургуулийн утас …» and names nobody holds: the main path answers
            text = 'Ажилтны гар утасны дугаарыг энд өгдөггүй. ' + person.role + ' ' + person.name + '.'
            text += (' Сургуулийн имэйл: ' + person.email + '.') if person.email else ''
            # The phone itself is not answered: a note with where to reach the person, not an answer
            # (round 26b: as an answer it scored as «answered an unanswerable question», U01/O08).
            result = self._result(query, None, 'reception_post_phone', source_table='staff')
            result['message'] = prefix + text + self._workplace(person)
            return result
        if intent.startswith('department_'):
            heads = self._role_holders(value + ' тэнхимийн эрхлэгч', True)
            if len(heads) != 1:
                return self._answer_legacy(query, now=now)
            head = heads[0]
            text = ('Тэнхимийн утасны дугаарыг энд өгдөггүй. ' if intent == 'department_phone' else '')
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
                return reply('Тийм. ' + self._office_text(service, room),
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
                return reply(self._office_text(second, first),
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
            if intent in _OFFICE_NOTES:
                return self._office_note(query, intent, service, room, prefix)
            if intent in ('office_floor', 'office_full'):
                text = self._office_text(service, room)
            elif intent == 'office_hours':
                if not _recorded(service.office_hours):
                    return missing('reception_hours_unknown')
                text = (service.name + ' ' + service.office_hours + ' цагийн хооронд ажилладаг ('
                        + floor_text(room.floor) + ', ' + room.name + ' тоот).')
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
            # «… тэнхимийн багш нарын өрөө хаана вэ?» asks for that room only (W04-R08); so do «… тэнхимийн багш нар
            # хаана суудаг вэ?» and «… тэнхимийн багшийн өрөө …» (11/23, check set Q38).
            if re.search(r'тэнхимийн\s+багш', query.casefold()):
                teachers = [room for room in matches if 'багш нарын өрөө' in (room.purpose or '').casefold()]
                if teachers:
                    return reply('; '.join(room.department + 'ийн багш нарын өрөө: ' + room.name + ' тоот, '
                                           + floor_text(room.floor) for room in teachers) + '.',
                                 'rooms', 'reception_department_rooms')
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
                if result.get('reason_code') == 'reception_teacher_schedule':
                    return result
                if result['answer']:
                    # Avoid "Хуваариар бол Хуваарийн дагуу …" (same qualifier twice).
                    result['answer'] = 'Хуваариар бол ' + re.sub(r'^Хуваарийн дагуу\s*', '', result['answer'])
                return result
            if intent == 'teacher_meet':
                text = person.name + ' — ' + (person.role or 'багш') + '.' + self._workplace(person)
                schedule = self._teacher_schedule(person, now) if self.complete else None
                # Staff who teach no lesson: the timetable says nothing about them («хичээлгүй (чөлөөтэй)» read as
                # available, 11/26).
                teaches = any(_key(lesson.teacher) == _key(person.name) for lesson in self.tables.timetable)
                status = (None if schedule or (self.complete and not teaches)
                          else self._answer_legacy(value + ' багш хаана вэ?', now=now))
                if schedule:
                    text += ' ' + schedule
                elif isinstance(status, dict) and status.get('answer'):
                    # Only what the timetable says; the card ends with its own sentence about presence.
                    said = [part for part in re.split(r'(?<=[.!?])\s+', re.sub(r'^Хуваарийн дагуу\s*', '', status['answer']))
                            if not re.search(r'мэдэх боломжгүй|батлахгүй', part)]
                    if said:
                        text += ' Хуваариар бол ' + ' '.join(said)
                if _recorded(person.office_hours):
                    text += ' Бүртгэсэн уулзах цаг: ' + person.office_hours + '.'
                else:
                    # Meeting hours and presence are not recorded: never confirm them.
                    text += ' Уулзах цаг хүснэгтэд бүртгэгдээгүй тул өрөөндөө байгааг батлахгүй.'
                if person.email:
                    text += ' Уулзах цагаа сургуулийн имэйлээр тохирно уу: ' + person.email + '.'
                made = reply(text, 'staff', 'reception_teacher_meet')
                if schedule and isinstance(made.get('reception'), dict):
                    made['reception']['schedule_shown'] = True     # no second line about today (_completed)
                return made
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
                # 11/25 (sweep of every teacher): who the person is, that the office room is not recorded, and the
                # department's teachers' room as the department's; the e-mail and today's lessons follow.
                text = person.name + ' — ' + (person.role or 'багш') + '. Ажлын өрөө нь бүртгэлд алга.'
                unit = re.sub(r'\s*тэнхим\w*$', '', person.department or '', flags=re.I).strip()
                shared = next((row for row in (self._department_rooms(unit) if unit else ())
                               if 'багш нарын өрөө' in (row.purpose or '').casefold()), None)
                if shared is not None:
                    text += (' Тэнхимийн багш нарын өрөө: ' + shared.name + ' тоот, ' + floor_text(shared.floor)
                             + '.')
                return reply(text, 'staff', 'reception_teacher_office_unrecorded')
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
                label = _key(day) + ' (' + _MN_DAYS[target.weekday()] + ' гараг)'
                day = _MN_DAYS[target.weekday()]
            weekday = _DAY_LOOKUP[_key(day)]
            lessons = sorted((lesson for lesson in self.tables.timetable if _key(lesson.group) == _key(group.group)
                              and lesson.day == _DAYS[weekday]), key=lambda lesson: lesson.interval[0])
            if not lessons and not self.tables.timetable_complete:
                return missing('reception_timetable_incomplete')
            # A joint lesson is stored once per teacher/room; each time once, with its subject (11/23, check set Q36:
            # «… хэдэн цагаас хичээлтэй вэ?» needs the subject too, and the first lesson's start comes first).
            by_time = {}
            for lesson in lessons:
                by_time.setdefault(lesson.time, []).append(lesson)
            slots = []
            for time_text, items in by_time.items():
                subjects = ', '.join(dict.fromkeys(item.subject for item in items if item.subject))
                rooms = ', '.join(dict.fromkeys(item.room for item in items if item.room))
                slots.append(time_text + (' ' + subjects if subjects else '') + (' (' + rooms + ' тоот)' if rooms else ''))
            period = (' Хуваарийн хугацаа: ' + self.tables.term_start.isoformat() + ' – '
                      + self.tables.term_end.isoformat() + '.') if self.tables.term_start and self.tables.term_end else ''
            when = label or (_MN_DAYS[weekday] + ' гарагт')
            if not slots:
                return reply(group.group + ' анги ' + when + ' хуваарьт хичээлгүй.' + period
                             + ' Хуваарь өөрчлөгдсөн байж болно.', 'timetable', 'reception_class_day')
            return reply(group.group + ' анги ' + when + ' ' + _clock(lessons[0].interval[0]) + '-аас хичээлтэй: '
                         + '; '.join(slots) + '.' + period
                         + ' Хуваарь өөрчлөгдсөн байж болно; бодит байршлыг батлахгүй.', 'timetable', 'reception_class_day')
        if intent == 'class_now':
            group = self._group_named(value)
            if group is None:
                return missing()
            if not isinstance(now, datetime):
                return missing('reception_date_required')
            reason = self._calendar_reason(now)
            if reason == 'reception_holiday':
                return reply(group.group + ' анги — өнөөдөр бүртгэсэн амралтын өдөр; хуваарьт хичээл байхгүй.', 'timetable',
                             'reception_holiday')
            if reason:
                return missing(reason)
            weekday, minute = now.weekday(), now.hour * 60 + now.minute
            lessons = sorted((lesson for lesson in self.tables.timetable if _key(lesson.group) == _key(group.group)
                              and lesson.day == _DAYS[weekday]), key=lambda lesson: lesson.interval[0])
            if not lessons and not self.tables.timetable_complete:
                return missing('reception_timetable_incomplete')

            def slot(items):
                # A joint lesson is stored once per teacher and room: one time, its subjects and rooms once.
                subjects = ', '.join(dict.fromkeys(item.subject for item in items if item.subject))
                rooms = ', '.join(dict.fromkeys(item.room for item in items if item.room))
                return items[0].time + (' ' + subjects if subjects else '') + (' (' + rooms + ' тоот)' if rooms else '')
            current = [lesson for lesson in lessons if lesson.interval[0] <= minute < lesson.interval[1]]
            later = [lesson for lesson in lessons if lesson.interval[0] > minute]
            following = [lesson for lesson in later if lesson.interval[0] == later[0].interval[0]] if later else []
            when = 'одоо (' + _MN_DAYS[weekday] + ' ' + now.strftime('%H:%M') + ')'
            if current:
                text = group.group + ' анги ' + when + ' хуваариар: ' + slot(current)
            elif lessons:
                text = group.group + ' анги ' + when + ' хуваариар хичээлгүй'
            else:
                text = group.group + ' анги өнөөдөр (' + _MN_DAYS[weekday] + ') хуваарьт хичээлгүй'
            if following:
                text += '. Дараагийн хичээл: ' + slot(following)
            elif lessons and not current:
                text += '; өнөөдрийн хичээл ' + _clock(max(lesson.interval[1] for lesson in lessons)) + '-д дууссан'
            return reply(text + '. Хуваарь өөрчлөгдсөн байж болно; бодит байршлыг батлахгүй.', 'timetable',
                         'reception_class_now')
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
        if intent == 'lunch_break':
            if not self.tables.timetable or not self.tables.timetable_complete:
                return missing('reception_timetable_incomplete')
            _, slots, common = self._common_slots()
            gaps = self._slot_gaps(slots, common)
            longest = max(gaps, default=None)
            # One break of 20 minutes or more, longer than every other one; a single gap or equal gaps name none.
            if (longest is None or len(gaps) < 2 or longest[0] < 20
                    or sum(gap == longest[0] for gap, _, _ in gaps) != 1):
                return missing('reception_lookup_missing')
            gap, earlier, later = longest
            start, end = slots[earlier][1], slots[later][0]
            # Some classes have a joined lesson through the break: «ихэнх анги», never «бүх анги».
            through = any(lesson.interval[0] < end and lesson.interval[1] > start for lesson in self.tables.timetable)
            return reply('Ресепшний хуваарийн хүснэгтээр ' + ('ихэнх анги ' if through else 'хичээлийн өдрийн завсарлага ')
                         + _clock(start) + '–' + _clock(end)
                         + (' хооронд хичээлгүй (өдрийн завсарлага, ' if through else ' (') + str(gap)
                         + ' минут). Албадын цайны цаг хүснэгтэд бүртгэгдээгүй.', 'timetable', 'reception_lunch_break')
        if intent == 'lesson_length':
            if not self.tables.timetable or not self.tables.timetable_complete:
                return missing('reception_timetable_incomplete')
            usual, slots, common = self._common_slots()
            if not common:
                return missing('reception_lookup_missing')
            gaps = self._slot_gaps(slots, common)
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
            # A joint lesson is stored once per teacher/room; list each slot once. One line per class (11/23 (2):
            # 25 «ЦИ-2: 08:00-09:30; КУ-2: 08:00-09:30; …» pairs in one line could not be read at the desk).
            if not lessons:
                # Plain words here too (code review 11/23 (2)).
                return reply(now.strftime('%Y-%m-%d') + '-нд ' + value + '-р курсын хуваарьт хичээл алга.',
                             'timetable', 'reception_course_timetable')
            times = {}
            for lesson in lessons:
                times.setdefault(lesson.group, [])
                if lesson.time not in times[lesson.group]:
                    times[lesson.group].append(lesson.time)
            return reply(now.strftime('%Y-%m-%d') + '-ны хуваарь:\n'
                         + '\n'.join(group + ': ' + ', '.join(slots) for group, slots in times.items())
                         + '\nЯг одоо хаана байгааг мэдэх боломжгүй.', 'timetable', 'reception_course_timetable')
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
            return self._result(query, prefix + row.name + ' тоот өрөө ' + floor_text(row.floor) + 'т байрладаг'
                + (' (' + row.purpose + ')' if row.purpose and _key(row.purpose) != 'анги' else '') + '.',
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
        window = self._school_window()
        closed = (calendar_reason is None and isinstance(now, datetime)
                  and (now.weekday() >= 5 or window is not None and not window[0] <= minute < window[1]))
        # Part of the complete answers (config ``complete_answers``): switched off, the short status stays.
        if self.complete and (calendar_reason == 'reception_holiday' or closed) and not (day and moment):
            # «Соронзонболд багш хаана байна?» on a holiday, a weekend or outside the school day: the office and the
            # timetable of the day a visitor can come, not «the timetable does not apply» or «free» alone (11/26).
            schedule = self._teacher_schedule(person, now)
            if schedule:
                return self._schedule_reply(query, person, schedule, prefix)
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
