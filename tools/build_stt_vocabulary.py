"""Gemini-ийн дуу танилтад өгөх сургуулийн үгийн жагсаалт (`custom_vocabulary`).

Эх: мэдлэгийн модны нэрс, хадгалсан сайтын тэнхим, хөтөлбөр, тэнхимийн
эрхлэгчийн нийтэлсэн нэр. DB-г зөвхөн уншина; сүлжээ, загвар ажиллуулахгүй.
Гаралт анхдагчаар унтраалттай (`"enabled": false`); хэмжиж сайжирвал л асаана.

    .venv/Scripts/python.exe tools/build_stt_vocabulary.py
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tools'))
from build_knowledge_tree import build_tree, load_inputs  # noqa: E402
from tools.compare_stt_candidate import MODEL, validate_vocabulary  # noqa: E402

OUTPUT = ROOT / 'config/stt-vocabulary.json'
LIMIT = 100  # Google: up to 1000 phrases, about 100 usually works best.
SKIP_TOPICS = {'nmct', 'review-needed'}
SCHOOL = ['Шинэ Монгол Технологийн Коллеж', 'ШМТК', 'Шинэ Монгол Коосэн', 'Коосэн', 'NMCT']
YEARS = ['2026', '2027', '2026–2027']
HEAD = re.compile(r'Тэнхимийн эрхлэгч\s*:\s*([А-ЯЁӨҮ][А-ЯЁӨҮа-яёөү.]*[а-яёөү])')
PROGRAM_CODE = re.compile(r'^\d{6}\s+')


def published(value):
    if isinstance(value, dict):
        value = value.get('published_clause', '')
    if isinstance(value, list):
        return [str(item) for item in value]
    return [line for line in str(value).splitlines()]


def collect(config, tree):
    facts = {f['payload']['fact_id']: f['payload']['value'] for f in tree['records']['facts']}
    groups = [('school', SCHOOL)]
    groups.append(('departments', [name for key, value in facts.items()
                                   if key.startswith('school.departments.') for name in published(value)]))
    groups.append(('programs', [PROGRAM_CODE.sub('', line).strip() for key, value in facts.items()
                                if key.startswith('admission.programs.') for line in published(value)
                                if PROGRAM_CODE.match(line)]))
    groups.append(('department_heads', [m.group(1) for page in tree['records']['pages']
                                        for m in HEAD.finditer(page['payload'].get('full_text', ''))]))
    groups.append(('japan_programs', ['Sakura', 'ARC'] + [name for key, value in facts.items()
                                                         if key == 'cs.arc.courses' for name in published(value)]))
    groups.append(('topics', [part.strip() for topic in config['topics'] if topic['topic_id'] not in SKIP_TOPICS
                              for part in topic['label_mn'].split(',') if 0 < len(part.split()) <= 3]))
    groups.append(('years', YEARS))
    terms, seen, counts = [], set(), {}
    for name, values in groups:
        for value in values:
            key = value.casefold()
            if value and key not in seen and len(terms) < LIMIT:
                seen.add(key)
                terms.append(value)
                counts[name] = counts.get(name, 0) + 1
    return validate_vocabulary(terms), counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    parser.add_argument('--force', action='store_true', help='Гараар засварласан файлыг дарж бичих.')
    args = parser.parse_args()
    if args.output.exists() and not args.force:
        sys.exit(f'{args.output} байна. Таны засварыг дарахгүйн тулд зогслоо; --force эсвэл өөр --output.')
    config = json.loads((ROOT / 'config/knowledge-topics.json').read_text(encoding='utf-8-sig'))
    terms, counts = collect(config, build_tree(config, load_inputs(ROOT)))
    value = dict(
        schema_version=1,
        enabled=False,
        model=MODEL,
        purpose_mn='Gemini-д сургуулийн нэр, тэнхим, хөтөлбөр, оныг таниулах жагсаалт. '
                   'Анхдагчаар унтраалттай; ижил бичлэгээр хэмжиж сайжирвал л асаана.',
        sources_mn=['config/knowledge-topics.json', 'хадгалсан сайтын тэнхим, хөтөлбөр, эрхлэгчийн нэр (2026.10)'],
        provider_limit='custom_vocabulary: 1000 хүртэл; ~100 хамгийн сайн (ai.google.dev/gemini-api/docs/transcribe)',
        counts=counts,
        terms=terms)
    args.output.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(output=str(args.output), terms=len(terms), counts=counts), ensure_ascii=False))


if __name__ == '__main__':
    main()
