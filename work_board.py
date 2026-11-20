"""Work board for /work: what the teacher said and whether it was done, this week's work, the
check-question sets, the system as it is built, and where figures and files live.

`CORE/workboard.json` holds only what has no other home: feedback items, the week's short status,
audit findings and open decisions. Everything else is read from its real source on every request
(weekly plan, config switches, question-set files, figure files), so the page cannot drift from
them. The page writes to the board file and to question sets that are not locked; nothing else.

A status of `confirmed` means the person said so on the page. The assistant edits the file up to
`done` only (rule in CLAUDE.md); `check()` reports a `confirmed` item that has no user log entry.
"""
from __future__ import annotations

import csv
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import threading

from project_plan import public_plan

BOARD = 'CORE/workboard.json'
BACKUPS = 'runtime/workboard-backups'
MAX_FILE = 1_000_000
STATUSES = ('open', 'doing', 'done', 'confirmed', 'later')
KINDS = ('teacher', 'user', 'audit', 'decision')
ABOUT = ('ppt', 'thesis', 'system', 'plan')
ID_PREFIX = {'teacher': 'T', 'user': 'U', 'audit': 'A', 'decision': 'D'}
USER = 'user'
ULAANBAATAR = timezone(timedelta(hours=8))
STALE_DAYS = 7
# The newest file of the first pattern that matches is the set; a locked copy wins over its draft.
SETS = (
    ('system', 'Системийн шалгах асуулт', ('data/eval/system-questions-locked-*.json',
                                           'data/eval/system-questions-draft-*.json')),
    ('reception', 'Ресепшний асуулт', ('data/reception/questions-locked-*.json',)),
    ('w04', 'W04 · сайтын асуулт', ('data/rag-locked-questions-20261102.json',)),
    ('w04b', 'W04-b · баталгаажуулах асуулт', ('data/rag-locked-questions-20261104b.json',)),
)
KIND_MN = {'answerable': 'Хариутай', 'unanswerable': 'Хариугүй', 'compound': 'Хоёр асуулттай',
           'reception': 'Ресепшн', 'table': 'Хүснэгтээс', 'document': 'Баримтаас',
           'out_of_scope': 'Хүрээнээс гадуур'}
ABSTAIN_MN = 'Хариулахгүй; хэнд, хаана хандахыг заана'
STATUS_MN = {'open': 'хийгээгүй', 'doing': 'хийж байна', 'done': 'хийсэн', 'confirmed': 'баталсан', 'later': 'хойшилсон'}
_CONTROL = re.compile(r'[\x00-\x08\x0b-\x1f\x7f]')
_ISO_DATE = re.compile(r'\d{4}-\d{2}-\d{2}')
# The board file is in the public repository: what the page stores must not carry a phone or an address.
_CONTACT = re.compile(r'(?<!\d)\d{8}(?!\d)|[\w.+-]+@[\w-]+\.[\w.-]+')
_LOCK = threading.Lock()


class Conflict(ValueError):
    """The file changed after the page read it; the page must reload before writing."""


def _today(today=None):
    if today is None:
        return datetime.now(ULAANBAATAR).date()
    return today.date() if isinstance(today, datetime) else today


def _read(path):
    if path.stat().st_size > MAX_FILE:
        raise ValueError('File is too large for the work board.')
    raw = path.read_bytes()
    return raw, json.loads(raw.decode('utf-8-sig'))


def _write(root, path, data):
    """Replace the file in one step; the previous version stays in runtime/ (never in git)."""
    text = json.dumps(data, ensure_ascii=False, indent=1) + '\n'
    if path.is_file():
        backups = Path(root) / BACKUPS
        backups.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        (backups / f'{path.stem}.{stamp}.json').write_bytes(path.read_bytes())
        for old in sorted(backups.glob(f'{path.stem}.*.json'))[:-40]:
            old.unlink()
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(text, encoding='utf-8', newline='\n')
    os.replace(temporary, path)
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _clean(value, limit, name, required=True):
    if not isinstance(value, str):
        raise ValueError(f'{name}: текст байх ёстой.')
    value = ' '.join(value.replace('\r', ' ').replace('\n', ' ').split())
    if _CONTROL.search(value) or len(value) > limit:
        raise ValueError(f'{name}: {limit} тэмдэгтээс богино, энгийн текст байх ёстой.')
    if required and not value:
        raise ValueError(f'{name}: хоосон байж болохгүй.')
    return value


