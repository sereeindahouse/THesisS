"""Expected answer type: does the shown text hold the kind of value the question asks for?

A question such as «Hub Center өдөр бүр хэдэн цаг хүртэл нээлттэй вэ?» asks for a clock
time. A passage that describes Hub Center («10 давхарт байрлах 593.11 м² талбай») shares the
topic words and contains digits, so the earlier any-digit screen accepted it as an answer.
Classic question answering checks the expected answer type of a question before accepting
a candidate (Li & Roth 2002; Hovy et al. 2001), and topically related distractors are the
hardest case (Jia & Liang 2017; Shi et al. 2023). Grounding: papers/40-answer-type-guard-20261117.mn.md.

Closed, transparent patterns only — no model. A question type that is not recognised keeps
the earlier screen (any digit for хэзээ/хэд questions, nothing otherwise). Passing proves
only that a value of the asked type is present, not that it is the right value.
"""
from functools import lru_cache
import re

from mongolian_morphology import light_stem

NUMERIC_QUESTION = re.compile(r'(?<!\w)(?:хэзээ|хэдэн|хэд|хэдэд|хэдний|хэддүгээр)(?!\w)')
_NUMERAL_WORDS = (r'нэг|хоёр|гурав|гурван|дөрөв|дөрвөн|тав|таван|зургаа|зургаан|долоо|долоон|найм|найман|'
                  r'ес|есөн|арав|арван|хорь|хорин|гуч|гучин|дөч|дөчин|тавь|тавин|зуу|зуун|мянга|мянган')
_NUMBER = r'(?:\d+(?:[.,]\d+)*\+?|(?:' + _NUMERAL_WORDS + r'))'
# Units written in more than one way are compared in one form.
_UNIT_FORMS = ((re.compile(r'квадрат\s+метр\w*|кв\.?\s*м(?:етр\w*)?(?!\w)|(?<!\w)м2(?!\w)', re.I), 'м²'),
               (re.compile(r'%'), ' хувь'), (re.compile(r'₮'), ' төгрөг'))
_ORDINAL_WORDS = r'нэг|хоёр|гурав|дөрөв|тав|зургаа|долоо|найм|ес|арав'
_RANK_VALUE = re.compile(r'\d{1,3}\s*-?\s*(?:р|дугаар|дүгээр)\s+байр|(?:' + _ORDINAL_WORDS + r')(?:дугаар|дүгээр)\s+байр|'
                         r'(?:тэргүүн|тусгай|шилдэг)\s+байр|(?:алт|мөнгө|хүрэл)\w*\s+медаль|аварга|'
                         r'(?<!\w)[ivx]+\s+зэрэг\w*\s+(?:диплом|шагнал)', re.I)
_FLOOR_VALUE = re.compile(r'\d{1,2}\s*-?\s*(?:р|дугаар|дүгээр)?\s*давхар', re.I)
_TIME_VALUE = re.compile(r'(?<!\d)\d{1,2}[:.]\d{2}(?!\d)|(?<!\d)\d{1,2}\s*(?:-\s*\d{1,2}\s*)?цаг', re.I)
# A month.day pair needs a two-digit day; «2.5 сая» (a decimal) and «2-3 оюутан» (a range) are no dates.
_DATE_VALUE = re.compile(
    r'(?<!\d)(?:19|20)\d{2}(?!\d)|'
    r'(?<![\d.,])(?:0?[1-9]|1[0-2])[./](?:0[1-9]|[12]\d|3[01])(?![\d.,])(?!\s*(?:сая|мянга|тэрбум|хувь|төгрөг|м²))|'
    r'(?<!\d)\d{1,2}\s*-?\s*(?:р|дугаар|дүгээр)?\s*сар|(?:' + _ORDINAL_WORDS + r'|арван\s*нэг|арван\s*хоёр)'
    r'(?:дугаар|дүгээр)\s+сар|(?<!\w)(?:даваа|мягмар|лхагва|пүрэв|баасан|бямба|ням)(?:\s+гараг\w*)?(?!\w)|'
    r'(?<!\w)(?:хавар|намар|өвөл|зун)\w*|\d+\s*(?:хоног|долоо\s+хоног|сар|жил)\w*\s+(?:дотор|дараа|өмнө|хойш)', re.I)
_STOP_AFTER_COUNT = frozenset('вэ бэ уу үү юу юм нийт ба болон эсвэл'.split())
_ORDINAL_MARKERS = frozenset('р дугаар дүгээр дахь дэх дахи дэхь дэхи'.split())


_NUMERAL_DIGITS = {'нэг': '1', 'хоёр': '2', 'гурав': '3', 'гурван': '3', 'дөрөв': '4', 'дөрвөн': '4',
                   'тав': '5', 'таван': '5', 'зургаа': '6', 'зургаан': '6', 'долоо': '7', 'долоон': '7',
                   'найм': '8', 'найман': '8', 'ес': '9', 'есөн': '9', 'арав': '10', 'арван': '10'}
_NUMERAL_WORD = re.compile(r'(?<!\w)(' + '|'.join(sorted(_NUMERAL_DIGITS, key=len, reverse=True)) + r')(?!\w)')
# «арван нэг(эн)» is 11, not «10 1»: a tens word followed by a unit word is one number.
_TENS = {'арван': 10, 'хорин': 20, 'гучин': 30, 'дөчин': 40, 'тавин': 50}
_UNITS = dict({word: int(digit) for word, digit in _NUMERAL_DIGITS.items() if int(digit) < 10}, нэгэн=1)
_COMPOUND_NUMERAL = re.compile(r'(?<!\w)(' + '|'.join(_TENS) + r')\s+('
                               + '|'.join(sorted(_UNITS, key=len, reverse=True)) + r')(?!\w)')
