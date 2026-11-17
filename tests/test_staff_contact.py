"""11/17 (3): a teacher-contact request is answered with the published school e-mail list,
or a clarifying question that offers each department's list; plain wordings of stored lists."""
import unittest

from rag_runtime import common_question_alias, school_scope_sources
from source_fields import staff_query_scope

EMAILS = dict(source_id='e1', title='Химийн инженерийн тэнхим — teachers', url='https://nmct.edu.mn/departments/chemical',
              content_scope='department_teacher_roster', source_locator='Flight /teachers/emails',
              text='Химийн инженерийн тэнхим — багш, ажилтны сургуулийн имэйл (сайтад нийтэлсэн)\n'
                   'Багш: Туршилт\nИмэйл: fake.teacher@nmct.edu.mn')
ROSTER = dict(EMAILS, source_id='r1', source_locator='Flight /teachers/roster',
              text='Химийн инженерийн тэнхим — сайтад нийтэлсэн багш, ажилтан (1 нэр): Туршилт (багш).')
PAGE = dict(source_id='p1', title='Химийн инженерийн тэнхим', url='https://nmct.edu.mn/departments/chemical',
            text='Нүүр Тэнхимүүд Химийн инженерийн тэнхим\nТэнхим')


class StaffContactTests(unittest.TestCase):
    catalog = [PAGE, ROSTER, EMAILS]

    def test_working_hours_and_degree_wordings(self):
        # 11/17 (5): at the reception desk a subjectless question is about the school.
        for query in ('Хэдэн цагт ажилладаг вэ?', 'Та нар хэдэн цагаас хэдэн цаг хүртэл ажилладаг вэ?',
                      'Сургууль хэдэн цагт ажилладаг вэ?'):
            self.assertEqual(common_question_alias(query), 'Сургуулийн ерөнхий ажлын цаг хэд вэ?')
        self.assertIsNone(common_question_alias('Номын сан хэдэн цагт ажилладаг вэ?'))
        self.assertEqual(common_question_alias('Төгсөхөд ямар зэрэг авах вэ?'),
                         '2026 оны элсэлтийн хөтөлбөр хэдэн жил үргэлжлэх вэ?')
        # Round 6: transfer into the 2nd year and «how many majors» -> the stored programme list.
        for query in ('2-р курст шилжиж орж болох уу?', 'Шилжилтийн хөтөлбөрт ямар мэргэжил байдаг вэ?',
                      'Хэдэн мэргэжлээр элсүүлдэг вэ?'):
            self.assertEqual(common_question_alias(query), '2026 оны элсэлтээр ямар мэргэжлүүдэд элсэлт авах гэж жагсаасан бэ?')
        self.assertIsNone(common_question_alias('Шилжих хүсэлт хаана өгөх вэ?'))

    def test_event_participant_count_is_not_a_staff_question(self):
        # 11/17 (5): «намрын ажилд хэдэн багш оролцсон» is a news item's figure, not a roster.
        self.assertIsNone(staff_query_scope('2026 оны намрын ажилд хэдэн багш оролцсон бэ?', [PAGE],
                                            catalog=self.catalog))
        self.assertIsNotNone(staff_query_scope('Химийн инженерийн тэнхимд хэдэн багш ажилладаг вэ?', [PAGE],
                                               catalog=self.catalog))

    def test_unnamed_teacher_contact_asks_which_department(self):
        for query in ('Багштай яаж холбогдох вэ?', 'Багшийн имэйл хаяг авч болох уу?',
                      'Хүүхдийнхээ багштай холбогдмоор байна'):
            with self.subTest(query=query):
                scope = staff_query_scope(query, [PAGE], catalog=self.catalog)
                self.assertEqual(scope['stop'], 'clarify_staff_contact')
                self.assertIsNone(scope['person'])
                self.assertEqual(scope['suggestions'], ['Химийн инженерийн тэнхимийн багш нарын имэйл'])

    def test_named_department_contact_uses_its_published_email_list(self):
        scope = staff_query_scope('Химийн инженерийн тэнхимийн багштай яаж холбогдох вэ?', [PAGE], catalog=self.catalog)
        self.assertEqual(scope['kind'], 'contact')
        self.assertNotIn('stop', scope)
        self.assertEqual([source['source_id'] for source in scope['sources']], ['e1'])

    def test_names_question_still_uses_the_roster(self):
        scope = staff_query_scope('Химийн инженерийн тэнхимийн багш нар хэн хэн бэ?', [PAGE], catalog=self.catalog)
        self.assertEqual(scope['kind'], 'names')
        self.assertEqual([source['source_id'] for source in scope['sources']], ['r1'])


class StoredListWordingTests(unittest.TestCase):
    def test_programme_and_department_lists(self):
        programmes = '2026 оны элсэлтээр ямар мэргэжлүүдэд элсэлт авах гэж жагсаасан бэ?'
        for query in ('Ямар мэргэжлээр элсүүлдэг вэ?', 'Ямар ямар мэргэжил байдаг вэ?',
                      'Сургууль ямар хөтөлбөрөөр элсэлт авдаг вэ?'):
            with self.subTest(query=query):
                self.assertEqual(common_question_alias(query), programmes)
        self.assertEqual(common_question_alias('Ямар тэнхимүүд байдаг вэ?'), 'Сургууль ямар тэнхимүүдтэй вэ?')
        self.assertIsNone(common_question_alias('Ямар мэргэжлийн багш нар байдаг вэ?'))

    def test_school_mission_drops_department_pages(self):
        about = dict(source_id='a', url='https://nmct.edu.mn/about', text='Эрхэм зорилго\n...')
        department = dict(source_id='d', url='https://nmct.edu.mn/departments/general-department', text='Эрхэм зорилго\n...')
        self.assertEqual(school_scope_sources('Сургуулийн эрхэм зорилго юу вэ?', [department, about]), [about])
        self.assertEqual(school_scope_sources('Ерөнхий эрдмийн тэнхимийн эрхэм зорилго юу вэ?', [department, about]),
                         [department, about])
        self.assertEqual(school_scope_sources('Сургуулийн эрхэм зорилго юу вэ?', [department]), [department])
        # Review 11/17: a programme's own vision keeps its programme pages.
        programme = dict(source_id='g', url='https://nmct.edu.mn/programs/x', text='Алсын хараа\n...')
        self.assertEqual(school_scope_sources('Програм хангамжийн хөтөлбөрийн алсын хараа юу вэ?', [programme, about]),
                         [programme, about])

    def test_unresolved_class_code_is_not_asked_for_again(self):
        scope = staff_query_scope('КУ-2 ангийн багштай яаж холбогдох вэ?', [PAGE], catalog=StaffContactTests.catalog)
        self.assertEqual(scope['stop'], 'clarify_staff_contact')
        self.assertNotIn('жишээ нь КУ-2', scope['message'])

    def test_phone_request_says_phones_are_not_shown(self):
        scope = staff_query_scope('Багшийн утасны дугаар хэд вэ?', [PAGE], catalog=StaffContactTests.catalog)
        self.assertIn('утасны дугаарыг энд харуулахгүй', scope['message'])


if __name__ == '__main__':
    unittest.main()
