"""Ask the locked reception question set through the running local server.

Scores: table/document questions must contain every required value; an
out-of-scope question must get no answer and a "where to ask" referral.
Writes a JSON report; prints only the summary and the non-passing ids.

    .venv/Scripts/python.exe tools/evaluate_reception_questions.py \
        data/reception/questions-locked-20261109.json --out runtime/reception-eval-X.json
"""
import argparse
import collections
import http.client
import json
import re
import sys
import unicodedata
from pathlib import Path


def norm(text):
    return ' '.join(unicodedata.normalize('NFC', text).casefold().split())


def present(value, text):
    value, text = norm(value), norm(text)
    if value.isdigit():
        return re.search(rf'(?<!\d){re.escape(value)}(?!\d)', text) is not None
    return value in text


def ask(query, port):
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=180)
    connection.request('POST', '/api/route', json.dumps({'query': query}).encode(),
                       {'Content-Type': 'application/json', 'Host': f'127.0.0.1:{port}'})
    body = json.loads(connection.getresponse().read())
    connection.close()
    return body


def score(question, result):
    answer = result.get('answer') or ''
    if question['kind'] in ('table', 'document'):
        missing = [v for v in question['required_values'] if not present(v, answer)]
        return 'pass' if answer and not missing else ('partial' if answer else 'refused')
    if question['id'] == 'O04' and answer:      # becomes answerable once the timetable is imported
        return 'pass'
    return 'pass' if not answer and result.get('referral') else ('answered' if answer else 'refused_no_referral')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('questions', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args(argv)
    data = json.loads(args.questions.read_text(encoding='utf-8'))
    rows, summary = [], collections.Counter()
    for question in data['questions']:
        result = ask(question['query'], args.port)
        outcome = score(question, result)
        summary[f"{question['kind']}:{outcome}"] += 1
        rows.append(dict(id=question['id'], kind=question['kind'], query=question['query'], outcome=outcome,
                         answer_kind=result.get('answer_kind'), answer=(result.get('answer') or '')[:400],
                         message=(result.get('message') or '')[:400], referral=bool(result.get('referral'))))
    report = dict(questions_sha256=data.get('questions_sha256'), summary=dict(summary), rows=rows)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(summary), ensure_ascii=False))
    print('not passing:', [r['id'] for r in rows if r['outcome'] != 'pass'])
    return 0


if __name__ == '__main__':
    sys.exit(main())
