"""The referral layer adds "where to ask" only to unanswered results."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from referral import attach_referral, load_referral, load_topic_rules, topic_of  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RULES = [{'exact_path': '/elselt', 'topic_id': 'admissions'},
         {'path_prefix': '/career', 'topic_id': 'career'}]
REFERRAL = {'enabled': True, 'general': {'text_mn': 'Ресепшнээс асууна уу.', 'source': {'url': 'x'}},
            'topic_offices': {'approved': False, 'map': {'admissions': 'Сургалтын алба'}}}


class ReferralTest(unittest.TestCase):
    def test_unanswered_result_gets_general_referral_in_message(self):
        result = attach_referral({'answer': None, 'message': 'Олдсонгүй.'}, REFERRAL)
        self.assertEqual(result['message'], 'Олдсонгүй. Ресепшнээс асууна уу.')
        self.assertIsNone(result['referral']['office'])

    def test_answered_or_clarifying_results_are_unchanged(self):
        answered = {'answer': 'Тийм.', 'message': None}
        self.assertNotIn('referral', attach_referral(dict(answered), REFERRAL))
        clarifying = {'answer': None, 'clarification': {'question': 'Аль хөтөлбөр?'}, 'message': ''}
        self.assertNotIn('referral', attach_referral(dict(clarifying), REFERRAL))

    def test_office_named_only_after_school_approval(self):
        result = {'answer': None, 'message': '', 'related_sources': [{'url': 'https://nmct.edu.mn/elselt'}]}
        self.assertIsNone(attach_referral(dict(result), REFERRAL, rules=RULES)['referral']['office'])
        approved = dict(REFERRAL, topic_offices=dict(REFERRAL['topic_offices'], approved=True))
        out = attach_referral(dict(result), approved, rules=RULES, locate=lambda name: '406 өрөө, 4-р давхар')
        self.assertEqual(out['referral']['office'], 'Сургалтын алба (406 өрөө, 4-р давхар)')
        self.assertTrue(out['message'].startswith('Энэ сэдвийг хариуцсан нэгж: Сургалтын алба'))

    def test_topic_rules_and_project_config(self):
        self.assertEqual(topic_of('https://nmct.edu.mn/career/jobs?page=2', RULES), 'career')
        self.assertIsNone(topic_of('https://nmct.edu.mn/unknown', RULES))
        config = load_referral(ROOT)
        self.assertIsNotNone(config)
        self.assertIs(config['topic_offices']['approved'], False)  # school has not approved offices
        self.assertTrue(load_topic_rules(ROOT))
        self.assertIsNone(load_referral(ROOT / 'missing'))


if __name__ == '__main__':
    unittest.main()
