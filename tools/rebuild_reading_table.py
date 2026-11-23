"""Rewrite the plan's reading table from the 14-hours-a-week schedule (2026-11-23).

The user (11/22): «put every paper I must read on 127, split by week; I can give 14 hours a week».
The schedule (papers/46-reading-plan-20261122.mn.md, data/reading-plan-20261122.json) was built
from the thesis citations, the plan's reading lines and the six Mongolian works. This script
writes it into the one place the plan keeps reading (CORE/WEEKLY-PLAN-2026-2027.mn.md, table
«Унших дараалал ба төлөв»), which /reader and the work board read live. Rows the user marked ✅
are kept word for word; every other row comes from the schedule, one paper per row so that each
row can link its own guide.

    .venv/Scripts/python.exe tools/rebuild_reading_table.py [--check]
"""
import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / 'CORE/WEEKLY-PLAN-2026-2027.mn.md'
SCHEDULE = ROOT / 'data/reading-plan-20261122.json'
MARK = '**Унших дараалал ба төлөв'
PROMISED = {'RAG08': '11/17-ны слайдад «SQuAD 2.0 унших» гэж амласан',
            **{f'MON0{n}': '11/17-ны слайдад «Монгол судалгааны ажил унших» гэж амласан' for n in range(1, 7)}}
INTRO = ('**Унших дараалал ба төлөв (2026.11.02; 2026.11.23-нд долоо хоногт 14 цагаар дахин хуваарилсан).** '
         'Хэрэглэгч 11/22-нд «унших бүх өгүүллээ долоо хоногоор хуваа, долоо хоногт 14 цаг гаргана» гэсэн тул '
         'дипломд иш татсан, төлөвлөгөөнд нэрлэсэн бүх өгүүлэл ба Монгол зургаан ажлыг W05–W08-д хуваарилав '
         '(цагийн тооцоо, бүтэн жагсаалт: `papers/46-reading-plan-20261122.mn.md`). W09–W20-д шинэ өгүүлэл '
         'уншихгүй; тухайн долоо хоногийн «Унших, ойлгох» мөрөнд нэрлэсэн өгүүллийг 30 минут сэргээн уншиж, ажилдаа '
         'хэрэглэнэ. Цаг нь тооцоо (англи өгүүлэл Монгол хөтөчтэй 5 хуудас/цаг, Монгол 10 хуудас/цаг, +0.5 цаг) — '
         'хэмжсэн хурд биш. «Бүтэн» гэдэг нь эхнээс нь дуустал, «Гол хэсэг» гэдэг нь заасан бүлгүүдийг унших. Унших '
         'арга: Keshav-ийн 3 шат, 1 хуудасны тэмдэглэл, 1 минут Монголоор чанга тайлбарлах. Монгол хөтөч нь орчуулга '
         'биш, эхтэй хамт уншина. Хэрэглэгч уншсан гэж зөвхөн хэрэглэгч өөрөө хэлсэн үед тэмдэглэнэ.')


def guide_link(path):
    return f'[хөтөч](../{path})' if path else 'хөтөч бэлдээгүй'


def row(week, item, current):
    title = item['title'].replace('|', '/')
    paper = (f"{item['code']}: {item.get('authors', '')} ({item.get('year', '')}) — *{title}*"
             + (f" ([эх]({item['url']}))" if item.get('url') else ''))
    # Only the instruction itself; the schedule's reasoning («Хүснэгтийн мөрөнд …») stays in papers/46.
    sections = re.split(r'(?<=\))\.\s|\.\s(?=[А-ЯӨҮЁA-Z«])', item.get('sections_mn') or 'Бүтэн')[0].rstrip('.')
    how = f"{sections.replace('|', '/')} · ~{item['hours']:g} цаг · {guide_link(item.get('guide'))}"
    if item.get('status') == 'partial':
        state = 'Хэсэгчлэн уншсан — үлдсэнийг ' + week + '-д'
    elif current:
        state = 'Одоо' + (' — ' + PROMISED[item['code']] if item['code'] in PROMISED else '')
    else:
        state = 'Үлдсэн'
    return f'| {week} | {paper} | {how} | {state} |'


def build(text, schedule):
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(MARK))
    head = next(i for i in range(start + 1, len(lines)) if lines[i].startswith('|'))
    end = head
    while end < len(lines) and lines[end].startswith('|'):
        end += 1
    old_rows = lines[head + 2:end]
    kept = [line for line in old_rows if '✅' in line.split('|')[-2]]
    weeks = schedule['weeks']
    # A paper the user has since read keeps only its ✅ row (kept above), not a second «Одоо» row.
    new_rows = [row(week['week'], item, week is weeks[0]) for week in weeks for item in week['items']
                if item.get('status') != 'read']
    totals = ' · '.join(f"{week['week']}: {sum(item['hours'] for item in week['items']):g} цаг" for week in weeks)
    table = ['| 7 хоног | Өгүүлэл | Яаж унших | Төлөв |', '|---|---|---|---|', *kept, *new_rows]
    note = f'Долоо хоногийн цаг (14 цагийн дотор): {totals}.'
    return '\n'.join(lines[:start] + [INTRO, '', note, ''] + table + lines[end:]) + ('\n' if text.endswith('\n') else '')


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--check', action='store_true', help='print what would change, write nothing')
    args = parser.parse_args()
    raw = PLAN.read_bytes().decode('utf-8')
    crlf = '\r\n' in raw
    text = raw.replace('\r\n', '\n')
    new = build(text, json.loads(SCHEDULE.read_text(encoding='utf-8')))
    if args.check:
        print(new[new.index(MARK):new.index(MARK) + 4000])
        return 0
    PLAN.write_bytes((new.replace('\n', '\r\n') if crlf else new).encode('utf-8'))
    print(f'{PLAN.relative_to(ROOT)}: reading table rewritten')
    return 0


if __name__ == '__main__':
    sys.exit(main())
