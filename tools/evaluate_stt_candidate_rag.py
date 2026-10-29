"""Frozen typed/raw downstream comparison, separate from speech providers.

prepare is entirely offline. run calls only the existing loopback /api/route,
never a voice, correction, TTS, admin, training or external provider endpoint.
Human correctness remains pending until a separately bound review is supplied.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = 'http://127.0.0.1:8765'
ARMS = ('typed', 'baseline_raw', 'candidate_raw')
MAX_ROUTE_CALLS = 39
TIMEOUT_SECONDS = 60
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
RAG_CODES = ('rag_runtime.py', 'source_fields.py', 'website_retrieval.py', 'sqlite_retrieval.py')
CORPORA = ('CORE/database/website.db', 'runtime/content.db')
SOURCE_FILES = ('protocol.json', 'run.json', 'manifest-snapshot.json', 'results.jsonl', 'rag-inputs.json')


def _now():
    return datetime.now(timezone.utc).isoformat()


def _valid_utc(value):
    if not isinstance(value, str):
        return False
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return False
    return stamp.utcoffset() is not None and stamp.utcoffset().total_seconds() == 0


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n').encode('utf-8')


def _private(root, value):
    path = Path(value)
    path = (path if path.is_absolute() else root / path).resolve()
    if not path.is_relative_to((root / 'runtime').resolve()):
        raise ValueError('Evaluation paths must remain inside project runtime/.')
    return path


def _read(path):
    raw = path.read_bytes()
    if len(raw) > MAX_JSON_BYTES:
        raise ValueError('Evidence file exceeds the bounded size.')
    value = json.loads(raw.decode('utf-8-sig'))
    if not isinstance(value, dict):
        raise ValueError('Expected a JSON evidence object.')
    return value


def _write(path, value):
    with path.open('xb') as stream:
        stream.write(_bytes(value))


def _code_sha():
    return sha(Path(__file__))


def _check_binding(root, binding):
    if (not isinstance(binding, dict) or set(binding) != {'code_sha256', 'corpus_sha256'}
            or not isinstance(binding['code_sha256'], dict)
            or not isinstance(binding['corpus_sha256'], dict)
            or set(binding['code_sha256']) != set(RAG_CODES)
            or set(binding['corpus_sha256']) != set(CORPORA)):
        raise ValueError('Require the exact four-code/two-corpus RAG binding.')
    for mapping in binding.values():
        for name, expected in mapping.items():
            path = (root / name).resolve()
            if not path.is_relative_to(root) or not path.is_file() or sha(path) != expected:
                raise ValueError('Frozen RAG code or corpus changed.')


def load_inputs(stt_run, *, root=ROOT):
    """Validate completed source evidence and every typed/raw/audio association."""
    root = Path(root).resolve()
    source = _private(root, stt_run)
    fingerprint = {name: sha(source / name) for name in SOURCE_FILES}
    protocol, state, manifest, inputs = [_read(source / name) for name in
        ('protocol.json', 'run.json', 'manifest-snapshot.json', 'rag-inputs.json')]
    if not all(isinstance(value, dict) for value in (protocol, state, manifest, inputs)):
        raise ValueError('Speech evidence must contain JSON objects.')
    if (not isinstance(state, dict) or state.get('completed') is not True
            or state.get('error') or state.get('model') != 'gemini-3.5-transcribe'
            or protocol.get('model') != 'gemini-3.5-transcribe'
            or state.get('protocol_sha256') != fingerprint['protocol.json']
            or state.get('manifest_sha256') != fingerprint['manifest-snapshot.json']
            or state.get('results_sha256') != fingerprint['results.jsonl']
            or protocol.get('manifest_sha256') != fingerprint['manifest-snapshot.json']):
        raise ValueError('A complete, internally bound speech run is required.')
    if (not isinstance(inputs, dict) or inputs.get('schema_version') != 1
            or inputs.get('protocol_sha256') != fingerprint['protocol.json']
            or inputs.get('run_sha256') != fingerprint['run.json']
            or inputs.get('results_sha256') != fingerprint['results.jsonl']):
        raise ValueError('RAG inputs do not match the speech run.')
    humans, controls = manifest.get('human_rows'), manifest.get('control_rows')
    if (not isinstance(humans, list) or not 1 <= len(humans) <= 13
            or not isinstance(controls, list) or len(controls) > 2):
        raise ValueError('Require 1–13 human rows and at most two excluded controls.')
    if any(not isinstance(row, dict) or row.get('reference_status') != 'eligible_speaker_confirmed'
           for row in humans):
        raise ValueError('Human references must be explicitly speaker-confirmed.')
    raw = (source / 'results.jsonl').read_bytes()
    if len(raw) > MAX_JSON_BYTES:
        raise ValueError('Speech results exceed the bounded size.')
    results = [json.loads(line) for line in raw.decode('utf-8').splitlines()]
    expected = humans + controls
    ids = [row.get('id') for row in expected if isinstance(row, dict)]
    if (not all(isinstance(row, dict) for row in results)
            or len(ids) != len(expected) or any(not isinstance(value, str) or not value for value in ids)
            or len({value.casefold() for value in ids}) != len(ids)
            or [row.get('id') for row in results] != ids):
        raise ValueError('Speech result IDs are missing, duplicated or reordered.')
    rows = inputs.get('rows')
    if (not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows)
            or [row.get('id') for row in rows] != ids[:len(humans)]):
        raise ValueError('RAG rows must match the human cohort exactly.')
    for original, result in zip(expected, results):
        if (result.get('error') or original.get('audio_sha256') != result.get('audio_sha256')
                or not isinstance(original.get('audio_sha256'), str)
                or len(original['audio_sha256']) != 64
                or any(not isinstance(result.get(arm), dict)
                    or not isinstance(result[arm].get('text'), str) or result[arm].get('error')
                    for arm in ('baseline', 'candidate'))):
            raise ValueError('Incomplete speech output cannot enter a paired RAG run.')
    for row, original, result in zip(rows, humans, results):
        if (row.get('audio_sha256') != original['audio_sha256']
                or row.get('typed') != original.get('reference')
                or row.get('baseline_raw') != result['baseline']['text']
                or row.get('candidate_raw') != result['candidate']['text']):
            raise ValueError('Typed/raw text or audio provenance changed.')
        for arm in ARMS:
            text = row.get(arm)
            if not isinstance(text, str) or len(text) > 1000 or (arm == 'typed' and not text.strip()):
                raise ValueError('Questions must be bounded strings; never truncate raw transcripts.')
    _check_binding(root, inputs.get('rag_binding'))
    if any(sha(source / name) != digest for name, digest in fingerprint.items()):
        raise ValueError('Speech evidence changed during capture.')
    return dict(source=source, source_sha256=fingerprint, rows=rows, binding=inputs['rag_binding'])


def _rubric(rows, value=None):
    if value is None:
        return dict(schema_version=1, reference_origin=None, reviewer=None,
            reference_confirmed=False, records=[dict(id=row['id'], task_applicable=None,
                answerability=None, required_fields=None, reference_sources=None,
                notes=None) for row in rows])
    if (not isinstance(value, dict) or value.get('schema_version') != 1
            or not isinstance(value.get('records'), list)
            or not all(isinstance(row, dict) for row in value['records'])
            or [row.get('id') for row in value['records']] != [row['id'] for row in rows]):
        raise ValueError('Rubric IDs must match the frozen cohort.')
    for row in value['records']:
        if (row.get('task_applicable') is not None and type(row['task_applicable']) is not bool
                or row.get('answerability') not in (None, 'answerable', 'clarify', 'unsupported', 'non_question')
                or row.get('required_fields') is not None and not isinstance(row['required_fields'], list)
                or row.get('reference_sources') is not None and not isinstance(row['reference_sources'], list)):
            raise ValueError('Invalid task reference rubric.')
        if row.get('answerability') == 'non_question' and row.get('task_applicable') is True:
            raise ValueError('A non-question cannot enter the task-success denominator.')
    return value


def prepare(stt_run, output_dir, *, root=ROOT, rubric_path=None):
    """Freeze source and null-or-reviewed task references without any HTTP."""
    root = Path(root).resolve()
    output = _private(root, output_dir)
    if output.exists():
        raise FileExistsError('Preserve the earlier evaluation packet.')
    captured = load_inputs(stt_run, root=root)
    rubric = _rubric(captured['rows'], _read(_private(root, rubric_path)) if rubric_path else None)
    rubric_bytes = _bytes(rubric)
    protocol = dict(schema_version=1, created_utc=_now(), state='offline_prepared',
        source_run=captured['source'].relative_to(root).as_posix(),
        source_sha256=captured['source_sha256'], evaluator_sha256=_code_sha(),
        rag_binding=captured['binding'], rubric_sha256=hashlib.sha256(rubric_bytes).hexdigest(),
        ids=[row['id'] for row in captured['rows']], arms=list(ARMS),
        base_url=BASE_URL, max_route_calls=MAX_ROUTE_CALLS, timeout_seconds=TIMEOUT_SECONDS,
        automatic_retries=0, allow_draft=False, clarification_ids_used=False,
        human_review_complete=False, route_calls=0, network_calls=0,
        production_provider_changed=False, held_out_evaluation=False)
    output.mkdir(parents=True, exist_ok=False)
    _write(output / 'protocol.json', protocol)
    with (output / 'rubric-snapshot.json').open('xb') as stream:
        stream.write(rubric_bytes)
    _write(output / 'human-review-template.json', dict(schema_version=1,
        protocol_sha256=sha(output / 'protocol.json'), run_sha256=None, results_sha256=None,
        judgments_origin=None, reviewer=None, reviewed_at_utc=None, human_review_complete=False,
        records=[dict(id=row['id'], typed_task_success=None, baseline_task_success=None,
            candidate_task_success=None, notes=None) for row in captured['rows']]))
    return protocol


def validate_url(url):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != 'http' or parsed.netloc != '127.0.0.1:8765'
            or parsed.path not in {'/api/status', '/api/route'} or parsed.query or parsed.fragment
            or parsed.username or parsed.password or any(ord(char) < 33 for char in url)):
        raise ValueError('Only the fixed loopback status/route endpoints are permitted.')
    return url


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Redirects are prohibited.')


class LoopbackTransport:
    def __init__(self, *, opener=None):
        self.opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        self.network_calls = 0

    def request(self, method, path, payload=None):
        if (method, path) not in {('GET', '/api/status'), ('POST', '/api/route')}:
            raise ValueError('Method/endpoint is not permitted.')
        if path == '/api/route' and (not isinstance(payload, dict)
                or set(payload) != {'query', 'allow_draft'} or payload['allow_draft'] is not False):
            raise ValueError('Only a fresh query with allow_draft=false is permitted.')
        url = validate_url(BASE_URL + path)
        request = urllib.request.Request(url, data=_bytes(payload) if payload is not None else None,
            method=method, headers={'Content-Type': 'application/json', 'Origin': BASE_URL})
        self.network_calls += 1
        with self.opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            if hasattr(response, 'geturl') and response.geturl() != url:
                raise ValueError('Redirects are prohibited.')
            if getattr(response, 'status', 200) != 200:
                raise ValueError('Loopback request failed.')
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ValueError('Loopback response exceeds size limit.')
            result = json.loads(raw.decode('utf-8'))
            if not isinstance(result, dict):
                raise ValueError('Expected a JSON object from the loopback server.')
            return result


def _server_fingerprint(root, status, binding):
    if not isinstance(status, dict):
        raise ValueError('Invalid server status.')
    loaded = {}

    def collect(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == 'loaded_artifact_sha256' and isinstance(item, dict):
                    for name, digest in item.items():
                        if name in loaded and loaded[name] != digest:
                            raise ValueError('Conflicting loaded-code fingerprints.')
                        loaded[name] = digest
                else:
                    collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)
    collect(status)
    for name, digest in loaded.items():
        path = (root / name).resolve()
        if not path.is_relative_to(root) or not path.is_file() or sha(path) != digest:
            raise ValueError('The server is running stale or unexpected code.')
    if any(loaded.get(name) != digest for name, digest in binding['code_sha256'].items()):
        raise ValueError('Server does not attest the frozen RAG code.')
    rag = status.get('rag', {})
    provider = rag.get('provider', {})
    if (provider.get('provider') != 'ollama_local' or provider.get('available') is not True
            or provider.get('configured') is not True or not isinstance(provider.get('model'), str)
            or not provider['model'].strip()):
        raise ValueError('Require the existing available local Ollama provider.')
    release = status.get('content_release')
    corpus = rag.get('retrieval', {}).get('corpus_id')
    if (not isinstance(release, dict) or not corpus or release.get('corpus_id') != corpus
            or not release.get('release_id') or not release.get('package_id')):
        raise ValueError('Server release/corpus identity is incomplete.')
    return dict(loaded_artifact_sha256=loaded, content_release=release, corpus_id=corpus,
        provider_identity={key: provider[key] for key in
            ('provider', 'configured', 'available', 'model', 'automatic_application') if key in provider},
        mode=status.get('mode'), demo_protocol_version=status.get('demo_protocol_version'))


def _error(exc):
    if isinstance(exc, urllib.error.HTTPError):
        return 'http_' + str(exc.code)
    if isinstance(exc, TimeoutError):
        return 'timeout'
    return 'evaluation_stopped'


def _http_error_response(exc):
    if not isinstance(exc, urllib.error.HTTPError):
        return None
    try:
        raw = exc.read(65537)
    except OSError:
        raw = b''
    return dict(http_status=exc.code, body=raw[:65536].decode('utf-8', errors='replace'),
                body_truncated=len(raw) > 65536)


def run(stt_run, packet_dir, output_dir, *, root=ROOT, transport=None):
    root = Path(root).resolve()
    packet, output = _private(root, packet_dir), _private(root, output_dir)
    if output.exists():
        raise FileExistsError('Use a new output directory; no automatic rerun.')
    protocol = _read(packet / 'protocol.json')
    captured = load_inputs(stt_run, root=root)
    if (protocol.get('source_sha256') != captured['source_sha256']
            or protocol.get('source_run') != captured['source'].relative_to(root).as_posix()
            or protocol.get('evaluator_sha256') != _code_sha()
            or protocol.get('rag_binding') != captured['binding']
            or protocol.get('rubric_sha256') != sha(packet / 'rubric-snapshot.json')
            or protocol.get('base_url') != BASE_URL or protocol.get('max_route_calls') != 39
            or protocol.get('automatic_retries') != 0 or protocol.get('arms') != list(ARMS)
            or protocol.get('allow_draft') is not False
            or protocol.get('timeout_seconds') != TIMEOUT_SECONDS
            or protocol.get('ids') != [row['id'] for row in captured['rows']]):
        raise ValueError('Prepared source, evaluator or rubric changed.')
    _write(packet / 'execution-claim.json', dict(claimed_utc=_now(), protocol_sha256=sha(packet / 'protocol.json')))
    output.mkdir(parents=True, exist_ok=False)
    for name in ('protocol.json', 'rubric-snapshot.json', 'human-review-template.json'):
        with (output / name).open('xb') as stream:
            stream.write((packet / name).read_bytes())
    transport = transport or LoopbackTransport()
    state = dict(schema_version=1, started_utc=_now(), completed=False,
        protocol_sha256=sha(output / 'protocol.json'), route_attempts=0, logical_cases=0,
        network_calls=0, error=None, human_review_complete=False, production_provider_changed=False)
    results_path = output / 'results.jsonl'
    frozen_server = None
    with results_path.open('x', encoding='utf-8') as stream:
        try:
            frozen_server = _server_fingerprint(root, transport.request('GET', '/api/status'), captured['binding'])
            _write(output / 'server-snapshot.json', frozen_server)
            for index, row in enumerate(captured['rows']):
                order = ARMS[index % 3:] + ARMS[:index % 3]
                for arm in order:
                    item = dict(id=row['id'], arm=arm, query=row[arm], status='error',
                        response=None, elapsed_seconds=None, error=None)
                    try:
                        if (_code_sha() != protocol['evaluator_sha256'] or any(
                                sha(captured['source'] / name) != digest for name, digest in captured['source_sha256'].items())):
                            raise ValueError('Frozen speech inputs changed.')
                        _check_binding(root, captured['binding'])
                        if not row[arm].strip():
                            item.update(status='no_question', elapsed_seconds=0.0)
                        else:
                            current = _server_fingerprint(root, transport.request('GET', '/api/status'), captured['binding'])
                            if current != frozen_server:
                                raise ValueError('Server release or model identity changed.')
                            if state['route_attempts'] >= MAX_ROUTE_CALLS:
                                raise ValueError('Route call limit reached.')
                            state['route_attempts'] += 1
                            started = time.perf_counter()
                            try:
                                response = transport.request('POST', '/api/route',
                                    dict(query=row[arm], allow_draft=False))
                            finally:
                                item['elapsed_seconds'] = time.perf_counter() - started
                            item['response'] = response
                            query = row[arm].strip()
                            conversation = response.get('conversation', {})
                            if (response.get('route') not in {'A', 'B', 'C', 'D', 'E'}
                                    or response.get('content_release') != frozen_server['content_release']
                                    or response.get('package_id') != frozen_server['content_release']['package_id']
                                    or conversation.get('applied') is not False
                                    or conversation.get('raw_query') != query or conversation.get('resolved_query') != query):
                                raise ValueError('Route response does not match the fresh query/release.')
                            item['status'] = 'answered'
                        state['logical_cases'] += 1
                    except BaseException as exc:
                        item['error'] = state['error'] = _error(exc)
                        failed_response = _http_error_response(exc)
                        if failed_response is not None:
                            item['response'] = failed_response
                    stream.write(json.dumps(item, ensure_ascii=False, allow_nan=False) + '\n')
                    stream.flush()
                    if state['error']:
                        break
                if state['error']:
                    break
            if not state['error']:
                _check_binding(root, captured['binding'])
                if (_code_sha() != protocol['evaluator_sha256'] or any(
                        sha(captured['source'] / name) != digest for name, digest in captured['source_sha256'].items())):
                    raise ValueError('Frozen speech inputs changed at the end.')
                if _server_fingerprint(root, transport.request('GET', '/api/status'), captured['binding']) != frozen_server:
                    raise ValueError('Server changed at the end of the run.')
                state['completed'] = state['logical_cases'] == len(captured['rows']) * 3
        except BaseException as exc:
            state['error'] = _error(exc)
            failed_response = _http_error_response(exc)
            if failed_response is not None:
                _write(output / 'initial-or-final-error-response.json', failed_response)
    state.update(finished_utc=_now(), network_calls=getattr(transport, 'network_calls', None),
        results_sha256=sha(results_path), server_snapshot_sha256=sha(output / 'server-snapshot.json') if frozen_server else None)
    _write(output / 'run.json', state)
    review = _read(packet / 'human-review-template.json')
    review.update(run_sha256=sha(output / 'run.json'), results_sha256=state['results_sha256'])
    _write(output / 'bound-human-review-template.json', review)
    return state


def summarize(run_dir, *, root=ROOT):
    root = Path(root).resolve()
    directory = _private(root, run_dir)
    state, protocol = _read(directory / 'run.json'), _read(directory / 'protocol.json')
    if (state.get('protocol_sha256') != sha(directory / 'protocol.json')
            or state.get('results_sha256') != sha(directory / 'results.jsonl')
            or protocol.get('rubric_sha256') != sha(directory / 'rubric-snapshot.json')):
        raise ValueError('Evaluation evidence checksum differs.')
    if state.get('server_snapshot_sha256') is not None and state['server_snapshot_sha256'] != sha(directory / 'server-snapshot.json'):
        raise ValueError('Server fingerprint evidence changed.')
    rows = [json.loads(line) for line in (directory / 'results.jsonl').read_text(encoding='utf-8').splitlines()]
    expected = {(identity, arm) for identity in protocol['ids'] for arm in ARMS}
    actual = [(row.get('id'), row.get('arm')) for row in rows]
    complete = (state.get('completed') is True and not state.get('error')
        and len(actual) == len(expected) and set(actual) == expected
        and all(row.get('status') in {'answered', 'no_question'} and not row.get('error') for row in rows))
    summary = dict(completed=complete,
        quality_status='pending_human_review' if complete else 'incomplete_no_aggregate',
        human_review_complete=False, task_accuracy=None, task_success_no_regression=None,
        typed_rag_failures=None, possible_asr_induced_failures=None,
        route_attempts=state.get('route_attempts'), logical_cases=state.get('logical_cases'),
        timing_scope='POST route wall time only; excludes status/hash checks and STT/TTS',
        held_out_evaluation=False, production_provider_changed=False)
    if not complete:
        return summary
    summary['arms'] = {}
    for arm in ARMS:
        selected = [row for row in rows if row['arm'] == arm]
        times = [row['elapsed_seconds'] for row in selected if row['status'] == 'answered']
        if any(type(value) not in (int, float) or not math.isfinite(value) or value < 0 for value in times):
            raise ValueError('Invalid route timing evidence.')
        summary['arms'][arm] = dict(answered=sum(row['status'] == 'answered' for row in selected),
            no_question=sum(row['status'] == 'no_question' for row in selected),
            median_seconds=statistics.median(times) if times else None,
            max_seconds=max(times) if times else None)
    # Ratings are intentionally separate: this tool never turns route A–E into correctness.
    review_path = directory / 'human-review.json'
    if not review_path.is_file():
        return summary
    review = _read(review_path)
    rubric = _rubric([dict(id=identity) for identity in protocol['ids']], _read(directory / 'rubric-snapshot.json'))
    records = review.get('records', [])
    reference = rubric.get('records', [])
    def meaningful_strings(value):
        return (isinstance(value, list) and 0 < len(value) <= 64
            and all(isinstance(item, str) and 0 < len(item.strip()) <= 1000 for item in value))
    valid_reference = (rubric.get('reference_confirmed') is True and rubric.get('reference_origin') == 'human'
        and isinstance(rubric.get('reviewer'), str) and bool(rubric['reviewer'].strip())
        and [row['id'] for row in reference] == protocol['ids'] and all(type(row.get('task_applicable')) is bool
            and row.get('answerability') in {'answerable', 'clarify', 'unsupported', 'non_question'}
            and (row['answerability'] != 'non_question' or row['task_applicable'] is False)
            and isinstance(row.get('required_fields'), list) and isinstance(row.get('reference_sources'), list)
            and (not row['task_applicable'] or row['answerability'] != 'answerable'
                or meaningful_strings(row['required_fields']) and meaningful_strings(row['reference_sources']))
            for row in reference))
    valid_review = (review.get('human_review_complete') is True and review.get('judgments_origin') == 'human'
        and isinstance(review.get('reviewer'), str) and bool(review['reviewer'].strip())
        and _valid_utc(review.get('reviewed_at_utc'))
        and review.get('protocol_sha256') == state['protocol_sha256']
        and review.get('run_sha256') == sha(directory / 'run.json')
        and review.get('results_sha256') == state['results_sha256']
        and isinstance(records, list) and all(isinstance(row, dict) for row in records)
        and [row.get('id') for row in records if isinstance(row, dict)] == protocol['ids']
        and all(all(type(row.get(key)) is bool for key in
            ('typed_task_success','baseline_task_success','candidate_task_success')) for row in records))
    if valid_reference and valid_review:
        result_by_case = {(row['id'], row['arm']): row for row in rows}
        if any(label['task_applicable'] and result_by_case[(row['id'], arm)]['status'] == 'no_question'
                and row[key] for row, label in zip(records, reference) for arm, key in
                [('typed', 'typed_task_success'), ('baseline_raw', 'baseline_task_success'),
                 ('candidate_raw', 'candidate_task_success')]):
            summary['human_review_issue'] = 'success_without_a_question_or_answer'
            return summary
        applicable = [row for row, label in zip(records, reference) if label['task_applicable']]
        summary['human_review_complete'] = True
        summary['reviewed_tasks'] = len(applicable)
        summary['excluded_non_task_records'] = len(records) - len(applicable)
        summary['quality_status'] = 'human_development_review_recorded'
        if applicable:
            summary['task_accuracy'] = {arm: dict(successes=sum(row[key] for row in applicable),
                denominator=len(applicable)) for arm, key in
                [('typed','typed_task_success'),('baseline_raw','baseline_task_success'),('candidate_raw','candidate_task_success')]}
            summary['task_success_no_regression'] = all(not row['baseline_task_success'] or row['candidate_task_success'] for row in applicable)
            summary['typed_rag_failures'] = sum(not row['typed_task_success'] for row in applicable)
            summary['possible_asr_induced_failures'] = {arm: sum(row['typed_task_success'] and not row[key] for row in applicable)
                for arm, key in [('baseline_raw','baseline_task_success'),('candidate_raw','candidate_task_success')]}
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prep = commands.add_parser('prepare', help='offline packet only')
    prep.add_argument('--stt-run', required=True)
    prep.add_argument('--output', required=True)
    prep.add_argument('--rubric')
    execute = commands.add_parser('run', help='explicit loopback RAG calls only')
    for name in ('stt-run', 'packet', 'output'):
        execute.add_argument('--' + name, required=True)
    report = commands.add_parser('summarize')
    report.add_argument('--run', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'prepare':
            value = prepare(args.stt_run, args.output, rubric_path=args.rubric)
            result = dict(state=value['state'], human_inputs=len(value['ids']),
                max_route_calls=value['max_route_calls'], network_calls=0, actual_rag_calls=0)
        elif args.command == 'run':
            result = run(args.stt_run, args.packet, args.output)
        else:
            result = summarize(args.run)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0 if result.get('completed', True) else 1
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps(dict(error=_error(exc), execution_stopped=True)))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
