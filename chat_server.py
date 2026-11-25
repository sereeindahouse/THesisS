"""ШМТК-ийн ухаалаг туслах — the chat server: one page, typed and spoken questions, sourced answers.

Loopback only (127.0.0.1). The page asks /api/route; every answer is taken from the stored school
sources (the website copy, the school's tables) by rag_runtime.ChatRAG, which writes no text of its
own. Speech goes through voice_runtime (Gemini transcription, online text-to-speech).

    python chat_server.py            ->  http://127.0.0.1:8780
"""
import argparse
import json
import re
import secrets
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from answer_contract import spoken_text
from clarification_context import ClarificationConflict, ClarificationContext
from latin_query import to_cyrillic, vocabulary_from
from privacy_filter import hide_mobiles
from project_policy import ContentUsePolicy
from question_planner import QuestionPlanner, compose as compose_parts
from rag_runtime import ChatRAG
from sqlite_retrieval import ReadOnlyContentStore
from teacher_media import TeacherMedia, TeacherMediaError
from voice_runtime import MAX_AUDIO_BYTES, VoiceRuntime, VoiceRuntimeError
from website_retrieval import WebsiteRetriever

ROOT = Path(__file__).resolve().parent
PORT = 8780
MAX_BODY = 8192
PAGE = 'web/index.html'
POST_PATHS = frozenset({'/api/route', '/api/conversation/reset', '/api/voice/transcribe', '/api/voice/speak',
                        '/api/voice/reset', '/api/voice/gemini/configure', '/api/voice/gemini/clear'})


def _content_length(headers):
    """One bounded ASCII decimal Content-Length, or None."""
    lengths = headers.get_all('Content-Length', [])
    if len(lengths) != 1 or not re.fullmatch(r'[0-9]{1,10}', lengths[0]):
        return None
    return int(lengths[0])


def content_databases(root):
    """(school content database, website database, release token or None).

    A published content release, when the project keeps one, is the source; otherwise the two
    databases stored with the project (the chat-only copy holds just these two). Read once, when the
    server starts: after a release is published or rolled back, restart this server. A damaged
    active release is not replaced by something else — resolve() raises and the server does not start."""
    root = Path(root)
    if (root / 'runtime/content-releases/active.json').is_file():
        from content_release import ContentReleaseManager
        active = ContentReleaseManager(root).resolve()
        if active is not None:
            return Path(active['content_database']), Path(active['website_database']), active['activation_token']
    return root / 'runtime/content.db', root / 'CORE/database/website.db', None


