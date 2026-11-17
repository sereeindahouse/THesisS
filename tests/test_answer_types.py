"""Regression checks for the 11/17 (3) fixes: expected answer type, anchor binding,
page-chrome trimming, the whole-word «нийт» marker, and new reception wordings."""
from datetime import date, datetime
import unittest

from answer_types import expected_value, normalise_units, value_supported
from evidence_contract import evidence_units, missing_query_markers
from reception_tables import ClassGroup, Lesson, ReceptionAnswerPath, ReceptionTables, Room, Service, Staff
import rule_selector


class ExpectedValueTests(unittest.TestCase):
    def test_question_kinds(self):
        self.assertEqual(expected_value('Hub Center өдөр бүр хэдэн цаг хүртэл нээлттэй вэ?')[0], 'time')
        self.assertEqual(expected_value('Манай баг ямар байр эзэлсэн бэ?')[0], 'rank')
        self.assertEqual(expected_value('Номын сан хэддүгээр давхарт байдаг вэ?')[0], 'floor')
        self.assertEqual(expected_value('Шалгалт хэзээ болох вэ?')[0], 'date')
        self.assertEqual(expected_value('Сургууль анх хэдэн оюутантай хичээллэж эхэлсэн бэ?'), ('count', ('оюута',)))
        self.assertEqual(expected_value('Сургалтын төлбөр хэд вэ?')[0], 'number')
        self.assertIsNone(expected_value('Сургуулийн эрхэм зорилго юу вэ?'))
        # «хэдэн оноо» is points, not a year.
        self.assertEqual(expected_value('Бичгийн шалгалт хэдэн оноотой вэ?')[0], 'count')

    def test_opening_hours_or_a_date(self):
        self.assertEqual(expected_value('Номын сан хэзээ нээгддэг вэ?')[0], 'time')
        self.assertEqual(expected_value('Сургалтын алба хэзээ ажилладаг вэ?')[0], 'time')
        # A past or starting event asks for a date; «хаана» (where) is not «хаадаг».
        self.assertEqual(expected_value('Сургууль хэзээ нээгдсэн бэ?')[0], 'date')
        self.assertEqual(expected_value('Тэнхим StoD компанитай хэзээ хамтран ажиллаж эхэлсэн бэ?')[0], 'date')
        self.assertEqual(expected_value('Элсэлт хэзээ, хаана болох вэ?')[0], 'date')

    def test_values_of_the_asked_type(self):
        cases = [
            ('Hub Center өдөр бүр хэдэн цаг хүртэл нээлттэй вэ?', '10 давхарт байрлах 593.11 м² талбай', False),
            ('Hub Center өдөр бүр хэдэн цаг хүртэл нээлттэй вэ?', 'Даваа–баасан 08:00–20:00 нээлттэй', True),
            ('Сургууль анх хэдэн оюутантай хичээллэж эхэлсэн бэ?', 'анхны 93 оюутан 3 бүлэгтэйгээр', True),
            ('Хоёр том лекцийн танхим нийт хэдэн суудалтай вэ?', '2 том танхим\n242 суудал', True),
            ('Hub Center хэдэн квадрат метр талбайтай вэ?', '593.11 м² талбай', True),
            ('Төгсөгчдийн хэдэн хувь нь Японд ажиллаж байна вэ?', 'төгсөгчдийн 44.1% нь', True),
            ('Номын санд хэдэн ном, сурах бичиг байдаг вэ?', '3270+ ном, сурах бичиг', True),
            ('Манай баг ямар байр эзэлсэн бэ?', 'нийт 59 багаас 5-р байр эзэлж', True),
            ('Манай баг ямар байр эзэлсэн бэ?', 'амжилттай оролцлоо', False),
            ('Шалгалт хэзээ болох вэ?', 'Шалгалт 8/15 болно', True),
            ('Энэ улирлын хичээл хэзээ дуусах вэ?', 'Мэргэжил тус бүрээр жил, улирал бүрийн хичээлийн тоо', False),
        ]
        for query, text, expected in cases:
            with self.subTest(query=query, text=text):
                self.assertEqual(value_supported(query, text), expected)

    def test_units_and_small_numbers_have_one_form(self):
        self.assertIn('м²', normalise_units('Hub Center хэдэн квадрат метр'))
        self.assertIn('хувь', normalise_units('44.1%'))
        self.assertEqual(normalise_units('Хоёр том танхим', numerals=True), '2 том танхим')
        # Review 11/17 (4): a tens word and a unit word are one number, not «10 1».
        self.assertEqual(normalise_units('Арван нэгэн анги', numerals=True), '11 анги')
        self.assertEqual(normalise_units('хорин таван оюутан', numerals=True), '25 оюутан')

    def test_review_findings_on_value_types(self):
        # «байр» is also a building or a dormitory; only an achievement is a ranking.
        self.assertEqual(expected_value('Сургууль хэдэн байртай вэ?')[0], 'count')
        self.assertIsNone(expected_value('Ямар байранд хичээллэдэг вэ?'))
        self.assertEqual(expected_value('Манай баг хэддүгээр байранд орсон бэ?')[0], 'rank')
        cases = [
            # A decimal or a range is not a date.
            ('Тэтгэлэг хэзээ олгодог вэ?', '2.5 сая төгрөгийн тэтгэлэг', False),
            ('Тэтгэлэг хэзээ олгодог вэ?', '2-3 оюутан тэтгэлэг авдаг', False),
            ('Шалгалт хэзээ болох вэ?', '12.25-нд болно', True),
            # A table line names the counted noun first; trailing punctuation is no part of a number.
            ('Хэдэн оюутан суралцдаг вэ?', 'Оюутны тоо: 1200', True),
            ('Хэдэн оюутан суралцдаг вэ?', 'Оюутан: 1200,', True),
            ('Хэдэн оюутан суралцдаг вэ?', 'Нийт 25, оюутан', True),
            ('Хэдэн оюутан суралцдаг вэ?', 'Оюутны тоо 2024 онд нэмэгдсэн', False),
            ('Сургууль хэдэн байртай вэ?', '3 хичээлийн байртай', True),
            # An ordinal ranks or orders; it is no count («4-р байр эзэллээ»).
            ('Сургууль хэдэн байртай вэ?', 'Ирмүүн 4-р байр буюу дэд байр эзэллээ', False),
        ]
        for query, text, expected in cases:
            with self.subTest(query=query, text=text):
                self.assertEqual(value_supported(query, text), expected)


