"""Seminar deck v104 (2026-11-23) for the 11/24 seminar: v103 with this week's actual state.

The user, 2026-11-23: «ppt хий энэ долоо хоногийн хийсэн» — they read three Mongolian research works (MON01,
MON02, MON05), the career centre answered, the 40 check questions are «боломжийн», and they asked how Latin-script
and abbreviated questions («ene bagsh haana bdag ve», «end bn uu») will be handled and reported to the teacher.
Only the plan's / previous deck's promised lines are reported (two-track rule, 11/20); development done ahead of the
plan stays off the slides.

Changes: slide 4 (done this week), slide 9 (40 questions, 20 / 10 / 10), a new slide 10 (the Latin-script and
abbreviation problem, a copy of slide 9's layout), the next-week slide; the printed page numbers after slide 9 move
by one. Slides 1–3, 5–8 and the plan slides are untouched (the user confirmed them on 11/15–11/20).

    python tools/nmct_slides/update_seminar_v104.py <pylibs> <base v103> <out v104>
"""
import copy
import sys

sys.path.insert(0, sys.argv[1])
from pptx import Presentation                                    # noqa: E402
from pptx.util import Emu, Pt                                    # noqa: E402

BASE, OUT = sys.argv[2:4]
R_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'

# The 11/17 deck's promised lines for this week, in its order, with their state on 11/23 (the user's answers).
WORK_DONE = [
    ('Системийн үнэлгээний асуудал: шалгах асуултын багц',
     'Бодит хүн юу асуухыг судалж 40 асуулт бэлдсэн (20 / 10 / 10); сургалтын албатай тулгаж түгжинэ'),
    ('Монгол судалгааны ажил унших', '6 ажлаас 3-ыг уншсан: дохионы хэл, уртын дуу, эрдэм шинжилгээний бичлэг'),
    ('Карьер төвөөс мэдээлэл авах', 'Хариу ирсэн'),
    ('Мэдээллийн багцаа цэгцэлсэн',
     'Албадын ажлын цаг 08:00–17:00, цайны цаг 12:40–13:20; ажлын анкет, ярилцлага → Сургалтын алба'),
    ('Судалгаа: SQuAD 2.0', 'Монгол хөтөч бэлэн; энэ долоо хоногт уншина'),
    ('Бичвэрийн хэллэг (11/16-ны зөвлөгөө)', 'Монгол 25 бүтээлийн бүтэц, хэллэгтэй тулгаж 1–5-р бүлгийг засав'),
    ('Багшийн зөвлөгөөг тусгасан (11/17)', 'Use case диаграммын үг; зургийн өнгийг бүлгээр ялгасан'),
]
EVALUATION = [
    ('Асуултын төрөл', 'Тоо', 'Юуг шалгах'),
    ('Сургуулийн мэдээллийн асуулт', '20', 'Хариулт зөв эсэх; зөв эх сурвалжийг харуулсан эсэх'),
    ('Өрөө, анги, багш, хуваарийн асуулт', '10', 'Сургуулийн хүснэгтээс зөв мөрийг олсон эсэх'),
    ('Мэдээлэл нь байхгүй асуулт', '10', 'Хариулт зохиохгүй, хэнд, хаана хандахыг заасан эсэх'),
]
EVALUATION_NOTES = [
    ('Асуудал:', ' системийн хариулт зөв эсэхийг юугаар, яаж хэмжих вэ.'),
    ('Шийдэл:', ' эцэг эх, элсэгч, оюутан, зочин, ажил хайгчийн нэрийн өмнөөс тэдний бичдэг, ярьдаг хэлбэрээр 40 асуулт '
                'бичиж, зөв хариултыг нь урьдчилан тэмдэглэсэн. Сургалтын албатай тулгаж түгжсэний дараа системийг '
                'хэмжинэ.'),
]
LATIN_TITLE = 'ШИЙДЭХ АСУУДАЛ: ЛАТИН, ТОВЧИЛСОН БИЧИГ'
LATIN = [
    ('Ингэж бичсэн асуулт', 'Систем одоо', 'Зөв ойлгох нь'),
    ('ene bagsh haana bdag ve', 'Олдсонгүй гэсэн', 'Энэ багш хаана байдаг вэ?'),
    ('end bn uu', 'Олдсонгүй гэсэн', 'Энд байна уу?'),
    ('ene basgh haana bdag ve', 'Олдсонгүй гэсэн', '«basgh» → «bagsh» → багш'),
    ('Сургалтын алба хаана бдаг вэ', 'Олдсонгүй гэсэн', '«бдаг» → байдаг'),
]
LATIN_NOTES = [
    ('Асуудал:', ' туршихаар бичсэн 9 латин, 2 товчилсон асуултад систем одоо «олдсонгүй» гэж хариулсан (11/23). '
                 'Латин «u» нь у, ү, ө, «o» нь о, ө-ийн аль нь ч байж болно.'),
    ('Санал:', ' латиныг кирилл рүү хөрвүүлж сургуулийн үгсийн жагсаалтаар зөвийг сонгох; товчилсон үгийн жагсаалт; '
               'ойролцоо үгээр засах; «Ингэж ойлголоо: …» гэж харуулах (Byambadorj нар, 2020).'),
    ('Багшаас:', ' энэ асуудлыг судалгааны хүрээнд оруулах уу?'),
]
# W05 of the plan: Үзлэг №1 material, the first chapters, reading (RRF is read; Bruch et al. is the W05 paper left).
NEXT_WEEK = [
    'Үзлэг №1-ийн слайд, яриа, үзүүлэн бэлдэх (12/01)',
    '40 асуултыг сургалтын албатай тулгаж түгжих',
    'Дипломын эхний бүлгүүдийг багшийн саналаар засах',
    'Монгол судалгааны үлдсэн 3 ажил, SQuAD 2.0-г унших',
    'Судалгаа: хайлтын дүнг нэгтгэх аргууд (Bruch нар)',
]

