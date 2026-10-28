"""Constructed history fixtures; numbers and dates are not school results."""
import json
from pathlib import Path
import unittest

from historical_fields import event_requirements, event_supported
from rag_runtime import GroundedGenerator
from source_fields import field_evidence_requirements, missing_field_evidence


class GraduationRoleTests(unittest.TestCase):
    query = ('Барилгын инженерчлэлийн анхны төгсөлт хэдэн онд болсон, нийт хэдэн '
             'удаагийн төгсөлтөөр хэдэн оюутан мэргэжил эзэмшсэн гэж эхэд бичсэн бэ?')
    source = ('Барилгын инженерчлэлийн хөтөлбөрөөр 2037 онд анхны оюутнууд төгссөн '
              'бөгөөд өнөөгийн байдлаар нийт 9 удаагийн төгсөлтөөр 142 оюутан '
              'мэргэжил эзэмшээд байна. Жил бүр 170–180 оюутан суралцдаг.')

    def test_first_year_and_cumulative_counts_are_three_distinct_fields(self):
        fields = event_requirements(self.query)
        self.assertEqual([r['name'] for r in fields], [
            'first_graduation_year', 'cumulative_graduation_cohorts', 'cumulative_graduation_count'])
        for field in fields:
            self.assertTrue(event_supported(field, self.source), field['name'])

    def test_values_are_source_derived_with_different_years_and_counts(self):
        fields = field_evidence_requirements(self.query)
        for year, cohorts, graduates in [(2046, 4, 63), (2052, 12, 219)]:
            text = self.source.replace('2037', str(year)).replace('9 удаагийн', f'{cohorts} удаагийн').replace('142 оюутан', f'{graduates} оюутан')
            self.assertEqual(missing_field_evidence(fields, [text]), [])

    def test_elliptical_total_cohort_wording_does_not_invent_first_cohort_size(self):
        query = ('Барилгын инженерчлэлээр анх хэзээ төгсгөсөн бэ? '
                 'Эхэд нийт хэдэн удаа, хэдэн оюутан төгссөн гэж бичсэн байна?')
        fields = event_requirements(query)
        self.assertEqual([field['name'] for field in fields], [
            'first_graduation_year', 'cumulative_graduation_cohorts', 'cumulative_graduation_count'])
        self.assertEqual(missing_field_evidence(fields, [self.source]), [])
        self.assertNotIn('first_graduation_count', [field['name'] for field in fields])

    def test_elliptical_total_needs_local_graduation_predicate(self):
        query = ('Анхны төгсөлт хэзээ болсон бэ? '
                 'Нийт хэдэн удаа, хэдэн оюутан лабораторид ажилласан бэ?')
        fields = event_requirements(query)
        self.assertNotIn('cumulative_graduation_cohorts', [field['name'] for field in fields])

    def test_elliptical_cohort_query_preserves_source_role_guards(self):
        fields = event_requirements('Нийт хэдэн удаа, хэдэн оюутан төгссөн бэ?')
        self.assertEqual([field['name'] for field in fields], [
            'cumulative_graduation_cohorts', 'cumulative_graduation_count'])
        for field in fields:
            self.assertFalse(event_supported(field, 'Жил бүр 90 оюутан суралцдаг.'))
            self.assertFalse(event_supported(field, 'Нийт 4 удаагийн төгсөлтөөр 90 оюутан төгсөөгүй.'))

    def test_since_first_year_does_not_request_first_cohort_size(self):
        query = 'Анх хэдэн онд төгссөн, түүнээс хойш нийт хэдэн оюутан мэргэжил эзэмшсэн бэ?'
        fields = event_requirements(query)
        self.assertEqual([r['name'] for r in fields], ['first_graduation_year', 'cumulative_graduation_count'])
        for field in fields:
            self.assertTrue(event_supported(field, self.source))

    def test_reordered_clauses_preserve_first_year_and_cumulative_fields(self):
        query = ('Нийт хэдэн удаагийн төгсөлтөөр хэдэн оюутан мэргэжил эзэмшсэн бэ? '
                 'Анхны төгсөлт хэдэн онд болсон бэ?')
        self.assertEqual({r['name'] for r in event_requirements(query)}, {
            'first_graduation_year', 'cumulative_graduation_cohorts', 'cumulative_graduation_count'})

    def test_later_first_cohort_question_does_not_invent_cumulative_student_count(self):
        query = 'Нийт хэдэн удаагийн төгсөлт болсон бэ? Анхны төгсөгчдийн тоо хэд вэ?'
        self.assertEqual({r['name'] for r in event_requirements(query)}, {
            'first_graduation_count', 'cumulative_graduation_cohorts'})

    def test_true_first_cohort_request_still_needs_its_own_count(self):
        fields = event_requirements('Анхны төгсөгчид хэдэн онд хэдүүлээ төгссөн бэ?')
        self.assertEqual([r['name'] for r in fields], ['first_graduation_year', 'first_graduation_count'])
        for field in fields:
            self.assertTrue(event_supported(field, '2044\nАнхны 23 төгсөгч дипломоо гардан авав.'))
        count = fields[1]
        self.assertFalse(event_supported(count, self.source))

    def test_cumulative_values_do_not_supply_unknown_first_cohort_size(self):
        field = event_requirements('Анхны төгсөгчдийн тоо хэд вэ?')[0]
        self.assertFalse(event_supported(field,
            '2044 онд анхны оюутнууд төгссөн бөгөөд нийт 8 удаагийн төгсөлтөөр 106 оюутан мэргэжил эзэмшжээ.'))

    def test_first_cohort_and_other_event_numbers_do_not_supply_cumulative_fields(self):
        cumulative = event_requirements(self.query)[1:]
        for text in ['2044 онд анхны 23 төгсөгч дипломоо гардан авав.',
                     'Нийт 9 багш 142 оюутантай ажилладаг. Анхны оюутнууд төгссөн.',
                     'Нийт 9 удаагийн уулзалтаар 142 оюутан оролцсон. Анхны оюутнууд төгссөн.',
                     'Нийт 9 удаагийн төгсөлт. Жил бүр 142 оюутан суралцдаг.']:
            for field in cumulative:
                self.assertFalse(event_supported(field, text), (field['name'], text))

    def test_missing_one_cumulative_facet_remains_missing(self):
        fields = event_requirements(self.query)
        no_count = self.source.replace('142 оюутан', 'оюутнууд')
        self.assertTrue(event_supported(fields[1], no_count))
        self.assertFalse(event_supported(fields[2], no_count))
        no_cohorts = 'Нийт 142 оюутан мэргэжил эзэмшээд байна.'
        self.assertFalse(event_supported(fields[1], no_cohorts))
        self.assertTrue(event_supported(fields[2], no_cohorts))

    def test_negated_conditional_and_unconfirmed_cumulative_events_are_rejected(self):
        fields = event_requirements(self.query)[1:]
        for text in [self.source.replace('эзэмшээд байна', 'эзэмшээгүй'),
                     'Хэрэв ' + self.source,
                     self.source.split('.')[0] + ' гэсэн мэдээлэл батлагдаагүй.',
                     self.source.split('.')[0] + ' гэх таамаг байна.']:
            for field in fields:
                self.assertFalse(event_supported(field, text), (field['name'], text))

    def test_another_event_year_does_not_date_first_graduation(self):
        field = event_requirements(self.query)[0]
        for text in ['2040 онд лаборатори нээгдэж, анхны оюутнууд төгссөн.',
                     '2040 онд багш нар шагнал авав. Анхны оюутнууд төгссөн.']:
            self.assertFalse(event_supported(field, text), text)

    def test_cumulative_count_cannot_be_borrowed_across_conjoined_events(self):
        fields = event_requirements(self.query)[1:]
        text = ('Нийт 9 удаагийн төгсөлт зохион байгуулсан бөгөөд '
                '142 оюутан мэргэжил эзэмшжээ.')
        for field in fields:
            self.assertFalse(event_supported(field, text), field['name'])

    def test_exact_selector_accepts_complete_original_cumulative_paragraph(self):
        def transport(method, url, payload, timeout, max_bytes):
            if method == 'GET':
                return {'models': [{'name': 'graduation-fixture'}]}
            units = json.loads(payload['messages'][1]['content'])['EVIDENCE_UNITS']
            chosen = [unit['unit_id'] for unit in units if '142 оюутан' in unit['text']]
            return dict(done=True, done_reason='stop', message=dict(content=json.dumps(
                dict(insufficient=False, unit_ids=chosen))))

        generator = GroundedGenerator(Path(__file__).resolve().parents[1], transport=transport)
        generator.model = 'graduation-fixture'
        generator.configured = True
        result = generator.generate(self.query, [dict(source_id='civil-fixture',
            url='https://example.org/civil', title='Барилгын инженерийн тэнхим', text=self.source)])
        self.assertTrue(result['generated'], result)
        self.assertEqual(result['missing_requested_fields'], [])
        for claim in result['claims']:
            self.assertIn(claim['text'], self.source)


if __name__ == '__main__':
    unittest.main()
