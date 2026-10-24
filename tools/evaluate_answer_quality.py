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
RUNTIME_ARTIFACT_NAMES = ('rag_runtime.py', 'source_fields.py', 'historical_fields.py', 'question_router.py', 'answer_contract.py',
    'website_retrieval.py', 'CORE/website_corpus.py', 'CORE/document_corpus.py', 'CORE/client_tab_corpus.py', 'evidence_contract.py', 'speech_text.py')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def run(cases_path, output, base_url, validation_path=None, label_scope=None):
    # This collector intentionally sends questions only to the local thesis demo.
    from urllib.parse import urlsplit
    parts = urlsplit(base_url)
    if parts.scheme != 'http' or parts.hostname not in {'127.0.0.1', 'localhost'} or parts.username or parts.password or parts.path not in {'', '/'} or parts.query or parts.fragment:
        raise ValueError('Use the local loopback demo URL.')
    bundle = json.loads(cases_path.read_text(encoding='utf-8-sig'))
    reference_validation = None
    if bundle.get('source_snapshot_sha256'):
        if validation_path is None:
            raise ValueError('Frozen reference cases require --validation before collection.')
        reference_validation = json.loads(validation_path.read_text(encoding='utf-8-sig'))
        if (reference_validation.get('public_cases_sha256') != sha(cases_path)
                or reference_validation.get('source_snapshot_sha256') != bundle['source_snapshot_sha256']):
            raise ValueError('Reference cases changed after pre-registration validation.')
    cases = bundle['cases']
    ids = set()
    for case in cases:
        if not all(case.get(k) for k in ('id', 'query', 'requested_attribute', 'expected_behavior')) or case['id'] in ids:
            raise ValueError('Cases require unique id, query, requested_attribute and expected_behavior.')
        ids.add(case['id'])
    runtime_preflight = None
    opener = None
    if bundle.get('source_snapshot_sha256'):
        # A collector hash of disk files does not identify already imported
        # server modules. Reject a stale server before reserving any output.
        artifact_names = RUNTIME_ARTIFACT_NAMES
        expected_artifacts = {name: sha(ROOT/name) for name in artifact_names}
        if any(value is None for value in expected_artifacts.values()):
            raise ValueError('Runtime fingerprint requires all required local code files.')
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        status_request = urllib.request.Request(base_url.rstrip('/')+'/api/status',
            headers={'Origin': base_url.rstrip('/')})
        try:
            with opener.open(status_request, timeout=15) as response:
                status = json.load(response)
        except Exception as error:
            raise ValueError('Could not validate the running server code fingerprint.') from error
        rag = status.get('rag') if isinstance(status, dict) else None
        loaded = rag.get('loaded_artifact_sha256') if isinstance(rag, dict) else None
        if (not isinstance(loaded, dict) or any(
                loaded.get(name) != expected for name, expected in expected_artifacts.items())):
            raise ValueError('Running server code differs from local files; restart before frozen collection.')
        runtime_preflight = dict(captured_utc=datetime.now(timezone.utc).isoformat(),
            status=status, expected_artifact_sha256=expected_artifacts, matched=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Reserve before answer requests. Preserve even interrupted answer runs.
    with output.open('x', encoding='utf-8') as handle:
        handle.write('{}\n')
    tracked = ['tools/evaluate_answer_quality.py', 'tools/validate_answer_cases.py',
               'source_fields.py', 'historical_fields.py', 'rag_runtime.py', 'answer_contract.py', 'website_retrieval.py', 'demo_server.py',
               'voice_runtime.py', 'llm_runtime.py', 'CORE/website_corpus.py', 'CORE/document_corpus.py', 'CORE/client_tab_corpus.py', 'CORE/database/website.db',
               'runtime/content.db', 'evidence_contract.py', 'speech_text.py', 'CORE/website/document-excerpts-20261012.json',
               'config/model-catalog/gemma3-4b-text.json', 'runtime/rag-model.json']
    report = dict(created_utc=datetime.now(timezone.utc).isoformat(),
        label_scope=label_scope or bundle.get('label_scope', 'Unreviewed'),
        input_label_scope=bundle.get('label_scope', 'Unreviewed'), cases_sha256=sha(cases_path),
        artifact_sha256={name: sha(ROOT/name) for name in tracked},
        git_head=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        git_dirty=bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True)),
        environment=dict(python=sys.version, platform=platform.platform()),
        correctness_score=None, independent_human_evaluation=False,
        reference_validation=reference_validation,
        reference_validation_sha256=sha(validation_path) if validation_path else None,
        runtime_preflight=runtime_preflight, cases=[])
    if opener is None:
        # Legacy, non-frozen collections retain their existing no-preflight path.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def save():
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    save()
    for case in cases:
        row = dict(case, human_review=dict(reviewer=None, correctness=None, citation_support=None,
            completeness=None, appropriate_abstention=None, response_appropriateness=None, error_category=None, notes=None))
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
    parser.add_argument('--validation', type=Path, help='Frozen reference validation report; must match input cases.')
    parser.add_argument('--label-scope', help='Run-specific scope, e.g. observed development rerun; preserves original input label separately.')
    args = parser.parse_args()
    run(args.cases, args.output, args.base_url, args.validation, args.label_scope)
