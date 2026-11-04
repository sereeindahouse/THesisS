"""Өгүүллийн Монгол хөтчөөс (markdown) нэг файлтай HTML уншигч үүсгэнэ.

Зөвхөн манай хөтчийн текстийг харуулна; англи өгүүллийг хуулахгүй, холбоосоор нээнэ.
Сүлжээ, LLM, гаднын сан ашиглахгүй. Хэрэглэгчийн хариулт/тэмдэглэл зөвхөн хөтчийн
localStorage-д үлдэнэ; энэ нь «уншсан» гэсэн бүртгэл биш.

    .venv/Scripts/python.exe tools/build_paper_reader.py
"""
from __future__ import annotations

import argparse
import html
import json
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / 'papers/20-RAG01-delgerengui-hotoch-20261104.mn.md'
OUTPUT = ROOT / 'papers/reader/RAG01-reader.html'

GLOSSARY_TITLE = 'Гол нэр томьёо'
LINKS_TITLE = 'Манай системтэй холбох'
QUESTIONS_TITLE = 'Өөрийгөө шалгах асуулт'
NOTES_TITLE = 'Уншсаны тэмдэглэл'
INTRO_TITLE = 'Энэ файлыг яаж ашиглах вэ'

LIST_ITEM = re.compile(r'^\s*(- |\d+\. )')
LATEX = [(r'\approx', '≈'), (r'\sum', '∑'), (r'\prod', '∏'), (r'\in', '∈'), (r'\eta', 'η'),
         (r'\theta', 'θ'), (r'\;', ' '), (r'\,', ' ')]


def slug(text, index):
    words = re.findall(r'[0-9a-zа-яөүё]+', text.lower())
    return f's{index}-' + '-'.join(words[:4])


def split_sections(markdown):
    """Return (title, meta lines, [(heading, body lines)]) split on '## ' headings."""
    lines = markdown.splitlines()
    title = lines[0].removeprefix('# ').strip() if lines and lines[0].startswith('# ') else 'Хөтөч'
    meta, sections, current = [], [], None
    for line in lines[1:]:
        if line.startswith('## '):
            current = (line[3:].strip(), [])
            sections.append(current)
        elif current is None:
            if line.strip():
                meta.append(line)
        else:
            current[1].append(line)
    return title, meta, sections


def table_rows(lines):
    rows = [[cell.strip() for cell in line.strip().strip('|').split('|')]
            for line in lines if line.strip().startswith('|')]
    return [row for row in rows if not all(re.fullmatch(r':?-+:?', cell) for cell in row)]


def latex(source):
    text = html.escape(source.strip())
    text = re.sub(r'\\text\{([^}]*)\}', r'\1', text)
    for command, symbol in LATEX:
        text = text.replace(html.escape(command), symbol)
    for _ in range(2):
        text = re.sub(r'_\{([^{}]*)\}', r'<sub>\1</sub>', text)
        text = re.sub(r'\^\{([^{}]*)\}', r'<sup>\1</sup>', text)
    text = re.sub(r'_([A-Za-z0-9ηθ])', r'<sub>\1</sub>', text)
    return text


