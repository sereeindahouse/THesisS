"""Seminar room for /seminar: the weekly seminar's speech, the teacher questions and the notebook page.

The user (2026-11-23): the speech and notebook files open as raw text in VS Code — show them on 127 in the most
useful way. The layout follows the quick research brief papers/53-seminar-view-research-20261123.mn.md: each slide's
picture beside its part of the speech in large type, a time budget per part with a quiet over-budget mark, rehearsal
aloud, the teacher questions as cards with the answer hidden (self-testing), and the notebook as a printable page.

Read live from CORE/seminar-YYYY-MM-DD/ (local only, not in git): the newest deck (*.pptx), its slide pictures from
tools/nmct_slides/render_slides.py (runtime/slide-render/<deck>/slide-NN.png), the newest *Яриа*.md and *Дэвтэр*.md.
Nothing is written; card marks stay in the browser.
"""
from __future__ import annotations

import html
from pathlib import Path
import re

from report_room import Renderer, linked_markdown, render_markdown, split_page

FOLDER = re.compile(r'seminar-\d{4}-\d{2}-\d{2}')
PART = re.compile(r'^\*\*(\d+)(?:\s*[–-]\s*(\d+))?\.\s*(.+?)\s*\((\d+)\s*сек\)\*\*\s*$')
QUESTION = re.compile(r'^- \*\*(.+?)\*\*\s*(?:[—–-]\s*)?(.*)$')
WORD = re.compile(r'\S+')
LIMIT_SECONDS = 300          # the school's five-minute seminar slot (CORE/SCHOOL-THESIS-GUIDE.mn.md)


def seminar_folders(root):
    base = Path(root) / 'CORE'
    return sorted(path for path in base.glob('seminar-*') if path.is_dir() and FOLDER.fullmatch(path.name))


def _newest(paths):
    paths = [path for path in paths if path.is_file()]
    return max(paths, key=lambda path: (path.stat().st_mtime, path.name)) if paths else None


def seminar_files(root, folder=None):
    """The folder (newest by default) with its newest deck, speech and notebook; KeyError if it does not exist."""
    folders = seminar_folders(root)
    if folder is None:
        if not folders:
            raise KeyError('seminar')
        chosen = folders[-1]
    else:
        chosen = next((path for path in folders if path.name == folder), None)
        if chosen is None:
            raise KeyError(folder)
    return dict(folder=chosen, deck=_newest(chosen.glob('*.pptx')), speech=_newest(chosen.glob('*Яриа*.md')),
                notebook=_newest(chosen.glob('*Дэвтэр*.md')))


def deck_stems(root):
    return {path.stem for folder in seminar_folders(root) for path in folder.glob('*.pptx')}


def slide_image(root, stem, number):
    """PNG bytes of a rendered slide of a known deck; KeyError for anything else."""
    if stem not in deck_stems(root) or not re.fullmatch(r'\d{2}', number or ''):
        raise KeyError(stem)
    folder = (Path(root) / 'runtime/slide-render').resolve()
    path = (folder / stem / f'slide-{number}.png').resolve()
    if path.parent.parent != folder or not path.is_file():
        raise KeyError(stem)
    return path.read_bytes()


def speech_parts(markdown):
    """(title, intro lines, [part], [(heading, lines)]) — a part is one «**N. Name (NN сек)**» block."""
    title, head, sections = split_page(markdown)
    intro, parts, current = [], [], None
    for line in head:
        match = PART.match(line.strip())
        if match:
            first, last = int(match[1]), int(match[2] or match[1])
            current = dict(first=first, last=last, title=match[3], seconds=int(match[4]), lines=[])
            parts.append(current)
        elif line.strip() == '---':
            current = None
        elif current is not None:
            current['lines'].append(line)
        else:
            intro.append(line)
    for part in parts:
        part['words'] = sum(len(WORD.findall(line)) for line in part['lines'])
    return title, intro, parts, sections


