"""Versioned excerpts of whitelisted public NMCT client-tab fields.

Decode captured Next Flight data as JSON/text only, never execute Javascript.
Every imported excerpt is regenerated from the captured HTML and exact locator.
Placeholder values and undated statistics remain in the omission inventory.
"""
from contextlib import closing
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sqlite3

from CORE.website_corpus import PageParser, canonical_url, readonly, split_chunks

METHOD = 'next_flight_whitelist_v1'
FIELDS = ('goalsJson', 'achievementsJson')
DDL = '''CREATE TABLE IF NOT EXISTS client_tab_extractions(
 run_id TEXT NOT NULL, url TEXT NOT NULL, version INTEGER NOT NULL,
 page_version INTEGER NOT NULL, html_sha256 TEXT NOT NULL,
 payload_sha256 TEXT NOT NULL, payload_json TEXT NOT NULL,
 PRIMARY KEY(run_id,url,version),
 FOREIGN KEY(run_id,url) REFERENCES captures(run_id,url));'''


def digest(value):
    return hashlib.sha256(value).hexdigest()


class _FlightScripts(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.in_script = False
        self.parts, self.streams = [], []

    def handle_starttag(self, tag, attrs):
        if tag == 'script':
            self.in_script, self.parts = True, []

    def handle_data(self, data):
        if self.in_script:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag != 'script' or not self.in_script:
            return
        self.in_script = False
        content = ''.join(self.parts).strip()
        if not content.startswith('self.__next_f.push('):
            return
        match = re.fullmatch(r'self\.__next_f\.push\((.*)\);?', content, re.S)
        if not match:
            raise ValueError('Unsupported Flight script wrapper.')
        item = json.loads(match[1])
        if not isinstance(item, list) or not item:
            raise ValueError('Invalid Flight push.')
        if item[0] == 1:
            if len(item) != 2 or not isinstance(item[1], str):
                raise ValueError('Invalid Flight text segment.')
            self.streams.append(item[1])


def flight_records(html):
    """Parse JSON lines and UTF-8 byte-length T records; fail on ambiguous data."""
    if not isinstance(html, str) or len(html) > 16 * 1024 * 1024:
        raise ValueError('Invalid captured HTML length.')
    scripts = _FlightScripts()
    scripts.feed(html)
    stream = ''.join(scripts.streams).encode('utf-8')
    records, pos = {}, 0
    while pos < len(stream):
        if stream[pos:pos + 1] == b'\n':
            pos += 1
            continue
        header = re.match(rb'([0-9a-f]+):', stream[pos:])
        if not header:
            raise ValueError('Invalid Flight record boundary.')
        identifier = header[1].decode()
        pos += header.end()
        text = re.match(rb'T([0-9a-f]+),', stream[pos:])
        if text:
            size = int(text[1], 16)
            pos += text.end()
            if pos + size > len(stream):
                raise ValueError('Truncated Flight text record.')
            value = stream[pos:pos + size].decode('utf-8')
            pos += size
        else:
            end = stream.find(b'\n', pos)
            end = len(stream) if end < 0 else end
            raw = stream[pos:end].decode('utf-8')
            pos = end
            if not raw or raw[0] not in '[{"-0123456789ntf':
                # Module/hint/error records cannot become evidence.
                continue
            value = json.loads(raw)
        if identifier in records and records[identifier] != value:
            raise ValueError('Conflicting Flight record identity.')
        records[identifier] = value
    return records


def _pointer(parts):
    return '/' + '/'.join(str(p).replace('~', '~0').replace('/', '~1') for p in parts)


def captured_fields(html):
    records = flight_records(html)
    found = []
    for identifier, value in records.items():
        if not isinstance(value, (dict, list)):
            continue
        pending = [(value, [])]
        while pending:
            value, path = pending.pop()
            if isinstance(value, dict):
                for key in FIELDS:
                    if key not in value:
                        continue
                    raw = value[key]
                    reference = None
                    if isinstance(raw, str) and re.fullmatch(r'\$[0-9a-f]+', raw):
                        reference = raw[1:]
                        raw = records.get(reference)
                    if not isinstance(raw, str):
                        raise ValueError('Unresolved or non-text client field.')
                    found.append(dict(field=key, record=identifier,
                        pointer=_pointer(path + [key]), reference=reference,
                        raw=raw, raw_sha256=digest(raw.encode('utf-8'))))
                pending.extend((child, path + [key]) for key, child in value.items()
                               if isinstance(child, (dict, list)))
            elif isinstance(value, list):
                pending.extend((child, path + [index]) for index, child in enumerate(value)
                               if isinstance(child, (dict, list)))
    # Multiple matching props are ambiguous; never choose a convenient value.
    for field in FIELDS:
        if sum(item['field'] == field for item in found) > 1:
            raise ValueError('Repeated whitelisted client property.')
    return sorted(found, key=lambda item: item['field'])


class _FieldHTML(PageParser):
    def handle_starttag(self, tag, attrs):
        if tag == 'blockquote':
            self.parts.append('\n')
        super().handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        super().handle_endtag(tag)
        if tag == 'blockquote':
            self.parts.append('\n')


def _plain(value):
    parser = _FieldHTML()
    parser.feed(value)
    return parser.result()['text']


def _placeholder(text):
    return bool(re.fullmatch(r'(?:үндсэн )?зорилго|зорилт\s*\d+|амжилт(?:ын мэдээ)?|test|placeholder|lorem ipsum', text.casefold().strip()))


def build_extraction(html_bytes, *, url, title, page_version=1, version=1, charset='utf-8'):
    """Deterministic selected-field extraction, with an explicit omission audit."""
    if canonical_url(url) != url or not url.startswith('https://nmct.edu.mn/departments/'):
        raise ValueError('Client-tab extraction is limited to public department pages.')
    if type(version) is not int or version < 1 or type(page_version) is not int or page_version < 1:
        raise ValueError('Invalid extraction/page version.')
    html = html_bytes.decode(charset)
    main_parser = PageParser()
    main_parser.feed(html)
    main = main_parser.result()['text']
    result = dict(url=url, title=title, version=version, page_version=page_version,
        html_sha256=digest(html_bytes), method=METHOD, coverage='selected_client_fields',
        reviewer_kind='deterministic_parser', charset=charset, passages=[], omissions=[])
    for field in captured_fields(html):
        sources = []
        if field['field'] == 'goalsJson':
            goals = json.loads(field['raw'])
            if not isinstance(goals, dict) or not isinstance(goals.get('goal'), str) or not isinstance(goals.get('objectives'), list):
                raise ValueError('Unsupported goals schema.')
            sources.append(('/goal', PageParser.clean([goals['goal']])))
            for index, objective in enumerate(goals['objectives']):
                if not isinstance(objective, str):
                    raise ValueError('Non-text objective.')
                sources.append((f'/objectives/{index}', PageParser.clean([objective])))
        else:
            sources.append(('', _plain(field['raw'])))
        for subpointer, text in sources:
            locator = f"Flight record {field['record']} JSON {field['pointer']}"
            if field['reference']:
                locator += f" -> text record {field['reference']}"
            locator += subpointer
            if not text or _placeholder(text):
                reason = 'empty_or_placeholder'
            elif field['field'] == 'achievementsJson' and not re.search(r'\b20\d{2}\b', text):
                reason = 'undated_achievement_or_statistics'
            elif text in main:
                reason = 'already_in_visible_main'
            elif len(text) < 15:
                reason = 'insufficient_context'
            else:
                reason = None
            if reason:
                result['omissions'].append(dict(locator=locator, field=field['field'],
                    reason=reason, raw_sha256=field['raw_sha256'], normalized_text_sha256=digest(text.encode())))
                continue
            for chunk in split_chunks(text):
                result['passages'].append(dict(locator=locator, field=field['field'],
                    record=field['record'], pointer=field['pointer'], reference=field['reference'],
                    subpointer=subpointer, raw_sha256=field['raw_sha256'],
                    normalized_text_sha256=digest(text.encode('utf-8')), normalized_length=len(text),
                    start_offset=chunk['start'], end_offset=chunk['end'], text=chunk['text'],
                    scope='historical_achievements' if field['field'] == 'achievementsJson' else 'department_objectives'))
    return result


def _checked_page(db, run, doc):
    capture = db.execute('''SELECT c.*,p.title FROM captures c JOIN pages p
      ON p.url=c.url AND p.version=c.version WHERE c.run_id=? AND c.url=?''',
      (run['run_id'], doc['url'])).fetchone()
    if capture is None or capture['version'] != doc['page_version'] or capture['html_sha256'] != doc['html_sha256']:
        raise ValueError('No matching immutable HTML capture/page version.')
    manifest_bytes = (Path(run['snapshot_dir']) / 'manifest.json').read_bytes()
    manifest = json.loads(manifest_bytes)
    if digest(manifest_bytes) != run['manifest_sha256'] or manifest['run_id'] != run['run_id']:
        raise ValueError('Capture manifest has changed.')
    manifest_pages = [p for p in manifest['pages'] if p['url'] == doc['url']]
    if len(manifest_pages) != 1 or manifest_pages[0]['html_sha256'] != doc['html_sha256']:
        raise ValueError('Capture manifest identity is ambiguous.')
    path = Path(capture['html_path']).resolve()
    if not path.is_relative_to(Path(run['snapshot_dir']).resolve()):
        raise ValueError('HTML capture is outside its snapshot.')
    body = path.read_bytes()
    if digest(body) != capture['html_sha256']:
        raise ValueError('Captured HTML has changed.')
    charset = json.loads(capture['http_metadata'])['charset']
    expected = build_extraction(body, url=capture['url'], title=capture['title'],
        page_version=capture['version'], version=doc['version'], charset=charset)
    if doc != expected:
        raise ValueError('Client-tab payload differs from exact captured-field extraction.')
    return dict(capture, retrieved_at=manifest_pages[0]['retrieved_at'])


def import_excerpts(database, bundle_path):
    """Validate every byte/locator before a transactional immutable import."""
    bundle = json.loads(Path(bundle_path).read_text(encoding='utf-8-sig'))
    if bundle['schema_version'] != 1 or bundle.get('method') != METHOD:
        raise ValueError('Unsupported client-tab bundle schema/method.')
    pending, identities = [], set()
    with closing(readonly(database)) as db:
        run = db.execute('SELECT * FROM crawl_runs WHERE run_id=?', (bundle['run_id'],)).fetchone()
        if run is None:
            raise ValueError('Capture run not found.')
        for doc in bundle['pages']:
            identity = (doc['url'], doc['version'])
            if identity in identities:
                raise ValueError('Duplicate extraction version.')
            identities.add(identity)
            _checked_page(db, run, doc)
            payload = json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
            pending.append((run['run_id'], doc['url'], doc['version'], doc['page_version'],
                            doc['html_sha256'], digest(payload.encode()), payload))
    with closing(sqlite3.connect(database)) as db:
        db.execute('PRAGMA foreign_keys=ON')
        with db:
            db.execute(DDL)
            added = 0
            for row in pending:
                old = db.execute('SELECT payload_sha256 FROM client_tab_extractions WHERE run_id=? AND url=? AND version=?', row[:3]).fetchone()
                if old and old[0] != row[5]:
                    raise ValueError('Preserve existing extraction; use a new version.')
                if not old:
                    db.execute('INSERT INTO client_tab_extractions VALUES(?,?,?,?,?,?,?)', row)
                    added += 1
    return dict(added_pages=added, pages_in_bundle=len(pending),
        passages_in_bundle=sum(len(p['passages']) for p in bundle['pages']),
        school_staff_approval=False, training_performed=False)


def prepare_bundle(database, snapshot):
    """Prepare locators against a capture without importing or changing the DB.

    Semantic page versions are reused when text is unchanged. Import the snapshot
    before this bundle; a concurrently changed page lineage fails import checks.
    """
    snapshot = Path(snapshot).resolve()
    manifest = json.loads((snapshot / 'manifest.json').read_text(encoding='utf-8-sig'))
    result = dict(schema_version=1, method=METHOD, run_id=manifest['run_id'], pages=[])
    with closing(readonly(database)) as db:
        for page in manifest['pages']:
            if not page['url'].startswith('https://nmct.edu.mn/departments/'):
                continue
            path = (snapshot / page['html_file']).resolve()
            if not path.is_relative_to(snapshot):
                raise ValueError('Capture path is outside the snapshot.')
            body = path.read_bytes()
            if digest(body) != page['html_sha256']:
                raise ValueError('Capture digest mismatch.')
            parser = PageParser()
            parser.feed(body.decode(page['http']['charset']))
            extracted = parser.result()
            if digest(extracted['text'].encode()) != page['text_sha256']:
                raise ValueError('Semantic text digest mismatch.')
            old = db.execute('SELECT version,title FROM pages WHERE url=? AND text_sha256=?',
                             (page['url'], page['text_sha256'])).fetchone()
            page_version = old['version'] if old else db.execute(
                'SELECT COALESCE(MAX(version),0)+1 FROM pages WHERE url=?', (page['url'],)).fetchone()[0]
            existing = db.execute("SELECT 1 FROM sqlite_master WHERE name='client_tab_extractions'").fetchone()
            latest = db.execute('SELECT COALESCE(MAX(version),0)+1 FROM client_tab_extractions WHERE run_id=? AND url=?',
                (manifest['run_id'], page['url'])).fetchone()[0] if existing else 1
            result['pages'].append(build_extraction(body, url=page['url'],
                title=old['title'] if old else extracted['title'], page_version=page_version,
                version=latest, charset=page['http']['charset']))
    return result


def read_client_tab_rows(db, run):
    """Fail closed per captured page; existing databases require no read migration."""
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='client_tab_extractions'").fetchone():
        return [], []
    records = db.execute('''SELECT e.* FROM client_tab_extractions e WHERE run_id=?
      AND version=(SELECT MAX(x.version) FROM client_tab_extractions x
        WHERE x.run_id=e.run_id AND x.url=e.url) ORDER BY url''', (run['run_id'],)).fetchall()
    rows, problems = [], []
    for record in records:
        try:
            doc = json.loads(record['payload_json'])
            if (doc['url'] != record['url'] or doc['version'] != record['version']
                    or doc['page_version'] != record['page_version'] or doc['html_sha256'] != record['html_sha256']
                    or digest(record['payload_json'].encode()) != record['payload_sha256']):
                raise ValueError('Client-tab payload identity/hash mismatch.')
            capture = _checked_page(db, run, doc)
            page = db.execute('SELECT * FROM pages WHERE url=? AND version=?',
                              (doc['url'], doc['page_version'])).fetchone()
            for ordinal, passage in enumerate(doc['passages']):
                text = passage['text']
                identity = f"{run['run_id']}|{doc['url']}|{record['payload_sha256']}|{ordinal}"
                rows.append(dict(source_id='tab-' + digest(identity.encode())[:20],
                    url=doc['url'], version=doc['page_version'], extraction_version=doc['version'],
                    title=doc['title'] + ' — ' + passage['field'], retrieved_at=capture['retrieved_at'],
                    source_updated_at=json.loads(capture['http_metadata']).get('last_modified'), text_scope='client_tab_field_excerpt',
                    valid_from=None, valid_until=None, chunk_id=ordinal,
                    start_offset=passage['start_offset'], end_offset=passage['end_offset'],
                    text=text, excerpt=text, page_years=sorted(set(re.findall(r'\b20\d{2}\b', text))),
                    page_header=doc['title'], snapshot_only=True, validity_unknown=True,
                    source_locator=passage['locator'], extraction_method=METHOD,
                    reviewer_kind=doc['reviewer_kind'], html_sha256=doc['html_sha256'],
                    field_sha256=passage['raw_sha256'], excerpt_coverage=doc['coverage'],
                    client_field=passage['field'], content_scope=passage['scope']))
        except (OSError, ValueError, KeyError, TypeError, UnicodeError):
            problems.append('Excluded client-tab page with invalid capture/extraction: ' + record['url'])
    return rows, problems


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', default='CORE/database/website.db')
    commands = parser.add_subparsers(dest='command', required=True)
    prepare = commands.add_parser('prepare')
    prepare.add_argument('snapshot')
    prepare.add_argument('--output', required=True)
    imp = commands.add_parser('import')
    imp.add_argument('bundle')
    args = parser.parse_args()
    if args.command == 'prepare':
        bundle = prepare_bundle(args.database, args.snapshot)
        with Path(args.output).open('x', encoding='utf-8', newline='\n') as handle:
            handle.write(json.dumps(bundle, ensure_ascii=False, indent=2) + '\n')
        result = dict(output=str(Path(args.output).resolve()), pages=len(bundle['pages']),
            passages=sum(len(p['passages']) for p in bundle['pages']), database_modified=False)
    else:
        result = import_excerpts(args.database, args.bundle)
    print(json.dumps(result, ensure_ascii=False, indent=2))
