"""Constructed event-scope regressions; numerical values are test fixtures."""
import json
from pathlib import Path
import unittest

from source_fields import field_evidence_requirements, missing_field_evidence
from rag_runtime import GroundedGenerator


class FoundingEventTests(unittest.TestCase):
    query = 'Сургууль анх хэдэн оны хэдэн сарын хэдэнд, хэдэн оюутан хэдэн бүлэгтэй байгуулагдсан бэ?'
    history = ('2043\nҮүсгэн байгуулагдсан\n'
               '"Туршилтын коллеж"-ийг 07 сарын 19-ний өдөр үүсгэн байгуулж, анхны 71 оюутан 4 бүлэгтэйгээр хичээллэж эхлэв.')
    scholarship = ('Тэтгэлэг\n2044 оны долдугаар сарын 19\n'
                   'Манай сургууль анх удаа 7 оюутнаа тэтгэлэгт сонгон тодорхойлсон юм.')

    def fields(self, query=None):
        result=field_evidence_requirements(query or self.query)
        self.assertTrue(result)
        return result

    def test_complete_local_event_with_year_heading_supplies_all_fields(self):
        fields=self.fields()
        self.assertEqual(len(fields),3)
        self.assertEqual(missing_field_evidence(fields,[self.history]),[])

    def test_unrelated_scholarship_cannot_supply_founding_numbers(self):
        self.assertEqual(len(missing_field_evidence(self.fields(),[self.scholarship])),3)

    def test_initial_student_or_group_field_cannot_be_missing(self):
        for text in [self.history.replace('71 оюутан','оюутнууд'),self.history.replace('4 бүлэгтэйгээр','бүлгүүдээр')]:
            with self.subTest(text=text):self.assertTrue(missing_field_evidence(self.fields(),[text]))

    def test_fields_cannot_be_borrowed_from_another_event_or_unit(self):
        date_only=self.history.split(', анхны')[0]+'.'
        unrelated='Хожим манай сургууль анхны 71 оюутан, 4 бүлэгтэй хөтөлбөр хэрэгжүүлэв.'
        self.assertTrue(missing_field_evidence(self.fields(),[date_only,unrelated]))
        self.assertTrue(missing_field_evidence(self.fields(),[date_only+'\n'+unrelated]))

    def test_later_counts_do_not_fill_founding_fields(self):
        text=self.history.replace(', анхны',', харин одоогийн анхны')
        self.assertTrue(missing_field_evidence(self.fields(),[text]))

    def test_negated_or_planned_founding_is_not_a_completed_event(self):
        for replacement in ['үүсгэн байгуулахаар төлөвлөж','үүсгэн байгуулаагүй боловч']:
            self.assertTrue(missing_field_evidence(self.fields(),[self.history.replace('үүсгэн байгуулж',replacement)]))

    def test_different_entity_founding_is_not_school_founding(self):
        text=self.history.replace('Туршилтын коллеж','Туршилтын клуб')
        self.assertTrue(missing_field_evidence(self.fields(),[text]))

    def test_publication_date_cannot_supply_missing_founding_year(self):
        text=self.history.replace('2043\n','2043 оны долдугаар сарын 19\n')
        self.assertTrue(missing_field_evidence(self.fields(),[text]))

    def test_year_only_request_does_not_require_unasked_counts_or_month_day(self):
        fields=self.fields('Сургууль хэдэн онд байгуулагдсан бэ?')
        self.assertEqual(len(fields),1)
        self.assertEqual(missing_field_evidence(fields,['Туршилтын коллеж 2043 онд байгуулагдсан.']),[])

    def test_date_only_request_does_not_require_student_counts(self):
        fields=self.fields('Сургууль байгуулагдсан огноо хэд вэ?')
        self.assertEqual(len(fields),1)
        self.assertEqual(missing_field_evidence(fields,[self.history.split(', анхны')[0]+'.']),[])

    def test_brevity_does_not_disable_event_contract(self):
        self.assertEqual(self.fields(self.query+' Нэмэлт тайлбар хэрэггүй.'),self.fields())

    def test_named_school_must_be_the_founded_subject(self):
        query=self.query.replace('Сургууль','Альфа сургууль')
        fields=self.fields(query)
        text='Альфа сургууль 2043 оны 07 сарын 19-ний өдөр байгуулагдсан бөгөөд анхны 71 оюутан 4 бүлэгтэй хичээллэв.'
        self.assertEqual(missing_field_evidence(fields,[text]),[])
        self.assertTrue(missing_field_evidence(fields,[text.replace('Альфа','Бета')]))
        self.assertTrue(missing_field_evidence(fields,[text.replace('Альфа','Альфа болон Бета')]))

    def test_school_as_actor_founding_a_club_or_program_is_rejected(self):
        for entity in ['Бета клубийг','Бета хөтөлбөрийг']:
            text=f'Туршилтын сургууль 2043 оны 07 сарын 19-ний өдөр {entity} үүсгэн байгуулж, анхны 71 оюутан 4 бүлэгтэй үйл ажиллагаа эхлүүлэв.'
            self.assertTrue(missing_field_evidence(self.fields(),[text]))

    def test_publication_predicate_and_planned_main_predicate_are_rejected(self):
        texts=[
            '2043 оны 07 сарын 19-ний өдөр нийтэлсэн мэдээнд Туршилтын коллеж байгуулагдсан бөгөөд анхны 71 оюутан 4 бүлэгтэй хичээллэсэн гэж бичжээ.',
            'Туршилтын коллежийг 2043 оны 07 сарын 19-ний өдөр үүсгэн байгуулж, анхны 71 оюутан 4 бүлэгтэйгээр хичээллүүлэхээр төлөвлөсөн.',
            'Туршилтын коллежийг 2043 оны 07 сарын 19-ний өдөр анхны 71 оюутан 4 бүлэгтэй үүсгэн байгуулж байгаагүй.',
            'Туршилтын коллеж 2043 оны 07 сарын 19-ний өдөр анхны 71 оюутан 4 бүлэгтэй байгуулагдсан гэх мэдээлэл худал.',
        ]
        for text in texts:
            with self.subTest(text=text):self.assertTrue(missing_field_evidence(self.fields(),[text]))

    def test_another_conjunct_cannot_supply_founding_date_or_intake(self):
        texts=[
            'Туршилтын коллеж 2043 онд байгуулагдсан бөгөөд 07 сарын 19-ний өдөр болсон тэтгэлгийн уулзалтад анхны 71 оюутан 4 бүлэгт оролцов.',
            'Туршилтын коллеж 2043 онд байгуулагдсан бөгөөд 07 сарын 19-ний өдөр анхны 71 суралцагч 4 бүлэгтэй тэтгэлэгт нэр дэвшив.',
            'Туршилтын коллеж 2043 оны 07 сарын 19-ний өдөр байгуулагдсан бөгөөд хоёр жил өнгөрсний дараах анхны 71 оюутан 4 бүлэгтэй сургалт хэрэгжүүлэв.',
        ]
        for text in texts:
            with self.subTest(text=text):self.assertTrue(missing_field_evidence(self.fields(),[text]))

    def test_invalid_numeric_day_cannot_match_a_prefix_digit(self):
        text='Туршилтын коллеж 2043 оны 07 сарын 99-ний өдөр анхны 71 оюутан 4 бүлэгтэй байгуулагдсан.'
        self.assertTrue(missing_field_evidence(self.fields(),[text]))

    def test_declarative_year_and_when_forms_keep_the_event_requirement(self):
        for query in ['Сургууль байгуулагдсан оныг хэл.', 'Сургууль хэдийд байгуулагдсан бэ?']:
            fields=self.fields(query)
            self.assertEqual(missing_field_evidence(fields,['Туршилтын коллеж 2043 онд байгуулагдсан.']),[])

    def test_counts_before_completed_founding_predicate_are_local(self):
        text='Туршилтын коллеж 2043 оны 07 сарын 19-ний өдөр анхны 71 оюутан 4 бүлэгтэй байгуулагдсан.'
        self.assertEqual(missing_field_evidence(self.fields(),[text]),[])

    def test_conditional_denied_or_unconfirmed_event_does_not_count(self):
        positive='Туршилтын коллеж 2043 оны 07 сарын 19-ний өдөр анхны 71 оюутан 4 бүлэгтэй байгуулагдсан'
        for text in ['Хэрэв '+positive+' бол дурсгалын өдөр болно.',
                     positive+' гэх яриаг няцаасан.',positive+' гэх таамаг батлагдаагүй.']:
            with self.subTest(text=text):self.assertTrue(missing_field_evidence(self.fields(),[text]))

    def test_intake_at_another_named_school_cannot_fill_this_founding(self):
        text='Альфа сургууль 2043 оны 07 сарын 19-ний өдөр байгуулагдсан бөгөөд Бета сургуулийн анхны 71 оюутан 4 бүлэгтэй хичээллэв.'
        self.assertTrue(missing_field_evidence(self.fields(),[text]))

    def test_latin_named_school_is_bound_to_the_local_subject(self):
        fields=self.fields(self.query.replace('Сургууль','ALPHA сургууль'))
        text='ALPHA сургууль 2043 оны 07 сарын 19-ний өдөр анхны 71 оюутан 4 бүлэгтэй байгуулагдсан.'
        self.assertEqual(missing_field_evidence(fields,[text]),[])
        self.assertTrue(missing_field_evidence(fields,[text.replace('ALPHA','BETA')]))

    def test_impossible_month_day_does_not_count(self):
        for date in ['02 сарын 31','04 сарын 31','13 сарын 19']:
            text=f'Туршилтын коллеж 2043 оны {date}-ний өдөр анхны 71 оюутан 4 бүлэгтэй байгуулагдсан.'
            with self.subTest(date=date):self.assertTrue(missing_field_evidence(self.fields(),[text]))

    def test_non_founding_and_non_school_questions_are_not_rewritten(self):
        self.assertEqual(field_evidence_requirements('Сургууль анх хэдэн оюутнаа тэтгэлэгт нэр дэвшүүлсэн бэ?'),[])
        self.assertEqual(field_evidence_requirements('Клуб хэдэн онд байгуулагдсан бэ?'),[])

    def generate(self, sources, choose):
        def transport(method,url,payload,timeout,max_bytes):
            if method=='GET':return {'models':[{'name':'event-fixture'}]}
            units=json.loads(payload['messages'][1]['content'])['EVIDENCE_UNITS']
            selected=choose(units)
            return dict(done=True,done_reason='stop',message=dict(content=json.dumps(
                dict(insufficient=False,unit_ids=[selected['unit_id']]))))
        generator=GroundedGenerator(Path(__file__).resolve().parents[1],transport=transport)
        generator.model='event-fixture';generator.configured=True
        return generator.generate(self.query,sources)

    def test_wrong_event_cannot_be_accepted_even_when_selector_repeats_it(self):
        source=dict(source_id='wrong',url='https://example.org/scholarship',text=self.scholarship,title='Зохиомол тэтгэлэг')
        result=self.generate([source],lambda units:units[0])
        self.assertFalse(result['generated'])

    def test_retry_can_select_correct_original_event_without_authoring_answer(self):
        sources=[dict(source_id='wrong',url='https://example.org/scholarship',text=self.scholarship,title='Зохиомол тэтгэлэг'),
                 dict(source_id='right',url='https://example.org/history',text=self.history,title='Зохиомол түүх')]
        count=[0]
        def choose(units):
            count[0]+=1
            return units[0] if count[0]==1 else next(u for u in units if '71' in u['text'])
        result=self.generate(sources,choose)
        self.assertTrue(result['generated'])
        self.assertEqual(result['llm_calls'],2)
        self.assertTrue(all(c['text'] in self.history for c in result['claims']))


if __name__=='__main__':unittest.main()
