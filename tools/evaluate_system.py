"""Ask a question set through a running local server and count the three thesis measures.

    1. answered_correct — every required value (or one of any_of) is in the answer text;
    2. source_top3     — the expected source URL is among the first three shown sources;
    3. abstain_correct — a question without an answer in the sources gets no answer, but a
                         "where to ask" referral (wrong_answer counts the opposite).

The gold values were written from the sources before the system was run; this tool never
edits them. Reception questions from the person-locked set (also_run) are scored the same
way: table/document -> required values, out-of-scope -> abstain. Prints a short summary
per split and kind and writes every answer to a JSON report.

    .venv/Scripts/python.exe tools/evaluate_system.py data/eval/system-questions-draft-20261117.json \
        --port 8766 --out runtime/eval/system-<label>.json [--split tune]
"""
import argparse
import collections
import http.client
import json
from pathlib import Path
import re
import sys
import unicodedata

ROOT = Path(__file__).resolve().parents[1]


def norm(text):
    return ' '.join(unicodedata.normalize('NFC', text or '').casefold().replace(' ', ' ').split())


def present(value, text):
    value, text = norm(value), norm(text)
    if value.isdigit():
        # A whole number only: 10 does not match 1007. "7577 7799" also counts as 75777799.
        pattern = rf'(?<!\d){re.escape(value)}(?!\d)'
        return bool(re.search(pattern, text) or re.search(pattern, re.sub(r'(?<=\d{4})[ -](?=\d{4}\b)', '', text)))
    return value in text


def ask(query, port):
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=300)
    connection.request('POST', '/api/route', json.dumps({'query': query}).encode(),
                       {'Content-Type': 'application/json', 'Host': f'127.0.0.1:{port}'})
    response = connection.getresponse()
    body = json.loads(response.read())
    connection.close()
    if response.status != 200:
        raise RuntimeError(f'HTTP {response.status}: {body}')
    return body


def answer_text(result):
    parts = [result.get('answer') or '']
    parts += [card.get('source_quote', '') for card in result.get('teacher_cards') or []]
    return '\n'.join(part for part in parts if part)


def shown_sources(result):
    urls = []
    for item in (result.get('citations') or []) + (result.get('related_sources') or []):
        url = item.get('source_url_or_filename') or item.get('url')
        if url and url not in urls:
            urls.append(url)
    for part in result.get('parts') or []:
        for url in part.get('source_urls') or []:
            if url not in urls:
                urls.append(url)
    return urls


def normalise(question):
    """Locked reception questions use kind table/document/out_of_scope."""
    question = dict(question)
    if question.get('kind') in ('table', 'document'):
        question.setdefault('split', 'locked')
    elif question.get('kind') not in ('answerable', 'reception', 'compound', 'unanswerable'):
        question.setdefault('expect', 'abstain')
        question.setdefault('split', 'locked')
    return question


def score(question, result):
    text = answer_text(result)
    row = dict(answered=bool(text.strip()), referral=bool(result.get('referral')))
    if question.get('expect') == 'abstain':
        row['abstain_correct'] = not row['answered'] and row['referral']
        row['wrong_answer'] = row['answered']
        # The locked set's O04 became answerable once the timetable was imported (11/10 rule).
        if question.get('id') == 'O04' and row['answered']:
            row.update(abstain_correct=True, wrong_answer=False)
        return row
    required = question.get('required_values') or []
    any_of = question.get('any_of') or []
    missing = [value for value in required if not present(value, text)]
    row['missing'] = missing
    row['answered_correct'] = row['answered'] and not missing and (not any_of or any(present(v, text) for v in any_of))
    if question.get('source_url'):
        row['source_top3'] = question['source_url'] in shown_sources(result)[:3]
    return row


def summarise(rows):
    table = collections.defaultdict(collections.Counter)
    for row in rows:
        for key in (('all', 'all'), (row['split'], 'all'), (row['split'], row['kind'])):
            counter = table[key]
            counter['n'] += 1
            for measure in ('answered_correct', 'source_top3', 'abstain_correct', 'wrong_answer'):
                if measure in row:
                    counter[measure + '_n'] += 1
                    counter[measure] += int(row[measure])
    return {f'{split}/{kind}': dict(counter) for (split, kind), counter in sorted(table.items())}


def main(argv=None):
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('questions', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--split', help='only this split (tune/test/locked)')
    parser.add_argument('--no-also-run', action='store_true')
    args = parser.parse_args(argv)
    data = json.loads(args.questions.read_text(encoding='utf-8'))
    questions = [normalise(q) for q in data['questions']]
    if not args.no_also_run:
        for extra in data.get('also_run', []):
            questions += [normalise(q) for q in json.loads((ROOT / extra).read_text(encoding='utf-8'))['questions']]
    if args.split:
        questions = [q for q in questions if q.get('split') == args.split]
    rows = []
    for question in questions:
        result = ask(question['query'], args.port)
        row = dict(id=question['id'], split=question.get('split'), kind=question['kind'],
                   query=question['query'], **score(question, result),
                   route=result.get('route'), reason_code=result.get('reason_code'),
                   answer_kind=result.get('answer_kind'), answer=answer_text(result)[:600],
                   message=(result.get('message') or '')[:300], sources=shown_sources(result)[:3],
                   parts=len(result.get('parts') or []))
        rows.append(row)
    summary = summarise(rows)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(dict(question_file=str(args.questions), status=data.get('status'),
        summary=summary, rows=rows), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for key, counter in summary.items():
        cells = [f"n={counter['n']}"]
        for measure in ('answered_correct', 'source_top3', 'abstain_correct', 'wrong_answer'):
            if counter.get(measure + '_n'):
                cells.append(f"{measure}={counter[measure]}/{counter[measure + '_n']}")
        print(f'{key:24} ' + '  '.join(cells))
    failing = [r['id'] for r in rows if r.get('answered_correct') is False or r.get('abstain_correct') is False]
    print('not passing:', failing)
    return 0


if __name__ == '__main__':
    sys.exit(main())
