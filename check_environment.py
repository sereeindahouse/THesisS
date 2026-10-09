"""Record local versions without using a microphone or online services."""
import argparse
from datetime import datetime, timezone
from importlib import metadata, util
import json
import os
from pathlib import Path
import platform
import sqlite3
import sys


PACKAGES = {
    'faster-whisper': 'faster_whisper',
    'edge-tts': 'edge_tts',
    'sounddevice': 'sounddevice',
    'scipy': 'scipy',
}


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='results/environment-2026-10-07.json')
    args = parser.parse_args()
    destination = Path(args.output)
    if destination.exists():
        parser.error('Output exists; choose a new filename.')
    versions = {}
    missing = []
    for package, module in PACKAGES.items():
        try:
            versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            versions[package] = None
        if versions[package] is None or util.find_spec(module) is None:
            missing.append(package)
    report = {
        'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'python': platform.python_version(),
        'executable': sys.executable,
        'virtual_environment': sys.prefix != sys.base_prefix,
        'platform': platform.platform(),
        'logical_cpu_count': os.cpu_count(),
        'processor': os.environ.get('PROCESSOR_IDENTIFIER') or platform.processor(),
        'sqlite': sqlite3.sqlite_version,
        'working_directory': str(Path.cwd()),
        'script_directory': str(Path(__file__).resolve().parent),
        'packages': versions,
        'missing_packages': missing,
        'checks_not_performed': ['microphone capture', 'model download', 'STT inference', 'online TTS', 'listening review'],
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Saved:', destination)
    print('Python:', report['python'], '| venv:', report['virtual_environment'])
    print('Missing packages:', ', '.join(missing) if missing else 'none (runtime checks still required)')
    return 1 if missing else 0


if __name__ == '__main__':
    raise SystemExit(main())
