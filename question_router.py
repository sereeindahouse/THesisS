"""Bounded, deterministic development routing over the existing content store.

A=fact-backed stored response, B=stored FAQ, D=clarification, E=refusal within
this imported package. C is disabled. These are proposed development routes,
not human gold. Matching uses only canonical questions and explicit aliases;
neither a retrieval score nor a clarification establishes answer support.
"""
import argparse
import json
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path
from time import perf_counter

from retrieval_probe import terms
from sqlite_retrieval import ReadOnlyContentStore, exact_key, search_content

ROOT = Path(__file__).resolve().parent
POLICY_VERSION = 'bounded-exact-v1'

# The existing question audit proposes these fact routes. A returns the same
# reviewed-format stored response and its fact dependencies, not a new template.
# Unknown/new FAQ IDs default to B. This is not an inferred/gold route label.
FACT_RESPONSE_FAQS = frozenset({'faq.contact', 'faq.arc.courses'})
YEAR_REQUIRED_FAQS = frozenset({'faq.arc.courses'})
ENTITY_TERMS = {'faq.sakura': frozenset({'sakura'}),
                'faq.arc.courses': frozenset({'arc'})}

# Generic question words cannot justify suggesting an unrelated school FAQ.
# These exact tokens are a transparent development rule, not Mongolian stemming.
QUESTION_WORDS = frozenset('''сургуулийн сургууль сургуулиас танай манай би миний
энэ тэр нь юм уу юу вэ бэ яаж ямар хэд хэдэн хэзээ хаана хаанаас хэрхэн тухай
талаар мэдээлэл мэдээллийг мэдээллийн мэдээллээ хэлнэ хэлж хэлээч хэлээд өгнө
өгч өгөөч өгнөө үү байна байгаа болох болохгүй болохыг бол болохоор гэсэн
тул болон бас эсвэл оны онд он одоо надад please tell me what when where how
the a an is are test тестийн'''.split())
YEAR_RE = re.compile(r'(?<!\d)(?:19|20)\d{2}(?!\d)')
NUMBER_RE = re.compile(r'\d+')
OFFICE_WORDS = frozenset({'алба', 'албаны', 'албанд', 'албанаас', 'албатай',
                         'албыг', 'албад', 'албандаа', 'албадаа', 'албууд', 'албуудаас'})
YEAR_PREFIX_RE = re.compile(r'^((?:19|20)\d{2}(?:\s*[–—-]\s*(?:19|20)\d{2})?)\s+'
                            r'(?:оны|онд|хичээлийн жилийн)\s+(.+)$', re.IGNORECASE)
YEAR_RANGE_RE = re.compile(r'(?<!\d)((?:19|20)\d{2})\s*[–—-]\s*((?:19|20)\d{2})(?!\d)')


def _topic_words(text):
    return set(terms(text)) - QUESTION_WORDS - set(NUMBER_RE.findall(text))


def _support_text(faq, facts):
    return ' '.join([faq['answer'], faq['scope'], *[
        json.dumps(facts[fid]['value'], ensure_ascii=False) + ' ' + facts[fid]['scope']
        for fid in faq['fact_ids']]])


def _guard_codes(preview, allow_draft):
    reasons = preview.get('answer_blocked_reasons', preview['blocked_reasons'])
    codes = []
    if any('approval_status=draft' in reason for reason in reasons):
        codes.append('approval_required')
    if any('approval_status=' in reason and 'approval_status=draft' not in reason
           for reason in reasons):
        codes.append('content_rejected_or_unapproved')
    if any('expired for' in reason for reason in reasons):
        codes.append('expired_content')
    if any('not yet valid' in reason for reason in reasons):
        codes.append('future_validity')
    if preview.get('answer_status') != 'complete_in_scope':
        codes.append('partial_answer')
    if not allow_draft and preview['unknown_validity_records']:
        codes.append('unknown_validity')
    return codes or ['answer_guard_blocked']


