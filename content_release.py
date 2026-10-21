"""Private, local content releases: stage, inspect, seal, publish and rollback.

Publishing selects immutable data, not school approval or a model update. The
original databases/captures are never edited. SQLite backups are consistent per
database; the pair has no cross-database transaction. One atomic pointer selects
the sealed pair. Semantic answer correctness still requires review.
"""
from __future__ import annotations

from contextlib import closing, contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import time

from content_store import ContentStore, canonical, shape_errors
from CORE.website_corpus import canonical_url, import_snapshot
from sqlite_retrieval import ReadOnlyContentStore
from tools import manage_snapshot as snapshots
from validate_content import validate_content


class ReleaseError(ValueError):
    """A content release operation was refused without changing active data."""
    status = 400
    code = 'content_release_invalid'


class ReleaseConflict(ReleaseError):
    """The active activation changed; refresh before retrying publication."""
    status = 409
    code = 'content_release_conflict'


class ReleaseInvalid(ReleaseError):
    """A staged/sealed release failed its contract; never fall back silently."""


CODE_FILES = ('content_release.py', 'content_store.py', 'validate_content.py',
              'website_retrieval.py', 'CORE/website_corpus.py',
              'CORE/document_corpus.py', 'CORE/client_tab_corpus.py',
              'sqlite_retrieval.py', 'project_policy.py', 'tools/manage_snapshot.py')
MAX_JSON = 4 * 1024 * 1024
ID_PATTERN = re.compile(r'release-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}')


def utc():
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    if not path.is_file() or path.stat().st_size > MAX_JSON:
        raise ReleaseInvalid('Missing or oversized release JSON.')
    try:
        value = json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(value, dict):
            raise ValueError('object required')
        return value
    except (ValueError, UnicodeError) as error:
        raise ReleaseInvalid('Invalid release JSON.') from error


