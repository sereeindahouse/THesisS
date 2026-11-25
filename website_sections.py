"""Whole sections of the saved school pages as answers to open questions (2026-11-25).

A saved page is a small tree: the page's title, under it headings, under each heading its text. The website
path picks single sentences, which answers «how much» or «when» but not an open question such as «Hub Center
гэж юу вэ?» or «Механик инженерийн тэнхимийн оюутны үйл ажиллагааны талаар»: the visitor got one tile of a page, or
«мэдээлэл олдсонгүй», though a whole section says it (the user, 11/25: answers are too short). Here a question
that names a node of that tree is answered with the whole section in the page's own words.

It is a navigation step, not a ranking of similar text, and it is strict on purpose:

1. the question must ask for a description («… гэж юу вэ?», «…-ийн талаар», «… ямар … вэ?», «… байдаг уу?», or a
   bare name), not for a value (хэд, хэзээ, хэн, хаана …) and not whether something may be done («… болох уу?»);
2. every content word of the question must be in the section's names — page title, heading, the label printed
   above the heading, the heading it stands under. A question of four or more content words may have one of them
   in the section's text instead. So «Номын сан ямар цагаар ажилладаг вэ?» does not get the library's section;
3. the question must say at least half of the section's own heading, and a question of one word all of it; a
   section meant by the label above its heading must have that label said whole. So «Хамгаалалт байдаг уу?» is
   not «Хүүхэд хамгааллын ажил», and «Механик инженерийн тэнхимийн талаар» names a page, not one of its sections
   (the stored overview answers that);
4. of the sections that pass, the one whose own name the question says most fully is meant; when sections of two
   pages are equally named the question does not say which, and nothing is shown. A page of the site itself is
   preferred to a news item about the same thing.

Two words are the same word when both the keys of their stems and the words as written agree (same_word below):
«газрын» meets «газар», but «зөвлөгөө» is not «зөвлөл». Nothing is generated, and every question this step does
not match is left as it was.

The sections are cut by tools/build_website_sections.py from the saved HTML (its heading tags) and stored in
runtime/website-sections.json (not in Git: it is the school's page text) with the corpus ID they were cut from;
a file cut from another corpus is not used.
"""
from dataclasses import dataclass
import json
from pathlib import Path
import re
import unicodedata

from mongolian_morphology import light_stem

SECTIONS_PATH = 'runtime/website-sections.json'
MAX_ANSWER_CHARS = 1400
# Words that say nothing about which section is meant: question words, courtesy, the school's own name.
_GENERIC = frozenset('''юу вэ бэ уу үү юм ямар яаж хэрхэн хэн хаана хэзээ хэд хэдэн аль гэж гэдэг гэсэн нь бол болох болно болдог
    байдаг байна байгаа байх бий талаар тухай хэлж хэлнэ хэлээч өгөөч өгнө өгөх танилцуулна танилцуулаач танилцуулга
    мэдээлэл мэдээллийг дэлгэрэнгүй товч тайлбарлана тайлбарлаж манай танай танайх энэ тэр ба болон мөн эсвэл их маш
    сургууль сургуулийн сургуульд сургуулиас шмтк коллеж коллежийн шинэ монгол технологийн nmct та би надад бидэнд
    уучлаарай сайн хийдэг хийх авах хэрэгтэй зэрэг гэх мэт үзье харуулна харуулаач уна юү'''.split())
# The forms of a question that asks what something is, what there is, or to be told about it.
_DESCRIBE = re.compile(
    r'(?:гэж|гэдэг|гэдэг\s+нь)\s+юу|(?<!\w)юу\s+(?:вэ|бэ|хийдэг|байдаг|юм)|(?<!\w)ямар(?!\w)|талаар|тухай|танилцуул|'
    r'(?<!\w)(?:байдаг|байгаа|байна|бий)\s+(?:уу|юу|юү|үү)(?!\w)')
_ASKS = re.compile(r'(?<!\w)(?:уу|үү|юу|юү|вэ|бэ)\s*[?.!]*\s*$|\?')
# A value is asked for: the website path and its typed checks answer that, not a section.
_VALUE = re.compile(r'(?<!\w)(?:хэд|хэдэн|хэддүгээр|хэдий|хэдийд|хэзээ|хэн|хэнд|хэнтэй|хэнээс|хаана|хаашаа|хаанаас|аль|яаж|хэрхэн)(?!\w)|'
                    r'утас|мэйл|шуудан|(?<!\w)хаяг|дугаар|\d')
_WHAT = re.compile(r'(?:гэж|гэдэг|гэдэг\s+нь)\s+юу|талаар|тухай|танилцуул')
_NEWS = re.compile(r'/(?:news|events)/')
_VOWELS = frozenset('аэиоуөүяеёюыaeiouy')


@dataclass(frozen=True)
class Section:
    url: str
    version: int
    title: str
    heading: str
    text: str
    retrieved_at: str = ''
    label: str = ''      # the small label printed above the heading («ЯПОНД АЖИЛД ОРОХ ЗАМ»)
    parent: str = ''     # the heading this one stands under


def _words(text):
    return re.findall(r'[^\W\d_]{2,}', unicodedata.normalize('NFC', text or '').casefold())


def _skeleton(text):
    """The first two letters, then the consonants: a vowel falls out before an ending («газар» / «газрын»)."""
    return text[:2] + ''.join(letter for letter in text[2:] if letter not in _VOWELS)


def stem(word):
    """What a word is compared by: (key of its light stem, skeleton of the word as written)."""
    word = word.casefold()
    return _skeleton(light_stem(word))[:6], _skeleton(word)


