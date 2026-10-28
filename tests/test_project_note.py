"""Project handoff projection contracts, using constructed metadata only."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from data_explorer import progress
from project_plan import public_plan, public_project_note


NOTE_URL = 'https://github.com/sereeindahouse/THesisS/blob/main/CORE/PROJECT-NOTE.mn.md'


def fixture():
    source = dict(
        status_basis='Verified fixture evidence, not a real project measurement.',
        plan=dict(available=True, current=dict(
            status_label='A bounded pack, not the whole thesis',
            done=['Evidence A', 'Evidence B'],
            in_progress=['Open issue'], human_tasks=['Real approval pending'],
            next=['One next action', 'Later action']),
            workstreams=[dict(id=identity, title='Canonical title ' + identity,
                             goal=['Canonical goal ' + identity])
                         for identity in ('I', 'II', 'III')]))
    metadata = dict(schema_version=1, updated_date='2026-10-29',
        current_focus='Document current progress', status_label='Active documentation',
        workstreams=[dict(id=identity, state=state,
            status_label='Explicit status ' + identity, detail='Bounded detail ' + identity,
            label='Do not replace canonical label') for identity, state in
            [('I', 'verified_pack'), ('II', 'next'), ('III', 'active')]])
    return source, metadata


def canonical_text():
    source = '# Constructed plan\n\n## Дипломын 3 үндсэн хэсэг\n\n'
    for identity in ('I', 'II', 'III'):
        source += (f'### {identity} · Canonical title {identity}\n\n'
                   f'- **Үр дүн:** Canonical goal {identity}\n'
                   '- **Дэд ажил:** A bounded task\n'
                   '- **Дуусах шалгуур:** A real check\n\n')
    return source + ('## Долоо хоног ба үндсэн хэсгийн холбоо\n\n'
        '| Долоо хоног | Хэсэг |\n|---|---|\n| W01 | I, II, III |\n\n'
        '### W01 · 2026.10.26–11.01 — Constructed week\n\n'
        '- **Хийх:** Keep evidence distinct\n- **Гарах:** Reviewable output\n'
        '- **Тэнцэх:** Explicit evidence\n')


class ProjectNoteProjectionTests(unittest.TestCase):
    def test_five_perspectives_derive_from_existing_plan_and_evidence(self):
        source, metadata = fixture()
        before_source, before_metadata = deepcopy(source), deepcopy(metadata)
        result = public_project_note(source, metadata)
        self.assertTrue(result['available'])
        lenses = {item['id']: item for item in result['lenses']}
        self.assertEqual(list(lenses), ['goal', 'current', 'evidence', 'issues', 'next'])
        self.assertEqual(lenses['goal']['items'],
                         ['I · Canonical goal I', 'II · Canonical goal II', 'III · Canonical goal III'])
        self.assertEqual(lenses['evidence']['summary'], source['status_basis'])
        self.assertEqual(lenses['evidence']['items'], source['plan']['current']['done'])
        self.assertEqual(lenses['issues']['items'], ['Open issue', 'Real approval pending'])
        self.assertEqual(lenses['next']['summary'], 'One next action')
        self.assertEqual(lenses['next']['items'], ['Later action'])
        self.assertEqual(result['workstreams'][0]['label'], 'Canonical title I')
        self.assertEqual([item['state'] for item in result['workstreams']],
                         ['verified_pack', 'next', 'active'])
        self.assertNotIn('completion_percentage', result)
        self.assertEqual((source, metadata), (before_source, before_metadata))
        # Replacing the stored evidence and next task must change the view,
        # without editing the renderer or entering a second result table.
        source['status_basis'] = 'Different saved evidence'
        source['plan']['current']['done'] = ['Different completed check']
        source['plan']['current']['next'] = ['Different next action']
        changed = {item['id']: item for item in public_project_note(source, metadata)['lenses']}
        self.assertEqual(changed['evidence']['summary'], 'Different saved evidence')
        self.assertEqual(changed['evidence']['items'], ['Different completed check'])
        self.assertEqual(changed['next']['summary'], 'Different next action')

    def test_projection_never_reads_configured_paths_or_activates_arbitrary_urls(self):
        source, metadata = fixture()
        metadata.update(note_url='file:///private/token', path='../private/reference.json',
                        private_secret='must-not-be-exported')
        metadata['workstreams'][0]['private_secret'] = 'nested-not-exported'
        source['plan']['private_secret'] = 'plan-private-not-exported'
        with patch('builtins.open', side_effect=AssertionError('Projection must not open files')), \
                patch.object(Path, 'read_text', side_effect=AssertionError('Projection must not read paths')):
            result = public_project_note(source, metadata)
        encoded = json.dumps(result)
        self.assertTrue(result['available'])
        self.assertEqual(result['note_url'], NOTE_URL)
        for value in ('file://', '../private/', 'must-not-be-exported',
                      'nested-not-exported', 'plan-private-not-exported'):
            self.assertNotIn(value, encoded)

    def test_text_and_list_bounds_reject_invalid_types_without_model_calls(self):
        source, metadata = fixture()
        metadata['current_focus'] = 'f' * 2000
        metadata['status_label'] = 's' * 800
        metadata['workstreams'][0]['detail'] = 'd' * 2500
        source['status_basis'] = 'e' * 2000
        source['plan']['current'].update(done=['a' * 1800] * 20,
            in_progress=['i' * 1800] * 20, human_tasks=['h' * 1800] * 20,
            next=['n' * 1800] * 20)
        result = public_project_note(source, metadata)
        self.assertEqual(len(result['current_focus']), 700)
        self.assertEqual(len(result['status_label']), 300)
        self.assertEqual(len(result['workstreams'][0]['detail']), 1000)
        lenses = {item['id']: item for item in result['lenses']}
        self.assertEqual(len(lenses['evidence']['summary']), 1000)
        self.assertEqual(len(lenses['evidence']['items']), 3)
        self.assertTrue(all(len(value) == 1000 for value in lenses['evidence']['items']))
        self.assertEqual(len(lenses['issues']['items']), 6)
        self.assertEqual(len(lenses['next']['items']), 4)
        source['plan']['current'] = dict(done='not a list', next={'not': 'a list'},
                                         in_progress=12, human_tasks=[None, 'Real pending item', {}])
        clean = {item['id']: item for item in public_project_note(source, metadata)['lenses']}
        self.assertEqual(clean['evidence']['items'], [])
        self.assertEqual(clean['issues']['items'], ['Real pending item'])

    def test_missing_or_malformed_snapshot_hides_only_optional_note(self):
        source, metadata = fixture()
        for bad in (None, [], 'metadata', {}, dict(metadata, schema_version=2),
                    dict(metadata, schema_version=True), dict(metadata, current_focus=None),
                    dict(metadata, status_label=''), dict(metadata, updated_date='2026-02-30'),
                    dict(metadata, current_focus='hidden\x00control')):
            with self.subTest(metadata=bad):
                self.assertFalse(public_project_note(source, bad)['available'])
        for bad_plan in (None, [], {}, {'available': False}):
            with self.subTest(plan=bad_plan):
                self.assertFalse(public_project_note({'plan': bad_plan}, metadata)['available'])
        self.assertFalse(public_project_note(None, metadata)['available'])

    def test_malformed_workstreams_fail_closed_instead_of_raising(self):
        source, metadata = fixture()
        invalid = [None, {}, [], metadata['workstreams'][:2],
            [metadata['workstreams'][0]] * 3,
            [metadata['workstreams'][1], metadata['workstreams'][0], metadata['workstreams'][2]],
            [None, metadata['workstreams'][1], metadata['workstreams'][2]]]
        for streams in invalid:
            with self.subTest(streams=streams):
                value = deepcopy(metadata)
                value['workstreams'] = streams
                self.assertFalse(public_project_note(source, value)['available'])
        for state in ('complete', 'invented', None, [], {}):
            with self.subTest(state=state):
                value = deepcopy(metadata)
                value['workstreams'][0]['state'] = state
                self.assertFalse(public_project_note(source, value)['available'])
        for extra in (None, [], 'unexpected'):
            with self.subTest(extra_goal=extra):
                value = deepcopy(source)
                value['plan']['workstreams'].insert(0, extra)
                self.assertFalse(public_project_note(value, metadata)['available'])

    def test_legacy_progress_keeps_canonical_plan_without_note_or_models(self):
        source, metadata = fixture()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'CORE').mkdir()
            (root / 'config').mkdir()
            (root / 'CORE/WEEKLY-PLAN-2026-2027.mn.md').write_text(canonical_text(), encoding='utf-8')
            config = dict(schema_version=1, milestones=[], status_basis=source['status_basis'],
                          plan_status=dict(current=dict(week_id='W01', **source['plan']['current'])))
            path = root / 'config/project-progress.json'
            path.write_text(json.dumps(config), encoding='utf-8')
            with patch('website_retrieval._LocalE5.load', side_effect=AssertionError('No model allowed')):
                legacy = progress(root)
            self.assertTrue(legacy['plan']['available'])
            self.assertFalse(legacy['project_note']['available'])
            self.assertEqual(len(legacy['plan']['weeks']), 1)
            config['project_note'] = dict(metadata, private_secret='never-export-this',
                                          note_url='https://evil.example/note')
            path.write_text(json.dumps(config), encoding='utf-8')
            original = path.read_bytes()
            with patch('website_retrieval._LocalE5.load', side_effect=AssertionError('No model allowed')):
                result = progress(root)
            self.assertTrue(result['project_note']['available'])
            self.assertEqual(len(result['project_note']['lenses']), 5)
            self.assertEqual(result['project_note']['note_url'], NOTE_URL)
            self.assertNotIn('never-export-this', json.dumps(result))
            self.assertNotIn('evil.example', json.dumps(result))
            self.assertNotIn('plan_status', result)
            self.assertEqual(path.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
