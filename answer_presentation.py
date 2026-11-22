"""Make a checked reply read like a person at the reception desk wrote it (2026-11-22).

The user read the answers on 11/22: «it is not an answer, just trash». Three things made
them so: website menu and breadcrumb fragments inside the quoted text, citation markers,
and notes in which the system talks about its own rules («…үг өөрчлөхгүй нэгтгэн
үзүүлэв. Эхийн огноо, нөхцөлийг нягтлаарай», «Ойролцоо үгтэй хамааралгүй хэсгийг
хариулт болгож харуулахгүй»). The guards upstream still decide WHAT may be shown; this
layer runs after them and only changes HOW it reads:

- the shown answer loses menu/form fragments, citation markers and shouting capitals, and
  numbered cards («01 … 02 …») become a list; the quotes themselves stay verbatim in
  `rag.claims`, and no word of the source is replaced by another word;
- when the question asks for one field (e-mail, phone, address, the head of a unit), the
  line that holds it is moved to the top;
- a reply without an answer gets one plain sentence chosen from the guard's reason, and
  the guard's own wording is kept in `audit_message` for diagnosis.

It never adds a fact: the only text it writes is a sentence about what was not found.
"""
import re

_EMOJI = '\U0001F300-\U0001FAFF☀-➿⬀-⯿'

# Menu fragments counted in the 11/17 website release (577 chunks): every department page
# starts with the same header, news lists repeat «Бүх мэдээ» / «Мэдээ, мэдээлэл», cards end
# with «Дэлгэрэнгүй», the contact page carries its message form.
_DEPARTMENT_HEADER = re.compile(
    r'Нүүр\s+Тэнхимүүд\s+(?P<dept>[^\n]{3,80}?)\s+Тэнхим\s+(?P=dept)\s+'
    r'Тэнхимийн\s+эрхлэгч\s*:\s*(?P<head>\S+)\s+(?:Хөтөлбөр,\s+төлөвлөгөө\s+)?'
    r'Холбоо\s+барих\s+\d+\s+хөтөлбөр\s+\d+\s+багш\s+Тэнхимийн\s+тухай\s+'
    r'(?:Хөтөлбөр,\s+сургалтын\s+төлөвлөгөө\s+)?Багш\s+нар\s+\d+\s+Амжилт\s*(?P<mission>Эрхэм\s+зорилго\s*)?')
_CONTACT_BLOCK = re.compile(
    r'Хаяг\s+мэдээлэл\s+Хаяг\s+(?P<address>.+?)\s+Утас\s+(?P<phone>\+?[\d ]{8,16}?)\s+'
    r'Имэйл\s+(?P<email>\S+@\S+)(?:\s+Ажлын\s+цаг\s+(?P<hours>.+?Ням:\s*Амарна))?'
    r'(?:\s+Мэдэгдэл\s+илгээх\b.*?\bИлгээх)?(?=\s|$)', re.S)
