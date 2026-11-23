"""Content v4 (2026-11-23): stored answers for the topics visitors ask about, in the source's own words.

The user, 11/23, after reading the system's answers to the 40 check questions («our answer is too short and
useful … make it good enough with those 40»): many answers said «мэдээлэл олдсонгүй» although the school's
pages hold the answer (the vaccinations of the 1st course, «ДЭЭРЭЛХЭЛТГҮЙ СУРГУУЛЬ», the career centre's
study and work paths, the campus, the olympiad and its tuition discounts, the banks for the registration fee).
v4 keeps every v3 record and adds one stored FAQ per such topic, each built from clauses copied from the
saved official pages (website snapshot of the active release) — the build stops if a clause is not found
there word for word (whitespace aside). The interview answer now uses the rule's own words («эцэг эх,
асран хамгаалагчтай хамт»). All records stay `draft`: assistant-curated from saved official clauses,
not approved by the school.

    .venv/Scripts/python.exe tools/build_content_v4.py data/content-draft-v3-20261123.json \
        data/content-draft-v4-20261123.json --website-db <active release>/data/CORE/database/website.db
"""
import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from validate_content import validate_content  # noqa: E402

NOTE = ('Assistant-curated FAQ (v4, 2026-11-23) from clauses copied word for word from the saved official '
        'page; not human gold or school staff approval; current validity unknown.')


def _source(document_id, title, url, retrieved_at, scope, notes):
    return dict(document_id=document_id, version=1, title=title, source_url_or_filename=url,
                retrieved_at=retrieved_at, source_updated_at=None, scope=scope,
                content_capture='selected_fact_extract', notes=notes, approval_status='draft',
                approved_by=None, approved_at=None, valid_from=None, valid_until=None)


SOURCES = [
    _source('nmct-career-center-web-20261109', 'Дэлхийд өрсөлдөх мэргэжилтний зам (Карьер хөгжлийн төв)',
            'https://nmct.edu.mn/career-center', '2026-11-09', 'Карьер хөгжлийн төвийн хуудас: дадлага, '
            'төгсөлтийн дараах зам, тоон үзүүлэлт', 'Хуудасны тоо нь сайтад нийтэлсэн тоо; хэмжсэн огноо заагаагүй.'),
    _source('nmct-environment-web-20261014', 'Суралцахад төгс орчин', 'https://nmct.edu.mn/about/environment',
            '2026-10-14', 'Сургалтын орчин: анги, лаборатори, лекцийн танхим, номын сан, хоолны газар',
            'Сайтад нийтэлсэн тоо, тайлбар.'),
    _source('nmct-child-protection-news-20261020', 'ХҮҮХЭД ХАМГААЛЛЫН АЖИЛ',
            'https://nmct.edu.mn/news/khuukhed-khamgaallyn-ajil', '2026-11-17',
            'Хүүхэд хамгааллын багийн ажил, 2026 оны аравдугаар сарын 20-ны мэдээ', 'Мэдээний огноо 2026-10-20.'),
    _source('nmct-health-news-20261029', 'Эрүүл мэндийн эрт илрүүлэг, дархлаажуулалтын ажлууд зохион байгуулагдлаа',
            'https://nmct.edu.mn/news/eruul-mendiin-ert-ilruuleg-darkhlaajuulaltyn-ajluud-zokhion-baiguulagdlaa',
            '2026-11-17', 'Оюутны эрүүл мэндийн ажил, 2026 оны аравдугаар сарын 29-ний мэдээ', 'Мэдээний огноо 2026-10-29.'),
    _source('nmct-language-levels-news-20260902', 'Сургалтын үйл ажиллааны мэдээлэл',
            'https://nmct.edu.mn/news/surgaltiin-uil-ajillagaanii-medeelel-01', '2026-11-17',
            'Түвшин тогтоох шалгалт, хэлний хичээлийн түвшин, 2026 оны есдүгээр сарын 2-ны мэдээ',
            'Мэдээний огноо 2026-09-02.'),
    _source('nmct-olympiad-web-20261010', 'Байгалийн ухааны VII олимпиад', 'https://nmct.edu.mn/olympiad',
            '2026-10-10', 'Сургуулийн нэрэмжит олимпиадын танилцуулга хуудас', 'Олимпиадын өдөр 2026-04-25.'),
]

