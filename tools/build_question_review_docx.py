"""Write the check-question set as a Word file a school office can mark by hand.

The user (2026-11-20) wants to go through the questions with the training office: is each prepared
answer right, and what must a full answer tell the visitor. The file shows no system output, so the
office's review stays independent of what the system answers today.

    python tools/build_question_review_docx.py <pylibs with python-docx> [questions.json] [out.docx]
"""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = ROOT / 'data/eval/system-questions-draft-20261117.json'
OUT = ROOT / 'data/school-request/ШМТК_шалгах_асуулт_сургалтын_албанд.docx'
GROUPS = (('answerable', 'Сургуулийн мэдээллийн асуулт'),
          ('compound', 'Нэг дор хоёр зүйл асуусан асуулт'),
          ('reception', 'Өрөө, анги, багш, хуваарийн асуулт'),
          ('unanswerable', 'Одоо системд мэдээлэл нь байхгүй асуулт'))
INTRO = (
    'Дипломын ажлаар хийж буй сургуулийн ухаалаг туслах зөв хариулж байгаа эсэхийг шалгахад ашиглах асуултууд. '
    'Асуулт бүрийн хариултыг сургуулийн вэб сайт болон сургуулиас авсан мэдээллээс бэлдсэн.',
    'Танаас хүсэх зүйл:',
    '1. Бэлдсэн хариулт зөв эсэхийг «Зөв үү» баганад тэмдэглэх (Тийм / Үгүй).',
    '2. Буруу эсвэл хуучирсан бол зөв хариултыг бичих.',
    '3. Ирсэн хүнд хариулахдаа заавал хэлдэг нэмэлт мэдээллийг бичих (хугацаа, бүрдүүлэх материал, хэнд, хаана хандах гэх мэт).',
    'Сүүлийн хэсгийн асуултуудад одоогоор мэдээлэл байхгүй тул аль алба, аль өрөөнд хандуулахыг бичиж өгнө үү.')


def expected(question):
    if question.get('expect') == 'abstain' or question.get('kind') == 'unanswerable':
        return 'Мэдээлэл алга. Аль алба, хаана хандуулах вэ?'
    values = '; '.join(question.get('required_values') or [])
    if not values and question.get('any_of'):
        values = 'аль нэг нь: ' + '; '.join(question['any_of'])
    return values + (f" ({question['note']})" if question.get('note') else '')


def build(pylibs, questions=QUESTIONS, out=OUT):
    sys.path.insert(0, str(pylibs))
    from docx import Document
    from docx.enum.section import WD_ORIENT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt

    data = json.loads(Path(questions).read_text(encoding='utf-8'))
    document = Document()
    section = document.sections[0]
    section.orientation = WD_ORIENT.LANDSCAPE
    section.page_width, section.page_height = Cm(29.7), Cm(21.0)
    for side in ('left_margin', 'right_margin', 'top_margin', 'bottom_margin'):
        setattr(section, side, Cm(1.8))
    style = document.styles['Normal']
    style.font.name, style.font.size = 'Times New Roman', Pt(11)
    style.element.rPr.rFonts.set(qn('w:eastAsia'), 'Times New Roman')

    def shade(cell, colour):
        properties = cell._tc.get_or_add_tcPr()
        fill = OxmlElement('w:shd')
        fill.set(qn('w:val'), 'clear')
        fill.set(qn('w:color'), 'auto')
        fill.set(qn('w:fill'), colour)
        properties.append(fill)

    title = document.add_paragraph()
    run = title.add_run('Сургуулийн ухаалаг туслахыг шалгах асуултууд')
    run.bold, run.font.size = True, Pt(15)
    for line in INTRO:
        document.add_paragraph(line)
    widths = (Cm(1.4), Cm(7.6), Cm(7.0), Cm(1.8), Cm(8.3))
    for kind, heading in GROUPS:
        rows = [question for question in data['questions'] if question.get('kind') == kind]
        if not rows:
            continue
        head = document.add_paragraph()
        run = head.add_run(f'{heading} ({len(rows)})')
        run.bold, run.font.size = True, Pt(12)
        table = document.add_table(rows=1, cols=5)
        table.style = 'Table Grid'
        table.autofit = False
        layout = OxmlElement('w:tblLayout')          # LibreOffice keeps equal columns without a fixed layout
        layout.set(qn('w:type'), 'fixed')
        table._tbl.tblPr.append(layout)
        for column, width in zip(table.columns, widths):
            column.width = width
        for cell, text, width in zip(table.rows[0].cells, ('№', 'Асуулт', 'Бэлдсэн хариулт', 'Зөв үү',
                                                          'Засвар, заавал хэлэх нэмэлт мэдээлэл'), widths):
            cell.width = width
            cell.text = ''
            cell.paragraphs[0].add_run(text).bold = True
            shade(cell, 'E8EEF4')
        for question in rows:
            cells = table.add_row().cells
            for cell, text, width in zip(cells, (question['id'], question['query'], expected(question), '', ''), widths):
                cell.width = width
                cell.text = text
        document.add_paragraph()
    document.add_paragraph('Хянасан: ____________________     Алба: ____________________     Огноо: ______________')
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    document.save(str(out))
    return out, len(data['questions'])


if __name__ == '__main__':
    arguments = sys.argv[1:]
    if not arguments:
        raise SystemExit(__doc__)
    path, count = build(arguments[0], *arguments[1:3])
    sys.stdout.reconfigure(encoding='utf-8')
    print(f'{count} асуулт -> {path}')
