"""Reading room for /reader: the weekly reading list and each paper's Mongolian guide.

Everything is read from the repo on every request (WEEKLY-PLAN table, papers/*hotoch*.md),
so the page follows the work without a rebuild. Status comes only from the plan table;
this page never marks a paper as read.
"""
from __future__ import annotations

import html
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent
if str(ROOT / 'tools') not in sys.path:
    sys.path.insert(0, str(ROOT / 'tools'))
from build_paper_reader import Renderer, build, table_rows  # noqa: E402

PLAN = 'CORE/WEEKLY-PLAN-2026-2027.mn.md'
TABLE_MARK = 'Унших дараалал ба төлөв'
CODE = re.compile(r'\b([A-Z]{3}\d{2})\b')
RELATIVE_LINK = re.compile(r'\[([^\]]+)\]\((?!https?://)[^)]*\)')
STATUS_TEXT = {'read': 'Уншсан ✅', 'current': 'Энэ долоо хоног', 'next': 'Дараагийнх', 'later': 'Үлдсэн'}


def reading_list(root):
    """Rows of the plan's reading table: week, paper, how, status and the guide code if one exists."""
    lines = (Path(root) / PLAN).read_text(encoding='utf-8').splitlines()
    start = next((index for index, line in enumerate(lines) if TABLE_MARK in line), None)
    if start is None:
        return []
    block, index = [], start + 1
    while index < len(lines) and not lines[index].strip().startswith('|'):
        index += 1
    while index < len(lines) and lines[index].strip().startswith('|'):
        block.append(lines[index])
        index += 1
    rows, guides = [], guide_files(root)
    for cells in table_rows(block)[1:]:
        if len(cells) < 4:
            continue
        week, paper, how, status_cell = cells[:4]
        status = 'read' if '✅' in status_cell else 'current' if 'Одоо' in status_cell else 'later'
        code = next((found for found in CODE.findall(paper) if found in guides), None)
        rows.append({'week': week, 'paper': paper, 'how': how, 'status': status, 'status_note': status_cell,
                     'guide': code})
    upcoming = [row for row in rows if row['status'] == 'later']
    if upcoming:
        # After the current paper is marked ✅ there is no «Одоо» row; the first unread one is still next.
        upcoming[0]['status'] = 'next'
    return rows


def guide_files(root):
    """Map a paper code to its guide; the detailed ('delgerengui') guide wins over the short one."""
    found = {}
    for path in sorted((Path(root) / 'papers').glob('*hotoch*.md')):
        for code in CODE.findall(path.name):
            if code not in found or 'delgerengui' in path.name:
                found[code] = path
    return found


def guide_page(root, code):
    path = guide_files(root).get(code)
    if path is None:
        raise KeyError(code)
    markdown = RELATIVE_LINK.sub(r'\1', path.read_text(encoding='utf-8'))
    urls = re.findall(r'https?://\S+?(?=[\s)·]|$)', markdown)
    abs_url = next((url for url in urls if '/abs/' in url), urls[0] if urls else '#')
    pdf_url = next((url for url in urls if '/pdf/' in url or url.endswith('.pdf')), abs_url)
    return build(markdown, pdf_url=pdf_url, abs_url=abs_url, home_url='/reader')


HOURS = re.compile(r'~(\d+(?:\.\d+)?)\s*цаг')
WEEK_HEAD = re.compile(r'^### (W\d{2}) · \d{4}\.(\d{2})\.(\d{2})–(?:\d{4}\.)?(\d{2})\.(\d{2})')


def week_dates(root):
    """«W05» -> «11/23–11/29» from the plan's week headings."""
    found = {}
    for line in (Path(root) / PLAN).read_text(encoding='utf-8').splitlines():
        match = WEEK_HEAD.match(line)
        if match:
            week, m1, d1, m2, d2 = match.groups()
            found[week] = f'{int(m1)}/{d1}–{int(m2)}/{d2}'
    return found


