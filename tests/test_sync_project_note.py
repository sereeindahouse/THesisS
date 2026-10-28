"""Constructed note/workspace fixtures; no model, source DB or user data."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import sync_project_note as syncer


class SyncProjectNoteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'CORE').mkdir()
        (self.root / 'config').mkdir()
        self.config = dict(schema_version=1, status_basis='Recorded fixture checks; no accuracy claim.',
            plan_status=dict(current=dict(week_id='W01', status_label='Working', next=['One next action.'])),
            project_note=dict(schema_version=1, updated_date='2026-10-29', current_focus='III · Жишээ тэмдэглэл',
                status_label='Recorded current work', active_workstream='III',
                verified_code_commit='a' * 40,
                workstreams=[dict(id=identity, state=state, status_label='Status ' + identity,
                    detail='Fixture detail') for identity, state in [('I', 'verified_pack'), ('II', 'next'), ('III', 'active')]]))
        sections = '# Fixture plan\n\n## Дипломын 3 үндсэн хэсэг\n\n'
        for identity in ('I', 'II', 'III'):
            sections += ('### ' + identity + ' · Үр дүн ' + identity + '\n\n'
                '- **Үр дүн:** Fixture goal\n- **Дэд ажил:** Fixture work\n'
                '- **Дуусах шалгуур:** Fixture evidence\n\n')
        sections += ('## Долоо хоног ба үндсэн хэсгийн холбоо\n\n'
            '| Долоо хоног | Үндсэн хэсэг |\n|---|---|\n| W01 | I, II, III |\n\n'
            '### W01 · 2026.10.26–11.01 — Fixture\n\n- **Хийх:** One work item.\n')
        (self.root / 'CORE/WEEKLY-PLAN-2026-2027.mn.md').write_text(sections, encoding='utf-8')
        self.note = self.root / syncer.NOTE
        self.note.write_bytes(b'\xef\xbb\xbf# Manual opening\r\n\r\n' + syncer.START.encode()
            + b'\r\nstale snapshot\r\n' + syncer.END.encode() + b'\r\n\r\nManual decisions remain.\r\n')
        self.workspace = self.root / syncer.WORKSPACE
        self.workspace_data = dict(folders=[dict(name='Fixture folder', path='..')],
            settings={'files.exclude': {'**/models': True},
                'editor.fontSize': 17,
                'workbench.colorCustomizations': {'editor.background': '#101010'}})
        self.workspace.write_text(json.dumps(self.workspace_data), encoding='utf-8')
        self.write_config()

    def write_config(self):
        (self.root / syncer.CONFIG).write_text(json.dumps(self.config, ensure_ascii=False), encoding='utf-8')

    def bytes(self):
        return self.note.read_bytes(), self.workspace.read_bytes()

    def test_sync_preserves_manual_text_bom_crlf_folders_and_unrelated_settings(self):
        before = self.note.read_bytes()
        result = syncer.sync(self.root)
        self.assertEqual(result['changed'], [syncer.NOTE, syncer.WORKSPACE])
        after = self.note.read_bytes()
        self.assertEqual(before.split(syncer.START.encode())[0], after.split(syncer.START.encode())[0])
        self.assertEqual(before.split(syncer.END.encode())[1], after.split(syncer.END.encode())[1])
        self.assertNotIn(b'\n', after.replace(b'\r\n', b''))
        self.assertIn('2026-10-29'.encode(), after)
        self.assertIn('One next action.'.encode(), after)
        self.assertIn('a' * 40, after.decode('utf-8-sig'))
        workspace = json.loads(self.workspace.read_text(encoding='utf-8'))
        self.assertEqual(workspace['folders'], self.workspace_data['folders'])
        self.assertEqual(workspace['settings']['files.exclude'], {'**/models': True})
        self.assertEqual(workspace['settings']['editor.fontSize'], 17)
        self.assertEqual(workspace['settings']['workbench.colorCustomizations']['editor.background'], '#101010')
        self.assertIn('[THesisS · III]', workspace['settings']['window.title'])
        self.assertEqual(workspace['settings']['workbench.colorCustomizations']['statusBar.background'], '#44316A')

    def test_check_is_read_only_and_reports_stale_then_synced(self):
        before = self.bytes()
        checked = syncer.sync(self.root, check=True)
        self.assertFalse(checked['synced'])
        self.assertTrue(checked['check'])
        self.assertEqual(before, self.bytes())
        syncer.sync(self.root)
        before = self.bytes()
        self.assertTrue(syncer.sync(self.root, check=True)['synced'])
        self.assertEqual(before, self.bytes())

    def test_second_write_is_idempotent_and_does_not_rewrite_files(self):
        syncer.sync(self.root)
        with patch.object(syncer, '_replace', side_effect=AssertionError('Unexpected rewrite')):
            result = syncer.sync(self.root)
        self.assertEqual(result['changed'], [])

    def test_missing_duplicate_reversed_or_inline_markers_fail_without_writes(self):
        for note in ('No markers', syncer.START + '\n' + syncer.START + '\n' + syncer.END,
                     syncer.END + '\n' + syncer.START,
                     'prefix ' + syncer.START + '\n' + syncer.END,
                     syncer.START + '\n' + syncer.END + ' suffix'):
            with self.subTest(note=note):
                self.note.write_text(note, encoding='utf-8')
                before = self.bytes()
                with self.assertRaises(ValueError):
                    syncer.sync(self.root)
                self.assertEqual(before, self.bytes())

    def test_invalid_metadata_or_workspace_cannot_partially_update_note(self):
        valid = deepcopy(self.config)
        changes = [('active_workstream', 'IV'), ('current_focus', 'line\nnext'),
                   ('current_focus', '${env:HOME}'), ('current_focus', 'x' * 701),
                   ('updated_date', '2026-02-30'), ('updated_date', '2026-1-1'),
                   ('verified_code_commit', 'not a SHA')]
        for key, value in changes:
            with self.subTest(key=key, value=value):
                self.config = deepcopy(valid)
                self.config['project_note'][key] = value
                self.write_config()
                before = self.bytes()
                with self.assertRaises(ValueError):
                    syncer.sync(self.root)
                self.assertEqual(before, self.bytes())
        self.config = valid
        self.write_config()
        for settings in ([], {'workbench.colorCustomizations': []}):
            with self.subTest(settings=settings):
                self.workspace.write_text(json.dumps(dict(settings=settings)), encoding='utf-8')
                before = self.bytes()
                with self.assertRaises(ValueError):
                    syncer.sync(self.root)
                self.assertEqual(before, self.bytes())

    def test_missing_canonical_goals_does_not_generate_apparent_complete_status(self):
        (self.root / 'CORE/WEEKLY-PLAN-2026-2027.mn.md').write_text(
            '# Legacy\n\n### W01 · 2026.10.26–11.01 — First\n\n- **Хийх:** Work\n', encoding='utf-8')
        before = self.bytes()
        with self.assertRaises(ValueError):
            syncer.sync(self.root)
        self.assertEqual(before, self.bytes())

    def test_configured_paths_and_links_are_not_opened_or_injected_into_snapshot(self):
        self.config['project_note'].update(note_path='../private-transcript.txt', note_url='file:///private-token',
            workspace_path='../other-workspace.json', token='not-public')
        self.write_config()
        result = syncer.sync(self.root)
        self.assertTrue(result['synced'])
        self.assertNotIn('private-transcript', self.note.read_text(encoding='utf-8-sig'))
        self.assertNotIn('private-token', self.note.read_text(encoding='utf-8-sig'))
        self.assertNotIn('not-public', self.note.read_text(encoding='utf-8-sig'))

    def test_write_failure_restores_already_written_note(self):
        before = self.bytes()
        replace = syncer._replace
        calls = []

        def fail_second(path, content):
            calls.append(path)
            if len(calls) == 2:
                raise OSError('Constructed second-file failure')
            replace(path, content)

        with patch.object(syncer, '_replace', side_effect=fail_second):
            with self.assertRaises(OSError):
                syncer.sync(self.root)
        self.assertEqual(before, self.bytes())
        self.assertEqual(len(calls), 3)
        self.assertEqual(list((self.root / 'CORE').glob('.project-note-*')), [])

    def test_phase_colours_are_distinct_and_only_the_recorded_phase_is_named(self):
        seen = set()
        for phase in ('I', 'II', 'III'):
            self.config['project_note']['active_workstream'] = phase
            self.write_config()
            syncer.sync(self.root)
            workspace = json.loads(self.workspace.read_text(encoding='utf-8'))
            seen.add(workspace['settings']['workbench.colorCustomizations']['titleBar.activeBackground'])
            self.assertIn('[THesisS · ' + phase + ']', workspace['settings']['window.title'])
        self.assertEqual(len(seen), 3)


if __name__ == '__main__':
    unittest.main()
