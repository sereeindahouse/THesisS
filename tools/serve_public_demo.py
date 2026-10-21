"""Short-lived authenticated loopback ingress for an external HTTPS tunnel.

The external tunnel terminates ordinary browser-trusted HTTPS. This process binds
only 127.0.0.1 and never serves a filesystem directory, certificates or old reviews.
Start a separate demo backend for this trial; never tunnel the main demo directly.
"""
import argparse
from collections import deque
from datetime import datetime, timezone
import hmac
from http.client import HTTPConnection, HTTPException
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import secrets
import threading
import time
from urllib.parse import urlsplit

try:
    from tools.serve_device_demo import allowed_path, MAX_AUDIO, CHECK_PAGE
except ModuleNotFoundError:
    from serve_device_demo import allowed_path, MAX_AUDIO, CHECK_PAGE

COOKIE = '__Host-nmct_public'
MAX_RESPONSE = 12 * 1024 * 1024


def validate_origin(value):
    """An exact public HTTPS hostname, with no credentials, port or URL suffix."""
    if not isinstance(value, str):
        raise ValueError('An exact HTTPS origin is required.')
    parts = urlsplit(value)
    if (parts.scheme != 'https' or parts.path or parts.query or parts.fragment
            or parts.username or parts.password or parts.port is not None
            or not parts.hostname or parts.netloc != parts.hostname
            or not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?', parts.hostname)
            or '.' not in parts.hostname or '..' in parts.hostname
            or parts.hostname.endswith(('.localhost', '.local', '.invalid'))):
        raise ValueError('Use a canonical public HTTPS origin without a path or port.')
    # Numeric addresses and local hostnames are not public browser-trusted domains.
    if re.fullmatch(r'[0-9.]+', parts.hostname):
        raise ValueError('Use a public DNS hostname.')
    return value, parts.hostname


