import json
from pathlib import Path
import tempfile
import unittest

from evidence_contract import evidence_units
from tools.evaluate_llm_selection import (lexical_selection, common_render, slot_screen,
    blind_forms, digest, save_new)


def source(text):
    return dict(source_id='web-fixture',text=text,url='https://nmct.edu.mn/fixture',
        title='Туршилтын эх',version='fixture-v1')


class SelectorComparisonTests(unittest.TestCase):
    def test_lexical_selector_never_sees_reference_and_positive_only(self):
        units=evidence_units([source('Номын сан ажлын өдрүүдэд нээлттэй.\nХимийн лаборатори туршилтад зориулагдсан.')])
        result=lexical_selection('Номын сан ямар өдрүүдэд нээлттэй вэ?',units,1)
        self.assertEqual(result['selected_unit_ids'],[units[0]['unit_id']])
        self.assertEqual(result['llm_calls'],0)
        self.assertEqual(lexical_selection('Боржин чулуу',units,1)['selected_unit_ids'],[])

    def test_top_three_is_bounded_and_shared_render_can_reject_excess(self):
        units=evidence_units([source('\n'.join(f'Номын сангийн туршилтын хэсэг {i} нээлттэй.' for i in range(5)))])
        result=lexical_selection('Номын сан нээлттэй юу?',units,3)
        self.assertEqual(len(result['selected_unit_ids']),3)
        self.assertEqual(common_render('Номын сан',result['selected_unit_ids']+[units[4]['unit_id']],units)['reason'],'selector_exceeds_three_units')

    def test_unknown_ids_and_tampered_exact_spans_fail_shared_contract(self):
        units=evidence_units([source('Номын сан ажлын өдрүүдэд нээлттэй.')])
        self.assertFalse(common_render('Номын сан', ['fabricated'], units)['accepted'])
        units[0]['text']='Өөр мэдээлэл.'
        self.assertEqual(common_render('Номын сан',[units[0]['unit_id']],units)['reason'],'invalid_evidence_unit')

    def test_rendered_answer_is_original_quote_and_ref_screen_not_semantics(self):
        units=evidence_units([source('Химийн тэнхимд 5 үндсэн багш, 1 цагийн багш ажилладаг.')])
        result=common_render('Химийн тэнхимийн үндсэн ба цагийн багшийн тоо?', [units[0]['unit_id']],units)
        self.assertTrue(result['accepted'])
        self.assertIn(units[0]['text'],result['answer'])
        screen=slot_screen(dict(required_slots=[dict(name='үндсэн',all_of=['5 үндсэн']),dict(name='дутуу',all_of=['магистр'])]),result)
        self.assertEqual((screen['matched'],screen['total']),(1,2))
        self.assertIsNone(screen['human_correctness']);self.assertFalse(screen['semantic_correctness_proven'])

    def test_missing_requested_numeric_role_rejects_for_either_condition(self):
        units=evidence_units([source('Химийн тэнхимд 5 үндсэн багш ажилладаг.\nХимийн тэнхимд 1 цагийн багш ажилладаг.')])
        result=common_render('Химийн тэнхимийн үндсэн ба цагийн багшийн тоо?', [units[0]['unit_id']],units)
        self.assertFalse(result['accepted'])
        self.assertIn(result['reason'],{'requested_fields_not_in_selection','requested_evidence_markers_missing'})

    def test_blind_package_hides_conditions_and_preserves_null_human_review(self):
        with tempfile.TemporaryDirectory() as directory:
            case=dict(id='x',query='Асуулт?',required_facts=['Эх'],source_refs=[dict(quote='Эх',url='https://nmct.edu.mn/')],
                conditions={'secret_model':dict(common_output=dict(answer='Эх',accepted=True)),
                            'secret_baseline':dict(common_output=dict(answer=None,accepted=False))})
            blind_forms(dict(cases=[case]),'frozen-sha',Path(directory))
            package=json.loads((Path(directory)/'human-review.json').read_text(encoding='utf8'))
            self.assertEqual(len(package['rows']),2)
            self.assertNotIn('secret_model',json.dumps(package))
            self.assertNotIn('secret_baseline',json.dumps(package))
            self.assertTrue(all(row['human_review']['correctness'] is None for row in package['rows']))
            self.assertTrue(all(row['item_sha256']==digest({key:value for key,value in row.items() if key!='item_sha256'}) for row in package['rows']))
            with self.assertRaises(FileExistsError):blind_forms(dict(cases=[case]),'frozen-sha',Path(directory))

    def test_artifacts_refuse_silent_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'first.json';save_new(path,{'original':True})
            with self.assertRaises(FileExistsError):save_new(path,{'original':False})
            self.assertTrue(json.loads(path.read_text())['original'])


if __name__=='__main__':
    unittest.main()
