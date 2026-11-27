"""Examination No.1 deck v110 (2026-11-27), built on the user's last saved deck v109.

The department's guide for Үзлэг №1 (МИНИЙ-ДИПЛОМ/02_Семинар/ТСА үзлэгийн слайд бэлдэх заавар) asks for: cover,
rationale and goal, state of research / theory, methodology (may be split 3a, 3b), expected results in numbers,
work plan with a separate Word-report row. The user's approved «ЗОРИЛГО» and «ЗОРИЛТ» slides of v109 are kept
unchanged (CLAUDE.md 11/15 (5)); the system-structure and knowledge-tree slides of v109 are kept as methodology
slides. New slides are drawn as editable PowerPoint shapes (user 11/20: «диаграммыг би өөрөө засдаг болмоор»), with
only horizontal and vertical lines (Canva draws rotated lines differently), and no numbers inside the diagrams
(teacher 11/23).

    python tools/nmct_slides/build_exam1_v110.py <pylibs> <base v109.pptx> <out.pptx> [system_structure.png]

The optional PNG (tools/export_thesis_figure.py system_structure ...) replaces the v109 system-structure picture, so the
slide shows the same figure as the thesis (11/27: stored answers added to Figure 3.3).
"""
import copy
import sys

sys.path.insert(0, sys.argv[1])
from lxml import etree                                           # noqa: E402
from pptx import Presentation                                    # noqa: E402
from pptx.dml.color import RGBColor                              # noqa: E402
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE            # noqa: E402
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN                  # noqa: E402
from pptx.oxml.ns import qn                                      # noqa: E402
from pptx.util import Emu, Pt                                    # noqa: E402

BASE, OUT = sys.argv[2:4]
SYSTEM_PNG = sys.argv[4] if len(sys.argv) > 4 else None
FONT = 'Times New Roman'
BLACK = RGBColor(0, 0, 0)
NAVY = RGBColor(0x1F, 0x3A, 0x93)
GREY = RGBColor(0x55, 0x55, 0x55)
# thesis/Figures/palette.tex: blue = system step, green = information, orange = external service, pink = referral
BLUE_F, BLUE_D = RGBColor(0xBF, 0xDB, 0xF7), RGBColor(0x1F, 0x5F, 0xA8)
GREEN_F, GREEN_D = RGBColor(0xC8, 0xE6, 0xC9), RGBColor(0x2E, 0x7D, 0x32)
ORANGE_F, ORANGE_D = RGBColor(0xFF, 0xCC, 0x80), RGBColor(0xC6, 0x6A, 0x00)
PINK_F, PINK_D = RGBColor(0xE1, 0xBE, 0xE7), RGBColor(0x7B, 0x1F, 0xA2)
NAVY_F = RGBColor(0x1F, 0x3A, 0x93)

prs = Presentation(BASE)
slides = list(prs.slides)
TEMPLATE = slides[13]                       # v109 «ДАРААГИЙН 7 ХОНОГ»: logo + title + one text box


def duplicate(source):
    new = prs.slides.add_slide(source.slide_layout)
    for shape in list(new.shapes):
        shape._element.getparent().remove(shape._element)
    mapping = {}
    for rel in source.part.rels.values():
        if 'image' in rel.reltype:
            mapping[rel.rId] = new.part.relate_to(rel._target, rel.reltype)
    tree = new.shapes._spTree
    for element in source.shapes._spTree.iterchildren():
        if element.tag.endswith('}nvGrpSpPr') or element.tag.endswith('}grpSpPr'):
            continue
        clone = copy.deepcopy(element)
        for node in clone.iter():
            for attr in (qn('r:embed'), qn('r:link')):
                if node.get(attr) in mapping:
                    node.set(attr, mapping[node.get(attr)])
        tree.append(clone)
    return new


def walk(shapes):
    for shape in shapes:
        yield shape
        if shape.shape_type == 6:
            yield from walk(shape.shapes)


TITLES = ('ДАРААГИЙН 7 ХОНОГ', 'СИСТЕМИЙН БҮТЭЦ', 'МЭДЛЭГИЙН МОД')


def set_title(slide, text):
    box = next(s for s in walk(slide.shapes) if s.has_text_frame and s.text_frame.text.strip() in TITLES)
    box.text_frame.paragraphs[0].runs[0].text = text
    for extra in box.text_frame.paragraphs[0].runs[1:]:
        extra._r.getparent().remove(extra._r)
    line = next(s for s in slide.shapes if s.name == 'AutoShape 15')
    line.width = Emu(min(13_000_000, 285_000 * len(text)))


