"""Bounded, verbatim evidence selection for the local RAG generator.

An LLM selects opaque unit IDs; it cannot author or shorten the returned claims.
Physical paragraphs, table rows and their headings remain together. This prevents
rewriting a quantity's role or a planned action's tense, but does not establish
semantic relevance, exhaustive coverage, source truth or current validity.
"""
from __future__ import annotations

import hashlib
import re


def _unit_id(source_id, start, end, text):
    raw = f'{source_id}\0{start}\0{end}\0{text}'.encode('utf-8')
    return 'ev-' + hashlib.sha256(raw).hexdigest()[:24]


def _lines(text):
    return [(m.start() + len(m.group()) - len(m.group().lstrip()),
             m.start() + len(m.group().rstrip()), m.group().strip())
            for m in re.finditer(r'[^\n]+', text) if m.group().strip()]


def _prose(line):
    # Lists of requirements often omit punctuation. Never split them into
    # standalone answers, even when an individual row happens to be long.
    if re.match(r'^\d{1,2}[.)]?\s+', line):
        return False
    return not line.endswith('?') and (len(line) > 100 or line.endswith(('.', '!', '。')))


def _spans(text):
    """Yield contiguous physical paragraphs with preceding heading/list text.

    Sentence punctuation is not a safe boundary: the same paragraph can contain
    both a per-person quantity and a total, or a condition and its exception.
    """
    pending = []
    for line in _lines(text):
        if pending and line[2].isupper():
            yield pending[0][0], pending[-1][1]
            pending = []
        pending.append(line)
        if _prose(line[2]):
            yield pending[0][0], pending[-1][1]
            pending = []
    if pending:
        yield pending[0][0], pending[-1][1]


def _numbered_rows(text):
    return [line for line in text.splitlines()
            if re.match(r'^\s*\d{1,2}(?:[.)]|-[^\W\d_]+)?\s+', line)]


def _orphan_list(text):
    first = text.splitlines()[0] if text else ''
    # A leading 03/04 or 3. is a possible chunk continuation. A bare amount
    # such as "5 удаа" is not enough to infer a missing list heading.
    return bool(re.match(r'^\s*(?:0[2-9]|[2-9][.)])\s+', first)
                and len(_numbered_rows(text)) >= 2)


def _overlap(left, right):
    a, b = [x.strip() for x in left.splitlines()], [x.strip() for x in right.splitlines()]
    for length in range(min(len(a), len(b)), 1, -1):
        if a[-length:] == b[:length] and sum(map(len, b[:length])) >= 32:
            return length
    return 0


def _continues_previous(text):
    return bool(re.match(r'\s*(?:үүнээс|энэ|тус|мөн|харин|гэхдээ|ийм|тийм)\b', text, re.I))


def _explicit_conditional(text):
    # Only transparent lexical lead-ins, not arbitrary discourse inference.
    return bool(re.match(r'\s*хэрэв\b', text, re.I)
                or (len(text) <= 250 and re.search(r'зөвхөн.+тохиолдолд', text, re.I)))


def _after_template_counters(text, start, end):
    """Trim only an adjacent zero programme/teacher counter pair in a prefix.

    These two empty template cards are not staffing evidence. The remaining
    unit is still one exact contiguous source span. Isolated zeros, fees and
    counters after a prose paragraph are retained without interpretation.
    """
    # A later standalone counter table may contain legitimate zero counts;
    # template removal is confined to the source's heading prefix.
    if any(_prose(line[2]) for line in _lines(text[:start])):
        return start
    lines = _lines(text[start:end])
    trim = 0
    for index, line in enumerate(lines):
        if _prose(line[2]):
            break
        if index + 1 >= len(lines):
            continue
        labels = {re.sub(r'\s+', ' ', item[2]).casefold() for item in lines[index:index + 2]}
        if labels == {'0 хөтөлбөр', '0 багш'}:
            trim = lines[index + 1][1]
    if trim:
        remainder = text[start + trim:end]
        start += trim + len(remainder) - len(remainder.lstrip())
    return start


