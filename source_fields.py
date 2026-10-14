"""Bounded query-to-evidence contracts for the captured school sources.

Exact lookups copy clauses; they are not a general semantic entailment model.
These rules are development changes. Unrecognised questions still use RAG.
"""
import re
from answer_contract import tuition_amount_query

_FIRST = r'(?<!\w)(?:1-р|нэгдүгээр|i)\s+курс'
_SECOND = r'(?<!\w)(?:2-р|хоёрдугаар|ii)\s+курс'


def registration_amount_query(query):
    q = query.casefold()
    return bool(re.search(r'бүртгэ|элс', q) and re.search(r'хураамж|бүртгэ\w*\s+төлбөр', q)
                and re.search(r'хэд|төгрөг|үнэ|хэмжээ', q))


def ambiguity(query, sources):
    q = query.casefold()
    text = '\n'.join(s['text'].casefold() for s in sources)
    if ('бүртгэ' in q and 'хураамч' in q and re.search(r'хэд|төгрөг', q)):
        return ('Бүртгэлийн хураамжийн тухай асууж байна уу? Элсэлтийн эсвэл олимпиадын бүртгэл үү?',
                ['Элсэлтийн бүртгэлийн хураамж хэд вэ?', 'Олимпиадын бүртгэлийн хураамж хэд вэ?'])
    if ('гадаад' in q and re.search(r'ерөнхий боловсрол|ебс', q) and 'бүрдүүл' in q
            and 'байр' in q and 'баримт' not in q):
        return ('Ямар баримт бүрдүүлэхийг асууж байна уу, эсвэл хаана өгөх байршлыг асууж байна уу?',
                ['Гадаадад ЕБС төгссөн элсэгч ямар баримт бүрдүүлэх вэ?',
                 'Гадаадад ЕБС төгссөн элсэгч баримтаа хаана ирүүлэх вэ?'])
    if ('гадаад' in q and re.search(r'баримт|тодорхойлолт', q) and 'ярилцлаг' in q):
        return ('Баримт бичиг болон ярилцлагын тухай хоёр асуултыг тус тусад нь тодруулж асууна уу.',
                ['Гадаадад ЕБС төгссөн элсэгч ямар баримт өгөх вэ?', 'Ярилцлагын нийт оноо хэд вэ?'])
    exam_kind = re.search(r'бичгийн|ярилцлаг|олимпиад', q)
    if ('шалгалт' in q and not exam_kind and
            re.search(r'минут|хугацаа|хэр удаан', q) and
            'бичгийн' in text and 'ярилцлаг' in text):
        return ('Аль шалгалтын үргэлжлэх хугацааг асууж байна вэ?',
                ['Элсэлтийн бичгийн шалгалт хэдэн минут вэ?', 'Ярилцлагын шалгалт хэдэн минут вэ?',
                 'Олимпиадын шалгалт хэдэн минут вэ?'])
    if ('шалгалт' in q and re.search(r'дүн|хариу', q) and
            not re.search(r'элс|ярилцлаг|олимпиад|бичгийн', q)):
        return ('Элсэлтийн шалгалтын дүн үү, эсвэл олимпиадын дүн үү? Аль оныг сонирхож байна вэ?',
                ['2026 оны элсэлтийн нэгдсэн дүнг хаана зарлах вэ?',
                 '2026 оны олимпиадын дүнг хаана зарлах вэ?'])
    if ('шилжи' in q and re.search(r'индекс|код', q) and
            not re.search(r'механик|хими|цахилгаан|барилг|компьютер', q) and
            'шилжин' in text and 'механик' in text and 'хими' in text):
        return ('Шилжин элсэхэд аль хөтөлбөрийн индекс хэрэгтэй вэ?',
                ['Шилжин элсэх механик инженерийн индекс юу вэ?',
                 'Шилжин элсэх химийн инженерийн индекс юу вэ?'])
    if ('олимпиад' in q and not re.search(r'физик|биолог|хими', q) and
            (re.search(r'хоёрдугаар|2-р|ii байр', q) and re.search(r'хэд|тоо', q)
             or ('эрхийн бич' in q and re.search(r'мэргэж|хөтөлбөр|анги', q)))):
        return ('Олимпиадын аль төрөлд, хэддүгээр байрт орсон эрхийн бичиг вэ? Төрөл, байрнаас нөхцөл нь хамаарна.',
                ['Математик-физикийн олимпиадын хоёрдугаар байрны шагнал юу вэ?',
                 'Математик-хими-биологийн олимпиадын эрхийн бичгийн нөхцөл юу вэ?'])
    return None


