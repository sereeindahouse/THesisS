"""Seminar deck v108 (2026-11-24): the title slide after the user's sketch of the standard first page.

The user (11/24) photographed a sketch of the standard first page (`МИНИЙ-ДИПЛОМ/02_Семинар/922162101_…_n.jpg`) and said
the current one cannot be edited: in v107 the emblem, «ШИНЭ МОНГОЛ ТЕХНОЛОГИЙН КОЛЛЕЖ» and the building are one
picture (the template's background image). The new slide 1 is made of separate editable shapes, laid out as sketched:
a frame; at the top left the school emblem and the school's name with a rule under it; the topic in the middle; a
«Дэд сэдэв» line under it (the word written before «( )» on the sketch could not be read, so the line waits for the
user's own words); the date at the bottom centre; the student and the supervisor at the bottom right (the supervisor's
11/16 advice: date in the middle, names on the right). Every other slide is v107 as it was.

    python tools/nmct_slides/update_seminar_v108.py <pylibs> <base v107> <out v108>
"""
import sys

sys.path.insert(0, sys.argv[1])
from pptx import Presentation                                    # noqa: E402
from pptx.dml.color import RGBColor                              # noqa: E402
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE           # noqa: E402
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN                  # noqa: E402
from pptx.util import Cm, Pt                                     # noqa: E402

BASE, OUT = sys.argv[2:4]
EMBLEM = 'tools/nmct_slides/assets/seal.png'
NAVY, RULE, GREY = RGBColor(0x0E, 0x31, 0x99), RGBColor(0x05, 0xA0, 0xEA), RGBColor(0x80, 0x80, 0x80)
FONT = 'Times New Roman'
SCHOOL = 'ШИНЭ МОНГОЛ ТЕХНОЛОГИЙН КОЛЛЕЖ'
TOPIC, SUBTOPIC, DATE = 'ШМТК-ийн ухаалаг туслах', 'Дэд сэдэв', '2026.11.24'
PEOPLE = ('Оюутан: Б.Сэргэлэн', 'Удирдагч багш: Т.Хандсүрэн')


def write(box, lines, *, size, align, bold=False, italic=False, color=RGBColor(0, 0, 0), anchor=MSO_ANCHOR.MIDDLE):
    """Replace the box's text by ``lines``, one paragraph each, in the deck's font."""
    frame = box.text_frame
    frame.clear()
    frame.word_wrap = True
    frame.vertical_anchor = anchor
    for margin in ('margin_left', 'margin_right', 'margin_top', 'margin_bottom'):
        setattr(frame, margin, 0)
    for i, line in enumerate(lines):
        paragraph = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
        paragraph.alignment = align
        run = paragraph.add_run()
        run.text = line
        run.font.name, run.font.size, run.font.bold, run.font.italic = FONT, Pt(size), bold, italic
        run.font.color.rgb = color
    return box


prs = Presentation(BASE)
W, H = prs.slide_width, prs.slide_height
slide = prs.slides[0]
boxes = {shape.text_frame.text.split('\n')[0]: shape for shape in slide.shapes if shape.has_text_frame}
title, people, dates = boxes[TOPIC], boxes[PEOPLE[0]], boxes['2026.10–2027.05']

# The template background (emblem, school name and building in one picture) goes; nothing on it was editable.
for shape in list(slide.shapes):
    if shape.shape_type == 6:                                    # group
        for rel in [r for r in shape._element.xpath('.//a:blip/@r:embed')]:
            slide.part.drop_rel(rel)
        shape._element.getparent().remove(shape._element)

frame = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Cm(0.8), Cm(0.8), W - Cm(1.6), H - Cm(1.6))
frame.name = 'Frame'
frame.fill.background()
frame.line.color.rgb, frame.line.width = NAVY, Pt(2.25)
frame.shadow.inherit = False
tree = slide.shapes._spTree
tree.remove(frame._element)
tree.insert(2, frame._element)                                   # behind everything else

emblem = slide.shapes.add_picture(EMBLEM, Cm(1.8), Cm(1.5), height=Cm(2.6))
emblem.name = 'Emblem'
left = emblem.left + emblem.width + Cm(0.6)
school = write(slide.shapes.add_textbox(left, Cm(1.7), Cm(21.0), Cm(1.6)), [SCHOOL], size=26, bold=True,
               color=NAVY, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.BOTTOM)
school.name = 'School'
rule = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, left, Cm(3.75), left + Cm(21.0), Cm(3.75))
rule.name = 'Header rule'
rule.line.color.rgb, rule.line.width = RULE, Pt(2)

title.left, title.top, title.width, title.height = Cm(2.5), Cm(7.4), W - Cm(5.0), Cm(3.2)
write(title, [TOPIC], size=40, bold=True, color=NAVY, align=PP_ALIGN.CENTER)
subtitle = write(slide.shapes.add_textbox(Cm(2.5), Cm(10.9), W - Cm(5.0), Cm(1.6)), [SUBTOPIC], size=24,
                 italic=True, color=GREY, align=PP_ALIGN.CENTER)
subtitle.name = 'Subtitle'

dates.left, dates.top, dates.width, dates.height = (W - Cm(8.0)) // 2, H - Cm(3.4), Cm(8.0), Cm(1.2)
write(dates, [DATE], size=20, align=PP_ALIGN.CENTER)
people.left, people.top, people.width, people.height = W - Cm(1.8) - Cm(11.0), H - Cm(4.0), Cm(11.0), Cm(1.9)
write(people, list(PEOPLE), size=18, align=PP_ALIGN.RIGHT)

prs.save(OUT)
print('saved', OUT)
