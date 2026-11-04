"""Invented text/source fixtures only; no actual speech/reference or API."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from stt_text_normalization import Normalizer
from tools.evaluate_stt_normalization import outside_span_changes, output_path, regressions, main
from tools.stt_normalization_metrics import annotate_reference, score_texts
from tools.stt_normalization_reference import draft_rubric, validate_rubric
from tools.analyze_stt_normalization_results import post_analysis


class SourceReferenceTests(unittest.TestCase):
    def setUp(self):
        self.source = dict(source_id='fake-lab', url='https://example.invalid/fake',
                           version=1, text='ЗОХИОМОЛ лаборатори хоёрдугаар давхарт байрлана.')
        self.row = dict(id='fake', reference='ЗОХИОМОЛ лаборатори хэддүгээр давхарт вэ?', critical_slots=[])

    def test_reference_binds_subject_requested_field_and_captured_text(self):
        rubric = draft_rubric([self.row], [self.source])
        self.assertTrue(rubric['records'][0]['task_applicable'])
        self.assertFalse(rubric['human_reviewed'])
        self.assertTrue(validate_rubric(rubric, [self.row], [self.source]))
        rubric['records'][0]['support'][0]['phrase'] = 'FAKE invented evidence'
        with self.assertRaisesRegex(ValueError, 'reference_source_proof_changed'):
            validate_rubric(rubric, [self.row], [self.source])

    def test_wrong_subject_is_unresolved_not_claimed_source_absence(self):
        source = dict(self.source, text='ЗОХИОМОЛ спорт заал хоёрдугаар давхарт.')
        record = draft_rubric([self.row], [source])['records'][0]
        self.assertFalse(record['task_applicable'])
        self.assertEqual(record['answerability'], 'ambiguous')

    def test_declared_year_cannot_match_other_year(self):
        row = dict(self.row, reference='ЗОХИОМОЛ лаборатори 2026 онд хэддүгээр давхарт вэ?',
                   critical_slots=[dict(field='year', expected='2026')])
        record = draft_rubric([row], [dict(self.source, text=self.source['text'] + ' 2025 он.')])['records'][0]
        self.assertFalse(record['task_applicable'])

    def test_statement_and_uncertain_question_are_separate(self):
        statement = dict(self.row, reference='ЗОХИОМОЛ лаборатори хоёрдугаар давхарт.')
        self.assertEqual(draft_rubric([statement], [self.source])['records'][0]['answerability'], 'non_question')
        uncertain = dict(self.row, critical_slots=[dict(field='year_literal_uncertain', expected='хоёр')])
        self.assertEqual(draft_rubric([uncertain], [self.source])['records'][0]['answerability'], 'ambiguous')

    def test_identity_question_needs_declared_school_name_and_identity_intent(self):
        row = dict(id='fake', reference='ЗОХИОМОЛ Коосэн гэдэг нэр мөн үү?',
                   critical_slots=[dict(field='school_name', expected='ЗОХИОМОЛ Коосэн')])
        source = dict(self.source, text='Сургуулийн нэр: ЗОХИОМОЛ Коосэн.')
        self.assertTrue(draft_rubric([row], [source])['records'][0]['task_applicable'])
        other_attribute = dict(row, reference='ЗОХИОМОЛ Коосэн захирал хэн бэ?')
        self.assertFalse(draft_rubric([other_attribute], [source])['records'][0]['task_applicable'])


class EvaluationContractTests(unittest.TestCase):
    def test_original_text_and_only_declared_spans(self):
        raw = 'ЗОХИОМОЛ лаборатоори хоёр мянга хорин зургаан онд БИШ.'
        value = Normalizer(enabled=True, terms=['лаборатори']).normalize(raw)
        self.assertFalse(outside_span_changes(raw, value))
        self.assertEqual(value['original_text'], raw)
        self.assertIn('БИШ.', value['normalized_search_text'])
        value['normalized_search_text'] += ' fake'
        self.assertTrue(outside_span_changes(raw, value))

    def test_reference_inflection_counts_school_term_error(self):
        row = dict(id='fake', reference='ЗОХИОМОЛ лабораторийн мэдээлэл.', critical_slots=[])
        annotation = annotate_reference(row['reference'], [], ['лаборатори'])
        scored = score_texts([row], {'fake':'ЗОХИОМОЛ өөр мэдээлэл.'}, {'fake':annotation}, ['лаборатори'])
        self.assertEqual(scored['error_categories']['school_term'], 1)
        self.assertEqual(scored['school_term_errors'][0]['term'], 'лаборатори')

    def test_only_newly_lost_critical_values_are_regressions(self):
        before = dict(rows=[dict(id='fake', critical_values=dict(records=[{'found':True},{'found':None},{'found':False}]))])
        after = dict(rows=[dict(id='fake', critical_values=dict(records=[{'found':False},{'found':False},{'found':True}]))])
        self.assertEqual(regressions(before, after, 'critical_values'), 1)

    def test_public_initial_name_is_name_category_not_school_term(self):
        row = dict(id='fake', reference='ЗОХИОМОЛ багш З.Наран энд.', critical_slots=[])
        annotation = annotate_reference(row['reference'], [], ['З.Наран'])
        result = score_texts([row], {'fake':'ЗОХИОМОЛ багш З.Нарин энд.'}, {'fake':annotation}, ['З.Наран'])
        self.assertEqual(result['error_categories']['name'], 1)
        self.assertEqual(result['error_categories']['school_term'], 0)
        self.assertEqual(result['school_term_errors'], [])

    def test_representation_change_can_lose_literal_span_but_preserve_value(self):
        row = dict(id='fake', reference='ЗОХИОМОЛ дөрвөн давхар.',
                   critical_slots=[dict(field='floor', expected='дөрвөн')])
        normalizer = Normalizer(enabled=True)
        d = normalizer.normalize(row['reference'])
        a = {'fake':annotate_reference(row['reference'], row['critical_slots'], [])}
        before = score_texts([row], {'fake':row['reference']}, a, [])
        after = score_texts([row], {'fake':d['normalized_search_text']}, a, [])
        metrics = {arm+phase:value for arm in ('baseline','vocabulary')
                   for phase,value in (('_raw',before),('_normalized',after))}
        result = post_analysis(metrics, {arm:{'fake':d} for arm in ('baseline','vocabulary')})
        self.assertEqual(result['vocabulary']['lost_literal_slot_fields'], {'floor':1})
        self.assertEqual(result['vocabulary']['numeric_values_preserved'], 1)
        self.assertEqual(result['vocabulary']['numeric_replacements'], 1)

    def test_correct_inflection_and_initial_fragment_are_not_term_errors(self):
        row=dict(id='fake',reference='ЗОХИОМОЛ лабораторийн өрөө.',critical_slots=[])
        ann=annotate_reference(row['reference'],[],['лаборатори','З.Наран'])
        result=score_texts([row],{'fake':row['reference']+' з'},{'fake':ann},['лаборатори','З.Наран'])
        self.assertEqual(result['school_term_values']['found'],1)
        self.assertEqual(result['error_categories']['other'],1)
        self.assertEqual(result['school_term_errors'],[])

    def test_output_must_be_private_runtime(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(output_path(Path(folder), 'runtime/FAKE'), Path(folder).resolve() / 'runtime/FAKE')
            for value in ('runtime', 'papers/FAKE', '../FAKE'):
                with self.assertRaises(ValueError):
                    output_path(Path(folder), value)

    def test_exception_cannot_print_fake_private_text(self):
        output = io.StringIO()
        with patch.object(sys, 'argv', ['evaluate', 'prepare']), patch(
                'tools.evaluate_stt_normalization.install_guard', return_value={}), patch(
                'tools.evaluate_stt_normalization.prepare', side_effect=ValueError('FAKE PRIVATE SENTENCE')):
            with redirect_stdout(output):
                self.assertEqual(main(), 1)
        self.assertNotIn('FAKE PRIVATE SENTENCE', output.getvalue())
        self.assertEqual(json.loads(output.getvalue())['error_type'], 'ValueError')

    def test_guard_blocks_audio_credentials_network_and_writes(self):
        script = """
