import copy
import unittest

from evidence_contract import evidence_units, missing_query_markers, resolve_evidence_selection


def source(text, source_id='one', url='https://example.edu/page'):
    return dict(source_id=source_id, text=text, url=url)


def choose(query, text):
    units = evidence_units([source(text)])
    return resolve_evidence_selection(query, [u['unit_id'] for u in units], units)


class EvidenceContractTests(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
