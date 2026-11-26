"""Complete reception answers, the «who is …» wording and the label-only excerpt guard (2026-11-25).

FAKE records only: invented names, no real school data, no server, no network.
"""
from datetime import date, datetime
import unittest

from answer_presentation import is_fragment, withhold_fragment
from question_planner import QuestionPlanner
from reception_tables import ClassGroup, Lesson, ReceptionAnswerPath, ReceptionTables, Room, Service, Staff

NOW = datetime(2026, 11, 25, 10, 0)     # a Wednesday


def tables():
    return ReceptionTables(
        rooms=(Room(floor=6, name='604', purpose='Багш нарын өрөө', department='Зохиомол тэнхим'),
               Room(floor=4, name='406', purpose='Алба',
                    services=(Service(name='Зохиомол алба', office_hours='08:00–17:00', contact='—'),)),
               Room(floor=6, name='612', purpose='Анги')),
        staff=(Staff(name='З.Наран', department='Зохиомол тэнхим', room='604', role='Зохиомол тэнхимийн эрхлэгч',
                     email='naran@school.example'),
               Staff(name='З.Саран', department='Зохиомол тэнхим', room='604', role='Математикийн багш',
                     email='saran@school.example'),
               Staff(name='З.Тэмүүлэн', department='Зохиомол алба', room='406', role='Мэргэжилтэн',
                     email='temuulen@school.example')),
        classes=(ClassGroup(group='ЗА-1', room='612', course='1', department='Зохиомол тэнхим', teacher='З.Саран'),),
        timetable=(Lesson(day='wed', time='09:35-11:05', group='ЗА-1', room='612', teacher='З.Наран', subject='Алгоритм'),
                   Lesson(day='mon', time='08:00-09:30', group='ЗА-1', room='612', teacher='З.Саран', subject='Математик')),
        timetable_complete=True, dataset_label='FAKE only')


def path(complete=True):
    return ReceptionAnswerPath(tables(), enabled=True, complete=complete)


def planner():
    names = {'наран': 'З.Наран', 'саран': 'З.Саран', 'тэмүүлэн': 'З.Тэмүүлэн'}
    return QuestionPlanner(enabled=True, split_compound=True, class_groups=True, staff_names=True, given_names=names,
                           staff=names.values(), class_names=['ЗА-1'], offices=['Зохиомол алба'])


class PersonAnswerTests(unittest.TestCase):
    def test_who_is_a_teacher_gives_post_room_email_subjects_and_todays_lessons(self):
        result = path().answer('З.Наран багш гэж хэн бэ?', now=NOW)
        self.assertEqual(result['reason_code'], 'reception_person')
        lines = result['answer'].split('\n')
        self.assertEqual(lines[0], 'З.Наран — Зохиомол тэнхимийн эрхлэгч.')
        self.assertIn('Ажлын өрөө: 604 тоот, 6-р давхар', lines)
        self.assertIn('Сургуулийн имэйл: naran@school.example', lines)
        self.assertIn('Заадаг хичээл: Алгоритм (ЗА-1)', lines)
        self.assertIn('Өнөөдрийн хичээл (лхагва): 09:35-11:05 Алгоритм (ЗА-1; 612 тоот)', lines)
        self.assertEqual(lines[-1], 'Хуваарь өөрчлөгдөж болно. Яг одоо өрөөндөө байгаа эсэхийг мэдэх боломжгүй.')

    def test_the_name_alone_and_about_wordings_ask_the_same(self):
        expected = path().answer('З.Наран багш гэж хэн бэ?', now=NOW)['answer']
        for wording in ('З.Наран', 'З.Наран багш', 'З.Наран гэж хэн бэ', 'З.Наран багшийн талаар хэлж өгөөч',
                        'З.Наран багш хэн бэ?'):
            with self.subTest(wording=wording):
                self.assertEqual(path().answer(wording, now=NOW)['answer'], expected)

    def test_a_staff_member_who_does_not_teach_has_no_lesson_lines(self):
        answer = path().answer('З.Тэмүүлэн гэж хэн бэ?', now=NOW)['answer']
        self.assertTrue(answer.startswith('З.Тэмүүлэн — Мэргэжилтэн (Зохиомол алба).'))
        self.assertIn('Ажлын өрөө: 406 тоот, 4-р давхар', answer)
        self.assertNotIn('хичээл', answer)

    def test_a_name_outside_the_staff_table_is_not_claimed(self):
        reception = path()
        self.assertFalse(reception.recognizes('З.Тэнгэр багш гэж хэн бэ?'))
        self.assertIsNone(reception.answer('З.Тэнгэр багш гэж хэн бэ?', now=NOW))

    def test_a_subject_question_is_not_read_as_a_person(self):
        result = path().answer('Математикийн багш хэн бэ?', now=NOW)
        self.assertEqual(result['reason_code'], 'reception_subject_teachers')
        self.assertIn('Математикийн багш: З.Саран — ажлын өрөө 604 тоот (6-р давхар)', result['answer'])

    def test_the_switch_off_keeps_the_short_answer(self):
        self.assertEqual(path(complete=False).answer('З.Наран багш гэж хэн бэ?', now=NOW)['answer'],
                         'З.Наран — Зохиомол тэнхимийн эрхлэгч.')
        self.assertNotIn('\n', path(complete=False).answer('З.Саран багшийн өрөө хаана вэ?', now=NOW)['answer'])

    def test_a_room_question_adds_post_email_and_today(self):
        result = path().answer('З.Саран багшийн өрөө хаана вэ?', now=NOW)
        lines = result['answer'].split('\n')
        self.assertEqual(result['reason_code'], 'reception_teacher_office')
        self.assertEqual(lines[0], 'З.Саран — ажлын өрөө: 604, 6-р давхар.')
        self.assertIn('Албан тушаал: Математикийн багш (Зохиомол тэнхим)', lines)
        self.assertIn('Сургуулийн имэйл: saran@school.example', lines)
        self.assertIn('Өнөөдөр (лхагва): хуваарьт хичээлгүй', lines)
        self.assertEqual(result['answer'].count('Яг одоо өрөөндөө байгаа эсэхийг мэдэх боломжгүй.'), 1)

    def test_without_a_clock_no_line_about_today(self):
        self.assertNotIn('Өнөөд', path().answer('З.Наран багш гэж хэн бэ?')['answer'])


