"""Turn the school's raw reception files into the 7-sheet import template.

The school sent its own spreadsheets (rooms with seats, class groups, a staff
phone list) and a stamped list of official positions. This script cleans them
without guessing: floors come from the merged floor column and are checked
against the room number, Latin/Cyrillic look-alike letters in room codes are
unified, personal mobile numbers are dropped, and every derived or excluded
value is written to a review workbook for a person to check.

Only local files are read and written; nothing is printed except counts. The
output directory must be under runtime/ (private, not in Git). The reception
path stays disabled; enabling it is a separate human decision.

    .venv/Scripts/python.exe tools/prepare_school_dataset.py \\
        --rooms rooms.xlsx --staff staff.xlsx --official official.csv \\
        --out runtime/school-dataset-YYYYMMDD
"""
import argparse
import csv
import json
import re
import shutil
import sys
import unicodedata
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / 'data/school-request/ШМТК_сургуульд_өгөх_хүснэгт.xlsx'

ROMAN_FLOORS = {'B1': -1, 'I': 1, 'II': 2, 'III': 3, 'IV': 4, 'V': 5, 'VI': 6,
                'VII': 7, 'VIII': 8, 'IX': 9, 'X': 10}
# Latin letters that look like Cyrillic ones in room codes (B6 vs В6).
LOOKALIKE = str.maketrans('ABCEHKMOPTXY', 'АВСЕНКМОРТХУ')
# Department abbreviations used by the school; the full names appear in the
# stamped position list.
DEPARTMENTS = {
    'КУТ': 'Компьютерын ухааны тэнхим', 'КУ': 'Компьютерын ухааны тэнхим',
    'МИТ': 'Механик инженерийн тэнхим', 'МИ': 'Механик инженерийн тэнхим',
    'ХИТ': 'Химийн инженерийн тэнхим', 'ХИ': 'Химийн инженерийн тэнхим',
    'БДБИТ': 'Барилга, дэд бүтцийн инженерийн тэнхим', 'БИ': 'Барилга, дэд бүтцийн инженерийн тэнхим',
    'ЦЭИТ': 'Цахилгаан электроникийн инженерийн тэнхим', 'ЦИ': 'Цахилгаан электроникийн инженерийн тэнхим',
    'ЕЭТ': 'Ерөнхий эрдмийн тэнхим',
}
FULL_DEPARTMENTS = sorted(set(DEPARTMENTS.values()), key=len, reverse=True)
# Offices a visitor asks for, keyed by words in the room purpose.
SERVICE_PURPOSES = {
    'сургалтын алба': 'Сургалтын алба', 'оюутны алба': 'Оюутны алба',
    'санхүүгийн алба': 'Санхүүгийн алба', 'номын сан': 'Номын сан',
    'эмчийн өрөө': 'Эмч', 'сэтгэл зүйч': 'Сэтгэл зүйч',
    'карьер хөгжлийн төв': 'Гадаад харилцаа, карьер хөгжлийн төв',
    'дотоод хяналт': 'Дотоод хяналт, чанарын алба', 'захирал': 'Захирал',
}
# Units for non-teaching staff, matched on the official position text.
UNITS = [('сургалтын', 'Сургалтын алба'), ('оюутан', 'Оюутны алба'), ('оюутны', 'Оюутны алба'),
         ('гадаад харилцаа', 'Гадаад харилцаа, карьер хөгжлийн төв'), ('номын санч', 'Номын сан'),
         ('сэтгэл зүйч', 'Сэтгэл зүйч'), ('эмч', 'Эмч'), ('дотоод хяналт', 'Дотоод хяналт, чанарын алба'),
         ('захирал', 'Захиргаа'), ('захирл', 'Захиргаа'), ('нягтлан', 'Санхүүгийн алба'), ('ресепшн', 'Ресепшн')]
SUBJECT_TEACHER = re.compile(r'(математик|физик|хэлний|биеийн тамир|нийгмийн|түүх)', re.I)
SERVICE_STAFF = re.compile(r'(үйлчлэгч|жижүүр|нярав)', re.I)
# Room numbers such as 513, 103А, 1004 or basement В6Б; header cells are not rooms.
ROOM_CODE = re.compile(r'(В\d{1,2}[А-ЯӨҮ]?|\d{3,4}[А-ЯӨҮ]?)')


