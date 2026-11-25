"""Build the chat-only copy of the assistant in a folder of its own.

The copy holds what the chat needs and nothing else: chat_server.py, the page (web/index.html), the
Python modules chat_server imports, their settings, the two content databases as now published, the
school's tables, the teacher pictures taken from the school website, and the retrieval model. Run it
again after any change; only files that differ are copied, and files an earlier build put there and
this one no longer needs are removed.

    .venv/Scripts/python.exe tools/build_chat_clone.py                 # -> ../../shmtk-assistant
    .venv/Scripts/python.exe tools/build_chat_clone.py --target D:/x   # another folder
    .venv/Scripts/python.exe tools/build_chat_clone.py --dry-run       # list, copy nothing

Nothing is sent anywhere. The speech-service key stays an encrypted file readable only by this Windows
user; it is copied only when the copy has none (--no-key leaves it out).
"""
import argparse
import ast
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ENTRY = 'chat_server'
# The chat reads the published databases directly, so the release tooling is not part of the copy.
EXCLUDED_MODULES = frozenset({'content_release'})
CONFIG = ('answer-selection.json', 'content-use.json', 'faq-intents.json', 'knowledge-domains.json',
          'knowledge-topics.json', 'question-planner.json', 'reception-tables.json', 'referral.json',
          'retrieval-morphology.json', 'stt-audio-cleanup.json', 'stt-development.json',
          'stt-text-normalization.json', 'stt-vocabulary.json',
          'model-catalog/intfloat--multilingual-e5-small.json')
OPTIONAL_FILES = ('data/stt-model-choice.json', 'requirements.txt', 'requirements-modeltools.txt')
TREES = ('models/multilingual-e5-small', 'runtime/quality-media-20261021/teacher-media')
KEY_FILE = 'runtime/gemini-credentials.dpapi'
MANIFEST = '.build-files.json'
# Development notes kept beside the settings; no code reads them (a referral rule's own `note_mn` is
# shown to the visitor and stays).
NOTE_KEYS = frozenset({'note', 'purpose_mn', 'latin_note_mn', 'reviewed_note_mn', 'note_mn_rule'})
NOTE_PARENTS = frozenset({None, 'corrections', 'question_offices', 'topic_offices'})

START_CMD = '''@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PY={python}"
if not exist "%PY%" set "PY=python"
echo ШМТК-ийн ухаалаг туслах асаж байна. Хөтөч өөрөө нээгдэнэ: http://127.0.0.1:{port}
echo Зогсоохдоо энэ цонхыг хаана уу.
"%PY%" -X utf8 chat_server.py --port {port} --open
pause
'''

README = '''# ШМТК-ийн ухаалаг туслах — чат

Шинэ Монгол технологийн коллежийн талаарх асуултад Монголоор, бичгээр болон дуугаар хариулдаг туслах.

## Асаах

`start.cmd` файлыг хоёр товшино. Хөтөч дээр `http://127.0.0.1:{port}` хуудас нээгдэнэ.
Зогсоохдоо хар цонхыг хаана.

## Яаж ажилладаг вэ

1. Асуултыг бичнэ эсвэл микрофоноор хэлнэ. Яриаг Gemini 3.5 Transcribe үйлчилгээ текст болгоно.
2. Асуултыг ойлгоно: нийлмэл асуултыг хэсэглэнэ, «Сэлмаа багш», «Компьютерын 2-р курс» гэх мэт нэрийг
   хүснэгтийн бүтэн нэртэй нь холбоно (`question_planner.py`).
3. Хариултыг гурван газраас хайна (`rag_runtime.py`):
   - сургуулиас өгсөн хүснэгт — өрөө, ажилтан, анги, хичээлийн хуваарь (`reception_tables.py`);
   - хадгалсан асуулт, хариулт (`question_router.py`);
   - сургуулийн вэб сайтын хуулбар — түлхүүр үгийн (BM25) ба утгын (E5) хайлтыг нэгтгэнэ
     (`website_retrieval.py`), олдсон хэсгээс хариултыг дүрмээр сонгоно (`rule_selector.py`).
4. Хариултыг эх сурвалжийн үгээр, эх сурвалж ба огноотой нь харуулна. Систем өөрөө текст зохиодоггүй.
5. Хариулт олдоогүй бол аль албанд, хэдэн давхрын хэдэн тоотод хандахыг хэлнэ (`referral.py`).
6. «Сонсох» товчоор хариултыг дуугаар уншина (`voice_runtime.py`).

## Хавтасны бүтэц

| Хавтас, файл | Агуулга |
|---|---|
| `chat_server.py` | Сервер: хуудас ба `/api/route` (асуулт), `/api/voice/*` (дуу) |
| `web/index.html` | Чатын хуудас |
| `config/` | Тохиргоо: хариулт сонгох, асуулт ойлгох, хаана хандахыг заах, дуу таних үгийн жагсаалт |
| `CORE/database/website.db` | Сургуулийн вэб сайтын хуулбар (хуудас, хэсэг) |
| `runtime/content.db` | Хадгалсан асуулт, хариулт, баримт |
| `data/reception/` | Сургуулиас өгсөн хүснэгт: өрөө, ажилтан, анги, хуваарь |
| `models/multilingual-e5-small/` | Утгын хайлтын загвар (multilingual-e5-small) |

Ажилтны гар утасны дугаарыг систем харуулдаггүй (`privacy_filter.py`); сургуулийн имэйлийг л өгнө.
'''


