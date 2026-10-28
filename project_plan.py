"""Read the one public weekly plan as bounded, inert data for the source atlas.

Calendar position never implies completed work. Progress declarations come from
an explicit small whitelist; this module never reads evidence paths or private
study records and never renders Markdown/HTML.
"""
from datetime import date, datetime, timedelta, timezone
import hashlib
from pathlib import Path
import re


PLAN_PATH = 'CORE/WEEKLY-PLAN-2026-2027.mn.md'
MAX_BYTES = 160 * 1024
MAX_WEEKS = 80
MAX_SECTIONS = 80
MAX_BLOCKS = 1800
MAX_TEXT = 12000
_WEEK = re.compile(r'^###\s+(W\d{2})\s+·\s+(\d{4}\.\d{2}\.\d{2})'
                   r'(?:[–-]((?:\d{4}\.)?\d{2}\.\d{2}))?\s+—\s+(.+?)\s*$')
_LOOKS_WEEK = re.compile(r'^###\s+W\d')
_HEADING = re.compile(r'^(#{1,6})\s+(.+)$')
_LIST = re.compile(r'^(?:[-*+]\s+|\d+\.\s+)')
_LABEL = re.compile(r'^\*\*(Хийх|Гарах|Тэнцэх|Үүрэг/хамаарал|Дууссан гэж үзэх):\*\*\s*(.*)$', re.S)
_FIELDS = {'Хийх': 'work', 'Гарах': 'deliverables', 'Тэнцэх': 'acceptance',
           'Үүрэг/хамаарал': 'dependencies', 'Дууссан гэж үзэх': 'acceptance'}
_STATES = {'planned': 'Төлөвлөсөн', 'in_progress': 'Үргэлжилж буй',
           'partial': 'Хэсэгчилсэн', 'done': 'Нотолгоотой дууссан'}


def _unavailable():
    return dict(available=False, message='Долоо хоногийн төлөвлөгөө одоогоор нээгдсэнгүй.',
                weeks=[], sections=[], components=[], current={})


def _text(value, limit=3000):
    if not isinstance(value, str):
        return ''
    try:
        value.encode('utf-8')
    except UnicodeError:
        return ''
    if any(ord(c) < 32 and c not in '\t\n\r' for c in value):
        return ''
    return value.strip()[:limit]


def _strings(value, count=24, limit=3000):
    if not isinstance(value, list):
        return []
    return [text for item in value[:count] if (text := _text(item, limit))]


def _blocks(lines):
    result, paragraph = [], []

    def flush():
        if paragraph:
            value = '\n'.join(paragraph).strip()
            if len(value) > MAX_TEXT:
                raise ValueError('Plan paragraph exceeds its bound.')
            result.append(dict(type='paragraph', text=value))
            paragraph.clear()

    for raw in lines:
        line = raw.strip()
        if not line:
            flush()
        elif (heading := _HEADING.match(line)):
            flush(); result.append(dict(type='heading', text=heading[2]))
        elif line.startswith('|'):
            flush()
            cells = line.strip('|').split('|')
            if not all(re.fullmatch(r'\s*:?-+:?\s*', cell) for cell in cells):
                result.append(dict(type='table_row', text=line))
        elif (bullet := _LIST.match(line)):
            flush()
            # Keep ordered-list numbers visible; remove only unordered markers.
            value = line[bullet.end():] if line[0] in '-*+' else line
            result.append(dict(type='list_item', text=value))
        else:
            paragraph.append(line)
    flush()
    if len(result) > MAX_BLOCKS or any(len(block['text']) > MAX_TEXT for block in result):
        raise ValueError('Plan block limit exceeded.')
    return result


def _dates(begin, finish):
    first = date.fromisoformat(begin.replace('.', '-'))
    if finish is None:
        return first, first
    if len(finish) == 5:
        end_year = first.year + ((int(finish[:2]), int(finish[3:])) < (first.month, first.day))
        finish = str(end_year) + '.' + finish
    last = date.fromisoformat(finish.replace('.', '-'))
    if not 0 <= (last - first).days <= 6:
        raise ValueError('Invalid weekly interval.')
    return first, last


