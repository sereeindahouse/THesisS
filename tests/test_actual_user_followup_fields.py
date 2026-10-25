"""Constructed source-role controls; no school gold, model or STT inference."""
import unittest

from evidence_contract import evidence_units, exact_field_units, resolve_evidence_selection
from rag_runtime import ChatRAG
from source_fields import (cooperation_entity_choices, followup_field_request,
                           structured_field_extract, _office_field_plan)
from test_rag_runtime import Policy, Retriever, Generator


STOD = ('StoD Co., Ltd\n'
        'StoD компани нь программ хөгжүүлдэг байгууллага юм.\n'
        'Компьютерын ухааны тэнхим нь тус компанитай 2031 оны 6-р сараас хамтын ажиллагаагаа эхлүүлж, хамтран ажиллаж байна.\n'
        'Энэхүү хамтын ажиллагааны хүрээнд тус компанийн хөгжүүлсэн OrbitLab платформыг багш, оюутнууд сургалт болон программ хөгжүүлэлтдээ ашиглаж эхлээд байна.\n')
SAKURA = ('Sakura Internet Co., Ltd.\n'
          'Sakura Internet компани нь үүлэн тооцооллын үйлчилгээ үзүүлдэг байгууллага юм.\n'
          'Тэнхим нь тус компанитай 2030 оны 8-р сараас эхлэн хамтын ажиллагааны суурийг тавьж, онлайн сургалт явуулж байна.\n')
ARC = ('ARC Co., Ltd\nARC компани нь систем хөгжүүлдэг байгууллага юм.\n'
       'Тэнхим нь тус компанитай 2031 оны 2-р сараас эхлэн хамтын ажиллагаагаа эхлүүлж, '
       '2031–2032 оны хичээлийн жилийн намрын улиралд “Оптик”, “Роботик” зэрэг мэргэжлийн 2 хичээлийн хөтөлбөрийг сайжруулж, онлайнаар амжилттай хэрэгжүүлээд байна.\n')
END = 'Дотоодын компаниуд\nЖишээ ХХК'
S_QUERY = 'Sakura Internet-тэй хамтын ажиллагаа хэдэн оны хэдэн сараас эхэлсэн, компанийн ямар платформыг сургалтад ашиглаж эхэлсэн бэ?'
D_QUERY = 'Компьютерын ухааны тэнхим StoD компанитай хамтын ажиллагаагаа хэдэн оны хэдэн сараас эхлүүлж, ямар платформыг сургалтад ашиглаж эхэлсэн бэ?'
# Newly authored prompts, not a user's transcript or a literal typed query.
MISSING_QUERY = 'Компанийн хамтын ажиллагаа эхэлсэн сарын мэдээлэл болон сургалтад ашигладаг платформыг нь танилцуулаач?'
O_QUERY = 'Сургалтын алба хэдэн давхарт байдаг вэ, тус албаны утасны дугаарыг хэлнэ үү?'
TABLE = ('Оюутны тоо\n2031–2032 оны хичээлийн жилд нийт 79 оюутан суралцаж байна. Үүнээс:\n'
         '1-р курс 11 оюутан\n2-р курс 13 оюутан\n3-р курс 17 оюутан\n4-р курс 19 оюутан\n5-р курс 19 оюутан\n'
         'Мэргэжлийн клубийн үйл ажиллагаанд 23 оюутан хамрагдаж байна.')
T_QUERY = '2031–2032 оны хичээлийн жилд роботик инженерийн тэнхимд нийт хэдэн оюутан суралцаж, нэгдүгээрээс тавдугаар курс тус бүр хэдэн оюутантай вэ?'


def source(text, identifier='synthetic', **extra):
    result=dict(source_id=identifier, text=text, excerpt=text, start_offset=0,end_offset=len(text),
                text_scope='main_element',url='https://nmct.edu.mn/departments/computer-science',
                version=1,title='Компьютерын ухааны тэнхим',chunk_id=0,retrieved_at='2031-10-10',
                lexical_overlap_count=5)
    result.update(extra)
    return result


def selected(plan):
    return [part['source']['text'][part['start']:part['end']] for part in plan['parts']]


def office_contract(sources):
    # Exercise the source-role contract independently of the deliberately
    # narrow phrase parser; no observed user's wording is embedded here.
    request=dict(kind='office_floor_phone', requested_fields=['office_floor','office_phone'],
                 closed=True, unsafe=False)
    return _office_field_plan(request,sources)


