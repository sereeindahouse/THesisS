"""Export the system structure and UML diagrams from /data#tree to PDF.

Reads the page the local server renders (headless Chrome), keeps the two
diagrams exactly as drawn there, and prints each to its own A4 landscape/portrait
PDF in docs/diagrams/. Local only: needs http://127.0.0.1:8765/ running; no
network beyond localhost, no model calls.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/diagrams'
PAGE = 'http://127.0.0.1:8765/data#tree'
CHROMES = [
    Path('C:/Program Files/Google/Chrome/Application/chrome.exe'),
    Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'),
]

# Fit the system graph to its drawn content instead of the on-screen zoom.
FIT_SCRIPT = """<script>
const svg = document.querySelector('svg#systemGraph');
const scene = svg.querySelector('.graph-scene');
scene.removeAttribute('transform');
const box = scene.getBBox();
const pad = 24;
svg.setAttribute('viewBox', [box.x - pad, box.y - pad, box.width + 2 * pad, box.height + 2 * pad].join(' '));
</script>"""

PAGE_CSS = """@page { size: A4 %s; margin: 12mm; }
html, body { margin: 0; background: #fff !important; min-height: 0 !important; font-family: 'Segoe UI', Arial, sans-serif; color: #17332a; }
h1 { font-size: 18pt; margin: 0 0 4mm; }
p.note { font-size: 9pt; color: #55685f; margin: 0 0 4mm; }
.figure svg { width: 100%%; height: auto; max-height: %s; display: block; }
.figure svg * { cursor: default; }
.steps-page { break-before: page; }
.steps-page .system-steps { display: grid !important; grid-template-columns: 1fr 1fr !important; gap: 4mm !important; margin: 0 !important; }
.steps-page .system-steps > li { padding: 4mm !important; break-inside: avoid; }
.steps-page .system-steps h3 { font-size: 11pt !important; line-height: 1.4 !important; }
.steps-page .system-steps p { font-size: 9.5pt !important; line-height: 1.5 !important; color: #3d5246 !important; }
.steps-page .system-steps small { font-size: 8.5pt !important; margin-top: 2mm !important; }
"""


def find_chrome() -> Path:
    for path in CHROMES:
        if path.is_file():
            return path
    raise SystemExit('Chrome эсвэл Edge олдсонгүй.')


def dump_dom(chrome: Path, profile: Path) -> str:
    result = subprocess.run(
        [str(chrome), '--headless=new', '--disable-gpu', f'--user-data-dir={profile}',
         '--virtual-time-budget=8000', '--window-size=1400,1000', '--dump-dom', PAGE],
        capture_output=True, check=True)
    return result.stdout.decode('utf-8')


def extract(dom: str, pattern: str, label: str) -> str:
    match = re.search(pattern, dom, re.S)
    if not match:
        raise SystemExit(f'{label} хуудсанд олдсонгүй — сервер ажиллаж байгаа эсэхийг шалга.')
    return match.group(0)


def page(title: str, note: str, body: str, orientation: str, max_height: str, css: str = '') -> str:
    return (f'<!DOCTYPE html><html lang="mn"><head><meta charset="utf-8"><title>{title}</title>'
            f'<style>{css}\n{PAGE_CSS % (orientation, max_height)}</style></head><body>'
            f'<h1>{title}</h1><p class="note">{note}</p>{body}</body></html>')


def print_pdf(chrome: Path, profile: Path, html: Path, pdf: Path):
    subprocess.run(
        [str(chrome), '--headless=new', '--disable-gpu', f'--user-data-dir={profile}',
         '--virtual-time-budget=3000', '--no-pdf-header-footer',
         f'--print-to-pdf={pdf}', html.as_uri()],
        capture_output=True, check=True)
    if not pdf.is_file() or pdf.stat().st_size == 0:
        raise SystemExit(f'PDF үүссэнгүй: {pdf}')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=OUT)
    args = parser.parse_args(argv)
    chrome = find_chrome()
    args.out.mkdir(parents=True, exist_ok=True)
    css = (ROOT / 'demo/data.css').read_text(encoding='utf-8')
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        profile = tmp / 'profile'
        dom = dump_dom(chrome, profile)
        system_svg = extract(dom, r'<svg id="systemGraph".*?</svg>', 'Системийн бүтцийн зураг')
        steps = extract(dom, r'<ol class="system-steps">.*?</ol>', 'Системийн алхмууд')
        uml_svg = extract(dom, r'<svg class="uml-diagram".*?</svg>', 'UML диаграмм')
        source = f'Эх: {PAGE} (локал систем), бодит кодын одоогийн зураг.'

        jobs = [
            ('Системийн_бүтэц.pdf',
             page('Системийн бүтэц — асуултаас хариулт хүртэл', source,
                  f'<div class="figure">{system_svg}</div>{FIT_SCRIPT}'
                  f'<div class="steps-page"><h1>Алхам бүрийн тайлбар</h1>{steps}</div>',
                  'landscape', '170mm', css)),
            ('UML_идэвхийн_диаграмм.pdf',
             page('Системийн бүтэн үйл явц (UML идэвхийн диаграмм)', source,
                  f'<div class="figure">{uml_svg}</div>', 'portrait', '245mm')),
        ]
        written = []
        for name, html_text in jobs:
            html = tmp / (Path(name).stem + '.html')
            html.write_text(html_text, encoding='utf-8')
            pdf = args.out / name
            print_pdf(chrome, profile, html, pdf)
            written.append(pdf)
    for pdf in written:
        print(f'{pdf.relative_to(ROOT) if pdf.is_relative_to(ROOT) else pdf}  {pdf.stat().st_size // 1024} KB')


if __name__ == '__main__':
    sys.exit(main())