def _parse(text):
    weeks, sections = [], []
    section = dict(title='Төлөвлөгөөний хүрээ', lines=[])
    week = None
    title = ''

    def finish_section():
        nonlocal section
        if section is not None:
            blocks = _blocks(section['lines'])
            if blocks:
                sections.append(dict(title=section['title'], blocks=blocks))
            section = None

    def finish_week():
        nonlocal week
        if week is not None:
            blocks = _blocks(week.pop('lines'))
            week.update(work=[], deliverables=[], acceptance=[], dependencies=[], blocks=[])
            for block in blocks:
                label = _LABEL.match(block['text']) if block['type'] == 'list_item' else None
                if label:
                    week[_FIELDS[label[1]]].append(label[2])
                elif block['type'] == 'list_item':
                    week['work'].append(block['text'])
                else:
                    week['blocks'].append(block)
            weeks.append(week)
            week = None

    for line in text.splitlines():
        match = _WEEK.match(line.strip())
        if match:
            finish_week(); finish_section()
            first, last = _dates(match[2], match[3])
            week = dict(id=match[1], start_date=first.isoformat(), end_date=last.isoformat(),
                        title=match[4], lines=[])
        elif _LOOKS_WEEK.match(line.strip()):
            raise ValueError('Malformed week heading.')
        elif line.startswith('## '):
            finish_week(); finish_section()
            section = dict(title=line[3:].strip(), lines=[])
        elif line.startswith('# ') and not title and week is None:
            title = line[2:].strip()
        elif week is not None:
            week['lines'].append(line)
        else:
            if section is None:
                section = dict(title='Төлөвлөгөөний тайлбар', lines=[])
            section['lines'].append(line)
    finish_week(); finish_section()
    if not 1 <= len(weeks) <= MAX_WEEKS or len(sections) > MAX_SECTIONS:
        raise ValueError('Plan needs a bounded weekly schedule.')
    if len(title) > 500 or any(len(entry['title']) > 500 for entry in weeks + sections):
        raise ValueError('Plan heading exceeds its bound.')
    if sum(len(s['blocks']) for s in sections) > MAX_BLOCKS:
        raise ValueError('Too many plan blocks.')
    for index, entry in enumerate(weeks, 1):
        if entry['id'] != f'W{index:02d}':
            raise ValueError('Week IDs must be unique and sequential.')
        if index < len(weeks) and (date.fromisoformat(entry['end_date']) - date.fromisoformat(entry['start_date'])).days != 6:
            raise ValueError('Only the final interval can be shorter than a week.')
        if index > 1 and date.fromisoformat(entry['start_date']) != date.fromisoformat(weeks[index-2]['end_date']) + timedelta(days=1):
            raise ValueError('Week dates must be contiguous.')
    return title, weeks, sections


def _status_fields(status, weeks, calendar_id):
    status = status if isinstance(status, dict) else {}
    declarations = status.get('weeks')
    declarations = declarations if isinstance(declarations, dict) else {}
    for week in weeks:
        item = declarations.get(week['id'])
        item = item if isinstance(item, dict) else {}
        evidence = _strings(item.get('evidence'))
        state = item.get('state') if isinstance(item.get('state'), str) else None
        state = state if state in _STATES else 'planned'
        label = _text(item.get('label'), 300) or _STATES[state]
        if state == 'done' and not evidence:
            state, label = 'partial', 'Нотолгоо дутуу'
        week.update(status=state, status_label=label, evidence=evidence,
                    next_actions=_strings(item.get('next_actions')))
    current_raw = status.get('current')
    current_raw = current_raw if isinstance(current_raw, dict) else {}
    ids = {week['id'] for week in weeks}
    current_id = current_raw.get('week_id')
    current_id = current_id if isinstance(current_id, str) and current_id in ids else calendar_id
    current_week = next((w for w in weeks if w['id'] == current_id), None)
    current = dict(week_id=current_id,
                   title=_text(current_raw.get('title'), 500) or (current_week['title'] if current_week else 'Төлөвлөгөөний хугацаа'),
                   status_label=_text(current_raw.get('status_label'), 300) or (current_week['status_label'] if current_week else 'Хуанлийн хүрээнээс гадуур'))
    for key in ('done', 'in_progress', 'next', 'human_tasks'):
        current[key] = _strings(current_raw.get(key))
    components = []
    raw_components = status.get('components')
    if isinstance(raw_components, list):
        used = set()
        for item in raw_components[:16]:
            if not isinstance(item, dict):
                continue
            identity = _text(item.get('id'), 64)
            label = _text(item.get('label'), 300)
            if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}', identity) or not label or identity in used:
                continue
            state = item.get('state') if isinstance(item.get('state'), str) else None
            state = state if state in _STATES else 'planned'
            used.add(identity)
            components.append(dict(id=identity, label=label, state=state,
                                   detail=_text(item.get('detail')), evidence_label=_text(item.get('evidence_label'), 1000)))
    return current_id, current, components, _text(status.get('policy_notice'), 4000), _text(status.get('updated_date'), 32)


