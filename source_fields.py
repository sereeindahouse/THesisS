"""Bounded query-to-evidence contracts for the captured school sources.

Exact lookups copy clauses; they are not a general semantic entailment model.
These rules are development changes. Unrecognised questions still use RAG.
"""
import re
from answer_contract import tuition_amount_query, tuition_label_query
from evidence_contract import direction_card_bindings
from historical_fields import event_requirements, event_supported

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
_SCOPE_GENERIC = _SCOPE_GENERIC | frozenset('''багш багшийн багштай сургалт сургалтын
амьжиргаа амьжиргааны зардал зардлыг бүх даах даадаг хариуцдаг санхүүжүүлэх
санхүүжүүлдэг төлөх төлдөг төлнө хамрах хамардаг'''.split())
_SCOPE_GENERIC = _SCOPE_GENERIC | frozenset('''нийт үндсэн туслах цагийн доктор
магистр бүрэлдэхүүн бүрэлдэхүүнтэй ажилладаг бүрэн хувь хувийг хувиар
санхүүжилт санхүүжилтийн'''.split())
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


_PROGRAM_GENERIC_WORDS = frozenset(('ямар', 'аль', 'энэ', 'тэр', 'ашигладаг', 'ашиглаж',
                                   'ашиглах', 'ашигласан', 'ашиглагддаг', 'хэрэглэдэг',
                                   'хэрэглэж', 'хэрэглэх', 'одоогийн', 'байгаа', 'шинэ',
                                   'хуучин', 'суурилуулсан', 'нэвтрүүлсэн', 'номын',
                                   'сангийн', 'олон', 'улсын', 'болон', 'ба', 'мөн'))


def _program_name_key(name):
    return re.sub(r'-(?:ийн|ын|гийн|ыг|ийг|г)$', '', name.casefold())


def _queried_library_program(query, conjunction_only=False):
    prefix = r'(?:болон|\bба\b|\bмөн\b)\s+' if conjunction_only else r'(?<!\w)'
    pattern = prefix + r'(?P<name>[\w.+-]+)\s+программ?\w*'
    for match in re.finditer(pattern, query, re.I):
        if match['name'].casefold() not in _PROGRAM_GENERIC_WORDS:
            return match['name'], match.start('name'), match.end('name')
    # A literal Latin name may carry a Mongolian case suffix, with an explicit
    # date question between the name and its use/start verb. This recognises
    # query syntax only: a matching named programme must still exist in the
    # supplied evidence. Never infer a default programme from a library query.
    match = re.search(
        prefix + r'(?P<name>[A-Za-z][A-Za-z0-9.+-]+)'
        r'(?:-(?:ийн|ын|гийн|ыг|ийг|г))?\s+'
        r'(?:(?:хэдэн\s+он(?:оос|д)|хэзээ(?:нээс)?)\s+)?'
        r'(?:ашигл|нэвтрүүл|хэрэгл)', query, re.I)
    if match:
        return match['name'], match.start('name'), match.end('name')
    return None


def _library_program_names(sources):
    names = []
    for source in sources:
        text = source['text']
        if not re.search(r'номын\s+сан', text + '\n' + source.get('title', ''), re.I):
            continue
        # Only literal labelled names from these supplied sources. No fuzzy
        # matching, spelling aliases, transliteration or default programme.
        for match in re.finditer(r'(?<!\w)([A-Za-z][A-Za-z0-9.+-]+|[А-ЯӨҮЁ][а-яөүё0-9.+-]+)'
                                 r'\s+(?:олон\s+улсын\s+)?программ?\w*', text):
            name = match.group(1)
            if name.casefold() not in _PROGRAM_GENERIC_WORDS and name not in names:
                names.append(name)
    return names


def department_evidence_sources(query, sources, *, all_attributes=False):
    """Keep one literally named department's evidence, when unambiguous.

    Only supplied source titles identify departments. This bounded lexical
    filter does not infer names from body text, URLs, dates or retrieval rank.
    Generic, comparative and multiple-department questions retain every source.
    """
    q = query.casefold()
    if ('тэнхим' not in q or not (all_attributes or re.search(r'багш|эрхлэгч', q))
            or re.search(r'харьцуул|тэнхимүүд|бүх\s+тэнхим|бусад\s+тэнхим|өөр\s+тэнхим|хоёр\s+тэнхим', q)):
        return sources
    query_words = _scope_words(query)
    matches = {}
    for source in sources:
        # Extracted client fields add a method suffix to the same page title.
        # That suffix is metadata, never part of the department's name.
        title = source.get('title', '').split(' — ', 1)[0]
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
            or ' '.join(source.get('title', '').split(' — ', 1)[0].casefold().split()) == title]


def staff_query_scope(query, sources, *, catalog=None):
    """Bound staff requests to literal departments, named people and fields.

    The catalogue contributes titles only, never answer text. A short department
    name may identify a department only when that word is unique across all
    supplied department titles. A teacher name needs a local teacher-role
    assertion: an identically named student's patronymic is insufficient.
    """
    q = query.casefold()
    if not re.search(r'(?<!\w)(?:багш\w*|эрхлэгч\w*)(?!\w)', q):
        return None
    count = bool(re.search(r'хэд(?:эн)?\s+(?:(?:үндсэн|цагийн|туслах)\s+)?багш|'
        r'багш\w*(?:\s+нар\w*)?\s+(?:нийт\s+)?хэд(?:эн)?\b|багш\w*(?:\s+нар\w*)?\s+тоо', q))
    names = bool(re.search(r'нэр(?:с(?:ийг|ийн)?|ийг|үүд(?:ийг|ийн)?)?\b|хэн\s+хэн|ямар\s+багш', q))
    overview = bool(re.search(r'мэдээлэл|танилцуул|тухай|талаар|хэн\s+бэ|хэн\s+байдаг|хэн\s+юм|зураг|зургийг|хөрөг', q)
        or re.fullmatch(r'\s*багш(?:ийн|нар(?:ын)?)?(?:\s+нар(?:ын)?)?\s*[?!.]*', q))
    head = bool(re.search(r'эрхлэгч', q))
    if not (count or names or overview or head):
        # A named teacher's requested subject/qualification still needs identity.
        if not re.search(r'\b[А-ЯӨҮЁ][а-яөүё-]+\s+багш', query, re.I):
            return None
    catalog = list(catalog if catalog is not None else sources)
    titles = {}
    for source in catalog:
        title = source.get('title', '').split(' — ', 1)[0]
        if 'тэнхим' not in title.casefold() or title.casefold() in {'тэнхим', 'тэнхимүүд'}:
            continue
        words = {w for w in _scope_words(title)
                 if not w.startswith(('инженер', 'тэнхим')) and w not in {'ухаан', 'ерөнхий', 'дэд'}}
        if words:
            titles.setdefault(title, set()).update(words)
    query_words = _scope_words(query)
    owners = {word: {title for title, words in titles.items() if word in words}
              for words in titles.values() for word in words}
    selected = [title for title, words in titles.items()
                if any(word in query_words and len(owners[word]) == 1 for word in words)]
    selected_urls = {source.get('url') for source in catalog
                     if source.get('title', '').split(' — ', 1)[0] in selected}
    scoped = [source for source in sources if source.get('url') in selected_urls]
    # An explicit named teacher comes immediately before the role noun. Do not
    # interpret inflected department/subject words (e.g. Химийн) as people.
    person = None
    for match in re.finditer(r'(?<!\w)((?:[А-ЯӨҮЁ]\.\s*)?[А-ЯӨҮЁ][а-яөүё]+(?:-[А-ЯӨҮЁа-яөүё]+)?)\s+багш', query,re.I):
        candidate = match[1].strip()
        if candidate.casefold().endswith(('ийн', 'ын', 'гийн')) or _scope_words(candidate) & set(owners):
            continue
        if candidate.casefold() not in {'энэ', 'тэр', 'ямар', 'манай', 'танай', 'сургуулийн','хэдэн','үндсэн','цагийн','туслах','нийт','бүх'}:
            preceding=re.search(r'([А-ЯӨҮЁа-яөүё]+(?:ын|ийн|ы))\s+$',query[:match.start()])
            if preceding and not (_scope_words(preceding[1]) & set(owners)) and preceding[1].casefold() not in _SCOPE_GENERIC:
                candidate=preceding[1]+' '+candidate
            person = candidate
    result = dict(kind='head' if head else 'names' if names else 'count' if count else 'overview',
                  department_titles=selected, department_urls=sorted(x for x in selected_urls if x),
                  sources=scoped if selected else sources, person=person)
    contact_fields=staff_contact_fields(query)
    if contact_fields:
        result['contact_fields']=contact_fields
    if person:
        if re.search(r'болон|\bба\b|эсвэл|харьцуул',q):
            result.update(stop='clarify_staff_scope',message='Нэрлэсэн багш нарын мэдээллийг тус тусад нь тодруулж асууна уу. '
                'Нэг хүний танилцуулгаар бусад хүний тухай хэсгийг орлуулж хариулахгүй.')
            result['sources']=[]
            return result
        # The name and the role assertion must belong to the same local clause.
        pattern = r'(?<!\w)' + re.escape(person) + r'(?:ын|ийн|ы)?(?!\w)'
        role = r'(?:багш(?:ийн|аар|тай)?|(?:тэнхимийн\s+)?эрхлэгч(?:ийн)?)'
        assertion = r'(?:' + pattern + r'\s+' + role + r'(?!\w)|(?<!\w)' + role + r'\s*[:—-]?\s*' + pattern + r')'
        bound = []
        for source in result['sources']:
            own_cards=[card for card in staff_contact_cards(source['text']) if _staff_person_key(card['person'])==_staff_person_key(person)]
            if own_cards or any(re.search(assertion, clause, re.I)
                   and not re.search(r'овогтой|оюутан|сурагч', clause, re.I)
                   for clause in re.split(r'\n|(?<=[!?])\s+|(?<=\.)\s+(?=[А-ЯӨҮЁ])', source['text'])):
                bound.append(source)
        result['sources'] = bound
        if contact_fields:
            result['sources']=[source for source in bound if any(
                _staff_person_key(card['person'])==_staff_person_key(person)
                and all(field in card['fields'] for field in contact_fields)
                for card in staff_contact_cards(source['text']))]
            if not result['sources']:
                result.update(stop='staff_contact_not_supported',message='Нэрлэсэн багшийн асуусан холбоо барих талбарыг '
                    'өөрийн нэртэй нь нэг хэсэгт баталсан эх олдсонгүй. Тэнхимийн ерөнхий толгой, өөр хүний эсвэл '
                    'сургуулийн ерөнхий холбоог орлуулахгүй.')
                return result
        if not bound:
            result.update(stop='unsupported_person', message='Нэрлэсэн багшийн тухай энэ хайлтаар батлах эх олдсонгүй. '
                'Өөр хүний нэр, оюутны амжилт эсвэл тэнхимийн ерөнхий мэдээллээр орлуулахгүй. '
                'Багшийн бүтэн нэр, тэнхим эсвэл албан танилцуулгын холбоосыг нэмж өгнө үү.')
        return result
    unsupported_attributes = [word for word in ('цалин','настай','гэрийн','төрсөн') if word in q]
    if unsupported_attributes and not all(any(word in source['text'].casefold()
            for source in result['sources']) for word in unsupported_attributes):
        result.update(stop='staff_attribute_not_supported',sources=[],message='Багшийн асуусан хувийн эсвэл ажлын '
            'нарийвчилсан мэдээллийг батлах эх энэ хайлтаар олдсонгүй. Багшийн тоо, өөр хүний танилцуулгаар орлуулахгүй.')
        return result
    if not selected and result['kind'] in {'overview', 'head'}:
        result.update(stop='clarify_staff_scope', message='Аль тэнхимийн эсвэл ямар багшийн мэдээлэл хэрэгтэй вэ? '
            'Багшийн нэр, тэнхимийг хэлэх эсвэл багшийн тоо, эрхлэгчийн нэр, зурагтай танилцуулгын аль нь хэрэгтэйг тодруулна уу.')
    elif names:
        # A number, department head or student award list does not establish a
        # complete list of teachers. Structured portraits have a separate path.
        result.update(stop='staff_names_not_supported', message='Асуусан багш нарын бүрэн нэрсийн жагсаалтыг '
            'энэ хайлтаар батлах эх олдсонгүй. Багшийн тоо, оюутны нэрс эсвэл зөвхөн эрхлэгчийн нэрийг '
            'бүх багшийн жагсаалт гэж орлуулахгүй. Тэнхим эсвэл багшийн бүтэн нэрээр тодруулж болно.')
    elif count:
        positive = [source for source in result['sources'] if staff_count_spans(source['text'])]
        result['sources'] = positive
        if not positive:
            result.update(stop='staff_count_not_supported', message='Асуусан хүрээний багшийн тоог батлах тайлбар '
                'энэ хайлтаар олдсонгүй. Өөр тэнхимийн тоо эсвэл дан самбарын тоог орлуулж хариулахгүй. '
                'Тэнхимийн нэр болон шаардлагатай оныг нэмж өгнө үү.')
        elif not selected:
            result.update(stop='clarify_staff_scope', message='Аль тэнхимийн багшийн тоо хэрэгтэй вэ, эсвэл сургуулийн нийт тоог асууж байна уу? '
                'Хайлтаар олдсон тэнхимийн тоог сургуулийн нийт тоо гэж орлуулахгүй. Тэнхимийн нэр эсвэл огноотой албан эхийг нэмж өгнө үү.')
    return result


def _staff_person_key(value):
    return re.sub(r'\s+', ' ', re.sub(r'\.\s*','.',value.casefold())).strip()


def staff_contact_fields(query):
    """Requested public contact channels; values always come from a named card."""
    q=query.casefold()
    if not re.search(r'багш|эрхлэгч',q):return []
    fields=[]
    if (re.search(r'имэйл|имейл|мэйл|email|e-mail',q)
            or re.search(r'цахим\w*',q) and re.search(r'холбоо\s+бар|холбогд|хаяг|захиа',q)):
        fields.append('email')
    if re.search(r'утас|phone',q):fields.append('phone')
    return fields


def staff_contact_cards(text):
    """Only contiguous role/name/labelled-contact records, with exact spans.

    A name in a page heading cannot own an email elsewhere on that page. A new
    person, role, heading or non-contact line terminates the record.
    """
    lines=list(re.finditer(r'[^\n]+',text))
    cards=[]
    role=r'(?:тэнхимийн\s+)?эрхлэгч|багш'
    person=r'(?:[А-ЯӨҮЁа-яөүё]+(?:ын|ийн|ы)\s+)?(?:[А-ЯӨҮЁа-яөүё]\.\s*)?[А-ЯӨҮЁа-яөүё]+(?:-[А-ЯӨҮЁа-яөүё]+)?'
    for index,line in enumerate(lines):
        value=line.group().strip()
        same=re.fullmatch(r'(?P<role>'+role+r')\s*[:—-]\s*(?P<person>'+person+r')',value,re.I)
        if same:
            name=same['person'];field_index=index+1
        elif re.fullmatch(role,value,re.I) and index+1<len(lines) and re.fullmatch(person,lines[index+1].group().strip()):
            name=lines[index+1].group().strip();field_index=index+2
        else:continue
        fields={};ends={}
        for entry in lines[field_index:field_index+4]:
            label=entry.group().strip()
            email=re.fullmatch(r'(?:имэйл|имейл|мэйл|email|e-mail)\s*[:：]?\s*([A-Za-z0-9.!#$%&\'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})',label,re.I)
            phone=re.fullmatch(r'(?:утас|phone)\s*[:：]?\s*(\+?\d[\d ()-]{5,25}\d)',label,re.I)
            if email and 'email' not in fields:fields['email']=email[1];ends['email']=entry.end()
            elif phone and 'phone' not in fields:fields['phone']=phone[1];ends['phone']=entry.end()
            else:break
        if fields:
            cards.append(dict(person=name,fields=fields,field_ends=ends,start=line.start(),end=max(ends.values()),
                text=text[line.start():max(ends.values())]))
    return cards


def staff_count_spans(text):
    """Positive prose staff counts, excluding isolated UI placeholder counters."""
    result = []
    for match in re.finditer(r'[^\n]+', text):
        line = match.group()
        if (re.search(r'\d+\s*(?:(?:үндсэн|цагийн|туслах|мэргэжлийн)\s*)?багш', line, re.I)
                and re.search(r'бүрэлдэхүүн|үйл\s+ажиллагаа|ажиллаж|удирдан|багштай', line, re.I)
                and not re.search(r'байхгүй|байгаагүй|биш|төлөвлө|магадгүй|эсэх|зорилт|'
                    r'батлагдаагүй|батлаагүй|тодорхойгүй|мэдээлээгүй|таамаг|худал|'
                    r'хэрэв|тохиолдолд|байвал|байх\s+тухай', line, re.I)):
            result.append(line)
    return result


_REGISTRATION_FINANCIAL_EXCLUSIONS = re.compile(r'\b(?:биш|бус)\b|буцаа|хөнгөл|тэтгэл|цалин|дотуур\s+байр|хоол')


def registration_amount_query(query):
    q = query.casefold()
    if _REGISTRATION_FINANCIAL_EXCLUSIONS.search(q):
        return False
    return bool(re.search(r'бүртгэ|элс', q) and re.search(r'хураамж|бүртгэ\w*\s+(?:төлбөр|мөнгө(?:ний)?|мөнгийг)', q)
                and re.search(r'хэд|төгрөг|үнэ|хэмжээ', q))


