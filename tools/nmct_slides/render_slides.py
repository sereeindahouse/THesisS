"""Render a seminar .pptx into slide pictures so the deck can be checked without PowerPoint.

PowerPoint COM hangs on this machine (11/15), so LibreOffice (installed 11/16) does the rendering:
    pptx --soffice--> pdf --pdftoppm (MiKTeX)--> one PNG per slide + sheet.png (all slides on one page)

Usage (system Python, it has Pillow; the project .venv does not):
    python tools/nmct_slides/render_slides.py "МИНИЙ-ДИПЛОМ/02_Семинар/17_Семинар_ШМТК_v94.pptx"
Output: runtime/slide-render/<file name>/  (git-ignored; nothing leaves the computer)

LibreOffice draws some things differently from PowerPoint (group fill colours, fonts), so a clean
render is a strong hint, not proof that PowerPoint shows the same. A private LibreOffice profile is
used so an already open LibreOffice window is not touched.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

SOFFICE = Path(r'C:\Program Files\LibreOffice\program\soffice.exe')
ROOT = Path(__file__).resolve().parents[2]


def render(pptx: Path, dpi: int = 80, columns: int = 3) -> Path:
    out = ROOT / 'runtime' / 'slide-render' / pptx.stem
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        deck = tmp / 'deck.pptx'          # ASCII name: soffice/pdftoppm/curl choke on Cyrillic paths
        shutil.copy2(pptx, deck)
        profile = (tmp / 'profile').as_uri()
        subprocess.run([str(SOFFICE), f'-env:UserInstallation={profile}', '--headless',
                        '--convert-to', 'pdf', '--outdir', str(tmp), str(deck)],
                       check=True, timeout=300)
        pdf = tmp / 'deck.pdf'
        if not pdf.is_file():
            raise SystemExit('LibreOffice did not produce a PDF')
        subprocess.run(['pdftoppm', '-png', '-r', str(dpi), str(pdf), str(tmp / 'slide')],
                       check=True, timeout=300)
        for picture in tmp.glob('slide-*.png'):   # pdftoppm cannot write into a Cyrillic folder
            shutil.copy2(picture, out / picture.name)
        shutil.copy2(pdf, out / 'deck.pdf')
    pages = sorted(out.glob('slide-*.png'))
    images = [Image.open(p) for p in pages]
    width, height = images[0].size
    rows = -(-len(images) // columns)
    sheet = Image.new('RGB', (width * columns, height * rows), 'white')
    for i, image in enumerate(images):
        sheet.paste(image, ((i % columns) * width, (i // columns) * height))
    sheet.save(out / 'sheet.png')
    print(f'{len(pages)} slides -> {out}')
    return out


if __name__ == '__main__':
    render(Path(sys.argv[1]).resolve())
