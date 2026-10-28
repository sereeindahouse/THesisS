"""Constructed company-scope refinements, not empirical school accuracy."""
import unittest

from evidence_contract import evidence_units, resolve_evidence_selection
from rag_runtime import refine_evidence_selection
from source_fields import (closed_field_selection_query, field_evidence_requirements,
                           single_company_selection_scope)


class CompanyRefinementTests(unittest.TestCase):
    query = ('ALTO-тай хамтран хэрэгжүүлсэн гурван хичээлийг нэрлэж, аль хичээлийн '
             'жилийн ямар улиралд явуулсныг хэлээрэй. Оюутнуудын ажлын ярилцлага '
             'ямар шатанд хүрсэн гэж дурдсан бэ?')
    other = ('Nimbus Cloud компани нь үүлэн серверийн үйлчилгээ үзүүлдэг байгууллага юм.\n'
             'Тухайлбал, компанийн экспертүүдтэй хамтран “Үүлэн систем” хичээлийг хэрэгжүүлсэн.')
    owner = ('ALTO Co., Ltd\n'
             'ALTO компани нь мэдээллийн систем хөгжүүлдэг байгууллага юм.\n'
             'Тэнхим нь тус компанитай 2034–2035 оны хичээлийн жилийн хаврын улиралд '
             '“Сүлжээ”, “Өгөгдөл”, “Систем” гэсэн 3 хичээлийг хамтран хэрэгжүүлсэн.')
    progress = 'Мөн тус компанид оюутнуудын ажлын ярилцлагад амжилттай оролцоод байна.'

    def make(self, *, other=None, owner=None, progress=None):
        sources = [dict(source_id='other', text=other or self.other),
                   dict(source_id='owner', text=(owner or self.owner)+'\n'+(progress or self.progress))]
        units = evidence_units(sources)
        other_units = [u for u in units if u['source_id']=='other']
        owner_units = [u for u in units if u['source_id']=='owner']
        roots = [other_units[-1]['unit_id']] + [u['unit_id'] for u in owner_units]
        self.assertEqual(len(roots), 3)
        return units, roots

    def refine(self, query=None, **changes):
        query = query or self.query
        units, roots = self.make(**changes)
        before = resolve_evidence_selection(query, roots, units, max_claims=6)
        self.assertTrue(before['accepted'], before)
        after, diag = refine_evidence_selection(query, roots, units, before)
        return before, after, diag, units, roots

    def test_closed_two_sentence_query_has_only_known_facets(self):
        scope=single_company_selection_scope(self.query)
        self.assertEqual(scope['requested_name'],'alto')
        self.assertEqual(scope['requested_count'],3)
        self.assertTrue(closed_field_selection_query(self.query,field_evidence_requirements(self.query)))

    def test_other_company_and_its_dependent_course_are_removed_together(self):
        before,after,diag,_,roots=self.refine()
        self.assertGreater(len(before['claims']),len(after['claims']))
        self.assertNotIn('Nimbus','\n'.join(c['text'] for c in after['claims']))
        self.assertEqual(diag['removed_root_ids'],[roots[0]])
        self.assertIn('2034–2035','\n'.join(c['text'] for c in after['claims']))
        self.assertIn('хаврын улиралд','\n'.join(c['text'] for c in after['claims']))
        self.assertIn('ажлын ярилцлагад','\n'.join(c['text'] for c in after['claims']))

    def test_generic_company_and_requested_count_are_not_answer_constants(self):
        query=self.query.replace('ALTO','Nexora').replace('гурван','хоёр')
        owner=self.owner.replace('ALTO','Nexora').replace('“Систем” гэсэн 3','гэсэн 2').replace('“Өгөгдөл”, гэсэн','“Өгөгдөл” гэсэн')
        before,after,diag,_,_=self.refine(query,owner=owner)
        self.assertLess(len(after['claims']),len(before['claims']))
        self.assertEqual(diag['company_scope'],'nexora')

    def test_same_facet_paraphrases_and_possessive_company_are_closed(self):
        for query in [
            'ALTO компанитай хамтран ямар гурван хичээл хэрэгжүүлсэн бэ? Хичээлийн жил, улирал болон оюутнуудын ажлын ярилцлагын явцыг хамт хэлнэ үү.',
            'ALTO-ийн хамтын ажиллагааны хичээлүүдийг нэрлээд аль оны ямар улиралд хэрэгжсэнийг хэлээрэй. Эхний оюутнууд ажлын ярилцлагад орсон эсэхийг бас тайлбарлаарай.']:
            with self.subTest(query=query):
                self.assertIsNotNone(single_company_selection_scope(query))
                before,after,_,_,_=self.refine(query)
                self.assertLess(len(after['claims']),len(before['claims']))

    def test_unknown_facets_and_two_company_queries_disable_pruning(self):
        for query in [self.query+' Захирал нь хэн бэ?',
                      self.query.replace('ALTO-тай','ALTO болон Nimbus-тай'),
                      self.query.replace('гурван хичээлийг','гурван хичээлийн төлбөрийг'),
                      self.query.replace('аль хичээлийн','2027 оны хичээлийн'),
                      self.query.replace('хэлээрэй.','хэлээрэй, мөн байршлыг хэл.'),
                      'Хэрэв тэтгэлэгтэй бол '+self.query,
                      self.query.replace('ALTO-тай','ALTO-тай биш Nimbus-тай')]:
            with self.subTest(query=query):
                self.assertIsNone(single_company_selection_scope(query))
                before,after,diag,_,_=self.refine(query)
                self.assertEqual(after['claims'],before['claims'])
                self.assertFalse(diag['eligible'])

    def test_requested_company_mention_in_other_root_preserves_it(self):
        other=self.other.replace('хэрэгжүүлсэн.','хэрэгжүүлсэн. ALTO-тай холбоотой нэмэлт тайлбар.')
        before,after,_,_,_=self.refine(other=other)
        self.assertEqual(after['claims'],before['claims'])

    def test_unidentified_and_unbound_pronominal_roots_are_preserved(self):
        for other in ['Нэмэлт тайлбар нь хамтын ажиллагааны талаар мэдээлэл өгч байна.',
                      'Тухайн ажлын талаарх мэдээллийг энд дэлгэрүүлэн тайлбарлаж байна.']:
            with self.subTest(other=other):
                # The other root has no owner and no preceding company context.
                before,after,_,_,_=self.refine(other=other)
                self.assertEqual(after['claims'],before['claims'])

    def test_later_company_heading_cannot_erase_unknown_prefix(self):
        other='Нэмэлт холбоотой тайлбар\n'+self.other
        before,after,_,_,_=self.refine(other=other)
        self.assertEqual(after['claims'],before['claims'])

    def test_condition_negation_or_exception_preserves_original_selection(self):
        for suffix in [' Хэрэв нөхцөл биелбэл хэрэгжинэ.',
                       ' Бусад тохиолдолд хэрэгжихгүй.',
                       ' Харин өөр нөхцөлд энэ мэдээлэл хамаарна.']:
            with self.subTest(suffix=suffix):
                before,after,diag,_,_=self.refine(other=self.other+suffix)
                self.assertEqual(after['claims'],before['claims'])
                self.assertEqual(diag['reason'],'condition_or_exception_preserved')

    def test_missing_year_term_or_requested_count_prevents_pruning(self):
        for owner in [self.owner.replace('2034–2035 оны хичээлийн жилийн ',''),
                      self.owner.replace('хаврын улиралд ',''),
                      self.owner.replace('“Сүлжээ”, ',''),
                      self.owner.replace('“Сүлжээ”, “Өгөгдөл”, “Систем”','сүлжээ, өгөгдөл, систем')]:
            with self.subTest(owner=owner):
                before,after,_,_,_=self.refine(owner=owner)
                self.assertEqual(after['claims'],before['claims'])

    def test_same_company_and_mixed_owner_closures_are_preserved(self):
        before,after,_,_,_=self.refine(other=self.other.replace('Nimbus Cloud','ALTO'))
        self.assertEqual(after['claims'],before['claims'])
        units,roots=self.make(other=self.other.replace('Тухайлбал,',
            'Tori компани нь өөр байгууллага юм. Тухайлбал,'))
        # Explicitly link two different owners: no single owner may be inferred.
        other_units=[u for u in units if u['source_id']=='other']
        other_units[-1]['context_unit_ids']=[other_units[0]['unit_id']]
        before=resolve_evidence_selection(self.query,roots,units,max_claims=6)
        self.assertTrue(before['accepted'])
        after,_=refine_evidence_selection(self.query,roots,units,before)
        self.assertEqual(after['claims'],before['claims'])


if __name__=='__main__':
    unittest.main()