def _workstreams(sections, weeks):
    """Project the three declared outcomes, never infer completion from dates.

    Legacy plans remain valid without this optional section. An incomplete or
    malformed declaration does not turn into a seemingly complete three-goal
    report. Week links are accepted only as one complete, explicit mapping.
    """
    source = next((s for s in sections if s['title'] == 'Дипломын 3 үндсэн хэсэг'), None)
    if source is None:
        return []
    labels = {'Үр дүн': 'goal', 'Дэд ажил': 'subgoals', 'Бэлэн': 'done',
              'Үлдсэн': 'remaining', 'Дуусах шалгуур': 'acceptance', 'Нотолгоо': 'evidence'}
    entries, current = [], None
    for block in source['blocks']:
        if block['type'] == 'heading':
            match = re.fullmatch(r'(I|II|III)\s*·\s*(.+)', block['text'])
            if not match:
                return []
            current = dict(id=match[1], title=match[2], week_ids=[],
                           **{key: [] for key in labels.values()})
            entries.append(current)
        elif current is not None and block['type'] == 'list_item':
            match = re.fullmatch(r'\*\*([^*]+):\*\*\s*(.+)', block['text'], re.S)
            if match and match[1] in labels:
                current[labels[match[1]]].append(match[2])
    if [item['id'] for item in entries] != ['I', 'II', 'III'] or any(
            not item['goal'] or not item['subgoals'] or not item['acceptance'] for item in entries):
        return []
    mapping_section = next((s for s in sections if s['title'] == 'Долоо хоног ба үндсэн хэсгийн холбоо'), None)
    mapping, valid_ids = {}, {week['id'] for week in weeks}
    for block in mapping_section['blocks'] if mapping_section else []:
        if block['type'] != 'table_row':
            continue
        cells = [cell.strip() for cell in block['text'].strip('|').split('|')]
        if not cells or not re.fullmatch(r'W\d{2}', cells[0]):
            continue
        if len(cells) < 2 or cells[0] not in valid_ids or cells[0] in mapping:
            mapping = {}; break
        ids = [value.strip() for value in cells[1].split(',')]
        if not ids or len(set(ids)) != len(ids) or any(value not in {'I', 'II', 'III'} for value in ids):
            mapping = {}; break
        mapping[cells[0]] = ids
    if set(mapping) == valid_ids:
        for week in weeks:
            week['workstream_ids'] = mapping[week['id']]
            for item in entries:
                if item['id'] in week['workstream_ids']:
                    item['week_ids'].append(week['id'])
    return entries


def public_plan(root, status=None, today=None):
    """Return this project's public weekly plan; invalid inputs fail closed.

    ``today`` is a date, useful in deterministic tests. Default uses UTC+8,
    Ulaanbaatar's current civil timezone, without an optional tzdata dependency.
    """
    try:
        root = Path(root).resolve(strict=True)
        path = (root / PLAN_PATH).resolve(strict=True)
        if not path.is_relative_to(root) or not path.is_file():
            return _unavailable()
        with path.open('rb') as handle:
            raw = handle.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            return _unavailable()
        text = raw.decode('utf-8-sig')
        if any(ord(c) < 32 and c not in '\t\n\r' for c in text):
            return _unavailable()
        title, weeks, sections = _parse(text)
        if today is None:
            today = datetime.now(timezone(timedelta(hours=8))).date()
        if isinstance(today, datetime):
            today = today.date()
        if not isinstance(today, date):
            return _unavailable()
        calendar_id = None
        for week in weeks:
            first, last = date.fromisoformat(week['start_date']), date.fromisoformat(week['end_date'])
            week['calendar_state'] = 'past' if today > last else 'upcoming' if today < first else 'current'
            if week['calendar_state'] == 'current':
                calendar_id = week['id']
        active_id, current, components, notice, updated = _status_fields(status, weeks, calendar_id)
        workstreams = _workstreams(sections, weeks)
        return dict(available=True, title=title, source_sha256=hashlib.sha256(raw).hexdigest(),
                    source_path=PLAN_PATH, start_date=weeks[0]['start_date'], end_date=weeks[-1]['end_date'],
                    as_of_date=today.isoformat(), current_week_id=active_id, calendar_week_id=calendar_id,
                    updated_date=updated, weeks=weeks, sections=sections, current=current,
                    components=components, workstreams=workstreams, policy_notice=notice)
    except (OSError, RuntimeError, UnicodeError, ValueError, TypeError, OverflowError):
        return _unavailable()