class MeetingAnswerTests(unittest.TestCase):
    """«… багштай яаж уулзах вэ?»: the room, what the timetable says now, how to arrange it; presence never claimed."""
    def test_the_meeting_card_of_a_teacher(self):
        query = 'З.Наран багштай яаж уулзах вэ?'
        self.assertTrue(path().recognizes(query))
        result = path().answer(query, now=NOW)
        self.assertEqual(result['reason_code'], 'reception_teacher_meet')
        answer = result['answer']
        self.assertTrue(answer.startswith('З.Наран — Зохиомол тэнхимийн эрхлэгч.'))
        # No school hours in this fixture: the timetable's status now and today's lessons, as before 11/26 (the day's
        # schedule with its free stretches needs the confirmed hours — MeetingScheduleTests).
        for expected in ('604', 'Хуваариар бол', 'naran@school.example', 'Өнөөдрийн хичээл'):
            self.assertIn(expected, answer)
        self.assertEqual(answer.count('мэдэх боломжгүй') + answer.count('батлахгүй'), 1)      # one sentence about presence

    def test_a_stranger_named_as_a_teacher_is_not_answered_with_subject_teachers(self):
        # «Мат» opened «Математик» when a short word was cut to three letters: a stranger got that subject's teachers.
        result = path().answer('Мате багшийн өрөө хаана вэ?', now=NOW)
        self.assertFalse(result and result.get('answer'))


def calendar_path(complete=True):
    """The fixture with a calendar: the term, 11/26 a holiday, the school's hours and lunch break, and a Friday lesson."""
    made = tables()
    return ReceptionAnswerPath(ReceptionTables(
        rooms=made.rooms, staff=made.staff, classes=made.classes,
        timetable=made.timetable + (Lesson(day='fri', time='13:30-15:00', group='ЗА-1', room='612', teacher='З.Наран',
                                           subject='Алгоритм'),),
        timetable_complete=True, dataset_label='FAKE only', term_start=date(2026, 9, 7), term_end=date(2026, 12, 25),
        holidays=(date(2026, 11, 26),), calendar_bound=True, holidays_reviewed=True, school_hours='08:00–17:00',
        lunch_break='12:40–13:20'), enabled=True, complete=complete)


