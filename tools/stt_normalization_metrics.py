"""Pure offline STT scoring. Returned text-bearing objects are PRIVATE evidence.

No function opens a path, audio, database, credential or socket, or prints text.
The caller freezes reference annotations before comparing output rankings.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
import re

from score import normalize, score
from stt_text_normalization import spoken_integer
from tools.compare_stt_vocabulary import spoken_year
from website_retrieval import search_terms

MODEL = 'gemini-3.5-transcribe'
ARMS = ('baseline', 'vocabulary')
CATEGORIES = ('number_year', 'name', 'school_term', 'other')
NAME_FIELDS = {'school_name', 'company', 'person', 'person_name', 'teacher',
               'teacher_name', 'staff_name', 'name'}
NUMBER_FIELDS = {'year', 'year_literal', 'phone', 'phone_literal', 'floor',
                 'course', 'money', 'money_literal', 'deadline', 'number'}


def _tokens(text):
    if not isinstance(text, str):
        raise ValueError('Text must be a string.')
    return normalize(text).split()


def _positions(tokens, phrase):
    size = len(phrase)
    if not size:
        return []
    return [i for i in range(len(tokens) - size + 1) if tokens[i:i + size] == phrase]


def paired_inputs(manifest, saved_results, expected_count=12):
    """Return copied paired ``rows``, arm->ID->``texts`` and count-only cohort.

    A failed attempt remains an excluded error record. A genuinely successful
    empty output is retained and scores as deletions, never manufactured.
    """
    if not isinstance(manifest, dict) or not isinstance(manifest.get('human_rows'), list):
        raise ValueError('Manifest requires human rows.')
    humans = manifest['human_rows']
    if not humans or not isinstance(saved_results, list):
        raise ValueError('Require human rows and saved result records.')
    ids, by_id = [], {}
    for row in humans:
        if (not isinstance(row, dict) or not isinstance(row.get('id'), str)
                or not row['id'].strip() or row['id'].casefold() in {i.casefold() for i in ids}
                or row.get('reference_status') != 'eligible_speaker_confirmed'
                or not isinstance(row.get('reference'), str) or not _tokens(row['reference'])):
            raise ValueError('Require unique IDs and confirmed nonempty references.')
        ids.append(row['id'])
        by_id[row['id']] = row
    texts = {arm: {} for arm in ARMS}
    failed = incomplete = 0
    for record in saved_results:
        if (not isinstance(record, dict) or record.get('id') not in by_id
                or record.get('arm') not in ARMS):
            raise ValueError('Saved records must identify a declared human and arm.')
        if record.get('error'):
            failed += 1
            continue
        if not isinstance(record.get('text'), str):
            incomplete += 1
            continue
        if record.get('model') != MODEL:
            raise ValueError('Successful saved output has a different model.')
        arm, identity = record['arm'], record['id']
        if identity in texts[arm]:
            raise ValueError('Duplicate successful arm and ID.')
        texts[arm][identity] = record['text']
    paired = [identity for identity in ids if all(identity in texts[arm] for arm in ARMS)]
    if expected_count is not None and (type(expected_count) is not int or len(paired) != expected_count):
        raise ValueError('Paired cohort size differs from the declared protocol.')
    if not paired:
        raise ValueError('No successful paired inputs.')
    cohort = dict(human_clips=len(humans), paired_clips=len(paired), ids=paired,
        successful_by_arm={arm: len(texts[arm]) for arm in ARMS},
        saved_records=len(saved_results), failed_records=failed, incomplete_records=incomplete,
        excluded=[dict(id=identity, missing_arms=[arm for arm in ARMS if identity not in texts[arm]])
                  for identity in ids if identity not in paired])
    return dict(rows=[deepcopy(by_id[identity]) for identity in paired],
        texts={arm: {identity: texts[arm][identity] for identity in paired} for arm in ARMS}, cohort=cohort)


def word_alignment(reference, hypothesis):
    """Levenshtein token events with stable diagonal, deletion, insertion ties.

    Events include ``=`` matches and zero-based source/destination indices.
    Reference/hypothesis strings in events must never go to public stdout.
    """
    ref, hyp = _tokens(reference), _tokens(hypothesis)
    table = [list(range(len(hyp) + 1))]
    for i, token in enumerate(ref, 1):
        row = [i]
        for j, predicted in enumerate(hyp, 1):
            row.append(min(table[-1][j - 1] + (token != predicted), table[-1][j] + 1, row[-1] + 1))
        table.append(row)
    events, i, j = [], len(ref), len(hyp)
    while i or j:
        if i and j and table[i][j] == table[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]):
            i, j = i - 1, j - 1
            event = dict(op='=' if ref[i] == hyp[j] else 'S', reference_index=i,
                hypothesis_index=j, reference=ref[i], hypothesis=hyp[j])
        elif i and table[i][j] == table[i - 1][j] + 1:
            i -= 1
            event = dict(op='D', reference_index=i, hypothesis_index=None, reference=ref[i], hypothesis=None)
        else:
            j -= 1
            event = dict(op='I', reference_index=None, hypothesis_index=j, reference=None, hypothesis=hyp[j])
        events.append(event)
    return events[::-1]


def _number_word(word):
    return word.isdecimal() or spoken_integer([word]) is not None


def _pending(field):
    return 'uncertain' in field.casefold() or 'pending' in field.casefold()


def _valid_slots(slots):
    if not isinstance(slots, list) or any(not isinstance(slot, dict)
            or not isinstance(slot.get('field'), str) or not slot['field'].strip()
            or not isinstance(slot.get('expected'), str) or not _tokens(slot['expected']) for slot in slots):
        raise ValueError('Critical slots require nonempty field and expected span.')
    return slots


def annotate_reference(reference, critical_slots, terms):
    """Freeze per-reference labels before scoring output.

    ``labels`` parallels scorer tokens, each with category and optional canonical
    term. ``spans`` records proper-name and school-term occurrences. Number/year
    labels have priority over names, which have priority over school terms.
    """
    tokens = _tokens(reference)
    labels = [dict(category='number_year' if _number_word(token) else 'other', term=None) for token in tokens]
    spans = []
    for slot in _valid_slots(critical_slots):
        field, phrase = slot['field'], _tokens(slot['expected'])
        if _pending(field):
            continue
        category = ('number_year' if field in NUMBER_FIELDS or 'year' in field else
                    'name' if field in NAME_FIELDS or field.endswith('_name') else None)
        if category is None:
            continue
        for start in _positions(tokens, phrase):
            for index in range(start, start + len(phrase)):
                if category == 'number_year' or labels[index]['category'] != 'number_year':
                    labels[index] = dict(category=category, term=None)
            if category == 'name':
                spans.append(dict(start=start, end=start + len(phrase), category=category, canonical=slot['expected']))
    # Initial+given-name entries in the public vocabulary are person names,
    # even where the old manifest did not declare a separate name slot.
    for term in terms:
        if not re.fullmatch(r'[A-ZА-ЯЁӨҮ]\.\s*[A-ZА-ЯЁӨҮ][a-zа-яёөү]+', term):
            continue
        phrase = _tokens(term)
        for start in _positions(tokens, phrase):
            end = start + len(phrase)
            if all(labels[i]['category'] == 'other' for i in range(start, end)):
                for i in range(start, end):
                    labels[i] = dict(category='name', term=None)
                spans.append(dict(start=start, end=end, category='name', canonical=term))
    canonical_terms = sorted(set(terms), key=lambda value: (-len(_tokens(value)), value.casefold()))
    # Reference-only inflection labels; output text is never used to choose
    # a canonical term. One scorer token stays one token in this annotation.
    stems = [tuple(search_terms(token)) for token in tokens]
    for term in canonical_terms:
        phrase = _tokens(term)
        term_stems = [tuple(search_terms(token)) for token in phrase]
        positions = set(_positions(tokens, phrase))
        if all(len(stem) == 1 for stem in term_stems):
            positions.update(i for i in range(len(tokens) - len(phrase) + 1)
                             if stems[i:i + len(phrase)] == term_stems)
        for start in sorted(positions):
            end = start + len(phrase)
            if all(labels[index]['category'] == 'other' for index in range(start, end)):
                category = ('name' if re.fullmatch(r'[A-ZА-ЯЁӨҮ]\.\s*[A-ZА-ЯЁӨҮ][a-zа-яёөү]+', term)
                            else 'school_term')
                for index in range(start, end):
                    labels[index] = dict(category=category, term=term if category == 'school_term' else None)
                spans.append(dict(start=start, end=end, category=category,
                                  canonical=' '.join(tokens[start:end]), canonical_term=term))
    return dict(tokens=tokens, labels=labels, spans=spans,
        names=sorted(set(span['canonical'] for span in spans if span['category'] == 'name')),
        terms=sorted(set(span['canonical'] for span in spans if span['category'] == 'school_term')))


def _year_values(tokens):
    years = {int(token) for token in tokens if re.fullmatch(r'20\d{2}', token)}
    start = 0
    while start < len(tokens):
        if tokens[start].isdecimal() or not _number_word(tokens[start]):
            start += 1
            continue
        end = start + 1
        while end < len(tokens) and not tokens[end].isdecimal() and _number_word(tokens[end]):
            end += 1
        value = spoken_year(' '.join(tokens[start:end]))
        if value is not None:
            years.add(value)
        start = end
    return years


def critical_values(slots, text):
    """Exact token-span hits, with spoken/digit year meaning matched separately.

    Uncertain/pending slots have ``found=None`` and are excluded from denominator.
    ``records`` contains indices/field labels, never reference text.
    """
    tokens, records = _tokens(text), []
    years = _year_values(tokens)
    for index, slot in enumerate(_valid_slots(slots)):
        expected = _tokens(slot['expected'])
        literal = bool(_positions(tokens, expected))
        year = spoken_year(slot['expected'])
        if year is None and len(expected) == 1 and re.fullmatch(r'20\d{2}', expected[0]):
            year = int(expected[0])
        pending = _pending(slot['field'])
        found = None if pending else literal or (year is not None and year in years)
        records.append(dict(index=index, field=slot['field'], found=found,
            literal_found=literal, pending=pending, year_semantic=year is not None))
    eligible = [row for row in records if not row['pending']]
    return dict(found=sum(row['found'] for row in eligible), total=len(eligible),
        pending=len(records) - len(eligible), literal_found=sum(row['literal_found'] for row in eligible), records=records)


def _span_hits(annotation, hypothesis, category):
    tokens = _tokens(hypothesis)
    spans = [span for span in annotation['spans'] if span['category'] == category]
    records = [dict(index=index, found=bool(_positions(tokens, _tokens(span['canonical']))))
               for index, span in enumerate(spans)]
    return dict(found=sum(row['found'] for row in records), total=len(records), records=records)


def score_texts(rows, texts, annotations, terms):
    """Score one arm. Only caller-filtered aggregate fields may be published.

    ``annotations`` is ID -> annotate_reference result, frozen before outputs.
    Private ``rows`` include alignment, span/slot hit booleans and token strings.
    """
    identities = [row['id'] for row in rows]
    if set(identities) != set(texts) or set(identities) != set(annotations):
        raise ValueError('Text and annotation IDs must equal the paired cohort.')
    pairs = [dict(id=row['id'], reference=row['reference'], hypothesis=texts[row['id']]) for row in rows]
    result = score(pairs)
    result.pop('rows')
    categories = Counter({category: 0 for category in CATEGORIES})
    counts = Counter(S=0, D=0, I=0)
    term_events, term_clips = Counter(), defaultdict(set)
    private_rows = []
    name_tokens = set(token for annotation in annotations.values() for name in annotation['names'] for token in _tokens(name))
    term_lookup = defaultdict(set)
    for term in terms:
        if re.fullmatch(r'[A-ZА-ЯЁӨҮ]\.\s*[A-ZА-ЯЁӨҮ][a-zа-яёөү]+', term):
            continue
        for token in _tokens(term):
            if len(token) >= 3:
                term_lookup[token].add(term)
    for row in rows:
        identity, reference = row['id'], row['reference']
        annotation, hypothesis = annotations[identity], texts[identity]
        if annotation.get('tokens') != _tokens(reference) or len(annotation.get('labels', [])) != len(_tokens(reference)):
            raise ValueError('Frozen annotation no longer matches its reference.')
        events = word_alignment(reference, hypothesis)
        local_counts = Counter(S=0, D=0, I=0)
        local_categories = Counter({category: 0 for category in CATEGORIES})
        for event in events:
            if event['op'] == '=':
                continue
            term = None
            if event['reference_index'] is not None:
                label = annotation['labels'][event['reference_index']]
                category, term = label['category'], label['term']
            else:
                token = event['hypothesis']
                category = ('number_year' if _number_word(token) else 'name' if token in name_tokens else
                            'school_term' if token in term_lookup else 'other')
                if category == 'school_term' and len(term_lookup[token]) == 1:
                    term = next(iter(term_lookup[token]))
            event['category'] = category
            if term is not None:
                event['canonical_term'] = term
                term_events[term] += 1
                term_clips[term].add(identity)
            local_counts[event['op']] += 1
            local_categories[category] += 1
        counts.update(local_counts)
        categories.update(local_categories)
        private_rows.append(dict(id=identity, word_edit_errors=sum(local_counts.values()),
            edit_counts=dict(local_counts), error_categories=dict(local_categories), alignment=events,
            critical_values=critical_values(row.get('critical_slots', []), hypothesis),
            name_values=_span_hits(annotation, hypothesis, 'name'),
            school_term_values=_span_hits(annotation, hypothesis, 'school_term')))
    if sum(counts.values()) != result['word_edit_errors'] or sum(categories.values()) != result['word_edit_errors']:
        raise ValueError('Alignment and error-category totals disagree with scorer.')
    result.update(edit_counts=dict(counts), error_categories=dict(categories), rows=private_rows,
        school_term_errors=[dict(term=term, clips=len(term_clips[term]), error_events=term_events[term])
                            for term in sorted(term_events, key=lambda term: (-len(term_clips[term]), -term_events[term], term))])
    for key in ('critical_values', 'name_values', 'school_term_values'):
        result[key] = {count: sum(row[key].get(count, 0) for row in private_rows)
                       for count in (('found', 'total', 'pending', 'literal_found') if key == 'critical_values' else ('found', 'total'))}
    return result