def evidence_units(sources, max_characters=900):
    """Return stable selectable exact spans; no amount, URL or case rules.

    Oversized paragraphs are omitted rather than truncated. An orphan numbered
    list is exposed only when a same-URL overlapping unit supplies its heading;
    resolving that selection automatically includes the heading-bearing unit.
    Only the supplied retrieved sources are used, without I/O or corpus changes.
    """
    units, seen = [], set()
    for source in sources:
        sid, text = source.get('source_id'), source.get('text')
        if not isinstance(sid, str) or not isinstance(text, str) or sid in seen:
            continue
        seen.add(sid)
        for start, end in _spans(text):
            start = _after_template_counters(text, start, end)
            span = text[start:end]
            if not 12 <= len(span) <= max_characters:
                continue
            units.append(dict(unit_id=_unit_id(sid, start, end, span), source_id=sid,
                              text=span, start=start, end=end, quote=text,
                              url=source.get('url'), context_unit_ids=[]))
    # Obvious paragraph continuations retain their immediately preceding
    # source context. Dependencies are resolved server-side, never retyped.
    previous_by_source = {}
    for unit in units:
        previous = previous_by_source.get(unit['source_id'])
        if previous and (_continues_previous(unit['text']) or _explicit_conditional(previous['text'])):
            unit['context_unit_ids'] = [previous['unit_id']]
        previous_by_source[unit['source_id']] = unit
    kept = []
    for unit in units:
        if _orphan_list(unit['text']):
            choices = [(other, _overlap(other['text'], unit['text'])) for other in units
                       if other['source_id'] != unit['source_id'] and unit['url']
                       and other['url'] == unit['url'] and not _orphan_list(other['text'])
                       and re.search(r'(?m)^\s*0?1[.)]?\s+', other['text'])]
            choices = [(other, length) for other, length in choices if length]
            if not choices:
                continue
            context, _ = max(choices, key=lambda pair: pair[1])
            unit['context_unit_ids'].append(context['unit_id'])
        kept.append(unit)
    return kept


_ROLE_PATTERNS = {
    'total': r'нийт',
    'per_group': r'тус\s+бүр|бүрээс|бүрийн',
    'primary': r'үндсэн',
    'part_time': r'цагийн',
    'doctorate': r'доктор',
    'masters': r'магистр',
}
_ROMAN = {'I': '1', 'II': '2', 'III': '3', 'IV': '4', 'V': '5', 'VI': '6',
          'VII': '7', 'VIII': '8', 'IX': '9', 'X': '10', 'XI': '11', 'XII': '12'}


def _anchors(text):
    """Explicit numeric/code anchors only; this is not a Mongolian parser."""
    anchors = set(re.findall(r'\d+(?:[.,]\d+)*', text))
    for token in re.findall(r'(?<![A-Za-z])[A-Za-z][A-Za-z0-9]*(?![A-Za-z])', text):
        anchors.add(_ROMAN.get(token, token.casefold()))
    return anchors


def missing_query_markers(query, selected_text, available_text):
    """Check bounded explicit omissions, without claiming semantic coverage.

    A marker is mandatory only if it occurs in both the question and supplied
    units. Thus a spelling alias does not by itself reject all model selections;
    retrieval, entity/attribute ambiguity and unsupported-field guards remain
    the caller's responsibility. Roman course/month labels share digit anchors.
    """
    q, selected, available = query.casefold(), selected_text.casefold(), available_text.casefold()
    missing = []
    for name, pattern in _ROLE_PATTERNS.items():
        if not (re.search(pattern, q) and re.search(pattern, available)):
            continue
        # A table can express one value per course/person without repeating
        # "тус бүр". Preserve the entire table rather than demand that wording.
        table_per_group = name == 'per_group' and len(_numbered_rows(selected_text)) >= 2
        if not re.search(pattern, selected) and not table_per_group:
            missing.append(name)
    required = _anchors(query) & _anchors(available_text)
    missing.extend('anchor:' + anchor for anchor in sorted(required - _anchors(selected_text)))
    return missing


_PUBLICATION_DATE = re.compile(
    r'(?P<year>(?:19|20)\d{2})\s+оны\s+'
    r'(?:нэгдүгээр|хоёрдугаар|гуравдугаар|дөрөвдүгээр|тавдугаар|зургаадугаар|'
    r'долоодугаар|наймдугаар|есдүгээр|аравдугаар|арван\s*нэгдүгээр|арван\s*хоёрдугаар|'
    r'0?[1-9]|1[0-2])\s+сарын\s+(?:0?[1-9]|[12]\d|3[01])'
    r'(?:\s+(?:\d{1,2}:\d{2}|\d+\s+үзсэн))*', re.I)