class MeetingScheduleTests(unittest.TestCase):
    """11/26, the user: «уулзах цаг … хичээлийн хуваарийг оруулсан … тэндээс шүүгээд хичээлтэй үгүй юу гэдгийг хар»."""
    def card(self, now, query='З.Наран багштай яаж уулзах вэ?'):
        return calendar_path().answer(query, now=now)

    def test_a_school_day_lists_the_lessons_left_and_the_free_stretches(self):
        answer = self.card(datetime(2026, 11, 25, 10, 0))['answer']
        self.assertIn('Хуваариар өнөөдөр (лхагва, 11/25), 10:00-аас хойш: хичээлтэй — 09:35–11:05 ЗА-1 (612 тоот); '
                      'хичээлгүй — 11:05–17:00 (сургуулийн цайны цаг 12:40–13:20).', answer)

    def test_a_holiday_shows_the_next_school_day(self):
        answer = self.card(datetime(2026, 11, 26, 9, 0))['answer']
        self.assertIn('Өнөөдөр амралтын өдөр. Хуваариар дараагийн хичээлийн өдөр — баасан (11/27): хичээлтэй — '
                      '13:30–15:00 ЗА-1 (612 тоот); хичээлгүй — 08:00–13:30, 15:00–17:00 (сургуулийн цайны цаг 12:40–13:20).',
                      answer)
        self.assertNotIn('одоо хичээлтэй', answer)

    def test_after_hours_and_at_the_weekend_the_next_school_day(self):
        after = self.card(datetime(2026, 11, 27, 18, 0))['answer']
        self.assertIn('Өнөөдрийн ажлын цаг (08:00–17:00) дууссан. Хуваариар дараагийн хичээлийн өдөр — даваа (11/30) '
                      'хичээлгүй.', after)
        weekend = self.card(datetime(2026, 11, 28, 11, 0))['answer']
        self.assertIn('Өнөөдөр бямба гараг. Хуваариар дараагийн хичээлийн өдөр — даваа (11/30) хичээлгүй.', weekend)

    def test_where_now_on_a_holiday_gives_the_office_and_the_next_school_day(self):
        result = self.card(datetime(2026, 11, 26, 9, 0), 'З.Наран багш хаана байна')
        self.assertEqual(result['reason_code'], 'reception_teacher_schedule')
        # The asked fact first, then the post and the office.
        self.assertTrue(result['answer'].startswith('З.Наран — өнөөдөр амралтын өдөр. Хуваариар дараагийн хичээлийн өдөр — '
                                                    'баасан (11/27)'), result['answer'])
        for expected in ('Албан тушаал: Зохиомол тэнхимийн эрхлэгч.', 'Ажлын өрөө: 604 тоот, 6-р давхар.',
                         'Яг одоо хаана байгааг мэдэх боломжгүй', 'naran@school.example'):
            self.assertIn(expected, result['answer'])
        in_class = self.card(datetime(2026, 11, 26, 9, 0), 'З.Наран багш одоо хичээлтэй юу')
        self.assertEqual(in_class['reason_code'], 'reception_teacher_schedule')
        # Switched off, the short holiday answer stays.
        short = calendar_path(complete=False).answer('З.Наран багш хаана байна', now=datetime(2026, 11, 26, 9, 0))
        self.assertIsNone(short['answer'])

    def test_the_end_of_the_term_is_said_not_free(self):
        answer = self.card(datetime(2026, 12, 25, 18, 0), 'З.Наран багш хаана байна')['answer']
        self.assertIn('Энэ улирлын хуваарь 2026-12-25-нд дууссан; дараагийн хичээлийн өдрийн хуваарь бүртгэгдээгүй.', answer)
        self.assertNotIn('чөлөөтэй', answer)

    def test_an_impossible_lunch_time_does_not_break_the_card(self):
        made = calendar_path()
        made.tables = ReceptionTables(**{**made.tables.__dict__, 'lunch_break': '12:60-13:20'})
        answer = made.answer('З.Наран багштай яаж уулзах вэ?', now=datetime(2026, 11, 25, 10, 0))['answer']
        self.assertIn('хичээлгүй — 11:05–17:00.', answer)

    def test_switched_off_the_non_teaching_card_keeps_its_status(self):
        answer = calendar_path(complete=False).answer('З.Тэмүүлэн багштай яаж уулзах вэ?',
                                                      now=datetime(2026, 11, 25, 10, 0))['answer']
        self.assertIn('Хуваариар бол', answer)

    def test_staff_who_do_not_teach_get_no_timetable(self):
        result = self.card(datetime(2026, 11, 25, 10, 0), 'З.Тэмүүлэн багштай яаж уулзах вэ?')
        self.assertEqual(result['reason_code'], 'reception_teacher_meet')
        self.assertNotIn('Хуваариар', result['answer'])          # not «хичээлгүй (чөлөөтэй)» for someone who teaches none
        self.assertIn('temuulen@school.example', result['answer'])


