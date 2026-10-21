"""Paired development ablation on one corpus; not answer accuracy or held-out QA."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from website_retrieval import WebsiteRetriever, RANKING_MODES, RRF_K, ANCHOR_COVERAGE_WEIGHT, CATEGORY_WEIGHT
from tools.evaluate_source_retrieval import normalize


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def summarize(rows):
    positive = [r for r in rows if r['kind'] == 'source_support']
    controls = [r for r in rows if r['kind'] == 'no_candidates']
    return dict(target_cases=len(positive),
        **{f'support_at_{k}': sum(r['support_rank'] is not None and r['support_rank'] <= k for r in positive) for k in (1,3,5)},
        mrr_at_5=sum(1/r['support_rank'] if r['support_rank'] else 0 for r in positive)/len(positive) if positive else None,
        no_candidate_controls=len(controls), no_candidate_results=sum(not r['candidates'] for r in controls),
        router_controls_not_scored=sum(r['kind'].endswith('_guard') for r in rows))


def evaluate(cases_path, output):
    cases = json.loads(cases_path.read_text(encoding='utf-8-sig'))['cases']
    ids = [c['id'] for c in cases]
    if not cases or len(set(ids)) != len(ids): raise ValueError('Cases must have unique IDs.')
    output.mkdir(parents=True, exist_ok=False)
    retriever = WebsiteRetriever(root=ROOT)
    status = retriever.status()
    if not status['available']: raise RuntimeError('Frozen local corpus unavailable.')
    # Capture the exact index inputs before any requests. This private snapshot
    # permits local reinspection; publishing a hash alone cannot reconstruct it.
    with retriever._lock:
        corpus = list(retriever._rows)
    corpus_path = output/'indexed-passages.json'
    corpus_path.write_text(json.dumps(corpus, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    db_hash = sha(retriever.database)
    report = dict(created_utc=datetime.now(timezone.utc).isoformat(),
        label_scope='Existing assistant development/tuning labels. One target URL+phrase, not exhaustive relevance judgements, not independent held-out or answer accuracy.',
        protocol=dict(modes=list(RANKING_MODES),rrf_k=RRF_K,anchor_weight=ANCHOR_COVERAGE_WEIGHT,category_weight=CATEGORY_WEIGHT,
            common='Same eligible corpus, Mongolian lexical aliases, E5 prefixes/pooling, max two HTML/document parts plus two independent client fields per URL, overlap/news exclusion.',
            bm25='Positive lexical scores only; Mongolian normalized query/document terms.',
            e5='Dense scores; no lexical/topic abstention; local pinned model required.',
            rrf='Lexical positive ranks + dense ranks; no extra boosts or lexical/topic gates.',
            rrf_boosted='RRF + anchor/category boosts; no lexical/topic gates.',
            production='Existing RRF+boosts+lexical/topic gates. Default chat retrieval unchanged.',
            latency='Diagnostic timings only; same model cache shared, order rotated by query. Not a controlled speed benchmark.'),
        corpus_id=status['corpus_id'], counts=status['counts'], database_sha256=db_hash,
        indexed_passages_sha256=sha(corpus_path), cases_sha256=sha(cases_path),
        code_sha256_lf={name:hashlib.sha256((ROOT/name).read_text(encoding='utf-8').encode()).hexdigest() for name in ['website_retrieval.py','tools/evaluate_retrieval_ablation.py']},
        model_catalog=json.loads((ROOT/'config/model-catalog/intfloat--multilingual-e5-small.json').read_text(encoding='utf-8-sig')),
        git_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        environment=dict(python=sys.version,platform=platform.platform()), llm_calls=0, training_performed=False,
        modes={mode:[] for mode in RANKING_MODES}, completed=False)
    report_path=output/'results.json'
    def save(): report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    save()
    for index,case in enumerate(cases):
        order=list(RANKING_MODES[index%len(RANKING_MODES):]+RANKING_MODES[:index%len(RANKING_MODES)])
        for mode in order:
            started=time.perf_counter()
            result=retriever.search(case['query'],limit=5,mode=mode)
            if result['corpus_id'] != report['corpus_id']: raise RuntimeError('Corpus changed during comparison.')
            matches=[rank for rank,source in enumerate(result['candidates'],1)
                     if case['kind']=='source_support' and source['url']==case['expected_url']
                     and normalize(case['expected_phrase']) in normalize(source['text'])]
            report['modes'][mode].append(dict(**case,support_rank=matches[0] if matches else None,
                latency_ms=round((time.perf_counter()-started)*1000,2),backend=result['backend'],
                candidates=[{key:s.get(key) for key in ['source_id','url','text','source_locator','score','lexical_score','dense_score']} for s in result['candidates']]))
        save()
        print(case['id'], ' '.join(f"{m}:{report['modes'][m][-1]['support_rank']}" for m in RANKING_MODES),flush=True)
    if sha(retriever.database) != db_hash: raise RuntimeError('Source database mutated during comparison.')
    report.update(completed=True,summary={mode:summarize(rows) for mode,rows in report['modes'].items()},retriever_status=retriever.status())
    save()
    print(json.dumps(report['summary'],ensure_ascii=False))
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases',type=Path,default=ROOT/'data/rag-source-dev-20261012.json')
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    evaluate(args.cases,args.output_dir)
