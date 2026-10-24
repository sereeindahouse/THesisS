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


def _bullet_row(line):
    # The captured source uses this literal bullet. Acronyms and punctuation
    # inside its item are content, not a new uppercase heading/prose boundary.
    return bool(re.match(r'^•\s+\S', line))


def _prose(line):
    # Lists of requirements often omit punctuation. Never split them into
    # standalone answers, even when an individual row happens to be long.
    # A physical measurement/location can start an ordinary paragraph; it
    # is not the index of a requirement list. Leading-zero and punctuated
    # list labels stay lists, including long rows containing other amounts.
    if _bullet_row(line):
        return False
    measurement_prose = re.match(r'^[1-9]\d?\s+(?:давх(?:ар|рын|арт|рыг)|м[²2])(?:\s|[,;:])', line)
    if re.match(r'^\d{1,2}[.)]?\s+', line) and not measurement_prose:
        return False
    return not line.endswith('?') and (len(line) > 100 or line.endswith(('.', '!', '。')))


def _paragraph_spans(text):
    """Yield contiguous physical paragraphs with preceding heading/list text.

    Sentence punctuation is not a safe boundary: the same paragraph can contain
    both a per-person quantity and a total, or a condition and its exception.
    """
    pending = []
    for line in _lines(text):
        if pending and line[2].isupper() and not _bullet_row(line[2]):
            yield pending[0][0], pending[-1][1]
            pending = []
        pending.append(line)
        if _prose(line[2]):
            yield pending[0][0], pending[-1][1]
            pending = []
    if pending:
        yield pending[0][0], pending[-1][1]


_BADGE_NUMBER = re.compile(r'\d[\d,.]*\+?')
_BADGE_UNIT = re.compile(
    r'(?:м[²2](?:\s+(?:нийт\s+)?талбай)?|(?:хүний\s+)?суудал|'
    r'ном(?:,?\s+сурах\s+бичиг)?|хүн|оюутан|багш|минут|хоног)', re.I)

_DIRECTION_LABEL = re.compile(
    r'[^\W\d_]+(?:аас|ээс|оос|өөс)\s+(?:дээш|доош|баруун|зүүн|дотогш|гадагш)\s*[:：]?', re.I)
_STRUCTURE_NEGATION = re.compile(
    r'\bбиш\b|байхгүй|тодорхойгүй|(?:хэрэгж|явагд|урс|чиглэ|бай)[а-яёөү]*гүй\b', re.I)


def direction_card_bindings(text):
    """Physical direction-heading/name/prose triples, not inferred meanings.

    Names and directions are read from the source. No domain, organisation or
    expected flow-name pair is stored here; a bare direction mention is not a
    binding. Only immediate short labels followed by a complete prose row count.
    """
    lines = _lines(text)
    bindings = []
    for index, (start, _, heading) in enumerate(lines[:-2]):
        if not _DIRECTION_LABEL.fullmatch(heading):
            continue
        _, _, label = lines[index + 1]
        _, end, description = lines[index + 2]
        if (not 2 <= len(label) <= 100 or _prose(label)
                or _DIRECTION_LABEL.fullmatch(label) or _bullet_row(label)
                or not description.endswith(('.', '!', '。')) or len(description) < 24
                or _STRUCTURE_NEGATION.search(label + '\n' + description)):
            continue
        bindings.append(dict(start=start, end=end, direction=heading.rstrip(':：').casefold(), label=label))
    return bindings


