"""Configured source selection without an LLM; Gemma code stays available.

bounded_lexical_selection extends the registered bm25_bounded_complete_subset
rule from the private 2026-10-27 comparison with two 2026-11-01 additions: units
that literally hold a requested field join the candidates, and a subset must
also cover the question's key terms. It reads no references. All other guards
and rendering stay in common_render. Passing is not proof of correctness: the
key-term check is a transparent literal screen tuned on observed questions.

2026-11-03: ``single_unit_coverage`` (config, off by default) asks that one
selected unit alone covers the key terms, instead of 1-3 units summed
(papers/15-rag-diagnosis-20261101.mn.md, stage 2). Same thresholds; it is
measured on the locked W04 set before anyone turns it on.
"""
from __future__ import annotations

from functools import lru_cache
from itertools import combinations
import json
from pathlib import Path
import re
import time
import unicodedata
from urllib.parse import urlsplit

from answer_types import same_family, word_family

RULE_SELECTOR = 'bm25_bounded_complete_subset'
GEMMA_SELECTOR = 'gemma_production_selector'
CONFIG_PATH = 'config/answer-selection.json'
SAFE_DEFAULT = dict(selector=RULE_SELECTOR, local_llm_enabled=False, single_unit_coverage=False,
                    typed_value_check=True)
# Words that shape a request or name the school itself, not what is being asked.
REQUEST_WORDS = frozenset('''хэлнэ хэлээрэй хэлж хэлээд нэрлэж нэрлээд нэрлээрэй нэрлэнэ
    тайлбарлана тайлбарлаач тайлбарлаарай ялгаж ялгаад харьцуулна харьцуулж өгнө аль хамт
    ажилладаг сургууль коллеж хэн хэдэн хэддүгээр үнэхээр хүртэл байдаг болдог тавьдаг
    өгдөг авдаг хийдэг ордог байх ёстой гараг гарагт гарагийн нийт'''.split())
# The same kinds of words as the search index writes them (it cuts endings: «хэддүгээр» → «хэддүг»),
# and the school's short names (11/17 (5)).
QUESTION_TERMS = frozenset('хэддүг хэдий хэдийд хэдийн шмтк nmct'.split())
# «өнөөдрийг / одоог хүртэл» (to date) frames a cumulative figure; removed as a phrase, since
# «одоогийн» (current: «одоогийн дарга») cuts to the same «одоог» and must stay a topic word.
TO_DATE = re.compile(r'(?<!\w)(?:өнөөдрийг|өнөөг|одоог)\s+хүртэл(?!\w)', re.I)
# «хаанаас», «хаашаа», «хаагуур» (from/to/through where) are question words; the index cuts
# «хаанаас» to «хаан», which matched «Хаан банк» (round 9: «Тодорхойлолт хаанаас авах вэ?» was
# answered with the registration fee). Their cut forms leave the terms only when the question has
# one, and after the final verb is dropped, so «… үнэмлэх хаанаас авах вэ?» keeps «үнэмлэх».
WHERE_WORD = re.compile(r'(?<!\w)хаа(?:наас|шаа|гуур|нахын|наа)(?!\w)', re.I)
WHERE_TERMS = frozenset(('хаан', 'хаашаа', 'хаагуур', 'хаанах', 'хаанаа'))
# «Тодорхойлолт хаанаас авах вэ?», «Хичээлийн хуваарь хаанаас харах вэ?» ask where a paper is issued
# or a list is shown (round 9): a text that only names it («Сургуулийн тодорхойлолтоор … элссэн», an
# exam page's «хичээл … харагдана» beside a «Хугацааны хуваарь» heading) does not answer.
# Group 1: a paper to get; group 2: a list to see; group 3 (round 17): a paper to hand in («Багшаар ажилд
# орох хүсэлт хаана өгөх вэ?» was answered with a project visit's «амжилт хүслээ»). Each needs its own
# verb in the text: «Хуудас 1 Томоор үзэх →» (a viewer's button) does not say where a grade sheet is
# issued (round 10).
OBTAIN_QUESTION = re.compile(r'(?<!\w)хаа(?:наас|на)\s+(?:\w+\s+)?(?:(ав(?:ах|на|дуулах|ч\s+болох)|гаргуул\w*)|'
                             r'(хар(?:ах|ж\s+болох)|үз(?:эх|ж\s+болох)|ол(?:ох|ж\s+болох))|'
                             r'(өг(?:өх|ч\s+болох)|гарга(?:х|ж\s+болох)|илгээ(?:х|ж\s+болох)|бөглө(?:х|ж\s+болох)))(?!\w)')
# Round 17: «хэрхэн/яаж авах» a paper or an account asks the same («Тодорхойлолт яаж авах вэ?» showed an
# admission rule naming a foreign school's certificate; «Оюутны цахим хаяг хэрхэн авах вэ?» the school's
# postal address). Not a scholarship or a discount, whose conditions answer how to get it (review).
PAPER_HOW = re.compile(r'(?<!\w)(?:тодорхойлолт|хуудас|үнэмлэх|карт|гэрчилгээ|диплом|лавлагаа|маягт|анкет|гэрээ|'
                       r'өргөдөл|хуулбар|хаяг)\w*\s+(?:хэрхэн|яаж)\s+(?:ав(?:ах|на|ч\s+болох)|гаргуул\w*)(?!\w)')
