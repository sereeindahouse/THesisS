import io
import json
import unittest
from unittest.mock import patch, MagicMock
from email.message import Message
from open_demo import probe_demo


class LauncherIdentityTests(unittest.TestCase):
    def call(self, backend, mode='local_development'):
        response=MagicMock()
        response.status=200
        response.headers=Message()
        response.headers['Content-Type']='application/json'
        response.read.return_value=json.dumps(dict(mode=mode,content_database_readonly=True,
            generated=False,llm_calls=0,content={},retrieval=dict(live_backend=backend))).encode()
        response.__enter__.return_value=response
        opener=MagicMock()
        opener.open.return_value=response
        with patch('open_demo.socket.create_connection'),patch('open_demo.urllib.request.build_opener',return_value=opener):
            return probe_demo()

    def test_existing_and_new_retrieval_backends_recognized(self):
        for backend in ['bm25','bm25_mongolian','bm25+e5_rrf']:
            self.assertEqual(self.call(backend)['retrieval']['live_backend'],backend)

    def test_unrelated_service_not_accepted(self):
        with self.assertRaises(RuntimeError): self.call('bm25',mode='other-service')
        with self.assertRaises(RuntimeError): self.call('unknown')

    def test_malformed_backend_not_accepted(self):
        with self.assertRaises(RuntimeError): self.call([])

if __name__=='__main__': unittest.main()
