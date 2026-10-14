import unittest
from unittest.mock import patch
import test_website_retrieval as retrieval_tests


class AblationTests(unittest.TestCase):
    def setUp(self):
        self.helper = retrieval_tests.RetrievalTests()
        self.helper.setUp()
        self.retriever = self.helper.retriever

    def tearDown(self):
        self.helper.tearDown()

    def test_bm25_never_loads_or_calls_dense_encoder(self):
        with patch.object(self.retriever, '_dense', side_effect=AssertionError('must not load E5')):
            result = self.retriever.search('сургалтын төлбөр', mode='bm25')
        self.assertEqual(len(result['candidates']), 1)
        self.assertEqual(result['candidates'][0]['score'], result['candidates'][0]['lexical_score'])

    def test_e5_and_fusion_fail_instead_of_silently_falling_back(self):
        with patch.object(self.retriever, '_dense', return_value=None):
            for mode in ['e5', 'rrf', 'rrf_boosted']:
                with self.subTest(mode=mode), self.assertRaises(RuntimeError):
                    self.retriever.search('сургалтын төлбөр', mode=mode)
            self.assertTrue(self.retriever.search('сургалтын төлбөр')['candidates'])

    def test_rank_only_dense_can_return_irrelevant_neighbor_but_production_filters(self):
        with patch.object(self.retriever, '_dense', return_value=[.99]):
            dense = self.retriever.search('Ангараг муур', mode='e5')
            self.assertEqual(len(dense['candidates']), 1)
            self.assertFalse(dense['query_answer_support_established'])
            self.assertFalse(self.retriever.search('Ангараг муур')['candidates'])

    def test_ranking_mode_cannot_change_source_eligibility(self):
        self.helper.mutate("UPDATE pages SET valid_until='2000-01-01'")
        with patch.object(self.retriever, '_dense', return_value=[]):
            self.assertFalse(self.retriever.search('төлбөр', mode='bm25')['candidates'])
            # An empty corpus cannot become an evaluated E5 result.
            with self.assertRaises(RuntimeError): self.retriever.search('төлбөр', mode='e5')

    def test_explicit_production_matches_default(self):
        with patch.object(self.retriever, '_dense', return_value=[.6]):
            default = self.retriever.search('сургалтын төлбөр')
            explicit = self.retriever.search('сургалтын төлбөр', mode='production')
            self.assertEqual(default['candidates'], explicit['candidates'])

    def test_e5_score_is_not_discarded_just_because_zero(self):
        with patch.object(self.retriever, '_dense', return_value=[0.]):
            result = self.retriever.search('Ангараг', mode='e5')
        self.assertEqual(len(result['candidates']), 1)
        self.assertEqual(result['candidates'][0]['score'], 0.)

    def test_unknown_mode_rejected(self):
        with self.assertRaises(ValueError): self.retriever.search('төлбөр', mode='made_up')


if __name__ == '__main__': unittest.main()