def make_gateway(*, port, backend_port, token, external_origin, lifetime=7200,
                 listening_trial=None, result_dir=None):
    if (type(port) is not int or type(backend_port) is not int
            or not 0 <= port <= 65535 or not 1 <= backend_port <= 65535
            or backend_port in {8765, port}):
        raise ValueError('Use a separate loopback backend, never the main8765 server.')
    if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{40,100}', token):
        raise ValueError('Require a random capability of at least240bits.')
    if type(lifetime) is not int or not 60 <= lifetime <= 7200:
        raise ValueError('A public trial lasts60–7200seconds.')
    origin, host = validate_origin(external_origin)
    if result_dir is not None:
        result_dir = Path(result_dir).resolve()
        result_dir.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + lifetime
    expires_utc = datetime.fromtimestamp(time.time()+lifetime, timezone.utc).isoformat()
    audio_ids = set()
    lock = threading.Lock()
    requests = deque()
    slots = threading.BoundedSemaphore(2)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *args):
            pass  # No capability, cookie, query, IP, transcript or audio in logs.

        def send(self, code, body=b'', mime='application/json; charset=utf-8', extra=()):
            self.send_response(code)
            for name, value in [('Content-Type', mime), ('Content-Length', str(len(body))),
                    ('Cache-Control', 'no-store'), ('Referrer-Policy', 'no-referrer'),
                    ('X-Content-Type-Options', 'nosniff'),
                    ('X-Robots-Tag', 'noindex, nofollow, noarchive'),
                    ('Cross-Origin-Resource-Policy', 'same-origin'),
                    ('Permissions-Policy', 'microphone=(self), camera=()'),
                    ('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; media-src 'self' blob:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'"),
                    *extra]:
                self.send_header(name, value)
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True

        def fail(self, code, message):
            self.close_connection = True
            lengths = self.headers.get_all('Content-Length', [])
            if len(lengths) == 1 and re.fullmatch(r'[0-9]{1,10}', lengths[0]) and not self.headers.get('Transfer-Encoding'):
                remaining = int(lengths[0])-getattr(self, '_body_bytes_read', 0)
                if 0 < remaining <= 65536:
                    try:
                        self.connection.settimeout(0.25)
                        self.rfile.read(remaining)
                    except OSError:
                        pass
            self.send(code, json.dumps({'error': message}, ensure_ascii=False).encode(),
                      extra=[('Connection', 'close')])

        def preflight(self):
            self.connection.settimeout(15)
            if time.monotonic() >= deadline:
                self.fail(410, 'Түр HTTPS туршилтын хугацаа дууссан.'); return False
            if self.headers.get_all('Host', []) != [host]:
                self.fail(403, 'Хаяг таарахгүй байна.'); return False
            lengths = self.headers.get_all('Content-Length', [])
            if (self.headers.get('Transfer-Encoding') or len(lengths) > 1
                    or (self.command == 'GET' and lengths not in ([], ['0']))):
                self.fail(400, 'Хүсэлтийн framing буруу.'); return False
            if len(self.headers.get_all('Origin', [])) > 1 or self.headers.get('Origin') not in {None, origin}:
                self.fail(403, 'Өөр сайтаас дуудахгүй.'); return False
            bootstrap = self.command == 'GET' and self.path.startswith('/connect/')
            if self.headers.get('Sec-Fetch-Site') == 'cross-site' and not bootstrap:
                self.fail(403, 'Өөр сайтаас дуудахгүй.'); return False
            with lock:
                now = time.monotonic()
                while requests and now-requests[0] >= 60:
                    requests.popleft()
                if len(requests) >= 180:
                    self.fail(429, 'Хүсэлтийн хязгаарт хүрлээ. Түр хүлээнэ үү.'); return False
                requests.append(now)
            return True

        def authenticated(self):
            try:
                cookies = SimpleCookie(); cookies.load(self.headers.get('Cookie', ''))
                value = cookies[COOKIE].value if COOKIE in cookies else ''
            except CookieError:
                value = ''
            return hmac.compare_digest(value.encode('utf-8'), token.encode('ascii'))

        def do_GET(self):
            if not self.preflight(): return
            parts = urlsplit(self.path)
            path = parts.path
            if parts.query or parts.fragment or parts.scheme or parts.netloc:
                return self.fail(400, 'Query бүхий хаяг ашиглахгүй.')
            if path.startswith('/connect/'):
                if not hmac.compare_digest(path[len('/connect/'):].encode('utf-8'), token.encode('ascii')):
                    return self.fail(403, 'Холболтын код буруу.')
                landing = '/listening' if listening_trial is not None else '/'
                page = ('<!doctype html><html lang="mn"><meta charset="utf-8">'
                        '<meta name="viewport" content="width=device-width,initial-scale=1">'
                        '<title>Холбогдлоо</title><p><a href="'+landing+'">Үргэлжлүүлэх</a></p>'
                        '<script>history.replaceState(null,"","/");location.replace("'+landing+'");</script></html>')
                return self.send(200, page.encode(), 'text/html; charset=utf-8', extra=[('Set-Cookie',
                    f'{COOKIE}={token}; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age={int(max(0,deadline-time.monotonic()))}')])
            if not self.authenticated():
                return self.fail(401, 'Танд өгсөн хувийн HTTPS холбоосоор нээнэ үү.')
            if result_dir is not None and path == '/device-check':
                return self.send(200, CHECK_PAGE.encode(), 'text/html; charset=utf-8')
            if listening_trial is not None:
                try:
                    if path == '/listening':
                        return self.send(200, listening_trial.page_bytes(), 'text/html; charset=utf-8')
                    if path == '/api/listening':
                        return self.send(200, json.dumps(listening_trial.manifest(), ensure_ascii=False, allow_nan=False).encode())
                    match = re.fullmatch(r'/api/listening/audio/([A-Za-z0-9_-]{1,64})', path)
                    if match:
                        data, mime = listening_trial.audio(match[1])
                        if len(data) > MAX_RESPONSE: return self.fail(502, 'Дууны хэмжээ хэт том.')
                        return self.send(200, data, mime)
                except (ValueError, KeyError, OSError):
                    return self.fail(404, 'Сонсголын жишээ олдсонгүй.')
            match = re.fullmatch(r'/api/voice/audio/([0-9a-f]{32})', path)
            if match:
                with lock:
                    known = match[1] in audio_ids
                if not known: return self.fail(403, 'Зөвхөн энэ туршилтын дуу нээлттэй.')
            if not allowed_path('GET', path):
                return self.fail(403, 'Энэ файл эсвэл API туршилтад хаалттай.')
            self.forward(path)

        def do_POST(self):
            if not self.preflight(): return
            if not self.authenticated(): return self.fail(401, 'Холболтын эрх байхгүй.')
            if self.headers.get_all('Origin', []) != [origin]:
                return self.fail(403, 'HTTPS origin шаардлагатай.')
            path = self.path
            listening_save = listening_trial is not None and path == '/api/listening/review'
            device_save = result_dir is not None and path == '/device-result'
            if not listening_save and not device_save and not allowed_path('POST', path):
                return self.fail(403, 'Хаалттай API.')
            lengths = self.headers.get_all('Content-Length', [])
            maximum = MAX_AUDIO if path == '/api/voice/transcribe' else 24576
            if (len(lengths) != 1 or not re.fullmatch(r'[0-9]{1,10}', lengths[0])
                    or not 0 < int(lengths[0]) <= maximum):
                return self.fail(400, 'Хүсэлтийн хэмжээ эсвэл framing буруу.')
            try:
                body = self.rfile.read(int(lengths[0]))
            except OSError:
                return self.fail(408, 'Хүсэлтийг хүлээх хугацаа дууссан.')
            self._body_bytes_read = len(body)
            if len(body) != int(lengths[0]): return self.fail(400, 'Хүсэлт дутуу.')
            if device_save:
                try:
                    value = json.loads(body)
                    booleans = {'secure_context', 'media_devices', 'mic_granted', 'page_fits',
                                'answer_seen', 'audio_heard', 'human_reported'}
                    if (not isinstance(value, dict) or set(value)-booleans-{'platform', 'mic_error'}
                            or any(type(value.get(k)) is not bool for k in booleans)
                            or value['human_reported'] is not True
                            or value.get('platform') not in {'Android', 'other'}
                            or not isinstance(value.get('mic_error', ''), str)
                            or len(value.get('mic_error', '')) > 100):
                        raise ValueError()
                    identity = secrets.token_hex(12)
                    record = dict(value, created_utc=datetime.now(timezone.utc).isoformat(),
                        source='user_device_browser_self_report', independent_observer=False)
                    with (result_dir/(identity+'.json')).open('x', encoding='utf-8') as handle:
                        json.dump(record, handle, ensure_ascii=False, indent=2)
                    return self.send(200, json.dumps({'saved': True, 'id': identity}).encode())
                except (ValueError, TypeError, KeyError):
                    return self.fail(400, 'Өөрөө шалгасан boolean үр дүн шаардлагатай.')
                except OSError:
                    return self.fail(503, 'Төхөөрөмжийн тэмдэглэлийг хадгалж чадсангүй.')
            if listening_save:
                try:
                    value = listening_trial.save_review(json.loads(body))
                    return self.send(200, json.dumps(value, ensure_ascii=False, allow_nan=False).encode())
                except (ValueError, TypeError, KeyError):
                    return self.fail(400, 'Өөрөө сонссон үнэлгээ шаардлагатай.')
                except OSError:
                    return self.fail(503, 'Үнэлгээг хадгалж чадсангүй.')
            if path == '/api/voice/reset':
                try:
                    value = json.loads(body)
                    with lock:
                        if (not isinstance(value, dict) or set(value) != {'ids'}
                                or not isinstance(value['ids'], list)
                                or any(not isinstance(item, str) or item not in audio_ids for item in value['ids'])):
                            raise ValueError()
                except (ValueError, TypeError):
                    return self.fail(400, 'Зөвхөн энэ туршилтын дууг цэвэрлэнэ.')
            self.forward(path, body)

        def forward(self, path, body=None):
            if not slots.acquire(blocking=False):
                return self.fail(429, 'Хоёр хүсэлт боловсруулж байна. Түр хүлээнэ үү.')
            upstream = HTTPConnection('127.0.0.1', backend_port, timeout=135)
            try:
                headers = {'Origin': f'http://127.0.0.1:{backend_port}'}
                if body is not None: headers['Content-Type'] = self.headers.get('Content-Type', 'application/json')
                upstream.request('POST' if body is not None else 'GET', path, body, headers)
                response = upstream.getresponse(); data = response.read(MAX_RESPONSE+1)
                if len(data) > MAX_RESPONSE: return self.fail(502, 'Backend хариулт хэт том.')
                mime = response.getheader('Content-Type', 'application/octet-stream')
                if response.status == 200 and path in {'/api/status', '/api/voice/transcribe', '/api/voice/speak'}:
                    value = json.loads(data)
                    if not isinstance(value, dict): raise ValueError('Invalid upstream result')
                    if path == '/api/status':
                        value['local_review_writes_supported'] = False
                        value['public_gateway'] = dict(https=True, expires_utc=expires_utc,
                            private_review_available=False, temporary=True,
                            human_listening_available=listening_trial is not None)
                        # Internal storage paths are irrelevant to remote visitors.
                        if isinstance(value.get('voice'), dict): value['voice'].pop('private_storage', None)
                    else:
                        identifier = value.get('id')
                        if (not isinstance(identifier, str) or not re.fullmatch(r'[0-9a-f]{32}', identifier)
                                or value.get('audio_url') != '/api/voice/audio/'+identifier):
                            raise ValueError('Invalid session audio result')
                        with lock: audio_ids.add(identifier)
                    data = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
                self.send(response.status, data, mime)
            except (OSError, ValueError, HTTPException):
                self.fail(502, 'Тусдаа локал backend бэлэн биш байна.')
            finally:
                upstream.close(); slots.release()

        def do_OPTIONS(self): self.fail(405, 'Cross-origin хүсэлт дэмжихгүй.')
        def do_PUT(self): self.fail(405, 'PUT дэмжихгүй.')
        def do_DELETE(self): self.fail(405, 'DELETE дэмжихгүй.')
        def do_HEAD(self): self.fail(405, 'HEAD дэмжихгүй.')

    class Server(ThreadingHTTPServer):
        daemon_threads = True
        def get_request(self):
            connection, address = super().get_request(); connection.settimeout(15)
            return connection, address
    return Server(('127.0.0.1', port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8787)
    parser.add_argument('--backend-port', type=int, default=8766)
    parser.add_argument('--external-origin', required=True)
    parser.add_argument('--token-file', type=Path, required=True)
    parser.add_argument('--lifetime', type=int, default=7200)
    parser.add_argument('--listening-dir', type=Path)
    parser.add_argument('--result-dir', type=Path)
    args = parser.parse_args()
    trial = None
    if args.listening_dir:
        try:
            from tools.tts_listening_trial import ListeningTrial
        except ModuleNotFoundError:
            from tts_listening_trial import ListeningTrial
        trial = ListeningTrial(args.listening_dir)
    token = args.token_file.read_text(encoding='ascii').strip()
    with make_gateway(port=args.port, backend_port=args.backend_port, token=token,
            external_origin=args.external_origin, lifetime=args.lifetime, listening_trial=trial,
            result_dir=args.result_dir) as server:
        timer = threading.Timer(args.lifetime, server.shutdown); timer.daemon = True; timer.start()
        print('Authenticated public-tunnel ingress ready on loopback only.', flush=True)
        try: server.serve_forever()
        finally: timer.cancel()


if __name__ == '__main__': main()
