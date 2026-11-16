"""Seminar deck v93 (2026-11-17): v92 plus the wording the user asked for on 2026-11-16.

Base is the deck last saved in МИНИЙ-ДИПЛОМ/02_Семинар (v92). «Зорилго», «Зорилт» and every other
slide stay as they are. Changes:
  1. reception slide: the third column no longer lists what is missing («мэдээлэл алга»); it says
     what the system has and what will be collected, matching thesis table 4.2
  2. system structure slide: the picture is re-exported from the thesis figure (the data box now
     reads «Сургуулийн өгсөн жагсаалт, хуваарь»)

python-pptx is not installed in the project venv; pass its folder as the first argument:
    python tools/nmct_slides/update_seminar_v93.py <pylibs> <base v92> <out v93> [<structure png>]
PowerPoint itself is never started (COM hangs on this machine).
"""
import sys

sys.path.insert(0, sys.argv[1])
from pptx import Presentation                                    # noqa: E402

BASE, OUT = sys.argv[2], sys.argv[3]
STRUCTURE_PNG = sys.argv[4] if len(sys.argv) >= 5 else None

# first cell of the row -> new text of the third cell
RECEPTION = {
    'Сургалтын төлбөр': 'Төлбөрийн дүн бий; төлөх журмыг цуглуулна',
    'Багшийн имэйл': 'Сургуулийн имэйл бий (76-аас 67)',
    'Ажлын байрны анкет': 'Цуглуулна: анкет бөглөх газар',
    'Ярилцлагад хаана очих': 'Цуглуулна: ярилцлага болох өрөө, давхар',
    'Гадны хүүхдэд давтлага': 'Цуглуулна: давтлага өгдөг эсэх',
    'Сургалтын орчин': 'Сайтын «Суралцахад төгс орчин» хуудас бий',
    'Харилцаа, хандлага': 'Баримтаар хариулах сэдэв биш',
    'Дотуур байр': 'Цуглуулна: дотуур байр байдаг эсэх',
}


def set_paragraph(paragraph, text):
    """Replace a paragraph's text, keeping the first run's formatting."""
    runs = paragraph.runs
    runs[0].text = text
    for run in runs[1:]:
        run.text = ''


def title_of(slide):
    """All text of the slide (the title sits inside a group, so read the slide XML)."""
    return slide._element.xml


deck = Presentation(BASE)
slides = list(deck.slides)

# 1. reception topics
reception = next(slide for slide in slides
                 if any(getattr(shape, 'has_table', False) and shape.has_table and len(shape.table.columns) >= 3
                        and shape.table.cell(0, 2).text_frame.text.strip() == 'Систем одоо' for shape in slide.shapes))
table = next(shape.table for shape in reception.shapes if getattr(shape, 'has_table', False) and shape.has_table)
set_paragraph(table.cell(0, 2).text_frame.paragraphs[0], 'Мэдээлэл')
done = set()
for row in list(table.rows)[1:]:
    topic = row.cells[0].text_frame.text.strip()
    key = next((name for name in RECEPTION if topic.startswith(name)), None)
    if key is None:
        raise SystemExit(f'unexpected reception row «{topic}»')
    set_paragraph(row.cells[2].text_frame.paragraphs[0], RECEPTION[key])
    done.add(key)
if done != set(RECEPTION):
    raise SystemExit(f'rows not found: {sorted(set(RECEPTION) - done)}')

# 2. system structure picture
if STRUCTURE_PNG:
    structure = next(slide for slide in slides
                     if 'СИСТЕМИЙН БҮТЭЦ' in title_of(slide) and any(shape.shape_type == 13 for shape in slide.shapes))
    old = next(shape for shape in structure.shapes if shape.shape_type == 13)
    left, top, width, height = old.left, old.top, old.width, old.height
    added = structure.shapes.add_picture(STRUCTURE_PNG, left, top)
    scale = min(width / added.width, height / added.height)
    added.width, added.height = int(added.width * scale), int(added.height * scale)
    added.left = left + (width - added.width) // 2
    added.top = top + (height - added.height) // 2
    old._element.getparent().remove(old._element)

deck.save(OUT)
print('saved', len(deck.slides), 'slides ->', OUT)
