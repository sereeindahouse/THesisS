"""Private data-only SQLite/capture backup and isolated restore; no models or network.

Each SQLite backup is transaction-consistent. The two independent databases do
not have a shared atomic transaction. A manifest binds both copies and every
capture byte; restoration never writes the original project or previous runs.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import sqlite3
import stat
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sqlite_retrieval import ReadOnlyContentStore
from website_retrieval import WebsiteRetriever

DATABASES = ('CORE/database/website.db', 'runtime/content.db')
PATH_COLUMNS = {'crawl_runs': ('snapshot_dir',), 'captures': ('html_path', 'text_path'),
                'assets': ('path',)}
OPTIONAL_FILES = (
    'CORE/website/catalog.json', 'CORE/website/summary.json',
    'CORE/website/document-excerpts-20261012.json',
    'CORE/website/document-excerpts-supplement-20261015.json',
    'CORE/website/client-tab-excerpts-20261015.json',
    'data/content-draft-v1.json', 'data/content-draft-v2-20261015.json',
    'data/content-evidence-v2-20261015.json',
    'config/content-use.json', 'config/project-progress.json',
    'config/stt-development.json', 'config/stt-context-development.json',
    'config/model-catalog/Cafet--whisper-small-mongolian.json',
    'config/model-catalog/intfloat--multilingual-e5-small.json',
    'config/model-catalog/gemma3-4b-text.json', 'config/releases/models-20261010.json')
DEVICE_NAMES = {'con', 'prn', 'aux', 'nul'} | {
    prefix + str(n) for prefix in ('com', 'lpt') for n in range(1, 10)}
MAX_FILES, MAX_BYTES = 10000, 512 * 1024 * 1024
CAPTURE_EXTENSIONS = frozenset({'.html', '.txt', '.json', '.png', '.pdf'})


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for part in iter(lambda: handle.read(4 * 1024 * 1024), b''):
            digest.update(part)
    return digest.hexdigest()


def relative(value):
    if not isinstance(value, str) or '\\' in value or ':' in value:
        raise ValueError('Require a portable relative path.')
    p = PurePosixPath(value)
    if (p.is_absolute() or not p.parts or str(p) != value
            or any(part in {'.', '..'} or part.endswith((' ', '.'))
                   or re.search(r'[\x00-\x1f<>"|?*]', part)
                   or part.partition('.')[0].casefold() in DEVICE_NAMES for part in p.parts)):
        raise ValueError('Unsafe relative path.')
    return p


def no_links(path):
    """Reject symlinks and Windows reparse points, including existing ancestors."""
    path = Path(path).absolute()
    for item in (path, *path.parents):
        if item.is_symlink():
            raise ValueError('Symlinks are not snapshot paths.')
        if item.exists():
            info = item.lstat()
            if getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 1024):
                raise ValueError('Reparse points are not snapshot paths.')
    return path.resolve()


def contained(root, name):
    p = no_links(root / Path(*relative(name).parts))
    if not p.is_relative_to(root):
        raise ValueError('Path escapes its root.')
    return p


def allowed(name):
    p = relative(name)
    return (name in DATABASES or name in OPTIONAL_FILES
            or (len(p.parts) >= 5 and p.parts[:3] == ('CORE', 'website', 'snapshots')
                and p.suffix.casefold() in CAPTURE_EXTENSIONS))


def old_relative(value, original_root):
    cls = PureWindowsPath if PureWindowsPath(original_root).drive else PurePosixPath
    origin, old = cls(original_root), cls(value)
    if not origin.is_absolute() or not old.is_absolute():
        raise ValueError('Database capture paths must be absolute.')
    rel = relative(old.relative_to(origin).as_posix())
    if rel.parts[:3] != ('CORE', 'website', 'snapshots') or len(rel.parts) < 4:
        raise ValueError('Database references an unknown external capture.')
    return rel.as_posix()


def readonly(path):
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA query_only=ON')
    return db


def check_sqlite(path):
    with closing(readonly(path)) as db:
        if db.execute('PRAGMA integrity_check').fetchall()[0][0] != 'ok':
            raise ValueError('SQLite integrity check failed.')
        if db.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('SQLite foreign-key check failed.')


def capture_paths(database, original_root):
    result, directories = {}, set()
    with closing(readonly(database)) as db:
        for table, columns in PATH_COLUMNS.items():
            for column in columns:
                for row in db.execute('SELECT DISTINCT ' + column + ' FROM ' + table):
                    result[row[0]] = old_relative(row[0], original_root)
                    if table == 'crawl_runs':
                        directories.add(result[row[0]])
        for old, rel in result.items():
            if not any(rel == d or rel.startswith(d + '/') for d in directories):
                raise ValueError('Capture does not belong to a recorded snapshot.')
    return result, sorted(directories)


def capture_integrity(database, storage_root, original_root):
    """Validate stored immutable manifests, HTML, text and original document bytes."""
    paths, directories = capture_paths(database, original_root)
    with closing(readonly(database)) as db:
        for run in db.execute('SELECT * FROM crawl_runs'):
            directory = contained(storage_root, paths[run['snapshot_dir']])
            manifest = directory / 'manifest.json'
            if sha(manifest) != run['manifest_sha256']:
                raise ValueError('Captured manifest checksum differs.')
            data = json.loads(manifest.read_bytes())
            if data['run_id'] != run['run_id']:
                raise ValueError('Capture run identity differs.')
            for page in data['pages']:
                for key, digest in (('html_file', 'html_sha256'), ('text_file', 'text_sha256')):
                    path = contained(directory, page[key])
                    if sha(path) != page[digest]:
                        raise ValueError('Captured HTML/text checksum differs.')
            for doc in data.get('documents', []):
                path = contained(directory, doc['file'])
                if sha(path) != doc['sha256'] or path.stat().st_size != doc['size_bytes']:
                    raise ValueError('Captured document checksum/size differs.')
        for row in db.execute('SELECT html_path,html_sha256 FROM captures'):
            if sha(contained(storage_root, paths[row['html_path']])) != row['html_sha256']:
                raise ValueError('Database HTML checksum differs.')
        for row in db.execute('SELECT path,sha256,size_bytes FROM assets'):
            path = contained(storage_root, paths[row['path']])
            if sha(path) != row['sha256'] or path.stat().st_size != row['size_bytes']:
                raise ValueError('Database asset checksum/size differs.')
    return paths, directories


def data_summary(root):
    status = WebsiteRetriever(root, use_dense=False).status()
    if not status['available']:
        raise ValueError('Website corpus is unavailable.')
    with ReadOnlyContentStore(root / DATABASES[1]) as store:
        content = dict(package_id=store.package_id(), counts=store.counts())
    return dict(website=dict(corpus_id=status['corpus_id'], counts=status['counts']), content=content)


def new_destination(path, *, allow_empty=False):
    path = no_links(path)
    if path.exists() and (not allow_empty or not path.is_dir() or any(path.iterdir())):
        raise FileExistsError('Require a new destination; existing contents are never overwritten.')
    return path


def disjoint(left, right):
    return not (left.is_relative_to(right) or right.is_relative_to(left))


def protect_original(root, destination):
    if destination.is_relative_to(root) and not destination.is_relative_to(root / 'runtime'):
        raise ValueError('New data destinations inside the original project must stay under runtime.')


def backup(root, output):
    root = no_links(root)
    output = new_destination(output)
    # A private runtime child is allowed; it is never among the copied inputs.
    if output == root or root.is_relative_to(output):
        raise ValueError('Snapshot output must not contain the source root.')
    protect_original(root, output)
    for name in DATABASES:
        path = contained(root, name)
        if not path.is_file():
            raise FileNotFoundError(path)
        check_sqlite(path)
    paths, directories = capture_integrity(root / DATABASES[0], root, str(root))
    if any(output.is_relative_to(contained(root, directory)) for directory in directories):
        raise ValueError('Snapshot output must not modify an original capture tree.')
    names = set(DATABASES)
    for directory in directories:
        source = contained(root, directory)
        for path in source.rglob('*'):
            no_links(path)
            if path.is_file():
                names.add(path.relative_to(root).as_posix())
    names.update(name for name in OPTIONAL_FILES if contained(root, name).is_file())
    if (any(not allowed(n) for n in names) or len(names) > MAX_FILES
            or len({name.casefold() for name in names}) != len(names)):
        raise ValueError('Snapshot file scope exceeds its fixed allowlist.')
    if sum(contained(root, n).stat().st_size for n in names) > MAX_BYTES:
        raise ValueError('Snapshot exceeds the bounded512MiB data limit.')
    expected = data_summary(root)
    output.mkdir(parents=True)
    payload = output / 'payload'
    records = []
    for name in sorted(names):
        source, target = contained(root, name), contained(payload, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        if name in DATABASES:
            with closing(readonly(source)) as src, closing(sqlite3.connect(target)) as dst:
                src.backup(dst)
                # A standalone archive must not depend on a source WAL header
                # or create sidecars merely when later opened read-only.
                dst.execute('PRAGMA journal_mode=DELETE')
            check_sqlite(target)
        else:
            before = sha(source)
            with source.open('rb') as src, target.open('xb') as dst:
                shutil.copyfileobj(src, dst)
            if before != sha(target) or before != sha(source):
                raise ValueError('Source changed while copying; incomplete snapshot retained.')
        records.append(dict(path=name, bytes=target.stat().st_size, sha256=sha(target)))
    capture_integrity(payload / DATABASES[0], payload, str(root))
    if data_summary(payload) != expected:
        raise ValueError('Database content changed during backup; incomplete snapshot retained.')
    manifest = dict(schema_version=1, kind='nmct_private_data_snapshot',
        created_utc=datetime.now(timezone.utc).isoformat(), source_root=str(root),
        sqlite_consistency='Each database uses SQLite backup; no cross-database atomicity claim.',
        models=dict(copied=False, downloaded=False, inferred=False,
                    policy='Use separately installed pinned local weights; catalogs/profiles only are copied.'),
        private=True,
        scope='Data-only SQLite, official capture trees and selected public configuration; not a complete experiment/project backup.',
        capture_policy=dict(allowed_extensions=sorted(CAPTURE_EXTENSIONS),
                            audio_model_files_allowed=False,
                            classification='Path/extension policy, not forensic content classification.'),
        excluded=['project source code', 'model weight directories', 'personal recording directories',
                  'private utterance references', 'study/evaluation outputs', 'voice session storage'],
        files=records, expected=expected)
    with (output / 'manifest.json').open('x', encoding='utf-8') as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2, allow_nan=False)
    verify(output)
    return dict(snapshot=str(output), files=len(records), bytes=sum(r['bytes'] for r in records),
                manifest_sha256=sha(output / 'manifest.json'), expected=expected, models_copied=False)


def verify(snapshot):
    snapshot = no_links(snapshot)
    manifest_path = contained(snapshot, 'manifest.json')
    if manifest_path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError('Snapshot manifest exceeds its bounded4MiB limit.')
    manifest = json.loads(manifest_path.read_bytes())
    if (manifest.get('schema_version') != 1 or manifest.get('kind') != 'nmct_private_data_snapshot'
            or manifest.get('models', {}).get('copied') is not False):
        raise ValueError('Unsupported snapshot manifest.')
    records = manifest.get('files')
    if not isinstance(records, list) or not 2 <= len(records) <= MAX_FILES:
        raise ValueError('Invalid bounded snapshot inventory.')
    names, total = set(), 0
    payload = contained(snapshot, 'payload')
    for row in records:
        name = row['path']
        if not allowed(name) or name.casefold() in names:
            raise ValueError('Unknown, unsafe or duplicate snapshot path.')
        names.add(name.casefold())
        if type(row['bytes']) is not int or row['bytes'] < 0 or not re.fullmatch('[0-9a-f]{64}', row['sha256']):
            raise ValueError('Invalid file checksum/size.')
        total += row['bytes']
        if total > MAX_BYTES:
            raise ValueError('Snapshot exceeds its size limit.')
        path = contained(payload, name)
        if not path.is_file() or path.stat().st_size != row['bytes'] or sha(path) != row['sha256']:
            raise ValueError('Snapshot file checksum/size differs.')
    actual = set()
    for path in snapshot.rglob('*'):
        no_links(path)
        if path.is_file():
            actual.add(path.relative_to(snapshot).as_posix())
    if actual != {'manifest.json'} | {'payload/' + row['path'] for row in records}:
        raise ValueError('Snapshot contains unknown or missing files.')
    if not set(DATABASES).issubset({row['path'] for row in records}):
        raise ValueError('Snapshot lacks its databases.')
    for name in DATABASES:
        check_sqlite(payload / name)
    capture_integrity(payload / DATABASES[0], payload, manifest['source_root'])
    return manifest


def restore(snapshot, destination):
    snapshot = no_links(snapshot)
    destination = new_destination(destination, allow_empty=True)
    if not disjoint(snapshot, destination):
        raise ValueError('Restore destination must be isolated from the snapshot.')
    manifest = verify(snapshot)  # Complete preflight before destination writes.
    source_root = no_links(manifest['source_root'])
    if destination == source_root or source_root.is_relative_to(destination):
        raise ValueError('Restore must not overwrite or contain the original project.')
    protect_original(source_root, destination)
    payload = snapshot / 'payload'
    destination.mkdir(parents=True, exist_ok=True)
    for row in manifest['files']:
        source, target = contained(payload, row['path']), contained(destination, row['path'])
        target.parent.mkdir(parents=True, exist_ok=True)
        with source.open('rb') as src, target.open('xb') as dst:
            shutil.copyfileobj(src, dst)
        if sha(target) != row['sha256']:
            raise ValueError('Copied restore bytes differ; partial destination retained.')
    database = destination / DATABASES[0]
    paths, _ = capture_paths(database, manifest['source_root'])
    with closing(sqlite3.connect(database)) as db:
        with db:
            for table, columns in PATH_COLUMNS.items():
                for column in columns:
                    for old, rel in paths.items():
                        db.execute('UPDATE ' + table + ' SET ' + column + '=? WHERE ' + column + '=?',
                                   (str(contained(destination, rel)), old))
    for name in DATABASES:
        check_sqlite(destination / name)
    capture_integrity(database, destination, str(destination))
    restored = data_summary(destination)
    if restored != manifest['expected']:
        raise ValueError('Restored corpus/package IDs or counts differ.')
    result = dict(restored_root=str(destination), snapshot_manifest_sha256=sha(snapshot / 'manifest.json'),
                  verified=restored, sqlite_paths_rebased=True, models_copied=False,
                  model_downloads=0, inference_calls=0, original_project_modified=False)
    with (destination / 'restore-report.json').open('x', encoding='utf-8') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
    return result


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    create = sub.add_parser('backup'); create.add_argument('--root', type=Path, default=ROOT)
    create.add_argument('--output', type=Path, required=True)
    check = sub.add_parser('verify'); check.add_argument('--snapshot', type=Path, required=True)
    recover = sub.add_parser('restore'); recover.add_argument('--snapshot', type=Path, required=True)
    recover.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    if args.action == 'backup':
        result = backup(args.root, args.output)
    elif args.action == 'restore':
        result = restore(args.snapshot, args.destination)
    else:
        value = verify(args.snapshot)
        result = dict(verified=True, files=len(value['files']), expected=value['expected'])
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