def registration_payment_query(query):
    """A fee amount/payment request, not a login account or arbitrary money.

    Admission and olympiad both have registration payments. An unscoped payment
    request needs clarification even if retrieval happens to rank only one of
    them. Negative/other-cost clauses retain their separate evidence needs.
    """
    q = query.casefold()
    if _REGISTRATION_FINANCIAL_EXCLUSIONS.search(q):
        return False
    fee_label = (re.search(r'бүртгэ|элс', q)
                 and re.search(r'хураамж|бүртгэ\w*\s+(?:төлбөр|мөнгө(?:ний)?|мөнгийг)', q))
    return bool(fee_label and (registration_amount_query(query)
                or re.search(r'данс|шилжүүл|банк|апп|\bqr\b|төл(?:өх|өхдөө|ж|нө|бөл)', q)))



# Facility names and measurement roles describe scope, not stored answer values.
_FACILITY_KINDS = (
    ('сургалтын анги', r'сургалтын\s+анги|анги\s*танхим'),
    ('лекцийн танхим', r'лекцийн\s+танхим'),
    ('лаборатори', r'лаборатор\w*'),
    ('хоолны танхим', r'нийтийн\s+хоолны\s+газ(?:ар|р)|хоолны\s+(?:танхим|газ(?:ар|р))|цайны\s+газ(?:ар|р)'),
    ('бүжгийн танхим', r'бүжгийн\s+танхим'),
    ('спорт заал', r'спорт(?:ын)?\s+(?:заал|танхим)|биеийн\s+тамирын\s+(?:заал|танхим)'),
    ('хурлын өрөө', r'хурлын\s+(?:өрөө|танхим)'),
    ('уншлагын танхим', r'уншлагын\s+танхим'),
)

_FLOOR_VALUE = (r'(?<![\w\d])(?:\d{1,3}(?:\s*-\s*р)?|'
    r'нэгдүгээр|хоёрдугаар|гуравдугаар|дөрөвдүгээр|тавдугаар|зургаадугаар|'
    r'долдугаар|наймдугаар|есдүгээр|аравдугаар)\s+давх(?:арт|ард|арын|рын)(?!\w)')
_FLOOR_UNCERTAIN = (r'хэрэв|тохиолдолд|байвал|магадгүй|төлөвлө|тодорхойгүй|'
    r'батлагдаагүй|мэдээлээгүй|байхгүй|байгаагүй|байрладаггүй|байрлахгүй|\bбиш\b|'
    r'нүү(?:сэн|вэл)|шилж(?:сэн|вэл)')


def facility_floor_requirements(query):
    """Ask for the location's floor, rather than an ordinal or floor area."""
    q=query.casefold()
    if not re.search(r'хэд(?:эн|дүгээр)?\s+давхар|аль\s+давхар|давхар\w*(?:\s+нь)?\s+(?:байдаг|байрладаг|хэд)',q):
        return []
    objects=[('library',r'номын\s+сан(?:гийн|д)?')]+list(_FACILITY_KINDS)
    context=[name for name in _detail_names(query)]
    context += [m[1].casefold() for m in re.finditer(r'(?<!\w)([A-Za-zА-ЯӨҮЁа-яөүё0-9][\w-]{0,40})\s+байр(?:ны|анд|т|д)?(?!\w)',query)
                if m[1].casefold() not in {'сургуулийн','коллежийн','барилгын','тус','энэ','тэр'}]
    return [dict(name='facility_floor_'+name,label='асуусан орчны байрлах давхар',type='facility_floor',
        object=name,aliases=[pattern],context_names=sorted(set(context)),
        query_condition_unverified=bool(re.search(_FLOOR_UNCERTAIN,q)))
        for name,pattern in objects if re.search(pattern,q,re.I)]


def facility_floor_records(text, requirement):
    """Exact local facility/floor bindings; unrelated list ordinals never count.

    A facility's own heading can own its next location sentence (with at most
    one short subtitle). A container can supply location only with an explicit
    membership statement and a contiguous numbered list containing the target.
    """
    if requirement.get('query_condition_unverified'):return []
    aliases=requirement['aliases']
    target='(?:'+'|'.join(aliases)+')'
    all_facilities=[r'номын\s+сан(?:гийн|д)?']+[pattern for _,pattern in _FACILITY_KINDS]
    lines=list(re.finditer(r'[^\n]+',text))
    found=[]

    def add(start,end,kind):
        span=text[start:end]
        if (re.search(_FLOOR_UNCERTAIN,span,re.I) or any(not re.search(r'(?<!\w)'+re.escape(name)+r'(?!\w)',span,re.I)
                for name in requirement.get('context_names',[]))):return
        found.append(dict(start=start,end=end,text=span,kind=kind))

    for index,line in enumerate(lines):
        value=line.group().strip()
        if re.search(_FLOOR_UNCERTAIN,value,re.I):continue
        # Literal subject/location prose, with no intervening facility noun.
        for clause in re.finditer(r'[^\n]+?(?:[.!?](?=\s|$)|$)',value):
            sentence=clause.group().strip()
            floor=re.search(_FLOOR_VALUE,sentence,re.I)
            subject=re.match(r'\s*(?:(?:сургуулийн|коллежийн|манай|тус)\s+)?'+target+r'\s+(?:нь\s+)?',sentence,re.I)
            if floor and subject and floor.start()>=subject.end():
                between=sentence[subject.end():floor.start()]
                if (not any(re.search(pattern,between,re.I) for pattern in all_facilities)
                        and re.fullmatch(r'(?:(?:сургуулийн|коллежийн|барилгын|байрны|гол|тус|энэ|тэр)\s+)*',between)
                        and re.search(r'байрл(?:адаг|ах|асан|аж)|байдаг',sentence[floor.end():],re.I)):
                    start=line.start()+clause.start()
                    add(start,line.start()+clause.end(),'explicit_facility_location')
        if not re.fullmatch(target+r'\s*[:：]?',value,re.I):continue
        for offset in (1,2):
            if index+offset>=len(lines):continue
            if offset==2:
                subtitle=lines[index+1].group().strip()
                if (len(subtitle)>65 or re.search(r'[.!?]|\d|давхар|\b(?:байр|барилга|төв|танхим|өрөө|заал)\w*',subtitle,re.I)
                        or any(re.search(pattern,subtitle,re.I) for pattern in all_facilities)):
                    continue
            location=lines[index+offset]
            value=location.group().strip()
            if re.search(_FLOOR_UNCERTAIN,value,re.I):continue
            sentence=re.split(r'(?<=[.!?])\s+',value,maxsplit=1)[0]
            floor=re.match(_FLOOR_VALUE,sentence,re.I)
            if (floor and not any(re.search(pattern,sentence,re.I) for pattern in all_facilities)
                    and re.search(r'байрл\w*|байдаг|талбай|орчин|өрөө',sentence[floor.end():],re.I)):
                end=location.start()+len(location.group())-len(location.group().lstrip())+len(sentence)
                add(line.start(),end,'facility_heading_location')

    # The floor statement must itself introduce the following membership list.
    # Mere page adjacency or an unlabelled list does not establish containment.
    for index,line in enumerate(lines):
        value=line.group().strip()
        if not (re.search(_FLOOR_VALUE,value,re.I) and re.search(r'байрл\w*|байдаг',value,re.I)
                and re.search(r'бүрэлдэхүүнд|дараах\s+(?:өрөө|орчин|хэсэг)|багтаана|багтаадаг',value,re.I)):
            continue
        if index==0:continue
        heading=lines[index-1].group().strip()
        if len(heading)>80 or re.search(r'[.!?]|давхар',heading,re.I):continue
        cursor=index+1;member_end=None
        while cursor+1<len(lines):
            number=lines[cursor].group().strip();member=lines[cursor+1].group().strip()
            if not re.fullmatch(r'0?[1-9]\d?[.)]?',number):break
            if re.fullmatch(target,member,re.I):member_end=lines[cursor+1].end()
            cursor+=2
        if member_end:add(lines[index-1].start(),member_end,'explicit_container_membership')
    return sorted(found,key=lambda item:(item['end']-item['start'],item['start']))


def _facility_capacity_types(sources):
    """Identify capacities only when a facility label precedes a seat count."""
    kinds = set()
    for source in sources:
        text = source['text'].casefold()
        for seat in re.finditer(r'\d[\d,.]*\s*(?:хүний\s*)?суудал', text):
            preceding = text[max(0, seat.start() - 260):seat.start()]
            candidates = [(m.end(), label) for label, pattern in _FACILITY_KINDS
                          for m in re.finditer(pattern, preceding)]
            if candidates:
                kinds.add(max(candidates)[1])
    return kinds


def _number_measurements(query, sources):
    """For one bare query number, find distinct literal source measurement roles.

    This recognises a small set of explicit units. It never guesses a role for
    an unlabelled number or treats a repeated copy of the same unit as ambiguity.
    """
    numbers = re.findall(r'(?<![\w.,])\d+(?:[.,]\d+)*(?![\w.,])', query)
    if len(set(numbers)) != 1:
        return set()
    number = numbers[0]
    by_unit = {}
    unit_patterns = (
        ('талбай (м²)', r'^\s*(?:м²|м2|m²|m2|квадрат\s+метр|метр\s+квадрат)'),
        ('суудлын тоо', r'^\s*(?:хүний\s*)?суудал'),
        ('хүний тоо', r'^\s*(?:хүн|оюутан|багш)(?![а-яөүё])'),
        ('номын тоо', r'^\s*(?:ном(?:той|ыг|ын)?|сурах\s+бичиг)(?![а-яөүё])'),
        ('мөнгөн дүн', r'^\s*(?:₮|төгрөг|иен|доллар)(?![а-яөүё])'),
        ('хугацаа', r'^\s*(?:минут|цаг|хоног)(?![а-яөүё])'),
    )
    for source in sources:
        text = source['text'].casefold()
        for occurrence in re.finditer(r'(?<![\d.,])' + re.escape(number) + r'(?![\d.,])', text):
            following = text[occurrence.end():occurrence.end() + 50]
            for label, pattern in unit_patterns:
                if re.search(pattern, following):
                    before = text[max(0, occurrence.start() - 120):occurrence.start()]
                    after = text[occurrence.end():occurrence.end() + 120]
                    nearby = [(len(before) - match.end(), kind)
                              for kind, facility in _FACILITY_KINDS
                              for match in re.finditer(facility, before)]
                    nearby += [(match.start(), kind)
                               for kind, facility in _FACILITY_KINDS
                               for match in re.finditer(facility, after)]
                    kind = min(nearby)[1] if nearby else None
                    by_unit.setdefault(label, set()).add(kind)
    roles = set()
    for label, kinds in by_unit.items():
        known = kinds - {None}
        # A truncated copy that omits the facility name is not evidence of a
        # second object. Only multiple explicit objects make one unit ambiguous.
        if len(known) > 1:
            roles.update(label + ' / ' + kind for kind in known)
        else:
            roles.add(label)
    return roles


def ambiguity(query, sources):
    q = query.casefold()
    text = '\n'.join(s['text'].casefold() for s in sources)
    if _competition_rank_query(query) and not _detail_names(query):
        return ('Аль оюутан эсвэл багийн, ямар тэмцээний дүнг асууж байна вэ? '
                'Тэмцээний нэр, оролцогч болон он/огноог тодруулна уу.', [])
    programme=re.search(r'(?<!\w)([\w-]{3,})\s+хөтөлбөр',q)
    if (programme and programme[1] not in {'манай','тухайн','ямар','энэ','тэр','бүх'}
            and re.search(r'хот|байршил|хаана',q) and re.search(r'уулзалт|арга\s+хэмжээ',q)
            and not re.search(r'харьцуул|хотуудад|бүх|тус\s+бүр|хоёул|#\s*\d|'
                              r'сарын\s+\d|\d{4}[-./]\d{1,2}[-./]\d{1,2}',q)):
        pages={source.get('url') for source in sources if source.get('url')
               and re.search(r'(?<!\w)'+re.escape(programme[1])+r'(?!\w)',source.get('title',''),re.I)}
        if len(pages)>1:
            return ('Энэ хөтөлбөрийн өөр өөр уулзалтын мэдээ байна. Аль удаагийн уулзалтыг асууж байна вэ? '
                    'Мэдээний огноо, дугаар эсвэл холбоосыг нэмж өгнө үү.',[])
    if re.search(r'номын\s+сан', q):
        requested_program = _queried_library_program(query, conjunction_only=True)
        known_programs = _library_program_names(sources)
        if (requested_program and known_programs
                and _program_name_key(requested_program[0]) not in {_program_name_key(name) for name in known_programs}):
            name, start, end = requested_program
            return ('Номын сангийн программын «' + name + '» гэсэн нэрийг шалгана уу. '
                    'Эхэд ' + ', '.join('«' + value + '»' for value in known_programs[:3])
                    + ' гэж бичсэн байна. Тэр программыг асууж байна уу?',
                    [query[:start] + value + query[end:] for value in known_programs[:3]])
    # A generic room is not interchangeable with a classroom, lecture hall,
    # or cafeteria. Require multiple observed capacity kinds before asking.
    if ('танхим' in q and re.search(r'суудал|хэдэн\s+хүн|багтаамж', q)
            and not any(re.search(pattern, q) for _, pattern in _FACILITY_KINDS)
            and not re.search(r'харьцуул|бүх|төрөл\s+бүр|тус\s+бүр', q)):
        kinds = _facility_capacity_types(sources)
        if len(kinds) > 1:
            return ('Аль танхимын суудлын тоог асууж байна вэ? Эхэд '
                    + ', '.join(sorted(kinds)) + ' гэсэн өөр төрлийн орчин байна.', [])
    # A bare displayed number can refer to distinct units on the same page.
    # Asking for one interpretation would hide the unresolved measurement.
    if (re.search(r'үзүүлэлт|тоо|гэсэн|юуны|юуг', q)
            and not re.search(r'м²|м2|квадрат|суудал|талбай|төгрөг|иен|минут|хоног', q)
            and not any(re.search(pattern, q) for _, pattern in _FACILITY_KINDS)
            and not re.search(r'харьцуул|бүх|ялга|хоёул', q)):
        roles = _number_measurements(q, sources)
        if len(roles) > 1:
            return ('Тэр тоо эхэд өөр өөр хэмжигдэхүүнээр давтагдсан байна: '
                    + ', '.join(sorted(roles)) + '. Аль нэгж эсвэл аль орчны үзүүлэлтийг асууж байна вэ?', [])
    if ('тэнхим' in q and
            (('эрхлэгч' in q and re.search(r'нэр|имэйл|мэйл|утас', q))
             or (re.search(r'багш', q) and re.search(r'хэд|тоо', q)))
            and not _literal_scope(query, sources)):
        names = _department_names(sources)
        return (('Аль тэнхимийн багшийн тоог асууж байна вэ?' if 'багш' in q else
                 'Аль тэнхимийн эрхлэгчийн нэр, холбоо барих мэдээлэл хэрэгтэй вэ?')
                + (' ' + '; '.join(names[:5]) + '.' if names else ''), [])
    japan = bool(re.search(r'япон', q))
    pathway = bool(re.search(r'дадлаг|дэвшин|суралц|аялал|ажил(?:лах|д|длах)|танилцах', q))
    multiple = bool(re.search(r'харьцуул|хөтөлбөрүүд|бүх\s+тэтгэл|тэтгэлгүүд', q))
    if (japan and (re.search(r'хоног|хугацаа|үргэлжил|хэр удаан', q)
                   or ('хэл' in q and re.search(r'шаардлаг|түвшин', q)))
            and not pathway and not multiple and not _literal_scope(query, sources)):
        return ('Япон руу явах аль замыг асууж байна вэ: танилцах хөтөлбөр, дадлага, '
                'дэвшин суралцах эсвэл ажиллах уу? Хугацаа, хэлний шаардлага нь замаасаа хамаарна.', [])
    if ('тэтгэл' in q and re.search(r'курс|хамрагд|хамрагдах|шаардлаг|нөхцөл|дүн|хэмжээ|хугацаа|эхлэх|хэзээ|хэд|зардал|зардлыг|даах|даадаг|санхүүж', q)
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
            not re.search(r'элс|ярилцлаг|олимпиад|бичгийн|түвшин\s+тогтоо\w*', q)):
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


def enrollment_consequence_query(query):
    """Identify a missed-contract consequence, not enrolment confirmation."""
    q = query.casefold()
    return bool(re.search(r'элс', q) and 'гэрээ' in q
                and re.search(r'ирээгүй|байгуулаагүй|хугацаа\w*.{0,25}(?:алд|хоцор)|'
                              r'хүчингүй|татгалз|дараагийн\s+шалгуулагч', q))


def enrollment_consequence_supported(query, text):
    q, value = query.casefold(), text.casefold()
    if not ('гэрээ' in value and re.search(r'байгуулаагүй|ирээгүй', value)
            and re.search(r'эрхийн\s+бич\w*.{0,35}хүчингүй|суралцахаас\s+татгалзсан', value)):
        return False
    if 'хүндэтгэх шалтгаантай' in q and 'хүндэтгэх шалтгаангүй' in value:
        return False
    if 'дараагийн' in q and not (re.search(r'дараагийн\s+шалгуулагч', value)
            and 'хүсэлт' in value and re.search(r'элсүүлж\s+болно', value)):
        return False
    return True


_WEEK_DAYS = ('даваа', 'мягмар', 'лхагва', 'пүрэв', 'баасан', 'бямба', 'ням')
_HOUR_VALUE = r'\d{1,2}[:.]\d{2}|\d+\s*цагаас|\d+\s*цаг\s+хүртэл'


