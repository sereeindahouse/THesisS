import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import prepare_user_study as study


class UserStudyPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runtime = self.root/'runtime'
        self.runtime.mkdir()
        self.source = self.root/'source.json'
        self.sources = [dict(source_id='test-source', url='https://nmct.edu.mn/test',
                             version=1, source_locator='frozen test paragraph',
                             text='Invented fixture: Hall A has 17 seats. Hall B has 23 seats.')]
        self.source.write_text(json.dumps(self.sources), encoding='utf-8')
        self.cases_path = self.root/'cases.json'
        self.bundle = dict(schema_version=1, label_author='assistant', human_reference_review=False,
            prepared_before_current_system_outputs=True, label_scope='Assistant-authored unreviewed fixture',
            source_snapshot_sha256=hashlib.sha256(self.source.read_bytes()).hexdigest(),
            protocol=dict(review_rubric=dict(prepared_before_model_outputs=True,
                markdown='Frozen rubric, not a human result.',
                sha256=hashlib.sha256(b'Frozen rubric, not a human result.').hexdigest())), cases=[])
        for index in range(6):
            self.bundle['cases'].append(dict(id=f'fixture-{index}', query=f'Fixture task {index}?',
                requested_attribute=f'fixture.attribute.{index}', expected_behavior='Report the source-backed role.',
                reference_answerability='answerable', label_author='assistant', human_reference_review=False,
                human_review=None, required_facts=['Hall A has 17 seats.'], forbidden_claims=['17 rooms'],
                source_refs=[dict(source_id='test-source', url=self.sources[0]['url'], version=1,
                    locator='frozen test paragraph', quote='Hall A has 17 seats.')]))
        self.save()
        self.patcher = patch.object(study, 'ROOT', self.root)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def save(self):
        self.cases_path.write_text(json.dumps(self.bundle), encoding='utf-8')

    def prepare(self, name='prepared', participants=None, **kwargs):
        return study.prepare(self.cases_path, self.source, self.runtime/name,
                             participants or ['P001', 'P002', 'P003'], 71, **kwargs)

    def read(self, name, directory='prepared'):
        return json.loads((self.runtime/directory/name).read_text(encoding='utf-8'))

    def test_every_person_sees_each_case_once_and_each_case_rotates_conditions(self):
        self.prepare(tasks_per_session=2)
        rows = self.read('linkage.private.json')['rows']
        for participant in ('P001', 'P002', 'P003'):
            own = [r for r in rows if r['participant_id'] == participant]
            self.assertEqual(len(own), 6)
            self.assertEqual(len({r['case_id'] for r in own}), 6)
            self.assertEqual(sorted(r['condition'] for r in own), sorted(study.CONDITIONS*2))
        for case in self.bundle['cases']:
            self.assertEqual({r['condition'] for r in rows if r['case_id'] == case['id']}, set(study.CONDITIONS))
        tasks = self.read('participant.forms.json')['participants'][0]['tasks']
        self.assertEqual([t['session'] for t in tasks], [1, 1, 2, 2, 3, 3])

    def test_materials_have_no_results_and_participant_does_not_see_answer_key(self):
        before = copy.deepcopy(self.bundle)
        report = self.prepare()
        self.assertEqual(self.bundle, before)
        self.assertEqual(report['actual_participants'], 0)
        self.assertEqual(report['completed_trials'], 0)
        self.assertIsNone(report['sample_size_justification'])
        self.assertIsNone(report['recruitment_target_n'])
        self.assertTrue(report['preparation_slots_only'])
        self.assertFalse(report['teacher_approved_design'])
        participant_text = (self.runtime/'prepared/participant.forms.json').read_text(encoding='utf-8')
        self.assertNotIn('17 seats', participant_text)
        self.assertNotIn('required_facts', participant_text)
        for trial in self.read('facilitator.forms.json')['trials']:
            self.assertEqual(trial['status'], 'not_started')
            self.assertTrue(all(v is None for v in trial['timing_events_ms'].values()))
            self.assertIsNone(trial['actual_input']['human_listened_utterance_reference'])
            self.assertIsNone(trial['actual_input']['human_reference_confirmed'])
            self.assertIsNone(trial['actual_input']['raw_stt'])
            self.assertIsNone(trial['actual_input']['explicit_edit_confirmed'])
            self.assertIsNone(trial['tts_listening']['human_listened'])
            self.assertIsNone(trial['task_success']['facilitator_judgment'])

    def test_blind_review_omits_condition_participant_model_route_but_keeps_sources(self):
        self.prepare()
        blind = self.read('blind-review.forms.json')
        forbidden = {'participant_id', 'condition', 'route', 'model', 'trial_id', 'case_id'}
        def assert_blind(value):
            if isinstance(value, dict):
                self.assertFalse(forbidden.intersection(value))
                for child in value.values():
                    assert_blind(child)
            elif isinstance(value, list):
                for child in value:
                    assert_blind(child)
        assert_blind(blind)
        self.assertEqual(len({r['review_id'] for r in blind['cases']}), 18)
        for row in blind['cases']:
            self.assertIsNone(row['actual_answer'])
            self.assertEqual(row['frozen_source_refs'][0]['quote'], 'Hall A has 17 seats.')
            self.assertIsNone(row['required_facts'][0]['judgment'])
            self.assertTrue(all(v is None for v in row['human_review']['dimensions'].values()))

    def test_generated_consent_protocol_explains_local_audio_and_online_listen_text(self):
        self.prepare()
        protocol = (self.runtime/'prepared/protocol.mn.md').read_text(encoding='utf-8')
        self.assertIn('локал серверт Whisper боловсруулна', protocol)
        self.assertIn('«Сонсох» үйлдэл ашиглах үед', protocol)
        self.assertIn('синтезийн текст, сонгосон voice/хэлний тохиргоо онлайн Edge/Microsoft TTS', protocol)
        self.assertIn('бүрэн офлайн гэж танилцуулахгүй', protocol)
        participant = self.read('participant.forms.json')['participants'][0]
        self.assertIsNone(participant['consent'])
        self.assertIsNone(participant['audio_storage_consent'])

    def test_fabricated_review_output_or_asr_derived_reference_rejected_before_reserving(self):
        for key, value in [('human_review', {'correctness': 'pass'}),
                           ('response', {'answer': 'made up'}),
                           ('stt_generated_reference', 'hypothesis promoted to gold'),
                           ('transcript', 'model transcript')]:
            with self.subTest(key=key):
                original = copy.deepcopy(self.bundle)
                self.bundle['cases'][0][key] = value
                self.save()
                with self.assertRaisesRegex(ValueError, 'not results/transcript-derived gold'):
                    self.prepare()
                self.assertFalse((self.runtime/'prepared').exists())
                self.bundle = original

    def test_duplicate_case_query_and_mismatched_source_or_rubric_rejected(self):
        mutations = [
            lambda b: b['cases'][1].update(id=b['cases'][0]['id']),
            lambda b: b['cases'][1].update(query='  FIXTURE   TASK 0?  '),
            lambda b: b['cases'][0]['source_refs'][0].update(quote='Hall A has 18 seats.'),
            lambda b: b['protocol']['review_rubric'].update(markdown='Post-output changed rubric'),
            lambda b: b.update(human_reference_review=True),
        ]
        initial = copy.deepcopy(self.bundle)
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.bundle = copy.deepcopy(initial)
                mutation(self.bundle)
                self.save()
                with self.assertRaises(ValueError):
                    self.prepare()
                self.assertFalse((self.runtime/'prepared').exists())

    def test_manifest_matches_read_input_and_created_files_and_reproducible_schedule(self):
        manifest = self.prepare()
        self.assertEqual(manifest['cases_sha256'], hashlib.sha256(self.cases_path.read_bytes()).hexdigest())
        self.assertEqual(manifest['source_snapshot_sha256'], hashlib.sha256(self.source.read_bytes()).hexdigest())
        for name, artifact in manifest['artifacts'].items():
            data = (self.runtime/'prepared'/name).read_bytes()
            self.assertEqual(artifact['sha256'], hashlib.sha256(data).hexdigest())
        self.prepare(name='prepared-again')
        self.assertEqual(self.read('linkage.private.json'), self.read('linkage.private.json', 'prepared-again'))
        with self.assertRaises(FileExistsError):
            self.prepare()

    def test_privacy_pseudonyms_bounds_and_private_directory_enforced(self):
        for participants in (['P001', 'P001'], ['PersonalFullName'], ['P01'], []):
            with self.subTest(participants=participants), self.assertRaises(ValueError):
                study.prepare(self.cases_path, self.source, self.runtime/'bad', participants, 71)
        with self.assertRaises(ValueError):
            study.prepare(self.cases_path, self.source, self.root/'public', ['P001'], 71)
        with self.assertRaises(ValueError):
            self.prepare(tasks_per_session=0)


if __name__ == '__main__':
    unittest.main()
