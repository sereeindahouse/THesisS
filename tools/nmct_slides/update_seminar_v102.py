"""Seminar deck v102 (2026-11-20) for the 11/24 seminar: v101 plus the teachers' advice of 11/17.

What the user passed on (2026-11-20):
  1. «use case диаграмм дээр "Шинэ хувилбарыг шалгаж нийтлэх" гэдэг үгийг зас» -> «Мэдээллийг шалгаж шинэчлэх»;
  2. «графын өнгө өөр байх ёстой, бүгд ижил байна» -> every group has its own colour (thesis/Figures/palette.tex);
  3. «энэ долоо хоногийн ажил дээр "Системийн үнэлгээний асуудал" гэж бич» -> slides 4, 9 and the W04 plan row;
  and the user's own wish: «би өөрөө засдаг болмоор байна» -> the use case diagram and the knowledge tree are
  drawn with PowerPoint shapes (text and colour editable in PowerPoint and Canva), no longer a picture.

Only horizontal and vertical lines are used in the drawn diagrams: Canva showed rotated lines differently
(11/16). Slides 2 and 3 (Зорилго, Зорилт) are not touched — the user approved them (11/15).

    python tools/nmct_slides/update_seminar_v102.py <pylibs> <base v101> <out v102> <system structure png>
"""
import copy
import sys

sys.path.insert(0, sys.argv[1])
from pptx import Presentation                                    # noqa: E402
from pptx.dml.color import RGBColor                              # noqa: E402
from pptx.enum.dml import MSO_LINE                               # noqa: E402
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE            # noqa: E402
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN                  # noqa: E402
from pptx.oxml.ns import qn                                      # noqa: E402
from pptx.util import Emu, Pt                                    # noqa: E402

BASE, OUT, STRUCTURE_PNG = sys.argv[2:5]
FONT = 'Times New Roman'
# Same values as thesis/Figures/palette.tex.
BLUE, BLUE_D = 'BBDEFB', '0D47A1'
TEAL, TEAL_D = '80CBC4', '00695C'
ORANGE, ORANGE_L, ORANGE_D = 'FFB74D', 'FFE0B2', 'BF360C'
GREEN, GREEN_S, GREEN_D = 'C8E6C9', '81C784', '1B5E20'
VIOLET, VIOLET_D = 'E1BEE7', '6A1B9A'

WORK_DONE = [
    ('Системийн үнэлгээний асуудал', 'Шалгах 50 асуултын ноорог бичсэн; системийг асуултаар хэмждэг болсон'),
    ('Хариултын алдааг олж зассан', 'Хариулт олдоогүй үед хариуцсан алба, өрөөг заадаг болсон'),
    ('Сургуулиас мэдээлэл тодруулсан', 'Албадын ажлын цаг 08:00–17:00; ажлын анкет, ярилцлага → Сургалтын алба'),
    ('Ресепшний дэлгэцийн горим хийсэн', 'Том үсэг, сэдвийн товчлуур; хэрэглээгүй үед эхлэл рүү буцна'),
    ('Багшийн зөвлөгөөг тусгасан', 'Use case диаграммын үг; зургийн өнгийг бүлгээр ялгасан'),
]
EVALUATION = [
    ('Шалгах асуулт', 'Хэн хянасан', 'Одоогийн дүн'),
    ('Сайтын мэдээллийн 64 асуулт', 'Хүн хянаагүй ноорог', 'Хариутай 36-аас 34 зөв'),
    ('Шинэ 50 ба ресепшний 30 асуулт', '30-ыг би хянасан; 50 нь хянаагүй ноорог',
     'Хариутай 58-аас 50 зөв; хариугүй 22-оос 21-д зөв татгалзсан'),
]
EVALUATION_NOTES = [
    'Асуудал: эдгээр асуултыг системийг засахдаа ашигласан тул тоонууд эцсийн дүн биш.',
    'Шийдэл: асуулт бүрийг өөрөө хянаж түгжих; ресепшнээс бодит асуулт цуглуулах; засварт ашиглаагүй хэсгээр эцсийн дүнг гаргах.',
]
NEXT_WEEK = [
    'Үзлэг №1-ийн слайд, яриаг бэлдэх',
    'Шалгах асуултыг өөрөө хянаж түгжих',
    'Ресепшнээс бодит асуулт цуглуулах',
    'Арга зүйн бүлгийг системийн өөрчлөлтөөр шинэчлэх',
    'Судалгаа: RRF — хайлтын дүнг нэгтгэх арга',
]

