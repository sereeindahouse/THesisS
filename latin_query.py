"""Mongolian typed in Latin letters, read in Cyrillic before the question is planned (2026-11-23).

People type Mongolian in Latin letters on a phone («surguuli haana bdag ve», «dotuur bair bga yu»); the system
answered none of them (papers/52, 11/23 test: 0 of 9). The user asked on 11/23 evening that the 40 check
questions work, two of which are in Latin letters (Q19, Q23); papers/52 §5 keeps the full study (Byambadorj et
al., 2020, a trained model) as future work. This is the small rule-based part of proposal (1)+(2):

  * the usual shortenings first («bdag» байдаг, «bga» байгаа, «bn» байна, «ve» вэ …);
  * letter groups by the usual chat spelling (sh ш, ch ч, ts ц, kh х, ya я, yu ю …);
  * an ambiguous letter (o о/ө, u у/ү/ө, e э/е, i и/ь/ий) is chosen by the words the school's own texts use
    (the most frequent spelling found there), otherwise the first reading.

Only a question written entirely in Latin letters is converted, and not an English one («where is room 508»,
which the reception path reads as it is). The visitor is shown how it was read («Ингэж ойлголоо: …»).
"""
import re
from collections import Counter

SHORT = {
    'bdag': 'байдаг', 'bgaa': 'байгаа', 'bga': 'байгаа', 'bn': 'байна', 'bnu': 'байна уу', 'bnuu': 'байна уу',
    'bhgui': 'байхгүй', 'bhq': 'байх', 've': 'вэ', 'be': 'бэ', 'yu': 'юу', 'yuu': 'юу', 'uu': 'уу', 'vv': 'үү',
    'yum': 'юм', 'ene': 'энэ', 'ter': 'тэр', 'end': 'энд', 'tend': 'тэнд', 'haana': 'хаана', 'hezee': 'хэзээ',
    'heden': 'хэдэн', 'hed': 'хэд', 'hen': 'хэн', 'yamar': 'ямар', 'yaj': 'яаж', 'bagsh': 'багш', 'surguuli': 'сургууль',
    'surguuliin': 'сургуулийн', 'tanai': 'танай', 'manai': 'манай', 'ni': 'нь', 'bol': 'бол', 'gej': 'гэж',
    'bolomj': 'боломж', 'bolno': 'болно', 'boloh': 'болох', 'hereg': 'хэрэг', 'tsag': 'цаг', 'davhar': 'давхар',
    'davhart': 'давхарт', 'oroo': 'өрөө', 'uruu': 'өрөө', 'too': 'тоо', 'toot': 'тоот',
}
UNITS = (('sh', ['ш']), ('ch', ['ч']), ('ts', ['ц']), ('kh', ['х']), ('zh', ['ж']), ('ya', ['я']), ('yu', ['ю']),
         ('ye', ['е']), ('yo', ['ё']), ('ai', ['ай']), ('ei', ['эй']), ('oi', ['ой', 'өй']), ('ui', ['уй', 'үй']),
         ('ii', ['ий']), ('aa', ['аа']), ('ee', ['ээ']), ('oo', ['оо', 'өө']), ('uu', ['уу', 'үү', 'өө']),
         ('a', ['а']), ('b', ['б']), ('c', ['ц', 'с']), ('d', ['д']), ('e', ['э', 'е']), ('f', ['ф']), ('g', ['г']),
         ('h', ['х']), ('i', ['и', 'ь', 'ий']), ('j', ['ж']), ('k', ['к', 'х']), ('l', ['л']), ('m', ['м']), ('n', ['н']),
         ('o', ['о', 'ө']), ('p', ['п']), ('q', ['ө']), ('r', ['р']), ('s', ['с']), ('t', ['т']), ('u', ['у', 'ү', 'ө']),
         ('v', ['в', 'ү']), ('w', ['в']), ('x', ['х']), ('y', ['ы', 'й', 'ү']), ('z', ['з']))
# «tulbur» is «төлбөр»: «u» stands for у, ү and ө in chat spelling (the school's words decide).
ENGLISH = frozenset('where is the what when who how room teacher are you do does can i a an of in on at to for and'.split())
# Names written in Latin letters on the school's own pages stay as they are («QPay» is no «өпаы»).
KEEP = frozenset('qpay sakura internet arc jica nmct it moodle facebook messenger zoom gmail email google kosen robocon naprock'.split())
_LATIN_WORD = re.compile(r'[a-z]+')
MAX_CANDIDATES = 512


def _options(word):
    """Readings of each letter group, longest group first."""
    options, position = [], 0
    while position < len(word):
        for unit, readings in UNITS:
            if word.startswith(unit, position):
                options.append(readings)
                position += len(unit)
                break
        else:
            return None
    return options


def _spellings(options):
    spellings = ['']
    for readings in options:
        # Pruned at each letter group, so a long word is still read to its end (code review 11/23 (8)).
        spellings = [prefix + reading for prefix in spellings for reading in dict.fromkeys(readings)][:MAX_CANDIDATES]
    return spellings


def latin_question(text):
    """True for a question written only in Latin letters (no Cyrillic), not an English one."""
    if not isinstance(text, str) or re.search(r'[А-Яа-яӨөҮүЁё]', text):
        return False
    words = _LATIN_WORD.findall(text.casefold())
    if len(words) < 2 or len(''.join(words)) < 3:
        return False
    # A Mongolian sentence has its small words («haana», «ve», «yu», «bdag»); a name or an English question has none.
    return any(word in SHORT for word in words) and sum(word in ENGLISH for word in words) * 2 < len(words)


def to_cyrillic(text, vocabulary=None):
    """The Cyrillic reading of a Latin-letter question, or None when it is not one (see latin_question)."""
    if not latin_question(text):
        return None
    counts = vocabulary or Counter()

    def word(match):
        latin = match.group(0)
        lower = latin.casefold()
        if lower in KEEP:
            return latin
        if lower in SHORT:
            return SHORT[lower]
        options = _options(lower)
        if options is None:
            return latin
        spellings = _spellings(options)
        known = [spelling for spelling in spellings if counts.get(spelling)]
        return max(known, key=lambda spelling: counts[spelling]) if known else spellings[0]
    return re.sub(r'[A-Za-z]+', word, text)


def vocabulary_from(texts):
    """Word counts of the school's own texts (website chunks, FAQ answers, the reception tables)."""
    counts = Counter()
    for text in texts:
        counts.update(re.findall(r'[а-яөүё]+', str(text or '').casefold()))
    return counts
