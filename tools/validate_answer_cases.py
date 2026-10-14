"""Validate assistant reference provenance before collecting live outputs.

This checks a quote's membership in the frozen corpus, not whether a label or
generated answer is semantically correct. Public cases retain offsets/hashes;
the full source snapshot remains local. No model or database writes.
"""
import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import unicodedata

ANSWERABILITY={'answerable','needs_clarification','unsupported_in_verified_passages'}


def validate(bundle,passages,source_hash):
    if bundle.get('schema_version')!=1 or bundle.get('source_snapshot_sha256')!=source_hash:
        raise ValueError('Reference schema or frozen source SHA256 mismatch.')
    ids=[row['source_id'] for row in passages]
    if len(ids)!=len(set(ids)):
        raise ValueError('Source IDs must be unique.')
    sources={row['source_id']:row for row in passages}
    cases=bundle.get('cases',[])
    if not isinstance(cases,list) or not 1<=len(cases)<=100:
        raise ValueError('Use 1–100 reference cases.')
    seen_ids,seen_queries=set(),set()
    public=deepcopy(bundle)
    for number,case in enumerate(cases):
        if not all(case.get(k) for k in ('id','query','requested_attribute','expected_behavior','reference_answerability')):
            raise ValueError('Missing case metadata.')
        query=case['query']
        if not isinstance(query,str) or len(query)>1000 or not query.strip():
            raise ValueError('Invalid query text.')
        key=' '.join(unicodedata.normalize('NFC',query).casefold().split())
        if case['id'] in seen_ids or key in seen_queries:
            raise ValueError('Duplicate case ID or query.')
        seen_ids.add(case['id']);seen_queries.add(key)
        if case['reference_answerability'] not in ANSWERABILITY:
            raise ValueError('Unsupported answerability label.')
        if case.get('label_author')!='assistant' or case.get('human_reference_review') is not False:
            raise ValueError('This protocol requires explicit assistant/unreviewed provenance.')
        refs=case.get('source_refs',[])
        if (not isinstance(refs,list) or not isinstance(case.get('required_facts'),list)
                or not isinstance(case.get('forbidden_claims'),list)):
            raise ValueError('Reference lists required.')
        if case['reference_answerability']=='answerable' and (not refs or not case['required_facts']):
            raise ValueError('Answerable cases need evidence and required facts.')
        clean=[]
        for ref in refs:
            source=sources.get(ref.get('source_id'))
            if source is None or ref.get('url')!=source['url'] or ref.get('version')!=source['version']:
                raise ValueError('Unknown or mismatched source reference: '+case['id'])
            locator=source.get('source_locator') or ''
            if not locator and all(k in source for k in ('text_scope','chunk_id','start_offset','end_offset')):
                locator=(f"{source['text_scope']}; chunk_id={source['chunk_id']}; "
                         f"page_char_offsets={source['start_offset']}:{source['end_offset']}")
            if (ref.get('locator') or '')!=locator:
                raise ValueError('Source locator differs from frozen passage: '+case['id'])
            quote=ref.get('quote')
            if not isinstance(quote,str) or not quote.strip() or quote not in source['text']:
                raise ValueError('Quote must occur exactly in source: '+case['id'])
            start=source['text'].find(quote)
            clean.append(dict(source_id=ref['source_id'],url=ref['url'],version=ref['version'],
                locator=locator,quote_start=start,quote_end=start+len(quote),
                quote_sha256=hashlib.sha256(quote.encode()).hexdigest(),
                passage_sha256=hashlib.sha256(source['text'].encode()).hexdigest()))
        public['cases'][number]['source_refs']=clean
    summary=dict(cases=len(cases),answerability_counts=dict(Counter(c['reference_answerability'] for c in cases)),
        source_references=sum(len(c.get('source_refs',[])) for c in cases),
        known_task_paraphrases=sum(bool(c.get('paraphrase_of')) for c in cases),
        new_or_unlinked_tasks=sum(not c.get('paraphrase_of') for c in cases),
        independent_human_reference=False,quote_membership_validated=True,
        semantic_reference_correctness_validated=False,held_out_evaluation=False)
    return public,summary


def run(cases_path,passages_path,output,public_output):
    source_bytes=passages_path.read_bytes();case_bytes=cases_path.read_bytes()
    source_hash=hashlib.sha256(source_bytes).hexdigest()
    public,summary=validate(json.loads(case_bytes.decode('utf-8-sig')),
                            json.loads(source_bytes.decode('utf-8-sig')),source_hash)
    for path in (output,public_output):
        if path.exists():raise FileExistsError('Keep earlier reference/pre-registration runs intact: '+str(path))
    public_output.parent.mkdir(parents=True,exist_ok=True);output.parent.mkdir(parents=True,exist_ok=True)
    public_output.write_text(json.dumps(public,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    report=dict(validated_utc=datetime.now(timezone.utc).isoformat(),summary=summary,
        original_cases_sha256=hashlib.sha256(case_bytes).hexdigest(),source_snapshot_sha256=source_hash,
        public_cases_sha256=hashlib.sha256(public_output.read_bytes()).hexdigest(),
        warning='Quote membership and assistant labels do not establish human gold or answer accuracy.')
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(report,ensure_ascii=False))
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases',type=Path,required=True)
    parser.add_argument('--passages',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--public-output',type=Path,required=True)
    args=parser.parse_args()
    run(args.cases,args.passages,args.output,args.public_output)
