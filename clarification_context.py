"""One-shot clarification capabilities for explicit, bounded D-route choices.

This is deterministic reply selection, not LLM chat memory. Only choices already
offered by the server may resolve a reply; school data remains read-only.
"""
from collections import OrderedDict
import re
import secrets
import threading
import time
import unicodedata


ID_RE = re.compile(r"[0-9a-f]{32}")
YEAR_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")

# Exact small vocabularies select an existing choice. A word is accepted only
# when it maps to one choice, never to the highest-scoring or nearest choice.
CATEGORIES = (
    (r"элсэлтийн", ("элсэлт", "элсэлтийн", "элсэлтийнх", "элсэлтийн бүртгэл")),
    (r"олимпиадын", ("олимпиад", "олимпиадын", "олимпиадынх", "олимпиадын бүртгэл")),
    (r"бичгийн", ("бичгийн", "бичгийнх", "бичгийн шалгалт")),
    (r"ярилцлаг", ("ярилцлага", "ярилцлагын", "ярилцлагынх", "ярилцлагын шалгалт")),
    (r"механик инженер", ("механик", "механикийн", "механик инженер", "механик инженерийн")),
    (r"химийн инженер", ("химийн", "химийнх", "химийн инженер", "химийн инженерийн")),
    (r"математик-физикийн", ("математик-физик", "математик физик", "физикийн", "физикийнх")),
    (r"математик-хими-биологийн", ("математик-хими-биологи", "математик хими биологи", "хими-биологийн")),
    (r"баримт", ("баримт", "баримтын", "баримт бичиг", "баримт бичгийн")),
    (r"хаана", ("байршил", "байршлын", "байршлынх", "хаана")),
    (r"мэргэжлээр|хөтөлбөр", ("мэргэжил", "мэргэжлийн", "хөтөлбөр", "хөтөлбөрийн")),
    (r"холбоо барих|холбоо", ("холбоо", "холбоо барих", "утас")),
)
CONSTRAINT_PATTERNS = (
    r"механик", r"химийн инженер", r"компьютер", r"цахилгаан", r"барилг",
    r"физик", r"биологи", r"ярилцлаг", r"бичгийн", r"элсэлтийн алб",
)
UNSAFE_CONSTRAINT_RE = re.compile(
    r"\b\w+гүй\b|\b(?:биш|үгүй|бол|тохиолдолд|зөвхөн|бусад|өөр)\b", re.IGNORECASE)
QUESTION_FILLERS = frozenset("""юу вэ бэ хэд хэдэн ямар аль уу үү нь юм байна байгаа
мэдээлэл мэдээллийг тухай талаар хэлнэ хэлээч хэлж өгөөч өгнө өгч надад
оны онд он сургуулийн танай хэр""".split())
CONCEPT_WORDS = {"удаан": "duration", "хугацаа": "duration", "хугацааны": "duration",
                 "үргэлжилдэг": "duration", "үргэлжлэх": "duration",
                 "үргэлжилнэ": "duration", "үргэлжлэдэг": "duration"}
WORD_FORMS = {
    "бүртгэлийн": "бүртгэл", "бүртгэх": "бүртгэл",
    "хураамжийн": "хураамж", "хураамч": "хураамж",
    "төлбөрийн": "төлбөр", "шалгалтын": "шалгалт", "шалгалтад": "шалгалт",
    "элсэлтийн": "элсэлт", "олимпиадын": "олимпиад", "олимпиадад": "олимпиад",
    "ярилцлагын": "ярилцлага", "гадаадад": "гадаад", "баримтаа": "баримт",
    "баримтын": "баримт", "инженерийн": "инженер",
}


def _substantive_words(text):
    """Finite word forms, with unknown qualifiers retained conservatively."""
    text = YEAR_RE.sub("", text.casefold())
    words = {WORD_FORMS.get(word, word) for word in re.findall(r"[^\W\d_]+", text)
             if word not in QUESTION_FILLERS}
    for word, concept in CONCEPT_WORDS.items():
        if word in words:
            words.remove(word)
            words.add("concept_" + concept)
    if "минут" in words:
        words.add("concept_duration")
    if "бүртгэл" in words and "төлбөр" in words:
        words.remove("төлбөр")
        words.add("хураамж")
    return words


