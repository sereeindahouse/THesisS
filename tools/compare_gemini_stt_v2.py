"""Same-day Gemini A/B/C on the 12 paired dev clips: word list v1, word list v2, v2 + audio cleanup.

User approved on 2026-11-04 (thesis session, plan steps 1-4): re-send only the
12 clips paired on 11/03, three arms each (36 calls at most), on the saved
free-tier key. No retry, no paid fallback; the first HTTP 429 stops the run.
Raw output stays under runtime/; transcripts and the key are never printed.
Scoring is offline: tools/evaluate_gemini_stt_offline.py --results <this run>.

    .venv/Scripts/python.exe tools/compare_gemini_stt_v2.py --dry-run
    .venv/Scripts/python.exe tools/compare_gemini_stt_v2.py --pause 5
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from audio_preprocess import clean_wav  # noqa: E402
from tools.compare_stt_candidate import (  # noqa: E402
    MODEL, CandidateError, GeminiTransport, capture_manifest, validate_vocabulary)

MANIFEST = 'runtime/stt-candidate-20261029/manifest.json'
PAIRED_RUN = ROOT / 'runtime/stt-vocabulary-ab-20261103/results.jsonl'
OUTPUT = ROOT / 'runtime/stt-gemini-v2-20261104'
# arm -> (vocabulary file, cleaned audio)
ARMS = {'vocabulary': ('config/stt-vocabulary-v1-20261103.json', False),
        'vocabulary_v2': ('config/stt-vocabulary.json', False),
        'vocabulary_v2_clean': ('config/stt-vocabulary.json', True)}


def paired_ids():
    """The 12 clips that had both arms on 11/03; same cohort, no new selection."""
    arms = {}
    for line in PAIRED_RUN.read_text(encoding='utf-8').splitlines():
        record = json.loads(line)
        if isinstance(record.get('text'), str):
            arms.setdefault(record['id'], set()).add(record['arm'])
    return sorted(identity for identity, done in arms.items() if done == {'baseline', 'vocabulary'})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    parser.add_argument('--dry-run', action='store_true', help='Validate inputs; send nothing.')
    parser.add_argument('--resume', action='store_true', help='Continue a stopped run within the 36-call total.')
    parser.add_argument('--pause', type=float, default=5.0, help='Seconds between calls (free-tier rate).')
    args = parser.parse_args()
    captured = capture_manifest(MANIFEST, root=ROOT)
    ids = paired_ids()
    vocabularies = {arm: validate_vocabulary(json.loads((ROOT / path).read_text(encoding='utf-8'))['terms'])
                    for arm, (path, _) in ARMS.items()}
    cleaned = {identity: clean_wav(captured['audio_bytes'][identity]) for identity in ids}
    plan = dict(model=MODEL, clips=len(ids), ids=ids, arms=list(ARMS), max_calls=len(ids) * len(ARMS),
                manifest_sha256=captured['manifest_sha256'],
                vocabulary_terms={arm: len(terms) for arm, terms in vocabularies.items()},
                vocabulary_sha256={arm: hashlib.sha256(json.dumps(terms, ensure_ascii=False).encode()).hexdigest()
                                   for arm, terms in vocabularies.items()},
                cleanup={identity: report for identity, (_, report) in cleaned.items()})
    if args.dry_run:
        print(json.dumps(dict(plan, cleanup=len(cleaned), dry_run=True), ensure_ascii=False))
        return
    if args.output.exists() and not args.resume:
        sys.exit(f'{args.output} байна; өмнөх raw-ийг дарахгүй (--resume).')
    from gemini_credentials import WindowsCredentialStore
    saved = WindowsCredentialStore(ROOT / 'runtime/gemini-credentials.dpapi').load()
    if not saved:
        sys.exit('Хадгалсан Gemini түлхүүр алга.')
    args.output.mkdir(parents=True, exist_ok=True)
    results_path = args.output / 'results.jsonl'
    results = ([json.loads(line) for line in results_path.read_text(encoding='utf-8').splitlines()]
               if results_path.exists() else [])
    done = {(r['id'], r['arm']) for r in results if 'text' in r}
    stopped = None
    order = list(ARMS)
    for index, identity in enumerate(ids):
        # Rotate which arm goes first so provider drift does not favour one arm.
        shift = index % len(order)
        for arm in order[shift:] + order[:shift]:
            if stopped or (identity, arm) in done:
                continue
            if len(results) >= plan['max_calls']:
                stopped = 'approved_call_budget_used'
                continue
            if args.pause and results:
                time.sleep(args.pause)
            audio = cleaned[identity][0] if ARMS[arm][1] else captured['audio_bytes'][identity]
            started = time.perf_counter()
            record = dict(id=identity, arm=arm, audio_sha256=hashlib.sha256(audio).hexdigest())
            try:
                transport = GeminiTransport(saved['api_key'], vocabulary=vocabularies[arm])
                result = transport.transcribe(audio, display_name=f'clip-{identity}-{arm}')
                record.update(text=result['text'], model=result.get('model'), usage=result.get('usage'),
                              cleanup=result.get('cleanup'))
            except CandidateError as error:
                record.update(error=error.code, partial=bool(error.partial_result))
                if error.code == 'http_429':
                    stopped = 'http_429'
            record['elapsed_seconds'] = round(time.perf_counter() - started, 3)
            results.append(record)
            with results_path.open('a', encoding='utf-8') as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + '\n')
    summary = dict(plan, created_utc=datetime.now(timezone.utc).isoformat(), calls=len(results),
                   errors=sum('error' in r for r in results), stopped=stopped, automatic_retry=False,
                   scope='Нэг хэлэгчийн 12 dev бичлэг; ерөнхий accuracy биш, статистикийн ялгаа батлахгүй.')
    (args.output / 'run.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: summary[k] for k in ('calls', 'errors', 'stopped')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
