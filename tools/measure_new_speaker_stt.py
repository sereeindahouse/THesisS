"""New-speaker Gemini study. Bare invocation is OFFLINE; cloud requires --execute.

Only private runtime/stt-new-speakers-<date>/ manifests are accepted. Dry-run
reads consented WAVs locally, never credentials or a transport. Future execution
reserves each clip/arm durably before dispatch; resume never repeats an attempt.
"""
from __future__ import annotations
import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import date, datetime, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import sys
import time
from uuid import uuid4
import wave

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
from audio_preprocess import clean_wav
from score import normalize
from tools.compare_stt_candidate import CandidateError, GeminiTransport, validate_vocabulary, sanitized_error
from tools.new_speaker_stt_scoring import ARMS, MODEL, summarize

CODE = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}')
MAX_CLIPS, MAX_WAV_BYTES, MAX_MANIFEST_BYTES = 300, 8 * 1024 * 1024, 2 * 1024 * 1024
LEGACY_MANIFEST = 'runtime/stt-candidate-20261029/manifest.json'
BIND_CODE = ('tools/measure_new_speaker_stt.py', 'tools/new_speaker_stt_scoring.py',
    'tools/evaluate_gemini_stt_offline.py', 'tools/stt_normalization_metrics.py',
    'tools/compare_stt_vocabulary.py', 'tools/compare_stt_candidate.py',
    'audio_preprocess.py', 'stt_text_normalization.py', 'score.py')


class StudyError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class PrivateArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's default echoes unknown arguments, possibly a pasted key.
        raise StudyError('invalid_arguments_use_help')


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n').encode('utf-8')


def _read_json(path, limit=MAX_MANIFEST_BYTES):
    try:
        raw = Path(path).read_bytes()
        if len(raw) > limit:
            raise StudyError('json_too_large')
        return json.loads(raw.decode('utf-8-sig')), raw
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise StudyError('invalid_json_file') from None


def _write_new(path, value):
    with Path(path).open('xb') as stream:
        stream.write(_bytes(value))
        stream.flush()
        os.fsync(stream.fileno())


def _check_artifact(path):
    path=Path(path)
    if (path.is_symlink() or path.resolve() != path.absolute() or
            path.exists() and (not path.is_file() or path.stat().st_nlink > 1)):
        raise StudyError('unsafe_private_artifact_path')
    return path


def _check_output(output):
    output=Path(output)
    if (output.is_symlink() or output.resolve() != output.absolute() or
            output.exists() and not output.is_dir()):
        raise StudyError('unsafe_private_output_path')
    for name in ('run.lock','protocol.json','manifest-snapshot.json','attempts.jsonl',
                 'attempt-state.json','scores-private.json','summary.json'):
        _check_artifact(output/name)
    return output


def _replace_derived(path, value):
    path = _check_artifact(path)
    temporary = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
    try:
        _write_new(temporary, value)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _manifest_path(root, value):
    root = Path(root).resolve()
    supplied = root / value
    path = supplied.resolve()
    if (supplied.is_symlink() or path.name != 'manifest.json' or
            path.parent.parent != root / 'runtime' or
            not re.fullmatch(r'stt-new-speakers-(?:\d{8}|\d{4}-\d{2}-\d{2})', path.parent.name)):
        raise StudyError('manifest_must_be_new_speaker_runtime_bundle')
    stamp = path.parent.name.removeprefix('stt-new-speakers-')
    try:
        date.fromisoformat(stamp if '-' in stamp else stamp[:4]+'-'+stamp[4:6]+'-'+stamp[6:])
    except ValueError:
        raise StudyError('invalid_study_date') from None
    return path


def _wav(path):
    try:
        size = path.stat().st_size
        if not 0 < size <= MAX_WAV_BYTES:
            raise StudyError('wav_size_out_of_range')
        data = path.read_bytes()
        if len(data) != size:
            raise StudyError('audio_changed_during_read')
        with wave.open(io.BytesIO(data), 'rb') as source:
            rate, frames = source.getframerate(), source.getnframes()
            if (source.getcomptype() != 'NONE' or source.getnchannels() != 1 or
                    source.getsampwidth() != 2 or not 8000 <= rate <= 48000):
                raise StudyError('require_pcm16_mono_wav_8_to_48khz')
            duration = frames / rate
            if not .5 <= duration <= 30:
                raise StudyError('require_half_to_thirty_seconds')
            pcm = source.readframes(frames)
            if len(pcm) != frames * 2:
                raise StudyError('truncated_wav')
        cleaned, report = clean_wav(data)
        return data, cleaned, dict(audio_sha256=_sha(data), cleaned_sha256=_sha(cleaned),
            audio_bytes=len(data), cleaned_bytes=len(cleaned), sample_rate=rate,
            frames=frames, seconds=duration, cleanup=report)
    except StudyError:
        raise
    except (OSError, ValueError, EOFError, wave.Error):
        raise StudyError('invalid_wav_file') from None


