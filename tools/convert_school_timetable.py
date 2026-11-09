"""Add the school's Excel weekly timetable to the reception import workbook.

The school's timetable is one sheet: a header row with "Өдөр", one (or two)
columns per class group, and five day blocks of ten periods. A lesson is a
merged cell: its rows give the periods, its columns give the groups (one
merged cell over several groups is a joint lesson, e.g. English by level).
Teacher names (И.Нэр) and rooms (№301) are read from the cell text; a lesson
without a room is held in the group's home room from the header.

Every guess (teacher not in the staff list, room not in the room list) is
written to a review sheet. A newer timetable file can be dropped in and the
same command re-run. Only counts are printed.

    .venv/Scripts/python.exe tools/convert_school_timetable.py \\
        --timetable timetable.xlsx --base runtime/school-dataset-X/ресепшний_импорт.xlsx \\
        --out runtime/school-dataset-X/ресепшний_импорт_хуваарьтай.xlsx
"""
import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from prepare_school_dataset import DEPARTMENTS, floor_from_code, room_code  # noqa: E402

# Timetable group prefixes -> the school's class list prefixes.
GROUP_PREFIX = {'ЦЭИ': 'ЦИ', 'БДБИ': 'БИ', 'КУ': 'КУ', 'ХИ': 'ХИ', 'МИ': 'МИ'}
TEACHER = re.compile(r'(?<![А-ЯӨҮЁа-яөүё])([А-ЯӨҮЁ])\.\s?([А-ЯӨҮЁ][а-яөүё]+(?:-[А-ЯӨҮЁ]?[а-яөүё]+)?)')
ROOM = re.compile(r'№\s*([A-Za-zА-Яа-я]?\d{2,4}[А-ЯA-Z]?)')
DAYS = {'даваа': 'Даваа', 'мягмар': 'Мягмар', 'лхагва': 'Лхагва', 'пүрэв': 'Пүрэв', 'баасан': 'Баасан'}


def key(value):
    return re.sub(r'[\s.]+', '', unicodedata.normalize('NFC', str(value or '')).casefold())


def group_name(header):
    match = re.match(r'\s*([А-ЯӨҮ]+)-(\d)', str(header or ''))
    if not match or match.group(1) not in GROUP_PREFIX:
        return None
    return f'{GROUP_PREFIX[match.group(1)]}-{match.group(2)}'


def read_grid(path):
    """Return groups {name: (first_col, last_col, home_room)}, period rows and merged regions."""
    sheet = openpyxl.load_workbook(path).active
    header = next(r for r in range(1, 30) if str(sheet.cell(r, 2).value or '').strip() == 'Өдөр')
    starts = [(c, group_name(sheet.cell(header, c).value)) for c in range(3, sheet.max_column + 1)
              if sheet.cell(header, c).value]
    groups = {}
    for index, (col, name) in enumerate(starts):
        if name is None:
            continue
        end = starts[index + 1][0] - 1 if index + 1 < len(starts) else col
        home = ROOM.search(str(sheet.cell(header + 1, col).value or ''))
        groups[name] = (col, end, room_code(home.group(1)) if home else '')
    rows, day = {}, None
    for r in range(header + 2, sheet.max_row + 1):
        label = str(sheet.cell(r, 2).value or '').strip().casefold()
        day = DAYS.get(label, day)
        time = str(sheet.cell(r, 4).value or '').strip()
        if day and re.fullmatch(r'\d{1,2}:\d{2}-\d{1,2}:\d{2}', time):
            rows[r] = (day, time)
    regions = {}
    for merged in sheet.merged_cells.ranges:
        regions[(merged.min_row, merged.min_col)] = (merged.min_row, merged.min_col, merged.max_row, merged.max_col)
    covered = {(r, c) for (r0, c0, r1, c1) in regions.values()
               for r in range(r0, r1 + 1) for c in range(c0, c1 + 1)}
    first, last = min(c for c, _, _ in groups.values()), max(e for _, e, _ in groups.values())
    for r in rows:
        for c in range(first, last + 1):
            if (r, c) not in covered:
                regions[(r, c)] = (r, c, r, c)
    cells = []
    for (r0, c0, r1, c1) in regions.values():
        text = str(sheet.cell(r0, c0).value or '').strip()
        if text and r0 in rows and c1 >= first and c0 <= last:
            cells.append((r0, c0, r1, c1, text))
    return groups, rows, cells


def parse_text(text):
    """Subject before the first teacher; (teacher, room) pairs in reading order."""
    flat = ' '.join(text.split())
    teachers = list(TEACHER.finditer(flat))
    subject = flat[:teachers[0].start()].strip(' ,;-/') if teachers else flat
    pairs = []
    for index, match in enumerate(teachers):
        end = teachers[index + 1].start() if index + 1 < len(teachers) else len(flat)
        room = ROOM.search(flat, match.end(), end)
        pairs.append((f'{match.group(1)}.{match.group(2)}', room_code(room.group(1)) if room else ''))
    return subject or flat, pairs


def lessons_from(groups, rows, cells):
    lessons = []
    for r0, c0, r1, c1, text in sorted(cells):
        covered = [r for r in range(r0, r1 + 1) if r in rows]
        day = rows[covered[0]][0]
        time = rows[covered[0]][1].split('-')[0] + '-' + rows[covered[-1]][1].split('-')[1]
        members = [name for name, (start, end, _) in groups.items() if c0 <= end and c1 >= start]
        subject, pairs = parse_text(text)
        for name in members:
            home = groups[name][2]
            for teacher, room in pairs or [('', '')]:
                lessons.append(dict(day=day, time=time, subject=subject, teacher=teacher,
                                    room=room or home, group=name, joint=len(members) > 1 or len(pairs) > 1,
                                    text=' '.join(text.split())))
    return lessons


