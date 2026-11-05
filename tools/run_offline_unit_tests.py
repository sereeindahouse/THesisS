"""Run unchanged discovery in an asset-free temporary source copy.

No runtime, models, database, audio, secret, or real transcript is read/copied.
The default denies all socket connections. --allow-loopback explicitly permits
isolated HTTP integration tests; it never permits a remote address. This wrapper
does not hide, rewrite, or skip tests that fail under the chosen restrictions.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {'.py', '.js', '.html', '.css', '.json', '.md', '.txt', '.svg',
                 '.bib', '.toml', '.yml', '.yaml', '.ini', '.cmd', '.bat', '.ps1',
                 '.code-workspace'}
PUBLIC_DIRECTORIES = {'CORE', 'config', 'demo', 'schemas', 'tests', 'tools'}
NEW_SOURCE_NAMES = {'reception_tables.py', 'stt_text_normalization.py', 'mn_numbers.py'}
PUBLIC_DATA_INPUTS = {'data/content-draft-v1.json', 'data/content-draft-v2-20261015.json',
                      'data/content-evidence-v2-20261015.json', 'data/rag-locked-questions-20261102.json',
                      'data/stt-recording-kit/README.mn.md', 'data/stt-recording-kit/questions.mn.md',
                      'data/stt-recording-kit/consent.mn.md', 'data/stt-recording-kit/manifest.example.json'}


def permitted(name):
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {'..', '.git', 'runtime', 'models', 'audio',
                                         '__pycache__', 'secrets'} for part in path.parts):
        return False
    if path.suffix.lower() in {'.db', '.sqlite', '.sqlite3', '.wav', '.mp3', '.dpapi',
                              '.safetensors', '.bin', '.pem', '.key', '.env'}:
        return False
    if name in PUBLIC_DATA_INPUTS:
        return True
    if len(path.parts) > 1 and path.parts[0] not in PUBLIC_DIRECTORIES:
        return False
    if path.suffix.lower() == '.md' and name != 'CORE/WEEKLY-PLAN-2026-2027.mn.md':
        return False
    if path.parts[0] == 'CORE' and path.suffix.lower() == '.json':
        return False
    # Binary fixtures are allowed only in the explicitly fake reception fixture set.
    if path.suffix.lower() in {'.csv', '.xlsx'}:
        return path.parts[:3] == ('tests', 'fixtures', 'reception_fake')
    return path.suffix.lower() in TEXT_SUFFIXES or path.name in {'.gitignore', '.gitattributes'}


def source_names():
    # A path listing reads only Git metadata; the predicate runs before opening files.
    listed = subprocess.check_output(
        ['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=ROOT)
    names = {name.decode('utf-8') for name in listed.split(b'\0') if name}
    # New work may still be excluded by the project's exact public allowlist.
    # Enumerate only these source directories, never the repository as a whole.
    names.update(name for name in NEW_SOURCE_NAMES if (ROOT / name).is_file())
    for directory in ('tests', 'docs'):
        for path in (ROOT / directory).rglob('*'):
            name = path.relative_to(ROOT).as_posix()
            if permitted(name) and path.is_file():
                names.add(name)
    for name in ('config/reception-tables.json', 'config/stt-text-normalization.json',
                 'tools/run_offline_unit_tests.py'):
        if (ROOT / name).is_file():
            names.add(name)
    return sorted(name for name in names if permitted(name))


def guard_source(original_root, allow_loopback, strict_assets=False):
    # sitecustomize is inherited by Python children through PYTHONPATH. Python -S
    # smoke tests deliberately do not import sitecustomize, but load only source.
    return '''import ipaddress, os, sys
_original = %r
_allow_loopback = %r
_strict_assets = %r
def _audit(event, args):
    if _strict_assets and event in {'open', 'os.mkdir', 'sqlite3.connect'} and args and isinstance(args[0], (str, bytes, os.PathLike)):
        name = os.fsdecode(args[0])
        parts = name.replace('\\\\', '/').casefold().split('/')
        if (any(part in {'runtime', 'models', 'audio', 'secrets'} for part in parts)
                or name.casefold().endswith(('.db', '.sqlite', '.sqlite3', '.dpapi', '.wav', '.mp3', '.safetensors', '.bin', '.pem', '.key', '.env'))
                or event == 'sqlite3.connect' and name != ':memory:'):
            raise PermissionError('Strict asset policy forbids even temporary runtime/model/audio/database fixtures')
    if event == 'open' and args and isinstance(args[0], (str, bytes, os.PathLike)):
        target = os.path.normcase(os.path.abspath(os.fsdecode(args[0])))
        if target.startswith(_original + os.sep):
            relative = target[len(_original)+1:]
            pieces = relative.replace('\\\\', '/').split('/')
            if (pieces[0] in {'runtime', 'models', 'audio', 'data', 'secrets'}
                    or target.endswith(('.db', '.sqlite', '.sqlite3', '.dpapi', '.wav', '.mp3', '.pem', '.key', '.env'))):
                raise PermissionError('Original project assets are excluded from isolated tests')
    if event in {'socket.connect', 'socket.bind', 'socket.sendto', 'socket.getaddrinfo'}:
        address = args[0] if event == 'socket.getaddrinfo' else args[1]
        host = address[0] if isinstance(address, tuple) else address
        if not _allow_loopback:
            raise PermissionError('No sockets allowed in this test run')
        if host == 'localhost': return
        try: allowed = ipaddress.ip_address(host).is_loopback
        except (ValueError, TypeError): allowed = False
        if not allowed:
            raise PermissionError('Remote network access is forbidden in isolated tests')
sys.addaudithook(_audit)
import json, unittest
class _RecordedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._passed = 0
    def addSuccess(self, test):
        self._passed += 1
        super().addSuccess(test)
    def stopTestRun(self):
        super().stopTestRun()
        report = dict(tests_run=self.testsRun, passed=self._passed,
            failures=len(self.failures), errors=len(self.errors), skipped=len(self.skipped),
            expected_failures=len(self.expectedFailures), unexpected_successes=len(self.unexpectedSuccesses),
            successful=self.wasSuccessful(),
            failure_ids=[t.id() for t, _ in self.failures],
            error_ids=[t.id() for t, _ in self.errors],
            skip_reasons=[reason for _, reason in self.skipped],
            failure_counts_include_subtests=True)
        with open(os.path.join(os.path.dirname(__file__), 'test-summary.json'), 'w', encoding='utf-8') as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
unittest.TextTestRunner.resultclass = _RecordedResult
''' % (os.path.normcase(str(original_root)), allow_loopback, strict_assets)


def report_destination(path):
    """Validate a new report path before test work; never replace an existing file."""
    if path is None:
        return None
    path = Path(path)
    if path.is_symlink():
        raise ValueError('Unsafe test report destination')
    output = path.resolve()
    if (output.suffix.lower() != '.json'
            or any(part.casefold() in {'runtime', 'models', 'audio', 'secrets', '.git'}
                   for part in output.parts)):
        raise ValueError('Unsafe test report destination')
    if output.exists():
        raise FileExistsError('Preserve the existing report; choose a new destination')
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-loopback', action='store_true',
                        help='Permit only temporary loopback integration-test connections.')
    parser.add_argument('--list-only', action='store_true',
                        help='Import/discover all tests, print the count; run no test bodies.')
    parser.add_argument('--pattern', default='test*.py', help='Default is the full discovery pattern.')
    parser.add_argument('--strict-assets', action='store_true',
                        help='Also deny temporary runtime/model/audio/database fixtures; tests may error.')
    parser.add_argument('--report', type=Path,
                        help='Write counts and test IDs (no fixture content) to this JSON file.')
    args = parser.parse_args()
    output = report_destination(args.report)
    names = source_names()
    temp_root = Path(tempfile.gettempdir()).resolve()
    temporary = tempfile.TemporaryDirectory(prefix='thesiss-offline-tests-', dir=temp_root)
    destination = Path(temporary.name).resolve()
    if destination.parent != temp_root or destination == ROOT or ROOT.is_relative_to(destination):
        raise ValueError('Unsafe isolated test workspace')
    try:
        for name in names:
            source = ROOT / name
            # A tracked symlink cannot be used to import an excluded private asset.
            if source.is_symlink() or not source.resolve().is_relative_to(ROOT):
                raise ValueError('Source copy refuses symbolic links: ' + name)
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        (destination / 'sitecustomize.py').write_text(
            guard_source(ROOT, args.allow_loopback, args.strict_assets), encoding='utf-8')
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1',
                   PYTHONPATH=str(destination), HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
        # Providers are mocked by the unchanged tests; inherited environment keys
        # are removed as an additional guard, without reading credential values.
        for name in list(env):
            if any(part in name.upper() for part in ('TOKEN', 'SECRET', 'API_KEY', 'PASSWORD')):
                env.pop(name)
        if args.list_only:
            script = ('import json, unittest; s=unittest.defaultTestLoader.discover(".", '
                      'pattern='+repr(args.pattern)+'); '
                      'print(json.dumps({"discovered":s.countTestCases(),'
                      '"loader_errors":unittest.defaultTestLoader.errors})); '
                      'raise SystemExit(bool(unittest.defaultTestLoader.errors))')
            command = [sys.executable, '-B', '-X', 'utf8', '-c', script]
        else:
            command = [sys.executable, '-B', '-X', 'utf8', '-m', 'unittest', 'discover', '-p', args.pattern]
        print(json.dumps(dict(isolated=True, copied_source_files=len(names),
            production_assets_copied=False, socket_policy='loopback-only' if args.allow_loopback else 'deny-all',
            strict_assets=args.strict_assets, test_filter=args.pattern, list_only=args.list_only)), flush=True)
        result = subprocess.run(command, cwd=destination, env=env)
        summary = destination / 'test-summary.json'
        if summary.is_file():
            report = json.loads(summary.read_text(encoding='utf-8'))
            report.update(isolated=True, socket_policy='loopback-only' if args.allow_loopback else 'deny-all',
                strict_assets=args.strict_assets, production_assets_copied=False, test_filter=args.pattern)
            print(json.dumps({k:v for k,v in report.items() if not k.endswith('_ids')}), flush=True)
            if output is not None:
                # Recheck after execution and reserve exclusively. A concurrent
                # writer cannot make us overwrite a report or project config.
                if report_destination(output) != output:
                    raise ValueError('Test report destination changed')
                output.parent.mkdir(parents=True, exist_ok=True)
                with output.open('x', encoding='utf-8') as stream:
                    stream.write(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        return result.returncode
    finally:
        if destination.parent != temp_root:
            raise ValueError('Temporary cleanup escaped its verified parent')
        temporary.cleanup()


if __name__ == '__main__':
    raise SystemExit(main())