def _library_opening_hours_supported(text, query):
    """A library label must own its schedule; office hours cannot substitute."""
    wanted = {day for day in _WEEK_DAYS if re.search(r'(?<!\w)' + day + r'(?!\w)', query.casefold())}
    lines = re.split(r'\n|(?<=[.!?])\s+', text.casefold())
    for index, line in enumerate(lines):
        if not re.search(r'номын\s+сан', line):
            continue
        # A short, explicit library heading may own its next schedule rows.
        rows = [line]
        if len(line.split()) <= 5:
            for row in lines[index + 1:index + 10]:
                if not row.strip():
                    continue
                if (any(day in row for day in _WEEK_DAYS) or 'өдөр бүр' in row
                        or re.fullmatch(r'\s*(?:ажлын\s+цаг|цагийн\s+хуваарь)\s*[:—-]?\s*', row)):
                    rows.append(row)
                else:
                    break
        covered = set()
        for row in rows:
            if re.search(r'тодорхойгүй|мэдээлээгүй|батлаагүй|төлөвлө|магадгүй', row):
                continue
            if not (re.search(_HOUR_VALUE, row) or re.search(r'амарна|ажиллахгүй|хаалттай', row)):
                continue
            days = {day for day in _WEEK_DAYS if re.search(r'(?<!\w)' + day + r'(?!\w)', row)}
            for left, right in re.findall('(' + '|'.join(_WEEK_DAYS) + r')\s*[–—-]\s*(' + '|'.join(_WEEK_DAYS) + ')', row):
                start, end = _WEEK_DAYS.index(left), _WEEK_DAYS.index(right)
                if start <= end:
                    days.update(_WEEK_DAYS[start:end + 1])
            if re.search(r'өдөр\s+бүр', row):
                days.update(_WEEK_DAYS)
            covered.update(days)
        if covered and (not wanted or wanted <= covered):
            return True
    return False


def _cafeteria_opening_hours_supported(text, query):
    """An opening-hours assertion must belong to the dining facility itself."""
    label = r'хоолны\s+(?:газ(?:ар|р)\w*|танхим\w*)|цайны\s+газ(?:ар|р)\w*|нийтийн\s+хоолны\s+газ(?:ар|р)\w*'
    other = r'захиргаа\w*|номын\s+сан|лаборатор\w*|сургалтын\s+алба|спорт\w*\s+заал'
    lines = re.split(r'\n|(?<=[!?])\s+|(?<=[.])\s+(?=[А-ЯӨҮЁ])', text.casefold())
    wanted = {day for day in _WEEK_DAYS if re.search(r'(?<!\w)' + day + r'(?!\w)', query.casefold())}
    for index, line in enumerate(lines):
        if not re.search(label,line) or re.search(other,line):
            continue
        rows=[line]
        if re.fullmatch(r'\s*(?:'+label+r')\s*[:—-]?\s*',line):
            for row in lines[index+1:index+10]:
                if not row.strip():continue
                if re.search(other,row):break
                if re.match(r'\s*(?:'+ '|'.join(_WEEK_DAYS) + r'|өдөр\s+бүр|ажлын\s+цаг|цагийн\s+хуваарь|\d{1,2}[:.]\d{2})',row):
                    rows.append(row)
                else:break
        covered=set();supported=False
        for row in rows:
            if re.search(r'тодорхойгүй|мэдээлээгүй|батлаагүй|батлагдаагүй|төлөвлө|магадгүй|'
                         r'\bбиш\b|хэрэв|тохиолдолд|байвал',row):continue
            if not (re.search(_HOUR_VALUE,row) and re.search(r'ажилла\w*|нээлттэй|нээгд\w*|нээдэг|хаадаг|хуваарь|\d{1,2}[:.]\d{2}\s*[–—-]\s*\d{1,2}[:.]\d{2}',row)
                    or re.search(r'амарна|ажиллахгүй|хаалттай',row)):continue
            supported=True
            days={day for day in _WEEK_DAYS if re.search(r'(?<!\w)'+day+r'(?!\w)',row)}
            for left,right in re.findall('('+'|'.join(_WEEK_DAYS)+r')\s*[–—-]\s*('+'|'.join(_WEEK_DAYS)+')',row):
                start,end=_WEEK_DAYS.index(left),_WEEK_DAYS.index(right)
                if start<=end:days.update(_WEEK_DAYS[start:end+1])
            if re.search(r'өдөр\s+бүр',row):days.update(_WEEK_DAYS)
            covered.update(days)
        if supported and (not wanted or wanted<=covered):return True
    return False


def _equipment_identity_supported(text, query):
    """Require the requested identity labels with the actual equipment."""
    q = query.casefold()
    anchors = {word.casefold() for word in re.findall(r'(?<!\w)[A-Za-z][A-Za-z0-9-]{1,}(?!\w)', query)}
    manufacturer = 'үйлдвэрлэгч' in q
    model = bool(re.search(r'загвар', q))
    for clause in re.split(r'\n|(?<=[.!?])\s+', text.casefold()):
        if (any(not re.search(r'(?<!\w)' + re.escape(anchor) + r'(?!\w)', clause) for anchor in anchors)
                or not re.search(r'машин|тоног\s+төхөөрөмж|\bcnc\b|токарь|фрезер', clause)
                or re.search(r'тодорхойгүй|мэдээлээгүй|батлаагүй|магадгүй|байхгүй|таамаг', clause)):
            continue
        if manufacturer and not re.search(r'үйлдвэрлэгч\s*(?:нь\s*)?[:—-]?\s*'
                r'(?!тодорхой|мэдээлэл|загвар|дугаар)[a-zа-яөүё][a-zа-яөүё0-9&.-]{2,}', clause):
            continue
        if model:
            match = re.search(r'загвар(?:ын\s+дугаар)?\s*(?:нь\s*)?[:№—-]?\s*([a-z0-9][a-z0-9_/-]{1,30})(?!\w)', clause)
            if not match or not re.search(r'\d', match[1]):
                continue
        return True
    return False


def requested_detail(query):
    """Return a narrow missing-field screen, not an automatic truth label."""
    q = query.casefold()
    if facility_floor_requirements(query):
        return 'facility_floor'
    if enrollment_consequence_query(query):
        return 'enrollment_contract_consequence'
    if (re.search(r'номын\s+сан', q)
            and re.search(r'нээлттэй|ажилла\w*|цагийн\s+хуваарь|нээгд|нээдэг|нээх|хаадаг|хаах|хаагд|хэд\s+цаг', q)
            and re.search(r'өдр|гараг|хэдээс|хэд\s+хүртэл|цагийн\s+хуваарь', q)):
        return 'library_opening_hours'
    if (re.search(r'хоолны\s+(?:газ(?:ар|р)|танхим)|цайны\s+газ(?:ар|р)|нийтийн\s+хоол', q)
            and re.search(r'ажилла\w*|нээлттэй|нээгд\w*|нээ(?:дэг|х|нэ|дэг)|хаадаг|хаах|цагийн\s+хуваарь|хэдээс|хэд\s+хүртэл', q)
            and re.search(r'цаг|хэдээс|хэдэд|хэд\s+хүртэл|гараг|өдр', q)):
        return 'cafeteria_opening_hours'
    if (re.search(r'машин|тоног\s+төхөөрөмж|\bcnc\b|токарь|фрезер', q)
            and re.search(r'үйлдвэрлэгч|загвар(?:ын)?\s+дугаар|яг\s+загвар', q)):
        return 'equipment_identity'
    if _competition_rank_query(query) and re.search(r'эцсийн|эцэслэсэн|батлагдсан',q):
        return 'competition_final_rank'
    if 'патент' in q and re.search(r'дугаар|бүртгэлийн\s+(?:код|id)|идентификатор', q):
        return 'patent_registration_identifier'
    if ('сургалт' in q and re.search(r'төлбөр|хураамж|үнэ', q)
            and (re.search(r'нэг\s+(?:оролцогч|хүн)|(?:оролцогч|хүн)\w*\s+(?:тутам|бүр)', q)
                 or re.search(r'богино\s+хугацаа|зуны\s+сургалт|сургалт\w*\s+нэг\s+удаа', q))):
        return 'short_training_participant_fee'
    if (re.search(r'хоолны\s+(?:газ(?:ар|р)|танхим)|цайны\s+газ(?:ар|р)|нийтийн\s+хоол', q)
            and re.search(r'цэс|үнэ|ямар\s+хоол', q)
            and re.search(r'өнөөдр|яг\s+одоо|одоогийн|энэ\s+өдрийн', q)):
        return 'current_cafeteria_menu'
    if ('магадлан' in q and 'итгэмжл' in q
            and re.search(r'эцсийн\s+шийдвэр|шийдвэр.{0,20}(?:гарсан|гаргасан|батлагдсан)', q)
            and re.search(r'хэдэн\s+сар|хэдний|огноо|хэзээ|ямар\s+өдөр', q)):
        return 'accreditation_final_decision_date'
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
    if registration_payment_query(query) and 'данс' in q:
        return 'registration_payment_account'
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
    if tuition_label_query(q) and re.search(r'хувааж|хуваар|хуваан|сар бүр.*төл|сараар.*төл', q):
        return 'tuition_instalments'
    if ('олимпиад' in q and re.search(r'хөнгөлөлт|50', q) and
            re.search(r'таван жил|5 жил|тасралтгүй|сунга|жил бүр', q)):
        return 'award_renewal'
    return None


DETAIL_LABELS = {
    'facility_floor': 'асуусан орчны байрлах давхар',
    'cafeteria_opening_hours': 'хоолны газрын нээх, хаах цагийн хуваарь',
    'enrollment_contract_consequence': 'гэрээ байгуулах хугацааг алдсан нөхцөл, элсэх эрхийн үр дагавар',
    'library_opening_hours': 'номын сангийн тухайн өдрийн нээх, хаах цаг',
    'equipment_identity': 'тухайн тоног төхөөрөмжийн үйлдвэрлэгч, загварын тодорхой мэдээлэл',
    'competition_final_rank': 'тухайн оролцогчийн тухайн тэмцээнд бодитоор эзэлсэн эцсийн байр',
    'patent_registration_identifier': 'тухайн төслийн патентын бүртгэлийн дугаар',
    'short_training_participant_fee': 'тухайн богино сургалтын нэг оролцогчийн төлбөр',
    'current_cafeteria_menu': 'өнөөдрийн хоолны цэс, үнэ',
    'accreditation_final_decision_date': 'магадлан итгэмжлэлийн эцсийн шийдвэр гарсан огноо',
    'current_exchange_rate': 'өнөөдрийн бодит валютын ханш',
    'laboratory_opening_hours': 'лабораторийн нээлттэй өдөр, цагийн хуваарь',
    'appeal_deadline': 'давж заалдах/гомдол гаргах хугацаа',
    'guaranteed_salary': 'баталгаатай олгох цалингийн хэмжээ, нөхцөл',
    'registration_amount': 'бүртгэлийн хураамжийн дүн',
    'registration_payment_account': 'бүртгэлийн төлбөр шилжүүлэх банкны дансны дугаар',
    'admission_office_contact': 'элсэлтийн алба/комиссын холбоо барих мэдээлэл',
    'essay_font': 'эссэний фонт, үсгийн пунктын шаардлага',
    'photo_file_size': 'цээж зургийн файлын MB хэмжээний хязгаар',
    'sql_weekly_hours': 'SQL-ийн долоо хоногийн хичээлийн цаг',
    'course_weekly_hours': 'хөтөлбөр/хичээлийн долоо хоногийн цаг',
    'tuition_instalments': 'сургалтын төлбөрийг сараар хувааж төлөх хуваарь',
    'award_renewal': 'олимпиадын хөнгөлөлтийг дараагийн жилүүдэд сунгах нөхцөл',
}


def _competition_rank_query(query):
    q = query.casefold()
    rank = re.search(r'хэддүгээр|ямар\s+байр', q)
    event = re.search(r'тэмцээн|уралдаан|олимпиад', q)
    participant = re.search(r'баг|оюут|сурагч', q) and 'эзэл' in q
    return bool(rank and (event or participant))


def _quoted_detail_names(query):
    return [next(value for value in match.groups() if value) for match in
            re.finditer(r'«([^»]+)»|“([^”]+)”|"([^"\n]+)"', query)]


def _detail_names(query):
    """Literal names, not aliases/NER: quotes, Latin tokens, initials and labelled names."""
    names = _quoted_detail_names(query)
    generic = {'final','rank','result','team','competition','patent','registration','number',
               'id','fee','training','course','participant','манай','тухайн','ямар','энэ','тэр'}
    names += re.findall(r'(?<!\w)[A-Za-z][A-Za-z0-9:+_-]{1,}(?!\w)', query)
    names += re.findall(r'(?<!\w)[А-ЯӨҮЁ]\.\s*[А-ЯӨҮЁ][а-яөүё]{2,}', query)
    names += re.findall(r'(?<!\w)([А-ЯӨҮЁ][а-яөүё]{2,})\s+(?:баг|төсөл|тэмцээн|уралдаан|сургалт)', query)
    names += re.findall(r'(?<!\w)([А-ЯӨҮЁ][а-яөүё]{2,})\s+(?:муж|аймаг|хот|улс)',query)
    return sorted({re.sub(r'\s+', ' ', value.casefold()).strip()
                   for value in names if value.casefold() not in generic})


def _detail_scope_matches(query, clause):
    if not query:
        return True
    normalized = re.sub(r'\s+', ' ', clause.casefold())
    if any(not re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)', normalized)
           for name in _detail_names(query)):
        return False
    years = set(re.findall(r'(?<!\d)(?:19|20)\d{2}(?!\d)', query))
    return years <= set(re.findall(r'(?<!\d)(?:19|20)\d{2}(?!\d)', clause))


_DETAIL_UNCERTAIN = (r'төлөвлө|зорилоо|оролцохоор|оролцоно|оролцох\s+болно|'
    r'эзлэх|эзэлнэ|шалгарах|бүртгүүлэх|бүртгүүлнэ|олгогдоогүй|аваагүй|'
    r'эзлээгүй|эзлээгүй|шалгараагүй|бүртгэгдээгүй|төлөөгүй|авах\s+боломж|'
    r'тодорхойгүй|магадгүй|болзошгүй|таамаг|цуурхал|мэдээлээгүй|хэрэв|'
    r'\b(?:биш|үгүй|эсэх)\b|эзэлсэн\s+бол\b|гэж.{0,30}болохгүй')


def _completed_detail_supported(field, text, query):
    # These observed-development screens bind one explicit field/value and
    # the query's literal names/year in one clause. Unknown forms abstain.
    clauses = re.split(r'\n|;|(?<=[.!?])\s+|\b(?:боловч|харин)\b|(?<!\d),(?!\d)', text.casefold())
    for clause in clauses:
        if re.search(_DETAIL_UNCERTAIN, clause) or not _detail_scope_matches(query, clause):
            continue
        if field == 'competition_final_rank':
            ordinal = (r'(?:\d{1,3}\s*-?\s*(?:р|дугаар|дүгээр)|'
                r'[ivxlcdm]+\s*(?:дугаар|дүгээр)?|нэгдүгээр|хоёрдугаар|гуравдугаар|'
                r'дөрөвдүгээр|тавдугаар|зургадугаар|долдугаар|наймдугаар|есдүгээр|аравдугаар|тусгай)')
            if re.search(r'(?<!\w)' + ordinal + r'\s+байр\w*\s+(?:эзэлсэн|эзэллээ|эзлэв|эзлэн|шалгарсан|шалгарлаа|орсон|орлоо|хүртсэн|хүртлээ)(?!\w)', clause):
                return True
        elif field == 'patent_registration_identifier':
            for match in re.finditer(r'патент\w*\s+(?:албан\s+ёсны\s+)?(?:бүртгэлийн\s+)?'
                    r'(?:дугаар|№)\s*(?:нь\s*)?[:№#-]?\s*([a-zа-яөүё0-9][a-zа-яөүё0-9/-]{2,35})(?!\w)', clause):
                identifier = match[1]
                if (re.search(r'\d', identifier) and not re.fullmatch(r'(?:19|20)\d{2}', identifier)
                        and not re.fullmatch(r'(?:19|20)\d{2}[-/]\d{1,2}[-/]\d{1,2}', identifier)):
                    return True
        elif field == 'short_training_participant_fee':
            if (re.search(r'сургалт', clause) and re.search(r'төлбөр|хураамж|үнэ', clause)
                    and re.search(r'нэг\s+(?:оролцогч|хүн)|(?:оролцогч|хүн)\w*\s+(?:тутам|бүр)', clause)
                    and re.search(r'\d+(?:[.,]\d+)*\s*(?:төгрөг|₮)', clause)
                    and not re.search(r'жилд|жилийн\s+төлбөр|хичээлийн\s+жил|олимпиад|элсэлтийн', clause)):
                return True
    return False


_DECISION_DATE = (
    r'(?<!\d)(?:(?:19|20)\d{2}\s*(?:оны?\s*)?'
    r'(?:\d{1,2}|[а-яөүё]+(?:дугаар|дүгээр))\s*сарын\s*\d{1,2}'
    r'|(?:19|20)\d{2}[-./]\d{1,2}[-./]\d{1,2})(?!\d)'
    r'(?:-(?:ний|ны|нд))?(?:\s*өдөр)?'
)
_ACCREDITATION_DECISION = (
    r'(?:(?:байгууллагын|хөтөлбөрийн)\s+)?(?:дахин\s+)?'
    r'магадлан\s+итгэмжлэл(?:ийн|д|ийг)?\s+'
    r'(?:эцсийн\s+)?шийдвэр(?:ийг|ийн|ээр)?'
)
_COMPLETED_DECISION = r'(?:гарсан|гарав|гаргасан|гаргав|батлагдсан|батлагдав|баталсан)(?![а-яөүё])'


