"""Versioned, visually checked excerpts of already captured official documents.

Import is explicit. Image transcription is not byte-exact HTML extraction and
must retain its method, locator and reviewer kind. No OCR quality or school
staff approval is inferred. Original captures are never rewritten.
"""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import urlsplit

from CORE.website_corpus import readonly

DDL = '''CREATE TABLE IF NOT EXISTS document_extractions(
 run_id TEXT NOT NULL, url TEXT NOT NULL, version INTEGER NOT NULL,
 asset_sha256 TEXT NOT NULL, payload_sha256 TEXT NOT NULL, payload_json TEXT NOT NULL,
 PRIMARY KEY(run_id,url,version),
 FOREIGN KEY(run_id,url) REFERENCES assets(run_id,url));'''


def digest(data):
    return hashlib.sha256(data).hexdigest()


def official(url):
    try:
        p = urlsplit(url)
        return p.scheme == 'https' and p.hostname == 'nmct.edu.mn' and p.port in (None, 443) and not p.username and not p.password
    except (TypeError, ValueError):
        return False


def validate_document(doc):
    if not official(doc['url']) or type(doc['version']) is not int or doc['version'] < 1:
        raise ValueError('Invalid document identity.')
    if not re.fullmatch(r'[0-9a-f]{64}', doc['asset_sha256']):
        raise ValueError('Expected captured document SHA256.')
    if doc['method'] != 'visual_transcription' or doc['reviewer_kind'] not in {'assistant', 'human'}:
        raise ValueError('Explicit visual transcription provenance required.')
    if doc['coverage'] != 'selected_passages' or not isinstance(doc['title'], str) or not doc['title'].strip():
        raise ValueError('Label excerpt coverage and document title explicitly.')
    if not isinstance(doc['passages'], list) or not doc['passages']:
        raise ValueError('No passages.')
    locators = set()
    for passage in doc['passages']:
        if not isinstance(passage['text'], str) or not 15 <= len(passage['text']) <= 6000:
            raise ValueError('Invalid excerpt length.')
        if not isinstance(passage['locator'], str) or not passage['locator'].strip() or passage['locator'] in locators:
            raise ValueError('Missing or repeated page/section locator.')
        locators.add(passage['locator'])


def import_excerpts(database, bundle_path):
    bundle = json.loads(Path(bundle_path).read_text(encoding='utf-8-sig'))
    if bundle['schema_version'] != 1:
        raise ValueError('Unsupported document excerpt schema.')
    # Read and validate all input before modifying the database.
    pending, identities = [], set()
    with closing(readonly(database)) as db:
        run = db.execute('SELECT * FROM crawl_runs WHERE run_id=?', (bundle['run_id'],)).fetchone()
        if run is None:
            raise ValueError('Capture run not found.')
        snapshot = Path(run['snapshot_dir']).resolve()
        for doc in bundle['documents']:
            validate_document(doc)
            identity = (doc['url'], doc['version'])
            if identity in identities:
                raise ValueError('Duplicate document version in bundle.')
            identities.add(identity)
            asset = db.execute('SELECT * FROM assets WHERE run_id=? AND url=?', (bundle['run_id'], doc['url'])).fetchone()
            if asset is None or asset['sha256'] != doc['asset_sha256']:
                raise ValueError('No matching captured asset.')
            path = Path(asset['path']).resolve()
            if not path.is_relative_to(snapshot) or digest(path.read_bytes()) != asset['sha256']:
                raise ValueError('Original document missing, changed or outside snapshot.')
            payload = json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
            pending.append((bundle['run_id'], doc['url'], doc['version'], doc['asset_sha256'], digest(payload.encode()), payload))
    with closing(sqlite3.connect(database)) as db:
        db.execute('PRAGMA foreign_keys=ON')
        with db:
            db.execute(DDL)
            added = 0
            for row in pending:
                old = db.execute('SELECT payload_sha256 FROM document_extractions WHERE run_id=? AND url=? AND version=?', row[:3]).fetchone()
                if old and old[0] != row[4]:
                    raise ValueError('Preserve existing extraction; use a new version for corrections.')
                if not old:
                    db.execute('INSERT INTO document_extractions VALUES(?,?,?,?,?,?)', row)
                    added += 1
    return {'added_documents': added, 'documents_in_bundle': len(pending),
            'passages_in_bundle': sum(len(d['passages']) for d in bundle['documents']),
            'school_staff_approval': False, 'training_performed': False}


def read_document_rows(db, run):
    """Fail closed per document; old corpus databases need no migration to read."""
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='document_extractions'").fetchone():
        return [], []
    records = db.execute('''SELECT e.*,a.path,a.sha256 FROM document_extractions e
      JOIN assets a ON e.run_id=a.run_id AND e.url=a.url WHERE e.run_id=?
      AND e.version=(SELECT MAX(x.version) FROM document_extractions x WHERE x.run_id=e.run_id AND x.url=e.url)
      ORDER BY e.url''', (run['run_id'],)).fetchall()
    rows, problems = [], []
    for record in records:
        try:
            doc = json.loads(record['payload_json'])
            validate_document(doc)
            path = Path(record['path']).resolve()
            if (not path.is_relative_to(Path(run['snapshot_dir']).resolve())
                    or digest(path.read_bytes()) != record['sha256']
                    or doc['asset_sha256'] != record['sha256'] or record['asset_sha256'] != record['sha256']
                    or doc['url'] != record['url'] or doc['version'] != record['version']
                    or digest(record['payload_json'].encode()) != record['payload_sha256']):
                raise ValueError('Document integrity check failed.')
            for ordinal, passage in enumerate(doc['passages']):
                text = passage['text']
                identity = f"{record['run_id']}|{record['url']}|{record['payload_sha256']}|{ordinal}"
                rows.append(dict(source_id='doc-' + digest(identity.encode())[:20],
                    url=doc['url'], version=doc['version'], title=doc['title'] + ' — ' + passage['locator'],
                    retrieved_at=doc.get('retrieved_at') or run['retrieved_at'], source_updated_at=None,
                    text_scope='document_visual_excerpt', valid_from=None, valid_until=None,
                    chunk_id=ordinal, start_offset=0, end_offset=len(text), text=text, excerpt=text,
                    page_years=sorted(set(re.findall(r'\b20\d{2}\b', doc['title'] + ' ' + text))),
                    page_header=doc['title'], snapshot_only=True, validity_unknown=True,
                    source_locator=passage['locator'], extraction_method=doc['method'],
                    reviewer_kind=doc['reviewer_kind'], asset_sha256=doc['asset_sha256'],
                    excerpt_coverage=doc['coverage']))
        except (OSError, ValueError, KeyError, TypeError):
            problems.append('Excluded document with invalid capture/extraction: ' + record['url'])
    return rows, problems


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle')
    parser.add_argument('--database', default='CORE/database/website.db')
    args = parser.parse_args()
    print(json.dumps(import_excerpts(args.database, args.bundle), ensure_ascii=False, indent=2))
