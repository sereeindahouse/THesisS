"""Synchronise the recorded project snapshot and this workspace's colours.

The agent still writes actual work, evidence and decisions into the note. This
command only projects the existing public plan/config into one marked block
and local workspace settings. It never opens evidence or configured paths.
"""
import argparse
from datetime import date
import json
import os
from pathlib import Path
import re
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from project_plan import public_plan, public_project_note

START = '<!-- project-state:start -->'
END = '<!-- project-state:end -->'
CONFIG = 'config/project-progress.json'
NOTE = 'CORE/PROJECT-NOTE.mn.md'
WORKSPACE = 'CORE/THesisS.code-workspace'
MAX_INPUT = 1024 * 1024
COLOURS = {
    'I': dict(active='#164E43', inactive='#203B36', accent='#88D4BB'),
    'II': dict(active='#203F70', inactive='#24354F', accent='#90B9F1'),
    'III': dict(active='#44316A', inactive='#342C46', accent='#C6A8EF'),
}


def _read(root, relative):
    path = (root / relative).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('Project note inputs must stay inside the project.')
    raw = path.read_bytes()
    if len(raw) > MAX_INPUT:
        raise ValueError('Project note input exceeds its size bound.')
    return path, raw, raw.decode('utf-8-sig')


def _line(value, label, limit):
    if (not isinstance(value, str) or not value.strip() or len(value) > limit
            or any(ord(c) < 32 or ord(c) == 127 for c in value)
            or '${' in value):
        raise ValueError(label + ' must be bounded, single-line recorded text.')
    return value.strip()


def _inline(value):
    # Snapshot text remains readable without creating links, HTML or headings
    # from a status string. The original user wording stays in config/manual note.
    value = ' '.join(str(value).split())
    value = value.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    return re.sub(r'([\\`*_{\}\[\]|])', r'\\\1', value)


def _snapshot(data, public, metadata):
    lines = [
        '**Одоогийн бүртгэл — ' + _inline(public['updated_date']) + '**',
        '',
        '- **Одоо:** ' + _inline(public['current_focus']),
        '- **Төлөв:** ' + _inline(public['status_label']),
        '- **Идэвхтэй хэсэг:** ' + metadata['active_workstream'],
    ]
    verified = metadata.get('verified_code_commit')
    if verified is not None:
        if not isinstance(verified, str) or not re.fullmatch(r'[0-9a-f]{40}', verified):
            raise ValueError('verified_code_commit must be an actual full Git SHA.')
        lines.append('- **Сүүлд бүртгэсэн шалгагдсан кодын суурь:** `' + verified + '`')
    basis = data.get('status_basis')
    if isinstance(basis, str) and basis.strip():
        lines.append('- **Бүртгэсэн нотолгоо:** ' + _inline(basis[:1600]))
    lines.extend(['', '| Хэсэг | Бүртгэсэн төлөв |', '|---|---|'])
    for item in public['workstreams']:
        lines.append('| ' + item['id'] + ' · ' + _inline(item['label']) + ' | '
                     + _inline(item['status_label']) + ' |')
    next_lens = next(item for item in public['lenses'] if item['id'] == 'next')
    lines.extend(['', '**Дараагийн алхам:** ' + _inline(next_lens['summary']), '',
        'Энэ блок нь бүртгэсэн төлөвийн хуулбар; шинэ туршилт, хүний үнэлгээ, '
        'дипломын completion хувь үүсгэдэггүй.'])
    return '\n'.join(lines)


