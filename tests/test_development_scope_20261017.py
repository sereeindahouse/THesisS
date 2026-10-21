"""Development regressions after the preserved independent 24-case first run.

Synthetic names, dates and values exercise scope mechanisms, not school gold.
"""
import copy
import unittest

from rag_runtime import ChatRAG, source_extract, year_evidence_sources
from source_fields import ambiguity, department_evidence_sources, detail_supported, requested_detail
from test_rag_runtime import SOURCE, Policy, Retriever, Generator


def source(text, *, name='synthetic-main', title='Туршилтын эх', visual=False, url=None):
    return dict(copy.deepcopy(SOURCE), source_id=name, text=text, excerpt=text, title=title,
                url=url or 'https://nmct.edu.mn/synthetic/' + name,
                text_scope='document_visual_excerpt' if visual else 'main_element')


class CapturingGenerator(Generator):
    def generate(self, query, sources):
        self.calls += 1
        self.sources = copy.deepcopy(sources)
        first = sources[0]
        return dict(generated=True, llm_calls=1, reason='synthetic',
                    claims=[dict(source_id=first['source_id'], text=first['text'], quote=first['text'])])


def chat_result(query, sources):
    retriever, generator = Retriever(), CapturingGenerator()
    retriever.sources = sources
    return ChatRAG('.', Policy(), retriever, generator).route(None, query), generator


class ComplementaryYearEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.first = source('2018 онд туршилтын лаборатори нээгдэв.', name='first')
        self.second = source('2022 онд шинэ цахим систем нэвтрүүлэв.', name='second')

    def test_separate_historical_questions_can_use_complementary_passages(self):
        values = [self.first, self.second]
        self.assertEqual(year_evidence_sources('2018 онд юу нээсэн, 2022 онд юу нэвтрүүлсэн бэ?', values), values)

    def test_one_missing_requested_year_rejects_the_entire_request(self):
        self.assertEqual(year_evidence_sources('2018 ба 2027 онд юу болсон бэ?', [self.first, self.second]), [])

    def test_academic_year_interval_cannot_be_assembled_from_unrelated_endpoints(self):
        self.assertEqual(year_evidence_sources('2018–2022 оны хөтөлбөр?', [self.first, self.second]), [])
        combined = source('2018–2022 оны хөтөлбөр хэрэгжив.')
        self.assertEqual(year_evidence_sources('2018–2022 оны хөтөлбөр?', [combined]), [combined])

    def test_route_does_not_false_abstain_before_generator_on_separate_years(self):
        result, generator = chat_result('2018 онд юу нээсэн, 2022 онд юу нэвтрүүлсэн бэ?', [self.first, self.second])
        self.assertEqual(result['route'], 'C')
        self.assertEqual(generator.sources, [self.first, self.second])