deck = Presentation(BASE)
slides = list(deck.slides)
assert len(slides) == 13, 'expected the 13-slide v103'


def set_paragraph(paragraph, text):
    """Replace a paragraph's text, keeping the first run's formatting."""
    runs = paragraph.runs
    runs[0].text = text
    for run in runs[1:]:
        run.text = ''


def table_of(slide):
    return next(shape for shape in slide.shapes if getattr(shape, 'has_table', False) and shape.has_table)


def slide_with(text):
    return next(slide for slide in deck.slides if text in slide._element.xml)


def fill_table(frame, rows):
    """Write the rows, adding copies of the last row when the table is shorter; the frame grows with it."""
    table = frame.table
    while len(table.rows) < len(rows):
        table._tbl.append(copy.deepcopy(list(table.rows)[-1]._tr))
    while len(table.rows) > len(rows):
        table._tbl.remove(list(table.rows)[-1]._tr)
    for row, texts in zip(table.rows, rows):
        for cell, text in zip(row.cells, texts):
            set_paragraph(cell.text_frame.paragraphs[0], text)
    frame.height = sum(row.height for row in table.rows)


def notes_box(slide):
    return next(shape for shape in slide.shapes if shape.has_text_frame and shape.text_frame.text.startswith('Асуудал:'))


def fill_notes(box, parts, size=None):
    """Bold head + plain rest per paragraph; paragraphs are copied from the last one when more are needed."""
    body = box.text_frame._txBody
    while len(box.text_frame.paragraphs) < len(parts):
        body.append(copy.deepcopy(box.text_frame.paragraphs[-1]._p))
    for paragraph, (head, rest) in zip(box.text_frame.paragraphs, parts):
        first, second = paragraph.runs[0], paragraph.runs[1]
        first.text, second.text = head, rest
        if size:
            first.font.size = second.font.size = size


def page_number(slide):
    return next(shape for shape in slide.shapes if shape.has_text_frame and shape.name == 'TextBox 15'
                and shape.text_frame.text.strip().isdigit())


def duplicate(source):
    """A copy of a slide at the end of the deck: shapes, and the images they use under new relationship ids."""
    new = deck.slides.add_slide(source.slide_layout)
    for shape in list(new.shapes):
        shape._element.getparent().remove(shape._element)
    renamed = {}
    for rel_id, rel in source.part.rels.items():
        if rel.reltype.endswith('/image'):
            renamed[rel_id] = new.part.relate_to(rel.target_part, rel.reltype)
    for shape in source.shapes:
        element = copy.deepcopy(shape._element)
        for node in element.iter():
            for attribute in ('embed', 'link', 'id'):
                key = '{%s}%s' % (R_NS, attribute)
                if node.get(key) in renamed:
                    node.set(key, renamed[node.get(key)])
        new.shapes._spTree.append(element)
    return new


# 1. done this week: the promised lines with their 11/23 state
done = table_of(slide_with('ХИЙСЭН АЖИЛ'))
fill_table(done, [tuple(cell.text_frame.text for cell in done.table.rows[0].cells)] + WORK_DONE)

# 2. the evaluation problem: 40 questions written as people ask
evaluation = slide_with('ШИЙДЭХ АСУУДАЛ: СИСТЕМИЙН ҮНЭЛГЭЭ')
frame = table_of(evaluation)
fill_table(frame, EVALUATION)
notes = notes_box(evaluation)
notes.top = frame.top + frame.height + Emu(330000)
fill_notes(notes, EVALUATION_NOTES)

# 3. a new slide after it: Latin-script and abbreviated questions
latin = duplicate(evaluation)
title = next(shape for group in latin.shapes if group.shape_type == 6 for shape in group.shapes
             if shape.has_text_frame and 'ШИЙДЭХ АСУУДАЛ' in shape.text_frame.text)
set_paragraph(title.text_frame.paragraphs[0], LATIN_TITLE)
underline = next(shape for shape in latin.shapes if shape.name == 'AutoShape 13')
underline.width = Emu(int(underline.width * len(LATIN_TITLE) / len('ШИЙДЭХ АСУУДАЛ: СИСТЕМИЙН ҮНЭЛГЭЭ')))
frame = table_of(latin)
fill_table(frame, LATIN)
for column, width in zip(frame.table.columns, (3700000, 2000000, 4764800)):
    column.width = Emu(width)
notes = notes_box(latin)
notes.top = frame.top + frame.height + Emu(250000)
fill_notes(notes, LATIN_NOTES, size=Pt(16))
order = deck.slides._sldIdLst
moved = list(order)[-1]
order.remove(moved)
order.insert(slides.index(evaluation) + 1, moved)

# 4. printed page numbers: the new slide is 10, the ones after it move by one
for number, slide in enumerate(deck.slides, start=1):
    try:
        box = page_number(slide)
    except StopIteration:
        continue
    set_paragraph(box.text_frame.paragraphs[0], str(number))

# 5. next week: the rest of W05 and Үзлэг №1
upcoming = next(shape for shape in slide_with('ДАРААГИЙН 7 ХОНОГ').shapes
                if shape.has_text_frame and shape.name == 'TextBox 14')
paragraphs = upcoming.text_frame.paragraphs
assert len(paragraphs) == len(NEXT_WEEK), 'next-week list is expected to have five lines'
for paragraph, text in zip(paragraphs, NEXT_WEEK):
    set_paragraph(paragraph, text)

deck.save(OUT)
sys.stdout.reconfigure(encoding='utf-8')
print(OUT, len(deck.slides), 'slides')
