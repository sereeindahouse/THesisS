"""Project-owner acceptance of published official website content.

Separate from school staff approval and from measured validity. Original
versioned DB records, human references and school approval metadata stay intact.
"""
import json
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from question_router import route_question
from sqlite_retrieval import ReadOnlyContentStore, guarded_preview, search_content


class ContentUsePolicy:
    def __init__(self, root):
        self.root = Path(root)
        self.config = {}
        try:
            value = json.loads((self.root / 'config/content-use.json').read_text(encoding='utf-8'))
            if (value.get('basis') == 'user_acceptance_of_official_website'
                    and value.get('enabled') is True
                    and value.get('official_hosts') == ['nmct.edu.mn']):
                self.config = value
        except (OSError, ValueError, TypeError, AttributeError):
            pass

    @property
    def enabled(self):
        return bool(self.config)

    def status(self):
        return dict(enabled=self.enabled,
            basis=self.config.get('basis'), accepted_on=self.config.get('accepted_on'),
            school_staff_approval_claimed=False, database_approval_modified=False,
            validity_bounds_invented=False,
            message=('Албан сайтад нийтэлсэн эхийг төслийн хэрэглээнд ашиглаж байна.'
                     if self.enabled else 'Албан эх ашиглах төслийн бодлого тохируулагдаагүй.'))

    @staticmethod
    def _official(url):
        try:
            value = urlsplit(url)
            return (value.scheme == 'https' and value.hostname == 'nmct.edu.mn'
                    and value.username is None and value.password is None
                    and value.port in (None, 443))
        except (ValueError, TypeError):
            return False

    def faq_accepted(self, content, faq_id):
        if not self.enabled:
            return False
        faqs = {item['faq_id']: item for item in content['faqs']}
        facts = {item['fact_id']: item for item in content['facts']}
        sources = {(item['document_id'], item['version']): item for item in content['sources']}
        faq = faqs.get(faq_id)
        if faq is None or faq.get('answer_status') != 'complete_in_scope':
            return False
        dependencies = [faq] + [facts[fid] for fid in faq['fact_ids']]
        for item in dependencies:
            if item['approval_status'] not in ('draft', 'approved') or not item['source_refs']:
                return False
            for reference in item['source_refs']:
                source = sources.get((reference['document_id'], reference['version']))
                if (source is None or source['approval_status'] not in ('draft', 'approved')
                        or not self._official(source['source_url_or_filename'])
                        or source['content_capture'] not in ('selected_fact_extract', 'full_snapshot')):
                    return False
        return True

    def attribution(self, content, citations):
        sources = {(item['document_id'], item['version']): item for item in content['sources']}
        return [{**ref, 'retrieved_at': sources[(ref['document_id'], ref['version'])]['retrieved_at'],
                 'source_accepted_for_project': True,
                 'acceptance_basis': self.config['basis'], 'school_staff_approval': False}
                for ref in citations]

    def route(self, db, query, *, allow_draft=False, package_id=None):
        if allow_draft or not self.enabled:
            return route_question(db, query, allow_draft=allow_draft, package_id=package_id)
        # The underlying draft-capable read preserves known expiry, scope,
        # year, number and partial-answer guards. Only acceptance is different.
        result = route_question(db, query, allow_draft=True, package_id=package_id)
        with ReadOnlyContentStore(db) as store:
            content = store.export(result['package_id'])
        answer_id = result.get('answer_faq_id')
        if answer_id and not self.faq_accepted(content, answer_id):
            return route_question(db, query, allow_draft=False, package_id=result['package_id'])
        if any(not self._official(c['source_url_or_filename']) for c in result['citations']):
            return route_question(db, query, allow_draft=False, package_id=result['package_id'])
        result.update(mode='official_website', source_accepted_for_project=True,
                      acceptance_basis=self.config['basis'], school_staff_approval_claimed=False)
        result['citations'] = self.attribution(content, result['citations'])
        if result['answer'] is not None:
            result.update(answer_kind='official_website_snapshot',
                          message='Албан сайтад нийтэлсэн эхийн мэдээлэл. Эхийн огноо, хамрах хүрээг хадгалсан.',
                          reason_code='official_website_stored_answer',
                          reason_codes=['official_website_stored_answer'])
        return result

    def search(self, db, query, *, backend='bm25', top_k=3, allow_draft=False,
               package_id=None, as_of=None):
        """Rank candidates for manual selection; never include an answer.

        The ranking and exact-match evidence stay unchanged. In normal official
        mode, selection availability follows the same pinned-package preview
        policy as the next request, including expiry and completeness guards.
        A selectable fuzzy candidate is not an answer to the original query.
        """
        result = search_content(db, query, backend=backend, top_k=top_k,
                                allow_draft=allow_draft, package_id=package_id,
                                as_of=as_of)
        for key in ('answer', 'answer_faq_id', 'exact_match_preview'):
            result.pop(key, None)
        result.update(answer_served=False, preview_requires_selection=True)
        if allow_draft or not self.enabled:
            return result
        with ReadOnlyContentStore(db) as store:
            for candidate in result['candidates']:
                preview = self.preview(store, candidate['faq_id'],
                                       package_id=result['package_id'],
                                       as_of=date.fromisoformat(result['as_of']))
                accepted = preview.get('source_accepted_for_project', False)
                reasons = list(preview['answer_blocked_reasons'])
                if not accepted:
                    reasons.append('Not accepted as official website content by project policy.')
                candidate.update(
                    eligible=accepted and preview['answer_eligible'],
                    answer_eligible=False,
                    mode='official_website' if accepted else 'approved_only',
                    source_accepted_for_project=accepted,
                    blocked_reasons=reasons,
                    citations=preview['citations'])
                if accepted:
                    candidate.update(acceptance_basis=self.config['basis'],
                                     school_staff_approval_claimed=False)
        result.update(mode='official_website',
                      source_accepted_for_project=any(
                          candidate['source_accepted_for_project'] for candidate in result['candidates']),
                      acceptance_basis=self.config['basis'], school_staff_approval_claimed=False)
        if len(result['exact_matches']) == 1 and any(
                candidate['exact_match'] and candidate['eligible'] for candidate in result['candidates']):
            result['status'] = 'ranked_candidates_only'
        return result

    def preview(self, store, faq_id, *, allow_draft=False, package_id=None, as_of=None):
        if allow_draft or not self.enabled:
            return guarded_preview(store, faq_id, allow_draft=allow_draft,
                                   package_id=package_id, as_of=as_of)
        content = store.export(package_id)
        if not self.faq_accepted(content, faq_id):
            return guarded_preview(store, faq_id, allow_draft=False,
                                   package_id=package_id, as_of=as_of)
        result = guarded_preview(store, faq_id, allow_draft=True,
                                 package_id=package_id, as_of=as_of)
        result.update(mode='official_website', preview_kind='official_website_snapshot',
                      source_accepted_for_project=True,
                      acceptance_basis=self.config['basis'], school_staff_approval_claimed=False)
        result['citations'] = self.attribution(content, result['citations'])
        return result
