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
KEEP_OLDER = ('02_Семинар/',)
ARCHIVE = 'Хуучин'   # earlier seminar decks and speeches are moved here, never deleted
LATEX_LINK = ('01_Диплом', 'LaTeX_бичвэр')

SECTIONS = {
    '01_Диплом': 'Дипломын бичвэр: LaTeX эх (холбоос, засвар шууд `thesis/`-д орно), хамгийн сүүлийн PDF, системийн бүтэц ба UML зургийн PDF (`tools/export_system_diagrams.py`).',
    '02_Семинар': 'Хамгийн сүүлийн семинарын PPT ба яриа.',
    '03_Сургуульд_өгөх': 'Сургуульд өгөх баримт.',
    '04_Унших': 'Өгүүлэл унших Монгол хөтөч (англи эхтэй хамт уншина).',
    '05_Дэвтэр': 'Дэвтрийн асуулт ба сургуулийн гарын авлага.',
    '06_Систем': 'Системийн шалгалт: таны хянаж түгжих асуултын хуудас ба сайжруулалтын тайлан.',
}

KEY_DOCS = [
    ('Ажлын самбарын бүртгэл (хуудас: http://127.0.0.1:8765/work)', 'CORE/workboard.json'),
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

    # 11/16: нэг эх бичвэр, хоёр PDF — багшид үзүүлэх богино ноорог ба бүтэн ажлын ноорог.
    add('01_Диплом', root / 'thesis/main_teacher.pdf', 'Диплом_1_багшид_үзүүлэх.pdf')
    add('01_Диплом', root / 'thesis/main.pdf', 'Диплом_2_бүтэн_ноорог.pdf')
    # 11/27: which files are K (the teacher sees them, the user edits) and which are KS (agent notes).
    add('01_Диплом', root / 'thesis/K-KS-ЗААВАР.mn.md', '00_K_ба_KS_засах_заавар.md')
    # 11/20: найруулгын туршилтын өмнө/дараа хуудас — хэрэглэгч уншаад таалагдаагүй мөрийг буцаалгана.
    add('01_Диплом', _newest(root.glob('reports/Хэллэгийн туршилт *.md')), 'Хэллэгийн_туршилт_өмнө_дараа.md')
    # 11/16: docs/diagrams/*.pdf (11/06-ны хуучин зураг) хуулахгүй — диаграммууд одоо хоёр PDF-ийн дотор.
    seminars = sorted(root.glob('CORE/seminar-*'))
    deck = _newest(p for folder in seminars for p in folder.glob('*.pptx'))
    add('02_Семинар', deck)
    add('02_Семинар', _newest(p for folder in seminars for p in folder.glob('*Яриа*.md')))
    # 11/20: слайдын дүрсээр зурсан диаграмм Canva-д өөрөөр харагдвал оронд нь тавих зураг (сүүлийн семинарынх).
    for source in sorted(deck.parent.glob('Зураг_*.png')) if deck else ():     # the pictures of that same deck
        add('02_Семинар', source)
    for source in sorted(root.glob('data/school-request/*.pdf')):
        add('03_Сургуульд_өгөх', source)
    # 11/15: хэрэглэгч сургуулиас асууж тэмдэглэх асуултын хуудас.
    for source in sorted(root.glob('data/school-request/*.md')):
        add('03_Сургуульд_өгөх', source)
    # 11/16: албанд имэйлээр хавсаргах Word файл (жишээ нь карьерын төв).
    for source in sorted(root.glob('data/school-request/*.docx')):
        add('03_Сургуульд_өгөх', source)
    for source in sorted(root.glob('papers/*hotoch*.md')):
        add('04_Унших', source)
    # 11/16: багшийн зөвлөгөөгөөр хийсэн Монгол эрдэм шинжилгээний хэллэгийн тайлан (дипломын найруулгад баримтална).
    add('04_Унших', root / 'reports/Монгол эрдэм шинжилгээний бичвэрийн хэллэг.md')
    # 11/26: the teacher's question «төстэй системийг туршсан уу» — the full survey and the 8-question comparison.
    add('04_Унших', root / 'reports/Төстэй системүүдийн судалгаа.md')
    add('04_Унших', _newest(root.glob('papers/*similar-systems*.mn.md')), 'Төстэй_систем_8_асуултын_туршилт.mn.md')
    # 11/26: the five-reviewer check of the supervisor draft (plain-Mongolian decision and fixes).
    add('01_Диплом', _newest(root.glob('papers/*teacher-draft-review*/0-шийдвэр-ба-засвар.mn.md')),
        'Нооргийн_5_хянагчийн_шалгалт.mn.md')
    add('05_Дэвтэр', _newest(p for folder in seminars for p in folder.glob('*Дэвтэр*.md')))
    # 11/17: системийн шалгах асуултын хянах хуудас (сургуулийн өгөгдөлтэй тул git-д ордоггүй) ба тайлан.
    add('06_Систем', _newest(root.glob('CORE/eval-review/*хянах*.mn.md')))
    add('06_Систем', _newest(root.glob('papers/*system-upgrade*.mn.md')), 'Системийн_сайжруулалтын_тайлан.mn.md')
    add('06_Систем', _newest(root.glob('papers/*mongolian-morphology-retrieval*.mn.md')), 'Монгол_үгийн_хэлбэр_ба_хайлт.mn.md')
    add('06_Систем', _newest(root.glob('papers/*answer-type-guard*.mn.md')), 'Хариугүй_асуулт_ба_багштай_холбогдох.mn.md')
    add('06_Систем', root / 'reports/Систем яаж ажилладаг.md', '00_Систем_яаж_ажилладаг_бүх_дүрэм.md')
    # 11/17 (round 4): хэрэглэгчийн «намайг яаж автоматжуулах вэ» асуулт ба дагалдах асуултын судалгаа.
    add('06_Систем', root / 'reports/Автомат гогцоо ба дагалдах асуулт.md', 'Автомат_гогцоо_ба_дагалдах_асуулт.md')
    add('06_Систем', _newest(root.glob('papers/*autofix-round*.mn.md')), 'Автомат_засварын_тойрог.mn.md')
    # 11/20: диплом, PPT, 127 систем, багшийн зөвлөгөөний бүтэн шалгалт (самбар /work-ийн дэлгэрэнгүй).
    add('06_Систем', _newest(root.glob('papers/*whole-audit*.mn.md')), 'Бүтэн_шалгалтын_тайлан.mn.md')
    # 11/23: хэрэглэгчийн «RAG дууссан уу, вектор хайлт кодонд бий юу, ер нь яаж хийдэг вэ» асуултын хариу.
    add('06_Систем', _newest(root.glob('papers/*rag-how-it-works*.mn.md')), 'RAG_яаж_ажилладаг.mn.md')
    # 11/23 (2): «бүх даалгаврыг хийсэн үү?» — даалгавар бүрийн тулгалт, дутууг нөхсөн тойрог.
    add('06_Систем', _newest(root.glob('papers/*honest-check*.mn.md')), 'Даалгавар_бүрийн_тулгалт.mn.md')
    # 11/25: «системийн клон хий, зөвхөн чат» ба «хариулт дутуу, богино» — чатын тусдаа хуулбар, бүрэн хариулт.
    add('06_Систем', _newest(root.glob('papers/*chat-copy*.mn.md')), 'Чатын_хуулбар_ба_бүрэн_хариулт.mn.md')
    # 11/25 (2): «хийгээгүй шалгалтуудыг хий, RAG хайлт ба хариултыг сайжруул» — үлдсэн шалгалтын дүн, хуудасны бүтэн
    # хэсгээр хариулах алхам, хайлтын хүрээний дүрмүүд.
    add('06_Систем', _newest(root.glob('papers/*page-sections*.mn.md')), 'Хуудасны_хэсгээр_хариулах.mn.md')
    # 11/25 (3): «эхлээд сургуулийн үндсэн асуулт, багшийн мэдээлэл, өрөөг бүгдийг хий» — бүх багш, өрөө, албаар шалгасан нь.
    add('06_Систем', _newest(root.glob('papers/*basic-questions*.mn.md')), 'Үндсэн_асуултын_шалгалт.mn.md')
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
    # Earlier seminar decks are kept (the user builds each week's deck on the previous ones, 11/11),
    # but out of the way in a «Хуучин» subfolder (11/16: the folder had become a pile of versions).
    # A deck the user edited stays where it is: it is their working copy.
    for relative, recorded in old.items():
        dest = out / relative
        if relative not in new and dest.is_file():
            if relative.startswith(KEEP_OLDER):
                if _stamp(dest) == recorded and dest.parent.name != ARCHIVE:
                    archived = dest.parent / ARCHIVE / dest.name
                    archived.parent.mkdir(exist_ok=True)
                    if not archived.exists():
                        shutil.move(str(dest), str(archived))
                        continue
                new[relative] = recorded
            elif _stamp(dest) == recorded:
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
              '- Ажлын самбар (багшийн зөвлөгөө, энэ долоо хоног, шалгах асуулт): http://127.0.0.1:8765/work',
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
