"""Validate/freeze a real school-question STT *pilot*, without ASR or transcript creation.

JSON contract (all listed fields required; unknown fields rejected):
  schema_version: 1; study_kind: "real_school_question_pilot" or
    "single_speaker_school_question_pilot".
  speakers: [{speaker_id, speaker_group_id, consent_scope}]
    consent_scope: "evaluation_only" or "training_and_evaluation".
    speaker_group_id identifies the SAME person across any pseudonyms. This is a
    human-maintained identity declaration, not an automatic identity check.
  clips: [{clip_id, speaker_id, split, audio_path, audio_sha256,
           duration_seconds, recorded_at, device, room, scenario, elicitation,
           audio_origin, reference, transcript_review}]
    split: "train", "dev", or "test"; elicitation: "spontaneous_question";
    audio_origin: "real_human_recording". Paths are relative to --dataset-root.
    transcript_review: {confirmed: true, reviewer_id, reviewed_at,
                        uncertainties: []}
    Timestamps are timezone-aware ISO8601; review must follow recording.

Audio must actually be lossless, finite, nonzero mono 16kHz PCM16 or FLOAT32
WAV, at most30 seconds. A checked transcript, human origin, consent and question
content remain human assertions: this tool cannot prove them by inspecting JSON.
It does not listen, infer a transcript, assess accuracy, or invent participants.

validate_manifest returns structural/input errors and separate freeze_errors.
The multi-speaker mode requires every row valid, all three splits, and at least two distinct
canonical people in EACH split. This minimum is a pilot integrity rule, not a
claim of sufficient sample size or general accuracy. No person, audio SHA, or
normalized/space-stripped transcript may occur across splits. Exact duplicate
audio is rejected within a split too, to avoid counting a recording twice.

The explicit single-speaker mode requires exactly ONE canonical person across
the declared roster, evaluation_only consent and dev clips only. One or more
actually present, reviewed clips may freeze as personal development evidence.
It is NOT a speaker-independent test, permission for weight training or a claim
of general accuracy. Aliases of that one person remain one person.

CLI: python tools/stt_study_manifest.py validate --manifest MANIFEST --dataset-root ROOT
     python tools/stt_study_manifest.py freeze --manifest MANIFEST --dataset-root ROOT --output NEW_JSON
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import struct
import sys
import unicodedata


_SOURCE = Path(__file__).resolve()
_CODE_SHA256 = hashlib.sha256(_SOURCE.read_bytes()).hexdigest()
_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z')
_SHA = re.compile(r'[0-9a-f]{64}\Z')
_SPLITS = ('train', 'dev', 'test')
_SCOPES = {'evaluation_only', 'training_and_evaluation'}
_MULTI_SPEAKER = 'real_school_question_pilot'
_SINGLE_SPEAKER = 'single_speaker_school_question_pilot'
_ROOT_FIELDS = {'schema_version', 'study_kind', 'speakers', 'clips'}
_SPEAKER_FIELDS = {'speaker_id', 'speaker_group_id', 'consent_scope'}
_CLIP_FIELDS = {'clip_id', 'speaker_id', 'split', 'audio_path', 'audio_sha256',
                'duration_seconds', 'recorded_at', 'device', 'room', 'scenario',
                'elicitation', 'audio_origin', 'reference', 'transcript_review'}
_REVIEW_FIELDS = {'confirmed', 'reviewer_id', 'reviewed_at', 'uncertainties'}
_MAX_MANIFEST_BYTES = 8 * 1024 * 1024
_MAX_WAV_BYTES = 2 * 1024 * 1024


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _utc():
    return datetime.now(timezone.utc).isoformat()


def _normal(text):
    text = unicodedata.normalize('NFC', text).casefold()
    return ' '.join(''.join(' ' if unicodedata.category(c).startswith('P') else c
                            for c in text).split())


def _no_duplicates(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Duplicate JSON key: ' + key)
        value[key] = item
    return value


def _json(data):
    def reject_constant(value):
        raise ValueError('Non-finite JSON constant: ' + value)
    try:
        result = json.loads(data.decode('utf-8-sig'), object_pairs_hook=_no_duplicates,
                            parse_constant=reject_constant)
        def check_strings(value, depth=0):
            if depth > 16:
                raise ValueError('JSON nesting exceeds the manifest contract.')
            if isinstance(value, str):
                value.encode('utf-8')  # Reject escaped, unpaired Unicode surrogates.
            elif isinstance(value, dict):
                for key, item in value.items():
                    check_strings(key, depth + 1); check_strings(item, depth + 1)
            elif isinstance(value, list):
                for item in value:
                    check_strings(item, depth + 1)
        check_strings(result)
        return result
    except RecursionError as exc:
        raise ValueError('JSON nesting exceeds the manifest contract.') from exc


def _bounded_read(path, limit):
    with path.open('rb') as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise ValueError('File exceeds the declared size limit.')
    return data


def _fields(value, expected, location, errors):
    if not isinstance(value, dict):
        errors.append(dict(code='object_required', path=location, message='Expected an object.'))
        return False
    for key in sorted(expected - set(value)):
        errors.append(dict(code='missing_field', path=location + '.' + key, message='Required field is missing.'))
    for key in sorted(set(value) - expected):
        errors.append(dict(code='unknown_field', path=location + '.' + key, message='Unknown field; check the documented contract.'))
    return True


def _text(value, maximum):
    return (isinstance(value, str) and bool(value.strip()) and len(value) <= maximum
            and not any(ord(c) < 32 and c not in '\t\n\r' for c in value))


def _identity(value):
    return isinstance(value, str) and bool(_ID.fullmatch(value))


def _timestamp(value):
    if not isinstance(value, str) or len(value) > 48:
        raise ValueError('Expected timezone-aware ISO8601 timestamp.')
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError('Timestamp must include a timezone offset.')
    return result.astimezone(timezone.utc)


def _resolve_path(path):
    try:
        return Path(path).resolve(strict=True)
    except RuntimeError as exc:
        # Python3.11 reports symbolic-link loops as RuntimeError, not OSError.
        raise ValueError('Path cannot be resolved; possible symbolic-link loop.') from exc


def _audio_path(root, value):
    if not isinstance(value, str) or not value or len(value) > 240 or '\x00' in value:
        raise ValueError('Expected a bounded relative audio path.')
    portable = value.replace('\\', '/')
    win, posix = PureWindowsPath(value), PurePosixPath(portable)
    if (win.is_absolute() or win.drive or posix.is_absolute()
            or any(p in {'..', '.'} for p in portable.split('/'))
            or ':' in portable or not posix.parts):
        raise ValueError('Audio path must be relative and cannot traverse directories.')
    path = _resolve_path(root / Path(*posix.parts))
    if not path.is_relative_to(root) or not path.is_file() or path.suffix.casefold() != '.wav':
        raise ValueError('Audio must be an existing WAV inside the dataset root; escaping links are rejected.')
    return path


def _inspect_wav(data):
    """Strict RIFF/PCM16/FLOAT32 parser, including the corresponding extensible GUIDs."""
    if len(data) < 44 or data[:4] != b'RIFF' or data[8:12] != b'WAVE':
        raise ValueError('Expected a little-endian RIFF/WAVE file.')
    if struct.unpack_from('<I', data, 4)[0] + 8 != len(data):
        raise ValueError('RIFF length does not match the actual file bytes.')
    position, fmt, payload = 12, None, None
    while position < len(data):
        if position + 8 > len(data):
            raise ValueError('Truncated WAV chunk header.')
        kind, length = struct.unpack_from('<4sI', data, position)
        start = position + 8; end = start + length
        if end > len(data) or end + (length & 1) > len(data):
            raise ValueError('Truncated WAV chunk payload or padding.')
        if kind == b'fmt ':
            if fmt is not None or length < 16 or length > 64:
                raise ValueError('Require one bounded WAV format chunk.')
            fmt = data[start:end]
        elif kind == b'data':
            if payload is not None:
                raise ValueError('Require exactly one audio data chunk.')
            payload = data[start:end]
        position = end + (length & 1)
    if fmt is None or payload is None:
        raise ValueError('WAV format or audio data chunk is missing.')
    encoding, channels, rate, byte_rate, alignment, bits = struct.unpack_from('<HHIIHH', fmt)
    if encoding == 0xFFFE:
        if len(fmt) != 40 or struct.unpack_from('<H', fmt, 16)[0] != 22:
            raise ValueError('Invalid extensible WAV format.')
        valid_bits, mask = struct.unpack_from('<HI', fmt, 18)
        guid = fmt[24:40]
        subtype = struct.unpack_from('<I', guid)[0]
        if (valid_bits != bits or mask.bit_count() > 1
                or guid[4:] != bytes.fromhex('00001000800000aa00389b71')):
            raise ValueError('Unsupported extensible WAV subtype or channel mask.')
        encoding = subtype
    elif len(fmt) not in (16, 18) or (len(fmt) == 18 and struct.unpack_from('<H', fmt, 16)[0] != 0):
        raise ValueError('Unexpected extra WAV format bytes.')
    if channels != 1 or rate != 16000 or (encoding, bits) not in {(1, 16), (3, 32)}:
        raise ValueError('Require mono16kHz PCM16 or FLOAT32 WAV.')
    if alignment != bits // 8 or byte_rate != rate * alignment or len(payload) % alignment:
        raise ValueError('WAV frame alignment or byte rate is inconsistent.')
    frames = len(payload) // alignment
    if not 1 <= frames <= 30 * rate:
        raise ValueError('Audio must contain frames and last at most30 seconds.')
    if encoding == 3:
        samples = [x[0] for x in struct.iter_unpack('<f', payload)]
        if not all(math.isfinite(x) for x in samples):
            raise ValueError('FLOAT32 WAV contains non-finite samples.')
        nonzero = any(x != 0 for x in samples)
    else:
        nonzero = any(payload)
    if not nonzero:
        raise ValueError('All-zero audio cannot be a spoken question.')
    return dict(sample_rate=rate, channels=channels, frames=frames,
                sample_format='pcm16' if encoding == 1 else 'float32',
                duration_seconds=frames / rate)


def validate_manifest(manifest_path, dataset_root):
    """Return validation findings; never modify source/audio or create transcripts."""
    errors, freeze_errors, audio_audits = [], [], []
    counts = {s: dict(clips=0, speakers=0) for s in _SPLITS}
    report = dict(schema_version=1, checked_utc=_utc(), study_kind='real_school_question_pilot',
                  valid=False, freeze_ready=False, errors=errors, freeze_errors=freeze_errors,
                  counts=counts, audio_audits=audio_audits, source_sha256=None,
                  validator_sha256=_CODE_SHA256, minimum_canonical_speakers_per_split=2,
                  measured_accuracy=None,
                  limitations=['Consent, real human origin, spontaneous question content and actual human listening are recorded human declarations, not automatically verified facts.',
                               'Two speakers per split is a pilot integrity minimum, not a sufficient general-accuracy study.'])
    def error(code, location, message):
        errors.append(dict(code=code, path=location, message=message))
    try:
        root = _resolve_path(dataset_root)
        if not root.is_dir():
            raise ValueError('Dataset root is not a directory.')
        source = _resolve_path(manifest_path)
        source_bytes = _bounded_read(source, _MAX_MANIFEST_BYTES)
        manifest = _json(source_bytes)
        report['source_sha256'] = _sha(source_bytes)
    except (OSError, ValueError, UnicodeError, TypeError) as exc:
        error('unreadable_manifest_or_root', '$', str(exc))
        return report
    if not _fields(manifest, _ROOT_FIELDS, '$', errors):
        return report
    if type(manifest.get('schema_version')) is not int or manifest['schema_version'] != 1:
        error('schema_version', '$.schema_version', 'Expected integer schema_version1.')
    kind = manifest.get('study_kind')
    if kind not in (_MULTI_SPEAKER, _SINGLE_SPEAKER):
        error('study_kind', '$.study_kind', 'Use the explicit multi-speaker or single-speaker school-question pilot mode.')
    single_speaker = kind == _SINGLE_SPEAKER
    report['study_kind'] = kind
    if single_speaker:
        report.update(analysis_scope='single_speaker_development', evaluation_only=True,
                      speaker_independent=False, eligible_for_weight_training=False,
                      heldout_test=False, general_accuracy_claim=False,
                      minimum_canonical_speakers_per_split=None, required_splits=['dev'])
        report['limitations'][1] = ('One canonical person may provide reviewed dev questions. '
            'This is personal diagnostic evidence, not a speaker-independent or heldout test, '
            'weight-training authorization, or general-accuracy evidence.')
    roster, clips = manifest.get('speakers'), manifest.get('clips')
    if not isinstance(roster, list) or not 1 <= len(roster) <= 5000:
        error('speakers_required', '$.speakers', 'Provide1..5000 declared speakers; do not invent missing participants.')
        roster = []
    if not isinstance(clips, list) or not 1 <= len(clips) <= 10000:
        error('clips_required', '$.clips', 'Provide1..10000 real recorded questions; an empty collection is incomplete.')
        clips = []
    speakers = {}
    for index, speaker in enumerate(roster):
        location = f'$.speakers[{index}]'
        if not _fields(speaker, _SPEAKER_FIELDS, location, errors):
            continue
        sid, group = speaker.get('speaker_id'), speaker.get('speaker_group_id')
        if not _identity(sid) or not _identity(group):
            error('speaker_identity', location, 'Use bounded ASCII pseudonyms and a stable canonical person group ID.')
            continue
        key = sid.casefold()
        if key in speakers:
            error('duplicate_speaker_id', location + '.speaker_id', 'Speaker pseudonyms must be unique ignoring case.')
            continue
        if not isinstance(speaker.get('consent_scope'), str) or speaker['consent_scope'] not in _SCOPES:
            error('consent_scope', location + '.consent_scope', 'Explicit evaluation_only or training_and_evaluation scope is required.')
        if single_speaker and speaker.get('consent_scope') != 'evaluation_only':
            error('single_speaker_evaluation_only', location + '.consent_scope',
                  'The single-speaker diagnostic mode requires explicit evaluation_only scope; it does not authorize weight training.')
        speakers[key] = speaker
    if single_speaker and len({speaker['speaker_group_id'].casefold() for speaker in speakers.values()}) != 1:
        error('single_speaker_required', '$.speakers',
              'Declare exactly one canonical person; aliases cannot turn this into a multi-person study.')
    ids, group_splits, audio_seen, text_seen, compact_seen = set(), {}, {}, {}, {}
    split_groups = {s: set() for s in _SPLITS}
    for index, clip in enumerate(clips):
        location = f'$.clips[{index}]'
        if not _fields(clip, _CLIP_FIELDS, location, errors):
            continue
        cid, sid, split = clip.get('clip_id'), clip.get('speaker_id'), clip.get('split')
        if not _identity(cid) or cid.casefold() in ids:
            error('clip_identity', location + '.clip_id', 'Clip IDs must be bounded unique pseudonyms ignoring case.')
        else:
            ids.add(cid.casefold())
        if split not in _SPLITS:
            error('split', location + '.split', 'Assign train, dev, or test before recognition outputs.')
        else:
            counts[split]['clips'] += 1
        if single_speaker and split != 'dev':
            error('single_speaker_dev_only', location + '.split',
                  'Single-speaker diagnostic recordings belong only to dev, never train or test.')
        speaker = speakers.get(sid.casefold()) if _identity(sid) else None
        if speaker is None:
            error('unknown_speaker', location + '.speaker_id', 'Clip must refer to a declared speaker.')
        elif split in _SPLITS:
            group = speaker['speaker_group_id'].casefold()
            split_groups[split].add(group)
            if group in group_splits and group_splits[group] != split:
                error('speaker_split_leakage', location + '.speaker_id', 'The same canonical person cannot occur in different splits, even under different pseudonyms.')
            group_splits[group] = split
            if split == 'train' and speaker.get('consent_scope') != 'training_and_evaluation':
                error('training_consent_required', location + '.speaker_id', 'Evaluation-only recordings must never enter training.')
        for key, maximum in (('device', 160), ('room', 160), ('scenario', 600)):
            if not _text(clip.get(key), maximum):
                error('context_required', location + '.' + key, 'Provide bounded nonempty recording context.')
        if clip.get('elicitation') != 'spontaneous_question':
            error('not_spontaneous_question', location + '.elicitation', 'This corpus is for spontaneous questions, not reading or guided answers.')
        if clip.get('audio_origin') != 'real_human_recording':
            error('not_real_recording', location + '.audio_origin', 'Synthetic or generated speech does not belong in this real-question pilot.')
        reference = clip.get('reference')
        if not _text(reference, 4000) or not _normal(reference):
            error('reference_required', location + '.reference', 'A nonempty human-listened transcript is required; do not fill it with a model guess.')
        elif split in _SPLITS:
            normalized = _normal(reference)
            for key, seen, code in ((normalized, text_seen, 'transcript_split_duplicate'),
                                    (normalized.replace(' ', ''), compact_seen, 'compact_transcript_split_duplicate')):
                if key in seen and seen[key] != split:
                    error(code, location + '.reference', 'A normalized transcript occurs across splits; paraphrase/spacing does not establish independence.')
                seen[key] = split
        review = clip.get('transcript_review')
        if _fields(review, _REVIEW_FIELDS, location + '.transcript_review', errors):
            if review.get('confirmed') is not True or not _identity(review.get('reviewer_id')):
                error('human_review_unconfirmed', location + '.transcript_review', 'Require explicit true confirmation and reviewer pseudonym after listening.')
            uncertainty = review.get('uncertainties')
            if not isinstance(uncertainty, list) or uncertainty:
                error('unresolved_uncertainty', location + '.transcript_review.uncertainties', 'Unresolved words/numbers must be reviewed; this list must be empty before freezing.')
        try:
            recorded = _timestamp(clip.get('recorded_at'))
            reviewed = _timestamp(review.get('reviewed_at') if isinstance(review, dict) else None)
            now = datetime.now(timezone.utc)
            if reviewed <= recorded or reviewed > now or recorded > now:
                raise ValueError('Review must be after recording; neither event may be in the future.')
        except (ValueError, TypeError, OverflowError) as exc:
            error('review_chronology', location + '.transcript_review.reviewed_at', str(exc))
        expected = clip.get('audio_sha256')
        if not isinstance(expected, str) or not _SHA.fullmatch(expected):
            error('audio_sha256', location + '.audio_sha256', 'Expected lowercase SHA256 of the actual WAV bytes.')
        duration = clip.get('duration_seconds')
        # Compare the bounded range before converting an arbitrary JSON integer
        # to float: math.isfinite(10**1000) raises OverflowError.
        duration_valid = (type(duration) in (int, float) and 0 < duration <= 30
                          and math.isfinite(duration))
        if not duration_valid:
            error('duration', location + '.duration_seconds', 'Declare finite actual duration in seconds, greater than0 and at most30.')
        try:
            path = _audio_path(root, clip.get('audio_path'))
            data = _bounded_read(path, _MAX_WAV_BYTES)
            actual = _sha(data)
            audit = _inspect_wav(data)
            if actual != expected:
                error('audio_hash_mismatch', location + '.audio_sha256', 'WAV bytes differ from the declared hash.')
            if duration_valid and abs(duration - audit['duration_seconds']) > .001:
                error('audio_duration_mismatch', location + '.duration_seconds', 'Declared duration differs from actual frames by more than1ms.')
            if actual in audio_seen:
                error('duplicate_audio', location + '.audio_path', 'The same audio SHA cannot be counted twice or shared across splits.')
            audio_seen[actual] = split
            audio_audits.append(dict(clip_id=cid, audio_path=clip.get('audio_path'),
                                     sha256=actual, bytes=len(data), **audit))
        except (OSError, ValueError, TypeError, struct.error) as exc:
            error('invalid_audio', location + '.audio_path', str(exc))
    for split in _SPLITS:
        counts[split]['speakers'] = len(split_groups[split])
        if not single_speaker and counts[split]['speakers'] < 2:
            freeze_errors.append(dict(code='insufficient_split_speakers', path=split,
                                      message='Freeze requires at least2 distinct canonical real speakers in each of train/dev/test.'))
    try:
        if _sha(_bounded_read(source, _MAX_MANIFEST_BYTES)) != report['source_sha256']:
            error('source_changed_during_validation', '$', 'Manifest bytes changed while validating.')
    except (OSError, ValueError) as exc:
        error('source_changed_during_validation', '$', str(exc))
    report['valid'] = not errors
    report['freeze_ready'] = not errors and not freeze_errors
    return report


def freeze_manifest(manifest_path, dataset_root, output_path):
    """Create one immutable-by-convention evidence JSON; never overwrite a file."""
    root = _resolve_path(dataset_root)
    report = validate_manifest(manifest_path, root)
    if not report['freeze_ready']:
        codes = [e['code'] for e in report['errors'] + report['freeze_errors']]
        raise ValueError('Manifest is not ready to freeze: ' + ', '.join(codes))
    source = _resolve_path(manifest_path)
    source_bytes = _bounded_read(source, _MAX_MANIFEST_BYTES)
    if _sha(source_bytes) != report['source_sha256']:
        raise ValueError('source_changed_after_validation')
    for row in report['audio_audits']:
        path = _audio_path(root, row['audio_path'])
        if _sha(_bounded_read(path, _MAX_WAV_BYTES)) != row['sha256']:
            raise ValueError('audio_changed_after_validation: ' + row['clip_id'])
    if _sha(_SOURCE.read_bytes()) != _CODE_SHA256:
        raise ValueError('validator_code_changed_after_import')
    single_speaker = report['study_kind'] == _SINGLE_SPEAKER
    artifact = dict(schema_version=1, artifact_kind=('frozen_single_speaker_school_question_pilot'
                    if single_speaker else 'frozen_real_school_question_pilot'),
                    frozen_utc=_utc(), source_manifest_sha256=report['source_sha256'],
                    validator=dict(path='tools/stt_study_manifest.py', sha256=_CODE_SHA256),
                    manifest=_json(source_bytes), validation=report,
                    no_asr_performed=True, no_transcript_created=True, measured_accuracy=None)
    if single_speaker:
        artifact.update(analysis_scope='single_speaker_development', evaluation_only=True,
                        speaker_independent=False, eligible_for_weight_training=False,
                        heldout_test=False, general_accuracy_claim=False)
    payload = (json.dumps(artifact, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # x mode rejects existing files AND existing symlinks, without touching them.
    with destination.open('xb') as handle:
        handle.write(payload)
    result = dict(output=str(destination), sha256=_sha(payload), counts=report['counts'],
                  frozen_utc=artifact['frozen_utc'], measured_accuracy=None)
    if single_speaker:
        result.update(artifact_kind=artifact['artifact_kind'],
                      analysis_scope='single_speaker_development', evaluation_only=True,
                      speaker_independent=False, eligible_for_weight_training=False,
                      heldout_test=False, general_accuracy_claim=False)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    for command in ('validate', 'freeze'):
        sub = commands.add_parser(command)
        sub.add_argument('--manifest', type=Path, required=True)
        sub.add_argument('--dataset-root', type=Path, required=True)
        if command == 'freeze':
            sub.add_argument('--output', type=Path, required=True, help='New JSON path; existing files are never overwritten.')
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    try:
        result = (freeze_manifest(args.manifest, args.dataset_root, args.output)
                  if args.command == 'freeze' else validate_manifest(args.manifest, args.dataset_root))
    except (OSError, ValueError) as exc:
        print(json.dumps(dict(valid=False, error=str(exc)), ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if args.command == 'freeze' or result['valid'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
