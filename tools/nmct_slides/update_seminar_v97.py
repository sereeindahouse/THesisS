"""Seminar deck v97 (2026-11-17): v96 with the two plan tables in the same font size as the other slides.

The supervisor remarked that the plan slides (11, 12) use a smaller font than the rest of the deck
(user, 2026-11-16). v96 set them in 12 pt; the other tables are 14-16 pt. Both plan tables go to
14 pt, like the «хийсэн ажил» table. The 17 rows still fit at the same row height. The table grows
from 732 to 752 pt (right margin 39 pt) and the «Гол ажил» column widens so the longest task stays on
one line also in Canva, which sets Arial wider than PowerPoint/LibreOffice (W03 wrapped there at
740 pt); the side cell margins shrink from 6 to 4 pt. Text, rows, highlighted week (W04) and every other slide stay as they are.

python-pptx is not installed in the project venv; pass its folder as the first argument:
    python tools/nmct_slides/update_seminar_v97.py <pylibs> <base v96> <out v97>
PowerPoint itself is never started (COM hangs on this machine). To look at the result:
    python tools/nmct_slides/render_slides.py <out v97>
"""
import sys

sys.path.insert(0, sys.argv[1])
from pptx import Presentation                                    # noqa: E402
from pptx.util import Pt                                         # noqa: E402

BASE, OUT = sys.argv[2], sys.argv[3]
PLAN_SLIDES = (11, 12)
OLD_SIZE, NEW_SIZE = Pt(12), Pt(14)
COLUMN_WIDTHS = (Pt(64), Pt(94), Pt(390), Pt(204))   # was 62, 90, 358, 222 = 732
SIDE_MARGIN = Pt(4)

deck = Presentation(BASE)
for number in PLAN_SLIDES:
    shape = next(s for s in deck.slides[number - 1].shapes if s.has_table)
    table = shape.table
    assert len(table.columns) == len(COLUMN_WIDTHS)
    assert abs(shape.width - Pt(732)) < Pt(2), 'table width changed in the base'
    for column, width in zip(table.columns, COLUMN_WIDTHS):
        column.width = width
    shape.width = sum(COLUMN_WIDTHS)
    resized = 0
    for row in table.rows:
        for cell in row.cells:
            cell.margin_left = cell.margin_right = SIDE_MARGIN
            for paragraph in cell.text_frame.paragraphs:
                for run in paragraph.runs:
                    assert run.font.size == OLD_SIZE, (number, run.text, run.font.size)
                    run.font.size = NEW_SIZE
                    resized += 1
    print('slide', number, 'runs resized:', resized)

deck.save(OUT)
print('saved', OUT)
