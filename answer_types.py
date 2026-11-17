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
# A floor in digits («3-р давхар») or in words («гуравдугаар давхар»).
_FLOOR = (r'\d{1,2}\s*-?\s*(?:р|дугаар|дүгээр)?\s*давхар|'
          r'(?:' + _ORDINAL_WORDS + r'|арван\s*нэг|арван\s*хоёр)(?:дугаар|дүгээр)\s+давхар')
# A place inside the campus: a room, a floor, a building or block («2-р байрны А корпус»),
# or a street address (review 11/17 (5)). «4-р байр … эзэллээ» is a contest ranking, not
# building 4 (round 9: «Хүний нөөц хаана вэ?» was answered with a speech-contest result).
_PLACE_VALUE = re.compile(r'(?<!\d)\d{2,4}\s*(?:тоот|-?р\s+өрөө|өрөө)|(?:өрөө|тоот)\s*[:№#]?\s*\d{2,4}(?!\d)|'
                          r'(?<!\w)(?:корпус|блок)\w*|\d{1,2}\s*-?\s*(?:р|дугаар|дүгээр)\s+байр(?:ны|анд|нд)?(?!\w)'
                          r'(?!(?:\s+\w+){0,3}\s+эзэл(?:сэн|лээ|жээ|ж|в|сний)(?!\w))|'
                          r'\d{1,2}\s*-?\s*(?:р|дугаар|дүгээр)?\s*хороо|гудамж\w*|' + _FLOOR, re.I)
_FLOOR_VALUE = re.compile(_FLOOR, re.I)
_TIME_VALUE = re.compile(r'(?<!\d)\d{1,2}[:.]\d{2}(?!\d)|(?<!\d)\d{1,2}\s*(?:-\s*\d{1,2}\s*)?цаг', re.I)
# A month.day pair needs a two-digit day; «2.5 сая» (a decimal) and «2-3 оюутан» (a range) are no dates.
_DATE_VALUE = re.compile(
    r'(?<!\d)(?:19|20)\d{2}(?!\d)|'
    r'(?<![\d.,])(?:0?[1-9]|1[0-2])[./](?:0[1-9]|[12]\d|3[01])(?![\d.,])(?!\s*(?:сая|мянга|тэрбум|хувь|төгрөг|м²))|'
    r'(?<!\d)\d{1,2}\s*-?\s*(?:р|дугаар|дүгээр)?\s*сар|(?:' + _ORDINAL_WORDS + r'|арван\s*нэг|арван\s*хоёр)'
    r'(?:дугаар|дүгээр)\s+сар|(?<!\w)(?:даваа|мягмар|лхагва|пүрэв|баасан|бямба|ням)(?:\s+гараг\w*)?(?!\w)|'
    r'(?<!\w)(?:хавар|намар|өвөл|зун)\w*|\d+\s*(?:хоног|долоо\s+хоног|сар|жил)\w*\s+(?:дотор|дараа|өмнө|хойш)', re.I)