ISSUE_VERB = re.compile(r'(?<!\w)(?:олго\w*|ав(?:на|ах|даг|ч\s+болно|ч\s+болох)|гаргаж\s+өг\w*|гаргуул\w*|'
                        r'захиал\w*)(?!\w)')
# «хүлээн авна» (an office accepts), not a story's «багийг хүлээн авч» (welcomed a team).
SUBMIT_VERB = re.compile(r'(?<!\w)(?:өг(?:нө|өх|дөг|ч\s+болно)|гарга(?:на|х|даг|ж\s+болно)|илгээ\w*|ирүүл\w*|бөглө\w*|'
                         r'хүлээн\s+ав(?:на|даг|ах))(?!\w)')
SEE_VERB = re.compile(r'(?<!\w)(?:хар(?:на|ах|ж\s+болно|агдана)|үз(?:нэ|эх|ж\s+болно)|ол(?:но|ох|ж\s+болно))(?!\w)')
# Pages about the school as a whole (not a department, programme, event or news item).
SCHOOL_WIDE_PATH = re.compile(r'^/(?:about(?:/.*)?|contact|elselt|elseltiin-juram/.*|student)?/?$')
SCHOOL_NAME = re.compile(r'(?<!\w)шинэ\s+монгол\s+технологийн\s+коллеж\w*', re.I)
LIGHT_VERB = re.compile(r'(?<!\w)(\w{3,}(?:[аэоөиу]ж|[^г\W]ч))\s+ор(?:ж|ох|сон|дог|но)?(?!\w)')
FINAL_PREDICATE = re.compile(r'(?:даг|дэг|дог|дөг|на|нэ|но|нө|сан|сэн|сон|сөн|ах|эх|ох|өх)$')
NUMERIC_QUESTION = re.compile(r'(?<!\w)(?:хэзээ|хэдэн|хэд|хэдэд|хэдний|хэддүгээр)(?!\w)')
SHORT_QUESTION_TERMS = 6
SHORT_QUESTION_COVERAGE = 0.85
LONG_QUESTION_COVERAGE = 0.3


def _stems(text):
    """The index's terms, one word at a time; a word whose index stem belongs to another family keeps
    its own form: the index joins «хаягдлын» (waste) with «хаяг» (an address), round 16."""
    from website_retrieval import search_terms
    return [stem if word_family(stem) in (None, word_family(word)) else word.casefold()
            for word in re.findall(r'\w+', unicodedata.normalize('NFC', text)) for stem in search_terms(word)]


@lru_cache(maxsize=4096)
def _words(text):
    # One spelling per unit and small number («квадрат метр» = «м²», «хоёр» = «2») before comparing.
    # Cached: the same claims are checked for many candidate subsets of one answer.
    from answer_types import normalise_units
    text = normalise_units(text, numerals=True)
    return frozenset(re.findall(r'\w+', text)) | frozenset(_stems(text))


_CONVERB = re.compile(r'\w{3,}[жч]')


def _has_term(term, words, verb_stem=False):
    # Shared prefixes stand in for Mongolian suffixes. With ``verb_stem`` (accepting a topic,
    # round 8) a converb needs its whole stem: with three letters «хувааж» (dividing) covered
    # «Хувийн» (personal), and «Төлбөрөө хувааж төлж болох уу?» was answered by a registration step.
    # Words of another family never match (answer_types.same_family, round 16).
    size = max(3, len(term) - 3)
    if verb_stem and _CONVERB.fullmatch(term):
        size = max(size, len(term) - 1)
    return any(word.startswith(term[:size]) and same_family(term, word) for word in words)


# Mongolian drops a stem's last short vowel before a vowel suffix (ажил → ажлаа, өдөр → өдрийн).
_FLEETING_VOWEL = re.compile(r'(?<=[^аэиоуөүяеёюы])[аэиоуөү](?=[^аэиоуөүяеёюйы]$)')


@lru_cache(maxsize=4096)
def _anchor_words(text):
    """_words plus each word without its fleeting vowel, so «ажлаа» finds «ажил».
    Used only for the anchor of the typed check; topic coverage keeps _words."""
    words = _words(text)
    return words | frozenset(_FLEETING_VOWEL.sub('', word, count=1) for word in words)


@lru_cache(maxsize=1024)
def key_terms(query):
    # Cached and immutable: every candidate subset of one answer asks for the same query's terms.
    terms = _all_terms(query)
    # Mongolian ends a sentence with its verb; that word names no topic. Only the question's own last
    # word: «Оюутны байрны үнэ хэд вэ?» ends with «хэд», so «үнэ» (a price, ending like «-нэ») and the
    # «сан» of «Номын сан хаана вэ?» stay topics (round 17).
    predicate = question_predicate(query)
    if len(terms) > 1 and predicate and FINAL_PREDICATE.search(terms[-1]) and terms[-1] in _stems(predicate):
        terms = terms[:-1]
    return tuple(term for term in terms if term not in WHERE_TERMS) if WHERE_WORD.search(query) else terms


@lru_cache(maxsize=1024)
def _all_terms(query):
    from answer_types import normalise_units
    # «Шинэ Монгол Технологийн Коллежийн эрхэм зорилго» asks about the school's mission: the
    # full name names the school itself, like «сургууль», and is not a topic word.
    text = TO_DATE.sub(' ', SCHOOL_NAME.sub(' сургууль ', normalise_units(query, numerals=True)))
    # «2-р курст шилжиж орж болох уу?»: after a converb («шилжиж») «орох» only finishes the verb
    # («transfer in»), so the source's «2-р курс шилжин» need not repeat it (round 6).
    text = LIGHT_VERB.sub(r'\1', text)
    return tuple(term for term in dict.fromkeys(_stems(text))
                 if term not in REQUEST_WORDS and term not in QUESTION_TERMS)


