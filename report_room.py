"""Report room for /reports: the assistant's notes and reports in papers/ as readable pages.

The user (2026-11-23): «a section on 127 that shows your reports, where I can check the resources». Every page
lists the sources it points to — web links, and other notes in papers/ as links — so a claim can be traced. Files are
read live on every request; nothing is written. Reading guides (*hotoch*) stay in /reader.
"""
from __future__ import annotations

import html
from pathlib import Path
import re
import sys
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent
if str(ROOT / 'tools') not in sys.path:
    sys.path.insert(0, str(ROOT / 'tools'))
from build_paper_reader import Renderer  # noqa: E402

PAPERS = 'papers'
# 11/26, the user: «those works … show in 127 … when I read it in VS Code it shows raw text». Besides papers/NN-*.md:
# the research reports in reports/*.md (route /reports/r/<name>) and the Markdown files of a papers/NN-*/ folder (route
# /reports/<folder> opens its «0-*.md» summary, /reports/<folder>/<file> any other .md in it).
REPORTS = 'reports'
NAME = re.compile(r'\d{2}-[0-9A-Za-z._-]+')
REPORT_NAME = re.compile(r'[^/\\:*?"<>|]{1,120}')
DATE = re.compile(r'(20\d{2})(\d{2})(\d{2})')
GUIDE_CODE = re.compile(r'\b([A-Z]{3}\d{2})\b')
LINK = re.compile(r'\[([^\]]+)\]\(([^)\s]+)\)')
CODE_PATH = re.compile(r'`((?:\.\./)?papers/([0-9][0-9A-Za-z._*-]*?)(?:\.md)?)`')
URL = re.compile(r'https?://[^\s)<>«»"`]+')


def report_files(root):
    """papers/NN-*.md written as reports (guides excluded), newest number first."""
    folder = Path(root) / PAPERS
    found = [path for path in folder.glob('*.md')
             if NAME.fullmatch(path.name[:-3]) and 'hotoch' not in path.name and path.is_file()]
    return sorted(found, key=lambda path: (path.name[:2], path.name), reverse=True)


def research_reports(root):
    """reports/*.md (the deep-research reports and other plain reports), newest first."""
    folder = Path(root) / REPORTS
    found = [path for path in folder.glob('*.md') if path.is_file()] if folder.is_dir() else []
    return sorted(found, key=lambda path: path.stat().st_mtime, reverse=True)


def report_folders(root):
    """papers/NN-*/ folders that hold a «0-*.md» summary for the reader, newest number first."""
    folder = Path(root) / PAPERS
    found = [path for path in folder.iterdir()
             if path.is_dir() and NAME.fullmatch(path.name) and _summary_file(path) is not None] if folder.is_dir() else []
    return sorted(found, key=lambda path: path.name, reverse=True)


def _summary_file(folder):
    return next(iter(sorted(folder.glob('0-*.md'))), None)


def report_path(root, name):
    """The file for a /reports/<name> route, or KeyError. <name> is a papers/ file name without «.md», a papers/NN-*/
    folder (its «0-*.md»), «<folder>/<file>» for another .md in that folder, or «r/<name>» for reports/<name>.md."""
    name = name or ''
    if name.startswith('r/'):
        stem = name[2:]
        folder = (Path(root) / REPORTS).resolve()
        if not REPORT_NAME.fullmatch(stem) or stem.startswith('.'):
            raise KeyError(name)
        path = (folder / (stem + '.md')).resolve()
        if path.parent != folder or not path.is_file():
            raise KeyError(name)
        return path
    papers = (Path(root) / PAPERS).resolve()
    head, _, tail = name.partition('/')
    if not NAME.fullmatch(head) or '..' in name:
        raise KeyError(name)
    if tail:
        if not REPORT_NAME.fullmatch(tail) or tail.startswith('.'):
            raise KeyError(name)
        path = (papers / head / (tail + '.md')).resolve()
        if path.parent != (papers / head).resolve() or not path.is_file():
            raise KeyError(name)
        return path
    path = (papers / (name + '.md')).resolve()
    if path.parent == papers and path.is_file() and 'hotoch' not in path.name:
        return path
    folder = (papers / name).resolve()
    summary = _summary_file(folder) if folder.parent == papers and folder.is_dir() else None
    if summary is None:
        raise KeyError(name)
    return summary


