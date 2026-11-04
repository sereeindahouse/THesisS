"""Offline-only saved STT evaluation. Stdout contains counts, never private text.

prepare freezes reference-only labels/sources; run then scores both saved arms.
Neither command opens audio, a credential, a speech provider or a network socket.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

from stt_text_normalization import Normalizer
from tools.stt_normalization_metrics import ARMS, annotate_reference, paired_inputs, score_texts
from tools.stt_normalization_reference import draft_rubric, validate_rubric
from tools.stt_normalization_retrieval import FrozenRetrieval, snapshot_database, support_rank

INPUTS = ('runtime/stt-vocabulary-ab-20261103/results.jsonl',
          'runtime/stt-candidate-20261029/manifest.json',
          'config/stt-vocabulary.json', 'config/stt-text-normalization.json')
CODES = ('tools/evaluate_stt_normalization.py', 'tools/stt_normalization_metrics.py',
         'tools/stt_normalization_reference.py', 'tools/stt_normalization_retrieval.py',
         'stt_text_normalization.py', 'score.py', 'tools/compare_stt_vocabulary.py',
         'website_retrieval.py', 'CORE/website_corpus.py', 'CORE/document_corpus.py',
         'CORE/client_tab_corpus.py', 'config/model-catalog/intfloat--multilingual-e5-small.json')
DEFAULT_OUTPUT = 'runtime/stt-normalization-offline-20261104/verified-v2'
MODEL = 'gemini-3.5-transcribe'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def read(path):
    raw = Path(path).read_bytes()
    if len(raw) > 32 * 1024 * 1024:
        raise ValueError('bounded_json_required')
    return json.loads(raw.decode('utf-8-sig'))


def write_new(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def output_path(root, value):
    root = Path(root).resolve()
    path = (root / value).resolve()
    if not path.is_relative_to(root / 'runtime') or path == root / 'runtime':
        raise ValueError('private_output_required')
    return path


def install_guard(output):
    """Fail closed for network/audio/credentials and writes outside this run."""
    output = Path(output).resolve()
    import tempfile
    import socket
    # Local-only libraries otherwise probe IPv6 by opening a socket and test
    # writable system temp directories. Keep both probes inside this process.
    socket.has_ipv6 = False
    (output / 'tmp').mkdir(parents=True, exist_ok=True)
    tempfile.tempdir = str(output / 'tmp')
    os.environ.update(TMP=str(output / 'tmp'), TEMP=str(output / 'tmp'))
    devnull = Path(os.devnull).resolve()
    counts = dict(network_attempts=0, audio_open_attempts=0, credential_open_attempts=0,
                  outside_write_attempts=0, blocked_subprocess_attempts=0)
    audio = {'.wav', '.mp3', '.flac', '.ogg', '.m4a', '.webm', '.aac', '.pcm', '.opus'}
    def audit(event, args):
        # Constructing an unconnected socket is not a network operation.
        # Deny every audited address lookup, bind, connect and send operation.
        if event.startswith('socket.') and event not in {'socket.gethostname', 'socket.__new__'}:
            counts['network_attempts'] += 1
            raise PermissionError('offline_network_blocked')
        if event == 'subprocess.Popen':
            # platform.py may probe the Windows version through cmd /c ver.
            # Keep all child processes blocked, but do not call them networking.
            counts['blocked_subprocess_attempts'] += 1
            raise PermissionError('offline_subprocess_blocked')
        if event == 'open' and args and isinstance(args[0], (str, bytes, os.PathLike)):
            path = Path(os.fsdecode(args[0])).resolve()
            if path.suffix.casefold() in audio:
                counts['audio_open_attempts'] += 1
                raise PermissionError('audio_access_blocked')
            if path.suffix.casefold() == '.dpapi' or any(
                    part.casefold() in {'secrets', '.aws', '.env'} or 'credentials' in part.casefold()
                    for part in path.parts):
                counts['credential_open_attempts'] += 1
                raise PermissionError('credential_access_blocked')
            mode, flags = args[1:3]
            writing = (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (
                isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
            if writing and path != devnull and not path.is_relative_to(output):
                counts['outside_write_attempts'] += 1
                raise PermissionError('outside_output_write_blocked')
    sys.addaudithook(audit)
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_DATASETS_OFFLINE='1',
                      HF_HUB_DISABLE_TELEMETRY='1', TOKENIZERS_PARALLELISM='false',
                      HF_HOME=str(output / 'cache' / 'hf'), TORCH_HOME=str(output / 'cache' / 'torch'))
    return counts


def fingerprints(root):
    return {name: sha(root / name) for name in INPUTS + CODES}


def require_inputs_unchanged(root, protocol):
    if fingerprints(root) != protocol['input_and_code_sha256']:
        raise ValueError('inputs_or_code_changed')


def prepare(root, output, *, expected_count=12):
    if (output / 'protocol.json').exists() or (output / 'corpus.db').exists():
        raise FileExistsError('new_private_directory_required')
    before = fingerprints(root)
    manifest = read(root / INPUTS[1])
    saved = [json.loads(line) for line in (root / INPUTS[0]).read_text(encoding='utf-8').splitlines()]
    inputs = paired_inputs(manifest, saved, expected_count=expected_count)
    vocabulary, options = read(root / INPUTS[2]), read(root / INPUTS[3])
    if vocabulary.get('model') != MODEL or options.get('enabled') is not False:
        raise ValueError('unexpected_model_or_normalizer_flag')
    output.mkdir(parents=True, exist_ok=True)
    snapshot = snapshot_database(root / 'CORE/database/website.db', output / 'corpus.db')
    with FrozenRetrieval(root, output / 'corpus.db') as retrieval:
        corpus = retrieval.corpus_rows()
        # Corpus inspection uses only typed references; no raw ranking is run.
        rubric = draft_rubric(inputs['rows'], corpus, terms=vocabulary['terms'])
        validate_rubric(rubric, inputs['rows'], corpus)
        annotations = {r['id']: annotate_reference(r['reference'], r.get('critical_slots', []),
                                                  vocabulary['terms']) for r in inputs['rows']}
        write_new(output / 'inputs-private.json', inputs)
        write_new(output / 'annotations-private.json', annotations)
        write_new(output / 'rubric-private.json', rubric)
        write_new(output / 'corpus-private.json', corpus)
        write_new(output / 'vocabulary-private.json', vocabulary)
        protocol = dict(schema_version=1, model=MODEL, as_of='2026-11-04',
            created_utc=datetime.now(timezone.utc).isoformat(), primary_arm='vocabulary',
            expected_paired_clips=expected_count, input_and_code_sha256=before,
            source_snapshot=snapshot, retrieval=retrieval.status(),
            gate='top3_gain>=1; top3_loss=0; critical/name/term_new_errors=0; outside_span_changes=0',
            reference_origin=rubric['reference_origin'], human_reviewed=False,
            private_sha256={name: sha(output / name) for name in ('inputs-private.json',
                'annotations-private.json', 'rubric-private.json', 'corpus-private.json', 'vocabulary-private.json')})
    require_inputs_unchanged(root, protocol)
    write_new(output / 'protocol.json', protocol)
    return dict(prepared=True, paired_clips=len(inputs['rows']),
                reference_classes=dict(Counter(r['answerability'] for r in rubric['records'])),
                raw_or_normalized_rankings_executed=0)


def outside_span_changes(raw, derivative):
    if derivative['original_text'] != raw:
        return True
    cursor, chunks = 0, []
    for span in derivative['replacements']:
        if span['start'] < cursor or raw[span['start']:span['end']] != span['original']:
            return True
        chunks.extend((raw[cursor:span['start']], span['replacement']))
        cursor = span['end']
    chunks.append(raw[cursor:])
    return ''.join(chunks) != derivative['normalized_search_text']


def regressions(before, after, key):
    count = 0
    for a, b in zip(before['rows'], after['rows']):
        if a['id'] != b['id']:
            raise ValueError('paired_metric_order_changed')
        for x, y in zip(a[key]['records'], b[key]['records']):
            count += x.get('found') is True and y.get('found') is False
    return count


def run(root, output, guard_counts):
    protocol = read(output / 'protocol.json')
    if (output / 'summary.json').exists():
        raise FileExistsError('results_already_exist')
    require_inputs_unchanged(root, protocol)
    for name, digest in protocol['private_sha256'].items():
        if sha(output / name) != digest:
            raise ValueError('frozen_reference_changed')
    if sha(output / 'corpus.db') != protocol['source_snapshot']['database_sha256']:
        raise ValueError('snapshot_changed')
    inputs = read(output / 'inputs-private.json')
    annotations, rubric = read(output / 'annotations-private.json'), read(output / 'rubric-private.json')
    vocabulary = read(output / 'vocabulary-private.json')
    normalizer = Normalizer(enabled=True, terms=vocabulary['terms'])
    metrics, derivatives, variants = {}, {}, {}
    outside = 0
    for arm in ARMS:
        derivatives[arm] = {r['id']: normalizer.normalize(inputs['texts'][arm][r['id']]) for r in inputs['rows']}
        outside += sum(outside_span_changes(inputs['texts'][arm][identity], value)
                       for identity, value in derivatives[arm].items())
        variants[arm + '_raw'] = inputs['texts'][arm]
        variants[arm + '_normalized'] = {identity: d['normalized_search_text'] for identity, d in derivatives[arm].items()}
    for arm, texts in variants.items():
        metrics[arm] = score_texts(inputs['rows'], texts, annotations, vocabulary['terms'])
    ranks = {arm: {} for arm in variants}
    results = []
    applicable = [r for r in rubric['records'] if r['task_applicable']]
    with FrozenRetrieval(root, output / 'corpus.db', as_of=protocol['as_of']) as retrieval:
        validate_rubric(rubric, inputs['rows'], retrieval.corpus_rows())
        backend = retrieval.warm()
        for index, row in enumerate(rubric['records']):
            # Alternate paired order; every arm uses this exact frozen backend.
            order = list(variants) if index % 2 == 0 else list(reversed(variants))
            for arm in order:
                text = variants[arm][row['id']]
                candidates = retrieval.search(text, limit=3)['candidates'] if text.strip() else []
                rank = support_rank(row['support'], candidates) if row['task_applicable'] else None
                ranks[arm][row['id']] = rank
                results.append(dict(id=row['id'], arm=arm, applicable=row['task_applicable'],
                                    rank=rank, candidates=candidates))
    retrieval_counts = {arm: dict(top3=sum(ranks[arm][r['id']] is not None for r in applicable),
                                  total=len(applicable)) for arm in variants}
    ranked_ids = {(r['arm'], r['id']): [c['source_id'] for c in r['candidates']] for r in results}
    search_changes = {arm: dict(clips=len(inputs['rows']),
        text_changed=sum(d['changed'] for d in derivatives[arm].values()),
        top3_order_changed=sum(ranked_ids[(arm+'_raw', r['id'])] !=
                               ranked_ids[(arm+'_normalized', r['id'])] for r in inputs['rows']),
        top3_members_changed=sum(set(ranked_ids[(arm+'_raw', r['id'])]) !=
                                 set(ranked_ids[(arm+'_normalized', r['id'])]) for r in inputs['rows'])) for arm in ARMS}
    raw, normalized = metrics['vocabulary_raw'], metrics['vocabulary_normalized']
    gained = sum(ranks['vocabulary_raw'][r['id']] is None and ranks['vocabulary_normalized'][r['id']] is not None for r in applicable)
    lost = sum(ranks['vocabulary_raw'][r['id']] is not None and ranks['vocabulary_normalized'][r['id']] is None for r in applicable)
    gate = dict(top3_gained=gained, top3_lost=lost, outside_span_changes=outside,
                critical_new_errors=regressions(raw, normalized, 'critical_values'),
                name_new_errors=regressions(raw, normalized, 'name_values'),
                term_new_errors=regressions(raw, normalized, 'school_term_values'))
    recommendation = 'ON' if gained >= 1 and all(v == 0 for k, v in gate.items() if k != 'top3_gained') else 'OFF'
    require_inputs_unchanged(root, protocol)
    if any(value for key, value in guard_counts.items() if key != 'blocked_subprocess_attempts'):
        raise ValueError('guard_detected_prohibited_attempt')
    public_metrics = {arm: {k: v for k, v in value.items() if k not in {'rows', 'school_term_errors'}} for arm, value in metrics.items()}
    summary = dict(model=MODEL, paired_clips=len(inputs['rows']), speakers=1,
        reference_words=raw['reference_words'], reference_characters=raw['reference_characters'],
        primary_arm='vocabulary', metrics=public_metrics, retrieval=retrieval_counts,
        search_changes=search_changes,
        reference_classes=dict(Counter(r['answerability'] for r in rubric['records'])),
        reference_origin=protocol['reference_origin'], human_reviewed=False,
        source_hit_evaluation_complete=bool(applicable),
        reference_limitation='no_source_hit_rate_when_no_frozen_applicable_source_reference',
        recommendation=recommendation, gate=gate, config_flags_changed=False,
        guard=guard_counts, protocol_sha256=sha(output / 'protocol.json'), backend=backend,
        scope='observed_development_one_speaker_not_general_accuracy')
    write_new(output / 'derivatives-private.json', derivatives)
    write_new(output / 'metrics-private.json', metrics)
    write_new(output / 'retrieval-private.json', results)
    write_new(output / 'summary.json', summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'run'))
    parser.add_argument('--output', default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        output = output_path(ROOT, args.output)
        counters = install_guard(output)
        result = prepare(ROOT, output) if args.command == 'prepare' else run(ROOT, output, counters)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except Exception as error:
        # Exceptions from libraries can contain query/reference text. Never echo.
        print(json.dumps(dict(error='offline_evaluation_failed', error_type=type(error).__name__)))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
