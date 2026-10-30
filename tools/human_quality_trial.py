"""Local human answer, critical-slot listening, and typed/raw/edited task pilot.

This tool collects explicit human self-reports, never AI-filled human scores.
The fixed local demo forwards explicitly submitted audio to Gemini Live;
prepared TTS files are reused. Retained legacy local-ASR trials stay historical.
Run with --run-dir runtime/<new-private-dir>. No public listener is opened.
"""
from datetime import datetime, timezone
import argparse
import copy
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import random
import re
import secrets
import sys
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
import uuid


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from stt_measurement import measure

LIVE_MODEL = 'gemini-3.5-live-translate-preview'
MAX_AUDIO = 8 * 1024 * 1024


def sha(data):
    return hashlib.sha256(data).hexdigest()


def utc():
    return datetime.now(timezone.utc).isoformat()


class TrialConflict(ValueError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        # A fixed loopback URL must never redirect a recording or request to another host.
        return None


class HumanTrial:
    def __init__(self, run_dir, audio_results, review_file, upstream='http://127.0.0.1:8765', *, resume=False, stt_provider='gemini_live'):
        if stt_provider not in {'gemini_live', 'cafet'}:
            raise ValueError('Unknown fixed study recognizer.')
        self.stt_provider = stt_provider
        self.directory = Path(run_dir).resolve()
        if ROOT.joinpath('runtime').resolve() not in self.directory.parents:
            raise ValueError('Human records must remain in a private runtime subdirectory.')
        if resume:
            if not self.directory.is_dir():
                raise ValueError('Resume requires an existing private study directory.')
        else:
            self.directory.mkdir(parents=True, exist_ok=False)
        self.audio_manifest = Path(audio_results).resolve()
        raw = self.audio_manifest.read_bytes()
        self.audio_manifest_sha = sha(raw)
        bundle = json.loads(raw)
        self.samples = {}
        for case in bundle['cases']:
            for audio in case['audio']:
                if audio.get('success') is not True:
                    continue
                path = (self.audio_manifest.parent / audio['path']).resolve()
                if not path.is_relative_to(self.audio_manifest.parent) or path.suffix != '.mp3':
                    raise ValueError('Unsafe fixed listening path.')
                identifier = sha((case['id'] + ':' + audio['voice'] + ':' + audio['variant']).encode())[:24]
                self.samples[identifier] = dict(path=path, sha256=audio['sha256'],
                    keys=list(case['critical_values']), reference=case['critical_values'],
                    written=case['written'], condition=audio['variant'], voice=audio['voice'],
                    source_refs=copy.deepcopy(case.get('source_refs', [])),
                    critical_reference_sha256=case.get('critical_reference_sha256'))
                self.audio(identifier)
        if not self.samples:
            raise ValueError('Require frozen, successful listening audio.')
        self.text_scope = bundle.get('text_scope_mn') or (
            'Эдгээр өгүүлбэр нь зохиомол туршилтын өгөгдөл. Сургуулийн бодит мэдээлэл биш.'
            if bundle.get('constructed', True) else
            'Эдгээр нь багцад заасан хадгалсан эхийн өгүүлбэр. Өнөөдрийн хүчинтэй мэдээлэл гэж таамаглахгүй.')
        if upstream != 'http://127.0.0.1:8765':
            raise ValueError('Only the fixed loopback demo may process recordings.')
        self.upstream = upstream
        self._opener = build_opener(ProxyHandler({}), NoRedirect())
        self.review_file = Path(review_file).resolve()
        self.review_sha = None
        self.rows = None
        self.sessions = {}
        self.lock = threading.RLock()
        self.token = secrets.token_hex(32)
        self._restoring = resume
        if resume:
            self._restore()
            self._restoring = False
        else:
            self._write_new('manifest.json', dict(created_utc=utc(), audio_manifest_sha256=self.audio_manifest_sha,
                listening_samples=len(self.samples), expected_answer_file=str(self.review_file.relative_to(ROOT)),
                scores_fabricated=False, human_review_source='explicit_browser_self_report',
                human_scores_observer_verified=False, public_server=False,
                recognition_provider=self.stt_provider,
                audio_reference_not_inferred_from_stt=True,
                human_answer_or_listening_results_at_preparation=0))

    def _saved(self, name):
        path = (self.directory / name).resolve(strict=True)
        if not path.is_relative_to(self.directory) or not path.is_file():
            raise ValueError('Unsafe saved study path.')
        with path.open('rb') as stream:
            raw = stream.read(MAX_AUDIO + 1)
        if len(raw) > MAX_AUDIO:
            raise ValueError('Saved study item exceeds its bound.')
        return raw

    @staticmethod
    def _new_task(task_id, text, context):
        return dict(id=task_id, intended_request=text, recording=None, reference=None,
                    reference_draft=None, transcription_attempted=False, context=context,
                    transcript=None, results={}, audio_ids=set(), lock=threading.RLock(),
                    observations=set(), synthesized=set(), last_error=None, measurement=None)

    def _restore(self):
        """Validate the journal before appending. Replay never calls models or creates human events."""
        def require(condition):
            if not condition:
                raise ValueError('Saved study evidence is inconsistent; original files were not changed.')
        manifest = json.loads(self._saved('manifest.json'))
        require(manifest['audio_manifest_sha256'] == self.audio_manifest_sha
                and manifest['listening_samples'] == len(self.samples)
                and manifest['expected_answer_file'] == str(self.review_file.relative_to(ROOT)))
        # A task-only session can precede the first answer-page load. Do not
        # create a new review snapshot merely by restoring that session.
        rows = ({row['review_id'] for row in self._answers()}
                if (self.directory / 'frozen-answer-review.json').is_file() else set())
        paths = sorted(p for p in self.directory.iterdir()
                       if re.fullmatch(r'[0-9a-f]{32}-[0-9]{4}-[a-z-]+\.json', p.name))
        require(len(paths) <= 10000)
        total = 0
        for path in paths:
            raw = self._saved(path.name)
            total += len(raw)
            require(total <= 64 * 1024 * 1024)
            event = json.loads(raw)
            sid, number, kind = path.name[:-5].split('-', 2)
            require(event['session_id'] == sid and event['kind'] == kind
                    and re.fullmatch(r'[0-9a-f]{32}', event['id']) is not None
                    and event['audio_manifest_sha256'] == self.audio_manifest_sha
                    and event['answer_bundle_sha256'] in (None, self.review_sha))
            if kind == 'consent':
                require(sid not in self.sessions and int(number) == 1)
                consent = {k: event[k] for k in ('pseudonym', 'consent', 'audio_storage_consent', 'implementation_participation')}
                require(re.fullmatch(r'P[0-9]{3,6}', consent['pseudonym']) is not None
                        and consent['consent'] is True
                        and type(consent['audio_storage_consent']) is bool
                        and type(consent['implementation_participation']) is bool)
                order = list(self.samples)
                random.Random(sid).shuffle(order)
                self.sessions[sid] = dict(id=sid, events=0, last_sha=None, consent=consent,
                    listening_order=order, listening={}, reviews={}, tasks={})
            require(sid in self.sessions)
            session = self.sessions[sid]
            require(int(number) == session['events'] + 1
                    and event['previous_event_sha256'] == session['last_sha']
                    and event['speaker_id'] == event['speaker_group_id'] == session['consent']['pseudonym']
                    and event['human_observer_verified'] is False)
            if kind == 'listening':
                sample = self.samples.get(event['sample_id'])
                require(sample is not None and event['sample_id'] not in session['listening']
                        and event['audio_sha256'] == sample['sha256']
                        and set(event['heard_values']) == set(sample['keys'])
                        and event['listened'] is True and event['playback_ended'] is True
                        and all(type(event[k]) is int and 1 <= event[k] <= 5 for k in ('intelligibility', 'naturalness')))
                session['listening'][event['sample_id']] = event['id']
            elif kind == 'answer-review':
                require(event['review_id'] in rows and event['review_id'] not in session['reviews'])
                session['reviews'][event['review_id']] = event['id']
            elif kind == 'task-start':
                task_id = event['task_id']
                require(re.fullmatch(r'[0-9a-f]{32}', task_id) is not None and task_id not in session['tasks'])
                session['tasks'][task_id] = self._new_task(task_id, event['intended_request'], event['recording_context'])
            elif kind.startswith('task-'):
                require(event['task_id'] in session['tasks'])
                task = session['tasks'][event['task_id']]
                if kind == 'task-recording':
                    require(task['recording'] is None and session['consent']['audio_storage_consent'])
                    for filename, digest in (('audio_file', 'audio_sha256'), ('original_audio_file', 'original_audio_sha256'),
                                             ('provenance_file', 'provenance_sha256')):
                        require(sha(self._saved(event[filename])) == event[digest])
                    task['recording'] = copy.deepcopy(event)
                    task['last_error'] = None
                elif kind in {'task-reference', 'task-reference-pending'}:
                    require(task['recording'] is not None and task['reference'] is None
                            and not task['transcription_attempted']
                            and event['audio_sha256'] == task['recording']['audio_sha256'])
                    if kind == 'task-reference':
                        require(event['human_utterance_reference_confirmed'] is True
                                and event['reference_confirmed_before_asr'] is True
                                and event['listened'] is True and event['playback_ended'] is True
                                and event['uncertainties'] == [])
                        task['reference'] = {k: copy.deepcopy(event[k]) for k in (
                            'text', 'audio_sha256', 'confirmed_utc', 'uncertainties', 'reference_origin', 'observer_verified')}
                    else:
                        task['reference_draft'] = dict(text=event['reference_draft'], uncertainties=event['uncertainties'])
                elif kind == 'task-stt-attempt':
                    require(task['reference'] is not None and not task['transcription_attempted']
                            and event['uploaded_audio_sha256'] == task['recording']['audio_sha256'])
                    task['transcription_attempted'] = True
                elif kind == 'task-stt':
                    require(task['transcription_attempted'] and task['transcript'] is None
                            and event['uploaded_audio_sha256'] == task['recording']['audio_sha256']
                            and event['asr_utterance_reference'] == task['reference']['text'])
                    task['transcript'] = copy.deepcopy(event['actual_response'])
                    task['measurement'] = copy.deepcopy(event.get('measurement'))
                    task['audio_ids'].add(task['transcript']['id'])
                elif kind == 'task-route':
                    condition = event['condition']
                    require(condition in {'typed', 'raw', 'explicit-edited'} and condition not in task['results']
                            and (condition == 'typed' or task['transcript'] is not None))
                    task['results'][condition] = dict(query=event['actual_sent_text'], result=copy.deepcopy(event['actual_response']))
                elif kind == 'task-tts':
                    require(event['condition'] in task['results'])
                    task['audio_ids'].add(event['actual_response']['id'])
                    task['synthesized'].add(event['condition'])
                elif kind == 'task-observation':
                    require(event['condition'] in task['results'] and event['condition'] not in task['observations'])
                    task['observations'].add(event['condition'])
                elif kind == 'task-error':
                    if event.get('operation') == 'prepare_audio':
                        require(sha(self._saved(event['audio_file'])) == event['input_sha256'])
                    task['last_error'] = dict(operation=event['operation'], message=event['error'])
                else:
                    raise ValueError('Unsupported saved study event; preserve the original journal.')
            elif kind != 'consent':
                raise ValueError('Unsupported saved study event; preserve the original journal.')
            session['events'], session['last_sha'] = int(number), sha(raw)

    def _write_new(self, name, value):
        with (self.directory / name).open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write('\n')

    def _answers(self):
        with self.lock:
            return self._answers_locked()

    def _answers_locked(self):
        if self.rows is not None:
            if sha(self.review_file.read_bytes()) != self.review_sha:
                raise TrialConflict('Frozen answer review file changed; restart as a new study.')
            return self.rows
        if not self.review_file.is_file():
            return []
        raw = self.review_file.read_bytes()
        value = json.loads(raw)
        rows = value['rows']
        forbidden = {'condition', 'model', 'route', 'llm_calls'}
        if not isinstance(rows, list) or not rows or len(rows) > 100:
            raise ValueError('Invalid answer review bundle.')
        result = []
        seen = set()
        for row in rows:
            if forbidden.intersection(row) or row['review_id'] in seen:
                raise ValueError('Reviewer bundle must omit condition, model and route.')
            seen.add(row['review_id'])
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', row['review_id']):
                raise ValueError('Invalid review ID.')
            if not isinstance(row['query'], str) or not isinstance(row['required_facts'], list):
                raise ValueError('Invalid reviewer reference.')
            result.append({key: row.get(key) for key in
                ('review_id', 'query', 'answer', 'abstention_reason', 'required_facts', 'source_refs',
                 'answer_sources', 'reference_sources')})
        self.review_sha = sha(raw)
        self.rows = result
        frozen = dict(input_sha256=self.review_sha, bundle=value)
        if self._restoring:
            if json.loads(self._saved('frozen-answer-review.json')) != frozen:
                raise ValueError('Frozen answer review changed; original study cannot be resumed.')
        else:
            self._write_new('frozen-answer-review.json', frozen)
        return result

    def audio(self, identifier):
        if identifier not in self.samples:
            raise KeyError('Unknown fixed audio.')
        sample = self.samples[identifier]
        path = sample['path'].resolve(strict=True)
        if not path.is_relative_to(self.audio_manifest.parent) or path.stat().st_size > MAX_AUDIO:
            raise ValueError('Unsafe listening path.')
        raw = path.read_bytes()
        if sha(raw) != sample['sha256']:
            raise TrialConflict('Fixed listening audio changed.')
        return raw

    def _session(self, sid):
        if not isinstance(sid, str) or sid not in self.sessions:
            raise KeyError('Start a consented session first.')
        return self.sessions[sid]

    def _event(self, session, kind, payload):
        with self.lock:
            number = session['events'] + 1
            record = {**copy.deepcopy(payload), 'id': uuid.uuid4().hex, 'session_id': session['id'], 'kind': kind,
                'saved_utc': utc(), 'previous_event_sha256': session['last_sha'],
                'audio_manifest_sha256': self.audio_manifest_sha, 'answer_bundle_sha256': self.review_sha,
                'speaker_id': session['consent']['pseudonym'],
                'speaker_group_id': session['consent']['pseudonym'],
                'identity_source': 'participant_declared_pseudonym_not_independently_verified',
                'human_observer_verified': False}
            raw = (json.dumps(record, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
            with (self.directory / f'{session["id"]}-{number:04d}-{kind}.json').open('xb') as stream:
                stream.write(raw)
            session['events'], session['last_sha'] = number, sha(raw)
            if kind == 'task-error' and payload.get('task_id') in session['tasks']:
                session['tasks'][payload['task_id']]['last_error'] = dict(
                    operation=payload['operation'], message=payload['error'])
            return dict(saved=True, event_sha256=session['last_sha'], id=record['id'])

    def start(self, body):
        if not isinstance(body, dict) or set(body) != {'pseudonym', 'consent', 'audio_storage_consent', 'implementation_participation'}:
            raise ValueError('Invalid consent fields.')
        if (not isinstance(body['pseudonym'], str) or not re.fullmatch(r'P[0-9]{3,6}', body['pseudonym'])
                or body['consent'] is not True or type(body['audio_storage_consent']) is not bool
                or type(body['implementation_participation']) is not bool):
            raise ValueError('Use P001 etc. and explicit consent choices.')
        sid = uuid.uuid4().hex
        order = list(self.samples)
        random.Random(sid).shuffle(order)
        session = dict(id=sid, events=0, last_sha=None, consent=copy.deepcopy(body),
            listening_order=order, listening={}, reviews={}, tasks={})
        self.sessions[sid] = session
        self._event(session, 'consent', body)
        return dict(session_id=sid)

    def state(self, sid=None):
        rows = self._answers()
        session = self._session(sid) if sid else None
        samples = session['listening_order'] if session else []
        return dict(csrf_token=self.token, answer_ready=bool(rows), answer_bundle_sha256=self.review_sha,
            answers=rows, listening=[dict(sample_id=identifier,
                critical_fields=self.samples[identifier]['keys'], audio_sha256=self.samples[identifier]['sha256'],
                audio_url='/api/listening/audio/' + identifier) for identifier in samples],
            completed_listening=list(session['listening']) if session else [],
            completed_reviews=list(session['reviews']) if session else [],
            audio_storage_consent=session['consent']['audio_storage_consent'] if session else False,
            reference_reveal_allowed=bool(session and len(session['listening']) == len(self.samples)),
            active_task=self._public_task(session) if session else None,
            initial_results_are_empty=not bool(session and (session['listening'] or session['reviews'] or session['tasks'])),
            local_audio_processing=self.stt_provider == 'cafet', audio_storage_local=True,
            recognition_provider=self.stt_provider, recognition_model=LIVE_MODEL if self.stt_provider == 'gemini_live' else None,
            cloud_submission_requires_explicit_action=self.stt_provider == 'gemini_live', answer_tts_online=True,
            listening_text_scope=self.text_scope)

    def _public_task(self, session):
        if not session['tasks']:
            return None
        task = next(reversed(session['tasks'].values()))
        with task['lock']:
            recording = task['recording']
            return dict(task_id=task['id'], intended_request=task['intended_request'], context=task['context'],
                recording=dict(audio_sha256=recording['audio_sha256'], duration_seconds=recording['duration_seconds'],
                    audio_url=f'/api/task-recording/{task["id"]}?session_id={session["id"]}') if recording else None,
                reference=copy.deepcopy(task['reference']), reference_draft=copy.deepcopy(task['reference_draft']),
                transcription_attempted=task['transcription_attempted'], transcript=copy.deepcopy(task['transcript']),
                measurement=copy.deepcopy(task['measurement']),
                results=[dict(condition=k, answer=v['result'].get('answer'), route=v['result'].get('route'),
                    citations=v['result'].get('citations'), input_lineage=v['result'].get('input_lineage'),
                    observation_saved=k in task['observations']) for k,v in task['results'].items()],
                last_error=copy.deepcopy(task['last_error']))

    def review(self, body):
        required = {'session_id', 'review_id', 'correctness', 'completeness', 'citation_support', 'reason'}
        if not isinstance(body, dict) or set(body) != required:
            raise ValueError('Invalid answer review fields.')
        with self.lock:
            session = self._session(body['session_id'])
            rows = {row['review_id']: row for row in self._answers()}
            if body['review_id'] not in rows:
                raise ValueError('Unknown frozen answer review.')
            if body['review_id'] in session['reviews']:
                raise TrialConflict('Prior human judgment is immutable; start a separately identified review.')
            for key in ('correctness', 'completeness', 'citation_support'):
                if body[key] not in {'correct', 'partial', 'wrong', 'not_applicable'}:
                    raise ValueError('Choose a judgment for every dimension.')
            if not isinstance(body['reason'], str) or not 3 <= len(body['reason'].strip()) <= 1500:
                raise ValueError('Add a concrete evidence reason.')
            result = self._event(session, 'answer-review', dict(**body,
                human_review_source='explicit_browser_self_report', implementation_participation=session['consent']['implementation_participation']))
            session['reviews'][body['review_id']] = result['id']
            return result

    def listen(self, body):
        required = {'session_id', 'sample_id', 'audio_sha256', 'heard_values', 'intelligibility',
                    'naturalness', 'listened', 'playback_ended'}
        if not isinstance(body, dict) or set(body) != required:
            raise ValueError('Invalid critical-slot listening fields.')
        with self.lock:
            session = self._session(body['session_id'])
            sample = self.samples.get(body['sample_id'])
            if sample is None or sample['sha256'] != body['audio_sha256']:
                raise ValueError('Require the exact frozen audio hash.')
            if body['sample_id'] in session['listening']:
                raise TrialConflict('Listening result already saved; previous text is not overwritten.')
            if (body['listened'] is not True or body['playback_ended'] is not True
                    or not isinstance(body['heard_values'], dict)
                    or set(body['heard_values']) != set(sample['keys'])
                    or any(not isinstance(v, str) or not 1 <= len(v.strip()) <= 200 for v in body['heard_values'].values())):
                raise ValueError('Complete playback, confirm listening and type every heard value; use ? if unclear.')
            for field in ('intelligibility', 'naturalness'):
                if type(body[field]) is not int or not 1 <= body[field] <= 5:
                    raise ValueError('Listening ratings must be integers 1–5.')
            self.audio(body['sample_id'])
            result = self._event(session, 'listening', dict(**body, human_review_source='explicit_browser_self_report',
                condition_blinded_at_submission=True))
            session['listening'][body['sample_id']] = result['id']
            return dict(**result, reference_hidden_until_all_listening_complete=True)

    def reveal(self, sid):
        session = self._session(sid)
        if len(session['listening']) != len(self.samples):
            raise TrialConflict('Finish listening before revealing reference values.')
        return [dict(sample_id=identifier, written=self.samples[identifier]['written'],
            critical_values=self.samples[identifier]['reference'], source_refs=self.samples[identifier]['source_refs'],
            critical_reference_sha256=self.samples[identifier]['critical_reference_sha256'])
            for identifier in session['listening_order']]

    def begin_task(self, body):
        base = {'session_id', 'intended_request'}
        context_fields = {'device', 'room', 'scenario'}
        if not isinstance(body, dict) or set(body) not in (base, base | context_fields):
            raise ValueError('Invalid task fields.')
        session = self._session(body['session_id'])
        text = body['intended_request']
        if not isinstance(text, str) or not 3 <= len(text.strip()) <= 1000:
            raise ValueError('First type the request you intend to make, before recording.')
        context = {key: body.get(key) for key in context_fields}
        if context_fields <= set(body) and any(
                not isinstance(value, str) or not 1 <= len(value.strip()) <= 200 for value in context.values()):
            raise ValueError('State the recording device, room and question scenario.')
        task_id = uuid.uuid4().hex
        task = self._new_task(task_id, text.strip(), context)
        session['tasks'][task_id] = task
        self._event(session, 'task-start', dict(task_id=task_id, intended_request=text.strip(),
            recording_context=context, recording_context_reported=context_fields <= set(body),
            intent_entered_before_stt=True, asr_utterance_reference=None, human_utterance_reference_confirmed=False))
        return dict(task_id=task_id)

    def _task(self, sid, task_id):
        session = self._session(sid)
        if task_id not in session['tasks']:
            raise KeyError('Unknown task in this session.')
        return session, session['tasks'][task_id]

    def _upstream(self, path, body=None, mime='application/json', *, extra_headers=None):
        headers = {'Origin': self.upstream, **(extra_headers or {})}
        if body is not None:
            headers['Content-Type'] = mime
        request = Request(self.upstream + path, data=body, headers=headers)
        try:
            with self._opener.open(request, timeout=240) as response:
                raw = response.read(MAX_AUDIO + 1)
                if len(raw) > MAX_AUDIO:
                    raise ValueError('Upstream body exceeds fixed limit.')
                return json.loads(raw) if response.headers.get_content_type() == 'application/json' else raw
        except HTTPError as error:
            # Do not expose arbitrary server internals or local filesystem paths.
            raise ValueError(f'Local demo returned HTTP {error.code}; keep this attempt and retry when ready.') from None
        except (URLError, TimeoutError) as error:
            raise ValueError('Local demo is unavailable or timed out; this attempt remains recorded.') from None

    def capture_recording(self, sid, task_id, raw, mime):
        """Retain audio for human listening; this operation never invokes ASR."""
        session, task = self._task(sid, task_id)
        with task['lock']:
            if not session['consent']['audio_storage_consent']:
                raise ValueError('Audio storage consent was not given; use typed/review/listening sections.')
            if task['recording'] is not None:
                raise TrialConflict('This task already has one recording; begin a new task to retry.')
            if (not raw or len(raw) > MAX_AUDIO
                    or mime not in {'audio/wav', 'audio/webm', 'audio/ogg', 'audio/mpeg', 'audio/mp4', 'audio/x-wav'}):
                raise ValueError('Use a supported audio file up to 8 MiB.')
            recordings = (self.directory / 'recordings').resolve()
            if not recordings.is_relative_to(self.directory):
                raise ValueError('Unsafe recording directory.')
            recordings.mkdir(exist_ok=True)
            name = 'recordings/' + session['id'] + '-' + task_id + '-' + uuid.uuid4().hex + '-input.audio'
            with (self.directory / name).open('xb') as stream:
                stream.write(raw)
            # Reuse the established content-sniffing decoder; no model or network call.
            try:
                try:
                    from tools.prepare_stt_study_audio import prepare_audio
                except ModuleNotFoundError:
                    from prepare_stt_study_audio import prepare_audio
                prepared = prepare_audio(self.directory / name, self.directory / (name + '.wav'))
            except (OSError, ValueError, ImportError) as error:
                too_long = getattr(error, 'code', None) == 'audio_too_long'
                message = ('Бичлэг 30 секундээс урт байна. Эх файл хадгалагдсан. '
                           'Нэг богино асуултыг дахин бичнэ үү.' if too_long else
                           'Recording could not be decoded to study WAV; original retained.')
                self._event(session, 'task-error', dict(task_id=task_id, operation='prepare_audio',
                    audio_file=name, input_sha256=sha(raw), input_mime=mime,
                    error_code='audio_too_long' if too_long else 'audio_preparation_failed', error=message))
                raise ValueError(message) from error
            recording = dict(audio_file=Path(prepared['output']).relative_to(self.directory).as_posix(),
                audio_sha256=prepared['audio_sha256'], input_mime='audio/wav',
                original_audio_file=name, original_audio_sha256=sha(raw), original_mime=mime,
                provenance_file=Path(prepared['provenance']).relative_to(self.directory).as_posix(),
                provenance_sha256=prepared['provenance_sha256'], duration_seconds=prepared['duration_seconds'],
                captured_utc=utc(), recording_context=copy.deepcopy(task['context']),
                recorded_at_not_inferred_from_upload=True, native_study_format='mono_16000hz_pcm16_wav')
            self._event(session, 'task-recording', dict(task_id=task_id, **recording,
                asr_performed=False, human_utterance_reference_confirmed=False))
            task['recording'] = recording
            task['last_error'] = None
            return dict(audio_sha256=recording['audio_sha256'],
                audio_url=f'/api/task-recording/{task_id}?session_id={sid}', asr_performed=False)

    def recording_audio(self, sid, task_id):
        _, task = self._task(sid, task_id)
        recording = task['recording']
        if recording is None:
            raise ValueError('Record or upload speech before listening.')
        path = (self.directory / recording['audio_file']).resolve(strict=True)
        if not path.is_relative_to(self.directory) or path.stat().st_size > MAX_AUDIO:
            raise ValueError('Unsafe retained recording.')
        raw = path.read_bytes()
        if sha(raw) != recording['audio_sha256']:
            raise TrialConflict('Retained recording changed; begin a new task.')
        return raw, recording['input_mime']

    def confirm_reference(self, body):
        required = {'session_id', 'task_id', 'audio_sha256', 'reference', 'uncertainties',
                    'listened', 'playback_ended', 'confirmed'}
        if not isinstance(body, dict) or set(body) != required:
            raise ValueError('Invalid listened-reference fields.')
        session, task = self._task(body['session_id'], body['task_id'])
        with task['lock']:
            if task['recording'] is None:
                raise ValueError('Record or upload speech before confirming its reference.')
            if task['reference'] is not None or task['transcription_attempted']:
                raise TrialConflict('The pre-ASR reference is immutable; begin a new task to correct it.')
            if (body['audio_sha256'] != task['recording']['audio_sha256']
                    or body['listened'] is not True or body['playback_ended'] is not True
                    or type(body['confirmed']) is not bool):
                raise ValueError('Listen to the exact recording and explicitly confirm its full spoken text.')
            text = body['reference']
            if (not isinstance(text, str) or not 1 <= len(text.strip()) <= 1000
                    or not any(character.isalnum() for character in text)):
                raise ValueError('Type the complete spoken words yourself; an intent or model guess is not a reference.')
            uncertainties = body['uncertainties']
            if (not isinstance(uncertainties, list) or len(uncertainties) > 20
                    or any(not isinstance(value, str) or not 1 <= len(value.strip()) <= 200 for value in uncertainties)):
                raise ValueError('List unresolved words or numbers explicitly.')
            self.recording_audio(body['session_id'], body['task_id'])
            if uncertainties or not body['confirmed']:
                draft = dict(text=text.strip(), uncertainties=copy.deepcopy(uncertainties))
                duplicate = task['reference_draft'] == draft
                if not duplicate:
                    self._event(session, 'task-reference-pending', dict(task_id=body['task_id'],
                        reference_draft=text.strip(), uncertainties=copy.deepcopy(uncertainties),
                        audio_sha256=body['audio_sha256'], human_utterance_reference_confirmed=False,
                        reference_confirmed_before_asr=False, asr_performed=False))
                    task['reference_draft'] = draft
                return dict(saved=True, reference_confirmed_before_asr=False, asr_performed=False,
                    duplicate_draft=duplicate, unresolved_count=len(uncertainties),
                    pending_reason='unresolved_words' if uncertainties else 'confirmation_required')
            reference = dict(text=text.strip(), audio_sha256=body['audio_sha256'], confirmed_utc=utc(),
                uncertainties=[], reference_origin='human_listened_before_asr', observer_verified=False)
            self._event(session, 'task-reference', dict(task_id=body['task_id'], **reference,
                human_utterance_reference_confirmed=True, reference_confirmed_before_asr=True,
                listened=True, playback_ended=True))
            task['reference'] = reference
            return dict(saved=True, reference_confirmed_before_asr=True, asr_performed=False)

    def recognize(self, body):
        required = {'session_id', 'task_id'} | ({'cloud_audio_consent'} if self.stt_provider == 'gemini_live' else set())
        if not isinstance(body, dict) or set(body) != required:
            raise ValueError('Use the already retained, human-reviewed task recording.')
        return self.transcribe(body['session_id'], body['task_id'], cloud_audio_consent=body.get('cloud_audio_consent', False))

    def transcribe(self, sid, task_id, *, cloud_audio_consent=False):
        _, task = self._task(sid, task_id)
        with task['lock']:
            return self._transcribe(sid, task_id, cloud_audio_consent=cloud_audio_consent)

    def _transcribe(self, sid, task_id, *, cloud_audio_consent=False):
        session, task = self._task(sid, task_id)
        if not session['consent']['audio_storage_consent']:
            raise ValueError('Audio storage consent was not given; use typed/review/listening sections.')
        if task['recording'] is None or task['reference'] is None:
            raise ValueError('Listen and confirm the full spoken reference before ASR.')
        if task['transcription_attempted']:
            raise TrialConflict('This task already attempted ASR; begin a new task to retry.')
        raw, mime = self.recording_audio(sid, task_id)
        cloud = self.stt_provider == 'gemini_live'
        if cloud and cloud_audio_consent is not True:
            raise ValueError('Энэ бичлэгийг Google Gemini рүү илгээх үйлдлээ батална уу.')
        started = time.perf_counter()
        headers = None
        if cloud:
            state = self._upstream('/api/voice/gemini/session')
            if (not isinstance(state, dict) or state.get('model') != LIVE_MODEL or state.get('ready') is not True
                    or not isinstance(state.get('csrf_token'), str) or not state['csrf_token'].isascii()):
                raise ValueError('Үндсэн чатын Gemini холболт бэлэн биш. Хадгалсан түлхүүрийг дахин тохируулахгүй.')
            headers = {'X-Gemini-Token': state['csrf_token'], 'X-STT-Provider': 'gemini_live',
                       'X-Gemini-Audio-Consent': 'send-this-audio'}
        audio_name = task['recording']['audio_file']
        task['transcription_attempted'] = True
        self._event(session, 'task-stt-attempt', dict(task_id=task_id, uploaded_audio_sha256=sha(raw),
            reference_confirmed_before_asr=True, reference_not_sent_to_asr=True,
            recognition_provider=self.stt_provider, cloud_audio_consent=cloud_audio_consent if cloud else False))
        try:
            value = (self._upstream('/api/voice/transcribe', raw, mime, extra_headers=headers) if cloud
                     else self._upstream('/api/voice/transcribe', raw, mime))
            if (not isinstance(value, dict) or value.get('kind') != 'stt' or not isinstance(value.get('text'), str)
                    or not isinstance(value.get('id'), str) or not re.fullmatch(r'[0-9a-f]{32}', value['id'])):
                raise ValueError('Upstream STT response is malformed.')
            if cloud and (value.get('model') != LIVE_MODEL or value.get('provider') != 'google_gemini_live'
                          or value.get('input_sha256') != sha(raw) or value.get('translated_output_used') is not False):
                raise ValueError('Gemini model, raw-input source, or retained audio hash differs.')
            wall_seconds = time.perf_counter()-started
            measurement = measure(task['reference']['text'], value['text'],
                audio_seconds=task['recording']['duration_seconds'], wall_seconds=wall_seconds,
                provider_seconds=value.get('transcription_seconds'), cache_hit=value.get('cache_hit', False)) if cloud else None
        except ValueError as error:
            self._event(session, 'task-error', dict(task_id=task_id, operation='transcribe', input_sha256=sha(raw),
                audio_file=audio_name, input_mime=mime, error=str(error)))
            raise
        task['transcript'] = copy.deepcopy(value)
        task['measurement'] = measurement
        task['audio_ids'].add(value['id'])
        self._event(session, 'task-stt', dict(task_id=task_id, uploaded_audio_sha256=sha(raw),
            audio_file=audio_name, input_mime=mime,
            actual_response=value, wall_seconds=wall_seconds, measurement=measurement,
            asr_utterance_reference=task['reference']['text'], human_utterance_reference_confirmed=True,
            reference_confirmed_before_asr=True, reference_not_sent_to_asr=True))
        return dict(text=value['text'], transcription_id=value['id'], recognition_review=value.get('recognition_review'),
                    measurement=measurement, provider=value.get('provider'), model=value.get('model'))

    def route(self, body):
        if not isinstance(body, dict) or set(body) != {'session_id', 'task_id', 'condition', 'edited_text', 'edit_confirmed'}:
            raise ValueError('Invalid route task fields.')
        _, task = self._task(body['session_id'], body['task_id'])
        with task['lock']:
            return self._route(body)

    def _route(self, body):
        session, task = self._task(body['session_id'], body['task_id'])
        condition = body['condition']
        if condition not in {'typed', 'raw', 'explicit-edited'}:
            raise ValueError('Unknown task condition.')
        if condition in task['results']:
            raise TrialConflict('Task condition already submitted; preserve the first attempt.')
        request = dict(query=task['intended_request'])
        if condition != 'typed':
            if task['transcript'] is None:
                raise ValueError('Record or upload speech first.')
            text = task['transcript']['text']
            if condition == 'explicit-edited':
                if (body['edit_confirmed'] is not True or not isinstance(body['edited_text'], str)
                        or not 1 <= len(body['edited_text'].strip()) <= 1000):
                    raise ValueError('Explicitly confirm the text you personally reviewed.')
                text = body['edited_text'].strip()
            elif body['edited_text'] is not None or body['edit_confirmed'] is not False:
                raise ValueError('Raw condition must use the immutable server-owned STT text.')
            request.update(query=text, transcription_id=task['transcript']['id'])
        elif body['edited_text'] is not None or body['edit_confirmed'] is not False:
            raise ValueError('Typed condition must use the original intended request.')
        started = time.perf_counter()
        try:
            result = self._upstream('/api/route', json.dumps(request).encode())
        except ValueError as error:
            self._event(session, 'task-error', dict(task_id=task['id'], condition=condition, operation='route', error=str(error)))
            raise
        task['results'][condition] = dict(query=request['query'], result=copy.deepcopy(result))
        self._event(session, 'task-route', dict(task_id=task['id'], condition=condition,
            actual_sent_text=request['query'], explicit_edit_confirmed=condition == 'explicit-edited',
            actual_response=result, wall_seconds=time.perf_counter()-started,
            edited_intent_is_asr_gold=False))
        return dict(condition=condition, answer=result.get('answer'), route=result.get('route'),
            citations=result.get('citations'), input_lineage=result.get('input_lineage'))

    def speak(self, body):
        if not isinstance(body, dict) or set(body) != {'session_id', 'task_id', 'condition'}:
            raise ValueError('Invalid synthesis task fields.')
        _, task = self._task(body['session_id'], body['task_id'])
        with task['lock']:
            return self._speak(body)

    def _speak(self, body):
        session, task = self._task(body['session_id'], body['task_id'])
        condition = body['condition']
        if condition not in task['results']:
            raise ValueError('Submit this task condition first.')
        prior = task['results'][condition]
        result = prior['result']
        request = dict(query=prior['query'], allow_draft=False, voice='mn-MN-BataaNeural',
            package_id=result['package_id'], release_token=result.get('content_release', {}).get('activation_token'))
        if result.get('response_id'):
            request['response_id'] = result['response_id']
        started = time.perf_counter()
        try:
            audio = self._upstream('/api/voice/speak', json.dumps(request).encode())
        except ValueError as error:
            self._event(session, 'task-error', dict(task_id=task['id'], condition=condition, operation='speak', error=str(error)))
            raise
        if not re.fullmatch(r'[0-9a-f]{32}', audio.get('id', '')):
            raise ValueError('Malformed bound TTS ID.')
        task['audio_ids'].add(audio['id'])
        task['synthesized'].add(condition)
        self._event(session, 'task-tts', dict(task_id=task['id'], condition=condition,
            actual_response=audio, wall_seconds=time.perf_counter()-started,
            human_listened=None))
        return dict(audio_url=f'/api/voice-audio/{audio["id"]}?session_id={session["id"]}')

    def voice_audio(self, sid, identifier):
        session = self._session(sid)
        if not re.fullmatch(r'[0-9a-f]{32}', identifier) or not any(identifier in t['audio_ids'] for t in session['tasks'].values()):
            raise KeyError('Audio does not belong to this study session.')
        return self._upstream('/api/voice/audio/' + identifier)

    def observe(self, body):
        required = {'session_id', 'task_id', 'condition', 'task_success', 'heard_answer',
                    'intelligibility', 'naturalness', 'tts_listened', 'notes'}
        if not isinstance(body, dict) or set(body) != required:
            raise ValueError('Invalid task observation fields.')
        _, task = self._task(body['session_id'], body['task_id'])
        with task['lock']:
            return self._observe(body)

    def _observe(self, body):
        session, task = self._task(body['session_id'], body['task_id'])
        if body['condition'] not in task['results'] or body['task_success'] not in {'yes', 'partial', 'no'}:
            raise ValueError('Submit the condition before judging its task success.')
        if type(body['tts_listened']) is not bool:
            raise ValueError('Explicitly state whether you actually listened.')
        if body['condition'] in task['observations']:
            raise TrialConflict('Previous observation is immutable.')
        if body['tts_listened'] and body['condition'] not in task['synthesized']:
            raise ValueError('This condition has no synthesized audio to listen to.')
        for key in ('heard_answer', 'notes'):
            if not isinstance(body[key], str) or len(body[key]) > 1500:
                raise ValueError('Invalid task note.')
        if body['tts_listened'] and not body['heard_answer'].strip():
            raise ValueError('After listening, type what you understood from the answer.')
        for key in ('intelligibility', 'naturalness'):
            rating = body[key]
            if body['tts_listened']:
                if type(rating) is not int or not 1 <= rating <= 5:
                    raise ValueError('Choose listening scores only after listening.')
            elif rating is not None:
                raise ValueError('Unheard audio cannot receive listening ratings.')
        result = self._event(session, 'task-observation', dict(**body,
            human_review_source='explicit_browser_self_report', asr_wer_measured=False))
        task['observations'].add(body['condition'])
        return result


PAGE = r'''<!doctype html><html lang="mn"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Чанарын бодит шалгалт</title><style>*{box-sizing:border-box}body{margin:0;background:#f2f5f1;color:#18342c;font:16px/1.6 system-ui}main{max-width:900px;margin:auto;padding:24px 18px}article,section{background:white;border:1px solid #d4ded6;padding:20px;border-radius:14px;margin:18px 0}h1{line-height:1.2}h2{font-size:22px}label{display:block;margin:12px 0}input:not([type=checkbox]),textarea,select{width:100%;font:inherit;padding:8px;border:1px solid #a8bdae;border-radius:6px}textarea{min-height:85px}button,a.button{font:inherit;background:#245942;color:white;padding:9px 15px;border:0;border-radius:7px;cursor:pointer;margin:5px 8px 5px 0}button:disabled{opacity:.5;cursor:default}audio{width:100%}pre{white-space:pre-wrap;overflow-wrap:anywhere}small,.muted{color:#547064}.error{color:#9c2430}.hidden{display:none}.row{display:flex;gap:12px;flex-wrap:wrap}.row>*{flex:1;min-width:180px}a{color:#245942}</style>
<main><a href="http://127.0.0.1:8765/">← Чат</a><h1>Чанарыг хүнээр шалгах жижиг туршилт</h1>
<p>Энд таны бодит үнэлгээг хадгална. Хувийн нэр, утас хэрэггүй. Аль нэг хэсгийг сонгоод завсарлаж болно. Энэ нь сургуулиар баталсан судалгааны дизайн биш.</p>
<p>Бичлэг эхлээд энэ компьютерт хадгалагдана. Сонсож reference-ээ баталсны дараа «Google руу илгээж Gemini-ээр таних» товч дарвал зөвхөн тэр аудио Google Gemini 3.5 Live руу очно; reference текстийг Google руу илгээхгүй. Free tier-ийн өгөгдлийг Google сайжруулалтад ашиглаж, хүн хянаж болох нөхцөлтэй. Автоматаар устах хугацаа тохируулаагүй. «Хариуг сонсох» үед хариултын текст онлайн Edge/Microsoft TTS-д очно. Доорх бэлтгэсэн 12 дууг сонсоход шинээр сүлжээнд текст/бичлэг явуулахгүй.</p>
<section id="start"><label>Оролцогчийн зохиомол ID (жишээ P001)<input id="pseudo" value="P001" maxlength="7"></label><label><input type="checkbox" id="consent"> Би энэ туршилтад сайн дураар оролцож, хариултаа локал файлд хадгалахыг зөвшөөрч байна.</label><label><input type="checkbox" id="audioConsent"> Шинээр бичсэн дуугаа локал хадгалж STT туршихыг зөвшөөрнө. Сонгохгүйгээр бусад хэсгийг хийж болно.</label><label><input type="checkbox" id="developer"> Би энэ системийг хөгжүүлэхэд оролцсон.</label><button id="begin">Эхлэх</button></section>
<p id="status" role="status"></p><div id="workspace" class="hidden"><nav><a href="#listen">1. Дуу сонсох</a> · <a href="#answer">2. Хариулт үнэлэх</a> · <a href="#voice">3. Бодит асуулт</a></nav>
<section id="listen"><h2>1. Он, тоо, нэрийг дуунаас ойлгох</h2><p><span id="listeningScope"></span> Текст, өмнөх/шинэ хувилбарын нэрийг түр нуусан. Сонссоноо бичнэ үү; ойлгомжгүй бол <b>?</b> гэж бич. Бүх дуу дууссаны дараа эх текстийг харуулна.</p><p id="listenProgress"></p><div id="listenCard"></div><div id="reveal"></div></section>
<section id="answer"><h2>2. Эхтэй нь тулгаж хариултыг үнэлэх</h2><p>Зөв, дутуу, бурууг эхийн баримтаар дүгнэнэ. Хариулт үүсгэсэн арга, model-ийг нуусан. Та хөгжүүлэгч бол энэ нь хараат бус үнэлгээ гэж тооцогдохгүй.</p><p id="answerProgress"></p><div id="answerCard"></div><button id="refreshAnswers">Шинэ асуултын багцыг шалгах</button></section>
<section id="voice"><h2>3. Шинэ асуултаа бичиж, сонсож батлаад STT турших</h2><p>Эхлээд асуух санаагаа бичиж хадгална. Дараа нь өөрийн үгээр ярьж бичнэ. Санаагаа бичсэн текст болон зассан STT нь аудиогийн reference болохгүй. Танилт ажиллуулахаас өмнө бичлэгээ бүтнээр сонсож, яг хэлсэн үгээ тусад нь бичиж батална. Ижил асуултын 3 нөхцөл нь жижиг paired даалгавар; хариуг давтаж харах нөлөөг салгаж чадахгүй. Баталсан reference ба Gemini raw-ийг WER/CER, үг солигдсон/хасагдсан/нэмэгдсэн тоо, хугацаагаар автоматаар харьцуулна. Тоо–үгийг нууцаар дүйцүүлэхгүй; нэр/тоо/оны утгын зөв байдлыг хүн тусад нь нягтална.</p>
<p>Нэг хүн өөр session-д орсон ч ижил оролцогчийн ID-гаа хэрэглэнэ. Шинэ асуулт нь шинэ хүн гэсэн үг биш.</p><label>Бичлэгийн төхөөрөмж<input id="device" maxlength="200" placeholder="Жишээ: laptop-ийн дотоод микрофон"></label><label>Бичлэгийн орчин<input id="room" maxlength="200" placeholder="Жишээ: гэрт, чимээгүй"></label><label>Асуултын нөхцөл / сэдэв<input id="scenario" maxlength="200" placeholder="Жишээ: элсэлтийн оныг лавлах"></label><label>Та яг юу асуухыг хүсэж байна вэ?<textarea id="intent" placeholder="Өөрийн шинэ асуултаа бичнэ үү"></textarea></label><button id="taskBegin">Энэ санааг хадгалж даалгавар эхлэх</button><div id="taskBody" class="hidden"><button id="typed">Бичсэн асуултыг илгээх</button><p id="recordStatus"></p><button id="record">Микрофон эхлүүлэх</button><button id="stop" disabled>Бичлэгийг зогсоох</button><label>Эсвэл өөрийн дуу оруулах<input id="upload" type="file" accept="audio/*"></label><audio id="recordedAudio" controls preload="metadata"></audio><label>Танилтаас өмнө сонсож буулгасан яг үг<textarea id="reference" placeholder="Бичлэгээ сонсоод бүх хэлсэн үгээ бичнэ үү. Энд бэлэн текст байхгүй."></textarea></label><label>Эргэлзээтэй үг, тоо (нэг мөрөнд нэгийг; байвал батлагдахгүй)<textarea id="uncertainties" aria-describedby="referenceHelp" placeholder="Эргэлзээтэй үг байвал л бичнэ. Байхгүй бол хоосон үлдээнэ."></textarea></label><label><input id="referenceConfirmed" type="checkbox"> Би бичлэгийг бүтнээр сонсож, яг хэлсэн бүх үгийг нягталсан. Эргэлзээтэй үг, тоо үлдээгүй.</label><p id="referenceHelp" role="status" aria-live="polite">Дуугаа бүтнээр сонсоод яг хэлсэн үгээ бичнэ. Эргэлзээтэй үггүй бол дээрх эргэлзээний талбарыг хоосон үлдээж, батлах чагтыг сонгоно.</p><button id="saveReference" disabled>Сонссон текстийг хадгалах</button><button id="recognize" disabled>Google руу илгээж Gemini-ээр таних</button><p id="measurement" role="status"></p><pre id="raw"></pre><button id="rawSend" disabled>Raw текстийг өөрчлөхгүй илгээх</button><label>Та өөрөө сонсож/нягталсан зассан текст<textarea id="edited"></textarea></label><label><input id="editConfirmed" type="checkbox"> Би энэ текстийг өөрөө нягталж илгээхийг баталж байна. Энэ засвар анхны reference-ийг өөрчлөхгүй.</label><button id="editedSend" disabled>Зассан текстийг илгээх</button><div id="taskResults"></div><button id="nextTask">Дараагийн шинэ асуулт</button></div></section></div></main>
<script>
const $=id=>document.getElementById(id);let token='',sid=sessionStorage.getItem('humanTrialSession')||'',state={},taskId='',recording=null,stream=null,busy=false,recordingSha='',referenceHeard=false,recordingClock=null,recordingSaving=false;
const words={year:'Он',phone:'Утасны цифр',name:'Нэр',negation:'Үгүйсгэсэн үг',amount:'Мөнгөн дүн',unit:'Мөнгөний нэгж'};
function el(tag,text,parent){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(parent)parent.append(n);return n}
function status(text,error=false){$('status').textContent=text;$('status').className=error?'error':''}
async function api(path,body,extra={}){const r=await fetch(path,{method:body===undefined?'GET':'POST',headers:body===undefined?{}:{'Content-Type':'application/json','X-Trial-Token':token,...extra},body:body===undefined?undefined:JSON.stringify(body)});const v=await r.json();if(!r.ok)throw Error(v.error||'Хүсэлт амжилтгүй');return v}
async function action(fn){if(busy)return;busy=true;try{await fn()}catch(e){status(e.message,true)}finally{busy=false}}
async function refresh(){state=await api('/api/state?'+(sid?'session_id='+sid:''));token=state.csrf_token;$('listeningScope').textContent=state.listening_text_scope;renderListening();renderAnswer()}
$('begin').onclick=()=>action(async()=>{const v=await api('/api/start',{pseudonym:$('pseudo').value,consent:$('consent').checked,audio_storage_consent:$('audioConsent').checked,implementation_participation:$('developer').checked});sid=v.session_id;sessionStorage.setItem('humanTrialSession',sid);$('start').classList.add('hidden');$('workspace').classList.remove('hidden');status('Session эхэллээ. Үнэлгээ зөвхөн таны хадгалсан үйлдлээр бүртгэгдэнэ.');await refresh()});
function rating(parent,label,values){const l=el('label',label,parent),s=el('select',undefined,l);el('option','Сонгоно уу',s).value='';for(const [value,text] of values)el('option',text,s).value=value;return s}
const scale=[['1','1 — ойлгомжгүй / маш хиймэл'],['2','2'],['3','3'],['4','4'],['5','5 — бүрэн ойлгомжтой / жам ёсны']];
function renderListening(){if(!sid)return;const remaining=state.listening.filter(x=>!state.completed_listening.includes(x.sample_id));$('listenProgress').textContent=`Хадгалсан ${state.completed_listening.length}/${state.listening.length}`;const box=$('listenCard');box.replaceChildren();if(!remaining.length){el('p','Бүх дууны хариулт хадгалагдлаа.',box);const b=el('button','Эх текстийг одоо харах',box);b.onclick=()=>action(async()=>{const v=await api('/api/reveal?session_id='+sid);$('reveal').replaceChildren();for(const r of v.references)el('p',r.written,$('reveal'));b.disabled=true});return}
 const item=remaining[0],audio=el('audio',undefined,box);audio.controls=true;audio.src=item.audio_url;let ended=false;audio.onended=()=>{ended=true};const fields={};for(const key of item.critical_fields){const l=el('label',words[key]||key,box);fields[key]=el('input',undefined,l);fields[key].maxLength=200}const int=rating(box,'Үг, тоог ойлгосон байдал',scale),nat=rating(box,'Дууны жам ёсны байдал',scale);const l=el('label',undefined,box),confirm=el('input',undefined,l);confirm.type='checkbox';l.append(' Би энэ дууг бодитоор сонссон.');const save=el('button','Сонссон зүйлээ хадгалж дараагийн дуу',box);save.onclick=()=>action(async()=>{await api('/api/listen',{session_id:sid,sample_id:item.sample_id,audio_sha256:item.audio_sha256,heard_values:Object.fromEntries(Object.entries(fields).map(([k,v])=>[k,v.value])),intelligibility:Number(int.value),naturalness:Number(nat.value),listened:confirm.checked,playback_ended:ended});status('Сонсголын хариулт хадгалагдлаа.');await refresh()})}
function sourceBlock(parent,title,refs){el('strong',title,parent);if(!refs?.length)el('p','Энэ хариултад эшилсэн эх байхгүй.',parent);for(const ref of refs||[]){if(ref.citation_number)el('p','Эшлэл ['+ref.citation_number+']',parent);el('blockquote',ref.quote,parent);if(/^https:\/\/nmct\.edu\.mn(?:\/|$)/.test(ref.url||'')){const a=el('a',ref.title||'Албан эх',parent);a.href=ref.url;a.target='_blank';a.rel='noreferrer'}}}
function renderAnswer(){if(!sid)return;const box=$('answerCard');box.replaceChildren();const rows=state.answers.filter(x=>!state.completed_reviews.includes(x.review_id));$('answerProgress').textContent=`Хадгалсан ${state.completed_reviews.length}/${state.answers.length} · Хэсэгчлэн хадгалаад завсарлаж болно.`;if(!state.answer_ready){el('p','Шинэ асуултын гаралтын багц бэлтгэгдэж байна. Дуу болон бодит асуултын хэсгийг хийж болно.',box);return}if(!rows.length){el('p','Багцын бүх хариултыг үнэлсэн байна. Баярлалаа.',box);return}const row=rows[0];el('h3',row.query,box);el('strong','Системийн хариулт:',box);el('p',row.answer||row.abstention_reason||'Хариулт өгөөгүй.',box);const details=el('details',undefined,box);details.open=true;el('summary','Эхийн нотолгоог харьцуулах',details);sourceBlock(details,'Системийн хариулт бодитоор эшилсэн эх',row.answer_sources);el('hr',undefined,details);el('strong','Гаралтаас өмнө бэлтгэсэн шалгах мэдээлэл (хүн батлаагүй)',details);for(const fact of row.required_facts)el('p','• '+fact,details);sourceBlock(details,'Энэ шалгах мэдээллийн эх',row.reference_sources||row.source_refs);const options=[['correct','Зөв / бүрэн дэмжигдсэн'],['partial','Дутуу / хэсэгчлэн'],['wrong','Буруу / дэмжигдээгүй'],['not_applicable','Энэ тохиолдолд хамаарахгүй']];const c=rating(box,'Утгын зөв байдал',options),m=rating(box,'Шаардсан мэдээллийн бүрэн байдал',options),s=rating(box,'Системийн эшлэлийн нотолгоо',options);const l=el('label','Ямар баримтаар ингэж дүгнэв?',box),reason=el('textarea',undefined,l),b=el('button','Үнэлгээг хадгалах',box);b.onclick=()=>action(async()=>{await api('/api/review',{session_id:sid,review_id:row.review_id,correctness:c.value,completeness:m.value,citation_support:s.value,reason:reason.value});status('Хүний өөрийн үнэлгээг хадгаллаа.');await refresh()})}
$('refreshAnswers').onclick=()=>action(refresh);
function renderMeasurement(m){
 if(!m){$('measurement').textContent='';return}
 const y=m.year_token_comparison;
 const years=y&&JSON.stringify(y.reference)!==JSON.stringify(y.raw)?` Он (баталсан текст): ${y.reference.join(', ')||'цифрээр бичээгүй'}; raw: ${y.raw.join(', ')||'цифрээр бичээгүй'}. Бичлэгтэй тулгаж нягтална уу; үгээр бичсэн тоог энэ шалгалт тайлбарлаагүй.`:'';
 $('measurement').textContent=`WER ${(m.raw_score.corpus_wer*100).toFixed(1)}% · CER ${(m.raw_score.corpus_cer*100).toFixed(1)}% · ${m.raw_score.word_edit_errors}/${m.raw_score.reference_words} үгийн алдаа · ${m.wall_seconds.toFixed(2)} s${m.cache_hit?' · cache (шинэ Google танилт биш)':''}. Зөвхөн энэ reference-ийн development хэмжилт; хүний утгын үнэлгээ тусдаа.`+years;
}
function restoreTask(task){
 if(!task)return;taskId=task.task_id;$('intent').value=task.intended_request;$('intent').disabled=true;$('taskBegin').disabled=true;
 for(const key of ['device','room','scenario']){$(key).value=task.context[key]||'';$(key).disabled=true}
 $('taskBody').classList.remove('hidden');const clip=task.recording,ref=task.reference,raw=task.transcript;
 $('record').disabled=!!clip||!state.audio_storage_consent;$('upload').disabled=$('record').disabled;$('stop').disabled=true;
 $('saveReference').disabled=!clip||!!ref||task.transcription_attempted;$('reference').disabled=!!ref;$('uncertainties').disabled=!!ref;$('referenceConfirmed').disabled=!!ref;
 $('recognize').disabled=!ref||task.transcription_attempted;
 if(clip){recordingSha=clip.audio_sha256;$('recordedAudio').src=clip.audio_url;$('recordStatus').textContent=`Бичлэг хадгалагдсан (${clip.duration_seconds.toFixed(2)} секунд). Бүтнээр сонсоод яг хэлсэн үгээ батална.`}
 if(task.reference_draft){$('reference').value=task.reference_draft.text;$('uncertainties').value=task.reference_draft.uncertainties.join('\n');referenceFeedback('Хадгалсан ноорог сэргэсэн. Эргэлзээний талбар хоосон, батлах чагт сонгосон үед л STT нээгдэнэ.',true)}
 if(ref){$('reference').value=ref.text;$('referenceConfirmed').checked=true;$('recordStatus').textContent='Сонсож баталсан reference сэргэсэн. Анхны баталгаа өөрчлөгдөөгүй.'}
 renderMeasurement(task.measurement);
 if(raw){$('raw').textContent='Анхны STT: '+raw.text;$('edited').value=raw.text}
 $('rawSend').disabled=!raw||!raw.text||task.results.some(r=>r.condition==='raw');$('editedSend').disabled=!raw||task.results.some(r=>r.condition==='explicit-edited');
 $('typed').disabled=task.results.some(r=>r.condition==='typed');for(const value of task.results)renderResult(value);
 if(task.last_error)$('recordStatus').textContent=task.last_error.message+' Эх файл хадгалагдсан. Дахин богино бичлэг хийх эсвэл шинэ асуулт эхлүүлж болно.';
 if(task.transcription_attempted&&!raw)$('recordStatus').textContent='Өмнөх STT оролдлого амжилтгүй/тасарсан. Автоматаар давтахгүй; шинэ асуулт эхлүүлнэ үү.';
}
$('taskBegin').onclick=()=>action(async()=>{const r=await api('/api/task/begin',{session_id:sid,intended_request:$('intent').value,device:$('device').value,room:$('room').value,scenario:$('scenario').value});sessionStorage.removeItem('humanTrialNewTask:'+sid);restoreTask({task_id:r.task_id,intended_request:$('intent').value,context:{device:$('device').value,room:$('room').value,scenario:$('scenario').value},recording:null,reference:null,transcript:null,transcription_attempted:false,results:[]});status('Санааг STT-ээс өмнө хадгаллаа. Бичсэн нөхцөлийг эхэлж илгээж болно.')});
async function sendCondition(condition){const v=await api('/api/task/route',{session_id:sid,task_id:taskId,condition,edited_text:condition==='explicit-edited'?$('edited').value:null,edit_confirmed:condition==='explicit-edited'?$('editConfirmed').checked:false});renderResult(v);status(condition+' нөхцөлийн бодит гаралтыг хадгаллаа.')}
$('typed').onclick=()=>action(async()=>{await sendCondition('typed');$('typed').disabled=true});$('rawSend').onclick=()=>action(async()=>{await sendCondition('raw');$('rawSend').disabled=true});$('editedSend').onclick=()=>action(async()=>{await sendCondition('explicit-edited');$('editedSend').disabled=true});
async function capture(blob){$('recordStatus').textContent='Бичлэгийг локал хадгалж байна…';try{const mime=(blob.type||'audio/webm').split(';')[0];const r=await fetch('/api/task/record',{method:'POST',headers:{'Content-Type':mime,'X-Trial-Token':token,'X-Session-Id':sid,'X-Task-Id':taskId},body:blob});const v=await r.json();if(!r.ok)throw Error(v.error||'Бичлэг хадгалсангүй');recordingSha=v.audio_sha256;referenceHeard=false;$('recordedAudio').src=v.audio_url;$('saveReference').disabled=false;$('record').disabled=true;$('upload').disabled=true;$('recordStatus').textContent='Бичлэг хадгалсан. Бүтнээр сонсоод яг хэлсэн үгээ бичнэ үү. STT хараахан ажиллаагүй.'}catch(error){$('recordStatus').textContent=error.message;$('record').disabled=false;$('upload').disabled=false;$('stop').disabled=true;throw error}}
async function saveStoppedRecording(blob){recordingSaving=true;try{await capture(blob)}catch(error){status(error.message,true)}finally{recordingSaving=false}}
$('recordedAudio').onended=()=>{referenceHeard=true};
function referenceFeedback(message,error=false){$('referenceHelp').textContent=message;$('referenceHelp').className=error?'error':''}
function pendingReferenceHelp(count){const message=count?`Эргэлзээний талбарт ${count} мөр байна. Ноорог хадгалагдсан, STT нээгдэхгүй. Бичлэгээ дахин сонсож эргэлзээгээ шийднэ үү. Эргэлзээгүй болсон үедээ л энэ талбарыг хоосолж, чагтаа сонгоод дахин хадгална.`:'Ноорог хадгалагдсан. Яг хэлсэн бүх үгээ сонсож нягталсан бол батлах чагтыг сонгоод дахин хадгална.';referenceFeedback(message,true);status(message,true);$('recognize').disabled=true;$('uncertainties').setAttribute('aria-invalid',count?'true':'false');$('referenceHelp').scrollIntoView({block:'center',behavior:'smooth'});if(count)$('uncertainties').focus();else $('referenceConfirmed').focus()}
$('saveReference').onclick=()=>action(async()=>{try{if(!referenceHeard)throw Error('Эхлээд хадгалсан бичлэгээ бүтнээр тоглуулж сонсоно уу.');const result=await api('/api/task/reference',{session_id:sid,task_id:taskId,audio_sha256:recordingSha,reference:$('reference').value,uncertainties:$('uncertainties').value.split('\n').map(x=>x.trim()).filter(Boolean),listened:referenceHeard,playback_ended:referenceHeard,confirmed:$('referenceConfirmed').checked});if(!result.reference_confirmed_before_asr){pendingReferenceHelp(result.unresolved_count);return}$('reference').disabled=true;$('uncertainties').disabled=true;$('referenceConfirmed').disabled=true;$('saveReference').disabled=true;$('recognize').disabled=false;referenceFeedback('Reference батлагдаж хадгалагдсан. «Google руу илгээж Gemini-ээр таних» товч нээгдлээ.');status('Сонсож баталсан текст хадгалагдлаа. Одоо ганц Gemini горимоор туршиж болно.');$('recognize').scrollIntoView({block:'center',behavior:'smooth'});}catch(error){referenceFeedback(error.message,true);throw error}});
$('recognize').onclick=()=>action(async()=>{$('recognize').disabled=true;$('recordStatus').textContent='Gemini 3.5 Live дууг таньж байна…';const v=await api('/api/task/transcribe',{session_id:sid,task_id:taskId,cloud_audio_consent:true});renderMeasurement(v.measurement);$('raw').textContent='Анхны STT: '+v.text;$('edited').value=v.text;$('rawSend').disabled=!v.text;$('editedSend').disabled=false;$('recordStatus').textContent='Анхны танилт хадгалагдсан. Өмнө баталсан reference тусдаа хэвээр.'});
$('upload').onchange=()=>action(async()=>{const f=$('upload').files[0];if(f)await capture(f)});
$('record').onclick=()=>action(async()=>{if(recordingSaving)return;stream=await navigator.mediaDevices.getUserMedia({audio:true});const chunks=[];recording=new MediaRecorder(stream);recording.ondataavailable=e=>{if(e.data.size)chunks.push(e.data)};recording.onstop=()=>{clearInterval(recordingClock);stream.getTracks().forEach(t=>t.stop());saveStoppedRecording(new Blob(chunks,{type:recording.mimeType}));};recording.start();const started=Date.now();const tick=()=>{const seconds=Math.floor((Date.now()-started)/1000);$('recordStatus').textContent=`Бичиж байна: ${seconds} секунд. Нэг асуултыг 5–15 секундэд хэлээд зогсооно уу. Дээд хязгаар 30 секунд.`;$('recordStatus').className=seconds>=25?'error':''};tick();recordingClock=setInterval(tick,1000);$('record').disabled=true;$('stop').disabled=false;});
$('stop').onclick=()=>{if(recording?.state==='recording'){recording.stop();$('stop').disabled=true}};
$('nextTask').onclick=()=>{if(recording?.state==='recording'||recordingSaving){status('Эхлээд бичлэгийг зогсоож хадгална уу.',true);return}if(busy)return;if(stream)stream.getTracks().forEach(t=>t.stop());sessionStorage.setItem('humanTrialNewTask:'+sid,'1');location.reload()};
function renderResult(value){const box=el('article',undefined,$('taskResults'));el('h3',value.condition,box);el('p',value.answer||'Систем эхтэй хариулт өгөөгүй / тодруулга шаардсан.',box);const audio=el('audio',undefined,box);audio.controls=true;let listened=false;audio.onended=()=>{listened=true};const speak=el('button','Энэ хариуг сонсох (онлайн TTS)',box);speak.onclick=()=>action(async()=>{const v=await api('/api/task/speak',{session_id:sid,task_id:taskId,condition:value.condition});audio.src=v.audio_url;await audio.play()});const success=rating(box,'Таны асуух гэсэн зүйлийг шийдэж чадсан уу?',[['yes','Тийм'],['partial','Хэсэгчлэн'],['no','Үгүй']]);const l=el('label','Та хариултаас юу ойлгов? (сонссон бол сонссон зүйлээ)',box),heard=el('textarea',undefined,l);const int=rating(box,'Сонссон бол ойлгомж 1–5',scale),nat=rating(box,'Сонссон бол жам ёсны байдал 1–5',scale),n=el('label','Тэмдэглэл',box),notes=el('textarea',undefined,n);const save=el('button','Энэ нөхцөлийн ажиглалтыг хадгалах',box);save.onclick=()=>action(async()=>{await api('/api/task/observe',{session_id:sid,task_id:taskId,condition:value.condition,task_success:success.value,heard_answer:heard.value,tts_listened:listened,intelligibility:listened?Number(int.value):null,naturalness:listened?Number(nat.value):null,notes:notes.value});save.disabled=true;status('Бодит даалгаврын ажиглалт хадгалагдлаа.')});if(value.observation_saved)save.disabled=true;}
window.addEventListener('pagehide',()=>{clearInterval(recordingClock);if(stream)stream.getTracks().forEach(t=>t.stop())});(async()=>{try{await refresh();if(sid){$('start').classList.add('hidden');$('workspace').classList.remove('hidden');if(sessionStorage.getItem('humanTrialNewTask:'+sid)!=='1')restoreTask(state.active_task);status('Өмнөх session-ийн хадгалсан үнэлгээг үргэлжлүүлж байна.')}}catch(e){status(e.message+' Хадгалсан session-ийг устгаагүй. Холболт сэргэсний дараа хуудсаа дахин ачаална уу.',true)}})();
</script></html>'''


def make_server(trial, port=8790):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *args):
            pass

        def send(self, code, value=None, mime='application/json; charset=utf-8'):
            raw = value if isinstance(value, bytes) else json.dumps(value or {}, ensure_ascii=False).encode()
            self.send_response(code)
            for key, value in [('Content-Type', mime), ('Content-Length', str(len(raw))),
                    ('Cache-Control', 'no-store'), ('Connection', 'close'), ('Referrer-Policy', 'no-referrer'),
                    ('X-Content-Type-Options', 'nosniff'), ('X-Frame-Options', 'DENY'),
                    ('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")]:
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(raw)
            self.close_connection = True

        def valid(self, post=False):
            self.connection.settimeout(10)
            host = f'127.0.0.1:{self.server.server_port}'
            if (self.headers.get_all('Host', []) != [host] or len(self.headers.get_all('Origin', [])) > 1
                    or self.headers.get('Origin') not in {None, 'http://' + host}
                    or self.headers.get('Sec-Fetch-Site') == 'cross-site'):
                self.send(403, {'error': 'Local same-origin trial only.'}); return False
            lengths = self.headers.get_all('Content-Length', [])
            if self.headers.get_all('Transfer-Encoding', []) or len(lengths) > 1:
                self.send(400, {'error': 'Invalid request framing.'}); return False
            if not post and lengths and not re.fullmatch(r'0+', lengths[0]):
                self.send(400, {'error': 'GET requests cannot contain a body.'}); return False
            if post:
                supplied = self.headers.get('X-Trial-Token', '')
                if (self.headers.get('Origin') != 'http://' + host or not supplied.isascii()
                        or not secrets.compare_digest(supplied, trial.token)):
                    self.send(403, {'error': 'Require local Origin and trial token.'}); return False
            return True

        def do_GET(self):
            if not self.valid(): return
            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query)
            sid = query.get('session_id', [None])[0]
            try:
                if parsed.path == '/':
                    return self.send(200, PAGE.encode(), 'text/html; charset=utf-8')
                if parsed.path == '/api/state':
                    return self.send(200, trial.state(sid))
                if parsed.path == '/api/reveal':
                    return self.send(200, dict(references=trial.reveal(sid)))
                if re.fullmatch('/api/listening/audio/[0-9a-f]{24}', parsed.path):
                    return self.send(200, trial.audio(parsed.path.rsplit('/', 1)[1]), 'audio/mpeg')
                if re.fullmatch('/api/voice-audio/[0-9a-f]{32}', parsed.path):
                    return self.send(200, trial.voice_audio(sid, parsed.path.rsplit('/', 1)[1]), 'audio/mpeg')
                if re.fullmatch('/api/task-recording/[0-9a-f]{32}', parsed.path):
                    raw, mime = trial.recording_audio(sid, parsed.path.rsplit('/', 1)[1])
                    return self.send(200, raw, mime)
                self.send(404, {'error': 'Unknown trial resource.'})
            except TrialConflict as error:
                self.send(409, {'error': str(error)})
            except KeyError:
                self.send(404, {'error': 'Unknown study session or sample.'})
            except (ValueError, OSError) as error:
                self.send(400, {'error': str(error)})

        def do_POST(self):
            if not self.valid(post=True): return
            try:
                length = self.headers.get('Content-Length', '')
                audio = self.path == '/api/task/record'
                if not re.fullmatch(r'[0-9]{1,8}', length) or not 1 <= int(length) <= (MAX_AUDIO if audio else 32768):
                    raise ValueError('Invalid body size.')
                raw = self.rfile.read(int(length))
                if len(raw) != int(length):
                    raise ValueError('Incomplete request body.')
                if audio:
                    result = trial.capture_recording(self.headers.get('X-Session-Id'), self.headers.get('X-Task-Id'),
                        raw, self.headers.get_content_type())
                else:
                    if self.headers.get_content_type() != 'application/json':
                        raise ValueError('JSON is required.')
                    body = json.loads(raw)
                    methods = {'/api/start': trial.start, '/api/review': trial.review, '/api/listen': trial.listen,
                        '/api/task/begin': trial.begin_task, '/api/task/route': trial.route,
                        '/api/task/reference': trial.confirm_reference, '/api/task/transcribe': trial.recognize,
                        '/api/task/speak': trial.speak, '/api/task/observe': trial.observe}
                    if self.path not in methods:
                        return self.send(404, {'error': 'Unknown trial action.'})
                    result = methods[self.path](body)
                self.send(200, result)
            except TrialConflict as error:
                self.send(409, {'error': str(error)})
            except KeyError:
                self.send(404, {'error': 'Unknown study session or item.'})
            except (ValueError, TypeError, OSError) as error:
                self.send(400, {'error': str(error)})

    class Server(ThreadingHTTPServer):
        daemon_threads = True

        def get_request(self):
            connection, address = super().get_request()
            connection.settimeout(10)
            return connection, address
    return Server(('127.0.0.1', port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--audio-results', type=Path,
        default=ROOT/'runtime/delivery-implementation-20261020/voice/paired-audio/results.json')
    parser.add_argument('--review-file', type=Path,
        default=ROOT/'runtime/quality-media-20261021/llm-comparison/human-review-v2.json')
    parser.add_argument('--port', type=int, default=8790)
    parser.add_argument('--resume', action='store_true', help='Validate and resume the existing immutable event journal.')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('Use a valid local port.')
    trial = HumanTrial(args.run_dir, args.audio_results, args.review_file, resume=args.resume)
    with make_server(trial, args.port) as server:
        print(f'Human trial: http://127.0.0.1:{server.server_port}/', flush=True)
        server.serve_forever()


if __name__ == '__main__':
    main()