class ClarificationConflict(ValueError):
    """A valid-looking capability no longer matches its server-side context."""


def _key(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split()).rstrip(" ?!.")


def _pin_constraints(original, option):
    """Keep supplied dates; reject choices that erase other explicit constraints."""
    if UNSAFE_CONSTRAINT_RE.search(original):
        return None
    original_years = set(YEAR_RE.findall(original))
    option_years = set(YEAR_RE.findall(option))
    if original_years and option_years and original_years != option_years:
        return None
    numbers = set(re.findall(r"\d+(?:[.,]\d+)*", original)) - original_years
    if not numbers <= set(re.findall(r"\d+(?:[.,]\d+)*", option)):
        return None
    latin = set(re.findall(r"[a-z][a-z0-9]*", original.casefold()))
    if not latin <= set(re.findall(r"[a-z][a-z0-9]*", option.casefold())):
        return None
    for pattern in CONSTRAINT_PATTERNS:
        if re.search(pattern, original.casefold()) and not re.search(pattern, option.casefold()):
            return None
    # Do not silently erase a qualifier merely because it was not among the
    # known category/number guards above (period, relative year, citizenship,
    # programme name, condition, etc.). Unknown words fail closed; only the
    # finite question fillers/forms above may differ from an offered choice.
    if not _substantive_words(original) <= _substantive_words(option):
        return None
    if original_years and not option_years:
        # Retain range punctuation/order rather than replacing supplied dates.
        dates = re.findall(r"(?:19|20)\d{2}(?:\s*[–—-]\s*(?:19|20)\d{2})?", original)
        option = ", ".join(dates) + " оны " + option
    return option if len(option) <= 1000 else None


def _choices(result):
    original = result["query"]
    offered = list(result.get("suggestions") or [])
    clarification = result.get("clarification") or {}
    if isinstance(clarification, dict) and clarification.get('kind') == 'missing_cooperation_entity':
        # Select only an explicitly offered partner. Append its identity to the
        # full original request: a canonical FAQ must not erase month/platform,
        # a supplied year, unknown qualifiers, or the uncorrected STT wording.
        aliases = {'Sakura Internet': ('Sakura Internet', 'Sakura', 'Сакура'),
                   'ARC': ('ARC',), 'StoD': ('StoD',)}
        if (not original.strip() or len(original) > 900
                or re.search(r'хамтын\s+ажиллагааны\s+байгууллага\s*:', original, re.I)
                or any(re.search(r'(?<!\w)' + re.escape(alias) + r'(?!\w)', original, re.I)
                       for values in aliases.values() for alias in values)):
            return {}
        mappings = {}
        for option in clarification.get('options', [])[:12]:
            if not isinstance(option, dict):
                continue
            entity, label = option.get('entity'), option.get('question')
            if entity not in aliases or not isinstance(label, str) or not 1 <= len(label) <= 200:
                continue
            if not any(re.search(r'(?<!\w)' + re.escape(alias) + r'(?!\w)', label, re.I)
                       for alias in aliases[entity]):
                continue
            resolved = original + '\nХамтын ажиллагааны байгууллага: ' + entity
            if len(resolved) > 1000:
                continue
            for reply in (label, *aliases[entity]):
                mappings.setdefault(_key(reply), set()).add(resolved)
        return {reply: next(iter(queries)) for reply, queries in mappings.items() if len(queries) == 1}
    if isinstance(clarification, dict):
        offered.extend(item.get("question") for item in clarification.get("options", [])
                       if isinstance(item, dict))
    mappings = {}

    def add(reply, query):
        mappings.setdefault(_key(reply), set()).add(query)

    for option in offered[:12]:
        if not isinstance(option, str) or not option.strip() or len(option) > 1000:
            continue
        option = option.strip()
        resolved = _pin_constraints(original, option)
        if resolved is None:
            continue
        add(option, resolved)
        # A short category cannot silently supply a new year. A user can still
        # choose the full dated option, or explicitly reply with a listed year.
        if set(YEAR_RE.findall(option)) - set(YEAR_RE.findall(original)):
            continue
        for pattern, aliases in CATEGORIES:
            if re.search(pattern, option.casefold()):
                for alias in aliases:
                    add(alias, resolved)

    if (isinstance(clarification, dict) and clarification.get("kind") == "missing_year"
            and not UNSAFE_CONSTRAINT_RE.search(original)):
        years = clarification.get("supported_years", [])
        years = sorted({year for year in years if isinstance(year, str) and YEAR_RE.fullmatch(year)})
        # Missing-year routing supports only literal base questions; use that
        # original question rather than broadening to a suggested question.
        if years and not YEAR_RE.search(original):
            for year in years:
                for ending in ("", " оны", " онд", " хичээлийн жил", " хичээлийн жилийн"):
                    add(year + ending, year + " оны " + original)
            if len(years) == 2 and int(years[0]) < int(years[1]):
                for dash in ("–", "—", "-"):
                    year_range = dash.join(years)
                    for ending in ("", " оны", " хичээлийн жил", " хичээлийн жилийн"):
                        add(year_range + ending, year_range + " оны " + original)
    return {reply: next(iter(queries)) for reply, queries in mappings.items()
            if len(queries) == 1}


