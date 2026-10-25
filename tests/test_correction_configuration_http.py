"""Opt-in server wiring and HTTP boundary with an invented local provider."""
import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import demo_server
from llm_runtime import LLMRuntime


class CorrectionConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.path=self.root/'runtime/rag-model.json';self.path.parent.mkdir()
        self.environment=patch.dict(os.environ,{});self.environment.start()
        for key in ('THESIS_LLM_MODEL','THESIS_OLLAMA_URL'):os.environ.pop(key,None)
        self.requests=[]
        self.generator=LLMRuntime(self.root,transport=self.forbidden,
            model='fixture-model',base_url='http://127.0.0.1:11434')
        self.rag=SimpleNamespace(generator=self.generator)

    def tearDown(self):self.environment.stop();self.temp.cleanup()

    def forbidden(self,*args):raise AssertionError('RAG transport must never serve transcript correction')

    def fake(self,method,url,payload,timeout,limit):
        self.requests.append((method,url))
        if method=='GET':return {'models':[{'name':'fixture-model'}]}
        raw=json.loads(payload['messages'][1]['content'])['raw_transcript']
        return {'done':True,'message':{'content':json.dumps({'corrected_text':raw,'reason':'No edit needed.'})}}

    def configure(self,value=True):self.path.write_text(json.dumps({'stt_correction_from_rag':value}),encoding='utf-8')

    def create(self):
        def factory(*args,**kwargs):return LLMRuntime(*args,transport=self.fake,**kwargs)
        with patch.object(demo_server,'LLMRuntime',side_effect=factory):
            return demo_server._transcription_corrector(self.root,self.rag)

    def test_explicit_optin_creates_separate_runtime_without_initial_network(self):
        self.configure();runtime=self.create()
        self.assertTrue(runtime.configured);self.assertEqual(runtime.model,'fixture-model')
        self.assertEqual(runtime.base_url,self.generator.base_url)
        self.assertIsNot(runtime,self.generator)
        self.assertIsNot(runtime._chat_lock,self.generator._chat_lock)
        self.assertIsNot(runtime._status_lock,self.generator._status_lock)
        self.assertEqual(self.requests,[])
        result=runtime.suggest_correction('сайн байна уу')
        self.assertTrue(result['used']);self.assertEqual(result['llm_calls'],1)
        self.assertEqual(result['raw_text'],result['suggested_text'])
        self.assertFalse(result['automatic_application'])

    def test_absent_or_nonboolean_optin_never_inherits_the_rag_model(self):
        self.assertFalse(self.create().configured)
        for value in (False,'true',1,None):
            with self.subTest(value=value):self.configure(value);self.assertFalse(self.create().configured)
        self.assertEqual(self.requests,[])

    def test_malformed_nondict_and_oversized_config_fail_closed(self):
        for value in ('{','[]',' '*16385):
            with self.subTest(value=value[:12]):
                self.path.write_text(value,encoding='utf-8');self.assertFalse(self.create().configured)
        self.assertEqual(self.requests,[])

    def test_any_explicit_model_environment_including_disabled_invalid_cloud_wins(self):
        self.configure()
        for value in ('','   ','bad model','fixture:cloud','explicit-local-model'):
            with self.subTest(value=value):
                os.environ['THESIS_LLM_MODEL']=value;runtime=self.create()
                self.assertEqual(runtime.model,value.strip())
                self.assertNotEqual(runtime.model,'fixture-model')
                if value!='explicit-local-model':self.assertFalse(runtime.configured)
        self.assertEqual(self.requests,[])

    def test_any_explicit_url_environment_blocks_project_fallback(self):
        self.configure()
        for value in ('','https://remote.example','http://127.0.0.1:11111'):
            with self.subTest(value=value):
                os.environ['THESIS_OLLAMA_URL']=value;self.assertFalse(self.create().configured)
        self.assertEqual(self.requests,[])

    def test_unconfigured_or_missing_generator_never_enables_correction(self):
        self.configure()
        for generator in (None,SimpleNamespace(configured=False),SimpleNamespace(configured=1),SimpleNamespace(configured=True)):
            with self.subTest(generator=generator):
                self.rag=SimpleNamespace(generator=generator);self.assertFalse(self.create().configured)
        self.assertEqual(self.requests,[])

    def test_copied_settings_still_require_local_url_and_local_valid_model(self):
        self.configure()
        for model,url in [('fixture:cloud','http://127.0.0.1:11434'),
                          ('bad model','http://127.0.0.1:11434'),
                          ('fixture-model','https://remote.example'),
                          ('fixture-model','http://user:secret@127.0.0.1:11434')]:
            with self.subTest(model=model,url=url):
                self.rag=SimpleNamespace(generator=SimpleNamespace(configured=True,model=model,base_url=url))
                self.assertFalse(self.create().configured)
        self.assertEqual(self.requests,[])

    def test_supplied_service_is_preserved_without_constructing_any_runtime(self):
        self.configure();supplied=object();os.environ['THESIS_LLM_MODEL']=''
        with patch.object(demo_server,'LLMRuntime',side_effect=AssertionError('Must not replace supplied service')):
            self.assertIs(demo_server._transcription_corrector(self.root,self.rag,supplied),supplied)

    def test_http_opted_in_correction_stays_manual_and_cross_site_denied_before_provider(self):
        self.configure()
        def factory(*args,**kwargs):return LLMRuntime(*args,transport=self.fake,**kwargs)
        with patch.object(demo_server,'LLMRuntime',side_effect=factory):
            server=demo_server.make_server(port=0,project_root=self.root,rag_service=self.rag)
        self.assertEqual(self.requests,[])
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        def request(headers):
            client=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3)
            client.request('POST','/api/voice/correct',json.dumps({'text':'сайн байна уу'}),
                           {'Content-Type':'application/json',**headers})
            response=client.getresponse();value=json.loads(response.read());client.close()
            return response.status,value
        try:
            for headers in ({'Origin':'https://outside.example'},
                            {'Sec-Fetch-Site':'cross-site','Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'}):
                self.assertEqual(request(headers)[0],403);self.assertEqual(self.requests,[])
            status,result=request({'Origin':'http://127.0.0.1:'+str(server.server_port)})
            self.assertEqual(status,200);self.assertTrue(result['used'])
            self.assertEqual(result['llm_calls'],1);self.assertFalse(result['automatic_application'])
            self.assertEqual(result['raw_text'],'сайн байна уу')
            self.assertEqual(sum(method=='POST' for method,_ in self.requests),1)
        finally:server.shutdown();server.server_close();worker.join(timeout=2)


if __name__=='__main__':unittest.main()
