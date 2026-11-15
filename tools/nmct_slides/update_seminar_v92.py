"""Seminar deck v92 (2026-11-17): the user's own v90 copy plus audited text fixes and two diagrams.

Base is the deck the user last saved in МИНИЙ-ДИПЛОМ/02_Семинар (v90). The «Зорилго» and «Зорилт»
slides are not touched. Changes:
  1. slide 1 title -> the thesis title «ШМТК-ийн ухаалаг туслах»
  2. reception slide: the teacher e-mail row now says the school e-mail addresses are loaded
  3. «how it works» slide: «эх» -> «эх сурвалж»; what happens when nothing is found
  4. two diagram slides taken from v91 (use case, system structure), inserted as slides 6 and 8
  5. page numbers renumbered

python-pptx is not installed in the project venv; pass its folder as the first argument:
    python tools/nmct_slides/update_seminar_v92.py <pylibs> <base v90> <v91> <out v92> [<use case png> <structure png>]
The two optional PNGs (tools/export_thesis_figure.py) replace the v91 pictures, so the slides show
the same diagrams as the thesis after the 2026-11-16 label changes.
PowerPoint itself is never started (COM hangs on this machine).
"""
import copy
import io
import sys

sys.path.insert(0, sys.argv[1])
from pptx import Presentation                                    # noqa: E402
from pptx.oxml.ns import qn                                      # noqa: E402

BASE, DIAGRAMS, OUT = sys.argv[2], sys.argv[3], sys.argv[4]
NEW_PICTURES = sys.argv[5:7] if len(sys.argv) >= 7 else (None, None)
R_ATTRS = (qn('r:embed'), qn('r:link'), qn('r:id'))
SKIP_RELS = ('slideLayout', 'notesSlide')


def set_paragraph(paragraph, text):
    """Replace a paragraph's text, keeping the first run's formatting."""
    runs = paragraph.runs
    runs[0].text = text
    for run in runs[1:]:
        run.text = ''


def replace_in_frame(frame, old, new):
    done = 0
    for paragraph in frame.paragraphs:
        whole = ''.join(run.text for run in paragraph.runs)
        if old in whole:
            set_paragraph(paragraph, whole.replace(old, new))
            done += 1
    return done


def frames(shapes):
    """Every text frame on a slide, including table cells and grouped shapes."""
    for shape in shapes:
        if shape.shape_type == 6:                                # group
            yield from frames(shape.shapes)
        elif getattr(shape, 'has_table', False) and shape.has_table:
            for row in shape.table.rows:
                for cell in row.cells:
                    yield cell.text_frame
        elif shape.has_text_frame:
            yield shape.text_frame


def replace_on_slide(slide, old, new):
    count = sum(replace_in_frame(frame, old, new) for frame in frames(slide.shapes))
    if count != 1:
        raise SystemExit(f'expected exactly one «{old}» on the slide, found {count}')


def clone_slide(deck, source):
    """Append a copy of `source` (a slide of the same deck), relationships included."""
    target = deck.slides.add_slide(source.slide_layout)
    for shape in list(target.shapes):
        shape._element.getparent().remove(shape._element)
    mapping = {}
    for rel_id, rel in source.part.rels.items():
        if any(kind in rel.reltype for kind in SKIP_RELS):
            continue
        mapping[rel_id] = (target.part.relate_to(rel.target_ref, rel.reltype, is_external=True)
                           if rel.is_external else target.part.relate_to(rel.target_part, rel.reltype))
    copied = [copy.deepcopy(shape._element) for shape in source.shapes]
    background = source._element.cSld.find(qn('p:bg'))
    if background is not None:
        new_bg = copy.deepcopy(background)
        target._element.cSld.insert(0, new_bg)
        copied.append(new_bg)
    for element in copied:
        for node in element.iter():
            for attribute in R_ATTRS:
                value = node.get(attribute)
                if value in mapping:
                    node.set(attribute, mapping[value])
    for element in copied:
        if element.tag != qn('p:bg'):
            target.shapes._spTree.append(element)
    return target


def shape_named(slide, name):
    return next(shape for shape in slide.shapes if shape.name == name)


