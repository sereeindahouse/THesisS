"""Actual loopback photo/profile/TTS contracts on invented source records."""
import hashlib
import http.client
import json
import threading
import unittest

from content_store import ContentStore
from demo_server import make_server
from project_policy import ContentUsePolicy
from rag_runtime import ChatRAG
from tools.serve_device_demo import allowed_path
import test_teacher_media as media_fixtures
import test_clarification_http as http_fixtures
from test_demo_server import fixture


class TeacherMediaHTTPTests(unittest.TestCase):
    def setUp(self):
        self.media = media_fixtures.TeacherMediaTests(); self.media.setUp()
        self.addCleanup(self.media.doCleanups)
        self.root = self.media.root
        (self.root/'config').mkdir()
        (self.root/'config/content-use.json').write_text(json.dumps(dict(enabled=True,
            basis='user_acceptance_of_official_website',official_hosts=['nmct.edu.mn'],accepted_on='2026-10-10')),encoding='utf-8')
        self.database=self.root/'runtime/content.db'
        with ContentStore(self.database) as store:store.import_content(fixture('approved'),allow_draft=True)
        self.original=hashlib.sha256(self.database.read_bytes()).hexdigest()
        self.voice=http_fixtures.Voice()
        self.rag=ChatRAG(self.root,ContentUsePolicy(self.root),http_fixtures.Retriever(),http_fixtures.NoGenerator())
        self.server=make_server(self.database,port=0,project_root=self.root,rag_service=self.rag,
            voice_service=self.voice,teacher_service=self.media.manager)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join(timeout=2)
        self.assertEqual(hashlib.sha256(self.database.read_bytes()).hexdigest(),self.original)

    def request(self,method,path,body=None,headers=None):
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=8)
        try:
            data=None if body is None else json.dumps(body,ensure_ascii=False).encode('utf-8')
            connection.request(method,path,body=data,headers={'Content-Type':'application/json',**(headers or {})})
            response=connection.getresponse();data=response.read()
            value=json.loads(data) if response.getheader('Content-Type','').startswith('application/json') else data
            return response.status,value,dict(response.getheaders())
        finally:connection.close()

    def profile(self):
        status,result,_=self.request('POST','/api/route',dict(query='Батчулуун багшийн зураг харуулна уу?'))
        self.assertEqual(status,200,result);return result

    def speak(self,result):
        return self.request('POST','/api/voice/speak',dict(query=result['query'],package_id=result['package_id'],
            response_id=result['response_id'],release_token=result['content_release']['activation_token'],voice='mn-MN-BataaNeural'))

    def test_dated_profile_and_photo_are_bound_to_same_named_source(self):
        result=self.profile();self.assertEqual(result['route'],'A');self.assertEqual(result['llm_calls'],0)
        self.assertFalse(result['generated']);self.assertEqual(result['answer_kind'],'official_teacher_profile')
        card=result['teacher_cards'][0];citation=result['citations'][0]
        self.assertEqual(card['name'],'Батчулуун');self.assertIn(card['name'],result['answer'])
        self.assertEqual(citation['source_html_sha256'],card['source_html_sha256'])
        self.assertEqual(citation['extraction_method'],'official_structured_teacher_record')
        self.assertFalse(citation['school_staff_approval'])
        status,data,headers=self.request('GET',card['image_url'])
        self.assertEqual(status,200);self.assertEqual(data,media_fixtures.PNG)
        self.assertEqual(headers['Content-Type'],'image/png');self.assertEqual(headers['X-Content-Type-Options'],'nosniff')
        self.assertNotIn(str(self.root),json.dumps(result,ensure_ascii=False))

    def test_profile_tts_uses_cached_exact_teacher_text_without_new_generation(self):
        result=self.profile();status,audio,_=self.speak(result)
        self.assertEqual(status,200,audio);self.assertEqual(self.voice.spoken[0][0],result['answer'])
        self.assertFalse(audio['text_generated']);self.assertEqual(audio['answer_llm_calls'],0)
        self.assertEqual(audio['answer_kind'],'official_teacher_profile')

    def test_generic_request_clarifies_from_available_captured_subset(self):
        status,result,_=self.request('POST','/api/route',dict(query='Багшийн зурагтай танилцуулга үзье.'))
        self.assertEqual(status,200);self.assertEqual(result['route'],'D');self.assertIsNone(result['answer'])
        self.assertNotIn('teacher_cards',result);self.assertIn('бүх багшийн жагсаалт биш',result['message'])
        self.assertTrue(result['suggestions'][0].startswith('Батчулуун'))

    def test_unknown_and_private_field_requests_never_show_profile_as_answer(self):
        for query in ('Дорж багшийн зураг','Батчулуун багшийн утасны дугаар','Батчулуун багш хэдэн настай вэ?'):
            with self.subTest(query=query):
                status,result,_=self.request('POST','/api/route',dict(query=query))
                self.assertEqual(status,200);self.assertNotIn('teacher_cards',result)
                self.assertNotEqual(result.get('answer_kind'),'official_teacher_profile')

    def test_tampered_source_invalidates_previous_profile_tts_before_provider(self):
        result=self.profile();page=self.media.store/'page.html';page.write_bytes(page.read_bytes()+b' changed')
        self.assertEqual(self.speak(result)[0],409);self.assertFalse(self.voice.spoken)
        status,catalog,_=self.request('GET','/api/teachers')
        self.assertEqual(status,200);self.assertFalse(catalog['available']);self.assertEqual(catalog['profiles'],[])

    def test_source_changes_during_synthesis_never_return_stale_audio_url(self):
        result=self.profile();original=self.voice.synthesize
        def change(text,voice):
            page=self.media.store/'page.html';page.write_bytes(page.read_bytes()+b' changed')
            return original(text,voice)
        self.voice.synthesize=change
        status,value,_=self.speak(result);self.assertEqual(status,409);self.assertNotIn('audio_url',value)
        self.assertEqual(self.voice.deleted,['b'*32])

    def test_catalog_media_identity_host_origin_and_traversal_are_bounded(self):
        status,catalog,_=self.request('GET','/api/teachers')
        self.assertEqual(status,200);self.assertEqual(len(catalog['profiles']),1)
        for path in ('/api/teacher-media/teacher-'+'0'*24,'/api/teacher-media/../../private.txt','/api/teacher-media/not-a-picture'):
            self.assertEqual(self.request('GET',path)[0],404)
        self.assertEqual(self.request('GET','/api/teachers',headers={'Origin':'https://attacker.example'})[0],403)
        self.assertEqual(self.request('GET','/api/teachers',headers={'Host':'attacker.example'})[0],403)

    def test_gateway_exposes_only_public_teacher_get_routes_and_never_admin(self):
        self.assertTrue(allowed_path('GET','/api/teachers'))
        self.assertTrue(allowed_path('GET','/api/teacher-media/teacher-'+'a'*24))
        for method,path in (('POST','/api/teachers'),('GET','/api/teacher-media/../../x'),
                            ('GET','/api/admin/state'),('POST','/api/admin/publish'),('GET','/runtime/quality-media-20261021/teacher-media/manifest.json')):
            self.assertFalse(allowed_path(method,path),(method,path))


if __name__=='__main__':unittest.main()
