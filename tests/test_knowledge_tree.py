"""Invented navigation fixtures; no school gold, network or model inference."""
from contextlib import closing
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from content_release import ReleaseInvalid
from content_store import ContentStore
from CORE.website_corpus import PageParser, import_snapshot
from tools.build_knowledge_tree import build_tree, load_inputs, url_topic, validate_topics, write_output
from test_content_store import fixture


ROOT = Path(__file__).resolve().parents[1]


def taxonomy():
    return json.loads((ROOT / 'config/knowledge-topics.json').read_text(encoding='utf-8'))


def invented_inputs():
    ref = dict(document_id='invented-source', version=3, locator='invented locator')
    source = dict(document_id=ref['document_id'], version=ref['version'],
        source_url_or_filename='https://nmct.edu.mn/elselt', approval_status='draft',
        retrieved_at='fixture-capture-time', valid_from=None, valid_until=None)
    fact = dict(fact_id='invented-fee', entity_id='nmct.admissions', key='registration_fee.future',
        value='invented fixture value', source_refs=[ref], approval_status='draft',
        valid_from=None, valid_until=None)
    page = dict(url='https://nmct.edu.mn/about/environment', version=7,
        text='Invented environment\nНомын сан\nБиеийн тамирын заал\n',
        text_sha256='fixture-sha', retrieved_at='fixture-time', approval_status='rejected',
        valid_from=None, valid_until=None)
    return dict(pages=[page, dict(page, url='https://nmct.edu.mn/unclassified', version=2)],
        passages=[dict(source_id='invented-passage', url=page['url'], version=7,
            text='invented excerpt', start_offset=2, end_offset=18, extraction_method='fixture')],
        sources=[source], facts=[fact],
        faqs=[dict(faq_id='invented-faq', fact_ids=[fact['fact_id']], source_refs=[ref], answer='fixture'),
              dict(faq_id='invented-faq-2', fact_ids=[fact['fact_id']], source_refs=[ref], answer='fixture')])


