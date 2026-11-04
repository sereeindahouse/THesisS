"""Reference-only, conservative AI source rubric; all text stays private."""
import re
from score import normalize
from website_retrieval import search_terms
from tools.compare_stt_vocabulary import spoken_year

QUESTION = re.compile(r'\b(?:вэ|бэ|уу|үү|юу|ямар|хэн|хэрхэн|яаж|хэзээ|хаана\w*|хэд\w*)\b')
GENERIC = set('сайн байна шинэ монгол коосэн сургууль сургуулийн хэд хэдэн хэддүгээр хэзээ хаана байдаг байгаа ажилладаг ажиллаж талаар мэдээлэл мэдэх боломжтой хэлж өгөөч нийт оны онд он мянга мянган хоёр хорин зургаан'.split())
FIELDS = (
    ('phone', r'утас|холбогд', r'утас|phone|tel'),
    ('floor', r'давхар|хаана', r'давхар|байрш|хаяг'),
    ('money', r'төлбөр|төгрөг|хураамж', r'төлбөр|төгрөг|хураамж|₮'),
    ('deadline', r'хэзээ|хугацаа|хэдний', r'хугацаа|бүртгэл|элсэлт|он'),
    ('teacher', r'багш', r'багш'),
    ('credit', r'кредит|цаг', r'кредит|цаг'),
    ('program', r'мэргэжил|хөтөлбөр|ямар', r'мэргэжил|хөтөлбөр|сургалт'),
)


def draft_rubric(rows, corpus_rows, typed_search=None, terms=()):
    """Use references/captured sources only, never output rankings or hypotheses.

    This is an AI rule-assisted development reference, NOT human gold. Each
    supporting unit must pass subject anchors, explicit requested-field evidence
    and any declared year scope. Unresolved cases stay out of the hit denominator.
    """
    records = []
    for row in rows:
        text = normalize(row['reference'])
        slots = row.get('critical_slots', [])
        field = next((name for name, query, _ in FIELDS if re.search(query, text)), None)
        school_names = [s['expected'] for s in slots if s['field'] == 'school_name']
        if field is None and school_names and re.search(r'нэр|мөн|гэдэг|юу|аль|тухай|талаар', text):
            field = 'school_identity'
        result = dict(id=row['id'], task_applicable=False, answerability='non_question',
                      field_kind=field, support=[], annotation_notes=[])
        if not QUESTION.search(text):
            result['annotation_notes'] = ['reference_has_no_question_marker']
            records.append(result)
            continue
        if any('uncertain' in slot['field'] for slot in slots):
            result.update(answerability='ambiguous', annotation_notes=['reference_contains_uncertain_slot'])
            records.append(result)
            continue
        anchors = {token for token in search_terms(text)
                   if token not in GENERIC and not token.isdigit() and len(token) >= 3}
        if field == 'school_identity':
            anchors = set(search_terms(' '.join(school_names)))
        years = {spoken_year(slot['expected']) if not re.fullmatch(r'20\d{2}', slot['expected'])
                 else int(slot['expected']) for slot in slots if slot['field'] == 'year'} - {None}
        names = [set(search_terms(slot['expected'])) for slot in slots
                 if slot['field'] in {'company', 'department', 'subject'}]
        proof = []
        for source in corpus_rows:
            body = normalize(source['text'])
            tokens = set(search_terms(body))
            matched = anchors & tokens
            coverage = len(matched) / max(1, len(anchors))
            if not field or len(matched) < min(2, len(anchors)) or coverage < .60:
                continue
            pattern = (r'коосэн|сургууль' if field == 'school_identity' else
                       next(pattern for name, _, pattern in FIELDS if name == field))
            if not re.search(pattern, body):
                continue
            if field == 'school_identity' and not all(' ' + normalize(name) + ' ' in ' ' + body + ' ' for name in school_names):
                continue
            if field in {'phone', 'money', 'teacher', 'credit'} and not re.search(r'\d', body):
                continue
            if years and not years.issubset({int(v) for v in re.findall(r'\b20\d{2}\b', body)}):
                continue
            if any(not expected.intersection(tokens) for expected in names):
                continue
            proof.append((coverage, len(matched), source))
        if proof:
            best = max(value[0] for value in proof)
            accepted = [source for coverage, _, source in proof if coverage >= max(.60, best - .05)]
            result.update(task_applicable=True, answerability='answerable',
                support=[dict(source_id=s['source_id'], url=s['url'], version=s['version'], phrase=s['text'])
                         for s in accepted],
                annotation_notes=['subject_and_requested_field_verified_in_frozen_source',
                                  'explicit_year_scope_checked', 'assistant_rule_assisted_review'],
                anchor_count=len(anchors), minimum_anchor_coverage=max(.60, best - .05))
        else:
            # Failure of these conservative rules is not proof that a source
            # does not exist. Keep such questions unresolved, never false gold.
            result.update(answerability='ambiguous',
                          annotation_notes=['no_source_met_fixed_subject_field_year_checks'],
                          anchor_count=len(anchors))
        records.append(result)
    return dict(schema_version=1, reference_origin='assistant_rule_assisted_source_review',
                human_reviewed=False, derived_before_output_rankings=True, records=records)


def validate_rubric(rubric, rows, corpus_rows):
    records = rubric.get('records', [])
    if [r['id'] for r in records] != [r['id'] for r in rows]:
        raise ValueError('rubric_ids_differ')
    sources = {s['source_id']: s for s in corpus_rows}
    for record in records:
        if record.get('answerability') not in {'answerable', 'unsupported', 'non_question', 'ambiguous'}:
            raise ValueError('invalid_reference_class')
        if record.get('task_applicable') is not (record['answerability'] == 'answerable'):
            raise ValueError('invalid_reference_applicability')
        if record['task_applicable'] and not record.get('support'):
            raise ValueError('missing_source_proof')
        for support in record.get('support', []):
            source = sources.get(support.get('source_id'))
            if (source is None or support.get('url') != source['url'] or
                    support.get('version') != source['version'] or not support.get('phrase') or
                    support['phrase'] not in source['text']):
                raise ValueError('reference_source_proof_changed')
    return True