_FORM = re.compile(r'\s*Мэдэгдэл\s+илгээх\s+Нэр\s*\*.*?\bИлгээх\b', re.S)
# «2026-2027 оны … журам (татсан: 2026-10-10) — эхийн мэдээлэл:\n\n<excerpt>» (rag_runtime source_text_lookup):
# the excerpt first; the page title and date are already in the source list under the answer.
_EXTRACT_HEADER = re.compile(r'\A[^\n]+? \(татсан: \d{4}-\d{2}-\d{2}\)(?:\n\n(?P<notice>.+?))? — эхийн мэдээлэл:\n\n', re.S)
_ROSTER = re.compile(r'(?P<dept>\S[^\n:]*?тэнхим) — сайтад нийтэлсэн багш, ажилтан \((?P<n>\d+) нэр\):')
_MENU = [
    re.compile(r'Академик\s+бүтэц\s+Тэнхимүүд\s+'),
    re.compile(r'(?<!\S)\d+\s+Тэнхим\s+\d+\s+Хөтөлбөр\s+\d+\s+Багш\s+нар\s+'),
    re.compile(r'(?<!\S)0\s+хөтөлбөр\s+\d+\s+багш(?!\S)\s*'),
    re.compile(r'Бүх\s+мэдээ\s+'),
    re.compile(r'Мэдээ,?\s+мэдээлэл\s+(?=Мэдээ\b|Гадаад|ГАДААД|Оюутны|Хамтын|Зарлал|NAPROCK|Сургуулийн|\d)'),
    re.compile(r'\AОюутны\s+амьдрал\s+'),
    re.compile(r'\Aмэдээ\s+'),
]
_MORE = re.compile(r'\s*(?:\.\.\.|…)\s*Дэлгэрэнгүй\b|\s+Дэлгэрэнгүй(?=\s+(?:\d|0\s+хөтөлбөр)|\s*$)')
_MARKER = re.compile(r'[ \t]*\[\d+\]')
_HEADING_TWICE = re.compile(r'\A(?P<h>\S+(?:\s+\S+){0,3})\s+(?=(?P=h)\s)', re.I)  # «Зөвлөл Зөвлөл нь …»
_NUMBERED = re.compile(r'(?<!\S)0([1-9])\s+(?=[^\d\s])')
_ACRONYMS = {'ШМТК', 'БШУЯ', 'ЕБС', 'ЭЕШ', 'ББС', 'МУИС', 'ШУТИС', 'СЭЗИС', 'ХААИС', 'АШУҮИС', 'ЖАЙКА', 'КОСЭН',
             'NMCT', 'QPAY', 'QR', 'JLPT', 'IT', 'AI'}


def _department(match):
    dept = match['dept'].strip()
    head = re.sub(r'тэнхим$', 'тэнхимийн', dept) if dept.endswith('тэнхим') else dept + '-ийн'
    return head + ' эрхлэгч: ' + match['head'] + '.\n\n' + ('Эрхэм зорилго: ' if match['mission'] else '')


def _contact(match, keep_hours):
    lines = ['Хаяг: ' + match['address'].strip(), 'Утас: ' + match['phone'].strip(), 'Имэйл: ' + match['email']]
    if keep_hours and match['hours']:
        lines.append('Ажлын цаг: ' + re.sub(r'\s+', ' ', match['hours']).strip())
    return '\n'.join(lines)


def _emoji_menus(text):
    """Remove tab menus such as «🏛️ Оюутны Зөвлөл 🎯 Клуб & Дугуйлан 🔬 …» (two or more icons
    close together); a single icon inside a sentence is left alone."""
    icon = re.compile('[' + _EMOJI + ']️?')
    spots = [m.start() for m in icon.finditer(text)]
    if len(spots) < 2:
        return text
    runs, start, last = [], spots[0], spots[0]
    for spot in spots[1:]:
        if spot - last <= 40:
            last = spot
            continue
        runs.append((start, last)); start = last = spot
    runs.append((start, last))
    for first, final in reversed(runs):
        if first != final:
            # Up to the last icon only: the words after it are often the heading of real content
            # («🏛️ Оюутны зөвлөлийн тухай …»), and deleting content is worse than a menu word left over.
            text = text[:first] + ' ' + text[final:]
    return icon.sub('', text)


def _sentence_case(text):
    """A shouted line («БИЧГИЙН ШАЛГАЛТ 2026.08.15 ӨДӨР …») in normal case, acronyms kept."""
    def fix(line):
        letters = re.findall(r'[А-ЯЁӨҮа-яёөү]', line)
        upper = [c for c in letters if c.isupper()]
        if len(letters) < 12 or len(upper) < 0.8 * len(letters):
            return line
        def word(w):
            stem, dash, suffix = w.partition('-')
            if re.search(r'\d', w) and re.fullmatch(r'[А-ЯЁӨҮA-Z]{1,5}-?\d[\w-]*\W*', w):  # «КУ-2», «N2» stay
                return w
            if re.sub(r'\W', '', stem) in _ACRONYMS:  # «ШМТК-ИЙН» -> «ШМТК-ийн»
                return stem + dash + suffix.lower()
            return w.lower()
        out = ' '.join(word(w) for w in line.split(' '))
        return out[:1].upper() + out[1:]
    return '\n'.join(fix(line) for line in text.split('\n'))