_SEASON = re.compile(r'(?<!\w)(?:хавар|намар|өвөл|зун)\w*', re.I)
_YEAR = r'(?<!\d)(?:19|20)\d{2}(?!\d)'
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
    """('time'|'rank'|'floor'|'place'|'date'|'name'|'count'|'number', noun stems) or None."""
    q = normalise_units(query)
    # «Robocon чиглэлийн клуб ямар нэртэй вэ?», «Клубийн нэр юу вэ?» ask for a proper name of
    # the named thing (W04-A14 «NewRobo клуб»); its stem is where the name must stand.
    named = re.search(r'([^\W\d_]{2,})\s+(?:ямар\s+нэр(?:тэй|ээр)|нэр(?:\s+нь)?\s+(?:юу|хэн))(?!\w)', q, re.I)
    if named:
        return 'name', (light_stem(named.group(1).casefold()),)
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
    # «Хүний нөөцийн алба хаана байдаг вэ?»: where an office or room is, inside the building
    # (a room number or a floor), not «Японд хаана дадлага хийдэг» (11/17 (5)). «Хүний нөөц хаана
    # вэ?» names the office without «алба» (round 9: a Japanese speech-contest page was shown).
    if re.search(r'(?:алба|өрөө|төв|танхим|кабинет|лаборатори|номын\s+сан|нөөц|нягтлан(?:\s+бодогч)?|оффис)\w*'
                 r'\s+хаана(?!\w)', q):
        return 'place', ()
    # «хэдий хугацаанд» (over what period), «хэдийд» (when), «хэдийнээс» (since when) ask for a date.
    if re.search(r'(?<!\w)хэзээ(?!\w)|хэдний\s+өдөр|хэдэн\s+сарын|ямар\s+өдөр|хэдэн\s+он(?:д|ы)?(?!\w)|'
                 r'(?<!\w)хэдий\s+хугаца|(?<!\w)хэдийд(?!\w)|(?<!\w)хэдийнээс(?!\w)', q):
        return 'date', ()
    # «Оюутны зөвлөлийн дарга хэн бэ?»: a person's name next to the post (round 5); the posts the
    # staff table holds are answered before this, by the reception lookup.
    who = re.search(r'([^\W\d_]{2,})\s+(?:нь\s+)?хэн\s+(?:бэ|вэ)[?!. ]*$', q)
    if who and who.group(1) not in _PRONOUNS:
        noun = who.group(1)
        if noun in ('хүн', 'хүмүүс'):
            # «Сургуулийг үүсгэсэн хүн хэн бэ?»: the deed names the person, not «хүн».
            before = re.findall(r'[^\W\d_]{2,}', q[:who.start(1)])
            return ('person', (light_stem(before[-1])[:4],)) if before else None
        return 'person', (light_stem(noun),)
    deed = re.search(r'(?<!\w)хэн\s+([^\W\d_]{3,})', q)
    if deed and not re.fullmatch(r'бэ|вэ|нь', deed.group(1)):
        # «Сургуулийг хэн үүсгэн байгуулсан бэ?»: a name in the sentence of the deed (review, round 5).
        return 'person', (light_stem(deed.group(1))[:4],)
    match = re.search(r'(?<!\w)хэдэн\s+([^?!.,;]+)', q)
    if match:
        # Only the counted noun right after «хэдэн»; later verbs («байна») would match anything.
        words = [word for word in re.findall(r'[\w²]+', match.group(1)) if word not in _STOP_AFTER_COUNT][:1]
        if words and words[0] in _CLASSIFIERS:
            # «хэдэн ширхэг компьютер» counts the noun after the classifier; «Лаборатори хэдэн ширхэг
            # байдаг вэ?» the noun before «хэдэн» (round 5; particles such as «нь» are skipped).
            after = [word for word in re.findall(r'[\w²]+', match.group(1))[1:] if word not in _STOP_AFTER_COUNT]
            before = [word for word in re.findall(r'[\w²]+', q[:match.start()])
                      if word not in _STOP_AFTER_COUNT and word != 'нь']
            noun = after[:1] if after and not _VERB_END.search(after[0]) else before[-1:]
            words = noun
        stems = tuple(light_stem(word) for word in words if len(word) >= 2)
        if stems:
            return 'count', stems
    if NUMERIC_QUESTION.search(q):
        return 'number', ()
    return None


_CLASSIFIERS = frozenset(('ширхэг', 'ш'))
_PRONOUNS = frozenset('та чи би тэр энэ тэд бид та нар'.split())
_VERB_END = re.compile(r'(?:даг|дэг|дог|дөг|на|нэ|но|нө|сан|сэн|сон|сөн|ах|эх|ох|өх|ж|ч)$')
# «Б.Тэмүүлэн», «Б.ТЭМҮҮЛЭН»: an initial and a name.
_PERSON_NAME = re.compile(r'(?<![\w.])[А-ЯӨҮЁ]\.\s?[А-ЯӨҮЁ][А-ЯӨҮЁа-яөүё-]{2,}')
# The website's staff list: «Билгүүн (Тэнхимийн эрхлэгч)» — a name followed by its post in brackets.
_LISTED_NAME = re.compile(r'(?<![\w.])([А-ЯӨҮЁ][а-яөүё-]{2,})\s*\(')