def _accreditation_decision_date_supported(text, query=None):
    """Bind a date to the completed decision, rather than a nearby event.

    Co-occurrence of accreditation, a date and a completed verb is insufficient:
    a meeting/publication date can otherwise leak into a missing decision date.
    Only the explicit local subject/date/predicate forms below are recognised.
    Unrecognised prose remains unsupported; this is not semantic entailment.
    """
    q = (query or '').casefold()
    for clause in re.split(r'\n|;|(?<=[.!?])\s+|\b(?:боловч|харин)\b', text.casefold()):
        if re.search(r'гараагүй|гаргаагүй|батлагдаагүй|батлаагүй|'
                     r'гарах|гарна|орж\s+байна|явагдаж|төлөвлө|хүлээгд|'
                     r'нийтэл|нийтлэгд|шинэчил|тодорхойгүй|магадгүй|болзошгүй|'
                     r'байхгүй|мэдээлээгүй|нотлогдоогүй|цуурхал|таамаг|худал|'
                     r'(?:гарсан|баталсан|батлагдсан)\s+бол\b|'
                     r'\b(?:биш|үгүй|эсэх)\b|гэж.{0,35}болохгүй', clause):
            continue
        patterns = (
            _ACCREDITATION_DECISION + r'\s*[:—-]?\s*' + _DECISION_DATE
            + r'\s+(?:албан\s+ёсоор\s+)?' + _COMPLETED_DECISION,
            _DECISION_DATE + r'\s+' + _ACCREDITATION_DECISION
            + r'\s+(?:албан\s+ёсоор\s+)?' + _COMPLETED_DECISION,
            _ACCREDITATION_DECISION + r'\s+' + _COMPLETED_DECISION
            + r'\s+огноо\s*[:—-]?\s*' + _DECISION_DATE,
        )
        for pattern in patterns:
            match = re.search(pattern, clause)
            if match:
                # Scope must belong to this decision, not a neighbouring event
                # in the same sentence. Do not silently drop query qualifiers.
                decision = match.group()
                if ('байгууллаг' in q and 'байгууллаг' not in decision
                        or 'хөтөлбөр' in q and 'хөтөлбөр' not in decision
                        or 'дахин' in q and 'дахин' not in decision):
                    continue
                requested_years = set(re.findall(r'(?<!\d)(?:19|20)\d{2}(?!\d)', q))
                decision_years = set(re.findall(r'(?<!\d)(?:19|20)\d{2}(?!\d)', decision))
                if not requested_years or requested_years <= decision_years:
                    return True
    return False


def detail_supported(field, text, query=None):
    # Require the requested field together with its value/condition in a clause.
    # Nearby programme duration, A4 format and word count are not substitutes.
    if field == 'facility_floor':
        requirements=facility_floor_requirements(query or '')
        return bool(requirements) and all(facility_floor_records(text,requirement) for requirement in requirements)
    if field == 'enrollment_contract_consequence':
        return enrollment_consequence_supported(query or '', text)
    if field == 'library_opening_hours':
        return _library_opening_hours_supported(text, query or '')
    if field == 'cafeteria_opening_hours':
        return _cafeteria_opening_hours_supported(text, query or '')
    if field == 'equipment_identity':
        return _equipment_identity_supported(text, query or '')
    if field in {'competition_final_rank', 'patent_registration_identifier', 'short_training_participant_fee'}:
        return _completed_detail_supported(field, text, query)
    if field == 'registration_amount':
        return bool(re.search(r'бүртгэлийн\s+хураамж\w*[:\s]*\d+(?:[.,]\d+)*\s*(?:төгрөг|₮)', text.casefold()))
    if field == 'registration_payment_account':
        # A fee amount, QPay mention or contact phone is not a bank account.
        # Require an account label next to its literal digits (or IBAN).
        q = text.casefold()
        return bool(re.search(r'\bданс(?:ны\s+дугаар)?\s*[:№#]?\s*(?:mn\s*)?\d[\d -]{5,32}\d\b', q)
                    or re.search(r'\b\d[\d -]{5,32}\d\s*(?:тоот\s+|дугаартай\s+)?данс', q))
    if field == 'current_cafeteria_menu':
        # This captured corpus has no live, date-bound menu/price evidence tool.
        return False
    if field == 'current_exchange_rate':
        # A captured conversion, even with a date or the word "today", cannot
        # establish a live rate. This application has no live FX evidence tool.
        return False
    if field == 'accreditation_final_decision_date':
        return _accreditation_decision_date_supported(text, query)
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


_ROMAN_MONTHS = ('I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X', 'XI', 'XII')
_ROMAN_MONTH_PATTERN = '(?:' + '|'.join(sorted(_ROMAN_MONTHS, key=len, reverse=True)) + ')'
_MONTH_DASH = r'\s*[-–—−]\s*'


def _requested_schedule_ranges(query):
    if not ('сар' in query.casefold() and re.search(r'хуваарь|төлөвлө', query, re.I)):
        return []
    pattern = r'(?<!\w)(' + _ROMAN_MONTH_PATTERN + ')' + _MONTH_DASH + '(' + _ROMAN_MONTH_PATTERN + r')(?!\w)'
    ranges = []
    for match in re.finditer(pattern, query, re.I):
        start, end = (_ROMAN_MONTHS.index(value.upper()) + 1 for value in match.groups())
        # A reversed or year-crossing range needs a separate interpretation.
        if start <= end and (start, end) not in ranges:
            ranges.append((start, end))
    return ranges if len(ranges) >= 2 else []


def _field_intent_without_presentation_clauses(query):
    """Ignore bounded answer-format instructions, never a named-field exclusion.

    This local detection view does not rewrite the user's submitted query.
    Unknown negative/restrictive clauses remain intact for the conservative
    exclusion guard below. In particular, a subject-qualified request such as
    'үнэлгээний нэмэлт тайлбар хэрэггүй' is not a presentation-only clause.
    """
    q = query.casefold()
    extra_explanation = (
        r'(?:нэмэлт|илүү|урт|дэлгэрэнгүй)\s+тайлбар(?:ыг)?\s+'
        r'(?:хэрэггүй|шаардлагагүй|бүү\s+нэм|битгий\s+нэм)'
    )
    # Keep delimiters: commas can also express a genuinely requested pair.
    clauses = re.split(r'([.!?;,\n])', q)
    for index in range(0, len(clauses), 2):
        clause = clauses[index]
        stripped = clause.strip()
        if re.fullmatch(extra_explanation, stripped):
            clauses[index] = ''
            continue
        if re.fullmatch(r'(?:зөвхөн|дангаар)\s+(?:товч(?:хон)?|богино(?:хон)?)\s+'
                        r'(?:хариул(?:на\s+уу)?|тайлбарла(?:на\s+уу)?|хэл(?:нэ\s+үү)?)', stripped):
            clauses[index] = re.sub(r'(?<!\w)(?:зөвхөн|дангаар)\s+', '', clause, count=1)
            continue
        # "Only these two, explain them" keeps both named subjects. Restrict
        # this to a complete presentation suffix, so "one of these two" or
        # "only these two's frequency" cannot erase a real scope restriction.
        both_reference = (r'(?:хоёр(?:ыг)?|хоёуланг(?:\s+нь)?|хоёрын\s+талаар|'
                          r'2(?:-?ыг)?|2-?ын\s+талаар)')
        presentation_verb = (r'(?:(?:товч(?:хон)?|тус\s+бүр|тус\s+тус)\s+)?'
                             r'(?:тайлбарла(?:на\s+уу)?|хэл(?:нэ\s+үү)?|'
                             r'хариул(?:на\s+уу)?)')
        clause = re.sub(r'(?<!\w)зөвхөн\s+(?=(?:энэ|эдгээр|тэр)\s+' +
                        both_reference + r'\s+' + presentation_verb + r'\s*$)', '', clause)
        # Also recognise an unpunctuated format suffix after an explicit
        # request verb, without swallowing a subject-qualified exclusion.
        clause = re.sub(r'(?P<request>(?<!\w)(?:харьцуул|тайлбарла|хэлнэ\s+үү|'
                        r'өгнө\s+үү|хариул)(?:на\s+уу)?)\s+' + extra_explanation + r'\s*$',
                        r'\g<request>', clause)
        clauses[index] = clause
    return ''.join(clauses)


def _single_purpose_definition_subject(query):
    """Return one subject only for a fully consumed purpose-only grammar."""
    q = _field_intent_without_presentation_clauses(query).strip(' .!?\n')
    match = re.fullmatch(
        r'(?:(?:чанарын\s+баталгаажуулалтын\s+хуудсанд|эхэд|эхийн\s+хуудсанд)\s+)?'
        r'(?P<subject>мониторинг(?:ийн)?|үнэлгээ(?:ний)?)\s+'
        r'(?:ямар\s+зорилготой(?:\s+гэж\s+(?:тайлбарласан|тодорхойлсон))?\s+(?:бэ|вэ)|'
        r'зорилго\s+юу\s+(?:вэ|бэ)|'
        r'зорилгыг\s+(?:хэл(?:нэ\s+үү|ээрэй)?|тайлбарла(?:на\s+уу)?))', q)
    if match:
        return 'monitoring' if match['subject'].startswith('мониторинг') else 'evaluation'
    return None


def single_purpose_selection_scope(query):
    """Literal identities for conservative root exclusion, not entailment.

    A purpose marker alone cannot certify that a root answers the question.
    The selector may discard an explicitly different subject, while retaining
    every requested-subject or unidentified root for the ordinary guards.
    """
    subject = _single_purpose_definition_subject(query)
    aliases = {'monitoring': r'мониторинг(?:ийн|ийг|оор)?',
               'evaluation': r'үнэлгээ(?:ний|г|гээр)?'}
    if subject is None:
        return None
    return dict(requested_alias=r'мониторинг[а-яёөү]*' if subject == 'monitoring' else r'үнэлгээ[а-яёөү]*',
                other_alias=aliases['evaluation' if subject == 'monitoring' else 'monitoring'],
                requested_subject='мониторинг' if subject == 'monitoring' else 'үнэлгээ',
                other_subject='үнэлгээ' if subject == 'monitoring' else 'мониторинг')


def closed_field_selection_query(query, requirements):
    """Bounded question grammars whose facets are all screened here.

    A nonempty field list alone is not sufficient: it may miss a compound
    question's founder, location, purpose or other unknown facet. Unknown words,
    extra sentences, conditions and numbers therefore disable subset pruning.
    This does not change routing or make other queries unanswerable.
    """
    q = _field_intent_without_presentation_clauses(query).strip(' .!?\n')
    if not requirements or re.search(r'[;:\n]|[.!?].*\S', q):
        return False
    kinds = {field['type'] for field in requirements}
    if kinds == {'school_founding_event'}:
        if {field['facet'] for field in requirements} != {'year'}:
            return False
        school = re.search(r'сургуул\w*|коллеж\w*|коосэн\w*', q)
        if not school:
            return False
        prefix = q[:school.start()].strip(' “"«')
        if (len(prefix.split()) > 5 or re.search(r'[,;.!?]|\b(?:ба|болон|хэн|хаана|хэд\w*|хэзээ|ямар|тоо\w*|оюут\w*|бүл\w*|захирал\w*|нэрл\w*|тайлбарл\w*|хэл\w*|байгуулагч\w*)\b', prefix)
                or re.search(r'[^a-zа-яёөү\s]', prefix)):
            return False
        tail = q[school.end():].strip(' ”"»-')
        return bool(re.fullmatch(
            r'(?:анх\s+)?(?:хэдэн\s+онд\s+байгуулагдсан(?:\s+(?:бэ|вэ|уу))?|'
            r'байгуулагдсан\s+оныг\s+хэл(?:нэ\s+үү|ээрэй)?)', tail))
    elif kinds == {'direction_name_pair'}:
        return bool(re.fullmatch(
            r'(?:чанарын\s+баталгаажуулалтын\s+)?(?:хоёр|2)\s+урсгалын\s+'
            r'чиглэл\s+(?:ба|болон)\s+нэр(?:ийг)?\s+(?:тус\s+тус\s+)?'
            r'хэл(?:нэ\s+үү|ээрэй)?', q))
    elif kinds == {'definition'}:
        subject = _single_purpose_definition_subject(query)
        return bool(subject and {field['name'] for field in requirements} == {subject + '_definition'})
    else:
        return False