def atomic_json(path, value):
    path = snapshots.no_links(path)
    temporary = path.with_name(path.name + '.' + secrets.token_hex(8) + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8', newline='\n') as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


class ContentReleaseManager:
    def __init__(self, root):
        self.root = snapshots.no_links(Path(root))
        self.directory = snapshots.contained(self.root, 'runtime/content-releases')
        self.pointer = self.directory / 'active.json'
        self._verified = {}

    @contextmanager
    def _lock(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        path = snapshots.no_links(self.directory / '.lock')
        with path.open('a+b') as handle:
            if handle.tell() == 0:
                handle.write(b'0'); handle.flush()
            deadline = time.monotonic() + 5
            while True:
                try:
                    handle.seek(0)
                    if os.name == 'nt':
                        import msvcrt
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise ReleaseConflict('Another content operation holds the release lock.')
                    time.sleep(0.025)
            try:
                yield
            finally:
                handle.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _path(self, release_id):
        if not isinstance(release_id, str) or ID_PATTERN.fullmatch(release_id) is None:
            raise ReleaseInvalid('Invalid release ID.')
        return snapshots.contained(self.directory, release_id)

    def _pointer(self):
        if not self.pointer.exists():
            # An activation receipt means a missing pointer is corruption, not
            # permission to silently serve the original legacy databases.
            if (self.directory / 'activated.json').exists():
                raise ReleaseInvalid('The active release pointer is missing.')
            return None
        snapshots.no_links(self.pointer)
        value = read_json(self.pointer)
        if (set(value) != {'schema_version', 'release_id', 'activation_token', 'activated_utc', 'actor', 'action', 'previous_activation_token'}
                or value['schema_version'] != 1
                or not re.fullmatch('[0-9a-f]{32}', str(value['activation_token']))):
            raise ReleaseInvalid('Invalid active release pointer.')
        self._path(value['release_id'])
        return value

    def _check_expected(self, expected_active):
        pointer = self._pointer()
        actual = pointer['activation_token'] if pointer else None
        if expected_active != actual:
            raise ReleaseConflict('Active release changed. Refresh and review the current release.')
        return pointer

    def _stage_metadata(self, release_id):
        value = read_json(self._path(release_id) / 'stage.json')
        if value.get('release_id') != release_id:
            raise ReleaseInvalid('Release identity mismatch.')
        return value

    def _mutable(self, release_id):
        path = self._path(release_id)
        self._stage_metadata(release_id)
        if (path / 'seal.json').exists():
            raise ReleaseInvalid('Validated releases are immutable; stage another release to edit.')
        return path / 'data'

    def _code(self):
        # Bind the actual installed implementation, not a copied editable file.
        code_root = Path(__file__).resolve().parent
        return {name: snapshots.sha(snapshots.contained(code_root, name)) for name in CODE_FILES}

    def _inventory(self, data_root, *, digest=True):
        records, total, folded = [], 0, set()
        for path in sorted(data_root.rglob('*')):
            path = snapshots.no_links(path)
            if not path.is_file():
                continue
            name = path.relative_to(data_root).as_posix()
            if not snapshots.allowed(name) or name.casefold() in folded:
                raise ReleaseInvalid('Unknown or case-colliding file in release data.')
            folded.add(name.casefold())
            info = path.stat(); total += info.st_size
            if total > snapshots.MAX_BYTES or len(records) >= snapshots.MAX_FILES:
                raise ReleaseInvalid('Release exceeds its bounded data-only size limit.')
            row = dict(path=name, bytes=info.st_size)
            if digest:
                row['sha256'] = snapshots.sha(path)
            else:
                row['mtime_ns'] = info.st_mtime_ns
                # DB hashes are cheap and checked on every resolution, even
                # when mtime was preserved by an outside process.
                if name in snapshots.DATABASES:
                    row['sha256'] = snapshots.sha(path)
            records.append(row)
        if not {name.casefold() for name in snapshots.DATABASES}.issubset(folded):
            raise ReleaseInvalid('Release databases are missing.')
        return records

    @staticmethod
    def _rebase(database, source_root, target_root):
        paths, _ = snapshots.capture_paths(database, str(source_root))
        with closing(sqlite3.connect(database)) as db:
            with db:
                for table, columns in snapshots.PATH_COLUMNS.items():
                    for column in columns:
                        for old, rel in paths.items():
                            db.execute('UPDATE ' + table + ' SET ' + column + '=? WHERE ' + column + '=?',
                                       (str(snapshots.contained(target_root, rel)), old))

    def stage(self, label, expected_active=None):
        if not isinstance(label, str) or not label.strip() or len(label) > 160:
            raise ReleaseInvalid('A release label of 1–160 characters is required.')
        with self._lock():
            pointer = self._check_expected(expected_active)
            source = self._resolve_pointer(pointer)['data_root'] if pointer else self.root
            return self._stage_from_source(label, pointer, Path(source))

    def _stage_from_source(self, label, pointer, source, *, code_upgrade=None):
        release_id = datetime.now(timezone.utc).strftime('release-%Y%m%dT%H%M%SZ-') + secrets.token_hex(6)
        path = self._path(release_id)
        # Existing backup preflights scope, checks every capture SHA and
        # uses the SQLite backup API, including committed WAL data.
        snapshots.backup(source, path)
        data = path / 'data'
        (path / 'payload').rename(data)
        self._rebase(data / snapshots.DATABASES[0], source, data)
        (path / 'manifest.json').rename(path / 'source-snapshot.json')
        metadata = dict(schema_version=1, release_id=release_id, label=label.strip(), created_utc=utc(),
            base_release_id=pointer['release_id'] if pointer else None,
            base_activation_token=pointer['activation_token'] if pointer else None,
            baseline=snapshots.data_summary(data))
        if code_upgrade is not None:
            metadata['code_upgrade'] = code_upgrade
        atomic_json(path / 'stage.json', metadata)
        return self._row(release_id)

    def stage_code_upgrade(self, label, expected_active):
        """Explicit local CLI recovery: COPY intact old data for new-code validation.

        Serving, normal staging, verification and activation still require exact
        installed-code equality. This operation never edits/reseals old bytes,
        changes the pointer, or marks the new candidate validated/published.
        """
        if not isinstance(label, str) or not label.strip() or len(label) > 160:
            raise ReleaseInvalid('A release label of 1–160 characters is required.')
        with self._lock():
            pointer = self._check_expected(expected_active)
            if pointer is None:
                raise ReleaseInvalid('Code upgrade requires an existing active sealed release.')
            release_id = pointer['release_id']
            self._stage_metadata(release_id)
            path = self._path(release_id)
            seal = self._verify(release_id, full=True, _allow_code_upgrade=True)
            old_seal_hash, old_stage_hash = snapshots.sha(path/'seal.json'), snapshots.sha(path/'stage.json')
            if snapshots.data_summary(path/'data') != seal.get('summary'):
                raise ReleaseInvalid('Sealed summary differs from the intact source databases.')
            installed_code = self._code()
            if seal['code'] == installed_code:
                raise ReleaseInvalid('Installed code is unchanged; use normal staging.')
            provenance = dict(action='explicit_local_code_upgrade_copy', source_release_id=release_id,
                source_activation_token=pointer['activation_token'], source_seal_sha256=old_seal_hash,
                source_stage_sha256=old_stage_hash, previous_code=seal['code'], installed_code=installed_code,
                changed_code_files=sorted(name for name in CODE_FILES if seal['code'][name] != installed_code[name]),
                original_seal_modified=False, active_changed=False,
                validation_required=True, explicit_publish_required=True)
            result = self._stage_from_source(label, pointer, path/'data', code_upgrade=provenance)
            candidate = self._stage_metadata(result['release_id'])
            # Check again after copying; native/concurrent changes are not a
            # license to quietly migrate a different snapshot or code version.
            self._verify(release_id, full=True, _allow_code_upgrade=True)
            if (snapshots.sha(path/'seal.json') != old_seal_hash
                    or snapshots.sha(path/'stage.json') != old_stage_hash
                    or self._code() != installed_code or candidate['baseline'] != seal['summary']):
                raise ReleaseInvalid('Source data, seal or installed code changed during the upgrade copy.')
            return result

    @staticmethod
    def _known_urls(data):
        with closing(snapshots.readonly(data / snapshots.DATABASES[0])) as db:
            return {row[0] for row in db.execute('SELECT url FROM pages UNION SELECT url FROM assets')}

    def _check_content(self, data, content):
        if not isinstance(content, dict):
            raise ReleaseInvalid('Content must be a JSON object.')
        if len(canonical(content).encode('utf-8')) > MAX_JSON:
            raise ReleaseInvalid('Content exceeds its bounded4MiB limit.')
        try:
            errors = shape_errors(content)
            if not errors:
                errors = validate_content(content)
        except (TypeError, AttributeError, KeyError) as error:
            raise ReleaseInvalid('Malformed content.') from error
        if errors:
            raise ReleaseInvalid('Content rejected: ' + '; '.join(errors[:12]))
        urls = self._known_urls(data)
        for source in content['sources']:
            url = source['source_url_or_filename']
            # Documents are accepted only when their actual saved original is
            # present in assets; filename-only and external origins are denied.
            if (not isinstance(url, str) or not url.startswith('https://nmct.edu.mn/')
                    or url not in urls):
                raise ReleaseInvalid('Every content source must reference a captured official URL.')

    def import_content(self, release_id, content):
        with self._lock():
            data = self._mutable(release_id)
            self._check_content(data, content)
            with ContentStore(data / snapshots.DATABASES[1]) as store:
                result = store.import_content(content, allow_draft=True, source_filename='local-admin-staged-import')
            return dict(release_id=release_id, **result, active_changed=False)

    def import_website(self, release_id, snapshot_path):
        with self._lock():
            data = self._mutable(release_id)
            source = snapshots.no_links(Path(snapshot_path))
            if not source.is_dir() or not source.is_relative_to(self.root):
                raise ReleaseInvalid('Website import must be an existing directory inside this project.')
            manifest = read_json(source / 'manifest.json')
            run_id = manifest.get('run_id')
            if not isinstance(run_id, str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,100}', run_id):
                raise ReleaseInvalid('Unsafe website capture run ID.')
            target = snapshots.contained(data, 'CORE/website/snapshots/' + run_id)
            if target.exists():
                raise ReleaseInvalid('Capture run already exists; preserve it and use a new run ID.')
            records = []
            for item in source.rglob('*'):
                item = snapshots.no_links(item)
                if item.is_file():
                    name = item.relative_to(source).as_posix()
                    snapshots.relative(name)
                    if item.suffix.casefold() not in snapshots.CAPTURE_EXTENSIONS:
                        raise ReleaseInvalid('Website capture contains a non-corpus file.')
                    records.append((name, item, snapshots.sha(item)))
            if (len(records) > snapshots.MAX_FILES or sum(p.stat().st_size for _, p, _ in records) > snapshots.MAX_BYTES):
                raise ReleaseInvalid('Website capture exceeds its bounded size limit.')
            if any(canonical_url(page.get('url')) != page.get('url') for page in manifest.get('pages', [])):
                raise ReleaseInvalid('Website page URL is outside the official public scope.')
            for doc in manifest.get('documents', []):
                url = doc.get('url')
                if not isinstance(url, str) or not url.startswith('https://nmct.edu.mn/'):
                    raise ReleaseInvalid('Document URL is outside the official source scope.')
            target.mkdir(parents=True)
            for name, original, digest in records:
                copied = snapshots.contained(target, name)
                copied.parent.mkdir(parents=True, exist_ok=True)
                with original.open('rb') as src, copied.open('xb') as dst:
                    shutil.copyfileobj(src, dst)
                if snapshots.sha(copied) != digest or snapshots.sha(original) != digest:
                    raise ReleaseInvalid('Capture changed during copying; staged import is incomplete.')
            result = import_snapshot(data / snapshots.DATABASES[0], target)
            snapshots.capture_integrity(data / snapshots.DATABASES[0], data, str(data))
            return dict(release_id=release_id, **result, active_changed=False)

    @staticmethod
    def _content(data):
        with ReadOnlyContentStore(data / snapshots.DATABASES[1]) as store:
            return store.export()

    @staticmethod
    def _changes(before, after):
        result = dict(package_changed=before['content']['package_id'] != after['content']['package_id'],
                      corpus_changed=before['website']['corpus_id'] != after['website']['corpus_id'], counts={})
        for group in ('website', 'content'):
            left, right = before[group]['counts'], after[group]['counts']
            result['counts'][group] = {key: dict(before=left.get(key, 0), after=right.get(key, 0),
                delta=right.get(key, 0)-left.get(key, 0)) for key in sorted(set(left) | set(right))
                if type(left.get(key, 0)) is int and type(right.get(key, 0)) is int}
        return result

    @staticmethod
    def _check_page_text(data):
        """Bind DB text and chunk offsets back to saved captured originals."""
        with closing(snapshots.readonly(data / snapshots.DATABASES[0])) as db:
            for row in db.execute('SELECT url,version,text,text_sha256 FROM pages'):
                if hashlib.sha256(row['text'].encode('utf-8')).hexdigest() != row['text_sha256']:
                    raise ReleaseInvalid('Website DB text digest differs from its capture.')
                for chunk in db.execute('SELECT start_offset,end_offset,text FROM chunks WHERE url=? AND version=?',
                                        (row['url'], row['version'])):
                    start, end = chunk['start_offset'], chunk['end_offset']
                    if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(row['text'])
                            or row['text'][start:end] != chunk['text']):
                        raise ReleaseInvalid('Website chunk is not an exact captured text slice.')
            for row in db.execute('SELECT c.text_path,p.text,p.text_sha256 FROM captures c JOIN pages p ON p.url=c.url AND p.version=c.version'):
                relative = snapshots.old_relative(row['text_path'], str(data))
                saved = snapshots.contained(data, relative).read_text(encoding='utf-8')
                if saved != row['text']:
                    raise ReleaseInvalid('Website DB text differs from its saved original.')

    @staticmethod
    def _record_diff(before, after, identity):
        left = {str(item[identity]): item for item in before}
        right = {str(item[identity]): item for item in after}
        return dict(added=sorted(right.keys()-left.keys()), removed=sorted(left.keys()-right.keys()),
                    updated=sorted(key for key in left.keys() & right.keys() if canonical(left[key]) != canonical(right[key])))

    def validate(self, release_id):
        with self._lock():
            path = self._path(release_id)
            metadata = self._stage_metadata(release_id)
            if (path / 'seal.json').exists():
                self._verify(release_id, full=True)
                return self._row(release_id)
            data = self._mutable(release_id)
            for name in snapshots.DATABASES:
                snapshots.check_sqlite(data / name)
            snapshots.capture_integrity(data / snapshots.DATABASES[0], data, str(data))
            self._check_page_text(data)
            content = self._content(data)
            self._check_content(data, content)
            summary = snapshots.data_summary(data)
            changes = self._changes(metadata['baseline'], summary)
            base = self.root if metadata['base_release_id'] is None else self._path(metadata['base_release_id']) / 'data'
            old_content = self._content(base)
            for group, identity in (('sources', 'document_id'), ('facts', 'fact_id'), ('faqs', 'faq_id')):
                changes[group] = self._record_diff(old_content[group], content[group], identity)
            changes['details'] = {}
            for group, identity in (('sources', 'document_id'), ('facts', 'fact_id'), ('faqs', 'faq_id')):
                left = {item[identity]: item for item in old_content[group]}
                right = {item[identity]: item for item in content[group]}
                keys = sorted(set(changes[group]['added'] + changes[group]['updated'] + changes[group]['removed']))
                changes['details'][group] = [dict(id=key, before=left.get(key), after=right.get(key)) for key in keys]
            def pages(root):
                with closing(snapshots.readonly(root / snapshots.DATABASES[0])) as db:
                    run = db.execute('SELECT run_id FROM crawl_runs ORDER BY retrieved_at DESC LIMIT 1').fetchone()[0]
                    return [dict(row) for row in db.execute('SELECT p.url,p.text_sha256 FROM pages p JOIN captures c ON p.url=c.url AND p.version=c.version WHERE c.run_id=?', (run,))]
            changes['website_urls'] = self._record_diff(pages(base), pages(data), 'url')
            inventory = self._inventory(data)
            seal = dict(schema_version=1, release_id=release_id, validated_utc=utc(), summary=summary,
                changes=changes, files=inventory, code=self._code(), semantic_correctness_proven=False,
                school_staff_approval_claimed=False, review_required='Operator reviews changed sources, facts and FAQ before publication.',
                stage_sha256=snapshots.sha(path / 'stage.json'))
            atomic_json(path / 'seal.json', seal)
            self._verify(release_id, full=True)
            return self._row(release_id)

    def _verify(self, release_id, *, full=False, _allow_code_upgrade=False):
        path = self._path(release_id)
        seal_path = snapshots.no_links(path / 'seal.json')
        seal = read_json(seal_path)
        stored_code = seal.get('code')
        if (not isinstance(stored_code, dict) or set(stored_code) != set(CODE_FILES)
                or any(not isinstance(digest, str) or re.fullmatch('[0-9a-f]{64}', digest) is None
                       for digest in stored_code.values())):
            raise ReleaseInvalid('Invalid sealed code inventory; expected exact installed-code names and SHA256 values.')
        if (seal.get('schema_version') != 1 or seal.get('release_id') != release_id
                or seal.get('stage_sha256') != snapshots.sha(path / 'stage.json')
                or (not _allow_code_upgrade and stored_code != self._code())):
            raise ReleaseInvalid('Release identity, metadata or installed code changed since validation.')
        data = path / 'data'
        stamp = self._inventory(data, digest=False)
        cache_key = (snapshots.sha(seal_path), canonical(stamp))
        if full or self._verified.get(release_id) != cache_key:
            if self._inventory(data) != seal.get('files'):
                raise ReleaseInvalid('Sealed release data was modified or is missing.')
            self._verified[release_id] = cache_key
        return seal

    def verify(self, release_id, full=True):
        return self._verify(release_id, full=full)

    def content(self, release_id):
        path = self._path(release_id)
        self._stage_metadata(release_id)
        if (path / 'seal.json').exists():
            self._verify(release_id)
        return self._content(path / 'data')

    def inspect(self, release_id):
        return self._row(release_id)

    def _resolve_pointer(self, pointer):
        if pointer is None:
            return None
        release_id = pointer['release_id']; seal = self._verify(release_id)
        data = self._path(release_id) / 'data'
        return dict(release_id=release_id, activation_token=pointer['activation_token'],
            activated_utc=pointer['activated_utc'], root=str(data), data_root=str(data),
            content_database=str(data / snapshots.DATABASES[1]), website_database=str(data / snapshots.DATABASES[0]),
            corpus_id=seal['summary']['website']['corpus_id'], package_id=seal['summary']['content']['package_id'],
            counts=dict(website=seal['summary']['website']['counts'], content=seal['summary']['content']['counts']),
            label=self._stage_metadata(release_id)['label'], sealed=True)

    def resolve(self):
        return self._resolve_pointer(self._pointer())

    def _activate(self, release_id, expected_active, actor, action):
        if not isinstance(actor, str) or not actor.strip() or len(actor) > 120:
            raise ReleaseInvalid('Actor must be a short nonempty local audit label.')
        with self._lock():
            self._check_expected(expected_active)
            if (action == 'publish'
                    and self._stage_metadata(release_id)['base_activation_token'] != expected_active):
                raise ReleaseConflict('The candidate was staged from an older active release. Stage from the latest release and review its changes.')
            self._verify(release_id, full=True)
            pointer = dict(schema_version=1, release_id=release_id, activation_token=secrets.token_hex(16),
                           activated_utc=utc(), actor=actor.strip(), action=action,
                           previous_activation_token=expected_active)
            # A receipt makes a deleted/corrupt pointer fail closed. If process
            # termination occurs between these writes, manual repair is needed;
            # an unreviewed legacy fallback is never selected.
            atomic_json(self.directory / 'activated.json', dict(schema_version=1, ever_activated=True))
            atomic_json(self.pointer, pointer)
            atomic_json(self._path(release_id) / 'activation.json', pointer)
            history = snapshots.no_links(self.directory / 'activation-history')
            history.mkdir(exist_ok=True)
            atomic_json(history / (pointer['activation_token'] + '.json'), pointer)
            return self._resolve_pointer(pointer)

    def publish(self, release_id, expected_active, actor='local-admin'):
        return self._activate(release_id, expected_active, actor, 'publish')

    def rollback(self, release_id, expected_active, actor='local-admin'):
        if not (self._path(release_id) / 'activation.json').is_file():
            raise ReleaseInvalid('Rollback requires a previously activated release.')
        return self._activate(release_id, expected_active, actor, 'rollback')

    def _row(self, release_id):
        metadata = self._stage_metadata(release_id)
        result = {key: metadata[key] for key in ('release_id', 'label', 'created_utc', 'base_release_id')}
        result.update(status='staged', validation=None, error=None)
        result['sealed'] = (self._path(release_id) / 'seal.json').exists()
        result['activated_before'] = result['was_published'] = (self._path(release_id) / 'activation.json').is_file()
        if (self._path(release_id) / 'seal.json').exists():
            try:
                seal = self._verify(release_id)
                result.update(status='validated', validation={key: seal[key] for key in (
                    'validated_utc', 'summary', 'changes', 'semantic_correctness_proven', 'review_required')})
            except (OSError, ValueError, KeyError) as error:
                result.update(status='invalid', error=str(error))
        result['state'] = result['status']
        validation = result['validation']
        summary = validation['summary'] if validation else metadata['baseline']
        result['counts'] = {group: summary[group]['counts'] for group in ('website', 'content')}
        result['diff'] = validation['changes'] if validation else None
        return result

    def state(self):
        active, active_error = None, None
        try:
            active = self.resolve()
        except (OSError, ValueError, KeyError) as error:
            # Recovery UI may inspect old releases and CAS rollback a damaged
            # current data release. The public chat resolve() still fails closed.
            active_error = str(error)
            try:
                pointer = self._pointer()
                if pointer:
                    active = dict(release_id=pointer['release_id'], activation_token=pointer['activation_token'], invalid=True)
            except (OSError, ValueError, KeyError):
                pass
        releases = []
        if self.directory.exists():
            for path in sorted(self.directory.iterdir(), reverse=True):
                if ID_PATTERN.fullmatch(path.name) and path.is_dir():
                    try:
                        releases.append(self._row(path.name))
                    except (OSError, ValueError, KeyError) as error:
                        releases.append(dict(release_id=path.name, status='invalid', error=str(error)))
        return dict(schema_version=1, active_release_id=active['release_id'] if active else None,
                    active=active, active_error=active_error, releases=releases)
