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
- when the question asks for one field (e-mail, phone, address, the head of a unit) or an
  amount («хэдэн минут»), the line or sentence that holds it is moved to the top;
- (11/23, 2) a website excerpt of several cards starts at the asked card when the cards
  before it share no word with the question; number cards («8/13 / Бүртгэл хаагдах /
  16:00 цаг») read as one line; a quoted page keeps its title and date after the answer;
- a reply without an answer gets one plain sentence chosen from the guard's reason, and
  the guard's own wording is kept in `audit_message` for diagnosis.

It never adds a fact: the only text it writes is a sentence about what was not found,
the label order of a number card, and the source line «(Эх сурвалж: <page>, <date>)».
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
# the excerpt first, then the page and the day it was saved in one short line, so the year of a fee or a rule
# stays next to the value (11/23 full suite: «Сургалтын төлбөр: жилд 8,280,000 ₮.» had lost «Элсэлт 2026»).
_EXTRACT_HEADER = re.compile(
    r'\A(?P<title>[^\n]+?) \(татсан: (?P<date>\d{4}-\d{2}-\d{2})\)(?:\n\n(?P<notice>.+?))? — эхийн мэдээлэл:\n\n', re.S)
_SOURCE_TAIL = re.compile(r'\n\n\(Эх сурвалж: [^\n]+\)\Z')
# A Japanese card label in front of the Mongolian title («合宿 · Гашшүкү хөтөлбөр»).
_CJK_LABEL = re.compile(r'[぀-ヿ㐀-鿿]+\s*·\s*')
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


_STAT_VALUE = re.compile(r'\d[\d.,/%₮+:\- ]*[₮%]?')  # «7», «8/13», «20,000₮», «100%»


def _stat(line):
    """A card's value: short, and not a year or a phone number (code review 11/23 (2))."""
    return (bool(_STAT_VALUE.fullmatch(line)) and len(line) <= 8 and not re.fullmatch(r'(?:19|20)\d{2}', line)
            and not re.search(r'\d{7}', line.replace(' ', '')))


def _short(line, words=6):
    return 0 < len(line.split()) <= words and not re.search(r'[.!?:;]$', line)


def _stat_cards(text):
    """Website number cards — a value line, its label and a short note («8/13\\nБүртгэл хаагдах\\n16:00 цаг») —
    as one line «Бүртгэл хаагдах: 8/13 (16:00 цаг)». Only when two or more cards are found, and a label must
    start with a letter («1\\n1-р курс\\n…» is a numbered list, not a card)."""
    lines = text.split('\n')
    out, i, cards = [], 0, 0
    while i < len(lines):
        value = lines[i].strip()
        label = lines[i + 1].strip() if i + 1 < len(lines) else ''
        if (_stat(value) and _short(label) and re.match(r'[A-Za-zА-ЯЁӨҮа-яёөү]', label)
                and not _STAT_VALUE.fullmatch(label)):
            note = lines[i + 2].strip() if i + 2 < len(lines) else ''
            after = lines[i + 3].strip() if i + 3 < len(lines) else ''
            # A card's note is short and does not start like a heading («Хугацааны хуваарь» after the last card).
            has_note = (_short(note, 5) and not _STAT_VALUE.fullmatch(note)
                        and (not after or _stat(after) or not re.match(r'[А-ЯЁӨҮ]', note)))
            out.append(label + ': ' + value + (' (' + note + ')' if has_note else ''))
            i += 3 if has_note else 2
            cards += 1
            continue
        out.append(lines[i])
        i += 1
    return '\n'.join(out) if cards >= 2 else text


_CJK_LINE = re.compile(r'[\s぀-ヿ㐀-鿿·・]+')


def _drop_labels(text):
    """A page's own labels between the sentences (11/26, a sweep of random questions): a card's caption in Japanese
    with its number («教室» then «01»), a lone «Дэлгэрэнгүй», a heading said again in small letters, whole or by its
    last word («Эрхэм зорилго» / «зорилго» — the page's alternative text). Narrow on purpose (code review): Japanese
    text without a card number, a list item said twice («Физик», «Физик») and a capitalised line («Хими» after
    «Органик хими») stay, and so do the source's sentences and values."""
    lines, out, skip = text.split('\n'), [], False
    for index, line in enumerate(lines):
        bare = line.strip()
        if skip:
            skip = False
            continue
        following = lines[index + 1].strip() if index + 1 < len(lines) else ''
        if bare and _CJK_LINE.fullmatch(bare) and re.fullmatch(r'0\d', following):
            skip = True              # the caption and its card number go together
            continue
        if bare == 'Дэлгэрэнгүй':
            continue
        previous = out[-1].strip() if out else ''
        if (bare and previous and bare[:1].islower() and previous[:1].isupper() and len(bare.split()) <= 3
                and not re.search(r'\d', bare) and (bare.casefold() == previous.casefold() or (
                    len(bare.split()) == 1 and len(previous.split()) <= 4
                    and previous.casefold().split()[-1:] == [bare.casefold()]))):
            continue
        out.append(line)
    return '\n'.join(out)