deck = Presentation(BASE)
slides = list(deck.slides)
assert len(slides) == 13, 'expected the 13-slide v101'


def rgb(value):
    return RGBColor.from_string(value)


def set_paragraph(paragraph, text, like=None):
    """Replace a paragraph's text, keeping the first run's formatting (an empty cell copies `like`)."""
    runs = paragraph.runs
    if not runs:
        run = paragraph.add_run()
        if like is not None and like._r.rPr is not None:
            run._r.insert(0, copy.deepcopy(like._r.rPr))
        runs = (run,)
    runs[0].text = text
    for run in runs[1:]:
        run.text = ''


def table_of(slide):
    return next(shape for shape in slide.shapes if getattr(shape, 'has_table', False) and shape.has_table)


def slide_with(text):
    return next(slide for slide in slides if text in slide._element.xml)


def title_box(slide):
    for shape in slide.shapes:
        if shape.shape_type == 6:
            for inner in shape.shapes:
                if inner.has_text_frame and inner.text_frame.text.strip():
                    return inner
    raise SystemExit('slide title not found')


def remove(shape):
    shape._element.getparent().remove(shape._element)


def node(slide, kind, left, top, width, height, lines, fill, border, colour='000000'):
    """One editable shape with centred text; lines = [(text, point size, bold)]."""
    shape = slide.shapes.add_shape(kind, Emu(int(left)), Emu(int(top)), Emu(int(width)), Emu(int(height)))
    shape.fill.solid()
    shape.fill.fore_color.rgb = rgb(fill)
    shape.line.color.rgb = rgb(border)
    shape.line.width = Pt(1.25)
    style = shape._element.find(qn('p:style'))        # theme style brings a shadow and white text; all is explicit here
    if style is not None:
        shape._element.remove(style)
    frame = shape.text_frame
    frame.word_wrap = True
    frame.vertical_anchor = MSO_ANCHOR.MIDDLE
    frame.margin_left = frame.margin_right = Emu(30000)
    frame.margin_top = frame.margin_bottom = Emu(10000)
    for index, (text, size, bold) in enumerate(lines):
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        paragraph.alignment = PP_ALIGN.CENTER
        run = paragraph.add_run()
        run.text = text
        run.font.name, run.font.size, run.font.bold = FONT, Pt(size), bold
        run.font.color.rgb = rgb(colour)
    return shape


def line(slide, x1, y1, x2, y2, dashed=False, arrow=False, colour='000000', width=1.0):
    connector = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Emu(int(x1)), Emu(int(y1)), Emu(int(x2)), Emu(int(y2)))
    connector.line.color.rgb = rgb(colour)
    connector.line.width = Pt(width)
    if dashed:
        connector.line.dash_style = MSO_LINE.DASH
    style = connector._element.find(qn('p:style'))
    if style is not None:
        connector._element.remove(style)
    if arrow:
        ln = connector.line._get_or_add_ln()
        ln.append(ln.makeelement(qn('a:tailEnd'), {'type': 'triangle', 'w': 'med', 'len': 'med'}))
    return connector


def label(slide, left, top, width, height, text, size=10, bold=False, fill=None, align=PP_ALIGN.CENTER):
    box = slide.shapes.add_textbox(Emu(int(left)), Emu(int(top)), Emu(int(width)), Emu(int(height)))
    if fill:
        box.fill.solid()
        box.fill.fore_color.rgb = rgb(fill)
    frame = box.text_frame
    frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = Emu(0)
    frame.vertical_anchor = MSO_ANCHOR.MIDDLE
    frame.word_wrap = True
    paragraph = frame.paragraphs[0]
    paragraph.alignment = align
    run = paragraph.add_run()
    run.text = text
    run.font.name, run.font.size, run.font.bold = FONT, Pt(size), bold
    run.font.color.rgb = rgb('000000')
    return box


