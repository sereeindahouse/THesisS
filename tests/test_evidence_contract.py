import copy
import unittest

from evidence_contract import evidence_units, missing_query_markers, resolve_evidence_selection


def source(text, source_id='one', url='https://example.edu/page'):
    return dict(source_id=source_id, text=text, url=url)


def choose(query, text):
    units = evidence_units([source(text)])
    return resolve_evidence_selection(query, [u['unit_id'] for u in units], units)


class EvidenceContractTests(unittest.TestCase):
    def test_uppercase_acronym_bullets_keep_the_complete_headed_list(self):
        for acronym in ('PQR LLC', 'KLM ХК', 'XYZ НҮТББ'):
            text = ('Туршилтын байгууллагууд:\n• Alpha Ltd\n• Beta Joint\n• ' + acronym
                    + '\nЭдгээр байгууллага нь зохиомол жагсаалтын тайлбар юм.')
            units = evidence_units([source(text)])
            self.assertEqual(len(units), 1)
            self.assertEqual(units[0]['text'], text)
            self.assertEqual(text[units[0]['start']:units[0]['end']], text)
            selected = resolve_evidence_selection('Байгууллагуудыг бүгдийг жагсаана уу.',
                                                 [units[0]['unit_id']], units)
            self.assertTrue(selected['accepted'])
            self.assertEqual(selected['claims'][0]['text'], text)

    def test_period_ending_bullets_do_not_finish_a_list_early(self):
        text = ('Туршилтын хөтөлбөрүүд:\n• Alpha Ltd.\n• beta joint.\n• SIGMA PLC.\n'
                'Тус бүрийн зорилгыг дараа нь дэлгэрүүлэн тайлбарлана.')
        units = evidence_units([source(text)])
        self.assertEqual(len(units), 1)
        self.assertEqual(units[0]['text'], text)
        self.assertTrue(all(name in units[0]['text'] for name in ('Alpha Ltd.', 'beta joint.', 'SIGMA PLC.')))

    def test_real_uppercase_heading_still_ends_a_bullet_list(self):
        text = ('Туршилтын байгууллагууд:\n• Alpha Ltd.\n• SIGMA PLC\n'
                'ХОЛБОО БАРИХ\nДараагийн хэсэгт өөр сэдвийн мэдээлэл байна.')
        units = evidence_units([source(text)])
        self.assertEqual(len(units), 2)
        self.assertEqual(units[0]['text'], 'Туршилтын байгууллагууд:\n• Alpha Ltd.\n• SIGMA PLC')
        self.assertTrue(units[1]['text'].startswith('ХОЛБОО БАРИХ\n'))
        self.assertNotIn('ХОЛБОО БАРИХ', units[0]['text'])
        for unit in units:
            self.assertEqual(text[unit['start']:unit['end']], unit['text'])

    def test_oversized_bullet_list_is_omitted_whole_without_partial_answer(self):
        heading = 'Туршилтын бүрэн жагсаалт:\n'
        items = '\n'.join('• ABC' + str(i) + ' байгууллагын урт туршилтын нэр.' for i in range(8))
        text = heading + items + '\nДАРААГИЙН ХЭСЭГ\nЭнэ бол өөр сэдвийн тусдаа тайлбар юм.'
        units = evidence_units([source(text)], max_characters=110)
        self.assertEqual(len(units), 1)
        self.assertTrue(units[0]['text'].startswith('ДАРААГИЙН ХЭСЭГ'))
        self.assertNotIn('ABC', units[0]['text'])
        self.assertEqual(text[units[0]['start']:units[0]['end']], units[0]['text'])

    def test_inline_bullet_character_is_ordinary_prose_not_a_list_row(self):
        text = ('Энэ өгүүлбэрийн дундах • тэмдэг нь жагсаалтын мөр биш.\n'
                'Дараагийн өгүүлбэр нь тусдаа ердийн тайлбар юм.')
        units = evidence_units([source(text)])
        self.assertEqual(len(units), 2)
        self.assertEqual(units[0]['text'], text.splitlines()[0])
        self.assertEqual(units[1]['text'], text.splitlines()[1])

    def test_trailing_measurement_badge_belongs_to_preceding_prose(self):
        for number, label in (('812.4', 'м² нийт талбай'), ('2840+', 'ном, сурах бичиг'),
                              ('275', 'хүний суудал')):
            text = ('ӨМНӨХ ХЭСЭГ\nЭнэ хэсгийн үндсэн тайлбарыг эх сурвалжид нийтэлсэн байна.\n'
                    + number + '\n' + label + '\n'
                    'ДАРААГИЙН ХЭСЭГ\nЭнэ бол өөр объектын тухай тусдаа тайлбар юм.')
            units = evidence_units([source(text)])
            self.assertTrue(units[0]['text'].endswith(number + '\n' + label))
            self.assertTrue(units[1]['text'].startswith('ДАРААГИЙН ХЭСЭГ'))
            self.assertEqual(text[units[0]['start']:units[0]['end']], units[0]['text'])
            self.assertEqual(''.join(text.split()), ''.join(''.join(u['text'] for u in units).split()))

    def test_numeric_floor_prose_finishes_before_library_badge(self):
        for opening in ('7 давхарт', '12 давхрын', '25 м²'):
            text = ('Номын сан\n' + opening + ' байрлах орчинд уншлагын үйлчилгээг явуулж байна. '
                    'Нэг оюутанд 4.1–8.3 ном ногдож байна.\n'
                    '2840+\nном, сурах бичиг\nСПОРТЫН ТАНХИМ\nСпортын тусдаа танхимыг ашиглаж байна.')
            units = evidence_units([source(text)])
            self.assertTrue(units[0]['text'].endswith('2840+\nном, сурах бичиг'))
            self.assertTrue(units[1]['text'].startswith('СПОРТЫН ТАНХИМ'))

    def test_numeric_requirement_rows_keep_heading_and_conditions(self):
        for label in ('01', '1.', '1)'):
            text = ('ДЭВШИН СУРАЛЦАХ ШААРДЛАГА\n' + label + ' давхрын байрлал нь 25 м² талбайтай. '
                    'Энэ нь шаардлагын мөрийг дуусгах эсвэл гол нөхцөлийг хасах үндэс болохгүй.\n'
                    '02 Дүнгийн голч 3.5-аас багагүй байх\n03 Сахилгын зөрчилгүй байх')
            units = evidence_units([source(text)])
            self.assertEqual(len(units), 1)
            self.assertEqual(units[0]['text'], text)

    def test_numbered_list_and_bare_facility_label_are_not_shifted(self):
        for label in ('Лаборатори', 'Анги танхим', 'Бүртгэлийн алхам', 'Хөтөлбөр'):
            text = ('Өмнөх мэдээллийг тусдаа өгүүлбэрээр тайлбарласан байна.\n'
                    '02\n' + label + '\nДараагийн хөтөлбөрийн тайлбарыг энд өгсөн байна.')
            units = evidence_units([source(text)])
            self.assertNotIn('02', units[0]['text'])
            self.assertTrue(units[1]['text'].startswith('02\n'))

    def test_badge_without_preceding_prose_is_not_shifted(self):
        text = '812.4\nм² нийт талбай\nТанхимын мэдээлэл\nЭнэ бол танхимын тухай үндсэн тайлбар юм.'
        self.assertEqual(evidence_units([source(text)])[0]['text'], text)

    def test_measurement_badge_still_respects_oversized_unit_policy(self):
        text = 'Тайлбар ' + 'өгөгдөл ' * 12 + 'дуусна.\n812.4\nм² нийт талбай\nДараагийн мэдээлэл.'
        units = evidence_units([source(text)], max_characters=120)
        self.assertFalse(any('812.4' in u['text'] for u in units))

    def test_unrelated_area_total_does_not_require_a_book_total_word(self):
        text = ('Номын сан\nНэг оюутанд 4.1–8.3 ном ногдож, 2460 номтой байна.\n'
                + 'Спортын талбайн талаар тусдаа мэдээлэл өгсөн. ' * 4
                + '\nСпортын заалны нийт талбай 801 м² байна.')
        units = evidence_units([source(text)])
        selected = next(u for u in units if '2460' in u['text'])
        result = resolve_evidence_selection('Номын сангийн нийт номын үзүүлэлтийг хэлээрэй.',
                                            [selected['unit_id']], units)
        self.assertTrue(result['accepted'])
        self.assertNotIn('801', result['claims'][0]['text'])

    def test_same_object_total_is_still_required_after_context_filter(self):
        units = evidence_units([source('Нийт 168 оюутан суралцаж байна.\nНэгдүгээр курс 31 оюутантай.')])
        selected = units[-1]
        result = resolve_evidence_selection('Нийт хэдэн оюутан, нэгдүгээр курс хэд вэ?',
                                            [selected['unit_id']], units)
        self.assertFalse(result['accepted'])
        self.assertIn('total', result['missing_markers'])

    def test_objectless_total_keeps_strict_check(self):
        self.assertIn('total', missing_query_markers('Нийт хэд вэ?', '31 оюутан.',
                                                    'Нийт 168 оюутан.\n31 оюутан.'))

    def test_named_section_heading_is_added_to_selected_body(self):
        text = ('ZXQ Research Co., Ltd\nТус байгууллага технологийн чиглэлээр үйл ажиллагаа явуулдаг.\n'
                'Хамтын ажиллагааны хүрээнд 2033 онд гурван хичээлийг онлайнаар хэрэгжүүлсэн.\n'
                'Мөн оюутнууд ярилцлагад амжилттай оролцсон байна.')
        units = evidence_units([source(text)])
        selected = units[-1]
        result = resolve_evidence_selection('ZXQ компанийн гурван хичээл, ярилцлагын явц?',
                                            [selected['unit_id']], units)
        self.assertTrue(result['accepted'])
        self.assertEqual(len(result['named_heading_context_unit_ids']), 1)
        self.assertEqual(len(result['claims']), 3)
        self.assertTrue(result['claims'][0]['text'].startswith('ZXQ Research'))
        self.assertEqual(text[units[0]['start']:units[0]['end']], result['claims'][0]['text'])

    def test_different_nearest_section_heading_blocks_named_context(self):
        text = ('ZXQ Research\nЭнэ байгууллага сургалт явуулдаг.\n'
                'BCD Institute\nӨөр байгууллагын тусдаа хөтөлбөрийг танилцуулсан.\n'
                'Хөтөлбөр 12 хоног үргэлжилдэг.')
        units = evidence_units([source(text)])
        result = resolve_evidence_selection('ZXQ хөтөлбөр хэд хоног вэ?',
                                            [units[-1]['unit_id']], units)
        self.assertFalse(result['accepted'])
        self.assertIn('anchor:zxq', result['missing_markers'])

    def test_long_or_many_word_section_heading_blocks_older_named_context(self):
        headings = [
            'BCD институтын тусдаа мэргэжил дээшлүүлэх сургалтын зохион байгуулалт '
            'болон хамрагдах хүмүүсийн нөхцөлийн дэлгэрэнгүй танилцуулга',
            'BCD one two three four five six seven eight nine',
        ]
        for heading in headings:
            with self.subTest(heading=heading):
                text = ('ZXQ Research\nБайгууллага технологийн судалгаа явуулдаг.\n'
                        + heading + '\nСургалт 19 хоног үргэлжилдэг.')
                units = evidence_units([source(text)])
                result = resolve_evidence_selection('ZXQ сургалт хэд хоног вэ?',
                                                    [units[-1]['unit_id']], units)
                self.assertFalse(result['accepted'])
                self.assertIn('anchor:zxq', result['missing_markers'])

    def test_oversized_omitted_heading_still_blocks_older_named_context(self):
        heading = 'BCD институтын тусдаа сургалтын танилцуулга ' + 'дэлгэрэнгүй ' * 100
        text = ('ZXQ Research\nБайгууллага технологийн судалгаа явуулдаг.\n'
                + heading + '\nСургалт 19 хоног үргэлжилдэг.')
        units = evidence_units([source(text)])
        self.assertFalse(any(heading in unit['text'] for unit in units))
        result = resolve_evidence_selection('ZXQ сургалт хэд хоног вэ?',
                                            [units[-1]['unit_id']], units)
        self.assertFalse(result['accepted'])
        self.assertIn('anchor:zxq', result['missing_markers'])

    def test_selected_long_section_start_cannot_inherit_older_name(self):
        heading = ('BCD институтын тусдаа мэргэжил дээшлүүлэх сургалтын зохион '
                   'байгуулалт болон хамрагдах хүмүүсийн дэлгэрэнгүй танилцуулга')
        text = ('ZXQ Research\nБайгууллага технологийн судалгаа явуулдаг.\n'
                + heading)
        units = evidence_units([source(text)])
        result = resolve_evidence_selection('ZXQ сургалтын танилцуулга?',
                                            [units[-1]['unit_id']], units)
        self.assertFalse(result['accepted'])
        self.assertIn('anchor:zxq', result['missing_markers'])

    def test_company_heading_with_period_remains_valid_local_context(self):
        text = ('ZXQ Research Co., Ltd.\nБайгууллага технологийн судалгаа явуулдаг.\n'
                'Сургалт 19 хоног үргэлжилдэг.')
        units = evidence_units([source(text)])
        result = resolve_evidence_selection('ZXQ сургалт хэд хоног вэ?',
                                            [units[-1]['unit_id']], units)
        self.assertTrue(result['accepted'])
        self.assertEqual(result['claims'][0]['text'], units[0]['text'])
        self.assertEqual(len(result['named_heading_context_unit_ids']), 1)

    def test_named_context_cannot_be_borrowed_from_other_source(self):
        units = evidence_units([source('ZXQ Research\nБайгууллага сургалт явуулдаг.'),
                                source('Хөтөлбөр 12 хоног үргэлжилдэг.', 'other')])
        result = resolve_evidence_selection('ZXQ хөтөлбөр хэд хоног вэ?',
                                            [units[-1]['unit_id']], units)
        self.assertFalse(result['accepted'])
        self.assertIn('anchor:zxq', result['missing_markers'])

    def test_selected_new_section_cannot_inherit_previous_organisation(self):
        for heading in ('BCD Institute', 'Өөр тусдаа хөтөлбөр'):
            units = evidence_units([source('ZXQ Research\nБайгууллага сургалт явуулдаг.\n'
                                          + heading + '\nӨөр сургалт 12 хоног үргэлжилдэг.')])
            result = resolve_evidence_selection('ZXQ сургалт хэд хоног вэ?',
                                                [units[-1]['unit_id']], units)
            self.assertFalse(result['accepted'])
            self.assertIn('anchor:zxq', result['missing_markers'])

    def test_body_latin_mention_cannot_be_inherited_as_heading(self):
        units = evidence_units([source('Энэ мэдээнд ZXQ байгууллагын тухай дурдсан байна.\n'
                                      'Дараагийн тусдаа сургалт 12 хоног үргэлжилдэг.')])
        result = resolve_evidence_selection('ZXQ хөтөлбөр хэд хоног вэ?',
                                            [units[-1]['unit_id']], units)
        self.assertFalse(result['accepted'])
        self.assertIn('anchor:zxq', result['missing_markers'])

    def test_named_context_keeps_claim_and_character_budgets(self):
        units = evidence_units([source('ZXQ Research\nБайгууллага сургалт явуулдаг.\n'
                                      'Сургалт 12 хоног үргэлжилдэг.')])
        selected = [units[-1]['unit_id']]
        self.assertEqual(resolve_evidence_selection('ZXQ сургалт?', selected, units,
                                                    max_claims=1)['reason'],
                         'evidence_context_exceeds_claim_budget')
        self.assertEqual(resolve_evidence_selection('ZXQ сургалт?', selected, units,
                                                    max_characters=30)['reason'],
                         'evidence_selection_exceeds_budget')

    def test_quantity_roles_are_copied_together_with_nonfixture_amounts(self):
        text = ('Хуваарилалт\n2031–2032 оны хичээлийн жилд мэргэжил тус бүрээс 4, '
                'нийт 24 оюутан хамрагдана.')
        result = choose('2031–2032 онд тус бүрээс хэд, нийт хэд вэ?', text)
        self.assertTrue(result['accepted'])
        self.assertEqual(result['claims'][0]['text'], text)
        self.assertNotIn('тус бүрээс 24', result['claims'][0]['text'])

    def test_planned_table_keeps_heading_all_rows_and_no_added_past_tense(self):
        text = ('ЖИЛИЙН ХУВААРЬ\n4, 5-р курсийн оюутнуудад зориулсан хуваарь\n'
                '1\nIX–X сар\nБүртгэл, сонгон шалгаруулалт\n'
                '2\nXI–XII сар\nJLPT/EJU шалгалт, бэлтгэл\n'
                'БУСАД ХӨТӨЛБӨР\nАялал\nАяллын хөтөлбөрийг тусад нь зарлана.')
        units = evidence_units([source(text)])
        table = next(u for u in units if 'IX–X' in u['text'])
        result = resolve_evidence_selection('IX–X болон XI–XII сард ямар ажил төлөвлөсөн бэ?',
                                            [table['unit_id']], units)
        self.assertTrue(result['accepted'])
        self.assertIn('4, 5-р курс', result['claims'][0]['text'])
        self.assertIn('XI–XII', result['claims'][0]['text'])
        self.assertNotIn('явагдсан', result['claims'][0]['text'])
        self.assertNotIn('БУСАД', result['claims'][0]['text'])

    def test_numbered_requirements_keep_path_heading_and_condition(self):
        text = ('Япон коосэнд дэвшин суралцахад тавигдах шаардлагууд\n'
                '01 Сургуулийн үйл ажиллагаанд идэвхтэй оролцдог\n'
                '02 Япон хэлний N2 түвшний мэдлэг, чадвартай\n'
                '03 Ёс зүйн зөрчил гаргаагүй\n'
                'БЭЛТГЭЛ ХӨТӨЛБӨР\nБэлтгэлийг төгсөгчдөд зориулан зохион байгуулдаг.')
        units = evidence_units([source(text)])
        selected = next(u for u in units if 'N2' in u['text'])
        result = resolve_evidence_selection('Коосэнд суралцах япон хэл, ёс зүйн нөхцөл юу вэ?',
                                            [selected['unit_id']], units)
        self.assertTrue(result['accepted'])
        self.assertTrue(result['claims'][0]['text'].startswith('Япон коосэнд'))
        self.assertIn('зөрчил гаргаагүй', result['claims'][0]['text'])

    def test_physical_paragraph_keeps_staff_counts_and_qualifying_sentences(self):
        text = ('Тэнхимийн тухай\nТэнхим 7 үндсэн багш, 2 цагийн багштай. '
                'Үүнээс 3 багш доктор, 6 багш магистр зэрэгтэй.')
        result = choose('Үндсэн ба цагийн багш, доктор ба магистрын тоо хэд вэ?', text)
        self.assertTrue(result['accepted'])
        self.assertEqual(result['claims'][0]['text'], text)

    def test_orphan_list_with_overlap_automatically_adds_scope(self):
        heading = ('Коосэнд дэвшин суралцах шаардлагууд\n'
                   '01 Идэвхтэй оролцоо шаардлагатай\n02 Голч дүн сайн\n'
                   '03 Мэргэжлийн мэдлэг сайн\n04 Япон хэлний N2 түвшний мэдлэгтэй')
        tail = ('03 Мэргэжлийн мэдлэг сайн\n04 Япон хэлний N2 түвшний мэдлэгтэй\n'
                '05 Ёс зүйн зөрчил гаргаагүй\nБЭЛТГЭЛ ХӨТӨЛБӨР\n'
                'Бэлтгэлийн хөтөлбөрийг зохион байгуулдаг.')
        units = evidence_units([source(heading), source(tail, 'two')])
        orphan = next(u for u in units if '05 Ёс' in u['text'])
        result = resolve_evidence_selection('N2 болон ёс зүйн ямар нөхцөлтэй вэ?',
                                            [orphan['unit_id']], units)
        self.assertTrue(result['accepted'])
        self.assertTrue(result['context_expanded'])
        self.assertIn('Коосэнд дэвшин суралцах', result['claims'][0]['text'])
        self.assertIn('05 Ёс', result['claims'][1]['text'])

    def test_orphan_list_without_scope_is_not_selectable(self):
        text = '03 Мэргэжлийн мэдлэг сайн\n04 Япон хэлний N2 түвшний мэдлэгтэй\n05 Ёс зүйн зөрчил гаргаагүй'
        self.assertEqual(evidence_units([source(text)]), [])

    def test_separate_anaphoric_paragraph_keeps_its_subject_context(self):
        units = evidence_units([source('Механикийн тэнхим 142 оюутантай.\nҮүнээс 28 нь нэгдүгээр курст суралцдаг.')])
        selected = units[-1]
        result = resolve_evidence_selection('', [selected['unit_id']], units)
        self.assertTrue(result['accepted'])
        self.assertEqual(len(result['claims']), 2)
        self.assertIn('Механикийн тэнхим', result['claims'][0]['text'])

    def test_explicit_separate_conditional_cannot_be_dropped(self):
        units = evidence_units([source('Хэрэв ярилцлагад тэнцвэл дадлагад оролцох эрх нээгдэнэ.\nДадлага 8–28 хоног үргэлжилнэ.')])
        result = resolve_evidence_selection('', [units[-1]['unit_id']], units)
        self.assertTrue(result['accepted'])
        self.assertIn('тэнцвэл', result['claims'][0]['text'])
        self.assertEqual(len(result['claims']), 2)

    def test_orphan_does_not_borrow_scope_from_other_page(self):
        a = 'Шаардлагууд\n01 Оролцоо сайн\n02 Суралцах чадвар сайн\n03 Мэргэжлийн мэдлэг сайн\n04 Япон хэлний N2 түвшин'
        b = '03 Мэргэжлийн мэдлэг сайн\n04 Япон хэлний N2 түвшин\n05 Ёс зүйн зөрчилгүй'
        units = evidence_units([source(a), source(b, 'two', 'https://example.edu/other')])
        self.assertFalse(any('05 Ёс' in u['text'] for u in units))

    def test_missing_total_is_rejected_even_when_selected_count_is_true(self):
        units = evidence_units([source('Нийт 142 оюутан суралцаж байна.\nI курс 28, V курс 19 оюутантай.')])
        picked = next(u for u in units if 'I курс' in u['text'])
        result = resolve_evidence_selection('Нийт хэд, I ба V курс хэдэн оюутантай вэ?', [picked['unit_id']], units)
        self.assertFalse(result['accepted'])
        self.assertIn('total', result['missing_markers'])

    def test_missing_named_latin_programme_is_rejected_if_available(self):
        units = evidence_units([source('JICA дадлага 8–28 хоног үргэлжилнэ.\nАялал 6 хоног үргэлжилнэ.')])
        travel = next(u for u in units if u['text'].startswith('Аялал'))
        result = resolve_evidence_selection('JICA хөтөлбөр хэд хоног вэ?', [travel['unit_id']], units)
        self.assertFalse(result['accepted'])
        self.assertIn('anchor:jica', result['missing_markers'])

    def test_roman_course_labels_match_source_digits(self):
        self.assertEqual(missing_query_markers('I ба V курс', '1-р курс 28, 5-р курс 19',
                                               '1-р курс 28, 5-р курс 19'), [])

    def test_per_course_table_does_not_require_repeating_per_group_wording(self):
        selected = 'Нийт 142 оюутан.\n1-р курс 28 оюутан\n5-р курс 19 оюутан'
        self.assertEqual(missing_query_markers('I ба V курс тус бүр хэд, нийт хэд вэ?', selected,
                                               selected + '\nМэргэжил тус бүр 4 оюутантай.'), [])

    def test_unit_ids_are_deterministic_and_source_bound(self):
        first = evidence_units([source('Мэргэжил бүрээс 4, нийт 24 оюутан хамрагдана.')])
        self.assertEqual(first, evidence_units([source(first[0]['text'])]))
        other = evidence_units([source(first[0]['text'], 'other')])
        self.assertNotEqual(first[0]['unit_id'], other[0]['unit_id'])

    def test_offsets_reproduce_unicode_source_without_rewriting(self):
        text = '  НЭГДҮГЭЭР ХЭСЭГ\n\tНөхцөл хангавал 24 оюутан хамрагдана.\n\nДараагийн тайлбар байна.'
        for unit in evidence_units([source(text)]):
            self.assertEqual(text[unit['start']:unit['end']], unit['text'])

    def test_fabricated_free_text_id_and_duplicate_ids_rejected(self):
        units = evidence_units([source('Нийт 24 оюутан хамрагдана.')])
        self.assertEqual(resolve_evidence_selection('', ['Нийт 99 оюутан'], units)['reason'], 'unknown_evidence_unit')
        sid = units[0]['unit_id']
        self.assertEqual(resolve_evidence_selection('', [sid, sid], units)['reason'], 'duplicate_evidence_selection')

    def test_tampered_text_or_offsets_rejected(self):
        units = evidence_units([source('Мэргэжил бүрээс 4, нийт 24 оюутан хамрагдана.')])
        altered = copy.deepcopy(units)
        altered[0]['text'] = 'Мэргэжил бүрээс 24 оюутан хамрагдана.'
        self.assertEqual(resolve_evidence_selection('', [units[0]['unit_id']], altered)['reason'], 'invalid_evidence_unit')

    def test_long_paragraph_is_omitted_without_truncation(self):
        self.assertEqual(evidence_units([source('Нөхцөл ' + 'тайлбар ' * 150 + 'эцэслэнэ.')]), [])

    def test_total_budget_rejects_instead_of_silently_omitting_a_claim(self):
        units = evidence_units([source('Нийт 24 оюутан хамрагдана.\nДадлага 8–28 хоног үргэлжилнэ.')])
        result = resolve_evidence_selection('', [u['unit_id'] for u in units], units, max_characters=25)
        self.assertEqual(result['reason'], 'evidence_selection_exceeds_budget')

    def test_paired_zero_template_prefix_is_trimmed_at_exact_source_offset(self):
        text = ('Тэнхим\nТэнхимийн нэр\n0 хөтөлбөр\n0 багш\n'
                '0 хөтөлбөр\n0 багш\nТэнхимийн тухай\nТэнхим 7 үндсэн, 2 цагийн багштай.\n'
                'Дадлагын хугацаа 8–28 хоног байна.')
        units = evidence_units([source(text)])
        self.assertEqual(units[0]['text'], 'Тэнхимийн тухай\nТэнхим 7 үндсэн, 2 цагийн багштай.')
        self.assertEqual(text[units[0]['start']:units[0]['end']], units[0]['text'])
        original = evidence_units([source('Тэнхимийн тухай\nТэнхим 7 үндсэн, 2 цагийн багштай.\n'
                                          'Дадлагын хугацаа 8–28 хоног байна.')])
        self.assertEqual(units[1]['text'], original[1]['text'])
        self.assertEqual(resolve_evidence_selection('', [units[0]['unit_id']], units)['accepted'], True)

    def test_valid_or_unpaired_zero_values_and_body_counters_are_retained(self):
        samples = [
            'Төлбөр\n0 төгрөг\nЭнэ бүртгэлийн үйлчилгээ үнэ төлбөргүй байна.',
            'Тэнхим\n0 багш\nНэмэлт мэдээллийг дараа нь нийтэлнэ.',
            'Тэнхим\n0 хөтөлбөр\n2 багш\nНэмэлт мэдээллийг дараа нь нийтэлнэ.',
            'Тэнхим\n1 хөтөлбөр\n0 багш\nНэмэлт мэдээллийг дараа нь нийтэлнэ.',
            'Тэнхим\nБүртгэл 0 хөтөлбөр, 0 багш гэж тэмдэглэгдсэн байна.',
        ]
        for text in samples:
            with self.subTest(text=text):
                self.assertEqual(evidence_units([source(text)])[0]['text'], text)
        text = 'Энэ нь баталгаажсан тоон мэдээллийн хүснэгт юм.\n0 хөтөлбөр\n0 багш\nНэмэлт тайлбарыг энд нийтэлсэн.'
        units = evidence_units([source(text)])
        self.assertIn('0 хөтөлбөр\n0 багш', '\n'.join(u['text'] for u in units))

    def test_publication_year_context_keeps_later_start_year_distinct(self):
        text = ('ТЭТГЭЛГИЙН МЭДЭЭ\n2031 оны есдүгээр сарын 23 48 үзсэн\n'
                'Тэтгэлгийн мэдээллийг нийтэлсэн байна.\n'
                'Тэтгэлэг 2032 оны 4 дүгээр сараас эхлэн төгстөл олгогдоно.')
        units = evidence_units([source(text)])
        answer = next(u for u in units if '2032' in u['text'])
        result = resolve_evidence_selection('2031 оны мэдээнд эхлэх хугацааг юу гэж зарласан бэ?',
                                            [answer['unit_id']], units)
        self.assertTrue(result['accepted'])
        self.assertEqual(len(result['publication_context_unit_ids']), 1)
        self.assertIn('2031 оны есдүгээр сарын 23', result['claims'][0]['text'])
        self.assertEqual(result['claims'][1]['text'], answer['text'])
        self.assertEqual(text[units[0]['start']:units[0]['end']], result['claims'][0]['text'])

    def test_publication_context_cannot_borrow_date_from_different_source(self):
        units = evidence_units([source('Дадлага 2032 онд эхэлнэ.'),
                                source('МЭДЭЭ\n2031 оны есдүгээр сарын 23\nТэтгэлгийн мэдээллийг нийтэлсэн.', 'other')])
        result = resolve_evidence_selection('2031 оны мэдээний эхлэх хугацаа?', [units[0]['unit_id']], units)
        self.assertFalse(result['accepted'])
        self.assertIn('anchor:2031', result['missing_markers'])

    def test_body_year_or_body_date_cannot_replace_publication_date(self):
        for prefix in ('Энэ хөтөлбөр 2031 онд эхэлсэн байна.',
                       'Мэдээний тайлбарыг энд нийтэлсэн байна.\n2031 оны есдүгээр сарын 23\nҮйл ажиллагаа зохион байгуулсан.'):
            units = evidence_units([source(prefix + '\nТэтгэлэг 2032 онд эхэлнэ.')])
            answer = next(u for u in units if u['text'] == 'Тэтгэлэг 2032 онд эхэлнэ.')
            result = resolve_evidence_selection('2031 оны мэдээнд юу гэжээ?', [answer['unit_id']], units)
            self.assertFalse(result['accepted'])
            self.assertIn('anchor:2031', result['missing_markers'])

    def test_publication_context_keeps_other_numeric_anchor_and_budget_checks(self):
        text = ('ТЭТГЭЛГИЙН МЭДЭЭ\n2031 оны есдүгээр сарын 23\n'
                'Мэдээ нийтлэгдсэн байна.\nТэтгэлэг 2032 онд эхэлнэ.\nДадлага IX–X сард үргэлжилнэ.')
        units = evidence_units([source(text)])
        answer = next(u for u in units if u['text'] == 'Тэтгэлэг 2032 онд эхэлнэ.')
        result = resolve_evidence_selection('2031 оны IX–X сарын хуваарь?', [answer['unit_id']], units)
        self.assertFalse(result['accepted'])
        self.assertIn('anchor:9', result['missing_markers'])
        result = resolve_evidence_selection('2031 оны мэдээ?', [answer['unit_id']], units, max_characters=35)
        self.assertEqual(result['reason'], 'evidence_selection_exceeds_budget')
        result = resolve_evidence_selection('2031 оны мэдээ?', [answer['unit_id']], units, max_claims=1)
        self.assertEqual(result['reason'], 'evidence_context_exceeds_claim_budget')


