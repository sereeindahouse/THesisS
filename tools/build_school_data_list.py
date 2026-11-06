"""Сургуульд өгөх энгийн хүснэгтүүд (PDF + Excel) ба ресепшний энгийн асуултууд.

Багшийн 2026.11.06-ны заавар: мэдлэгийн модны зураг, өнгөт тайлбаргүй; зөвхөн
хэрэгтэй мэдээллийн хүснэгт. XeLaTeX (MiKTeX) ба openpyxl хэрэгтэй.

    .venv/Scripts/python.exe tools/build_school_data_list.py
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / 'data/school-request'
PDF = OUT_DIR / 'ШМТК_сургуулиас_хэрэгтэй_мэдээлэл.pdf'
XLSX = OUT_DIR / 'ШМТК_сургуульд_өгөх_хүснэгт.xlsx'
BLANK_ROWS = 6

# (хүснэгтийн нэр, тайлбар, баганууд, жишээ мөр)
TABLES = [
    ('1. Өрөө', 'Сургуулийн бүх өрөө.',
     ['Өрөөний дугаар', 'Давхар', 'Зориулалт (анги, лаборатори, алба, багшийн өрөө)', 'Тэнхим'],
     ['305', '3', 'Компьютерын лаборатори', 'Компьютерын ухаан']),
    ('2. Алба, үйлчилгээ', 'Сургалтын алба, санхүү, номын сан, цайны газар, эмнэлэг, спорт заал, ресепшн.',
     ['Алба', 'Давхар', 'Өрөө', 'Ажлын цаг', 'Албаны утас эсвэл имэйл'],
     ['Номын сан', '2', '210', 'Да–Ба 09:00–18:00', '—']),
    ('3. Багш, ажилтан', 'Нийтэд харуулахыг зөвшөөрсөн хүмүүс л.',
     ['Овог нэр', 'Тэнхим', 'Албан тушаал', 'Өрөө', 'Оюутантай уулзах цаг'],
     ['Б.Бат', 'Компьютерын ухаан', 'Багш', '302', 'Мя 14:00–16:00']),
    ('4. Анги (бүлэг)', 'Энэ хичээлийн жилийн бүлгүүд.',
     ['Бүлгийн нэр', 'Курс', 'Тэнхим', 'Үндсэн өрөө', 'Ангийн багш'],
     ['КУ-2', '2', 'Компьютерын ухаан', '305', 'Б.Бат']),
    ('5. Хичээлийн хуваарь', 'Энэ улирлын хуваарь. Байгаа Excel хуваарийг шууд өгч болно.',
     ['Гараг', 'Цаг (эхлэх–дуусах)', 'Хичээл', 'Багш', 'Өрөө', 'Бүлэг'],
     ['Даваа', '09:00–10:30', 'Програмчлал', 'Б.Бат', '305', 'КУ-2']),
]

DATES = ['Улирал эхлэх өдөр', 'Улирал дуусах өдөр', 'Амралтын өдрүүд']

# (асуулт, аль хүснэгтээс хариулах вэ)
QUESTIONS = [
    ('Номын сан хэддүгээр давхарт вэ?', '2'),
    ('Сургалтын алба хаана байдаг вэ? Хэдэн цагт ажилладаг вэ?', '2'),
    ('Цайны газар хэдэн цагт ажилладаг вэ?', '2'),
    ('305 тоот хэддүгээр давхарт вэ?', '1'),
    ('Компьютерын ухааны тэнхим хаана вэ?', '1'),
    ('Бат багшийн өрөө хаана вэ?', '3'),
    ('Бат багш хэзээ оюутантай уулздаг вэ?', '3'),
    ('Бат багш одоо хичээлтэй юу?', '5 (зөвхөн хуваариар)'),
    ('КУ-2 анги хаана хичээллэдэг вэ?', '4'),
    ('2-р курс өнөөдөр хэдэн цагт хичээлтэй вэ?', '5'),
    ('Санхүүгийн албатай яаж холбогдох вэ?', '2'),
    ('Ангийн багш хэн бэ?', '4'),
]

RECEPTION_STAFF = [
    'Ирсэн хүмүүс танаас хамгийн их юу асуудаг вэ? (5 асуулт)',
    'Аль асуултад хариулахад хэцүү байдаг вэ?',
    'Танд ямар жагсаалт байдаг вэ? (өрөө, утас, хуваарь)',
]


def tex(text):
    return (str(text).replace('\\', r'\textbackslash{}').replace('&', r'\&').replace('%', r'\%')
            .replace('#', r'\#').replace('_', r'\_'))


def latex_table(title, note, columns, example):
    spec = '|r|' + '|'.join(['X'] * len(columns)) + '|'
    head = ' & '.join([r'\textbf{№}'] + [rf'\textbf{{{tex(c)}}}' for c in columns])
    sample = ' & '.join([r'\textit{жишээ}'] + [rf'\textcolor{{gray}}{{\textit{{{tex(v)}}}}}' for v in example])
    blanks = '\n'.join(rf'{i} & ' + ' & '.join([''] * len(columns)) + r'\\[2.2mm]\hline'
                       for i in range(1, BLANK_ROWS + 1))
    return rf'''\par\noindent\begin{{minipage}}{{\linewidth}}
\subsection*{{{tex(title)}}}
{{\small {tex(note)}}}\par\vspace{{1mm}}
\begin{{tabularx}}{{\linewidth}}{{{spec}}}\hline
\rowcolor{{headfill}}{head}\\\hline
{sample}\\\hline
{blanks}
\end{{tabularx}}
\end{{minipage}}\par\vspace{{3mm}}
'''


def document():
    tables = '\n'.join(latex_table(*t) for t in TABLES)
    dates = '\n'.join(rf'{tex(d)} & \\[2.2mm]\hline' for d in DATES)
    questions = '\n'.join(rf'{i} & {tex(q)} & {tex(t)}\\\hline' for i, (q, t) in enumerate(QUESTIONS, 1))
    staff = '\n'.join(rf'\item {tex(s)}' for s in RECEPTION_STAFF)
    return rf'''\documentclass[10pt]{{article}}
\usepackage[a4paper,landscape,margin=14mm]{{geometry}}
\usepackage{{fontspec}}
\IfFontExistsTF{{Arial}}{{\setmainfont{{Arial}}}}{{\setmainfont{{Liberation Sans}}}}
\usepackage{{xcolor,colortbl,array,tabularx}}
\definecolor{{headfill}}{{HTML}}{{E7E6E6}}
\pagestyle{{empty}}\setlength{{\parindent}}{{0pt}}
\renewcommand{{\arraystretch}}{{1.25}}
\begin{{document}}
{{\Large\bfseries ШМТК-ийн AI чатботод сургуулиас хэрэгтэй мэдээлэл}}\hfill{{\small Компьютерын ухааны тэнхимийн төгсөлтийн ажил}}\par
\vspace{{1mm}}{{\small Чатбот ресепшнд ирсэн хүний асуултад зөвхөн эдгээр хүснэгтээс хариулна.
Хүснэгтийг бөглөх эсвэл байгаа файлаа (Excel, Word, хуваарь) шууд өгөхөд болно.
Хувийн утас, гэрийн хаяг, оюутны дүн, ирц хэрэггүй.}}\par\vspace{{2mm}}
{tables}
\subsection*{{6. Улирлын огноо}}
\begin{{tabularx}}{{0.6\linewidth}}{{|p{{55mm}}|X|}}\hline
{dates}
\end{{tabularx}}
\newpage
\section*{{Ресепшнд асуух энгийн асуултууд}}
{{\small Чатбот эдгээр асуултад хариулах ёстой. Хариулт нь баруун баганад заасан хүснэгтээс гарна.
«Багш одоо хаана?» гэсэн асуултад зөвхөн хуваариар хариулна; багш өрөөндөө байгааг батлахгүй.}}\par\vspace{{2mm}}
\begin{{tabularx}}{{\linewidth}}{{|r|X|p{{55mm}}|}}\hline
\rowcolor{{headfill}}\textbf{{№}} & \textbf{{Асуулт}} & \textbf{{Хүснэгт}}\\\hline
{questions}
\end{{tabularx}}
\subsection*{{Ресепшний ажилтнаас асуух}}
\begin{{enumerate}}\setlength{{\itemsep}}{{1pt}}
{staff}
\end{{enumerate}}
\vspace{{4mm}}Хариуцсан хүн: \rule{{70mm}}{{0.4pt}} \qquad Өгөх хугацаа: \rule{{40mm}}{{0.4pt}}
\end{{document}}
'''


def build_pdf():
    xelatex = shutil.which('xelatex') or str(Path(os.environ.get('LOCALAPPDATA', '')) /
                                             'Programs/MiKTeX/miktex/bin/x64/xelatex.exe')
    with tempfile.TemporaryDirectory() as work:
        source = Path(work) / 'list.tex'
        source.write_text(document(), encoding='utf-8')
        for _ in range(2):
            run = subprocess.run([xelatex, '-interaction=nonstopmode', '-halt-on-error', source.name],
                                 cwd=work, capture_output=True, text=True, encoding='utf-8', errors='replace')
            if run.returncode:
                sys.exit(run.stdout[-3000:])
        shutil.copyfile(Path(work) / 'list.pdf', PDF)


def build_xlsx():
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    book = Workbook()
    book.remove(book.active)
    bold, head = Font(bold=True), PatternFill('solid', fgColor='E7E6E6')
    sample_font = Font(italic=True, color='808080')
    for title, note, columns, example in TABLES:
        sheet = book.create_sheet(title.split('. ', 1)[1][:31])
        sheet.append([note])
        sheet.append(columns)
        sheet.append(example)
        for cell in sheet[2]:
            cell.font, cell.fill = bold, head
        for cell in sheet[3]:
            cell.font = sample_font
        for i, column in enumerate(columns):
            sheet.column_dimensions[chr(65 + i)].width = max(16, min(45, len(column) + 4))
        sheet.freeze_panes = 'A3'
    sheet = book.create_sheet('Улирлын огноо')
    for row in DATES:
        sheet.append([row, ''])
    sheet.column_dimensions['A'].width = 24
    sheet = book.create_sheet('Ресепшний асуулт')
    sheet.append(['№', 'Асуулт', 'Хүснэгт'])
    for cell in sheet[1]:
        cell.font, cell.fill = bold, head
    for i, (question, source) in enumerate(QUESTIONS, 1):
        sheet.append([i, question, source])
    sheet.column_dimensions['B'].width = 60
    sheet.column_dimensions['C'].width = 22
    for row in sheet.iter_rows():
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical='top')
    book.save(XLSX)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    build_pdf()
    build_xlsx()
    print(PDF)
    print(XLSX)


if __name__ == '__main__':
    main()
