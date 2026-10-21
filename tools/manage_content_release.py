"""Local content release CLI; no network, models or automatic school approval."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from content_release import ContentReleaseManager


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('status')
    stage = commands.add_parser('stage'); stage.add_argument('--label', required=True)
    stage.add_argument('--expected-active', default=None, help='Activation token; omitted only for the initial legacy state.')
    upgrade = commands.add_parser('stage-code-upgrade', help='Explicit local copy of intact old sealed data for current-code validation; never activates it.')
    upgrade.add_argument('--label', required=True)
    upgrade.add_argument('--expected-active', required=True, help='Exact current activation token, even when current code no longer serves the old seal.')
    for name in ('import-content', 'import-website', 'validate', 'verify', 'publish', 'rollback'):
        command = commands.add_parser(name); command.add_argument('--release-id', required=True)
        if name.startswith('import-'):
            command.add_argument('--path', type=Path, required=True)
        if name in ('publish', 'rollback'):
            command.add_argument('--expected-active', default=None)
            command.add_argument('--actor', default='local-admin')
    args = parser.parse_args(); manager = ContentReleaseManager(args.root)
    if args.command == 'status':
        result = manager.state()
    elif args.command == 'stage':
        result = manager.stage(args.label, args.expected_active)
    elif args.command == 'stage-code-upgrade':
        result = manager.stage_code_upgrade(args.label, args.expected_active)
    elif args.command == 'import-content':
        if args.path.stat().st_size > 4 * 1024 * 1024:
            raise ValueError('Content JSON exceeds4MiB.')
        result = manager.import_content(args.release_id, json.loads(args.path.read_text(encoding='utf-8-sig')))
    elif args.command == 'import-website':
        result = manager.import_website(args.release_id, args.path)
    elif args.command in ('publish', 'rollback'):
        result = getattr(manager, args.command)(args.release_id, args.expected_active, args.actor)
    else:
        result = getattr(manager, args.command)(args.release_id)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
