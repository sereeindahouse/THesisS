"""Constructed staff identity/attribute counterexamples, not accuracy scores."""
import unittest
from source_fields import (staff_query_scope, staff_count_spans, field_extract, requested_detail, detail_supported,
    field_evidence_requirements, missing_field_evidence, staff_contact_cards)
from teacher_media import _directory_only, _generic_staff_overview


def source(title,text,url):
    return dict(title=title,text=text,url=url)


class StaffScopeTests(unittest.TestCase):
    def setUp(self):
        self.chem=source('Химийн инженерийн тэнхим',
            'Тус тэнхим нь 7 үндсэн багш, 3 цагийн багштай үйл ажиллагаа явуулж байна.', 'https://nmct.edu.mn/departments/chemical')
        self.mech=source('Механик инженерийн тэнхим',
            'Тэнхим нь 4 үндсэн багш, 1 туслах багшийн бүрэлдэхүүнтэй.', 'https://nmct.edu.mn/departments/mechanical')
        self.cs=source('Компьютерын ухааны тэнхим',
            'Тэнхимийн эрхлэгч : Наран', 'https://nmct.edu.mn/departments/computer-science')
        self.home=source('Нүүр хуудас','99+\nБагш нар','https://nmct.edu.mn/')
        self.catalog=[self.chem,self.mech,self.cs,self.home]

    def scope(self,q,rows=None):
        return staff_query_scope(q,self.catalog if rows is None else rows,catalog=self.catalog)

    def test_natural_short_department_names_keep_only_matching_department(self):
        for q,expected in [('Химийн багш хэд байдаг вэ?',self.chem),
                           ('Механикийн багш нар хэд вэ?',self.mech),
                           ('Компьютерийн тэнхимийн эрхлэгч хэн бэ?',self.cs)]:
            with self.subTest(q=q):
                self.assertEqual(self.scope(q)['sources'],[expected])

    def test_count_requires_positive_prose_not_zero_header_or_homepage(self):
        header=source(self.chem['title'],'0 хөтөлбөр\n0 багш',self.chem['url'])
        result=self.scope('Химийн багш хэд байдаг вэ?',[header,self.home])
        self.assertEqual(result['stop'],'staff_count_not_supported')
        result=self.scope('Сургууль нийт хэдэн багштай вэ?')
        self.assertEqual(result['stop'],'clarify_staff_scope')
        self.assertNotIn(self.home,result['sources'])

    def test_names_do_not_accept_counts_heads_or_award_participants(self):
        result=self.scope('Химийн багш нарын нэрсийг өгөөч.')
        self.assertEqual(result['stop'],'staff_names_not_supported')
        self.assertEqual(result['sources'],[self.chem])

    def test_named_teacher_needs_role_assertion_not_student_patronymic(self):
        award=source('Амжилт','Оюутан Дорж овогтой Болд тэмцээнд түрүүлсэн.','https://nmct.edu.mn/news/prize')
        other=source('Багшийн нэг өдөр','Наран багшийн ажлын өдөр.','https://nmct.edu.mn/news/day')
        result=self.scope('Дорж багшийн тухай мэдээлэл өгөөч.',[award,other])
        self.assertEqual(result['stop'],'unsupported_person')
        self.assertEqual(result['sources'],[])
        true=source('Багшийн танилцуулга','Дорж багш роботын сургалт заадаг.','https://nmct.edu.mn/news/teacher')
        result=self.scope('Дорж багш ямар хичээл заадаг вэ?',[award,other,true])
        self.assertEqual(result['sources'],[true])
        self.assertNotIn('stop',result)
        mixed=self.scope('Дорж багш болон Наран багшийн тухай мэдээлэл өгөөч.',[true,other])
        self.assertEqual(mixed['stop'],'clarify_staff_scope')
        self.assertEqual(mixed['sources'],[])

    def test_person_case_fullname_and_role_cannot_be_discarded(self):
        wrong=source('Багш','Батын Болд багш компьютерийн сүлжээ заадаг.','https://nmct.edu.mn/news/teacher')
        false_role=source('Сургууль','Болд захиргааны ажилтан бөгөөд багш Наран хичээл заадаг.','https://nmct.edu.mn/news/staff')
        wrong_initial=source('Багш','Г.Болд багш сүлжээ заадаг.','https://nmct.edu.mn/news/initial')
        for q,rows in [('болд багш ямар хичээл заадаг вэ?',[false_role]),
                       ('БОЛД БАГШ ЯМАР ХИЧЭЭЛ ЗААДАГ ВЭ?',[false_role]),
                       ('Доржийн Болд багш ямар хичээл заадаг вэ?',[wrong]),
                       ('Б.Болд багш ямар хичээл заадаг вэ?',[wrong_initial])]:
            result=self.scope(q,rows)
            self.assertEqual(result['stop'],'unsupported_person',q)
            self.assertEqual(result['sources'],[])
        true=source('Багш','Доржийн Болд багш сүлжээ заадаг.','https://nmct.edu.mn/news/full')
        self.assertEqual(self.scope('Доржийн Болд багш ямар хичээл заадаг вэ?',[wrong,true])['sources'],[true])
        self.assertIsNone(self.scope('ямар багш вэ?').get('person'))

    def test_conditional_or_unverified_staff_count_is_not_positive_prose(self):
        for text in ['Тэнхимийн 17 багштай байх тухай мэдээлэл батлагдаагүй.',
                     'Хэрэв 17 багштай байвал тэнхимийн үйл ажиллагааг эхлүүлнэ.',
                     'Тэнхим нь 17 багштай үйл ажиллагаа явуулдаг гэсэн таамаг бий.']:
            self.assertEqual(staff_count_spans(text),[],text)

    def test_count_does_not_fill_age_or_salary_question(self):
        for q in ['Химийн багш хэдэн настай вэ?','Химийн багш хэдэн төгрөгийн цалинтай вэ?']:
            result=self.scope(q)
            self.assertEqual(result['stop'],'staff_attribute_not_supported',q)
            self.assertEqual(result['sources'],[])
            self.assertIsNone(field_extract(q,self.catalog),q)

    def test_multiple_departments_are_not_collapsed_to_first(self):
        result=self.scope('Химийн болон механикийн тэнхимийн багшийн тоог харьцуулна уу.')
        self.assertEqual(set(result['department_titles']),{self.chem['title'],self.mech['title']})
        self.assertEqual(result['sources'],[self.chem,self.mech])
        self.assertIsNone(field_extract('Химийн болон механикийн тэнхимийн багшийн тоог харьцуулна уу.',self.catalog))

    def test_short_name_must_be_unique_in_whole_catalog_not_retrieved_pool(self):
        another=source('Химийн технологийн тэнхим','Өөр тэнхим','https://nmct.edu.mn/departments/other')
        result=staff_query_scope('Химийн багш хэд вэ?',[self.chem],catalog=self.catalog+[another])
        self.assertFalse(result['department_titles'])
        self.assertEqual(result['stop'],'clarify_staff_scope')

    def test_closed_count_copies_actual_paragraph_with_no_answer_constants(self):
        for q,row in [('Химийн багш хэд байдаг вэ?',self.chem),('Механикийн багш нар хэд вэ?',self.mech)]:
            self.assertEqual(field_extract(q,self.catalog),(row,row['text']))
        for q in ['Химийн багш хэд вэ, цалин нь хэд вэ?',
                  'Химийн багш хэд вэ, мөн нэрсийг хэлнэ үү?',
                  '2030 онд Химийн багш хэд вэ?']:
            self.assertIsNone(field_extract(q,self.catalog),q)

    def test_generic_overview_does_not_require_picture_intent(self):
        for q in ['Багш нар','Багш нарын талаар мэдээлэл өгөөч.',
                  'Багш нарынхаа талаар мэдээлэл өгөөч.']:
            self.assertTrue(_generic_staff_overview(q),q)
        for q in ['Дорж багшийн тухай','Химийн багшийн цалин','Багш нар Японд хэзээ явах вэ?']:
            self.assertFalse(_generic_staff_overview(q),q)

    def test_partial_directory_does_not_drop_compound_unknown_fields(self):
        title='Компьютерын ухааны тэнхим'
        self.assertTrue(_directory_only('Компьютерийн багш нар хэн хэн байдаг вэ?',title))
        self.assertTrue(_directory_only('Компьютерын ухааны тэнхимийн багш нарын нэрийг хэлнэ үү.',title))
        for q in ['Компьютерийн болон химийн багш нарын нэрийг хэлнэ үү.',
                  'Компьютерийн багш хэд вэ, нэрсийг хэл.',
                  'Компьютерийн Дорж багшийн нэрийг хэл.',
                  'Компьютерийн багш нарын цалин болон нэрсийг хэл.']:
            self.assertFalse(_directory_only(q,title),q)


