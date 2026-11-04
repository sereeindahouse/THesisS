"""Сургуульд өгөх 3 хуудас PDF: мэдлэгийн модны зураг + хэрэгтэй мэдээллийн жагсаалт.

Мод `config/knowledge-topics.json`-оос, салаа бүрийн эх байгаа эсэх
`build_knowledge_tree`-ээс (DB-г зөвхөн уншина). XeLaTeX (MiKTeX) хэрэгтэй.

    .venv/Scripts/python.exe tools/build_school_data_list.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from build_knowledge_tree import build_tree, load_inputs  # noqa: E402

OUTPUT = ROOT / 'data/school-request/ШМТК_сургуулиас_хэрэгтэй_мэдээлэл.pdf'
SKIP = {'nmct', 'review-needed'}

# Огт эх байхгүй салаа: заавал хэрэгтэй (А).
MISSING = [
    ('Байршил, өрөө', [
        ('Давхар бүрийн өрөө', 'Өрөө бүрийн дугаар, давхар, зориулалт (анги, лаборатори, алба, багшийн өрөө).'),
        ('Ресепшн, үйлчилгээний өрөө', 'Ресепшн, сургалтын алба, санхүү, номын сан, цайны газар, эмнэлгийн өрөө, спорт заал: давхар, өрөө, ажлын цаг.'),
        ('Тэнхимийн өрөө', '6 тэнхим тус бүрийн өрөөний дугаар.'),
    ]),
    ('Багш, ажилтан', [
        ('Тэнхимийн багш, албан тушаал', 'Тэнхим бүрийн багш, ажилтны овог нэр, албан тушаал (нийтэд харуулахыг зөвшөөрсөн хүмүүс).'),
        ('Багшийн өрөө, уулзах цаг', 'Багш бүрийн өрөө, оюутан уулзах өдөр, цаг.'),
        ('Хуваариар хичээлтэй эсвэл сул', 'Багшийн нэртэй хичээлийн хуваарь (доорх хуваариас гарна).'),
    ]),
    ('Анги, хичээлийн хуваарь', [
        ('Бүлэг, ангийн өрөө', 'Бүлэг бүрийн нэр (жишээ: КУ-2), курс, тэнхим, үндсэн өрөө, ангийн багш.'),
        ('Долоо хоногийн хуваарь', 'Энэ улирлын хуваарь: гараг, эхлэх-дуусах цаг, хичээл, багш, өрөө, бүлэг. '
                                   'Улирлын эхлэх, дуусах өдөр, амралт.'),
    ]),
]
# Эх бий боловч дутуу салаа (Б).
THIN = [
    ('Оюутны амьдрал', [
        ('Номын сан', 'Ажлын цаг; нэг удаад хэдэн ном, хэдэн хоног зээлэх журам.'),
        ('Спортын орчин', 'Заалны ажлын цаг, клуб, секцийн нэр ба цаг.'),
        ('Суралцах орчин', 'Дотуур байр байгаа эсэх, төлбөр, хаана; цайны газрын цаг.'),
        ('Оюутны зөвлөл', 'Холбогдох хаяг; дарга, гишүүдийг нийтэд харуулах бол нэр.'),
    ]),
    ('Карьер, хамтын ажиллагаа', [
        ('Дадлага', 'Дадлагын журам: хэзээ, хэдэн долоо хоног, хаана.'),
        ('Японтой холбоотой хөтөлбөр', 'Хөтөлбөр бүрийн дараагийн бүртгэлийн хугацаа, тэнцэх нөхцөл.'),
    ]),
    ('Элсэлт', [('Бүх салаа', '2027 оны элсэлтийн журам гармагц: огноо, төлбөр, шалгалт.')]),
    ('Холбоо барих', [('—', 'Алба тус бүрийн утас, имэйл (сургалтын алба, санхүү, ресепшн).')]),
    ('Арга хэмжээ', [('—', 'Энэ хичээлийн жилийн арга хэмжээний хуваарь (нээлттэй хаалганы өдөр, олимпиад г.м.).')]),
]


def tex(text):
    return (str(text).replace('\\', r'\textbackslash{}').replace('&', r'\&').replace('%', r'\%')
            .replace('#', r'\#').replace('_', r'\_'))


def tree_picture(tree):
    topics = [t for t in tree['topics'] if t['topic_id'] not in SKIP]
    frames = [t for t in topics if t['parent_id'] == 'nmct']
    has = lambda t: any(t['subtree_counts'][k] for k in ('pages', 'facts', 'faqs'))
    lines = [r'\begin{tikzpicture}[x=24.2mm,y=-1mm,',
             r'  frame/.style={draw,rounded corners=2pt,align=center,text width=21mm,minimum height=11mm,font=\scriptsize\bfseries},',
             r'  leaf/.style={draw,rounded corners=1.5pt,align=left,text width=20mm,minimum height=7mm,font=\tiny,inner sep=1.6pt},',
             r'  ok/.style={fill=okfill,draw=okline}, gap/.style={fill=gapfill,draw=gapline}]',
             r'\node[draw,fill=rootfill,rounded corners=3pt,font=\normalsize\bfseries,minimum width=80mm,minimum height=10mm]'
             r' (root) at (5,0) {ШМТК-ийн AI чатбот — мэдлэгийн мод};']
    for i, frame in enumerate(frames):
        style = 'ok' if has(frame) else 'gap'
        lines.append(rf'\node[frame,{style}] (f{i}) at ({i},22) {{{tex(frame["label_mn"])}}};')
        lines.append(rf'\draw[line] (root.south) -- ++(0,-4) -| (f{i}.north);')
        children = [t for t in topics if t['parent_id'] == frame['topic_id']]
        for j, child in enumerate(children):
            style = 'ok' if has(child) else 'gap'
            lines.append(rf'\node[leaf,{style}] (f{i}c{j}) at ({i},{40 + j * 11}) {{{tex(child["label_mn"])}}};')
            lines.append(rf'\draw[line] (f{i}.south) -- (f{i}c{j}.north);' if j == 0 else
                         rf'\draw[line] (f{i}c{j - 1}.south) -- (f{i}c{j}.north);')
    lines.append(r'\end{tikzpicture}')
    return '\n'.join(lines), len(frames), len(topics) - len(frames)


def table(groups):
    rows = [r'\begin{longtable}{|>{\raggedright\arraybackslash}p{38mm}|>{\raggedright\arraybackslash}p{50mm}|>{\raggedright\arraybackslash}p{168mm}|}\hline\noalign{}',
            r'\rowcolor{headfill}\textbf{Хүрээ} & \textbf{Салаа} & \textbf{Сургуулиас хэрэгтэй мэдээлэл}\\\hline\endhead']
    for frame, leaves in groups:
        for k, (leaf, need) in enumerate(leaves):
            rows.append(rf'{tex(frame) if k == 0 else ""} & {tex(leaf)} & {tex(need)}\\\hline')
    rows.append(r'\end{longtable}')
    return '\n'.join(rows)


def document(tree):
    picture, n_frames, n_leaves = tree_picture(tree)
    counts = tree['counts']
    return rf'''\documentclass[10pt]{{article}}
\usepackage[a4paper,landscape,margin=12mm]{{geometry}}
\usepackage{{fontspec}}
\IfFontExistsTF{{Arial}}{{\setmainfont{{Arial}}}}{{\setmainfont{{Liberation Sans}}}}
\usepackage{{tikz,xcolor,longtable,colortbl,array}}
\definecolor{{okfill}}{{HTML}}{{E2F0D9}}\definecolor{{okline}}{{HTML}}{{548235}}
\definecolor{{gapfill}}{{HTML}}{{FCE4D6}}\definecolor{{gapline}}{{HTML}}{{C55A11}}
\definecolor{{rootfill}}{{HTML}}{{DDEBF7}}\definecolor{{headfill}}{{HTML}}{{DDEBF7}}
\tikzset{{line/.style={{draw=gray!70,thin}}}}
\pagestyle{{empty}}\setlength{{\parindent}}{{0pt}}
\begin{{document}}
{{\Large\bfseries ШМТК-ийн AI чатботод сургуулиас хэрэгтэй мэдээлэл}}\hfill{{\small Компьютерын ухааны тэнхимийн төгсөлтийн ажил}}\par
\vspace{{1mm}}{{\small Чатбот зөвхөн сургуулийн өгсөн мэдээллээс хариулна. Доорх модны {n_frames} хүрээ, {n_leaves} салааны
\colorbox{{okfill}}{{ногоон}} нь сайтаас мэдээлэлтэй, \colorbox{{gapfill}}{{улбар}} нь мэдээлэл огт алга.
Одоо сайтаас {counts["pages"]} хуудас, {counts["facts"]} баримт хадгалсан.}}\par\vspace{{3mm}}
\begin{{center}}{picture}\end{{center}}
\newpage
{{\Large\bfseries А. Огт байхгүй — заавал хэрэгтэй}}\par\vspace{{1mm}}
{{\small Эдгээр нь сургуулийн сайтад байхгүй тул систем одоо хариулж чадахгүй: «Багш хаана байна?», «Анги хаана вэ?»,
«Сургалтын алба хэддүгээр давхарт вэ?». Багш одоо хаана байгааг систем зөвхөн хуваариар таамаглаж хэлнэ, хүнийг хянахгүй.}}\par\vspace{{2mm}}
{table(MISSING)}
\newpage
{{\Large\bfseries Б. Сайтад дутуу — боломжтой бол}}\par\vspace{{2mm}}
{table(THIN)}
\vspace{{4mm}}
{{\large\bfseries Хэрхэн өгөх вэ?}}\par\vspace{{1mm}}
\begin{{itemize}}\setlength{{\itemsep}}{{1pt}}
\item Байгаа хэлбэрээр нь өгөхөд болно: Excel, Word, PDF эсвэл хуваарийн хуулбар. Шинээр хүснэгт бөглөх шаардлагагүй.
\item А хэсэг хамгийн чухал. Эхлээд өрөөний жагсаалт ба энэ улирлын хичээлийн хуваарь хангалттай.
\item Нийтэд харуулахгүй мэдээллийг тэмдэглэнэ үү. Хувийн утас, гэрийн хаяг, оюутны дүн, ирц хэрэггүй.
\item Хуваарь, өрөө өөрчлөгдвөл шинэ хувилбараа өгнө үү.
\end{{itemize}}
\vspace{{3mm}}Холбоо барих: \rule{{70mm}}{{0.4pt}} \qquad Хугацаа: \rule{{40mm}}{{0.4pt}}
\end{{document}}
'''


def main():
    config = json.loads((ROOT / 'config/knowledge-topics.json').read_text(encoding='utf-8-sig'))
    tree = build_tree(config, load_inputs(ROOT))
    xelatex = shutil.which('xelatex') or str(Path(os.environ.get('LOCALAPPDATA', '')) /
                                             'Programs/MiKTeX/miktex/bin/x64/xelatex.exe')
    with tempfile.TemporaryDirectory() as work:
        source = Path(work) / 'list.tex'
        source.write_text(document(tree), encoding='utf-8')
        for _ in range(2):
            run = subprocess.run([xelatex, '-interaction=nonstopmode', '-halt-on-error', source.name],
                                 cwd=work, capture_output=True, text=True, encoding='utf-8', errors='replace')
            if run.returncode:
                sys.exit(run.stdout[-3000:])
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path(work) / 'list.pdf', OUTPUT)
    print(OUTPUT)


if __name__ == '__main__':
    main()
