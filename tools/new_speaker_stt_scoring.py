"""Pure offline scoring for the new-speaker kit; never prints or opens files.

``summarize(rows, results, terms)`` returns ``summary`` (safe count-only metrics
and pseudonymous speaker codes) and ``private_rows`` (reference annotations and
text-bearing alignments, to be stored ONLY beneath runtime/ by the caller).
The paired cohort is selected once, then reused globally and per speaker.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import re

from score import normalize
from stt_text_normalization import spoken_integer
from tools.compare_stt_vocabulary import spoken_year
from tools.evaluate_gemini_stt_offline import value_wer
from tools.stt_normalization_metrics import annotate_reference, score_texts

MODEL = 'gemini-3.5-transcribe'
ARMS = ('vocabulary_v2', 'vocabulary_v2_clean')
_CODE = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}')
_SAFE_METRICS = (
    'normalization', 'utterances', 'reference_words', 'reference_characters',
    'word_edit_errors', 'character_edit_errors', 'corpus_wer', 'corpus_cer',
    'normalized_sentence_exact_match', 'edit_counts', 'error_categories',
    'critical_values', 'name_values', 'school_term_values',
)


def _code(value):
    return isinstance(value, str) and _CODE.fullmatch(value) is not None


def reference_year_slots(reference):
    """Unique automatic 2000--2099 candidates, not human critical judgments.

    Reuse spoken_year's exact plain-year grammar. Invalid trailing number words
    cannot turn a valid year prefix into a confirmed slot. Distinct requested
    values are counted once even when repeated as words and digits.
    """
    tokens = normalize(reference).split()
    found, seen = [], set()
    for start, token in enumerate(tokens):
        expected = None
        if re.fullmatch(r'20\d{2}', token):
            expected, value = token, int(token)
        elif token == 'хоёр' and tokens[start + 1:start + 2] in (['мянга'], ['мянган']):
            for end in range(min(start + 4, len(tokens)), start + 1, -1):
                phrase = ' '.join(tokens[start:end])
                value = spoken_year(phrase)
                if value is None:
                    continue
                # A following complete year may be a range after punctuation.
                next_year = tokens[end:end + 2] in (['хоёр', 'мянга'], ['хоёр', 'мянган'])
                tail_number = (end < len(tokens) and
                               spoken_integer([tokens[end]]) is not None)
                if tail_number and not next_year:
                    continue
                expected = phrase
                break
        if expected is not None and value not in seen:
            seen.add(value)
            found.append(dict(field='year_automatic', expected=expected))
    return found


def _rows(rows):
    if not isinstance(rows, list) or not rows:
        raise ValueError('scoring_requires_manifest_rows')
    seen, adapted, origins = set(), [], Counter()
    for row in rows:
        if (not isinstance(row, dict) or not all(_code(row.get(k)) for k in
                ('clip_id', 'speaker_code', 'question_id')) or
                row['clip_id'].casefold() in seen or
                not isinstance(row.get('reference_text'), str) or
                not normalize(row['reference_text'])):
            raise ValueError('invalid_scoring_row')
        seen.add(row['clip_id'].casefold())
        if 'critical_slots' in row:
            slots, origin = deepcopy(row['critical_slots']), 'manifest_explicit_not_independently_reviewed'
            if not isinstance(slots, list) or len(slots) > 50:
                raise ValueError('invalid_manifest_critical_slots')
            ref = ' ' + normalize(row['reference_text']) + ' '
            for slot in slots:
                if (not isinstance(slot, dict) or not isinstance(slot.get('field'), str) or
                        not slot['field'].strip() or not isinstance(slot.get('expected'), str) or
                        not normalize(slot['expected']) or
                        ' ' + normalize(slot['expected']) + ' ' not in ref):
                    raise ValueError('critical_span_not_in_reference')
        else:
            slots, origin = reference_year_slots(row['reference_text']), 'reference_derived_year_candidates'
        origins[origin] += 1
        adapted.append(dict(id=row['clip_id'], speaker_code=row['speaker_code'],
            question_id=row['question_id'], reference=row['reference_text'],
            critical_slots=slots, critical_slot_origin=origin))
    return adapted, dict(origins)


def _results(rows, results):
    if not isinstance(results, list):
        raise ValueError('scoring_requires_result_records')
    declared = {row['id']: row for row in rows}
    texts = {arm: {} for arm in ARMS}
    counters = {speaker: Counter() for speaker in {r['speaker_code'] for r in rows}}
    for record in results:
        if not isinstance(record, dict) or record.get('clip_id') not in declared or record.get('arm') not in ARMS:
            raise ValueError('undeclared_result_case')
        row = declared[record['clip_id']]
        if record.get('speaker_code') != row['speaker_code']:
            raise ValueError('result_speaker_mismatch')
        counts = counters[row['speaker_code']]
        counts['records'] += 1
        if record.get('error') or record.get('status') in {'error', 'failed'}:
            counts['failed_records'] += 1
            continue
        if not isinstance(record.get('text'), str):
            counts['incomplete_records'] += 1
            continue
        if record.get('model') != MODEL:
            raise ValueError('result_model_mismatch')
        arm, identity = record['arm'], row['id']
        if identity in texts[arm]:
            raise ValueError('duplicate_successful_case')
        texts[arm][identity] = record['text']
        counts['successful_' + arm] += 1
    return texts, counters


def _drops(before, after, *, years_only=False):
    count = 0
    for left, right in zip(before['rows'], after['rows']):
        if left['id'] != right['id']:
            raise ValueError('paired_metric_order_changed')
        for a, b in zip(left['critical_values']['records'], right['critical_values']['records']):
            if not years_only or a['year_semantic']:
                count += a['found'] is True and b['found'] is False
    return count


def _year_counts(private_rows):
    slots = [s for row in private_rows for s in row['critical_values']['records'] if s['year_semantic']]
    return dict(found=sum(s['found'] is True for s in slots if not s['pending']),
                total=sum(not s['pending'] for s in slots), pending=sum(s['pending'] for s in slots))


def _group(rows, paired, texts, annotations, terms, counters):
    ids = {row['id'] for row in rows}
    selected = [row for row in paired if row['id'] in ids]
    coverage = dict(manifest_clips=len(rows), paired_clips=len(selected),
        unpaired_clips=len(rows) - len(selected),
        successful_by_arm={arm: sum(identity in texts[arm] for identity in ids) for arm in ARMS})
    # Speaker counters are merged by caller; do not multiply them per clip.
    speakers = {row['speaker_code'] for row in rows}
    for key in ('records', 'failed_records', 'incomplete_records'):
        coverage[key] = sum(counters[speaker][key] for speaker in speakers)
    if not selected:
        return dict(**coverage, arms={arm: None for arm in ARMS}, cleanup_effect=None), {}
    scored, private, safe = {}, {}, {}
    selected_annotations = {row['id']: annotations[row['id']] for row in selected}
    for arm in ARMS:
        chosen = {row['id']: texts[arm][row['id']] for row in selected}
        value = score_texts(selected, chosen, selected_annotations, terms)
        scored[arm], private[arm] = value, value['rows']
        safe[arm] = {key: deepcopy(value[key]) for key in _SAFE_METRICS}
        safe[arm]['value_wer'] = value_wer(selected, chosen)
        safe[arm]['year_values'] = _year_counts(value['rows'])
    raw, clean = ARMS
    a, b = safe[raw], safe[clean]
    effect = dict(
        strict_word_error_delta=b['word_edit_errors'] - a['word_edit_errors'],
        character_error_delta=b['character_edit_errors'] - a['character_edit_errors'],
        strict_wer_delta=b['corpus_wer'] - a['corpus_wer'],
        cer_delta=b['corpus_cer'] - a['corpus_cer'],
        value_wer_delta=b['value_wer']['corpus_wer'] - a['value_wer']['corpus_wer'],
        critical_span_new_misses=_drops(scored[raw], scored[clean]),
        year_value_new_misses=_drops(scored[raw], scored[clean], years_only=True),
    )
    effect['regressed'] = (effect['strict_word_error_delta'] > 0 or effect['character_error_delta'] > 0 or
        effect['value_wer_delta'] > 1e-12 or effect['critical_span_new_misses'] > 0)
    effect['interpretation'] = 'paired_descriptive_metric_regression_not_population_harm'
    return dict(**coverage, arms=safe, cleanup_effect=effect), private


def summarize(rows, results, terms):
    """Score the exact paired cohort overall and by manifest speaker code.

    Missing/error arms never become empty successful text. A genuine successful
    empty response remains eligible and is scored as deletions. No file, audio,
    provider, credential or logging operation occurs here.
    """
    adapted, origins = _rows(rows)
    if not isinstance(terms, (list, tuple)) or any(not isinstance(t, str) for t in terms):
        raise ValueError('invalid_scoring_terms')
    texts, counters = _results(adapted, results)
    paired = [row for row in adapted if all(row['id'] in texts[arm] for arm in ARMS)]
    annotations = {row['id']: annotate_reference(row['reference'], row['critical_slots'], terms) for row in adapted}
    overall, private = _group(adapted, paired, texts, annotations, terms, counters)
    speakers = sorted({row['speaker_code'] for row in adapted})
    per_speaker = {}
    for speaker in speakers:
        selected = [row for row in adapted if row['speaker_code'] == speaker]
        per_speaker[speaker], _ = _group(selected, paired, texts, annotations, terms, counters)
    evaluated = [group for group in per_speaker.values() if group['paired_clips']]
    macro = {arm: dict(
        strict_wer=sum(group['arms'][arm]['corpus_wer'] for group in evaluated) / len(evaluated),
        value_wer=sum(group['arms'][arm]['value_wer']['corpus_wer'] for group in evaluated) / len(evaluated),
    ) for arm in ARMS} if evaluated else {arm: None for arm in ARMS}
    regressed = [speaker for speaker, group in per_speaker.items()
                 if group['cleanup_effect'] is not None and group['cleanup_effect']['regressed']]
    summary = dict(model=MODEL, arms=list(ARMS), manifest_clips=len(adapted),
        speaker_count=len(speakers), paired_clips=len(paired), overall=overall,
        per_speaker=per_speaker, macro_speaker_metrics=macro,
        evaluated_speakers=len(evaluated), cleanup_regressed_speakers=regressed,
        cleanup_regression_detected=bool(regressed) if evaluated else None,
        critical_slot_origins=origins, human_critical_review_claimed=False,
        reference_review='provided_manifest_not_independently_audited',
        scope='paired_manifest_speaker_codes_descriptive_not_general_accuracy')
    return dict(summary=summary, private_rows=dict(arms=private, annotations=annotations,
        critical_reference=[dict(clip_id=row['id'], speaker_code=row['speaker_code'],
            question_id=row['question_id'], critical_slots=row['critical_slots'],
            critical_slot_origin=row['critical_slot_origin']) for row in adapted]))
