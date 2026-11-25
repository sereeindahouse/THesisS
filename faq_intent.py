"""Map a visitor's own wording to one stored FAQ (2026-11-23).

The FAQ router (question_router.py) answers only a stored question or alias word for word. People ask the
same thing their own way («Манай хүү энэ жил 9-р анги төгсөнө, танай сургуульд орж болох уу?» for the stored
«…1-р курст ямар анги төгссөн сурагч бүртгүүлэх вэ?»), and such questions fell through to the website
search, which refused most of them (the user, 11/23: the answers are too short and useless; 2 of 20 school
questions of the check set were answered). This layer maps a question to ONE stored FAQ; the router then
answers that FAQ's own question, so every FAQ guard (acceptance, validity, year) still decides.

A match needs all of:
  1. the intent's concept words (config/faq-intents.json): each `require` group has a word in the question
     (a word beginning with the stem, or the phrase), and no `exclude` stem or phrase is in it;
  2. the question's years and other numbers in the FAQ's own text (or the intent's `allow_numbers`), so
     «2027 оны төлбөр» is never mapped to the 2026 fee;
  3. with the encoder, a close meaning: the multilingual E5 cosine of the question and the FAQ's question,
     aliases or examples is at least `threshold`. Without the encoder only a single gated intent maps.
Nothing is generated: the visitor sees the stored answer, and the stored question it answers stays with the
result (`understood_as`, `faq_intent`) for the audit; the page does not show it (answer_presentation.present).
"""
import json
import re
import threading
from pathlib import Path

from answer_types import value_supported

CONFIG_PATH = 'config/faq-intents.json'
_YEAR = re.compile(r'(?<!\d)(?:19|20)\d{2}(?!\d)')
_NUMBER = re.compile(r'(?<!\d)\d+(?!\d)')
_WORD = re.compile(r'[^\W_]+')


def _flat(text):
    return ' '.join(re.sub(r'[^\w\s%-]', ' ', str(text or '').casefold()).split())


def _has(term, words, flat):
    """A stem begins a word («төгс» -> «төгсөнө»); a term with a space is a phrase of whole-word starts."""
    term = term.casefold()
    if ' ' in term:
        return re.search(r'(?<!\w)' + r'\s+'.join(map(re.escape, term.split())), flat) is not None
    return any(word.startswith(term) for word in words)


# Question words, particles, pronouns and words every school question shares («газар», «сургууль»): no topic of
# their own (nearest stored questions, 11/26: «бие засах газар» was offered «хоолны газар»).
_FORM_WORDS = frozenset(('вэ бэ уу юу үү юм хаана хаанаас хэзээ хэн хэнд хэнээс хэд хэдэн хэддүгээр ямар яаж яах '
                         'юуг юунд байна байдаг байгаа бий болох болно гэж гэсэн гэдэг энэ тэр эдгээр танай танайх манай '
                         'миний би та чинь нь бол ч л хэлнэ хэлж өгөөч өгнө газар хүн хүмүүс зүйл талаар тухай '
                         'мэдээлэл асуулт сургууль сургуулийн сургуульд коллеж коллежийн шмтк').split())


def _topic_stems(text):
    """The first four letters of each topic word: «Төлбөрөө хуваан төлж болох уу?» -> {«төлб», «хува», «төлж»}."""
    words = re.findall(r'[a-zа-яөүё]{3,}', (text or '').casefold())
    return {word[:4] for word in words if word not in _FORM_WORDS}


