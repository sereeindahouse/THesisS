"""Paired retrieval comparison of the morphology channel on support-labelled questions.

One in-process retriever (E5 on when the local model loads) ranks every question with
each variant. A question counts as supported at k when an expected source is among the
first k production candidates (URL + phrase where the set records a phrase, URL only for
the 11/17 draft set). Choose a variant on the development rows; the draft set's «test»
split is reported, never used for choosing.

    .venv-modeltools/Scripts/python.exe tools/evaluate_morphology.py --out runtime/eval/morphology-20261117.json
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from website_retrieval import WebsiteRetriever
from tools.evaluate_source_retrieval import normalize

SETS = (('w04', 'data/rag-locked-questions-20261102.json'), ('w04b', 'data/rag-locked-questions-20261104b.json'),
        ('source_dev', 'data/rag-source-dev-20261012.json'), ('draft', 'data/eval/system-questions-draft-20261117.json'))
VARIANTS = {'off': False, 'light': ('light', 1.0), 'prefix4': ('prefix4', 1.0), 'prefix5': ('prefix5', 1.0),
            'light+prefix5': ('light+prefix5', 1.0), 'light_w0.5': ('light', 0.5)}


def load_cases():
    cases = []
    for name, path in SETS:
        data = json.loads((ROOT / path).read_text(encoding='utf-8-sig'))
        for q in data.get('questions') or data.get('cases'):
            if q.get('support'):
                targets = [(s['url'], s.get('phrase')) for s in q['support']]
            elif q.get('expected_url'):
                targets = [(q['expected_url'], q.get('expected_phrase'))]
            elif q.get('source_url'):
                targets = [(q['source_url'], None)]
            else:
                targets = []
            unanswerable = q.get('kind') in {'unanswerable', 'no_candidates'} or q.get('expect') == 'abstain'
            if not targets and not unanswerable:
                continue
            split = 'test' if name == 'draft' and q.get('split') == 'test' else 'dev'
            cases.append(dict(set=name, id=q['id'], query=q['query'], targets=targets,
                              unanswerable=unanswerable and not targets, split=split))
    return cases


def rank(case, candidates):
    for position, source in enumerate(candidates, 1):
        for url, phrase in case['targets']:
            if source['url'] == url and (not phrase or normalize(phrase) in normalize(source['text'])):
                return position
    return None


def summarise(rows):
    targets = [r for r in rows if not r['unanswerable']]
    controls = [r for r in rows if r['unanswerable']]
    return dict(target=len(targets), at1=sum(r['rank'] == 1 for r in targets),
                at3=sum(r['rank'] is not None and r['rank'] <= 3 for r in targets),
                at5=sum(r['rank'] is not None for r in targets),
                mrr5=round(sum(1 / r['rank'] for r in targets if r['rank']) / len(targets), 4) if targets else None,
                controls=len(controls), controls_without_candidates=sum(r['candidates'] == 0 for r in controls))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--database', type=Path, help='Website DB; default: the active release.')
    parser.add_argument('--lexical-only', action='store_true')
    args = parser.parse_args()
    if args.database is None:
        from content_release import ContentReleaseManager
        args.database = Path(ContentReleaseManager(ROOT).resolve()['website_database'])
    retriever = WebsiteRetriever(root=ROOT, database=args.database, use_dense=not args.lexical_only)
    cases = load_cases()
    report = dict(variants={k: list(v) if v else None for k, v in VARIANTS.items()}, rows={}, summary={})
    for name, setting in VARIANTS.items():
        rows = []
        for case in cases:
            result = retriever.search(case['query'], limit=5, morphology=setting)
            rows.append(dict(set=case['set'], id=case['id'], split=case['split'], unanswerable=case['unanswerable'],
                             rank=rank(case, result['candidates']), candidates=len(result['candidates']),
                             urls=[c['url'] for c in result['candidates']]))
        report['rows'][name] = rows
        report['summary'][name] = {split: summarise([r for r in rows if r['split'] == split]) for split in ('dev', 'test')}
        report['summary'][name]['backend'] = result['backend']
        print(name, json.dumps(report['summary'][name], ensure_ascii=False), flush=True)
    base = {(r['set'], r['id']): r for r in report['rows']['off']}
    for name in VARIANTS:
        if name == 'off':
            continue
        better = [f"{r['set']}:{r['id']}" for r in report['rows'][name] if not r['unanswerable']
                  and (r['rank'] or 9) < (base[(r['set'], r['id'])]['rank'] or 9) and r['split'] == 'dev']
        worse = [f"{r['set']}:{r['id']}" for r in report['rows'][name] if not r['unanswerable']
                 and (r['rank'] or 9) > (base[(r['set'], r['id'])]['rank'] or 9) and r['split'] == 'dev']
        report['summary'][name]['dev_paired'] = dict(better=better, worse=worse)
        print(name, 'dev better', len(better), 'worse', len(worse), worse[:12], flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
