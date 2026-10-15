"""Source-scope counterexamples; synthetic development checks, no model calls."""
import unittest

from source_fields import ambiguity, requested_detail, detail_supported, department_evidence_sources


def source(text, title='Карьерын төв'):
    return dict(text=text, title=title)


CAREER = source('''Сакүра Сайэнс: танилцах хөтөлбөр.
JICA дадлага хөтөлбөр: япон хэл дээр ярилцлага өгнө.
Япон коосэнд дэвшин суралцахад тавигдах шаардлагууд.
Япон хэлний N2 түвшний мэдлэг, чадвартай.
Ясуда ОУ-ын тэтгэлэг. Кисо Жибан Консалтантс тэтгэлэг.
Химийн инженерчлэлийн нэрэмжит тэтгэлэг.''')


class ScopeAmbiguityTests(unittest.TestCase):
    def test_department_head_needs_department_even_when_one_source_ranks_first(self):
        sources = [source('Тэнхимийн эрхлэгч Н.Нэр. Имэйл name@example.invalid.',
                          'Цахилгаан электроникийн инженерийн тэнхим')]
        result = ambiguity('Тэнхимийн эрхлэгчийн нэр, имэйлийг өгөөч.', sources)
        self.assertIsNotNone(result)
        self.assertIn('Аль тэнхим', result[0])
        self.assertIn('Цахилгаан', result[0])
        self.assertIsNone(ambiguity('Цахилгаан электроникийн тэнхимийн эрхлэгчийн имэйл юу вэ?', sources))

    def test_named_department_scope_can_come_from_its_source_text(self):
        sources = [source('Механик инженерийн тэнхим. Тэнхимийн эрхлэгчийн имэйл.', 'Тэнхимүүд')]
        self.assertIsNone(ambiguity('Механик инженерийн тэнхимийн эрхлэгчийн нэрийг өгөөч.', sources))

    def test_generic_japan_duration_and_language_need_pathway(self):
        for query in ['Япон руу явах хөтөлбөр хэд хоног үргэлжлэх вэ?',
                      'Япон руу явахад япон хэлний ямар шаардлага тавьдаг вэ?',
                      'Япон руу явахад япон хэлний N2 түвшин шаардлагатай юу?']:
            with self.subTest(query=query):
                result = ambiguity(query, [CAREER])
                self.assertIsNotNone(result)
                self.assertIn('аль зам', result[0])
                self.assertIn('дадлага', result[0])

    def test_named_or_explicit_japan_pathway_keeps_own_question(self):
        for query in ['JICA-ийн Японы дадлага хэд хоног үргэлжлэх вэ?',
                      'Сакүра Сайэнс Япон руу явах хөтөлбөр хэд хоног үргэлжлэх вэ?',
                      'Япон коосэнд дэвшин суралцахад хэлний ямар түвшин шаарддаг вэ?',
                      'Японд ажиллахад хэлний ямар шаардлага тавьдаг вэ?']:
            with self.subTest(query=query):
                self.assertIsNone(ambiguity(query, [CAREER]))

    def test_scholarship_year_does_not_identify_one_programme(self):
        result = ambiguity('2026 оны тэтгэлэгт хэддүгээр курсийнхэн хамрагдах боломжтой вэ?', [CAREER])
        self.assertIsNotNone(result)
        self.assertIn('Аль тэтгэлэг', result[0])

    def test_scholarship_literal_names_and_department_qualifier_are_not_generic(self):
        for query in ['2026 оны есдүгээр сарын Ясуда тэтгэлгийн мэдээнд сарын дүн, эхлэх хугацааг юу гэж зарласан бэ?',
                      'Ясудагийн сарын тэтгэлгийн хэмжээ хэд вэ?',
                      'Кисо Жибан тэтгэлэгт хэддүгээр курс хамрагдах вэ?',
                      'Химийн инженерчлэлийн тэтгэлэгт ямар курс хамрагдах вэ?']:
            with self.subTest(query=query):
                self.assertIsNone(ambiguity(query, [CAREER]))

    def test_new_literal_scholarship_name_needs_no_code_alias(self):
        sources = [source('Орион сангийн тэтгэлэгт 3-р курсийн оюутнууд хамрагдана.')]
        self.assertIsNone(ambiguity('Орион сангийн тэтгэлэгт хэн хамрагдах вэ?', sources))

    def test_explicit_overview_or_comparison_does_not_require_one_programme(self):
        for query in ['Тэтгэлэгт хөтөлбөрүүдийг танилцуулна уу?',
                      'Бүх тэтгэлгийн хамрагдах курсийн нөхцөлийг харьцуулна уу?',
                      'Япон руу явах хөтөлбөрүүдийн хугацааг харьцуулна уу?']:
            with self.subTest(query=query):
                self.assertIsNone(ambiguity(query, [CAREER]))