def _iso_date(value):
    """`YYYY-MM-DD` only: `date.fromisoformat` alone also takes `20261124` and week dates."""
    if not isinstance(value, str) or not _ISO_DATE.fullmatch(value):
        raise ValueError('Огноо YYYY-MM-DD хэлбэртэй байх ёстой.')
    return date.fromisoformat(value)


def _public_text(value, limit, name, required=True):
    value = _clean(value, limit, name, required)
    if _CONTACT.search(value):
        raise ValueError(f'{name}: утасны дугаар, имэйл хаяг бүү бичээрэй — энэ бүртгэл GitHub-д нийтэд хадгалагдана.')
    return value


def load(root):
    _, data = _read(Path(root) / BOARD)
    items = data.get('items')
    if data.get('schema_version') != 1 or not isinstance(items, list) or not isinstance(data.get('week'), dict):
        raise ValueError('Unsupported work board.')
    seen = set()
    for item in items:
        if (not isinstance(item, dict) or item.get('status') not in STATUSES or item.get('kind') not in KINDS
                or not isinstance(item.get('id'), str) or item['id'] in seen):
            raise ValueError('Invalid work board item.')
        seen.add(item['id'])
    return data


def check(root, today=None):
    """Problems a person or the assistant should fix in the board file; empty when clean."""
    data, problems = load(root), []
    for item in data['items']:
        if item['status'] == 'confirmed' and not any(entry.get('by') == USER for entry in item.get('log', [])):
            problems.append(f"{item['id']}: «баталсан» боловч хэрэглэгчийн бүртгэл алга.")
        if item['status'] == 'done' and not item.get('evidence'):
            problems.append(f"{item['id']}: хийсэн гэсэн боловч нотолгооны файл заагаагүй.")
    stale = _stale(data, public_plan(root, today=_today(today)), _today(today))
    if stale:
        problems.append(stale)
    return problems


def _stale(data, plan, today):
    week = data['week']
    try:
        age = (today - _iso_date(week.get('updated', ''))).days
    except ValueError:
        return 'Долоо хоногийн хэсгийн огноо буруу.'
    calendar = plan.get('calendar_week_id') if plan.get('available') else None
    if calendar and week.get('week_id') != calendar:
        return f"Долоо хоногийн хэсэг {week.get('week_id')}-ийнх, өнөөдөр {calendar}."
    if age > STALE_DAYS:
        return f'Долоо хоногийн хэсгийг {age} хоногийн өмнө шинэчилсэн.'
    return ''


def _dates(data, plan, today):
    """Next seminar (the handbook's weekly slot) and the dated milestones still ahead."""
    rows, seminar = [], data.get('seminar') or {}
    try:
        until = _iso_date(seminar['until'])
        day = today + timedelta(days=(int(seminar['weekday']) - today.weekday()) % 7)
        if day <= until:
            week = next((w['id'] for w in plan.get('weeks', [])
                         if w['start_date'] <= day.isoformat() <= w['end_date']), '')
            rows.append(dict(date=day.isoformat(), label=f"Семинар {seminar.get('time', '')}".strip(),
                             days=(day - today).days, week=week))
    except (KeyError, ValueError, TypeError):
        pass
    for row in data.get('milestones', []):
        try:
            day = _iso_date(row['date'])
        except (KeyError, ValueError, TypeError):
            continue
        if day >= today:
            rows.append(dict(date=day.isoformat(), label=str(row.get('label', '')), days=(day - today).days, week=''))
    return sorted(rows, key=lambda row: row['date'])


def _week(plan):
    if not plan.get('available'):
        return None
    for week in plan['weeks']:
        if week.get('calendar_state') == 'current':
            return {key: week.get(key) for key in ('id', 'title', 'start_date', 'end_date', 'work', 'deliverables')}
    return None