class AnchorBindingTests(unittest.TestCase):
    def units(self, texts, source='s1'):
        return [dict(unit_id='u%d' % i, source_id=source, text=text) for i, text in enumerate(texts)]

    def test_value_must_stand_next_to_the_anchor(self):
        query = 'Hub Center өдөр бүр хэдэн цаг хүртэл нээлттэй вэ?'
        units = self.units(['Hub Center 10 давхарт байрлах 593.11 м² талбай',
                            'Нээлтийн уулзалт 11 сарын 02-06 өдөр, 10 цагт болно',
                            'Hub Center сургуулийн оюутнуудад', 'Номын сан 3270 ном'])
        focus = rule_selector.focus_terms(query, units)
        self.assertTrue(focus <= {'hub', 'center'})
        # The time comes from an unrelated unit: no answer.
        self.assertTrue(rule_selector.value_missing(query, [units[0]['text'], units[1]['text']], True, focus))
        self.assertFalse(rule_selector.value_missing(query, ['Hub Center 08:00–20:00 нээлттэй'], True, focus))

    def test_anchor_may_be_in_the_page_heading(self):
        query = 'NAPROCK тэмцээнд манай баг ямар байр эзэлсэн бэ?'
        claim = 'Competition ангилалд нийт 59 багаас 5-р байр эзэлж'
        self.assertTrue(rule_selector.value_missing(query, [claim], True, {'naprock'}))
        self.assertFalse(rule_selector.value_missing(query, [claim], True, {'naprock'},
                                                     contexts=['NAPROCK 2026 | 5 баг, 5 амжилт!']))

    def test_anchor_sees_a_fleeting_vowel(self):
        # «ажлаа» (their work) is «ажил» without its last short vowel.
        query = 'Механикийн хэдэн оюутан төгсөлтийн ажлаа хамгаалсан бэ?'
        claim = 'Төгсөлтийн судалгааны ажил\n17 оюутан амжилттай хамгаалсан.'
        self.assertFalse(rule_selector.value_missing(query, [claim], True, {'ажлаа'}))
        self.assertTrue(rule_selector.value_missing(query, ['17 оюутан дадлага хийсэн.'], True, {'ажлаа'}))

    def test_a_value_for_another_year_does_not_answer(self):
        query = '2026 оны зун хэдэн оюутан дадлага хийсэн бэ?'
        self.assertTrue(rule_selector.value_missing(query, ['2025 оны зуны улиралд 3 оюутан дадлага хийсэн'], True, ()))
        self.assertFalse(rule_selector.value_missing(query, ['2026 оны зуны улиралд 3 оюутан дадлага хийсэн'], True, ()))

    def test_earlier_screen_when_the_switch_is_off(self):
        self.assertFalse(rule_selector.value_missing('Хэдэн цагт нээгддэг вэ?', ['10 давхарт'], typed=False))

    def test_switch_off_keeps_the_earlier_reason(self):
        source = dict(source_id='s1', url='https://nmct.edu.mn/about', title='Шалгалт',
                      text='Элсэлтийн шалгалт бичгээр болно.\n\nЭлсэлтийн шалгалтын талаар ярилцлага бас болно.')
        units = evidence_units([source])
        for typed in (False, True):
            selection = rule_selector.bounded_lexical_selection('Элсэлтийн шалгалт хэзээ болох вэ?', units,
                                                                sources=[source], typed=typed)
            reasons = {row['reason'] for row in selection['checked_subsets']}
            self.assertTrue(selection['abstained'])
            self.assertEqual('requested_value_missing' in reasons, typed, reasons)

    def test_heading_line_matches_the_question_terms(self):
        self.assertTrue(rule_selector.heading_match('Сургуулийн эрхэм зорилго юу вэ?',
                                                    'Эрхэм зорилго\nМэргэжлийн болон харилцааны өндөр ур чадвартай'))
        self.assertFalse(rule_selector.heading_match('Сургуулийн эрхэм зорилго юу вэ?',
                                                     'Үнэт зүйлс\nсургуулийн эрхэм зорилго, үзэл санааны дор'))


