import copy
import unittest
from test_rag_runtime import SOURCE, Policy, Retriever, Generator
from rag_runtime import ChatRAG, source_extract, focused_extract
from source_fields import ambiguity, detail_supported, requested_detail


def source(text, visual=False, **extra):
    return dict(copy.deepcopy(SOURCE), text=text, excerpt=text,
                text_scope='document_visual_excerpt' if visual else 'main_element', **extra)


class SourceFieldTests(unittest.TestCase):
    def test_written_comparison_never_uses_interview_only_rule(self):
        written=source('Бичгийн шалгалт\n1-р курс — 120 минут\nНийт 100 оноотой шалгалт\nМатематик 40 оноо\nЯрилцлага 20 оноо')
        interview=source('Ярилцлагын шалгалт 15 минут үргэлжилнэ. Нийт 20 оноо.', True)
        q='Бичгийн шалгалтын нийт оноо хэд вэ? Ярилцлагын онооноос ялгаж хэл.'
        self.assertIsNone(focused_extract(q,[interview]))
        answer=source_extract(q,[interview,written])[1]
        self.assertIn('Нийт 100',answer)
        self.assertIn('Ярилцлага 20',answer)
        self.assertNotIn('120 оноо',answer)

    def test_written_duration_is_not_interview_duration(self):
        written=source('Бичгийн шалгалт\n1-р курс — 120 минут\nНийт 100 оноотой шалгалт\nЯрилцлага 20 оноо')
        self.assertIn('120 минут',source_extract('Бичгийн шалгалтын хугацаа?', [written])[1])

    def test_foreign_documents_keep_both_requirements_not_grade(self):
        grade=source('1-р курст Бүртгүүлэгч нь 9-р анги төгссөн.',True)
        doc=source('Гадаад оронд ерөнхий боловсрол эзэмшсэн сурагч шалгалт өгснийг гэрчилсэн баримт, БШУЯ-наас баталгаажуулсан тодорхойлолтыг хамт ирүүлнэ.',True)
        self.assertEqual(source_extract('Гадаадад ЕБС төгссөн хүнд ямар баримт хэрэгтэй вэ?',[grade,doc]),(doc,doc['text']))
        self.assertIsNone(source_extract('Гадаад оюутны төлбөр хэд вэ?',[doc]))
        self.assertIsNone(source_extract('Гадаадад их сургууль төгссөн хүний баримт юу вэ?',[doc]))

    def test_font_and_word_count_are_distinct_and_real_font_can_be_supported(self):
        self.assertEqual(requested_detail('Эссэг ямар фонтын хэдэн пунктээр хэвлэх вэ?'),'essay_font')
        self.assertFalse(detail_supported('essay_font','Эссэ A4 цаасан дээр 500-700 үгтэй байна.'))
        self.assertTrue(detail_supported('essay_font','Эссэний фонт Arial, 12 пункт байна.'))

    def test_sql_hours_require_query_unit_with_sql_not_programme_years(self):
        self.assertFalse(detail_supported('sql_weekly_hours','SQL ашиглах чадвар. Хөтөлбөр 5 жил. Долоо хоногт 4 цаг спорт.'))
        self.assertTrue(detail_supported('sql_weekly_hours','SQL хичээл долоо хоногт 3 цаг орно.'))
        self.assertFalse(detail_supported('sql_weekly_hours','SQL чадвар\nДолоо хоногт 3 цаг спорт.'))

    def test_annual_fee_does_not_support_instalment_schedule(self):
        self.assertFalse(detail_supported('tuition_instalments','Сургалтын төлбөр жилд 8,280,000 ₮.'))
        self.assertTrue(detail_supported('tuition_instalments','Сургалтын төлбөрийг сар бүр 100 төгрөгөөр хувааж төлөх хуваарьтай.'))

    def test_generic_fee_and_duration_are_not_special_group_values(self):
        annual=source('Сургалтын төлбөр: жилд 8,280,000 ₮.')
        duration=source('ШМТК нь инженерийн 5 жилийн хөтөлбөрөөр дэд бакалаврын зэрэг олгодог.',True)
        for group in ['Химийн инженерийн','Гадаад сурагчийн','Дотуур байртай сурагчийн']:
            self.assertIsNone(source_extract(group+' сургалтын төлбөр жилд хэд вэ?',[annual]))
        self.assertIsNone(source_extract('Шилжин элсэх химийн инженерийн хөтөлбөр хэдэн жил вэ?',[duration]))

    def test_photo_recency_is_not_file_megabytes(self):
        self.assertFalse(detail_supported('photo_file_size','Сүүлийн 6 сарын цээж зургийг JPEG файлаар оруулна.'))
        self.assertTrue(detail_supported('photo_file_size','Цээж зургийн файл 2 MB-аас ихгүй байна.'))

    def test_ambiguity_respects_named_exam_type(self):
        sources=[source('Бичгийн шалгалт 120 минут. Ярилцлага 15 минут.')]
        self.assertIsNotNone(ambiguity('Шалгалт хэдэн минут вэ?',sources))
        self.assertIsNone(ambiguity('Бичгийн шалгалт хэдэн минут вэ?',sources))
        self.assertIsNotNone(ambiguity('Шалгалтын дүнг хаанаас харах вэ?',sources))
        self.assertIsNone(ambiguity('Элсэлтийн нэгдсэн дүн хаана гарах вэ?',sources))

    def test_olympiad_category_is_requested_before_award_lookup(self):
        sources=[source('Математик-физик. Математик-хими-биологи.')]
        self.assertIsNotNone(ambiguity('Олимпиадын хоёрдугаар байрт хэдэн сурагч вэ?',sources))
        self.assertIsNone(ambiguity('Математик-физикийн олимпиадын хоёрдугаар байрт хэд вэ?',sources))

    def test_missing_sql_hours_has_no_llm_call(self):
        retriever,generator=Retriever(),Generator()
        retriever.sources=[source('SQL ур чадвар. Хөтөлбөр 5 жил.')]
        chat=ChatRAG('.',Policy(),retriever,generator)
        result=chat.route(None,'SQL-ийг долоо хоногт хэдэн цаг үзэх вэ?')
        self.assertEqual(result['reason_code'],'requested_attribute_not_supported')
        self.assertEqual(generator.calls,0)

    def test_ambiguity_has_no_llm_call(self):
        retriever,generator=Retriever(),Generator()
        retriever.sources=[source('Бичгийн шалгалт 120 минут. Ярилцлага 15 минут.')]
        result=ChatRAG('.',Policy(),retriever,generator).route(None,'Шалгалт хэдэн минут вэ?')
        self.assertEqual(result['route'],'D')
        self.assertEqual(generator.calls,0)

    def test_faq_year_absence_reaches_dated_web_but_not_unsupported_year(self):
        retriever,generator=Retriever(),Generator()
        retriever.sources=[source('Олимпиадад оролцогчдыг 2026 оны 04-р сарын 2-ноос бүртгэнэ.',True)]
        chat=ChatRAG('.',Policy(reason='unsupported_year'),retriever,generator)
        result=chat.route(None,'2026 оны олимпиадын бүртгэл хэднээс явсан вэ?')
        self.assertEqual(result['route'],'A')
        self.assertEqual(result['faq_scope_handoff']['reason_code'],'unsupported_year')
        self.assertEqual(chat.route(None,'2028 оны олимпиадын бүртгэл хэднээс явсан вэ?')['reason_code'],'requested_year_not_supported')
        self.assertEqual(generator.calls,0)

    def test_essay_medium_keeps_prohibition(self):
        essay=source('Анхаарах: Эссэгээ A4 цаасан дээр хэвлээд авч ирнэ. Гараар бичсэн эссэ хүлээн авахгүй.')
        self.assertIn('хүлээн авахгүй',source_extract('Эссэг гараар бичээд авч ирэх үү?',[essay])[1])

    def test_roman_second_course_is_not_first_course(self):
        programmes=source('1-р курс · 5 жил\n071309 Цахилгааны инженер\n2-р курс шилжин · 4 жил\n071501 Механик инженер\nБичгийн шалгалт')
        answer=source_extract('II курсийн хөтөлбөрийн индекс юу вэ?',[programmes])[1]
        self.assertIn('071501',answer)
        self.assertNotIn('071309',answer)

    def test_year_handoff_does_not_replace_office_phone_with_general_phone(self):
        retriever,generator=Retriever(),Generator()
        retriever.sources=[source('2026 оны сургуулийн ерөнхий утас 75777799.')]
        result=ChatRAG('.',Policy(reason='unsupported_year'),retriever,generator).route(None,'2026 оны элсэлтийн албаны утас хэд вэ?')
        self.assertEqual(result['reason_code'],'requested_attribute_not_supported')
        self.assertEqual(generator.calls,0)

    def test_multiple_unrelated_fields_are_not_claimed_complete(self):
        self.assertIsNotNone(ambiguity('Гадаадад ЕБС төгссөн хүний баримт болон ярилцлагын оноог хэл.',[]))

    def test_bank_permission_and_essay_topics_use_inflected_word_forms(self):
        bank=source('Цахимаар бүртгэл хийхдээ бүртгэлийн хураамжийг QR кодоор Төрийн банкны апп ашиглан төлнө. Голомт банкаар төлөх боломжгүй.',True)
        topics=source('Бүртгүүлэгч бичгийн шалгалтад ирэхдээ дараах асуултад хариулж хэвлэмэл байдлаар авч ирнэ.\nКоосэнд суралцах болсон шалтгаан\nМэргэжил сонгосон шалтгаан\nӨөрийн сонирхол',True)
        self.assertEqual(source_extract('Төрийн банкны апп ашиглаад элсэлтийн QR хураамж төлж болох уу?',[bank]),(bank,bank['text']))
        self.assertEqual(source_extract('Элсэлтийн эссэд хариулах сэдвүүд юу вэ?',[topics]),(topics,topics['text']))

    def test_registration_confirmation_fee_is_not_enrolment_contract(self):
        confirmation=source('Элсэгч сургуулиас товлосон хугацаанд суралцах гэрээ байгуулан, сургалтын төлбөрийг төлсний дараа элсэн суралцах баталгаажна.',True)
        fee=source('Цахимаар бүртгэл хийхдээ бүртгэлийн хураамж 20,000 төгрөгийг QR код ашиглан төлнө.',True)
        question='Элсэлтийн бүртгэлээ баталгаажуулах хураамж нь сургалтын төлбөрөөс тусдаа хэдэн төгрөг вэ?'
        self.assertEqual(requested_detail(question),'registration_amount')
        self.assertFalse(detail_supported('registration_amount',confirmation['text']))
        self.assertEqual(source_extract(question,[confirmation,fee]),(fee,fee['text']))
        retriever,generator=Retriever(),Generator()
        retriever.sources=[confirmation,fee]
        from unittest.mock import patch
        with patch.object(retriever,'search',wraps=retriever.search) as search:
            result=ChatRAG('.',Policy(),retriever,generator).route(None,question)
        self.assertEqual(search.call_args.kwargs['limit'],10)
        self.assertIn('20,000',result['answer'])
        self.assertEqual(generator.calls,0)

    def test_missing_acronym_does_not_turn_weekly_hours_into_programme_years(self):
        q='Компьютерийн ухааны хөтөлбөрт зүйг долоо хоногт хэдэн цаг үзэх вэ?'
        self.assertEqual(requested_detail(q),'course_weekly_hours')
        retriever,generator=Retriever(),Generator()
        retriever.sources=[source('Компьютерийн хөтөлбөр 5 жил. Программчлалын чадвар олгоно.')]
        result=ChatRAG('.',Policy(),retriever,generator).route(None,q)
        self.assertEqual(result['reason_code'],'requested_attribute_not_supported')
        self.assertEqual(generator.calls,0)
        self.assertTrue(detail_supported('course_weekly_hours','Хичээл долоо хоногт 3 цаг орно.'))

    def test_recognition_typo_is_clarified_not_silently_rewritten(self):
        q='эсэлтийн бүртгэлийн хураамч хэдэн төгрөг вэ'
        self.assertIsNotNone(ambiguity(q,[]))
        self.assertIsNone(ambiguity('Элсэлтийн бүртгэлийн хураамж хэд вэ?',[]))
        self.assertIsNotNone(ambiguity('Гадаадад ерөнхий боловсрол эзэмшсэн элсэгч ямар байранд бүрдүүлэх вэ?',[]))
        self.assertIsNone(ambiguity('Гадаадад ерөнхий боловсрол эзэмшсэн элсэгч ямар баримт бүрдүүлэх вэ?',[]))


if __name__=='__main__': unittest.main()
