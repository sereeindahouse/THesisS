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

    def test_round10_transfer_is_not_a_class_group(self):
        # W04-A06: «Механик инженерт 2-р курст шилжин орвол …» became «МИ-2 анги …» and lost its
        # stored answer; a class question with the same words still names the class.
        import question_planner
        plan = QuestionPlanner(enabled=True, split_compound=True, class_groups=True, staff_names=True,
                               groups={(question_planner._stem('Механик'), '2'): 'МИ-2'}, given_names={},
                               topic_keywords=['анги', 'багш'], offices=[], staff=[], class_names=['МИ-2'])
        transfer = 'Механик инженерт 2-р курст шилжин орвол хэдэн жил суралцах вэ?'
        self.assertEqual(plan.plan(transfer)['parts'][0]['query'], transfer)
        self.assertEqual(plan.plan('Механик инженерийн 2-р курсийн ангийн багш хэн бэ?')['parts'][0]['query'],
                         'МИ-2 ангийн багш хэн бэ?')

    def test_round12_department_followup(self):
        plan = QuestionPlanner(enabled=True, split_compound=True, class_groups=True, staff_names=True, given_names={},
                               offices=[], topic_keywords=['эрхлэгч', 'анги', 'багш'], staff=[], class_names=[])
        self.assertEqual(plan.plan('Эрхлэгч нь хэн бэ?', previous='Механик тэнхим хаана вэ?')['parts'][0]['query'],
                         'Механик тэнхимийн эрхлэгч хэн бэ?')

    def test_round13_spoken_class_genitive_names_and_there(self):
        plan = QuestionPlanner(enabled=True, split_compound=True, class_groups=True, staff_names=True,
                               given_names={'сэлмаа': 'Б.Сэлмаа'}, offices=['Номын сан'], topic_keywords=['анги', 'багш'],
                               staff=['Б.Сэлмаа'], class_names=['КУ-2'])

        def asked(query, previous=None):
            return plan.plan(query, previous=previous)['parts'][0]['query']

        self.assertEqual(asked('КУ хоёр анги хаана хичээллэдэг вэ'), 'КУ-2 анги хаана хичээллэдэг вэ')
        self.assertEqual(asked('Сэлмаагийн өрөө хаана вэ'), 'Б.Сэлмаа багшийн өрөө хаана вэ')
        self.assertEqual(asked('Тэнд ном зээлж болох уу?', 'Номын сан хаана вэ?'), 'Номын сан ном зээлж болох уу?')
        # «энд» (here) is the school: a new question (review).
        self.assertEqual(asked('Энд кафе байдаг уу?', 'Номын сан хаана вэ?'), 'Энд кафе байдаг уу?')

    def test_round16_meeting_followups_take_the_comitative(self):
        from question_planner import _comitative
        plan = QuestionPlanner(enabled=True, split_compound=True, class_groups=True, staff_names=True,
                               given_names={}, offices=['Номын сан', 'Сэтгэл зүйч'], topic_keywords=['анги', 'багш'],
                               staff=[], class_names=['КУ-2'])

        def asked(query, previous=None):
            return plan.plan(query, previous=previous)['parts'][0]['query']

        self.assertEqual(asked('Уулзаж болох уу?', 'Сэтгэл зүйч хаана суудаг вэ?'), 'Сэтгэл зүйчтэй уулзаж болох уу?')
        self.assertEqual(asked('Яаж холбогдох вэ?', 'Захирал хэн бэ?'), 'Захиралтай яаж холбогдох вэ?')
        self.assertEqual(asked('Хэдэн цагт ажилладаг вэ?', 'Эмч хаана байдаг вэ?'), 'Эмч хэдэн цагт ажилладаг вэ?')
        # A contact number, or a class, takes no «-тай» (review).
        self.assertNotIn('зүйчтэй', asked('Холбогдох утас нь?', 'Сэтгэл зүйч хаана суудаг вэ?'))
        self.assertNotIn('ангитай', asked('Уулзаж болох уу?', 'КУ-2 анги хаана вэ?'))
        self.assertEqual([_comitative(word) for word in ('зүйч', 'Захирал', 'Болд', 'өрөө', 'багш', 'Зоригт')],
                         ['зүйчтэй', 'Захиралтай', 'Болдтой', 'өрөөтэй', 'багштай', 'Зоригттой'])

    def test_round17_one_noun_with_its_particle_follows_up(self):
        plan = QuestionPlanner(enabled=True, split_compound=True, class_groups=True, staff_names=True,
                               given_names={}, offices=['Номын сан'], topic_keywords=['төлбөр', 'анги', 'багш'],
                               staff=[], class_names=['КУ-2'])

        def asked(query, previous=None):
            return plan.plan(query, previous=previous)['parts'][0]['query']

        # «Төлбөр нь хэд вэ?» asks about the dormitory just named; a full question is a new one.
        self.assertEqual(asked('Төлбөр нь хэд вэ?', 'Дотуур байр байдаг уу?'), 'Дотуур байр төлбөр хэд вэ?')
        self.assertEqual(asked('Сургалтын төлбөр хэд вэ?', 'Дотуур байр байдаг уу?'), 'Сургалтын төлбөр хэд вэ?')
        # «Төлбөр нь?» alone, and «нь» with any question word (review).
        self.assertEqual(asked('Төлбөр нь?', 'Дотуур байр байдаг уу?'), 'Дотуур байр төлбөр?')
        self.assertEqual(asked('Төлбөр нь яаж төлөх вэ?', 'Дотуур байр байдаг уу?'), 'Дотуур байр төлбөр яаж төлөх вэ?')

    def test_round20_courtesy_compound_parts_and_pronouns(self):
        plan = QuestionPlanner(enabled=True, split_compound=True, class_groups=True, staff_names=True,
                               given_names={}, offices=['Номын сан', 'Сургалтын алба'], topic_keywords=['төлбөр', 'анги', 'багш'],
                               staff=[], class_names=['КУ-2'])

        def parts(query, previous=None):
            return [part['query'] for part in plan.plan(query, previous=previous)['parts']]

        # A polite opening or a short self-introduction is not part of the question; a greeting alone stays.
        self.assertEqual(parts('Уучлаарай, номын сан хаана байдаг вэ?'), ['Номын сан хаана байдаг вэ?'])
        self.assertEqual(parts('Сайн байна уу, захиралтай уулзах гэсэн юм'), ['Захиралтай уулзах гэсэн юм'])
        self.assertEqual(parts('Би шинэ оюутан, сургалтын алба хаана байдаг вэ?'), ['Сургалтын алба хаана байдаг вэ?'])
        self.assertEqual(parts('Сайн байна уу'), ['Сайн байна уу'])
        # The later part of one question reads like a follow-up of the part before it.
        self.assertEqual(parts('Захирал хэн бэ, өрөө нь хаана вэ?'), ['Захирал хэн бэ?', 'Захирал хаана вэ?'])
        # «Түүнтэй» (with them) is the thing just named.
        self.assertEqual(parts('Түүнтэй уулзаж болох уу?', 'Захирал хэн бэ?'), ['Захиралтай уулзаж болох уу?'])
        # Review: a later part with a topic of its own stays; the previous question's opening is no subject;
        # «түүнтэй» anywhere, and the class teacher after a class-teacher question; stacked openings.
        self.assertEqual(parts('Сургалтын алба хаана вэ, багш нар хэн бэ?'), ['Сургалтын алба хаана вэ?', 'багш нар хэн бэ?'])
        self.assertEqual(parts('Уулзаж болох уу?', 'Сайн байна уу, сэтгэл зүйч хаана суудаг вэ?'), ['Сэтгэл зүйчтэй уулзаж болох уу?'])
        self.assertEqual(parts('Одоо түүнтэй уулзаж болох уу?', 'Захирал хэн бэ?'), ['Захиралтай одоо уулзаж болох уу?'])
        self.assertEqual(parts('Түүнтэй уулзаж болох уу?', 'КУ-2 ангийн багш хэн бэ?'), ['КУ-2 ангийн багштай уулзаж болох уу?'])
        self.assertEqual(parts('Сайн байна уу, уучлаарай, номын сан хаана байдаг вэ?'), ['Номын сан хаана байдаг вэ?'])

    def test_round21_spoken_questions_and_their_followups(self):
        plan = QuestionPlanner(enabled=True, split_compound=True, class_groups=True, staff_names=True,
                               given_names={}, offices=['Номын сан'], topic_keywords=['төлбөр', 'анги', 'багш'],
                               staff=[], class_names=['КУ-2'])

        def parts(query, previous=None):
            return [part['query'] for part in plan.plan(query, previous=previous)['parts']]

        # The filler and the colloquial ending go before the follow-up rules read the question.
        self.assertEqual(parts('хэдэн цагт ажилладаг юм бэ', 'аан номын сан хаана байдаг юм бэ'), ['Номын сан хэдэн цагт ажилладаг вэ'])
        self.assertEqual(parts('аан ку хоёр ангийн багш хэн юм бэ'), ['КУ-2 ангийн багш хэн бэ'])
        # Review: a filler before a polite opening; a wish in its own sentence keeps the wish rule.
        self.assertEqual(parts('Аан сайн байна уу, номын сан хаана байдаг вэ?'), ['Номын сан хаана байдаг вэ?'])
        self.assertEqual(parts('Номын сан хаана вэ? Тодорхойлолт авах гэсэн юм'),
                         ['Номын сан хаана вэ?', 'Номын сан Тодорхойлолт хаанаас авах вэ?'])

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
        # Round 20: the later part reads as a follow-up of the part before it, which drops «нь».
        plan = planner(class_groups=False).plan('КУ-2 анги хаана хичээллэдэг вэ, ангийн багш нь хэн бэ?')
        self.assertEqual(self.queries(plan), ['КУ-2 анги хаана хичээллэдэг вэ?', 'КУ-2 ангийн багш хэн бэ?'])
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
        # A time-bound question is a timetable question, not the registered room: since 11/25 it asks that day's
        # lessons with their rooms (it used to be left as asked, and was then refused as «today's state»).
        self.assertEqual(self.queries(p.plan('КУ-2 өнөөдөр хаана хичээллэх вэ?')), ['КУ-2 анги өнөөдөр хэдэн цагт хичээлтэй вэ?'])

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

    def test_sentences_after_a_named_teacher_are_about_that_teacher(self):
        # The user's example, 11/25: three short sentences, a particle after «багш», a department before the name.
        p = planner()
        plan = p.plan('Компьютерийн ухааны сэлмаа багш чинь хэн бэ? Хэдэн давхарт байдаг вэ? Яаж уулзах вэ?')
        self.assertEqual(self.queries(plan), ['Б.Сэлмаа багш гэж хэн бэ?', 'Б.Сэлмаа багштай яаж уулзах вэ?'])
        # The floor question is answered by the card: it is listed with the card's own question, not lost.
        self.assertEqual(plan['parts'][0]['original'], 'Компьютерийн ухааны сэлмаа багш чинь хэн бэ? Хэдэн давхарт байдаг вэ?')
        self.assertEqual(self.queries(p.plan('Сэлмаа гэдэг багш хаана суудаг вэ? Имэйл нь юу вэ?')),
                         ['Б.Сэлмаа багшийн өрөө хаана вэ?', 'Б.Сэлмаа багшийн имэйл?'])
        self.assertEqual(self.queries(p.plan('Сэлмаа багш хэн бэ? Хаана суудаг вэ? Имэйл нь юу вэ? Юу заадаг вэ?')),
                         ['Б.Сэлмаа багш гэж хэн бэ?'])
        # A sentence with a subject of its own is a question of its own.
        self.assertEqual(self.queries(p.plan('Сэлмаа багш хэн бэ? Сургалтын төлбөр хэд вэ?'))[1], 'Сургалтын төлбөр хэд вэ?')

    def test_a_given_name_with_a_post_or_alone_before_a_question_about_a_person(self):
        p = planner()
        self.assertEqual(self.queries(p.plan('Сэлмаа эрхлэгч хаана суудаг вэ?')), ['Б.Сэлмаа багшийн өрөө хаана вэ?'])
        self.assertEqual(self.queries(p.plan('Сэлмаа хэдэн давхарт суудаг вэ?')), ['Б.Сэлмаа багшийн өрөө хаана вэ?'])
        self.assertEqual(self.queries(p.plan('Сэлмаатай яаж уулзах вэ?')), ['Б.Сэлмаа багштай яаж уулзах вэ?'])
        self.assertEqual(self.queries(p.plan('Сэлмаа багш аль ангийн багш вэ?')), ['Б.Сэлмаа багш гэж хэн бэ?'])
        unknown = p.plan('Байхгүй хаана суудаг вэ?')                            # not a name in the staff table
        self.assertFalse(any(rewrite['rule'] == 'staff_name' for part in unknown['parts'] for rewrite in part['rewrites']))

    def test_desk_wordings_for_a_room_a_subject_an_office_and_a_department_head(self):
        p = planner()
        self.assertEqual(self.queries(p.plan('604 тоотод хэн суудаг вэ?')), ['604 тоот хаана вэ?'])
        self.assertEqual(self.queries(p.plan('Програмчлал хэн заадаг вэ?')), ['Програмчлал хичээлийг хэн заадаг вэ?'])
        self.assertEqual(self.queries(p.plan('Оюутны албаны хүн хэн бэ?')), ['Оюутны албаны ажилтан хэн бэ?'])
        self.assertEqual(self.queries(p.plan('Оюутны албанд хэн ажилладаг вэ?')), ['Оюутны албаны ажилтан хэн бэ?'])
        self.assertEqual(self.queries(p.plan('Механик инженерийн тэнхимийн эрхлэгч хаана суудаг вэ?')),
                         ['Механик инженерийн тэнхимийн эрхлэгчтэй яаж уулзах вэ?'])

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
        # 11/25: every way of asking to meet a named teacher gets the meeting card (room, timetable now, recorded
        # meeting hours or how to arrange it); before, «одоо» gave the timetable alone and «хэзээ» nothing.
        for asked in ('Сэлмаа багштай одоо уулзаж болох уу?', 'Сэлмаа багштай хэзээ уулзаж болох вэ?',
                      'Сэлмаа багштай яаж уулзах вэ?', 'сэлмаа багшийг хайж байна', 'Сэлмаа багш дээр очих гэсэн юм',
                      'Сэлмаа багш одоо өрөөндөө байгаа юу?', 'Сэлмаа багш чинь хаана байгаа вэ?'):
            with self.subTest(asked=asked):
                self.assertEqual(self.queries(p.plan(asked)), ['Б.Сэлмаа багштай яаж уулзах вэ?'])
        self.assertEqual(self.queries(p.plan('Сэлмаа багш одоо хичээлтэй юу?')), ['Б.Сэлмаа багш одоо хичээлтэй юу?'])
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
        # 11/25: «хэзээ / хэдэн цагт хичээлтэй» is today's lessons with their times, «хичээл нь хаана» their rooms
        # (both were left as asked and found nothing).
        self.assertEqual(self.queries(p.plan('Сэлмаа багш хэзээ хичээлтэй вэ?')), ['Б.Сэлмаа багш өнөөдөр хичээлтэй юу?'])
        self.assertEqual(self.queries(p.plan('Сэлмаа багш хэдэн цагт хичээлтэй вэ?')), ['Б.Сэлмаа багш өнөөдөр хичээлтэй юу?'])
        self.assertEqual(self.queries(p.plan('Сэлмаа багшийн хичээл хаана ордог вэ?')),
                         ['Б.Сэлмаа багш өнөөдөр хаана хичээл заах вэ?'])
        # 11/17 (5): a named day goes to that day's timetable wording, never to «now» or the office.
        self.assertEqual(self.queries(p.plan('Сэлмаа багш даваа гарагт хаана байна вэ?')),
                         ['Б.Сэлмаа багш даваа гарагт хичээлтэй юу?'])
        # 11/26: a meeting on a named day is answered with that day's lessons and free stretches (teacher_time_parts),
        # so the words stay as asked, the name first.
        self.assertEqual(self.queries(p.plan('Сэлмаа багштай өнөөдөр уулзаж болох уу?')),
                         ['Б.Сэлмаа багш өнөөдөр уулзаж болох уу?'])
        self.assertEqual(self.queries(p.plan('Сэлмаа багш 15:00 цагт хаана байна вэ?')),
                         ['Б.Сэлмаа багш 15:00 цагт хаана байна вэ?'])
        # Review 11/17 (5): a teacher named like a weekday («А.Даваа») is not read as that day; since 11/25 the
        # question gets the meeting card.
        self.assertEqual(self.queries(p.plan('А.Даваа багштай уулзаж болох уу?')), ['А.Даваа багштай яаж уулзах вэ?'])

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
        self.assertIn('Энэ талаар мэдээлэл олдсонгүй.', result['answer'])
        self.assertEqual(result['reason_code'], 'compound_parts_partly_answered')
        self.assertEqual(result['referral']['text'], 'Ресепшний ажилтнаас асууна уу.')
        self.assertEqual([p['answered'] for p in result['parts']], [True, False])
        self.assertFalse(result['generated'])



