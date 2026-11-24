"""Scale a deck to 1920 x 1080 without moving anything relative to anything else (2026-11-24).

Canva's resize rearranged the user's 16:10 deck when it changed the aspect ratio. This keeps the layout: every
slide is scaled by one factor (the height ratio) and centred; fonts, line widths, table columns and rows, text
insets and spacing scale with it. A picture or shape that covered the whole old slide (the building background)
is scaled to cover the whole new slide instead, keeping its proportions (the overflow is cut by the slide edge).

    python tools/nmct_slides/scale_deck_to_1920x1080.py <pylibs> <in.pptx> <out.pptx>
"""
import sys

sys.path.insert(0, sys.argv[1])
from pptx import Presentation                                    # noqa: E402

SRC, OUT = sys.argv[2:4]
NEW_W, NEW_H = 1920 * 9525, 1080 * 9525                          # Canva: 1 px = 9525 EMU
A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
SIZE_ATTRS = {                                                   # element local name -> attributes in EMU or 1/100 pt
    'rPr': ('sz',), 'defRPr': ('sz',), 'endParaRPr': ('sz',), 'ln': ('w',), 'gridCol': ('w',), 'tr': ('h',),
    'bodyPr': ('lIns', 'tIns', 'rIns', 'bIns'), 'tcPr': ('marL', 'marR', 'marT', 'marB'), 'spcPts': ('val',),
    'pPr': ('marL', 'indent'),
}

prs = Presentation(SRC)
W, H = prs.slide_width, prs.slide_height
scale = NEW_H / H
dx = (NEW_W - W * scale) / 2
cover = NEW_W / W                                                # for a full-slide background


def top_xfrm(element):
    for path in ('./p:spPr/a:xfrm', './p:grpSpPr/a:xfrm', './p:xfrm'):
        found = element.xpath(path)
        if found:
            return found[0]
    return None


for slide in prs.slides:
    tree = slide.shapes._spTree
    for element in tree.iterchildren():
        xfrm = top_xfrm(element)
        if xfrm is None:
            continue
        off, ext = xfrm.find('{%s}off' % A), xfrm.find('{%s}ext' % A)
        x, y, cx, cy = (int(off.get('x')), int(off.get('y')), int(ext.get('cx')), int(ext.get('cy')))
        if cx >= 0.95 * W and cy >= 0.95 * H and x <= 0.03 * W and y <= 0.03 * H:
            new = (x * cover, y * cover - (cy * cover - NEW_H) / 2 if cy * cover > NEW_H else y * cover,
                   cx * cover, cy * cover)
        else:
            new = (x * scale + dx, y * scale, cx * scale, cy * scale)
        off.set('x', str(round(new[0]))); off.set('y', str(round(new[1])))
        ext.set('cx', str(round(new[2]))); ext.set('cy', str(round(new[3])))
    for node in tree.iter():
        tag = node.tag.split('}')[-1] if isinstance(node.tag, str) else ''
        for attr in SIZE_ATTRS.get(tag, ()):
            value = node.get(attr)
            if value is not None and value.lstrip('-').isdigit():
                node.set(attr, str(round(int(value) * scale)))

prs.slide_width, prs.slide_height = NEW_W, NEW_H
prs.save(OUT)
print('saved', OUT, 'scale', round(scale, 4), 'dx px', round(dx / 9525))
