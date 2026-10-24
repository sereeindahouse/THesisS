import io
import json
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from email.message import Message
from open_demo import probe_demo, start_or_reuse, DemoProbeTimeout


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

    def test_owned_cold_start_retries_timeout_but_not_wrong_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'demo').mkdir()
            (root/'demo_server.py').write_text('# fixture')
            (root/'demo/index.html').write_text('fixture')
            ready=dict(content=dict(available=True))
            for first,success in ((DemoProbeTimeout('cold'),True),(RuntimeError('wrong identity'),False)):
                child=MagicMock();child.poll.return_value=None;child.pid=12345
                with patch('open_demo.probe_demo',side_effect=[None,first,ready]), \
                     patch('open_demo.ensure_database',return_value=False), \
                     patch('tools.start_local_llm.start_local_llm'), \
                     patch('open_demo.subprocess.Popen',return_value=child):
                    if success:
                        self.assertFalse(start_or_reuse(root)['reused_server'])
                        child.terminate.assert_not_called()
                    else:
                        with self.assertRaisesRegex(RuntimeError,'wrong identity'):start_or_reuse(root)
                        child.terminate.assert_called_once()

if __name__=='__main__': unittest.main()
