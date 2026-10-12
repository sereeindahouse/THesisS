import copy
import json
from pathlib import Path
import tempfile
import unittest

from rag_runtime import ChatRAG, GroundedGenerator, source_extract

SOURCE = dict(source_id='web-test', text='Сургалтын төлбөр: жилд 8,280,000 ₮.',
              excerpt='Сургалтын төлбөр: жилд 8,280,000 ₮.', url='https://nmct.edu.mn/elselt',
              title='Элсэлт 2026', chunk_id=1, version=1, retrieved_at='2026-10-10',
              source_updated_at=None, lexical_overlap_count=1)
CLAIM = dict(text='Сургалтын төлбөр жилд 8,280,000 ₮.', source_id='web-test',
             quote=SOURCE['text'])


class GeneratorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root/'runtime').mkdir()
        self.config = self.root/'runtime/rag-model.json'
        self.config.write_text(json.dumps(dict(model='local-test',base_url='http://127.0.0.1:11434')))
        self.proposal = dict(insufficient=False, claims=[{k:CLAIM[k] for k in ('text','source_id')}])
        self.requests = []

    def tearDown(self):
        self.temp.cleanup()

    def transport(self, method, url, payload, timeout, max_bytes):
        self.requests.append((method,url,payload))
        if method == 'GET':
            return {'models':[{'name':'local-test:latest'}]}
        return {'done':True,'message':{'content':json.dumps(self.proposal,ensure_ascii=False)}}

    def generate(self):
        return GroundedGenerator(self.root,self.transport).generate('Төлбөр хэд вэ?', [SOURCE])

    def test_valid_evidence(self):
        r=self.generate()
        self.assertTrue(r['generated'])
        self.assertEqual(r['llm_calls'],1)
        self.assertEqual(r['claims'][0]['quote'],SOURCE['text'])

    def test_invented_citation_rejected(self):
        self.proposal['claims'][0]['source_id']='invented'
        self.assertEqual(self.generate()['reason'],'unknown_citation')

    def test_model_authored_quote_not_accepted(self):
        self.proposal['claims'][0]['quote']='Төлбөр үнэгүй болсон байна.'
        self.assertEqual(self.generate()['reason'],'invalid_generation')

    def test_invented_number_rejected(self):
        self.proposal['claims'][0]['text']='Сургалтын төлбөр 9,999,999 ₮.'
        self.assertEqual(self.generate()['reason'],'unsupported_number')

    def test_generator_year_mismatch_makes_no_provider_call(self):
        r=GroundedGenerator(self.root,self.transport).generate('2028 оны төлбөр?', [SOURCE])
        self.assertEqual(r['reason'],'requested_year_not_supported')
        self.assertFalse(self.requests)

    def test_question_is_not_accepted_as_answer(self):
        self.proposal['claims'][0]['text']='Сургалтын төлбөр хэд вэ?'
        self.assertEqual(self.generate()['reason'],'question_instead_of_answer')

    def test_insufficient_no_answer(self):
        self.proposal=dict(insufficient=True,claims=[])
        self.assertFalse(self.generate()['generated'])

    def test_malformed_claim_rejected(self):
        self.proposal['claims'][0]['text']=123
        self.assertEqual(self.generate()['reason'],'invalid_generation')

    def test_unconfigured_no_model_call(self):
        self.config.unlink()
        r=self.generate()
        self.assertFalse(r['generated'])
        self.assertEqual(r['llm_calls'],0)
        self.assertFalse(self.requests)

    def test_remote_origin_rejected(self):
        self.config.write_text(json.dumps(dict(model='local-test',base_url='http://example.com')))
        self.assertFalse(self.generate()['generated'])
        self.assertFalse(self.requests)

    def test_cloud_model_rejected(self):
        self.config.write_text(json.dumps(dict(model='local-test:cloud')))
        self.assertFalse(self.generate()['generated'])
        self.assertFalse(self.requests)

    def test_prompt_data_is_structured(self):
        self.generate()
        p=self.requests[-1][2]
        self.assertIsInstance(p['format'],dict)
        self.assertEqual(json.loads(p['messages'][1]['content'])['SOURCES'][0]['source_id'],'web-test')


