"""Short-lived authenticated HTTPS gateway to a separate loopback demo.

No certificate trust-store, firewall or production-server settings are changed.
Private reference-review APIs never pass through this gateway.
"""
import argparse
from datetime import datetime, timezone
import hmac
from http.client import HTTPConnection, HTTPException
from http.cookies import SimpleCookie, CookieError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
from pathlib import Path
import re
import secrets
import ssl
import time
import threading
from urllib.parse import urlsplit

COOKIE = '__Host-nmct_device'
MAX_AUDIO = 8 * 1024 * 1024
GET_PATHS = {'/', '/index.html', '/data', '/data.html', '/data.js', '/data.css', '/api/status', '/api/explorer', '/api/teachers'}
POST_PATHS = {'/api/route', '/api/search', '/api/preview', '/api/website-search',
              '/api/conversation/reset', '/api/voice/transcribe', '/api/voice/speak',
              '/api/voice/reset', '/api/voice/correct'}
CHECK_PAGE = '''<!doctype html><html lang="mn"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Android холболтын шалгалт</title>
<style>body{font:17px system-ui;max-width:650px;margin:24px auto;padding:0 16px;line-height:1.6}button,a{display:inline-block;padding:12px;margin:8px 0}label{display:block;margin:12px 0}pre{white-space:pre-wrap}</style>
<h1>Төхөөрөмжийн шалгалт</h1><p>Микрофоны зөвшөөрлийг шалгахдаа дуу бичихгүй, илгээхгүй. Доорх тэмдэглэл зөвхөн таны компьютерийн локал серверт хадгалагдана.</p>
<pre id="state"></pre><button id="mic">Микрофоны зөвшөөрөл шалгах</button><p><a href="/" target="_blank" rel="noopener">Чатыг нээж асуулт, хариулт, дууг турших</a></p>
<p>Чатад «Бүртгэлийн хураамж хэд вэ?» гэж асуугаад «Элсэлтийнх» гэж тодруулна. Эхтэй хариултыг харж, хүсвэл «Сонсох» дарна.</p>
<label><input id="fits" type="checkbox"> Хуудас утасны дэлгэцэд багтаж байна</label>
<label><input id="answer" type="checkbox"> Эхтэй хариулт бодитоор харсан</label>
<label><input id="heard" type="checkbox"> Хариултын дууг өөрөө сонссон</label>
<button id="save">Өөрийн шалгасан үр дүнг хадгалах</button><pre id="result"></pre>
<script>const s={secure_context:window.isSecureContext,media_devices:!!navigator.mediaDevices?.getUserMedia,mic_granted:null};
const show=()=>document.getElementById('state').textContent=JSON.stringify(s,null,2);show();
document.getElementById('mic').onclick=async()=>{try{const stream=await navigator.mediaDevices.getUserMedia({audio:true});stream.getTracks().forEach(t=>t.stop());s.mic_granted=true}catch(e){s.mic_granted=false;s.mic_error=e.name}show()};
document.getElementById('save').onclick=async()=>{const b={...s,page_fits:document.getElementById('fits').checked,answer_seen:document.getElementById('answer').checked,audio_heard:document.getElementById('heard').checked,platform:navigator.userAgent.includes('Android')?'Android':'other',human_reported:true};const r=await fetch('/device-result',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});document.getElementById('result').textContent=JSON.stringify(await r.json(),null,2)};
</script></html>'''


def allowed_path(method, path):
    if method == 'GET':
        return path in GET_PATHS or bool(re.fullmatch(r'/api/voice/audio/[0-9a-f]{32}', path)) or bool(
            re.fullmatch(r'/api/teacher-media/teacher-[0-9a-f]{24}', path)) or bool(
            re.fullmatch(r'/api/explorer/document/(?:png|pdf)-[0-9a-f]{20}', path)) or bool(
            re.fullmatch(r'/demo/audio/q0[123]\.wav', path))
    return method == 'POST' and path in POST_PATHS