def route_question(db_path, query, *, allow_draft=False, package_id=None, as_of=None):
    """Route without changing DB, generating text, training or downloading.

    Uses a package pinned by read-only retrieval. Reopening that immutable
    package for policy metadata avoids mixing content from separate imports.
    ``allow_draft`` permits clearly labeled stored development previews with
    unknown dates, matching sqlite_retrieval; known expiry/partial still block.
    Invalid inputs/missing or incompatible stores raise existing CLI/API errors.
    """
    started = perf_counter()
    retrieval = search_content(db_path, query, backend='bm25', top_k=50,
        allow_draft=allow_draft, package_id=package_id, as_of=as_of)
    query = retrieval['query']
    with ReadOnlyContentStore(db_path) as store:
        content = store.export(retrieval['package_id'])
    faqs = {faq['faq_id']: faq for faq in content['faqs']}
    facts = {fact['fact_id']: fact for fact in content['facts']}
    literal_exact_ids = retrieval['exact_matches']
    year_prefix = YEAR_PREFIX_RE.fullmatch(query)
    binding_id = None
    if not literal_exact_ids and year_prefix:
        # Only this anchored, explicit year grammar is supported. It is a
        # supplied constraint on a literal stored base question, not an alias,
        # fuzzy intent, STT correction or authorization to discard other words.
        base = year_prefix.group(2)
        ids = [faq_id for faq_id, faq in faqs.items() if faq_id in YEAR_REQUIRED_FAQS
               and exact_key(base) in {exact_key(text) for text in
                   [faq['question'], *faq['question_aliases']]}]
        if len(ids) == 1:
            binding_id = ids[0]
            retrieval = search_content(db_path, base, backend='bm25', top_k=50,
                allow_draft=allow_draft, package_id=retrieval['package_id'],
                as_of=date.fromisoformat(retrieval['as_of']))
    query_words = _topic_words(query)
    exact_ids = retrieval['exact_matches']
    # Restrict clarification candidates to content-bearing question wording.
    # Answer-text overlap or common particles alone cannot establish relevance.
    candidates = [candidate for candidate in retrieval['candidates']
        if candidate['faq_id'] in exact_ids or any(query_words & _topic_words(text)
            for text in [faqs[candidate['faq_id']]['question'],
                         *faqs[candidate['faq_id']]['question_aliases']])]
    if exact_ids:
        # Once an exact intent exists, unrelated ranking candidates cannot
        # supply constraints/citations or become competing clarification clicks.
        candidates = [candidate for candidate in candidates if candidate['faq_id'] in exact_ids]
    result = dict(query=query, package_id=retrieval['package_id'],
        mode=retrieval['mode'], as_of=retrieval['as_of'],
        policy_version=POLICY_VERSION, route_definition_status='development_proposed_not_gold',
        route='E', reason_code=None, reason_codes=[], message=None, clarification=None,
        answer=None, answer_faq_id=None, answer_kind=None, intended_answer_route=None,
        citations=[], candidates=candidates, exact_matches=literal_exact_ids,
        binding_faq_id=binding_id,
        match_kind='explicit_year_literal_base' if binding_id else
                   ('literal_exact' if exact_ids else 'lexical_candidates'),
        unknown_validity_records=[], human_gold=False, c_enabled=False,
        generated=False, llm_calls=0, score_is_probability=False,
        automatic_approval=False, training_performed=False, database_modified=False,
        scope='Only the imported facts/FAQ package; not a claim about all school information.')
    evidence = {}
    for candidate in candidates:
        for citation in candidate['citations']:
            evidence[(citation['document_id'], citation['version'], citation['locator'])] = citation
    result['citations'] = [evidence[key] for key in sorted(evidence)]

    def finish(route, codes, message, clarification=None):
        result.update(route=route, reason_code=codes[0], reason_codes=codes,
                      message=message, clarification=clarification,
                      latency_ms=round((perf_counter() - started) * 1000, 3))
        return result

    def clarify(kind, message, options, years=()):
        return finish('D', [kind], message, dict(kind=kind, question=message,
            options=[{'faq_id': faq_id, 'question': faqs[faq_id]['question']}
                     for faq_id in options], supported_years=sorted(years)))

    def clarify_year(faq_id):
        years = sorted(set(YEAR_RE.findall(support[faq_id])))
        year_label = '–'.join(years)
        value = clarify('missing_year', 'Аль оны эсвэл хичээлийн жилийн мэдээлэл хэрэгтэй вэ?', [], years)
        if year_label:
            value['clarification']['options'] = [dict(faq_id=faq_id,
                question=f'{year_label} оны {faqs[faq_id]["question"]}',
                binding='explicit_year_literal_base', supplied_years=years)]
        return value

    if not candidates:
        return finish('E', ['no_supported_question_match'],
            'Одоогийн facts/FAQ багцад энэ асуултыг дэмжих таарсан асуулт алга. '
            'Сайтын бүх мэдээлэлд байхгүй гэж дүгнээгүй; хариулт зохиохгүй.')
    related_ids = [candidate['faq_id'] for candidate in candidates]
    support = {faq_id: _support_text(faqs[faq_id], facts) for faq_id in related_ids}
    query_years = set(YEAR_RE.findall(query))
    if any(int(start) > int(end) for start, end in YEAR_RANGE_RE.findall(query)):
        return finish('E', ['invalid_year_range'],
            'Асуултын жилийн хүрээ урвуу байна. Оны дарааллыг автоматаар засахгүй.')
    constraint_ids = exact_ids if len(exact_ids) == 1 else related_ids
    supported_years = {year for faq_id in constraint_ids for year in YEAR_RE.findall(support[faq_id])}
    year_compatible = [faq_id for faq_id in constraint_ids
                       if query_years <= set(YEAR_RE.findall(support[faq_id]))]
    if query_years and not year_compatible:
        result['requested_years'] = sorted(query_years)
        result['supported_years'] = sorted(supported_years)
        return finish('E', ['unsupported_year'],
            'Асуусан оныг дэмжих facts/FAQ энэ багцад алга. Өөр оны мэдээллийг орлуулахгүй.')
    query_numbers = set(NUMBER_RE.findall(query)) - query_years
    number_compatible = [faq_id for faq_id in constraint_ids
                         if query_numbers <= set(NUMBER_RE.findall(support[faq_id]))]
    if query_numbers and not number_compatible:
        return finish('E', ['unmatched_numeric_constraints'],
            'Асуултад байгаа тоо эсвэл дугаарыг энэ багцын эхээр батлах боломжгүй. Тоог засаж таахгүй.')

    # These exclusions express the actual five-FAQ scope, not broad semantic
    # classification. General contact never substitutes for an office-specific
    # number; historical Sakura activities never establish live enrollment.
    tokens = set(terms(query))
    known_entities = set().union(*ENTITY_TERMS.values())
    requested_entities = tokens & known_entities
    if len(exact_ids) == 1 and requested_entities:
        faq_id = exact_ids[0]
        canonical_entities = (set(terms(faqs[faq_id]['question'])) | set(terms(support[faq_id]))) & known_entities
        if not requested_entities <= canonical_entities:
            return finish('E', ['unmatched_named_entity'],
                'Асуултын нэр нь яг таарсан FAQ-ийн өөрийн эх, хүрээтэй зөрж байна. Нэрийг орлуулахгүй.')
    office_requested = bool(tokens & OFFICE_WORDS)
    office_options = [faq_id for faq_id in related_ids if faq_id != 'faq.contact' and any(
        word in OFFICE_WORDS for text in [faqs[faq_id]['question'], *faqs[faq_id]['question_aliases']]
        for word in terms(text))]
    if ('faq.contact' in related_ids and office_requested
            and (exact_ids == ['faq.contact'] or not office_options)):
        return finish('E', ['specific_scope_not_supported'],
            'Энэ багцад сургуулийн ерөнхий холбоо бий; албаны тусгай холбоо батлагдаагүй.')
    if 'faq.sakura' in related_ids and tokens & {'нээлттэй', 'бүртгэл', 'бүртгэлийн', 'одоо'}:
        return finish('E', ['live_status_not_supported'],
            'Sakura-ийн түүхэн танилцуулга нь өнөөдрийн бүртгэл, боломжийн төлөвийг батлахгүй.')

    preview = retrieval['exact_match_preview']
    if len(exact_ids) == 1:
        faq_id = exact_ids[0]
        result['intended_answer_route'] = ('A' if faq_id in FACT_RESPONSE_FAQS
                                            and faqs[faq_id]['fact_ids'] else 'B')
        result['unknown_validity_records'] = preview['unknown_validity_records']
        # Never bypass source/fact/FAQ guards just because clarification is easy.
        if not preview['answer_eligible']:
            return finish('E', _guard_codes(preview, allow_draft),
                'Яг таарсан асуулт байна. Гэхдээ эх, fact, FAQ-ийн баталгаа, '
                'хүчинтэй хугацаа эсвэл хариултын бүрэн байдлын шалгалт хангаагүй.')
        if faq_id in YEAR_REQUIRED_FAQS and not query_years:
            return clarify_year(faq_id)
        result.update(answer=retrieval['answer'], answer_faq_id=faq_id,
            answer_kind=('approved_stored_answer' if preview['approval_status'] == 'approved'
                         and not preview['unknown_validity_records']
                         and all(c['approval_status'] == 'approved' for c in preview['citations'])
                         and not any(facts[fid]['approval_status'] != 'approved' for fid in faqs[faq_id]['fact_ids'])
                         else 'development_draft_preview'),
            fact_ids=faqs[faq_id]['fact_ids'], citations=preview['citations'])
        return finish(result['intended_answer_route'],
            ['exact_stored_draft_preview' if result['answer_kind'] == 'development_draft_preview'
             else 'exact_approved_stored_answer'],
            'Хөгжүүлэлтийн draft хариулт; сургуулиар баталгаажсан хариулт биш.'
            if result['answer_kind'] == 'development_draft_preview'
            else 'Яг таарсан, эхтэй бөгөөд хүчинтэй хугацаа нь тодорхой хадгалсан хариулт.')
    if len(exact_ids) > 1:
        if query_years or query_numbers or requested_entities or office_requested:
            return clarify('ambiguous_constrained_exact_match',
                'Ижил хэлбэр хэд хэдэн FAQ-д байна. Нэр, он, тоо эсвэл албаны хүрээг хасаж сонголт өгөхгүй; эх ба хүрээг нягтлах шаардлагатай.',
                [], query_years)
        return clarify('ambiguous_exact_match',
            'Ижил асуултын хэлбэр хэд хэдэн FAQ-д байна. Аль асуултыг хэлж байна вэ?', exact_ids)

    # Unsupported named entities are never silently changed into known ones.
    latin_query = set(re.findall(r'[a-z][a-z0-9]*', exact_key(query))) - QUESTION_WORDS
    latin_supported = {token for faq_id in related_ids
        for text in [faqs[faq_id]['question'], *faqs[faq_id]['question_aliases']]
        for token in re.findall(r'[a-z][a-z0-9]*', exact_key(text))}
    if latin_query - latin_supported:
        return finish('E', ['unmatched_named_entity'],
            'Асуултын нэрийг энэ багцын хадгалсан асуулттай баттай холбож чадсангүй. Нэрийг орлуулахгүй.')
    compatible_ids = [faq_id for faq_id in related_ids
        if (not query_years or faq_id in year_compatible)
        and (not query_numbers or faq_id in number_compatible)
        and (not office_requested or faq_id in office_options)
        and (not requested_entities or requested_entities <= ENTITY_TERMS.get(faq_id, frozenset()))]
    if not compatible_ids:
        return finish('E', ['constraints_not_supported_together'],
            'Асуултын нэр, он, тоо эсвэл хүрээг хамтад нь дэмжих нэг хадгалсан асуулт алга. Тааж нэгтгэхгүй.')
    related_ids = compatible_ids
    result['candidates'] = [c for c in candidates if c['faq_id'] in related_ids]
    evidence = {}
    for candidate in result['candidates']:
        for citation in candidate['citations']:
            evidence[(citation['document_id'], citation['version'], citation['locator'])] = citation
    result['citations'] = [evidence[key] for key in sorted(evidence)]
    if query_years or query_numbers or office_requested:
        # Replacing a constrained user request with a shorter canonical option
        # would silently drop its year/number/entity. Keep the original request
        # visible and ask for scope review instead of offering that unsafe click.
        return clarify('constrained_wording_not_exact',
            'Нэр, он, тооны хязгаарлалтыг хадгалсан хүсэлт яг таараагүй. '
            'Богино FAQ-аар орлуулахгүй; энэ асуултын эхтэй хэлбэрийг нягтлах шаардлагатай.', [], query_years)
    entity_options = {faq_id: ENTITY_TERMS[faq_id] for faq_id in related_ids if faq_id in ENTITY_TERMS}
    if len(entity_options) > 1 and not any(tokens & values for values in entity_options.values()):
        return clarify('missing_entity', 'Аль хамтын ажиллагааны тухай асууж байна вэ?', entity_options)
    if len(related_ids) == 1 and related_ids[0] in YEAR_REQUIRED_FAQS and not query_years:
        return clarify_year(related_ids[0])
    # Scores do not choose an answer. A user's next request must independently
    # pass exact wording, scope/year and approval/validity checks.
    return clarify('select_supported_question',
        'Төстэй асуулт олдлоо. Хариулахын өмнө аль хадгалсан асуултыг хэлж байгааг тодруулъя.', related_ids)


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='Эхтэй exact/D/E development router; C/LLM ажиллахгүй.')
    parser.add_argument('query')
    parser.add_argument('--db', type=Path, default=ROOT / 'runtime/content.db')
    parser.add_argument('--package-id')
    parser.add_argument('--as-of', type=date.fromisoformat)
    parser.add_argument('--allow-draft', action='store_true')
    args = parser.parse_args()
    try:
        result = route_question(args.db, args.query, allow_draft=args.allow_draft,
                                package_id=args.package_id, as_of=args.as_of)
    except (OSError, ValueError, KeyError, sqlite3.Error) as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
