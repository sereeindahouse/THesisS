"""Seminar deck v105 (2026-11-23): v104 with slide 10's proposal line attributed honestly.

The user, 2026-11-23, asked whether Byambadorj et al. (2020) show the four proposals on slide 10. They do not all:
the paper converts Latin-script social-media Mongolian to Cyrillic with a neural model and corrects words by
edit distance against a dictionary (86% of words right); the abbreviation list and the «Ингэж ойлголоо» display
are this project's own proposals. Only that paragraph changes; every other slide is v104 as it was.

    python tools/nmct_slides/update_seminar_v105.py <pylibs> <base v104> <out v105>
"""
import sys

sys.path.insert(0, sys.argv[1])
from pptx import Presentation                                    # noqa: E402

BASE, OUT = sys.argv[2:4]
PROPOSAL = (' латиныг кирилл рүү хөрвүүлж, ойролцоо үгээр засах — Byambadorj нар (2020) нейрон загвар ба ойролцоо '
            'үгийн засвараар латин бичгийн үгийн 86%-ийг зөв хөрвүүлсэн. Нэмж (өөрийн санал): товчилсон үгийн '
            'жагсаалт, «Ингэж ойлголоо: …» гэж харуулах.')

deck = Presentation(BASE)
assert len(deck.slides) == 14, 'expected the 14-slide v104'
slide = deck.slides[9]
assert 'ЛАТИН, ТОВЧИЛСОН БИЧИГ' in slide._element.xml, 'slide 10 is expected to be the Latin-script slide'
notes = next(shape for shape in slide.shapes if shape.has_text_frame and shape.text_frame.text.startswith('Асуудал:'))
paragraph = next(p for p in notes.text_frame.paragraphs if p.runs and p.runs[0].text == 'Санал:')
paragraph.runs[1].text = PROPOSAL
deck.save(OUT)
sys.stdout.reconfigure(encoding='utf-8')
print(OUT, len(deck.slides), 'slides')
