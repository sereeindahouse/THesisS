"""Read-only SQLite FAQ ranking and guarded exact-question previews.

BM25/E5 scores rank candidates; they are never probabilities or proof that an
answer is supported. Only a unique canonical question/explicit alias can return
a complete stored answer, after ContentStore approval and validity guards.
Explicit draft previews are development evidence, never approved school facts.
"""
import argparse
import json
import math
import sqlite3
import sys
import unicodedata
from datetime import date, datetime
from pathlib import Path

from content_store import ContentStore
from retrieval_probe import bm25_scores, dense_scores, terms

ROOT = Path(__file__).resolve().parent


class ReadOnlyContentStore(ContentStore):
    """Open an existing supported store, without creating directories or tables.

    A read transaction freezes the package/content view for this connection.
    Import/write methods inherited from ContentStore fail at SQLite's read-only
    boundary. Close the context before a separate content importer is used.
    """

    def __init__(self, path):
        self.path = Path(path).resolve()
        if not self.path.is_file():
            raise FileNotFoundError('Existing content database required; import content first.')
        self.connection = sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True)
        self.connection.row_factory = sqlite3.Row
        try:
            self.connection.execute('PRAGMA query_only=ON')
            self.connection.execute('PRAGMA foreign_keys=ON')
            self.connection.execute('BEGIN')
            version = self.connection.execute('PRAGMA user_version').fetchone()[0]
            tables = self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
            if version != 1 or {row['name'] for row in tables} != {
                    'packages', 'source_versions', 'package_sources', 'facts', 'faqs', 'citations', 'faq_facts'}:
                raise ValueError('Database is not a supported NMCT content store.')
        except Exception:
            self.connection.close()
            raise


def exact_key(text):
    """Case/whitespace/end-punctuation normalization; retain names and numbers.

    This does not stem words, replace spoken numbers, correct STT or invent new
    aliases. Interior punctuation remains part of the explicit stored wording.
    """
    value = ' '.join(unicodedata.normalize('NFC', text).casefold().split())
    return value.rstrip('.?!。！？').rstrip()



def guarded_preview(store, faq_id, *, allow_draft=False, package_id=None, as_of=None):
    """View a stored FAQ by ID; viewing never proves it answers a query.

    Approved-only mode masks unknown-validity or partial answers. Explicit
    development mode permits scoped partial/unknown-date viewing, still subject
    to ContentStore rejection/known expiry guards and clear draft-mode labels.
    """
    if type(allow_draft) is not bool:
        raise ValueError('allow_draft must be a boolean.')
    preview = store.preview('faq', faq_id, package_id=package_id,
                            allow_draft=allow_draft, as_of=as_of, include_answer=True)
    reasons = list(preview['blocked_reasons'])
    if not allow_draft:
        if preview['answer_status'] != 'complete_in_scope':
            reasons.append('FAQ answer is partial_in_scope; no approved complete preview.')
        if preview['unknown_validity_records']:
            reasons.append('Unknown validity bounds; no approved complete preview.')
    preview['answer_eligible'] = not reasons
    preview['answer_blocked_reasons'] = reasons
    preview['preview_kind'] = ('development_document_view' if allow_draft else 'approved_document_view')
    preview['query_answer_support_established'] = False
    if reasons:
        preview['answer'] = None
    return preview


