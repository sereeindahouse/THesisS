import json
from pathlib import Path
import tempfile
import unittest

from question_planner import QuestionPlanner, compose
from reception_tables import ClassGroup, ReceptionTables, Staff


class FakeReception:
    enabled = True

    def __init__(self):
        self.tables = ReceptionTables(rooms=(), timetable=(),
            staff=(Staff(name='Б.Сэлмаа', department='Ерөнхий эрдмийн тэнхим'),
                   Staff(name='А.Даваа', department='Ерөнхий эрдмийн тэнхим'),
                   Staff(name='Б.Болормаа', department='Ерөнхий эрдмийн тэнхим'),
                   Staff(name='Д.Болормаа', department='Химийн инженерийн тэнхим')),
            classes=(ClassGroup(group='КУ-2', room='612', course='2', department='Компьютерын ухааны тэнхим',
                                teacher='А.Номин-Эрдэнэ'),
                     ClassGroup(group='МИ-1', room='511', course='1', department='Механик инженерийн тэнхим',
                                teacher='Э.Оюунзаяа')))


def planner(**switches):
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        (root / 'config').mkdir()
        config = dict(schema_version=1, enabled=True, split_compound=True, class_groups=True, staff_names=True)
        config.update(switches)
        (root / 'config/question-planner.json').write_text(json.dumps(config), encoding='utf-8')
        (root / 'config/knowledge-domains.json').write_text(json.dumps({'domains': {
            'admissions': {'keywords': ['төлбөр', 'элсэлт']}, 'contact': {'keywords': ['утас', 'ажлын цаг']},
            'location': {'keywords': ['давхар', 'өрөө']}}}, ensure_ascii=False), encoding='utf-8')
        return QuestionPlanner.from_config(root, FakeReception())


