"""Constructed student-table controls; numbers are fixtures, not school facts."""
import unittest

from evidence_contract import exact_field_units, resolve_evidence_selection
from source_fields import followup_field_request, structured_field_extract


YEAR = '2031–2032'
TITLE = 'Роботик инженерийн тэнхим'
BASE_QUERY = f'{YEAR} онд роботикийн тэнхимийн курс бүрт хэдэн оюутан байна вэ?'


def table(counts=(11, 13, 17, 19, 19), year=YEAR, title=TITLE,
          identifier='constructed-robotics', version=1):
    text = ('Оюутны тоо\n'
            f'{year} оны хичээлийн жилд нийт {sum(counts)} оюутан суралцаж байна. Үүнээс:\n'
            + ''.join(f'{grade}-р курс {count} оюутан\n'
                      for grade, count in enumerate(counts, 1))
            + 'Мэргэжлийн клубийн үйл ажиллагаанд 23 оюутан хамрагдаж байна.\n'
              'Хөгжлийн чиглэл\nСургалтын орчныг сайжруулна.')
    return dict(source_id=identifier, title=title, text=text,
                url='https://nmct.edu.mn/departments/' + identifier,
                version=version, text_scope='main_element',
                start_offset=0, end_offset=len(text))


def selected(plan):
    return '\n'.join(part['source']['text'][part['start']:part['end']]
                     for part in plan['parts'])


