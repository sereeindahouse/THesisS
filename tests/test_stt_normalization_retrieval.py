"""FAKE-only corpus fixtures; no real recordings, transcript or model access."""
from copy import deepcopy
from contextlib import closing
from datetime import date
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest

import numpy as np

import website_retrieval as production
from tools.stt_normalization_retrieval import (FrozenRetrieval, RetrievalError,
                                             _MemoryRetriever, snapshot_database, support_rank)


class FakeEncoder:
    dimension, revision = 2, 'fake-revision'
    def load(self):
        pass
    def encode(self, texts, prefix):
        if prefix != 'passage: ':
            raise AssertionError('warm must encode only fake passages')
        return np.ones((len(texts), 2), dtype=float)


class FakeRetriever:
    def __init__(self):
        self._rows = [dict(source_id='fake-1', url='https://example.invalid/fake',
                           version=1, text='ЗОХИОМОЛ лаборатори нэгдүгээр давхарт.')]
        self._passages = [self._rows[0]['text']]
        self._encoder, self._embeddings = FakeEncoder(), None
        self._corpus_id, self._dense_status = 'fake-corpus', 'not_loaded'
        self.backend, self.ranking_mode = 'bm25+e5_rrf', 'production'
        self.calls, self.seen_dates = [], []
    def _refresh(self):
        self.seen_dates.append(production.date.today())
    def search(self, text, *, limit, mode):
        self._refresh()
        self.calls.append((text, limit, mode))
        return dict(query=text, candidates=deepcopy(self._rows[:limit]), corpus_id=self._corpus_id,
                    backend=self.backend, ranking_mode=self.ranking_mode)


class FrozenRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = self.root / 'fake.db'
        self.database.write_bytes(b'FAKE database stamp only; fake retriever never opens it')
        self.fake = FakeRetriever()
        self.retrieval = FrozenRetrieval(self.root, self.database, _retriever=self.fake)
        self.addCleanup(self.retrieval.close)

    def test_corpus_can_be_reviewed_before_any_ranking_or_embedding(self):
        rows = self.retrieval.corpus_rows()
        rows[0]['text'] = 'FAKE changed by caller'
        self.assertFalse(self.fake.calls)
        self.assertIsNone(self.fake._embeddings)
        self.assertNotEqual(rows[0]['text'], self.fake._rows[0]['text'])

    def test_warm_is_memory_only_and_idempotent(self):
        before = set(self.root.iterdir())
        self.assertEqual(self.retrieval.warm()['backend'], 'bm25+e5_rrf')
        first = self.fake._embeddings
        self.retrieval.warm()
        self.assertIs(first, self.fake._embeddings)
        self.assertFalse(first.flags.writeable)
        self.assertEqual(before, set(self.root.iterdir()))

    def test_search_uses_production_for_both_fake_text_variants(self):
        self.retrieval.search('ЗОХИОМОЛ лаборатоори')
        self.retrieval.search('ЗОХИОМОЛ лаборатори')
        self.assertEqual([call[2] for call in self.fake.calls], ['production', 'production'])
        self.assertEqual([call[1] for call in self.fake.calls], [3, 3])

    def test_date_is_fixed_and_module_restored(self):
        original_date = production.date
        self.retrieval.search('ЗОХИОМОЛ лаборатори')
        self.assertEqual(set(self.fake.seen_dates), {date(2026, 11, 4)})
        self.assertIs(production.date, original_date)

    def test_backend_fallback_is_rejected(self):
        self.fake.backend = 'bm25_mongolian'
        with self.assertRaisesRegex(RetrievalError, '^retrieval_backend_or_corpus_changed$'):
            self.retrieval.search('ЗОХИОМОЛ лаборатори')

    def test_wrong_mode_is_rejected(self):
        self.fake.ranking_mode = 'bm25'
        with self.assertRaises(RetrievalError):
            self.retrieval.search('ЗОХИОМОЛ лаборатори')

    def test_corpus_drift_is_rejected(self):
        self.fake._corpus_id = 'different-fake-corpus'
        with self.assertRaisesRegex(RetrievalError, '^frozen_corpus_changed$'):
            self.retrieval.search('ЗОХИОМОЛ лаборатори')

    def test_database_drift_is_rejected(self):
        self.database.write_bytes(b'FAKE changed database')
        with self.assertRaisesRegex(RetrievalError, '^frozen_database_changed$'):
            self.retrieval.search('ЗОХИОМОЛ лаборатори')

    def test_wal_is_not_silently_ignored(self):
        self.database.with_name('fake.db-wal').write_bytes(b'FAKE WAL')
        with self.assertRaisesRegex(RetrievalError, '^frozen_database_has_wal$'):
            self.retrieval.corpus_rows()

    def test_missing_encoder_does_not_become_bm25_success(self):
        self.fake._encoder.revision = None
        with self.assertRaisesRegex(RetrievalError, '^pinned_local_e5_unavailable$'):
            self.retrieval.warm()

    def test_bad_embeddings_are_rejected(self):
        self.fake._encoder.encode = lambda _texts, _prefix: np.array([[np.nan, 1]])
        with self.assertRaises(RetrievalError):
            self.retrieval.warm()

    def test_explicit_lexical_mode_is_labelled_honestly(self):
        fake = FakeRetriever()
        fake.backend = 'bm25_mongolian'
        lexical = FrozenRetrieval(self.root, self.database, use_dense=False, _retriever=fake)
        self.addCleanup(lexical.close)
        result = lexical.search('ЗОХИОМОЛ лаборатори')
        self.assertEqual(result['backend'], 'bm25_mongolian')
        self.assertIsNone(fake._embeddings)

    def test_close_prevents_reuse(self):
        self.retrieval.close()
        with self.assertRaisesRegex(RetrievalError, '^retrieval_closed$'):
            self.retrieval.search('ЗОХИОМОЛ лаборатори')

    def test_invalid_inputs_do_not_echo_private_fake_text(self):
        private_fake = 'FAKE secret text' * 100
        with self.assertRaises(RetrievalError) as error:
            self.retrieval.search(private_fake)
        self.assertNotIn(private_fake, str(error.exception))

    def test_missing_memory_matrix_cannot_enter_disk_cache_branch(self):
        bare = object.__new__(_MemoryRetriever)
        bare._embeddings = None
        with self.assertRaisesRegex(RetrievalError, '^frozen_embeddings_missing$'):
            bare._dense('ЗОХИОМОЛ')


