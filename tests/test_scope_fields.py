"""Source-scope counterexamples; synthetic development checks, no model calls."""
import unittest

from source_fields import (ambiguity, requested_detail, detail_supported, department_evidence_sources,
                           field_evidence_requirements, missing_field_evidence)


class SeparateHistoricalYearFieldsTests(unittest.TestCase):
    def test_news_host_cannot_be_replaced_with_extra_activities(self):
        fields = field_evidence_requirements('«Аврора» хөтөлбөр хаана болсон, хичээлээс гадна юу хийсэн гэж мэдээнд бичсэн бэ?')
        activities = 'Оролцогчид компани, байгууллагын ажил, соёлтой танилцсан.'
        host = 'Гадаад улсын Өрнөд хотын инженерийн коллежид амжилттай зохион байгуулагдлаа.'
        self.assertIn('news_activity_location', missing_field_evidence(fields, [activities]))
        self.assertEqual(missing_field_evidence(fields, [activities, host]), [])

    def test_selection_must_cover_each_separately_asked_year(self):
        fields = field_evidence_requirements('2018 онд юу нээсэн, 2022 онд ямар систем нэвтрүүлсэн бэ?')
        self.assertEqual([f['name'] for f in fields], ['explicit_year_2018', 'explicit_year_2022'])
        self.assertEqual(missing_field_evidence(fields, ['2022 онд цахим систем нэвтрүүлэв.']), ['explicit_year_2018'])
        self.assertEqual(missing_field_evidence(fields, ['2018 онд лаборатори нээгдэв.', '2022 онд цахим систем нэвтрүүлэв.']), [])

    def test_academic_interval_does_not_become_separate_year_fields(self):
        self.assertEqual(field_evidence_requirements('2022–2023 оны хичээлийн жилийн төлбөр болон хураамж хэд вэ?'), [])


class PairedPracticeListFieldsTests(unittest.TestCase):
    query = 'Барилгын танилцах дадлагын байгууллагуудыг үйлдвэрлэлийн дадлагын байгууллагуудаас ялгаж жагсаана уу.'

    def test_each_explicitly_requested_category_needs_its_own_list(self):
        fields = field_evidence_requirements(self.query)
        partial = 'Үйлдвэрлэлийн дадлага хийх байгууллагууд:\n• Orion ХХК\n• DELTA LLC'
        self.assertEqual(missing_field_evidence(fields, partial), ['practice_introductory_organisations'])
        both = partial + '\nТанилцах дадлага:\n• Cedar ХХК\n• SUMMIT LTD.'
        self.assertEqual(missing_field_evidence(fields, both), [])

    def test_two_labels_without_actual_rows_do_not_pass(self):
        fields = field_evidence_requirements(self.query)
        self.assertEqual(len(missing_field_evidence(fields,
            'Үйлдвэрлэлийн дадлага болон танилцах дадлагын талаар дараа мэдээлнэ.')), 2)

    def test_one_combined_list_cannot_invent_the_mapping_between_categories(self):
        fields = field_evidence_requirements(self.query)
        text = 'Үйлдвэрлэлийн дадлага болон танилцах дадлага:\n• Orion ХХК\n• Cedar ХХК'
        self.assertEqual(len(missing_field_evidence(fields, text)), 2)

    def test_unrelated_following_section_cannot_supply_the_list(self):
        fields = field_evidence_requirements(self.query)
        text = 'Үйлдвэрлэлийн дадлага:\nМэдээлэл дараа гарна.\nТанилцах дадлага:\n• Cedar ХХК'
        self.assertEqual(missing_field_evidence(fields, text), ['practice_industrial_organisations'])

    def test_source_negation_is_not_a_positive_list(self):
        fields = field_evidence_requirements(self.query)
        text = 'Үйлдвэрлэлийн дадлага:\n• Orion ХХК\nТанилцах дадлага хийхгүй байгууллагууд:\n• Cedar ХХК'
        self.assertEqual(missing_field_evidence(fields, text), ['practice_introductory_organisations'])

    def test_past_and_habitual_negative_practice_headers_still_fail(self):
        fields = field_evidence_requirements(self.query)
        for negative in ('хийгдээгүй', 'явуулдаггүй', 'явагдаагүй', 'хамрагддаггүй'):
            text = 'Үйлдвэрлэлийн дадлага:\n• Orion ХХК\nТанилцах дадлага ' + negative + ' байгууллагууд:\n• Cedar ХХК'
            with self.subTest(negative=negative):
                self.assertEqual(missing_field_evidence(fields, text), ['practice_introductory_organisations'])

    def test_safe_is_positive_and_does_not_become_a_negation_suffix_rule(self):
        fields = field_evidence_requirements(self.query)
        text = 'Аюулгүй үйлдвэрлэлийн дадлагын байгууллагууд:\n• Orion ХХК\nАюулгүй танилцах дадлагын байгууллагууд:\n• Cedar ХХК'
        self.assertEqual(missing_field_evidence(fields, text), [])

    def test_numbered_lists_and_separate_units_keep_each_category(self):
        fields = field_evidence_requirements(self.query)
        self.assertEqual(missing_field_evidence(fields, [
            'Үйлдвэрлэлийн дадлагын байгууллагууд:\n1. Orion ХХК',
            'Танилцах дадлага:\n\n1) Cedar ХХК']), [])

    def test_unasked_or_negated_category_is_not_added(self):
        for query in ['Үйлдвэрлэлийн дадлагын байгууллагуудыг жагсаа.',
                      'Танилцах дадлагыг хасаж, зөвхөн үйлдвэрлэлийн дадлагын байгууллагуудыг хэлнэ үү.',
                      'Үйлдвэрлэлийн сургалт болон танилцах аяллын байгууллагуудыг жагсаана уу.']:
            self.assertFalse(any(field['type']=='labelled_list' for field in field_evidence_requirements(query)))