def route_of(root, path):
    """The /reports route of a file report_path accepts, or None."""
    path, root = Path(path).resolve(), Path(root).resolve()
    papers, reports = root / PAPERS, root / REPORTS
    if path.parent == reports and path.suffix == '.md':
        return '/reports/r/' + quote(path.stem)
    if path.parent == papers and path.suffix == '.md':
        return '/reports/' + path.name[:-3]
    if path.parent.parent == papers and path.suffix == '.md':
        if _summary_file(path.parent) == path:
            return '/reports/' + path.parent.name
        return '/reports/' + path.parent.name + '/' + quote(path.stem)
    return None


def _target(root, target, names):
    """A link inside a note: web links stay; another note becomes /reports/…, a guide /reader/…, other files text."""
    if re.match(r'https?://', target):
        return target
    name = target.split('#')[0].rsplit('/', 1)[-1]
    if 'hotoch' in name:
        code = GUIDE_CODE.search(name)
        return f'/reader/{code.group(1)}' if code else None
    if name.endswith('.md') and name[:-3] in names:
        return '/reports/' + name[:-3]
    return None


def _resolve_code_path(match, names):
    """`papers/45-…md` or a unique `papers/44-*` pattern in back-ticks becomes a link to that note."""
    stem = match.group(2)
    if '*' in stem:
        prefix = stem.split('*', 1)[0]
        hits = [name for name in names if name.startswith(prefix)]
        stem = hits[0] if len(hits) == 1 else None
    else:
        stem = stem[:-3] if stem.endswith('.mn') and stem not in names and stem[:-3] in names else stem
        stem = stem if stem in names else (stem + '.mn' if stem + '.mn' in names else None)
    # The link names the file itself: a «*» pattern would also read as italics.
    return f'[papers/{stem}.md](/reports/{stem})' if stem else match.group(0)


def linked_markdown(root, markdown, names=None):
    """Rewrite links so they open inside 127; relative links to files outside papers/ become plain text."""
    names = names if names is not None else {path.name[:-3] for path in report_files(root)}

    def link(match):
        target = _target(root, match.group(2), names)
        return f'[{match.group(1)}]({target})' if target else match.group(1)

    markdown = LINK.sub(link, markdown)
    return CODE_PATH.sub(lambda match: _resolve_code_path(match, names), markdown)


def sources(markdown):
    """Web addresses and in-project notes a page points to, in order of first mention."""
    web, notes = {}, {}
    for text, target in LINK.findall(markdown):
        if target.startswith('/reports/') or target.startswith('/reader/'):
            notes.setdefault(target, text)
        elif target.startswith('http'):
            web.setdefault(target.rstrip('.,;'), text)
    for url in URL.findall(LINK.sub('', markdown)):
        web.setdefault(url.rstrip('.,;'), '')
    return web, notes


def render_markdown(lines, renderer):
    """The guides' markdown subset plus fenced code, quotes and «####» headings."""
    out, chunk, index = [], [], 0

    def flush():
        if chunk:
            out.append(renderer.blocks(chunk))
            chunk.clear()

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if stripped.startswith('```'):
            flush()
            block, index = [], index + 1
            while index < len(lines) and not lines[index].strip().startswith('```'):
                block.append(lines[index])
                index += 1
            out.append('<pre><code>' + html.escape('\n'.join(block)) + '</code></pre>')
        elif stripped.startswith('> '):
            flush()
            block = []
            while index < len(lines) and lines[index].strip().startswith('>'):
                block.append(lines[index].strip()[1:].strip())
                index += 1
            out.append('<blockquote>' + renderer.blocks(block) + '</blockquote>')
            continue
        elif stripped.startswith('#### '):
            flush()
            out.append(f'<h4>{renderer.inline(stripped[5:])}</h4>')
        else:
            chunk.append(line)
        index += 1
    flush()
    return '\n'.join(out)


def split_page(markdown):
    """(title, lines before the first «## », [(heading, lines)])."""
    lines = markdown.splitlines()
    title = lines[0].removeprefix('# ').strip() if lines and lines[0].startswith('# ') else ''
    head, sections, current = [], [], None
    for line in lines[1:] if title else lines:
        if line.startswith('## '):
            current = (line[3:].strip(), [])
            sections.append(current)
        elif current is None:
            head.append(line)
        else:
            current[1].append(line)
    return title, head, sections


def _short(url):
    """«anlp.jp/…/E5-3.pdf» for a bare address without link text."""
    parts = url.split('/', 3)
    rest = parts[3].rstrip('/') if len(parts) > 3 else ''
    tail = rest.rsplit('/', 1)[-1]
    return parts[2] + ('/' + rest if len(rest) <= 40 else '/…/' + tail[-40:])


