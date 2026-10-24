"""Loopback development UI: read-only school content, private voice and human review."""
import argparse
import hashlib
import json
import re
import secrets
import sqlite3
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from sqlite_retrieval import ReadOnlyContentStore, guarded_preview, search_content
from CORE.website_corpus import website_status, search_website
from question_router import route_question
from voice_runtime import VoiceRuntime, VoiceRuntimeError, MAX_AUDIO_BYTES
from answer_contract import spoken_text
from listening_review import ListeningReview
from project_policy import ContentUsePolicy
from llm_runtime import LLMRuntime
from rag_runtime import ChatRAG
from data_explorer import SourceExplorer
from clarification_context import ClarificationContext, ClarificationConflict
from content_release import ContentReleaseManager, ReleaseConflict, ReleaseError
from release_runtime import LiveContentRuntime
from website_retrieval import WebsiteRetriever
from teacher_media import TeacherMedia, TeacherMediaError

ROOT = Path(__file__).resolve().parent
MAX_BODY = 8192
AUDIO_NAMES = ("q01.wav", "q02.wav", "q03.wav")
CLARIFICATION_ARTIFACT_SHA256 = {
    name: hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest()
    for name in ("clarification_context.py", "demo_server.py", "content_release.py", "release_runtime.py", "data_explorer.py", "teacher_media.py", "tools/build_knowledge_tree.py")
}


def _content_length(headers):
    """Parse one bounded ASCII decimal field; invalid framing has no length."""
    lengths = headers.get_all("Content-Length", [])
    if len(lengths) != 1 or not re.fullmatch(r"[0-9]{1,10}", lengths[0]):
        return None
    return int(lengths[0])