def legend(slide, left, top, entries, gap=260000):
    """Small colour keys with their meaning, so colour is never the only carrier.

    `fills` lists every fill the entry stands for (an actor's strong tint and its actions' pale one).
    """
    x = left
    for fills, border, text, width in entries:
        for fill in fills:
            node(slide, MSO_SHAPE.RECTANGLE, x, top + 30000, 190000, 130000, [], fill, border)
            x += 230000
        label(slide, x + 10000, top, width, 190000, text, size=10, align=PP_ALIGN.LEFT)
        x += 10000 + width + gap


# 1. title slide: the seminar date
date_box = next(shape for shape in slides[0].shapes if shape.has_text_frame and '2026.11.17' in shape.text_frame.text)
set_paragraph(next(p for p in date_box.text_frame.paragraphs if p.text.strip() == '2026.11.17'), '2026.11.24')

# 2. work done this week, led by the teachers' wording
done = table_of(slide_with('ХИЙСЭН АЖИЛ')).table
rows = list(done.rows)
assert len(rows) == len(WORK_DONE) + 1, 'work table is expected to have five rows'
for row, texts in zip(rows[1:], WORK_DONE):
    for cell, text in zip(row.cells, texts):
        set_paragraph(cell.text_frame.paragraphs[0], text)

# 3. reception checklist: the user decided on 11/18 that interviews are referred to the training office
reception = table_of(slide_with('РЕСЕПШНД ЮУ АСУУДАГ ВЭ')).table
interview = next(row for row in reception.rows if row.cells[1].text_frame.text.strip().startswith('Ярилцлагад хаана очих'))
mark = interview.cells[0].text_frame.paragraphs[0]
set_paragraph(mark, '✓')
mark.runs[0].font.color.rgb = RGBColor(0x2E, 0x7D, 0x32)
set_paragraph(interview.cells[3].text_frame.paragraphs[0], 'Сургалтын алба руу чиглүүлнэ')

# 4. use case diagram: drawn shapes instead of the picture
usecase = slide_with('USE CASE ДИАГРАММ')
remove(next(shape for shape in usecase.shapes if shape.shape_type == 6 and shape.name == 'Group 15'))
X0, X1, Y0, Y1 = 640000, 11440000, 1730000, 6880000
ACTOR_W, ACTOR_H, UC_W, UC_H = 1750000, 800000, 2400000, 620000
BOX_L, BOX_R = X0 + 2450000, X0 + 8650000
BOX_B = Y1 - 400000
PITCH = (BOX_B - Y0 - 380000 - 100000) / 5
ROW = [Y0 + 380000 + PITCH * (index + 0.5) for index in range(5)]
UC1_L, UC2_L = BOX_L + 250000, BOX_R - 250000 - UC_W
UC1_R, UC2_R = UC1_L + UC_W, UC2_L + UC_W
LEFT_R, RIGHT_L = X0 + ACTOR_W, X1 - ACTOR_W
BUS_L, BUS_R = LEFT_R + 380000, UC2_R + 200000
ACTOR_X = X0 + ACTOR_W / 2
STAFF_Y = (ROW[2] + ROW[3]) / 2
node(usecase, MSO_SHAPE.RECTANGLE, BOX_L, Y0, BOX_R - BOX_L, BOX_B - Y0, [], 'F7F7F7', '000000')
label(usecase, BOX_L, Y0 + 60000, BOX_R - BOX_L, 260000, 'Сургуулийн ухаалаг туслах', size=13, bold=True)
# associations: one vertical line per actor side, horizontal stubs to each use case
line(usecase, LEFT_R, ROW[2], BUS_L, ROW[2])
line(usecase, BUS_L, ROW[0], BUS_L, ROW[4])
for y in ROW:
    line(usecase, BUS_L, y, UC1_L, y)
