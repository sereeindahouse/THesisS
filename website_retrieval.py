"""Local source retrieval for NMCT RAG; rankings are not answer verification.

Uses the most recent website snapshot read-only. Optional multilingual E5 is
loaded once from checksum-pinned local assets, never downloaded or trained.
Mongolian search aliases affect ranking only; returned evidence remains exact
source text with offsets, snapshot dates and stable source identifiers.
"""
from collections import Counter
from contextlib import closing
from datetime import date
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import threading
import time
import unicodedata
from urllib.parse import urlsplit

from CORE.website_corpus import readonly
from CORE.document_corpus import read_document_rows
from CORE.client_tab_corpus import read_client_tab_rows
from retrieval_probe import bm25_scores, sha256

ROOT = Path(__file__).resolve().parent
INDEX_VERSION = 'website-hybrid-v5-complete-physical-boundaries'
SOURCE_BOUNDARY_CONTEXT = 900
# Ranking experiments share the production corpus/preprocessing/diversity policy.
# Only production applies lexical/topic abstention gates; other modes rank only.
RANKING_MODES = ('bm25', 'e5', 'rrf', 'rrf_boosted', 'production')
RRF_K = 30
ANCHOR_COVERAGE_WEIGHT = .035
CATEGORY_WEIGHT = .09
STOPWORDS = set('би миний бид манай танай та надад талаар талаарх тухай юу вэ бэ уу үү юм байна байдаг болох бол ямар хэд хэрхэн яаж хаана хэзээ нь ын ийн ы ий н р болон буюу эсвэл бас мөн энэ тэр тэгээд гэж гэсэн сайн уу мэдээлэл авах өгөөч тайлбарла тайлбарлаж болно болох уу'.split())
STOPWORDS.update('боломж боломжтой бий дээр доор хэдэн бүх одоо оны онд жил жилийн сонирхож мэдэх мэдмээр хүсэж суралц суралцах'.split())
# Transparent domain search aliases, not a Mongolian morphological model.
STEMS = {
    'компьютер': 'компьютер', 'computer': 'компьютер', 'программ': 'програм',
    'програм': 'програм', 'software': 'програм', 'мэргэжл': 'мэргэжил',
    'мэргэжил': 'мэргэжил', 'элс': 'элсэлт', 'admission': 'элсэлт',
    'бүртгүүл': 'бүртгэл', 'бүртгэл': 'бүртгэл', 'төлбөр': 'төлбөр',
    'tuition': 'төлбөр', 'хураамж': 'хураамж', 'тэтгэл': 'тэтгэлэг',
    'scholarship': 'тэтгэлэг', 'тэнхим': 'тэнхим', 'department': 'тэнхим',
    'хөтөлбөр': 'хөтөлбөр', 'program': 'хөтөлбөр', 'оюут': 'оюутан',
    'суралц': 'суралц', 'сургуул': 'сургууль',
    'сургалт': 'сургалт', 'шалгалт': 'шалгалт', 'шалгуу': 'шалгалт',
    'лаборатор': 'лаборатори', 'механик': 'механик', 'химийн': 'хими',
    'барилг': 'барилга', 'цахилгаан': 'цахилгаан', 'электроник': 'электроник',
    'дадлаг': 'дадлага', 'утас': 'утас', 'холбогд': 'холбоо',
    'хаяг': 'хаяг', 'байрш': 'байршил', 'имэйл': 'имэйл', 'мэйл': 'имэйл',
    'email': 'имэйл', 'коосэн': 'коосэн', 'kosen': 'коосэн',
    'ярилцлаг': 'ярилцлага', 'эссэ': 'эссэ',
    'сакура': 'sakura', 'сакүра': 'sakura', 'арк': 'arc',
    'номын': 'ном', 'номынсан': 'ном', 'дотуур': 'дотуур',
}
SUFFIXES = ('уудаар', 'үүдээр', 'уудын', 'үүдийн', 'нууд', 'нүүд', 'уудаас',
            'үүдээс', 'ийн', 'ын', 'аар', 'ээр', 'оор', 'өөр', 'аас', 'ээс',
            'оос', 'өөс', 'тай', 'тэй', 'той', 'ууд', 'үүд', 'энд', 'анд', 'онд', 'инд')