class ComposeWordingTests(unittest.TestCase):
    """11/23 check set (Q14, Q22, Q24): one stored answer is shown once; nothing found is said before where to ask."""

    def test_the_same_answer_for_two_parts_is_shown_once_under_both_questions(self):
        plan = planner().plan('Сургалтын төлбөр хэд вэ, хэсэгчлэн төлж болох уу?')
        same = dict(answer='Жилд 8,280,000 ₮.', route='B', reason_code='x',
                    citations=[{'url': 'https://nmct.edu.mn/elselt'}], llm_calls=0)
        result = compose('Сургалтын төлбөр хэд вэ, хэсэгчлэн төлж болох уу?', plan, [dict(same), dict(same)])
        self.assertEqual(result['answer'], 'Сургалтын төлбөр хэд вэ? Хэсэгчлэн төлж болох уу?\nЖилд 8,280,000 ₮.')

    def test_nothing_answered_says_so_before_the_referral(self):
        plan = planner().plan('Сургалтын төлбөр хэд вэ, хэсэгчлэн төлж болох уу?')
        missing = dict(answer=None, route='E', reason_code='website_no_evidence', citations=[], llm_calls=0,
                       referral=dict(text='Лавлах газар: Санхүүгийн алба (8-р давхар).'))
        result = compose('Сургалтын төлбөр хэд вэ, хэсэгчлэн төлж болох уу?', plan, [dict(missing), dict(missing)])
        self.assertEqual(result['reason_code'], 'compound_parts_not_answered')
        self.assertEqual(result['message'], 'Энэ талаар мэдээлэл олдсонгүй. Лавлах газар: Санхүүгийн алба (8-р давхар).')



