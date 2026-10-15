"""Bounded query-to-evidence contracts for the captured school sources.

Exact lookups copy clauses; they are not a general semantic entailment model.
These rules are development changes. Unrecognised questions still use RAG.
"""
import re
from answer_contract import tuition_amount_query

_FIRST = r'(?<!\w)(?:1-р|нэгдүгээр|i)\s+курс'
_SECOND = r'(?<!\w)(?:2-р|хоёрдугаар|ii)\s+курс'

# These words describe the requested attribute, rather than identifying one
# department, scholarship or Japan pathway. Names come from the supplied
# source text; this list contains no answer values or scholarship names.
_SCOPE_GENERIC = frozenset('''энэ тэр аль ямар юу вэ бэ уу үү юм байна байгаа
оны онд он сарын сар жил жилийн хичээлийн эх эхийн хуудсанд хуудасны
мэдээлэл мэдээлсэн нийтэлсэн нийтлэгдсэн мэдээнд тухай талаар гэж гэсэн
хэд хэдэн хэддүгээр хэддүгээрийн хэр хэрхэн яаж өгөөч өгнө нэр нэрийг
имэйл имэйлийг мэйл утас холбоо барих тэнхим тэнхимийн эрхлэгч эрхлэгчийн
тэтгэлэг тэтгэлэгт тэтгэлгийн хөтөлбөр хөтөлбөрийн хөтөлбөрт
хамрагдах хамрагдаж хамрагддаг боломж боломжтой болзол нөхцөл шаардлага
шаардлагад шаардлагатай тавьдаг ямархуу курс курсийн курсийнхэн оюутан
оюутны оюутнууд сурагч сурагчид сургууль сургуулийн манай танай
япон японы японд улсын улс руу явах явахад хэл хэлний түвшин үргэлжлэх
үргэлжилдэг үргэлжилнэ вэ хоног хоногийн өдөр өдрийн хугацаа хугацааг
сарын дүн хэмжээ эхлэх олгох зарласан есдүгээр наймдугаар дөрөвдүгээр
болон ба тус бүр хувьд нь n jlpt eju'''.split())
_SCOPE_SUFFIXES = ('гийн', 'ийн', 'ын', 'аар', 'ээр', 'оор', 'өөр', 'аас', 'ээс', 'оос', 'өөс')


def _scope_words(text):
    words = set(re.findall(r'[^\W\d_]+', text.casefold())) - _SCOPE_GENERIC
    result = set()
    for word in words:
        for suffix in _SCOPE_SUFFIXES:
            if word.endswith(suffix) and len(word) - len(suffix) >= 4:
                word = word[:-len(suffix)]
                break
        if word not in _SCOPE_GENERIC:
            result.add(word)
    return result


def _literal_scope(query, sources):
    """A literal, non-generic query/source name overlap, not inferred NER."""
    query_words = _scope_words(query)
    return bool(query_words & _scope_words('\n'.join(
        source.get('title', '') + '\n' + source['text'] for source in sources)))


def _department_names(sources):
    names = []
    for source in sources:
        title = source.get('title', '').strip()
        if 'тэнхим' in title.casefold() and title.casefold() not in {'тэнхим', 'тэнхимүүд'}:
            if title not in names:
                names.append(title)
    return names


def department_evidence_sources(query, sources):
    """Keep one literally named department's staff evidence, when unambiguous.

    Only supplied source titles identify departments. This bounded lexical
    filter does not infer names from body text, URLs, dates or retrieval rank.
    Generic, comparative and multiple-department questions retain every source.
    """
    q = query.casefold()
    if ('тэнхим' not in q or not re.search(r'багш|эрхлэгч', q)
            or re.search(r'харьцуул|тэнхимүүд|бүх\s+тэнхим|бусад\s+тэнхим|өөр\s+тэнхим|хоёр\s+тэнхим', q)):
        return sources
    query_words = _scope_words(query)
    matches = {}
    for source in sources:
        title = source.get('title', '')
        if not isinstance(title, str) or 'тэнхим' not in title.casefold():
            continue
        named_words = {word for word in _scope_words(title) if not word.startswith('инженер')}
        if named_words and named_words <= query_words:
            key = ' '.join(title.casefold().split())
            matches.setdefault(key, set())
            if source.get('url'):
                matches[key].add(source['url'])
    if len(matches) != 1:
        return sources
    title, urls = next(iter(matches.items()))
    return [source for source in sources
            if source.get('url') in urls
            or ' '.join(source.get('title', '').casefold().split()) == title]


def registration_amount_query(query):
    q = query.casefold()
    return bool(re.search(r'бүртгэ|элс', q) and re.search(r'хураамж|бүртгэ\w*\s+төлбөр', q)
                and re.search(r'хэд|төгрөг|үнэ|хэмжээ', q))