class TeacherAtATimeTests(unittest.TestCase):
    """11/26 (3), the user: «хичээлийн хуваарь хараад тэр асуусан цагт хичээлтэй үгүйг хэл»."""
    NOW = datetime(2026, 11, 25, 8, 30)      # a Wednesday morning; З.Наран teaches Wed 09:35–11:05 and Fri 13:30–15:00

    def ask(self, question, now=None):
        asked = planner().plan(question)['parts'][0]['query']
        return calendar_path().answer(asked, now=now or self.NOW)

    def test_an_hour_inside_and_outside_a_lesson(self):
        busy = self.ask('З.Наран багш 10 цагт хичээлтэй юу')
        self.assertEqual(busy['reason_code'], 'reception_teacher_at')
        self.assertTrue(busy['answer'].startswith('З.Наран — өнөөдөр (лхагва, 11/25) 10:00-д хуваариар хичээлтэй: '
                                                  '09:35–11:05 ЗА-1 (612 тоот). Одооноос (08:30): '), busy['answer'])
        free = self.ask('З.Наран багш 14:30-д хичээлтэй юу')['answer']
        # Not in a lesson: the office is named, once (the user, 11/26: «in room or in lesson»).
        self.assertTrue(free.startswith('З.Наран — өнөөдөр (лхагва, 11/25) 14:30-д хуваариар хичээлгүй — ажлын өрөө: 604 тоот, '
                                        '6-р давхар. Одооноос (08:30): хичээлтэй — 09:35–11:05 ЗА-1 (612 тоот); хичээлгүй — '
                                        '08:30–09:35, 11:05–17:00'), free)
        self.assertEqual(free.count('604 тоот'), 1)
        early = self.ask('З.Наран багш 9 цагийн үед завтай юу')['answer']             # «цагийн үед» is an hour
        self.assertTrue(early.startswith('З.Наран — өнөөдөр (лхагва, 11/25) 09:00-д хуваариар хичээлгүй — ажлын өрөө: 604 тоот, '
                                         '6-р давхар (дараагийн хичээл 09:35-д).'), early)
        # «2 цагт» at a school is the afternoon; the name need not come first, the day may stand anywhere.
        for wording in ('Наран багштай баасан гарагт 2 цагт уулзаж болох уу', 'Баасан гарагт 2 цагт Наран багш хичээлтэй юу'):
            friday = self.ask(wording)['answer']
            self.assertTrue(friday.startswith('З.Наран — нөгөөдөр (баасан, 11/27) 14:00-д хуваариар хичээлтэй: '
                                              '13:30–15:00 ЗА-1 (612 тоот). Тэр өдөр: '), friday)
        for answer in (busy['answer'], free, friday):
            self.assertEqual(answer.count('мэдэх боломжгүй') + answer.count('батлахгүй'), 1)

    def test_a_holiday_a_weekend_and_when_free(self):
        holiday = self.ask('З.Наран багш маргааш 10 цагт завтай юу')['answer']       # 11/26 is the fixture's holiday
        self.assertIn('маргааш (пүрэв, 11/26) нь амралтын өдөр; хуваарьт хичээлгүй. Дараагийн хичээлийн өдөр — нөгөөдөр '
                      '(баасан, 11/27): хичээлтэй — 13:30–15:00 ЗА-1 (612 тоот)', holiday)
        weekend = self.ask('З.Наран багш бямба гарагт 10 цагт хичээлтэй юу')['answer']
        self.assertIn('бямба (11/28) нь хичээлийн өдөр биш; хуваарьт хичээлгүй. Дараагийн хичээлийн өдөр — даваа (11/30): '
                      'хичээлгүй.', weekend)
        when = self.ask('З.Наран багш хэзээ чөлөөтэй вэ')['answer']
        self.assertIn('өнөөдөр (лхагва, 11/25), 08:30-аас хойш хуваариар: хичээлтэй — 09:35–11:05 ЗА-1 (612 тоот); '
                      'хичээлгүй — 08:30–09:35, 11:05–17:00', when)

    def test_time_that_has_passed_is_said(self):
        past = self.ask('З.Наран багш 10 цагт хичээлтэй юу', datetime(2026, 11, 25, 16, 0))['answer']
        self.assertIn('10:00-д хуваариар хичээлтэй: 09:35–11:05 ЗА-1 (612 тоот) — энэ цаг өнгөрсөн. Одооноос (16:00): хичээлгүй.',
                      past)
        evening = self.ask('З.Наран багш 14 цагт завтай юу', datetime(2026, 11, 25, 18, 0))['answer']
        self.assertTrue(evening.startswith('З.Наран — өнөөдрийн ажлын цаг (08:00–17:00) дууссан. Нөгөөдөр (баасан, 11/27) '
                                           '14:00-д хуваариар хичээлтэй: 13:30–15:00 ЗА-1 (612 тоот).'), evening)

    def test_a_date_a_duration_and_office_hours_are_no_clock_hour(self):
        from reception_tables import teacher_time_parts
        for rest in ('12 сарын 4-д завтай юу', '11/27-д 14 цагт хичээлтэй юу', '2 цагийн дараа завтай юу',
                     'хэзээ оюутантай уулздаг вэ', 'одоо хичээлтэй юу', 'завтай юу', 'маргааш хичээлтэй юу',
                     'хэзээ уулзаж болох вэ'):
            self.assertIsNone(teacher_time_parts(rest), rest)
        self.assertEqual(teacher_time_parts('маргааш 10 цагт хичээлтэй юу'), ('маргааш', 600, False))
        self.assertEqual(teacher_time_parts('2 цагт завтай юу'), (None, 840, True))
        # Those questions keep their earlier answers.
        self.assertEqual(self.ask('Наран багш завтай юу')['reason_code'], 'reception_teacher_meet')
        self.assertEqual(self.ask('Наран багштай хэзээ уулзаж болох вэ')['reason_code'], 'reception_teacher_meet')
        self.assertEqual(self.ask('З.Наран багш маргааш хичээлтэй юу')['reason_code'], 'reception_holiday')
        self.assertIsNone(calendar_path()._teacher_time_slots('З.Тэмүүлэн багш 10 цагт хичээлтэй юу'))   # teaches nothing

    def test_the_two_sentences_are_not_shown_when_switched_off(self):
        made = calendar_path()
        made.caveats = False
        for question in ('З.Наран багш 14:30-д хичээлтэй юу', 'З.Наран багштай яаж уулзах вэ', 'З.Наран багш гэж хэн бэ',
                         'З.Наран багшийн өрөө хаана вэ'):
            answer = made.answer(question, now=self.NOW)['answer']
            self.assertNotIn('Хуваарь өөрчлөгдөж болно', answer, question)
            self.assertNotIn('мэдэх боломжгүй', answer, question)
            self.assertIn('604', answer, question)
            self.assertNotIn('  ', answer, question)

    def test_a_past_hour_gets_no_office_or_next_lesson(self):
        late = datetime(2026, 11, 25, 15, 0)
        answer = self.ask('З.Наран багш 9 цагт завтай юу', now=late)['answer']
        self.assertIn('09:00-д хуваариар хичээлгүй — энэ цаг өнгөрсөн.', answer)
        self.assertNotIn('дараагийн хичээл', answer)

    def test_only_a_text_with_such_a_sentence_is_touched(self):
        made = calendar_path()
        made.caveats = False
        kept = made.answer('З.Наран багш гэж хэн бэ', now=self.NOW)['answer']
        self.assertNotIn('мэдэх боломжгүй', kept)
        self.assertNotIn('\n\n', kept)
        self.assertFalse(any(not line.strip() for line in kept.split('\n')), kept)

    def test_where_a_teacher_is_now_is_read_from_the_timetable(self):
        in_lesson = self.ask('З.Наран багш одоо хаана байна', now=datetime(2026, 11, 25, 10, 0))['answer']
        self.assertTrue(in_lesson.startswith('З.Наран — одоо (10:00) хуваариар хичээлтэй: 09:35–11:05 ЗА-1 (612 тоот).'), in_lesson)
        free = self.ask('З.Наран багш яг одоо хаана байгаа вэ', now=datetime(2026, 11, 25, 14, 0))
        self.assertEqual(free['reason_code'], 'reception_teacher_at')
        self.assertTrue(free['answer'].startswith('З.Наран — одоо (14:00) хуваариар хичээлгүй — ажлын өрөө: 604 тоот, 6-р давхар.'),
                        free['answer'])
        after = self.ask('З.Наран багш одоо хаана байна', now=datetime(2026, 11, 25, 18, 0))['answer']
        self.assertIn('ажлын цаг', after)
        self.assertNotIn('одоо (18:00)', after)

    def test_a_joint_lesson_names_all_its_groups(self):
        made = calendar_path()
        made.tables = ReceptionTables(**{**made.tables.__dict__, 'timetable': made.tables.timetable + (
            Lesson(day='wed', time='09:35-11:05', group='ЗА-2', room='612', teacher='З.Наран', subject='Алгоритм'),)})
        answer = made.answer('З.Наран багш 10 цагт хичээлтэй юу', now=self.NOW)['answer']
        self.assertIn('10:00-д хуваариар хичээлтэй: 09:35–11:05 ЗА-1, ЗА-2 (612 тоот).', answer)

    def test_the_cards_show_the_day_a_visitor_can_come_with_the_caveat(self):
        card = self.ask('З.Наран багш гэж хэн бэ', datetime(2026, 11, 26, 9, 0))['answer']
        self.assertIn('Хуваариар дараагийн хичээлийн өдөр — баасан (11/27): хичээлтэй — 13:30–15:00 ЗА-1 (612 тоот)', card)
        office = self.ask('З.Наран багшийн өрөө хаана вэ')['answer']
        self.assertIn('Хуваариар өнөөдөр (лхагва, 11/25), 08:30-аас хойш: хичээлтэй — 09:35–11:05 ЗА-1 (612 тоот)', office)
        self.assertIn('Хуваарь өөрчлөгдөж болно.', office)


