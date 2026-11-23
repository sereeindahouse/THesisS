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

    def test_question_words_and_the_school_name_are_no_topic(self):
        # 11/17 (5): the index cuts «хэддүгээр» to «хэддүг»; the school's name names the school.
        self.assertEqual(rule_selector.key_terms('Сургууль Баянзүрх дүүргийн хэддүгээр хороонд байрладаг вэ?'),
                         ('баянзүрх', 'дүүрг', 'хоро'))
        self.assertEqual(rule_selector.key_terms('Шинэ Монгол Технологийн Коллежийн эрхэм зорилго юу вэ?'),
                         ('эрхэм', 'зорилго'))
        self.assertNotIn('өнөөдрийг', rule_selector.key_terms('Хөтөлбөрийг өнөөдрийг хүртэл хэдэн оюутан төгссөн бэ?'))
        # «одоогийн» (current) stays a topic word: the site rarely states who holds a post now.
        self.assertIn('одоог', rule_selector.key_terms('Оюутны зөвлөлийн одоогийн дарга хэн бэ?'))

    def test_dated_period_needs_a_calendar_date(self):
        query = '2026 оны элсэлтийн цахим бүртгэл хэдий хугацаанд явагдсан бэ?'
        self.assertEqual(expected_value(query)[0], 'date')
        # The named year and a season are no answer; a month/day is.
        self.assertFalse(value_supported(query, 'ШМТК — Элсэлт 2026. Элсэлтийн шалгалтаа намар болон хавар авдаг.'))
        self.assertTrue(value_supported(query, 'Цахим бүртгэл 08/03-08/13'))
        # Without a year a season still answers «хэзээ».
        self.assertTrue(value_supported('Элсэлтийн шалгалт хэзээ болдог вэ?', 'Шалгалтаа намар авдаг.'))

    def test_publication_date_place_and_two_word_topics(self):
        # 11/17 (5): an article's dated heading line is not the date asked about.
        self.assertFalse(value_supported('Элсэлт хэзээ эхлэх вэ?', 'ЭЛСЭЛТИЙН МЭДЭЭЛЭЛ\n2026 оны есдүгээр сарын 11'))
        self.assertTrue(value_supported('Элсэлт хэзээ эхлэх вэ?', 'Бүртгэл 2026 оны есдүгээр сарын 11-нд эхэлнэ.'))
        # Where an office is: a room or a floor, in digits or in words.
        self.assertEqual(expected_value('Хүний нөөцийн алба хаана байдаг вэ?')[0], 'place')
        self.assertIsNone(expected_value('Японд хаана дадлага хийдэг вэ?'))
        self.assertFalse(value_supported('Хүний нөөцийн алба хаана байдаг вэ?', 'Байгууллагын бүтэц, алба нэгж'))
        self.assertTrue(value_supported('Хүний нөөцийн алба хаана байдаг вэ?', 'Хүний нөөцийн алба 406 тоот'))
        self.assertTrue(value_supported('Номын сан хаана вэ', 'Номын сан гуравдугаар давхарт.'))
        # A two-word topic must stand together in the text: «цайны цаг» is no cafeteria.
        self.assertEqual(rule_selector.phrase_pair('Цайны газар байдаг уу?'), ('цайны', 'газар'))
        self.assertFalse(rule_selector.topic_covered('Цайны газар байдаг уу?',
                                                     'Багш нар цайны цаг болон чөлөөт цагаа өнгөрөөх газар'))
        self.assertTrue(rule_selector.topic_covered('Спорт заал байдаг уу?', 'Сургууль 2 спорт заалтай.'))

    def test_round9_where_words_empty_topics_and_issued_papers(self):
        # «хаанаас» is a question word, cut to «хаан» it matched «Хаан банк»; the bank stays a topic.
        self.assertEqual(rule_selector.key_terms('Тодорхойлолт хаанаас авах вэ?'), ('тодорхойлолт',))
        self.assertIn('хаан', rule_selector.key_terms('Хаан банкаар төлж болох уу?'))
        # The final verb is dropped before the question word, so the paper stays a topic (review).
        self.assertEqual(rule_selector.key_terms('Оюутны үнэмлэх хаанаас авах вэ?'), ('оюутан', 'үнэмлэх'))
        # A question with no topic word is not about any paragraph.
        self.assertFalse(rule_selector.topic_covered('Та хэн бэ?', 'Дадлага хөтөлбөрт хэн хамрагдах вэ?'))
        # «… хаанаас авах вэ?»: one sentence names the paper and says it is issued.
        query = 'Сургуулийн тодорхойлолт хаанаас авах вэ?'
        self.assertFalse(rule_selector.topic_covered(
            query, 'Сургуулийн тодорхойлолтоор 7 төгсөгч элсэв.\nБүртгэлийн хуудсыг цахимаар авна.'))
        self.assertTrue(rule_selector.topic_covered(query, 'Сургуулийн тодорхойлолтыг Сургалтын албанаас авна.'))
        # The sentence with the issuing verb must name the asked paper itself (review).
        self.assertFalse(rule_selector.topic_covered('Дотуур байрны гэрээ хаанаас авах вэ?',
                                                     'Дотуур байрны гэрээг 2 хувь хийнэ.\nДотуур байранд хоол авна.'))
        # «… хаанаас харах вэ?» likewise: an exam page's «харагдана» beside a «хуваарь» heading is no answer.
        timetable = 'Хичээлийн хуваарь хаанаас харах вэ?'
        self.assertFalse(rule_selector.topic_covered(timetable, 'Шалгалтын дараа хичээл бүрийн оноо харагдана.\nХугацааны хуваарь'))
        self.assertTrue(rule_selector.topic_covered(timetable, 'Хичээлийн хуваарийг оюутны цахим системээс харна.'))
        # A viewer's «Томоор үзэх» button is no place to get a grade sheet (round 10).
        self.assertFalse(rule_selector.topic_covered('Дүнгийн хуудас хаанаас авах вэ?', 'Хуудас 1\nХуудас 1 Томоор үзэх →'))
        # «4-р байр … эзэллээ» is a ranking, not building 4; «Хүний нөөц хаана вэ?» asks for a place.
        from answer_types import _PLACE_VALUE
        self.assertEqual(expected_value('Хүний нөөц хаана вэ?'), ('place', ()))
        self.assertFalse(_PLACE_VALUE.search('илтгэлээ тавьж, 4-р байр буюу дэд байр эзэллээ'))
        self.assertTrue(_PLACE_VALUE.search('2-р байрны А корпус'))
        self.assertTrue(_PLACE_VALUE.search('Номын сан 2-р байрны 1 давхрыг эзэлдэг'))   # occupies, not won
        self.assertEqual(expected_value('Нягтлан бодогч хаана вэ?'), ('place', ()))

    def test_round10_shares_yearly_counts_and_quantities(self):
        from answer_types import value_supported
        share = 'Төгсөгчдийн хэдэн хувь нь Япон улсад ажиллаж байна вэ?'
        # «Тус 2 сургуулийн хувьд» (as for the two schools) is no percentage; «21.6%» is.
        self.assertFalse(value_supported(share, 'Тус 2 сургуулийн хувьд 2019 оноос хамтын ажиллагаа эхэлсэн.'))
        self.assertTrue(value_supported(share, '21.6%\nЯпон улс болон бусад улсад ажиллах'))
        # The number stands right before «хувь»: «45 хувьд хүрсэн» is a share, «хувьдаа» is not (review).
        self.assertTrue(value_supported(share, 'Ажилд орсон төгсөгчдийн тоо 45 хувьд хүрсэн.'))
        self.assertFalse(value_supported(share, 'Тус 2 сургуулийн хувьдаа хамтран ажилладаг.'))
        # A yearly count needs a yearly figure, not a current total.
        yearly = 'Монбүшёо тэтгэлэгт жил бүр хэдэн оюутан сонгогддог вэ?'
        self.assertFalse(value_supported(yearly, 'Одоогоор 12 оюутан тус тэтгэлэгт хамрагдаад байна.'))
        self.assertTrue(value_supported(yearly, 'Жил бүр 3 оюутан сонгогддог.'))
        self.assertTrue(value_supported(yearly, 'Тэтгэлэгт жилд 3 оюутан сонгогддог.'))
        self.assertFalse(value_supported(yearly, '2025–2026 оны хичээлийн жилд 12 оюутан хамрагдсан.'))
        # «хичээлийн жилд», «сүүлийн 4 жилд» are not yearly rates.
        self.assertTrue(value_supported('Сакура Сайэнс хөтөлбөрт сүүлийн 4 жилд хэдэн оюутан хамрагдсан бэ?',
                                        '26 оюутан Сакура Сайэнс хөтөлбөрт хамрагдсан, сүүлийн 4 жилд.'))
        # «Хоёр мэргэжил …»: the quantity and the noun stand together, not a list's «2.».
        two = 'Хоёр мэргэжил сонгож болох уу?'
        self.assertEqual(rule_selector.quantity_pair(two), ('2', 'мэргэжил'))
        self.assertFalse(rule_selector.topic_covered(two, '1. Бүртгүүлэх\nСонирхож буй мэргэжлээ сонгож форм бөглөнө.\n2. Төлбөр'))
        self.assertTrue(rule_selector.topic_covered(two, 'Элсэгч 2 мэргэжил сонгож болно.'))
        # Any quantity right before the noun answers it; a list step «2. Мэргэжил …» does not (review).
        self.assertTrue(rule_selector.topic_covered(two, 'Элсэгч зөвхөн нэг мэргэжил сонгож бүртгүүлнэ.'))
        self.assertTrue(rule_selector.topic_covered(two, 'Элсэгч 2-3 мэргэжил сонгож болно.'))
        self.assertFalse(rule_selector.topic_covered(two, 'Алхам:\n1. Мэдээлэл оруулна\n2. Мэргэжил сонгох\n3. Төлбөр'))
        self.assertIsNone(rule_selector.quantity_pair('Хоёр долоо хоногт хэдэн удаа хичээл ордог вэ?'))
        for query in ('2-р курст шилжиж орж болох уу?', 'Номын сангаас нэг удаад хэдэн ном зээлж болох вэ?',
                      'Сакура Сайэнс хөтөлбөрт сүүлийн 4 жилд хэдэн оюутан хамрагдсан бэ?'):
            with self.subTest(query=query):
                self.assertIsNone(rule_selector.quantity_pair(query))

    def test_round11_another_departments_page_does_not_answer(self):
        # «Барилгын тэнхим ямар лабораторитой вэ?» joined the Механик page's labs with the department
        # list's «Барилга»; a named department is answered from its own pages only.
        self.assertEqual(rule_selector._department_stem('Барилгын тэнхим ямар лабораторитой вэ?'), 'civil')
        self.assertEqual(rule_selector._department_stem('Барилгын дэд бүтцийн инженерийн тэнхим'), 'civil')
        # Whole word beginnings: «компани», «цахим» are no departments; two departments name none (review).
        for text in ('Компанитай хамтран ажилладаг тэнхим аль вэ?', 'Цахим хичээл заадаг тэнхим',
                     'Барилгын тэнхим механик тэнхимээс юугаараа ялгаатай вэ?'):
            with self.subTest(text=text):
                self.assertIsNone(rule_selector._department_stem(text))
        self.assertEqual(rule_selector._page_department('https://nmct.edu.mn/departments/general-department'), 'general')
        self.assertIsNone(rule_selector._page_department('https://nmct.edu.mn/departments'))
        self.assertEqual(rule_selector._department_stem('Цахилгааны тэнхим хаана вэ?'), 'electrical')
        for text in ('Тэнхимүүд', 'Сургууль хэдэн тэнхимтэй вэ?', 'Хамгийн олон оюутантай тэнхим аль вэ?'):
            with self.subTest(text=text):
                self.assertIsNone(rule_selector._department_stem(text))
        units = [dict(unit_id='m1', source_id='mech', text='Тэнхим нь механик боловсруулалтын лаборатори, гагнуурын лаборатори гэсэн лабораторитой.'),
                 dict(unit_id='d1', source_id='list', text='Барилгын дэд бүтцийн инженерийн тэнхим')]
        sources = [dict(source_id='mech', title='Механик инженерийн тэнхим', url='https://nmct.edu.mn/departments/mechanical'),
                   dict(source_id='list', title='Тэнхимүүд', url='https://nmct.edu.mn/departments')]
        result = rule_selector.bounded_lexical_selection('Барилгын тэнхим ямар лабораторитой вэ?', units, sources=sources)
        self.assertTrue(result['abstained'])

    def test_round14_list_numbers_headings_and_two_word_places(self):
        from answer_types import value_supported
        # «04 / Оюутан бүрийн эрх ашгийг …» numbers a list item; it counts no students.
        self.assertFalse(value_supported('Хэдэн оюутантай вэ?', '02\nЦаг баримтлах\n04\nОюутан бүрийн эрх ашгийг дээдэлж'))
        self.assertTrue(value_supported('Хэдэн оюутантай вэ?', '1200 оюутан суралцдаг.'))
        # A news item's title and date alone answer nothing.
        self.assertTrue(rule_selector._heading_only('ДУГУЙЛАН, КЛУБИЙН ТАНИЛЦУУЛГА\n2026 оны аравдугаар сарын 13 [1]'))
        self.assertFalse(rule_selector._heading_only('Робокон клуб\nРобот бүтээдэг клуб.'))
        # A code, a phone or a labelled uppercase line is content, not a heading (review).
        for text in ('IT-101', 'УТАС: 7000-1234', 'ХАЯГ: УЛААНБААТАР ХОТ, СБД, 1-Р ХОРОО'):
            with self.subTest(text=text):
                self.assertFalse(rule_selector._heading_only(text))
        # «Нийт: 05 оюутан» is a count; only a zero-padded number alone on its line numbers a list (review).
        self.assertTrue(value_supported('Хэдэн оюутантай вэ?', 'Нийт: 05 оюутан'))
        # The where-question pair is only for «… байр» (review).
        self.assertTrue(rule_selector.topic_covered('Захирлын өрөө хаана вэ?', 'Захирал Б.Бат. Ажлын өрөө: 508 тоот, 5-р давхар.'))
        # «Оюутны байр хаана байдаг вэ?» (a dormitory) is not a contest's «1-р байр: … оюутан».
        self.assertEqual(rule_selector.phrase_pair('Оюутны байр хаана байдаг вэ?'), ('оюутан', 'байр'))
        self.assertFalse(rule_selector.topic_covered('Оюутны байр хаана байдаг вэ?',
                                                     '1-р байр: ЦЭИ-2 ангийн оюутан Л.Эрдэмбаяр\n2-р байр: МИ-4 ангийн оюутан'))

    def test_round16_word_families_list_numbers_how_verbs_and_split_pairs(self):
        from answer_types import value_supported
        # «хаяг» (an address) is not «хаягдал» (waste); «хуваан» (dividing) is not «Хувийн» (personal).
        self.assertFalse(rule_selector._has_term('хаяг', {'хаягдлын'}))
        self.assertTrue(rule_selector._has_term('хаяг', {'хаягаа'}))
        self.assertFalse(rule_selector._has_term('хуваан', {'хувийн'}))
        # The search index's own stem joins «хаягдлын» with «хаяг»: the word keeps its family.
        self.assertFalse(rule_selector._has_term('хаяг', rule_selector._words('Хог хаягдлын менежментийг дэмжсэн оюутан')))
        self.assertIn('хаягдлыг', rule_selector.key_terms('Хог хаягдлыг хаана хаях вэ?'))
        self.assertFalse(value_supported('Төлбөрөө хэдэн хуваан төлж болох вэ?',
                                         '3. Хувийн хэсэг\nТөлбөр баталгаажмагц нэвтэрч, бүртгэлээ харна.'))
        # A list number at a line start counts nothing; a labelled count on that line still does.
        self.assertFalse(value_supported('Хэдэн оюутантай вэ?', '3. Оюутан бүрийн эрх'))
        self.assertTrue(value_supported('Хэдэн оюутантай вэ?', '3. Оюутны тоо: 1200'))
        # A how-question's own verb must stand in the text when its root names the act; short roots
        # («элс», «ав») are left alone.
        self.assertEqual(rule_selector._how_verb_root('Цахим системд яаж нэвтрэх вэ?'), 'нэвтр')
        self.assertEqual(rule_selector._how_verb_root('Багш нар оюутантай хэрхэн харьцдаг вэ?'), 'харьц')
        self.assertIsNone(rule_selector._how_verb_root('Клубт яаж элсэх вэ?'))
        self.assertFalse(rule_selector.topic_covered('Цахим системд яаж нэвтрэх вэ?', 'Цээж зургаа цахим системд оруулна.'))
        self.assertTrue(rule_selector.topic_covered('Цахим системд яаж нэвтрэх вэ?', 'Цахим системд нэвтэрч, бүртгэлээ харна.'))
        # One root whatever the verb's form; the act's noun names a long root's act too, but a root a
        # topic noun shares («төл» / «төлбөр») must stand as a verb (review).
        self.assertEqual(rule_selector._how_verb_root('Хэрхэн хичээллэдэг вэ?'), rule_selector._how_verb_root('Хэрхэн хичээллэх вэ?'))
        self.assertTrue(rule_selector.topic_covered('Төгсөлтийн ажлыг хэрхэн хамгаалдаг вэ?', 'Төгсөлтийн ажлын хамгаалалт 6 сард болно.'))
        self.assertFalse(rule_selector.topic_covered('Багш нар оюутантай хэрхэн харьцдаг вэ?', 'Багш нар оюутантай уулзаж харьцуулахад'))
        self.assertFalse(rule_selector.topic_covered('Сургалтын төлбөрөө хэрхэн төлөх вэ?', 'Сургалтын төлбөр 3 сая төгрөг.'))
        # Two joined paragraphs, one with «эцэг эхийн» and one with «хурал», do not answer; one paragraph does.
        self.assertEqual(rule_selector.genitive_pairs('Эцэг эхийн хурал хэзээ болдог вэ?'), (('эхийн', 'хурал'),))
        # A pronoun, or the asked value's own word (the room of «… албаны өрөө хаана вэ?»), makes no pair (review).
        self.assertEqual(rule_selector.genitive_pairs('Таны нэр хэн бэ?'), ())
        self.assertEqual(rule_selector.genitive_pairs('Сургалтын албаны өрөө хаана вэ?'), (('сургалт', 'албаны'),))
        # W04-A09: «Төгсөлтийн судалгааны ажил» holds «төгсөлтийн ажлаа» (a fleeting vowel), in one paragraph.
        query = '2024–2025 онд механикийн хэдэн оюутан төгсөлтийн ажлаа хамгаалсан бэ?'
        sources = [dict(source_id='m', url='https://nmct.edu.mn/departments/mechanical', title='Механик инженерийн тэнхим',
                        text='Төгсөлтийн судалгааны ажил\n2024–2025 онд 17 оюутан амжилттай хамгаалсан.\n\n'
                             'Үйлдвэрлэлийн дадлагын ажлын байранд оюутнууд ажилласан.')]
        self.assertFalse(rule_selector.bounded_lexical_selection(query, evidence_units(sources), sources=sources)['abstained'])
        news = dict(source_id='s2', url='https://nmct.edu.mn/news/x', title='Мэдээ',
                    text='Оюутны эрдэм шинжилгээний бага хурал 2025 онд болсон.')
        for text, answered in (('Ярилцлагын шалгалтаар эцэг эхийн хамтын ажиллагааг шалгана.', False),
                               ('Эцэг эхийн хурал 10 сарын 15-нд болно.', True)):
            with self.subTest(text=text):
                sources = [dict(source_id='s1', url='https://nmct.edu.mn/elselt', title='Элсэлт', text=text), news]
                result = rule_selector.bounded_lexical_selection('Эцэг эхийн хурал хэзээ болдог вэ?', evidence_units(sources),
                                                                 sources=sources)
                self.assertEqual(result['abstained'], not answered)
                if not answered:
                    self.assertIn('pair_split', {row['reason'] for row in result['checked_subsets']})

    def test_round17_building_teacher_words_last_word_predicate_how_to_get_and_interviews(self):
        from reception_tables import normalize_wording
        # «байр» (a building, a dormitory) is not «байна» (is) or «байрлах» (to be located); «багш» is not «баг».
        for word in ('байна', 'байрлах', 'байршил'):
            with self.subTest(word=word):
                self.assertFalse(rule_selector._has_term('байрны', {word}))
        self.assertTrue(rule_selector._has_term('байрны', {'байранд'}))
        self.assertFalse(rule_selector._has_term('багш', {'багийг'}))
        self.assertTrue(rule_selector._has_term('багш', {'багшийн'}))
        self.assertFalse(rule_selector._has_term('баг', {'багш'}))   # both ways (review)
        # Only the question's own last word is its verb: «үнэ» (a price) and «сан» stay topics.
        self.assertEqual(rule_selector.key_terms('Оюутны байрны үнэ хэд вэ?'), ('оюутан', 'байрны', 'үнэ'))
        self.assertEqual(rule_selector.key_terms('Номын сан хаана вэ?'), ('ном', 'сан'))
        self.assertEqual(rule_selector.key_terms('Хэдэн оюутан суралцдаг вэ?'), ('оюутан',))
        # A colloquial ending is no verb either (review).
        self.assertEqual(rule_selector.key_terms('Элсэлт хэзээ эхлэх бол?'), rule_selector.key_terms('Элсэлт хэзээ эхлэх вэ?'))
        self.assertFalse(rule_selector.topic_covered('Оюутны байрны үнэ хэд вэ?',
                                                     'Энэ жил 78 оюутан голд байрлах талбайд ажиллаж, хөдөлмөрийн үнэ цэнийг мэдэрлээ.'))
        # «яаж/хэрхэн авах» needs the paper and a verb of issuing in one sentence, as «хаанаас авах» does.
        self.assertFalse(rule_selector.topic_covered('Тодорхойлолт яаж авах вэ?',
                                                     'Гадаадад өгсөн шалгалтыг гэрчилсэн тодорхойлолтын хамт бүрдүүлэн ирүүлнэ.'))
        self.assertTrue(rule_selector.topic_covered('Тодорхойлолт яаж авах вэ?', 'Тодорхойлолтыг сургалтын албанаас авна.'))
        # Only a paper or an account: a scholarship's conditions say how to get it (review).
        self.assertTrue(rule_selector.topic_covered('Тэтгэлэг яаж авах вэ?', 'Тэтгэлэгт голч дүн 3.5-аас дээш оюутан хамрагдана.'))
        # Where a paper is handed in: the paper and a verb of handing in, in one sentence.
        self.assertFalse(rule_selector.topic_covered('Багшаар ажилд орох хүсэлт хаана өгөх вэ?',
                                                     'Тус тэнхимийн багш нар оролцож, төслийн ажилд амжилт хүслээ.'))
        self.assertTrue(rule_selector.topic_covered('Багшаар ажилд орох хүсэлт хаана өгөх вэ?',
                                                    'Багшаар ажилд орох хүсэлтээ хүний нөөцийн албанд өгнө.'))
        # A story's «багийг хүлээн авч … амжилт хүслээ» neither receives nor names a request (round 17 probe).
        self.assertFalse(rule_selector.topic_covered('Багшаар ажилд орох хүсэлт хаана өгөх вэ?',
                                                     'Тэнхимийн багш нар оролцов. Захирал төслийн багийг хүлээн авч, ажилд амжилт хүслээ.'))
        # Where an interview is asks for a place; «хоол хаана идэх» asks where the canteen is.
        self.assertEqual(expected_value('Ярилцлага хаана болох вэ?'), ('place', ()))
        for query in ('Хоол хаана идэх вэ?', 'Хоолоо хаана идэх вэ?', 'Хаана хоол идэх вэ?', 'Хоол идэх газар хаана вэ?'):
            with self.subTest(query=query):
                self.assertEqual(normalize_wording(query), 'Хоолны газар хаана байдаг вэ?')

    def test_round18_typed_forms_and_dates_of_events_to_come(self):
        from reception_tables import normalize_wording
        from rag_runtime import common_question_alias
        # «ве», «хэд дүгээр», a wondering «… бол?» read as the usual forms; a conditional «бол» stays.
        self.assertEqual(normalize_wording('жилийн төлбөр хэд ве'), 'жилийн төлбөр хэд вэ')
        self.assertEqual(normalize_wording('Номын сан хэд дүгээр давхарт вэ?'), 'Номын сан хэддүгээр давхарт вэ?')
        self.assertEqual(normalize_wording('Элсэлт хэзээ эхлэх бол?'), 'Элсэлт хэзээ эхлэх вэ?')
        self.assertEqual(normalize_wording('Хэрэв ирэх бол ирээрэй'), 'Хэрэв ирэх бол ирээрэй')
        # The forms come first, so the rules after them see them; «бол» only in a question (review).
        self.assertEqual(normalize_wording('Номын сан хэд дүгээр давхар вэ'), 'Номын сан хэддүгээр давхарт вэ')
        self.assertEqual(normalize_wording('Номын сан хана ве'), 'Номын сан хаана вэ')
        for text in ('Хэрэв элсэх бол', 'Энэ ах бол'):
            with self.subTest(text=text):
                self.assertEqual(normalize_wording(text), text)
        self.assertEqual(common_question_alias('Нэг жилд хэдэн төгрөг төлөх вэ?'), common_question_alias('Жилийн төлбөр хэд вэ?'))
        # An event to come needs a day or a month, not the page title's year; a past one may be a year.
        self.assertFalse(value_supported('Бүртгэл хэзээ дуусах вэ?', 'ШМТК — Элсэлт 2026\nЦахим бүртгэлээ үүсгээд хураамжаа төлнө.'))
        for text in ('Бүртгэл хаагдах 8/13 16:00 цаг', 'Ярилцлагын шалгалт 2026.08.15 өдөр'):
            with self.subTest(text=text):
                self.assertTrue(value_supported('Бүртгэл хэзээ дуусах вэ?', text))
        # Nor a season; «эхэлнэ» is an event to come too (review).
        self.assertFalse(value_supported('Бүртгэл хэзээ дуусах вэ?', 'Элсэлт 2026 намар'))
        self.assertFalse(value_supported('Элсэлт хэзээ эхэлнэ вэ?', 'ШМТК — Элсэлт 2026'))
        self.assertTrue(value_supported('Сургууль хэзээ байгуулагдсан бэ?', 'Сургууль 2014 онд байгуулагдсан.'))

    def test_round19_a_floor_plans_list_numbers_are_no_rooms(self):
        # «Хурлын өрөө» and, on the next line, a list number «06» is no room number; «өрөө 809» on one line is.
        self.assertFalse(value_supported('Хурлын танхим хаана вэ?', '593 м² талбай\n05\nХурлын өрөө\n06\nУншлагын танхим'))
        self.assertTrue(value_supported('Хурлын танхим хаана вэ?', 'Хурлын танхим: өрөө 809'))
        # Where the student council is asks for a place, not what it does.
        self.assertEqual(expected_value('Оюутны зөвлөл хаана байдаг вэ?'), ('place', ()))

    def test_round22_other_institutions_unknown_departments_and_student_records(self):
        import re
        from question_router import personal_record_service_request
        from rag_runtime import ChatRAG

        def out_of_scope(query):
            return bool(ChatRAG.OUT_OF_SCOPE.fullmatch(re.sub(r'\s+', ' ', query.casefold()).strip(' ?!.')))

        # Another institution's fee or admission is not this school's; a contest held there is a school question.
        for query in ('Монгол Улсын Их Сургуулийн төлбөр хэд вэ?', 'ШУТИС-ийн элсэлт хэзээ эхлэх вэ?', 'АШУҮИС-ийн төлбөр хэд вэ?',
                      'ШУТИС-ийн захирлын нэр хэн бэ?', 'муис ийн төлбөр хэд вэ'):
            with self.subTest(query=query):
                self.assertTrue(out_of_scope(query))
        for query in ('ШУТИС-ийн тэмцээнд манай баг ямар байр эзэлсэн бэ?', 'Сургуулийн төлбөр хэд вэ?',
                      'МУИС-ийн төлбөрөөс манайх хямд уу?', 'ШУТИС-ийн бүртгэлтэй олимпиад хэзээ вэ?'):
            with self.subTest(query=query):
                self.assertFalse(out_of_scope(query))
        # Whether a student's grades can be seen here; published results are no personal record.
        from question_router import personal_record_request
        for query in ('Оюутны дүнг харж болох уу?', 'Оюутан дүнгээ харж болох уу?'):
            with self.subTest(query=query):
                self.assertTrue(personal_record_request(query))
        for query in ('Элсэлтийн шалгалтын дүнг харж болох уу?', 'Оюутны дүн мэдээлж болох уу?', 'Оюутны байр харж болох уу?'):
            with self.subTest(query=query):
                self.assertFalse(personal_record_request(query) or personal_record_service_request(query))
        # Only a word takes a hyphenated genitive: «N3-ийн», «20-ны» make no new pair (review).
        # A hyphenated genitive is a genitive; a department the school does not have must be named as one.
        self.assertEqual(rule_selector.genitive_pairs('ШУТИС-ийн элсэлт хэзээ эхлэх вэ?'), (('шутис', 'элсэлт'),))
        self.assertEqual(rule_selector.genitive_pairs('N3-ийн түвшин хэзээ шаардах вэ?'), ())
        for text, answered in (('ШУТИС-ийн Барилга, Архитектурын Сургуулийн санаачилгаар тэмцээн болсон. Тэнхимийн оюутнууд оролцов.', False),
                               ('ШУТИС-ийн Архитектурын Сургуулийн тэнхимийн оюутнууд 3-р давхарт, 305 тоотод цугларав.', False),
                               ('Архитектурын инженерийн тэнхим 305 тоотод байрладаг.', True),
                               ('Архитектурын тэнхим 3-р давхарт, 305 тоотод байрладаг.', True)):
            with self.subTest(text=text):
                sources = [dict(source_id='s1', url='https://nmct.edu.mn/news/x', title='Мэдээ', text=text)]
                result = rule_selector.bounded_lexical_selection('Архитектурын тэнхим хаана байдаг вэ?', evidence_units(sources),
                                                                 sources=sources)
                self.assertEqual(result['abstained'], not answered)

    def test_a_converb_needs_its_stem(self):
        # Round 8: «хувааж» (dividing) does not cover «Хувийн» (personal); other words keep the short prefix.
        self.assertFalse(rule_selector.topic_covered(
            'Төлбөрөө хувааж төлж болох уу?',
            '3. Хувийн хэсэг\nТөлбөр баталгаажмагц нэвтэрч, бүртгэлийн мэдээллээ харна.'))
        self.assertTrue(rule_selector.topic_covered('Хаана сурч болох вэ?', 'Суралцах хөтөлбөр'))

    def test_round6_light_verbs_dates_near_the_anchor_and_other_departments(self):
        # «шилжиж орж» = transfer in: «орж» only finishes the verb.
        self.assertEqual(rule_selector.key_terms('2-р курст шилжиж орж болох уу?'), ('2', 'курст', 'шилжиж'))
        self.assertEqual(rule_selector.key_terms('Сургуульд орж болох уу?'), ('орж',))
        # Agent nouns and other verbs keep their meaning: only «орох» after a verb's converb is dropped.
        self.assertEqual(rule_selector.key_terms('Хэрэглэгч орох эрхтэй юу?')[:1], ('хэрэглэгч',))
        self.assertIn('авч', rule_selector.key_terms('Багаж авч болох уу?'))

    def test_round5_person_classifier_and_how_questions(self):
        # «… дарга хэн бэ?» needs a person's name next to the post, not a rule mentioning the post.
        query = 'Оюутны зөвлөлийн дарга хэн бэ?'
        self.assertEqual(expected_value(query), ('person', ('дарга',)))
        self.assertFalse(value_supported(query, 'Цаг баримтлах, оюутны зөвлөлийн даргад урьдчилан мэдэгдэх'))
        self.assertTrue(value_supported(query, 'Оюутны зөвлөлийн дарга Б.Тэмүүлэн'))
        # The website prints the name on the line above the post.
        self.assertTrue(value_supported('Захирал хэн бэ?', 'Т.Зохиомол\nШинэ Монгол технологийн Коллежийн Захирал'))
        # «хэдэн ширхэг» counts the noun before «хэдэн».
        self.assertEqual(expected_value('Лаборатори хэдэн ширхэг байдаг вэ?'), ('count', ('лаборатори',)))
        self.assertTrue(value_supported('Лаборатори хэдэн ширхэг байдаг вэ?', '25 Анги танхим 13 Лаборатори'))
        self.assertTrue(rule_selector.topic_covered('Лаборатори хэдэн ширхэг байдаг вэ?', '25 Анги танхим 13 Лаборатори',
                                                    typed=True))
        # The website's staff list names the head as «Нэр (Тэнхимийн эрхлэгч)».
        self.assertTrue(value_supported('Механик тэнхимийн эрхлэгч хэн бэ?',
                                        'Механик инженерийн тэнхим: Бадам (Багш); Билгүүн (Тэнхимийн эрхлэгч)'))
        # A «how» verb that shares its root with a topic noun («төлөх»/«төлбөр») must stand as a verb;
        # other how-questions keep their usual key terms (review, round 5).
        self.assertEqual(rule_selector.key_terms('Номын сангаас ном яаж зээлэх вэ?'), ('ном', 'санг'))
        self.assertTrue(rule_selector.topic_covered('Сургалтын төлбөрөө хэрхэн төлөх вэ?', 'Сургалтын төлбөрийг QPay-ээр төлнө.'))
        # Counted noun after the classifier; «нь» is skipped; pronouns and «хүн» are not posts.
        self.assertEqual(expected_value('Сургуульд хэдэн ширхэг компьютер байдаг вэ?'), ('count', ('компьютер',)))
        self.assertEqual(expected_value('Лаборатори нь хэдэн ширхэг байдаг вэ?'), ('count', ('лаборатори',)))
        self.assertIsNone(expected_value('Та хэн бэ?'))
        self.assertFalse(value_supported('Захирал хэн бэ?', 'Захирал (Director)'))
        self.assertTrue(value_supported('Оюутны зөвлөлийн дарга хэн бэ?', 'Оюутны зөвлөлийн дарга Б.ТЭМҮҮЛЭН'))
        founder = 'Сургуулийг хэн үүсгэн байгуулсан бэ?'
        self.assertTrue(value_supported(founder, 'Коллежийг үүсгэн байгуулагч, Гавъяат багш, доктор Ж.Зохиомол багш'))
        self.assertFalse(value_supported(founder, 'Энэ нь түүний үүсгэн байгуулсан цэцэрлэгээс их сургууль хүртэл'))
        self.assertFalse(rule_selector.topic_covered('Сургалтын төлбөрөө хэрхэн төлөх вэ?',
                                                     'I байр - 1 сурагч, сургалтын төлбөрийн 50%-ийн хөнгөлөлт'))

    def test_stative_count_is_not_an_event_count(self):
        # Round 4 (11/17): «… хэдэн оюутантай вэ?» took «17 оюутан амжилттай хамгаалсан» (theses
        # defended); a year before «он…» counts nothing either.
        query = 'Механик инженерийн тэнхим хэдэн оюутантай вэ?'
        self.assertFalse(value_supported(query, '2024–2025 онд 17 оюутан амжилттай хамгаалсан.'))
        self.assertTrue(value_supported(query, '2025–2026 оны хичээлийн жилд нийт 128 оюутан суралцаж байна.'))
        self.assertTrue(value_supported('Хэдэн оюутан хамгаалсан бэ?', '2024–2025 онд 17 оюутан амжилттай хамгаалсан.'))
        self.assertFalse(value_supported('Хэдэн оюутан суралцдаг вэ?', '2025 онд оюутан элсэв'))
        # W04-b-B04 (review): when the year itself is asked, «2016 оноос» is the answer.
        self.assertTrue(value_supported('Номын сан Koha программыг хэдэн оноос ашиглаж байна вэ?',
                                        'Koha олон улсын программыг 2016 оноос нэвтрүүлэн ашиглаж байна.'))

    def test_name_type_needs_a_new_name_next_to_the_named_thing(self):
        query = 'Механикийн оюутнуудын Robocon чиглэлийн клуб ямар нэртэй вэ?'
        self.assertEqual(expected_value(query), ('name', ('клуб',)))
        self.assertTrue(value_supported(query, '• Robocon чиглэлийн NewRobo клуб'))
        # Only the question's own words, or a capital that starts a sentence or a bullet: no name.
        self.assertFalse(value_supported(query, 'Үүнд Robocon клуб, номын өдөрлөг, Сэнпай–Коохай арга хэмжээ'))
        self.assertFalse(value_supported(query, 'Мэргэжлийн клубийн үйл ажиллагаанд 13 оюутан'))
        self.assertTrue(value_supported('Клубийн нэр юу вэ?', 'Оюутнууд «Шинэ Робот» клубт хамрагддаг'))
        # Review (round 4): the text is read as written, so a capitalised name counts; «www» does not.
        self.assertTrue(value_supported('Клуб ямар нэртэй вэ?', 'Оюутнууд Залуус клубт хамрагддаг'))
        self.assertFalse(value_supported('Клуб ямар нэртэй вэ?', 'Клубын мэдээллийг www хуудсаас үзнэ үү'))

    def test_page_title_and_asked_value_words_in_coverage(self):
        # W04-A07: the dated line names neither «элсэлт» nor «2026»; its page title does, and
        # «хугацаа» is the asked date itself (round 4, 11/17).
        query = '2026 оны элсэлтийн цахим бүртгэл хэдий хугацаанд явагдсан бэ?'
        shown = 'Үе шат 1\nБүртгэл хаагдах\n8/13 16:00 цаг\nЦахим бүртгэл 08/03-08/13'
        titles = 'Шинэ Монгол Технологийн Коллежийн элсэлтийн онлайн бүртгэл\nШМТК — Элсэлт 2026'
        self.assertTrue(rule_selector.topic_covered(query, shown, titles, typed=True))
        self.assertFalse(rule_selector.topic_covered(query, shown, typed=True))
        self.assertFalse(rule_selector.topic_covered(query, shown, titles))   # «хугацаа» counts when untyped
        # A title does not lift a paragraph about something else.
        self.assertFalse(rule_selector.topic_covered(query, 'Бүртгэлийн хураамж 20,000 төгрөг', titles, typed=True))

    def test_review_findings_round_three(self):
        # A labelled date on its own line is an answer, not a publication heading.
        self.assertTrue(value_supported('Элсэлтийн бүртгэл хэзээ эхлэх вэ?', 'Бүртгэл эхлэх огноо:\n2026 оны 8 сарын 1\n'))
        # A building or block is a place too.
        self.assertTrue(value_supported('Мэдээллийн технологийн төв хаана байрладаг вэ?',
                                        'Төв нь хичээлийн 2-р байрны А корпуст байрладаг.'))
        # The two-word rule is for existence questions only.
        self.assertIsNone(rule_selector.phrase_pair('Сургуулийн имэйл хаяг юу вэ?'))
        self.assertIsNone(rule_selector.phrase_pair('Элсэлтийн шалгалт хэзээ болох вэ?'))
        self.assertTrue(rule_selector.topic_covered('Сургуулийн имэйл хаяг юу вэ?',
                                                    'Хаяг: Улаанбаатар хот\nУтас: 7577\nИмэйл: info@nmct.edu.mn'))
        # «Төлбөрөө хэрхэн төлөх вэ?» asks which fee; a named fee does not.
        from source_fields import ambiguity
        self.assertEqual(ambiguity('Төлбөрөө хэрхэн төлөх вэ?', [dict(text='QPay')])[1],
                         ['Бүртгэлийн хураамжаа хэрхэн төлөх вэ?', 'Сургалтын төлбөрөө хэрхэн төлөх вэ?'])
        self.assertIsNone(ambiguity('Бүртгэлийн хураамжаа хэрхэн төлөх вэ?', [dict(text='QPay')]))

    def test_unanchored_question_takes_only_a_school_wide_page(self):
        query = 'Хэдэн оюутан суралцдаг вэ?'
        claim = 'Оюутны тоо\n2025–2026 оны хичээлийн жилд нийт 128 оюутан суралцаж байна.'
        department = 'Механик инженерийн тэнхим\n\nhttps://nmct.edu.mn/departments/mechanical'
        school = 'Бидний тухай\n\nhttps://nmct.edu.mn/about'
        self.assertTrue(rule_selector.value_missing(query, [claim], True, (), contexts=[department]))
        self.assertFalse(rule_selector.value_missing(query, [claim], True, (), contexts=[school]))
        # A range or an ordinal does not count a building: «тэргүүн байранд 1-3 байр».
        self.assertTrue(rule_selector.value_missing('Сургууль хэдэн байртай вэ?', ['тэргүүн байранд 1-3 байр'],
                                                    True, (), contexts=[school]))

    def test_title_only_anchor_needs_the_question_verb_for_a_count(self):
        query = 'Компьютерын ухааны тэнхимд хэдэн оюутан суралцдаг вэ?'
        page = 'Компьютерын ухааны тэнхим\n\nhttps://nmct.edu.mn/departments/computer-science'
        focus = {'компьютер'}
        self.assertTrue(rule_selector.value_missing(query, ['КУ-5 ангийн 3 оюутан компанид дадлага хийсэн.'],
                                                    True, focus, contexts=[page]))
        self.assertFalse(rule_selector.value_missing(query, ['Хичээлийн жилд нийт 128 оюутан суралцаж байна.'],
                                                     True, focus, contexts=[page]))

    def test_heading_line_matches_the_question_terms(self):
        self.assertTrue(rule_selector.heading_match('Сургуулийн эрхэм зорилго юу вэ?',
                                                    'Эрхэм зорилго\nМэргэжлийн болон харилцааны өндөр ур чадвартай'))
        self.assertFalse(rule_selector.heading_match('Сургуулийн эрхэм зорилго юу вэ?',
                                                     'Үнэт зүйлс\nсургуулийн эрхэм зорилго, үзэл санааны дор'))


