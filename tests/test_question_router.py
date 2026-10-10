"""Routing contracts use invented fixtures, never school approval or gold."""
import copy
import hashlib
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date, datetime
from pathlib import Path

from content_store import ContentStore
from question_router import route_question


def fixture(state='draft'):
    meta = dict(approval_status=state,
        approved_by='invented fixture reviewer' if state == 'approved' else None,
        approved_at='2026-10-10T00:00:00Z' if state == 'approved' else None,
        valid_from='2026-10-01', valid_until='2026-10-31')
    ref = dict(document_id='fixture.source', version=1, locator='invented only')
    definitions = [
        ('faq.contact', 'phone', 'Холбоо барих утас хэд вэ?',
         ['Тестийн утас хэд вэ?'], '12345678', 'Тестийн утас 12345678.', 'Ерөнхий холбоо.'),
        ('faq.sakura', 'sakura', 'Sakura хамтын ажиллагааны талаар мэдээлэл өгнө үү.',
         [], '2024 оны сургалт', 'Sakura 2024 оны тест сургалтад оролцсон.', 'Түүхэн танилцуулга.'),
        ('faq.arc.courses', 'courses', 'ARC хамтын ажиллагаанд ямар хичээлүүд багтсан бэ?',
         ['2025–2026 оны ARC хамтын ажиллагаанд ямар хичээлүүд багтсан бэ?'],
         ['2025–2026 оны алгоритм', '2025–2026 оны тест сүлжээ'],
         '2025–2026 оны тест хичээлүүд нь алгоритм ба сүлжээ.', 'Зөвхөн 2025–2026 оны хичээл.')]
    result = dict(schema_version=1, sources=[dict(document_id='fixture.source', version=1,
        title='Invented source; not NMCT approval', source_url_or_filename='invented-only.txt',
        retrieved_at='2026-10-10', source_updated_at=None, scope='invented tests',
        content_capture='selected_fact_extract', notes='', **meta)], facts=[], faqs=[])
    for faq_id, key, question, aliases, value, answer, scope in definitions:
        fid = 'fixture.' + key
        result['facts'].append(dict(fact_id=fid, entity_id='fixture', key=key, value=value,
            source_refs=[copy.deepcopy(ref)], scope=scope, notes='', **meta))
        result['faqs'].append(dict(faq_id=faq_id, question=question, question_aliases=aliases,
            answer=answer, fact_ids=[fid], source_refs=[copy.deepcopy(ref)], scope=scope,
            answer_status='complete_in_scope', notes='', **meta))
    return result


class QuestionRouterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'content.db'
        self.today = date(2026, 10, 10)

    def tearDown(self):
        self.temp.cleanup()

    def put(self, content):
        with ContentStore(self.path) as store:
            return store.import_content(content, allow_draft=True)['package_id']

    def route(self, query='Холбоо барих утас хэд вэ?', **kwargs):
        result = route_question(self.path, query, as_of=self.today, **kwargs)
        self.assertFalse(result['generated'])
        self.assertFalse(result['human_gold'])
        self.assertFalse(result['automatic_approval'])
        self.assertFalse(result['training_performed'])
        self.assertFalse(result['database_modified'])
        self.assertFalse(result['score_is_probability'])
        self.assertFalse(result['c_enabled'])
        self.assertEqual(result['llm_calls'], 0)
        self.assertNotEqual(result['route'], 'C')
        self.assertGreaterEqual(result['latency_ms'], 0)
        self.assertEqual(result['reason_code'], result['reason_codes'][0])
        self.assertTrue(all('answer' not in candidate for candidate in result['candidates']))
        return result

    def test_default_draft_blocks_exact_with_approval_required(self):
        self.put(fixture())
        result = self.route()
        self.assertEqual(result['route'], 'E')
        self.assertEqual(result['reason_code'], 'approval_required')
        self.assertEqual(result['intended_answer_route'], 'A')
        self.assertIsNone(result['answer'])

    def test_explicit_draft_fact_response_keeps_source_and_development_label(self):
        self.put(fixture())
        result = self.route('ТЕСТИЙН  утас хэд вэ?!', allow_draft=True)
        self.assertEqual(result['route'], 'A')
        self.assertEqual(result['answer'], 'Тестийн утас 12345678.')
        self.assertEqual(result['answer_kind'], 'development_draft_preview')
        self.assertEqual(result['citations'][0]['approval_status'], 'draft')
        self.assertEqual(result['citations'][0]['version'], 1)
        self.assertEqual(result['fact_ids'], ['fixture.phone'])

    def test_approved_fact_and_faq_answers_require_exact_and_known_validity(self):
        self.put(fixture('approved'))
        fact = self.route()
        faq = self.route('Sakura хамтын ажиллагааны талаар мэдээлэл өгнө үү.')
        self.assertEqual(fact['route'], 'A')
        self.assertEqual(faq['route'], 'B')
        self.assertEqual(faq['answer_kind'], 'approved_stored_answer')
        self.assertIsNotNone(faq['answer'])

    def test_unknown_validity_blocks_approved_but_explicit_preview_remains_draft(self):
        content = fixture('approved')
        content['sources'][0]['valid_until'] = None
        self.put(content)
        default = self.route()
        self.assertEqual(default['route'], 'E')
        self.assertIn('unknown_validity', default['reason_codes'])
        preview = self.route(allow_draft=True)
        self.assertEqual(preview['route'], 'A')
        self.assertEqual(preview['answer_kind'], 'development_draft_preview')
        self.assertTrue(preview['unknown_validity_records'])

    def test_expired_and_future_dependency_never_answer_in_either_mode(self):
        for field, value, code in [('valid_until', '2026-10-09', 'expired_content'),
                                   ('valid_from', '2026-10-11', 'future_validity')]:
            content = fixture('approved')
            content['facts'][0][field] = value
            package = self.put(content)
            for mode in (False, True):
                with self.subTest(field=field, mode=mode):
                    result = self.route(allow_draft=mode, package_id=package)
                    self.assertEqual(result['route'], 'E')
                    self.assertIn(code, result['reason_codes'])
                    self.assertIsNone(result['answer'])

    def test_partial_answer_never_becomes_automatic_draft_answer(self):
        content = fixture('approved')
        content['faqs'][0]['answer_status'] = 'partial_in_scope'
        self.put(content)
        for mode in (False, True):
            result = self.route(allow_draft=mode)
            self.assertEqual(result['route'], 'E')
            self.assertIn('partial_answer', result['reason_codes'])
            self.assertIsNone(result['answer'])

    def test_source_or_fact_rejected_blocks_explicit_draft_preview(self):
        for group in ('sources', 'facts'):
            content = fixture()
            content[group][0].update(approval_status='rejected')
            package = self.put(content)
            result = self.route(package_id=package, allow_draft=True)
            self.assertEqual(result['route'], 'E')
            self.assertIn('content_rejected_or_unapproved', result['reason_codes'])

    def test_known_rejected_content_is_blocked_even_explicit_preview(self):
        content = fixture()
        content['facts'][0].update(approval_status='rejected', approved_by=None, approved_at=None)
        self.put(content)
        result = self.route(allow_draft=True)
        self.assertEqual(result['route'], 'E')
        self.assertEqual(result['reason_code'], 'content_rejected_or_unapproved')

    def test_missing_year_only_for_the_actual_year_bound_courses_scope(self):
        self.put(fixture('approved'))
        result = self.route('ARC хамтын ажиллагаанд ямар хичээлүүд багтсан бэ?')
        self.assertEqual(result['route'], 'D')
        self.assertEqual(result['reason_code'], 'missing_year')
        self.assertEqual(result['clarification']['supported_years'], ['2025', '2026'])
        self.assertIsNone(result['answer'])
        self.assertEqual(self.route()['route'], 'A')

    def test_existing_dated_alias_can_answer_but_unsupported_year_never_replaces(self):
        self.put(fixture('approved'))
        supported = self.route('2025–2026 оны ARC хамтын ажиллагаанд ямар хичээлүүд багтсан бэ?')
        self.assertEqual(supported['route'], 'A')
        wrong = self.route('2027 онд ARC хамтын ажиллагаанд ямар хичээлүүд багтах вэ?', allow_draft=True)
        self.assertEqual(wrong['route'], 'E')
        self.assertEqual(wrong['reason_code'], 'unsupported_year')
        self.assertIsNone(wrong['answer'])
        self.assertEqual(wrong['requested_years'], ['2027'])

    def test_fuzzy_candidates_are_clarification_even_approved_without_threshold(self):
        self.put(fixture('approved'))
        result = self.route('Холбоо барих утсыг хэлээч', allow_draft=True)
        self.assertEqual(result['route'], 'D')
        self.assertEqual(result['reason_code'], 'select_supported_question')
        self.assertEqual(result['clarification']['options'][0]['faq_id'], 'faq.contact')
        self.assertIsNone(result['answer'])

    def test_year_clarification_option_binds_validated_year_and_terminates_without_alias_mutation(self):
        content = fixture('approved')
        content['faqs'][2]['question_aliases'] = []
        package = self.put(content)
        before = self.path.read_bytes()
        result = self.route('ARC хамтын ажиллагаанд ямар хичээлүүд багтсан бэ?')
        chosen = result['clarification']['options'][0]['question']
        next_step = self.route(chosen)
        self.assertEqual(next_step['route'], 'A')
        self.assertEqual(next_step['query'], chosen)
        self.assertEqual(next_step['package_id'], package)
        self.assertEqual(next_step['match_kind'], 'explicit_year_literal_base')
        self.assertEqual(next_step['exact_matches'], [])
        self.assertEqual(next_step['binding_faq_id'], 'faq.arc.courses')
        self.assertEqual(before, self.path.read_bytes())
        unsupported = self.route('2027 оны ARC хамтын ажиллагаанд ямар хичээлүүд багтсан бэ?')
        self.assertEqual(unsupported['route'], 'E')
        self.assertEqual(unsupported['reason_code'], 'unsupported_year')

    def test_exact_year_guard_does_not_borrow_support_from_another_related_faq(self):
        content = fixture('approved')
        content['faqs'][0]['question_aliases'].append('2027 оны холбоо барих утас хэд вэ?')
        other = copy.deepcopy(content['faqs'][0])
        other.update(faq_id='fixture.future_phone', question='2027 оны шинэ холбоо барих утас?',
                     question_aliases=[], answer='2027 оны тестийн холбоо 12345678.', scope='2027 он.')
        content['faqs'].append(other)
        self.put(content)
        result = self.route('2027 оны холбоо барих утас хэд вэ?')
        self.assertEqual(result['route'], 'E')
        self.assertEqual(result['reason_code'], 'unsupported_year')
        self.assertIsNone(result['answer'])

    def test_approved_answer_kind_remains_approved_when_draft_toggle_is_enabled(self):
        self.put(fixture('approved'))
        result = self.route(allow_draft=True)
        self.assertEqual(result['mode'], 'development_draft')
        self.assertEqual(result['answer_kind'], 'approved_stored_answer')

    def test_explicit_entity_is_preserved_in_every_fuzzy_option(self):
        self.put(fixture('approved'))
        result = self.route('ARC хамтын ажиллагааны хичээлүүдийн мэдээлэл')
        self.assertEqual(result['route'], 'D')
        self.assertEqual(result['reason_code'], 'missing_year')
        self.assertEqual({x['faq_id'] for x in result['clarification']['options']}, {'faq.arc.courses'})

    def test_supported_numeric_constraint_never_disappears_in_clickable_shorter_question(self):
        self.put(fixture('approved'))
        result = self.route('Холбоо барих утас 12345678 мөн үү?')
        self.assertEqual(result['route'], 'D')
        self.assertEqual(result['reason_code'], 'constrained_wording_not_exact')
        self.assertEqual(result['clarification']['options'], [])
        self.assertIsNone(result['answer'])

    def test_exact_alias_does_not_override_its_own_fact_number_or_canonical_entity(self):
        content = fixture('approved')
        content['faqs'][0]['question_aliases'].append('Холбоо барих утас 12345679 мөн үү?')
        content['faqs'][1]['question_aliases'].append('ARC хамтын ажиллагааны талаар мэдээлэл өгнө үү.')
        self.put(content)
        for query, code in [('Холбоо барих утас 12345679 мөн үү?', 'unmatched_numeric_constraints'),
                            ('ARC хамтын ажиллагааны талаар мэдээлэл өгнө үү.', 'unmatched_named_entity')]:
            with self.subTest(query=query):
                result = self.route(query, allow_draft=True)
                self.assertEqual(result['route'], 'E')
                self.assertEqual(result['reason_code'], code)
                self.assertIsNone(result['answer'])

    def test_reversed_range_and_ambiguous_bound_base_never_drop_year_constraints(self):
        content = fixture('approved')
        content['faqs'][2]['question_aliases'] = []
        self.put(content)
        reversed_range = self.route('2026–2025 оны ARC хамтын ажиллагаанд ямар хичээлүүд багтсан бэ?')
        self.assertEqual(reversed_range['route'], 'E')
        self.assertEqual(reversed_range['reason_code'], 'invalid_year_range')
        other = copy.deepcopy(content['faqs'][2])
        other.update(faq_id='fixture.other_arc', question='Өөр ARC тест?',
            question_aliases=['ARC хамтын ажиллагаанд ямар хичээлүүд багтсан бэ?'])
        content['faqs'].append(other)
        self.put(content)
        ambiguous = self.route('2025–2026 оны ARC хамтын ажиллагаанд ямар хичээлүүд багтсан бэ?')
        self.assertEqual(ambiguous['route'], 'D')
        self.assertEqual(ambiguous['reason_code'], 'ambiguous_constrained_exact_match')
        self.assertEqual(ambiguous['clarification']['options'], [])
        self.assertIsNone(ambiguous['answer'])

    def test_known_general_contact_alias_cannot_assert_office_and_ambiguous_entity_never_disappears(self):
        content = fixture('approved')
        content['faqs'][0]['question_aliases'].append('Сургалтын албаны утас хэд вэ?')
        arc_question = content['faqs'][2]['question']
        content['faqs'][1]['question_aliases'].append(arc_question)
        self.put(content)
        office = self.route('Сургалтын албаны утас хэд вэ?', allow_draft=True)
        self.assertEqual(office['route'], 'E')
        self.assertEqual(office['reason_code'], 'specific_scope_not_supported')
        self.assertIsNone(office['answer'])
        ambiguity = self.route(arc_question, allow_draft=True)
        self.assertEqual(ambiguity['route'], 'D')
        self.assertEqual(ambiguity['reason_code'], 'ambiguous_constrained_exact_match')
        self.assertEqual(ambiguity['clarification']['options'], [])
        self.assertIsNone(ambiguity['answer'])

    def test_official_program_wording_does_not_count_as_office_specific_support(self):
        content = fixture('approved')
        other = copy.deepcopy(content['faqs'][1])
        other.update(faq_id='faq.cs.program',
            question='Сургалтын хөтөлбөр болон албан ёсны мэдээллийн эх сурвалжийг хэлж өгнө үү.',
            question_aliases=[], answer='Тестийн хөтөлбөрийн ерөнхий тайлбар.', scope='Ерөнхий хөтөлбөр.')
        content['faqs'].append(other)
        self.put(content)
        result = self.route('Сургалтын албаны утас хэд вэ?', allow_draft=True)
        self.assertEqual(result['route'], 'E')
        self.assertEqual(result['reason_code'], 'specific_scope_not_supported')
        self.assertIsNone(result['answer'])

    def test_ambiguous_exact_alias_does_not_pick_arbitrary_fact_or_faq(self):
        content = fixture('approved')
        content['faqs'][1]['question_aliases'].append('Тестийн утас хэд вэ?')
        self.put(content)
        result = self.route('Тестийн утас хэд вэ?')
        self.assertEqual(result['route'], 'D')
        self.assertEqual(result['reason_code'], 'ambiguous_exact_match')
        self.assertEqual(len(result['clarification']['options']), 2)
        self.assertIsNone(result['answer'])

    def test_missing_entity_clarification_is_justified_by_two_stored_cooperations(self):
        self.put(fixture('approved'))
        result = self.route('Хамтын ажиллагааны мэдээлэл өгөөч', allow_draft=True)
        self.assertEqual(result['route'], 'D')
        self.assertEqual(result['reason_code'], 'missing_entity')
        self.assertEqual({x['faq_id'] for x in result['clarification']['options']},
                         {'faq.sakura', 'faq.arc.courses'})
        self.assertIsNone(result['answer'])

    def test_wrong_entity_wrong_phone_specific_office_and_live_status_never_answer(self):
        self.put(fixture('approved'))
        checks = [
            ('Google хамтын ажиллагааны мэдээлэл өгөөч', 'unmatched_named_entity'),
            ('Холбоо барих утас 12345679 мөн үү?', 'unmatched_numeric_constraints'),
            ('Сургалтын албаны холбоо барих утас хэд вэ?', 'specific_scope_not_supported'),
            ('Sakura хамтын ажиллагааны бүртгэл нээлттэй юу?', 'live_status_not_supported'),
            ('Холбоо барих утас хэд вэ, бас 2027 оны төлбөр?', 'unsupported_year')]
        for query, code in checks:
            with self.subTest(query=query):
                result = self.route(query, allow_draft=True)
                self.assertEqual(result['route'], 'E')
                self.assertEqual(result['reason_code'], code)
                self.assertIsNone(result['answer'])

    def test_generic_particles_do_not_make_unrelated_question_relevant(self):
        self.put(fixture('approved'))
        for query in ('Гадаад паспортын төлбөр хэд вэ?', 'Маргааш миний багш хэдэн цагт ирэх вэ?'):
            result = self.route(query, allow_draft=True)
            self.assertEqual(result['route'], 'E')
            self.assertEqual(result['reason_code'], 'no_supported_question_match')
            self.assertFalse(result['candidates'])
            self.assertIsNone(result['clarification'])

    def test_db_is_unchanged_all_routes_and_pinned_old_package_remains_old(self):
        old = self.put(fixture())
        new = self.put(fixture('approved'))
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.assertEqual(self.route()['package_id'], new)
        self.assertEqual(self.route(package_id=old)['reason_code'], 'approval_required')
        self.route('ARC хамтын ажиллагаанд ямар хичээлүүд багтсан бэ?')
        self.route('Гадаад паспорт', allow_draft=True)
        self.assertEqual(before, hashlib.sha256(self.path.read_bytes()).hexdigest())

    def test_missing_and_unrelated_database_are_not_created_or_changed(self):
        with self.assertRaises(FileNotFoundError):
            self.route()
        self.assertFalse(self.path.exists())
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute('CREATE TABLE unrelated(value TEXT)')
            connection.commit()
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            self.route()
        self.assertEqual(before, self.path.read_bytes())

    def test_invalid_query_options_do_not_bypass_input_contract(self):
        self.put(fixture())
        for query in ('', ' ', '?' * 5, 'а' * 4001):
            with self.assertRaises(ValueError):
                self.route(query)
        with self.assertRaises(ValueError):
            self.route(allow_draft='yes')
        with self.assertRaises(ValueError):
            route_question(self.path, 'Утас?', as_of=datetime(2026, 10, 10))


if __name__ == '__main__':
    unittest.main()
