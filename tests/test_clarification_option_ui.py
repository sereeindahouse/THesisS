"""Actual rendered browser choices through the real bounded capability resolver."""
from pathlib import Path
import copy
import json
import shutil
import subprocess
import unittest

from clarification_context import ClarificationContext

ROOT=Path(__file__).resolve().parents[1]
NODE=shutil.which('node')
COOP_QUERY='Компанийн хамтын ажиллагаа эхэлсэн сар болон ямар платформ ашигласныг хэлнэ үү?'
YEAR_QUERY='Роботик инженерийн тэнхимийн оюутны тоо болон нэмэлт XCode талбарын мэдээлэл юу вэ?'


def cooperation():
    return dict(query=COOP_QUERY,route='D',answer=None,can_speak=False,package_id='invented-package',
        rag={'corpus_id':'invented-corpus'},clarification=dict(kind='missing_cooperation_entity',options=[
          dict(question='Sakura Internet',entity='Sakura Internet'),dict(question='ARC',entity='ARC'),dict(question='StoD',entity='StoD')]))


def missing_year():
    return dict(query=YEAR_QUERY,route='D',answer=None,can_speak=False,package_id='invented-package',
        rag={'corpus_id':'invented-corpus'},clarification=dict(kind='missing_year',supported_years=['2025','2026'],options=[
          dict(question='2025–2026 оны Роботик инженерийн тэнхимд хэдэн оюутан суралцаж байна вэ?')]))


def rendered_click(result,pending=None,*,source=None,**fixture):
    response=subprocess.run([NODE,str(ROOT/'tests/clarification_option_ui_harness.js'),str(source or ROOT/'demo/index.html')],
        input=json.dumps(dict(result=result,pending=pending,**fixture),ensure_ascii=False),capture_output=True,
        text=True,encoding='utf-8',timeout=10)
    if response.returncode:raise AssertionError(response.stderr)
    return json.loads(response.stdout)