def key_term_coverage(query, text):
    """Literal share of key terms in text; shared prefixes stand in for suffixes."""
    words = _words(text)
    terms = key_terms(query)
    if not terms:
        return 1.0
    return sum(_has_term(term, words) for term in terms) / len(terms)


def heading_match(query, text):
    """A line of text that is exactly the question's key terms, i.e. a section heading
    such as «Эрхэм зорилго» for «Сургуулийн эрхэм зорилго юу вэ?»."""
    from answer_types import normalise_units
    terms = set(key_terms(query))
    return bool(terms) and any(set(_stems(normalise_units(line, numerals=True))) == terms
                               for line in text.splitlines())


def focus_terms(query, units):
    """The question's rarest key terms among the candidate units: its anchor.

    An answer value counts only next to this anchor (cf. Ravichandran & Hovy 2002), so a
    unit about the topic cannot borrow a time or number from an unrelated unit.
    """
    from answer_types import VALUE_WORDS, expected_value
    kind, stems = expected_value(query) or (None, ())
    asked = set(stems) | set(VALUE_WORDS.get(kind, ()))
    # Years have their own guard; the words of the asked value («цаг», «байр») are not the topic.
    terms = [term for term in key_terms(query) if not re.search(r'\d', term)
             and not any(term.startswith(word) or word.startswith(term) for word in asked)]
    unit_words = [_anchor_words(unit['text']) for unit in units]
    frequency = {term: sum(_has_term(term, words) for words in unit_words) for term in terms}
    # A name in the question (Latin script, or capitalised after the first word) is its anchor.
    tokens = re.findall(r'\w+', query)
    names = [token.casefold() for index, token in enumerate(tokens)
             if re.search(r'[A-Za-z]', token) or (index and token[:1].isupper())]
    named = {term for term in terms if frequency[term] and any(_has_term(term, {name}) for name in names)}
    if named:
        return named
    # Otherwise the rarest key terms among the candidate units.
    present = [count for count in frequency.values() if count]
    return {term for term, count in frequency.items() if present and count == min(present)}


def value_missing(query, claims, typed=True, focus=(), contexts=None):
    """The question asks for a value (time, date, rank, floor, count) that no shown claim
    holds next to the question's anchor term. The anchor may stand in the claim itself or
    in its own page's title and heading (``contexts``), as a news title names its event."""
    claims = [claims] if isinstance(claims, str) else list(claims)
    contexts = list(contexts) if contexts is not None else [''] * len(claims)
    if not typed:
        # Earlier screen: a "when" or "how many" question needs a number in what it shows.
        return bool(NUMERIC_QUESTION.search(query.casefold()) and not re.search(r'\d', '\n'.join(claims)))
    from answer_types import expected_value, value_supported
    if expected_value(query) is None:
        return False
    years = set(re.findall(r'(?<!\d)(?:19|20)\d{2}(?!\d)', query))

    def other_year(claim):
        # «2025 оны зуны улиралд 3 оюутан» is not a value for a 2026 question.
        stated = set(re.findall(r'(?<!\d)(?:19|20)\d{2}(?!\d)', claim))
        return bool(years and stated and not stated & years)

    def school_scope(context):
        # With no anchor of its own («Хэдэн цагт ажилладаг вэ?», «Хэдэн оюутан суралцдаг вэ?») the
        # question is about the school itself: only a school-wide page (home, about, contact,
        # admissions, student life) may answer it, not a department's figure («Механик … 128
        # оюутан»), a programme's or an event's (an olympiad at 10:00), 11/17 (5).
        address = re.search(r'https?://\S+', context)
        if focus or not address:
            return True     # an anchored question, or no known page: the earlier behaviour
        return bool(SCHOOL_WIDE_PATH.match(urlsplit(address.group()).path or '/'))

    count = expected_value(query)[0] == 'count'
    predicate = question_predicate(query)

    def anchored(claim, context):
        if not focus:
            return True
        words = _anchor_words(claim)
        if any(_has_term(term, words) for term in focus):
            return True
        if not any(_has_term(term, _anchor_words(claim + '\n' + context)) for term in focus):
            return False
        # The anchor only in the page title is a weak tie for a count: «КУ-5 ангийн 3 оюутан …
        # дадлага хийсэн» on the computer-science page does not answer «… тэнхимд хэдэн оюутан
        # суралцдаг». Then the number's sentence must share the question's verb («суралцаж»).
        return not count or predicate is None or _has_term(predicate, words)

    # With no anchor term (focus) nothing else ties a number to the question: strict count.
    return not any(value_supported(query, claim, strict=not focus) and not other_year(claim)
                   and school_scope(context) and anchored(claim, context)
                   for claim, context in zip(claims, contexts))


@lru_cache(maxsize=1024)
def question_predicate(query):
    """The question's own verb («… хэдэн оюутан суралцдаг вэ?» → «суралцдаг»), or None."""
    words = [word for word in re.findall(r'\w+', query.casefold())
             if word not in ('вэ', 'бэ', 'уу', 'үү', 'юу', 'юм', 'бол', 'ве', 'бе', 'гэж')]
    return words[-1] if words and FINAL_PREDICATE.search(words[-1]) else None