def index_page(root):
    """Unread papers week by week with the planned hours (11/23: the user reads 14 hours a week), then the read ones."""
    rows, plain, dates = reading_list(root), Renderer(), week_dates(root)

    def item(row, status):
        paper, how = (plain.inline(RELATIVE_LINK.sub(r'\1', row[key])) for key in ('paper', 'how'))
        action = (f'<a class="open" href="/reader/{row["guide"]}">Хөтөч нээх →</a>' if row['guide']
                  else '<span class="missing">Хөтөч бэлдээгүй</span>')
        return (f'<li class="paper {status}"><span class="week">{html.escape(row["week"])}</span>'
                f'<div class="what"><p>{paper}</p><small>{how}</small></div>{action}</li>')

    sections = []
    unread = [row for row in rows if row['status'] != 'read']
    for week in dict.fromkeys(row['week'] for row in unread):
        chosen = [row for row in unread if row['week'] == week]
        hours = sum(float(found[1]) for row in chosen for found in [HOURS.search(row['how'])] if found)
        now = any(row['status'] == 'current' for row in chosen)
        title = (html.escape(week) + (' · ' + dates[week] if week in dates else '')
                 + (' · энэ долоо хоног' if now else ''))
        load = f' · ~{hours:g} цаг' if hours else ''
        items = ''.join(item(row, 'current' if now else 'later') for row in chosen)
        sections.append(f'<section><h2>{title} <span>{len(chosen)} өгүүлэл{load}</span></h2><ol>{items}</ol></section>')
    done = [row for row in rows if row['status'] == 'read']
    if done:
        items = ''.join(item(row, 'read') for row in done)
        sections.append(f'<section><h2>Уншсан <span>{len(done)}</span></h2><ol>{items}</ol></section>')
    read = len(done)
    guided = sum(bool(row['guide']) for row in rows)
    body = ''.join(sections) or '<p class="empty">Унших жагсаалт олдсонгүй.</p>'
    return INDEX.format(total=len(rows), read=read, guided=guided, body=body)


INDEX = '''<!doctype html>
<html lang="mn"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Өгүүлэл унших · THesisS</title>
<style>
:root{{--ink:#163d37;--muted:#66736c;--line:#dce3d8;--cream:#f7f8f2;--gold:#ad8c47;--night:#0f1d2e;font-family:"Segoe UI",Arial,sans-serif;color:var(--ink);background:var(--cream)}}
body{{margin:0}}.top{{background:var(--night);color:#fff;padding:16px 28px;display:flex;gap:18px;align-items:center;flex-wrap:wrap}}
.top h1{{margin:0;font-size:18px;flex:1}}.top a{{color:#ffd76a;font-size:13px;text-decoration:none}}
main{{max-width:980px;margin:0 auto;padding:24px 22px 60px}}.summary{{color:var(--muted);font-size:14px;margin:0 0 18px}}
section{{margin-bottom:22px}}h2{{font-size:15px;margin:0 0 8px}}h2 span{{font-size:12px;color:var(--muted);font-weight:400}}
ol{{list-style:none;margin:0;padding:0;display:grid;gap:8px}}
.paper{{display:grid;grid-template-columns:54px 1fr auto;gap:14px;align-items:center;background:#fff;border:1px solid var(--line);border-radius:11px;padding:12px 16px}}
.paper.current{{border-color:#e2c46f;background:#fffaf0}}.paper.read{{opacity:.8}}
.week{{font-weight:700;font-size:13px;color:var(--muted)}}.what p{{margin:0 0 3px;font-size:14px;line-height:1.5}}.what small{{color:var(--muted);font-size:12px}}
.open{{background:var(--night);color:#ffd76a;text-decoration:none;font-size:13px;padding:8px 12px;border-radius:8px;white-space:nowrap}}
.missing{{font-size:12px;color:var(--muted);white-space:nowrap}}a{{color:#2f6b5d}}
@media(max-width:620px){{.paper{{grid-template-columns:1fr}}}}
</style></head>
<body><div class="top"><h1>Өгүүлэл унших</h1><a href="/work">Ажлын самбар</a><a href="/seminar">Семинар</a><a href="/reports">Тайлан</a><a href="/data">← Мэдлэгийн атлас</a><a href="/code-map">Кодын хот</a></div>
<main><p class="summary">{total} өгүүлэл · {read} уншсан · {guided} нь Монгол хөтөчтэй. Долоо хоногт 14 цаг хүртэл уншихаар хуваарилсан; цаг нь тооцоо. Төлөвийг долоо хоногийн төлөвлөгөөнөөс уншдаг; энэ хуудас «уншсан» гэж тэмдэглэхгүй — уншсанаа хэлбэл тэмдэглэнэ.</p>
{body}</main></body></html>
'''
