"""Validate a curated package's exact-clause provenance without model calls.

Portable validation checks package/quote hashes, dependencies and inherited
records. --require-sources additionally checks the private saved source files;
the portable result alone never claims those files were available or verified.
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from content_store import digest, shape_errors
from validate_content import validate_content
from CORE.website_corpus import PageParser

SHA256 = re.compile(r'[0-9a-f]{64}\Z')


def text_sha256(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _file(root, relative):
    if not isinstance(relative, str) or not relative:
        raise ValueError('Missing source-relative path.')
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError('Source file escapes project root.')
    return path


def validate_evidence(content, evidence, *, root=None, require_sources=False):
    errors = []
    verified = set()
    unavailable = set()
    try:
        errors.extend(shape_errors(content))
        errors.extend(validate_content(content))
        if evidence.get('schema_version') != 1:
            errors.append('Unsupported evidence schema_version.')
        if evidence.get('reviewer_kind') != 'assistant':
            errors.append('Evidence must retain its assistant review scope.')
        if evidence.get('package_id') != digest(content):
            errors.append('Package digest differs from evidence.')
        if evidence.get('counts') != {g: len(content[g]) for g in ('sources', 'facts', 'faqs')}:
            errors.append('Package counts differ from evidence.')
        if not SHA256.fullmatch(evidence.get('baseline_sha256', '')):
            errors.append('Invalid baseline file SHA256.')
        if not SHA256.fullmatch(evidence.get('baseline_package_id', '')):
            errors.append('Invalid baseline package digest.')
        facts = {f['fact_id']: f for f in content['facts']}
        faqs = {f['faq_id']: f for f in content['faqs']}
        sources = {(s['document_id'], s['version']): s for s in content['sources']}
        source_proofs = {(s['document_id'], s['version']): s for s in evidence['source_proofs']}
        fact_proofs = {f['fact_id']: f for f in evidence['fact_proofs']}
        if len(source_proofs) != len(evidence['source_proofs']):
            errors.append('Duplicate source proof.')
        if len(fact_proofs) != len(evidence['fact_proofs']):
            errors.append('Duplicate fact proof.')
        if set(fact_proofs) != set(evidence['new_fact_ids']):
            errors.append('New facts and fact proofs differ.')
        if len(set(evidence['new_fact_ids'])) != len(evidence['new_fact_ids']):
            errors.append('Duplicate new fact identity.')
        if len(set(evidence['new_faq_ids'])) != len(evidence['new_faq_ids']):
            errors.append('Duplicate new FAQ identity.')
        if not set(evidence['new_faq_ids']) <= set(faqs):
            errors.append('New FAQ is missing from package.')
        expected_inherited = evidence.get('inherited_counts', {})
        if (len(facts) - len(fact_proofs) != expected_inherited.get('facts')
                or len(faqs) - len(evidence['new_faq_ids']) != expected_inherited.get('faqs')):
            errors.append('Inherited record count differs.')

        def check_file(relative, expected_hash):
            if not SHA256.fullmatch(expected_hash or ''):
                raise ValueError(f'Invalid file SHA256: {relative}')
            if root is None:
                unavailable.add(relative)
                if require_sources:
                    errors.append(f'Source root required: {relative}')
                return None
            path = _file(root, relative)
            if not path.is_file():
                unavailable.add(relative)
                if require_sources:
                    errors.append(f'Source file unavailable: {relative}')
                return None
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
                errors.append(f'Source file SHA256 mismatch: {relative}')
                return None
            verified.add(relative)
            return path

        baseline_file = check_file(evidence['baseline_file'], evidence['baseline_sha256'])
        if baseline_file is not None:
            baseline = json.loads(baseline_file.read_text(encoding='utf-8-sig'))
            if digest(baseline) != evidence['baseline_package_id']:
                errors.append('Baseline package digest mismatch.')
            for group, key in [('sources', 'document_id'), ('facts', 'fact_id'), ('faqs', 'faq_id')]:
                def identity(item):
                    return (item[key], item['version']) if group == 'sources' else item[key]
                current = {identity(item): item for item in content[group]}
                if len(baseline[group]) != expected_inherited.get(group):
                    errors.append(f'Baseline {group} count differs.')
                for item in baseline[group]:
                    if current.get(identity(item)) != item:
                        errors.append(f'Inherited {group} record changed: {identity(item)}')

        manifest_path = check_file(evidence['source_manifest_file'], evidence['source_manifest_sha256'])
        captured_pages, captured_assets = {}, {}
        if manifest_path is not None:
            manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
            if manifest['run_id'] != evidence['source_run_id']:
                errors.append('Source manifest run identity differs.')
            captured_pages = {p['url']:p for p in manifest['pages']}
            captured_assets = {p['url']:p for p in manifest['documents']}

        saved = {}
        for identity, proof in source_proofs.items():
            source = sources.get(identity)
            if source is None:
                errors.append(f'Source proof has no source: {identity}')
                continue
            if (source['source_url_or_filename'] != proof['url']
                    or source['retrieved_at'] != proof['retrieved_at']):
                errors.append(f'Source URL/capture time differs: {identity}')
            if (source['approval_status'] != 'draft' or source['approved_by'] is not None
                    or source['approved_at'] is not None or source['valid_from'] is not None
                    or source['valid_until'] is not None or source['source_updated_at'] is not None):
                errors.append(f'Source invented approval or validity metadata: {identity}')
            path = check_file(proof['input_file'], proof['input_sha256'])
            if proof['kind'] == 'saved_html_main_text':
                html_path = check_file(proof['html_file'], proof['html_sha256'])
                capture = captured_pages.get(proof['url'])
                if manifest_path is not None:
                    if (capture is None or capture['retrieved_at'] != proof['retrieved_at']
                            or capture['html_sha256'] != proof['html_sha256']
                            or capture['text_sha256'] != proof['input_sha256']
                            or _file(root, proof['html_file']) != manifest_path.parent / capture['html_file']
                            or _file(root, proof['input_file']) != manifest_path.parent / capture['text_file']):
                        errors.append(f'HTML source differs from captured manifest: {identity}')
                if html_path is not None and capture is not None:
                    parser = PageParser()
                    parser.feed(html_path.read_bytes().decode(capture['http']['charset']))
                    extracted = parser.result()
                    if (extracted['text_scope'] != 'main_element'
                            or extracted['text_scope'] != proof['text_scope']
                            or text_sha256(extracted['text']) != proof['input_sha256']):
                        errors.append(f'Saved text differs from main HTML extraction: {identity}')
                if path is not None:
                    saved[identity] = path.read_text(encoding='utf-8')
            elif proof['kind'] == 'selected_visual_transcription':
                check_file(proof['asset_file'], proof['asset_sha256'])
                capture = captured_assets.get(proof['url'])
                if manifest_path is not None:
                    if (capture is None or capture['retrieved_at'] != proof['retrieved_at']
                            or capture['sha256'] != proof['asset_sha256']
                            or _file(root, proof['asset_file']) != manifest_path.parent / capture['file']):
                        errors.append(f'Document source differs from captured manifest: {identity}')
                if (proof.get('method') != 'visual_transcription' or proof.get('reviewer_kind') != 'assistant'
                        or proof.get('coverage') != 'selected_passages'):
                    errors.append(f'Document review scope changed: {identity}')
                if path is not None:
                    bundle = json.loads(path.read_text(encoding='utf-8-sig'))
                    doc = next((d for d in bundle['documents'] if d['url'] == proof['url']
                                and d['version'] == proof['extraction_version']), None)
                    if doc is None or doc['asset_sha256'] != proof['asset_sha256']:
                        errors.append(f'Document extraction identity differs: {identity}')
                    else:
                        saved[identity] = {p['locator']: p['text'] for p in doc['passages']}
            else:
                errors.append(f'Unsupported source proof kind: {identity}')

        for fid, proof in fact_proofs.items():
            fact = facts.get(fid)
            identity = (proof['document_id'], proof['version'])
            sp = source_proofs.get(identity)
            if fact is None or sp is None:
                errors.append(f'Missing fact/source proof dependency: {fid}')
                continue
            if (fact['approval_status'] != 'draft' or any(fact[k] is not None
                    for k in ('approved_by','approved_at','valid_from','valid_until'))):
                errors.append(f'Fact invented approval or validity metadata: {fid}')
            reference = dict(document_id=identity[0], version=identity[1], locator=proof['locator'])
            if fact['source_refs'] != [reference]:
                errors.append(f'Fact reference differs from exact proof: {fid}')
            if (proof['input_file'] != sp['input_file'] or proof['input_sha256'] != sp['input_sha256']):
                errors.append(f'Fact input differs from source proof: {fid}')
            if not isinstance(proof['quotes'], list) or not proof['quotes']:
                errors.append(f'Empty fact quotes: {fid}')
                continue
            clauses = fact['value']['published_clause']
            clauses = clauses if isinstance(clauses, list) else [clauses]
            if clauses != [q['quote'] for q in proof['quotes']]:
                errors.append(f'Fact clause differs from proof: {fid}')
            if fact['value']['year_scope'] != proof['year_scope']:
                errors.append(f'Fact year scope differs from proof: {fid}')
            for q in proof['quotes']:
                if q['quote_sha256'] != text_sha256(q['quote']):
                    errors.append(f'Quote SHA256 mismatch: {fid}')
                if (type(q['start']) is not int or type(q['end']) is not int
                        or q['start'] < 0 or q['end'] != q['start'] + len(q['quote'])):
                    errors.append(f'Quote offsets invalid: {fid}')
                    continue
                original = saved.get(identity)
                if original is not None:
                    if isinstance(original, dict):
                        original = original.get(proof['locator'], '')
                    if original[q['start']:q['end']] != q['quote']:
                        errors.append(f'Saved source clause differs: {fid}')

        for fid in evidence['new_faq_ids']:
            faq = faqs.get(fid)
            if faq is not None and not set(faq['fact_ids']) <= set(fact_proofs):
                errors.append(f'New FAQ depends on an untraced inherited fact: {fid}')
            if faq is not None:
                if (faq['approval_status'] != 'draft' or any(faq[k] is not None
                        for k in ('approved_by','approved_at','valid_from','valid_until'))):
                    errors.append(f'FAQ invented approval or validity metadata: {fid}')
                expected_refs = {(r['document_id'],r['version'],r['locator'])
                    for fact_id in faq['fact_ids'] for r in facts[fact_id]['source_refs']}
                actual_refs = {(r['document_id'],r['version'],r['locator']) for r in faq['source_refs']}
                if actual_refs != expected_refs:
                    errors.append(f'FAQ exact dependency locators differ: {fid}')
    except (AttributeError, KeyError, TypeError, ValueError, OSError, UnicodeError) as error:
        errors.append(f'Malformed or unreadable evidence: {error}')
    return dict(valid=not errors, errors=errors, source_files_verified=sorted(verified),
        source_files_unavailable=sorted(unavailable), source_verification_required=require_sources,
        reviewer_kind='assistant', human_gold=False, school_staff_approval_claimed=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('content', type=Path)
    parser.add_argument('evidence', type=Path)
    parser.add_argument('--root', type=Path)
    parser.add_argument('--require-sources', action='store_true')
    args = parser.parse_args()
    result = validate_evidence(json.loads(args.content.read_text(encoding='utf-8-sig')),
        json.loads(args.evidence.read_text(encoding='utf-8-sig')), root=args.root,
        require_sources=args.require_sources)
    sys.stdout.reconfigure(encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result['valid']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