class CourseQuestionVariantsTests(unittest.TestCase):
    def test_distribution_question_without_total_keeps_every_course(self):
        source = table()
        request = followup_field_request(BASE_QUERY)
        self.assertIsNotNone(request)
        self.assertEqual(request['kind'], 'department_student_table')
        self.assertTrue(request['all_courses'])
        plan = structured_field_extract(BASE_QUERY, [source])
        self.assertIsNotNone(plan)
        text = selected(plan)
        for grade, count in enumerate((11, 13, 17, 19, 19), 1):
            self.assertIn(f'{grade}-р курс {count} оюутан', text)
        self.assertIn(YEAR, text)
        self.assertIn('нийт 79', text)  # Source context and integrity, not a supplied answer.
        self.assertNotIn('клуб', text.casefold())
        self.assertNotIn('23 оюутан', text)

    def test_real_query_wording_uses_different_constructed_values(self):
        query = '2025–2026 онд механикийн тэнхимийн курс бүрт хэдэн оюутан байна вэ?'
        source = table((7, 8, 9, 10), year='2025–2026', title='Механик инженерийн тэнхим')
        plan = structured_field_extract(query, [source])
        self.assertIsNotNone(plan)
        text = selected(plan)
        self.assertIn('нийт 34', text)
        for grade, count in enumerate((7, 8, 9, 10), 1):
            self.assertIn(f'{grade}-р курс {count} оюутан', text)
        self.assertNotIn('5-р курс', text)
        self.assertNotIn('128', text)

    def test_case_variants_keep_the_same_bounded_distribution_request(self):
        queries = (
            BASE_QUERY,
            f'{YEAR} оны роботикийн тэнхимд курс тус бүрт хэдэн оюутан байна вэ?',
            f'Роботикийн тэнхимийн {YEAR} оны курс бүрийн оюутны тоог хэлж өгөөч.',
            f'{YEAR} онд роботик инженерийн тэнхимийн курсын тус бүрийн оюутны тоог хэлнэ үү.',
            f'{YEAR} оны роботикийн тэнхимийн нийт суралцагч, курс тус бүрийн тоог хэлж өгөөч.',
        )
        for query in queries:
            with self.subTest(query=query):
                plan = structured_field_extract(query, [table()])
                self.assertIsNotNone(plan)
                self.assertIn('5-р курс 19 оюутан', selected(plan))

    def test_selected_spans_resolve_through_the_unchanged_evidence_contract(self):
        source = table()
        plan = structured_field_extract(BASE_QUERY, [source])
        self.assertIsNotNone(plan)
        units = exact_field_units(plan['parts'])
        result = resolve_evidence_selection(BASE_QUERY, [u['unit_id'] for u in units], units)
        self.assertTrue(result['accepted'], result)
        self.assertTrue(all(claim['text'] in source['text'] for claim in result['claims']))
        self.assertIn('5-р курс 19 оюутан', '\n'.join(c['text'] for c in result['claims']))

    def test_named_department_and_year_are_not_borrowed_from_nearby_tables(self):
        source = table()
        for query in (BASE_QUERY.replace('роботикийн', 'химийн'),
                      BASE_QUERY.replace(YEAR, '2032–2033'),
                      BASE_QUERY.replace('роботикийн', 'роботикийн болон химийн')):
            with self.subTest(query=query):
                self.assertIsNone(structured_field_extract(query, [source]))
        other = table((3, 4, 5), title='Химийн инженерийн тэнхим', identifier='constructed-chemical')
        plan = structured_field_extract(BASE_QUERY, [other, source])
        self.assertIsNotNone(plan)
        self.assertTrue(all(p['source']['source_id'] == source['source_id'] for p in plan['parts']))

    def test_extra_constraints_negation_and_numbers_do_not_disappear(self):
        queries = (
            BASE_QUERY.replace('хэдэн', 'зөвхөн хэдэн'),
            BASE_QUERY.replace('роботикийн', 'роботикийн биш'),
            BASE_QUERY.replace('байна', 'байхгүй'),
            'Хэрэв би тэнцвэл ' + BASE_QUERY,
            BASE_QUERY + ' Мөн клубийн оюутны тоог хэл.',
            BASE_QUERY.replace('курс бүрт', '2-р курс бүрт'),
            BASE_QUERY.replace('хэдэн', 'эмэгтэй хэдэн'),
            BASE_QUERY.replace('оюутан', 'оюутан болон багш'),
            BASE_QUERY.replace('онд', 'онд 2034 онд'),
        )
        for query in queries:
            with self.subTest(query=query):
                self.assertIsNone(structured_field_extract(query, [table()]))

    def test_missing_identity_year_or_count_role_is_not_a_closed_table_request(self):
        for query in (BASE_QUERY.replace(YEAR + ' онд ', ''),
                      BASE_QUERY.replace('роботикийн тэнхимийн ', ''),
                      f'{YEAR} оны роботикийн тэнхимийн курс бүрийн талаар хэл.',
                      f'{YEAR} оны роботикийн тэнхимийн курс бүрийн тоо?',
                      f'{YEAR} оны роботикийн тэнхимийн курс бүрт хэдэн багш байна вэ?',
                      f'{YEAR} онд роботикийн тэнхимийн оюутан хэд байна вэ?',
                      BASE_QUERY.replace(YEAR, '2032–2031')):
            with self.subTest(query=query):
                self.assertIsNone(structured_field_extract(query, [table()]))

    def test_broken_conflicting_or_incomplete_source_still_fails_closed(self):
        base = table()
        for text in (base['text'].replace('нийт 79', 'нийт 80'),
                     base['text'].replace('3-р курс 17 оюутан\n', ''),
                     base['text'].split('Мэргэжлийн клубийн')[0].rstrip(),
                     base['text'].replace('Мэргэжлийн клубийн', 'Зөвхөн тэнцсэн тохиолдолд Мэргэжлийн клубийн'),
                     'Хуучин 2029 оны хүснэгт\n' + base['text']):
            source = dict(base, text=text, end_offset=len(text))
            with self.subTest(text=text):
                self.assertIsNone(structured_field_extract(BASE_QUERY, [source]))
        other = table((12, 13, 17, 19, 19), identifier='conflicting')
        self.assertIsNone(structured_field_extract(BASE_QUERY, [base, other]))


if __name__ == '__main__':
    unittest.main()
