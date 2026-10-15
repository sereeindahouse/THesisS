"""Bounded Mongolian speech formatting; display/source text stays unchanged.

Only explicitly labelled integer currency amounts are verbalised. Dates, phone
numbers, times, programme codes, decimals and numeric ranges remain literal.
"""
import re

_ONES = ('', 'нэг', 'хоёр', 'гурван', 'дөрвөн', 'таван', 'зургаан', 'долоон', 'найман', 'есөн')
_TENS = ('', 'арван', 'хорин', 'гучин', 'дөчин', 'тавин', 'жаран', 'далан', 'наян', 'ерэн')
_AMOUNT = re.compile(
    r'(?<![\w.,:+/–—-])(?P<number>[1-9]\d{0,2}(?:,\d{3})+|0|[1-9]\d*)'
    r'\s*(?P<unit>₮|төгрөг(?:ийн|өөр|ийг|өөс)?|MNT)(?!\w)', re.I)


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