def make_server(*, port=PORT, project_root=None, voice_service=None, rag_service=None, teacher_service=None):
    """Bind loopback only; the content databases are opened read-only for each request."""
    root = Path(project_root or ROOT).resolve()
    database, website_database, release_token = content_databases(root)
    voice = voice_service if voice_service is not None else VoiceRuntime(root)
    content_policy = ContentUsePolicy(root)
    # The school is in Ulaanbaatar (UTC+8, no DST): timetable answers need the real date and time.
    rag = rag_service if rag_service is not None else ChatRAG(
        root, content_policy, retriever=WebsiteRetriever(root=root, database=website_database),
        reception_clock=lambda: datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None))
    clarification_context = ClarificationContext()
    teachers = teacher_service if teacher_service is not None else TeacherMedia(root)
    gemini_token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *args):
            pass

        def send_data(self, code, body, content_type):
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            if self.close_connection:
                self.send_header('Connection', 'close')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Cross-Origin-Resource-Policy', 'same-origin')
            self.send_header('Content-Security-Policy',
                             "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                             "style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; "
                             "media-src 'self' blob:; object-src 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def send_json(self, code, value):
            # Staff mobiles printed on the website never leave the server. A visitor's own transcript
            # goes back unchanged: its lineage is checked against it later.
            if urlsplit(self.path).path != '/api/voice/transcribe':
                value = hide_mobiles(value)
            self.send_data(code, json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8'),
                           'application/json; charset=utf-8')

        def error(self, code, message):
            self.close_connection = True
            # A close with unread incoming bytes can lose the JSON response through a TCP reset
            # (seen on Windows): discard a small, explicitly framed remainder, never parse it.
            length = _content_length(self.headers)
            if (self.command == 'POST' and length is not None
                    and not self.headers.get_all('Transfer-Encoding', [])):
                remaining = length - getattr(self, '_body_bytes_read', 0)
                if 0 < remaining <= 65536:
                    try:
                        self.connection.settimeout(0.25)
                        self.rfile.read(remaining)
                    except (OSError, TimeoutError):
                        pass
            self.send_json(code, {'error': message})

        def local_request(self, *, navigation=False):
            """Only this machine's own page may call the server."""
            port_number = self.server.server_address[1]
            origins = {f'http://127.0.0.1:{port_number}', f'http://localhost:{port_number}'}
            if self.headers.get('Host') not in {origin[len('http://'):] for origin in origins}:
                return False
            if self.headers.get('Sec-Fetch-Site') == 'cross-site' and not navigation:
                return False
            origin = self.headers.get('Origin')
            return not origin or origin in origins

        def latin_reading(self, query):
            """The Cyrillic reading of a question typed in Latin letters, or None (switch: planner config
            `latin_script`). An ambiguous letter is spelled as in the school's own texts."""
            try:
                settings = json.loads((root / 'config/question-planner.json').read_text(encoding='utf-8'))
            except (OSError, ValueError):
                return None
            if settings.get('latin_script') is not True:
                return None
            vocabulary = getattr(rag, '_latin_vocabulary', None)
            if vocabulary is None:
                retriever = getattr(rag, 'retriever', None)
                try:
                    retriever.status()          # loads the website texts on the first request
                except Exception:
                    pass
                rows = getattr(retriever, '_rows', None) or ()
                texts = [row.get('text', '') for row in rows]
                tables = getattr(getattr(rag, 'reception', None), 'tables', None)
                for room in getattr(tables, 'rooms', ()) or ():
                    texts += [room.purpose or '', room.department or '']
                for person in getattr(tables, 'staff', ()) or ():
                    texts += [person.name or '', person.role or '', person.department or '']
                vocabulary = vocabulary_from(texts)
                if rows:                        # never keep a vocabulary built without the website texts
                    rag._latin_vocabulary = vocabulary
            return to_cyrillic(query, vocabulary)

        def teacher_answer(self, query):
            """A teacher's introduction from the school website, with its picture when the site has one."""
            if not content_policy.enabled:
                return None
            match = teachers.profile(query)
            if match is None:
                return None
            result = content_policy.route(database, query, allow_draft=False)
            result.update(query=query, answer=None, citations=[], generated=False, llm_calls=0,
                          related_sources=[], suggestions=[], clarification=None,
                          teacher_media_bundle_id=match['bundle_id'])

            def citation(card):
                return dict(document_id=card['teacher_id'], version=1,
                            title=card['name'] + ' — багшийн албан танилцуулга',
                            source_url_or_filename=card['source_url'], locator=card['source_locator'],
                            retrieved_at=card['captured_utc'], source_html_sha256=card['source_html_sha256'],
                            source_accepted_for_project=True, school_staff_approval=False,
                            approval_status='draft', extraction_method='official_structured_teacher_record')
            if match['status'] == 'staff_scope_required':
                result.update(route='D', answer_kind='teacher_scope_clarification', reason_code='teacher_scope_required',
                              message='Аль тэнхимийн эсвэл ямар багшийн талаар мэдэх вэ? Нэр, тэнхим, багшийн тоо эсвэл '
                                      'танилцуулга гэдгээ тодруулна уу.',
                              suggestions=['Компьютерын ухааны багш нарын нэрсийг харуулна уу.',
                                           'Механик инженерийн тэнхим хэдэн багштай вэ?',
                                           'Химийн инженерийн тэнхимийн эрхлэгч хэн бэ?'])
            elif match['status'] == 'partial_directory':
                cards = match['profiles']
                if not cards:
                    return None
                result.update(route='A', answer_kind='partial_teacher_directory',
                              reason_code='captured_partial_teacher_directory',
                              answer='\n\n'.join(card['source_quote'] for card in cards),
                              message=match['department'] + ': сайтад танилцуулгатай ' + str(len(cards))
                                      + ' багшийг доор харуулав. Энэ нь бүх багшийн бүрэн жагсаалт биш.',
                              teacher_cards=cards, coverage='partial_captured_profiles', full_staff_roster=False,
                              citations=[citation(card) for card in cards])
            elif match['status'] == 'ambiguous':
                result.update(route='D', answer_kind='teacher_profile_clarification', reason_code='teacher_name_required',
                              message='Аль багшийн танилцуулгыг үзэх вэ? Сайтад танилцуулгатай зарим багшийг доор харуулав.',
                              suggestions=[name + ' багшийн зурагтай танилцуулгыг үзье.' for name in match['candidates'][:6]])
            else:
                card = match['profile']
                result.update(route='A', answer_kind='official_teacher_profile',
                              reason_code='source_bound_teacher_profile', answer=card['source_quote'],
                              message=('' if card.get('image_url') else
                                       'Багшийн зураг сайтад байхгүй тул нэр, танилцуулгыг нь харууллаа.'),
                              teacher_cards=[card], citations=[citation(card)])
            return rag._remember(result, False)

        def do_GET(self):
            path = unquote(urlsplit(self.path).path)
            page = path in {'/', '/index.html'}
            navigation = (page and self.headers.get('Sec-Fetch-Mode') == 'navigate'
                          and self.headers.get('Sec-Fetch-Dest') == 'document')
            if not self.local_request(navigation=navigation):
                return self.error(403, 'Зөвхөн энэ компьютерын хуудаснаас нээнэ.')
            if page:
                file = (root / PAGE).resolve()
                if not file.is_relative_to(root) or not file.is_file():
                    return self.error(404, 'Чатын хуудас олдсонгүй.')
                return self.send_data(200, file.read_bytes(), 'text/html; charset=utf-8')
            if path == '/api/status':
                voice_state = voice.status()
                cloud = voice_state.get('gemini', {})
                voice_state.update(active_stt_provider='gemini', model='gemini-3.5-transcribe',
                                   stt_ready=cloud.get('ready', False))
                counts = {}
                try:
                    with ReadOnlyContentStore(database) as store:
                        counts = store.counts()
                except (OSError, sqlite3.Error, ValueError, KeyError):
                    pass
                reception = getattr(rag, 'reception', None)
                return self.send_json(200, {
                    'service': 'nmct-assistant-chat', 'voice': voice_state, 'content': {'counts': counts},
                    'reception_tables': bool(getattr(reception, 'enabled', False) and getattr(reception, 'tables', None)),
                    'retrieval': rag.status().get('retrieval', {}), 'generated': False, 'llm_calls': 0})
            if path == '/api/voice/gemini/session':
                return self.send_json(200, dict(**voice.gemini.status(), csrf_token=gemini_token))
            if path.startswith('/api/teacher-media/'):
                try:
                    data, mime = teachers.media(path.removeprefix('/api/teacher-media/'))
                    return self.send_data(200, data, mime)
                except KeyError:
                    return self.error(404, 'Багшийн зураг олдсонгүй.')
                except (TeacherMediaError, ValueError, OSError):
                    return self.error(409, 'Зургийг шалгаж чадсангүй. Танилцуулгыг дахин нээнэ үү.')
            media = re.fullmatch(r'/api/voice/audio/([A-Za-z0-9_-]{1,64})', path)
            if media:
                try:
                    data, mime = voice.audio(media.group(1))
                    return self.send_data(200, data, mime)
                except (ValueError, FileNotFoundError):
                    return self.error(404, 'Энэ дуу олдсонгүй.')
                except OSError:
                    return self.error(503, 'Дууг уншиж чадсангүй.')
            self.error(404, 'Ийм хуудас алга.')

        def read_body(self, maximum):
            if self.headers.get_all('Transfer-Encoding', []):
                raise ValueError('Content-Length бүхий хүсэлт шаардлагатай.')
            length = _content_length(self.headers)
            if length is None:
                raise ValueError('Хүчинтэй Content-Length шаардлагатай.')
            if not 0 < length <= maximum:
                raise ValueError(f'Өгөгдлийн хэмжээ 1–{maximum} byte байна.')
            self.connection.settimeout(15)
            encoded = self.rfile.read(length)
            self._body_bytes_read = len(encoded)
            if len(encoded) != length:
                raise ValueError('Хүсэлтийн өгөгдөл дутуу ирлээ.')
            return encoded

        def read_json(self, maximum=MAX_BODY):
            encoded = self.read_body(maximum)
            if self.headers.get_content_type() != 'application/json':
                raise ValueError('Content-Type нь application/json байх ёстой.')
            try:
                body = json.loads(encoded.decode('utf-8'))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError('JSON өгөгдөл буруу.') from error
            if not isinstance(body, dict):
                raise ValueError('JSON object шаардлагатай.')
            return body

        def gemini_authorized(self):
            supplied = self.headers.get('X-Gemini-Token', '')
            if not supplied.isascii() or not secrets.compare_digest(supplied, gemini_token):
                raise PermissionError('Хуудсаа дахин ачаалж, дуу таних үйлчилгээг дахин нээнэ үү.')

        def answer_question(self, body):
            """One visitor question -> one reply: every part goes through the guarded route on its own."""
            if set(body) - {'query', 'clarification_id', 'transcription_id', 'context_query'}:
                raise ValueError('Зөвшөөрөөгүй талбар байна.')
            query = body.get('query')
            if not isinstance(query, str) or not query.strip() or len(query) > 1000:
                raise ValueError('Асуулт 1–1000 тэмдэгттэй байна.')
            context_started = time.perf_counter()
            # The page's previous question, only for an elliptical follow-up («Имэйл нь?»).
            context_query = body.get('context_query')
            if context_query is not None and (not isinstance(context_query, str)
                                              or not context_query.strip() or len(context_query) > 300):
                raise ValueError('context_query нь 1–300 тэмдэгттэй байна.')
            raw_query = query.strip()
            input_lineage = ({'kind': 'typed', 'submitted_text': raw_query, 'manual_verification_claimed': False}
                             if 'transcription_id' not in body else
                             voice.transcription_lineage(body['transcription_id'], raw_query))
            conversation = dict(raw_query=raw_query, resolved_query=raw_query, applied=False,
                                reason='fresh_query', clarification_id=None)
            latin = (self.latin_reading(raw_query) if input_lineage['kind'] == 'typed'
                     and 'clarification_id' not in body else None)
            if latin:
                conversation.update(resolved_query=latin, latin_script=dict(original=raw_query, read_as=latin))
            package_id = corpus_id = None
            if 'clarification_id' in body:
                token = body['clarification_id']
                if not isinstance(token, str) or not re.fullmatch(r'[0-9a-f]{32}', token):
                    raise ValueError('Тодруулгын ID буруу.')
                # The stored content is read again for the short reply: neither the page's text nor a
                # cached clarification is an answer.
                with ReadOnlyContentStore(database) as store:
                    package_id = store.package_id()
                corpus_id = rag.retriever.status().get('corpus_id')
                conversation = clarification_context.resolve(token, raw_query, allow_draft=False,
                                                             package_id=package_id, corpus_id=corpus_id)
            context_elapsed = time.perf_counter() - context_started

            def answer_one(text):
                # The school's tables (rooms, staff, classes, timetable) come before the website's
                # teacher introductions; neither claims where a person is right now.
                reception = getattr(rag, 'reception', None)
                one = (None if reception is not None and reception.recognizes(text) else self.teacher_answer(text))
                if one is None:
                    stt_options = ({'stt_text': True} if input_lineage['kind'] in {'raw_stt', 'edited_stt'}
                                   and getattr(getattr(rag, 'normalizer', None), 'enabled', False) else {})
                    one = rag.route(database, text, allow_draft=False, **stt_options)
                    cards = [] if one.get('answer_kind') == 'reception_table_lookup' else teachers.attach(text, one)
                    if cards:
                        one['teacher_cards'] = cards
                        one['teacher_media_bundle_id'] = cards[0]['bundle_id']
                        one = rag._remember(one, False)
                return one

            # Question understanding: a compound question is split, plain class and staff names are
            # resolved; every part keeps all the guards of the route.
            planner = getattr(rag, 'question_planner', None)
            if planner is None:
                planner = QuestionPlanner.from_config(root, getattr(rag, 'reception', None))
                rag.question_planner = planner
            plan = (planner.plan(conversation['resolved_query'], previous=context_query)
                    if planner.enabled and 'clarification_id' not in body else None)
            if plan is None or not plan['changed']:
                result = answer_one(conversation['resolved_query'])
            elif not plan['compound']:
                result = answer_one(plan['parts'][0]['query'])
                result['query'] = conversation['resolved_query']
                # Stored again under the visitor's own wording, which the page sends back to be spoken.
                result = rag._remember(result, False)
            else:
                result = compose_parts(conversation['resolved_query'], plan,
                                       [answer_one(part['query']) for part in plan['parts']])
                result = rag._remember(result, False)
            if plan is not None and plan['changed']:
                result['question_plan'] = plan
            if latin:
                result['latin_script'] = dict(original=raw_query, read_as=latin)   # «Ингэж ойлголоо: …»
            context_started = time.perf_counter()
            if 'clarification_id' in body:
                result_corpus = (result.get('rag') or {}).get('corpus_id')
                if result['package_id'] != package_id or (result_corpus is not None and result_corpus != corpus_id):
                    raise ClarificationConflict('Тодруулах үед мэдээлэл шинэчлэгдсэн. Бүтэн асуултаа дахин илгээнэ үү.')
            conversation['clarification_id'] = clarification_context.issue(result, allow_draft=False)
            conversation['context_latency_ms'] = round((context_elapsed + time.perf_counter() - context_started) * 1000, 3)
            result['conversation'] = conversation
            result['input_lineage'] = input_lineage
            result['content_release'] = {'activation_token': release_token}
            return result

        def speak(self, body):
            """The reply the page shows, read aloud; the stored answer is looked up again, not trusted from the page."""
            if set(body) - {'query', 'voice', 'package_id', 'response_id', 'release_token'}:
                raise ValueError('Зөвшөөрөөгүй талбар байна.')
            if body.get('release_token') != release_token:
                return self.error(409, 'Мэдээлэл шинэчлэгдсэн. Асуултаа дахин илгээнэ үү.')
            query = body.get('query')
            if not isinstance(query, str) or not query.strip() or len(query) > 1000:
                raise ValueError('Асуулт буруу.')
            current = content_policy.route(database, query.strip(), allow_draft=False)
            if body.get('package_id') != current['package_id']:
                return self.error(409, 'Мэдээлэл шинэчлэгдсэн. Асуултаа дахин илгээнэ үү.')
            response_id = body.get('response_id')
            if response_id is not None:
                if not isinstance(response_id, str) or not re.fullmatch(r'[0-9a-f]{32}', response_id):
                    raise ValueError('Хариултын ID буруу.')
                try:
                    current = rag.recall(response_id, query.strip(), current['package_id'], False)
                except ValueError as error:
                    return self.error(409, str(error))
            teacher_bundle = current.get('teacher_media_bundle_id')
            if teacher_bundle is not None:
                teacher_state = teachers.status()
                if not teacher_state.get('available') or teacher_bundle != teacher_state.get('bundle_id'):
                    return self.error(409, 'Багшийн танилцуулга шинэчлэгдсэн. Асуултаа дахин илгээнэ үү.')
            spoken = hide_mobiles(spoken_text(current))     # no staff mobile is read aloud
            result = voice.synthesize(spoken, body.get('voice'))
            result.update(route=current['route'], package_id=current['package_id'], spoken_text=spoken,
                          citations=current['citations'], answer_kind=current.get('answer_kind'))
            return self.send_json(200, result)

        def do_POST(self):
            self._body_bytes_read = 0
            if not self.local_request():
                return self.error(403, 'Зөвхөн энэ компьютерын хуудаснаас дуудна.')
            path = unquote(urlsplit(self.path).path)
            if path not in POST_PATHS:
                return self.error(404, 'Ийм үйлдэл алга.')
            try:
                if path == '/api/voice/transcribe':
                    audio = self.read_body(MAX_AUDIO_BYTES)
                    self.gemini_authorized()
                    return self.send_json(200, voice.transcribe_gemini(
                        audio, self.headers.get_content_type(),
                        consent=self.headers.get('X-Gemini-Audio-Consent') == 'send-this-audio', live=False))
                body = self.read_json()
                if path.startswith('/api/voice/gemini/'):
                    self.gemini_authorized()
                    if path.endswith('/clear'):
                        if body != {}:
                            raise ValueError('Түлхүүр арилгах хүсэлт хоосон object байна.')
                        return self.send_json(200, voice.gemini.clear())
                    return self.send_json(200, voice.gemini.configure(body))
                if path == '/api/conversation/reset':
                    if set(body) != {'clarification_ids'}:
                        raise ValueError('Зөвхөн clarification_ids жагсаалт өгнө.')
                    return self.send_json(200, clarification_context.reset(body['clarification_ids']))
                if path == '/api/voice/reset':
                    if set(body) != {'ids'}:
                        raise ValueError('Зөвхөн ids жагсаалт өгнө.')
                    return self.send_json(200, voice.reset(body['ids']))
                if path == '/api/voice/speak':
                    return self.speak(body)
                return self.send_json(200, self.answer_question(body))
            except VoiceRuntimeError as error:
                self.close_connection = True
                return self.send_json(error.status, {'error': str(error), 'code': error.code})
            except TeacherMediaError:
                return self.error(503, 'Багшийн танилцуулгыг шалгаж чадсангүй. Түр хүлээгээд дахин оролдоно уу.')
            except PermissionError as error:
                return self.error(403, str(error))
            except ClarificationConflict as error:
                return self.error(409, str(error))
            except ValueError as error:
                return self.error(400, str(error))
            except KeyError:
                return self.error(404, 'Хадгалсан мэдээлэл олдсонгүй.')
            except (OSError, sqlite3.Error):
                return self.error(503, 'Мэдээллийн сан бэлэн биш байна.')
            except RuntimeError as error:
                return self.error(503, str(error))

        def do_PUT(self):
            self.error(405, 'Энэ сервер PUT дэмжихгүй.')

        def do_DELETE(self):
            self.error(405, 'Энэ сервер DELETE дэмжихгүй.')

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


def already_running(port):
    """Whether this chat server already answers on the port (started twice: open the page, do not fail)."""
    import urllib.request
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f'http://127.0.0.1:{port}/api/status', timeout=3) as response:
            return json.loads(response.read(65536)).get('service') == 'nmct-assistant-chat'
    except (OSError, ValueError, AttributeError):
        return False


def main():
    parser = argparse.ArgumentParser(description='ШМТК-ийн ухаалаг туслах — чатын сервер')
    parser.add_argument('--port', type=int, default=PORT)
    parser.add_argument('--open', action='store_true', help='хуудсыг хөтчөөр нээнэ')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('--port must be between 1 and 65535')
    url = f'http://127.0.0.1:{args.port}'
    if already_running(args.port):
        print(f'ШМТК-ийн ухаалаг туслах аль хэдийн ажиллаж байна: {url}', flush=True)
        if args.open:
            import webbrowser
            webbrowser.open(url)
        return
    with make_server(port=args.port) as server:
        print(f'ШМТК-ийн ухаалаг туслах: {url}  (зогсоох: Ctrl+C)', flush=True)
        if args.open:
            import webbrowser
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
