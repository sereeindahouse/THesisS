import unittest
import test_demo_server as server_fixture


class ExplorerHTTPTests(unittest.TestCase):
    def setUp(self):
        self.helper=server_fixture.DemoServerTests();self.helper.setUp()
        for name,content in [('data.html',"<html lang='mn'>Эхийн атлас</html>"),
                             ('data.css','body{color:inherit}'),('data.js','/*local fixture*/')]:
            (self.helper.root/'demo'/name).write_text(content,encoding='utf-8')
        self.request=self.helper.request

    def tearDown(self):self.helper.tearDown()

    def test_catalogue_missing_corpus_honest_and_no_private_content(self):
        status,result=self.request('GET','/api/explorer')
        self.assertEqual(status,200)
        self.assertFalse(result['summary']['available'])
        self.assertEqual(result['summary']['curated']['faqs'],1)
        self.assertEqual(result['sources'],[])
        self.assertNotIn('must not be served',str(result))

    def test_allowlisted_dashboard_assets_and_closed_file_surface(self):
        for route in ['/data','/data.html','/data.css','/data.js']:
            self.assertEqual(self.request('GET',route)[0],200)
        for route in ['/private.txt','/data/../private.txt','/data.js/../private.txt',
                      '/api/explorer/document/../../private.txt','/CORE/database/website.db']:
            self.assertEqual(self.request('GET',route)[0],404)

    def test_catalogue_and_preview_reject_cross_site_and_wrong_host(self):
        for route in ['/data','/api/explorer','/api/explorer/document/png-'+'a'*20]:
            with self.subTest(route=route):
                self.assertEqual(self.request('GET',route,headers={'Sec-Fetch-Site':'cross-site'})[0],403)
                self.assertEqual(self.request('GET',route,headers={'Host':'evil.example'})[0],403)