def question_cards(lines):
    """Top-level «- **question** — answer» items with their nested lines as the answer."""
    cards, current = [], None
    for line in lines:
        match = QUESTION.match(line)
        if match:
            current = dict(question=match[1], answer=[match[2]] if match[2].strip() else [])
            cards.append(current)
        elif current is not None and line.strip():
            current['answer'].append(line[2:] if line.startswith('  ') else line)
    return cards


def _clock(seconds):
    return f'{seconds // 60}:{seconds % 60:02d}'


def _slides(stem, available, first, last):
    numbers = [number for number in range(first, last + 1) if f'{number:02d}' in available]
    if not numbers:
        return '<div class="noslide">Слайдын зураг алга — <code>render_slides.py</code>-оор зурна.</div>'
    size = 'one' if len(numbers) == 1 else 'many'
    return f'<div class="slides {size}">' + ''.join(
        f'<img src="/seminar-slide/{html.escape(stem)}/{number:02d}.png" alt="Слайд {number}" loading="lazy">'
        for number in numbers) + '</div>'


def seminar_page(root, folder=None):
    files = seminar_files(root, folder)
    renderer = Renderer()
    deck = files['deck']
    stem = deck.stem if deck else ''
    render_dir = Path(root) / 'runtime/slide-render' / stem
    available = {path.stem.removeprefix('slide-') for path in render_dir.glob('slide-*.png')} if deck else set()

    # 1. rehearse: slide pictures beside their part of the speech
    intro, parts, sections = [], [], []
    if files['speech']:
        _, intro, parts, sections = speech_parts(linked_markdown(root, files['speech'].read_text(encoding='utf-8')))
    budget = sum(part['seconds'] for part in parts)
    words = sum(part['words'] for part in parts)
    cards_html = ''.join(
        f'<article class="part" data-budget="{part["seconds"]}" data-title="{html.escape(part["title"])}">'
        f'{_slides(stem, available, part["first"], part["last"])}'
        f'<div class="script"><h3><span class="num">{part["first"]}{"–" + str(part["last"]) if part["last"] != part["first"] else ""}</span>'
        f'{renderer.inline(part["title"])}</h3>'
        f'<p class="budget">Төсөв {part["seconds"]} сек · {part["words"]} үг <span class="clock" aria-live="off"></span>'
        f'<span class="over-note"></span></p>{render_markdown(part["lines"], renderer)}</div></article>'
        for part in parts) or '<p class="empty">Ярианы хэсэг олдсонгүй.</p>'

    # 2. teacher questions: what to ask, and cards for what the teacher may ask
    ask_html, card_html, extra = '', '', []
    for heading, lines in sections:
        lowered = heading.lower()
        if lowered.startswith('багшаас асуух'):
            ask_html += f'<div class="ask"><h3>{renderer.inline(heading)}</h3>{render_markdown(lines, renderer)}</div>'
        elif lowered.startswith('багш асуувал'):
            cards = question_cards(lines)
            card_html += ''.join(
                f'<li class="card" data-id="{index}"><p class="q">{renderer.inline(card["question"])}</p>'
                f'<details><summary>Хариуг харах</summary>{render_markdown(card["answer"], renderer)}</details>'
                f'<div class="marks"><button type="button" data-mark="known">✓ Мэдсэн</button>'
                f'<button type="button" data-mark="again">↺ Дахин</button></div></li>'
                for index, card in enumerate(cards))
        else:
            extra.append(f'<section class="extra"><h3>{renderer.inline(heading)}</h3>{render_markdown(lines, renderer)}</section>')

    # 3. notebook page
    notebook_html = '<p class="empty">Дэвтрийн хуудас алга.</p>'
    if files['notebook']:
        n_title, n_head, n_sections = split_page(linked_markdown(root, files['notebook'].read_text(encoding='utf-8')))
        notebook_html = (f'<h3 class="paper-title">{renderer.inline(n_title)}</h3>{render_markdown(n_head, renderer)}'
                         + ''.join(f'<h4>{renderer.inline(heading)}</h4>{render_markdown(lines, renderer)}'
                                   for heading, lines in n_sections))

    current = ' aria-current="page"'
    others = ''.join(f'<a href="/seminar/{path.name}"{current if path == files["folder"] else ""}>'
                     f'{path.name.removeprefix("seminar-")}</a>' for path in reversed(seminar_folders(root)))
    date = files['folder'].name.removeprefix('seminar-').replace('-', '.')
    source = files['speech'].relative_to(Path(root)).as_posix() if files['speech'] else files['folder'].name
    summary = (f'{html.escape(deck.name) if deck else "PPT алга"} · ярианы {len(parts)} хэсэг, ≈{words} үг · '
               f'төсөв {_clock(budget)} / {_clock(LIMIT_SECONDS)}')
    body = (PAGE.replace('@@DATE@@', html.escape(date)).replace('@@SUMMARY@@', summary)
            .replace('@@INTRO@@', render_markdown(intro, renderer)).replace('@@PARTS@@', cards_html)
            .replace('@@ASK@@', ask_html or '').replace('@@CARDS@@', card_html or '<li class="empty">Асуулт алга.</li>')
            .replace('@@NOTEBOOK@@', notebook_html).replace('@@EXTRA@@', ''.join(extra) or '<p class="empty">Нэмэлт алга.</p>')
            .replace('@@OTHERS@@', others).replace('@@SOURCE@@', html.escape(source))
            .replace('@@LIMIT@@', str(LIMIT_SECONDS)).replace('@@KEY@@', html.escape(source, quote=True)))
    return body


