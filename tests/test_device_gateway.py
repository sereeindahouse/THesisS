"""Real loopback HTTPS with a temporary explicit test CA, never LAN or trust-store edits."""
from contextlib import redirect_stderr
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import secrets
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from tools import serve_device_demo as gateway


class DeviceGatewayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cert_temp = tempfile.TemporaryDirectory()
        cls.certificate_root = Path(cls.cert_temp.name)
        executable = Path('C:/Program Files/Git/usr/bin/openssl.exe')
        openssl = str(executable) if executable.is_file() else shutil.which('openssl')
        if not openssl:
            cls.cert_temp.cleanup()
            raise unittest.SkipTest('Local OpenSSL is required for an isolated TLS fixture.')
        cls.cert, cls.key = cls.certificate_root/'test-ca.pem', cls.certificate_root/'private-key.pem'
        subprocess.run([openssl,'req','-x509','-newkey','rsa:2048','-nodes','-days','1',
                        '-subj','/CN=NMCT loopback test only','-addext','subjectAltName=IP:127.0.0.1',
                        '-keyout',str(cls.key),'-out',str(cls.cert)],
                       check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=20)
        cls.context = ssl.create_default_context(cafile=str(cls.cert))

    @classmethod
    def tearDownClass(cls):
        cls.cert_temp.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.records = self.root/'results'
        self.token = secrets.token_urlsafe(40)
        self.backend_calls = []
        self.backend_status = 200
        self.backend_body = None
        self.backend_invalid_http = False
        owner = self
        class Backend(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            def log_message(self,*args):pass
            def serve(self):
                count=int(self.headers.get('Content-Length','0'))
                owner.backend_calls.append(dict(method=self.command,path=self.path,
                    headers=dict(self.headers.items()),body=self.rfile.read(count)))
                if owner.backend_invalid_http:
                    self.wfile.write(b'not-an-http-status\r\n\r\n');self.close_connection=True;return
                value = owner.backend_body
                if value is None:
                    value=json.dumps(dict(backend=True,local_review_writes_supported=True)).encode()
                self.send_response(owner.backend_status)
                self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(value)))
                self.end_headers();self.wfile.write(value)
            do_GET=serve
            do_POST=serve
        self.backend=ThreadingHTTPServer(('127.0.0.1',0),Backend)
        self.backend.daemon_threads=True
        self.backend_port=self.backend.server_port
        self.backend_thread=threading.Thread(target=self.backend.serve_forever,daemon=True)
        self.backend_thread.start()
        self.addCleanup(self.stop_server,self.backend,self.backend_thread)
        with socket.socket() as probe:
            probe.bind(('127.0.0.1',0));self.port=probe.getsockname()[1]
        self.server=gateway.make_gateway(bind='127.0.0.1',port=self.port,backend_port=self.backend_port,
            token=self.token,cert=self.cert,key=self.key,result_dir=self.records,lifetime=60)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.stop_server,self.server,self.thread)
        self.origin=f'https://127.0.0.1:{self.port}'

    @staticmethod
    def stop_server(server,thread):
        server.shutdown();server.server_close();thread.join(timeout=3)

    def request(self,method,path,body=None,headers=None,*,authenticated=True):
        headers=dict(headers or {})
        if authenticated:headers.setdefault('Cookie',gateway.COOKIE+'='+self.token)
        if method=='POST':
            headers.setdefault('Origin',self.origin)
            headers.setdefault('Content-Type','application/json')
        connection=http.client.HTTPSConnection('127.0.0.1',self.port,context=self.context,timeout=4)
        try:
            connection.request(method,path,body,headers)
            response=connection.getresponse()
            return response.status,dict(response.getheaders()),response.read()
        finally:connection.close()

    def raw_request(self,method,path,extra,body=b'',*,include_origin=True):
        lines=[f'{method} {path} HTTP/1.1',f'Host: 127.0.0.1:{self.port}',
            f'Cookie: {gateway.COOKIE}={self.token}',
            *([f'Origin: {self.origin}'] if include_origin else []),
            'Connection: close',*extra,'','']
        with socket.create_connection(('127.0.0.1',self.port),timeout=4) as raw:
            with self.context.wrap_socket(raw,server_hostname='127.0.0.1') as secure:
                secure.sendall('\r\n'.join(lines).encode('latin-1')+body)
                response=http.client.HTTPResponse(secure);response.begin()
                return response.status,response.read()

    def test_real_tls_explicit_ca_auth_redirect_and_cookie_attributes(self):
        code,_,_=self.request('GET','/api/status',authenticated=False)
        self.assertEqual(code,401);self.assertFalse(self.backend_calls)
        code,headers,body=self.request('GET','/connect/'+self.token,authenticated=False)
        self.assertEqual(code,303);self.assertEqual(body,b'')
        self.assertEqual(headers['Location'],'/device-check')
        cookie=headers['Set-Cookie']
        for flag in ('Secure','HttpOnly','SameSite=Strict','Path=/','Max-Age='):
            self.assertIn(flag,cookie)
        self.assertTrue(cookie.startswith(gateway.COOKIE+'='))
        self.assertNotIn('Domain=',cookie)
        code,_,body=self.request('GET','/device-check')
        self.assertEqual(code,200);self.assertIn(b'getUserMedia',body)
        self.assertNotIn(self.token.encode(),body)

    def test_untrusted_certificate_does_not_silently_disable_tls_validation(self):
        connection=http.client.HTTPSConnection('127.0.0.1',self.port,timeout=4)
        try:
            with self.assertRaises(ssl.SSLCertVerificationError):
                connection.request('GET','/api/status')
        finally:connection.close()
        self.assertFalse(self.backend_calls)

    def test_wrong_host_origin_crosssite_and_expired_session_block_before_backend(self):
        for headers in ({'Host':'attacker.invalid'}, {'Origin':'https://attacker.invalid'},
                        {'Sec-Fetch-Site':'cross-site'}):
            with self.subTest(headers=headers):
                self.assertEqual(self.request('GET','/api/status',headers=headers)[0],403)
        self.assertEqual(self.request('POST','/api/route',b'{}',{'Origin':'https://attacker.invalid'})[0],403)
        self.assertEqual(self.raw_request('POST','/api/route',
            ['Origin: https://attacker.invalid','Content-Length: 2'],b'{}')[0],403)
        self.assertEqual(self.raw_request('POST','/api/route',
            ['Content-Length: 2'],b'{}',include_origin=False)[0],403)
        self.assertEqual(self.raw_request('GET','/api/status',[f'Host: 127.0.0.1:{self.port}'])[0],403)
        deadline=time.monotonic()+8000
        with patch.object(gateway.time,'monotonic',return_value=deadline):
            self.assertEqual(self.request('GET','/api/status')[0],410)
        self.assertFalse(self.backend_calls)

    def test_private_review_files_and_unlisted_methods_never_reach_backend(self):
        for path in ('/api/review','/api/review/stt-audio/q04','/models/model.bin',
                     '/audio/q04.wav','/private-key.pem','/token.txt','/manifest.json',
                     '/api/explorer/document/../../private-key.pem'):
            with self.subTest(path=path):self.assertEqual(self.request('GET',path)[0],403)
        self.assertEqual(self.request('POST','/api/review/stt-confirm',b'{}')[0],403)
        self.assertEqual(self.request('PUT','/api/route',b'{}')[0],405)
        self.assertEqual(self.request('DELETE','/api/route')[0],405)
        self.assertFalse(self.backend_calls)

    def test_valid_proxy_uses_only_loopback_host_origin_and_drops_session_secrets(self):
        query=b'{"query":"invented test"}'
        code,_,body=self.request('POST','/api/route',query,
            {'Authorization':'private-client-secret','X-Do-Not-Forward':'secret'})
        self.assertEqual(code,200);self.assertTrue(json.loads(body)['backend'])
        row=self.backend_calls[-1]
        self.assertEqual(row['body'],query)
        self.assertEqual(row['headers']['Host'],f'127.0.0.1:{self.backend_port}')
        self.assertEqual(row['headers']['Origin'],f'http://127.0.0.1:{self.backend_port}')
        for name in ('Cookie','Authorization','X-Do-Not-Forward'):
            self.assertNotIn(name,row['headers'])
        code,_,body=self.request('GET','/api/status')
        value=json.loads(body)
        self.assertEqual(code,200);self.assertFalse(value['local_review_writes_supported'])
        self.assertFalse(value['device_gateway']['private_review_available'])
        self.assertTrue(value['device_gateway']['https'])

    def test_duplicate_lengths_transfer_encoding_and_get_body_framing_are_rejected(self):
        for method,headers in (
            ('POST',['Content-Length: 2','Content-Length: 2']),
            ('POST',['Content-Length: 2','Transfer-Encoding: chunked']),
            ('POST',['Content-Length: ²']),('POST',['Content-Length: '+'9'*5000]),
            ('POST',['Content-Length: -1']),('POST',['Content-Length: 24577']),
            ('GET',['Content-Length: 2','Content-Length: 2']),
            ('GET',['Transfer-Encoding: chunked'])):
            with self.subTest(method=method,headers=[value[:60] for value in headers]):
                self.assertEqual(self.raw_request(method,'/api/route' if method=='POST' else '/api/status',headers,b'{}')[0],400)
        self.assertFalse(self.backend_calls)
        self.assertEqual(self.raw_request('POST','/api/voice/transcribe',
            ['Content-Length: '+str(gateway.MAX_AUDIO+1)])[0],400)

    def test_device_result_requires_explicit_booleans_and_records_false_human_answers_honestly(self):
        valid=dict(secure_context=True,media_devices=True,mic_granted=False,
            page_fits=False,answer_seen=False,audio_heard=False,human_reported=True,platform='other')
        for value in ({},{'human_reported':True},dict(valid,audio_heard='true'),
                      dict(valid,human_reported=False),dict(valid,unexpected=True)):
            with self.subTest(value=value):
                self.assertEqual(self.request('POST','/device-result',json.dumps(value).encode())[0],400)
        self.assertEqual(list(self.records.iterdir()),[])
        code,_,body=self.request('POST','/device-result',json.dumps(valid).encode())
        self.assertEqual(code,200);self.assertTrue(json.loads(body)['saved'])
        records=list(self.records.glob('*.json'));self.assertEqual(len(records),1)
        saved=json.loads(records[0].read_text(encoding='utf-8'))
        for name in ('mic_granted','page_fits','answer_seen','audio_heard'):
            self.assertIs(saved[name],False)
        self.assertEqual(saved['source'],'user_device_browser_self_report')
        self.assertIs(saved['independent_observer'],False)
        self.assertFalse(self.backend_calls)

    def test_device_result_storage_failure_is_not_reported_as_saved(self):
        valid=dict(secure_context=True,media_devices=True,mic_granted=False,
            page_fits=False,answer_seen=False,audio_heard=False,human_reported=True,platform='other')
        original_open=Path.open
        def deny_result(path,*args,**kwargs):
            if path.parent==self.records:raise PermissionError('fixture disk failure')
            return original_open(path,*args,**kwargs)
        with patch.object(Path,'open',new=deny_result):
            code,_,body=self.request('POST','/device-result',json.dumps(valid).encode())
        self.assertEqual(code,503);self.assertNotIn('saved',json.loads(body))
        self.assertEqual(list(self.records.iterdir()),[])

    def test_backend_failure_invalid_status_json_and_http_are_sanitized(self):
        self.backend_status=503;self.backend_body=b'{"error":"test backend unavailable"}'
        self.assertEqual(self.request('POST','/api/route',b'{}')[0],503)
        self.backend_status=200
        for value in (b'not JSON',b'[]'):
            self.backend_body=value
            with self.subTest(value=value):self.assertEqual(self.request('GET','/api/status')[0],502)
        self.backend_invalid_http=True
        self.assertEqual(self.request('GET','/api/status')[0],502)

    def test_capability_certificate_keys_and_failed_requests_are_not_logged_or_served(self):
        logs=io.StringIO()
        with redirect_stderr(logs):
            self.assertEqual(self.request('GET','/connect/'+self.token,authenticated=False)[0],303)
            self.assertEqual(self.request('GET','/connect/wrong',authenticated=False)[0],403)
            for path in ('/'+self.cert.name,'/'+self.key.name,'/device-token.txt'):
                self.assertEqual(self.request('GET',path)[0],403)
        self.assertEqual(logs.getvalue(),'')
        self.assertFalse(self.backend_calls)


if __name__ == '__main__':unittest.main()