class CafeteriaHoursTests(unittest.TestCase):
    def test_opening_hours_are_distinct_from_capacity_and_other_offices(self):
        q='Цайны газар хэдээс хэд хүртэл ажилладаг вэ?'
        self.assertEqual(requested_detail(q),'cafeteria_opening_hours')
        for text in ['Цайны газар\n400 м² талбайтай, 360 суудалтай.',
                     'Цайны газар\nНомын сан Даваа - Баасан 09:00 - 18:00 ажиллана.',
                     'Цайны газар\nЗахиргааны ажлын цаг Даваа - Баасан 09:00 - 18:00.',
                     'Цайны газар 09:00 - 18:00 ажилладаг гэсэн мэдээлэл тодорхойгүй.']:
            self.assertFalse(detail_supported('cafeteria_opening_hours',text,q),text)
        for text in ['Цайны газар Даваа - Баасан 09:00 - 18:00 ажиллана.',
                     'Цайны газар\nДаваа - Баасан: 09:00 - 18:00']:
            self.assertTrue(detail_supported('cafeteria_opening_hours',text,q),text)

    def test_requested_day_is_not_replaced_by_other_days(self):
        text='Цайны газар\nДаваа - Баасан: 09:00 - 18:00'
        self.assertFalse(detail_supported('cafeteria_opening_hours',text,'Цайны газар бямба гарагт хэдээс ажилладаг вэ?'))

    def test_opening_clock_inflection_does_not_accept_floor_area_or_seats(self):
        for q in ['Хоолны газар өглөө хэдэн цагт нээгддэг вэ?',
                  'Цайны газар хэдэн цагт нээдэг вэ?',
                  'Хоолны газар хэдэн цагт нээх вэ?']:
            self.assertEqual(requested_detail(q),'cafeteria_opening_hours',q)
            self.assertFalse(detail_supported('cafeteria_opening_hours','Хоолны газар\n400 м²\n360 суудал',q))
            self.assertTrue(detail_supported('cafeteria_opening_hours','Хоолны газар 08:30 цагт нээгддэг.',q))

    def test_natural_closing_clock_question_requires_own_confirmed_schedule(self):
        q='Цайны газар орой хэдэд хаадаг юм бэ?'
        self.assertEqual(requested_detail(q),'cafeteria_opening_hours')
        self.assertTrue(detail_supported('cafeteria_opening_hours','Цайны газар 18:30 цагт хаадаг.',q))
        for text in ['Цайны газар\n400 м² талбай, 360 суудалтай.',
                     'Цайны газар\nЗахиргаа Даваа - Баасан 09:00 - 18:00 ажиллана.',
                     'Цайны газар 18:30 цагт хаадаг гэсэн мэдээлэл батлагдаагүй.',
                     'Хэрэв хичээлтэй байвал цайны газар 18:30 цагт хаадаг.']:
            self.assertFalse(detail_supported('cafeteria_opening_hours',text,q),text)
        self.assertFalse(detail_supported('cafeteria_opening_hours',
            'Цайны газар\nДаваа - Баасан 09:00 - 18:00',q+' Бямба гарагт асууж байна.'))