class QuestionPlannerTests(unittest.TestCase):
    def queries(self, plan):
        return [part['query'] for part in plan['parts']]

    def test_compound_split_inherits_subject_for_a_part_without_topic(self):
        plan = planner().plan('Сургалтын төлбөр хэд вэ, хэсэгчлэн төлж болох уу?')
        self.assertTrue(plan['compound'])
        self.assertEqual(self.queries(plan), ['Сургалтын төлбөр хэд вэ?', 'Сургалтын төлбөр хэсэгчлэн төлж болох уу?'])
        self.assertEqual([p['original'] for p in plan['parts']], ['Сургалтын төлбөр хэд вэ?', 'хэсэгчлэн төлж болох уу?'])

    def test_part_with_its_own_topic_is_not_prefixed(self):
        plan = planner().plan('Номын сан хэддүгээр давхарт байдаг вэ, ажлын цаг хэд вэ?')
        self.assertEqual(self.queries(plan), ['Номын сан хэддүгээр давхарт байдаг вэ?', 'ажлын цаг хэд вэ?'])

    def test_possessive_part_takes_the_previous_subject_without_repeating_its_noun(self):
        plan = planner(class_groups=False).plan('КУ-2 анги хаана хичээллэдэг вэ, ангийн багш нь хэн бэ?')
        self.assertEqual(self.queries(plan), ['КУ-2 анги хаана хичээллэдэг вэ?', 'КУ-2 ангийн багш нь хэн бэ?'])
        # With the class rules on, the inherited part then takes the closed reception wording.
        plan = planner().plan('КУ-2 анги хаана хичээллэдэг вэ, ангийн багш нь хэн бэ?')
        self.assertEqual(self.queries(plan), ['КУ-2 анги хаана хичээллэдэг вэ?', 'КУ-2 ангийн багш хэн бэ?'])

    def test_comma_without_a_second_question_is_not_split(self):
        plan = planner().plan('Элсэлт, сургалтын төлбөрийн мэдээлэл хэрэгтэй байна уу?')
        self.assertFalse(plan['compound'])

    def test_class_group_from_department_and_course(self):
        p = planner()
        self.assertEqual(self.queries(p.plan('Компьютерын ухааны 2-р курс хаана хичээллэдэг вэ?')),
                         ['КУ-2 анги хаана хичээллэдэг вэ?'])
        self.assertEqual(self.queries(p.plan('Механикийн 1-р курсын ангийн багш хэн бэ?')),
                         ['МИ-1 ангийн багш хэн бэ?'])
        # No such group in the table: the text stays as asked.
        self.assertFalse(p.plan('Механикийн 3-р курс хаана вэ?')['changed'])

    def test_unique_given_name_only_before_bagsh(self):
        p = planner()
        self.assertEqual(self.queries(p.plan('Сэлмаа багшийн имэйл юу вэ?')), ['Б.Сэлмаа багшийн имэйл юу вэ?'])
        self.assertFalse(p.plan('Даваа гарагт хичээл хэдэн цагт эхлэх вэ?')['changed'])   # weekday, not a person
        self.assertFalse(p.plan('Болормаа багшийн имэйл юу вэ?')['changed'])              # two people share the name
        self.assertFalse(p.plan('Б.Сэлмаа багшийн имэйл юу вэ?')['changed'])              # already full

    def test_class_questions_take_the_closed_reception_wording(self):
        p = planner()
        self.assertEqual(self.queries(p.plan('Компьютерын 2-р курсынхан хэдэн тоот өрөөнд байдаг вэ?')),
                         ['КУ-2 анги хаана хичээллэдэг вэ?'])
        self.assertEqual(self.queries(p.plan('КУ-2 ангийн багш нь хэн бэ?')), ['КУ-2 ангийн багш хэн бэ?'])
        # A time-bound question is a timetable question, not the registered room.
        self.assertFalse(p.plan('КУ-2 өнөөдөр хаана хичээллэх вэ?')['changed'])

    def test_short_office_name_becomes_the_unique_table_name(self):
        p = planner()
        p.offices = ('Гадаад харилцаа, карьер хөгжлийн төв', 'Номын сан', 'Сургалтын алба')
        self.assertEqual(self.queries(p.plan('карьерын төв хаана вэ?')), ['Карьер хөгжлийн төв хаана вэ?'])
        self.assertFalse(p.plan('Номын сан хаана вэ?')['changed'])          # already a table name
        self.assertFalse(p.plan('Сургууль хаана байрладаг вэ?')['changed'])  # not an office

    def test_office_room_question_asks_where_the_office_is(self):
        p = planner()
        p.offices = ('Сургалтын алба', 'Сэтгэл зүйч', 'Номын сан')
        self.assertEqual(self.queries(p.plan('Сургалтын албаны өрөө хаана вэ?')), ['Сургалтын алба хаана вэ?'])
        self.assertEqual(self.queries(p.plan('Сэтгэл зүйчийн өрөө хаана байдаг вэ?')), ['Сэтгэл зүйч хаана байдаг вэ?'])

    def test_class_teacher_contact_and_weekday_timetable(self):
        p = planner()
        self.assertEqual(self.queries(p.plan('КУ-2 ангийн багштай яаж холбогдох вэ?')), ['КУ-2 ангийн багшийн имэйл?'])
        self.assertEqual(self.queries(p.plan('КУ-2 ангийн даваа гарагийн эхний хичээл хэдэн цагт эхлэх вэ?')),
                         ['КУ-2 анги даваа гарагт хэдэн цагт хичээлтэй вэ?'])
        self.assertFalse(p.plan('ЗЗ-9 ангийн багштай яаж холбогдох вэ?')['changed'])   # not a recorded group

    def test_named_teacher_contact_room_and_meeting(self):
        p = planner()
        self.assertEqual(self.queries(p.plan('Сэлмаа багштай холбогдмоор байна')), ['Б.Сэлмаа багшийн имэйл?'])
        self.assertEqual(self.queries(p.plan('Б.Сэлмаа багшийн өрөө хэдэн тоот вэ?')), ['Б.Сэлмаа багшийн өрөө хаана вэ?'])
        self.assertEqual(self.queries(p.plan('Сэлмаа багштай одоо уулзаж болох уу?')), ['Б.Сэлмаа багш одоо хичээлтэй юу?'])
        self.assertEqual(self.queries(p.plan('Сэлмаа багштай хэзээ уулзаж болох вэ?')),
                         ['Б.Сэлмаа багш хэзээ оюутантай уулздаг вэ?'])
        # A full name not in the staff table stays for the website path.
        self.assertFalse(p.plan('Х.Хүрэлбаатар багштай холбогдох уу?')['changed'])
        # The timetable-status wording keeps its own (schedule-only) answer.
        self.assertEqual(self.queries(p.plan('Сэлмаа багш хаана байна вэ?')), ['Б.Сэлмаа багш хаана байна вэ?'])
        # Review 11/17: another day is not «now», and a phone question is not an e-mail question.
        self.assertEqual(self.queries(p.plan('Сэлмаа багш маргааш хичээлтэй юу?')), ['Б.Сэлмаа багш маргааш хичээлтэй юу?'])
        self.assertEqual(self.queries(p.plan('Сэлмаа багшийн утасны дугаар хэд вэ?')),
                         ['Б.Сэлмаа багшийн утасны дугаар хэд вэ?'])
        # Review 11/17 (4): «холбоо барих утас» stays a phone question (its reply says phones are
        # not shown, then offers the school e-mail); «хэзээ хичээлтэй» is the timetable, not office
        # hours; a weekday «хаана байна» is where the teacher is then, not the office room.
        self.assertEqual(self.queries(p.plan('Сэлмаа багштай холбоо барих утас хэд вэ?')), ['Б.Сэлмаа багшийн утас?'])
        self.assertEqual(self.queries(p.plan('КУ-2 ангийн багштай холбоо барих утас хэд вэ?')),
                         ['КУ-2 ангийн багшийн утас?'])
        self.assertEqual(self.queries(p.plan('Сэлмаа багш хэзээ хичээлтэй вэ?')), ['Б.Сэлмаа багш хэзээ хичээлтэй вэ?'])
        self.assertEqual(self.queries(p.plan('Сэлмаа багш даваа гарагт хаана байна вэ?')),
                         ['Б.Сэлмаа багш даваа гарагт хаана байна вэ?'])

    def test_teacher_rewrite_uses_the_table_spelling(self):
        reception = FakeReception()
        reception.tables = ReceptionTables(rooms=(), timetable=(), classes=(),
                                           staff=(Staff(name='Б. Сэлмаа', department='Ерөнхий эрдмийн тэнхим'),))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'config').mkdir()
            (root / 'config/question-planner.json').write_text(json.dumps(dict(
                schema_version=1, enabled=True, split_compound=True, class_groups=True, staff_names=True)),
                encoding='utf-8')
            p = QuestionPlanner.from_config(root, reception)
        self.assertEqual(self.queries(p.plan('Б.Сэлмаа багштай холбогдмоор байна')), ['Б. Сэлмаа багшийн имэйл?'])

    def test_review_findings_for_class_and_office_rules(self):
        p = planner()
        p.offices = ('Сургалтын алба',)
        # A class teacher's weekday is about the teacher, not the class timetable.
        self.assertFalse(p.plan('КУ-2 ангийн багш даваа гарагт хичээлтэй юу?')['changed'])
        # Any form of «сургууль» names the school, not part of the office name.
        self.assertEqual(self.queries(p.plan('Сургуульд сургалтын албаны өрөө хаана вэ?')), ['Сургалтын алба хаана вэ?'])

    def test_switches_off_leave_the_question_unchanged(self):
        p = planner(enabled=False)
        self.assertFalse(p.enabled)
        plan = planner(split_compound=False, class_groups=False, staff_names=False).plan(
            'Компьютерын ухааны 2-р курс хаана вэ, Сэлмаа багш хаана вэ?')
        self.assertFalse(plan['changed'])

    def test_compose_keeps_part_answers_verbatim_and_refers_the_missing_part(self):
        plan = planner().plan('Сургалтын төлбөр хэд вэ, хэсэгчлэн төлж болох уу?')
        found = dict(answer='Жилд 8,280,000 ₮.', route='B', reason_code='x', citations=[{'url': 'https://nmct.edu.mn/elselt'}],
                     llm_calls=0)
        missing = dict(answer=None, route='E', reason_code='website_no_evidence', citations=[],
                       referral=dict(text='Ресепшний ажилтнаас асууна уу.'), llm_calls=0)
        result = compose(plan['parts'][0]['original'] + ' ' + plan['parts'][1]['original'], plan, [found, missing])
        self.assertIn('Жилд 8,280,000 ₮.', result['answer'])
        self.assertIn('Энэ хэсгийн баталгаатай мэдээлэл олдсонгүй.', result['answer'])
        self.assertEqual(result['reason_code'], 'compound_parts_partly_answered')
        self.assertEqual(result['referral']['text'], 'Ресепшний ажилтнаас асууна уу.')
        self.assertEqual([p['answered'] for p in result['parts']], [True, False])
        self.assertFalse(result['generated'])


if __name__ == '__main__':
    unittest.main()