class UnrecordedRoomTests(unittest.TestCase):
    def test_a_teacher_without_a_recorded_room_is_still_named_with_the_departments_room(self):
        staff = tables().staff + (Staff(name='З.Номт', department='Зохиомол тэнхим', role='Зохиомол тэнхимийн багш',
                                        email='nomt@school.example'),)
        rooms = tables().rooms[1:] + (Room(floor=6, name='604', purpose='Багш нарын өрөө', department='Зохиомол тэнхим'),)
        made = ReceptionAnswerPath(ReceptionTables(rooms=rooms, staff=staff, classes=tables().classes,
                                                   timetable=tables().timetable, timetable_complete=True,
                                                   dataset_label='FAKE only'), enabled=True, complete=True)
        result = made.answer('З.Номт багшийн өрөө хаана вэ?', now=NOW)
        self.assertEqual(result['reason_code'], 'reception_teacher_office_unrecorded')
        answer = result['answer']
        self.assertTrue(answer.startswith('З.Номт — Зохиомол тэнхимийн багш. Ажлын өрөө нь бүртгэлд алга.'))
        self.assertIn('Тэнхимийн багш нарын өрөө: 604 тоот, 6-р давхар.', answer)
        self.assertIn('nomt@school.example', answer)

    def test_an_office_whose_name_holds_a_comma(self):
        rooms = tables().rooms + (Room(floor=4, name='405', purpose='Алба',
                                       services=(Service(name='Зохиомол хяналт, чанарын алба', office_hours='08:00–17:00',
                                                         contact='—'),)),)
        made = ReceptionAnswerPath(ReceptionTables(rooms=rooms, staff=tables().staff, classes=tables().classes,
                                                   timetable=tables().timetable, timetable_complete=True,
                                                   dataset_label='FAKE only'), enabled=True, complete=True)
        query = 'Зохиомол хяналт, чанарын алба хаана байдаг вэ?'
        self.assertTrue(made.recognizes(query))
        self.assertTrue(made.answer(query, now=NOW)['answer'].startswith('Зохиомол хяналт, чанарын алба: 4-р давхар, 405 тоот.'))
        # A list of two places is not an office's name.
        self.assertFalse(made.recognizes('Зохиомол алба, номын сан хаана байдаг вэ?'))