class ClarificationContext:
    """Bounded, thread-safe in-memory cache; nothing persists across restarts."""
    def __init__(self, *, ttl_seconds=300, max_entries=64, clock=time.monotonic):
        if not 0 < ttl_seconds <= 300 or not 1 <= max_entries <= 64:
            raise ValueError("Clarification cache bounds are invalid.")
        self.ttl_seconds, self.max_entries, self.clock = ttl_seconds, max_entries, clock
        self._entries = OrderedDict()
        self._lock = threading.Lock()

    def status(self):
        return dict(enabled=True, mode="bounded_explicit_d_reply", ttl_seconds=self.ttl_seconds,
                    max_entries=self.max_entries, persisted=False, one_shot=True,
                    llm_memory=False, database_modified=False, training_performed=False,
                    timing_scope="conversation.context_latency_ms excludes rag.route and HTTP transfer")

    def _prune(self):
        cutoff = self.clock() - self.ttl_seconds
        for token, entry in list(self._entries.items()):
            if entry["issued_at"] <= cutoff:
                del self._entries[token]

    def issue(self, result, *, allow_draft=False):
        if (result.get("route") != "D" or result.get("answer")
                or not isinstance(result.get("query"), str)
                or not isinstance(result.get("package_id"), str)):
            return None
        choices = _choices(result)
        if not choices:
            return None
        token = secrets.token_hex(16)
        entry = dict(query=result["query"], package_id=result["package_id"],
                     corpus_id=(result.get("rag") or {}).get("corpus_id"),
                     allow_draft=allow_draft, choices=choices, issued_at=self.clock())
        with self._lock:
            self._prune()
            self._entries[token] = entry
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
        return token

    def resolve(self, token, raw_query, *, allow_draft, package_id, corpus_id=None):
        if not isinstance(token, str) or not ID_RE.fullmatch(token):
            raise ValueError("Тодруулгын ID буруу.")
        with self._lock:
            self._prune()
            entry = self._entries.pop(token, None)
        if entry is None:
            raise ClarificationConflict("Тодруулгын хугацаа дууссан эсвэл хэрэглэгдсэн. Бүтэн асуултаа дахин илгээнэ үү.")
        if (entry["allow_draft"] != allow_draft or entry["package_id"] != package_id
                or entry["corpus_id"] is not None and entry["corpus_id"] != corpus_id):
            raise ClarificationConflict("Тодруулгын эх эсвэл горим өөрчлөгдлөө. Бүтэн асуултаа дахин илгээнэ үү.")
        resolved = entry["choices"].get(_key(raw_query))
        return dict(raw_query=raw_query, resolved_query=resolved or raw_query,
                    applied=resolved is not None,
                    reason="supported_reply" if resolved is not None else "unrecognized_reply",
                    clarification_id=None)

    def reset(self, tokens):
        if (not isinstance(tokens, list) or len(tokens) > 64 or any(
                not isinstance(token, str) or not ID_RE.fullmatch(token) for token in tokens)):
            raise ValueError("clarification_ids нь 64 хүртэлх хүчинтэй ID-гийн жагсаалт байна.")
        removed = 0
        with self._lock:
            self._prune()
            for token in tokens:
                removed += int(self._entries.pop(token, None) is not None)
        return dict(removed=removed)