class SiblingWindowTests(unittest.TestCase):
    def test_left_out_window_of_a_returned_page_joins(self):
        # 11/17 (5): two windows per page return; the window with the asked count was left out.
        from rag_runtime import sibling_windows
        url = 'https://nmct.edu.mn/departments/mechanical'

        def window(sid, text, address=url):
            return dict(source_id=sid, url=address, text=text, text_scope='main_element', title='Механик тэнхим')

        returned = [window('w1', 'Механик инженерийн тэнхим нь үйлдвэрлэлд суурилсан сургалттай.'),
                    window('w2', 'Механик инженерийн тэнхимийн лаборатори.')]
        rows = returned + [window('w3', 'Оюутны тоо\nНийт 128 оюутан суралцаж байна.'),
                           window('x1', 'Нийт 50 оюутан суралцаж байна.', 'https://nmct.edu.mn/departments/civil')]
        found = dict(candidates=list(returned), query_anchor_terms=['механик', 'тэнхим'])
        out = sibling_windows('Механик инженерийн тэнхимд хэдэн оюутан суралцдаг вэ?', found, rows)
        self.assertEqual(out['sibling_windows'], ['w3'])
        self.assertEqual([c['source_id'] for c in out['candidates']], ['w1', 'w2', 'w3'])
        # Review 11/17 (5): a window repeating a returned one by > 55 %, or lacking the asked class
        # code, does not join.
        repeat = dict(window('w4', 'Механик инженерийн тэнхим нь үйлдвэрлэлд суурилсан сургалттай. 128 оюутан'),
                      start_offset=0, end_offset=70)
        first = dict(returned[0], start_offset=0, end_offset=60)
        out = sibling_windows('Механик инженерийн тэнхимд хэдэн оюутан суралцдаг вэ?',
                              dict(candidates=[first], query_anchor_terms=[]), [first, repeat])
        self.assertNotIn('sibling_windows', out)
        out = sibling_windows('КУ-5 анги хэдэн оюутантай вэ?', dict(candidates=list(returned), query_anchor_terms=[]),
                              rows)
        self.assertNotIn('sibling_windows', out)
        # Only the returned page's own windows join, never another page's, and none twice.
        found = dict(candidates=[window('w3', 'Оюутны тоо\nНийт 128 оюутан суралцаж байна.')], query_anchor_terms=[])
        added = sibling_windows('Механик тэнхимд хэдэн оюутан суралцдаг вэ?', found, rows)['sibling_windows']
        self.assertNotIn('x1', added)
        self.assertNotIn('w3', added)


