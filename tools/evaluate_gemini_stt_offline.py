"""Offline: score saved Gemini transcripts, the search-only correction and the chat answer.

Sends nothing. Reads the frozen 10/29 manifest (references, critical slots) and a
saved results.jsonl, then compares every arm in it on the clips all arms share.
With --search-arm A, an extra arm "A_search" is A after stt_text_normalization
(search copy only). On the 11/03 run the arms are baseline and vocabulary.

Downstream, each text goes through the local chat route (ChatRAG, LLM off) and is
compared with the answer for the typed reference, its spoken numbers written as
digits the way a person types them. That agreement is an automatic proxy, not
human correctness: a stricter number guard can refuse where the typed words passed. Private per-clip rows stay under runtime/; stdout
prints aggregates only (plus, with --show-term-errors, single error tokens).

    .venv/Scripts/python.exe tools/evaluate_gemini_stt_offline.py
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from score import score  # noqa: E402
from stt_text_normalization import Normalizer  # noqa: E402
from tools.stt_normalization_metrics import annotate_reference, score_texts  # noqa: E402

MANIFEST = 'runtime/stt-candidate-20261029/manifest.json'
RESULTS = 'runtime/stt-vocabulary-ab-20261103/results.jsonl'
OUTPUT = 'runtime/stt-gemini-offline-20261104'
MODEL = 'gemini-3.5-transcribe'
DIGITS = Normalizer(enabled=True, normalize_vocabulary=False)


def paired(manifest, saved):
    """Confirmed human rows and arm -> id -> text for the clips every arm has."""
    rows = [row for row in manifest['human_rows'] if row.get('reference_status') == 'eligible_speaker_confirmed']
    texts = {}
    for record in saved:
        if isinstance(record.get('text'), str):
            if record.get('model') != MODEL:
                raise ValueError('Saved output from a different model.')
            texts.setdefault(record['arm'], {})[record['id']] = record['text']
    ids = [row['id'] for row in rows if all(row['id'] in arm for arm in texts.values())]
    cohort = dict(human_clips=len(rows), paired_clips=len(ids), ids=ids, arms=sorted(texts),
                  failed_records=sum(bool(r.get('error')) for r in saved))
    return [row for row in rows if row['id'] in ids], {arm: {i: t[i] for i in ids} for arm, t in texts.items()}, cohort


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def answer_key(result):
    """What the user would get: kind, stored answer text and first cited source."""
    citations = result.get('citations') or []
    first = citations[0] if citations else {}
    return dict(answer_kind=result.get('answer_kind'), route=result.get('route'),
                has_answer=bool(result.get('answer')),
                answer_sha256=hashlib.sha256(str(result.get('answer') or '').encode()).hexdigest()[:16],
                first_source=first.get('document_id') or first.get('source_id') or first.get('url'))


def same_answer(reference, hypothesis):
    if reference['has_answer'] != hypothesis['has_answer']:
        return False
    if reference['has_answer']:
        return reference['answer_sha256'] == hypothesis['answer_sha256']
    return reference['first_source'] == hypothesis['first_source']


def value_wer(rows, texts):
    """Extra metric: spoken and digit numbers compared by value on both sides.

    The strict WER above stays the reported WER; this only shows how many word
    errors remain once '2026' and 'хоёр мянга хорин зургаан' count as equal.
    """
    numbers = Normalizer(enabled=True, normalize_vocabulary=False)
    pairs = [dict(id=row['id'], reference=numbers.normalize(row['reference'])['normalized_search_text'],
                  hypothesis=numbers.normalize(texts[row['id']])['normalized_search_text']) for row in rows]
    result = score(pairs)
    return dict(word_edit_errors=result['word_edit_errors'], reference_words=result['reference_words'],
                corpus_wer=result['corpus_wer'])


def text_arms(texts, terms, search_arm=None):
    arms, replacements = dict(texts), Counter()
    if search_arm:
        normalizer = Normalizer(enabled=True, terms=list(terms))
        searched = {}
        for identity, text in texts[search_arm].items():
            prepared = normalizer.normalize(text)
            searched[identity] = prepared['normalized_search_text']
            replacements.update(item['kind'] for item in prepared['replacements'])
        arms[search_arm + '_search'] = searched
    return arms, dict(replacements)


def downstream(rows, arms, database):
    from project_policy import ContentUsePolicy
    from rag_runtime import ChatRAG
    from stt_text_normalization import Normalizer as Off
    # The search arm is already normalized above; keep the runtime normalizer OFF
    # so no arm is corrected twice and production config is not consulted.
    rag = ChatRAG(ROOT, ContentUsePolicy(ROOT), normalizer=Off())
    private, totals = [], {arm: Counter() for arm in arms}
    for row in rows:
        reference = answer_key(rag.route(database, DIGITS.normalize(row['reference'])['normalized_search_text']))
        record = dict(id=row['id'], reference=reference)
        for arm, texts in arms.items():
            key = answer_key(rag.route(database, texts[row['id']]))
            match = same_answer(reference, key)
            record[arm] = dict(key, same_as_typed=match)
            totals[arm].update(same_as_typed=int(match), answered=int(key['has_answer']),
                               typed_answered=int(reference['has_answer']),
                               typed_answered_and_same=int(match and reference['has_answer']))
        private.append(record)
    return private, {arm: dict(counts, clips=len(rows)) for arm, counts in totals.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', default=MANIFEST)
    parser.add_argument('--results', default=RESULTS)
    parser.add_argument('--vocabulary', default='config/stt-vocabulary.json')
    parser.add_argument('--database', default='runtime/content.db')
    parser.add_argument('--output', default=OUTPUT)
    parser.add_argument('--search-arm', help='Also score this arm after the search-only normalization.')
    parser.add_argument('--skip-chat', action='store_true', help='Text metrics only.')
    parser.add_argument('--show-term-errors', action='store_true',
                        help='Print single error tokens for name/school-term/number events (no sentences).')
    args = parser.parse_args()
    manifest = json.loads((ROOT / args.manifest).read_text(encoding='utf-8'))
    saved = [json.loads(line) for line in (ROOT / args.results).read_text(encoding='utf-8').splitlines() if line.strip()]
    terms = json.loads((ROOT / args.vocabulary).read_text(encoding='utf-8'))['terms']
    rows, texts, cohort = paired(manifest, saved)
    arms, replacements = text_arms(texts, terms, args.search_arm)
    annotations = {row['id']: annotate_reference(row['reference'], row.get('critical_slots', []), terms)
                   for row in rows}
    summary = dict(created_utc=datetime.now(timezone.utc).isoformat(), network_calls=0, llm_calls=0,
                   manifest_sha256=_sha(ROOT / args.manifest), results_sha256=_sha(ROOT / args.results),
                   vocabulary_sha256=_sha(ROOT / args.vocabulary), cohort=cohort,
                   chat_reference='typed reference with spoken numbers as digits',
                   search_replacements=replacements,
                   scope='Нэг хэлэгчийн хадгалсан dev бичлэг; автомат proxy, хүний үнэлгээ эсвэл ерөнхий accuracy биш.')
    private = {}
    for arm, texts in arms.items():
        scored = score_texts(rows, texts, annotations, terms)
        private[arm] = scored.pop('rows')
        summary[arm] = dict(scored, value_wer=value_wer(rows, texts))
    if not args.skip_chat:
        chat_rows, chat = downstream(rows, arms, ROOT / args.database)
        summary['chat_agreement'] = chat
        private['chat'] = chat_rows
    output = ROOT / args.output
    output.mkdir(parents=True, exist_ok=True)
    (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    (output / 'private-rows.json').write_text(json.dumps(private, ensure_ascii=False, indent=2), encoding='utf-8')
    for arm in arms:
        m = summary[arm]
        line = [arm, f"WER {m['corpus_wer']:.2%} ({m['word_edit_errors']}/{m['reference_words']})",
                'value WER', f"{m['value_wer']['corpus_wer']:.2%}", 'categories', m['error_categories'], 'critical', m['critical_values']]
        if 'chat_agreement' in summary:
            line += ['chat same/typed', summary['chat_agreement'][arm]]
        print(*line)
    print('search replacements', replacements)
    if args.show_term_errors:
        for arm in arms:
            for event in (e for row in private[arm] for e in row['alignment']):
                if event['op'] != '=' and event.get('category') in {'name', 'school_term'}:
                    print(arm, event['category'], event['op'], event['reference'], '->', event['hypothesis'])


if __name__ == '__main__':
    main()