NAV_LINES = {'Тэнхимүүд', 'Буцах', 'Бүгдийг харах', 'Нэвтрэх', 'Холбоосууд',
             'Удирдлага', 'MN MN', 'Нүүр', 'NM', 'CT', 'NMCT'}
# Exact, reviewed search spellings only. Preserve the submitted query and source
# text; this is neither general spell correction nor an ASR transcript edit.
SEARCH_SPELLINGS = {
    'шаардалага': 'шаардлага',
    'шаардалагатай': 'шаардлагатай',
    'шаардалагад': 'шаардлагад',
}


def search_terms(text):
    tokens = re.findall(r'\w+', unicodedata.normalize('NFC', text).casefold())
    result = []
    for token in tokens:
        if token in STOPWORDS or (len(token) == 1 and not token.isdigit()):
            continue
        token = SEARCH_SPELLINGS.get(token, token)
        token = {'зургаа':'зураг', 'зургийг':'зураг', 'зургийн':'зураг', 'зурагтай':'зураг', 'зурганд':'зураг'}.get(token, token)
        normalized = next((value for prefix, value in STEMS.items() if token.startswith(prefix)), token)
        if normalized == token:
            for suffix in SUFFIXES:
                if token.endswith(suffix) and len(token) - len(suffix) >= 4:
                    normalized = token[:-len(suffix)]
                    break
        if normalized not in STOPWORDS:
            result.append(normalized)
    return result


_ROMAN_QUERY_CODES = {'I','II','III','IV','V','VI','VII','VIII','IX','X','XI','XII'}
_GENERIC_QUERY_CODES = {'NMCT','PDF','PNG','JPEG','JPG','MB','GB','HTTP','HTTPS'}


def explicit_codes(text):
    """Literal source acronyms, excluding file types and Roman labels."""
    return {code.casefold() for code in re.findall(
        r'(?<![A-Za-z0-9])[A-Z][A-Z0-9]{1,}(?![A-Za-z0-9])', text)
        if code not in _ROMAN_QUERY_CODES | _GENERIC_QUERY_CODES}


def single_query_code(query, known_codes=()):
    """One literal acronym narrows topic, with corpus-backed case equivalence.

    Multiple named codes may require complementary sources, so do not apply
    this one-code gate to those questions. Lowercase words only count when an
    uppercase acronym was observed in the corpus; arbitrary English words do
    not become entities. This is a ranking guard, not entity recognition.
    """
    codes = explicit_codes(query)
    codes.update(token.casefold() for token in re.findall(
        r'(?<![A-Za-z0-9])[A-Za-z][A-Za-z0-9]{1,}(?![A-Za-z0-9])', query)
        if token.casefold() in known_codes)
    return next(iter(codes)) if len(codes) == 1 else None


def preceding_entity_codes(text, start):
    """Keep a cut company's local antecedent available to the topic guard.

    Merged HTML can cut a sentence after its named company. Only a short
    preceding slice of the same text is considered, and only with an explicit
    company/organisation anaphor. A complete new line starts its own scope.
    This context affects eligibility only; quoted text and offsets stay exact.
    """
    if not start or text[start-1] == '\n':
        return set()
    prefix = text[max(0, start-360):start].rsplit('\n', 1)[-1]
    if not re.search(r'\b(?:тус|уг|тухайн)\s+(?:компан|байгууллаг)',
                     prefix + ' ' + text[start:start+220], re.I):
        return set()
    return explicit_codes(prefix)


def diversity_group(row):
    # Hidden client fields have separate coordinate systems and independent
    # subjects. HTML/CAD must not consume the budget for a different CAM field.
    # At most two client fields and two other parts per URL are returned.
    return row['url'], row.get('text_scope') == 'client_tab_field_excerpt'


