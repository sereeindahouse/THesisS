"""Constructed structural controls, not empirical school facts or human gold."""
import unittest

from evidence_contract import direction_card_bindings, evidence_units
from source_fields import field_evidence_requirements, missing_field_evidence


def units(text, budget=900):
    return evidence_units([dict(source_id='constructed', text=text, url='https://example.org/test')], max_characters=budget)


class StructureContextTests(unittest.TestCase):
    flow_query = 'Хоёр урсгалын чиглэл ба нэрийг тус тус хэлнэ үү.'
    flow_a = 'Доороос дээш\nСанал нэгтгэх\nАжилтнаас удирдлагад хүрэх оролцоонд суурилсан урсгал.'
    flow_b = 'Дээрээс доош\nДэмжлэг үзүүлэх\nУдирдлагаас ажилтанд хүрэх зөвлөгөө, чиглүүлгийн урсгал.'
    intro = 'Үйл ажиллагаа нь хоёр чиглэлд суурилсан бүтэцтэй хэрэгжинэ.'
    course_query = 'ZXQ компанийн гурван хичээлийг нэрлэж, ямар хэлбэрээр хэрэгжүүлснийг хэлнэ үү.'
    heading = 'ZXQ Co., Ltd\nZXQ компани нь сургалтын үйлчилгээний чиглэлээр үйл ажиллагаа явуулдаг байгууллага юм.'
    course = 'Тэнхим нь тус компанитай хамтран “Сорил А”, “Сорил Б”, “Сорил В” гэсэн гурван хичээлийг онлайнаар хэрэгжүүлсэн.'

    def missing(self, query, texts):
        return missing_field_evidence(field_evidence_requirements(query), texts)

    def test_flow_pair_requires_both_physical_direction_name_bindings(self):
        self.assertTrue(self.missing(self.flow_query, [self.flow_a]))
        self.assertFalse(self.missing(self.flow_query, [self.flow_a + '\n' + self.flow_b]))

    def test_flow_names_without_directions_do_not_fill_the_pair(self):
        self.assertTrue(self.missing(self.flow_query, ['Санал нэгтгэх ба дэмжлэг үзүүлэх гэсэн хоёр урсгалтай.']))

    def test_duplicate_direction_is_not_two_flows(self):
        self.assertTrue(self.missing(self.flow_query, [self.flow_a + '\n' + self.flow_a]))

    def test_direction_without_name_and_description_is_not_a_binding(self):
        self.assertEqual(direction_card_bindings('Доороос дээш\nДээрээс доош'), [])

    def test_negated_direction_description_does_not_supply_a_positive_binding(self):
        negated = self.flow_a.replace('суурилсан урсгал.', 'суурилсан урсгал биш.')
        self.assertTrue(self.missing(self.flow_query, [negated + '\n' + self.flow_b]))

    def test_flow_units_remain_exact_contiguous_source_spans(self):
        text = self.intro + '\n' + self.flow_a + '\n' + self.flow_b
        rows = units(text)
        self.assertTrue(any(not self.missing(self.flow_query, [row['text']]) for row in rows))
        for row in rows:
            self.assertEqual(text[row['start']:row['end']], row['text'])

    def test_oversize_flow_pair_is_not_truncated_to_a_claim(self):
        text = self.intro + '\n' + self.flow_a + '\n' + self.flow_b
        self.assertFalse(any(not self.missing(self.flow_query, [row['text']]) for row in units(text, 80)))

    def test_same_company_heading_attaches_to_immediate_pronoun_paragraph(self):
        rows = units(self.heading + '\n' + self.course)
        self.assertTrue(any(not self.missing(self.course_query, [row['text']]) for row in rows))

    def test_another_company_prefix_cannot_inherit_previous_company(self):
        text = self.heading + '\n' + self.course.replace('Тэнхим нь', 'OTHER компани нь')
        self.assertFalse(any(not self.missing(self.course_query, [row['text']]) for row in units(text)))

    def test_intervening_heading_blocks_company_pronoun_merge(self):
        text = self.heading + '\nӨӨР БАЙГУУЛЛАГА\n' + self.course
        self.assertFalse(any(not self.missing(self.course_query, [row['text']]) for row in units(text)))

    def test_course_form_from_another_unit_cannot_fill_names_only(self):
        a = self.heading + '\n' + self.course.replace('онлайнаар', '')
        b = 'OTHER Co., Ltd\n' + self.course
        self.assertTrue(self.missing(self.course_query, [a, b]))

    def test_course_count_must_match_explicit_question(self):
        text = self.heading + '\n' + self.course.replace('“Сорил В”', 'ерөнхий сургалт')
        self.assertTrue(self.missing(self.course_query, [text]))

    def test_negated_course_mode_does_not_count_as_completed_delivery(self):
        text = self.heading + '\n' + self.course.replace('хэрэгжүүлсэн.', 'хэрэгжүүлээгүй.')
        self.assertTrue(self.missing(self.course_query, [text]))

    def test_online_registration_does_not_supply_course_delivery_form(self):
        text = self.heading + '\n' + self.course.replace('онлайнаар хэрэгжүүлсэн.', 'хэрэгжүүлсэн бөгөөд бүртгэлийг онлайнаар явуулсан.')
        self.assertTrue(self.missing(self.course_query, [text]))

    def test_flow_or_course_name_only_query_adds_no_new_field(self):
        for query in ['Хоёр урсгалын нэрийг хэлнэ үү.', 'ZXQ компанийн гурван хичээлийг нэрлэнэ үү.']:
            self.assertEqual(field_evidence_requirements(query), [])


if __name__ == '__main__':
    unittest.main()