class PlaceAnswerTests(unittest.TestCase):
    def test_an_office_lists_its_staff_but_its_hours_stay_short(self):
        where = path().answer('Зохиомол алба хаана байдаг вэ?', now=NOW)['answer'].split('\n')
        self.assertEqual(where[0], 'Зохиомол алба: 4-р давхар, 406 тоот. Ажлын цаг 08:00–17:00.')
        self.assertEqual(where[1:], ['Ажилтнууд:', '• З.Тэмүүлэн — Мэргэжилтэн, temuulen@school.example'])
        self.assertNotIn('\n', path().answer('Зохиомол алба хэдэн цагт ажилладаг вэ?', now=NOW)['answer'])

    def test_a_room_names_its_unit_and_who_works_there(self):
        lines = path().answer('604 тоот хаана вэ?', now=NOW)['answer'].split('\n')
        self.assertEqual(lines[0], '604 тоот өрөө 6-р давхарт байрладаг (Багш нарын өрөө).')
        self.assertIn('Харьяалал: Зохиомол тэнхим', lines)
        self.assertIn('Энэ өрөөнд ажилладаг: З.Наран; З.Саран', lines)

    def test_a_class_names_its_teacher_and_todays_lessons(self):
        lines = path().answer('ЗА-1 анги хаана хичээллэдэг вэ?', now=NOW)['answer'].split('\n')
        self.assertIn('Ангийн багш: З.Саран (604 тоот, 6-р давхар; saran@school.example)', lines)
        self.assertIn('Өнөөдрийн хичээл (лхагва): 09:35-11:05 Алгоритм (612 тоот; З.Наран)', lines)

    def test_the_class_teacher_answer_says_where_to_find_the_teacher(self):
        lines = path().answer('ЗА-1 ангийн багш хэн бэ?', now=NOW)['answer'].split('\n')
        self.assertEqual(lines[0], 'ЗА-1 ангийн багш: З.Саран.')
        self.assertIn('Ажлын өрөө: 604 тоот, 6-р давхар', lines)
        self.assertIn('Сургуулийн имэйл: saran@school.example', lines)