def _minutes(text):
    hours, minutes = text.split(':')
    return int(hours) * 60 + int(minutes)


def _clash(old, new):
    """Same rule as the importer: one teacher, group or room in two different lessons at once."""
    if old['day'] != new['day']:
        return False
    a, b = map(_minutes, old['time'].split('-'))
    c, d = map(_minutes, new['time'].split('-'))
    joint = old['time'] == new['time'] and key(old['subject']) == key(new['subject'])
    return c < b and a < d and not joint and any(key(old[f]) == key(new[f]) for f in ('teacher', 'group', 'room'))


def fill(base, out, lessons, review_path):
    book = openpyxl.load_workbook(base)
    staff_sheet, room_sheet = book['Багш, ажилтан'], book['Өрөө']
    staff = {key(row[0].value): row[1].value for row in staff_sheet.iter_rows(min_row=4) if row[0].value}
    rooms = {room_code(row[0].value) for row in room_sheet.iter_rows(min_row=4) if row[0].value}
    classes = {row[0].value: row[2].value for row in book['Анги (бүлэг)'].iter_rows(min_row=4) if row[0].value}
    issues, added_staff, added_rooms, kept = [], {}, set(), []
    for lesson in lessons:
        if lesson['group'] not in classes:
            issues.append(('Бүлэг', lesson['group'], 'Ангийн жагсаалтад алга', 'Хичээлийг орхисон'))
            continue
        if not lesson['teacher']:
            issues.append(('Багш', lesson['text'][:60], 'Багшийн нэр уншигдсангүй', 'Хичээлийг орхисон'))
            continue
        if key(lesson['teacher']) not in staff and lesson['teacher'] not in added_staff:
            added_staff[lesson['teacher']] = classes[lesson['group']] or DEPARTMENTS.get(lesson['group'][:2], '')
            issues.append(('Багш', lesson['teacher'], 'Ажилтны жагсаалтад алга',
                           f"Нэмсэн; тэнхимийг бүлгээс: {added_staff[lesson['teacher']]}"))
        if lesson['room'] not in rooms and lesson['room'] not in added_rooms:
            if floor_from_code(lesson['room']) is None:
                issues.append(('Өрөө', lesson['room'], 'Давхар тодорхойгүй', 'Хичээлийг орхисон'))
                continue
            added_rooms.add(lesson['room'])
            issues.append(('Өрөө', lesson['room'], 'Өрөөний жагсаалтад алга', 'Нэмсэн; давхрыг дугаараас'))
        clash = next((old for old in kept if _clash(old, lesson)), None)
        if clash is not None:
            issues.append(('Давхцал', f"{lesson['day']} {lesson['time']} {lesson['group']}",
                           f"{lesson['subject']} ({lesson['teacher']}, {lesson['room']}) нь "
                           f"{clash['group']}-ийн {clash['subject']} ({clash['time']})-тэй давхцаж байна",
                           'Хоёр дахийг орхисон — сургууль шалгана'))
            continue
        kept.append(lesson)
    line = staff_sheet.max_row + 1
    while line > 4 and not staff_sheet.cell(line - 1, 1).value:
        line -= 1
    for name, department in added_staff.items():
        for column, value in enumerate([name, department, 'Багш (хуваариас)', None, None], 1):
            staff_sheet.cell(line, column, value)
        line += 1
    line = room_sheet.max_row + 1
    while line > 4 and not room_sheet.cell(line - 1, 1).value:
        line -= 1
    for code in sorted(added_rooms):
        for column, value in enumerate([code, str(floor_from_code(code)), 'Хуваарьт заасан өрөө', None], 1):
            room_sheet.cell(line, column, value)
        line += 1
    sheet = book['Хичээлийн хуваарь']
    for r in range(4, sheet.max_row + 1):
        for cell in sheet[r]:
            cell.value = None
    for offset, lesson in enumerate(kept):
        values = [lesson['day'], lesson['time'], lesson['subject'], lesson['teacher'], lesson['room'], lesson['group']]
        for column, value in enumerate(values, 1):
            sheet.cell(4 + offset, column, value)
    book.save(out)
    review = openpyxl.Workbook()
    ws = review.active
    ws.title = 'Хуваарийн асуудал'
    ws.append(['Төрөл', 'Утга', 'Асуудал', 'Юу хийсэн'])
    for issue in issues:
        ws.append(list(issue))
    joint = review.create_sheet('Хамтарсан хичээл')
    joint.append(['Гараг', 'Цаг', 'Бүлэг', 'Хичээл', 'Багш', 'Өрөө'])
    for lesson in kept:
        if lesson['joint']:
            joint.append([lesson['day'], lesson['time'], lesson['group'], lesson['subject'], lesson['teacher'], lesson['room']])
    review.save(review_path)
    return dict(lessons=len(kept), dropped=len(lessons) - len(kept), joint=sum(l['joint'] for l in kept),
                added_staff=len(added_staff), added_rooms=len(added_rooms), issues=len(issues))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--timetable', type=Path, required=True)
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    out = args.out if args.out.is_absolute() else ROOT / args.out
    if not out.resolve().is_relative_to((ROOT / 'runtime').resolve()):
        parser.error('--out must be under runtime/ (private).')
    groups, rows, cells = read_grid(args.timetable)
    lessons = lessons_from(groups, rows, cells)
    counts = fill(args.base, out, lessons, out.with_name('хуваарь_шалгах.xlsx'))
    counts.update(groups=len(groups), periods=len(rows))
    print(json.dumps(counts, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
