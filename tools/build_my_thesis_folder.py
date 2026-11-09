"""Keep МИНИЙ-ДИПЛОМ/ as the one folder where the user finds every essential output.

Copies the newest deliverables (thesis PDF, seminar deck, school request, reading
guides, notebook) and links the LaTeX source, then writes 00_ЭНДЭЭС_ЭХЭЛ.md.
Local only: no network, no model calls. The folder is git-ignored (public repo).

A copy the user edited after the last run is never overwritten or removed; the
index flags it instead. Runs from the Claude Code Stop hook, so it must stay fast
and must never fail loudly.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
FOLDER = 'МИНИЙ-ДИПЛОМ'
MANIFEST = '.manifest.json'
INDEX = '00_ЭНДЭЭС_ЭХЭЛ.md'
LATEX_LINK = ('01_Диплом', 'LaTeX_бичвэр')

SECTIONS = {
    '01_Диплом': 'Дипломын бичвэр: LaTeX эх (холбоос, засвар шууд `thesis/`-д орно), хамгийн сүүлийн PDF, системийн бүтэц ба UML зургийн PDF (`tools/export_system_diagrams.py`).',
    '02_Семинар': 'Хамгийн сүүлийн семинарын PPT ба яриа.',
    '03_Сургуульд_өгөх': 'Сургуульд өгөх баримт.',
    '04_Унших': 'Өгүүлэл унших Монгол хөтөч (англи эхтэй хамт уншина).',
    '05_Дэвтэр': 'Дэвтрийн асуулт ба сургуулийн гарын авлага.',
}

KEY_DOCS = [
    ('Миний ажил нэг хуудсанд', 'CORE/THESIS-START.mn.md'),
    ('Долоо хоногийн төлөвлөгөө ба унших жагсаалт', 'CORE/WEEKLY-PLAN-2026-2027.mn.md'),
    ('Өдөр бүрийн хийсэн ажил, нотолгоо', 'CORE/PROJECT-NOTE.mn.md'),
    ('Сургуулийн заавар (семинар, дэвтэр, үзлэг)', 'CORE/SCHOOL-THESIS-GUIDE.mn.md'),
    ('Мэдлэгийн мод', 'CORE/KNOWLEDGE-TREE.mn.md'),
]


def _newest(paths):
    paths = [path for path in paths if path.is_file()]
    return max(paths, key=lambda path: path.stat().st_mtime) if paths else None


def planned_copies(root: Path):
    """Return [(section, destination name, source path)] for files that exist."""
    plan = []

    def add(section, source, name=None):
        if source is not None and source.is_file():
            plan.append((section, name or source.name, source))

    # 11/09: хоёр ноорог — 1) багшид үзүүлэх (main_teacher), 2) ажлын, бүх бүлэг (main).
    add('01_Диплом', root / 'thesis/main_teacher.pdf', 'Диплом_1_багшид_үзүүлэх.pdf')
    add('01_Диплом', root / 'thesis/main.pdf', 'Диплом_2_ажлын_ноорог.pdf')
    for source in sorted(root.glob('docs/diagrams/*.pdf')):
        add('01_Диплом', source)
    seminars = sorted(root.glob('CORE/seminar-*'))
    add('02_Семинар', _newest(p for folder in seminars for p in folder.glob('*.pptx')))
    add('02_Семинар', _newest(p for folder in seminars for p in folder.glob('*Яриа*.md')))
    for source in sorted(root.glob('data/school-request/*.pdf')):
        add('03_Сургуульд_өгөх', source)
    for source in sorted(root.glob('papers/*hotoch*.md')):
        add('04_Унших', source)
    add('05_Дэвтэр', _newest(p for folder in seminars for p in folder.glob('*Дэвтэр*.md')))
    add('05_Дэвтэр', root / 'runtime/school-handbook-20261028/ТСА гарын авлага.pdf')
    return plan


def _stamp(path: Path):
    stat = path.stat()
    return [stat.st_size, int(stat.st_mtime)]


def _ensure_link(link: Path, target: Path):
    if not target.is_dir() or link.exists() or link.is_symlink():
        return link.exists()
    link.parent.mkdir(parents=True, exist_ok=True)
    if os.name == 'nt':
        result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(target)],
                                capture_output=True, check=False)
        return result.returncode == 0
    link.symlink_to(target, target_is_directory=True)
    return True


def build(root: Path = ROOT):
    out = root / FOLDER
    out.mkdir(exist_ok=True)
    manifest_path = out / MANIFEST
    try:
        old = json.loads(manifest_path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        old = {}
    new, edited, rows = {}, [], []
    for section, name, source in planned_copies(root):
        relative = f'{section}/{name}'
        dest = out / section / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        recorded = old.get(relative)
        if dest.exists() and recorded and _stamp(dest) != recorded:
            edited.append(relative)
            new[relative] = recorded
        elif not dest.exists() or _stamp(source) != _stamp(dest):
            shutil.copy2(source, dest)
            new[relative] = _stamp(dest)
        else:
            new[relative] = _stamp(dest)
        rows.append((section, name, source.relative_to(root).as_posix(),
                     datetime.fromtimestamp(source.stat().st_mtime).strftime('%Y-%m-%d %H:%M')))
    # An older copy that a newer file replaced: remove it only if the user never touched it.
    for relative, recorded in old.items():
        dest = out / relative
        if relative not in new and dest.is_file():
            if _stamp(dest) == recorded:
                dest.unlink()
            else:
                edited.append(relative)
                new[relative] = recorded
    link_ok = _ensure_link(out.joinpath(*LATEX_LINK), root / 'thesis')
    manifest_path.write_text(json.dumps(new, ensure_ascii=False, indent=1), encoding='utf-8')
    (out / INDEX).write_text(render_index(rows, edited, link_ok), encoding='utf-8')
    return {'files': len(rows), 'edited_copies': edited, 'latex_link': link_ok}


def render_index(rows, edited, link_ok):
    lines = [
        '# Миний диплом — бүх чухал зүйл энд',
        '',
        f'Шинэчилсэн: {datetime.now().strftime("%Y-%m-%d %H:%M")}. Энэ хавтсыг Claude хариулт бүрийн дараа '
        'автоматаар шинэчилнэ (`tools/build_my_thesis_folder.py`). Хуулбарыг энд засвал дарагдахгүй, '
        'гэхдээ эх файл руу нь буцааж хуулах хэрэгтэй. GitHub-д гарахгүй.',
        '',
    ]
    if edited:
        lines += ['**⚠ Та эдгээр хуулбарыг энд зассан байна — эх файл руу нь хуулаарай:**', '']
        lines += [f'- `{item}`' for item in edited] + ['']
    for section, about in SECTIONS.items():
        lines += [f'## {section}', '', about, '']
        if section == LATEX_LINK[0]:
            state = 'бэлэн' if link_ok else 'үүсээгүй — `thesis/`-ийг шууд нээнэ үү'
            lines.append(f'- `{LATEX_LINK[1]}/` → `thesis/` ({state})')
        for row_section, name, source, modified in rows:
            if row_section == section:
                lines.append(f'- `{name}` — эх: `{source}`, {modified}')
        lines.append('')
    lines += ['## Үндсэн баримтууд (эх файлыг нь нээж уншина)', '']
    lines += [f'- {label}: `{path}`' for label, path in KEY_DOCS]
    lines += ['', '## Локал хуудсууд (`CORE/DEMO.cmd` асаасны дараа)', '',
              '- Чат: http://127.0.0.1:8765/',
              '- Мэдлэгийн атлас, мод, одны зураг: http://127.0.0.1:8765/data',
              '- Өгүүлэл унших өрөө: http://127.0.0.1:8765/reader',
              '- Кодын хот: http://127.0.0.1:8765/code-map', '']
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--quiet', action='store_true', help='Hook mode: never fail, print nothing.')
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    try:
        result = build(args.root.resolve())
    except Exception:  # the hook must not interrupt the session
        if args.quiet:
            return 0
        raise
    if not args.quiet:
        print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
