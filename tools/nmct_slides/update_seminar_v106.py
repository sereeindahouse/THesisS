"""Seminar deck v106 (2026-11-23): slide 10 presents the Latin-script work as future work.

The user, 2026-11-23: «that Latin work is future work, so just do it in the PPT» — nothing is built in the system now;
the slide keeps the measured problem and the proposal, now under «Цаашдын ажил», and no longer asks the teacher to
decide. Only slide 10 changes; every other slide is v105 as it was.

    python tools/nmct_slides/update_seminar_v106.py <pylibs> <base v105> <out v106>
"""
import sys

sys.path.insert(0, sys.argv[1])
from pptx import Presentation                                    # noqa: E402

BASE, OUT = sys.argv[2:4]
OLD_TITLE = 'ШИЙДЭХ АСУУДАЛ: ЛАТИН, ТОВЧИЛСОН БИЧИГ'
TITLE = 'ЦААШДЫН АЖИЛ: ЛАТИН, ТОВЧИЛСОН БИЧИГ'
FUTURE = ('Цаашдын ажил:', ' латиныг кирилл рүү хөрвүүлж, ойролцоо үгээр засах — Byambadorj нар (2020) нейрон загвар '
          'ба ойролцоо үгийн засвараар латин бичгийн үгийн 86%-ийг зөв хөрвүүлсэн. Нэмж (өөрийн санал): товчилсон '
          'үгийн жагсаалт, «Ингэж ойлголоо: …» гэж харуулах. Энэ хугацаанд хэрэгжүүлэхгүй.')

deck = Presentation(BASE)
assert len(deck.slides) == 14, 'expected the 14-slide v105'
slide = deck.slides[9]
title = next(shape for group in slide.shapes if group.shape_type == 6 for shape in group.shapes
             if shape.has_text_frame and shape.text_frame.text == OLD_TITLE)
title.text_frame.paragraphs[0].runs[0].text = TITLE
for run in title.text_frame.paragraphs[0].runs[1:]:
    run.text = ''
notes = next(shape for shape in slide.shapes if shape.has_text_frame and shape.text_frame.text.startswith('Асуудал:'))
paragraphs = notes.text_frame.paragraphs
proposal = next(p for p in paragraphs if p.runs and p.runs[0].text == 'Санал:')
proposal.runs[0].text, proposal.runs[1].text = FUTURE
ask = next(p for p in paragraphs if p.runs and p.runs[0].text == 'Багшаас:')
ask._p.getparent().remove(ask._p)          # the decision is made: no question to the teacher on this slide
deck.save(OUT)
sys.stdout.reconfigure(encoding='utf-8')
print(OUT, len(deck.slides), 'slides')
