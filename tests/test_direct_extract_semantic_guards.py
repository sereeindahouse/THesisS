"""Source-context regressions for the two closed direct-extract grammars.

All values, places and contacts below are constructed fixtures. These tests
check bounded guards and exact copying, not empirical school-answer accuracy.
"""
import unittest

from rag_runtime import school_contact_extract, sports_area_extract


CONTACT_QUERY = 'Бямба гарагт хэдээс хэд хүртэл ажилладаг вэ, бас ерөнхий утсаа хэлээд өгөөч.'
SPORTS_QUERY = 'Спортын хоёр заал нь нийлээд ямар талбайтай вэ? Бүжгийн танхимыг битгий нэмээрэй.'
CONTACT_TEXT = (
    'Хаяг мэдээлэл\nХаяг\nТуршилтын хот, Жишээ гудамж\n'
    'Утас\n+976 22334455\nИмэйл\nfixture@nmct.edu.mn\nАжлын цаг\n'
    'Даваа - Баасан: 08:15 - 17:45\nБямба: 07:15 - 12:45\nНям: Амарна\n'
    'Мэдэгдэл илгээх\nНэр *'
)
SPORTS_TEXT = (
    'Туршилтын ЕБС-ийн дундын ашиглалтын 2 спорт заал (784.3 м²) болон '
    '155 м² бүжгийн танхимд биеийн тамирын хичээл, дугуйлан секц, тэмцээн зохион байгуулдаг.'
)


def contact(text=CONTACT_TEXT, **extra):
    return dict(source_id='synthetic-contact', url='https://nmct.edu.mn/contact',
                text=text, version=1, **extra)


def sports(text=SPORTS_TEXT, **extra):
    return dict(source_id='synthetic-sports', url='https://nmct.edu.mn/about/environment',
                text=text, version=1, **extra)


