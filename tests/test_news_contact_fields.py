"""Constructed announcement fields; values do not describe an actual school."""
import unittest
from source_fields import (field_evidence_requirements, missing_field_evidence,
                           source_bound_field_requirements)
from rag_runtime import admission_announcement_sources

Q='2038 оны нэгдүгээр сард зарласан нэмэлт элсэлт хэдний өдөр хүртэл үргэлжилсэн бэ? Тэр зар дээр лавлах ямар утаснууд байсан бэ?'
DEADLINE='Сул суудлын нэмэлт элсэлтээ 1 сарын 23-ны өдрийг дуустал зарлаж байна.'
PHONE='76543210, 88001122 утсаар холбогдон дэлгэрэнгүй мэдээлэл авна уу.'


class NewsContactFieldsTests(unittest.TestCase):
    def fields(self):
        return [f for f in field_evidence_requirements(Q) if f['type']=='announcement_field']

    def test_both_fields_are_required_and_no_phone_or_date_values_are_in_code(self):
        fields=self.fields()
        self.assertEqual({f['field'] for f in fields},{'phone','deadline'})
        self.assertEqual(missing_field_evidence(fields,[DEADLINE,PHONE]),[])

    def test_either_omitted_field_blocks_full_answer(self):
        self.assertEqual(missing_field_evidence(self.fields(),[DEADLINE]),['announcement_contact_phone'])
        self.assertEqual(missing_field_evidence(self.fields(),[PHONE]),['announcement_deadline'])

    def test_values_and_formatted_phone_are_source_derived(self):
        self.assertEqual(missing_field_evidence(self.fields(),[
            DEADLINE.replace('1 сарын 23','11 сарын 7'),PHONE.replace('76543210','1234-5678').replace('88001122','99887766')]),[])

    def test_arbitrary_digits_retracted_contact_and_publication_date_are_not_fields(self):
        for text in ('20380112 нийтэлсэн мэдээ.',
                     PHONE+' Энэ мэдээллийг үгүйсгэсэн.',
                     'Бүртгэл дуусах өдөр тодорхойгүй. 2038-01-12-нд нийтлэв.'):
            self.assertTrue(missing_field_evidence(self.fields(),[text]))

    def test_general_information_and_contact_do_not_become_announcement_scope(self):
        fields=field_evidence_requirements('Сургуулийн мэдээлэл авах утас хэд вэ?')
        self.assertFalse(any(f['type']=='announcement_field' for f in fields))


