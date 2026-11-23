"""Seminar deck v107 (2026-11-23): the supervisor's advice of 11/23.

The user met the supervisor on 11/23 and relayed: in the thesis figures the colours of «зочин» and «хүснэгт оруулах»
were too alike; the numbers on the figures are not needed because the caption and the text explain them; the deck
should show the state of the thesis writing («ийм ийм хэсгээ хийсэн, тэр дундаа арга зүйгээ илүү дэлгэрэнгүй»).

Changes: a new slide 5 «ДИПЛОМЫН БИЧВЭРИЙН ЯВЦ» (a copy of slide 4's table layout, checklist marks as advised on
11/16); the use case slide's visitor actors move from teal to the blue of the thesis figure (palette.tex nmBlueS /
nmBlueD); the knowledge-tree legend loses its «(8 хүрээ)», «(3 хүрээ)» counts; the system-structure picture is the
re-exported thesis figure without step numbers; printed page numbers after slide 4 move by one. Every other slide is
v106 as it was (slides 2–3 were confirmed by the user on 11/15).

    python tools/nmct_slides/update_seminar_v107.py <pylibs> <base v106> <out v107> <system_structure.png>
"""
import copy
import sys

sys.path.insert(0, sys.argv[1])
from pptx import Presentation                                    # noqa: E402
from pptx.dml.color import RGBColor                              # noqa: E402
from pptx.util import Emu                                        # noqa: E402

BASE, OUT, STRUCTURE_PNG = sys.argv[2:5]
R_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
DONE_TITLE = 'ЭНЭ 7 ХОНОГТ ХИЙСЭН АЖИЛ'
THESIS_TITLE = 'ДИПЛОМЫН БИЧВЭРИЙН ЯВЦ'
# The teacher draft (thesis/main_teacher.tex) as built on 11/23; ✓ written, ☐ waits for the locked question set.
THESIS_STATE = [
    ('Бүлэг', 'Бичсэн хэсэг (багшид үзүүлэх ноорог, 11/23)'),
    ('1. Удиртгал', '✓ Үндэслэл, зорилго, зорилт, хамрах хүрээ, use case диаграмм'),
    ('2. Онол, өнөөгийн түвшин', '✓ RAG, мэдлэгийн мод, Монгол хэлний яриа таних, төсөөтэй систем, шинэлэг тал'),
    ('3. Арга зүй (дэлгэрэнгүй болгосон)',
     '✓ Шаардлага, мэдээлэл цуглуулсан арга, мэдлэгийн мод, системийн бүтэц ба 3 диаграмм, үнэлэх арга'),
    ('3.7 Яриа таних аргыг сонгох туршилт',
     '✓ Ижил 12 бичлэгээр Whisper, Gemini-г харьцуулав: алдаа ойролцоо → API-аар ажилладаг Gemini-г сонгосон'),
    ('4. Үр дүн', '✓ Цуглуулсан мэдээлэл, сэдвийн хамрах байдал, туршилтын үр дүн   ☐\u00a0Системийн\u00a0үнэлгээ'),
    ('5. Цаашдын ажил', '✓ Дараагийн 7 ажил'),
    ('Багшийн зөвлөгөө (11/23)', '✓ Зургийн өнгө, тоог засав; «Бүлгийн дүгнэлт»-ийг хасав; хоосон зайг цэгцлэв'),
]
TEAL = (RGBColor(0x80, 0xCB, 0xC4), RGBColor(0x00, 0x69, 0x5C))
BLUE = (RGBColor(0x64, 0xB5, 0xF6), RGBColor(0x0D, 0x47, 0xA1))   # palette.tex nmBlueS / nmBlueD

deck = Presentation(BASE)
slides = list(deck.slides)
assert len(slides) == 14, 'expected the 14-slide v106'


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


def page_number(slide):
    """The printed number in the bottom-right corner; its shape name differs between slides (TextBox 8, 14, 15…)."""
    return next(shape for shape in text_shapes(slide.shapes) if shape.text_frame.text.strip().isdigit()
                and shape.left > Emu(11000000) and shape.top > Emu(6900000))


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


def text_shapes(container):
    for shape in container:
        if shape.shape_type == 6:
            yield from text_shapes(shape.shapes)
        elif shape.has_text_frame:
            yield shape


# 1. a new slide after «done this week»: the state of the thesis writing
done = slide_with(DONE_TITLE)
thesis = duplicate(done)
title = next(shape for shape in text_shapes(thesis.shapes) if shape.text_frame.text == DONE_TITLE)
set_paragraph(title.text_frame.paragraphs[0], THESIS_TITLE)
underline = next(shape for shape in thesis.shapes if shape.name == 'AutoShape 13')
underline.width = Emu(int(underline.width * len(THESIS_TITLE) / len(DONE_TITLE)))
frame = table_of(thesis)
fill_table(frame, THESIS_STATE)
total = sum(column.width for column in frame.table.columns)
first = int(total * 0.34)
frame.table.columns[0].width, frame.table.columns[1].width = Emu(first), Emu(total - first)
order = deck.slides._sldIdLst
moved = list(order)[-1]
order.remove(moved)
order.insert(slides.index(done) + 1, moved)

# 2. use case slide: the visitor actors and their legend key in the thesis blue instead of teal
use_case = slide_with('USE CASE ДИАГРАММ')
recoloured = 0
for shape in use_case.shapes:
    if shape.shape_type == 1 and shape.fill.type == 1 and shape.fill.fore_color.rgb == TEAL[0]:
        shape.fill.fore_color.rgb, shape.line.color.rgb = BLUE
        recoloured += 1
assert recoloured == 4, recoloured                # three actors and the legend key

# 3. knowledge tree legend: no counts on the figure (the speech names them)
tree = slide_with('МЭДЛЭГИЙН МОД')
trimmed = 0
for shape in text_shapes(tree.shapes):
    for paragraph in shape.text_frame.paragraphs:
        for run in paragraph.runs:
            for count in (' (8 хүрээ)', ' (3 хүрээ)'):
                if count in run.text:
                    run.text = run.text.replace(count, '')
                    trimmed += 1
assert trimmed == 2, trimmed

# 4. system structure: the thesis figure re-exported without step numbers (same 1308 x 1104 size)
structure = slide_with('СИСТЕМИЙН БҮТЭЦ')
picture = next(shape for shape in structure.shapes if shape.shape_type == 13)
image_part = structure.part.related_part(picture._element.blipFill.blip.rEmbed)
with open(STRUCTURE_PNG, 'rb') as handle:
    image_part._blob = handle.read()

# 5. printed page numbers: the new slide is 5, the ones after it move by one
for number, slide in enumerate(deck.slides, start=1):
    try:
        box = page_number(slide)
    except StopIteration:
        continue
    set_paragraph(box.text_frame.paragraphs[0], str(number))

deck.save(OUT)
sys.stdout.reconfigure(encoding='utf-8')
print(OUT, len(deck.slides), 'slides')
