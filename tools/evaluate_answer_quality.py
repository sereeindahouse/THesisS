"""Capture question/field/reference/output/evidence/timing for separate human review.

No automatic correctness score is inferred from route, phrase hits or citations.
Outputs are private by default and must not overwrite a previous run.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def run(cases_path, output, base_url):
    # This collector intentionally sends questions only to the local thesis demo.
    from urllib.parse import urlsplit
    parts = urlsplit(base_url)
    if parts.scheme != 'http' or parts.hostname not in {'127.0.0.1', 'localhost'} or parts.username or parts.password or parts.path not in {'', '/'} or parts.query or parts.fragment:
        raise ValueError('Use the local loopback demo URL.')
    bundle = json.loads(cases_path.read_text(encoding='utf-8-sig'))
    cases = bundle['cases']
    ids = set()
    for case in cases:
        if not all(case.get(k) for k in ('id', 'query', 'requested_attribute', 'expected_behavior')) or case['id'] in ids:
            raise ValueError('Cases require unique id, query, requested_attribute and expected_behavior.')
        ids.add(case['id'])
    output.parent.mkdir(parents=True, exist_ok=True)
    # Reserve the output before issuing requests. Preserve even interrupted runs.
    with output.open('x', encoding='utf-8') as handle:
        handle.write('{}\n')
    tracked = ['rag_runtime.py', 'answer_contract.py', 'website_retrieval.py', 'demo_server.py',
               'voice_runtime.py', 'llm_runtime.py', 'CORE/document_corpus.py', 'CORE/database/website.db',
               'runtime/content.db', 'CORE/website/document-excerpts-20261012.json',
               'config/model-catalog/gemma3-4b-text.json', 'runtime/rag-model.json']
    report = dict(created_utc=datetime.now(timezone.utc).isoformat(),
        label_scope=bundle.get('label_scope', 'Unreviewed'), cases_sha256=sha(cases_path),
        artifact_sha256={name: sha(ROOT/name) for name in tracked},
        git_head=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        git_dirty=bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True)),
        environment=dict(python=sys.version, platform=platform.platform()),
        correctness_score=None, independent_human_evaluation=False, cases=[])
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def save():
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    save()
    for case in cases:
        row = dict(case, human_review=dict(reviewer=None, correctness=None, citation_support=None,
            completeness=None, appropriate_abstention=None, error_category=None, notes=None))
        payload = json.dumps(dict(query=case['query'], allow_draft=False), ensure_ascii=False).encode()
        request = urllib.request.Request(base_url.rstrip('/')+'/api/route', data=payload,
            headers={'Content-Type': 'application/json', 'Origin': base_url.rstrip('/')})
        start = time.perf_counter()
        try:
            with opener.open(request, timeout=125) as response:
                row['response'] = json.load(response)
            row['http_wall_ms'] = round((time.perf_counter()-start)*1000, 2)
        except Exception as error:
            row.update(http_wall_ms=round((time.perf_counter()-start)*1000, 2), error=type(error).__name__+': '+str(error))
        report['cases'].append(row)
        save()
        result = row.get('response', {})
        print(case['id'], result.get('route'), result.get('reason_code'), row['http_wall_ms'], row.get('error', ''), flush=True)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--base-url', default='http://127.0.0.1:8765')
    args = parser.parse_args()
    run(args.cases, args.output, args.base_url)