class EvidenceTests(unittest.TestCase):
    def test_total_is_a_whole_word(self):
        text = 'Лекцийн танхим\n2 том танхим\n242 суудал\nИнженерийн нийтлэг шаардлагад нийцүүлэн'
        self.assertNotIn('total', missing_query_markers('Хоёр том лекцийн танхим нийт хэдэн суудалтай вэ?',
                                                        '2 том танхим\n242 суудал', text))
        self.assertIn('total', missing_query_markers('Нийт хэдэн суудал вэ?', '242 суудал',
                                                     text + '\nНийт 900 суудал'))

    def test_page_title_may_supply_a_year_anchor(self):
        # 11/17 (5): «Цахим бүртгэл 08/03-08/13» on the page «Элсэлт 2026» answers a 2026 question.
        query = '2026 оны элсэлтийн цахим бүртгэл хэдий хугацаанд явагдсан бэ?'
        self.assertEqual(missing_query_markers(query, 'Цахим бүртгэл 08/03-08/13', '2026 онд\nЦахим бүртгэл'),
                         ['anchor:2026'])
        self.assertEqual(missing_query_markers(query, 'Цахим бүртгэл 08/03-08/13', '2026 онд\nЦахим бүртгэл',
                                               selected_context='ШМТК — Элсэлт 2026'), [])
        # Review 11/17 (5): only a year from the title; other numbers there never stand in.
        self.assertEqual(missing_query_markers('3-р курсын хичээл хэзээ вэ?', 'Хичээл эхэлнэ', '3-р курс',
                                               selected_context='2026 оны 3 сарын 11'), ['anchor:3'])

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

    def test_post_holders_from_the_staff_table(self):
        # Round 4 (11/17): «Сургуулийн захирал хэн бэ?» showed another university's president.
        tables = ReceptionTables(
            rooms=(Room(5, '508', services=(Service('Захирал', '', ''),)), Room(6, '605')),
            staff=(Staff(name='Т.Зохиомол', department='Захиргаа', room='508', role='Захирал',
                         email='fake.director@nmct.edu.mn'),
                   Staff(name='С.Туслах', department='Захиргаа', room='508', role='Захирлын туслах'),
                   Staff(name='Б.Эрхлэгч', department='Механик инженерийн тэнхим', room='605',
                         role='Механик инженерийн тэнхимийн эрхлэгч'),
                   Staff(name='Д.Эрхлэгч', department='Химийн инженерийн тэнхим', role='Химийн инженерийн тэнхимийн эрхлэгч'),
                   Staff(name='Э.Багш', department='Механик инженерийн тэнхим', role='Механик инженерийн тэнхимийн багш')),
            classes=(), timetable=())
        path = ReceptionAnswerPath(tables, enabled=True)
        # 11/23: a post holder's phone is never given; the school e-mail and the room are (reception topic 2).
        phone = path.answer('Захирлын утасны дугаар хэд вэ?')
        self.assertEqual(phone['reason_code'], 'reception_post_phone')
        self.assertIsNone(phone['answer'])   # the phone is not answered; the note says where to reach the person
        self.assertEqual(phone['message'], 'Ажилтны гар утасны дугаарыг энд өгдөггүй. Захирал Т.Зохиомол. '
                         'Сургуулийн имэйл: fake.director@nmct.edu.mn. Ажлын өрөө: 508 тоот, 5-р давхар.')
        self.assertEqual(path.answer('Захирлын гар утасны дугаар хэд вэ?')['message'], phone['message'])
        self.assertIsNone(path.answer('Сургуулийн утасны дугаар хэд вэ?'))
        director = path.answer('Сургуулийн захирал хэн бэ?')
        self.assertEqual(director['reason_code'], 'reception_role_holder')
        self.assertEqual(director['answer'], 'Т.Зохиомол — Захирал. Ажлын өрөө: 508 тоот, 5-р давхар. '
                                             'Сургуулийн имэйл: fake.director@nmct.edu.mn.')
        # Who heads a department is on its website page (W04-A11): the teacher directory answers
        # it with its source; a meeting with a head is not on the website, so this path takes it.
        for query in ('Механик тэнхимийн эрхлэгч хэн бэ?', 'Тэнхимийн эрхлэгч хэн бэ?', 'Механик тэнхимийн багш хэн бэ?'):
            with self.subTest(query=query):
                self.assertFalse(path.recognizes(query))
        self.assertIn('Б.Эрхлэгч — Механик инженерийн тэнхимийн эрхлэгч',
                      path.answer('Механик тэнхимийн эрхлэгчтэй уулзаж болох уу?')['answer'])
        meet = path.answer('Захиралтай уулзаж болох уу?')
        self.assertEqual(meet['reason_code'], 'reception_role_meet')
        self.assertIn('өрөөндөө байгаа эсэхийг мэдэх боломжгүй', meet['answer'])
        # A personal name, a post nobody holds, or the website's own people stay with the other paths.
        for query in ('Э.Багш хэн бэ?', 'Оюутны зөвлөлийн дарга хэн бэ?', 'Сургуулийг хэн үүсгэн байгуулсан бэ?'):
            with self.subTest(query=query):
                self.assertFalse(path.recognizes(query))
                self.assertIsNone(path.answer(query))

    def test_rooms_by_their_recorded_purpose(self):
        # Round 6: «Хурлын заал хэддүгээр давхарт байдаг вэ?» was refused though the table names room 809.
        tables = ReceptionTables(rooms=(Room(8, '809', purpose='Хурлын заал'), Room(4, '410', purpose='Компьютерын лаборатори'),
                                        Room(6, '613', purpose='Компьютерын лаборатори'), Room(4, '401', purpose='Анги'),
                                        Room(4, '402', purpose='Анги'), Room(4, '403', purpose='Анги'), Room(4, '404', purpose='Анги')),
                                 staff=(), classes=(), timetable=())
        path = ReceptionAnswerPath(tables, enabled=True)
        self.assertEqual(path.answer('Хурлын заал хэддүгээр давхарт байдаг вэ?')['answer'], 'Хурлын заал: 8-р давхар, 809 тоот.')
        self.assertEqual(path.answer('Компьютерын лаборатори хаана вэ?')['answer'],
                         'Компьютерын лаборатори: 4-р давхар, 410 тоот; 6-р давхар, 613 тоот.')
        self.assertFalse(path.recognizes('Анги хаана вэ?'))   # four rooms: too common to name
        # A near spelling or a room code is not a purpose (review, round 6).
        self.assertFalse(path.recognizes('Цахим лаборатори хаана вэ?'))
        self.assertEqual(path._purpose_rooms('809 өрөө'), [])

    def test_spoken_wordings_and_existence(self):
        # Round 8: questions typed or spoken without «вэ», «хэд давхарт», «лаб», «хаана суудаг»,
        # «… байдаг уу?» about a recorded service, and a class's timetable for «маргааш».
        tables = ReceptionTables(
            rooms=(Room(10, '1006', services=(Service('Номын сан', '', ''),)), Room(6, '607', services=(Service('Эмч', '', ''),)),
                   Room(8, '809', purpose='Хурлын заал'), Room(4, '410', purpose='Компьютерын лаборатори'), Room(6, '612')),
            staff=(), classes=(ClassGroup(group='КУ-2', room='612', course='2', department='Компьютерын ухааны тэнхим'),),
            timetable=(Lesson('thu', '08:00-09:30', 'КУ-2', '612', 'А.Багш'),),
            timetable_complete=True, calendar_bound=True, term_start=date(2026, 9, 7), term_end=date(2026, 12, 25),
            holidays_reviewed=True)
        path = ReceptionAnswerPath(tables, enabled=True)
        self.assertEqual(path.answer('номын сан хаана байдаг')['answer'], 'Номын сан: 10-р давхар, 1006 тоот.')
        self.assertEqual(path.answer('хурлын заал хэд давхарт')['answer'], 'Хурлын заал: 8-р давхар, 809 тоот.')
        self.assertEqual(path.answer('компьютерын лаб хаана')['answer'], 'Компьютерын лаборатори: 4-р давхар, 410 тоот.')
        self.assertEqual(path.answer('эмч байдаг уу')['answer'], 'Тийм. Эмч: 6-р давхар, 607 тоот.')
        self.assertFalse(path.recognizes('Дотуур байр байдаг уу?'))
        self.assertFalse(path.recognizes('Эмч байгаа юу?'))   # whether someone is there now
        tomorrow = path.answer('КУ-2 анги маргааш хэдэн цагт хичээлтэй вэ', now=datetime(2026, 11, 18, 10, 0))
        self.assertEqual(tomorrow['reason_code'], 'reception_class_day')
        self.assertIn('маргааш (пүрэв гараг) 08:00-аас хичээлтэй', tomorrow['answer'])   # nominative (code review 11/23 (8))
        self.assertIn('08:00-09:30', tomorrow['answer'])

    def test_round9_class_teacher_room_post_rooms_and_parents(self):
        tables = ReceptionTables(
            rooms=(Room(6, '604'), Room(8, '804', services=(Service('Санхүүгийн алба', '', ''),))),
            staff=(Staff(name='А.Номин-Эрдэнэ', department='КУ', room='604'),
                   Staff(name='С.Зохиомол', department='Санхүү', room='804', role='Нягтлан бодогч')),
            classes=(ClassGroup(group='КУ-2', room='612', teacher='А.Номин-Эрдэнэ'),), timetable=())
        path = ReceptionAnswerPath(tables, enabled=True)
        # «КУ-2 ангийн» was read as a teacher's name («багш олдсонгүй»).
        for query in ('КУ-2 ангийн багшийн өрөө хаана вэ?', 'КУ-2 ангийн багш хаана байна вэ?'):
            with self.subTest(query=query):
                room = path.answer(query)
                self.assertEqual(room['reason_code'], 'reception_class_teacher_room')
                self.assertIn('ажлын өрөө: 604, 6-р давхар. Яг одоо өрөөндөө байгаа эсэхийг мэдэх боломжгүй.', room['answer'])
        # «нягтлан» is the post «Нягтлан бодогч»: its one holder's room.
        post = path.answer('Нягтлан хаана байдаг вэ?')
        self.assertEqual(post['answer'], 'Нягтлан бодогч (С.Зохиомол): 8-р давхар, 804 тоот. Яг одоо өрөөндөө байгаа эсэхийг мэдэх боломжгүй.')
        # A parent who wants the class teacher is asked which class.
        self.assertEqual(path.answer('Хүүхдийнхээ ангийн багштай уулзмаар байна')['reason_code'], 'reception_group_required')
        self.assertFalse(path.recognizes('Хичээлийн хуваарь хаанаас харах вэ?'))   # no timetable loaded here
        for query in ('Хүүхдийн ангийн багш хаана вэ?', 'Хүүхдийн ангийн багшийн имэйл'):
            with self.subTest(query=query):
                self.assertEqual(path.answer(query)['reason_code'], 'reception_group_required')

    def test_round11_basement_floor(self):
        tables = ReceptionTables(rooms=(Room(-1, 'В3', purpose='Робокон клуб'),), staff=(), classes=(), timetable=())
        path = ReceptionAnswerPath(tables, enabled=True)
        self.assertEqual(path.answer('В3 тоот хэддүгээр давхарт вэ?')['answer'], 'В3 тоот өрөө хонгилын давхарт байрладаг (Робокон клуб).')
        self.assertEqual(path.answer('Робокон клуб хаана вэ?')['answer'], 'Робокон клуб: хонгилын давхар, В3 тоот.')

    def test_round12_posts_classes_teachers_and_the_calendar(self):
        tables = ReceptionTables(
            rooms=(Room(5, '508'), Room(6, '612'), Room(5, '509')),
            staff=(Staff(name='Т.Зохиомол', department='Захиргаа', room='508', role='Захирал', email='fake.director@nmct.edu.mn'),
                   Staff(name='Б.Багш', department='Ерөнхий эрдэм', room='509')),
            classes=(ClassGroup(group='КУ-2', room='612', course='2', department='Компьютерын ухааны тэнхим'),),
            timetable=(Lesson('mon', '08:00-09:30', 'КУ-2', '612', 'Б.Багш', 'Математик'),
                       Lesson('mon', '12:45-14:15', 'КУ-2', '612', 'Б.Багш', 'Физик'),
                       Lesson('thu', '09:35-11:05', 'КУ-2', '612', 'Б.Багш', 'Математик')),
            timetable_complete=True, calendar_bound=True, term_start=date(2026, 9, 7), term_end=date(2026, 12, 25),
            holidays=(date(2026, 11, 26),), holidays_reviewed=True)
        path = ReceptionAnswerPath(tables, enabled=True)
        # «Сургуулийн захирлын нэр хэн бэ?» was read as the post «… захирлын нэр»; «Захирлыг хэн гэдэг вэ?» too.
        for query in ('Сургуулийн захирлын нэр хэн бэ?', 'Захирлыг хэн гэдэг вэ?'):
            with self.subTest(query=query):
                self.assertIn('Т.Зохиомол — Захирал', path.answer(query)['answer'])
        # A wish to meet the post holder; a post holder's e-mail (the follow-up «Захирал имэйл»).
        self.assertEqual(path.answer('Захиралтай уулзах гэсэн юм')['reason_code'], 'reception_role_meet')
        self.assertIn('fake.director@nmct.edu.mn', path.answer('Захирал имэйл')['answer'])
        self.assertFalse(path.recognizes('Сургуулийн имэйл хаяг юу вэ?'))
        # A class's lesson hours by weekday; a teacher's subjects from the timetable.
        self.assertEqual(path.answer('КУ-2 ангийн хичээл хэдэн цагт дуусдаг вэ?')['answer'],
                         'КУ-2 — хуваарийн хичээлийн цаг: даваа 08:00–14:15; пүрэв 09:35–11:05. Хуваарь өөрчлөгдөж болно.')
        self.assertIn('Математик (КУ-2); Физик (КУ-2)', path.answer('Б.Багш багш ямар хичээл заадаг вэ?')['answer'])
        # The school calendar: a school day, a recorded holiday, a day without lessons.
        wednesday = datetime(2026, 11, 18, 10, 0)
        self.assertTrue(path.answer('Маргааш амралтын өдөр үү?', now=wednesday)['answer'].startswith('Үгүй. Маргааш (пүрэв гараг, 11/19) хичээлийн өдөр'))
        self.assertTrue(path.answer('Маргааш амралтын өдөр үү?', now=datetime(2026, 11, 25, 9, 0))['answer'].startswith('Тийм.'))
        self.assertIn('хуваарьт хичээл бүртгэгдээгүй', path.answer('Өнөөдөр хичээлтэй юу?', now=datetime(2026, 11, 22, 9, 0))['answer'])
        # Only what the tables can answer is claimed (review): an unknown teacher or class, a term start.
        for query in ('Англи хэлний багш ямар хичээл заадаг вэ?', 'Оройн ангийн хичээл хэдэн цагт эхэлдэг вэ?',
                      'КУ-2 ангийн хичээл хэзээ эхлэх вэ?'):
            with self.subTest(query=query):
                self.assertFalse(path.recognizes(query))
        # Without a reviewed calendar a day's status is not told.
        unknown = ReceptionAnswerPath(ReceptionTables(rooms=(), staff=(), classes=(), timetable=tables.timetable,
                                                      timetable_complete=True), enabled=True)
        self.assertFalse(unknown.recognizes('Маргааш амралтын өдөр үү?'))

    def test_round13_spoken_rooms_floors_and_typos(self):
        from reception_tables import _spoken_number, normalize_wording
        self.assertEqual(_spoken_number('таван зуун найм'.split()), 508)
        self.assertEqual(_spoken_number('мянга зургаа'.split()), 1006)
        self.assertEqual(_spoken_number('зургаан зуун арван хоёр'.split()), 612)
        self.assertIsNone(_spoken_number('хоёр гурав'.split()))
        self.assertEqual(normalize_wording('таван зуун найм тоот хаана вэ'), '508 тоот хаана вэ')
        self.assertEqual(normalize_wording('номын сан хана вэ'), 'номын сан хаана вэ')
        self.assertEqual(normalize_wording('захирлын өрөө хэд давхар вэ'), 'захирлын өрөө хэддүгээр давхарт вэ')
        # «хэдэн давхартай» (how many floors) stays as asked.
        self.assertEqual(normalize_wording('Сургууль хэдэн давхартай вэ?'), 'Сургууль хэдэн давхартай вэ?')
        # Review: «Сургууль хэдэн давхар вэ?» asks how many floors; «нэг өрөөнд» is no room number.
        self.assertEqual(normalize_wording('Сургууль хэдэн давхар вэ?'), 'Сургууль хэдэн давхар вэ?')
        self.assertEqual(normalize_wording('Дотуур байрны нэг өрөөнд хэдэн хүн амьдардаг вэ?'),
                         'Дотуур байрны нэг өрөөнд хэдэн хүн амьдардаг вэ?')
        self.assertEqual(normalize_wording('зуун нэгэн тоот хаана вэ'), '101 тоот хаана вэ')
        tables = ReceptionTables(
            rooms=(Room(4, '401', purpose='Анги'), Room(4, '406', purpose='Сургалтын алба'), Room(5, '508'),
                   Room(-1, 'В3', purpose='Робокон клуб')), staff=(), classes=(), timetable=())
        path = ReceptionAnswerPath(tables, enabled=True)
        self.assertEqual(path.answer('508 тоот хаана вэ?')['answer'], '508 тоот өрөө 5-р давхарт байрладаг.')
        self.assertEqual(path.answer('Дөрөвдүгээр давхарт юу байдаг вэ?')['answer'],
                         '4-р давхарт бүртгэлтэй: 406 (Сургалтын алба); анги, бусад өрөө: 401.')
        self.assertEqual(path.answer('Хонгилд юу байдаг вэ?')['answer'], 'Хонгилын давхарт бүртгэлтэй: В3 (Робокон клуб).')
        self.assertEqual(path.answer('2 давхарт юу байдаг вэ?')['reason_code'], 'reception_floor_unknown')
        self.assertEqual(path.answer('Хоёр давхарт юу байдаг вэ?')['reason_code'], 'reception_floor_unknown')
        self.assertFalse(path.recognizes('Энэ тоот хаана вэ?'))

    def test_round14_room_word_term_break_and_lesson_length(self):
        timetable = tuple(Lesson('mon', time, 'Г-%d' % index, '30%d' % (index % 9), 'Б.Багш', 'Математик')
                          for index in range(20) for time in ('08:00-09:30', '09:35-11:05', '13:20-14:50'))
        tables = ReceptionTables(rooms=(Room(3, '301'),), staff=(), classes=(), timetable=timetable,
                                 timetable_complete=True, calendar_bound=True, term_start=date(2026, 9, 7),
                                 term_end=date(2026, 12, 25), holidays_reviewed=True)
        path = ReceptionAnswerPath(tables, enabled=True)
        # W04-R07: «тоот өрөө» together.
        self.assertEqual(path.answer('301 тоот өрөө хэддүгээр давхарт вэ?')['answer'], '301 тоот өрөө 3-р давхарт байрладаг.')
        # The break's own dates are not recorded: the term's end and where to ask (review).
        self.assertEqual(path.answer('Улирлын амралт хэзээ эхлэх вэ?')['answer'],
                         'Хуанлид амралтын хугацаа бүртгэгдээгүй; энэ улирлын хичээл 2026-12-25-нд дуусна. '
                         'Амралтын яг хугацааг сургалтын албанаас тодруулна уу.')
        self.assertFalse(path.recognizes('Зуны амралт хэзээ эхлэх вэ?'))
        self.assertEqual(path.answer('Хичээл хэдэн минут үргэлжилдэг вэ?')['answer'],
                         'Хуваариар нэг хичээл ихэвчлэн 90 минут, хичээлийн хооронд 5 минутын завсарлагатай; '
                         '11:05–13:20 хооронд 135 минут (08:00-09:30, 09:35-11:05, 13:20-14:50).')

    def test_round25_questions_that_ask_a_clock_time(self):
        from rule_selector import _has_term
        from source_fields import staff_query_scope
        # «орой» (the evening) is not «орох» (to enter): the interview's time answered «Оройн анги хэдэн цагаас эхэлдэг вэ?».
        self.assertFalse(_has_term('оройн', frozenset({'орох', 'шалгалтад'})))
        self.assertTrue(_has_term('оройн', frozenset({'орой', 'анги'})))
        self.assertFalse(_has_term('оройн', frozenset({'оройтсон', 'оюутан'})))
        # A time, not how many teachers; a count question stays one.
        self.assertIsNone(staff_query_scope('Багш нар хэдэн цагт ирдэг вэ?', []))
        self.assertIsNotNone(staff_query_scope('Цахилгааны тэнхимд багш нар хэд вэ?', []))
        self.assertNotEqual(staff_query_scope('Математикийн багш хэд дэх өдөр ирдэг вэ?', [])['stop'], 'staff_count_not_supported')
        timetable = tuple(Lesson('mon', time, 'Г-%d' % index, '30%d' % (index % 9), 'Б.Багш', 'Математик')
                          for index in range(20) for time in ('08:00-09:30', '09:35-11:05', '11:10-12:40', '13:20-14:50'))
        tables = ReceptionTables(rooms=(Room(4, '406', services=(Service('Сургалтын алба', '08:00–17:00', ''),)),
                                        Room(10, '1006', services=(Service('Номын сан', '', ''),))),
                                 staff=(), classes=(), timetable=timetable, timetable_complete=True)
        path = ReceptionAnswerPath(tables, enabled=True)
        # Opening, closing and serving are the office's hours; an unrecorded place says so, an unknown one goes on.
        for query in ('Сургалтын алба хэдэн цагт хаадаг вэ?', 'Сургалтын алба хэдэн цаг хүртэл нээлттэй вэ?',
                      'Сургалтын алба хэдэн цагаас нээдэг вэ?'):
            with self.subTest(query=query):
                self.assertEqual(path.answer(query)['answer'], 'Сургалтын алба 08:00–17:00 цагийн хооронд ажилладаг (4-р давхар, 406 тоот).')
                self.assertTrue(path.recognizes(query))
        self.assertEqual(path.answer('Номын сан хэдэн цаг хүртэл нээлттэй вэ?')['reason_code'], 'reception_hours_unknown')
        # Taking payments is not confirmed to follow the working hours: no answer, a note that says so (11/23 (2));
        # an unknown place is not claimed at all.
        payment = path.answer('Сургалтын алба хэдэн цаг хүртэл төлбөр авдаг вэ?')
        self.assertIsNone(payment['answer'])
        self.assertIn('Төлбөр хүлээн авах цагийн тусгай мэдээлэл алга', payment['message'])
        for query in ('Дотуур байр хэдэн цагт хаадаг вэ?', 'Гал тогоо хэдэн цагаас ажилладаг вэ?'):
            with self.subTest(query=query):
                self.assertIsNone(path.answer(query))
                self.assertFalse(path.recognizes(query))
        # The school's own hours in the same verbs, when the user-confirmed value is set.
        from reception_tables import _corrected
        school = ReceptionAnswerPath(_corrected(tables, {'school_hours': '08:00–17:00'}), enabled=True)
        for query in ('Сургууль хэдэн цагт хаагддаг вэ?', 'Сургууль хэдэн цаг хүртэл нээлттэй вэ?'):
            with self.subTest(query=query):
                self.assertEqual(school.answer(query)['answer'], 'Сургуулийн ажлын цаг: 08:00–17:00.')
        # The school day's times in the other wordings.
        for query in ('Сургууль хэдэн цагт тардаг вэ?', 'Сүүлийн цаг хэдэн цагт дуусдаг вэ?', 'Хичээл хэдэн цаг хүртэл ордог вэ?',
                      'Эхний цаг хэдэн цагаас эхэлдэг вэ?'):
            with self.subTest(query=query):
                self.assertEqual(path.answer(query)['reason_code'], 'reception_bell_schedule')
        # The day's first start and last end do not answer the first lesson's end or the last one's start.
        for query in ('Эхний цаг хэдэн цагт дуусдаг вэ?', 'Сүүлийн хичээл хэдэн цагт эхэлдэг вэ?'):
            with self.subTest(query=query):
                self.assertNotEqual((path.answer(query) or {}).get('reason_code'), 'reception_bell_schedule')
        # The midday break is the one longer gap between the shared lesson times; the offices' break is not recorded.
        for query in ('Өдрийн завсарлага хэдэн цагт вэ?', 'Их завсарлага хэзээ вэ?', 'Хичээлийн цайны цаг хэдээс хэд хүртэл вэ?'):
            with self.subTest(query=query):
                self.assertEqual(path.answer(query)['answer'], 'Хуваариар хичээлийн өдрийн завсарлага '
                                 '12:40–13:20 (40 минут).')
        # A bare «цайны цаг» or «завсарлага» may ask something else: not claimed.
        for query in ('Цайны цаг хэдээс хэд хүртэл вэ?', 'Завсарлага хэзээ вэ?', 'Сургалтын алба цайны цагаар ажилладаг уу?'):
            with self.subTest(query=query):
                self.assertNotEqual((path.answer(query) or {}).get('reason_code'), 'reception_lunch_break')

        def path_with(times, extra=()):
            return ReceptionAnswerPath(ReceptionTables(rooms=(), staff=(), classes=(), timetable=tuple(
                Lesson('mon', time, 'Г-%d' % index, '301', 'Б.Багш', 'Математик')
                for index in range(20) for time in times) + tuple(extra), timetable_complete=True), enabled=True)
        # Equal gaps, a single gap and a short pause name no midday break.
        for times in (('08:00-09:30', '09:35-11:05', '11:10-12:40'), ('08:00-09:30', '09:35-11:05'),
                      ('08:00-09:30', '09:35-11:05', '11:15-12:45')):
            with self.subTest(times=times):
                self.assertEqual(path_with(times).answer('Өдрийн завсарлага хэдэн цагт вэ?')['reason_code'], 'reception_lookup_missing')
        # A joined lesson through the break: most classes, not all.
        joined = path_with(('08:00-09:30', '09:35-11:05', '11:10-12:40', '13:20-14:50'),
                           (Lesson('mon', '11:10-14:50', 'Г-99', '302', 'Б.Багш', 'Дадлага'),))
        self.assertEqual(joined.answer('Өдрийн завсарлага хэдэн цагт вэ?')['answer'],
                         'Хуваариар ихэнх анги 12:40–13:20 хооронд хичээлгүй (өдрийн завсарлага, 40 минут).')

    def test_round15_room_timetable_subject_teachers_and_teacher_rooms(self):
        tables = ReceptionTables(
            rooms=(Room(6, '612'),), staff=(Staff(name='Б.Багш', department='Ерөнхий эрдэм', room='509'),),
            classes=(ClassGroup(group='КУ-2', room='612', course='2', department='Компьютерын ухааны тэнхим'),),
            timetable=(Lesson('wed', '09:35-11:05', 'КУ-2', '612', 'Б.Багш', 'Хими'),
                       Lesson('wed', '11:10-12:40', 'КУ-2', '612', 'Б.Багш', 'Хэрэглээний математик 1'),
                       Lesson('mon', '08:00-09:30', 'КУ-2', '612', 'А.Багш', 'Техникийн Англи хэл')),
            timetable_complete=True, calendar_bound=True, term_start=date(2026, 9, 7), term_end=date(2026, 12, 25),
            holidays_reviewed=True)
        path = ReceptionAnswerPath(tables, enabled=True)
        wednesday = datetime(2026, 11, 18, 10, 0)
        self.assertEqual(path.answer('612 тоотод одоо хичээл орж байна уу?', now=wednesday)['answer'],
                         '612 тоот — хуваариар одоо (лхагва 10:00): 09:35-11:05 КУ-2 (Хими). '
                         'Дараагийн хичээл: 11:10-12:40 КУ-2 (Хэрэглээний математик 1).')
        self.assertIn('хичээл бүртгэгдээгүй (сул)', path.answer('612 тоот одоо сул уу?', now=datetime(2026, 11, 18, 13, 0))['answer'])
        self.assertEqual(path.answer('612 тоот өрөөнд даваа гарагт ямар хичээл ордог вэ?')['answer'],
                         '612 тоот — даваа гарагт хичээл: 08:00-09:30 КУ-2 (Техникийн Англи хэл). Хуваарь өөрчлөгдөж болно.')
        self.assertFalse(path.recognizes('999 тоотод одоо хичээл орж байна уу?'))   # not a recorded room
        # rag_runtime calls answer() alone: what is not claimed gets None and goes on to the website (review).
        self.assertIsNone(path.answer('999 тоотод одоо хичээл орж байна уу?', now=wednesday))
        self.assertIsNone(path.answer('Механик тэнхимийн багш нар хэн хэн бэ?'))
        self.assertIsNone(path.answer('Б.Сэлмаа багш хэн бэ?'))
        # Teachers of a subject from the timetable; a department or class is not a subject.
        self.assertIn('Хэрэглээний математик 1 — Б.Багш', path.answer('Математикийн багш хэн бэ?')['answer'])
        self.assertIn('Техникийн Англи хэл — А.Багш', path.answer('Англи хэлний хичээл хэн заадаг вэ?')['answer'])
        for query in ('Механик тэнхимийн багш хэн бэ?', 'Түүхийн багш хэн бэ?'):
            with self.subTest(query=query):
                self.assertFalse(path.recognizes(query))
        # Where a teacher teaches on a day: the lessons with their rooms.
        partial = ReceptionAnswerPath(ReceptionTables(rooms=tables.rooms, staff=(), classes=(), timetable=tables.timetable[:1],
                                                      timetable_complete=False), enabled=True)
        # A partial timetable never calls a room free (review).
        self.assertEqual(partial.answer('612 тоот одоо сул уу?', now=datetime(2026, 11, 18, 13, 0))['reason_code'],
                         'reception_timetable_incomplete')
        self.assertIn('09:35-11:05 (612 тоот), 11:10-12:40 (612 тоот)',
                      path.answer('Б.Багш багш өнөөдөр хаана хичээл заах вэ?', now=wednesday)['answer'])

    def test_round16_term_start_and_week_holidays(self):
        timetable = (Lesson('mon', '08:00-09:30', 'КУ-2', '612', 'Б.Багш', 'Хими'),)
        tables = ReceptionTables(rooms=(), staff=(), classes=(), timetable=timetable, timetable_complete=True,
                                 calendar_bound=True, term_start=date(2026, 9, 7), term_end=date(2026, 12, 25),
                                 holidays=(date(2026, 11, 20),), holidays_reviewed=True)
        path = ReceptionAnswerPath(tables, enabled=True)
        self.assertEqual(path.answer('Хичээл хэзээ эхэлсэн бэ?')['reason_code'], 'reception_term_dates')
        self.assertEqual(path.answer('Энэ долоо хоногт амралтын өдөр бий юу?', now=datetime(2026, 11, 18, 10, 0))['answer'],
                         'Энэ долоо хоногт (11/16–11/22) амралтын өдөр: баасан (11/20).')
        self.assertEqual(path.answer('Энэ долоо хоногт амралтын өдөр бий юу?', now=datetime(2026, 11, 25, 10, 0))['answer'],
                         'Энэ долоо хоногт (11/23–11/29) хуанлид амралтын өдөр байхгүй.')
        # Days outside the term are said, and a week wholly outside it is (review).
        self.assertEqual(path.answer('Энэ долоо хоногт амралтын өдөр бий юу?', now=datetime(2026, 12, 23, 10, 0))['answer'],
                         'Энэ долоо хоногт (12/21–12/27) хуанлид амралтын өдөр байхгүй. '
                         'Хичээлийн улирлаас гадуур: бямба (12/26), ням (12/27).')
        self.assertEqual(path.answer('Энэ долоо хоногт амралтын өдөр бий юу?', now=datetime(2027, 1, 13, 10, 0))['reason_code'],
                         'reception_outside_term')
        # «Хичээл хэзээ дуусах вэ?» may ask about today's lessons: it is not read as the term.
        self.assertFalse(path.recognizes('Хичээл хэзээ дуусах вэ?'))
        # Without reviewed term dates: the term question says so; the week question, like «Маргааш амралтын
        # өдөр үү?», is left to the website path (review).
        unknown = ReceptionAnswerPath(ReceptionTables(rooms=(), staff=(), classes=(), timetable=timetable), enabled=True)
        self.assertTrue(unknown.recognizes('Хичээл хэзээ эхэлсэн бэ?'))
        self.assertEqual(unknown.answer('Хичээл хэзээ эхэлсэн бэ?')['reason_code'], 'reception_calendar_unknown')
        self.assertFalse(unknown.recognizes('Энэ долоо хоногт амралтын өдөр бий юу?'))
        self.assertIsNone(unknown.answer('Энэ долоо хоногт амралтын өдөр бий юу?', now=datetime(2026, 11, 18, 10, 0)))

    def test_round18_department_by_short_name_and_class_timetable(self):
        tables = ReceptionTables(
            rooms=(Room(-1, 'В6', 'Туршилтын өрөө', 'Механик инженерийн тэнхим'), Room(6, '605', 'Багш нарын өрөө', 'Механик инженерийн тэнхим'),
                   Room(3, '304', 'Багш нарын өрөө', 'Барилга, дэд бүтцийн инженерийн тэнхим')),
            staff=(), classes=(ClassGroup(group='КУ-2', room='612'),),
            timetable=(Lesson('mon', '08:00-09:30', 'КУ-2', '612', 'Б.Багш', 'Хими'),), timetable_complete=True)
        path = ReceptionAnswerPath(tables, enabled=True)
        # «Механик тэнхим» is «Механик инженерийн тэнхим»; the teachers' room comes first; «байдаг» too.
        for query in ('Механик тэнхим хаана вэ?', 'Механик тэнхим хаана байдаг вэ?'):
            with self.subTest(query=query):
                self.assertEqual(path.answer(query)['answer'],
                                 'Тэнхимд хамаарах бүртгэлтэй өрөө: 605 (6-р давхар; Багш нарын өрөө); В6 (хонгилын давхар; '
                                 'Туршилтын өрөө).')
        self.assertIn('304 (3-р давхар', path.answer('Барилгын тэнхимийн өрөө хаана вэ?')['answer'])
        # The teachers' room when that is asked (W04-R08); an unrecorded department goes on to the website (review).
        self.assertNotIn('В6', path.answer('Механик инженерийн тэнхимийн багш нарын өрөө хаана вэ?')['answer'])
        self.assertFalse(path.recognizes('Цахилгааны тэнхим хаана байдаг вэ?'))
        self.assertIsNone(path.answer('Цахилгааны тэнхим хаана байдаг вэ?'))
        # A class's timetable asked without a question word: the week's lessons with their rooms.
        self.assertEqual(path.answer('КУ-2 ангийн хуваарь')['answer'],
                         'КУ-2 — долоо хоногийн хуваарь: даваа 08:00 Хими (612). Хуваарь өөрчлөгдөж болно.')

    def test_round19_teachers_rooms_subject_teachers_and_office_staff(self):
        tables = ReceptionTables(
            rooms=(Room(3, '304', 'Багш нарын өрөө', 'Барилга, дэд бүтцийн инженерийн тэнхим'), Room(4, '408', 'Багш нарын өрөө'),
                   Room(6, '605', 'Багш нарын өрөө', 'Механик инженерийн тэнхим'), Room(10, '1007', 'Карьер хөгжлийн төв')),
            staff=(Staff(name='А.Багш', department='Ерөнхий эрдмийн тэнхим', room='408'), Staff(name='Б.Багш', department='Ерөнхий эрдмийн тэнхим'),
                   Staff(name='В.Ажилтан', department='Гадаад харилцаа, карьер хөгжлийн төв', room='1007', role='Карьерын мэргэжилтэн')),
            classes=(), timetable=(Lesson('mon', '08:00-09:30', 'КУ-2', '612', 'А.Багш', 'Англи хэл'),
                                   Lesson('tue', '08:00-09:30', 'КУ-2', '612', 'Б.Багш', 'Техникийн англи хэл')),
            timetable_complete=True)
        path = ReceptionAnswerPath(tables, enabled=True)
        # The teachers' rooms of several departments: the departments tell them apart.
        self.assertEqual(path.answer('Багш нарын өрөө хаана вэ?')['answer'],
                         'Багш нарын өрөө: 3-р давхар, 304 тоот (Барилга, дэд бүтцийн инженерийн тэнхим); 4-р давхар, 408 тоот; '
                         '6-р давхар, 605 тоот (Механик инженерийн тэнхим).')
        # The teachers of a subject with their recorded rooms; a named teacher keeps their own office.
        expected = ('Бүртгэсэн хуваарьт Англи хэл, Техникийн англи хэл заадаг багш нарын ажлын өрөө: А.Багш — 408 өрөө, '
                    '4-р давхар; Б.Багш — өрөө бүртгэгдээгүй. Яг одоо өрөөндөө байгаа эсэхийг мэдэх боломжгүй.')
        for query in ('Англи хэлний багш нар хаана байдаг вэ?', 'Англи хэлний багшийн өрөө хаана вэ?'):
            with self.subTest(query=query):
                self.assertEqual(path.answer(query)['answer'], expected)
        self.assertEqual(path.answer('А.Багш багшийн өрөө хаана вэ?')['reason_code'], 'reception_teacher_office')
        # Who staffs an office; a short or unknown name is left to the website.
        self.assertEqual(path.answer('Карьер хөгжлийн төв хэн хариуцдаг вэ?')['answer'],
                         'Гадаад харилцаа, карьер хөгжлийн төв — ажилтан: В.Ажилтан (Карьерын мэргэжилтэн). '
                         'Ажлын өрөө: 1007 (10-р давхар).')
        self.assertFalse(path.recognizes('Номын сан хэн хариуцдаг вэ?'))
        # Review: «… багшийн өрөө хаана байдаг вэ?» too; a person named with an initial is no subject, though
        # «мэргэ» starts «Мэргэжлийн англи хэл»; a department's head answers who is responsible.
        self.assertEqual(path.answer('Англи хэлний багшийн өрөө хаана байдаг вэ?')['answer'], expected)
        self.assertEqual(path.answer('А.Багш багшийн өрөө хаана байдаг вэ?')['reason_code'], 'reception_teacher_office')
        named = ReceptionAnswerPath(ReceptionTables(rooms=(), staff=(Staff(name='Д.Мэргэн', department='Ерөнхий эрдмийн тэнхим'),),
                                                    classes=(), timetable=(Lesson('mon', '08:00-09:30', 'КУ-2', '612', 'А.Багш',
                                                                                   'Мэргэжлийн англи хэл'),)), enabled=True)
        self.assertEqual(named._subject_teachers('Д.Мэргэн'), {})
        heads = ReceptionAnswerPath(ReceptionTables(rooms=(Room(6, '605', 'Багш нарын өрөө', 'Механик инженерийн тэнхим'),), classes=(),
            staff=(Staff(name='Б.Эрхлэгч', department='Механик инженерийн тэнхим', room='605', role='Механик инженерийн тэнхимийн эрхлэгч'),
                   Staff(name='В.Багш', department='Механик инженерийн тэнхим'), Staff(name='Г.Багш', department='Механик инженерийн тэнхим')),
            timetable=()), enabled=True)
        self.assertEqual(heads.answer('Механик инженерийн тэнхим хэн хариуцдаг вэ?')['answer'],
                         'Механик инженерийн тэнхим — хариуцагч: Б.Эрхлэгч (Механик инженерийн тэнхимийн эрхлэгч). '
                         'Ажлын өрөө: 605 (6-р давхар).')

    def test_round20_indirect_questions_contacts_and_office_staff(self):
        from reception_tables import normalize_wording
        # An indirect question asks the plain one.
        for asked, plain in (('Номын сан хаана байдгийг хэлж өгөөч', 'Номын сан хаана байдаг вэ'),
                             ('Эмчийн өрөө хаана байгааг мэдэх үү?', 'Эмчийн өрөө хаана байдаг вэ?'),
                             ('Сургалтын албаны өрөөг хэлж өгнө үү', 'Сургалтын албаны өрөө хаана вэ'),
                             ('Захирлын өрөө хэдэн давхарт байдгийг хэлээч', 'Захирлын өрөө хэддүгээр давхарт байдаг вэ')):
            with self.subTest(asked=asked):
                self.assertEqual(normalize_wording(asked), plain)
        tables = ReceptionTables(
            rooms=(Room(4, '406', services=(Service('Сургалтын алба', '', ''),)), Room(4, '409', services=(Service('Сэтгэл зүйч', '', ''),)),
                   Room(10, '1006', 'Номын сан')),
            staff=(Staff(name='Н.Зүйч', department='Оюутны алба', room='409', role='Сэтгэл зүйч', email='zuich@nmct.edu.mn'),
                   Staff(name='Х.Номч', department='Номын сан', room='1006', role='Номын санч')),
            classes=(), timetable=())
        path = ReceptionAnswerPath(tables, enabled=True)
        # A post one person holds: their school e-mail and room, also when a room carries the post's name.
        self.assertEqual(path.answer('Сэтгэл зүйчтэй хэрхэн холбогдох вэ?')['answer'],
                         'Н.Зүйч — Сэтгэл зүйч. Сургуулийн имэйл: zuich@nmct.edu.mn. Ажлын өрөө: 409 тоот, 4-р давхар.')
        self.assertEqual(path.answer('Сургалтын албатай яаж холбогдох вэ?')['reason_code'], 'reception_contact_unknown')
        # «Сургалтын албаны өрөө» names the office; «Номын сангийн ажилтан хэн бэ?» its recorded staff.
        self.assertEqual(path.answer('Сургалтын албаны өрөө хаана вэ?')['answer'], 'Сургалтын алба: 4-р давхар, 406 тоот.')
        # Review: one staff member of an office is not its contact; a yes/no «… байгааг мэдэх үү?» stays as asked.
        lone = ReceptionAnswerPath(ReceptionTables(rooms=(Room(4, '406', services=(Service('Сургалтын алба', '', ''),)),),
                                                   staff=(Staff(name='А.Б', department='Сургалтын алба', role='Арга зүйч',
                                                                email='ab@nmct.edu.mn'),), classes=(), timetable=()), enabled=True)
        self.assertEqual(lone.answer('Сургалтын албатай яаж холбогдох вэ?')['reason_code'], 'reception_contact_unknown')
        self.assertEqual(normalize_wording('Номын сан нээлттэй байгааг мэдэх үү?'), 'Номын сан нээлттэй байгааг мэдэх үү?')
        self.assertEqual(normalize_wording('Номын сан хаана байрладгийг хэлж өгөөч'), 'Номын сан хаана байрладаг вэ')
        for query in ('Номын сангийн ажилтан хэн бэ?', 'Номын сан хэн ажилладаг вэ?', 'Номын санд хэн ажилладаг вэ?'):
            with self.subTest(query=query):
                self.assertEqual(path.answer(query)['answer'],
                                 'Номын сан — ажилтан: Х.Номч (Номын санч). Ажлын өрөө: 1006 (10-р давхар).')

    def test_round21_spoken_fillers_and_colloquial_endings(self):
        from reception_tables import normalize_wording
        # A filler at the start and a colloquial ending, as speech recognition writes them; a statement stays.
        for spoken, plain in (('аан номын сан хаана байдаг юм бэ', 'номын сан хаана байдаг вэ'),
                              ('тэгээд захирал хэн юм бэ', 'захирал хэн бэ'),
                              ('нөгөө сургалтын алба хаана байдаг билээ', 'сургалтын алба хаана байдаг вэ'),
                              ('эмч хаана байдаг юм', 'эмч хаана байдаг вэ'),
                              ('захиралтай уулзаж болох юм уу', 'захиралтай уулзаж болох уу'),
                              ('энэ долоо хоногт амралтын өдөр бий юм уу', 'энэ долоо хоногт амралтын өдөр бий юу'),
                              ('сургуулийн хаяг юу юм бэ', 'сургуулийн хаяг юу вэ'),
                              ('Тийм юм', 'Тийм юм'), ('Ана хаана байна вэ', 'Ана хаана байна вэ'),
                              # Review: an initial is no filler; «нөгөө» (the other) stays; «и» sets no harmony;
                              # a statement or a noun «юм» stays; space after the mark.
                              ('Э.Батаа багш хаана байдаг вэ', 'Э.Батаа багш хаана байдаг вэ'),
                              ('нөгөө байр хаана байдаг вэ', 'нөгөө байр хаана байдаг вэ'),
                              ('Тийм юм уу', 'Тийм үү'),
                              ('Хаана байгааг нь мэдэхгүй юм', 'Хаана байгааг нь мэдэхгүй юм'),
                              ('Ямар юм бэ', 'Ямар юм бэ'), ('хэн юм бэ? ', 'хэн бэ?')):
            with self.subTest(spoken=spoken):
                self.assertEqual(normalize_wording(spoken), plain)

    def test_round22_lessons_on_a_weekday(self):
        timetable = (Lesson('mon', '08:00-09:30', 'КУ-2', '612', 'Б.Багш', 'Хими'),)
        path = ReceptionAnswerPath(ReceptionTables(rooms=(), staff=(), classes=(), timetable=timetable, timetable_complete=True),
                                   enabled=True)
        self.assertEqual(path.answer('Ням гарагт хичээл ордог уу?')['answer'], 'Үгүй. Ням гарагт хуваарьт хичээл байхгүй.')
        self.assertEqual(path.answer('Даваа гарагт хичээлтэй юу?')['answer'],
                         'Тийм. Даваа гарагт хуваарьт 1 анги хичээлтэй. Амралт, баярын өдөр өөр байж болно.')
        # A partial timetable never says a day has no lessons.
        partial = ReceptionAnswerPath(ReceptionTables(rooms=(), staff=(), classes=(), timetable=timetable), enabled=True)
        self.assertEqual(partial.answer('Ням гарагт хичээл ордог уу?')['reason_code'], 'reception_timetable_incomplete')
        # Review: the other spelling and the dative; outside the term the stored timetable does not apply.
        for query in ('Ням гаригт хичээл ордог уу?', 'Нямд хичээлтэй юу?'):
            with self.subTest(query=query):
                self.assertEqual(path.answer(query)['reason_code'], 'reception_weekday_no_lessons')
        bound = ReceptionAnswerPath(ReceptionTables(rooms=(), staff=(), classes=(), timetable=timetable, timetable_complete=True,
                                                    calendar_bound=True, term_start=date(2026, 9, 1), term_end=date(2026, 12, 31),
                                                    holidays_reviewed=True), enabled=True)
        self.assertEqual(bound.answer('Даваа гарагт хичээлтэй юу?', now=datetime(2027, 2, 1, 10, 0))['reason_code'],
                         'reception_outside_term')

    def test_corrections_confirmed_after_the_import(self):
        from reception_tables import ReceptionDataError, _corrected
        tables = ReceptionTables(
            rooms=(Room(4, '406', services=(Service('Сургалтын алба', '', ''),)), Room(4, '409', services=(Service('Оюутны алба', '09:00–16:00', ''),)),
                   Room(10, '1001', 'Сэтгэл зүйчийн өрөө', services=(Service('Сэтгэл зүйч', '', ''),))),
            staff=(Staff(name='Н.Зүйч', department='Оюутны алба', room='409', role='Сэтгэл зүйч'),), classes=(), timetable=())
        self.assertIs(_corrected(tables, None), tables)
        fixed = ReceptionAnswerPath(_corrected(tables, {'note_mn': 'тест', 'office_hours': {'name_contains': 'алба', 'hours': '08:00–17:00'},
                                                        'staff_room_by_role': {'Сэтгэл зүйч': '1001'}}), enabled=True)
        # The common hours go to offices without their own; a recorded value stays; other services get none.
        self.assertEqual(fixed.answer('Сургалтын алба хэдэн цагт ажилладаг вэ?')['answer'], 'Сургалтын алба 08:00–17:00 цагийн хооронд ажилладаг (4-р давхар, 406 тоот).')
        self.assertEqual(fixed.answer('Оюутны алба хэдэн цагт ажилладаг вэ?')['answer'], 'Оюутны алба 09:00–16:00 цагийн хооронд ажилладаг (4-р давхар, 409 тоот).')
        # The other wordings of the same question; an office's own name may hold a comma.
        for query in ('Сургалтын алба хэдэн цагаас ажилладаг вэ?', 'Сургалтын алба хэдэн цаг хүртэл ажилладаг вэ?',
                      'Сургалтын албаны ажлын цаг хэд вэ?'):
            with self.subTest(query=query):
                self.assertEqual(fixed.answer(query)['answer'], 'Сургалтын алба 08:00–17:00 цагийн хооронд ажилладаг (4-р давхар, 406 тоот).')
        comma = ReceptionAnswerPath(_corrected(ReceptionTables(rooms=(Room(4, '405', services=(Service('Дотоод хяналт, чанарын алба', '', ''),)),),
                                                              staff=(), classes=(), timetable=()),
                                               {'office_hours': {'name_contains': 'алба', 'hours': '08:00–17:00'}}), enabled=True)
        self.assertEqual(comma.answer('Дотоод хяналт, чанарын алба хэдэн цагт ажилладаг вэ?')['answer'],
                         'Дотоод хяналт, чанарын алба 08:00–17:00 цагийн хооронд ажилладаг (4-р давхар, 405 тоот).')
        self.assertIsNone(fixed.answer('Сургуулийн ажлын цаг хэд вэ?'))   # the school's own hours: the website answer
        self.assertEqual(fixed.answer('Сэтгэл зүйч хэдэн цагт ажилладаг вэ?')['reason_code'], 'reception_hours_unknown')
        # The post's holder sits in the corrected room.
        self.assertIn('Ажлын өрөө: 1001 тоот, 10-р давхар', fixed.answer('Сэтгэл зүйчтэй уулзаж болох уу?')['answer'])
        # Anything malformed rejects the dataset: an unknown key, a free-text hour, an unrecorded room.
        for bad in ({'rooms': {}}, {'office_hours': {'name_contains': 'алба', 'hours': 'өглөөнөөс орой'}},
                    {'staff_room_by_role': {'Сэтгэл зүйч': '9999'}}, ['алба']):
            with self.subTest(bad=bad), self.assertRaises(ReceptionDataError):
                _corrected(tables, bad)

    def test_the_schools_general_hours_confirmed_by_the_user(self):
        # Round 24 (11/19): the user confirmed 08:00–17:00; the website's contact page says 09:00–18:00, and
        # «Сургууль хэдэн цагаас ажилладаг вэ?» showed an entrance-exam time.
        from reception_tables import ReceptionDataError, _corrected
        tables = ReceptionTables(rooms=(Room(4, '406', services=(Service('Сургалтын алба', '09:00–16:00', ''),)),
                                        Room(10, '1006', services=(Service('Номын сан', '', ''),))),
                                 staff=(), classes=(), timetable=())
        fixed = ReceptionAnswerPath(_corrected(tables, {'school_hours': '08:00–17:00'}), enabled=True)
        for query in ('Сургууль хэдэн цагт ажилладаг вэ?', 'Сургууль хэдэн цагаас ажилладаг вэ?',
                      'Сургууль хэдэн цаг хүртэл ажилладаг вэ?', 'Сургуулийн ажлын цаг хэд вэ?', 'Хэдэн цагт ажилладаг вэ?',
                      'Та нар хэдэн цагт ажилладаг вэ?', 'Танай сургууль хэдээс хэд хүртэл ажилладаг вэ?',
                      'Сургууль хэдэн цагт нээдэг вэ?', 'ШМТК-ийн ажлын цаг хэд вэ?', 'аан сургууль хэдэн цагт ажилладаг юм бэ'):
            with self.subTest(query=query):
                result = fixed.answer(query)
                self.assertEqual(result['answer'], 'Сургуулийн ажлын цаг: 08:00–17:00.')
                self.assertEqual(result['reason_code'], 'reception_school_hours')
                self.assertTrue(fixed.recognizes(query))
        # A named office keeps its own hours; an unconfirmed day, a lesson time and another place are not the school's hours.
        self.assertEqual(fixed.answer('Сургалтын алба хэдэн цагт ажилладаг вэ?')['answer'], 'Сургалтын алба 09:00–16:00 цагийн хооронд ажилладаг (4-р давхар, 406 тоот).')
        self.assertEqual(fixed.answer('Номын сан хэдэн цагт ажилладаг вэ?')['reason_code'], 'reception_hours_unknown')
        for query in ('Сургууль бямба гарагт ажилладаг уу?', 'Бямба гарагт хэдэн цагт ажилладаг вэ?',
                      'Сургууль хэдэн цагт тардаг вэ?', 'Сургуулийн номын сан хэдэн цагт ажилладаг вэ?'):
            with self.subTest(query=query):
                self.assertNotEqual((fixed.answer(query) or {}).get('reason_code'), 'reception_school_hours')
        # Without the confirmed value the question stays with the website answer; a free-text value is rejected.
        self.assertIsNone(ReceptionAnswerPath(_corrected(tables, {}), enabled=True).answer('Сургууль хэдэн цагт ажилладаг вэ?'))
        for bad in ('өглөөнөөс орой', 8, ['08:00–17:00']):
            with self.subTest(bad=bad), self.assertRaises(ReceptionDataError):
                _corrected(tables, {'school_hours': bad})

    def test_the_lunch_break_confirmed_by_the_user(self):
        # 2026-11-20: the user confirmed with the school that the lunch break is always 12:40–13:20.
        from reception_tables import ReceptionDataError, _corrected
        tables = ReceptionTables(rooms=(Room(4, '406', services=(Service('Сургалтын алба', '08:00–17:00', ''),)),),
                                 staff=(), classes=(), timetable=())
        fixed = ReceptionAnswerPath(_corrected(tables, {'lunch_break': '12:40–13:20'}), enabled=True)
        for query in ('Цайны цаг хэдээс хэд хүртэл вэ?', 'Цайны цаг хэдэн цагт вэ?', 'Сургуулийн цайны цаг хэзээ вэ?',
                      'Өдрийн цайны цаг хэдэн цагаас вэ?', 'Их завсарлага хэзээ вэ?', 'Албадын цайны цаг хэдэн цагт вэ?',
                      'цайны цаг'):
            with self.subTest(query=query):
                result = fixed.answer(query)
                self.assertEqual(result['answer'], 'Сургуулийн цайны цаг: 12:40–13:20.')
                self.assertEqual(result['reason_code'], 'reception_lunch_break')
                self.assertTrue(fixed.recognizes(query))
        # Whether an office serves through the break was not said; other «цаг» questions keep their own answers.
        for query in ('Сургалтын алба цайны цагаар ажилладаг уу?', 'Сургалтын алба хэдэн цагт ажилладаг вэ?',
                      'Цайны газар хаана байдаг вэ?', 'Завсарлага хэдэн минут вэ?'):
            with self.subTest(query=query):
                self.assertNotEqual((fixed.answer(query) or {}).get('reason_code'), 'reception_lunch_break')
        # Without the confirmed value a bare «цайны цаг» is still not claimed; a free-text value is rejected.
        self.assertIsNone(ReceptionAnswerPath(_corrected(tables, {}), enabled=True).answer('Цайны цаг хэдэн цагт вэ?'))
        for bad in ('үдээс хойш', 1240, ['12:40–13:20']):
            with self.subTest(bad=bad), self.assertRaises(ReceptionDataError):
                _corrected(tables, {'lunch_break': bad})

    def test_an_offices_weekend_lunch_and_payment_hours_are_notes(self):
        # 11/23 (2): these reached the FAQ router's «…хадгалсан асуулт алга. Тааж нэгтгэхгүй.» Only the weekday hours
        # are confirmed; the reply says them and what is not known, with no answer.
        from reception_tables import _corrected
        tables = ReceptionTables(rooms=(Room(4, '406', services=(Service('Сургалтын алба', '08:00–17:00', ''),)),
                                        Room(8, '804', services=(Service('Санхүүгийн алба', '08:00–17:00', ''),)),
                                        Room(10, '1006', services=(Service('Номын сан', '', ''),))),
                                 staff=(), classes=(), timetable=())
        fixed = ReceptionAnswerPath(_corrected(tables, {'lunch_break': '12:40–13:20'}), enabled=True)
        for query, message in (
                ('Сургалтын алба бямба гарагт ажилладаг уу?', 'Сургалтын алба 08:00–17:00 цагийн хооронд ажилладаг '
                 '(4-р давхар, 406 тоот). Бямба, ням гарагийн ажлын цагийн мэдээлэл алга.'),
                ('Сургалтын алба ням гаригт хэдэн цагт ажилладаг вэ?', 'Сургалтын алба 08:00–17:00 цагийн хооронд ажилладаг '
                 '(4-р давхар, 406 тоот). Бямба, ням гарагийн ажлын цагийн мэдээлэл алга.'),
                ('Номын сан бямба гарагт ажилладаг уу?', 'Ажлын цагийн мэдээлэл алга.'),
                ('Сургалтын алба цайны цагаар ажилладаг уу?', 'Сургалтын алба 08:00–17:00 цагийн хооронд ажилладаг '
                 '(4-р давхар, 406 тоот). Сургуулийн цайны цаг 12:40–13:20. Цайны цагаар ажилладаг эсэх мэдээлэл алга.'),
                ('Санхүүгийн алба хэдэн цаг хүртэл төлбөр авдаг вэ?', 'Санхүүгийн алба 08:00–17:00 цагийн хооронд ажилладаг '
                 '(8-р давхар, 804 тоот). Төлбөр хүлээн авах цагийн тусгай мэдээлэл алга.')):
            with self.subTest(query=query):
                result = fixed.answer(query)
                self.assertIsNone(result['answer'])
                self.assertEqual(result['reason_code'], 'reception_office_note')
                self.assertEqual(result['message'], message)
                self.assertTrue(fixed.recognizes(query))
        # An unrecorded place is not claimed; the school's own weekend question keeps its answer.
        self.assertFalse(fixed.recognizes('Цайны газар бямба гарагт ажилладаг уу?'))
        self.assertIsNone(fixed.answer('Цайны газар бямба гарагт ажилладаг уу?'))

    def test_a_courses_day_reads_one_line_per_class(self):
        from datetime import datetime
        tables = ReceptionTables(rooms=(), staff=(), timetable_complete=True, classes=(
            ClassGroup(group='КУ-2', room='612', course='2'), ClassGroup(group='МИ-2', room='402', course='2')), timetable=(
            Lesson('mon', '08:00-09:30', 'КУ-2', '612', 'Б.Багш', 'Математик'),
            Lesson('mon', '09:35-11:05', 'КУ-2', '612', 'Б.Багш', 'Физик'),
            Lesson('mon', '08:00-09:30', 'МИ-2', '402', 'Б.Багш', 'Хими')))
        path = ReceptionAnswerPath(tables, enabled=True)
        result = path.answer('2-р курс өнөөдөр хэдэн цагт хичээлтэй вэ?', now=datetime(2026, 11, 23, 9, 0))
        self.assertEqual(result['answer'], '2026-11-23-ны хуваарь:\nКУ-2: 08:00-09:30, 09:35-11:05\nМИ-2: 08:00-09:30\n'
                                           'Яг одоо хаана байгааг мэдэх боломжгүй.')

    def test_a_post_named_as_a_room_gives_its_holders_room(self):
        # Round 5: «Захирлын өрөө хаана вэ?» answered «өрөө олдсонгүй».
        tables = ReceptionTables(rooms=(Room(5, '508'),),
            staff=(Staff(name='Т.Зохиомол', department='Захиргаа', room='508', role='Захирал'),
                   Staff(name='С.Туслах', department='Захиргаа', room='508', role='Захирлын туслах')),
            classes=(), timetable=())
        result = ReceptionAnswerPath(tables, enabled=True).answer('Захирлын өрөө хаана вэ?')
        self.assertEqual(result['reason_code'], 'reception_role_room')
        self.assertEqual(result['answer'], 'Захирал (Т.Зохиомол): 5-р давхар, 508 тоот. Яг одоо өрөөндөө байгаа эсэхийг мэдэх боломжгүй.')

    def test_department_contact_is_its_head_never_a_phone(self):
        # Round 4 (11/17): «Барилгын тэнхимийн утас хэд вэ?» showed another department's contact block.
        tables = ReceptionTables(
            rooms=(Room(3, '304'),),
            staff=(Staff(name='Б.Эрхлэгч', department='Барилга, дэд бүтцийн инженерийн тэнхим', room='304',
                         role='Барилга, дэд бүтцийн инженерийн тэнхимийн эрхлэгч', email='fake.head@nmct.edu.mn'),
                   Staff(name='А.Багш', department='Барилга, дэд бүтцийн инженерийн тэнхим',
                         role='Барилга, дэд бүтцийн инженерийн тэнхимийн багш')),
            classes=(), timetable=())
        path = ReceptionAnswerPath(tables, enabled=True)
        phone = path.answer('Барилгын тэнхимийн утас хэд вэ?')
        self.assertEqual(phone['reason_code'], 'reception_department_phone')
        self.assertTrue(phone['answer'].startswith('Тэнхимийн утасны дугаарыг энд өгдөггүй. Тэнхимийн эрхлэгч Б.Эрхлэгч'))
        self.assertIn('fake.head@nmct.edu.mn', phone['answer'])
        self.assertIn('304 тоот, 3-р давхар', path.answer('Барилгын тэнхимтэй яаж холбогдох вэ?')['answer'])
        self.assertFalse(path.recognizes('Химийн тэнхимийн утас хэд вэ?'))   # no recorded head: website path

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
                self.assertIn('утасны дугаарыг энд өгдөггүй', result['answer'])
                self.assertIn('fake.teacher@nmct.edu.mn', result['answer'])
        # An unrecorded teacher stays with the staff path (which says phones are not shown).
        self.assertFalse(self.path.recognizes('Х.Хүрэлбаатар багшийн утас?'))
        self.assertFalse(self.path.recognizes('ЗЗ-9 ангийн багшийн утас?'))

    def test_teacher_day_from_the_published_timetable(self):
        # 11/17 (5): busy/free and times only; never presence in the office.
        tables = ReceptionTables(
            rooms=(Room(6, '604'),), classes=(),
            staff=(Staff(name='А.Номин-Эрдэнэ', department='КУ', room='604', email='fake.teacher@nmct.edu.mn'),),
            timetable=(Lesson('mon', '09:35-11:05', 'КУ-5', '609', 'А.Номин-Эрдэнэ'),
                       Lesson('mon', '08:00-09:30', 'КУ-5', '602', 'А.Номин-Эрдэнэ')),
            timetable_complete=True, calendar_bound=True, term_start=date(2026, 9, 7), term_end=date(2026, 12, 25),
            holidays=(date(2026, 11, 26),), holidays_reviewed=True)
        path = ReceptionAnswerPath(tables, enabled=True)
        result = path.answer('А.Номин-Эрдэнэ багш даваа гарагт хичээлтэй юу?')
        self.assertEqual(result['reason_code'], 'reception_teacher_day')
        self.assertLess(result['answer'].index('08:00-09:30'), result['answer'].index('09:35-11:05'))
        self.assertIn('Яг одоо хаана байгааг мэдэх боломжгүй', result['answer'])
        self.assertNotIn('609', result['answer'])
        # Sunday 11/15 → tomorrow is Monday; Monday 11/16 → Tuesday has no lessons.
        tomorrow = path.answer('А.Номин-Эрдэнэ багш маргааш хичээлтэй юу?', now=datetime(2026, 11, 15, 9))
        self.assertIn('маргааш (даваа)', tomorrow['answer'])
        self.assertIn('08:00-09:30', tomorrow['answer'])
        free = path.answer('А.Номин-Эрдэнэ багш маргааш хичээлтэй юу?', now=datetime(2026, 11, 16, 9))
        self.assertIn('(сул)', free['answer'])
        holiday = path.answer('А.Номин-Эрдэнэ багш маргааш хичээлтэй юу?', now=datetime(2026, 11, 25, 9))
        self.assertEqual(holiday['reason_code'], 'reception_holiday')
        self.assertEqual(path.answer('А.Номин-Эрдэнэ багш маргааш хичээлтэй юу?')['reason_code'],
                         'reception_date_required')
        self.assertEqual(path.answer('Х.Хүрэлбаатар багш даваа гарагт хичээлтэй юу?')['reason_code'],
                         'reception_teacher_not_found')

    def test_lesson_times_from_the_whole_timetable(self):
        # 11/17 (5): the school day's lesson times, read from the timetable (usual double periods).
        times = ['08:00-09:30'] * 25 + ['09:35-11:05'] * 25 + ['13:20-14:05'] * 3
        tables = ReceptionTables(rooms=(), staff=(), classes=(), timetable=tuple(
            Lesson('mon', time, 'КУ-5', '602', 'А.Номин-Эрдэнэ') for time in times), timetable_complete=True)
        result = ReceptionAnswerPath(tables, enabled=True).answer('Хичээл хэдэн цагт эхэлдэг вэ?')
        self.assertEqual(result['reason_code'], 'reception_bell_schedule')
        self.assertIn('08:00-д эхэлж', result['answer'])
        self.assertIn('Ихэвчлэн: 08:00-09:30, 09:35-11:05.', result['answer'])

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
