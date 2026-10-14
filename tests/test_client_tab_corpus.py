from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from CORE.client_tab_corpus import METHOD, build_extraction, captured_fields, flight_records, import_excerpts, prepare_bundle, read_client_tab_rows
from CORE.website_corpus import PageParser, import_snapshot, readonly


def captured_html(goals=None, achievements=None, text_record=False, visible='Тэнхимийн танилцуулга.'):
    goals = goals or {'goal': 'Мэдлэг чадвартай инженер бэлтгэх зорилго.',
                      'objectives': ['CAD программ ашиглан инженерийн зураг төсөл боловсруулна.']}
    achievements = achievements or '<p>2025 онд Дизакон тэмцээнд 5-р байр эзэлсэн.</p>'
    props = dict(goalsJson=json.dumps(goals, ensure_ascii=False), achievementsJson=achievements)
    stream = ''
    if text_record:
        stream = 'a:T' + format(len(achievements.encode('utf-8')), 'x') + ',' + achievements
        props['achievementsJson'] = '$a'
    stream += 'b:' + json.dumps(['$', '$L2', None, props], ensure_ascii=False) + '\n'
    push = 'self.__next_f.push(' + json.dumps([1, stream], ensure_ascii=False) + ')'
    return ('<main><h1>Барилгын тэнхим</h1><p>' + visible + '</p></main><script>' + push + '</script>').encode('utf-8')


class FlightExtractionTests(unittest.TestCase):
    def test_utf8_byte_length_text_record_with_adjacent_json(self):
        body = captured_html(text_record=True)
        fields = captured_fields(body.decode())
        achievement = next(f for f in fields if f['field'] == 'achievementsJson')
        self.assertEqual(achievement['reference'], 'a')
        self.assertIn('2025', achievement['raw'])
        self.assertIn('JSON /3/achievementsJson -> text record a',
            build_extraction(body, url='https://nmct.edu.mn/departments/civil', title='Барилгын тэнхим')['passages'][0]['locator'])

    def test_json_only_decode_does_not_execute_script(self):
        html = '<script>self.__next_f.push((function(){ throw "execute" })())</script>'
        with self.assertRaises(ValueError):
            flight_records(html)

    def test_segmented_pushes_and_truncated_utf8_record(self):
        html = '<script>self.__next_f.push([1,"a:T4,"])</script><script>self.__next_f.push([1,"АБb:{}\\n"])</script>'
        self.assertEqual(flight_records(html)['a'], 'АБ')
        with self.assertRaises(ValueError):
            flight_records('<script>self.__next_f.push([1,"a:T9,abc"])</script>')

    def test_unresolved_references_and_ambiguous_props_fail_closed(self):
        for stream in ('a:{"goalsJson":"$f"}\n',
                       'a:{"goalsJson":"one"}\nb:{"goalsJson":"two"}\n'):
            html = '<script>self.__next_f.push(' + json.dumps([1, stream]) + ')</script>'
            with self.assertRaises(ValueError):
                captured_fields(html)

    def test_placeholders_and_undated_statistics_are_inventoried_not_evidence(self):
        body = captured_html(goals={'goal': 'үндсэн зорилго', 'objectives': ['зорилт 1', 'зорилт 2']},
                             achievements='<p>123 - төгсөгч</p><p>300 - суралцагч</p>')
        doc = build_extraction(body, url='https://nmct.edu.mn/departments/electrical', title='Тэнхим')
        self.assertFalse(doc['passages'])
        self.assertEqual({p['reason'] for p in doc['omissions']}, {'empty_or_placeholder', 'undated_achievement_or_statistics'})

    def test_visible_duplicates_are_omitted_and_offsets_are_exact(self):
        goal = 'Мэдлэг чадвартай инженер бэлтгэх зорилго.'
        lines = [f'Монгол хэл инженер технологийн тэмцээний амжилт {index}.' for index in range(70)]
        achievement = '<p>2024 он</p>' + ''.join('<p>' + line + '</p>' for line in lines)
        body = captured_html(visible=goal, achievements=achievement)
        doc = build_extraction(body, url='https://nmct.edu.mn/departments/civil', title='Тэнхим')
        self.assertTrue(any(p['reason'] == 'already_in_visible_main' for p in doc['omissions']))
        text = '2024 он\n' + '\n'.join(lines)
        for passage in doc['passages']:
            if passage['field'] == 'achievementsJson':
                self.assertEqual(passage['text'], text[passage['start_offset']:passage['end_offset']])


class ClientTabImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.snapshot = self.root/'snapshot'
        self.snapshot.mkdir()
        self.database = self.root/'website.db'
        self.body = captured_html(text_record=True)
        self.url = 'https://nmct.edu.mn/departments/civil'
        self.parser = PageParser()
        self.parser.feed(self.body.decode())
        extracted = self.parser.result()
        (self.snapshot/'page.html').write_bytes(self.body)
        (self.snapshot/'page.txt').write_text(extracted['text'], encoding='utf-8', newline='')
        self.manifest = dict(run_id='run1', retrieved_at='2026-10-15T01:00:00+00:00', inventory=[], pages=[dict(
            url=self.url, status='ok', html_file='page.html', text_file='page.txt',
            html_sha256=hashlib.sha256(self.body).hexdigest(), text_sha256=hashlib.sha256(extracted['text'].encode()).hexdigest(),
            retrieved_at='2026-10-15T01:00:00+00:00', http={'charset':'utf-8', 'last_modified':None})])
        (self.snapshot/'manifest.json').write_text(json.dumps(self.manifest), encoding='utf-8')
        import_snapshot(self.database, self.snapshot)
        self.doc = build_extraction(self.body, url=self.url, title=extracted['title'])
        self.bundle = self.root/'tabs.json'
        self.write()

    def tearDown(self):
        self.temp.cleanup()

    def write(self):
        self.bundle.write_text(json.dumps(dict(schema_version=1, method=METHOD, run_id='run1', pages=[self.doc]), ensure_ascii=False), encoding='utf-8')

    def rows(self):
        with closing(readonly(self.database)) as db:
            return read_client_tab_rows(db, db.execute('SELECT * FROM crawl_runs').fetchone())

    def test_idempotent_and_provenance_source_date_and_readonly_rows(self):
        self.assertEqual(import_excerpts(self.database, self.bundle)['added_pages'], 1)
        self.assertEqual(import_excerpts(self.database, self.bundle)['added_pages'], 0)
        before = self.database.read_bytes()
        rows, warnings = self.rows()
        self.assertFalse(warnings)
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(r['source_id'].startswith('tab-') for r in rows))
        self.assertEqual(rows[0]['retrieved_at'], '2026-10-15T01:00:00+00:00')
        self.assertEqual(rows[0]['html_sha256'], self.doc['html_sha256'])
        self.assertEqual(rows[0]['reviewer_kind'], 'deterministic_parser')
        self.assertEqual(before, self.database.read_bytes())

    def test_fabricated_text_locator_title_and_hash_rejected_before_migration(self):
        original = json.loads(json.dumps(self.doc))
        for change in ('text', 'locator', 'title', 'html_sha256', 'page_version'):
            self.doc = json.loads(json.dumps(original))
            if change in ('text', 'locator'):
                self.doc['passages'][0][change] = 'invented content'
            elif change == 'page_version':
                self.doc[change] = 99
            else:
                self.doc[change] = 'invented'
            self.write()
            with self.assertRaises(ValueError):
                import_excerpts(self.database, self.bundle)
        with closing(sqlite3.connect(self.database)) as db:
            self.assertFalse(db.execute("SELECT 1 FROM sqlite_master WHERE name='client_tab_extractions'").fetchone())

    def test_new_extraction_version_retains_old_and_latest_is_read(self):
        import_excerpts(self.database, self.bundle)
        self.doc['version'] = 2
        self.write()
        import_excerpts(self.database, self.bundle)
        rows, warnings = self.rows()
        self.assertFalse(warnings)
        self.assertTrue(all(r['extraction_version'] == 2 for r in rows))
        with closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM client_tab_extractions').fetchone()[0], 2)

    def test_changed_html_or_payload_is_excluded(self):
        import_excerpts(self.database, self.bundle)
        (self.snapshot/'page.html').write_bytes(self.body+b'changed')
        rows, warnings = self.rows()
        self.assertFalse(rows)
        self.assertTrue(warnings)
        (self.snapshot/'page.html').write_bytes(self.body)
        with closing(sqlite3.connect(self.database)) as db:
            db.execute("UPDATE client_tab_extractions SET payload_sha256=?", ('0'*64,))
            db.commit()
        self.assertFalse(self.rows()[0])

    def test_missing_original_unknown_run_and_duplicate_bundle_fail(self):
        (self.snapshot/'page.html').unlink()
        with self.assertRaises(OSError):
            import_excerpts(self.database, self.bundle)
        (self.snapshot/'page.html').write_bytes(self.body)
        obj = json.loads(self.bundle.read_text(encoding='utf-8'))
        obj['pages'].append(self.doc)
        self.bundle.write_text(json.dumps(obj), encoding='utf-8')
        with self.assertRaises(ValueError):
            import_excerpts(self.database, self.bundle)
        obj['pages'] = [self.doc]
        obj['run_id'] = 'notcaptured'
        self.bundle.write_text(json.dumps(obj), encoding='utf-8')
        with self.assertRaises(ValueError):
            import_excerpts(self.database, self.bundle)

    def test_legacy_database_without_table_returns_empty(self):
        self.assertEqual(self.rows(), ([], []))

    def test_prepare_is_readonly_reuses_page_version_and_rejects_capture_tampering(self):
        before = self.database.read_bytes()
        bundle = prepare_bundle(self.database, self.snapshot)
        self.assertEqual(bundle['pages'], [self.doc])
        self.assertEqual(self.database.read_bytes(), before)
        (self.snapshot/'page.html').write_bytes(self.body+b'changed')
        with self.assertRaises(ValueError):
            prepare_bundle(self.database, self.snapshot)


if __name__ == '__main__':
    unittest.main()
