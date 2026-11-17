"""Mongolian (Cyrillic) term conflation for one extra BM25 ranking channel.

Two published, language-light options are offered, both ranking-only:

* ``light``  — inflectional suffix stripping (case, reflexive-possessive,
  plural, frequent verb endings), in the spirit of light stemmers that remove
  only frequent inflections (Savoy 2006; Larkey et al. 2002) and of the
  dictionary-free Mongolian noun lemmatizer (Khaltar & Fujii 2008). No vowel
  re-insertion: the same surface stem is produced for query and passage, so
  «ажлаа» and «ажлаар» meet at «ажл» even though that is not a dictionary word.
* ``prefix<N>`` — keep the first N letters of each word (Can et al. 2008 F5;
  Dolamic & Savoy 2010 trunc-4).
* ``light+prefix<N>`` — the light stem, then truncated.

The output feeds a separate lexical ranking that is fused with the existing
rankings. It never changes ``search_terms``, the anchor gate, the evidence
text or any answer guard.
"""
import re
import unicodedata

# Longest first within each group; every group is tried once per pass.
REFLEXIVE = ('гаа', 'гээ', 'гоо', 'гөө', 'аа', 'ээ', 'оо', 'өө')
CASES = (
    'уудаар', 'үүдээр', 'уудаас', 'үүдээс', 'уудын', 'үүдийн',
    'гаар', 'гээр', 'гоор', 'гөөр', 'гаас', 'гээс', 'гоос', 'гөөс', 'гийн',
    'наас', 'нээс', 'ноос', 'нөөс',
    'аар', 'ээр', 'оор', 'өөр', 'аас', 'ээс', 'оос', 'өөс',
    'тай', 'тэй', 'той', 'руу', 'рүү', 'луу', 'лүү',
    'ийнх', 'ынх', 'ийн', 'ийг', 'ын', 'ыг', 'нд', 'ны',
)
PLURALS = ('нууд', 'нүүд', 'чууд', 'чүүд', 'ууд', 'үүд', 'нар')
# Converbs «-хад/-хэд» also end common nouns («хүүхэд»), so they need a longer stem.
CONVERBS = ('хдаа', 'хдээ', 'хдоо', 'хдөө', 'хад', 'хэд', 'ход', 'хөд')
VERBS = (
    'даг', 'дэг', 'дог', 'дөг', 'сан', 'сэн', 'сон', 'сөн',
    'вал', 'вэл', 'вол', 'бал', 'бэл', 'бол',
    'аад', 'ээд', 'оод', 'өөд', 'на', 'нэ', 'но', 'нө', 'ж', 'ч', 'х',
)
# One-letter endings (dative -д/-т, accusative -г, genitive -н) are frequent
# word-final letters too, so they need a longer remaining stem.
SINGLE = ('д', 'т', 'г', 'н')
MIN_STEM = 3
MIN_STEM_SINGLE = 4
_CYRILLIC_WORD = re.compile(r'[а-яёөү]+')


def light_stem(token):
    """Strip at most one suffix per group: reflexive → case → plural → verb."""
    if not _CYRILLIC_WORD.fullmatch(token):
        return token
    for group in (REFLEXIVE, CASES, PLURALS, CONVERBS, VERBS, SINGLE):
        limit = MIN_STEM_SINGLE if group in (SINGLE, CONVERBS) else MIN_STEM
        for suffix in group:
            if token.endswith(suffix) and len(token) - len(suffix) >= limit:
                token = token[:-len(suffix)]
                break
    return token


def conflate(token, method):
    if method == 'light':
        return light_stem(token)
    match = re.fullmatch(r'(light\+)?prefix(\d)', method or '')
    if not match:
        raise ValueError('Unknown morphology method.')
    if match[1]:
        token = light_stem(token)
    return token[:int(match[2])]


def morph_terms(text, method, stopwords=frozenset()):
    tokens = re.findall(r'\w+', unicodedata.normalize('NFC', text).casefold())
    return [conflate(token, method) for token in tokens
            if token not in stopwords and (len(token) > 1 or token.isdigit())]