class DepartmentAndReferentTests(unittest.TestCase):
    def setUp(self):
        self.target = source('Туршилтын тэнхим асуудлыг шийдвэрлэх чадвартай инженер бэлтгэнэ.',
                             title='Фотоник инженерийн тэнхим', name='target')
        self.other = source('Өөр тэнхимийн дадлага нь үйлдвэрлэлийн чадвар олгоно.',
                            title='Материалын инженерийн тэнхим', name='other')

    def test_named_department_mission_cannot_select_other_departments_claims(self):
        question = 'Фотоник инженерийн тэнхимийн зорилгод ямар чадвар онцолсон бэ?'
        result, generator = chat_result(question, [self.target, self.other])
        self.assertEqual(result['route'], 'C')
        self.assertEqual(generator.sources, [self.target])
        self.assertNotIn(self.other['text'], result['answer'])

    def test_client_field_suffix_is_not_part_of_department_identity(self):
        tab = dict(self.target, source_id='target-tab', title=self.target['title'] + ' — goalsJson')
        values = [tab, self.other]
        self.assertEqual(department_evidence_sources('Фотоник инженерийн тэнхимийн зорилт?', values, all_attributes=True), [tab])

    def test_explicit_department_comparison_preserves_both(self):
        values = [self.target, self.other]
        self.assertIs(department_evidence_sources('Фотоник болон материалын тэнхимийн зорилгыг харьцуул.', values, all_attributes=True), values)

    def test_bare_staff_count_asks_department_before_any_generator_call(self):
        values = [dict(self.target, text='Тэнхим нь 7 багштай.'), dict(self.other, text='Тэнхим нь 3 багштай.')]
        result, generator = chat_result('Тэнхим нь хэдэн багштай вэ?', values)
        self.assertEqual(result['route'], 'D')
        self.assertIn('Аль тэнхим', result['message'])
        self.assertEqual(generator.calls, 0)

    def test_named_staff_count_remains_answerable(self):
        self.assertIsNone(ambiguity('Фотоник инженерийн тэнхим хэдэн багштай вэ?', [self.target, self.other]))

    def test_staff_role_words_do_not_identify_an_unnamed_department(self):
        value = dict(self.target, text='Тэнхим нь 7 үндсэн багштай.')
        self.assertIsNotNone(ambiguity('Тэнхим нийт хэдэн үндсэн багштай вэ?', [value]))

    def test_cost_coverage_is_an_attribute_not_a_scholarship_name(self):
        scholarship = source('Орион тэтгэлэг сургалтын болон амьжиргааны бүх зардлыг даадаг.')
        result, generator = chat_result('Энэ тэтгэлэг сургалт, амьжиргааны бүх зардлыг даах уу?', [scholarship])
        self.assertEqual(result['route'], 'D')
        self.assertIn('Аль тэтгэлэг', result['message'])
        self.assertEqual(generator.calls, 0)

    def test_literal_scholarship_name_prevents_unnecessary_clarification(self):
        scholarship = source('Орион тэтгэлэг сургалтын болон амьжиргааны бүх зардлыг даадаг.')
        self.assertIsNone(ambiguity('Орион тэтгэлэг бүх зардлыг даах уу?', [scholarship]))


class UnsupportedAttributeTests(unittest.TestCase):
    def test_library_book_quantity_range_is_not_an_opening_time(self):
        self.assertNotEqual(requested_detail('Номын сан Koha программыг хэдэн оноос ашигласан, нэг оюутанд хэдээс хэдэн ном ногддог вэ?'), 'library_opening_hours')

    def test_library_hours_cannot_be_replaced_with_stock_or_general_office_hours(self):
        question = 'Номын сан ням гарагт хэдээс хэд хүртэл ажилладаг вэ?'
        self.assertEqual(requested_detail(question), 'library_opening_hours')
        values = [source('Номын сан 900 номтой.'), source('Ажлын цаг\nНям: 10:00 - 14:00.', name='office')]
        result, generator = chat_result(question, values)
        self.assertEqual(result['reason_code'], 'requested_attribute_not_supported')
        self.assertEqual(generator.calls, 0)

    def test_explicit_library_day_and_hours_are_supported(self):
        text = 'Номын сан ням гарагт 11:00 - 15:00 нээлттэй.'
        self.assertTrue(detail_supported('library_opening_hours', text, 'Номын сан ням гарагт хэдээс ажилладаг вэ?'))
        self.assertFalse(detail_supported('library_opening_hours', text, 'Номын сан бямба гарагт хэдээс ажилладаг вэ?'))

    def test_library_heading_can_own_adjacent_schedule_rows(self):
        self.assertTrue(detail_supported('library_opening_hours', 'Номын сан\nДаваа - Баасан: 09:00 - 17:00.', 'Номын сан мягмар гарагт хэдээс ажилладаг вэ?'))
        self.assertFalse(detail_supported('library_opening_hours', 'Номын сан\nДаваа - Баасан: 09:00 - 17:00.', 'Номын сан ням гарагт хэдээс ажилладаг вэ?'))

    def test_library_day_cannot_borrow_another_day_or_facility_hours(self):
        query = 'Номын сан ням гарагт хэдээс ажилладаг вэ?'
        self.assertFalse(detail_supported('library_opening_hours', 'Номын сан\nНям: тодорхойгүй\nДаваа: 09:00 - 17:00.', query))
        self.assertFalse(detail_supported('library_opening_hours', 'Номын сан\nСпорт заал\nНям: 10:00 - 14:00.', query))
        self.assertTrue(detail_supported('library_opening_hours', 'Номын сан\nНям: Амарна\nДаваа: 09:00 - 17:00.', query))

    def test_unknown_equipment_identity_is_not_general_inventory(self):
        question = 'CNC машины үйлдвэрлэгч ба яг загварын дугаар юу вэ?'
        self.assertEqual(requested_detail(question), 'equipment_identity')
        result, generator = chat_result(question, [source('Лабораторид CNC, токарь, фрезер ашигладаг.')])
        self.assertEqual(result['reason_code'], 'requested_attribute_not_supported')
        self.assertEqual(generator.calls, 0)

    def test_equipment_identity_requires_all_requested_labels(self):
        question = 'CNC машины үйлдвэрлэгч ба загварын дугаар юу вэ?'
        self.assertFalse(detail_supported('equipment_identity', 'CNC машины үйлдвэрлэгч нь Орион.', question))
        self.assertFalse(detail_supported('equipment_identity', 'CNC машин 2024 онд авсан, загвар тодорхойгүй.', question))
        self.assertTrue(detail_supported('equipment_identity', 'CNC машины үйлдвэрлэгч нь Орион, загварын дугаар ZX-42.', question))


