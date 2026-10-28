"""Export a private, read-only topic navigation view; never answer or rank.

Topic membership is an authored proposal, not source approval, current validity,
an is-a ontology, RAPTOR clustering, or a knowledge graph reasoning system.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import copy
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

GROUPS = ('pages', 'passages', 'sources', 'facts', 'faqs')


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_topics(config):
    if config.get('schema_version') != 1 or config.get('relation') != 'topic_contains':
        raise ValueError('Expected v1 topic_contains navigation configuration.')
    topics = config['topics']
    ids = [t['topic_id'] for t in topics]
    if not ids or len(ids) != len(set(ids)) or not all(isinstance(x, str) and x for x in ids):
        raise ValueError('Topics require unique nonempty IDs.')
    parents = {t['topic_id']: t['parent_id'] for t in topics}
    if sum(parent is None for parent in parents.values()) != 1:
        raise ValueError('Topics require exactly one root.')
    for identifier in ids:
        seen, current = set(), identifier
        while current is not None:
            if current not in parents or current in seen:
                raise ValueError('Unknown parent or topic cycle.')
            seen.add(current)
            current = parents[current]
    if config['fallback_topic_id'] not in parents:
        raise ValueError('Unknown fallback topic.')
    seen = set()
    for rule in config.get('url_rules', []):
        kinds = [k for k in ('exact_path', 'path_prefix') if k in rule]
        if len(kinds) != 1 or not isinstance(rule[kinds[0]], str) or not rule[kinds[0]].startswith('/'):
            raise ValueError('URL rule requires one explicit path or path prefix.')
        key = (kinds[0], rule[kinds[0]])
        if key in seen or rule['topic_id'] not in parents:
            raise ValueError('Duplicate URL rule or unknown rule topic.')
        seen.add(key)
    seen = set()
    for rule in config.get('fact_rules', []):
        if rule['topic_id'] not in parents or not isinstance(rule['entity_id'], str):
            raise ValueError('Unknown fact topic or invalid entity.')
        if not isinstance(rule['key_prefixes'], list) or not rule['key_prefixes']:
            raise ValueError('Fact rules require key prefixes.')
        for prefix in rule['key_prefixes']:
            key = (rule['entity_id'], prefix)
            if not isinstance(prefix, str) or key in seen:
                raise ValueError('Invalid or duplicate fact prefix.')
            seen.add(key)
    for rule in config.get('source_reference_rules', []):
        if (rule['topic_id'] not in parents or not rule['exact_path'].startswith('/')
                or not isinstance(rule['literal_label'], str) or not rule['literal_label']
                or '\n' in rule['literal_label']):
            raise ValueError('Source reference requires an explicit path, topic and one literal line.')
    return parents


def url_topic(url, config):
    """Longest explicit path wins; prefixes match whole path segments only."""
    try:
        parts = urlsplit(url)
        if (parts.scheme != 'https' or parts.hostname != 'nmct.edu.mn'
                or parts.username or parts.password or parts.port not in (None, 443)):
            return config['fallback_topic_id']
        path = unquote(parts.path).rstrip('/') or '/'
    except (ValueError, TypeError):
        return config['fallback_topic_id']
    matches = []
    for rule in config.get('url_rules', []):
        exact = rule.get('exact_path')
        prefix = rule.get('path_prefix')
        if exact == path or (prefix is not None and (path == prefix or path.startswith(prefix.rstrip('/') + '/'))):
            matched = exact if exact is not None else prefix
            matches.append((len(matched), exact is not None, rule['topic_id']))
    return max(matches)[2] if matches else config['fallback_topic_id']


def build_tree(config, inputs):
    """Pure deterministic grouping; original payloads are retained unchanged."""
    parents = validate_topics(config)
    fallback = config['fallback_topic_id']
    records = {g: [] for g in GROUPS}
    source_topics, fact_topics = {}, {}
    source_references = {identifier: [] for identifier in parents}

    def reference_topics(item):
        return [source_topics[(r['document_id'], r['version'])]
                for r in item.get('source_refs', [])
                if (r['document_id'], r['version']) in source_topics]

    def first_known(topics):
        return next((t for t in topics if t != fallback), fallback)

    def add(group, identifier, payload, primary, others=(), basis='explicit_url', provenance=None):
        secondary = sorted(set(others) - {primary, fallback})
        records[group].append(dict(content_id=identifier, primary_topic_id=primary,
            secondary_topic_ids=secondary, membership_basis=basis,
            payload=copy.deepcopy(payload), provenance=copy.deepcopy(provenance or {})))

    for item in inputs.get('pages', []):
        identifier = 'page:' + digest([item['url'], item['version']])[:24]
        primary = url_topic(item['url'], config)
        secondary = []
        for rule in config.get('source_reference_rules', []):
            if primary == fallback or (unquote(urlsplit(item['url']).path).rstrip('/') or '/') != rule['exact_path']:
                continue
            occurrences = [dict(start_offset=m.start(), end_offset=m.end()) for m in
                re.finditer(r'(?m)^' + re.escape(rule['literal_label']) + r'$', item.get('text', ''))]
            if not occurrences:
                continue
            secondary.append(rule['topic_id'])
            source_references[rule['topic_id']].append(dict(content_id=identifier,
                literal_label=rule['literal_label'], label_occurrences=occurrences,
                match_scope='exact_captured_text_line; source link only, no claim validation',
                source={k: item.get(k) for k in ('url', 'version', 'retrieved_at', 'text_sha256',
                    'approval_status', 'valid_from', 'valid_until')}))
        add('pages', identifier, item, primary, secondary)
    for item in inputs.get('passages', []):
        add('passages', 'passage:' + item['source_id'], item, url_topic(item['url'], config),
            provenance=inputs.get('passage_provenance', {}).get(item['source_id']))
    for item in inputs.get('sources', []):
        primary = url_topic(item['source_url_or_filename'], config)
        source_topics[(item['document_id'], item['version'])] = primary
        identifier = f"source:{item['document_id']}@{item['version']}"
        add('sources', identifier, item, primary,
            provenance=inputs.get('source_provenance', {}).get(identifier))
    for item in inputs.get('facts', []):
        refs = reference_topics(item)
        matches = [(len(prefix), rule['topic_id'])
                   for rule in config.get('fact_rules', [])
                   if item.get('entity_id') == rule['entity_id']
                   for prefix in rule['key_prefixes'] if item.get('key', '').startswith(prefix)]
        primary = max(matches)[1] if matches else first_known(refs)
        fact_topics[item['fact_id']] = primary
        add('facts', 'fact:' + item['fact_id'], item, primary, refs,
            basis='entity_and_longest_key_prefix' if matches else 'referenced_source_url')
    for item in inputs.get('faqs', []):
        linked = [fact_topics[f] for f in item.get('fact_ids', []) if f in fact_topics]
        refs = reference_topics(item)
        primary = first_known(linked + refs)
        add('faqs', 'faq:' + item['faq_id'], item, primary, linked + refs,
            basis='first_known_linked_fact_then_referenced_source')

    seen = set()
    for group in GROUPS:
        records[group].sort(key=lambda r: r['content_id'])
        for record in records[group]:
            if record['content_id'] in seen:
                raise ValueError('Duplicate content ID; refusing an ambiguous export.')
            seen.add(record['content_id'])
    nodes = []
    for topic in config['topics']:
        identifier = topic['topic_id']
        direct = {g: [r['content_id'] for r in records[g] if r['primary_topic_id'] == identifier] for g in GROUPS}
        links = {g: [r['content_id'] for r in records[g] if identifier in r['secondary_topic_ids']] for g in GROUPS}
        linked_sources = {f"source:{ref['document_id']}@{ref['version']}"
            for group in ('facts', 'faqs') for record in records[group]
            if record['primary_topic_id'] == identifier
            for ref in record['payload'].get('source_refs', [])
            if (ref['document_id'], ref['version']) in source_topics}
        nodes.append(dict(topic, relation_to_parent='topic_contains' if parents[identifier] else None,
            child_ids=[k for k, parent in parents.items() if parent == identifier],
            primary_record_ids=direct, crosslink_record_ids=links,
            direct_counts={g: len(direct[g]) for g in GROUPS},
            subtree_counts={g: 0 for g in GROUPS},
            source_references=source_references[identifier],
            subtree_source_reference_count=0,
            source_ids=dict(retrieval=[r['payload']['source_id'] for r in records['passages']
                                      if r['primary_topic_id'] == identifier],
                            structured=sorted(linked_sources | set(direct['sources'])))))
    node_map = {n['topic_id']: n for n in nodes}
    for node in nodes:
        current = node['topic_id']
        while current is not None:
            for group in GROUPS:
                node_map[current]['subtree_counts'][group] += node['direct_counts'][group]
            node_map[current]['subtree_source_reference_count'] += (
                len(node['source_references']) + len(node['source_ids']['structured']))
            current = parents[current]
    totals = {g: len(records[g]) for g in GROUPS}
    missing_sources = [n['topic_id'] for n in nodes if n['topic_id'] != fallback
        and not n['subtree_source_reference_count']
        and not any(n['subtree_counts'][g] for g in ('pages', 'passages', 'sources'))]
    return dict(schema_version=1, relation='topic_contains', label_scope=config['label_scope'],
        information_scope=information_scope(config,nodes,totals),
        coverage_notes=dict(source_presence='At least one captured source or explicit source reference; not full topic coverage.',
            fact_presence='Existing structured fact records only; no facts extracted from page labels or body text.',
            passage_view='Existing retrieval-preparation rows at the recorded as-of date; not all captured text.'),
        membership_establishes_answer_truth=False, automatic_approval=False,
        database_modified=False, llm_calls=0, model_inference_calls=0,
        input_provenance=copy.deepcopy(inputs.get('provenance', {})),
        taxonomy_sha256=digest(config), counts=totals, topics=nodes, records=records,
        missing_evidence_topics=missing_sources, missing_source_topics=missing_sources,
        missing_fact_topics=[n['topic_id'] for n in nodes
            if n['topic_id'] != fallback and not n['subtree_counts']['facts']],
        review_needed_record_ids=[r['content_id'] for rows in records.values()
                                  for r in rows if r['primary_topic_id'] == fallback])


def information_scope(config, nodes, totals):
    """Public authored bounds plus observed coverage; no answerability score.

    The authored fields describe which questions may be supported, not which
    values exist. Counts always come from this selected database pair. Neither
    body text nor private provenance is exported or used to invent a fact.
    """
    declared=config.get('information_scope')
    if not isinstance(declared,dict) or declared.get('schema_version')!=1:
        return {}
    def text(value):
        return value.strip()[:2000] if isinstance(value,str) and not any(ord(c)<32 for c in value) else ''
    def strings(values):
        return [value for item in values[:24] if (value:=text(item))] if isinstance(values,list) else []
    by_id={node['topic_id']:node for node in nodes}
    root=next(node['topic_id'] for node in nodes if node['parent_id'] is None)
    fallback=config['fallback_topic_id']
    content_roots=[node for node in nodes if node['parent_id']==root and node['topic_id']!=fallback]
    raw_domains=declared.get('domains',[])
    if not isinstance(raw_domains,list) or len(raw_domains)>32:
        return {}
    fields={}
    for item in raw_domains:
        if not isinstance(item,dict) or item.get('topic_id') not in {node['topic_id'] for node in content_roots} or item['topic_id'] in fields:
            return {}
        fields[item['topic_id']]=strings(item.get('request_fields_mn'))
    domains=[]
    for node in content_roots:
        descendants=[]
        for candidate in nodes:
            current=candidate['topic_id']
            while current is not None and current!=node['topic_id']:
                current=by_id[current]['parent_id']
            if current==node['topic_id']:
                descendants.append(candidate['topic_id'])
        counts=copy.deepcopy(node['subtree_counts'])
        has_source=bool(node['subtree_source_reference_count'] or any(counts[key] for key in ('pages','passages','sources')))
        domains.append(dict(topic_id=node['topic_id'],label_mn=node['label_mn'],
            subtopic_ids=descendants,request_fields_mn=fields.get(node['topic_id'],[]),counts=counts,
            source_status='source_present' if has_source else 'source_missing',
            structured_status='records_present' if counts['facts'] or counts['faqs'] else 'records_missing'))
    gaps=[]
    for node in nodes:
        if node['topic_id'] in (root,fallback):
            continue
        counts=node['subtree_counts']
        has_source=bool(node['subtree_source_reference_count'] or any(counts[key] for key in ('pages','passages','sources')))
        if not has_source or not counts['facts']:
            gaps.append(dict(topic_id=node['topic_id'],label_mn=node['label_mn'],source_present=has_source,
                             facts=counts['facts'],faqs=counts['faqs']))
    return dict(schema_version=1,title_mn=text(declared.get('title_mn')),
        purpose_mn=text(declared.get('purpose_mn')),included_mn=strings(declared.get('included_mn')),
        excluded_mn=strings(declared.get('excluded_mn')),unknown_mn=strings(declared.get('unknown_mn')),
        domains=domains,domain_count=len(domains),topic_count=len(nodes),counts=copy.deepcopy(totals),
        gaps=gaps,review_bucket_topic_id=fallback,
        requires_matching_saved_evidence=True,automatic_answerability_claim=False,
        affects_retrieval=False,
        coverage_note_mn='Эх байгаа нь бүтэн, өнөөдөр хүчинтэй хариултын баталгаа биш. Бүтэцтэй баримтгүй салааны HTML текст хайлтад орсон байж болно. Нэг эх олон сэдэвтэй холбоотой тул салааны тоонуудыг нэмээд нийт гэж үзэхгүй.',
        tree_role_mn='Сэдэв → дэд сэдэв → эх/баримт/FAQ-ийн навигац. Энэ нь Gemma-ийн сурсан жин, нейрон сүлжээ эсвэл бүх асуултыг шийдэх reasoning мод биш.')


def load_inputs(root, *, website_database=None, content_database=None):
    """Resolve the selected sealed release; legacy fixtures use canonical paths.

    A corrupt activation never falls back. WebsiteRetriever's existing passage
    preparation is reused with dense retrieval disabled; no search is performed.
    """
    from content_release import ContentReleaseManager
    from CORE.website_corpus import readonly
    from sqlite_retrieval import ReadOnlyContentStore
    from website_retrieval import WebsiteRetriever, INDEX_VERSION

    root = Path(root).resolve()
    manager = ContentReleaseManager(root)
    explicit = website_database is not None or content_database is not None
    if explicit and (website_database is None or content_database is None):
        raise ValueError('Both selected databases are required.')
    active = None if explicit else manager.resolve()
    data = Path(active['data_root']) if active else root
    retriever = WebsiteRetriever(root=data, database=website_database, use_dense=False)
    retriever._refresh()
    with closing(readonly(retriever.database)) as db:
        db.execute('BEGIN')
        run = retriever._run
        if run is None:
            raise ValueError('A captured website run is required.')
        pages = [dict(row) for row in db.execute('''SELECT p.*,c.html_sha256,c.html_path,
            c.text_path,c.http_metadata FROM pages p JOIN captures c
            ON p.url=c.url AND p.version=c.version WHERE c.run_id=? ORDER BY p.url,p.version''', (run['run_id'],))]
        assets = [dict(row) for row in db.execute('SELECT * FROM assets WHERE run_id=? ORDER BY url', (run['run_id'],))]
    content_db = Path(content_database) if explicit else data / 'runtime/content.db'
    with ReadOnlyContentStore(content_db) as store:
        package_id = store.package_id()
        content = store.export(package_id)
        source_provenance = {f"source:{r['document_id']}@{r['version']}":
            dict(content_sha256=r['content_sha256']) for r in store.connection.execute(
                '''SELECT v.document_id,v.version,v.content_sha256 FROM source_versions v
                   JOIN package_sources p ON p.document_id=v.document_id AND p.version=v.version
                   WHERE p.package_id=?''', (package_id,))}
    page_map = {(p['url'], p['version']): p for p in pages}
    asset_map = {a['url']: a for a in assets}
    passage_provenance = {}
    for row in retriever._rows:
        page = page_map.get((row['url'], row['version']))
        passage_provenance[row['source_id']] = dict(run_id=run['run_id'],
            captured_page={k: page[k] for k in ('url', 'version', 'text_sha256', 'html_sha256',
                'retrieved_at', 'approval_status', 'valid_from', 'valid_until')} if page else None,
            captured_asset=asset_map.get(row['url']))
    later = None if explicit else manager.resolve()
    if (active or {}).get('activation_token') != (later or {}).get('activation_token'):
        raise ValueError('Active release changed during export; retry with the new selection.')
    return dict(content, pages=pages, passages=copy.deepcopy(retriever._rows),
        source_provenance=source_provenance, passage_provenance=passage_provenance,
        provenance=dict(selection='explicit_database_pair' if explicit else 'active_sealed_release' if active else 'canonical_paths_without_active_release',
            release_id=active['release_id'] if active else None,
            activation_token=active['activation_token'] if active else None,
            package_id=package_id, corpus_id=retriever._corpus_id,
            retrieval_index_version=INDEX_VERSION, retrieval_view_as_of=date.today().isoformat(),
            capture_run=run, document_warnings=list(retriever._document_warnings),
            website_database_sha256=file_sha(retriever.database), content_database_sha256=file_sha(content_db)))


def write_output(output, value):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8', newline='\n') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        handle.write('\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--topics', type=Path, default=ROOT / 'config/knowledge-topics.json')
    parser.add_argument('--output', type=Path, required=True, help='New private JSON file; existing files are refused.')
    args = parser.parse_args()
    config = json.loads(args.topics.read_text(encoding='utf-8-sig'))
    result = build_tree(config, load_inputs(args.root))
    result['artifact_sha256'] = {'tools/build_knowledge_tree.py': file_sha(__file__),
                                 'topic_config_file': file_sha(args.topics)}
    write_output(args.output, result)
    print(json.dumps(dict(output=str(args.output.resolve()), counts=result['counts'],
        missing_evidence_topics=result['missing_evidence_topics'], database_modified=False)))


if __name__ == '__main__':
    main()
