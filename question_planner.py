"""Question understanding before routing: split a compound question, resolve plain names.

The planner never answers and never writes answer text. It only turns one visitor
question into one to three routable questions, then every part goes through the
existing guarded route (reception tables -> stored FAQ -> website sources) on its own.
The composed reply lists each part with its own sourced answer, or says that part was
not found and where to ask. Three closed rules, each switchable in
config/question-planner.json so the thesis can report the planner off and on:

1. split_compound   — "A вэ, B уу?" with a question word on both sides becomes two parts;
                      a part without its own topic (or with the possessive "нь") inherits the
                      subject of the previous part ("…төлбөр хэд вэ, хэсэгчлэн төлж болох уу").
2. class_groups     — "Компьютерын ухааны 2-р курс" -> "КУ-2" when the reception class table
                      has exactly one group for that department and course.
3. staff_names      — "Сэлмаа багш" -> "Б.Сэлмаа багш" when exactly one person in the staff
                      or class table has that given name; only directly before "багш".
4. closed_wording   — the reception table path answers only fixed wordings (a safety design).
                      A class-group question about its room or class teacher is put into that
                      wording ("ХИ-3 анги хэдэн тоот вэ" -> "ХИ-3 анги хаана хичээллэдэг вэ"), and
                      a short office name is replaced by the unique table name it abbreviates
                      ("карьерын төв" -> "Карьер хөгжлийн төв"). Part of class_groups.
                      11/17: also a class teacher's contact ("КУ-2 ангийн багштай яаж холбогдох вэ"
                      -> "КУ-2 ангийн багшийн имэйл"), a class's weekday timetable, and an office's
                      room ("Сургалтын албаны өрөө хаана вэ" -> "Сургалтын алба хаана вэ").
5. teacher_intent   — a named teacher (in the staff table) with a contact, room or meeting
                      question goes to that wording ("Соронзонболд багштай одоо уулзаж болох уу"
                      -> "Н.Соронзонболд багш одоо хичээлтэй юу"). Part of staff_names.

No model, no network; a rule that does not match leaves the text unchanged.
"""
from copy import deepcopy
import json
from pathlib import Path
import re

from reception_tables import NUMBER_UNITS, last_vowel, normalize_wording, spoken_form, strip_fillers

CONFIG_PATH = 'config/question-planner.json'
MAX_PARTS = 3
# «юм» alone ends a statement («Багштай уулзах гэсэн юм, имэйл нь юу вэ?» is one request); only
# «юм бэ» asks, and «бэ» is here already (11/17 (5)).
QUESTION_WORD = re.compile(r'(?<!\w)(?:вэ|бэ|уу|үү|юу|хэн|хэнд|хэнээс|хэд\w*|хаана|хаашаа|хаанаас|хэзээ|'
                           r'ямар|яаж|яах|аль|болох\s+уу|байдаг\s+уу)(?!\w)', re.I)
# «Төлбөр нь хэд вэ?», «Төлбөр нь?»: one noun with «нь» (its) asks about the thing just named, even when
# the noun is a topic word of its own (round 17: after «Дотуур байр байдаг уу?» it was answered with a
# scholarship's «100% / Сургалтын төлбөр …»). The question words are QUESTION_WORD's (review).
OWN_ATTRIBUTE = re.compile(r'\s*[^\W\d_]+\s+нь(?:\s+(?:' + QUESTION_WORD.pattern + r'|хэрхэн)|\s*\?*\s*$)', re.I)
# Words that carry no topic of their own; a part made only of these needs the previous subject.
FUNCTION_WORDS = frozenset('''вэ бэ уу үү юу юм хэн хэнд хэд хэдэн хэдэд хаана хаашаа хэзээ ямар яаж аль
    нь бол болох байдаг байна байх вэ? бас мөн тэгээд мөн ба болон эсвэл гэж гэх юм бэ уу? одоо
    хийж хийх авах өгөх очих төлж төлөх сурч сурах үргэлжлүүлэн хэсэгчлэн'''.split())
