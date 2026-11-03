"""Сургуульд өгөх мэдээлэл хүсэх Excel: мэдлэгийн мод бүтнээр + ресепшний хүснэгтүүд.

Мод `config/knowledge-topics.json`-оос, сэдэв бүрийн одоогийн эхийн тоо
`build_knowledge_tree`-ээс (DB-г зөвхөн уншина), ресепшний 5 хүснэгт
`data/reception/...загвар.xlsx`-аас ирнэ. Систем, загвар ажиллуулахгүй.

    .venv/Scripts/python.exe tools/build_school_request_xlsx.py
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from openpyxl import load_workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.datavalidation import DataValidation

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from build_knowledge_tree import build_tree, load_inputs  # noqa: E402

RECEPTION = ROOT / 'data/reception/Ресепшний_мэдээлэл_цуглуулах_загвар.xlsx'
OUTPUT = ROOT / 'data/school-request/ШМТК_мэдлэгийн_мод_мэдээлэл_хүсэх.xlsx'
SKIP = {'nmct', 'review-needed'}

NAVY, LIGHT, FILL, EX, HAVE, NONE = '0E3199', 'E8F4FB', 'FFF2CC', '7F7F7F', 'E2F0D9', 'FCE4D6'
F = 'Arial'
thin = Side(style='thin', color='A6A6A6')
BOX = Border(left=thin, right=thin, top=thin, bottom=thin)
HEAD_FONT = Font(name=F, bold=True, color='FFFFFF', size=11)
HEAD_FILL = PatternFill('solid', fgColor=NAVY)
IN_FILL = PatternFill('solid', fgColor=FILL)
BODY = Font(name=F, size=10)
BOLD = Font(name=F, size=10, bold=True)
GREY = Font(name=F, size=9, color=EX)
WRAP = Alignment(wrap_text=True, vertical='top')

# Сэдэв бүрээр: сургуулиас юу хүсэх, жишээ асуулт, хаана бөглөх.
# Хүсэлт ба асуулт л; сургуулийн тухай баримт биш.
ASK = {
    'school': ('Сургуулийн ерөнхий мэдээлэл', 'Сургуулийн тухай ярь', ''),
    'school.overview': ('Сургуулийн товч танилцуулга, эрхэм зорилго, бүтэц (хамгийн сүүлийн албан хувилбар)', 'ШМТК ямар сургууль вэ?', ''),
    'school.history': ('Байгуулагдсан он, гол үе шатууд', 'Сургууль хэдэн онд байгуулагдсан бэ?', ''),
    'school.quality': ('Магадлан итгэмжлэл, чанарын баталгаажуулалтын нийтэлсэн мэдээлэл', 'Сургууль магадлан итгэмжлэгдсэн үү?', ''),
    'admissions': ('Элсэлтийн ерөнхий мэдээлэл, энэ жилийн журам (PDF байвал хавсаргана)', 'Элсэлт хэзээ эхлэх вэ?', ''),
    'admissions.requirements': ('Элсэх шаардлага: ямар шалгалт, ямар хичээл, босго оноо; хөтөлбөр бүрээр', 'Элсэхэд ямар шалгалт өгөх вэ?', ''),
    'admissions.exams': ('Шалгалт, эссэ, ярилцлагын хуваарь, хэлбэр, үнэлгээ', 'Ярилцлага хэзээ болох вэ?', ''),
    'admissions.documents': ('Бүрдүүлэх материалын жагсаалт, зургийн шаардлага, гадаадын сургуулийн бичиг баримт', 'Ямар бичиг баримт бүрдүүлэх вэ?', ''),
    'admissions.fees': ('Сургалтын төлбөр, бүртгэлийн хураамж, төлөх хугацаа ба арга, хөнгөлөлт, тэтгэлэг', 'Жилийн сургалтын төлбөр хэд вэ?', ''),
    'admissions.rules': ('Бүртгэлийн алхам, хугацаа, гэрээ байгуулах, элсэлт баталгаажуулах журам', 'Онлайн бүртгэл яаж хийх вэ?', ''),
    'admissions.olympiad': ('Олимпиадын ангилал, бүртгэл, олимпиадаар элсэх нөхцөл', 'Олимпиадад шагнал авсан бол шалгалтгүй элсэх үү?', ''),
    'academics': ('Сургалтын ерөнхий мэдээлэл', 'Ямар тэнхимүүд байдаг вэ?', ''),
    'academics.programs': ('Хөтөлбөрийн жагсаалт, суралцах хугацаа, олгох зэрэг, шилжих хөтөлбөр', 'Хэдэн жил суралцах вэ?', ''),
    'academics.general': ('Тэнхимийн танилцуулга, эрхлэгч, заадаг хичээл, лаборатори', 'Ерөнхий эрдмийн тэнхим юу заадаг вэ?', ''),
    'academics.computer-science': ('Тэнхимийн танилцуулга, эрхлэгч, хөтөлбөр, лаборатори, нийтэлсэн оюутны тоо', 'Компьютерын ухааны тэнхимд юу заадаг вэ?', ''),
    'academics.mechanical': ('Тэнхимийн танилцуулга, эрхлэгч, хөтөлбөр, лаборатори', 'Механикийн тэнхим ямар мэргэжил бэлтгэдэг вэ?', ''),
    'academics.electrical': ('Тэнхимийн танилцуулга, эрхлэгч, хөтөлбөр, лаборатори', 'Цахилгаан электроникийн тэнхимд юу сурах вэ?', ''),
    'academics.chemical': ('Тэнхимийн танилцуулга, эрхлэгч, хөтөлбөр, лаборатори', 'Химийн инженерийн тэнхим ямар лабораторитой вэ?', ''),
    'academics.civil': ('Тэнхимийн танилцуулга, эрхлэгч, хөтөлбөр, лаборатори', 'Барилгын тэнхим юу заадаг вэ?', ''),
    'student': ('Оюутны амьдралын ерөнхий мэдээлэл', 'Оюутнууд хичээлээс гадуур юу хийдэг вэ?', ''),
    'student.library': ('Номын сангийн давхар, өрөө, ажлын цаг, ном зээлэх журам, цахим сан', 'Номын сан хэдэн цагт хаадаг вэ?', '5_Үйлчилгээ'),
    'student.environment': ('Анги танхим, лаборатори, дотуур байр, цайны газрын мэдээлэл', 'Дотуур байр байдаг уу?', '5_Үйлчилгээ'),
    'student.sports': ('Спорт заал, клуб, секц, тэдгээрийн цаг', 'Ямар спортын клуб байдаг вэ?', '5_Үйлчилгээ'),
    'student.council': ('Оюутны зөвлөл, клубүүд, тэдэнтэй холбогдох арга', 'Оюутны зөвлөлд яаж орох вэ?', ''),
    'career': ('Карьер хөгжлийн төвийн мэдээлэл', 'Карьерын төв юу хийдэг вэ?', ''),
    'career.internship': ('Үйлдвэрлэлийн дадлагын хугацаа, газар, журам', 'Дадлагаа хэзээ хийх вэ?', ''),
    'career.japan': ('Японд суралцах, дадлага хийх хөтөлбөрийн нөхцөл, хугацаа', 'Японд суралцах боломж бий юу?', ''),
    'career.partners': ('Хамтрагч сургууль, байгууллагын жагсаалт', 'Ямар байгууллагатай хамтран ажилладаг вэ?', ''),
    'news': ('Мэдээг сайтаас авна. Шинэ мэдээг хэр давтамжтай шинэчлэх нь зүйтэй вэ?', 'Сүүлийн үеийн мэдээ юу байна?', ''),
    'events': ('Удахгүй болох арга хэмжээ, огноо, бүртгэл', 'Нээлттэй хаалганы өдөр хэзээ вэ?', ''),
    'contact': ('Албан утас, имэйл, хаяг, ажлын цаг; алба бүрийн утас', 'Сургалтын албаны утас хэд вэ?', ''),
    'location': ('Барилгын давхар, өрөөний мэдээлэл', 'Хаана юу байдаг вэ?', '1_Өрөө'),
    'location.floors': ('Давхар бүрийн өрөө, түүний зориулалт', 'Номын сан хэддүгээр давхарт вэ?', '1_Өрөө'),
    'location.services': ('Ресепшн, сургалтын алба, номын сан, цайны газар, эмнэлгийн өрөөний байршил ба цаг', 'Сургалтын алба хаана байдаг вэ?', '5_Үйлчилгээ'),
    'location.departments': ('Тэнхим бүрийн өрөө', 'Компьютерын ухааны тэнхимийн өрөө хаана вэ?', '1_Өрөө'),
    'staff': ('Багш, ажилтны нийтэд харуулах мэдээлэл', 'Энэ тэнхимд ямар багш нар байдаг вэ?', '2_Багш_ажилтан'),
    'staff.directory': ('Тэнхим бүрийн багш, ажилтан, албан тушаал (нийтэд харуулахыг зөвшөөрсөн)', 'Компьютерын ухааны тэнхимд ямар багш нар байдаг вэ?', '2_Багш_ажилтан'),
    'staff.offices': ('Багшийн өрөө, уулзах өдөр ба цаг', 'Соронзонболд багштай хэзээ уулзаж болох вэ?', '2_Багш_ажилтан'),
    'staff.availability': ('Багшийн хичээлийн хуваарь. Систем «хуваариар бол одоо хичээлтэй / сул» гэж л хэлнэ', 'Соронзонболд багш одоо хаана байна?', '4_Хичээлийн_хуваарь'),
    'classes': ('Анги, бүлэг, хуваарийн мэдээлэл', 'Манай анги хаана хичээллэдэг вэ?', '3_Анги'),
    'classes.groups': ('Бүлэг, курс, үндсэн өрөө, ангийн багш', 'КУ-2 анги хаана хичээллэдэг вэ?', '3_Анги'),
    'classes.timetable': ('Долоо хоногийн хичээлийн хуваарь, улирал бүрээр', 'Мягмар гарагт 2-р курс ямар хичээлтэй вэ?', '4_Хичээлийн_хуваарь'),
}


def header(ws, cols, height=34):
    for i, (name, width, note) in enumerate(cols, 1):
        c = ws.cell(1, i, name)
        c.font, c.fill, c.border = HEAD_FONT, HEAD_FILL, BOX
        c.alignment = Alignment(wrap_text=True, vertical='center')
        if note:
            c.comment = Comment(note, 'THesisS')
        ws.column_dimensions[c.column_letter].width = width
    ws.row_dimensions[1].height = height
    ws.freeze_panes = 'C2'


def put(ws, row, col, value, font=BODY, fill=None):
    c = ws.cell(row, col, value)
    c.font, c.border, c.alignment = font, BOX, WRAP
    if fill:
        c.fill = PatternFill('solid', fgColor=fill) if isinstance(fill, str) else fill
    return c


def status(topic):
    own = topic['subtree_counts']
    n_pages, n_facts, n_faqs = own['pages'], own['facts'], own['faqs']
    if not (n_pages or n_facts or n_faqs):
        return 'Эх алга — систем хариулж чадахгүй', NONE
    parts = [f'{n} {w}' for n, w in ((n_pages, 'сайтын хуудас'), (n_facts, 'баримт'), (n_faqs, 'бэлэн хариулт')) if n]
    return 'Эх байна: ' + ', '.join(parts), HAVE


def page_urls(topic, pages, limit=3):
    urls = [pages[p]['payload'].get('url', '') for p in topic['primary_record_ids']['pages']]
    urls = [u.replace('https://', '') for u in urls if u]
    more = len(urls) - limit
    return '\n'.join(urls[:limit]) + (f'\n… дахиад {more}' if more > 0 else '')


def tree_sheet(wb, tree, pages):
    ws = wb.create_sheet('Мэдлэгийн_мод', 0)
    header(ws, [
        ('Код', 14, 'Системийн дотоод нэр. Өөрчлөхгүй байх нь дээр (шинэ мөрөнд хоосон үлдээж болно).'),
        ('Хүрээ / сэдэв', 34, None),
        ('Одоо системд', 24, 'Сургуулийн сайтаас 2026.10-д хадгалсан эхээр тоолсон.'),
        ('Одоогийн эх (сайт)', 32, None),
        ('Сургуулиас хүсэх мэдээлэл', 44, None),
        ('Жишээ асуулт', 32, 'Хэрэглэгч ингэж асууж магадгүй.'),
        ('Хаана бөглөх', 18, 'Хоосон бол энэ мөрийн «Мэдээлэл, засвар» нүдэнд бичих эсвэл файл хавсаргана.'),
        ('Хариуцах алба / хүн', 20, None),
        ('Мэдээлэл, засвар', 40, 'Шинэ мэдээлэл, засвар, эсвэл хавсаргасан файлын нэр.'),
        ('Нийтэд харуулах', 11, None),
        ('Тэмдэглэл', 24, None),
    ])
    row = 2
    for topic in tree['topics']:
        tid = topic['topic_id']
        if tid in SKIP:
            continue
        ask, example, where = ASK[tid]
        frame = topic['parent_id'] == 'nmct'
        text, color = status(topic)
        put(ws, row, 1, tid, GREY)
        put(ws, row, 2, topic['label_mn'] if frame else '   └ ' + topic['label_mn'], BOLD if frame else BODY,
            LIGHT if frame else None)
        put(ws, row, 3, text, BODY, color)
        put(ws, row, 4, page_urls(topic, pages), GREY)
        put(ws, row, 5, ask)
        put(ws, row, 6, example, Font(name=F, size=10, italic=True))
        put(ws, row, 7, where or '', BODY)
        for col in range(8, 12):
            put(ws, row, col, None, BODY, IN_FILL)
        row += 1
    last = row - 1
    for rr in range(row, row + 15):  # сургууль шинэ сэдэв нэмэх мөр
        for col in range(1, 12):
            put(ws, rr, col, None, BODY, IN_FILL if col >= 2 else None)
    dv = DataValidation(type='list', formula1='"Тийм,Үгүй"', allow_blank=True)
    dv.add(f'J2:J{row + 14}')
    ws.add_data_validation(dv)
    ws.cell(row + 16, 1, 'Ногоон: эх байна. Улбар: эх алга. Доорх шар хоосон мөрөнд шинэ сэдэв нэмж болно.').font = GREY
    return ws, last


def known_sheet(wb, tree):
    ws = wb.create_sheet('Одоо_мэдэх_зүйл', 1)
    header(ws, [
        ('№', 5, None),
        ('Сэдэв', 22, None),
        ('Асуулт', 36, None),
        ('Системийн одоогийн хариулт', 60, 'Сайтын хадгалсан хуудаснаас. Хуучирсан байж болно.'),
        ('Эх', 26, None),
        ('Зөв үү?', 12, 'Зөв / Буруу / Хуучирсан'),
        ('Зөв мэдээлэл', 40, 'Буруу эсвэл хуучирсан бол зөвийг нь бичнэ үү.'),
    ])
    label = {t['topic_id']: t['label_mn'] for t in tree['topics']}
    topic_of = {}
    for t in tree['topics']:
        for group in ('faqs', 'facts'):
            for rid in t['primary_record_ids'][group]:
                topic_of[rid] = t['topic_id']
    records = tree['records']
    titles = {s['payload']['document_id']: s['payload'].get('title') or s['payload']['document_id']
              for s in records['sources']}
    rows = []
    covered = set()
    for faq in records['faqs']:
        p = faq['payload']
        covered.update(p['fact_ids'])
        rows.append((topic_of.get(faq['content_id']), p['question'], p['answer'], p['source_refs']))
    for fact in records['facts']:
        p = fact['payload']
        if p['fact_id'] in covered:
            continue
        value = p['value']
        if isinstance(value, dict):
            value = value.get('published_clause') or json.dumps(value, ensure_ascii=False)
        elif isinstance(value, list):
            value = '; '.join(map(str, value))
        rows.append((topic_of.get(fact['content_id']), p.get('scope') or p['key'], value, p['source_refs']))
    order = {t['topic_id']: i for i, t in enumerate(tree['topics'])}
    rows.sort(key=lambda r: order.get(r[0], 999))
    for i, (tid, question, answer, refs) in enumerate(rows, 1):
        r = i + 1
        put(ws, r, 1, i)
        put(ws, r, 2, label.get(tid, ''))
        put(ws, r, 3, question)
        put(ws, r, 4, answer)
        put(ws, r, 5, '\n'.join(sorted({titles.get(x['document_id'], x['document_id']) for x in refs})), GREY)
        put(ws, r, 6, None, BODY, IN_FILL)
        put(ws, r, 7, None, BODY, IN_FILL)
    dv = DataValidation(type='list', formula1='"Зөв,Буруу,Хуучирсан"', allow_blank=True)
    dv.add(f'F2:F{len(rows) + 1}')
    ws.add_data_validation(dv)
    ws.freeze_panes = 'D2'
    return ws, len(rows) + 1


def guide_sheet(wb, n_frames, n_topics, n_known):
    ws = wb.create_sheet('Заавар', 0)
    ws.sheet_view.showGridLines = False
    ws.column_dimensions['A'].width = 3
    ws.column_dimensions['B'].width = 24
    ws.column_dimensions['C'].width = 92
    ws.cell(2, 2, 'ШМТК-ийн AI чатботод хэрэгтэй сургуулийн мэдээлэл').font = Font(name=F, bold=True, size=16, color=NAVY)
    ws.cell(3, 2, 'Шинэ Монгол Технологийн Коллеж · Компьютерын ухааны тэнхимийн төгсөлтийн ажил').font = Font(name=F, size=10, color=EX)
    rows = [
        ('Юунд хэрэгтэй вэ?', 'Сургуулийн мэдээллийг бичгээр болон дуугаар асуухад сургуулийн баримтаас хариулдаг AI чатбот хийж байна. '
         'Мөн 1-р давхрын ресепшнд ирсэн хүний асуултад хариулна. Систем зөвхөн өгсөн мэдээллээс хариулна; мэдээлэл алга бол «мэдээлэл алга» гэнэ.'),
        ('Мэдлэгийн мод', f'Систем юу мэддэг, юу мэддэггүйн газрын зураг. {n_frames} хүрээ, {n_topics} сэдэвтэй. '
         '«Мэдлэгийн_мод» хуудаснаас сэдэв бүрд одоо эх байгаа эсэх (ногоон / улбар), сургуулиас юу хүсэж буйг харна.'),
        ('Хуудсууд', f'Мэдлэгийн_мод · Одоо_мэдэх_зүйл ({n_known} хариулт) · 1_Өрөө · 2_Багш_ажилтан · 3_Анги · '
         '4_Хичээлийн_хуваарь · 5_Үйлчилгээ · Шинэ_сэдэв · Явц.'),
        ('Хэн бөглөх вэ?', 'Сургалтын алба, тэнхим, захиргаа. Мэдэх хэсгээ л бөглөхөд болно.'),
        ('Яаж бөглөх вэ?', 'Шар нүдэнд бичнэ. «Одоо_мэдэх_зүйл» хуудсанд систем одоо өгдөг хариултыг уншаад «Зөв үү?» баганад сонгоно. '
         'Буруу бол зөвийг бичнэ. Журам, хуваарь PDF/Word хэлбэрээр байвал файлаа хавсаргаж, нэрийг нь «Мэдээлэл, засвар» баганад бичнэ.'),
        ('Нийтэд харуулах', '«Үгүй» гэсэн мэдээллийг систем хэрэглэгчид харуулахгүй.'),
        ('Хувийн мэдээлэл', 'Хувийн утас, гэрийн хаяг, оюутны нэрс, дүн бүү оруулна уу. Багш одоо хаана байгааг систем зөвхөн '
         'хичээлийн хуваариар таамаглаж хэлнэ («Хуваариар бол одоо 405 тоотод хичээлтэй»). Хүнийг хянахгүй.'),
        ('Хугацаа', '________________'),
        ('Буцааж өгөх', 'Бөглөсөн файлыг оюутан ________________ (утас/имэйл: ________________)-д өгнө үү.'),
    ]
    r = 5
    for key, value in rows:
        ws.cell(r, 2, key).font = Font(name=F, bold=True, size=11, color=NAVY)
        ws.cell(r, 2).alignment = WRAP
        c = ws.cell(r, 3, value)
        c.font, c.alignment = Font(name=F, size=11), WRAP
        ws.row_dimensions[r].height = 16 * (len(value) // 85 + 1) + 6
        r += 1
    r += 1
    ws.cell(r, 2, 'Тэмдэглэгээ').font = Font(name=F, bold=True, size=11, color=NAVY)
    for text, fill in (('Бөглөх нүд', FILL), ('Эх байна', HAVE), ('Эх алга', NONE), ('Сайтаас авсан, шалгах', LIGHT)):
        r += 1
        c = ws.cell(r, 3, text)
        c.font, c.border, c.fill = BODY, BOX, PatternFill('solid', fgColor=fill)
    return ws


def new_topic_sheet(wb):
    ws = wb.create_sheet('Шинэ_сэдэв')
    header(ws, [('Хүрээ', 24, 'Мэдлэгийн модны аль хүрээнд орох вэ, эсвэл шинэ хүрээ'), ('Сэдэв', 28, None),
                ('Мэдээлэл', 60, None), ('Эх / файлын нэр', 28, None), ('Нийтэд харуулах', 12, None)])
    ws.freeze_panes = 'A2'
    for r in range(2, 32):
        for col in range(1, 6):
            put(ws, r, col, None, BODY, IN_FILL)
    dv = DataValidation(type='list', formula1='"Тийм,Үгүй"', allow_blank=True)
    dv.add('E2:E31')
    ws.add_data_validation(dv)
    return ws


def progress_sheet(wb, tree_last, known_last):
    del wb['Явц']
    ws = wb.create_sheet('Явц')
    ws.sheet_view.showGridLines = False
    for col, width in zip('ABC', (26, 16, 52)):
        ws.column_dimensions[col].width = width
    for i, h in enumerate(('Хуудас', 'Бөглөсөн мөр', 'Юуг тоолдог'), 1):
        c = ws.cell(1, i, h)
        c.font, c.fill, c.border = HEAD_FONT, HEAD_FILL, BOX
    checks = [('Мэдлэгийн_мод', f'I2:I{tree_last + 15}', 'Мэдээлэл/засвар бичсэн сэдэв'),
              ('Одоо_мэдэх_зүйл', f'F2:F{known_last}', 'Зөв эсэхийг шалгасан хариулт'),
              ('1_Өрөө', 'C3:C500', 'Нэр/зориулалт бөглөгдсөн өрөө'),
              ('2_Багш_ажилтан', 'D3:D500', 'Өрөөний дугаар бөглөгдсөн хүн'),
              ('3_Анги', 'A3:A500', 'Нэр бичигдсэн бүлэг'),
              ('4_Хичээлийн_хуваарь', 'C3:C500', 'Гараг бөглөгдсөн хичээл'),
              ('5_Үйлчилгээ', 'C3:C500', 'Өрөө бөглөгдсөн үйлчилгээ'),
              ('Шинэ_сэдэв', 'B2:B31', 'Шинээр санал болгосон сэдэв')]
    for i, (name, rng, what) in enumerate(checks, 2):
        ws.cell(i, 1, name).font = BODY
        c = ws.cell(i, 2, f"=COUNTA('{name}'!{rng})")
        c.font, c.border = BODY, BOX
        ws.cell(i, 3, what).font = GREY
    end = len(checks) + 2
    ws.cell(end, 1, 'Нийт').font = BOLD
    ws.cell(end, 2, f'=SUM(B2:B{end - 1})').font = BOLD
    ws.cell(end + 2, 1, 'Ресепшний хуудасны жишээ мөрийг (2-р мөр) тоолохгүй.').font = GREY


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    parser.add_argument('--force', action='store_true', help='Байгаа файлыг дарж бичих.')
    args = parser.parse_args()
    if args.output.exists() and not args.force:
        sys.exit(f'{args.output} байна. Таны засварыг дарахгүйн тулд зогслоо; --force эсвэл өөр --output.')
    config = json.loads((ROOT / 'config/knowledge-topics.json').read_text(encoding='utf-8-sig'))
    tree = build_tree(config, load_inputs(ROOT))
    missing = [t['topic_id'] for t in tree['topics'] if t['topic_id'] not in SKIP and t['topic_id'] not in ASK]
    if missing:
        sys.exit(f'ASK-д тайлбаргүй шинэ сэдэв: {missing}')
    pages = {p['content_id']: p for p in tree['records']['pages']}
    wb = load_workbook(RECEPTION)
    del wb['Заавар']
    topics = [t for t in tree['topics'] if t['topic_id'] not in SKIP]
    n_frames = sum(t['parent_id'] == 'nmct' for t in topics)
    _, tree_last = tree_sheet(wb, tree, pages)
    _, known_last = known_sheet(wb, tree)
    guide_sheet(wb, n_frames, len(topics) - n_frames, known_last - 1)
    new_topic_sheet(wb)
    progress_sheet(wb, tree_last, known_last)
    for ws in wb.worksheets:
        ws.page_setup.orientation = 'landscape'
        ws.page_setup.paperSize = ws.PAPERSIZE_A4
        ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.print_title_rows = None if ws.title in ('Заавар', 'Явц') else '1:1'
    wb.active = 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    wb.save(args.output)
    print(json.dumps(dict(output=str(args.output), frames=n_frames, topics=len(topics) - n_frames,
                          known_answers=known_last - 1, sheets=wb.sheetnames), ensure_ascii=False))


if __name__ == '__main__':
    main()
