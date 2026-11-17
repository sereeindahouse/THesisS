"""Carry visual document transcriptions to a new capture run when the file is byte-identical.

A website refresh creates a new run; its PNG/PDF documents get no transcription until one
is imported for that run. When a document's captured bytes (SHA256) are unchanged, the
earlier transcription still describes exactly those bytes, so it is re-imported for the new
run through the normal validated import. Changed or new documents are only listed: they need
a fresh transcription, never a copied one.

    .venv/Scripts/python.exe tools/carry_document_extractions.py --database <website.db> \
        --to-run nmct-20261117T001006Z [--from-run nmct-20261109T152024Z]
"""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from CORE.document_corpus import import_excerpts            # noqa: E402
from CORE.website_corpus import readonly                    # noqa: E402


def latest_extractions(db, run_id):
    return {row['url']: json.loads(row['payload_json']) for row in db.execute(
        '''SELECT e.url, e.payload_json FROM document_extractions e WHERE e.run_id=?
           AND e.version=(SELECT MAX(x.version) FROM document_extractions x
                          WHERE x.run_id=e.run_id AND x.url=e.url)''', (run_id,))}


def plan(database, to_run, from_run=None):
    with closing(readonly(database)) as db:
        if from_run is None:
            row = db.execute('''SELECT r.run_id FROM crawl_runs r WHERE r.run_id<>? AND EXISTS
                (SELECT 1 FROM document_extractions e WHERE e.run_id=r.run_id)
                ORDER BY r.retrieved_at DESC LIMIT 1''', (to_run,)).fetchone()
            if row is None:
                raise ValueError('No earlier run with document transcriptions.')
            from_run = row['run_id']
        old = latest_extractions(db, from_run)
        already = latest_extractions(db, to_run)
        assets = {row['url']: row['sha256'] for row in db.execute(
            'SELECT url, sha256 FROM assets WHERE run_id=?', (to_run,))}
    carry, changed, missing = [], [], []
    for url, doc in sorted(old.items()):
        if url in already:
            continue
        if url not in assets:
            missing.append(url)
        elif assets[url] != doc['asset_sha256']:
            changed.append(url)
        else:
            carry.append(doc)
    uncovered = sorted(set(assets) - set(old) - set(already))
    return dict(from_run=from_run, to_run=to_run, carry=carry, changed=changed,
                missing_in_new_run=missing, new_documents_without_transcription=uncovered)


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--to-run', required=True)
    parser.add_argument('--from-run')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    result = plan(args.database, args.to_run, args.from_run)
    report = {key: value for key, value in result.items() if key != 'carry'}
    report['carried'] = [doc['url'] for doc in result['carry']]
    if result['carry'] and not args.dry_run:
        with tempfile.TemporaryDirectory() as folder:
            bundle = Path(folder) / 'bundle.json'
            bundle.write_text(json.dumps(dict(schema_version=1, run_id=args.to_run, documents=result['carry']),
                                         ensure_ascii=False), encoding='utf-8')
            report['import'] = import_excerpts(args.database, bundle)
    report['dry_run'] = args.dry_run
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
