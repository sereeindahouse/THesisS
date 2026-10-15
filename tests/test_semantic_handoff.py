import unittest
from test_rag_runtime import Policy,Retriever,Generator
from rag_runtime import ChatRAG

class WebsiteHandoffTests(unittest.TestCase):
    def chat(self,reason,text):
        r=Retriever();g=Generator();r.sources[0].update(text=text,excerpt=text,page_header='2026 оны мэдээ')
        return ChatRAG('.',Policy(reason=reason),r,g),r,g

    def test_dated_new_topic_reaches_web_instead_of_unrelated_faq(self):
        c,r,g=self.chat('constrained_wording_not_exact','2026 оны тэтгэлгийн мэдээ. Сарын тэтгэлэг 120,000 иен.')
        value=c.route(None,'2026 оны Сора тэтгэлгийн сарын дүн хэд вэ?')
        self.assertEqual(r.calls,1)
        self.assertIn('faq_scope_handoff',value)

    def test_numeric_handoff_requires_all_numbers_in_one_web_passage(self):
        c,r,g=self.chat('unmatched_numeric_constraints','Дадлагын хугацаа 8–24 хоног.')
        value=c.route(None,'JICA 8–25 хоногийн дадлага ямар вэ?')
        self.assertEqual(r.calls,1);self.assertEqual(g.calls,0)
        self.assertEqual(value['reason_code'],'requested_number_not_supported')

    def test_matching_numbers_allow_full_web_guards(self):
        c,r,g=self.chat('unmatched_numeric_constraints','Дадлагын хугацаа 8–24 хоног.')
        value=c.route(None,'JICA 8–24 хоногийн дадлагын мэдээлэл?')
        self.assertEqual(r.calls,1);self.assertEqual(g.calls,1)

    def test_live_fx_does_not_return_old_approximate_conversion(self):
        c,r,g=self.chat('no_supported_question_match','2026 оны мэдээ. Ойролцоогоор 2,400,000 төгрөг.')
        value=c.route(None,'Ясуда тэтгэлгийн иенийг өнөөдрийн ханшаар төгрөгөөр хэлнэ үү?')
        self.assertEqual(g.calls,0);self.assertIsNone(value['answer'])
        self.assertIn('валютын ханш',value['message'])

    def test_generator_rechecks_selected_field_not_whole_page(self):
        import json
        from unittest.mock import patch
        from evidence_contract import evidence_units
        from rag_runtime import GroundedGenerator
        from test_rag_runtime import SOURCE
        text='CNC лаборатори Даваа - Баасан 09:00 - 18:00 нээлттэй.\nCNC лабораторид нэг удаад 12–16 оюутан ажиллах боломжтой.'
        source=dict(SOURCE,text=text)
        units=evidence_units([source]);self.assertEqual(len(units),2)
        generator=GroundedGenerator('.');generator.model='test'
        def run(unit):
            proposal=dict(insufficient=False,unit_ids=[f'u{units.index(unit)+1}'])
            with patch.object(generator,'status',return_value=dict(available=True)),patch.object(generator,'_request',return_value=dict(done=True,message=dict(content=json.dumps(proposal)))):
                return generator.generate('CNC лаборатори долоо хоногийн ямар өдрүүдэд хэдээс хэд хүртэл нээлттэй вэ?',[source])
        self.assertEqual(run(units[1])['reason'],'requested_field_not_in_selection')
        self.assertTrue(run(units[0])['generated'])

    def test_year_absence_does_not_erase_special_tuition_scope(self):
        for query in ('2026 оны гадаад оюутны сургалтын төлбөр 8,280,000 уу?',
                      '2026 оны сургалтын төлбөрийн хөнгөлөлт хэд вэ?',
                      '2026 оны компьютерийн сургалтын төлбөр 8,280,000 уу?'):
            c,r,g=self.chat('unsupported_year','2026 оны сургалтын төлбөр жилд 8,280,000 ₮.')
            value=c.route(None,query)
            self.assertIsNone(value['answer']);self.assertEqual(r.calls,0);self.assertEqual(g.calls,0)

    def test_compound_exam_duration_needs_both_minutes_not_neighboring_points(self):
        from rag_runtime import source_extract,both_exam_durations_supported
        from test_rag_runtime import SOURCE
        text='Бичгийн шалгалт 140 минут. Ярилцлагын шалгалт 25 оноотой.'
        query='Бичгийн болон ярилцлагын шалгалт тус бүр хэдэн минут үргэлжлэх вэ?'
        self.assertIsNone(source_extract(query,[dict(SOURCE,text=text)]))
        c,r,g=self.chat('no_supported_question_match',text)
        self.assertIsNone(c.route(None,query)['answer']);self.assertEqual(g.calls,0)
        self.assertFalse(both_exam_durations_supported(text))
        self.assertTrue(both_exam_durations_supported(text+' Ярилцлагын шалгалт 18 минут.'))

    def test_rejected_expired_partial_and_exact_match_are_not_handed_off(self):
        for reason in ('expired_content','future_validity','partial_answer','content_rejected_or_unapproved'):
            c,r,g=self.chat(reason,'2026 оны эх. 7 хоног.')
            self.assertEqual(c.route(None,'2026 оны Сора тэтгэлэг 7 хоног уу?')['reason_code'],reason)
            self.assertEqual(r.calls,0)

if __name__=='__main__':unittest.main()
