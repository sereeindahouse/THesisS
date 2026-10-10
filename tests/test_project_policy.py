import json
import tempfile
import unittest
from copy import deepcopy
from datetime import date
from pathlib import Path

from content_store import ContentStore
from project_policy import ContentUsePolicy
from sqlite_retrieval import ReadOnlyContentStore, search_content


class OfficialPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'config').mkdir()
        (self.root / 'config/content-use.json').write_text(json.dumps(dict(
            enabled=True, basis='user_acceptance_of_official_website', accepted_on='2026-10-10',
            official_hosts=['nmct.edu.mn'])), encoding='utf-8')
        source = dict(document_id='school', version=1, title='School',
            source_url_or_filename='https://nmct.edu.mn/contact', retrieved_at='2026-10-10',
            source_updated_at=None, scope='General school contact', content_capture='selected_fact_extract',
            notes='', approval_status='draft', approved_by=None, approved_at=None,
            valid_from=None, valid_until=None)
        fact = dict(fact_id='phone', entity_id='school', key='phone', value='75777799',
            source_refs=[dict(document_id='school', version=1, locator='Contact')],
            scope='General contact', notes='', approval_status='draft', approved_by=None,
            approved_at=None, valid_from=None, valid_until=None)
        faq = dict(faq_id='faq.contact', question='Сургуулийн утас хэд вэ?', answer='75777799',
            question_aliases=[], fact_ids=['phone'], source_refs=fact['source_refs'],
            scope='General contact', answer_status='complete_in_scope', notes='',
            approval_status='draft', approved_by=None, approved_at=None, valid_from=None, valid_until=None)
        self.data = dict(schema_version=1, sources=[source], facts=[fact], faqs=[faq])
        self.db = self.root / 'content.db'
        self.policy = ContentUsePolicy(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def import_data(self, data=None):
        with ContentStore(self.db) as store:
            store.import_content(data or self.data, allow_draft=True)

    def test_official_snapshot_answer_without_fabricating_school_approval(self):
        self.import_data()
        before = self.db.read_bytes()
        result = self.policy.route(self.db, 'Сургуулийн утас хэд вэ?')
        self.assertEqual(result['answer'], '75777799')
        self.assertEqual(result['answer_kind'], 'official_website_snapshot')
        self.assertFalse(result['school_staff_approval_claimed'])
        self.assertEqual(result['citations'][0]['approval_status'], 'draft')
        self.assertEqual(before, self.db.read_bytes())

    def test_unknown_dates_stay_unknown(self):
        self.import_data()
        result = self.policy.route(self.db, 'Сургуулийн утас хэд вэ?')
        self.assertTrue(result['unknown_validity_records'])

    def test_external_lookalike_is_not_official(self):
        self.data['sources'][0]['source_url_or_filename'] = 'https://nmct.edu.mn.evil.test/contact'
        self.import_data()
        self.assertIsNone(self.policy.route(self.db, 'Сургуулийн утас хэд вэ?')['answer'])

    def test_known_expiry_not_bypassed(self):
        self.data['facts'][0]['valid_until'] = '2020-01-01'
        self.import_data()
        self.assertIsNone(self.policy.route(self.db, 'Сургуулийн утас хэд вэ?')['answer'])

    def test_metadata_only_is_not_answer_evidence(self):
        self.data['sources'][0]['content_capture'] = 'audit_metadata_only'
        self.import_data()
        self.assertIsNone(self.policy.route(self.db, 'Сургуулийн утас хэд вэ?')['answer'])

    def test_rejected_source_not_bypassed(self):
        self.data['sources'][0]['approval_status'] = 'rejected'
        self.import_data()
        self.assertIsNone(self.policy.route(self.db, 'Сургуулийн утас хэд вэ?')['answer'])

    def test_partial_not_promoted(self):
        self.data['faqs'][0]['answer_status'] = 'partial_in_scope'
        self.import_data()
        self.assertIsNone(self.policy.route(self.db, 'Сургуулийн утас хэд вэ?')['answer'])

    def test_missing_policy_keeps_strict_default(self):
        self.import_data()
        result = ContentUsePolicy(self.root / 'other').route(self.db, 'Сургуулийн утас хэд вэ?')
        self.assertIsNone(result['answer'])

    def test_fuzzy_match_never_returns_answer(self):
        self.import_data()
        self.assertIsNone(self.policy.route(self.db, 'утас')['answer'])

    def test_explicit_draft_keeps_draft_attribution(self):
        self.import_data()
        result = self.policy.route(self.db, 'Сургуулийн утас хэд вэ?', allow_draft=True)
        self.assertEqual(result['answer_kind'], 'development_draft_preview')

    def test_normal_search_selects_official_unknown_date_faq_without_answer(self):
        self.import_data()
        before = self.db.read_bytes()
        baseline = search_content(self.db, 'утас')
        result = self.policy.search(self.db, 'утас')
        self.assertEqual(result['mode'], 'official_website')
        self.assertFalse(result['answer_served'])
        self.assertTrue(result['preview_requires_selection'])
        for key in ('answer', 'answer_faq_id', 'exact_match_preview'):
            self.assertNotIn(key, result)
        candidate = result['candidates'][0]
        self.assertTrue(candidate['eligible'])
        self.assertFalse(candidate['answer_eligible'])
        self.assertTrue(candidate['source_accepted_for_project'])
        self.assertFalse(candidate['school_staff_approval_claimed'])
        self.assertTrue(candidate['unknown_validity_records'])
        self.assertEqual(candidate['score'], baseline['candidates'][0]['score'])
        self.assertEqual(candidate['exact_match'], baseline['candidates'][0]['exact_match'])
        self.assertEqual(candidate['citations'][0]['approval_status'], 'draft')
        self.assertEqual(candidate['citations'][0]['retrieved_at'], '2026-10-10')
        with ReadOnlyContentStore(self.db) as store:
            selected = self.policy.preview(store, candidate['faq_id'])
        self.assertEqual(selected['answer'], '75777799')
        self.assertFalse(selected['query_answer_support_established'])
        self.assertEqual(before, self.db.read_bytes())

    def test_exact_search_still_requires_selection_and_contains_no_answer(self):
        self.import_data()
        result = self.policy.search(self.db, 'Сургуулийн утас хэд вэ?')
        self.assertEqual(result['exact_matches'], ['faq.contact'])
        self.assertEqual(result['status'], 'ranked_candidates_only')
        self.assertTrue(result['candidates'][0]['exact_match'])
        self.assertTrue(result['candidates'][0]['eligible'])
        self.assertFalse(result['candidates'][0]['answer_eligible'])
        self.assertNotIn('75777799', json.dumps(result))

    def test_rejected_source_cannot_be_selected_from_normal_search(self):
        self.data['sources'][0]['approval_status'] = 'rejected'
        self.import_data()
        candidate = self.policy.search(self.db, 'утас')['candidates'][0]
        self.assertFalse(candidate['eligible'])
        self.assertFalse(candidate['source_accepted_for_project'])
        self.assertTrue(candidate['blocked_reasons'])

    def test_external_source_cannot_be_selected_even_if_approved(self):
        self.data['sources'][0]['source_url_or_filename'] = 'https://example.org/contact'
        for item in [*self.data['sources'], *self.data['facts'], *self.data['faqs']]:
            item.update(approval_status='approved', approved_by='test-only reviewer',
                        approved_at='2026-10-10T00:00:00Z',
                        valid_from='2020-01-01', valid_until='2099-01-01')
        self.import_data()
        self.assertTrue(search_content(self.db, 'утас')['candidates'][0]['eligible'])
        candidate = self.policy.search(self.db, 'утас')['candidates'][0]
        self.assertFalse(candidate['eligible'])
        self.assertFalse(candidate['source_accepted_for_project'])

    def test_search_preserves_expiry_future_start_partial_and_capture_guards(self):
        variants = [('expired', 'facts', 'valid_until', '2020-01-01'),
                    ('future', 'facts', 'valid_from', '2099-01-01'),
                    ('partial', 'faqs', 'answer_status', 'partial_in_scope'),
                    ('metadata', 'sources', 'content_capture', 'audit_metadata_only')]
        for name, group, field, value in variants:
            with self.subTest(name=name):
                data = deepcopy(self.data)
                data[group][0][field] = value
                db = self.root / (name + '.db')
                with ContentStore(db) as store:
                    store.import_content(data, allow_draft=True)
                before = db.read_bytes()
                result = self.policy.search(db, 'утас')
                self.assertFalse(result['candidates'][0]['eligible'])
                self.assertTrue(result['candidates'][0]['blocked_reasons'])
                self.assertEqual(before, db.read_bytes())

    def test_missing_policy_search_keeps_strict_metadata(self):
        self.import_data()
        baseline = search_content(self.db, 'утас')
        result = ContentUsePolicy(self.root / 'other').search(self.db, 'утас')
        self.assertEqual(result['mode'], 'approved_only')
        self.assertEqual(result['candidates'], baseline['candidates'])
        self.assertFalse(result['candidates'][0]['eligible'])
        self.assertNotIn('answer', result)

    def test_explicit_draft_search_keeps_development_availability(self):
        self.import_data()
        baseline = search_content(self.db, 'утас', allow_draft=True)
        result = self.policy.search(self.db, 'утас', allow_draft=True)
        self.assertEqual(result['mode'], 'development_draft')
        self.assertEqual(result['candidates'], baseline['candidates'])
        self.assertNotIn('source_accepted_for_project', result)
        self.assertNotIn('answer', result)


if __name__ == '__main__':
    unittest.main()