line(usecase, UC2_R, ROW[1], RIGHT_L, ROW[1])
line(usecase, UC2_R, ROW[4], RIGHT_L, ROW[4])
line(usecase, BUS_R, STAFF_Y, RIGHT_L, STAFF_Y)
line(usecase, BUS_R, ROW[2], BUS_R, ROW[3])
line(usecase, UC2_R, ROW[2], BUS_R, ROW[2])
line(usecase, UC2_R, ROW[3], BUS_R, ROW[3])
# generalisation: both visitor groups are a «Зочин» (hollow triangle at the general actor)
line(usecase, ACTOR_X, ROW[0] + ACTOR_H / 2, ACTOR_X, ROW[2] - ACTOR_H / 2 - 150000)
line(usecase, ACTOR_X, ROW[4] - ACTOR_H / 2, ACTOR_X, ROW[2] + ACTOR_H / 2 + 150000)
node(usecase, MSO_SHAPE.FLOWCHART_MERGE, ACTOR_X - 90000, ROW[2] - ACTOR_H / 2 - 150000, 180000, 150000, [], 'FFFFFF', '000000')
node(usecase, MSO_SHAPE.ISOSCELES_TRIANGLE, ACTOR_X - 90000, ROW[2] + ACTOR_H / 2, 180000, 150000, [], 'FFFFFF', '000000')
# «include» / «extend»
line(usecase, UC1_R, ROW[1], UC2_L, ROW[1], dashed=True, arrow=True)
line(usecase, UC1_R, ROW[4], UC2_L, ROW[4], dashed=True, arrow=True)
UC1_X = UC1_L + UC_W / 2
line(usecase, UC1_X, ROW[3] - UC_H / 2, UC1_X, ROW[2] + UC_H / 2, dashed=True, arrow=True)
GAP = UC2_L - UC1_R
label(usecase, UC1_R + (GAP - 760000) / 2, ROW[1] - 280000, 760000, 200000, '«include»', size=10)
label(usecase, UC1_R + (GAP - 760000) / 2, ROW[4] - 280000, 760000, 200000, '«include»', size=10)
label(usecase, UC1_X + 60000, (ROW[2] + ROW[3]) / 2 - 100000, 760000, 200000, '«extend»', size=10, align=PP_ALIGN.LEFT)
for index, text, fill, border in (
        (0, 'Бичгээр асуух', BLUE, BLUE_D), (1, 'Дуугаар асуух', BLUE, BLUE_D),
        (2, 'Эх сурвалж, огноотой хариулт авах', BLUE, BLUE_D),
        (3, 'Хэнд, хаана хандахыг мэдэх', VIOLET, VIOLET_D), (4, 'Хариултыг дуугаар сонсох', BLUE, BLUE_D)):
    node(usecase, MSO_SHAPE.OVAL, UC1_L, ROW[index] - UC_H / 2, UC_W, UC_H, [(text, 12, False)], fill, border)
for index, text, fill, border in (
        (1, 'Яриаг текст болгох', ORANGE_L, ORANGE_D), (2, 'Сургуулийн хүснэгт оруулах', GREEN, GREEN_D),
        (3, 'Мэдээллийг шалгаж шинэчлэх', GREEN, GREEN_D), (4, 'Текстийг дуу болгох', ORANGE_L, ORANGE_D)):
    node(usecase, MSO_SHAPE.OVAL, UC2_L, ROW[index] - UC_H / 2, UC_W, UC_H, [(text, 12, False)], fill, border)
ACTOR = ('«actor»', 9, False)
for y, lines, fill, border, left in (
        (ROW[0], [ACTOR, ('Өдөр тутмын зочин', 12, False), ('оюутан, эцэг эх, ажил горилогч', 9, False)], TEAL, TEAL_D, X0),
        (ROW[2], [ACTOR, ('Зочин', 12, False)], TEAL, TEAL_D, X0),
        (ROW[4], [ACTOR, ('Нээлттэй өдөрлөгийн зочин', 12, False), ('элсэгч, эцэг эх', 9, False)], TEAL, TEAL_D, X0),
        (ROW[1], [ACTOR, ('Яриа таних үйлчилгээ', 12, False), ('Gemini 3.5 Transcribe', 9, False)], ORANGE, ORANGE_D, RIGHT_L),
        (STAFF_Y, [ACTOR, ('Сургуулийн ажилтан', 12, False)], GREEN_S, GREEN_D, RIGHT_L),
        (ROW[4], [ACTOR, ('Дуу үүсгэх үйлчилгээ', 12, False), ('Edge TTS', 9, False)], ORANGE, ORANGE_D, RIGHT_L)):
    node(usecase, MSO_SHAPE.RECTANGLE, left, y - ACTOR_H / 2, ACTOR_W, ACTOR_H, lines, fill, border)