def key(value):
    return re.sub(r'[\s.]+', '', unicodedata.normalize('NFC', str(value or '')).casefold())


def room_code(value):
    """Canonical room code; None for an empty cell."""
    if value is None or not str(value).strip():
        return None
    text = str(value).strip()
    if re.fullmatch(r'\d+\.0', text):
        text = text[:-2]
    return text.upper().translate(LOOKALIKE)


def floor_from_label(label):
    match = re.match(r'\s*(B1|[IVX]+)\s+давхар', str(label or ''), re.I)
    return ROMAN_FLOORS.get(match.group(1).upper()) if match else None


def floor_from_code(code):
    if code.startswith('В'):
        return -1  # B-prefixed rooms are on the basement (B1) floor in the school list.
    match = re.fullmatch(r'(\d+?)(\d\d)[А-ЯӨҮ]?', code)
    return int(match.group(1)) if match else None


def department_of(text):
    """Full department name named in a position, or one an abbreviation stands for."""
    lowered = str(text or '').casefold()
    for name in FULL_DEPARTMENTS:
        if name.casefold().replace(' тэнхим', '') in lowered:
            return name
    for abbr, name in DEPARTMENTS.items():
        if re.search(rf'(?<![А-ЯӨҮа-яөү]){abbr}(?![А-ЯӨҮа-яөү])', str(text or '')):
            return name
    return None


def unit_of(position):
    lowered = str(position or '').casefold()
    for word, unit in UNITS:
        if word in lowered:
            return unit
    return None


class Report:
    def __init__(self):
        self.issues = []

    def add(self, table, row, problem, action, review=True):
        self.issues.append(dict(table=table, row=row, problem=problem, action=action,
                                review='Тийм' if review else 'Үгүй'))


def read_rooms(path, report):
    book = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheet1, sheet2 = book.worksheets[0], book.worksheets[1]
    rooms, floor = {}, None
    for line, cells in enumerate(sheet1.iter_rows(values_only=True), 1):
        cells = list(cells) + [None] * 7
        if not isinstance(cells[1], (int, float)):
            continue  # title or header row; data rows carry a running number
        if cells[2] not in (None, ''):
            floor = floor_from_label(cells[2])
        code = room_code(cells[3])
        if code is not None and not ROOM_CODE.fullmatch(code):
            continue  # title, header or column-number row
        if code is None:
            report.add('Өрөө', line, 'Өрөөний дугааргүй мөр', 'Орхисон')
            continue
        by_code = floor_from_code(code)
        if floor is not None and by_code is not None and floor != by_code:
            report.add('Өрөө', line, f'Давхар ({floor}) дугаартай ({code}) зөрж байна', 'Баганын давхрыг авсан')
        if str(cells[3]).strip().upper() != code:
            report.add('Өрөө', line, f'Латин үсэгтэй код «{str(cells[3]).strip()}»', f'«{code}» болгосон', False)
        if code in rooms:
            report.add('Өрөө', line, f'{code} өрөө давхардсан', 'Эхний мөрийг авсан')
            continue
        rooms[code] = dict(name=code, floor=floor if floor is not None else by_code,
                           purpose=str(cells[4] or '').strip(), department='', source='Sheet1')
    groups, part = [], 0
    for line, cells in enumerate(sheet2.iter_rows(values_only=True), 1):
        cells = list(cells) + [None] * 6
        label = str(cells[3] or '').strip()
        if label.startswith(('Өрөөний зориулалт', 'Анги, танхимын зориулалт')):
            part += 1
            continue
        group = re.fullmatch(r'([А-ЯӨҮ]{2})-(\d{1,2})', label)
        code = room_code(cells[2])
        if group and part == 0:
            groups.append(dict(group=label, course=group.group(2),
                               department=DEPARTMENTS.get(group.group(1), ''), room=code or '',
                               teacher=str(cells[5] or '').strip(), students=cells[4], line=line))
            continue
        if not code or not label or not ROOM_CODE.fullmatch(code):
            continue
        department = department_of(label)
        if code not in rooms:
            rooms[code] = dict(name=code, floor=floor_from_code(code), purpose=label,
                               department=department or '', source='Sheet2')
            report.add('Өрөө', line, f'{code} өрөө зөвхөн Sheet2-т байна',
                       'Нэмсэн; давхрыг дугаараас гаргасан')
        elif department and not rooms[code]['department']:
            rooms[code]['department'] = department
    book.close()  # read-only workbooks keep the file open on Windows
    return rooms, groups


