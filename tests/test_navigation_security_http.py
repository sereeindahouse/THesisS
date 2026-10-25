"""Temporary HTTP fixtures; no real browser, provider or production data."""
import unittest
import test_demo_server as server_fixture


class PublicNavigationSecurityTests(unittest.TestCase):
    def setUp(self):
        self.helper=server_fixture.DemoServerTests();self.helper.setUp()
        self.request=self.helper.request
        self.local='http://127.0.0.1:'+str(self.helper.server.server_port)
        for name,content in [('data.html','<html>Public catalogue shell</html>'),
                             ('data.js','/* public script */'),('data.css','body{}'),
                             ('admin.html','<html>Admin fixture</html>'),
                             ('admin.js','/* admin fixture */'),('admin.css','body{}')]:
            (self.helper.root/'demo'/name).write_text(content,encoding='utf-8')
        self.navigation={'Sec-Fetch-Site':'cross-site','Sec-Fetch-Mode':'navigate',
                         'Sec-Fetch-Dest':'document','Referer':'https://outside.example/link'}

    def tearDown(self):self.helper.tearDown()

    def test_external_top_level_navigation_reads_only_four_public_html_shells(self):
        for path in ('/','/index.html','/data','/data.html'):
            with self.subTest(path=path):
                status,body=self.request('GET',path,headers=self.navigation)
                self.assertEqual(status,200)
                self.assertIsInstance(body,bytes)
                self.assertNotIn(b'must not be served',body)

    def test_query_or_fragment_target_cannot_turn_public_shell_into_api(self):
        status,body=self.request('GET','/data?next=/api/admin/state',headers=self.navigation)
        self.assertEqual(status,200);self.assertEqual(body,b'<html>Public catalogue shell</html>')

    def test_navigation_never_overrides_explicit_nonlocal_or_null_origin(self):
        for origin in ('https://outside.example','null','http://127.0.0.1.attacker.example'):
            for path in ('/','/data'):
                with self.subTest(origin=origin,path=path):
                    self.assertEqual(self.request('GET',path,headers={**self.navigation,'Origin':origin})[0],403)

    def test_valid_local_origin_and_host_alias_still_work(self):
        self.assertEqual(self.request('GET','/data',headers={**self.navigation,'Origin':self.local})[0],200)
        self.assertEqual(self.request('GET','/data',headers={**self.navigation,'Host':'localhost:'+str(self.helper.server.server_port)})[0],200)

    def test_wrong_host_is_rejected_before_public_navigation(self):
        self.assertEqual(self.request('GET','/data',headers={**self.navigation,'Host':'attacker.example'})[0],403)

    def test_missing_or_other_fetch_context_does_not_get_navigation_exception(self):
        for change in ({'Sec-Fetch-Mode':'cors'},{'Sec-Fetch-Mode':'no-cors'},
                       {'Sec-Fetch-Dest':'iframe'},{'Sec-Fetch-Dest':'frame'},
                       {'Sec-Fetch-Dest':'empty'},{'Sec-Fetch-Dest':'script'}):
            with self.subTest(change=change):
                self.assertEqual(self.request('GET','/data',headers={**self.navigation,**change})[0],403)
        for missing in ('Sec-Fetch-Mode','Sec-Fetch-Dest'):
            headers={k:v for k,v in self.navigation.items() if k!=missing}
            with self.subTest(missing=missing):self.assertEqual(self.request('GET','/data',headers=headers)[0],403)

    def test_public_assets_are_not_cross_site_navigation_documents(self):
        for path in ('/data.js','/data.css','/demo/audio/q01.wav'):
            with self.subTest(path=path):self.assertEqual(self.request('GET',path,headers=self.navigation)[0],403)

    def test_local_document_can_load_its_static_assets_normally(self):
        for path in ('/data.js','/data.css'):
            headers={'Sec-Fetch-Site':'same-origin','Sec-Fetch-Mode':'no-cors',
                     'Sec-Fetch-Dest':'script' if path.endswith('.js') else 'style','Referer':self.local+'/data'}
            with self.subTest(path=path):self.assertEqual(self.request('GET',path,headers=headers)[0],200)

    def test_private_api_and_media_do_not_inherit_public_navigation_permission(self):
        for path in ('/api/status','/api/explorer','/api/explorer/tree','/api/review',
                     '/api/teachers','/api/voice/audio/'+'a'*32,
                     '/api/review/stt-audio/q01','/api/teacher-media/teacher-'+'a'*24,
                     '/api/explorer/document/png-'+'a'*20):
            with self.subTest(path=path):self.assertEqual(self.request('GET',path,headers=self.navigation)[0],403)

    def test_admin_document_assets_and_state_remain_cross_site_denied(self):
        for path in ('/admin','/admin.html','/admin.js','/admin.css','/api/admin/state','/api/admin/content'):
            with self.subTest(path=path):self.assertEqual(self.request('GET',path,headers=self.navigation)[0],403)

    def test_referrer_never_grants_an_api_exception(self):
        for referrer in (self.local+'/data','https://outside.example/link'):
            with self.subTest(referrer=referrer):
                self.assertEqual(self.request('GET','/api/status',headers={**self.navigation,'Referer':referrer})[0],403)

    def test_nonlocal_origin_still_rejected_when_fetch_site_says_same_origin(self):
        for path in ('/data','/api/status','/api/explorer','/api/admin/state'):
            with self.subTest(path=path):
                self.assertEqual(self.request('GET',path,headers={'Sec-Fetch-Site':'same-origin','Origin':'https://outside.example'})[0],403)

    def test_post_requests_never_get_the_navigation_exception_even_with_admin_token(self):
        status,state=self.request('GET','/api/admin/state');self.assertEqual(status,200)
        headers={**self.navigation,'X-Admin-Token':state['csrf_token']}
        for path,body in [('/api/search',{'query':'fixture'}),('/api/route',{'query':'fixture'}),
                          ('/api/voice/reset',{'ids':[]}),('/api/admin/stage',{'label':'blocked','expected_active':None})]:
            with self.subTest(path=path):self.assertEqual(self.request('POST',path,body,headers=headers)[0],403)

    def test_private_and_encoded_paths_are_not_public_html_aliases(self):
        for path in ('/private.txt','/content.db','/api%2fstatus','/data/../api/status',
                     '/data%2f..%2fprivate.txt','/admin?from=/data'):
            with self.subTest(path=path):self.assertEqual(self.request('GET',path,headers=self.navigation)[0],403)


if __name__=='__main__':unittest.main()