def _official(url):
    try:
        parsed = urlsplit(url)
        return (parsed.scheme == 'https' and parsed.hostname == 'nmct.edu.mn'
                and parsed.port in (None, 443) and not parsed.username and not parsed.password)
    except ValueError:
        return False


def _rank_text(text):
    return '\n'.join(line for line in text.splitlines() if line.strip() not in NAV_LINES)


def _complete_line_bounds(text, start, end):
    """Bound one imported window by complete physical lines, without rewriting.

    Keep the existing per-window grouping and forward line context. An edge
    may expand by at most SOURCE_BOUNDARY_CONTEXT Unicode characters. When an
    enclosing line is farther away, omit its incomplete edge rather than emit
    a cut word/sentence or copy an unbounded paragraph. Returned offsets remain
    character offsets into the captured page, including for multibyte scripts.
    """
    if not 0 <= start < end <= len(text):
        return None
    original_start, original_end = start, end
    left = text.rfind('\n', max(0, start - SOURCE_BOUNDARY_CONTEXT - 1), start)
    if left >= 0:
        start = left + 1
    elif start <= SOURCE_BOUNDARY_CONTEXT:
        start = 0
    else:
        left = text.find('\n', start, end)
        if left < 0:
            return None
        start = left + 1

    right = text.find('\n', end, min(len(text), end + SOURCE_BOUNDARY_CONTEXT + 1))
    if right >= 0:
        end = right
    elif len(text) - end <= SOURCE_BOUNDARY_CONTEXT:
        end = len(text)
    else:
        right = text.rfind('\n', start, end)
        if right < 0:
            return None
        end = right

    # Only outer whitespace is removed, by moving the exact source offsets.
    while start < end and text[start].isspace():
        start += 1
    while start < end and text[end - 1].isspace():
        end -= 1
    if start >= end or end <= original_start or start >= original_end:
        return None
    return start, end


class _LocalE5:
    """Persistent CPU encoder, with the same mean-pooling protocol as the probe."""
    def __init__(self, root):
        self.root = root
        self.model = self.tokenizer = None
        self.revision = None
        self.dimension = 384

    def load(self):
        if self.model is not None:
            return
        import torch
        from transformers import AutoModel, AutoTokenizer
        path = self.root / 'models/multilingual-e5-small'
        metadata = json.loads((self.root / 'config/model-catalog/intfloat--multilingual-e5-small.json').read_text(encoding='utf-8-sig'))
        manifest = json.loads((path / 'source-manifest.json').read_text(encoding='utf-8-sig'))
        expected = next(row for row in metadata['files'] if row['rfilename'] == 'model.safetensors')['lfs']['sha256']
        if (manifest['repo_id'] != metadata['repo_id'] or manifest['revision'] != metadata['revision']
                or sha256(path / 'model.safetensors') != expected):
            raise ValueError('Local E5 checkpoint does not match pinned metadata.')
        for name, item in manifest['files'].items():
            asset = (path / name).resolve()
            if not asset.is_relative_to(path.resolve()) or sha256(asset) != item['sha256']:
                raise ValueError('Local E5 asset failed checksum validation.')
        torch.set_num_threads(2)
        self.tokenizer = AutoTokenizer.from_pretrained(str(path), local_files_only=True, trust_remote_code=False)
        self.model = AutoModel.from_pretrained(str(path), local_files_only=True, trust_remote_code=False, use_safetensors=True).eval()
        self.revision = metadata['revision']

    def encode(self, texts, prefix):
        import numpy as np
        import torch
        import torch.nn.functional as F
        self.load()
        values = []
        for start in range(0, len(texts), 8):
            batch = self.tokenizer([prefix + t for t in texts[start:start + 8]],
                padding=True, truncation=True, max_length=512, return_tensors='pt')
            with torch.inference_mode():
                hidden = self.model(**batch).last_hidden_state
                mask = batch['attention_mask'].unsqueeze(-1).bool()
                pooled = hidden.masked_fill(~mask, 0.0).sum(1) / batch['attention_mask'].sum(1).unsqueeze(-1)
                values.append(F.normalize(pooled, p=2, dim=1).numpy())
        return np.concatenate(values)


