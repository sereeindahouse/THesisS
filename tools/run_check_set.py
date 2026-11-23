"""Start a private server from the working tree, ask a question set, save every shown answer (2026-11-23).

    .venv/Scripts/python.exe tools/run_check_set.py <label> [--port 8769] [--questions data/eval/...json]

The default set is the 40 check questions (local only: they name school staff). The user allowed on 11/23 that
they are used to improve the system, so their scores are development scores, not a final evaluation. The output
(runtime/eval/q40-<label>.json) keeps the full answer and message of each question for reading them by eye.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from run_planner_comparison import server_python, wait_ready  # noqa: E402
import evaluate_system as ev  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument('label')
parser.add_argument('--port', type=int, default=8769)
parser.add_argument('--questions', default='data/eval/system-questions-draft-20261122.json')
parser.add_argument('--keep', action='store_true', help='leave the server running')
args = parser.parse_args()
sys.stdout.reconfigure(encoding='utf-8')

data = json.loads((ROOT / args.questions).read_text(encoding='utf-8'))
questions = [ev.normalise(q) for q in data['questions']]
process = subprocess.Popen([server_python(), '-X', 'utf8', str(ROOT / 'demo_server.py'), '--port', str(args.port)],
                           cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    wait_ready(args.port)
    rows = []
    for q in questions:
        result = ev.ask(q['query'], args.port)
        row = dict(id=q['id'], kind=q['kind'], expect=q.get('expect'), query=q['query'], **ev.score(q, result),
                   route=result.get('route'), reason_code=result.get('reason_code'),
                   answer_kind=result.get('answer_kind'), answer=ev.answer_text(result),
                   message=result.get('message') or '', referral_detail=result.get('referral'),
                   sources=ev.shown_sources(result)[:3], parts=len(result.get('parts') or []),
                   gold=dict(required=q.get('required_values'), any_of=q.get('any_of'), source_url=q.get('source_url'),
                             gold_quote=q.get('gold_quote'), office=q.get('expected_office'),
                             room=q.get('expected_room'), floor=q.get('expected_floor')))
        rows.append(row)
    out = ROOT / 'runtime/eval' / f'q40-{args.label}.json'
    out.write_text(json.dumps(dict(label=args.label, rows=rows, summary=ev.summarise(
        [dict(r, split='test') for r in rows])), ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    summary = ev.summarise([dict(r, split='test') for r in rows])
    for key, counter in summary.items():
        cells = [f"n={counter['n']}"]
        for measure in ('answered_correct', 'source_top3', 'abstain_correct', 'wrong_answer'):
            if counter.get(measure + '_n'):
                cells.append(f"{measure}={counter[measure]}/{counter[measure + '_n']}")
        print(f'{key:24} ' + '  '.join(cells))
    print('not passing:', [r['id'] for r in rows if r.get('answered_correct') is False or r.get('abstain_correct') is False])
    print('saved', out)
finally:
    if not args.keep:
        process.terminate()
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
