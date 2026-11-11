import json
import unittest
from unittest.mock import patch

import test_website_retrieval
from website_retrieval import predict_domain

DOMAINS = {
    'admissions': {'keywords': ['элсэлт', 'төлбөр']},
    'career': {'keywords': ['дадлага', 'карьер']},
    'location': {'keywords': ['давхар', 'өрөө']},
    'staff': {'keywords': ['багш']},
}


class PredictDomainTests(unittest.TestCase):
    def test_single_domain_with_case_endings(self):
        self.assertEqual(predict_domain('Элсэлтийн төлбөр хэд вэ?', DOMAINS), 'admissions')

    def test_broad_question_tie_gets_no_domain(self):
        self.assertIsNone(predict_domain('Ямар сургууль вэ, хэдэн давхар, ямар багш нар байдаг вэ?', DOMAINS))

    def test_no_keyword_no_domain(self):
        self.assertIsNone(predict_domain('Сайн байна уу?', DOMAINS))

    def test_keyword_must_start_a_word(self):
        self.assertIsNone(predict_domain('Ахлагч хэн бэ?', {'staff': {'keywords': ['лагч']}}))


class DomainBoostRankingTests(unittest.TestCase):
    """Option Б reorders already-scored pages and never hides another domain."""

    def setUp(self):
        self.helper = test_website_retrieval.RetrievalTests()
        self.helper.setUp()
        self.addCleanup(self.helper.tearDown)
        self.root, self.retriever = self.helper.root, self.helper.retriever
        (self.root / 'config').mkdir(exist_ok=True)
        self.write_config(enabled=False)
        (self.root / 'config/knowledge-topics.json').write_text(json.dumps({'url_rules': [
            {'path_prefix': '/elseltiin-juram', 'topic_id': 'admissions.rules'},
            {'exact_path': '/career', 'topic_id': 'career'}]}), encoding='utf-8')
        self.helper.inject_rows([
            dict(source_id='career', url='https://nmct.edu.mn/career', title='Карьер',
                 text='Дадлагын төлбөр. Төлбөр тооцоо. Төлбөр.', start_offset=0, end_offset=40),
            dict(source_id='admissions', url='https://nmct.edu.mn/elseltiin-juram/2026', title='Журам',
                 text='Журам: төлбөр.', start_offset=1000, end_offset=1040)])

    def write_config(self, enabled, weight=0.5):
        (self.root / 'config/knowledge-domains.json').write_text(json.dumps(
            {'enabled': enabled, 'weight': weight, 'domains': DOMAINS}), encoding='utf-8')

    def ranked(self, query, **options):
        with patch.object(self.retriever, '_dense', return_value=[.99, .1]):
            result = self.retriever.search(query, **options)
        return result, [row['source_id'] for row in result['candidates']]

    def test_off_by_default_keeps_the_original_order(self):
        result, order = self.ranked('Төлбөр хэд вэ?')
        self.assertFalse(result['domain_boost'])
        self.assertIsNone(result['predicted_domain'])
        self.assertEqual(order[0], 'career')

    def test_boost_lifts_the_domain_page_without_removing_others(self):
        before = self.ranked('Төлбөр хэд вэ?', domain_boost=False)[1]
        result, after = self.ranked('Төлбөр хэд вэ?', domain_boost=True)
        self.assertEqual(before[0], 'career')
        self.assertEqual(result['predicted_domain'], 'admissions')
        self.assertEqual(after[0], 'admissions')
        self.assertEqual(sorted(before), sorted(after))

    def test_config_switch_turns_the_boost_on(self):
        self.write_config(enabled=True)
        result, order = self.ranked('Төлбөр хэд вэ?')
        self.assertTrue(result['domain_boost'])
        self.assertEqual(order[0], 'admissions')

    def test_unknown_domain_changes_nothing(self):
        result, order = self.ranked('Тооцоо хэд вэ?', domain_boost=True)
        self.assertIsNone(result['predicted_domain'])
        self.assertEqual(order, self.ranked('Тооцоо хэд вэ?', domain_boost=False)[1])

    def test_boost_does_not_bypass_the_topic_gate(self):
        # The career page has a high dense score but none of the query words.
        result, order = self.ranked('Элсэлтийн журам', domain_boost=True)
        self.assertEqual(result['predicted_domain'], 'admissions')
        self.assertNotIn('career', order)


if __name__ == '__main__':
    unittest.main()