class FollowupFieldTests(unittest.TestCase):
    def setUp(self):
        self.partners=source(SAKURA+ARC+STOD+END)

    def test_choices_are_derived_from_three_own_cards_not_generic_partner_list(self):
        choices=cooperation_entity_choices([self.partners])
        self.assertEqual([row['entity'] for row in choices],['Sakura Internet','ARC','StoD'])
        listed=source('Хамтрагчид\nOther Co., Ltd\nSakura Internet Co., Ltd.')
        self.assertEqual(cooperation_entity_choices([listed]),[])

    def test_complete_stod_month_platform_copies_dynamic_values_with_own_heading(self):
        plan=structured_field_extract(D_QUERY,[self.partners])
        self.assertEqual(plan['missing_fields'],[])
        text='\n'.join(selected(plan))
        self.assertIn('2031 оны 6-р сараас',text)
        self.assertIn('OrbitLab платформыг',text)
        self.assertNotIn('2030 оны 8',text)
        self.assertNotIn('Оптик',text)
        units=exact_field_units(plan['parts'])
        resolved=resolve_evidence_selection(D_QUERY,[units[-1]['unit_id']],units,max_claims=6)
        self.assertTrue(resolved['accepted'],resolved)
        self.assertIn('StoD Co., Ltd',resolved['claims'][0]['text'])
        self.assertTrue(all(claim['text'] in self.partners['text'] for claim in resolved['claims']))

    def test_sakura_platform_is_explicitly_missing_instead_of_borrowed_stod_name(self):
        plan=structured_field_extract(S_QUERY,[self.partners])
        self.assertEqual(plan['missing_fields'],['cooperation_platform'])
        self.assertIn('Sakura Internet',plan['message'])
        text='\n'.join(selected(plan))
        self.assertIn('2030 оны 8-р сараас',text)
        self.assertNotIn('OrbitLab',text)

    def test_another_partner_cannot_supply_requested_date_or_platform(self):
        missing=source(SAKURA+END)
        self.assertIsNone(structured_field_extract(D_QUERY,[missing]))
        self.assertIsNone(structured_field_extract(D_QUERY.replace('StoD','UnknownCloud'),[self.partners]))

    def test_conditions_negation_and_unknown_compound_do_not_authorize_direct_extraction(self):
        for query in (D_QUERY+' Мөн утсыг хэл.',D_QUERY.replace('хэдэн оны','хэрэв би тэнцвэл хэдэн оны'),
                      D_QUERY.replace('StoD','StoD биш'),D_QUERY.replace('ашиглаж','ашиглахгүйгээр')):
            with self.subTest(query=query):self.assertIsNone(structured_field_extract(query,[self.partners]))

    def test_conflicting_company_month_and_scoped_denial_are_not_ignored(self):
        changed=source((STOD+END).replace('2031 оны 6','2031 оны 7'),'other',version=2)
        self.assertIsNone(structured_field_extract(D_QUERY,[source(STOD+END),changed]))
        for invalid in ('Хуучин 2028 оны мэдээлэл\n'+STOD+END,
                        (STOD+END).replace('хамтран ажиллаж байна.','хамтран ажилладаг биш.'),
                        (STOD+END).replace('6-р','19-р')):
            with self.subTest(invalid=invalid):
                self.assertIsNone(structured_field_extract(D_QUERY,[source(invalid)]))

    def test_explicit_year_count_keeps_own_year_courses_and_excludes_job_workflow(self):
        query='2031–2032 оны намар ARC-ийн дэмжлэгээр хэдэн мэргэжлийн хичээл хэрэгжүүлсэн бэ?'
        plan=structured_field_extract(query,[self.partners])
        text='\n'.join(selected(plan))
        self.assertIn('2031–2032',text)
        self.assertIn('мэргэжлийн 2 хичээл',text)
        self.assertIn('“Оптик”, “Роботик”',text)
        self.assertNotIn('OrbitLab',text)
        self.assertIsNone(structured_field_extract(query.replace('2031–2032','2033–2034'),[self.partners]))
        self.assertIsNone(structured_field_extract(query.replace('ARC','Sakura Internet'),[self.partners]))

    def test_appended_entity_is_a_constraint_and_does_not_erase_body(self):
        body=MISSING_QUERY+'\nХамтын ажиллагааны байгууллага: StoD'
        request=followup_field_request(body)
        self.assertEqual(request['body'],MISSING_QUERY)
        self.assertEqual(request['entity'],'StoD')
        self.assertFalse(request['closed'])
        plan=structured_field_extract(body,[self.partners])
        self.assertEqual(plan['missing_fields'],['unparsed_request_scope'])
        self.assertIn('OrbitLab','\n'.join(selected(plan)))
        self.assertIn('бүх шаардлагыг бүрэн',plan['message'])
        conflict=D_QUERY+'\nХамтын ажиллагааны байгууллага: Sakura Internet'
        # The appended choice must not silently override an explicitly named
        # original company. The resolver remains responsible for both anchors.
        self.assertIsNone(structured_field_extract(conflict,[self.partners]))

    def test_office_never_borrows_general_school_or_another_office_phone(self):
        general=source('Ерөнхий холбоо\nУтас: 22334455\nБайршил: 9 давхар')
        plan=structured_field_extract(O_QUERY,[general])
        self.assertEqual(plan['parts'],[])
        self.assertEqual(plan['missing_fields'],['office_floor','office_phone'])
        office=source('Сургалтын алба\nБайршил: 7 давхар\nКарьерын алба\nУтас: 88776655')
        own=office_contract([office])
        self.assertEqual(own['missing_fields'],['office_phone'])
        self.assertNotIn('88776655','\n'.join(selected(own)))

    def test_office_own_supported_parts_and_explicit_missing_part_can_be_distinguished(self):
        office=source('Сургалтын алба\nБайршил: 7 давхар\nУтас: 88776655\nНомын сан')
        plan=office_contract([office])
        self.assertEqual(plan['missing_fields'],[])
        self.assertIn('7 давхар','\n'.join(selected(plan)))
        self.assertIn('88776655','\n'.join(selected(plan)))
        raw=O_QUERY.replace('байдаг вэ','байдаггүй')
        result=structured_field_extract(raw,[office])
        self.assertEqual(result['parts'],[])
        self.assertIn('үгүйсгэсэн',result['message'])

    def test_student_table_uses_own_department_year_and_all_requested_rows(self):
        table=source(TABLE,title='Роботик инженерийн тэнхим')
        plan=structured_field_extract(T_QUERY,[table])
        text='\n'.join(selected(plan))
        self.assertIn('нийт 79',text)
        self.assertIn('1-р курс 11',text)
        self.assertIn('5-р курс 19',text)
        self.assertNotIn('23 оюутан',text)
        for query in (T_QUERY.replace('2031–2032','2033–2034'),T_QUERY.replace('роботик','оптик'),
                      T_QUERY+' Мөн клубийн тоог хэл.',T_QUERY.replace('нийт хэдэн','зөвхөн нийт хэдэн')):
            with self.subTest(query=query):self.assertIsNone(structured_field_extract(query,[table]))

    def test_inconsistent_incomplete_conditional_tables_are_not_shortened(self):
        for text in (TABLE.replace('нийт 79','нийт 80'),TABLE.replace('3-р курс 17 оюутан\n',''),
                     TABLE.replace('Мэргэжлийн клубийн','Зөвхөн тэнцсэн тохиолдолд Мэргэжлийн клубийн'),
                     'Хуучин 2025 оны хүснэгт\n'+TABLE):
            with self.subTest(text=text):
                self.assertIsNone(structured_field_extract(T_QUERY,[source(text,title='Роботик инженерийн тэнхим')]))

    def test_raw_table_unit_keeps_year_total_context_and_club_is_separate(self):
        table=source(TABLE,title='Роботик инженерийн тэнхим')
        units=evidence_units([table])
        picked=next(unit for unit in units if unit['text'].startswith('1-р курс'))
        self.assertNotIn('клуб',picked['text'])
        result=resolve_evidence_selection('Курс бүр хэдэн оюутантай вэ?',[picked['unit_id']],units,max_claims=6)
        self.assertTrue(result['accepted'])
        text='\n'.join(claim['text'] for claim in result['claims'])
        self.assertIn('2031–2032',text)
        self.assertIn('нийт 79',text)
        self.assertNotIn('23 оюутан',text)
        conditional=TABLE.replace('Мэргэжлийн клубийн','Харин мэргэжлийн клубийн')
        self.assertTrue(any('1-р курс' in unit['text'] and 'клуб' in unit['text'] for unit in evidence_units([source(conditional)])))
        gap=TABLE.replace('3-р курс 17 оюутан\n','')
        self.assertTrue(any('1-р курс' in unit['text'] and 'клуб' in unit['text'] for unit in evidence_units([source(gap)])))


