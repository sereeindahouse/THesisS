import hashlib
import unittest

from evidence_contract import evidence_units, resolve_evidence_selection


def source(text, cuts):
    return dict(source_id='s', text=text, url='https://nmct.edu.mn/about/test',
                version=1, start_offset=0, end_offset=len(text), text_scope='main_element',
                structure_method='verified-captured-dom-v1', structure_boundaries=cuts,
                structure_text_sha256=hashlib.sha256(text.encode()).hexdigest())


class EvidenceStructureTests(unittest.TestCase):
    def test_separate_statistic_cards_cannot_be_packed_into_event(self):
        stats = '2007\nЭхлэл тавигдсан он\n17\nОнцлох үйл явдал\n'
        event = '2019\nҮүсгэн байгуулагдсан\n09 сарын 12-нд 72 оюутан, 2 бүлэгтэй хичээллэж эхлэв.'
        units = evidence_units([source(stats + event, [len(stats)])])
        chosen = next(u for u in units if '72 оюутан' in u['text'])
        self.assertEqual(chosen['text'], event)
        self.assertNotIn('2007', chosen['text'])
        self.assertEqual(chosen['page_span']['start'], len(stats))
        self.assertEqual(chosen['quote'][chosen['start']:chosen['end']], event)

    def test_facility_card_keeps_total_badge_ratio_software_year_and_conditions(self):
        rooms = '01\nСургалтын өрөө\n02\nЗөвлөгөөний өрөө\n'
        card = ('Номын сан\n2018 оноос программ ашиглаж, нэг оюутанд 4–8 ном ногдоно. '
                'Зөвхөн үнэмлэхтэй оюутан ном авна.\n2800+\nном, сурах бичиг')
        units = evidence_units([source(rooms + card, [len(rooms)])])
        chosen = next(u for u in units if '2800+' in u['text'])
        self.assertEqual(chosen['text'], card)
        self.assertNotIn('Зөвлөгөөний өрөө', chosen['text'])

    def test_new_boundary_does_not_omit_conditional_predecessor(self):
        condition = 'Хэрэв өмнөх шатны шалгалтад тэнцсэн бол дараагийн шатанд оролцоно.\n'
        next_part = 'Ярилцлага\nЗөвхөн урилгатай хүмүүс ярилцлагад орно. Бусад хүн оролцохгүй.'
        units = evidence_units([source(condition + next_part, [len(condition)])])
        self.assertEqual(len(units), 2)
        self.assertEqual(units[1]['context_unit_ids'], [units[0]['unit_id']])
        resolved = resolve_evidence_selection('Ярилцлагад хэн оролцох вэ?',
                                             [units[1]['unit_id']], units)
        self.assertTrue(resolved['accepted'])
        joined = '\n'.join(c['text'] for c in resolved['claims'])
        self.assertIn('өмнөх шатны шалгалтад тэнцсэн', joined)
        self.assertIn('Бусад хүн оролцохгүй', joined)

    def test_large_omitted_predecessor_still_blocks_dependent_unit(self):
        huge = 'Хэрэв ' + 'урьдчилсан болзол ' * 80 + 'биелсэн бол.\n'
        following = 'Тус хөтөлбөрт зөвхөн шалгуур хангасан суралцагч оролцоно.'
        units = evidence_units([source(huge + following, [len(huge)])])
        self.assertEqual(units, [])

    def test_invalid_metadata_uses_original_paragraphs(self):
        text = '2009\nӨмнөх он\n2021\nЭнэ нь нэг бүтэн эхийн өгүүлбэр юм.'
        original = evidence_units([dict(source_id='s', text=text)])
        for cuts, digest, scope in [([2], hashlib.sha256(text.encode()).hexdigest(), 'main_element'),
                                     ([5], '0' * 64, 'main_element'),
                                     ([5], hashlib.sha256(text.encode()).hexdigest(), 'client_tab_field_excerpt'),
                                     ([5, 5], hashlib.sha256(text.encode()).hexdigest(), 'main_element'),
                                     ([True], hashlib.sha256(text.encode()).hexdigest(), 'main_element')]:
            with self.subTest(cuts=cuts, digest=digest, scope=scope):
                row = source(text, cuts)
                row.update(structure_text_sha256=digest, text_scope=scope)
                self.assertEqual([u['text'] for u in evidence_units([row])],
                                 [u['text'] for u in original])

    def test_same_words_at_other_page_positions_remain_separate(self):
        part = 'Тайлбар\nЭнэ хэсэг зөвхөн 2027 онд хэрэгжихээр төлөвлөсөн.'
        text = part + '\n' + part
        units = evidence_units([source(text, [len(part) + 1])])
        self.assertEqual(len(units), 2)
        self.assertNotEqual(units[0]['unit_id'], units[1]['unit_id'])
        self.assertNotEqual(units[0]['page_span'], units[1]['page_span'])


if __name__ == '__main__':
    unittest.main()
