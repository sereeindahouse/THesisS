"""Render one thesis TikZ figure (thesis/Figures/<name>.tex) to a cropped PNG, e.g. for a slide.

    python tools/export_thesis_figure.py system_structure out.png [--pillow <folder with PIL>]

MiKTeX here has no `standalone` class, so the figure is compiled alone on a large page with the
same fonts and TikZ libraries as thesis/main.tex, rasterised with pdftoppm and cropped to its ink.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from build_thesis_pdfs import _tool                              # noqa: E402

TEMPLATE = r"""\documentclass[11pt]{article}
\usepackage[paperwidth=60cm,paperheight=60cm,margin=2cm]{geometry}
\usepackage{fontspec}
\setmainfont{Times New Roman}
\setsansfont{Arial}
\usepackage{amssymb}
\usepackage{tikz}
\usepackage{xcolor}
\input{palette}
\usetikzlibrary{positioning,arrows.meta,bending,shapes.geometric,shapes.symbols,shapes.multipart,fit,calc,backgrounds,decorations.pathreplacing,shadows}
\pagestyle{empty}
\begin{document}
\noindent\input{FIGURE}
\end{document}
"""


def export(name, target, dpi=200):
    from PIL import Image, ImageChops
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        shutil.copy2(ROOT / 'thesis/Figures' / f'{name}.tex', work / 'figure.tex')
        shutil.copy2(ROOT / 'thesis/Figures/palette.tex', work / 'palette.tex')   # one palette for every figure
        (work / 'page.tex').write_text(TEMPLATE.replace('FIGURE', 'figure'), encoding='utf-8')
        run = subprocess.run([_tool('xelatex'), '-interaction=nonstopmode', '-halt-on-error', 'page.tex'],
                             cwd=work, capture_output=True, check=False)
        if run.returncode != 0 or not (work / 'page.pdf').is_file():
            raise SystemExit(f'xelatex failed for {name}')
        subprocess.run([_tool('pdftoppm'), '-r', str(dpi), '-png', '-singlefile', 'page.pdf', 'page'],
                       cwd=work, check=True)
        image = Image.open(work / 'page.png').convert('RGB')
        box = ImageChops.difference(image, Image.new('RGB', image.size, 'white')).getbbox()
        pad = dpi // 10
        box = (max(box[0] - pad, 0), max(box[1] - pad, 0),
               min(box[2] + pad, image.width), min(box[3] + pad, image.height))
        image.crop(box).save(target)
    return target


if __name__ == '__main__':
    args = sys.argv[1:]
    if '--pillow' in args:
        sys.path.insert(0, args[args.index('--pillow') + 1])
        del args[args.index('--pillow'):args.index('--pillow') + 2]
    print(export(args[0], args[1]))
