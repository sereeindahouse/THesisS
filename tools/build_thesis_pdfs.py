"""Build both thesis PDFs in an isolated copy and copy them back.

    python tools/build_thesis_pdfs.py            # main (full draft) + main_teacher (short draft)
    python tools/build_thesis_pdfs.py main       # only one job

MiKTeX here has no latexmk (perl), so each job runs xelatex, bibtex, xelatex, xelatex.
The build happens in a temporary copy so an editor that holds thesis/main.* open cannot
break it. A job is copied back only when it compiled and left no undefined reference.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
THESIS = ROOT / 'thesis'
JOBS = ('main', 'main_teacher')
SKIP = shutil.ignore_patterns('archive-*', '*.pdf', '*.aux', '*.toc', '*.lot', '*.lof', '*.out',
                              '*.bbl', '*.blg', '*.xdv', '*.fls', '*.fdb_latexmk', '*.synctex*')


def _tool(name):
    found = shutil.which(name)
    if found:
        return found
    return str(Path(os.environ.get('LOCALAPPDATA', '')) / f'Programs/MiKTeX/miktex/bin/x64/{name}.exe')


def build_job(work: Path, job: str):
    xelatex = [_tool('xelatex'), '-interaction=nonstopmode', '-halt-on-error', f'{job}.tex']
    steps = [xelatex, [_tool('bibtex'), job], xelatex, xelatex]
    for step in steps:
        run = subprocess.run(step, cwd=work, capture_output=True, check=False)
        if run.returncode != 0 and step is xelatex:
            return {'job': job, 'ok': False, 'error': f'{Path(step[0]).stem} exit {run.returncode}'}
    log = (work / f'{job}.log').read_text(encoding='utf-8', errors='replace')
    pages = re.search(r'Output written on .*\((\d+) pages?\)', log)
    undefined = len(re.findall(r'LaTeX Warning: (?:Reference|Citation) .* undefined', log))
    return {'job': job, 'ok': bool(pages) and undefined == 0,
            'pages': int(pages.group(1)) if pages else 0, 'undefined': undefined}


def build(jobs=JOBS):
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / 'thesis'
        shutil.copytree(THESIS, work, ignore=SKIP)
        for job in jobs:
            result = build_job(work, job)
            if result['ok']:
                shutil.copy2(work / f'{job}.pdf', THESIS / f'{job}.pdf')
            results.append(result)
    return results


if __name__ == '__main__':
    outcome = build(tuple(sys.argv[1:]) or JOBS)
    print(json.dumps(outcome, ensure_ascii=False))
    sys.exit(0 if all(item['ok'] for item in outcome) else 1)
