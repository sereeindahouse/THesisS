"""Offline decoder experiments; human speech and synthetic controls stay separate."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
import sys
import time
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from score import score
from stt_mn import load_choice

BASE_DECODING = dict(language='mn', task='transcribe', beam_size=5, vad_filter=False,
                     temperature=0.0, without_timestamps=True,
                     condition_on_previous_text=False)
PINNED_SOURCE = 'Cafet/whisper-small-mongolian'
PINNED_REVISION = 'd54c63a518d6dea7ab54a27c83d0b6b52bea3e9d'
PINNED_SHA256 = '7a2a3f0a939addbd2ae9532dfb2b16590ecc3fbb145a214b784b05797e202843'
_ID = re.compile(r'[a-zA-Z0-9][a-zA-Z0-9._-]{0,100}\Z')
_SHA = re.compile(r'[0-9a-f]{64}\Z')
_WINDOWS_DEVICE_NAMES = {'con', 'prn', 'aux', 'nul'} | {
    prefix + str(number) for prefix in ('com', 'lpt') for number in range(1, 10)}


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def read_frozen_json(path):
    """Parse and fingerprint the same captured bytes, never a second read."""
    data = path.read_bytes()
    return json.loads(data.decode('utf-8-sig')), hashlib.sha256(data).hexdigest()


def audit_wav(path):
    """Inspect the actual PCM WAV without importing a private pilot runner."""
    with wave.open(str(path), 'rb') as handle:
        channels, width, rate, count = (handle.getnchannels(), handle.getsampwidth(),
                                       handle.getframerate(), handle.getnframes())
        if width != 2 or channels not in (1, 2) or not 8000 <= rate <= 48000:
            raise ValueError('Require a PCM16 mono/stereo WAV at 8–48 kHz.')
        payload = handle.readframes(count)
        if len(payload) != count * channels * width:
            raise ValueError('Truncated WAV frames.')
    return dict(sample_rate=rate, channels=channels, sample_width_bytes=width,
                frames=count, seconds=count / rate, all_zero=not any(payload), sha256=sha(path))


def save_new(path, value):
    with path.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write('\n')


def local_path(root, value):
    path = Path(value)
    path = (path if path.is_absolute() else root / path).resolve()
    if not path.is_relative_to(root):
        raise ValueError('Experiment paths must remain inside the project root.')
    return path


def decoding_for(config, arm):
    if config.get('schema_version') != 1 or not isinstance(config.get('arms'), dict):
        raise ValueError('Expected schema_version=1 and an arms mapping.')
    change = config['arms'].get(arm)
    if not _ID.fullmatch(arm) or not isinstance(change, dict):
        raise ValueError('Unknown experiment arm.')
    if set(change) - {'hotwords', 'beam_size', 'initial_prompt'} or len(change) > 1:
        raise ValueError('An arm may change one of hotwords, beam_size or initial_prompt.')
    if 'beam_size' in change and (type(change['beam_size']) is not int or change['beam_size'] != 10):
        raise ValueError('The beam comparison is fixed at beam_size=10.')
    for name in ('hotwords','initial_prompt'):
        if name not in change:
            continue
        value = change[name]
        if (not isinstance(value, str) or not value.strip() or len(value) > 1200
                or any(ord(char) < 32 for char in value)):
            raise ValueError(name+' must be a nonempty bounded single-line string.')
    return dict(BASE_DECODING, **change)


def manifest_rows(root, manifest):
    if manifest.get('schema_version') != 1:
        raise ValueError('Expected manifest schema_version=1.')
    humans, controls = manifest.get('human_rows'), manifest.get('control_rows')
    if not isinstance(humans, list) or not isinstance(controls, list) or not humans + controls:
        raise ValueError('Supply human_rows/control_rows lists with at least one recording.')
    if len(humans) + len(controls) > 100:
        raise ValueError('This bounded development experiment accepts at most 100 recordings.')
    rows, ids = [], set()
    for group, values in (('human', humans), ('control', controls)):
        for row in values:
            if not isinstance(row, dict):
                raise ValueError('Manifest recordings must be objects.')
            identity, expected, reference = row.get('id'), row.get('audio_sha256'), row.get('reference')
            if (not isinstance(identity, str) or not _ID.fullmatch(identity) or identity.casefold() in ids
                    or identity.casefold() in {'protocol', 'summary'}
                    or identity.partition('.')[0].casefold() in _WINDOWS_DEVICE_NAMES
                    or not isinstance(expected, str) or not _SHA.fullmatch(expected)
                    or not isinstance(reference, str)):
                raise ValueError('Recording IDs, SHA256 or reference fields are invalid.')
            ids.add(identity.casefold())
            if group == 'human':
                if row.get('reference_status') != 'eligible_speaker_confirmed' or not reference.strip():
                    raise ValueError('Human metrics require an explicitly confirmed nonempty reference.')
                kind = 'human_speech'
            else:
                kind = row.get('control_kind')
                if row.get('reference_status') != 'synthetic_control' or kind not in {'synthetic_speech', 'silence', 'noise'}:
                    raise ValueError('Control rows require their synthetic status and explicit kind.')
                if (kind == 'synthetic_speech' and not reference.strip()
                        or kind in {'silence', 'noise'} and reference.strip()):
                    raise ValueError('Synthetic speech needs text; nonspeech controls must have an empty reference.')
            path = local_path(root, row['audio_path'])
            if path.suffix.casefold() != '.wav' or not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
                raise ValueError('Require an existing local WAV of at most 8 MiB.')
            audit = audit_wav(path)
            if audit['sha256'] != expected:
                raise ValueError('Frozen audio checksum differs: ' + identity)
            if audit['seconds'] <= 0 or audit['seconds'] > 30:
                raise ValueError('Recordings must be longer than zero and at most 30 seconds.')
            rows.append(dict(row, group=group, kind=kind, path=path, audio_audit=audit))
    return rows


def run(config_path, arm, manifest_path, output_dir, *, root=ROOT):
    root = Path(root).resolve()
    output_dir = local_path(root, output_dir)
    # Refuse even an empty previous directory before model verification/loading.
    if output_dir.exists():
        raise FileExistsError('Output directory already exists; preserve the previous run.')
    config_path, manifest_path = local_path(root, config_path), local_path(root, manifest_path)
    config, config_sha256 = read_frozen_json(config_path)
    manifest, manifest_sha256 = read_frozen_json(manifest_path)
    decoding = decoding_for(config, arm)
    rows = manifest_rows(root, manifest)
    if sha(config_path) != config_sha256 or sha(manifest_path) != manifest_sha256:
        raise ValueError('Configuration or manifest changed after its input snapshot.')
    choice, model_path = load_choice(root)
    if ((choice.get('source_repo'), choice.get('source_revision'), choice.get('model_sha256'))
            != (PINNED_SOURCE, PINNED_REVISION, PINNED_SHA256)
            or choice.get('decoding') != BASE_DECODING
            or choice.get('device') != 'cpu' or choice.get('compute_type') != 'int8'):
        raise ValueError('Only the pinned Cafet CPU/int8 baseline may be varied.')
    model_path = Path(model_path).resolve()
    if not model_path.is_relative_to((root / 'models').resolve()):
        raise ValueError('Require the existing model inside the local models directory.')
    model_manifest_path = model_path / 'download-manifest.json'
    model_manifest = read_json(model_manifest_path)
    model_files = {}
    for name, metadata in model_manifest['files'].items():
        path = (model_path / name).resolve()
        if not path.is_relative_to(model_path) or sha(path) != metadata['sha256']:
            raise ValueError('Pinned model asset checksum differs: ' + name)
        model_files[name] = metadata['sha256']
    protocol = dict(created_utc=datetime.now(timezone.utc).isoformat(), arm=arm,
        experiment='local decoder-only development comparison', training_performed=False,
        model=PINNED_SOURCE, revision=PINNED_REVISION, model_sha256=PINNED_SHA256,
        model_source=str(model_path.relative_to(root)), device='cpu', compute_type='int8',
        local_files_only=True, private_audio_uploaded=False, network_calls=0, llm_calls=0,
        baseline_decoding=dict(BASE_DECODING), decoding=decoding,
        config_path=str(config_path.relative_to(root)), config_sha256=config_sha256,
        manifest_path=str(manifest_path.relative_to(root)), manifest_sha256=manifest_sha256,
        model_manifest_sha256=sha(model_manifest_path), model_asset_sha256=model_files,
        code_sha256={name: sha(ROOT / name) for name in
            ('tools/evaluate_stt_context.py', 'stt_mn.py', 'score.py')},
        versions={name: importlib.metadata.version(name) for name in
            ('faster-whisper', 'ctranslate2', 'av', 'numpy')},
        recordings=[dict(id=row['id'], group=row['group'], kind=row['kind'],
                         audio_sha256=row['audio_sha256']) for row in rows],
        reference_used_for_inference=False, automatic_postcorrection=False,
        production_accepted=False, held_out_evaluation=False)
    output_dir.mkdir(parents=True, exist_ok=False)
    save_new(output_dir / 'protocol.json', protocol)
    from faster_whisper import WhisperModel
    loaded = time.perf_counter()
    model = WhisperModel(str(model_path), device='cpu', compute_type='int8', local_files_only=True)
    load_seconds = time.perf_counter() - loaded
    human_pairs, control_pairs, nonspeech, outputs = [], [], [], []
    for index, row in enumerate(rows, 1):
        print(f'{index}/{len(rows)} {arm} {row["id"]}: transcribing locally', flush=True)
        if sha(row['path']) != row['audio_sha256']:
            raise ValueError('Audio changed after protocol freeze: ' + row['id'])
        started = time.perf_counter()
        segments, info = model.transcribe(str(row['path']), **decoding)
        segments = [dict(start=float(segment.start), end=float(segment.end), text=segment.text.strip(),
                         avg_logprob=float(segment.avg_logprob), no_speech_prob=float(segment.no_speech_prob))
                    for segment in segments]
        elapsed = time.perf_counter() - started
        if sha(row['path']) != row['audio_sha256']:
            raise ValueError('Audio changed during inference: ' + row['id'])
        text = ' '.join(segment['text'] for segment in segments).strip()
        result = dict(id=row['id'], group=row['group'], control_kind=row['kind'],
            audio_path=row['audio_path'], audio_sha256=row['audio_sha256'], audio_audit=row['audio_audit'],
            created_utc=datetime.now(timezone.utc).isoformat(), text=text, segments=segments,
            transcription_seconds=elapsed, model_load_seconds=load_seconds,
            decoder_duration=float(info.duration), actual_compute_type=model.model.compute_type,
            protocol_file='protocol.json', protocol_sha256=sha(output_dir / 'protocol.json'),
            reference_used_for_inference=False, automatic_postcorrection=False, training_performed=False)
        save_new(output_dir / (row['id'] + '.json'), result)
        outputs.append(result)
        pair = dict(id=row['id'], reference=row['reference'], hypothesis=text)
        if row['group'] == 'human':
            human_pairs.append(pair)
        elif row['kind'] == 'synthetic_speech':
            control_pairs.append(pair)
        else:
            nonspeech.append(dict(id=row['id'], kind=row['kind'], text=text, empty_output=not bool(text)))
        print(f'{index}/{len(rows)} {row["id"]}: saved ({elapsed:.2f}s)', flush=True)
    if sha(config_path) != protocol['config_sha256'] or sha(manifest_path) != protocol['manifest_sha256']:
        raise ValueError('Frozen configuration or manifest changed during inference.')
    summary = dict(created_utc=datetime.now(timezone.utc).isoformat(), arm=arm, completed=True,
        protocol_sha256=sha(output_dir / 'protocol.json'), human_recordings=len(human_pairs),
        human_metrics=score(human_pairs) if human_pairs else None,
        control_speech_recordings=len(control_pairs),
        control_speech_metrics=score(control_pairs) if control_pairs else None,
        nonspeech_results=nonspeech, nonspeech_nonempty_count=sum(not row['empty_output'] for row in nonspeech),
        total_transcription_seconds=sum(row['transcription_seconds'] for row in outputs),
        model_load_seconds=load_seconds, training_performed=False, private_audio_uploaded=False,
        automatic_postcorrection=False, production_accepted=False, human_listening_performed=False,
        limitations=['Observed development cohort, not held-out or population ASR accuracy.',
                    'Synthetic speech and nonspeech controls are never pooled into human WER/CER.',
                    'A contextual decoder hypothesis remains unconfirmed raw model output.',
                    'Numbers are scored using the unchanged project normalization; no reference-based correction.'])
    save_new(output_dir / 'summary.json', summary)
    print(json.dumps({key: summary[key] for key in ('human_recordings', 'human_metrics',
          'control_speech_recordings', 'control_speech_metrics', 'nonspeech_nonempty_count')}, ensure_ascii=False), flush=True)
    return summary


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--arm', required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    run(args.config, args.arm, args.manifest, args.output_dir)


if __name__ == '__main__':
    main()