# document_id -> the page or document whose saved text must hold each clause.
URLS = {source['document_id']: source['source_url_or_filename'] for source in SOURCES}
URLS.update({'nmct-olympiad-rule-snapshot-20261010': 'https://nmct.edu.mn/olympiad/o-2025-2026.pdf',
             'nmct-admission-rule-page2-snapshot-20261010': 'https://nmct.edu.mn/elseltiin-juram/page-2.png'})


def _fact(fact_id, entity, key, document_id, locator, clauses, scope, year=None):
    value = dict(published_clauses=clauses)
    if year:
        value['year_scope'] = year
    return dict(fact_id=fact_id, entity_id=entity, key=key, value=value,
                source_refs=[dict(document_id=document_id, version=None, locator=locator)], scope=scope,
                notes='Exact published clause(s) copied from the saved page (v4 build checks them).',
                approval_status='draft', approved_by=None, approved_at=None, valid_from=None, valid_until=None)


FACTS = [
    _fact('career.study_after_graduation', 'nmct.career', 'study_after_graduation', 'nmct-career-center-web-20261109',
          'ТӨГСӨЛТИЙН ДАРАА / Дэвшин сурах; ТЭТГЭЛЭГТ ХӨТӨЛБӨР',
          ['5-р курсийн төгсөлтийн дараах замууд Дэвшин сурах Дотоодын ТОП их сургуулийн 3-р курст Японы их '
           'сургуулийн 3-р курст ШМТДС, МУИС, ШУТИС, ХААИС, ҮБХИС Тоёохаши ТИС, Нагаока ТИС, Чиба ТИС Коосэн '
           'Сэнкока (6 Коосэн)',
           'Монбүшёо — Японы Засгийн газрын тэтгэлэг Сургалтын төлбөр, амьжиргааны зардал болон бусад холбогдох '
           'зардлыг 100% хариуцдаг тэтгэлэгт хөтөлбөр. Одоогоор 12 оюутан тус тэтгэлэгт хамрагдаад байна.'],
          'Төгсөлтийн дараах дэвшин суралцах зам, тэтгэлэг; хуудасны нийтэлсэн мэдээлэл.'),
    _fact('career.graduate_outcomes', 'nmct.career', 'graduate_outcomes', 'nmct-career-center-web-20261109',
          'ТООН ҮЗҮҮЛЭЛТ; СУРЧ, АЖИЛЛАЖ БУЙ БАЙДАЛ',
          ['178+ Японы компанид дадлага хийсэн оюутан Сүүлийн 3 жилд 183+ Төгсөгч мэргэжлээрээ ажиллаж байна '
           'Дотоод гадаадын компаниудад 107+ Япон улсад дэвшин суралцсан Их, дээд сургууль, коллеж',
           '20.9% Дотоодын их, дээд сургуульд элсэх 26.4% Япон улс болон бусад улсад суралцах 31.0% Дотоодын аж, '
           'ахуйн нэгжид ажиллах 21.6% Япон улс болон бусад улсад ажиллах'],
          'Сайтад нийтэлсэн тоон үзүүлэлт; хэмжсэн огноо, аргыг заагаагүй.'),
    _fact('career.internship_japan', 'nmct.career', 'internship_japan', 'nmct-career-center-web-20261109',
          'ДАДЛАГА ХӨТӨЛБӨР / Хэн хамрагдах вэ?',
          ['Ахлах курсийн оюутнууд карьерын төвөөр дамжуулан хүсэлтээ гарган, япон хэл дээр ярилцлага өгч, тэнцсэн '
           'тохиолдолд хамтын ажиллагаатай компаниудад 7–30 хоногийн хугацаанд дадлага хийх боломжтой. Өвлийн болон '
           'зуны амралтаар хамрагдана.'],
          'Японы компанид хийх дадлага.'),
    _fact('campus.facilities', 'nmct.campus', 'facilities', 'nmct-environment-web-20261014',
          'Тоон үзүүлэлт; I. Сургалтын орчин; Номын сан',
          ['25 Анги танхим 13 Лаборатори 2 Лекцийн танхим 3270+ Номын сан',
           '25 анги танхим 658 суудал',
           'Ухаалаг самбар 55″ / 65″ дэлгэц Утасгүй интернэт',
           '13 лаборатори 278 суудал Инженерийн 5 мэргэжил бүрийн онцлог, нийтлэг шаардлагад нийцүүлэн зориулалтын '
           'лаборатори, туршилт дадлагын өрөөнүүдийг ашиглаж байна.',
           '2 том танхим 242 суудал',
           '10 давхрын 593.11 м² талбай бүхий open space орчин. Koha олон улсын программыг 2016 оноос нэвтрүүлэн '
           'ашиглаж байна. Нэг оюутанд 5.2–7.9 ном ногдож байна. 3270+ ном, сурах бичиг'],
          'Сургалтын орчны нийтэлсэн тоо, тайлбар.'),
    _fact('campus.cafeteria', 'nmct.campus', 'cafeteria', 'nmct-environment-web-20261014', 'Нийтийн хоолны газар',
          ['Нийтийн хоолны газар Мэргэжлийн хоолзүйч 400 м² талбай бүхий үйлчилгээний танхим. Мэргэжлийн хоолзүйч '
           'ажиллаж, хоолны цэсийг сар бүрээр батлуулан, оюутан, багш нарт үйлчилдэг. 360 хүний суудал'],
          'Нийтийн хоолны газар; өнөөдрийн цэс, үнэ биш.'),
    _fact('student.anti_bullying', 'nmct.student', 'anti_bullying', 'nmct-child-protection-news-20261020',
          'Мэдээ, 2026-10-20',
          ['ШМТК-ийн 1-р курсийн оюутнуудад хүүхэд хамгааллын ажлын хүрээнд Баянзүрх дүүргийн Цагдаагийн газрын '
           '1-р хэлтсийн ахлагч А. Мөнхтөр “Үе тэнгийн дээрэлхэлт, зөрчлийн үйлдэл” сэдвээр мэдээлэл, яриа сургалт '
           'зохион байгууллаа.',
           'Энэ хичээлийн жилд Хүүхэд хамгааллын багаас “ДЭЭРЭЛХЭЛТГҮЙ СУРГУУЛЬ” уриалгыг дэвшүүлэн ажиллаж байна.',
           'Бидний зорилго бол оюутан бүр өөрийгөө аюулгүй, хүндлэгдсэн, хамгаалагдсан орчинд суралцах нөхцөлийг '
           'бүрдүүлэх юм.'],
          'Хүүхэд хамгааллын багийн 2026–2027 оны хичээлийн жилийн ажил.', '2026–2027'),
    _fact('student.health_programs', 'nmct.student', 'health_programs', 'nmct-health-news-20261029', 'Мэдээ, 2026-10-29',
          ['3 талт судалгаа | 1–3-р курс Оюутнуудын бие бялдрын хөгжил, физиологийн үзүүлэлт болон сэтгэл зүйн '
           'эрүүл мэндийг үнэлнэ. Эрүүл мэндийн үзлэг, эрт илрүүлэг | 1-р курс Өвчлөлөөс урьдчилан сэргийлэх, эрүүл '
           'мэндийн байдлыг эрт илрүүлэх үзлэг, шинжилгээнд хамруулна. Дархлаажуулалт | 1-р курс Сахуу, татран '
           'өвчнөөс урьдчилан сэргийлэх дархлаажуулалтад хамруулна.'],
          'Оюутны эрүүл мэндийн ажил (2026 оны намар).', '2026–2027'),
    _fact('study.language_levels', 'nmct.academics', 'language_levels', 'nmct-language-levels-news-20260902',
          'Мэдээ, 2026-09-02',
          ['ШМТК-ийн 2-4 курсийн оюутнууд Математик, Физик, Англи хэл, Япон хэлний хичээлүүдээр түвшин тогтоох '
           'шалгалт өгч байна. Манай сургуулийн Япон хэл, Англи хэлний хичээлүүд түвшинчилж явагддаг бөгөөд энэ нь '
           'оюутнуудын суралцах үр дүнг дээшлүүлэхэд ихээхэн ач холбогдолтой байдаг.'],
          'Хэлний хичээлийн түвшин, түвшин тогтоох шалгалт.', '2026–2027'),
    _fact('olympiad.overview.2025_2026', 'nmct.olympiad', 'overview.2025_2026', 'nmct-olympiad-web-20261010',
          'Олимпиадын хуудасны толгой',
          ['Шинэ Монгол Технологийн Коллежийн нэрэмжит Байгалийн ухааны VII олимпиад ЕБС-ийн 9-р ангийн сурагчдыг урьж байна.',
           'Бүртгэлийн хураамж 5,000 ₮ Математик / Физик Математик / Хими / Биологи Олимпиадын өдөр 4-р сарын 25 '
           'Байршил ШМТК-ийн байранд'],
          '2025–2026 оны VII олимпиад; дараагийн олимпиадын огноо биш.', '2025–2026'),
    _fact('olympiad.tuition_discount.2025_2026', 'nmct.olympiad', 'tuition_discount.2025_2026',
          'nmct-olympiad-rule-snapshot-20261010', 'х.2, Зургаа.А, математик-физикийн шагнал',
          ['Олимпиадын ангилал тус бүрээр 1-3-р байр, тусгай байрыг шалгаруулж, шагналт байранд орсон сурагчдыг Шинэ '
           'Монгол Технологийн коллежид 2026-2027 оны хичээлийн жилд сургалтын төлбөрийн 10-50%-ийн хөнгөлөлттэй '
           'суралцах эрхийн бичиг, дурсгалын зүйл, мөн амжилттай оролцсон тодорхой тооны сурагчдыг ШМТК-д бичгийн '
           'шалгалтгүй элсэх эрхийн бичгээр шагнаж урамшуулна.',
           'I байр - 1 сурагч, медаль, сургалтын төлбөрийн 50%-ийн хөнгөлөлтийн эрхийн бичиг II байр - 2 сурагч, '
           'медаль, сургалтын төлбөрийн 30%-ийн хөнгөлөлтийн эрхийн бичиг III байр - 3 сурагч, медаль, сургалтын '
           'төлбөрийн 20%-ийн хөнгөлөлтийн эрхийн бичиг Тусгай байр - 4 сурагч, сургалтын төлбөрийн 10%-ийн '
           'хөнгөлөлтийн эрхийн бичиг'],
          '2025–2026 оны олимпиадын шагналт байрны хөнгөлөлт (2026–2027 оны хичээлийн жилд); бусад хөнгөлөлт биш.',
          '2026–2027'),
    _fact('admission.fee_banks.2026_2027', 'nmct.admissions', 'fee_banks.2026_2027',
          'nmct-admission-rule-page2-snapshot-20261010', 'х.2, IV.11, бүртгэлийн хураамж төлөх',
          ['Цахимаар бүртгэл хийхдээ бүртгэлийн хураамж 20,000 төгрөгийг зааврын дагуу, QR код ашиглан Хаан банк, '
           'Төрийн банк, Худалдаа хөгжлийн банк, Хас банк, Богд банк, Улаанбаатар хотын банкны аппликейшн ашиглан '
           'төлнө (Голомт банкаар төлөх боломжгүй болно).'],
          '2026–2027 оны элсэлтийн бүртгэлийн хураамж төлөх банк; дансны дугаар биш.', '2026–2027'),
]


