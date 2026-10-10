"""HTTP contracts use invented content; no student recordings or approval are inferred."""
import copy
import hashlib
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from content_store import ContentStore
from demo_server import make_server


def fixture(state="draft"):
    metadata = {"approval_status": state,
                "approved_by": "test-only reviewer" if state == "approved" else None,
                "approved_at": "2026-10-10T09:00:00+08:00" if state == "approved" else None,
                "valid_from": "2020-01-01", "valid_until": "2099-12-31"}
    ref = {"document_id": "test.source", "version": 1, "locator": "invented paragraph"}
    return {"schema_version": 1,
            "sources": [{"document_id": "test.source", "version": 1, "title": "Invented fixture",
                         "source_url_or_filename": "https://example.org/test-only",
                         "retrieved_at": "2026-10-10", "source_updated_at": None, "scope": "test only",
                         "content_capture": "selected_fact_extract", "notes": "", **metadata}],
            "facts": [{"fact_id": "test.fact", "entity_id": "test.entity", "key": "name",
                       "value": "Тест", "source_refs": [copy.deepcopy(ref)], "scope": "test only",
                       "notes": "", **metadata}],
            "faqs": [{"faq_id": "test.faq", "question": "Тест үү?", "answer": "Зөвхөн тестийн хариулт.",
                      "question_aliases": ["Тест мөн үү?"], "fact_ids": ["test.fact"],
                      "source_refs": [copy.deepcopy(ref)], "scope": "test only",
                      "answer_status": "complete_in_scope", "notes": "", **metadata}]}


class DemoServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "demo" / "audio").mkdir(parents=True)
        (self.root / "demo" / "index.html").write_text("<html lang='mn'>Тест</html>", encoding="utf-8")
        (self.root / "demo" / "audio" / "q01.wav").write_bytes(b"RIFFtest-only-sample")
        (self.root / "private.txt").write_text("must not be served")
        self.db = self.root / "content.db"
        self.content = fixture()
        with ContentStore(self.db) as store:
            store.import_content(self.content, allow_draft=True)
        self.server = make_server(self.db, port=0, project_root=self.root)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def request(self, method, path, payload=None, *, raw=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=3)
        request_headers = {}
        body = raw
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        elif raw is not None:
            request_headers["Content-Type"] = "application/json"
        request_headers.update(headers or {})
        connection.request(method, path, body=body, headers=request_headers)
        response = connection.getresponse()
        encoded = response.read()
        result = json.loads(encoded) if response.getheader("Content-Type", "").startswith(
            "application/json") else encoded
        status = response.status
        connection.close()
        return status, result

    def test_status_reads_actual_counts_and_reports_historical_metrics(self):
        status, result = self.request("GET", "/api/status")
        self.assertEqual(status, 200)
        self.assertEqual(result["content"]["counts"]["faqs"], 1)
        self.assertEqual(result["content"]["approval_counts"]["sources"], {"draft": 1})
        self.assertEqual([s["available"] for s in result["audio_samples"]], [True, False, False])
        self.assertTrue(result["readonly"])
        self.assertFalse(result["microphone_connected"])
        self.assertTrue(result["stt"]["historical_development_result"])
        self.assertFalse(result["retrieval"]["human_gold_approved"])

    def test_public_manifest_fields_are_whitelisted_to_only_three_samples(self):
        manifest = {"publication_authorized_by_user": True, "samples": [
            {"filename": "q01.wav", "reference": "Нийтлэхийг зөвшөөрсөн",
             "url": "/private.txt", "private_field": "not public"},
            {"filename": "q04.wav", "reference": "not public"}]}
        (self.root / "demo" / "audio" / "samples.json").write_text(
            json.dumps(manifest), encoding="utf-8")
        _, result = self.request("GET", "/api/status")
        self.assertEqual(len(result["audio_samples"]), 3)
        sample = result["audio_samples"][0]
        self.assertEqual(sample["reference"], "Нийтлэхийг зөвшөөрсөн")
        self.assertEqual(sample["url"], "/demo/audio/q01.wav")
        self.assertNotIn("private_field", sample)

    def test_default_search_does_not_expose_draft_or_exact_answer(self):
        status, result = self.request("POST", "/api/search", {"query": "Тест үү?"})
        self.assertEqual(status, 200)
        self.assertEqual(result["candidates"][0]["faq_id"], "test.faq")
        self.assertFalse(result["candidates"][0]["eligible"])
        self.assertNotIn("answer", result)
        self.assertFalse(result["answer_served"])
        self.assertTrue(result["preview_requires_selection"])

    def test_explicit_draft_search_still_requires_selected_preview(self):
        status, result = self.request("POST", "/api/search",
                                      {"query": "Тест үү?", "allow_draft": True})
        self.assertEqual(status, 200)
        self.assertTrue(result["candidates"][0]["eligible"])
        self.assertNotIn("answer", result)
        self.assertNotIn("exact_match_preview", result)

    def test_preview_requires_explicit_draft_and_never_claims_query_support(self):
        status, blocked = self.request("POST", "/api/preview", {"faq_id": "test.faq"})
        self.assertEqual(status, 200)
        self.assertIsNone(blocked["answer"])
        status, shown = self.request("POST", "/api/preview",
                                     {"faq_id": "test.faq", "allow_draft": True})
        self.assertEqual(status, 200)
        self.assertEqual(shown["answer"], "Зөвхөн тестийн хариулт.")
        self.assertEqual(shown["approval_status"], "draft")
        self.assertFalse(shown["is_answer_to_query"])
        self.assertFalse(shown["generated"])
        self.assertEqual(shown["citations"][0]["version"], 1)

    def test_approved_unknown_validity_and_partial_are_not_served_by_default(self):
        for variant in ("unknown", "partial"):
            content = fixture("approved")
            if variant == "unknown":
                content["sources"][0]["valid_until"] = None
            else:
                content["faqs"][0]["answer_status"] = "partial_in_scope"
            with ContentStore(self.db) as store:
                store.import_content(content)
            _, blocked = self.request("POST", "/api/preview", {"faq_id": "test.faq"})
            self.assertIsNone(blocked["answer"])
            _, preview = self.request("POST", "/api/preview",
                                       {"faq_id": "test.faq", "allow_draft": True})
            self.assertEqual(preview["answer"], "Зөвхөн тестийн хариулт.")

    def test_malformed_body_and_unknown_fields_fail_closed(self):
        for payload in ([], {"query": ""}, {"query": "Тест", "allow_draft": "true"},
                        {"query": "Тест", "limit": True}, {"query": "Тест", "backend": "e5"},
                        {"faq_id": "../private.txt"}):
            path = "/api/preview" if isinstance(payload, dict) and "faq_id" in payload else "/api/search"
            self.assertEqual(self.request("POST", path, payload)[0], 400)
        self.assertEqual(self.request("POST", "/api/search", raw=b"{")[0], 400)
        self.assertEqual(self.request("POST", "/api/search", raw=b"x" * 8193)[0], 400)

    def test_private_paths_and_unlisted_audio_are_not_served(self):
        for path in ("/private.txt", "/content.db", "/demo/audio/q04.wav",
                     "/demo/audio/../../private.txt", "/demo/audio/%2e%2e/private.txt",
                     "/data/content-draft-v1.json", "/api/approve"):
            self.assertEqual(self.request("GET", path)[0], 404)
        status, sample = self.request("GET", "/demo/audio/q01.wav")
        self.assertEqual(status, 200)
        self.assertEqual(sample, b"RIFFtest-only-sample")
        self.assertEqual(self.request("GET", "/")[0], 200)

    def test_wrong_origin_host_and_non_json_requests_are_denied(self):
        self.assertEqual(self.request("POST", "/api/search", {"query": "Тест"},
                                      headers={"Origin": "https://example.org"})[0], 403)
        self.assertEqual(self.request("GET", "/api/status",
                                      headers={"Host": "attacker.example"})[0], 403)
        self.assertEqual(self.request("POST", "/api/search", raw=b"{}",
                                      headers={"Content-Type": "text/plain"})[0], 400)

    def test_requests_do_not_change_database_and_update_routes_do_not_exist(self):
        before = hashlib.sha256(self.db.read_bytes()).hexdigest()
        self.request("POST", "/api/search", {"query": "Тест", "allow_draft": True})
        self.request("POST", "/api/preview", {"faq_id": "test.faq", "allow_draft": True})
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(), before)
        self.assertEqual(self.request("POST", "/api/approve", {})[0], 404)
        self.assertEqual(self.request("PUT", "/api/preview", {})[0], 405)
        self.assertEqual(self.request("DELETE", "/api/preview")[0], 405)

    def test_missing_database_is_reported_without_creating_it(self):
        absent = self.root / "not-created.db"
        other = make_server(absent, port=0, project_root=self.root)
        other_thread = threading.Thread(target=other.serve_forever, daemon=True)
        other_thread.start()
        current = self.server
        self.server = other
        try:
            _, state = self.request("GET", "/api/status")
            self.assertFalse(state["content"]["available"])
            self.assertEqual(self.request("POST", "/api/search", {"query": "Тест"})[0], 503)
            self.assertFalse(absent.exists())
        finally:
            other.shutdown()
            other.server_close()
            other_thread.join(timeout=2)
            self.server = current


    def website_fixture(self):
        from CORE.website_corpus import PageParser, import_snapshot
        directory = self.root / "capture"
        directory.mkdir()
        html = "<main><h1>Тестийн эх</h1><p>Тестийн ажлын цаг 09:00</p></main>".encode("utf-8")
        parser = PageParser()
        parser.feed(html.decode("utf-8"))
        extracted = parser.result()["text"]
        (directory / "page.html").write_bytes(html)
        (directory / "page.txt").write_text(extracted, encoding="utf-8", newline="")
        manifest = {"run_id": "test-only", "retrieved_at": "2026-10-10", "inventory": [], "pages": [
            {"url": "https://nmct.edu.mn/contact", "status": "ok", "html_file": "page.html",
             "text_file": "page.txt", "html_sha256": hashlib.sha256(html).hexdigest(),
             "text_sha256": hashlib.sha256(extracted.encode("utf-8")).hexdigest(),
             "retrieved_at": "2026-10-10", "http": {"charset": "utf-8"}}]}
        (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        database = self.root / "CORE/database/website.db"
        import_snapshot(database, directory)
        return database

    def test_website_status_search_draft_guard_and_readonly_source(self):
        database = self.website_fixture()
        before = hashlib.sha256(database.read_bytes()).hexdigest()
        _, status = self.request("GET", "/api/status")
        self.assertEqual(status["website"]["pages"], 1)
        self.assertEqual(status["website"]["approved_pages"], 0)
        for draft in (False, True):
            code, result = self.request("POST", "/api/website-search",
                                        {"query": "ажлын цаг", "allow_draft": draft})
            self.assertEqual(code, 200)
            self.assertIsNone(result["answer"])
            self.assertEqual(result["llm_calls"], 0)
            match = result["matches"][0]
            self.assertEqual(match["url"], "https://nmct.edu.mn/contact")
            self.assertEqual(match["approval_status"], "draft")
            self.assertTrue(match["validity_unknown"])
            if draft:
                self.assertIn("09:00", match["excerpt"])
            else:
                self.assertIsNone(match["excerpt"])
        self.assertEqual(hashlib.sha256(database.read_bytes()).hexdigest(), before)
        self.assertEqual(self.request("GET", "/CORE/database/website.db")[0], 404)

    def test_missing_website_database_never_created_by_http(self):
        database = self.root / "CORE/database/website.db"
        _, status = self.request("GET", "/api/status")
        self.assertFalse(status["website"]["available"])
        self.assertEqual(self.request("POST", "/api/website-search", {"query": "ажлын цаг"})[0], 503)
        self.assertFalse(database.exists())

    def test_website_search_validates_origin_and_payload_before_reading(self):
        self.assertEqual(self.request("POST", "/api/website-search", {"query": "ажлын цаг"},
                                     headers={"Origin": "https://outside.example"})[0], 403)
        for payload in ({"query": ""}, {"query": "test", "allow_draft": "yes"},
                        {"query": "test", "limit": 6}, {"query": "test", "db": "private"}):
            self.assertEqual(self.request("POST", "/api/website-search", payload)[0], 400)


    def test_route_http_default_requires_approval_explicit_draft_only_previews(self):
        before = hashlib.sha256(self.db.read_bytes()).hexdigest()
        status, blocked = self.request("POST", "/api/route", {"query": "Тест үү?"})
        self.assertEqual(status, 200)
        self.assertEqual(blocked["route"], "E")
        self.assertIsNone(blocked["answer"])
        self.assertIn("approval_required", blocked["reason_codes"])
        status, shown = self.request("POST", "/api/route", {"query": "Тест үү?", "allow_draft": True})
        self.assertEqual(status, 200)
        self.assertEqual(shown["route"], "B")
        self.assertEqual(shown["answer"], "Зөвхөн тестийн хариулт.")
        self.assertEqual(shown["answer_kind"], "development_draft_preview")
        self.assertFalse(shown["generated"])
        self.assertFalse(shown["human_gold"])
        self.assertFalse(shown["c_enabled"])
        self.assertEqual(shown["llm_calls"], 0)
        self.assertTrue(shown["citations"])
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(), before)

    def test_route_http_unrelated_query_never_answers_or_calls_llm(self):
        status, result = self.request("POST", "/api/route", {"query": "Паспорт сунгах журам", "allow_draft": True})
        self.assertEqual(status, 200)
        self.assertEqual(result["route"], "E")
        self.assertIsNone(result["answer"])
        self.assertEqual(result["llm_calls"], 0)

    def test_route_http_rejects_origin_and_control_fields(self):
        self.assertEqual(self.request("POST", "/api/route", {"query": "Тест үү?"},
                                     headers={"Origin": "https://outside.example"})[0], 403)
        for payload in ({"query": ""}, {"query": "Тест", "allow_draft": "yes"},
                        {"query": "Тест", "as_of": "2000-01-01"}, {"query": "Тест", "limit": 3},
                        {"query": "Тест", "package_id": "private"}):
            self.assertEqual(self.request("POST", "/api/route", payload)[0], 400)


if __name__ == "__main__":
    unittest.main()