class AnnouncementArticleScopeTests(unittest.TestCase):
    numeric='2038 оны 1 сарын нэмэлт элсэлтийн зарын бүртгэл дуусах өдөр болон холбоо барих бүх утсыг хэлнэ үү.'
    written='2038 оны нэгдүгээр сарын нэмэлт элсэлтэд хэдний өдөр хүртэл бүртгэсэн, зар дээрх лавлах хоёр дугаар юу байсан бэ?'

    def source(self, sid, topic, body, *, month='нэгдүгээр', day=7, version=1):
        return dict(source_id=sid,url='https://nmct.edu.mn/news/'+sid,version=version,title=topic,
                    text=f'{topic}\n2038 оны {month} сарын {day} 17 үзсэн\n{body}')

    def setUp(self):
        self.target=self.source('supplement','НЭМЭЛТ ЭЛСЭЛТ',DEADLINE+'\n'+PHONE)
        self.other=self.source('jobs','АЖЛЫН ШАЛГАЛТ',
            'Ажлын ур чадварын шалгалтын бүртгэл 1 сарын 27-ны өдрийг дуустал үргэлжилнэ.\n'
            'Холбоо барих утас 11335577.',day=9)

    def test_phone_and_deadline_synonyms_require_both_fields(self):
        for query in (self.numeric,self.written,self.numeric.replace('дуусах өдөр','эцсийн өдрийг')):
            with self.subTest(query=query):
                fields=field_evidence_requirements(query)
                self.assertEqual({item['name'] for item in fields},
                                 {'announcement_contact_phone','announcement_deadline'})
                self.assertEqual(missing_field_evidence(fields,[DEADLINE,PHONE]),[])

    def test_same_month_other_event_cannot_supply_notice_deadline(self):
        for query in (self.numeric,self.written):
            with self.subTest(query=query):
                self.assertEqual(admission_announcement_sources(query,[self.other,self.target]),[self.target])

    def test_other_article_related_headline_and_footer_do_not_identify_notice(self):
        for changed in [dict(self.other,text=self.other['text']+'\n'+DEADLINE+'\n'+PHONE),
                        dict(self.other,title='Бүртгэлийн мэдээлэл',text=self.other['text']+'\nХолбоотой мэдээ\n'+DEADLINE),
                        dict(self.other,title='Бүртгэлийн мэдээлэл',text=self.other['text']+'\n«'+DEADLINE+'» гэсэн холбоос байна.'),
                        dict(self.other,title='',text=self.other['text']+'\n'+DEADLINE)]:
            with self.subTest(title=changed['title'],text=changed['text']):
                self.assertEqual(admission_announcement_sources(self.numeric,[changed,self.target]),[self.target])

    def test_requested_phone_count_and_all_source_phones_are_preserved(self):
        source=dict(self.target,text=self.target['text'].replace(PHONE,
            '76543210 утсаар холбогдоно уу.\nЛавлах утас 88001122.'))
        for query in (self.numeric,self.written):
            with self.subTest(query=query):
                fields=source_bound_field_requirements(query,[source])
                self.assertIn('announcement_contact_phone',missing_field_evidence(fields,[DEADLINE,'Утас 76543210.']))
                self.assertEqual(missing_field_evidence(fields,[DEADLINE,'Утас 76543210.','Утас 88001122.']),[])

    def test_all_source_phone_binding_does_not_pool_distinct_articles(self):
        fields=source_bound_field_requirements(self.numeric,[self.target,self.other])
        phone=next(item for item in fields if item['field']=='phone')
        self.assertNotIn('required_phones',phone)

    def test_month_year_and_body_dates_do_not_replace_publication_identity(self):
        for changed in [dict(self.target,text=self.target['text'].replace('2038 оны','2037 оны')),
                        dict(self.target,text=self.target['text'].replace('нэгдүгээр сарын','хоёрдугаар сарын')),
                        dict(self.target,text='Энэ мэдээ 2038 оны нэгдүгээр сарын 7-нд болсон үйл явдалтай холбоотой.\n'+DEADLINE+'\n'+PHONE)]:
            with self.subTest(text=changed['text']):
                self.assertEqual(admission_announcement_sources(self.numeric,[self.other,changed]),[])

    def test_ambiguous_articles_or_versions_never_mix(self):
        other_notice=self.source('another','НЭМЭЛТ ЭЛСЭЛТ',DEADLINE+'\n'+PHONE,day=9)
        other_version=dict(self.target,version=2,source_id='version-two')
        for second in (other_notice,other_version):
            with self.subTest(second=second):
                self.assertEqual(admission_announcement_sources(self.numeric,[self.target,second]),[])

    def test_same_page_continuation_can_supply_its_own_phone(self):
        main=dict(self.target,text=self.target['text'].replace(PHONE,''))
        continuation=dict(self.target,source_id='continuation',text=PHONE)
        self.assertEqual(admission_announcement_sources(self.numeric,[self.other,main,continuation]),[main,continuation])

    def test_ordinary_contact_question_and_unscoped_date_keep_existing_behavior(self):
        for query in ('Сургуулийн утас хэд вэ?',
                      '2038 оны 1 сарын ажлын шалгалтын зарын утас хэд вэ?',
                      'Нэмэлт элсэлтийн зарын утас хэд вэ?'):
            with self.subTest(query=query):
                self.assertEqual(admission_announcement_sources(query,[self.other,self.target]),[self.other,self.target])

    def test_formatted_numbers_compare_by_digits_without_inventing_values(self):
        fields=source_bound_field_requirements(self.numeric,[self.target])
        self.assertEqual(missing_field_evidence(fields,[DEADLINE,'Лавлах утас 7654-3210, 8800 1122.']),[])
        self.assertIn('announcement_contact_phone',missing_field_evidence(fields,[DEADLINE,'Лавлах утас 76543210, 11335577.']))


if __name__=='__main__':unittest.main()
