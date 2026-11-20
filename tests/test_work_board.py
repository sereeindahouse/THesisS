"""Work board (/work): one board file plus live reads; only the board and unlocked drafts are written."""
from datetime import date
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import work_board
import test_demo_server as server_fixture

REPO = Path(__file__).resolve().parents[1]
TODAY = date(2026, 11, 20)

PLAN = '''# План

### W01 · 2026.11.16–11.22 — Шалгах асуулт

- **Хийх:** асуулт бичих
- **Гарах:** багц

### W02 · 2026.11.23–11.29 — Үзлэгийн материал

- **Хийх:** слайд
'''

BOARD = {
    'schema_version': 1,
    'week': {'week_id': 'W01', 'updated': '2026-11-20', 'headline_mn': 'Товч', 'parts': [],
             'report': {'promised': [{'text_mn': 'Шалгах асуулт', 'state': 'done'}, {'text_mn': 'SQuAD унших', 'state': 'todo'}],
                         'next_mn': ['Үзлэгийн слайд']},
             'ahead': {'done_mn': ['Алдаа зассан'], 'problems_mn': ['Хариулт богино'], 'next_mn': ['Дэлгэрүүлэх']}},
    'seminar': {'weekday': 1, 'time': '15:00', 'until': '2026-12-25'},
    'milestones': [{'date': '2026-12-01', 'label': 'Үзлэг №1'}, {'date': '2026-11-01', 'label': 'Өнгөрсөн'}],
    'months': [{'month': '2026-11', 'label': '11-р сар', 'goal': 'Зорилт'}],
    'evaluation': {'problem_mn': 'Асуудал', 'results': [
        {'set': 'system', 'path': 'data/eval/system-questions-draft-20261117.json', 'date': '2026-11-19', 'text_mn': '3-аас 2'}]},
    'figures': [{'name': 'Зураг', 'file': 'thesis/Figures/x.tex', 'thesis': '1.1', 'slide': '6'}],
    'items': [
        {'id': 'T1117-1', 'kind': 'teacher', 'date': '2026-11-17', 'about': 'ppt', 'from_mn': 'Багш',
         'said_mn': 'Үгийг зас.', 'action_mn': 'Зассан.', 'status': 'done',
         'evidence': [{'text_mn': 'Слайд 6', 'path': 'x.pptx'}], 'log': []},
        {'id': 'A1120-1', 'kind': 'audit', 'date': '2026-11-20', 'about': 'thesis', 'from_mn': 'Агент',
         'said_mn': 'Зөрүү.', 'action_mn': 'Засах.', 'status': 'open', 'evidence': [], 'log': []},
    ],
}

DRAFT = {'schema_version': 1, 'status': 'draft', 'questions': [
    {'id': 'F01', 'split': 'tune', 'kind': 'answerable', 'query': 'Төлбөр хэд вэ?', 'required_values': ['8,280,000'],
     'source_url': 'https://nmct.edu.mn/elselt'},
    {'id': 'U01', 'split': 'test', 'kind': 'unanswerable', 'query': 'Цаг агаар ямар вэ?', 'expect': 'abstain'},
]}
LOCKED = {'schema_version': 1, 'status': 'locked', 'lock_kind': 'assistant_at_user_instruction',
          'locked_at': '2026-11-03T16:00:00+00:00', 'questions': [
              {'id': 'A01', 'kind': 'answerable', 'query': 'Зорилго юу вэ?', 'answer_mn': 'Инженер бэлдэх.',
               'required_values': ['инженер'], 'support': [{'url': 'https://nmct.edu.mn/about', 'phrase': 'инженер'}]}]}


def make_root(folder):
    root = Path(folder)
    for name in ('CORE', 'data/eval', 'config'):
        (root / name).mkdir(parents=True, exist_ok=True)
    (root / 'CORE/WEEKLY-PLAN-2026-2027.mn.md').write_text(PLAN, encoding='utf-8')
    (root / work_board.BOARD).write_text(json.dumps(BOARD, ensure_ascii=False), encoding='utf-8')
    (root / 'data/eval/system-questions-draft-20261117.json').write_text(json.dumps(DRAFT, ensure_ascii=False), encoding='utf-8')
    (root / 'data/rag-locked-questions-20261102.json').write_text(json.dumps(LOCKED, ensure_ascii=False), encoding='utf-8')
    return root


class WorkBoardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = make_root(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def sha(self, key='system'):
        return next(row['sha'] for row in work_board.snapshot(self.root, today=TODAY)['question_sets'] if row['key'] == key)

    def test_snapshot_reads_week_dates_sets_and_structure_live(self):
        view = work_board.snapshot(self.root, today=TODAY)
        self.assertEqual(view['week']['id'], 'W01')
        self.assertEqual(view['stale_mn'], '')
        # Friday 11/20: the next Tuesday seminar is 11/24, in the plan's following week; past milestones drop.
        self.assertEqual([(row['date'], row['week']) for row in view['dates']],
                         [('2026-11-24', 'W02'), ('2026-12-01', '')])
        sets = {row['key']: row for row in view['question_sets']}
        self.assertTrue(sets['system']['editable'])
        self.assertEqual((sets['system']['results'][0]['text_mn'], sets['system']['results'][0]['stale']), ('3-аас 2', False))
        self.assertFalse(sets['w04']['editable'])
        self.assertEqual(sets['w04']['lock_mn'], 'Агент түгжсэн — хүн хянаагүй')
        self.assertTrue(sets['system']['questions'][1]['abstain'])
        self.assertEqual(view['counts']['teacher']['done'], 1)
        # No config files in this root: every part is still listed, switched parts read as off.
        steps = {row['name']: row for group in view['structure'] for row in group['rows']}
        self.assertEqual((steps['Мэдлэгийн модны нэмэлт оноо']['switch'], steps['Мэдлэгийн модны нэмэлт оноо']['on']), (True, False))
        self.assertFalse(steps['Хэнд, хаана хандахыг заах']['on'])
        self.assertFalse(steps['Сайтаас хайх']['switch'])        # no setting turns it off: shown as fixed, not as a switch
        self.assertIn('бичүүлэхгүй', steps['Хэлний загвараар бичүүлэх']['text'])

    def test_stale_week_is_reported(self):
        self.assertIn('W01-ийнх', work_board.snapshot(self.root, today=date(2026, 11, 24))['stale_mn'])
        board = json.loads((self.root / work_board.BOARD).read_text(encoding='utf-8'))
        board['week']['updated'] = '2026-11-10'
        (self.root / work_board.BOARD).write_text(json.dumps(board, ensure_ascii=False), encoding='utf-8')
        self.assertIn('хоногийн өмнө', work_board.snapshot(self.root, today=TODAY)['stale_mn'])

    def test_simple_status_feeds_the_atlas_panel(self):
        status = work_board.simple_status(self.root, today=TODAY)
        self.assertEqual(status['now'], 'Товч')
        # reported work first; development ahead of the plan is marked as such
        self.assertEqual(status['done'], ['Шалгах асуулт', 'Урьдчилсан: Алдаа зассан'])
        self.assertEqual(status['next'], ['SQuAD унших', 'Үзлэгийн слайд'])
        self.assertEqual(status['dates'][0], {'date': '11/24', 'label': 'Семинар 15:00'})
        self.assertEqual(set(status), {'now', 'parts', 'done', 'problems', 'next', 'dates', 'months'})

    def test_user_confirms_and_adds_feedback(self):
        item = work_board.save_item(self.root, {'id': 'T1117-1', 'status': 'confirmed', 'note': 'Зөв болсон'}, today=TODAY)
        self.assertEqual((item['status'], item['log'][-1]['by']), ('confirmed', 'user'))
        self.assertEqual(work_board.check(self.root, today=TODAY), [])
        new = work_board.save_item(self.root, {'new': True, 'kind': 'teacher', 'date': '2026-11-24', 'about': 'thesis',
                                               'from_mn': 'Удирдагч багш', 'said_mn': '  Арга зүйг\nдэлгэрүүл.  '}, today=TODAY)
        self.assertEqual((new['id'], new['status'], new['said_mn']), ('T1124-1', 'open', 'Арга зүйг дэлгэрүүл.'))
        again = work_board.save_item(self.root, {'new': True, 'kind': 'teacher', 'date': '2026-11-24', 'about': 'ppt',
                                                 'from_mn': 'Багш', 'said_mn': 'Хоёр дахь.'}, today=TODAY)
        self.assertEqual((again['id'], again['track']), ('T1124-2', 'report'))
        moved = work_board.save_item(self.root, {'id': 'A1120-1', 'track': 'ahead'}, today=TODAY)
        self.assertEqual((moved['track'], moved['log'][-1]['text_mn']), ('ahead', 'урьдчилсан хөгжүүлэлт болгосон'))
        # The person's own «done» needs no evidence file; only the assistant's `done` does.
        work_board.save_item(self.root, {'id': 'T1124-2', 'status': 'confirmed'}, today=TODAY)
        self.assertEqual(work_board.check(self.root, today=TODAY), [])
        self.assertTrue(list((self.root / work_board.BACKUPS).glob('workboard.*.json')))
        brief = '\n'.join(work_board.brief_lines(self.root, today=TODAY))
        self.assertIn('T1124-1', brief)
        self.assertIn('A1120-1 · урьдчилсан', brief)
        self.assertIn('✓ Шалгах асуулт', brief)       # what the seminar reports comes first
        self.assertIn('☐ SQuAD унших', brief)
        self.assertNotIn('T1117-1 ·', brief)

    def test_item_input_is_validated(self):
        for payload in ({'id': 'T1117-1'}, {'id': 'T1117-1', 'status': 'finished'}, {'id': 'missing', 'note': 'x'},
                        {'new': True, 'kind': 'audit', 'date': '2026-11-24', 'about': 'ppt', 'from_mn': 'x', 'said_mn': 'y'},
                        {'new': True, 'kind': 'teacher', 'date': '24-11-2026', 'about': 'ppt', 'from_mn': 'x', 'said_mn': 'y'},
                        {'new': True, 'kind': 'teacher', 'date': '2026-11-24', 'about': 'ppt', 'from_mn': 'x', 'said_mn': ''},
                        {'new': True, 'kind': 'teacher', 'date': '20261124', 'about': 'ppt', 'from_mn': 'x', 'said_mn': 'y'},
                        {'id': 'T1117-1', 'track': 'secret'},
                        {'id': 'T1117-1', 'note': 'x' * 1201}):
            with self.assertRaises(ValueError, msg=payload):
                work_board.save_item(self.root, payload, today=TODAY)
        self.assertEqual(json.loads((self.root / work_board.BOARD).read_text(encoding='utf-8')), BOARD)

    def test_confirmed_without_a_user_entry_is_reported(self):
        board = json.loads((self.root / work_board.BOARD).read_text(encoding='utf-8'))
        board['items'][0]['status'] = 'confirmed'
        board['items'][1].update(status='done')
        (self.root / work_board.BOARD).write_text(json.dumps(board, ensure_ascii=False), encoding='utf-8')
        problems = work_board.check(self.root, today=TODAY)
        self.assertTrue(any('T1117-1' in line for line in problems))
        self.assertTrue(any('A1120-1' in line and 'нотолгоо' in line for line in problems))

    def test_draft_question_edit_review_and_lock(self):
        saved = work_board.save_question(self.root, {'set': 'system', 'id': 'F01', 'base_sha': self.sha(), 'fields': {
            'query': 'Сургалтын төлбөр хэд вэ?', 'required_values': ['8,280,000', 'төгрөг'], 'user_review': 'OK'}}, today=TODAY)
        self.assertEqual(saved['question']['required_values'], ['8,280,000', 'төгрөг'])
        self.assertEqual(saved['reviewed'], 1)
        edited = {row['key']: row for row in work_board.snapshot(self.root, today=TODAY)['question_sets']}['system']
        self.assertTrue(edited['results'][0]['stale'])       # the number was measured before this edit
        with self.assertRaises(work_board.Conflict):   # the page still holds the old hash
            work_board.save_question(self.root, {'set': 'system', 'id': 'U01', 'base_sha': '0' * 64,
                                                 'fields': {'user_review': 'OK'}}, today=TODAY)
        with self.assertRaises(ValueError):            # one question is not reviewed yet
            work_board.lock_set(self.root, {'set': 'system', 'base_sha': self.sha(), 'locked_by': 'Хянагч'}, today=TODAY)
        work_board.save_question(self.root, {'set': 'system', 'id': 'U01', 'base_sha': self.sha(),
                                             'fields': {'user_review': 'OK'}}, today=TODAY)
        result = work_board.lock_set(self.root, {'set': 'system', 'base_sha': self.sha(), 'locked_by': 'Хянагч'}, today=TODAY)
        self.assertEqual(result, {'path': 'data/eval/system-questions-locked-20261120.json', 'total': 2})
        locked = json.loads((self.root / result['path']).read_text(encoding='utf-8'))
        self.assertEqual((locked['status'], locked['lock_kind']), ('locked', 'person'))
        self.assertEqual(locked['questions_sha256'], work_board.questions_sha256(locked['questions']))
        self.assertEqual(locked['questions'][0]['user_edited'], '2026-11-20')
        # The locked copy is now the set the page shows, and it refuses every further write.
        view = {row['key']: row for row in work_board.snapshot(self.root, today=TODAY)['question_sets']}
        self.assertFalse(view['system']['editable'])
        self.assertEqual(view['system']['lock_mn'], 'Та түгжсэн — хүн хянасан')
        self.assertEqual(view['system']['results'], [])      # the draft's numbers are not shown as the locked set's
        with self.assertRaises(ValueError):
            work_board.save_question(self.root, {'set': 'system', 'id': 'F01', 'base_sha': view['system']['sha'],
                                                 'fields': {'user_review': 'дахин'}}, today=TODAY)

    def test_locked_sets_and_bad_fields_are_refused(self):
        with self.assertRaises(ValueError):
            work_board.save_question(self.root, {'set': 'w04', 'id': 'A01', 'base_sha': self.sha('w04'),
                                                 'fields': {'user_review': 'OK'}}, today=TODAY)
        for fields in ({}, {'id': 'X'}, {'split': 'test'}, {'required_values': 'нэг'}, {'required_values': ['x'] * 9},
                       {'required_values': []}):          # an answerable question must keep a criterion
            with self.assertRaises(ValueError, msg=fields):
                work_board.save_question(self.root, {'set': 'system', 'id': 'F01', 'base_sha': self.sha(), 'fields': fields},
                                         today=TODAY)
        self.assertEqual(json.loads((self.root / 'data/rag-locked-questions-20261102.json').read_text(encoding='utf-8')), LOCKED)

    def test_a_clone_without_the_local_record_opens_an_empty_board(self):
        (self.root / work_board.BOARD).unlink()
        view = work_board.snapshot(self.root, today=TODAY)
        self.assertEqual((view['items'], view['board_week']['report']['promised']), ([], []))
        self.assertIn('буруу', view['stale_mn'])
        with self.assertRaises(FileNotFoundError):       # the atlas panel falls back to its own block
            work_board.simple_status(self.root, today=TODAY)
        self.assertTrue(any(line.startswith('⚠') for line in work_board.brief_lines(self.root, today=TODAY)))
        added = work_board.save_item(self.root, {'new': True, 'kind': 'teacher', 'date': '2026-11-24', 'about': 'ppt',
                                                 'from_mn': 'Удирдагч багш', 'said_mn': 'Эхний зөвлөгөө.'}, today=TODAY)
        self.assertEqual(added['id'], 'T1124-1')
        self.assertEqual(len(work_board.load(self.root)['items']), 1)

    def test_lock_checks_the_set_shape(self):
        draft = json.loads(json.dumps(DRAFT))
        draft['questions'].append(dict(draft['questions'][0]))             # the same id twice
        for question in draft['questions']:
            question['user_review'] = 'OK'
        (self.root / 'data/eval/system-questions-draft-20261117.json').write_text(json.dumps(draft, ensure_ascii=False), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'давхардсан'):
            work_board.lock_set(self.root, {'set': 'system', 'base_sha': self.sha(), 'locked_by': 'Хянагч'}, today=TODAY)
        self.assertFalse(list((self.root / 'data/eval').glob('*locked*')))

    def test_lock_hash_matches_the_evaluation_tool(self):
        import sys
        sys.path.insert(0, str(REPO / 'tools'))
        try:
            import evaluate_locked_questions
        except ImportError as error:   # the tool's own dependencies are optional on a fresh clone
            self.skipTest(str(error))
        self.assertEqual(work_board.questions_sha256(DRAFT['questions']),
                         evaluate_locked_questions.questions_sha256(DRAFT['questions']))


class RealBoardTests(unittest.TestCase):
    @unittest.skipUnless((REPO / work_board.BOARD).is_file(), 'the board record is a local file, absent on a fresh clone')
    def test_real_board_loads_and_every_done_item_names_its_evidence(self):
        view = work_board.snapshot(REPO, today=TODAY)
        self.assertGreaterEqual(len(view['items']), 10)
        self.assertEqual([line for line in work_board.check(REPO, today=TODAY) if 'хоног' not in line and 'өнөөдөр' not in line], [])
        for item in view['items']:
            self.assertTrue(item['said_mn'].strip(), item['id'])
            self.assertIn(item['about'], work_board.ABOUT, item['id'])


class WorkBoardHTTPTests(unittest.TestCase):
    def setUp(self):
        self.helper = server_fixture.DemoServerTests()
        self.helper.setUp()
        make_root(self.helper.root)
        shutil.copy(REPO / 'demo/work.html', self.helper.root / 'demo/work.html')

    def tearDown(self):
        self.helper.tearDown()

    def test_page_and_api(self):
        status, body = self.helper.request('GET', '/work')
        self.assertEqual(status, 200)
        self.assertIn('Ажлын самбар', body.decode('utf-8'))
        status, view = self.helper.request('GET', '/api/work')
        self.assertEqual(status, 200)
        self.assertEqual({row['key'] for row in view['question_sets']}, {'system', 'w04'})
        token = view['csrf_token']
        status, saved = self.helper.request('POST', '/api/work/item', {'id': 'A1120-1', 'status': 'doing', 'note': 'Засахыг зөвшөөрөв.'},
                                            headers={'X-Work-Token': token})
        self.assertEqual((status, saved['result']['status']), (200, 'doing'))

    def test_writes_need_the_page_token_and_same_site(self):
        self.assertEqual(self.helper.request('POST', '/api/work/item', {'id': 'A1120-1', 'note': 'x'})[0], 403)
        self.assertEqual(self.helper.request('POST', '/api/work/item', {'id': 'A1120-1', 'note': 'x'},
                                             headers={'X-Work-Token': 'guess'})[0], 403)
        self.assertEqual(self.helper.request('GET', '/api/work', headers={'Sec-Fetch-Site': 'cross-site'})[0], 403)
        self.assertEqual(self.helper.request('GET', '/api/work', headers={'Host': 'evil.example'})[0], 403)
        token = self.helper.request('GET', '/api/work')[1]['csrf_token']
        self.assertEqual(self.helper.request('POST', '/api/work/unknown', {}, headers={'X-Work-Token': token})[0], 404)
        self.assertEqual(self.helper.request('POST', '/api/work/question', {'set': 'system', 'id': 'F01', 'base_sha': '0' * 64,
                                             'fields': {'user_review': 'OK'}}, headers={'X-Work-Token': token})[0], 409)
        self.assertEqual(json.loads((self.helper.root / work_board.BOARD).read_text(encoding='utf-8')), BOARD)


if __name__ == '__main__':
    unittest.main()