class Renderer:
    """Small markdown subset used by our guides: h3, lists, tables, $$ math, paragraphs."""

    def __init__(self, glossary=None, link_base=''):
        self.glossary, self.link_base = glossary or {}, link_base

    def href(self, target):
        # Web links stay as they are; guide-relative files are re-based to the reader's folder.
        target = html.unescape(target)
        if re.match(r'https?://', target):
            return html.escape(target)
        if ':' in target.split('/')[0]:
            return '#'
        return html.escape(self.link_base + target)

    def term(self, text):
        tip = self.glossary.get(re.sub(r'\s*\(.*\)$', '', text).lower())
        if not tip:
            return f'<strong>{text}</strong>'
        return f'<strong class="term" tabindex="0" data-tip="{html.escape(tip)}">{text}</strong>'

    def inline(self, text):
        out = html.escape(text, quote=False)
        out = re.sub(r'`([^`]+)`', r'<code>\1</code>', out)
        out = re.sub(r'\[([^\]]+)\]\(([^)\s]+)\)',
                     lambda m: f'<a href="{self.href(m.group(2))}" target="_blank" rel="noopener">{m.group(1)}</a>', out)
        out = re.sub(r'\*\*(.+?)\*\*', lambda m: self.term(m.group(1)), out)
        return re.sub(r'(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])', r'<em>\1</em>', out)

    def blocks(self, lines):
        out, index = [], 0
        while index < len(lines):
            line = lines[index]
            stripped = line.strip()
            if not stripped or stripped == '---':
                index += 1
            elif stripped.startswith('### '):
                out.append(f'<h3>{self.inline(stripped[4:])}</h3>')
                index += 1
            elif stripped.startswith('$$'):
                block = [stripped]
                while not (len(''.join(block)) > 2 and block[-1].endswith('$$')) and index + 1 < len(lines):
                    index += 1
                    block.append(lines[index].strip())
                out.append(f'<div class="math">{latex(" ".join(block).strip("$"))}</div>')
                index += 1
            elif stripped.startswith('|'):
                block = []
                while index < len(lines) and lines[index].strip().startswith('|'):
                    block.append(lines[index])
                    index += 1
                rows = table_rows(block)
                head = ''.join(f'<th>{self.inline(cell)}</th>' for cell in rows[0])
                body = ''.join('<tr>' + ''.join(f'<td>{self.inline(cell)}</td>' for cell in row) + '</tr>'
                               for row in rows[1:])
                out.append(f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>')
            elif LIST_ITEM.match(line):
                block = []
                while index < len(lines) and LIST_ITEM.match(lines[index]):
                    block.append(lines[index])
                    index += 1
                out.append(self.items(block))
            else:
                out.append(f'<p>{self.inline(stripped)}</p>')
                index += 1
        return '\n'.join(out)

    def items(self, block):
        """Two-space indentation nests a list inside the previous item."""
        out, stack = [], []
        for line in block:
            level = (len(line) - len(line.lstrip())) // 2
            tag = 'ol' if re.match(r'\s*\d+\. ', line) else 'ul'
            if level >= len(stack):
                for _ in range(level - len(stack) + 1):
                    out.append(f'<{tag}>')
                    stack.append(tag)
            else:
                while len(stack) > level + 1:
                    out.append(f'</li></{stack.pop()}>')
                out.append('</li>')
            out.append(f'<li>{self.inline(LIST_ITEM.sub("", line))}')
        while stack:
            out.append(f'</li></{stack.pop()}>')
        return ''.join(out)


def build(markdown, *, pdf_url, abs_url, link_base=''):
    title, meta, sections = split_sections(markdown)
    find = lambda needle: next((body for heading, body in sections if needle in heading), [])
    glossary = {}
    for row in table_rows(find(GLOSSARY_TITLE))[1:]:
        if len(row) >= 3:
            mongolian = row[1].replace('**', '')
            glossary[re.sub(r'\s*\(.*\)$', '', mongolian).lower()] = f'{row[0]} — {row[2]}'
    plain, rich = Renderer(link_base=link_base), Renderer(glossary, link_base)
    links = [row for row in table_rows(find(LINKS_TITLE))[1:] if len(row) >= 3]
    link_notes = [line.strip() for line in find(LINKS_TITLE)
                  if line.strip() and line.strip() != '---' and not line.strip().startswith('|')]
    questions = [LIST_ITEM.sub('', line) for line in find(QUESTIONS_TITLE) if re.match(r'\s*\d+\. ', line)]
    prompts = [LIST_ITEM.sub('', line).rstrip(':') for line in find(NOTES_TITLE) if line.strip().startswith('- ')]

    reading = [(heading, body) for heading, body in sections
               if not any(key in heading for key in (INTRO_TITLE, LINKS_TITLE, QUESTIONS_TITLE, NOTES_TITLE))]
    nav, articles = [], []
    for index, (heading, body) in enumerate(reading, 1):
        starred = '⭐' in heading
        clean = heading.replace('⭐', '').strip()
        anchor, kind = slug(clean, index), 'starred' if starred else 'optional'
        star = '<span aria-hidden="true">★</span> ' if starred else ''
        nav.append(f'<li><a href="#{anchor}" class="{kind}">{star}{plain.inline(clean)}</a></li>')
        articles.append(f'<section id="{anchor}" class="chapter {kind}"><header>'
                        f'<span class="chapter-tag">{"Заавал унших" if starred else "Сонголтоор"}</span>'
                        f'<h2>{plain.inline(clean)}</h2><a class="source-link" href="{html.escape(pdf_url)}" '
                        f'target="_blank" rel="noopener">Англи эхээс унших ↗</a></header>{rich.blocks(body)}</section>')

    link_rows = ''.join(
        f'<li><button type="button" class="link-row" aria-expanded="false">'
        f'<span class="node paper">{plain.inline(row[0])}</span><span class="wire" aria-hidden="true"></span>'
        f'<span class="node ours">{plain.inline(row[1])}</span></button>'
        f'<p class="link-note" hidden>{rich.inline(row[2])}</p></li>' for row in links)
    question_cards = ''.join(
        f'<li><p>{rich.inline(text)}</p><textarea data-store="q{number}" rows="2" '
        f'placeholder="Номгүйгээр өөрийн үгээр хариул…" aria-label="{number}-р асуултын миний хариулт"></textarea></li>'
        for number, text in enumerate(questions, 1))
    note_fields = ''.join(f'<label>{plain.inline(prompt)}<textarea data-store="note{number}" rows="2"></textarea></label>'
                          for number, prompt in enumerate(prompts, 1))
    store_key = 'paper-reader:' + re.sub(r'[^A-Za-z0-9]+', '-', abs_url).strip('-')
    return PAGE.format(
        title=plain.inline(title), meta=''.join(f'<p>{plain.inline(line)}</p>' for line in meta),
        pdf=html.escape(pdf_url), abs=html.escape(abs_url), intro=rich.blocks(find(INTRO_TITLE)),
        nav=''.join(nav), articles=''.join(articles), links=link_rows,
        link_notes=''.join(f'<p class="links-limit">{rich.inline(note)}</p>' for note in link_notes),
        questions=question_cards, notes=note_fields, terms=len(glossary), store=json.dumps(store_key))


PAGE = '''<!doctype html>
<html lang="mn">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
:root{{--ink:#163d37;--muted:#66736c;--teal:#164e48;--cream:#f7f8f2;--line:#dce3d8;--gold:#ad8c47;--night:#0f1d2e;font-family:"Segoe UI",Arial,sans-serif;color:var(--ink);background:var(--cream)}}
*{{box-sizing:border-box}}body{{margin:0}}a{{color:#2f6b5d}}
.top{{position:sticky;top:0;z-index:5;background:var(--night);color:#dce8f5;padding:14px 28px;display:flex;gap:18px;align-items:center;flex-wrap:wrap}}
.top h1{{font-size:17px;margin:0;flex:1;min-width:240px;color:#fff}}.top a{{color:#ffd76a;font-size:13px;text-decoration:none}}
.progress{{position:absolute;left:0;bottom:0;height:3px;background:#ffd76a;width:0}}
.top label{{font-size:12px;color:#9fb3c8;display:flex;gap:6px;align-items:center}}
.layout{{display:grid;grid-template-columns:240px minmax(0,760px) 340px;gap:28px;max-width:1440px;margin:0 auto;padding:24px 28px 80px}}
nav{{position:sticky;top:72px;align-self:start;max-height:calc(100vh - 90px);overflow:auto}}
nav ol{{list-style:none;margin:0;padding:0}}nav li a{{display:block;padding:7px 10px;border-radius:7px;font-size:13px;color:var(--muted);text-decoration:none;border-left:3px solid transparent}}
nav li a.starred{{color:var(--ink);font-weight:600}}nav li a.starred span{{color:var(--gold)}}nav li a.active{{background:#e5ece0;border-left-color:var(--teal);color:var(--teal)}}
.nav-title{{font-size:11px;letter-spacing:.08em;color:var(--muted);margin:0 0 8px 10px}}
main{{min-width:0}}.intro,.chapter,.panel{{background:#fff;border:1px solid var(--line);border-radius:12px;padding:22px 26px;margin-bottom:18px}}
.intro{{background:#fbf8ef;border-color:#eadfbf}}.intro p,.intro li{{font-size:14px}}.meta p{{margin:4px 0;font-size:13px;color:var(--muted)}}
.chapter header{{display:flex;flex-wrap:wrap;align-items:baseline;gap:10px;margin-bottom:6px}}.chapter h2{{margin:0;font-size:22px;flex:1 1 100%}}
.chapter-tag{{font-size:11px;padding:3px 9px;border-radius:20px;background:#eef3ea;color:var(--muted)}}.starred .chapter-tag{{background:#fbf1cc;color:#7b5d17}}
.source-link{{font-size:12px;margin-left:auto}}.chapter p,.chapter li{{font-size:15.5px;line-height:1.7}}.chapter h3{{font-size:17px;margin:22px 0 6px}}
.only-starred .optional{{display:none}}
.math{{font-family:"Cambria Math","Times New Roman",serif;font-size:19px;background:#f4f7f1;border-radius:9px;padding:14px 18px;margin:12px 0;overflow-x:auto;white-space:nowrap}}
.table-wrap{{overflow-x:auto;margin:12px 0}}table{{border-collapse:collapse;font-size:14px;width:100%}}th,td{{border:1px solid var(--line);padding:7px 10px;text-align:left;vertical-align:top}}th{{background:#f1f5ee}}
code{{background:#f1f5ee;padding:1px 5px;border-radius:4px;font-size:.9em}}
.term{{border-bottom:2px dotted var(--gold);cursor:help;position:relative}}
.term:hover::after,.term:focus::after{{content:attr(data-tip);position:absolute;left:0;top:calc(100% + 6px);z-index:9;width:min(320px,80vw);background:var(--night);color:#e7eef7;font-weight:400;font-size:13px;line-height:1.5;padding:10px 12px;border-radius:8px;box-shadow:0 8px 24px #0004}}
aside{{position:sticky;top:72px;align-self:start;max-height:calc(100vh - 90px);overflow:auto}}
.panel h2{{font-size:15px;margin:0 0 4px}}.panel>p{{font-size:12px;color:var(--muted);margin:0 0 12px}}
.links{{list-style:none;margin:0;padding:0;display:grid;gap:10px}}
.link-row{{display:grid;grid-template-columns:1fr 26px 1fr;align-items:center;width:100%;border:0;background:none;padding:0;text-align:left;cursor:pointer;font:inherit;color:inherit}}
.node{{font-size:12px;line-height:1.4;padding:8px 9px;border-radius:9px;min-height:100%}}.node.paper{{background:#14304a;color:#dce8f5}}.node.ours{{background:#e3f1e6;color:#1d4a3c}}
.node .term{{border-bottom-color:#ffd76a}}.wire{{height:2px;background:linear-gradient(90deg,#14304a,#7fbf9a);position:relative}}.wire::after{{content:"";position:absolute;right:-1px;top:-4px;border:5px solid transparent;border-left-color:#7fbf9a}}
.link-row[aria-expanded=true] .node{{outline:2px solid var(--gold)}}.link-note{{font-size:13px;line-height:1.55;background:#fbf8ef;border-radius:8px;padding:9px 11px;margin:6px 0 0}}
.links-limit{{font-size:12px;color:var(--muted);margin:12px 0 0}}
.quiz ol{{padding-left:20px;margin:0;display:grid;gap:12px}}.quiz li p{{margin:0 0 6px;font-size:14.5px}}
textarea{{width:100%;font:inherit;font-size:13px;border:1px solid var(--line);border-radius:8px;padding:8px;resize:vertical;background:#fcfdfb}}
.notes label{{display:block;font-size:13px;margin-bottom:10px}}.local{{font-size:12px;color:var(--muted)}}
@media(max-width:1180px){{.layout{{grid-template-columns:200px minmax(0,1fr)}}aside{{grid-column:1/-1;position:static;max-height:none}}}}
@media(max-width:760px){{.layout{{grid-template-columns:1fr;padding:16px}}nav{{position:static;max-height:none}}.top{{padding:12px 16px}}}}
@media print{{.top,nav,aside{{display:none}}.layout{{display:block}}}}
</style>
</head>
<body>
<div class="top"><h1>{title}</h1><a href="{abs}" target="_blank" rel="noopener">arXiv ↗</a><a href="{pdf}" target="_blank" rel="noopener">Англи PDF ↗</a><label><input type="checkbox" id="onlyStarred"> Зөвхөн ★ хэсэг</label><div class="progress" id="progress"></div></div>
<div class="layout">
<nav aria-label="Хэсгүүд"><p class="nav-title">ХЭСГҮҮД · ★ заавал унших</p><ol id="toc">{nav}</ol></nav>
<main id="reader">
<section class="intro"><div class="meta">{meta}</div>{intro}<p class="local">Тасархай доогуур зураастай үг дээр хулгана аваачвал ({terms} нэр томьёо) тайлбар гарна.</p></section>
{articles}
</main>
<aside>
<section class="panel"><h2>Өгүүлэл ↔ Манай систем</h2><p>Мөрийг дарвал дипломд юу гэж бичиж болохыг харуулна.</p><ol class="links">{links}</ol>{link_notes}</section>
<section class="panel quiz"><h2>Өөрийгөө шалгах</h2><p>Номгүйгээр хариулаад дараа нь хэсгээ дахин уншиж тулга.</p><ol>{questions}</ol></section>
<section class="panel notes"><h2>Миний тэмдэглэл</h2>{notes}<p class="local">Зөвхөн энэ хөтөчид хадгалагдана. Төлөвлөгөөнд «уншсан» гэж тэмдэглэхгүй.</p></section>
</aside>
</div>
<script>
'use strict';
(() => {{
  const key={store},chapters=[...document.querySelectorAll('.chapter')],links=new Map([...document.querySelectorAll('#toc a')].map(a=>[a.getAttribute('href').slice(1),a]));
  let saved={{}};try{{saved=JSON.parse(localStorage.getItem(key)||'{{}}');}}catch{{saved={{}};}}
  document.querySelectorAll('textarea[data-store]').forEach(area=>{{area.value=saved[area.dataset.store]||'';area.addEventListener('input',()=>{{saved[area.dataset.store]=area.value;try{{localStorage.setItem(key,JSON.stringify(saved));}}catch{{}}}});}});
  document.querySelectorAll('.link-row').forEach(button=>button.addEventListener('click',()=>{{const open=button.getAttribute('aria-expanded')!=='true';button.setAttribute('aria-expanded',String(open));button.nextElementSibling.hidden=!open;}}));
  const only=document.getElementById('onlyStarred');only.addEventListener('change',()=>{{document.getElementById('reader').classList.toggle('only-starred',only.checked);document.getElementById('toc').querySelectorAll('a.optional').forEach(a=>a.parentElement.hidden=only.checked);}});
  const observer=new IntersectionObserver(entries=>entries.forEach(entry=>{{if(entry.isIntersecting){{links.forEach(a=>a.classList.remove('active'));links.get(entry.target.id)?.classList.add('active');}}}}),{{rootMargin:'-20% 0px -70% 0px'}});
  chapters.forEach(chapter=>observer.observe(chapter));
  const bar=document.getElementById('progress');addEventListener('scroll',()=>{{const max=document.documentElement.scrollHeight-innerHeight;bar.style.width=(max>0?Math.min(100,scrollY/max*100):0)+'%';}},{{passive:true}});
}})();
</script>
</body>
</html>
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('guide', nargs='?', type=Path, default=GUIDE)
    parser.add_argument('--out', type=Path, default=OUTPUT)
    parser.add_argument('--pdf', default='https://arxiv.org/pdf/2005.11401')
    parser.add_argument('--abs', default='https://arxiv.org/abs/2005.11401')
    args = parser.parse_args()
    link_base = Path(os.path.relpath(args.guide.resolve().parent, args.out.resolve().parent)).as_posix() + '/'
    page = build(args.guide.read_text(encoding='utf-8'), pdf_url=args.pdf, abs_url=args.abs, link_base=link_base)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(page, encoding='utf-8')
    print(json.dumps({'output': args.out.relative_to(ROOT).as_posix() if args.out.is_relative_to(ROOT) else str(args.out),
                      'bytes': len(page.encode('utf-8'))}, ensure_ascii=False))


if __name__ == '__main__':
    main()
