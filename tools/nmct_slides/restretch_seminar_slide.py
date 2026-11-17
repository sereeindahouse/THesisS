"""Stretch one slide that still has the A4 layout (centred) to the deck's 16:10 width, like the others.

2026-11-17, user: in the final deck (their own file, edited in Canva) slide 8 «Мэдлэгийн мод» was
pasted from an older A4 deck, so it sat in the middle with empty bands at the sides while every other
slide fills the width. Only that slide changes: its boxes, lines and text stay the same (no box is
added or removed); positions and widths follow the same rule as `fit_seminar_to_screen.py`:

    * the A4 layout is first moved back to x = 0 (the offset is read from the header logo);
    * header logo and page number go to the right edge; the page number shows the slide's place;
    * lines turned by ~90° (the tree's vertical spines) keep their length and centre, and are
      stored as unrotated vertical lines (Canva ignores a line's rotation and drew them flat);
    * everything else stretches horizontally by k = deck width / A4 width.

    python tools/nmct_slides/restretch_seminar_slide.py <pylibs> <in.pptx> <out.pptx> <slide number>
"""
import sys

sys.path.insert(0, sys.argv[1])
from pptx import Presentation                                    # noqa: E402

IN, OUT, NUMBER = sys.argv[2], sys.argv[3], int(sys.argv[4])
A = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
A4_W = 10693400                       # template width in EMU (A4 landscape at this height)
A4_LOGO_LEFT = 8357616                # header logo left on the A4 template (9.14 in)

deck = Presentation(IN)
W, H = deck.slide_width, deck.slide_height
assert abs(H - 7556500) < 2000, 'unexpected slide height'
K, DX = W / A4_W, W - A4_W
slide = deck.slides[NUMBER - 1]
shapes = list(slide.shapes)
logo = next(s for s in shapes if s.top < H * 0.2 and s.left > W * 0.6)
offset = logo.left - A4_LOGO_LEFT
assert offset > 0, 'slide already fills the width'


def turned(shape):
    xfrm = shape._element.find('.//' + A + 'xfrm')
    rot = int(xfrm.get('rot', 0)) / 60000 % 180 if xfrm is not None else 0
    return 45 < rot < 135


counts = dict(right_edge=0, vertical=0, stretched=0)
for shape in shapes:
    left = shape.left - offset                        # back to the A4 position
    if left >= A4_W * 0.75 and (shape.top < H * 0.2 or shape.top > H * 0.9):
        shape.left = left + DX
        counts['right_edge'] += 1
        if shape.has_text_frame and shape.text_frame.text.strip().isdigit():
            runs = [r for p in shape.text_frame.paragraphs for r in p.runs]
            runs[0].text = str(NUMBER)
            for run in runs[1:]:
                run.text = ''
    elif turned(shape):
        # Canva draws a line shape without its rotation, so the tree's two vertical spines showed
        # as horizontal lines through the centre box. Store them as unrotated vertical lines.
        length, centre_x = shape.width, (left + shape.width / 2) * K
        centre_y = shape.top + shape.height / 2
        xfrm = shape._element.find('.//' + A + 'xfrm')
        xfrm.attrib.pop('rot', None)
        shape.left, shape.width = round(centre_x), 0
        shape.top, shape.height = round(centre_y - length / 2), length
        counts['vertical'] += 1
    else:
        shape.left, shape.width = round(left * K), round(shape.width * K)
        counts['stretched'] += 1

deck.save(OUT)
print('slide', NUMBER, 'offset', round(offset / 914400, 3), 'in;', counts)
print('saved', OUT)
