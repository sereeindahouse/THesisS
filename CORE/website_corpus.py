"""Collect and inspect public NMCT website sources; never approve or answer automatically."""
import argparse
from contextlib import closing
from collections import deque
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sqlite3
import sys
import time
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, quote, unquote, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.robotparser import RobotFileParser
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ''):
    sys.path.insert(0, str(ROOT))
DATABASE = ROOT / 'CORE/database/website.db'
SNAPSHOTS = ROOT / 'CORE/website/snapshots'
ORIGIN = 'https://nmct.edu.mn'
USER_AGENT = 'THesisS-research-source-audit/1.0'
PRIVATE = {'admin', 'login', 'logout', 'register', 'signup', 'dashboard', 'account',
           'reset-password', 'password-reset', 'forgot-password', 'api', '_next'}
MEDIA = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.ico', '.mp4', '.mp3',
         '.wav', '.woff', '.woff2', '.ttf', '.css', '.js', '.zip', '.xlsx', '.docx'}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def canonical_url(link, base=ORIGIN, *, allow_documents=False):
    """Allow public same-origin HTTPS pages and finite pagination; discard tracking."""
    parsed = urlsplit(urljoin(base, link))
    if parsed.scheme not in {'http', 'https'} or parsed.hostname not in {'nmct.edu.mn', 'www.nmct.edu.mn'}:
        return None
    if parsed.username or parsed.password or parsed.port not in {None, 80, 443}:
        return None
    path = re.sub('/+', '/', unquote(parsed.path) or '/')
    if any(part.casefold() in PRIVATE for part in path.split('/')) or '..' in path.split('/'):
        return None
    if Path(path).suffix.casefold() in MEDIA:
        return None
    if Path(path).suffix.casefold() == '.pdf' and not allow_documents:
        return None
    query = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if key in {'page', 'p'}:
            if not value.isdigit() or not 1 <= int(value) <= 100:
                return None
            if int(value) > 1:
                query.append((key, str(int(value))))
        elif not key.startswith('utm_') and key not in {'fbclid', 'gclid'}:
            # Do not enumerate registration forms, token URLs or arbitrary parameter spaces.
            return None
    if path != '/':
        path = path.rstrip('/')
    return urlunsplit(('https', 'nmct.edu.mn', quote(path, safe='/@-._~'), urlencode(sorted(query)), ''))


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links, self.assets, self.parts, self.main_parts, self.title_parts = [], [], [], [], []
        self.stack = []
        self.ignore = 0
        self.main = 0
        self.title = False
        self.dates = []
        self.headings = []
        self.in_heading = False
        self.heading_parts = []
        self.has_main = False

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag in {'script', 'style', 'noscript', 'svg'}:
            self.ignore += 1
        if tag == 'main':
            self.main += 1
            self.has_main = True
        if tag == 'title':
            self.title = True
        if tag == 'h1':
            self.in_heading = True
            self.heading_parts = []
        if tag == 'a' and values.get('href'):
            self.links.append(values['href'])
        if tag in {'img', 'iframe', 'source'}:
            for key in ('src', 'data-src'):
                if values.get(key):
                    self.assets.append(values[key])
        if tag == 'time' and values.get('datetime'):
            self.dates.append(values['datetime'])
        if tag == 'meta' and values.get('property') in {'article:published_time', 'article:modified_time'}:
            self.dates.append(values.get('content', ''))
        if tag in {'p','div','section','article','main','h1','h2','h3','h4','li','tr','br','header','footer','nav'}:
            self.parts.append('\n')
            if self.main:
                self.main_parts.append('\n')

    def handle_endtag(self, tag):
        if tag in {'script', 'style', 'noscript', 'svg'}:
            self.ignore = max(0, self.ignore - 1)
        if tag == 'main':
            self.main = max(0, self.main - 1)
        if tag == 'title':
            self.title = False
        if tag == 'h1':
            self.headings.append(' '.join(''.join(self.heading_parts).split()))
            self.in_heading = False
        if tag in {'p','div','section','article','main','h1','h2','h3','h4','li','tr','header','footer','nav'}:
            self.parts.append('\n')
            if self.main:
                self.main_parts.append('\n')

    def handle_data(self, data):
        if self.title:
            self.title_parts.append(data)
        if self.in_heading and not self.ignore:
            self.heading_parts.append(data + ' ')
        if not self.ignore and not self.title:
            self.parts.append(data + ' ')
            if self.main:
                self.main_parts.append(data + ' ')

    @staticmethod
    def clean(parts):
        # Remove adjacent repeated lines only; retain meaningful names, numbers and dates.
        lines, previous = [], None
        for line in ''.join(parts).splitlines():
            line = ' '.join(unicodedata.normalize('NFC', line).split())
            if line and line != previous:
                lines.append(line)
            previous = line
        return '\n'.join(lines)

    def result(self):
        full = self.clean(self.parts)
        main = self.clean(self.main_parts) if self.has_main else full
        return {'title': next((heading for heading in self.headings if heading), ' '.join(self.title_parts).strip()), 'full_text': full, 'text': main,
                'links': self.links, 'assets': self.assets, 'published_dates': self.dates,
                'text_scope': 'main_element' if self.has_main else 'visible_page_with_navigation'}