def _publication_years(unit):
    """Recognize dated source headings, never a year merely found in prose."""
    quote, start, end = unit.get('quote'), unit.get('start'), unit.get('end')
    if not isinstance(quote, str) or type(start) is not int or type(end) is not int:
        return set()
    years = set()
    for line_start, line_end, line in _lines(quote):
        match = _PUBLICATION_DATE.fullmatch(line)
        if not match or not start <= line_start < line_end <= end:
            continue
        prefix = _lines(quote[:line_start])
        if any(_prose(item[2]) and not item[2].isupper() for item in prefix):
            continue
        years.add(match['year'])
    return years


def resolve_evidence_selection(query, selected_ids, units, max_characters=1800, max_claims=3):
    """Resolve IDs into server-owned exact claims, preserving linked context.

    No free-form statement is accepted. Accepted means provenance and these
    bounded structural/explicit-marker checks passed; it is not entailment.
    """
    def result(reason, accepted=False, claims=None, **extra):
        return dict(accepted=accepted, reason=reason, claims=claims or [], **extra)

    if (not isinstance(selected_ids, list) or not 1 <= len(selected_ids) <= max_claims
            or any(not isinstance(sid, str) for sid in selected_ids)):
        return result('invalid_evidence_selection')
    if len(set(selected_ids)) != len(selected_ids):
        return result('duplicate_evidence_selection')
    known = {unit['unit_id']: unit for unit in units}
    expanded, visiting = [], set()

    def append(sid):
        if sid in expanded:
            return True
        if sid in visiting or sid not in known:
            return False
        visiting.add(sid)
        unit = known[sid]
        for context in unit.get('context_unit_ids', []):
            if not append(context):
                return False
        visiting.remove(sid)
        expanded.append(sid)
        return True

    if not all(append(sid) for sid in selected_ids):
        return result('unknown_evidence_unit')
    # A question may name an announcement year while the answer states a later
    # start year. Retain that distinction by adding the same source's actual
    # publication heading, rather than discarding or replacing the year check.
    selected_years = _anchors('\n'.join(known[sid]['text'] for sid in expanded))
    missing_years = set(re.findall(r'(?<!\d)(?:19|20)\d{2}(?!\d)', query)) - selected_years
    selected_sources = {known[sid]['source_id'] for sid in expanded}
    publication_context = []
    for year in sorted(missing_years):
        candidates = [unit for unit in units if unit['source_id'] in selected_sources
                      and year in _publication_years(unit)]
        if candidates:
            publication_context.append(min(candidates, key=lambda unit: (unit['start'], len(unit['text'])))['unit_id'])
    if publication_context:
        original_expanded = list(expanded)
        expanded.clear()
        visiting.clear()
        if not all(append(sid) for sid in publication_context + original_expanded):
            return result('unknown_evidence_unit')
    if len(expanded) > max_claims:
        return result('evidence_context_exceeds_claim_budget')
    claims = []
    for sid in expanded:
        unit = known[sid]
        source_id, start, end, text, quote = (unit.get(k) for k in ('source_id', 'start', 'end', 'text', 'quote'))
        if (not isinstance(quote, str) or type(start) is not int or type(end) is not int
                or not 0 <= start < end <= len(quote) or quote[start:end] != text
                or _unit_id(source_id, start, end, text) != sid):
            return result('invalid_evidence_unit')
        claims.append(dict(source_id=source_id, text=text, quote=quote))
    selected_text = '\n\n'.join(claim['text'] for claim in claims)
    if len(selected_text) > max_characters:
        return result('evidence_selection_exceeds_budget')
    missing = missing_query_markers(query, selected_text, '\n'.join(u['text'] for u in units))
    if missing:
        return result('requested_evidence_markers_missing', missing_markers=missing)
    return result('verbatim_evidence_selection', accepted=True, claims=claims,
                  selected_unit_ids=expanded, context_expanded=expanded != selected_ids,
                  publication_context_unit_ids=publication_context)
