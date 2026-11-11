"""Compare option А (no domain boost) with option Б (domain boost) on one locked question file.

Only a human-locked file of real questions is accepted. Each question has a
split: "tune" may be used to choose the keyword list and weight; "test" is
reported but must not be looked at while tuning. Results are development
retrieval ranks (is the expected page among the first k pages), not answer
accuracy.

    .venv/Scripts/python.exe tools/compare_domain_boost.py QUESTIONS.json --out runtime/domain-boost-X.json

Question file:
    {"status": "locked", "lock_kind": "person", "locked_by": "...",
     "questions": [{"id": "R01", "query": "...", "split": "tune",
                    "expected_domain": "admissions", "expected_url": "https://nmct.edu.mn/..."}]}
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from website_retrieval import WebsiteRetriever, load_domains, predict_domain


def first_rank(urls, url):
    return urls.index(url) + 1 if url in urls else None


def summarize(rows):
    summary = {}
    for split in sorted({row['split'] for row in rows}):
        part = [row for row in rows if row['split'] == split]
        with_domain = [row for row in part if row.get('expected_domain')]
        with_url = [row for row in part if row.get('expected_url')]
        summary[split] = dict(
            questions=len(part),
            domain_correct=sum(row['predicted_domain'] == row['expected_domain'] for row in with_domain),
            domain_none=sum(row['predicted_domain'] is None for row in with_domain),
            domain_labelled=len(with_domain),
            url_labelled=len(with_url),
            **{f'{arm}_at_{k}': sum(row[arm] is not None and row[arm] <= k for row in with_url)
               for arm in ('A_rank', 'B_rank') for k in (1, 3)})
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('questions', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--database', type=Path, help='website.db to search (default: the project copy)')
    parser.add_argument('--limit', type=int, default=5)
    args = parser.parse_args(argv)
    data = json.loads(args.questions.read_text(encoding='utf-8'))
    if data.get('status') != 'locked' or data.get('lock_kind') != 'person':
        raise SystemExit('Refusing: the question file must be locked by a person (status=locked, lock_kind=person).')
    questions = data['questions']
    ids = [q['id'] for q in questions]
    if len(set(ids)) != len(ids) or any(q.get('split') not in ('tune', 'test') for q in questions):
        raise SystemExit('Refusing: ids must be unique and every split must be "tune" or "test".')
    domains = (load_domains(ROOT) or {}).get('domains')
    retriever = WebsiteRetriever(root=ROOT, database=args.database)
    rows = []
    for question in questions:
        arms = {}
        for arm, boost in (('A', False), ('B', True)):
            result = retriever.search(question['query'], args.limit, domain_boost=boost)
            arms[arm] = [row.get('url') for row in result['candidates']]
        rows.append(dict(
            id=question['id'], split=question['split'], query=question['query'],
            expected_domain=question.get('expected_domain'), expected_url=question.get('expected_url'),
            predicted_domain=predict_domain(question['query'], domains),
            A_urls=arms['A'], B_urls=arms['B'],
            A_rank=first_rank(arms['A'], question.get('expected_url')),
            B_rank=first_rank(arms['B'], question.get('expected_url'))))
    report = dict(created_utc=datetime.now(timezone.utc).isoformat(), questions_file=str(args.questions),
                  domains_config=json.loads((ROOT / 'config/knowledge-domains.json').read_text(encoding='utf-8')),
                  scope='Development retrieval ranks on one locked file; not answer accuracy.',
                  summary=summarize(rows), rows=rows)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report['summary'], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