def _faq(faq_id, question, aliases, answer, fact_ids, scope):
    return dict(faq_id=faq_id, question=question, question_aliases=aliases, answer=answer, fact_ids=fact_ids,
                source_refs=None, scope=scope, answer_status='complete_in_scope', notes=NOTE,
                approval_status='draft', approved_by=None, approved_at=None, valid_from=None, valid_until=None)


FAQS = [
    _faq('faq.admission.fee_banks.2026_2027',
         '2026–2027 оны элсэлтийн бүртгэлийн хураамжийг ямар банкны аппликейшнаар төлөх вэ?',
         ['Элсэлтийн бүртгэлийн хураамжийг ямар банкаар төлж болох вэ?'],
         'Бүртгэлийн хураамж 20,000 төгрөгийг QR код ашиглан Хаан банк, Төрийн банк, Худалдаа хөгжлийн банк, Хас банк, '
         'Богд банк, Улаанбаатар хотын банкны аппликейшнаар төлнө. Голомт банкаар төлөх боломжгүй (2026–2027 оны '
         'элсэлтийн журам, IV.11).',
         ['admission.fee_banks.2026_2027'], '2026–2027 оны элсэлтийн бүртгэлийн хураамж төлөх банк; дансны дугаар биш.'),
    _faq('faq.olympiad.tuition_discount.2025_2026', 'Сургалтын төлбөрийн хөнгөлөлт байдаг уу?',
         ['Олимпиадад шалгарвал сургалтын төлбөрийн хөнгөлөлт авах уу?'],
         'Сургуулийн нэрэмжит Байгалийн ухааны VII олимпиадад (2025–2026) ангилал тус бүрт 1–3-р байр, тусгай байр '
         'эзэлсэн сурагчид 2026–2027 оны хичээлийн жилд сургалтын төлбөрийн 10–50%-ийн хөнгөлөлттэй суралцах эрхийн '
         'бичиг авна: I байр 50%, II байр 30%, III байр 20%, тусгай байр 10% (олимпиадын журам). Энэ бол олимпиадын '
         'шагналаар олгох хөнгөлөлт.',
         ['olympiad.tuition_discount.2025_2026'], 'Олимпиадын шагналт байрны хөнгөлөлт; бусад хөнгөлөлт биш.'),
    _faq('faq.study.language_levels', 'Япон хэл, Англи хэлний хичээл түвшингээр ордог уу?',
         ['Хэлний хичээлийг түвшинчилж заадаг уу?'],
         'Тийм. Япон хэл, Англи хэлний хичээлүүд түвшинчилж явагддаг. 2–4-р курсийн оюутнууд Математик, Физик, Англи '
         'хэл, Япон хэлний хичээлээр түвшин тогтоох шалгалт өгдөг (2026 оны есдүгээр сарын 2-ны мэдээ).',
         ['study.language_levels'], 'Хэлний хичээлийн түвшин.'),
    _faq('faq.career.study_in_japan', 'Төгсөөд Японд үргэлжлүүлэн суралцаж болох уу?',
         ['Төгсөгчид хаана дэвшин суралцдаг вэ?'],
         'Тийм. 5-р курсийн төгсөлтийн дараа Японы их сургуулийн 3-р курст (Тоёохаши ТИС, Нагаока ТИС, Чиба ТИС), '
         'Коосэн Сэнкокад (6 Коосэн) эсвэл дотоодын их сургуулийн 3-р курст (ШМТДС, МУИС, ШУТИС, ХААИС, ҮБХИС) дэвшин '
         'суралцаж болно. 107+ төгсөгч Япон улсад дэвшин суралцсан. Японы Засгийн газрын Монбүшёо тэтгэлэг сургалтын '
         'төлбөр, амьжиргааны зардлыг 100% хариуцдаг; одоогоор 12 оюутан хамрагдсан (Карьер хөгжлийн төвийн хуудас).',
         ['career.study_after_graduation', 'career.graduate_outcomes'],
         'Төгсөлтийн дараах дэвшин суралцах зам; элсэх шалгуур биш.'),
    _faq('faq.career.graduate_outcomes', 'Төгсөгчид мэргэжлээрээ ажилд ордог уу?',
         ['Төгсөгчид юу хийж байна вэ?'],
         'Тийм. Карьер хөгжлийн төвийн мэдээллээр 183+ төгсөгч дотоод, гадаадын компаниудад мэргэжлээрээ ажиллаж байна. '
         'Төгсөгчдийн 31.0% нь дотоодын аж ахуйн нэгжид, 21.6% нь Япон улс болон бусад улсад ажилладаг; 20.9% нь '
         'дотоодын их, дээд сургуульд, 26.4% нь Япон улс болон бусад улсад суралцдаг.',
         ['career.graduate_outcomes'], 'Төгсөгчдийн ажил, суралцах байдлын нийтэлсэн хувь; хэмжсэн огноо заагаагүй.'),
    _faq('faq.career.internship_japan', 'Японы компанид дадлага хийх боломжтой юу?',
         ['Японд дадлага хэдэн хоног үргэлжилдэг вэ?'],
         'Тийм. Ахлах курсийн оюутнууд карьерын төвөөр дамжуулан хүсэлтээ гаргаж, япон хэл дээр ярилцлага өгөөд тэнцвэл '
         'хамтын ажиллагаатай компаниудад 7–30 хоногийн хугацаанд дадлага хийнэ. Өвлийн болон зуны амралтаар хамрагдана. '
         'Сүүлийн 3 жилд 178+ оюутан Японы компанид дадлага хийсэн (Карьер хөгжлийн төвийн хуудас).',
         ['career.internship_japan', 'career.graduate_outcomes'], 'Японы компанид хийх дадлага.'),
    _faq('faq.campus.facilities', 'Сургалтын орчин ямар вэ?',
         ['Сургууль хэдэн лабораторитой вэ?', 'Номын сан ямар вэ?'],
         'Сургууль 25 анги танхим (658 суудал), 13 лаборатори (278 суудал), 2 лекцийн танхимтай (242 суудал). Анги '
         'танхимууд ухаалаг самбар, 55″/65″ дэлгэц, утасгүй интернэттэй; лабораториуд инженерийн 5 мэргэжлийн онцлогт '
         'нийцсэн. 10-р давхарт 593 м² номын сантай, 3270+ ном, сурах бичигтэй (Суралцахад төгс орчин хуудас).',
         ['campus.facilities'], 'Сургалтын орчны нийтэлсэн тоо.'),
    _faq('faq.campus.cafeteria', 'Сургуульд хоолны газар бий юу?', ['Хоолны газар хэдэн хүний суудалтай вэ?'],
         'Тийм. 400 м² талбай бүхий нийтийн хоолны газар 360 хүний суудалтай. Мэргэжлийн хоолзүйч ажиллаж, хоолны цэсийг '
         'сар бүр батлуулан оюутан, багш нарт үйлчилдэг (Суралцахад төгс орчин хуудас).',
         ['campus.cafeteria'], 'Нийтийн хоолны газар; өнөөдрийн цэс, үнэ биш.'),
    _faq('faq.student.anti_bullying', 'Сургууль дээрэлхэлтээс сэргийлэх ямар ажил хийдэг вэ?',
         ['Дээрэлхэлтийн асуудлыг сургууль яаж шийддэг вэ?'],
         'Сургуулийн Хүүхэд хамгааллын баг энэ хичээлийн жилд «ДЭЭРЭЛХЭЛТГҮЙ СУРГУУЛЬ» уриалгыг дэвшүүлэн ажиллаж байна. '
         '1-р курсийн оюутнуудад Баянзүрх дүүргийн Цагдаагийн газрын ахлагч «Үе тэнгийн дээрэлхэлт, зөрчлийн үйлдэл» '
         'сэдвээр сургалт хийсэн. Зорилго нь оюутан бүр аюулгүй, хүндлэгдсэн, хамгаалагдсан орчинд суралцах (2026 оны '
         'аравдугаар сарын 20-ны мэдээ).',
         ['student.anti_bullying'], 'Хүүхэд хамгааллын багийн ажил.'),
    _faq('faq.student.health_programs', '1-р курсийн оюутнуудад вакцин хийдэг үү?',
         ['Оюутнуудад эрүүл мэндийн үзлэг хийдэг үү?'],
         'Тийм. 1-р курсийн оюутнуудыг сахуу, татран өвчнөөс урьдчилан сэргийлэх дархлаажуулалтад хамруулдаг. Мөн 1-р '
         'курст эрүүл мэндийн үзлэг, эрт илрүүлэг хийж, 1–3-р курсийн оюутнуудын бие бялдар, сэтгэл зүйн эрүүл мэндийг '
         '3 талт судалгаагаар үнэлдэг (2026 оны аравдугаар сарын 29-ний мэдээ).',
         ['student.health_programs'], 'Оюутны эрүүл мэндийн ажил.'),
    _faq('faq.olympiad.overview.2025_2026', 'Танай сургууль 9-р ангийн сурагчдад олимпиад зохиодог уу?',
         ['Байгалийн ухааны олимпиад гэж юу вэ?'],
         'Тийм. ШМТК ЕБС-ийн 9-р ангийн сурагчдад зориулж Шинэ Монгол Технологийн Коллежийн нэрэмжит Байгалийн ухааны '
         'олимпиад зохиодог. VII олимпиад 2026 оны 4-р сарын 25-нд ШМТК-ийн байранд болсон; Математик/Физик, '
         'Математик/Хими/Биологи гэсэн хоёр ангилалтай, бүртгэлийн хураамж 5,000 төгрөг (олимпиадын хуудас).',
         ['olympiad.overview.2025_2026'], '2025–2026 оны VII олимпиад; дараагийн олимпиадын огноо биш.'),
    _faq('faq.admission.degree.2026_2027', 'Сургуулиа төгсөхөд ямар зэрэг, диплом авах вэ?',
         ['Төгсөхөд ямар диплом авах вэ?'],
         'Дэд бакалаврын зэрэг. ШМТК инженерийн 5 жилийн хөтөлбөрөөр дэд бакалаврын зэрэг олгодог (2026–2027 оны '
         'элсэлтийн журам, I.1).',
         ['admission.engineering_degree.2026_2027'], 'Олгох зэрэг.'),
]

