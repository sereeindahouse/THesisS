"""Local, read-only development UI. Only three explicitly published samples are served."""
import argparse
import json
import re
import sqlite3
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from sqlite_retrieval import ReadOnlyContentStore, guarded_preview, search_content

ROOT = Path(__file__).resolve().parent
MAX_BODY = 8192
AUDIO_NAMES = ("q01.wav", "q02.wav", "q03.wav")


def make_server(db_path=None, *, port=8765, project_root=None):
    """Bind loopback only; open each worker connection read-only per request."""
    root = Path(project_root or ROOT).resolve()
    database = Path(db_path or root / "runtime" / "content.db").resolve()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def send_data(self, code, body, content_type):
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                             "style-src 'self' 'unsafe-inline'; connect-src 'self'; "
                             "media-src 'self'; object-src 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def send_json(self, code, value):
            self.send_data(code, json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"),
                           "application/json; charset=utf-8")

        def error(self, code, message):
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
            path = unquote(urlsplit(self.path).path)
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
                return self.send_json(200, {
                    "mode": "local_development", "readonly": True, "content": content,
                    "audio_samples": samples,
                    "stt": {"wer_percent": 36.0, "cer_percent": 16.9, "verified_recordings": 13,
                            "historical_development_result": True, "production_accepted": False},
                    "retrieval": {"live_backend": "bm25", "historical_bm25_top1": "10/15",
                                  "historical_e5_top1": "14/15", "human_gold_approved": False,
                                  "score_is_probability": False},
                    "microphone_connected": False, "tts_connected": False,
                    "generated": False, "llm_calls": 0})
            prefix = next((p for p in ("/demo/audio/", "/sample-audio/")
                           if path.startswith(p)), None)
            if prefix is not None:
                name = path[len(prefix):]
                file = self.authorized_sample(name) if name in AUDIO_NAMES else None
                if file:
                    return self.send_data(200, file.read_bytes(), "audio/wav")
            self.error(404, "Энэ файл эсвэл API нээлттэй биш.")

        def read_json(self):
            if self.headers.get_content_type() != "application/json":
                raise ValueError("Content-Type нь application/json байх ёстой.")
            origin = self.headers.get("Origin")
            port_number = self.server.server_address[1]
            if origin and origin not in {f"http://127.0.0.1:{port_number}",
                                         f"http://localhost:{port_number}"}:
                raise PermissionError("Өөр сайтаас API дуудахгүй.")
            raw_length = self.headers.get("Content-Length")
            if not raw_length or not raw_length.isdigit():
                raise ValueError("Хүчинтэй Content-Length шаардлагатай.")
            length = int(raw_length)
            if not 0 < length <= MAX_BODY:
                raise ValueError("JSON өгөгдлийн хэмжээ 1–8192 byte байна.")
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError("JSON өгөгдөл буруу.") from error
            if not isinstance(body, dict):
                raise ValueError("JSON object шаардлагатай.")
            return body

        def do_POST(self):
            if not self.valid_host():
                return self.error(403, "Зөвхөн localhost хаягаас нээнэ.")
            path = unquote(urlsplit(self.path).path)
            if path not in {"/api/search", "/api/preview"}:
                return self.error(404, "Энэ API нээлттэй биш.")
            try:
                body = self.read_json()
                allowed = {"query", "allow_draft", "limit"} if path == "/api/search" else {
                    "faq_id", "allow_draft"}
                if set(body) - allowed:
                    raise ValueError("Зөвшөөрөөгүй талбар байна.")
                allow_draft = body.get("allow_draft", False)
                if type(allow_draft) is not bool:
                    raise ValueError("allow_draft нь true эсвэл false байна.")
                if path == "/api/search":
                    query = body.get("query")
                    limit = body.get("limit", 5)
                    if not isinstance(query, str) or not query.strip() or len(query) > 1000:
                        raise ValueError("Асуулт 1–1000 тэмдэгттэй байна.")
                    if type(limit) is not int or not 1 <= limit <= 5:
                        raise ValueError("limit нь 1–5 бүхэл тоо байна.")
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
            except PermissionError as error:
                return self.error(403, str(error))
            except ValueError as error:
                return self.error(400, str(error))
            except KeyError:
                return self.error(404, "FAQ эсвэл импортолсон багц олдсонгүй.")
            except (OSError, sqlite3.Error):
                return self.error(503, "SQLite агуулга бэлэн биш. Эхлээд импортлоно.")

        def do_PUT(self):
            self.error(405, "Энэ demo өгөгдөл өөрчлөхгүй.")

        def do_DELETE(self):
            self.error(405, "Энэ demo өгөгдөл өөрчлөхгүй.")

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser(description="Локал SQLite FAQ demo — зөвхөн унших горим")
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
