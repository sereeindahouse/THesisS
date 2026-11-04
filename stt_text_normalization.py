"""Optional, conservative search-only normalization of STT text.

Pure text processing: no provider, audio, model, transcript storage or scoring.
The 2000--2099 grammar follows tools.compare_stt_vocabulary.spoken_year, without
importing the evaluation runner and its transport dependencies.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

CONFIG_PATH = 'config/stt-text-normalization.json'
VOCABULARY_PATH = 'config/stt-vocabulary.json'
MAX_TEXT = 2000
MAX_TERMS = 1000
MAX_TERM = 160
MIN_FUZZY_TOKEN = 8
MIN_SIMILARITY = .90
_WORDS = re.compile(r'[^\W\d_]+|\d+', re.UNICODE)
_PROTECTED = re.compile(r'https?://\S+|\b[\w.+-]+@[\w.-]+\.[\w.-]+|`[^`]*`', re.I)
_ONES = dict(тэг=0, нэг=1, нэгэн=1, хоёр=2, гурав=3, гурван=3, дөрөв=4,
             дөрвөн=4, тав=5, таван=5, зургаа=6, зургаан=6, долоо=7,
             долоон=7, найм=8, найман=8, ес=9, есөн=9)
_TENS = dict(арав=10, арван=10, хорь=20, хорин=20, гуч=30, гучин=30,
             дөч=40, дөчин=40, тавь=50, тавин=50, жар=60, жаран=60,
             дал=70, далан=70, ная=80, наян=80, ер=90, ерэн=90)
_HUNDREDS = {'зуу', 'зуун'}
_THOUSANDS = {'мянга', 'мянган'}
_NUMBER_WORDS = set(_ONES) | set(_TENS) | _HUNDREDS | _THOUSANDS
_NUMBER_CONTEXT = re.compile(r'^(?:он|оны|онд|жил|жилийн|багш|багштай|оюутан|оюутантай|'
                             r'хүн|хүнтэй|өрөө|өрөөний|давхар|давхарт|төгрөг|кредит|цаг|'
                             r'минут|секунд|хувь|ширхэг|бүлэг|дугаар|ангитай|анги)$', re.I)
_NUMBER_ENDINGS = ('ы', 'ий', 'ын', 'ийн', 'ны', 'ний', 'д', 'нд', 'г', 'ыг', 'ийг',
                   'аас', 'ээс', 'оос', 'өөс', 'дугаар', 'дүгээр')


def _unsupported_number_continuation(word):
    """Do not normalize a valid prefix of an inflected number phrase."""
    return any(word == base + ending for base in _NUMBER_WORDS for ending in _NUMBER_ENDINGS)


def _small_number(words):
    if len(words) == 1:
        return _ONES.get(words[0], _TENS.get(words[0]))
    if len(words) == 2 and words[0] in _TENS and words[1] in _ONES and _ONES[words[1]]:
        return _TENS[words[0]] + _ONES[words[1]]
    return None


def _below_thousand(words):
    if not words:
        return 0
    positions = [i for i, word in enumerate(words) if word in _HUNDREDS]
    if not positions:
        return _small_number(words)
    if len(positions) != 1:
        return None
    position = positions[0]
    if position == 0:
        multiplier = 1
    elif position == 1 and words[0] in _ONES and _ONES[words[0]]:
        multiplier = _ONES[words[0]]
    else:
        return None
    rest = words[position + 1:]
    remainder = _small_number(rest) if rest else 0
    return None if remainder is None else multiplier * 100 + remainder


def spoken_integer(words):
    """Return a plain 0--999999 integer, or None for an ambiguous/invalid run."""
    if not words or any(word not in _NUMBER_WORDS for word in words):
        return None
    positions = [i for i, word in enumerate(words) if word in _THOUSANDS]
    if not positions:
        return _below_thousand(words)
    if len(positions) != 1:
        return None
    position = positions[0]
    high = _below_thousand(words[:position]) if position else 1
    low = _below_thousand(words[position + 1:])
    if high is None or high == 0 or low is None:
        return None
    return high * 1000 + low


def _one_edit(a, b):
    """True only for one insertion/deletion/substitution (not transpositions)."""
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    if len(a) > len(b):
        a, b = b, a
    index = 0
    while index < len(a) and a[index] == b[index]:
        index += 1
    # A trailing letter is often an inflection rather than a typo. Do not
    # erase a case ending or add a missing case ending on that evidence alone.
    if index == 0 or index == len(a):
        return False
    return a[index:] == b[index + 1:]


def _read_json(root, relative, size):
    path = (root / relative).resolve(strict=True)
    if not path.is_relative_to(root) or path.stat().st_size > size:
        raise ValueError('Configuration path or size is invalid.')
    with path.open('rb') as stream:
        raw = stream.read(size + 1)
    if len(raw) > size:
        raise ValueError('Configuration exceeds its bound.')
    return json.loads(raw.decode('utf-8-sig'))


class Normalizer:
    """A loaded configuration; disabled by default and safe for repeated calls."""

    def __init__(self, *, enabled=False, terms=(), normalize_numbers=True,
                 normalize_vocabulary=True, reason='disabled'):
        if any(type(value) is not bool for value in
               (enabled, normalize_numbers, normalize_vocabulary)):
            raise ValueError('Normalizer options must be booleans.')
        if not isinstance(terms, (list, tuple)) or len(terms) > MAX_TERMS:
            raise ValueError('Invalid vocabulary.')
        self.enabled = enabled
        self.normalize_numbers = normalize_numbers
        self.normalize_vocabulary = normalize_vocabulary
        self.reason = 'enabled' if enabled else reason
        self._terms = []
        seen = set()
        for term in terms:
            if (not isinstance(term, str) or not term.strip() or len(term) > MAX_TERM
                    or any(ord(c) < 32 for c in term)):
                raise ValueError('Vocabulary terms must be bounded plain text.')
            term_words = tuple(match.group().casefold() for match in _WORDS.finditer(term))
            # Number-only and punctuated terms (initials, codes, academic ranges)
            # are not fuzzy targets; their exact occurrence is left untouched.
            if (not term_words or any(word.isdigit() for word in term_words)
                    or re.fullmatch(r'[^\W\d_]+(?: +[^\W\d_]+)*', term, re.UNICODE) is None):
                continue
            key = term.casefold()
            if key in seen:
                continue
            seen.add(key)
            self._terms.append((term, term_words))
        self._terms.sort(key=lambda item: (-len(item[1]), item[0]))

    @classmethod
    def from_config(cls, root):
        """Load only the two fixed config files; invalid/missing settings stay OFF."""
        try:
            root = Path(root).resolve()
            data = _read_json(root, CONFIG_PATH, 16 * 1024)
            allowed = {'schema_version', 'enabled', 'normalize_numbers', 'normalize_vocabulary', 'purpose_mn'}
            if (not isinstance(data, dict) or set(data) - allowed
                    or type(data.get('schema_version')) is not int or data['schema_version'] != 1
                    or type(data.get('enabled')) is not bool
                    or any(type(data.get(k, True)) is not bool for k in ('normalize_numbers', 'normalize_vocabulary'))):
                raise ValueError('Invalid normalization settings.')
            if data['enabled'] is False:
                return cls(reason='disabled')
            terms = ()
            if data.get('normalize_vocabulary', True):
                vocabulary = _read_json(root, VOCABULARY_PATH, 256 * 1024)
                if not isinstance(vocabulary, dict) or not isinstance(vocabulary.get('terms'), list):
                    raise ValueError('Invalid vocabulary settings.')
                terms = vocabulary['terms']
            return cls(enabled=True, terms=terms,
                       normalize_numbers=data.get('normalize_numbers', True),
                       normalize_vocabulary=data.get('normalize_vocabulary', True))
        except (OSError, ValueError, TypeError, KeyError, UnicodeError):
            return cls(reason='configuration_missing_or_invalid')

    def normalize(self, text):
        """Keep the exact original and a search derivative with original offsets."""
        if not isinstance(text, str):
            raise TypeError('STT text must be a string.')
        result = dict(enabled=self.enabled, original_text=text, normalized_search_text=text,
                      changed=False, replacements=[], reason=self.reason)
        if not self.enabled or not text or len(text) > MAX_TEXT:
            if self.enabled and len(text) > MAX_TEXT:
                result['reason'] = 'text_exceeds_bound'
            return result
        protected = [(match.start(), match.end()) for match in _PROTECTED.finditer(text)]
        tokens = list(_WORDS.finditer(text))
        replacements = []
        used = set()

        def available(start, end):
            return not any(start < right and end > left for left, right in protected)

        if self.normalize_numbers:
            index = 0
            while index < len(tokens):
                token = tokens[index]
                if token.group().casefold() not in _NUMBER_WORDS:
                    index += 1
                    continue
                stop = index + 1
                while (stop < len(tokens) and text[tokens[stop-1].end():tokens[stop].start()].isspace()
                       and (tokens[stop].group().casefold() in _NUMBER_WORDS or tokens[stop].group().isdigit())):
                    stop += 1
                words = [value.group().casefold() for value in tokens[index:stop]]
                number = spoken_integer(words)
                start, end = token.start(), tokens[stop-1].end()
                context = (stop < len(tokens) and text[end:tokens[stop].start()].isspace()
                           and _NUMBER_CONTEXT.fullmatch(tokens[stop].group()))
                inflected_tail = (stop < len(tokens) and text[end:tokens[stop].start()].isspace()
                                  and _unsupported_number_continuation(tokens[stop].group().casefold()))
                # Single words can be indefinite pronouns/adjectives. Require a
                # quantity noun; a multiword run must form one complete integer.
                if (number is not None and not inflected_tail and (stop-index > 1 or context)
                        and available(start, end)):
                    # Hyphen/decimal/identifier adjacency is not a plain integer.
                    if not ((start and (text[start-1].isalnum() or text[start-1] in '_./:-'))
                            or (end < len(text) and (text[end].isalnum() or text[end] in '_./:-'))):
                        replacements.append(dict(start=start, end=end, original=text[start:end],
                                                 replacement=str(number), kind='number'))
                        used.update(range(index, stop))
                index = stop
        if self.normalize_vocabulary:
            index = 0
            while index < len(tokens):
                candidates = []
                exact = False
                for canonical, term_words in self._terms:
                    stop = index + len(term_words)
                    if stop > len(tokens) or any(i in used for i in range(index, stop)):
                        continue
                    span = tokens[index:stop]
                    if any(not text[left.end():right.start()].isspace() for left, right in zip(span, span[1:])):
                        continue
                    actual = tuple(value.group().casefold() for value in span)
                    if actual == term_words:
                        exact = True
                        continue
                    changed = [i for i, (a, b) in enumerate(zip(actual, term_words)) if a != b]
                    if len(changed) != 1:
                        continue
                    a, b = actual[changed[0]], term_words[changed[0]]
                    if (min(len(a), len(b)) < MIN_FUZZY_TOKEN
                            or 1 - 1 / max(len(a), len(b)) < MIN_SIMILARITY
                            or not _one_edit(a, b)):
                        continue
                    start, end = span[0].start(), span[-1].end()
                    if available(start, end):
                        candidates.append((start, end, canonical))
                # Any exact configured term at this position or multiple close
                # interpretations wins over correction: abstain instead of guess.
                unique = set(candidates)
                if not exact and len(unique) == 1:
                    start, end, canonical = unique.pop()
                    replacements.append(dict(start=start, end=end, original=text[start:end],
                                             replacement=canonical, kind='vocabulary'))
                    while index < len(tokens) and tokens[index].start() < end:
                        index += 1
                else:
                    index += 1
        replacements.sort(key=lambda item: item['start'])
        output, position = [], 0
        for replacement in replacements:
            output.extend((text[position:replacement['start']], replacement['replacement']))
            position = replacement['end']
        output.append(text[position:])
        result.update(normalized_search_text=''.join(output), replacements=replacements,
                      changed=bool(replacements))
        return result
