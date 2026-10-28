"""Constructed programme/date/partner/course scope; no real school facts."""
import unittest
from evidence_contract import evidence_units,resolve_evidence_selection
from rag_runtime import refine_evidence_selection
from source_fields import programme_event_scope,programme_event_record,field_evidence_requirements,missing_field_evidence


class ProgrammeEventRefinementTests(unittest.TestCase):
    query=('Nova карьер төлөвлөлтийн зуны сургалтыг 2037 онд хэзээ, Японы ямар компанитай '
           'хамтран, хэддүгээр курсийн оюутнуудад зориулж зохион байгуулсан бэ?')
    programme=('Туршилтын коллеж 2037.02.11-13-ны өдрүүдэд Япон улсын Люмен Фотоник компанитай '
               'хамтран 3-4-р курсийн оюутнуудад зориулж Nova карьер төлөвлөлтийн зуны сургалтыг '
               'хамтран зохион байгуулсан билээ. Энэхүү үйл ажиллагааны контент өндөр үзэлттэй '
               'төдийгүй олон үзэгчид сонирхлоо илэрхийлжээ.')
    other='Кварц инженеринг компани дадлага хөтөлбөр зарлаж, оюутнуудад компани болон хөтөлбөрөө танилцууллаа.'
    continuation='Тус компани эхний дадлагад өөр төгсөгчийг хамруулсан байна.'

    def refine(self, *, query=None,programme=None,other=None,continuation=None,select_child=False):
        query=query or self.query;programme=programme or self.programme;other=other or self.other
        text=other+('\n'+continuation if continuation else '')
        units=evidence_units([dict(source_id='programme',text=programme),dict(source_id='other',text=text)])
        roots=[u['unit_id'] for u in units if u['source_id']=='programme']
        foreign=[u['unit_id'] for u in units if u['source_id']=='other']
        roots+=foreign[-1:] if select_child else foreign
        before=resolve_evidence_selection(query,roots,units,max_claims=6)
        self.assertTrue(before['accepted'],before)
        after,diag=refine_evidence_selection(query,roots,units,before)
        return before,after,diag,units

    def test_all_known_facet_wordings_consume_generic_identifier(self):
        queries=[self.query,
            '2037 оны Nova карьер төлөвлөлтийн зуны сургалтын огноо, хамтарсан Японы компани, хамрагдах курсыг хэлнэ үү.',
            'Nova карьер төлөвлөлтийн сургалтыг 2037 онд ямар өдрүүдэд, хэнтэй хамт, хэддүгээр курсийнхэнд зориулж хийсэн бэ?',
            '2037 оны Nova карьер төлөвлөлтийн зуны сургалт хэдний өдрүүдэд болсон, Японы аль компани хамтарсан, ямар курсийн оюутнуудад зориулсан бэ?']
        for query in queries:
            with self.subTest(query=query):
                scope=programme_event_scope(query)
                self.assertEqual(scope['programme'],'nova')
                self.assertEqual(scope['year'],'2037')
                before,after,diag,_=self.refine(query=query)
                self.assertLess(len(after['claims']),len(before['claims']))
                self.assertEqual(after['claims'][0]['text'],self.programme)

    def test_whole_programme_paragraph_including_additive_social_clause_is_retained(self):
        _,after,diag,_=self.refine()
        self.assertEqual([c['text'] for c in after['claims']],[self.programme])
        self.assertIn('төдийгүй',after['claims'][0]['text'])
        self.assertEqual(diag['reason'],'closed_fields_complete_subset')

    def test_proven_other_company_dependency_closure_is_removed_together(self):
        before,after,_,_=self.refine(continuation=self.continuation,select_child=True)
        self.assertEqual(len(before['claims']),3)
        self.assertEqual([c['text'] for c in after['claims']],[self.programme])

    def test_latin_and_temporal_company_name_are_source_derived(self):
        for other in ['Өнөөдөр Японы Zircon компанитай уулзалт зохион байгуулагдлаа.',
                      'Aster Robotics компани шинэ дадлага хөтөлбөрийг танилцууллаа.']:
            with self.subTest(other=other):
                before,after,_,_=self.refine(other=other)
                self.assertLess(len(after['claims']),len(before['claims']))

    def test_other_identifier_year_date_partner_and_course_values_work(self):
        programme=self.programme.replace('Nova','Orbit').replace('2037.02.11-13','2041.11.21-24')
        programme=programme.replace('Люмен Фотоник','Гэрэл Системс').replace('3-4-р','2-5-р')
        query=self.query.replace('Nova','Orbit').replace('2037','2041')
        _,after,_,_=self.refine(query=query,programme=programme)
        self.assertEqual([c['text'] for c in after['claims']],[programme])

    def test_unknown_facets_second_identifier_and_condition_disable(self):
        for query in [self.query+' Төлбөр хэд вэ?',self.query.replace('Nova','Nova болон Orbit'),
                      self.query.replace('2037 онд','2037 болон 2038 онд'),
                      'Хэрэв тэтгэлэгтэй бол '+self.query,
                      self.query.replace('ямар компанитай','ямар компанитай, ямар хотод')]:
            with self.subTest(query=query):
                self.assertIsNone(programme_event_scope(query))
                before,after,_,_=self.refine(query=query)
                self.assertEqual(after['claims'],before['claims'])

    def test_omitted_wrong_year_future_or_invalid_date_prevents_pruning(self):
        for programme in [self.programme.replace('2037.02.11-13','2038.02.11-13'),
                          self.programme.replace('2037.02.11-13','2037.02.31-32'),
                          self.programme.replace('Люмен Фотоник компанитай хамтран','хамтран'),
                          self.programme.replace('3-4-р курсийн оюутнуудад','оюутнуудад'),
                          self.programme.replace('зохион байгуулсан билээ','зохион байгуулахаар төлөвлөж байна')]:
            with self.subTest(programme=programme):
                fields=field_evidence_requirements(self.query)
                self.assertTrue(missing_field_evidence(fields,programme))
                before,after,_,_=self.refine(programme=programme)
                self.assertEqual(after['claims'],before['claims'])

    def test_separate_other_programme_fields_and_publication_date_cannot_fill_roles(self):
        scope=programme_event_scope(self.query)
        text=self.programme.replace('2037.02.11-13-ны өдрүүдэд ','')
        text='2037.02.11-13 нийтэлсэн\n'+text
        self.assertIsNone(programme_event_record(text,scope))

    def test_retracted_unconfirmed_or_conditional_event_is_not_positive_evidence(self):
        scope=programme_event_scope(self.query)
        for text in [self.programme.replace('зохион байгуулсан билээ','зохион байгуулсан гэж батлагдаагүй'),
                     self.programme.replace('зохион байгуулсан билээ','зохион байгуулсан гэж батлаагүй'),
                     self.programme+' Энэ мэдээллийг няцаасан.',
                     self.programme+' Энэ мэдэгдлийг үгүйсгэсэн.',
                     'Хэрэв нөхцөл биелбэл '+self.programme,
                     'Зөвхөн бүртгүүлсэн тохиолдолд '+self.programme]:
            with self.subTest(text=text):
                self.assertIsNone(programme_event_record(text,scope))
                self.assertTrue(missing_field_evidence(field_evidence_requirements(self.query),text))

    def test_unknown_unbound_pronoun_and_own_partner_roots_stay(self):
        for other in [self.continuation,
                      'Нэмэлт тайлбарыг эхийн өөр хэсэгт дэлгэрүүлсэн байна.',
                      self.other.replace('Кварц инженеринг','Люмен Фотоник'),
                      self.other+' Nova сургалтын тухай нэмэлт мэдээлэл.']:
            with self.subTest(other=other):
                before,after,_,_=self.refine(other=other)
                self.assertEqual(after['claims'],before['claims'])

    def test_condition_negation_and_requested_dependencies_remain(self):
        for suffix in [' Хэрэв нөхцөл биелбэл энэ мэдээлэл хамаарна.',
                       ' Энэ хөтөлбөрт хамрагдах боломжгүй.',
                       ' Зөвхөн багштай тохиолдолд оролцоно.']:
            with self.subTest(suffix=suffix):
                before,after,_,_=self.refine(other=self.other+suffix)
                self.assertEqual(after['claims'],before['claims'])


if __name__=='__main__':unittest.main()
