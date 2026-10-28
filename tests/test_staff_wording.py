"""Constructed staff-role wording regressions, not real accuracy results."""
import unittest
from source_fields import staff_query_scope,field_evidence_requirements,missing_field_evidence,field_extract


def row(title,text,key):
    return dict(title=title,text=text,url='https://nmct.edu.mn/departments/'+key)


class StaffWordingTests(unittest.TestCase):
    def setUp(self):
        self.chem=row('Химийн инженерийн тэнхим','Тэнхим нь 7 үндсэн багш, 3 цагийн багштай.','chem')
        self.general=row('Ерөнхий эрдмийн тэнхим','Анх 6 багштай эхэлсэн. Тэнхим нь 23 багштай.','general')
        self.mech=row('Механик инженерийн тэнхим','Тэнхимийн эрхлэгч : Б.Саруул\nИмэйл saruul@example.org\nУтас 88776655','mech')
        self.catalog=[self.chem,self.general,self.mech]

    def scope(self,query):
        return staff_query_scope(query,self.catalog,catalog=self.catalog)

    def test_qualification_and_ordinal_are_not_person_names(self):
        for query in ('Химийн тэнхимд доктор, магистр зэрэгтэй багш хэд вэ?',
                      'Ерөнхий эрдмийн тэнхимийн анхны багшийн тоог хэлнэ үү.'):
            with self.subTest(query=query):
                result=self.scope(query)
                self.assertIsNone(result['person'])
                self.assertNotIn('stop',result)

    def test_explicit_initial_named_person_is_still_checked(self):
        result=self.scope('Б.Зэрэгтэй багшийн мэдээлэл өгнө үү.')
        self.assertEqual(result['person'],'Б.Зэрэгтэй')
        self.assertEqual(result['stop'],'unsupported_person')

    def test_group_names_do_not_request_teacher_list(self):
        query=('Ерөнхий эрдмийн тэнхимийн багшийн тоо хэд вэ? '
               'Заах аргын нэгдлүүдийн нэрийг хэлнэ үү.')
        result=self.scope(query)
        self.assertEqual(result['kind'],'count')
        self.assertNotIn('stop',result)

    def test_head_name_contact_does_not_require_all_teacher_names(self):
        result=self.scope('Механик инженерийн тэнхимийн эрхлэгчийн нэр, имэйл, утас юу вэ?')
        self.assertEqual(result['kind'],'head')
        self.assertNotIn('stop',result)
        self.assertEqual(result['sources'],[self.mech])

    def test_full_teacher_names_request_still_fails_count_only_source(self):
        for query in ('Химийн тэнхимийн багш нарын нэрсийг өгнө үү.',
                      'Химийн тэнхимийн эрхлэгч болон багш нарын бүх нэрийг хэлнэ үү.'):
            self.assertEqual(self.scope(query)['stop'],'staff_names_not_supported')

    def test_degree_attribute_does_not_add_other_department(self):
        result=self.scope('Химийн инженерийн тэнхимийн багшийн бүрэлдэхүүнийг орон тоо болон эрдмийн зэргээр нь ялгаарай.')
        self.assertEqual(result['department_titles'],[self.chem['title']])
        self.assertEqual(result['sources'],[self.chem])

    def test_multiple_explicit_departments_stay_multiple(self):
        result=self.scope('Химийн болон механикийн тэнхимийн багшийн тоог харьцуулна уу.')
        self.assertEqual(set(result['department_titles']),{self.chem['title'],self.mech['title']})

    def test_shared_confirmation_predicate_still_requires_both_admission_stages(self):
        query='Бүртгэл болон элсэлтийг баталгаажуулах нөхцөлийг харьцуулна уу.'
        fields=field_evidence_requirements(query)
        self.assertEqual({f['stage'] for f in fields if f['type']=='admission_stage'},
                         {'registration','enrolment'})
        only_registration='Бүртгэлийн хураамжийг төлснөөр элсэлтийн бүртгэл баталгаажна.'
        self.assertIn('admission_enrolment_confirmation',missing_field_evidence(fields,only_registration))
        self.assertEqual(field_evidence_requirements('Элсэлтийн бүртгэлийг баталгаажуулах нөхцөл юу вэ?'),[])

    def test_second_sentence_with_bas_keeps_interview_progress_requirement(self):
        query=('ARC-ийн хамтын ажиллагааны хичээлүүдийг нэрлээд аль оны ямар улиралд хэрэгжсэнийг хэлээрэй. '
               'Эхний оюутнууд ажлын ярилцлагад орсон эсэхийг бас тайлбарлаарай.')
        self.assertEqual({f['name'] for f in field_evidence_requirements(query)},
                         {'course_content','job_interview_progress'})
        self.assertIn('job_interview_progress',missing_field_evidence(field_evidence_requirements(query),
            'ARC хамтын ажиллагааны хичээлүүдийг онлайнаар хэрэгжүүлсэн.'))

    def test_closed_head_contact_pair_copies_card_not_navigation(self):
        query='Механик инженерийн тэнхимийн эрхлэгчийн нэр, имэйл хаяг, лавлах утас юу вэ?'
        selected=field_extract(query,[self.mech])
        self.assertIsNotNone(selected)
        self.assertEqual(selected[1],self.mech['text'])
        other=row(self.mech['title'],'Багш : Г.Наран\nИмэйл naran@example.org\nУтас 99887766','mech')
        self.assertEqual(field_extract(query,[other,self.mech])[1],self.mech['text'])
        conflicting=row(self.mech['title'],self.mech['text'].replace('Б.Саруул','Б.Өлзий'),'mech')
        self.assertIsNone(field_extract(query,[self.mech,conflicting]))
        self.assertIsNone(field_extract(query+' Цалин нь хэд вэ?',[self.mech]))

    def test_sufficiency_question_is_not_presentation_scope_exclusion(self):
        query=('Элсэлтийн бүртгэл баталгаажих нөхцөл болон элсэн суралцах баталгаажих '
               'нөхцөл хоёр юугаараа ялгаатай вэ? Бүртгэлийн хураамж төлөх нь дангаараа хангалттай юу?')
        fields=field_evidence_requirements(query)
        self.assertEqual({f['stage'] for f in fields if f['type']=='admission_stage'},
                         {'registration','enrolment'})
        self.assertEqual(field_evidence_requirements(query+' Гэрээний нөхцөлийг хас.'),[])


if __name__=='__main__':unittest.main()