def make_server(db_path=None, *, port=8765, project_root=None, voice_service=None, review_service=None, llm_service=None, rag_service=None, clarification_service=None, teacher_service=None):
    """Bind loopback only; open each worker connection read-only per request."""
    root = Path(project_root or ROOT).resolve()
    database = Path(db_path or root / "runtime" / "content.db").resolve()
    voice = voice_service if voice_service is not None else VoiceRuntime(root)
    review = review_service if review_service is not None else ListeningReview(root)

    content_policy = ContentUsePolicy(root)
    llm = llm_service if llm_service is not None else LLMRuntime(root)
    rag = rag_service if rag_service is not None else ChatRAG(root, content_policy)
    clarification_context = clarification_service if clarification_service is not None else ClarificationContext()
    explorer = SourceExplorer(root,content_database=database)
    releases = ContentReleaseManager(root)
    live_content = LiveContentRuntime(root, database, rag, explorer, content_policy,
                                      manager=releases, clarification=clarification_context)
    admin_token = secrets.token_urlsafe(32)
    teachers = teacher_service if teacher_service is not None else TeacherMedia(root)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def send_data(self, code, body, content_type):
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            if self.close_connection:
                self.send_header("Connection", "close")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                             "style-src 'self' 'unsafe-inline'; connect-src 'self'; "
                             "media-src 'self' blob:; object-src 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def send_json(self, code, value):
            self.send_data(code, json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"),
                           "application/json; charset=utf-8")

        def error(self, code, message):
            self.close_connection = True
            # A close with unread incoming bytes can discard the JSON response
            # through a TCP reset (observed on Windows). Discard only a small,
            # explicitly framed remainder; never parse or execute rejected data.
            length = _content_length(self.headers)
            if (self.command == "POST" and length is not None
                    and not self.headers.get_all("Transfer-Encoding", [])):
                remaining = length - getattr(self, "_body_bytes_read", 0)
                if 0 < remaining <= 65536:
                    try:
                        self.connection.settimeout(0.25)
                        self.rfile.read(remaining)
                    except (OSError, TimeoutError):
                        pass
            self.send_json(code, {"error": message})

        def valid_host(self):
            port_number = self.server.server_address[1]
            return self.headers.get("Host") in {
                f"127.0.0.1:{port_number}", f"localhost:{port_number}"
            }

        def authorized_sample(self, name):
            path = (root / "demo" / "audio" / name).resolve()
            expected = root / "demo" / "audio"
            return path if path.parent == expected and path.is_file() else None

        def admin_authorized(self):
            supplied = self.headers.get('X-Admin-Token', '')
            return supplied.isascii() and secrets.compare_digest(supplied, admin_token)

        def teacher_answer(self, query, draft, database, rag):
            """Explicit profile lookup has its own dated source bundle and TTS capability."""
            if not content_policy.enabled:
                return None
            match = teachers.profile(query)
            if match is None:
                return None
            result = content_policy.route(database, query, allow_draft=draft)
            result.update(query=query, answer=None, citations=[], generated=False, llm_calls=0,
                          related_sources=[], suggestions=[], clarification=None,
                          teacher_media_bundle_id=match['bundle_id'])
            if match['status'] == 'staff_scope_required':
                result.update(route='D',answer_kind='teacher_scope_clarification',reason_code='teacher_scope_required',
                    message='Аль тэнхимийн эсвэл ямар багшийн талаар мэдэх вэ? Нэр, тэнхим, багшийн тоо эсвэл танилцуулга гэдгээ тодруулна уу. Хадгалсан эх бүх багшийн бүрэн жагсаалт биш.',
                    suggestions=['Компьютерын ухааны багш нарын нэрсийг харуулна уу.',
                                 'Механик инженерийн тэнхим хэдэн багштай вэ?',
                                 'Химийн инженерийн тэнхимийн эрхлэгч хэн бэ?'])
            elif match['status'] == 'partial_directory':
                cards=match['profiles']
                if not cards:
                    return None
                result.update(route='A',answer_kind='partial_teacher_directory',reason_code='captured_partial_teacher_directory',
                    answer='\n\n'.join(card['source_quote'] for card in cards),
                    message=match['department']+' — хадгалсан '+str(len(cards))+' багшийн албан танилцуулгыг үзүүлэв. Энэ нь бүх багшийн бүрэн жагсаалт биш; эхийн огноог нягтлаарай.',
                    teacher_cards=cards,coverage='partial_captured_profiles',full_staff_roster=False,
                    citations=[dict(document_id=card['teacher_id'],version=1,
                        title=card['name']+' — багшийн албан танилцуулга',
                        source_url_or_filename=card['source_url'],locator=card['source_locator'],
                        retrieved_at=card['captured_utc'],source_html_sha256=card['source_html_sha256'],
                        source_accepted_for_project=True,school_staff_approval=False,
                        approval_status='draft',extraction_method='official_structured_teacher_record') for card in cards])
            elif match['status'] == 'ambiguous':
                names = match['candidates']
                result.update(route='D', answer_kind='teacher_profile_clarification',
                    reason_code='teacher_name_required',
                    message='Ямар багшийн зурагтай танилцуулгыг үзэх вэ? Доорх нэрсийн албан эхтэй танилцуулга бэлэн байна. Энэ нь бүх багшийн жагсаалт биш.',
                    suggestions=[name+' багшийн зурагтай танилцуулгыг үзье.' for name in names[:6]])
            else:
                card = match['profile']
                result.update(route='A', answer_kind='official_teacher_profile',
                    reason_code='source_bound_teacher_profile', answer=card['source_quote'],
                    message='Албан сайтаас хадгалсан нэр, танилцуулга, зургийг үзүүлэв. Эхийн огноог нягтлаарай.',
                    teacher_cards=[card], citations=[dict(document_id=card['teacher_id'],version=1,
                        title=card['name']+' — багшийн албан танилцуулга',
                        source_url_or_filename=card['source_url'],locator=card['source_locator'],
                        retrieved_at=card['captured_utc'],source_html_sha256=card['source_html_sha256'],
                        source_accepted_for_project=True,school_staff_approval=False,
                        approval_status='draft',extraction_method='official_structured_teacher_record')])
            return rag._remember(result, draft)

        def admin_get(self, path):
            if path == '/api/admin/state':
                state = releases.state()
                if state['active'] is None and not state.get('active_error'):
                    try:
                        with ReadOnlyContentStore(database) as store:
                            content_counts = store.counts()
                        website_counts = WebsiteRetriever(root, use_dense=False).status().get('counts', {})
                        state['legacy'] = {'counts': {'content': content_counts, 'website': website_counts}}
                    except (OSError, ValueError, sqlite3.Error):
                        pass
                return self.send_json(200, {**state, 'csrf_token': admin_token})
            if path == '/api/admin/content':
                if not self.admin_authorized():
                    return self.error(403, 'Админ хуудсыг дахин нээж, мэдээллээ шинэчилнэ үү.')
                query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
                if set(query) != {'release_id'} or len(query['release_id']) != 1:
                    raise ValueError('Нэг хувилбарын ID шаардлагатай.')
                release_id = query['release_id'][0]
                return self.send_json(200, {'release_id': release_id, 'content': releases.content(release_id)})
            return self.error(404, 'Админ API олдсонгүй.')

        def admin_post(self, path):
            if not self.admin_authorized():
                return self.error(403, 'Админ хуудсыг дахин нээж, мэдээллээ шинэчилнэ үү.')
            if self.headers.get_content_type() != 'application/json':
                raise ValueError('JSON өгөгдөл шаардлагатай.')
            body = self.read_json(4 * 1024 * 1024)
            operation = path.removeprefix('/api/admin/')
            required = {
                'stage': {'label', 'expected_active'},
                'import-content': {'release_id', 'content'},
                'import-website': {'release_id', 'snapshot_path'},
                'validate': {'release_id'},
                'publish': {'release_id', 'expected_active'},
                'rollback': {'release_id', 'expected_active'},
            }
            if operation not in required:
                return self.error(404, 'Админ үйлдэл олдсонгүй.')
            allowed = required[operation] | ({'actor'} if operation in {'publish', 'rollback'} else set())
            if not required[operation] <= set(body) or set(body) - allowed:
                raise ValueError('Админ үйлдлийн талбарууд дутуу эсвэл илүү байна.')
            if operation == 'stage':
                result = releases.stage(body['label'], body['expected_active'])
            elif operation == 'import-content':
                result = releases.import_content(body['release_id'], body['content'])
            elif operation == 'import-website':
                result = releases.import_website(body['release_id'], body['snapshot_path'])
            elif operation == 'validate':
                result = releases.validate(body['release_id'])
            else:
                result = getattr(releases, operation)(body['release_id'], body['expected_active'],
                                                      body.get('actor', 'local-admin'))
            return self.send_json(200, {'result': result})

        def do_GET(self):
            if not self.valid_host():
                return self.error(403, "Зөвхөн localhost хаягаас нээнэ.")
            if self.headers.get("Sec-Fetch-Site") == "cross-site":
                return self.error(403, "Өөр сайтаас локал өгөгдөл уншихгүй.")
            origin = self.headers.get('Origin')
            port_number = self.server.server_address[1]
            if origin and origin not in {f'http://127.0.0.1:{port_number}', f'http://localhost:{port_number}'}:
                return self.error(403, 'Өөр сайтаас локал өгөгдөл уншихгүй.')
            path = unquote(urlsplit(self.path).path)
            if path == '/api/teachers':
                return self.send_json(200, {**teachers.status(), 'profiles': teachers.catalog()})
            if path.startswith('/api/teacher-media/'):
                identifier = path.removeprefix('/api/teacher-media/')
                try:
                    data, mime = teachers.media(identifier)
                    return self.send_data(200, data, mime)
                except KeyError:
                    return self.error(404, 'Багшийн баталгаатай зураг олдсонгүй.')
                except (TeacherMediaError, ValueError, OSError):
                    return self.error(409, 'Зургийн эхийг шалгаж чадсангүй. Танилцуулгыг дахин нээнэ үү.')
            if path in {'/admin', '/admin.html', '/admin.js', '/admin.css'}:
                name = 'admin.html' if path in {'/admin', '/admin.html'} else path[1:]
                file = (root / 'demo' / name).resolve()
                if file.parent != root / 'demo' or not file.is_file():
                    return self.error(404, 'Админ хуудас олдсонгүй.')
                mime = {'.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript'}[file.suffix]
                return self.send_data(200, file.read_bytes(), mime + '; charset=utf-8')
            if path.startswith('/api/admin/'):
                try:
                    return self.admin_get(path)
                except ReleaseError as error:
                    return self.error(error.status, str(error))
                except (ValueError, OSError, KeyError, sqlite3.Error):
                    return self.error(400, 'Хувилбарын мэдээллийг уншиж чадсангүй.')
            if path == '/api/status' or path.startswith('/api/explorer'):
                try:
                    bundle = live_content.snapshot()
                    database, rag, explorer = bundle.database, bundle.rag, bundle.explorer
                    clarification_context = bundle.clarification
                    website_database = bundle.website_database
                except (ReleaseError, ValueError, OSError, sqlite3.Error):
                    return self.error(503, 'Идэвхтэй эхийн хувилбарын шалгалт амжилтгүй. Админ хэсгээс хувилбараа шалгана уу.')
            if path in {"/data", "/data.html", "/data.css", "/data.js"}:
                name = "data.html" if path in {"/data", "/data.html"} else path[1:]
                file = (root / "demo" / name).resolve()
                if file.parent != root / "demo" or not file.is_file():
                    return self.error(404, "Мэдээллийн сангийн харагдац олдсонгүй.")
                mime = {".html": "text/html", ".css": "text/css", ".js": "text/javascript"}[file.suffix]
                return self.send_data(200, file.read_bytes(), mime + "; charset=utf-8")
            if path == "/api/explorer":
                try:
                    return self.send_json(200, {**explorer.snapshot(), 'content_release': bundle.public()})
                except (OSError,sqlite3.Error,ValueError,KeyError,TypeError):
                    return self.error(503, "Эхийн сан эсвэл явцын бүртгэлийг уншиж чадсангүй.")
            if path == "/api/explorer/tree":
                try:
                    tree=explorer.knowledge_tree()
                    if not live_content.is_current(bundle):
                        return self.error(409,"Эхийн хувилбар солигдлоо. Модыг дахин ачаална уу.")
                    release=bundle.public()
                    return self.send_json(200,{**tree,'release':{k:release.get(k) for k in ('release_id','corpus_id','package_id')}})
                except (OSError,sqlite3.Error,ValueError,KeyError,TypeError):
                    return self.error(503,"Мэдлэгийн модыг эхийн сантай тулгаж уншиж чадсангүй.")
            document = re.fullmatch(r"/api/explorer/document/((?:png|pdf)-[0-9a-f]{20})",path)
            if document:
                try:
                    data,mime = explorer.document(document.group(1))
                    return self.send_data(200,data,mime)
                except FileNotFoundError:
                    return self.error(404, "Хадгалсан эх баримт олдсонгүй.")
                except (OSError,sqlite3.Error,ValueError):
                    return self.error(409, "Эх баримтын файл, байрлал эсвэл hash таарахгүй байна.")
            if path == "/api/review":
                try:
                    return self.send_json(200, review.status())
                except (ValueError, OSError):
                    return self.error(503, "Сонсголын локал бүртгэл бэлэн биш.")
            media = re.fullmatch(r"/api/(voice/audio|review/stt-audio|review/tts-audio)/([A-Za-z0-9_-]{1,64})", path)
            if media:
                try:
                    kind, record_id = media.groups()
                    data, mime = (voice.audio(record_id) if kind == "voice/audio" else
                                  review.audio("stt" if kind == "review/stt-audio" else "tts", record_id))
                    return self.send_data(200, data, mime)
                except (ValueError, FileNotFoundError):
                    return self.error(404, "Энэ дууны ID олдсонгүй эсвэл зөвшөөрөгдөөгүй.")
                except OSError:
                    return self.error(503, "Дууг уншиж чадсангүй.")
            if path in {"/", "/index.html"}:
                file = (root / "demo" / "index.html").resolve()
                if file.parent != root / "demo" or not file.is_file():
                    return self.error(404, "Demo хуудас олдсонгүй.")
                return self.send_data(200, file.read_bytes(), "text/html; charset=utf-8")
            if path == "/api/status":
                samples = [{"id": name[:-4], "url": f"/demo/audio/{name}",
                            "available": self.authorized_sample(name) is not None}
                           for name in AUDIO_NAMES]
                manifest_path = (root / "demo" / "audio" / "samples.json").resolve()
                if manifest_path.parent == root / "demo" / "audio" and manifest_path.is_file():
                    try:
                        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                        if manifest.get("publication_authorized_by_user") is True:
                            allowed_fields = {"reference", "stt_text", "duration_seconds",
                                              "sample_rate_hz", "wer", "cer"}
                            for published in manifest.get("samples", []):
                                for sample in samples:
                                    if published.get("filename") == sample["id"] + ".wav":
                                        sample.update({key: value for key, value in published.items()
                                                       if key in allowed_fields})
                    except (OSError, ValueError, AttributeError, TypeError):
                        pass
                content = {"available": False, "counts": {}, "approval_counts": {}}
                try:
                    with ReadOnlyContentStore(database) as store:
                        package = store.export()
                        content = {"available": True, "counts": store.counts(),
                                   "package_id": store.package_id(),
                                   "approval_counts": {
                                       kind: dict(Counter(item["approval_status"] for item in package[kind]))
                                       for kind in ("sources", "facts", "faqs")}}
                except (OSError, sqlite3.Error, ValueError, KeyError):
                    content["message"] = "Эхлээд draft агуулгыг SQLite-д импортлоно."
                try:
                    website = website_status(website_database)
                except (OSError, sqlite3.Error, ValueError):
                    website = {"available": False, "pages": 0, "chunks": 0, "documents": 0,
                               "message": "Албан сайтын мэдээллийг эхлээд цуглуулна."}
                voice_state = voice.status()
                rag_state = rag.status()
                return self.send_json(200, {
                    "website": website, "content_policy": content_policy.status(), "llm": llm.status(),
                    "rag": rag_state,
                    "clarification": {**clarification_context.status(),
                                      "loaded_artifact_sha256": dict(CLARIFICATION_ARTIFACT_SHA256)},
                    "routing": {"available": True, "c_enabled": rag_state["provider"]["available"] and content_policy.enabled, "human_gold": False,
                                "mode": "development_proposed_not_gold"},
                    "mode": "local_development", "demo_protocol_version": 2, "readonly": False,
                    "content_database_readonly": True, "local_review_writes_supported": True,
                    "voice": voice_state, "content": content,
                    "content_release": bundle.public(),
                    "teacher_media": teachers.status(),
                    "audio_samples": samples,
                    "stt": {"wer_percent": 36.0, "cer_percent": 16.9, "verified_recordings": 13,
                            "historical_development_result": True, "production_accepted": False},
                    "retrieval": {"live_backend": rag_state.get("retrieval", {}).get("backend", "bm25"), "historical_bm25_top1": "10/15",
                                  "historical_e5_top1": "14/15", "human_gold_approved": False,
                                  "score_is_probability": False},
                    "microphone_connected": voice_state.get("stt_ready", False),
                    "tts_connected": voice_state.get("tts_ready", False),
                    "generated": False, "llm_calls": 0})
            prefix = next((p for p in ("/demo/audio/", "/sample-audio/")
                           if path.startswith(p)), None)
            if prefix is not None:
                name = path[len(prefix):]
                file = self.authorized_sample(name) if name in AUDIO_NAMES else None
                if file:
                    return self.send_data(200, file.read_bytes(), "audio/wav")
            self.error(404, "Энэ файл эсвэл API нээлттэй биш.")

        def read_body(self, maximum):
            origin = self.headers.get("Origin")
            port_number = self.server.server_address[1]
            if origin and origin not in {f"http://127.0.0.1:{port_number}",
                                         f"http://localhost:{port_number}"}:
                raise PermissionError("Өөр сайтаас API дуудахгүй.")
            if self.headers.get("Sec-Fetch-Site") == "cross-site":
                raise PermissionError("Өөр сайтаас API дуудахгүй.")
            if self.headers.get_all("Transfer-Encoding", []):
                raise ValueError("Content-Length бүхий хүсэлт шаардлагатай.")
            length = _content_length(self.headers)
            if length is None:
                raise ValueError("Хүчинтэй Content-Length шаардлагатай.")
            if not 0 < length <= maximum:
                raise ValueError(f"Өгөгдлийн хэмжээ 1–{maximum} byte байна.")
            self.connection.settimeout(15)
            encoded = self.rfile.read(length)
            self._body_bytes_read = len(encoded)
            if len(encoded) != length:
                raise ValueError("Хүсэлтийн өгөгдөл дутуу ирлээ.")
            return encoded

        def read_json(self, maximum=MAX_BODY):
            encoded = self.read_body(maximum)
            if self.headers.get_content_type() != "application/json":
                raise ValueError("Content-Type нь application/json байх ёстой.")
            try:
                body = json.loads(encoded.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError("JSON өгөгдөл буруу.") from error
            if not isinstance(body, dict):
                raise ValueError("JSON object шаардлагатай.")
            return body

        def do_POST(self):
            self._body_bytes_read = 0
            if not self.valid_host():
                return self.error(403, "Зөвхөн localhost хаягаас нээнэ.")
            path = unquote(urlsplit(self.path).path)
            if path.startswith('/api/admin/'):
                try:
                    return self.admin_post(path)
                except ReleaseError as error:
                    return self.error(error.status, str(error))
                except PermissionError as error:
                    return self.error(403, str(error))
                except (ValueError, OSError, KeyError, TypeError, sqlite3.Error) as error:
                    return self.error(400, str(error))
            if path not in {"/api/search", "/api/preview", "/api/website-search", "/api/route",
                            "/api/conversation/reset",
                            "/api/voice/transcribe", "/api/voice/speak", "/api/voice/reset", "/api/voice/correct",
                            "/api/review/stt-confirm", "/api/review/tts-confirm"}:
                return self.error(404, "Энэ API нээлттэй биш.")
            try:
                if path == "/api/voice/transcribe":
                    audio = self.read_body(MAX_AUDIO_BYTES)
                    result = voice.transcribe(audio, self.headers.get_content_type())
                    return self.send_json(200, result)
                body = self.read_json(24576 if path.startswith("/api/review/") else MAX_BODY)
                if path == "/api/conversation/reset":
                    if set(body) != {"clarification_ids"}:
                        raise ValueError("Зөвхөн clarification_ids жагсаалт өгнө.")
                    return self.send_json(200, live_content.snapshot().clarification.reset(body["clarification_ids"]))
                if path == "/api/voice/correct":
                    if set(body) != {"text"}:
                        raise ValueError("Зөвхөн text талбар өгнө.")
                    text = body["text"]
                    if not isinstance(text, str) or not text.strip() or len(text) > 1000:
                        raise ValueError("STT текст 1–1000 тэмдэгттэй байна.")
                    return self.send_json(200, llm.suggest_correction(text))
                if path == "/api/voice/reset":
                    if set(body) != {"ids"}:
                        raise ValueError("Зөвхөн ids жагсаалт өгнө.")
                    return self.send_json(200, voice.reset(body["ids"]))
                if path == "/api/review/stt-confirm":
                    if set(body) != {"id", "text", "confirmed"}:
                        raise ValueError("id, text, confirmed шаардлагатай.")
                    result = review.confirm_stt(body["id"], body["text"], body["confirmed"])
                    result["rescore"] = review.rescore_existing()
                    return self.send_json(200, result)
                if path == "/api/review/tts-confirm":
                    if set(body) != {"id", "listener", "overall", "intelligibility",
                                     "pronunciation_errors", "confirmed"}:
                        raise ValueError("Сонсголын бүх талбар шаардлагатай.")
                    return self.send_json(200, review.save_tts(
                        body["id"], body["listener"], body["overall"], body["intelligibility"],
                        body["pronunciation_errors"], body["confirmed"]))
                bundle = live_content.snapshot()
                database, rag = bundle.database, bundle.rag
                clarification_context = bundle.clarification
                if path == "/api/voice/speak":
                    if set(body) - {"query", "allow_draft", "voice", "package_id", "response_id", "release_token"}:
                        raise ValueError("Зөвшөөрөөгүй талбар байна.")
                    if body.get('release_token') != bundle.token:
                        return self.error(409, 'Мэдээллийн хувилбар солигдсон. Асуултаа дахин илгээнэ үү.')
                    query, draft = body.get("query"), body.get("allow_draft", False)
                    if not isinstance(query, str) or not query.strip() or len(query) > 1000 or type(draft) is not bool:
                        raise ValueError("Асуулт болон draft горим буруу.")
                    current = content_policy.route(database, query.strip(), allow_draft=draft)
                    if body.get("package_id") != current["package_id"]:
                        return self.error(409, "Агуулгын хувилбар өөрчлөгдлөө. Асуултаа дахин шалгана уу.")
                    response_id = body.get("response_id")
                    if response_id is not None:
                        if not isinstance(response_id, str) or not re.fullmatch(r"[0-9a-f]{32}", response_id):
                            raise ValueError("Хариултын ID буруу.")
                        try:
                            current = rag.recall(response_id, query.strip(), current["package_id"], draft)
                        except ValueError as error:
                            return self.error(409, str(error))
                    teacher_bundle = current.get('teacher_media_bundle_id')
                    if teacher_bundle is not None:
                        teacher_state = teachers.status()
                        if not teacher_state.get('available') or teacher_bundle != teacher_state.get('bundle_id'):
                            return self.error(409, 'Багшийн танилцуулгын эх өөрчлөгдсөн. Асуултаа дахин илгээнэ үү.')
                    spoken = spoken_text(current)
                    result = voice.synthesize(spoken, body.get("voice"))
                    if not live_content.is_current(bundle):
                        voice.reset([result['id']])
                        return self.error(409, 'Дуу бэлтгэх үед мэдээллийн хувилбар солигдсон. Асуултаа дахин илгээнэ үү.')
                    if teacher_bundle is not None:
                        teacher_state = teachers.status()
                        if not teacher_state.get('available') or teacher_bundle != teacher_state.get('bundle_id'):
                            voice.reset([result['id']])
                            return self.error(409, 'Дуу бэлтгэх үед багшийн эх өөрчлөгдсөн. Асуултаа дахин илгээнэ үү.')
                    result['content_release'] = bundle.public()
                    answer_rag=current.get('rag') or {}
                    authored=answer_rag.get('answer_text_generated',current.get('generated',False))
                    result.update(route=current["route"], package_id=current["package_id"],
                                  spoken_text=spoken, citations=current["citations"],
                                  text_generated=authored, llm_calls=0,
                                  answer_llm_calls=current.get('llm_calls',0),
                                  answer_llm_role=answer_rag.get('llm_role','text_generation' if authored else 'none'),
                                  answer_kind=current.get("answer_kind"))
                    return self.send_json(200, result)
                allowed = ({"query", "allow_draft", "clarification_id", "transcription_id"} if path == "/api/route" else
                           {"query", "allow_draft", "limit"} if path in {"/api/search", "/api/website-search"} else
                           {"faq_id", "allow_draft"})
                if set(body) - allowed:
                    raise ValueError("Зөвшөөрөөгүй талбар байна.")
                allow_draft = body.get("allow_draft", False)
                if type(allow_draft) is not bool:
                    raise ValueError("allow_draft нь true эсвэл false байна.")
                if path in {"/api/search", "/api/website-search", "/api/route"}:
                    query = body.get("query")
                    limit = body.get("limit", 5)
                    if not isinstance(query, str) or not query.strip() or len(query) > 1000:
                        raise ValueError("Асуулт 1–1000 тэмдэгттэй байна.")
                    if type(limit) is not int or not 1 <= limit <= 5:
                        raise ValueError("limit нь 1–5 бүхэл тоо байна.")
                    if path == "/api/route":
                        context_started = time.perf_counter()
                        raw_query = query.strip()
                        input_lineage = ({'kind': 'typed', 'submitted_text': raw_query,
                                          'manual_verification_claimed': False}
                            if 'transcription_id' not in body else
                            voice.transcription_lineage(body['transcription_id'], raw_query))
                        conversation = dict(raw_query=raw_query, resolved_query=raw_query,
                                            applied=False, reason="fresh_query", clarification_id=None)
                        if "clarification_id" in body:
                            token = body["clarification_id"]
                            if not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{32}", token):
                                raise ValueError("Тодруулгын ID буруу.")
                            # Read the current package/corpus independently of the
                            # short reply; neither client text nor cached D is an
                            # answer or authorization to bypass routing guards.
                            with ReadOnlyContentStore(database) as store:
                                package_id = store.package_id()
                            retriever = getattr(rag, "retriever", None)
                            corpus_id = (retriever.status().get("corpus_id") if retriever is not None
                                         else rag.status().get("retrieval", {}).get("corpus_id"))
                            conversation = clarification_context.resolve(
                                token, raw_query, allow_draft=allow_draft,
                                package_id=package_id, corpus_id=corpus_id)
                        context_elapsed = time.perf_counter() - context_started
                        result = self.teacher_answer(conversation['resolved_query'], allow_draft, database, rag)
                        if result is None:
                            result = rag.route(database, conversation["resolved_query"], allow_draft=allow_draft)
                            cards = teachers.attach(conversation['resolved_query'], result)
                            if cards:
                                result['teacher_cards'] = cards
                                result['teacher_media_bundle_id'] = cards[0]['bundle_id']
                                result = rag._remember(result, allow_draft)
                        context_started = time.perf_counter()
                        if "clarification_id" in body:
                            result_corpus = (result.get("rag") or {}).get("corpus_id")
                            if result["package_id"] != package_id or (result_corpus is not None and result_corpus != corpus_id):
                                raise ClarificationConflict("Тодруулах үед эхийн хувилбар өөрчлөгдлөө. Бүтэн асуултаа дахин илгээнэ үү.")
                        conversation["clarification_id"] = clarification_context.issue(result, allow_draft=allow_draft)
                        conversation["context_latency_ms"] = round(
                            (context_elapsed + time.perf_counter() - context_started) * 1000, 3)
                        conversation["latency_scope"] = "clarification_package_corpus_checks_resolution_and_issue; excludes_rag_route_http_stt_tts"
                        result["conversation"] = conversation
                        result['input_lineage'] = input_lineage
                        if not live_content.is_current(bundle):
                            raise ClarificationConflict('Хариулах үед мэдээллийн хувилбар солигдсон. Асуултаа дахин илгээнэ үү.')
                        result['content_release'] = bundle.public()
                        return self.send_json(200, result)
                    if path == "/api/website-search":
                        result = search_website(query.strip(), bundle.website_database,
                                                limit=limit, allow_draft=allow_draft or content_policy.enabled)
                        if content_policy.enabled and not allow_draft:
                            result.update(mode="official_website", source_accepted_for_project=True,
                                          acceptance_basis="user_acceptance_of_official_website",
                                          school_staff_approval_claimed=False)
                            for match in result["matches"]:
                                match["source_accepted_for_project"] = True
                        return self.send_json(200, result)
                    result = content_policy.search(database, query.strip(), backend="bm25",
                                                   top_k=limit, allow_draft=allow_draft)
                else:
                    record_id = body.get("faq_id")
                    if not isinstance(record_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", record_id):
                        raise ValueError("faq_id буруу.")
                    with ReadOnlyContentStore(database) as store:
                        result = content_policy.preview(store, record_id, allow_draft=allow_draft)
                    result["is_answer_to_query"] = False
                    result["preview_notice"] = "Сонгосон FAQ-г харуулж байна; асуултад зөв таарсан нь батлагдаагүй."
                return self.send_json(200, result)
            except VoiceRuntimeError as error:
                self.close_connection = True
                return self.send_json(error.status, {"error": str(error), "code": error.code})
            except TeacherMediaError:
                return self.error(503, 'Багшийн эхийн санг шалгаж чадсангүй. Түр хүлээгээд дахин оролдоно уу.')
            except PermissionError as error:
                return self.error(403, str(error))
            except ClarificationConflict as error:
                return self.error(409, str(error))
            except ReleaseError:
                return self.error(503, 'Идэвхтэй эхийн хувилбарыг шалгаж чадсангүй. Админ хэсгээс шалгана уу.')
            except ValueError as error:
                return self.error(400, str(error))
            except KeyError:
                return self.error(404, "FAQ эсвэл импортолсон багц олдсонгүй.")
            except (OSError, sqlite3.Error):
                return self.error(503, "SQLite агуулга бэлэн биш. Эхлээд импортлоно.")
            except RuntimeError as error:
                return self.error(503, str(error))

        def do_PUT(self):
            self.error(405, "Энэ API нь PUT дэмжихгүй.")

        def do_DELETE(self):
            self.error(405, "Энэ API нь DELETE дэмжихгүй.")

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser(description="Локал дуу/FAQ demo — сургуулийн SQLite зөвхөн уншина")
    parser.add_argument("--db", type=Path, default=ROOT / "runtime" / "content.db")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    with make_server(args.db, port=args.port) as server:
        print(f"Demo: http://127.0.0.1:{args.port}  (Ctrl+C to stop)", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
