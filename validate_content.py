"""Validate the NMCT content contract and source links using the standard library.

This is a domain validator, not a general JSON Schema implementation.
"""
import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path


def validate_content(content, *, approved_only=False, as_of=None):
    errors = []
    if not isinstance(content, dict) or content.get('schema_version') != 1:
        return ['Unsupported content schema_version.']
    groups = [('sources', 'document_id'), ('facts', 'fact_id'), ('faqs', 'faq_id')]
    indexes = {}
    for group, identity in groups:
        items = content.get(group)
        if not isinstance(items, list):
            errors.append(f'{group}: expected a list.')
            indexes[group] = {}
            continue
        index = {}
        for number, item in enumerate(items):
            label = f'{group}[{number}]'
            if not isinstance(item, dict):
                errors.append(f'{label}: expected an object.')
                continue
            key = item.get(identity)
            if not isinstance(key, str) or not key.strip():
                errors.append(f'{label}: missing {identity}.')
            else:
                if group == 'sources':
                    version = item.get('version')
                    if type(version) is not int or version < 1:
                        errors.append(f'{label}: invalid source version.')
                        unique_key = None
                    else:
                        unique_key = (key, version)
                else:
                    unique_key = key
                if unique_key is not None:
                    if unique_key in index:
                        errors.append(f'{label}: duplicate {identity}/version {unique_key}.')
                    else:
                        index[unique_key] = item
            state = item.get('approval_status')
            if state not in {'draft', 'approved', 'rejected', 'expired'}:
                errors.append(f'{label}: invalid approval_status.')
            if approved_only and state != 'approved':
                errors.append(f'{label}: approved-only import rejects {state}.')
            for field in ('approved_by', 'approved_at'):
                if field not in item or (item[field] is not None and not isinstance(item[field], str)):
                    errors.append(f'{label}: missing/invalid {field}.')
            if state == 'approved':
                for field in ('approved_by', 'approved_at'):
                    if not isinstance(item.get(field), str) or not item[field].strip():
                        errors.append(f'{label}: approved metadata requires {field}.')
                if isinstance(item.get('approved_at'), str) and item['approved_at'].strip():
                    try:
                        datetime.fromisoformat(item['approved_at'].replace('Z', '+00:00'))
                    except ValueError:
                        errors.append(f'{label}: invalid approved_at timestamp.')
            parsed = {}
            for field in ('valid_from', 'valid_until'):
                value = item.get(field)
                if field not in item:
                    errors.append(f'{label}: missing {field}; use null when unknown.')
                if value is not None:
                    try:
                        parsed[field] = date.fromisoformat(value)
                    except (ValueError, TypeError):
                        errors.append(f'{label}: invalid {field} date.')
            if len(parsed) == 2 and parsed['valid_from'] > parsed['valid_until']:
                errors.append(f'{label}: validity dates are reversed.')
            if as_of is not None:
                if parsed.get('valid_until') and parsed['valid_until'] < as_of:
                    errors.append(f'{label}: expired for {as_of}.')
                if parsed.get('valid_from') and parsed['valid_from'] > as_of:
                    errors.append(f'{label}: not yet valid for {as_of}.')
        indexes[group] = index
    sources = {}
    for source_key, source in indexes['sources'].items():
        document_id = source['document_id']
        version = source.get('version')
        if type(version) is not int or version < 1:
            errors.append(f'{document_id}: invalid source version.')
        else:
            sources[(document_id, version)] = source
        for field in ('title', 'source_url_or_filename', 'retrieved_at', 'scope'):
            if not isinstance(source.get(field), str) or not source[field].strip():
                errors.append(f'{document_id}: missing {field}.')
    for group in ('facts', 'faqs'):
        for key, item in indexes[group].items():
            references = item.get('source_refs')
            if not isinstance(references, list) or not references:
                errors.append(f'{key}: source_refs must not be empty.')
                continue
            for reference in references:
                if not isinstance(reference, dict):
                    errors.append(f'{key}: invalid source reference.')
                    continue
                source = sources.get((reference.get('document_id'), reference.get('version')))
                if source is None:
                    errors.append(f'{key}: referenced source version not found.')
                elif item.get('approval_status') == 'approved' and source.get('approval_status') != 'approved':
                    errors.append(f'{key}: approved record depends on an unapproved source.')
                if not isinstance(reference.get('locator'), str) or not reference['locator'].strip():
                    errors.append(f'{key}: source locator required.')
            if not isinstance(item.get('scope'), str) or not item['scope'].strip():
                errors.append(f'{key}: scope required.')
    for key, fact in indexes['facts'].items():
        if 'value' not in fact:
            errors.append(f'{key}: fact value is missing.')
        for field in ('entity_id', 'key'):
            if not isinstance(fact.get(field), str) or not fact[field].strip():
                errors.append(f'{key}: missing {field}.')
    for key, faq in indexes['faqs'].items():
        for field in ('question', 'answer'):
            if not isinstance(faq.get(field), str) or not faq[field].strip():
                errors.append(f'{key}: missing {field}.')
        fact_ids = faq.get('fact_ids')
        if not isinstance(fact_ids, list) or not fact_ids:
            errors.append(f'{key}: fact_ids must not be empty.')
            continue
        faq_refs = {(r.get('document_id'), r.get('version')) for r in faq.get('source_refs', []) if isinstance(r, dict)}
        for fact_id in fact_ids:
            fact = indexes['facts'].get(fact_id)
            if fact is None:
                errors.append(f'{key}: referenced fact {fact_id} not found.')
            else:
                refs = {(r.get('document_id'), r.get('version')) for r in fact.get('source_refs', []) if isinstance(r, dict)}
                if not refs <= faq_refs:
                    errors.append(f'{key}: FAQ omits a supporting fact source version.')
                if faq.get('approval_status') == 'approved' and fact.get('approval_status') != 'approved':
                    errors.append(f'{key}: approved FAQ depends on an unapproved fact.')
    return errors


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('content', type=Path)
    parser.add_argument('--approved-only', action='store_true')
    parser.add_argument('--as-of', type=date.fromisoformat)
    args = parser.parse_args()
    content = json.loads(args.content.read_text(encoding='utf-8-sig'))
    errors = validate_content(content, approved_only=args.approved_only, as_of=args.as_of)
    if errors:
        for error in errors:
            print(error)
        raise SystemExit(1)
    print(f'Content links valid: {len(content["sources"])} sources, {len(content["facts"])} facts, '
          f'{len(content["faqs"])} FAQs. Mode: {"approved-only" if args.approved_only else "development draft"}.')
    if not args.approved_only:
        print('Draft records are not approved production content.')


if __name__ == '__main__':
    main()