class FollowupChatTests(unittest.TestCase):
    def chat(self,query,sources,reason='no_supported_question_match'):
        retriever=Retriever();retriever.sources=sources;retriever._rows=sources
        generator=Generator()
        result=ChatRAG('.',Policy(reason),retriever,generator).route(None,query)
        return result,generator.calls

    def test_missing_entity_offers_all_source_backed_choices_without_answer(self):
        result,calls=self.chat(MISSING_QUERY,[source(SAKURA+ARC+STOD+END)],'missing_entity')
        self.assertEqual(result['route'],'D')
        self.assertEqual(result['clarification']['kind'],'missing_cooperation_entity')
        self.assertEqual([row['entity'] for row in result['clarification']['options']],['Sakura Internet','ARC','StoD'])
        self.assertEqual(result['query'],MISSING_QUERY)
        self.assertIsNone(result['answer'])
        self.assertEqual(calls,0)

    def test_sakura_partial_answer_metadata_and_stod_complete_are_distinct(self):
        sources=[source(SAKURA+ARC+STOD+END)]
        sakura,calls=self.chat(S_QUERY,sources)
        self.assertEqual(sakura['answer_kind'],'partial_official_website_extract')
        self.assertEqual(sakura['missing_fields'],['cooperation_platform'])
        self.assertNotIn('OrbitLab',sakura['answer'])
        self.assertEqual(calls,0)
        stod,calls=self.chat(D_QUERY,sources)
        self.assertEqual(stod['answer_kind'],'official_website_extract')
        self.assertIn('OrbitLab',stod['answer'])
        self.assertEqual(stod['missing_fields'],[])
        self.assertEqual(calls,0)

    def test_office_targets_both_missing_fields_without_generic_faq_or_model(self):
        result,calls=self.chat(O_QUERY,[source('Холбоо барих\nУтас: 22334455')],'specific_scope_not_supported')
        self.assertEqual(result['route'],'E')
        self.assertEqual(result['reason_code'],'requested_office_fields_not_supported')
        self.assertEqual(result['missing_fields'],['office_floor','office_phone'])
        self.assertIn('давхар',result['message'])
        self.assertRegex(result['message'],r'тусгай ут(?:ас|сыг)')
        self.assertIsNone(result['answer'])
        self.assertNotIn('22334455',result['message'])
        self.assertEqual(result['citations'],[])
        self.assertEqual(result['related_sources'],[])
        self.assertEqual(calls,0)
        empty,calls=self.chat(O_QUERY,[],'specific_scope_not_supported')
        self.assertEqual(empty['reason_code'],'requested_office_fields_not_supported')
        self.assertEqual(empty['missing_fields'],['office_floor','office_phone'])
        self.assertEqual(calls,0)

    def test_unknown_company_does_not_become_known_partner(self):
        result,calls=self.chat(D_QUERY.replace('StoD','UnknownCloud'),[source(SAKURA+ARC+STOD+END)])
        self.assertEqual(result['route'],'E')
        self.assertEqual(result['reason_code'],'cooperation_entity_not_supported')
        self.assertIsNone(result['answer'])
        self.assertEqual(calls,0)

    def test_recognized_fields_with_wrong_own_year_do_not_fall_back_to_mixed_generation(self):
        query='2030–2031 оны намар ARC-ийн дэмжлэгээр хэдэн мэргэжлийн хичээл хэрэгжүүлсэн бэ?'
        # Requested years occur elsewhere in the same captured page, while
        # ARC's own course paragraph describes another academic year.
        result,calls=self.chat(query,[source(SAKURA+ARC+STOD+END)])
        self.assertEqual(result['route'],'E')
        self.assertIsNone(result['answer'])
        self.assertEqual(calls,0)

    def test_appended_raw_scope_stays_partial_and_conditions_or_other_entity_fail_closed(self):
        sources=[source(SAKURA+ARC+STOD+END)]
        raw=MISSING_QUERY+'\nХамтын ажиллагааны байгууллага: StoD'
        result,calls=self.chat(raw,sources)
        self.assertEqual(result['answer_kind'],'partial_official_website_extract')
        self.assertIn('OrbitLab',result['answer'])
        self.assertEqual(result['missing_fields'],['unparsed_request_scope'])
        self.assertEqual(result['query'],raw)
        self.assertEqual(calls,0)
        for query in (MISSING_QUERY.replace('Компанийн','Sakura Internet компанийн')+'\nХамтын ажиллагааны байгууллага: StoD',
                      D_QUERY.replace('хэдэн оны','хэрэв тэнцвэл хэдэн оны')):
            with self.subTest(query=query):
                blocked,calls=self.chat(query,sources)
                self.assertIsNone(blocked['answer'])
                self.assertIn(blocked['route'],('D','E'))
                self.assertEqual(calls,0)


if __name__=='__main__':unittest.main()