def _legacy_hashes(root):
    path = root / LEGACY_MANIFEST
    if not path.exists():
        return set(), None
    value, raw = _read_json(path)
    try:
        rows = value['human_rows']
        if not isinstance(rows,list) or not rows or any(not isinstance(row,dict) for row in rows):
            raise ValueError()
        hashes = {row['audio_sha256'] for row in rows}
        if not isinstance(rows, list) or any(not isinstance(h, str) or not re.fullmatch(r'[0-9a-f]{64}', h) for h in hashes):
            raise ValueError()
        return hashes, _sha(raw)
    except (KeyError, TypeError, ValueError):
        raise StudyError('legacy_hash_metadata_invalid') from None


def capture(manifest, *, root=ROOT):
    """Validate one new bundle; raw bytes are not retained or printed."""
    root = Path(root).resolve()
    path = _manifest_path(root, manifest)
    value, raw = _read_json(path)
    if (not isinstance(value, dict) or type(value.get('schema_version')) is not int or
            value['schema_version'] != 1 or not isinstance(value.get('clips'), list) or
            not 1 <= len(value['clips']) <= MAX_CLIPS or
            type(value.get('new_speakers_confirmed', False)) is not bool):
        raise StudyError('invalid_manifest_schema')
    rows, ids = [], set()
    for original in value['clips']:
        if not isinstance(original, dict):
            raise StudyError('invalid_clip_record')
        for key in ('clip_id','speaker_code','question_id'):
            if not isinstance(original.get(key), str) or not CODE.fullmatch(original[key]):
                raise StudyError('require_pseudonymous_identifiers')
        if original['clip_id'].casefold() in ids:
            raise StudyError('duplicate_clip_id')
        ids.add(original['clip_id'].casefold())
        if original.get('consent') is not True:
            raise StudyError('consent_required')
        reference = original.get('reference_text')
        if (not isinstance(reference, str) or not 0 < len(reference) <= 1000 or
                not normalize(reference) or not any(c.isalnum() for c in reference) or
                any(ord(c) < 32 and c not in '\n\r\t' for c in reference)):
            raise StudyError('nonempty_bounded_reference_required')
        audio_path = original.get('audio_path')
        if not isinstance(audio_path, str) or not audio_path or Path(audio_path).is_absolute():
            raise StudyError('relative_audio_path_required')
        audio = (path.parent / audio_path).resolve()
        if not audio.is_relative_to(path.parent) or audio.suffix.casefold() != '.wav' or not audio.is_file():
            raise StudyError('audio_must_be_inside_new_study')
        rows.append(dict(original, _audio=audio))
    speakers = {r['speaker_code'] for r in rows}
    if len({s.casefold() for s in speakers}) != len(speakers):
        raise StudyError('speaker_codes_differ_only_by_case')
    known, legacy_hash = _legacy_hashes(root)
    seen_audio = set()
    for row in rows:
        _, _, metadata = _wav(row['_audio'])
        digest = metadata['audio_sha256']
        if digest in known:
            raise StudyError('legacy_audio_cannot_be_a_new_speaker')
        if digest in seen_audio:
            raise StudyError('duplicate_audio_in_study')
        seen_audio.add(digest)
        row['audio_metadata'] = metadata
    vocabulary, vocabulary_raw = _read_json(root / 'config/stt-vocabulary.json')
    if vocabulary.get('model') != MODEL:
        raise StudyError('vocabulary_model_mismatch')
    try:
        terms = validate_vocabulary(vocabulary['terms'])
    except (KeyError, ValueError):
        raise StudyError('invalid_vocabulary') from None
    try:
        summarize(rows, [], terms)
    except ValueError:
        raise StudyError('invalid_reference_annotations') from None
    code = {name:_sha((root/name).read_bytes()) for name in BIND_CODE}
    schedule, positions = [], Counter()
    for row in rows:
        order = ARMS if positions[row['speaker_code']] % 2 == 0 else tuple(reversed(ARMS))
        positions[row['speaker_code']] += 1
        schedule.extend(dict(clip_id=row['clip_id'], speaker_code=row['speaker_code'], arm=arm) for arm in order)
    public_rows = [{k:v for k,v in row.items() if k != '_audio'} for row in rows]
    plan = dict(schema_version=1, model=MODEL, manifest_sha256=_sha(raw),
        rows_sha256=_sha(_bytes(public_rows)), vocabulary_sha256=_sha(vocabulary_raw),
        terms_sha256=_sha(_bytes(terms)), code_sha256=code, legacy_metadata_sha256=legacy_hash,
        new_speakers_confirmed=value.get('new_speakers_confirmed', False),
        max_transcription_attempts=len(rows)*2, max_http_requests=len(rows)*8,
        schedule=schedule, automatic_retry=False, paid_fallback=False,
        service_tier='operator_confirmed_free_only', cost_budget_usd=0,
        speaker_identity='operator_attestation_not_biometric_verification')
    if _sha(path.read_bytes()) != plan['manifest_sha256']:
        raise StudyError('manifest_changed_during_capture')
    return dict(root=root, manifest=path, manifest_raw=raw, rows=rows, terms=terms, plan=plan,
                output=_check_output(path.parent/'measurement'))


