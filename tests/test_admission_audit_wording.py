"""Constructed wording and source controls for the Oct 28 admission audit.

The school answers are never embedded in the intent detector. These fixtures
exercise distinct confirmation roles, missing evidence and process completeness.
"""
import unittest

from rag_runtime import (ChatRAG, admission_stage_sources, registration_process_query,
                         registration_process_excerpt, source_extract)
from source_fields import field_evidence_requirements, field_search_expansions, missing_field_evidence
from test_rag_runtime import Policy, Retriever, Generator, SOURCE


REGISTER = ('Хүссэн хөтөлбөрөө сонгон, бүртгэлийн хураамжаа FixturePay-ээр төлснөөр '
            'элсэлтийн бүртгэл бүрэн баталгаажна.')
ENROL = ('Элсэгч тогтоосон хугацаанд суралцах гэрээ байгуулан, сургалтын төлбөрийг '
         'төлсний дараа элсэн суралцах баталгаажна.')
STEPS = ('1. Бүртгүүлэх\nМэдээллээ бөглөнө.\n2. Хураамж төлөх\nFixturePay ашиглана.\n'
         '3. Хувийн хэсэг\nТөлбөр баталгаажмагц бүртгэлийн мэдээллээ харна.')


class AdmissionAuditWordingTests(unittest.TestCase):
    def test_admission_fee_amount_does_not_require_a_registration_inflection(self):
        paragraph='Цахимаар бүртгэл хийхдээ бүртгэлийн хураамж 7,301 төгрөгийг зааврын дагуу төлнө.'
        source=dict(SOURCE,text=paragraph,excerpt=paragraph,text_scope='document_visual_excerpt',
                    url='https://nmct.edu.mn/elseltiin-juram/fixture.png')
        for question in [
            'Элсэлтийн хураамж хэдэн төгрөг вэ?',
            'Шинэ Монгол коллеж сургуулийн элсэлтийн хураамж хэдэн төгрөг вэ? Бүртгүүл хийн тулд төлөх мөнгөний дүнг хэлж өгнө',
            'Элсэх хураамжийн хэмжээ хэд вэ?',
            'Элсэлтийн хураамж нь сургалтын төлбөрөөс тусдаа хэдэн төгрөг вэ?',
        ]:
            with self.subTest(question=question):
                self.assertEqual(source_extract(question,[source]),(source,paragraph))

    def test_fee_alias_keeps_refund_other_registration_and_extra_fields_separate(self):
        paragraph='Цахимаар бүртгэл хийхдээ бүртгэлийн хураамж 7,301 төгрөгийг зааврын дагуу төлнө.'
        source=dict(SOURCE,text=paragraph,excerpt=paragraph,text_scope='document_visual_excerpt',
                    url='https://nmct.edu.mn/elseltiin-juram/fixture.png')
        for question in [
            'Элсэлтийн хураамжийг буцааж авахад хэдэн төгрөг вэ?',
            'Элсэлтийн хураамж биш олимпиадын бүртгэлийн хураамж хэд вэ?',
            'Элсэлтийн хураамж хэд вэ, дотуур байрны төлбөр хэд вэ?',
            'Элсэлтийн хураамж хэд вэ, сургалтын төлбөр хэд вэ?',
        ]:
            with self.subTest(question=question):
                self.assertIsNone(source_extract(question,[source]))

    def test_fee_alias_routes_to_exact_source_without_model_selection(self):
        paragraph='Цахимаар бүртгэл хийхдээ бүртгэлийн хураамж 7,301 төгрөгийг зааврын дагуу төлнө.'
        source=dict(SOURCE,text=paragraph,excerpt=paragraph,text_scope='document_visual_excerpt',
                    url='https://nmct.edu.mn/elseltiin-juram/fixture.png')
        retriever,generator=Retriever(),Generator()
        retriever.sources=[source]
        result=ChatRAG('.',Policy(),retriever,generator).route(None,'Элсэлтийн хураамж хэдэн төгрөг вэ?')
        self.assertEqual(result['route'],'A')
        self.assertTrue(result['answer'].endswith(paragraph))
        self.assertEqual(generator.calls,0)
        self.assertEqual(result['llm_calls'],0)

    def test_payment_to_student_outcome_requires_both_distinct_stages(self):
        questions = [
            'Бүртгэлийн мөнгөө шилжүүлчихвэл би оюутан болсон гэсэн үг үү?',
            'Бүртгэлийн хураамжаа төлөөд шууд оюутан болчихсон гэж ойлгож болох уу?',
            'Элсэлтийн бүртгэлийн төлбөрөө төлбөл элссэн гэсэн үг үү?',
            'Бүртгэлээ баталгаажуулбал элсэн суралцах эрхээ авсан гэсэн үг үү?',
            'Бүртгэлийн мөнгө шилжүүлэхэд оюутны эрх баталгаажих уу?',
            'Элсэлтийн хураамжаа төлсөн бол суралцах эрх маань шууд баталгаажих уу?',
        ]
        for question in questions:
            with self.subTest(question=question):
                fields = field_evidence_requirements(question)
                self.assertEqual([field['stage'] for field in fields if field['type'] == 'admission_stage'],
                                 ['registration', 'enrolment'])
                self.assertEqual(missing_field_evidence(fields, [REGISTER, ENROL]), [])
                self.assertIn('admission_enrolment_confirmation', missing_field_evidence(fields, [REGISTER]))
                self.assertIn('admission_registration_confirmation', missing_field_evidence(fields, [ENROL]))
                self.assertEqual(len(field_search_expansions(question)), 2)

    def test_other_money_and_registration_requests_do_not_become_stage_comparisons(self):
        for question in [
            'Бүртгэлийн мөнгөө ямар данс руу шилжүүлэх вэ?',
            'Бүртгэлийн хураамж хэдэн төгрөг вэ?',
            'Олимпиадын бүртгэлийн мөнгөө төлсөн бол оюутан болох уу?',
            'Бүртгэлийн мөнгөө буцааж авах уу, оюутан болоогүй.',
            'Дотуур байрны төлбөрөө шилжүүлбэл оюутны эрх баталгаажих уу?',
            'Оюутан болохын тулд ямар шалгалт өгөх вэ?',
        ]:
            with self.subTest(question=question):
                self.assertFalse(any(field['type'] == 'admission_stage'
                                     for field in field_evidence_requirements(question)))

    def test_ordinary_wording_filters_olympiad_and_cannot_use_just_one_stage(self):
        question = 'Бүртгэлийн мөнгөө шилжүүлчихвэл би оюутан болсон гэсэн үг үү?'
        register = dict(SOURCE, text=REGISTER)
        enrol = dict(SOURCE, text=ENROL, text_scope='document_visual_excerpt',
                     url='https://nmct.edu.mn/elseltiin-juram/fixture.png')
        olympiad = dict(SOURCE, title='Олимпиадын бүртгэл',
                        url='https://nmct.edu.mn/olympiad', text='Бүртгэлийн хураамж төлнө.')
        self.assertEqual(admission_stage_sources(question, [register, enrol, olympiad]), [register, enrol])
        self.assertIsNone(source_extract(question, [register]))
        self.assertIsNone(source_extract(question, [enrol]))

    def test_ordinary_payment_wording_keeps_admission_scope_in_orchestration(self):
        question = 'Бүртгэлийн мөнгөө шилжүүлчихвэл би оюутан болсон гэсэн үг үү?'
        class StageRetriever(Retriever):
            def search(self, query, limit=5):
                self.calls += 1
                rows = [dict(SOURCE, source_id='fixture-register', text=REGISTER, excerpt=REGISTER),
                        dict(SOURCE, source_id='fixture-enrol', text=ENROL, excerpt=ENROL,
                             url='https://nmct.edu.mn/elseltiin-juram/fixture.png')]
                return dict(candidates=rows, corpus_id=self.corpus_id, backend='fixture')
        class NoGeneration(Generator):
            def generate(self, query, sources):
                self.calls += 1
                self.source_ids = [source['source_id'] for source in sources]
                return dict(generated=False, llm_calls=0, claims=[], reason='insufficient_evidence')
        generator = NoGeneration()
        result = ChatRAG('.', Policy(), StageRetriever(), generator).route(None, question)
        self.assertNotEqual(result['reason_code'], 'registration_scope_ambiguous')
        self.assertEqual(generator.source_ids, ['fixture-register', 'fixture-enrol'])

    def test_plural_case_and_presentation_words_keep_complete_process(self):
        for question in [
            'Элсэлтийн онлайн бүртгэлийг яаж хийх вэ? Алхмуудыг нь хэлээд өгөөч.',
            'Онлайнаар бүртгүүлэх дарааллыг зааж өгнө үү.',
            'Цахим бүртгэлийн алхам бүрийг тайлбарлаад өгөөч.',
            'Элсэлтийн бүртгэлээ хийхэд ямар дараалалтай вэ?',
            'Онлайн бүртгэлийн үе шатуудыг тайлбарлаж өгнө үү.',
        ]:
            with self.subTest(question=question):
                self.assertTrue(registration_process_query(question))
                retriever, generator = Retriever(), Generator()
                text = 'Нэвтрэх Нууц үг сэргээх\n' + STEPS + '\nӨөр гарчиг'
                retriever.sources[0].update(text=text, excerpt=text)
                result = ChatRAG('.', Policy(), retriever, generator).route(None, question)
                self.assertEqual(result['route'], 'A')
                self.assertIn(STEPS, result['answer'])
                self.assertNotIn('Нууц үг сэргээх', result['answer'])
                self.assertNotIn('Өөр гарчиг', result['answer'])
                self.assertEqual(generator.calls, 0)

    def test_process_extraction_keeps_additional_steps_and_multiline_conditions(self):
        condition = 'Хэрэв төлбөр баталгаажаагүй бол мэдээлэл харагдахгүй.'
        text = STEPS + '\n' + condition + '\n4. Мэдээллээ шалгах\nАлдаатай бол админтай холбогдоно.'
        self.assertEqual(registration_process_excerpt(dict(SOURCE, text=text)), text)
        text = STEPS + '\nХугацаа хэтэрвэл бүртгэл цуцлагдана.'
        self.assertEqual(registration_process_excerpt(dict(SOURCE, text=text)), text)

    def test_missing_reordered_or_descriptionless_steps_are_not_complete(self):
        for text in [
            STEPS.replace('2. Хураамж төлөх\nFixturePay ашиглана.\n', ''),
            STEPS.replace('2. Хураамж төлөх', '4. Хураамж төлөх'),
            STEPS.replace('FixturePay ашиглана.\n', ''),
            STEPS + '\n4. Өөр алхам\n' + 'Урт мэдээлэл. ' * 100,
        ]:
            with self.subTest(text=text[:100]):
                self.assertIsNone(registration_process_excerpt(dict(SOURCE, text=text)))

    def test_conditional_prefix_cannot_be_cut_off_by_direct_process(self):
        text = 'Зөвхөн тодорхой ангиллын элсэгчид дараах бүртгэл хийнэ.\n' + STEPS
        self.assertIsNone(registration_process_excerpt(dict(SOURCE, text=text)))

    def test_partial_process_never_falls_back_to_fee_or_generation(self):
        question = 'Элсэлтийн онлайн бүртгэлийн алхмуудыг хэлээд өгөөч.'
        retriever, generator = Retriever(), Generator()
        retriever.sources[0]['text'] = STEPS.split('3.')[0].rstrip()
        result = ChatRAG('.', Policy(), retriever, generator).route(None, question)
        self.assertEqual(result['route'], 'E')
        self.assertIsNone(result['answer'])
        self.assertEqual(result['rag']['reason'], 'registration_process_not_supported')
        self.assertEqual(generator.calls, 0)

    def test_process_aliases_do_not_erase_named_subject_or_extra_requested_field(self):
        for question in [
            'Эсэгтийн бүртгэлийн алхмуудыг хэлээд өгөөч.',
            'Олимпиадын онлайн бүртгэлийн алхмуудыг хэлээд өгөөч.',
            'Гадаад оюутны элсэлтийн бүртгэлийн алхмуудыг хэлээд өгөөч.',
            'Элсэлтийн онлайн бүртгэлийн алхмууд болон хураамж хэд вэ?',
            'Элсэлтийн онлайн бүртгэлийн алхмууд ба хаах огноог хэлээд өгөөч.',
            'Цахим бүртгэлийн алхам биш шалгалтын хуваарийг хэлээд өгөөч.',
            'Элсэлтийн онлайн бүртгэлээр хувийн мэдээллээ засах дарааллыг зааж өгнө үү.',
        ]:
            with self.subTest(question=question):
                self.assertFalse(registration_process_query(question))

    def test_stated_grade_cannot_be_replaced_by_a_japan_job_roadmap(self):
        question = 'Миний голч дүн 3.0 бол Японд дэвших боломжтой юу?'
        retriever, generator = Retriever(), Generator()
        result = ChatRAG('.', Policy(), retriever, generator).route(None, question)
        self.assertEqual(result['route'], 'E')
        self.assertEqual(result['reason_code'], 'supplied_grade_eligibility_not_verified')
        self.assertEqual(result['query'], question)
        self.assertIn('өгсөн голчийн тоонд', result['message'])
        self.assertIsNone(result['answer'])
        self.assertEqual(result['citations'], [])
        self.assertEqual(retriever.calls, 0)
        self.assertEqual(generator.calls, 0)


if __name__ == '__main__':
    unittest.main()