ANSWERS = {
    'faq.admission.interview.2026_2027':
        'Ярилцлага 15 минут үргэлжилж, нийт 20 оноогоор дүгнэгдэнэ. Бүртгүүлэгч эцэг эх, асран хамгаалагчтай хамт '
        'ярилцлагын шалгалтад орно. Багш нар инженер технологийн мэргэжлээр суралцах сонирхол, хүсэл эрмэлзэл, өөрийгөө '
        'илэрхийлэх чадвар, эцэг эхийн хамтын ажиллагааг харж, бүртгүүлэгч бүртэй ярилцана (2026–2027 оны журам, V.4).',
}


def _flat(text):
    return ' '.join(str(text).split())


def saved_texts(database, urls):
    """The saved text of each page (latest version) or document (its passages), whitespace-flattened."""
    texts = {}
    with sqlite3.connect(f'file:{database}?mode=ro', uri=True) as connection:
        for url in set(urls):
            row = connection.execute('select text from pages where url=? order by version desc limit 1', (url,)).fetchone()
            if row:
                texts[url] = _flat(row[0])
                continue
            row = connection.execute('select payload_json from document_extractions where url=? order by version desc '
                                     'limit 1', (url,)).fetchone()
            if row:
                payload = json.loads(row[0])
                passages = payload.get('passages') or payload.get('sections') or []
                texts[url] = _flat(' '.join(str(item.get('text', '')) for item in passages if isinstance(item, dict))
                                   or json.dumps(payload, ensure_ascii=False))
    return texts