class DirectExtractContextGuardsTests(unittest.TestCase):
    def test_contact_copies_dynamic_values_and_one_original_span(self):
        source = contact()
        selected = school_contact_extract(CONTACT_QUERY, [source])
        self.assertIsNotNone(selected)
        self.assertIs(selected[0], source)
        self.assertIn(selected[1], CONTACT_TEXT)
        self.assertIn('+976 22334455', selected[1])
        self.assertIn('Бямба: 07:15 - 12:45', selected[1])
        self.assertNotIn('Мэдэгдэл илгээх', selected[1])

    def test_contact_owner_before_phone_cannot_be_discarded(self):
        for heading in ('Зөвхөн Химийн тэнхимийн холбоо барих мэдээлэл',
                        'Захирлын хүлээн авах цаг ба ажлын утас'):
            with self.subTest(heading=heading):
                self.assertIsNone(school_contact_extract(
                    CONTACT_QUERY, [contact(heading + '\n' + CONTACT_TEXT)]))

    def test_contact_historical_or_conditional_context_before_phone_is_not_lost(self):
        for heading in ('2019 оны хуучин хуваарь', 'Зөвхөн шалгалттай өдөр мөрдөнө',
                        'Баталгаажаагүй төлөвлөгөө'):
            with self.subTest(heading=heading):
                self.assertIsNone(school_contact_extract(
                    CONTACT_QUERY, [contact(heading + '\n' + CONTACT_TEXT)]))

    def test_contact_correction_or_condition_after_hours_is_not_lost(self):
        for note in ('Дээрх Бямба гарагийн цаг зөвхөн шалгалттай өдөр хүчинтэй.',
                     'Энэ мэдээлэл хүчингүй болсон тул хэрэглэхгүй.',
                     'Баярын өдөр Бямба гарагт ажиллахгүй.'):
            with self.subTest(note=note):
                self.assertIsNone(school_contact_extract(
                    CONTACT_QUERY, [contact(CONTACT_TEXT + '\n' + note)]))

    def test_contact_second_day_row_cannot_be_ignored_for_different_spelling_or_invalid_time(self):
        for row in ('Бямба гараг: 12:00 - 16:00',
                    '  Бямба гараг: 12:00 - 16:00',
                    'Бямба: 12:00 - 16:00 хэрэв хичээлтэй бол',
                    'Бямба: 99:00 - 16:00',
                    'Баасан - Ням: 99:00 - 16:00'):
            with self.subTest(row=row):
                self.assertIsNone(school_contact_extract(
                    CONTACT_QUERY, [contact(CONTACT_TEXT + '\n' + row)]))

    def test_contact_conflicting_source_with_other_syntax_is_not_silently_ignored(self):
        other = contact('Ерөнхий утас +976 66554433. Бямба гарагийн цаг 12:00–16:00.')
        other['source_id'] = 'synthetic-other-contact'
        self.assertIsNone(school_contact_extract(CONTACT_QUERY, [contact(), other]))

    def test_conditional_contact_quote_is_not_misreported_as_silent_context_loss(self):
        # An earlier review expected strict rejection. If a future implementation
        # supports conditional direct answers, the condition must remain visible;
        # acceptance alone would not demonstrate that the context was discarded.
        condition = 'Хэрэв шалгалттай бол дараах цаг мөрдөнө'
        text = CONTACT_TEXT.replace('Ажлын цаг', condition + '\nАжлын цаг')
        selected = school_contact_extract(CONTACT_QUERY, [contact(text)])
        if selected is not None:
            self.assertIn(condition, selected[1])

    def test_sports_copies_the_measurement_with_owner_without_dance_sum(self):
        text = SPORTS_TEXT + '\n939.3\nм² нийт талбай'
        source = sports(text)
        selected = sports_area_extract(SPORTS_QUERY, [source])
        self.assertIsNotNone(selected)
        self.assertIs(selected[0], source)
        self.assertIn(selected[1], text)
        self.assertEqual(selected[1],
                         'Туршилтын ЕБС-ийн дундын ашиглалтын 2 спорт заал (784.3 м²)')
        self.assertNotIn('155', selected[1])
        self.assertNotIn('939.3', selected[1])

    def test_sports_prior_line_negation_condition_or_past_context_is_not_lost(self):
        for heading in ('Дараах мэдээлэл үнэн биш:', '2019 оны хуучин барилгын тайлбар:',
                        '2019 оны байдлаар:',
                        'Хэрэв зөвшөөрөл олгогдвол:', 'Ирэх жил барихаар хэлэлцэж буй төсөл:'):
            with self.subTest(heading=heading):
                self.assertIsNone(sports_area_extract(
                    SPORTS_QUERY, [sports(heading + '\n' + SPORTS_TEXT)]))

    def test_sports_predicate_after_the_measurement_can_deny_or_limit_it(self):
        prefix = SPORTS_TEXT.split('155 м² бүжгийн танхим')[0] + '155 м² бүжгийн танхим'
        for predicate in ('тай байв.',
                          'тай байсан ч эдгээрийг ашиглахаа больсон.',
                          'тай гэж үзэх үндэслэл алга.',
                          'ын зураг төслийг ирэх онд хэрэгжүүлэх саналыг хэлэлцэв.',
                          'ын мэдээлэл одоо хүчингүй болсон.'):
            with self.subTest(predicate=predicate):
                self.assertIsNone(sports_area_extract(
                    SPORTS_QUERY, [sports(prefix + predicate)]))

    def test_sports_per_hall_qualification_after_the_sentence_cannot_answer_total(self):
        for qualification in ('Дээрх 784.3 м² нь заал тус бүрийн талбай юм.',
                              '784.3 м² нь нэг заалны талбай бөгөөд нийт талбайг илэрхийлэхгүй.'):
            with self.subTest(qualification=qualification):
                self.assertIsNone(sports_area_extract(
                    SPORTS_QUERY, [sports(SPORTS_TEXT + '\n' + qualification)]))

    def test_sports_conflicting_total_in_different_syntax_is_not_ignored(self):
        other = sports('Спортын хоёр заалны нийт талбай 900 м².')
        other['source_id'] = 'synthetic-other-sports'
        self.assertIsNone(sports_area_extract(SPORTS_QUERY, [sports(), other]))

    def test_extra_query_requirements_cannot_be_discarded(self):
        for prefix, suffix in [('2031 онд ', ''), ('Өнөөдөр ', ''),
                               ('Химийн тэнхимийн ', ''), ('', ' Зуны төлбөр хэд вэ?')]:
            with self.subTest(prefix=prefix, suffix=suffix):
                self.assertIsNone(school_contact_extract(
                    prefix + CONTACT_QUERY + suffix, [contact()]))
                self.assertIsNone(sports_area_extract(
                    prefix + SPORTS_QUERY + suffix, [sports()]))


if __name__ == '__main__':
    unittest.main()
