"""Measure passage support on explicit development labels, not answer accuracy."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import unicodedata

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from website_retrieval import WebsiteRetriever


def normalize(text):
    return ' '.join(unicodedata.normalize('NFC',text).casefold().split())


def evaluate(retriever,cases):
    rows=[]
    for case in cases:
        result=retriever.search(case['query'],limit=5)
        matches=[]
        if case['kind']=='source_support':
            matches=[i+1 for i,s in enumerate(result['candidates']) if s['url']==case['expected_url'] and normalize(case['expected_phrase']) in normalize(s['text'])]
        rows.append(dict(**case,support_rank=matches[0] if matches else None,
            candidates=[{k:s.get(k) for k in ('url','source_id','text','source_locator','score','matched_terms')} for s in result['candidates']],
            no_candidates=len(result['candidates'])==0,backend=result['backend'],latency_seconds=result['latency_seconds']))
    positives=[r for r in rows if r['kind']=='source_support']
    controls=[r for r in rows if r['kind']=='no_candidates']
    return dict(timestamp_utc=datetime.now(timezone.utc).isoformat(),
        label_scope='Assistant-authored development source-support labels; not answer correctness or held-out evaluation.',
        summary=dict(cases=len(rows),source_support_cases=len(positives),
            support_at_1=sum(r['support_rank']==1 for r in positives),
            support_at_3=sum(r['support_rank'] is not None and r['support_rank']<=3 for r in positives),
            support_at_5=sum(r['support_rank'] is not None for r in positives),
            no_evidence_controls=len(controls),no_evidence_controls_passed=sum(r['no_candidates'] for r in controls),
            router_controls_not_scored_here=sum(r['kind'].endswith('_guard') for r in rows)),
        retrieval_status=retriever.status(),training_performed=False,llm_calls=0,cases=rows)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases',type=Path,default=ROOT/'data/rag-source-dev-20261012.json')
    parser.add_argument('--output',type=Path,default=ROOT/'runtime/source-retrieval-dev.json')
    parser.add_argument('--lexical-only',action='store_true')
    args=parser.parse_args()
    cases=json.loads(args.cases.read_text(encoding='utf-8-sig'))['cases']
    report=evaluate(WebsiteRetriever(root=ROOT,use_dense=not args.lexical_only),cases)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_bytes((json.dumps(report,ensure_ascii=False,indent=2)+'\n').encode())
    print(json.dumps(report['summary'],ensure_ascii=False))
    print('Misses:',[c['id'] for c in report['cases'] if c['kind']=='source_support' and c['support_rank'] is None])