def main(argv=None):
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('source', type=Path)
    parser.add_argument('target', type=Path)
    parser.add_argument('--website-db', type=Path, required=True)
    args = parser.parse_args(argv)
    content = json.loads(args.source.read_text(encoding='utf-8'))
    versions = {source['document_id']: source['version'] for source in content['sources']}
    known = {source['document_id'] for source in content['sources']}
    for source in SOURCES:
        if source['document_id'] in known:
            raise SystemExit('Source already present: ' + source['document_id'])
        content['sources'].append(source)
        versions[source['document_id']] = source['version']
    texts = saved_texts(args.website_db, URLS.values())
    problems = []
    for fact in FACTS:
        ref = fact['source_refs'][0]
        ref['version'] = versions[ref['document_id']]
        saved = texts.get(URLS[ref['document_id']], '')
        for clause in fact['value']['published_clauses']:
            if _flat(clause) not in saved:
                problems.append(f"{fact['fact_id']}: clause not in the saved text of {URLS[ref['document_id']]}: "
                                f"{clause[:80]}…")
    if problems:
        raise SystemExit('Clauses not found word for word:\n' + '\n'.join(problems))
    content['facts'].extend(FACTS)
    facts = {fact['fact_id']: fact for fact in content['facts']}
    for faq in FAQS:
        refs = {}
        for fact_id in faq['fact_ids']:
            for ref in facts[fact_id]['source_refs']:
                refs[(ref['document_id'], ref['version'], ref['locator'])] = dict(ref)
        faq['source_refs'] = list(refs.values())
    known_faqs = {faq['faq_id'] for faq in content['faqs']}
    duplicates = [faq['faq_id'] for faq in FAQS if faq['faq_id'] in known_faqs]
    if duplicates:
        raise SystemExit('FAQ already present: ' + ', '.join(duplicates))
    content['faqs'].extend(FAQS)
    changed = set()
    for faq in content['faqs']:
        if faq['faq_id'] in ANSWERS:
            old = faq['answer']
            faq['answer'] = ANSWERS[faq['faq_id']]
            faq['notes'] = (faq['notes'].strip() + ' v3-ийн хариулт (2026-11-23-нд журмын үгээр солив): ' + old).strip()
            changed.add(faq['faq_id'])
    if changed != set(ANSWERS):
        raise SystemExit('Unknown FAQ IDs: ' + ', '.join(sorted(set(ANSWERS) - changed)))
    errors = validate_content(content)
    if errors:
        raise SystemExit('Invalid content:\n' + '\n'.join(errors))
    args.target.write_text(json.dumps(content, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'{args.target}: +{len(SOURCES)} sources, +{len(FACTS)} facts, +{len(FAQS)} FAQs, '
          f'{len(changed)} answer changed; every clause found word for word; validation OK')
    return 0


if __name__ == '__main__':
    sys.exit(main())