def read_official(path):
    with open(path, encoding='utf-8') as stream:
        return {key(row['name']): row for row in csv.DictReader(stream)}


def read_staff(path, official, rooms, report):
    book = openpyxl.load_workbook(path, read_only=True, data_only=True)
    staff, comparison, seen = [], [], set()
    for line, cells in enumerate(book.active.iter_rows(values_only=True), 1):
        cells = list(cells) + [None] * 7
        if not isinstance(cells[0], (int, float)):
            continue
        name, role = str(cells[1] or '').strip(), str(cells[2] or '').strip()
        if not name:
            report.add('Ажилтан', line, 'Нэргүй мөр', 'Орхисон')
            continue
        seen.add(key(name))
        record = official.get(key(name))
        position = record['position'] if record else role
        comparison.append(dict(name=name, phone_role=role, official_position=record['position'] if record else '',
                               status='Хоёуланд' if record else 'Зөвхөн утасны жагсаалтад'))
        if SERVICE_STAFF.search(position):
            report.add('Ажилтан', line, 'Үйлчилгээний ажилтан', 'Лавлахад оруулаагүй (сургууль шийднэ)')
            continue
        if not record and not role:
            report.add('Ажилтан', line, 'Албан тушаалгүй, орон тооны жагсаалтад алга', 'Орхисон')
            continue
        department, how = department_of(position) or department_of(role), 'албан тушаалаас'
        if department is None and unit_of(position):
            department, how = unit_of(position), 'албан тушаалын үгээс гаргасан'
        if department is None and SUBJECT_TEACHER.search(position):
            department, how = 'Ерөнхий эрдмийн тэнхим', 'хичээлээс таамагласан'
        if department is None:
            report.add('Ажилтан', line, 'Нэгж тодорхойгүй', 'Орхисон')
            continue
        if how != 'албан тушаалаас':
            report.add('Ажилтан', line, f'Нэгжийг {how}: {department}', 'Оруулсан')
        room = room_code(cells[5]) or ''
        if room and room not in rooms:
            report.add('Ажилтан', line, f'{room} өрөө өрөөний хүснэгтэд алга', 'Өрөөг хоосон үлдээсэн')
            room = ''
        staff.append(dict(name=name, department=department, role=position, room=room, office_hours=''))
    book.close()
    for name_key, record in official.items():
        if name_key not in seen:
            comparison.append(dict(name=record['name'], phone_role='', official_position=record['position'],
                                   status='Зөвхөн орон тооны жагсаалтад'))
    return staff, comparison


def services_from(rooms, report):
    services, used = [], set()
    for room in rooms.values():
        lowered = room['purpose'].casefold()
        for word, name in SERVICE_PURPOSES.items():
            if word in lowered and name not in used:
                used.add(name)
                services.append(dict(name=name, floor=room['floor'], room=room['name'],
                                     office_hours='', contact='—'))
    for name in sorted(set(SERVICE_PURPOSES.values()) - used):
        report.add('Алба', '-', f'{name}-ийн өрөө хүснэгтэд алга', 'Оруулаагүй')
    return services


def check_groups(groups, staff, rooms, report):
    names = {key(person['name']) for person in staff}
    for group in groups:
        code = group['room']
        if code and code not in rooms:
            floor = floor_from_code(code)
            if floor is None:
                report.add('Анги', group['line'], f'{code} өрөөний давхар тодорхойгүй', 'Өрөөг хоосон')
                group['room'] = ''
            else:
                rooms[code] = dict(name=code, floor=floor, purpose='Анги', department='', source='Sheet2')
                report.add('Анги', group['line'], f'{code} өрөө зөвхөн ангийн жагсаалтад байна',
                           'Өрөө нэмсэн; давхрыг дугаараас гаргасан')
        if group['teacher'] and key(group['teacher']) not in names:
            report.add('Анги', group['line'], 'Ангийн багш ажилтны лавлахад алга', 'Багшийг хоосон үлдээсэн')
            group['teacher'] = ''
        if not group['room']:
            report.add('Анги', group['line'], 'Үндсэн өрөөгүй', 'Импортод орохгүй')
    return [group for group in groups if group['room']]


