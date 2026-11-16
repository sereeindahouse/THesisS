"""Seminar deck v96 (2026-11-17): v95 plus the supervisor's remarks of 2026-11-16.

Base is the deck last saved in МИНИЙ-ДИПЛОМ/02_Семинар (v95). «Зорилго», «Зорилт» and every slide
not listed here stay as they are. Changes:
  1. title slide: the line «Дипломын ажлын долоо хоногийн тайлан» is removed, the date sits in the
     centre, the names sit on the right
  2. «хийсэн ажил» slide: the reading row now covers every paper cited in the draft, and a row says
     the thesis text was started
  3. reception slide: a narrow first column turns the table into a checklist
     (✓ = the information is in the system, ☐ = to be collected) with a one-line key under it
  4. use case slide: titled «USE CASE ДИАГРАММ»; the picture is the redrawn thesis figure
     (actors as «actor» rectangles, equal-sized ellipses on a grid, colour)
  5. system structure slide: the picture is the coloured thesis figure

python-pptx is not installed in the project venv; pass its folder as the first argument:
    python tools/nmct_slides/update_seminar_v96.py <pylibs> <base v95> <out v96> <usecase png> <structure png>
PowerPoint itself is never started (COM hangs on this machine).
"""
import copy
import sys

sys.path.insert(0, sys.argv[1])
from pptx import Presentation                                    # noqa: E402
from pptx.dml.color import RGBColor                              # noqa: E402
from pptx.enum.text import PP_ALIGN                              # noqa: E402
from pptx.oxml.ns import qn                                      # noqa: E402
from pptx.util import Emu, Pt                                    # noqa: E402

BASE, OUT, USECASE_PNG, STRUCTURE_PNG = sys.argv[2:6]

HAVE, COLLECT, NOT_A_FACT = '✓', '☐', '–'
MARK_COLOUR = {HAVE: RGBColor(0x2E, 0x7D, 0x32), COLLECT: RGBColor(0xC5, 0x5A, 0x11),
               NOT_A_FACT: RGBColor(0x59, 0x59, 0x59), '': RGBColor(0x00, 0x00, 0x00)}
# first cell of the row -> checklist mark
RECEPTION = {
    'Сургалтын төлбөр': HAVE,
    'Багшийн имэйл': HAVE,
    'Ажлын байрны анкет': COLLECT,
    'Ярилцлагад хаана очих': COLLECT,
    'Гадны хүүхдэд давтлага': COLLECT,
    'Сургалтын орчин': HAVE,
    'Харилцаа, хандлага': NOT_A_FACT,
    'Дотуур байр': COLLECT,
}
READING_ROW = ('Судалгааны өгүүллүүд уншсан',
               'Дипломын нооргт иш татсан 9 өгүүлэл: RAG, хайлтын арга, яриа таних, их сургуулийн туслах систем')
WRITING_ROW = ('Дипломын бичвэрээ эхлүүлсэн',
               'Эхний ноорог 21 хуудас: удиртгал, онол, арга зүй; багшид үзүүлсэн')


def set_paragraph(paragraph, text):
    """Replace a paragraph's text, keeping the first run's formatting."""
    runs = paragraph.runs
    runs[0].text = text
    for run in runs[1:]:
        run.text = ''


def table_of(slide):
    return next(shape for shape in slide.shapes if getattr(shape, 'has_table', False) and shape.has_table)


def slide_with(slides, text):
    """The slide whose XML holds the text (titles sit inside a group)."""
    return next(slide for slide in slides if text in slide._element.xml)


def replace_picture(slide, png, left, top, width, height):
    """Swap the slide's picture for png, scaled to fit the given box and centred in it."""
    old = next(shape for shape in slide.shapes if shape.shape_type == 13)
    added = slide.shapes.add_picture(png, left, top)
    scale = min(width / added.width, height / added.height)
    added.width, added.height = int(added.width * scale), int(added.height * scale)
    added.left = left + (width - added.width) // 2
    added.top = top + (height - added.height) // 2
    old._element.getparent().remove(old._element)


deck = Presentation(BASE)
slides = list(deck.slides)

# 1. title slide
title = slides[0]
shapes = {shape.text_frame.text.strip().split('\n')[0]: shape
          for shape in title.shapes if shape.has_text_frame and shape.text_frame.text.strip()}
weekly = shapes['Дипломын ажлын долоо хоногийн тайлан']
weekly._element.getparent().remove(weekly._element)
names = next(shape for key, shape in shapes.items() if key.startswith('Оюутан'))
set_paragraph(names.text_frame.paragraphs[0], 'Оюутан: Б.Сэргэлэн')
set_paragraph(names.text_frame.paragraphs[1], 'Удирдагч багш: Т.Хандсүрэн')
names.left, names.top, names.width = Emu(6350000), Emu(5380000), Emu(3700000)
dates = next(shape for key, shape in shapes.items() if key.startswith('2026.10'))
dates.left, dates.top = (deck.slide_width - dates.width) // 2, Emu(6480000)

