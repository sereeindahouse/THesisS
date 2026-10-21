"""Explicit human listening of a fixed, private, school-text TTS bundle.

No personal recordings or historical STT references are read. A saved response
is a human self-report, never an automatic listening/quality acceptance.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import uuid


PAGE = '''<!doctype html><html lang="mn"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Дууг сонсож үнэлэх · ШМТК</title><style>
*{box-sizing:border-box}body{margin:0;background:#f5f6f0;color:#18382d;font:16px/1.6 system-ui,sans-serif}
main{max-width:800px;margin:auto;padding:28px 16px}h1{font-size:30px;line-height:1.25}a{color:#315f43}
article{padding:22px;background:white;border:1px solid #dce4d6;border-radius:18px;margin:20px 0}
audio{width:100%;margin:12px 0}label{display:block;margin:14px 0}select,textarea,button{font:inherit;padding:10px;border:1px solid #acb9a7;border-radius:8px}
select{float:right;max-width:52%}textarea{display:block;width:100%;min-height:70px}button{background:#285b41;color:white;cursor:pointer}button:disabled{opacity:.5;cursor:default}
p,pre{overflow-wrap:anywhere}pre{white-space:pre-wrap;font:inherit}small,.note{color:#53695c}.result{font-weight:600}
</style><main><a href="/">← Чат</a><h1>Дууг сонсож үнэлэх</h1>
<p>Жишээ бүрийг сонсоод өөрийн үнэлгээг хадгална. Бүх жишээг нэг дор дуусгах шаардлагагүй.</p>
<p class="note">1 = маш муу, 2 = муу, 3 = дунд, 4 = сайн, 5 = маш сайн. Хүний сонсголын үнэлгээг файл үүссэн эсэхээс тусад нь бүртгэнэ. Нэр, утас, хувийн бичлэг авахгүй.</p>
<p><label>Сонсох хурд <select id="speed"><option value="1">1× · хэвийн</option><option value=".85">0.85×</option><option value="1.15">1.15×</option></select></label></p>
<p id="status">Жишээг ачаалж байна…</p><div id="samples"></div></main><script>
const field=(tag,text)=>{const n=document.createElement(tag);n.textContent=text;return n};
const names={intelligibility:'Ойлгомжтой байдал',pronunciation:'Үг, нэр, тооны дуудлага',naturalness:'Ярианы хэвийн байдал'};
async function load(){const r=await fetch('/api/listening');if(!r.ok)throw Error('Жишээ ачаалсангүй.');const m=await r.json();document.getElementById('status').textContent=m.samples.length+' жишээ · өөрөө сонссон дүн';
for(const s of m.samples){const a=document.createElement('article');a.append(field('h2',s.label));a.append(field('small',s.voice_label+' · '+s.seconds.toFixed(1)+' секунд'));
const audio=document.createElement('audio');audio.controls=true;audio.preload='none';audio.src=s.audio_url;audio.playbackRate=Number(document.getElementById('speed').value);a.append(audio);
const d=document.createElement('details');d.append(field('summary','Уншсан текстийг харах'));d.append(field('pre',s.text));a.append(d);
const selects={};for(const [key,label] of Object.entries(names)){const l=field('label',label);const select=document.createElement('select');select.append(new Option('Үнэлгээ сонгох',''));for(let v=1;v<=5;v++)select.append(new Option(v+' / 5',String(v)));l.append(select);a.append(l);selects[key]=select}
const comments=document.createElement('textarea');comments.maxLength=500;comments.placeholder='Буруу дуудагдсан үг, тоо байвал бичнэ үү (заавал биш)';a.append(comments);
const l=document.createElement('label');const heard=document.createElement('input');heard.type='checkbox';l.append(heard,document.createTextNode(' Би энэ жишээг өөрөө сонсож үнэлсэн'));a.append(l);
const save=field('button','Үнэлгээг хадгалах');const result=field('p','');result.className='result';a.append(save,result);let playbackEnded=false;audio.addEventListener('ended',()=>playbackEnded=true);
save.onclick=async()=>{if(!heard.checked||Object.values(selects).some(x=>!x.value)){result.textContent='Сонссон гэдгээ тэмдэглэж, гурван үнэлгээг сонгоно уу.';return}save.disabled=true;
try{const body={sample_id:s.id,audio_sha256:s.audio_sha256,listened:true,playback_ended:playbackEnded,playback_rate:audio.playbackRate,comments:comments.value,...Object.fromEntries(Object.entries(selects).map(([k,v])=>[k,Number(v.value)]))};const response=await fetch('/api/listening/review',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const value=await response.json();if(!response.ok)throw Error(value.message||'Хадгалсангүй.');result.textContent='Хадгаллаа. Таны өөрөө сонссон үнэлгээ бүртгэгдлээ.'}catch(e){result.textContent=e.message;save.disabled=false}};
document.getElementById('samples').append(a)}}
document.getElementById('speed').onchange=e=>document.querySelectorAll('audio').forEach(a=>a.playbackRate=Number(e.target.value));load().catch(e=>document.getElementById('status').textContent=e.message);
</script>'''


class ListeningTrial:
    def __init__(self, bundle_dir):
        self.root = Path(bundle_dir).resolve(strict=True)
        path = self.root / 'manifest.json'
        if path.stat().st_size > 100_000:
            raise ValueError('Listening manifest too large.')
        bundle = json.loads(path.read_text(encoding='utf-8'))
        if bundle.get('scope') != 'school_text_tts_human_self_report':
            raise ValueError('School-text-only listening scope required.')
        samples = bundle.get('samples')
        if not isinstance(samples, list) or not 1 <= len(samples) <= 12:
            raise ValueError('Require 1–12 frozen samples.')
        self.samples = {}
        for sample in samples:
            identifier = sample.get('id')
            if (not isinstance(identifier, str) or not re.fullmatch(r'[a-z0-9-]{1,40}', identifier)
                    or identifier in self.samples):
                raise ValueError('Invalid/duplicate listening sample ID.')
            # Filenames are generated from the ID, never provided by requests.
            audio = (self.root / (identifier + '.mp3')).resolve(strict=True)
            if not audio.is_relative_to(self.root) or not 1 <= audio.stat().st_size <= 8 * 1024 * 1024:
                raise ValueError('Unsafe listening audio.')
            digest = hashlib.sha256(audio.read_bytes()).hexdigest()
            if digest != sample.get('audio_sha256'):
                raise ValueError('Listening audio hash changed.')
            if (not isinstance(sample.get('text'), str) or len(sample['text']) > 2500
                    or sample.get('voice') not in {'mn-MN-BataaNeural', 'mn-MN-YesuiNeural'}
                    or not isinstance(sample.get('label'), str) or len(sample['label']) > 160
                    or type(sample.get('seconds')) not in {int, float} or not 0 < sample['seconds'] <= 180):
                raise ValueError('Invalid listening metadata.')
            self.samples[identifier] = {**sample, '_audio_path': audio}
        self.manifest_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()

    def page_bytes(self):
        return PAGE.encode('utf-8')

    def manifest(self):
        return dict(scope='school_text_tts_human_self_report', human_results_inferred=False,
            manifest_sha256=self.manifest_sha256, samples=[dict(
                id=s['id'], label=s['label'], text=s['text'], seconds=s['seconds'],
                voice_label='Батаа' if 'Bataa' in s['voice'] else 'Есүй',
                audio_sha256=s['audio_sha256'], audio_url='/api/listening/audio/' + s['id'])
                for s in self.samples.values()])

    def audio(self, identifier):
        if identifier not in self.samples:
            raise KeyError('Unknown listening sample.')
        sample = self.samples[identifier]
        path = sample['_audio_path'].resolve(strict=True)
        if not path.is_relative_to(self.root) or path.stat().st_size > 8 * 1024 * 1024:
            raise ValueError('Unsafe listening audio.')
        body = path.read_bytes()
        if hashlib.sha256(body).hexdigest() != sample['audio_sha256']:
            raise ValueError('Listening audio hash changed.')
        return body, 'audio/mpeg'

    def save_review(self, body):
        required = {'sample_id', 'audio_sha256', 'listened', 'playback_ended',
                    'playback_rate', 'comments', 'intelligibility', 'pronunciation', 'naturalness'}
        if not isinstance(body, dict) or set(body) != required:
            raise ValueError('Invalid listening fields.')
        identifier = body['sample_id']
        if not isinstance(identifier, str) or identifier not in self.samples:
            raise ValueError('Unknown listening sample.')
        sample = self.samples[identifier]
        if body['listened'] is not True or body['audio_sha256'] != sample['audio_sha256']:
            raise ValueError('Explicit listening confirmation and exact audio required.')
        if type(body['playback_ended']) is not bool or type(body['playback_rate']) not in {int, float} or body['playback_rate'] not in {.85, 1, 1.15}:
            raise ValueError('Invalid playback metadata.')
        for field in ('intelligibility', 'pronunciation', 'naturalness'):
            if type(body[field]) is not int or not 1 <= body[field] <= 5:
                raise ValueError('Ratings must be integers 1–5.')
        if not isinstance(body['comments'], str) or len(body['comments']) > 500:
            raise ValueError('Invalid listening comment.')
        # Reverify the frozen file before binding a human response to it.
        self.audio(identifier)
        record = dict(**body, id=uuid.uuid4().hex,
            saved_utc=datetime.now(timezone.utc).isoformat(),
            manifest_sha256=self.manifest_sha256,
            review_source='human_browser_self_report', observer_verified=False,
            automatic_quality_acceptance=False)
        destination = (self.root / 'reviews').resolve()
        if not destination.is_relative_to(self.root):
            raise ValueError('Unsafe listening review directory.')
        destination.mkdir(exist_ok=True)
        with (destination / (record['id'] + '.json')).open('x', encoding='utf-8', newline='\n') as handle:
            json.dump(record, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
        return dict(saved=True, id=record['id'], review_source=record['review_source'],
                    observer_verified=False, automatic_quality_acceptance=False)


def make_local_server(bundle_dir, port=8788):
    """Loopback-only listening while external HTTPS authorization is pending."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    trial = ListeningTrial(bundle_dir)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *args):
            pass

        def send(self, code, data=b'', mime='application/json; charset=utf-8'):
            self.send_response(code)
            for key, value in [('Content-Type', mime), ('Content-Length', str(len(data))),
                    ('Cache-Control', 'no-store'), ('Connection', 'close'),
                    ('Referrer-Policy', 'no-referrer'), ('X-Content-Type-Options', 'nosniff'),
                    ('X-Robots-Tag', 'noindex, nofollow'),
                    ('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; media-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")]:
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(data)
            self.close_connection = True

        def valid(self):
            self.connection.settimeout(5)
            host = f'127.0.0.1:{self.server.server_port}'
            if self.headers.get_all('Host', []) != [host]:
                self.send(403); return False
            if self.headers.get('Origin') not in {None, 'http://' + host}:
                self.send(403); return False
            if (self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length', [])) > 1
                    or len(self.headers.get_all('Origin', [])) > 1):
                self.send(400); return False
            return True

        def do_GET(self):
            if not self.valid(): return
            if self.path in {'/', '/listening'}:
                # The chat runs on its established loopback port, not this server.
                return self.send(200, trial.page_bytes().replace(b'href="/"', b'href="http://127.0.0.1:8765/"'), 'text/html; charset=utf-8')
            if self.path == '/api/listening':
                return self.send(200, json.dumps(trial.manifest(), ensure_ascii=False).encode())
            match = re.fullmatch(r'/api/listening/audio/([a-z0-9-]{1,40})', self.path)
            if match:
                try:
                    data, mime = trial.audio(match[1])
                    return self.send(200, data, mime)
                except (KeyError, ValueError, OSError):
                    pass
            self.send(404)

        def do_POST(self):
            if not self.valid(): return
            expected = f'http://127.0.0.1:{self.server.server_port}'
            length = self.headers.get('Content-Length', '')
            if (self.path != '/api/listening/review' or self.headers.get('Origin') != expected
                    or self.headers.get('Content-Type') != 'application/json'
                    or not re.fullmatch(r'[0-9]{1,5}', length) or not 1 <= int(length) <= 4096):
                return self.send(400)
            try:
                value = trial.save_review(json.loads(self.rfile.read(int(length))))
                return self.send(200, json.dumps(value).encode())
            except (ValueError, TypeError, KeyError, OSError):
                self.send(400)

    class Server(ThreadingHTTPServer):
        daemon_threads = True
        def get_request(self):
            connection, address = super().get_request()
            connection.settimeout(5)
            return connection, address
    return Server(('127.0.0.1', port), Handler)


if __name__ == '__main__':
    import argparse
    import threading
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle-dir', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8788)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('Use a valid local port.')
    with make_local_server(args.bundle_dir, args.port) as server:
        timer = threading.Timer(7200, server.shutdown)
        timer.daemon = True
        timer.start()
        print(f'Local listening: http://127.0.0.1:{args.port}/listening', flush=True)
        try:
            server.serve_forever()
        finally:
            timer.cancel()
