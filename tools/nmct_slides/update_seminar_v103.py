"""Seminar deck v103 (2026-11-20) for the 11/24 seminar: v102 with the weekly slides put back on the plan.

The user, 2026-11-20: the seminar reports the work the plan and the previous deck's «Дараагийн 7 хоног»
slide promised, nothing else. v102 had listed development done ahead of the plan on the «done this
week» slide and put development numbers on the evaluation slide. v103 reports against the five lines
promised on 11/17 and states the evaluation problem as the plan's W04 does: a set of questions whose
right answers are written before the system is measured.

Slides 1–3, 5–8, 10, 11, 13 are untouched (the user confirmed the diagrams of v102 on 11/20).

    python tools/nmct_slides/update_seminar_v103.py <pylibs> <base v102> <out v103>
"""
import copy
import sys

sys.path.insert(0, sys.argv[1])
from pptx import Presentation                                    # noqa: E402
from pptx.util import Emu                                        # noqa: E402

BASE, OUT = sys.argv[2:4]
# What the 11/17 deck promised for this week, in its order, plus the teachers' advice of 11/17.
WORK_DONE = [
    ('Системийн үнэлгээний асуудал: шалгах асуултын багц',
     'Ресепшний сэдвүүдээр 50 асуулт бэлдэж, өөрөө уншиж шалгасан; сургалтын албатай тулгана'),
    ('Монгол судалгааны ажил унших', '6 ажил сонгосон; уншиж байна'),
    ('Карьер төвөөс мэдээлэл авах', 'Асуултын хуудсаа бэлдсэн'),
    ('Мэдээллийн багцаа цэгцэлсэн',
     'Албадын ажлын цаг 08:00–17:00, цайны цаг 12:40–13:20; ажлын анкет, ярилцлага → Сургалтын алба'),
    ('Судалгаа: SQuAD 2.0', 'Уншиж байна: мэдээлэл нь байхгүй асуултыг яаж шалгах'),
    ('Багшийн зөвлөгөөг тусгасан', 'Use case диаграммын үг; зургийн өнгийг бүлгээр ялгасан'),
]
EVALUATION = [
    ('Асуултын төрөл', 'Тоо', 'Юуг шалгах'),
    ('Сургуулийн мэдээллийн асуулт', '20', 'Хариулт зөв эсэх; зөв эх сурвалжийг харуулсан эсэх'),
    ('Нэг дор хоёр зүйл асуусан асуулт', '9', 'Хоёр хэсэгт хоёуланд нь хариулсан эсэх'),
    ('Өрөө, анги, багш, хуваарийн асуулт', '9', 'Сургуулийн хүснэгтээс зөв мөрийг олсон эсэх'),
    ('Мэдээлэл нь байхгүй асуулт', '12', 'Хариулт зохиохгүй, хэнд, хаана хандахыг заасан эсэх'),
]
EVALUATION_NOTES = [
    ('Асуудал:', ' системийн хариулт зөв эсэхийг юугаар, яаж хэмжих вэ.'),
    ('Шийдэл:', ' зөв хариултыг нь урьдчилан бичсэн 50 асуултын багц бэлдсэн. Сургалтын албатай тулгаж түгжсэний дараа системийг хэмжинэ.'),
]
NEXT_WEEK = [
    'Үзлэг №1-ийн слайд, яриаг бэлдэх',
    'Бичвэрийн эхний бүлгүүдийг засах: удиртгал, онол, арга зүй',
    'Шалгах асуултыг сургалтын албатай тулгаж түгжих',
    'Системийн үзүүлэнг бэлдэх',
    'Судалгаа: RRF — хайлтын дүнг нэгтгэх арга',
]

deck = Presentation(BASE)
slides = list(deck.slides)
assert len(slides) == 13, 'expected the 13-slide v102'


def set_paragraph(paragraph, text):
    """Replace a paragraph's text, keeping the first run's formatting."""
    runs = paragraph.runs
    runs[0].text = text
    for run in runs[1:]:
        run.text = ''


def table_of(slide):
    return next(shape for shape in slide.shapes if getattr(shape, 'has_table', False) and shape.has_table)


def slide_with(text):
    return next(slide for slide in slides if text in slide._element.xml)


def fill_table(frame, rows):
    """Write the rows, adding copies of the last row when the table is shorter; the frame grows with it."""
    table = frame.table
    while len(table.rows) < len(rows):
        table._tbl.append(copy.deepcopy(list(table.rows)[-1]._tr))
    assert len(table.rows) == len(rows), 'table has more rows than the new content'
    for row, texts in zip(table.rows, rows):
        for cell, text in zip(row.cells, texts):
            set_paragraph(cell.text_frame.paragraphs[0], text)
    frame.height = sum(row.height for row in table.rows)


# 1. done this week: the promised lines only
done = table_of(slide_with('ХИЙСЭН АЖИЛ'))
fill_table(done, [tuple(cell.text_frame.text for cell in done.table.rows[0].cells)] + WORK_DONE)

# 2. the problem being solved: how the system will be measured (no development numbers)
problem = slide_with('ШИЙДЭХ АСУУДАЛ')
frame = table_of(problem)
fill_table(frame, EVALUATION)
for column, width in zip(frame.table.columns, (4200000, 1100000, 5164800)):
    column.width = Emu(width)
notes = next(shape for shape in problem.shapes if shape.has_text_frame and shape.text_frame.text.startswith('Асуудал:'))
notes.top = frame.top + frame.height + Emu(330000)
for paragraph, (head, rest) in zip(notes.text_frame.paragraphs, EVALUATION_NOTES):
    first, second = paragraph.runs[0], paragraph.runs[1]
    first.text, second.text = head, rest

# 3. next week: W05 of the plan
upcoming = next(shape for shape in slide_with('ДАРААГИЙН 7 ХОНОГ').shapes
                if shape.has_text_frame and shape.name == 'TextBox 14')
paragraphs = upcoming.text_frame.paragraphs
assert len(paragraphs) == len(NEXT_WEEK), 'next-week list is expected to have five lines'
for paragraph, text in zip(paragraphs, NEXT_WEEK):
    set_paragraph(paragraph, text)

deck.save(OUT)
sys.stdout.reconfigure(encoding='utf-8')
print(OUT)