def requested_detail(query):
    """Return a narrow missing-field screen, not an automatic truth label."""
    q = query.casefold()
    if re.search(r'элсэлтийн\s+(?:алб|комисс)', q) and re.search(r'утас|имэйл|мэйл', q):
        return 'admission_office_contact'
    if registration_amount_query(query):
        return 'registration_amount'
    if 'эсс' in q and re.search(r'фонт|пункт|үсгийн хэмжээ', q):
        return 'essay_font'
    if re.search(r'зур(?:аг|г)', q) and re.search(r'\bmb\b|мегабайт|файлын.*хэмжээ', q):
        return 'photo_file_size'
    if 'sql' in q and 'долоо хоног' in q and re.search(r'цаг|минут', q):
        return 'sql_weekly_hours'
    if ('долоо хоног' in q and re.search(r'цаг|минут', q)
            and re.search(r'хөтөлбөр|хичээл|үзэх|судлах', q)):
        return 'course_weekly_hours'
    if 'сургалтын төлбөр' in q and re.search(r'хувааж|хуваар|хуваан|сар бүр.*төл|сараар.*төл', q):
        return 'tuition_instalments'
    if ('олимпиад' in q and re.search(r'хөнгөлөлт|50', q) and
            re.search(r'таван жил|5 жил|тасралтгүй|сунга|жил бүр', q)):
        return 'award_renewal'
    return None


DETAIL_LABELS = {
    'registration_amount': 'бүртгэлийн хураамжийн дүн',
    'admission_office_contact': 'элсэлтийн алба/комиссын холбоо барих мэдээлэл',
    'essay_font': 'эссэний фонт, үсгийн пунктын шаардлага',
    'photo_file_size': 'цээж зургийн файлын MB хэмжээний хязгаар',
    'sql_weekly_hours': 'SQL-ийн долоо хоногийн хичээлийн цаг',
    'course_weekly_hours': 'хөтөлбөр/хичээлийн долоо хоногийн цаг',
    'tuition_instalments': 'сургалтын төлбөрийг сараар хувааж төлөх хуваарь',
    'award_renewal': 'олимпиадын хөнгөлөлтийг дараагийн жилүүдэд сунгах нөхцөл',
}


def detail_supported(field, text):
    # Require the requested field together with its value/condition in a clause.
    # Nearby programme duration, A4 format and word count are not substitutes.
    if field == 'registration_amount':
        return bool(re.search(r'бүртгэлийн\s+хураамж\w*[:\s]*\d+(?:[.,]\d+)*\s*(?:төгрөг|₮)', text.casefold()))
    for clause in re.split(r'\n|(?<=[.!?])\s+', text.casefold()):
        if (field == 'admission_office_contact' and re.search(r'элсэлтийн\s+(?:алб|комисс)', clause)
                and re.search(r'утас|имэйл|мэйл', clause) and re.search(r'\d|@', clause)):
            return True
        if field == 'essay_font' and re.search(r'фонт|пункт|үсгийн хэмжээ', clause) and re.search(r'\d|times|arial|үсэг', clause):
            return True
        if field == 'photo_file_size' and re.search(r'зур(?:аг|г)', clause) and re.search(r'\d+\s*(?:mb|мегабайт)', clause):
            return True
        if (field == 'sql_weekly_hours' and 'sql' in clause and 'долоо хоног' in clause
                and re.search(r'\d+\s*(?:цаг|минут)', clause)):
            return True
        if (field == 'course_weekly_hours' and 'долоо хоног' in clause
                and re.search(r'хичээл|хөтөлбөр', clause) and re.search(r'\d+\s*(?:цаг|минут)', clause)):
            return True
        if (field == 'tuition_instalments' and 'сургалтын төлбөр' in clause
                and re.search(r'сар|хувааж|хуваан', clause) and re.search(r'төлнө|төлөх|болно|хуваарь', clause)):
            return True
        if (field == 'award_renewal' and re.search(r'хөнгөлөлт|тэтгэл', clause)
                and re.search(r'сунга|жил бүр|таван жил|5 жил|дараагийн жил', clause)):
            return True
    return False


