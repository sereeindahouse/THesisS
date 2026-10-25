"""Bounded Mongolian speech formatting; display/source text stays unchanged.

Explicit currency, standalone 2000–2099 calendar years and labelled eight-digit
phone numbers have bounded verbalizers. The explicit educational acronym ЕБС
and its reviewed possessive ЕБС-ийн expand for speech only. Dates, ranges, other identifiers and
ambiguous forms remain literal. This formats text; it does not establish human
intelligibility or change the displayed evidence.
"""
import re

_ONES = ('', 'нэг', 'хоёр', 'гурван', 'дөрвөн', 'таван', 'зургаан', 'долоон', 'найман', 'есөн')
_TENS = ('', 'арван', 'хорин', 'гучин', 'дөчин', 'тавин', 'жаран', 'далан', 'наян', 'ерэн')
_AMOUNT = re.compile(
    r'(?<![\w.,:+/–—-])(?P<number>[1-9]\d{0,2}(?:,\d{3})+|0|[1-9]\d*)'
    r'\s*(?P<unit>₮|төгрөг(?:ийн|өөр|ийг|өөс)?|MNT)(?!\w)', re.I)
_YEAR = re.compile(
    r'(?<![\w.,:/+–—-])(?P<number>20[0-9]{2})(?P<space>[ \t]+)'
    r'(?P<unit>оны|онд|он)(?!\w)', re.I)
_PHONE = re.compile(
    r'(?P<label>(?<!\w)утас(?:ны[ \t]+дугаар)?[ \t]*:?[ \t]*)'
    r'(?P<number>[0-9]{8})(?![\w/+–—-]|[.,][0-9])', re.I)
_DIGITS = ('тэг', 'нэг', 'хоёр', 'гурав', 'дөрөв', 'тав', 'зургаа', 'долоо', 'найм', 'ес')
_EDUCATIONAL_ACRONYM = re.compile(
    r'(?<![\w/\\@.+~%=:?#&|$–—-])ЕБС(?P<possessive>-ийн)?'
    r'(?![\w/\\@+~%=#&|$–—-]|[.:?][\w])')
_EDUCATIONAL_CREDIT = re.compile(
    r'(?<![\w.,/\\@+~%=:#?&|$–—-])(?P<number>[0-9]{1,3}(?:[.,][0-9]{1,2})?)'
    r'[ \t]*кр(?:[ \t]+|\.[ \t]*)цаг(?P<suffix>ийн|аас|аар|ийг)?'
    r'(?![\w/\\@+~%=#&|$–—-]|[.:?][\w])',re.I)


def normalize_spoken_educational_credits(text):
    """Expand only numbered кр цаг/кр.цаг in nearby educational prose.

    The official НССДС credit-equivalence guide labels its unit кредит цаг
    and кр.цаг (usp.edu.mn, Бакалаврын сургалтын журмын14-р хавсралт).
    This speech-only expansion preserves the written number and case ending;
    it is neither a credit conversion nor a measured human pronunciation gain.
    """
    breaks=[]
    for match in re.finditer(r'[.!?;\r\n]',text):
        index=match.start()
        if match[0]=='.' and ((index>0 and index+1<len(text)
                and text[index-1].isdigit() and text[index+1].isdigit())
                or (text[max(0,index-2):index].casefold()=='кр'
                    and re.match(r'[ \t]*цаг(?:ийн|аас|аар|ийг)?(?!\w)',text[index+1:],re.I))):
            continue
        breaks.append(index)

    def expand(match):
        before,after=text[:match.start()],text[match.end():]
        if (re.search(r'(?:\d|цаг(?:ийн|аас|аар|ийг)?)\s*[–—/\-]\s*$',before,re.I)
                or re.match(r'\s*[–—/\-]\s*\d',after)
                or re.search(r'(?:код|id|дугаар|файлын\s+нэр|url|хаяг)\s*[:=#]?\s*$',before,re.I)):
            return match.group()
        left=max((index+1 for index in breaks if index<match.start()),default=0)
        right=min((index for index in breaks if index>=match.end()),default=len(text))
        context=text[max(left,match.start()-160):min(right,match.end()+160)]
        if not re.search(r'(?<!\w)(?:хичээл\w*|оюут\w*|суралц\w*|сургал\w*)(?!\w)',context,re.I):
            return match.group()
        return match['number']+' кредит цаг'+(match['suffix'] or '')
    return _EDUCATIONAL_CREDIT.sub(expand,text)


def normalize_spoken_educational_acronyms(text):
    """Expand only the two reviewed uppercase ЕБС forms, preserving grammar.

    Unsupported suffixes, compounds, identifiers and mixed/lowercase spellings
    remain literal. This is a speech rendering rule, not evidence correction,
    a general acronym dictionary or a claim of improved human intelligibility.
    """
    def expand(match):
        # Do not turn spaced, unsupported compound spellings into a new form.
        if (re.match(r'[ \t]+[-–—/][ \t]*\w', text[match.end():]) or
            re.search(r'\w[ \t]+[-–—/][ \t]*$', text[:match.start()])):
            return match.group()
        return ('ерөнхий боловсролын сургуулийн' if match['possessive']
                else 'ерөнхий боловсролын сургууль')
    return _EDUCATIONAL_ACRONYM.sub(expand, text)