legend(usecase, X0, Y1 - 260000, [
    ([TEAL], TEAL_D, 'зочин', 520000), ([BLUE], BLUE_D, 'зочны үйлдэл', 1050000),
    ([VIOLET], VIOLET_D, 'хэнд, хаана хандахыг мэдэх', 2050000),
    ([ORANGE, ORANGE_L], ORANGE_D, 'гадны үйлчилгээ, үйлдэл', 1850000),
    ([GREEN_S, GREEN], GREEN_D, 'ажилтан, мэдээлэл шинэчлэх', 2150000)])

# 5. system structure: the same picture in the new colours
structure = slide_with('СИСТЕМИЙН БҮТЭЦ')
old = next(shape for shape in structure.shapes if shape.shape_type == 6 and shape.name == 'Group 15')
left, top, width, height = old.left, old.top, old.width, old.height
remove(old)
picture = structure.shapes.add_picture(STRUCTURE_PNG, left, top)
scale = min(width / picture.width, height / picture.height)
picture.width, picture.height = int(picture.width * scale), int(picture.height * scale)
picture.left, picture.top = left + (width - picture.width) // 2, top + (height - picture.height) // 2

# 6. knowledge tree: 11 domains as in the thesis, coloured by where the information came from
tree = slide_with('МЭДЛЭГИЙН МОД')
keep = {'Group 2', 'Group 4', 'AutoShape 7', 'TextBox 8'}     # logo, title, title underline, page number
for shape in list(tree.shapes):
    if shape.name not in keep:
        remove(shape)
BOX_W, BOX_H, STEP = 3120877, 473783, 677656
LEFT_X, RIGHT_X, MID_Y = 659629, 8303167, 3983545
CENTRE_L, CENTRE_W, CENTRE_H = 4645518, 2792627, 824179
BUS_A, BUS_B = 4185251, 7898418
left_names = ['Сургуулийн тухай', 'Элсэлт', 'Сургалт, тэнхимүүд', 'Оюутны амьдрал', 'Карьер, хамтын ажиллагаа', 'Мэдээ']
right_names = [('Арга хэмжээ', False), ('Холбоо барих', False), ('Байршил, өрөө', True), ('Багш, ажилтан', True),
               ('Анги, хичээлийн хуваарь', True)]
left_y = [MID_Y + (index - 2.5) * STEP for index in range(6)]
right_y = [MID_Y + (index - 2) * STEP for index in range(5)]
line(tree, BUS_A, left_y[0], BUS_A, left_y[-1], colour=BLUE_D)
line(tree, BUS_A, MID_Y, CENTRE_L, MID_Y, colour=BLUE_D)
for y in left_y:
    line(tree, LEFT_X + BOX_W, y, BUS_A, y, colour=BLUE_D)
line(tree, CENTRE_L + CENTRE_W, MID_Y, BUS_B, MID_Y, colour=BLUE_D)
line(tree, BUS_B, right_y[0], BUS_B, right_y[-1], colour=BLUE_D)
for y in right_y:
    line(tree, BUS_B, y, RIGHT_X, y, colour=BLUE_D)
node(tree, MSO_SHAPE.ROUNDED_RECTANGLE, CENTRE_L, MID_Y - CENTRE_H / 2, CENTRE_W, CENTRE_H,
     [('Шинэ Монгол', 16, True), ('Технологийн Коллеж', 16, True)], BLUE_D, BLUE_D, colour='FFFFFF')
for name, y in zip(left_names, left_y):
    node(tree, MSO_SHAPE.ROUNDED_RECTANGLE, LEFT_X, y - BOX_H / 2, BOX_W, BOX_H, [(name, 14, True)], BLUE, BLUE_D, colour=BLUE_D)
for (name, school), y in zip(right_names, right_y):
    fill, border = (GREEN, GREEN_D) if school else (BLUE, BLUE_D)
    node(tree, MSO_SHAPE.ROUNDED_RECTANGLE, RIGHT_X, y - BOX_H / 2, BOX_W, BOX_H, [(name, 14, True)], fill, border, colour=border)
