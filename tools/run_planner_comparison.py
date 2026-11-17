"""Planner off / on (and optional knowledge-tree boost) on the same code, data and Python.

Starts a private development server on its own port with the same Python the launcher
uses for the main server (.venv-modeltools when complete, so E5 dense retrieval is on),
flips only config/question-planner.json (and, for --boost, config/knowledge-domains.json)
between runs, and always restores both files. The main server is never touched.

    .venv/Scripts/python.exe tools/run_planner_comparison.py --label 20261117 [--boost 0.02]
"""
import argparse
import http.client
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
PLANNER = ROOT / 'config/question-planner.json'
DOMAINS = ROOT / 'config/knowledge-domains.json'
QUESTIONS = ROOT / 'data/eval/system-questions-draft-20261117.json'


def server_python():
    candidate = ROOT / '.venv-modeltools/Scripts/python.exe'
    if candidate.is_file() and subprocess.run([str(candidate), '-c', 'import torch, transformers'],
                                              capture_output=True).returncode == 0:
        return str(candidate)
    raise SystemExit('.venv-modeltools with torch is required so dense retrieval matches the main server.')


def wait_ready(port, timeout=300):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            connection = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
            connection.request('GET', '/api/status')
            status = json.loads(connection.getresponse().read())
            connection.close()
            return status
        except (OSError, ValueError):
            time.sleep(3)
    raise SystemExit('development server did not start')


def run(label, port, extra_args=()):
    out = ROOT / 'runtime/eval' / f'system-{label}.json'
    result = subprocess.run([sys.executable, str(ROOT / 'tools/evaluate_system.py'), str(QUESTIONS),
                             '--port', str(port), '--out', str(out), *extra_args],
                            capture_output=True, text=True, encoding='utf-8', env={'PYTHONIOENCODING': 'utf-8',
                            **__import__('os').environ})
    summary = [line for line in result.stdout.splitlines() if line.split('/')[0] in {'tune', 'test', 'locked', 'all'}
               and '/all ' in line or line.startswith(('test/reception', 'test/compound', 'test/answerable'))]
    print(f'== {label}', *summary, sep='\n', flush=True)
    if result.returncode:
        print(result.stderr[-2000:], flush=True)


def with_server(port, body):
    process = subprocess.Popen([server_python(), '-X', 'utf8', str(ROOT / 'demo_server.py'), '--port', str(port)],
                               cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        status = wait_ready(port)
        print('dev server ready; dense:', json.dumps(status.get('rag', {}).get('retrieval', {}).get('dense_status')),
              flush=True)
        body()
    finally:
        process.terminate()
        process.wait(timeout=60)


def set_json(path, **changes):
    value = json.loads(path.read_text(encoding='utf-8'))
    value.update(changes)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label', required=True)
    parser.add_argument('--port', type=int, default=8767)
    parser.add_argument('--boost', type=float)
    args = parser.parse_args()
    planner_before, domains_before = PLANNER.read_text(encoding='utf-8'), DOMAINS.read_text(encoding='utf-8')
    try:
        set_json(PLANNER, enabled=False)
        with_server(args.port, lambda: run(f'planner-off-{args.label}', args.port))
        set_json(PLANNER, enabled=True)

        def on_runs():
            run(f'planner-on-{args.label}', args.port)
            if args.boost is not None:
                # The retriever reads this file per search; no restart is needed.
                set_json(DOMAINS, enabled=True, weight=args.boost)
                run(f'planner-on-boost-{args.boost}-{args.label}', args.port)
        with_server(args.port, on_runs)
    finally:
        PLANNER.write_text(planner_before, encoding='utf-8')
        DOMAINS.write_text(domains_before, encoding='utf-8')
        print('configs restored', flush=True)


if __name__ == '__main__':
    main()