def _structural_spans(text, spans):
    """Keep tightly adjacent source cards and same-entity paragraphs intact."""
    combined = []
    index = 0
    while index < len(spans):
        start, end = spans[index]
        lines = _lines(text[start:end])
        if index + 1 < len(spans):
            next_start, next_end = spans[index + 1]
            following = _lines(text[next_start:next_end])
            # A legal company suffix is structure, not a particular partner.
            # An intervening heading, another paragraph or explicit company
            # name cannot be silently inherited through this pronoun link.
            company_heading = bool(lines and re.fullmatch(
                r'[A-Za-z0-9][A-Za-z0-9 &,./()\-]{0,90}\s+(?:Ltd\.?|Inc\.?|Corp\.?|LLC|PLC)', lines[0][2], re.I))
            # A complete captured window can start at the company's explicit
            # descriptive sentence rather than its separate legal-name line.
            # Accept only a literal initial Latin name + "компани нь" lead.
            company_heading = company_heading or bool(len(lines) == 1 and re.match(
                r'^[A-Za-z][A-Za-z0-9 &./()\-]{1,90}\s+компани\s+нь\b', lines[0][2], re.I))
            pronoun = (re.search(r'\bтус\s+компани[а-яёөү]*\b', following[0][2][:120], re.I)
                       if len(following) == 1 else None)
            prefix = following[0][2][:pronoun.start()] if pronoun else ''
            same_company = (pronoun and following[0][2].endswith(('.', '!', '。'))
                            and not re.search(r'[A-Za-z]|компани', prefix, re.I))
            if company_heading and same_company and not text[end:next_start].strip():
                combined.append((start, next_end))
                index += 2
                continue
        combined.append((start, end))
        index += 1
    result = []
    index = 0
    while index < len(combined):
        start, end = combined[index]
        if index and index + 1 < len(combined):
            previous_start, previous_end = combined[index - 1]
            next_start, next_end = combined[index + 1]
            intro = text[previous_start:previous_end]
            bindings = direction_card_bindings(text[start:next_end])
            prefix = text[end:next_start]
            if (re.search(r'\b(?:хоёр|2)\s+(?:чиглэл|урсгал)[а-яёөү]*\b', intro, re.I)
                    and not _STRUCTURE_NEGATION.search(intro)
                    and len(bindings) == 2 and len({b['direction'] for b in bindings}) == 2
                    and bindings[0]['start'] == 0 and bindings[0]['end'] == end - start
                    and bindings[1]['end'] == next_end - start and not prefix.strip()):
                result.append((start, next_end))
                index += 2
                continue
        result.append((start, end))
        index += 1
    return result


def _spans(text):
    """Attach a trailing numeric measurement badge to its preceding prose.

    The HTML text flattens a paragraph followed by its statistic card into
    separate physical lines. A bare facility name or numbered list is not a
    measurement badge. Moving this exact boundary keeps every nonspace source
    character and does not rewrite quantities, clauses or conditions.
    """
    spans = list(_paragraph_spans(text))
    adjusted = []
    for start, end in spans:
        if adjusted:
            previous_start, previous_end = adjusted[-1]
            previous_lines = _lines(text[previous_start:previous_end])
            lines = _lines(text[start:end])
            if (previous_lines and _prose(previous_lines[-1][2])
                    and not text[previous_end:start].strip()
                    and len(lines) >= 2 and _BADGE_NUMBER.fullmatch(lines[0][2])
                    and _BADGE_UNIT.fullmatch(lines[1][2])):
                badge_end = start + lines[1][1]
                adjusted[-1] = (previous_start, badge_end)
                remainder = text[badge_end:end]
                start = badge_end + len(remainder) - len(remainder.lstrip())
        if start < end:
            adjusted.append((start, end))
    yield from _structural_spans(text, adjusted)