class ContractConsequenceTests(unittest.TestCase):
    def setUp(self):
        self.expiry = source('Элсэх эрх авсан боловч хүндэтгэх шалтгаангүйгээр заасан хугацаанд ирж суралцах гэрээ байгуулаагүй элсэгчийг суралцахаас татгалзсан хэмээн үзэж элсэх эрхийн бичгийг хүчингүйд тооцно. Энэ тохиолдолд элсэлтийн шалгалтын оноогоор дараагийн шалгуулагчид мэдэгдэн, түүний хүсэлтийг үндэслэн элсүүлж болно.', visual=True, name='expiry')
        self.confirmation = source('Элсэгч сургуулиас товлосон хугацаанд суралцах гэрээ байгуулан, сургалтын төлбөрийг төлсний дараа элсэн суралцах баталгаажна.', visual=True, name='confirmation')
        self.question = 'Элсэх эрх авсан хүн гэрээ байгуулах хугацаандаа хүндэтгэх шалтгаангүй ирээгүй бол яах вэ? Дараагийн шалгуулагчийг заавал элсүүлэх үү?'

    def test_consequence_selects_actual_clause_even_after_generic_confirmation(self):
        self.assertEqual(source_extract(self.question, [self.confirmation, self.expiry]), (self.expiry, self.expiry['text']))

    def test_confirmation_alone_cannot_answer_contract_expiry(self):
        self.assertIsNone(source_extract(self.question, [self.confirmation]))
        result, generator = chat_result(self.question, [self.confirmation])
        self.assertEqual(result['reason_code'], 'requested_attribute_not_supported')
        self.assertEqual(generator.calls, 0)

    def test_condition_and_permissive_next_applicant_modality_are_preserved(self):
        result, generator = chat_result(self.question, [self.expiry, self.confirmation])
        self.assertEqual(result['route'], 'A')
        self.assertIn('хүндэтгэх шалтгаангүйгээр', result['answer'])
        self.assertIn('түүний хүсэлтийг үндэслэн элсүүлж болно', result['answer'])
        self.assertEqual(generator.calls, 0)

    def test_excused_absence_is_not_unexcused_absence(self):
        question = 'Элсэх эрх авсан хүн хүндэтгэх шалтгаантай боловч гэрээ байгуулаагүй бол яах вэ?'
        self.assertFalse(detail_supported('enrollment_contract_consequence', self.expiry['text'], question))


if __name__ == '__main__':
    unittest.main()