def _date(name):
    match = DATE.search(name)
    return f'{match[1]}.{match[2]}.{match[3]}' if match else ''


def _summary(lines):
    for line in lines:
        text = line.strip()
        if text and not text.startswith(('#', '|', '---', '```')):
            text = re.sub(r'[*`]', '', LINK.sub(r'\1', text))
            return text if len(text) <= 220 else text[:217].rstrip() + '…'
    return ''


def _row(root, path, route, label, renderer, names):
    markdown = path.read_text(encoding='utf-8')
    title, head, sections = split_page(markdown)
    web, notes = sources(linked_markdown(root, markdown, names))
    summary = _summary(head or (sections[0][1] if sections else []))
    return (f'<li><a class="title" href="{html.escape(route)}">{renderer.inline(title or path.name)}</a>'
            f'<span class="meta">{html.escape(label)} · вэб эх сурвалж {len(web)}'
            f' · төслийн тэмдэглэл {len(notes)}</span><p>{html.escape(summary)}</p></li>')


def reports_index(root):
    renderer, files = Renderer(), report_files(root)
    names = {path.name[:-3] for path in files}
    research = [_row(root, path, route_of(root, path), 'Судалгааны тайлан · ' + _mtime(path), renderer, names)
                for path in research_reports(root)]
    entries = [(path.name, _row(root, path, '/reports/' + path.name[:-3],
                                path.name[:2] + ' · ' + _date(path.name), renderer, names)) for path in files]
    entries += [(folder.name, _row(root, _summary_file(folder), '/reports/' + folder.name,
                                   folder.name[:2] + ' · ' + _date(folder.name) + ' · хавтас', renderer, names))
                for folder in report_folders(root)]
    rows = [row for _, row in sorted(entries, key=lambda entry: (entry[0][:2], entry[0]), reverse=True)]
    body = ''
    if research:
        body += f'<h2 class="group">Судалгааны тайлан</h2><ol class="reports">{"".join(research)}</ol>'
    body += ((f'<h2 class="group">Тэмдэглэл</h2>' if research else '') + f'<ol class="reports">{"".join(rows)}</ol>'
             if rows else '<p class="empty">Тайлан олдсонгүй.</p>')
    return PAGE.replace('@@TITLE@@', 'Тайлан ба эх сурвалж').replace('@@BODY@@', (
        '<p class="lead">Миний (AI туслахын) бичсэн судалгааны тэмдэглэл, тайлан. Хуудас бүрийн баруун талд тэр '
        'тайлангийн иш татсан эх сурвалж бий — дарж шалгана уу. Өгүүллийн Монгол хөтөч <a href="/reader">Өгүүлэл '
        'унших</a> хэсэгт.</p>' + body))


def _mtime(path):
    import datetime
    return datetime.datetime.fromtimestamp(path.stat().st_mtime).strftime('%Y.%m.%d')


def report_page(root, name):
    path = report_path(root, name)
    names = {item.name[:-3] for item in report_files(root)}
    markdown = linked_markdown(root, path.read_text(encoding='utf-8'), names)
    renderer = Renderer()
    title, head, sections = split_page(markdown)
    parts = [render_markdown(head, renderer)]
    for index, (heading, lines) in enumerate(sections):
        parts.append(f'<section id="s{index}"><h2>{renderer.inline(heading)}</h2>{render_markdown(lines, renderer)}</section>')
    web, notes = sources(markdown)
    web_items = ''.join(
        f'<li><a href="{html.escape(url)}" target="_blank" rel="noopener">{html.escape(text or _short(url))}</a>'
        f'<small>{html.escape(url.split("/")[2])}</small></li>' for url, text in web.items())
    note_items = ''.join(f'<li><a href="{html.escape(target)}">{html.escape(text)}</a></li>'
                         for target, text in notes.items())
    siblings = ''
    if path.parent.parent.resolve() == (Path(root) / PAPERS).resolve():
        # A papers/NN-*/ folder: its other Markdown files open here too (the full English letter, the reports).
        others = [item for item in sorted(path.parent.glob('*.md')) if item != path]
        siblings = (f'<h3>Энэ хавтасны бусад файл ({len(others)})</h3><ol>'
                    + ''.join(f'<li><a href="{html.escape(route_of(root, item))}">{html.escape(item.name)}</a></li>'
                              for item in others) + '</ol>') if others else ''
    relative = path.resolve().relative_to(Path(root).resolve()).as_posix()
    side = ('<aside><h2>Эх сурвалж</h2>'
            + (f'<h3>Вэб ({len(web)})</h3><ol>{web_items}</ol>' if web else '<p>Вэб холбоос алга.</p>')
            + (f'<h3>Төслийн бусад тэмдэглэл ({len(notes)})</h3><ol>{note_items}</ol>' if notes else '')
            + siblings + f'<p class="file">Эх файл: <code>{html.escape(relative)}</code></p></aside>')
    body = (f'<p class="back"><a href="/reports">← Бүх тайлан</a></p><div class="layout"><article>'
            f'<h1>{renderer.inline(title or path.name)}</h1>{"".join(parts)}</article>{side}</div>')
    return PAGE.replace('@@TITLE@@', html.escape(re.sub(r'[*`]', '', title or path.name))).replace('@@BODY@@', body)