def dry_report(captured):
    plan, rows = captured['plan'], captured['rows']
    return dict(dry_run=True, model=MODEL, clips=len(rows), speaker_codes=len({r['speaker_code'] for r in rows}),
        clips_per_speaker=dict(Counter(r['speaker_code'] for r in rows)),
        max_transcription_attempts=plan['max_transcription_attempts'], max_http_requests=plan['max_http_requests'],
        vocabulary_terms=len(captured['terms']), total_audio_seconds=round(sum(r['audio_metadata']['seconds'] for r in rows),3),
        ready_for_future_execute=plan['new_speakers_confirmed'],
        cloud_execution_authorized=False, account_tier_independently_verified=False,
        known_legacy_hash_metadata_available=plan['legacy_metadata_sha256'] is not None,
        new_speaker_identity_verified=False, network_calls=0, credential_reads=0, config_changed=False)


@contextmanager
def run_lock(output):
    """OS lock is released after process death; no stale-PID lock deletion."""
    output=_check_output(output)
    output.mkdir(parents=True, exist_ok=True)
    stream = (output/'run.lock').open('a+b')
    locked = False
    try:
        if stream.seek(0,2) == 0:
            stream.write(b'\0'); stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError:
            raise StudyError('study_is_already_running') from None
        yield
    finally:
        if locked:
            stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()


def _append(path, value):
    path=_check_artifact(path)
    with path.open('ab') as stream:
        stream.write((json.dumps(value,ensure_ascii=False,allow_nan=False)+'\n').encode('utf-8'))
        stream.flush()
        os.fsync(stream.fileno())


def load_journal(path, plan):
    path=_check_artifact(path)
    if not path.exists():
        return [], []
    raw = path.read_bytes()
    if len(raw) > 32*1024*1024 or raw and not raw.endswith(b'\n'):
        raise StudyError('journal_corrupt_do_not_retry')
    starts, finishes, done, stopped = [], [], set(), set()
    try:
        events = [json.loads(line) for line in raw.decode('utf-8').splitlines()]
        for event in events:
            sequence = event['attempt']
            if type(sequence) is not int or not 1 <= sequence <= len(plan['schedule']):
                raise ValueError()
            expected = plan['schedule'][sequence-1]
            if any(event.get(k) != v for k,v in expected.items()):
                raise ValueError()
            if event['event'] == 'start':
                if sequence != len(starts)+1 or event['invocation'] in stopped:
                    raise ValueError()
                starts.append(event)
            elif event['event'] == 'finish':
                if sequence > len(starts) or sequence in done or event['invocation'] != starts[sequence-1]['invocation']:
                    raise ValueError()
                done.add(sequence); finishes.append(event)
                if event.get('stop'):
                    stopped.add(event['invocation'])
            else:
                raise ValueError()
    except (ValueError, KeyError, TypeError, UnicodeError):
        raise StudyError('journal_corrupt_do_not_retry') from None
    return starts, finishes


def _real_factory(terms):
    # This function is NEVER called by dry-run or fake-transport tests.
    key = os.environ.get('GEMINI_API_KEY')
    if not key:
        from gemini_credentials import WindowsCredentialStore
        saved = WindowsCredentialStore(ROOT/'runtime/gemini-credentials.dpapi').load()
        key = saved.get('api_key') if isinstance(saved,dict) else None
    if not key:
        raise StudyError('gemini_key_missing')
    return lambda: GeminiTransport(key,vocabulary=terms)


def _partial(value):
    if not isinstance(value,dict):
        return None
    return {k:value.get(k) for k in ('text','model','usage','cleanup')}