@unittest.skipUnless(NODE,'Node is optional; actual browser handler checks require its JS runtime')
class ClarificationOptionUITests(unittest.TestCase):
    def setUp(self):self.context=ClarificationContext()

    def issued(self,result,draft=False):
        result=copy.deepcopy(result)
        identity=self.context.issue(result,allow_draft=draft)
        self.assertIsNotNone(identity)
        result['conversation']={'clarification_id':identity}
        pending=dict(id=identity,originalQuery=result['query'],draft=draft)
        return result,pending

    def route_request(self,output):
        requests=[call['body'] for call in output['calls'] if call['path']=='/api/route']
        self.assertEqual(len(requests),1,output)
        self.assertFalse(any(call['path']=='/api/conversation/reset' for call in output['calls']))
        return requests[0]

    def resolve(self,request):
        return self.context.resolve(request['clarification_id'],request['query'],allow_draft=request['allow_draft'],
                                    package_id='invented-package',corpus_id='invented-corpus')

    def test_rendered_company_buttons_preserve_original_month_and_platform(self):
        for index,entity in enumerate(('Sakura Internet','ARC','StoD')):
            with self.subTest(entity=entity):
                result,pending=self.issued(cooperation())
                output=rendered_click(result,pending,selectedIndex=index)
                request=self.route_request(output)
                self.assertEqual(request['clarification_id'],pending['id'])
                self.assertEqual(request['query'],entity)
                self.assertEqual(output['buttons'][index]['label'],entity)
                self.assertIsNone(output['currentTranscription'])
                resolved=self.resolve(request)
                self.assertTrue(resolved['applied'])
                self.assertEqual(resolved['resolved_query'],COOP_QUERY+'\nХамтын ажиллагааны байгууллага: '+entity)

    def test_rendered_year_range_replies_with_range_and_preserves_unknown_facet(self):
        result,pending=self.issued(missing_year())
        output=rendered_click(result,pending)
        self.assertEqual(output['buttons'][0],{'label':'2025–2026','query':'2025–2026'})
        request=self.route_request(output)
        self.assertEqual(request['clarification_id'],pending['id'])
        self.assertEqual(request['query'],'2025–2026')
        resolved=self.resolve(request)
        self.assertTrue(resolved['applied'])
        self.assertEqual(resolved['resolved_query'],'2025–2026 оны '+YEAR_QUERY)
        self.assertIn('XCode',resolved['resolved_query'])

    def test_rendered_single_year_replies_with_that_literal_year(self):
        result=missing_year();result['clarification']['options'][0]['question']='2025 оны Роботик инженерийн тэнхимийн оюутны тоо хэд вэ?'
        result,pending=self.issued(result);output=rendered_click(result,pending)
        request=self.route_request(output);self.assertEqual(request['query'],'2025')
        self.assertEqual(self.resolve(request)['resolved_query'],'2025 оны '+YEAR_QUERY)

    def test_old_button_cannot_replace_or_reset_a_new_pending_clarification(self):
        result,_=self.issued(cooperation());new_result,new_pending=self.issued(missing_year())
        output=rendered_click(result,new_pending,selectedIndex=2)
        self.assertEqual(output['calls'],[]);self.assertEqual(output['submitted'],[])
        self.assertEqual(output['pending'],new_pending)
        self.assertIn('хуучирсан',output['routeStatus'])
        self.assertEqual(self.context.resolve(new_pending['id'],'2025–2026',allow_draft=False,
             package_id='invented-package',corpus_id='invented-corpus')['resolved_query'],'2025–2026 оны '+YEAR_QUERY)

    def test_consumed_button_never_becomes_a_fresh_short_query(self):
        result,_=self.issued(cooperation());output=rendered_click(result,None,selectedIndex=2)
        self.assertEqual(output['calls'],[]);self.assertEqual(output['submitted'],[])
        self.assertIn('хуучирсан',output['routeStatus'])

    def test_draft_mismatch_retains_context_without_posting(self):
        result,pending=self.issued(cooperation(),draft=False)
        for checked,turn_draft in ((True,False),(False,True)):
            with self.subTest(checked=checked,turn_draft=turn_draft):
                output=rendered_click(result,pending,checkedDraft=checked,turnDraft=turn_draft)
                self.assertEqual(output['calls'],[]);self.assertEqual(output['pending'],pending)
                self.assertIn('горим',output['routeStatus'])

    def test_matching_draft_context_can_be_consumed(self):
        result,pending=self.issued(cooperation(),draft=True)
        request=self.route_request(rendered_click(result,pending,checkedDraft=True,turnDraft=True,selectedIndex=2))
        self.assertTrue(request['allow_draft']);self.assertTrue(self.resolve(request)['applied'])

    def test_busy_controls_also_guard_programmatic_option_click(self):
        result,pending=self.issued(cooperation())
        for busy in ('routeBusy','voiceBusy','micStarting','recording'):
            with self.subTest(busy=busy):
                output=rendered_click(result,pending,busy=busy)
                self.assertEqual(output['calls'],[]);self.assertEqual(output['pending'],pending)
                self.assertEqual(output['currentTranscription'],{'id':'synthetic-audio'})

    def test_no_capability_option_displays_and_submits_full_canonical_question(self):
        result=missing_year();output=rendered_click(result)
        canonical=result['clarification']['options'][0]['question']
        request=self.route_request(output)
        self.assertEqual(output['buttons'][0]['label'],canonical)
        self.assertEqual(request['query'],canonical)
        self.assertNotIn('clarification_id',request)

    def test_other_d_option_with_capability_keeps_full_canonical_reply(self):
        original='Бүртгэлийн хураамж хэд вэ?'
        canonical='2025–2026 оны элсэлтийн бүртгэлийн хураамж хэд вэ?'
        result=dict(query=original,route='D',answer=None,can_speak=False,package_id='invented-package',
             rag={'corpus_id':'invented-corpus'},clarification=dict(kind='registration_scope',options=[dict(question=canonical)]))
        result,pending=self.issued(result);output=rendered_click(result,pending)
        request=self.route_request(output)
        self.assertEqual(output['buttons'][0]['label'],canonical)
        self.assertEqual(request['query'],canonical)
        self.assertEqual(request['clarification_id'],pending['id']);self.assertTrue(self.resolve(request)['applied'])


if __name__=='__main__':unittest.main()
