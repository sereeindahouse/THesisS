"""Versioned local content storage; explicit draft previews are development only.

No model, router, automatic approval or generated answer is part of this module.
"""
import hashlib
import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from validate_content import validate_content


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


APPROVAL_FIELDS = {'approval_status', 'approved_by', 'approved_at', 'valid_from', 'valid_until'}


def shape_errors(content):
    """Check the fixed v1 shape before the existing domain/link validator."""
    errors = []
    if set(content) != {'schema_version', 'sources', 'facts', 'faqs'} or type(content.get('schema_version')) is not int:
        errors.append('Content must contain exactly schema_version, sources, facts and faqs.')
    required = {
        'sources': {'document_id', 'version', 'title', 'source_url_or_filename', 'retrieved_at',
                    'source_updated_at', 'scope', 'content_capture', 'notes'} | APPROVAL_FIELDS,
        'facts': {'fact_id', 'entity_id', 'key', 'value', 'source_refs', 'scope', 'notes'} | APPROVAL_FIELDS,
        'faqs': {'faq_id', 'question', 'answer', 'question_aliases', 'fact_ids', 'source_refs',
                 'scope', 'answer_status', 'notes'} | APPROVAL_FIELDS,
    }
    for group, fields in required.items():
        items = content.get(group)
        if not isinstance(items, list):
            errors.append(f'{group}: expected a list.')
            continue
        for number, item in enumerate(items):
            label = f'{group}[{number}]'
            if not isinstance(item, dict):
                errors.append(f'{label}: expected an object.')
                continue
            if set(item) != fields:
                errors.append(f'{label}: missing fields {sorted(fields - set(item))}; '
                              f'unknown fields {sorted(set(item) - fields)}.')
            if not isinstance(item.get('notes'), str):
                errors.append(f'{label}: notes must be a string.')
            if group == 'sources':
                if item.get('content_capture') not in ('selected_fact_extract', 'audit_metadata_only', 'full_snapshot'):
                    errors.append(f'{label}: invalid content_capture.')
                updated = item.get('source_updated_at')
                if updated is not None and not isinstance(updated, str):
                    errors.append(f'{label}: invalid source_updated_at.')
            else:
                references = item.get('source_refs')
                if not isinstance(references, list):
                    errors.append(f'{label}: source_refs must be a list.')
                else:
                    for reference in references:
                        if (not isinstance(reference, dict)
                                or set(reference) != {'document_id', 'version', 'locator'}
                                or not isinstance(reference.get('document_id'), str)
                                or type(reference.get('version')) is not int
                                or reference.get('version', 0) < 1
                                or not isinstance(reference.get('locator'), str)):
                            errors.append(f'{label}: invalid source reference shape.')
            if group == 'faqs':
                if item.get('answer_status') not in ('complete_in_scope', 'partial_in_scope'):
                    errors.append(f'{label}: invalid answer_status.')
                for field in ('question_aliases', 'fact_ids'):
                    value = item.get(field)
                    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
                        errors.append(f'{label}: {field} must be a list of strings.')
    return errors
DDL = """
CREATE TABLE packages (
    import_seq INTEGER PRIMARY KEY AUTOINCREMENT,
    package_id TEXT NOT NULL UNIQUE,
    schema_version INTEGER NOT NULL,
    imported_at TEXT NOT NULL,
    source_filename TEXT NOT NULL
);
CREATE TABLE source_versions (
    document_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK(version >= 1),
    content_sha256 TEXT NOT NULL,
    content_json TEXT NOT NULL,
    PRIMARY KEY(document_id, version)
);
CREATE TABLE package_sources (
    package_id TEXT NOT NULL REFERENCES packages(package_id),
    document_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY(package_id, document_id, version),
    FOREIGN KEY(document_id, version) REFERENCES source_versions(document_id, version)
);
CREATE TABLE facts (
    package_id TEXT NOT NULL REFERENCES packages(package_id),
    fact_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    fact_key TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY(package_id, fact_id)
);
CREATE TABLE faqs (
    package_id TEXT NOT NULL REFERENCES packages(package_id),
    faq_id TEXT NOT NULL,
    question TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY(package_id, faq_id)
);
CREATE TABLE citations (
    package_id TEXT NOT NULL,
    record_kind TEXT NOT NULL CHECK(record_kind IN ('fact', 'faq')),
    record_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    locator TEXT NOT NULL,
    PRIMARY KEY(package_id, record_kind, record_id, document_id, version, locator),
    FOREIGN KEY(package_id, document_id, version)
        REFERENCES package_sources(package_id, document_id, version)
);
CREATE TABLE faq_facts (
    package_id TEXT NOT NULL,
    faq_id TEXT NOT NULL,
    fact_id TEXT NOT NULL,
    PRIMARY KEY(package_id, faq_id, fact_id),
    FOREIGN KEY(package_id, faq_id) REFERENCES faqs(package_id, faq_id),
    FOREIGN KEY(package_id, fact_id) REFERENCES facts(package_id, fact_id)
);
PRAGMA user_version=1;
"""


class ContentStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute('PRAGMA foreign_keys=ON')
        version = self.connection.execute('PRAGMA user_version').fetchone()[0]
        tables = self.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
        if version == 0 and not tables:
            self.connection.executescript(DDL)
        elif version != 1 or {row['name'] for row in tables} != {
                'packages', 'source_versions', 'package_sources', 'facts', 'faqs', 'citations', 'faq_facts'}:
            self.connection.close()
            raise ValueError('Database is not a supported NMCT content store.')

    def close(self):
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def import_content(self, content, *, source_filename='', allow_draft=False):
        if not isinstance(content, dict):
            raise ValueError('Content must be a JSON object.')
        try:
            errors = shape_errors(content)
            if not errors:
                errors = validate_content(content, approved_only=not allow_draft)
        except (TypeError, AttributeError, KeyError) as error:
            raise ValueError('Malformed content fields; import rejected.') from error
        if errors:
            raise ValueError('Content import rejected:\n' + '\n'.join(errors))
        package_id = digest(content)
        db = self.connection
        if db.execute('SELECT 1 FROM packages WHERE package_id=?', (package_id,)).fetchone():
            return {'package_id': package_id, 'imported': False, 'counts': self.counts(package_id)}
        with db:
            db.execute('INSERT INTO packages(package_id,schema_version,imported_at,source_filename) VALUES(?,?,?,?)',
                       (package_id, content['schema_version'], datetime.now(timezone.utc).isoformat(), source_filename))
            for source in content['sources']:
                identity = (source['document_id'], source['version'])
                body = {key: value for key, value in source.items() if key not in APPROVAL_FIELDS}
                body_hash = digest(body)
                existing = db.execute('SELECT content_sha256 FROM source_versions WHERE document_id=? AND version=?',
                                      identity).fetchone()
                if existing and existing['content_sha256'] != body_hash:
                    raise ValueError(f'Source {identity} changed under the same version; increment version.')
                db.execute('INSERT OR IGNORE INTO source_versions VALUES(?,?,?,?)',
                           (*identity, body_hash, canonical(body)))
                db.execute('INSERT INTO package_sources VALUES(?,?,?,?)',
                           (package_id, *identity, canonical(source)))
            for fact in content['facts']:
                db.execute('INSERT INTO facts VALUES(?,?,?,?,?)',
                           (package_id, fact['fact_id'], fact['entity_id'], fact['key'], canonical(fact)))
            for faq in content['faqs']:
                db.execute('INSERT INTO faqs VALUES(?,?,?,?)',
                           (package_id, faq['faq_id'], faq['question'], canonical(faq)))
                for fact_id in set(faq['fact_ids']):
                    db.execute('INSERT INTO faq_facts VALUES(?,?,?)', (package_id, faq['faq_id'], fact_id))
            for group, kind, key in [('facts', 'fact', 'fact_id'), ('faqs', 'faq', 'faq_id')]:
                for item in content[group]:
                    for reference in item['source_refs']:
                        db.execute('INSERT OR IGNORE INTO citations VALUES(?,?,?,?,?,?)',
                                   (package_id, kind, item[key], reference['document_id'],
                                    reference['version'], reference['locator']))
        return {'package_id': package_id, 'imported': True, 'counts': self.counts(package_id)}

    def package_id(self, requested=None):
        if requested is None:
            row = self.connection.execute('SELECT package_id FROM packages ORDER BY import_seq DESC LIMIT 1').fetchone()
        else:
            row = self.connection.execute('SELECT package_id FROM packages WHERE package_id=?', (requested,)).fetchone()
        if row is None:
            raise KeyError('Requested content package not found; import content first.')
        return row['package_id']

    def counts(self, package_id=None):
        package_id = self.package_id(package_id)
        result = {}
        for table, label in [('package_sources', 'sources'), ('facts', 'facts'), ('faqs', 'faqs'),
                             ('citations', 'citations'), ('faq_facts', 'faq_fact_links')]:
            result[label] = self.connection.execute(
                f'SELECT count(*) FROM {table} WHERE package_id=?', (package_id,)).fetchone()[0]
        return result

    def export(self, package_id=None):
        package_id = self.package_id(package_id)
        content = {'schema_version': 1}
        for table, group, ordering in [('package_sources', 'sources', 'document_id,version'),
                                       ('facts', 'facts', 'fact_id'), ('faqs', 'faqs', 'faq_id')]:
            rows = self.connection.execute(
                f'SELECT payload_json FROM {table} WHERE package_id=? ORDER BY {ordering}', (package_id,)).fetchall()
            content[group] = [json.loads(row['payload_json']) for row in rows]
        return content

    def list_records(self, kind='faq', *, package_id=None, allow_draft=False, as_of=None):
        package_id = self.package_id(package_id)
        content = self.export(package_id)
        if kind not in {'faq', 'fact'}:
            raise ValueError('kind must be faq or fact.')
        return [self.preview(kind, item[f'{kind}_id'], package_id=package_id,
                             allow_draft=allow_draft, as_of=as_of, include_answer=False)
                for item in content[kind + 's']]

    def preview(self, kind, record_id, *, package_id=None, allow_draft=False, as_of=None, include_answer=True):
        if kind not in {'faq', 'fact'}:
            raise ValueError('kind must be faq or fact.')
        as_of = date.today() if as_of is None else as_of
        if not isinstance(as_of, date) or isinstance(as_of, datetime):
            raise ValueError('as_of must be a date.')
        package_id = self.package_id(package_id)
        content = self.export(package_id)
        sources = {(s['document_id'], s['version']): s for s in content['sources']}
        facts = {f['fact_id']: f for f in content['facts']}
        items = facts if kind == 'fact' else {f['faq_id']: f for f in content['faqs']}
        if record_id not in items:
            raise KeyError(f'{kind} {record_id} not found in package {package_id}.')
        item = items[record_id]
        checked = [(f'{kind}:{record_id}', item)]
        if kind == 'faq':
            checked.extend((f'fact:{fid}', facts[fid]) for fid in item['fact_ids'])
        citations = {}
        for _, dependency in list(checked):
            for ref in dependency['source_refs']:
                source = sources[(ref['document_id'], ref['version'])]
                checked.append((f'source:{ref["document_id"]}@{ref["version"]}', source))
                citation_key = (ref['document_id'], ref['version'], ref['locator'])
                citations[citation_key] = {**ref, 'title': source['title'],
                                          'source_url_or_filename': source['source_url_or_filename'],
                                          'approval_status': source['approval_status']}
        blocked, unknown = set(), set()
        for label, record in checked:
            state = record['approval_status']
            if state != 'approved' and not (allow_draft and state == 'draft'):
                blocked.add(f'{label}: approval_status={state}')
            valid_from, valid_until = record['valid_from'], record['valid_until']
            if valid_from is not None and date.fromisoformat(valid_from) > as_of:
                blocked.add(f'{label}: not yet valid for {as_of}')
            if valid_until is not None and date.fromisoformat(valid_until) < as_of:
                blocked.add(f'{label}: expired for {as_of}')
            if valid_from is None or valid_until is None:
                unknown.add(label)
        result = {'package_id': package_id, 'kind': kind, 'record_id': record_id,
                  'mode': 'development_draft' if allow_draft else 'approved_only',
                  'as_of': as_of.isoformat(), 'eligible': not blocked,
                  'blocked_reasons': sorted(blocked), 'unknown_validity_records': sorted(unknown),
                  'approval_status': item['approval_status'], 'scope': item['scope'],
                  'citations': [citations[key] for key in sorted(citations)],
                  'generated': False, 'automatic_approval': False}
        if kind == 'faq':
            result.update(question=item['question'], answer_status=item['answer_status'])
        if include_answer:
            result['answer' if kind == 'faq' else 'value'] = (
                item['answer' if kind == 'faq' else 'value'] if not blocked else None)
        return result
