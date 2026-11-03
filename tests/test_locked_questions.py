"""The W04 runner must refuse an unlocked set and score only from synthetic data here."""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from evaluate_locked_questions import (DEFAULT_SET, EXPECTED_COUNTS, lock, missing_values, questions_sha256,
                                       require_locked, score_answers, score_retrieval, stored_texts,
                                       validate_shape, validate_sources, value_present)

URL = 'https://example.test/page'


def full_set():
    questions = [dict(id=f'A{i}', kind='answerable', query=f'асуулт {i}?', answer_mn='53.', required_values=['53'],
                      support=[dict(url=URL, phrase='53 төгсөгч')]) for i in range(EXPECTED_COUNTS['answerable'])]
    questions += [dict(id=f'U{i}', kind='unanswerable', query=f'хариугүй {i}?', why_mn='алга')
                  for i in range(EXPECTED_COUNTS['unanswerable'])]
    questions += [dict(id=f'R{i}', kind='reception', query=f'ресепшн {i}?', expected_now='no_data')
                  for i in range(EXPECTED_COUNTS['reception'])]
    return dict(status='draft', locked_by=None, locked_at=None, questions_sha256=None, questions=questions)


class ValueTests(unittest.TestCase):
    def test_number_does_not_match_inside_longer_number(self):
        self.assertFalse(value_present('10', 'нийт 2010 онд 100 оноо'))
        self.assertTrue(value_present('10', 'Техник зураг 10 оноо'))

    def test_alternative_wordings_and_case(self):
        self.assertTrue(value_present(['2026.04.25', '4-р сарын 25'], 'Олимпиад 4-Р САРЫН 25-нд'))
        self.assertEqual(missing_values(dict(required_values=['78', '5 багш']), '78 оюутан'), ['5 багш'])


class LockTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / 'set.json'
        self.path.write_text(json.dumps(full_set(), ensure_ascii=False), encoding='utf-8')

    def test_draft_cannot_run(self):
        with self.assertRaisesRegex(ValueError, 'not locked'):
            require_locked(full_set())

    def test_lock_needs_a_person_and_happens_once(self):
        with self.assertRaisesRegex(ValueError, 'person'):
            lock(self.path, ' ')
        require_locked(lock(self.path, 'Оюутан'))
        with self.assertRaisesRegex(ValueError, 'already locked'):
            lock(self.path, 'Оюутан')

    def test_lock_records_whether_a_person_or_the_assistant_locked(self):
        self.assertEqual(lock(self.path, 'Оюутан')['lock_kind'], 'person')
        self.path.write_text(json.dumps(full_set(), ensure_ascii=False), encoding='utf-8')
        data = lock(self.path, 'Claude (AI)', assistant=True)
        self.assertEqual(data['lock_kind'], 'assistant_at_user_instruction')
        require_locked(data)

    def test_change_after_lock_is_refused(self):
        data = lock(self.path, 'Оюутан')
        data['questions'][0]['query'] = 'өөрчилсөн асуулт?'
        with self.assertRaisesRegex(ValueError, 'changed after locking'):
            require_locked(data)

    def test_lock_refuses_wrong_counts(self):
        data = full_set()
        data['questions'].pop()
        self.path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'counts'):
            lock(self.path, 'Оюутан')

    def test_hash_ignores_nothing_in_questions(self):
        first = full_set()['questions']
        second = full_set()['questions']
        second[0]['answer_mn'] = 'өөр'
        self.assertNotEqual(questions_sha256(first), questions_sha256(second))


class ScoreTests(unittest.TestCase):
    def test_retrieval_needs_the_right_page_and_phrase(self):
        question = dict(id='A1', kind='answerable', query='q', support=[dict(url=URL, phrase='53 төгсөгч')])
        candidates = [dict(url='https://example.test/other', text='53 төгсөгч'), dict(url=URL, text='өөр текст'),
                      dict(url=URL, text='Анхны 53 Төгсөгч')]
        report = score_retrieval([question], lambda query, mode: candidates, modes=('bm25',))['bm25']
        self.assertEqual((report['ranks']['A1'], report['top_1'], report['top_3'], report['top_5']), (3, 0, 1, 1))

    def test_answers_are_sorted_into_plain_outcomes(self):
        questions = [dict(id='A1', kind='answerable', query='a1', required_values=['53']),
                     dict(id='A2', kind='answerable', query='a2', required_values=['53']),
                     dict(id='A3', kind='answerable', query='a3', required_values=['53']),
                     dict(id='U1', kind='unanswerable', query='u1'), dict(id='U2', kind='unanswerable', query='u2'),
                     dict(id='R1', kind='reception', query='r1', expected_now='no_data'),
                     dict(id='R2', kind='reception', query='r2', expected_now='answerable', required_values=['10'])]
        replies = dict(a1=dict(answer='53 төгсөгч', llm_calls=0), a2=dict(answer='52 төгсөгч'), a3=dict(answer=None, message='алга'),
                       u1=dict(answer=None), u2=dict(answer='зохиосон'), r1=dict(answer=None), r2=dict(answer='10 давхарт'))
        report = score_answers(questions, lambda query: replies[query])['summary']
        self.assertEqual(report['answerable_values_present'], 1)
        self.assertEqual(report['answerable_values_missing'], 1)
        self.assertEqual(report['answerable_refused'], 1)
        self.assertEqual((report['unanswerable_refused'], report['unanswerable_answered']), (1, 1))
        self.assertEqual((report['reception_refused'], report['reception_values_present']), (1, 1))


class SourceTests(unittest.TestCase):
    def test_sources_check_phrases_and_absence(self):
        questions = [dict(id='A1', support=[dict(url=URL, phrase='53 төгсөгч')]), dict(id='A2', support=[dict(url=URL, phrase='байхгүй үг')]),
                     dict(id='U1', absence_terms=['ном зээл'])]
        problems = validate_sources(questions, {URL: 'Анхны 53 төгсөгч. Ном зээлж болно.'})
        self.assertEqual(len(problems), 2)
        self.assertIn('A2', problems[0])
        self.assertIn('U1', problems[1])

    def test_stored_texts_join_pages_and_documents(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / 'site.db'
            connection = sqlite3.connect(database)
            connection.executescript('create table pages(url,version,text);create table document_extractions(url,payload_json);'
                                     'create table client_tab_extractions(url,payload_json);')
            connection.execute('insert into pages values(?,1,?)', (URL, 'хуучин'))
            connection.execute('insert into pages values(?,2,?)', (URL, 'шинэ'))
            connection.execute('insert into document_extractions values(?,?)', (URL, json.dumps(dict(text='журам'), ensure_ascii=False)))
            connection.commit()
            connection.close()
            text = stored_texts(database)[URL]
        self.assertIn('шинэ', text)
        self.assertIn('журам', text)
        self.assertNotIn('хуучин', text)


class RealDraftTests(unittest.TestCase):
    def test_published_set_has_the_planned_shape(self):
        data = json.loads(DEFAULT_SET.read_text(encoding='utf-8'))
        self.assertEqual(validate_shape(data), [])
        self.assertTrue(all(q['id'] for q in data['questions']))


if __name__ == '__main__':
    unittest.main()