def same_word(one, other):
    """Two forms of one word. The stem keys must be equal or, from four letters on, one must open the other
    («дадл» from «дадлагын», «дадлг» from «дадлага»; «үйл» is not «үйлдвэр»). And the words as written must
    agree the same way, because the stemmer also cuts what is no ending: «зөвлөгөө» and «зөвлөл» share the
    stem key «зөвл», but «зөвлг» and «зөвлл» do not open one another (code review, 11/25)."""
    key, other_key = one[0], other[0]
    if key != other_key and not (len(key) >= 4 and len(other_key) >= 4
                                 and (key.startswith(other_key) or other_key.startswith(key))):
        return False
    return one[1].startswith(other[1]) or other[1].startswith(one[1])


def content_stems(text):
    """What the words that name something are compared by (see stem), in order, each once."""
    return list(dict.fromkeys(stem(word) for word in _words(text) if word not in _GENERIC))


def _held(term, keys):
    return term in keys or any(same_word(term, key) for key in keys)


def _said(keys, wanted):
    """How much of a name (its keys) the question's words say, from 0 to 1."""
    return sum(_held(key, wanted) for key in keys) / len(keys) if keys else 0.0


def describes(query):
    """Whether the question asks what something is or to be told about it (or is a bare name)."""
    text = unicodedata.normalize('NFC', query or '').casefold()
    if _VALUE.search(text):
        return False
    return _DESCRIBE.search(text) is not None or _ASKS.search(text) is None


def asks_what(query):
    """«… гэж юу вэ?», «…-ийн талаар», «…-ийн тухай», or a bare name: the question is the name of a thing and
    nothing else. («… байдаг уу?» and «… ямар … вэ?» describe too, but a stored answer often answers them
    more directly — «Тийм. …».)"""
    text = unicodedata.normalize('NFC', query or '').casefold()
    return describes(query) and (_WHAT.search(text) is not None or _ASKS.search(text) is None)


class SectionIndex:
    def __init__(self, sections=(), corpus_id=None):
        self.sections, self.corpus_id = list(sections), corpus_id
        self._heading = [frozenset(content_stems(section.heading)) for section in self.sections]
        self._label = [frozenset(content_stems(section.label)) for section in self.sections]
        self._names = [heading | label | frozenset(content_stems(section.title + ' ' + section.parent))
                       for heading, label, section in zip(self._heading, self._label, self.sections)]
        self._body = [frozenset(content_stems(section.text)) for section in self.sections]

    def __bool__(self):
        return bool(self.sections)

    @classmethod
    def from_file(cls, root, corpus_id=None):
        """The stored sections, when they were cut from the corpus now served (``corpus_id``); otherwise none."""
        try:
            data = json.loads((Path(root) / SECTIONS_PATH).read_text(encoding='utf-8'))
            if data.get('schema_version') != 1 or (corpus_id is not None and data.get('corpus_id') != corpus_id):
                return cls()
            return cls([Section(**item) for item in data['sections']], data.get('corpus_id'))
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            return cls()

    def find(self, query):
        """The one section a describing question names, with why; None when it names none, or several pages'."""
        terms = content_stems(query)
        if not self.sections or not 1 <= len(terms) <= 8 or not describes(query):
            return None
        wanted, passed = frozenset(terms), []
        for index, section in enumerate(self.sections):
            names = self._names[index]
            outside = [term for term in terms if not _held(term, names)]
            if outside and (len(terms) < 4 or len(outside) > 1 or not _held(outside[0], self._body[index])):
                continue
            # How fully the question says the section's own name: its heading, or the whole label above it.
            said = max(_said(self._heading[index], wanted),
                       1.0 if self._label[index] and _said(self._label[index], wanted) == 1.0 else 0.0)
            if said < (1.0 if len(terms) == 1 else 0.5):
                continue
            passed.append((said, not outside, -len(section.text), -index))
        if not passed:
            return None
        passed.sort(reverse=True)
        best = passed[0]
        rivals = [row for row in passed if row[:2] == best[:2]]
        standing = [row for row in rivals if not _NEWS.search(self.sections[-row[3]].url)]
        if standing and len(standing) < len(rivals):
            best, rivals = standing[0], standing
        section = self.sections[-best[3]]
        if any(self.sections[-row[3]].url != section.url for row in rivals):
            return None
        return dict(section=section, terms=terms, said=round(best[0], 2), all_named=best[1], candidates=len(passed),
                    news=_NEWS.search(section.url) is not None, whole=len(section.text) <= MAX_ANSWER_CHARS,
                    intro=section.heading.casefold() == section.title.casefold())


def section_text(section, limit=MAX_ANSWER_CHARS):
    """The section as shown: its name and its page, then its text; a long text is cut at a line's end."""
    same = section.heading.casefold() == section.title.casefold()
    place = section.title if same else section.heading + ' (' + section.title + ')'
    body = section.text
    if len(body) > limit:
        cut = body.rfind('\n', 0, limit)
        body = body[:cut if cut > limit // 2 else limit].rstrip() + '\n…'
    return place + '\n' + body


def holds(section, text):
    """Whether every line of ``text`` that says something stands in the section word for word."""
    flat = ' '.join(section.text.split()).casefold()
    lines = [' '.join(line.strip(' •-–').split()).casefold() for line in str(text or '').split('\n')]
    lines = [line for line in lines if len(line) >= 20]
    return bool(lines) and all(line in flat for line in lines)
