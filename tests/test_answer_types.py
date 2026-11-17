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
        director = path.answer('Сургуулийн захирал хэн бэ?')
        self.assertEqual(director['reason_code'], 'reception_role_holder')
        self.assertEqual(director['answer'], 'Т.Зохиомол — Захирал. Ажлын өрөө: 508, 5-р давхар. '
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
        self.assertIn('өрөөндөө байгааг батлахгүй', meet['answer'])
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
        self.assertEqual(path.answer('Хурлын заал хэддүгээр давхарт байдаг вэ?')['answer'], 'Хурлын заал: 809 өрөө, 8-р давхар.')
        self.assertEqual(path.answer('Компьютерын лаборатори хаана вэ?')['answer'],
                         'Компьютерын лаборатори: 410 өрөө, 4-р давхар; 613 өрөө, 6-р давхар.')
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
        self.assertEqual(path.answer('номын сан хаана байдаг')['answer'], 'Номын сан: 1006 өрөө, 10-р давхар.')
        self.assertEqual(path.answer('хурлын заал хэд давхарт')['answer'], 'Хурлын заал: 809 өрөө, 8-р давхар.')
        self.assertEqual(path.answer('компьютерын лаб хаана')['answer'], 'Компьютерын лаборатори: 410 өрөө, 4-р давхар.')
        self.assertEqual(path.answer('эмч байдаг уу')['answer'], 'Тийм. Эмч: 607 өрөө, 6-р давхар.')
        self.assertFalse(path.recognizes('Дотуур байр байдаг уу?'))
        self.assertFalse(path.recognizes('Эмч байгаа юу?'))   # whether someone is there now
        tomorrow = path.answer('КУ-2 анги маргааш хэдэн цагт хичээлтэй вэ', now=datetime(2026, 11, 18, 10, 0))
        self.assertEqual(tomorrow['reason_code'], 'reception_class_day')
        self.assertIn('маргаашийн (пүрэв гараг)', tomorrow['answer'])
        self.assertIn('08:00-09:30', tomorrow['answer'])

    def test_a_post_named_as_a_room_gives_its_holders_room(self):
        # Round 5: «Захирлын өрөө хаана вэ?» answered «өрөө олдсонгүй».
        tables = ReceptionTables(rooms=(Room(5, '508'),),
            staff=(Staff(name='Т.Зохиомол', department='Захиргаа', room='508', role='Захирал'),
                   Staff(name='С.Туслах', department='Захиргаа', room='508', role='Захирлын туслах')),
            classes=(), timetable=())
        result = ReceptionAnswerPath(tables, enabled=True).answer('Захирлын өрөө хаана вэ?')
        self.assertEqual(result['reason_code'], 'reception_role_room')
        self.assertEqual(result['answer'], 'Захирал (Т.Зохиомол): 508 өрөө, 5-р давхар.')

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
        self.assertTrue(phone['answer'].startswith('Тэнхимийн утасны дугаарыг энд харуулахгүй. Тэнхимийн эрхлэгч Б.Эрхлэгч'))
        self.assertIn('fake.head@nmct.edu.mn', phone['answer'])
        self.assertIn('304, 3-р давхар', path.answer('Барилгын тэнхимтэй яаж холбогдох вэ?')['answer'])
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
                self.assertIn('утасны дугаарыг энд харуулахгүй', result['answer'])
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
        self.assertIn('өрөөндөө байгааг батлахгүй', result['answer'])
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