def _has_429(code, value):
    return code == 'http_429' or (isinstance(value,dict) and isinstance(value.get('cleanup'),dict)
                                 and value['cleanup'].get('error') == 'http_429')


def _save_scores(captured, finishes, starts, stopped, injected):
    scored = summarize(captured['rows'], finishes, captured['terms'])
    report = dict(scored['summary'], stopped=stopped, attempts_reserved=len(starts),
        unfinished_attempts=len(starts)-len(finishes),
        max_transcription_attempts=captured['plan']['max_transcription_attempts'],
        http_requests=sum(r.get('http_requests',0) for r in finishes),
        http_requests_complete=len(starts)==len(finishes),
        http_requests_upper_bound=sum(r.get('http_requests',0) for r in finishes)+4*(len(starts)-len(finishes)),
        max_http_requests=captured['plan']['max_http_requests'],
        schedule_exhausted=len(starts)==len(captured['plan']['schedule']),
        completed=stopped is None and sum(isinstance(r.get('text'),str) and not r.get('error') for r in finishes)==len(captured['plan']['schedule']),
        automatic_retry=False, paid_fallback=False, config_changed=False,
        transport_kind='injected_transport' if injected else 'gemini',
        account_tier_independently_verified=False,
        new_speaker_identity_verified=False,
        new_speakers_operator_confirmed=captured['plan']['new_speakers_confirmed'])
    _replace_derived(captured['output']/'scores-private.json',scored['private_rows'])
    _replace_derived(captured['output']/'summary.json',report)
    return report


def _attempt_state(output, plan, reserved):
    _replace_derived(output/'attempt-state.json',dict(reserved=reserved,protocol_sha256=_sha(_bytes(plan))))


def _verify_captured(captured):
    root=captured['root']; plan=captured['plan']
    manifest=_manifest_path(root,captured['manifest'])
    if captured['output'] != manifest.parent/'measurement':
        raise StudyError('private_study_output_required')
    rows=[{k:v for k,v in row.items() if k != '_audio'} for row in captured['rows']]
    if (_sha(_bytes(rows)) != plan['rows_sha256'] or _sha(_bytes(captured['terms'])) != plan['terms_sha256'] or
            _sha(manifest.read_bytes()) != plan['manifest_sha256'] or
            _sha(captured['manifest_raw']) != plan['manifest_sha256'] or
            _sha((root/'config/stt-vocabulary.json').read_bytes()) != plan['vocabulary_sha256'] or
            any(_sha((root/name).read_bytes()) != digest for name,digest in plan['code_sha256'].items())):
        raise StudyError('captured_inputs_or_code_changed')


