"""Recount representation-only changes; never emit sentences or references."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from score import normalize
from stt_text_normalization import spoken_integer
from tools.evaluate_stt_normalization import (DEFAULT_OUTPUT, install_guard, output_path,
                                            read, sha, write_new, regressions)
from tools.stt_normalization_metrics import annotate_reference, score_texts


def post_analysis(metrics, derivatives):
    results = {}
    for arm in ('baseline', 'vocabulary'):
        before, after = metrics[arm + '_raw'], metrics[arm + '_normalized']
        lost = Counter()
        for a, b in zip(before['rows'], after['rows']):
            if a['id'] != b['id']:
                raise ValueError('paired_order_changed')
            for x, y in zip(a['critical_values']['records'], b['critical_values']['records']):
                if x['found'] is True and y['found'] is False:
                    lost[x['field']] += 1
        replacements = [s for r in derivatives[arm].values() for s in r['replacements']]
        numeric = [s for s in replacements if s['replacement'].isdigit()]
        years = {}
        for phase, value in (('raw', before), ('normalized', after)):
            slots = [s for r in value['rows'] for s in r['critical_values']['records']
                     if s['year_semantic'] and not s['pending']]
            years[phase] = dict(found=sum(s['found'] for s in slots), total=len(slots))
        results[arm] = dict(numeric_replacements=len(numeric),
            numeric_values_preserved=sum(spoken_integer(normalize(s['original']).split()) ==
                                         int(s['replacement']) for s in numeric),
            lost_literal_slot_fields=dict(lost), year_values=years,
            school_term_errors=after['school_term_errors'])
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        output = output_path(ROOT, args.output)
        install_guard(output)
        protocol = read(output / 'protocol.json')
        for name, digest in protocol['private_sha256'].items():
            if sha(output / name) != digest:
                raise ValueError('frozen_input_changed')
        for name in ('score.py','stt_text_normalization.py','config/stt-vocabulary.json',
                     'config/stt-text-normalization.json'):
            if sha(ROOT / name) != protocol['input_and_code_sha256'][name]:
                raise ValueError('scorer_normalizer_or_flags_changed')
        original = read(output / 'metrics-private.json')
        inputs, vocabulary = read(output / 'inputs-private.json'), read(output / 'vocabulary-private.json')
        derivatives = read(output / 'derivatives-private.json')
        annotations = {r['id']:annotate_reference(r['reference'],r.get('critical_slots',[]),vocabulary['terms']) for r in inputs['rows']}
        corrected = {}
        for arm in ('baseline','vocabulary'):
            for phase in ('raw','normalized'):
                texts = (inputs['texts'][arm] if phase == 'raw' else
                         {i:d['normalized_search_text'] for i,d in derivatives[arm].items()})
                key = arm+'_'+phase
                corrected[key] = score_texts(inputs['rows'],texts,annotations,vocabulary['terms'])
                for field in ('word_edit_errors','character_edit_errors','reference_words','reference_characters','edit_counts','critical_values'):
                    if corrected[key][field] != original[key][field]:
                        raise ValueError('recount_changed_primary_metrics')
        summary = read(output / 'summary.json')
        summary['metrics'] = {k:{f:v for f,v in m.items() if f not in {'rows','school_term_errors'}} for k,m in corrected.items()}
        for field in ('name_values','school_term_values'):
            new_errors=regressions(corrected['vocabulary_raw'],corrected['vocabulary_normalized'],field)
            if new_errors != summary['gate']['name_new_errors' if field=='name_values' else 'term_new_errors']:
                raise ValueError('recount_changed_gate')
        summary['taxonomy_recount'] = dict(reason='exclude_person_name_fragments_from_school_terms_and_use_reference_inflections',
            original_summary_sha256=sha(output/'summary.json'), helper_sha256=sha(ROOT/'tools/stt_normalization_metrics.py'),
            original_ranks_reused=True, new_retrieval_calls=0)
        write_new(output / 'annotations-recount-private.json',annotations)
        write_new(output / 'metrics-recount-private.json',corrected)
        write_new(output / 'summary-recount.json',summary)
        result = dict(protocol_sha256=sha(output / 'protocol.json'),
                      metrics_sha256=sha(output / 'metrics-recount-private.json'),
                      derivatives_sha256=sha(output / 'derivatives-private.json'),
                      analysis=post_analysis(corrected,
                                             read(output / 'derivatives-private.json')))
        write_new(output / 'postanalysis.json', result)
        print(json.dumps({arm: {k: v for k, v in value.items() if k != 'school_term_errors'}
                          for arm, value in result['analysis'].items()}, ensure_ascii=False))
        return 0
    except Exception as error:
        print(json.dumps(dict(error='offline_analysis_failed', error_type=type(error).__name__)))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
