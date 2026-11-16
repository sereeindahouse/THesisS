"""Seminar deck v95 (2026-11-17): v94 with the plan table's highlighted week moved W03 -> W04.

The seminar on 2026-11-17 falls in W04 (11.16-11.22); v94 still marked W03 (user, 2026-11-16).
Nothing else changes: same text, same slides («Зорилго», «Зорилт» untouched).

python-pptx is not installed in the project venv; pass its folder as the first argument:
    python tools/nmct_slides/update_seminar_v95.py <pylibs> <base v94> <out v95>
PowerPoint itself is never started (COM hangs on this machine). To look at the result, render it
with LibreOffice and open the PDF:
    soffice --headless --convert-to pdf --outdir <dir> <out v95>
"""
import sys

sys.path.insert(0, sys.argv[1])
from pptx import Presentation                                    # noqa: E402
from pptx.oxml.ns import qn                                      # noqa: E402

BASE, OUT = sys.argv[2], sys.argv[3]
OLD_WEEK, NEW_WEEK = 'W03', 'W04'

deck = Presentation(BASE)
table = next(s for s in deck.slides[10].shapes if s.has_table).table
rows = {row.cells[0].text.strip(): row for row in table.rows}
old_row, new_row = rows[OLD_WEEK], rows[NEW_WEEK]

moved = 0
for old_cell, new_cell in zip(old_row.cells, new_row.cells):
    fill = old_cell._tc.tcPr.find(qn('a:solidFill'))
    assert fill is not None, 'highlight not found on ' + OLD_WEEK
    assert new_cell._tc.tcPr.find(qn('a:solidFill')) is None, NEW_WEEK + ' already filled'
    new_cell._tc.get_or_add_tcPr().append(fill)   # lxml moves the element out of the old cell
    moved += 1
assert moved == 4, moved

deck.save(OUT)
print('saved', OUT)