def set_number(slide, number):
    for shape in slide.shapes:
        if shape.has_text_frame and shape.left > 16_000_000 and shape.top > 9_000_000:
            shape.text_frame.paragraphs[0].runs[0].text = str(number)


def remove(slide, name):
    for shape in list(slide.shapes):
        if shape.name == name:
            shape._element.getparent().remove(shape._element)


def text(slide, x, y, w, h, lines, size=20, color=BLACK, bold=False, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, name=None):
    box = slide.shapes.add_textbox(Emu(x), Emu(y), Emu(w), Emu(h))
    frame = box.text_frame
    frame.word_wrap = True
    frame.vertical_anchor = anchor
    frame.margin_left = frame.margin_right = Emu(0)
    if isinstance(lines, str):
        lines = [lines]
    for k, line in enumerate(lines):
        paragraph = frame.paragraphs[0] if k == 0 else frame.add_paragraph()
        paragraph.alignment = align
        parts = line if isinstance(line, list) else [(line, {})]
        for part, opts in parts:
            run = paragraph.add_run()
            run.text = part
            run.font.name = FONT
            run.font.size = Pt(opts.get('size', size))
            run.font.bold = opts.get('bold', bold)
            run.font.italic = opts.get('italic', False)
            run.font.color.rgb = opts.get('color', color)
        paragraph.space_after = Pt(4)
    if name:
        box.name = name
    return box


def node(slide, x, y, w, h, lines, fill, line, size=18, bold=False, color=BLACK, name=None, shape=MSO_SHAPE.ROUNDED_RECTANGLE):
    box = slide.shapes.add_shape(shape, Emu(x), Emu(y), Emu(w), Emu(h))
    box.fill.solid()
    box.fill.fore_color.rgb = fill
    box.line.color.rgb = line
    box.line.width = Pt(1.5)
    if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        box.adjustments[0] = 0.12
    box.shadow.inherit = False
    frame = box.text_frame
    frame.word_wrap = True
    frame.vertical_anchor = MSO_ANCHOR.MIDDLE
    frame.margin_left = frame.margin_right = Emu(90_000)
    if isinstance(lines, str):
        lines = [lines]
    for k, line_text in enumerate(lines):
        paragraph = frame.paragraphs[0] if k == 0 else frame.add_paragraph()
        paragraph.alignment = PP_ALIGN.CENTER
        run = paragraph.add_run()
        run.text = line_text
        run.font.name = FONT
        run.font.size = Pt(size if k == 0 else size - 3)
        run.font.bold = bold if k == 0 else False
        run.font.color.rgb = color
    if name:
        box.name = name
    return box


def arrow(slide, x1, y1, x2, y2, color=GREY, width=2.0, head=True):
    connector = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Emu(x1), Emu(y1), Emu(x2), Emu(y2))
    connector.line.color.rgb = color
    connector.line.width = Pt(width)
    if head:
        ln = connector.line._get_or_add_ln()
        tail = etree.SubElement(ln, qn('a:tailEnd'))
        tail.set('type', 'triangle')
        tail.set('w', 'med')
        tail.set('len', 'med')
    return connector


def table(slide, x, y, w, rows, widths, size=16, header_fill=RGBColor(0xE8, 0xEE, 0xF7), row_h=420_000, bold_last=False):
    shape = slide.shapes.add_table(len(rows), len(rows[0]), Emu(x), Emu(y), Emu(w), Emu(row_h * len(rows)))
    tbl = shape.table
    tbl.first_row = True
    for c, width in enumerate(widths):
        tbl.columns[c].width = Emu(width)
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            cell = tbl.cell(r, c)
            cell.fill.solid()
            cell.fill.fore_color.rgb = header_fill if r == 0 else RGBColor(0xFF, 0xFF, 0xFF)
            cell.margin_left = cell.margin_right = Emu(70_000)
            cell.margin_top = cell.margin_bottom = Emu(30_000)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            frame = cell.text_frame
            frame.word_wrap = True
            paragraph = frame.paragraphs[0]
            run = paragraph.add_run()
            run.text = value
            run.font.name = FONT
            run.font.size = Pt(size)
            run.font.bold = r == 0 or (bold_last and r == len(rows) - 1)
            run.font.color.rgb = BLACK
    # thin black borders on every cell (the theme's default table style is a coloured band)
    style = shape._element.graphic.graphicData.tbl.tblPr
    style.set('bandRow', '0')
    for tc in shape._element.iter(qn('a:tc')):
        tcPr = tc.get_or_add_tcPr()
        for side in ('a:lnL', 'a:lnR', 'a:lnT', 'a:lnB'):
            ln = etree.SubElement(tcPr, qn(side), w='9525')
            fill = etree.SubElement(ln, qn('a:solidFill'))
            etree.SubElement(fill, qn('a:srgbClr'), val='000000')
        # schema order: borders must come before the fill
        fills = [child for child in tcPr if child.tag == qn('a:solidFill')]
        for child in fills:
            tcPr.remove(child)
            tcPr.append(child)
    return shape