def _source_spans(source):
    """Apply verified DOM boundaries before physical paragraph grouping.

    Every segment remains an exact, contiguous slice of the same source. The
    saved HTML supplies section/card boundaries; query words and expected
    numerical answers never decide where the source is split. Legacy excerpts
    and invalid metadata retain the conservative physical-text grouping.
    """
    text = source['text']
    cuts = source.get('structure_boundaries')
    valid = (source.get('text_scope') == 'main_element'
             and source.get('structure_method') == 'verified-captured-dom-v1'
             and source.get('structure_text_sha256') == hashlib.sha256(text.encode('utf-8')).hexdigest()
             and isinstance(cuts, list) and bool(cuts)
             and all(type(cut) is int and 0 < cut < len(text) for cut in cuts)
             and cuts == sorted(set(cuts))
             and all(text[cut - 1] == '\n' or text[cut] == '\n' for cut in cuts))
    boundaries = [0, *cuts, len(text)] if valid else [0, len(text)]
    for left, right in zip(boundaries, boundaries[1:]):
        for start, end in _spans(text[left:right]):
            yield left + start, left + end


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
    return bool(re.match(r'\s*(?:үүнээс|энэ|тус|мөн|харин|гэхдээ|ийм|тийм|тухайлбал)\b', text, re.I))


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
        previous_physical = None
        for physical_start, end in _source_spans(source):
            start = _after_template_counters(text, physical_start, end)
            span = text[start:end]
            previous = previous_physical
            # Record every physical paragraph before filtering. An omitted
            # paragraph remains a boundary; it is never replaced by the last
            # older selectable unit of the source.
            previous_physical = dict(start=physical_start, end=end,
                                     conditional=_explicit_conditional(span), unit=None)
            if not 12 <= len(span) <= max_characters:
                continue
            unit = dict(unit_id=_unit_id(sid, start, end, span), source_id=sid,
                        text=span, start=start, end=end, quote=text,
                        url=source.get('url'), context_unit_ids=[])
            offset = source.get('start_offset')
            if (source.get('text_scope') == 'main_element' and source.get('version') is not None
                    and isinstance(source.get('url'), str) and type(offset) is int and offset >= 0
                    and source.get('end_offset') == offset + len(text)):
                # Coordinate systems of document/client excerpts are different.
                # Only complete captured HTML supplies canonical page offsets.
                unit['page_span'] = dict(url=source['url'], version=source['version'],
                                         start=offset + start, end=offset + end)
            if previous and (_continues_previous(span) or previous['conditional']):
                # A dependent paragraph without its physical predecessor is
                # not a standalone claim. Keep it out of the selectable pool
                # rather than attach it across omitted text or a trimmed prefix.
                if (previous['unit'] is None or start != physical_start
                        or text[previous['end']:physical_start].strip()):
                    continue
                unit['context_unit_ids'] = [previous['unit']['unit_id']]
            units.append(unit)
            previous_physical['unit'] = unit
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

_ROLE_CONTEXT_STOP = set(('нийт тус бүр бүрээс бүрийн хэд хэдэн хэдийг ямар юу вэ бэ уу үү '
    'болон ба буюу хамтад хэлээрэй мэдээлсэн мэдээлэл үзүүлэлт үзүүлэлтийг хүрээ '
    'хэмжээ тоо тоог оны онд жил жилийн анх тусдаа тус бүр нь гэж гэсэн '
    'сургууль сургуулийн хуудсанд танилцуулгад').split())
_ROLE_CONTEXT_SUFFIXES = ('уудын', 'үүдийн', 'гийн', 'ийн', 'ын', 'ийг', 'аар', 'ээр', 'оор', 'өөр')


def _role_context_tokens(text):
    """Small lexical context check, not a parser or semantic completeness test."""
    tokens = set()
    for token in re.findall(r'[а-яёөү]+', text.casefold()):
        if token in _ROLE_CONTEXT_STOP:
            continue
        for suffix in _ROLE_CONTEXT_SUFFIXES:
            if token.endswith(suffix) and len(token) - len(suffix) >= 3:
                token = token[:-len(suffix)]
                break
        if len(token) >= 3 and token not in _ROLE_CONTEXT_STOP:
            tokens.add(token[:4])
    return tokens


def _total_context_matches(query, available_text):
    # A total on an unrelated nearby topic cannot create a requirement for
    # another measure. Questions without an explicit object keep the strict
    # old check. A 90-character local window is deliberately bounded.
    # Bind the role to its own question clause, not another requested field
    # later in a compound question (e.g. a programme's adoption history).
    match = re.search(_ROLE_PATTERNS['total'], query, re.I)
    clause = re.split(r'[,;?\n]|\b(?:болон|буюу)\b', query[match.end():], maxsplit=1)[0]
    objects = _role_context_tokens(' '.join(clause.split()[:6]))
    if not objects:
        return True
    return any(objects & _role_context_tokens(available_text[max(0, m.start()-90):m.end()+90])
               for m in re.finditer(_ROLE_PATTERNS['total'], available_text, re.I))


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
        if name == 'total' and not _total_context_matches(query, available_text):
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


def _heading_boundary(line):
    """Treat an unfinished physical line as a possible section boundary.

    A long or omitted heading must still block inheritance from an older
    section. Bare lines can also be unfinished prose, so this is deliberately
    conservative: identifying a boundary does not make it usable name context.
    """
    company = (re.fullmatch(r'[A-Za-z0-9 &,./()\-]+', line)
               and re.search(r'\b(?:Ltd|Inc|Co)\.$', line))
    return bool(company or not line.endswith(('.', '!', '?', '。', '！', '？')))


