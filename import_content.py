"""Import, inspect and preview the local development content store."""
import argparse
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

from content_store import ContentStore

ROOT = Path(__file__).resolve().parent
DEFAULT_DB = ROOT / 'runtime' / 'content.db'


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=DEFAULT_DB)
    commands = parser.add_subparsers(dest='command', required=True)
    imp = commands.add_parser('import', help='Store a validated, immutable content-package snapshot.')
    imp.add_argument('content', type=Path)
    imp.add_argument('--allow-draft', action='store_true', help='Explicit development import; no approval is granted.')
    status = commands.add_parser('status')
    status.add_argument('--package-id')
    for name in ('list', 'preview'):
        command = commands.add_parser(name)
        command.add_argument('--kind', choices=['faq', 'fact'], default='faq')
        command.add_argument('--package-id')
        command.add_argument('--allow-draft', action='store_true', help='Development preview only; draft remains draft.')
        command.add_argument('--as-of', type=date.fromisoformat)
        if name == 'preview':
            command.add_argument('record_id')
    args = parser.parse_args()
    # Runtime artifacts stay below runtime by default; explicit DB paths permit temp/test stores.
    if args.command != 'import' and not args.db.is_file():
        parser.error('Database does not exist; import content first.')
    try:
        with ContentStore(args.db) as store:
            if args.command == 'import':
                content = json.loads(args.content.read_text(encoding='utf-8-sig'))
                result = store.import_content(content, source_filename=str(args.content), allow_draft=args.allow_draft)
                result.update(development_draft=bool(args.allow_draft), automatic_approval=False)
            elif args.command == 'status':
                package_id = store.package_id(args.package_id)
                result = {'package_id': package_id, 'counts': store.counts(package_id),
                          'packages': store.connection.execute('SELECT count(*) FROM packages').fetchone()[0],
                          'source_versions': store.connection.execute('SELECT count(*) FROM source_versions').fetchone()[0],
                          'sqlite_foreign_key_check': [tuple(row) for row in store.connection.execute('PRAGMA foreign_key_check')]}
            elif args.command == 'list':
                result = store.list_records(args.kind, package_id=args.package_id,
                                            allow_draft=args.allow_draft, as_of=args.as_of)
            else:
                result = store.preview(args.kind, args.record_id, package_id=args.package_id,
                                       allow_draft=args.allow_draft, as_of=args.as_of)
            print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, KeyError, OSError, sqlite3.DatabaseError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    main()