def search_content(db_path, query, *, backend='bm25', top_k=3,
                   allow_draft=False, package_id=None, as_of=None):
    """Return source-linked candidates and an optional unique exact-match preview.

    Default mode may rank drafts but does not expose their answers. Fuzzy matches
    always return answer=None. An approved exact answer additionally requires
    known validity bounds; explicit development previews show unknown bounds.
    E5 is optional, uses the existing verified local checkpoint and never trains
    or downloads. The caller should cache/search in batches for later services;
    this small development CLI intentionally makes no latency guarantee.
    """
    if not isinstance(query, str) or not query.strip() or len(query) > 4000 or not terms(query):
        raise ValueError('query must contain words and be at most 4000 characters.')
    if backend not in {'bm25', 'e5'}:
        raise ValueError('backend must be bm25 or e5.')
    if type(top_k) is not int or not 1 <= top_k <= 50:
        raise ValueError('top_k must be an integer from 1 to 50.')
    if type(allow_draft) is not bool:
        raise ValueError('allow_draft must be a boolean.')
    as_of = date.today() if as_of is None else as_of
    if not isinstance(as_of, date) or isinstance(as_of, datetime):
        raise ValueError('as_of must be a date.')
    query = query.strip()
    with ReadOnlyContentStore(db_path) as store:
        frozen_package = store.package_id(package_id)
        content = store.export(frozen_package)
        faqs = content['faqs']
        exact_ids = [faq['faq_id'] for faq in faqs
                     if exact_key(query) in {exact_key(text)
                         for text in [faq['question'], *faq['question_aliases']]}]
        previews = {faq['faq_id']: store.preview('faq', faq['faq_id'],
                    package_id=frozen_package, allow_draft=allow_draft,
                    as_of=as_of, include_answer=False) for faq in faqs}
        report = dict(query=query, package_id=frozen_package,
            mode='development_draft' if allow_draft else 'approved_only',
            backend=backend, as_of=as_of.isoformat(), top_k=top_k,
            corpus_faq_count=len(faqs), candidates=[], exact_matches=exact_ids,
            status='no_candidates', answer=None, answer_faq_id=None,
            exact_match_preview=None, generated=False, llm_calls=0,
            score_is_probability=False, automatic_approval=False,
            training_performed=False, database_modified=False)
        if not faqs:
            return report
        passages = [' '.join([faq['question'], *faq['question_aliases'],
                             faq['answer'], faq['scope']]) for faq in faqs]
        if backend == 'bm25':
            scores = bm25_scores(passages, [query])[0]
            report['backend_protocol'] = dict(k1=1.5, b=0.75,
                tokenizer='NFC/casefold Unicode word tokens',
                idf='log1p((N-df+0.5)/(df+0.5))',
                query_term_weight='sorted unique query terms')
        else:
            matrix, protocol = dense_scores(passages, [query])
            scores = matrix[0]
            report['backend_protocol'] = protocol
        if len(scores) != len(faqs) or not all(math.isfinite(score) for score in scores):
            raise ValueError('Retrieval backend returned invalid scores.')
        for index in sorted(range(len(faqs)), key=lambda i: (-scores[i], faqs[i]['faq_id'])):
            # An all-zero lexical ranking is not a useful candidate set.
            if backend == 'bm25' and scores[index] <= 0:
                continue
            faq = faqs[index]
            preview = previews[faq['faq_id']]
            exact = faq['faq_id'] in exact_ids
            answer_eligible = (exact and len(exact_ids) == 1 and preview['eligible']
                and faq['answer_status'] == 'complete_in_scope'
                and (allow_draft or not preview['unknown_validity_records']))
            report['candidates'].append(dict(faq_id=faq['faq_id'], question=faq['question'],
                score=float(scores[index]), scope=faq['scope'],
                answer_status=faq['answer_status'], approval_status=faq['approval_status'],
                eligible=preview['eligible'], answer_eligible=answer_eligible,
                blocked_reasons=preview['blocked_reasons'],
                unknown_validity_records=preview['unknown_validity_records'],
                citations=preview['citations'], exact_match=exact))
            if len(report['candidates']) == top_k:
                break
        if report['candidates']:
            report['status'] = 'ranked_candidates_only'
        elif backend == 'bm25':
            report['status'] = 'no_lexical_match'
        if len(exact_ids) > 1:
            report['status'] = 'ambiguous_exact_match'
        elif len(exact_ids) == 1:
            faq_id = exact_ids[0]
            preview = store.preview('faq', faq_id, package_id=frozen_package,
                allow_draft=allow_draft, as_of=as_of, include_answer=True)
            reasons = list(preview['blocked_reasons'])
            if preview['answer_status'] != 'complete_in_scope':
                reasons.append('FAQ answer is partial_in_scope; no complete exact answer.')
            if not allow_draft and preview['unknown_validity_records']:
                reasons.append('Unknown validity bounds; no approved exact answer.')
            preview['answer_eligible'] = not reasons
            preview['answer_blocked_reasons'] = reasons
            if reasons:
                preview['answer'] = None
                report['status'] = 'blocked_exact_match'
            else:
                report['answer'] = preview['answer']
                report['answer_faq_id'] = faq_id
                report['status'] = ('development_exact_preview' if allow_draft
                                    else 'approved_exact_answer')
            report['exact_match_preview'] = preview
        return report


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(
        description='SQLite FAQ хайлт; төстэй оноо нь зөв хариултын баталгаа биш.')
    parser.add_argument('query', help='Текст асуулт')
    parser.add_argument('--db', type=Path, default=ROOT / 'runtime/content.db',
                        help='Байгаа SQLite сан; энэ команд импортлох/шинээр үүсгэхгүй.')
    parser.add_argument('--backend', choices=['bm25', 'e5'], default='bm25',
                        help='E5 зөвхөн өмнө татсан локал жин ашиглана.')
    parser.add_argument('--top-k', type=int, default=3)
    parser.add_argument('--package-id', help='Хуучин багцын hash; байхгүй бол хамгийн сүүлийн багц.')
    parser.add_argument('--as-of', type=date.fromisoformat, help='Хүчинтэй байдлыг шалгах YYYY-MM-DD өдөр')
    parser.add_argument('--allow-draft', action='store_true',
                        help='Draft-ийг хөгжүүлэлтийн горимд харна; хүний баталгаа болохгүй.')
    parser.add_argument('--output', type=Path,
                        help='results доторх шинэ JSON; байгаа файл дээр дарж бичихгүй.')
    args = parser.parse_args()
    output = None
    if args.output:
        output = args.output.resolve()
        if not output.is_relative_to((ROOT / 'results').resolve()):
            parser.error('--output must be inside project results.')
        if output.exists():
            parser.error('--output already exists; use a new result filename.')
        if not output.parent.is_dir():
            parser.error('--output parent directory must already exist.')
    try:
        result = search_content(args.db, args.query, backend=args.backend,
            top_k=args.top_k, allow_draft=args.allow_draft,
            package_id=args.package_id, as_of=args.as_of)
    except (OSError, ValueError, KeyError, sqlite3.Error) as error:
        parser.error(str(error))
    encoded = json.dumps(result, ensure_ascii=False, indent=2)
    if output:
        with output.open('x', encoding='utf-8') as handle:
            handle.write(encoded + '\n')
    print(encoded)


if __name__ == '__main__':
    main()