class KnowledgeTreeTests(unittest.TestCase):
    def test_taxonomy_is_single_parent_acyclic_and_rejects_invalid_hierarchies(self):
        config = taxonomy()
        parents = validate_topics(config)
        self.assertEqual(sum(p is None for p in parents.values()), 1)
        for mutate in ('cycle', 'unknown_parent', 'duplicate_id', 'second_root'):
            broken = copy.deepcopy(config)
            if mutate == 'cycle':
                broken['topics'][1]['parent_id'] = broken['topics'][2]['topic_id']
            elif mutate == 'unknown_parent':
                broken['topics'][1]['parent_id'] = 'missing'
            elif mutate == 'duplicate_id':
                broken['topics'].append(copy.deepcopy(broken['topics'][1]))
            else:
                broken['topics'][1]['parent_id'] = None
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                validate_topics(broken)

    def test_longest_explicit_path_wins_without_prefix_or_host_leakage(self):
        config = taxonomy()
        for url, expected in (
            ('https://nmct.edu.mn/departments/computer-science', 'academics.computer-science'),
            ('https://nmct.edu.mn/departments/unseen', 'academics'),
            ('https://nmct.edu.mn/departments-other', 'review-needed'),
            ('https://nmct.edu.mn/events/science-olimpiad-events', 'admissions.olympiad'),
            ('https://nmct.edu.mn/news?page=2', 'news'),
            ('https://example.invalid/departments/computer-science', 'review-needed')):
            self.assertEqual(url_topic(url, config), expected)
            reversed_config = dict(config, url_rules=list(reversed(config['url_rules'])))
            self.assertEqual(url_topic(url, reversed_config), expected)

    def test_every_record_retained_once_and_root_counts_reconcile(self):
        inputs = invented_inputs()
        result = build_tree(taxonomy(), inputs)
        root = next(n for n in result['topics'] if n['parent_id'] is None)
        for group, rows in result['records'].items():
            self.assertEqual(len(rows), len(inputs[group]))
            self.assertEqual(root['subtree_counts'][group], len(inputs[group]))
            all_primary = [r for n in result['topics'] for r in n['primary_record_ids'][group]]
            self.assertEqual(len(all_primary), len(set(all_primary)))
            self.assertEqual(len(all_primary), len(inputs[group]))
        self.assertTrue(result['review_needed_record_ids'])
        unknown = [r for r in result['records']['pages'] if r['primary_topic_id'] == 'review-needed']
        self.assertEqual(unknown[0]['payload']['url'], 'https://nmct.edu.mn/unclassified')

    def test_shared_fact_crosslinks_do_not_create_extra_facts(self):
        result = build_tree(taxonomy(), invented_inputs())
        self.assertEqual(result['counts']['facts'], 1)
        self.assertEqual(result['counts']['faqs'], 2)
        fact = result['records']['facts'][0]
        self.assertEqual(fact['primary_topic_id'], 'admissions.fees')
        self.assertIn('admissions', fact['secondary_topic_ids'])
        admissions = next(n for n in result['topics'] if n['topic_id'] == 'admissions')
        self.assertEqual(admissions['crosslink_record_ids']['facts'], [fact['content_id']])
        self.assertEqual(admissions['subtree_counts']['facts'], 1)
        fees = next(n for n in result['topics'] if n['topic_id'] == 'admissions.fees')
        self.assertEqual(fees['source_ids']['structured'], ['source:invented-source@3'])

    def test_literal_page_links_distinguish_missing_sources_from_missing_facts(self):
        inputs = invented_inputs()
        result = build_tree(taxonomy(), inputs)
        self.assertNotIn('student.library', result['missing_source_topics'])
        self.assertIn('student.library', result['missing_fact_topics'])
        library = next(n for n in result['topics'] if n['topic_id'] == 'student.library')
        reference = library['source_references'][0]
        self.assertEqual(library['direct_counts']['pages'], 0)
        self.assertEqual(len(library['crosslink_record_ids']['pages']), 1)
        for occurrence in reference['label_occurrences']:
            text = inputs['pages'][0]['text']
            self.assertEqual(text[occurrence['start_offset']:occurrence['end_offset']], 'Номын сан')
        self.assertEqual(reference['source']['approval_status'], 'rejected')
        inputs['pages'][0]['text'] = 'A sentence containing Номын сан in prose.'
        inputs['pages'][1]['text'] = 'Номын сан'  # Wrong URL cannot supply a link.
        self.assertIn('student.library', build_tree(taxonomy(), inputs)['missing_source_topics'])

    def test_payload_metadata_and_values_are_unchanged_and_copied(self):
        inputs = invented_inputs()
        original = copy.deepcopy(inputs)
        result = build_tree(taxonomy(), inputs)
        for group, rows in result['records'].items():
            expected = sorted(json.dumps(p, sort_keys=True) for p in original[group])
            actual = sorted(json.dumps(r['payload'], sort_keys=True) for r in rows)
            self.assertEqual(actual, expected)
        result['records']['facts'][0]['payload']['value'] = 'changed output only'
        self.assertEqual(inputs, original)
        self.assertFalse(result['membership_establishes_answer_truth'])

    def test_unknown_source_fact_and_faq_survive_and_duplicate_identity_fails(self):
        inputs = invented_inputs()
        inputs['sources'][0]['source_url_or_filename'] = 'unknown-source.txt'
        inputs['facts'][0]['entity_id'] = 'unknown-entity'
        result = build_tree(taxonomy(), inputs)
        for group in ('sources', 'facts', 'faqs'):
            self.assertTrue(all(r['primary_topic_id'] == 'review-needed' for r in result['records'][group]))
        inputs['facts'].append(copy.deepcopy(inputs['facts'][0]))
        with self.assertRaisesRegex(ValueError, 'Duplicate content ID'):
            build_tree(taxonomy(), inputs)

    def test_serialization_is_reproducible_and_refuses_overwrite(self):
        result = build_tree(taxonomy(), invented_inputs())
        with tempfile.TemporaryDirectory() as directory:
            first, second = (Path(directory) / x for x in ('first.json', 'second.json'))
            write_output(first, result)
            write_output(second, build_tree(taxonomy(), invented_inputs()))
            self.assertEqual(first.read_bytes(), second.read_bytes())
            before = first.read_bytes()
            with self.assertRaises(FileExistsError):
                write_output(first, {'unexpected': 'replacement'})
            self.assertEqual(first.read_bytes(), before)

    def test_information_scope_uses_existing_roots_and_observed_counts(self):
        config=taxonomy();result=build_tree(config,invented_inputs());scope=result['information_scope']
        self.assertEqual(scope['domain_count'],8)
        self.assertEqual(scope['topic_count'],len(config['topics']))
        self.assertEqual(scope['counts'],result['counts'])
        self.assertFalse(scope['automatic_answerability_claim'])
        self.assertFalse(scope['affects_retrieval'])
        self.assertTrue(scope['requires_matching_saved_evidence'])
        self.assertNotIn('review-needed',[item['topic_id'] for item in scope['domains']])
        for domain in scope['domains']:
            node=next(item for item in result['topics'] if item['topic_id']==domain['topic_id'])
            self.assertEqual(domain['counts'],node['subtree_counts'])
            self.assertTrue(domain['request_fields_mn'])
            self.assertIn(domain['topic_id'],domain['subtopic_ids'])

    def test_information_scope_does_not_turn_source_presence_into_full_answers(self):
        scope=build_tree(taxonomy(),invented_inputs())['information_scope']
        student=next(item for item in scope['domains'] if item['topic_id']=='student')
        self.assertEqual(student['source_status'],'source_present')
        self.assertEqual(student['structured_status'],'records_missing')
        gap=next(item for item in scope['gaps'] if item['topic_id']=='student.environment')
        self.assertTrue(gap['source_present']);self.assertEqual(gap['facts'],0)
        self.assertNotIn('answerable',student)
        school=next(item for item in scope['domains'] if item['topic_id']=='school')
        self.assertEqual(school['source_status'],'source_missing')

    def test_information_scope_only_exports_public_contract_not_private_provenance(self):
        config=taxonomy();inputs=invented_inputs()
        config['information_scope']['private_path']='SECRET-CONFIG-PATH'
        config['information_scope']['domains'][0]['secret']='SECRET-DOMAIN'
        inputs['provenance']={'path':'SECRET-PROVENANCE'}
        scope=build_tree(config,inputs)['information_scope']
        rendered=json.dumps(scope)
        for secret in ('SECRET-CONFIG-PATH','SECRET-DOMAIN','SECRET-PROVENANCE'):
            self.assertNotIn(secret,rendered)
        scope['domains'][0]['counts']['facts']=999
        self.assertNotEqual(build_tree(config,inputs)['information_scope']['domains'][0]['counts']['facts'],999)

    def test_scope_is_optional_and_invalid_domain_declaration_fails_closed(self):
        config=taxonomy();del config['information_scope']
        self.assertEqual(build_tree(config,invented_inputs())['information_scope'],{})
        for invalid in ('school.history','missing'):
            config=taxonomy();config['information_scope']['domains'][0]['topic_id']=invalid
            self.assertEqual(build_tree(config,invented_inputs())['information_scope'],{})

    def test_empty_corpus_has_no_false_source_or_fact_promotion(self):
        scope=build_tree(taxonomy(),{})['information_scope']
        self.assertTrue(all(item['source_status']=='source_missing' for item in scope['domains']))
        self.assertTrue(all(item['structured_status']=='records_missing' for item in scope['domains']))
        self.assertTrue(all(not value for value in scope['counts'].values()))


