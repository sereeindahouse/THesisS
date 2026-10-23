"""Freeze and compare source selection, without inventing human correctness.

The retrieval candidates and evidence units are fixed before any model answers.
This is a selector comparison, not a whole-chat or held-out accuracy estimate.
The lexical baselines select the best one / best three BM25 units, respectively;
both pass the SAME provenance, literal-field and answer-budget renderer as Gemma.
No reference facts are supplied to either selector. Existing files are preserved.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TRACKED = ('tools/evaluate_llm_selection.py', 'rag_runtime.py', 'evidence_contract.py',
    'source_fields.py', 'answer_contract.py', 'website_retrieval.py', 'retrieval_probe.py',
    'speech_text.py', 'llm_runtime.py', 'config/model-catalog/gemma3-4b-text.json',
    'runtime/rag-model.json')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':')).encode('utf-8')).hexdigest()


def utc():
    return datetime.now(timezone.utc).isoformat()


def save_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write('\n')


def scoped_sources(query, sources):
    # Exactly the filters preceding evidence_units in GroundedGenerator.generate.
    from rag_runtime import (department_evidence_sources, dated_news_evidence_sources,
        article_evidence_sources, year_evidence_sources)
    sources = department_evidence_sources(query, sources, all_attributes=True)
    sources = dated_news_evidence_sources(query, article_evidence_sources(query, sources))
    return year_evidence_sources(query, sources)


def lexical_selection(query, units, count=1):
    """BM25 rank with stable input-order ties; no answer/reference access."""
    from retrieval_probe import bm25_scores
    from website_retrieval import search_terms
    if count not in (1, 3):
        raise ValueError('Use the registered best-one or best-three baseline.')
    scores = bm25_scores([' '.join(search_terms(unit['text'])) for unit in units],
                         [' '.join(search_terms(query))])[0] if units else []
    ranked = sorted(range(len(units)), key=lambda i: (-scores[i], i))
    ids = [units[i]['unit_id'] for i in ranked[:count] if scores[i] > 0]
    return dict(selected_unit_ids=ids, scores=[dict(unit_id=units[i]['unit_id'],
        score=float(scores[i])) for i in ranked], llm_calls=0,
        abstained=not ids, baseline='bm25_best_'+str(count)+'_units',
        description='Fixed top-k selection, not an adaptive semantic selector.')


def common_render(query, ids, units, *, abstained=False):
    """The same final guards/render for all conditions; no reference access."""
    from evidence_contract import resolve_evidence_selection
    from source_fields import (field_evidence_requirements, missing_field_evidence,
        requested_detail, detail_supported)
    from rag_runtime import compound_exam_duration, both_exam_durations_supported, refine_evidence_selection
    from answer_contract import (render_claims, MAX_SPEECH_CHARACTERS,
        interview_attribute, ATTRIBUTE_LABELS, supports_interview_attribute)
    if abstained or not ids:
        return dict(accepted=False, answer=None, claims=[], reason='selector_abstained')
    if len(ids) > 3:
        return dict(accepted=False, answer=None, claims=[], reason='selector_exceeds_three_units')
    resolved = resolve_evidence_selection(query, ids, units, max_characters=1800, max_claims=6)
    if not resolved['accepted']:
        return dict(resolved, answer=None)
    texts = [claim['text'] for claim in resolved['claims']]
    missing = missing_field_evidence(field_evidence_requirements(query), texts)
    selected = '\n'.join(texts)
    detail, attribute = requested_detail(query), interview_attribute(query)
    reason = ('requested_fields_not_in_selection' if missing else
        'requested_field_not_in_selection' if compound_exam_duration(query)
            and not both_exam_durations_supported(selected) else
        'requested_field_not_in_selection' if detail and not detail_supported(detail, selected, query=query) else
        'requested_field_not_in_selection' if attribute in ATTRIBUTE_LABELS
            and not supports_interview_attribute(query, selected) else None)
    refinement = None
    if not reason:
        resolved, refinement = refine_evidence_selection(query, ids, units, resolved)
    answer, _ = render_claims(resolved['claims'])
    if len(answer) > MAX_SPEECH_CHARACTERS:
        reason = 'answer_exceeds_speech_budget'
    if reason:
        return dict(accepted=False, answer=None, claims=[], reason=reason, missing_fields=missing)
    return dict(resolved, answer=answer, reason='source_preserving_selection', selection_refinement=refinement)


def slot_screen(case, output):
    """Literal required-quote fragments only; NEVER a semantic/human score."""
    answer = output.get('answer') or ''
    groups = case['required_slots']
    hits = [dict(name=slot['name'], hit=all(fragment in answer for fragment in slot['all_of']),
                 all_of=slot['all_of']) for slot in groups]
    return dict(slots=hits, matched=sum(row['hit'] for row in hits), total=len(hits),
        all_literal_slots_present=all(row['hit'] for row in hits),
        semantic_correctness_proven=False, human_correctness=None)


def freeze(cases_path, output_dir, root=ROOT):
    from content_release import ContentReleaseManager
    from website_retrieval import WebsiteRetriever
    from evidence_contract import evidence_units
    from rag_runtime import GroundedGenerator
    root, output_dir = Path(root), Path(output_dir)
    references = json.loads(Path(cases_path).read_text(encoding='utf-8-sig'))
    if references.get('human_reference_review') is not False or references.get('label_author') != 'assistant':
        raise ValueError('Declare assistant, human-unreviewed references.')
    ids, queries = set(), set()
    for row in references['cases']:
        if row['id'] in ids or row['query'] in queries:
            raise ValueError('Duplicate cases.')
        ids.add(row['id']); queries.add(row['query'])
        if not row.get('required_slots') or not row.get('source_refs') or not row.get('required_facts'):
            raise ValueError('Each answerable case needs source-grounded slots and facts.')
    active = ContentReleaseManager(root).resolve()
    database = Path(active['website_database']) if active else root/'CORE/database/website.db'
    retriever = WebsiteRetriever(root, database)
    retriever.status()
    all_sources = {row['source_id']:row for row in retriever._rows}
    for row in references['cases']:
        for ref in row['source_refs']:
            source = all_sources.get(ref['source_id'])
            if source is None or ref['quote'] not in source['text'] or ref['url'] != source['url']:
                raise ValueError('Reference quote/source membership failed: '+row['id'])
        for slot in row['required_slots']:
            if not slot.get('all_of') or any(not any(fragment in r['quote'] for r in row['source_refs'])
                for fragment in slot['all_of']):
                raise ValueError('Every literal slot must occur in a prewritten reference quote.')
    generator = GroundedGenerator(root)
    provider_status = generator.status()
    model_identity = generator._request('GET', '/api/tags', None, 3)
    frozen_cases = []
    for case in references['cases']:
        retrieval = retriever.search(case['query'], limit=5)
        sources = scoped_sources(case['query'], retrieval['candidates'])
        units = evidence_units(sources, max_characters=900)
        frozen_cases.append(dict(case, retrieval=retrieval, sources=sources, units=units,
            candidate_sha256=digest(sources), evidence_units_sha256=digest(units)))
    frozen = dict(schema_version=1, frozen_utc=utc(), references_sha256=sha(cases_path),
        protocol='Candidate-fixed production evidence selector vs fixed top1/top3 lexical units.',
        human_reference_review=False, held_out_evaluation=False,
        question_scope='New wording constructed from known corpus; topics may overlap earlier development tasks.',
        no_model_outputs_observed_at_freeze=True,
        planned_conditions=['gemma_production_selector','bm25_best_1_units','bm25_best_3_units'],
        common_rules='Same evidence units, resolver/context expansion, literal field/detail guards, rendering and budget.',
        baseline_limitations='Fixed top1 can omit complementary facts; fixed top3 can add irrelevant context or exceed budgets. Neither is all possible deterministic approaches.',
        production_limitations='Gemma includes the existing at-most-one field-repair call; this compares pipelines, not model weights alone. Retrieval and routing quality are outside this experiment.',
        code_sha256={name:sha(root/name) for name in TRACKED},
        database_sha256=sha(database), corpus_id=retriever.status()['corpus_id'],
        release_id=active['release_id'] if active else None,
        model_status=provider_status, local_provider_model_inventory=model_identity,
        reference_provenance_checks=dict(quote_membership=True,literal_slots_in_refs=True,
            semantic_reference_correctness=False), cases=frozen_cases)
    save_new(output_dir/'frozen-inputs.json', frozen)
    print('frozen', len(frozen_cases), 'cases', sha(output_dir/'frozen-inputs.json'), flush=True)
    return frozen


def blind_forms(report, frozen_sha, output_dir):
    rows, key = [], []
    for case in report['cases']:
        for condition, result in case['conditions'].items():
            review_id = 'review-'+hashlib.sha256((case['id']+'|'+condition+'|'+frozen_sha).encode()).hexdigest()[:16]
            output = result['common_output']
            rows.append(dict(review_id=review_id, case_id=case['id'], query=case['query'],
                answer=output['answer'], abstention_reason=None if output['accepted'] else 'Энэ хувилбар эхтэй хариулт буцаагаагүй.',
                required_facts=case['required_facts'], source_refs=case['source_refs'],
                human_review=dict(reviewer=None, correctness=None, completeness=None,
                    citation_support=None, irrelevant_content=None, notes=None)))
            key.append(dict(review_id=review_id, case_id=case['id'], condition=condition))
    random.Random(421021).shuffle(rows)
    for row in rows:
        row['item_sha256'] = digest(row)
    package = dict(schema_version=1, protocol='Нөхцөл, модель, route-ийг нуусан эхтэй хариултын үнэлгээ. Хүний үнэлгээ бөглөөгүй.',
        input_sha256=frozen_sha, human_evaluation_completed=False, rows=rows)
    save_new(output_dir/'human-review.json', package)
    save_new(output_dir/'condition-key.private.json', dict(input_sha256=frozen_sha, mapping=key))


def run(frozen_path, output_dir, root=ROOT):
    from rag_runtime import GroundedGenerator
    from evidence_contract import evidence_units
    from llm_runtime import _http_json
    root, output_dir = Path(root), Path(output_dir)
    frozen = json.loads(Path(frozen_path).read_text(encoding='utf-8'))
    for name, expected in frozen['code_sha256'].items():
        if sha(root/name) != expected:
            raise ValueError('Code differs from frozen protocol: '+name)
    for case in frozen['cases']:
        if digest(case['sources']) != case['candidate_sha256'] or digest(case['units']) != case['evidence_units_sha256']:
            raise ValueError('Frozen candidates/units changed.')
        if evidence_units(scoped_sources(case['query'], case['sources']), max_characters=900) != case['units']:
            raise ValueError('Production source preprocessing no longer matches frozen units.')
    first_path = output_dir/'first-run.json'
    save_new(first_path, dict(status='reserved_before_first_model_answer', frozen_sha256=sha(frozen_path), cases=[]))
    report = dict(schema_version=1, started_utc=utc(), frozen_sha256=sha(frozen_path),
        independent_human_evaluation=False, semantic_correctness_score=None,
        code_sha256=frozen['code_sha256'], conditions=frozen['planned_conditions'], cases=[])

    def save():
        first_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')

    exchanges = []
    def transport(method, url, payload, timeout, max_bytes):
        record = dict(method=method, url=url, payload=deepcopy(payload), requested_utc=utc())
        exchanges.append(record)
        try:
            response = _http_json(method,url,payload,timeout,max_bytes)
            record['response']=deepcopy(response)
            return response
        except Exception as error:
            record['error']=type(error).__name__+': '+str(error)
            raise

    generator = GroundedGenerator(root, transport=transport)
    for case in frozen['cases']:
        row = {key:deepcopy(case[key]) for key in ('id','query','required_facts','source_refs')}
        row.update(candidate_sha256=case['candidate_sha256'],evidence_units_sha256=case['evidence_units_sha256'], conditions={})
        for count in (1, 3):
            started=time.perf_counter()
            selection=lexical_selection(case['query'],case['units'],count)
            output=common_render(case['query'],selection['selected_unit_ids'],case['units'],abstained=selection['abstained'])
            row['conditions']['bm25_best_'+str(count)+'_units']=dict(selection=selection,common_output=output,
                wall_ms=round((time.perf_counter()-started)*1000,3),llm_calls=0,literal_reference_screen=slot_screen(case,output))
        before=len(exchanges)
        started=time.perf_counter()
        result=generator.generate(case['query'],deepcopy(case['sources']))
        if result.get('evidence_units'):
            keys=('unit_id','source_id','text','start','end','context_unit_ids')
            expected=[{key:u.get(key) for key in keys} for u in case['units']]
            if result['evidence_units'] != expected:
                raise ValueError('Gemma saw different units: '+case['id'])
        output=common_render(case['query'],result.get('proposed_unit_ids',[]),case['units'],abstained=not result.get('generated'))
        row['conditions']['gemma_production_selector']=dict(selection=result,common_output=output,
            wall_ms=round((time.perf_counter()-started)*1000,3),llm_calls=result.get('llm_calls',0),
            literal_reference_screen=slot_screen(case,output),provider_exchanges=deepcopy(exchanges[before:]))
        report['cases'].append(row);save()
        print(case['id'], {key:(value['common_output']['accepted'],value['literal_reference_screen']['matched'],value['literal_reference_screen']['total']) for key,value in row['conditions'].items()},flush=True)
    report['finished_utc']=utc()
    report['summary']={condition:dict(cases=len(report['cases']),
        structural_accepted=sum(case['conditions'][condition]['common_output']['accepted'] for case in report['cases']),
        all_literal_slots_present=sum(case['conditions'][condition]['literal_reference_screen']['all_literal_slots_present'] for case in report['cases']),
        llm_calls=sum(case['conditions'][condition]['llm_calls'] for case in report['cases']),
        median_wall_ms=statistics.median(case['conditions'][condition]['wall_ms'] for case in report['cases']),
        human_correctness=None, semantic_accuracy=None) for condition in frozen['planned_conditions']}
    save();blind_forms(report,sha(frozen_path),output_dir)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('freeze');p.add_argument('--cases',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True)
    p=sub.add_parser('run');p.add_argument('--frozen',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    if args.command=='freeze':freeze(args.cases,args.output_dir)
    else:run(args.frozen,args.output_dir)


if __name__=='__main__':
    main()