class PhysicalPredecessorFilteringTests(unittest.TestCase):
    """Invented paragraphs: dependency safety, not empirical school facts."""
    first = 'OMEGA Research\nOMEGA хөтөлбөрийн үндсэн чиглэлийг энд танилцуулсан.'
    second = 'DELTA Research\nDELTA хөтөлбөрийн үндсэн чиглэлийг энд танилцуулсан.'
    tail = 'Мөн энэ хөтөлбөрийн дадлага 43 хоног үргэлжилдэг.'

    def test_oversized_physical_predecessor_cannot_link_tail_to_older_subject(self):
        middle = 'DELTA Research\n' + 'Өөр хөтөлбөрийн дэлгэрэнгүй мэдээллийг тусад нь тайлбарласан болно. ' * 22
        self.assertGreater(len(middle), 900)
        text = self.first + '\n' + middle + '\n' + self.tail
        rows = evidence_units([source(text)])
        self.assertEqual([row['text'] for row in rows], [self.first])
        self.assertFalse(any('43 хоног' in row['text'] for row in rows))
        for row in rows:
            self.assertEqual(row['quote'][row['start']:row['end']], row['text'])

    def test_short_or_template_paragraph_remains_a_dependency_boundary(self):
        for omitted in ('X.', 'Шаблон.', 'Template.'):
            with self.subTest(omitted=omitted):
                rows = evidence_units([source(self.first + '\n' + omitted + '\n' + self.tail)])
                self.assertEqual([row['text'] for row in rows], [self.first])

    def test_whitespace_only_gap_keeps_immediate_retained_continuation(self):
        text = self.first + '\n\n  \n\t' + self.tail
        rows = evidence_units([source(text)])
        self.assertEqual(rows[-1]['context_unit_ids'], [rows[0]['unit_id']])
        value = resolve_evidence_selection('OMEGA хөтөлбөрийн дадлага хэд хоног вэ?',
                                            [rows[-1]['unit_id']], rows)
        self.assertTrue(value['accepted'])
        self.assertEqual([claim['text'] for claim in value['claims']], [self.first, self.tail])

    def test_retained_new_subject_is_the_predecessor_not_older_subject(self):
        rows = evidence_units([source(self.first + '\n' + self.second + '\n' + self.tail)])
        self.assertEqual(rows[-1]['context_unit_ids'], [rows[1]['unit_id']])
        wrong = resolve_evidence_selection('OMEGA хөтөлбөрийн дадлага хэд хоног вэ?',
                                            [rows[-1]['unit_id']], rows)
        right = resolve_evidence_selection('DELTA хөтөлбөрийн дадлага хэд хоног вэ?',
                                            [rows[-1]['unit_id']], rows)
        self.assertFalse(wrong['accepted'])
        self.assertTrue(right['accepted'])
        self.assertEqual([claim['text'] for claim in right['claims']], [self.second, self.tail])

    def test_source_change_never_inherits_previous_source_even_for_same_url(self):
        for url in ('https://example.edu/page', 'https://example.edu/other'):
            with self.subTest(url=url):
                rows = evidence_units([source(self.first), source(self.tail, 'two', url)])
                self.assertEqual(rows[-1]['context_unit_ids'], [])
                value = resolve_evidence_selection('OMEGA хөтөлбөрийн дадлага хэд хоног вэ?',
                                                    [rows[-1]['unit_id']], rows)
                self.assertFalse(value['accepted'])

    def test_omitted_conditional_cannot_leave_an_unqualified_following_claim(self):
        condition = 'Хэрэв оролцогч шаардлага хангавал ' + 'нэмэлт нөхцөлүүдийг тусад нь нягтална. ' * 30
        following = 'Оролцогч 87 нэгжийн дэмжлэг авах боломжтой.'
        rows = evidence_units([source(self.first + '\n' + condition + '\n' + following)])
        self.assertEqual([row['text'] for row in rows], [self.first])

    def test_dropped_dependent_chain_stops_at_new_independent_paragraph(self):
        middle = 'DELTA Research\n' + 'Өөр хөтөлбөрийн тухай дэлгэрэнгүй тайлбарласан болно. ' * 24
        independent = 'SIGMA хөтөлбөрийн сургалт 61 хоног үргэлжилдэг.'
        next_tail = 'Мөн тухайн хөтөлбөрийн дадлага 19 хоног үргэлжилдэг.'
        rows = evidence_units([source(self.first + '\n' + middle + '\n' + self.tail + '\n'
                                     + 'Үүнээс 7 хоногийг бэлтгэлд зарцуулдаг.' + '\n'
                                     + independent + '\n' + next_tail)])
        self.assertEqual([row['text'] for row in rows], [self.first, independent, next_tail])
        self.assertEqual(rows[-1]['context_unit_ids'], [rows[1]['unit_id']])

    def test_trimmed_initial_template_does_not_break_retained_following_context(self):
        explanation = 'Энэ хэсэгт судалгааны хөтөлбөрийн бодит тайлбарыг нийтэлсэн байна.'
        text = '0 хөтөлбөр\n0 багш\n' + explanation + '\n' + self.tail
        rows = evidence_units([source(text)])
        self.assertEqual([row['text'] for row in rows], [explanation, self.tail])
        self.assertEqual(rows[-1]['context_unit_ids'], [rows[0]['unit_id']])


if __name__ == '__main__':
    unittest.main()