def fill_template(out, rooms, staff, groups, services):
    path = out / 'ресепшний_импорт.xlsx'
    shutil.copyfile(TEMPLATE, path)
    book = openpyxl.load_workbook(path)
    data = {
        'Өрөө': [[r['name'], str(r['floor']), r['purpose'], r['department']]
                 for r in rooms.values() if r['floor'] is not None],
        'Алба, үйлчилгээ': [[s['name'], str(s['floor']), s['room'], s['office_hours'], s['contact']]
                            for s in services],
        'Багш, ажилтан': [[p['name'], p['department'], p['role'], p['room'], p['office_hours']]
                          for p in staff],
        'Анги (бүлэг)': [[g['group'], g['course'], g['department'], g['room'], g['teacher']] for g in groups],
    }
    for title, rows in data.items():
        sheet = book[title]
        for line in range(4, sheet.max_row + 1):
            for cell in sheet[line]:
                cell.value = None
        for offset, row in enumerate(rows):
            for column, value in enumerate(row, 1):
                sheet.cell(row=4 + offset, column=column, value=value or None)
    book.save(path)
    return path, {title: len(rows) for title, rows in data.items()}


def write_review(out, report, comparison, counts):
    path = out / 'шалгах_жагсаалт.xlsx'
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = 'Асуудал'
    sheet.append(['Хүснэгт', 'Эх мөр', 'Асуудал', 'Юу хийсэн', 'Хүн шалгах уу'])
    for issue in report.issues:
        sheet.append([issue['table'], issue['row'], issue['problem'], issue['action'], issue['review']])
    compare = book.create_sheet('Ажилтан_тулгалт')
    compare.append(['Нэр', 'Утасны жагсаалтын тушаал', 'Орон тооны тушаал', 'Төлөв'])
    for row in sorted(comparison, key=lambda r: (r['status'], r['name'])):
        compare.append([row['name'], row['phone_role'], row['official_position'], row['status']])
    summary = book.create_sheet('Тоо')
    for title, count in counts.items():
        summary.append([title, count])
    for ws in book.worksheets:
        for column in ws.columns:
            ws.column_dimensions[column[0].column_letter].width = 28
    book.save(path)
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--rooms', type=Path, required=True)
    parser.add_argument('--staff', type=Path, required=True)
    parser.add_argument('--official', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    out = args.out if args.out.is_absolute() else ROOT / args.out
    if not out.resolve().is_relative_to((ROOT / 'runtime').resolve()):
        parser.error('--out must be under runtime/ (private).')
    out.mkdir(parents=True, exist_ok=True)
    report = Report()
    rooms, groups = read_rooms(args.rooms, report)
    official = read_official(args.official)
    staff, comparison = read_staff(args.staff, official, rooms, report)
    groups = check_groups(groups, staff, rooms, report)
    services = services_from(rooms, report)
    for room in rooms.values():
        if room['floor'] is None:
            report.add('Өрөө', '-', f"{room['name']} өрөөний давхар тодорхойгүй", 'Импортод оруулаагүй')
    template, counts = fill_template(out, rooms, staff, groups, services)
    counts.update({'Асуудал (нийт)': len(report.issues),
                   'Хүн шалгах асуудал': sum(i['review'] == 'Тийм' for i in report.issues),
                   'Хоёр жагсаалтад хоёуланд': sum(r['status'] == 'Хоёуланд' for r in comparison),
                   'Зөвхөн утасны жагсаалтад': sum(r['status'] == 'Зөвхөн утасны жагсаалтад' for r in comparison),
                   'Зөвхөн орон тооны жагсаалтад': sum(r['status'] == 'Зөвхөн орон тооны жагсаалтад' for r in comparison)})
    review = write_review(out, report, comparison, counts)
    (out / 'counts.json').write_text(json.dumps(counts, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(template=str(template.relative_to(ROOT)), review=str(review.relative_to(ROOT)),
                          counts=counts), ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
