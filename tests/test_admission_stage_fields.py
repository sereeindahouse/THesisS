"""Constructed confirmation-stage and scope regressions; no school gold."""
import unittest
from source_fields import field_evidence_requirements, missing_field_evidence, direct_lookup_contract, field_search_expansions
from rag_runtime import ChatRAG, source_extract,admission_stage_sources
from test_rag_runtime import Policy, Retriever, Generator, SOURCE

QUERY='Бүртгэл баталгаажих болон элсэн суралцах баталгаажих нөхцөлийг ялгаж өгөөч.'
REGISTER='Хүссэн хөтөлбөрөө сонгон, бүртгэлийн хураамжаа TestPay-ээр төлснөөр элсэлтийн бүртгэл бүрэн баталгаажна.'
ENROL='Элсэгч тогтоосон хугацаанд суралцах гэрээ байгуулан, сургалтын төлбөрийг төлсний дараа элсэн суралцах баталгаажна.'


class AdmissionStageFieldsTests(unittest.TestCase):
    def test_enrolment_comparison_never_borrows_olympiad_payment(self):
        admission=dict(SOURCE,title='Элсэлт',url='https://nmct.edu.mn/elselt',text=REGISTER)
        olympiad=dict(SOURCE,title='Олимпиадын бүртгэл',url='https://nmct.edu.mn/olympiad',text='Бүртгэлийн хураамжийг QR кодоор төлнө.')
        by_title=dict(olympiad,url='https://nmct.edu.mn/news/contest')
        self.assertEqual(admission_stage_sources(QUERY,[admission,olympiad,by_title]),[admission])
        self.assertEqual(admission_stage_sources(QUERY+' Олимпиадынхтай бас харьцуул.',[admission,olympiad]),[admission,olympiad])
        self.assertEqual(admission_stage_sources('Олимпиадын хураамжийг яаж төлөх вэ?',[olympiad]),[olympiad])

    def test_a_direct_clause_cannot_bypass_the_other_requested_stage(self):
        text=ENROL.replace('Элсэгч тогтоосон хугацаанд','Элсэгч сургуулиас товлосон хугацаанд')
        source=dict(SOURCE,text_scope='document_visual_excerpt',text=text,excerpt=text,
                    url='https://nmct.edu.mn/elseltiin-juram/constructed.png')
        self.assertIsNotNone(source_extract('Элсэн суралцах хэзээ баталгаажих вэ?',[source]))
        self.assertIsNone(source_extract(QUERY,[source]))

    def test_stage_expansion_is_bounded_to_explicit_comparison(self):
        expansions=field_search_expansions(QUERY)
        self.assertEqual([item['requirement']['stage'] for item in expansions],['registration','enrolment'])
        self.assertEqual(field_search_expansions('Бүртгэлийн хураамж хэд вэ?'),[])
        self.assertEqual(field_search_expansions('Элсэх талаар мэдээлэл өгнө үү.'),[])
        self.assertTrue(all('source_id' not in item for item in expansions))

    def test_retrieval_only_adds_field_supported_official_candidates(self):
        registration=dict(SOURCE,source_id='fixture-register',text=REGISTER,excerpt=REGISTER)
        enrolment=dict(SOURCE,source_id='fixture-enrolment',text=ENROL,excerpt=ENROL)
        unrelated=dict(SOURCE,source_id='fixture-unrelated',text='Өөр гэрээ ба төлбөр.',excerpt='Өөр гэрээ ба төлбөр.')
        external=dict(enrolment,source_id='fixture-external',url='https://unrelated.example/rule')
        class FacetRetriever(Retriever):
            def search(self,query,limit=5):
                candidates=[registration] if query==QUERY else [unrelated,enrolment,external]
                return dict(candidates=candidates,corpus_id='fixture-corpus',backend='fixture')
        class NoGeneration(Generator):
            def generate(self,query,sources):
                return dict(generated=False,reason='fixture_only',claims=[],llm_calls=0)
        result=ChatRAG('.',Policy(),FacetRetriever(),NoGeneration()).route(None,QUERY)
        sources=result['rag']['retrieved_sources']
        self.assertEqual([item['source_id'] for item in sources],['fixture-enrolment','fixture-register'])
        self.assertEqual(missing_field_evidence(field_evidence_requirements(QUERY),[item['text'] for item in sources]),[])
        self.assertEqual(len(result['rag']['field_query_expansion']),2)

    def test_field_search_never_mixes_corpus_versions(self):
        class ChangingRetriever(Retriever):
            def search(self,query,limit=5):
                return dict(candidates=[],corpus_id='first' if query==QUERY else 'second',backend='fixture')
        result=ChatRAG('.',Policy(),ChangingRetriever(),Generator()).route(None,QUERY)
        self.assertEqual(result['route'],'E')
        self.assertEqual(result['reason_code'],'website_search_unavailable')

    def test_supplement_caps_preserve_all_primary_rows_and_both_missing_roles(self):
        originals=[dict(SOURCE,source_id=f'original-{index}',text='Өөр мэдээлэл.') for index in range(5)]
        registration=[dict(SOURCE,source_id=f'registration-{index}',text=REGISTER) for index in range(5)]
        enrolment=[dict(SOURCE,source_id=f'enrolment-{index}',text=ENROL) for index in range(5)]
        class ManySources(Retriever):
            def search(self,query,limit=5):
                rows=originals if query==QUERY else enrolment if 'суралцах гэрээ' in query else registration
                return dict(candidates=rows,corpus_id='fixed-fixture',backend='fixture')
        class NoGeneration(Generator):
            def generate(self,query,sources):
                return dict(generated=False,reason='fixture_only',claims=[],llm_calls=0)
        result=ChatRAG('.',Policy(),ManySources(),NoGeneration()).route(None,QUERY)
        ids=[item['source_id'] for item in result['rag']['retrieved_sources']]
        self.assertEqual(ids,['registration-0','registration-1','enrolment-0','enrolment-1']+[item['source_id'] for item in originals])
        self.assertTrue(all(len(item['supplemental_source_ids'])==2 for item in result['rag']['field_query_expansion']))

    def test_both_stages_are_requested_without_answer_values(self):
        fields=field_evidence_requirements(QUERY)
        self.assertEqual([x['name'] for x in fields],['admission_registration_confirmation','admission_enrolment_confirmation'])
        self.assertEqual(missing_field_evidence(fields,[REGISTER,ENROL]),[])

    def test_registration_fee_is_not_enrolment_confirmation(self):
        fields=field_evidence_requirements(QUERY)
        self.assertEqual(missing_field_evidence(fields,[REGISTER]),['admission_enrolment_confirmation'])
        self.assertEqual(missing_field_evidence(fields,[ENROL]),['admission_registration_confirmation'])

    def test_payment_provider_and_money_values_are_not_hardcoded(self):
        for provider in ('OtherPay','ЦахимШилжүүлэг'):
            text=REGISTER.replace('TestPay',provider)
            self.assertEqual(missing_field_evidence(field_evidence_requirements(QUERY),[text,ENROL]),[])

    def test_unrelated_contract_or_payment_does_not_complete_enrolment(self):
        fields=field_evidence_requirements(QUERY)
        for text in ('Суралцах гэрээ байгуулна. Сургалтын төлбөрийн мэдээлэл байна.',
                     'Элсэн суралцах баталгаажна. Номын сангийн төлбөрийг төлсний дараа гэрээ байгуулна.',
                     ENROL.replace('сургалтын төлбөрийг төлсний дараа','байрны төлбөрийг төлсний дараа'),
                     ENROL.replace('баталгаажна','баталгаажихгүй')):
            self.assertIn('admission_enrolment_confirmation',missing_field_evidence(fields,[REGISTER,text]))

    def test_negated_registration_cannot_satisfy_the_stage(self):
        fields=field_evidence_requirements(QUERY)
        self.assertIn('admission_registration_confirmation',missing_field_evidence(fields,[REGISTER.replace('баталгаажна','баталгаажихгүй'),ENROL]))

    def test_retracted_rule_and_olympiad_registration_are_not_admission_conditions(self):
        fields=field_evidence_requirements(QUERY)
        retracted=ENROL.rstrip('.')+' гэж мэдээлсэн ч уг мэдээллийг үгүйсгэсэн.'
        self.assertIn('admission_enrolment_confirmation',missing_field_evidence(fields,[REGISTER,retracted]))
        olympiad='Олимпиадын бүртгэлийн хураамжийг төлснөөр бүртгэл бүрэн баталгаажна.'
        self.assertIn('admission_registration_confirmation',missing_field_evidence(fields,[olympiad,ENROL]))

    def test_general_programming_question_does_not_choose_between_two_programmes(self):
        def source(name):return dict(title=name+' хөтөлбөр',url='https://nmct.edu.mn/programs/'+name,
            text='Программчлалын хэл: Rust, Julia ашиглан судална.')
        query='Ямар программчлалын хэл заадаг вэ?'
        self.assertTrue(direct_lookup_contract(query,[source('Роботик')])['allowed_sources'])
        self.assertFalse(direct_lookup_contract(query,[source('Роботик'),source('Химийн')])['allowed_sources'])

    def test_mode_cannot_be_borrowed_from_another_assessment_clause(self):
        source=dict(text_scope='document_visual_excerpt',title='Элсэлтийн журам',text=
            'Ярилцлагын шалгалтад онлайнаар орно. Танхимын ярилцлагын шалгалтаар харилцааны чадварыг шалгана.')
        result=direct_lookup_contract('Онлайн ярилцлагаар ямар чадвар шалгах вэ?',[source])
        self.assertFalse(result['allowed_sources'])


if __name__=='__main__':unittest.main()
