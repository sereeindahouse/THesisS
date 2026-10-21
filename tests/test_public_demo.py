"""Real HTTP ingress tests: the external tunnel alone provides browser HTTPS."""
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
import socket
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from tools import serve_public_demo as gateway


class ListeningFixture:
    def page_bytes(self): return b'<html>Listening fixture</html>'
    def manifest(self): return {'samples': [{'id': 'sample-a'}], 'human_review': None}
    def audio(self, identity):
        if identity != 'sample-a': raise ValueError()
        return b'fixture mp3', 'audio/mpeg'
    def save_review(self, body):
        if not isinstance(body, dict) or body != {'listened': True}: raise ValueError()
        return {'saved': True, 'human_self_report': True}


class PublicGatewayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.results = Path(self.temp.name)/'device-results'
        self.token = secrets.token_urlsafe(40)
        self.origin = 'https://fixture-test.trycloudflare.com'
        self.host = 'fixture-test.trycloudflare.com'
        self.calls = []
        self.backend_body = None
        self.backend_status = 200
        owner = self
        class Backend(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def handle_request(self):
                count = int(self.headers.get('Content-Length', '0'))
                owner.calls.append(dict(method=self.command, path=self.path,
                    headers=dict(self.headers.items()), body=self.rfile.read(count)))
                value = owner.backend_body
                if value is None:
                    value = json.dumps(dict(backend=True, local_review_writes_supported=True,
                        voice={'private_storage': 'private fixture path'})).encode()
                self.send_response(owner.backend_status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(value)))
                self.end_headers(); self.wfile.write(value)
            do_GET = handle_request
            do_POST = handle_request
        self.backend = ThreadingHTTPServer(('127.0.0.1', 0), Backend)
        self.backend.daemon_threads = True
        self.backend_thread = threading.Thread(target=self.backend.serve_forever, daemon=True)
        self.backend_thread.start()
        self.addCleanup(self.stop_server, self.backend, self.backend_thread)
        self.server = gateway.make_gateway(port=0, backend_port=self.backend.server_port,
            token=self.token, external_origin=self.origin, lifetime=60,
            listening_trial=ListeningFixture(), result_dir=self.results)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start(); self.addCleanup(self.stop_server, self.server, self.thread)

    @staticmethod
    def stop_server(server, thread):
        server.shutdown(); server.server_close(); thread.join(timeout=3)

    def request(self, method, path, body=None, headers=None, authenticated=True):
        headers = dict(headers or {})
        headers.setdefault('Host', self.host)
        if authenticated: headers.setdefault('Cookie', gateway.COOKIE+'='+self.token)
        if method == 'POST':
            headers.setdefault('Origin', self.origin)
            headers.setdefault('Content-Type', 'application/json')
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=4)
        try:
            connection.request(method, path, body, headers)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally: connection.close()

    def raw(self, method, path, extra, body=b'', origin=True):
        lines = [f'{method} {path} HTTP/1.1', 'Host: '+self.host,
            'Cookie: '+gateway.COOKIE+'='+self.token,
            *(['Origin: '+self.origin] if origin else []), 'Connection: close', *extra, '', '']
        with socket.create_connection(('127.0.0.1', self.server.server_port), timeout=4) as connection:
            connection.sendall('\r\n'.join(lines).encode('latin-1')+body)
            response = http.client.HTTPResponse(connection); response.begin()
            return response.status, response.read()

    def test_authentication_bootstrap_and_secure_cookie_never_forward(self):
        self.assertEqual(self.server.server_address[0], '127.0.0.1')
        self.assertEqual(self.request('GET', '/api/status', authenticated=False)[0], 401)
        self.assertEqual(self.request('GET', '/connect/wrong', authenticated=False)[0], 403)
        code, headers, body = self.request('GET', '/connect/'+self.token,
            headers={'Sec-Fetch-Site': 'cross-site'}, authenticated=False)
        self.assertEqual(code, 200)
        cookie = headers['Set-Cookie']
        for flag in ('Secure', 'HttpOnly', 'SameSite=Strict', 'Path=/', 'Max-Age='):
            self.assertIn(flag, cookie)
        self.assertNotIn('Domain=', cookie)
        self.assertIn(b'history.replaceState', body)
        self.assertIn(b'/listening', body)
        self.assertNotIn(self.token.encode(), body)
        self.assertEqual(headers['Referrer-Policy'], 'no-referrer')
        self.assertEqual(headers['X-Robots-Tag'], 'noindex, nofollow, noarchive')
        self.assertFalse(self.calls)

    def test_host_origin_duplicate_and_cross_site_are_rejected_before_backend(self):
        for headers in ({'Host': 'attacker.invalid'}, {'Origin': 'https://attacker.invalid'},
                        {'Sec-Fetch-Site': 'cross-site'}):
            with self.subTest(headers=headers):
                self.assertEqual(self.request('GET', '/api/status', headers=headers)[0], 403)
        self.assertEqual(self.raw('POST', '/api/route', ['Content-Length: 2'], b'{}', origin=False)[0], 403)
        self.assertEqual(self.raw('POST', '/api/route', ['Origin: '+self.origin, 'Content-Length: 2'], b'{}')[0], 403)
        self.assertEqual(self.raw('GET', '/api/status', ['Host: '+self.host])[0], 403)
        self.assertFalse(self.calls)

    def test_private_paths_and_methods_cannot_escape_allowlist(self):
        for path in ('/api/review', '/api/review/stt-audio/q04', '/api/review/tts-audio/q01',
                     '/audio/q04.wav', '/models/model.bin', '/token.txt', '/../../AGENTS.md',
                     '/demo/audio/q04.wav', '/api/voice/audio/'+'0'*32,
                     '/api/listening/audio/../../secret', '/api/status?debug=1',
                     'https://attacker.invalid/api/status'):
            with self.subTest(path=path):
                self.assertIn(self.request('GET', path)[0], (400, 403))
        self.assertEqual(self.request('POST', '/api/review/tts-confirm', b'{}')[0], 403)
        for method in ('PUT', 'DELETE', 'OPTIONS', 'HEAD'):
            self.assertEqual(self.request(method, '/api/status')[0], 405)
        self.assertFalse(self.calls)

    def test_proxy_uses_loopback_origin_drops_secrets_and_sanitizes_status(self):
        code, _, data = self.request('POST', '/api/route', b'{"query":"fixture"}',
            {'Authorization': 'secret', 'X-Private': 'secret'})
        self.assertEqual(code, 200)
        row = self.calls[-1]
        self.assertEqual(row['headers']['Host'], f'127.0.0.1:{self.backend.server_port}')
        self.assertEqual(row['headers']['Origin'], f'http://127.0.0.1:{self.backend.server_port}')
        for header in ('Cookie', 'Authorization', 'X-Private'):
            self.assertNotIn(header, row['headers'])
        code, _, data = self.request('GET', '/api/status')
        self.assertEqual(code, 200)
        value = json.loads(data)
        self.assertFalse(value['local_review_writes_supported'])
        self.assertNotIn('private_storage', value['voice'])
        self.assertTrue(value['public_gateway']['https'])
        self.assertTrue(value['public_gateway']['temporary'])
        self.assertFalse(value['public_gateway']['private_review_available'])

    def test_only_audio_created_through_this_proxy_is_available_or_resettable(self):
        identity = 'a'*32
        path = '/api/voice/audio/'+identity
        self.assertEqual(self.request('GET', path)[0], 403)
        self.assertEqual(self.request('POST', '/api/voice/reset', json.dumps({'ids': [identity]}).encode())[0], 400)
        self.assertFalse(self.calls)
        self.backend_body = json.dumps({'id': identity, 'audio_url': path}).encode()
        self.assertEqual(self.request('POST', '/api/voice/transcribe', b'fixture audio')[0], 200)
        self.assertEqual(self.request('GET', path)[0], 200)
        self.assertEqual(self.request('POST', '/api/voice/reset', json.dumps({'ids': [identity]}).encode())[0], 200)
        self.backend_body = b'{"id":"invalid","audio_url":"/private"}'
        self.assertEqual(self.request('POST', '/api/voice/speak', b'{}')[0], 502)

    def test_optional_listening_routes_are_local_and_require_explicit_self_report(self):
        for path in ('/listening', '/api/listening', '/api/listening/audio/sample-a'):
            self.assertEqual(self.request('GET', path, authenticated=False)[0], 401)
            self.assertEqual(self.request('GET', path)[0], 200)
        self.assertEqual(self.request('GET', '/api/listening/audio/unknown')[0], 404)
        self.assertEqual(self.request('POST', '/api/listening/review', b'{"listened":false}')[0], 400)
        code, _, data = self.request('POST', '/api/listening/review', b'{"listened":true}')
        self.assertEqual(code, 200)
        self.assertTrue(json.loads(data)['human_self_report'])
        self.assertFalse(self.calls)

    def test_framing_and_body_limits_prevent_backend_requests(self):
        for method, headers in (
            ('POST', ['Content-Length: 2', 'Content-Length: 2']),
            ('POST', ['Content-Length: 2', 'Transfer-Encoding: chunked']),
            ('POST', ['Content-Length: -1']), ('POST', ['Content-Length: 24577']),
            ('POST', ['Content-Length: '+'9'*5000]),
            ('GET', ['Content-Length: 2']), ('GET', ['Transfer-Encoding: chunked'])):
            with self.subTest(method=method, headers=[item[:60] for item in headers]):
                self.assertEqual(self.raw(method, '/api/route' if method == 'POST' else '/api/status', headers, b'{}')[0], 400)
        self.assertEqual(self.raw('POST', '/api/voice/transcribe',
            ['Content-Length: '+str(gateway.MAX_AUDIO+1)])[0], 400)
        self.assertFalse(self.calls)

    def test_device_check_requires_real_explicit_self_report_and_keeps_false_results(self):
        self.assertEqual(self.request('GET', '/device-check', authenticated=False)[0], 401)
        code, _, page = self.request('GET', '/device-check')
        self.assertEqual(code, 200); self.assertIn(b'getUserMedia', page)
        value = dict(secure_context=True, media_devices=True, mic_granted=False,
            page_fits=False, answer_seen=False, audio_heard=False,
            human_reported=True, platform='Android')
        for invalid in ({}, dict(value, human_reported=False), dict(value, audio_heard='true')):
            self.assertEqual(self.request('POST', '/device-result', json.dumps(invalid).encode())[0], 400)
        self.assertEqual(list(self.results.iterdir()), [])
        code, _, data = self.request('POST', '/device-result', json.dumps(value).encode())
        self.assertEqual(code, 200)
        saved = json.loads((self.results/(json.loads(data)['id']+'.json')).read_text(encoding='utf-8'))
        self.assertEqual(saved['source'], 'user_device_browser_self_report')
        self.assertIs(saved['independent_observer'], False)
        self.assertIs(saved['audio_heard'], False)
        self.assertIs(saved['mic_granted'], False)
        self.assertFalse(self.calls)

    def test_expired_trial_and_bounded_request_rate(self):
        with patch.object(gateway.time, 'monotonic', return_value=time.monotonic()+8000):
            self.assertEqual(self.request('GET', '/api/status')[0], 410)
        self.assertFalse(self.calls)
        for _ in range(180):
            self.assertEqual(self.request('GET', '/listening')[0], 200)
        self.assertEqual(self.request('GET', '/listening')[0], 429)

    def test_backend_invalid_json_failure_and_size_are_sanitized(self):
        self.backend_status = 503; self.backend_body = b'{"error":"fixture unavailable"}'
        self.assertEqual(self.request('POST', '/api/route', b'{}')[0], 503)
        self.backend_status = 200
        for value in (b'[]', b'not JSON'):
            self.backend_body = value
            self.assertEqual(self.request('GET', '/api/status')[0], 502)
        self.backend_body = b'x'*(gateway.MAX_RESPONSE+1)
        self.assertEqual(self.request('GET', '/')[0], 502)

    def test_configuration_rejects_unbounded_ttl_weak_tokens_and_main_backend(self):
        base = dict(port=0, backend_port=self.backend.server_port, token=self.token,
                    external_origin=self.origin, lifetime=60)
        for changed in ({'backend_port': 8765}, {'lifetime': 7201}, {'lifetime': True},
                        {'token': 'short'}, {'external_origin': 'http://fixture.trycloudflare.com'},
                        {'external_origin': 'https://fixture.trycloudflare.com/'},
                        {'external_origin': 'https://user:password@fixture.trycloudflare.com'},
                        {'external_origin': 'https://127.0.0.1'},
                        {'external_origin': 'https://fixture.trycloudflare.com:443'}):
            with self.subTest(changed=changed):
                with self.assertRaises(ValueError): gateway.make_gateway(**dict(base, **changed))


if __name__ == '__main__': unittest.main()
