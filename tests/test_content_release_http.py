"""Loopback end-to-end release publication, recovery and stale voice contracts.

All source material is invented inside a temporary directory. No real models,
network synthesis, school approval, personal audio or production DB is used.
"""
from contextlib import closing
import http.client
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from content_release import ContentReleaseManager
from content_store import ContentStore
from CORE.website_corpus import import_snapshot
from demo_server import make_server
from project_policy import ContentUsePolicy
from rag_runtime import ChatRAG
from tools import manage_snapshot as snapshots
from tools.serve_device_demo import allowed_path
from website_retrieval import WebsiteRetriever
from test_content_release import captured, content, URL
from test_voice_demo_http import FakeLLM, FakeReview, FakeVoice


class NoGenerator:
    def status(self):
        return dict(available=False)

    def generate(self, *args, **kwargs):
        raise AssertionError('Release HTTP tests must never call a model.')


class ReleaseHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)/'project'; self.root.mkdir()
        self.database = self.root/'runtime/content.db'
        import_snapshot(self.root/'CORE/database/website.db', captured(self.root))
        self.baseline = content()
        for group in ('sources', 'facts', 'faqs'):
            for record in self.baseline[group]:
                record.update(valid_from='2020-01-01', valid_until='2099-12-31')
        with ContentStore(self.database) as store:
            store.import_content(self.baseline, allow_draft=True)
        (self.root/'config').mkdir()
        (self.root/'config/content-use.json').write_text(json.dumps(dict(
            basis='user_acceptance_of_official_website', enabled=True,
            official_hosts=['nmct.edu.mn'], accepted_on='2026-10-20')), encoding='utf-8')
        self.original = {name:snapshots.sha(self.root/name) for name in snapshots.DATABASES}
        self.voice = FakeVoice()
        policy = ContentUsePolicy(self.root)
        rag = ChatRAG(self.root, policy, retriever=WebsiteRetriever(self.root,use_dense=False), generator=NoGenerator())
        self.server = make_server(self.database, port=0, project_root=self.root,
            voice_service=self.voice, review_service=FakeReview(), llm_service=FakeLLM(), rag_service=rag)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        status, state = self.request('GET', '/api/admin/state')
        self.assertEqual(status, 200); self.token = state['csrf_token']

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=2)
        self.assertEqual(self.original, {name:snapshots.sha(self.root/name) for name in snapshots.DATABASES})
        self.temp.cleanup()

    def request(self, method, path, payload=None, *, headers=None, raw=None):
        connection = http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=15)
        request_headers = dict(headers or {}); body = raw
        if payload is not None:
            body = json.dumps(payload,ensure_ascii=False).encode('utf-8')
            request_headers.setdefault('Content-Type','application/json')
        connection.request(method,path,body=body,headers=request_headers)
        response = connection.getresponse(); data = response.read()
        result = json.loads(data) if response.getheader('Content-Type','').startswith('application/json') else data
        status = response.status; connection.close(); return status,result

    def admin(self, operation, payload):
        return self.request('POST','/api/admin/'+operation,payload,headers={'X-Admin-Token':self.token})

    def stage(self, label='test release', expected=None):
        status,result = self.admin('stage',dict(label=label,expected_active=expected))
        self.assertEqual(status,200,result)
        return result['result']['release_id']

    def seal(self, release_id):
        status,result = self.admin('validate',dict(release_id=release_id))
        self.assertEqual(status,200,result); return result['result']

    def publish(self, release_id, expected=None, operation='publish'):
        status,result = self.admin(operation,dict(release_id=release_id,expected_active=expected))
        self.assertEqual(status,200,result); return result['result']

    def initial(self):
        release_id = self.stage('initial'); self.seal(release_id)
        return self.publish(release_id)

    def changed(self, active):
        release_id = self.stage('updated alias',active['activation_token'])
        value = json.loads(json.dumps(self.baseline))
        value['faqs'][0].update(answer='Тестийн шинэчилсэн хариулт.',question_aliases=['Шинэ лавлагаа юу вэ?'])
        status,result = self.admin('import-content',dict(release_id=release_id,content=value))
        self.assertEqual(status,200,result)
        return release_id

    def route(self, query='Тест үү?'):
        status,result = self.request('POST','/api/route',dict(query=query))
        self.assertEqual(status,200,result); self.assertEqual(result['llm_calls'],0)
        return result

    def speak(self, result, token=None):
        return self.request('POST','/api/voice/speak',dict(query=result['query'],package_id=result['package_id'],
            release_token=token if token is not None else result['content_release']['activation_token'],
            voice='mn-MN-BataaNeural'))

    def test_staged_edits_are_invisible_until_explicit_publish(self):
        initial = self.initial(); original = self.route()
        edited = self.changed(initial)
        self.assertEqual(self.route()['answer'],original['answer'])
        checked = self.seal(edited)
        self.assertIn('test.faq',checked['diff']['faqs']['updated'])
        self.assertEqual(self.route()['content_release']['activation_token'],initial['activation_token'])
        published = self.publish(edited,initial['activation_token'])
        new = self.route('Шинэ лавлагаа юу вэ?')
        self.assertEqual(new['answer'],'Тестийн шинэчилсэн хариулт.')
        self.assertEqual(new['content_release']['activation_token'],published['activation_token'])
        status,search = self.request('POST','/api/search',dict(query='Шинэ лавлагаа юу вэ?'))
        self.assertEqual(status,200); self.assertTrue(search['candidates'][0]['eligible'])
        status,explorer = self.request('GET','/api/explorer')
        self.assertEqual(status,200)
        self.assertEqual(explorer['curated']['faqs'][0]['answer'],new['answer'])
        self.assertEqual(explorer['content_release']['activation_token'],published['activation_token'])

    def test_http_rollback_mints_token_and_rejects_pre_rollback_voice(self):
        first = self.initial(); old = self.route()
        self.assertEqual(self.speak(old)[0],200)
        edited = self.changed(first); self.seal(edited)
        second = self.publish(edited,first['activation_token'])
        rolled = self.publish(first['release_id'],second['activation_token'],'rollback')
        self.assertNotEqual(rolled['activation_token'],first['activation_token'])
        before = len(self.voice.spoken)
        self.assertEqual(self.speak(old)[0],409)
        self.assertEqual(len(self.voice.spoken),before)
        self.assertEqual(self.route()['answer'],old['answer'])
        self.assertEqual(self.speak(self.route())[0],200)

    def test_publish_during_synthesis_never_returns_stale_audio(self):
        first = self.initial(); old = self.route()
        edited = self.changed(first); self.seal(edited)
        original_synthesize = self.voice.synthesize
        def publish_while_synthesizing(text, voice):
            ContentReleaseManager(self.root).publish(edited,first['activation_token'])
            return original_synthesize(text,voice)
        self.voice.synthesize = publish_while_synthesizing
        status,result = self.speak(old)
        self.assertEqual(status,409,result)
        self.assertNotIn('audio_url',result)

    def test_corrupt_active_chat_fails_closed_but_admin_can_rollback(self):
        first = self.initial(); edited = self.changed(first); self.seal(edited)
        second = self.publish(edited,first['activation_token'])
        with closing(sqlite3.connect(second['content_database'])) as db:
            db.execute("UPDATE packages SET source_filename='tampered'"); db.commit()
        self.assertEqual(self.request('GET','/api/status')[0],503)
        self.assertEqual(self.request('POST','/api/route',dict(query='Тест үү?'))[0],503)
        status,state = self.request('GET','/api/admin/state')
        self.assertEqual(status,200); self.assertTrue(state['active_error'])
        self.assertEqual(state['active']['activation_token'],second['activation_token'])
        self.publish(first['release_id'],state['active']['activation_token'],'rollback')
        self.assertEqual(self.route()['answer'],self.baseline['faqs'][0]['answer'])

    def test_admin_csrf_origin_framing_and_input_limits(self):
        body = dict(label='must not stage',expected_active=None)
        self.assertEqual(self.request('POST','/api/admin/stage',body)[0],403)
        self.assertEqual(self.request('POST','/api/admin/stage',body,headers={'X-Admin-Token':'wrong'})[0],403)
        self.assertEqual(self.request('POST','/api/admin/stage',body,headers={'X-Admin-Token':'é'})[0],403)
        self.assertEqual(self.request('GET','/api/admin/content?release_id=invalid',headers={'X-Admin-Token':'é'})[0],403)
        for headers in ({'Origin':'https://attacker.example'}, {'Sec-Fetch-Site':'cross-site'}):
            headers['X-Admin-Token']=self.token
            self.assertEqual(self.request('POST','/api/admin/stage',body,headers=headers)[0],403)
        self.assertEqual(self.request('GET','/api/admin/state',headers={'Sec-Fetch-Site':'cross-site'})[0],403)
        self.assertEqual(self.request('GET','/api/admin/state',headers={'Origin':'https://attacker.example'})[0],403)
        self.assertEqual(self.admin('stage',{'label':'missing expected'})[0],400)
        self.assertEqual(self.admin('stage',dict(label='bad field',expected_active=None,unknown=True))[0],400)
        self.assertEqual(self.request('POST','/api/admin/stage',body,headers={
            'X-Admin-Token':self.token,'Content-Length':str(4*1024*1024+1)})[0],400)
        status,state=self.request('GET','/api/admin/state')
        self.assertEqual(status,200); self.assertEqual(state['releases'],[])

    def test_stale_cas_and_unsealed_publication_are_rejected(self):
        release_id=self.stage()
        self.assertEqual(self.admin('publish',dict(release_id=release_id,expected_active=None))[0],400)
        self.seal(release_id); active=self.publish(release_id)
        self.assertEqual(self.admin('publish',dict(release_id=release_id,expected_active=None))[0],409)
        self.assertEqual(self.admin('stage',dict(label='stale',expected_active=None))[0],409)
        self.assertEqual(self.route()['content_release']['activation_token'],active['activation_token'])

    def test_refreshed_token_cannot_publish_candidate_from_older_baseline(self):
        first=self.initial()
        left=self.stage('left candidate',first['activation_token']);self.seal(left)
        right=self.stage('right candidate',first['activation_token']);self.seal(right)
        second=self.publish(left,first['activation_token'])
        status,state=self.request('GET','/api/admin/state');self.assertEqual(status,200)
        status,result=self.admin('publish',dict(release_id=right,expected_active=state['active']['activation_token']))
        self.assertEqual(status,409,result)
        self.assertEqual(self.route()['content_release']['activation_token'],second['activation_token'])

    def test_new_website_snapshot_updates_explorer_and_website_search_only_after_publish(self):
        first=self.initial(); release_id=self.stage('new web',first['activation_token'])
        source=captured(self.root,'new-capture','Шинэ зарлал туршилтын хугацаа.')
        manifest=json.loads((source/'manifest.json').read_bytes());manifest['retrieved_at']='2026-10-20T02:00:00+00:00'
        (source/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
        status,result=self.admin('import-website',dict(release_id=release_id,snapshot_path=str(source)))
        self.assertEqual(status,200,result)
        checked=self.seal(release_id);self.assertTrue(checked['diff']['corpus_changed'])
        self.assertEqual(self.request('GET','/api/explorer')[1]['summary']['corpus_id'],first['corpus_id'])
        new=self.publish(release_id,first['activation_token'])
        status,explorer=self.request('GET','/api/explorer')
        self.assertEqual(status,200);self.assertEqual(explorer['summary']['corpus_id'],new['corpus_id'])
        status,result=self.request('POST','/api/website-search',dict(query='Шинэ зарлал'))
        self.assertEqual(status,200);self.assertTrue(result['matches'])
        self.assertIn('Шинэ зарлал',result['matches'][0]['excerpt'])

    def test_admin_routes_remain_blocked_in_device_gateway_allowlist(self):
        for path in ('/admin','/admin.js','/api/admin/state','/api/admin/content','/api/admin/stage',
                     '/api/admin/validate','/api/admin/publish','/api/admin/rollback'):
            for method in ('GET','POST'):
                with self.subTest(method=method,path=path):
                    self.assertFalse(allowed_path(method,path))

    def test_old_clarification_cannot_be_replayed_after_rollback_to_same_data(self):
        release_id=self.stage('ambiguous fee fixture')
        value=json.loads(json.dumps(self.baseline))
        for key,question,answer in (
                ('admission','Элсэлтийн бүртгэлийн хураамж хэд вэ?','Тестийн элсэлтийн хариулт.'),
                ('olympiad','Олимпиадын бүртгэлийн хураамж хэд вэ?','Тестийн олимпиадын хариулт.')):
            item=json.loads(json.dumps(value['faqs'][0]))
            item.update(faq_id='test.'+key,question=question,answer=answer,
                        question_aliases=['Бүртгэлийн хураамж хэд вэ?'])
            value['faqs'].append(item)
        status,result=self.admin('import-content',dict(release_id=release_id,content=value))
        self.assertEqual(status,200,result);self.seal(release_id)
        first=self.publish(release_id)
        ambiguous=self.route('Бүртгэлийн хураамж хэд вэ?')
        self.assertEqual(ambiguous['route'],'D',ambiguous)
        capability=ambiguous['conversation']['clarification_id']
        self.assertIsNotNone(capability,ambiguous)
        second_id=self.stage('same data new activation',first['activation_token']);self.seal(second_id)
        second=self.publish(second_id,first['activation_token'])
        self.publish(first['release_id'],second['activation_token'],'rollback')
        status,result=self.request('POST','/api/route',dict(query='Элсэлтийнх',clarification_id=capability))
        self.assertEqual(status,409,result)


if __name__ == '__main__':
    unittest.main()
