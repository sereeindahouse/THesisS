"""Content v7 (2026-11-25): three stored answers for basic questions that got a wrong or no answer.

The user, 11/25: «first do all school basic questions — school general info, teacher info and where their room
is». Asking 62 general questions on the real server showed three that the saved pages answer but the chat did
not: «Элсэхэд ямар шаардлага тавьдаг вэ?» (a department's objectives were shown), «Элсэхэд ямар бичиг баримт
хэрэгтэй вэ?» (not found) and «Хэдэн тэнхимтэй вэ?» (not found). v7 keeps every v6 record and adds:

- faq.admission.overview  — who may apply, registration, exams, essay, interview, confirmation; built from the
  admission facts already stored (each a clause copied word for word from the saved page or regulation page);
- faq.admission.documents — what to prepare (photo, details, essay, documents for schooling abroad), same facts;
- faq.school.departments  — the six departments, from the saved «Тэнхимүүд» page (checked word for word).

All records stay `draft`: assistant-curated from saved official clauses, not approved by the school.

    .venv/Scripts/python.exe tools/build_content_v7.py data/content-draft-v6-20261125.json \
        data/content-draft-v7-20261125.json --website-db <active release>/data/CORE/database/website.db
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from validate_content import validate_content  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_content_v4 import _flat, saved_texts  # noqa: E402
from build_content_v5 import SITE, _fact, _faq  # noqa: E402

NOTE = ('Assistant-curated FAQ (v7, 2026-11-25) from facts whose clauses are copied word for word from the saved '
        'official pages; not human gold or school staff approval; current validity unknown.')
DEPARTMENTS_SOURCE, DEPARTMENTS_URL = 'nmct-departments-web-20261007', 'https://nmct.edu.mn/departments'
ADMISSION = 'сургуулийн сайтын «Элсэлт 2026» хуудас, 2026–2027 оны элсэлтийн журам'

FACTS = [
    _fact('school.departments', 'nmct.school', 'departments', DEPARTMENTS_SOURCE, 'Тэнхимүүд',
          ['6 Тэнхим', 'Ерөнхий Эрдмийн тэнхим', 'Компьютерын ухааны тэнхим', 'Механик инженерийн тэнхим',
           'Барилгын дэд бүтцийн инженерийн тэнхим', 'Цахилгаан электроникийн инженерийн тэнхим', 'Химийн инженерийн тэнхим'],
          'Сургуулийн тэнхимүүдийн жагсаалт; сайтын «Тэнхимүүд» хуудас.'),
]
FAQS = [
    _faq('faq.admission.overview', 'Элсэхэд ямар шаардлагатай вэ?',
         ['Танай сургуульд яаж элсэх вэ?', 'Элсэлтийн шаардлага юу вэ?', 'Элсэхэд юу хэрэгтэй вэ?'],
         'Элсэлтийн шаардлага, алхам (2026–2027 оны элсэлтийн журам, 2026 оны элсэлтийн мэдээллээр):\n'
         '• Хэн бүртгүүлэх: 1-р курст ЕБС-ийн 9-р ангийг төгсөж суурь боловсролын гэрчилгээ авсан сурагч, 2-р курст '
         'ЕБС-ийн 10-р ангийг төгссөн сурагч.\n'
         '• Цахим бүртгэл: цээж зураг, иргэний болон холбоо барих мэдээллээ оруулж, сонирхож буй мэргэжлээ сонгон '
         'формоо бөглөнө; бүртгэлийн хураамж 20,000 төгрөг, QPay-ээр төлнө.\n'
         '• Бичгийн шалгалт (1-р курс): 120 минут, нийт 100 оноо — Математик 40, Физик 20, Хими 20, Эх хэл/монгол 10, '
         'Техник зураг 10.\n'
         '• Эссэ: 500–700 үгтэй, A4 цаасан дээр хэвлэж бичгийн шалгалтын өдөр биечлэн авчирна.\n'
         '• Ярилцлага: 15 минут, 20 оноо; эцэг эх, асран хамгаалагчтай хамт орно.\n'
         '• Элсэлт баталгаажих: сургуулиас товлосон хугацаанд суралцах гэрээ байгуулж, сургалтын төлбөрөө төлсний '
         'дараа.\n' + '(Эх сурвалж: ' + ADMISSION + '.)',
         ['admission.course_qualification.2026_2027', 'admission.online_registration_steps.2026',
          'admission.registration_fee.2026', 'admission.writing_exam.2026', 'admission.essay_rule.2026_2027',
          'admission.essay_format.2026', 'admission.interview.2026_2027', 'admission.enrollment_confirmation.2026_2027'],
         '2026 оны элсэлт ба 2026–2027 оны журмын шаардлага, алхам; дараагийн элсэлтийн огноо биш.'),
    _faq('faq.admission.documents', 'Элсэхэд ямар бичиг баримт хэрэгтэй вэ?',
         ['Элсэлтэд юу бүрдүүлэх вэ?', 'Элсэхэд ямар материал бүрдүүлэх вэ?'],
         'Элсэлтэд бүрдүүлэх зүйл (2026–2027 оны элсэлтийн журам, 2026 оны элсэлтийн мэдээллээр):\n'
         '• Цахим бүртгэлд: сүүлийн 6 сарын дотор авахуулсан цээж зураг (регистрийн дугаараараа нэрлэсэн jpeg, png '
         'эсвэл jpg файл), иргэний болон холбоо барих мэдээлэл.\n'
         '• Бичгийн шалгалтын өдөр: A4 цаасан дээр хэвлэсэн 500–700 үгтэй эссэ; гараар бичсэн эссэ хүлээж авахгүй.\n'
         '• Гадаадад ерөнхий боловсрол эзэмшсэн бол: ЕБС-тай дүйцүүлэх шалгалтыг гадаад оронд өгснийг гэрчилсэн '
         'баримт, БШУЯ-наас баталгаажуулсан тодорхойлолтыг Элсэлтийн комисст ирүүлнэ.\n'
         + '(Эх сурвалж: ' + ADMISSION + '.)',
         ['admission.photo_requirements.2026_2027', 'admission.online_registration_steps.2026',
          'admission.essay_rule.2026_2027', 'admission.essay_format.2026', 'admission.foreign_school_documents.2026_2027'],
         'Журам ба элсэлтийн хуудсанд нийтэлсэн бүрдүүлэх зүйл; бусад баримтын бүрэн жагсаалт биш.'),
    _faq('faq.school.departments', 'Сургууль хэдэн тэнхимтэй вэ?',
         ['Ямар ямар тэнхим байдаг вэ?', 'Сургуулийн тэнхимүүд'],
         'Сургууль 6 тэнхимтэй:\n• Ерөнхий эрдмийн тэнхим\n• Компьютерын ухааны тэнхим\n• Механик инженерийн тэнхим\n'
         '• Барилгын дэд бүтцийн инженерийн тэнхим\n• Цахилгаан электроникийн инженерийн тэнхим\n'
         '• Химийн инженерийн тэнхим\n' + SITE.format(page='Тэнхимүүд'),
         ['school.departments'], 'Тэнхимүүдийн жагсаалт.'),
]


def main(argv=None):
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('source', type=Path)
    parser.add_argument('target', type=Path)
    parser.add_argument('--website-db', type=Path, required=True)
    args = parser.parse_args(argv)
    content = json.loads(args.source.read_text(encoding='utf-8'))
    versions = {}
    for source in content['sources']:        # the newest stored version of each source
        versions[source['document_id']] = max(source['version'], versions.get(source['document_id'], 0))
    if DEPARTMENTS_SOURCE not in versions:
        raise SystemExit('Unknown source: ' + DEPARTMENTS_SOURCE)
    saved = saved_texts(args.website_db, [DEPARTMENTS_URL]).get(DEPARTMENTS_URL, '')
    problems = []
    for fact in FACTS:
        fact['source_refs'][0]['version'] = versions[DEPARTMENTS_SOURCE]
        fact['notes'] = 'Exact published clause(s) copied from the saved page (v7 build checks them).'
        problems += [f"{fact['fact_id']}: not in the saved text of {DEPARTMENTS_URL}: {clause}"
                     for clause in fact['value']['published_clauses'] if _flat(clause) not in saved]
    if problems:
        raise SystemExit('Clauses not found word for word:\n' + '\n'.join(problems))
    known = {fact['fact_id'] for fact in content['facts']} | {faq['faq_id'] for faq in content['faqs']}
    duplicates = [item for item in [fact['fact_id'] for fact in FACTS] + [faq['faq_id'] for faq in FAQS] if item in known]
    if duplicates:
        raise SystemExit('Already present: ' + ', '.join(duplicates))
    content['facts'].extend(FACTS)
    facts = {fact['fact_id']: fact for fact in content['facts']}
    missing = [fact_id for faq in FAQS for fact_id in faq['fact_ids'] if fact_id not in facts]
    if missing:
        raise SystemExit('Unknown facts: ' + ', '.join(missing))
    for faq in FAQS:
        faq['notes'] = NOTE
        refs = {}
        for fact_id in faq['fact_ids']:
            for ref in facts[fact_id]['source_refs']:
                refs[(ref['document_id'], ref['version'], ref['locator'])] = dict(ref)
        faq['source_refs'] = list(refs.values())
    content['faqs'].extend(FAQS)
    errors = validate_content(content)
    if errors:
        raise SystemExit('Invalid content:\n' + '\n'.join(errors))
    args.target.write_text(json.dumps(content, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'{args.target}: +{len(FACTS)} fact, +{len(FAQS)} FAQs; every new clause found word for word; validation OK')
    return 0


if __name__ == '__main__':
    sys.exit(main())
