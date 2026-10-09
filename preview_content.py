"""Preview a selected fact/FAQ with source links; this is not a router or retrieval model."""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

from validate_content import validate_content


def preview(content, identity, *, allow_draft=False, as_of=None):
    errors = validate_content(content)
    if errors:
        raise ValueError('; '.join(errors))
    all_records = content['facts'] + content['faqs']
    item = next((item for item in all_records if item.get('fact_id', item.get('faq_id')) == identity), None)
    if item is None:
        raise KeyError(f'Unknown fact/FAQ ID: {identity}')
    sources = {(item['document_id'], item['version']): item for item in content['sources']}
    facts = {item['fact_id']: item for item in content['facts']}
    cited = [sources[(ref['document_id'], ref['version'])] for ref in item['source_refs']]
    dependencies = [item, *cited, *[facts[key] for key in item.get('fact_ids', [])]]
    if not allow_draft and any(item['approval_status'] != 'approved' for item in dependencies):
        raise ValueError('Selected content or a dependency is unapproved. Development preview requires --allow-draft.')
    subset = dict(schema_version=1, sources=list({(source['document_id'], source['version']): source for source in cited}.values()),
                  facts=[item] if 'fact_id' in item else [facts[key] for key in item['fact_ids']],
                  faqs=[item] if 'faq_id' in item else [])
    errors = validate_content(subset, approved_only=not allow_draft, as_of=as_of)
    if errors:
        raise ValueError('; '.join(errors))
    result = dict(
        id=identity, preview_mode='development_draft' if allow_draft else 'approved',
        approval_status=item['approval_status'],
        answer=item.get('answer', item.get('value')), scope=item['scope'],
        sources=[dict(document_id=source['document_id'], version=source['version'],
                      title=source['title'], url=source['source_url_or_filename'],
                      locator=ref['locator'], approval_status=source['approval_status'])
                 for source, ref in zip(cited, item['source_refs'])])
    return result


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('id')
    parser.add_argument('--content', type=Path, default=Path(__file__).resolve().parent / 'data/content-draft-v1.json')
    parser.add_argument('--allow-draft', action='store_true')
    parser.add_argument('--as-of', type=date.fromisoformat)
    args = parser.parse_args()
    content = json.loads(args.content.read_text(encoding='utf-8-sig'))
    try:
        result = preview(content, args.id, allow_draft=args.allow_draft, as_of=args.as_of)
    except (ValueError, KeyError) as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
