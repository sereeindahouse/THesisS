"""Ask a running server a bank of probe questions and save what it answered.

A bank is JSON: {"single": [question, ...], "followup": [{"previous", "query", "expect", "entity"}, ...]}.
A follow-up pair asks the previous question first, then the follow-up with that question as
`context_query` (the page sends the same), unless --no-context measures the raw follow-up.
Staff mobiles never reach the output: the server hides them, and the saved text is masked again.

    .venv/Scripts/python.exe tools/probe_questions.py runtime/eval/probe-bank.json \
        --port 8765 --out runtime/eval/probe-<label>.json
"""
import argparse
import json
from pathlib import Path
import re
import sys
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from privacy_filter import hide_mobiles  # noqa: E402


def ask(port, query, context=None):
    body = {'query': query, **({'context_query': context} if context else {})}
    request = urllib.request.Request(f'http://127.0.0.1:{port}/api/route', data=json.dumps(body).encode('utf-8'),
                                     headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.load(response)


def row(query, result):
    text = result.get('answer') or result.get('message') or (result.get('clarification') or {}).get('question') or ''
    followup = (result.get('question_plan') or {}).get('followup') or {}
    return hide_mobiles(dict(query=query, route=result.get('route'), reason=result.get('reason_code'),
                             kind=result.get('answer_kind'), text=text, understood_as=followup.get('rewritten'),
                             office=(result.get('referral') or {}).get('office'),
                             citations=[c.get('title') for c in result.get('citations') or []][:3]))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('bank', type=Path)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--no-context', action='store_true', help='send follow-ups without the previous question')
    args = parser.parse_args()
    bank = json.loads(args.bank.read_text(encoding='utf-8'))
    single = [row(query, ask(args.port, query)) for query in bank.get('single', [])]
    pairs = []
    for pair in bank.get('followup', []):
        previous = ask(args.port, pair['previous'])
        context = None if args.no_context else (
            ((previous.get('question_plan') or {}).get('followup') or {}).get('rewritten') or pair['previous'])
        pairs.append(dict(pair, previous_reason=previous.get('reason_code'),
                          **row(pair['query'], ask(args.port, pair['query'], context))))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(dict(single=single, followup=pairs), ensure_ascii=False, indent=1), encoding='utf-8')
    for item in single + pairs:
        shown = re.sub(r'\s+', ' ', item['text'])[:110]
        print(f"{item['route']} {str(item['reason'])[:30]:<30} | {item['query'][:48]:<48} | "
              f"{('[' + item['understood_as'] + '] ') if item.get('understood_as') else ''}{shown}")


if __name__ == '__main__':
    main()
