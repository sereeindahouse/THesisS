"""Read-only query contracts use invented fixtures, not school approval/gold."""
import copy
import hashlib
import io
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date
from pathlib import Path
from unittest.mock import patch

from content_store import ContentStore
from sqlite_retrieval import ReadOnlyContentStore, exact_key, guarded_preview, main, search_content


def fixture(state='draft', version=1):
    meta = dict(approval_status=state,
        approved_by='invented test reviewer' if state == 'approved' else None,
        approved_at='2026-10-10T00:00:00Z' if state == 'approved' else None,
        valid_from='2026-10-01', valid_until='2026-10-31')
    ref = dict(document_id='test.source', version=version, locator='test only')
    return dict(schema_version=1,
        sources=[dict(document_id='test.source', version=version, title='Invented test source',
            source_url_or_filename='test-only.txt', retrieved_at='2026-10-10',
            source_updated_at=None, scope='invented test', content_capture='selected_fact_extract',
            notes='', **meta)],
        facts=[dict(fact_id='test.phone', entity_id='test', key='phone', value='12345678',
            source_refs=[copy.deepcopy(ref)], scope='invented test phone', notes='', **meta)],
        faqs=[dict(faq_id='test.contact', question='Тестийн холбоо барих утас хэд вэ?',
            question_aliases=['Тестийн утас хэд вэ?'], answer='Зөвхөн тестийн утас 12345678.',
            fact_ids=['test.phone'], source_refs=[copy.deepcopy(ref)], scope='invented test phone',
            answer_status='complete_in_scope', notes='', **meta)])


class SQLiteRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'content.db'
        self.today = date(2026, 10, 10)

    def tearDown(self):
        self.temp.cleanup()

    def import_fixture(self, content):
        with ContentStore(self.path) as store:
            return store.import_content(content, allow_draft=True)['package_id']

    def search(self, query='Тестийн утас хэд вэ?', **kwargs):
        return search_content(self.path, query, as_of=self.today, **kwargs)

    def test_draft_blocked_by_default_and_explicit_exact_preview_labeled(self):
        self.import_fixture(fixture())
        blocked = self.search()
        self.assertIsNone(blocked['answer'])
        self.assertEqual(blocked['status'], 'blocked_exact_match')
        self.assertFalse(blocked['candidates'][0]['eligible'])
        self.assertNotIn('answer', blocked['candidates'][0])
        preview = self.search(allow_draft=True)
        self.assertEqual(preview['answer'], 'Зөвхөн тестийн утас 12345678.')
        self.assertEqual(preview['status'], 'development_exact_preview')
        self.assertEqual(preview['mode'], 'development_draft')
        self.assertEqual(preview['exact_match_preview']['citations'][0]['version'], 1)
        self.assertFalse(preview['automatic_approval'])

    def test_fuzzy_ranking_never_answers_even_approved_or_dense_high_score(self):
        self.import_fixture(fixture('approved'))
        fuzzy = self.search('Тестийн утсыг хэлээч', allow_draft=True)
        self.assertEqual(fuzzy['candidates'][0]['faq_id'], 'test.contact')
        self.assertEqual(fuzzy['status'], 'ranked_candidates_only')
        self.assertIsNone(fuzzy['answer'])
        self.assertFalse(fuzzy['candidates'][0]['answer_eligible'])
        with patch('sqlite_retrieval.dense_scores', return_value=([[0.999]], {'local_files_only': True})):
            dense = self.search('2027 оны төлбөр?', backend='e5', allow_draft=True)
        self.assertEqual(dense['candidates'][0]['score'], .999)
        self.assertIsNone(dense['answer'])
        self.assertFalse(dense['score_is_probability'])

    def test_latest_and_pinned_package_have_correct_approval_and_version(self):
        old = self.import_fixture(fixture())
        new = self.import_fixture(fixture('approved', version=2))
        self.assertEqual(self.search()['package_id'], new)
        self.assertEqual(self.search()['status'], 'approved_exact_answer')
        self.assertEqual(self.search()['exact_match_preview']['citations'][0]['version'], 2)
        pinned = self.search(package_id=old)
        self.assertIsNone(pinned['answer'])
        self.assertEqual(pinned['package_id'], old)
        self.assertEqual(pinned['candidates'][0]['citations'][0]['version'], 1)
        self.import_fixture(fixture())
        self.assertEqual(self.search()['package_id'], new)

    def test_known_expired_and_future_source_block_in_all_modes(self):
        for field, value in [('valid_until', '2026-10-09'), ('valid_from', '2026-10-11')]:
            with self.subTest(field=field):
                content = fixture('approved')
                content['sources'][0][field] = value
                package = self.import_fixture(content)
                for mode in (False, True):
                    result = self.search(package_id=package, allow_draft=mode)
                    self.assertIsNone(result['answer'])
                    self.assertFalse(result['candidates'][0]['eligible'])
                    self.assertTrue(result['candidates'][0]['blocked_reasons'])

    def test_unknown_validity_not_approved_answer_but_development_label_visible(self):
        content = fixture('approved')
        content['sources'][0]['valid_until'] = None
        self.import_fixture(content)
        guarded = self.search()
        self.assertTrue(guarded['candidates'][0]['eligible'])
        self.assertFalse(guarded['candidates'][0]['answer_eligible'])
        self.assertIsNone(guarded['answer'])
        self.assertIn('source:test.source@1', guarded['candidates'][0]['unknown_validity_records'])
        self.assertTrue(self.search(allow_draft=True)['exact_match_preview']['unknown_validity_records'])

    def test_partial_answer_never_returns_complete_answer(self):
        content = fixture('approved')
        content['faqs'][0]['answer_status'] = 'partial_in_scope'
        self.import_fixture(content)
        for mode in (False, True):
            result = self.search(allow_draft=mode)
            self.assertIsNone(result['answer'])
            self.assertFalse(result['exact_match_preview']['answer_eligible'])

    def test_ambiguous_alias_does_not_pick_an_arbitrary_answer(self):
        content = fixture('approved')
        other = copy.deepcopy(content['faqs'][0])
        other.update(faq_id='test.other', question='Өөр тестийн асуулт?', answer='Өөр тестийн хариулт.')
        content['faqs'].append(other)
        self.import_fixture(content)
        result = self.search(allow_draft=True)
        self.assertEqual(result['status'], 'ambiguous_exact_match')
        self.assertEqual(len(result['exact_matches']), 2)
        self.assertIsNone(result['answer'])

    def test_no_lexical_overlap_empty_corpus_and_empty_query_do_not_fabricate(self):
        package = self.import_fixture(fixture())
        result = self.search('гадаад паспорт авах', package_id=package, allow_draft=True)
        self.assertEqual(result['candidates'], [])
        self.assertEqual(result['status'], 'no_lexical_match')
        self.assertIsNone(result['answer'])
        empty = fixture()
        empty['faqs'] = []
        self.import_fixture(empty)
        self.assertEqual(self.search()['status'], 'no_candidates')
        for query in ('', '   ', '???', 123):
            with self.assertRaises(ValueError):
                self.search(query)

    def test_normalization_retains_years_names_and_interior_punctuation(self):
        self.assertEqual(exact_key(' ТЕСТИЙН   утас хэд вэ! '), exact_key('Тестийн утас хэд вэ?'))
        self.assertNotEqual(exact_key('2026 оны элсэлт?'), exact_key('2027 оны элсэлт?'))
        self.assertNotEqual(exact_key('2026-2027'), exact_key('2026 2027'))
        self.assertNotEqual(exact_key('Sakura хамтын ажиллагаа?'), exact_key('ARC хамтын ажиллагаа?'))

    def test_searches_are_read_only_repeatable_and_snapshot_is_fixed(self):
        self.import_fixture(fixture())
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        first = self.search(allow_draft=True)
        self.assertEqual(first, self.search(allow_draft=True))
        self.assertEqual(before, hashlib.sha256(self.path.read_bytes()).hexdigest())
        with ReadOnlyContentStore(self.path) as reader:
            original = reader.package_id()
            with self.assertRaises(sqlite3.OperationalError):
                reader.connection.execute('DELETE FROM packages')
        with closing(sqlite3.connect(self.path)) as writer:
            writer.execute('PRAGMA journal_mode=WAL')
        with ReadOnlyContentStore(self.path) as reader:
            original = reader.package_id()
            self.import_fixture(fixture('approved', version=2))
            self.assertEqual(reader.package_id(), original)
        self.assertNotEqual(self.search()['package_id'], original)

    def test_missing_or_wrong_database_never_creates_files_or_schema(self):
        missing = Path(self.temp.name) / 'missing' / 'new.db'
        with self.assertRaises(FileNotFoundError):
            search_content(missing, 'Тестийн утас?')
        self.assertFalse(missing.parent.exists())
        wrong = Path(self.temp.name) / 'other.db'
        with closing(sqlite3.connect(wrong)) as db:
            db.execute('CREATE TABLE example(value)')
            db.commit()
        before = hashlib.sha256(wrong.read_bytes()).hexdigest()
        with self.assertRaises(ValueError):
            search_content(wrong, 'Тестийн утас?')
        self.assertEqual(before, hashlib.sha256(wrong.read_bytes()).hexdigest())

    def test_bad_options_and_missing_package_rejected(self):
        self.import_fixture(fixture())
        for kwargs in ({'backend': 'untrusted'}, {'top_k': 0}, {'top_k': True},
                       {'allow_draft': 1}, {'as_of': '2026-10-10'}):
            with self.subTest(kwargs=kwargs), self.assertRaises((ValueError, TypeError)):
                search_content(self.path, 'Тестийн утас?', **kwargs)
        with self.assertRaises(KeyError):
            self.search(package_id='missing')

    def test_cli_output_guard_runs_before_database_or_dense_loading(self):
        root = Path(self.temp.name)
        results = root / 'results'
        results.mkdir()
        existing = results / 'already.json'
        existing.write_text('preserve evidence', encoding='utf-8')
        targets = [existing, root / 'outside.json', results / 'missing' / 'new.json']
        for target in targets:
            with self.subTest(target=target), patch('sqlite_retrieval.ROOT', root), \
                    patch('sys.argv', ['sqlite_retrieval.py', 'Тест үү?', '--backend', 'e5',
                                       '--output', str(target)]), \
                    patch('sys.stderr', new=io.StringIO()), \
                    patch('sqlite_retrieval.search_content') as search:
                with self.assertRaises(SystemExit) as stopped:
                    main()
                self.assertEqual(stopped.exception.code, 2)
                search.assert_not_called()
        self.assertEqual(existing.read_text(encoding='utf-8'), 'preserve evidence')
        self.assertFalse((results / 'missing').exists())

    def test_manual_view_masks_partial_unknown_approved_but_labels_development(self):
        content = fixture('approved')
        content['sources'][0]['valid_until'] = None
        content['faqs'][0]['answer_status'] = 'partial_in_scope'
        self.import_fixture(content)
        with ReadOnlyContentStore(self.path) as store:
            approved = guarded_preview(store, 'test.contact', as_of=self.today)
            self.assertIsNone(approved['answer'])
            self.assertFalse(approved['answer_eligible'])
            self.assertEqual(len(approved['answer_blocked_reasons']), 2)
            draft = guarded_preview(store, 'test.contact', allow_draft=True, as_of=self.today)
            self.assertIsNotNone(draft['answer'])
            self.assertEqual(draft['preview_kind'], 'development_document_view')
            self.assertEqual(draft['answer_status'], 'partial_in_scope')
            self.assertTrue(draft['unknown_validity_records'])
            self.assertFalse(draft['query_answer_support_established'])


if __name__ == '__main__':
    unittest.main()
