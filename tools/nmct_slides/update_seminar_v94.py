"""Seminar deck v94 (2026-11-17): v93 plus two layout fixes the user found on 2026-11-16.

Base is the deck last saved in МИНИЙ-ДИПЛОМ/02_Семинар (v93). Text and every other slide stay as
they are («Зорилго», «Зорилт» untouched). Changes:
  1. slide 7: the «RAG хэсэг» label was light blue (05A0EA) on the teal box and unreadable;
     it is now the title navy (0E3199) and bold
  2. slides 11-12: the plan table's «Гол ажил» column was too narrow (W03 wrapped out of its row);
     the week and date columns give it 31 pt: 81/102/327/222 -> 62/90/358/222 (same total width)

python-pptx is not installed in the project venv; pass its folder as the first argument:
    python tools/nmct_slides/update_seminar_v94.py <pylibs> <base v93> <out v94>
PowerPoint itself is never started (COM hangs on this machine).
"""
import sys

sys.path.insert(0, sys.argv[1])
from pptx import Presentation                                    # noqa: E402
from pptx.dml.color import RGBColor                              # noqa: E402
from pptx.util import Pt                                         # noqa: E402

BASE, OUT = sys.argv[2], sys.argv[3]
NAVY = RGBColor(0x0E, 0x31, 0x99)
PLAN_WIDTHS_PT = (62, 90, 358, 222)


def walk(shapes):
    for shape in shapes:
        yield shape
        if shape.shape_type == 6:  # group
            yield from walk(shape.shapes)


deck = Presentation(BASE)

# 1. readable RAG label
hits = 0
for shape in walk(deck.slides[6].shapes):
    if shape.has_text_frame and shape.text_frame.text.strip() == 'RAG хэсэг':
        for run in shape.text_frame.paragraphs[0].runs:
            run.font.color.rgb = NAVY
            run.font.bold = True
        hits += 1
assert hits == 1, f'RAG label found {hits} times'

# 2. wider «Гол ажил» column in both plan tables
for index in (10, 11):
    table = next(s for s in deck.slides[index].shapes if s.has_table).table
    header = [c.text for c in table.rows[0].cells]
    assert header[2] == 'Гол ажил', header
    old_total = sum(c.width for c in table.columns)
    for column, width in zip(table.columns, PLAN_WIDTHS_PT):
        column.width = Pt(width)
    assert abs(sum(c.width for c in table.columns) - old_total) < Pt(2), 'table width changed'

deck.save(OUT)
print('saved', OUT)
