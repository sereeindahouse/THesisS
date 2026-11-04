"""Frozen, local-only retrieval for the STT text-normalization experiment.

The caller owns the socket/file-access guard and private output directory. This
module never prints queries or evidence, never uses a speech provider, and never
writes an embedding cache. Production ranking and its lexical gates are reused.
"""
from __future__ import annotations

from contextlib import closing, contextmanager
from copy import deepcopy
from datetime import date
import hashlib
from pathlib import Path
import sqlite3
import time
from unittest.mock import patch

from score import normalize
import website_retrieval as production


class RetrievalError(RuntimeError):
    """A bounded error code, without query/reference/evidence contents."""


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def snapshot_database(source, destination, *, timeout_seconds=30):
    """Create one consistent SQLite backup from a read-only source connection.

    An existing destination is never replaced. Committed WAL data is included
    by SQLite's backup API instead of copying a potentially inconsistent file.
    Only the newly allocated destination is cleaned up if the backup fails.
    """
    source, destination = Path(source).resolve(strict=True), Path(destination).resolve()
    if not source.is_file() or source == destination:
        raise RetrievalError('invalid_snapshot_paths')
    if not isinstance(timeout_seconds, (int, float)) or not 0 < timeout_seconds <= 300:
        raise RetrievalError('invalid_snapshot_timeout')
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive allocation protects a concurrent writer's file as well.
    with destination.open('xb'):
        pass
    deadline = time.monotonic() + timeout_seconds

    def progress(_status, _remaining, _total):
        if time.monotonic() > deadline:
            raise RetrievalError('snapshot_timeout')

    try:
        with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True, timeout=5)) as original:
            original.execute('PRAGMA query_only=ON')
            with closing(sqlite3.connect(destination.as_uri() + '?mode=rw', uri=True)) as frozen:
                original.backup(frozen, pages=256, progress=progress, sleep=.01)
                check = frozen.execute('PRAGMA quick_check').fetchone()
                if check is None or check[0] != 'ok':
                    raise RetrievalError('snapshot_integrity_failed')
        return dict(database_sha256=_sha(destination), database_bytes=destination.stat().st_size,
                    snapshot_method='sqlite_readonly_backup', original_open_mode='ro')
    except Exception:
        # This exact file was exclusively created above; never remove a source.
        destination.unlink(missing_ok=True)
        raise RetrievalError('snapshot_failed') from None


class _MemoryRetriever(production.WebsiteRetriever):
    def _dense(self, query):
        # If refresh invalidates the pinned matrix, fail before production can
        # enter its on-disk cache branch. The normal dense scoring is unchanged.
        if self._embeddings is None:
            raise RetrievalError('frozen_embeddings_missing')
        return super()._dense(query)