def clean_text(text, *, keep_website_hours=True):
    """Website menu/form fragments, citation markers and shouting out; the source's words stay."""
    if not isinstance(text, str) or not text.strip():
        return text
    header = _EXTRACT_HEADER.match(text)
    tail = ''
    if header:
        text = text[header.end():] + ('\n\n' + header['notice'].strip() if header['notice'] else '')
        tail = '\n\n(Эх сурвалж: ' + header['title'].strip() + ', ' + header['date'] + ')'
    text = _CJK_LABEL.sub('', text)
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
    text = _stat_cards(text)
    text = _drop_labels(text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    text = re.sub(r'[ \t]+\n', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip() + tail


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


# «Ярилцлага хэдэн минут үргэлжлэх вэ?» — the sentence with the asked amount, not the description before it.
_QUANTITIES = (
    (re.compile(r'хэдэн\s+минут|хэр\s+удаан\s+үргэлж|хэдэн\s+цаг\s+үргэлж'), re.compile(r'\d+\s*минут|\d+\s*цаг\s+үргэлж')),
    (re.compile(r'хэдэн\s+үг'), re.compile(r'\d+(?:\s*[–-]\s*\d+)?\s*үг')),
)
_MISSION = re.compile(r'\n\nЭрхэм зорилго:.*\Z', re.S)


def _lead(units, hit):
    """Move the asked sentence to the front. A bare «Тийм.» or «Үгүй.» that opened the text answered a yes/no
    question, not this one, and goes (11/23, check set Q13: «… 7–30 хоногийн хугацаанд дадлага хийнэ. Тийм. …»)."""
    first = units[0]
    units.insert(0, units.pop(hit))
    if re.fullmatch(r'(?:Тийм|Үгүй)[.!]?', first.strip()):
        units.remove(first)
    return units


def direct_first(query, text):
    """Move the line, list item or sentence that holds the asked field or amount to the top. Only for «<unit>-ийн
    эрхлэгч хэн бэ?» is something left out: the unit's mission statement printed under the head's name."""
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
        if re.search(r'(?<!\w)хэн(?!\w)', q) and re.match(r'[^\n]{3,160}эрхлэгч:\s*\S', text):
            # «Ерөнхий Эрдмийн тэнхимийн эрхлэгч: Б.Сэлмаа.» answers it; the mission paragraph is not the answer
            # (the source line after it stays — code review 11/23 (2)).
            body, tail = _split_tail(text)
            return _MISSION.sub('', body) + tail
        roster = re.match(r'(?P<head>[^\n:]{3,120}:\s*)(?P<items>[^\n]+)', text)
        if roster and ';' in roster['items']:
            items = [item.strip() for item in roster['items'].rstrip('.').split(';')]
            hit = next((i for i, item in enumerate(items) if role.group(0)[:4] in item.casefold()), None)
            if hit is not None:
                # «Билгүүн (МИТ-ийн эрхлэгч).» first, then the rest of the published list.
                lead = items.pop(hit)
                return lead + '.\n\n' + roster['head'] + '; '.join(items) + '.' + text[roster.end():]
        return text
    for asks, holds in _QUANTITIES:
        if asks.search(q):
            body, tail = _split_tail(text)
            if '\n' not in body.strip():
                units = _sentences(body)
                hit = next((i for i, unit in enumerate(units) if holds.search(unit)), None)
                if hit:
                    return ' '.join(_lead(units, hit)) + tail
            return text
    # «Монбүшёо тэтгэлэгт хэдэн оюутан хамрагдсан бэ?» — the line with «12 оюутан» when it is buried under the card.
    counted = re.search(r'хэдэн\s+([а-яөүё]{3,})', q)
    if counted:
        holds = re.compile(r'\d[\d,. ]*' + re.escape(counted.group(1)[:4]), re.I)
        body, tail = _split_tail(text)
        lines = body.split('\n')
        if len(lines) > 1:
            hit = next((i for i, line in enumerate(lines) if holds.search(line)), None)
            if hit is not None and hit >= 2:
                lines.insert(0, lines.pop(hit))
                return '\n'.join(lines) + tail
        else:
            units = _sentences(body)
            hit = next((i for i, unit in enumerate(units) if holds.search(unit)), None)
            if hit:
                return ' '.join(_lead(units, hit)) + tail
    return text


# A yes/no question, anywhere in the wording: its particle (a «юу» that is not «юу вэ / юу бэ»), a tag («биз»), or
# Latin letters only (the particle cannot be read). Under these a leading «Тийм.» is the answer and stays.
_YES_NO_ASKED = re.compile(r'(?<!\w)(?:уу|үү|юү|биз)(?!\w)|(?<!\w)юу(?!\s+(?:вэ|бэ)(?!\w))(?!\w)')
_CYRILLIC = re.compile(r'[а-яөүё]', re.I)
_WHAT_IS = re.compile(r'^\s*(?P<name>\S.*?)\s+(?:гэж\s+юу|гэдэг\s+(?:нь\s+)?юу)(?!\w)|'
                      r'^\s*(?P<about>\S.*?)\s+(?:талаар|тухай)(?!\w)')
_NAME_END = re.compile(r'\s*(?:—|–|:|\s-\s)')


def drop_yes(query, text):
    """A stored answer written for a yes/no question opens with «Тийм.»; under another wording of the question
    («Нийтийн хоолны газрын талаар») that word answers nothing, so it goes and the sentences stay. «Үгүй.»
    always stays: without it the rest would read as a yes (code review, 11/25)."""
    if (not isinstance(text, str) or not isinstance(query, str) or not _CYRILLIC.search(query)
            or _YES_NO_ASKED.search(query.casefold())):
        return text
    opened = re.match(r'Тийм[.!]\s+(?=\S)', text)
    return _cap(text[opened.end():]) if opened else text


def named_first(query, text):
    """«Гашшүкү хөтөлбөр гэж юу вэ?» — the line of a stored answer that opens with the asked name goes to the top:
    a plain line is moved, a list item is repeated above its list (the list stays whole). Nothing is rewritten."""
    if not isinstance(text, str) or not isinstance(query, str):
        return text
    asked = _WHAT_IS.search(query)
    words = re.findall(r'[^\W\d_]{2,}', (asked.group('name') or asked.group('about') or '').casefold()) if asked else []
    if not words or len(words) > 5:
        return text
    body, tail = _split_tail(text)
    lines = body.split('\n')
    if len(lines) < 2:
        return text

    def opens(line):
        line = line.lstrip('•-– ').casefold()
        end = _NAME_END.search(line)
        if end is None or end.start() > 60 or not line[end.end():].strip():
            return False        # no name, or a header that only opens the list under it
        head = re.findall(r'[^\W\d_]{2,}', line[:end.start()])
        # The line's own name opens as the asked name does, and every word of it is one of the asked words
        # («JENESYS» for «JENESYS хөтөлбөр»; not «Хөтөлбөр» for «Япон улстай танилцах хөтөлбөр»).
        return bool(head) and len(head) <= len(words) and head[0][:5] == words[0][:5] and all(
            any(word[:5] == part[:5] for word in words) for part in head)
    hit = next((index for index, line in enumerate(lines) if index and opens(line)), None)
    if hit is None or opens(lines[0]):
        return text
    if lines[hit].lstrip().startswith('•'):
        return lines[hit].lstrip('• ').rstrip() + '\n\n' + body + tail
    lead = lines.pop(hit)
    return lead + '\n\n' + '\n'.join(lines).strip('\n') + tail


def _split_tail(text):
    tail = _SOURCE_TAIL.search(text)
    return (text[:tail.start()], tail.group(0)) if tail else (text, '')


# Words that say nothing about which part of a page answers («хэдэн», «байдаг», the school's own name), as the
# five-letter stems the comparison uses, so «сургуулиас» is left out too (code review 11/23 (2)).
_STOP_STEMS = frozenset({'хэдэн', 'ямар', 'хаана', 'хэзээ', 'байна', 'байда', 'болох', 'болно', 'болон', 'эсвэл',
                         'гэсэн', 'сургу', 'шмтк'})


def _stems(text):
    return {word[:5] for word in re.findall(r'[а-яёөүa-z]{4,}', text.casefold()) if word[:5] not in _STOP_STEMS}


def focus(query, text):
    """A website excerpt of several cards where the asked part starts lower down («Шалгалтаас чөлөөлөгдөх …» after
    the exam's score lines): start at the first line that shares two or more words with the question when every
    line before it shares none, and leave out the page's contact footer when contacts were not asked."""
    if not isinstance(text, str) or not isinstance(query, str):
        return text
    body, tail = _split_tail(text)
    lines = body.split('\n')
    asked = _stems(query)
    if len(lines) < 4 or len(asked) < 2:
        return text
    scores = [len(asked & _stems(line)) for line in lines]
    # The first line sharing two or more of the question's words, when no line before it shares any («Шалгалтаас
    # чөлөөлөгдөх» before the olympiad line that shares three — 11/23 (2) probes).
    start = next((i for i, score in enumerate(scores) if score >= 2), 0)
    if any(scores[:start]):
        start = 0
    end = len(lines)
    q = query.casefold()
    # Any spelling of a contact question keeps the footer («и-мэйл», «цахим шуудан» — code review 11/23 (2)).
    if not (re.search(r'холбоо', q) or any(asks.search(q) for asks, _ in _FIELDS)):
        end = next((i for i in range(start + 1, len(lines)) if lines[i].strip() == 'Холбоо барих'), end)
    if start == 0 and end == len(lines):
        return text
    return '\n'.join(lines[start:end]).strip() + tail


# --- a reply without an answer: one plain sentence instead of the guard's rule text ----------
_DROP = re.compile(  # sentences in which the system explains its own rules
    r'орлуулахгүй|орлуулж\s+хариулахгүй|хариулт\s+болгож\s+харуулахгүй|нягтлаарай|Доорх\s+сэдвүүдээс\s+мөн|'
    r'ресепшний\s+ажилтнаас|Доорх\s+(?:албан\s+)?эх(?:ийг|ийн)?\s+шал|сургуультай\s+холбо|хувийн\s+бүртгэлийн\s+хариу|'
    r'Үргэлжлэх\s+хугацаа,\s+нийт\s+оноо\s+нь|нэвтрэх\s+цэсийг\s+баталгаатай|тоон\s+босго\s+гэж\s+үзэхгүй|'
    r'банкны\s+албан\s+эхээс\s+шалгана|^Тэр\s+хүрээг\s+хасаж\s+өөр\s+асуултад\s+хариулахгүй|'
    r'Энэ\s+чат\s+суралцагчийн\s+хувийн\s+бүртгэлтэй|Холбоотой\s+хэсгийг\s+доор|Холбоотой\s+албан\s+мэдээнүүдийг|'
    r'^Тааж\s+нэгтгэхгүй')
_REWRITES = (
    (re.compile(r'^Энэ асуултад хариулах (?:тодорхой )?мэдээлэл хадгалсан эх сурвалж(?:аас|ид) олдсонгүй\.?$'),
     lambda m: 'Энэ талаар мэдээлэл олдсонгүй.'),
    (re.compile(r'^Асуусан (?P<x>.+?) хадгалсан эх сурвалжид олдсонгүй\.?$'), lambda m: 'Асуусан ' + m['x'] + ' олдсонгүй.'),
    (re.compile(r'^Энэ хайлтаар олдсон эхэд (?P<x>.+?) тодорхой заагаагүй байна\.?$'),
     lambda m: _cap(m['x']) + ' олдсонгүй.'),
    (re.compile(r'^Эхэд (?P<x>.+?) (?:тодорхой )?заагаагүй(?: байна)?\.?$'), lambda m: _cap(m['x']) + ' олдсонгүй.'),
    (re.compile(r'^Энэ хайлтаар олдсон эхүүдээс (?P<x>.+?) (?:яг минутаар )?батлах мэдээлэл олдсонгүй\.?$'),
     lambda m: _cap(m['x']) + ' заасан мэдээлэл олдсонгүй.'),
    (re.compile(r'^Асуусан (?P<y>[\d, ]+) оны?г? (?:хүрээг хамтад нь )?батлах тохирох эх энэ хайлтаар олдсонгүй\.?$'),
     lambda m: m['y'].strip() + ' оны мэдээлэл олдсонгүй.'),
    (re.compile(r'^(?P<y>\d{4}) оны сургалтын төлбөрийн дүнг одоогийн хариултын эх батлахгүй байна\.?$'),
     lambda m: m['y'] + ' оны сургалтын төлбөрийн мэдээлэл алга.'),
    (re.compile(r'^Хадгалсан эх нь өнөөдрийн мэдээлэл.*$'), lambda m: _LIVE_NOTE),
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
    # 11/23 (2): notes the 11/23 lint did not count, read in the probe banks.
    (re.compile(r'^Асуултын нэр(?:ийг энэ багцын хадгалсан асуулттай баттай холбож чадсангүй|, он, тоо эсвэл хүрээг '
                r'хамтад нь дэмжих нэг хадгалсан асуулт алга)\.?$'), lambda m: 'Энэ талаар мэдээлэл олдсонгүй.'),
    # Full test suite 11/23 (2): what was not found stays named («тусгай утас»), not a generic «not found».
    (re.compile(r'^Хадгалсан эхээр баталж чадаагүй мэдээлэл: (?P<x>.+?)\.?$'), lambda m: 'Олдоогүй мэдээлэл: ' + m['x'] + '.'),
    (re.compile(r'^Хадгалсан эхээс «(?P<x>[^»]+)»-д хамаарах давхар болон тусгай утсыг хамтад нь баталсан бүртгэл олдсонгүй\.?$'),
     lambda m: '«' + m['x'] + '»-ийн давхар, тусгай утасны мэдээлэл олдсонгүй.'),
    (re.compile(r'^Асуусан сургалтын албаны өөрийн давхар, тусгай утсыг энэ хайлтын эхээр зөрүүгүй баталж чадсангүй\.?$'),
     lambda m: 'Сургалтын албаны давхар, тусгай утасны мэдээлэл олдсонгүй.'),
    (re.compile(r'^Асуусан нэрлэсэн компанийн өөрийн он, хичээл, платформын холбоог энэ хайлтын эхээр зөрүүгүй баталж чадсангүй\.?$'),
     lambda m: 'Нэрлэсэн компанитай хамтын ажиллагааны он, хичээл, платформын мэдээлэл олдсонгүй.'),
    (re.compile(r'^Асуусан нэрлэсэн тэнхимийн өөрийн он, нийт болон курс тус бүрийн бүтэн хүснэгтийг энэ хайлтын эхээр '
                r'зөрүүгүй баталж чадсангүй\.?$'),
     lambda m: 'Нэрлэсэн тэнхимийн он, курс тус бүрийн бүтэн хүснэгт олдсонгүй.'),
    (re.compile(r'^Асуултын нэр, он, нэмэлт хүсэлт эсвэл хоёр талбарын холбоог бүрэн тодорхойлж чадсангүй\.?$|'
                r'^Асуултын бичвэрт үгүйсгэсэн эсвэл нөхцөлт хэлбэр байна\.?$'),
     lambda m: 'Асуултыг бүрэн ойлгож чадсангүй.'),
    (re.compile(r'^Сургалтын албаны давхар болон тусгай утсыг энэ эхээр баталж чадсангүй; ерөнхий сургуулийн дугаараар '
                r'орлуулахгүй\.?$'),
     lambda m: 'Сургалтын албаны давхар, тусгай утасны мэдээлэл олдсонгүй.'),
    (re.compile(r'^Асуусан .+? энэ хайлтын эхээр (?:хамтад нь |зөрүүгүй )?баталж чадсангүй\.?$'),
     lambda m: 'Энэ асуултын хариу олдсонгүй.'),
    (re.compile(r'^Баталгаажуулаагүй зүйл: (?P<x>.+?)\.?$'), lambda m: 'Олдоогүй мэдээлэл: ' + m['x'] + '.'),
    (re.compile(r'^Нэрлэсэн багшийн тухай энэ хайлтаар батлах эх олдсонгүй\.?$'), lambda m: 'Нэрлэсэн багшийн мэдээлэл олдсонгүй.'),
    (re.compile(r'^Асуусан багш нарын бүрэн нэрсийн жагсаалтыг энэ хайлтаар батлах эх олдсонгүй\.?$'),
     lambda m: 'Асуусан багш нарын нэрсийн жагсаалт олдсонгүй.'),
    (re.compile(r'^Таны нэрлэсэн бүртгэлийн хураамжийг батлах эх энэ хайлтаар олдсонгүй\.?$'),
     lambda m: 'Таны нэрлэсэн бүртгэлийн хураамжийн мэдээлэл олдсонгүй.'),
    # Code review 11/23 (2): the guard's advice reaches the visitor in plain words instead of being dropped, and the
    # remaining «…батлах хэсэг энэ хайлтаар олдсонгүй» notes of rag_runtime / source_fields.
    (re.compile(r'^Товчилсон нэр хэрэглэсэн бол бүтэн нэрийг нь бичиж, асуусан оноо хамт тодруулна уу\.?$'),
     lambda m: 'Нэр, оныг бүтнээр нь бичиж дахин асууж болно.'),
    (re.compile(r'^Таны өгсөн голчийн тоонд үндэслэн Японд дэвшин суралцах эрхтэй эсэхийг баталж чадсангүй\.?$'),
     lambda m: 'Таны голчоор Японд дэвшин суралцах эрхтэй эсэхийг энд тодорхойлох боломжгүй.'),
    (re.compile(r'^Тэр нөхцөлийг хасаж өөр асуултад хариулахгүй; хэрэгтэй хүрээгээ тодруулна уу\.?$'),
     lambda m: 'Асуултаа тодруулж дахин асууна уу.'),
    (re.compile(r'^Нэрлэсэн компанийн хамтын ажиллагааны сар, платформыг энэ эхээр баталж чадсангүй\.?$'),
     lambda m: 'Нэрлэсэн компанитай хамтын ажиллагааны сар, платформын мэдээлэл олдсонгүй.'),
    (re.compile(r'^Бичгийн болон ярилцлагын шалгалтын үргэлжлэх хугацааг хоёуланг нь батлах хэсэг энэ хайлтаар олдсонгүй\.?$'),
     lambda m: 'Бичгийн болон ярилцлагын шалгалтын үргэлжлэх хугацааны мэдээлэл олдсонгүй.'),
    (re.compile(r'^Сургалтын төлбөрийн дүнг шууд батлах тохирох заалт энэ хайлтаар олдсонгүй\.?$'),
     lambda m: 'Сургалтын төлбөрийн дүн олдсонгүй.'),
    (re.compile(r'^Элсэлтийн онлайн бүртгэлийн алхмуудыг бүрэн батлах хэсэг энэ хайлтаар олдсонгүй\.?$'),
     lambda m: 'Элсэлтийн онлайн бүртгэлийн алхмууд бүрэн олдсонгүй.'),
    (re.compile(r'^Сургуулийн имэйлийг нь асууж болно, эсвэл ресепшнээс асууна уу\.?$'),
     lambda m: 'Сургуулийн имэйлийг нь асууж болно.'),
    (re.compile(r'^Багшийн утасны дугаарыг энд харуулахгүй; ресепшнээс асууна уу\.?$'),
     lambda m: 'Багшийн утасны дугаарыг энд харуулахгүй.'),
    (re.compile(r'^Нэрлэсэн багшийн асуусан холбоо барих талбарыг өөрийн нэртэй нь нэг хэсэгт баталсан эх олдсонгүй\.?$'),
     lambda m: 'Нэрлэсэн багшийн асуусан холбоо барих мэдээлэл олдсонгүй.'),
    (re.compile(r'^Багшийн асуусан хувийн эсвэл ажлын нарийвчилсан мэдээллийг батлах эх энэ хайлтаар олдсонгүй\.?$'),
     lambda m: 'Багшийн асуусан мэдээлэл олдсонгүй.'),
)
_GENERIC = frozenset({'Энэ талаар мэдээлэл олдсонгүй.', 'Энэ асуултын хариу олдсонгүй.'})
# Whatever guard sentence is still left that explains the system's own checks («…хадгалсан асуулт алга», «…эхээр
# баталж чадсангүй», «…хүснэгтэд бүртгэгдээгүй») becomes one plain «not found» sentence (said once).
_MACHINE = re.compile(
    r'хадгалсан\s+(?:асуулт|эх(?!\s+сурвалж))|Тааж|баталж\s+чадсангүй|баталсангүй|батлахгүй|батлагдаагүй|'
    r'батлах\s+(?:тохирох\s+)?эх(?!\s+сурвалж)|хайлтын\s+эх(?!\s+сурвалж)|(?<!эцэг )(?<!\S)эх(?:ээр|ээс|эд|ийн)\s|'
    r'хүснэгтэд\s+бүртгэгдээгүй|(?<!\S)багцын|FAQ|энэ\s+хайлтаар', re.I)
_NOT_FOUND = 'Энэ талаар мэдээлэл олдсонгүй.'
_LIVE_NOTE = 'Өнөөдрийн байдлыг (нээлттэй ажлын байр, бүртгэл гэх мэт) энэ системээс мэдэх боломжгүй.'
# «… анкет өгөх гэсэн юм, хаана очих вэ?», «Хэдэн давхарт гарах вэ?», «… хэнд хэлэх вэ?» ask where to go or whom to
# tell: the office the question itself names (referral.py) is the reply, so no «not found» sentence leads it
# (check set Q28, Q34, Q35, 11/23).
# 11/26: «тодорхойлолт хаанаас авах вэ», «дүнгийн хуулбар авах гэсэн юм» ask where to go too: the place, without
# «not found» before it.
_WHERE_TO_GO = re.compile(r'хаана\s+(?:очи|оч(?:но|оо)|өгө|өгн|хандах|бөглө)|хаашаа|хэд(?:эн|дүгээр)\s+давхарт?\s+гар'
                          # only a paper the school issues, asked where to get it (code review: «тэтгэлэг авмаар
                          # байна», «… хаанаас авсан бэ» are other questions)
                          r'|(?:тодорхойлолт|үнэмлэх|хуулбар|лавлагаа|гэрчилгээ|карт|маягт|анкет)\w*\s+(?:хаанаас\s+)?'
                          r'(?:авах|авна|авдаг|авмаар|гаргуулах)(?!\w)'
                          r'|хэнд\s+(?:хандах|хандана|хэлэх|хэлнэ|өгөх|мэдэгдэх)', re.I)
_BY_REASON = {
    'credential_not_shared': 'Нууц үг, пин кодыг энд өгдөггүй. Хариуцсан ажилтнаас биечлэн асууна уу.',
    'personal_record_outside_scope': ('Хувийн дүн, ирц, төлбөрийн мэдээллийг энэ системээс харах боломжгүй. '
                                      'Өөрийн сургалтын системд нэвтэрч харна уу.'),
    'personal_record_service_unavailable': 'Хувийн дүн, ирц, төлбөрөө харах системийн хаягийг энд зааж өгөх боломжгүй.',
    'invalid_year_range': 'Оны дараалал буруу байна. Эхлэх, дуусах оноо шалгаад дахин асууна уу.',
    # The reception tables' notes (reception_tables.ReceptionAnswerPath._result) in plain words; the guard's own
    # text stays in audit_message.
    'reception_data_unavailable': 'Өрөө, анги, багшийн мэдээлэл одоогоор бэлэн биш байна.',
    'reception_room_not_found': 'Нэрлэсэн өрөө олдсонгүй. Өрөөний дугаарыг шалгаад дахин асууна уу.',
    'reception_teacher_not_found': 'Нэрлэсэн багш олдсонгүй. Бүтэн нэрээр нь асууна уу.',
    'reception_time_required': 'Аль өдөр, хэдэн цагийг шалгахыг хэлнэ үү (жишээ: даваа 09:30).',
    'reception_invalid_time': 'Цагийг 00:00–23:59 хэлбэрээр бичнэ үү.',
    # Returned by many timetable questions, not only «… одоо хичээлтэй юу?» (code review 11/23 (2)).
    'reception_timetable_incomplete': 'Хичээлийн хуваарь бүрэн биш тул хуваариар хариулах боломжгүй.',
    'reception_date_required': 'Аль өдрийн хуваарийг асууж байгаагаа хэлнэ үү.',
    'reception_calendar_unknown': ('Улирлын огноо, амралтын өдрийн мэдээлэл алга тул тухайн өдрийн хуваарийг '
                                   'хэлэх боломжгүй.'),
    'reception_outside_term': 'Энэ өдөр хичээлийн улиралд багтахгүй.',
    'reception_holiday': 'Энэ өдөр амралтын өдөр тул хичээлийн хуваарь хамаарахгүй.',
    'reception_lookup_missing': 'Асуусан мэдээлэл олдсонгүй.',
    'reception_contact_unknown': 'Энэ албаны холбоо барих мэдээлэл олдсонгүй.',
    'reception_hours_unknown': 'Ажлын цагийн мэдээлэл олдсонгүй.',
    'reception_email_unknown': 'Энэ хүний сургуулийн имэйл олдсонгүй.',
    'reception_room_unknown': 'Энэ хүний ажлын өрөө олдсонгүй.',
    'reception_floor_unknown': 'Энэ давхрын өрөөний мэдээлэл олдсонгүй.',
}
# The FAQ router's questions back to the visitor (question_router.route_query clarify()), by the clarification's
# kind, so a later wording change in the router cannot bring the machine text back (code review 11/23 (2)).
_CLARIFY = {
    'ambiguous_constrained_exact_match': ('Энэ асуулт хэд хэдэн сэдэвт хамаарч байна. Аль хөтөлбөр, аль он, аль '
                                          'албаны тухай асууж байгаагаа тодруулна уу.'),
    'ambiguous_exact_match': 'Ижил төстэй хэд хэдэн асуулт байна. Аль нь болохыг доороос сонгоно уу.',
    'constrained_wording_not_exact': 'Яг аль хүний, аль хөтөлбөрийн эсвэл аль хичээлийн жилийн мэдээлэл хэрэгтэйг тодруулна уу.',
    'select_supported_question': 'Төстэй хэд хэдэн асуулт байна. Аль нь болохыг доороос сонгоно уу.',
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
    elif reason in _BY_REASON and result.get('note_kept') and result.get('message'):
        # 11/28 sweep: the tables' own note names the person and where they sit («Х.Ганчимэг — сургуулийн имэйл
        # бүртгэгдээгүй. Ажлын өрөө: …»); the stock sentence «Энэ хүний …» named nobody.
        lead = str(result.get('audit_message', result['message'])).strip()
        if referral_text and lead.endswith(referral_text):
            lead = lead[:-len(referral_text)].strip()
    elif reason in _BY_REASON:
        lead = _BY_REASON[reason]
    else:
        original = result.get('audit_message', result.get('message')) or ''
        if referral_text and original.endswith(referral_text):
            original = original[:-len(referral_text)]
        lead = _plain(original, _NOT_FOUND)
        # «Хүүхэд маань өвдөөд өнөөдөр хичээлдээ ирж чадахгүй нь хэнд хэлэх вэ?» (Q28): «өнөөдөр» is no question about
        # today's openings, so the live-status note goes too.
        if (lead in (_NOT_FOUND, _LIVE_NOTE) and referral_text
                and (result.get('referral') or {}).get('office_source') == 'question'
                and _WHERE_TO_GO.search(str(result.get('query') or ''))):
            lead = ''
    return (lead + ' ' + referral_text).strip()


def _plain(original, fallback):
    """The guard's sentences without the rule talk. A sentence still about the system's checks becomes ``fallback``
    when it leads, and is left out after a kept sentence; a partial answer's notice never says that nothing was found
    (code review 11/23 (2))."""
    kept = []
    for sentence in _sentences(original):
        if _DROP.search(sentence):
            continue
        for pattern, rewrite in _REWRITES:
            match = pattern.match(sentence)
            if match:
                sentence = rewrite(match)
                break
        else:
            if _MACHINE.search(sentence):
                if kept:
                    continue
                sentence = fallback
        if fallback != _NOT_FOUND and sentence in _GENERIC:
            sentence = fallback
        if sentence == fallback and any('олдсонгүй' in earlier for earlier in kept):
            continue
        kept.append(sentence)
    return ' '.join(kept) or fallback


# --- a website excerpt that is only menu or tile labels ------------------------------------------------------
# 11/25, the user: «хариулт хангалтгүй». «Механик инженерийн хөтөлбөрийн талаар хэлж өгөөч» showed «Дэлгэрэнгүй / 03 /
# Механик инженерийн тэнхим» (a tile of the departments index), «Карьер хөгжлийн төв юу хийдэг вэ?» showed a floor
# plan's «Сэтгэл зүйчийн өрөө: 08 / Техникийн өрөө: 09». Such an excerpt holds no sentence: it is not an answer to
# an open question. A question that asks for one value (хэд, хэзээ, хэн, хаана, утас …) may be answered by a tile's
# number or date, so it is left to the typed-value check.
_CLOSED = re.compile(r'[.!?…]["»”)]?$')                     # a line closed like a sentence
_VALUE_ASKED = re.compile(r'(?<!\w)(?:хэд|хэдэн|хэддүгээр|хэдий|хэзээ|хэн|хэнд|хаана|хаашаа|аль)(?!\w)|'
                          r'утас|мэйл|шуудан|(?<!\w)хаяг|дугаар', re.I)


def is_fragment(text):
    """Whether the text is labels only. A line says something when it is closed like a sentence («Тийм, дотуур
    байртай.»), lists things with a comma («Математик, англи хэл»), or is long; two or more list items also do.
    Short lines without any of these («Дэлгэрэнгүй», «03», «Техникийн өрөө: 09») are a page's labels.
    Code review 11/25: the first form asked for five words and a full stop, which would have withheld short
    correct answers."""
    lines = [line.strip() for line in str(text or '').split('\n') if line.strip()]
    if not lines:
        return False
    if sum(line.startswith(('•', '-', '–')) for line in lines) >= 2:
        return False

    def says_something(line):
        words = re.findall(r'[^\W\d_]{2,}', line)
        return (len(words) >= 2 and _CLOSED.search(line) is not None) or (len(words) >= 3 and ',' in line) or len(words) >= 10
    return not any(says_something(line) for line in lines)


def withhold_fragment(result):
    """A website excerpt of labels only, shown for an open question, becomes «not found» (where to ask is added
    after it); the withheld text stays in ``withheld_answer`` for the audit."""
    if (not isinstance(result, dict) or result.get('answer_kind') != 'rag_generated'
            or not isinstance(result.get('answer'), str) or not result['answer'].strip()
            or _VALUE_ASKED.search(str(result.get('query') or ''))):
        return result
    if not is_fragment(clean_text(result['answer'])):
        return result
    result.update(route='E', withheld_answer=result['answer'], answer=None, citations=[], clarification=None,
                  reason_code='website_fragment_withheld', message=_NOT_FOUND)
    return result


def present(result, *, confirmed_school_hours=False):
    """Plain wording for one checked reply; returns the same dict (also when unchanged)."""
    if not isinstance(result, dict):
        return result
    answer = result.get('answer')
    if isinstance(answer, str) and answer.strip():
        shown = clean_text(answer, keep_website_hours=not confirmed_school_hours)
        if result.get('answer_kind') in {'rag_generated', 'official_website_extract'}:
            shown = focus(result.get('query'), shown)
        shown = direct_first(result.get('query'), shown)
        if result.get('answer_kind') == 'official_website_snapshot':
            # A stored answer under another wording of its question: no stray «Тийм.», the asked name first.
            shown = named_first(result.get('query'), drop_yes(result.get('query'), shown))
        if shown != answer:
            result['answer'] = shown
        if result.get('message') and result.get('answer_kind') not in {
                'partial_teacher_directory', 'partial_official_website_extract'}:
            # The note under a full answer was the guard talking to itself; the page hides it.
            result['audit_message'] = result['message']
            result['message'] = ''
        elif result.get('message'):
            # A partial answer keeps its notice (what is missing), in plain words (11/23 (2)).
            plain = _plain(result['message'], 'Асуусан мэдээллийн зарим нь олдсонгүй.')
            if plain != result['message']:
                result['audit_message'] = result['message']
                result['message'] = plain
    elif not result.get('clarification') and result.get('message') and result.get('reason_code') not in {
            'conversation_help', 'out_of_scope'}:
        referral = (result.get('referral') or {}).get('text', '')
        result['audit_message'] = result.get('audit_message', result['message'])
        result['message'] = plain_note(result, referral)
    elif isinstance(result.get('clarification'), dict):
        plain = _CLARIFY.get(result['clarification'].get('kind'))
        asked = result['clarification'].get('question')
        if plain and asked != plain:
            result['audit_message'] = result.get('audit_message', result.get('message'))
            result['clarification']['question'] = plain
            if result.get('message') == asked:
                result['message'] = plain
    for source in result.get('related_sources') or []:
        if isinstance(source, dict) and isinstance(source.get('excerpt'), str):
            source['excerpt'] = clean_text(source['excerpt'], keep_website_hours=not confirmed_school_hours)
    return result