def local_modules(entry=ENTRY, root=ROOT, excluded=EXCLUDED_MODULES):
    """{module name: path} for the project modules ``entry`` imports, directly or through others."""
    def path_of(name):
        parts = name.split('.')
        for candidate in (root.joinpath(*parts).with_suffix('.py'), root.joinpath(*parts, '__init__.py')):
            if candidate.is_file():
                return candidate
        return None
    found, todo = {}, [entry]
    while todo:
        name = todo.pop()
        if name in found or name in excluded:
            continue
        path = path_of(name)
        if path is None:
            continue
        found[name] = path
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8-sig'))):
            if isinstance(node, ast.Import):
                todo += [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                todo += [node.module] + [node.module + '.' + alias.name for alias in node.names]
    return found


def without_notes(value, parent=None):
    """The settings without their development notes."""
    if isinstance(value, dict):
        return {key: without_notes(item, key) for key, item in value.items()
                if not (key in NOTE_KEYS or key.endswith('_note_mn') or key == 'note_mn' and parent in NOTE_PARENTS)}
    if isinstance(value, list):
        return [without_notes(item, 'list') for item in value]
    return value


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def same_file(source, target):
    if not target.is_file() or source.stat().st_size != target.stat().st_size:
        return False
    # A large file with the same size and time is not read again (the 470 MB model).
    if source.stat().st_size > 8 << 20 and int(source.stat().st_mtime) == int(target.stat().st_mtime):
        return True
    return sha256(source) == sha256(target)


def plan(root=ROOT, *, with_model=True):
    """[(path in the copy, source path or bytes)] — everything the copy holds."""
    from chat_server import content_databases
    from reception_tables import CONFIG_PATH as RECEPTION_CONFIG
    items = {}
    for name, path in sorted(local_modules(root=root).items()):
        relative = path.relative_to(root).as_posix()
        items[relative] = path
        package = path.parent
        while package != root:                      # a package's __init__.py, when it has one
            init = package / '__init__.py'
            if init.is_file():
                items[init.relative_to(root).as_posix()] = init
            package = package.parent
    items['web/index.html'] = root / 'web/index.html'
    for name in CONFIG:
        path = root / 'config' / name
        text = json.dumps(without_notes(json.loads(path.read_text(encoding='utf-8-sig'))), ensure_ascii=False, indent=2)
        items['config/' + name] = (text + '\n').encode('utf-8')
    for name in OPTIONAL_FILES:
        if (root / name).is_file():
            items[name] = root / name
    content, website, _ = content_databases(root)
    items['runtime/content.db'] = content
    items['CORE/database/website.db'] = website
    reception = json.loads((root / RECEPTION_CONFIG).read_text(encoding='utf-8-sig'))
    if reception.get('enabled') is True:
        source = root / reception['source']
        for path in sorted(source.rglob('*') if source.is_dir() else [source]):
            if path.is_file():
                items[path.relative_to(root).as_posix()] = path
    for tree in TREES:
        if tree.startswith('models/') and not with_model:
            continue
        for path in sorted((root / tree).rglob('*')):
            if path.is_file():
                items[path.relative_to(root).as_posix()] = path
    return items


def build(target, *, root=ROOT, with_model=True, with_key=True, port=8780, dry_run=False, python=None):
    target = Path(target).resolve()
    if target == root or root.is_relative_to(target) or target.is_relative_to(root):
        raise SystemExit('The copy must live outside the project folder.')
    items = plan(root, with_model=with_model)
    python = python or next((str(path) for path in (root / '.venv-modeltools/Scripts/python.exe',
                                                    root / '.venv/Scripts/python.exe') if path.is_file()), 'python')
    # CRLF so cmd.exe reads the launcher; UTF-8 text is shown through «chcp 65001».
    items['start.cmd'] = START_CMD.format(python=python.replace('/', '\\'), port=port).replace('\n', '\r\n').encode('utf-8')
    items['README.md'] = README.format(port=port).encode('utf-8')
    copied, kept = [], 0
    for relative, source in items.items():
        destination = target / relative
        if isinstance(source, bytes):
            if destination.is_file() and destination.read_bytes() == source:
                kept += 1
                continue
            copied.append(relative)
            if not dry_run:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(source)
            continue
        if same_file(source, destination):
            kept += 1
            continue
        copied.append(relative)
        if not dry_run:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    key_copied = False
    if with_key and (root / KEY_FILE).is_file() and not (target / KEY_FILE).exists():
        key_copied = True                 # the encrypted file as it is; never read or printed
        if not dry_run:
            (target / KEY_FILE).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / KEY_FILE, target / KEY_FILE)
    # Files an earlier build wrote and this one does not: removed. Anything else in the folder stays.
    # With --skip-model the model already in the copy stays: the switch means «do not copy it now», not «remove
    # it» (code review 11/25).
    removed, kept_files = [], []
    protected = () if with_model else tuple(tree + '/' for tree in TREES if tree.startswith('models/'))
    manifest = target / MANIFEST
    try:
        previous = json.loads(manifest.read_text(encoding='utf-8')) if manifest.is_file() else []
    except ValueError:
        previous = []
    for relative in previous:
        if protected and relative.startswith(protected):
            kept_files.append(relative)
            continue
        stale = (target / relative).resolve()
        if relative not in items and stale.is_relative_to(target) and stale.is_file():
            removed.append(relative)
            if not dry_run:
                stale.unlink()
    if not dry_run:
        target.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps(sorted(set(items) | set(kept_files)), ensure_ascii=False, indent=0), encoding='utf-8')
    return dict(target=str(target), files=len(items), copied=copied, kept=kept, removed=removed,
                key_copied=key_copied, python=python,
                megabytes=round(sum(len(source) if isinstance(source, bytes) else source.stat().st_size
                                    for source in items.values()) / 1e6, 1))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--target', type=Path, default=ROOT.parent.parent / 'shmtk-assistant')
    parser.add_argument('--port', type=int, default=8780)
    parser.add_argument('--skip-model', action='store_true', help='leave the retrieval model out (keyword search only)')
    parser.add_argument('--no-key', action='store_true', help='do not copy the encrypted speech-service key')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    report = build(args.target, with_model=not args.skip_model, with_key=not args.no_key, port=args.port,
                   dry_run=args.dry_run)
    sys.stdout.reconfigure(encoding='utf-8')
    print(('Would build' if args.dry_run else 'Built') + f" {report['target']}: {report['files']} files, "
          f"{report['megabytes']} MB; copied {len(report['copied'])}, unchanged {report['kept']}, "
          f"removed {len(report['removed'])}; key copied: {report['key_copied']}")
    for name in report['copied'][:60]:
        print('  +', name)
    if len(report['copied']) > 60:
        print('  …', len(report['copied']) - 60, 'more')
    for name in report['removed']:
        print('  -', name)


if __name__ == '__main__':
    main()
