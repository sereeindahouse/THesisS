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
FINAL_PREDICATE = re.compile(r'(?:даг|дэг|дог|дөг|на|нэ|но|нө|сан|сэн|сон|сөн|ах|эх|ох|өх)$')
NUMERIC_QUESTION = re.compile(r'(?<!\w)(?:хэзээ|хэдэн|хэд|хэдэд|хэдний|хэддүгээр)(?!\w)')
SHORT_QUESTION_TERMS = 6
SHORT_QUESTION_COVERAGE = 0.85
LONG_QUESTION_COVERAGE = 0.3


@lru_cache(maxsize=4096)
def _words(text):
    # One spelling per unit and small number («квадрат метр» = «м²», «хоёр» = «2») before comparing.
    # Cached: the same claims are checked for many candidate subsets of one answer.
    from answer_types import normalise_units
    from website_retrieval import search_terms
    text = normalise_units(text, numerals=True)
    return frozenset(re.findall(r'\w+', text)) | frozenset(search_terms(text))


def _has_term(term, words):
    # Shared prefixes stand in for Mongolian suffixes.
    return any(word.startswith(term[:max(3, len(term) - 3)]) for word in words)


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
    from answer_types import normalise_units
    from website_retrieval import search_terms
    terms = tuple(term for term in dict.fromkeys(search_terms(normalise_units(query, numerals=True)))
                  if term not in REQUEST_WORDS)
    # Mongolian ends a sentence with its verb; that word names no topic.
    return terms[:-1] if len(terms) > 1 and FINAL_PREDICATE.search(terms[-1]) else terms


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
    from website_retrieval import search_terms
    terms = set(key_terms(query))
    return bool(terms) and any(set(search_terms(normalise_units(line, numerals=True))) == terms
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

    return not any(value_supported(query, claim) and not other_year(claim)
                   and (not focus or any(_has_term(term, _anchor_words(claim + '\n' + context)) for term in focus))
                   for claim, context in zip(claims, contexts))


def topic_covered(query, text):
    required = (SHORT_QUESTION_COVERAGE if len(key_terms(query)) <= SHORT_QUESTION_TERMS
                else LONG_QUESTION_COVERAGE)
    return key_term_coverage(query, text) >= required


def relevant_to_question(query, text, typed=True, claims=None, focus=(), contexts=None):
    if value_missing(query, claims if claims is not None else [text], typed, focus, contexts):
        return False
    return topic_covered(query, text)


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
    # A page's title and heading name what its paragraphs are about (the anchor check).
    headings = {source.get('source_id'): source.get('title', '') + '\n' + source.get('page_header', '')
                for source in sources or []}
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
            shown = '\n'.join(claims)
            if (candidate['accepted'] and not requirements
                    and not relevant_to_question(query, shown, typed, claims=claims, focus=focus, contexts=contexts)):
                # Name the cause: topic words present but no value of the asked type. With the
                # switch off the earlier screen keeps its earlier reason.
                candidate = dict(accepted=False, reason='requested_value_missing'
                                 if typed and topic_covered(query, shown)
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
                'selection_not_relevant', 'no_single_unit_covers_question'}
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