def field_evidence_requirements(query):
    """Describe a few explicitly requested facets, without storing answers.

    This development omission screen recognises literal paired subjects and
    requested measurement roles. It does not infer intent for arbitrary prose,
    certify semantic completeness, or add evidence to a model's selection.
    The returned descriptors are JSON-safe for logging and prompt guidance.
    """
    q = _field_intent_without_presentation_clauses(query)
    if re.search(r'зөвхөн|дангаар|хэрэггүй|хас(?:а|ч|на|ах)|\bхас\b|бүү|битгий|'
                 r'асуугаагүй|сонирхохгүй|ялгаагүй|\bбиш\b', q):
        return []
    paired = bool(re.search(r'болон|\bба\b|тус\s+бүр|харьцуул|ялга|хоёул|,|\bмөн\b|\bөөр\b', q))
    requirements = []

    def add(name, label, aliases, kind, **extra):
        requirements.append(dict(name=name, label=label, aliases=aliases, type=kind, **extra))

    requirements.extend(_school_founding_requirements(q))
    requirements.extend(event_requirements(q))
    requirements.extend(facility_floor_requirements(query))
    contact_fields=staff_contact_fields(q)
    if contact_fields:
        staff=staff_query_scope(q,[],catalog=[])
        for field in contact_fields:
            add('staff_contact_'+field,'нэрлэсэн багшийн '+('имэйл' if field=='email' else 'утас'),
                [],'staff_contact',field=field,person=staff.get('person') if staff else None)

    # These descriptors ask for source structure, not any particular direction,
    # flow name, course title, partner or delivery-mode answer.
    if (re.search(r'\b(?:хоёр|2)\s+урсгал\w*', q)
            and 'чиглэл' in q and re.search(r'нэр\w*', q)):
        add('flow_direction_name_pair', 'хоёр урсгалын чиглэл–нэрийн тусдаа холбоо',
            [], 'direction_name_pair')
    if ('хичээл' in q and re.search(r'нэрл\w*|ямар\s+хичээл\w*', q)
            and re.search(r'ямар\s+(?:хэлбэр|горим|арга)\w*|хэрхэн\s+хэрэгжүүл', q)):
        count_match = re.search(r'\b(нэг|хоёр|гурван|дөрвөн|таван|зургаан|[1-6])\s+хичээл\w*', q)
        counts = dict(нэг=1, хоёр=2, гурван=3, дөрвөн=4, таван=5, зургаан=6)
        count = (counts.get(count_match[1], int(count_match[1]) if count_match[1].isdigit() else None)
                 if count_match else None)
        add('course_names_delivery_form', 'асуусан хичээлийн нэрс ба тэдгээрийн сургалтын хэлбэр',
            [r'хичээл\w*'], 'course_delivery_form', requested_count=count,
            named_anchors=sorted(set(token.casefold() for token in re.findall(r'(?<![A-Za-z])[A-Za-z][A-Za-z0-9]+', query))))

    # Separately asked historical years need complementary evidence. A written
    # academic interval stays a single scope in the existing year filter.
    years = sorted(set(re.findall(r'(?<!\d)(?:19|20)\d{2}(?!\d)', q)))
    if (paired and len(years) > 1
            and not re.search(r'(?:19|20)\d{2}\s*[–—-]\s*(?:19|20)\d{2}', q)):
        for year in years:
            add('explicit_year_' + year, year + ' оны асуусан үйл явдал',
                [r'(?<!\d)' + year + r'(?!\d)'], 'explicit_marker')

    # These are two categories explicitly named by the user, not inferred
    # organisation names. A keyword mention alone cannot supply a list field.
    practice_fields = (
        ('practice_industrial_organisations', 'үйлдвэрлэлийн дадлагын байгууллагын жагсаалт',
         r'үйлдвэрлэлийн\s+дадлаг\w*'),
        ('practice_introductory_organisations', 'танилцах дадлагын байгууллагын жагсаалт',
         r'танилцах\s+дадлаг\w*'),
    )
    if (paired and re.search(r'байгууллаг\w*|жагсаа\w*', q)
            and all(re.search(pattern, q) for _, _, pattern in practice_fields)):
        for name, label, pattern in practice_fields:
            add(name, label, [pattern], 'labelled_list',
                excluded_aliases=[other for other_name, _, other in practice_fields if other_name != name])

    if re.search(r'мэдээ|нийтлэл',q):
        if re.search(r'түвшин\s+тогтоо\w*',q):
            if 'хэл' in q and 'түвшинчил' in q:
                add('news_levelled_languages','түвшинчилж ордог хэлний хичээлүүд',[r'хэл\w*'],
                    'news_field',predicate_aliases=[r'түвшинчил\w*'])
            if re.search(r'математик|физик',q) and re.search(r'юунд|ашигла',q):
                add('news_placement_baseline','шалгалтын дүнгийн гарааны үнэлгээний үүрэг',
                    [r'математик\w*|физик\w*'],'news_field',predicate_aliases=[r'гарааны\s+үнэлгээ'])
                add('news_placement_use','дүнг хичээл, заах арга, хөтөлбөрт ашиглах',
                    [r'математик\w*|физик\w*'],'news_field',
                    predicate_aliases=[r'төлөвлөлт|заах\s+арга|хөтөлбөр\w*\s+сайжруул'])
        if re.search(r'хичээл\w*\s+гадна',q) and re.search(r'юу|ямар',q):
            add('news_complementary_activities','хичээлээс гаднах үйл ажиллагаа',
                [r'компани\w*|байгууллаг\w*|соёл\w*|уламжлал\w*|аялал\w*|үзмэр\w*'],
                'news_field',predicate_aliases=[r'танилц\w*|аял\w*|зочил\w*|туршлага\w*|үзэ\w*'])
        grove=bool(re.search(r'(?<!\w)төгөл(?:ийн|ийг|д|тэй|өөс|өөр|үүд)?(?!\w)',q))
        activity=grove or re.search(r'ямар\s+ажил|ажил\s+хий',q)
        if re.search(r'(?<!\w)хаана(?!\w)', q):
            add('news_activity_location','үйл ажиллагаа болсон байршил',
                [r'аймаг\w*|муж\w*|сум\w*|дүүрэг\w*|хот\w*|хүрээлэн\w*|талбай\w*|гол\w*|сургуул\w*|коллеж\w*'],
                'news_field',predicate_aliases=[r'байрл\w*|хураа\w*|ажилл\w*|байгуул\w*|тар[ьи]\w*|болсон|болов|болжээ'])
        if grove and re.search(r'ямар|байгуул|тарь',q):
            add('news_grove_activity','байгуулсан төгөл, хийсэн ажил',[r'төгөл\w*'],
                'news_field',predicate_aliases=[r'байгуул\w*|тар[ьи]\w*'])
        if 'цаашид' in q and 'уламжлал' in q:
            add('news_future_tradition','цаашид хийх уламжлал',[r'уламжлал\w*'],
                'news_field',predicate_aliases=[r'цаашид|тогтмол|жил\s+бүр|улирал\s+бүр|болох\w*'])
        if activity and 'ямар ажил' in q:
            add('news_work_activity','ямар ажил хийсэн',[r'ажил\w*|хураа\w*|тар[ьи]\w*'],
                'news_field',predicate_aliases=[r'хураа\w*|ажилла\w*|гүйцэтгэ\w*|хий\w*'])
        if activity and re.search(r'чадвар|үнэт\s+зүйл',q):
            add('news_work_learning','ажлаас олсон чадвар, үнэт зүйл',
                [r'чадвар\w*|үнэ\s*цэн\w*|хариуцлаг\w*|үнэт\s+зүйл'],
                'news_field',predicate_aliases=[r'мэдэр\w*|эзэмш\w*|ойлго\w*|сурч|олго\w*'])
        if re.search(r'ямар|мэдлэг|чадвар|чиглэл',q):
            for quoted in re.finditer(r'[«“"]([^»”"]{3,100})[»”"]\s+сургалт\w*',q):
                add('news_training_content','нэрлэсэн сургалтын мэдлэг, чадвар',
                    [re.escape(quoted[1])],'news_field',predicate_aliases=[r'мэдлэг|чадвар|арга\s+хэмжээ'])

    for start, end in _requested_schedule_ranges(query):
        roman_start, roman_end = _ROMAN_MONTHS[start - 1], _ROMAN_MONTHS[end - 1]
        interval = '(?:' + roman_start + _MONTH_DASH + roman_end + '|' + str(start) + _MONTH_DASH + str(end) + ')'
        add('schedule_months_' + str(start) + '_' + str(end),
            roman_start + '–' + roman_end + ' сарын төлөвлөсөн ажил',
            [r'(?<!\w)' + interval + r'(?:-р)?\s*сар(?:д|ын)?(?!\w)'], 'schedule',
            month_start=start, month_end=end)

    single_definition = _single_purpose_definition_subject(query)
    if (single_definition or (paired and 'мониторинг' in q and 'үнэлгээ' in q
            and re.search(r'ялга|харьцуул|зорил|давтамж|тайлбар|тодорхойл', q))):
        subjects = (
            ('monitoring', 'мониторинг', [r'мониторинг(?:ийн|ийг|оор)?']),
            ('evaluation', 'үнэлгээ', [r'үнэлгээ(?:ний|г|гээр)?']),
        )
        for name, label, aliases in subjects:
            if single_definition and name != single_definition:
                continue
            add(name + '_definition', label + 'ийн зорилго, тайлбар', aliases, 'definition',
                # A purpose-only question cannot be satisfied by a report of
                # yesterday's activity. Broader paired definitions retain the
                # original descriptive screen; subset pruning needs explicit
                # purpose wording before discarding a complementary root.
                predicate_aliases=([r'\bзорилго(?:той|ор)\b'] if single_definition else
                    [r'зорилготой|зорилгоор|чиглэ\w*|хяна\w*|үнэлж|сайжруул\w*|дэмжин\s+зөвл']))
            if 'давтамж' in q or re.search(r'хэр\s+ойрхон|хэдийд|үе\s+тутам', q):
                add(name + '_frequency', label + 'ийн давтамж', aliases, 'definition',
                    predicate_aliases=[r'өдөр\s+тут\w*|өдөр\s+бүр|байнг\w*|тасралтгүй|'
                                       r'давтамж\w*|хугацааны\s+давтамж|тогтмол|сар\s+бүр|жил\s+бүр|улирал\s+тутам'])

    if (paired and re.search(r'(?<!\w)cad(?!\w)', q) and re.search(r'(?<!\w)cam(?!\w)', q)
            and re.search(r'чадвар|зорил|холб|ялга|харьцуул|эзэмш|зориул', q)):
        for name in ('cad', 'drafter', 'cam'):
            if re.search(r'(?<!\w)' + name + r'(?!\w)', q):
                add(name + '_objective', name.upper() + ' хэрэглэсэн чадвар, зорилт',
                    [r'(?<!\w)' + name + r'(?!\w)'], 'objective',
                    predicate_aliases=[r'эзэмшүүл\w*|эзэмших|чадвар\w*.{0,30}олго\w*|сургах|технолог\w*.{0,30}эзэмш'],
                    excluded_aliases=[] if 'клуб' in q else [r'клуб\w*'])

    classroom = bool(re.search(r'сургалтын\s+анги|ердийн\s+анги|анги\s*танхим', q))
    if (paired and classroom and 'лаборатор' in q and re.search(r'суудал|багтаамж', q)
            and re.search(r'өрөө|танхим|хэдэн\s+анги', q)):
        for name, label, aliases in (
            ('classroom', 'анги танхим', [r'(?:сургалтын\s+)?анги\s*танхим\w*|сургалтын\s+анги\w*|ердийн\s+анги\w*']),
            ('laboratory', 'лаборатори', [r'лаборатор\w*']),
        ):
            add(name + '_rooms', label + 'ын өрөөний тоо', aliases, 'measurement',
                object=name, units=[r'\d+\s*(?:анги(?:\s*танхим)?|өрөө|танхим|лаборатор\w*)'])
            add(name + '_seats', label + 'ын суудлын тоо', aliases, 'measurement',
                object=name, units=[r'\d+(?:[.,]\d+)*\s*(?:хүний\s*)?суудал'])

    library = bool(re.search(r'номын\s+сан', q))
    program = _queried_library_program(query) if library else None
    software_year = (library and (program or re.search(r'программ?', q))
                     and re.search(r'(?<!\w)(?:он(?:ы|ыг|оос|оор|д|доо)?|'
                                   r'жил(?:ийн|ийг|ээс|ээр|д|дээ)?|хэзээ(?:нээс)?)(?!\w)', q)
                     and re.search(r'ашигл\w*.{0,20}эхэл|нэвтрүүл|хэрэгл\w*.{0,20}эхэл', q))
    stock_matches = list(re.finditer(r'номын\s+(?:нийт\s+)?(?:тоо|үзүүлэлт)|нийт\s+ном|хэдэн\s+ном', q))
    stock_requested = any(not re.search(r'нэг\s+оюутанд|оюутан\s+тутам|ногдох',
                                       re.split(r'болон|\bба\b|,', q[:match.start()])[-1])
                          for match in stock_matches)
    ratio_requested = bool(re.search(r'нэг\s+оюутанд|оюутан\s+тутам|ногдох', q))
    if paired and software_year and (stock_requested or ratio_requested):
        if stock_requested:
            add('library_stock_total', 'номын сангийн нийт номын тоо', [r'ном(?:,?\s+сурах\s+бичиг)?'], 'library_stock')
        name = _program_name_key(program[0]) if program else None
        add('library_software_start_year', 'номын сангийн программ ашиглаж эхэлсэн он',
            [r'(?<!\w)' + re.escape(name) + r'(?!\w)'] if name else [r'программ?\w*'],
            'software_start_year', program_name=name)
        if ratio_requested:
            add('library_per_student_ratio', 'нэг оюутанд ногдох номын хэмжээ', [r'ном'], 'library_ratio')

    named_acronym = bool(re.search(r'(?<!\w)[A-Z][A-Z0-9]{1,7}(?!\w)', query))
    if (paired and named_acronym and 'хичээл' in q and re.search(r'ажлын\s+ярилцлаг', q)
            and re.search(r'хамт|компани|түнш', q)
            and re.search(r'явц|дурд|хэрэгж|сайжруул|амжилт|оролц|хичээл', q)):
        add('course_content', 'хамтын ажиллагааны хичээл, хэрэгжилт', [r'хичээл\w*'], 'course',
            predicate_aliases=[r'хэрэгжүүл\w*|сайжруул\w*|заа(?:х|сан|даг|ж)\w*|онлайн\w*'])
        add('job_interview_progress', 'ажлын ярилцлагын явц', [r'ажлын\s+ярилцлаг\w*'], 'progress',
            predicate_aliases=[r'оролц\w*|тэнц\w*|эхэл\w*|дуус\w*|амжилт\w*|үргэлжил\w*'])
    return requirements


def _definition_regions(text, requirement, requirements):
    """Keep a labelled definition apart from the other subject's definition."""
    labels = [alias for item in requirements if item['type'] == 'definition' for alias in item['aliases']]
    # A single-purpose contract still needs the other subject as a boundary:
    # its purpose predicate cannot fill a missing definition of the first one.
    if requirement['name'] in {'monitoring_definition', 'evaluation_definition'}:
        labels = list(dict.fromkeys(labels + [r'мониторинг(?:ийн|ийг|оор)?', r'үнэлгээ(?:ний|г|гээр)?']))
    starts = []
    for label in labels:
        for match in re.finditer(label, text, re.I):
            line_start = text.rfind('\n', 0, match.start()) + 1
            line_end = text.find('\n', match.end())
            line_end = len(text) if line_end < 0 else line_end
            before, after = text[line_start:match.start()].strip(), text[match.end():line_end].strip()
            if ((not before or re.search(r'[.!?]\s*$', before))
                    and (not after or re.match(r'^(?:нь|бол|гэдэг|гэж|зорилго\s+нь|[:—-])(?:\s|$)', after))):
                starts.append((match.start(), match.end(), label))
    starts = sorted(set(starts))
    for start, end, label in starts:
        if label not in requirement['aliases']:
            continue
        next_subject = min((a for a, _, other in starts if a > start and other not in requirement['aliases']), default=len(text))
        if requirement['name'] in {'monitoring_definition', 'evaluation_definition'}:
            # A second literal subject bounds the region even after an
            # unrecognised connector/semicolon. Treating it as an object can
            # conservatively reject a valid definition; borrowing its purpose
            # could instead discard the only correct requested-purpose root.
            opposing = [alias for alias in labels if alias not in requirement['aliases']]
            mentions = [match.start() for alias in opposing for match in re.finditer(
                r'(?<!\w)(?:' + alias + r')(?!\w)', text, re.I) if match.start() > start]
            next_subject = min([next_subject, *mentions])
        yield text[start:min(next_subject, end + 650)]


def _measurement_present(text, requirement):
    # A count may share its line with a label; a seat count may instead follow
    # that label. The nearest explicit facility wins, so a lecture hall's seats
    # cannot fill a laboratory omission. Never combine separate selected units.
    objects = [
        ('classroom', r'(?:сургалтын\s+)?анги\s*танхим\w*|сургалтын\s+анги\w*|ердийн\s+анги\w*'),
        ('laboratory', r'лаборатор\w*'),
        ('library', r'номын\s+сан\w*'),
        ('hub', r'(?<!\w)hub(?:\s+center)?(?!\w)'),
    ] + [(label, pattern) for label, pattern in _FACILITY_KINDS
         if label not in {'сургалтын анги', 'лаборатори'}]
    anchors = [(match.start(), match.end(), name) for name, pattern in objects
               for match in re.finditer(pattern, text, re.I)]
    for unit in requirement['units']:
        for value in re.finditer(unit, text, re.I):
            inline = [anchor for anchor in anchors if value.start() <= anchor[0] < value.end()]
            preceding = [anchor for anchor in anchors if anchor[1] <= value.start()
                         and value.start() - anchor[1] <= 300]
            candidates = inline or preceding
            if candidates and max(candidates, key=lambda anchor: anchor[0])[2] == requirement['object']:
                return True
    return False


def _schedule_present(text, requirement):
    """Match a requested month row inside one explicitly labelled schedule.

    This recognises a table's label/range/task structure, not whether its task
    is the right real-world activity. Source IDs, expected tasks and years are
    deliberately absent. A date mentioned in an article is not a schedule row.
    """
    labels = []
    for line in re.finditer(r'[^\n]+', text):
        value = line.group().strip()
        heading = re.fullmatch(r'[\w\s–—-]{0,65}(?:хуваарь|төлөвлөгөө)\s*[:：]?', value, re.I)
        inline = re.match(r'^[\w\s–—-]{0,65}(?:хуваарь|төлөвлөгөө)\s*[:：]', value, re.I)
        if heading or inline:
            labels.append(line.start() + (heading.end() if heading else inline.end()))
    if not labels:
        return False
    any_month = '(?:' + _ROMAN_MONTH_PATTERN + r'|\d{1,2})'
    next_interval = re.compile(r'(?<!\w)' + any_month + _MONTH_DASH + any_month + r'(?:-р)?\s*сар(?:д|ын)?(?!\w)', re.I)
    for alias in requirement['aliases']:
        for match in re.finditer(alias, text, re.I):
            preceding_labels = [position for position in labels if position <= match.start()]
            if not preceding_labels:
                continue
            before = text[max(preceding_labels):match.start()]
            if re.search(r'нийтэл|нийтлэгд|мэдээний\s+огноо', before, re.I):
                continue
            following = text[match.end():]
            other = next_interval.search(following)
            if other:
                following = following[:other.start()]
            rows = [row.strip(' \t:：—–-.,;') for row in following.splitlines()
                    if row.strip(' \t:：—–-.,;')]
            # A table index and a later unrelated paragraph cannot fill an
            # empty task cell. The first actual row must itself be substantive.
            if not rows or re.fullmatch(r'[\d\W]+', rows[0]):
                continue
            task = rows[0]
            if (len(re.findall(r'[^\W\d_]', task, re.UNICODE)) >= 4
                    and not re.search(r'байхгүй|тодорхойгүй|төлөвлөөгүй|нийтэл|мэдээний\s+огноо', task, re.I)):
                return True
    return False


def _library_stock_present(text):
    integer = r'(?:\d{1,3}(?:,\d{3})+|\d+)\+?'
    pattern = r'(?<![\w\d.,–—-])' + integer + r'(?![\d.,–—-])\s*ном(?:,?\s+сурах\s+бичиг)?(?:той)?(?!\w)'
    for match in re.finditer(pattern, text, re.I):
        # Keep a per-student amount separate even if its number is an integer.
        start = max(text.rfind('\n', 0, match.start()), text.rfind('. ', 0, match.start())) + 1
        end = text.find('\n', match.end())
        clause = text[start:end if end >= 0 else len(text)]
        preceding = text[:start].strip().splitlines()
        per_student_heading = bool(preceding and re.fullmatch(r'нэг\s+оюутанд|оюутан\s+тутамд?', preceding[-1].strip(), re.I))
        if not per_student_heading and not re.search(r'нэг\s+оюут|оюутанд|ногд|ноогд|тутам', clause, re.I):
            return True
    return False


def _library_software_year_present(text, requirement):
    for clause in re.split(r'\n|(?<=[.!?])\s+', text):
        if not (re.search(r'программ?\w*', clause, re.I)
                and any(re.search(alias, clause, re.I) for alias in requirement['aliases'])
                and re.search(r'(?<!\d)(?:19|20)\d{2}(?!\d)', clause)):
            continue
        name = requirement.get('program_name')
        if name and not re.search(r'(?<!\w)' + re.escape(name) + r'\s+(?:олон\s+улсын\s+)?программ?\w*', clause, re.I):
            continue
        if re.search(r'ашиглаагүй|нэвтрүүлээгүй|эхлээгүй|төлөвлө|\bбиш\b', clause, re.I):
            continue
        if (re.search(r'(?:19|20)\d{2}\s+оноос.{0,45}(?:ашигл|хэрэгл)', clause, re.I)
                or re.search(r'нэвтрүүл\w*|(?:ашигл|хэрэгл)\w*.{0,20}эхэл', clause, re.I)):
            return True
    return False


def _library_ratio_present(text):
    for clause in re.split(r'\n|(?<=[.!?])\s+', text):
        if (re.search(r'нэг\s+оюутанд|оюутан\s+тутамд?', clause, re.I)
                and re.search(r'\d+(?:[.,]\d+)?(?:\s*[-–—]\s*\d+(?:[.,]\d+)?)?\s*ном', clause, re.I)
                and re.search(r'ногд|ноогд', clause, re.I)):
            return True
    return False


def _labelled_list_present(text, requirement):
    """A requested label with its own immediately following captured list rows.

    This detects a bounded structural omission, not the truth/exhaustiveness of
    the organisations or the semantic meaning of arbitrary prose.
    """
    lines = [line.strip() for line in text.splitlines()]
    for index, line in enumerate(lines):
        if (len(line) > 160 or not any(re.search(alias, line, re.I) for alias in requirement['aliases'])
                or any(re.search(alias, line, re.I) for alias in requirement.get('excluded_aliases', []))
                or re.search(r'\bбиш\b|(?<!\w)(?:хий|явуул|явагд|хамрагд|бай)[а-яёөү]*гүй(?!\w)', line, re.I)):
            continue
        following = index + 1
        while following < len(lines) and not lines[following]:
            following += 1
        if following < len(lines) and re.match(r'^(?:•\s+\S|\d{1,2}[.)]\s+\S)', lines[following]):
            return True
    return False