def source(text, title='Карьерын төв'):
    return dict(text=text, title=title)


CAREER = source('''Сакүра Сайэнс: танилцах хөтөлбөр.
JICA дадлага хөтөлбөр: япон хэл дээр ярилцлага өгнө.
Япон коосэнд дэвшин суралцахад тавигдах шаардлагууд.
Япон хэлний N2 түвшний мэдлэг, чадвартай.
Ясуда ОУ-ын тэтгэлэг. Кисо Жибан Консалтантс тэтгэлэг.
Химийн инженерчлэлийн нэрэмжит тэтгэлэг.''')


class ScopeAmbiguityTests(unittest.TestCase):
    def test_award_eligibility_is_not_unnamed_final_competition_result(self):
        self.assertIsNone(ambiguity('Физикийн олимпиадын хоёрдугаар байрт хэд вэ?',[]))
        self.assertIsNotNone(ambiguity('Манай оюутан тэмцээнд хэддүгээр байр эзэлсэн бэ?',[]))

    def test_repeated_programme_meetings_need_event_not_arbitrary_city(self):
        sources=[dict(text='Уулзалт болсон.',title='Өрнөл хөтөлбөр #1',url='https://example.invalid/news/a'),
                 dict(text='Уулзалт болсон.',title='Өрнөл хөтөлбөр #2',url='https://example.invalid/news/b')]
        query='Өрнөл хөтөлбөрийн уулзалт аль хотод болсон бэ?'
        self.assertIn('огноо',ambiguity(query,sources)[0])
        self.assertIsNone(ambiguity(query,[sources[0],sources[0]]))
        self.assertIsNone(ambiguity('Өрнөл хөтөлбөрийн уулзалтуудыг хот тус бүрээр харьцуул.',sources))
        self.assertIsNone(ambiguity('Өрнөл хөтөлбөр #2 уулзалт аль хотод болсон бэ?',sources))

    def test_placement_result_purpose_does_not_become_admission_result(self):
        sources=[source('Түвшин тогтоох шалгалт. Бичгийн шалгалт болон ярилцлагын шалгалт.')]
        self.assertIsNone(ambiguity('Түвшин тогтоох шалгалтын математик, физикийн дүнг юунд ашигладаг вэ?',sources))
        generic=ambiguity('Шалгалтын дүн хаана гарах вэ?',sources)
        self.assertIsNotNone(generic)
        self.assertIn('Элсэлтийн',generic[0])

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