def field_extract(query, sources):
    """Select literal spans by the requested field and source section labels.

    No answer amounts, programme codes or dates are stored in these rules.
    Conditions remain in the copied clause. Title/year provenance is separate.
    """
    q = query.casefold()
    for source in sources:
        text = source['text']
        visual = source.get('text_scope') == 'document_visual_excerpt'
        match = None
        if visual:
            if ('гадаад' in q and re.search(r'ебс|ерөнхий боловсрол|суурь боловсрол', q)
                    and re.search(r'баримт|тодорхойлолт', q) and not re.search(r'их сургууль|дадлага', q)
                    and text.startswith('Гадаад оронд ерөнхий боловсрол')):
                return source, text
            if (re.search(_FIRST, q) and re.search(r'анги|гэрчилгээ', q)
                    and text.startswith('1-р курст Бүртгүүлэгч')):
                return source, text
            if (re.search(r'инженер|үндсэн хөтөлбөр', q) and re.search(r'хэдэн жил|үргэлжил|хугацаа', q)
                    and not re.search(r'долоо хоног|sql|ярилцлаг|бичгийн|шилжи', q)
                    and not re.search(_SECOND, q)
                    and text.startswith('ШМТК нь инженерийн')):
                return source, text
            if ('ярилцлаг' in q and re.search(r'шалгах|шалгаж|шалгадаг|сонирхол|чадвар|үнэл', q)
                    and not re.search(r'бичгийн|дүн|хариу|эхлэх|хугацаа|босго', q)
                    and text.startswith('Ярилцлагын шалгалтаар')):
                return source, text
            if (re.search(r'бүртгэ|элс', q) and re.search(r'банк|апп|qr', q)
                    and re.search(r'хураамж|төл', q)
                    and text.startswith('Цахимаар бүртгэл хийхдээ бүртгэлийн хураамж')):
                return source, text
            if ('эсс' in q and re.search(r'сэд(?:эв|в)|асуулт', q)
                    and text.startswith('Бүртгүүлэгч бичгийн шалгалтад ирэхдээ дараах асуултад')):
                return source, text
            if ('ярилцлаг' in q and 'хуваар' in q and re.search(r'хаана|хаанаас|авах|хэвл', q)):
                match = re.search(r'ЯРИЛЦЛАГЫН ШАЛГАЛТЫН ХУВААРИЙГ[^\n]+', text)
            elif ('элс' in q and re.search(r'нэгдсэн дүн|дүнг.*зарла|дүнгээ', q)):
                match = re.search(r'Шалгалтын нэгдсэн дүнг[^\n]+', text)
            elif ('элс' in q and re.search(r'баталгааж|гэрээ', q) and not registration_amount_query(query)
                    and text.startswith('Элсэгч сургуулиас товлосон')):
                return source, text
            elif 'олимпиад' in q:
                if re.search(r'анги|оролцох эрх|оролцогч', q) and not re.search(r'эрхийн бич|сонгох', q):
                    match = re.search(r'Тус олимпиад нь[^\n]+', text)
                elif 'бүртгэ' in q and re.search(r'хэдн|хэзээ|хугацаа|цаг|сарын', q):
                    match = re.search(r'Олимпиадад оролцогчдыг[^\n]+', text)
                elif re.search(r'шагнал|шагналыг', q) and re.search(r'гардуул|өрөө|тоот', q):
                    match = re.search(r'Шагналт байр эзэлсэн сурагчдад шагналыг[^\n]+', text)
        if source['url'] == 'https://nmct.edu.mn/elselt':
            if 'бичгийн' in q and re.search(r'оноо|минут|үргэлжил|хэр удаан|хугацаа', q) and not re.search(r'дүн|хариу|босго|тэнцэх', q):
                # Includes the separately labelled interview score; never sums it.
                match = re.search(r'Бичгийн шалгалт\n1-р курс[^\n]+\nНийт[^\n]+\n(?:[^\n]+\n)*?Ярилцлага[^\n]+', text)
            elif (re.search(r'хөтөлбөр|мэргэж', q) and re.search(r'индекс|код', q)
                    and re.search(_FIRST, q)):
                match = re.search(r'1-р курс ·[^\n]+\n.+?(?=\n2-р курс шилжин)', text, re.S)
            elif (('шилжи' in q or re.search(_SECOND, q)) and re.search(r'хөтөлбөр|мэргэж|индекс|код|хэдэн жил', q)):
                match = re.search(r'2-р курс шилжин ·[^\n]+\n.+?(?=\nБичгийн шалгалт)', text, re.S)
            elif tuition_amount_query(query):
                match = re.search(r'Сургалтын төлбөр:[^\n]+', text)
            elif ('эсс' in q and re.search(r'гараар|хэвл|a4|цаас|авч ир', q)
                    and not re.search(r'фонт|пункт|үсгийн хэмжээ', q)):
                match = re.search(r'Анхаарах: Эссэгээ[^\n]+', text)
        if (visual and 'бүртгэ' in q and re.search(r'хураамж|төлбөр', q)
                and re.search(r'хэд|төгрөг|хэмжээ', q) and 'элс' in q
                and text.startswith('Цахимаар бүртгэл хийхдээ бүртгэлийн хураамж')):
            return source, text
        if match and len(match.group()) <= 1500:
            return source, match.group()
    return None