def _course_delivery_form_present(text, requirement):
    # The named source section and its own course clause must stay together.
    # Another selected company's online paragraph cannot fill this field.
    if any(not re.search(r'(?<![A-Za-z0-9])' + re.escape(anchor) + r'(?![A-Za-z0-9])', text, re.I)
           for anchor in requirement['named_anchors']):
        return False
    mode = r'онлайнаар|цахимаар|танхимаар|биечлэн|хосолсон\s+хэлбэрээр|зайнаас'
    for clause in re.split(r'\n|[;；]|(?<=[.!?])\s+', text):
        courses = list(re.finditer(r'хичээл\w*', clause, re.I))
        titles = re.findall(r'[“"«]([^”"»\n]+)[”"»]', clause)
        needed = requirement.get('requested_count') or 1
        if (not courses or len(set(title.strip().casefold() for title in titles)) < needed
                or not re.search(r'хэрэгжүүл\w*|явагд\w*|явуул\w*|заа(?:сан|даг|ж|х)\w*', clause, re.I)
                or re.search(r'\bбиш\b|байхгүй|тодорхойгүй|эсэх|магадгүй|'
                             r'(?:хэрэгж|явуул|явагд|заа|бай)[а-яёөү]*гүй\b', clause, re.I)):
            continue
        for form in re.finditer(mode, clause, re.I):
            preceding = [course for course in courses if course.end() <= form.start()]
            if not preceding:
                continue
            between = clause[preceding[-1].end():form.start()]
            if (len(between) <= 120 and not re.search(
                    r'тэмцээн|өдөрлөг|уулзалт|ярилцлага|бүртгэл', between, re.I)):
                return True
    return False


def missing_field_evidence(requirements, units_or_text):
    """Return absent facet names, checking each selected unit independently.

    Literal labels and local predicate/measurement markers only screen known
    omissions. A successful match is not proof of truth, scope or completeness.
    """
    texts = [units_or_text] if isinstance(units_or_text, str) else list(units_or_text)
    if not all(isinstance(text, str) for text in texts):
        raise TypeError('Supply selected evidence text strings.')
    missing = []
    for requirement in requirements:
        found = False
        for text in texts:
            if requirement['type'] == 'explicit_marker':
                found = any(re.search(alias, text, re.I) for alias in requirement['aliases'])
            elif requirement['type'] == 'historical_event':
                found = event_supported(requirement, text)
            elif requirement['type'] == 'facility_floor':
                found = bool(facility_floor_records(text,requirement))
            elif requirement['type'] == 'staff_contact':
                found=any(requirement['field'] in card['fields'] and (not requirement.get('person')
                    or _staff_person_key(requirement['person'])==_staff_person_key(card['person']))
                    for card in staff_contact_cards(text))
            elif requirement['type'] == 'school_founding_event':
                found = _school_founding_fields_present(text, requirement)
            elif requirement['type'] == 'direction_name_pair':
                found = len({item['direction'] for item in direction_card_bindings(text)}) == 2
            elif requirement['type'] == 'course_delivery_form':
                found = _course_delivery_form_present(text, requirement)
            elif requirement['type'] == 'labelled_list':
                found = _labelled_list_present(text, requirement)
            elif requirement['type'] == 'schedule':
                found = _schedule_present(text, requirement)
            elif requirement['type'] == 'library_stock':
                found = _library_stock_present(text)
            elif requirement['type'] == 'software_start_year':
                found = _library_software_year_present(text, requirement)
            elif requirement['type'] == 'library_ratio':
                found = _library_ratio_present(text)
            elif requirement['type'] == 'measurement':
                found = _measurement_present(text, requirement)
            else:
                if requirement['type'] == 'definition':
                    regions = _definition_regions(text, requirement, requirements)
                else:
                    # Do not let another sentence's objective or progress verb
                    # support a mere keyword mention in this sentence.
                    regions = [clause for clause in re.split(r'\n|(?<=[.!?])\s+', text)
                               if any(re.search(alias, clause, re.I) for alias in requirement['aliases'])]
                for region in regions:
                    if (any(re.search(alias, region, re.I) for alias in requirement['predicate_aliases'])
                            and not any(re.search(alias, region, re.I) for alias in requirement.get('excluded_aliases', []))
                            and not re.search(r'\bбиш\b|(?:эзэмшүүл|оролц|хэрэгжүүл|сайжруул|чиглэ|үнэл|тэнц|олго|мэдэр|байгуул|ажилла)\w*гүй', region, re.I)):
                        found = True
                        break
            if found:
                break
        if not found:
            missing.append(requirement['name'])
    return missing


def _office_floor_phone_request(query, *, unsafe=False):
    """A bounded office/field contract independent of one sentence template.

    Subject inflections and requested attributes are recognised separately.
    Every remaining word must be grammatical or a bounded request/visit word;
    unfamiliar names, another office, dates and additional fields cannot be
    discarded merely because floor and phone also occur in the question.
    """
    office = r'(?<!\w)сургалтын\s+алба(?:ны|нд|тай|наас)?(?!\w)'
    floor = r'(?<!\w)(?:давхар(?:т|ын|ыг)?|давхрыг|давхрын)(?!\w)'
    phone = r'(?<!\w)(?:утас(?:ны)?|утсыг|утсаар|дугаар(?:ыг|ын)?)(?!\w)'
    if not (re.search(office,query,re.I)
            and re.search(r'(?<!\w)(?:давхар|давхр)\w*',query,re.I)
            and re.search(r'(?<!\w)(?:утас|утс|дугаар)\w*',query,re.I)):
        return None
    # Separate coordinated fields from a location question about a telephone:
    # a phone being on a floor does not ask for the office's phone number.
    clauses = re.split(r',|(?<!\w)(?:ба|болон|мөн|бас)(?!\w)',query,flags=re.I)
    separate_fields = (any(re.search(floor,part,re.I) and not re.search(phone,part,re.I)
                           for part in clauses)
                       and any(re.search(phone,part,re.I) and not re.search(floor,part,re.I)
                               for part in clauses)
                       and not any(re.search(floor,part,re.I) and re.search(phone,part,re.I)
                                   for part in clauses))
    remaining = re.sub(office,' ',query,flags=re.I)
    remaining = re.sub(floor,' ',remaining,flags=re.I)
    remaining = re.sub(phone,' ',remaining,flags=re.I)
    grammar = frozenset('''сайн байна уу үү энэ тэр тус тэдний нь надад манай танай
        алба албаны очих уулзах гэсэн юм аа хэд хэдэн аль хэддүгээр ямар юу вэ бэ
        болон ба мөн бас байрлах байрладаг байрлаж байдаг байгаа дээр өөрийнх болохыг холбоо барих
        мэдээлэл мэдээллийг мэдээлнэ хэл хэлж хэлнэ өгөөч өгнө өгч танилцуулаач
        хэрэгтэй хүсэж хүссэн асууж талаар мэдмээр'''.split())
    words = set(re.findall(r'\w+',remaining.casefold()))
    unknown = words - grammar
    # In particular, neither a supplied year nor a proposed floor/phone value
    # is a harmless request word. Source cards must not erase that constraint.
    closed = bool(not unsafe and not unknown and separate_fields
                  and not re.search(r'\d|[^\w\s,.!?-]',remaining))
    meaning_guard = bool(re.search(r'\bбиш\b|\bүгүй\b|\w+гүй\b|хэрэв|зөвхөн|боловч|эсвэл|тохиолдолд',query,re.I))
    return dict(kind='office_floor_phone',requested_fields=['office_floor','office_phone'],
                closed=closed,unsafe=bool(unsafe),negated_or_conditional=meaning_guard,
                unparsed_scope=not closed and not meaning_guard)


def _cooperation_month_platform_slots(query):
    """Recognise compound date/platform requests in either field order.

    The literal company remains a requested identity, not an alias guessed
    from a known answer. Only the supplied source cards can establish it.
    """
    latin = list(re.finditer(r'(?<![a-z0-9])(?P<name>[a-z][a-z0-9]*(?:[ -]+[a-z][a-z0-9]*)*)'
        r'(?:-(?:ийн|ын|тай|тэй)|(?:ийн|тай|тэй))?',query,re.I))
    entity = latin[0]['name'].strip() if len(latin)==1 else None
    remaining = query
    for match in reversed(latin):
        remaining=remaining[:match.start()]+' '+remaining[match.end():]
    grammar = frozenset('''компьютерын компьютерийн ухааны тэнхим тэнхимийн
        компани компанийн компанитай тус нь хамтын ажиллагаа ажиллагаагаа ажиллагааны
        платформ платформын платформыг нэр нэрийг нэрлээд нэрлэж аль ямар юу хэд хэдэн
        хэзээ хэзээнээс он оны оныг онд сар сарын сард сараас сарыг эхэлсэн эхлүүлсэн эхлүүлж эхэлж эхлэх
        ашигладаг ашиглаж ашигласан ашиглах хэрэглэдэг сургалтад сургалтанд сургалт сургалтын
        болон ба мөн бас вэ бэ уу үү хэлж хэлнэ хэл өгнө өгөөч мэдээлэл мэдээллийг
        танилцуулаач байна байгаа'''.split())
    unknown=set(re.findall(r'\w+',remaining.casefold()))-grammar
    date_role=False
    for clause in re.split(r',|(?<!\w)(?:болон|ба|мөн|бас)(?!\w)',query,flags=re.I):
        owner=re.search(r'хамтын\s+ажиллагаа\w*',clause,re.I)
        starts=list(re.finditer(r'(?<!\w)(?:эхэлсэн|эхлүүлсэн|эхлүүлж|эхэлж|эхлэх)(?!\w)',clause,re.I))
        calendars=list(re.finditer(r'(?<!\w)(?:хэзээ|хэзээнээс|сар|сард|сараас|сарыг|сарын|он|оны|оныг|онд)(?!\w)',clause,re.I))
        if owner and any('платформ' not in clause[min(owner.start(),start.start(),calendar.start()):
                max(owner.end(),start.end(),calendar.end())].casefold() for start in starts for calendar in calendars):
            date_role=True
    return dict(entity=entity,closed_grammar=not unknown and date_role and len(latin)<=1
                and not re.search(r'\d|[^\w\s,.!?-]',remaining))


def _student_table_request(query, *, unsafe=False):
    """Requested year, named department, total and every recorded course.

    A nominal attribute list and a full question share these same slots. The
    source plan still checks title identity, a contiguous complete table and
    its total; this parser never supplies student counts or course counts.
    """
    if unsafe or not (re.search(r'(?<!\w)нийт(?!\w)',query,re.I)
            and re.search(r'оюут(?:ан|ны|нууд)|суралцагч',query,re.I)
            and re.search(r'(?<!\w)курс(?:ийн)?\s+(?:тус\s+)?бүр(?:ийн)?(?!\w)',query,re.I)):
        return None
    years=list(re.finditer(r'(?<!\d)((?:19|20)\d{2})\s*[–—-]\s*((?:19|20)\d{2})(?!\d)',query))
    if len(years)!=1 or int(years[0][1])>=int(years[0][2]):return None
    year=years[0][1]+'–'+years[0][2]
    without_year=query[:years[0].start()]+' '+query[years[0].end():]
    scopes=list(re.finditer(r'(?<!\w)тэнхим(?:ийн|д)?(?!\w)',without_year,re.I))
    if len(scopes)!=1:return None
    grammar=frozenset('''оны онд он хичээлийн жилд жилийн нийт суралцагч суралцагчийн
        суралцагчид оюутан оюутны оюутнууд оюутантай суралцаж курс курсийн тус бүр бүрийн
        тоо тоог нь хэд хэдэн хэдтэй болон ба мөн бас вэ бэ уу үү хэл хэлж хэлнэ өгнө өгөөч
        мэдээлэл мэдээллийг танилцуулаач байна байгаа'''.split())
    before=without_year[:scopes[0].start()]
    department_words=[word for word in re.findall(r'\w+',before.casefold()) if word not in grammar]
    after=without_year[scopes[0].end():]
    if (not 1<=len(department_words)<=6 or set(re.findall(r'\w+',after.casefold()))-grammar
            or re.search(r'\d|[^\w\s,.!?-]',without_year)):
        return None
    return dict(kind='department_student_table',year=year,department=' '.join(department_words),
                all_courses=True,closed=True)


def followup_field_request(query):
    """Small source-field contracts; unknown clauses never authorize pruning.

    A separate entity line is a server-issued clarification constraint. It
    supplies only the organisation, preserving the original question verbatim.
    """
    scoped = re.fullmatch(r'([\s\S]+)\nХамтын ажиллагааны байгууллага:\s*([^\n]{1,80})', query, re.I)
    body, entity = (scoped[1], scoped[2].strip()) if scoped else (query, None)
    q = _field_intent_without_presentation_clauses(body).strip(' .!?\n')
    unsafe = bool(re.search(r'\bбиш\b|\bүгүй\b|\w+гүй\b|хэрэв|зөвхөн|боловч|эсвэл|тохиолдолд|'
                            r'[;:\n]|[.!?].*\S', q, re.I))
    # Missing entity recognition does not assert that the remaining raw STT
    # wording is fully understood. It only offers a source-backed identity.
    if (re.search(r'хамтын\s+ажиллагаа', q, re.I) and 'платформ' in q
            and re.search(r'сар|хэзээ', q, re.I)):
        name = r'(?P<company>[a-z][a-z0-9 ]{1,65}?)(?:-тэй|-тай|тэй|тай|\s+компанитай)'
        prefix = r'(?:компьютер(?:ын|ийн)\s+ухааны\s+тэнхим\s+)?'
        predicate = r'хамтын\s+ажиллагаа(?:гаа)?\s+хэдэн\s+оны\s+хэдэн\s+сараас\s+эх(?:элсэн|лүүлж)\s*[, ]\s*'
        platform = r'(?:компанийн\s+)?ямар\s+платформыг\s+сургалтад\s+ашиглаж\s+эхэлсэн\s+(?:вэ|бэ)'
        match = re.fullmatch(prefix + name + r'\s+' + predicate + platform, q, re.I)
        slots = _cooperation_month_platform_slots(q)
        detected=match['company'].strip() if match else slots['entity']
        conflict=bool(entity and detected and entity.casefold()!=detected.casefold())
        latin=set(re.findall(r'[a-z][a-z0-9]*',body.casefold()))
        scoped_partial=bool(scoped and not unsafe and not conflict
            and latin <= set(re.findall(r'[a-z][a-z0-9]*',entity.casefold()))
            and not (set(re.findall(r'\d+',body))-set(re.findall(r'(?:19|20)\d{2}',body))))
        closed=bool((match or slots['closed_grammar']) and (entity or detected) and not unsafe and not conflict)
        return dict(kind='cooperation_month_platform', entity=entity or detected,
                    body=body, closed=closed, unsafe=unsafe,
                    conflicting_entity=conflict,
                    partial_scope=scoped_partial and not closed,
                    requested_fields=['cooperation_start_month','cooperation_platform'])
    office = _office_floor_phone_request(q,unsafe=unsafe)
    if office:
        return office
    stats = re.fullmatch(r'(?P<year>(?:19|20)\d{2}\s*[–—-]\s*(?:19|20)\d{2})\s+оны\s+'
        r'(?:хичээлийн\s+жилд\s+)?(?P<department>[а-яёөү ]{3,65}?)\s+тэнхимд\s+'
        r'нийт\s+хэдэн\s+оюутан\s+суралцаж\s*,?\s*'
        r'(?:нэгдүгээрээс\s+тавдугаар|1\s*[–—-]\s*5-р)\s+курс\s+тус\s+бүр\s+хэдэн\s+оюутантай\s+(?:вэ|бэ)',q,re.I)
    if stats and not unsafe:
        return dict(kind='department_student_table', year=re.sub(r'\s*[–—-]\s*','–',stats['year']),
                    department=stats['department'], first_course=1,last_course=5,closed=True)
    nominal_table=_student_table_request(q,unsafe=unsafe)
    if nominal_table:return nominal_table
    arc = re.fullmatch(r'(?P<year>(?:19|20)\d{2}\s*[–—-]\s*(?:19|20)\d{2})\s+оны\s+'
        r'намар\s+(?P<company>[a-z][a-z0-9 ]{1,65}?)(?:-ийн|ийн)\s+дэмжлэгээр\s+'
        r'хэдэн\s+мэргэжлийн\s+хичээл\s+хэрэгжүүлсэн\s+(?:вэ|бэ)',q,re.I)
    if arc and not unsafe:
        return dict(kind='cooperation_course_count',year=re.sub(r'\s*[–—-]\s*','–',arc['year']),
                    entity=arc['company'].strip(),closed=True)
    return None


def _closed_structured_question(query):
    """Recognise complete field grammars, never a bag of overlapping words.

    Unknown qualifiers, dates, comparisons and additional requests retain the
    ordinary RAG path. Descriptors contain requested roles, not answer values.
    """
    q = _field_intent_without_presentation_clauses(query).strip(' .!?\n')
    if re.search(r'\d|[;:\n]|[.!?].*\S', q):
        return None
    patterns = (
        ('facility_rooms', r'hub\s*(?:center)?(?:-?д|т)?\s+'
         r'(?:(?:багийн\s+ажил\s+хийх|багаар\s+ажиллах)\s+өрөө)\s*[, ]\s*'
         r'(?:(?:болон|ба|мөн)\s+)?сэтгэл\s*зүйчийн\s+өрөө\s+'
         r'(?:байдаг|бий)\s+(?:уу|юу|вэ|бэ)'),
        ('internship_application', r'японд\s+дадлага\s+хийхийн\s+тулд\s+'
         r'хэн\s+хүсэлт\s+гаргаж\s*,?\s*ямар\s+ярилцлага\s+өгдөг\s+(?:вэ|бэ)'),
        ('pathway_language', r'япон\s+коосэнд\s+дэвшин\s+суралцахад\s+'
         r'(?P<language>япон|англи)\s+хэлний\s+ямар\s+түвшин\s+(?:хэрэгтэй|шаардлагатай)\s+(?:вэ|бэ)'),
        ('member_absence', r'оюутны\s+зөвлөлийн\s+гишүүн\s+шалтгаангүй\s+'
         r'хэд(?:эн\s+удаа)?\s+тасалбал\s+ямар\s+арга\s+хэмжээтэй\s+(?:вэ|бэ)'),
    )
    for kind, pattern in patterns:
        match = re.fullmatch(pattern, q, re.I)
        if match:
            return dict(kind=kind, **match.groupdict())
    return None