_TENS_WORD = re.compile(r'(?<!\w)(хорин|гучин|дөчин|тавин)(?!\w)')


def normalise_units(text, numerals=False):
    """One written form per unit (and, for word matching, per small number: «хоёр» = «2»)."""
    text = text.casefold()
    for pattern, form in _UNIT_FORMS:
        text = pattern.sub(form, text)
    if numerals:
        text = _COMPOUND_NUMERAL.sub(lambda match: str(_TENS[match.group(1)] + _UNITS[match.group(2)]), text)
        text = _TENS_WORD.sub(lambda match: str(_TENS[match.group(1)]), text)
        text = _NUMERAL_WORD.sub(lambda match: _NUMERAL_DIGITS[match.group(1)], text)
    return text


@lru_cache(maxsize=1024)
def expected_value(query):
    """('time'|'rank'|'floor'|'date'|'count'|'number', count-noun stems) or None."""
    q = normalise_units(query)
    when = re.search(r'(?<!\w)хэзээ(?!\w)(.{0,40})', q)
    # «хэзээ нээгддэг / ажилладаг» asks for opening hours; «хэзээ нээгдсэн», «хэзээ хамтран
    # ажиллаж эхэлсэн» (a past or starting event) asks for a date. «хаана» (where) is not «хаадаг».
    opening_hours = bool(when and re.search(r'нээ|хаа(?:г|л|д)|ажилла', when.group(1))
                         and not re.search(r'эхэл|эхлэ|\w(?:сан|сэн|сон|сөн)(?!\w)', when.group(1)))
    if opening_hours or re.search(r'хэдэн\s+цаг(?:т|аас|ийн|\s+хүртэл|\s+болтол)|хэдээс\s+хэд|хэд\s+хүртэл', q):
        return 'time', ()
    # «байр» is also a building or a dormitory («хэдэн байртай», «ямар байранд»): a ranking
    # question names the achievement («ямар байр эзэлсэн», «хэддүгээр байрт орсон»).
    if re.search(r'(?:хэддүгээр|ямар|хэдэн)\s+байр(?:ыг|т|анд)?\s+(?:\w+\s+){0,2}?'
                 r'(?:эзэл|ор(?:сон|дог|ов|жээ)|ав(?:сан|ч|дог)|шалгар)', q):
        return 'rank', ()
    if re.search(r'хэддүгээр\s+давхар|хэдэн\s+давхар', q):
        return 'floor', ()
    if re.search(r'(?<!\w)хэзээ(?!\w)|хэдний\s+өдөр|хэдэн\s+сарын|ямар\s+өдөр|хэдэн\s+он(?:д|ы)?(?!\w)', q):
        return 'date', ()
    match = re.search(r'(?<!\w)хэдэн\s+([^?!.,;]+)', q)
    if match:
        # Only the counted noun right after «хэдэн»; later verbs («байна») would match anything.
        words = [word for word in re.findall(r'[\w²]+', match.group(1)) if word not in _STOP_AFTER_COUNT][:1]
        stems = tuple(light_stem(word) for word in words if len(word) >= 2)
        if stems:
            return 'count', stems
    if NUMERIC_QUESTION.search(q):
        return 'number', ()
    return None


def _count_supported(stems, text):
    # Trailing punctuation is not part of a number («25,», «1200.»).
    tokens = [(match.group().rstrip('.,'), match.end()) for match in re.finditer(r'[\w²+.,]+', text)]

    def counted(token):
        stem = light_stem(token.strip('.,+'))
        return any(stem == wanted or (min(len(stem), len(wanted)) >= 3
                                      and (stem.startswith(wanted) or wanted.startswith(stem)))
                   for wanted in stems)

    def amount(token):
        return bool(re.fullmatch(_NUMBER, token)) and not re.fullmatch(r'(?:19|20)\d{2}', token)

    for index, (token, end) in enumerate(tokens):
        # An ordinal («3-р байр», «6 дахь удаагаа») ranks or orders; it does not count anything.
        ordinal = index + 1 < len(tokens) and tokens[index + 1][0] in _ORDINAL_MARKERS
        if (re.fullmatch(_NUMBER, token) and not ordinal
                and any(counted(following) for following, _ in tokens[index + 1:index + 4])):
            return True
        # A table or list line names the counted noun first: «Оюутны тоо: 1200», «Оюутан: 1200».
        if counted(token) and index + 1 < len(tokens):
            following = tokens[index + 1][0]
            if following.startswith('тоо') and index + 2 < len(tokens) and amount(tokens[index + 2][0]):
                return True
            if re.match(r'\s*[:：]', text[end:]) and amount(following):
                return True
    return False


def value_supported(query, text):
    """True when text holds a value of the type the question asks for (or no type is asked)."""
    expected = expected_value(query)
    if expected is None:
        return True
    kind, stems = expected
    shown = normalise_units(text)
    if kind == 'time':
        return bool(_TIME_VALUE.search(shown))
    if kind == 'rank':
        return bool(_RANK_VALUE.search(shown))
    if kind == 'floor':
        return bool(_FLOOR_VALUE.search(shown))
    if kind == 'date':
        return bool(_DATE_VALUE.search(shown))
    if kind == 'count':
        return _count_supported(stems, shown)
    return bool(re.search(r'\d', shown))


VALUE_LABELS = {'time': 'цаг', 'rank': 'эзэлсэн байр', 'floor': 'давхар', 'date': 'огноо, хугацаа',
                'count': 'тоо', 'number': 'тоон утга'}
# Words that name the asked value itself, not the topic (excluded from the anchor terms).
VALUE_WORDS = {'time': ('цаг',), 'rank': ('байр',), 'floor': ('давхар',), 'date': ('сар', 'өдөр')}
