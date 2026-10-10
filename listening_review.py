"""Local, explicit human listening review; never infer a reference or rating.

This public module uses only the standard library. Personal pilot metadata,
recordings, feedback and its backups stay in the project's ignored data/results.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path


PENDING_IDS = ('q10', 'q13', 'q16', 'q17', 'q19', 'q20')
TTS_IDS = ('bataa-raw', 'bataa-spoken', 'yesui-spoken')
TTS_DIRECTORY = 'results/tts-pronunciation-20261009'
_LOCK = threading.RLock()


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _json(data):
    return (json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def _read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def _valid_reference(row):
    # Same contract as run_stt_pilot.is_scoring_reference, without a private import.
    text = row.get('reference', '').strip()
    return (row.get('evaluation_status') == 'eligible_speaker_confirmed'
            and bool(text) and text.casefold() not in {'q', 'quit', 'exit', 'skip'})


def _csv(data):
    reader = csv.DictReader(io.StringIO(data.decode('utf-8-sig'), newline=''))
    fields, rows = reader.fieldnames, list(reader)
    if not fields or any(None in row or any(v is None for v in row.values()) for row in rows):
        raise ValueError('Баталгаажуулалтын CSV-ийн бүтэц буруу байна.')
    return fields, rows


def _csv_bytes(fields, rows):
    buffer = io.StringIO(newline='')
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return ('\ufeff' + buffer.getvalue()).encode('utf-8')


def _atomic_replace(path, data):
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    temporary = Path(temporary)
    try:
        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class ListeningReview:
    """Review only the six retained pending answers and three controlled TTS files."""

    def __init__(self, root):
        self.root = Path(root).resolve()
        self._tts_hashes = {}

    def _path(self, relative, directory=None):
        relative = str(relative).replace('\\', '/')
        if Path(relative).is_absolute() or ':' in relative:
            raise ValueError('Баталгаажуулалтын зам зөвхөн төслийн дотор байна.')
        path = (self.root / relative).resolve()
        boundary = (self.root / directory).resolve() if directory else self.root
        if not boundary.is_relative_to(self.root) or not path.is_relative_to(boundary) or path == boundary:
            raise ValueError('Баталгаажуулалтын файл зөвшөөрсөн хавтсаас гарсан байна.')
        return path

    def _stt(self):
        csv_path = self._path('data/stt-pilot.csv')
        review_path = self._path('data/stt-reference-review-20261009.json')
        if not csv_path.is_file() or not review_path.is_file():
            raise FileNotFoundError('Локал STT pilot-ийн хувийн бүртгэл энэ хуулбарт байхгүй.')
        original = csv_path.read_bytes()
        fields, rows = _csv(original)
        needed = {'id', 'reference', 'audio_path', 'evaluation_status', 'notes'}
        if not needed.issubset(fields) or len({row['id'] for row in rows}) != len(rows):
            raise ValueError('STT pilot-ийн ID эсвэл баганууд буруу байна.')
        # q05 is permanently barred even if a damaged inventory changes its flag.
        excluded = next((row for row in rows if row['id'] == 'q05'), None)
        if excluded and excluded['evaluation_status'] != 'excluded_by_user':
            raise ValueError('q05 нь хэрэглэгчийн шийдвэрээр хасагдсан хэвээр байх ёстой.')
        review_bytes = review_path.read_bytes()
        review = json.loads(review_bytes.decode('utf-8-sig'))
        entries = review.get('entries')
        if (not isinstance(entries, list) or not all(isinstance(e, dict) and isinstance(e.get('id'), str) for e in entries)
                or len({e['id'] for e in entries}) != len(entries)):
            raise ValueError('STT сонсголын бүртгэл буруу байна.')
        return csv_path, original, fields, rows, review_path, review_bytes, review

    def _pending_entry(self, identifier, rows, review):
        if identifier not in PENDING_IDS:
            raise ValueError('Зөвхөн үлдсэн зургаан STT бичлэгийг энд батална; q05 хасагдсан.')
        row = next((row for row in rows if row['id'] == identifier), None)
        entry = next((e for e in review['entries'] if e['id'] == identifier), None)
        if row is None or entry is None:
            raise FileNotFoundError('Сонгосон STT бичлэгийн бүртгэл алга.')
        if _valid_reference(row) or row['evaluation_status'] == 'excluded_by_user':
            raise ValueError('Энэ бичлэг одоо батлах хүлээлгийн жагсаалтад байхгүй.')
        if row['audio_path'].replace('\\', '/') != entry.get('audio_path', '').replace('\\', '/'):
            raise ValueError('STT CSV болон сонсголын бүртгэлийн аудио зөрж байна.')
        return row, entry

    def _stt_audio(self, identifier, rows, review):
        row, entry = self._pending_entry(identifier, rows, review)
        path = self._path(entry['audio_path'], 'audio')
        if path != self._path('audio/' + identifier + '.wav', 'audio'):
            raise ValueError('STT аудионы нэр ID-тай таарахгүй байна.')
        data = path.read_bytes()
        if _sha(data) != entry.get('audio_sha256'):
            raise ValueError('Бичлэг анхны STT нооргоос хойш өөрчлөгдсөн байна: ' + identifier)
        return row, entry, data

    def _tts(self):
        path = self._path('data/tts-listening-review.csv')
        manifest_path = self._path(TTS_DIRECTORY + '/manifest.json')
        if not path.is_file() or not manifest_path.is_file():
            raise FileNotFoundError('Локал TTS сонсголын гурван туршилт энэ хуулбарт байхгүй.')
        original = path.read_bytes()
        fields, rows = _csv(original)
        if not {'file', 'listener', 'overall', 'intelligibility', 'pronunciation_errors', 'review_details'}.issubset(fields):
            raise ValueError('TTS саналын CSV баганууд буруу байна.')
        manifest = _read_json(manifest_path)
        entries = manifest.get('tests', [])
        if not isinstance(entries, list) or not all(isinstance(e, dict) for e in entries):
            raise ValueError('TTS manifest-ийн бүтэц буруу байна.')
        selected = [entry for entry in entries if entry.get('id') in TTS_IDS]
        if len(selected) != 3 or len({entry['id'] for entry in selected}) != 3:
            raise ValueError('TTS manifest нь зөвшөөрсөн гурван ID-тай таарахгүй байна.')
        for entry in selected:
            expected = TTS_DIRECTORY + '/' + entry['id'] + '.mp3'
            if entry.get('file', '').replace('\\', '/') != expected:
                raise ValueError('TTS manifest-ийн аудио зөвшөөрсөн файл биш байна.')
            if len([row for row in rows if row['file'].replace('\\', '/') == expected]) != 1:
                raise ValueError('TTS CSV-д тухайн файлын ганц мөр байх ёстой.')
        return path, original, fields, rows, selected

    def _tts_audio(self, identifier, entries):
        if identifier not in TTS_IDS:
            raise ValueError('Зөвхөн хяналттай гурван TTS файлыг үнэлнэ.')
        entry = next(e for e in entries if e['id'] == identifier)
        path = self._path(entry['file'], TTS_DIRECTORY)
        data = path.read_bytes()
        digest = _sha(data)
        # The historical manifest has no SHA. Pin the bytes when first shown or
        # played in this local reviewer and reject replacements before saving.
        expected = self._tts_hashes.setdefault(identifier, digest)
        manifest_hash = entry.get('audio_sha256')
        if digest != expected or (manifest_hash and digest != manifest_hash):
            raise ValueError('Сонсохоор нээсэн TTS аудио өөрчлөгдсөн байна.')
        return entry, data

    @staticmethod
    def _tts_reviewed(row):
        try:
            return bool(row['listener'].strip()) and 1 <= int(row['overall']) <= 5 and 1 <= int(row['intelligibility']) <= 5
        except (ValueError, TypeError):
            return False

    def _metrics(self, inventory_hash):
        latest = self._path('results/current-human-reference-comparisons/latest.json')
        if not latest.is_file():
            return None
        record = _read_json(latest)
        if record.get('reference_inventory_sha256') != inventory_hash:
            return None
        choice_path = self._path('data/stt-model-choice.json')
        if not choice_path.is_file():
            return None
        choice = _read_json(choice_path)
        selected = next((r for r in record.get('runs', []) if r.get('run') == Path(choice.get('development_run', '')).name), None)
        return ({'scored_ids': selected.get('scored_ids', []), 'metrics': selected.get('metrics'),
                 'created_at': record.get('created_at'), 'inference_repeated': False,
                 'scope': 'Нэг хэлэгчийн хөгжүүлэлтийн бичлэг; системийн нийт нарийвчлал биш.'}
                if selected else None)

    def status(self):
        with _LOCK:
            result = dict(available=False, stt_available=False, tts_available=False,
                          pending_stt=[], tts=[], eligible_stt_count=0, excluded_stt_ids=[],
                          pending_stt_count=0, pending_tts_count=0, reviewed_tts_count=0,
                          current_reference_metrics=None, automatic_confirmation=False,
                          automatic_ratings=False, training_performed=False,
                          notes=['Эдгээр нь хүний сонсголын бүртгэл. Ноорог текст нь сургуулийн баримт биш.',
                                 'TTS 1–5 оноо нь тухайн хүний санал; MOS эсвэл эцсийн үйлчилгээний баталгаа биш.'])
            try:
                _, original, _, rows, _, _, review = self._stt()
            except FileNotFoundError:
                pass
            else:
                result['stt_available'] = True
                result['eligible_stt_count'] = sum(_valid_reference(row) for row in rows)
                result['excluded_stt_ids'] = [r['id'] for r in rows if r['evaluation_status'] == 'excluded_by_user']
                for identifier in PENDING_IDS:
                    row = next((r for r in rows if r['id'] == identifier), None)
                    if row is None or _valid_reference(row) or row['evaluation_status'] == 'excluded_by_user':
                        continue
                    _, entry, _ = self._stt_audio(identifier, rows, review)
                    note = 'Асуултад өөрийн үгээр хариулсан бичлэг. Хэлсэн бүх үгийг сонсож бичнэ; асуултыг reference болгож болохгүй.'
                    if identifier == 'q16':
                        note += ' q16-д утасны дугаар хэлсэн: өмнөх дутуу текстийг давтаж батлахгүй, дугаарыг бүтнээр оруулна.'
                    result['pending_stt'].append(dict(id=identifier,
                        question=entry.get('displayed_question', row.get('prompt', '')),
                        reference_draft=entry.get('draft_model_text', ''),
                        audio_url='/api/review/stt-audio/' + identifier, note=note))
                result['pending_stt_count'] = len(result['pending_stt'])
                result['current_reference_metrics'] = self._metrics(_sha(original))
            try:
                _, _, _, rows, entries = self._tts()
            except FileNotFoundError:
                pass
            else:
                result['tts_available'] = True
                for identifier in TTS_IDS:
                    entry, _ = self._tts_audio(identifier, entries)
                    row = next(r for r in rows if r['file'].replace('\\', '/') == entry['file'].replace('\\', '/'))
                    reviewed = self._tts_reviewed(row)
                    result['tts'].append(dict(id=identifier, filebasename=identifier + '.mp3',
                        audio_url='/api/review/tts-audio/' + identifier, voice=entry.get('voice', ''),
                        text=entry.get('text', ''), review_status='speaker_rated' if reviewed else 'listening_pending',
                        listener=row.get('listener', ''), overall=int(row['overall']) if reviewed else None,
                        intelligibility=int(row['intelligibility']) if reviewed else None,
                        pronunciation_errors=row.get('pronunciation_errors', '')))
                result['reviewed_tts_count'] = sum(t['review_status'] == 'speaker_rated' for t in result['tts'])
                result['pending_tts_count'] = 3 - result['reviewed_tts_count']
            result['available'] = result['stt_available'] or result['tts_available']
            return result

    def audio(self, kind, identifier):
        with _LOCK:
            if kind == 'stt':
                _, _, _, rows, _, _, review = self._stt()
                _, _, data = self._stt_audio(identifier, rows, review)
                return data, 'audio/wav'
            if kind == 'tts':
                _, _, _, _, entries = self._tts()
                _, data = self._tts_audio(identifier, entries)
                return data, 'audio/mpeg'
            raise ValueError('Сонсголын аудионы төрөл stt эсвэл tts байна.')

    def _commit(self, changes, event):
        """Back up all metadata before atomic replacements; roll back on failure."""
        directory = self._path('data/listening-review-history')
        operation = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ-') + uuid.uuid4().hex
        history = directory / operation
        records = []
        for path, before, after in changes:
            if path.read_bytes() != before:
                raise RuntimeError('Бүртгэл өөр цонхонд өөрчлөгдсөн байна; дахин ачаалаад батална уу.')
        try:
            directory.mkdir(parents=True, exist_ok=True)
            history.mkdir()
            for index, (path, before, after) in enumerate(changes):
                backup = history / (str(index) + '-' + path.name + '.before')
                backup.write_bytes(before)
                records.append(dict(path=path.relative_to(self.root).as_posix(), backup=backup.name,
                                    before_sha256=_sha(before), after_sha256=_sha(after)))
        except OSError as error:
            raise RuntimeError('Баталгаажуулалтын нөөц үүсгэж чадсангүй; эх бүртгэлийг өөрчлөөгүй.') from error
        journal = dict(operation_id=operation, created_at=datetime.now(timezone.utc).isoformat(),
                       state='prepared', files=records, original_audio_modified=False,
                       inference_repeated=False, model_draft_auto_confirmed=False, **event)
        journal_path = history / 'journal.json'
        try:
            journal_path.write_bytes(_json(journal))
        except OSError as error:
            raise RuntimeError('Баталгаажуулалтын журнал үүсгэж чадсангүй; эх бүртгэлийг өөрчлөөгүй.') from error
        replaced = []
        try:
            for path, before, after in changes:
                if path.read_bytes() != before:
                    raise RuntimeError('Бүртгэл зэрэг өөрчлөгдсөн тул хадгалалтыг зогсоолоо.')
                _atomic_replace(path, after)
                replaced.append((path, before, after))
            journal['state'] = 'committed'
            _atomic_replace(journal_path, _json(journal))
        except Exception as error:
            rollback_errors = []
            for path, before, after in reversed(replaced):
                try:
                    if path.read_bytes() != after:
                        raise RuntimeError('external modification after replacement')
                    _atomic_replace(path, before)
                except Exception:
                    rollback_errors.append(path.name)
            journal.update(state='rollback_failed' if rollback_errors else 'rolled_back', rollback_errors=rollback_errors)
            try:
                journal_path.write_bytes(_json(journal))
            except OSError:
                pass
            raise RuntimeError('Баталгаажуулалтыг бүрэн хадгалж чадсангүй; нөөц ба журнал хадгалагдсан. '
                               + ('Нөөцөөс сэргээх шаардлагатай.' if rollback_errors else 'Өмнөх төлөвийг сэргээсэн.')) from error
        return journal

    def confirm_stt(self, identifier, text, confirmed):
        if confirmed is not True:
            raise ValueError('Дууг сонсож бүх үг таарч байгааг илэрхий батлах тэмдэглэгээ хэрэгтэй.')
        if not isinstance(text, str) or not text.strip() or len(text) > 6000 or text.strip().casefold() in {'q', 'quit', 'exit', 'skip', 'зөв', 'yes', 'y'}:
            raise ValueError('Хэлсэн бүтэн текстээ бичнэ; удирдлагын үг эсвэл хоосон текст батлахгүй.')
        text = text.strip()
        with _LOCK:
            path, before, fields, rows, review_path, review_before, review = self._stt()
            row, entry, data = self._stt_audio(identifier, rows, review)
            if identifier == 'q16':
                words = lambda value: ' '.join(''.join(c if c.isalnum() else ' ' for c in value.casefold()).split())
                partial = entry.get('previous_partial_reference')
                if partial and words(text) == words(partial):
                    raise ValueError('q16-ийн өмнөх текстэд хэлсэн утасны дугаар дутуу байсан. Дууг дахин сонсоод бүтнээр бичнэ үү.')
            now = datetime.now(timezone.utc).isoformat()
            row.update(reference=text, evaluation_status='eligible_speaker_confirmed')
            row['notes'] += ' Speaker explicitly confirmed full spoken text in local listening web review at ' + now + '; model draft was not automatically accepted.'
            entry.update(confirmed_reference=text, status='speaker_confirmed_after_listening',
                         confirmed_at=now, confirmation_source='speaker_explicit_web_confirmation')
            changes = [(path, before, _csv_bytes(fields, rows)), (review_path, review_before, _json(review))]
            choice_path = self._path('data/stt-model-choice.json')
            if choice_path.is_file():
                choice_before = choice_path.read_bytes()
                choice = json.loads(choice_before.decode('utf-8-sig'))
                choice['remaining_reference_reviews'] = [r['id'] for r in rows if r['evaluation_status'] != 'excluded_by_user' and not _valid_reference(r)]
                if isinstance(choice.get('current_reference_evaluation'), dict):
                    choice['current_reference_evaluation']['stale_after_reference_review'] = True
                changes.append((choice_path, choice_before, _json(choice)))
            journal = self._commit(changes, dict(kind='stt', id=identifier, audio_sha256=_sha(data),
                confirmation_source='speaker_explicit_web_confirmation', human_confirmed=True,
                submitted_reference=text, speaker_id=row.get('speaker_id', '')))
            return dict(saved=True, id=identifier, operation_id=journal['operation_id'],
                        status='speaker_confirmed_after_listening', rescore_pending=True,
                        original_audio_modified=False, inference_repeated=False,
                        pending_stt_count=sum(r['id'] in PENDING_IDS and not _valid_reference(r)
                                              and r['evaluation_status'] != 'excluded_by_user' for r in rows))

    def save_tts(self, identifier, listener, overall, intelligibility, pronunciation_errors, confirmed):
        if confirmed is not True:
            raise ValueError('Дууг өөрөө сонсож өгсөн үнэлгээ гэдгийг илэрхий батална уу.')
        if not isinstance(listener, str) or not listener.strip() or len(listener) > 80:
            raise ValueError('Сонсож үнэлсэн хүний нэр эсвэл кодыг бичнэ үү.')
        if any(type(score) is not int or not 1 <= score <= 5 for score in (overall, intelligibility)):
            raise ValueError('Ерөнхий үнэлгээ ба ойлгомжтой байдлын оноо тус бүр 1–5 бүхэл тоо байна.')
        if not isinstance(pronunciation_errors, str) or len(pronunciation_errors) > 2000:
            raise ValueError('Дуудлагын тайлбар 2000 тэмдэгтээс ихгүй байна.')
        with _LOCK:
            path, before, fields, rows, entries = self._tts()
            entry, data = self._tts_audio(identifier, entries)
            row = next(r for r in rows if r['file'].replace('\\', '/') == entry['file'].replace('\\', '/'))
            row.update(listener=listener.strip(), overall=str(overall), intelligibility=str(intelligibility),
                       pronunciation_errors=pronunciation_errors.strip())
            now = datetime.now(timezone.utc).isoformat()
            row['review_details'] += ' Explicit local web listening rating at ' + now + '; individual subjective 1–5 scores, not MOS, final voice selection or production acceptance.'
            journal = self._commit([(path, before, _csv_bytes(fields, rows))], dict(kind='tts', id=identifier,
                audio_sha256=_sha(data), confirmation_source='listener_explicit_web_rating',
                human_confirmed=True, listener=listener.strip(), overall=overall,
                intelligibility=intelligibility, pronunciation_errors=pronunciation_errors.strip()))
            return dict(saved=True, id=identifier, operation_id=journal['operation_id'],
                        review_status='speaker_rated', individual_rating=True, mos_computed=False,
                        final_voice_selected=False, production_accepted=False, original_audio_modified=False)

    def rescore_existing(self):
        """Optional private helper, only after the caller's successful human save.

        It evaluates retained output JSONs; no model is loaded or transcribed.
        Saving a reference remains successful if this optional derived step fails.
        """
        with _LOCK:
            helpers = ('run_stt_mn_pilot.py', 'rescore_stt_runs.py', 'run_stt_pilot.py', 'score.py', 'stt_mn.py')
            if not all((self.root / name).is_file() for name in helpers):
                return dict(status='not_available', inference_repeated=False,
                            message='Хуучин raw гаралтыг оноох локал скрипт энэ хуулбарт байхгүй; баталсан текст хадгалагдсан.')
            choice_path = self._path('data/stt-model-choice.json')
            if not choice_path.is_file():
                return dict(status='not_available', inference_repeated=False, message='Локал загварын сонголтын бүртгэл алга.')
            try:
                choice = _read_json(choice_path)
                out_dir = self._path(choice['development_run'], 'results')
                if not (out_dir / 'protocol.json').is_file():
                    raise FileNotFoundError('Хадгалсан туршилтын protocol алга.')
                python = self.root / '.venv/Scripts/python.exe'
                if not python.is_file():
                    python = Path(sys.executable)
                program = ('import json; from pathlib import Path; '
                           'from run_stt_mn_pilot import evaluate; from rescore_stt_runs import rescore_all; '
                           'root=Path.cwd(); choice=json.loads((root/"data/stt-model-choice.json").read_text(encoding="utf-8-sig")); '
                           'evaluate(root, root/choice["development_run"]); rescore_all(root)')
                subprocess.run([str(python), '-X', 'utf8', '-c', program], cwd=self.root,
                               capture_output=True, check=True, timeout=60,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                result = _read_json(self._path('results/current-human-reference-comparisons/latest.json'))
                current_hash = _sha(self._path('data/stt-pilot.csv').read_bytes())
                if result.get('reference_inventory_sha256') != current_hash:
                    raise RuntimeError('Оноо тооцоход хэрэглэсэн текстийн хувилбар зөрсөн байна.')
                return dict(status='completed', inference_repeated=False,
                    scored_ids=result.get('human_reference_ids', []),
                    pending_reference_ids=result.get('pending_reference_ids', []),
                    metrics=self._metrics(current_hash),
                    message='Хадгалсан модель гаралтыг шинэ баталсан текстээр дахин оноолсон; аудиог дахин таниулаагүй.')
            except Exception:
                return dict(status='failed', inference_repeated=False,
                    message='Текстийн баталгаа хадгалагдсан. Хуучин raw гаралтыг дахин оноох алхам бүтэлгүйтсэн; шинэ оноо гэж үзэхгүй.')