class FacilityAndDecisionScopeTests(unittest.TestCase):
    def setUp(self):
        self.environment = [source('''Сургалтын анги танхимууд
18 анги танхим
540 суудал
Лекцийн танхим
2 том танхим
210 суудал
Спорт заал
360 м² бүжгийн танхимд биеийн тамирын хичээл орно.
Нийтийн хоолны газар
400 м² үйлчилгээний танхим
360
хүний суудал''', 'Сургалтын орчин')]

    def test_generic_seat_count_requires_observed_multiple_room_types(self):
        self.assertIn('Аль танхим', ambiguity('Сургуулийн танхим хэдэн суудалтай вэ?', self.environment)[0])
        self.assertIsNone(ambiguity('Танхимын багтаамж хэдэн хүн бэ?', [source('Лекцийн танхим 210 суудалтай.')]))
        self.assertIsNone(ambiguity('Танхим хэдэн суудалтай вэ?', [source('Танхим 210 суудалтай.')]))

    def test_named_room_or_explicit_comparison_is_not_generic(self):
        for query in ['Лекцийн танхим хэдэн суудалтай вэ?',
                      'Нийтийн хоолны танхимын багтаамж хэд вэ?',
                      'Спортын танхим хэдэн хүн багтаах вэ?',
                      'Сургалтын анги танхим хэдэн суудалтай вэ?',
                      'Танхимын төрөл бүрийн суудлыг харьцуулна уу?']:
            with self.subTest(query=query):
                self.assertIsNone(ambiguity(query, self.environment))

    def test_repeated_bare_number_with_different_units_needs_clarification(self):
        result = ambiguity('Сургалтын орчны хуудсан дахь 360 гэсэн үзүүлэлт нь юуны хэмжээ вэ?', self.environment)
        self.assertIn('нэгж', result[0])
        other = [source('Номын сан 720 номтой. Танхим 720 суудалтай.')]
        self.assertIsNotNone(ambiguity('720 гэсэн тоо юуг хэлж байна вэ?', other))
        self.assertIsNotNone(ambiguity('128 гэсэн тоо юуг хэлж байна вэ?', [source('Лекцийн танхим 128 суудалтай. Нийтийн хоолны газар 128 суудалтай.')]))
        self.assertIsNone(ambiguity('Сургалтын орчны 360 м² нь юуны хэмжээ вэ?', self.environment))
        self.assertIsNone(ambiguity('Хоолны танхимын 360 гэсэн тоо юуг хэлж байна вэ?', self.environment))
        self.assertIsNone(ambiguity('Нийтийн хоолны газрын 360 гэсэн тоо юуг хэлж байна вэ?', self.environment))

    def test_repeated_identical_measurements_and_number_substrings_are_not_ambiguous(self):
        for text in ['360 м² талбай. Дахин дурдвал 360 м².',
                     '360 м² талбай. 1360 суудалтай.',
                     '360 м² талбай. 360.5 суудал гэж буруу бичжээ.']:
            with self.subTest(text=text):
                self.assertIsNone(ambiguity('360 гэсэн тоо юуг хэлж байна вэ?', [source(text)]))

    def test_truncated_duplicate_without_object_is_not_a_distinct_measurement(self):
        sources = [source('Бүжгийн танхим 360 м² талбайтай.'),
                   source('360 м² талбайтай.')]
        self.assertIsNone(ambiguity('360 гэсэн үзүүлэлт нь юуны хэмжээ вэ?', sources))
        # A genuinely different, explicitly named object still requires scope.
        sources.append(source('Нийтийн хоолны газар 360 м² талбайтай.'))
        self.assertIsNotNone(ambiguity('360 гэсэн үзүүлэлт нь юуны хэмжээ вэ?', sources))

    def test_current_menu_is_not_a_monthly_approval_policy_or_old_snapshot(self):
        for query in ['Нийтийн хоолны газрын өнөөдрийн баталсан хоолны цэс болон үнэ хэд вэ?',
                      'Цайны газрын одоогийн цэс юу байна вэ?']:
            with self.subTest(query=query):
                self.assertEqual(requested_detail(query), 'current_cafeteria_menu')
        for text in ['Хоолны цэсийг сар бүр батлуулна. 360 суудалтай.',
                     'Өнөөдрийн хоолны цэс: шөл 10,000 төгрөг.']:
            self.assertFalse(detail_supported('current_cafeteria_menu', text))
        self.assertIsNone(requested_detail('Нийтийн хоолны газрын цэсийг хэр ойрхон баталдаг вэ?'))
        self.assertIsNone(requested_detail('Нийтийн хоолны газар өнөөдөр хэдэн суудалтай вэ?'))

    def test_accreditation_decision_requires_completed_decision_and_full_date(self):
        query = '2026 оны байгууллагын дахин магадлан итгэмжлэлийн эцсийн шийдвэр яг хэдэн сарын хэдний өдөр гарсан бэ?'
        self.assertEqual(requested_detail(query), 'accreditation_final_decision_date')
        for text in ['2026\nМагадлан итгэмжлэгдсэн байгууллага\nБайгууллагын магадлан итгэмжлэлд дахин орж байна.',
                     '2026 оны 9 сарын 12\nМагадлан итгэмжлэлийн эцсийн шийдвэр гарсан.',
                     'Магадлан итгэмжлэлийн эцсийн шийдвэр гарсан. Тэмцээн 2026.09.12-нд боллоо.',
                     'Магадлан итгэмжлэлийн эцсийн шийдвэр 2026 оны 9 сарын 12-нд гарах төлөвтэй.',
                     'Магадлан итгэмжлэлийн эцсийн шийдвэр гарсан тухай мэдээг 2026.09.12-нд нийтэлсэн.']:
            with self.subTest(text=text):
                self.assertFalse(detail_supported('accreditation_final_decision_date', text))
        for text in ['Магадлан итгэмжлэлийн эцсийн шийдвэр 2026 оны 9 сарын 12-ны өдөр гарсан.',
                     'Магадлан итгэмжлэлийн эцсийн шийдвэрийг 2026.09.12-нд баталсан тул гаргасан.']:
            with self.subTest(text=text):
                self.assertTrue(detail_supported('accreditation_final_decision_date', text))
        self.assertIsNone(requested_detail('Магадлан итгэмжлэлд орж байгаа юу?'))

    def test_decision_date_cannot_be_borrowed_from_another_same_sentence_event(self):
        for text in [
            'Магадлан итгэмжлэлийн эцсийн шийдвэр гарсан бөгөөд зөвлөл 2028.04.17-нд хуралдсан.',
            'Магадлан итгэмжлэлийн эцсийн шийдвэр 2028.04.17-ны хурлын дараа гарсан.',
            '2028.04.17-нд зөвлөл хуралдаж магадлан итгэмжлэлийн эцсийн шийдвэр гарсан.',
            'Магадлан итгэмжлэлийн эцсийн шийдвэр гарсан; хурал 2028.04.17-нд боллоо.',
            'Магадлан итгэмжлэлийн эцсийн шийдвэрийн талаар 2028.04.17-нд хуралдсан тул гаргасан.',
        ]:
            with self.subTest(text=text):
                self.assertFalse(detail_supported('accreditation_final_decision_date', text))

    def test_completed_decision_date_is_not_negated_hedged_or_merely_proposed(self):
        for text in [
            'Магадлан итгэмжлэлийн эцсийн шийдвэр 2028.04.17-нд батлагдаагүй.',
            'Магадлан итгэмжлэлийн эцсийн шийдвэр 2028.04.17-нд гарсан биш.',
            'Магадлан итгэмжлэлийн эцсийн шийдвэр 2028.04.17-нд гарсан эсэх тодорхойгүй.',
            'Магадлан итгэмжлэлийн эцсийн шийдвэр 2028.04.17-нд гарсан гэж хэлж болохгүй.',
            'Магадлан итгэмжлэлийн эцсийн шийдвэр 2028.04.17-нд баталсангүй.',
            'Магадлан итгэмжлэлийн эцсийн шийдвэр 2028.04.17-нд гарсан байж болзошгүй.',
            'Магадлан итгэмжлэлийн эцсийн шийдвэр 2028.04.17-нд гарсан тухай мэдээлэл байхгүй.',
            'Магадлан итгэмжлэлийн эцсийн шийдвэр 2028.04.17-нд гарсан бол мэдэгдэнэ.',
        ]:
            with self.subTest(text=text):
                self.assertFalse(detail_supported('accreditation_final_decision_date', text))

    def test_decision_date_respects_requested_object_renewal_and_year(self):
        field = 'accreditation_final_decision_date'
        query = '2028 оны байгууллагын дахин магадлан итгэмжлэлийн эцсийн шийдвэр хэзээ гарсан бэ?'
        for text in [
            'Хөтөлбөрийн дахин магадлан итгэмжлэлийн эцсийн шийдвэр 2028.04.17-нд гарсан.',
            'Байгууллагын магадлан итгэмжлэлийн эцсийн шийдвэр 2028.04.17-нд гарсан.',
            'Байгууллагын дахин магадлан итгэмжлэлийн эцсийн шийдвэр 2027.04.17-нд гарсан.',
            'Байгууллагын хуралд хөтөлбөрийн дахин магадлан итгэмжлэлийн эцсийн шийдвэр 2028.04.17-нд гарсан гэв.',
        ]:
            with self.subTest(text=text):
                self.assertFalse(detail_supported(field, text, query=query))
        for text in [
            'Байгууллагын дахин магадлан итгэмжлэлийн эцсийн шийдвэр 2028.04.17-нд гарсан.',
            '2028 оны дөрөвдүгээр сарын 17-ны өдөр байгууллагын дахин магадлан итгэмжлэлийн эцсийн шийдвэр батлагдсан.',
            'Байгууллагын дахин магадлан итгэмжлэлийн эцсийн шийдвэр гарсан огноо: 2028-04-17.',
        ]:
            with self.subTest(text=text):
                self.assertTrue(detail_supported(field, text, query=query))


