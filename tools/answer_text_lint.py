"""Count what makes a shown answer read like a machine, not like a person at the desk.

The user read the answers on 2026-11-22: «it is not an answer, just trash» — website menu
fragments, citation markers and notes such as «…үг өөрчлөхгүй нэгтгэн үзүүлэв» or
«Ойролцоо үгтэй хамааралгүй хэсгийг хариулт болгож харуулахгүй». This lint counts those
patterns in a saved run, so a wording change is measured before and after like any other
fix. It reads the text the visitor sees: the answer, or the note when there is no answer.

    .venv/Scripts/python.exe tools/answer_text_lint.py runtime/eval/system-<label>.json \
        [runtime/eval/probe-<label>.json ...] [--examples 3]

A pattern hit is a symptom, not a verdict: the list is for this project's wording only.
"""
import argparse
import json
from pathlib import Path
import re
import sys

PATTERNS = {
    'meta': [  # the system talking about its own rules instead of answering
        r'үг өөрчлөхгүй', r'нягтлаарай', r'орлуулахгүй', r'орлуулж\s+хариулахгүй', r'хариулт\s+болгож\s+харуулахгүй',
        r'хадгалсан\s+эх(?!\s+сурвалж)', r'хадгалсан\s+эх\s+сурвалж', r'эхийн\s+мэдээлэл', r'\(татсан:',
        r'батлахгүй', r'баталсангүй', r'баталж\s+чадсангүй', r'гэж\s+нийтэлсэн', r'бүртгэлд\s+заасан',
        r'бүртгэсэн\s+үндсэн', r'гэжээ', r'баталгаатай\s+мэдээлэл', r'Эдгээр\s+нь\s+ерөнхий', r'хамрах\s+хүрээ',
        r'регистр,\s+паспорт', r'тайлбарлажээ', r'дурдсан\.', r'Эхийн\s+он', r'Эхийн\s+огноо',
        # 11/23 (2): read in the probe banks after the first count had called them clean.
        r'Тааж\s+нэгтгэхгүй', r'хадгалсан\s+асуулт', r'хүснэгтэд\s+бүртгэгдээгүй', r'хайлтын\s+эх(?:ээр|ээс)',
        r'батлах\s+(?:тохирох\s+)?эх(?!\s+сурвалж)', r'батлагдаагүй', r'FAQ',
    ],
    'reception_referral': [r'ресепшний\s+ажилтнаас'],  # pointless for a system that stands at the reception
    'nav': [  # website menu, breadcrumb and form fragments
        r'Бүх\s+мэдээ', r'Мэдээ,\s+мэдээлэл', r'Нүүр\s+Тэнхимүүд', r'Академик\s+бүтэц', r'(?<!\d)0\s+хөтөлбөр',
        r'Холбоо\s+барих\s+\d', r'Мэдэгдэл\s+илгээх', r'Сонгоно\s+уу', r'\.\.\.\s*Дэлгэрэнгүй|Дэлгэрэнгүй\s+(?:\d|Мэдээ)',
        r'Тэнхимийн\s+тухай\s+(?:Хөтөлбөр|Багш)', r'Хаяг\s+мэдээлэл\s+Хаяг',
        r'[\U0001F300-\U0001FAFF☀-➿]',
    ],
    'marker': [r'\[\d+\]'],
    'wrong_hours': [r'09:00\s*[-–]\s*18:00'],  # the website's hours; the school confirmed 08:00–17:00 (11/19)
    'lowercase_part': [r'(?m)^[а-яёөү][^\n]{0,80}\?$'],  # a compound part echoed in lower case
}
COMPILED = {name: [re.compile(p) for p in patterns] for name, patterns in PATTERNS.items()}


def shown(row):
    """The text the visitor reads: the answer, or the note when there is no answer."""
    answer = (row.get('answer') if 'answer' in row else row.get('text')) or ''
    return answer if answer.strip() else (row.get('message') or row.get('text') or '')


def rows_of(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if isinstance(data, dict) and 'rows' in data:
        return [(r.get('id') or r.get('query'), r.get('query'), shown(r)) for r in data['rows']]
    if isinstance(data, dict) and ('single' in data or 'followup' in data):
        return [(r.get('query'), r.get('query'), r.get('text') or '') for r in data.get('single', []) + data.get('followup', [])]
    raise ValueError(f'{path}: not a system or probe run')


def lint(text):
    return {name: [p.pattern for p in patterns if p.search(text)] for name, patterns in COMPILED.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('runs', nargs='+')
    parser.add_argument('--examples', type=int, default=0)
    args = parser.parse_args()
    for path in args.runs:
        rows = rows_of(path)
        counts = {name: 0 for name in PATTERNS}
        examples = {name: [] for name in PATTERNS}
        clean = 0
        for ident, query, text in rows:
            hits = lint(text)
            clean += not any(hits.values())
            for name, matched in hits.items():
                if matched:
                    counts[name] += 1
                    if len(examples[name]) < args.examples:
                        flat = re.sub(r'\s+', ' ', text)[:150]
                        examples[name].append(f'{ident}: {flat}')
        print(f'== {path}: {len(rows)} replies, {clean} without any flag')
        print('   ' + '  '.join(f'{name}={count}' for name, count in counts.items()))
        for name, items in examples.items():
            for item in items:
                print(f'   [{name}] {item}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
