from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from mongolian_morphology import conflate, light_stem, morph_terms
from website_retrieval import load_morphology
from CORE.website_corpus import known_urls


class LightStemTests(unittest.TestCase):
    def test_case_and_reflexive_forms_meet(self):
        for forms in (('эрхийг', 'эрхээ', 'эрх'), ('талбайд', 'талбай'), ('танхимд', 'танхим'),
                      ('байрладаг', 'байрлах'), ('хэлэлцдэг', 'хэлэлцсэн'), ('ажлаа', 'ажлаар'),
                      ('төгсөхөд', 'төгсөх'), ('багшийн', 'багш')):
            with self.subTest(forms=forms):
                self.assertEqual(len({light_stem(word) for word in forms}), 1)

    def test_short_roots_and_other_scripts_are_kept(self):
        self.assertEqual(light_stem('өрөө'), 'өрөө')
        self.assertEqual(light_stem('эрх'), 'эрх')
        self.assertEqual(light_stem('koha'), 'koha')
        self.assertEqual(light_stem('2016'), '2016')

    def test_converb_needs_a_longer_stem(self):
        self.assertNotEqual(light_stem('хүүхэд'), 'хүү')

    def test_prefix_methods(self):
        self.assertEqual(conflate('инженерийн', 'prefix5'), 'инжен')
        self.assertEqual(conflate('эрхийг', 'light+prefix5'), 'эрх')
        with self.assertRaises(ValueError):
            conflate('эрх', 'stem')

    def test_morph_terms_skip_stopwords(self):
        self.assertEqual(morph_terms('Эрхээ хаана авах вэ', 'light', {'хаана', 'вэ'}), ['эрх', 'ава'])


class ConfigTests(unittest.TestCase):
    def test_channel_is_off_unless_enabled(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / 'config').mkdir()
            path = Path(root) / 'config/retrieval-morphology.json'
            self.assertIsNone(load_morphology(root))
            path.write_text(json.dumps({'enabled': False, 'method': 'light'}), encoding='utf-8')
            self.assertIsNone(load_morphology(root))
            path.write_text(json.dumps({'enabled': True, 'method': 'prefix5', 'weight': 0.5}), encoding='utf-8')
            self.assertEqual(load_morphology(root), ('prefix5', 0.5))


class RevisitTests(unittest.TestCase):
    def test_known_urls_are_official_captured_pages(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / 'web.db'
            with closing(sqlite3.connect(database)) as db, db:
                db.execute('CREATE TABLE corpus_meta (schema_version INTEGER)')
                db.execute('INSERT INTO corpus_meta VALUES (1)')
                db.execute('CREATE TABLE captures (run_id TEXT, url TEXT, version INTEGER)')
                db.executemany('INSERT INTO captures VALUES (?,?,1)', [
                    ('a', 'https://nmct.edu.mn/about/environment'), ('b', 'https://nmct.edu.mn/about/environment'),
                    ('a', 'https://example.com/page')])
            self.assertEqual(known_urls(database), ['https://nmct.edu.mn/about/environment'])
            self.assertEqual(known_urls(Path(folder) / 'missing.db'), [])


if __name__ == '__main__':
    unittest.main()