def notes(slide, words):
    slide.notes_slide.notes_text_frame.text = words


L, R = 1_911_057, 16_300_000          # content left / right edge (v109 content slides)
TOP = 2_550_000

# ---------------------------------------------------------------- 1. cover (template lines, date, supervisor degree)
cover = slides[0]
for shape in walk(cover.shapes):
    if shape.has_text_frame and shape.text_frame.text == '2026.11.24':
        shape.text_frame.paragraphs[0].runs[0].text = '2026.12.01'
    if shape.has_text_frame and shape.text_frame.text.startswith('Оюутан:'):
        paragraph = shape.text_frame.paragraphs[1]
        paragraph.runs[0].text = 'Удирдагч багш: Бакалавр Т.Хандсүрэн'
        for extra in paragraph.runs[1:]:
            extra._r.getparent().remove(extra._r)
title_box = next(s for s in cover.shapes if s.name == 'TextBox 8')
title_box.top = Emu(6_650_000)
text(cover, 909_205, 5_300_000, 16_469_591, 420_000, 'КОМПЬЮТЕРЫН УХААНЫ ТЭНХИМ   /2026–2027 оны хичээлийн жил/',
     size=18, color=BLACK, bold=True, align=PP_ALIGN.CENTER, name='Department line')
text(cover, 909_205, 5_900_000, 16_469_591, 520_000, 'ТӨГСӨЛТИЙН АЖЛЫН ҮЗЛЭГ №1', size=24, color=RGBColor(0x00, 0x9F, 0xE3),
     bold=True, align=PP_ALIGN.CENTER, name='Examination line')

# ---------------------------------------------------------------- new slides
s_reason = duplicate(TEMPLATE)
s_research = duplicate(TEMPLATE)
s_method = duplicate(TEMPLATE)
s_results = duplicate(TEMPLATE)
s_plan = duplicate(TEMPLATE)
for s in (s_reason, s_research, s_method, s_results, s_plan):
    remove(s, 'TextBox 16')

# 2. rationale and problem
set_title(s_reason, 'СУДАЛГААНЫ ҮНДЭСЛЭЛ БА АСУУДАЛ')
box_w, gap, box_y, box_h = 4_300_000, 600_000, TOP + 300_000, 4_000_000
xs = [L, L + box_w + gap, L + 2 * (box_w + gap)]
for x, head, fill, line, color in ((xs[0], 'ҮНДЭСЛЭЛ', BLUE_F, BLUE_D, BLACK), (xs[1], 'АСУУДАЛ', BLUE_F, BLUE_D, BLACK),
                                   (xs[2], 'ШИЙДЭЛ', NAVY_F, NAVY_F, RGBColor(0xFF, 0xFF, 0xFF))):
    card = node(s_reason, x, box_y, box_w, box_h, [''], fill, line, name='Card ' + head)
    text(s_reason, x + 250_000, box_y + 200_000, box_w - 500_000, 450_000, head, size=20, bold=True,
         color=(RGBColor(0xFF, 0xFF, 0xFF) if fill == NAVY_F else NAVY))
text(s_reason, xs[0] + 250_000, box_y + 750_000, box_w - 500_000, 1_000_000, '5-аас 3', size=54, bold=True, color=NAVY)
text(s_reason, xs[0] + 250_000, box_y + 1_850_000, box_w - 500_000, 2_000_000,
     'Ресепшнд өдөр тутам асуудаг таван сэдвийн гурав нь «хэнтэй холбогдох, хаана очих» асуулт*', size=18)
text(s_reason, xs[1] + 250_000, box_y + 750_000, box_w - 500_000, 3_100_000,
     ['Ажилтнууд ижил мэдээллийг давтан тайлбарладаг, 1-р давхрын цаасан мэдээлэл хангалтгүй**.',
      'Өрөөний дугаар, багшийн өрөө, хичээлийн хуваарийг сургуулийн сайт, Facebook чатбот хэлдэггүй***.'], size=18)
text(s_reason, xs[2] + 250_000, box_y + 750_000, box_w - 500_000, 3_100_000,
     ['Монгол хэлээр бичгээр, дуугаар асуухад сургуулийн албан мэдээллээс эх сурвалжтай хариулж,',
      'хариулт олдоогүй бол хандах алба, өрөөг заадаг ухаалаг туслах.'], size=18, color=RGBColor(0xFF, 0xFF, 0xFF))