class FrozenRetrieval:
    """One frozen production-ranking backend, with embeddings kept in memory.

    ``corpus_rows()`` is usable before ``warm()`` to build a reference rubric
    without inspecting raw/normalized query rankings. ``_retriever`` exists only
    for FAKE dependency injection in unit tests.
    """
    def __init__(self, root, database, *, as_of='2026-11-04', use_dense=True, _retriever=None):
        self.root, self.database = Path(root).resolve(), Path(database).resolve(strict=True)
        if type(use_dense) is not bool:
            raise RetrievalError('invalid_dense_option')
        try:
            self.as_of = date.fromisoformat(as_of)
            if self.as_of.isoformat() != as_of:
                raise ValueError()
        except (TypeError, ValueError):
            raise RetrievalError('invalid_retrieval_date') from None
        frozen = self.as_of

        class FrozenDate(date):
            @classmethod
            def today(cls):
                return frozen

        self._date = FrozenDate
        self.use_dense, self._closed, self._warm = use_dense, False, False
        self._backend = 'bm25+e5_rrf' if use_dense else 'bm25_mongolian'
        self._retriever = _retriever if _retriever is not None else _MemoryRetriever(
            root=self.root, database=self.database, use_dense=use_dense)
        self._stamp = self._database_stamp()
        with self._scope():
            self._retriever._refresh()
        self._corpus_id = self._retriever._corpus_id
        self._source_ids = tuple(row['source_id'] for row in self._retriever._rows)
        if not self._corpus_id or not self._source_ids:
            raise RetrievalError('frozen_corpus_unavailable')

    @contextmanager
    def _scope(self):
        if self._closed:
            raise RetrievalError('retrieval_closed')
        with patch.object(production, 'date', self._date):
            yield

    def _database_stamp(self):
        stat = self.database.stat()
        # Frozen snapshots must not acquire a WAL, which would bypass the
        # production refresh fast path and invalidate pinned embeddings.
        if self.database.with_name(self.database.name + '-wal').exists():
            raise RetrievalError('frozen_database_has_wal')
        return stat.st_mtime_ns, stat.st_size

    def _check_stable(self):
        if self._database_stamp() != self._stamp:
            raise RetrievalError('frozen_database_changed')
        if (self._retriever._corpus_id != self._corpus_id or
                tuple(row['source_id'] for row in self._retriever._rows) != self._source_ids):
            raise RetrievalError('frozen_corpus_changed')

    def corpus_rows(self):
        with self._scope():
            self._check_stable()
            return deepcopy(self._retriever._rows)

    def warm(self):
        with self._scope():
            self._check_stable()
            if self._warm:
                return self.status()
            if self.use_dense:
                try:
                    import numpy as np
                    encoder = self._retriever._encoder
                    encoder.load()
                    embeddings = np.asarray(encoder.encode(self._retriever._passages, 'passage: '))
                    dimension = getattr(encoder, 'dimension', 384)
                    if (embeddings.shape != (len(self._source_ids), dimension) or
                            not np.isfinite(embeddings).all() or not encoder.revision):
                        raise ValueError()
                    embeddings.setflags(write=False)
                    self._retriever._embeddings = embeddings
                    self._retriever._dense_status = 'ready'
                except (ImportError, OSError, ValueError, RuntimeError, KeyError, AttributeError):
                    raise RetrievalError('pinned_local_e5_unavailable') from None
            self._warm = True
            return self.status()

    def search(self, text, limit=3):
        if (not isinstance(text, str) or not text.strip() or len(text) > 1000 or
                type(limit) is not int or not 1 <= limit <= 10):
            raise RetrievalError('invalid_retrieval_query')
        self.warm()
        with self._scope():
            self._check_stable()
            try:
                result = self._retriever.search(text, limit=limit, mode='production')
            except (OSError, ValueError, RuntimeError, KeyError, sqlite3.Error):
                raise RetrievalError('production_retrieval_failed') from None
            self._check_stable()
            if (result.get('corpus_id') != self._corpus_id or result.get('backend') != self._backend or
                    result.get('ranking_mode') != 'production'):
                raise RetrievalError('retrieval_backend_or_corpus_changed')
            return result

    def status(self):
        with self._scope():
            self._check_stable()
            return dict(as_of=self.as_of.isoformat(), corpus_id=self._corpus_id,
                        source_count=len(self._source_ids), backend=self._backend if self._warm else None,
                        dense_status=getattr(self._retriever, '_dense_status', None),
                        e5_revision=getattr(self._retriever._encoder, 'revision', None) if self.use_dense else None,
                        embedding_storage='memory_only', database_modified=False, warmed=self._warm)

    def close(self):
        self._closed = True
        self._retriever._embeddings = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def _phrase_present(phrase, text):
    needle, haystack = normalize(phrase).split(), normalize(text).split()
    return bool(needle) and any(haystack[start:start + len(needle)] == needle
                               for start in range(len(haystack) - len(needle) + 1))


def support_rank(supports, candidates):
    """Return 1-based first support rank, requiring URL/version AND evidence.

    A support is ``{url, version, phrase[, source_id]}``. These reference values
    belong in private runtime files. A page URL or matching name alone is never
    sufficient. Unknown/malformed candidate rows cannot become successful hits.
    """
    if not isinstance(supports, list) or not isinstance(candidates, list):
        raise RetrievalError('invalid_support_collection')
    for support in supports:
        if (not isinstance(support, dict) or not isinstance(support.get('url'), str) or
                not support['url'].strip() or type(support.get('version')) not in (str, int) or
                not str(support['version']).strip() or not isinstance(support.get('phrase'), str) or
                not normalize(support['phrase']) or ('source_id' in support and
                (not isinstance(support['source_id'], str) or not support['source_id'].strip()))):
            raise RetrievalError('invalid_support_reference')
    for rank, candidate in enumerate(candidates, 1):
        if not isinstance(candidate, dict) or not isinstance(candidate.get('text'), str):
            continue
        for support in supports:
            if (candidate.get('url') == support['url'] and candidate.get('version') == support['version']
                    and ('source_id' not in support or candidate.get('source_id') == support['source_id'])
                    and _phrase_present(support['phrase'], candidate['text'])):
                return rank
    return None