def _person_supported(query, stems, text):
    """A person's name («Б.Батболд») next to the asked post: in the same line within three words,
    or as the whole line just before or after it («Т.Оюунжаргал» above «…Захирал»)."""
    def listed(near):
        # «Захирал (Director)» is the post with a gloss, not a name.
        return any(not any(name.casefold().startswith(stem) for stem in stems)
                   for name in _LISTED_NAME.findall(near))

    deed = len(stems) == 1 and len(stems[0]) == 4 and not re.search(r'хэн\s+(?:бэ|вэ)[?!. ]*$', query.casefold())
    if deed:
        # «… хэн үүсгэн байгуулсан бэ?»: the name stands in the same sentence as the deed.
        return any(any(word.casefold().startswith(stems[0]) for word in re.findall(r'\w+', sentence))
                   and _PERSON_NAME.search(sentence) for sentence in re.split(r'(?<=[.!?])\s+|\n', text))
    lines = text.splitlines()
    for number, line in enumerate(lines):
        tokens = list(re.finditer(r'[\w.-]+', line))
        for index, token in enumerate(tokens):
            if not any(token.group().casefold().startswith(stem) for stem in stems):
                continue
            near = line[tokens[max(0, index - 3)].start():tokens[min(len(tokens) - 1, index + 3)].end()]
            if _PERSON_NAME.search(near) or listed(near):
                return True
            for other in (lines[number - 1] if number else '', lines[number + 1] if number + 1 < len(lines) else ''):
                if _PERSON_NAME.fullmatch(other.strip()):
                    return True
    return False


_PAST_VERB = re.compile(r'\w(?:сан|сэн|сон|сөн|жээ|чээ|лаа|лээ|лоо|лөө)$')


def _stative_count(query):
    """«Механик тэнхим хэдэн оюутантай вэ?», «… хэдэн багш байдаг вэ?»: nothing but particles or
    «байдаг/байна» after the counted noun, so the question asks how many there are."""
    match = re.search(r'(?<!\w)хэдэн\s+([^?!.,;]+)', normalise_units(query))
    words = re.findall(r'\w+', match.group(1)) if match else []
    return bool(words) and all(word in _STOP_AFTER_COUNT or re.fullmatch(r'бай(?:даг|на|гаа)|бий', word)
                               for word in words[1:])


def _count_supported(stems, text, strict=False, stative=False):
    """A number counting the asked noun. ``strict`` (a question with no anchor of its own,
    «Сургууль хэдэн байртай вэ?») takes only a number right before the noun, not a range
    («1-3 байр»), since nothing else ties the number to the question (11/17 (5)). ``stative``
    (_stative_count): an event's count in the past tense («17 оюутан амжилттай хамгаалсан»)
    does not say how many there are (round 4, 11/17)."""
    # Trailing punctuation is not part of a number («25,», «1200.»).
    matches = list(re.finditer(r'[\w²+.,]+', text))
    tokens = [(match.group().rstrip('.,'), match.end()) for match in matches]

    def in_range(index):
        dash = r'\s*[-–—]\s*'
        before = index > 0 and re.fullmatch(_NUMBER, tokens[index - 1][0]) and re.fullmatch(
            dash, text[matches[index - 1].end():matches[index].start()])
        after = index + 1 < len(tokens) and re.fullmatch(_NUMBER, tokens[index + 1][0]) and re.fullmatch(
            dash, text[matches[index].end():matches[index + 1].start()])
        return bool(before or after)

    def counted(token):
        stem = light_stem(token.strip('.,+'))
        return any(stem == wanted or (min(len(stem), len(wanted)) >= 3
                                      and (stem.startswith(wanted) or wanted.startswith(stem)))
                   for wanted in stems)

    def amount(token):
        return bool(re.fullmatch(_NUMBER, token)) and not re.fullmatch(r'(?:19|20)\d{2}', token)

    years_asked = any(stem.startswith('он') for stem in stems)

    for index, (token, end) in enumerate(tokens):
        # An ordinal («3-р байр», «6 дахь удаагаа») ranks or orders; it does not count anything.
        ordinal = index + 1 < len(tokens) and tokens[index + 1][0] in _ORDINAL_MARKERS
        # «2025 онд 17 оюутан»: a year before «он…» dates the count; it counts nothing itself,
        # unless the year is what is asked («Koha-г хэдэн оноос ашиглаж байна?» -> «2016 оноос»).
        ordinal = ordinal or bool(not years_asked and re.fullmatch(r'(?:19|20)\d{2}', token)
                                  and index + 1 < len(tokens) and tokens[index + 1][0].startswith('он'))
        window = tokens[index + 1:index + (3 if strict else 4)]
        if (re.fullmatch(_NUMBER, token) and not ordinal and not (strict and in_range(index))
                and any(counted(following) for following, _ in window)
                and not (stative and any(_PAST_VERB.search(word) for word, _ in tokens[index + 1:index + 5]))):
            return True
        # A table or list line names the counted noun first: «Оюутны тоо: 1200», «Оюутан: 1200».
        if counted(token) and index + 1 < len(tokens):
            following = tokens[index + 1][0]
            if following.startswith('тоо') and index + 2 < len(tokens) and amount(tokens[index + 2][0]):
                return True
            if re.match(r'\s*[:：]', text[end:]) and amount(following):
                return True
    return False