class TimedFollowupTests(unittest.TestCase):
    """11/28, the user's test: the third sentence named a day by its number and an hour, and went to the website."""

    def test_a_day_or_hour_sentence_is_about_the_person_named_before(self):
        plan = planner().plan('Сэлмаа багш гэж хэн бэ? Хэзээ уулзаж болох вэ? 1 дэхь өдөр 09:00 цагт уулзах боломжтой болов уу?')
        third = plan['parts'][-1]['query']
        self.assertTrue(third.startswith('Б.Сэлмаа багш'), third)
        self.assertIn('даваа гараг', third)
        for later in ('Даваа гарагт 9 цагт уулзах боломжтой юу?', 'Маргааш 10 цагт завтай юу?',
                      'Өглөө 9 цагт өрөөндөө байх уу?', 'Хоёрдахь өдөр хичээлтэй юу?'):
            parts = planner().plan('Сэлмаа багш хаана суудаг вэ? ' + later)['parts']
            self.assertTrue(parts[-1]['query'].startswith('Б.Сэлмаа багш'), (later, parts[-1]['query']))



class HyphenatedNameTests(unittest.TestCase):
    def test_a_hyphenated_given_name_alone(self):
        plan = QuestionPlanner(enabled=True, split_compound=True, class_groups=True, staff_names=True,
                               given_names={'цэнд-очир': 'Т.Цэнд-Очир'}, offices=[], topic_keywords=[], staff=[],
                               class_names=[])
        self.assertEqual(plan.plan('Цэнд-Очир гэж хэн бэ?')['parts'][0]['query'], 'Т.Цэнд-Очир гэж хэн бэ?')



