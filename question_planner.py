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

No model, no network; a rule that does not match leaves the text unchanged.
"""
from copy import deepcopy
import json
from pathlib import Path
import re

CONFIG_PATH = 'config/question-planner.json'
MAX_PARTS = 3
QUESTION_WORD = re.compile(r'(?<!\w)(?:вэ|бэ|уу|үү|юу|юм|хэн|хэнд|хэнээс|хэд\w*|хаана|хаашаа|хаанаас|хэзээ|'
                           r'ямар|яаж|яах|аль|болох\s+уу|байдаг\s+уу)(?!\w)', re.I)
# Words that carry no topic of their own; a part made only of these needs the previous subject.
FUNCTION_WORDS = frozenset('''вэ бэ уу үү юу юм хэн хэнд хэд хэдэн хэдэд хаана хаашаа хэзээ ямар яаж аль
    нь бол болох байдаг байна байх вэ? бас мөн тэгээд мөн ба болон эсвэл гэж гэх юм бэ уу? одоо
    хийж хийх авах өгөх очих төлж төлөх сурч сурах үргэлжлүүлэн хэсэгчлэн'''.split())
GROUP = re.compile(r'(?<![\w-])([А-ЯӨҮЁ]{2}-\d)(?!\d)')
LOCATION = re.compile(r'хаана|тоот|өрөө|давхар|хичээллэ', re.I)
TIME_WORDS = re.compile(r'өнөөдөр|маргааш|одоо|цаг|гараг|даваа|мягмар|лхагва|пүрэв|баасан|бямба|ням', re.I)
OFFICE_QUESTION = re.compile(r'(.{2,60}?)\s+(хаана|хэддүгээр\s+давхарт)(?!\w)(.*)', re.I | re.S)
COURSE = re.compile(r'(?<!\d)([1-5])\s*(?:-?\s*(?:р|дугаар|дүгээр|дахь|дэх)\b)?\s*курс\w*', re.I)


def _words(text):
    return re.findall(r'[\w.-]+', text.casefold())


def _stem(word):
    return word.casefold()[:5]


class QuestionPlanner:
    def __init__(self, *, enabled=False, split_compound=False, class_groups=False, staff_names=False,
                 groups=None, given_names=None, topic_keywords=(), offices=()):
        self.enabled = enabled is True
        self.split_compound = self.enabled and split_compound is True
        self.class_groups = self.enabled and class_groups is True
        self.staff_names = self.enabled and staff_names is True
        self.groups = dict(groups or {})            # (department stem, course) -> group code
        self.given_names = dict(given_names or {})  # given name (casefold) -> full "Б.Сэлмаа"
        self.topic_keywords = tuple(keyword.casefold() for keyword in topic_keywords)
        self.offices = tuple(offices)                # service names in the reception rooms table

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
        groups, names, offices = {}, {}, []
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
        keywords = []
        try:
            domains = json.loads((root / 'config/knowledge-domains.json').read_text(encoding='utf-8'))['domains']
            keywords = [word for domain in domains.values() for word in domain.get('keywords', [])]
        except (OSError, ValueError, KeyError, AttributeError):
            pass
        return cls(enabled=True, split_compound=config.get('split_compound'), class_groups=config.get('class_groups'),
                   staff_names=config.get('staff_names'), groups=groups, given_names=names, topic_keywords=keywords,
                   offices=offices)

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
                subject_words = subject.split()
                first = part.split()[0].casefold() if part.split() else ''
                if subject_words and first[:4] == subject_words[-1].casefold()[:4]:
                    subject_words = subject_words[:-1]     # "КУ-2 анги" + "ангийн багш" -> "КУ-2 ангийн багш"
                part = ' '.join(subject_words + [part])
            result.append(part)
        return result

    def _class_group(self, text):
        course = COURSE.search(text)
        if not course:
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

    def _class_intent(self, text):
        match = GROUP.search(text)
        if not match or match.group(1) not in set(self.groups.values()) or TIME_WORDS.search(text):
            return text, None
        group = match.group(1)
        if re.search(r'багш', text, re.I) and re.search(r'(?<!\w)хэн(?!\w)', text, re.I):
            canonical = group + ' ангийн багш хэн бэ?'
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
        name = match.group(1).strip(' ,')
        lowered = name.casefold()
        if any(lowered in office.casefold() for office in self.offices):
            return text, None
        stems = {_stem(word) for word in re.findall(r'[А-ЯӨҮЁа-яөүё]{3,}', name) if _stem(word) != 'сургу'}
        if not stems:
            return text, None
        hits = [office for office in self.offices
                if stems <= {_stem(word) for word in re.findall(r'[А-ЯӨҮЁа-яөүё]{3,}', office)}]
        if len(hits) != 1:
            return text, None
        short = hits[0].rsplit(',', 1)[-1].strip()
        if sum(short.casefold() in office.casefold() for office in self.offices) != 1:
            return text, None
        replaced = short[:1].upper() + short[1:] + ' ' + match.group(2) + match.group(3)
        return replaced, dict(rule='office_name', text=name, value=short)

    def _staff_name(self, text):
        for match in re.finditer(r'(?<![\w.])([А-ЯӨҮЁ][а-яөүё-]{2,})(?=\s+багш)', text):
            full = self.given_names.get(match.group(1).casefold())
            if full:
                return text[:match.start()] + full + text[match.end():], dict(rule='staff_name',
                    text=match.group(1), value=full)
        return text, None

    def plan(self, query):
        """Return parts to route; each keeps the visitor's original wording for the reply."""
        originals = self._split(query) if self.split_compound else [query.strip()]
        routed = self._inherit(originals) if len(originals) > 1 else list(originals)
        parts = []
        for original, text in zip(originals, routed):
            rewrites = []
            if self.class_groups:
                for rule in (self._class_group, self._class_intent, self._office):
                    text, rewrite = rule(text)
                    rewrites += [rewrite] if rewrite else []
            if self.staff_names:
                text, rewrite = self._staff_name(text)
                rewrites += [rewrite] if rewrite else []
            parts.append(dict(original=original, query=text, rewrites=rewrites))
        return dict(enabled=self.enabled, compound=len(parts) > 1, parts=parts,
                    changed=len(parts) > 1 or any(p['query'] != query.strip() for p in parts))


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