class Policy:
    enabled=True
    def __init__(self,reason='no_supported_question_match',answer=None):
        self.reason,self.answer=reason,answer
    def route(self,db,query,allow_draft=False):
        return dict(query=query,route='E',package_id='package1',reason_code=self.reason,
            reason_codes=[self.reason],answer=self.answer,citations=[],clarification=None,
            exact_matches=[],generated=False,llm_calls=0,message='no',answer_kind=None)


class Retriever:
    def __init__(self):
        self.corpus_id='corpus1'
        self.sources=[copy.deepcopy(SOURCE)]
        self.calls=0
    def status(self):
        return dict(available=True,corpus_id=self.corpus_id)
    def search(self,q,limit=4):
        self.calls+=1
        return dict(candidates=self.sources,corpus_id=self.corpus_id,backend='test')


class Generator:
    def __init__(self):
        self.calls=0
    def status(self):
        return dict(available=True)
    def generate(self,q,sources):
        self.calls+=1
        return dict(generated=True,llm_calls=1,claims=[copy.deepcopy(CLAIM)],reason='test')


class ChatTests(unittest.TestCase):
    def setUp(self):
        self.retriever=Retriever()
        self.generator=Generator()
        self.policy=Policy()
        self.chat=ChatRAG('.',self.policy,self.retriever,self.generator)

    def test_c_citations_and_cache(self):
        r=self.chat.route(None,'Төлбөр хэд вэ?')
        self.assertEqual(r['route'],'C')
        self.assertIn('[1]',r['answer'])
        self.assertEqual(r['citations'][0]['source_url_or_filename'],SOURCE['url'])
        self.assertEqual(self.chat.recall(r['response_id'],r['query'],r['package_id'],False)['answer'],r['answer'])
        self.assertEqual(self.generator.calls,1)

    def test_document_citation_keeps_locator_and_transcription_method(self):
        self.retriever.sources[0].update(url='https://nmct.edu.mn/rule.png',
            source_locator='х.2, IV.6', extraction_method='visual_transcription', reviewer_kind='assistant')
        result=self.chat.route(None,'Төлбөр хэд вэ?')
        citation=result['citations'][0]
        self.assertEqual(citation['locator'],'х.2, IV.6')
        self.assertEqual(citation['extraction_method'],'visual_transcription')
        self.assertEqual(citation['reviewer_kind'],'assistant')
        self.assertFalse(citation['school_staff_approval'])

    def test_provider_failure_does_not_claim_evidence_missing(self):
        self.generator.generate=lambda q,s: dict(generated=False,llm_calls=1,claims=[],reason='provider_or_format_failure')
        result=self.chat.route(None,'Төлбөр хэд вэ?')
        self.assertEqual(result['reason_code'],'generation_unavailable_with_sources')
        self.assertTrue(result['related_sources'])
        self.assertIn('саатал',result['message'])
        self.assertEqual(result['suggestions'][0],result['query'])
        self.assertIsNone(result['answer'])

    def test_cache_mismatch(self):
        r=self.chat.route(None,'Төлбөр хэд вэ?')
        for query,package,draft in [('өөр','package1',False),(r['query'],'other',False),(r['query'],'package1',True)]:
            with self.assertRaises(ValueError):
                self.chat.recall(r['response_id'],query,package,draft)

    def test_changed_corpus_invalidates_audio(self):
        r=self.chat.route(None,'Төлбөр хэд вэ?')
        self.retriever.corpus_id='changed'
        with self.assertRaises(ValueError):
            self.chat.recall(r['response_id'],r['query'],'package1',False)

    def test_guards_never_bypassed(self):
        for reason in ['expired_content','future_validity','partial_answer','unsupported_year',
                       'live_status_not_supported','specific_scope_not_supported','missing_year',
                       'content_rejected_or_unapproved','unmatched_numeric_constraints']:
            self.policy.reason=reason
            r=self.chat.route(None,'Асуулт')
            self.assertEqual(r['reason_code'],reason)
        self.assertEqual(self.retriever.calls,0)
        self.assertEqual(self.generator.calls,0)

    def test_disabled_policy_never_uses_web(self):
        self.policy.enabled=False
        self.chat.route(None,'Асуулт')
        self.assertEqual(self.retriever.calls,0)

    def test_direct_answer_no_llm(self):
        self.policy.answer='Эхтэй бэлэн хариулт'
        self.assertEqual(self.chat.route(None,'Асуулт')['answer'],self.policy.answer)
        self.assertEqual(self.generator.calls,0)

    def test_greeting_no_search(self):
        r=self.chat.route(None,'Сайн байна уу?')
        self.assertEqual(r['route'],'D')
        self.assertTrue(r['suggestions'])
        self.assertEqual(self.retriever.calls,0)

    def test_external_sources_excluded(self):
        self.retriever.sources[0]['url']='https://nmct.edu.mn.evil/elselt'
        r=self.chat.route(None,'Асуулт')
        self.assertIsNone(r['answer'])
        self.assertFalse(r['related_sources'])
        self.assertEqual(self.generator.calls,0)

    def test_live_request_sources_only(self):
        r=self.chat.route(None,'Одоо бүртгэл нээлттэй юу?')
        self.assertIsNone(r['answer'])
        self.assertEqual(r['reason_code'],'live_status_not_supported')
        self.assertEqual(self.generator.calls,0)
        self.assertTrue(r['related_sources'])

    def test_new_year_not_replaced(self):
        r=self.chat.route(None,'2028 оны төлбөр хэд вэ?')
        self.assertIsNone(r['answer'])
        self.assertEqual(self.generator.calls,0)

    def test_no_sources_has_next_steps(self):
        self.retriever.sources=[]
        r=self.chat.route(None,'Ангараг дээр муур бий юу?')
        self.assertTrue(r['message'])
        self.assertTrue(r['suggestions'])
        self.assertFalse(r['generated'])

    def test_empty_topic_clarifies_without_search(self):
        for query in ['???','Сургуулийн тухай мэдээлэл']:
            self.assertEqual(self.chat.route(None,query)['reason_code'],'clarify_topic')
        self.assertEqual(self.retriever.calls,0)

    def test_fee_extract_copies_source_but_not_other_fee_scope(self):
        s=copy.deepcopy(SOURCE)
        direct=source_extract('Сургалтын төлбөр хэд вэ?',[s])
        self.assertEqual(direct[1],s['text'])
        for q in ['Олимпиадын төлбөр хэд вэ?','Гадаад оюутны сургалтын төлбөр хэд вэ?',
                  'Сургалтын төлбөрийн хөнгөлөлт бий юу?']:
            self.assertIsNone(source_extract(q,[s]))

    def test_how_to_enroll_is_not_replaced_by_eligibility(self):
        s=copy.deepcopy(SOURCE)
        s['text']='Элсэлтэд оролцох эрх\nЕБС-ийн 9 дүгээр ангиа төгссөн сурагч\nХолбоо барих'
        self.assertIsNone(source_extract('Яаж элсэх вэ?',[s]))
        self.assertIsNotNone(source_extract('Элсэхэд ямар шаардлагатай вэ?',[s]))

    def test_registration_steps_are_copied_without_changing_scope(self):
        s=copy.deepcopy(SOURCE)
        steps='1. Бүртгүүлэх\nМэдээллээ бөглөнө.\n2. Хураамж төлөх\nQPay ашиглана.\n3. Хувийн хэсэг\nБүртгэлийн мэдээллээ харна.'
        s['text']='Элсэлт 2026\n'+steps+'\nСонгох мэргэжил'
        self.assertEqual(source_extract('Элсэлтийн бүртгэлд ямар алхмууд байдаг вэ?',[s])[1],steps)
        self.assertEqual(source_extract('Яаж элсэх вэ?',[s])[1],steps)
        self.assertIsNone(source_extract('Гадаад оюутан яаж элсэх вэ?',[s]))

    def test_kosen_news_does_not_answer_general_concept(self):
        self.retriever.sources[0]['url']='https://nmct.edu.mn/news/kis-meeting'
        r=self.chat.route(None,'Коосэн сургалтын онцлог юу вэ?')
        self.assertEqual(r['reason_code'],'concept_overview_not_supported')
        self.assertEqual(self.generator.calls,0)
        self.assertTrue(r['related_sources'])

    def test_direct_extract_retains_source_year_and_capture_date(self):
        self.retriever.sources[0]['page_header']='ШМТК — Элсэлт 2026\nАлбан эх'
        r=self.chat.route(None,'Сургалтын төлбөр хэд вэ?')
        self.assertEqual(r['route'],'A')
        self.assertIn('2026-10-10',r['answer'])
        self.assertIn('Элсэлт 2026',r['answer'])
        self.assertFalse(r['generated'])
        self.assertEqual(self.generator.calls,0)

if __name__=='__main__':
    unittest.main()