def value_supported(query, text, strict=False):
    """True when text holds a value of the type the question asks for (or no type is asked).
    ``strict``: the question has no anchor term of its own (see _count_supported)."""
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
    if kind == 'place':
        return bool(_PLACE_VALUE.search(shown))
    if kind == 'date':
        # «2026 оны элсэлтийн бүртгэл хэдий хугацаанд явагдсан бэ?»: the named year is not its own
        # answer, and a season («намар») is too vague for a dated event or a period (11/17 (5)).
        # A dated heading line («2026 оны есдүгээр сарын 11») at the top of an article says when it
        # was published, not the date asked about («Элсэлт хэзээ эхлэх вэ?»), 11/17 (5). Only a
        # date-only line among the first two, not after a label («Бүртгэл эхлэх огноо:»).
        from evidence_contract import _PUBLICATION_DATE
        lines = shown.splitlines()
        shown = '\n'.join(line for index, line in enumerate(lines)
                          if not (index < 2 and _PUBLICATION_DATE.fullmatch(line.strip())
                                  and not (index and lines[index - 1].rstrip().endswith(':'))))
        asked_years = re.findall(_YEAR, query)
        if asked_years or re.search(r'хэдий\s+хугаца', normalise_units(query)):
            for year in asked_years:
                shown = re.sub(r'(?<!\d)' + year + r'(?!\d)', ' ', shown)
            shown = _SEASON.sub(' ', shown)
        return bool(_DATE_VALUE.search(shown))
    if kind == 'name':
        # The capital of a name is the point: read the text as written, not case-folded.
        return _name_supported(query, stems, text)
    if kind == 'person':
        return _person_supported(query, stems, text)
    if kind == 'count':
        return _count_supported(stems, shown, strict=strict, stative=_stative_count(query))
    return bool(re.search(r'\d', shown))


_NAME_TOKENS = re.compile(r'«[^»\n]{2,40}»|"[^"\n]{2,40}"|“[^”\n]{2,40}”|[\w-]+')
# A Latin name carries a capital or a digit («NewRobo», «IT», «Robo2026»), not «www».
_LATIN_NAME = re.compile(r'(?=[A-Za-z0-9-]*[A-Z0-9])[A-Za-z][A-Za-z0-9-]{1,}')
_CAPITAL_NAME = re.compile(r'[А-ЯӨҮЁ][а-яөүё-]{2,}')


def _name_supported(query, stems, text):
    """A proper name the question does not already hold — a Latin word, a quoted phrase, or a
    capitalised word inside a sentence — within two words of the named thing: «Robocon
    чиглэлийн NewRobo клуб» names the club, «Үүнд Robocon клуб» only repeats the question."""
    asked = {word.casefold() for word in re.findall(r'\w+', query)}
    for line in text.splitlines():
        tokens = list(_NAME_TOKENS.finditer(line))
        for index, token in enumerate(tokens):
            if not any(token.group().casefold().startswith(stem) for stem in stems):
                continue
            for other in tokens[max(0, index - 2):index] + tokens[index + 1:index + 3]:
                word = other.group()
                if word.strip('«»"“”').casefold() in asked:
                    continue
                if word[0] in '«"“' or _LATIN_NAME.fullmatch(word):
                    return True
                # A capital after a sentence end, a bullet or a label starts the line, not a name.
                before = line[:other.start()]
                if _CAPITAL_NAME.fullmatch(word) and before.strip() and not re.search(r'[.!?•:;]\s*$', before):
                    return True
    return False


VALUE_LABELS = {'time': 'цаг', 'rank': 'эзэлсэн байр', 'floor': 'давхар', 'place': 'байршил (өрөө, давхар)',
                'date': 'огноо, хугацаа', 'name': 'нэр', 'person': 'хүний нэр',
                'count': 'тоо', 'number': 'тоон утга'}
# Words that name the asked value itself, not the topic (excluded from the anchor terms).
VALUE_WORDS = {'time': ('цаг',), 'rank': ('байр',), 'floor': ('давхар',), 'place': ('өрөө', 'давхар', 'байрла'),
               'date': ('сар', 'өдөр', 'хугаца', 'огноо'), 'name': ('нэр',), 'person': ('хэн',),
               'count': ('ширхэг',)}