class FaqIntents:
    def __init__(self, intents=(), *, threshold=0.84, enabled=True, encoder=None, lock=None):
        self.intents = [dict(intent) for intent in intents]
        self.threshold = float(threshold)
        self.enabled = bool(enabled) and bool(self.intents)
        self.encoder = encoder
        self._vectors = {}
        # The retriever's own lock when the encoder is the retriever's: one tokenizer must not run in two threads.
        self._lock = lock or threading.Lock()

    @classmethod
    def from_config(cls, root, encoder=None, lock=None):
        try:
            data = json.loads((Path(root) / CONFIG_PATH).read_text(encoding='utf-8'))
            intents = data['intents']
            if not isinstance(intents, list) or any(not isinstance(item.get('faq_id'), str)
                                                     or not item.get('require') for item in intents):
                raise ValueError('invalid intents')
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return cls(enabled=False)
        return cls(intents, threshold=data.get('threshold', 0.84), enabled=data.get('enabled', False) is True,
                   encoder=encoder, lock=lock)

    def gated(self, query):
        """Intents whose concept words the question holds, with the words that matched."""
        flat = _flat(query)
        words = _WORD.findall(flat)
        found = []
        for intent in self.intents:
            if any(_has(term, words, flat) for term in intent.get('exclude', ())):
                continue
            hits = []
            for group in intent['require']:
                hit = next((term for term in group if _has(term, words, flat)), None)
                if hit is None:
                    break
                hits.append(hit)
            else:
                found.append((intent, hits))
        return found

    @staticmethod
    def _numbers_fit(query, faq_text, allowed=()):
        years = set(_YEAR.findall(query))
        if years - set(_YEAR.findall(faq_text)):
            return False
        numbers = set(_NUMBER.findall(_YEAR.sub(' ', query)))
        return numbers <= set(_NUMBER.findall(faq_text)) | set(map(str, allowed))

    def _embed(self, texts):
        with self._lock:
            return self.encoder.encode(list(texts), 'query: ')

    def _similarity(self, query_vector, intent, faq):
        variants = [faq.get('question', '')] + list(faq.get('question_aliases') or []) + list(intent.get('examples', ()))
        key = tuple(text for text in variants if text)   # a changed stored question is encoded again
        if key not in self._vectors:
            self._vectors[key] = self._embed(key)
        return float((self._vectors[key] @ query_vector).max())

    def nearest(self, query, faqs, *, floor=0.83, limit=3):
        """The stored questions closest in meaning to a question nothing answered (2026-11-26): for each FAQ its
        shortest wording (the question or an alias) with the E5 cosine of the closest wording, best first, at least
        ``floor``, at most ``limit``; [] without the encoder. Offered to choose from, never answered by itself.
        E5-small scores short Mongolian questions of the same form close together (0.88–0.93 for «дүрэмт
        хувцастай юу» and «Тэтгэлэг байдаг уу?», measured 11/26), so a stored question must also share a topic
        word with the question (its first four letters); the closeness only orders them."""
        if self.encoder is None or not isinstance(query, str) or not query.strip():
            return []
        asked = _topic_stems(query)
        if not asked:
            return []
        query_vector = self._embed([query])[0]
        scored = []
        for faq in faqs.values():
            variants = tuple(text for text in [faq.get('question', '')] + list(faq.get('question_aliases') or []) if text)
            if not variants or not asked & set().union(*map(_topic_stems, variants)):
                continue
            if variants not in self._vectors:
                self._vectors[variants] = self._embed(variants)
            similarity = float((self._vectors[variants] @ query_vector).max())
            if similarity >= floor:
                scored.append((similarity, min(variants, key=len)))
        shown, result = {query.strip().casefold()}, []
        for similarity, text in sorted(scored, key=lambda row: -row[0]):
            if text.strip().casefold() not in shown:
                shown.add(text.strip().casefold())
                result.append((text, round(similarity, 4)))
            if len(result) == limit:
                break
        return result

    def match(self, query, faqs):
        """The FAQ a question maps to, or None. ``faqs``: faq_id -> stored record (question, aliases, answer)."""
        if not self.enabled or not isinstance(query, str) or not query.strip():
            return None
        candidates = []
        for intent, hits in self.gated(query):
            faq = faqs.get(intent['faq_id'])
            if not faq:
                continue
            text = ' '.join([faq.get('question', ''), *faq.get('question_aliases', []), faq.get('answer', '')])
            if not self._numbers_fit(query, text, intent.get('allow_numbers', ())):
                continue
            # A value the question asks for (a count, a date, a time …) must be in the stored answer: «Номын сан Koha-г
            # хэдэн оноос ашиглаж байна вэ?» is not answered by the campus FAQ, which has no year (answer_types.py).
            if not value_supported(query, faq.get('answer', '')):
                continue
            candidates.append((intent, hits, faq))
        if not candidates:
            return None
        scored = []
        if self.encoder is not None:
            try:
                query_vector = self._embed([query])[0]
                scored = sorted(((self._similarity(query_vector, intent, faq), intent, hits, faq)
                                 for intent, hits, faq in candidates), key=lambda row: -row[0])
            except Exception:       # no encoder at run time: only a single gated intent maps
                scored = []
        if scored:
            best, intent, hits, faq = scored[0]
            if best < self.threshold:
                return None
            return dict(faq_id=intent['faq_id'], question=faq['question'], similarity=round(best, 4),
                        concept_words=hits, method='concept_words+e5',
                        others=[dict(faq_id=row[1]['faq_id'], similarity=round(row[0], 4)) for row in scored[1:4]])
        if len(candidates) != 1:
            return None
        intent, hits, faq = candidates[0]
        return dict(faq_id=intent['faq_id'], question=faq['question'], similarity=None, concept_words=hits,
                    method='concept_words_only', others=[])
