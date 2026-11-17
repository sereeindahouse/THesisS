"""Tell a visitor where to get information the system cannot give.

The training office asked (2026-11-09) that the reception assistant must not
stop at "not found": it should say where the information can be obtained.
This layer only adds a sentence to an unanswered result. It never writes an
answer, never guesses a fact, and only names a responsible office after the
school has approved the topic -> office table (`topic_offices.approved`).
"""
import json
import re
from pathlib import Path

CONFIG_PATH = 'config/referral.json'


def load_referral(root):
    """Return the referral settings, or None when missing, invalid or disabled."""
    try:
        data = json.loads((Path(root) / CONFIG_PATH).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    general = data.get('general') if isinstance(data, dict) else None
    if not data.get('enabled') or not isinstance(general, dict) or not general.get('text_mn'):
        return None
    return data


def load_topic_rules(root):
    """URL -> topic rules from the knowledge tree (same rules the data atlas uses)."""
    try:
        data = json.loads((Path(root) / 'config/knowledge-topics.json').read_text(encoding='utf-8'))
        return data.get('url_rules', [])
    except (OSError, ValueError):
        return []


def topic_of(url, rules):
    path = re.sub(r'^https?://[^/]+', '', str(url or '')).split('?')[0].rstrip('/') or '/'
    for rule in rules:
        if rule.get('exact_path') == path:
            return rule.get('topic_id')
    best = None
    for rule in rules:
        prefix = rule.get('path_prefix')
        if prefix and path.startswith(prefix) and (best is None or len(prefix) > len(best[0])):
            best = (prefix, rule.get('topic_id'))
    return best[1] if best else None


def _office(result, referral, rules, locate):
    offices = referral.get('topic_offices') or {}
    if offices.get('approved') is not True:
        return None
    for source in result.get('related_sources') or []:
        topic = topic_of(source.get('url'), rules)
        while topic:
            name = (offices.get('map') or {}).get(topic)
            if name:
                place = locate(name) if locate else None
                return name + (' (' + place + ')' if place else '')
            topic = topic.rpartition('.')[0]
    return None


def _question_office(query, referral, locate):
    """Office named by the question's own words, e.g. «төлбөр» -> finance office.

    An unanswered result's related pages are often the wrong ones (a payment
    question retrieves the career page), so the question decides the topic.
    The first matching rule wins; a rule without an office (job applications)
    stops the search. An office is named only when the school's room table
    places it, so a missing table names nothing.
    """
    offices = referral.get('question_offices') or {}
    if offices.get('enabled') is not True or not locate:
        return None
    text = str(query or '').lower()
    for rule in offices.get('rules') or ():
        if re.search(rule['pattern'], text):
            place = locate(rule['office']) if rule.get('office') else None
            # '' = the question's topic was found but names no office here: no page-topic guess.
            return rule['office'] + ' (' + place + ')' if place else ''
    return None


def attach_referral(result, referral, *, rules=(), locate=None):
    """Add "where to ask" to a result that has no answer; answered results are unchanged."""
    if not referral or result.get('answer') or result.get('clarification'):
        return result
    office = _question_office(result.get('query'), referral, locate)
    source = 'question' if office else None
    if office is None:
        office = _office(result, referral, rules, locate)
        source = 'source_topic' if office else None
    office = office or None
    general = referral['general']
    text = ('Энэ сэдвээр лавлах газар: ' + office + '. ' + general.get('with_office_mn', general['text_mn'])
            if office else general['text_mn'])
    reviewed = bool(office) and ((referral.get('question_offices') or {}).get('reviewed') is True
                                 if source == 'question' else True)
    result['referral'] = dict(text=text, office=office, office_source=source, office_reviewed=reviewed,
                              source=general.get('source'))
    message = (result.get('message') or '').strip()
    result['message'] = (message + ' ' + text).strip()
    return result