PAGE = '''<!doctype html>
<html lang="mn"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>@@TITLE@@ · THesisS</title>
<style>
:root{--ink:#14302b;--muted:#5d6b64;--line:#dce3d8;--cream:#f7f8f2;--night:#0f1d2e;--link:#1f5f8b;font-family:"Segoe UI",Arial,sans-serif;color:var(--ink);background:var(--cream)}
body{margin:0}.top{background:var(--night);color:#fff;padding:14px 28px;display:flex;gap:18px;align-items:center;flex-wrap:wrap}
.top h1{margin:0;font-size:18px;flex:1}.top a{color:#ffd76a;font-size:13px;text-decoration:none}
main{max-width:1180px;margin:0 auto;padding:22px 22px 70px}.lead{color:var(--muted);font-size:15px;line-height:1.6;max-width:75ch}
a{color:var(--link)}.reports{list-style:none;padding:0;margin:0;display:grid;gap:10px}
.reports li{background:#fff;border:1px solid var(--line);border-radius:12px;padding:14px 18px}
.reports .title{font-weight:700;font-size:16px;text-decoration:none}.reports .meta{display:block;color:var(--muted);font-size:12px;margin:4px 0}
.reports p{margin:4px 0 0;font-size:14px;line-height:1.55;color:#33443e}
.layout{display:grid;grid-template-columns:minmax(0,1fr) 320px;gap:26px;align-items:start}
article{background:#fff;border:1px solid var(--line);border-radius:14px;padding:22px 30px;font-size:16.5px;line-height:1.65}
article h1{font-size:23px;line-height:1.35;margin:0 0 14px}article h2{font-size:19px;margin:26px 0 8px;padding-top:10px;border-top:1px solid var(--line)}
article h3{font-size:16.5px;margin:18px 0 6px}article p,article li{max-width:78ch}article li{margin:3px 0}
article table{border-collapse:collapse;font-size:14px;margin:10px 0}.table-wrap{overflow-x:auto}
article th,article td{border:1px solid var(--line);padding:6px 9px;text-align:left;vertical-align:top}article th{background:#f1f4ec}
pre{background:#f3f5f1;border:1px solid var(--line);border-radius:8px;padding:10px 12px;overflow-x:auto;font-size:13px}
code{font-family:Consolas,monospace;font-size:.92em;background:#f1f4ec;padding:1px 4px;border-radius:4px}
blockquote{margin:10px 0;padding:6px 16px;border-left:4px solid #c9d6c3;background:#fafbf7}
aside{position:sticky;top:14px;background:#fff;border:1px solid var(--line);border-radius:14px;padding:16px 18px;font-size:13.5px;max-height:calc(100vh - 40px);overflow:auto}
aside h2{font-size:16px;margin:0 0 8px}aside h3{font-size:13px;color:var(--muted);margin:14px 0 6px;text-transform:uppercase;letter-spacing:.03em}
aside ol{margin:0;padding-left:20px}aside li{margin:6px 0;line-height:1.4;word-break:break-word}aside small{display:block;color:var(--muted)}
.file{color:var(--muted);margin-top:14px}.back{margin:0 0 12px}.empty{color:var(--muted)}
.group{font-size:17px;margin:22px 0 10px}
@media(max-width:900px){.layout{grid-template-columns:1fr}aside{position:static;max-height:none}}
@media print{.top,.back,aside{display:none}article{border:0;padding:0}}
</style></head>
<body><div class="top"><h1>@@TITLE@@</h1><a href="/seminar">Семинар</a><a href="/reports">Тайлан</a><a href="/reader">Өгүүлэл унших</a><a href="/work">Ажлын самбар</a><a href="/">Чат</a></div>
<main>@@BODY@@</main></body></html>
'''