def _overlapping_source_windows(sources):
    """Merge only byte-identical overlapping windows of one captured page.

    This does not read another source or fill a gap. Retain original sources so
    every returned field can be mapped back to one original contiguous quote.
    Any inconsistent overlapping capture invalidates that URL/version group.
    """
    groups = {}
    for source in sources:
        text, start, end = (source.get(key) for key in ('text', 'start_offset', 'end_offset'))
        if (source.get('text_scope') != 'main_element' or not isinstance(text, str)
                or type(start) is not int or start < 0 or end != start + len(text)
                or not source.get('url') or source.get('version') is None):
            continue
        groups.setdefault((source['url'], source['version']), []).append(source)
    for group in groups.values():
        ordered = sorted(group, key=lambda source: (source['start_offset'], -len(source['text'])))
        windows, bad = [], False
        for source in ordered:
            start, text = source['start_offset'], source['text']
            if not windows or start > windows[-1]['end']:
                windows.append(dict(start=start, end=start + len(text), text=text, sources=[source]))
                continue
            window = windows[-1]
            overlap = min(window['end'] - start, len(text))
            if window['text'][start-window['start']:start-window['start']+overlap] != text[:overlap]:
                bad = True
                break
            if start + len(text) > window['end']:
                window['text'] += text[overlap:]
                window['end'] = start + len(text)
            window['sources'].append(source)
        if not bad:
            yield from windows


def _source_lines(text):
    return [(match.start() + len(match[0]) - len(match[0].lstrip()),
             match.start() + len(match[0].rstrip()), match[0].strip())
            for match in re.finditer(r'[^\n]+', text) if match[0].strip()]


def _unsafe_field_prefix(lines, index):
    """A local dated/qualified heading cannot silently lose its scope."""
    for _, _, line in lines[max(0, index - 2):index]:
        if (re.search(r'хэрэв|зөвхөн|\bбиш\b|хуучин|төлөвлө|магадгүй|хамаарахгүй', line, re.I)
                or (re.search(r'(?<!\d)(?:19|20)\d{2}(?!\d)', line)
                    and (not line.endswith(('.', '!', '?', '。'))
                         or re.search(r'журам|шаардлага|нөхцөл|хуваарь|мөрдө|үйлчил|хүчинтэй', line, re.I)))):
            return True
    return False


def _closes_field_list(line):
    return (len(line) <= 100 and not line.endswith(('.', '!', '?', '。'))
            and not re.search(r'хэрэв|зөвхөн|\bбиш\b|харин|гэхдээ|тохиолдолд|'
                              r'хамаарахгүй|төлөвлө|магадгүй|дээрх|нэмэлт|анхаар|'
                              r'хязгаар|чөлөөл|бусад\s+нөхцөл', line, re.I))


def _map_window_spans(window, spans):
    result = []
    for left, right in spans:
        absolute_left, absolute_right = window['start'] + left, window['start'] + right
        candidates = [source for source in window['sources']
                      if source['start_offset'] <= absolute_left < absolute_right <= source['end_offset']]
        if not candidates:
            return None
        source = min(candidates, key=lambda candidate: (len(candidate['text']), candidate['source_id']))
        start, end = absolute_left - source['start_offset'], absolute_right - source['start_offset']
        if source['text'][start:end] != window['text'][left:right]:
            return None
        result.append(dict(source=source, start=start, end=end))
    return result


def cooperation_source_cards(sources):
    """Own company headings and their adjacent paragraphs, from source data.

    A shared footer/company list is not a card. A card needs its own descriptive
    sentence and cooperation paragraph before another company boundary.
    """
    cards = []
    for window in _overlapping_source_windows(sources):
        lines = _source_lines(window['text'])
        starts = []
        for index, (start, end, line) in enumerate(lines):
            legal = re.fullmatch(r'([A-Za-z][A-Za-z0-9 &.\-]{1,65}?)\s+(?:Co\.,?\s*Ltd\.?|Ltd\.?|Inc\.?)', line)
            prose = re.match(r'^([A-Za-z][A-Za-z0-9 &.\-]{1,65}?)\s+компани\s+нь\b', line, re.I)
            if legal or prose:
                name = (legal or prose)[1].strip()
                if starts and starts[-1]['name'].casefold() == name.casefold():
                    continue
                starts.append(dict(name=name,index=index,start=start,end=end))
        for position, heading in enumerate(starts):
            stop = starts[position+1]['start'] if position+1 < len(starts) else len(window['text'])
            block = window['text'][heading['start']:stop]
            if (not re.search(r'^'+re.escape(heading['name'])+r'\s+компани\s+нь\b',block,re.I|re.M)
                    or not re.search(r'тус\s+компанитай.{0,80}хамтын\s+ажиллагаа',block,re.I)):
                continue
            # A new non-company section also closes this card. Never borrow a
            # platform after a domestic-partners/contact/programme heading.
            tail = [line for line in lines if heading['start'] < line[0] < stop]
            for left, _, label in tail:
                if re.fullmatch(r'дотоодын.{0,90}|хамтын\s+ажиллагаатай\s+байгууллагууд|'
                                r'холбоо\s+барих|хөтөлбөрүүд',label,re.I):
                    stop=left;break
            cards.append(dict(entity=heading['name'],window=window,start=heading['start'],end=stop,
                              heading=(heading['start'],heading['end']),text=window['text'][heading['start']:stop]))
    return cards


def cooperation_entity_choices(sources):
    choices={}
    for card in cooperation_source_cards(sources):
        source=card['window']['sources'][0]
        choices.setdefault(card['entity'].casefold(),dict(question=card['entity'],entity=card['entity'],
            source_url=source['url'],source_version=source['version']))
    return list(choices.values())


def _cooperation_field_plan(request,sources):
    if not request.get('closed') and not request.get('partial_scope'):
        return None
    wanted=request.get('entity','').casefold()
    matches=[card for card in cooperation_source_cards(sources) if card['entity'].casefold()==wanted]
    if not matches:
        return None
    plans=[]
    for card in matches:
        window=card['window']; lines=_source_lines(window['text'])
        local=[line for line in lines if card['start']<=line[0]<card['end']]
        unsafe=re.search(r'хуучин|хүчингүй|баталгаажаагүй|батлаагүй|няцаа|хэрэв|зөвхөн|'
                         r'\bбиш\b|тохиолдолд|төлөвлө|магадгүй|хамаарахгүй',card['text'],re.I)
        index=next(index for index,line in enumerate(lines) if line[0]==card['start'])
        if unsafe or _unsafe_field_prefix(lines,index):
            return None
        years=set(re.findall(r'(?<!\d)(?:19|20)\d{2}(?!\d)',request.get('body','')))
        if request.get('year'):years.update(re.findall(r'\d{4}',request['year']))
        if not years <= set(re.findall(r'(?<!\d)(?:19|20)\d{2}(?!\d)',card['text'])):
            return None
        if request['kind']=='cooperation_course_count':
            candidates=[line for line in local if request['year'] in re.sub(r'\s*[–—-]\s*','–',line[2])
                and re.search(r'хичээлийн\s+жилийн\s+намрын\s+улиралд',line[2],re.I)
                and re.search(r'мэргэжлийн\s+\d+\s+хичээл',line[2],re.I)
                and re.search(r'онлайнаар\s+амжилттай\s+хэрэгжүүл',line[2],re.I)]
            if len(candidates)!=1:return None
            spans=[card['heading'],(candidates[0][0],candidates[0][1])]
            missing=[]
        else:
            dates=[line for line in local if re.search(r'тус\s+компанитай\s+(?:19|20)\d{2}\s+оны\s+(?:[1-9]|1[0-2])-р\s+сараас',line[2],re.I)
                and re.search(r'хамтын\s+ажиллагаа',line[2],re.I)
                and re.search(r'эхлүүл|эхэл|суурийг\s+тавь',line[2],re.I)]
            platforms=[line for line in local if re.search(r'тус\s+компанийн\s+хөгжүүлсэн\s+\S+\s+платформыг',line[2],re.I)
                and re.search(r'сургалт\w*.{0,100}ашиглаж\s+эх(?:эл|л)',line[2],re.I)]
            if len(dates)!=1 or len(platforms)>1:return None
            spans=[card['heading'],(dates[0][0],dates[0][1])]
            if platforms:spans.append((platforms[0][0],platforms[0][1]))
            missing=[] if platforms else ['cooperation_platform']
        mapped=_map_window_spans(window,spans)
        if not mapped:return None
        notice=(card['entity']+'-ийн энэ эхэд сургалтад ашигласан платформын нэрийг тодорхой заагаагүй байна. '
                'Өөр компанийн платформын нэрээр орлуулахгүй.' if missing else '')
        if request.get('partial_scope'):
            missing.append('unparsed_request_scope')
            notice+=(' Анхны танигдсан бичвэрийн зарим үг тодорхойгүй тул асуултын бүх шаардлагыг бүрэн тайлбарласан '
                     'гэж үзэхгүй. Сонгосон байгууллагын эхээс баталсан хэсгийг үзүүлэв; үлдсэн санаагаа бичиж тодруулна уу.')
        plans.append(dict(kind=request['kind'],parts=mapped,missing_fields=missing,message=notice or None))
    signatures={tuple(part['source']['text'][part['start']:part['end']] for part in plan['parts']) for plan in plans}
    return plans[0] if len(signatures)==1 else None


def _student_table_plan(request,sources):
    wanted=_scope_words(request['department'])
    candidates=[]
    for window in _overlapping_source_windows(sources):
        if not any(wanted and wanted <= _scope_words(source.get('title','')) for source in window['sources']):
            continue
        lines=_source_lines(window['text'])
        for index,(start,_,heading) in enumerate(lines[:-2]):
            if heading.casefold()!='оюутны тоо' or _unsafe_field_prefix(lines,index):continue
            intro=lines[index+1]
            match=re.fullmatch(r'((?:19|20)\d{2})\s*[–—-]\s*((?:19|20)\d{2})\s+оны\s+хичээлийн\s+жилд\s+'
                r'нийт\s+(\d+)\s+оюутан\s+суралцаж\s+байна\.\s+Үүнээс:',intro[2],re.I)
            if not match or match[1]+'–'+match[2]!=request['year']:continue
            cursor=index+2;rows=[]
            while cursor<len(lines):
                row=re.fullmatch(r'(\d+)-р\s+курс\s+(\d+)\s+оюутан',lines[cursor][2],re.I)
                if not row:break
                rows.append((int(row[1]),int(row[2]),lines[cursor]));cursor+=1
            if not rows:continue
            expected=(list(range(1,len(rows)+1)) if request.get('all_courses') else
                      list(range(request['first_course'],request['last_course']+1)))
            if ([row[0] for row in rows]!=expected or sum(row[1] for row in rows)!=int(match[3])
                    or cursor>=len(lines)
                    or re.match(r'мөн|харин|гэхдээ|хэрэв|энэ|тус\b|нэмэлт|анхаар|зөвхөн',lines[cursor][2],re.I)):
                continue
            mapped=_map_window_spans(window,[(start,rows[-1][2][1])])
            if mapped:candidates.append(dict(kind=request['kind'],parts=mapped))
    signatures={tuple(part['source']['text'][part['start']:part['end']] for part in plan['parts']) for plan in candidates}
    return candidates[0] if len(signatures)==1 else None


def _office_field_plan(request,sources):
    """Own labelled office cards only; general school contact is unrelated."""
    labels={'office_floor':'сургалтын албаны байрлах давхар',
            'office_phone':'сургалтын албаны тусгай утасны дугаар'}
    missing=list(labels)
    if not request.get('closed'):
        qualifier = ('Асуултын бичвэрт үгүйсгэсэн эсвэл нөхцөлт хэлбэр байна. '
                     if request.get('negated_or_conditional') else
                     'Асуултын нэр, он, нэмэлт хүсэлт эсвэл хоёр талбарын холбоог бүрэн тодорхойлж чадсангүй. ')
        return dict(kind=request['kind'],parts=[],missing_fields=missing,
            message=qualifier+'Тэр хүрээг хасаж өөр асуултад хариулахгүй. '
                    'Сургалтын албаны давхар болон тусгай утсыг энэ эхээр баталж чадсангүй; '
                    'ерөнхий сургуулийн дугаараар орлуулахгүй. Асуултаа бичиж тодруулж болно.')
    candidates=[]
    for window in _overlapping_source_windows(sources):
        lines=_source_lines(window['text'])
        for index,(start,end,label) in enumerate(lines):
            if not re.fullmatch(r'сургалтын\s+алба',label,re.I) or _unsafe_field_prefix(lines,index):continue
            found={};pending=None;invalid=False
            for left,right,row in lines[index+1:index+8]:
                if re.search(r'хэрэв|зөвхөн|биш|хуучин|хүчингүй|төлөвлө|байхгүй|хамаарахгүй',row,re.I):
                    invalid=True;break
                if re.fullmatch(r'байршил\s*[:：]?',row,re.I):pending=('office_floor',left);continue
                if re.fullmatch(r'утас\s*[:：]?',row,re.I):pending=('office_phone',left);continue
                floor=re.fullmatch(r'(?:байршил\s*[:：]?\s*)?\d{1,2}(?:-р)?\s+давхар(?:т)?[.]?',row,re.I)
                phone=re.fullmatch(r'(?:утас|холбоо\s+барих\s+утас)\s*[:：]?\s*(?:\+976\s*)?\d{8}',row,re.I)
                if floor:key='office_floor'
                elif phone or (pending and pending[0]=='office_phone' and re.fullmatch(r'(?:\+976\s*)?\d{8}',row)):
                    key='office_phone'
                else:break
                if key in found:invalid=True;break
                found[key]=(pending[1] if pending and pending[0]==key else left,right)
                pending=None
            if invalid:continue
            if found:
                mapped=_map_window_spans(window,[(start,end),*found.values()])
                if mapped:candidates.append((mapped,[key for key in missing if key not in found]))
    signatures={tuple(part['source']['text'][part['start']:part['end']] for part in plan[0]) for plan in candidates}
    if len(signatures)>1:return None
    parts,missing=candidates[0] if candidates else ([],missing)
    notice='Хадгалсан эхээр баталж чадаагүй мэдээлэл: '+', '.join(labels[key] for key in missing)+'. '
    return dict(kind=request['kind'],parts=parts,missing_fields=missing,
                message=notice+'Сургуулийн ерөнхий утсыг албаны тусгай дугаар гэж орлуулахгүй.' if missing else None)


