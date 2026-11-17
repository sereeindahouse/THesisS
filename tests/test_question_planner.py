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

    def test_round8_spoken_names_codes_and_bare_followups(self):
        plan = QuestionPlanner(enabled=True, split_compound=True, class_groups=True, staff_names=True,
                               given_names={'сэлмаа': 'Б.Сэлмаа'}, offices=['Номын сан', 'Захирал'],
                               topic_keywords=['төлбөр', 'имэйл', 'өрөө', 'давхар', 'анги', 'багш'],
                               staff=['Б.Сэлмаа'], class_names=['КУ-2', 'БИ-2'])

        def asked(query, previous=None):
            return plan.plan(query, previous=previous)['parts'][0]['query']

        # A given name in lower case is the same teacher; a class code without its dash or case too.
        self.assertEqual(asked('сэлмаа багшийн имэйл'), 'Б.Сэлмаа багшийн имэйл')
        self.assertEqual(asked('ку 2 ангийн багш хэн бэ'), 'КУ-2 ангийн багш хэн бэ')
        self.assertEqual(asked('КУ2 анги хаана хичээллэдэг вэ'), 'КУ-2 анги хаана хичээллэдэг вэ')
        self.assertEqual(asked('ба 2 удаа'), 'ба 2 удаа')   # not a class in the table
        self.assertEqual(asked('Би 2 давхарт хаана очих вэ?'), 'Би 2 давхарт хаана очих вэ?')   # a pronoun
        self.assertEqual(asked('давхар нь', 'сэлмаа багш хаана байна'), 'Б.Сэлмаа багшийн өрөө хаана вэ?')
        # «… нь?» alone follows the previous question; a bare «өрөө/давхар» becomes the location question.
        self.assertEqual(asked('имэйл нь', 'сэлмаа багш хаана байна'), 'Б.Сэлмаа багшийн имэйл')
        self.assertEqual(asked('өрөө нь?', 'Захирал хэн бэ?'), 'Захирал хаана вэ?')
        self.assertEqual(asked('давхар нь', 'Номын сан хаана вэ?'), 'Номын сан хэддүгээр давхарт вэ?')

    def test_round9_wishes_and_class_teacher_followups(self):
        plan = QuestionPlanner(enabled=True, split_compound=True, class_groups=True, staff_names=True,
                               given_names={}, offices=['Номын сан'], topic_keywords=['имэйл', 'өрөө', 'анги', 'багш'],
                               staff=[], class_names=['КУ-2'])

        def asked(query, previous=None):
            return plan.plan(query, previous=previous)['parts'][0]['query']

        # A wish to get a paper asks where it is issued.
        self.assertEqual(asked('Сургуулийн тодорхойлолт авах гэсэн юм'), 'Сургуулийн тодорхойлолт хаанаас авах вэ?')
        self.assertEqual(asked('Дүнгийн хуудас авмаар байна'), 'Дүнгийн хуудас хаанаас авах вэ?')
        # Only papers: an exam, broad information or a class timetable stay as asked (review).
        for query in ('Шалгалт авах гэж байна', 'Мэдээлэл авмаар байна', 'КУ-2 ангийн хуваарь авмаар байна'):
            with self.subTest(query=query):
                self.assertEqual(asked(query), query)
        self.assertEqual(asked('КУ-2 ангийн дүнгийн хуудас авах гэсэн юм'), 'КУ-2 ангийн дүнгийн хуудас хаанаас авах вэ?')
        # The class teacher's room, not the class's room; the class's own schedule stays the class's.
        self.assertEqual(asked('КУ-2 ангийн багшийн өрөө хаана вэ?'), 'КУ-2 ангийн багшийн өрөө хаана вэ?')
        self.assertEqual(asked('Өрөө нь хаана вэ?', 'КУ-2 ангийн багш хэн бэ?'), 'КУ-2 ангийн багшийн өрөө хаана вэ?')
        self.assertEqual(asked('Имэйл нь?', 'КУ-2 ангийн багш хэн бэ?'), 'КУ-2 ангийн багшийн имэйл?')
        self.assertEqual(asked('Давхар нь хэд вэ?', 'КУ-2 ангийн багш хэн бэ?'), 'КУ-2 ангийн багшийн өрөө хаана вэ?')
        self.assertEqual(asked('Давхар нь хэд вэ?', 'Номын сан хаана вэ?'), 'Номын сан хэддүгээр давхарт вэ?')
        self.assertEqual(asked('Маргааш хэдэн цагт хичээлтэй вэ?', 'КУ-2 ангийн багш хэн бэ?'),
                         'КУ-2 анги маргааш хэдэн цагт хичээлтэй вэ?')
        self.assertEqual(asked('КУ-2 анги хаана байдаг вэ?'), 'КУ-2 анги хаана хичээллэдэг вэ?')

    def test_elliptical_followup_borrows_only_the_previous_named_thing(self):
        # Round 4 (11/17): «Номын сан хаана вэ?» then «Хэдэн цагт ажилладаг вэ?» answered the school's
        # hours. Only the named thing is carried (research: whole history hurts); a new topic is not.
        plan = QuestionPlanner(enabled=True, split_compound=True, class_groups=True, staff_names=True,
                               given_names={'сэлмаа': 'Б.Сэлмаа'}, offices=['Номын сан', 'Сургалтын алба'],
                               topic_keywords=['төлбөр', 'элсэлт', 'имэйл', 'давхар', 'өрөө', 'анги', 'багш'],
                               staff=['Б.Сэлмаа'], class_names=['КУ-2'])

        def asked(query, previous):
            result = plan.plan(query, previous=previous)
            return result['parts'][0]['query'], (result.get('followup') or {}).get('entity')

        self.assertEqual(asked('Хэдэн цагт ажилладаг вэ?', 'Номын сан хаана вэ?'),
                         ('Номын сан хэдэн цагт ажилладаг вэ?', 'Номын сан'))
        self.assertEqual(asked('Хэддүгээр давхарт байдаг вэ?', 'Сургалтын алба хаана байдаг вэ?')[0],
                         'Сургалтын алба хэддүгээр давхарт байдаг вэ?')
        self.assertEqual(asked('Маргааш хичээлтэй юу?', 'Сэлмаа багшийн имэйл хаяг юу вэ?')[0],
                         'Б.Сэлмаа багш маргааш хичээлтэй юу?')
        self.assertEqual(asked('Имэйл нь юу вэ?', 'Сэлмаа багш хаана байна вэ?')[0], 'Б.Сэлмаа багшийн имэйл юу вэ?')
        self.assertEqual(asked('Ангийн багш нь хэн бэ?', 'КУ-2 анги хаана хичээллэдэг вэ?')[0], 'КУ-2 ангийн багш хэн бэ?')
        self.assertEqual(asked('Хэрхэн төлөх вэ?', 'Сургалтын төлбөр хэд вэ?')[0], 'Сургалтын төлбөр хэрхэн төлөх вэ?')
        # A topic or a name of its own, a greeting, or no previous question: asked as it is.
        for query, previous in (('Сургалтын төлбөр хэд вэ?', 'Номын сан хаана вэ?'),
                                ('Сургалтын алба хаана вэ?', 'Номын сан хаана вэ?'),
                                ('КУ-5 анги хаана вэ?', 'КУ-2 анги хаана хичээллэдэг вэ?'),
                                ('Сайн байна уу?', 'Номын сан хаана вэ?'),
                                ('Хэдэн цагт ажилладаг вэ?', None)):
            with self.subTest(query=query, previous=previous):
                self.assertEqual(asked(query, previous), (query, None))

    def test_compound_split_inherits_subject_for_a_part_without_topic(self):
        plan = planner().plan('Сургалтын төлбөр хэд вэ, хэсэгчлэн төлж болох уу?')
        self.assertTrue(plan['compound'])
        self.assertEqual(self.queries(plan), ['Сургалтын төлбөр хэд вэ?', 'Сургалтын төлбөр хэсэгчлэн төлж болох уу?'])
        self.assertEqual([p['original'] for p in plan['parts']], ['Сургалтын төлбөр хэд вэ?', 'хэсэгчлэн төлж болох уу?'])

    def test_parallel_counts_share_the_subject_and_the_predicate(self):
        # 11/17 (5): one predicate over two asked counts (W04-A18).
        plan = planner().plan('2026 оны намрын ажилд хэдэн оюутан, хэдэн багш оролцсон бэ?')
        self.assertEqual(self.queries(plan), ['2026 оны намрын ажилд хэдэн оюутан оролцсон бэ?',
                                              '2026 оны намрын ажилд хэдэн багш оролцсон бэ?'])
        # Review 11/17 (5): a whole first question («ямар байна») is not glued to the next predicate.
        self.assertEqual(QuestionPlanner._distribute(['Төлбөр ямар байна?', 'хэдэн жил суралцах вэ?']),
                         ['Төлбөр ямар байна?', 'хэдэн жил суралцах вэ?'])
        # «юм» ends a statement: one request, not two parts.
        self.assertFalse(planner().plan('Багштай уулзах гэсэн юм, имэйл хаяг нь юу вэ?')['compound'])
        # Two complete questions are not rewritten.
        plan = planner().plan('Сургалтын төлбөр хэд вэ, хэсэгчлэн төлж болох уу?')
        self.assertEqual(self.queries(plan), ['Сургалтын төлбөр хэд вэ?', 'Сургалтын төлбөр хэсэгчлэн төлж болох уу?'])

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
        # 11/17 (5): a named day goes to that day's timetable wording, never to «now» or the office.
        self.assertEqual(self.queries(p.plan('Сэлмаа багш даваа гарагт хаана байна вэ?')),
                         ['Б.Сэлмаа багш даваа гарагт хичээлтэй юу?'])
        self.assertEqual(self.queries(p.plan('Сэлмаа багштай өнөөдөр уулзаж болох уу?')),
                         ['Б.Сэлмаа багш өнөөдөр хичээлтэй юу?'])
        self.assertEqual(self.queries(p.plan('Сэлмаа багш 15:00 цагт хаана байна вэ?')),
                         ['Б.Сэлмаа багш 15:00 цагт хаана байна вэ?'])
        # Review 11/17 (5): a teacher named like a weekday («А.Даваа») is not read as that day.
        self.assertEqual(self.queries(p.plan('А.Даваа багштай уулзаж болох уу?')), ['А.Даваа багш одоо хичээлтэй юу?'])

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