@lru_cache(maxsize=1024)
def phrase_pair(query):
    """A two-word facility named in an existence question («Цайны газар байдаг уу?», «Дотуур байр
    бий юу?»), or None. Other questions («Элсэлтийн шалгалт хэзээ болох вэ?», «Сургуулийн имэйл
    хаяг юу вэ?») keep their words apart in a correct text (review 11/17 (5))."""
    terms = key_terms(query)
    # Round 14: also «Оюутны байр хаана байдаг вэ?» (a dormitory, answered with a contest's «1-р байр: …
    # оюутан» ranking): a where-question only for «… байр», whose other sense is a place in a contest
    # («Захирлын өрөө хаана вэ?» keeps «Захирал … Ажлын өрөө: 508», review).
    asked = query.casefold().strip()
    where = len(terms) == 2 and terms[1].startswith('байр') and re.search(
        r'хаана(?:\s+(?:байдаг|байрладаг|байна))?\s+(?:вэ|бэ)\s*[?？]?\s*$', asked)
    if len(terms) != 2 or not (where or re.search(r'(?:байдаг|бий|байгаа|байна)\s+(?:уу|үү|юу)\s*[?？]?\s*$', asked)):
        return None
    from answer_types import normalise_units
    words = re.findall(r'\w+', normalise_units(query, numerals=True))
    first = [i for i, word in enumerate(words) if _has_term(terms[0], {word})]
    second = [i for i, word in enumerate(words) if _has_term(terms[1], {word})]
    return terms if any(j - i == 1 for i in first for j in second) else None


_GENITIVE = re.compile(r'\w{2,}(?:ийн|ын|ний|ны)')
_PRONOUN_GENITIVES = frozenset('миний чиний таны түүний бидний тэдний үүний тэрний энэний'.split())


@lru_cache(maxsize=1024)
def genitive_pairs(query):
    """(modifier, head) key terms of «эцэг эхийн хурал», «амралтын өдөр»: a genitive word and the word
    right after it. Two joined paragraphs, one with the modifier and one with the head, do not answer
    such a question (round 16: «Эцэг эхийн хурал хэзээ болдог вэ?» joined an interview paragraph's
    «эцэг эхийн» with a student conference's «хурал»)."""
    from answer_types import VALUE_WORDS, expected_value, normalise_units
    terms = key_terms(query)
    # The asked value's own word («… албаны өрөө хаана вэ?») is bound by the value check instead.
    asked = VALUE_WORDS.get((expected_value(query) or (None, ()))[0], ())
    # «ШУТИС-ийн элсэлт»: a hyphenated genitive is one word (round 22).
    words = re.findall(r'(?<![\w-])[^\W\d_]{3,}-(?:ийн|ын|ний|ны)(?!\w)|\w+', normalise_units(query, numerals=True))
    pairs = []
    for first, second in zip(words, words[1:]):
        if not _GENITIVE.fullmatch(first.replace('-', '')) or first in _PRONOUN_GENITIVES:
            continue
        first = first.split('-')[0]
        modifier = next((term for term in terms if _has_term(term, {first})), None)
        head = next((term for term in terms if term != modifier and _has_term(term, {second})), None)
        if modifier and head and not any(head.startswith(word) for word in asked):
            pairs.append((modifier, head))
    return tuple(pairs)


@lru_cache(maxsize=1024)
def quantity_pair(query):
    """«Хоёр мэргэжил сонгож болох уу?»: a small quantity right before a topic noun, or None. The
    text must say them together («2 мэргэжил»); a list's «2.» and a far «мэргэжлээ» do not
    (round 10: a registration form was shown). Ordinals («2-р курс»), years, «нэг» (also «a», «at
    once»: «нэг удаад») and spans of time («сүүлийн 4 жилд») are not quantities of a topic."""
    from answer_types import normalise_units
    terms = key_terms(query)
    words = re.findall(r'[\w-]+', normalise_units(query, numerals=True))
    for index, word in enumerate(words[:-1]):
        following = words[index + 1].casefold()
        if (re.fullmatch(r'[2-9]|1\d|20', word) and word in terms and re.fullmatch(r'[^\W\d_]+', following)
                and not re.match(r'(?:жил|сар|өдөр|цаг|удаа|минут|хоног)', following)):
            noun = next((term for term in terms if term != word and _has_term(term, {words[index + 1]})), None)
            if noun:
                return word, noun
    return None


def _quantity_together(text, number, noun):
    """Some quantity right before the noun: the asked one or another («зөвхөн нэг мэргэжил» answers
    «Хоёр мэргэжил …?» too, review), a range or a bound («2-3», «2-оос»); not a list number."""
    from answer_types import normalise_units
    prefix = re.escape(noun[:max(3, len(noun) - 3)])
    return bool(re.search(r'(?<![\w.,])\d+(?:[-–]\d+|-?[а-яөүё]+)?(?![\w.,)%])\s+(?:[\w-]+\s+)?' + prefix,
                          normalise_units(text, numerals=True).casefold()))


def _near(text, first, second, distance=2):
    from answer_types import normalise_units
    words = re.findall(r'\w+', normalise_units(text, numerals=True))
    left = [i for i, word in enumerate(words) if _has_term(first, {word})]
    right = [i for i, word in enumerate(words) if _has_term(second, {word})]
    return any(abs(i - j) <= distance for i in left for j in right)


