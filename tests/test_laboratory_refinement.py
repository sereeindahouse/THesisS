"""Constructed complete laboratory requests; no school names/values or inference."""
import unittest

from evidence_contract import evidence_units,resolve_evidence_selection
from rag_runtime import refine_evidence_selection
from source_fields import laboratory_overview_scope,field_evidence_requirements,missing_field_evidence


class LaboratoryRefinementTests(unittest.TestCase):
    query=('Химийн тэнхимийн хоёр лабораторийг нэрлээд, тэнд ашигладаг төхөөрөмжүүд болон '
           'нэг удаа хэдэн оюутан ажиллах боломжтойг тайлбарлаач.')
    laboratory=('Лаборатори, сургалтын орчин\nТэнхим нь спектрийн лаборатори, уусмалын лаборатори '
                'гэсэн хоёр үндсэн лабораторитой. Эдгээр лабораториудад фотометр, хатаагч '
                'төхөөрөмжүүд ашиглагддаг. Нэг удаад 6–9 оюутан ажиллах боломжтой.')
    activity=('Оюутны үйл ажиллагаа\nОюутнууд мэргэжлийн клуб, нэмэлт сургалт, уулзалт зэрэг '
              'үйл ажиллагаанд идэвхтэй оролцож байна. Үүнд Sky клуб, спортын өдөрлөг багтана.')
    table='2-р курс 39 оюутан\n3-р курс 22 оюутан\nМэргэжлийн клубийн үйл ажиллагаанд 5 оюутан хамрагдаж байна.'

    def refine(self, texts=None, query=None, links=None):
        query=query or self.query
        texts=texts or [self.laboratory,self.activity,self.table]
        units=evidence_units([dict(source_id=str(i),text=text) for i,text in enumerate(texts)])
        if links:
            for child,parent in links:
                units[child]['context_unit_ids']=[units[parent]['unit_id']]
        roots=[unit['unit_id'] for unit in units]
        self.assertLessEqual(len(roots),3)
        before=resolve_evidence_selection(query,roots,units,max_claims=6)
        self.assertTrue(before['accepted'],before)
        after,diag=refine_evidence_selection(query,roots,units,before)
        return before,after,diag,units

    def test_complete_three_facets_drop_only_independent_student_activity_and_table(self):
        before,after,diag,_=self.refine()
        self.assertEqual(len(before['claims']),3)
        self.assertEqual([claim['text'] for claim in after['claims']],[self.laboratory])
        self.assertEqual(diag['reason'],'closed_fields_complete_subset')
        self.assertEqual(missing_field_evidence(field_evidence_requirements(self.query),self.laboratory),[])

    def test_generic_department_equipment_count_and_capacity_are_not_constants(self):
        query=self.query.replace('Химийн','Электроникийн').replace('хоёр','гурван')
        laboratory=self.laboratory.replace('уусмалын лаборатори','дохионы лаборатори, оптикийн лаборатори')
        laboratory=laboratory.replace('хоёр','гурван').replace('фотометр, хатаагч','осциллограф, микроскоп').replace('6–9','11–14')
        _,after,_,_=self.refine([laboratory,self.activity],query=query)
        self.assertEqual([claim['text'] for claim in after['claims']],[laboratory])

    def test_omitting_each_facet_is_detected(self):
        requirements=field_evidence_requirements(self.query)
        for field,text in [('names',self.laboratory.replace('спектрийн лаборатори, уусмалын лаборатори гэсэн хоёр үндсэн лабораторитой.',
                                                        'лабораторийн мэдээллийг удахгүй нэмнэ.')),
                           ('equipment',self.laboratory.replace('фотометр, хатаагч төхөөрөмжүүд ашиглагддаг.',
                                                              'тоног төхөөрөмжүүд ашиглагддаг.')),
                           ('session_capacity',self.laboratory.replace('Нэг удаад 6–9 оюутан ажиллах боломжтой.',
                                                                     'Нийт 29 оюутан суралцаж байна.'))]:
            with self.subTest(field=field):
                self.assertIn('laboratory_'+field,missing_field_evidence(requirements,text))
                before,after,_,_=self.refine([text,self.activity])
                self.assertEqual(after['claims'],before['claims'])

    def test_weekly_hours_and_course_students_are_not_one_session_capacity(self):
        for value in ['Долоо хоногт 6–9 цаг ажиллах боломжтой.',
                      'Нийт 6–9 оюутан суралцдаг.',
                      'Нэг удаад 6–9 оюутан ажиллах боломжгүй.']:
            with self.subTest(value=value):
                text=self.laboratory.replace('Нэг удаад 6–9 оюутан ажиллах боломжтой.',value)
                self.assertIn('laboratory_session_capacity',missing_field_evidence(field_evidence_requirements(self.query),text))

    def test_other_facility_capacity_cannot_fill_laboratory_field(self):
        text=self.laboratory.replace('Нэг удаад 6–9','Номын сан\nНэг удаад 6–9')
        self.assertIn('laboratory_session_capacity',missing_field_evidence(field_evidence_requirements(self.query),text))

    def test_requested_lab_count_is_checked_against_source_labels(self):
        query=self.query.replace('хоёр','гурван')
        self.assertIn('laboratory_names',missing_field_evidence(field_evidence_requirements(query),self.laboratory))
        before,after,_,_=self.refine(query=query)
        self.assertEqual(after['claims'],before['claims'])

    def test_unrecognized_facets_conditions_years_or_multiple_departments_disable(self):
        for query in [self.query+' Байршлыг хэлнэ үү.',
                      self.query.replace('төхөөрөмжүүд','төхөөрөмжүүдийн үнэ'),
                      self.query.replace('Химийн','Химийн болон физикийн'),
                      self.query.replace('Химийн','2029 оны химийн'),
                      'Хэрэв зөвшөөрөлтэй бол '+self.query,
                      self.query.replace('нэг удаа','долоо хоногт')]:
            with self.subTest(query=query):
                self.assertIsNone(laboratory_overview_scope(query))
                before,after,diag,_=self.refine(query=query)
                self.assertEqual(after['claims'],before['claims'])
                self.assertFalse(diag['eligible'])

    def test_unknown_pronominal_permission_and_lab_bearing_roots_remain(self):
        for extra in ['Тухайн үйлчилгээг эхийн өөр хэсэгт тайлбарласан.',
                      'Сурагчид багшаас зөвшөөрөл авч оролцоно.',
                      self.activity+' Багшийн зөвшөөрөл шаардлагатай.',
                      self.activity.replace('Sky клуб','Sky лабораторийн клуб')]:
            with self.subTest(extra=extra):
                before,after,_,_=self.refine([self.laboratory,extra])
                self.assertEqual(after['claims'],before['claims'])

    def test_condition_or_exception_is_preserved(self):
        for suffix in [' Хэрэв багш байвал оролцоно.',
                       ' Зөвхөн бүртгүүлсэн тохиолдолд хэрэглэнэ.',
                       ' Бусад үед ашиглахгүй.']:
            with self.subTest(suffix=suffix):
                before,after,diag,_=self.refine([self.laboratory,self.activity+suffix])
                self.assertEqual(after['claims'],before['claims'])
                self.assertEqual(diag['reason'],'condition_or_exception_preserved')

    def test_dependent_activity_does_not_drop_laboratory_context(self):
        before,after,_,_=self.refine([self.laboratory,self.activity],links=[(1,0)])
        self.assertEqual(after['claims'],before['claims'])

    def test_source_text_is_still_exact_after_refinement(self):
        _,after,_,units=self.refine()
        self.assertEqual(after['selected_unit_ids'],[units[0]['unit_id']])
        for claim in after['claims']:
            self.assertIn(claim['text'],claim['quote'])

    def test_generic_equipment_adjectives_are_not_equipment_names(self):
        fields=field_evidence_requirements(self.query)
        for clause in ('Эдгээр лабораториудад орчин үеийн тоног төхөөрөмжүүд ашиглагддаг.',
                       'Лаборатори нь сайн чанарын, шинэ тоног төхөөрөмжүүд ашигладаг.'):
            self.assertIn('laboratory_equipment',missing_field_evidence(fields,clause))
        self.assertNotIn('laboratory_equipment',missing_field_evidence(fields,
            'Лабораторид фотометр төхөөрөмж ашиглагддаг.'))


if __name__=='__main__':unittest.main()
