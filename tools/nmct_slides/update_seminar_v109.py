"""Seminar deck v109 (2026-11-24): the user's three changes to the v108 title slide.

The user (11/24) confirmed the sketch was for the deck and asked: the building picture back in the background, «Үзлэг»
instead of «Дэд сэдэв» (the word before «( )» on the sketch), and the emblem and the school's name bigger. In Canva the
user had also removed the frame of v108 (the design's text was unchanged), so v109 has no frame. The building is the
template's own faded picture (assets/building_bg.jpg) as a separate picture at the back, cropped to 16:10, so it can be
moved or deleted. Every other slide is v108 (= v107) as it was.

    python tools/nmct_slides/update_seminar_v109.py <pylibs> <base v108> <out v109>
"""
import sys

sys.path.insert(0, sys.argv[1])
from pptx import Presentation                                    # noqa: E402
from pptx.dml.color import RGBColor                              # noqa: E402
from pptx.util import Cm, Pt                                     # noqa: E402

BASE, OUT = sys.argv[2:4]
BUILDING = 'tools/nmct_slides/assets/building_bg.jpg'            # 1536 x 864, already faded
SUBTITLE, NOTE = 'Үзлэг', RGBColor(0x33, 0x33, 0x33)

prs = Presentation(BASE)
W, H = prs.slide_width, prs.slide_height
slide = prs.slides[0]
shapes = {shape.name: shape for shape in slide.shapes}

frame = shapes.get('Frame')                                      # removed by the user in Canva
if frame is not None:
    frame._element.getparent().remove(frame._element)

background = slide.shapes.add_picture(BUILDING, 0, 0, W, H)
background.name = 'Background building'
side = (1 - (W / H) / (1536 / 864)) / 2                          # 16:9 picture on a 16:10 slide: crop, never stretch
background.crop_left = background.crop_right = side
tree = slide.shapes._spTree
tree.remove(background._element)
tree.insert(2, background._element)                              # behind everything else

emblem = shapes['Emblem']
emblem.left, emblem.top = Cm(1.5), Cm(1.2)
emblem.height, emblem.width = Cm(3.6), int(Cm(3.6) * 194 / 213)
left = emblem.left + emblem.width + Cm(0.6)
school = shapes['School']
school.left, school.top, school.width, school.height = left, Cm(1.6), Cm(26.0), Cm(2.5)
for run in school.text_frame.paragraphs[0].runs:
    run.font.size = Pt(34)
rule = shapes['Header rule']
rule.begin_x, rule.begin_y, rule.end_x, rule.end_y = left, Cm(4.6), left + Cm(26.0), Cm(4.6)

title = shapes['TextBox 4']
title.top, title.height = Cm(7.6), Cm(3.4)
subtitle = shapes['Subtitle']
subtitle.top, subtitle.height = Cm(11.3), Cm(1.9)
paragraph = subtitle.text_frame.paragraphs[0]
for extra in paragraph.runs[1:]:
    extra._r.getparent().remove(extra._r)
run = paragraph.runs[0]
run.text = SUBTITLE
run.font.size, run.font.italic, run.font.bold = Pt(30), False, False
run.font.color.rgb = NOTE

prs.save(OUT)
print('saved', OUT)
