"""The knowledge tree beside the chat (knowledge_view.py, 2026-11-26).

Uses the project's own tree configuration; every reply and table below is INVENTED. No server, no model.
"""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from knowledge_view import KnowledgeView, url_topic
from reception_tables import ClassGroup, Lesson, ReceptionTables, Room, Service, Staff

ROOT = Path(__file__).resolve().parents[1]


def tables():
    return ReceptionTables(
        rooms=(Room(floor=4, name='406', purpose='Алба', services=(Service(name='Зохиомол алба', office_hours='', contact='—'),)),
               Room(floor=6, name='604', purpose='Багш нарын өрөө', department='Зохиомол тэнхим')),
        staff=(Staff(name='З.Наран', department='Зохиомол тэнхим', room='604'), Staff(name='З.Саран', department='Зохиомол тэнхим')),
        classes=(ClassGroup(group='ЗА-1', room='604'),),
        timetable=(Lesson(day='mon', time='08:00-09:30', group='ЗА-1', room='604', teacher='З.Наран', subject='Алгоритм'),),
        timetable_complete=True, dataset_label='FAKE only')


class TreeTests(unittest.TestCase):
    def setUp(self):
        self.view = KnowledgeView(ROOT, tables=tables())

    def test_eleven_domains_with_their_sub_sections(self):
        tree = self.view.tree()
        self.assertEqual(len(tree), 11)
        staff = next(domain for domain in tree if domain['id'] == 'staff')
        self.assertEqual([child['id'] for child in staff['children']], ['staff.directory', 'staff.offices', 'staff.availability'])
        self.assertNotIn('review-needed', [domain['id'] for domain in tree])

    def test_school_tables_are_counted_where_they_answer(self):
        tree = {domain['id']: domain for domain in self.view.tree()}
        self.assertEqual(tree['staff']['counts']['rows'], 2 + 1 + 1)          # staff, with a room, teaching
        self.assertEqual(tree['location']['counts']['rows'], 2 + 1 + 1)       # rooms, offices, department rooms
        self.assertEqual(tree['classes']['counts']['rows'], 1 + 1)

    def test_the_data_sets_say_what_they_hold_in_counts_only(self):
        sets = {item['kind']: item for item in self.view.datasets()}
        school = ' '.join(sets['school']['lines'])
        self.assertIn('2 өрөө', school)
        self.assertIn('2 ажилтан', school)
        self.assertNotIn('Наран', json.dumps(self.view.datasets(), ensure_ascii=False))     # no person leaves the view
        self.assertEqual(sets['tree']['lines'][0], '11 хүрээ, 31 дэд хэсэг')

    def test_website_pages_are_placed_by_the_trees_url_rules(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / 'website.db'
            connection = sqlite3.connect(database)       # closed before the folder is removed (Windows)
            connection.execute('create table pages (url text, version integer, retrieved_at text)')
            connection.executemany('insert into pages values (?, 1, ?)', [
                ('https://nmct.edu.mn/about/history', '2026-11-17'), ('https://nmct.edu.mn/news/a', '2026-11-17')])
            connection.commit()
            connection.close()
            view = KnowledgeView(ROOT, website_database=database)
            tree = {domain['id']: domain for domain in view.tree()}
            self.assertEqual(tree['school']['counts']['pages'], 1)
            self.assertEqual(tree['news']['counts']['pages'], 1)
        self.assertEqual(url_topic('https://nmct.edu.mn/departments/mechanical', view.config), 'academics.mechanical')
        self.assertEqual(url_topic('https://example.org/x', view.config), 'review-needed')


class PlaceTests(unittest.TestCase):
    def setUp(self):
        self.view = KnowledgeView(ROOT, tables=tables())

    def place(self, query='', **result):
        result.setdefault('answer', 'Хариулт.')
        result.setdefault('citations', [])
        return self.view.place(result, query)

    def test_a_table_reply_is_placed_by_what_was_looked_up(self):
        place = self.place('Наран багштай яаж уулзах вэ?', reason_code='reception_teacher_meet', answer_kind='reception_table_lookup')
        self.assertEqual(place['places'][0]['domain_id'], 'staff')
        self.assertEqual(place['places'][0]['topic_id'], 'staff.offices')
        self.assertEqual(place['places'][0]['source'], 'table')
        self.assertEqual(self.place(reason_code='reception_service_lookup')['places'][0]['topic_id'], 'location.services')
        self.assertEqual(self.place(reason_code='reception_class_day')['places'][0]['topic_id'], 'classes.timetable')

    def test_a_section_with_a_labelled_heading_is_its_sub_section(self):
        place = self.place(reason_code='website_section', answer_kind='website_section', citations=[
            dict(source_url_or_filename='https://nmct.edu.mn/about/environment', locator='Номын сан')])
        self.assertEqual((place['places'][0]['topic_id'], place['places'][0]['source']), ('student.library', 'section'))

    def test_every_part_of_a_composed_reply_is_placed(self):
        place = self.place(reason_code='compound_parts_all_answered', parts=[
            dict(reason_code='reception_service_lookup', answer_kind='reception_table_lookup', answered=True, source_urls=[]),
            dict(reason_code='website_section', answer_kind='website_section', answered=True,
                 source_urls=['https://nmct.edu.mn/about/history'], locators=['Түүх'])])
        self.assertEqual([item['domain_id'] for item in place['places']], ['location', 'school'])

    def test_nothing_found_names_the_domains_the_question_asked_at_the_start_of_a_word(self):
        place = self.place('Номын сангийн талаар', answer=None, reason_code='website_no_evidence')
        self.assertFalse(place['found'])
        self.assertEqual([item['domain_id'] for item in place['asked']], ['student'])     # «анги» inside «сангийн» is no class


if __name__ == '__main__':
    unittest.main()