def make_gateway(*, bind, port, backend_port, token, cert, key, result_dir, lifetime=5400):
    address = ipaddress.ip_address(bind)
    if address.version != 4 or not address.is_private or address.is_unspecified:
        raise ValueError('Bind an explicit private IPv4 or loopback address, never all interfaces/public internet.')
    if (type(port) is not int or type(backend_port) is not int or not 1 <= port <= 65535
            or not 1 <= backend_port <= 65535 or backend_port in {8765, port}):
        raise ValueError('Use a separate loopback backend; preserve the main8765 demo.')
    if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{40,100}', token):
        raise ValueError('Require a random capability of at least240bits.')
    if not 60 <= lifetime <= 7200:
        raise ValueError('A device trial lasts60–7200seconds.')
    result_dir = Path(result_dir).resolve()
    result_dir.mkdir(parents=True, exist_ok=True)
    origin = f'https://{bind}:{port}'
    deadline = time.monotonic() + lifetime
    expires_utc = datetime.fromtimestamp(time.time()+lifetime, timezone.utc).isoformat()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *args):
            pass  # Never log the capability URL, cookies, audio, query or IP.

        def send(self, code, body=b'', mime='application/json; charset=utf-8', extra=()):
            self.send_response(code)
            for name,value in [('Content-Type',mime), ('Content-Length',str(len(body))),
                ('Cache-Control','no-store'), ('Referrer-Policy','no-referrer'),
                ('X-Content-Type-Options','nosniff'), ('Cross-Origin-Resource-Policy','same-origin'),
                ('Content-Security-Policy',"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; media-src 'self' blob:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'"),
                *extra]:
                self.send_header(name,value)
            self.end_headers()
            self.wfile.write(body)

        def fail(self, code, message):
            self.close_connection = True
            lengths=self.headers.get_all('Content-Length',[])
            if (len(lengths)==1 and re.fullmatch(r'[0-9]{1,10}',lengths[0])
                    and not self.headers.get('Transfer-Encoding')):
                remaining=int(lengths[0])-getattr(self,'_body_bytes_read',0)
                if 0 < remaining <= 65536:
                    try:
                        self.connection.settimeout(0.25)
                        self.rfile.read(remaining)
                    except OSError:
                        pass
            self.send(code,json.dumps({'error':message},ensure_ascii=False).encode(),extra=[('Connection','close')])

        def preflight(self):
            self.connection.settimeout(15)
            if time.monotonic() >= deadline:
                self.fail(410,'Төхөөрөмжийн туршилтын хугацаа дууссан.');return False
            if self.headers.get_all('Host',[]) != [f'{bind}:{port}']:
                self.fail(403,'Хаяг таарахгүй байна.');return False
            lengths=self.headers.get_all('Content-Length',[])
            if (self.headers.get('Transfer-Encoding') or len(lengths)>1
                    or (self.command=='GET' and lengths not in ([],['0']))):
                self.fail(400,'Хүсэлтийн framing буруу.');return False
            if len(self.headers.get_all('Origin',[]))>1:
                self.fail(403,'Origin давхардаж болохгүй.');return False
            if (self.headers.get('Sec-Fetch-Site') == 'cross-site' or
                    self.headers.get('Origin') not in {None,origin}):
                self.fail(403,'Өөр сайтаас дуудахгүй.');return False
            return True

        def authenticated(self):
            try:
                cookies=SimpleCookie();cookies.load(self.headers.get('Cookie',''))
                value=cookies[COOKIE].value if COOKIE in cookies else ''
            except CookieError:
                value=''
            return hmac.compare_digest(value.encode('utf-8'),token.encode('ascii'))

        def do_GET(self):
            if not self.preflight():return
            parts=urlsplit(self.path)
            path=parts.path
            if parts.query or parts.fragment or parts.scheme or parts.netloc:
                return self.fail(400,'Query бүхий хаяг ашиглахгүй.')
            if path.startswith('/connect/'):
                if not hmac.compare_digest(path[len('/connect/'):].encode('utf-8'),token.encode('ascii')):return self.fail(403,'Холболтын код буруу.')
                return self.send(303,b'',extra=[('Location','/device-check'),('Set-Cookie',
                    f'{COOKIE}={token}; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age={int(max(0,deadline-time.monotonic()))}')])
            if not self.authenticated():return self.fail(401,'Компьютер дээр бэлтгэсэн хувийн холболтын холбоосыг ашиглана уу.')
            if path=='/device-check':return self.send(200,CHECK_PAGE.encode(),'text/html; charset=utf-8')
            if not allowed_path('GET',path):return self.fail(403,'Энэ API төхөөрөмжийн туршилтад хаалттай.')
            self.forward(path)

        def do_POST(self):
            if not self.preflight():return
            if not self.authenticated():return self.fail(401,'Холболтын эрх байхгүй.')
            if self.headers.get_all('Origin',[]) != [origin]:return self.fail(403,'HTTPS origin шаардлагатай.')
            path=self.path
            if path!='/device-result' and not allowed_path('POST',path):return self.fail(403,'Хаалттай API.')
            lengths=self.headers.get_all('Content-Length',[])
            maximum=MAX_AUDIO if path=='/api/voice/transcribe' else 24576
            if (self.headers.get('Transfer-Encoding') or len(lengths)!=1 or not re.fullmatch(r'[0-9]{1,10}',lengths[0])
                    or not 0<int(lengths[0])<=maximum):return self.fail(400,'Хүсэлтийн хэмжээ эсвэл framing буруу.')
            try:body=self.rfile.read(int(lengths[0]))
            except OSError:return self.fail(408,'Хүсэлтийг хүлээх хугацаа дууссан.')
            self._body_bytes_read=len(body)
            if len(body)!=int(lengths[0]):return self.fail(400,'Хүсэлт дутуу.')
            if path=='/device-result':
                try:
                    value=json.loads(body)
                    booleans={'secure_context','media_devices','mic_granted','page_fits','answer_seen','audio_heard','human_reported'}
                    if (not isinstance(value,dict) or set(value)-booleans-{'platform','mic_error'} or any(type(value.get(k)) is not bool for k in booleans)
                            or value['human_reported'] is not True or value.get('platform') not in {'Android','other'}
                            or not isinstance(value.get('mic_error',''),str) or len(value.get('mic_error',''))>100):raise ValueError()
                    identity=secrets.token_hex(12)
                    record=dict(value,created_utc=datetime.now(timezone.utc).isoformat(),
                        source='user_device_browser_self_report',independent_observer=False)
                    with (result_dir/(identity+'.json')).open('x',encoding='utf-8') as handle:json.dump(record,handle,ensure_ascii=False,indent=2)
                except (ValueError,TypeError,KeyError):return self.fail(400,'Өөрөө шалгасан boolean үр дүн шаардлагатай.')
                except OSError:return self.fail(503,'Төхөөрөмжийн тэмдэглэлийг хадгалж чадсангүй.')
                return self.send(200,json.dumps({'saved':True,'id':identity},ensure_ascii=False).encode())
            self.forward(path,body)

        def forward(self,path,body=None):
            upstream=HTTPConnection('127.0.0.1',backend_port,timeout=135)
            try:
                headers={'Origin':f'http://127.0.0.1:{backend_port}'}
                if body is not None:headers['Content-Type']=self.headers.get('Content-Type','application/json')
                upstream.request('POST' if body is not None else 'GET',path,body,headers)
                response=upstream.getresponse();data=response.read(12*1024*1024+1)
                if len(data)>12*1024*1024:return self.fail(502,'Backend хариулт хэт том.')
                mime=response.getheader('Content-Type','application/octet-stream')
                if path=='/api/status' and response.status==200:
                    value=json.loads(data)
                    if not isinstance(value,dict):raise ValueError('Invalid upstream status')
                    value['local_review_writes_supported']=False
                    value['device_gateway']=dict(https=True,expires_utc=expires_utc,private_review_available=False)
                    data=json.dumps(value,ensure_ascii=False,allow_nan=False).encode()
                self.send(response.status,data,mime)
            except (OSError,ValueError,HTTPException):self.fail(502,'Тусдаа локал backend бэлэн биш байна.')
            finally:upstream.close()

        def do_OPTIONS(self):self.fail(405,'Cross-origin хүсэлт дэмжихгүй.')
        def do_PUT(self):self.fail(405,'PUT дэмжихгүй.')
        def do_DELETE(self):self.fail(405,'DELETE дэмжихгүй.')

    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version=ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(str(cert),str(key))
    class Server(ThreadingHTTPServer):
        daemon_threads=True
        def get_request(self):
            connection,address=super().get_request();connection.settimeout(5)
            try:return context.wrap_socket(connection,server_side=True),address
            except Exception:connection.close();raise
    return Server((bind,port),Handler)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bind',default='127.0.0.1')
    parser.add_argument('--port',type=int,default=9443)
    parser.add_argument('--backend-port',type=int,default=8766)
    parser.add_argument('--cert',type=Path,required=True);parser.add_argument('--key',type=Path,required=True)
    parser.add_argument('--token-file',type=Path,required=True);parser.add_argument('--result-dir',type=Path,required=True)
    parser.add_argument('--lifetime',type=int,default=5400)
    args=parser.parse_args()
    token=args.token_file.read_text(encoding='ascii').strip()
    with make_gateway(bind=args.bind,port=args.port,backend_port=args.backend_port,token=token,
            cert=args.cert,key=args.key,result_dir=args.result_dir,lifetime=args.lifetime) as server:
        timer=threading.Timer(args.lifetime,server.shutdown);timer.daemon=True;timer.start()
        print('HTTPS device gateway ready; capability is only in its private token file.',flush=True)
        try:server.serve_forever()
        finally:timer.cancel()


if __name__=='__main__':main()