class NamedStaffContactTests(unittest.TestCase):
    query='Механикийн тэнхимийн Б.Болд багштай цахимаар яаж холбоо барих вэ?'
    card='Тэнхимийн эрхлэгч\nБ.Болд\nИмэйл bold-test@example.edu\nУтас 99112233'

    def setUp(self):
        self.own=source('Механик инженерийн тэнхим','Холбоо барих\n'+self.card,'https://nmct.edu.mn/departments/mechanical')
        self.header=source(self.own['title'],'Тэнхимийн эрхлэгч : Б.Болд\n1 хөтөлбөр\n0 багш',self.own['url'])
        self.other=source(self.own['title'],'Холбоо барих\nТэнхимийн эрхлэгч\nГ.Наран\nИмэйл naran-test@example.edu',self.own['url'])

    def test_contact_requires_own_complete_record_not_matching_header(self):
        scoped=staff_query_scope(self.query,[self.header,self.other,self.own])
        self.assertEqual(scoped['sources'],[self.own])
        self.assertNotIn('stop',scoped)
        requirements=field_evidence_requirements(self.query)
        self.assertEqual([req['name'] for req in requirements],['staff_contact_email'])
        self.assertEqual(missing_field_evidence(requirements,self.header['text']),['staff_contact_email'])
        self.assertEqual(missing_field_evidence(requirements,self.other['text']),['staff_contact_email'])
        self.assertEqual(missing_field_evidence(requirements,self.card),[])
        self.assertEqual(field_extract(self.query,[self.header,self.other,self.own]),
            (self.own,self.card.rsplit('\n',1)[0]))

    def test_fullname_and_initial_must_match_the_contact_record(self):
        for q in [self.query.replace('Б.Болд','Г.Болд'),self.query.replace('Б.Болд','Доржийн Болд')]:
            scoped=staff_query_scope(q,[self.own,self.header])
            self.assertEqual(scoped['stop'],'staff_contact_not_supported',q)
            self.assertEqual(scoped['sources'],[])
            self.assertIsNone(field_extract(q,[self.own,self.header]),q)

    def test_wrong_contact_channel_and_next_person_do_not_supply_email(self):
        phone=source(self.own['title'],'Тэнхимийн эрхлэгч\nБ.Болд\nУтас 99112233\nБагш\nГ.Наран\nИмэйл naran-test@example.edu',self.own['url'])
        scoped=staff_query_scope(self.query,[phone])
        self.assertEqual(scoped['stop'],'staff_contact_not_supported')
        self.assertEqual(missing_field_evidence(field_evidence_requirements(self.query),phone['text']),['staff_contact_email'])
        cards=staff_contact_cards(phone['text'])
        self.assertEqual([card['person'] for card in cards],['Б.Болд','Г.Наран'])

    def test_extra_requested_attribute_is_not_dropped_by_direct_lookup(self):
        self.assertIsNone(field_extract(self.query.rstrip('?')+', мөн цалин нь хэд вэ?',[self.own]))

    def test_online_teaching_does_not_mean_teacher_email(self):
        q='Б.Болд багш цахим сургалтаар ямар хичээл заадаг вэ?'
        self.assertEqual(field_evidence_requirements(q),[])
        self.assertIsNone(field_extract(q,[self.own]))


if __name__=='__main__':unittest.main()
