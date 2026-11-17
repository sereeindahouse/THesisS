"""Same code, data and Python; one config value off vs on, over every question set.

For each setting a private development server is started (the generator reads its config
once, at start), then the 50-question draft set with the locked reception set is asked
over HTTP (tools/evaluate_system.py), and the W04 / W04-b sets are run in-process
(tools/evaluate_locked_questions.py). The config file is always restored; the main server
is never touched.

    .venv/Scripts/python.exe tools/run_config_comparison.py --label typed-20261117 \
        --file config/answer-selection.json --key typed_value_check --values false true
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from run_planner_comparison import QUESTIONS, server_python, wait_ready  # noqa: E402

LOCKED_SETS = (('w04', 'data/rag-locked-questions-20261102.json'), ('w04b', 'data/rag-locked-questions-20261104b.json'))


def run_sets(label, port):
    environment = dict(os.environ, PYTHONIOENCODING='utf-8')
    out = ROOT / 'runtime/eval' / f'system-{label}.json'
    result = subprocess.run([sys.executable, str(ROOT / 'tools/evaluate_system.py'), str(QUESTIONS), '--port', str(port),
                             '--out', str(out)], capture_output=True, text=True, encoding='utf-8', env=environment)
    print(f'== {label}', *[line for line in result.stdout.splitlines() if '/all ' in line or line.startswith(
        ('test/answerable', 'test/reception', 'test/compound'))], sep='\n', flush=True)
    for name, path in LOCKED_SETS:
        locked = subprocess.run([server_python(), '-X', 'utf8', str(ROOT / 'tools/evaluate_locked_questions.py'),
                                 '--set', str(ROOT / path), '--run', str(ROOT / 'runtime/eval' / f'{name}-{label}.json')],
                                capture_output=True, text=True, encoding='utf-8', env=environment)
        print(f'   {name}:', (locked.stdout.strip().splitlines() or [locked.stderr[-500:]])[-1], flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label', required=True)
    parser.add_argument('--file', required=True)
    parser.add_argument('--key', required=True)
    parser.add_argument('--values', nargs='+', required=True, help='JSON values, e.g. false true')
    parser.add_argument('--port', type=int, default=8768)
    args = parser.parse_args()
    path = ROOT / args.file
    before = path.read_text(encoding='utf-8')
    try:
        for raw in args.values:
            value = json.loads(raw)
            data = json.loads(before)
            data[args.key] = value
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            process = subprocess.Popen([server_python(), '-X', 'utf8', str(ROOT / 'demo_server.py'), '--port', str(args.port)],
                                       cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                wait_ready(args.port)
                run_sets(f'{args.key}-{raw}-{args.label}', args.port)
            finally:
                process.terminate()
                process.wait(timeout=60)
    finally:
        path.write_text(before, encoding='utf-8')
        print('config restored', flush=True)


if __name__ == '__main__':
    main()