def _short_heading(unit):
    """Recognize only an initial short physical heading, never body mentions."""
    lines = _lines(unit.get('text', ''))
    if not lines:
        return None
    line = lines[0][2]
    if len(line) > 100 or len(line.split()) > 8 or not _heading_boundary(line):
        return None
    return line


def _named_heading_context(query, expanded, units, known):
    """Keep a named section's preceding heading when its body omits the name.

    Only a query's literal Latin/code anchor is considered. The nearest
    preceding heading must belong to the same source; another heading blocks
    inheritance. This does not infer arbitrary Mongolian named entities.
    """
    required = {anchor for anchor in _anchors(query)
                if re.fullmatch(r'[a-z][a-z0-9]*', anchor)}
    missing = required - _anchors('\n'.join(known[sid]['text'] for sid in expanded))
    context = []
    for sid in expanded:
        selected = known[sid]
        # Possible section starts block inheritance even if they are too long
        # to be trusted as a name heading. Check physical source lines too:
        # oversized/unselectable units must not disappear as boundaries.
        selected_lines = _lines(selected.get('text', ''))
        if selected_lines and _heading_boundary(selected_lines[0][2]):
            continue
        quote, start = selected.get('quote'), selected.get('start')
        if not isinstance(quote, str) or type(start) is not int:
            continue
        boundaries = [line for line in _lines(quote[:start]) if _heading_boundary(line[2])]
        if not boundaries:
            continue
        heading_start, _, heading_text = boundaries[-1]
        preceding = [unit for unit in units if unit['source_id'] == selected['source_id']
                     and unit['start'] == heading_start and unit['end'] <= start
                     and _short_heading(unit) == heading_text]
        if preceding and missing & _anchors(heading_text):
            heading = preceding[0]
            context.append(heading['unit_id'])
    return list(dict.fromkeys(context))


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
    named_context = _named_heading_context(query, expanded, units, known)
    if named_context:
        original_expanded = list(expanded)
        expanded.clear()
        visiting.clear()
        if not all(append(sid) for sid in named_context + original_expanded):
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
    # Remove only copies of the same physical HTML span. A substring on another
    # page/year/position is independent evidence and must not disappear. Validate
    # every expanded unit above before considering any of them redundant.
    removed = {}
    for position, sid in enumerate(expanded):
        unit = known[sid]
        span = unit.get('page_span')
        if not isinstance(span, dict) or set(span) != {'url', 'version', 'start', 'end'}:
            continue
        if (type(span['start']) is not int or type(span['end']) is not int
                or span['start'] < 0 or span['end'] - span['start'] != len(unit['text'])):
            continue
        for other_position, other_id in enumerate(expanded):
            if sid == other_id:
                continue
            other = known[other_id]; parent = other.get('page_span')
            if (not isinstance(parent, dict) or set(parent) != set(span)
                    or parent['url'] != span['url'] or parent['version'] != span['version']
                    or type(parent['start']) is not int or type(parent['end']) is not int
                    or parent['end'] - parent['start'] != len(other['text'])
                    or not parent['start'] <= span['start'] < span['end'] <= parent['end']):
                continue
            if (parent['start'] == span['start'] and parent['end'] == span['end']
                    and other_position > position):
                continue
            left, right = span['start'] - parent['start'], span['end'] - parent['start']
            if other['text'][left:right] == unit['text']:
                removed[sid] = other_id
                break
    all_expanded = list(expanded)
    if removed:
        for sid, covering in list(removed.items()):
            while covering in removed:
                covering = removed[covering]
            removed[sid] = covering
        claims = [claim for sid, claim in zip(expanded, claims) if sid not in removed]
        expanded = [sid for sid in expanded if sid not in removed]
    selected_text = '\n\n'.join(claim['text'] for claim in claims)
    if len(selected_text) > max_characters:
        return result('evidence_selection_exceeds_budget')
    missing = missing_query_markers(query, selected_text, '\n'.join(u['text'] for u in units))
    if missing:
        return result('requested_evidence_markers_missing', missing_markers=missing)
    return result('verbatim_evidence_selection', accepted=True, claims=claims,
                  selected_unit_ids=expanded, context_expanded=expanded != selected_ids,
                  expanded_unit_ids=all_expanded, duplicate_unit_coverage=removed,
                  publication_context_unit_ids=publication_context,
                  named_heading_context_unit_ids=named_context)