class ExplicitFieldEvidenceTests(unittest.TestCase):
    def test_library_total_and_named_software_year_are_separate_requested_facets(self):
        query = 'Номын сангийн номын тоо болон LumaShelf программыг ашиглаж эхэлсэн оныг хэлнэ үү.'
        requirements = field_evidence_requirements(query)
        self.assertEqual([item['name'] for item in requirements], ['library_stock_total', 'library_software_start_year'])
        software = 'LumaShelf олон улсын программыг 2009 оноос нэвтрүүлэн ашиглаж байна. Нэг оюутанд 4.1–8.3 ном ногдож байна.'
        self.assertEqual(missing_field_evidence(requirements, software), ['library_stock_total'])
        self.assertEqual(missing_field_evidence(requirements, software + '\n1800+\nном, сурах бичиг'), [])
        self.assertEqual(missing_field_evidence(requirements, [software, '1,800 ном']), [])
        other = 'БусадПрограм программыг 2009 оноос нэвтрүүлэн ашиглаж байна.\n1800 ном'
        self.assertEqual(missing_field_evidence(requirements, other), ['library_software_start_year'])

    def test_library_stock_cannot_be_a_decimal_range_or_integer_per_student_ratio(self):
        requirements = field_evidence_requirements('Номын сангийн нийт номын тоо болон LumaShelf программыг ашиглаж эхэлсэн он хэд вэ?')
        stock = [item for item in requirements if item['name'] == 'library_stock_total']
        for text in ['Нэг оюутанд 4.1–8.3 ном ногдож байна.',
                     'Нэг оюутанд 7 ном ногдоно.', 'Нэг оюутанд\n7\nном',
                     '4.1 ном', '8–13 ном', 'Программыг 2009 оноос ашиглаж байна.']:
            with self.subTest(text=text):
                self.assertEqual(missing_field_evidence(stock, text), ['library_stock_total'])
        self.assertEqual(missing_field_evidence(stock, 'Нэг оюутанд 7 ном ногдоно.\n1800+\nном'), [])

    def test_library_software_year_requires_local_named_programme_and_start_use_predicate(self):
        requirements = field_evidence_requirements('Номын сангийн нийт номын тоо болон LumaShelf программыг ашиглаж эхэлсэн он хэд вэ?')
        year = [item for item in requirements if item['type'] == 'software_start_year']
        for text in ['LumaShelf програм. 2009 онд ашиглаж эхэлсэн.',
                     'LumaShelf программын тухай мэдээ 2009 онд нийтлэгдсэн.',
                     'LumaShelf, өөрөөр хэлбэл OpenShelf программыг 2009 оноос ашиглаж байна.',
                     'OpenShelf программыг 2009 оноос ашиглаж байна.',
                     'LumaShelf программыг 2009 онд ашиглаж эхлэхээр төлөвлөсөн.']:
            with self.subTest(text=text):
                self.assertEqual(missing_field_evidence(year, text), ['library_software_start_year'])
        self.assertEqual(missing_field_evidence(year, 'LumaShelf программыг 2009 онд ашиглаж эхэлсэн.'), [])

    def test_library_per_student_ratio_is_required_only_when_explicitly_requested(self):
        query = 'Номын сангийн нийт номын үзүүлэлт, нэг оюутанд ногдох номын хүрээ, LumaShelf ашиглаж эхэлсэн оныг хэл.'
        requirements = field_evidence_requirements(query)
        self.assertEqual([item['name'] for item in requirements],
                         ['library_stock_total', 'library_software_start_year', 'library_per_student_ratio'])
        text = 'LumaShelf программыг 2009 оноос нэвтрүүлэн ашиглаж байна.\n1800 ном'
        self.assertEqual(missing_field_evidence(requirements, text), ['library_per_student_ratio'])
        self.assertEqual(missing_field_evidence(requirements, text + '\nНэг оюутанд 4.1–8.3 ном ногдоно.'), [])
        only_ratio = field_evidence_requirements('Номын сангийн нэг оюутанд ногдох номын тоо болон LumaShelf программыг ашиглаж эхэлсэн оныг хэл.')
        self.assertEqual([item['name'] for item in only_ratio], ['library_software_start_year', 'library_per_student_ratio'])

    def test_library_unknown_source_derived_programme_name_needs_explicit_full_query_confirmation(self):
        sources = [source('Номын сан\nLumaShelf олон улсын програм\nLumaShelf программыг 2009 оноос ашиглаж байна.')]
        query = '2028 оны номын сангийн 1800 номын тоо болон лума программыг ашиглаж эхэлсэн оныг хэлнэ үү.'
        question, suggestions = ambiguity(query, sources)
        self.assertIn('лума', question)
        self.assertIn('LumaShelf', question)
        self.assertEqual(suggestions, [query.replace('лума', 'LumaShelf')])
        self.assertIn('2028', suggestions[0])
        self.assertIn('1800', suggestions[0])
        self.assertEqual(query, '2028 оны номын сангийн 1800 номын тоо болон лума программыг ашиглаж эхэлсэн оныг хэлнэ үү.')
        self.assertIsNone(ambiguity(suggestions[0], sources))
        self.assertIsNone(ambiguity(query.replace('лума', 'LumaShelf-гийн'), sources))
        self.assertIsNone(ambiguity(query, [source('Программ ашигладаг тухай ерөнхий мэдээлэл.')]))

    def test_library_generic_programme_wording_does_not_create_an_unknown_name(self):
        sources = [source('Номын сан\nLumaShelf олон улсын програм\nLumaShelf программыг 2009 оноос ашиглаж байна.')]
        for query in ['Номын сангийн номын тоо болон ашигладаг программыг хэзээ нэвтрүүлсэн бэ?',
                      'Номын сангийн номын тоо болон хэрэглэдэг программыг хэзээ нэвтрүүлсэн бэ?',
                      'Номын сангийн номын тоо болон программыг ашиглаж эхэлсэн оныг хэл.']:
            with self.subTest(query=query):
                self.assertIsNone(ambiguity(query, sources))
                requirements = field_evidence_requirements(query)
                self.assertIsNone(next(item for item in requirements if item['type'] == 'software_start_year')['program_name'])

    def test_library_year_intent_does_not_match_conjunction_or_success_word_fragments(self):
        for query in [
            'Номын сангийн номын тоо болон LumaShelf программыг ашиглаж эхэлсэн шалтгааныг тайлбарла.',
            'Номын сангийн номын тоо болон LumaShelf программыг нэвтрүүлсэн амжилтыг тайлбарла.',
        ]:
            with self.subTest(query=query):
                self.assertEqual(field_evidence_requirements(query), [])
        for year_word in ['он', 'онд', 'оны', 'оныг', 'оноос', 'оноор', 'ондоо',
                          'жил', 'жилийн', 'жилд', 'жилдээ', 'хэзээ', 'хэзээнээс']:
            # A genuine date word is explicit even when its inflection changes.
            query = 'Номын сангийн номын тоо болон LumaShelf программыг ашиглаж эхэлсэн ' + year_word + ' хэд вэ?'
            self.assertIn('library_software_start_year', [item['name'] for item in field_evidence_requirements(query)])

    def test_schedule_facets_come_from_two_requested_month_ranges(self):
        query = 'Жилийн ажлын хуваарьт III–IV болон VII–VIII сард ямар ажил төлөвлөсөн бэ?'
        requirements = field_evidence_requirements(query)
        self.assertEqual([item['name'] for item in requirements], ['schedule_months_3_4', 'schedule_months_7_8'])
        schedule = ('ЖИЛИЙН АЖЛЫН ХУВААРЬ\n'
                    '1\nIII–IV сар\nЛабораторийн судалгаа\n'
                    '2\nVII–VIII сар\nҮр дүнгийн хэлэлцүүлэг')
        self.assertEqual(missing_field_evidence(requirements, schedule), [])
        self.assertEqual(missing_field_evidence(requirements, 'Жилийн хуваарь\nIII–IV сар\nЛабораторийн судалгаа'),
                         ['schedule_months_7_8'])
        self.assertEqual(missing_field_evidence(requirements,
            'Жилийн хуваарь\nV–VI сар\nЛабораторийн судалгаа\nIX–X сар\nҮр дүнгийн хэлэлцүүлэг'),
            ['schedule_months_3_4', 'schedule_months_7_8'])

    def test_schedule_dash_variants_and_arabic_equivalents_preserve_requested_months(self):
        requirements = field_evidence_requirements('II—III болон X-XI сарын хуваарьт ямар ажил төлөвлөсөн бэ?')
        for text in [
            'Ажлын хуваарь\nII−III сар\nӨгөгдөл цуглуулалт\nX–XI сар\nТайлангийн бэлтгэл',
            'Ажлын төлөвлөгөө\n2–3-р сар — Өгөгдөл цуглуулалт\n10-11 сар: Тайлангийн бэлтгэл',
            'Хуваарь: II–III сар — Өгөгдөл цуглуулалт\nX–XI сар — Тайлангийн бэлтгэл',
        ]:
            with self.subTest(text=text):
                self.assertEqual(missing_field_evidence(requirements, text), [])

    def test_schedule_requires_same_unit_label_and_substantive_following_task_row(self):
        requirements = field_evidence_requirements('III–IV болон VII–VIII сарын хуваарьт ямар ажил төлөвлөсөн бэ?')
        missing = [item['name'] for item in requirements]
        for text in [
            'III–IV сар\nСудалгааны ажил\nVII–VIII сар\nТайлангийн бэлтгэл',
            'Жилийн хуваарь\nIII–IV сар\n2\nVII–VIII сар\n3',
            'Жилийн хуваарь\nIII–IV сар\nVII–VIII сар',
            'Жилийн хуваарь\nМэдээний огноо\nIII–IV сар\nНийтэлсэн тухай мэдээлэл\nVII–VIII сар\nМэдээний огноо',
            'Жилийн хуваарь\n2031.03.04-нд нийтэлсэн мэдээ.\n2031.07.08-нд хэлэлцүүлэг хийв.',
        ]:
            with self.subTest(text=text):
                self.assertEqual(missing_field_evidence(requirements, text), missing)
        self.assertEqual(missing_field_evidence(requirements,
            ['Жилийн хуваарь', 'III–IV сар\nСудалгааны ажил', 'VII–VIII сар\nТайлангийн бэлтгэл']), missing)

    def test_single_invalid_or_unrequested_month_ranges_do_not_activate_schedule_facets(self):
        for query in [
            'III–IV сард ямар ажил төлөвлөсөн бэ?',
            'III–IV болон III–IV сарын хуваарь юу вэ?',
            'III–IV болон VII–VIII сарын мэдээ хаанаас авах вэ?',
            'III–IV болон VII–VIII дугаар ангийн хуваарь юу вэ?',
            'XII–III болон VII–VIII сарын хуваарьт юу төлөвлөсөн бэ?',
            'Зөвхөн III–IV сарын хуваарийг хэл, VII–VIII хэрэггүй.',
        ]:
            with self.subTest(query=query):
                self.assertEqual(field_evidence_requirements(query), [])

    def test_monitoring_and_evaluation_need_both_local_definitions_and_frequencies(self):
        requirements = field_evidence_requirements('Мониторинг болон үнэлгээний зорилго, давтамжийн ялгаа юу вэ?')
        self.assertEqual([item['name'] for item in requirements],
                         ['monitoring_definition', 'monitoring_frequency', 'evaluation_definition', 'evaluation_frequency'])
        overview = 'Мониторинг ба Үнэлгээ\nДотоод хяналт, үнэлгээний үйл ажиллагаа.'
        monitoring = 'Мониторинг\nӨдөр тутмын үйл ажиллагааны хэрэгжилтийг хянаж, дэмжин зөвлөх зорилготой.'
        evaluation = 'Үнэлгээ\nЗорилтын биелэлтийг тодорхой хугацааны давтамжтай үнэлж, шинэчлэн сайжруулах зорилгоор хийнэ.'
        self.assertEqual(missing_field_evidence(requirements, overview), [item['name'] for item in requirements])
        self.assertEqual(missing_field_evidence(requirements, [overview, monitoring]),
                         ['evaluation_definition', 'evaluation_frequency'])
        self.assertEqual(missing_field_evidence(requirements, [monitoring, evaluation]), [])
        self.assertEqual(missing_field_evidence(requirements, monitoring + '\n' + evaluation), [])

    def test_definition_and_frequency_cannot_leak_from_the_other_subject(self):
        requirements = field_evidence_requirements('Мониторинг ба үнэлгээний зорилго, давтамжийг харьцуул.')
        text = ('Мониторинг\nӨдөр тутам дэмжин зөвлөх зорилготой.\n'
                'Үнэлгээ\nТухай мэдээлэл дараа нэмэгдэнэ.')
        self.assertEqual(missing_field_evidence(requirements, text),
                         ['evaluation_definition', 'evaluation_frequency'])
        text = 'Мониторинг нь өдөр тутам хянах зорилготой.\nҮнэлгээ нь зорилтын биелэлтийг үнэлж сайжруулах зорилготой.'
        self.assertEqual(missing_field_evidence(requirements, text), ['evaluation_frequency'])

    def test_cad_cam_require_local_objective_verbs_instead_of_a_club_or_other_sentence(self):
        requirements = field_evidence_requirements('CAD, Drafter болон CAM-ыг ямар өөр чадвар эзэмшүүлэх зорилттой холбосон бэ?')
        cad = 'CAD програм, Drafter ашиглан эд ангийн зураг төсөл боловсруулах чадварыг эзэмшүүлэх.'
        cam = 'CAM болон тоног төхөөрөмж ашиглан туршилт хийх технологийг эзэмшүүлэх.'
        club = 'CAD CAM клуб\nОюутнуудын үйл ажиллагаа.'
        self.assertEqual(missing_field_evidence(requirements, [club, cad]), ['cam_objective'])
        self.assertEqual(missing_field_evidence(requirements, [cad, cam]), [])
        self.assertIn('cam_objective', missing_field_evidence(requirements,
            'CAM-ийн тухай мэдээлэл. Бусад технологийг эзэмшүүлэх.'))
        self.assertIn('cam_objective', missing_field_evidence(requirements,
            'CAD CAM клуб нь дадлага хийх чадварыг эзэмшүүлэх.'))
        self.assertIn('cam_objective', missing_field_evidence(requirements,
            'CAM ашиглан туршилт хийх технологийг эзэмшүүлэхгүй.'))

    def test_room_and_seat_counts_stay_with_their_own_facility(self):
        requirements = field_evidence_requirements('Ердийн анги танхим болон лабораторийг тус бүр хэдэн өрөө, хэдэн суудалтай гэжээ?')
        classroom = 'Сургалтын анги танхимууд\n18 анги танхим\n540 суудал'
        laboratory = 'Дадлагын лаборатори\n9 лаборатори\n190 суудал'
        self.assertEqual(missing_field_evidence(requirements, [classroom, laboratory]), [])
        missing = missing_field_evidence(requirements, [classroom, 'Лаборатори\n9 лаборатори',
                                                      'Лекцийн танхим\n2 танхим\n190 суудал'])
        self.assertEqual(missing, ['laboratory_seats'])
        self.assertEqual(missing_field_evidence(requirements,
            'Сургалтын анги танхим\n18 өрөө\n540 суудал\nЛаборатори\n9 өрөө'), ['laboratory_seats'])
        self.assertIn('laboratory_seats', missing_field_evidence(requirements,
            'Лаборатори\n9 өрөө\nНомын сан\n190 суудал'))

    def test_labels_and_measurements_in_different_units_are_not_joined(self):
        requirements = field_evidence_requirements('Анги танхим болон лаборатори тус бүр хэдэн өрөө, суудалтай вэ?')
        self.assertEqual(missing_field_evidence(requirements,
            ['Сургалтын анги танхим', '18 өрөө\n540 суудал', 'Лаборатори', '9 өрөө\n190 суудал']),
            [item['name'] for item in requirements])

    def test_named_partner_course_and_job_interview_need_substantive_local_evidence(self):
        requirements = field_evidence_requirements('XYZ компанитай хамтын ажиллагаанд ямар хичээл болон ажлын ярилцлагын ямар явцыг дурдсан бэ?')
        course = 'Мэргэжлийн хичээлийн хөтөлбөрийг сайжруулж, онлайнаар хэрэгжүүлсэн.'
        progress = 'Эхний оюутнууд ажлын ярилцлагад амжилттай оролцсон.'
        self.assertEqual([item['name'] for item in requirements], ['course_content', 'job_interview_progress'])
        self.assertEqual(missing_field_evidence(requirements, [course, 'Ажлын ярилцлага']), ['job_interview_progress'])
        self.assertEqual(missing_field_evidence(requirements, [course, progress]), [])
        self.assertIn('job_interview_progress', missing_field_evidence(requirements,
            ['Ажлын ярилцлагын талаар. Сургуулийн тэмцээнд амжилттай оролцсон.']))

    def test_single_subject_unrelated_attributes_and_explicit_exclusion_do_not_activate(self):
        for query in [
            'Мониторингийн зорилго юу вэ?',
            'Мониторинг ба үнэлгээний тайланг хаанаас авах вэ?',
            'Зөвхөн мониторингийн зорилго хэл; үнэлгээ хэрэггүй.',
            'Мониторинг биш, үнэлгээний зорилгыг хэл.',
            'CAD болон CAM хичээл долоо хоногт хэдэн цаг вэ?',
            'CAD-ийн чадварын зорилтыг хэл; CAM-ыг хас.',
            'Лаборатори болон анги танхим хаана байрладаг вэ?',
            '9-р анги болон лабораторийн суудлын тоог хэл.',
            'SQL хичээл ба элсэлтийн ярилцлага хэдэн цаг вэ?',
        ]:
            with self.subTest(query=query):
                self.assertEqual(field_evidence_requirements(query), [])

    def test_descriptors_are_json_safe_and_contain_no_answer_values(self):
        import json
        query = 'Анги танхим болон лаборатори тус бүр хэдэн өрөө, суудалтай вэ?'
        requirements = field_evidence_requirements(query)
        self.assertEqual(json.loads(json.dumps(requirements)), requirements)
        self.assertNotIn('540', json.dumps(requirements))
        with self.assertRaises(TypeError):
            missing_field_evidence(requirements, [{'text': '18 өрөө'}])


