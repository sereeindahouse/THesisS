import copy
import unittest
from tools.validate_answer_cases import validate


SOURCE=dict(source_id='test-source',url='https://nmct.edu.mn/test',version=1,
            source_locator='х.1, тест',text='Ярилцлага 15 минут үргэлжилнэ. Нийт 20 оноо.')


class ReferenceValidationTests(unittest.TestCase):
    def bundle(self):
        return dict(schema_version=1,source_snapshot_sha256='frozen',cases=[dict(
            id='one',query='Ярилцлага хэр удаан вэ?',requested_attribute='duration',
            expected_behavior='15 минут',reference_answerability='answerable',
            label_author='assistant',human_reference_review=False,required_facts=['15 минут'],
            forbidden_claims=[],paraphrase_of='old-duration',source_refs=[dict(
                source_id='test-source',url=SOURCE['url'],version=1,locator='х.1, тест',quote='15 минут')])])

    def test_quotes_become_traceable_offsets_without_mutating_input(self):
        bundle=self.bundle();before=copy.deepcopy(bundle)
        public,summary=validate(bundle,[SOURCE],'frozen')
        ref=public['cases'][0]['source_refs'][0]
        self.assertEqual(SOURCE['text'][ref['quote_start']:ref['quote_end']],'15 минут')
        self.assertNotIn('quote',ref)
        self.assertEqual(bundle,before)
        self.assertFalse(summary['independent_human_reference'])
        self.assertEqual(summary['known_task_paraphrases'],1)

    def test_wrong_corpus_source_quote_or_locator_rejected(self):
        with self.assertRaises(ValueError):validate(self.bundle(),[SOURCE],'different')
        for field,value in [('source_id','other'),('version',2),('url','https://example.org'),
                            ('quote','15 минутын дараа дүн гарна'),('locator','х.2')]:
            bundle=self.bundle();bundle['cases'][0]['source_refs'][0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):validate(bundle,[SOURCE],'frozen')

    def test_duplicate_query_and_missing_answerable_evidence_rejected(self):
        bundle=self.bundle();bundle['cases'].append(dict(copy.deepcopy(bundle['cases'][0]),id='two'))
        with self.assertRaises(ValueError):validate(bundle,[SOURCE],'frozen')
        bundle=self.bundle();bundle['cases'][0]['source_refs']=[]
        with self.assertRaises(ValueError):validate(bundle,[SOURCE],'frozen')

    def test_unsupported_case_does_not_turn_into_human_gold(self):
        bundle=self.bundle();case=bundle['cases'][0]
        case.update(reference_answerability='unsupported_in_verified_passages',source_refs=[],required_facts=[])
        _,summary=validate(bundle,[SOURCE],'frozen')
        self.assertFalse(summary['semantic_reference_correctness_validated'])
        self.assertFalse(summary['held_out_evaluation'])
        case['human_reference_review']=True
        with self.assertRaises(ValueError):validate(bundle,[SOURCE],'frozen')

    def test_html_locator_is_derived_from_actual_page_offsets(self):
        source=dict(SOURCE,source_locator=None,text_scope='main_element',chunk_id=2,start_offset=80,end_offset=180)
        bundle=self.bundle()
        bundle['cases'][0]['source_refs'][0]['locator']='main_element; chunk_id=2; page_char_offsets=80:180'
        public,_=validate(bundle,[source],'frozen')
        self.assertIn('80:180',public['cases'][0]['source_refs'][0]['locator'])
        bundle['cases'][0]['source_refs'][0]['locator']='main_element; chunk_id=2; page_char_offsets=0:100'
        with self.assertRaises(ValueError):validate(bundle,[source],'frozen')
