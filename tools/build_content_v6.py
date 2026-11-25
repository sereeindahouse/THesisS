"""Content v6 (2026-11-25): one more stored answer — what a graduate can do after the fifth year.

Reading real replies after v5 showed «Цахилгааны инженер мэргэжлээр төгсөөд юу хийх вэ?» answered with another
department's list of companies, and then with a news item about a business trip. The career page has a section
for exactly that question («5-р курсийн төгсөлтийн дараах замууд»): three paths, each a short list. v6 keeps every
v5 record and adds that section as one fact (every line copied word for word; the build stops when a line is not
in the saved page) and one stored answer made of those lines. The record stays `draft`: assistant-curated from
saved official clauses, not approved by the school.

    .venv/Scripts/python.exe tools/build_content_v6.py data/content-draft-v5-20261125.json \
        data/content-draft-v6-20261125.json --website-db <active release>/data/CORE/database/website.db
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

SOURCE, URL = 'nmct-career-center-web-20261109', 'https://nmct.edu.mn/career-center'
NOTE = ('Assistant-curated FAQ (v6, 2026-11-25) from clauses copied word for word from the saved official '
        'page; not human gold or school staff approval; current validity unknown.')

FACTS = [
    _fact('career.after_graduation_paths', 'nmct.career', 'after_graduation_paths', SOURCE,
          'ТӨГСӨЛТИЙН ДАРАА / 5-р курсийн төгсөлтийн дараах замууд',
          ['5-р курсийн төгсөлтийн дараах замууд',
           'Дэвшин сурах', 'Дотоодын ТОП их сургуулийн 3-р курст', 'Японы их сургуулийн 3-р курст',
           'ШМТДС, МУИС, ШУТИС, ХААИС, ҮБХИС', 'Тоёохаши ТИС, Нагаока ТИС, Чиба ТИС', 'Коосэн Сэнкока (6 Коосэн)',
           'Мэргэжлээрээ ажиллах', 'Дотоодын ТОП аж ахуйн нэгжүүдэд', 'Японы компани (ХИ, ЦЭИ, МИ, БДБИ, IT)',
           'Япон улсад үндсэн ажилтнаар', 'Инженерийн мэргэжлээр',
           'Бусад сонголт', 'АНУ', 'Бүгд Найрамдах Солонгос Улс', 'Канад', 'Засгийн газрын тэтгэлэгүүд'],
          'Тавдугаар курс төгссөний дараах замууд; сайтын жагсаалтын үг.'),
]
FAQS = [
    _faq('faq.career.after_graduation', '5-р курс төгссөний дараа ямар зам байдаг вэ?',
         ['Төгсөөд юу хийх вэ?', 'Төгссөний дараа ямар боломж байдаг вэ?', 'Төгсөөд хаана ажиллах вэ?',
          'Төгсөөд хаана үргэлжлүүлэн суралцах вэ?'],
         '5-р курсийн төгсөлтийн дараах гурван зам бий:\n'
         '• Дэвшин сурах — дотоодын ТОП их сургуулийн 3-р курст (ШМТДС, МУИС, ШУТИС, ХААИС, ҮБХИС); Японы их '
         'сургуулийн 3-р курст (Тоёохаши ТИС, Нагаока ТИС, Чиба ТИС); Коосэн Сэнкока (6 Коосэн).\n'
         '• Мэргэжлээрээ ажиллах — дотоодын ТОП аж ахуйн нэгжүүдэд; Японы компани (ХИ, ЦЭИ, МИ, БДБИ, IT); Япон '
         'улсад үндсэн ажилтнаар; инженерийн мэргэжлээр.\n'
         '• Бусад сонголт — АНУ, Бүгд Найрамдах Солонгос Улс, Канад; Засгийн газрын тэтгэлэгүүд.\n'
         + SITE.format(page='Карьер хөгжлийн төв'),
         ['career.after_graduation_paths'], 'Төгсөлтийн дараах замуудын жагсаалт; хүн бүрийн үр дүн биш.'),
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
    if SOURCE not in versions:
        raise SystemExit('Unknown source: ' + SOURCE)
    saved = saved_texts(args.website_db, [URL]).get(URL, '')
    problems = []
    for fact in FACTS:
        fact['source_refs'][0]['version'] = versions[SOURCE]
        fact['notes'] = 'Exact published clause(s) copied from the saved page (v6 build checks them).'
        problems += [f"{fact['fact_id']}: not in the saved text of {URL}: {clause}"
                     for clause in fact['value']['published_clauses'] if _flat(clause) not in saved]
    if problems:
        raise SystemExit('Clauses not found word for word:\n' + '\n'.join(problems))
    known = {fact['fact_id'] for fact in content['facts']} | {faq['faq_id'] for faq in content['faqs']}
    duplicates = [item for item in [fact['fact_id'] for fact in FACTS] + [faq['faq_id'] for faq in FAQS] if item in known]
    if duplicates:
        raise SystemExit('Already present: ' + ', '.join(duplicates))
    content['facts'].extend(FACTS)
    facts = {fact['fact_id']: fact for fact in content['facts']}
    for faq in FAQS:
        faq['notes'] = NOTE
        faq['source_refs'] = [dict(ref) for fact_id in faq['fact_ids'] for ref in facts[fact_id]['source_refs']]
    content['faqs'].extend(FAQS)
    errors = validate_content(content)
    if errors:
        raise SystemExit('Invalid content:\n' + '\n'.join(errors))
    args.target.write_text(json.dumps(content, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'{args.target}: +{len(FACTS)} fact, +{len(FAQS)} FAQ; every clause found word for word; validation OK')
    return 0


if __name__ == '__main__':
    sys.exit(main())