for k in range(2):
    arrow(s_reason, xs[k] + box_w + 60_000, box_y + box_h // 2, xs[k + 1] - 60_000, box_y + box_h // 2, color=BLUE_D, width=3)
text(s_reason, L, box_y + box_h + 350_000, 14_000_000, 900_000,
     ['* Ресепшний ажилтны мэдээлснээр (2026.11.12); давтамжийг тоолоогүй.   ** Сургалтын албатай уулзалт (2026.11.09).',
      '*** 2026.11.26-нд сургуулийн Facebook чатботод ижил асуулт тавьсан нэг удаагийн ажиглалт.'], size=13, color=GREY)
notes(s_reason, 'Ресепшний ажилтны хэлснээр өдөр тутам асуудаг таван сэдвийн гурав нь хэнтэй холбогдох, хаана очих асуулт. '
      'Сургалтын албаныхан ижил мэдээллийг давтан тайлбарладаг гэсэн. Өрөөний дугаар, багшийн өрөө, хуваарийг сайт, чатбот хэлдэггүй. '
      'Тиймээс Монголоор асуухад албан мэдээллээс эх сурвалжтай хариулдаг, олдоогүй бол алба, өрөөг заадаг туслах хийж байна. (40 сек)')

# 3. state of research / theory
set_title(s_research, 'СУДЛАГДСАН БАЙДАЛ, ОНОЛЫН ҮНДЭС')
lw = 5_300_000
node(s_research, L, TOP, lw, 4_250_000, [''], RGBColor(0xF3, 0xF6, 0xFB), RGBColor(0xC9, 0xD3, 0xE6), name='Theory card')
text(s_research, L + 200_000, TOP + 120_000, lw - 400_000, 400_000, 'ОНОЛЫН ҮНДЭС', size=18, bold=True, color=NAVY)
text(s_research, L + 200_000, TOP + 560_000, lw - 400_000, 1_500_000,
     ['Хайлтаар баяжуулсан хариулт (RAG) [5]: хайгч баримтаас хайж, үүсгэгч хариулт бичнэ.',
      'Энэ ажилд үүсгэгчийн оронд эх сурвалжийн өгүүлбэрийг үгчлэн сонгоно.'], size=15)
text(s_research, L + 200_000, TOP + 2_050_000, lw - 400_000, 500_000,
     [[('RRF(d) = Σ', {'size': 20, 'italic': True}), ('r', {'size': 13, 'italic': True}),
       ('  1 / (k + rank', {'size': 20, 'italic': True}), ('r', {'size': 13, 'italic': True}), ('(d))', {'size': 20, 'italic': True})]],
     size=20, align=PP_ALIGN.CENTER)
text(s_research, L + 200_000, TOP + 2_650_000, lw - 400_000, 1_500_000,
     ['BM25 [6] үгээр, E5 [7] утгаар хайсан хоёр жагсаалтыг баримт бүрийн байрын урвуу утгаар нэгтгэнэ [8]; энэ ажилд k = 30.'], size=15)
rx = L + lw + 400_000
rows = [['Систем', 'Хэл, хэлбэр', 'Хариулт гаргах арга', 'Өрөө, хуваарь'],
        ['Unimib Assistant, Итали [1]', 'Англи, бичгээр', 'Хэлний загвар бичнэ', 'Дурдаагүй'],
        ['Бурч их сургууль [2]', 'Англи, бичгээр', 'Хэлний загвар бичнэ', 'Дурдаагүй'],
        ['ШМТК-ийн Facebook чатбот', 'Монгол, бичгээр', '«Generated by AI», эх сурвалжгүй', 'Давхар хэлдэг, өрөө хэлдэггүй'],
        ['ШУТИС-ийн оюутны робот (2IP-2026)', 'Монгол, дэлгэцтэй', 'Нийтэд тайлбаргүй', 'Анги, лаборатори руу чиглүүлдэг'],
        ['Энэ ажил', 'Монгол, бичгээр ба дуугаар', 'Эх сурвалжийн үгээр, огноотой', 'Сургуулийн хүснэгтээс; олдоогүй бол алба, өрөө']]
table(s_research, rx, TOP, R - rx, rows, [2_450_000, 1_850_000, 2_300_000, R - rx - 6_600_000], size=13, row_h=600_000, bold_last=True)
node(s_research, L, TOP + 4_500_000, R - L, 900_000, [''], RGBColor(0xFF, 0xF3, 0xE0), RGBColor(0xE8, 0xB8, 0x6A), name='Gap card')
text(s_research, L + 250_000, TOP + 4_580_000, R - L - 500_000, 760_000,
     [[('Судалгааны цоорхой: ', {'bold': True, 'color': RGBColor(0x9A, 0x5B, 0x00)}),
       ('уншсан бүтээлүүдэд Монгол хэлээр, сургуулийн барилга доторх мэдээллээр (өрөө, багш, хуваарь) эх сурвалжтай хариулж, '
        'олдоогүй үед алба, өрөөг заадаг систем олдсонгүй (системтэй тойм биш).', {})]], size=16, anchor=MSO_ANCHOR.MIDDLE)
text(s_research, L, TOP + 5_520_000, R - L, 700_000,
     '[1] Antico нар, 2024 · [2] Matic, Zajmovic, 2026 · [5] Lewis нар, 2020 · [6] Robertson, Zaragoza, 2009 · '
     '[7] Wang нар, 2024 · [8] Cormack нар, 2009 · ШУТИС: үзэсгэлэнгийн бичлэг (2026.11), Facebook: 2026.11.26-ны ажиглалт',
     size=11, color=GREY)
notes(s_research, 'Онолын хувьд RAG аргын хайгч хэсгийг ашигладаг, харин хариултыг хэлний загвараар бичүүлэхгүй, эх сурвалжийн өгүүлбэрийг сонгоно. '
      'Үгээр хайдаг BM25, утгаар хайдаг E5 хоёрын жагсаалтыг RRF томьёогоор нэгтгэнэ. Төстэй систем олон бий: Итали, Боснийн их сургуулийн чатбот, '
      'манай сургуулийн Facebook чатбот, ШУТИС-ийн оюутны робот. Тэдгээр нь хариултаа хэлний загвараар бичдэг эсвэл тайлбар нь нийтэд алга. '
      'Монголоор, барилга доторх мэдээллээр эх сурвалжтай хариулж, алба, өрөө заадаг систем олдсонгүй. (60 сек)')

# 4. methodology (3a): work steps, tools, evaluation
set_title(s_method, 'СУДАЛГААНЫ АРГА ЗҮЙ')
steps = [('Шаардлага тодорхойлох', 'сургалтын алба, ресепшний ажилтан', BLUE_F, BLUE_D),
         ('Мэдээлэл цуглуулах', 'вэб сайт, сургуулийн хүснэгт', GREEN_F, GREEN_D),
         ('Мэдлэгийн мод байгуулах', 'хүрээ, дэд сэдвээр ангилах', GREEN_F, GREEN_D),
         ('Систем хэрэгжүүлэх', 'хайлт, хүснэгтийн хариулт, дуу', BLUE_F, BLUE_D),
         ('Үнэлэх', 'ресепшний бодит асуултаар', PINK_F, PINK_D)]
sw, sh, sgap = 5_600_000, 900_000, 230_000
sy = TOP - 50_000
for k, (head, sub, fill, line) in enumerate(steps):
    y = sy + k * (sh + sgap)
    node(s_method, L, y, sw, sh, [head, sub], fill, line, size=18, bold=True, name='Step ' + head)
    if k:
        arrow(s_method, L + sw // 2, y - sgap + 20_000, L + sw // 2, y - 20_000, color=GREY, width=2)
loop_x = L + sw + 350_000
y4 = sy + 3 * (sh + sgap) + sh // 2
y5 = sy + 4 * (sh + sgap) + sh // 2
arrow(s_method, L + sw, y5, loop_x, y5, color=PINK_D, width=2, head=False)
arrow(s_method, loop_x, y5, loop_x, y4, color=PINK_D, width=2, head=False)
arrow(s_method, loop_x, y4, L + sw + 30_000, y4, color=PINK_D, width=2)
text(s_method, loop_x + 100_000, (y4 + y5) // 2 - 250_000, 1_700_000, 500_000, 'хангалтгүй бол засна', size=13, color=PINK_D)
cx = L + sw + 2_300_000
cw = R - cx
blocks = [('ХАНДЛАГА', ['Систем хөгжүүлэлт ба бодит асуултаар туршилт']),
          ('ХЭРЭГСЭЛ', ['Python, SQLite (огноотой мэдээллийн хувилбар)', 'BM25 ба multilingual-e5-small (хайлт)',
                        'Gemini 3.5 Transcribe (яриа таних), edge-tts (дуу)', 'Вэб: HTML, JavaScript; ресепшний дэлгэц, гар утас']),
          ('ҮНЭЛГЭЭ', ['Зөв хариулсан хувь', 'Хариулт олдоогүй үед алба, өрөө заасан хувь', 'Зөв эх сурвалж эхний 3 үр дүнд орсон хувь',
                       'Хариу гарах хугацаа; дуугаар асуусан асуултын зөв хувь'])]
by = sy
for head, items in blocks:
    text(s_method, cx, by, cw, 420_000, head, size=18, bold=True, color=NAVY)
    lines = ['• ' + item for item in items]
    text(s_method, cx, by + 430_000, cw, 380_000 * len(lines), lines, size=16)
    by += 430_000 + 380_000 * len(lines) + 250_000
notes(s_method, 'Ажлыг таван алхмаар хийж байна. Эхлээд сургалтын алба, ресепшнээс хэрэгцээг тодорхойлсон. Дараа нь вэб сайт болон сургуулиас '
      'өгсөн хүснэгтээс мэдээлэл цуглуулж, мэдлэгийн мод болгон ангилсан. Үүн дээр систем хийсэн: хайлт, хүснэгтээс хариулах, дуу. '
      'Сүүлд ресепшний бодит асуултаар үнэлнэ, хангалтгүй бол засна. Хэрэгсэл, үнэлгээний хэмжүүрийг баруун талд бичсэн. (60 сек)')

# 5. expected results in numbers (each row names its objective)
set_title(s_results, 'ХҮЛЭЭГДЭЖ БУЙ ҮР ДҮН')
rows = [['Зорилт', 'Үзүүлэлт', 'Шалгуур', 'Одоо'],
        ['1', 'Ресепшнд асуудаг сэдвийн мэдээлэл системд орсон', '8 / 8 сэдэв', '4 / 8 (2026.11.15)'],
        ['2', 'Мэдээлэлд байгаа асуултад зөв хариулсан хувь', '≥ 80%', 'Бодит асуултаар хэмжинэ*'],
        ['2', 'Мэдээлэлд ороогүй асуултад алба, өрөө заасан хувь', '≥ 90%', 'Бодит асуултаар хэмжинэ*'],
        ['2', 'Зөв эх сурвалж эхний 3 үр дүнд орсон хувь', '≥ 80%', 'Хэмжинэ'],
        ['3', 'Дуугаар асуусан асуултын зөв хувь (5+ хүн)', '≥ 70%', 'Хэмжинэ'],
        ['3', 'Сонсоод нэр, тоо, оныг зөв ойлгосон хувь', '≥ 90%', 'Хэмжинэ'],
        ['4', 'Бичгээр асуухад хариу гарах хугацаа', '≤ 2 сек', '0.4 сек (медиан, 55 асуулт)']]
table(s_results, L, TOP, 9_700_000, rows, [900_000, 4_700_000, 1_500_000, 2_600_000], size=15, row_h=520_000)
px = L + 9_700_000 + 450_000
pw = R - px
node(s_results, px, TOP, pw, 2_000_000, [''], RGBColor(0xF3, 0xF6, 0xFB), RGBColor(0xC9, 0xD3, 0xE6), name='Product card')
text(s_results, px + 200_000, TOP + 120_000, pw - 400_000, 400_000, 'БҮТЭЭГДЭХҮҮН', size=17, bold=True, color=NAVY)
text(s_results, px + 200_000, TOP + 550_000, pw - 400_000, 1_400_000,
     'Ресепшний дэлгэц ба гар утаснаас нээгддэг, Монголоор бичгээр, дуугаар асуудаг вэб туслах ба диплом', size=15)
node(s_results, px, TOP + 2_250_000, pw, 1_900_000, [''], RGBColor(0xF3, 0xF6, 0xFB), RGBColor(0xC9, 0xD3, 0xE6), name='Value card')
text(s_results, px + 200_000, TOP + 2_370_000, pw - 400_000, 400_000, 'АЧ ХОЛБОГДОЛ', size=17, bold=True, color=NAVY)
text(s_results, px + 200_000, TOP + 2_800_000, pw - 400_000, 1_300_000,
     'Ирсэн хүн өрөө, багш, албыг нэг газраас олж, ажилтан ижил мэдээллийг давтан тайлбарлах нь багасна', size=15)
text(s_results, L, TOP + 4_400_000, R - L, 1_000_000,
     ['* Хөгжүүлэлтийн шалгалтад (агентын бичсэн 40 асуулт) 28/28 зөв, хариугүй 12 асуултын 12-т зохиож хариулаагүй; '
      'эдгээр асуултаар системийг засварласан тул эцсийн дүн биш.',
      'Эцсийн үнэлгээ: ресепшнд 2026.12.02-оос хоёр долоо хоног бүртгэсэн, тааруулахад ашиглаагүй бодит асуулт. Шалгуурыг 2026.11.27-нд тогтоов.'],
     size=12, color=GREY)
notes(s_results, 'Зорилт бүрийг тоогоор хэмжинэ. Мэдээлэлд байгаа асуултын 80-аас доошгүй хувьд зөв хариулах, хариулт байхгүй асуултын 90-ээс доошгүй '
      'хувьд зохиолгүйгээр алба, өрөө заах, дуугаар асуухад 70 хувь гэх мэт. Одоо бодит асуулт хараахан цуглуулаагүй тул эцсийн дүн алга; '
      'хөгжүүлэлтийн шалгалтын тоог зөвхөн хөгжүүлэлтийн дүн гэж хэлнэ. Бичгээр асуухад хариу ихэвчлэн 0.4 секундэд гарч байна. (60 сек)')

# 6. work plan (Gantt drawn with shapes)
set_title(s_plan, 'АЖЛЫН ТӨЛӨВЛӨГӨӨ')
months = ['11-р сар', '12-р сар', '1-р сар', '2-р сар', '3-р сар', '4-р сар', '5-р сар']
label_w = 4_300_000
gx = L + label_w
gw = R - gx
mw = gw // len(months)
hy = TOP - 150_000
for k, month in enumerate(months):
    node(s_plan, gx + k * mw + 15_000, hy, mw - 30_000, 380_000, [month], NAVY_F, NAVY_F, size=14, bold=True,
         color=RGBColor(0xFF, 0xFF, 0xFF), shape=MSO_SHAPE.RECTANGLE, name='Month ' + month)
DONE, PLAN, WORD, MILE = (GREEN_F, GREEN_D), (BLUE_F, BLUE_D), (NAVY_F, NAVY_F), (ORANGE_F, ORANGE_D)
rows = [('Шаардлага, мэдээлэл цуглуулах', [(0.0, 1.0, DONE), (1.0, 2.2, PLAN)]),
        ('Систем хөгжүүлэх', [(0.0, 1.0, DONE), (1.0, 3.5, PLAN)]),
        ('Үзлэг №1', [(1.0, None, MILE)]),
        ('Ресепшний бодит асуулт цуглуулах', [(1.05, 1.7, PLAN)]),
        ('Онол, судалгааны тойм', [(0.0, 1.0, DONE), (1.0, 3.6, PLAN)]),
        ('Дуу: олон хүний бичлэг, сонсголын шалгалт', [(2.0, 3.0, PLAN)]),
        ('Эцсийн үнэлгээ', [(3.5, 4.25, PLAN)]),
        ('Word тайлан бичих', [(0.0, 1.0, DONE), (1.0, 7.0, WORD)]),
        ('Бүтэн ноорог (≤ 40 хуудас)', [(4.5, None, MILE)]),
        ('Урьдчилсан хамгаалалт', [(5.45, None, MILE)]),
        ('Эцсийн хамгаалалт', [(6.85, None, MILE)])]
rh = 470_000
ry = hy + 480_000
for k, (label, bars) in enumerate(rows):
    y = ry + k * rh
    if k % 2 == 0:
        band = s_plan.shapes.add_shape(MSO_SHAPE.RECTANGLE, Emu(L), Emu(y), Emu(R - L), Emu(rh))
        band.fill.solid()
        band.fill.fore_color.rgb = RGBColor(0xF4, 0xF6, 0xF9)
        band.line.fill.background()
        band.name = 'Row band'
    text(s_plan, L + 60_000, y + 60_000, label_w - 100_000, rh - 80_000, label, size=14,
         bold=label.startswith(('Үзлэг', 'Word', 'Эцсийн хамгаалалт')), color=(NAVY if label.startswith('Word') else BLACK))
    for start, end, (fill, line) in bars:
        if end is None:
            size = 300_000
            node(s_plan, int(gx + start * mw) - size // 2, y + (rh - size) // 2, size, size, [''], fill, line,
                 shape=MSO_SHAPE.DIAMOND, name='Milestone ' + label)
        else:
            node(s_plan, int(gx + start * mw) + 20_000, y + 110_000, int((end - start) * mw) - 40_000, rh - 220_000, [''],
                 fill, line, name='Bar ' + label)
ly = ry + len(rows) * rh + 120_000
lx = gx
for fill, line, label, shape in ((GREEN_F, GREEN_D, 'хийгдсэн', MSO_SHAPE.ROUNDED_RECTANGLE),
                                 (BLUE_F, BLUE_D, 'төлөвлөсөн', MSO_SHAPE.ROUNDED_RECTANGLE),
                                 (NAVY_F, NAVY_F, 'Word тайлан', MSO_SHAPE.ROUNDED_RECTANGLE),
                                 (ORANGE_F, ORANGE_D, 'үзлэг, хамгаалалт (огноог тэнхим тогтооно)', MSO_SHAPE.DIAMOND)):
    node(s_plan, lx, ly + 40_000, 300_000, 220_000, [''], fill, line, shape=shape, name='Legend ' + label)
    text(s_plan, lx + 380_000, ly, 3_600_000, 320_000, label, size=13, color=GREY)
    lx += 380_000 + 120_000 * len(label) // 2 + 700_000
notes(s_plan, 'Төлөвлөгөөг 5-р сар хүртэл сар бүрээр харуулав. Ногоон нь 11-р сард хийсэн ажил. Хамгийн чухал нь ресепшнээс бодит асуултыг '
      '12-р сарын эхнээс цуглуулах, учир нь эцсийн үнэлгээ түүнээс хамаарна. 1-р сард олон хүний дуугаар шалгана, 2–3-р сард эцсийн үнэлгээ, '
      '3-р сард бүтэн ноорог. Word тайланг тусдаа мөрөөр бичиж байгаа, үзлэгийн огноог тэнхим тогтооно. (60 сек)')

# ---------------------------------------------------------------- order: keep cover, goal, objectives, system, tree, thanks
goal, objectives, system_slide, tree_slide, thanks = slides[1], slides[2], slides[7], slides[8], slides[14]
set_title(system_slide, 'АРГА ЗҮЙ: СИСТЕМИЙН БҮТЭЦ')
if SYSTEM_PNG:
    old_figure = next(s for s in system_slide.shapes if s.name == 'Group 17')
    box = (old_figure.left, old_figure.top, old_figure.width, old_figure.height)
    old_figure._element.getparent().remove(old_figure._element)
    from PIL import Image
    pw, ph = Image.open(SYSTEM_PNG).size
    scale = min(box[2] * 1.12 / pw, (R_LIMIT := 9_250_000 - box[1]) / ph)
    w, h = int(pw * scale), int(ph * scale)
    picture = system_slide.shapes.add_picture(SYSTEM_PNG, Emu((18_288_000 - w) // 2), Emu(box[1]), Emu(w), Emu(h))
    picture.name = 'System structure (thesis Figure 3.3)'

set_title(tree_slide, 'АРГА ЗҮЙ: МЭДЛЭГИЙН МОД')
notes(goal, 'Миний ажлын зорилго бол сургуулийн албан мэдээллийг Монгол хэлээр бичиж эсвэл ярьж асуухад сургуулийн баримтаас хариулт өгч, '
      'дуугаар уншдаг систем хөгжүүлэх. Хариулт бүр аль баримтаас авсан нь харагдана. (25 сек)')
notes(objectives, 'Үүний тулд дөрвөн зорилт тавьсан: мэдээлэл цуглуулж сан бүрдүүлэх, эх сурвалжтай хариулт гаргах, яриаг текст болгож хариултыг '
      'дуугаар унших, бүгдийг нэг систем болгох. Зорилт бүр хүлээгдэж буй үр дүнгийн хүснэгтэд нэг мөртэй. (25 сек)')
notes(system_slide, 'Системийн бүтэц: асуулт бичгээр эсвэл дуугаар орж ирнэ. Өрөө, анги, багш, хуваарийн асуултыг сургуулийн хүснэгтээс, '
      'олон асуудаг сэдвийг сайтаас бүрдүүлсэн хадгалсан хариултаас, бусдыг вэб сайтаас үгээр болон утгаар хайж, дүрмээр сонгоод эх сурвалжтай нь харуулна. Олдохгүй бол ягаан хэсэг: хандах алба, өрөөг заана. (50 сек)')
notes(tree_slide, 'Мэдээллийг мэдлэгийн модонд хүрээ, дэд сэдвээр ангилсан. Мод нь дутуу мэдээллийг харуулж, сургуульд хүсэх жагсаалт гаргахад тусалсан, '
      'хариулт бүр аль хүрээнээс гарсныг дэлгэцэнд харуулдаг. Өөрөөр хэлбэл мод системийн хамрах хүрээг тодорхойлдог. Хайлтад нэмэлт оноо өгөх алхмыг '
      'хэмжихэд 76 асуултаас зөв хуудас эхэнд гарсан нь 55-аас 56 болсон, бараг ялгаагүй тул асаагаагүй. (40 сек)')
order = [cover, s_reason, goal, objectives, s_research, s_method, system_slide, tree_slide, s_results, s_plan, thanks]
sld_ids = prs.slides._sldIdLst
by_part = {}
keep = {slide.part for slide in order}
for sld_id in list(sld_ids):
    part = prs.part.related_part(sld_id.rId)
    sld_ids.remove(sld_id)
    if part in keep:
        by_part[part] = sld_id
    else:
        prs.part.drop_rel(sld_id.rId)            # unused v109 slide: not written to the new file
for k, slide in enumerate(order, 1):
    sld_ids.append(by_part[slide.part])
    set_number(slide, k)
prs.save(OUT)
print('saved', OUT, len(order), 'slides')