class WebsiteRetriever:
    def __init__(self, root=None, database=None, use_dense=True):
        self.root = Path(root or ROOT).resolve()
        self.database = Path(database or self.root / 'CORE/database/website.db').resolve()
        self.use_dense = bool(use_dense)
        self._lock = threading.RLock()
        self._stamp = None
        self._rows = []
        self._run = None
        self._counts = {'pages': 0, 'chunks': 0, 'documents': 0, 'indexed_chunks': 0}
        self._encoder = _LocalE5(self.root)
        self._embeddings = None
        self._dense_status = 'not_loaded' if self.use_dense else 'disabled'
        self._corpus_id = None
        self._error = None

    def _refresh(self):
        stat = self.database.stat()
        stamp = (stat.st_mtime_ns, stat.st_size, date.today().isoformat())
        # Committed WAL transactions need not touch the main database file.
        # Re-read a SQLite snapshot while a WAL exists rather than trusting
        # filesystem timestamps (or comparing data_version across connections).
        # Keep the fast metadata path for the normal rollback-journal corpus.
        wal_active = self.database.with_name(self.database.name + '-wal').exists()
        if stamp == self._stamp and not wal_active:
            return
        with closing(readonly(self.database)) as db:
            db.execute('BEGIN')
            run = db.execute('SELECT * FROM crawl_runs ORDER BY retrieved_at DESC,run_id DESC LIMIT 1').fetchone()
            if run is None:
                self._rows, self._run, self._stamp = [], None, stamp
                return
            pages = db.execute('SELECT p.* FROM pages p JOIN captures x ON p.url=x.url AND p.version=x.version WHERE x.run_id=? ORDER BY p.url', (run['run_id'],)).fetchall()
            chunks = db.execute('SELECT c.* FROM chunks c JOIN captures x ON c.url=x.url AND c.version=x.version WHERE x.run_id=? ORDER BY c.url,c.ordinal', (run['run_id'],)).fetchall()
            document_count = db.execute('SELECT COUNT(*) FROM assets WHERE run_id=?', (run['run_id'],)).fetchone()[0]
            document_rows, document_warnings = read_document_rows(db, run)
            client_rows, client_warnings = read_client_tab_rows(db, run)
        page_map = {(p['url'], p['version']): dict(p) for p in pages}
        rows, seen, context_codes = [], set(), {}
        for chunk in chunks:
            page = page_map[(chunk['url'], chunk['version'])]
            # Never fall back to full_text: its repeated nav/banner/footer can be stale.
            if not _official(page['url']) or page['text_scope'] != 'main_element':
                continue
            if page['valid_from'] and page['valid_from'] > date.today().isoformat():
                continue
            if page['valid_until'] and page['valid_until'] < date.today().isoformat():
                continue
            if page.get('approval_status') == 'rejected':
                continue
            start, end = chunk['start_offset'], chunk['end_offset']
            if not 0 <= start < end <= len(page['text']) or page['text'][start:end] != chunk['text']:
                continue
            bounds = _complete_line_bounds(page['text'], start, end)
            if bounds is None:
                continue
            start, end = bounds
            text = page['text'][start:end]
            dedup = hashlib.sha256(text.encode()).hexdigest()
            if dedup in seen:
                continue
            seen.add(dedup)
            identity = f"{page['url']}|{page['version']}|{start}|{end}|{dedup}"
            row = {key: page[key] for key in ('url', 'version', 'title', 'retrieved_at', 'source_updated_at', 'text_scope', 'valid_from', 'valid_until')}
            row.update(source_id='web-' + hashlib.sha256(identity.encode()).hexdigest()[:20],
                chunk_id=chunk['ordinal'], start_offset=start, end_offset=end, text=text, excerpt=text,
                page_years=sorted(set(re.findall(r'\b20\d{2}\b', page['text']))),
                page_header=page['text'][:300], snapshot_only=True, validity_unknown=not bool(page['valid_from'] and page['valid_until']))
            rows.append(row)
            context_codes[row['source_id']] = preceding_entity_codes(page['text'], start)
        # A client field inherits the captured HTML page's approval/validity
        # guard; extracting a hidden field cannot make a blocked page eligible.
        client_rows = [row for row in client_rows if (page := page_map.get((row['url'], row['version'])))
            and _official(row['url']) and page['text_scope'] == 'main_element'
            and page.get('approval_status') != 'rejected'
            and not (page['valid_from'] and page['valid_from'] > date.today().isoformat())
            and not (page['valid_until'] and page['valid_until'] < date.today().isoformat())]
        rows.extend(document_rows)
        rows.extend(client_rows)
        self._document_warnings = document_warnings + client_warnings
        self._run = dict(run)
        self._rows = rows
        self._context_codes = context_codes
        self._passages = [row['title'] + '\n' + _rank_text(row['text']) for row in rows]
        self._lexical_passages = [' '.join(search_terms(p)) for p in self._passages]
        self._body_terms = [set(search_terms(_rank_text(row['text']) + '\n' + row.get('source_locator', ''))) for row in rows]
        frequencies = Counter(term for terms in self._body_terms for term in terms)
        self._term_weights = {term: math.log(1 + (len(rows) + 1) / (count + 1)) for term, count in frequencies.items()}
        self._counts = dict(pages=len(pages), chunks=len(chunks), documents=document_count, indexed_chunks=len(rows),
            indexed_document_passages=len(document_rows), indexed_documents=len({r['url'] for r in document_rows}),
            indexed_client_tab_passages=len(client_rows), indexed_client_tab_pages=len({r['url'] for r in client_rows}))
        fingerprint = INDEX_VERSION + run['manifest_sha256'] + '|'.join(row['source_id'] for row in rows)
        corpus_id = hashlib.sha256(fingerprint.encode()).hexdigest()
        if corpus_id != self._corpus_id:
            self._embeddings = None
        self._corpus_id = corpus_id
        self._stamp = stamp

    def status(self):
        with self._lock:
            try:
                self._refresh()
            except (OSError, ValueError, sqlite3.Error, KeyError) as error:
                return {'available': False, 'reason': type(error).__name__, 'dense_status': self._dense_status}
            return dict(available=bool(self._rows), corpus_id=self._corpus_id,
                counts=dict(self._counts), dense_status=self._dense_status,
                backend='bm25+e5_rrf' if self._dense_status == 'ready' else 'bm25_mongolian',
                retrieved_at=self._run['retrieved_at'] if self._run else None,
                training_performed=False, database_modified=False, score_is_probability=False)

    def _dense(self, query):
        if not self.use_dense or self._dense_status == 'unavailable':
            return None
        try:
            import numpy as np
            self._encoder.load()
            if self._embeddings is None:
                key = hashlib.sha256((self._corpus_id + str(self._encoder.revision)).encode()).hexdigest()
                path = self.root / 'runtime' / ('website-e5-' + key + '.npz')
                if path.is_file():
                    with np.load(path, allow_pickle=False) as archive:
                        stored = archive['embeddings']
                        if stored.shape != (len(self._rows), 384) or not np.isfinite(stored).all():
                            raise ValueError('Invalid local embedding cache.')
                        self._embeddings = stored
                else:
                    self._embeddings = self._encoder.encode(self._passages, 'passage: ')
                    path.parent.mkdir(parents=True, exist_ok=True)
                    temporary = path.with_suffix('.tmp')
                    with temporary.open('wb') as handle:
                        np.savez_compressed(handle, embeddings=self._embeddings)
                    temporary.replace(path)
            scores = (self._encoder.encode([query], 'query: ') @ self._embeddings.T)[0]
            if not np.isfinite(scores).all():
                raise ValueError('Nonfinite dense scores.')
            self._dense_status = 'ready'
            return [float(value) for value in scores]
        except (ImportError, OSError, ValueError, RuntimeError, KeyError) as error:
            self._dense_status = 'unavailable'
            self._error = type(error).__name__
            self._embeddings = None
            return None

    def search(self, query, limit=5, *, mode='production'):
        if mode not in RANKING_MODES:
            raise ValueError('Unknown ranking mode.')
        if not isinstance(query, str) or not query.strip() or len(query) > 1000 or not re.search(r'\w', query):
            raise ValueError('query must contain words and be at most 1000 characters.')
        if type(limit) is not int or not 1 <= limit <= 10:
            raise ValueError('limit must be an integer from 1 to 10.')
        started = time.perf_counter()
        with self._lock:
            self._refresh()
            query_terms = set(search_terms(query))
            topic_texts = [row['text'] + '\n' + row.get('source_locator','') + '\n' + row['title']
                          for row in self._rows]
            known_codes = set().union(*(explicit_codes(text) for text in topic_texts))
            known_codes.update(code for codes in getattr(self, '_context_codes', {}).values() for code in codes)
            topic_codes = [(set(search_terms(text)) & known_codes)
                           | getattr(self, '_context_codes', {}).get(row['source_id'], set())
                           for row, text in zip(self._rows, topic_texts)]
            query_code = single_query_code(query, known_codes)
            # Generic school words should not turn every unknown topic into a match.
            anchors = query_terms - {'сургууль', 'шинэ', 'монгол', 'nmct', 'шмтк', 'оюутан', 'сургалт'}
            anchors = {term for term in anchors if not re.fullmatch(r'(?:19|20)\d{2}', term)}
            if 'мэргэжил' in anchors:
                anchors.add('хөтөлбөр')
            lexical = bm25_scores(self._lexical_passages, [' '.join(anchors or query_terms)])[0] if self._rows else []
            dense = self._dense(query) if self._rows and mode != 'bm25' else None
            if mode in {'e5', 'rrf', 'rrf_boosted'} and dense is None:
                raise RuntimeError('Dense ranking experiment requires a working pinned local E5; fallback is not an E5 result.')
            lexical_rank = sorted(range(len(self._rows)), key=lambda i: (-lexical[i], self._rows[i]['source_id']))
            dense_rank = sorted(range(len(self._rows)), key=lambda i: (-dense[i], self._rows[i]['source_id'])) if dense is not None else []
            fused = [0.0] * len(self._rows)
            for ranking, weight in ((lexical_rank, 1.0), (dense_rank, 1.0)):
                for rank, index in enumerate(ranking, 1):
                    if ranking is lexical_rank and lexical[index] <= 0:
                        continue
                    fused[index] += weight / (RRF_K + rank)
            if mode == 'bm25':
                fused = list(lexical)
            elif mode == 'e5':
                fused = list(dense)
            if mode in {'production', 'rrf_boosted'}:
                # Reward coverage of informative query anchors. A dense neighbour with
                # only a generic registration term must not hide a specific rule clause.
                anchor_weight = sum(self._term_weights.get(t, 0) for t in anchors)
                if anchor_weight:
                    for index, terms in enumerate(self._body_terms):
                        fused[index] += ANCHOR_COVERAGE_WEIGHT * sum(self._term_weights.get(t, 0) for t in anchors & terms) / anchor_weight
                # Explicit phrase/category matches improve ranking only, never certify an answer.
                query_lower = query.casefold()
                for index, row in enumerate(self._rows):
                    body = row['text'].casefold()
                    if 'төлбөр' in anchors and 'сургалт' in query_terms and 'сургалтын төлбөр' in body:
                        fused[index] += CATEGORY_WEIGHT
                    if anchors <= {'мэргэжил', 'хөтөлбөр'} and anchors and 'элсэлт авах хөтөлбөр' in body:
                        fused[index] += CATEGORY_WEIGHT
                    if 'элсэлт' in anchors and 'шаардлага' in anchors and 'элсэлтэд оролцох эрх' in body:
                        fused[index] += CATEGORY_WEIGHT
                    if mode == 'production' and 'дотуур' in anchors and 'дотуур' not in body:
                        fused[index] = 0
                    if mode == 'production' and 'ном' in anchors and 'сан' in query_lower and 'номын сан' not in body:
                        fused[index] = 0
            candidates, used = [], []
            for index in sorted(range(len(self._rows)), key=lambda i: (-fused[i], self._rows[i]['source_id'])):
                if mode != 'e5' and not fused[index]:
                    continue
                row = self._rows[index]
                # Apply eligibility after every scoring boost: a category match
                # must never revive a different named topic. Ranking-only
                # ablations retain their original ungated interpretation.
                if mode == 'production' and query_code and query_code not in topic_codes[index]:
                    continue
                # Unknown topics must not acquire a nearest-neighbour answer merely
                # because E5 always ranks something. At least one real anchor is required.
                if mode == 'production' and anchors and not (anchors & self._body_terms[index]):
                    continue
                # Two HTML/document parts plus two independent client fields per page; no overlapping repeats.
                same = [r for r in used if diversity_group(r) == diversity_group(row)]
                # Normalized field offsets belong to one JSON locator, not the
                # HTML page or another field which also starts at zero.
                if len(same) >= 2 or any(r.get('text_scope') == row.get('text_scope')
                        and r.get('text_scope') != 'document_visual_excerpt'
                        and (row.get('text_scope') != 'client_tab_field_excerpt'
                             or r.get('source_locator') == row.get('source_locator'))
                        and max(0, min(r['end_offset'], row['end_offset']) - max(r['start_offset'], row['start_offset'])) > .55 * min(len(r['text']), len(row['text'])) for r in same):
                    continue
                # News listings mostly duplicate article teasers; use article bodies instead.
                if urlsplit(row['url']).path == '/news':
                    continue
                overlap = sorted(anchors & self._body_terms[index])
                candidate = dict(row, lexical_score=float(lexical[index]),
                    dense_score=dense[index] if dense is not None else None, score=fused[index],
                    matched_terms=overlap, query_anchor_terms=sorted(anchors),
                    lexical_overlap_count=len(overlap), requested_years=sorted(set(re.findall(r'\b20\d{2}\b', query))),
                    query_answer_support_established=False)
                candidates.append(candidate)
                used.append(row)
                if len(candidates) == limit:
                    break
            warnings = ['Search rankings do not prove answer support or current validity.',
                        'Documents and whitelisted client fields are selected excerpts, not complete OCR, all client tabs or human gold.']
            warnings.extend(getattr(self, '_document_warnings', []))
            if self._dense_status == 'unavailable':
                warnings.append('Local E5 unavailable; lexical retrieval remains active (' + str(self._error) + ').')
            return dict(query=query.strip(), status='ranked_candidates_only' if candidates else 'no_candidates',
                corpus_id=self._corpus_id,
                backend=('bm25+e5_rrf' if dense is not None else 'bm25_mongolian') if mode == 'production' else mode,
                ranking_mode=mode, lexical_topic_gates=(mode == 'production'),
                rrf_k=RRF_K if mode in {'rrf', 'rrf_boosted', 'production'} else None,
                candidates=candidates, counts=dict(self._counts), warnings=warnings,
                query_terms=sorted(query_terms), query_anchor_terms=sorted(anchors),
                has_lexical_evidence=any(row['lexical_overlap_count'] for row in candidates),
                score_is_probability=False, query_answer_support_established=False,
                generated=False, llm_calls=0, training_performed=False, database_modified=False,
                latency_seconds=time.perf_counter() - started)