def _row(question):
    kind = question.get('kind', '')
    support = question.get('support') or []
    source = question.get('source_url') or (support[0].get('url', '') if support and isinstance(support[0], dict) else '')
    abstain = question.get('expect') == 'abstain' or kind in ('unanswerable', 'out_of_scope')
    return dict(id=question.get('id', ''), kind=kind, kind_mn=KIND_MN.get(kind, kind), split=question.get('split', ''),
                query=question.get('query', ''), required_values=list(question.get('required_values') or []),
                any_of=list(question.get('any_of') or []), abstain=abstain, abstain_mn=ABSTAIN_MN if abstain else '',
                answer_mn=question.get('answer_mn') or question.get('expected') or '',
                note=question.get('note', ''), source=source, user_review=question.get('user_review', ''))


def _set_path(root, patterns):
    for pattern in patterns:
        found = sorted(Path(root).glob(pattern))
        if found:
            return found[-1]
    return None


def _set_problems(questions):
    """What must hold before a set can be scored: unique ids, a question, and a criterion for each."""
    problems, seen = [], set()
    for question in questions:
        if not isinstance(question, dict):
            return ['Асуултын бүтэц буруу.']
        name = question.get('id')
        if not isinstance(name, str) or not name or name in seen:
            problems.append(f'давхардсан эсвэл хоосон дугаар: {name}')
        seen.add(name)
        if not str(question.get('query', '')).strip():
            problems.append(f'{name}: асуулт хоосон')
        row = _row(question)
        if not row['abstain'] and not row['required_values'] and not row['any_of']:
            problems.append(f'{name}: зөв хариултад байх ёстой утга алга')
    return problems


def _results(results, path, questions):
    """Only numbers measured on this file; flagged when a question was edited after the measurement."""
    rows = []
    for row in results:
        if row.get('path') != path:
            continue
        edited = max((str(question.get('user_edited', '')) for question in questions), default='')
        rows.append(dict(row, stale=bool(edited) and edited >= str(row.get('date', ''))))
    return rows


def question_sets(root, results=()):
    root, sets = Path(root), []
    for key, label, patterns in SETS:
        path = _set_path(root, patterns)
        if path is None:
            continue
        try:
            raw, data = _read(path)
            rows = [_row(question) for question in data['questions']]
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
        locked = data.get('status') == 'locked'
        person = locked and data.get('lock_kind') == 'person'
        lock_mn = ('Та түгжсэн — хүн хянасан' if person else 'Агент түгжсэн — хүн хянаагүй' if locked
                   else 'Ноорог — та хянаж түгжинэ')
        shown = path.relative_to(root).as_posix()
        sets.append(dict(key=key, label_mn=label, path=shown, locked=locked,
                         person_locked=person, lock_mn=lock_mn, locked_at=str(data.get('locked_at', ''))[:10],
                         editable=not locked, sha=hashlib.sha256(raw).hexdigest(), total=len(rows),
                         reviewed=sum(bool(row['user_review']) for row in rows),
                         results=_results(results, shown, data['questions']), questions=rows))
    return sets