def ambiguity(query, sources):
    q = query.casefold()
    text = '\n'.join(s['text'].casefold() for s in sources)
    if ('тэнхим' in q and 'эрхлэгч' in q and re.search(r'нэр|имэйл|мэйл|утас', q)
            and not _literal_scope(query, sources)):
        names = _department_names(sources)
        return ('Аль тэнхимийн эрхлэгчийн нэр, холбоо барих мэдээлэл хэрэгтэй вэ?'
                + (' ' + '; '.join(names[:5]) + '.' if names else ''), [])
    japan = bool(re.search(r'япон', q))
    pathway = bool(re.search(r'дадлаг|дэвшин|суралц|аялал|ажил(?:лах|д|длах)|танилцах', q))
    multiple = bool(re.search(r'харьцуул|хөтөлбөрүүд|бүх\s+тэтгэл|тэтгэлгүүд', q))
    if (japan and (re.search(r'хоног|хугацаа|үргэлжил|хэр удаан', q)
                   or ('хэл' in q and re.search(r'шаардлаг|түвшин', q)))
            and not pathway and not multiple and not _literal_scope(query, sources)):
        return ('Япон руу явах аль замыг асууж байна вэ: танилцах хөтөлбөр, дадлага, '
                'дэвшин суралцах эсвэл ажиллах уу? Хугацаа, хэлний шаардлага нь замаасаа хамаарна.', [])
    if ('тэтгэл' in q and re.search(r'курс|хамрагд|хамрагдах|шаардлаг|нөхцөл|дүн|хэмжээ|хугацаа|эхлэх|хэзээ|хэд', q)
            and not multiple and not _literal_scope(query, sources)):
        return ('Аль тэтгэлэгт хөтөлбөрийн тухай асууж байна вэ? Тэтгэлгийн нэрийг нэмж асууна уу; '
                'хамрагдах курс, нөхцөл нь хөтөлбөрөөсөө хамаарна.', [])
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
    if ('ханш' in q and re.search(r'өнөөдр|яг одоо|одоогийн|одоог|бодит цаг', q)):
        return 'current_exchange_rate'
    if ('лаборатор' in q and re.search(r'нээлттэй|ажиллах цаг|цагийн хуваарь|хэдээс|хэд хүртэл', q)
            and re.search(r'долоо хоног|өдр|хэдээс|хэд хүртэл|цагийн хуваарь', q)):
        return 'laboratory_opening_hours'
    if (re.search(r'давж\s+заалд|гомдол\s+гарга', q)
            and re.search(r'хоног|өдөр|хугацаа|хэзээ', q)):
        return 'appeal_deadline'
    if ('цалин' in q and re.search(r'баталгаат|баталгаатай|заавал|батлан', q)):
        return 'guaranteed_salary'
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
    'current_exchange_rate': 'өнөөдрийн бодит валютын ханш',
    'laboratory_opening_hours': 'лабораторийн нээлттэй өдөр, цагийн хуваарь',
    'appeal_deadline': 'давж заалдах/гомдол гаргах хугацаа',
    'guaranteed_salary': 'баталгаатай олгох цалингийн хэмжээ, нөхцөл',
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
    if field == 'current_exchange_rate':
        # A captured conversion, even with a date or the word "today", cannot
        # establish a live rate. This application has no live FX evidence tool.
        return False
    for clause in re.split(r'\n|(?<=[.!?])\s+', text.casefold()):
        if (field == 'laboratory_opening_hours' and 'лаборатор' in clause
                and re.search(r'нээлттэй|ажилла(?:х|на|даг)|цагийн хуваарь', clause)
                and re.search(r'даваа|мягмар|лхагва|пүрэв|баасан|бямба|ням|өдөр бүр|өдрүүд', clause)
                and re.search(r'\d{1,2}[:.]\d{2}|\d+\s*цагаас|\d+\s*цаг хүртэл', clause)):
            return True
        if (field == 'appeal_deadline' and re.search(r'давж\s+заалд|гомдол\s+гарга', clause)
                and re.search(r'\d+\s*(?:ажлын\s+)?(?:хоног|өдөр)|\d{1,2}[:/]\d{1,2}|\d+\s*сарын\s*\d+', clause)):
            return True
        if (field == 'guaranteed_salary' and 'цалин' in clause
                and re.search(r'баталгаат|баталгаатай|заавал|батлан', clause)
                and not re.search(r'баталгаагүй|баталгаатай\s+(?:биш|гэж.{0,20}болохгүй)', clause)
                and re.search(r'\d+(?:[.,]\d+)*\s*(?:иен|төгрөг|₮|доллар|usd|jpy|mnt)', clause)):
            return True
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
        # Canonical clarification choice: copy a labelled amount from its
        # actual olympiad source. Year evidence is checked upstream. Do not
        # reuse this for deadline, monthly, negative or conditional queries.
        if re.fullmatch(r"(?:(?:19|20)\d{2}(?:\s*[–—-]\s*(?:19|20)\d{2})?\s+оны\s+)?"
                        r"олимпиадын\s+бүртгэлийн\s+хураамж\s+хэд\s+вэ[?!.]*", q):
            if source['url'] == 'https://nmct.edu.mn/olympiad':
                match = re.search(r'Бүртгэлийн хураамж\n\d+(?:[.,]\d+)*\s*(?:₮|төгрөг)(?=\n|$)', text)
            elif (visual and source['url'].startswith('https://nmct.edu.mn/olympiad/')
                  and text.startswith('Тус олимпиад нь')):
                match = re.search(r'Тус олимпиад нь[^\n]*бүртгэлийн хураамж\s+\d+(?:[.,]\d+)*\s*төгрөг[^\n]*', text)
            if match and len(match.group()) <= 1500:
                return source, match.group()
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
