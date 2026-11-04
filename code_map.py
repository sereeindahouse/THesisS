"""Code map for /code-map: every tracked Python file, its size, purpose line and local imports.

Read live on each request (git ls-files + ast), so new code shows up as soon as it exists.
Only file names, line counts, the first docstring line and import edges leave this module;
file contents are never sent. The I/II/III colour is guessed from the file name.
"""
from __future__ import annotations

import ast
from pathlib import Path
import subprocess

_PARSED = {}  # (path, mtime_ns, size) -> (lines, doc, imported modules); an edit changes the key
SKIP_DIRS = {'.venv', '.venv-modeltools', 'runtime', 'models', '__pycache__', '.git', 'node_modules'}
DISTRICTS = {'.': 'Үндсэн код', 'tools': 'Хэрэгслүүд', 'tests': 'Тестүүд', 'CORE': 'CORE'}
WORKSTREAM_WORDS = (
    ('II', ('stt', 'voice', 'tts', 'gemini', 'whisper', 'audio', 'speech', 'transcri', 'listening', 'spoken')),
    ('I', ('rag', 'retriev', 'search', 'website', 'corpus', 'content', 'answer', 'rule', 'faq', 'knowledge',
           'topic', 'reception', 'sqlite', 'clarification', 'question', 'router', 'document', 'teacher', 'source')),
)


def tracked_python(root):
    root = Path(root)
    try:
        result = subprocess.run(['git', 'ls-files', '-z', '--', '*.py'], cwd=root, capture_output=True,
                                timeout=10, check=True)
        names = [name for name in result.stdout.decode('utf-8').split('\0') if name]
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError):
        names = [path.relative_to(root).as_posix() for path in root.rglob('*.py')
                 if not SKIP_DIRS.intersection(path.relative_to(root).parts)]
    return sorted(name for name in names if not SKIP_DIRS.intersection(Path(name).parts) and (root / name).is_file())


def workstream(name):
    lowered = name.lower()
    for label, words in WORKSTREAM_WORDS:
        if any(word in lowered for word in words):
            return label
    return 'III'


def summary(tree):
    doc = ast.get_docstring(tree) or ''
    first = next((line.strip() for line in doc.splitlines() if line.strip()), '')
    return first[:220]


def imported_modules(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            yield node.module
            yield from (f'{node.module}.{alias.name}' for alias in node.names)


def parsed(path):
    stat = path.stat()
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    if key not in _PARSED:
        text = path.read_text(encoding='utf-8', errors='replace')
        try:
            tree = ast.parse(text)
        except SyntaxError:
            tree = ast.Module(body=[], type_ignores=[])
        _PARSED[key] = (text.count('\n') + 1, summary(tree), tuple(imported_modules(tree)))
    return _PARSED[key]


def scan(root):
    """Return files with lines/doc/workstream and edges to local files they import."""
    root = Path(root)
    names = tracked_python(root)
    by_module = {name[:-3].replace('/', '.'): name for name in names}
    by_module.update({name[:-12].replace('/', '.'): name for name in names if name.endswith('/__init__.py')})
    stems = {}
    for name in names:
        stems.setdefault(Path(name).stem, []).append(name)
    files = []
    for name in names:
        lines, doc, modules = parsed(root / name)
        imports = set()
        for module in modules:
            target = by_module.get(module)
            if target is None and '.' not in module and len(stems.get(module, [])) == 1:
                target = stems[module][0]  # tools add their own folder to sys.path
            if target and target != name:
                imports.add(target)
        folder = name.split('/')[0] if '/' in name else '.'
        files.append({'path': name, 'district': DISTRICTS.get(folder, folder), 'lines': lines, 'doc': doc,
                      'workstream': workstream(name), 'imports': sorted(imports)})
    return {'files': files, 'edges': sum(len(item['imports']) for item in files),
            'workstream_rule': 'file_name_keywords_guess', 'contents_included': False}