def _structured_window_fields(descriptor, window):
    text, kind = window['text'], descriptor['kind']
    lines = _source_lines(text)
    # Source-wide correction/obsolete notices cannot disappear merely because
    # the requested card has an attractive label. Date values in unrelated
    # completed events are not treated as dates of these requirements.
    if re.search(r'хуучин|хүчингүй|баталгаажаагүй|няцаа|батлаагүй|төлөвлөж|'
                 r'дээрх.{0,60}(?:биш|хамаарахгүй|өөрчлөгд)', text, re.I):
        return []
    candidates = []
    if kind == 'facility_rooms':
        for index, (start, _, label) in enumerate(lines):
            if (not re.fullmatch(r'hub\s+center', label, re.I) or index + 3 >= len(lines)
                    or _unsafe_field_prefix(lines, index)):
                continue
            description = lines[index + 1]
            if (not description[2].endswith('.') or not re.search(r'байрл|орчин', description[2], re.I)
                    or re.search(r'хэрэв|зөвхөн|биш|байхгүй|төлөвлө|магадгүй', description[2], re.I)):
                continue
            cursor = index + 2
            if re.fullmatch(r'\d+(?:[.,]\d+)?\s+м[²2]\s+талбай', lines[cursor][2], re.I):
                cursor += 1
            rows, expected = [], 1
            while cursor + 1 < len(lines) and re.fullmatch(r'0?\d{1,2}', lines[cursor][2]):
                if int(lines[cursor][2]) != expected:
                    rows = []
                    break
                item = lines[cursor + 1]
                if (len(item[2]) > 100 or re.search(r'[.!?]|хэрэв|зөвхөн|биш|байхгүй|эсвэл', item[2], re.I)):
                    rows = []
                    break
                rows.append((lines[cursor][0], item[1], item[2]))
                cursor += 2
                expected += 1
            # A new physical heading must close the list: a clipped prefix of
            # a longer list cannot certify that later conditions were checked.
            if len(rows) < 2 or cursor >= len(lines) or not _closes_field_list(lines[cursor][2]):
                continue
            wanted = [r'багаар\s+ажиллах\s+өрөө', r'сэтгэл\s*зүйчийн\s+өрөө']
            matches = [[row for row in rows if re.fullmatch(pattern, row[2], re.I)] for pattern in wanted]
            if all(len(found) == 1 for found in matches):
                candidates.append([(start, description[1]), *[(found[0][0], found[0][1]) for found in matches]])
    elif kind == 'internship_application':
        for index, (start, _, label) in enumerate(lines[:-1]):
            if (not re.fullmatch(r'дадлага\s+хөтөлбөрт\s+хэн\s+хамрагдах\s+вэ\?', label, re.I)
                    or _unsafe_field_prefix(lines, index)):
                continue
            answer = lines[index + 1]
            body = answer[2]
            if (not body.endswith('.') or not re.search(r'курсийн\s+оюут\w*', body, re.I)
                    or not re.search(r'хүсэлт\w*\s+гарга\w*', body, re.I)
                    or not re.search(r'япон\s+хэл\s+дээр\s+ярилцлага\s+өг\w*', body, re.I)
                    or not re.search(r'тэнцсэн\s+тохиолдолд', body, re.I)
                    or not re.search(r'дадлага\s+хийх\s+боломжтой', body, re.I)
                    or re.search(r'биш|хамрагдахгүй|тодорхойгүй|төлөвлө|магадгүй', body, re.I)):
                continue
            if index + 2 < len(lines):
                following = lines[index + 2][2]
                if (re.search(r'нэмэлт|анхаар|хязгаар|чөлөөл|хэрэв|зөвхөн', following, re.I)
                        or not (re.fullmatch(r'\d+', following) or following.isupper() or following.endswith('?'))):
                    continue
            candidates.append([(start, answer[1])])
    elif kind == 'pathway_language':
        for index, (start, end, label) in enumerate(lines):
            if (not re.fullmatch(r'япон\s+коосэнд\s+дэвшин\s+суралцахад\s+тавигдах\s+шаардлагууд', label, re.I)
                    or _unsafe_field_prefix(lines, index)):
                continue
            cursor, rows, expected = index + 1, [], 1
            while cursor < len(lines):
                item = re.fullmatch(r'(0?\d{1,2})\s+(.+)', lines[cursor][2])
                if not item:
                    break
                if int(item[1]) != expected:
                    rows = []
                    break
                rows.append(lines[cursor])
                cursor += 1
                expected += 1
            if len(rows) < 2 or cursor >= len(lines) or not _closes_field_list(lines[cursor][2]):
                continue
            region = '\n'.join(row[2] for row in rows)
            if re.search(r'хэрэв|зөвхөн|биш|боловч|харин|эсвэл|тохиолдолд|хамаарахгүй|төлөвлө', region, re.I):
                continue
            language = re.escape(descriptor['language'])
            wanted = [row for row in rows if re.fullmatch(
                r'0?\d{1,2}\s+' + language + r'\s+хэлний\s+(?:(?:JLPT|CEFR)\s+)?'
                r'(?:N[1-5]|[ABC][12])\s+түвшний\s+мэдлэг\s*,?\s+чадвартай[.]?', row[2], re.I)]
            if len(wanted) == 1:
                candidates.append([(start, end), (wanted[0][0], wanted[0][1])])
    elif kind == 'member_absence':
        scopes = [(start, end) for index, (start, end, label) in enumerate(lines)
                  if re.fullmatch(r'оюутны\s+зөвлөл(?:ийн\s+тухай)?', label, re.I)
                  and not _unsafe_field_prefix(lines, index)]
        for index, (start, _, label) in enumerate(lines[:-1]):
            if not re.fullmatch(r'цаг\s+баримтлалт', label, re.I):
                continue
            preceding = [scope for scope in scopes if scope[1] < start and start - scope[1] <= 1500]
            if not preceding:
                continue
            scope = preceding[-1]
            region = text[scope[1]:start]
            if re.search(r'багш\w*\s+зөвлөл|сургуулийн\s+зөвлөл|'
                         r'хэрэв|зөвхөн|биш|хүчингүй|төлөвлө|(?<!\d)(?:19|20)\d{2}(?!\d)', region, re.I):
                continue
            answer = lines[index + 1]
            if (not answer[2].endswith('.') or not re.search(
                    r'\d+\s+удаа\s+шалтгаангүй\s+тасалвал\s+эрх\s+түтгэлзүүлэх\s+асуудлыг\s+хэлэлцэнэ\.', answer[2], re.I)
                    or re.search(r'биш|тохиолдолд|зөвхөн|хэрэв|харин|хамаарахгүй|төлөвлө', answer[2], re.I)):
                continue
            if any(re.match(r'мөн|харин|гэхдээ|хэрэв|энэ|тус\b|нэмэлт|анхаар', line[2], re.I)
                   for line in lines[index + 2:index + 5]):
                continue
            candidates.append([scope, (start, answer[1])])
    return candidates


def structured_field_extract(query, sources):
    """Return requested labelled fields as original, independently exact spans.

    A complete bounded grammar plus an explicit source heading is required.
    Shared headings are retained with a chosen list item; the item is never
    rephrased as the whole pathway's eligibility. Conflicting candidate fields
    fail closed. This is a development rule, not a general entailment model.
    """
    followup=followup_field_request(query)
    if followup:
        if followup['kind'].startswith('cooperation_'):
            return _cooperation_field_plan(followup,sources)
        if followup['kind']=='department_student_table':
            return _student_table_plan(followup,sources)
        if followup['kind']=='office_floor_phone':
            return _office_field_plan(followup,sources)
    descriptor = _closed_structured_question(query)
    if descriptor is None:
        return None
    candidates = []
    headings = {
        'facility_rooms': r'(?im)^hub\s+center\s*$',
        'internship_application': r'(?im)^дадлага\s+хөтөлбөрт\s+хэн\s+хамрагдах\s+вэ\?\s*$',
        'pathway_language': r'(?im)^япон\s+коосэнд\s+дэвшин\s+суралцахад\s+тавигдах\s+шаардлагууд\s*$',
        'member_absence': r'(?im)^оюутны\s+зөвлөл(?:ийн\s+тухай)?\s*$',
    }
    for window in _overlapping_source_windows(sources):
        plans = _structured_window_fields(descriptor, window)
        if not plans and re.search(headings[descriptor['kind']], window['text']):
            # A second explicit scoped source that is conditional, incomplete,
            # or negated must not be ignored in favour of a convenient copy.
            return None
        for spans in plans:
            mapped = _map_window_spans(window, spans)
            if mapped:
                candidates.append(mapped)
    if not candidates:
        return None
    signatures = {tuple(item['source']['text'][item['start']:item['end']] for item in candidate)
                  for candidate in candidates}
    if len(signatures) != 1:
        return None
    return dict(kind=descriptor['kind'], parts=candidates[0])


def field_extract(query, sources):
    """Select literal spans by the requested field and source section labels.

    No answer amounts, programme codes or dates are stored in these rules.
    Conditions remain in the copied clause. Title/year provenance is separate.
    """
    q = query.casefold()
    floors=facility_floor_requirements(query)
    if len(floors)==1:
        target='(?:'+'|'.join(floors[0]['aliases'])+')'
        rest=re.sub(target,' ',q)
        words=set(re.findall(r'[^\W\d_]+',rest))
        allowed=set('''сургуулийн коллежийн хэд хэдэн хэддүгээр аль давхар давхарт давхрын давхард
            байдаг байрладаг байрлах байна вэ бэ юм нь хэл хэлнэ хэлж өгөөч уу үү'''.split())
        if words<=allowed and not re.search(r'\d|болон|\bба\b|эсвэл|харьцуул',rest):
            candidates=[(source,record) for source in sources for record in facility_floor_records(source['text'],floors[0])]
            if candidates:
                source,record=min(candidates,key=lambda item:item[1]['end']-item[1]['start'])
                return source,record['text']
    contact_fields=staff_contact_fields(q)
    if contact_fields:
        contact_scope=staff_query_scope(query,sources)
        if contact_scope and not contact_scope.get('stop'):
            remaining=_scope_words(query)
            for title in contact_scope['department_titles']:
                remaining-=_scope_words(title)
            if contact_scope.get('person'):remaining-=_scope_words(contact_scope['person'])
            allowed=set('''багштай багш багшийн цахим цахимаар холбоо барих холбогдох холбогдож
                яаж хэрхэн имэйл имейл мэйл email хаяг хаягийг утас утсыг phone өгөөч хэл хэлнэ
                хэлж хэлээрэй уу үү вэ бэ холбогдохыг зааж'''.split())
            if not (remaining-allowed) and not re.search(r'болон|\bба\b|эсвэл|харьцуул|цалин|нас',q):
                for source in contact_scope['sources']:
                    for card in staff_contact_cards(source['text']):
                        if (all(field in card['fields'] for field in contact_fields)
                                and (not contact_scope.get('person') or _staff_person_key(card['person'])==_staff_person_key(contact_scope['person']))):
                            end=max(card['field_ends'][field] for field in contact_fields)
                            return source,source['text'][card['start']:end]
    # Copy one named department's positive staff-count paragraph for a closed
    # count request. Unknown extra attributes keep the normal guarded RAG path.
    staff = staff_query_scope(query, sources)
    if staff and staff['kind']=='count' and len(staff['department_titles'])==1 and not staff.get('stop'):
        allowed = _SCOPE_GENERIC | frozenset('''нар нарын байдаг вэ бэ юм байгаа байна
            өгөөч өгнө хэлнэ хэл хэлж хэлээд хэлээрэй тус нийт тоог тоо хэд хэдэн
            бүрэлдэхүүн бүрэлдэхүүнтэй'''.split())
        title_words = set().union(*(_scope_words(title) for title in staff['department_titles']))
        remaining = _scope_words(query) - title_words - allowed
        if not remaining and not re.search(r'\d|нас|цалин|нэр|хичээл|харьцуул|болон', q):
            for source in staff['sources']:
                spans = staff_count_spans(source['text'])
                if spans and len(spans[0])<=1500:
                    return source, spans[0]
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
            if enrollment_consequence_query(query):
                if enrollment_consequence_supported(query, text):
                    return source, text
                # A generic confirmation/payment clause is a different field.
                continue
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
                    and not enrollment_consequence_query(query)
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


def _school_founding_requirements(query):
    """Explicit school founding event facets; never store an answer value.

    This is a bounded event contract, not a general relation/entailment model.
    Its requested facets must coexist in one positive founding-event clause.
    """
    if (not re.search(r'сургуул\w*|коллеж\w*|коосэн\w*', query)
            or not re.search(r'байгуулагд\w*|үүсгэн\s+байгуул\w*', query)):
        return []
    facets = []
    if re.search(r'хэзээ|хэдийд|огноо|хэдэн\s+он|байгуулагд\w*\s+оныг|хэдэн\s+сарын|хэдэнд|өдөр', query):
        facets.append('date' if re.search(r'огноо|сарын|хэдэнд|өдөр', query) else 'year')
    if re.search(r'хэдэн\s+(?:оюутан|суралцагч)|(?:оюутан|суралцагч)\w*\s+(?:тоо|хэд)', query):
        facets.append('students')
    if re.search(r'хэдэн\s+бүлэг|бүлг\w*\s+(?:тоо|хэд)', query):
        facets.append('groups')
    labels = dict(date='сургууль байгуулагдсан он, сар, өдөр', year='сургууль байгуулагдсан он',
                  students='байгуулагдах үеийн анхны оюутны тоо', groups='байгуулагдах үеийн бүлгийн тоо')
    school = re.search(r'сургуул\w*|коллеж\w*|коосэн\w*', query)
    subject_terms = re.findall(r'[a-zа-яёөү]+', query[:school.start()])
    subject_terms = [term for term in subject_terms if term not in
                     {'манай', 'тус', 'энэ', 'тэр', 'надад', 'тэгвэл', 'анх'}]
    return [dict(name='school_founding_' + facet, label=labels[facet], aliases=[],
                 type='school_founding_event', facet=facet, required_event_facets=facets,
                 subject_terms=subject_terms)
            for facet in facets]


def _school_founding_event_records(text):
    """Yield local positive school-founding clauses and their own year heading.

    A publication date, scholarship nomination, programme launch, another
    paragraph's counts or a plan to found a school cannot establish this event.
    Physical year/heading adjacency is used, not a year anywhere in the page.
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    completed = r'үүсгэн\s+байгуул(?:ж|сан|жээ|ав)(?![а-яёөү])|байгуулагд(?:сан|жээ|ав)(?![а-яёөү])'
    school_noun = r'(?<![а-яёөү])(?:сургуулийг|сургууль|коллеж(?:ийг)?|коосэн(?:ийг|г)?)(?![а-яёөү])'
    # This deliberately accepts a small literal grammar. Unknown event links
    # abstain rather than borrow a neighbouring predicate's date or counts.
    calendar_word = (r'оны|онд|он|сарын|сар|өдөр|өдрийн|нд|ны|ний|анх|албан|ёсоор|'
                     r'нэгдүгээр|хоёрдугаар|гуравдугаар|дөрөвдүгээр|тавдугаар|зургадугаар|'
                     r'долдугаар|наймдугаар|есдүгээр|аравдугаар|арван|нэг|хоёрдугаар')
    for index, line in enumerate(lines):
        for clause in re.split(r'(?<=[.!?。])\s+|[;；]', line):
            verb = re.search(completed, clause, re.I)
            if not verb:
                continue
            schools = list(re.finditer(school_noun, clause[:verb.start()], re.I))
            if not schools:
                continue
            school = schools[-1]
            between = clause[school.end():verb.start()]
            active = verb.group().casefold().startswith('үүсгэн')
            accusative = (school.group().casefold().endswith(('ийг', 'энг'))
                          or bool(re.match(r'[”"»]?[-–]?ийг\b', between, re.I)))
            if active != accusative:
                continue
            # A date before the school name is permitted only if it is a
            # calendar prefix. "published on DATE ... school" is not that.
            prefix = clause[:school.start()]
            named = re.findall(r'[a-zа-яёөү]+', prefix.casefold())
            between_words = re.findall(r'[а-яёөү]+', between.casefold())
            allowed = calendar_word + r'|ийг|анхны|эхний|оюутан\w*|суралцагч\w*|бүлэг\w*'
            if any(not re.fullmatch(allowed, word) for word in between_words):
                continue
            if re.search(r'нийтэл|мэдээ|төлөвлө|байгаагүй|\bбиш\b|худал|магадгүй|'
                         r'байгуулагдаагүй|тодорхойгүй|дараах|дараа\s+нь|өнгөрсний|тэтгэл|'
                         r'нэр\s+дэвш|уулзалт|хожим|одоогийн|өнөөдөр|хэрэв|тохиолдолд|'
                         r'няцаа|таамаг|батлагдаагүй', clause, re.I):
                continue
            if re.search(r'сургуул\w*|коллеж\w*|коосэн\w*', clause[verb.end():], re.I):
                # A following intake naming another school cannot fill this
                # founding event. Unknown cross-subject prose stays excluded.
                continue
            # Do not import later/current counts into the founding event.
            clause = re.split(r'\b(?:харин|өнөөдөр|хожим|одоогийн)\b|дараа\s+нь', clause, maxsplit=1, flags=re.I)[0]
            if not re.search(completed, clause, re.I):
                continue
            event_prefix = clause[:verb.end()]
            years = re.findall(r'(?<!\d)(?:19|20)\d{2}(?!\d)', event_prefix)
            year = len(set(years)) == 1
            if not years:
                # Only an immediately preceding year, optionally followed by
                # a short founding heading, may supply a timeline year.
                preceding = lines[max(0, index-2):index]
                if preceding and re.fullmatch(r'(?:19|20)\d{2}', preceding[-1]):
                    year = True
                elif (len(preceding) == 2 and re.fullmatch(r'(?:19|20)\d{2}', preceding[0])
                      and len(preceding[1]) <= 90 and re.search(r'байгуулагд\w*|үүсгэн\s+байгуул\w*', preceding[1], re.I)):
                    year = True
            # Dates must qualify the founding predicate, not a later conjunct.
            month_day = bool(re.search(r'(?<!\d)(?:0?[1-9]|1[0-2])\s+сарын\s+(?:0?[1-9]|[12]\d|3[01])(?!\d)(?:-\w+)?\s*(?:өдөр|нд|ны|ний)?', event_prefix, re.I)
                             or re.search(r'(?<!\d)(?:19|20)\d{2}[./-](?:0?[1-9]|1[0-2])[./-](?:0?[1-9]|[12]\d|3[01])(?!\d)', event_prefix))
            numeric_dates = re.findall(r'(?<!\d)(\d{1,2})\s+сарын\s+(\d{1,2})(?!\d)', event_prefix)
            numeric_dates += re.findall(r'(?<!\d)(?:19|20)\d{2}[./-](\d{1,2})[./-](\d{1,2})(?!\d)', event_prefix)
            # Bound calendar validation too: February may have 29 days when
            # its year is supplied by a heading; impossible dates never count.
            limits = (31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
            if any(not (1 <= int(month) <= 12 and 1 <= int(day) <= limits[int(month)-1])
                   for month, day in numeric_dates):
                month_day = False
            initial = re.search(r'анхны|эхний', clause, re.I)
            initial_part = clause[initial.start():] if initial else ''
            # Intake after the founding predicate needs an explicit school
            # teaching/start predicate; a scholarship's "first students" is
            # a different relation even within the same physical sentence.
            intake_linked = bool(initial and (initial.end() <= verb.start()
                                 or re.search(r'хичээлл\w*|суралц\w*', initial_part, re.I)))
            students = bool(intake_linked and re.search(r'(?<!\d)\d+\s+(?:оюутан|суралцагч)\w*', initial_part, re.I))
            groups = bool(intake_linked and re.search(r'(?<!\d)\d+\s+бүлэг\w*', initial_part, re.I))
            yield dict(year=year, date=year and month_day, students=students, groups=groups,
                       subject_prefix=named)


def _school_founding_fields_present(text, requirement):
    # All asked fields must be supported by the same event region. Separate
    # schools/events cannot each supply one convenient number.
    subject = requirement.get('subject_terms', [])
    return any((not subject or record['subject_prefix'][-len(subject):] == subject)
               and all(record.get(facet, False) for facet in requirement['required_event_facets'])
               for record in _school_founding_event_records(text))
