"""Same 13 human clips sent to Gemini with and without the school word list.

User approved on 2026-11-03 (plan: keen-toasting-lighthouse): re-send only the
13 clips already measured on 10/30, two arms each (26 calls at most), on the
saved free-tier key. No retry, no paid fallback; the first HTTP 429 stops the run.
Raw output stays under runtime/; transcripts and the key are never printed.

    .venv/Scripts/python.exe tools/compare_stt_vocabulary.py --dry-run
    .venv/Scripts/python.exe tools/compare_stt_vocabulary.py
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from score import normalize, score  # noqa: E402
from tools.compare_stt_candidate import (  # noqa: E402
    MODEL, CandidateError, GeminiTransport, capture_manifest, validate_vocabulary)

MANIFEST = 'runtime/stt-candidate-20261029/manifest.json'
OUTPUT = ROOT / 'runtime/stt-vocabulary-ab-20261103'
ARMS = ('baseline', 'vocabulary')


def slot_hits(rows, texts):
    """Predeclared name/number/year spans that appear verbatim after normalization."""
    found = total = 0
    for row in rows:
        for slot in row.get('critical_slots', []):
            total += 1
            found += normalize(slot['expected']) in normalize(texts.get(row['id'], ''))
    return dict(found=found, total=total)


def summarize(rows, results):
    texts = {arm: {r['id']: r['text'] for r in results if r['arm'] == arm and isinstance(r.get('text'), str)}
             for arm in ARMS}
    paired = [row for row in rows if all(row['id'] in texts[arm] for arm in ARMS)]
    summary = dict(paired_clips=len(paired), human_clips=len(rows))
    for arm in ARMS:
        if paired:
            metrics = score([dict(id=r['id'], reference=r['reference'], hypothesis=texts[arm][r['id']])
                             for r in paired])
            metrics.pop('rows')
            summary[arm] = dict(metrics, critical_slots=slot_hits(paired, texts[arm]))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', default=MANIFEST)
    parser.add_argument('--vocabulary', type=Path, default=ROOT / 'config/stt-vocabulary.json')
    parser.add_argument('--output', type=Path, default=OUTPUT)
    parser.add_argument('--dry-run', action='store_true', help='Validate inputs; send nothing.')
    args = parser.parse_args()
    captured = capture_manifest(args.manifest, root=ROOT)
    rows = [row for row in captured['rows'] if row['group'] == 'human']
    vocabulary = json.loads(args.vocabulary.read_text(encoding='utf-8'))
    terms = validate_vocabulary(vocabulary['terms'])
    plan = dict(model=MODEL, human_clips=len(rows), max_calls=len(rows) * len(ARMS),
                vocabulary_terms=len(terms), manifest_sha256=captured['manifest_sha256'])
    if args.dry_run:
        print(json.dumps(dict(plan, dry_run=True), ensure_ascii=False))
        return
    if args.output.exists():
        sys.exit(f'{args.output} байна; өмнөх raw-ийг дарахгүй.')
    from gemini_credentials import WindowsCredentialStore
    saved = WindowsCredentialStore(ROOT / 'runtime/gemini-credentials.dpapi').load()
    if not saved:
        sys.exit('Хадгалсан Gemini түлхүүр алга.')
    args.output.mkdir(parents=True)
    results, stopped = [], None
    for index, row in enumerate(rows):
        # Alternate which arm goes first so provider drift does not favour one arm.
        order = ARMS if index % 2 == 0 else ARMS[::-1]
        for arm in order:
            if stopped:
                break
            started = time.perf_counter()
            record = dict(id=row['id'], arm=arm)
            try:
                transport = GeminiTransport(saved['api_key'], vocabulary=terms if arm == 'vocabulary' else None)
                result = transport.transcribe(captured['audio_bytes'][row['id']],
                                              display_name=f"clip-{row['id']}-{arm}")
                record.update(text=result['text'], model=result.get('model'), usage=result.get('usage'),
                              cleanup=result.get('cleanup'))
            except CandidateError as error:
                record.update(error=error.code, partial=bool(error.partial_result))
                if error.code == 'http_429':
                    stopped = 'http_429'
            record['elapsed_seconds'] = round(time.perf_counter() - started, 3)
            results.append(record)
        if stopped:
            break
    with (args.output / 'results.jsonl').open('w', encoding='utf-8') as handle:
        for record in results:
            handle.write(json.dumps(record, ensure_ascii=False) + '\n')
    summary = dict(plan, created_utc=datetime.now(timezone.utc).isoformat(), calls=len(results),
                   errors=sum('error' in r for r in results), stopped=stopped, automatic_retry=False,
                   vocabulary_sha256=__import__('hashlib').sha256(
                       json.dumps(terms, ensure_ascii=False).encode()).hexdigest(),
                   scope='Нэг хэлэгчийн 13 dev бичлэг; ерөнхий accuracy биш, статистикийн ялгаа батлахгүй.',
                   **summarize(rows, results))
    (args.output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in summary.items() if k not in ARMS}, ensure_ascii=False))
    for arm in ARMS:
        if arm in summary:
            m = summary[arm]
            print(arm, f"WER {m['corpus_wer']:.2%} ({m['word_edit_errors']}/{m['reference_words']})",
                  f"CER {m['corpus_cer']:.2%}", 'slots', m['critical_slots'])


if __name__ == '__main__':
    main()