class EvidenceTests(unittest.TestCase):
    def test_total_is_a_whole_word(self):
        text = 'Лекцийн танхим\n2 том танхим\n242 суудал\nИнженерийн нийтлэг шаардлагад нийцүүлэн'
        self.assertNotIn('total', missing_query_markers('Хоёр том лекцийн танхим нийт хэдэн суудалтай вэ?',
                                                        '2 том танхим\n242 суудал', text))
        self.assertIn('total', missing_query_markers('Нийт хэдэн суудал вэ?', '242 суудал',
                                                     text + '\nНийт 900 суудал'))

    def test_navigation_and_view_counter_are_trimmed_from_a_unit(self):
        text = 'Бүх мэдээ\nМэдээ, мэдээлэл\nОюутны амжилтын мэдээлэл\n2026 оны аравдугаар сарын 29 70 үзсэн'
        source = dict(source_id='n1', text=text, url='https://nmct.edu.mn/news/x')
        units = evidence_units([source])
        self.assertEqual(units[0]['text'], 'Оюутны амжилтын мэдээлэл\n2026 оны аравдугаар сарын 29')
        self.assertEqual(text[units[0]['start']:units[0]['end']], units[0]['text'])


class ReceptionWordingTests(unittest.TestCase):
    def setUp(self):
        tables = ReceptionTables(
            rooms=(Room(6, '604'), Room(4, '406', services=(Service('Сургалтын алба', '', ''),))),
            staff=(Staff(name='А.Номин-Эрдэнэ', department='КУ', room='604', email='fake.teacher@nmct.edu.mn'),),
            classes=(ClassGroup(group='КУ-5', room='602', course='5', department='Компьютерын ухааны тэнхим',
                                teacher='А.Номин-Эрдэнэ'),),
            timetable=(Lesson('mon', '09:35-11:05', 'КУ-5', '609', 'А.Номин-Эрдэнэ'),
                       Lesson('mon', '08:00-09:30', 'КУ-5', '602', 'А.Номин-Эрдэнэ')),
            timetable_complete=True, calendar_bound=True, term_start=date(2026, 9, 7), term_end=date(2026, 12, 25))
        self.path = ReceptionAnswerPath(tables, enabled=True)

    def test_class_teacher_email(self):
        result = self.path.answer('КУ-5 ангийн багшийн имэйл?')
        self.assertEqual(result['reason_code'], 'reception_class_teacher_email')
        self.assertIn('fake.teacher@nmct.edu.mn', result['answer'])
        self.assertIn('604', result['answer'])

    def test_phone_question_gets_the_school_email_not_a_phone(self):
        # Review 11/17 (4): phones are never shown; the reply says so, then gives the school e-mail.
        for query, reason in (('КУ-5 ангийн багшийн утас?', 'reception_class_teacher_phone'),
                              ('А.Номин-Эрдэнэ багшийн утасны дугаар хэд вэ?', 'reception_teacher_phone')):
            with self.subTest(query=query):
                self.assertTrue(self.path.recognizes(query))
                result = self.path.answer(query)
                self.assertEqual(result['reason_code'], reason)
                self.assertIn('утасны дугаарыг энд харуулахгүй', result['answer'])
                self.assertIn('fake.teacher@nmct.edu.mn', result['answer'])
        # An unrecorded teacher stays with the staff path (which says phones are not shown).
        self.assertFalse(self.path.recognizes('Х.Хүрэлбаатар багшийн утас?'))
        self.assertFalse(self.path.recognizes('ЗЗ-9 ангийн багшийн утас?'))

    def test_class_weekday_in_time_order(self):
        result = self.path.answer('КУ-5 анги даваа гарагт хэдэн цагт хичээлтэй вэ?', now=datetime(2026, 11, 17, 9))
        self.assertEqual(result['reason_code'], 'reception_class_day')
        self.assertLess(result['answer'].index('08:00'), result['answer'].index('09:35'))

    def test_term_dates(self):
        result = self.path.answer('Энэ улирлын хичээл хэзээ дуусах вэ?')
        self.assertEqual(result['reason_code'], 'reception_term_dates')
        self.assertIn('2026-12-25', result['answer'])


if __name__ == '__main__':
    unittest.main()
