"""Loopback development UI: read-only school content, private voice and human review."""
import argparse
import json
import re
import sqlite3
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from sqlite_retrieval import ReadOnlyContentStore, guarded_preview, search_content
from CORE.website_corpus import website_status, search_website
from question_router import route_question
from voice_runtime import VoiceRuntime, VoiceRuntimeError, MAX_AUDIO_BYTES
from listening_review import ListeningReview

ROOT = Path(__file__).resolve().parent
MAX_BODY = 8192
AUDIO_NAMES = ("q01.wav", "q02.wav", "q03.wav")


def make_server(db_path=None, *, port=8765, project_root=None, voice_service=None, review_service=None):
    """Bind loopback only; open each worker connection read-only per request."""
    root = Path(project_root or ROOT).resolve()
    database = Path(db_path or root / "runtime" / "content.db").resolve()
    voice = voice_service if voice_service is not None else VoiceRuntime(root)
    review = review_service if review_service is not None else ListeningReview(root)

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

        def do_GET(self):
            if not self.valid_host():
                return self.error(403, "Зөвхөн localhost хаягаас нээнэ.")
            if self.headers.get("Sec-Fetch-Site") == "cross-site":
                return self.error(403, "Өөр сайтаас локал өгөгдөл уншихгүй.")
            path = unquote(urlsplit(self.path).path)
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
                    website = website_status(root / "CORE/database/website.db")
                except (OSError, sqlite3.Error, ValueError):
                    website = {"available": False, "pages": 0, "chunks": 0, "documents": 0,
                               "message": "Албан сайтын мэдээллийг эхлээд цуглуулна."}
                voice_state = voice.status()
                return self.send_json(200, {
                    "website": website,
                    "routing": {"available": True, "c_enabled": False, "human_gold": False,
                                "mode": "development_proposed_not_gold"},
                    "mode": "local_development", "demo_protocol_version": 2, "readonly": False,
                    "content_database_readonly": True, "local_review_writes_supported": True,
                    "voice": voice_state, "content": content,
                    "audio_samples": samples,
                    "stt": {"wer_percent": 36.0, "cer_percent": 16.9, "verified_recordings": 13,
                            "historical_development_result": True, "production_accepted": False},
                    "retrieval": {"live_backend": "bm25", "historical_bm25_top1": "10/15",
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
            if self.headers.get("Transfer-Encoding"):
                raise ValueError("Content-Length бүхий хүсэлт шаардлагатай.")
            raw_length = self.headers.get("Content-Length")
            if not raw_length or not raw_length.isdigit():
                raise ValueError("Хүчинтэй Content-Length шаардлагатай.")
            length = int(raw_length)
            if not 0 < length <= maximum:
                raise ValueError(f"Өгөгдлийн хэмжээ 1–{maximum} byte байна.")
            self.connection.settimeout(15)
            encoded = self.rfile.read(length)
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
            if not self.valid_host():
                return self.error(403, "Зөвхөн localhost хаягаас нээнэ.")
            path = unquote(urlsplit(self.path).path)
            if path not in {"/api/search", "/api/preview", "/api/website-search", "/api/route",
                            "/api/voice/transcribe", "/api/voice/speak", "/api/voice/reset",
                            "/api/review/stt-confirm", "/api/review/tts-confirm"}:
                return self.error(404, "Энэ API нээлттэй биш.")
            try:
                if path == "/api/voice/transcribe":
                    audio = self.read_body(MAX_AUDIO_BYTES)
                    result = voice.transcribe(audio, self.headers.get_content_type())
                    return self.send_json(200, result)
                body = self.read_json(24576 if path.startswith("/api/review/") else MAX_BODY)
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
                if path == "/api/voice/speak":
                    if set(body) - {"query", "allow_draft", "voice", "package_id"}:
                        raise ValueError("Зөвшөөрөөгүй талбар байна.")
                    query, draft = body.get("query"), body.get("allow_draft", False)
                    if not isinstance(query, str) or not query.strip() or len(query) > 1000 or type(draft) is not bool:
                        raise ValueError("Асуулт болон draft горим буруу.")
                    current = route_question(database, query.strip(), allow_draft=draft)
                    if body.get("package_id") != current["package_id"]:
                        return self.error(409, "Агуулгын хувилбар өөрчлөгдлөө. Асуултаа дахин шалгана уу.")
                    spoken = current["answer"]
                    if spoken is None:
                        spoken = current["message"]
                        if current.get("clarification"):
                            spoken += " " + current["clarification"]["question"]
                    elif current.get("answer_kind") == "development_draft_preview":
                        spoken = "Ноорог, сургуулиар баталгаажаагүй. " + spoken
                    result = voice.synthesize(spoken, body.get("voice"))
                    result.update(route=current["route"], package_id=current["package_id"],
                                  spoken_text=spoken, citations=current["citations"],
                                  text_generated=False, llm_calls=0,
                                  answer_kind=current.get("answer_kind"))
                    return self.send_json(200, result)
                allowed = ({"query", "allow_draft"} if path == "/api/route" else
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
                        return self.send_json(200, route_question(database, query.strip(), allow_draft=allow_draft))
                    if path == "/api/website-search":
                        return self.send_json(200, search_website(query.strip(), root / "CORE/database/website.db",
                                                                 limit=limit, allow_draft=allow_draft))
                    result = search_content(database, query.strip(), backend="bm25",
                                            top_k=limit, allow_draft=allow_draft)
                    result.pop("answer", None)
                    result.pop("answer_faq_id", None)
                    result.pop("exact_match_preview", None)
                    result["answer_served"] = False
                    result["preview_requires_selection"] = True
                else:
                    record_id = body.get("faq_id")
                    if not isinstance(record_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", record_id):
                        raise ValueError("faq_id буруу.")
                    with ReadOnlyContentStore(database) as store:
                        result = guarded_preview(store, record_id, allow_draft=allow_draft)
                    result["is_answer_to_query"] = False
                    result["preview_notice"] = "Сонгосон FAQ-г харуулж байна; асуултад зөв таарсан нь батлагдаагүй."
                return self.send_json(200, result)
            except VoiceRuntimeError as error:
                self.close_connection = True
                return self.send_json(error.status, {"error": str(error), "code": error.code})
            except PermissionError as error:
                return self.error(403, str(error))
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