GROUP = re.compile(r'(?<![\w-])([А-ЯӨҮЁ]{2}-\d)(?!\d)')
# «хаана» as a word: «хаанаас авах» (where to get a paper) is not where a class meets (review, round 9).
LOCATION = re.compile(r'(?<!\w)хаана(?!\w)|тоот|өрөө|давхар|хичээллэ', re.I)
TIME_WORDS = re.compile(r'өнөөдөр|маргааш|одоо|цаг|гараг|даваа|мягмар|лхагва|пүрэв|баасан|бямба|ням', re.I)
OFFICE_QUESTION = re.compile(r'(.{2,60}?)\s+(хаана|хэддүгээр\s+давхарт)(?!\w)(.*)', re.I | re.S)
# A phone question is not rewritten to e-mail: staff phones are never shown, so it goes to the
# phone wording, whose reply says so before offering the school e-mail (no silent field swap).
CONTACT = re.compile(r'холбо(?:о\s+бар|гд)|имэйл|имейл|мэйл|цахим\s+шуудан', re.I)
PHONE = re.compile(r'утас|утс[аы]|phone', re.I)
OTHER_TIME = re.compile(r'маргааш|өчигдөр|нөгөөдөр|(?<!\w)(?:даваа|мягмар|лхагва|пүрэв|баасан|бямба|ням)(?!\w)|'
                        r'\d{1,2}:\d{2}|цагт', re.I)
MEETING = re.compile(r'уулз|одоо|чөлөөтэй|(?<!\w)сул(?!\w)|хичээлтэй', re.I)
ROOM_ASK = re.compile(r'өрөө|тоот|хаана\s+(?:суудаг|байдаг|ажилладаг|байна)', re.I)
WEEKDAY = re.compile(r'(?<!\w)(даваа|мягмар|лхагва|пүрэв|баасан|бямба|ням)(?!\w)', re.I)
DAY_WORD = re.compile(r'(?<!\w)(өнөөдөр|маргааш|даваа|мягмар|лхагва|пүрэв|баасан|бямба|ням)(?!\w)', re.I)
TEACHER = re.compile(r'(?<![\w.])([А-ЯӨҮЁ])\.\s*([А-ЯӨҮЁ][а-яөүё-]{2,})\s+багш', re.I)
# Parallel asked values sharing one predicate: «…хэдэн оюутан» + «хэдэн багш оролцсон бэ».
PARALLEL_HEAD = re.compile(r'^(?P<subject>.*?)(?P<ask>(?<!\w)(?:хэдэн|хэд|хэддүгээр|ямар)\s+[\w-]+)$', re.I)
PARALLEL_TAIL = re.compile(r'^(?P<ask>(?:хэдэн|хэд|хэддүгээр|ямар)\s+[\w-]+)\s+(?P<predicate>\S.*)$', re.I)
PARTICLES = frozenset('вэ бэ уу үү юу юм'.split())
# Finite verb endings («байна», «байдаг», «оролцсон»); a counted noun («удаа», «оюутан») keeps none.
VERB_END = re.compile(r'(?:даг|дэг|дог|дөг|на|нэ|но|нө|сан|сэн|сон|сөн|ах|эх|ох|өх)$')
# Words that ask about a property of the thing already named («Имэйл нь юу вэ?», «Хэддүгээр
# давхарт байдаг вэ?»), not a new topic, when a follow-up borrows the previous question's thing.
FOLLOWUP_ATTRIBUTES = frozenset(('утас', 'имэйл', 'цахим шуудан', 'хаяг', 'өрөө', 'давхар', 'тоот', 'байрлах',
                                 'байрладаг', 'багш', 'анги', 'бүлэг', 'хуваарь', 'уулзах', 'эрхлэгч', 'холбоо барих'))
SPOKEN_DIGITS = NUMBER_UNITS
# Round 20: a polite opening («Уучлаарай, …», «Сайн байна уу, …») or a short self-introduction («Би шинэ оюутан,
# …») before the question; its comma kept the desk's lookups from reading «номын сан хаана байдаг вэ».
COURTESY = re.compile(r'(?:\s*(?:уучлаарай|өршөөгөөрэй|сайн\s+(?:байна\s+|байцгаана\s+)?уу|байна\s+уу|надад\s+тусална\s+уу|'
                      r'туслаач|нэг\s+юм\s+асууя|асуух\s+юм\s+байна|би\s+(?:шинэ\s+)?(?:оюутан|элсэгч|эцэг\s+эх|зочин)|'
                      r'би\s+элсэх\s+гэсэн\s+юм)\s*[,!.]+)+\s*(?=\S)', re.I)


def _without_courtesy(text):
    """The question without its polite opening, and whether one was there."""
    courtesy = COURTESY.match(text) if isinstance(text, str) else None
    if not courtesy:
        return text, False
    rest = text[courtesy.end():].strip()
    return rest[:1].upper() + rest[1:], True
GREETING = re.compile(r'(?:сайн\s+(?:байна\s+|байцгаана\s+)?уу|баярлалаа|hello|hi)', re.I)
# A wish to get a paper (round 9); only papers, so «Шалгалт авах …» (an exam) and «Мэдээлэл авмаар байна»
# (broad information, which has its own clarification) stay as asked (review).
REQUEST = re.compile(r'(.{0,60}?(?:тодорхойлолт|хуудас|үнэмлэх|карт|гэрчилгээ|диплом|лавлагаа|маягт|анкет|'
                     r'гэрээ|өргөдөл|хуулбар)\w*)\s+ав(?:ах\s+гэсэн(?:\s+юм)?|маар\s+байна|ъя|ах\s+хэрэгтэй\s+байна)'
                     r'\s*[.!?]*', re.I)
