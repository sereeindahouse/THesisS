"""Isolated Cafet/Gemini development comparison; prepare is entirely offline.

No command changes the production STT provider. Live execution requires a
separate user authorization bound to the exact prepared protocol and manifest.
Only existing local model assets are loaded; no dependency/model downloads.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import io
import importlib.metadata
import json
import math
import os
from pathlib import Path
import re
import sys
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from score import normalize, score
from tools.evaluate_stt_context import (
    BASE_DECODING, PINNED_REVISION, PINNED_SHA256, PINNED_SOURCE,
    audit_wav, local_path, manifest_rows, read_frozen_json, sha,
)

MODEL = 'gemini-3.5-transcribe'
HOST = 'generativelanguage.googleapis.com'
BASE_URL = 'https://' + HOST
TIMEOUT_SECONDS = 60
MAX_ATTEMPTS = 15
MAX_COST_USD = Decimal('0.10')
MAX_OUTPUT_TOKENS = 480
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
SERVICE_TIER_CHECKED_DATE = '2026-10-30'
INPUT_USD_PER_MILLION = Decimal('2.00')
OUTPUT_USD_PER_MILLION = Decimal('12.00')
CODE_FILES = ('tools/compare_stt_candidate.py', 'tools/evaluate_stt_context.py',
              'score.py', 'stt_mn.py')
SOURCE_URLS = {
    'transcription': 'https://ai.google.dev/gemini-api/docs/transcribe',
    'interactions': 'https://ai.google.dev/api/interactions-api',
    'files': 'https://ai.google.dev/gemini-api/docs/files',
    'pricing': 'https://ai.google.dev/gemini-api/docs/pricing',
    'data_terms': 'https://ai.google.dev/gemini-api/terms',
}
_FILE_NAME = re.compile(r'files/[a-zA-Z0-9_-]{1,160}\Z')
_SAFE_CODE = re.compile(r'[a-z][a-z0-9_]{0,80}\Z')
_SHA = re.compile(r'[0-9a-f]{64}\Z')


def _now():
    return datetime.now(timezone.utc).isoformat()


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       indent=2, allow_nan=False) + '\n').encode('utf-8')


def _read(path):
    if path.stat().st_size > MAX_RESPONSE_BYTES:
        raise ValueError('JSON input is too large.')
    return read_frozen_json(path)


def _write_new(path, value):
    with path.open('xb') as handle:
        handle.write(_json_bytes(value))


def _private_path(root, value):
    path = local_path(root, value)
    if not path.is_relative_to((root / 'runtime').resolve()):
        raise ValueError('Private comparison files must remain inside runtime/.')
    return path


def _code_hashes():
    # Module source is always the actual checkout, even for synthetic test roots.
    return {name: sha(ROOT / name) for name in CODE_FILES}


def capture_manifest(manifest_path, *, root=ROOT):
    """Validate with the existing manifest/WAV contract and capture identical bytes."""
    root = Path(root).resolve()
    path = _private_path(root, manifest_path)
    manifest, manifest_sha256 = _read(path)
    if not isinstance(manifest, dict):
        raise ValueError('Manifest must be an object.')
    humans, controls = manifest.get('human_rows'), manifest.get('control_rows')
    if (not isinstance(humans, list) or not 1 <= len(humans) <= 13
            or not isinstance(controls, list) or len(controls) > 2):
        raise ValueError('Require 1–13 confirmed human rows and at most two nonspeech controls.')
    if any(not isinstance(row, dict) or row.get('control_kind') not in {'silence', 'noise'}
           for row in controls):
        raise ValueError('Synthetic speech is excluded from this comparison.')
    if any(not isinstance(row.get('reference'), str) or len(row['reference']) > 5000
           for row in humans if isinstance(row, dict)):
        raise ValueError('References must be bounded strings.')
    if any(row.get('audio_origin', 'real_human_recording') != 'real_human_recording'
           for row in humans if isinstance(row, dict)):
        raise ValueError('Human rows cannot declare a synthetic audio origin.')
    for row in humans:
        if isinstance(row, dict) and 'critical_slots' in row:
            slots = row['critical_slots']
            if (not isinstance(slots, list) or len(slots) > 12 or any(
                not isinstance(slot, dict) or set(slot) != {'field', 'expected'}
                or not isinstance(slot['field'], str) or not 1 <= len(slot['field']) <= 100
                or not isinstance(slot['expected'], str) or not slot['expected'].strip()
                or normalize(slot['expected']) not in normalize(row['reference']) for slot in slots)):
                raise ValueError('Critical slots must be bounded, predeclared reference spans.')
    rows = manifest_rows(root, manifest)
    audio_bytes = {}
    for row in rows:
        data = row['path'].read_bytes()
        if hashlib.sha256(data).hexdigest() != row['audio_sha256']:
            raise ValueError('Audio changed while capturing the manifest.')
        audio_bytes[row['id']] = data
    if sha(path) != manifest_sha256:
        raise ValueError('Manifest changed while capturing its inputs.')
    references = [{'id': row['id'], 'reference': row['reference']}
                  for row in rows if row['group'] == 'human']
    return dict(manifest=manifest, manifest_sha256=manifest_sha256, rows=rows,
                reference_sha256=hashlib.sha256(_json_bytes(references)).hexdigest(),
                audio_bytes=audio_bytes)


def estimated_cost(audio_seconds, attempts):
    """Preflight estimate using audio tokens and a bounded output-token allowance.

    This does not cap a provider bill or validate account pricing/tax/retention.
    A changed published rate requires a reviewed protocol, not a silent update.
    """
    if not math.isfinite(float(audio_seconds)) or audio_seconds < 0:
        raise ValueError('Invalid audio duration.')
    audio_tokens = math.ceil(float(audio_seconds) * 25)
    return ((Decimal(audio_tokens) * INPUT_USD_PER_MILLION
             + Decimal(attempts * MAX_OUTPUT_TOKENS) * OUTPUT_USD_PER_MILLION)
            / Decimal(1000000))


def _execution_caps(service_tier):
    return dict(max_transcription_attempts=MAX_ATTEMPTS, timeout_seconds=TIMEOUT_SECONDS,
                automatic_retries=0,
                max_estimated_cost_usd=0.0 if service_tier == 'free' else float(MAX_COST_USD),
                max_output_tokens=MAX_OUTPUT_TOKENS)


def prepare(manifest_path, output_dir, *, root=ROOT, service_tier='paid'):
    """Write a new private review packet; perform zero inference/network calls."""
    root = Path(root).resolve()
    if service_tier not in {'paid', 'free'}:
        raise ValueError('Choose the paid or free service tier explicitly.')
    output = _private_path(root, output_dir)
    if output.exists():
        raise FileExistsError('Output exists; preserve the earlier packet.')
    captured = capture_manifest(manifest_path, root=root)
    rows = captured['rows']
    duration = sum(row['audio_audit']['seconds'] for row in rows)
    estimate = estimated_cost(duration, len(rows))
    if estimate > MAX_COST_USD:
        raise ValueError('Conservative estimate exceeds the fixed USD 0.10 limit.')
    references = [{'id': row['id'], 'reference': row['reference'], 'hypothesis': ''}
                  for row in rows if row['group'] == 'human']
    counts = score(references)
    protocol = dict(
        schema_version=1, created_utc=_now(), study='observed development cohort',
        state='prepared_awaiting_user_authorization', model=MODEL,
        service_tier=service_tier, service_tier_checked_date=SERVICE_TIER_CHECKED_DATE,
        paid_fallback_allowed=False,
        transcription_mode='verbatim', language_codes=['mn-MN'],
        manifest_sha256=captured['manifest_sha256'],
        reference_sha256=captured['reference_sha256'], code_sha256=_code_hashes(),
        baseline=dict(model=PINNED_SOURCE, revision=PINNED_REVISION,
                      model_sha256=PINNED_SHA256, device='cpu', compute_type='int8',
                      decoding=dict(BASE_DECODING), local_files_only=True),
        human_recordings=len(references), control_recordings=len(rows) - len(references),
        reference_words=counts['reference_words'],
        reference_characters=counts['reference_characters'], audio_seconds=duration,
        recordings=[dict(id=row['id'], group=row['group'], kind=row['kind'],
                         audio_sha256=row['audio_sha256'],
                         seconds=row['audio_audit']['seconds']) for row in rows],
        caps=_execution_caps(service_tier),
        pricing=dict(checked_date='2026-10-29', source=SOURCE_URLS['pricing'],
                     input_usd_per_million_tokens=float(INPUT_USD_PER_MILLION),
                     output_usd_per_million_tokens=float(OUTPUT_USD_PER_MILLION),
                     estimated_audio_tokens_per_second=25,
                     conservative_estimated_cost_usd=float(estimate),
                     paid_equivalent_estimated_cost_usd=float(estimate),
                     estimate_basis='paid_rate_equivalent_not_actual_bill',
                     billing_cap_guaranteed=False),
        acceptance=dict(required_human_recordings=13, required_reference_words=186,
                        required_reference_characters=1089,
                        expected_baseline_word_errors=67, expected_baseline_character_errors=184,
                        candidate_max_word_errors=60, candidate_max_character_errors=184,
                        critical_new_errors=0, candidate_max_elapsed_seconds=10,
                        task_success_no_regression=True, human_review_required=True),
        source_urls=SOURCE_URLS, private_audio_uploaded=False, network_calls=0,
        inference_calls=0, training_performed=False, production_accepted=False,
        reference_used_for_inference=False, automatic_postcorrection=False,
        limitations=[
            'Prepared packet only: no ASR gain or human review is implied.',
            'Existing observed single-speaker development cohort, not held-out evaluation.',
            'References remain local and are never included in provider requests.',
            'Files API deletion is attempted after each upload; deletion is not a claim about vendor logs.',
            'Account tier, current price and data handling require user review before authorization.',
            'Token estimate and request limits are not an enforceable provider billing cap.',
            'A free-tier protocol cannot make a paid-backed credential free or verify its billing tier.',
            'Unpaid data terms can allow product improvement and human review; store=False and file deletion do not override them.',
        ])
    output.mkdir(parents=True, exist_ok=False)
    _write_new(output / 'protocol.json', protocol)
    protocol_sha256 = sha(output / 'protocol.json')
    # Preserve the exact original manifest bytes so the recorded SHA stays useful.
    manifest_path = _private_path(root, manifest_path)
    original = manifest_path.read_bytes()
    if hashlib.sha256(original).hexdigest() != captured['manifest_sha256']:
        raise ValueError('Manifest changed before saving the prepared snapshot.')
    with (output / 'manifest-snapshot.json').open('xb') as handle:
        handle.write(original)
    approval = dict(schema_version=1, authorized_by=None, recorded_at_utc=None,
                    authorization_note=None, user_cloud_audio_upload_authorized=False,
                    user_paid_service_authorized=False, paid_service_account_confirmed=False,
                    billing_project_id=None, billing_verified_at_utc=None, model=MODEL,
                    service_tier=service_tier, paid_fallback_allowed=False,
                    user_unpaid_data_terms_acknowledged=False,
                    free_service_account_confirmed=False,
                    free_service_verification_source=None, free_service_verified_at_utc=None,
                    manifest_sha256=captured['manifest_sha256'], protocol_sha256=protocol_sha256,
                    max_transcription_attempts=MAX_ATTEMPTS,
                    max_estimated_cost_usd=protocol['caps']['max_estimated_cost_usd'])
    _write_new(output / 'approval-template.json', approval)
    review = dict(schema_version=1, manifest_sha256=captured['manifest_sha256'],
                  protocol_sha256=protocol_sha256, reviewer=None, reviewed_at_utc=None,
                  human_review_complete=False, run_sha256=None, results_sha256=None,
                  review_type='developer_self_review', judgments_origin=None,
                  rag_binding=None, records=[
                      dict(id=row['id'], critical_new_errors=None,
                           critical_slots=row.get('critical_slots'), critical_slots_confirmed=False,
                           typed_task_success=None,
                           baseline_task_success=None, candidate_task_success=None, notes=None)
                      for row in rows if row['group'] == 'human'])
    _write_new(output / 'human-review-template.json', review)
    return protocol


def validate_approval(approval, protocol, protocol_sha256):
    """Require explicit user-recorded consent bound to these exact private inputs."""
    if not isinstance(approval, dict) or approval.get('schema_version') != 1:
        raise ValueError('An explicit authorization record is required.')
    # Missing tier belongs only to legacy paid packets, never an implicit free run.
    service_tier = protocol.get('service_tier', 'paid')
    if (service_tier not in {'paid', 'free'}
            or approval.get('service_tier', 'paid') != service_tier
            or protocol.get('paid_fallback_allowed', False) is not False
            or approval.get('paid_fallback_allowed', False) is not False):
        raise ValueError('Authorization must match the fixed service tier without paid fallback.')
    if approval.get('user_cloud_audio_upload_authorized') is not True:
        raise ValueError('Explicit user cloud-audio upload authorization is required.')
    if (approval.get('authorized_by') != 'user'
            or approval.get('model') != MODEL
            or approval.get('manifest_sha256') != protocol['manifest_sha256']
            or approval.get('protocol_sha256') != protocol_sha256):
        raise ValueError('Authorization does not match this manifest, protocol and model.')
    note, stamp = approval.get('authorization_note'), approval.get('recorded_at_utc')
    if not isinstance(note, str) or not 1 <= len(note.strip()) <= 2000 or not isinstance(stamp, str):
        raise ValueError('Record the actual user authorization and its UTC timestamp.')
    try:
        parsed = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('Authorization timestamp must be ISO 8601 UTC.') from None
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError('Authorization timestamp must be UTC.')
    if service_tier == 'free':
        if (approval.get('user_unpaid_data_terms_acknowledged') is not True
                or approval.get('free_service_account_confirmed') is not True
                or approval.get('user_paid_service_authorized') is not False
                or approval.get('paid_service_account_confirmed') is not False
                or approval.get('billing_project_id') is not None
                or approval.get('billing_verified_at_utc') is not None
                or approval.get('paid_fallback_allowed') is not False):
            raise ValueError('Free service requires unpaid-data consent, verified free account and no paid authorization.')
        source = approval.get('free_service_verification_source')
        if not isinstance(source, str) or not 1 <= len(source.strip()) <= 2000:
            raise ValueError('Record the actual source verifying this credential account uses the free tier.')
        verified_value = approval.get('free_service_verified_at_utc')
    else:
        project = approval.get('billing_project_id')
        if (approval.get('user_paid_service_authorized') is not True
                or approval.get('paid_service_account_confirmed') is not True
                or not isinstance(project, str) or not re.fullmatch(r'[a-zA-Z0-9-]{1,120}', project)):
            raise ValueError('Confirm user paid-service permission and the active paid project before upload.')
        verified_value = approval.get('billing_verified_at_utc')
    try:
        verified = datetime.fromisoformat(verified_value.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        raise ValueError('Record the real service-account verification time in UTC.') from None
    if verified.utcoffset() is None or verified.utcoffset().total_seconds() != 0:
        raise ValueError('Service-account verification time must be UTC.')
    attempts = approval.get('max_transcription_attempts')
    if type(attempts) is not int or not len(protocol['recordings']) <= attempts <= MAX_ATTEMPTS:
        raise ValueError('Authorization must cover this packet within 15 transcription attempts.')
    try:
        budget = Decimal(str(approval.get('max_estimated_cost_usd')))
    except Exception:
        raise ValueError('Invalid authorization budget.') from None
    if service_tier == 'free':
        if not budget.is_finite() or budget != 0:
            raise ValueError('Free service authorizes exactly zero spending and no paid fallback.')
    elif (not budget.is_finite() or not Decimal('0') < budget <= MAX_COST_USD
          or budget < Decimal(str(protocol['pricing']['conservative_estimated_cost_usd']))):
        raise ValueError('Authorization budget must cover the estimate and remain at most USD 0.10.')
    return approval


def validate_url(url):
    """Only fixed Google API endpoints; never send keys or audio through redirects."""
    if not isinstance(url, str) or len(url) > 4096 or any(ord(c) < 33 for c in url):
        raise ValueError('Invalid provider URL.')
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname != HOST or parsed.netloc != HOST
            or parsed.username or parsed.password or parsed.fragment):
        raise ValueError('Provider endpoint is outside the fixed HTTPS host.')
    allowed = (parsed.path in {'/upload/v1beta/files', '/v1beta/interactions'}
               or re.fullmatch(r'/v1beta/files/[a-zA-Z0-9_-]{1,160}', parsed.path))
    if not allowed:
        raise ValueError('Provider endpoint path is not permitted.')
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
    if (parsed.path != '/upload/v1beta/files' and query
            or any(key not in {'upload_id', 'upload_protocol'} for key, _ in query)
            or len(query) > 2):
        raise ValueError('Unexpected provider URL query parameters.')
    return url


def build_request(file_uri):
    validate_url(file_uri)
    if not urllib.parse.urlsplit(file_uri).path.startswith('/v1beta/files/'):
        raise ValueError('Audio URI must identify the just-uploaded file.')
    return dict(model=MODEL, store=False, input=[dict(type='audio', uri=file_uri,
                                                    mime_type='audio/wav')],
                generation_config=dict(max_output_tokens=MAX_OUTPUT_TOKENS,
                    transcription_config=dict(language_codes=['mn-MN'], mode=dict(type='verbatim'))))


class CandidateError(RuntimeError):
    def __init__(self, code, partial_result=None):
        self.code = code if isinstance(code, str) and _SAFE_CODE.fullmatch(code) else 'candidate_error'
        self.partial_result = partial_result
        super().__init__(self.code)


def sanitized_error(exc):
    # Never stringify exceptions: HTTP bodies, URLs and library messages may contain secrets.
    if isinstance(exc, CandidateError):
        return exc.code
    if isinstance(exc, urllib.error.HTTPError):
        return 'http_' + str(exc.code) if type(exc.code) is int else 'http_error'
    if isinstance(exc, (TimeoutError, TimeoutError.__base__)) and isinstance(exc, TimeoutError):
        return 'timeout'
    if isinstance(exc, KeyboardInterrupt):
        return 'interrupted'
    return 'operation_failed'


def _usage(value):
    if not isinstance(value, dict):
        return None
    return {name: value[name] for name in
            ('total_input_tokens', 'total_output_tokens', 'total_thought_tokens', 'total_tokens')
            if type(value.get(name)) is int and 0 <= value[name] <= 10000000}


def parse_interaction(value):
    if not isinstance(value, dict) or value.get('status') != 'completed':
        raise CandidateError('interaction_incomplete')
    returned_model = value.get('model')
    if returned_model != MODEL:
        raise CandidateError('returned_model_mismatch')
    usage = _usage(value.get('usage'))
    if usage and usage.get('total_output_tokens', 0) >= MAX_OUTPUT_TOKENS:
        raise CandidateError('output_token_cap_exceeded')
    for item in [value] + (value.get('steps') if isinstance(value.get('steps'), list) else []):
        if isinstance(item, dict) and any(str(item.get(key, '')).lower() in
                {'max_tokens', 'max_output_tokens', 'length', 'token_limit'}
                for key in ('finish_reason', 'stop_reason')):
            raise CandidateError('interaction_truncated')
    texts = []
    steps = value.get('steps')
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, dict) or step.get('type') != 'model_output':
                raise CandidateError('unexpected_interaction_step')
            content = step.get('content')
            if not isinstance(content, list):
                raise CandidateError('invalid_interaction_content')
            for item in content:
                if not isinstance(item, dict) or item.get('type') != 'text' or not isinstance(item.get('text'), str):
                    raise CandidateError('invalid_interaction_content')
                texts.append(item['text'])
    elif isinstance(value.get('output_text'), str):
        # Some documented SDK-facing responses expose this convenience field.
        texts = [value['output_text']]
    elif ('steps' not in value and 'output_text' not in value
          and usage is not None and usage.get('total_output_tokens') == 0):
        # Observed completed nonspeech responses omit the empty repeated output
        # field. Zero output usage distinguishes this from missing/lost text.
        texts = ['']
    else:
        raise CandidateError('missing_interaction_output')
    text = ''.join(texts)
    if len(text) > 50000:
        raise CandidateError('transcript_too_large')
    return dict(text=text, model=returned_model, usage=usage,
                response_sha256=hashlib.sha256(_json_bytes(value)).hexdigest(),
                status='completed')


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise CandidateError('redirect_rejected')


class GeminiTransport:
    """Bounded stdlib Files/Interactions REST transport with one delete attempt."""
    def __init__(self, api_key, *, opener=None):
        if not isinstance(api_key, str) or not api_key or len(api_key) > 300 or any(c.isspace() for c in api_key):
            raise ValueError('A valid GEMINI_API_KEY environment value is required.')
        self._key = api_key
        self._opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        self.network_calls = 0

    def _request(self, method, url, data=None, headers=None):
        validate_url(url)
        outgoing = {'x-goog-api-key': self._key, **(headers or {})}
        request = urllib.request.Request(url, data=data, headers=outgoing, method=method)
        self.network_calls += 1
        try:
            with self._opener.open(request, timeout=TIMEOUT_SECONDS) as response:
                if hasattr(response, 'geturl') and response.geturl() != url:
                    raise CandidateError('redirect_rejected')
                status = getattr(response, 'status', 200)
                if not 200 <= status < 300:
                    raise CandidateError('http_error')
                payload = response.read(MAX_RESPONSE_BYTES + 1)
                if len(payload) > MAX_RESPONSE_BYTES:
                    raise CandidateError('response_too_large')
                values = json.loads(payload.decode('utf-8')) if payload.strip() else {}
                if not isinstance(values, dict):
                    raise CandidateError('invalid_json_response')
                return values, response.headers
        except CandidateError:
            raise
        except BaseException as exc:
            raise CandidateError(sanitized_error(exc)) from None

    def transcribe(self, audio_bytes, *, display_name):
        if not isinstance(audio_bytes, bytes) or not 0 < len(audio_bytes) <= 8 * 1024 * 1024:
            raise ValueError('Require bounded captured WAV bytes.')
        if not re.fullmatch(r'clip-[a-zA-Z0-9][a-zA-Z0-9._-]{0,100}', display_name):
            raise ValueError('Require a neutral clip ID as the upload display name.')
        name, result, failure, cleanup = None, None, None, None
        try:
            _, headers = self._request('POST', BASE_URL + '/upload/v1beta/files',
                _json_bytes({'file': {'display_name': display_name}}),
                {'Content-Type': 'application/json', 'X-Goog-Upload-Protocol': 'resumable',
                 'X-Goog-Upload-Command': 'start',
                 'X-Goog-Upload-Header-Content-Length': str(len(audio_bytes)),
                 'X-Goog-Upload-Header-Content-Type': 'audio/wav'})
            upload_url = headers.get('X-Goog-Upload-URL') or headers.get('x-goog-upload-url')
            validate_url(upload_url)
            if urllib.parse.urlsplit(upload_url).path != '/upload/v1beta/files':
                raise CandidateError('invalid_upload_endpoint')
            uploaded, _ = self._request('POST', upload_url, audio_bytes,
                {'Content-Type': 'audio/wav', 'Content-Length': str(len(audio_bytes)),
                 'X-Goog-Upload-Offset': '0', 'X-Goog-Upload-Command': 'upload, finalize'})
            file = uploaded.get('file')
            if not isinstance(file, dict) or not isinstance(file.get('name'), str) or not _FILE_NAME.fullmatch(file['name']):
                raise CandidateError('invalid_uploaded_file')
            name = file['name']
            uri = file.get('uri')
            validate_url(uri)
            if uri != BASE_URL + '/v1beta/' + name:
                raise CandidateError('uploaded_file_uri_mismatch')
            if file.get('state', 'ACTIVE') != 'ACTIVE':
                raise CandidateError('uploaded_file_not_active')
            response, _ = self._request('POST', BASE_URL + '/v1beta/interactions',
                _json_bytes(build_request(uri)), {'Content-Type': 'application/json'})
            result = parse_interaction(response)
        except BaseException as exc:
            failure = sanitized_error(exc)
        finally:
            if name:
                try:
                    self._request('DELETE', BASE_URL + '/v1beta/' + name)
                    cleanup = dict(attempted=True, deleted=True, error=None)
                except BaseException as exc:
                    cleanup = dict(attempted=True, deleted=False, error=sanitized_error(exc))
                    failure = failure or 'uploaded_file_cleanup_failed'
            else:
                cleanup = dict(attempted=False, deleted=None, error='no_valid_uploaded_file_handle')
        if result is not None:
            result['cleanup'] = cleanup
        if failure:
            partial = result or dict(text=None, model=MODEL, usage=None, cleanup=cleanup)
            raise CandidateError(failure, partial) from None
        return result


class CafetBaseline:
    def __init__(self, root=ROOT):
        started = time.perf_counter()
        from stt_mn import load_choice
        root = Path(root).resolve()
        choice, model_path = load_choice(root)
        if ((choice.get('source_repo'), choice.get('source_revision'), choice.get('model_sha256'))
                != (PINNED_SOURCE, PINNED_REVISION, PINNED_SHA256)
                or choice.get('decoding') != BASE_DECODING
                or choice.get('device') != 'cpu' or choice.get('compute_type') != 'int8'):
            raise ValueError('Only the pinned Cafet CPU INT8 baseline may be compared.')
        model_path = Path(model_path).resolve()
        if not model_path.is_relative_to((root / 'models').resolve()):
            raise ValueError('Require the existing local model inside models/.')
        manifest, _ = _read(model_path / 'download-manifest.json')
        for name, metadata in manifest['files'].items():
            path = (model_path / name).resolve()
            if not path.is_relative_to(model_path) or sha(path) != metadata['sha256']:
                raise ValueError('Local model checksum changed.')
        from faster_whisper import WhisperModel
        self.model = WhisperModel(str(model_path), device='cpu', compute_type='int8', local_files_only=True)
        self.model_load_seconds = time.perf_counter() - started

    def transcribe(self, audio_bytes, *, display_name):
        segments, info = self.model.transcribe(io.BytesIO(audio_bytes), **BASE_DECODING)
        values = [dict(start=float(s.start), end=float(s.end), text=s.text.strip()) for s in segments]
        return dict(text=' '.join(s['text'] for s in values).strip(), model=PINNED_SOURCE,
                    revision=PINNED_REVISION, model_sha256=PINNED_SHA256, segments=values,
                    actual_compute_type=self.model.model.compute_type, usage=None,
                    decoder_duration=float(info.duration))


def _result(value, elapsed):
    if (not isinstance(value, dict) or not isinstance(value.get('text'), str)
            or len(value['text']) > 50000 or not isinstance(value.get('model'), str)):
        raise CandidateError('invalid_recognizer_result')
    allowed = ('text', 'model', 'revision', 'model_sha256', 'segments', 'actual_compute_type',
               'decoder_duration', 'response_sha256', 'status', 'cleanup')
    return dict({k: value[k] for k in allowed if k in value}, usage=_usage(value.get('usage')),
                elapsed_seconds=elapsed, error=None)


def execute(manifest_path, packet_dir, output_dir, approval_path, *, root=ROOT,
            baseline_factory=None, transport_factory=None, environ=None):
    """Run only after validating the complete authorization; one attempt per clip."""
    root = Path(root).resolve()
    packet, output = _private_path(root, packet_dir), _private_path(root, output_dir)
    if output.exists():
        raise FileExistsError('Run output already exists; automatic retries are prohibited.')
    protocol, protocol_sha256 = _read(packet / 'protocol.json')
    approval_path = _private_path(root, approval_path)
    approval, approval_sha256 = _read(approval_path)
    validate_approval(approval, protocol, protocol_sha256)
    service_tier = protocol.get('service_tier', 'paid')
    captured = capture_manifest(manifest_path, root=root)
    if (captured['manifest_sha256'] != protocol['manifest_sha256']
            or captured['reference_sha256'] != protocol['reference_sha256']
            or _code_hashes() != protocol.get('code_sha256')
            or sha(packet / 'manifest-snapshot.json') != protocol['manifest_sha256']):
        raise ValueError('Prepared manifest, references or evaluator code changed; prepare a new packet.')
    if (protocol.get('model') != MODEL or protocol.get('transcription_mode') != 'verbatim'
            or protocol.get('caps') != _execution_caps(service_tier)
            or ('service_tier' in protocol
                and protocol.get('service_tier_checked_date') != SERVICE_TIER_CHECKED_DATE)
            or (service_tier == 'free' and protocol.get('paid_fallback_allowed') is not False)):
        raise ValueError('Protocol must retain the fixed model and execution bounds.')
    env = os.environ if environ is None else environ
    key = env.get('GEMINI_API_KEY')
    if not isinstance(key, str) or not key.strip():
        raise ValueError('GEMINI_API_KEY must be supplied through the environment; no execution started.')
    # An approval is for one bounded pass, even when a different output name is used.
    _write_new(packet / 'execution-claim.json', dict(protocol_sha256=protocol_sha256,
        claimed_utc=_now(), output_path=output.relative_to(root).as_posix()))
    baseline_factory = baseline_factory or (lambda: CafetBaseline(root))
    transport_factory = transport_factory or GeminiTransport
    # Both factories occur only after permission, key, input and code checks.
    baseline, candidate = baseline_factory(), transport_factory(key)
    output.mkdir(parents=True, exist_ok=False)
    for name in ('protocol.json', 'manifest-snapshot.json', 'human-review-template.json'):
        with (output / name).open('xb') as handle:
            handle.write((packet / name).read_bytes())
    state = dict(schema_version=1, started_utc=_now(), completed=False,
                 model=MODEL, protocol_sha256=protocol_sha256,
                 service_tier=service_tier, paid_fallback_allowed=False,
                 max_authorized_spend_usd=approval['max_estimated_cost_usd'],
                 manifest_sha256=protocol['manifest_sha256'], approval_sha256=approval_sha256,
                 transcription_attempts=0, completed_recordings=0, error=None,
                 inference_performed=True, training_performed=False, production_accepted=False,
                 private_audio_uploaded=False, network_calls=0)
    state['baseline_model_load_seconds'] = getattr(baseline, 'model_load_seconds', None)
    state['runtime_versions'] = {}
    for package in ('faster-whisper', 'ctranslate2', 'av', 'numpy'):
        try:
            state['runtime_versions'][package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            state['runtime_versions'][package] = None
    results_path = output / 'results.jsonl'
    observed_cost = Decimal('0')
    usage_recordings = 0
    with results_path.open('x', encoding='utf-8') as handle:
        for row in captured['rows']:
            result = dict(id=row['id'], group=row['group'], kind=row['kind'],
                          audio_sha256=row['audio_sha256'], baseline=None, candidate=None)
            try:
                if (sha(_private_path(root, manifest_path)) != captured['manifest_sha256']
                        or _code_hashes() != protocol['code_sha256']
                        or sha(row['path']) != row['audio_sha256']):
                    raise CandidateError('frozen_input_changed')
                audio = captured['audio_bytes'][row['id']]
                started = time.perf_counter()
                result['baseline'] = _result(baseline.transcribe(audio, display_name='clip-' + row['id']),
                                             time.perf_counter() - started)
                if state['transcription_attempts'] >= approval['max_transcription_attempts']:
                    raise CandidateError('transcription_attempt_limit')
                state['transcription_attempts'] += 1
                started = time.perf_counter()
                value = candidate.transcribe(audio, display_name='clip-' + row['id'])
                result['candidate'] = _result(value, time.perf_counter() - started)
                state['private_audio_uploaded'] = True
                usage = result['candidate']['usage'] or {}
                if 'total_input_tokens' in usage and 'total_output_tokens' in usage:
                    usage_recordings += 1
                    observed_cost += (Decimal(usage['total_input_tokens']) * INPUT_USD_PER_MILLION
                                      + Decimal(usage['total_output_tokens']) * OUTPUT_USD_PER_MILLION) / Decimal(1000000)
                    if (service_tier == 'paid'
                            and observed_cost > Decimal(str(approval['max_estimated_cost_usd']))):
                        raise CandidateError('observed_token_cost_limit')
                if sha(row['path']) != row['audio_sha256']:
                    raise CandidateError('audio_changed_during_inference')
                state['completed_recordings'] += 1
            except BaseException as exc:
                state['error'] = sanitized_error(exc)
                partial = getattr(exc, 'partial_result', None)
                if result['candidate'] is None and partial:
                    result['candidate'] = partial
                result['error'] = state['error']
            state['network_calls'] = getattr(candidate, 'network_calls', 0)
            if state['network_calls']:
                # A failed upload can already have transmitted data.
                state['private_audio_uploaded'] = True
            handle.write(json.dumps(result, ensure_ascii=False, allow_nan=False) + '\n')
            handle.flush()
            if state['error']:
                break
    state['completed'] = state['error'] is None and state['completed_recordings'] == len(captured['rows'])
    state['finished_utc'] = _now()
    state['usage_complete'] = state['completed'] and usage_recordings == len(captured['rows'])
    state['paid_equivalent_token_cost_estimate_usd'] = float(observed_cost) if state['usage_complete'] else None
    state['known_paid_equivalent_token_cost_estimate_usd'] = float(observed_cost) if usage_recordings else None
    # Preserve legacy paid fields; free usage is not evidence of a paid charge or a zero bill.
    state['observed_token_cost_estimate_usd'] = (
        state['paid_equivalent_token_cost_estimate_usd'] if service_tier == 'paid' else None)
    state['known_token_cost_estimate_usd'] = (
        state['known_paid_equivalent_token_cost_estimate_usd'] if service_tier == 'paid' else None)
    state['token_cost_estimate_basis'] = 'paid_rate_equivalent_not_actual_bill'
    state['usage_recordings'] = usage_recordings
    state['actual_billed_cost_usd'] = None
    state['results_sha256'] = sha(results_path)
    _write_new(output / 'run.json', state)
    if state['completed']:
        raw = [json.loads(line) for line in results_path.read_text(encoding='utf-8').splitlines()]
        by_id = {row['id']: row for row in raw}
        rag_codes = {name: sha(root / name) for name in
            ('rag_runtime.py', 'source_fields.py', 'website_retrieval.py', 'sqlite_retrieval.py')
            if (root / name).is_file()}
        binding = dict(code_sha256=rag_codes, corpus_sha256={name: sha(root / name) for name in
            ('CORE/database/website.db', 'runtime/content.db') if (root / name).is_file()})
        _write_new(output / 'rag-inputs.json', dict(schema_version=1,
            protocol_sha256=protocol_sha256, run_sha256=sha(output / 'run.json'),
            results_sha256=state['results_sha256'], rag_binding=binding,
            rag_calls=0, human_review_complete=False, rows=[dict(id=row['id'],
                audio_sha256=row['audio_sha256'], typed=row['reference'],
                baseline_raw=by_id[row['id']]['baseline']['text'],
                candidate_raw=by_id[row['id']]['candidate']['text'])
                for row in captured['rows'] if row['group'] == 'human']))
        review, _ = _read(packet / 'human-review-template.json')
        review.update(run_sha256=sha(output / 'run.json'), results_sha256=state['results_sha256'],
                      rag_binding=binding)
        _write_new(output / 'bound-human-review-template.json', review)
    return state


def edit_counts(reference, hypothesis):
    """Word alignment; diagonal, then deletion, then insertion resolves ties."""
    ref, hyp = normalize(reference).split(), normalize(hypothesis).split()
    table = [list(range(len(hyp) + 1))]
    for i, word in enumerate(ref, 1):
        row = [i]
        for j, predicted in enumerate(hyp, 1):
            row.append(min(table[-1][j-1] + (word != predicted), table[-1][j] + 1, row[-1] + 1))
        table.append(row)
    counts = dict(S=0, D=0, I=0)
    i, j = len(ref), len(hyp)
    while i or j:
        if i and j and table[i][j] == table[i-1][j-1] + (ref[i-1] != hyp[j-1]):
            counts['S'] += ref[i-1] != hyp[j-1]
            i, j = i-1, j-1
        elif i and table[i][j] == table[i-1][j] + 1:
            counts['D'] += 1
            i -= 1
        else:
            counts['I'] += 1
            j -= 1
    return counts


def summarize(run_dir, *, root=ROOT):
    """Recompute descriptive metrics; human-pending output never becomes approval."""
    root = Path(root).resolve()
    directory = _private_path(root, run_dir)
    state, _ = _read(directory / 'run.json')
    protocol, protocol_sha256 = _read(directory / 'protocol.json')
    manifest, manifest_sha256 = _read(directory / 'manifest-snapshot.json')
    if (protocol_sha256 != state.get('protocol_sha256')
            or manifest_sha256 != state.get('manifest_sha256')
            or sha(directory / 'results.jsonl') != state.get('results_sha256')):
        raise ValueError('Run evidence checksum differs.')
    results = [json.loads(line) for line in (directory / 'results.jsonl').read_text(encoding='utf-8').splitlines()]
    expected = manifest['human_rows'] + manifest['control_rows']
    complete = (state.get('completed') is True and len(results) == len(expected)
                and [r.get('id') for r in results] == [r['id'] for r in expected]
                and all(not r.get('error') and all(isinstance(r.get(arm), dict)
                    and isinstance(r[arm].get('text'), str) and not r[arm].get('error')
                    for arm in ('baseline', 'candidate')) for r in results))
    summary = dict(completed=complete, human_metrics=None, nonspeech_results=[],
                   service_tier=protocol.get('service_tier', 'paid'),
                   paid_fallback_allowed=False,
                   max_authorized_spend_usd=state.get('max_authorized_spend_usd'),
                   paid_equivalent_token_cost_estimate_usd=state.get(
                       'paid_equivalent_token_cost_estimate_usd', state.get('observed_token_cost_estimate_usd')),
                   known_paid_equivalent_token_cost_estimate_usd=state.get(
                       'known_paid_equivalent_token_cost_estimate_usd', state.get('known_token_cost_estimate_usd')),
                   actual_billed_cost_usd=state.get('actual_billed_cost_usd'),
                   quality_status='incomplete_no_aggregate' if not complete else 'pending_human_review',
                   human_review_complete=False, critical_new_errors=None,
                   task_success_no_regression=None, automatic_checks=None,
                   production_accepted=False, held_out_evaluation=False,
                   human_listening_performed=False, training_performed=False)
    if not complete:
        return summary
    by_id = {r['id']: r for r in results}
    metrics = {}
    for arm in ('baseline', 'candidate'):
        pairs = [dict(id=r['id'], reference=r['reference'], hypothesis=by_id[r['id']][arm]['text'])
                 for r in manifest['human_rows']]
        metrics[arm] = score(pairs)
        breakdown = [dict(id=pair['id'], **edit_counts(pair['reference'], pair['hypothesis']))
                     for pair in pairs]
        metrics[arm]['word_error_breakdown'] = dict(rows=breakdown,
            totals={key: sum(row[key] for row in breakdown) for key in ('S', 'D', 'I')},
            tie_rule='diagonal then deletion then insertion')
    summary['human_metrics'] = metrics
    for row in manifest['control_rows']:
        summary['nonspeech_results'].append(dict(id=row['id'], kind=row['control_kind'],
            baseline_false_accept=bool(by_id[row['id']]['baseline']['text'].strip()),
            candidate_false_accept=bool(by_id[row['id']]['candidate']['text'].strip())))
    baseline, candidate = metrics['baseline'], metrics['candidate']
    times = [by_id[r['id']]['candidate']['elapsed_seconds'] for r in manifest['human_rows']]
    checks = dict(
        cohort_matches=(len(manifest['human_rows']) == 13 and baseline['reference_words'] == 186
                        and baseline['reference_characters'] == 1089),
        baseline_matches=(baseline['word_edit_errors'] == 67 and baseline['character_edit_errors'] == 184),
        candidate_word_target=(candidate['word_edit_errors'] <= 60),
        candidate_character_no_regression=(candidate['character_edit_errors'] <= 184),
        latency_within_budget=(all(type(t) in (int, float) and math.isfinite(t) and 0 <= t <= 10 for t in times)),
        nonspeech_no_false_accept=(len(manifest['control_rows']) == 2 and not any(
            r['candidate_false_accept'] for r in summary['nonspeech_results'])))
    summary['automatic_checks'] = checks
    summary['candidate_max_elapsed_seconds'] = max(times)
    summary['candidate_median_elapsed_seconds'] = statistics.median(times)
    summary['paired_elapsed_seconds'] = [dict(id=row['id'],
        baseline=by_id[row['id']]['baseline']['elapsed_seconds'],
        candidate=by_id[row['id']]['candidate']['elapsed_seconds']) for row in manifest['human_rows']]
    summary['baseline_model_load_seconds'] = state.get('baseline_model_load_seconds')
    summary['runtime_versions'] = state.get('runtime_versions', {})
    review_path = directory / 'human-review.json'
    if review_path.is_file():
        review, _ = _read(review_path)
        records = review.get('records', [])
        rag_inputs, _ = _read(directory / 'rag-inputs.json')
        valid = (review.get('schema_version') == 1 and review.get('human_review_complete') is True
            and review.get('manifest_sha256') == manifest_sha256
            and review.get('protocol_sha256') == protocol_sha256
            and review.get('run_sha256') == sha(directory / 'run.json')
            and review.get('results_sha256') == state['results_sha256']
            and review.get('review_type') in {'developer_self_review', 'independent_review'}
            and review.get('judgments_origin') == 'human'
            and isinstance(review.get('rag_binding'), dict)
            and review.get('rag_binding') == rag_inputs.get('rag_binding')
            and rag_inputs.get('run_sha256') == sha(directory / 'run.json')
            and rag_inputs.get('results_sha256') == state['results_sha256']
            and bool(review['rag_binding'].get('code_sha256'))
            and len(review['rag_binding'].get('corpus_sha256', {})) == 2
            and isinstance(review.get('reviewer'), str) and bool(review['reviewer'].strip())
            and isinstance(review.get('reviewed_at_utc'), str) and bool(review['reviewed_at_utc'].strip())
            and isinstance(records, list) and len(records) == len(manifest['human_rows'])
            and [r.get('id') for r in records if isinstance(r, dict)] == [r['id'] for r in manifest['human_rows']]
            and all(type(r.get('critical_new_errors')) is int and r['critical_new_errors'] >= 0
                    and isinstance(r.get('critical_slots'), list)
                    and r.get('critical_slots_confirmed') is True
                    and all(isinstance(slot, dict) and isinstance(slot.get('field'), str)
                        and isinstance(slot.get('expected'), str) for slot in r['critical_slots'])
                    and type(r.get('typed_task_success')) is bool
                    and type(r.get('baseline_task_success')) is bool
                    and type(r.get('candidate_task_success')) is bool for r in records)
            and all(r['critical_slots'] == original.get('critical_slots')
                    for r, original in zip(records, manifest['human_rows'])))
        if valid:
            summary['human_review_complete'] = True
            summary['critical_new_errors'] = sum(r['critical_new_errors'] for r in records)
            summary['task_success_no_regression'] = all(not r['baseline_task_success']
                or r['candidate_task_success'] for r in records)
            acceptable = (all(checks.values()) and summary['critical_new_errors'] == 0
                          and summary['task_success_no_regression'])
            summary['quality_status'] = 'eligible_for_separate_promotion_review' if acceptable else 'rejected_by_predeclared_criteria'
    if not all(checks.values()):
        summary['quality_status'] = 'rejected_by_predeclared_criteria'
    return summary


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prep = commands.add_parser('prepare', help='offline review packet; no key/network/inference')
    prep.add_argument('--manifest', required=True)
    prep.add_argument('--output', required=True)
    prep.add_argument('--service-tier', choices=('paid', 'free'), default='paid')
    run = commands.add_parser('run', help='explicitly authorized private comparison only')
    for name in ('manifest', 'packet', 'output', 'approval'):
        run.add_argument('--' + name, required=True)
    report = commands.add_parser('summarize', help='read-only recomputation; does not promote a model')
    report.add_argument('--run', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'prepare':
            protocol = prepare(args.manifest, args.output, service_tier=args.service_tier)
            value = dict(state=protocol['state'], human_recordings=protocol['human_recordings'],
                         service_tier=protocol['service_tier'], paid_fallback_allowed=False,
                         control_recordings=protocol['control_recordings'], audio_seconds=protocol['audio_seconds'],
                         conservative_estimated_cost_usd=protocol['pricing']['conservative_estimated_cost_usd'],
                         network_calls=0, inference_calls=0)
        elif args.command == 'run':
            value = execute(args.manifest, args.packet, args.output, args.approval)
        else:
            value = summarize(args.run)
        print(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))
        return 0 if value.get('completed', True) else 1
    except (ValueError, FileExistsError, OSError, CandidateError) as exc:
        # CLI errors disclose no HTTP body, API key, local audio/reference, or token.
        print(json.dumps(dict(error=sanitized_error(exc), execution_stopped=True)))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