class LongFollowupTests(unittest.TestCase):
    """11/28 (2), the user's test: a follow-up of several questions after a teacher lost the teacher, glued the first
    part's hour and verb into the later parts and answered «олдсонгүй»."""

    def plan(self):
        return QuestionPlanner(enabled=True, split_compound=True, class_groups=True, staff_names=True,
                               given_names={'соронзонболд': 'Н.Соронзонболд'}, offices=['Номын сан'],
                               topic_keywords=['төлбөр', 'имэйл', 'өрөө', 'давхар', 'анги', 'багш', 'хаяг'],
                               staff=['Н.Соронзонболд', 'И.Уянга', 'Б.Уянга'], class_names=['КУ-2'])

    def parts(self, text, previous):
        return [part['query'] for part in self.plan().plan(text, previous=previous)['parts']]

    def test_every_part_of_a_long_followup_is_about_the_teacher(self):
        parts = self.parts('2 дахь өдөр 11 цагийн үед уулзвал өрөөндөө байх уу, өрөө нь хаана байдаг вэ, бусад багш нар нь хэн бэ',
                           'соронзонболд багш гэж хэн бэ,')
        self.assertEqual(len(parts), 3, parts)
        self.assertTrue(all(part.startswith('Н.Соронзонболд багш') for part in parts), parts)
        self.assertIn('мягмар', parts[0])
        self.assertNotIn('11 цаг', parts[1])                     # the first part's hour stays in the first part
        self.assertEqual(parts[2], 'Н.Соронзонболд багшийн тэнхимийн бусад багш нар хэн бэ?')
        self.assertEqual(self.parts('бусад багш нар нь хэн бэ', 'соронзонболд багш гэж хэн бэ?'),
                         ['Н.Соронзонболд багшийн тэнхимийн бусад багш нар хэн бэ?'])

    def test_no_hour_or_verb_is_carried_as_a_subject(self):
        parts = self.parts('Маргааш 10 цагт уулзаж болох уу, имэйл нь юу вэ', 'Соронзонболд багш хаана суудаг вэ?')
        self.assertEqual(parts[1], 'Н.Соронзонболд багшийн имэйл?')

    def test_unpunctuated_yes_no_with_ju_is_cut(self):
        parts = self.parts('даваа гарагт завтай юу ямар хичээл заадаг вэ', 'Соронзонболд багш гэж хэн бэ?')
        self.assertEqual(len(parts), 2, parts)

    def test_a_shared_given_name_is_kept(self):
        parts = self.parts('ямар хичээл заадаг вэ, хэдэн давхарт суудаг вэ?', 'Уянга багш гэж хэн бэ?')
        self.assertTrue(all(part.startswith('Уянга багш') for part in parts), parts)

    def test_a_new_question_after_a_teacher_keeps_its_own_subject(self):
        for text in ('Сургуулийн хаяг хаана вэ', '604 тоот хаана байдаг вэ', 'Сургуулийн төлбөр хэд вэ, хэсэгчлэн төлж болох уу'):
            for part in self.parts(text, 'соронзонболд багш гэж хэн бэ?'):
                self.assertNotIn('Соронзонболд', part, (text, part))

    def test_an_office_named_before_reaches_every_part(self):
        self.assertEqual(self.parts('Хэдэн цагт ажилладаг вэ, хэн ажилладаг вэ', 'Номын сан хаана байдаг вэ?'),
                         ['Номын сан хэдэн цагт ажилладаг вэ?', 'Номын сан хэн ажилладаг вэ?'])
        self.assertEqual(len(self.parts('Өрөө нь хаана вэ, имэйл нь?', 'КУ-2 ангийн багш хэн бэ?')), 2)