legend(tree, LEFT_X, 6330000, [([BLUE], BLUE_D, 'вэб сайтаас авсан мэдээлэл (8 хүрээ)', 3300000),
                               ([GREEN], GREEN_D, 'сургуулийн зүгээс өгсөн мэдээлэл (3 хүрээ)', 3900000)])

# 7. the problem being solved this week: system evaluation (replaces the speech-recognition choice of W03)
problem = slide_with('ШИЙДЭХ АСУУДАЛ')
heading = title_box(problem)
old_title = heading.text_frame.text.strip()
set_paragraph(heading.text_frame.paragraphs[0], 'ШИЙДЭХ АСУУДАЛ: СИСТЕМИЙН ҮНЭЛГЭЭ')
underline = next(shape for shape in problem.shapes if shape.name == 'AutoShape 13')
underline.width = int(underline.width * len('ШИЙДЭХ АСУУДАЛ: СИСТЕМИЙН ҮНЭЛГЭЭ') / len(old_title))
frame = table_of(problem)
frame.top = Emu(2150000)
for row, texts in zip(frame.table.rows, EVALUATION):
    header = row.cells[1].text_frame.paragraphs[0].runs[0]       # the old table's first header cell was empty
    for cell, text in zip(row.cells, texts):
        set_paragraph(cell.text_frame.paragraphs[0], text, like=header)
for column, width in zip(frame.table.columns, (3300000, 3300000, 3864800)):
    column.width = Emu(width)
notes = problem.shapes.add_textbox(frame.left, Emu(4350000), frame.width, Emu(1500000))
notes.text_frame.word_wrap = True
for index, text in enumerate(EVALUATION_NOTES):
    paragraph = notes.text_frame.paragraphs[0] if index == 0 else notes.text_frame.add_paragraph()
    paragraph.space_after = Pt(10)
    head, _, rest = text.partition(':')
    first, second = paragraph.add_run(), paragraph.add_run()
    first.text, second.text = head + ':', rest
    for run, bold in ((first, True), (second, False)):
        run.font.name, run.font.size, run.font.bold = FONT, Pt(18), bold
        run.font.color.rgb = rgb('000000')

# 8. plan: W04 in the teachers' words; the highlighted row is the seminar's week (11/24 is in W05)
plan = table_of(slide_with('ТӨЛӨВЛӨГӨӨ 1/2')).table
by_week = {row.cells[0].text_frame.text.strip(): row for row in plan.rows}
set_paragraph(by_week['W04'].cells[2].text_frame.paragraphs[0], 'Системийн үнэлгээний асуудал (шалгах асуултын багц)')
for old_cell, new_cell in zip(by_week['W04'].cells, by_week['W05'].cells):
    old_pr, new_pr = old_cell._tc.get_or_add_tcPr(), new_cell._tc.get_or_add_tcPr()
    fill = old_pr.find(qn('a:solidFill'))
    assert fill is not None and new_pr.find(qn('a:solidFill')) is None, 'W04 is expected to be the highlighted row'
    old_pr.remove(fill)
    borders = [child for child in new_pr if child.tag in {qn('a:lnL'), qn('a:lnR'), qn('a:lnT'), qn('a:lnB'),
                                                        qn('a:lnTlToBr'), qn('a:lnBlToTr')}]
    if borders:                      # CT_TableCellProperties: the fill comes after the border lines
        borders[-1].addnext(fill)
    else:
        new_pr.insert(0, fill)

# 9. next week
upcoming = next(shape for shape in slide_with('ДАРААГИЙН 7 ХОНОГ').shapes
                if shape.has_text_frame and shape.name == 'TextBox 14')
paragraphs = upcoming.text_frame.paragraphs
assert len(paragraphs) == len(NEXT_WEEK), 'next-week list is expected to have five lines'
for paragraph, text in zip(paragraphs, NEXT_WEEK):
    set_paragraph(paragraph, text)

deck.save(OUT)
sys.stdout.reconfigure(encoding='utf-8')
print(OUT)