def execute(captured, *, transport_factory=None, resume=False, free_tier_confirmed=False,
            pause=5.0, sleeper=time.sleep):
    """Future cloud run, or injected fake in tests. Each reservation is single-use."""
    if not captured['plan']['new_speakers_confirmed']:
        raise StudyError('new_speakers_operator_confirmation_required')
    if not math.isfinite(pause) or not 0 <= pause <= 60:
        raise StudyError('pause_out_of_range')
    injected = transport_factory is not None
    if not injected and free_tier_confirmed is not True:
        raise StudyError('free_tier_confirmation_required')
    _verify_captured(captured)
    output = _check_output(captured['output'])
    if output.exists() and not resume:
        raise StudyError('existing_run_requires_resume')
    if resume and not output.exists():
        raise StudyError('resume_run_missing')
    with run_lock(output):
        protocol_path = output/'protocol.json'
        if resume:
            old,_ = _read_json(protocol_path, 8*1024*1024)
            if old != captured['plan']:
                raise StudyError('resume_inputs_or_code_changed')
            if (output/'manifest-snapshot.json').read_bytes() != captured['manifest_raw']:
                raise StudyError('resume_manifest_changed')
        else:
            _write_new(protocol_path,captured['plan'])
            with (output/'manifest-snapshot.json').open('xb') as stream:
                stream.write(captured['manifest_raw']); stream.flush(); os.fsync(stream.fileno())
            _attempt_state(output,captured['plan'],0)
        starts, finishes = load_journal(output/'attempts.jsonl',captured['plan'])
        state,_ = _read_json(output/'attempt-state.json')
        if (not isinstance(state,dict) or type(state.get('reserved')) is not int or
                not 0 <= state['reserved'] <= len(captured['plan']['schedule']) or
                state.get('protocol_sha256') != _sha(_bytes(captured['plan'])) or
                state['reserved'] > len(starts)):
            raise StudyError('journal_reservations_missing_do_not_retry')
        # A crash between the durable journal append and counter update leaves
        # a reserved start. Count it and skip it; it never authorizes a retry.
        if state['reserved'] < len(starts):
            _attempt_state(output,captured['plan'],len(starts))
        # Credentials are loaded only after all offline input/protocol checks.
        factory = transport_factory
        if factory is None and len(starts) < len(captured['plan']['schedule']):
            factory = _real_factory(captured['terms'])
        by_id = {r['clip_id']:r for r in captured['rows']}
        invocation, stopped = uuid4().hex, None
        for item in captured['plan']['schedule'][len(starts):]:
            row = by_id[item['clip_id']]
            if pause and starts:
                sleeper(pause)
            data, cleaned, metadata = _wav(row['_audio'])
            if metadata != row['audio_metadata']:
                raise StudyError('audio_changed_before_dispatch')
            if _sha(captured['manifest'].read_bytes()) != captured['plan']['manifest_sha256']:
                raise StudyError('consent_or_reference_changed_before_dispatch')
            start = dict(event='start',attempt=len(starts)+1,invocation=invocation,**item,
                         started_utc=datetime.now(timezone.utc).isoformat())
            _append(output/'attempts.jsonl',start)
            starts.append(start)
            _attempt_state(output,captured['plan'],len(starts))
            finish = dict(start,event='finish')
            began, transport, before_http = time.perf_counter(), None, 0
            try:
                transport = factory()
                before_http = getattr(transport,'network_calls',0)
                neutral = 'clip-'+_sha(item['clip_id'].encode())[:16]+'-'+('clean' if item['arm']==ARMS[1] else 'raw')
                value = transport.transcribe(cleaned if item['arm']==ARMS[1] else data,display_name=neutral)
                if (not isinstance(value,dict) or not isinstance(value.get('text'),str) or
                        len(value['text']) > 20000 or value.get('model') != MODEL):
                    raise CandidateError('invalid_transcription_result',_partial(value))
                cleanup = value.get('cleanup')
                if isinstance(cleanup,dict) and cleanup.get('deleted') is False:
                    raise CandidateError('uploaded_file_cleanup_failed',_partial(value))
                finish.update(text=value['text'],model=MODEL,usage=value.get('usage'),cleanup=cleanup)
            except BaseException as error:
                code = sanitized_error(error)
                partial = _partial(error.partial_result) if isinstance(error,CandidateError) else None
                finish.update(error=code,partial_result=partial)
                if _has_429(code,partial):
                    stopped='http_429'
                elif code in {'interrupted','uploaded_file_cleanup_failed'}:
                    stopped=code
            finish['http_requests'] = max(0,getattr(transport,'network_calls',0)-before_http) if transport else 0
            finish['elapsed_seconds'] = round(time.perf_counter()-began,6)
            if finish['http_requests'] > 4:
                stopped='transport_http_budget_violation'
            if stopped:
                finish['stop']=stopped
            _append(output/'attempts.jsonl',finish)
            finishes.append(finish)
            if stopped:
                break
        if _sha(captured['manifest'].read_bytes()) != captured['plan']['manifest_sha256']:
            stopped='manifest_changed_after_dispatch'
        return _save_scores(captured,finishes,starts,stopped,injected)


def main(argv=None):
    parser=PrivateArgumentParser(description=__doc__)
    parser.add_argument('--manifest',required=True)
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run',action='store_true')
    mode.add_argument('--execute',action='store_true')
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--free-tier-confirmed',action='store_true')
    parser.add_argument('--pause',type=float,default=5.0)
    try:
        args=parser.parse_args(argv)
        captured=capture(args.manifest,root=ROOT)
        if not args.execute:
            report=dry_report(captured)
            if args.resume:
                old,_=_read_json(captured['output']/'protocol.json',8*1024*1024)
                if old != captured['plan']:
                    raise StudyError('resume_inputs_or_code_changed')
                starts,_=load_journal(captured['output']/'attempts.jsonl',captured['plan'])
                report['attempts_already_reserved']=len(starts)
        else:
            report=execute(captured,resume=args.resume,free_tier_confirmed=args.free_tier_confirmed,pause=args.pause)
        print(json.dumps(report,ensure_ascii=False,allow_nan=False))
        return 0 if not args.execute or report['completed'] else 2
    except (Exception,KeyboardInterrupt) as error:
        code=error.code if isinstance(error,StudyError) else 'interrupted' if isinstance(error,KeyboardInterrupt) else 'study_failed'
        print(json.dumps(dict(error=code,error_type=type(error).__name__,transcripts_printed=False)))
        return 1


if __name__=='__main__':
    raise SystemExit(main())