class RequestedScopeFieldTests(unittest.TestCase):
    def test_current_fx_cannot_be_established_by_dated_snapshot(self):
        query = 'Тэтгэлгийн иений дүн яг өнөөдрийн ханшаар хэдэн төгрөг болох вэ?'
        self.assertEqual(requested_detail(query), 'current_exchange_rate')
        for text in ['2026 оны 10 сарын 15. Өнөөдрийн ханш 1 иен = 24 төгрөг.',
                     'Сарын тэтгэлэг 100,000 иен буюу ойролцоогоор 2,400,000 төгрөг.']:
            self.assertFalse(detail_supported('current_exchange_rate', text))
        self.assertIsNone(requested_detail('2026 оны мэдээнд иенийг хэдэн төгрөгөөр ойролцоолсон бэ?'))

    def test_lab_hours_need_lab_day_and_clock_not_capacity_or_general_office_hours(self):
        query = 'CNC лаборатори долоо хоногийн ямар өдрүүдэд хэдээс хэд хүртэл нээлттэй вэ?'
        self.assertEqual(requested_detail(query), 'laboratory_opening_hours')
        for text in ['CNC лабораторид нэг удаа 15–20 оюутан ажиллах боломжтой.',
                     'Ажлын цаг Даваа - Баасан: 09:00 - 18:00.',
                     'CNC лабораторид 09:00 - 18:00 цагт 20 оюутан ажиллав.']:
            self.assertFalse(detail_supported('laboratory_opening_hours', text))
        self.assertTrue(detail_supported('laboratory_opening_hours',
            'CNC лаборатори Даваа - Баасан 09:00 - 18:00 нээлттэй.'))
        self.assertEqual(requested_detail('SQL хичээл долоо хоногт хэдэн цаг вэ?'), 'sql_weekly_hours')

    def test_appeal_deadline_is_distinct_from_disciplinary_counts(self):
        self.assertEqual(requested_detail('Огцруулах шийдвэрийг хэд хоногийн дотор давж заалдаж болох вэ?'), 'appeal_deadline')
        self.assertFalse(detail_supported('appeal_deadline',
            '5 удаа хоцорвол анхааруулна. 2 удаа сануулах хуудас авбал огцруулна.'))
        self.assertTrue(detail_supported('appeal_deadline',
            'Шийдвэрийг хүлээн авснаас хойш ажлын 7 хоногийн дотор давж заалдаж болно.'))
        self.assertFalse(detail_supported('appeal_deadline', 'Давж заалдаж болно. Дадлага 7 хоног үргэлжилнэ.'))
        self.assertIsNone(requested_detail('Хоцролт, таслалтад ямар арга хэмжээ авдаг вэ?'))

    def test_guaranteed_salary_requires_salary_amount_and_guarantee_same_clause(self):
        query = 'JICA-ийн 7–30 хоногийн дадлагад сард хэдэн иен цалин баталгаатай өгөх вэ?'
        self.assertEqual(requested_detail(query), 'guaranteed_salary')
        for text in ['Сарын тэтгэлэг 100,000 иен. Дадлага 7–30 хоног.',
                     'Цалин 100,000 иен авах боломжтой.',
                     'Цалин 100,000 иен авах нь баталгаатай биш.',
                     'Цалин баталгаатай. Сарын тэтгэлэг 100,000 иен.']:
            self.assertFalse(detail_supported('guaranteed_salary', text))
        self.assertTrue(detail_supported('guaranteed_salary', 'Сард 100,000 иен цалин баталгаатай олгоно.'))
        self.assertIsNone(requested_detail('JICA дадлагад ямар алхмаар хамрагдах вэ?'))


class DepartmentEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.chemical = dict(title='Химийн инженерийн тэнхим', url='https://example.invalid/chemical', text='Багшийн тухай.')
        self.same_page = dict(title='Сонгосон нэмэлт хэсэг', url=self.chemical['url'], text='Эрхлэгчийн холбоо.')
        self.same_title = dict(title=self.chemical['title'], url='https://example.invalid/chemical-archived', text='Багшийн бүрэлдэхүүн.')
        self.mechanical = dict(title='Механик инженерийн тэнхим', url='https://example.invalid/mechanical', text='Багшийн тухай.')
        self.sources = [self.chemical, self.same_page, self.mechanical, self.same_title]

    def test_named_staff_or_head_keeps_department_title_or_same_url_only(self):
        for query in ['Химийн инженерийн тэнхимийн үндсэн ба цагийн багшийн тоо хэд вэ?',
                      'Химийн инженерийн тэнхимийн эрхлэгчийн имэйл юу вэ?']:
            with self.subTest(query=query):
                self.assertEqual(department_evidence_sources(query, self.sources),
                                 [self.chemical, self.same_page, self.same_title])

    def test_generic_or_multiple_departments_are_unchanged(self):
        for query in ['Тэнхимийн багш хэд вэ?',
                      'Инженерийн тэнхимийн багш хэд вэ?',
                      'Химийн болон механикийн тэнхимийн багш хэд вэ?',
                      'Химийн болон бусад тэнхимийн багшийг харьцуулна уу?',
                      'Бүх тэнхимийн эрхлэгчийн нэрийг өгөөч.',
                      'Химийн тэнхим хэдэн лабораторитой вэ?']:
            with self.subTest(query=query):
                self.assertIs(department_evidence_sources(query, self.sources), self.sources)

    def test_title_must_match_all_named_words_not_one_generic_overlap(self):
        source = dict(title='Цахилгаан электроникийн инженерийн тэнхим', url='https://example.invalid/electrical', text='Багшийн тухай.')
        sources = [source, self.chemical]
        self.assertIs(department_evidence_sources('Цахилгаан инженерийн тэнхимийн багш хэд вэ?', sources), sources)
        self.assertEqual(department_evidence_sources('Цахилгаан электроникийн инженерийн тэнхимийн багш хэд вэ?', sources), [source])

    def test_body_url_and_other_metadata_do_not_identify_department(self):
        other = dict(title='Ерөнхий мэдээлэл', url=self.chemical['url'],
                     page_header=self.chemical['title'], text=self.chemical['title']+' багшийн тухай.')
        sources = [other, self.mechanical]
        self.assertIs(department_evidence_sources('Химийн инженерийн тэнхимийн багш хэд вэ?', sources), sources)

    def test_unknown_name_and_ambiguous_matching_titles_are_unchanged(self):
        self.assertIs(department_evidence_sources('Шинэ нэртэй тэнхимийн багш хэд вэ?', self.sources), self.sources)
        another = dict(self.chemical, title='Химийн инженерчлэлийн тэнхим', url='https://example.invalid/second')
        sources = [self.chemical, another]
        self.assertIs(department_evidence_sources('Химийн инженерийн тэнхимийн багш хэд вэ?', sources), sources)


if __name__ == '__main__':
    unittest.main()