class LongChatTests(unittest.TestCase):
    """11/28 (3), the user's long chat: «тэгвэл очиж уулзая гэвэл хэнтэй уулзах вэ» after an admissions question, the
    accreditation question after «хүүхэд маань төгсөөд …», a dormitory price, a department named before."""

    def plan(self):
        return QuestionPlanner(enabled=True, split_compound=True, class_groups=True, staff_names=True,
                               given_names={'соронзонболд': 'Н.Соронзонболд'}, offices=['Сургалтын алба'],
                               topic_keywords=['төлбөр', 'имэйл', 'өрөө', 'давхар', 'анги', 'багш', 'магадлан'],
                               staff=['Н.Соронзонболд'], class_names=['КУ-2'])

    def parts(self, text, previous=None):
        return [part['query'] for part in self.plan().plan(text, previous=previous)['parts']]

    def test_who_to_go_to_takes_the_previous_topic_or_person(self):
        parts = self.parts('тэгвэл очиж уулзая гэвэл хэнтэй уулзах вэ', 'хэддүгээр ангиас ордог вэ энэ сургуулийн онцлог нь яг юу юм')
        self.assertEqual(len(parts), 1, parts)
        self.assertTrue(parts[0].startswith('хэддүгээр ангиас ордог'), parts)
        self.assertTrue(parts[0].endswith('хэнд хандах вэ?'), parts)
        self.assertEqual(self.parts('хэнтэй уулзах вэ', 'соронзонболд багш гэж хэн бэ'), ['Н.Соронзонболд багштай яаж уулзах вэ?'])
        self.assertEqual(self.parts('тэгвэл тэр хүнтэй яаж уулзах вэ', 'механик тэнхимийн эрхлэгч хэн бэ?'),
                         ['механик тэнхимийн эрхлэгчтэй яаж уулзах вэ'])

    def test_a_verb_phrase_of_the_previous_question_is_no_subject(self):
        self.assertEqual(self.parts('магадлал нь итгэмжлэл хэзээ авсан бэ', 'хүүхэд маань төгсөөд хаана ажиллах вэ'),
                         ['магадлан итгэмжлэл хэзээ авсан бэ'])

    def test_the_verb_of_being_is_not_carried(self):
        self.assertEqual(self.parts('дотуур байр байдаг уу, хэдэн төгрөг вэ'), ['дотуур байр байдаг уу?', 'дотуур байр хэдэн төгрөг вэ?'])

    def test_a_department_named_before(self):
        self.assertEqual(self.parts('эрхлэгч нь хэн бэ, өрөө нь хаана вэ', 'механик тэнхимийн багш нар хэн бэ'),
                         ['механик тэнхимийн эрхлэгч хэн бэ?', 'механик тэнхимийн эрхлэгч хаана вэ?'])

    def test_the_next_question_refers_to_the_office_or_the_last_part(self):
        from question_planner import context_for
        self.assertEqual(context_for(dict(reason_code='referral_office',
                                          referral=dict(office='Сургалтын алба (4-р давхар, 406 тоот)'))), 'Сургалтын алба хаана байдаг вэ?')
        plan = self.plan().plan('Соронзонболд багш хаана суудаг вэ, имэйл нь юу вэ')
        self.assertEqual(context_for({}, plan), ' '.join(part['query'] for part in plan['parts']))
        self.assertEqual(context_for(dict(reason_code='reception_service_lookup', answer='Санхүүгийн алба: 8-р давхар, 804 тоот.')),
                         'Санхүүгийн алба хаана байдаг вэ?')
        self.assertIsNone(context_for({}, None))



class StatementTests(unittest.TestCase):
    """11/28 (4), the user: a sentence with no question («хүүхэд маань КУ-2 ангид сурдаг») asks back what they want to know."""

    def test_a_sentence_naming_a_class_or_teacher(self):
        plan = QuestionPlanner(enabled=True, split_compound=True, class_groups=True, staff_names=True,
                               given_names={'сэлмаа': 'Б.Сэлмаа'}, offices=['Номын сан'], topic_keywords=[],
                               staff=['Б.Сэлмаа'], class_names=['КУ-2'])
        ask = lambda text: plan.plan(text)['parts'][0]['query']
        self.assertEqual(ask('сайн байна уу хүүхэд маань КУ-2 ангид сурдаг'), 'КУ-2 анги — юу мэдэх вэ?')
        self.assertEqual(ask('Сэлмаа багш манай ангийн багш'), 'Б.Сэлмаа багш — юу мэдэх вэ?')
        for kept in ('Номын сан', 'КУ-2 ангийн хуваарийг харуулаач', 'сургуулийн тодорхойлолт авах гэсэн юм', 'баярлалаа'):
            self.assertNotIn('юу мэдэх вэ', ask(kept), kept)


if __name__ == '__main__':
    unittest.main()