import json, pathlib, socket, sys
from tools.evaluate_stt_normalization import install_guard
root = pathlib.Path(sys.argv[1]); hooks = []; original_add = sys.addaudithook
def capture(hook):
    hooks.append(hook); original_add(hook)
sys.addaudithook = capture
counters = install_guard(root)
def network():
    # Exercise this hook directly: an outer test sandbox may reject sockets
    # before our hook gets the event. No actual network operation is needed.
    hooks[0]('socket.connect', (None, ('203.0.113.1',443)))
operations = [network, lambda: open(root/'FAKE.wav','rb'),
              lambda: open(root/'FAKE.dpapi','rb'), lambda: open(root.parent/'FAKE-outside.txt','w')]
for operation in operations:
    try: operation()
    except PermissionError: pass
print(json.dumps(counters))
"""
        with tempfile.TemporaryDirectory() as folder:
            result = subprocess.run([sys.executable,'-B','-X','utf8','-c',script,str(Path(folder)/'allowed')],
                                    capture_output=True,text=True,check=True)
            self.assertEqual(json.loads(result.stdout),dict(network_attempts=1,audio_open_attempts=1,
                credential_open_attempts=1,outside_write_attempts=1,blocked_subprocess_attempts=0))
            self.assertFalse((Path(folder) / 'FAKE-outside.txt').exists())


if __name__ == '__main__':
    unittest.main()