def import_images(element, source_slide, target_slide):
    """Re-attach pictures inside an element copied from another deck (the title is a picture group)."""
    for node in element.iter():
        for attribute in R_ATTRS:
            value = node.get(attribute)
            if not value:
                continue
            rel = source_slide.part.rels[value]
            if 'image' not in rel.reltype:
                raise SystemExit(f'cannot copy a {rel.reltype} relationship across decks')
            _, new_id = target_slide.part.get_or_add_image_part(io.BytesIO(rel.target_part.blob))
            node.set(attribute, new_id)


def diagram_slide(deck, template, source, image_path=None):
    """A new slide: header of `template`, title and picture of `source` (slide of the v91 deck).

    With `image_path` the picture is that file, fitted and centred in the old picture's box.
    """
    slide = clone_slide(deck, template)
    for shape in list(slide.shapes):
        if getattr(shape, 'has_table', False) and shape.has_table:
            shape._element.getparent().remove(shape._element)
    for name in ('Group 4', 'Group 6', 'AutoShape 9'):            # title text and its underline
        new = copy.deepcopy(shape_named(source, name)._element)
        import_images(new, source, slide)
        old = shape_named(slide, name)._element
        old.getparent().replace(old, new)
    picture = next(shape for shape in source.shapes if shape.shape_type == 13)
    if image_path is None:
        slide.shapes.add_picture(io.BytesIO(picture.image.blob), picture.left, picture.top,
                                 picture.width, picture.height)
        return slide
    added = slide.shapes.add_picture(image_path, picture.left, picture.top)
    scale = min(picture.width / added.width, picture.height / added.height)
    added.width, added.height = int(added.width * scale), int(added.height * scale)
    added.left = picture.left + (picture.width - added.width) // 2
    added.top = picture.top + (picture.height - added.height) // 2
    return slide


def move_slide(deck, slide, position):
    id_list = deck.slides._sldIdLst
    entry = next(item for item in id_list if deck.slides.get(int(item.get('id'))) is slide)
    id_list.remove(entry)
    id_list.insert(position, entry)


def renumber(deck):
    for number, slide in enumerate(deck.slides, 1):
        for shape in slide.shapes:
            if shape.has_text_frame and shape.text_frame.text.strip().isdigit() and shape.top > deck.slide_height * 0.85:
                set_paragraph(shape.text_frame.paragraphs[0], str(number))


deck, source = Presentation(BASE), Presentation(DIAGRAMS)
slides = list(deck.slides)

# 1. title slide
title = next(frame for frame in frames(slides[0].shapes) if 'бичгэн, дуут туслах' in frame.text)
set_paragraph(title.paragraphs[0], 'ШМТК-ийн ухаалаг туслах')
for extra in title.paragraphs[1:]:
    extra._p.getparent().remove(extra._p)

# 2. reception topics: only the row whose first cell is the teacher e-mail topic
table = next(shape.table for shape in slides[4].shapes if getattr(shape, 'has_table', False) and shape.has_table)
row = next(row for row in table.rows if row.cells[0].text_frame.text.startswith('Багшийн имэйл'))
set_paragraph(row.cells[2].text_frame.paragraphs[0], 'Хэсэгчлэн: сургуулийн имэйл бий (76-аас 67)')

# 3. «how it works»
replace_on_slide(slides[5], 'эхтэй нь харуулна', 'эх сурвалжтай нь харуулна')
replace_on_slide(slides[5], 'эхийг шалгаад харуулна. Тохирох эх олдохгүй бол «олдсонгүй» гэнэ',
                 'эх сурвалжийг шалгаад харуулна. Тохирох эх сурвалж олдохгүй бол ресепшн рүү чиглүүлнэ')

# 4. diagrams from v91 (its slides 6 and 8), header cloned from this deck's reception slide
use_case = diagram_slide(deck, slides[4], source.slides[5], NEW_PICTURES[0])
structure = diagram_slide(deck, slides[4], source.slides[7], NEW_PICTURES[1])
move_slide(deck, use_case, 5)
move_slide(deck, structure, 7)

# 5. page numbers
renumber(deck)
deck.save(OUT)
print('saved', len(deck.slides), 'slides')
