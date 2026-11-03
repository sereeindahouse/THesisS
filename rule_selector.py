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

from itertools import combinations
import json
from pathlib import Path
import re
import time

RULE_SELECTOR = 'bm25_bounded_complete_subset'
GEMMA_SELECTOR = 'gemma_production_selector'
CONFIG_PATH = 'config/answer-selection.json'
SAFE_DEFAULT = dict(selector=RULE_SELECTOR, local_llm_enabled=False, single_unit_coverage=False)
# Words that shape a request or name the school itself, not what is being asked.
REQUEST_WORDS = frozenset('''хэлнэ хэлээрэй хэлж хэлээд нэрлэж нэрлээд нэрлээрэй нэрлэнэ
    тайлбарлана тайлбарлаач тайлбарлаарай ялгаж ялгаад харьцуулна харьцуулж өгнө аль хамт
    ажилладаг сургууль коллеж хэн хэдэн хэддүгээр үнэхээр хүртэл байдаг болдог тавьдаг
    өгдөг авдаг хийдэг ордог байх ёстой гараг гарагт гарагийн'''.split())
FINAL_PREDICATE = re.compile(r'(?:даг|дэг|дог|дөг|на|нэ|но|нө|сан|сэн|сон|сөн|ах|эх|ох|өх)$')
NUMERIC_QUESTION = re.compile(r'(?<!\w)(?:хэзээ|хэдэн|хэд|хэдэд|хэдний|хэддүгээр)(?!\w)')
SHORT_QUESTION_TERMS = 6
SHORT_QUESTION_COVERAGE = 0.85
LONG_QUESTION_COVERAGE = 0.3


def key_terms(query):
    from website_retrieval import search_terms
    terms = [term for term in dict.fromkeys(search_terms(query)) if term not in REQUEST_WORDS]
    # Mongolian ends a sentence with its verb; that word names no topic.
    return terms[:-1] if len(terms) > 1 and FINAL_PREDICATE.search(terms[-1]) else terms


def key_term_coverage(query, text):
    """Literal share of key terms in text; shared prefixes stand in for suffixes."""
    from website_retrieval import search_terms
    tokens = set(re.findall(r'\w+', text.casefold())) | set(search_terms(text))
    terms = key_terms(query)
    if not terms:
        return 1.0
    return sum(any(token.startswith(term[:max(3, len(term) - 3)]) for token in tokens)
               for term in terms) / len(terms)


def relevant_to_question(query, text):
    # A "when" or "how many" question needs a number in what it shows.
    if NUMERIC_QUESTION.search(query.casefold()) and not re.search(r'\d', text):
        return False
    required = (SHORT_QUESTION_COVERAGE if len(key_terms(query)) <= SHORT_QUESTION_TERMS
                else LONG_QUESTION_COVERAGE)
    return key_term_coverage(query, text) >= required


def answer_selection(root):
    """A missing or damaged file means no LLM; only a valid file may enable one."""
    try:
        value = json.loads((Path(root) / CONFIG_PATH).read_text(encoding='utf-8'))
        selector, enabled = value['selector'], value['local_llm_enabled']
        single_unit = value.get('single_unit_coverage', False)
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return dict(SAFE_DEFAULT)
    if (selector not in {RULE_SELECTOR, GEMMA_SELECTOR} or type(enabled) is not bool
            or selector == GEMMA_SELECTOR and not enabled or type(single_unit) is not bool):
        return dict(SAFE_DEFAULT)
    return dict(selector=selector, local_llm_enabled=enabled, single_unit_coverage=single_unit)


def bounded_lexical_selection(query, units, sources=None, requirements=(), single_unit=False):
    """First complete and relevant BM25 subset, with no references or answer values.

    Rank units by BM25 (stable original-order ties); retain at most 8 positive
    roots, then add up to 4 units holding a requested field whatever their BM25
    score. Try 1, then 2, then 3 roots. Within each size prefer greatest summed
    BM25, then ranked-order tuple. The first subset accepted by the shared
    renderer wins; without a requested field it must also cover the key terms.
    With ``single_unit`` one selected unit alone must cover them.
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
    for count in range(1, min(3, len(ranked)) + 1):
        choices = list(combinations(range(len(ranked)), count))
        # Within a size, cover the question's key terms first, then BM25.
        coverage = {indices: key_term_coverage(query, ' '.join(texts_by_id[ranked[i]['unit_id']] for i in indices))
                    for indices in choices}
        choices.sort(key=lambda indices: (-coverage[indices], -sum(ranked[i]['score'] for i in indices), indices))
        for indices in choices:
            ids = [ranked[i]['unit_id'] for i in indices]
            candidate = common_render(query, ids, units, sources=sources)
            if (candidate['accepted'] and not requirements and not relevant_to_question(
                    query, '\n'.join(claim['text'] for claim in candidate['claims']))):
                candidate = dict(accepted=False, reason='selection_not_relevant')
            elif (candidate['accepted'] and not requirements and single_unit
                    and not any(relevant_to_question(query, texts_by_id[unit_id]) for unit_id in ids)):
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

    def __init__(self, single_unit_coverage=False):
        self.single_unit_coverage = single_unit_coverage is True

    def status(self):
        return dict(provider='none', configured=False, available=False, provider_ready=False,
                    model=None, llm_calls=0, network_probe=False, selection_method=RULE_SELECTOR,
                    single_unit_coverage=self.single_unit_coverage,
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
                                              single_unit=self.single_unit_coverage)
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
    return RuleSelectionGenerator(single_unit_coverage=selection['single_unit_coverage'])