def captured_data(root):
    """Minimal real SQLite stores and captured bytes, all invented for tests."""
    snapshot = root / 'CORE/website/snapshots/invented-run'
    snapshot.mkdir(parents=True)
    body = b'<html><title>Fixture</title><main>Invented captured environment.</main></html>'
    parser = PageParser(); parser.feed(body.decode())
    text = parser.result()['text']
    (snapshot / 'page.html').write_bytes(body)
    (snapshot / 'page.txt').write_text(text, encoding='utf-8')
    manifest = dict(run_id='invented-run', retrieved_at='2026-10-01T00:00:00+00:00', inventory=[], pages=[dict(
        url='https://nmct.edu.mn/about/environment', status='ok', html_file='page.html', text_file='page.txt',
        html_sha256=hashlib.sha256(body).hexdigest(), text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        retrieved_at='2026-10-01T00:00:00+00:00', http={'charset': 'utf-8', 'last_modified': None})])
    (snapshot / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    import_snapshot(root / 'CORE/database/website.db', snapshot)
    with ContentStore(root / 'runtime/content.db') as store:
        store.import_content(fixture(), allow_draft=True)


class InputSelectionTests(unittest.TestCase):
    def test_active_data_is_selected_without_models_or_database_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'root'
            root.mkdir()
            selected = root / 'runtime/selected/data'
            captured_data(selected)
            paths = [selected / 'CORE/database/website.db', selected / 'runtime/content.db']
            before = [p.read_bytes() for p in paths]
            active = dict(data_root=str(selected), release_id='invented-active', activation_token='same-token')
            with patch('content_release.ContentReleaseManager.resolve', return_value=active), \
                    patch('website_retrieval._LocalE5.load', side_effect=AssertionError('No model allowed')):
                inputs = load_inputs(root)
            self.assertEqual(inputs['provenance']['selection'], 'active_sealed_release')
            self.assertEqual(len(inputs['pages']), 1)
            self.assertEqual(len(inputs['passages']), 1)
            self.assertEqual([p.read_bytes() for p in paths], before)
            self.assertIn('captured_page', inputs['passage_provenance'][inputs['passages'][0]['source_id']])
            self.assertFalse((root / 'CORE/database/website.db').exists())
            with patch('content_release.ContentReleaseManager.resolve', return_value=None):
                self.assertEqual(load_inputs(selected)['provenance']['selection'], 'canonical_paths_without_active_release')

    def test_invalid_activation_never_silently_falls_back(self):
        with patch('content_release.ContentReleaseManager.resolve', side_effect=ReleaseInvalid('corrupt activation')):
            with self.assertRaisesRegex(ReleaseInvalid, 'corrupt activation'):
                load_inputs(ROOT)

    def test_changing_activation_refuses_mixed_export(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            captured_data(root)
            first = dict(data_root=str(root), release_id='invented', activation_token='before')
            with patch('content_release.ContentReleaseManager.resolve', side_effect=[first, dict(first, activation_token='after')]):
                with self.assertRaisesRegex(ValueError, 'Active release changed'):
                    load_inputs(root)


if __name__ == '__main__':
    unittest.main()