# 2. work done
done_frame = table_of(slide_with(slides, 'ХИЙСЭН АЖИЛ'))
done = done_frame.table
reading = next(row for row in done.rows if row.cells[0].text_frame.text.strip() == 'RAG-ийн өгүүлэл уншсан')
for cell, text in zip(reading.cells, READING_ROW):
    set_paragraph(cell.text_frame.paragraphs[0], text)
writing_tr = copy.deepcopy(reading._tr)
done._tbl.append(writing_tr)
writing = list(done.rows)[-1]
for cell, text in zip(writing.cells, WRITING_ROW):
    set_paragraph(cell.text_frame.paragraphs[0], text)
done_frame.top = Emu(2250000)
done_frame.height = sum(row.height for row in done.rows)

# 3. reception checklist: one narrow column in front
reception_slide = slide_with(slides, 'РЕСЕПШНД ЮУ АСУУДАГ ВЭ')
reception_frame = table_of(reception_slide)
reception = reception_frame.table
if len(reception.columns) != 3:
    raise SystemExit('reception table is expected to have 3 columns')
grid = reception._tbl.tblGrid
first_col = grid.findall(qn('a:gridCol'))[0]
grid.insert(list(grid).index(first_col), copy.deepcopy(first_col))
for tr in reception._tbl.findall(qn('a:tr')):
    first_tc = tr.findall(qn('a:tc'))[0]
    tr.insert(list(tr).index(first_tc), copy.deepcopy(first_tc))
for column, width in zip(reception.columns, (560000, 2900000, 2000000, 3849100)):
    column.width = Emu(width)
seen = set()
for index, row in enumerate(reception.rows):
    topic = row.cells[1].text_frame.text.strip()
    if index == 0:
        mark = ''
    else:
        key = next((name for name in RECEPTION if topic.startswith(name)), None)
        if key is None:
            raise SystemExit(f'unexpected reception row «{topic}»')
        mark = RECEPTION[key]
        seen.add(key)
    paragraph = row.cells[0].text_frame.paragraphs[0]
    set_paragraph(paragraph, mark)
    paragraph.alignment = PP_ALIGN.CENTER
    run = paragraph.runs[0]
    run.font.name = 'Segoe UI Symbol'
    run.font.bold = True
    run.font.color.rgb = MARK_COLOUR[mark]
if seen != set(RECEPTION):
    raise SystemExit(f'rows not found: {sorted(set(RECEPTION) - seen)}')
key_box = reception_slide.shapes.add_textbox(reception_frame.left, reception_frame.top + reception_frame.height + Emu(170000),
                                             reception_frame.width, Emu(330000))
key_paragraph = key_box.text_frame.paragraphs[0]
for mark, label in ((HAVE, ' мэдээлэл системд бий      '), (COLLECT, ' цуглуулна      '),
                    (NOT_A_FACT, ' баримтаар хариулах сэдэв биш')):
    symbol = key_paragraph.add_run()
    symbol.text = mark
    symbol.font.name, symbol.font.bold, symbol.font.size = 'Segoe UI Symbol', True, Pt(14)
    symbol.font.color.rgb = MARK_COLOUR[mark]
    text = key_paragraph.add_run()
    text.text = label
    text.font.name, text.font.size = 'Arial', Pt(13)
    text.font.color.rgb = RGBColor(0x40, 0x40, 0x40)

# 4. use case slide
usecase = slide_with(slides, 'СИСТЕМИЙГ ХЭН, ЮУНД АШИГЛАХ ВЭ')
for shape in usecase.shapes:
    if shape.shape_type == 6:
        for inner in shape.shapes:
            if inner.has_text_frame and inner.text_frame.text.strip() == 'СИСТЕМИЙГ ХЭН, ЮУНД АШИГЛАХ ВЭ':
                set_paragraph(inner.text_frame.paragraphs[0], 'USE CASE ДИАГРАММ')
replace_picture(usecase, USECASE_PNG, Emu(690000), Emu(1800000), Emu(9310000), Emu(4990000))

# 5. system structure picture
structure = next(slide for slide in slides
                 if 'СИСТЕМИЙН БҮТЭЦ' in slide._element.xml and any(shape.shape_type == 13 for shape in slide.shapes))
replace_picture(structure, STRUCTURE_PNG, Emu(2000000), Emu(1760000), Emu(6600000), Emu(5080000))

deck.save(OUT)
print('saved', len(deck.slides), 'slides ->', OUT)
