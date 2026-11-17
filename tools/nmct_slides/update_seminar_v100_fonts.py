"""Seminar deck v100 (2026-11-17): v99 (16:10) with one font size per role on every slide.

User, 2026-11-17: «it has to same in every slide font». The font families already follow the ШМТК
template (`nmct_template.js`: Times New Roman for titles and text, Arial for tables), but the sizes
differed from slide to slide: tables 16 pt (slides 2, 3), 14 pt (4, 9, 10, 11) and 13 pt (5); body
text 22 pt (2) and 18 pt (12); the small note lines 13 pt (3, 5). One size per role now:

    title 20 pt bold (already everywhere) · table 14 pt (the 17-row plan tables do not fit larger)
    body text 18 pt · note/legend line 14 pt · page number 11 pt (already)

Cover (1), closing (13), the knowledge-tree box labels (8) and the picture slides (6, 7) are left as
they are: they are a title page and diagram labels, not running text.

python-pptx is not installed in the project venv; pass its folder as the first argument:
    python tools/nmct_slides/update_seminar_v100_fonts.py <pylibs> <base v99> <out v100>
"""
import sys

sys.path.insert(0, sys.argv[1])
from pptx import Presentation                                    # noqa: E402
from pptx.util import Pt                                         # noqa: E402

BASE, OUT = sys.argv[2], sys.argv[3]
TABLE, BODY, NOTE = Pt(14), Pt(18), Pt(14)
SKIP = {1, 6, 7, 8, 13}
TITLE_SIZE, PAGE_SIZE = Pt(20), Pt(11)

deck = Presentation(BASE)
assert len(deck.slides) == 13, 'expected the 13-slide v99'


def shapes(container):
    for shape in container:
        if shape.shape_type == 6:
            yield from shapes(shape.shapes)
        else:
            yield shape


changed = {}
for number, slide in enumerate(deck.slides, 1):
    if number in SKIP:
        continue
    for shape in shapes(slide.shapes):
        if shape.has_table:
            runs = [r for row in shape.table.rows for c in row.cells
                    for p in c.text_frame.paragraphs for r in p.runs]
            target = TABLE
        elif shape.has_text_frame:
            runs = [r for p in shape.text_frame.paragraphs for r in p.runs]
            sizes = {round(r.font.size.pt) for r in runs if r.font.size and r.text.strip()}
            if not sizes or sizes & {round(TITLE_SIZE.pt), round(PAGE_SIZE.pt)}:
                continue                                   # slide title, page number
            italic_or_legend = all(r.font.italic or round(r.font.size.pt) == 13
                                   for r in runs if r.text.strip() and r.font.size)
            target = NOTE if italic_or_legend else BODY
        else:
            continue
        for run in runs:
            if run.font.size is not None and run.font.size != target:
                changed[number] = changed.get(number, 0) + 1
                run.font.size = target

deck.save(OUT)
print('runs resized per slide:', changed)
print('saved', OUT)
