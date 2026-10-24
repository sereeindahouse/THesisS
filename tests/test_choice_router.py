"""Source/year/scope contracts use invented admissions data, never school gold."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import tempfile
import unittest

from content_store import ContentStore
from project_policy import ContentUsePolicy
from question_router import route_question


def fixture(state='approved'):
    meta=dict(approval_status=state, approved_by='invented test reviewer' if state=='approved' else None,
        approved_at='2026-10-01T00:00:00Z' if state=='approved' else None,
        valid_from='2026-10-01',valid_until='2026-10-31')
    ref=dict(document_id='invented.admission',version=3,locator='invented choice clause')
    source=dict(document_id='invented.admission',version=3,title='Invented fixture, not school approval',
        source_url_or_filename='https://nmct.edu.mn/fixture-only',retrieved_at='2026-10-10',
        source_updated_at=None,content_capture='selected_fact_extract',scope='Invented tests',notes='',**meta)
    fact=dict(fact_id='fixture.choice',entity_id='nmct.admissions',key='second_choice.fixture',
        value=dict(published_clause='Тестийн нэмэлт 2-р сонголт заавал.',year_scope='2042–2043'),
        source_refs=[ref],scope='Зөвхөн 2042–2043 оны зохиомол журам.',notes='',**meta)
    faq=dict(faq_id='fixture.choice.faq',question='2042–2043 оны элсэлтэд хоёр дахь сонголт хийх ёстой юу?',
        question_aliases=[],answer='2042–2043 оны тестийн журамд 2-р сонголт заавал.',
        fact_ids=[fact['fact_id']],source_refs=[ref],scope=fact['scope'],
        answer_status='complete_in_scope',notes='',**meta)
    tuition=deepcopy(fact)
    tuition.update(fact_id='fixture.tuition',key='annual_tuition.fixture',
        value=dict(published_clause='2042 онд жилийн тестийн төлбөр 17 төгрөг.',year_scope='2042'),
        scope='2042 оны төлбөр; 2043 оны үнэ биш.')
    tuition_faq=deepcopy(faq)
    tuition_faq.update(faq_id='fixture.tuition.faq',question='2042 оны сургалтын төлбөр хэд вэ?',
        answer='2042 оны жилийн тестийн төлбөр 17 төгрөг; 2043 оны үнэ биш.',
        fact_ids=[tuition['fact_id']],scope=tuition['scope'])
    return dict(schema_version=1,sources=[source],facts=[fact,tuition],faqs=[faq,tuition_faq])


class ChoiceRouterTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.db=self.root/'content.db'
        self.as_of=date(2026,10,10)

    def tearDown(self):self.tmp.cleanup()

    def put(self,data=None):
        with ContentStore(self.db) as store:return store.import_content(data or fixture(),allow_draft=True)['package_id']

    def route(self,query,**kw):
        return route_question(self.db,query,as_of=self.as_of,**kw)

    def test_literal_choice_alias_cannot_expand_positive_scope_using_negated_years(self):
        data=fixture()
        wrong='2044–2045 оны элсэлтэд нэг мэргэжил сонгож болох уу?'
        data['faqs'][0]['question_aliases'].append(wrong)
        data['faqs'][0]['scope']+=' 2044–2045 оны журам биш.'
        data['facts'][0]['scope']+=' 2044–2045 оны журам биш.'
        self.put(data)
        result=self.route(wrong)
        self.assertEqual(result['route'],'E')
        self.assertIsNone(result['answer'])
        self.assertEqual(result['reason_code'],'admission_choice_scope_not_available')

    def test_trailing_tuition_calendar_year_retains_positive_year_scope(self):
        self.put()
        for q in ('Сургалтын төлбөр 2043 онд хэд болох вэ?',
                  'Сургалтын төлбөр 2043 оны яг хэд вэ?'):
            with self.subTest(q=q):
                result=self.route(q)
                self.assertIsNone(result['answer'])
                self.assertEqual(result['reason_code'],'tuition_year_scope_not_available')

    def test_one_program_question_returns_actual_stored_answer_and_citation(self):
        self.put()
        before=self.db.read_bytes()
        result=self.route('2042–2043 оны элсэлтэд ганцхан мэргэжил сонгоод бүртгүүлж болох уу?')
        self.assertEqual(result['route'],'B')
        self.assertEqual(result['answer'],fixture()['faqs'][0]['answer'])
        self.assertEqual(result['binding_faq_id'],'fixture.choice.faq')
        self.assertEqual(result['match_kind'],'bounded_admission_choice')
        self.assertEqual(result['exact_matches'],[])
        self.assertEqual(result['citations'][0]['version'],3)
        self.assertEqual(self.db.read_bytes(),before)
        self.assertEqual(result['llm_calls'],0)

    def test_equivalent_second_choice_questions_preserve_the_same_policy(self):
        self.put()
        for body in ['элсэлтийн бүртгэлд мэргэжлийн 2-р сонголт заавал хийх үү',
                     'элсэлтэд хоёр дахь мэргэжлийн сонголтыг орхиж болох уу',
                     'элсэлтийн цахим бүртгэлд хоёрдугаар сонголт хийхгүй байж болох уу',
                     'элсэлтэд нэг мэргэжил сонгож болох уу']:
            with self.subTest(body=body):
                r=self.route('2042–2043 оны '+body+'?')
                self.assertEqual(r['answer'],fixture()['faqs'][0]['answer'])

    def test_unknown_condition_or_second_question_never_disappears(self):
        self.put()
        for query in [
            '2042–2043 оны элсэлтэд тэтгэлэгтэй бол ганцхан мэргэжил сонгоод бүртгүүлж болох уу?',
            '2042–2043 оны элсэлтэд ганцхан мэргэжил сонгоод бүртгүүлж болох уу, бас төлбөр хэд вэ?',
            '2042–2043 оны элсэлтэд ганцхан мэргэжил сонгоод бүртгүүлж болох уу? Тэгвэл шалгалт өгөхгүй юу?',
            '2042–2043 оны элсэлтэд ганцхан мэргэжил сонгоод бүртгүүлж болох уу эсвэл багш сонгох уу?']:
            with self.subTest(query=query):
                r=self.route(query)
                self.assertIsNone(r['answer'])
                self.assertNotEqual(r['match_kind'],'bounded_admission_choice')

    def test_other_intents_are_not_changed_to_admission_choice(self):
        self.put()
        for query in ['2042–2043 оны элсэлтэд ганцхан хичээл сонгож болох уу?',
                      '2042–2043 оны багшийн бүртгэлд нэг мэргэжил сонгож болох уу?',
                      '2042–2043 оны элсэлтэд нэг мэргэжил сонгохгүй байж болох уу?']:
            self.assertIsNone(self.route(query)['answer'])

    def test_calendar_year_cannot_replace_academic_interval(self):
        self.put()
        r=self.route('2043 оны элсэлтэд нэг мэргэжил сонгож болох уу?')
        self.assertEqual(r['reason_code'],'admission_choice_scope_not_available')
        self.assertIsNone(r['answer'])

    def test_missing_year_asks_an_understandable_year_question(self):
        self.put()
        r=self.route('Элсэлтийн бүртгэлд нэг мэргэжил сонгож болох уу?')
        self.assertEqual(r['route'],'D')
        self.assertEqual(r['reason_code'],'admission_choice_year_needed')
        self.assertEqual(r['clarification']['supported_years'],['2042','2043'])
        self.assertEqual(r['clarification']['options'],[])

    def test_reversed_interval_still_rejected_before_scope_binding(self):
        self.put()
        r=self.route('2043–2042 оны элсэлтэд нэг мэргэжил сонгож болох уу?')
        self.assertEqual(r['reason_code'],'invalid_year_range')
        self.assertIsNone(r['answer'])

    def test_draft_preview_remains_explicit_and_default_guard_blocks(self):
        self.put(fixture('draft'))
        q='2042–2043 оны элсэлтэд нэг мэргэжил сонгож болох уу?'
        self.assertIsNone(self.route(q)['answer'])
        r=self.route(q,allow_draft=True)
        self.assertEqual(r['answer_kind'],'development_draft_preview')
        self.assertFalse(r['human_gold'])
        self.assertFalse(r['automatic_approval'])

    def test_every_rejected_expired_future_partial_dependency_still_blocks(self):
        q='2042–2043 оны элсэлтэд нэг мэргэжил сонгож болох уу?'
        for group,field,value in [('sources','approval_status','rejected'),
             ('facts','approval_status','rejected'),('faqs','approval_status','rejected'),
             ('facts','valid_until','2026-10-09'),('sources','valid_from','2026-10-11'),
             ('faqs','answer_status','partial_in_scope')]:
            data=fixture('draft') if value=='rejected' else fixture()
            data[group][0][field]=value
            if value=='rejected':data[group][0].update(approved_by=None,approved_at=None)
            package=self.put(data)
            for allow in (False,True):
                with self.subTest(group=group,field=field,allow=allow):
                    self.assertIsNone(self.route(q,allow_draft=allow,package_id=package)['answer'])

    def test_ambiguous_two_faqs_cannot_pick_a_policy_by_score(self):
        data=fixture();other=deepcopy(data['faqs'][0]);other['faq_id']='fixture.other.choice'
        other['question']='Өөр зохиомол сонголтын асуулт?';data['faqs'].append(other);self.put(data)
        r=self.route('2042–2043 оны элсэлтэд нэг мэргэжил сонгож болох уу?')
        self.assertIsNone(r['answer'])
        self.assertEqual(r['reason_code'],'admission_choice_scope_not_available')

    def test_old_package_stays_pinned_after_new_year_policy_import(self):
        old=self.put();new=fixture()
        new['facts'][0]['value']['year_scope']='2044–2045'
        new['faqs'][0].update(question='2044–2045 оны өөр журам уу?',answer='2044–2045 оны өөр зохиомол хариулт.')
        self.put(new)
        r=self.route('2042–2043 оны элсэлтэд нэг мэргэжил сонгож болох уу?',package_id=old)
        self.assertEqual(r['answer'],fixture()['faqs'][0]['answer'])
        self.assertEqual(r['package_id'],old)

    def test_negative_mentioned_year_is_not_positive_tuition_coverage(self):
        self.put()
        r=self.route('2043 онд сургалтын төлбөр яг хэд болох вэ?')
        self.assertEqual(r['route'],'E')
        self.assertEqual(r['reason_code'],'tuition_year_scope_not_available')
        self.assertEqual(r['supported_years'],['2042'])
        self.assertIn('2043',r['message'])
        self.assertNotIn('17',r['message'])
        self.assertNotIn('FAQ',r['message'])

    def test_supported_tuition_canonical_question_keeps_existing_preview(self):
        self.put()
        r=self.route('2042 оны сургалтын төлбөр хэд вэ?')
        self.assertEqual(r['answer'],fixture()['faqs'][1]['answer'])

    def test_exact_wrong_year_alias_cannot_borrow_a_negated_year(self):
        data=fixture()
        data['faqs'][1]['question_aliases']=['2043 онд сургалтын төлбөр яг хэд болох вэ?']
        self.put(data)
        r=self.route(data['faqs'][1]['question_aliases'][0])
        self.assertEqual(r['reason_code'],'tuition_year_scope_not_available')
        self.assertIsNone(r['answer'])

    def test_live_class_clock_does_not_use_historical_exam_or_contact_hours(self):
        self.put()
        r=self.route('Манай 2-р курсийн хичээл маргааш хэдэн цагт эхлэх вэ?')
        self.assertEqual(r['reason_code'],'live_class_schedule_not_available')
        self.assertEqual(r['route'],'E')
        self.assertIsNone(r['answer'])
        self.assertIn('Тэнхим, бүлгээ',r['message'])
        self.assertNotIn('FAQ',r['message'])

    def test_literal_tomorrow_faq_cannot_establish_a_live_class_timetable(self):
        data=fixture()
        q='Манай 2-р курсийн хичээл маргааш хэдэн цагт эхлэх вэ?'
        data['faqs'][0]['question_aliases']=[q]
        self.put(data)
        r=self.route(q)
        self.assertEqual(r['reason_code'],'live_class_schedule_not_available')
        self.assertIsNone(r['answer'])

    def test_owner_accepted_official_draft_uses_same_guarded_preview(self):
        self.put(fixture('draft'))
        (self.root/'config').mkdir()
        (self.root/'config/content-use.json').write_text(json.dumps(dict(enabled=True,
            basis='user_acceptance_of_official_website',official_hosts=['nmct.edu.mn'])),encoding='utf-8')
        r=ContentUsePolicy(self.root).route(self.db,'2042–2043 оны элсэлтэд нэг мэргэжил сонгож болох уу?')
        self.assertIsNotNone(r['answer'])
        self.assertEqual(r['answer_kind'],'official_website_snapshot')
        self.assertFalse(r['school_staff_approval_claimed'])


if __name__=='__main__':unittest.main()