class PlannerTests(unittest.TestCase):
    def queries(self, question):
        return [part['query'] for part in planner().plan(question)['parts']]

    def test_who_and_where_in_one_question_is_one_who_question(self):
        # The user's example (2026-11-25), with an invented name.
        self.assertEqual(self.queries('наран багш гэж хэн бэ хаана байдаг вэ'), ['З.Наран багш гэж хэн бэ?'])
        self.assertEqual(self.queries('Наран багш гэж хэн бэ, хаана суудаг вэ?'), ['З.Наран багш гэж хэн бэ?'])

    def test_a_given_name_alone_or_without_the_word_teacher(self):
        self.assertEqual(self.queries('Тэмүүлэн гэж хэн бэ?'), ['З.Тэмүүлэн гэж хэн бэ?'])
        self.assertEqual(self.queries('Саран'), ['З.Саран гэж хэн бэ?'])
        self.assertEqual(self.queries('Наран багшийн талаар мэдээлэл өгөөч'), ['З.Наран багш гэж хэн бэ?'])

    def test_where_a_class_is_today_asks_that_days_lessons(self):
        self.assertEqual(self.queries('ЗА-1 анги өнөөдөр хаана хичээлтэй вэ?'), ['ЗА-1 анги өнөөдөр хэдэн цагт хичээлтэй вэ?'])
        self.assertEqual(self.queries('ЗА-1 анги маргааш хаана хичээллэх вэ?'), ['ЗА-1 анги маргааш хэдэн цагт хичээлтэй вэ?'])
        answer = path().answer('ЗА-1 анги өнөөдөр хэдэн цагт хичээлтэй вэ?', now=NOW)['answer']
        self.assertIn('09:35-11:05 Алгоритм (612 тоот)', answer)
        self.assertIn('Ангийн багш: З.Саран (604 тоот, 6-р давхар; saran@school.example)', answer)

    def test_where_a_class_is_now_gives_the_lesson_in_progress_and_the_next(self):
        for wording in ('ЗА-1 анги одоо хаана байна вэ?', 'ЗА-1 анги одоо хичээлтэй юу?'):
            with self.subTest(wording=wording):
                self.assertEqual(self.queries(wording), ['ЗА-1 анги одоо хаана хичээлтэй вэ?'])
        self.assertEqual(self.queries('ЗА-1 анги одоо хэдэн цаг болж байна'), ['ЗА-1 анги одоо хэдэн цаг болж байна'])
        reception = path()
        during = reception.answer('ЗА-1 анги одоо хаана хичээлтэй вэ?', now=NOW)
        self.assertEqual(during['reason_code'], 'reception_class_now')
        self.assertTrue(during['answer'].startswith('ЗА-1 анги одоо (лхагва 10:00) хуваариар: 09:35-11:05 Алгоритм (612 тоот).'))
        before = reception.answer('ЗА-1 анги одоо хаана хичээлтэй вэ?', now=datetime(2026, 11, 25, 8, 30))['answer']
        self.assertTrue(before.startswith('ЗА-1 анги одоо (лхагва 08:30) хуваариар хичээлгүй. Дараагийн хичээл: 09:35-11:05 Алгоритм (612 тоот).'))
        after = reception.answer('ЗА-1 анги одоо хаана хичээлтэй вэ?', now=datetime(2026, 11, 25, 15, 0))['answer']
        self.assertTrue(after.startswith('ЗА-1 анги одоо (лхагва 15:00) хуваариар хичээлгүй; өнөөдрийн хичээл 11:05-д дууссан.'))
        self.assertIsNone(reception.answer('ЗА-1 анги одоо хаана хичээлтэй вэ?')['answer'])       # no clock: no claim

    def test_who_is_only_directly_after_the_teachers_name(self):
        # Code review 11/25: these named a teacher and held «хэн бэ», «тухай» or «танилцуул» somewhere else.
        for wording, expected in (
                ('Наран багшийн тэнхимийн эрхлэгч хэн бэ?', 'З.Наран багшийн тэнхимийн эрхлэгч хэн бэ?'),
                ('Наран багшийн зурагтай танилцуулгыг үзье.', 'З.Наран багшийн зурагтай танилцуулгыг үзье.'),
                ('Наран багшийн оронд хэн бэ?', 'З.Наран багшийн оронд хэн бэ?')):
            with self.subTest(wording=wording):
                self.assertEqual(self.queries(wording), [expected])
        self.assertEqual(self.queries('Наран багшийг танилцуулна уу'), ['З.Наран багш гэж хэн бэ?'])

    def test_a_part_the_who_answer_does_not_hold_is_still_asked(self):
        self.assertEqual(self.queries('Наран багш гэж хэн бэ, маргааш хичээлтэй юу?'),
                         ['З.Наран багш гэж хэн бэ?', 'З.Наран багш маргааш хичээлтэй юу?'])
        self.assertEqual(self.queries('Наран багш гэж хэн бэ, имэйл нь юу вэ?'), ['З.Наран багш гэж хэн бэ?'])

    def test_other_teacher_questions_keep_their_wording(self):
        self.assertEqual(self.queries('Наран багш хаана суудаг вэ?'), ['З.Наран багшийн өрөө хаана вэ?'])
        self.assertEqual(self.queries('Наран багшийн имэйл юу вэ?'), ['З.Наран багшийн имэйл юу вэ?'])
        self.assertEqual(self.queries('Сургалтын төлбөр хэд вэ?'), ['Сургалтын төлбөр хэд вэ?'])
        self.assertEqual(self.queries('Баярлалаа'), ['Баярлалаа'])