_VERB_FORM = (r'(?:[аэоөиу]?х|н[аэоө]|с[аэоө]н|[аэоөиу]?[жч]|[аэоө]{2}д|д[аэоө]г|т[аэоө]й|[аэоө]?гд|л[аэоө]{2}|'
              r'[аэоө]{2}р[аэ]й|[аэоө]р[аэ]й)')


_ACT_NOUN = r'(?:[аэоө]?лт|[аэоө]?лга|[аэоө]{2})'


def _root_pattern(root):
    """«нэвтр» -> «нэвт[аэоө]?р»: a stem's last short vowel shows before a consonant ending
    («нэвтрэх», «нэвтэрч»), round 16."""
    if re.search(r'[^аэиоуөүяеёюыьъ]{2}$', root):
        return re.escape(root[:-1]) + '[аэоө]?' + re.escape(root[-1])
    return re.escape(root)


def _issued_together(query, text, verb=ISSUE_VERB):
    """One sentence names the asked paper (the question's last topic word: «… гэрээ хаанаас авах
    вэ?» -> «гэрээ») and says it is issued: two joined windows, one naming «тодорхойлолт» and
    another with «авна», do not answer (round 9)."""
    terms = key_terms(query)
    return bool(terms) and any(verb.search(sentence) and _has_term(terms[-1], _words(sentence))
                               for sentence in re.split(r'[.!?\n]+', text.casefold()))


@lru_cache(maxsize=1024)
def _how_verb_root(query):
    """The root of a «how» question's verb when a topic noun of the question shares it
    («хэрхэн төлөх» with «төлбөр» -> «төл»), or when the root is long enough to name the act on its
    own («Цахим системд яаж нэвтрэх вэ?» -> «нэвтр», «… хэрхэн харьцдаг вэ?» -> «харьц»; round 16: a
    photo upload step and a project visit were shown for them), else None. Short roots («ав», «оч»,
    «элс») would match unrelated words."""
    if not re.search(r'(?<!\w)(?:хэрхэн|яаж)(?!\w)', query.casefold()):
        return None
    terms = _all_terms(query)
    match = re.fullmatch(r'(\w{2,}?)[аэоөиу]?(?:х|д[аэоө]г)', terms[-1]) if terms else None
    if not match:
        return None
    root = match.group(1)
    return (root if len(root) >= 4 or any(term != terms[-1] and term.startswith(root) for term in terms[:-1])
            else None)


def topic_covered(query, text, titles='', typed=False):
    """Key-term coverage of the shown text, read with its pages' titles.

    A paragraph under the page title «ШМТК — Элсэлт 2026» is about admissions 2026, as
    the anchor check already reads the title (W04-A07: «Цахим бүртгэл 08/03-08/13»). With
    ``typed`` the asked value's own words («хугацаа», «цаг») need no literal match: the
    value check has already found a value of that type. Both apply only to a question
    with an asked value type, whose value-next-to-anchor guard stops two unrelated
    paragraphs from being joined (W04-A14 «ямар нэртэй» was stitched from two pages
    when titles counted for it). The threshold still follows the full term count.
    """
    terms = key_terms(query)
    required = (SHORT_QUESTION_COVERAGE if len(terms) <= SHORT_QUESTION_TERMS
                else LONG_QUESTION_COVERAGE)
    kind = None
    if typed:
        from answer_types import VALUE_WORDS, expected_value
        kind, stems = expected_value(query) or (None, ())

        def without(words, among):
            return tuple(term for term in among if not any(term.startswith(word) or word.startswith(term)
                                                             for word in words))
        # The value's own words go first; the counted noun too, unless nothing else is left
        # («Лаборатори хэдэн ширхэг байдаг вэ?» keeps «лаборатори», round 5).
        terms = without(VALUE_WORDS.get(kind, ()), terms) or terms
        terms = without(stems, terms) or terms
    # «Хоёр мэргэжил сонгож болох уу?» is answered by «зөвхөн нэг мэргэжил» too: the quantity check
    # below stands in for the literal number (review, round 10).
    quantity = quantity_pair(query)
    if quantity:
        terms = tuple(term for term in terms if term != quantity[0]) or terms
    words = _words(text + ('\n' + titles if kind else ''))
    # A question without a topic word («Та хэн бэ?») is not about any paragraph (round 9: it was
    # answered with an internship text).
    if not terms or sum(_has_term(term, words, verb_stem=True) for term in terms) / len(terms) < required:
        return False
    obtain = OBTAIN_QUESTION.search(query.casefold())
    if obtain and not _issued_together(query, text, ISSUE_VERB if obtain.group(1)
                                       else SEE_VERB if obtain.group(2) else SUBMIT_VERB):
        return False
    if PAPER_HOW.search(query.casefold()) and not _issued_together(query, text):
        return False
    if quantity and not _quantity_together(text, *quantity):
        return False
    # «Сургалтын төлбөрөө хэрхэн төлөх вэ?»: the asked verb shares its root with a topic noun
    # («төлөх» / «төлбөр»), so a prefix match cannot tell paying from a fee; the verb must stand
    # as a verb («төлнө», «төлсөн», «төлж»), round 5.
    root = _how_verb_root(query)
    if root:
        # A long root may stand as the act's noun too («Төгсөлтийн ажлыг хэрхэн хамгаалдаг вэ?» ->
        # «хамгаалалт»); a root a topic noun shares must stand as a verb (review, round 16).
        shared = any(term.startswith(root) for term in _all_terms(query)[:-1])
        form = _VERB_FORM if shared else '(?:' + _VERB_FORM + '|' + _ACT_NOUN + ')'
        if not re.search(r'(?<!\w)' + _root_pattern(root) + form, text.casefold()):
            return False
    # «Цайны газар байдаг уу?» (a cafeteria) is not answered by «цайны цаг … газар»: a two-word
    # topic must stand together in the text too (11/17 (5)).
    pair = phrase_pair(query)
    return pair is None or _near(text, *pair)


