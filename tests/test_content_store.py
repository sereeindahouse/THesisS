"""Contract tests use invented fixtures, never school approval or final gold labels."""
import copy
import tempfile
import unittest
from datetime import date
from pathlib import Path

from content_store import ContentStore


def fixture(state='draft', version=1):
    metadata = {'approval_status': state, 'approved_by': 'test-only reviewer' if state == 'approved' else None,
                'approved_at': '2026-10-10T09:00:00+08:00' if state == 'approved' else None,
                'valid_from': '2026-10-01', 'valid_until': '2026-10-31'}
    ref = {'document_id': 'test.source', 'version': version, 'locator': 'test paragraph'}
    return {'schema_version': 1,
            'sources': [{'document_id': 'test.source', 'version': version, 'title': 'Invented fixture',
                         'source_url_or_filename': 'test-only.txt', 'retrieved_at': '2026-10-10',
                         'source_updated_at': None, 'scope': 'test only',
                         'content_capture': 'selected_fact_extract', 'notes': '', **metadata}],
            'facts': [{'fact_id': 'test.fact', 'entity_id': 'test.entity', 'key': 'name',
                       'value': 'Зөвхөн тест', 'source_refs': [copy.deepcopy(ref)], 'scope': 'test only',
                       'notes': '', **metadata}],
            'faqs': [{'faq_id': 'test.faq', 'question': 'Тест үү?', 'answer': 'Зөвхөн тестийн хариулт.',
                      'question_aliases': ['Тест мөн үү?'], 'fact_ids': ['test.fact'],
                      'source_refs': [copy.deepcopy(ref)], 'scope': 'test only',
                      'answer_status': 'complete_in_scope', 'notes': '', **metadata}]}


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ContentStore(Path(self.temp.name) / 'content.db')
        self.today = date(2026, 10, 10)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_repeat_import_does_not_duplicate_or_change_draft(self):
        content = fixture()
        first = self.store.import_content(content, allow_draft=True)
        second = self.store.import_content(copy.deepcopy(content), allow_draft=True)
        self.assertTrue(first['imported'])
        self.assertFalse(second['imported'])
        self.assertEqual(first['package_id'], second['package_id'])
        self.assertEqual(self.store.counts(), {'sources': 1, 'facts': 1, 'faqs': 1, 'citations': 2, 'faq_fact_links': 1})
        self.assertEqual(self.store.connection.execute('SELECT count(*) FROM packages').fetchone()[0], 1)
        self.assertEqual(self.store.export()['faqs'][0]['approval_status'], 'draft')

    def test_default_import_and_preview_reject_draft(self):
        with self.assertRaisesRegex(ValueError, 'approved-only'):
            self.store.import_content(fixture())
        self.store.import_content(fixture(), allow_draft=True)
        blocked = self.store.preview('faq', 'test.faq', as_of=self.today)
        self.assertFalse(blocked['eligible'])
        self.assertIsNone(blocked['answer'])
        draft = self.store.preview('faq', 'test.faq', allow_draft=True, as_of=self.today)
        self.assertTrue(draft['eligible'])
        self.assertEqual(draft['mode'], 'development_draft')
        self.assertEqual(draft['citations'][0]['version'], 1)
        self.assertFalse(draft['automatic_approval'])

    def test_approved_metadata_is_separate_snapshot_and_old_package_preserved(self):
        old = self.store.import_content(fixture(), allow_draft=True)['package_id']
        new = self.store.import_content(fixture('approved'))['package_id']
        self.assertNotEqual(old, new)
        self.assertTrue(self.store.preview('faq', 'test.faq', as_of=self.today)['eligible'])
        self.assertFalse(self.store.preview('faq', 'test.faq', package_id=old, as_of=self.today)['eligible'])
        self.assertEqual(self.store.connection.execute('SELECT count(*) FROM source_versions').fetchone()[0], 1)
        self.store.import_content(fixture(), allow_draft=True)
        self.assertEqual(self.store.package_id(), new)

    def test_dependency_validity_blocks_even_explicit_draft_preview(self):
        content = fixture('approved')
        content['facts'][0]['valid_until'] = '2026-10-09'
        self.store.import_content(content)
        for allow_draft in (False, True):
            output = self.store.preview('faq', 'test.faq', allow_draft=allow_draft, as_of=self.today)
            self.assertFalse(output['eligible'])
            self.assertIsNone(output['answer'])
            self.assertTrue(any('fact:test.fact: expired' in r for r in output['blocked_reasons']))

    def test_future_source_and_expired_rejected_status_never_served(self):
        for state in ('draft', 'expired', 'rejected'):
            content = fixture(state)
            content['sources'][0]['valid_from'] = '2026-10-11'
            package = self.store.import_content(content, allow_draft=True)['package_id']
            result = self.store.preview('fact', 'test.fact', package_id=package,
                                        allow_draft=True, as_of=self.today)
            self.assertFalse(result['eligible'])
            self.assertIsNone(result['value'])

    def test_unapproved_dependency_and_missing_citation_rejected_atomically(self):
        for broken in ('source', 'fact', 'version'):
            content = fixture('approved')
            if broken == 'source':
                content['sources'][0]['approval_status'] = 'draft'
            elif broken == 'fact':
                content['facts'][0]['approval_status'] = 'draft'
            else:
                content['faqs'][0]['source_refs'][0]['version'] = 99
            with self.assertRaises(ValueError):
                self.store.import_content(content, allow_draft=True)
        self.assertEqual(self.store.connection.execute('SELECT count(*) FROM packages').fetchone()[0], 0)

    def test_same_source_version_content_mutation_rolls_back(self):
        first = self.store.import_content(fixture(), allow_draft=True)
        changed = fixture()
        changed['sources'][0]['title'] = 'Changed source text'
        with self.assertRaisesRegex(ValueError, 'increment version'):
            self.store.import_content(changed, allow_draft=True)
        self.assertEqual(self.store.package_id(), first['package_id'])
        self.assertEqual(self.store.connection.execute('SELECT count(*) FROM packages').fetchone()[0], 1)

    def test_new_source_version_preserves_exact_old_citations(self):
        old = self.store.import_content(fixture(), allow_draft=True)['package_id']
        changed = fixture(version=2)
        changed['sources'][0]['title'] = 'New version'
        new = self.store.import_content(changed, allow_draft=True)['package_id']
        self.assertEqual(self.store.preview('faq', 'test.faq', package_id=old,
                                          allow_draft=True, as_of=self.today)['citations'][0]['version'], 1)
        self.assertEqual(self.store.preview('faq', 'test.faq', package_id=new,
                                          allow_draft=True, as_of=self.today)['citations'][0]['version'], 2)
        self.assertEqual(list(self.store.connection.execute('PRAGMA foreign_key_check')), [])

    def test_unknown_validity_is_visible_and_boundary_dates_inclusive(self):
        content = fixture('approved')
        content['sources'][0]['valid_until'] = None
        self.store.import_content(content)
        result = self.store.preview('faq', 'test.faq', as_of=date(2026, 10, 31))
        self.assertTrue(result['eligible'])
        self.assertIn('source:test.source@1', result['unknown_validity_records'])
        self.assertFalse(self.store.preview('faq', 'test.faq', as_of=date(2026, 11, 1))['eligible'])
        self.assertFalse(self.store.preview('faq', 'test.faq', as_of=date(2026, 9, 30))['eligible'])

    def test_malformed_shapes_are_rejected_before_mutation(self):
        cases = [[], {'schema_version': 1}, fixture(), fixture(), fixture()]
        cases[2]['faqs'][0]['source_refs'][0]['version'] = True
        cases[3]['sources'][0]['unexpected'] = 'not in contract'
        cases[4]['faqs'][0]['fact_ids'] = [{}]
        for content in cases:
            with self.subTest(content=content):
                with self.assertRaises(ValueError):
                    self.store.import_content(content, allow_draft=True)
        self.assertEqual(self.store.connection.execute('SELECT count(*) FROM packages').fetchone()[0], 0)

    def test_record_listing_never_contains_answer_values(self):
        self.store.import_content(fixture(), allow_draft=True)
        output = self.store.list_records(allow_draft=True, as_of=self.today)
        self.assertEqual(len(output), 1)
        self.assertNotIn('answer', output[0])
        self.assertEqual(output[0]['question'], 'Тест үү?')


if __name__ == '__main__':
    unittest.main()