def _calendar_year(number):
    """A linking numeral before он/оны/онд, restricted by _YEAR to 2000–2099."""
    remainder = number - 2000
    if remainder == 0:
        return 'хоёр мянган'
    if remainder % 10 == 1:
        # Linking нэгэн before a noun; do not reuse this form for phone digits.
        tail = (_TENS[remainder // 10] + ' ' if remainder >= 10 else '') + 'нэгэн'
    else:
        tail = _small(remainder)
    return 'хоёр мянга ' + tail


def normalize_spoken_years_and_phones(text):
    """Verbalize only explicit year and phone spans, preserving all other text.

    Phone groups are read as eight separate digits with a comma after four;
    leading zeros and digit order survive. This is not phone validation. Calendar
    dates/ranges and phone extensions/ranges need a separate, reviewed grammar.
    """
    def year(match):
        before, after = text[:match.start()], text[match.end():]
        if re.search(r'(?:[0-9]|[0-9]{4}\s+(?:он|оны|онд))\s*[–—/\-]\s*$', before, re.I):
            return match.group()
        if re.match(r'\s*[–—/\-]\s*[0-9]', after):
            return match.group()
        # Keep full dates literal, including numeric and written month names.
        if re.match(r'\s+(?:[0-9]{1,2}(?:-р|\s+(?:дугаар|дүгээр))?'
                    r'|[а-яөүё -]{1,35}(?:дугаар|дүгээр))\s+сар', after, re.I):
            return match.group()
        return _calendar_year(int(match['number'])) + match['space'] + match['unit']

    text = _YEAR.sub(year, text)

    def phone(match):
        after = text[match.end():]
        if re.match(r'\s*[–—/\-]\s*[0-9]|\s+[0-9]|\s*[,;]\s*[0-9]'
                    r'|\s+(?:дотуур|нэмэлт|ext\.?|extension)\b'
                    r'|\.[\w]|\s*(?:₮|төгрөг\b|MNT\b)', after, re.I):
            return match.group()
        digits = match['number']
        groups = [' '.join(_DIGITS[int(d)] for d in digits[i:i + 4]) for i in (0, 4)]
        return match['label'] + ', '.join(groups)

    return _PHONE.sub(phone, text)


def _small(number):
    words = []
    if number >= 100:
        words.extend((_ONES[number // 100], 'зуун'))
    number %= 100
    if number >= 10:
        words.append(_TENS[number // 10])
    if number % 10:
        words.append(_ONES[number % 10])
    return ' '.join(words)


def _currency_number(number):
    if number == 0:
        return 'тэг'
    words = []
    for scale, name in ((1_000_000, 'сая'), (1_000, 'мянга')):
        if number >= scale:
            group, number = divmod(number, scale)
            words.append(_small(group))
            words.append('мянган' if scale == 1_000 and number == 0 else name)
    if number:
        words.append(_small(number))
    return ' '.join(words)


def normalize_spoken_currency(text):
    """Format unambiguous currency only; idempotent and free of providers."""
    def replace(match):
        # Do not verbalise only one endpoint of a range such as 5,000–20,000 ₮.
        if re.search(r'[\d,]\s*[–—-]\s*$', text[:match.start()]):
            return match.group()
        number = int(match['number'].replace(',', ''))
        if number > 999_999_999:
            return match.group()
        unit = match['unit']
        if unit == '₮' or unit.casefold() == 'mnt':
            unit = 'төгрөг'
        return _currency_number(number) + ' ' + unit
    return _AMOUNT.sub(replace, text)


def remove_rendered_citations(text, citation_count):
    """Remove only a known trailing marker added by render_claims per line."""
    def replace(match):
        return '' if 1 <= int(match[1]) <= citation_count else match.group()
    return re.sub(r' \[(\d+)\](?=\r?\n|$)', replace, text)


def normalize_spoken_notation(text, *, official_extract=False):
    """Format bounded spoken notation and omit only the extraction caption.

    Keep academic years, source titles, period notices and all body text. The
    displayed evidence is untouched; a retrieval timestamp is not a spoken fact.
    """
    if official_extract:
        heading, separator, body = text.partition(' — эхийн мэдээлэл:\n\n')
        if separator:
            heading = re.sub(r'\A([^\n]+) \(татсан: \d{4}-\d{2}-\d{2}\)(?=\n|$)', r'\1', heading)
            text = heading.rstrip('. ') + '.\n\n' + body
    text = re.sub(r'(?<!\w)QR(?=\s+код)', 'кью ар', text, flags=re.I)
    text = normalize_spoken_educational_acronyms(text)
    text = normalize_spoken_educational_credits(text)
    return normalize_spoken_years_and_phones(text)
