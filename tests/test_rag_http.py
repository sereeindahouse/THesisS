import unittest

import test_demo_server as server_fixture


class Voice:
    def __init__(self): self.spoken=[]
    def status(self): return {}
    def synthesize(self,text,voice):
        self.spoken.append(text)
        return {'audio_url':'/api/voice/audio/fixture','id':'fixture'}


class RAG:
    def __init__(self): self.calls=0
    def status(self):
        return {'provider':{'available':True}}
    def route(self,db,q,allow_draft=False):
        self.calls+=1
        return dict(query=q,route='C',answer='Тестийн эхтэй хариулт',package_id='package',
                    generated=True,llm_calls=1,response_id='a'*32,citations=[],message='test')
    def recall(self,response_id,query,package,draft):
        if response_id!='a'*32 or query!='Тест үү?':
            raise ValueError('Хариулт таарахгүй')
        return dict(query=query,route='C',answer='Тестийн эхтэй хариулт',package_id=package,
                    generated=True,llm_calls=1,citations=[],message='test',answer_kind='rag_generated')


class RAGHTTPTests(unittest.TestCase):
    def setUp(self):
        # Reuse the server fixture without inheriting/re-running unrelated tests.
        self.helper=server_fixture.DemoServerTests()
        self.helper.setUp()
        self.helper.server.shutdown()
        self.helper.server.server_close()
        self.helper.thread.join()
        from demo_server import make_server
        import threading
        self.voice,self.rag=Voice(),RAG()
        self.helper.server=make_server(self.helper.db,port=0,project_root=self.helper.root,
            voice_service=self.voice,rag_service=self.rag)
        self.helper.thread=threading.Thread(target=self.helper.server.serve_forever,daemon=True)
        self.helper.thread.start()
        self.request=self.helper.request
        _,r=self.request('POST','/api/search',{'query':'Тест үү?'})
        self.package=r['package_id']

    def tearDown(self): self.helper.tearDown()

    def test_cached_generated_text_is_spoken_without_second_generation(self):
        status,r=self.request('POST','/api/voice/speak',dict(query='Тест үү?',allow_draft=True,
            voice='mn-MN-BataaNeural',package_id=self.package,response_id='a'*32))
        self.assertEqual(status,200)
        self.assertEqual(self.voice.spoken,['Тестийн эхтэй хариулт'])
        self.assertTrue(r['text_generated'])
        self.assertEqual(r['llm_calls'],0)
        self.assertEqual(self.rag.calls,0)

    def test_unknown_response_id_refused_before_tts(self):
        status,_=self.request('POST','/api/voice/speak',dict(query='Тест үү?',allow_draft=True,
            package_id=self.package,response_id='b'*32))
        self.assertEqual(status,409)
        self.assertFalse(self.voice.spoken)

    def test_source_selection_is_not_reported_as_model_authored_tts_text(self):
        from unittest.mock import patch
        value=dict(query='Тест үү?',route='C',answer='Эхийн яг үг.',package_id='package',
            generated=True,llm_calls=2,citations=[],answer_kind='rag_generated',
            rag=dict(answer_text_generated=False,llm_role='evidence_selection'))
        with patch.object(self.rag,'recall',return_value=value):
            status,result=self.request('POST','/api/voice/speak',dict(query='Тест үү?',allow_draft=True,
                voice='mn-MN-BataaNeural',package_id=self.package,response_id='a'*32))
        self.assertEqual(status,200)
        self.assertFalse(result['text_generated'])
        self.assertEqual(result['answer_llm_calls'],2)
        self.assertEqual(result['answer_llm_role'],'evidence_selection')
        self.assertEqual(result['llm_calls'],0)

    def test_client_text_cannot_override_spoken_answer(self):
        status,_=self.request('POST','/api/voice/speak',dict(query='Тест үү?',allow_draft=True,
            package_id=self.package,response_id='a'*32,text='invented'))
        self.assertEqual(status,400)
        self.assertFalse(self.voice.spoken)

    def test_old_content_package_refused_before_recall(self):
        status,_=self.request('POST','/api/voice/speak',dict(query='Тест үү?',allow_draft=True,
            package_id='old',response_id='a'*32))
        self.assertEqual(status,409)
        self.assertFalse(self.voice.spoken)

if __name__=='__main__': unittest.main()