class NewsFacetTests(unittest.TestCase):
    def test_placement_announcement_does_not_cover_levelled_language_and_score_use(self):
        req=field_evidence_requirements('Түвшин тогтоох шалгалтын мэдээнд ямар хэлний хичээлүүд түвшинчилж ордог, математик-физикийн дүнг юунд ашигладаг вэ?')
        self.assertEqual(len(req),3)
        intro='Математик, физик, Герман хэл, Солонгос хэлний түвшин тогтоох шалгалт өгч байна.'
        self.assertEqual(len(missing_field_evidence(req,intro)),3)
        content=['Герман хэл, Солонгос хэлний хичээлүүд түвшинчилж явагддаг.',
                 'Математик, физикийн дүн нь гарааны үнэлгээ болж, хичээл төлөвлөлт, багшийн заах арга, сургалтын хөтөлбөрийн сайжруулалтад ашиглагдана.']
        self.assertEqual(missing_field_evidence(req,content),[])

    def test_beyond_classes_requires_company_or_cultural_activity_not_arrival(self):
        req=field_evidence_requirements('Хөтөлбөрийн мэдээнд инженерийн хичээлээс гадна юу хийсэн бэ?')
        self.assertEqual([r['name'] for r in req],['news_complementary_activities'])
        self.assertTrue(missing_field_evidence(req,'Технологийн коллежид сургалтад хамрагдаад ирлээ.'))
        self.assertEqual(missing_field_evidence(req,'Компани, байгууллагуудын үйл ажиллагаа болон соёл, уламжлалтай танилцлаа.'),[])

    def test_grove_story_needs_site_activity_and_future_plan(self):
        query='«Зуны ногоон аян» мэдээнд хаана ямар төгөл байгуулсан, цаашид ямар уламжлалтай болох вэ?'
        req=field_evidence_requirements(query)
        self.assertEqual(len(req),3)
        intro='Зуны ногоон аяны нээлт боллоо.'
        site='Оюутнууд Зүүн сумын цэцэрлэгт хүрээлэнд "Ирээдүйн төгөл" байгууллаа.'
        plan='Цаашид жил бүр мод тарих уламжлалтай болно.'
        self.assertEqual(len(missing_field_evidence(req,intro)),3)
        self.assertEqual(missing_field_evidence(req,[site,plan]),[])
        self.assertEqual(missing_field_evidence(req,[site]),['news_future_tradition'])

    def test_work_learning_needs_substance_not_encouragement(self):
        req=field_evidence_requirements('«Зуны ажил» мэдээнд хаана ямар ажил хийж, ямар чадвар үнэт зүйлийг мэдэрсэн бэ?')
        self.assertEqual(len(req),3)
        self.assertEqual(missing_field_evidence(req,[
            'Оюутнууд Баруун сумын талбайд жимс хураан ажиллаж байна.',
            'Багаар ажиллах чадвар, хөдөлмөрийн үнэ цэнийг бодитоор мэдэрчээ.']),[])
        self.assertIn('news_work_learning',missing_field_evidence(req,'Оюутнууддаа амжилт хүсье!'))

    def test_quoted_training_requires_content_from_that_training(self):
        req=field_evidence_requirements('Гурав дахь өдрийн мэдээнд «Дижитал чадвар» сургалтаар ямар мэдлэг олгосон бэ?')
        self.assertEqual([r['name'] for r in req],['news_training_content'])
        self.assertEqual(missing_field_evidence(req,'Дижитал чадвар сургалтаар мэдээлэл хамгаалах мэдлэг олгов.'),[])
        self.assertEqual(missing_field_evidence(req,'Сургалтын нээлт. Хажуу өрөөнд механикийн мэдлэг олгов.'),['news_training_content'])
        self.assertEqual(missing_field_evidence(req,'Дижитал чадвар сургалтаар мэдлэг олгоогүй.'),['news_training_content'])

    def test_completed_relations_reject_ordinals_urls_and_other_event_money(self):
        rank='ORBIT 2029 тэмцээний эцсийн дүнгээр NOVA баг ямар байр эзэлсэн бэ?'
        self.assertEqual(requested_detail(rank),'competition_final_rank')
        self.assertTrue(detail_supported('competition_final_rank','ORBIT 2029 тэмцээнд NOVA баг 3-р байр эзэлсэн.',rank))
        for text in ['ORBIT 2029 багууд: 3. NOVA',
                     'ORBIT 2029 тэмцээнд NOVA баг 3-р байр эзлэх төлөвлөгөөтэй.',
                     'ORBIT 2029 тэмцээнд ALPHA баг 3-р байр эзэлсэн.']:
            self.assertFalse(detail_supported('competition_final_rank',text,rank))
        patent='"GreenLoop" төслийн патентын бүртгэлийн дугаар юу вэ?'
        self.assertFalse(detail_supported('patent_registration_identifier','GreenLoop төсөл https://example.invalid/news/999123 хаягтай.',patent))
        fee='Sunny биш «Ур чадвар» богино хугацааны сургалтын нэг оролцогчийн төлбөр хэд вэ?'
        self.assertEqual(requested_detail(fee),'short_training_participant_fee')
        self.assertFalse(detail_supported('short_training_participant_fee','Сургалтын төлбөр жилд 9,000,000 төгрөг.',fee))

    def test_persons_name_prefix_does_not_activate_grove_requirement(self):
        query='2029 оны мэдээнд Б.Төгөлсайхан, О.Төгөлт хоёр ямар амжилт гаргасан бэ?'
        self.assertEqual(field_evidence_requirements(query),[])

    def test_identified_speech_contest_does_not_require_the_unknown_winner_name(self):
        query='Өрнөд мужийн уран илтгэлийн тэмцээнд хэн, хэддүгээр байр эзэлсэн бэ?'
        self.assertIsNone(ambiguity(query,[]))
        self.assertIsNone(requested_detail(query))


if __name__ == '__main__':
    unittest.main()