def _numbered(text):
    """«01 A 02 B 03 C» (website cards) -> one item per line, only for a 1, 2, 3 … run."""
    found = list(_NUMBERED.finditer(text))
    run = [m for i, m in enumerate(found) if int(m[1]) == i + 1]
    if len(run) < 2 or len(run) != len(found):
        return text
    for match in reversed(run):
        text = text[:match.start()] + '\n• ' + text[match.end():]
    return text


def clean_text(text, *, keep_website_hours=True):
    """Website menu/form fragments, citation markers and shouting out; the source's words stay."""
    if not isinstance(text, str) or not text.strip():
        return text
    header = _EXTRACT_HEADER.match(text)
    if header:
        text = text[header.end():] + ('\n\n' + header['notice'].strip() if header['notice'] else '')
    text = _ROSTER.sub(lambda m: m['dept'] + 'ийн багш, ажилтан (' + m['n'] + '):', text)
    text = _DEPARTMENT_HEADER.sub(_department, text)
    text = _CONTACT_BLOCK.sub(lambda m: _contact(m, keep_website_hours), text)
    text = _FORM.sub('', text)
    for pattern in _MENU:
        text = pattern.sub('', text)
    text = _MORE.sub(lambda m: '…' if m.group(0).lstrip().startswith(('...', '…')) else '', text)
    text = _MARKER.sub('', text)
    text = _emoji_menus(text)
    text = _HEADING_TWICE.sub(lambda m: '' if m['h'][:1].isupper() else m.group(0), text)
    text = _sentence_case(text)
    text = _numbered(text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    text = re.sub(r'[ \t]+\n', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# What the question asks for, and how to recognise the line that holds it.
_FIELDS = (
    (re.compile(r'и-?мэйл|имайл|e-?mail|цахим\s+шуудан', re.I), re.compile(r'@')),
    # Mongolian numbers start 7, 8 or 9; «2026-2027» (a school year) must not count as a phone (code review).
    (re.compile(r'утас|утасны\s+дугаар', re.I), re.compile(r'^Утас:|\+976|(?<!\d)[789]\d{3}[- ]?\d{4}(?!\d)')),
    (re.compile(r'(?<!\w)хаяг(?!\w)|хаана\s+байрла', re.I), re.compile(r'^Хаяг:')),
)
# Stems, so the genitive «захирлын», «даргын» counts too (code review 11/23); items are matched on the first
# four letters of the asked stem («захи», «дарг», «эрхл», «мене»).
_ROLE = re.compile(r'эрхлэгч|захирал|захирл|дарга|даргы|менежер', re.I)


def direct_first(query, text):
    """Move the line or list item that holds the asked field to the top; nothing is removed."""
    if not isinstance(text, str) or not text.strip() or not isinstance(query, str):
        return text
    q = query.casefold()
    for asks, holds in _FIELDS:
        if asks.search(q):
            lines = text.split('\n')
            hit = next((i for i, line in enumerate(lines) if holds.search(line)), None)
            if hit not in (None, 0) and len(lines) > 1:
                lines.insert(0, lines.pop(hit))
                return '\n'.join(lines)
            return text
    role = _ROLE.search(q)
    if role:
        roster = re.match(r'(?P<head>[^\n:]{3,120}:\s*)(?P<items>[^\n]+)', text)
        if roster and ';' in roster['items']:
            items = [item.strip() for item in roster['items'].rstrip('.').split(';')]
            hit = next((i for i, item in enumerate(items) if role.group(0)[:4] in item.casefold()), None)
            if hit is not None:
                # «Билгүүн (МИТ-ийн эрхлэгч).» first, then the rest of the published list.
                lead = items.pop(hit)
                return lead + '.\n\n' + roster['head'] + '; '.join(items) + '.' + text[roster.end():]
    return text


# --- a reply without an answer: one plain sentence instead of the guard's rule text ----------
_DROP = re.compile(  # sentences in which the system explains its own rules
    r'орлуулахгүй|орлуулж\s+хариулахгүй|хариулт\s+болгож\s+харуулахгүй|нягтлаарай|Доорх\s+сэдвүүдээс\s+мөн|'
    r'ресепшний\s+ажилтнаас|Доорх\s+(?:албан\s+)?эх(?:ийг|ийн)?\s+шал|сургуультай\s+холбо|хувийн\s+бүртгэлийн\s+хариу|'
    r'Үргэлжлэх\s+хугацаа,\s+нийт\s+оноо\s+нь|Товчилсон\s+нэр\s+хэрэглэсэн|нэвтрэх\s+цэсийг\s+баталгаатай|'
    r'Энэ\s+чат\s+суралцагчийн\s+хувийн\s+бүртгэлтэй|Холбоотой\s+хэсгийг\s+доор|Холбоотой\s+албан\s+мэдээнүүдийг')
_REWRITES = (
    (re.compile(r'^Энэ асуултад хариулах (?:тодорхой )?мэдээлэл хадгалсан эх сурвалж(?:аас|ид) олдсонгүй\.?$'),
     lambda m: 'Энэ талаар мэдээлэл олдсонгүй.'),
    (re.compile(r'^Асуусан (?P<x>.+?) хадгалсан эх сурвалжид олдсонгүй\.?$'), lambda m: 'Асуусан ' + m['x'] + ' олдсонгүй.'),
    (re.compile(r'^Энэ хайлтаар олдсон эхэд (?P<x>.+?) тодорхой заагаагүй байна\.?$'),
     lambda m: _cap(m['x']) + ' олдсонгүй.'),
    (re.compile(r'^Энэ хайлтаар олдсон эхүүдээс (?P<x>.+?) (?:яг минутаар )?батлах мэдээлэл олдсонгүй\.?$'),
     lambda m: _cap(m['x']) + ' заасан мэдээлэл олдсонгүй.'),
    (re.compile(r'^Асуусан (?P<y>[\d, ]+) оны?г? (?:хүрээг хамтад нь )?батлах тохирох эх энэ хайлтаар олдсонгүй\.?$'),
     lambda m: m['y'].strip() + ' оны мэдээлэл олдсонгүй.'),
    (re.compile(r'^(?P<y>\d{4}) оны сургалтын төлбөрийн дүнг одоогийн хариултын эх батлахгүй байна\.?$'),
     lambda m: m['y'] + ' оны сургалтын төлбөрийн мэдээлэл алга.'),
    (re.compile(r'^Хадгалсан эх нь өнөөдрийн мэдээлэл.*$'),
     lambda m: 'Өнөөдрийн байдлыг (нээлттэй ажлын байр, бүртгэл гэх мэт) энэ системээс мэдэх боломжгүй.'),
    (re.compile(r'^Хадгалсан эх өнөөдрийн бодит хоолны цэс.*$'),
     lambda m: 'Өнөөдрийн хоолны цэс, үнийн мэдээлэл энэ системд алга.'),
    (re.compile(r'^Хадгалсан мэдээ өнөөдрийн валютын ханшийг батлахгүй.*$'),
     lambda m: 'Өнөөдрийн валютын ханшийг банкнаас шалгана уу.'),
    (re.compile(r'^Асуусан мэдээллийг энэ хайлтын эх сурвалжаас бүрэн баталж чадсангүй\.?$'),
     lambda m: 'Асуусан мэдээлэл бүрэн олдсонгүй.'),
    (re.compile(r'^Бэлтгэсэн хариултыг эхтэй нь нийцүүлж баталгаажуулж чадсангүй\.?$'),
     lambda m: 'Энэ асуултад итгэлтэй хариулт олдсонгүй.'),
    (re.compile(r'^Холбоотой албан эхүүдийг оллоо\.?$'), lambda m: 'Шууд хариулт олдсонгүй; холбогдох хуудсыг доор харуулав.'),
    (re.compile(r'^Аль хөтөлбөр эсвэл оныг сонирхож байгаагаа нэмбэл илүү тодорхой хариулна\.?$'),
     lambda m: 'Аль хөтөлбөр, аль оныг сонирхож байгаагаа хэлбэл илүү тодорхой хариулна.'),
)
_BY_REASON = {
    'credential_not_shared': 'Нууц үг, пин кодыг энд өгдөггүй. Хариуцсан ажилтнаас биечлэн асууна уу.',
    'personal_record_outside_scope': ('Хувийн дүн, ирц, төлбөрийн мэдээллийг энэ системээс харах боломжгүй. '
                                      'Өөрийн сургалтын системд нэвтэрч харна уу.'),
    'personal_record_service_unavailable': 'Хувийн дүн, ирц, төлбөрөө харах системийн хаягийг энд зааж өгөх боломжгүй.',
    'invalid_year_range': 'Оны дараалал буруу байна. Эхлэх, дуусах оноо шалгаад дахин асууна уу.',
}


def _cap(text):
    text = text.strip()
    return text[:1].upper() + text[1:]


def _sentences(text):
    return [part.strip() for part in re.split(r'(?<=[.!?])\s+', text.strip()) if part.strip()]


def plain_note(result, referral_text=''):
    """One plain sentence for a reply without an answer, then where to ask."""
    reason = result.get('reason_code')
    if reason == 'personal_identifier_outside_scope':
        q = str(result.get('query') or '').casefold()
        lead = ('Ажилтны гар утасны дугаарыг энд өгдөггүй.' if re.search(r'утас|дугаар', q)
                else 'Хүний регистр, иргэний үнэмлэхийн дугаарыг энд өгдөггүй.')
    elif reason in _BY_REASON:
        lead = _BY_REASON[reason]
    else:
        original = result.get('audit_message', result.get('message')) or ''
        if referral_text and original.endswith(referral_text):
            original = original[:-len(referral_text)]
        kept = []
        for sentence in _sentences(original):
            if _DROP.search(sentence):
                continue
            for pattern, rewrite in _REWRITES:
                match = pattern.match(sentence)
                if match:
                    sentence = rewrite(match)
                    break
            kept.append(sentence)
        lead = ' '.join(kept) or 'Энэ талаар мэдээлэл олдсонгүй.'
    return (lead + ' ' + referral_text).strip()


def present(result, *, confirmed_school_hours=False):
    """Plain wording for one checked reply; returns the same dict (also when unchanged)."""
    if not isinstance(result, dict):
        return result
    answer = result.get('answer')
    if isinstance(answer, str) and answer.strip():
        shown = clean_text(answer, keep_website_hours=not confirmed_school_hours)
        shown = direct_first(result.get('query'), shown)
        if shown != answer:
            result['answer'] = shown
        if result.get('message') and result.get('answer_kind') not in {
                'partial_teacher_directory', 'partial_official_website_extract'}:
            # The note under a full answer was the guard talking to itself; the page hides it.
            result['audit_message'] = result['message']
            result['message'] = ''
    elif not result.get('clarification') and result.get('message') and result.get('reason_code') not in {
            'conversation_help', 'out_of_scope'}:
        referral = (result.get('referral') or {}).get('text', '')
        result['audit_message'] = result.get('audit_message', result['message'])
        result['message'] = plain_note(result, referral)
    for source in result.get('related_sources') or []:
        if isinstance(source, dict) and isinstance(source.get('excerpt'), str):
            source['excerpt'] = clean_text(source['excerpt'], keep_website_hours=not confirmed_school_hours)
    return result