def prepare(root):
    """Validate every input, then return both intended file changes in memory."""
    root = Path(root).resolve(strict=True)
    _, _, config_text = _read(root, CONFIG)
    note_path, note_raw, note_text = _read(root, NOTE)
    workspace_path, workspace_raw, workspace_text = _read(root, WORKSPACE)
    data = json.loads(config_text)
    workspace = json.loads(workspace_text)
    if not isinstance(data, dict) or not isinstance(workspace, dict):
        raise ValueError('Config and workspace must be JSON objects.')
    metadata = data.get('project_note')
    if not isinstance(metadata, dict):
        raise ValueError('project_note metadata is required.')
    active = metadata.get('active_workstream')
    if active not in COLOURS:
        raise ValueError('active_workstream must be I, II or III.')
    focus = _line(metadata.get('current_focus'), 'current_focus', 700)
    _line(metadata.get('status_label'), 'status_label', 300)
    updated = _line(metadata.get('updated_date'), 'updated_date', 10)
    if date.fromisoformat(updated).isoformat() != updated:
        raise ValueError('updated_date must use YYYY-MM-DD.')
    plan = public_plan(root, data.get('plan_status'))
    public = public_project_note({**data, 'plan': plan}, metadata)
    if not public.get('available'):
        raise ValueError('The canonical plan/project-note projection is unavailable.')
    if (note_text.count(START) != 1 or note_text.count(END) != 1
            or not re.search(r'(?m)^' + re.escape(START) + r'\r?$', note_text)
            or not re.search(r'(?m)^' + re.escape(END) + r'\r?$', note_text)):
        raise ValueError('The note needs exactly one complete snapshot marker block.')
    begin, finish = note_text.index(START) + len(START), note_text.index(END)
    if begin >= finish:
        raise ValueError('Snapshot markers are out of order.')
    newline = '\r\n' if '\r\n' in note_text else '\n'
    generated = _snapshot(data, public, metadata).replace('\n', newline)
    new_note = note_text[:begin] + newline + generated + newline + note_text[finish:]
    # Preserve BOM when present, as well as all manual content outside markers.
    note_bytes = new_note.encode('utf-8-sig' if note_raw.startswith(b'\xef\xbb\xbf') else 'utf-8')
    settings = workspace.setdefault('settings', {})
    if not isinstance(settings, dict):
        raise ValueError('Workspace settings must be an object.')
    custom = settings.setdefault('workbench.colorCustomizations', {})
    if not isinstance(custom, dict):
        raise ValueError('Workspace colour customizations must be an object.')
    palette = COLOURS[active]
    custom.update({
        'titleBar.activeBackground': palette['active'],
        'titleBar.activeForeground': '#FFFFFF',
        'titleBar.inactiveBackground': palette['inactive'],
        'titleBar.inactiveForeground': '#E0DFE8',
        'statusBar.background': palette['active'],
        'statusBar.foreground': '#FFFFFF',
        'activityBar.activeBorder': palette['accent'],
    })
    compact_focus = focus if len(focus) <= 90 else focus[:87] + '…'
    settings['window.title'] = ('[THesisS · ' + active + '] ' + compact_focus
                                + ' ${separator} ${dirty}${activeEditorShort}')
    workspace_bytes = (json.dumps(workspace, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    return [(note_path, note_raw, note_bytes), (workspace_path, workspace_raw, workspace_bytes)]


def _replace(path, content):
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.project-note-', delete=False) as handle:
            temp_name = handle.name
            handle.write(content)
            handle.flush()
        os.replace(temp_name, path)
    finally:
        if temp_name is not None and os.path.exists(temp_name):
            os.unlink(temp_name)


def sync(root=ROOT, *, check=False):
    changes = [(path, old, new) for path, old, new in prepare(root) if old != new]
    if check:
        return dict(synced=not changes, changed=[path.relative_to(Path(root).resolve()).as_posix() for path, _, _ in changes], check=True)
    written = []
    try:
        for path, old, new in changes:
            # Reject concurrent manual edits instead of overwriting them.
            if path.read_bytes() != old:
                raise ValueError('Project note input changed during synchronization.')
            _replace(path, new)
            written.append((path, old))
    except Exception:
        for path, old in reversed(written):
            _replace(path, old)
        raise
    return dict(synced=True, changed=[path.relative_to(Path(root).resolve()).as_posix() for path, _, _ in changes], check=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Report stale state without changing any file.')
    args = parser.parse_args(argv)
    try:
        result = sync(check=args.check)
    except (OSError, UnicodeError, ValueError, TypeError, OverflowError) as error:
        print('Project note sync failed: ' + str(error), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['synced'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