COURSE = re.compile(r'(?<!\d)([1-5])\s*(?:-?\s*(?:р|дугаар|дүгээр|дахь|дэх)\b)?\s*курс\w*', re.I)


def _words(text):
    return re.findall(r'[\w.-]+', text.casefold())


def _stem(word):
    return word.casefold()[:5]


def _comitative(word):
    """«зүйч» -> «зүйчтэй», «Захирал» -> «Захиралтай», «Болд» -> «Болдтой»: the word's last vowel other
    than «и» chooses the ending (round 16)."""
    last = last_vowel(word) or 'э'
    return word + ('той' if last in 'оё' else 'тай' if last in 'аяуюы' else 'тэй')


def _office_stem(word):
    # «албаны» and «алба» meet at «алба»; a five-letter cut would not (11/17).
    from mongolian_morphology import light_stem
    return light_stem(word.casefold())


class QuestionPlanner:
    def __init__(self, *, enabled=False, split_compound=False, class_groups=False, staff_names=False,
                 groups=None, given_names=None, topic_keywords=(), offices=(), staff=(), class_names=()):
        self.enabled = enabled is True
        self.split_compound = self.enabled and split_compound is True
        self.class_groups = self.enabled and class_groups is True
        self.staff_names = self.enabled and staff_names is True
        self.groups = dict(groups or {})            # (department stem, course) -> group code
        self.given_names = dict(given_names or {})  # given name (casefold) -> full "Б.Сэлмаа"
        self.topic_keywords = tuple(keyword.casefold() for keyword in topic_keywords)
        self.offices = tuple(offices)                # service names in the reception rooms table
        # "б.сэлмаа" -> the table's own spelling, so the rewrite matches the reception lookup.
        self.staff = {re.sub(r'\s+', '', name.casefold()): name.strip() for name in staff}
        self.class_names = frozenset(class_names)    # every class group code in the table

    @classmethod
    def from_config(cls, root, reception=None):
        root = Path(root)
        try:
            config = json.loads((root / CONFIG_PATH).read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            return cls()
        if config.get('schema_version') != 1 or config.get('enabled') is not True:
            return cls()
        tables = getattr(reception, 'tables', None) if getattr(reception, 'enabled', False) else None
        groups, names, offices, staff, class_names = {}, {}, [], [], []
        if tables is not None:
            seen = {}
            for group in tables.classes:
                department = (group.department or '').strip()
                if not department or not str(group.course).strip().isdigit():
                    continue
                key = (_stem(department.split()[0]), str(group.course).strip())
                seen.setdefault(key, set()).add(group.group)
            groups = {key: next(iter(values)) for key, values in seen.items() if len(values) == 1}
            owners = {}
            for full in [person.name for person in tables.staff] + [group.teacher for group in tables.classes]:
                match = re.fullmatch(r'\s*([А-ЯӨҮЁ])\.\s*([А-ЯӨҮЁа-яөүё-]{3,})\s*', full or '')
                if match:
                    owners.setdefault(match[2].casefold(), set()).add(match[1] + '.' + match[2])
            names = {given: next(iter(fulls)) for given, fulls in owners.items() if len(fulls) == 1}
            offices = [service.name for room in tables.rooms for service in room.services]
            staff = [person.name for person in tables.staff]
            class_names = [group.group for group in tables.classes]
        keywords = []
        try:
            domains = json.loads((root / 'config/knowledge-domains.json').read_text(encoding='utf-8'))['domains']
            keywords = [word for domain in domains.values() for word in domain.get('keywords', [])]
        except (OSError, ValueError, KeyError, AttributeError):
            pass
        return cls(enabled=True, split_compound=config.get('split_compound'), class_groups=config.get('class_groups'),
                   staff_names=config.get('staff_names'), groups=groups, given_names=names, topic_keywords=keywords,
                   offices=offices, staff=staff, class_names=class_names)

    # -- rules ---------------------------------------------------------------
    def _split(self, query):
        sentences = [s.strip() for s in re.split(r'[?？;]+', query) if s.strip()]
        parts = []
        for sentence in sentences:
            pieces = [p.strip() for p in re.split(r',\s*', sentence) if p.strip()]
            current = pieces[0]
            for piece in pieces[1:]:
                if QUESTION_WORD.search(current) and QUESTION_WORD.search(piece):
                    parts.append(current)
                    current = piece
                else:
                    current += ', ' + piece
            parts.append(current)
        if len(parts) < 2 or len(parts) > MAX_PARTS:
            return [query.strip()]
        return [part + '?' for part in parts]

    @staticmethod
    def _distribute(parts):
        """«X-д хэдэн оюутан, хэдэн багш оролцсон бэ?» asks two counts under one predicate: each
        part gets the shared subject (from the first) and predicate (from the last), 11/17 (5)."""
        texts = [part.rstrip('?？').strip() for part in parts]
        tail = PARALLEL_TAIL.match(texts[-1])
        heads = [PARALLEL_HEAD.match(text) for text in texts[:-1]]
        # A head must end in the asked noun («хэдэн оюутан»), not a verb or a particle: «Төлбөр
        # ямар байна?» is already a whole question (review 11/17 (5)).
        if (not tail or not all(heads) or not heads[0].group('subject').strip()
                or any(head.group('ask').split()[-1].casefold() in PARTICLES
                       or VERB_END.search(head.group('ask').split()[-1].casefold()) for head in heads)):
            return parts
        subject, predicate = heads[0].group('subject').strip(), tail.group('predicate').strip()
        return ([(head.group('subject').strip() or subject) + ' ' + head.group('ask') + ' ' + predicate + '?'
                 for head in heads] + [subject + ' ' + tail.group('ask') + ' ' + predicate + '?'])

    def _has_topic(self, text):
        words = [w for w in _words(text) if w not in FUNCTION_WORDS]
        if not words:
            return False
        lowered = text.casefold()
        if any(keyword in lowered for keyword in self.topic_keywords):
            return True
        return bool(re.search(r'[А-ЯӨҮЁA-Z]{2}-\d', text))

    @staticmethod
    def _subject(part):
        match = QUESTION_WORD.search(part)
        return part[:match.start()].strip(' ,') if match else ''

    def _inherit(self, parts):
        result = [parts[0]]
        for part in parts[1:]:
            subject = self._subject(result[-1])
            possessive = re.search(r'(?<!\w)нь(?!\w)', part.casefold())
            if subject and (possessive or not self._has_topic(part)):
                # «Захирал хэн бэ, өрөө нь хаана вэ?» (round 20): the later part as a follow-up of the one before
                # («Захирал хаана вэ?»), as when it is asked on its own; one with a topic of its own («…, багш
                # нар хэн бэ?») stays as asked (review).
                followup = self._followup(part, result[-1])
                if followup:
                    result.append(followup['rewritten'])
                    continue
                subject_words = subject.split()
                first = part.split()[0].casefold() if part.split() else ''
                if subject_words and first[:4] == subject_words[-1].casefold()[:4]:
                    subject_words = subject_words[:-1]     # "КУ-2 анги" + "ангийн багш" -> "КУ-2 ангийн багш"
                part = ' '.join(subject_words + [part])
            result.append(part)
        return result

    def _class_group(self, text):
        course = COURSE.search(text)
        # «Механик инженерт 2-р курст шилжин орвол …» asks about the transfer into the 2nd year, an
        # admission question, not class МИ-2 (round 10: W04-A06 lost its stored answer).
        if not course or re.search(r'шилж|элс', text, re.I):
            return text, None
        before = text[:course.start()]
        tokens = list(re.finditer(r'[А-ЯӨҮЁа-яөүё]+', before))
        for token in reversed(tokens[-4:]):
            group = self.groups.get((_stem(token.group()), course.group(1)))
            if group:
                rest = text[course.end():]
                label = group if re.match(r'\s*анги', rest, re.I) else group + ' анги'
                return text[:token.start()] + label + rest, dict(rule='class_group', text=text[token.start():course.end()],
                                                               value=group)
        return text, None

    def _known_group(self, text):
        match = GROUP.search(text)
        known = self.class_names or set(self.groups.values())
        return match.group(1) if match and match.group(1) in known else None

    def _class_contact(self, text):
        group = self._known_group(text)
        if not group or not re.search(r'багш', text, re.I) or not (CONTACT.search(text) or PHONE.search(text)):
            return text, None
        # A phone question keeps its own wording: the reply says phones are not shown, then gives
        # the school e-mail, as the reception desk does.
        canonical = group + (' ангийн багшийн утас?' if PHONE.search(text) else ' ангийн багшийн имэйл?')
        return canonical, dict(rule='closed_wording', text=text, value=canonical)

    def _class_day(self, text):
        group, day = self._known_group(text), WEEKDAY.search(text)
        # «КУ-2 ангийн багш даваа гарагт хичээлтэй юу?» asks about the teacher, not the class.
        if not group or not day or not re.search(r'хичээл|цаг', text, re.I) or re.search(r'багш', text, re.I):
            return text, None
        canonical = group + ' анги ' + day.group(1).casefold() + ' гарагт хэдэн цагт хичээлтэй вэ?'
        if canonical.rstrip('?') == text.strip().rstrip('?'):
            return text, None
        return canonical, dict(rule='closed_wording', text=text, value=canonical)

    def _class_intent(self, text):
        group = self._known_group(text)
        if not group or TIME_WORDS.search(text):
            return text, None
        if re.search(r'багш', text, re.I) and re.search(r'(?<!\w)хэн(?!\w)', text, re.I):
            canonical = group + ' ангийн багш хэн бэ?'
        elif re.search(r'ангийн\s+багш', text, re.I) and LOCATION.search(text) and not re.search(r'хичээллэ', text, re.I):
            # «КУ-2 ангийн багшийн өрөө хаана вэ?» asks where the class teacher sits, not where the
            # class meets (round 9).
            canonical = group + ' ангийн багшийн өрөө хаана вэ?'
        elif LOCATION.search(text):
            canonical = group + ' анги хаана хичээллэдэг вэ?'
        else:
            return text, None
        if canonical.rstrip('?') == text.strip().rstrip('?'):
            return text, None
        return canonical, dict(rule='closed_wording', text=text, value=canonical)

    def _office(self, text):
        match = OFFICE_QUESTION.fullmatch(text.strip())
        if not match or not self.offices:
            return text, None
        # «Сургалтын албаны өрөө хаана вэ» asks where the office is: drop the room word.
        name = re.sub(r'\s+өрөө(?:нд|ний)?$', '', match.group(1).strip(' ,'), flags=re.I)
        lowered = name.casefold()
        if any(lowered in office.casefold() for office in self.offices):
            return text, None
        # Any form of «сургууль» names the school, not the office.
        stems = {stem for stem in (_office_stem(word) for word in re.findall(r'[А-ЯӨҮЁа-яөүё]{3,}', name))
                 if not stem.startswith('сургуул')}
        if not stems:
            return text, None
        hits = [office for office in self.offices
                if stems <= {_office_stem(word) for word in re.findall(r'[А-ЯӨҮЁа-яөүё]{3,}', office)}]
        if len(hits) != 1:
            return text, None
        short = hits[0].rsplit(',', 1)[-1].strip()
        if sum(short.casefold() in office.casefold() for office in self.offices) != 1:
            return text, None
        replaced = short[:1].upper() + short[1:] + ' ' + match.group(2) + match.group(3)
        return replaced, dict(rule='office_name', text=name, value=short)

    def _class_code(self, text):
        """«ку-2», «КУ2», «ку 2 анги» -> «КУ-2» when that class is in the table (round 8); a spaced
        code only right before «анги», so «Би 2 давхарт …» keeps its pronoun."""
        def code(match):
            digit = match.group(2) or match.group(3) or str(SPOKEN_DIGITS.get((match.group(4) or '').casefold(), ''))
            value = match.group(1).upper() + '-' + digit
            return value if digit and value in self.class_names else match.group(0)
        # «КУ хоёр анги» (speech writes the number as a word), round 13.
        fixed = re.sub(r'(?<![\w-])([А-ЯӨҮЁа-яөүё]{2})(?:-?(\d)(?![\w-])|\s+(\d)(?=\s+анги)|\s+(' + '|'.join(SPOKEN_DIGITS)
                       + r')(?=\s+анги))', code, text, flags=re.I)
        return (fixed, dict(rule='class_code', text=text, value=fixed)) if fixed != text else (text, None)

    def _staff_name(self, text):
        # A given name typed in lower case («сэлмаа багш») is the same teacher (round 8); only names in
        # the staff table are read, so ordinary words before «багш» are not.
        for match in re.finditer(r'(?<![\w.])([А-ЯӨҮЁа-яөүё][а-яөүё-]{2,})(?=\s+багш)', text):
            full = self.given_names.get(match.group(1).casefold())
            if full:
                return text[:match.start()] + full + text[match.end():], dict(rule='staff_name',
                    text=match.group(1), value=full)
        # «Сэлмаагийн өрөө хаана вэ?» (a given name in the genitive, round 13) is that teacher's office.
        for match in re.finditer(r'(?<![\w.])([А-ЯӨҮЁа-яөүё][а-яөүё-]{2,}?)(?:гийн|ийн|ын)(?=\s+(?:өрөө|ажлын\s+өрөө|имэйл))',
                                 text):
            full = self.given_names.get(match.group(1).casefold())
            if full:
                return (text[:match.start()] + full + ' багшийн' + text[match.end():],
                        dict(rule='staff_name', text=match.group(0), value=full))
        return text, None

    @staticmethod
    def _day_wording(full, day):
        word = day.group(1).casefold()
        return full + ' багш ' + (word if word in ('өнөөдөр', 'маргааш') else word + ' гарагт') + ' хичээлтэй юу?'

    def _teacher_intent(self, text):
        match = TEACHER.search(text)
        key = match and (match.group(1) + '.' + match.group(2)).casefold()
        if not match or key not in self.staff:
            return text, None
        full = self.staff[key]
        # Day and time words are looked for outside the teacher's own name («Г.Баасан», «А.Даваа»).
        rest = text[:match.start()] + ' ' + text[match.end():]
        day = DAY_WORD.search(rest)
        other_time = OTHER_TIME.search(rest)
        # Already the closed wording (e.g. «…багшийн имэйл юу вэ?»): leave it as asked.
        # «…багш хаана (байна) вэ?» is the timetable-status wording; it must not become an office room.
        if re.search(r'багшийн\s+(?:и-?мэйл|имэйл|мэйл|цахим\s+шуудан|утас)|багшийн\s+өрөө\s+хаана\s+вэ|'
                     r'багш\s+одоо\s+хичээлтэй\s+юу|багш\s+хэзээ\s+оюутантай\s+уулздаг|'
                     r'багш\s+(?:одоо\s+)?хаана(?:\s+байна)?\s*(?:вэ)?\s*\??$', text, re.I):
            return text, None
        if PHONE.search(text):
            # «холбоо барих утас»: phones are never shown; the phone wording says so and gives
            # the school e-mail instead (not a silent e-mail answer).
            canonical = full + ' багшийн утас?'
        elif CONTACT.search(text):
            canonical = full + ' багшийн имэйл?'
        elif ROOM_ASK.search(text):
            # «…багш даваа гарагт хаана байна вэ?» asks where the teacher is then: that day's
            # timetable (11/17 (5)), not the office room; a clock time has no wording, so it stays.
            if (day or other_time) and not re.search(r'өрөө|тоот', text, re.I):
                if not day:
                    return text, None
                canonical = self._day_wording(full, day)
            else:
                canonical = full + ' багшийн өрөө хаана вэ?'
        elif MEETING.search(text):
            if re.search(r'(?<!\w)хэзээ(?!\w)', text, re.I):
                # «хэзээ уулзах» asks for office hours; «хэзээ хичээлтэй» asks for the teacher's
                # timetable, which has no closed wording here, so it stays as asked.
                if not re.search(r'уулз|чөлөөтэй|(?<!\w)сул(?!\w)', text, re.I):
                    return text, None
                canonical = full + ' багш хэзээ оюутантай уулздаг вэ?'
            elif day:
                # «маргааш», «өнөөдөр» or a weekday is not «now»: that day's timetable wording.
                canonical = self._day_wording(full, day)
            elif other_time:
                # A clock time has no closed wording: leave the question as asked.
                return text, None
            else:
                canonical = full + ' багш одоо хичээлтэй юу?'
        else:
            return text, None
        if canonical.rstrip('?') == text.strip().rstrip('?'):
            return text, None
        return canonical, dict(rule='teacher_intent', text=text, value=canonical)

    def _named(self, text):
        """The thing a question names — a teacher («Б.Сэлмаа багш»), a class group («КУ-2 анги»)
        or a recorded office («Номын сан») — or None."""
        teacher = TEACHER.search(text)
        if teacher:
            return teacher.group(1).upper() + '.' + teacher.group(2) + ' багш'
        if self.staff_names:
            _, rewrite = self._staff_name(text)
            if rewrite:
                return rewrite['value'] + ' багш'
        group = GROUP.search(text)
        if group:
            return group.group(1) + ' анги'
        lowered = text.casefold()
        for office in self.offices:
            short = office.rsplit(',', 1)[-1].strip()
            if short and short.casefold() in lowered:
                return short
        return None

    def _followup(self, query, previous):
        """«Номын сан хаана вэ?» then «Хэдэн цагт ажилладаг вэ?» (round 4, 11/17): an elliptical
        follow-up takes only the previous question's named thing — a teacher, class, office or
        its short subject — never the whole history, which hurts retrieval (Lin et al. 2021;
        Voskarides et al. 2020). A question with a topic or a name of its own is a new question
        (a topic shift) and is left as asked; so is a greeting."""
        text = query.strip()
        lowered = text.casefold()
        if (not isinstance(previous, str) or not previous.strip() or len(_words(text)) > 6
                or not (QUESTION_WORD.search(text) or re.search(r'(?<!\w)нь\s*\?*$', lowered))
                or GREETING.fullmatch(lowered.strip(' ?!.'))
                or GROUP.search(self._class_code(text)[0]) or self._named(text) is not None
                or (any(keyword in lowered for keyword in self.topic_keywords if keyword not in FOLLOWUP_ATTRIBUTES)
                    and not OWN_ATTRIBUTE.match(lowered))):
            return None
        previous = self._class_code(previous.strip())[0]
        entity = self._named(previous)
        if entity is None:
            subject = self._subject(previous)
            if not subject or len(subject.split()) > 4 or QUESTION_WORD.search(subject):
                return None
            entity = subject
        # «тэнд» (there) points at the previous thing, which takes its place (round 13); «энд» (here) is
        # the school itself and starts a new question (review).
        if re.search(r'(?<!\w)энд(?!\w)', text, re.I):
            return None
        rest = re.sub(r'\s+(?=[?!.])', '', re.sub(r'(?<!\w)(?:нь|тэнд)(?!\w)\s*', '', text, flags=re.I)).strip()
        # «Түүнтэй уулзаж болох уу?» (round 20): «түүнтэй» (with them) is the thing just named, which then takes
        # «-тай» whatever follows («Одоо түүнтэй …», «Түүнтэй утсаар холбогдож болох уу?», review).
        with_them = bool(re.search(r'(?<!\w)(?:түүнтэй|тэр\s+хүнтэй)(?!\w)', rest, re.I))
        rest = re.sub(r'\s*(?<!\w)(?:түүнтэй|тэр\s+хүнтэй)(?!\w)\s*', ' ', rest, flags=re.I).strip()
        rest = rest[:1].lower() + rest[1:]
        group = GROUP.search(previous)
        if (group and entity == group.group(1) + ' анги' and re.match(r'\s+ангийн\s+багш', previous[group.end():])
                and (with_them or re.match(r'(?:и-?мэйл|имэйл|мэйл|цахим|өрөө|утас|утсан|байршил|давхар)', rest.casefold()))):
            # «КУ-2 ангийн багш хэн бэ?» then «Өрөө нь хаана вэ?» / «Имэйл нь?» (round 9): the class
            # teacher's room or e-mail, not the class's own room.
            entity = group.group(1) + ' ангийн багш'
        head = entity.split()
        # «Өрөө нь?», «Давхар нь?» alone (round 8): the whole location question about the thing.
        bare = re.fullmatch(r'(өрөө|байршил|давхар)(?:\s+(?:хаана|хэд|хэдэн|хэддүгээр|юу)(?:\s+(?:вэ|бэ))?)?\s*\??',
                            rest.casefold())
        if bare:
            if head[-1] == 'багш':
                # A teacher's room and floor are both in the recorded office.
                rewritten = ' '.join(head[:-1] + ['багшийн']) + ' өрөө хаана вэ?'
            elif bare.group(1) == 'давхар':
                rewritten = entity + ' хэддүгээр давхарт вэ?'
            else:
                rewritten = entity + ' хаана вэ?'
            return dict(rule='followup_context', previous=previous, entity=entity, rewritten=rewritten)
        first = rest.split()[0].casefold() if rest.split() else ''
        if len(head) > 1 and first[:4] == head[-1].casefold()[:4]:
            head = head[:-1]      # «КУ-2 анги» + «ангийн багш хэн бэ» -> «КУ-2 ангийн багш хэн бэ»
        elif head[-1].casefold() == 'багш' and re.match(r'(?:и-?мэйл|имэйл|мэйл|цахим|өрөө|утас|утсан)', first):
            head = head[:-1] + ['багшийн']   # -> «Б.Сэлмаа багшийн имэйл юу вэ»
        elif head[-1].casefold() == 'тэнхим' and re.match(r'(?:эрхлэгч|багш|и-?мэйл|имэйл|утас)', first):
            head = head[:-1] + ['тэнхимийн']   # round 12: -> «Механик тэнхимийн эрхлэгч хэн бэ»
        elif ((with_them or re.match(r'(?:(?:яаж|хэрхэн|одоо|өнөөдөр|маргааш)\s+)?(?:уулз|холбогд)', rest.casefold())
                and not re.search(r'утас|утсан|и-?мэйл|имэйл|мэйл|хаяг|дугаар', rest.casefold()))
                and head[-1].casefold() != 'анги' and not re.search(r'(?:тай|тэй|той)$', head[-1].casefold())):
            # «Сэтгэл зүйч хаана суудаг вэ?» then «Уулзаж болох уу?» (round 16): one meets or contacts
            # someone «-тай»: «Сэтгэл зүйчтэй уулзаж болох уу?», the wording the desk's lookup reads.
            head = head[:-1] + [_comitative(head[-1])]
        return dict(rule='followup_context', previous=previous, entity=entity, rewritten=' '.join(head + [rest]))

    def plan(self, query, previous=None):
        """Return parts to route; each keeps the visitor's original wording for the reply.
        ``previous``: the visitor's previous question, for an elliptical follow-up."""
        # Round 21: a spoken question's filler and colloquial ending first («тэгээд захирал хэн юм бэ»), so the
        # follow-up and split rules below read «захирал хэн бэ».
        stripped = spoken_form(_without_courtesy(strip_fillers(query))[0])
        # The previous question's opening is no subject either («Сайн байна уу, сэтгэл зүйч хаана суудаг вэ?»), review.
        previous = spoken_form(_without_courtesy(strip_fillers(previous))[0]) if previous else previous
        followup = self._followup(stripped, previous) if previous else None
        asked = followup['rewritten'] if followup else stripped
        originals = self._split(asked) if self.split_compound else [asked.strip()]
        routed = list(originals)
        if len(originals) > 1:
            # Distributed parallel parts already carry the subject; others may inherit it.
            distributed = self._distribute(originals)
            routed = distributed if distributed != originals else self._inherit(originals)
        parts = []
        for original, text in zip(originals, routed):
            rewrites = []
            normalized = normalize_wording(text)
            if normalized != text:
                rewrites.append(dict(rule='wording', text=text, value=normalized))
                text = normalized
            # «Сургуулийн тодорхойлолт авах гэсэн юм» (round 9): at the desk, a wish to get a paper
            # asks where it is issued.
            wish = REQUEST.fullmatch(text.strip())
            if wish and not QUESTION_WORD.search(wish.group(1)):
                rewrites.append(dict(rule='request', text=text, value=wish.group(1) + ' хаанаас авах вэ?'))
                text = wish.group(1) + ' хаанаас авах вэ?'
            if self.class_groups:
                for rule in (self._class_code, self._class_group, self._class_contact, self._class_day, self._class_intent,
                             self._office):
                    text, rewrite = rule(text)
                    rewrites += [rewrite] if rewrite else []
            if self.staff_names:
                for rule in (self._staff_name, self._teacher_intent):
                    text, rewrite = rule(text)
                    rewrites += [rewrite] if rewrite else []
            parts.append(dict(original=original, query=text, rewrites=rewrites))
        result = dict(enabled=self.enabled, compound=len(parts) > 1, parts=parts,
                      changed=len(parts) > 1 or any(p['query'] != query.strip() for p in parts))
        if followup:
            result['followup'] = followup
        return result


def _source_urls(result):
    urls = []
    for item in (result.get('citations') or []) + (result.get('related_sources') or []):
        url = item.get('source_url_or_filename') or item.get('url')
        if url and url not in urls:
            urls.append(url)
    return urls


def compose(query, plan, results):
    """One reply from per-part results; never merges or rewrites their answer text."""
    answered = [bool((r.get('answer') or '').strip()) for r in results]
    base = deepcopy(results[answered.index(True)] if any(answered) else results[0])
    lines, citations, related, seen = [], [], [], set()
    for part, result, ok in zip(plan['parts'], results, answered):
        if ok:
            lines.append(part['original'] + '\n' + result['answer'].strip())
        else:
            lines.append(part['original'] + '\nЭнэ хэсгийн баталгаатай мэдээлэл олдсонгүй.')
        for item in result.get('citations') or []:
            key = json.dumps(item, sort_keys=True, ensure_ascii=False)
            if key not in seen:
                seen.add(key)
                citations.append(item)
        related += [item for item in result.get('related_sources') or [] if item not in related]
    referral = next((r.get('referral') for r, ok in zip(results, answered) if not ok and r.get('referral')), None)
    base.update(query=query, answer='\n\n'.join(lines) if any(answered) else None,
                citations=citations, related_sources=related[:3], clarification=None,
                route='C' if all(answered) else ('C' if any(answered) else 'E'),
                reason_code='compound_parts_all_answered' if all(answered) else
                            ('compound_parts_partly_answered' if any(answered) else 'compound_parts_not_answered'),
                answer_kind='compound_parts' if any(answered) else None,
                generated=False, llm_calls=sum(r.get('llm_calls', 0) for r in results),
                parts=[dict(original=part['original'], query=part['query'], rewrites=part['rewrites'],
                            route=result.get('route'), reason_code=result.get('reason_code'),
                            answer_kind=result.get('answer_kind'), answered=ok,
                            source_urls=_source_urls(result)[:3])
                       for part, result, ok in zip(plan['parts'], results, answered)])
    base['reason_codes'] = [base['reason_code']]
    if referral:
        base['referral'] = referral
        base['message'] = referral.get('text', '')
    else:
        base.pop('referral', None)
        base['message'] = ''
    base.pop('teacher_cards', None)
    return base