STRUCTURAL_SPANS_VERSION = 'canonical-dom-fences-v1'
_HTML_VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link',
              'meta', 'param', 'source', 'track', 'wbr'}
_HTML_HEADINGS = {'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}


class _StructureParser(PageParser):
    """Track the existing extractor's tokens, without changing its output."""
    def __init__(self):
        super().__init__()
        self.nodes, self.node_stack, self.token_paths = [], [], []
        self.structurally_valid = True

    def _record(self, before):
        self.token_paths.extend([tuple(self.node_stack)] * (len(self.main_parts) - before))

    def handle_starttag(self, tag, attrs):
        node = dict(tag=tag, parent=self.node_stack[-1] if self.node_stack else None)
        self.nodes.append(node)
        if tag not in _HTML_VOID:
            self.node_stack.append(len(self.nodes) - 1)
        before = len(self.main_parts)
        super().handle_starttag(tag, attrs)
        self._record(before)

    def handle_endtag(self, tag):
        before = len(self.main_parts)
        super().handle_endtag(tag)
        self._record(before)
        if tag in _HTML_VOID:
            return
        if not self.node_stack or self.nodes[self.node_stack[-1]]['tag'] != tag:
            self.structurally_valid = False
            return
        self.node_stack.pop()

    def handle_data(self, data):
        before = len(self.main_parts)
        super().handle_data(data)
        self._record(before)

    def mapped_lines(self):
        """Match NFC/whitespace/deduplication exactly, retaining token ancestry.

        A node may fence a line only when it owns every nonspace token in that
        line. Inline markup must never manufacture a boundary in flattened text.
        """
        rows, pieces, paths, previous, offset = [], [], [], None, 0

        def flush():
            nonlocal pieces, paths, previous, offset
            line = ' '.join(unicodedata.normalize('NFC', ''.join(pieces)).split())
            if line and line != previous:
                common = set.intersection(*(set(path) for path in paths)) if paths else set()
                touched = set().union(*paths)
                rows.append(dict(start=offset, end=offset + len(line), text=line,
                                 owners=common, touched=touched))
                offset += len(line) + 1
            previous = line
            pieces, paths = [], []

        for token, path in zip(self.main_parts, self.token_paths):
            for index, piece in enumerate(token.split('\n')):
                if index:
                    flush()
                pieces.append(piece)
                if piece.strip():
                    paths.append(path)
        flush()
        return rows


def structural_spans(html, expected_text):
    """Partition captured main text at verified section/repeated-card fences.

    Every returned range is in the original canonical character coordinate
    system, and the ranges cover *all* characters, including whitespace gaps.
    These are splitting constraints for a paragraph parser, not replacement
    evidence: no sentence, heading, year, list, badge or condition is removed.

    Card fences require a pure group of repeated sibling containers, each with
    exactly one heading and a complete paragraph. Their outer container keeps
    sibling year/name/badge text attached. Any shared section text vetoes card
    splitting. Other layouts retain their bounds; any outer main text outside
    all sections also vetoes inner section fences. No content is classified as
    decorative, conditional or semantically unnecessary.
    Malformed nesting or extraction mismatch fails closed with []; an ambiguous
    node never supplies a fence. This function performs no I/O or query matching.
    """
    if not isinstance(html, str) or not isinstance(expected_text, str) or not expected_text:
        return []
    parser = _StructureParser()
    try:
        parser.feed(html)
        parser.close()
        if (not parser.structurally_valid or parser.node_stack or not parser.has_main
                or parser.result()['text'] != expected_text):
            return []
        lines = parser.mapped_lines()
    except (ValueError, TypeError, IndexError):
        return []
    if '\n'.join(line['text'] for line in lines) != expected_text:
        return []

    children = [[] for _ in parser.nodes]
    owned, touched = [[] for _ in parser.nodes], [[] for _ in parser.nodes]
    for node_id, node in enumerate(parser.nodes):
        if node['parent'] is not None:
            children[node['parent']].append(node_id)
    for index, line in enumerate(lines):
        for node_id in line['owners']:
            owned[node_id].append(index)
        for node_id in line['touched']:
            touched[node_id].append(index)

    def bounds(node_id):
        indexes = owned[node_id]
        if (not indexes or indexes != touched[node_id]
                or indexes != list(range(indexes[0], indexes[-1] + 1))):
            return None
        # Include the following newline, so every cut starts a physical line.
        return lines[indexes[0]]['start'], min(len(expected_text), lines[indexes[-1]]['end'] + 1)

    def descendants(node_id):
        pending, result = [node_id], []
        while pending:
            current = pending.pop()
            result.append(current)
            pending.extend(children[current])
        return result

    def card(node_id):
        if parser.nodes[node_id]['tag'] not in {'div', 'article', 'li'} or bounds(node_id) is None:
            return False
        members = descendants(node_id)
        headings = [n for n in members if parser.nodes[n]['tag'] in _HTML_HEADINGS and owned[n]]
        paragraphs = [n for n in members if parser.nodes[n]['tag'] == 'p' and bounds(n) is not None]
        return len(headings) == 1 and bool(paragraphs)

    def ancestors(node_id):
        parent = parser.nodes[node_id]['parent']
        result = []
        while parent is not None:
            result.append(parent)
            parent = parser.nodes[parent]['parent']
        return result

    section_ids = {n for n, node in enumerate(parser.nodes) if node['tag'] == 'section'}
    shared_main_scope = {
        n for n, node in enumerate(parser.nodes) if node['tag'] == 'main'
        and any(not lines[i]['owners'] & section_ids for i in owned[n])}
    cuts = {0, len(expected_text)}
    for node_id, node in enumerate(parser.nodes):
        span = bounds(node_id)
        parents = ancestors(node_id)
        outer_scope = bool(shared_main_scope.intersection(parents))
        if (node['tag'] == 'section' and span is not None and not outer_scope
                and not section_ids.intersection(parents)):
            cuts.update(span)
        meaningful = [child for child in children[node_id] if touched[child]]
        if (len(meaningful) < 2 or not all(card(child) for child in meaningful)
                or len({parser.nodes[child]['tag'] for child in meaningful}) != 1
                or set(owned[node_id]) != {i for child in meaningful for i in owned[child]}):
            continue
        # Shared text of any tag can carry a subject, condition or date. It must
        # not disappear merely because later cards carry individual headings.
        group_lines = set(owned[node_id])
        sections = section_ids.intersection(parents)
        if outer_scope or any(set(owned[section]) - group_lines for section in sections):
            continue
        for child in meaningful:
            cuts.update(bounds(child))
    ordered = sorted(cuts)
    return [(start, end) for start, end in zip(ordered, ordered[1:]) if start < end]


def split_chunks(text, size=900, overlap=140):
    """Character windows keep exact contiguous source excerpts and offsets."""
    if not isinstance(text, str) or not 100 <= size <= 10000 or not 0 <= overlap < size:
        raise ValueError('Invalid chunk parameters.')
    chunks, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            boundary = text.rfind('\n', start + size // 2, end)
            if boundary > start:
                end = boundary + 1
        chunks.append({'ordinal': len(chunks), 'start': start, 'end': end, 'text': text[start:end]})
        if end == len(text):
            break
        start = max(start + 1, end - overlap)
    return chunks


class SameOriginRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        target = urlsplit(new_url)
        if target.scheme != 'https' or target.hostname not in {'nmct.edu.mn','www.nmct.edu.mn'}:
            raise ValueError('Redirect left the official website; not followed.')
        if any(part.casefold() in PRIVATE for part in target.path.split('/')):
            raise ValueError('Redirect points to a private/technical endpoint.')
        return super().redirect_request(request, response, code, message, headers, new_url)


def fetch(url, max_bytes=16 * 1024 * 1024):
    opener = build_opener(SameOriginRedirect())
    request = Request(url, headers={'User-Agent': USER_AGENT, 'Accept': 'text/html,application/xml,application/pdf;q=0.9'})
    with opener.open(request, timeout=20) as response:
        body = response.read(max_bytes + 1)
        if len(body) > max_bytes:
            raise ValueError('Response exceeds configured size limit.')
        return body, dict(status=response.status, final_url=response.url,
                          content_type=response.headers.get_content_type(),
                          charset=response.headers.get_content_charset() or 'utf-8',
                          last_modified=response.headers.get('Last-Modified'),
                          etag=response.headers.get('ETag'))


def capture_documents(destination, inventory, robots):
    """Save linked PDFs and admissions rule scans; binary files are not OCR facts."""
    targets = set()
    for item in inventory:
        parsed = urlsplit(item['url'])
        if parsed.scheme != 'https' or parsed.hostname != 'nmct.edu.mn' or parsed.query:
            continue
        if item['kind'] == 'document' and parsed.path.endswith('.pdf'):
            targets.add((item['url'], 'pdf'))
        if parsed.path.startswith('/elseltiin-juram/') and Path(parsed.path).suffix.lower() in {'.png','.jpg','.jpeg'}:
            targets.add((item['url'], 'admissions_rule_scan'))
    documents = []
    (destination / 'documents').mkdir(exist_ok=True)
    for url, kind in sorted(targets):
        if not robots.can_fetch(USER_AGENT, url):
            inventory.append({'url':url,'kind':'skipped_document','reason':'robots disallow'})
            continue
        try:
            body, headers = fetch(url)
            if headers['content_type'] not in {'application/pdf','image/png','image/jpeg'}:
                raise ValueError('Unexpected document response type.')
            filename = 'documents/' + sha256(url.encode('utf-8'))[:20] + Path(urlsplit(url).path).suffix
            (destination / filename).write_bytes(body)
            documents.append(dict(url=url, kind=kind, file=filename, size_bytes=len(body), sha256=sha256(body),
                                  extraction_status='binary_only', retrieved_at=now(), http=headers))
            print('Document saved: ' + url, flush=True)
        except (OSError, ValueError) as error:
            inventory.append({'url':url,'kind':'failed_document','reason':str(error)[:250]})
    return documents


DDL = '''
CREATE TABLE IF NOT EXISTS corpus_meta(schema_version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS crawl_runs(run_id TEXT PRIMARY KEY,retrieved_at TEXT NOT NULL,snapshot_dir TEXT NOT NULL,manifest_sha256 TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pages(url TEXT NOT NULL,version INTEGER NOT NULL,title TEXT NOT NULL,text TEXT NOT NULL,full_text TEXT NOT NULL,
 text_sha256 TEXT NOT NULL,retrieved_at TEXT NOT NULL,source_updated_at TEXT,text_scope TEXT NOT NULL,
 approval_status TEXT NOT NULL CHECK(approval_status='draft'),valid_from TEXT,valid_until TEXT,
 PRIMARY KEY(url,version),UNIQUE(url,text_sha256));
CREATE TABLE IF NOT EXISTS captures(run_id TEXT NOT NULL REFERENCES crawl_runs(run_id),url TEXT NOT NULL,version INTEGER NOT NULL,
 html_path TEXT NOT NULL,text_path TEXT NOT NULL,html_sha256 TEXT NOT NULL,http_metadata TEXT NOT NULL,
 PRIMARY KEY(run_id,url),FOREIGN KEY(url,version) REFERENCES pages(url,version));
CREATE TABLE IF NOT EXISTS chunks(url TEXT NOT NULL,version INTEGER NOT NULL,ordinal INTEGER NOT NULL,start_offset INTEGER NOT NULL,
 end_offset INTEGER NOT NULL,text TEXT NOT NULL,PRIMARY KEY(url,version,ordinal),FOREIGN KEY(url,version) REFERENCES pages(url,version));
CREATE TABLE IF NOT EXISTS link_inventory(run_id TEXT NOT NULL,url TEXT NOT NULL,kind TEXT NOT NULL,reason TEXT NOT NULL,
 PRIMARY KEY(run_id,url,kind),FOREIGN KEY(run_id) REFERENCES crawl_runs(run_id));
CREATE TABLE IF NOT EXISTS assets(run_id TEXT NOT NULL,url TEXT NOT NULL,kind TEXT NOT NULL,path TEXT NOT NULL,sha256 TEXT NOT NULL,
 size_bytes INTEGER NOT NULL,extraction_status TEXT NOT NULL,PRIMARY KEY(run_id,url),FOREIGN KEY(run_id) REFERENCES crawl_runs(run_id));
'''


def import_snapshot(database, snapshot):
    """Atomically import immutable semantic versions; all pages remain draft."""
    database, snapshot = Path(database), Path(snapshot).resolve()
    manifest_bytes = (snapshot / 'manifest.json').read_bytes()
    manifest = json.loads(manifest_bytes)
    records = []
    for page in manifest['pages']:
        if canonical_url(page['url']) != page['url'] or page['status'] != 'ok':
            raise ValueError('Manifest contains an unexpected page URL or status.')
        for key in ('html_file', 'text_file'):
            file = (snapshot / page[key]).resolve()
            if not file.is_relative_to(snapshot) or not file.is_file():
                raise ValueError('Snapshot file escapes its capture directory or is missing.')
        html = (snapshot / page['html_file']).read_bytes()
        text = (snapshot / page['text_file']).read_text(encoding='utf-8')
        if sha256(html) != page['html_sha256'] or sha256(text.encode('utf-8')) != page['text_sha256']:
            raise ValueError('Snapshot digest differs from recorded capture.')
        parsed = PageParser()
        parsed.feed(html.decode(page['http']['charset'], errors='replace'))
        extracted = parsed.result()
        if extracted['text'] != text:
            raise ValueError('Text does not match the captured HTML extraction.')
        records.append((page, extracted))
    database.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(database)
    try:
        db.execute('PRAGMA foreign_keys=ON')
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='corpus_meta'").fetchone():
            user_tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if user_tables:
                raise ValueError('Refusing to modify an unrelated database.')
            db.executescript(DDL)
            db.execute('INSERT INTO corpus_meta VALUES(1)')
            db.commit()
        if db.execute('SELECT schema_version FROM corpus_meta').fetchall() != [(1,)]:
            raise ValueError('Unsupported corpus schema.')
        db.executescript(DDL)
        existing = db.execute('SELECT manifest_sha256 FROM crawl_runs WHERE run_id=?', (manifest['run_id'],)).fetchone()
        digest = sha256(manifest_bytes)
        if existing:
            if existing[0] != digest:
                raise ValueError('Existing capture run differs; preserve it.')
            return {'imported': False, 'run_id': manifest['run_id'], 'pages_in_run': len(records)}
        with db:
            db.execute('INSERT INTO crawl_runs VALUES(?,?,?,?)',
                       (manifest['run_id'], manifest['retrieved_at'], str(snapshot), digest))
            for page, extracted in records:
                identity = db.execute('SELECT version FROM pages WHERE url=? AND text_sha256=?',
                                      (page['url'], page['text_sha256'])).fetchone()
                if identity:
                    version = identity[0]
                else:
                    version = db.execute('SELECT COALESCE(MAX(version),0)+1 FROM pages WHERE url=?', (page['url'],)).fetchone()[0]
                    db.execute('INSERT INTO pages VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                        (page['url'], version, extracted['title'] or page['url'], extracted['text'], extracted['full_text'],
                         page['text_sha256'], page['retrieved_at'], page['http'].get('last_modified'),
                         extracted['text_scope'], 'draft', None, None))
                    db.executemany('INSERT INTO chunks VALUES(?,?,?,?,?,?)',
                        [(page['url'], version, c['ordinal'], c['start'], c['end'], c['text']) for c in split_chunks(extracted['text'])])
                db.execute('INSERT INTO captures VALUES(?,?,?,?,?,?,?)',
                    (manifest['run_id'], page['url'], version, str(snapshot / page['html_file']),
                     str(snapshot / page['text_file']), page['html_sha256'], json.dumps(page['http'], ensure_ascii=False)))
            for entry in manifest['inventory']:
                db.execute('INSERT OR IGNORE INTO link_inventory VALUES(?,?,?,?)',
                           (manifest['run_id'], entry['url'], entry['kind'], entry['reason']))
            for asset in manifest.get('documents', []):
                path = (snapshot / asset['file']).resolve()
                if not path.is_relative_to(snapshot) or sha256(path.read_bytes()) != asset['sha256']:
                    raise ValueError('Document capture path or digest mismatch.')
                db.execute('INSERT INTO assets VALUES(?,?,?,?,?,?,?)',
                    (manifest['run_id'], asset['url'], asset['kind'], str(path), asset['sha256'],
                     asset['size_bytes'], asset.get('extraction_status', 'binary_only')))
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        return {'imported': True, 'run_id': manifest['run_id'], 'pages_in_run': len(records)}
    finally:
        db.close()


def readonly(database):
    database = Path(database).resolve()
    if not database.is_file():
        raise FileNotFoundError('Website database has not been collected.')
    db = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA query_only=ON')
    try:
        if db.execute('SELECT schema_version FROM corpus_meta').fetchone()[0] != 1:
            raise ValueError('Unsupported corpus schema.')
        return db
    except Exception:
        db.close()
        raise


def website_status(database=DATABASE):
    with closing(readonly(database)) as db:
        run = db.execute('SELECT * FROM crawl_runs ORDER BY retrieved_at DESC LIMIT 1').fetchone()
        pages = db.execute('SELECT COUNT(*) FROM captures WHERE run_id=?', (run['run_id'],)).fetchone()[0] if run else 0
        chunks = db.execute('SELECT COUNT(*) FROM chunks c JOIN captures x ON c.url=x.url AND c.version=x.version WHERE x.run_id=?',
                            (run['run_id'],)).fetchone()[0] if run else 0
        assets = db.execute('SELECT COUNT(*) FROM assets WHERE run_id=?', (run['run_id'],)).fetchone()[0] if run else 0
        return {'available': bool(run), 'pages': pages, 'chunks': chunks, 'documents': assets,
                'versions': db.execute('SELECT COUNT(*) FROM pages').fetchone()[0],
                'crawl_runs': db.execute('SELECT COUNT(*) FROM crawl_runs').fetchone()[0],
                'run_id': run['run_id'] if run else None, 'retrieved_at': run['retrieved_at'] if run else None,
                'approved_pages': 0, 'approval_status': 'draft', 'automatic_answer': False}


def search_website(query, database=DATABASE, *, limit=5, allow_draft=False):
    if not isinstance(query, str) or not query.strip() or len(query) > 1000 or type(limit) is not int or not 1 <= limit <= 10:
        raise ValueError('Invalid website query or limit.')
    if type(allow_draft) is not bool:
        raise ValueError('allow_draft must be a boolean.')
    from retrieval_probe import bm25_scores, terms
    if not terms(query):
        raise ValueError('The query must contain words.')
    with closing(readonly(database)) as db:
        run = db.execute('SELECT run_id FROM crawl_runs ORDER BY retrieved_at DESC LIMIT 1').fetchone()
        rows = db.execute('SELECT c.*,p.title,p.retrieved_at,p.text_scope FROM chunks c JOIN pages p ON p.url=c.url AND p.version=c.version '
                          'JOIN captures x ON x.url=c.url AND x.version=c.version WHERE x.run_id=? ORDER BY c.url,c.ordinal', (run[0],)).fetchall() if run else []
    scores = bm25_scores([row['title'] + '\n' + row['text'] for row in rows], [query])[0] if rows else []
    matches = []
    matched_urls = set()
    for index in sorted(range(len(rows)), key=lambda i: (-scores[i], rows[i]['url'], rows[i]['ordinal'])):
        if scores[index] <= 0:
            continue
        row = rows[index]
        if row['url'] in matched_urls:
            continue
        matched_urls.add(row['url'])
        matches.append({'url': row['url'], 'version': row['version'], 'title': row['title'],
            'chunk_id': row['ordinal'], 'start_offset': row['start_offset'], 'end_offset': row['end_offset'],
            'retrieved_at': row['retrieved_at'], 'approval_status': 'draft', 'validity_unknown': True,
            'score': float(scores[index]), 'excerpt': row['text'] if allow_draft else None,
            'text_scope': row['text_scope']})
        if len(matches) == limit:
            break
    return {'query': query, 'matches': matches, 'mode': 'development_draft' if allow_draft else 'approved_only',
            'answer': None, 'generated': False, 'llm_calls': 0, 'score_is_probability': False}


def collect(destination=SNAPSHOTS, *, max_pages=300, delay=0.3):
    """BFS of discoverable public pages; record every omission, do not claim hidden content."""
    run_id = 'nmct-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    destination = Path(destination) / run_id
    destination.mkdir(parents=True, exist_ok=False)
    (destination / 'html').mkdir()
    (destination / 'text').mkdir()
    manifest = {'run_id': run_id, 'origin': ORIGIN, 'retrieved_at': now(),
                'user_agent': USER_AGENT, 'pages': [], 'inventory': [], 'robots': {}, 'sitemaps': [],
                'limits': {'max_pages': max_pages, 'max_html_bytes': 16*1024*1024, 'delay_seconds': delay},
                'automatic_approval': False, 'authenticated_endpoints_visited': False}
    queue, seen = deque([ORIGIN + '/']), set()
    robots = RobotFileParser()
    try:
        body, headers = fetch(ORIGIN + '/robots.txt')
        robots.parse(body.decode('utf-8', errors='replace').splitlines())
        manifest['robots'] = dict(status='retrieved', sha256=sha256(body))
        (destination / 'robots.txt').write_bytes(body)
    except HTTPError as error:
        if error.code not in {404, 410}:
            raise RuntimeError('Robots retrieval failed; collection stopped.') from error
        robots.parse([])
        manifest['robots'] = dict(status=error.code, rules='no robots file published')
    for sitemap_url in [ORIGIN + '/sitemap.xml', ORIGIN + '/sitemap_index.xml']:
        try:
            body, headers = fetch(sitemap_url)
            parsed = ET.fromstring(body)
            locations = [element.text for element in parsed.iter() if element.tag.split('}')[-1] == 'loc' and element.text]
            manifest['sitemaps'].append({'url': sitemap_url, 'status': 'retrieved', 'locations': len(locations)})
            for link in locations:
                normalized = canonical_url(link)
                if normalized and not normalized.endswith('.xml'):
                    queue.append(normalized)
        except (HTTPError, ET.ParseError, ValueError) as error:
            manifest['sitemaps'].append({'url': sitemap_url, 'status': getattr(error, 'code', type(error).__name__)})
    def save():
        (destination / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    try:
        while queue and len(seen) < max_pages:
            url = queue.popleft()
            if url in seen:
                continue
            seen.add(url)
            if not robots.can_fetch(USER_AGENT, url):
                manifest['inventory'].append({'url': url, 'kind': 'skipped', 'reason': 'robots disallow'})
                continue
            try:
                body, headers = fetch(url)
                if headers['content_type'] != 'text/html':
                    manifest['inventory'].append({'url': url, 'kind': 'skipped', 'reason': 'not HTML; inventoried only'})
                    continue
                parser = PageParser()
                parser.feed(body.decode(headers['charset'], errors='replace'))
                extracted = parser.result()
                if not extracted['text'].strip():
                    manifest['inventory'].append({'url': url, 'kind': 'failed', 'reason': 'no visible server-rendered text'})
                    continue
                identity = sha256(url.encode('utf-8'))[:20]
                html_file, text_file = 'html/' + identity + '.html', 'text/' + identity + '.txt'
                (destination / html_file).write_bytes(body)
                (destination / text_file).write_text(extracted['text'], encoding='utf-8', newline='')
                manifest['pages'].append({'url': url, 'status': 'ok', 'title': extracted['title'],
                    'retrieved_at': now(), 'html_file': html_file, 'text_file': text_file,
                    'html_sha256': sha256(body), 'text_sha256': sha256(extracted['text'].encode('utf-8')),
                    'characters': len(extracted['text']), 'http': headers, 'text_scope': extracted['text_scope'],
                    'published_dates': extracted['published_dates']})
                for link in extracted['links']:
                    normalized = canonical_url(link, url)
                    if normalized:
                        if normalized not in seen:
                            queue.append(normalized)
                    else:
                        document = canonical_url(link, url, allow_documents=True)
                        kind = 'document' if document and document.endswith('.pdf') else 'external_or_excluded'
                        manifest['inventory'].append({'url': urljoin(url, link), 'kind': kind, 'reason': 'linked resource; not crawled as public HTML'})
                for asset in extracted['assets']:
                    manifest['inventory'].append({'url': urljoin(url, asset), 'kind': 'media', 'reason': 'linked media; image/audio/video text not extracted'})
                print(f'Collected {len(manifest["pages"])} pages: {url} ({len(extracted["text"])} characters)', flush=True)
            except (HTTPError, URLError, TimeoutError, OSError, ValueError) as error:
                manifest['inventory'].append({'url': url, 'kind': 'failed', 'reason': str(error)[:250]})
                print(f'Unavailable: {url} ({type(error).__name__})', flush=True)
            save()
            time.sleep(delay)
        manifest['pending_urls'] = sorted(set(queue) - seen)
        manifest['html_frontier_exhausted'] = not manifest['pending_urls']
        manifest['attempted_public_urls'] = len(seen)
        manifest['documents'] = capture_documents(destination, manifest['inventory'], robots)
        manifest['completed_at'] = now()
        unique = {(entry['url'], entry['kind']): entry for entry in manifest['inventory']}
        manifest['inventory'] = list(unique.values())
        manifest['coverage_statement'] = 'Discoverable public HTML and linked PDFs/admissions rule scans. Image/PDF text, client-only tab states, authenticated forms, external sites and decorative media are not asserted extracted.'
        save()
    except BaseException:
        manifest['interrupted'] = True
        save()
        raise
    return destination, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=DATABASE)
    commands = parser.add_subparsers(dest='command', required=True)
    crawl = commands.add_parser('collect')
    crawl.add_argument('--max-pages', type=int, default=300)
    crawl.add_argument('--delay', type=float, default=0.3)
    commands.add_parser('status')
    imp = commands.add_parser('import')
    imp.add_argument('snapshot', type=Path)
    query = commands.add_parser('search')
    query.add_argument('query')
    query.add_argument('--allow-draft', action='store_true')
    query.add_argument('--limit', type=int, default=5)
    args = parser.parse_args()
    if args.command == 'collect':
        if not 1 <= args.max_pages <= 1000 or not 0.1 <= args.delay <= 10:
            parser.error('Invalid collection bounds.')
        destination, manifest = collect(max_pages=args.max_pages, delay=args.delay)
        result = import_snapshot(args.db, destination)
        result.update(website_status(args.db), snapshot=str(destination),
                      html_frontier_exhausted=manifest['html_frontier_exhausted'])
    elif args.command == 'status':
        result = website_status(args.db)
    elif args.command == 'import':
        result = import_snapshot(args.db, args.snapshot)
    else:
        result = search_website(args.query, args.db, limit=args.limit, allow_draft=args.allow_draft)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