class FragmentTests(unittest.TestCase):
    def test_labels_without_a_sentence_are_a_fragment(self):
        self.assertTrue(is_fragment('Дэлгэрэнгүй\n03\nМеханик инженерийн тэнхим'))
        self.assertTrue(is_fragment('Карьер хөгжлийн төв\nСэтгэл зүйчийн өрөө: 08\nТехникийн өрөө: 09'))
        self.assertFalse(is_fragment('Эрхэм зорилго\nМэргэжлийн болон харилцааны өндөр ур чадвартай инженер хүнийг бэлдэх.'))
        self.assertFalse(is_fragment('Дадлага хийх байгууллагууд:\n• Мултипак ХХК\n• Сейф Трек ХХК'))
        self.assertFalse(is_fragment(''))
        # Code review 11/25: short but whole answers are not labels.
        for answer in ('Сургалтын төлбөр 4,200,000 төгрөг.', 'Тийм, дотуур байртай.', 'Математик, англи хэл',
                       'Хаяг: Улаанбаатар хот, Баянзүрх дүүрэг',
                       'Мэргэжлийн болон харилцааны өндөр ур чадвартай баялаг бүтээгч залуу инженер хүнийг бэлдэх'):
            with self.subTest(answer=answer):
                self.assertFalse(is_fragment(answer))
        self.assertTrue(is_fragment('Япон дах Гашшүкү хөтөлбөр\n2026 оны гуравдугаар сарын 25'))
        self.assertTrue(is_fragment('Магадлан итгэмжлэгдсэн\nБоловсролын магадлан итгэмжлэлийн зөвлөл'))

    def result(self, query, answer, kind='rag_generated'):
        return dict(query=query, answer=answer, answer_kind=kind, route='C', reason_code='source_grounded_generation',
                    citations=[dict(title='x')], message='')

    def test_a_fragment_shown_for_an_open_question_is_withheld(self):
        result = withhold_fragment(self.result('Механик инженерийн хөтөлбөрийн талаар хэлж өгөөч',
                                               'Дэлгэрэнгүй\n03\nМеханик инженерийн тэнхим'))
        self.assertIsNone(result['answer'])
        self.assertEqual((result['route'], result['reason_code']), ('E', 'website_fragment_withheld'))
        self.assertEqual(result['message'], 'Энэ талаар мэдээлэл олдсонгүй.')
        self.assertEqual(result['withheld_answer'], 'Дэлгэрэнгүй\n03\nМеханик инженерийн тэнхим')

    def test_a_value_question_a_sentence_and_other_answer_kinds_are_left(self):
        value = self.result('Олимпиадын бүртгэлийн хураамж хэд вэ?', 'Бүртгэлийн хураамж\n5,000 ₮')
        self.assertEqual(withhold_fragment(dict(value)), value)
        sentence = self.result('Сургуулийн эрхэм зорилго юу вэ?',
                               'Эрхэм зорилго\nМэргэжлийн болон харилцааны өндөр ур чадвартай инженер хүнийг бэлдэх.')
        self.assertEqual(withhold_fragment(dict(sentence)), sentence)
        stored = self.result('Спорт заал байгаа юу?', 'Биеийн тамирын заал', kind='official_website_snapshot')
        self.assertEqual(withhold_fragment(dict(stored)), stored)


class SchoolOverviewTests(unittest.TestCase):
    """A question that names only the school gets the stored introduction when the content holds one."""
    OVERVIEW = 'Зохиомол сургууль бол жишээ сургууль.'

    class Policy:
        enabled = True

        def __init__(self, overview, reason='missing_entity'):
            self.overview, self.reason = overview, reason

        def route(self, db, query, allow_draft=False):
            from rag_runtime import ChatRAG
            answer = self.overview if query == ChatRAG.SCHOOL_OVERVIEW else None
            return dict(query=query, route='B' if answer else 'E', package_id='package1', answer=answer, citations=[],
                        reason_code='official_website_stored_answer' if answer else self.reason, reason_codes=[],
                        clarification=None, exact_matches=[], generated=False, llm_calls=0, message='', answer_kind=None)

    class Retriever:
        calls = 0

        def status(self):
            return dict(available=True, corpus_id='corpus1')

        def search(self, query, limit=4):
            self.calls += 1
            return dict(candidates=[], corpus_id='corpus1', backend='test')

    class Generator:
        def status(self):
            return dict(available=True)

    def chat(self, overview, reason='missing_entity'):
        from faq_intent import FaqIntents
        from rag_runtime import ChatRAG
        retriever = self.Retriever()
        chat = ChatRAG('.', self.Policy(overview, reason), retriever, self.Generator(), reception=ReceptionAnswerPath())
        chat.faq_intents = FaqIntents(enabled=False)      # no stored FAQs behind the fake policy
        return chat, retriever

    def test_a_school_only_question_gets_the_stored_overview(self):
        for query in ('Танай сургуулийн тухай дэлгэрэнгүй мэдээлэл хэлнэ үү.', 'Сургуулийн тухай мэдээлэл'):
            with self.subTest(query=query):
                chat, retriever = self.chat(self.OVERVIEW)
                result = chat.route('content.db', query)
                self.assertEqual(result['answer'], self.OVERVIEW)
                self.assertEqual(result['query'], query)
                self.assertEqual(retriever.calls, 0)

    def test_a_vague_question_without_the_school_still_gets_the_clarifying_question(self):
        # Code review 11/25: «энэ юу вэ?» has no topic word either, and is no question about the school.
        chat, _ = self.chat(self.OVERVIEW, 'no_supported_question_match')
        for query in ('энэ юу вэ?', 'тэгээд?'):
            with self.subTest(query=query):
                result = chat.route('content.db', query)
                self.assertIsNone(result['answer'])
                self.assertEqual(result['reason_code'], 'clarify_topic')
        self.assertEqual(chat.route('content.db', 'ШМТК ямар сургууль вэ?')['answer'], self.OVERVIEW)

    def test_without_a_stored_overview_the_topic_is_asked_as_before(self):
        chat, _ = self.chat(None)
        result = chat.route('content.db', 'Танай сургуулийн тухай дэлгэрэнгүй мэдээлэл хэлнэ үү.')
        self.assertIsNone(result['answer'])
        self.assertEqual(result['reason_code'], 'clarify_topic')


if __name__ == '__main__':
    unittest.main()
