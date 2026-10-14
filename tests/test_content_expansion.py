"""Integration checks for the versioned official-source content expansion."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from content_store import ContentStore, digest
from project_policy import ContentUsePolicy
from sqlite_retrieval import exact_key
from tools.validate_content_evidence import validate_evidence

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    return json.loads((ROOT / 'data' / name).read_text(encoding='utf-8-sig'))


class ContentExpansionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old = load('content-draft-v1.json')
        cls.content = load('content-draft-v2-20261015.json')
        cls.evidence = load('content-evidence-v2-20261015.json')

    def test_portable_provenance_is_valid_without_claiming_private_source_verification(self):
        result = validate_evidence(self.content, self.evidence)
        self.assertTrue(result['valid'], result['errors'])
        self.assertEqual(result['source_files_verified'], [])
        self.assertTrue(result['source_files_unavailable'])
        self.assertFalse(result['human_gold'])
        self.assertFalse(result['school_staff_approval_claimed'])

    def test_original_records_survive_new_package_and_import_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            with ContentStore(Path(temp) / 'content.db') as store:
                old = store.import_content(self.old, allow_draft=True)
                before = store.export(old['package_id'])
                new = store.import_content(self.content, allow_draft=True)
                repeat = store.import_content(copy.deepcopy(self.content), allow_draft=True)
                self.assertNotEqual(old['package_id'], new['package_id'])
                self.assertTrue(new['imported'])
                self.assertFalse(repeat['imported'])
                self.assertEqual(before, store.export(old['package_id']))
                self.assertEqual(store.counts(new['package_id'])['faqs'], 30)
                self.assertEqual(store.connection.execute('SELECT count(*) FROM packages').fetchone()[0], 2)
                self.assertEqual(store.connection.execute('SELECT count(*) FROM source_versions').fetchone()[0], 14)
                self.assertEqual(list(store.connection.execute('PRAGMA foreign_key_check')), [])

    def test_changed_old_record_is_detected_even_when_new_digest_is_recomputed(self):
        altered = copy.deepcopy(self.content)
        evidence = copy.deepcopy(self.evidence)
        altered['facts'][0]['value'] = 'not the original phone'
        evidence['package_id'] = digest(altered)
        result = validate_evidence(altered, evidence, root=ROOT)
        self.assertFalse(result['valid'])
        self.assertTrue(any('Inherited facts record changed' in e for e in result['errors']))

    def test_tampered_clause_is_detected_even_when_package_digest_is_recomputed(self):
        altered = copy.deepcopy(self.content)
        evidence = copy.deepcopy(self.evidence)
        fact = next(f for f in altered['facts'] if f['fact_id'] == 'admission.registration_fee.2026')
        fact['value']['published_clause'] = 'Бүртгэлийн хураамж: 99,000 ₮'
        evidence['package_id'] = digest(altered)
        result = validate_evidence(altered, evidence)
        self.assertFalse(result['valid'])
        self.assertTrue(any('Fact clause differs from proof' in e for e in result['errors']))

    def test_changed_quote_offset_or_quote_hash_is_detected(self):
        for field, value in [('start', -1), ('quote_sha256', '0' * 64)]:
            with self.subTest(field=field):
                altered = copy.deepcopy(self.evidence)
                altered['fact_proofs'][0]['quotes'][0][field] = value
                result = validate_evidence(self.content, altered)
                self.assertFalse(result['valid'])

    def test_aliases_are_unique_and_admission_aliases_preserve_explicit_year_scope(self):
        seen = {}
        for faq in self.content['faqs']:
            for question in [faq['question'], *faq['question_aliases']]:
                key = exact_key(question)
                self.assertNotIn(key, seen, (question, seen.get(key), faq['faq_id']))
                seen[key] = faq['faq_id']
                if faq['faq_id'].startswith(('faq.admission.', 'faq.olympiad.')):
                    self.assertIn('2026', question)

    def test_every_new_exact_question_and_alias_uses_official_policy_without_staff_approval(self):
        policy = ContentUsePolicy(ROOT)
        new_ids = set(self.evidence['new_faq_ids'])
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / 'content.db'
            with ContentStore(db) as store:
                store.import_content(self.content, allow_draft=True)
            for faq in self.content['faqs']:
                if faq['faq_id'] not in new_ids:
                    continue
                for question in [faq['question'], *faq['question_aliases']]:
                    with self.subTest(question=question):
                        result = policy.route(db, question)
                        self.assertEqual(result['route'], 'B')
                        self.assertEqual(result['answer_faq_id'], faq['faq_id'])
                        self.assertEqual(result['answer'], faq['answer'])
                        self.assertTrue(result['source_accepted_for_project'])
                        self.assertFalse(result['school_staff_approval_claimed'])
                        self.assertTrue(all(c['school_staff_approval'] is False for c in result['citations']))

    def test_unsupported_year_number_office_and_partial_qualifiers_do_not_serve_stored_answers(self):
        questions = [
            '2027 оны жилийн сургалтын төлбөр хэд вэ?',
            '2027 оны элсэлтийн бүртгэлийн хураамж хэд вэ?',
            'Сургалтын албаны ажлын цаг хэд вэ?',
            'Бүртгэлийн хураамж хэд вэ?',
            '2026 оны элсэлтийн бүртгэлийн хураамж 99,000 төгрөг үү?',
            '2026 оны жилийн сургалтын төлбөр сард хэд вэ?',
            '2026 оны элсэлтийн цээж зургийн пиксел хэд вэ?',
        ]
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / 'content.db'
            with ContentStore(db) as store:
                store.import_content(self.content, allow_draft=True)
            policy = ContentUsePolicy(ROOT)
            for question in questions:
                with self.subTest(question=question):
                    result = policy.route(db, question)
                    self.assertIsNone(result['answer'])
                    self.assertIn(result['route'], ('D', 'E'))

    def test_missing_sources_are_explicit_when_strict_verification_is_requested(self):
        with tempfile.TemporaryDirectory() as temp:
            result = validate_evidence(self.content, self.evidence, root=temp, require_sources=True)
            self.assertFalse(result['valid'])
            self.assertTrue(any('Source file unavailable' in e for e in result['errors']))
            self.assertFalse(result['source_files_verified'])

    def test_new_records_cannot_invent_validity_and_faq_locators_cannot_drift(self):
        for kind in ('facts', 'faqs'):
            altered = copy.deepcopy(self.content)
            evidence = copy.deepcopy(self.evidence)
            key = 'fact_id' if kind == 'facts' else 'faq_id'
            item = next(x for x in altered[kind] if x[key] in evidence['new_fact_ids' if kind == 'facts' else 'new_faq_ids'])
            item['valid_from'] = '2026-10-15'
            evidence['package_id'] = digest(altered)
            result = validate_evidence(altered, evidence)
            self.assertFalse(result['valid'])
            self.assertTrue(any('invented approval or validity' in e for e in result['errors']))
        altered = copy.deepcopy(self.content)
        evidence = copy.deepcopy(self.evidence)
        faq = next(x for x in altered['faqs'] if x['faq_id'] in evidence['new_faq_ids'])
        faq['source_refs'][0]['locator'] = 'unrelated section'
        evidence['package_id'] = digest(altered)
        result = validate_evidence(altered, evidence)
        self.assertFalse(result['valid'])
        self.assertTrue(any('exact dependency locators differ' in e for e in result['errors']))

    def test_duplicate_new_id_and_escaping_source_path_are_rejected(self):
        evidence = copy.deepcopy(self.evidence)
        evidence['new_faq_ids'].append(evidence['new_faq_ids'][0])
        self.assertTrue(any('Duplicate new FAQ' in e for e in validate_evidence(self.content, evidence)['errors']))
        evidence = copy.deepcopy(self.evidence)
        evidence['source_proofs'][0]['input_file'] = '../outside-project.txt'
        result = validate_evidence(self.content, evidence, root=ROOT)
        self.assertFalse(result['valid'])
        self.assertTrue(any('escapes project root' in e for e in result['errors']))

    def test_source_timestamp_is_bound_to_frozen_manifest_when_available(self):
        if not (ROOT / self.evidence['source_manifest_file']).exists():
            self.skipTest('Private frozen source files are intentionally absent in a public clone.')
        altered = copy.deepcopy(self.content)
        evidence = copy.deepcopy(self.evidence)
        proof = evidence['source_proofs'][0]
        proof['retrieved_at'] = '2026-10-15T00:00:00+00:00'
        source = next(s for s in altered['sources'] if (s['document_id'],s['version']) == (proof['document_id'],proof['version']))
        source['retrieved_at'] = proof['retrieved_at']
        evidence['package_id'] = digest(altered)
        result = validate_evidence(altered, evidence, root=ROOT, require_sources=True)
        self.assertFalse(result['valid'])
        self.assertTrue(any('differs from captured manifest' in e for e in result['errors']))


if __name__ == '__main__':
    unittest.main()
