"""Seminar deck v98 (2026-11-17): v97 turned from A4 landscape into 16:9 so it fills a wide screen.

The user presented v97 in Canva full screen and saw black bands on both sides: the ШМТК template is
A4 landscape (29.7 x 21 cm, ratio 1.41) and the screen is wider (user, 2026-11-17: «16:9 хий»).
The slide height stays the same; only the width grows by k = (16/9) / (A4 ratio) ~ 1.256.

    * cover and closing background (photo of the building with logo and college name): the photo
      itself is 16:9 and was cropped at the sides to fit A4, so the frame widens and the crop goes;
    * header logo (top right) and page number move right with the edge, size unchanged;
    * pictures and groups holding a picture (use case, system figure, closing logo) keep their size
      and aspect ratio; only their centre moves with the slide;
    * everything else (titles, text, tables with their columns, boxes, arrows, lines) is stretched
      horizontally by k; font sizes and every text stay as they are;
    * the two edits the user made to v97 in Canva are copied (see the end of the script), and the
      page numbers follow the new order.

python-pptx is not installed in the project venv; pass its folder as the first argument:
    python tools/nmct_slides/update_seminar_v98_16x9.py <pylibs> <base v97> <out v98>
PowerPoint itself is never started (COM hangs on this machine). To look at the result:
    python tools/nmct_slides/render_slides.py <out v98>
"""
import sys

sys.path.insert(0, sys.argv[1])
from pptx import Presentation                                    # noqa: E402
from pptx.util import Emu                                        # noqa: E402

BASE, OUT = sys.argv[2], sys.argv[3]
A = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
P = '{http://schemas.openxmlformats.org/presentationml/2006/main}'

deck = Presentation(BASE)
OLD_W, H = deck.slide_width, deck.slide_height
assert abs(OLD_W - 10693400) < 1000 and abs(H - 7556500) < 1000, 'base is not the A4 template'
NEW_W = round(H * 16 / 9)
K, DX = NEW_W / OLD_W, NEW_W - OLD_W


def visible(blip):
    # The Canva export puts fully transparent image fills (alphaModFix amt=0) behind every title
    # and box; they are not pictures and must stretch with their text.
    alpha = blip.find(A + 'alphaModFix')
    return alpha is None or alpha.get('amt') != '0'


def holds_picture(shape):
    if shape.shape_type == 13:                         # real picture: use case, system figure
        return True
    if shape.shape_type == 5 and shape.width > Emu(914400 * 2):
        return False                                   # image-filled panel (slide 7 «RAG хэсэг»)
    return any(visible(b) for b in shape._element.iter(A + 'blip'))   # arrows, closing logo


def full_bleed(shape):
    return shape.left <= Emu(10000) and shape.top <= Emu(10000) and shape.width >= OLD_W * 0.99


counts = dict(background=0, right_edge=0, picture=0, stretched=0, table=0)
for number, slide in enumerate(deck.slides, 1):
    for shape in slide.shapes:
        if full_bleed(shape) and holds_picture(shape):
            shape.width = NEW_W + (shape.width - OLD_W)
            for rect in shape._element.iter(A + 'fillRect'):
                for side in ('l', 'r', 't', 'b'):
                    rect.attrib.pop(side, None)
            counts['background'] += 1
        elif shape.left >= OLD_W * 0.75 and (shape.top < H * 0.2 or shape.top > H * 0.9):
            # header logo (top right) and page number (bottom right), not the 5th step box
            shape.left = shape.left + DX
            counts['right_edge'] += 1
        elif holds_picture(shape):
            centre = shape.left + shape.width / 2
            shape.left = round(centre * K - shape.width / 2)
            counts['picture'] += 1
        else:
            shape.left, shape.width = round(shape.left * K), round(shape.width * K)
            if shape.has_table:
                for column in shape.table.columns:
                    column.width = round(column.width * K)
                counts['table'] += 1
            counts['stretched'] += 1

deck.slide_width = NEW_W

# The user's own copy of v97 in Canva (edited 2026-11-17 before the seminar) differs from the file in
# two places; v98 follows the user's copy: the dates sit on the same line as the names (left of
# them), and slide 7 «Систем хэрхэн ажилладаг вэ» is gone (13 slides).
cover = deck.slides[0]
names = next(s for s in cover.shapes if s.has_text_frame and s.text_frame.text.startswith('Оюутан'))
dates = next(s for s in cover.shapes if s.has_text_frame and s.text_frame.text.startswith('2026.10'))
dates.top = names.top
dates.left = names.left - dates.width - round(Emu(914400 * 0.3))
removed = deck.slides[6]
assert any(s.has_text_frame and 'ХЭРХЭН АЖИЛЛАДАГ' in s.text_frame.text.upper()
           for s in removed.shapes for s in ([s] + (list(s.shapes) if s.shape_type == 6 else []))), \
    'slide 7 is not «Систем хэрхэн ажилладаг вэ»'
slide_ids = deck.slides._sldIdLst
removed_id = slide_ids[6]
deck.part.drop_rel(removed_id.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'))
slide_ids.remove(removed_id)
print('slides after removing «Систем хэрхэн ажилладаг вэ»:', len(deck.slides))
renumbered = 0
for number, slide in enumerate(deck.slides, 1):
    for shape in slide.shapes:
        if shape.has_text_frame and shape.top > H * 0.9 and shape.text_frame.text.strip().isdigit():
            runs = [r for p in shape.text_frame.paragraphs for r in p.runs]
            runs[0].text = str(number)
            for run in runs[1:]:
                run.text = ''
            renumbered += 1
print('page numbers rewritten:', renumbered)
deck.save(OUT)
print('slide size', round(OLD_W / 914400, 2), '->', round(NEW_W / 914400, 2), 'x', round(H / 914400, 2), 'in')
print(counts)
print('saved', OUT)