class SupportRankTests(unittest.TestCase):
    def setUp(self):
        self.support = dict(url='https://example.invalid/fake', version=1,
                            phrase='лаборатори нэгдүгээр давхарт')
        self.candidate = dict(url=self.support['url'], version=1, source_id='fake-1',
                              text='ЗОХИОМОЛ: лаборатори нэгдүгээр давхарт.')

    def test_support_requires_version_url_and_whole_phrase(self):
        self.assertEqual(support_rank([self.support], [self.candidate]), 1)
        for changed in (dict(version=2), dict(url='https://example.invalid/other'),
                        dict(text='ЗОХИОМОЛ лабораторид нэгдүгээр давхарт')):
            with self.subTest(changed=list(changed)):
                candidate = dict(self.candidate, **changed)
                self.assertIsNone(support_rank([self.support], [candidate]))

    def test_url_membership_alone_is_not_support(self):
        self.assertIsNone(support_rank([self.support], [dict(self.candidate, text='ЗОХИОМОЛ өөр сэдэв')]))

    def test_top_three_rank_is_one_based(self):
        wrong = dict(self.candidate, text='ЗОХИОМОЛ буруу')
        self.assertEqual(support_rank([self.support], [wrong, wrong, self.candidate]), 3)
        self.assertIsNone(support_rank([self.support], [wrong] * 3))

    def test_optional_source_identity_is_also_required(self):
        support = dict(self.support, source_id='fake-1')
        self.assertEqual(support_rank([support], [self.candidate]), 1)
        self.assertIsNone(support_rank([support], [dict(self.candidate, source_id='fake-2')]))

    def test_empty_or_malformed_references_are_rejected(self):
        for item in (dict(self.support, phrase='?!'), dict(self.support, version=None),
                     dict(self.support, version=True), dict(self.support, source_id=''),
                     {'url': self.support['url']}):
            with self.subTest(keys=list(item)):
                with self.assertRaisesRegex(RetrievalError, '^invalid_support_reference$'):
                    support_rank([item], [self.candidate])


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source, self.target = self.root / 'fake-source.db', self.root / 'fake-frozen.db'
        with closing(sqlite3.connect(self.source)) as connection, connection:
            connection.execute('CREATE TABLE fake_only (value TEXT)')
            connection.execute('INSERT INTO fake_only VALUES (?)', ('FAKE data only',))

    def test_backup_copies_fake_data_and_preserves_original(self):
        original = self.source.read_bytes()
        metadata = snapshot_database(self.source, self.target)
        with closing(sqlite3.connect(self.target)) as connection, connection:
            self.assertEqual(connection.execute('SELECT value FROM fake_only').fetchone()[0], 'FAKE data only')
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(metadata['database_sha256'], hashlib.sha256(self.target.read_bytes()).hexdigest())
        self.assertEqual(metadata['original_open_mode'], 'ro')

    def test_existing_destination_is_never_replaced(self):
        self.target.write_bytes(b'FAKE existing output')
        with self.assertRaises(FileExistsError):
            snapshot_database(self.source, self.target)
        self.assertEqual(self.target.read_bytes(), b'FAKE existing output')

    def test_source_cannot_be_destination(self):
        before = self.source.read_bytes()
        with self.assertRaisesRegex(RetrievalError, '^invalid_snapshot_paths$'):
            snapshot_database(self.source, self.source)
        self.assertEqual(self.source.read_bytes(), before)

    def test_committed_wal_is_included_without_checkpointing_source(self):
        with closing(sqlite3.connect(self.source)) as connection, connection:
            connection.execute('PRAGMA journal_mode=WAL')
            connection.execute('INSERT INTO fake_only VALUES (?)', ('FAKE WAL row',))
            connection.commit()
            wal = self.source.with_name(self.source.name + '-wal')
            original, original_wal = self.source.read_bytes(), wal.read_bytes()
            snapshot_database(self.source, self.target)
            self.assertEqual(self.source.read_bytes(), original)
            self.assertEqual(wal.read_bytes(), original_wal)
            with closing(sqlite3.connect(self.target)) as frozen, frozen:
                self.assertEqual(frozen.execute('SELECT count(*) FROM fake_only').fetchone()[0], 2)


if __name__ == '__main__':
    unittest.main()
