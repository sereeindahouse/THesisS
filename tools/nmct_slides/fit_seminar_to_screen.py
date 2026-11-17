"""Fit an A4-landscape ШМТК seminar deck to a wider screen (16:10 or 16:9) so it fills it in full screen.

2026-11-17, user: in Canva full screen the A4 deck (ratio 1.41) left black bands at the sides, the 16:9
v98 then left bands at the top and bottom, because the user's screen is 1920 x 1200 = 16:10.
«it must full». The base is the user's own deck as exported from Canva (the user edits there).

The slide height stays the same; only the width grows by k = ratio / (A4 ratio):
    * cover and closing background (building photo with logo and college name): the frame widens;
      the photo is 16:9 and was cropped at the sides for A4, so the crop is recomputed for the new
      frame (at 16:10 the photo's sides are still trimmed a little, nothing is stretched);
    * header logo (top right) and page number move right with the edge, size unchanged;
    * pictures and groups holding a visible picture (use case, system figure, arrows, closing logo)
      keep their size and aspect ratio; only their centre moves with the slide;
    * everything else (titles, text, tables with their columns, boxes, lines) stretches horizontally
      by k; font sizes and every text stay as they are. Fully transparent image fills that the Canva
      export puts behind titles and boxes are not pictures.
    * page numbers are rewritten in slide order (the user removed a slide in Canva).

python-pptx is not installed in the project venv; pass its folder as the first argument:
    python tools/nmct_slides/fit_seminar_to_screen.py <pylibs> <base.pptx> <out.pptx> 16:10
PowerPoint itself is never started (COM hangs on this machine). To look at the result:
    python tools/nmct_slides/render_slides.py <out.pptx>
"""
import sys

sys.path.insert(0, sys.argv[1])
from pptx import Presentation                                    # noqa: E402
from pptx.util import Emu                                        # noqa: E402

BASE, OUT = sys.argv[2], sys.argv[3]
RATIO_W, RATIO_H = (int(x) for x in (sys.argv[4] if len(sys.argv) > 4 else '16:10').split(':'))
A = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
INCH = 914400

deck = Presentation(BASE)
OLD_W, H = deck.slide_width, deck.slide_height
assert abs(OLD_W / H - 297 / 210) < 0.01, 'base is not the A4 landscape template'
NEW_W = round(H * RATIO_W / RATIO_H)
K, DX = NEW_W / OLD_W, NEW_W - OLD_W


def visible(blip):
    alpha = blip.find(A + 'alphaModFix')
    return alpha is None or alpha.get('amt') != '0'


def holds_picture(shape):
    if shape.shape_type == 13:
        return True
    if shape.shape_type == 5 and shape.width > Emu(2 * INCH):
        return False                                   # image-filled panel: stretch it
    return any(visible(b) for b in shape._element.iter(A + 'blip'))


def full_bleed(shape):
    return shape.left <= Emu(10000) and shape.top <= Emu(10000) and shape.width >= OLD_W * 0.99


def refit_photo(shape, old_w, new_w):
    """Recompute the side crop of a stretched photo fill so the photo keeps its own aspect ratio."""
    for fill in shape._element.iter(A + 'blipFill'):
        rect = fill.find(A + 'stretch/' + A + 'fillRect')
        if rect is None:
            continue
        l, r = int(rect.get('l', 0)), int(rect.get('r', 0))
        # fillRect l/r are 1/1000 % of the frame; negative = photo extends beyond the frame.
        photo_w = old_w * (1 - (l + r) / 100000)      # photo width the old frame showed it at
        side = round((1 - photo_w / new_w) / 2 * 100000)
        rect.set('l', str(side))
        rect.set('r', str(side))


counts = dict(background=0, right_edge=0, picture=0, stretched=0, table=0)
for slide in deck.slides:
    for shape in slide.shapes:
        if full_bleed(shape) and holds_picture(shape):
            old_frame = shape.width
            shape.width = NEW_W + (old_frame - OLD_W)
            refit_photo(shape, old_frame, shape.width)
            counts['background'] += 1
        elif shape.left >= OLD_W * 0.75 and (shape.top < H * 0.2 or shape.top > H * 0.9):
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

renumbered = 0
for number, slide in enumerate(deck.slides, 1):
    for shape in slide.shapes:
        if shape.has_text_frame and shape.top > H * 0.9 and shape.text_frame.text.strip().isdigit():
            runs = [r for p in shape.text_frame.paragraphs for r in p.runs]
            runs[0].text = str(number)
            for run in runs[1:]:
                run.text = ''
            renumbered += 1

deck.save(OUT)
print('slide size', round(OLD_W / INCH, 2), '->', round(NEW_W / INCH, 2), 'x', round(H / INCH, 2), 'in',
      f'({RATIO_W}:{RATIO_H}), slides', len(deck.slides))
print(counts, 'page numbers:', renumbered)
print('saved', OUT)