def _heading_only(text):
    """Only a heading and a date («ДУГУЙЛАН, КЛУБИЙН ТАНИЛЦУУЛГА / 2026 оны аравдугаар сарын 13»): a news
    item's title says no more than the question (round 14: «Ямар клубүүд байдаг вэ?»)."""
    from evidence_contract import _PUBLICATION_DATE
    lines = [re.sub(r'\s*\[\d+\]', '', line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    def heading(line):
        return (line.upper() == line and len(re.findall(r'[А-ЯӨҮЁ]{2,}', line)) >= 2 and len(line.split()) <= 10
                and not re.search(r'[\d:]', line))
    return bool(lines) and all(_PUBLICATION_DATE.fullmatch(line) or heading(line) for line in lines)


def relevant_to_question(query, text, typed=True, claims=None, focus=(), contexts=None, titles=''):
    if _heading_only(text):
        return False
    if value_missing(query, claims if claims is not None else [text], typed, focus, contexts):
        return False
    return topic_covered(query, text, titles, typed)


def answer_selection(root):
    """A missing or damaged file means no LLM; only a valid file may enable one."""
    try:
        value = json.loads((Path(root) / CONFIG_PATH).read_text(encoding='utf-8'))
        selector, enabled = value['selector'], value['local_llm_enabled']
        single_unit = value.get('single_unit_coverage', False)
        typed = value.get('typed_value_check', True)
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return dict(SAFE_DEFAULT)
    if (selector not in {RULE_SELECTOR, GEMMA_SELECTOR} or type(enabled) is not bool
            or selector == GEMMA_SELECTOR and not enabled or type(single_unit) is not bool
            or type(typed) is not bool):
        return dict(SAFE_DEFAULT)
    return dict(selector=selector, local_llm_enabled=enabled, single_unit_coverage=single_unit,
                typed_value_check=typed)


# The school's six departments (nmct.edu.mn/departments/<slug>, 11/17 copy) by the words of their
# names; whole word beginnings, so «компани» or «цахим» name none of them (review, round 11).
_DEPARTMENT_WORDS = (('хими', 'chemical'), ('барилг', 'civil'), ('бүтц', 'civil'), ('компьютер', 'computer-science'),
                     ('цахилгаа', 'electrical'), ('электрон', 'electrical'), ('эрдм', 'general'), ('эрдэм', 'general'),
                     ('механик', 'mechanical'))
_DEPARTMENT_PAGE = re.compile(r'/departments/(chemical|civil|computer-science|electrical|general-department|mechanical)(?![\w-])')


@lru_cache(maxsize=1024)
def _department_stem(text):
    """The one department a question names by the words right before «тэнхим» («Барилгын тэнхим» ->
    civil, «Цахилгааны тэнхим» -> electrical); None for the school, «Хамгийн олон оюутантай тэнхим»
    or a question naming two departments (review)."""
    found = set()
    for match in re.finditer(r'((?:[а-яөүё]+[ \t]+){1,4})тэнхим', (text or '').casefold()):
        found |= {name for word in match.group(1).split() for prefix, name in _DEPARTMENT_WORDS
                  if word.startswith(prefix)}
    return found.pop() if len(found) == 1 else None


def _page_department(url):
    """The department whose own page an address is (its URL, not its title), or None."""
    match = _DEPARTMENT_PAGE.search(url or '')
    return None if match is None else 'general' if match.group(1) == 'general-department' else match.group(1)


def bounded_lexical_selection(query, units, sources=None, requirements=(), single_unit=False, typed=True):
    """First complete and relevant BM25 subset, with no references or answer values.

    Rank units by BM25 (stable original-order ties); retain at most 8 positive
    roots, then add up to 4 units holding a requested field whatever their BM25
    score. Try 1, then 2, then 3 roots. Within each size prefer greatest summed
    BM25, then ranked-order tuple. The first subset accepted by the shared
    renderer wins; without a requested field it must also cover the key terms.
    With ``single_unit`` one selected unit alone must cover them. With ``typed`` the
    selection must also hold a value of the asked type (answer_types.py); among equally
    covering subsets one holding the question's own section heading comes first.
    """
    from source_fields import missing_field_evidence
    from tools.evaluate_llm_selection import common_render, lexical_selection
    scored = lexical_selection(query, units, 3)['scores']
    ranked = [row for row in scored if row['score'] > 0][:8]
    texts_by_id = {unit['unit_id']: unit['text'] for unit in units}
    if requirements:
        chosen = {row['unit_id'] for row in ranked}
        ranked = ranked + [row for row in scored if row['unit_id'] not in chosen and len(
            missing_field_evidence(requirements, [texts_by_id[row['unit_id']]])) < len(requirements)][:4]
    checked = []
    focus = focus_terms(query, units) if typed else set()
    # A page's title and heading name what its paragraphs are about (the anchor check); its
    # address tells a department page or a news item from a school-wide page (school_scope).
    headings = {source.get('source_id'): source.get('title', '') + '\n' + source.get('page_header', '')
                + '\n' + (source.get('url') or '') for source in sources or []}
    # For key-term coverage only the page's own name: its title and the first header line.
    titles = {source.get('source_id'): source.get('title', '') + '\n'
              + (source.get('page_header') or '').split('\n', 1)[0] for source in sources or []}
    source_of = {unit['unit_id']: unit.get('source_id') for unit in units}
    asked_department = _department_stem(query)
    page_department = {source.get('source_id'): _page_department(source.get('url')) for source in sources or []}
    pairs = genitive_pairs(query)
    # «Архитектурын тэнхим хаана байдаг вэ?» (round 22): a department the school's six do not hold must be named
    # as such in the text or its page's name («архитектурын … тэнхим» together), not «Архитектурын Сургууль» on
    # another department's page.
    # The name stands right before «тэнхим» (or with «инженерийн», «ухааны» between); a general modifier
    # («мэргэжлийн тэнхимүүд») names no department (review).
    named_department = next((pair for pair in pairs if pair[1].startswith('тэнхим') and not pair[0].startswith(
        ('мэргэж', 'инженер', 'сургал'))), None) if asked_department is None else None
    names_department = {}

    def department_named(unit_id):
        if unit_id not in names_department:
            from answer_types import normalise_units
            words = re.findall(r'\w+', normalise_units(texts_by_id[unit_id] + '\n' + titles.get(source_of.get(unit_id), ''),
                                                       numerals=True))
            names_department[unit_id] = any(
                _has_term(named_department[0], {word}) and (
                    (index + 1 < len(words) and _has_term(named_department[1], {words[index + 1]}))
                    or (index + 2 < len(words) and words[index + 1].startswith(('инженер', 'ухаан', 'технолог'))
                        and _has_term(named_department[1], {words[index + 2]})))
                for index, word in enumerate(words))
        return names_department[unit_id]

    def holds_pair(unit_id, first, second):
        # The unit read with its page's own name, as for coverage, and with fleeting vowels:
        # «Төгсөлтийн судалгааны ажил» holds «төгсөлтийн ажлаа» (W04-A09).
        words = _anchor_words(texts_by_id[unit_id] + '\n' + titles.get(source_of.get(unit_id), ''))
        return _has_term(first, words) and _has_term(second, words)
    if typed and not requirements:
        from answer_types import expected_value, value_supported
        if expected_value(query) is not None:
            # The paragraph that holds the asked value («Энэ жил 78 оюутан…») can rank below
            # paragraphs that only repeat the topic words (Jia & Liang 2017). Up to two units
            # with a value of the asked type next to the anchor join the subsets; every guard
            # below still applies (11/17 (5)).
            chosen = {row['unit_id'] for row in ranked}

            def anchored(unit_id):
                # The anchor may stand in the paragraph or in its own page's title (as below).
                words = _anchor_words(texts_by_id[unit_id] + '\n' + headings.get(source_of.get(unit_id), ''))
                return not focus or any(_has_term(term, words) for term in focus)

            ranked = ranked + [row for row in scored if row['score'] > 0 and row['unit_id'] not in chosen
                               and value_supported(query, texts_by_id[row['unit_id']], strict=not focus)
                               and anchored(row['unit_id'])][:2]
    headed_unit = {row['unit_id']: heading_match(query, texts_by_id[row['unit_id']]) for row in ranked}
    for count in range(1, min(3, len(ranked)) + 1):
        choices = list(combinations(range(len(ranked)), count))
        # Within a size, cover the question's key terms first, then a unit headed by
        # those terms («Эрхэм зорилго»), then BM25.
        coverage = {indices: key_term_coverage(query, ' '.join(texts_by_id[ranked[i]['unit_id']] for i in indices))
                    for indices in choices}
        headed = {indices: any(headed_unit[ranked[i]['unit_id']] for i in indices) for indices in choices}
        choices.sort(key=lambda indices: (-coverage[indices], -headed[indices],
                                          -sum(ranked[i]['score'] for i in indices), indices))
        for indices in choices:
            ids = [ranked[i]['unit_id'] for i in indices]
            candidate = common_render(query, ids, units, sources=sources)
            claims = [claim['text'] for claim in candidate['claims']] if candidate['accepted'] else []
            contexts = [headings.get(claim.get('source_id'), '') for claim in candidate['claims']] if claims else []
            named = '\n'.join(dict.fromkeys(titles.get(claim.get('source_id'), '')
                                            for claim in candidate['claims'])) if claims and typed else ''
            shown = '\n'.join(claims)
            if candidate['accepted'] and not requirements and asked_department and any(
                    page_department.get(source_of.get(unit_id)) not in (None, asked_department) for unit_id in ids):
                # «Барилгын тэнхим ямар лабораторитой вэ?» was answered with the Механик department
                # page's labs, its «Барилга» found on the department list (round 11).
                candidate = dict(accepted=False, reason='other_department')
            elif (candidate['accepted'] and not requirements and named_department
                    and not any(department_named(unit_id) for unit_id in ids)):
                candidate = dict(accepted=False, reason='unknown_department')
            elif (candidate['accepted'] and not requirements and len(ids) > 1 and pairs
                    and not all(any(holds_pair(unit_id, *pair) for unit_id in ids) for pair in pairs)):
                # «Эцэг эхийн хурал хэзээ болдог вэ?»: no joined paragraph says «эцэг эхийн … хурал» (round 16).
                candidate = dict(accepted=False, reason='pair_split')
            elif (candidate['accepted'] and not requirements
                    and not relevant_to_question(query, shown, typed, claims=claims, focus=focus, contexts=contexts,
                                                 titles=named)):
                # Name the cause: topic words present but no value of the asked type. With the
                # switch off the earlier screen keeps its earlier reason.
                candidate = dict(accepted=False, reason='requested_value_missing'
                                 if typed and topic_covered(query, shown, named, typed)
                                 and value_missing(query, claims, typed, focus, contexts)
                                 else 'selection_not_relevant')
            elif (candidate['accepted'] and not requirements and single_unit
                    and not any(relevant_to_question(query, texts_by_id[unit_id], typed, focus=focus)
                                for unit_id in ids)):
                candidate = dict(accepted=False, reason='no_single_unit_covers_question')
            checked.append(dict(root_ids=ids, accepted=candidate['accepted'], reason=candidate['reason']))
            if candidate['accepted']:
                return dict(selected_unit_ids=ids, llm_calls=0, abstained=False, ranked_top8=ranked,
                            checked_subsets=checked, output=candidate)
    return dict(selected_unit_ids=[], llm_calls=0, abstained=True, ranked_top8=ranked,
                checked_subsets=checked, output=None)


class RuleSelectionGenerator:
    """The generator interface ChatRAG expects; it has no provider or transport."""
    model = None
    configured = False
    llm_role = None

    def __init__(self, single_unit_coverage=False, typed_value_check=True):
        self.single_unit_coverage = single_unit_coverage is True
        self.typed_value_check = typed_value_check is not False

    def status(self):
        return dict(provider='none', configured=False, available=False, provider_ready=False,
                    model=None, llm_calls=0, network_probe=False, selection_method=RULE_SELECTOR,
                    single_unit_coverage=self.single_unit_coverage, typed_value_check=self.typed_value_check,
                    reason='local_llm_disabled_by_configuration')

    def generate(self, query, sources):
        from evidence_contract import evidence_units
        from source_fields import missing_field_evidence, source_bound_field_requirements
        from tools.evaluate_llm_selection import scoped_sources
        started = time.perf_counter()
        result = dict(claims=[], generated=False, llm_calls=0, model=None,
                      selection_method=RULE_SELECTOR, llm_role=None, answer_text_generated=False)

        def finish(reason):
            result.update(reason=reason, latency_ms=round((time.perf_counter() - started) * 1000, 2))
            return result

        if not sources:
            return finish('no_evidence')
        # The year filter runs inside scoped_sources; an empty result keeps its
        # own explanation instead of claiming that the source has no such data.
        scoped = scoped_sources(query, sources)
        if not scoped:
            return finish('requested_year_not_supported')
        units = evidence_units(scoped, max_characters=900)
        if not units:
            return finish('no_complete_evidence_units')
        result['answer_mode'] = 'source_preserving_selection'
        result['evidence_unit_count'] = len(units)
        requirements = source_bound_field_requirements(query, scoped)
        if requirements:
            result['requested_fields'] = [field['name'] for field in requirements]
        selection = bounded_lexical_selection(query, units, sources=scoped, requirements=requirements,
                                              single_unit=self.single_unit_coverage, typed=self.typed_value_check)
        result['selection_rule'] = dict(ranked_top8=selection['ranked_top8'],
                                        checked_subsets=selection['checked_subsets'])
        if selection['abstained']:
            if not selection['ranked_top8']:
                return finish('insufficient_evidence')
            missing = missing_field_evidence(requirements, [unit['text'] for unit in units])
            if missing:
                result['missing_requested_fields'] = missing
                return finish('requested_fields_not_in_evidence')
            if requirements:
                return finish('requested_fields_not_in_selection')
            # Stage 3: no single unit or subset covers the question, so say nothing was found.
            # A subset that covered the topic but lacked the asked value is reported as such.
            if any(row['reason'] == 'requested_value_missing' for row in selection['checked_subsets']):
                from answer_types import expected_value
                result['expected_value'] = (expected_value(query) or ('number', ()))[0]
                return finish('requested_value_not_in_selection')
            return finish('selection_not_relevant' if any(row['reason'] in {
                'selection_not_relevant', 'no_single_unit_covers_question', 'other_department', 'pair_split',
                'unknown_department'}   # round 22: these too say «not found», not «could not verify»
                for row in selection['checked_subsets']) else 'selector_abstained')
        output = selection['output']
        result.update(claims=output['claims'], generated=True, proposed_unit_ids=selection['selected_unit_ids'],
            selected_unit_ids=output['selected_unit_ids'], semantic_correctness_proven=False,
            publication_context_unit_ids=output.get('publication_context_unit_ids', []),
            named_heading_context_unit_ids=output.get('named_heading_context_unit_ids', []),
            selection_refinement=output.get('selection_refinement'))
        if requirements:
            result['missing_requested_fields'] = []
            result['field_screen_semantic_correctness_proven'] = False
        return finish('source_preserving_selection')


def default_generator(root):
    selection = answer_selection(root)
    if selection['selector'] == GEMMA_SELECTOR:
        from rag_runtime import GroundedGenerator
        return GroundedGenerator(root)
    return RuleSelectionGenerator(single_unit_coverage=selection['single_unit_coverage'],
                                  typed_value_check=selection['typed_value_check'])