PAGE = '''<!doctype html>
<html lang="mn"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Семинар @@DATE@@ · THesisS</title>
<style>
:root{--ink:#10302b;--muted:#56655e;--line:#d9e1d4;--cream:#f6f7f1;--paper:#fffdf7;--night:#0f1d2e;--amber:#a14f05;--ok:#1d6b45;font-family:"Segoe UI",Arial,sans-serif;color:var(--ink);background:var(--cream)}
body{margin:0}.top{background:var(--night);color:#fff;padding:14px 28px;display:flex;gap:18px;align-items:center;flex-wrap:wrap}
.top h1{margin:0;font-size:19px;flex:1}.top a{color:#ffd76a;font-size:13px;text-decoration:none}
.tabs{position:sticky;top:0;z-index:5;background:var(--cream);border-bottom:1px solid var(--line);display:flex;gap:6px;padding:8px 28px;flex-wrap:wrap}
.tabs a{font-size:14px;text-decoration:none;color:var(--ink);padding:6px 12px;border-radius:999px;border:1px solid var(--line);background:#fff}
main{max-width:1240px;margin:0 auto;padding:18px 22px 120px}section.block{margin:0 0 34px}section.block>h2{font-size:21px;margin:8px 0 6px}
.lead{color:var(--muted);font-size:15px;line-height:1.6;max-width:80ch;margin:4px 0 14px}.summary{font-size:14px;color:var(--muted)}
.intro{font-size:14px;color:var(--muted);line-height:1.6;margin:0 0 14px;max-width:110ch}.intro summary{cursor:pointer;color:#1f5f8b}
.part{display:grid;grid-template-columns:minmax(0,5fr) minmax(0,6fr);gap:22px;background:#fff;border:2px solid var(--line);border-radius:16px;padding:16px;margin:0 0 14px;scroll-margin-top:70px}
.part.current{border-color:#2f6b5d;box-shadow:0 0 0 4px #2f6b5d22}.part.over{border-color:var(--amber)}.part.done{opacity:.72}
.slides img{width:100%;border:1px solid var(--line);border-radius:8px;display:block;background:#fff}
.slides.many{display:grid;grid-template-columns:1fr 1fr;gap:6px;align-content:start}
.noslide{color:var(--muted);font-size:13px;border:1px dashed var(--line);border-radius:8px;padding:20px;text-align:center}
.script h3{margin:2px 0 4px;font-size:18px}.num{display:inline-block;min-width:34px;margin-right:8px;padding:2px 8px;border-radius:7px;background:#e7efe5;font-size:14px;text-align:center}
.budget{margin:0 0 8px;color:var(--muted);font-size:13.5px}.clock{margin-left:10px;font-weight:700;color:var(--ink)}.over-note{margin-left:10px;color:var(--amber);font-weight:700}
.script p:not(.budget){font-size:clamp(19px,1.55vw,24px);line-height:1.6;max-width:68ch;margin:0 0 10px;text-align:left}
.controls{position:fixed;left:0;right:0;bottom:0;z-index:6;background:var(--night);color:#fff;display:flex;gap:10px;align-items:center;padding:10px 22px;flex-wrap:wrap}
.controls button{font-size:15px;padding:9px 14px;border-radius:9px;border:0;cursor:pointer;background:#ffd76a;color:#1b1b1b;font-weight:600}
.controls button.secondary{background:#2b3c52;color:#fff}.controls .total{font-size:18px;font-weight:700;min-width:120px}
.bar{flex:1;min-width:120px;height:10px;background:#2b3c52;border-radius:6px;overflow:hidden}.bar span{display:block;height:100%;width:0;background:#7ed3a1}.bar span.over{background:#f0a24a}
.hint{font-size:12.5px;color:#c9d3df}
table.result{border-collapse:collapse;margin:12px 0;font-size:14.5px}table.result td,table.result th{border:1px solid var(--line);padding:6px 10px;text-align:left}
table.result tr.over td{color:var(--amber);font-weight:600}
.ask{background:#fff;border:1px solid var(--line);border-radius:14px;padding:6px 18px 10px;margin:0 0 14px;font-size:16px;line-height:1.6}
.cards{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:12px}
.card{background:#fff;border:2px solid var(--line);border-radius:14px;padding:14px 16px;font-size:15.5px;line-height:1.55}
.card .q{font-size:18px;font-weight:700;margin:0 0 8px}.card summary{cursor:pointer;color:#1f5f8b;font-weight:600}
.card.known{border-color:#7fb99a;background:#f5fbf6}.card.again{border-color:#e5b46f}
.marks{display:flex;gap:8px;margin-top:10px}.marks button{font-size:14px;padding:6px 10px;border-radius:8px;border:1px solid var(--line);background:#fff;cursor:pointer}
.cardstat{font-size:14px;color:var(--muted);margin:0 0 10px}
.paper{background:var(--paper);border:1px solid var(--line);border-radius:6px;padding:26px 34px;max-width:820px;font-size:16px;line-height:1.75;
 background-image:repeating-linear-gradient(transparent 0 27px,#e8eef5 27px 28px)}
.paper h3.paper-title{font-size:20px;margin:0 0 10px}.paper h4{font-size:16.5px;margin:20px 0 6px}
.extra{background:#fff;border:1px solid var(--line);border-radius:14px;padding:6px 20px 12px;margin:0 0 14px;font-size:15.5px;line-height:1.6}
.extra table{border-collapse:collapse;font-size:14px}.extra td,.extra th{border:1px solid var(--line);padding:6px 9px;vertical-align:top;text-align:left}
code{font-family:Consolas,monospace;font-size:.92em;background:#eef2ea;padding:1px 4px;border-radius:4px}a{color:#1f5f8b}
footer{color:var(--muted);font-size:13px;line-height:1.7;border-top:1px solid var(--line);padding-top:12px}
footer .others a{margin-right:10px}footer .others a[aria-current]{font-weight:700;color:var(--ink)}
.empty{color:var(--muted)}.print{font-size:14px;padding:7px 12px;border-radius:8px;border:1px solid var(--line);background:#fff;cursor:pointer;margin:0 0 10px}
@media(max-width:860px){.part{grid-template-columns:1fr}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important}}
@media print{.top,.tabs,.controls,footer{display:none}body.print-notebook main>section:not(#notebook){display:none}
 .paper{border:0;background:#fff;padding:0;max-width:none}body{background:#fff}}
</style></head>
<body data-source="@@KEY@@">
<div class="top"><h1>Семинар · @@DATE@@</h1><a href="/reports">Тайлан ба эх сурвалж</a><a href="/reader">Өгүүлэл унших</a><a href="/work">Ажлын самбар</a><a href="/">Чат</a></div>
<nav class="tabs" aria-label="Хэсгүүд"><a href="#rehearse">▶ Давтах</a><a href="#questions">? Багшийн асуулт</a><a href="#notebook">✎ Дэвтэр</a><a href="#extra">+ Нэмэлт</a></nav>
<main>
<section class="block" id="rehearse"><h2>Яриагаа давтах</h2>
<p class="summary">@@SUMMARY@@</p>
<p class="lead">Чангаар уншиж давтана: эхлээд ганцаараа нэг удаа, дараа нь найзынхаа өмнө нэг удаа. «Эхлэх»-ийг дараад хэсэг дуусах бүрд «Дараагийн хэсэг» (эсвэл Space) дарна. Хэсгийн төсөв хэтэрвэл хүрээ нь улбар шар болж, хэдэн секунд хэтэрснийг бичнэ — анивчихгүй, дуугарахгүй. Дуусахад хэсэг бүрийн хугацаа гарна. Юу ч бичиж хадгалахгүй.</p>
<details class="intro"><summary>Файлын тухай (PPT-ийн хувилбар, хугацааны тооцоо)</summary>@@INTRO@@</details>
@@PARTS@@
<div id="result"></div></section>
<section class="block" id="questions"><h2>Багшийн асуулт</h2>
@@ASK@@
<p class="lead">Асуултыг уншаад хариугаа эхлээд өөрөө чангаар хэлж үзээд, дараа нь «Хариуг харах»-ыг дарна. Мэдсэн бол «✓», дахин давтах бол «↺» — тэмдэг зөвхөн энэ хөтчид хадгалагдана.</p>
<p class="cardstat" id="cardstat"></p><ol class="cards">@@CARDS@@</ol></section>
<section class="block" id="notebook"><h2>Дэвтэрт хуулж бичих</h2><button type="button" class="print" id="print">🖨 Зөвхөн дэвтрийн хуудсыг хэвлэх</button>
<div class="paper">@@NOTEBOOK@@</div></section>
<section class="block" id="extra"><h2>Нэмэлт</h2>@@EXTRA@@</section>
<footer><div>Хуудасны зохиомжийн үндэслэл: <a href="/reports/53-seminar-view-research-20261123.mn">судалгааны товч тайлан</a>. Эх файл: <code>@@SOURCE@@</code> (зөвхөн энэ компьютерт).</div>
<div class="others">Бусад семинар: @@OTHERS@@</div></footer>
</main>
<div class="controls" role="region" aria-label="Цаг"><button type="button" id="start">▶ Эхлэх</button><button type="button" id="next" class="secondary" disabled>Дараагийн хэсэг →</button><button type="button" id="stop" class="secondary" disabled>■ Дуусгах</button>
<span class="total" id="total">0:00 / 5:00</span><div class="bar"><span id="bar"></span></div><span class="hint">Space = дараагийн · Esc = дуусгах</span></div>
<script>
(()=>{const parts=[...document.querySelectorAll('.part')],limit=@@LIMIT@@;let i=-1,start=0,partStart=0,timer=null,times=[];
const $=id=>document.getElementById(id),fmt=s=>{s=Math.max(0,Math.round(s));return Math.floor(s/60)+':'+String(s%60).padStart(2,'0')};
const smooth=!matchMedia('(prefers-reduced-motion: reduce)').matches;
function tick(){const now=Date.now(),total=(now-start)/1000;$('total').textContent=fmt(total)+' / '+fmt(limit);
 const bar=$('bar');bar.style.width=Math.min(100,total/limit*100)+'%';bar.classList.toggle('over',total>limit);
 if(i>=0&&i<parts.length){const el=parts[i],t=(now-partStart)/1000,b=+el.dataset.budget;el.querySelector('.clock').textContent=fmt(t)+' / '+fmt(b);
  const over=t>b+2;el.classList.toggle('over',over);el.querySelector('.over-note').textContent=over?'+'+Math.round(t-b)+' сек хэтэрлээ':'';}}
function show(n){const now=Date.now();if(i>=0&&i<parts.length){times[i]=(now-partStart)/1000;parts[i].classList.remove('current');parts[i].classList.add('done');}
 i=n;if(i<parts.length){partStart=now;parts[i].classList.add('current');parts[i].scrollIntoView({behavior:smooth?'smooth':'auto',block:'start'});}else finish();}
function reset(){clearInterval(timer);timer=null;i=-1;times=[];parts.forEach(p=>{p.classList.remove('current','done','over');p.querySelector('.clock').textContent='';p.querySelector('.over-note').textContent='';});$('result').innerHTML='';}
function begin(){reset();start=Date.now();timer=setInterval(tick,250);$('next').disabled=false;$('stop').disabled=false;$('start').textContent='↺ Дахин эхлэх';show(0);tick();}
function finish(){if(timer===null)return;if(i>=0&&i<parts.length){times[i]=(Date.now()-partStart)/1000;parts[i].classList.remove('current');}
 clearInterval(timer);timer=null;$('next').disabled=true;$('stop').disabled=true;const total=(Date.now()-start)/1000;
 let rows='';parts.forEach((p,k)=>{if(times[k]===undefined)return;const b=+p.dataset.budget,t=times[k];rows+='<tr class="'+(t>b+2?'over':'')+'"><td>'+p.dataset.title.replace(/</g,'&lt;')+'</td><td>'+fmt(b)+'</td><td>'+fmt(t)+'</td><td>'+(t>b?'+':'')+Math.round(t-b)+' сек</td></tr>';});
 $('result').innerHTML='<h3>Энэ давталт: '+fmt(total)+' / '+fmt(limit)+(total>limit?' — хязгаараас хэтэрсэн':'')+'</h3><table class="result"><tr><th>Хэсэг</th><th>Төсөв</th><th>Болсон</th><th>Зөрүү</th></tr>'+rows+'</table>';
 $('result').scrollIntoView({behavior:smooth?'smooth':'auto'});}
$('start').onclick=begin;$('next').onclick=()=>show(i+1);$('stop').onclick=finish;
document.addEventListener('keydown',e=>{if(timer===null||/INPUT|TEXTAREA|BUTTON|SUMMARY/.test(e.target.tagName))return;
 if(e.key===' '||e.key==='ArrowRight'){e.preventDefault();show(i+1);}else if(e.key==='Escape'){finish();}});
const key='seminar-cards:'+document.body.dataset.source;let marks={};try{marks=JSON.parse(localStorage.getItem(key)||'{}');}catch(e){}
const cards=[...document.querySelectorAll('.card')];
function paint(){let known=0;cards.forEach(c=>{const m=marks[c.dataset.id];c.classList.toggle('known',m==='known');c.classList.toggle('again',m==='again');if(m==='known')known++;});
 $('cardstat').textContent=cards.length?('Мэдсэн '+known+' / '+cards.length):'';}
cards.forEach(c=>c.querySelectorAll('[data-mark]').forEach(b=>b.onclick=()=>{marks[c.dataset.id]=b.dataset.mark;try{localStorage.setItem(key,JSON.stringify(marks));}catch(e){}paint();}));paint();
$('print').onclick=()=>{document.body.classList.add('print-notebook');window.print();setTimeout(()=>document.body.classList.remove('print-notebook'),500);};
})();
</script></body></html>
'''