def questions_sha256(questions):
    """Same canonical form as tools/evaluate_locked_questions.py (kept equal by a test)."""
    text = json.dumps(questions, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(text.encode()).hexdigest()


def _config(root, name):
    try:
        return json.loads((Path(root) / 'config' / name).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return {}


def _count_rows(root, source, name):
    try:
        with (Path(root) / source / name).open(encoding='utf-8-sig', newline='') as handle:
            return max(sum(1 for _ in csv.reader(handle)) - 1, 0)
    except OSError:
        return None


def structure(root, release=None):
    """The answer path as the switches say it is now: step, part, on or off, one plain line, file."""
    selection, tables, referral = (_config(root, name) for name in
                                   ('answer-selection.json', 'reception-tables.json', 'referral.json'))
    planner, domains, morphology, vocabulary, cleanup, topics = (_config(root, name) for name in (
        'question-planner.json', 'knowledge-domains.json', 'retrieval-morphology.json', 'stt-vocabulary.json',
        'stt-audio-cleanup.json', 'knowledge-topics.json'))

    def row(name, on, text, file, note=''):
        """A part with a switch in config/: `text` names what the part does, the pill says whether it is on."""
        return dict(name=name, on=bool(on), switch=True, text=text, file=file, note=note)

    def fixed(name, text, file, note=''):
        """A part of the code path that no setting turns off."""
        return dict(name=name, on=True, switch=False, text=text, file=file, note=note)

    source = tables.get('source', '')
    counts = {name: _count_rows(root, source, name + '.csv') for name in ('rooms', 'classes', 'staff', 'timetable')}
    table_text = ('Өрөө {rooms}, анги бүлэг {classes}, багш ба ажилтан {staff}, хуваарийн мөр {timetable}.'.format(**counts)
                  if all(value is not None for value in counts.values()) else 'Хүснэгт энэ компьютерт алга.')
    offices = referral.get('question_offices') or {}
    office_note = '' if offices.get('reviewed') else 'Сургууль батлаагүй'
    rules = len(offices.get('rules') or [])
    groups = [
        dict(step='1. Асуух', rows=[
            fixed('Бичгээр асуух', 'Вэб хуудсанд асуултаа бичнэ. Ресепшний дэлгэцийн горим: /kiosk.', 'demo/index.html'),
            fixed('Дуугаар асуух', f"Яриаг {vocabulary.get('model', 'gemini-3.5-transcribe')} текст болгоно.",
                  'gemini_stt_runtime.py', 'Нэг хэлэгчийн бичлэгээр л хэмжсэн'),
            row('Сургуулийн нэрийн жагсаалт', vocabulary.get('enabled'),
                f"Яриа танигчид сургуулийн {len(vocabulary.get('terms') or [])} нэрийг өгөх.", 'config/stt-vocabulary.json'),
            row('Дууг цэгцлэх', cleanup.get('enabled'), 'Илгээхээс өмнө эхэн, төгсгөлийн чимээгүйг тайрах.',
                'config/stt-audio-cleanup.json'),
        ]),
        dict(step='2. Ангилах', rows=[
            row('Асуултыг ойлгох', planner.get('enabled'),
                'Хоёр асуулттай өгүүлбэрийг хуваах, ангийн нэр, ажилтны нэрийг таних.', 'question_planner.py'),
            fixed('Дагалдах асуулт',
                  'Өмнөх асуултын албыг санаж, «Хэдэн цагт вэ?», «Имэйл нь?» гэсэн үргэлжлэлд хариулна.',
                  'rag_runtime.py'),
            fixed('Асуултыг ангилах',
                  'Өрөө, анги, багш, хуваарийн асуултыг сургуулийн хүснэгт рүү, бусдыг хайлт руу явуулна.',
                  'question_router.py'),
        ]),
        dict(step='3. Хайх', rows=[
            fixed('Сайтаас хайх', 'BM25 (үгээр) ба E5 (утгаар) хайж, хоёр жагсаалтыг RRF-ээр нэгтгэнэ.',
                  'website_retrieval.py'),
            row('Сургуулийн хүснэгт', tables.get('enabled'), table_text, 'reception_tables.py'),
            row('Мэдлэгийн модны нэмэлт оноо', domains.get('enabled'),
                f"Асуултын хүрээний ({len(domains.get('domains') or {})} хүрээ) эх сурвалжид оноо нэмэх.",
                'config/knowledge-domains.json', 'Үнэлгээний дараа асаах эсэхийг шийднэ'),
            row('Үгийн хэлбэрээр хайх', morphology.get('enabled'), 'Монгол үгийн нөхцөлийг хасаж хайх.',
                'config/retrieval-morphology.json', 'Туршсан, хариултад ашиггүй байсан'),
        ]),
        dict(step='4. Сонгох', rows=[
            fixed('Дүрмээр сонгох', 'Олдсон хэсгүүдээс хариулт болохыг дүрмээр сонгоно.', 'rule_selector.py'),
            row('Хэлний загвараар бичүүлэх', selection.get('local_llm_enabled'),
                'Хариултыг хэлний загвараар бичүүлнэ.' if selection.get('local_llm_enabled')
                else 'Хариултыг загвараар бичүүлэхгүй; эх сурвалжийн үгийг үгчлэн харуулна.',
                'config/answer-selection.json', 'W08-д ижил асуултаар харьцуулна'),
        ]),
        dict(step='5. Шалгаж хариулах', rows=[
            row('Асуусан утгын төрлийг шалгах', selection.get('typed_value_check'),
                'Цаг асуухад цаг, тоо асуухад тоо агуулсан хэсгийг л хариулт болгох.', 'rule_selector.py'),
            row('Хэнд, хаана хандахыг заах', referral.get('enabled') and offices.get('enabled'),
                f'Хариулт олдоогүй бол сэдвээр нь алба, өрөөг заах ({rules} дүрэм).', 'config/referral.json',
                office_note),
            fixed('Ажилтны гар утсыг нуух', 'Сайтад бичсэн ажилтны гар утас хариултад гарахгүй.', 'privacy_filter.py'),
            fixed('Дуугаар унших', 'Хариултыг Edge TTS уншина.', 'tts.py'),
        ]),
        dict(step='Мэдээлэл', rows=[
            fixed('Идэвхтэй хувилбар', (release or {}).get('label') or 'Хувилбарын мэдээлэл уншигдсангүй.',
                  'content_release.py', str((release or {}).get('activated_utc', ''))[:10]),
            fixed('Мэдлэгийн мод',
                  f"{len(domains.get('domains') or {})} хүрээ; модны файлд үндэс, хүрээ, дэд сэдэв нийлээд "
                  f"{len(topics.get('topics') or [])} зангилаа.", 'config/knowledge-topics.json'),
        ]),
    ]
    return groups


def _files(root, data):
    root = Path(root)

    def changed(path):
        try:
            return datetime.fromtimestamp(path.stat().st_mtime, ULAANBAATAR).date().isoformat()
        except OSError:
            return ''

    figures = [dict(row, changed=changed(root / row.get('file', ''))) for row in data.get('figures', [])]
    decks = [path for folder in root.glob('CORE/seminar-*') for path in folder.glob('*.pptx')]
    deck = max(decks, key=lambda path: path.stat().st_mtime) if decks else None
    outputs = [
        ('Багшид үзүүлэх ноорог (PDF)', 'МИНИЙ-ДИПЛОМ/01_Диплом/Диплом_1_багшид_үзүүлэх.pdf', root / 'thesis/main_teacher.pdf'),
        ('Бүтэн ажлын ноорог (PDF)', 'МИНИЙ-ДИПЛОМ/01_Диплом/Диплом_2_бүтэн_ноорог.pdf', root / 'thesis/main.pdf'),
        ('Сүүлийн семинарын PPT', f'МИНИЙ-ДИПЛОМ/02_Семинар/{deck.name}' if deck else '', deck),
        ('Долоо хоногийн төлөвлөгөө', 'CORE/WEEKLY-PLAN-2026-2027.mn.md', root / 'CORE/WEEKLY-PLAN-2026-2027.mn.md'),
        ('Өдөр бүрийн бүртгэл', 'CORE/PROJECT-NOTE.mn.md', root / 'CORE/PROJECT-NOTE.mn.md'),
        ('Энэ самбарын бүртгэл', BOARD, root / BOARD),
    ]
    return dict(figures=figures, howto_mn=data.get('figures_howto_mn', []),
                outputs=[dict(label_mn=label, path=shown, changed=changed(path))
                         for label, shown, path in outputs if path is not None and path.is_file()])


def snapshot(root, today=None, release=None):
    today = _today(today)
    data, plan = load(root), public_plan(root, today=today)
    items = sorted(data['items'], key=lambda item: (item.get('date', ''), item['id']), reverse=True)
    counts = {kind: {status: sum(1 for item in items if item['kind'] == kind and item['status'] == status)
                     for status in STATUSES} for kind in KINDS}
    evaluation = data.get('evaluation') or {}
    return dict(today=today.isoformat(), week=_week(plan), board_week=data['week'], stale_mn=_stale(data, plan, today),
                dates=_dates(data, plan, today), items=items, counts=counts, rules_mn=data.get('rules_mn', []),
                evaluation=dict(problem_mn=evaluation.get('problem_mn', ''), source_mn=evaluation.get('source_mn', '')),
                question_sets=question_sets(root, evaluation.get('results') or ()),
                structure=structure(root, release), files=_files(root, data))


def simple_status(root, today=None):
    """The short panel of the atlas «Төслийн явц» tab, from the same board (one source)."""
    today = _today(today)
    data, plan = load(root), public_plan(root, today=today)
    week = data['week']
    dates = [dict(date=f"{int(row['date'][5:7])}/{row['date'][8:10]}", label=row['label']) for row in _dates(data, plan, today)]
    return dict(now=week.get('headline_mn', ''), parts=week.get('parts', []), done=week.get('done_mn', []),
                problems=week.get('problems_mn', []), next=week.get('next_mn', []), dates=dates,
                months=data.get('months', []))


def brief_lines(root, today=None):
    """Lines for `tools/claude_context.py --brief`: what is open, so a session starts from it."""
    data = load(root)
    lines = [f'⚠ {problem}' for problem in check(root, today)]
    labels = {'open': 'ХИЙГЭЭГҮЙ', 'doing': 'хийж байна', 'done': 'хийсэн, хэрэглэгч шалгаагүй'}
    for kind, title in (('teacher', 'Багш'), ('user', 'Хэрэглэгч'), ('decision', 'Хэрэглэгчийн шийдэх'), ('audit', 'Асуудал')):
        for item in data['items']:
            if item['kind'] == kind and item['status'] in ('open', 'doing'):
                said = [entry for entry in item.get('log', []) if entry.get('by') == USER]
                lines.append(f"{item['id']} · {title} {item.get('date', '')[5:]} · {labels[item['status']]} · "
                             f"{item.get('said_mn', '')[:150]}"
                             + (f" ← хэрэглэгч {said[-1].get('date', '')[5:]}: {said[-1].get('text_mn', '')[:120]}" if said else ''))
    waiting = sum(1 for item in data['items'] if item['status'] == 'done')
    lines.append(f'Хийсэн боловч хэрэглэгч шалгаагүй: {waiting} (самбар: /work#feedback).')
    return lines


def save_item(root, payload, today=None):
    """Create an item (teacher, user or decision) or change one item's status, text or note."""
    today = _today(today).isoformat()
    path = Path(root) / BOARD
    with _LOCK:
        data = load(root)
        if payload.get('new') is True:
            kind = payload.get('kind')
            if kind not in ('teacher', 'user', 'decision'):
                raise ValueError('Төрөл буруу.')
            day = _iso_date(payload.get('date', today)).isoformat()
            about = payload.get('about')
            if about not in ABOUT:
                raise ValueError('Юуны тухай гэдгийг сонгоно уу.')
            stem = f'{ID_PREFIX[kind]}{day[5:7]}{day[8:10]}-'
            used = [int(item['id'][len(stem):]) for item in data['items']
                    if item['id'].startswith(stem) and item['id'][len(stem):].isdigit()]
            item = dict(id=f'{stem}{max(used, default=0) + 1}', kind=kind, date=day, about=about,
                        from_mn=_public_text(payload.get('from_mn', ''), 80, 'Хэн хэлсэн'),
                        source_mn=f'Та {today}-нд самбарт бичсэн',
                        said_mn=_public_text(payload.get('said_mn', ''), 1200, 'Юу гэж хэлсэн'),
                        action_mn='', status='open', evidence=[],
                        log=[dict(date=today, by=USER, text_mn='Самбарт нэмсэн.')])
            data['items'].append(item)
        else:
            item = next((entry for entry in data['items'] if entry['id'] == payload.get('id')), None)
            if item is None:
                raise ValueError('Ийм бүртгэл алга.')
            changed = []
            if 'status' in payload:
                if payload['status'] not in STATUSES:
                    raise ValueError('Төлөв буруу.')
                if payload['status'] != item['status']:
                    item['status'] = payload['status']
                    changed.append('төлөв: ' + STATUS_MN[payload['status']])
            if 'said_mn' in payload:
                item['said_mn'] = _public_text(payload['said_mn'], 1200, 'Юу гэж хэлсэн')
                changed.append('үгийг зассан')
            note = _public_text(payload.get('note', ''), 600, 'Тэмдэглэл', required=False)
            if not changed and not note:
                raise ValueError('Өөрчлөх зүйл алга.')
            item.setdefault('log', []).append(dict(date=today, by=USER, text_mn='; '.join(changed + ([note] if note else []))))
        _write(root, path, data)
        return item


def _editable_set(root, key, base_sha):
    patterns = next((patterns for name, _, patterns in SETS if name == key), None)
    path = _set_path(root, patterns) if patterns else None
    if path is None:
        raise ValueError('Ийм асуултын багц алга.')
    raw, data = _read(path)
    if hashlib.sha256(raw).hexdigest() != base_sha:
        raise Conflict('Багц өөрчлөгдсөн байна. Хуудсаа дахин ачаална уу.')
    if data.get('status') == 'locked':
        raise ValueError('Түгжсэн багцыг өөрчлөхгүй.')
    return path, data


def save_question(root, payload, today=None):
    """Edit one question of an unlocked set: its wording, required values, note and the review mark."""
    today = _today(today).isoformat()
    fields = payload.get('fields')
    if not isinstance(fields, dict) or not fields or set(fields) - {'query', 'required_values', 'note', 'user_review'}:
        raise ValueError('Засах талбар буруу.')
    with _LOCK:
        path, data = _editable_set(root, payload.get('set'), payload.get('base_sha'))
        question = next((entry for entry in data['questions'] if entry.get('id') == payload.get('id')), None)
        if question is None:
            raise ValueError('Ийм асуулт алга.')
        if 'query' in fields:
            query = _clean(fields['query'], 400, 'Асуулт')
            if query != question.get('query'):
                question['query'], question['user_edited'] = query, today
        if 'required_values' in fields:
            values = fields['required_values']
            if not isinstance(values, list) or len(values) > 8:
                raise ValueError('Зөв хариултын утга 8-аас олон байж болохгүй.')
            values = [_clean(value, 160, 'Зөв хариултын утга') for value in values]
            if not values and not _row(question)['abstain'] and not question.get('any_of'):
                raise ValueError('Хариутай асуултад зөв хариултын утга заавал байна.')
            if values != list(question.get('required_values') or []):
                question['required_values'], question['user_edited'] = values, today
        if 'note' in fields:
            question['note'] = _clean(fields['note'], 400, 'Тайлбар', required=False)
        if 'user_review' in fields:
            question['user_review'] = _clean(fields['user_review'], 400, 'Таны тэмдэглэл', required=False)
            question['user_review_date'] = today
        sha = _write(root, path, data)
        return dict(sha=sha, question=_row(question),
                    reviewed=sum(bool(entry.get('user_review')) for entry in data['questions']))


def lock_set(root, payload, today=None):
    """Lock a fully reviewed draft as a new file; the draft stays as the record of the review."""
    today = _today(today)
    name = _clean(payload.get('locked_by', ''), 80, 'Хянасан хүний нэр')
    with _LOCK:
        path, data = _editable_set(root, payload.get('set'), payload.get('base_sha'))
        problems = _set_problems(data['questions'])
        if problems:
            raise ValueError('Түгжихээс өмнө засах зүйл: ' + '; '.join(problems[:6]))
        missing = [entry.get('id', '?') for entry in data['questions'] if not entry.get('user_review')]
        if missing:
            raise ValueError(f'{len(missing)} асуулт хянагдаагүй: ' + ', '.join(missing[:8]))
        target = path.with_name(path.name.replace('-draft-', '-locked-'))
        target = target.with_name(re.sub(r'\d{8}(?=\.json$)', today.strftime('%Y%m%d'), target.name))
        if target == path or target.exists():
            raise Conflict('Түгжсэн файл аль хэдийн байна.')
        locked = dict(data, status='locked', lock_kind='person',
                      locked_by=f'{name} — 127 самбар дээр мөр бүрийг хянасан',
                      locked_at=datetime.now(timezone.utc).isoformat(),
                      locked_from=path.relative_to(Path(root)).as_posix(),
                      questions_sha256=questions_sha256(data['questions']))
        _write(root, target, locked)
        return dict(path=target.relative_to(Path(root)).as_posix(), total=len(data['questions']))
